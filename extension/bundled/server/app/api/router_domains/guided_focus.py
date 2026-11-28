"""Focus candidate normalization, guided-lane contamination guards, and visible sequence fallbacks."""

from __future__ import annotations

import re

from ...core.models import (
    MemorySnapshot,
    SandboxWriteRequest,
)
from ...core.text_boundaries import CLAUSE_END_PATTERN
from ...llm.prompts import infer_coaching_scenario as infer_message_coaching_scenario
from ...llm.turn_grounding import (
    looks_like_narration_opening,
)
from ...workspace.classifier import (
    is_code_like_current_file,
    is_code_like_entry_point,
)
from .._helpers import (
    contains_cjk_text,
    localized_text,
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
from ..coach_language_alignment import (
    language_aligned_context_text,
    language_aligned_memory_payload,
)
from ..coach_text_sanitizer import (
    normalize_visible_coach_text,
    strip_visible_next_step_prefix,
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
    _GUIDED_LANE_CONTINUATION_PATTERN,
    GENERIC_FOCUS_DISPLAY_LABELS,
    GENERIC_FOCUS_LABELS,
    GUIDED_LANE_SCENARIOS,
    GUIDED_SEQUENCE_SCENARIOS,
    GUIDED_VISIBLE_REPAIR_SCENARIOS,
)


class GuidedFocusDomainMixin(RouterDomainBase):
    """Focus candidate normalization, guided-lane contamination guards, and visible sequence fallbacks."""

    def normalize_focus_candidate(self, value: object) -> str:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip()
        return normalized.strip(
            " \t\r\n\"'`\u201c\u201d\u2018\u2019\u300c\u300d\u300e\u300f\uFF08\uFF09()[]{}<>:\uFF1A\uFF0C\u3002\uFF01\uFF1F\uFF1B;\u3001,."
        )

    def display_focus_label(self, value: object, response_language: str | None) -> str:
        cleaned = self.normalize_focus_candidate(value)
        if not cleaned:
            return ""
        localized = GENERIC_FOCUS_DISPLAY_LABELS.get(cleaned.lower())
        if localized is None:
            return cleaned
        return localized_text(localized[0], localized[1], response_language)

    def canonical_focus_for_scenario(self, 
        scenario: str | None,
        response_language: str | None,
    ) -> str | None:
        if scenario == "remote_workspace":
            return localized_text("VS Code remote workspace", "VS Code 远程工作区", response_language)
        if scenario == "debug_loop":
            return localized_text("VS Code debug loop", "VS Code 调试闭环", response_language)
        if scenario == "function_guidance":
            return localized_text("function contract reading", "\u51fd\u6570\u5951\u7ea6\u5224\u65ad", response_language)
        return None

    def localized_training_defaults_for_scenario(self, 
        scenario: str,
        response_language: str | None,
    ) -> tuple[str, str] | None:
        if scenario == "remote_workspace":
            return (
                localized_text(
                    "VS Code remote workspace",
                    "VS Code 远程工作区",
                    response_language,
                ),
                localized_text(
                    "remote workspace boundary",
                    "远程工作区边界",
                    response_language,
                ),
            )
        if scenario == "debug_loop":
            return (
                localized_text(
                    "VS Code debug loop",
                    "VS Code 调试闭环",
                    response_language,
                ),
                localized_text(
                    "the smallest trustworthy debug loop",
                    "最小可信的 debug loop",
                    response_language,
                ),
            )
        if scenario == "function_guidance":
            return (
                localized_text(
                    "function contract reading",
                    "\u51fd\u6570\u5951\u7ea6\u5224\u65ad",
                    response_language,
                ),
                localized_text(
                    "function contract and call-site reading",
                    "\u51fd\u6570\u5951\u7ea6\u4e0e call site \u5224\u65ad",
                    response_language,
                ),
            )
        return None

    def focus_looks_like_request_sentence(self, value: object) -> bool:
        cleaned = self.normalize_focus_candidate(value)
        if not cleaned:
            return False
        lowered = cleaned.lower()
        if lowered.startswith(
            (
                "teach me ",
                "help me ",
                "show me ",
                "tell me ",
                "walk me through ",
                "how to ",
                "this is ",
                "i want ",
                "create ",
                "generate ",
                "please ",
                "continue ",
            )
        ):
            return True
        return len(cleaned.split()) >= 7 and any(
            token in lowered
            for token in (
                "remote workspace",
                "debug loop",
                "typescript function",
                "function",
            )
        )

    def guided_lane_comparison_requested(self, message: str | None) -> bool:
        lowered = str(message or "").casefold()
        if not lowered:
            return False
        markers = (
            "compare",
            "comparison",
            "difference",
            "different",
            "versus",
            "compared to",
            "对比",
            "区别",
            "相比",
        )
        return any(marker.casefold() in lowered for marker in markers)

    def guided_lane_visible_marker_map(self) -> dict[str, tuple[str, ...]]:
        return {
            "remote_workspace": (
                "remote workspace",
                "remote lane",
                "remote ssh",
                "ssh",
                "tunnels",
                "dev container",
                "devcontainer",
                "wsl",
                "credential",
                "credential mode",
                "credential move",
                "host",
                "host label",
                "workspace label",
                "远程工作区",
                "远程工作区边界",
                "远程主线",
                "远程 ssh",
                "远程边界",
                "开发容器",
                "凭据",
                "凭据模式",
                "host label",
                "workspace label",
            ),
            "debug_loop": (
                "debug loop",
                "breakpoint",
                "launch.json",
                "stack frame",
                "call stack",
                "watch value",
                "state change",
                "调试闭环",
                "断点",
                "调用栈",
                "单步",
                "变量值",
            ),
            "function_guidance": (
                "function contract",
                "call site",
                "hover",
                "signature help",
                "go to definition",
                "查看定义",
                "函数 contract",
                "函数契约",
                "调用点",
                "调用位置",
                "签名提示",
            ),
        }

    def text_contaminates_guided_lane(self, 
        value: object,
        *,
        scenario: str,
        learner_message: str | None,
    ) -> bool:
        normalized_scenario = str(scenario or "").strip().lower()
        if normalized_scenario not in GUIDED_VISIBLE_REPAIR_SCENARIOS:
            return False
        if self.guided_lane_comparison_requested(learner_message):
            return False
        cleaned = normalize_visible_coach_text(value) or str(value or "").strip()
        if not cleaned:
            return False
        lowered = re.sub(r"\s+", " ", cleaned).casefold()
        marker_map = self.guided_lane_visible_marker_map()
        other_lane_markers = [
            marker.casefold()
            for lane, markers in marker_map.items()
            if lane != normalized_scenario
            for marker in markers
        ]
        def _marker_matches(marker: str) -> bool:
            if marker.isascii():
                return bool(re.search(rf"(?<![a-z0-9_]){re.escape(marker)}(?![a-z0-9_])", lowered))
            return marker in lowered
        return any(_marker_matches(marker) for marker in other_lane_markers)

    def guided_focus_display_value(self, 
        focus: object,
        *,
        scenario: str | None,
        response_language: str | None,
    ) -> str:
        raw_focus = self.normalize_focus_candidate(focus)
        aligned_focus = language_aligned_context_text(raw_focus, response_language) if raw_focus else ""
        canonical_focus = self.canonical_focus_for_scenario(scenario, response_language) or ""
        if scenario not in GUIDED_LANE_SCENARIOS:
            return aligned_focus or raw_focus or canonical_focus
        if canonical_focus:
            return canonical_focus
        if not raw_focus or self.focus_looks_like_request_sentence(raw_focus):
            return canonical_focus or aligned_focus or raw_focus
        if prefers_chinese(response_language):
            phrase_like_focus = bool(re.search(r"[A-Za-z]", raw_focus)) and len(raw_focus.split()) >= 2
            mixed_lane_focus = bool(
                re.search(r"[A-Za-z]{3,}.*[\u3400-\u9fff]|[\u3400-\u9fff].*[A-Za-z]{3,}", aligned_focus)
            )
            if phrase_like_focus and (not contains_cjk_text(aligned_focus) or mixed_lane_focus):
                return canonical_focus or aligned_focus or raw_focus
        return aligned_focus or raw_focus or canonical_focus

    def guided_lane_focus_needs_response_repair(self, 
        value: object,
        *,
        scenario: str | None,
        learner_message: str | None = None,
    ) -> bool:
        normalized_scenario = str(scenario or "").strip().lower()
        if normalized_scenario not in GUIDED_LANE_SCENARIOS:
            return False
        cleaned = str(value or "").strip()
        if not cleaned:
            return False
        visible_cleaned = normalize_visible_coach_text(cleaned) or cleaned
        if _GUIDED_LANE_CONTINUATION_PATTERN.match(cleaned) or _GUIDED_LANE_CONTINUATION_PATTERN.match(
            visible_cleaned
        ):
            return True
        if self.focus_looks_like_request_sentence(cleaned) or self.focus_looks_like_request_sentence(
            visible_cleaned
        ):
            return True
        return self.text_contaminates_guided_lane(
            visible_cleaned,
            scenario=normalized_scenario,
            learner_message=learner_message,
        )

    def repair_guided_lane_memory_snapshot_for_response(self, 
        memory: MemorySnapshot,
        *,
        scenario: str | None,
        response_language: str | None,
        learner_message: str | None = None,
    ) -> MemorySnapshot:
        normalized_scenario = str(scenario or "").strip().lower()
        if normalized_scenario not in GUIDED_LANE_SCENARIOS:
            aligned_payload = language_aligned_memory_payload(memory.model_dump(), response_language)
            if isinstance(aligned_payload, dict):
                return type(memory).model_validate(aligned_payload)
            return memory

        repaired_memory = memory
        current_focus = str(memory.current_focus or "").strip()
        if self.guided_lane_focus_needs_response_repair(
            current_focus,
            scenario=normalized_scenario,
            learner_message=learner_message,
        ):
            repaired_focus = self.canonical_focus_for_scenario(
                normalized_scenario,
                response_language,
            ) or self.guided_focus_display_value(
                current_focus,
                scenario=normalized_scenario,
                response_language=response_language,
            )
            if repaired_focus:
                repaired_memory = repaired_memory.model_copy(update={"current_focus": repaired_focus})

        active_thread = repaired_memory.active_thread
        if active_thread is not None:
            thread_focus = str(active_thread.focus_area or "").strip()
            if self.guided_lane_focus_needs_response_repair(
                thread_focus,
                scenario=normalized_scenario,
                learner_message=learner_message,
            ):
                repaired_thread_focus = self.canonical_focus_for_scenario(
                    normalized_scenario,
                    response_language,
                ) or self.guided_focus_display_value(
                    thread_focus,
                    scenario=normalized_scenario,
                    response_language=response_language,
                )
                if repaired_thread_focus:
                    repaired_memory = repaired_memory.model_copy(
                        update={
                            "active_thread": active_thread.model_copy(
                                update={"focus_area": repaired_thread_focus}
                            )
                        }
                    )

        aligned_payload = language_aligned_memory_payload(
            repaired_memory.model_dump(),
            response_language,
        )
        if isinstance(aligned_payload, dict):
            return type(repaired_memory).model_validate(aligned_payload)
        return repaired_memory

    def is_specific_focus_candidate(self, value: object) -> bool:
        cleaned = self.normalize_focus_candidate(value)
        if not cleaned:
            return False
        lowered = cleaned.lower()
        if lowered in GENERIC_FOCUS_LABELS:
            return False
        if lowered.startswith("current coaching focus:") or cleaned.startswith(
            ("\u5f53\u524d\u805a\u7126\uff1a", "\u5f53\u524d\u805a\u7126\u70b9\uff1a")
        ):
            return False
        if len(cleaned) > 96 or len(cleaned.split()) > 12:
            return False
        return True

    def extract_focus_hint_from_message(self, 
        message: str | None,
        *,
        allow_message_prefix: bool = True,
    ) -> str | None:
        normalized_message = re.sub(r"\s+", " ", str(message or "")).strip()
        if not normalized_message:
            return None

        named_concept_patterns = (
            r"""\b(?P<topic>[A-Z][A-Za-z0-9_-]{2,}(?:\s+[A-Z][A-Za-z0-9_-]{2,}){0,2}\s+(?:protocol|workflow|pattern|boundary|contract|guide|checklist|loop|api))\b""",
            r"""\b(?P<topic>[A-Z][A-Za-z0-9_-]{2,}\s+(?:protocol|workflow|pattern|boundary|contract|guide|checklist|loop|api))\b""",
        )
        for pattern in named_concept_patterns:
            match = re.search(pattern, normalized_message, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = self.normalize_focus_candidate(match.groupdict().get("topic"))
            if self.is_specific_focus_candidate(candidate):
                return candidate

        patterns = (
            r"""["'“”‘’「」『』]([^"'“”‘’「」『』\n]{3,80})["'“”‘’「」『』]""",
            r"""(?:围绕|聚焦|关注|关于)\s*["'“”‘’「」『』]?(?P<topic>[^,，。！？；;\n]{2,60}?)(?=[，。！？；,\n]|\s+(?:先|再|然后)\b|$)""",
            r"""(?:focus on|stay on|keep the focus on|guide me through|work on)\s*["'“”‘’「」『』]?(?P<topic>[^,.!?，。！？；;\n]{3,80}?)(?=\s+(?:and|first|before|then)\b|[,.!?，。！？；;\n]|$)""",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized_message, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = self.normalize_focus_candidate(match.groupdict().get("topic") or match.group(1))
            if self.is_specific_focus_candidate(candidate):
                return candidate

        if not allow_message_prefix:
            # Memory-anchor path: the raw opening clause of the learner message
            # is not a technical concept. Returning nothing lets the anchor
            # fall back to the previous anchor instead of drifting onto the
            # message prefix (2026-10-08 real-teaching review, cases 01-03).
            return None
        # A dot inside "refunds.py" is part of the name, not the end of the clause.
        first_clause = CLAUSE_END_PATTERN.split(normalized_message, maxsplit=1)[0]
        first_clause = re.sub(
            r"^(?:please|can you|could you|help me|guide me|show me|tell me|请|现在|先帮我)\s+",
            "",
            first_clause,
            flags=re.IGNORECASE,
        )
        # "我在 refunds.py 里也碰到…" opens with a pronoun and a preposition. Without them the
        # clause names the focus; with them it repeats the request.
        first_clause = re.sub(r"^(?:我|你|我们|你们)(?:在|的|把|给|跟|与)\s*", "", first_clause)
        first_clause = self.normalize_focus_candidate(first_clause)
        if self.is_specific_focus_candidate(first_clause):
            return first_clause
        return None

    def strip_resource_lookup_lead_in(self, value: object) -> str:
        cleaned = self.normalize_focus_candidate(value)
        if not cleaned:
            return ""
        cleaned = re.sub(
            r"^(?:please|can you|could you|would you|help me|teach me|show me|tell me|walk me through|guide me|请(?:直接)?|直接|请先|先|现在|麻烦你|帮我|请告诉我|告诉我|教我|讲解(?:一下)?|解释(?:一下)?|说明(?:一下)?)\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^(?:以及它|以及|并且|并|然后|再|它)\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return self.normalize_focus_candidate(cleaned)

    def rewrite_resource_lookup_terms(self, value: object) -> str:
        cleaned = self.normalize_focus_candidate(value)
        if not cleaned:
            return ""
        rewritten = cleaned
        replacements = (
            ("Coach 视图", "Coach view"),
            ("Plan 视图", "Plan view"),
            ("Resources 视图", "Resources view"),
            ("Training 视图", "Training view"),
            ("Settings 视图", "Settings view"),
            ("对话视图", "Coach view"),
            ("计划视图", "Plan view"),
            ("资料视图", "Resources view"),
            ("资源视图", "Resources view"),
            ("训练视图", "Training view"),
            ("设置视图", "Settings view"),
            ("首屏承诺", "first viewport promise"),
            ("首屏", "first viewport"),
            ("绝不能变成", "must not become"),
            ("不能变成", "must not become"),
            ("不能成为", "must not become"),
            ("不应该变成", "must not become"),
            ("设计文档", "design doc"),
            ("设计规范", "design spec"),
            ("规范文档", "design spec"),
            ("原始文件系统浏览器", "raw filesystem browser"),
            ("文件系统浏览器", "filesystem browser"),
            ("可追溯", "provenance"),
        )
        for source, target in replacements:
            rewritten = rewritten.replace(source, target)
        return self.normalize_focus_candidate(rewritten)

    def canonical_resource_view_terms(self, message: str | None) -> list[str]:
        normalized_message = str(message or "")
        lowered = normalized_message.lower()
        view_markers = (
            (("coach view", "coach 视图", "对话视图"), "Coach"),
            (("plan view", "plan 视图", "计划视图"), "Plan"),
            (
                ("resources view", "resource view", "resources 视图", "resource 视图", "资料视图", "资源视图"),
                "Resources",
            ),
            (("training view", "training 视图", "训练视图"), "Training"),
            (("settings view", "settings 视图", "设置视图"), "Settings"),
        )
        resolved: list[str] = []
        for markers, canonical in view_markers:
            if any(marker in lowered for marker in markers):
                resolved.append(canonical)
        return resolved

    def mapped_resource_lookup_phrases(self, message: str | None) -> list[str]:
        normalized_message = str(message or "")
        lowered = normalized_message.lower()
        mappings = (
            ("首屏承诺", "first viewport promise"),
            ("首屏", "first viewport"),
            ("绝不能变成", "must not become"),
            ("不能变成", "must not become"),
            ("不能成为", "must not become"),
            ("不应该变成", "must not become"),
            ("原始文件系统浏览器", "raw filesystem browser"),
            ("文件系统浏览器", "filesystem browser"),
            ("可追溯", "provenance"),
        )
        resolved: list[str] = []
        for source, target in mappings:
            if source in normalized_message:
                resolved.append(target)
        if "first viewport" in lowered and "promise" in lowered:
            resolved.append("first viewport promise")
        if "first viewport" in lowered:
            resolved.append("first viewport")
        if "promise" in lowered:
            resolved.append("promise")
        if "must not become" in lowered:
            resolved.append("must not become")
        if "raw filesystem browser" in lowered:
            resolved.append("raw filesystem browser")
        return resolved

    def resource_contract_stream_recovery_requested(self, message: str | None) -> bool:
        """Allow a grounded non-stream recovery only after the live stream fails."""

        if not self.canonical_resource_view_terms(message):
            return False
        facets = {
            str(item or "").strip().casefold()
            for item in self.mapped_resource_lookup_phrases(message)
            if str(item or "").strip()
        }
        return {"first viewport promise", "must not become"}.issubset(facets)

    def latin_resource_lookup_tokens(self, message: str | None) -> list[str]:
        normalized_message = str(message or "")
        stopwords = {
            "a",
            "an",
            "and",
            "are",
            "be",
            "can",
            "could",
            "directly",
            "do",
            "does",
            "for",
            "how",
            "i",
            "in",
            "is",
            "it",
            "me",
            "my",
            "of",
            "or",
            "please",
            "show",
            "tell",
            "the",
            "through",
            "to",
            "walk",
            "what",
            "why",
            "you",
        }
        resolved: list[str] = []
        seen_tokens: set[str] = set()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9._:/-]{0,40}", normalized_message):
            lowered = token.lower()
            if lowered in stopwords or lowered in seen_tokens:
                continue
            seen_tokens.add(lowered)
            resolved.append(token)
        return resolved

    def resource_lookup_clause_describes_import_action(self, value: object) -> bool:
        cleaned = self.normalize_focus_candidate(value)
        if not cleaned:
            return False
        lowered = cleaned.lower()
        import_markers = (
            "import",
            "imported",
            "upload",
            "uploaded",
            "导入",
            "上传",
        )
        document_markers = (
            "design doc",
            "design document",
            "design spec",
            "document",
            "markdown",
            "设计文档",
            "设计规范",
            "规范文档",
            "文档",
        )
        learning_markers = (
            "coach",
            "plan",
            "resources",
            "training",
            "settings",
            "remote",
            "debug",
            "function",
            "api",
            "protocol",
            "contract",
            "guide",
            "view",
            "first viewport",
            "promise",
            "must not become",
            "对话",
            "计划",
            "资料",
            "资源",
            "训练",
            "设置",
            "远程",
            "调试",
            "函数",
            "协议",
            "首屏",
            "承诺",
        )
        return (
            any(marker in lowered for marker in import_markers)
            and any(marker in lowered for marker in document_markers)
            and not any(marker in lowered for marker in learning_markers)
        )

    def resource_lookup_query_candidates(self, message: str | None) -> list[str]:
        normalized_message = self.normalize_focus_candidate(message)
        if not normalized_message:
            return []

        candidates: list[str] = []
        seen_candidates: set[str] = set()

        def add_candidate(value: object) -> None:
            stripped = self.strip_resource_lookup_lead_in(value)
            cleaned = self.normalize_focus_candidate(stripped)
            if not cleaned:
                return
            lowered = cleaned.lower()
            if lowered in seen_candidates:
                return
            seen_candidates.add(lowered)
            candidates.append(cleaned)

        focus_hint = self.extract_focus_hint_from_message(normalized_message)
        if (
            focus_hint
            and not self.focus_looks_like_request_sentence(focus_hint)
            and not self.resource_lookup_clause_describes_import_action(focus_hint)
        ):
            add_candidate(focus_hint)
            rewritten_focus = self.rewrite_resource_lookup_terms(focus_hint)
            if rewritten_focus and rewritten_focus.lower() != focus_hint.lower():
                add_candidate(rewritten_focus)

        clauses = [
            self.normalize_focus_candidate(part)
            for part in re.split(r"[，,。！？!?；;\n]+", normalized_message)
        ]
        for clause in clauses:
            if not clause:
                continue
            if self.resource_lookup_clause_describes_import_action(clause):
                continue
            add_candidate(clause)
            rewritten_clause = self.rewrite_resource_lookup_terms(clause)
            if rewritten_clause and rewritten_clause.lower() != clause.lower():
                add_candidate(rewritten_clause)

        composite_terms: list[str] = []
        for term in self.canonical_resource_view_terms(normalized_message):
            if term not in composite_terms:
                composite_terms.append(term)
        for term in self.mapped_resource_lookup_phrases(normalized_message):
            if term not in composite_terms:
                composite_terms.append(term)
        for term in self.latin_resource_lookup_tokens(self.rewrite_resource_lookup_terms(normalized_message) or normalized_message):
            if term not in composite_terms:
                composite_terms.append(term)
            if len(composite_terms) >= 8:
                break
        if composite_terms:
            add_candidate(" ".join(composite_terms))

        rewritten_message = self.rewrite_resource_lookup_terms(normalized_message)
        if rewritten_message and rewritten_message.lower() != normalized_message.lower():
            add_candidate(rewritten_message)

        add_candidate(normalized_message)
        return candidates

    def resolve_focus_hint(self, 
        *,
        user_message: str | None,
        candidates: list[object],
        fallback_current_file: str | None = None,
        allow_message_prefix: bool = True,
    ) -> str | None:
        def anchor_admissible(value: object) -> bool:
            cleaned = self.normalize_focus_candidate(value)
            if not cleaned:
                return False
            if allow_message_prefix:
                return True
            # Memory-anchor path (2026-10-08 + real-model maturity runs): a
            # narration opening ("我的脚本 assert 失败了", "我亲自写了下面的
            # 修改（用 None 哨兵") is the learner's phrasing — coach_context
            # may still carry it as focus chrome, but it must never win the
            # persisted anchor over the grounded current-file/task focus.
            return not looks_like_narration_opening(cleaned)

        for candidate in candidates:
            if self.is_specific_focus_candidate(candidate) and anchor_admissible(candidate):
                return self.normalize_focus_candidate(candidate)
        extracted = self.extract_focus_hint_from_message(
            user_message,
            allow_message_prefix=allow_message_prefix,
        )
        if extracted:
            return extracted
        if fallback_current_file:
            file_focus = self.normalize_focus_candidate(fallback_current_file)
            if file_focus:
                return file_focus
        for candidate in candidates:
            if anchor_admissible(candidate):
                return self.normalize_focus_candidate(candidate)
        return None

    def resolve_turn_focus_hint(self, 
        *,
        user_message: str | None,
        current_file_name: str | None = None,
        task_focus: str | None = None,
        stage_focus: str | None = None,
    ) -> str:
        if self.message_deserves_library_first_lookup(user_message):
            for candidate in self.resource_lookup_query_candidates(user_message):
                cleaned = self.normalize_focus_candidate(candidate)
                if cleaned and not self.resource_lookup_clause_describes_import_action(cleaned):
                    return cleaned
        extracted = self.extract_focus_hint_from_message(user_message)
        if extracted:
            # Memory-anchor anti-drift (real-model maturity runs): a narration
            # first clause ("我的脚本 assert 失败了", "我亲自写了下面的修改")
            # is the learner's phrasing, not a topic label — fall through to
            # the grounded current-file/task/stage focus instead.
            if not looks_like_narration_opening(extracted):
                return extracted
        for candidate in (current_file_name, task_focus, stage_focus):
            cleaned = self.normalize_focus_candidate(candidate)
            if cleaned:
                return cleaned
        return ""

    def function_guidance_current_file_name(self, 
        current_file: object | None,
        *,
        scenario: str | None,
    ) -> str:
        current_file_payload = self.normalize_current_file_payload(current_file)
        if current_file_payload is None:
            return ""
        current_file_name = (
            str(current_file_payload.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1]
        )
        if scenario == "function_guidance" and not is_code_like_current_file(current_file_payload):
            return ""
        return current_file_name

    def function_guidance_entry_points(self, 
        entry_points: object | None,
        *,
        scenario: str | None,
    ) -> list[str]:
        if not isinstance(entry_points, list) or not entry_points:
            return []
        cleaned_entry_points = [str(item).strip() for item in entry_points if str(item).strip()]
        if scenario != "function_guidance":
            return cleaned_entry_points
        return [entry_point for entry_point in cleaned_entry_points if is_code_like_entry_point(entry_point)]

    def function_guidance_starter_language(self, 
        message: str | None,
        current_file: object | None,
        coach_context: dict[str, object] | None = None,
    ) -> str:
        current_file_payload = self.normalize_current_file_payload(current_file)
        language_hint = ""
        if isinstance(current_file_payload, dict):
            language_hint = str(current_file_payload.get("language_id") or "").strip().lower()
        if not language_hint and isinstance(coach_context, dict):
            language_hint = str(coach_context.get("language_id") or "").strip().lower()
        if any(token in language_hint for token in ("python", "py", "ipynb")):
            return "python"
        if any(
            token in language_hint
            for token in ("typescript", "javascript", "tsx", "jsx", "ts", "js", "node")
        ):
            return "typescript"

        lowered_message = str(message or "").lower()
        if any(
            token in lowered_message
            for token in ("python", "pytest", "fastapi", "asyncio", "pydantic", "django", "uvicorn")
        ):
            return "python"
        if any(
            token in lowered_message
            for token in (
                "typescript",
                "javascript",
                "fetch",
                "node",
                "react",
                "next.js",
                "nextjs",
                "npm",
            )
        ):
            return "typescript"

        preferred_stack = str(coach_context.get("preferred_stack") or "").lower() if isinstance(coach_context, dict) else ""
        if "python" in preferred_stack:
            return "python"
        return "typescript"

    def function_guidance_starter_specs(self, language: str) -> dict[str, object]:
        if language == "python":
            relative_root = "knowledge/function-guidance/python"
            definition_path = f"{relative_root}/client.py"
            call_site_path = f"{relative_root}/usage.py"
            return {
                "language_id": "python",
                "label": "Trainer function guidance starter (Python)",
                "relative_root": relative_root,
                "definition_path": definition_path,
                "call_site_path": call_site_path,
                "definition_symbol": "build_headers",
                "call_site_symbol": "build_headers",
                "definition_content": (
                    "from collections.abc import Mapping\n\n"
                    "def build_headers(\n"
                    "    token: str | None,\n"
                    "    extra: Mapping[str, str] | None = None,\n"
                    ") -> dict[str, str]:\n"
                    "    headers = {\"Accept\": \"application/json\"}\n"
                    "    if token:\n"
                    "        headers[\"Authorization\"] = f\"Bearer {token}\"\n"
                    "    if extra:\n"
                    "        headers.update(dict(extra))\n"
                    "    return headers\n"
                ),
                "call_site_content": (
                    "from client import build_headers\n\n"
                    "def load_user(user_id: str, token: str | None) -> dict[str, object]:\n"
                    "    headers = build_headers(token, {\"X-User-Id\": user_id})\n"
                    "    return {\n"
                    "        \"path\": f\"/users/{user_id}\",\n"
                    "        \"headers\": headers,\n"
                    "    }\n"
                ),
            }

        relative_root = "knowledge/function-guidance/typescript/src"
        definition_path = f"{relative_root}/client.ts"
        call_site_path = f"{relative_root}/usage.ts"
        return {
            "language_id": "typescript",
            "label": "Trainer function guidance starter (TypeScript)",
            "relative_root": "knowledge/function-guidance/typescript",
            "definition_path": definition_path,
            "call_site_path": call_site_path,
            "definition_symbol": "fetchJson",
            "call_site_symbol": "fetchJson",
            "definition_content": (
                "export type FetchJsonOptions = {\n"
                "  method?: \"GET\" | \"POST\";\n"
                "  headers?: Record<string, string>;\n"
                "  retry?: number;\n"
                "};\n\n"
                "export async function fetchJson<T>(\n"
                "  url: string,\n"
                "  options: FetchJsonOptions = {},\n"
                "): Promise<T> {\n"
                "  const response = await fetch(url, {\n"
                "    method: options.method ?? \"GET\",\n"
                "    headers: options.headers,\n"
                "  });\n"
                "  if (!response.ok) {\n"
                "    throw new Error(`Request failed: ${response.status}`);\n"
                "  }\n"
                "  return (await response.json()) as T;\n"
                "}\n"
            ),
            "call_site_content": (
                "import { fetchJson } from \"./client\";\n\n"
                "type User = {\n"
                "  id: string;\n"
                "  name: string;\n"
                "};\n\n"
                "export async function loadUser(userId: string): Promise<User> {\n"
                "  return fetchJson<User>(`/api/users/${userId}`, {\n"
                "    headers: { \"x-trace-id\": userId },\n"
                "    retry: 1,\n"
                "  });\n"
                "}\n"
            ),
        }

    def should_prepare_function_guidance_starter(self, 
        *,
        scenario: str | None,
        current_file: object | None,
        coach_context: dict[str, object] | None,
    ) -> bool:
        if scenario != "function_guidance":
            return False
        if self.function_guidance_current_file_name(current_file, scenario=scenario):
            return False
        if not isinstance(coach_context, dict):
            return False
        if isinstance(coach_context.get("function_guidance_starter"), dict):
            return False
        project_entry_points = self.function_guidance_entry_points(
            coach_context.get("project_entry_points"),
            scenario=scenario,
        )
        return not project_entry_points

    def prepare_function_guidance_starter(self, 
        *,
        workspace_id: str,
        message: str | None,
        current_file: object | None,
        coach_context: dict[str, object] | None,
        response_language: str | None,
    ) -> dict[str, object] | None:
        sandbox_service = self.runtime.sandbox_service
        if sandbox_service is None:
            return None
        starter_language = self.function_guidance_starter_language(
            message,
            current_file,
            coach_context,
        )
        spec = self.function_guidance_starter_specs(starter_language)
        definition_preview = sandbox_service.write(
            workspace_id,
            SandboxWriteRequest(
                workspace_id=workspace_id,
                path=str(spec["definition_path"]),
                content=str(spec["definition_content"]),
                create=True,
            ),
        )
        call_site_preview = sandbox_service.write(
            workspace_id,
            SandboxWriteRequest(
                workspace_id=workspace_id,
                path=str(spec["call_site_path"]),
                content=str(spec["call_site_content"]),
                create=True,
            ),
        )
        sandbox_root = sandbox_service.ensure_workspace_root(workspace_id)
        definition_symbol = str(spec["definition_symbol"])
        return {
            "status": "ready",
            "label": str(spec["label"]),
            "language_id": str(spec["language_id"]),
            "relative_root": str(spec["relative_root"]),
            "workspace_root_path": str(sandbox_root),
            "definition_symbol": definition_symbol,
            "call_site_symbol": str(spec["call_site_symbol"]),
            "definition_path": definition_preview.relative_path or str(spec["definition_path"]),
            "call_site_path": call_site_preview.relative_path or str(spec["call_site_path"]),
            "definition_content": definition_preview.content or str(spec["definition_content"]),
            "call_site_content": call_site_preview.content or str(spec["call_site_content"]),
            "definition_excerpt": definition_preview.excerpt or str(spec["definition_content"]),
            "call_site_excerpt": call_site_preview.excerpt or str(spec["call_site_content"]),
            "boundary_note": localized_text(
                "Trainer-owned sandbox starter. Use it as a practice scaffold until a real project call site is available.",
                "这是 Trainer 自己管理的 sandbox starter。在真实项目里的 call site 就位之前，先把它当成练习脚手架。",
                response_language,
            ),
            "coach_instruction": localized_text(
                "Use this starter as the live call site for learn-first teaching instead of asking the learner for project code first.",
                "先用这个 starter 当作 live call site 来教学，不要一上来就要求学习者先提供项目代码。",
                response_language,
            ),
            "suggested_sequence": self.localized_actions(
                response_language,
                [
                    f"Open `{call_site_preview.relative_path or spec['call_site_path']}` and place the cursor on `{definition_symbol}`.",
                    "Use hover first, then signature help inside the argument list.",
                    f"Jump to definition in `{definition_preview.relative_path or spec['definition_path']}` and name the parameter and return contract.",
                ],
                [
                    f"先打开 `{call_site_preview.relative_path or spec['call_site_path']}`，把光标放到 `{definition_symbol}` 上。",
                    "先看 hover，再在参数位置里看 signature help。",
                    f"再跳到 `{definition_preview.relative_path or spec['definition_path']}` 的 definition，说明参数 contract 和返回 contract。",
                ],
            ),
        }

    def coach_context_scenario_value(self, coach_context: dict[str, object] | None) -> str:
        if not isinstance(coach_context, dict):
            return ""
        raw_candidates: list[object] = [coach_context.get("scenario")]
        for key in ("coaching_state", "coach_context", "coach_turn"):
            nested = coach_context.get(key)
            if isinstance(nested, dict):
                raw_candidates.append(nested.get("scenario"))
        for candidate in raw_candidates:
            normalized = str(candidate or "").strip()
            if normalized:
                return normalized
        return ""

    def infer_sequence_guidance_scenario(self, sequence: dict[str, object] | None) -> str:
        if not isinstance(sequence, dict):
            return ""
        explicit = str(sequence.get("scenario") or "").strip()
        if explicit in GUIDED_SEQUENCE_SCENARIOS:
            return explicit
        evidence_bits = [
            str(sequence.get("title") or "").strip(),
            str(sequence.get("source") or "").strip(),
            str(sequence.get("boundary_sentinel") or "").strip(),
        ]
        raw_steps = sequence.get("steps")
        if isinstance(raw_steps, list):
            for item in raw_steps[:6]:
                if not isinstance(item, dict):
                    continue
                evidence_bits.append(str(item.get("label") or "").strip())
                evidence_bits.append(str(item.get("text") or item.get("body") or "").strip())
        inferred = infer_message_coaching_scenario(
            " ".join(bit for bit in evidence_bits if bit).strip(),
            default="general",
        )
        return inferred if inferred in GUIDED_SEQUENCE_SCENARIOS else ""

    def sequence_visible_follow_up_copy(self, 
        scenario: str,
        *,
        title: str,
        response_language: str | None,
    ) -> tuple[str, str, str, str]:
        if scenario == "remote_workspace":
            close_line = localized_text(
                "For the smallest next move, tell me your current workspace label, path, or the exact step that feels unclear, and I'll keep coaching from this same sequence.",
                "现在先做最小验证：告诉我你当前的工作区标签、路径，或者你正卡在哪一步，我就按同一套顺序继续带你走。",
                response_language,
            )
            summary = f"Reuse the exact {title} sequence from the library and keep the reply grounded."
            next_step = "Ask for the learner's current workspace evidence or the exact step that feels unclear."
            teaching_note = "When the provider blanks, keep the same grounded sequence visible and continue from that lane."
            return close_line, summary, next_step, teaching_note
        if scenario == "debug_loop":
            close_line = localized_text(
                "For the smallest next move, tell me the breakpoint file, stack frame, watch value, or the exact debug-loop step that feels unclear, and I'll keep coaching from this same loop.",
                "现在先做最小验证：告诉我断点所在文件、当前 stack frame、watch value，或者 debug loop 里哪一步开始不符合预期，我就沿着同一条调试链继续带你走。",
                response_language,
            )
            summary = (
                f"Reuse the exact {title} sequence from the library and keep the reply anchored on the current VS Code debug loop."
            )
            next_step = (
                "Ask for the breakpoint file, current stack frame, watch value, or the exact debug-loop step that feels unclear."
            )
            teaching_note = (
                "When the provider blanks, keep the same debug loop visible and continue from the same breakpoint evidence."
            )
            return close_line, summary, next_step, teaching_note
        if scenario == "function_guidance":
            close_line = localized_text(
                "For the smallest next move, tell me the function name, one call site, or which hover / signature help / definition detail still feels unclear, and I'll keep coaching from this same function-guidance lane.",
                "现在先做最小验证：告诉我函数名、一个 call site，或者 hover / signature help / definition 里哪一处还没看懂，我就沿着同一条 function-guidance 主线继续带你走。",
                response_language,
            )
            summary = (
                f"Reuse the exact {title} sequence from the library and keep the reply anchored on one live call site."
            )
            next_step = (
                "Ask for the function name, one call site, or the hover / signature help / definition evidence that still feels unclear."
            )
            teaching_note = (
                "When the provider blanks, keep the same function-contract sequence visible and continue from one call site."
            )
            return close_line, summary, next_step, teaching_note
        close_line = localized_text(
            "For the smallest next move, tell me the exact step that feels unclear, and I'll keep coaching from this same sequence.",
            "现在先做最小验证：告诉我哪一步最不确定，我就沿着同一套顺序继续带你走。",
            response_language,
        )
        summary = f"Reuse the exact {title} sequence from the library and keep the reply visible."
        next_step = "Ask for the exact step that feels unclear."
        teaching_note = "When the provider blanks, keep the same sequence visible and continue from that lane."
        return close_line, summary, next_step, teaching_note

    def build_local_sequence_visible_fallback(self, 
        *,
        coach_context: dict[str, object] | None,
        response_language: str | None,
    ) -> dict[str, str] | None:
        if not isinstance(coach_context, dict):
            return None
        raw_sequences = coach_context.get("resource_sequence_guidance")
        if not isinstance(raw_sequences, list) or not raw_sequences:
            return None
        first_sequence = raw_sequences[0]
        if not isinstance(first_sequence, dict):
            return None
        raw_steps = first_sequence.get("steps")
        if not isinstance(raw_steps, list):
            return None
        steps: list[tuple[str, str]] = []
        for item in raw_steps[:6]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            text = str(item.get("text") or item.get("body") or "").strip()
            if not label or not text:
                continue
            steps.append((label, text))
        if len(steps) < 2:
            return None
        title = str(first_sequence.get("title") or "the library sequence").strip()
        coach_scenario = self.coach_context_scenario_value(coach_context)
        sequence_scenario = self.infer_sequence_guidance_scenario(first_sequence)
        if (
            coach_scenario in GUIDED_SEQUENCE_SCENARIOS
            and sequence_scenario
            and sequence_scenario != coach_scenario
        ):
            return None
        effective_scenario = (
            coach_scenario
            if coach_scenario in GUIDED_SEQUENCE_SCENARIOS
            else sequence_scenario
        )
        boundary = str(first_sequence.get("boundary_sentinel") or "").strip()
        close_line, summary, next_step, teaching_note = self.sequence_visible_follow_up_copy(
            effective_scenario,
            title=title,
            response_language=response_language,
        )
        if prefers_chinese(response_language):
            lines = [f"我先按资料库里的原始顺序把 {title} 摆出来，不额外加步骤：", ""]
            for label, text in steps:
                lines.append(f"- **{label}**：{text}")
            if boundary:
                lines.append("")
                lines.append(f"边界哨兵：**{boundary}**。")
            lines.append("")
            lines.append(close_line)
        else:
            lines = [f"I'll restate the exact {title} sequence from the library before we continue:", ""]
            for label, text in steps:
                lines.append(f"- **{label}**: {text}")
            if boundary:
                lines.append("")
                lines.append(f"Boundary sentinel: **{boundary}**.")
            lines.append("")
            lines.append(close_line)
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

    def reply_explicitly_lists_prepared_sequence(self, 
        reply: str,
        *,
        coach_context: dict[str, object] | None,
    ) -> bool:
        if not isinstance(coach_context, dict):
            return True
        raw_sequences = coach_context.get("resource_sequence_guidance")
        if not isinstance(raw_sequences, list) or not raw_sequences:
            return True
        if re.search(
            r"(^|\n)\s*(?:[-*]\s*)?(?:Step\s*\d+|第\s*[0-9一二三四五六七八九十]+\s*步|\d+\.)",
            str(reply or ""),
            re.IGNORECASE | re.MULTILINE,
        ):
            return True
        return False

    def guided_lane_visible_summary(self, 
        scenario: str,
        *,
        response_language: str | None,
    ) -> str:
        normalized = str(scenario or "").strip().lower()
        if normalized == "remote_workspace":
            return localized_text(
                "Establish the VS Code remote workspace boundary before widening the lesson.",
                "先建立 VS Code remote workspace 的边界，再扩大这一轮教学。",
                response_language,
            )
        if normalized == "debug_loop":
            return localized_text(
                "Build one trustworthy VS Code debug loop before widening the investigation.",
                "先建立一条可信的 VS Code debug loop，再扩大这一轮排查。",
                response_language,
            )
        if normalized == "function_guidance":
            return localized_text(
                "Anchor function guidance to one live call site before widening the explanation.",
                "先把 function guidance 锚定到一个真实 call site，再扩展说明。",
                response_language,
            )
        return ""

    def function_guidance_visible_repair_reply_parts(self, 
        coach_context: dict[str, object] | None,
        *,
        response_language: str | None,
    ) -> tuple[str, str]:
        chinese = prefers_chinese(response_language)
        if isinstance(coach_context, dict):
            starter = coach_context.get("function_guidance_starter")
            if isinstance(starter, dict) and str(starter.get("status") or "").strip() == "ready":
                call_site_path = str(starter.get("call_site_path") or "").strip() or "the prepared call site"
                definition_path = str(starter.get("definition_path") or "").strip() or "the prepared definition"
                symbol = (
                    str(starter.get("definition_symbol") or "").strip()
                    or str(starter.get("call_site_symbol") or "").strip()
                    or "the prepared function"
                )
                if chinese:
                    return (
                        f"这一轮我会先把函数理解锚定在准备好的 live call site `{call_site_path}`，再用 hover、signature help 和 Go to Definition 读稳 `{symbol}` 的 contract。",
                        f"下一步：打开 `{call_site_path}`，把光标放到 `{symbol}` 上，先看 hover 和 signature help，再跳到 `{definition_path}` 说清参数 contract 和返回 contract。",
                    )
                return (
                    f"I will keep this anchored to the prepared live call site in `{call_site_path}`, then use hover, signature help, and Go to Definition to read `{symbol}` with a stable contract.",
                    f"Next step: open `{call_site_path}`, place the cursor on `{symbol}`, check hover and signature help, then jump to `{definition_path}` and name the parameter and return contract.",
                )
        if chinese:
            return (
                "这一轮先只围绕一个真实 call site 读函数 contract。先用 hover、signature help 和 Go to Definition 看清它要什么、返回什么，再决定要不要展开实现。",
                "下一步：带回函数名、它期望什么，以及哪个 call site 证明了这个判断。",
            )
        return (
            "I will keep this turn anchored to one live call site and read the function contract before widening the explanation. Use hover, signature help, and Go to Definition to confirm what the function expects and what it returns.",
            "Next step: return the function name, what it expects, and which call site proves that reading.",
        )

    def build_guided_lane_visible_fallback(self, 
        *,
        scenario: str,
        response_language: str | None,
        coach_context: dict[str, object] | None,
    ) -> dict[str, str] | None:
        normalized = str(scenario or "").strip().lower()
        if normalized not in GUIDED_VISIBLE_REPAIR_SCENARIOS:
            return None
        summary = self.guided_lane_visible_summary(normalized, response_language=response_language)
        next_step = ""
        if normalized == "remote_workspace":
            if prefers_chinese(response_language):
                lines = [
                    "这一轮先只守住 VS Code remote workspace 的边界。先讲清工作区边界和文件到底落在哪台机器上，再做一个最小验证动作，确认 Trainer 不会越界写错地方。",
                    "下一步：在你当前的 VS Code 窗口里，给我一个能证明工作区落点的真实信号，比如 Explorer 里的路径、终端里的 `pwd`，或者左下角的 remote host 标签。",
                ]
            else:
                lines = [
                    "I will keep this turn inside one real VS Code remote lane and lock the workspace boundary first. Teach where the files actually live, then do one minimal verification move before any wider setup talk.",
                    "Next step: return one real boundary signal from the current VS Code window, such as an Explorer path, `pwd`, or the remote host label.",
                ]
            next_step = self.local_continuation_step_for_scenario(normalized, response_language)
        elif normalized == "debug_loop":
            if prefers_chinese(response_language):
                lines = [
                    "这一轮先只搭一条可信的 VS Code debug loop。先定一个 breakpoint 或 `launch.json` 动作，只停一次，只核对一个 value、branch 或 stack frame。",
                    "下一步：先选一个 breakpoint 或 `launch.json` 动作，再告诉我你准备停在哪里，以及要核对哪一个 value、branch 或 stack frame。",
                ]
            else:
                lines = [
                    "I will keep this turn inside one trustworthy VS Code debug loop. Pick one breakpoint or one `launch.json` move, pause once, and inspect one value, branch, or stack frame before widening anything.",
                    "Next step: choose one breakpoint or `launch.json` move, then tell me where you will pause and what single value, branch, or stack frame you expect to inspect there.",
                ]
            next_step = self.local_continuation_step_for_scenario(normalized, response_language)
        else:
            lines = list(
                self.function_guidance_visible_repair_reply_parts(
                    coach_context,
                    response_language=response_language,
                )
            )
            next_step = lines[1] if len(lines) > 1 else ""
        next_step = strip_visible_next_step_prefix(next_step or (lines[1] if len(lines) > 1 else ""))
        if next_step[:1].isascii() and next_step[:1].islower():
            # Stripping a "Next step:" label leaves a mid-sentence remainder;
            # the structured next step is a standalone sentence, so restore the
            # sentence-initial capital (same rule as normalize_visible_coach_text).
            next_step = f"{next_step[:1].upper()}{next_step[1:]}"
        teaching_note = localized_text(
            "When visible coach text drifts across guided lanes, rebuild the answer from the active lane before persisting it.",
            "当可见教练回复串到别的 guided lane 时，先按当前主线重建回答，再把结果持久化。",
            response_language,
        )
        reply = "\n\n".join(part for part in lines if str(part or "").strip()).strip()
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

    def guided_lane_visible_reply_is_generic(self, value: object) -> bool:
        cleaned = normalize_visible_coach_text(value) or str(value or "").strip()
        if not cleaned:
            return True
        lowered = re.sub(r"\s+", " ", cleaned).casefold()
        if len(cleaned) <= 10:
            return True
        generic_replies = {
            "ok",
            "okay",
            "got it",
            "sounds good",
            "好的",
            "好",
            "明白",
            "收到",
            "继续",
        }
        return lowered in generic_replies

    def build_guided_lane_stable_visible_reply(self, 
        *,
        scenario: str,
        response_language: str | None,
        coach_context: dict[str, object] | None,
    ) -> dict[str, str] | None:
        fallback = self.build_guided_lane_visible_fallback(
            scenario=scenario,
            response_language=response_language,
            coach_context=coach_context,
        )
        if fallback is None:
            return None
        return fallback

    def guided_lane_visible_reply_has_foreign_markers(self, 
        value: object,
        *,
        scenario: str | None,
    ) -> bool:
        normalized_scenario = str(scenario or "").strip().lower()
        if normalized_scenario not in GUIDED_VISIBLE_REPAIR_SCENARIOS:
            return False
        cleaned = normalize_visible_coach_text(value) or str(value or "").strip()
        if not cleaned:
            return False
        lowered = re.sub(r"\s+", " ", cleaned).casefold()
        marker_map = self.guided_lane_visible_marker_map()
        for lane, markers in marker_map.items():
            if lane == normalized_scenario:
                continue
            for marker in markers:
                if marker.casefold() in lowered:
                    return True
        return False

    def apply_guided_lane_visible_fallback(self, 
        *,
        reply: str,
        scenario: str,
        learner_message: str | None,
        response_language: str | None,
        coach_turn: dict[str, object] | None,
        agent_meta: dict[str, object] | None,
    ) -> tuple[str, dict[str, object] | None, dict[str, object], bool]:
        normalized = str(scenario or "").strip().lower()
        normalized_agent_meta = dict(agent_meta or {})
        # An explanation or worked-example request needs its answer first.
        if self.message_requests_explicit_explanation_or_example(learner_message):
            return reply, coach_turn, normalized_agent_meta, False
        if normalized not in GUIDED_VISIBLE_REPAIR_SCENARIOS:
            return reply, coach_turn, normalized_agent_meta, False
        texts_to_check = [
            reply,
            normalized_agent_meta.get("summary"),
            normalized_agent_meta.get("next_step"),
            normalized_agent_meta.get("resume_thread"),
            normalized_agent_meta.get("teaching_note"),
        ]
        if not any(
            self.text_contaminates_guided_lane(
                value,
                scenario=normalized,
                learner_message=learner_message,
            )
            for value in texts_to_check
        ):
            return reply, coach_turn, normalized_agent_meta, False
        coach_context = (
            normalized_object_mapping(coach_turn.get("coach_context"))
            if isinstance(coach_turn, dict)
            else None
        )
        fallback = self.build_guided_lane_visible_fallback(
            scenario=normalized,
            response_language=response_language,
            coach_context=coach_context,
        )
        if fallback is None:
            return reply, coach_turn, normalized_agent_meta, False
        normalized_agent_meta["summary"] = fallback["summary"]
        normalized_agent_meta["next_step"] = fallback["next_step"]
        normalized_agent_meta["teaching_note"] = fallback["teaching_note"]
        normalized_agent_meta["resume_thread"] = fallback["resume_thread"]
        normalized_agent_meta["scenario"] = normalized
        normalized_agent_meta["guided_lane_visible_repaired"] = True
        repaired_coach_turn = coach_turn
        if isinstance(coach_turn, dict):
            repaired_coach_turn = self.merge_agent_finalize_into_coach_turn(
                {
                    **coach_turn,
                    "scenario": normalized,
                },
                summary=fallback["summary"],
                next_step=fallback["next_step"],
                blocker=normalized_agent_meta.get("blocker"),
                resume_thread=fallback["resume_thread"],
                decision=normalized_agent_meta.get("decision"),
                teaching_note=fallback["teaching_note"],
                confidence=normalized_agent_meta.get("confidence"),
                evidence=normalized_agent_meta.get("evidence"),
            )
        return fallback["reply"], repaired_coach_turn, normalized_agent_meta, True
