"""Authoritative Plan what/why/next orientation.

Frontend and backend must call the same priority rules. After understand,
first-look next wins over inventing a LearningPlan. Do not mint a plan
to fill an empty recovered step.
"""

from __future__ import annotations

from typing import Any

from ..memory.transfer_skills import (
    apply_transfer_skill_to_coach_orientation,
    normalize_transfer_skill_state_record,
)

PLAN_ACTIONS = frozenset(
    {
        "generate_plan",
        "continue_without_plan",
        "adopt_evidence",
        "clear_blocker",
        "continue_step",
        "open_training",
        "unfreeze_plan",
        "wait",
    }
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_zh(language: str | None) -> bool:
    return (language or "").strip() == "zh-CN"


def derive_plan_orientation(
    *,
    has_formal_plan: bool = False,
    recovered_runtime: bool = False,
    resume_state: str = "",
    current_step: str = "",
    why_now: str = "",
    blocked_reason: str = "",
    pending_evidence_count: int = 0,
    first_look_recommended_next: str = "",
    first_look_why: str = "",
    transfer_state: dict[str, Any] | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Prefer recovered runtime, then first-look continue-without-plan, then generate."""

    zh = _is_zh(language)
    step = _text(current_step)
    first_look_next = _text(first_look_recommended_next)
    first_look_reason = _text(first_look_why)
    blocked = _text(blocked_reason)
    why = _text(why_now)
    resumed = recovered_runtime and _text(resume_state) == "in_progress"
    waiting_verify = recovered_runtime and _text(resume_state) == "waiting"

    if recovered_runtime and not step:
        orientation = {
            "object_kind": "plan",
            "object_label": "当前计划" if zh else "Current plan",
            "state": "waiting",
            "why": "计划在，但还没有权威的当前步骤。" if zh else "The plan is present, but there is no authoritative current step.",
            "primary_action": "wait",
            "primary_action_label": "等待步骤" if zh else "Wait for step",
            "next_step": "等计划运行时写出当前步骤，再继续。" if zh else "Wait for plan runtime to write the current step, then continue.",
            "advanced_where": "计划 · 运行时" if zh else "Plan · runtime",
        }
        return apply_transfer_skill_to_coach_orientation(
            orientation,
            normalize_transfer_skill_state_record(transfer_state),
        )

    if recovered_runtime and blocked:
        orientation = {
            "object_kind": "plan",
            "object_label": step or ("当前计划" if zh else "Current plan"),
            "state": "working" if resumed else "blocked",
            "why": blocked,
            "primary_action": "clear_blocker",
            "primary_action_label": "处理卡点" if zh else "Clear blocker",
            "next_step": (
                f"先处理卡点，再回到：{step}"
                if zh and step
                else f"Clear the blocker, then return to: {step}"
                if step
                else "先处理这个 blocker。"
                if zh
                else "Clear this blocker first."
            ),
            "advanced_where": "计划 · 证据与阻碍" if zh else "Plan · evidence and blockers",
        }
        return apply_transfer_skill_to_coach_orientation(
            orientation,
            normalize_transfer_skill_state_record(transfer_state),
        )

    if recovered_runtime and waiting_verify and step:
        if pending_evidence_count > 0:
            orientation = {
                "object_kind": "plan",
                "object_label": step,
                "state": "waiting",
                "why": why or ("这是当前主线步骤。" if zh else "This is the current mainline step."),
                "primary_action": "adopt_evidence",
                "primary_action_label": "核对证据" if zh else "Review evidence",
                "next_step": "先确认证据，再推进当前步骤。" if zh else "Confirm evidence, then continue this step.",
                "advanced_where": "计划 · 证据队列" if zh else "Plan · evidence queue",
            }
            return apply_transfer_skill_to_coach_orientation(
                orientation,
                normalize_transfer_skill_state_record(transfer_state),
            )
        orientation = {
            "object_kind": "plan",
            "object_label": step,
            "state": "waiting",
            "why": why or ("这是当前主线步骤。" if zh else "This is the current mainline step."),
            "primary_action": "wait",
            "primary_action_label": "等待步骤" if zh else "Wait",
            "next_step": "先确认证据，再推进当前步骤。" if zh else "Confirm evidence, then continue this step.",
            "advanced_where": "计划 · 证据队列" if zh else "Plan · evidence queue",
        }
        return apply_transfer_skill_to_coach_orientation(
            orientation,
            normalize_transfer_skill_state_record(transfer_state),
        )

    if recovered_runtime and step and pending_evidence_count > 0:
        orientation = {
            "object_kind": "plan",
            "object_label": step,
            "state": "waiting",
            "why": f"有 {pending_evidence_count} 条证据还没被采纳，计划尚未改写。"
            if zh
            else f"{pending_evidence_count} evidence item(s) are still pending; the plan is unchanged.",
            "primary_action": "adopt_evidence",
            "primary_action_label": "核对证据" if zh else "Review evidence",
            "next_step": "先确认证据，再推进当前步骤。" if zh else "Confirm evidence, then continue this step.",
            "advanced_where": "计划 · 证据队列" if zh else "Plan · evidence queue",
        }
        return apply_transfer_skill_to_coach_orientation(
            orientation,
            normalize_transfer_skill_state_record(transfer_state),
        )

    if recovered_runtime and step:
        orientation = {
            "object_kind": "plan",
            "object_label": step,
            "state": "working" if resumed else "interrupted",
            "why": why or ("这是当前主线步骤。" if zh else "This is the current mainline step."),
            "primary_action": "continue_step",
            "primary_action_label": "继续这一步" if zh else "Continue this step",
            "next_step": "完成这一步，再带回验证结果。" if zh else "Finish this step, then bring back a verification.",
            "advanced_where": "计划 · 运行时" if zh else "Plan · runtime",
        }
        return apply_transfer_skill_to_coach_orientation(
            orientation,
            normalize_transfer_skill_state_record(transfer_state),
        )

    if not has_formal_plan and first_look_next:
        orientation = {
            "object_kind": "plan",
            "object_label": "当前计划" if zh else "Current plan",
            "state": "ready",
            "why": first_look_reason
            or (
                "这个工作区已有第一眼下一步，先不要发明计划。"
                if zh
                else "This workspace already has a first-look next. Do not invent a plan yet."
            ),
            "primary_action": "continue_without_plan",
            "primary_action_label": "先不生成计划" if zh else "Continue without a plan",
            "next_step": first_look_next,
            "advanced_where": "计划 · 第一眼" if zh else "Plan · first look",
        }
        return apply_transfer_skill_to_coach_orientation(
            orientation,
            normalize_transfer_skill_state_record(transfer_state),
        )

    if not has_formal_plan:
        orientation = {
            "object_kind": "plan",
            "object_label": "学习计划" if zh else "Learning plan",
            "state": "needs_setup",
            "why": "还没有可执行的正式计划。" if zh else "There is no formal plan to follow yet.",
            "primary_action": "generate_plan",
            "primary_action_label": "生成计划" if zh else "Generate plan",
            "next_step": "先生成一条主线，再决定当前步骤。" if zh else "Generate a mainline before choosing the current step.",
            "advanced_where": "计划 · 空状态" if zh else "Plan · empty",
        }
        return apply_transfer_skill_to_coach_orientation(
            orientation,
            normalize_transfer_skill_state_record(transfer_state),
        )

    orientation = {
        "object_kind": "plan",
        "object_label": step or ("当前计划" if zh else "Current plan"),
        "state": "ready",
        "why": why or ("这是当前主线步骤。" if zh else "This is the current mainline step."),
        "primary_action": "continue_step",
        "primary_action_label": "继续这一步" if zh else "Continue this step",
        "next_step": step or ("完成这一步，再带回验证结果。" if zh else "Finish this step, then bring back a verification."),
        "advanced_where": "计划 · 当前步骤" if zh else "Plan · current step",
    }
    return apply_transfer_skill_to_coach_orientation(
        orientation,
        normalize_transfer_skill_state_record(transfer_state),
    )
