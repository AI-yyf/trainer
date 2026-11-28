"""Pure live-identity and training-card display helpers extracted from workspace_recovery.

This module is the canonical Batch-1 strangler destination for workspace live-plan,
live-task, and training-card display identity checks. It has zero dependency on
``app.memory.workspace_recovery`` so domain packages (``training``, ``evaluator``,
``llm.tool_handlers``, ``api.routes``) can depend on ``app.core`` directly while
remaining legacy callers transition progressively toward ``ProjectedWorkspaceState``.
"""

from __future__ import annotations

from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _recovered_overlay_empty_step(
    runtime: dict[str, Any] | None,
    existing: dict[str, Any] | None,
    current_step: str = "",
) -> bool:
    """Recovered overlay with no live current_step means the formal plan is not live."""
    runtime_map = runtime if isinstance(runtime, dict) else {}
    existing_map = existing if isinstance(existing, dict) else {}
    step = (
        _text(current_step)
        or _text(runtime_map.get("current_step"))
        or _text(existing_map.get("current_step"))
    )
    return bool(runtime_map or existing_map) and not step


def formal_plan_is_live_runtime_identity(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """A persisted formal plan is live only when recovered runtime still carries its id."""
    if plan is None:
        return False
    formal = _text(getattr(plan, "id", "") or getattr(plan, "plan_id", ""))
    runtime_map = runtime if isinstance(runtime, dict) else {}
    existing_map = existing if isinstance(existing, dict) else {}
    runtime_step = (
        _text(current_step)
        or _text(runtime_map.get("current_step"))
        or _text(existing_map.get("current_step"))
    )
    plan_step = _text(getattr(plan, "current_step", "") if plan is not None else "")
    carried = _text(runtime_map.get("plan_id") or existing_map.get("plan_id"))
    recovered = bool(runtime_map or existing_map)
    if not formal:
        return False
    if not recovered:
        return True
    if _recovered_overlay_empty_step(runtime_map, existing_map, runtime_step):
        return False
    if not runtime_step:
        return False
    if plan_step and runtime_step != plan_step:
        return False
    return carried == formal


def is_formal_plan_live_for_fill(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
) -> bool:
    """Title/summary fill is live only when recovered runtime still carries the plan id."""
    runtime_map = runtime if isinstance(runtime, dict) else {}
    existing_map = existing if isinstance(existing, dict) else {}
    if not runtime_map and not existing_map:
        return True
    recovered_step = _text(runtime_map.get("current_step")) or _text(existing_map.get("current_step"))
    if not recovered_step:
        return False
    return formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime_map,
        existing=existing_map,
        current_step=recovered_step,
    )


def formal_task_is_live_runtime_identity(
    *,
    recovered: bool = False,
    runtime_current_step: str = "",
    task_title: str = "",
) -> bool:
    """A persisted task is live only when recovered runtime still names it."""
    runtime_step = _text(runtime_current_step)
    title = _text(task_title)
    if not recovered:
        return bool(title)
    if not runtime_step:
        return False
    return bool(title) and runtime_step == title


def stale_formal_training_labels(
    *,
    plan: Any | None = None,
    task_title: str = "",
    task_goal: str = "",
    live_plan: bool = False,
    live_task: bool = False,
) -> set[str]:
    """Formal title/summary/old step labels that must not mint a recovered card."""
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


def live_training_card_title(
    *,
    plan: Any | None = None,
    task: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    task_title: str = "",
    card_title: str = "",
) -> str:
    """Training-card chrome uses recovered current_step instead of stale formal titles."""
    runtime_map = runtime if isinstance(runtime, dict) else {}
    existing_map = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime_map.get("current_step"))
        or _text(existing_map.get("current_step"))
    )
    recovered = bool(runtime_map or existing_map)
    title = _text(card_title)
    if recovered and not recovered_step:
        return ""
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime_map,
        existing=existing_map,
        current_step=recovered_step,
    )
    live_task = formal_task_is_live_runtime_identity(
        recovered=recovered,
        runtime_current_step=recovered_step,
        task_title=_text(task_title) or _text(getattr(task, "title", "") if task is not None else ""),
    )
    stale_labels = stale_formal_training_labels(
        plan=plan,
        task_title=_text(task_title) or _text(getattr(task, "title", "") if task is not None else ""),
        live_plan=live_plan,
        live_task=live_task,
    )
    if not live_plan and title and (
        title in stale_labels or any(label and label in title for label in stale_labels)
    ):
        return recovered_step
    return title


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
    """why_this_card uses recovered current_step instead of stale formal card titles."""
    runtime_map = runtime if isinstance(runtime, dict) else {}
    existing_map = existing if isinstance(existing, dict) else {}
    recovered_step = (
        _text(runtime_map.get("current_step"))
        or _text(existing_map.get("current_step"))
    )
    recovered = bool(runtime_map or existing_map)
    title = live_training_card_title(
        plan=plan,
        task=task,
        runtime=runtime_map,
        existing=existing_map,
        task_title=task_title,
        card_title=card_title,
    )
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=runtime_map,
        existing=existing_map,
        current_step=recovered_step,
    )
    stale_labels = stale_formal_training_labels(
        plan=plan,
        task_title=_text(task_title) or _text(getattr(task, "title", "") if task is not None else ""),
        live_plan=False,
        live_task=False,
    )
    why = _text(why_now)
    stale_not_live = recovered and (not recovered_step or not live_plan)
    if stale_not_live and stale_labels and why and (
        why in stale_labels or any(label and label in why for label in stale_labels)
    ):
        why = recovered_step if recovered_step and recovered_step not in stale_labels else ""
    if why:
        return why
    if title:
        if kind == "next":
            return f"{title} is the next training card."
        return f"{title} is the current training card."
    return ""


__all__ = [
    "_recovered_overlay_empty_step",
    "formal_plan_is_live_runtime_identity",
    "formal_task_is_live_runtime_identity",
    "is_formal_plan_live_for_fill",
    "live_training_card_title",
    "live_training_why_this_card",
    "stale_formal_training_labels",
]
