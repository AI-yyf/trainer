"""Authoritative Coach what/why/next orientation.

Frontend and backend must call the same priority rules. Do not invent
readiness from default capability flags or empty conversation theater.
"""

from __future__ import annotations

from typing import Any

from ..core.models import WorkbenchSnapshot
from ..memory.transfer_skills import (
    apply_transfer_skill_to_coach_orientation,
    normalize_transfer_skill_state_record,
)
from ..memory.workspace_recovery import (
    coach_focus_runtime_from_snapshot,
    formal_plan_is_live_runtime_identity,
    is_interrupted_streaming_checkpoint,
    leftover_formal_training_labels,
    live_plan_blocked_reason,
    live_plan_refresh_step_why,
    live_training_card_title,
    select_training_chrome_for_scope,
    training_record_matches_workspace,
)

OBJECTS = frozenset({"provider", "workspace", "conversation", "plan", "training"})
STATES = frozenset({"needs_setup", "waiting", "working", "blocked", "ready", "interrupted"})
ACTIONS = frozenset(
    {"open_settings", "open_plan", "open_training", "compose", "wait", "retry", "resume_checkpoint"}
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_zh(language: str | None) -> bool:
    return (language or "").strip() == "zh-CN"


def _phase(value: Any) -> str:
    return _text(value).lower().replace("-", "_")


def _understanding_for_scope(understanding: Any, workspace_id: str) -> Any:
    if understanding is None:
        return None
    stamp = ""
    if isinstance(understanding, dict):
        stamp = _text(understanding.get("workspace_id") or understanding.get("workspaceId"))
    else:
        stamp = _text(getattr(understanding, "workspace_id", "") or getattr(understanding, "workspaceId", ""))
    if workspace_id and stamp and stamp != workspace_id:
        return None
    return understanding


def _first_look_orientation_facts(understanding: Any) -> tuple[str, str]:
    if understanding is None:
        return "", ""
    if isinstance(understanding, dict):
        first = understanding.get("first_look_summary") or understanding.get("firstLookSummary")
    else:
        first = getattr(understanding, "first_look_summary", None)
    if first is None:
        return "", ""
    if isinstance(first, dict):
        nxt = _text(first.get("recommended_next_step") or first.get("recommendedNextStep"))
        why = _text(first.get("why_this_guess") or first.get("whyThisGuess"))
        return nxt, why
    return (
        _text(getattr(first, "recommended_next_step", "")),
        _text(getattr(first, "why_this_guess", "")),
    )


def normalize_coach_orientation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    object_kind = _text(value.get("object_kind") or value.get("objectKind"))
    state = _text(value.get("state"))
    action = _text(value.get("primary_action") or value.get("primaryAction"))
    object_label = _text(value.get("object_label") or value.get("objectLabel"))
    why = _text(value.get("why"))
    next_step = _text(value.get("next_step") or value.get("nextStep"))
    if object_kind not in OBJECTS or state not in STATES or action not in ACTIONS:
        return None
    if not object_label or not why or not next_step:
        return None
    revision = value.get("revision")
    return {
        "object_kind": object_kind,
        "object_label": object_label,
        "state": state,
        "why": why,
        "primary_action": action,
        "primary_action_label": _text(value.get("primary_action_label") or value.get("primaryActionLabel")),
        "next_step": next_step,
        "advanced_where": _text(value.get("advanced_where") or value.get("advancedWhere")),
        "source": "snapshot",
        "revision": int(revision) if isinstance(revision, int) and revision > 0 else 1,
    }


def derive_coach_orientation(
    *,
    sidecar_status: str = "",
    has_provider_model: bool = False,
    provider_send_blocked: bool = False,
    provider_block_reason: str = "",
    workspace_blocked: bool = False,
    workspace_block_reason: str = "",
    streaming: bool = False,
    checkpoint_recovery: bool = False,
    conversation_count: int = 0,
    plan_blocked_reason: str = "",
    plan_current_step: str = "",
    plan_why_now: str = "",
    active_thread_focus: str = "",
    training_reliability_phase: str = "",
    training_learning_phase: str = "",
    training_handoff_status: str = "",
    selected_card_title: str = "",
    language: str | None = None,
    transfer_state: dict[str, Any] | None = None,
    first_look_next: str = "",
    first_look_why: str = "",
) -> dict[str, Any]:
    zh = _is_zh(language)
    sidecar = _phase(sidecar_status)
    card_title = _text(selected_card_title)
    reliability_phase = _phase(training_reliability_phase)
    learning_phase = _phase(training_learning_phase)
    handoff_status = _phase(training_handoff_status)
    plan_blocked = _text(plan_blocked_reason)
    plan_step = _text(plan_current_step)
    plan_why = _text(plan_why_now)
    thread_focus = _text(active_thread_focus)
    first_look_next = _text(first_look_next)
    first_look_why = _text(first_look_why)
    leftover_training_not_live_for_bound_plan = bool(plan_step) and not card_title

    def record(
        *,
        object_kind: str,
        object_label: str,
        state: str,
        why: str,
        primary_action: str,
        primary_action_label: str,
        next_step: str,
        advanced_where: str,
    ) -> dict[str, Any]:
        payload = {
            "object_kind": object_kind,
            "object_label": object_label,
            "state": state,
            "why": why,
            "primary_action": primary_action,
            "primary_action_label": primary_action_label,
            "next_step": next_step,
            "advanced_where": advanced_where,
            "source": "snapshot",
            "revision": 1,
        }
        return apply_transfer_skill_to_coach_orientation(payload, transfer_state)

    if sidecar == "error":
        return record(
            object_kind="workspace",
            object_label="运行时" if zh else "Runtime",
            state="blocked",
            why="Sidecar 当前不可用。" if zh else "The sidecar is not available.",
            primary_action="open_settings",
            primary_action_label="查看设置" if zh else "Open Settings",
            next_step="先恢复 sidecar，再继续对话。" if zh else "Restore the sidecar, then continue.",
            advanced_where="设置 · 运行状态" if zh else "Settings · runtime",
        )
    if sidecar in {"starting", "unknown"}:
        return record(
            object_kind="workspace",
            object_label="运行时" if zh else "Runtime",
            state="waiting",
            why="Sidecar 还在启动或状态未确认。" if zh else "The sidecar is still starting or unconfirmed.",
            primary_action="wait",
            primary_action_label="等待就绪" if zh else "Wait",
            next_step="等运行时就绪后再发送。" if zh else "Wait until runtime is ready before sending.",
            advanced_where="设置 · 运行状态" if zh else "Settings · runtime",
        )
    if not has_provider_model or provider_send_blocked:
        return record(
            object_kind="provider",
            object_label="模型连接" if zh else "Provider",
            state="needs_setup",
            why=provider_block_reason
            or ("还没有可用的模型连接。" if zh else "No usable model connection is available."),
            primary_action="open_settings",
            primary_action_label="去设置" if zh else "Open Settings",
            next_step="先保存并测试 provider。" if zh else "Save and test a provider first.",
            advanced_where="设置 · Provider" if zh else "Settings · provider",
        )
    if workspace_blocked:
        return record(
            object_kind="workspace",
            object_label="当前工作区" if zh else "Workspace",
            state="blocked",
            why=workspace_block_reason
            or ("当前工作区还不能开始教练回合。" if zh else "This workspace cannot start a coaching turn yet."),
            primary_action="open_settings",
            primary_action_label="查看工作区" if zh else "Open Settings",
            next_step="先处理工作区限制。" if zh else "Resolve the workspace restriction first.",
            advanced_where="设置 · 工作区" if zh else "Settings · workspace",
        )
    if checkpoint_recovery:
        return record(
            object_kind="conversation",
            object_label="本轮对话" if zh else "This turn",
            state="interrupted",
            why="这一轮已中断，但进度已保存。" if zh else "This turn was interrupted, and progress was saved.",
            primary_action="resume_checkpoint",
            primary_action_label="恢复进度" if zh else "Resume",
            next_step="从已保存进度继续，或查看记录。" if zh else "Resume the saved progress, or review the record.",
            advanced_where="对话 · checkpoint" if zh else "Coach · checkpoint",
        )
    if streaming:
        return record(
            object_kind="conversation",
            object_label=thread_focus or ("本轮对话" if zh else "This turn"),
            state="working",
            why="教练正在处理这一轮。" if zh else "The coach is working on this turn.",
            primary_action="wait",
            primary_action_label="等待回复" if zh else "Wait",
            next_step="等这轮结束后再决定下一步。" if zh else "Wait for this turn to finish before the next move.",
            advanced_where="对话流" if zh else "Conversation",
        )
    if not leftover_training_not_live_for_bound_plan and reliability_phase in {
        "intent",
        "pending",
        "executing",
    }:
        return record(
            object_kind="training",
            object_label=card_title or ("当前训练卡" if zh else "Current training card"),
            state="waiting",
            why="训练步骤还在等待 sidecar 确认。" if zh else "The training step is waiting for sidecar acknowledgement.",
            primary_action="wait",
            primary_action_label="等待确认" if zh else "Wait",
            next_step="先等快照回来，不要重复提交。" if zh else "Wait for the snapshot. Do not submit again yet.",
            advanced_where="训练 · 保存状态" if zh else "Training · save status",
        )
    if not leftover_training_not_live_for_bound_plan and reliability_phase in {
        "failed",
        "cancelled",
    }:
        return record(
            object_kind="training",
            object_label=card_title or ("当前训练卡" if zh else "Current training card"),
            state="blocked",
            why="这次训练保存还没有被权威快照确认。" if zh else "This training save was not accepted by the snapshot.",
            primary_action="retry",
            primary_action_label="去训练重试" if zh else "Retry in Training",
            next_step="回到训练再提交一次。" if zh else "Return to Training and submit again.",
            advanced_where="训练 · 保存状态" if zh else "Training · save status",
        )
    if not leftover_training_not_live_for_bound_plan and (
        handoff_status == "ready_to_return" or learning_phase == "return"
    ):
        return record(
            object_kind="training",
            object_label=card_title or ("当前训练卡" if zh else "Current training card"),
            state="ready",
            why="验证和复盘已在卡上，还差回流转正。" if zh else "Verification and reflection are on the card; return is still due.",
            primary_action="open_training",
            primary_action_label="去完成回落" if zh else "Complete return",
            next_step="在训练里完成 Return。" if zh else "Complete Return in Training.",
            advanced_where="训练 · 回落" if zh else "Training · return",
        )
    if not leftover_training_not_live_for_bound_plan and (
        learning_phase == "reflect" or handoff_status == "needs_reflection"
    ):
        return record(
            object_kind="training",
            object_label=card_title or ("当前训练卡" if zh else "Current training card"),
            state="ready",
            why="可信验证已在，还差一条复盘。" if zh else "Trusted verification is in; reflection is still missing.",
            primary_action="open_training",
            primary_action_label="去复盘" if zh else "Open Training",
            next_step="先写下这条证据说明了什么。" if zh else "Write what this evidence proves.",
            advanced_where="训练 · 复盘" if zh else "Training · reflect",
        )
    if not leftover_training_not_live_for_bound_plan and (
        learning_phase == "verify" or handoff_status == "needs_verification"
    ):
        return record(
            object_kind="training",
            object_label=card_title or ("当前训练卡" if zh else "Current training card"),
            state="waiting",
            why="这张卡还在等可信验证。" if zh else "This card is still waiting for trusted verification.",
            primary_action="open_training",
            primary_action_label="去验证" if zh else "Open Training",
            next_step="先验证当前结果，再复盘。" if zh else "Verify the current result, then reflect.",
            advanced_where="训练 · 验证" if zh else "Training · verify",
        )
    if plan_blocked:
        return record(
            object_kind="plan",
            object_label=plan_step or thread_focus or ("当前计划" if zh else "Current plan"),
            state="blocked",
            why=plan_blocked,
            primary_action="open_plan",
            primary_action_label="查看计划" if zh else "Open Plan",
            next_step="先处理这个 blocker。" if zh else "Clear this blocker first.",
            advanced_where="计划 · 证据与阻碍" if zh else "Plan · evidence and blockers",
        )
    if not leftover_training_not_live_for_bound_plan and learning_phase in {"try", "learn"}:
        return record(
            object_kind="training",
            object_label=card_title or ("当前训练卡" if zh else "Current training card"),
            state="ready",
            why=(
                "当前对象是这张训练卡的学习步骤。"
                if zh and learning_phase == "learn"
                else "The current object is this card's learn step."
                if learning_phase == "learn"
                else "当前对象是这张训练卡的尝试步骤。"
                if zh
                else "The current object is this card's try step."
            ),
            primary_action="open_training",
            primary_action_label="打开训练" if zh else "Open Training",
            next_step=(
                "先看清任务，再开始做。"
                if zh and learning_phase == "learn"
                else "Read the task, then start."
                if learning_phase == "learn"
                else "做最小改动，然后验证。"
                if zh
                else "Make the smallest change, then verify."
            ),
            advanced_where="训练 · 当前卡" if zh else "Training · current card",
        )
    if plan_step:
        return record(
            object_kind="plan",
            object_label=plan_step,
            state="ready",
            why=plan_why or ("这是当前主线。" if zh else "This is the current thread."),
            primary_action="open_plan",
            primary_action_label="打开计划" if zh else "Open Plan",
            next_step="围绕这个对象继续，或先核对计划。" if zh else "Continue on this object, or check Plan.",
            advanced_where="计划 · 当前步骤" if zh else "Plan · current step",
        )
    if first_look_next:
        return record(
            object_kind="conversation",
            object_label="当前项目" if zh else "This project",
            state="ready",
            why=first_look_why
            or ("这是对这个工作区的第一眼判断。" if zh else "This is the first-look next for this workspace."),
            primary_action="compose",
            primary_action_label="开始说" if zh else "Start",
            next_step=first_look_next,
            advanced_where="对话 · 第一眼" if zh else "Coach · first look",
        )
    if thread_focus:
        return record(
            object_kind="conversation",
            object_label=thread_focus,
            state="ready",
            why="这是当前主线。" if zh else "This is the current thread.",
            primary_action="compose",
            primary_action_label="继续说" if zh else "Continue",
            next_step="围绕这个对象继续，或先核对计划。" if zh else "Continue on this object, or check Plan.",
            advanced_where="对话；细节在计划" if zh else "Coach; details in Plan",
        )
    if conversation_count == 0:
        return record(
            object_kind="conversation",
            object_label="教练对话" if zh else "Coach conversation",
            state="ready",
            why="还没有当前回合。" if zh else "There is no current turn yet.",
            primary_action="compose",
            primary_action_label="开始说" if zh else "Start",
            next_step="在下方输入你现在想学或想做的事。" if zh else "Say what you want to learn or do next.",
            advanced_where="计划 / 训练会在有对象后出现" if zh else "Plan / Training appear after there is an object",
        )
    return record(
        object_kind="conversation",
        object_label="本轮对话" if zh else "This conversation",
        state="ready",
        why="当前对象是这场教练对话。" if zh else "The current object is this coaching conversation.",
        primary_action="compose",
        primary_action_label="继续说" if zh else "Continue",
        next_step="接着问，或把结果带回计划 / 训练。" if zh else "Ask the next question, or return a result to Plan / Training.",
        advanced_where="计划 / 训练" if zh else "Plan / Training",
    )


def build_coach_orientation_from_snapshot(
    snapshot: WorkbenchSnapshot,
    *,
    response_language: str | None = None,
) -> dict[str, Any]:
    workspace = snapshot.memory.workspace if isinstance(snapshot.memory.workspace, dict) else {}
    workspace_id = _text(workspace.get("workspace_id") or workspace.get("workspaceId"))
    reliability = workspace.get("latest_training_reliability")
    reliability_record = reliability if isinstance(reliability, dict) else {}
    raw_handoff = workspace.get("latest_training_handoff")
    handoff = raw_handoff if training_record_matches_workspace(raw_handoff, workspace_id) else None
    handoff_record = handoff if isinstance(handoff, dict) else {}
    chrome_source = workspace.get("latest_training_chrome") or {
        "workspace_id": handoff_record.get("workspace_id") or handoff_record.get("workspaceId"),
        "selected_card_title": workspace.get("selected_card_title"),
        "card_title": handoff_record.get("card_title") or handoff_record.get("cardTitle"),
    }
    scoped_chrome = (
        select_training_chrome_for_scope(chrome_source, workspace_id)
        if workspace_id
        else None
    )
    if workspace_id and not training_record_matches_workspace(chrome_source, workspace_id):
        scoped_chrome = None
        handoff_record = {}
    provider = snapshot.provider
    has_provider_model = bool(provider and _text(provider.model) and _text(provider.base_url))
    active_thread = snapshot.memory.active_thread
    if workspace_id and active_thread is not None and not training_record_matches_workspace(
        {
            "workspace_id": _text(
                getattr(active_thread, "workspace_id", "")
                or getattr(active_thread, "workspaceId", "")
            ),
        },
        workspace_id,
    ):
        active_thread = None
    plan = snapshot.plan
    if workspace_id and plan is not None and not training_record_matches_workspace(
        {
            "workspace_id": _text(
                getattr(plan, "workspace_id", "") or getattr(plan, "workspaceId", "")
            ),
        },
        workspace_id,
    ):
        plan = None
    leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
    leftover_task = snapshot.current_task
    if workspace_id and leftover_task is not None and not training_record_matches_workspace(
        {
            "workspace_id": _text(
                getattr(leftover_task, "workspace_id", "")
                or getattr(leftover_task, "workspaceId", "")
                or (getattr(leftover_task, "metadata", None) or {}).get("workspace_id")
                or (getattr(leftover_task, "metadata", None) or {}).get("workspaceId")
            ),
        },
        workspace_id,
    ):
        leftover_task = None
    leftover_task_title = _text(
        getattr(leftover_task, "title", "") if leftover_task is not None else ""
    )
    leftover_refresh = live_plan_refresh_step_why(
        plan=plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
        current_step=_text(getattr(plan, "current_step", "")),
        why_now=_text(getattr(plan, "why_now", "")),
        next_after_current=_text(getattr(plan, "next_after_current", "")),
        task_title=leftover_task_title,
    )
    runtime_status = snapshot.plan_runtime_status if isinstance(snapshot.plan_runtime_status, dict) else {}
    recovered_runtime = runtime_status.get("recovered") is True
    understanding = _understanding_for_scope(
        getattr(snapshot.memory, "workspace_understanding", None),
        workspace_id,
    )
    if understanding is None:
        understanding = _understanding_for_scope(workspace.get("workspace_understanding"), workspace_id)
    first_look_next, first_look_why = _first_look_orientation_facts(understanding)
    leftover_live = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
        current_step=leftover_refresh["current_step"],
    )
    recovered_step = leftover_refresh["current_step"]
    # A frozen leftover plan that is no longer the live identity stays out of plan
    # orientation; only a live plan or an unfrozen plan adopts the recovered step.
    plan_frozen = bool(getattr(plan, "frozen", False)) if plan is not None else False
    plan_orientation_live = leftover_live or not plan_frozen
    thread_focus = _text(getattr(active_thread, "focus_area", "") if active_thread else "")
    if not leftover_live and recovered_step and not thread_focus:
        thread_focus = recovered_step
    leftover_labels = leftover_formal_training_labels(
        plan=plan,
        task_title=leftover_task_title,
        live_plan=leftover_live and bool(leftover_refresh["current_step"]),
        live_task=False,
    )
    if first_look_next and first_look_next in leftover_labels:
        first_look_next = ""
        first_look_why = ""
    return derive_coach_orientation(
        sidecar_status=snapshot.sidecar_status,
        has_provider_model=has_provider_model,
        conversation_count=len(snapshot.messages),
        plan_blocked_reason=live_plan_blocked_reason(
            plan=plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            blocked_reason=_text(getattr(plan, "blocked_reason", ""))
            or (_text(runtime_status.get("blocked_reason")) if recovered_runtime else ""),
        ),
        plan_current_step=recovered_step if plan_orientation_live else "",
        plan_why_now=leftover_refresh["why_now"] if plan_orientation_live else "",
        active_thread_focus=thread_focus,
        training_reliability_phase=_text(reliability_record.get("phase")),
        training_learning_phase=_text(
            handoff_record.get("learning_phase") or workspace.get("latest_training_learning_phase")
        ),
        training_handoff_status=_text(handoff_record.get("handoff_status") or handoff_record.get("status")),
        selected_card_title=live_training_card_title(
            plan=plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=leftover_task_title,
            card_title=_text(
                (scoped_chrome or {}).get("selected_card_title")
                or (
                    workspace.get("selected_card_title")
                    if not workspace_id or training_record_matches_workspace(chrome_source, workspace_id)
                    else ""
                )
                or handoff_record.get("card_title")
            ),
        ),
        language=response_language,
        transfer_state=normalize_transfer_skill_state_record(workspace.get("latest_transfer_state")),
        checkpoint_recovery=is_interrupted_streaming_checkpoint(workspace.get("latest_streaming_checkpoint")),
        first_look_next=first_look_next,
        first_look_why=first_look_why,
    )
