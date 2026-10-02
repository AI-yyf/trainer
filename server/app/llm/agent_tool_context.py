"""Agent tool-context assembly (§五十二: extracted from provider_service.py).

Builds the extra context block the coach agent loop receives: explicit
write-tool scoping, denied auto-mint tool reporting, and the
learner-pressure / streak / resume-hint annotations.
"""

from __future__ import annotations

from typing import Any

from ..core.models import ProviderConfig
from .coaching_patches import _compatibility_intake_is_tool_free
from .prompts import normalize_answer_policy
from .provider.redaction import _compact_text


def _denied_auto_mint_tool_names(extra: dict[str, Any]) -> list[str]:
    from .tools import PROJECT_WRITE_TOOL_NAMES

    denied: list[str] = []
    pressure_blocks = extra.get("pressure_blocks_live_object_mint") is True
    streak_blocks = extra.get("streak_blocks_live_object_mint") is True
    # Learning OS: never silently write learner project / business code.
    denied.extend(sorted(PROJECT_WRITE_TOOL_NAMES))
    # Composer chat never mints cards (even explicit "create a practice card").
    # Intentional mint is POST /training/generate-card only.
    denied.append("generate_training_card")
    if extra.get("completed_training_return_feedback") is True:
        denied.append("verify_practice_current_file")
    if extra.get("formal_plan_mutation") is not True:
        denied.append("save_formal_plan")
    if extra.get("explicit_learning_note_request") is not True:
        denied.append("record_learning_note")
    if extra.get("explicit_resource_import") is not True:
        denied.append("import_resource_url")
    if extra.get("explicit_resource_organize") is not True:
        denied.append("organize_resources")
    # Same live-plan identity as HTTP /task/next and /task/specify.
    if (
        pressure_blocks
        or streak_blocks
        or extra.get("live_formal_plan_for_task_mint") is not True
        or extra.get("closed_loop_return_blocks_task_mint") is True
    ):
        denied.append("specify_task")
        denied.append("next_task")
    return denied


def _stamp_explicit_write_tool_flags(
    extra: dict[str, Any],
    *,
    coach_context: dict[str, Any] | None,
    learner_message: str | None,
) -> None:
    from ..memory.note_request import message_requests_explicit_learning_note
    from .tools import resource_write_explicitly_requested

    extra["explicit_learning_note_request"] = (
        isinstance(coach_context, dict)
        and coach_context.get("explicit_learning_note_request") is True
    ) or message_requests_explicit_learning_note(learner_message)
    extra["explicit_resource_import"] = (
        isinstance(coach_context, dict)
        and coach_context.get("explicit_resource_import") is True
    ) or resource_write_explicitly_requested(extra, mode="download")
    extra["explicit_resource_organize"] = (
        isinstance(coach_context, dict)
        and coach_context.get("explicit_resource_organize") is True
    ) or resource_write_explicitly_requested(extra, mode="organize")
    if (
        extra.get("library_sandbox_work") is True
        or str(extra.get("active_view") or "").strip().lower() == "resources"
        or extra.get("resource_composer_intent")
        or (isinstance(coach_context, dict) and coach_context.get("library_sandbox_work") is True)
    ):
        extra["library_sandbox_work"] = True
        extra["explicit_resource_organize"] = True
        extra["explicit_resource_import"] = True
    extra["denied_tool_names"] = _denied_auto_mint_tool_names(extra)


def _build_agent_tool_context_extra(
    *,
    coach_context: dict[str, Any] | None,
    attachment_delivery: dict[str, Any],
    answer_mode: str | None,
    current_file: dict[str, object] | None,
    provider_config: ProviderConfig | None = None,
    learner_message: str | None = None,
) -> dict[str, Any]:
    from ..training.card_request import message_requests_explicit_training_card

    normalized_answer_mode = normalize_answer_policy(answer_mode)
    extra: dict[str, Any] = {
        "attachments_will_send": bool(attachment_delivery.get("attachments_delivered_to_model")),
        "answer_mode": normalized_answer_mode,
        "allow_coach_only_tools": normalized_answer_mode in {"guided", "balanced"},
    }
    if provider_config is not None:
        window = getattr(provider_config, "context_window_tokens", None)
        try:
            if window is not None:
                extra["context_window_tokens"] = int(window)
        except (TypeError, ValueError):
            pass
    resolved_learner_message = learner_message
    if not isinstance(coach_context, dict):
        if isinstance(current_file, dict):
            extra["current_file"] = dict(current_file)
        extra["explicit_training_card_request"] = message_requests_explicit_training_card(
            resolved_learner_message
        )
        _stamp_explicit_write_tool_flags(
            extra,
            coach_context=None,
            learner_message=resolved_learner_message,
        )
        if isinstance(resolved_learner_message, str) and resolved_learner_message.strip():
            extra["learner_message"] = resolved_learner_message
        return extra

    if isinstance(current_file, dict):
        extra["current_file"] = dict(current_file)

    explicit_tool_scope = coach_context.get("allow_coach_only_tools")
    if isinstance(explicit_tool_scope, bool):
        extra["allow_coach_only_tools"] = explicit_tool_scope

    def _add_if_present(key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        extra[key] = value

    for key in (
        "scenario",
        "active_view",
        "library_sandbox_work",
        "workspace_file_snapshot",
        "resource_composer_intent",
        "learner_signal",
        "current_focus",
        "summary",
        "continuity_summary",
        "review_queue_summary",
        "next_step_hint",
        "pace_signal",
        "first_turn_priority",
        "formal_plan_mutation",
        "completed_training_return_feedback",
        # Local-only cooperative cancellation signal for active SSE turns.
        "stream_cancel_event",
    ):
        _add_if_present(key, coach_context.get(key))

    if coach_context.get("formal_plan_mutation") is True:
        extra["formal_plan_mutation"] = True
        # Formal plan turns are an explicit, governed write lane. They must be
        # able to call the commit tool even when the learner's default answer
        # policy is guided and would otherwise hide coach-only writes.
        extra["allow_coach_only_tools"] = True

    if coach_context.get("pressure_blocks_live_object_mint") is True:
        extra["pressure_blocks_live_object_mint"] = True
    if coach_context.get("streak_blocks_live_object_mint") is True:
        extra["streak_blocks_live_object_mint"] = True
    if coach_context.get("closed_loop_return_blocks_task_mint") is True:
        extra["closed_loop_return_blocks_task_mint"] = True
    if coach_context.get("live_formal_plan_for_task_mint") is True:
        extra["live_formal_plan_for_task_mint"] = True

    # Host/user attestation only — never trust model tool-arg self-attestation.
    if coach_context.get("resource_organization_confirmed") is True:
        extra["resource_organization_confirmed"] = True

    if not isinstance(resolved_learner_message, str) or not resolved_learner_message.strip():
        context_message = coach_context.get("learner_message")
        if isinstance(context_message, str) and context_message.strip():
            resolved_learner_message = context_message
    extra["explicit_training_card_request"] = (
        coach_context.get("explicit_training_card_request") is True
        or message_requests_explicit_training_card(resolved_learner_message)
    )
    _stamp_explicit_write_tool_flags(
        extra,
        coach_context=coach_context,
        learner_message=resolved_learner_message,
    )
    if isinstance(resolved_learner_message, str) and resolved_learner_message.strip():
        extra["learner_message"] = resolved_learner_message

    thread_summary = _compact_text(coach_context.get("thread_summary"), 140)
    thread_next_step = _compact_text(coach_context.get("thread_next_step"), 110)
    resume_hint = _compact_text(coach_context.get("resume_hint"), 160)
    active_thread = coach_context.get("active_thread")
    if isinstance(active_thread, dict):
        if not thread_summary:
            thread_summary = _compact_text(active_thread.get("summary"), 140) or _compact_text(active_thread.get("focus_area"), 140)
        if not thread_next_step:
            thread_next_step = _compact_text(active_thread.get("next_step"), 110)
    if not resume_hint:
        resume_hint_parts: list[str] = []
        if thread_summary:
            resume_hint_parts.append(f"Resume the live thread around {thread_summary}.")
        if thread_next_step:
            resume_hint_parts.append(f"Keep the next move as {thread_next_step}.")
        if isinstance(active_thread, dict):
            blocker = _compact_text(active_thread.get("blocker"), 96)
            verified_result = _compact_text(active_thread.get("verified_result"), 96)
            if blocker:
                resume_hint_parts.append(f"Keep the blocker in view: {blocker}.")
            if verified_result:
                resume_hint_parts.append(f"Build on the verified result: {verified_result}.")
        resume_hint = " ".join(resume_hint_parts).strip()
    _add_if_present("thread_summary", thread_summary)
    _add_if_present("thread_next_step", thread_next_step)
    _add_if_present("resume_hint", resume_hint)

    implementation_guide = coach_context.get("implementation_guide")
    if isinstance(implementation_guide, dict):
        for key in ("current_step", "scope_boundary", "validation_strategy"):
            _add_if_present(f"implementation_{key}", implementation_guide.get(key))

    exercise_prompt = coach_context.get("exercise_prompt")
    if isinstance(exercise_prompt, dict):
        for key in ("prompt", "success_signal", "fallback_step"):
            _add_if_present(f"exercise_{key}", exercise_prompt.get(key))

    active_thread = coach_context.get("active_thread")
    if isinstance(active_thread, dict):
        for key in ("focus_area", "verified_result", "blocker", "next_step"):
            _add_if_present(f"thread_{key}", active_thread.get(key))

    if _compatibility_intake_is_tool_free(
        provider_config=provider_config,
        coach_context=coach_context,
        attachment_delivery=attachment_delivery,
        current_file=current_file,
    ):
        extra["allowed_tool_names"] = []

    return extra
