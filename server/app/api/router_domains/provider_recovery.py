"""Provider readiness, model policy gates, language-corruption recovery, and failure overrides."""

from __future__ import annotations

from typing import Literal, cast

from fastapi import HTTPException

from ...core.models import (
    CoachScenario,
    CoachTurnSummary,
    EvaluationReport,
    LearningPlan,
    ProviderConfig,
    SessionMessageRequest,
    TaskSpec,
    TurnRequest,
    WorkbenchSnapshot,
)
from ...llm.prompts import infer_coaching_scenario as infer_message_coaching_scenario
from ...llm.provider.capability import _is_loopback_provider_url
from ...llm.provider_gateway import (
    NEWAPI_CONNECTION_TYPE,
)
from ...llm.provider_protocols import (
    normalize_provider_protocol,
)
from ...llm.provider_service import (
    ProviderService,
    _build_language_corruption_recovery_override,
)
from .._helpers import (
    localized_text,
    normalized_object_mapping,
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
    ensure_coach_turn_payload,
)
from ..coach_support import CoachTurnPayload
from ..provider_payload import (
    provider_api_key_from_payload,
    provider_config_from_payload,
    provider_connection_type_from_payload,
    provider_protocol_from_payload,
)
from ..router_support import (
    _attach_requested_workspace_files as _attach_requested_workspace_files,
)
from ..router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from ..router_support import (
    _request_requires_agent_tools,
    provider_recovery_resumed_next_step_text,
    provider_recovery_resumed_summary_text,
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
    NON_LEARNING_RECOVERY_STOP_REASONS,
    PROVIDER_REPLY_STOP_REASONS,
)


class ProviderRecoveryDomainMixin(RouterDomainBase):
    """Provider readiness, model policy gates, language-corruption recovery, and failure overrides."""

    def detect_provider_language_corruption(self, 
        coaching_service: ProviderService,
        *,
        message: str | None,
        response_language: str | None,
        coach_context: dict[str, object] | None = None,
    ):
        provider_config = getattr(coaching_service, "_config", None)
        provider_api_key = getattr(coaching_service, "_api_key", None)
        if (
            provider_config is None
            or not provider_api_key
            or not self.should_probe_language_integrity(message, response_language)
        ):
            return None
        if self.message_requests_lane_continuation(message):
            return None
        if self.coach_context_has_prepared_library_grounding(coach_context):
            return None
        if coaching_service.has_recent_language_integrity_success(
            message=message,
            response_language=response_language,
        ):
            return None
        # This preflight only reads ok/error_category from the result, so the
        # capabilities this transport already verified are not probed again
        # before a coaching reply; an explicit Settings test keeps live probes.
        probe_result = coaching_service.test(
            provider_config,
            provider_api_key,
            probe_message=message,
            response_language=response_language,
            reuse_verified_capabilities=True,
        )
        if (
            not probe_result.ok
            and probe_result.error_category == "language_corruption"
            and probe_result.provider_reachable is True
            and isinstance(probe_result.status_code, int)
        ):
            coaching_service.clear_language_integrity_success(
                message=message,
                response_language=response_language,
                provider_config=provider_config,
                api_key=provider_api_key,
            )
            return probe_result
        if probe_result.ok is True and not getattr(probe_result, "error_category", None):
            coaching_service.mark_language_integrity_success(
                message=message,
                response_language=response_language,
                provider_config=provider_config,
                api_key=provider_api_key,
            )
        return None

    def isolate_preflight_language_corruption_turn(self, 
        coach_turn: dict[str, object],
        *,
        message: str | None,
        current_file: dict[str, object] | None,
    ) -> dict[str, object]:
        if self.message_requests_lane_continuation(message):
            return coach_turn

        scenario = infer_message_coaching_scenario(
            str(message or ""),
            current_file,
            {"history_mode": "fresh_lane"},
            default="general",
        )
        context = normalized_object_mapping(coach_turn.get("coach_context")) or {}
        context.update(
            {
                "scenario": scenario,
                "active_thread": None,
                "history_mode": "fresh_lane",
            }
        )
        return {
            **coach_turn,
            "scenario": scenario,
            "coach_context": context,
        }

    def recover_guided_language_corruption(self, 
        *,
        coaching_service: ProviderService,
        snapshot: WorkbenchSnapshot,
        coach_turn: dict[str, object],
        message: str | None,
        response_language: str | None,
        detail: str = "",
        failure: dict[str, object] | None = None,
    ) -> tuple[str, dict[str, object], dict[str, object]] | None:
        coach_context = normalized_object_mapping(coach_turn.get("coach_context"))
        recovery_override = _build_language_corruption_recovery_override(
            str(message or ""),
            current_file=None,
            coach_context=coach_context,
            response_language=response_language,
        )
        if not isinstance(recovery_override, dict):
            return None

        scenario = str(
            coach_turn.get("scenario") or recovery_override.get("scenario") or ""
        ).strip()
        if not scenario:
            return None

        summary = str(recovery_override.get("summary") or "").strip()
        if not summary:
            summary = coaching_service.language_corruption_summary(
                response_language,
                scenario=scenario,
            )

        next_step = str(recovery_override.get("next_step") or "").strip()
        if not next_step:
            next_step = coaching_service.language_corruption_next_step(
                response_language,
                scenario=scenario,
            )

        teaching_note = str(recovery_override.get("teaching_note") or "").strip()
        if not teaching_note:
            teaching_note = localized_text(
                "Keep the same coaching lane and turn the next move into one local, verifiable step.",
                "\u7ee7\u7eed\u7559\u5728\u540c\u4e00\u6761\u6559\u7ec3\u4e3b\u7ebf\u91cc\uff0c\u628a\u4e0b\u4e00\u6b65\u6536\u675f\u6210\u4e00\u4e2a\u672c\u5730\u53ef\u9a8c\u8bc1\u7684\u5c0f\u52a8\u4f5c\u3002",
                response_language,
            )

        resume_thread = str(recovery_override.get("resume_thread") or "").strip()
        reply = str(recovery_override.get("reply") or "").strip()

        if self.message_requests_lane_continuation(message):
            local_resume_step = self.resolve_local_continuation_step(
                snapshot=snapshot,
                coach_turn=coach_turn,
                fallback_next_step=next_step,
            )
            if not local_resume_step:
                local_resume_step = self.local_continuation_step_for_scenario(
                    scenario,
                    response_language,
                )
            if local_resume_step:
                next_step = local_resume_step
                teaching_note = localized_text(
                    "Keep the same learning lane. When a short continuation is corrupted, resume from the saved thread locally and verify the next visible move.",
                    "\u7ee7\u7eed\u7559\u5728\u540c\u4e00\u6761\u5b66\u4e60\u4e3b\u7ebf\u91cc\u3002\u5f53\u77ed continuation \u88ab\u7834\u574f\u65f6\uff0c\u5148\u4ece\u5df2\u4fdd\u5b58\u7684 thread \u5728\u672c\u5730\u7eed\u4e0a\uff0c\u518d\u9a8c\u8bc1\u4e0b\u4e00\u4e2a\u53ef\u89c1\u52a8\u4f5c\u3002",
                    response_language,
                )
                resume_thread = localized_text(
                    f"Continue the saved coaching thread. Next: {next_step}",
                    f"\u7ee7\u7eed\u6cbf\u7740\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u63a8\u8fdb\u3002\u4e0b\u4e00\u6b65\uff1a{next_step}",
                    response_language,
                )
                reply = localized_text(
                    f"{summary}\n\nThe provider did not preserve this short continuation cleanly, so Trainer resumed the saved thread locally instead of repeating the provider setup blocker.\n\nNext step: {next_step}",
                    f"{summary}\n\nprovider \u6ca1\u6709\u7a33\u5b9a\u4fdd\u7559\u8fd9\u6761\u5f88\u77ed\u7684 continuation\uff0c\u6240\u4ee5 Trainer \u5148\u6309\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u5728\u672c\u5730\u7eed\u4e0a\uff0c\u4e0d\u518d\u91cd\u590d provider \u914d\u7f6e\u963b\u585e\u3002\n\n\u4e0b\u4e00\u6b65\uff1a{next_step}",
                    response_language,
                )

        if not resume_thread:
            resume_thread = self.build_resume_thread_text(
                summary,
                next_step,
                response_language=response_language,
            )
        if not reply:
            reply = summary

        if snapshot.coaching_state:
            snapshot.coaching_state = snapshot.coaching_state.model_copy(
                update={
                    "summary": summary,
                    "next_step": next_step,
                    "resume_thread": resume_thread,
                }
            )

        blocker = detail or summary
        meta: dict[str, object] = {
            "summary": summary,
            "next_step": next_step,
            "blocker": blocker,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
            "scenario": scenario,
            "stop_reason": str(
                recovery_override.get("stop_reason") or "language_corruption_recovered"
            ).strip()
            or "language_corruption_recovered",
            "fell_back": True,
        }
        if detail:
            meta["detail"] = detail
        if isinstance(failure, dict):
            meta.update(
                {
                    "error_category": str(
                        failure.get("error_category") or "language_corruption"
                    ).strip()
                    or "language_corruption",
                    "retryable": bool(failure.get("retryable")),
                    "status_code": failure.get("status_code"),
                    "provider_reachable": failure.get("provider_reachable"),
                    "model_supported": failure.get("model_supported"),
                }
            )

        return (
            reply,
            ensure_coach_turn_payload(
                self.merge_agent_finalize_into_coach_turn(
                    coach_turn,
                    summary=summary,
                    next_step=next_step,
                    blocker=blocker,
                    resume_thread=resume_thread,
                    teaching_note=teaching_note,
                ),
                coach_turn,
            ),
            meta,
        )

    def apply_language_corruption_override(self, 
        *,
        coaching_service: ProviderService,
        snapshot: WorkbenchSnapshot,
        coach_turn: dict[str, object],
        message: str | None,
        response_language: str | None,
        reply_corruption: bool = False,
        allow_guided_recovery: bool = True,
    ) -> tuple[str, dict[str, object], dict[str, object]]:
        scenario = str(coach_turn.get("scenario") or "").strip()
        normalized_message = str(message or "").strip().lower()
        coach_context = normalized_object_mapping(coach_turn.get("coach_context")) or {}
        fresh_lane = str(coach_context.get("history_mode") or "").strip().lower() == "fresh_lane"
        if (
            scenario == "general"
            and normalized_message
            and any(
                token in normalized_message
                for token in (
                    "prototype",
                    "mvp",
                    "i have an idea",
                    "turn this idea into",
                    "make it real",
                    "\u843d\u5730",
                    "\u539f\u578b",
                    "\u6700\u5c0f\u539f\u578b",
                    "\u6700\u5c0f\u53ef\u9a8c\u8bc1",
                    "\u505a\u51fa\u6765",
                    "\u505a\u6210\u539f\u578b",
                    "\u60f3\u5b9e\u73b0",
                    "\u60f3\u505a",
                    "\u6211\u6709\u4e2aidea",
                    "\u6211\u6709\u4e00\u4e2aidea",
                    "\u6211\u6709\u4e2aai idea",
                    "\u6211\u6709\u4e00\u4e2aai idea",
                )
            )
        ):
            scenario = "idea_implementation"
            coach_turn = dict(coach_turn)
            coach_turn["scenario"] = scenario
        if scenario == "general":
            active_thread = coach_context.get("active_thread")
            scenario = self.inherit_active_thread_scenario_for_continuation(
                scenario,
                message=message,
                active_thread=(
                    active_thread
                    if isinstance(active_thread, dict)
                    else snapshot.memory.active_thread
                ),
            )
            if str(coach_turn.get("scenario") or "").strip() != scenario:
                coach_turn = dict(coach_turn)
                coach_turn["scenario"] = scenario
        if scenario == "general" and not fresh_lane:
            latest_user_message = ""
            for historical_message in reversed(snapshot.messages):
                role = str(getattr(historical_message, "role", "") or "").strip().lower()
                if role != "user":
                    continue
                latest_user_message = str(
                    getattr(historical_message, "content", "") or ""
                ).strip()
                if latest_user_message:
                    break
            if latest_user_message:
                inferred_scenario = infer_message_coaching_scenario(
                    latest_user_message,
                    None,
                    normalized_object_mapping(coach_turn.get("coach_context")),
                )
                if inferred_scenario and inferred_scenario != "general":
                    scenario = inferred_scenario
                    coach_turn = dict(coach_turn)
                    coach_turn["scenario"] = scenario
        if str(coach_turn.get("scenario") or "").strip() != scenario:
            coach_turn = dict(coach_turn)
            coach_turn["scenario"] = scenario
        if allow_guided_recovery:
            recovered_override = self.recover_guided_language_corruption(
                coaching_service=coaching_service,
                snapshot=snapshot,
                coach_turn=coach_turn,
                message=message,
                response_language=response_language,
            )
            if recovered_override is not None:
                return recovered_override
        if reply_corruption:
            summary = coaching_service.provider_failure_summary(
                "language_corruption",
                response_language,
            )
            next_step = coaching_service.provider_failure_next_step(
                "language_corruption",
                response_language,
            )
        else:
            summary = coaching_service.language_corruption_summary(
                response_language,
                scenario=scenario,
            )
            next_step = coaching_service.language_corruption_next_step(
                response_language,
                scenario=scenario,
            )
        blocker = summary
        if self.message_requests_lane_continuation(message):
            local_resume_step = self.resolve_local_continuation_step(
                snapshot=snapshot,
                coach_turn=coach_turn,
                fallback_next_step=next_step,
            )
            if not local_resume_step:
                local_resume_step = self.local_continuation_step_for_scenario(
                    scenario,
                    response_language,
                )
            if local_resume_step:
                next_step = local_resume_step
                teaching_note = localized_text(
                    "Keep the same learning lane. When a short continuation is corrupted, resume from the saved thread locally and verify the next visible move.",
                    "\u7ee7\u7eed\u7559\u5728\u540c\u4e00\u6761\u5b66\u4e60\u4e3b\u7ebf\u91cc\u3002\u5f53\u77ed continuation \u88ab\u7834\u574f\u65f6\uff0c\u5148\u4ece\u5df2\u4fdd\u5b58\u7684 thread \u5728\u672c\u5730\u7eed\u4e0a\uff0c\u518d\u9a8c\u8bc1\u4e0b\u4e00\u4e2a\u53ef\u89c1\u52a8\u4f5c\u3002",
                    response_language,
                )
                resume_thread = localized_text(
                    f"Continue the saved coaching thread. Next: {next_step}",
                    f"\u7ee7\u7eed\u6cbf\u7740\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u63a8\u8fdb\u3002\u4e0b\u4e00\u6b65\uff1a{next_step}",
                    response_language,
                )
                if snapshot.coaching_state:
                    snapshot.coaching_state = snapshot.coaching_state.model_copy(
                        update={
                            "summary": summary,
                            "next_step": next_step,
                            "resume_thread": resume_thread,
                        }
                    )
                return (
                    localized_text(
                        f"{summary}\n\nThe provider did not preserve this short continuation cleanly, so Trainer resumed the saved thread locally instead of repeating the provider setup blocker.\n\nNext step: {next_step}",
                        f"{summary}\n\nprovider \u6ca1\u6709\u7a33\u5b9a\u4fdd\u7559\u8fd9\u6761\u5f88\u77ed\u7684 continuation\uff0c\u6240\u4ee5 Trainer \u5148\u6309\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u5728\u672c\u5730\u7eed\u4e0a\uff0c\u4e0d\u518d\u91cd\u590d provider \u914d\u7f6e\u963b\u585e\u3002\n\n\u4e0b\u4e00\u6b65\uff1a{next_step}",
                        response_language,
                    ),
                    ensure_coach_turn_payload(
                        self.merge_agent_finalize_into_coach_turn(
                            coach_turn,
                            summary=summary,
                            next_step=next_step,
                            blocker=blocker,
                            resume_thread=resume_thread,
                            teaching_note=teaching_note,
                        ),
                        coach_turn,
                    ),
                    {
                        "summary": summary,
                        "next_step": next_step,
                        "blocker": blocker,
                        "teaching_note": teaching_note,
                        "resume_thread": resume_thread,
                        "scenario": scenario,
                        "stop_reason": "language_corruption",
                        "fell_back": True,
                    },
                )
        teaching_note = localized_text(
            "Pause the lesson until the provider path preserves the original sentence.",
            "\u5148\u8ba9 provider \u94fe\u8def\u5b8c\u6574\u4fdd\u7559\u539f\u53e5\uff0c\u518d\u7ee7\u7eed\u8fd9\u6761\u6559\u5b66\u4e3b\u7ebf\u3002",
            response_language,
        )
        resume_thread = self.build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
        if snapshot.coaching_state:
            snapshot.coaching_state = snapshot.coaching_state.model_copy(
                update={
                    "summary": summary,
                    "next_step": next_step,
                    "resume_thread": resume_thread,
                }
            )
        return (
            coaching_service.provider_failure_reply(
                "language_corruption",
                None,
                response_language,
            )
            if reply_corruption
            else coaching_service.language_corruption_reply(
                response_language,
                scenario=scenario,
            ),
            ensure_coach_turn_payload(
                self.merge_agent_finalize_into_coach_turn(
                    coach_turn,
                    summary=summary,
                    next_step=next_step,
                    blocker=blocker,
                    resume_thread=resume_thread,
                    teaching_note=teaching_note,
                ),
                coach_turn,
            ),
            {
                "summary": summary,
                "next_step": next_step,
                "blocker": blocker,
                "teaching_note": teaching_note,
                "resume_thread": resume_thread,
                "scenario": scenario,
                "stop_reason": "language_corruption",
                "fell_back": True,
            },
        )

    def recovery_turn_has_no_learning_evidence(self, 
        *,
        stop_reason: str | None,
        recovered_stop_reason: str | None = None,
        local_sequence_fallback: bool = False,
    ) -> bool:
        reasons = (
            str(stop_reason or "").strip(),
            str(recovered_stop_reason or "").strip(),
        )
        # A local sequence can still be a successful, evidence-bearing lesson.
        # Only the underlying provider/recovery reason makes the turn non-learning.
        return any(
            reason in NON_LEARNING_RECOVERY_STOP_REASONS or reason.startswith("agent_error")
            for reason in reasons
            if reason
        )

    def is_provider_recovery_thread_payload(self, active_thread: object | None) -> bool:
        """Identify a saved provider-recovery lane before it is normalized away."""
        if not isinstance(active_thread, dict):
            return False
        recovery_state = str(active_thread.get("recovery_state") or "").strip().lower()
        if recovery_state == "provider_or_local":
            return True
        combined = " ".join(
            str(active_thread.get(key) or "").strip().lower()
            for key in ("blocker", "next_step", "teaching_note")
        )
        return "provider" in combined and any(
            marker in combined
            for marker in (
                "gateway",
                "question mark",
                "question marks",
                "english",
            )
        )

    def provider_recovery_resumed_summary(self, response_language: str | None) -> str:
        return provider_recovery_resumed_summary_text(response_language)

    def provider_recovery_resumed_next_step(self, 
        scenario: str,
        response_language: str | None,
    ) -> str:
        return provider_recovery_resumed_next_step_text(
            scenario,
            response_language,
        )

    def consume_provider_reply_failure_override(self, 
        *,
        coaching_service: ProviderService,
        snapshot: WorkbenchSnapshot,
        coach_turn: dict[str, object],
        message: str | None,
        response_language: str | None,
        workspace_id: str | None = None,
    ) -> tuple[str, dict[str, object], dict[str, object]] | None:
        failure = coaching_service.consume_last_reply_failure()
        if not isinstance(failure, dict):
            return None
        category = str(failure.get("error_category") or "").strip() or "unknown"
        if category not in PROVIDER_REPLY_STOP_REASONS:
            return None
        detail = str(failure.get("detail") or "").strip()
        if category == "language_corruption":
            scenario = str(coach_turn.get("scenario") or "").strip()
            normalized_message = str(message or "").strip().lower()
            if (
                scenario == "general"
                and normalized_message
                and any(
                    token in normalized_message
                    for token in (
                        "prototype",
                        "mvp",
                        "i have an idea",
                        "turn this idea into",
                        "make it real",
                        "\u843d\u5730",
                        "\u539f\u578b",
                        "\u6700\u5c0f\u539f\u578b",
                        "\u6700\u5c0f\u53ef\u9a8c\u8bc1",
                        "\u505a\u51fa\u6765",
                        "\u505a\u6210\u539f\u578b",
                        "\u60f3\u5b9e\u73b0",
                        "\u60f3\u505a",
                        "\u6211\u6709\u4e2aidea",
                        "\u6211\u6709\u4e00\u4e2aidea",
                        "\u6211\u6709\u4e2aai idea",
                        "\u6211\u6709\u4e00\u4e2aai idea",
                    )
                )
            ):
                leftover_blocks_lane = bool(
                    workspace_id and self.recovered_overlay_without_live_object(workspace_id)
                )
                if not leftover_blocks_lane:
                    scenario = "idea_implementation"
                    coach_turn = dict(coach_turn)
                    coach_turn["scenario"] = scenario
            if scenario == "general":
                coach_context = coach_turn.get("coach_context")
                active_thread = (
                    coach_context.get("active_thread")
                    if isinstance(coach_context, dict)
                    else None
                )
                scenario = self.inherit_active_thread_scenario_for_continuation(
                    scenario,
                    message=message,
                    active_thread=(
                        active_thread
                        if isinstance(active_thread, dict)
                        else snapshot.memory.active_thread
                    ),
                )
                if str(coach_turn.get("scenario") or "").strip() != scenario:
                    coach_turn = dict(coach_turn)
                    coach_turn["scenario"] = scenario
            if scenario == "general":
                latest_user_message = ""
                for historical_message in reversed(snapshot.messages):
                    role = str(getattr(historical_message, "role", "") or "").strip().lower()
                    if role != "user":
                        continue
                    latest_user_message = str(
                        getattr(historical_message, "content", "") or ""
                    ).strip()
                    if latest_user_message:
                        break
                if latest_user_message:
                    inferred_scenario = infer_message_coaching_scenario(
                        latest_user_message,
                        None,
                        normalized_object_mapping(coach_turn.get("coach_context")),
                    )
                    if inferred_scenario and inferred_scenario != "general":
                        scenario = inferred_scenario
                        coach_turn = dict(coach_turn)
                        coach_turn["scenario"] = scenario
            if str(coach_turn.get("scenario") or "").strip() != scenario:
                coach_turn = dict(coach_turn)
                coach_turn["scenario"] = scenario
            recovered_override = self.recover_guided_language_corruption(
                coaching_service=coaching_service,
                snapshot=snapshot,
                coach_turn=coach_turn,
                message=message,
                response_language=response_language,
                detail=detail,
                failure=failure,
            )
            if recovered_override is not None:
                return recovered_override
            summary = coaching_service.provider_failure_summary(
                "language_corruption",
                response_language,
            )
            next_step = coaching_service.provider_failure_next_step(
                "language_corruption",
                response_language,
            )
            blocker = summary
            if self.message_requests_lane_continuation(message):
                local_resume_step = self.resolve_local_continuation_step(
                    snapshot=snapshot,
                    coach_turn=coach_turn,
                    fallback_next_step=next_step,
                )
                if not local_resume_step:
                    local_resume_step = self.local_continuation_step_for_scenario(
                        scenario,
                        response_language,
                    )
                if local_resume_step:
                    next_step = local_resume_step
                    teaching_note = localized_text(
                        "Keep the same learning lane. When a short continuation is corrupted, resume from the saved thread locally and verify the next visible move.",
                        "\u7ee7\u7eed\u7559\u5728\u540c\u4e00\u6761\u5b66\u4e60\u4e3b\u7ebf\u91cc\u3002\u5f53\u77ed continuation \u88ab\u7834\u574f\u65f6\uff0c\u5148\u4ece\u5df2\u4fdd\u5b58\u7684 thread \u5728\u672c\u5730\u7eed\u4e0a\uff0c\u518d\u9a8c\u8bc1\u4e0b\u4e00\u4e2a\u53ef\u89c1\u52a8\u4f5c\u3002",
                        response_language,
                    )
                    resume_thread = localized_text(
                        f"Continue the saved coaching thread. Next: {next_step}",
                        f"\u7ee7\u7eed\u6cbf\u7740\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u63a8\u8fdb\u3002\u4e0b\u4e00\u6b65\uff1a{next_step}",
                        response_language,
                    )
                    if snapshot.coaching_state:
                        snapshot.coaching_state = snapshot.coaching_state.model_copy(
                            update={
                                "summary": summary,
                                "next_step": next_step,
                                "resume_thread": resume_thread,
                            }
                        )
                    recovered_failure_meta: dict[str, object] = {
                        "summary": summary,
                        "next_step": next_step,
                        "blocker": blocker,
                        "teaching_note": teaching_note,
                        "resume_thread": resume_thread,
                        "scenario": scenario,
                        "stop_reason": category,
                        "error_category": category,
                        "detail": detail,
                        "retryable": bool(failure.get("retryable")),
                        "status_code": failure.get("status_code"),
                        "provider_reachable": failure.get("provider_reachable"),
                        "model_supported": failure.get("model_supported"),
                        "fell_back": True,
                    }
                    return (
                        localized_text(
                            f"{summary}\n\nThe provider did not preserve this short continuation cleanly, so Trainer resumed the saved thread locally instead of repeating the provider setup blocker.\n\nNext step: {next_step}",
                            f"{summary}\n\nprovider \u6ca1\u6709\u7a33\u5b9a\u4fdd\u7559\u8fd9\u6761\u5f88\u77ed\u7684 continuation\uff0c\u6240\u4ee5 Trainer \u5148\u6309\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u5728\u672c\u5730\u7eed\u4e0a\uff0c\u4e0d\u518d\u91cd\u590d provider \u914d\u7f6e\u963b\u585e\u3002\n\n\u4e0b\u4e00\u6b65\uff1a{next_step}",
                            response_language,
                        ),
                        ensure_coach_turn_payload(
                            self.merge_agent_finalize_into_coach_turn(
                                coach_turn,
                                summary=summary,
                                next_step=next_step,
                                blocker=blocker,
                                resume_thread=resume_thread,
                                teaching_note=teaching_note,
                            ),
                            coach_turn,
                        ),
                        recovered_failure_meta,
                    )
            teaching_note = localized_text(
                "Pause the lesson until the provider path preserves the original sentence.",
                "\u5148\u8ba9 provider \u94fe\u8def\u5b8c\u6574\u4fdd\u7559\u539f\u53e5\uff0c\u518d\u7ee7\u7eed\u8fd9\u6761\u6559\u5b66\u4e3b\u7ebf\u3002",
                response_language,
            )
            resume_thread = self.build_resume_thread_text(
                summary,
                next_step,
                response_language=response_language,
            )
            if snapshot.coaching_state:
                snapshot.coaching_state = snapshot.coaching_state.model_copy(
                    update={
                        "summary": summary,
                        "next_step": next_step,
                        "resume_thread": resume_thread,
                    }
                )
            language_failure_meta: dict[str, object] = {
                "summary": summary,
                "next_step": next_step,
                "blocker": blocker,
                "teaching_note": teaching_note,
                "resume_thread": resume_thread,
                "scenario": scenario,
                "stop_reason": category,
                "error_category": category,
                "detail": detail,
                "retryable": bool(failure.get("retryable")),
                "status_code": failure.get("status_code"),
                "provider_reachable": failure.get("provider_reachable"),
                "model_supported": failure.get("model_supported"),
                "fell_back": True,
            }
            return (
                coaching_service.provider_failure_reply(
                    "language_corruption",
                    detail,
                    response_language,
                ),
                ensure_coach_turn_payload(
                    self.merge_agent_finalize_into_coach_turn(
                        coach_turn,
                        summary=summary,
                        next_step=next_step,
                        blocker=blocker,
                        resume_thread=resume_thread,
                        teaching_note=teaching_note,
                    ),
                    coach_turn,
                ),
                language_failure_meta,
            )
        summary = coaching_service.provider_failure_summary(category, response_language)
        next_step = coaching_service.provider_failure_next_step(category, response_language)
        blocker = summary
        teaching_note = localized_text(
            "Keep the current plan and thread intact; unblock the provider path first, then resume from the same next step.",
            "\u5148\u4fdd\u6301\u5f53\u524d\u8ba1\u5212\u548c thread \u4e0d\u53d8\uff0c\u5148\u628a provider \u94fe\u8def\u4fee\u901a\uff0c\u518d\u4ece\u540c\u4e00\u4e2a\u4e0b\u4e00\u6b65\u7ee7\u7eed\u3002",
            response_language,
        )
        resume_thread = self.build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
        if snapshot.coaching_state:
            snapshot.coaching_state = snapshot.coaching_state.model_copy(
                update={
                    "summary": summary,
                    "next_step": next_step,
                    "resume_thread": resume_thread,
                }
            )
        provider_failure_meta: dict[str, object] = {
            "summary": summary,
            "next_step": next_step,
            "blocker": blocker,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
            "stop_reason": category,
            "error_category": category,
            "detail": detail,
            "retryable": bool(failure.get("retryable")),
            "status_code": failure.get("status_code"),
            "provider_reachable": failure.get("provider_reachable"),
            "model_supported": failure.get("model_supported"),
            "fell_back": True,
        }
        return (
            coaching_service.provider_failure_reply(
                category,
                detail or None,
                response_language,
            ),
            ensure_coach_turn_payload(
                self.merge_agent_finalize_into_coach_turn(
                    coach_turn,
                    summary=summary,
                    next_step=next_step,
                    blocker=blocker,
                    resume_thread=resume_thread,
                    teaching_note=teaching_note,
                ),
                coach_turn,
            ),
            provider_failure_meta,
        )

    def build_empty_response_visible_reply(self, 
        *,
        summary: object,
        next_step: object,
        response_language: str | None,
    ) -> str:
        summary_text = str(summary or "").strip() or localized_text(
            "The provider returned an empty visible answer, so this turn cannot be treated as complete.",
            "\u0070\u0072\u006f\u0076\u0069\u0064\u0065\u0072 \u8fd4\u56de\u4e86\u7a7a\u7684\u53ef\u89c1\u56de\u7b54\uff0c\u6240\u4ee5\u8fd9\u8f6e\u4e0d\u80fd\u7b97\u5b8c\u6210\u3002",
            response_language,
        )
        next_step_text = str(next_step or "").strip() or localized_text(
            "Retry the turn and require one visible, verifiable conclusion.",
            "\u91cd\u8bd5\u8fd9\u4e00\u8f6e\uff0c\u5e76\u8981\u6c42\u8fd4\u56de\u4e00\u4e2a\u53ef\u89c1\u3001\u53ef\u9a8c\u8bc1\u7684\u7ed3\u8bba\u3002",
            response_language,
        )
        return localized_text(
            (
                f"{summary_text}\n\n"
                "The provider returned an empty visible answer, so Trainer kept this turn "
                "recoverable instead of pretending the model completed it.\n\n"
                f"Next step: {next_step_text}"
            ),
            (
                f"{summary_text}\n\n"
                "\u0070\u0072\u006f\u0076\u0069\u0064\u0065\u0072 \u8fd4\u56de\u4e86\u7a7a\u7684\u53ef\u89c1\u56de\u7b54\uff0c\u6240\u4ee5 Trainer "
                "\u4f1a\u628a\u8fd9\u4e00\u8f6e\u4fdd\u6301\u4e3a\u53ef\u6062\u590d\u72b6\u6001\uff0c\u800c\u4e0d\u662f\u5047\u88c5 model "
                "\u5df2\u7ecf\u5b8c\u6210\u3002\n\n"
                f"\u4e0b\u4e00\u6b65\uff1a{next_step_text}"
            ),
            response_language,
        )

    def consume_provider_empty_reply_override(self, 
        *,
        coaching_service: ProviderService,
        snapshot: WorkbenchSnapshot,
        coach_turn: dict[str, object],
        response_language: str | None,
        assistant_content: str,
    ) -> tuple[str, dict[str, object], dict[str, object]] | None:
        override = coaching_service.consume_last_reply_override()
        if not isinstance(override, dict):
            return None
        stop_reason = str(override.get("stop_reason") or "").strip()
        if stop_reason != "empty_response":
            return None
        summary = str(override.get("summary") or "").strip() or localized_text(
            "The provider returned an empty visible answer, so I kept the same coaching thread moving locally.",
            "provider \u8fd4\u56de\u4e86\u7a7a\u7684\u53ef\u89c1\u7b54\u6848\uff0c\u6240\u4ee5\u6211\u5148\u5728\u672c\u5730\u628a\u540c\u4e00\u6761\u6559\u7ec3 thread \u63a5\u7eed\u4e0b\u53bb\u3002",
            response_language,
        )
        next_step = str(override.get("next_step") or "").strip() or localized_text(
            "Retry the same turn and require one visible conclusion.",
            "\u91cd\u8bd5\u540c\u4e00\u8f6e\uff0c\u5e76\u8981\u6c42\u7ed9\u51fa\u4e00\u4e2a\u53ef\u89c1\u7ed3\u8bba\u3002",
            response_language,
        )
        blocker = str(override.get("blocker") or "").strip() or summary
        teaching_note = str(override.get("teaching_note") or "").strip() or localized_text(
            "Keep the same learning lane and ask for one visible, verifiable conclusion on the next turn.",
            "\u7ee7\u7eed\u7559\u5728\u540c\u4e00\u6761\u5b66\u4e60\u4e3b\u7ebf\u91cc\uff0c\u4e0b\u4e00\u8f6e\u53ea\u8981\u6c42\u4e00\u4e2a\u53ef\u89c1\u3001\u53ef\u9a8c\u8bc1\u7684\u7ed3\u8bba\u3002",
            response_language,
        )
        resume_thread = str(override.get("resume_thread") or "").strip() or self.build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
        if snapshot.coaching_state:
            snapshot.coaching_state = snapshot.coaching_state.model_copy(
                update={
                    "summary": summary,
                    "next_step": next_step,
                    "resume_thread": resume_thread,
                }
            )
        visible_reply = localized_text(
            f"{summary}\n\nThe provider returned an empty visible answer, so Trainer kept this turn recoverable instead of pretending the model completed it.\n\nNext step: {next_step}",
            f"{summary}\n\nprovider 返回了空的可见答案，所以 Trainer 先把这一轮保持为可恢复状态，而不是假装 model 已经完成。\n\n下一步：{next_step}",
            response_language,
        )
        visible_reply = self.build_empty_response_visible_reply(
            summary=summary,
            next_step=next_step,
            response_language=response_language,
        )
        empty_response_meta: dict[str, object] = {
            "summary": summary,
            "next_step": next_step,
            "blocker": blocker,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
            "stop_reason": "empty_response",
            "fell_back": True,
        }
        return (
            visible_reply,
            ensure_coach_turn_payload(
                self.merge_agent_finalize_into_coach_turn(
                    coach_turn,
                    summary=summary,
                    next_step=next_step,
                    blocker=blocker,
                    resume_thread=resume_thread,
                    teaching_note=teaching_note,
                ),
                coach_turn,
            ),
            empty_response_meta,
        )

    def ensure_coach_provider_ready(self, 
        coaching_service: ProviderService,
        *,
        response_language: str | None,
    ) -> None:
        provider = getattr(coaching_service, "_config", None)
        if isinstance(provider, ProviderConfig):
            policy_violation = self.provider_model_policy_violation(provider)
            if policy_violation is not None:
                raise HTTPException(
                    status_code=400,
                    detail=self.provider_model_policy_detail(
                        provider,
                        policy_violation,
                        response_language,
                    ),
                )
        config = getattr(coaching_service, "_config", None)
        local_without_key = not coaching_service.has_api_key and _is_loopback_provider_url(
            getattr(config, "base_url", None)
        )
        if coaching_service.has_api_key or local_without_key:
            return
        detail = localized_text(
            "Trainer needs a saved model provider and API key before a coaching turn can start.",
            "Trainer \u9700\u8981\u5148\u4fdd\u5b58\u53ef\u7528\u7684 model provider \u548c API key\uff0c\u6559\u7ec3\u5bf9\u8bdd\u624d\u80fd\u5f00\u59cb\u3002",
            response_language,
        )
        raise HTTPException(status_code=400, detail=detail)
        raise HTTPException(
            status_code=400,
            detail=localized_text(
                "Trainer needs a saved model provider and API key before a coaching turn can start.",
                "Trainer \u9700\u8981\u5148\u4fdd\u5b58\u53ef\u7528\u7684 model provider \u548c API key\uff0c\u6559\u7ec3\u5bf9\u8bdd\u624d\u80fd\u5f00\u59cb\u3002",
                response_language,
            ),
        )

    def ensure_agent_tools_ready(self, 
        request: TurnRequest | SessionMessageRequest,
        coaching_service: ProviderService,
    ) -> None:
        """Reject grounded/tool lanes instead of silently degrading to plain chat."""
        if not _request_requires_agent_tools(request):
            return
        config = getattr(coaching_service, "_config", None)
        local_without_key = not coaching_service.has_api_key and _is_loopback_provider_url(
            getattr(config, "base_url", None)
        )
        if (
            (coaching_service.has_api_key or local_without_key)
            and self.runtime.provider_connection_verified(coaching_service)
            and self.runtime.provider_capability_state_for(coaching_service, "tools") == "verified"
        ):
            return
        raise HTTPException(
            status_code=409,
            detail=localized_text(
                "This action needs a verified tools-capable provider. Test a provider with tool calls in Settings before continuing.",
                "\u8fd9\u4e2a\u52a8\u4f5c\u9700\u8981\u5df2\u9a8c\u8bc1\u652f\u6301\u5de5\u5177\u8c03\u7528\u7684 Provider\u3002\u8bf7\u5148\u5728\u8bbe\u7f6e\u4e2d\u6d4b\u8bd5\u652f\u6301 tools \u7684 Provider\u3002",
                request.response_language,
            ),
        )

    def ensure_streaming_ready(self, 
        coaching_service: ProviderService,
        response_language: str | None,
    ) -> None:
        """Block only an explicitly unsupported stream, never an unverified one.

        The first real send is the live confirmation. Requiring a prior test
        made a saved connection unusable until the learner ran Settings > Test.
        If the provider explicitly reported streaming as unsupported, fail
        closed; otherwise let the actual stream attempt produce the truth.
        """

        config = getattr(coaching_service, "_config", None)
        loopback_without_key = not coaching_service.has_api_key and _is_loopback_provider_url(
            getattr(config, "base_url", None)
        )
        if not coaching_service.has_api_key and not loopback_without_key:
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "Add the API key before continuing.",
                    "请先补上 API 密钥再继续。",
                    response_language,
                ),
            )
        state = self.runtime.provider_capability_state_for(coaching_service, "streaming")
        if state in {"unsupported", "disabled"}:
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "This provider reports that streaming is unsupported. Choose a streaming-capable provider or protocol.",
                    "这个 Provider 明确不支持流式输出。请换一个支持流式的 Provider 或协议。",
                    response_language,
                ),
            )

    def provider_payload_declares_unknown_protocol(self, payload: dict) -> bool:
        provider_payload = payload.get("provider")
        if not isinstance(provider_payload, dict):
            return False
        provider_protocol = provider_protocol_from_payload(provider_payload)
        connection_type = provider_connection_type_from_payload(provider_payload)
        declared_protocol_raw = provider_payload.get("protocol") or provider_payload.get("api")
        declared_unknown = (
            isinstance(declared_protocol_raw, str)
            and bool(str(declared_protocol_raw).strip())
            and provider_protocol is None
        )
        return declared_unknown or (
            provider_protocol is None and connection_type == NEWAPI_CONNECTION_TYPE
        )

    def provider_transport_is_configured(self, 
        name: object = "",
        base_url: object = "",
        model: object = "",
    ) -> bool:
        return bool(str(name or "").strip() and str(base_url or "").strip() and str(model or "").strip())

    def provider_is_live_usable(self, coaching_service: ProviderService, payload: dict) -> bool:
        if self.provider_payload_declares_unknown_protocol(payload):
            return False
        provider_payload = payload.get("provider") if isinstance(payload, dict) else None
        if isinstance(provider_payload, dict) and provider_payload:
            if not self.provider_transport_is_configured(
                provider_payload.get("name") or provider_payload.get("label"),
                provider_payload.get("base_url") or provider_payload.get("baseUrl"),
                provider_payload.get("model"),
            ):
                return False
        config = getattr(coaching_service, "_config", None)
        if isinstance(config, ProviderConfig):
            if not self.provider_transport_is_configured(config.name, config.base_url, config.model):
                return False
            raw_protocol = getattr(config, "protocol", None)
            if raw_protocol and normalize_provider_protocol(raw_protocol) is None:
                return False
        # A caller-supplied API key is an explicit one-request provider override;
        # the request itself is the connectivity probe, so requiring a prior
        # Settings test would reject valid preview and integration callers.
        if isinstance(payload, dict) and provider_api_key_from_payload(payload):
            return bool(getattr(coaching_service, "has_api_key", False))
        return self.runtime.provider_connection_verified(coaching_service)

    def provider_service_allows_object_minting(self, 
        provider_service: ProviderService | None = None,
    ) -> bool:
        service = provider_service or self.runtime.provider_service
        return self.provider_is_live_usable(service, {})

    def honest_suggested_actions_without_usable_provider(self, 
        actions: list[dict[str, object]],
        *,
        response_language: str | None,
        snapshot: WorkbenchSnapshot | None = None,
        current_task: TaskSpec | None = None,
        current_plan: LearningPlan | None = None,
        current_evaluation: EvaluationReport | None = None,
    ) -> list[dict[str, object]]:
        kept = list(actions)
        if kept:
            return kept
        return self.structured_suggested_actions(
            [
                {
                    "label": localized_text(
                        "Repair the provider in Settings, then resend this turn.",
                        "先在设置里修好连接，再重发这一轮。",
                        response_language,
                    ),
                    "action": "hint",
                }
            ],
            response_language=response_language,
            scenario="general",
            focus_area=self.stateful_focus_area(
                current_task,
                current_plan,
                current_evaluation,
                snapshot=snapshot,
            ),
        )

    def honest_unusable_provider_coach_turn(self, 
        *,
        response_language: str | None,
        snapshot: WorkbenchSnapshot,
        coaching_service: ProviderService,
        object_kind: Literal["task", "plan", "coach"] = "coach",
        scenario: CoachScenario = "general",
    ) -> CoachTurnPayload:
        if object_kind == "plan":
            summary = localized_text(
                "This connection is not ready. Test it in Settings, then resend this turn. Trainer did not invent a plan.",
                "当前连接还不能用。请先在设置里测试，再重发这一轮。Trainer 没有生成新计划。",
                response_language,
            )
        elif object_kind == "task":
            summary = localized_text(
                "This connection is not ready. Test it in Settings, then resend this turn. Trainer did not invent a task.",
                "当前连接还不能用。请先在设置里测试，再重发这一轮。Trainer 没有生成新任务。",
                response_language,
            )
        else:
            summary = localized_text(
                "This connection is not ready. Test it in Settings, then resend this turn.",
                "当前连接还不能用。请先在设置里测试，再重发这一轮。",
                response_language,
            )
        next_step = coaching_service.provider_failure_next_step("unknown", response_language)
        actions = self.honest_suggested_actions_without_usable_provider(
            [],
            response_language=response_language,
            snapshot=snapshot,
            current_task=snapshot.current_task,
            current_plan=snapshot.plan,
            current_evaluation=snapshot.evaluation,
        )
        return {
            "scenario": scenario,
            "learner_signal": "steady",
            "coach_context": {},
            "suggested_actions": actions,
            "artifacts": {},
            "coach_turn": CoachTurnSummary(
                scenario=scenario,
                learner_signal="steady",
                summary=summary,
                next_step=next_step,
            ),
            "stream": False,
        }

    def normalized_provider_model_names(self, values: object) -> set[str]:
        if not isinstance(values, list):
            return set()
        return {
            str(value).strip().casefold()
            for value in values
            if str(value).strip()
        }

    def provider_model_policy_violation(self, provider: ProviderConfig) -> str | None:
        selected_model = str(provider.model or "").strip()
        if not selected_model:
            return None
        normalized_model = selected_model.casefold()
        denied_models = self.normalized_provider_model_names(provider.denied_models)
        if normalized_model in denied_models:
            return "model_denied"
        allowed_models = self.normalized_provider_model_names(provider.allowed_models)
        if allowed_models and normalized_model not in allowed_models:
            return "model_not_allowed"
        return None

    def provider_model_policy_detail(self, 
        provider: ProviderConfig,
        policy_violation: str,
        response_language: str | None,
    ) -> str:
        model = str(provider.model or "").strip()
        if policy_violation == "model_denied":
            return localized_text(
                f"The selected model '{model}' is blocked for this connection. Choose a different model and try again.",
                f"\u5f53\u524d\u8fde\u63a5\u5df2\u7981\u6b62\u4f7f\u7528\u6a21\u578b\u300c{model}\u300d\u3002\u8bf7\u4ece\u6a21\u578b\u5217\u8868\u4e2d\u66f4\u6362\u4e00\u4e2a\u540e\u518d\u8bd5\u3002",
                response_language,
            )
        return localized_text(
            f"The selected model '{model}' is not in this connection's allowed model list. Choose a model from the list and try again.",
            f"\u5f53\u524d\u9009\u62e9\u7684\u6a21\u578b\u300c{model}\u300d\u4e0d\u5728\u6b64\u8fde\u63a5\u5141\u8bb8\u4f7f\u7528\u7684\u6a21\u578b\u5217\u8868\u4e2d\u3002\u8bf7\u4ece\u5217\u8868\u4e2d\u9009\u62e9\u4e00\u4e2a\u6a21\u578b\u540e\u518d\u8bd5\u3002",
            response_language,
        )

    def build_coaching_service(self, payload: dict) -> ProviderService:
        override_config = provider_config_from_payload(payload)
        api_key_override = provider_api_key_from_payload(payload)
        workspace_id = str(payload.get("workspace_id") or payload.get("workspaceId") or "").strip()
        last_test = payload.get("last_test_result") or payload.get("lastTestResult")
        last_test_payload = last_test if isinstance(last_test, dict) else None
        if override_config is not None or api_key_override is not None:
            service = self.runtime.provider_service_for(override_config, api_key_override)
            self.runtime.rehydrate_last_test(
                override_config or getattr(service, "_config", None),
                api_key_override if api_key_override is not None else getattr(service, "_api_key", None),
                last_test=last_test_payload,
                workspace_id=workspace_id,
            )
            return self.runtime.overlay_last_test_on_service(service)
        # No inline provider. The browser side panel — which must never see a
        # provider key — reaches the chat routes this way; it uses the provider
        # the UI host last named for this workspace, when the host named one.
        # Without that the sidecar's own (unconfigured) default answered 400.
        workspace_service = self.runtime.workspace_provider_service(workspace_id)
        if workspace_service is not None:
            return self.runtime.overlay_last_test_on_service(workspace_service)
        self.runtime.rehydrate_last_test(
            getattr(self.runtime.provider_service, "_config", None),
            getattr(self.runtime.provider_service, "_api_key", None),
            last_test=last_test_payload,
            workspace_id=workspace_id,
        )
        return self.runtime.overlay_last_test_on_service(self.runtime.provider_service)

    def reject_blank_coach_message(self, request: TurnRequest) -> None:
        """Coach turns cost a live model call; a blank message is always a mistake."""
        if not request.message.strip():
            raise HTTPException(
                status_code=422,
                detail="Please type a message before sending. | 请输入消息内容后再发送。",
            )

    def reject_if_provider_not_live_usable(self, 
        coaching_service: ProviderService,
        payload: dict,
        response_language: str | None,
    ) -> None:
        overlay = getattr(self.runtime, "overlay_last_test_on_service", None)
        if callable(overlay):
            coaching_service = cast(ProviderService, overlay(coaching_service))
        if self.provider_is_live_usable(coaching_service, payload):
            return
        raise HTTPException(
            status_code=400,
            detail=localized_text(
                "This connection is not ready. Test it in Settings, then resend this turn.",
                "当前连接还不能用。请先在设置里测试，再重发这一轮。",
                response_language,
            ),
        )
