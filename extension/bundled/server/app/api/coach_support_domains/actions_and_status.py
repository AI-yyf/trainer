"""Coach turn helpers moved out of build_router (§五十二 extraction).

The helpers share one dependency bundle (``CoachSupportDeps``) assembled by
``build_router``. Keeping the bundle explicit makes the closure graph visible
instead of hiding 45 names inside a 25k-line function.
"""

from __future__ import annotations

from ...core.models import (
    UserProfile,
    WorkbenchSnapshot,
)
from ...memory.workspace_recovery import (
    PLAN_RUNTIME_KEY,
    coach_focus_runtime_from_snapshot,
    leftover_coach_turn_chrome_is_not_live,
    leftover_formal_plan_is_live_for_fill,
    leftover_formal_training_labels,
    live_coaching_next_step,
    live_plan_overlay_fields,
    live_task_suggested_title,
    overlay_plan_runtime_current_stage,
    plan_runtime_status_from_recovery,
)
from .._helpers import (
    localized_text,
)
from ..router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from ..router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from .types_and_deps import CoachSupportDeps


def coach_suggested_actions(deps: CoachSupportDeps,
    response_language: str | None,
    *,
    scenario: str = "general",
    snapshot: WorkbenchSnapshot | None = None,
) -> list[dict[str, str]]:
    def action(label: str, action_type: str) -> dict[str, str]:
        return {"label": label, "action": action_type}

    from ...pedagogy.evidence_controls import streak_adapts_without_inventing_live_objects

    leftover_runtime = coach_focus_runtime_from_snapshot(snapshot) if snapshot is not None else {}
    adaptation = (
        snapshot.memory.coaching_adaptation
        if snapshot is not None and snapshot.memory is not None
        else None
    )
    failure_streak = int(getattr(adaptation, "failure_streak", 0) or 0) if adaptation is not None else 0
    success_streak = int(getattr(adaptation, "success_streak", 0) or 0) if adaptation is not None else 0
    live_plan = False
    if snapshot is not None and snapshot.plan is not None:
        if leftover_runtime:
            live_plan = leftover_formal_plan_is_live_for_fill(
                plan=snapshot.plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
        else:
            live_plan = bool(
                str(getattr(snapshot.plan, "id", "") or getattr(snapshot.plan, "plan_id", "") or "").strip()
                or str(snapshot.plan.current_step or "").strip()
            )
    live_task = bool(
        snapshot is not None
        and snapshot.current_task is not None
        and str(
            snapshot.current_task.title
            or snapshot.current_task.natural_language_goal
            or ""
        ).strip()
    )
    workspace = (
        snapshot.memory.workspace
        if snapshot is not None and snapshot.memory is not None and isinstance(snapshot.memory.workspace, dict)
        else {}
    )
    chip_workspace_id = str(
        (workspace.get("workspace_id") or workspace.get("workspaceId") or "")
        if isinstance(workspace, dict)
        else ""
    ).strip()
    if not chip_workspace_id and snapshot is not None:
        chip_workspace_id = str(getattr(snapshot, "workspace_id", "") or "").strip()
    live_card = bool(
        chip_workspace_id
        and deps.runtime.memory_service.live_selected_training_card_id(chip_workspace_id)
    )
    if streak_adapts_without_inventing_live_objects(
        failure_streak=failure_streak,
        success_streak=success_streak,
        live_plan=live_plan,
        live_task=live_task,
        live_card=live_card,
    ):
        if failure_streak >= 2:
            labels = deps.localized_actions(
                response_language,
                [
                    "Give me a smaller hint for this blocked slice",
                    "Review the failing check before widening",
                    "Stay with repair. Do not generate a plan or task",
                ],
                [
                    "先给这个卡住的切片一个更小的提示",
                    "先评审失败检查，不要扩大范围",
                    "先修好这一步，不要生成计划或任务",
                ],
            )
            return [
                action(labels[0], "hint"),
                action(labels[1], "review"),
                action(labels[2], "hint"),
            ]
        labels = deps.localized_actions(
            response_language,
            [
                "Ask a harder question on this same slice",
                "Name where this should transfer next",
                "Stay awaiting a second workspace before calling it global",
            ],
            [
                "就这一步再问一个更难的问题",
                "先说出下一步该迁移到哪里",
                "先等到第二个工作区，不要当成全局掌握",
            ],
        )
        return [
            action(labels[0], "hint"),
            action(labels[1], "hint"),
            action(labels[2], "hint"),
        ]
    from ...pedagogy.context_pressure import (
        normalize_project_complexity,
        pressure_adapts_without_inventing_live_objects,
    )

    time_budget = (
        str(getattr(adaptation, "time_budget", "normal") or "normal")
        if adaptation is not None
        else "normal"
    )
    task_urgency = (
        str(getattr(adaptation, "task_urgency", "medium") or "medium")
        if adaptation is not None
        else "medium"
    )
    project_complexity = (
        str(getattr(adaptation, "project_complexity", "moderate") or "moderate")
        if adaptation is not None
        else "moderate"
    )
    if workspace.get("project_complexity") and normalize_project_complexity(
        workspace.get("project_complexity")
    ) == "complex":
        project_complexity = "complex"
    current_ability = str(
        workspace.get("current_ability") or workspace.get("currentAbility") or ""
    ).strip()
    user_preference = str(
        workspace.get("latest_user_feedback_kind")
        or workspace.get("latestUserFeedbackKind")
        or ""
    ).strip()
    if not user_preference:
        from ...pedagogy.context_pressure import preference_equivalent_from_strategy_bias

        user_preference = preference_equivalent_from_strategy_bias(
            challenge_level=(
                str(getattr(adaptation, "challenge_level", "") or "")
                if adaptation is not None
                else ""
            ),
            hint_depth=(
                str(getattr(adaptation, "hint_depth", "") or "")
                if adaptation is not None
                else ""
            ),
            next_step_bias=(
                str(getattr(adaptation, "next_step_bias", "") or "")
                if adaptation is not None
                else ""
            ),
            feedback_next_step_bias=str(
                workspace.get("feedback_next_step_bias")
                or workspace.get("feedbackNextStepBias")
                or ""
            ),
        )
    from ...pedagogy.evidence_controls import (
        analyze_learning_evidence,
        pedagogy_evidence_confidence,
    )

    outcomes = []
    if snapshot is not None and getattr(snapshot, "memory", None) is not None:
        outcomes = list(getattr(snapshot.memory, "learning_outcomes", []) or [])
    evidence_signals = analyze_learning_evidence(outcomes)
    if pressure_adapts_without_inventing_live_objects(
        time_budget=time_budget,
        task_urgency=task_urgency,
        project_complexity=project_complexity,
        current_ability=current_ability,
        user_preference=user_preference,
        evidence_confidence=pedagogy_evidence_confidence(
            verified_success=bool(evidence_signals.verified_success),
            success_count=int(evidence_signals.success_count or 0),
            outcomes=outcomes,
        ),
        live_plan=live_plan,
        live_task=live_task,
        live_card=live_card,
    ):
        labels = deps.localized_actions(
            response_language,
            [
                "Give me a smaller hint for this short session",
                "Stay with one thin slice before widening",
                "Stay with repair. Do not generate a plan, card, or task",
            ],
            [
                "先给这个短会话一个更小的提示",
                "先守住一个薄切片，不要扩大范围",
                "先修好这一步，不要生成计划、卡片或任务",
            ],
        )
        return [
            action(labels[0], "hint"),
            action(labels[1], "hint"),
            action(labels[2], "hint"),
        ]
    if scenario == "review":
        has_live_evaluation = bool(
            snapshot is not None
            and snapshot.evaluation is not None
            and str(
                getattr(snapshot.evaluation, "next_step", "")
                or getattr(snapshot.evaluation, "summary", "")
                or ""
            ).strip()
        )
        if not has_live_evaluation:
            labels = deps.localized_actions(
                response_language,
                [
                    "Name the failing path from current evidence",
                    "Ask one clarifying question about the error",
                    "Stay with diagnosis before generating a plan or task",
                ],
                [
                    "先从当前证据里点出失败路径",
                    "先问一个关于这个错误的澄清问题",
                    "先诊断，不要生成计划或任务",
                ],
            )
            return [
                action(labels[0], "hint"),
                action(labels[1], "hint"),
                action(labels[2], "hint"),
            ]
        labels = deps.localized_actions(
            response_language,
            [
                "Review the top fix first",
                "Give me a smaller review hint",
                "Review again after the patch",
            ],
            [
                "\u5148\u6cbf\u7740 review \u7ed3\u679c\u4fee\u6700\u5173\u952e\u7684\u95ee\u9898",
                "\u7ed9\u6211\u66f4\u5c0f\u7684 review \u63d0\u793a",
                "\u6539\u5b8c\u540e\u91cd\u65b0 review",
            ],
        )
        return [
            action(labels[0], "review"),
            action(labels[1], "hint"),
            action(labels[2], "retry_review"),
        ]
    if scenario == "debug_loop":
        labels = deps.localized_actions(
            response_language,
            [
                "Name the first pause point from current evidence",
                "Ask one clarifying question about the failing path",
                "Stay with diagnosis before generating a plan or task",
            ],
            [
                "先从当前证据里点出第一个停点",
                "先问一个关于失败路径的澄清问题",
                "先诊断，不要生成计划或任务",
            ],
        )
        return [
            action(labels[0], "hint"),
            action(labels[1], "hint"),
            action(labels[2], "hint"),
        ]
    if scenario == "onboarding" or (
        scenario == "general"
        and deps.first_look_recommended_next_from_snapshot(snapshot)
        and not (
            snapshot is not None
            and snapshot.current_task is not None
            and str(
                snapshot.current_task.title
                or snapshot.current_task.natural_language_goal
                or ""
            ).strip()
        )
    ):
        first_look_next = deps.first_look_recommended_next_from_snapshot(snapshot)
        compact_next = first_look_next[:72].rstrip()
        if compact_next:
            labels = deps.localized_actions(
                response_language,
                [
                    "Continue from this first look",
                    "Ask one clarifying question",
                    compact_next,
                ],
                [
                    "从这次第一眼判断继续",
                    "先问一个澄清问题",
                    compact_next,
                ],
            )
        else:
            labels = deps.localized_actions(
                response_language,
                [
                    "Continue understanding this workspace",
                    "Ask one clarifying question",
                    "Stay with conversation before generating a plan",
                ],
                [
                    "继续理解这个工作区",
                    "先问一个澄清问题",
                    "先对话，不要生成计划",
                ],
            )
        return [
            action(labels[0], "hint"),
            action(labels[1], "hint"),
            action(labels[2], "hint"),
        ]
    if scenario == "plan":
        labels = deps.localized_actions(
            response_language,
            [
                "Plan today's steps around this stage",
                "Pick the next task from this stage",
                "Adjust the plan around my current pace",
            ],
            [
                "\u56f4\u7ed5\u8fd9\u4e2a\u9636\u6bb5\u89c4\u5212\u4eca\u5929\u7684\u6b65\u9aa4",
                "\u4ece\u8fd9\u4e2a\u9636\u6bb5\u91cc\u6311\u4e0b\u4e00\u9053\u4efb\u52a1",
                "按我当前节奏微调计划",
            ],
        )
        return [
            action(labels[0], "plan"),
            action(labels[1], "next_task"),
            action(labels[2], "plan"),
        ]
    if scenario == "task":
        labels = deps.localized_actions(
            response_language,
            [
                "Start the first implementation slice",
                "Explain the principle behind this task",
                "Review my implementation after I try",
            ],
            [
                "先完成第一步实现",
                "\u89e3\u91ca\u8fd9\u9898\u80cc\u540e\u7684\u539f\u7406",
                "我做完后帮我评审",
            ],
        )
        return [
            action(labels[0], "task"),
            action(labels[1], "hint"),
            action(labels[2], "review"),
        ]
    if scenario == "next_task":
        labels = deps.localized_actions(
            response_language,
            [
                "Start this next task with one thin slice",
                "Review the result after I land it",
                "Pick another next task only if this slice is done",
            ],
            [
                "\u5148\u7528\u4e00\u4e2a\u6700\u8584\u7684\u5207\u7247\u542f\u52a8\u8fd9\u9053\u4e0b\u4e00\u9898",
                "我落完这一步后继续评审",
                "\u53ea\u6709\u8fd9\u4e00\u6b65\u505a\u5b8c\u4e86\u518d\u7ee7\u7eed\u6311\u4e0b\u4e00\u9898",
            ],
        )
        return [
            action(labels[0], "task"),
            action(labels[1], "review"),
            action(labels[2], "next_task"),
        ]
    if scenario == "idea_implementation":
        labels = deps.localized_actions(
            response_language,
            [
                "Plan the first patch around this idea",
                "Start the thinnest implementation task",
                "Review the slice after I land it",
            ],
            [
                "\u56f4\u7ed5\u8fd9\u4e2a\u60f3\u6cd5\u89c4\u5212\u7b2c\u4e00\u7248 patch",
                "启动一个最小的实现任务",
                "我做完第一步后继续 review",
            ],
        )
        return [
            action(labels[0], "plan"),
            action(labels[1], "task"),
            action(labels[2], "review"),
        ]
    if scenario == "project_adaptation":
        labels = deps.localized_actions(
            response_language,
            [
                "Plan the first adaptation boundary",
                "Pick the safest first adaptation task",
                "Review the boundary after the patch",
            ],
            [
                "\u5148\u89c4\u5212\u7b2c\u4e00\u5c42\u6539\u9020\u8fb9\u754c",
                "先挑最稳妥的第一步改造任务",
                "patch \u843d\u4e0b\u540e\u7ee7\u7eed review \u8fd9\u5c42\u8fb9\u754c",
            ],
        )
        return [
            action(labels[0], "plan"),
            action(labels[1], "task"),
            action(labels[2], "review"),
        ]
    if scenario == "project_sourcing":
        labels = deps.localized_actions(
            response_language,
            [
                "Give me the best outside project to start with",
                "Turn that source into my first training task",
                "Explain why this source fits my goal",
            ],
            [
                "先给我最适合开始的外部项目",
                "把这个来源转成我的第一道训练题",
                "解释为什么这个来源适合我的目标",
            ],
        )
        return [
            action(labels[0], "hint"),
            action(labels[1], "task"),
            action(labels[2], "hint"),
        ]
    if scenario == "principle":
        has_live_task = bool(
            snapshot is not None
            and snapshot.current_task is not None
            and str(
                snapshot.current_task.title
                or snapshot.current_task.natural_language_goal
                or ""
            ).strip()
        )
        labels = deps.localized_actions(
            response_language,
            [
                "Point me to the exact code boundary",
                "Stay with this principle before generating a task",
                "Review whether my patch follows the principle",
            ],
            [
                "把原理落到具体代码边界上",
                "先守住这个原理，不要生成任务",
                "review 我的 patch 有没有真的守住这个原理",
            ],
        )
        if not has_live_task:
            return [
                action(labels[0], "hint"),
                action(labels[1], "hint"),
                action(labels[2], "hint"),
            ]
        return [
            action(labels[0], "hint"),
            action(labels[1], "hint"),
            action(labels[2], "review"),
        ]
    labels = deps.localized_actions(
        response_language,
        [
            "Plan the next step around the current focus",
            "Extract one thin practice task from this",
            "Review the current implementation with me",
        ],
        [
            "\u56f4\u7ed5\u5f53\u524d\u805a\u7126\u70b9\u89c4\u5212\u4e0b\u4e00\u6b65",
            "\u4ece\u8fd9\u91cc\u63d0\u70bc\u4e00\u9053\u5f88\u8584\u7684\u8bad\u7ec3\u9898",
            "结合当前实现继续评审",
        ],
    )
    return [
        action(labels[0], "plan"),
        action(labels[1], "task"),
        action(labels[2], "review"),
    ]


def build_coach_visible_status(deps: CoachSupportDeps,
    agent_meta: dict[str, object] | None,
    *,
    response_language: str | None,
) -> dict[str, object] | None:
    provider_stop_reasons = {
        "invalid_key_or_permission",
        "model_unsupported",
        "model_not_found",
        "malformed_response",
        "rate_limit",
        "upstream_unavailable",
        "timeout",
        "network",
        "unknown",
    }
    if not isinstance(agent_meta, dict):
        return None

    raw_events = agent_meta.get("tool_events")
    tool_call_names: list[str] = []
    tool_call_pairs: list[tuple[str, str]] = []
    practice_verification_result: dict[str, object] | None = None
    had_failure = False
    if isinstance(raw_events, list):
        for item in raw_events:
            if not isinstance(item, dict):
                continue
            event_type = str(item.get("type") or "").strip()
            if event_type == "tool_call":
                tool_name = str(item.get("name") or "").strip()
                if tool_name == "coach_finalize":
                    continue
                raw_args = item.get("arguments")
                call_action = ""
                if isinstance(raw_args, dict):
                    call_action = str(raw_args.get("action") or "").strip().lower()
                if tool_name:
                    tool_call_names.append(tool_name)
                    tool_call_pairs.append((tool_name, call_action))
                continue
            if event_type != "tool_result":
                continue
            result_payload = item.get("result")
            if item.get("ok") is False:
                had_failure = True
            if isinstance(result_payload, dict) and result_payload.get("error"):
                had_failure = True
            tool_name = str(item.get("name") or item.get("tool_name") or "").strip()
            if practice_verification_result is None and isinstance(result_payload, dict):
                if tool_name == "verify_practice_current_file" or (
                    tool_name == "project_verify"
                    and str(result_payload.get("action") or "verify_practice").strip().lower()
                    == "verify_practice"
                    and "passed" in result_payload
                ):
                    practice_verification_result = result_payload

    stop_reason = str(agent_meta.get("stop_reason") or "").strip()
    fell_back = bool(agent_meta.get("fell_back"))
    agent_summary = str(agent_meta.get("summary") or "").strip()
    agent_next_step = deps.strip_visible_next_step_prefix(agent_meta.get("next_step") or "")
    agent_decision = str(agent_meta.get("decision") or "").strip()
    agent_blocker = str(agent_meta.get("blocker") or "").strip()
    agent_teaching_note = str(
        agent_meta.get("teaching_note") or agent_meta.get("teachingNote") or ""
    ).strip()
    agent_confidence = str(agent_meta.get("confidence") or "").strip()
    raw_evidence = agent_meta.get("evidence")
    agent_evidence: list[str] = []
    if isinstance(raw_evidence, list):
        for item in raw_evidence:
            text = str(item).strip()
            if text:
                agent_evidence.append(text)
            if len(agent_evidence) >= 4:
                break

    unique_tool_names = list(dict.fromkeys(tool_call_names))
    if stop_reason == "coach_finalize" and not unique_tool_names:
        return None
    if (
        not tool_call_names
        and not fell_back
        and stop_reason
        not in {
            "completed",
            "empty_response",
            "language_corruption",
            "no_progress",
            "timeout",
            "provider_error",
            "max_steps",
            *provider_stop_reasons,
        }
        and not stop_reason.startswith("agent_error")
    ):
        return None

    categories: set[str] = set()
    for tool_name, call_action in tool_call_pairs:
        if tool_name in {"recall_memory", "record_learning_note"}:
            categories.add("memory")
        elif tool_name == "inspect_plan":
            categories.add("plan")
        elif tool_name in {"search_resources", "library_read", "library_write", "library_exec", "web_fetch"}:
            categories.add("resources")
        elif tool_name in {"read_workspace_file", "list_workspace_files", "project_read"}:
            categories.add("workspace")
        elif tool_name == "run_diagnostics":
            categories.add("diagnostics")
        elif tool_name == "project_verify":
            if call_action == "diagnostics":
                categories.add("diagnostics")
            elif call_action in {"verify_practice", "rubric_review", "compare_anchor"}:
                categories.add("training")
            else:
                categories.add("workspace")
        elif tool_name == "learning_inspect":
            if call_action == "plan":
                categories.add("plan")
            else:
                categories.add("memory")
        elif tool_name == "learning_action":
            if call_action in {"save_formal_plan", "specify_task", "next_task"}:
                categories.add("plan")
            elif call_action == "record_note":
                categories.add("memory")
        elif tool_name == "generate_training_card":
            categories.add("training")

    if (
        stop_reason in {"timeout", "provider_error"}
        or stop_reason in provider_stop_reasons
        or stop_reason.startswith("agent_error")
    ):
        status = "blocked"
        summary = agent_summary or localized_text(
            "A deeper coach check got blocked, so I kept the reply on the safest next step.",
            "这一轮更深一层的教练检查被阻塞了，所以我把回复收在最稳妥的下一步。",
            response_language,
        )
    elif fell_back or had_failure or stop_reason == "max_steps":
        status = "degraded"
        summary = localized_text(
            "A deeper coach check degraded, so I kept the reply on the safest next step.",
            "这一轮更深一层的教练检查有降级，所以我把回复收在最稳妥的下一步。",
            response_language,
        )
    elif categories == {"memory"}:
        status = "done"
        summary = localized_text(
            "I re-anchored on your recent learning thread before answering.",
            "回答前我先重新对齐了你最近的学习主线。",
            response_language,
        )
    elif categories == {"plan"}:
        status = "done"
        summary = localized_text(
            "I aligned this reply with the current plan before answering.",
            "回答前我先对齐了当前计划。",
            response_language,
        )
    elif categories == {"resources"}:
        status = "done"
        summary = localized_text(
            "I checked the relevant resources before answering.",
            "回答前我先核对了相关资料。",
            response_language,
        )
    elif "workspace" in categories and "diagnostics" in categories:
        status = "done"
        summary = localized_text(
            "I inspected the code path and ran a quick check before answering.",
            "回答前我先检查了代码路径，并跑了一次快速校验。",
            response_language,
        )
    elif categories == {"workspace"}:
        status = "done"
        summary = localized_text(
            "I inspected the current code path before answering.",
            "回答前我先检查了当前代码路径。",
            response_language,
        )
    elif categories == {"training"}:
        status = "done"
        summary = localized_text(
            "I prepared the next training move before answering.",
            "回答前我先整理了下一步训练动作。",
            response_language,
        )
    elif categories:
        status = "done"
        summary = localized_text(
            "I checked the relevant context before answering.",
            "回答前我先核对了相关上下文。",
            response_language,
        )
    else:
        status = "done"
        summary = localized_text(
            "I tightened the coaching context before answering.",
            "回答前我先收紧了这一轮教练上下文。",
            response_language,
        )

    display_kind: str | None = None
    next_step = agent_next_step
    resume_thread: str | None = None
    detail: str | None = None
    if isinstance(practice_verification_result, dict):
        display_kind = "practice_verification"
        passed = bool(practice_verification_result.get("passed"))
        verification_summary = str(practice_verification_result.get("summary") or "").strip()
        verification_next_step = deps.strip_visible_next_step_prefix(
            practice_verification_result.get("next_step") or ""
        )
        status = "done" if passed else "degraded"
        if passed:
            summary = verification_summary or localized_text(
                "The active IDE file matches the supplied practice acceptance signals with no blocking diagnostics.",
                "当前 IDE 文件与提供的练习验收信号一致，没有阻塞性诊断。",
                response_language,
            )
            detail = verification_summary or (
                agent_summary if agent_summary and agent_summary != summary else None
            )
        else:
            summary = localized_text(
                "The active IDE file still needs one more signal before this practice can pass.",
                "当前 IDE 文件还差一个信号，才能通过这次练习。",
                response_language,
            )
            detail = verification_summary or (
                agent_summary if agent_summary and agent_summary != summary else None
            )
        if verification_next_step:
            next_step = verification_next_step
        elif not next_step:
            next_step = localized_text(
                "Patch the missing signal, then verify the current file again.",
                "补上缺失的信号，然后重新验证当前文件。",
                response_language,
            )
    elif stop_reason == "completed" and not unique_tool_names:
        status = "done"
        summary = localized_text(
            "I answered directly from the current thread.",
            "我直接根据当前主线作答。",
            response_language,
        )
        detail = localized_text(
            "No extra tool lookup was needed.",
            "不需要额外查工具。",
            response_language,
        )
    elif stop_reason == "language_corruption":
        status = "blocked"
        summary = localized_text(
            "The provider corrupted Chinese input before the model saw it, so I kept the recovery path explicit.",
            "provider 在模型看到消息前把中文输入破坏了，所以我把恢复路径直接保留在这里。",
            response_language,
        )
        detail = agent_blocker or summary
        if not next_step:
            next_step = localized_text(
                "Switch provider or gateway, or retry this check in English first.",
                "先切换 provider / gateway，或先用 English 重试这条链路。",
                response_language,
            )
    elif stop_reason == "language_corruption_recovered":
        status = "degraded"
        summary = agent_summary or localized_text(
            "The provider reply came back degraded, so I kept the lesson moving with a local recovery scaffold.",
            "这次 provider 的回复不够干净，所以我先用本地恢复脚手架把这轮教学接住。",
            response_language,
        )
        detail = agent_teaching_note or localized_text(
            "I kept the same coaching lane and turned the next move into a local, verifiable step.",
            "我把这一轮继续留在原来的教学主线里，并把下一步收束成一个本地可验证的小动作。",
            response_language,
        )
        if not next_step:
            next_step = localized_text(
                "Keep going with the next small verifiable move on this same lane.",
                "继续沿着同一条主线做下一个可验证的小动作。",
                response_language,
            )
        resume_thread = deps.build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
    elif stop_reason in provider_stop_reasons:
        status = "blocked"
        summary = agent_summary or localized_text(
            "The provider blocked this coaching turn before it could finish.",
            "provider 在这轮教练对话完成前把它挡住了。",
            response_language,
        )
        detail = agent_blocker or summary
        if not next_step:
            next_step = localized_text(
                "Fix the provider path, then resend this exact turn.",
                "先修好 provider 链路，再原样重发这一轮。",
                response_language,
            )
        resume_thread = deps.build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
    elif stop_reason == "empty_response":
        status = "degraded"
        summary = agent_summary or localized_text(
            "The provider returned an empty visible answer, so I kept the thread on the safest next step.",
            "模型返回了空内容，所以我把这一轮收在最稳妥的下一步。",
            response_language,
        )
        detail = agent_blocker or summary
        if not next_step:
            next_step = localized_text(
                "Retry the turn and require a visible conclusion.",
                "重新发起这一轮，并要求给出可见结论。",
                response_language,
            )
        resume_thread = deps.build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
    elif stop_reason == "no_progress":
        status = "degraded"
        tool_path = ", ".join(unique_tool_names[:3])
        summary = localized_text(
            f"The model repeated the same tool path{f': {tool_path}' if tool_path else ''} without new evidence.",
            f"模型重复了同样的工具路径{f'：{tool_path}' if tool_path else ''}，但没有带来新的证据。",
            response_language,
        )
        detail = agent_summary if agent_summary and agent_summary != summary else localized_text(
            "The turn stayed on the same thread so the next step can switch evidence sources.",
            "这一轮仍停在同一条主线上，所以下一步需要换一个证据来源。",
            response_language,
        )
        if not next_step:
            next_step = localized_text(
                f"Try a different evidence source, then decide whether {tool_path or 'this path'} is still the right path.",
                f"先换一个证据来源，再判断 {tool_path or '这条路径'} 是否仍然合适。",
                response_language,
            )
        resume_thread = deps.build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
    if not detail and unique_tool_names:
        tool_labels = [
            deps.localized_agent_tool_label(tool_name, response_language)
            for tool_name in unique_tool_names[:4]
        ]
        detail = localized_text(
            f"Used {len(unique_tool_names)} tool step{'s' if len(unique_tool_names) != 1 else ''}: {', '.join(tool_labels)}.",
            f"做了 {len(unique_tool_names)} 个工具步骤：{', '.join(tool_labels)}。",
            response_language,
        )

    status_part: dict[str, object] = {
        "type": "coach_visible_status",
        "status": status,
        "summary": summary,
        "source": (
            "resource_context"
            if agent_meta.get("auto_resource_lookup") is True
            and agent_meta.get("agentic") is not True
            else "agent_loop"
        ),
    }
    if stop_reason:
        status_part["stopReason"] = stop_reason
    if display_kind:
        status_part["displayKind"] = display_kind
    if detail:
        status_part["detail"] = detail
    if next_step:
        status_part["nextStep"] = next_step
    if resume_thread:
        status_part["resumeThread"] = resume_thread
    if agent_decision:
        status_part["decision"] = agent_decision
    if agent_blocker:
        status_part["blocker"] = agent_blocker
    if agent_teaching_note:
        status_part["teachingNote"] = agent_teaching_note
    if agent_confidence:
        status_part["confidence"] = agent_confidence
    if agent_evidence:
        status_part["evidence"] = agent_evidence
    if unique_tool_names:
        status_part["toolNames"] = unique_tool_names[:4]
        status_part["stepCount"] = len(tool_call_names)
    return status_part


def build_plan_runtime_status(deps: CoachSupportDeps,
    *,
    workspace_id: str,
    snapshot: WorkbenchSnapshot,
    response_language: str | None,
    profile: UserProfile | None,
    coach_turn: dict[str, object] | None = None,
    agent_meta: dict[str, object] | None = None,
) -> dict[str, object]:
    active_stage = deps.active_plan_stage(snapshot.plan)
    due_reviews = snapshot.memory.due_reviews[:3]
    workspace = snapshot.memory.workspace if isinstance(snapshot.memory.workspace, dict) else {}
    recovered_status = plan_runtime_status_from_recovery(
        workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
        workspace_id,
    )
    leftover_runtime = recovered_status or coach_focus_runtime_from_snapshot(snapshot)
    next_action = live_coaching_next_step(
        plan=snapshot.plan,
        task=snapshot.current_task,
        runtime=leftover_runtime,
        existing=leftover_runtime,
        next_step=snapshot.coaching_state.next_step if snapshot.coaching_state else "",
        task_title=(
            str(getattr(snapshot.current_task, "title", "") or "")
            if snapshot.current_task
            else ""
        ),
    )
    if leftover_coach_turn_chrome_is_not_live(
        runtime=leftover_runtime,
        existing=leftover_runtime,
    ):
        next_action = ""
    if not next_action and snapshot.current_task and snapshot.current_task.natural_language_goal.strip():
        leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
        next_action = live_task_suggested_title(
            plan=snapshot.plan,
            task=snapshot.current_task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            title=snapshot.current_task.natural_language_goal,
            goal=snapshot.current_task.natural_language_goal,
            task_title=snapshot.current_task.title,
        )
    if (
        not next_action
        and recovered_status is not None
        and snapshot.plan is not None
    ):
        # Orphaned pressure-only runtime without a formal plan must not invent
        # next_action / task-shaped hints from leftover current_step alone.
        next_action = str(
            recovered_status.get("current_step")
            or recovered_status.get("next_after_current")
            or ""
        ).strip()
    if not next_action and recovered_status is None:
        first_look = (
            snapshot.memory.workspace_understanding.first_look_summary
            if snapshot.memory.workspace_understanding is not None
            else None
        )
        next_action = str(getattr(first_look, "recommended_next_step", "") or "").strip()
    active_thread = snapshot.memory.active_thread
    leftover_runtime = recovered_status or coach_focus_runtime_from_snapshot(snapshot)
    leftover_fields = live_plan_overlay_fields(
        plan=snapshot.plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
        task_title=str(getattr(snapshot.current_task, "title", "") or "") if snapshot.current_task else "",
    )
    leftover_live = leftover_formal_plan_is_live_for_fill(
        plan=snapshot.plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
    )
    leftover_labels = leftover_formal_training_labels(
        plan=snapshot.plan,
        live_plan=leftover_live,
        live_task=True,
    )
    leftover_verify = (
        {
            str(item).strip()
            for item in (snapshot.plan.verify_method or [])
            if str(item).strip()
        }
        if snapshot.plan is not None and not leftover_live
        else set()
    )
    leftover_blocked = (
        str(snapshot.plan.blocked_reason or "").strip()
        if snapshot.plan is not None and not leftover_live
        else ""
    )
    current_step = leftover_fields["current_step"]
    why_now = leftover_fields["why_now"]
    verify_method = list(leftover_fields["verify_method"])
    blocked_reason = leftover_fields["blocked_reason"]
    next_after_current = leftover_fields["next_after_current"]
    structured_signal = deps.structured_plan_progress_signal(
        snapshot=snapshot,
        coach_turn=coach_turn,
    )
    # Scoped runtime is authoritative. A conversational next-step suggestion
    # must not replace the bound plan step during an ordinary resume turn.
    # Explicit plan commits and verified advances persist their runtime first.
    project_lane = str((coach_turn or {}).get("scenario") or "") in {
        "idea_implementation", "project_adaptation", "project_idea", "project_sourcing",
    }
    if structured_signal and (recovered_status is None or project_lane):
        structured_step = str(structured_signal.get("current_step") or "").strip()
        structured_why = str(structured_signal.get("why_now") or "").strip()
        structured_next = str(structured_signal.get("next_after_current") or "").strip()
        structured_blocked = str(structured_signal.get("blocked_reason") or "").strip()
        structured_verify_method = structured_signal.get("verify_method")
        if leftover_live:
            current_step = structured_step or current_step
            why_now = structured_why or why_now
            if isinstance(structured_verify_method, list):
                verify_method = [
                    str(item).strip() for item in structured_verify_method if str(item).strip()
                ]
            next_after_current = structured_next or next_after_current
            if structured_blocked:
                blocked_reason = structured_blocked
        else:
            if structured_step and structured_step not in leftover_labels:
                current_step = structured_step
            if structured_why and structured_why not in leftover_labels:
                why_now = structured_why
            if isinstance(structured_verify_method, list):
                gated_verify = [
                    str(item).strip()
                    for item in structured_verify_method
                    if str(item).strip()
                    and str(item).strip() not in leftover_labels
                    and str(item).strip() not in leftover_verify
                ]
                if gated_verify:
                    verify_method = gated_verify
            if structured_next and structured_next not in leftover_labels:
                next_after_current = structured_next
            if (
                structured_blocked
                and structured_blocked not in leftover_labels
                and structured_blocked != leftover_blocked
            ):
                blocked_reason = structured_blocked
    overlaid = {
        "current_step": current_step,
        "why_now": why_now,
        "verify_method": verify_method,
        "blocked_reason": blocked_reason,
        "next_after_current": next_after_current,
    }
    current_step = overlaid["current_step"]
    why_now = overlaid["why_now"]
    verify_method = list(overlaid["verify_method"])
    blocked_reason = overlaid["blocked_reason"]
    next_after_current = overlaid["next_after_current"]
    live_stage = overlay_plan_runtime_current_stage(
        plan_stage={
            "id": getattr(active_stage, "id", None),
            "title": getattr(active_stage, "title", None),
            "goal": getattr(active_stage, "goal", None),
            "status": getattr(active_stage, "status", None),
        }
        if active_stage
        else None,
        plan_current_step=str(getattr(snapshot.plan, "current_step", "") or "") if snapshot.plan else "",
        recovered=recovered_status,
    )
    if live_stage is not None:
        live_stage_id = (
            str(live_stage.get("id") or (recovered_status or {}).get("current_stage_id") or "").strip()
            or None
        )
    elif recovered_status is not None and snapshot.plan is not None:
        live_stage_id = None
    elif recovered_status is not None:
        live_stage_id = str(recovered_status.get("current_stage_id") or "").strip() or None
    else:
        live_stage_id = None
    next_step_hint = deps.build_next_step_hint(
        snapshot=snapshot,
        response_language=response_language,
        current_step=current_step or next_action,
        why_now=why_now,
        verify_method=verify_method,
        coach_turn=coach_turn,
        agent_meta=agent_meta,
    )
    return {
        "current_stage": live_stage,
        "current_main_thread": {
            "scenario": active_thread.scenario,
            "focus_area": active_thread.focus_area,
            "summary": active_thread.summary,
            "next_step": active_thread.next_step,
            "blocker": active_thread.blocker,
            "current_step": current_step,
            "why_now": why_now,
            "verify_method": verify_method,
            "blocked_reason": blocked_reason,
            "next_after_current": next_after_current,
            "verified_result": active_thread.verified_result,
        }
        if active_thread
        else {
            "focus_area": snapshot.memory.current_focus or "",
            "summary": snapshot.coaching_state.summary if snapshot.coaching_state else "",
            "next_step": next_action,
            "blocker": blocked_reason,
            "current_step": current_step,
            "why_now": why_now,
            "verify_method": verify_method,
            "blocked_reason": blocked_reason,
            "next_after_current": next_after_current,
        },
        "current_step": current_step,
        "why_now": why_now,
        "verify_method": verify_method,
        "blocked_reason": blocked_reason,
        "next_after_current": next_after_current,
        "plan_id": (
            str((recovered_status or {}).get("plan_id") or (recovered_status or {}).get("planId") or "")
            or (
                str(getattr(snapshot.plan, "id", "") or getattr(snapshot.plan, "plan_id", "") or "")
                if leftover_live
                else ""
            )
            or None
        ),
        "review_points": [
            {
                "concept": item.concept,
                "reason": item.reason,
                "severity": item.severity,
                "due_at": item.due_at,
                "source": item.source,
                "surface_mode": item.surface_mode,
                "task_hint": item.task_hint,
                "focus_area": item.focus_area,
                "linked_context": item.linked_context,
                "interval_days": item.interval_days,
                "mastery_score": item.mastery_score,
            }
            for item in due_reviews
        ],
        "coach_judgment": {
            "summary": (
                ""
                if leftover_coach_turn_chrome_is_not_live(
                    runtime=leftover_runtime,
                    existing=leftover_runtime,
                )
                else (snapshot.coaching_state.summary if snapshot.coaching_state else "")
            ),
            "teaching_goal": (
                ""
                if leftover_coach_turn_chrome_is_not_live(
                    runtime=leftover_runtime,
                    existing=leftover_runtime,
                )
                else (snapshot.coaching_state.teaching_goal if snapshot.coaching_state else "")
            ),
            "intervention_strategy": (
                snapshot.coaching_state.intervention_strategy if snapshot.coaching_state else ""
            ),
            "support_strategy": (
                ""
                if leftover_coach_turn_chrome_is_not_live(
                    runtime=leftover_runtime,
                    existing=leftover_runtime,
                )
                else (snapshot.coaching_state.support_strategy if snapshot.coaching_state else "")
            ),
            "resume_thread": (
                ""
                if leftover_coach_turn_chrome_is_not_live(
                    runtime=leftover_runtime,
                    existing=leftover_runtime,
                )
                else (snapshot.coaching_state.resume_thread if snapshot.coaching_state else "")
            ),
        },
        "next_training_action": next_action,
        "next_step_hint": next_step_hint,
        "review_queue_summary": (
            ""
            if leftover_coach_turn_chrome_is_not_live(
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            else snapshot.review_queue_summary
        ),
        "next_review_due": snapshot.next_review_due,
        "recovered": recovered_status is not None,
        "current_stage_id": live_stage_id,
        "resume_state": (
            str(recovered_status.get("resume_state") or "interrupted").strip()
            if recovered_status is not None
            else None
        ),
        "request_id": (
            str(recovered_status.get("request_id") or "").strip() or None
            if recovered_status is not None
            else None
        ),
        "revision": recovered_status.get("revision") if recovered_status is not None else None,
        **(
            {
                "verify_plan_advance": dict(recovered_status["verify_plan_advance"])
            }
            if isinstance(recovered_status, dict)
            and isinstance(recovered_status.get("verify_plan_advance"), dict)
            and recovered_status.get("verify_plan_advance")
            else {}
        ),
    }
