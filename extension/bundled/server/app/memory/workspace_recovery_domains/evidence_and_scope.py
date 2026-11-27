"""Fail-closed workspace recovery for plan, provider last-test, and streams.

These records live on structured workspace memory — the same DB path as
training reliability, coach orientation, and transfer state. Incomplete
records are never treated as success. API keys are never stored.
"""

from __future__ import annotations

from typing import Any

from .plan_persist_chrome import (
    ADAPTATION_GUIDE_KEY,
    AFFECT_STATE_KEY,
    COACH_FOCUS_KEY,
    COACH_TURN_KEY,
    COACHING_ADAPTATION_KEY,
    COACHING_FOCUS_KEY,
    CURRENT_TASK_KEY,
    EVALUATION_KEY,
    LEARNER_STATE_KEY,
    NEXT_STEP_HINT_KEY,
    PRINCIPLE_NOTES_KEY,
    PROJECT_SOURCES_KEY,
    TEACHING_DECISION_KEY,
    TONE_DECISION_KEY,
    _revision,
    _text,
    normalize_plan_runtime_recovery,
    stamp_workspace_scope,
    strip_secrets,
    utc_now_iso,
)
from .runtime_recovery import (
    _structured_string_list,
    build_plan_runtime_recovery,
    is_current_for_provider,
    is_current_for_workspace,
    normalize_provider_capability_recovery,
    recover_streaming_checkpoint_after_restart,
    select_plan_runtime_for_scope,
)


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
        "upstream_unavailable",
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
    if _text(current.get("plan_id")):
        # A reply may clarify a bound step or mark it waiting for verification,
        # but only a formal commit or verified advance can change its identity.
        facts = {
            key: value
            for key, value in facts.items()
            if key not in {"current_step", "currentStep", "why_now", "whyNow",
                           "verify_method", "verifyMethod", "next_after_current",
                           "nextAfterCurrent"}
        }
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
