"""Pure workspace scope, plan-runtime selection, evidence scoping, and card-open helpers.

Extracted from ``app.memory.workspace_recovery_domains`` in Batch 2 so leaf modules
across ``core``, ``api``, ``pedagogy``, ``llm.tool_handlers``, and ``memory`` can
depend on ``app.core`` directly with zero dependency on ``app.memory.workspace_recovery``.
"""

from __future__ import annotations

from typing import Any

from .workspace_live_identity import (
    _text,
    formal_plan_is_live_runtime_identity,
    live_training_card_title,
)
from .workspace_live_identity import (
    is_formal_plan_live_for_fill as leftover_formal_plan_is_live_for_fill,
)
from .workspace_live_identity import (
    stale_formal_training_labels as leftover_formal_training_labels,
)

PLAN_RUNTIME_KEY = "latest_plan_runtime"
PROVIDER_CAPABILITY_KEY = "latest_provider_capability"


def _revision(value: Any, fallback: int = 1) -> int:
    return int(value) if isinstance(value, int) and value > 0 else fallback


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


def is_current_for_workspace(record: dict[str, Any] | None, workspace_id: str) -> bool:
    record_workspace_id = _text((record or {}).get("workspace_id"))
    scope_workspace_id = _text(workspace_id)
    return bool(record_workspace_id) and bool(scope_workspace_id) and record_workspace_id == scope_workspace_id


def select_plan_runtime_for_scope(value: Any, workspace_id: str) -> dict[str, Any] | None:
    record = normalize_plan_runtime_recovery(value)
    return record if record and is_current_for_workspace(record, workspace_id) else None


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


def evidence_item_concepts(item: Any) -> list[str]:
    raw = getattr(item, "concepts", None)
    if raw is None and isinstance(item, dict):
        raw = item.get("concepts")
    return [_text(concept) for concept in (raw or []) if _text(concept)]


def evidence_bound_to_runtime_step(item: Any, current_step: str) -> bool:
    step = _text(current_step)
    if not step:
        return False
    bound_step = _text(
        getattr(item, "target_plan_step", None)
        or (item.get("target_plan_step") if isinstance(item, dict) else "")
    )
    if bound_step:
        return bound_step == step
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
    current_plan_id: str = "",
    current_stage_id: str = "",
) -> dict[str, list[Any]]:
    """Live pending/adopt follow recovered current_step. Older items stay history.

    Non-bound pending items (no step binding at all) surface in the
    ``unscoped`` bucket so they stay actionable; pending items explicitly bound
    to another step stay history, as do non-bound deferred/adopted/rejected.
    """

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
            target_plan = _text(
                getattr(item, "target_plan_id", None)
                or (item.get("target_plan_id") if isinstance(item, dict) else "")
            )
            if target_plan and target_plan != _text(current_plan_id):
                historic.append(item)
                continue
            if target_plan and _item_target_stage(item) != _text(current_stage_id):
                historic.append(item)
                continue
            if not recovered or not _text(current_step):
                live.append(item)
                continue
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

__all__ = [
    "PLAN_RUNTIME_KEY",
    "PROVIDER_CAPABILITY_KEY",
    "_formal_plan_candidate_focus",
    "_revision",
    "_verify_plan_advance_payload",
    "apply_live_training_mint_to_card",
    "evidence_bound_to_runtime_step",
    "evidence_item_concepts",
    "evidence_item_workspace_id",
    "is_current_for_workspace",
    "leftover_formal_plan_identity_labels",
    "live_coach_stage_label",
    "live_plan_current_step_fill",
    "live_plan_next_after_current",
    "live_training_open_copy",
    "normalize_plan_runtime_recovery",
    "scope_evidence_items_to_workspace",
    "scope_evidence_queue_to_runtime_step",
    "select_plan_runtime_for_pressure",
    "select_plan_runtime_for_scope",
    "stamp_produced_workspace_record",
    "stamp_workspace_scope",
]
