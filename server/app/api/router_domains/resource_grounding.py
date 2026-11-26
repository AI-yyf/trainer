"""Grounded resource contract verification, automatic library lookup, and first-look persistence."""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

from ...core.models import (
    FirstLookSummary,
    ResourceComposerIntent,
    ResourceRecord,
    SessionMessageRequest,
    TurnRequest,
    WorkbenchSnapshot,
    WorkspaceUnderstandingSnapshot,
)
from ...llm.prompts import infer_coaching_scenario as infer_message_coaching_scenario
from ...resources.research_brief import BriefPassage, brief_passages, preparation_for_active_stage
from ...workspace.classifier import (
    classify_heuristic,
)
from .._helpers import (
    normalized_object_mapping,
    prefers_chinese,
)
from .._singleflight import (
    claim_session_request_singleflight as claim_session_request_singleflight,
)
from .._singleflight import (
    fail_session_request_singleflight as fail_session_request_singleflight,
)
from .._singleflight import (
    publish_session_request_singleflight as publish_session_request_singleflight,
)
from ..router_support import (
    _attach_requested_workspace_files as _attach_requested_workspace_files,
)
from ..router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from ..router_support import (
    _resolve_agent_loop_enabled as _resolve_agent_loop_enabled,
)
from ..router_support import (
    overlay_session_response_honesty_stamps as overlay_session_response_honesty_stamps,
)
from ..router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from ._base import RouterDomainBase
from .constants import (
    GUIDED_SEQUENCE_SCENARIOS,
)


class ResourceGroundingDomainMixin(RouterDomainBase):
    """Grounded resource contract verification, automatic library lookup, and first-look persistence."""

    def resource_reply_mentions_promise(self, reply: str) -> bool:
        lowered = str(reply or "").lower()
        if "first viewport promise" in lowered or "first viewport" in lowered:
            return True
        return any(token in reply for token in ("首屏", "第一视口")) and any(
            token in reply for token in ("承诺", "promise")
        )

    def resource_reply_mentions_boundary(self, reply: str) -> bool:
        lowered = str(reply or "").lower()
        if "must not become" in lowered or "raw filesystem browser" in lowered:
            return True
        has_boundary = any(
            token in reply
            for token in ("绝不能", "不能变成", "不能成为", "不应该变成", "不能退化成", "不能退化为")
        )
        has_target = any(
            token in lowered for token in ("raw filesystem browser", "filesystem browser", "cms")
        ) or any(token in reply for token in ("文件系统浏览器", "原始文件系统浏览器", "CMS"))
        return has_boundary and has_target

    def grounded_resource_contract_needs_repair(self, 
        reply: str,
        *,
        coach_context: dict[str, object] | None,
    ) -> bool:
        if not isinstance(coach_context, dict):
            return False
        if self.coach_context_scenario_value(coach_context) != "principle":
            return False
        raw_facets = coach_context.get("resource_question_facets")
        facets = {
            str(item or "").strip().casefold()
            for item in raw_facets
            if str(item or "").strip()
        } if isinstance(raw_facets, list) else set()
        if not facets:
            return False
        if "first viewport promise" in facets and not self.resource_reply_mentions_promise(reply):
            return True
        if "must not become" in facets and not self.resource_reply_mentions_boundary(reply):
            return True
        return False

    def normalize_resource_contract_source_text(self, value: object) -> str:
        text = str(value or "").replace("\r\n", "\n").strip()
        if not text:
            return ""
        text = re.sub(r"</?mark>", "", text, flags=re.IGNORECASE)
        return text

    def ordered_resource_contract_candidates(self, 
        workspace_id: str,
        *,
        agent_meta: dict[str, object] | None,
    ) -> list[ResourceRecord]:
        resources = self.runtime.resource_service.repository.list_resources(workspace_id)
        if not resources:
            return []
        by_id = {item.id: item for item in resources}
        by_title = {item.name.strip().lower(): item for item in resources if item.name.strip()}
        ordered: list[ResourceRecord] = []
        seen_ids: set[str] = set()

        tool_events = agent_meta.get("tool_events") if isinstance(agent_meta, dict) else None
        for event in tool_events if isinstance(tool_events, list) else []:
            if not isinstance(event, dict):
                continue
            event_name = str(event.get("name") or "").strip()
            if event_name not in {"library_read", "search_resources", "read_resource_excerpt"}:
                continue
            result_payload = event.get("result")
            if not isinstance(result_payload, dict):
                continue
            action = str(result_payload.get("action") or "").strip().lower()
            if event_name == "read_resource_excerpt" or (
                event_name == "library_read" and action == "excerpt"
            ):
                res_obj = result_payload.get("resource")
                if isinstance(res_obj, dict):
                    res_id = str(res_obj.get("id") or "").strip()
                    record = by_id.get(res_id)
                    if record is not None and record.id not in seen_ids:
                        seen_ids.add(record.id)
                        ordered.append(record)
                continue
            if event_name == "library_read" and action not in {"", "search"}:
                continue
            hits = result_payload.get("hits")
            if not isinstance(hits, list):
                continue
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                resource_id = str(hit.get("resource_id") or hit.get("id") or "").strip()
                title_key = str(hit.get("title") or "").strip().lower()
                record = by_id.get(resource_id) or by_title.get(title_key)
                if record is None or record.id in seen_ids:
                    continue
                seen_ids.add(record.id)
                ordered.append(record)
        for record in resources:
            if record.id in seen_ids:
                continue
            seen_ids.add(record.id)
            ordered.append(record)
        return ordered[:6]

    def load_resource_record_text(self, resource: ResourceRecord) -> str:
        raw_paths = (
            resource.sandbox_path,
            resource.extracted_artifact_path,
            resource.canonical_source,
            resource.source,
        )
        for raw_path in raw_paths:
            path_text = str(raw_path or "").strip()
            if not path_text or re.match(r"^[a-z]+://", path_text, re.IGNORECASE):
                continue
            try:
                path = Path(path_text).expanduser()
            except OSError:
                continue
            if not path.exists() or not path.is_file():
                continue
            try:
                return path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                try:
                    return path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
            except OSError:
                continue
        fragments: list[str] = []
        for fragment in resource.knowledge_fragments[:6]:
            if not isinstance(fragment, dict):
                continue
            for key in ("snippet", "summary", "evidence_summary"):
                candidate = self.normalize_resource_contract_source_text(fragment.get(key))
                if candidate and candidate not in fragments:
                    fragments.append(candidate)
        return "\n\n".join(fragments)

    def extract_view_contract_section(self, text: str, *, view_name: str | None) -> str:
        normalized = self.normalize_resource_contract_source_text(text)
        if not normalized:
            return ""
        if not view_name:
            return normalized
        for depth in ("###", "##", "#"):
            match = re.search(
                rf"(?ims)^{re.escape(depth)}\s+[^\n]*\b{re.escape(view_name)}\b[^\n]*\n(?P<body>.*?)(?=^{re.escape(depth)}\s+|^\#\s+|\Z)",
                normalized,
            )
            if match:
                return str(match.group("body") or "").strip()
        return normalized

    def extract_labelled_contract_block(self, section_text: str, label: str) -> str:
        normalized = self.normalize_resource_contract_source_text(section_text)
        if not normalized:
            return ""
        match = re.search(
            rf"(?ims)^\s*(?:[-*]\s*)?{re.escape(label)}\s*:\s*(?P<body>.*?)(?=^\s*(?:[-*]\s*)?(?:First viewport promise|Must provide|Must not become)\s*:|^\s*###\s+|^\s*##\s+|\Z)",
            normalized,
        )
        return str(match.group("body") or "").strip() if match else ""

    def resource_contract_items(self, block_text: str) -> list[str]:
        normalized = self.normalize_resource_contract_source_text(block_text)
        if not normalized:
            return []
        items: list[str] = []
        for line in normalized.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("-", "*")):
                item = re.sub(r"[ .;,]+$", "", stripped[1:].strip())
                if item:
                    items.append(item)
                continue
            if not items:
                items.append(re.sub(r"[ .;,]+$", "", stripped))
        return items

    def extract_view_contract_details(self, 
        text: str,
        *,
        view_name: str | None,
    ) -> tuple[str, list[str]]:
        section_text = self.extract_view_contract_section(text, view_name=view_name)
        promise_items = self.resource_contract_items(
            self.extract_labelled_contract_block(section_text, "First viewport promise")
        )
        boundary_items = self.resource_contract_items(
            self.extract_labelled_contract_block(section_text, "Must not become")
        )
        promise_text = promise_items[0] if promise_items else ""
        return promise_text, boundary_items

    def localize_resource_contract_item(self, text: str, *, response_language: str | None) -> str:
        cleaned = re.sub(r"[ .;,]+$", "", str(text or "").strip())
        if not cleaned:
            return ""
        if not prefers_chinese(response_language):
            return cleaned
        lowered = cleaned.casefold()
        replacements = {
            "the learner can find, trust, preview, and convert resources without losing provenance": "让学习者在不丢失 provenance 的前提下找到、信任、预览并转化资料",
            "a cms": "CMS",
            "a raw filesystem browser": "raw filesystem browser",
            "a place that writes into user project code by surprise": "会悄悄写入用户项目代码的地方",
        }
        return replacements.get(lowered, cleaned)

    def join_visible_contract_items(self, items: list[str], *, response_language: str | None) -> str:
        cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if prefers_chinese(response_language):
            if len(cleaned) == 2:
                return f"{cleaned[0]} 或 {cleaned[1]}"
            return f"{'、'.join(cleaned[:-1])}，或 {cleaned[-1]}"
        if len(cleaned) == 2:
            return f"{cleaned[0]} or {cleaned[1]}"
        return f"{', '.join(cleaned[:-1])}, or {cleaned[-1]}"

    def punctuate_visible_contract_line(self, text: str, *, response_language: str | None) -> str:
        cleaned = re.sub(r"[ .;,。；]+$", "", str(text or "").strip())
        if not cleaned:
            return ""
        return f"{cleaned}{'。' if prefers_chinese(response_language) else '.'}"

    def build_grounded_resource_contract_visible_fallback(self, 
        *,
        workspace_id: str,
        coach_context: dict[str, object] | None,
        agent_meta: dict[str, object] | None,
        response_language: str | None,
    ) -> dict[str, str] | None:
        if not isinstance(coach_context, dict):
            return None
        raw_facets = coach_context.get("resource_question_facets")
        if not isinstance(raw_facets, list) or not raw_facets:
            return None
        view_name = next(
            (
                facet
                for facet in raw_facets
                if str(facet or "").strip() in {"Coach", "Plan", "Resources", "Training", "Settings"}
            ),
            None,
        )
        promise_text = ""
        boundary_items: list[str] = []
        for resource in self.ordered_resource_contract_candidates(workspace_id, agent_meta=agent_meta):
            source_text = self.load_resource_record_text(resource)
            if not source_text:
                continue
            promise_text, boundary_items = self.extract_view_contract_details(
                source_text,
                view_name=str(view_name or "").strip() or None,
            )
            if promise_text or boundary_items:
                break
        if not promise_text and not boundary_items:
            return None

        localized_promise = self.punctuate_visible_contract_line(
            self.localize_resource_contract_item(promise_text, response_language=response_language),
            response_language=response_language,
        )
        localized_boundary_items = [
            self.localize_resource_contract_item(item, response_language=response_language)
            for item in boundary_items[:3]
        ]
        boundary_visible = self.join_visible_contract_items(
            localized_boundary_items,
            response_language=response_language,
        )
        localized_view_name = str(view_name or "this view").strip() or "this view"

        if prefers_chinese(response_language):
            lines = ["我先直接按当前资料命中的 contract 回答：", ""]
            if localized_promise:
                lines.append(f"- `first viewport promise`：{localized_promise}")
            if boundary_visible:
                lines.append(f"- `must not become`：不能变成 {self.punctuate_visible_contract_line(boundary_visible, response_language=response_language)}")
            lines.extend(
                [
                    "",
                    f"下一步我可以把这两条 contract 变成一个可验证 checklist，再回到 {localized_view_name} 视图逐项核对。",
                ]
            )
            summary = f"先按资料把 {localized_view_name} 的 contract 直接答清，再决定是否扩展。"
            next_step = f"把这两条 contract 变成 checklist，再回到 {localized_view_name} 视图逐项核对。"
            teaching_note = "当 grounded resource turn 漂移时，先用已命中的资料 contract 修正可见回答。"
        else:
            lines = ["I will answer directly from the grounded library contract first:", ""]
            if localized_promise:
                lines.append(f"- `first viewport promise`: {localized_promise}")
            if boundary_visible:
                lines.append(
                    f"- `must not become`: {self.punctuate_visible_contract_line(boundary_visible, response_language=response_language)}"
                )
            lines.extend(
                [
                    "",
                    f"Next I can turn these two contract lines into a verifiable checklist and walk back through the {localized_view_name} view.",
                ]
            )
            summary = f"Answer the grounded {localized_view_name} contract directly before widening."
            next_step = (
                f"Turn these two contract lines into a checklist and verify them in the {localized_view_name} view."
            )
            teaching_note = (
                "When a grounded resource turn drifts, repair the visible answer from the retrieved contract first."
            )
        reply = "\n".join(lines).strip()
        resume_thread = self.build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
        return {
            "reply": reply,
            "summary": summary,
            "next_step": next_step,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
        }

    def requested_resource_context(self, 
        workspace_id: str,
        resource_ids: list[str] | None,
    ) -> dict[str, object]:
        if not resource_ids:
            return {}
        ids = list(resource_ids)
        # Just-in-time teaching digestion: the learner pointed the coach at
        # these materials, so each gets digested (总结/预备题目/直观案例) once
        # per content version — fire-and-forget, never blocking the turn, and
        # never a blanket sweep over the whole library.
        self.runtime.request_resource_digestion(workspace_id, ids)
        return self.runtime.resource_service.build_requested_resource_context(workspace_id, ids)

    def request_resource_ids(self, request: TurnRequest | SessionMessageRequest) -> list[str]:
        # Composer IDs describe a Resources search scope, not attached materials.
        return list(request.resource_ids)

    def resource_composer_context(self, 
        intent: ResourceComposerIntent | None,
    ) -> dict[str, object]:
        if intent is None:
            return {}
        return {
            "resource_composer_intent": {
                "mode": intent.mode,
                "resource_ids": list(intent.resource_ids),
            }
        }

    def workspace_understanding_resource_context(self, 
        workspace_id: str,
        resource_ids: list[str] | None,
    ) -> dict[str, object]:
        if not resource_ids:
            return {}
        return self.runtime.resource_service.build_workspace_understanding_context(workspace_id, list(resource_ids))

    def message_deserves_library_first_lookup(self, message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        explicit_markers = (
            "search my resources",
            "search the resources",
            "search my library",
            "search the library",
            "search my notes",
            "search my uploads",
            "look in my resources",
            "look in my library",
            "资料库",
            "资源库",
            "我的资料",
            "我的资源",
            "上传的资料",
            "搜索资料",
            "搜索我的资料",
            "搜索资料库",
            "搜索我的资料库",
        )
        if any(marker in lowered for marker in explicit_markers):
            return True
        teaching_markers = (
            "teach me",
            "explain",
            "walk me through",
            "help me understand",
            "tell me",
            "why does",
            "how do i",
            "what is",
            "remote",
            "ssh",
            "debug",
            "breakpoint",
            "api",
            "protocol",
            "function",
            "signature help",
            "hover",
            "教我",
            "解释",
            "讲解",
            "告诉我",
            "为什么",
            "怎么",
            "如何",
            "远程",
            "调试",
            "断点",
            "函数",
            "协议",
        )
        if any(marker in lowered for marker in teaching_markers):
            return True
        import_markers = (
            "imported",
            "uploaded",
            "indexed",
            "just imported",
            "just uploaded",
            "导入",
            "上传",
            "索引",
        )
        document_markers = (
            "design doc",
            "design document",
            "design spec",
            "spec",
            "specification",
            "view contract",
            "documentation",
            "document",
            "markdown",
            "设计文档",
            "设计规范",
            "规范文档",
            "文档",
        )
        view_markers = (
            "coach view",
            "plan view",
            "resources view",
            "training view",
            "settings view",
            "coach 视图",
            "plan 视图",
            "resources 视图",
            "training 视图",
            "settings 视图",
            "对话视图",
            "计划视图",
            "资料视图",
            "资源视图",
            "训练视图",
            "设置视图",
            "first viewport",
            "viewport promise",
            "首屏",
            "承诺",
        )
        references_imported_material = any(marker in lowered for marker in import_markers) and any(
            marker in lowered for marker in (*document_markers, *view_markers)
        )
        discusses_doc_contract = any(marker in lowered for marker in document_markers) and any(
            marker in lowered for marker in view_markers
        )
        return references_imported_material or discusses_doc_contract

    def message_deserves_library_probe(self, message: str | None) -> bool:
        """Broader gate for the cheap automatic library probe.

        Focus-hint and lane decisions keep using the strict teaching-marker
        heuristic above. This probe only decides whether one local search is
        cheap enough to run; it must not change the turn's scenario or focus.
        """
        if self.message_deserves_library_first_lookup(message):
            return True
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        skip_markers = (
            "thanks",
            "thank you",
            "ok",
            "okay",
            "got it",
            "continue",
            "next",
            "status",
            "what's next",
            "what is next",
            "how is it going",
            "谢谢",
            "好的",
            "收到",
            "继续",
            "下一步",
            "状态",
            "怎么样",
        )
        if any(marker in lowered for marker in skip_markers):
            return False
        if "?" in lowered or "？" in lowered:
            return True
        cjk_chars = len(re.findall(r"[\u3400-\u9fff]", lowered))
        return cjk_chars >= 6 or len(lowered.split()) >= 5

    def coach_context_has_prepared_library_grounding(self, 
        coach_context: dict[str, object] | None,
    ) -> bool:
        if not isinstance(coach_context, dict):
            return False
        resource_fragments = coach_context.get("resource_fragments")
        if isinstance(resource_fragments, list) and resource_fragments:
            return True
        requested_resources = coach_context.get("requested_resources")
        if isinstance(requested_resources, list) and requested_resources:
            return True
        if coach_context.get("auto_resource_lookup") is True:
            return bool(self.auto_resource_lookup_tool_events(coach_context, None))
        return False

    def resource_grounding_turn_prefers_fresh_lane(self, 
        message: str | None,
        grounding_context: dict[str, object] | None,
    ) -> bool:
        if self.message_requests_lane_continuation(message):
            return False
        if not self.coach_context_has_prepared_library_grounding(grounding_context):
            return False
        return self.message_deserves_library_first_lookup(message)

    def fresh_lane_keeps_review_signals(self, scenario: str | None) -> bool:
        return str(scenario or "").strip().lower() in {
            "next_task",
            "review",
            "review_reflection",
        }

    def turn_keeps_review_signals(self, 
        scenario: str | None,
        teaching_decision: object | None = None,
    ) -> bool:
        if self.fresh_lane_keeps_review_signals(scenario):
            return True
        if isinstance(teaching_decision, dict):
            mode = teaching_decision.get("mode")
        else:
            mode = getattr(teaching_decision, "mode", None)
        return str(mode or "").strip().lower() in {"review", "review_reflection"}

    def collect_auto_resource_search_hits(self, 
        raw_hits: object,
        *,
        limit: int,
        require_current_version: bool = False,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        if not isinstance(raw_hits, list):
            return [], []

        requested_resources: list[dict[str, object]] = []
        resource_fragments: list[dict[str, object]] = []
        seen_resource_ids: set[str] = set()
        for hit in raw_hits:
            hit_payload = asdict(hit) if is_dataclass(hit) and not isinstance(hit, type) else hit
            if not isinstance(hit_payload, dict):
                continue
            trust_state = str(hit_payload.get("trust_state") or "").strip().lower()
            index_state = str(hit_payload.get("index_state") or "").strip().lower()
            snippet = str(hit_payload.get("snippet") or hit_payload.get("summary") or "").strip()
            resource_id = str(hit_payload.get("resource_id") or "").strip()
            if not resource_id or resource_id in seen_resource_ids:
                continue
            if trust_state in {"blocked", "rejected"}:
                continue
            if index_state not in {"indexed", "ready", ""}:
                continue
            if not snippet:
                continue
            if require_current_version and (
                hit_payload.get("stale") or not hit_payload.get("content_hash")
                or not hit_payload.get("version_id") or not hit_payload.get("location")
            ):
                continue
            seen_resource_ids.add(resource_id)
            raw_location = hit_payload.get("location")
            hit_location: dict[str, object] = (
                dict(raw_location) if isinstance(raw_location, dict) else {}
            )
            requested_resources.append(
                {
                    "id": resource_id,
                    "title": str(hit_payload.get("title") or resource_id),
                    "kind": str(hit_payload.get("kind") or "resource"),
                    "summary": str(hit_payload.get("summary") or snippet),
                    "source": str(hit_payload.get("source") or ""),
                    "trust_score": str(hit_payload.get("trust_score") or ""),
                    "freshness": str(hit_payload.get("freshness") or ""),
                }
            )
            resource_fragments.append(
                {
                    "id": resource_id,
                    "resource_id": resource_id,
                    "title": str(hit_payload.get("title") or resource_id),
                    "snippet": snippet,
                    "summary": str(hit_payload.get("summary") or snippet),
                    "source": str(hit_payload.get("source") or ""),
                    "source_type": str(hit_payload.get("source_type") or "resource_search"),
                    "kind": str(hit_payload.get("kind") or "resource"),
                    "trust_score": hit_payload.get("trust_score"),
                    "trust_state": str(hit_payload.get("trust_state") or ""),
                    "freshness": str(hit_payload.get("freshness") or ""),
                    "citation_id": str(hit_payload.get("citation_id") or ""),
                    "version_id": str(hit_payload.get("version_id") or ""),
                    "content_hash": str(hit_payload.get("content_hash") or ""),
                    "stale": bool(hit_payload.get("stale")),
                    "current_version_id": str(hit_payload.get("current_version_id") or ""),
                    "current_content_hash": str(hit_payload.get("current_content_hash") or ""),
                    "location": hit_location,
                    "anchor_id": str(hit_payload.get("anchor_id") or ""),
                    "evidence_summary": str(hit_payload.get("match_summary") or snippet),
                    "rank_reasons": list(hit_payload.get("rank_reasons") or []),
                }
            )
            if len(resource_fragments) >= limit:
                break
        return requested_resources, resource_fragments

    def resource_context_ids(self, resource_context: dict[str, object] | None) -> list[str]:
        if not isinstance(resource_context, dict):
            return []
        collected: list[str] = []
        seen_ids: set[str] = set()
        requested_resource_ids = resource_context.get("requested_resource_ids")
        for item in requested_resource_ids if isinstance(requested_resource_ids, list) else []:
            resource_id = str(item or "").strip()
            if not resource_id or resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            collected.append(resource_id)
        if collected:
            return collected
        requested_resources = resource_context.get("requested_resources")
        for item in requested_resources if isinstance(requested_resources, list) else []:
            if not isinstance(item, dict):
                continue
            resource_id = str(item.get("id") or item.get("resource_id") or "").strip()
            if not resource_id or resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            collected.append(resource_id)
        if collected:
            return collected
        resource_fragments = resource_context.get("resource_fragments")
        for item in resource_fragments if isinstance(resource_fragments, list) else []:
            if not isinstance(item, dict):
                continue
            resource_id = str(item.get("resource_id") or item.get("id") or "").strip()
            if not resource_id or resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            collected.append(resource_id)
        return collected

    def load_resource_source_text(self, 
        workspace_id: str,
        resource_id: str,
        *,
        max_chars: int = 12000,
    ) -> tuple[ResourceRecord | None, str]:
        resource = self.runtime.repository.get_resource(workspace_id, resource_id)
        if resource is None:
            return None, ""
        if str(resource.kind or "").strip().lower() not in {"markdown", "text", "code"}:
            return resource, ""
        local_source_path = None
        try:
            local_source_path = self.runtime.resource_service._local_source_path(resource.source)
        except Exception:
            local_source_path = None
        if local_source_path is None or not local_source_path.exists() or not local_source_path.is_file():
            return resource, ""
        try:
            raw_text = local_source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                raw_text = local_source_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return resource, ""
        except OSError:
            return resource, ""
        return resource, raw_text[:max_chars]

    def extract_explicit_sequence_guidance(self, 
        resource: ResourceRecord,
        text: str,
    ) -> dict[str, object] | None:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return None
        title_match = re.search(r"^\s*#\s+(.+?)\s*$", normalized_text, re.MULTILINE)
        resource_title = (
            str(title_match.group(1)).strip()
            if title_match
            else str(resource.name or resource.id).strip() or "resource"
        )
        step_pattern = re.compile(
            r"^\s*(?P<label>(?:Step\s+\d+)|(?:第\s*[0-9一二三四五六七八九十]+\s*步))\s*(?:[-:：.]|\)|\s)\s*(?P<body>.+?)\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        steps: list[dict[str, str]] = []
        for match in step_pattern.finditer(normalized_text):
            label = " ".join(str(match.group("label") or "").split()).strip()
            body = " ".join(str(match.group("body") or "").split()).strip()
            if not label or not body:
                continue
            steps.append({"label": label, "text": body})
        if len(steps) < 2:
            return None
        boundary_match = re.search(
            r"^\s*(?:Boundary sentinel|Boundary|边界哨兵|边界提示)\s*[:：-]\s*(?P<body>.+?)\s*$",
            normalized_text,
            re.IGNORECASE | re.MULTILINE,
        )
        boundary_sentinel = (
            " ".join(str(boundary_match.group("body") or "").split()).strip()
            if boundary_match
            else ""
        )
        scenario = infer_message_coaching_scenario(
            f"{resource_title}\n{normalized_text}",
            default="general",
        )
        return {
            "resource_id": resource.id,
            "title": resource_title,
            "source": resource.canonical_source or resource.source,
            "step_count": len(steps),
            "steps": steps[:6],
            "boundary_sentinel": boundary_sentinel,
            "scenario": scenario if scenario in GUIDED_SEQUENCE_SCENARIOS else "",
        }

    def attach_resource_sequence_guidance(self, 
        workspace_id: str,
        resource_context: dict[str, object],
    ) -> dict[str, object]:
        resource_ids = self.resource_context_ids(resource_context)
        if not resource_ids:
            return resource_context
        sequences: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for resource_id in resource_ids[:3]:
            if resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            resource, source_text = self.load_resource_source_text(workspace_id, resource_id)
            if resource is None or not source_text:
                continue
            sequence = self.extract_explicit_sequence_guidance(resource, source_text)
            if sequence is None:
                continue
            sequences.append(sequence)
            if len(sequences) >= 2:
                break
        if not sequences:
            return resource_context
        enriched = dict(resource_context)
        enriched["resource_sequence_guidance"] = sequences
        first_sequence = sequences[0]
        first_title = str(first_sequence.get("title") or "This resource").strip()
        raw_step_count = first_sequence.get("step_count")
        first_step_count = raw_step_count if isinstance(raw_step_count, int) else 0
        if first_step_count >= 2:
            enriched["resource_sequence_summary"] = (
                f"{first_title} carries an exact {first_step_count}-step library sequence; "
                "restate every step in order, and preserve its step count and labels unless you clearly mark an extension."
            )
        return enriched

    def automatic_resource_context(self, 
        workspace_id: str,
        message: str | None,
        *,
        limit: int = 4,
        analysis: bool = False,
    ) -> dict[str, object]:
        if not analysis and not self.message_deserves_library_probe(message):
            return {}
        workspace_resources = self.runtime.repository.list_resources(workspace_id)
        if not workspace_resources:
            return {}
        requested_resources: list[dict[str, object]] = []
        resource_fragments: list[dict[str, object]] = []
        selected_query = ""
        queries_tried: list[str] = []
        candidates = self.resource_lookup_query_candidates(message)
        if analysis:
            first_clause = re.split(r"[，,。；;\n]", str(message or ""), maxsplit=1)[0]
            topic = re.sub(r"^(?:请|帮我|请帮我)?(?:把|从|在)?(?:我的)?(?:资料库|资源库)[里中内]?", "", first_clause)
            topic = re.sub(r"^(?:找出|搜索|查找|检索)(?:资料库[里中内]?)?(?:所有)?(?:关于)?", "", topic)
            topic = re.sub(r"(?:(?:的)?相关)?(?:论文|文献|文章|资料)(?:找出来|找出|列出来|查出来)?$", "", topic).strip()
            if topic and topic != first_clause:
                candidates.insert(0, topic)
        for candidate in dict.fromkeys(candidates[:6]):
            queries_tried.append(candidate)
            try:
                search_response = self.runtime.resource_service.search_resources(
                    workspace_id,
                    candidate,
                    top_k=24 if analysis else max(limit * 2, limit + 2),
                    project_scope=workspace_id,
                )
            except Exception:
                continue
            requested_resources, resource_fragments = self.collect_auto_resource_search_hits(
                getattr(search_response, "results", None),
                limit=limit,
                require_current_version=analysis,
            )
            if resource_fragments:
                selected_query = candidate
                break
        if not resource_fragments:
            return {}

        top_titles = ", ".join(
            str(item.get("title") or "").strip()
            for item in requested_resources[:2]
            if str(item.get("title") or "").strip()
        )
        summary = (
            f"Auto-grounded this turn in {len(resource_fragments)} likely library hits"
            + (f": {top_titles}" if top_titles else ".")
        )
        return {
            "requested_resources": requested_resources,
            "requested_resource_ids": [str(item["id"]) for item in requested_resources if item.get("id")],
            "requested_resource_summary": summary,
            "resource_brief": summary,
            "resource_fragments": resource_fragments,
            "auto_resource_lookup": True,
            "auto_resource_query": selected_query or (queries_tried[0] if queries_tried else ""),
            "auto_resource_queries_tried": queries_tried,
        }

    def compact_tool_preview(self, value: object, *, max_chars: int = 420) -> str:
        preview = " ".join(str(value or "").split()).strip()
        if len(preview) <= max_chars:
            return preview
        return f"{preview[: max_chars - 3].rstrip()}..."

    def auto_resource_lookup_tool_events(self, 
        resource_context: dict[str, object] | None,
        message: str | None,
    ) -> list[dict[str, object]]:
        if not isinstance(resource_context, dict):
            return []
        if resource_context.get("auto_resource_lookup") is not True:
            return []
        raw_fragments = resource_context.get("resource_fragments")
        if not isinstance(raw_fragments, list) or not raw_fragments:
            return []

        composer_intent = resource_context.get("resource_composer_intent")
        analysis = isinstance(composer_intent, dict) and composer_intent.get("mode") == "analyze"
        hits: list[dict[str, object]] = []
        for item in raw_fragments[:4 if analysis else 3]:
            if not isinstance(item, dict):
                continue
            resource_id = str(item.get("resource_id") or item.get("id") or "").strip()
            title = str(item.get("title") or resource_id or "resource").strip()
            snippet = self.compact_tool_preview(
                item.get("snippet") or item.get("summary") or item.get("evidence_summary") or "",
                max_chars=360,
            )
            if not resource_id and not snippet:
                continue
            hit: dict[str, object] = {
                "resource_id": resource_id,
                "title": title,
                "snippet": snippet,
            }
            source = str(item.get("source") or "").strip()
            if source:
                hit["source"] = source
            kind = str(item.get("kind") or "").strip()
            if kind:
                hit["kind"] = kind
            citation_id = str(item.get("citation_id") or "").strip()
            if citation_id:
                hit["citation_id"] = citation_id
            version_id = str(item.get("version_id") or "").strip()
            if version_id:
                hit["version_id"] = version_id
            content_hash = str(item.get("content_hash") or "").strip()
            if content_hash:
                hit["content_hash"] = content_hash
            if item.get("stale") is True:
                hit["stale"] = True
            current_version_id = str(item.get("current_version_id") or "").strip()
            if current_version_id:
                hit["current_version_id"] = current_version_id
            current_content_hash = str(item.get("current_content_hash") or "").strip()
            if current_content_hash:
                hit["current_content_hash"] = current_content_hash
            location = item.get("location")
            if isinstance(location, dict) and location:
                hit["location"] = dict(location)
            anchor_id = str(item.get("anchor_id") or "").strip()
            if anchor_id:
                hit["anchor_id"] = anchor_id
            trust_score = item.get("trust_score")
            if trust_score is not None:
                hit["trust_score"] = trust_score
            freshness = str(item.get("freshness") or "").strip()
            if freshness:
                hit["freshness"] = freshness
            source_type = str(item.get("source_type") or "").strip()
            if source_type:
                hit["source_type"] = source_type
            rank_reasons = item.get("rank_reasons")
            if isinstance(rank_reasons, list):
                hit["rank_reasons"] = [
                    self.compact_tool_preview(reason, max_chars=120)
                    for reason in rank_reasons[:3]
                    if str(reason or "").strip()
                ]
            hits.append(hit)

        if not hits:
            return []

        query = self.compact_tool_preview(message, max_chars=240)
        selected_query = self.compact_tool_preview(
            resource_context.get("auto_resource_query") or query,
            max_chars=240,
        )
        summary = self.compact_tool_preview(
            resource_context.get("requested_resource_summary")
            or resource_context.get("resource_brief")
            or f"Auto-grounded this turn in {len(raw_fragments)} likely library hits.",
            max_chars=360,
        )
        result: dict[str, object] = {
            "query": selected_query,
            "summary": summary,
            "total": len(raw_fragments),
            "hits": hits,
            "auto": True,
        }
        if analysis:
            result["mode"] = "analyze"
        queries_tried = resource_context.get("auto_resource_queries_tried")
        if isinstance(queries_tried, list) and queries_tried:
            result["queries_tried"] = [
                self.compact_tool_preview(candidate, max_chars=120)
                for candidate in queries_tried[:6]
                if str(candidate or "").strip()
            ]
        sequence_guidance = resource_context.get("resource_sequence_guidance")
        if isinstance(sequence_guidance, list) and sequence_guidance:
            result["prepared_sequences"] = sequence_guidance[:2]

        call_id = "auto-search-resources"
        result_with_domain = {"domain": "library_sandbox", "action": "search", **result}
        return [
            {
                "type": "tool_call",
                "id": call_id,
                "name": "library_read",
                "arguments": {
                    "action": "search",
                    "query": selected_query,
                    "mode": "narrow",
                    "auto": True,
                },
                "step": 0,
                "auto": True,
            },
            {
                "type": "tool_result",
                "id": call_id,
                "name": "library_read",
                "ok": True,
                "result": result_with_domain,
                "step": 0,
                "auto": True,
            },
        ]

    def merge_auto_resource_tool_events(self, 
        raw_events: object,
        auto_events: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        events = [dict(item) for item in raw_events if isinstance(item, dict)] if isinstance(raw_events, list) else []
        if not auto_events:
            return events
        already_has_auto_resource_evidence = any(
            str(item.get("name") or "").strip() in {"library_read", "search_resources"}
            and (
                str(item.get("id") or "").strip() == "auto-search-resources"
                or item.get("auto") is True
            )
            for item in events
        )
        if already_has_auto_resource_evidence:
            return events
        return [*auto_events, *events]

    def apply_auto_resource_agent_evidence(self, 
        agent_meta: dict[str, object] | None,
        auto_events: list[dict[str, object]],
    ) -> dict[str, object]:
        merged_meta = dict(agent_meta or {})
        merged_events = self.merge_auto_resource_tool_events(merged_meta.get("tool_events"), auto_events)
        if merged_events:
            merged_meta["tool_events"] = merged_events
            merged_meta["auto_resource_lookup"] = True
            merged_meta.setdefault("agentic", False)
            merged_meta.setdefault("stop_reason", "completed")
            merged_meta.setdefault(
                "summary",
                "Prepared library grounding from Resources before answering.",
            )
            merged_meta.setdefault(
                "teaching_note",
                "Resources were checked automatically because this looked like a teach/debug/remote/API/protocol turn.",
            )
        return merged_meta

    def should_attach_auto_resource_events(self, agent_meta: dict[str, object] | None) -> bool:
        if not isinstance(agent_meta, dict):
            return True
        stop_reason = str(agent_meta.get("stop_reason") or "").strip()
        return stop_reason not in {
            "invalid_key_or_permission",
            "model_unsupported",
            "model_not_found",
            "malformed_response",
            "rate_limit",
            "upstream_unavailable",
            "timeout",
            "network",
            "unknown",
            "provider_error",
            "language_corruption",
        }

    def compose_resource_context(self, 
        workspace_id: str,
        resource_ids: list[str] | None,
        *,
        message: str | None = None,
        resource_composer_intent: ResourceComposerIntent | None = None,
    ) -> dict[str, object]:
        if resource_composer_intent is not None and resource_composer_intent.mode == "analyze":
            ids = resource_ids or resource_composer_intent.resource_ids
            if not ids and preparation_for_active_stage(message or ""):
                stage = self.active_plan_stage(self.runtime.repository.get_latest_plan(workspace_id))
                if stage is not None:
                    ids = [
                        resource.id for resource_id in stage.resources
                        if (resource := self.runtime.repository.get_resource(workspace_id, resource_id)) is not None
                        and resource.index_status == "indexed"
                    ]
            analysis_context = (self.runtime.resource_service.build_requested_resource_context(
                workspace_id, ids[:4], fragments_per_source=1,
            ) if ids else self.automatic_resource_context(workspace_id, message, analysis=True))
            fragments = analysis_context.get("resource_fragments")
            use_page_hint = isinstance(fragments, list) and sum(
                isinstance(item, dict) and item.get("kind") == "pdf" for item in fragments
            ) == 1
            verified_fragments = []
            store = self.runtime.resource_version_store
            for item in fragments if isinstance(fragments, list) else []:
                if not isinstance(item, dict) or not item.get("location") or store is None:
                    continue
                resource_id = str(item.get("resource_id") or "")
                version = store.current_version(workspace_id, resource_id)
                if not version or item.get("version_id") != version["version_id"] or (
                    item.get("content_hash") != version["content_hash"]
                ):
                    continue
                resource = self.runtime.repository.get_resource(workspace_id, resource_id)
                if resource is None:
                    continue
                if ids:
                    body, anchors = self.runtime.resource_service.indexed_source_text(workspace_id, resource)
                    passages = brief_passages(
                        BriefPassage(resource, body, 1, anchors), message or "",
                        passage_length=900, limit=1, use_page_hint=use_page_hint,
                    )
                    if passages:
                        selected = passages[0]
                        passage = selected.text.lstrip()
                        excerpt = self.redact_training_fact_text(passage, 900)
                        if excerpt:
                            leading = selected.text[:len(selected.text) - len(passage)]
                            start = selected.first_line + leading.count("\n")
                            ref = selected.reference(passage.rstrip(), start)
                            citation = store.record_citation(
                                workspace_id=workspace_id, resource_id=resource_id,
                                version_id=resource.version_id, content_hash=resource.content_hash,
                                location=ref.metadata["location"],
                            )
                            verified_fragments.append({
                                **citation, "title": resource.name, "kind": resource.kind,
                                "source": resource.canonical_source or resource.source,
                                "snippet": excerpt, "excerpt": excerpt,
                            })
                            continue
                passage = self.runtime.resource_service.read_indexed_fragment_text(workspace_id, resource, item)
                excerpt = self.redact_training_fact_text(passage, 900)
                if excerpt:
                    verified_fragments.append({**item, "excerpt": excerpt})
            return {
                **({} if ids else analysis_context),
                "auto_resource_lookup": True,
                "resource_fragments": verified_fragments,
                **self.resource_composer_context(resource_composer_intent),
            }
        requested = self.requested_resource_context(workspace_id, resource_ids)
        workspace_context = self.workspace_understanding_resource_context(workspace_id, resource_ids)
        auto_context = self.automatic_resource_context(workspace_id, message) if not requested else {}
        composer_context = self.resource_composer_context(resource_composer_intent)
        merged: dict[str, object] = {}
        if workspace_context:
            merged.update(workspace_context)
        if auto_context:
            merged.update(auto_context)
        if requested:
            merged.update(requested)
        if composer_context:
            merged.update(composer_context)
        if not merged:
            return merged
        if message:
            question_facets: list[str] = []
            for facet in self.canonical_resource_view_terms(message):
                if facet not in question_facets:
                    question_facets.append(facet)
            for facet in self.mapped_resource_lookup_phrases(message):
                if facet not in question_facets:
                    question_facets.append(facet)
            if question_facets:
                merged["resource_question_facets"] = question_facets[:6]
        return self.attach_resource_sequence_guidance(workspace_id, merged)

    def load_curated_background_references(self, 
        workspace_id: str,
        *,
        focus_area: str | None = None,
        limit: int = 4,
    ) -> list[dict[str, object]]:
        references = self.runtime.resource_service.curated_background_references(
            workspace_id,
            max_fragments=limit,
            focus_area=focus_area,
        )
        if not references and focus_area:
            references = self.runtime.resource_service.curated_background_references(
                workspace_id,
                max_fragments=limit,
            )
        return references

    def load_recent_background_findings(self, 
        workspace_id: str,
        *,
        focus_area: str | None = None,
        limit: int = 4,
    ) -> list[dict[str, object]]:
        references = self.runtime.research_service.recent_background_references(
            workspace_id=workspace_id,
            focus_area=focus_area,
            min_confidence=0.35,
            limit=limit,
        )
        if not references and focus_area:
            references = self.runtime.research_service.recent_background_references(
                workspace_id=workspace_id,
                min_confidence=0.35,
                limit=limit,
            )
        return references

    def workspace_first_look_summary(self, workspace_id: str) -> FirstLookSummary | None:
        memory_snapshot = self.runtime.memory_service.snapshot(workspace_id)
        understanding = memory_snapshot.workspace_understanding
        if understanding is None:
            return None
        return understanding.first_look_summary

    def first_look_recommended_next_from_snapshot(self, snapshot: WorkbenchSnapshot | None) -> str:
        if snapshot is None or snapshot.memory is None:
            return ""
        understanding = snapshot.memory.workspace_understanding
        if understanding is None or understanding.first_look_summary is None:
            return ""
        return str(understanding.first_look_summary.recommended_next_step or "").strip()

    def persist_first_look_summary(self, 
        workspace_id: str,
        first_look_summary: FirstLookSummary,
    ) -> WorkspaceUnderstandingSnapshot:
        memory_snapshot = self.runtime.memory_service.snapshot(workspace_id)
        existing = memory_snapshot.workspace_understanding
        if existing is None:
            understanding = WorkspaceUnderstandingSnapshot(firstLookSummary=first_look_summary)
        else:
            understanding = existing.model_copy(deep=True)
            understanding.first_look_summary = first_look_summary
        self.runtime.memory_service.save_workspace_understanding(workspace_id, understanding)
        return understanding

    def maybe_persist_first_look_from_path(self, 
        workspace_id: str,
        folder_path: str | None,
        *,
        response_language: str | None = None,
        workspace_file_snapshot: dict | None = None,
        remote_name: str | None = None,
    ) -> FirstLookSummary | None:
        path = str(folder_path or "").strip()
        snapshot = workspace_file_snapshot if isinstance(workspace_file_snapshot, dict) else None
        remote = bool(
            str(remote_name or "").strip()
            or (isinstance(snapshot, dict) and snapshot.get("is_remote") is True)
            or "://" in path
        )
        local_dir = False
        if path and "://" not in path:
            try:
                candidate = Path(path).expanduser()
                local_dir = candidate.exists() and candidate.is_dir()
            except OSError:
                local_dir = False
        if not local_dir and not snapshot and not remote:
            return None
        if not path and not snapshot:
            return None
        summary = classify_heuristic(
            path,
            response_language=response_language,
            workspace_file_snapshot=snapshot,
            remote_name=remote_name,
        )
        self.persist_first_look_summary(workspace_id, summary)
        return summary

    def first_look_focus_hint(self, workspace_id: str) -> str | None:
        summary = self.workspace_first_look_summary(workspace_id)
        if summary is None:
            return None
        candidates = [
            summary.training_opportunities[0] if summary.training_opportunities else "",
            summary.recommended_next_step,
            summary.project_type_guess.replace("_", " ") if summary.project_type_guess else "",
            summary.folder_role.replace("_", " ") if summary.folder_role else "",
            summary.entry_points[0] if summary.entry_points else "",
        ]
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text:
                return text
        return None

    def resolve_external_references(self, 
        *,
        workspace_id: str,
        resource_context: dict[str, object] | None,
        focus_area: str | None = None,
        limit: int = 4,
        additional_curated_fragments: list[dict[str, object]] | None = None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
        resource_fragments = (
            resource_context.get("resource_fragments", [])
            if isinstance(resource_context, dict)
            else []
        )
        composer_intent = resource_context.get("resource_composer_intent") if resource_context else None
        if isinstance(composer_intent, dict) and composer_intent.get("mode") == "analyze":
            return ([item for item in resource_fragments[:limit] if isinstance(item, dict)]
                    if isinstance(resource_fragments, list) else [], [], [])
        curated_background_references = self.load_curated_background_references(
            workspace_id,
            focus_area=focus_area,
            limit=limit,
        )
        if additional_curated_fragments:
            curated_background_references = self.runtime.resource_service.merge_external_references(
                curated_fragments=curated_background_references + additional_curated_fragments,
                focus_area=focus_area,
                limit=limit,
            )
        recent_background_findings = self.load_recent_background_findings(
            workspace_id,
            focus_area=focus_area,
            limit=limit,
        )
        external_references = self.runtime.resource_service.merge_external_references(
            requested_fragments=resource_fragments if isinstance(resource_fragments, list) else [],
            curated_fragments=curated_background_references,
            research_findings=recent_background_findings,
            focus_area=focus_area,
            limit=limit,
        )
        return external_references, curated_background_references, recent_background_findings

    def persist_external_references_as_background(self, 
        *,
        workspace_id: str,
        scenario: str,
        coach_turn_data: dict[str, object] | None,
    ) -> None:
        coach_context = (
            normalized_object_mapping(coach_turn_data.get("coach_context"))
            if isinstance(coach_turn_data, dict)
            else None
        ) or {}
        external_references = coach_context.get("external_references")
        if not isinstance(external_references, list) or not external_references:
            return
        fallback_focus = str(
            coach_context.get("current_focus")
            or coach_context.get("summary")
            or scenario
            or "Current training focus"
        ).strip()
        for item in external_references[:3]:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "") or "").strip()
            snippet = str(item.get("snippet", "") or "").strip()
            if not source or not snippet:
                continue
            created_at_raw = str(item.get("created_at") or item.get("fetched_at") or "").strip()
            created_at = None
            if created_at_raw:
                try:
                    created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
                except ValueError:
                    created_at = None
            self.runtime.research_service.record_background_reference(
                workspace_id=workspace_id,
                focus_area=str(item.get("focus_area", "") or fallback_focus).strip(),
                source=source,
                content=snippet,
                trust_score=float(item.get("trust_score", 0.0) or 0.0),
                tags=[
                    "coach-turn",
                    f"scenario:{scenario}",
                    str(item.get("reference_origin", "") or "external-reference"),
                ],
                created_at=created_at,
                source_type=str(item.get("source_type", "") or "").strip() or None,
                freshness=str(item.get("freshness", "") or "").strip() or None,
                fetched_at=str(item.get("fetched_at", "") or "").strip() or None,
                why_it_matters=str(item.get("why_it_matters", "") or "").strip() or None,
            )
