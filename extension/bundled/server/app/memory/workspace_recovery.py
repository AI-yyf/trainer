"""Fail-closed workspace recovery for plan, provider last-test, and streams.

These records live on structured workspace memory — the same DB path as
training reliability, coach orientation, and transfer state. Incomplete
records are never treated as success. API keys are never stored.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .transfer_skills import describe_transfer_skill_state, normalize_transfer_skill_state_record

PLAN_RUNTIME_KEY = "latest_plan_runtime"
PROVIDER_CAPABILITY_KEY = "latest_provider_capability"
STREAMING_CHECKPOINT_KEY = "latest_streaming_checkpoint"
CURRENT_TASK_KEY = "latest_current_task"
AFFECT_STATE_KEY = "latest_affect_state"
TONE_DECISION_KEY = "latest_tone_decision"
COACHING_FOCUS_KEY = "latest_coaching_focus"
COACH_FOCUS_KEY = "latest_coach_focus"
COACH_TURN_KEY = "latest_coach_turn"
NEXT_STEP_HINT_KEY = "latest_next_step_hint"
COACHING_ADAPTATION_KEY = "latest_coaching_adaptation"
EVALUATION_KEY = "latest_evaluation"
LEARNER_STATE_KEY = "latest_learner_state"
TEACHING_DECISION_KEY = "latest_teaching_decision"
ADAPTATION_GUIDE_KEY = "latest_adaptation_guide"
PROJECT_SOURCES_KEY = "latest_project_sources"
PRINCIPLE_NOTES_KEY = "latest_principle_notes"
TRAINING_CHROME_KEY = "latest_training_chrome"

STREAMING_PHASES = frozenset({"streaming", "interrupted", "completed", "cancelled"})
SECRET_KEYS = frozenset({"apikey", "api_key", "api-key", "secret", "token", "authorization", "password"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _revision(value: Any, fallback: int = 1) -> int:
    return int(value) if isinstance(value, int) and value > 0 else fallback


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def strip_secrets(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key.casefold() not in SECRET_KEYS}


def normalize_plan_runtime_recovery(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    plan_id = _text(value.get("plan_id") or value.get("planId"))
    current_stage_id = _text(value.get("current_stage_id") or value.get("currentStageId"))
    current_step = _text(value.get("current_step") or value.get("currentStep"))
    blocked_reason = _text(value.get("blocked_reason") or value.get("blockedReason"))
    resume_state = _text(value.get("resume_state") or value.get("resumeState")).replace("-", "_")
    if resume_state not in {"interrupted", "in_progress", "waiting"}:
        resume_state = "interrupted"
    workspace_id = _text(value.get("workspace_id") or value.get("workspaceId"))
    recovered_without_step = resume_state in {"in_progress", "waiting"} and bool(workspace_id)
    if not plan_id and not current_stage_id and not current_step and not blocked_reason:
        if not recovered_without_step:
            return None
    verify_raw = value.get("verify_method") or value.get("verifyMethod") or []
    next_verify_raw = value.get("next_verify_method") or value.get("nextVerifyMethod") or []
    return {
        "revision": _revision(value.get("revision")),
        "workspace_id": _text(value.get("workspace_id") or value.get("workspaceId")) or None,
        "request_id": _text(value.get("request_id") or value.get("requestId")) or None,
        "plan_id": plan_id or None,
        "selected_card_id": _text(value.get("selected_card_id") or value.get("selectedCardId"))
        or None,
        "current_stage_id": current_stage_id or None,
        "current_step": current_step or None,
        "frozen": value.get("frozen") is True,
        "blocked_reason": blocked_reason or None,
        "why_now": _text(value.get("why_now") or value.get("whyNow")) or None,
        "verify_method": [item for item in verify_raw if str(item).strip()] if isinstance(verify_raw, list) else [],
        "next_after_current": _text(value.get("next_after_current") or value.get("nextAfterCurrent")) or None,
        "next_why_now": _text(
            value.get("next_why_now")
            or value.get("nextWhyNow")
            or value.get("why_after_current")
            or value.get("whyAfterCurrent")
        )
        or None,
        "next_blocked_reason": _text(
            value.get("next_blocked_reason")
            or value.get("nextBlockedReason")
            or value.get("blocked_after_current")
            or value.get("blockedAfterCurrent")
        )
        or None,
        "next_verify_method": [item for item in next_verify_raw if str(item).strip()]
        if isinstance(next_verify_raw, list)
        else [],
        "evidence_binding": _text(value.get("evidence_binding") or value.get("evidenceBinding")) or None,
        "resume_state": resume_state,
        "updated_at": _text(value.get("updated_at") or value.get("updatedAt")) or None,
        **_verify_plan_advance_payload(value),
    }


def _verify_plan_advance_payload(value: dict[str, Any]) -> dict[str, Any]:
    advance = value.get("verify_plan_advance") or value.get("verifyPlanAdvance")
    if not isinstance(advance, dict) or not advance:
        return {}
    return {
        "verify_plan_advance": {
            "advanced": bool(advance.get("advanced")),
            "what": _text(advance.get("what")),
            "why": _text(advance.get("why")),
            "next": _text(advance.get("next")),
            "plan_id": _text(advance.get("plan_id") or advance.get("planId")) or None,
        }
    }


def live_evidence_binding(
    *,
    binding: str = "",
    pending_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    recovered: bool = False,
    current_step: str = "",
) -> str:
    """Binding is current only when it names a live pending item for the step."""

    binding_id = _text(binding)
    if not binding_id:
        return ""
    pending = {_text(item_id) for item_id in (pending_ids or []) if _text(item_id)}
    if binding_id not in pending:
        return ""
    if recovered and not _text(current_step):
        return ""
    return binding_id


def _recovered_overlay_empty_step(
    runtime: dict[str, Any] | None,
    existing: dict[str, Any] | None,
    current_step: str = "",
) -> bool:
    """Recovered overlay with no live current_step is leftover-not-live."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    step = (
        _text(current_step)
        or _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    return bool(runtime or existing) and not step


def formal_plan_is_live_runtime_identity(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Leftover formal plan is live only when recovered runtime still carries its id."""

    if plan is None:
        return False
    formal = _text(getattr(plan, "id", "") or getattr(plan, "plan_id", ""))
    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    runtime_step = (
        _text(current_step)
        or _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    plan_step = _text(getattr(plan, "current_step", "") if plan is not None else "")
    carried = _text(runtime.get("plan_id") or existing.get("plan_id"))
    recovered = bool(runtime or existing)
    if not formal:
        return False
    if not recovered:
        return True
    if _recovered_overlay_empty_step(runtime, existing, runtime_step):
        return False
    if not runtime_step:
        return False
    if plan_step and runtime_step != plan_step:
        return False
    return carried == formal


def formal_task_is_live_runtime_identity(
    *,
    recovered: bool = False,
    runtime_current_step: str = "",
    task_title: str = "",
) -> bool:
    """Leftover formal task is live only when recovered runtime still names it."""

    runtime_step = _text(runtime_current_step)
    title = _text(task_title)
    if not recovered:
        return bool(title)
    if not runtime_step:
        return False
    return bool(title) and runtime_step == title


def formal_card_is_live_runtime_identity(
    *,
    card: Any | None = None,
    card_id: str = "",
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    selected_card_id: str = "",
) -> bool:
    """Leftover stored card is live only when recovered runtime still carries its id.

    Title / current_step text match must never count as live selectedCardId.
    Missing or mismatched runtime card id stays leftover-not-live.
    """

    formal = _text(card_id) or _text(
        getattr(card, "card_id", "") if card is not None else ""
    )
    if not formal:
        return False
    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    carried = (
        _text(selected_card_id)
        or _text(runtime.get("selected_card_id") or runtime.get("selectedCardId"))
        or _text(existing.get("selected_card_id") or existing.get("selectedCardId"))
    )
    if not carried:
        return False
    return carried == formal


def leftover_task_guide_focus_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Leftover task/guide/focus titles are not live when recovered current_step is empty."""

    return _recovered_overlay_empty_step(runtime, existing, current_step)


def prefer_recovered_coach_task_chrome(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    task_title: str = "",
    idea_summary: str = "",
    scope_boundary: str = "",
    guide_current_step: str = "",
    teaching_goal: str = "",
    success_signal: str = "",
    fallback_step: str = "",
    current_focus: str = "",
    active_task: str = "",
    next_step: str = "",
    active_stage: str = "",
) -> dict[str, str]:
    """Omit leftover task/guide/focus titles when recovered overlay is leftover-not-live."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(current_step)
        or _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)

    def omit_leftover(value: str) -> str:
        candidate = _text(value)
        if not candidate:
            return ""
        if recovered and not recovered_step:
            return ""
        if recovered and candidate != recovered_step:
            return ""
        return candidate

    if leftover_task_guide_focus_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    ):
        return {"live_task_title": ""}
    live_task = formal_task_is_live_runtime_identity(
        recovered=recovered,
        runtime_current_step=recovered_step,
        task_title=task_title,
    )
    return {
        "live_task_title": _text(task_title) if live_task else "",
        "idea_summary": omit_leftover(idea_summary),
        "scope_boundary": omit_leftover(scope_boundary),
        "current_step": omit_leftover(guide_current_step),
        "teaching_goal": omit_leftover(teaching_goal),
        "success_signal": omit_leftover(success_signal),
        "fallback_step": omit_leftover(fallback_step),
        "current_focus": omit_leftover(current_focus),
        "active_task": omit_leftover(active_task),
        "next_step": omit_leftover(next_step),
        "active_stage": omit_leftover(active_stage),
    }


def leftover_coach_turn_chrome_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Leftover coach-turn / review / artifact identity titles are not live when recovered current_step is empty."""

    return leftover_task_guide_focus_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    )


def leftover_coach_conversation_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Leftover Coach conversation is not live when recovered current_step is empty."""

    return leftover_coach_turn_chrome_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    )


def leftover_suggested_actions_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Leftover suggestedActions are not live Coach first-screen identity when recovered current_step is empty.

    Independent recovered runtime with a current_step is leftover-not-live for
    minting chips even when this returns False. Use leftover_minting_suggested_actions_are_not_live
    plus honest_suggested_actions_without_live_object on hydrate/session-start.
    """

    return leftover_coach_conversation_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    )


def leftover_minting_suggested_actions_are_not_live(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
) -> bool:
    """plan/task/next_task chips are not live when leftover stored is not a live plan or task."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    if not runtime and not existing:
        return False
    live_plan = leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=runtime,
        existing=existing,
    )
    recovered_step = _text(runtime.get("current_step")) or _text(existing.get("current_step"))
    live_task = formal_task_is_live_runtime_identity(
        recovered=True,
        runtime_current_step=recovered_step,
        task_title=task_title,
    )
    return not live_plan and not live_task


def leftover_first_look_headline_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Leftover first-look headline is not live Coach empty-state identity when recovered current_step is empty."""

    return leftover_coach_conversation_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    )


def leftover_evaluation_headline_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Leftover evaluation headline is not live Coach empty-state identity when recovered current_step is empty."""

    return leftover_coach_conversation_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    )


def leftover_streaming_checkpoint_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Leftover streaming checkpoint is not live Coach identity when recovered current_step is empty."""

    return leftover_coach_conversation_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    )


def leftover_transfer_skill_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Leftover transfer skill is not live Coach/Training/Plan identity when recovered current_step is empty."""

    return leftover_streaming_checkpoint_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    )


def leftover_transfer_skill_has_real_multi_scene_proof(transfer: dict[str, Any] | None) -> bool:
    """Real multi-scene transfer needs two distinct workspace ids. Same leftover object does not count."""

    record = normalize_transfer_skill_state_record(transfer)
    if not record:
        return False
    workspace_ids = list(
        dict.fromkeys(_text(item).casefold() for item in record.get("workspace_ids") or [] if _text(item))
    )
    return int(record.get("scene_count") or 0) >= 2 and len(workspace_ids) >= 2


def prefer_recovered_transfer_skill(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    transfer: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Keep awaiting_second_scene for one leftover A scene. Do not invent a second scene."""

    record = normalize_transfer_skill_state_record(transfer)
    if not record:
        return None
    if not leftover_transfer_skill_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    ):
        return record
    if leftover_transfer_skill_has_real_multi_scene_proof(record):
        return record
    if record.get("state") != "transferable":
        return record
    copy = describe_transfer_skill_state("awaiting_second_scene", str(record.get("concept") or ""))
    return {
        **record,
        "state": "awaiting_second_scene",
        "scene_count": max(1, min(int(record.get("scene_count") or 0), 1)),
        "why": copy["why"],
        "next": copy["next"],
    }


def prefer_recovered_coach_turn_chrome(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    coach_turn_next_step: str = "",
    coach_turn_summary: str = "",
    coach_turn_teaching_goal: str = "",
    coach_turn_encouragement: str = "",
    coach_turn_active_stage: str = "",
    coaching_state_next_step: str = "",
    coaching_state_summary: str = "",
    coaching_state_teaching_goal: str = "",
    coaching_state_encouragement: str = "",
    evaluation_next_step: str = "",
    next_step_hint_title: str = "",
    next_step_hint_summary: str = "",
    resume_thread: str = "",
    support_strategy: str = "",
    review_queue_summary: str = "",
    artifact_teaser: str = "",
    artifact_rationale: str = "",
    continuity_summary: str = "",
    coach_judgment_summary: str = "",
    coach_judgment_teaching_goal: str = "",
) -> dict[str, str]:
    """Omit leftover coach-turn / review / judgment / continuity titles when leftover-not-live."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(current_step)
        or _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)

    def omit_leftover(value: str) -> str:
        candidate = _text(value)
        if not candidate:
            return ""
        if recovered and not recovered_step:
            return ""
        if recovered and candidate != recovered_step:
            return ""
        return candidate

    if leftover_coach_turn_chrome_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    ):
        return {}
    return {
        "coach_turn_next_step": omit_leftover(coach_turn_next_step),
        "coach_turn_summary": omit_leftover(coach_turn_summary),
        "coach_turn_teaching_goal": omit_leftover(coach_turn_teaching_goal),
        "coach_turn_encouragement": omit_leftover(coach_turn_encouragement),
        "coach_turn_active_stage": omit_leftover(coach_turn_active_stage),
        "coaching_state_next_step": omit_leftover(coaching_state_next_step),
        "coaching_state_summary": omit_leftover(coaching_state_summary),
        "coaching_state_teaching_goal": omit_leftover(coaching_state_teaching_goal),
        "coaching_state_encouragement": omit_leftover(coaching_state_encouragement),
        "evaluation_next_step": omit_leftover(evaluation_next_step),
        "next_step_hint_title": omit_leftover(next_step_hint_title),
        "next_step_hint_summary": omit_leftover(next_step_hint_summary),
        "resume_thread": omit_leftover(resume_thread),
        "support_strategy": omit_leftover(support_strategy),
        "review_queue_summary": omit_leftover(review_queue_summary),
        "artifact_teaser": omit_leftover(artifact_teaser),
        "artifact_rationale": omit_leftover(artifact_rationale),
        "continuity_summary": omit_leftover(continuity_summary),
        "coach_judgment_summary": omit_leftover(coach_judgment_summary),
        "coach_judgment_teaching_goal": omit_leftover(coach_judgment_teaching_goal),
    }


def leftover_training_focus_chrome_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    plan: Any | None = None,
) -> bool:
    """Leftover Training/Practice focus titles are not live when leftover plan is not live."""

    return leftover_training_handoff_chrome_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
        plan=plan,
    )


def prefer_recovered_training_focus_chrome(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    plan: Any | None = None,
    teaching_decision_focus_area: str = "",
    learner_state_active_focus: str = "",
    latest_learning_focus_area: str = "",
    card_focus_area: str = "",
    task_focus_override: str = "",
) -> dict[str, str]:
    """Omit leftover teachingDecision.focusArea / learnerState.activeFocus when leftover-not-live."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(current_step)
        or _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)

    def omit_leftover(value: str) -> str:
        candidate = _text(value)
        if not candidate:
            return ""
        if recovered and not recovered_step:
            return ""
        if recovered and candidate != recovered_step:
            return ""
        return candidate

    if leftover_training_focus_chrome_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
        plan=plan,
    ):
        return {}
    return {
        "teaching_decision_focus_area": omit_leftover(teaching_decision_focus_area),
        "learner_state_active_focus": omit_leftover(learner_state_active_focus),
        "latest_learning_focus_area": omit_leftover(latest_learning_focus_area),
        "card_focus_area": omit_leftover(card_focus_area),
        "task_focus_override": omit_leftover(task_focus_override),
    }


def leftover_training_handoff_chrome_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    plan: Any | None = None,
) -> bool:
    """Leftover Training handoff/card chrome is not live when leftover plan is not live.

    Empty recovered current_step stays leftover-not-live. Recovered-without-plan
    (stored leftover, runtime plan_id empty) also stays leftover-not-live so
    leftover card chrome cannot dump as the live Training object.
    """

    if leftover_task_guide_focus_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    ):
        return True
    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    if not runtime and not existing:
        return False
    return not leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=runtime,
        existing=existing,
    )


def leftover_bound_plan_competing_identity_labels(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    card_titles: list[str] | tuple[str, ...] | None = None,
    leftover_plans: list[Any] | tuple[Any, ...] | None = None,
) -> set[str]:
    """Stored leftover titles must not paint as live Resources/Training identity.

    After a NEW live plan is bound, leftover titles compete with that live identity.
    When leftover is stored but not live (recovered-without-plan), leftover titles
    still compete so they cannot dump as the current library/card chrome.
    """

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    if not runtime and not existing:
        return set()
    recovered_step = _text(runtime.get("current_step")) or _text(existing.get("current_step"))
    live_plan = leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=runtime,
        existing=existing,
    )
    live_id = _text(
        runtime.get("plan_id")
        or runtime.get("planId")
        or existing.get("plan_id")
        or existing.get("planId")
        or (
            (getattr(plan, "id", "") or getattr(plan, "plan_id", ""))
            if live_plan
            else ""
        )
    )
    live_title = _text(getattr(plan, "title", "") if plan is not None and live_plan else "")
    labels: set[str] = set()

    def add(value: Any) -> None:
        text = _text(value)
        if text and text != recovered_step and text != live_title:
            labels.add(text)

    if not live_plan:
        if plan is not None:
            add(getattr(plan, "title", ""))
            add(getattr(plan, "current_step", ""))
            add(getattr(plan, "why_now", ""))
        for leftover in leftover_plans or []:
            add(getattr(leftover, "title", ""))
            add(getattr(leftover, "current_step", ""))
            add(getattr(leftover, "why_now", ""))
        for title in card_titles or []:
            add(title)
        return labels

    if not live_id:
        return set()
    for title in card_titles or []:
        add(title)
    for leftover in leftover_plans or []:
        leftover_id = _text(getattr(leftover, "id", "") or getattr(leftover, "plan_id", ""))
        if leftover_id and leftover_id == live_id:
            continue
        add(getattr(leftover, "title", ""))
        add(getattr(leftover, "current_step", ""))
        add(getattr(leftover, "why_now", ""))
    return labels


def bound_plan_leftover_training_live_identity_updates(
    *,
    workspace_id: str,
    generated_step: str,
    workspace: dict[str, Any] | None,
    competing_labels: set[str] | None = None,
) -> dict[str, Any]:
    """Clear leftover Training live identity when explicit generate binds a new plan."""

    generated = _text(generated_step)
    record = workspace if isinstance(workspace, dict) else {}
    handoff = record.get("latest_training_handoff")
    if not isinstance(handoff, dict):
        handoff = record.get("latestTrainingHandoff")
    handoff = handoff if isinstance(handoff, dict) else {}
    selected_title = _text(
        record.get("selected_card_title") or record.get("selectedCardTitle")
    )
    handoff_title = _text(handoff.get("card_title") or handoff.get("cardTitle"))
    next_hop = record.get("latest_training_next_hop")
    if not isinstance(next_hop, dict):
        next_hop = record.get("latestTrainingNextHop")
    next_hop = next_hop if isinstance(next_hop, dict) else {}
    next_hop_title = _text(next_hop.get("title") or next_hop.get("card_title") or next_hop.get("cardTitle"))
    leftover_title = handoff_title or selected_title or next_hop_title
    labels = {item for item in (competing_labels or set()) if _text(item)}
    if leftover_title and leftover_title != generated:
        labels.add(leftover_title)
    if not labels:
        return {}
    updates: dict[str, Any] = {}
    if leftover_title and leftover_title != generated:
        updates["selected_card_title"] = ""
        updates[TRAINING_CHROME_KEY] = stamp_workspace_scope(
            {"selected_card_title": ""},
            workspace_id,
        )
        updates["latest_training_learning_phase"] = ""
        if handoff:
            cleaned = dict(handoff)
            cleaned["card_title"] = ""
            cleaned.pop("cardTitle", None)
            cleaned["learning_phase"] = ""
            updates["latest_training_handoff"] = stamp_workspace_scope(cleaned, workspace_id)
    next_hop = record.get("latest_training_next_hop")
    if not isinstance(next_hop, dict):
        next_hop = record.get("latestTrainingNextHop")
    if isinstance(next_hop, dict):
        hop_title = _text(next_hop.get("title") or next_hop.get("card_title") or next_hop.get("cardTitle"))
        if hop_title and hop_title != generated:
            hop = dict(next_hop)
            hop["title"] = ""
            hop["card_title"] = ""
            hop.pop("cardTitle", None)
            updates["latest_training_next_hop"] = stamp_workspace_scope(hop, workspace_id)
    routing = record.get("active_training_card_routing")
    if not isinstance(routing, dict):
        routing = record.get("activeTrainingCardRouting")
    if isinstance(routing, dict):
        why = _text(routing.get("why_this_card") or routing.get("whyThisCard"))
        if leftover_title and leftover_title in why:
            cleaned_routing = dict(routing)
            cleaned_routing["why_this_card"] = ""
            cleaned_routing.pop("whyThisCard", None)
            updates["active_training_card_routing"] = stamp_workspace_scope(
                cleaned_routing,
                workspace_id,
            )
    sandbox = record.get("sandbox_preview")
    if not isinstance(sandbox, dict):
        sandbox = record.get("sandboxPreview")
    if isinstance(sandbox, dict) and _text(sandbox.get("title")) in labels:
        updates["sandbox_preview"] = {}
    if _text(record.get("onboarding_request") or record.get("onboardingRequest")) in labels:
        updates["onboarding_request"] = ""
    if _text(record.get("project_context") or record.get("projectContext")) in labels:
        updates["project_context"] = ""
    return updates


def prefer_recovered_training_handoff_chrome(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    plan: Any | None = None,
    success_signal: str = "",
    return_with: str = "",
    card_title: str = "",
    selected_card_title: str = "",
    followup: str = "",
    blocker: str = "",
    handoff_summary: str = "",
    next_after_completion: str = "",
    fallback_action: str = "",
    next_hop_title: str = "",
    next_hop_card_title: str = "",
    next_hop_handoff_summary: str = "",
    next_hop_next_after_completion: str = "",
    next_hop_fallback_action: str = "",
    routing_next_after_completion: str = "",
    routing_fallback_action: str = "",
    why_this_card: str = "",
    ledger_why_this_card: str = "",
    return_summary: str = "",
    next_hop_return_summary: str = "",
    next_hop_summary: str = "",
    next_hop_why_now: str = "",
) -> dict[str, str]:
    """Omit leftover handoff identity titles when leftover-not-live."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(current_step)
        or _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)

    def omit_leftover(value: str) -> str:
        candidate = _text(value)
        if not candidate:
            return ""
        if recovered and not recovered_step:
            return ""
        if recovered and candidate != recovered_step:
            return ""
        return candidate

    if leftover_training_handoff_chrome_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
        plan=plan,
    ):
        return {}
    return {
        "success_signal": omit_leftover(success_signal),
        "return_with": omit_leftover(return_with),
        "card_title": omit_leftover(card_title),
        "selected_card_title": omit_leftover(selected_card_title),
        "followup": omit_leftover(followup),
        "blocker": omit_leftover(blocker),
        "handoff_summary": omit_leftover(handoff_summary),
        "next_after_completion": omit_leftover(next_after_completion),
        "fallback_action": omit_leftover(fallback_action),
        "next_hop_title": omit_leftover(next_hop_title),
        "next_hop_card_title": omit_leftover(next_hop_card_title),
        "next_hop_handoff_summary": omit_leftover(next_hop_handoff_summary),
        "next_hop_next_after_completion": omit_leftover(next_hop_next_after_completion),
        "next_hop_fallback_action": omit_leftover(next_hop_fallback_action),
        "routing_next_after_completion": omit_leftover(routing_next_after_completion),
        "routing_fallback_action": omit_leftover(routing_fallback_action),
        "why_this_card": omit_leftover(why_this_card),
        "ledger_why_this_card": omit_leftover(ledger_why_this_card),
        "return_summary": omit_leftover(return_summary),
        "next_hop_return_summary": omit_leftover(next_hop_return_summary),
        "next_hop_summary": omit_leftover(next_hop_summary),
        "next_hop_why_now": omit_leftover(next_hop_why_now),
    }


def leftover_resource_selected_detail_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    plan: Any | None = None,
) -> bool:
    """Leftover Resources selected-detail is not live Resources identity.

    Empty recovered current_step stays leftover-not-live. Recovered-with-step
    also stays leftover-not-live: a recovered plan step is Plan identity, not
    Resources library identity. Do not dump leftover ResourceRecords named
    after the leftover step as the live library.
    """

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    if leftover_task_guide_focus_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    ):
        return True
    return bool(runtime or existing)


def prefer_recovered_resource_selected_detail(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    plan: Any | None = None,
    title: str = "",
    summary: str = "",
    match_summary: str = "",
) -> dict[str, str]:
    """Omit leftover selected-resource title/preview/detail when leftover-not-live."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(current_step)
        or _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)

    def omit_leftover(value: str) -> str:
        candidate = _text(value)
        if not candidate:
            return ""
        if recovered and not recovered_step:
            return ""
        if recovered and candidate != recovered_step:
            return ""
        return candidate

    if leftover_resource_selected_detail_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
        plan=plan,
    ):
        return {}
    return {
        "title": omit_leftover(title),
        "summary": omit_leftover(summary),
        "match_summary": omit_leftover(match_summary),
    }


def leftover_resource_sandbox_preview_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    plan: Any | None = None,
) -> bool:
    """Leftover Resources sandbox preview is not live Resources identity.

    Recovered overlay (empty or with current_step) stays leftover-not-live.
    A recovered plan step is Plan identity, not sandbox preview identity.
    """

    return leftover_resource_selected_detail_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
        plan=plan,
    )


def leftover_resource_sandbox_state_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    plan: Any | None = None,
) -> bool:
    """Leftover Resources sandboxState is not live Resources identity.

    Recovered overlay (empty or with current_step) stays leftover-not-live.
    """

    return leftover_resource_sandbox_preview_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
        plan=plan,
    )


def leftover_resource_library_list_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    plan: Any | None = None,
) -> bool:
    """Leftover Resources library list is not live Resources identity.

    Recovered overlay (empty or with current_step) stays leftover-not-live.
    """

    return leftover_resource_sandbox_state_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
        plan=plan,
    )


def resource_record_is_acknowledged_upload(item: Any) -> bool:
    """True for /resource/upload records; false for leftover library chrome dumps."""

    if item is None:
        return False
    if isinstance(item, dict):
        source = _text(item.get("source"))
        canonical = _text(item.get("canonical_source") or item.get("canonicalSource"))
        source_type = _text(item.get("source_type") or item.get("sourceType"))
        index_status = _text(item.get("index_status") or item.get("indexStatus")).lower()
        parse_status = _text(item.get("parse_status") or item.get("parseStatus")).lower()
        sandbox_path = _text(item.get("sandbox_path") or item.get("sandboxPath"))
    else:
        source = _text(getattr(item, "source", ""))
        canonical = _text(getattr(item, "canonical_source", ""))
        source_type = _text(getattr(item, "source_type", ""))
        index_status = _text(getattr(item, "index_status", "")).lower()
        parse_status = _text(getattr(item, "parse_status", "")).lower()
        sandbox_path = _text(getattr(item, "sandbox_path", ""))
    if sandbox_path:
        return True
    if index_status in {"indexed", "parsed"}:
        return True
    if parse_status in {"parsed", "indexed"}:
        return True
    if canonical:
        return True
    if source_type:
        return True
    lowered = source.lower()
    return lowered.startswith(
        ("inline://", "http://", "https://", "file://", "workspace://")
    )


def leftover_settings_profile_rhythm_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Leftover Settings profile/rhythm is not live Settings chrome.

    Empty recovered current_step stays leftover-not-live. Recovered-with-step
    also stays leftover-not-live: a recovered plan step is Plan identity, not
    Settings identity. Do not dump leftover rhythm/coachDefaults as live Settings.
    """

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    if leftover_task_guide_focus_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    ):
        return True
    return bool(runtime or existing)


def leftover_settings_learner_project_onboarding_is_not_live(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Leftover Settings learner/project/onboarding is not live Settings chrome.

    Recovered overlay (empty or with current_step) stays leftover-not-live.
    """

    return leftover_settings_profile_rhythm_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    )


def prefer_recovered_settings_profile_rhythm(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    preferred_rhythm: str = "",
    preferred_learning_mode: str = "",
    memory_scope: str = "",
    review_cadence: str = "",
    working_set_mode: str = "",
    review_reminder_mode: str = "",
) -> dict[str, str]:
    """Omit leftover preferredRhythm and coachDefaults cadence/memory scope when leftover-not-live."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(current_step)
        or _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    if leftover_settings_profile_rhythm_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    ):
        return {}
    return {
        "preferred_rhythm": _text(preferred_rhythm),
        "preferred_learning_mode": _text(preferred_learning_mode),
        "memory_scope": _text(memory_scope),
        "review_cadence": _text(review_cadence),
        "working_set_mode": _text(working_set_mode),
        "review_reminder_mode": _text(review_reminder_mode),
    }


def prefer_recovered_settings_learner_project_onboarding(
    *,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    learner_name: str = "",
    target_project: str = "",
    onboarding_request: str = "",
    project_context: str = "",
) -> dict[str, str]:
    """Omit leftover learner/project/onboarding titles when leftover-not-live."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(current_step)
        or _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    if leftover_settings_learner_project_onboarding_is_not_live(
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    ):
        return {}
    return {
        "learner_name": _text(learner_name),
        "target_project": _text(target_project),
        "onboarding_request": _text(onboarding_request),
        "project_context": _text(project_context),
    }


def leftover_formal_training_labels(
    *,
    plan: Any | None = None,
    task_title: str = "",
    task_goal: str = "",
    live_plan: bool = False,
    live_task: bool = False,
) -> set[str]:
    """Formal title/summary/old step that must not mint a recovered card."""

    labels: set[str] = set()
    if plan is not None and not live_plan:
        for value in (
            getattr(plan, "title", ""),
            getattr(plan, "summary", ""),
            getattr(plan, "why_now", ""),
            getattr(plan, "current_step", ""),
            getattr(plan, "next_after_current", ""),
        ):
            text = _text(value)
            if text:
                labels.add(text)
        for stage in getattr(plan, "stages", None) or []:
            stage_title = _text(getattr(stage, "title", ""))
            if stage_title:
                labels.add(stage_title)
    task = _text(task_title)
    if task and not live_task:
        labels.add(task)
    goal = _text(task_goal)
    if goal and not live_plan and not live_task:
        labels.add(goal)
    return labels


def leftover_formal_plan_identity_labels(*, plan: Any | None = None) -> set[str]:
    """Leftover identity is title/summary/current_step/stage, not next_after_current."""

    labels: set[str] = set()
    if plan is None:
        return labels
    for value in (
        getattr(plan, "title", ""),
        getattr(plan, "summary", ""),
        getattr(plan, "current_step", ""),
    ):
        text = _text(value)
        if text:
            labels.add(text)
    for stage in getattr(plan, "stages", None) or []:
        stage_title = _text(getattr(stage, "title", ""))
        if stage_title:
            labels.add(stage_title)
    return labels


def leftover_formal_plan_is_live_for_fill(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
) -> bool:
    """Title/summary fill is live only when recovered runtime still carries leftover plan id."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    if not runtime and not existing:
        return True
    recovered_step = _text(runtime.get("current_step")) or _text(existing.get("current_step"))
    if not recovered_step:
        return False
    return formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )


def leftover_frozen_plan_blocks_generation(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
) -> bool:
    """Frozen leftover blocks generate only when that leftover is still the live identity."""

    if plan is None or not bool(getattr(plan, "frozen", False)):
        return False
    return leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=runtime,
        existing=existing,
    )


def live_plan_blocked_reason(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    blocked_reason: str = "",
) -> str:
    """Orientation blocker uses recovered blocked_reason, not leftover formal."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = _text(runtime.get("current_step")) or _text(existing.get("current_step"))
    recovered_blocked = _text(runtime.get("blocked_reason")) or _text(existing.get("blocked_reason"))
    recovered = bool(runtime or existing)
    leftover = _text(blocked_reason)
    if recovered and not recovered_step:
        return ""
    if leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=runtime,
        existing=existing,
    ):
        return leftover
    return recovered_blocked


def live_plan_overlay_fields(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
) -> dict[str, Any]:
    """Overlay what/why/verify/blocked uses recovered runtime, not leftover formal fields."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = _text(runtime.get("current_step")) or _text(existing.get("current_step"))
    recovered = bool(runtime or existing)
    if recovered and not recovered_step:
        return {
            "current_step": "",
            "why_now": "",
            "verify_method": [],
            "blocked_reason": "",
            "next_after_current": "",
        }
    refresh = live_plan_refresh_step_why(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=_text(getattr(plan, "current_step", "") if plan is not None else ""),
        why_now=_text(getattr(plan, "why_now", "") if plan is not None else ""),
        next_after_current=_text(getattr(plan, "next_after_current", "") if plan is not None else ""),
        task_title=task_title,
    )
    blocked = live_plan_blocked_reason(
        plan=plan,
        runtime=runtime,
        existing=existing,
        blocked_reason=_text(getattr(plan, "blocked_reason", "") if plan is not None else ""),
    )
    live_plan = leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=runtime,
        existing=existing,
    )
    if live_plan:
        verify_raw = getattr(plan, "verify_method", None) if plan is not None else []
    else:
        verify_raw = runtime.get("verify_method") or existing.get("verify_method") or []
    verify_method = (
        [str(item).strip() for item in verify_raw if str(item).strip()]
        if isinstance(verify_raw, list)
        else []
    )
    return {
        "current_step": refresh["current_step"],
        "why_now": refresh["why_now"],
        "verify_method": verify_method,
        "blocked_reason": blocked,
        "next_after_current": refresh["next_after_current"],
    }


def live_plan_current_step_fill(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    stage_goal: str = "",
    phase_objective: str = "",
    summary: str = "",
    objective: str = "",
    title: str = "",
) -> str:
    """Empty current_step stays empty when leftover plan is not live identity."""

    step = _text(current_step)
    if step:
        return step
    live_plan = leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=runtime,
        existing=existing,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        live_plan=live_plan,
        live_task=True,
    )
    if not live_plan:
        return ""
    for candidate in (stage_goal, phase_objective):
        text = _text(candidate)
        if text and text not in leftover:
            return text
    return _text(summary) or _text(objective) or _text(title)


def live_plan_next_after_current(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    next_after_current: str = "",
    next_stage_goal: str = "",
    next_phase_objective: str = "",
) -> str:
    """Leftover stage goals do not land in next_after_current after leftover-not-live."""

    live_plan = leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=runtime,
        existing=existing,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        live_plan=live_plan,
        live_task=True,
    )
    if plan is not None and not live_plan:
        for stage in getattr(plan, "stages", None) or []:
            goal = _text(getattr(stage, "goal", ""))
            if goal:
                leftover.add(goal)
    nxt = _text(next_after_current)
    generic = "Review the result and decide whether to widen scope."
    if live_plan:
        return nxt or _text(next_stage_goal) or _text(next_phase_objective) or generic
    if nxt and nxt not in leftover:
        return nxt
    for candidate in (next_stage_goal, next_phase_objective):
        text = _text(candidate)
        if text and text not in leftover:
            return text
    return generic


def live_training_mint_anchors(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
    why_now: str = "",
    target_skill: str = "",
    focus_area: str = "",
) -> dict[str, str]:
    """Mint why/skill/focus from recovered truth, not leftover formal title."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered_why = _text(runtime.get("why_now")) or _text(existing.get("why_now"))
    recovered = bool(runtime or existing)
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    live_task = formal_task_is_live_runtime_identity(
        recovered=recovered,
        runtime_current_step=recovered_step,
        task_title=task_title,
    )
    why = _text(why_now)
    skill = _text(target_skill)
    focus = _text(focus_area)
    if live_plan or live_task:
        return {"why_now": why, "target_skill": skill, "focus_area": focus}
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=task_title,
        live_plan=live_plan,
        live_task=live_task,
    )
    if why in leftover:
        why = recovered_why
    if skill in leftover:
        skill = ""
    if focus in leftover:
        focus = recovered_step
    return {"why_now": why, "target_skill": skill, "focus_area": focus}


def _formal_plan_candidate_focus(plan: Any | None) -> str:
    if plan is None:
        return ""
    stages = list(getattr(plan, "stages", None) or [])
    current_stage_id = _text(getattr(plan, "current_stage_id", ""))
    active_stage = next(
        (
            stage
            for stage in stages
            if _text(getattr(stage, "id", "")) == current_stage_id
            or _text(getattr(stage, "status", "")) == "active"
        ),
        stages[0] if stages else None,
    )
    if active_stage is not None:
        return _text(getattr(active_stage, "title", ""))
    return _text(getattr(plan, "title", ""))


def live_coach_focus_area(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    evaluation: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    candidate: str = "",
) -> str:
    """Coach focus uses recovered current_step, not leftover formal title."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)
    if recovered and not recovered_step:
        return ""
    task_title = _text(getattr(task, "title", "") if task is not None else "")
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    live_task = formal_task_is_live_runtime_identity(
        recovered=recovered,
        runtime_current_step=recovered_step,
        task_title=task_title,
    )
    focus = _text(candidate)
    if not focus:
        evaluation_focus = _text(
            getattr(evaluation, "task_spec_id", "") if evaluation is not None else ""
        )
        if evaluation_focus:
            focus = evaluation_focus
        elif task_title:
            focus = task_title
        else:
            focus = _formal_plan_candidate_focus(plan)
    if live_plan or live_task:
        return focus
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=task_title,
        live_plan=live_plan,
        live_task=live_task,
    )
    if focus in leftover or not focus:
        return recovered_step
    return focus


def live_coach_stage_label(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    stage_title: str = "",
) -> str:
    """Live stage object is recovered current_step, not leftover formal title."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)
    if recovered and not recovered_step:
        return ""
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    label = _text(stage_title) or _formal_plan_candidate_focus(plan)
    if live_plan:
        return label
    # Orphaned pressure-only runtime (no formal plan) must not invent stage/task chrome.
    # Tight budget / leftover blocker urgency may still shrink pedagogy, but not mint a live task.
    if plan is None and recovered:
        return ""
    leftover = leftover_formal_training_labels(
        plan=plan,
        live_plan=False,
        live_task=True,
    )
    if label in leftover or not label:
        return recovered_step
    return label


def live_plan_lane_copy(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    stage_title: str = "",
) -> dict[str, str]:
    """Plan-lane chrome uses recovered current_step, not leftover formal stage title."""

    label = live_coach_stage_label(
        plan=plan,
        runtime=runtime,
        existing=existing,
        stage_title=stage_title,
    )
    if label:
        return {
            "label": label,
            "en": f"Current lane: keep the work inside Plan around '{label}'.",
            "zh": f"当前先留在 Plan 这条主线上，围绕「{label}」推进。",
        }
    return {
        "label": "",
        "en": "Current lane: keep the work inside Plan and generate the formal thread first.",
        "zh": "当前先留在 Plan 这条主线上，先生成正式计划。",
    }


def live_plan_artifact_stage_chrome(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    stage_title: str = "",
    coaching_next_step: str = "",
) -> dict[str, str]:
    """Plan artifact bullet/teaser and Coach active_stage share one live label."""

    label = live_coach_stage_label(
        plan=plan,
        runtime=runtime,
        existing=existing,
        stage_title=stage_title,
    )
    return {
        "active_stage": label,
        "bullet": label,
        "teaser": _text(coaching_next_step) or label,
        "stage_focus": label,
        "lane_focus": label,
        "summary_object": label,
    }


def live_plan_update_persist_chrome(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    stage_title: str = "",
    coaching_next_step: str = "",
    task_title: str = "",
    stage_goal: str = "",
) -> dict[str, str]:
    """Plan-update summary object and persist lane/stage focus share one live label."""

    chrome = live_plan_artifact_stage_chrome(
        plan=plan,
        runtime=runtime,
        existing=existing,
        stage_title=stage_title,
        coaching_next_step=coaching_next_step,
    )
    label = chrome["summary_object"]
    recovered = bool(runtime or existing)
    recovered_step = (
        _text(runtime.get("current_step") if isinstance(runtime, dict) else "")
        or _text(existing.get("current_step") if isinstance(existing, dict) else "")
        or label
    )
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    live_task = formal_task_is_live_runtime_identity(
        recovered=recovered,
        runtime_current_step=recovered_step,
        task_title=task_title,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=task_title,
        live_plan=live_plan,
        live_task=live_task,
    )
    task_focus = _text(task_title)
    if task_focus in leftover or (recovered and not label):
        task_focus = ""
    lane_focus = task_focus or chrome["stage_focus"]
    persist_next = (_text(stage_goal) or label) if live_plan and label else label
    if recovered and not label:
        active_task = ""
    elif live_plan or live_task:
        active_task = _text(task_title)
    elif plan is None:
        # No formal plan: leftover runtime + urgency must not invent active_task.
        active_task = ""
    else:
        active_task = label if _text(task_title) in leftover or not task_title else _text(task_title)
    return {
        **chrome,
        "stage_focus": chrome["stage_focus"],
        "task_focus": task_focus,
        "lane_focus": lane_focus,
        "next_step": persist_next,
        "active_task": active_task,
        "why_now": (
            f"Keep the live stage '{label}' small enough to recover."
            if label
            else ""
        ),
        "focus_area": label,
        "summary_object": label,
        "summary_en": (
            f"Plan tightened around {label}."
            if label
            else "Plan updated and ready for execution."
        ),
        "summary_zh": (
            f"计划已收紧到{label}。"
            if label
            else "计划已更新，可以继续执行。"
        ),
    }


def live_leftover_focus_candidate(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    stage_title: str = "",
    task_title: str = "",
    candidate: str = "",
    fallback: str = "",
) -> str:
    """Idea/adaptation focus keeps real source areas, not leftover formal titles."""

    chrome = live_plan_update_persist_chrome(
        plan=plan,
        runtime=runtime,
        existing=existing,
        stage_title=stage_title,
        task_title=task_title,
    )
    text = _text(candidate)
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=task_title,
        live_plan=formal_plan_is_live_runtime_identity(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=chrome["stage_focus"],
        ),
        live_task=formal_task_is_live_runtime_identity(
            recovered=bool(runtime or existing),
            runtime_current_step=chrome["stage_focus"],
            task_title=task_title,
        ),
    )
    if text and text not in leftover:
        return text
    return chrome["focus_area"] or fallback


def live_plan_refresh_step_why(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    why_now: str = "",
    next_after_current: str = "",
    stage_title: str = "",
    task_title: str = "",
    stage_goal: str = "",
) -> dict[str, str]:
    """Completed/else plan-refresh writes recovered step/why/next, not leftover formal fields."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    chrome = live_plan_update_persist_chrome(
        plan=plan,
        runtime=runtime,
        existing=existing,
        stage_title=stage_title,
        task_title=task_title,
        stage_goal=stage_goal,
    )
    recovered_step = (
        _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
        or chrome["next_step"]
    )
    recovered_why = _text(runtime.get("why_now")) or _text(existing.get("why_now"))
    recovered_next = (
        _text(runtime.get("next_after_current"))
        or _text(existing.get("next_after_current"))
    )
    recovered = bool(runtime or existing)
    if recovered and not recovered_step:
        return {"current_step": "", "why_now": "", "next_after_current": ""}
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=task_title,
        live_plan=live_plan,
        live_task=True,
    )
    step = _text(current_step)
    why = _text(why_now)
    nxt = _text(next_after_current)
    if live_plan:
        return {"current_step": step, "why_now": why, "next_after_current": nxt}
    if step in leftover or not step:
        step = recovered_step
    if why in leftover or not why:
        why = recovered_why
    if nxt in leftover or not nxt:
        nxt = recovered_next
    if nxt in leftover:
        nxt = ""
    return {"current_step": step, "why_now": why, "next_after_current": nxt}


def live_plan_mismatch_candidate_step(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
    stage_title: str = "",
    task_title: str = "",
) -> str:
    """Plan-mismatch persist stores recovered current_step, not leftover formal."""

    return live_plan_refresh_step_why(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=current_step,
        stage_title=stage_title,
        task_title=task_title,
    )["current_step"]


def live_plan_mismatch_candidate_plan_id(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    request_plan_id: str = "",
    current_step: str = "",
    stage_title: str = "",
    task_title: str = "",
) -> str:
    """Plan-mismatch persist stores a live plan id, not leftover formal identity."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = live_plan_mismatch_candidate_step(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=_text(current_step)
        or _text(runtime.get("current_step"))
        or _text(existing.get("current_step")),
        stage_title=stage_title,
        task_title=task_title,
    )
    requested = _text(request_plan_id)
    formal = _text(
        getattr(plan, "id", "") or getattr(plan, "plan_id", "") if plan is not None else ""
    )
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    recovered = bool(runtime or existing)
    if recovered and not recovered_step:
        if requested and requested != formal:
            return requested
        return ""
    if live_plan:
        return requested or formal
    if requested and requested != formal:
        return requested
    return ""


def live_plan_snapshot_persist_chrome(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    stage_title: str = "",
    task_title: str = "",
    stage_goal: str = "",
) -> dict[str, str]:
    """Sandbox persist, mismatch stage_id, and memory focus share one leftover gate."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    formal_title = _text(getattr(plan, "title", "") if plan is not None else "")
    formal_stage = _text(stage_title) or _formal_plan_candidate_focus(plan)
    formal_step = _text(getattr(plan, "current_step", "") if plan is not None else "")
    refresh = live_plan_refresh_step_why(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=formal_step,
        why_now=_text(getattr(plan, "why_now", "") if plan is not None else ""),
        next_after_current=_text(getattr(plan, "next_after_current", "") if plan is not None else ""),
        stage_title=formal_stage,
        task_title=task_title,
        stage_goal=stage_goal,
    )
    recovered_step = refresh["current_step"]
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=task_title,
        live_plan=live_plan,
        live_task=True,
    )
    recovered = bool(runtime or existing)
    label = live_coach_stage_label(
        plan=plan,
        runtime=runtime,
        existing=existing,
        stage_title=formal_stage,
    )
    stage_id = live_runtime_stage_id(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    title = formal_title
    summary = _text(getattr(plan, "summary", "") if plan is not None else "")
    show_stages = "1"
    plan_id = live_plan_mismatch_candidate_plan_id(
        plan=plan,
        runtime=runtime,
        existing=existing,
        request_plan_id=_text(runtime.get("plan_id") or existing.get("plan_id")),
        current_step=recovered_step,
        stage_title=formal_stage,
        task_title=task_title,
    )
    if recovered and not recovered_step:
        title = ""
        label = ""
        stage_id = ""
        summary = ""
        show_stages = ""
        plan_id = ""
    elif not live_plan:
        if title in leftover:
            title = recovered_step
        if summary in leftover:
            summary = ""
        show_stages = ""
    focus = live_coach_focus_area(
        plan=plan,
        runtime=runtime,
        existing=existing,
        candidate=formal_stage or formal_title,
    )
    return {
        "plan_title": title,
        "current_step": recovered_step,
        "why_now": refresh["why_now"],
        "next_after_current": refresh["next_after_current"],
        "stage_id": stage_id,
        "stage_title": label,
        "focus": focus,
        "summary": summary,
        "show_stages": show_stages,
        "plan_id": plan_id,
    }


def live_plan_update_heading(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    fallback: str = "",
) -> str:
    """Plan-update heading uses recovered current_step, not leftover formal plan title."""

    if plan is None:
        return _text(fallback)
    chrome = live_plan_snapshot_persist_chrome(
        plan=plan,
        runtime=runtime,
        existing=existing,
        stage_title=_formal_plan_candidate_focus(plan),
    )
    return chrome["plan_title"] or _text(fallback)


def live_task_label(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
) -> str:
    """Task chrome uses recovered current_step, not leftover formal task title."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)
    title = _text(task_title) or _text(getattr(task, "title", "") if task is not None else "")
    if recovered and not recovered_step:
        return ""
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    live_task = formal_task_is_live_runtime_identity(
        recovered=recovered,
        runtime_current_step=recovered_step,
        task_title=title,
    )
    if live_plan or live_task:
        return title
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=title,
        live_plan=False,
        live_task=False,
    )
    if title in leftover or not title:
        return recovered_step
    return title


def live_task_focus_area(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
    fallback: str = "",
) -> str:
    """Artifact focus_area uses recovered current_step, not leftover formal task title."""

    return live_task_label(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=task_title,
    ) or _text(fallback)


def live_task_next_action(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    goal: str = "",
    task_title: str = "",
    task_goal: str = "",
) -> str:
    """next_action fallback uses recovered current_step, not leftover formal task title."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)
    title = _text(task_title) or _text(getattr(task, "title", "") if task is not None else "")
    leftover_goal = (
        _text(task_goal)
        or _text(getattr(task, "natural_language_goal", "") if task is not None else "")
    )
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    live_task = formal_task_is_live_runtime_identity(
        recovered=recovered,
        runtime_current_step=recovered_step,
        task_title=title,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=title,
        task_goal=leftover_goal,
        live_plan=live_plan,
        live_task=live_task,
    )
    text = _text(goal)
    if recovered and not recovered_step:
        return ""
    if text and text not in leftover:
        return text
    return live_task_label(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=title,
    )


def live_task_suggested_reason(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    reason: str = "",
    task_title: str = "",
) -> str:
    """Suggested-action reason uses recovered current_step, not leftover formal task title."""

    return live_task_next_action(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        goal=reason,
        task_title=task_title,
    )


def live_task_suggested_title(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    title: str = "",
    goal: str = "",
    task_title: str = "",
) -> str:
    """Suggested-action title uses recovered current_step, not leftover formal goal."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)
    leftover_goal = (
        _text(goal)
        or _text(getattr(task, "natural_language_goal", "") if task is not None else "")
    )
    candidate = _text(title) or leftover_goal
    if not candidate:
        return ""
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    live_task = formal_task_is_live_runtime_identity(
        recovered=recovered,
        runtime_current_step=recovered_step,
        task_title=_text(task_title) or _text(getattr(task, "title", "") if task is not None else ""),
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=_text(task_title) or _text(getattr(task, "title", "") if task is not None else ""),
        task_goal=leftover_goal,
        live_plan=live_plan,
        live_task=live_task,
    )
    if recovered and not recovered_step:
        leftover = leftover_formal_training_labels(
            plan=plan,
            task_title=_text(task_title) or _text(getattr(task, "title", "") if task is not None else ""),
            task_goal=leftover_goal,
            live_plan=False,
            live_task=False,
        )
        return "" if candidate in leftover else candidate
    if live_plan or live_task:
        return candidate
    if candidate in leftover:
        return recovered_step
    return candidate


def live_coaching_next_step(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    next_step: str = "",
    goal: str = "",
    task_title: str = "",
) -> str:
    """General coaching next_step uses recovered current_step, not leftover formal goal."""

    return live_task_suggested_title(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        title=next_step or goal,
        goal=goal,
        task_title=task_title,
    )


def live_language_detection_hint(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    hint: str = "",
    goal: str = "",
    task_title: str = "",
) -> str:
    """Language-detection hint uses recovered current_step, not leftover formal goal."""

    return live_task_suggested_title(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        title=hint or goal,
        goal=goal,
        task_title=task_title,
    )


def live_task_training_concepts(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    concepts: list[str] | tuple[str, ...] | None = None,
    task_title: str = "",
) -> list[str]:
    """Training/eval concepts use recovered current_step, not leftover formal task title."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)
    title = _text(task_title) or _text(getattr(task, "title", "") if task is not None else "")
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    live_task = formal_task_is_live_runtime_identity(
        recovered=recovered,
        runtime_current_step=recovered_step,
        task_title=title,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=title,
        task_goal=_text(getattr(task, "natural_language_goal", "") if task is not None else ""),
        live_plan=False if recovered and not recovered_step else live_plan,
        live_task=False if recovered and not recovered_step else live_task,
    )
    live = live_task_label(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=title,
    )
    items: list[str] = []
    for item in concepts or []:
        text = _text(item)
        if not text or text in items:
            continue
        if leftover and text in leftover and text != live:
            continue
        items.append(text)
    if items:
        return items
    return [live] if live else []


def live_task_clean_step_candidates(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    next_step: str = "",
    goal: str = "",
    task_title: str = "",
) -> list[str]:
    """Clean-step candidates keep leftover formal task.title off the live list."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)
    title = _text(task_title) or _text(getattr(task, "title", "") if task is not None else "")
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    live_task = formal_task_is_live_runtime_identity(
        recovered=recovered,
        runtime_current_step=recovered_step,
        task_title=title,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=title,
        task_goal=_text(goal) or _text(getattr(task, "natural_language_goal", "") if task is not None else ""),
        live_plan=live_plan,
        live_task=live_task,
    )
    live_title = live_task_label(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=title,
    )
    candidates: list[str] = []
    for item in (_text(next_step), _text(goal), live_title):
        if not item or item in candidates:
            continue
        if leftover and item in leftover and item != live_title:
            continue
        candidates.append(item)
    return candidates


def live_task_heading(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
    fallback: str = "",
) -> str:
    """Task/next_task heading uses recovered current_step, not leftover formal title."""

    return live_task_label(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=task_title,
    ) or _text(fallback)


def live_task_thin_slice_copy(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
) -> dict[str, str]:
    """Thin-slice coach copy uses recovered current_step, not leftover formal task title."""

    label = live_task_label(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=task_title,
    )
    if label:
        return {
            "label": label,
            "en": f"Treat '{label}' as the next thin slice.",
            "zh": f"把「{label}」当成下一小步里最小、最可验证的一块。",
        }
    return {
        "label": "",
        "en": "Keep the next thin slice on the current recovered work.",
        "zh": "先把下一小步压在当前已恢复的工作上。",
    }


def live_task_picked_copy(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
) -> dict[str, str]:
    """Next-task pick copy uses recovered current_step, not leftover formal task title."""

    label = live_task_label(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=task_title,
    )
    if label:
        return {
            "label": label,
            "en": (
                f"I picked the next training task: {label}. "
                "Start with the thinnest verifiable slice, then come back so we can review the result together."
            ),
            "zh": (
                f"我已经为你选好了下一个训练任务：{label}。"
                "先完成一个最小可验证的步骤，完成后带着结果回来，我们再一起复盘。"
            ),
        }
    return {
        "label": "",
        "en": (
            "I picked the next training task from the recovered current step. "
            "Start with the thinnest verifiable slice, then come back so we can review the result together."
        ),
        "zh": (
            "我已经按当前已恢复的步骤选好了下一个训练任务。"
            "先完成一个最小可验证的步骤，完成后带着结果回来，我们再一起复盘。"
        ),
    }


def live_task_converted_copy(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
) -> dict[str, str]:
    """Goal-to-task copy uses recovered current_step, not leftover formal task title."""

    label = live_task_label(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=task_title,
    )
    if label:
        return {
            "label": label,
            "en": (
                f"I converted your goal into a practice task: {label}. "
                "Check the constraints and acceptance criteria first, then implement the smallest slice that proves the idea."
            ),
            "zh": (
                f"我把你的目标整理成了一项练习任务：{label}。"
                "先看清限制和完成标准，再实现能验证想法的最小一步。"
            ),
        }
    return {
        "label": "",
        "en": (
            "I converted your goal into a practice task on the recovered current step. "
            "Check the constraints and acceptance criteria first, then implement the smallest slice that proves the idea."
        ),
        "zh": (
            "我把你的目标整理成了当前已恢复步骤上的一项练习任务。"
            "先看清限制和完成标准，再实现能验证想法的最小一步。"
        ),
    }


def live_training_card_title(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
    card_title: str = "",
) -> str:
    """Training-card chrome uses recovered current_step, not leftover formal titles."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)
    title = _text(card_title)
    if recovered and not recovered_step:
        return ""
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    live_task = formal_task_is_live_runtime_identity(
        recovered=recovered,
        runtime_current_step=recovered_step,
        task_title=_text(task_title) or _text(getattr(task, "title", "") if task is not None else ""),
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=_text(task_title) or _text(getattr(task, "title", "") if task is not None else ""),
        live_plan=live_plan,
        live_task=live_task,
    )
    if not live_plan and title and (
        title in leftover or any(label and label in title for label in leftover)
    ):
        return recovered_step
    return title


def live_training_focus_fallback(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
    card_title: str = "",
    fallback: str = "",
) -> str:
    """live_current_task_focus fallback uses recovered current_step, not leftover formal card title."""

    live = live_task_focus_area(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=task_title,
        fallback="",
    )
    if live:
        return live
    title = live_training_card_title(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=task_title,
        card_title=card_title,
    )
    return title or _text(fallback)


def live_training_why_this_card(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
    card_title: str = "",
    why_now: str = "",
    kind: str = "current",
) -> str:
    """why_this_card uses recovered current_step, not leftover formal card titles."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)
    title = live_training_card_title(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=task_title,
        card_title=card_title,
    )
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=_text(task_title) or _text(getattr(task, "title", "") if task is not None else ""),
        live_plan=False,
        live_task=False,
    )
    why = _text(why_now)
    leftover_not_live = recovered and (not recovered_step or not live_plan)
    if leftover_not_live and leftover and why and (
        why in leftover or any(label and label in why for label in leftover)
    ):
        why = recovered_step if recovered_step and recovered_step not in leftover else ""
    if why:
        return why
    if title:
        if kind == "next":
            return f"{title} is the next training card."
        return f"{title} is the current training card."
    return ""


def live_training_open_copy(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
    card_title: str = "",
    next_step: str = "",
    primer_required: bool = False,
) -> dict[str, str]:
    """Open Training chrome uses recovered current_step, not leftover formal card titles."""

    title = live_training_card_title(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=task_title,
        card_title=card_title,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=_text(task_title) or _text(getattr(task, "title", "") if task is not None else ""),
        live_plan=False,
        live_task=False,
    )
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime if isinstance(runtime, dict) else {},
        existing=existing if isinstance(existing, dict) else {},
        current_step=_text((runtime or {}).get("current_step") if isinstance(runtime, dict) else "")
        or _text((existing or {}).get("current_step") if isinstance(existing, dict) else ""),
    )
    leftover_not_live = bool(runtime or existing) and (not title or not live_plan)
    step = _text(next_step)
    if leftover_not_live and leftover and step and (
        step in leftover or any(label and label in step for label in leftover)
    ):
        step = title
    if title:
        return {
            "title": title,
            "en_current": f"- Current card: **{title}**",
            "zh_current": f"- 当前卡片：**{title}**",
            "en_summary": f"{title} is now the active learn-first card.",
            "zh_summary": f"{title} 已经是当前训练主线。",
            "en_complete": (
                f"Open Training and finish the primer for {title}."
                if primer_required
                else (
                    f"Open Training and start with: {step}"
                    if step
                    else f"Open Training and complete {title}."
                )
            ),
            "zh_complete": (
                f"打开 Training，先完成 {title} 的 primer。"
                if primer_required
                else (
                    f"打开 Training，先做这一步：{step}"
                    if step
                    else f"打开 Training，完成 {title}。"
                )
            ),
        }
    return {
        "title": "",
        "en_current": "- Current card: keep one single current card.",
        "zh_current": "- 当前卡片：只保留一张当前主卡。",
        "en_summary": "The current training card is now the learn-first line.",
        "zh_summary": "当前训练卡已经是训练主线。",
        "en_complete": "Open Training and complete the current card.",
        "zh_complete": "打开 Training，完成当前卡片。",
    }


def live_training_persist_chrome(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
    card_title: str = "",
    summary: str = "",
) -> dict[str, str]:
    """Persist chrome uses recovered current_step, not leftover formal card titles."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime.get("current_step"))
        or _text(existing.get("current_step"))
    )
    recovered = bool(runtime or existing)
    title = live_training_card_title(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=task_title,
        card_title=card_title,
    )
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=_text(task_title) or _text(getattr(task, "title", "") if task is not None else ""),
        live_plan=False,
        live_task=False,
    )
    leftover_not_live = recovered and (not recovered_step or not live_plan)
    cleaned = _text(summary)
    if leftover_not_live and leftover and cleaned and (
        cleaned in leftover or any(label and label in cleaned for label in leftover)
    ):
        cleaned = ""
    if cleaned:
        return {
            "selected_card_title": title,
            "verification_summary": cleaned,
        }
    if title:
        return {
            "selected_card_title": title,
            "verification_summary": f"{title} passed current-file verification.",
        }
    return {
        "selected_card_title": "",
        "verification_summary": "Current-file verification passed.",
    }


def live_training_lane_copy(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
    card_title: str = "",
) -> dict[str, str]:
    """Training-lane chrome uses recovered current_step, not leftover formal titles."""

    title = live_training_card_title(
        plan=plan,
        task=task,
        runtime=runtime,
        existing=existing,
        task_title=task_title,
        card_title=card_title,
    )
    if title:
        return {
            "label": title,
            "en": f"Current lane: stay inside Training and keep '{title}' as the single current card.",
            "zh": f"当前先留在 Training 这条主线上，把「{title}」作为当前唯一主卡。",
        }
    return {
        "label": "",
        "en": "Current lane: stay inside Training and keep one single current card.",
        "zh": "当前先留在 Training 这条主线上，只保留一张当前主卡。",
    }


_MEMORY_LIVE_TEXT_KEYS = frozenset(
    {
        "focus_area",
        "summary",
        "next_step",
        "latest_coach_focus_area",
        "latest_turn_focus_area",
        "latest_coach_summary",
        "latest_turn_summary",
        "latest_coach_next_step",
        "latest_turn_next_step",
        "latest_user_feedback_focus",
        "latest_learning_blocker",
    }
)
_TRAINING_CARD_LIVE_TEXT_KEYS = (
    "title",
    "why_now",
    "focus_area",
    "target_skill",
    "problem_statement",
    "question",
    "scenario",
    "suggested_workspace_action",
    "deliverable",
    "context",
    "expected_answer",
    "stuck_recovery",
    "reflection_prompt",
    "trainer_review_input",
    "knowledge_type",
    "validation_method",
    "expected_answer_shape",
    "success_signal",
    "return_with",
    "next_after_completion",
    "scenario_pack",
    "verification_method",
)
_TRAINING_CARD_LIVE_LIST_KEYS = (
    "self_check",
    "hint_ladder",
    "common_mistakes",
    "next_steps",
    "learner_deliverables",
    "grading_rubric",
    "verification_steps",
)
_SCENARIO_LAB_LIVE_TEXT_KEYS = (
    "title",
    "focus_area",
    "summary",
    "success_signal",
    "review_outcome",
)
_SCENARIO_LAB_LIVE_LIST_KEYS = (
    "learner_deliverables",
    "verification_steps",
    "migrate_back_guidance",
)
_THEORY_DRILL_LIVE_TEXT_KEYS = (
    "title",
    "focus_area",
    "summary",
    "success_signal",
    "return_with",
)
_THEORY_DRILL_QUESTION_LIVE_TEXT_KEYS = (
    "prompt",
    "answer",
    "explanation",
    "knowledge_type",
)
_REVIEW_ARTIFACT_LIVE_TEXT_KEYS = (
    "title",
    "focus_area",
    "summary",
    "root_cause",
    "guardrail",
    "verified_result",
    "blocker",
)


def _replace_leftover_live_text(
    text: Any,
    leftover: set[str],
    recovered: str,
    *,
    embedded: bool = False,
) -> str:
    cleaned = _text(text)
    if not cleaned:
        return ""
    if cleaned in leftover:
        return recovered
    if not embedded:
        return cleaned
    for label in leftover:
        if not label:
            continue
        quoted = f"'{label}'" in cleaned or f"「{label}」" in cleaned
        colon = f": {label}" in cleaned or f"：{label}" in cleaned
        from_label = f"from {label}" in cleaned or f"Completed {label}" in cleaned
        if quoted or colon or from_label or (len(label) >= 12 and label in cleaned):
            cleaned = cleaned.replace(label, recovered)
    return _text(cleaned)


def _gate_embedded_texts(
    items: list[str] | None,
    leftover: set[str],
    recovered: str,
) -> list[str]:
    gated: list[str] = []
    for item in items or []:
        replaced = _replace_leftover_live_text(item, leftover, recovered, embedded=True)
        if replaced:
            gated.append(replaced)
    return gated


def _gate_record_title_fields(
    item: dict[str, Any],
    leftover: set[str],
    recovered: str,
    keys: tuple[str, ...],
) -> dict[str, Any]:
    copy = dict(item)
    for key in keys:
        if key not in copy:
            continue
        copy[key] = _replace_leftover_live_text(
            copy.get(key),
            leftover,
            recovered,
            embedded=key not in {"focus_area", "concept"},
        )
    return copy


def _gate_memory_thread_fields(
    thread: dict[str, Any],
    leftover: set[str],
    recovered: str,
) -> dict[str, str]:
    gated: dict[str, str] = {}
    for key in ("focus_area", "summary", "next_step"):
        if key in thread:
            gated[key] = _replace_leftover_live_text(thread.get(key), leftover, recovered)
    return gated


def _gate_record_list_fields(
    item: dict[str, Any],
    leftover: set[str],
    recovered: str,
    keys: tuple[str, ...],
) -> dict[str, Any]:
    copy = dict(item)
    for key in keys:
        value = copy.get(key)
        if not isinstance(value, list):
            continue
        copy[key] = _gate_embedded_texts([str(entry) for entry in value], leftover, recovered)
    return copy


def _gate_training_card_payload(
    item: dict[str, Any],
    leftover: set[str],
    recovered: str,
) -> dict[str, Any]:
    gated = _gate_record_title_fields(
        item,
        leftover,
        recovered,
        _TRAINING_CARD_LIVE_TEXT_KEYS,
    )
    return _gate_record_list_fields(
        gated,
        leftover,
        recovered,
        _TRAINING_CARD_LIVE_LIST_KEYS,
    )


def _gate_scenario_lab_payload(
    item: dict[str, Any],
    leftover: set[str],
    recovered: str,
) -> dict[str, Any]:
    gated = _gate_record_title_fields(
        item,
        leftover,
        recovered,
        _SCENARIO_LAB_LIVE_TEXT_KEYS,
    )
    return _gate_record_list_fields(
        gated,
        leftover,
        recovered,
        _SCENARIO_LAB_LIVE_LIST_KEYS,
    )


def _gate_flash_deck_payload(
    item: dict[str, Any],
    leftover: set[str],
    recovered: str,
) -> dict[str, Any]:
    gated = _gate_record_title_fields(
        item,
        leftover,
        recovered,
        ("title", "focus_area"),
    )
    gated["cards"] = [
        _gate_training_card_payload(card, leftover, recovered)
        for card in item.get("cards") or []
        if isinstance(card, dict)
    ]
    return gated


def _gate_theory_drill_question(
    item: dict[str, Any],
    leftover: set[str],
    recovered: str,
) -> dict[str, Any]:
    gated = _gate_record_title_fields(
        item,
        leftover,
        recovered,
        _THEORY_DRILL_QUESTION_LIVE_TEXT_KEYS,
    )
    if isinstance(gated.get("choices"), list):
        gated["choices"] = _gate_embedded_texts(
            [str(choice) for choice in gated["choices"]],
            leftover,
            recovered,
        )
    return gated


def _gate_theory_drill_payload(
    item: dict[str, Any],
    leftover: set[str],
    recovered: str,
) -> dict[str, Any]:
    gated = _gate_record_title_fields(
        item,
        leftover,
        recovered,
        _THEORY_DRILL_LIVE_TEXT_KEYS,
    )
    gated["questions"] = [
        _gate_theory_drill_question(question, leftover, recovered)
        for question in item.get("questions") or []
        if isinstance(question, dict)
    ]
    return gated


def _gate_theory_drill_history(
    entries: list[dict[str, Any]],
    leftover: set[str],
    recovered: str,
) -> list[dict[str, Any]]:
    gated: list[dict[str, Any]] = []
    for item in entries:
        copy = dict(item)
        if "note" in copy:
            copy["note"] = _replace_leftover_live_text(
                copy.get("note"),
                leftover,
                recovered,
                embedded=True,
            )
        for key in ("before_snapshot", "after_snapshot"):
            snap = copy.get(key)
            if isinstance(snap, dict):
                copy[key] = _gate_theory_drill_payload(snap, leftover, recovered)
        gated.append(copy)
    return gated


def _gate_scenario_lab_history(
    entries: list[dict[str, Any]],
    leftover: set[str],
    recovered: str,
) -> list[dict[str, Any]]:
    gated: list[dict[str, Any]] = []
    for item in entries:
        copy = dict(item)
        if "note" in copy:
            copy["note"] = _replace_leftover_live_text(
                copy.get("note"),
                leftover,
                recovered,
                embedded=True,
            )
        for key in ("before_snapshot", "after_snapshot"):
            snap = copy.get(key)
            if isinstance(snap, dict):
                copy[key] = _gate_scenario_lab_payload(snap, leftover, recovered)
        gated.append(copy)
    return gated


def _gate_review_artifact_payload(
    item: dict[str, Any],
    leftover: set[str],
    recovered: str,
) -> dict[str, Any]:
    return _gate_record_title_fields(
        item,
        leftover,
        recovered,
        _REVIEW_ARTIFACT_LIVE_TEXT_KEYS,
    )


def _gate_review_artifact_history(
    entries: list[dict[str, Any]],
    leftover: set[str],
    recovered: str,
) -> list[dict[str, Any]]:
    gated: list[dict[str, Any]] = []
    for item in entries:
        copy = dict(item)
        if "note" in copy:
            copy["note"] = _replace_leftover_live_text(
                copy.get("note"),
                leftover,
                recovered,
                embedded=True,
            )
        for key in ("before_snapshot", "after_snapshot"):
            snap = copy.get(key)
            if isinstance(snap, dict):
                copy[key] = _gate_review_artifact_payload(snap, leftover, recovered)
        gated.append(copy)
    return gated


def live_memory_snapshot_overlay(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    recent_summary: str = "",
    workspace: dict[str, Any] | None = None,
    active_thread: Any | None = None,
    teaching_observations: list[str] | None = None,
    user_feedback: list[dict[str, Any]] | None = None,
    recent_wins: list[str] | None = None,
    weaknesses: list[str] | None = None,
    teaching_strategy_effectiveness: list[dict[str, Any]] | None = None,
    learning_outcomes: list[dict[str, Any]] | None = None,
    top_weakness: str = "",
    reflections: list[str] | None = None,
    lowest_mastery_concepts: list[str] | None = None,
    coaching_adaptation: dict[str, Any] | None = None,
    memory_evidence: list[str] | None = None,
    plan_change_summary: str = "",
    due_reviews: list[dict[str, Any]] | None = None,
    teaching_assets: list[dict[str, Any]] | None = None,
    training_cards: list[dict[str, Any]] | None = None,
    review_artifact: dict[str, Any] | None = None,
    review_artifact_history: list[dict[str, Any]] | None = None,
    scenario_lab: dict[str, Any] | None = None,
    scenario_lab_history: list[dict[str, Any]] | None = None,
    flash_deck: dict[str, Any] | None = None,
    theory_drill: dict[str, Any] | None = None,
    theory_drill_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Gate leftover formal titles/ids on live memory snapshot surfaces."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    chrome = live_plan_snapshot_persist_chrome(
        plan=plan,
        runtime=runtime,
        existing=existing,
    )
    recovered_step = chrome["current_step"]
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=recovered_step,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        live_plan=live_plan,
        live_task=True,
    )
    leftover_plan_id = (
        ""
        if live_plan
        else _text(
            getattr(plan, "id", "") or getattr(plan, "plan_id", "") if plan is not None else ""
        )
    )
    thread_source = active_thread
    if thread_source is not None and not isinstance(thread_source, dict):
        thread_source = {
            "focus_area": _text(getattr(thread_source, "focus_area", "")),
            "summary": _text(getattr(thread_source, "summary", "")),
            "next_step": _text(getattr(thread_source, "next_step", "")),
        }
    workspace_payload = dict(workspace) if isinstance(workspace, dict) else {}
    observations = list(teaching_observations or [])
    feedback = [dict(item) for item in user_feedback or [] if isinstance(item, dict)]
    wins = list(recent_wins or [])
    weakness_texts = list(weaknesses or [])
    strategies = [dict(item) for item in teaching_strategy_effectiveness or [] if isinstance(item, dict)]
    outcomes = [dict(item) for item in learning_outcomes or [] if isinstance(item, dict)]
    reflection_texts = list(reflections or [])
    mastery_concepts = list(lowest_mastery_concepts or [])
    evidence_texts = list(memory_evidence or [])
    adaptation = dict(coaching_adaptation) if isinstance(coaching_adaptation, dict) else {}
    review_items = [dict(item) for item in due_reviews or [] if isinstance(item, dict)]
    asset_items = [dict(item) for item in teaching_assets or [] if isinstance(item, dict)]
    card_items = [dict(item) for item in training_cards or [] if isinstance(item, dict)]
    artifact = dict(review_artifact) if isinstance(review_artifact, dict) else {}
    history_items = [dict(item) for item in review_artifact_history or [] if isinstance(item, dict)]
    lab = dict(scenario_lab) if isinstance(scenario_lab, dict) else {}
    lab_history = [dict(item) for item in scenario_lab_history or [] if isinstance(item, dict)]
    deck = dict(flash_deck) if isinstance(flash_deck, dict) else {}
    drill = dict(theory_drill) if isinstance(theory_drill, dict) else {}
    drill_history = [dict(item) for item in theory_drill_history or [] if isinstance(item, dict)]
    if live_plan:
        return {
            "recent_summary": _text(recent_summary),
            "workspace": workspace_payload,
            "active_thread": thread_source if isinstance(thread_source, dict) else {},
            "teaching_observations": observations,
            "user_feedback": feedback,
            "recent_wins": wins,
            "weaknesses": weakness_texts,
            "teaching_strategy_effectiveness": strategies,
            "learning_outcomes": outcomes,
            "top_weakness": _text(top_weakness),
            "reflections": reflection_texts,
            "lowest_mastery_concepts": mastery_concepts,
            "coaching_adaptation": adaptation,
            "memory_evidence": evidence_texts,
            "plan_change_summary": _text(plan_change_summary),
            "due_reviews": review_items,
            "teaching_assets": asset_items,
            "training_cards": card_items,
            "review_artifact": artifact,
            "review_artifact_history": history_items,
            "scenario_lab": lab,
            "scenario_lab_history": lab_history,
            "flash_deck": deck,
            "theory_drill": drill,
            "theory_drill_history": drill_history,
        }
    if recovered_step:
        live_next_hop = workspace_payload.get("latest_training_next_hop")
        if isinstance(live_next_hop, dict):
            workspace_payload["latest_training_next_hop"] = {
                **live_next_hop,
                "title": recovered_step,
                "card_title": recovered_step,
            }
    gated_workspace = dict(workspace_payload)
    for key, value in list(gated_workspace.items()):
        if key in {PLAN_RUNTIME_KEY, "latestPlanRuntime"}:
            continue
        if key in {"plan_id", "planId"} and leftover_plan_id and _text(value) == leftover_plan_id:
            gated_workspace[key] = ""
            continue
        if isinstance(value, str) and (
            key in _MEMORY_LIVE_TEXT_KEYS
            or key.endswith("_focus_area")
            or key.endswith("_summary")
            or key.endswith("_next_step")
        ):
            gated_workspace[key] = _replace_leftover_live_text(value, leftover, recovered_step)
        elif key == "active_thread" and isinstance(value, dict):
            nested = dict(value)
            nested.update(_gate_memory_thread_fields(nested, leftover, recovered_step))
            gated_workspace[key] = nested
    # A recovered runtime step is the authoritative visible next hop, even when
    # the old formal-plan identity was gated from the workspace payload.
    if recovered_step:
        next_hop = gated_workspace.get("latest_training_next_hop")
        if isinstance(next_hop, dict):
            next_hop = dict(next_hop)
            next_hop["title"] = recovered_step
            next_hop["card_title"] = recovered_step
            next_hop.pop("cardTitle", None)
            gated_workspace["latest_training_next_hop"] = next_hop
    gated_thread = _gate_memory_thread_fields(
        thread_source if isinstance(thread_source, dict) else {},
        leftover,
        recovered_step,
    )
    gated_observations = [
        replaced
        for item in observations
        if (
            replaced := _replace_leftover_live_text(
                item,
                leftover,
                recovered_step,
                embedded=True,
            )
        )
    ]
    gated_feedback: list[dict[str, Any]] = []
    for item in feedback:
        copy = dict(item)
        if leftover_plan_id and _text(copy.get("plan_id") or copy.get("planId")) == leftover_plan_id:
            copy["plan_id"] = ""
            copy.pop("planId", None)
        if "focus_area" in copy:
            copy["focus_area"] = _replace_leftover_live_text(copy.get("focus_area"), leftover, recovered_step)
        gated_feedback.append(copy)
    return {
        "recent_summary": _replace_leftover_live_text(
            recent_summary,
            leftover,
            recovered_step,
            embedded=True,
        ),
        "workspace": gated_workspace,
        "active_thread": gated_thread,
        "teaching_observations": gated_observations,
        "user_feedback": gated_feedback,
        "recent_wins": _gate_embedded_texts(wins, leftover, recovered_step),
        "weaknesses": _gate_embedded_texts(weakness_texts, leftover, recovered_step),
        "teaching_strategy_effectiveness": [
            _gate_record_title_fields(
                item,
                leftover,
                recovered_step,
                ("focus_area", "last_summary"),
            )
            for item in strategies
        ],
        "learning_outcomes": [
            _gate_record_title_fields(
                item,
                leftover,
                recovered_step,
                ("concept", "summary"),
            )
            for item in outcomes
        ],
        "top_weakness": _replace_leftover_live_text(top_weakness, leftover, recovered_step),
        "reflections": _gate_embedded_texts(reflection_texts, leftover, recovered_step),
        "lowest_mastery_concepts": [
            replaced
            for item in mastery_concepts
            if (replaced := _replace_leftover_live_text(item, leftover, recovered_step))
        ],
        "coaching_adaptation": {
            **adaptation,
            **(
                {
                    "summary": _replace_leftover_live_text(
                        adaptation.get("summary"),
                        leftover,
                        recovered_step,
                        embedded=True,
                    ),
                    "evidence": _gate_embedded_texts(
                        list(adaptation.get("evidence") or []),
                        leftover,
                        recovered_step,
                    ),
                }
                if adaptation
                else {}
            ),
        },
        "memory_evidence": _gate_embedded_texts(evidence_texts, leftover, recovered_step),
        "plan_change_summary": _replace_leftover_live_text(
            plan_change_summary,
            leftover,
            recovered_step,
            embedded=True,
        ),
        "due_reviews": [
            _gate_record_title_fields(
                item,
                leftover,
                recovered_step,
                ("concept", "reason", "focus_area", "task_hint"),
            )
            for item in review_items
        ],
        "teaching_assets": [
            _gate_record_title_fields(
                item,
                leftover,
                recovered_step,
                ("title", "summary", "focus_area", "concept_card", "source_summary"),
            )
            for item in asset_items
        ],
        "training_cards": [
            _gate_training_card_payload(item, leftover, recovered_step)
            for item in card_items
        ],
        "review_artifact": {
            **artifact,
            **(
                _gate_review_artifact_payload(
                    artifact,
                    leftover,
                    recovered_step,
                )
                if artifact
                else {}
            ),
        },
        "review_artifact_history": _gate_review_artifact_history(
            history_items,
            leftover,
            recovered_step,
        ),
        "scenario_lab": {
            **lab,
            **(
                _gate_scenario_lab_payload(lab, leftover, recovered_step)
                if lab
                else {}
            ),
        },
        "scenario_lab_history": _gate_scenario_lab_history(
            lab_history,
            leftover,
            recovered_step,
        ),
        "flash_deck": {
            **deck,
            **(
                _gate_flash_deck_payload(deck, leftover, recovered_step)
                if deck
                else {}
            ),
        },
        "theory_drill": {
            **drill,
            **(
                _gate_theory_drill_payload(drill, leftover, recovered_step)
                if drill
                else {}
            ),
        },
        "theory_drill_history": _gate_theory_drill_history(
            drill_history,
            leftover,
            recovered_step,
        ),
    }


def coach_focus_runtime_from_snapshot(snapshot: Any | None) -> dict[str, Any]:
    """Read recovered plan runtime from a workbench snapshot when present."""

    if snapshot is None:
        return {}
    memory = getattr(snapshot, "memory", None)
    workspace = getattr(memory, "workspace", None) if memory is not None else None
    workspace = workspace if isinstance(workspace, dict) else {}
    workspace_id = _text(
        getattr(snapshot, "workspace_id", "")
        or workspace.get("workspace_id")
        or workspace.get("workspaceId")
    )
    recovered = select_plan_runtime_for_scope(
        workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
        workspace_id,
    )
    if recovered:
        return recovered
    status = getattr(snapshot, "plan_runtime_status", None)
    if not isinstance(status, dict):
        status = workspace.get("plan_runtime_status") if isinstance(workspace.get("plan_runtime_status"), dict) else None
    if isinstance(status, dict):
        step = _text(status.get("current_step") or status.get("currentStep"))
        if step or status.get("recovered") is True:
            return {
                "current_step": step,
                "plan_id": _text(status.get("plan_id") or status.get("planId")),
                "why_now": _text(status.get("why_now") or status.get("whyNow")),
                "blocked_reason": _text(status.get("blocked_reason") or status.get("blockedReason")),
            }
    return {}


def apply_live_training_mint_to_card(
    card: Any,
    *,
    anchors: dict[str, str],
    leftover_labels: set[str],
    recovered_step: str = "",
) -> Any:
    """Keep minted card why/skill/title off leftover formal labels."""

    leftover = {label for label in leftover_labels if _text(label)}
    if card is None or not leftover:
        return card
    updates: dict[str, str] = {}
    why = _text(getattr(card, "why_now", ""))
    if why in leftover:
        updates["why_now"] = _text(anchors.get("why_now"))
    skill = _text(getattr(card, "target_skill", ""))
    if skill in leftover:
        updates["target_skill"] = _text(anchors.get("target_skill"))
    focus = _text(getattr(card, "focus_area", ""))
    if focus in leftover:
        updates["focus_area"] = _text(anchors.get("focus_area"))
    title = _text(getattr(card, "title", ""))
    leftover_titles = tuple(leftover)
    titled_from_leftover = title in leftover or any(
        title
        in {
            f"Practice: {label}",
            f"Flash: {label}",
            f"练习：{label}",
            f"闪记：{label}",
        }
        for label in leftover_titles
    )
    if titled_from_leftover:
        replacement = _text(recovered_step) or _text(anchors.get("focus_area"))
        updates["title"] = "" if replacement in leftover else replacement
    if not updates:
        return card
    copier = getattr(card, "model_copy", None)
    if callable(copier):
        return copier(update=updates)
    for key, value in updates.items():
        setattr(card, key, value)
    return card


def _without_leftover_formal_identity(record: dict[str, Any], plan: Any | None) -> dict[str, Any]:
    cleaned = dict(record)
    formal_id = _text(getattr(plan, "id", "") or getattr(plan, "plan_id", "") if plan is not None else "")
    if formal_id and _text(cleaned.get("plan_id") or cleaned.get("planId")) == formal_id:
        cleaned["plan_id"] = ""
        cleaned.pop("planId", None)
    if plan is None:
        return cleaned
    for field in ("next_why_now", "next_blocked_reason"):
        formal = _text(getattr(plan, field, ""))
        if formal and _text(cleaned.get(field)) == formal:
            cleaned[field] = ""
    formal_verify = _structured_string_list(getattr(plan, "next_verify_method", []) or [])
    carried_verify = _structured_string_list(cleaned.get("next_verify_method") or [])
    if formal_verify and carried_verify == formal_verify:
        cleaned["next_verify_method"] = []
    return cleaned


def _runtime_for_formal_plan_persist(
    *,
    plan: Any | None,
    runtime: dict[str, Any],
    existing: dict[str, Any] | None,
) -> tuple[Any | None, dict[str, Any], dict[str, Any] | None]:
    """Do not let leftover formal mutate/freeze rewrite recovered current_step."""

    existing = existing if isinstance(existing, dict) else None
    existing_step = _text((existing or {}).get("current_step"))
    existing_plan_id = _text((existing or {}).get("plan_id"))
    if formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=existing or runtime,
        existing=existing,
        current_step=existing_step or _text(runtime.get("current_step")),
    ):
        return plan, runtime, existing
    if plan is not None and not existing_step and not existing_plan_id:
        return plan, runtime, existing
    plan_step = _text(getattr(plan, "current_step", "") if plan is not None else "")
    runtime_step = _text(runtime.get("current_step"))
    cleaned_existing = _without_leftover_formal_identity(existing, plan) if existing else existing
    if (
        existing_step
        and plan_step
        and runtime_step == plan_step
        and runtime_step != existing_step
    ):
        return None, _without_leftover_formal_identity(existing, plan), cleaned_existing
    return None, _without_leftover_formal_identity(runtime, plan), cleaned_existing


def build_plan_runtime_recovery(
    *,
    plan: Any | None,
    plan_runtime: dict[str, Any] | None,
    existing: dict[str, Any] | None = None,
    evidence_binding: str = "",
    request_id: str = "",
    workspace_id: str = "",
    replace_evidence_binding: bool = False,
) -> dict[str, Any] | None:
    runtime = plan_runtime if isinstance(plan_runtime, dict) else {}
    plan, runtime, existing = _runtime_for_formal_plan_persist(
        plan=plan,
        runtime=runtime,
        existing=existing,
    )
    leftover_live = leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=runtime,
        existing=existing if isinstance(existing, dict) else {},
    )
    if plan is not None and not leftover_live:
        plan_fields = {
            "current_step": "",
            "why_now": "",
            "verify_method": [],
            "blocked_reason": "",
            "next_after_current": "",
        }
    else:
        plan_fields = {
            "current_step": _text(getattr(plan, "current_step", "")),
            "why_now": _text(getattr(plan, "why_now", "")),
            "verify_method": list(getattr(plan, "verify_method", []) or []),
            "blocked_reason": _text(getattr(plan, "blocked_reason", "")),
            "next_after_current": _text(getattr(plan, "next_after_current", "")),
        }
    overlaid = overlay_plan_runtime_display_facts(
        plan_fields=plan_fields,
        recovered=runtime if _text(runtime.get("current_step")) else None,
    )
    payload = {
        "revision": _revision((existing or {}).get("revision"), 0) + 1,
        "workspace_id": workspace_id or _text((existing or {}).get("workspace_id")),
        "request_id": request_id or _text((existing or {}).get("request_id")),
        "plan_id": live_runtime_plan_id(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=overlaid["current_step"],
        )
        or None,
        "current_stage_id": live_runtime_stage_id(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=overlaid["current_step"],
        )
        or None,
        "current_step": overlaid["current_step"],
        "frozen": live_runtime_frozen(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=overlaid["current_step"],
        ),
        "blocked_reason": overlaid["blocked_reason"],
        "why_now": overlaid["why_now"],
        "verify_method": list(overlaid["verify_method"]),
        "next_after_current": overlaid["next_after_current"],
        "next_why_now": live_runtime_next_text(
            field="next_why_now",
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=overlaid["current_step"],
        ),
        "next_blocked_reason": live_runtime_next_text(
            field="next_blocked_reason",
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=overlaid["current_step"],
        ),
        "next_verify_method": live_runtime_next_verify_method(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=overlaid["current_step"],
        ),
        "evidence_binding": _text(evidence_binding)
        if replace_evidence_binding
        else (_text(evidence_binding) or _text((existing or {}).get("evidence_binding"))),
        "selected_card_id": _text(
            runtime.get("selected_card_id")
            or runtime.get("selectedCardId")
            or (existing or {}).get("selected_card_id")
            or (existing or {}).get("selectedCardId")
        )
        or None,
        "resume_state": _text(runtime.get("resume_state") or (existing or {}).get("resume_state"))
        or "interrupted",
        "updated_at": utc_now_iso(),
    }
    normalized = normalize_plan_runtime_recovery(payload)
    if normalized is None:
        return None
    previous = normalize_plan_runtime_recovery(existing)
    if previous and _plan_runtime_identity(previous) == _plan_runtime_identity(normalized):
        return previous
    return normalized


def bind_explicit_generated_plan_runtime(
    *,
    plan: Any,
    existing: dict[str, Any] | None = None,
    workspace_id: str = "",
    evidence_binding: str = "",
    request_id: str = "",
) -> dict[str, Any] | None:
    """Explicit generate binds THIS plan as live. Do not text-match leftover into it."""

    if plan is None:
        return None
    existing = existing if isinstance(existing, dict) else {}
    formal = _text(getattr(plan, "id", "") or getattr(plan, "plan_id", ""))
    if not formal:
        return None
    verify_raw = getattr(plan, "verify_method", None) or []
    verify_method = (
        [str(item).strip() for item in verify_raw if str(item).strip()]
        if isinstance(verify_raw, list)
        else []
    )
    next_verify_raw = getattr(plan, "next_verify_method", None) or []
    payload = {
        "revision": _revision(existing.get("revision"), 0) + 1,
        "workspace_id": workspace_id or _text(existing.get("workspace_id")),
        "request_id": request_id or _text(existing.get("request_id")) or formal,
        "plan_id": formal,
        "current_stage_id": _text(getattr(plan, "current_stage_id", "")),
        "current_step": _text(getattr(plan, "current_step", "")),
        "frozen": bool(getattr(plan, "frozen", False)),
        "blocked_reason": _text(getattr(plan, "blocked_reason", "")),
        "why_now": _text(getattr(plan, "why_now", "")),
        "verify_method": verify_method,
        "next_after_current": _text(getattr(plan, "next_after_current", "")),
        "next_why_now": _text(getattr(plan, "next_why_now", "")),
        "next_blocked_reason": _text(getattr(plan, "next_blocked_reason", "")),
        "next_verify_method": _structured_string_list(next_verify_raw),
        "evidence_binding": _text(evidence_binding) or _text(existing.get("evidence_binding")),
        "resume_state": _text(existing.get("resume_state")) or "in_progress",
        "updated_at": utc_now_iso(),
    }
    return normalize_plan_runtime_recovery(payload)


def _plan_runtime_identity(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record.get("plan_id"),
        record.get("selected_card_id"),
        record.get("current_stage_id"),
        record.get("current_step"),
        record.get("frozen"),
        record.get("blocked_reason"),
        record.get("why_now"),
        tuple(record.get("verify_method") or []),
        record.get("next_after_current"),
        record.get("next_why_now"),
        record.get("next_blocked_reason"),
        tuple(record.get("next_verify_method") or []),
        record.get("evidence_binding"),
        record.get("resume_state") or "interrupted",
        record.get("request_id"),
    )


def normalize_provider_capability_recovery(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    cleaned = strip_secrets(value)
    provider_name = _text(cleaned.get("provider_name") or cleaned.get("providerName"))
    base_url = _text(cleaned.get("base_url") or cleaned.get("baseUrl"))
    model = _text(cleaned.get("model"))
    checked_at = _text(cleaned.get("checked_at") or cleaned.get("checkedAt"))
    if not provider_name or not base_url or not model or not checked_at:
        return None
    evidence_raw = cleaned.get("capability_evidence") or cleaned.get("capabilityEvidence") or []
    evidence: list[dict[str, Any]] = []
    if isinstance(evidence_raw, list):
        for item in evidence_raw:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name"))
            state = _text(item.get("state"))
            if not name or not state:
                continue
            evidence.append(
                {
                    "name": name,
                    "declared": item.get("declared") is True,
                    "observed": item.get("observed") if isinstance(item.get("observed"), bool) else None,
                    "state": state,
                }
            )

    def verified_ready(ready_keys: tuple[str, ...], status_keys: tuple[str, ...], evidence_name: str) -> bool:
        if cleaned.get("ok") is not True:
            return False
        ready = any(cleaned.get(key) is True for key in ready_keys)
        status = any(_text(cleaned.get(key)) == "verified" for key in status_keys)
        match = next((item for item in evidence if item["name"].casefold() == evidence_name), None)
        return ready and status and match is not None and match["state"] == "verified" and match["observed"] is True

    return {
        "revision": _revision(cleaned.get("revision")),
        "workspace_id": _text(cleaned.get("workspace_id") or cleaned.get("workspaceId")) or None,
        "provider_profile_id": _text(
            cleaned.get("provider_profile_id")
            or cleaned.get("providerProfileId")
            or cleaned.get("profile_id")
            or cleaned.get("profileId")
        )
        or None,
        "provider_name": provider_name,
        "base_url": base_url,
        "model": model,
        "protocol": _text(cleaned.get("protocol")) or None,
        "ok": cleaned.get("ok") is True,
        "checked_at": checked_at,
        "tools_ready": verified_ready(("tools_ready", "toolsReady"), ("tool_probe_status", "toolProbeStatus"), "tools"),
        "tool_probe_status": _text(cleaned.get("tool_probe_status") or cleaned.get("toolProbeStatus"))
        or "unverified",
        "streaming_ready": verified_ready(
            ("streaming_ready", "streamingReady"),
            ("stream_probe_status", "streamProbeStatus"),
            "streaming",
        ),
        "stream_probe_status": _text(cleaned.get("stream_probe_status") or cleaned.get("streamProbeStatus"))
        or "unverified",
        "vision_ready": verified_ready(
            ("vision_ready", "visionReady"),
            ("vision_probe_status", "visionProbeStatus"),
            "vision",
        ),
        "vision_probe_status": _text(cleaned.get("vision_probe_status") or cleaned.get("visionProbeStatus"))
        or "unverified",
        "thinking_ready": verified_ready(
            ("thinking_ready", "thinkingReady"),
            ("thinking_probe_status", "thinkingProbeStatus"),
            "thinking",
        ),
        "thinking_probe_status": _text(cleaned.get("thinking_probe_status") or cleaned.get("thinkingProbeStatus"))
        or "unverified",
        "capability_evidence": evidence,
    }


def is_authoritative_provider_capability_success(value: Any) -> bool:
    record = normalize_provider_capability_recovery(value)
    return bool(record and record.get("ok") is True)


def normalize_streaming_checkpoint(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    request_id = _text(value.get("request_id") or value.get("requestId") or value.get("stream_id"))
    phase = _text(value.get("phase")).replace("-", "_").casefold()
    if not request_id or phase not in STREAMING_PHASES:
        return None
    return {
        "revision": _revision(value.get("revision")),
        "workspace_id": _text(value.get("workspace_id") or value.get("workspaceId")) or None,
        "provider_profile_id": _text(
            value.get("provider_profile_id")
            or value.get("providerProfileId")
            or value.get("profile_id")
            or value.get("profileId")
        )
        or None,
        "provider_name": _text(value.get("provider_name") or value.get("providerName")) or None,
        "base_url": _text(value.get("base_url") or value.get("baseUrl")) or None,
        "model": _text(value.get("model")) or None,
        "request_id": request_id,
        "checkpoint_id": _text(value.get("checkpoint_id") or value.get("checkpointId")) or None,
        "session_id": _text(value.get("session_id") or value.get("sessionId")) or None,
        "stream_message_id": _text(value.get("stream_message_id") or value.get("streamMessageId")) or None,
        "phase": phase,
        "stop_reason": _text(value.get("stop_reason") or value.get("stopReason")) or None,
        "error": _text(value.get("error")) or None,
        "updated_at": _text(value.get("updated_at") or value.get("updatedAt")) or None,
    }


def build_streaming_checkpoint(
    *,
    request_id: str,
    phase: str,
    existing: dict[str, Any] | None = None,
    checkpoint_id: str = "",
    session_id: str = "",
    stream_message_id: str = "",
    stop_reason: str = "",
    error: str = "",
    workspace_id: str = "",
    provider_profile_id: str = "",
    provider_name: str = "",
    base_url: str = "",
    model: str = "",
) -> dict[str, Any] | None:
    mapped_phase = phase.replace("-", "_").casefold()
    if mapped_phase == "failed":
        mapped_phase = "interrupted"
    if mapped_phase == "in_progress":
        mapped_phase = "streaming"
    payload = {
        "revision": _revision((existing or {}).get("revision"), 0) + 1,
        "workspace_id": workspace_id or _text((existing or {}).get("workspace_id")),
        "provider_profile_id": provider_profile_id or _text((existing or {}).get("provider_profile_id")),
        "provider_name": provider_name or _text((existing or {}).get("provider_name")),
        "base_url": base_url or _text((existing or {}).get("base_url")),
        "model": model or _text((existing or {}).get("model")),
        "request_id": request_id,
        "checkpoint_id": checkpoint_id or _text((existing or {}).get("checkpoint_id")),
        "session_id": session_id or _text((existing or {}).get("session_id")),
        "stream_message_id": stream_message_id or _text((existing or {}).get("stream_message_id")),
        "phase": mapped_phase,
        "stop_reason": stop_reason or _text((existing or {}).get("stop_reason")),
        "error": error,
        "updated_at": utc_now_iso(),
    }
    return normalize_streaming_checkpoint(payload)


def recover_streaming_checkpoint_after_restart(value: Any) -> dict[str, Any] | None:
    record = normalize_streaming_checkpoint(value)
    if record is None:
        return None
    if record["phase"] != "streaming":
        return record
    record = dict(record)
    record["phase"] = "interrupted"
    record["stop_reason"] = record.get("stop_reason") or "interrupted"
    record["revision"] = int(record.get("revision") or 1) + 1
    record["updated_at"] = utc_now_iso()
    return record


def is_completed_streaming_checkpoint(value: Any) -> bool:
    record = normalize_streaming_checkpoint(value)
    return bool(record and record.get("phase") == "completed")


def is_interrupted_streaming_checkpoint(value: Any) -> bool:
    record = normalize_streaming_checkpoint(value) or recover_streaming_checkpoint_after_restart(value)
    return bool(record and record.get("phase") in {"interrupted", "cancelled"})


def _same_identity(left: Any, right: Any) -> bool:
    first = _text(left)
    second = _text(right)
    return bool(first) and first.casefold() == second.casefold()


def stamp_produced_workspace_record(record: Any, workspace_id: str) -> Any:
    """Stamp a produced plan/task with the workspace that created it. Does not invent one."""

    if record is None:
        return None
    scope = _text(workspace_id)
    if not scope:
        return record
    existing = _text(getattr(record, "workspace_id", "") or getattr(record, "workspaceId", ""))
    if existing and existing != scope:
        return record
    if hasattr(record, "workspace_id"):
        record.workspace_id = existing or scope
    return record


def stamp_workspace_scope(record: dict[str, Any] | None, workspace_id: str) -> dict[str, Any] | None:
    if record is None:
        return None
    existing = _text(record.get("workspace_id"))
    scope = _text(workspace_id)
    if existing and scope and existing != scope:
        return None
    scoped = dict(record)
    scoped["workspace_id"] = existing or scope or None
    return scoped


def is_current_for_workspace(record: dict[str, Any] | None, workspace_id: str) -> bool:
    record_workspace_id = _text((record or {}).get("workspace_id"))
    scope_workspace_id = _text(workspace_id)
    return bool(record_workspace_id) and bool(scope_workspace_id) and record_workspace_id == scope_workspace_id


def is_current_for_provider(
    record: dict[str, Any] | None,
    *,
    workspace_id: str,
    provider_profile_id: str = "",
    provider_name: str = "",
    base_url: str = "",
    model: str = "",
) -> bool:
    if not is_current_for_workspace(record, workspace_id):
        return False
    record_profile_id = _text((record or {}).get("provider_profile_id"))
    scope_profile_id = _text(provider_profile_id)
    if scope_profile_id:
        return bool(record_profile_id) and record_profile_id == scope_profile_id
    if _text(provider_name) or _text(base_url) or _text(model):
        return (
            not record_profile_id
            and _same_identity((record or {}).get("provider_name"), provider_name)
            and _same_identity((record or {}).get("base_url"), base_url)
            and _same_identity((record or {}).get("model"), model)
        )
    return True


def select_plan_runtime_for_scope(value: Any, workspace_id: str) -> dict[str, Any] | None:
    record = normalize_plan_runtime_recovery(value)
    return record if record and is_current_for_workspace(record, workspace_id) else None


def normalize_training_chrome(value: Any) -> dict[str, Any] | None:
    """Incomplete Training chrome is not success. Unscoped title is not current truth."""

    if not isinstance(value, dict):
        return None
    workspace_id = _text(value.get("workspace_id") or value.get("workspaceId"))
    title = _text(
        value.get("selected_card_title")
        or value.get("selectedCardTitle")
        or value.get("card_title")
        or value.get("cardTitle")
        or value.get("title")
    )
    if not workspace_id and not title:
        return None
    return {
        "workspace_id": workspace_id or None,
        "selected_card_title": title or None,
        "card_title": _text(value.get("card_title") or value.get("cardTitle")) or None,
        "title": _text(value.get("title")) or None,
    }


def select_training_chrome_for_scope(value: Any, workspace_id: str) -> dict[str, Any] | None:
    record = normalize_training_chrome(value)
    return record if record and is_current_for_workspace(record, workspace_id) else None


def select_training_record_for_scope(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time fail-closed for stamped Training handoff / next hop."""

    if not isinstance(value, dict):
        return None
    return value if is_current_for_workspace(value, workspace_id) else None


def training_record_matches_workspace(value: Any, workspace_id: str) -> bool:
    """Stamped mismatch is not current. Unscoped payload may still belong to this store."""

    if not isinstance(value, dict):
        return False
    stamped = _text(value.get("workspace_id") or value.get("workspaceId"))
    if not stamped:
        return True
    scope = _text(workspace_id)
    if not scope:
        return True
    return stamped == scope


def apply_training_chrome_scope(workspace: dict[str, Any] | None, workspace_id: str) -> dict[str, Any]:
    """Drop recovered Training chrome that does not belong to this workspace."""

    payload = dict(workspace) if isinstance(workspace, dict) else {}
    handoff = payload.get("latest_training_handoff") or payload.get("latestTrainingHandoff")
    next_hop = payload.get("latest_training_next_hop") or payload.get("latestTrainingNextHop")
    chrome_source = payload.get(TRAINING_CHROME_KEY) or payload.get("latestTrainingChrome")
    handoff_record = handoff if isinstance(handoff, dict) else {}
    hop_record = next_hop if isinstance(next_hop, dict) else {}
    if not isinstance(chrome_source, dict):
        chrome_source = {
            "workspace_id": (
                _text(handoff_record.get("workspace_id") or handoff_record.get("workspaceId"))
                or _text(hop_record.get("workspace_id") or hop_record.get("workspaceId"))
            ),
            "selected_card_title": payload.get("selected_card_title") or payload.get("selectedCardTitle"),
            "card_title": handoff_record.get("card_title") or handoff_record.get("cardTitle"),
            "title": hop_record.get("title"),
        }
    chrome = select_training_chrome_for_scope(chrome_source, workspace_id)
    scoped_handoff = (
        handoff_record
        if handoff_record and training_record_matches_workspace(handoff_record, workspace_id)
        else None
    )
    scoped_hop = (
        hop_record if hop_record and training_record_matches_workspace(hop_record, workspace_id) else None
    )
    title = _text((chrome or {}).get("selected_card_title"))
    if not title and training_record_matches_workspace(chrome_source, workspace_id):
        title = _text(chrome_source.get("selected_card_title") or payload.get("selected_card_title"))
    payload[TRAINING_CHROME_KEY] = chrome
    payload["latest_training_handoff"] = scoped_handoff or None
    payload["latest_training_next_hop"] = scoped_hop or None
    payload["selected_card_title"] = title
    return payload


def evidence_item_workspace_id(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, dict):
        return _text(item.get("workspace_id") or item.get("workspaceId"))
    return _text(getattr(item, "workspace_id", "") or getattr(item, "workspaceId", ""))


def scope_evidence_items_to_workspace(items: list[Any], workspace_id: str) -> list[Any]:
    """Pending/history items from another workspace are not live here."""

    return [
        item
        for item in items
        if is_current_for_workspace({"workspace_id": evidence_item_workspace_id(item)}, workspace_id)
    ]


def _plan_identity_fields(plan: Any) -> dict[str, str]:
    if plan is None:
        return {}
    if isinstance(plan, dict):
        return {
            "workspace_id": _text(plan.get("workspace_id") or plan.get("workspaceId")),
            "id": _text(plan.get("id") or plan.get("plan_id") or plan.get("planId")),
            "title": _text(plan.get("title")),
            "summary": _text(plan.get("summary") or plan.get("objective")),
            "current_step": _text(plan.get("current_step") or plan.get("currentStep")),
        }
    return {
        "workspace_id": _text(getattr(plan, "workspace_id", "") or getattr(plan, "workspaceId", "")),
        "id": _text(getattr(plan, "id", "") or getattr(plan, "plan_id", "")),
        "title": _text(getattr(plan, "title", "")),
        "summary": _text(getattr(plan, "summary", "") or getattr(plan, "objective", "")),
        "current_step": _text(getattr(plan, "current_step", "")),
    }


def normalize_formal_plan_identity(value: Any) -> dict[str, str] | None:
    """Incomplete leftover plan identity is not current truth."""

    fields = _plan_identity_fields(value)
    if not fields:
        return None
    if not any(fields[key] for key in ("workspace_id", "id", "title", "summary", "current_step")):
        return None
    return fields


def formal_plan_identity_is_live(value: Any) -> bool:
    """Workspace stamp alone is not a live formal plan."""

    record = normalize_formal_plan_identity(value)
    if record is None:
        return False
    stages = []
    if isinstance(value, dict):
        stages = value.get("stages") or value.get("phases") or []
    else:
        stages = getattr(value, "stages", None) or getattr(value, "phases", None) or []
    stage_count = len(stages) if isinstance(stages, list) else 0
    return bool(record.get("id") or record.get("title") or record.get("summary") or record.get("current_step") or stage_count)


def select_formal_plan_for_scope(value: Any, workspace_id: str) -> dict[str, str] | None:
    record = normalize_formal_plan_identity(value)
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def select_resources_for_scope(value: Any, workspace_id: str) -> list[Any]:
    if not isinstance(value, list):
        return []
    scoped: list[Any] = []
    for item in value:
        record = item if isinstance(item, dict) else {
            "workspace_id": getattr(item, "workspace_id", "") if item is not None else "",
        }
        if training_record_matches_workspace(record, workspace_id):
            scoped.append(item)
    return scoped


def select_plan_runtime_for_pressure(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Scoped runtime usable as pressure only — never as a generated plan.

    A plan_id-only or otherwise incomplete record is stale: it must not invent
    urgency, a live plan, or a successful generate. Blocked reason or current
    step is required before the record can shrink/hold the next move.
    """

    record = select_plan_runtime_for_scope(value, workspace_id)
    if record is None:
        return None
    if not (_text(record.get("blocked_reason")) or _text(record.get("current_step"))):
        return None
    return record


def overlay_plan_runtime_display_facts(
    *,
    plan_fields: dict[str, Any],
    recovered: dict[str, Any] | None,
    plan: Any | None = None,
) -> dict[str, Any]:
    """Prefer recovered/advanced runtime what/why/next. Never invent a plan."""

    runtime = recovered if isinstance(recovered, dict) else {}
    if plan is not None:
        gated = live_plan_overlay_fields(plan=plan, runtime=runtime, existing=runtime)
        if leftover_formal_plan_is_live_for_fill(plan=plan, runtime=runtime, existing=runtime):
            return {
                "current_step": gated["current_step"] or _text(plan_fields.get("current_step")),
                "why_now": gated["why_now"] or _text(plan_fields.get("why_now")),
                "verify_method": list(gated["verify_method"])
                or [
                    str(item).strip()
                    for item in (plan_fields.get("verify_method") or [])
                    if str(item).strip()
                ],
                "blocked_reason": gated["blocked_reason"] or _text(plan_fields.get("blocked_reason")),
                "next_after_current": gated["next_after_current"]
                or _text(plan_fields.get("next_after_current")),
            }
        return gated
    runtime_step = _text(runtime.get("current_step"))
    if recovered is None or not runtime_step:
        return {
            "current_step": _text(plan_fields.get("current_step")),
            "why_now": _text(plan_fields.get("why_now")),
            "verify_method": [
                item for item in (plan_fields.get("verify_method") or []) if str(item).strip()
            ],
            "blocked_reason": _text(plan_fields.get("blocked_reason")),
            "next_after_current": _text(plan_fields.get("next_after_current")),
        }
    return {
        "current_step": runtime_step,
        "why_now": _text(recovered.get("why_now")),
        "verify_method": [item for item in (recovered.get("verify_method") or []) if str(item).strip()],
        "blocked_reason": _text(recovered.get("blocked_reason")),
        "next_after_current": _text(recovered.get("next_after_current")),
    }


def live_runtime_plan_id(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> str:
    """Plan id is live when already carried, or on first persist of a matching live plan."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    carried = _text(runtime.get("plan_id") or existing.get("plan_id"))
    formal = _text(
        getattr(plan, "id", "") or getattr(plan, "plan_id", "") if plan is not None else ""
    )
    runtime_step = _text(current_step) or _text(runtime.get("current_step"))
    existing_step = _text(existing.get("current_step"))
    existing_id = _text(existing.get("plan_id"))
    if not formal:
        return carried
    if not runtime_step:
        if runtime or existing:
            return carried if carried and carried != formal else ""
        return carried or formal
    still_on_plan = bool(
        live_runtime_stage_id(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=runtime_step,
        )
        or runtime_step == _text(getattr(plan, "current_step", ""))
    )
    if still_on_plan:
        if carried:
            return carried
        # Recovered overlay already has a step/id: do not invent leftover plan_id from text match.
        if existing_step or existing_id:
            return ""
        return formal
    if carried and carried != formal:
        return carried
    return ""


def _runtime_still_on_formal_plan(
    *,
    plan: Any | None,
    runtime: dict[str, Any],
    existing: dict[str, Any],
    current_step: str,
) -> bool:
    runtime_step = _text(current_step) or _text(runtime.get("current_step"))
    if not runtime_step:
        return not bool(runtime or existing)
    return bool(
        live_runtime_stage_id(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=runtime_step,
        )
        or runtime_step == _text(getattr(plan, "current_step", "") if plan is not None else "")
    )


def live_runtime_next_text(
    *,
    field: str,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> str:
    """Formal next-* text is live only while recovered runtime still names that plan step."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    aliases = {
        "next_why_now": (
            "next_why_now",
            "nextWhyNow",
            "why_after_current",
            "whyAfterCurrent",
        ),
        "next_blocked_reason": (
            "next_blocked_reason",
            "nextBlockedReason",
            "blocked_after_current",
            "blockedAfterCurrent",
        ),
    }.get(field, (field,))
    carried = ""
    found = False
    for source in (runtime, existing):
        for alias in aliases:
            if alias in source:
                carried = _text(source.get(alias))
                found = True
                break
        if found:
            break
    formal = _text(getattr(plan, field, "") if plan is not None else "")
    if _runtime_still_on_formal_plan(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    ):
        return carried or formal
    if carried and carried != formal:
        return carried
    return ""


def live_runtime_next_verify_method(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> list[str]:
    """Formal next verify list is live only while recovered runtime still names that plan step."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    carried: list[str] = []
    if "next_verify_method" in runtime or "nextVerifyMethod" in runtime:
        carried = _structured_string_list(
            runtime.get("next_verify_method") or runtime.get("nextVerifyMethod")
        )
    elif "next_verify_method" in existing or "nextVerifyMethod" in existing:
        carried = _structured_string_list(
            existing.get("next_verify_method") or existing.get("nextVerifyMethod")
        )
    formal = _structured_string_list(
        getattr(plan, "next_verify_method", []) if plan is not None else []
    )
    if _runtime_still_on_formal_plan(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    ):
        return carried or formal
    if carried and carried != formal:
        return carried
    return []


def live_runtime_frozen(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Formal frozen is live only while recovered runtime still names that plan step."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    formal = bool(getattr(plan, "frozen", False)) if plan is not None else False
    runtime_step = _text(current_step) or _text(runtime.get("current_step"))
    if _recovered_overlay_empty_step(runtime, existing, runtime_step):
        return False
    still_on_plan = bool(
        not runtime_step
        or live_runtime_stage_id(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=runtime_step,
        )
        or runtime_step == _text(getattr(plan, "current_step", "") if plan is not None else "")
    )
    if still_on_plan:
        if "frozen" in runtime:
            return bool(runtime.get("frozen"))
        if "frozen" in existing:
            return bool(existing.get("frozen"))
        return formal
    if "frozen" in runtime:
        return bool(runtime.get("frozen"))
    return False


def live_runtime_stage_id(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> str:
    """Stage id is live only when it still names the recovered current_step."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    current_stage = runtime.get("current_stage") if isinstance(runtime.get("current_stage"), dict) else {}
    runtime_step = _text(current_step) or _text(runtime.get("current_step"))
    runtime_has_stage = "current_stage_id" in runtime or "current_stage" in runtime
    runtime_stage = _text(runtime.get("current_stage_id") or current_stage.get("id"))
    candidate = runtime_stage if runtime_has_stage else _text(
        existing.get("current_stage_id") or getattr(plan, "current_stage_id", "")
    )
    if not runtime_step:
        if runtime or existing:
            return runtime_stage if runtime_has_stage else ""
        return candidate
    if plan is None:
        return candidate
    plan_step = _text(getattr(plan, "current_step", "") if plan is not None else "")
    stage_title = _text(current_stage.get("title"))
    stage_goal = _text(current_stage.get("goal") or current_stage.get("objective"))
    if plan is not None:
        for stage in getattr(plan, "stages", None) or []:
            stage_id = _text(getattr(stage, "id", ""))
            if stage_id and stage_id == candidate:
                stage_title = stage_title or _text(getattr(stage, "title", ""))
                stage_goal = stage_goal or _text(
                    getattr(stage, "goal", "") or getattr(stage, "objective", "")
                )
                break
        if not stage_title and not stage_goal:
            active = next(
                (
                    stage
                    for stage in (getattr(plan, "stages", None) or [])
                    if _text(getattr(stage, "id", "")) == _text(getattr(plan, "current_stage_id", ""))
                    or _text(getattr(stage, "status", "")).casefold() == "active"
                ),
                None,
            )
            if active is not None:
                stage_title = _text(getattr(active, "title", ""))
                stage_goal = _text(getattr(active, "goal", "") or getattr(active, "objective", ""))
    if runtime_step in {plan_step, stage_title, stage_goal}:
        return candidate
    return ""


def overlay_plan_runtime_current_stage(
    *,
    plan_stage: dict[str, Any] | None,
    plan_current_step: str = "",
    recovered: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Keep the plan record. Do not claim its old stage is live after runtime advances."""

    runtime_step = _text((recovered or {}).get("current_step"))
    if recovered is None or not runtime_step:
        return plan_stage
    stage = plan_stage if isinstance(plan_stage, dict) else {}
    stage_title = _text(stage.get("title"))
    stage_goal = _text(stage.get("goal") or stage.get("objective"))
    if runtime_step in {_text(plan_current_step), stage_title, stage_goal}:
        return plan_stage
    return None


def evidence_item_concepts(item: Any) -> list[str]:
    raw = getattr(item, "concepts", None)
    if raw is None and isinstance(item, dict):
        raw = item.get("concepts")
    return [_text(concept) for concept in (raw or []) if _text(concept)]


def evidence_bound_to_runtime_step(item: Any, current_step: str) -> bool:
    step = _text(current_step)
    if not step:
        return False
    if step in evidence_item_concepts(item):
        return True
    target = _text(
        getattr(item, "target_plan_stage_id", None)
        or (item.get("target_plan_stage_id") if isinstance(item, dict) else "")
    )
    return bool(target) and target == step


def scope_evidence_queue_to_runtime_step(
    *,
    pending: list[Any],
    deferred: list[Any],
    adopted: list[Any],
    rejected: list[Any],
    history: list[Any] | None = None,
    current_step: str = "",
    recovered: bool = False,
) -> dict[str, list[Any]]:
    """Live pending/adopt follow recovered current_step. Older items stay history.

    Non-bound pending items (no step binding at all) surface in the
    ``unscoped`` bucket so they stay actionable; pending items explicitly bound
    to another step stay history, as do non-bound deferred/adopted/rejected.
    """

    if not recovered or not _text(current_step):
        return {
            "pending": list(pending),
            "deferred": list(deferred),
            "adopted": list(adopted),
            "rejected": list(rejected),
            "history": list(history or []),
            "unscoped": [],
        }

    def _item_target_stage(item: Any) -> str:
        return _text(
            getattr(item, "target_plan_stage_id", None)
            or (item.get("target_plan_stage_id") if isinstance(item, dict) else "")
        )

    def _partition(
        items: list[Any], *, pending_bucket: bool = False
    ) -> tuple[list[Any], list[Any], list[Any]]:
        live: list[Any] = []
        historic: list[Any] = []
        unscoped: list[Any] = []
        for item in items:
            if evidence_bound_to_runtime_step(item, current_step):
                live.append(item)
                continue
            target_stage = _item_target_stage(item)
            if pending_bucket and not target_stage:
                # No binding at all: keep it visible as unscoped pending.
                unscoped.append(item)
            else:
                # Explicitly bound elsewhere (or non-pending): history as today.
                historic.append(item)
        return live, historic, unscoped

    live_pending, pending_history, pending_unscoped = _partition(list(pending), pending_bucket=True)
    live_deferred, deferred_history, _deferred_unscoped = _partition(list(deferred))
    live_adopted, adopted_history, _adopted_unscoped = _partition(list(adopted))
    live_rejected, rejected_history, _rejected_unscoped = _partition(list(rejected))
    historic = [
        *list(history or []),
        *pending_history,
        *deferred_history,
        *adopted_history,
        *rejected_history,
    ]
    seen: set[str] = set()
    unique_history: list[Any] = []
    for item in historic:
        item_id = _text(getattr(item, "id", "") or (item.get("id") if isinstance(item, dict) else ""))
        if item_id and item_id in seen:
            continue
        if item_id:
            seen.add(item_id)
        unique_history.append(item)
    return {
        "pending": live_pending,
        "deferred": live_deferred,
        "adopted": live_adopted,
        "rejected": live_rejected,
        "history": unique_history,
        "unscoped": pending_unscoped,
    }


def plan_runtime_status_from_recovery(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Recovery facts only: step/blocker/why/next + carried plan_id. Never invents a plan."""

    record = select_plan_runtime_for_scope(value, workspace_id)
    if record is None:
        return None
    has_pressure = bool(_text(record.get("blocked_reason")) or _text(record.get("current_step")))
    recovered_without_step = _text(record.get("resume_state")) in {"in_progress", "waiting"} and bool(
        _text(record.get("workspace_id"))
    )
    if not has_pressure and not recovered_without_step:
        return None
    current_step = _text(record.get("current_step"))
    # Carry bound plan_id so leftover_live / first-screen identity can match latest_plan_runtime.
    # Do not invent: empty when the recovery record has no plan_id (pressure-only leftover).
    return {
        "current_step": current_step,
        "current_stage_id": _text(record.get("current_stage_id")) or None if current_step else None,
        "why_now": _text(record.get("why_now")) if current_step else "",
        "verify_method": (
            [item for item in (record.get("verify_method") or []) if str(item).strip()]
            if current_step
            else []
        ),
        "blocked_reason": _text(record.get("blocked_reason")) if current_step else "",
        "next_after_current": _text(record.get("next_after_current")),
        "plan_id": _text(record.get("plan_id")) or None,
        "recovered": True,
        "current_stage": None,
        "resume_state": _text(record.get("resume_state")) or "interrupted",
        "request_id": _text(record.get("request_id")) or None,
        "revision": record.get("revision"),
        **(
            {"verify_plan_advance": dict(record["verify_plan_advance"])}
            if isinstance(record.get("verify_plan_advance"), dict)
            and record.get("verify_plan_advance")
            else {}
        ),
    }


def accept_plan_runtime_resume_request(
    requested: Any,
    *,
    recovered_status: Any,
) -> dict[str, Any] | None:
    """Bind a resume send to recovered runtime. Never invents a plan."""

    if not isinstance(requested, dict):
        return None
    action = _text(requested.get("action")).replace("-", "_")
    if action not in {"continue_step", "clear_blocker"}:
        return None
    if requested.get("recovered") is not True:
        return None
    if requested.get("formal_plan_mutation") is True or requested.get("formalPlanMutation") is True:
        return None
    status = recovered_status if isinstance(recovered_status, dict) else {}
    if status.get("recovered") is not True:
        return None
    requested_step = _text(requested.get("current_step") or requested.get("currentStep"))
    requested_blocker = _text(requested.get("blocked_reason") or requested.get("blockedReason"))
    requested_step_id = _text(requested.get("current_step_id") or requested.get("currentStepId"))
    recovered_step = _text(status.get("current_step"))
    recovered_blocker = _text(status.get("blocked_reason"))
    recovered_why = _text(status.get("why_now"))
    recovered_step_id = _text(status.get("current_stage_id") or status.get("currentStageId"))
    if action == "continue_step" and (not requested_step or requested_step != recovered_step):
        return None
    if action == "clear_blocker" and (
        not requested_blocker or requested_blocker != recovered_blocker
    ):
        return None
    if requested_step and recovered_step and requested_step != recovered_step:
        return None
    if requested_step_id and recovered_step_id and requested_step_id != recovered_step_id:
        return None
    if requested_step_id and not recovered_step_id:
        return None
    return {
        "action": action,
        "recovered": True,
        "current_step": recovered_step or None,
        "current_step_id": recovered_step_id or None,
        "blocked_reason": recovered_blocker or None,
        "why_now": recovered_why or None,
        "formal_plan_mutation": False,
    }


def accept_in_progress_plan_runtime_turn(
    *,
    intent: str,
    formal_plan_mutation: bool,
    recovered_status: Any,
) -> dict[str, Any] | None:
    """Bind a later plan-intent turn to in-progress runtime. Never invents a plan."""

    if formal_plan_mutation:
        return None
    if _text(intent).lower() != "plan":
        return None
    status = recovered_status if isinstance(recovered_status, dict) else {}
    if status.get("recovered") is not True:
        return None
    current_step = _text(status.get("current_step") or status.get("currentStep"))
    blocked_reason = _text(status.get("blocked_reason") or status.get("blockedReason"))
    if not current_step and not blocked_reason:
        return None
    return {
        "action": "clear_blocker" if blocked_reason else "continue_step",
        "recovered": True,
        "current_step": current_step or None,
        "current_step_id": _text(status.get("current_stage_id") or status.get("currentStageId")) or None,
        "blocked_reason": blocked_reason or None,
        "why_now": _text(status.get("why_now") or status.get("whyNow")) or None,
        "formal_plan_mutation": False,
    }


STRUCTURED_STEP_FINISHED_TOKENS = frozenset({"verify", "waiting"})
STRUCTURED_STEP_FINISHED_KEYS = (
    "decision",
    "learning_phase",
    "learningPhase",
    "training_learning_phase",
    "trainingLearningPhase",
    "training_phase",
    "trainingPhase",
    "step_status",
    "stepStatus",
    "plan_step_status",
    "planStepStatus",
)


def _structured_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = [_text(item) for item in value]
    return [item for item in items if item]


def extract_structured_verify_method(agent_meta: Any) -> list[str]:
    """Copy structured verify/evidence lists only. Never invent tests or files."""

    if not isinstance(agent_meta, dict):
        return []
    for key in ("verify_method", "verifyMethod", "verification"):
        items = _structured_string_list(agent_meta.get(key))
        if items:
            return items
    return _structured_string_list(agent_meta.get("evidence"))


def structured_plan_step_finished(agent_meta: Any) -> bool:
    """Finish only from exact existing tokens. Never guess from prose."""

    if not isinstance(agent_meta, dict):
        return False
    for key in STRUCTURED_STEP_FINISHED_KEYS:
        token = _text(agent_meta.get(key)).replace("-", "_").casefold()
        if token in STRUCTURED_STEP_FINISHED_TOKENS:
            return True
    return False


def extract_structured_next_step_runtime_facts(value: Any) -> dict[str, Any]:
    """Facts bound to next_after_current only. Never reuse current-step why/blocker/verify or prose."""

    if not isinstance(value, dict):
        return {}
    why_now = _text(
        value.get("next_why_now")
        or value.get("nextWhyNow")
        or value.get("why_after_current")
        or value.get("whyAfterCurrent")
    )
    blocked_reason = _text(
        value.get("next_blocked_reason")
        or value.get("nextBlockedReason")
        or value.get("blocked_after_current")
        or value.get("blockedAfterCurrent")
    )
    verify_method = _structured_string_list(
        value.get("next_verify_method") or value.get("nextVerifyMethod")
    )
    facts: dict[str, Any] = {}
    if why_now:
        facts["why_now"] = why_now
    if blocked_reason:
        facts["blocked_reason"] = blocked_reason
    if verify_method:
        facts["verify_method"] = verify_method
    return facts


def extract_structured_plan_runtime_facts(agent_meta: Any) -> dict[str, Any] | None:
    """Authoritative next/blocker/why/next/verify only. Never parse reply prose."""

    if not isinstance(agent_meta, dict):
        return None
    current_step = _text(agent_meta.get("next_step") or agent_meta.get("nextStep"))
    blocked_reason = _text(
        agent_meta.get("blocker") or agent_meta.get("blocked_reason") or agent_meta.get("blockedReason")
    )
    why_now = _text(
        agent_meta.get("summary")
        or agent_meta.get("teaching_goal")
        or agent_meta.get("teachingGoal")
        or agent_meta.get("why_now")
        or agent_meta.get("whyNow")
    )
    next_after_current = _text(
        agent_meta.get("next_after_current") or agent_meta.get("nextAfterCurrent")
    )
    verify_method = extract_structured_verify_method(agent_meta)
    next_facts = extract_structured_next_step_runtime_facts(agent_meta)
    finished = structured_plan_step_finished(agent_meta)
    if (
        not current_step
        and not blocked_reason
        and not why_now
        and not next_after_current
        and not verify_method
        and not next_facts
        and not finished
    ):
        return None
    facts: dict[str, Any] = {}
    if current_step:
        facts["current_step"] = current_step
    if blocked_reason:
        facts["blocked_reason"] = blocked_reason
    if why_now:
        facts["why_now"] = why_now
    if next_after_current:
        facts["next_after_current"] = next_after_current
    if verify_method:
        facts["verify_method"] = verify_method
    if next_facts.get("why_now"):
        facts["next_why_now"] = next_facts["why_now"]
    if next_facts.get("blocked_reason"):
        facts["next_blocked_reason"] = next_facts["blocked_reason"]
    if next_facts.get("verify_method"):
        facts["next_verify_method"] = next_facts["verify_method"]
    if finished:
        facts["resume_state"] = "waiting"
    return facts


RESUME_FAILURE_STOP_REASONS = frozenset(
    {
        "empty_response",
        "language_corruption",
        "language_corruption_recovered",
        "max_steps",
        "no_progress",
        "provider_error",
        "invalid_key_or_permission",
        "model_unsupported",
        "model_not_found",
        "malformed_response",
        "truncated_or_empty",
        "rate_limit",
        "timeout",
        "network",
        "unknown",
    }
)


def recovered_resume_turn_succeeded(
    *,
    reply_content: str,
    stop_reason: str = "",
) -> bool:
    if not _text(reply_content):
        return False
    reason = _text(stop_reason)
    return reason not in RESUME_FAILURE_STOP_REASONS and not reason.startswith("agent_error")


def build_plan_runtime_resume(
    *,
    existing: Any,
    accepted: Any,
    request_id: str,
    workspace_id: str,
    reply_facts: Any = None,
) -> dict[str, Any] | None:
    """Stamp a successful resume onto scoped runtime. Never invents a plan."""

    current = normalize_plan_runtime_recovery(existing)
    if current is None or not is_current_for_workspace(current, workspace_id):
        return None
    if not _text(request_id):
        return None
    accepted_recovery = accepted if isinstance(accepted, dict) else {}
    if accepted_recovery.get("recovered") is not True:
        return None
    if accepted_recovery.get("formal_plan_mutation") is True:
        return None
    action = _text(accepted_recovery.get("action")).replace("-", "_")
    if action not in {"continue_step", "clear_blocker"}:
        return None
    facts = reply_facts if isinstance(reply_facts, dict) else {}
    current_step = _text(facts.get("current_step") or facts.get("currentStep")) or (
        accepted_recovery.get("current_step") or current.get("current_step")
    )
    blocked_reason = _text(facts.get("blocked_reason") or facts.get("blockedReason")) or (
        accepted_recovery.get("blocked_reason") or current.get("blocked_reason")
    )
    why_now = _text(facts.get("why_now") or facts.get("whyNow")) or (
        accepted_recovery.get("why_now") or current.get("why_now")
    )
    next_after_current = _text(facts.get("next_after_current") or facts.get("nextAfterCurrent")) or (
        current.get("next_after_current")
    )
    verify_raw = facts.get("verify_method") or facts.get("verifyMethod")
    verify_method = _structured_string_list(verify_raw) or list(current.get("verify_method") or [])
    next_why_now = _text(facts.get("next_why_now") or facts.get("nextWhyNow")) or _text(
        current.get("next_why_now")
    )
    next_blocked_reason = _text(
        facts.get("next_blocked_reason") or facts.get("nextBlockedReason")
    ) or _text(current.get("next_blocked_reason"))
    next_verify_method = _structured_string_list(
        facts.get("next_verify_method") or facts.get("nextVerifyMethod")
    ) or list(current.get("next_verify_method") or [])
    finished = _text(facts.get("resume_state") or facts.get("resumeState")).replace("-", "_") == "waiting"
    return build_plan_runtime_recovery(
        plan=None,
        plan_runtime={
            "current_step": current_step,
            "current_stage_id": accepted_recovery.get("current_step_id")
            or current.get("current_stage_id"),
            "blocked_reason": blocked_reason,
            "why_now": why_now,
            "verify_method": verify_method,
            "next_after_current": next_after_current,
            "next_why_now": next_why_now,
            "next_blocked_reason": next_blocked_reason,
            "next_verify_method": next_verify_method,
            "resume_state": "waiting" if finished else "in_progress",
        },
        existing=current,
        request_id=request_id,
        workspace_id=workspace_id,
    )


def _evidence_field(evidence: Any, *keys: str) -> Any:
    if evidence is None:
        return None
    if isinstance(evidence, dict):
        for key in keys:
            if key in evidence:
                return evidence.get(key)
        return None
    for key in keys:
        if hasattr(evidence, key):
            return getattr(evidence, key)
    return None


def verified_adopt_allows_runtime_advance(evidence: Any) -> bool:
    """Authoritative verify ack only: adopted pass + verified. Never guess from prose."""

    if evidence is None:
        return False
    adopted = _evidence_field(evidence, "adopted")
    if adopted is not True:
        return False
    if _evidence_field(evidence, "rejected_at", "rejectedAt"):
        return False
    outcome = _text(_evidence_field(evidence, "outcome")).casefold()
    verified = _evidence_field(evidence, "verified") is True
    return outcome == "pass" and verified


WAITING_VERIFY_EVIDENCE_SOURCE = "plan_runtime_verify"


def build_waiting_verify_evidence(
    *,
    runtime: Any,
    workspace_id: str,
) -> dict[str, Any] | None:
    """One pending verify item from structured facts only. Never invents methods."""

    current = normalize_plan_runtime_recovery(runtime)
    if current is None or not is_current_for_workspace(current, workspace_id):
        return None
    if _text(current.get("resume_state")).replace("-", "_") != "waiting":
        return None
    current_step = _text(current.get("current_step"))
    verify_method = [item for item in (current.get("verify_method") or []) if _text(item)]
    if not current_step or not verify_method:
        return None
    method = verify_method[0]
    return {
        "summary": method,
        "source": WAITING_VERIFY_EVIDENCE_SOURCE,
        "concepts": [current_step],
        "outcome": "partial",
        "verification_source": method,
        "target_plan_stage_id": _text(current.get("current_stage_id")),
    }


def build_waiting_composer_evidence(
    *,
    runtime: Any,
    workspace_id: str,
    submitted_text: str,
    pending_count: int = 0,
) -> dict[str, Any] | None:
    """One pending item from composer text + current step. Never invents methods."""

    current = normalize_plan_runtime_recovery(runtime)
    if current is None or not is_current_for_workspace(current, workspace_id):
        return None
    if _text(current.get("resume_state")).replace("-", "_") != "waiting":
        return None
    current_step = _text(current.get("current_step"))
    if not current_step:
        return None
    if pending_count > 0:
        return None
    submitted = _text(submitted_text)
    if not submitted:
        return None
    return {
        "summary": submitted,
        "source": WAITING_VERIFY_EVIDENCE_SOURCE,
        "concepts": [current_step],
        "outcome": "partial",
        "verification_source": submitted,
        "target_plan_stage_id": _text(current.get("current_stage_id")),
    }


def attest_waiting_verify_on_adopt(evidence: Any) -> dict[str, Any]:
    """Adopt is the verify ack. Do not invent files, tests, or results."""

    if _text(_evidence_field(evidence, "source")) != WAITING_VERIFY_EVIDENCE_SOURCE:
        return {}
    method = _text(
        _evidence_field(evidence, "verification_source", "verificationSource")
    ) or _text(_evidence_field(evidence, "summary"))
    updates: dict[str, Any] = {
        "verified": True,
        "verification_source": method or WAITING_VERIFY_EVIDENCE_SOURCE,
    }
    if _text(_evidence_field(evidence, "outcome")).casefold() not in {"fail", "failed"}:
        updates["outcome"] = "pass"
    return updates


def build_plan_runtime_advance_after_adopt(
    *,
    existing: Any,
    evidence: Any,
    request_id: str,
    workspace_id: str,
) -> dict[str, Any] | None:
    """Advance recovered runtime after verified adopt. Never invents a plan or next step."""

    current = normalize_plan_runtime_recovery(existing)
    if current is None or not is_current_for_workspace(current, workspace_id):
        return None
    resume_state = _text(current.get("resume_state")).replace("-", "_")
    evidence_source = _text(_evidence_field(evidence, "source")).casefold()
    waiting = resume_state == "waiting"
    return_evidence = resume_state == "in_progress" and evidence_source == "training_handoff_return"
    if not waiting and not return_evidence:
        return None
    if not _text(request_id):
        return None
    if not verified_adopt_allows_runtime_advance(evidence):
        return None
    next_step = _text(current.get("next_after_current"))
    if not next_step:
        return None
    next_facts = extract_structured_next_step_runtime_facts(current)
    record = build_plan_runtime_recovery(
        plan=None,
        plan_runtime={
            "current_step": next_step,
            "current_stage_id": "",
            "blocked_reason": next_facts.get("blocked_reason") or "",
            "why_now": next_facts.get("why_now") or "",
            "verify_method": list(next_facts.get("verify_method") or []),
            "next_after_current": "",
            "next_why_now": "",
            "next_blocked_reason": "",
            "next_verify_method": [],
            "resume_state": "in_progress",
        },
        existing=current,
        evidence_binding="",
        replace_evidence_binding=True,
        request_id=request_id,
        workspace_id=workspace_id,
    )
    if record is None:
        return None
    # Preserve only a live selected card id. A plan's next step is not a card id.
    carried_card_id = _text(record.get("selected_card_id") or record.get("selectedCardId"))
    prior_step = _text(current.get("current_step"))
    new_step = _text(record.get("current_step"))
    if carried_card_id and carried_card_id in {prior_step, new_step, next_step}:
        record = {**record, "selected_card_id": None}
    return record


def build_plan_runtime_advance_after_verify(
    *,
    plan: Any,
    existing: Any,
    workspace_id: str,
    request_id: str = "",
) -> dict[str, Any] | None:
    """Sync recovered runtime to an already-advanced formal plan after evaluator verify.

    Fail-closed: only when existing runtime already carries this plan_id and had a
    live current_step. Never mints a second plan or invents a step without formal text.
    """

    if plan is None:
        return None
    current = normalize_plan_runtime_recovery(existing)
    if current is None or not is_current_for_workspace(current, workspace_id):
        return None
    formal = _text(getattr(plan, "id", "") or getattr(plan, "plan_id", ""))
    if not formal:
        return None
    if _text(current.get("plan_id")) != formal:
        return None
    if not _text(current.get("current_step")):
        return None
    new_step = _text(getattr(plan, "current_step", ""))
    if not new_step:
        return None
    verify_raw = getattr(plan, "verify_method", None) or []
    verify_method = (
        [str(item).strip() for item in verify_raw if str(item).strip()]
        if isinstance(verify_raw, list)
        else []
    )
    next_verify_raw = getattr(plan, "next_verify_method", None) or []
    # Preserve only an already-stamped card id field. Never invent from title / current_step.
    # Persist layer re-stamps via live_selected_training_card_id (fail-closed).
    carried_card_id = _text(current.get("selected_card_id") or current.get("selectedCardId"))
    if carried_card_id and carried_card_id == new_step:
        carried_card_id = ""
    if carried_card_id and carried_card_id == _text(current.get("current_step")):
        carried_card_id = ""
    payload = {
        "revision": _revision(current.get("revision"), 0) + 1,
        "workspace_id": workspace_id or _text(current.get("workspace_id")),
        "request_id": request_id or _text(current.get("request_id")) or formal,
        "plan_id": formal,
        "selected_card_id": carried_card_id or None,
        "current_stage_id": _text(getattr(plan, "current_stage_id", "")),
        "current_step": new_step,
        "frozen": bool(getattr(plan, "frozen", False)),
        "blocked_reason": _text(getattr(plan, "blocked_reason", "")),
        "why_now": _text(getattr(plan, "why_now", "")),
        "verify_method": verify_method,
        "next_after_current": _text(getattr(plan, "next_after_current", "")),
        "next_why_now": _text(getattr(plan, "next_why_now", "")),
        "next_blocked_reason": _text(getattr(plan, "next_blocked_reason", "")),
        "next_verify_method": _structured_string_list(next_verify_raw),
        "evidence_binding": _text(current.get("evidence_binding")),
        "resume_state": _text(current.get("resume_state")) or "in_progress",
        "updated_at": utc_now_iso(),
    }
    return normalize_plan_runtime_recovery(payload)


def select_provider_capability_for_scope(
    value: Any,
    *,
    workspace_id: str,
    provider_profile_id: str = "",
    provider_name: str = "",
    base_url: str = "",
    model: str = "",
) -> dict[str, Any] | None:
    record = normalize_provider_capability_recovery(value)
    if record and is_current_for_provider(
        record,
        workspace_id=workspace_id,
        provider_profile_id=provider_profile_id,
        provider_name=provider_name,
        base_url=base_url,
        model=model,
    ):
        return record
    return None


def select_streaming_checkpoint_for_scope(
    value: Any,
    *,
    workspace_id: str,
    provider_profile_id: str = "",
    provider_name: str = "",
    base_url: str = "",
    model: str = "",
) -> dict[str, Any] | None:
    record = recover_streaming_checkpoint_after_restart(value)
    if record and is_current_for_provider(
        record,
        workspace_id=workspace_id,
        provider_profile_id=provider_profile_id,
        provider_name=provider_name,
        base_url=base_url,
        model=model,
    ):
        return record
    return None


def _model_payload(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else None
    if isinstance(value, dict):
        return dict(value)
    return None


def normalize_latest_current_task(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    payload = _model_payload(value)
    if payload is None:
        return None
    title = _text(payload.get("title"))
    task_id = _text(payload.get("id"))
    goal = _text(payload.get("natural_language_goal") or payload.get("naturalLanguageGoal"))
    if not title and not task_id and not goal:
        return None
    cleaned = strip_secrets(payload)
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def normalize_latest_affect_state(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    payload = _model_payload(value)
    if payload is None:
        return None
    urgency = _text(payload.get("urgency_level") or payload.get("urgencyLevel")).casefold()
    if urgency not in {"low", "medium", "high"}:
        return None
    body = {
        "urgency_level": urgency,
        "recovery_signal": _text(payload.get("recovery_signal") or payload.get("recoverySignal"))
        or "steady",
        "frustration_level": payload.get("frustration_level", payload.get("frustrationLevel", 0.0)),
        "confidence_level": payload.get("confidence_level", payload.get("confidenceLevel", 0.5)),
        "momentum_level": payload.get("momentum_level", payload.get("momentumLevel", 0.5)),
        "needs_reassurance": bool(payload.get("needs_reassurance", payload.get("needsReassurance", False))),
    }
    existing_scope = _text(payload.get("workspace_id") or payload.get("workspaceId"))
    if adopt_scope and workspace_id:
        body["workspace_id"] = workspace_id
    elif existing_scope:
        body["workspace_id"] = existing_scope
    record = stamp_workspace_scope(body, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_current_task(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_current_task(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def apply_current_task_scope(workspace: dict[str, Any] | None, workspace_id: str) -> dict[str, Any]:
    """Drop recovered current_task chrome that does not belong to this workspace."""

    payload = dict(workspace) if isinstance(workspace, dict) else {}
    scoped = select_latest_current_task(
        payload.get(CURRENT_TASK_KEY)
        or payload.get("latestCurrentTask")
        or payload.get("current_task")
        or payload.get("currentTask"),
        workspace_id,
    )
    payload[CURRENT_TASK_KEY] = scoped
    if "latestCurrentTask" in payload:
        payload["latestCurrentTask"] = scoped
    if "current_task" in payload:
        payload["current_task"] = scoped
    if "currentTask" in payload:
        payload["currentTask"] = scoped
    return payload


def select_latest_affect_state(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_affect_state(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def normalize_latest_tone_decision(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    """Incomplete leftover toneDecision is not current truth."""

    payload = _model_payload(value)
    if payload is None:
        return None
    tone = _text(payload.get("tone"))
    verbosity_bias = _text(payload.get("verbosity_bias") or payload.get("verbosityBias"))
    acknowledge_progress = payload.get("acknowledge_progress", payload.get("acknowledgeProgress"))
    avoid_overwhelm = payload.get("avoid_overwhelm", payload.get("avoidOverwhelm"))
    has_acknowledge = isinstance(acknowledge_progress, bool)
    has_avoid = isinstance(avoid_overwhelm, bool)
    if not tone and not verbosity_bias and not has_acknowledge and not has_avoid:
        return None
    cleaned = {
        "tone": tone,
        "verbosity_bias": verbosity_bias,
        "acknowledge_progress": bool(acknowledge_progress) if has_acknowledge else False,
        "avoid_overwhelm": bool(avoid_overwhelm) if has_avoid else False,
        "workspace_id": _text(payload.get("workspace_id") or payload.get("workspaceId")),
    }
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_tone_decision(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_tone_decision(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def apply_affect_tone_scope(workspace: dict[str, Any] | None, workspace_id: str) -> dict[str, Any]:
    """Drop recovered affect / tone chrome that does not belong to this workspace."""

    payload = dict(workspace) if isinstance(workspace, dict) else {}
    payload[AFFECT_STATE_KEY] = select_latest_affect_state(
        payload.get(AFFECT_STATE_KEY) or payload.get("latestAffectState"),
        workspace_id,
    )
    payload[TONE_DECISION_KEY] = select_latest_tone_decision(
        payload.get(TONE_DECISION_KEY) or payload.get("latestToneDecision"),
        workspace_id,
    )
    return payload


def normalize_latest_coaching_focus(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    """Incomplete leftover coaching/focus is not current truth."""

    payload = _model_payload(value)
    if payload is None:
        return None
    summary = _text(
        payload.get("summary") or payload.get("latest_coach_summary") or payload.get("latestCoachSummary")
    )
    next_step = _text(
        payload.get("next_step")
        or payload.get("nextStep")
        or payload.get("latest_coach_next_step")
        or payload.get("latestCoachNextStep")
    )
    focus_area = _text(
        payload.get("focus_area")
        or payload.get("focusArea")
        or payload.get("current_focus")
        or payload.get("currentFocus")
        or payload.get("latest_coach_focus_area")
        or payload.get("latestCoachFocusArea")
    )
    teaching_goal = _text(
        payload.get("teaching_goal")
        or payload.get("teachingGoal")
        or payload.get("latest_teaching_goal")
        or payload.get("latestTeachingGoal")
    )
    if not summary and not next_step and not focus_area and not teaching_goal:
        return None
    cleaned = {
        "summary": summary,
        "next_step": next_step,
        "focus_area": focus_area,
        "teaching_goal": teaching_goal,
        "workspace_id": _text(payload.get("workspace_id") or payload.get("workspaceId")),
    }
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_coaching_focus(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_coaching_focus(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def apply_coaching_focus_scope(workspace: dict[str, Any] | None, workspace_id: str) -> dict[str, Any]:
    """Drop recovered coaching/focus chrome that does not belong to this workspace."""

    payload = dict(workspace) if isinstance(workspace, dict) else {}
    scoped = select_latest_coaching_focus(
        payload.get(COACHING_FOCUS_KEY) or payload.get("latestCoachingFocus"),
        workspace_id,
    )
    payload[COACHING_FOCUS_KEY] = scoped
    payload[COACH_FOCUS_KEY] = select_latest_coach_focus(
        payload.get(COACH_FOCUS_KEY) or payload.get("latestCoachFocus"),
        workspace_id,
    )
    payload[COACH_TURN_KEY] = select_latest_coach_turn(
        payload.get(COACH_TURN_KEY) or payload.get("latestCoachTurn"),
        workspace_id,
    )
    payload[NEXT_STEP_HINT_KEY] = select_latest_next_step_hint(
        payload.get(NEXT_STEP_HINT_KEY) or payload.get("latestNextStepHint"),
        workspace_id,
    )
    payload[COACHING_ADAPTATION_KEY] = select_latest_coaching_adaptation(
        payload.get(COACHING_ADAPTATION_KEY) or payload.get("latestCoachingAdaptation"),
        workspace_id,
    )
    return payload


def normalize_latest_coach_focus(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    """Incomplete leftover coachFocus is not current truth."""

    payload = _model_payload(value)
    if payload is None:
        return None
    current_focus = _text(payload.get("current_focus") or payload.get("currentFocus"))
    recommended = _text(
        payload.get("first_turn_priority")
        or payload.get("firstTurnPriority")
        or payload.get("next_step")
        or payload.get("nextStep")
    )
    summary = _text(
        payload.get("continuity_summary")
        or payload.get("continuitySummary")
        or payload.get("strategy_preference_summary")
        or payload.get("strategyPreferenceSummary")
    )
    next_step = _text(payload.get("next_step") or payload.get("nextStep"))
    first_turn_priority = _text(
        payload.get("first_turn_priority") or payload.get("firstTurnPriority")
    )
    if not current_focus and not recommended and not summary:
        return None
    cleaned = {
        "current_focus": current_focus,
        "next_step": next_step,
        "first_turn_priority": first_turn_priority,
        "continuity_summary": _text(
            payload.get("continuity_summary") or payload.get("continuitySummary")
        ),
        "strategy_preference_summary": _text(
            payload.get("strategy_preference_summary") or payload.get("strategyPreferenceSummary")
        ),
        "workspace_id": _text(payload.get("workspace_id") or payload.get("workspaceId")),
    }
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_coach_focus(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_coach_focus(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def normalize_latest_coach_turn(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    """Incomplete leftover coachTurn is not current truth."""

    payload = _model_payload(value)
    if payload is None:
        return None
    summary = _text(payload.get("summary"))
    next_step = _text(payload.get("next_step") or payload.get("nextStep"))
    teaching_goal = _text(payload.get("teaching_goal") or payload.get("teachingGoal"))
    if not summary and not next_step and not teaching_goal:
        return None
    cleaned = {
        "summary": summary,
        "next_step": next_step,
        "teaching_goal": teaching_goal,
        "workspace_id": _text(payload.get("workspace_id") or payload.get("workspaceId")),
    }
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_coach_turn(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_coach_turn(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def normalize_latest_next_step_hint(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    """Incomplete leftover nextStepHint is not current truth."""

    payload = _model_payload(value)
    if payload is None:
        return None
    title = _text(
        payload.get("title") or payload.get("label") or payload.get("next_step") or payload.get("nextStep")
    )
    summary = _text(payload.get("summary") or payload.get("detail"))
    recommended_action = _text(
        payload.get("recommended_action") or payload.get("recommendedAction")
    )
    if not title and not summary and not recommended_action:
        return None
    cleaned = {
        "title": title,
        "summary": summary,
        "recommended_action": recommended_action,
        "workspace_id": _text(payload.get("workspace_id") or payload.get("workspaceId")),
    }
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_next_step_hint(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_next_step_hint(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def normalize_latest_coaching_adaptation(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    """Incomplete leftover coachingAdaptation is not current truth."""

    payload = _model_payload(value)
    if payload is None:
        return None
    summary = _text(payload.get("summary"))
    evidence = [
        item
        for item in (payload.get("evidence") or [])
        if _text(item)
    ] if isinstance(payload.get("evidence"), list) else []
    if not summary and not evidence:
        return None
    cleaned = {
        "summary": summary,
        "evidence": evidence,
        "workspace_id": _text(payload.get("workspace_id") or payload.get("workspaceId")),
    }
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_coaching_adaptation(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_coaching_adaptation(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def normalize_latest_evaluation(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    """Incomplete leftover evaluation is not current truth."""

    payload = _model_payload(value)
    if payload is None:
        return None
    summary = _text(
        payload.get("summary")
        or payload.get("latest_evaluation_feedback")
        or payload.get("latestEvaluationFeedback")
    )
    next_step = _text(
        payload.get("next_step")
        or payload.get("nextStep")
        or payload.get("latest_evaluation_next_step")
        or payload.get("latestEvaluationNextStep")
    )
    headline = _text(payload.get("headline"))
    if not summary and not next_step and not headline:
        return None
    cleaned = {
        "summary": summary,
        "next_step": next_step,
        "headline": headline,
        "workspace_id": _text(payload.get("workspace_id") or payload.get("workspaceId")),
    }
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_evaluation(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_evaluation(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def normalize_latest_learner_state(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    """Incomplete leftover learnerState is not current truth."""

    payload = _model_payload(value)
    if payload is None:
        return None
    active_focus = _text(payload.get("active_focus") or payload.get("activeFocus"))
    evidence = [
        item
        for item in (payload.get("evidence") or [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(payload.get("evidence"), list) else []
    if not active_focus and not evidence:
        return None
    cleaned = {
        "active_focus": active_focus,
        "evidence": evidence,
        "workspace_id": _text(payload.get("workspace_id") or payload.get("workspaceId")),
    }
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_learner_state(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_learner_state(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def normalize_latest_teaching_decision(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    """Incomplete leftover teachingDecision is not current truth."""

    payload = _model_payload(value)
    if payload is None:
        return None
    reason = _text(payload.get("reason"))
    primary_goal = _text(payload.get("primary_goal") or payload.get("primaryGoal"))
    teaching_strategy = _text(payload.get("teaching_strategy") or payload.get("teachingStrategy"))
    closing_move = _text(payload.get("closing_move") or payload.get("closingMove"))
    focus_area = _text(payload.get("focus_area") or payload.get("focusArea"))
    if not reason and not primary_goal and not teaching_strategy and not closing_move:
        return None
    cleaned = {
        "reason": reason,
        "primary_goal": primary_goal,
        "teaching_strategy": teaching_strategy,
        "closing_move": closing_move,
        "focus_area": focus_area,
        "workspace_id": _text(payload.get("workspace_id") or payload.get("workspaceId")),
    }
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_teaching_decision(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_teaching_decision(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def apply_evaluation_chrome_scope(workspace: dict[str, Any] | None, workspace_id: str) -> dict[str, Any]:
    """Drop recovered evaluation / learner / teaching chrome that does not belong here."""

    payload = dict(workspace) if isinstance(workspace, dict) else {}
    payload[EVALUATION_KEY] = select_latest_evaluation(
        payload.get(EVALUATION_KEY) or payload.get("latestEvaluation"),
        workspace_id,
    )
    payload[LEARNER_STATE_KEY] = select_latest_learner_state(
        payload.get(LEARNER_STATE_KEY) or payload.get("latestLearnerState"),
        workspace_id,
    )
    payload[TEACHING_DECISION_KEY] = select_latest_teaching_decision(
        payload.get(TEACHING_DECISION_KEY) or payload.get("latestTeachingDecision"),
        workspace_id,
    )
    return payload


def normalize_latest_adaptation_guide(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    """Incomplete leftover adaptation guide is not current truth."""

    payload = _model_payload(value)
    if payload is None:
        return None
    target_outcome = _text(payload.get("target_outcome") or payload.get("targetOutcome"))
    first_migration_step = _text(
        payload.get("first_migration_step") or payload.get("firstMigrationStep")
    )
    if not target_outcome and not first_migration_step:
        return None
    cleaned = {
        "target_outcome": target_outcome,
        "first_migration_step": first_migration_step,
        "workspace_id": _text(payload.get("workspace_id") or payload.get("workspaceId")),
    }
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_adaptation_guide(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_adaptation_guide(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def normalize_latest_principle_notes(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    """Incomplete leftover principle notes are not current truth."""

    payload = _model_payload(value)
    if payload is None:
        return None
    current_principle = _text(payload.get("current_principle") or payload.get("currentPrinciple"))
    why_it_matters = _text(
        payload.get("why_it_matters")
        or payload.get("whyItMatters")
        or payload.get("why_this_approach")
    )
    apply_now = _text(
        payload.get("apply_now") or payload.get("applyNow") or payload.get("follow_up_exercise")
    )
    if not current_principle and not why_it_matters and not apply_now:
        return None
    cleaned = {
        "current_principle": current_principle,
        "why_it_matters": why_it_matters,
        "apply_now": apply_now,
        "workspace_id": _text(payload.get("workspace_id") or payload.get("workspaceId")),
    }
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_principle_notes(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_principle_notes(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def normalize_latest_project_sources(
    value: Any,
    workspace_id: str = "",
    *,
    adopt_scope: bool = False,
) -> dict[str, Any] | None:
    """Incomplete leftover project sources are not current truth."""

    payload = _model_payload(value)
    items = value if isinstance(value, list) else (payload or {}).get("sources")
    if payload is None and not isinstance(value, list):
        return None
    sources: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        source = _model_payload(item)
        if source is None:
            continue
        title = _text(source.get("title"))
        fit_reason = _text(source.get("fit_reason") or source.get("fitReason"))
        if not title and not fit_reason:
            continue
        sources.append({"title": title, "fit_reason": fit_reason})
    if not sources:
        return None
    cleaned = {
        "sources": sources,
        "workspace_id": _text((payload or {}).get("workspace_id") or (payload or {}).get("workspaceId")),
    }
    if adopt_scope and workspace_id:
        cleaned["workspace_id"] = workspace_id
    record = stamp_workspace_scope(cleaned, workspace_id)
    if record is None:
        return None
    if workspace_id and not is_current_for_workspace(record, workspace_id):
        return None
    return record


def select_latest_project_sources(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time: unscoped leftover is not current for another workspace."""

    record = normalize_latest_project_sources(value, "")
    if record is None:
        return None
    return record if is_current_for_workspace(record, workspace_id) else None


def apply_teaching_artifact_scope(workspace: dict[str, Any] | None, workspace_id: str) -> dict[str, Any]:
    """Drop recovered adaptation / sources / principle chrome that does not belong here."""

    payload = dict(workspace) if isinstance(workspace, dict) else {}
    payload[ADAPTATION_GUIDE_KEY] = select_latest_adaptation_guide(
        payload.get(ADAPTATION_GUIDE_KEY) or payload.get("latestAdaptationGuide"),
        workspace_id,
    )
    payload[PROJECT_SOURCES_KEY] = select_latest_project_sources(
        payload.get(PROJECT_SOURCES_KEY) or payload.get("latestProjectSources"),
        workspace_id,
    )
    payload[PRINCIPLE_NOTES_KEY] = select_latest_principle_notes(
        payload.get(PRINCIPLE_NOTES_KEY) or payload.get("latestPrincipleNotes"),
        workspace_id,
    )
    return payload
