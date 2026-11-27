"""Fail-closed workspace recovery for plan, provider last-test, and streams.

These records live on structured workspace memory — the same DB path as
training reliability, coach orientation, and transfer state. Incomplete
records are never treated as success. API keys are never stored.
"""

from __future__ import annotations

from typing import Any

from .plan_persist_chrome import (
    PLAN_RUNTIME_KEY,
    _formal_plan_candidate_focus,
    _text,
    formal_plan_is_live_runtime_identity,
    formal_task_is_live_runtime_identity,
    leftover_formal_training_labels,
    live_coach_focus_area,
    live_coach_stage_label,
    live_plan_refresh_step_why,
    live_plan_update_persist_chrome,
)


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
    raw_current_stage = runtime.get("current_stage")
    current_stage: dict[str, Any] = (
        raw_current_stage if isinstance(raw_current_stage, dict) else {}
    )
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
