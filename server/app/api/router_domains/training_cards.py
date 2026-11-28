"""Workspace coaching preferences, training card context preparation, generation, and learn-first activation."""

from __future__ import annotations

import logging
import os
import posixpath
import re
from pathlib import Path

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from ...core.models import (
    ActiveCardSelectionResult,
    CardGenerationRequest,
    CoachDefaults,
    DependencyUsageEvidence,
    ResourceKnowledgeEvidence,
    ResourceRecord,
    ResponseLanguage,
    SessionMessageRequest,
    TaskSpec,
    TurnRequest,
    UserProfile,
)
from ...core.workspace_live_identity import (
    live_training_why_this_card,
)
from ...llm.prompts import infer_coaching_scenario as infer_message_coaching_scenario
from ...llm.prompts import infer_learner_signal as infer_message_learner_signal
from ...workspace.classifier import (
    is_code_like_current_file,
)
from ...workspace.provisioning import (
    ProjectProvisioningIntegrityError,
)
from .._helpers import (
    localized_text,
    prefers_chinese,
    supported_response_language,
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
from .training_cards_activation_mixin import TrainingCardsActivationMixin

logger = logging.getLogger(__name__)


class TrainingCardsDomainMixin(RouterDomainBase, TrainingCardsActivationMixin):
    """Workspace coaching preferences, training card context preparation, generation, and learn-first activation."""

    def select_active_training_card(self, workspace_id: str) -> ActiveCardSelectionResult:
        cards = [card for card in self.runtime.memory_service.get_cards(workspace_id)
                 if card.review_state == "saved"]
        live_id = self.runtime.memory_service.live_selected_training_card_id(workspace_id)
        response_language = self.workspace_response_language(workspace_id)
        zh = prefers_chinese(response_language)
        no_live_why = (
            "No live training card is selected yet."
            if not zh
            else "尚未选择有效的训练卡片。"
        )
        no_live_fallback = (
            "Generate a training card explicitly before continuing."
            if not zh
            else "请先显式生成一张训练卡片，再继续。"
        )
        no_live_next = (
            "Generate the next truthful training card."
            if not zh
            else "先生成下一张如实的训练卡片。"
        )
        current_card_why = (
            "This is the current training card."
            if not zh
            else "这是当前的训练卡片。"
        )
        blocker_fallback = (
            "Return to coach with the exact blocker and verification output."
            if not zh
            else "带着确切的阻塞点和验证输出回到 Coach。"
        )
        evidence_next = (
            "Update evidence and route the next training step."
            if not zh
            else "更新证据，然后路由下一个训练步骤。"
        )
        # Leftover stored cards / title / current_step must not invent selectedCardId.
        # Live only when recovered runtime still carries a matching card id.
        if not live_id:
            return ActiveCardSelectionResult(
                why_this_card=no_live_why,
                fallback_action=no_live_fallback,
                next_after_completion=no_live_next,
                candidate_count=len(cards),
                eligible_count=0,
            )
        live_card = next((card for card in cards if card.card_id == live_id), None)
        if live_card is None:
            return ActiveCardSelectionResult(
                why_this_card=no_live_why,
                fallback_action=no_live_fallback,
                next_after_completion=no_live_next,
                candidate_count=len(cards),
                eligible_count=0,
            )
        router_service = getattr(self.runtime, "card_router_service", None)
        if router_service is None:
            leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
            return ActiveCardSelectionResult(
                selected_card=live_card,
                selected_card_id=live_card.card_id,
                selection_score=100.0,
                why_this_card=live_training_why_this_card(
                    plan=leftover_plan,
                    runtime=leftover_runtime,
                    existing=leftover_runtime,
                    card_title=live_card.title,
                    why_now=live_card.why_now,
                    kind="current",
                )
                or current_card_why,
                fallback_action=blocker_fallback,
                next_after_completion=evidence_next,
                candidate_count=len(cards),
                eligible_count=1,
            )
        selection = router_service.select_active_card(
            cards,
            self.routing_learner_state(workspace_id),
            self.routing_plan_state(workspace_id),
            response_language=response_language,
        )
        # Router may prefer another leftover; keep live identity fail-closed.
        if selection.selected_card_id != live_id:
            leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
            return ActiveCardSelectionResult(
                selected_card=live_card,
                selected_card_id=live_card.card_id,
                selection_score=100.0,
                why_this_card=live_training_why_this_card(
                    plan=leftover_plan,
                    runtime=leftover_runtime,
                    existing=leftover_runtime,
                    card_title=live_card.title,
                    why_now=live_card.why_now,
                    kind="current",
                )
                or current_card_why,
                fallback_action=selection.fallback_action or blocker_fallback,
                next_after_completion=selection.next_after_completion or evidence_next,
                candidate_count=len(cards),
                eligible_count=1,
            )
        return selection

    def routing_changed(self, 
        existing: ActiveCardSelectionResult | None,
        selection: ActiveCardSelectionResult,
    ) -> bool:
        if existing is None:
            return True
        return existing.model_dump(mode="json") != selection.model_dump(mode="json")

    def sync_active_training_card(self, workspace_id: str) -> ActiveCardSelectionResult:
        selection = self.select_active_training_card(workspace_id)
        existing = self.runtime.memory_service.snapshot(workspace_id).active_training_card_routing
        if self.routing_changed(existing, selection):
            selection = self.runtime.memory_service.persist_active_card_selection(workspace_id, selection)
            self.refresh_workspace_sessions(workspace_id)
        return selection

    def default_profile(self) -> UserProfile:
        return UserProfile(
            long_term_goal="Build stronger implementation habits",
            long_term_goals=["Build stronger implementation habits"],
            weekly_hours=4,
            teaching_style="auto",
            answer_policy="auto",
            preferred_libraries=[],
        )

    def resolved_profile(self, workspace_id: str) -> UserProfile:
        return self.runtime.repository.get_profile(workspace_id) or self.default_profile()

    def normalize_answer_mode(self, value: str | None) -> str:
        if value == "auto":
            return "guided"
        if value == "coach-first":
            return "guided"
        if value in {"guided", "balanced", "direct"}:
            return value
        return "guided"

    def answer_mode_preference_for_persistence(self, 
        raw_requested: str | None,
        saved_preference: str | None,
        effective_mode: str | None,
        fallback_mode: str | None,
    ) -> str | None:
        requested = str(raw_requested or "").strip()
        if requested:
            return requested
        if str(saved_preference or "").strip() == "auto":
            return "auto"
        return effective_mode or fallback_mode

    def normalize_teaching_style(self, value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"guided", "concept-first", "hands-on", "challenging"}:
            return normalized
        if normalized == "auto":
            return "guided"
        return "guided"

    def message_requests_direct_answer(self, message: str | None) -> bool:
        lowered = str(message or "").strip().lower()
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "just show me",
                "show me the fix",
                "give me the fix",
                "show me the code",
                "give me the code",
                "full code",
                "complete code",
                "just tell me the answer",
                "直接给我",
                "直接告诉我",
                "直接给答案",
                "给我完整代码",
                "完整代码",
                "直接修",
            )
        )

    def message_requests_concept_first(self, message: str | None) -> bool:
        lowered = str(message or "").strip().lower()
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "why does",
                "how does",
                "explain",
                "mechanism",
                "principle",
                "concept",
                "difference",
                "what is the idea",
                "原理",
                "机制",
                "解释",
                "概念",
                "区别",
                "为什么",
                "先讲",
            )
        )

    def message_requests_hands_on_style(self, message: str | None) -> bool:
        lowered = str(message or "").strip().lower()
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "implement with me",
                "build with me",
                "code with me",
                "walk me through the code",
                "pair on this",
                "hands-on",
                "带我实现",
                "边做边学",
                "一起写",
                "带我改",
                "跟我改",
                "实操",
                "动手",
            )
        )

    def message_requests_challenging_style(self, message: str | None) -> bool:
        lowered = str(message or "").strip().lower()
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "challenge me",
                "quiz me",
                "test me",
                "let me try first",
                "don't tell me yet",
                "hold back the answer",
                "让我先试",
                "先别告诉我",
                "先不要告诉我",
                "考考我",
                "挑战我",
                "先让我想",
            )
        )

    def message_requests_guided_coaching(self, message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "guide me",
                "keep guiding",
                "continue guiding",
                "coach me",
                "teach me",
                "walk me through",
                "help me learn",
                "practice with me",
                "带我",
                "引导我",
                "继续引导",
                "教我",
                "一步一步",
                "陪我练",
                "带我练",
                "给我训练题",
            )
        )

    def message_requests_explicit_explanation_or_example(self, message: str | None) -> bool:
        """Give a concise answer unless the learner explicitly asks to withhold it."""
        lowered = str(message or "").strip().lower()
        if not lowered or self.message_requests_challenging_style(message):
            return False
        example_markers = (
            "example",
            "worked example",
            "show an example",
            "give an example",
            "示例",
            "举例",
            "例子",
        )
        return self.message_requests_concept_first(message) or any(
            marker in lowered for marker in example_markers
        )

    def current_file_diagnostics_count(self, current_file: dict[str, object] | None) -> int:
        if not isinstance(current_file, dict):
            return 0
        diagnostics = current_file.get("diagnostics")
        if isinstance(diagnostics, list):
            return len(diagnostics)
        for key in ("diagnostic_errors", "diagnosticErrors"):
            value = current_file.get(key)
            if isinstance(value, int) and value > 0:
                return value
        return 0

    def resolve_auto_answer_mode(self, 
        *,
        message: str | None,
        current_file: dict[str, object] | None,
        coach_context: dict[str, object] | None = None,
    ) -> str:
        normalized_message = str(message or "")
        normalized_current_file = current_file if isinstance(current_file, dict) else None
        normalized_context = coach_context if isinstance(coach_context, dict) else None

        if self.message_requests_direct_answer(normalized_message):
            return "direct"

        learner_signal = infer_message_learner_signal(
            normalized_message,
            normalized_current_file,
            normalized_context,
        )
        if learner_signal == "blocked":
            return "direct"

        scenario = infer_message_coaching_scenario(
            normalized_message,
            normalized_current_file,
            normalized_context,
            default="idea_implementation",
        )
        if self.message_requests_implicit_learn_first_training(
            normalized_message,
            requested_scenario=scenario,
        ):
            return "guided"
        if self.message_requests_guided_coaching(normalized_message) or self.message_requests_challenging_style(
            normalized_message
        ):
            return "guided"
        if self.message_requests_hands_on_style(normalized_message):
            return "balanced"
        return "direct"

    def resolve_auto_teaching_style(self, 
        *,
        message: str | None,
        current_file: dict[str, object] | None,
        coach_context: dict[str, object] | None = None,
    ) -> str:
        normalized_message = str(message or "")
        normalized_current_file = current_file if isinstance(current_file, dict) else None
        normalized_context = coach_context if isinstance(coach_context, dict) else None

        if self.message_requests_direct_answer(normalized_message):
            return "hands-on"
        if self.message_requests_hands_on_style(normalized_message):
            return "hands-on"
        if self.message_requests_concept_first(normalized_message):
            return "concept-first"

        learner_signal = infer_message_learner_signal(
            normalized_message,
            normalized_current_file,
            normalized_context,
        )
        if learner_signal == "blocked":
            return "hands-on"

        scenario = infer_message_coaching_scenario(
            normalized_message,
            normalized_current_file,
            normalized_context,
            default="idea_implementation",
        )
        if scenario in {"remote_workspace", "debug_loop"}:
            return "hands-on"
        if scenario in {"function_guidance", "principle"}:
            return "concept-first"
        if self.current_file_diagnostics_count(normalized_current_file) > 0:
            return "hands-on"
        if self.message_requests_challenging_style(normalized_message) and learner_signal == "steady":
            return "challenging"
        return "guided"

    def preferred_answer_mode(self, 
        workspace_id: str,
        requested: str | None,
        profile: UserProfile | None,
    ) -> str | None:
        if requested and requested.strip():
            return requested.strip()
        workspace = self.workspace_preferences(workspace_id)
        saved = workspace.get("answer_mode")
        if isinstance(saved, str) and saved.strip():
            return saved.strip()
        return profile.answer_policy if profile else None

    def preferred_teaching_style(self, 
        requested: str | None,
        profile: UserProfile | None,
    ) -> str | None:
        if requested and requested.strip():
            return requested.strip()
        return profile.teaching_style if profile else None

    def workspace_preferences(self, workspace_id: str) -> dict[str, object]:
        snapshot = self.runtime.memory_service.snapshot(workspace_id)
        return snapshot.workspace if isinstance(snapshot.workspace, dict) else {}

    def persist_requested_response_language(self, 
        workspace_id: str,
        requested: str | None,
    ) -> ResponseLanguage | None:
        response_language = supported_response_language(requested)
        if response_language is not None:
            self.runtime.memory_service.update_workspace_state(
                workspace_id,
                response_language=response_language,
            )
        return response_language

    def effective_response_language(self, 
        workspace_id: str,
        requested: str | None,
        message: str | None = None,
    ) -> ResponseLanguage | None:
        requested_language = supported_response_language(requested)
        if requested_language is not None:
            return requested_language
        workspace = self.workspace_preferences(workspace_id)
        saved_language = supported_response_language(workspace.get("response_language"))
        if saved_language is not None:
            return saved_language
        if isinstance(message, str) and any("\u3400" <= char <= "\u9fff" for char in message):
            return "zh-CN"
        return None

    def effective_answer_mode(self, 
        workspace_id: str,
        requested: str | None,
        profile: UserProfile | None,
        *,
        message: str | None = None,
        current_file: dict[str, object] | None = None,
        coach_context: dict[str, object] | None = None,
    ) -> str:
        requested_mode = str(requested or "").strip().lower()
        if (
            self.message_requests_explicit_explanation_or_example(message)
            and requested_mode != "coach-first"
        ):
            return "direct"
        preferred_mode = self.preferred_answer_mode(workspace_id, requested, profile)
        normalized_preference = str(preferred_mode or "").strip()
        if normalized_preference == "auto":
            return self.resolve_auto_answer_mode(
                message=message,
                current_file=current_file,
                coach_context=coach_context,
            )
        return self.normalize_answer_mode(normalized_preference or None)

    def effective_teaching_style(self, 
        requested: str | None,
        profile: UserProfile | None,
        *,
        message: str | None = None,
        current_file: dict[str, object] | None = None,
        coach_context: dict[str, object] | None = None,
    ) -> str:
        preferred_style = self.preferred_teaching_style(requested, profile)
        normalized_preference = str(preferred_style or "").strip()
        if normalized_preference == "auto":
            return self.resolve_auto_teaching_style(
                message=message,
                current_file=current_file,
                coach_context=coach_context,
            )
        return self.normalize_teaching_style(normalized_preference or None)

    def profile_with_teaching_style(self, 
        profile: UserProfile,
        teaching_style: str | None,
    ) -> UserProfile:
        normalized_style = str(teaching_style or "").strip().lower()
        if not normalized_style:
            return profile
        if str(profile.teaching_style or "").strip().lower() == normalized_style:
            return profile
        return profile.model_copy(update={"teaching_style": normalized_style})

    def effective_coach_defaults(self, 
        workspace_id: str,
        requested: CoachDefaults | None,
    ) -> CoachDefaults | None:
        if requested is not None:
            return requested
        workspace = self.workspace_preferences(workspace_id)
        saved = workspace.get("coach_defaults")
        if isinstance(saved, CoachDefaults):
            return saved
        if isinstance(saved, dict):
            try:
                return CoachDefaults.model_validate(saved)
            except Exception as exc:
                logger.debug("Ignoring invalid saved CoachDefaults: %s", exc)
                return None
        return None

    def request_with_workspace_defaults(self, 
        request: TurnRequest | SessionMessageRequest,
        *,
        workspace_id: str,
        profile: UserProfile | None,
    ) -> TurnRequest | SessionMessageRequest:
        response_language = self.effective_response_language(workspace_id, request.response_language, request.message)
        request_current_file = (
            jsonable_encoder(request.current_file) if getattr(request, "current_file", None) is not None else None
        )
        answer_mode = self.effective_answer_mode(
            workspace_id,
            request.answer_mode,
            profile,
            message=request.message,
            current_file=request_current_file if isinstance(request_current_file, dict) else None,
        )
        teaching_style = self.effective_teaching_style(
            request.teaching_style,
            profile,
            message=request.message,
            current_file=request_current_file if isinstance(request_current_file, dict) else None,
        )
        coach_defaults = self.effective_coach_defaults(workspace_id, request.coach_defaults)
        update = {
            "response_language": response_language,
            "answer_mode": answer_mode,
            "teaching_style": teaching_style,
            "coach_defaults": coach_defaults,
        }
        if isinstance(request, TurnRequest) and request.intent == "plan":
            frozen_blocks = self.leftover_frozen_blocks_turn_generation(workspace_id)
            if not request.formal_plan_mutation or frozen_blocks:
                update["intent"] = "coach"
                # Discussion / frozen plan turns must not silently keep formalPlanMutation.
                update["formal_plan_mutation"] = False
            # Explicit plan generate/save keeps formal_plan_mutation even under high urgency
            # (same leftover pattern as /plan/generate and /training/generate-card).
        elif isinstance(request, TurnRequest):
            # Coaching / task / review / resources: never silent formalPlanMutation.
            if request.formal_plan_mutation:
                update["formal_plan_mutation"] = False
        elif getattr(request, "formal_plan_mutation", False):
            # /session/message has no plan intent - never formal mutate.
            update["formal_plan_mutation"] = False
        if isinstance(request, TurnRequest) and request.intent in {"next_task", "task"}:
            if self.should_remap_task_intent_without_live_plan(
                workspace_id,
                message=getattr(request, "message", None),
            ):
                update["intent"] = "coach"
        return request.model_copy(update=update)

    def frozen_plan_mutation_notice(self, response_language: str | None) -> str:
        messages = {
            "zh-CN": "这条计划已冻结。请先恢复为可编辑状态，再修改正式计划。",
            "en-US": "This plan is frozen. Resume it before changing the formal plan.",
            "es-ES": "Este plan está congelado. Reanúdalo antes de cambiar el plan principal.",
            "fr-FR": "Ce plan est gelé. Reprenez-le avant de modifier le plan principal.",
            "de-DE": "Dieser Plan ist eingefroren. Setzen Sie ihn fort, bevor Sie den Hauptplan ändern.",
            "ja-JP": "この計画は固定されています。正式な計画を変更する前に、再開してください。",
            "ko-KR": "이 계획은 고정되어 있습니다. 정식 계획을 바꾸기 전에 다시 시작하세요.",
            "pt-BR": "Este plano está congelado. Retome-o antes de alterar o plano principal.",
        }
        if response_language is None:
            return messages["en-US"]
        return messages.get(response_language, messages["en-US"])

    def normalize_current_file_payload(self, current_file: object | None) -> dict[str, object] | None:
        if current_file is None:
            return None
        if isinstance(current_file, dict):
            return current_file
        model_dump = getattr(current_file, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            return dumped if isinstance(dumped, dict) else None
        legacy_dict = getattr(current_file, "dict", None)
        if callable(legacy_dict):
            dumped = legacy_dict()
            return dumped if isinstance(dumped, dict) else None
        return None

    def current_file_fact_value(self, 
        current_file: dict[str, object],
        snake_case: str,
        camel_case: str,
    ) -> object:
        value = current_file.get(snake_case)
        return value if value is not None else current_file.get(camel_case)

    def is_training_placeholder_or_uri(self, value: str) -> bool:
        lowered = value.casefold()
        if any(marker in value for marker in ("<", ">", "{{", "}}", "${")):
            return True
        if re.match(r"^[a-z][a-z0-9+.-]*://", value, flags=re.IGNORECASE):
            return True
        if re.match(r"^[a-z][a-z0-9+.-]*:", value, flags=re.IGNORECASE) and not re.match(
            r"^[a-z]:[\\/]", value, flags=re.IGNORECASE
        ):
            return True
        return any(token in lowered for token in ("[redacted", "placeholder", "live call site"))

    def normalize_training_path(self, value: object) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        if not raw or len(raw) > 480 or "\x00" in raw or self.is_training_placeholder_or_uri(raw):
            return ""
        normalized = posixpath.normpath(raw)
        if normalized in {"", ".", "/"} or normalized.startswith("../") or normalized == "..":
            return ""
        return normalized.rstrip("/")

    def is_absolute_training_path(self, value: str) -> bool:
        return value.startswith("/") or value.startswith("//") or bool(
            re.match(r"^[a-z]:/", value, flags=re.IGNORECASE)
        )

    def relative_training_file_path(self, value: object, workspace_root: object) -> str:
        path = self.normalize_training_path(value)
        if not path:
            return ""
        if not self.is_absolute_training_path(path):
            return path

        root = self.normalize_training_path(workspace_root)
        if not root or not self.is_absolute_training_path(root):
            return ""
        is_posix_abs = (
            path.startswith("/")
            and root.startswith("/")
            and not (path.startswith("//") or root.startswith("//"))
        )
        is_windows_native_abs = os.name == "nt" and bool(
            re.match(r"^[a-z]:/", path, flags=re.IGNORECASE)
            and re.match(r"^[a-z]:/", root, flags=re.IGNORECASE)
        )
        if is_posix_abs or is_windows_native_abs:
            try:
                relative = Path(path).resolve().relative_to(Path(root).resolve())
            except (OSError, RuntimeError, ValueError):
                return ""
            return relative.as_posix() if relative.parts else ""
        comparison_path = path.casefold() if re.match(r"^[a-z]:/", path, flags=re.IGNORECASE) else path
        comparison_root = root.casefold() if re.match(r"^[a-z]:/", root, flags=re.IGNORECASE) else root
        if comparison_path == comparison_root:
            return ""
        prefix = f"{comparison_root}/"
        if not comparison_path.startswith(prefix):
            return ""
        return path[len(root) + 1 :]

    def redact_training_fact_text(self, value: object, limit: int, *, collapse: bool = False) -> str:
        text = str(value or "").replace("\x00", "").strip()
        if not text:
            return ""
        text = text[: max(limit * 4, 1024)]
        text = re.sub(
            r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}",
            "Bearer [redacted]",
            text,
        )
        text = re.sub(
            r"(?i)(\b(?:api[_-]?key|access[_-]?token|auth(?:orization)?|password|"
            r"secret|client[_-]?secret|private[_-]?key)\b\s*(?:=|:)\s*)(?:['\"]?)[^\s,'\"`]+",
            r"\1[redacted]",
            text,
        )
        text = re.sub(
            r"(?i)\b(?:sk|rk|ghp|github_pat|xoxb|akia)[-_a-z0-9]{8,}\b",
            "[redacted token]",
            text,
        )
        text = re.sub(r"(?i)[a-z][a-z0-9+.-]*://[^\s'\"`]+", "[redacted URI]", text)
        text = re.sub(
            r"(?<![\w.-])(?:[a-z]:[\\/][^\s'\"`]+|/"
            r"(?:users|home|workspaces|tmp|var|etc|private|mnt)[^\s'\"`]*)",
            "[redacted path]",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"<[^>\n]{1,200}>", "[redacted placeholder]", text)
        text = re.sub(r"\{\{[^}\n]{1,200}\}\}", "[redacted placeholder]", text)
        if collapse:
            text = " ".join(text.split())
        return text[:limit].rstrip()

    def dependency_usage_evidence_from_current_file(self, 
        *,
        path: str,
        content: str,
        content_excerpt: str,
        selection_text: str,
    ) -> list[DependencyUsageEvidence]:
        """Project import/call facts from the vetted current-file payload only."""

        if not path:
            return []
        source = "\n".join(
            part
            for part in (content, content_excerpt, selection_text)
            if part
        )
        if not source:
            return []

        evidence: list[DependencyUsageEvidence] = []
        seen: set[tuple[str, str]] = set()

        def append(kind: str, identifier: str) -> None:
            cleaned = identifier.strip()
            if not re.fullmatch(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", cleaned):
                return
            key = (kind, cleaned.casefold())
            if key in seen or len(evidence) >= 24:
                return
            seen.add(key)
            evidence.append(
                DependencyUsageEvidence(
                    filePath=path,
                    kind=kind,
                    identifier=cleaned,
                    summary=f"{kind} {cleaned}",
                )
            )

        def strip_comments_and_strings(line: str) -> str:
            result: list[str] = []
            quote = ""
            escaped = False
            index = 0
            while index < len(line):
                character = line[index]
                if quote:
                    if escaped:
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == quote:
                        quote = ""
                    result.append(" ")
                    index += 1
                    continue
                if character in {"'", '"', "`"}:
                    quote = character
                    result.append(" ")
                    index += 1
                    continue
                if character == "#" or line[index : index + 2] == "//":
                    break
                result.append(character)
                index += 1
            return "".join(result)

        call_keywords = {"if", "for", "while", "switch", "catch", "return", "new"}
        for line in source.splitlines():
            stripped = line.lstrip()
            if stripped.startswith(("//", "#")):
                continue
            python_from = re.match(
                r"from\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s+import\b",
                stripped,
            )
            python_import = re.match(
                r"import\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\b",
                stripped,
            )
            javascript_import = re.match(
                r"import\b.*?\bfrom\s+[\"']([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)[\"']",
                stripped,
            )
            commonjs_require = re.match(
                r"(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*require\(\s*"
                r"[\"']([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)[\"']\s*\)\s*;?\s*$",
                stripped,
            )
            for match in (python_from, python_import, javascript_import, commonjs_require):
                if match is not None:
                    append("import", match.group(1))

            code_line = strip_comments_and_strings(line)
            if re.match(r"(?:export\s+)?(?:async\s+)?(?:function|def|class)\b", code_line.lstrip()):
                continue
            for match in re.finditer(
                r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(",
                code_line,
            ):
                identifier = match.group(1)
                if identifier.casefold() not in call_keywords:
                    append("call", identifier)
        return evidence

    def safe_remote_workspace_name(self, value: object) -> str:
        raw = str(value or "").strip()
        if not raw or self.is_training_placeholder_or_uri(raw):
            return ""
        cleaned = self.redact_training_fact_text(raw, 120, collapse=True)
        if "[redacted" in cleaned or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+@-]{0,119}", cleaned):
            return ""
        return cleaned

    def training_card_guided_scenario(self, request: CardGenerationRequest) -> str:
        current_file = self.normalize_current_file_payload(request.current_file) or {}
        scenario_current_file = {
            "path": self.current_file_fact_value(current_file, "path", "path"),
            "language_id": self.current_file_fact_value(current_file, "language_id", "languageId"),
            "content": self.current_file_fact_value(current_file, "content", "content"),
            "content_excerpt": self.current_file_fact_value(
                current_file, "content_excerpt", "contentExcerpt"
            ),
            "selection_text": self.current_file_fact_value(
                current_file, "selection_text", "selectionText"
            ),
            "diagnostics": self.current_file_fact_value(current_file, "diagnostics", "diagnostics"),
        }
        scenario_text = "\n".join(
            value
            for value in (
                str(request.focus_area or "").strip(),
                str(request.target_skill or "").strip(),
                str(request.context_hint or "").strip(),
                str(request.why_now or "").strip(),
            )
            if value
        )
        scenario = infer_message_coaching_scenario(
            scenario_text,
            scenario_current_file,
            default="general",
        )
        return scenario if scenario in {"remote_workspace", "debug_loop", "function_guidance"} else "general"

    def trusted_training_card_request_from_api(self, request: CardGenerationRequest) -> CardGenerationRequest:
        """Replace client-supplied card anchors with facts derived by this process."""

        return request.model_copy(
            update={
                # Nested IDE input is consumed into vetted fields below; never carry raw input onward.
                "current_file": None,
                "resource_knowledge_evidence": None,
                "project_verification_steps": [],
                "plan_stage_id": "",
                **self.guided_training_workspace_facts(
                    workspace_id=request.workspace_id,
                    scenario=self.training_card_guided_scenario(request),
                    current_file=request.current_file,
                ),
            }
        )

    def guided_training_workspace_facts(self, 
        *,
        workspace_id: str,
        scenario: str,
        current_file: object | None,
    ) -> dict[str, object]:
        """Build minimal card anchors from the active workspace and IDE-file payload."""

        current_file_payload = self.normalize_current_file_payload(current_file) or {}
        raw_workspace_root = self.runtime.resolve_workspace_path(workspace_id)
        workspace_root = self.normalize_training_path(raw_workspace_root)
        has_workspace_root = bool(workspace_root and self.is_absolute_training_path(workspace_root))
        canonical_current_file = {
            "path": self.current_file_fact_value(current_file_payload, "path", "path"),
            "language_id": self.current_file_fact_value(current_file_payload, "language_id", "languageId"),
            "content": self.current_file_fact_value(current_file_payload, "content", "content"),
            "content_excerpt": self.current_file_fact_value(
                current_file_payload, "content_excerpt", "contentExcerpt"
            ),
            "selection_text": self.current_file_fact_value(
                current_file_payload, "selection_text", "selectionText"
            ),
            "selection_range": self.current_file_fact_value(
                current_file_payload, "selection_range", "selectionRange"
            ),
            "diagnostics": self.current_file_fact_value(current_file_payload, "diagnostics", "diagnostics"),
        }
        include_current_file = scenario != "function_guidance" or is_code_like_current_file(
            canonical_current_file
        )

        path = ""
        language_id = ""
        content = ""
        content_excerpt = ""
        selection_text = ""
        selection_range = ""
        diagnostics: list[str] = []
        trusted_current_file_path = False
        if include_current_file:
            raw_current_file_path = self.normalize_training_path(canonical_current_file["path"])
            path = self.relative_training_file_path(raw_current_file_path, workspace_root)
            if has_workspace_root and self.is_absolute_training_path(raw_current_file_path) and path:
                try:
                    resolved_current_file = Path(raw_current_file_path).resolve()
                    resolved_workspace_root = Path(workspace_root).resolve()
                    trusted_current_file_path = (
                        resolved_current_file.is_file()
                        and resolved_current_file.is_relative_to(resolved_workspace_root)
                    )
                except OSError:
                    trusted_current_file_path = False
            language_candidate = str(canonical_current_file["language_id"] or "").strip()
            if re.fullmatch(r"[A-Za-z0-9+_.-]{1,120}", language_candidate):
                language_id = language_candidate
            if path:
                content = self.redact_training_fact_text(canonical_current_file["content"], 12000)
                content_excerpt = self.redact_training_fact_text(
                    canonical_current_file["content_excerpt"], 4000
                )
                selection_text = self.redact_training_fact_text(
                    canonical_current_file["selection_text"], 4000
                )
                selection_range_candidate = str(
                    canonical_current_file["selection_range"] or ""
                ).strip()
                if re.fullmatch(r"\d+:\d+-\d+:\d+", selection_range_candidate):
                    selection_range = selection_range_candidate
            raw_diagnostics = canonical_current_file["diagnostics"]
            if isinstance(raw_diagnostics, list):
                diagnostics = [
                    self.redact_training_fact_text(item, 360, collapse=True)
                    for item in raw_diagnostics[:8]
                    if self.redact_training_fact_text(item, 360, collapse=True)
                ]
            if not path:
                diagnostics = []

        workspace_memory = self.runtime.memory_service.snapshot(workspace_id).workspace
        workspace_memory = workspace_memory if isinstance(workspace_memory, dict) else {}
        remote_name = self.safe_remote_workspace_name(workspace_memory.get("remote_name"))
        workspace_boundary = "workspace root" if has_workspace_root else ""
        remote_facts: list[str] = []
        if remote_name:
            remote_facts.append(f"remote identity: {remote_name}")
        if workspace_boundary:
            remote_facts.append(f"workspace boundary: {workspace_boundary}")
        if path:
            remote_facts.append(f"current file: {path}")

        dependency_usage_evidence = (
            self.dependency_usage_evidence_from_current_file(
                path=path,
                content=content,
                content_excerpt=content_excerpt,
                selection_text=selection_text,
            )
            if trusted_current_file_path
            else []
        )

        return {
            "current_file_path": path,
            "current_file_language_id": language_id,
            "current_file_content": content,
            "current_file_excerpt": content_excerpt,
            "current_file_selection": selection_text,
            "current_file_selection_range": selection_range,
            "current_file_diagnostics": diagnostics,
            "dependency_usage_evidence": dependency_usage_evidence,
            "workspace_root_path": workspace_boundary,
            "remote_workspace_name": remote_name,
            "remote_workspace_facts": remote_facts,
        }

    def infer_learner_signal(self, 
        message: str,
        current_file: dict[str, object] | None = None,
    ) -> str:
        return infer_message_learner_signal(message, self.normalize_current_file_payload(current_file))

    def message_requests_project_sourcing(self, message: str | None) -> bool:
        lowered = " ".join(str(message or "").casefold().split())
        return any(
            marker in lowered
            for marker in (
                "public project source",
                "source project",
                "reference repo",
                "reference repository",
                "reference project",
                "training repo",
                "training repository",
                "find a repo",
                "\u516c\u5f00\u9879\u76ee",
                "\u627e\u9879\u76ee",
                "\u627e\u4ee3\u7801\u5e93",
                "\u627e\u53c2\u8003\u5b9e\u73b0",
                "\u9002\u5408\u8bad\u7ec3\u7684\u9879\u76ee",
            )
        )

    def infer_coaching_scenario(self, 
        request: TurnRequest | SessionMessageRequest,
        *,
        current_task: TaskSpec | None = None,
        evaluation_summary: str | None = None,
    ) -> str:
        if isinstance(request, TurnRequest):
            if request.intent == "review":
                return "review"
            if request.intent == "plan":
                return "plan"
            if request.intent == "task":
                return "task"
            if request.intent == "next_task":
                return "next_task"

        if evaluation_summary:
            return "review"
        if self.message_requests_project_sourcing(request.message):
            return "project_sourcing"
        current_file = self.normalize_current_file_payload(getattr(request, "current_file", None))
        inferred = infer_message_coaching_scenario(
            request.message,
            current_file,
            default="general",
        )
        if current_task is not None:
            return "idea_implementation"
        return inferred

    def trusted_resource_knowledge_evidence(self, 
        workspace_id: str,
        resource: ResourceRecord,
    ) -> ResourceKnowledgeEvidence | None:
        """Return one redacted indexed fragment for a resource-training card."""

        if resource.index_status != "indexed" or self.resource_trust_state(resource) != "trusted":
            return None
        requested_context = self.runtime.resource_service.build_requested_resource_context(
            workspace_id,
            [resource.id],
            max_items=1,
            summary_chars=220,
        )
        fragments = requested_context.get("resource_fragments")
        if not isinstance(fragments, list):
            return None
        for fragment in fragments:
            if not isinstance(fragment, dict):
                continue
            if str(fragment.get("resource_id") or "").strip() != resource.id:
                continue
            fragment_id = self.redact_training_fact_text(fragment.get("id"), 160, collapse=True)
            focus_area = self.redact_training_fact_text(fragment.get("focus_area"), 240, collapse=True)
            summary = ""
            for key in ("evidence_summary", "summary", "snippet"):
                summary = self.redact_training_fact_text(fragment.get(key), 240, collapse=True)
                if summary:
                    break
            raw_source_type = str(fragment.get("source_type") or resource.kind).strip().lower()
            source_type = (
                raw_source_type
                if re.fullmatch(r"[a-z0-9][a-z0-9._:+-]{0,119}", raw_source_type)
                else resource.kind
            )
            if fragment_id and focus_area and summary:
                excerpt = self.redact_training_fact_text(
                    self.runtime.resource_service.read_indexed_fragment_text(workspace_id, resource, fragment),
                    1600,
                )
                return ResourceKnowledgeEvidence(
                    resourceId=resource.id,
                    fragmentId=fragment_id,
                    sourceType=source_type,
                    focusArea=focus_area,
                    summary=summary,
                    excerpt=excerpt,
                )
        return None

    def eligible_resource_training_record(self, 
        request: CardGenerationRequest,
    ) -> ResourceRecord | None:
        if request.source != "resource_knowledge":
            return None

        response_language = request.response_language
        try:
            provisioning = self.runtime.get_project_provisioning(request.workspace_id)
        except ProjectProvisioningIntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "This project needs to be reconnected to Trainer before creating review cards from resources.",
                    "这个项目需要先重新连接到 Trainer，才能用资料生成复习卡。",
                    response_language,
                ),
            ) from exc
        if provisioning is None:
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "Add this project to Trainer before creating review cards from resources.",
                    "请先把这个项目加入 Trainer，再用资料生成复习卡。",
                    response_language,
                ),
            )

        resource_id = request.resource_id.strip()
        resource = self.runtime.repository.get_resource(request.workspace_id, resource_id) if resource_id else None
        if resource is None:
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "This resource is no longer available. Refresh Resources and try again.",
                    "找不到这份资料。刷新资料页后再试一次。",
                    response_language,
                ),
            )

        if resource.parse_status != "parsed" or resource.index_status != "indexed":
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "This resource is still being prepared. Finish organizing and indexing it first.",
                    "这份资料还在整理中。完成整理和索引后就能生成复习卡。",
                    response_language,
                ),
            )
        if resource.freshness != "fresh":
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "Update this resource before creating a review card.",
                    "这份资料需要先更新，再生成复习卡。",
                    response_language,
                ),
            )

        quality_flags = {str(flag or "").strip().lower() for flag in resource.quality_flags}
        blocking_flags = {
            "network_disabled",
            "fetch_failed",
            "blocked_source",
            "no_content",
            "source_conflict",
        }
        if (
            resource.trust_score < 0.75
            or self.resource_trust_state(resource) != "trusted"
            or bool(blocking_flags & quality_flags)
        ):
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "Review this resource before creating a review card from it.",
                    "这份资料还需要确认内容后，才能生成复习卡。",
                    response_language,
                ),
            )
        if self.trusted_resource_knowledge_evidence(request.workspace_id, resource) is None:
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "Trainer could not find usable knowledge in this resource yet. Finish indexing it and try again.",
                    "Trainer 还没有在这份资料里找到可用内容。完成索引后再试一次。",
                    response_language,
                ),
            )
        return resource

    def require_expected_training_resource_version(self, request: CardGenerationRequest) -> None:
        expected = request.expected_resource_version
        if expected is None:
            return
        resource_id = request.resource_id.strip()
        resource = self.runtime.repository.get_resource(request.workspace_id, resource_id)
        version_store = self.runtime.resource_version_store
        version = (version_store.current_version(request.workspace_id, resource_id) or {}
                   if version_store is not None else {})
        if (
            resource is None
            or version.get("version_id") != expected.version_id
            or version.get("content_hash") != expected.content_hash
            or resource.content_hash != expected.content_hash
        ):
            raise HTTPException(status_code=409, detail=localized_text(
                "The linked source changed. Confirm the current version before practicing.",
                "已关联的资料版本发生变化。请核对当前版本后再练习。",
                request.response_language,
            ))
