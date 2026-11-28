"""Fail-closed workspace recovery for plan, provider last-test, and streams.

These records live on structured workspace memory — the same DB path as
training reliability, coach orientation, and transfer state. Incomplete
records are never treated as success. API keys are never stored.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...core.workspace_live_identity import (
    _recovered_overlay_empty_step as _recovered_overlay_empty_step,
)
from ...core.workspace_live_identity import (
    formal_plan_is_live_runtime_identity as formal_plan_is_live_runtime_identity,
)
from ...core.workspace_live_identity import (
    formal_task_is_live_runtime_identity as formal_task_is_live_runtime_identity,
)
from ...core.workspace_live_identity import (
    is_formal_plan_live_for_fill as leftover_formal_plan_is_live_for_fill,
)
from ...core.workspace_live_identity import (
    stale_formal_training_labels as leftover_formal_training_labels,
)
from ...core.workspace_scope_runtime import (
    PLAN_RUNTIME_KEY as PLAN_RUNTIME_KEY,
)
from ...core.workspace_scope_runtime import (
    PROVIDER_CAPABILITY_KEY as PROVIDER_CAPABILITY_KEY,
)
from ...core.workspace_scope_runtime import (
    _formal_plan_candidate_focus as _formal_plan_candidate_focus,
)
from ...core.workspace_scope_runtime import (
    _revision as _revision,
)
from ...core.workspace_scope_runtime import (
    _verify_plan_advance_payload as _verify_plan_advance_payload,
)
from ...core.workspace_scope_runtime import (
    leftover_formal_plan_identity_labels as leftover_formal_plan_identity_labels,
)
from ...core.workspace_scope_runtime import (
    live_coach_stage_label as live_coach_stage_label,
)
from ...core.workspace_scope_runtime import (
    live_plan_current_step_fill as live_plan_current_step_fill,
)
from ...core.workspace_scope_runtime import (
    live_plan_next_after_current as live_plan_next_after_current,
)
from ...core.workspace_scope_runtime import (
    normalize_plan_runtime_recovery as normalize_plan_runtime_recovery,
)
from ...core.workspace_scope_runtime import (
    stamp_workspace_scope as stamp_workspace_scope,
)
from ..transfer_skills import describe_transfer_skill_state, normalize_transfer_skill_state_record

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




def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def strip_secrets(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key.casefold() not in SECRET_KEYS}






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


