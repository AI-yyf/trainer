"""Workspace coaching preferences, training card context preparation, generation, and learn-first activation."""

from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from ...core.models import (
    ActiveCardSelectionResult,
    CardGenerationContext,
    CardGenerationRequest,
    CardGenerationResponse,
    CardLibraryActionRequest,
    CardStatusTransitionResponse,
    CoachDefaults,
    DependencyUsageEvidence,
    ExpectedResourceVersion,
    ResourceKnowledgeEvidence,
    ResourceRecord,
    ResponseLanguage,
    SessionMessageRequest,
    TaskSpec,
    TrainingCardCandidateSnapshot,
    TrainingPlanBinding,
    TurnRequest,
    UserProfile,
    WorkbenchSnapshot,
)
from ...learner_state import learner_memory_snapshot
from ...llm.prompts import infer_coaching_scenario as infer_message_coaching_scenario
from ...llm.prompts import infer_learner_signal as infer_message_learner_signal
from ...llm.provider_service import (
    ProviderService,
)
from ...memory.workspace_recovery import (
    apply_live_training_mint_to_card,
    live_training_open_copy,
    live_training_why_this_card,
)
from ...training.card_generator import (
    CardGenerationProviderFailure,
    CardGenerationService,
    _make_guided_scenario_pack_card,
)
from ...training.card_request import message_requests_explicit_training_card
from ...training.plan_binding import validated_mint_binding
from ...training.project_checks import project_python_checks
from ...workspace.classifier import (
    is_code_like_current_file,
)
from ...workspace.provisioning import (
    ProjectProvisioningIntegrityError,
)
from .._helpers import (
    SUPPORTED_RESPONSE_LANGUAGES,
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
    _apply_pedagogy_controls_to_card_request,
    _pedagogy_controls_for_workspace,
    _workspace_training_mint_overlay,
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
from ..runtime import SessionState
from ._base import RouterDomainBase
from .constants import (
    GUIDED_SCENARIO_TRAINING_PACKS,
)


class TrainingCardsDomainMixin(RouterDomainBase):
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
            except Exception:
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

    def prepare_training_card_request(self, request: CardGenerationRequest) -> CardGenerationRequest:
        """Apply the same redaction, locale, and resource trust projection to both routes."""
        request_payload = request.model_copy(deep=True, update={
            "resource_version_id": "", "resource_content_hash": "", "resource_location": {},
        })
        request_payload = request_payload.model_copy(
            update={"plan_binding": self.current_training_plan_binding(request_payload)}
        )
        if request_payload.plan_binding is not None:
            request_payload = request_payload.model_copy(
                update={
                    "plan_stage_id": request_payload.plan_binding.stage_id,
                    "source": "plan_requirement" if request_payload.source == "formal_plan_step"
                    else request_payload.source,
                }
            )
        request_payload = request_payload.model_copy(
            update={
                "focus_area": self.redact_training_fact_text(request_payload.focus_area, 240, collapse=True),
                "target_skill": self.redact_training_fact_text(request_payload.target_skill, 240, collapse=True),
                "context_hint": self.redact_training_fact_text(request_payload.context_hint, 1200),
                "why_now": self.redact_training_fact_text(request_payload.why_now, 360, collapse=True),
            }
        )
        if not request_payload.response_language:
            memory_snapshot = learner_memory_snapshot(self.runtime, request_payload.workspace_id)
            saved_language = memory_snapshot.workspace.get("response_language")
            resolved_language = (
                saved_language
                if isinstance(saved_language, str) and saved_language in SUPPORTED_RESPONSE_LANGUAGES
                else "en-US"
            )
            request_payload = request_payload.model_copy(update={"response_language": resolved_language})
        if request_payload.resource_id:
            request_payload = request_payload.model_copy(
                update={"resource_id": request_payload.resource_id.strip()}
            )
        self.require_expected_training_resource_version(request_payload)
        mint_overlay = _workspace_training_mint_overlay(
            self.runtime,
            request_payload.workspace_id,
            request_payload,
        )
        request_payload = request_payload.model_copy(update=mint_overlay["anchors"])
        eligible_resource = self.eligible_resource_training_record(request_payload)
        if request_payload.resource_id:
            resource = eligible_resource or self.runtime.repository.get_resource(
                request_payload.workspace_id,
                request_payload.resource_id,
            )
            if resource is not None:
                version = self.runtime.resource_version_store.current_version(
                    request_payload.workspace_id, resource.id
                ) if self.runtime.resource_version_store is not None else None
                resource_evidence = self.trusted_resource_knowledge_evidence(
                    request_payload.workspace_id,
                    resource,
                )
                if request_payload.expected_resource_version is not None and resource_evidence is None:
                    raise HTTPException(status_code=409, detail=localized_text(
                        "The confirmed source needs indexed content before it can be used for practice.",
                        "已确认的资料需要完成内容索引后才能用于练习。",
                        request_payload.response_language,
                    ))
                project_checks: list[str] = []
                if (
                    resource_evidence is not None and request_payload.current_file_path
                    and request_payload.card_type == "practice"
                    and request_payload.source in {"plan_requirement", "conversation_gap"}
                ):
                    root = self.runtime.resolve_workspace_path(request_payload.workspace_id)
                    if root:
                        project_checks = [
                            self.redact_training_fact_text(step, 280) for step in project_python_checks(
                                Path(root), request_payload.current_file_path, request_payload.context_hint,
                            )
                        ]
                request_payload = request_payload.model_copy(
                    update={
                        "resource_quality_flags": list(resource.quality_flags or []),
                        "resource_trust_score": float(resource.trust_score or 0.0),
                        "resource_trust_state": self.resource_trust_state(resource),
                        "resource_freshness": str(resource.freshness or "unknown"),
                        "resource_knowledge_evidence": resource_evidence,
                        "project_verification_steps": project_checks,
                        "resource_version_id": str((version or {}).get("version_id") or ""),
                        "resource_content_hash": str((version or {}).get("content_hash") or ""),
                        "resource_location": (version or {}).get("location") or {},
                    }
                )
            else:
                request_payload = request_payload.model_copy(
                    update={
                        "resource_missing": True,
                        "resource_missing_reason": "Requested resource was not found in workspace memory.",
                        "resource_trust_state": "untrusted",
                    }
                )
        return _apply_pedagogy_controls_to_card_request(request_payload, self.runtime)

    def current_training_plan_binding(self, request: CardGenerationRequest) -> TrainingPlanBinding | None:
        plan, recovered = self.leftover_runtime_for_workspace(request.workspace_id)
        revision = self.runtime.repository.get_plan_revision(request.workspace_id, plan.id) if plan else 0
        try:
            binding = validated_mint_binding(
                request.plan_binding,
                source=request.source,
                plan=plan,
                runtime=recovered,
                revision=revision,
            )
            if binding is not None and plan is not None and request.expected_resource_version is not None:
                stage = next((stage for stage in plan.stages if stage.id == binding.stage_id), None)
                if stage is None or request.resource_id not in stage.resources:
                    raise ValueError("Link the confirmed source to the current plan stage before practicing.")
            return binding
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def existing_open_resource_training_card(self, 
        request_payload: CardGenerationRequest,
    ) -> TrainingCardCandidateSnapshot | None:
        return next(
            (
                card
                for card in self.runtime.memory_service.get_cards(request_payload.workspace_id)
                if card.created_from == "resource"
                and card.resource_id == request_payload.resource_id
                and card.resource_content_hash == request_payload.resource_content_hash
                and (request_payload.expected_resource_version is None
                    or card.resource_version_id == request_payload.resource_version_id)
                and (request_payload.plan_binding is None or card.plan_binding == request_payload.plan_binding)
                and card.card_type == request_payload.card_type
                and card.status in {"candidate", "active", "needs_primer"}
            ),
            None,
        )

    def card_generation_service_for(self, 
        provider_service: ProviderService | None,
    ) -> CardGenerationService:
        configured_service = getattr(self.runtime, "card_generation_service", None)
        if configured_service is None:
            raise HTTPException(status_code=503, detail="Card generation service is not configured.")
        if getattr(configured_service, "_provider", None) is provider_service:
            return configured_service
        return CardGenerationService(
            provider_service=provider_service,
            event_ledger=getattr(configured_service, "_event_ledger", None),
        )

    def training_generate_candidate(self, 
        request: CardGenerationRequest,
        generated_card: TrainingCardCandidateSnapshot | None = None,
        provider_service_override: ProviderService | None = None,
    ) -> CardGenerationResponse:
        generator = self.card_generation_service_for(provider_service_override or self.runtime.provider_service)
        request_payload = self.prepare_training_card_request(request)

        def store_generated_card(
            generated_card: TrainingCardCandidateSnapshot | None = None,
        ) -> TrainingCardCandidateSnapshot:
            card = generated_card or generator.generate_card(request_payload.source, request_payload)
            card = card.model_copy(
                update={
                    "review_state": "pending",
                    "resource_id": request_payload.resource_id or card.resource_id,
                    "trust_state": request_payload.resource_trust_state or card.trust_state,
                    "difficulty": request_payload.difficulty or card.difficulty,
                }
            )
            mint_overlay = _workspace_training_mint_overlay(
                self.runtime,
                request_payload.workspace_id,
                request_payload,
            )
            card = apply_live_training_mint_to_card(
                card,
                anchors=mint_overlay["anchors"],
                leftover_labels=mint_overlay["leftover"],
                recovered_step=str(mint_overlay["recovered_step"] or ""),
            )
            # Recheck after the provider completes: a plan may change during generation.
            binding = self.current_training_plan_binding(request_payload)
            self.require_expected_training_resource_version(request_payload)
            card = card.model_copy(update={
                "plan_binding": binding,
                "plan_links": [binding.stage_id] if binding else (
                    [request_payload.plan_stage_id] if request_payload.plan_stage_id else []
                ),
            })
            return self.runtime.memory_service.upsert_card(request_payload.workspace_id, card)

        def existing_open_resource_card() -> TrainingCardCandidateSnapshot | None:
            return self.existing_open_resource_training_card(request_payload)

        def candidate_response(card: TrainingCardCandidateSnapshot) -> CardGenerationResponse:
            self.refresh_workspace_sessions(request_payload.workspace_id)
            return CardGenerationResponse(card=card)

        try:
            if request_payload.source == "resource_knowledge" and request_payload.resource_id:
                with self.training_card_lock(request_payload.workspace_id):
                    return candidate_response(
                        existing_open_resource_card() or store_generated_card(generated_card)
                    )
            return candidate_response(store_generated_card(generated_card))
        except (CardGenerationProviderFailure, HTTPException):
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def training_card_library_action(self, request: CardLibraryActionRequest) -> CardStatusTransitionResponse:
        workspace_id, card_id = request.workspace_id, request.card_id
        memory = self.runtime.memory_service
        with self.training_card_lock(workspace_id):
            card = memory.get_card(workspace_id, card_id)
            if card is None:
                raise HTTPException(status_code=404, detail="Training card not found.")
            if request.action == "start":
                if card.review_state != "saved" or card.status not in {
                    "candidate", "active", "needs_primer", "blocked", "skipped",
                }:
                    raise ValueError("Select an available card from your library.")
                if memory.live_selected_training_card_id(workspace_id) != card_id:
                    if card.trust_state in {"untrusted", "stale"} and not card.trust_acknowledged:
                        raise ValueError("Refresh or acknowledge the card's source before practicing.")
                    if card.resource_id and card.resource_version_id and card.resource_content_hash:
                        self.require_expected_training_resource_version(CardGenerationRequest(
                            workspace_id=workspace_id,
                            resource_id=card.resource_id,
                            expectedResourceVersion=ExpectedResourceVersion(
                                versionId=card.resource_version_id,
                                contentHash=card.resource_content_hash,
                            ),
                        ))
                    selection = memory.persist_active_card_selection(
                        workspace_id,
                        ActiveCardSelectionResult(
                            selected_card=card,
                            selected_card_id=card_id,
                            why_this_card=card.why_now,
                        ),
                    )
                    card = selection.selected_card or card
                    self.persist_training_card_to_sandbox(workspace_id, card)
            elif request.action == "archive":
                if card.status != "archived":
                    card = memory.transition_card_status(
                        workspace_id, card_id, "archived",
                        reason="Archived from the training library.",
                        archive_from_library=True,
                    ).card
            else:
                review_state: dict[str, Literal["saved", "deferred", "rejected"]] = {
                    "save": "saved", "defer": "deferred", "reject": "rejected",
                }
                card = memory.review_card_candidate(
                    workspace_id, card,
                    state=review_state[request.action],
                    prompt=request.prompt,
                    acceptance_criteria=request.acceptance_criteria,
                )
                if request.action == "save":
                    self.persist_training_card_to_sandbox(workspace_id, card, mark_current=False)
            self.refresh_workspace_sessions(workspace_id)
            return CardStatusTransitionResponse(card=card)

    def requested_training_card_type(self, message: str | None) -> Literal["practice", "flash"]:
        lowered = " ".join(str(message or "").strip().lower().split())
        direct_flash_tokens = (
            "flash card",
            "flashcard",
            "\u95ea\u5361",
            "\u95ea\u8bb0\u5361",
            "\u590d\u4e60\u5361",
        )
        if any(token in lowered for token in direct_flash_tokens):
            return "flash"

        practice_tokens = (
            "practice card",
            "learn-first",
            "hands-on",
            "primer",
            "before any test",
            "practice first",
            "do not test me first",
            "don't test me first",
            "before any quiz",
            "\u7ec3\u4e60\u5361",
            "\u5148\u5b66",
            "\u5148\u5b66\u4e60",
            "\u5148\u5b66\u518d\u7ec3\u4e60",
            "\u5148\u5b66\u540e\u7ec3",
            "\u5148\u8bb2\u518d\u7ec3",
            "\u4e0d\u8981\u5148\u8003\u8bd5",
            "\u4e0d\u8981\u5148\u6d4b\u8bd5",
        )
        if any(token in lowered for token in practice_tokens):
            return "practice"

        flash_cues = (
            "flash ",
            "recall card",
            "multiple choice",
            "quiz",
            "mcq",
        )
        if any(token in lowered for token in flash_cues):
            return "flash"
        return "practice"

    def validated_training_response_language(self, value: str | None) -> ResponseLanguage | None:
        return CardGenerationContext.model_validate({"response_language": value}).response_language

    def message_requests_general_learn_first_training(self, message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        learn_requested = any(
            token in lowered
            for token in (
                "learn first",
                "practice first",
                "teach me",
                "step by step",
                "before you test me",
                "before you quiz me",
                "first explain",
                "教我",
                "先教我",
                "先讲",
                "先学",
                "先学习",
                "先理解",
                "先讲解",
                "一步一步",
                "不要先考试",
                "不要先测试",
                "先学后练",
                "先学习再验证",
            )
        ) or bool(
            re.search(r"\blearn\b.{0,80}\bfirst\b", lowered)
            or re.search(r"\bunderstand\b.{0,80}\bfirst\b", lowered)
        )
        if not learn_requested:
            return False
        return any(
            token in lowered
            for token in (
                "tiny verified step",
                "small verified step",
                "tiny real step",
                "small real step",
                "tiny learning step",
                "small learning step",
                "small debug move",
                "smallest verifiable move",
                "tiny verified move",
                "tiny real move",
                "verifiable step",
                "verifiable move",
                "verifiable learning move",
                "verifiable value",
                "verify",
                "verified",
                "checkpoint",
                "validation step",
                "test my understanding",
                "before you test me",
                "before you quiz me",
                "再测试我",
                "再验证",
                "验证动作",
                "可验证",
                "很小的验证",
                "很小而且可验证",
                "很小的可验证",
                "很小的学习动作",
                "很小的训练动作",
            )
        )

    def message_requests_auto_training_handoff(self, message: str | None) -> bool:
        """Require an explicit learn-practice-verify loop before opening Training."""
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        learn_practice_markers = (
            "learn -> try -> verify",
            "learn, try, verify",
            "learn then practice",
            "learn then try",
            "learn first, then practice",
            "learn first, then try",
            "\u5148\u5b66\u518d\u7ec3",
            "\u5148\u5b66\u540e\u7ec3",
            "\u5148\u5b66\u518d\u5b9e\u8df5",
            "\u5148\u5b66\u540e\u5b9e\u8df5",
            "\u5148\u8bb2\u518d\u7ec3",
            "\u5148\u7406\u89e3\u518d\u7ec3",
        )
        verification_markers = (
            "verify",
            "verification",
            "test it",
            "check it",
            "\u9a8c\u6536",
            "\u9a8c\u8bc1",
            "\u68c0\u9a8c",
            "\u6d4b\u8bd5",
            "\u518d\u6d4b",
        )
        return any(marker in lowered for marker in learn_practice_markers) and any(
            marker in lowered for marker in verification_markers
        )

    def auto_answer_mode_allows_training_handoff(self, 
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
    ) -> bool:
        for value in (
            requested_answer_mode,
            saved_answer_mode,
            profile.answer_policy if profile else None,
        ):
            normalized = str(value or "").strip().lower()
            if normalized:
                return normalized == "auto"
        return False

    def message_requests_implicit_learn_first_training(self, 
        message: str | None,
        *,
        requested_scenario: str,
    ) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        if requested_scenario not in {
            "remote_workspace",
            "debug_loop",
            "function_guidance",
        }:
            return False
        if self.message_requests_general_learn_first_training(message):
            return True
        return False

    def message_requests_training_card_activation(self, 
        message: str | None,
        *,
        requested_scenario: str,
    ) -> bool:
        del requested_scenario
        return message_requests_explicit_training_card(message)

    def auto_preference_requests_training_card(self, 
        message: str | None,
        *,
        requested_scenario: str,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
    ) -> bool:
        del requested_scenario, requested_answer_mode, saved_answer_mode, profile
        return message_requests_explicit_training_card(message)

    def auto_lane_learn_first_force_training_card(self, 
        message: str | None,
        *,
        requested_scenario: str,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
    ) -> bool:
        del requested_answer_mode, saved_answer_mode, profile
        return self.message_requests_implicit_learn_first_training(
            message,
            requested_scenario=requested_scenario,
        )

    def training_card_defaults_for_scenario(self, 
        scenario: str,
        response_language: str | None,
    ) -> tuple[str, str]:
        localized_defaults = self.localized_training_defaults_for_scenario(
            scenario,
            response_language,
        )
        if localized_defaults is not None:
            return localized_defaults
        return (
            localized_text("current training focus", "当前训练重点", response_language),
            localized_text("learn-first practice", "先学习再练习", response_language),
        )

    def selected_training_card_scenario_pack(self, 
        selection: ActiveCardSelectionResult | None,
    ) -> str:
        if selection is None or selection.selected_card is None:
            return ""
        return str(getattr(selection.selected_card, "scenario_pack", "") or "").strip()

    def active_training_card_satisfies_request(self, 
        selection: ActiveCardSelectionResult | None,
        *,
        requested_scenario: str,
        message: str | None,
        force_training_card: bool,
    ) -> bool:
        if selection is None:
            return False
        if requested_scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return True
        if not force_training_card and not self.message_requests_training_card_activation(
            message,
            requested_scenario=requested_scenario,
        ):
            return True
        return self.selected_training_card_scenario_pack(selection) == requested_scenario

    def direct_guided_training_card_fallback(self, 
        *,
        workspace_id: str,
        scenario: str,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        active_thread: object | None,
    ) -> bool:
        if scenario not in {"remote_workspace", "debug_loop", "function_guidance"}:
            return False

        current_file_payload = self.normalize_current_file_payload(current_file)
        current_file_name = self.function_guidance_current_file_name(
            current_file_payload,
            scenario=scenario,
        )

        default_focus, default_skill = self.training_card_defaults_for_scenario(
            scenario,
            response_language,
        )
        active_thread_scenario = self.active_thread_scenario_value(active_thread)
        focus_candidates: list[object] = []
        if active_thread is not None and active_thread_scenario in {"", scenario, "general"}:
            focus_candidates.append(getattr(active_thread, "focus_area", ""))
        focus_candidates.append(default_focus)
        focus_hint = self.resolve_focus_hint(
            user_message=message,
            candidates=focus_candidates,
            fallback_current_file=current_file_name or None,
        )
        if scenario == "function_guidance" and current_file_name and not focus_hint:
            focus_hint = current_file_name

        context_bits = [f"Coach request: {str(message or '').strip()}"]
        if current_file_name:
            context_bits.append(f"Current file: {current_file_name}")
        active_next_step = str(getattr(active_thread, "next_step", "") or "").strip() if active_thread else ""
        if active_next_step and active_thread_scenario in {"", scenario, "general"}:
            context_bits.append(f"Active thread: {active_next_step}")

        pedagogy_controls = _pedagogy_controls_for_workspace(self.runtime, workspace_id)
        context = CardGenerationContext(
            workspace_id=workspace_id,
            source="conversation_gap",
            card_type=self.requested_training_card_type(message),
            context_hint=" | ".join(bit for bit in context_bits if bit).strip()[:420],
            target_skill=default_skill,
            focus_area=focus_hint or default_focus,
            difficulty=pedagogy_controls.difficulty if pedagogy_controls is not None else "medium",
            hint_count=pedagogy_controls.hint_count if pedagogy_controls is not None else None,
            code_reveal=pedagogy_controls.code_reveal if pedagogy_controls is not None else "",
            practice_type=pedagogy_controls.practice_type if pedagogy_controls is not None else "",
            review_frequency=pedagogy_controls.review_frequency if pedagogy_controls is not None else "",
            material_recommendation=(
                pedagogy_controls.material_recommendation if pedagogy_controls is not None else ""
            ),
            next_plan_step=pedagogy_controls.next_plan_step if pedagogy_controls is not None else "",
            should_reveal_code=(
                pedagogy_controls.should_reveal_code if pedagogy_controls is not None else None
            ),
            pedagogy_mode=pedagogy_controls.pedagogy_mode if pedagogy_controls is not None else "",
            why_now=localized_text(
                "The learner asked Coach for one learn-first training move.",
                "\u5b66\u4e60\u8005\u8981\u6c42 Coach \u5148\u5b89\u6392\u4e00\u4e2a\u5148\u5b66\u540e\u7ec3\u7684\u8bad\u7ec3\u52a8\u4f5c\u3002",
                response_language,
            ),
            response_language=self.validated_training_response_language(response_language),
        )
        context = context.model_copy(
            update=self.guided_training_workspace_facts(
                workspace_id=workspace_id,
                scenario=scenario,
                current_file=current_file_payload,
            )
        )
        card = _make_guided_scenario_pack_card(
            scenario,
            context,
            self.requested_training_card_type(message),
            response_language or "en-US",
        )
        stored_card = self.runtime.memory_service.upsert_card(workspace_id, card)
        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        self.runtime.memory_service.persist_active_card_selection(
            workspace_id,
            ActiveCardSelectionResult(
                selected_card=stored_card,
                selected_card_id=stored_card.card_id,
                selection_score=100.0,
                why_this_card=live_training_why_this_card(
                    plan=leftover_plan,
                    runtime=leftover_runtime,
                    existing=leftover_runtime,
                    card_title=stored_card.title,
                    why_now=stored_card.why_now,
                    kind="next",
                )
                or "This is the next training card.",
                fallback_action=localized_text(
                    "Return to Coach with the exact blocker and verification output.",
                    "带着准确的 blocker 和验证输出来回到 Coach。",
                    response_language,
                ),
                next_after_completion=localized_text(
                    "Finish the card, update the evidence, then route the next card.",
                    "完成这张卡，更新证据，再决定下一张卡。",
                    response_language,
                ),
                candidate_count=1,
                eligible_count=1,
            ),
        )
        self.refresh_workspace_sessions(workspace_id)
        return True

    def guided_training_card_requested(self, 
        *,
        scenario: str,
        message: str | None,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
        force_training_card: bool = False,
    ) -> bool:
        normalized_scenario = str(scenario or "").strip()
        if normalized_scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return False
        return force_training_card or self.message_requests_training_card_activation(
            message,
            requested_scenario=normalized_scenario,
        ) or self.auto_preference_requests_training_card(
            message,
            requested_scenario=normalized_scenario,
            requested_answer_mode=requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        ) or self.auto_lane_learn_first_force_training_card(
            message,
            requested_scenario=normalized_scenario,
            requested_answer_mode=requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        )

    def guarantee_guided_learn_first_training_card(self, 
        *,
        workspace_id: str,
        scenario: str,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        active_thread: object | None,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
        force_training_card: bool = False,
    ) -> bool:
        # Composer chat stays hint-only for remote_workspace / debug_loop packs;
        # POST /training/generate-card remains the binder for those. Function
        # guidance is the exception: when the learner asks to learn from real
        # code but no code-like file is available, the honest move is a
        # needs_primer card naming the missing facts, not a fake scaffolded
        # call site written into the sandbox.
        if scenario != "function_guidance":
            return False
        if not self.provider_service_allows_object_minting():
            return False
        if self.pressure_without_live_object_blocks_mint(
            workspace_id,
            message=message,
        ) or self.streak_without_live_object_blocks_mint(workspace_id):
            return False
        if scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return False
        if self.message_requests_direct_answer(message) or self.message_requests_explicit_explanation_or_example(
            message
        ):
            return False
        if not self.guided_training_card_requested(
            scenario=scenario,
            message=message,
            requested_answer_mode=requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
            force_training_card=force_training_card,
        ):
            return False
        snapshot = self.runtime.memory_service.snapshot(workspace_id)
        if self.active_training_card_satisfies_request(
            snapshot.active_training_card_routing,
            requested_scenario=scenario,
            message=message,
            force_training_card=True,
        ):
            return False
        return self.direct_guided_training_card_fallback(
            workspace_id=workspace_id,
            scenario=scenario,
            message=message,
            current_file=current_file,
            response_language=response_language,
            active_thread=active_thread,
        )

    def should_bypass_agent_loop_for_guided_training(self, 
        *,
        workspace_id: str,
        scenario: str,
        message: str | None,
        active_view: str | None = None,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
        force_training_card: bool = False,
    ) -> bool:
        # Training's Coach route is an explicit request for model-backed help.
        # The deterministic card handoff still creates/selects the card, but it
        # must not replace the learner's conversation with a local scaffold.
        if str(active_view or "").strip().lower() == "training":
            return False
        normalized_scenario = str(scenario or "").strip()
        if normalized_scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return False
        if self.message_requests_direct_answer(message) or self.message_requests_explicit_explanation_or_example(
            message
        ):
            return False
        visible_handoff_requested = force_training_card or self.auto_preference_requests_training_card(
            message,
            requested_scenario=normalized_scenario,
            requested_answer_mode=requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        )
        if not visible_handoff_requested:
            return False
        selection = self.runtime.memory_service.snapshot(workspace_id).active_training_card_routing
        return self.active_training_card_satisfies_request(
            selection,
            requested_scenario=normalized_scenario,
            message=message,
            force_training_card=True,
        )

    def build_guided_training_visible_fallback(self, 
        *,
        workspace_id: str,
        response_language: str | None,
    ) -> dict[str, str] | None:
        selection = self.runtime.memory_service.snapshot(workspace_id).active_training_card_routing
        if selection is None or selection.selected_card is None:
            return None
        card = selection.selected_card
        if str(card.scenario_pack or "").strip() not in GUIDED_SCENARIO_TRAINING_PACKS:
            return None

        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        reason = live_training_why_this_card(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            card_title=card.title,
            why_now=str(selection.why_this_card or card.why_now or "").strip(),
            kind="current",
        )
        deliver = str(card.problem_statement or "").strip()
        if not deliver and card.learner_deliverables:
            deliver = "; ".join(
                str(item).strip() for item in card.learner_deliverables[:2] if str(item).strip()
            )
        verify = "; ".join(
            str(item).strip() for item in card.verification_steps[:2] if str(item).strip()
        )
        if not verify:
            verify = str(card.success_signal or card.validation_method or "").strip()
        return_with = str(card.return_with or selection.next_after_completion or "").strip()
        next_step = str(
            card.suggested_workspace_action
            or (card.verification_steps[0] if card.verification_steps else "")
            or selection.fallback_action
            or card.stuck_recovery
            or ""
        ).strip()
        primer_required = str(card.status or "").strip() == "needs_primer"
        open_copy = live_training_open_copy(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            card_title=str(card.title or "").strip(),
            next_step=next_step,
            primer_required=primer_required,
        )

        if prefers_chinese(response_language):
            lines = [
                "我先把这一轮收束成一张先学后练的训练卡，不先测试你。",
                "",
                open_copy["zh_current"],
            ]
            if reason:
                lines.append(f"- 为什么现在做：{reason}")
            if deliver:
                lines.append(f"- 你要完成：{deliver}")
            if verify:
                lines.append(f"- 这样验证：{verify}")
            if return_with:
                lines.append(f"- 完成后带回：{return_with}")
            lines.append("")
            if next_step:
                lines.append(f"先在 Training 做这一步：{next_step}")
            else:
                lines.append("先打开 Training，沿着这张卡继续。")
            lines.append(
                "先完成 primer，再进入验证。"
                if primer_required
                else "完成后把验证结果带回 Coach。"
            )
            summary = open_copy["zh_summary"]
            normalized_next_step = open_copy["zh_complete"]
            teaching_note = "训练默认闭环保持为 Learn -> Try -> Verify -> Reflect -> Return。"
        else:
            lines = [
                "I set up one learn-first training card before any quiz.",
                "",
                open_copy["en_current"],
            ]
            if reason:
                lines.append(f"- Why now: {reason}")
            if deliver:
                lines.append(f"- Deliver: {deliver}")
            if verify:
                lines.append(f"- Verify: {verify}")
            if return_with:
                lines.append(f"- Return with: {return_with}")
            lines.append("")
            if next_step:
                lines.append(f"Open Training and start with: {next_step}")
            else:
                lines.append("Open Training and continue with this card.")
            lines.append(
                "Finish the primer first, then move into verification."
                if primer_required
                else "Bring the verification result back to Coach when you finish."
            )
            summary = open_copy["en_summary"]
            normalized_next_step = open_copy["en_complete"]
            teaching_note = "Keep the training loop as Learn -> Try -> Verify -> Reflect -> Return."

        resume_thread = self.build_resume_thread_text(
            summary,
            normalized_next_step,
            response_language=response_language,
        )
        return {
            "reply": "\n".join(lines).strip(),
            "summary": summary,
            "next_step": normalized_next_step,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
        }

    def apply_guided_training_visible_fallback(self, 
        *,
        coach_turn: dict[str, object],
        fallback: dict[str, str],
    ) -> tuple[str, dict[str, object], dict[str, object]]:
        repaired_coach_turn = self.merge_agent_finalize_into_coach_turn(
            coach_turn,
            summary=fallback["summary"],
            next_step=fallback["next_step"],
            blocker=None,
            resume_thread=fallback["resume_thread"],
            decision="training_handoff",
            teaching_note=fallback["teaching_note"],
            confidence=None,
            evidence=None,
        )
        agent_meta = {
            "stop_reason": "local_guided_training",
            "summary": fallback["summary"],
            "next_step": fallback["next_step"],
            "decision": "training_handoff",
            "blocker": None,
            "teaching_note": fallback["teaching_note"],
            "resume_thread": fallback["resume_thread"],
            "confidence": None,
            "evidence": None,
            "tool_events": [],
            "fell_back": False,
            "recovered_stop_reason": None,
            "agentic": False,
            "local_guided_training_fallback": True,
        }
        if repaired_coach_turn is None:
            repaired_coach_turn = coach_turn
        return fallback["reply"], repaired_coach_turn, agent_meta

    def maybe_activate_training_card_from_coach_request(self, 
        *,
        workspace_id: str,
        snapshot: WorkbenchSnapshot,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        provider_service_override: ProviderService | None = None,
    ) -> CardGenerationResponse | None:
        # Composer chat (/turn, /turn/stream, /session/message) must not mint.
        # Explicit POST /training/generate-card binds a NEW card_id. Do not clobber
        # an already-live selected_card_id from chat either.
        return None
        current_file_payload = self.normalize_current_file_payload(current_file)
        active_thread = snapshot.memory.active_thread
        active_thread_scenario = self.active_thread_scenario_value(active_thread)
        requested_scenario = infer_message_coaching_scenario(
            str(message or ""),
            current_file_payload,
            default="general",
        )
        if (
            requested_scenario == "general"
            and self.message_requests_lane_continuation(message)
            and active_thread_scenario in {
                "remote_workspace",
                "debug_loop",
                "function_guidance",
            }
        ):
            requested_scenario = active_thread_scenario
        if not self.message_requests_training_card_activation(
            message,
            requested_scenario=requested_scenario,
        ):
            return None

        current_file_name = self.function_guidance_current_file_name(
            current_file_payload,
            scenario=requested_scenario,
        )

        default_focus, default_skill = self.training_card_defaults_for_scenario(
            requested_scenario,
            response_language,
        )
        focus_candidates: list[object] = []
        if active_thread is not None and active_thread_scenario in {"", requested_scenario, "general"}:
            focus_candidates.append(getattr(active_thread, "focus_area", ""))
        if requested_scenario == "general":
            focus_candidates.append(
                self.stateful_focus_area(
                    snapshot.current_task,
                    snapshot.plan,
                    snapshot.evaluation,
                    snapshot=snapshot,
                )
            )
        focus_candidates.append(default_focus)
        focus_hint = self.resolve_focus_hint(
            user_message=message,
            candidates=focus_candidates,
            fallback_current_file=current_file_name or None,
        )
        if requested_scenario == "function_guidance" and current_file_name and not focus_hint:
            focus_hint = current_file_name

        target_skill = default_skill if requested_scenario != "general" else (focus_hint or default_skill)
        context_bits = [f"Coach request: {str(message or '').strip()}"]
        if current_file_name:
            context_bits.append(f"Current file: {current_file_name}")
        active_next_step = str(getattr(active_thread, "next_step", "") or "").strip() if active_thread else ""
        if active_next_step and active_thread_scenario in {"", requested_scenario, "general"}:
            context_bits.append(f"Active thread: {active_next_step}")
        context_hint = " | ".join(bit for bit in context_bits if bit).strip()[:420]

        request_payload = CardGenerationRequest(
            workspace_id=workspace_id,
            source="conversation_gap",
            card_type=self.requested_training_card_type(message),
            focus_area=focus_hint or default_focus,
            target_skill=target_skill,
            context_hint=context_hint,
            why_now=localized_text(
                "The learner asked Coach for one learn-first training move.",
                "学习者请 Coach 提供一个先学习再练习的训练动作。",
                response_language,
            ),
            difficulty="medium",
            response_language=self.validated_training_response_language(response_language),
        )
        request_payload = request_payload.model_copy(
            update=self.guided_training_workspace_facts(
                workspace_id=workspace_id,
                scenario=requested_scenario,
                current_file=current_file_payload,
            )
        )
        return self.training_generate_candidate(
            request_payload,
            provider_service_override=provider_service_override,
        )

    def safe_activate_training_card_from_coach_request(self, 
        *,
        workspace_id: str,
        snapshot: WorkbenchSnapshot,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        provider_service_override: ProviderService | None = None,
    ) -> CardGenerationResponse | None:
        # Composer chat must not mint (incl. guided fallback). HTTP generate-card may.
        return None
        if not self.provider_service_allows_object_minting(provider_service_override):
            return None
        if self.pressure_without_live_object_blocks_mint(
            workspace_id,
            snapshot=snapshot,
            current_task=snapshot.current_task,
            current_plan=snapshot.plan,
            message=message,
        ) or self.streak_without_live_object_blocks_mint(
            workspace_id,
            snapshot=snapshot,
            current_task=snapshot.current_task,
            current_plan=snapshot.plan,
        ):
            return None
        created: CardGenerationResponse | None = None
        try:
            created = self.maybe_activate_training_card_from_coach_request(
                workspace_id=workspace_id,
                snapshot=snapshot,
                message=message,
                current_file=current_file,
                response_language=response_language,
                provider_service_override=provider_service_override,
            )
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
        if created is not None:
            return created
        current_file_payload = self.normalize_current_file_payload(current_file)
        active_thread = snapshot.memory.active_thread
        active_thread_scenario = self.active_thread_scenario_value(active_thread)
        requested_scenario = infer_message_coaching_scenario(
            str(message or ""),
            current_file_payload,
            default="general",
        )
        if (
            requested_scenario == "general"
            and self.message_requests_lane_continuation(message)
            and active_thread_scenario in GUIDED_SCENARIO_TRAINING_PACKS
        ):
            requested_scenario = active_thread_scenario
        if requested_scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return None
        if not self.message_requests_training_card_activation(
            message,
            requested_scenario=requested_scenario,
        ):
            return None
        if self.direct_guided_training_card_fallback(
            workspace_id=workspace_id,
            scenario=requested_scenario,
            message=message,
            current_file=current_file,
            response_language=response_language,
            active_thread=active_thread,
        ):
            selection = self.runtime.memory_service.snapshot(workspace_id).active_training_card_routing
            if selection is not None and selection.selected_card is not None:
                return CardGenerationResponse(
                    card=selection.selected_card,
                    score=selection.selection_score,
                    success=True,
                    reason="local_guided_fallback",
                    active_routing=selection,
                )
            fallback_context = CardGenerationContext(
                workspace_id=workspace_id,
                source="conversation_gap",
                card_type=self.requested_training_card_type(message),
                context_hint="",
                target_skill="guided fallback",
                focus_area="guided fallback",
                difficulty="medium",
                why_now="local_guided_fallback",
                response_language=self.validated_training_response_language(response_language),
            ).model_copy(
                update=self.guided_training_workspace_facts(
                    workspace_id=workspace_id,
                    scenario=requested_scenario,
                    current_file=current_file_payload,
                )
            )
            return CardGenerationResponse(
                card=_make_guided_scenario_pack_card(
                    requested_scenario,
                    fallback_context,
                    self.requested_training_card_type(message),
                    response_language or "en-US",
                ),
                score=100.0,
                success=True,
                reason="local_guided_fallback",
                active_routing=None,
            )
        return None

    def ensure_explicit_training_card_after_language_block(self, 
        *,
        state: SessionState,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        fallback_scenario: str | None = None,
        force_training_card: bool = False,
        provider_service_override: ProviderService | None = None,
    ) -> None:
        # Composer chat must not mint or clobber. Keep live selected_card_id only.
        # Explicit POST /training/generate-card is the intentional mint path.
        live_id = self.runtime.memory_service.live_selected_training_card_id(state.workspace_id)
        if live_id:
            state.snapshot.memory = self.runtime.memory_service.snapshot(state.workspace_id)
        return
        if not self.provider_service_allows_object_minting(provider_service_override):
            return
        # Pressure/streak blocks invent on coach turns (including "create a card" in chat).
        # Explicit POST /training/generate-card is the intentional mint path.
        if self.pressure_without_live_object_blocks_mint(
            state.workspace_id,
            snapshot=state.snapshot,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
            message=message,
        ) or self.streak_without_live_object_blocks_mint(
            state.workspace_id,
            snapshot=state.snapshot,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
        ):
            return
        snapshot = self.runtime.memory_service.snapshot(state.workspace_id)
        current_file_payload = self.normalize_current_file_payload(current_file)
        active_thread = state.snapshot.memory.active_thread
        active_thread_scenario = self.active_thread_scenario_value(active_thread)
        requested_scenario = infer_message_coaching_scenario(
            str(message or ""),
            current_file_payload,
            default="general",
        )
        normalized_fallback_scenario = str(fallback_scenario or "").strip()
        if (
            normalized_fallback_scenario in GUIDED_SCENARIO_TRAINING_PACKS
            and force_training_card
            and requested_scenario not in GUIDED_SCENARIO_TRAINING_PACKS
        ):
            requested_scenario = normalized_fallback_scenario
        if requested_scenario == "general" and normalized_fallback_scenario in GUIDED_SCENARIO_TRAINING_PACKS:
            requested_scenario = normalized_fallback_scenario
        if (
            requested_scenario == "general"
            and self.message_requests_lane_continuation(message)
            and active_thread_scenario in GUIDED_SCENARIO_TRAINING_PACKS
        ):
            requested_scenario = active_thread_scenario
        if self.active_training_card_satisfies_request(
            snapshot.active_training_card_routing,
            requested_scenario=requested_scenario,
            message=message,
            force_training_card=force_training_card,
        ):
            state.snapshot.memory = snapshot
            return
        created = self.safe_activate_training_card_from_coach_request(
            workspace_id=state.workspace_id,
            snapshot=state.snapshot,
            message=message,
            current_file=current_file,
            response_language=response_language,
            provider_service_override=provider_service_override,
        )
        if created is not None:
            refreshed_snapshot = self.runtime.memory_service.snapshot(state.workspace_id)
            if self.active_training_card_satisfies_request(
                refreshed_snapshot.active_training_card_routing,
                requested_scenario=requested_scenario,
                message=message,
                force_training_card=force_training_card,
            ):
                state.snapshot.memory = refreshed_snapshot
                return
        if not force_training_card and not self.message_requests_training_card_activation(
            message,
            requested_scenario=requested_scenario,
        ):
            return

        current_file_name = self.function_guidance_current_file_name(
            current_file_payload,
            scenario=requested_scenario,
        )
        default_focus, default_skill = self.training_card_defaults_for_scenario(
            requested_scenario,
            response_language,
        )
        focus_candidates: list[object] = []
        if active_thread is not None and active_thread_scenario in {"", requested_scenario, "general"}:
            focus_candidates.append(getattr(active_thread, "focus_area", ""))
        if requested_scenario == "general":
            focus_candidates.append(
                self.stateful_focus_area(
                    state.snapshot.current_task,
                    state.snapshot.plan,
                    state.snapshot.evaluation,
                    snapshot=state.snapshot,
                )
            )
        focus_candidates.append(default_focus)
        focus_hint = self.resolve_focus_hint(
            user_message=message,
            candidates=focus_candidates,
            fallback_current_file=current_file_name or None,
        )
        if requested_scenario == "function_guidance" and current_file_name and not focus_hint:
            focus_hint = current_file_name
        target_skill = default_skill if requested_scenario != "general" else (focus_hint or default_skill)
        context_bits = [f"Coach request: {str(message or '').strip()}"]
        if current_file_name:
            context_bits.append(f"Current file: {current_file_name}")
        active_next_step = str(getattr(active_thread, "next_step", "") or "").strip() if active_thread else ""
        if active_next_step and active_thread_scenario in {"", requested_scenario, "general"}:
            context_bits.append(f"Active thread: {active_next_step}")
        fallback_request = CardGenerationRequest(
            workspace_id=state.workspace_id,
            source="conversation_gap",
            card_type=self.requested_training_card_type(message),
            focus_area=focus_hint or default_focus,
            target_skill=target_skill,
            context_hint=" | ".join(bit for bit in context_bits if bit).strip()[:420],
            why_now=localized_text(
                "The learner asked Coach for one learn-first training move.",
                "学习者请 Coach 提供一个先学习再练习的训练动作。",
                response_language,
            ),
            difficulty="medium",
            response_language=self.validated_training_response_language(response_language),
        )
        fallback_request = fallback_request.model_copy(
            update=self.guided_training_workspace_facts(
                workspace_id=state.workspace_id,
                scenario=requested_scenario,
                current_file=current_file_payload,
            )
        )
        try:
            self.training_generate_candidate(
                fallback_request,
                provider_service_override=ProviderService(),
            )
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
        refreshed_snapshot = self.runtime.memory_service.snapshot(state.workspace_id)
        if not self.active_training_card_satisfies_request(
            refreshed_snapshot.active_training_card_routing,
            requested_scenario=requested_scenario,
            message=message,
            force_training_card=force_training_card,
        ):
            if self.direct_guided_training_card_fallback(
                workspace_id=state.workspace_id,
                scenario=requested_scenario,
                message=message,
                current_file=current_file,
                response_language=response_language,
                active_thread=active_thread,
            ):
                refreshed_snapshot = self.runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.memory = refreshed_snapshot

    def ensure_explicit_training_card_after_coach_reply(self, 
        *,
        state: SessionState,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        fallback_scenario: str | None = None,
        force_training_card: bool = False,
        provider_service_override: ProviderService | None = None,
    ) -> None:
        self.ensure_explicit_training_card_after_language_block(
            state=state,
            message=message,
            current_file=current_file,
            response_language=response_language,
            fallback_scenario=fallback_scenario,
            force_training_card=force_training_card,
            provider_service_override=provider_service_override,
        )
