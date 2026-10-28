"""Coach turn helpers moved out of build_router (§五十二 extraction).

The helpers share one dependency bundle (``CoachSupportDeps``) assembled by
``build_router``. Keeping the bundle explicit makes the closure graph visible
instead of hiding 45 names inside a 25k-line function.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict, cast, get_args
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from ..core.models import (
    AgentMeta,
    ChatMessage,
    CoachDefaults,
    CoachingState,
    CoachScenario,
    CoachTurnSummary,
    EvaluateCurrentFileRequest,
    FirstLookSummary,
    LearnerState,
    LearningPlan,
    SessionMessageRequest,
    SessionMessageResponse,
    SuggestedAction,
    TaskSpec,
    TaskSpecifyRequest,
    TeachingDecision,
    TeachingKnowledgeAsset,
    TurnRequest,
    UserProfile,
    WorkbenchSnapshot,
)
from ..llm.prompts import infer_coaching_scenario as infer_message_coaching_scenario
from ..llm.prompts import infer_learner_signal as infer_message_learner_signal
from ..llm.provider_service import (
    ProviderService,
)
from ..llm.training_review_context import active_training_review, apply_training_review_context
from ..llm.turn_grounding import (
    GroundingDecision,
    sanitize_memory_anchor,
)
from ..memory.note_request import message_requests_explicit_learning_note
from ..memory.workspace_recovery import (
    PLAN_RUNTIME_KEY,
    accept_plan_runtime_resume_request,
    coach_focus_runtime_from_snapshot,
    leftover_bound_plan_competing_identity_labels,
    leftover_coach_conversation_is_not_live,
    leftover_coach_turn_chrome_is_not_live,
    leftover_evaluation_headline_is_not_live,
    leftover_first_look_headline_is_not_live,
    leftover_formal_plan_is_live_for_fill,
    leftover_formal_training_labels,
    leftover_minting_suggested_actions_are_not_live,
    leftover_resource_library_list_is_not_live,
    leftover_resource_sandbox_preview_is_not_live,
    leftover_resource_sandbox_state_is_not_live,
    leftover_resource_selected_detail_is_not_live,
    leftover_settings_learner_project_onboarding_is_not_live,
    leftover_settings_profile_rhythm_is_not_live,
    leftover_streaming_checkpoint_is_not_live,
    leftover_suggested_actions_is_not_live,
    leftover_task_guide_focus_is_not_live,
    leftover_training_handoff_chrome_is_not_live,
    leftover_transfer_skill_is_not_live,
    live_coaching_next_step,
    live_evidence_binding,
    live_leftover_focus_candidate,
    live_plan_overlay_fields,
    live_plan_update_persist_chrome,
    live_task_converted_copy,
    live_task_focus_area,
    live_task_picked_copy,
    live_task_suggested_title,
    live_task_thin_slice_copy,
    overlay_plan_runtime_current_stage,
    plan_runtime_status_from_recovery,
    prefer_recovered_coach_turn_chrome,
    prefer_recovered_training_focus_chrome,
    prefer_recovered_training_handoff_chrome,
    prefer_recovered_transfer_skill,
    resource_record_is_acknowledged_upload,
    stamp_produced_workspace_record,
)
from ..training.card_request import message_requests_explicit_training_card
from ._helpers import (
    localized_text,
    looks_like_mojibake_text,
    prefers_chinese,
    supported_response_language,
)
from .router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from .router_support import (
    _resolve_agent_loop_enabled,
    _stamp_library_sandbox_work,
)
from .router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from .training_return_feedback import completed_return_feedback


class CoachTurnPayload(TypedDict):
    """Stable data returned by ``resolve_coach_turn`` to every reply path."""

    scenario: str
    learner_signal: str
    coach_context: dict[str, object]
    suggested_actions: list[dict[str, object]]
    artifacts: dict[str, object]
    coach_turn: CoachTurnSummary
    stream: bool
    # Optional payload members written by the grounding assembly step: the
    # user-facing downgrade flag and the per-turn cached decision (DESIGN.md
    # §2.3: "缓存于 payload 私有键"; applied exactly once per turn).
    requires_confirmation: NotRequired[bool]
    _grounding_decision: NotRequired[GroundingDecision]
    _grounding_memory_provenance: NotRequired[dict[str, str]]
    _grounding_evaluated_next_step: NotRequired[str]


@dataclass(frozen=True, slots=True)
class CoachSupportDeps:
    runtime: Any
    GROUNDING_MEMORY_PROVENANCE_CACHE_KEY: Any
    GUIDED_LANE_SCENARIOS: Any
    active_plan_stage: Callable[..., Any]
    active_view_coaching_lane_override: Callable[..., Any]
    active_view_owns_turn_lane: Callable[..., Any]
    artifact_payload: Callable[..., Any]
    attach_plan_runtime_status: Callable[..., Any]
    build_next_step_hint: Callable[..., Any]
    build_resume_thread_text: Callable[..., Any]
    coach_artifact_title: Callable[..., Any]
    coach_focus_bundle: Callable[..., Any]
    continuation_step_needs_local_repair: Callable[..., Any]
    derive_coaching_state: Callable[..., Any]
    display_focus_label: Callable[..., Any]
    exercise_lines: Callable[..., Any]
    extract_lane_continuation_step: Callable[..., Any]
    first_look_recommended_next_from_snapshot: Callable[..., Any]
    function_guidance_current_file_name: Callable[..., Any]
    generic_guided_review_fallback_needs_repair: Callable[..., Any]
    guided_focus_display_value: Callable[..., Any]
    honest_suggested_actions_without_live_object: Callable[..., Any]
    is_provider_recovery_thread_payload: Callable[..., Any]
    leftover_runtime_for_workspace: Callable[..., Any]
    live_stage_object_label: Callable[..., Any]
    local_continuation_step_for_scenario: Callable[..., Any]
    localized_actions: Callable[..., Any]
    localized_agent_tool_label: Callable[..., Any]
    message_requests_lane_continuation: Callable[..., Any]
    normalize_active_view_name: Callable[..., Any]
    normalize_answer_mode: Callable[..., Any]
    normalized_object_mapping: Callable[..., Any]
    provider_recovery_resumed_next_step: Callable[..., Any]
    provider_recovery_resumed_summary: Callable[..., Any]
    recovered_overlay_without_live_object: Callable[..., Any]
    recovery_turn_has_no_learning_evidence: Callable[..., Any]
    render_artifact_content: Callable[..., Any]
    resolve_focus_hint: Callable[..., Any]
    resolve_turn_focus_hint: Callable[..., Any]
    resource_grounding_turn_prefers_fresh_lane: Callable[..., Any]
    should_preserve_active_thread_for_turn: Callable[..., Any]
    stateful_focus_area: Callable[..., Any]
    strip_visible_next_step_prefix: Callable[..., Any]
    structured_plan_progress_signal: Callable[..., Any]
    structured_suggested_actions: Callable[..., Any]
    summarize_review_queue: Callable[..., Any]
    GUIDED_VISIBLE_REPAIR_SCENARIOS: Any
    PROVIDER_REPLY_STOP_REASONS: Any
    _resolve_context_tier: Callable[..., Any]
    active_thread_scenario_value: Callable[..., Any]
    advance_plan_after_evaluation: Callable[..., Any]
    answer_mode_preference_for_persistence: Callable[..., Any]
    apply_agent_meta_to_coaching_state: Callable[..., Any]
    apply_attachment_delivery_metadata: Callable[..., Any]
    apply_auto_resource_agent_evidence: Callable[..., Any]
    apply_grounding_decision: Callable[..., Any]
    apply_guided_lane_visible_fallback: Callable[..., Any]
    apply_guided_training_visible_fallback: Callable[..., Any]
    apply_language_corruption_override: Callable[..., Any]
    apply_next_step_grounding_policy: Callable[..., Any]
    apply_pedagogy_snapshot: Callable[..., Any]
    auto_lane_learn_first_force_training_card: Callable[..., Any]
    auto_preference_requests_training_card: Callable[..., Any]
    auto_resource_lookup_tool_events: Callable[..., Any]
    build_assistant_metadata: Callable[..., Any]
    build_coach_context: Callable[..., Any]
    build_coaching_service: Callable[..., Any]
    build_conversation_history: Callable[..., Any]
    build_empty_response_visible_reply: Callable[..., Any]
    build_grounded_resource_contract_visible_fallback: Callable[..., Any]
    build_guided_lane_stable_visible_reply: Callable[..., Any]
    build_guided_training_visible_fallback: Callable[..., Any]
    build_local_sequence_visible_fallback: Callable[..., Any]
    build_session_response: Callable[..., Any]
    build_turn_summary: Callable[..., Any]
    build_user_message_metadata: Callable[..., Any]
    canonical_focus_for_scenario: Callable[..., Any]
    clean_active_thread_task: Callable[..., Any]
    closed_loop_return_blocks_task_mint: Callable[..., Any]
    coach_turn_mapping: Callable[..., Any]
    compose_resource_context: Callable[..., Any]
    consume_provider_empty_reply_override: Callable[..., Any]
    consume_provider_reply_failure_override: Callable[..., Any]
    current_workspace_id: Callable[..., Any]
    describe_request_attachment_delivery: Callable[..., Any]
    detect_provider_language_corruption: Callable[..., Any]
    ensure_agent_tools_ready: Callable[..., Any]
    ensure_coach_provider_ready: Callable[..., Any]
    ensure_explicit_training_card_after_coach_reply: Callable[..., Any]
    ensure_explicit_training_card_after_language_block: Callable[..., Any]
    extract_coach_turn_payload: Callable[..., Any]
    extract_focus_hint_from_message: Callable[..., Any]
    formal_plan_commit_missing_next_step: Callable[..., Any]
    formal_plan_commit_missing_reply: Callable[..., Any]
    formal_plan_commit_verified: Callable[..., Any]
    frozen_plan_mutation_notice: Callable[..., Any]
    function_guidance_entry_points: Callable[..., Any]
    grounded_resource_contract_needs_repair: Callable[..., Any]
    grounding_decision_from_payload: Callable[..., Any]
    grounding_response_coach_turn: Callable[..., Any]
    guarantee_guided_learn_first_training_card: Callable[..., Any]
    guided_lane_visible_reply_has_foreign_markers: Callable[..., Any]
    guided_lane_visible_reply_is_generic: Callable[..., Any]
    honest_suggested_actions_without_usable_provider: Callable[..., Any]
    honest_unusable_provider_coach_turn: Callable[..., Any]
    infer_coaching_scenario: Callable[..., Any]
    infer_learner_signal: Callable[..., Any]
    inherit_active_thread_scenario_for_continuation: Callable[..., Any]
    isolate_preflight_language_corruption_turn: Callable[..., Any]
    language_aligned_coaching_state_payload: Callable[..., Any]
    language_aligned_context_list: Callable[..., Any]
    language_aligned_context_text: Callable[..., Any]
    language_aligned_flat_payload: Callable[..., Any]
    language_aligned_memory_payload: Callable[..., Any]
    language_aligned_review_rhythm: Callable[..., Any]
    language_aligned_thread_payload: Callable[..., Any]
    leftover_frozen_blocks_turn_generation: Callable[..., Any]
    leftover_plan_state_fields: Callable[..., Any]
    live_formal_plan_for_explicit_task_next: Callable[..., Any]
    merge_agent_finalize_into_coach_turn: Callable[..., Any]
    message_keeps_existing_thread: Callable[..., Any]
    message_requests_explicit_explanation_or_example: Callable[..., Any]
    message_requests_project_sourcing: Callable[..., Any]
    model_implementation_guide: Callable[..., Any]
    model_learner_state: Callable[..., Any]
    model_principle_notes: Callable[..., Any]
    model_project_adaptation_guide: Callable[..., Any]
    model_project_ideas: Callable[..., Any]
    model_project_sources: Callable[..., Any]
    model_teaching_decision: Callable[..., Any]
    normalize_current_file_payload: Callable[..., Any]
    operation_reliability_record: Callable[..., Any]
    persist_evaluation_learning_loop: Callable[..., Any]
    persist_external_references_as_background: Callable[..., Any]
    persist_recovered_plan_resume_after_turn: Callable[..., Any]
    preserve_requested_domain_scenario: Callable[..., Any]
    pressure_without_live_object_blocks_mint: Callable[..., Any]
    profile_with_teaching_style: Callable[..., Any]
    provider_is_live_usable: Callable[..., Any]
    repair_generic_finalize_next_step: Callable[..., Any]
    repair_guided_lane_memory_snapshot_for_response: Callable[..., Any]
    repair_legacy_assistant_messages: Callable[..., Any]
    reply_explicitly_lists_prepared_sequence: Callable[..., Any]
    request_resource_ids: Callable[..., Any]
    request_with_workspace_defaults: Callable[..., Any]
    requires_formal_plan_commit: Callable[..., Any]
    resolve_coach_turn: Callable[..., Any]
    resolve_external_references: Callable[..., Any]
    resolve_local_continuation_step: Callable[..., Any]
    resolve_turn_grounding_async: Callable[..., Any]
    resolved_profile: Callable[..., Any]
    safe_activate_training_card_from_coach_request: Callable[..., Any]
    sanitize_visible_coach_reply_content: Callable[..., Any]
    should_attach_auto_resource_events: Callable[..., Any]
    should_bypass_agent_loop_for_guided_training: Callable[..., Any]
    should_preserve_relationship_continuity_for_turn: Callable[..., Any]
    should_remap_task_intent_without_live_plan: Callable[..., Any]
    streak_without_live_object_blocks_mint: Callable[..., Any]
    turn_history_text: Callable[..., Any]
    turn_keeps_review_signals: Callable[..., Any]
    update_snapshot_plan_from_turn: Callable[..., Any]
    workspace_preferences: Callable[..., Any]
    workspace_response_language: Callable[..., Any]
    build_coaching_artifacts: Callable[..., Any]
    coach_suggested_actions: Callable[..., Any]
    hydrate_snapshot: Callable[..., Any]
    persist_turn_reflection: Callable[..., Any]
    review_aware_next_task: Callable[..., Any]

def coach_suggested_actions(deps: CoachSupportDeps,
    response_language: str | None,
    *,
    scenario: str = "general",
    snapshot: WorkbenchSnapshot | None = None,
) -> list[dict[str, str]]:
    def action(label: str, action_type: str) -> dict[str, str]:
        return {"label": label, "action": action_type}

    from ..pedagogy.evidence_controls import streak_adapts_without_inventing_live_objects

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
    from ..pedagogy.context_pressure import (
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
        from ..pedagogy.context_pressure import preference_equivalent_from_strategy_bias

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
    from ..pedagogy.evidence_controls import (
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
                if tool_name:
                    tool_call_names.append(tool_name)
                continue
            if event_type != "tool_result":
                continue
            result_payload = item.get("result")
            if item.get("ok") is False:
                had_failure = True
            if isinstance(result_payload, dict) and result_payload.get("error"):
                had_failure = True
            tool_name = str(item.get("name") or item.get("tool_name") or "").strip()
            if (
                tool_name == "verify_practice_current_file"
                and practice_verification_result is None
                and isinstance(result_payload, dict)
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
    for tool_name in unique_tool_names:
        if tool_name in {"recall_memory", "record_learning_note"}:
            categories.add("memory")
        elif tool_name == "inspect_plan":
            categories.add("plan")
        elif tool_name == "search_resources":
            categories.add("resources")
        elif tool_name in {"read_workspace_file", "list_workspace_files"}:
            categories.add("workspace")
        elif tool_name == "run_diagnostics":
            categories.add("diagnostics")
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


def build_coaching_artifacts(deps: CoachSupportDeps,
    *,
    scenario: str,
    response_language: str | None,
    coaching_state: CoachingState | None,
    memory,
    message: str | None = None,
    task: TaskSpec | None = None,
    plan: LearningPlan | None = None,
    evaluation=None,
    snapshot: WorkbenchSnapshot | None = None,
    grounding_context: dict[str, object] | None = None,
    completed_return: bool = False,
    active_view: str | None = None,
) -> dict[str, object]:
    artifacts: dict[str, object] = {}
    recall = active_training_review(memory, deps.normalize_active_view_name(active_view))
    if recall is not None:
        recall_rule = recall.guardrail or recall.next_self_implementation_rule
        return {"review": deps.artifact_payload(
            kind="review", title=recall.title, summary=recall.summary,
            content="\n\n".join(part for part in [recall.summary, recall_rule] if part),
            bullets=[recall_rule], focus_area=recall.focus_area,
            metadata={"review_artifact_id": recall.id, "evidence_scope": "self_reported_recall",
                      "status": recall.status},
        )}

    def stored_exercise_prompt() -> dict[str, object] | None:
        if snapshot is None:
            return None
        workspace = snapshot.memory.workspace
        if not isinstance(workspace, dict):
            return None
        return deps.normalized_object_mapping(workspace.get("exercise_prompt"))

    evaluation_checks = (
        [*evaluation.static_checks, *evaluation.dynamic_checks, *evaluation.semantic_checks]
        if evaluation
        else []
    )
    failing_checks = [check.label for check in evaluation_checks if check.status in {"failed", "warning"}]
    active_stage = None
    if plan:
        active_stage = next(
            (stage for stage in plan.stages if stage.id == plan.current_stage_id or stage.status == "active"),
            plan.stages[0] if plan.stages else None,
        )
    leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
    leftover_focus = live_leftover_focus_candidate(
        plan=plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
        stage_title=active_stage.title if active_stage else "",
        task_title=task.title if task else "",
    )

    if task and scenario in {"task", "next_task"}:
        artifacts["task"] = task.model_dump()
    if plan and scenario == "plan":
        artifacts["plan"] = plan.model_dump()
    if evaluation and scenario == "review":
        artifacts["evaluation"] = evaluation.model_dump()

    title = deps.coach_artifact_title(
        scenario,
        response_language,
        task=task,
        plan=plan,
        evaluation_summary=evaluation.summary if evaluation else None,
        snapshot=snapshot,
        runtime=leftover_runtime,
    )
    summary = coaching_state.summary if coaching_state else memory.current_focus
    focus_bundle = deps.coach_focus_bundle(
        memory=memory,
        response_language=response_language,
        scenario=scenario,
        coaching_state=coaching_state,
        message=message,
        task=task,
        plan=plan,
        grounding_context=grounding_context,
        snapshot=snapshot,
    )
    persist_workspace_id = ""
    if snapshot is not None:
        persist_workspace = snapshot.memory.workspace if isinstance(snapshot.memory.workspace, dict) else {}
        persist_workspace_id = str(
            persist_workspace.get("workspace_id")
            or persist_workspace.get("workspaceId")
            or getattr(snapshot, "context_id", "")
            or ""
        ).strip()
    if persist_workspace_id:
        deps.runtime.memory_service.persist_turn_context_pressure(
            persist_workspace_id,
            coach_focus=focus_bundle,
        )

    if scenario == "idea_implementation":
        guide = snapshot.implementation_guide if snapshot and snapshot.implementation_guide else None
        exercise_prompt = stored_exercise_prompt()
        entry_point = (
            guide.codebase_entry_points[0]
            if guide and guide.codebase_entry_points
            else ""
        )
        bullets = [
            localized_text(
                "Current focus: keep the first patch inside one thin, visible slice.",
                "当前聚焦点：把第一版 patch 限制在一个很小、可见的范围里。",
                response_language,
            ),
            localized_text(
                f"Start in: {entry_point}",
                f"建议起点：{entry_point}",
                response_language,
            )
            if entry_point
            else "",
            guide.current_step if guide and guide.current_step else coaching_state.next_step if coaching_state else "",
            guide.success_signal if guide and guide.success_signal else "",
            localized_text(
                "Review rhythm: verify it immediately before widening the change.",
                "\u590d\u76d8\u8282\u594f\uff1a\u505a\u5b8c\u7acb\u523b\u9a8c\u8bc1\uff0c\u518d\u6269\u5927\u6539\u52a8\u8303\u56f4\u3002",
                response_language,
            ),
        ]
        if memory.teaching_observations:
            bullets.append(
                localized_text(
                    f"Teaching note: {memory.teaching_observations[0]}",
                    f"教学提醒：{memory.teaching_observations[0]}",
                    response_language,
                )
            )
        artifacts["idea_implementation"] = deps.artifact_payload(
            kind="idea_implementation",
            title=title,
            summary=summary,
            bullets=bullets[:4],
            teaser=guide.current_step if guide and guide.current_step else coaching_state.next_step if coaching_state else "",
            recommended_action="task",
            rationale=localized_text(
                "The coach is turning your idea into a persistent implementation lane with one thin next move, not just describing it.",
                "这里会把你的想法整理成一条能持续推进的实现主线，并明确下一小步，而不只是描述它。",
                response_language,
            ),
            focus_area=live_task_focus_area(
                plan=plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                task_title=task.title if task else "",
                fallback="implementation" if not task else "",
            ),
            verification=(
                guide.validation_strategy[:2]
                if guide and guide.validation_strategy
                else [
                    localized_text(
                        "Verify the first working path before widening scope.",
                        "\u5148\u9a8c\u8bc1\u7b2c\u4e00\u6761\u5de5\u4f5c\u8def\u5f84\uff0c\u518d\u6269\u5927\u8303\u56f4\u3002",
                        response_language,
                    )
                ]
            ),
            content=deps.render_artifact_content(
                title=title,
                summary=summary,
                bullets=bullets,
                verification=(
                    guide.validation_strategy[:2]
                    if guide and guide.validation_strategy
                    else [
                        localized_text(
                            "Verify the first working path before widening scope.",
                            "\u5148\u9a8c\u8bc1\u7b2c\u4e00\u6761\u5de5\u4f5c\u8def\u5f84\uff0c\u518d\u6269\u5927\u8303\u56f4\u3002",
                            response_language,
                        )
                    ]
                ),
                rationale=localized_text(
                    "The coach is turning your idea into a persistent implementation lane with one thin next move, not just describing it.",
                    "这里会把你的想法整理成一条能持续推进的实现主线，并明确下一小步，而不只是描述它。",
                    response_language,
                ),
                metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
                extras=[
                    *((
                        [
                            localized_text(
                                f"### MVP boundary\n\n{guide.mvp_definition}",
                                f"### 最小可行版本的范围\n\n{guide.mvp_definition}",
                                response_language,
                            )
                        ]
                    ) if guide and guide.mvp_definition else []),
                    *deps.exercise_lines(exercise_prompt if isinstance(exercise_prompt, dict) else None, response_language),
                ],
                response_language=response_language,
            ),
            metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
        )
    elif scenario == "project_idea":
        project_ideas = snapshot.project_ideas if snapshot and snapshot.project_ideas else []
        top_idea = project_ideas[0] if project_ideas else None
        exercise_prompt = stored_exercise_prompt()
        idea_lines = [
            localized_text(
                f"- [{idea.difficulty}] {idea.title}: {idea.why_now}",
                f"- [{idea.difficulty}] {idea.title}：{idea.why_now}",
                response_language,
            )
            for idea in project_ideas[:3]
            if idea.title
        ]
        bullets = [
            localized_text(
                "Pick one idea that trains a single engineering move.",
                "\u5148\u6311\u4e00\u4e2a\u53ea\u8bad\u7ec3\u4e00\u4e2a\u5de5\u7a0b\u52a8\u4f5c\u7684\u70b9\u3002",
                response_language,
            ),
            top_idea.first_step if top_idea and top_idea.first_step else coaching_state.next_step if coaching_state else "",
            top_idea.why_now if top_idea and top_idea.why_now else "",
            top_idea.acceptance_signals[0] if top_idea and top_idea.acceptance_signals else "",
            localized_text(
                "Keep the scope tight enough to finish in one short loop.",
                "\u8303\u56f4\u8981\u5c0f\u5230\u80fd\u5728\u4e00\u8f6e\u77ed\u5faa\u73af\u91cc\u5b8c\u6210\u3002",
                response_language,
            ),
        ]
        if memory.recent_wins:
            bullets.append(
                localized_text(
                    f"Build on a recent win: {memory.recent_wins[0]}",
                    f"尽量接住最近的进步：{memory.recent_wins[0]}",
                    response_language,
                )
            )
        artifacts["project_idea"] = deps.artifact_payload(
            kind="project_idea",
            title=title,
            summary=(
                top_idea.title
                if top_idea and top_idea.title
                else summary
            ),
            bullets=bullets[:4],
            teaser=top_idea.first_step if top_idea and top_idea.first_step else coaching_state.next_step if coaching_state else "",
            recommended_action="task",
            rationale=localized_text(
                "This extracts a project-shaped training idea from existing code instead of inventing a fake toy task.",
                "\u8fd9\u91cc\u662f\u5728\u73b0\u6709 project \u91cc\u63d0\u70bc\u8bad\u7ec3\u673a\u4f1a\uff0c\u800c\u4e0d\u662f\u865a\u6784\u4e00\u9053\u73a9\u5177\u9898\u3002",
                response_language,
            ),
            focus_area=live_leftover_focus_candidate(
                plan=plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                stage_title=active_stage.title if active_stage else "",
                task_title=task.title if task else "",
                candidate=top_idea.source_area if top_idea and top_idea.source_area else "",
                fallback="project-idea",
            ),
            verification=(
                top_idea.acceptance_signals[:2]
                if top_idea and top_idea.acceptance_signals
                else [
                    localized_text(
                        "Keep it small enough to finish in one short coaching loop.",
                        "\u8303\u56f4\u5fc5\u987b\u5c0f\u5230\u80fd\u5728\u4e00\u8f6e\u77ed\u6559\u7ec3\u5faa\u73af\u91cc\u5b8c\u6210\u3002",
                        response_language,
                    )
                ]
            ),
            content=deps.render_artifact_content(
                title=title,
                summary=summary,
                bullets=bullets,
                verification=(
                    top_idea.acceptance_signals[:2]
                    if top_idea and top_idea.acceptance_signals
                    else [
                        localized_text(
                            "Keep it small enough to finish in one short coaching loop.",
                            "\u8303\u56f4\u5fc5\u987b\u5c0f\u5230\u80fd\u5728\u4e00\u8f6e\u77ed\u6559\u7ec3\u5faa\u73af\u91cc\u5b8c\u6210\u3002",
                            response_language,
                        )
                    ]
                ),
                rationale=localized_text(
                    "This extracts a project-shaped training idea from existing code instead of inventing a fake toy task.",
                    "\u8fd9\u91cc\u662f\u5728\u73b0\u6709 project \u91cc\u63d0\u70bc\u8bad\u7ec3\u673a\u4f1a\uff0c\u800c\u4e0d\u662f\u865a\u6784\u4e00\u9053\u73a9\u5177\u9898\u3002",
                    response_language,
                ),
                metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
                extras=[
                    *(
                        [
                            localized_text(
                                "### Candidate drills\n\n" + "\n".join(idea_lines),
                                "### 候选训练题\n\n" + "\n".join(idea_lines),
                                response_language,
                            )
                        ]
                        if idea_lines
                        else []
                    ),
                    *deps.exercise_lines(exercise_prompt if isinstance(exercise_prompt, dict) else None, response_language),
                ],
                response_language=response_language,
            ),
            metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
        )
    elif scenario == "project_adaptation":
        adaptation_guide = (
            snapshot.project_adaptation_guide if snapshot and snapshot.project_adaptation_guide else None
        )
        exercise_prompt = stored_exercise_prompt()
        bullets = [
            localized_text(
                "Current focus: name the boundary that moves first and keep the rest stable.",
                "",
                response_language,
            ),
            adaptation_guide.target_outcome
            if adaptation_guide and adaptation_guide.target_outcome
            else "",
            adaptation_guide.first_migration_step
            if adaptation_guide and adaptation_guide.first_migration_step
            else coaching_state.next_step if coaching_state else "",
            localized_text(
                "Review rhythm: validate one boundary before touching the next one.",
                "",
                response_language,
            ),
        ]
        artifacts["project_adaptation"] = deps.artifact_payload(
            kind="project_adaptation",
            title=title,
            summary=summary,
            bullets=bullets,
            teaser=adaptation_guide.first_migration_step if adaptation_guide and adaptation_guide.first_migration_step else coaching_state.next_step if coaching_state else "",
            recommended_action="plan",
            rationale=localized_text(
                "Adaptation work fails when boundaries blur, so the coach is naming the first safe boundary and the review rhythm before more change.",
                "",
                response_language,
            ),
            focus_area=leftover_focus or "adaptation",
            verification=(
                adaptation_guide.validation_checkpoints[:2]
                if adaptation_guide and adaptation_guide.validation_checkpoints
                else [
                    localized_text(
                        "Validate one boundary before touching the next layer.",
                        "\u6bcf\u6539\u4e00\u5c42\uff0c\u5148\u9a8c\u8bc1\u4e0a\u4e00\u5c42\u7684\u8fb9\u754c\u3002",
                        response_language,
                    )
                ]
            ),
            content=deps.render_artifact_content(
                title=title,
                summary=summary,
                bullets=bullets,
                verification=(
                    adaptation_guide.validation_checkpoints[:2]
                    if adaptation_guide and adaptation_guide.validation_checkpoints
                    else [
                        localized_text(
                            "Validate one boundary before touching the next layer.",
                            "\u6bcf\u6539\u4e00\u5c42\uff0c\u5148\u9a8c\u8bc1\u4e0a\u4e00\u5c42\u7684\u8fb9\u754c\u3002",
                            response_language,
                        )
                    ]
                ),
                rationale=localized_text(
                    "Adaptation work fails when boundaries blur, so the coach is naming the first safe boundary and the review rhythm before more change.",
                    "",
                    response_language,
                ),
                metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
                extras=[
                    *(
                        [
                            localized_text(
                                "### Preserve first\n\n"
                                + "\n".join(
                                    f"- {item}"
                                    for item in adaptation_guide.preserve_areas[:3]
                                    if item
                                ),
                                "### \u5148\u4fdd\u7559\u8fd9\u4e9b\n\n"
                                + "\n".join(
                                    f"- {item}"
                                    for item in adaptation_guide.preserve_areas[:3]
                                    if item
                                ),
                                response_language,
                            )
                        ]
                        if adaptation_guide and adaptation_guide.preserve_areas
                        else []
                    ),
                    localized_text(
                        "### Boundary checklist\n\n| Layer | Change now? | Reason |\n| --- | --- | --- |\n| Stable module | No | Keep the blast radius small |\n| First boundary | Yes | Proves the adaptation path |\n| Downstream layers | Later | Wait until the previous boundary is verified |",
                        "",
                        response_language,
                    ),
                    *deps.exercise_lines(exercise_prompt if isinstance(exercise_prompt, dict) else None, response_language),
                    *(
                        [
                            localized_text(
                                "### Rollback note\n\n"
                                + "\n".join(
                                    f"- {item}"
                                    for item in adaptation_guide.rollback_notes[:2]
                                    if item
                                ),
                                "### \u56de\u9000\u63d0\u793a\n\n"
                                + "\n".join(
                                    f"- {item}"
                                    for item in adaptation_guide.rollback_notes[:2]
                                    if item
                                ),
                                response_language,
                            )
                        ]
                        if adaptation_guide and adaptation_guide.rollback_notes
                        else []
                    ),
                ],
                response_language=response_language,
            ),
            metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
        )
    elif scenario == "project_sourcing":
        project_sources = snapshot.project_sources if snapshot and snapshot.project_sources else []
        top_source = project_sources[0] if project_sources else None
        exercise_prompt = stored_exercise_prompt()
        bullets = [
            localized_text(
                "Current focus: pick an outside project that reinforces one real engineering move.",
                "\u5f53\u524d\u805a\u7126\uff1a\u6311\u4e00\u4e2a\u80fd\u5f3a\u5316\u4e00\u4e2a\u771f\u5b9e\u5de5\u7a0b\u52a8\u4f5c\u7684\u5916\u90e8\u9879\u76ee\u3002",
                response_language,
            ),
            top_source.first_filter if top_source and top_source.first_filter else coaching_state.next_step if coaching_state else "",
            top_source.first_task if top_source and top_source.first_task else "",
            localized_text(
                "Keep the source small enough that setup cost does not swallow the training value.",
                "\u9879\u76ee\u6765\u6e90\u8981\u8db3\u591f\u5c0f\uff0c\u4e0d\u80fd\u8ba9\u73af\u5883\u548c\u642d\u5efa\u6210\u672c\u541e\u6389\u8bad\u7ec3\u4ef7\u503c\u3002",
                response_language,
            ),
        ]
        source_details: list[str] = []
        if top_source and top_source.title:
            source_details.append(
                localized_text(
                    f"### Recommended source\n\n- {top_source.title}",
                    f"### \u63a8\u8350\u6765\u6e90\n\n- {top_source.title}",
                    response_language,
                )
            )
        if top_source and top_source.source_url:
            source_details.append(
                localized_text(
                    f"### Source\n\n- URL: {top_source.source_url}",
                    f"### \u6765\u6e90\n\n- URL: {top_source.source_url}",
                    response_language,
                )
            )
        if top_source and top_source.retrieved_at:
            source_details.append(
                localized_text(
                    f"- Retrieved at: {top_source.retrieved_at}",
                    f"- \u83b7\u53d6\u65f6\u95f4\uff1a{top_source.retrieved_at}",
                    response_language,
                )
            )
        if top_source and top_source.trust_score:
            source_details.append(
                localized_text(
                    f"- Trust score: {top_source.trust_score:.2f}",
                    f"- \u53ef\u4fe1\u5ea6\uff1a{top_source.trust_score:.2f}",
                    response_language,
                )
            )
        artifacts["project_source"] = deps.artifact_payload(
            kind="project_source",
            title=title,
            summary=summary,
            bullets=bullets[:4],
            teaser=top_source.repo_hint if top_source and top_source.repo_hint else coaching_state.next_step if coaching_state else "",
            recommended_action="task",
            rationale=localized_text(
                "When the current repo is not the best training surface, the coach should still keep momentum by recommending a realistic outside project source.",
                "\u5f53\u5f53\u524d\u4ed3\u5e93\u4e0d\u9002\u5408\u4f5c\u4e3a\u8bad\u7ec3\u9762\u65f6\uff0c\u6559\u7ec3\u4e5f\u5e94\u8be5\u7ee7\u7eed\u7ef4\u6301\u63a8\u8fdb\uff0c\u7ed9\u51fa\u4e00\u4e2a\u73b0\u5b9e\u53ef\u7528\u7684\u5916\u90e8\u9879\u76ee\u6765\u6e90\u3002",
                response_language,
            ),
            focus_area=top_source.title if top_source and top_source.title else "project-source",
            verification=[
                top_source.first_filter
                if top_source and top_source.first_filter
                else localized_text(
                    "The source should be small, recent, and easy to verify locally.",
                    "\u8fd9\u4e2a\u6765\u6e90\u5e94\u5f53\u4f53\u91cf\u5c0f\u3001\u7ef4\u62a4\u65b0\uff0c\u5e76\u4e14\u672c\u5730\u5bb9\u6613\u9a8c\u8bc1\u3002",
                    response_language,
                )
            ],
            content=deps.render_artifact_content(
                title=title,
                summary=summary,
                bullets=bullets,
                verification=[
                    top_source.first_filter
                    if top_source and top_source.first_filter
                    else localized_text(
                        "The source should be small, recent, and easy to verify locally.",
                        "\u8fd9\u4e2a\u6765\u6e90\u5e94\u5f53\u4f53\u91cf\u5c0f\u3001\u7ef4\u62a4\u65b0\uff0c\u5e76\u4e14\u672c\u5730\u5bb9\u6613\u9a8c\u8bc1\u3002",
                        response_language,
                    )
                ],
                rationale=localized_text(
                    "This keeps sourcing inside the same coaching lane instead of turning it into a separate research product.",
                    "\u8fd9\u91cc\u628a\u627e\u9879\u76ee\u6765\u6e90\u4ecd\u7136\u538b\u5728\u540c\u4e00\u6761\u6559\u7ec3\u4e3b\u7ebf\u91cc\uff0c\u800c\u4e0d\u662f\u628a\u5b83\u505a\u6210\u72ec\u7acb\u7814\u7a76\u4ea7\u54c1\u3002",
                    response_language,
                ),
                metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
                extras=[
                    *source_details,
                    *deps.exercise_lines(exercise_prompt if isinstance(exercise_prompt, dict) else None, response_language),
                    localized_text(
                        "### What to look for\n\n| Filter | Why |\n| --- | --- |\n| Small codebase | Lowers setup cost |\n| Tests or reproductions | Makes training verifiable |\n| Recent maintenance | Keeps patterns relevant |",
                        "### \u600e\u4e48\u7b5b\n\n| \u7b5b\u9009\u9879 | \u539f\u56e0 |\n| --- | --- |\n| \u4ee3\u7801\u5e93\u8db3\u591f\u5c0f | \u964d\u4f4e\u4e0a\u624b\u6210\u672c |\n| \u6709\u6d4b\u8bd5\u6216\u590d\u73b0\u8def\u5f84 | \u8bad\u7ec3\u66f4\u53ef\u9a8c\u8bc1 |\n| \u6700\u8fd1\u4ecd\u5728\u7ef4\u62a4 | \u6a21\u5f0f\u66f4\u63a5\u8fd1\u5f53\u524d\u5b9e\u8df5 |",
                        response_language,
                    )
                ],
                response_language=response_language,
            ),
            metadata={
                "background_mode": "embedded",
                "coach_focus": focus_bundle,
                "source_url": top_source.source_url if top_source else "",
                "retrieved_at": top_source.retrieved_at if top_source else "",
                "trust_score": top_source.trust_score if top_source else 0.0,
            },
        )
    elif scenario == "principle":
        principle_notes = snapshot.principle_notes if snapshot and snapshot.principle_notes else None
        exercise_prompt = stored_exercise_prompt()
        bullets = [
            localized_text(
                "Current focus: state the rule in plain words before adding detail.",
                "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u5148\u7528\u6700\u76f4\u767d\u7684\u8bdd\u8bf4\u6e05\u89c4\u5219\uff0c\u518d\u8865\u7ec6\u8282\u3002",
                response_language,
            ),
            principle_notes.apply_now if principle_notes and principle_notes.apply_now else coaching_state.next_step if coaching_state else "",
            principle_notes.current_principle if principle_notes and principle_notes.current_principle else "",
            principle_notes.concrete_anchor if principle_notes and principle_notes.concrete_anchor else "",
            localized_text(
                "Review rhythm: tie the rule back to one concrete line or boundary in the code.",
                "",
                response_language,
            ),
        ]
        if memory.weaknesses:
            bullets.append(
                localized_text(
                    f"Watch the old gap: {memory.weaknesses[0]}",
                    f"\u6ce8\u610f\u8fd9\u4e2a\u65e7\u95ee\u9898\uff1a{memory.weaknesses[0]}",
                    response_language,
                )
            )
        artifacts["principle"] = deps.artifact_payload(
            kind="principle",
            title=title,
            summary=summary,
            bullets=bullets[:4],
            teaser=principle_notes.apply_now if principle_notes and principle_notes.apply_now else coaching_state.next_step if coaching_state else "",
            recommended_action="hint",
            rationale=localized_text(
                "This keeps the explanation attached to the current code boundary and the next reviewable move instead of drifting into theory.",
                "",
                response_language,
            ),
            focus_area="principle",
            verification=(
                principle_notes.related_checks[:3]
                if principle_notes and principle_notes.related_checks
                else principle_notes.transfer_targets[:2]
                if principle_notes and principle_notes.transfer_targets
                else [
                    localized_text(
                        "Point at one concrete line, branch, or boundary where the principle matters.",
                        "",
                        response_language,
                    )
                ]
            ),
            content=deps.render_artifact_content(
                title=title,
                summary=summary,
                bullets=bullets,
                verification=(
                    principle_notes.related_checks[:3]
                    if principle_notes and principle_notes.related_checks
                    else principle_notes.transfer_targets[:2]
                    if principle_notes and principle_notes.transfer_targets
                    else [
                        localized_text(
                            "Point at one concrete line, branch, or boundary where the principle matters.",
                            "",
                            response_language,
                        )
                    ]
                ),
                rationale=localized_text(
                    "This keeps the explanation attached to the current code boundary and the next reviewable move instead of drifting into theory.",
                    "",
                    response_language,
                ),
                metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
                extras=[
                    *(
                        [
                            localized_text(
                                f"### Concrete anchor\n\n{principle_notes.concrete_anchor}",
                                f"### \u5177\u4f53\u951a\u70b9\n\n{principle_notes.concrete_anchor}",
                                response_language,
                            )
                        ]
                        if principle_notes and principle_notes.concrete_anchor
                        else []
                    ),
                    *(
                        [
                            localized_text(
                                f"### Common wrong intuition\n\n{principle_notes.common_mistake}",
                                f"### 常见错误直觉\n\n{principle_notes.common_mistake}",
                                response_language,
                            )
                        ]
                        if principle_notes and principle_notes.common_mistake
                        else []
                    ),
                    *(
                        [
                            localized_text(
                                f"### Transfer lesson\n\n{principle_notes.transferable_lesson}",
                                "",
                                response_language,
                            )
                        ]
                        if principle_notes and principle_notes.transferable_lesson
                        else []
                    ),
                    *(
                        [
                            localized_text(
                                f"### Source asset\n\n- {principle_notes.source_asset_title}",
                                f"### 来源教学资产\n\n- {principle_notes.source_asset_title}",
                                response_language,
                            )
                        ]
                        if principle_notes and principle_notes.source_asset_title
                        else []
                    ),
                    *deps.exercise_lines(exercise_prompt if isinstance(exercise_prompt, dict) else None, response_language),
                ],
                response_language=response_language,
            ),
            metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
        )
    elif scenario == "review" and evaluation:
        bullets = [
            localized_text(
                "Current focus: fix the first issue that restores correctness or the feedback loop.",
                "",
                response_language,
            ),
            evaluation.next_step,
            localized_text(
                "Review rhythm: patch, verify, then ask for the next prioritized issue.",
                "",
                response_language,
            ),
        ]
        if memory.review_rhythm:
            bullets.append(
                localized_text(
                    f"Keep the review rhythm alive: {memory.review_rhythm}",
                    f"别断复盘节奏：{memory.review_rhythm}",
                    response_language,
                )
            )
        artifacts["review"] = deps.artifact_payload(
            kind="review",
            title=title,
            summary=evaluation.summary,
            bullets=(bullets + failing_checks[:2])[:4],
            teaser=evaluation.next_step,
            recommended_action="plan" if completed_return else "retry_review" if failing_checks else "review",
            rationale=localized_text(
                "The review loop should keep the learner on the first high-leverage fix, not dump every issue with equal weight.",
                "",
                response_language,
            ),
            focus_area=deps.stateful_focus_area(task, plan, evaluation, snapshot=snapshot),
            verification=[evaluation.next_step],
            content=deps.render_artifact_content(
                title=title,
                summary=evaluation.summary,
                bullets=bullets + failing_checks[:2],
                verification=[evaluation.next_step],
                rationale=localized_text(
                    "The review loop should keep the learner on the first high-leverage fix, not dump every issue with equal weight.",
                    "",
                    response_language,
                ),
                metadata={
                    "failing_checks": failing_checks,
                    "passed": evaluation.passed,
                    "background_mode": "embedded",
                    "coach_focus": focus_bundle,
                },
                extras=[
                    localized_text(
                        "### Review order\n\n```mermaid\nflowchart TD\n    A[Patch first issue] --> B[Run verification]\n    B --> C{Still failing?}\n    C -->|Yes| D[Ask for next issue]\n    C -->|No| E[Widen scope carefully]\n```",
                        "### 评审顺序\n\n```mermaid\nflowchart TD\n    A[先修第一问题] --> B[执行验证]\n    B --> C{还有失败吗}\n    C -->|有| D[继续要下一条问题]\n    C -->|没有| E[再谨慎扩大范围]\n```",
                        response_language,
                    )
                ],
                response_language=response_language,
            ),
            metadata={
                "failing_checks": failing_checks,
                "passed": evaluation.passed,
                "background_mode": "embedded",
                "coach_focus": focus_bundle,
            },
        )
    elif scenario == "plan" and plan:
        bullets = [
            localized_text(
                "Current focus: keep today's work anchored on the active stage.",
                "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u628a\u4eca\u5929\u7684\u52a8\u4f5c\u7a33\u7a33\u951a\u5b9a\u5728\u6d3b\u8dc3\u9636\u6bb5\u4e0a\u3002",
                response_language,
            ),
            deps.live_stage_object_label(plan, snapshot=snapshot, stage=active_stage),
            coaching_state.next_step if coaching_state else "",
            localized_text(
                "Review rhythm: keep the current stage small enough to complete visibly.",
                "",
                response_language,
            ),
        ]
        if memory.teaching_observations:
            bullets.append(
                localized_text(
                    f"Teaching observation to preserve: {memory.teaching_observations[0]}",
                    f"\u8981\u7ee7\u7eed\u4fdd\u6301\u7684\u6559\u5b66\u89c2\u5bdf\uff1a{memory.teaching_observations[0]}",
                    response_language,
                )
            )
        artifacts["plan_update"] = deps.artifact_payload(
            kind="plan_update",
            title=title,
            summary=summary,
            bullets=bullets[:4],
            teaser=coaching_state.next_step
            if coaching_state
            else deps.live_stage_object_label(plan, snapshot=snapshot, stage=active_stage),
            recommended_action="plan",
            rationale=localized_text(
                "This plan update is meant to tighten today's sequence around the active stage and review rhythm, not create a broad dashboard.",
                "",
                response_language,
            ),
            focus_area=deps.stateful_focus_area(task, plan, evaluation, snapshot=snapshot),
            verification=[
                localized_text(
                    "You should be able to name today's first visible move after reading this.",
                    "",
                    response_language,
                )
            ],
            content=deps.render_artifact_content(
                title=title,
                summary=summary,
                bullets=bullets,
                verification=[
                    localized_text(
                        "You should be able to name today's first visible move after reading this.",
                        "",
                        response_language,
                    )
                ],
                rationale=localized_text(
                    "This plan update is meant to tighten today's sequence around the active stage and review rhythm, not create a broad dashboard.",
                    "",
                    response_language,
                ),
                metadata={
                    "active_stage_id": active_stage.id if active_stage else None,
                    "frozen": plan.frozen,
                    "background_mode": "embedded",
                    "coach_focus": focus_bundle,
                },
                extras=[
                    localized_text(
                        "### Stage framing\n\n| Track | Current stage |\n| --- | --- |\n| Coaching lane | " + (deps.live_stage_object_label(plan, snapshot=snapshot, stage=active_stage) or "Current stage") + " |\n| Next visible move | " + ((coaching_state.next_step if coaching_state else "") or "Define the first visible move") + " |",
                        "### \u9636\u6bb5\u6846\u67b6\n\n| \u8f68\u9053 | \u5f53\u524d\u5185\u5bb9 |\n| --- | --- |\n| \u6559\u7ec3\u4e3b\u7ebf | "
                        + (deps.live_stage_object_label(plan, snapshot=snapshot, stage=active_stage) or "\u5f53\u524d\u9636\u6bb5")
                        + " |\n| \u4e0b\u4e00\u4e2a\u53ef\u89c1\u52a8\u4f5c | "
                        + ((coaching_state.next_step if coaching_state else "") or "\u5148\u5b9a\u4e49\u7b2c\u4e00\u4e2a\u53ef\u89c1\u52a8\u4f5c")
                        + " |",
                        response_language,
                    )
                ],
                response_language=response_language,
            ),
            metadata={
                "active_stage_id": active_stage.id if active_stage else None,
                "frozen": plan.frozen,
                "background_mode": "embedded",
                "coach_focus": focus_bundle,
            },
        )
    elif scenario in {"task", "next_task"} and task:
        live_goal = live_task_suggested_title(
            plan=plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            title=task.natural_language_goal,
            goal=task.natural_language_goal,
            task_title=task.title,
        )
        bullets = [
            localized_text(
                "Current focus: finish only the first visible slice of this task.",
                "",
                response_language,
            ),
            live_goal,
            *(task.verification_strategy[:1] or []),
            *(task.constraints[:1] or []),
        ]
        if memory.review_rhythm:
            bullets.append(
                localized_text(
                    f"Review rhythm to keep: {memory.review_rhythm}",
                    f"\u9700\u8981\u4fdd\u6301\u7684\u590d\u4e60\u8282\u594f\uff1a{memory.review_rhythm}",
                    response_language,
                )
            )
        artifacts["next_step"] = deps.artifact_payload(
            kind="next_step",
            title=localized_text("Do this now", "\u73b0\u5728\u5148\u505a", response_language),
            summary=summary,
            bullets=bullets[:4],
            teaser=live_goal,
            recommended_action="review",
            rationale=localized_text(
                "The task is only valuable if the learner can attempt it immediately, verify one result, and return for review.",
                "",
                response_language,
            ),
            focus_area=live_task_focus_area(
                plan=plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                task_title=task.title,
            ),
            verification=task.verification_strategy[:2],
            content=deps.render_artifact_content(
                title=localized_text("Do this now", "\u73b0\u5728\u5148\u505a", response_language),
                summary=summary,
                bullets=bullets[:3],
                verification=task.verification_strategy[:2],
                rationale=localized_text(
                    "The task is only valuable if the learner can attempt it immediately, verify one result, and return for review.",
                    "",
                    response_language,
                ),
                metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
                extras=[
                    localized_text(
                        "### Start condition\n\nAttempt the task only when the acceptance signal is visible in the current code context.",
                        "",
                        response_language,
                    )
                ],
                response_language=response_language,
            ),
            metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
        )
    elif memory.due_reviews:
        due_review = memory.due_reviews[0]
        artifacts["review"] = deps.artifact_payload(
            kind="review",
            title=localized_text("Review to revisit", "\u5f85\u56de\u770b\u7684\u590d\u4e60\u70b9", response_language),
            summary=due_review.reason,
            bullets=[
                due_review.concept,
                localized_text(
                    "Use a tiny implementation pass to revisit it.",
                    "\u7528\u4e00\u6b21\u5f88\u5c0f\u7684\u5b9e\u73b0\u52a8\u4f5c\u91cd\u65b0\u8fc7\u4e00\u904d\u3002",
                    response_language,
                ),
            ],
            teaser=due_review.concept,
            recommended_action="next_task",
            rationale=localized_text(
                "Background review should surface through the current turn, not as a separate research mode.",
                "",
                response_language,
            ),
            focus_area=due_review.concept,
            verification=[due_review.reason],
            content=deps.render_artifact_content(
                title=localized_text("Review to revisit", "\u5f85\u56de\u770b\u7684\u590d\u4e60\u70b9", response_language),
                summary=due_review.reason,
                bullets=[
                    due_review.concept,
                    localized_text(
                        "Use a tiny implementation pass to revisit it.",
                        "\u7528\u4e00\u6b21\u5f88\u5c0f\u7684\u5b9e\u73b0\u52a8\u4f5c\u91cd\u65b0\u8fc7\u4e00\u904d\u3002",
                        response_language,
                    ),
                ],
                verification=[due_review.reason],
                rationale=localized_text(
                    "Background review should surface through the current turn, not as a separate research mode.",
                    "",
                    response_language,
                ),
                metadata={
                    "due_at": due_review.due_at,
                    "background_mode": "embedded",
                    "coach_focus": focus_bundle,
                },
                extras=[
                    localized_text(
                        "### Review note\n\nA review item should re-enter the loop as a tiny patch, not a giant recap.",
                        "",
                        response_language,
                    )
                ],
                response_language=response_language,
            ),
            metadata={
                "due_at": due_review.due_at,
                "background_mode": "embedded",
                "coach_focus": focus_bundle,
            },
        )

    return artifacts


def derive_coaching_state(deps: CoachSupportDeps,
    *,
    snapshot: WorkbenchSnapshot,
    response_language: str | None,
    answer_mode: str | None,
    scenario: str | None = None,
    learner_signal: str | None = None,
    message: str | None = None,
    current_file=None,
    grounding_context: dict[str, object] | None = None,
    active_view: str | None = None,
) -> CoachingState:
    memory = snapshot.memory
    plan = snapshot.plan
    task = snapshot.current_task
    evaluation = snapshot.evaluation
    active_stage = None
    if plan:
        active_stage = next(
            (stage for stage in plan.stages if stage.id == plan.current_stage_id or stage.status == "active"),
            plan.stages[0] if plan.stages else None,
        )

    raw_seed_scenario = scenario or (
        snapshot.memory.active_thread.scenario
        if snapshot.memory.active_thread is not None
        else "general"
    )
    # Active threads may persist pedagogy modes such as "review_reflection"
    # (a TeachingMode, not a CoachScenario); normalize before validation so a
    # restored thread can never crash CoachingState construction.
    if raw_seed_scenario == "review_reflection":
        raw_seed_scenario = "review"
    if raw_seed_scenario not in get_args(CoachScenario):
        raw_seed_scenario = "general"

    coaching_state_seed = CoachingState.model_validate(
        {
            "scenario": raw_seed_scenario,
            "answer_mode": deps.normalize_answer_mode(
                answer_mode or snapshot.profile.answer_policy if snapshot.profile else None
            ),
            "learner_signal": (
                "blocked"
                if learner_signal != "blocked"
                and infer_message_learner_signal(message or "", current_file) == "blocked"
                else learner_signal or "steady"
            ),
        }
    )
    resolved_scenario = coaching_state_seed.scenario
    resolved_mode = coaching_state_seed.answer_mode
    resolved_signal = coaching_state_seed.learner_signal
    active_thread = snapshot.memory.active_thread
    preserve_active_thread = deps.should_preserve_active_thread_for_turn(
        resolved_scenario,
        active_thread,
        message=message,
        grounding_context=grounding_context,
        active_view=active_view,
    )
    view_owned_lane = deps.active_view_owns_turn_lane(active_view)
    resource_grounded_turn = deps.resource_grounding_turn_prefers_fresh_lane(
        message,
        grounding_context,
    )
    active_thread_focus = active_thread.focus_area.strip() if active_thread else ""
    active_thread_summary = active_thread.summary.strip() if active_thread else ""
    active_thread_next_step = active_thread.next_step.strip() if active_thread else ""
    active_thread_blocker = active_thread.blocker.strip() if active_thread else ""
    active_thread_verified = active_thread.verified_result.strip() if active_thread else ""
    workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
    current_file_name = deps.function_guidance_current_file_name(
        current_file,
        scenario=resolved_scenario,
    )
    persist_chrome = live_plan_update_persist_chrome(
        plan=plan,
        runtime=coach_focus_runtime_from_snapshot(snapshot),
        existing=coach_focus_runtime_from_snapshot(snapshot),
        stage_title=active_stage.title if active_stage else "",
        task_title=task.title if task else "",
        stage_goal=active_stage.goal if active_stage else "",
    )
    turn_focus_hint = deps.resolve_turn_focus_hint(
        user_message=message,
        current_file_name=current_file_name or None,
        task_focus=persist_chrome["task_focus"] or None,
        stage_focus=persist_chrome["stage_focus"] or None,
    )

    def _workspace_text(*keys: str) -> str:
        for key in keys:
            value = str(workspace.get(key) or "").strip()
            if value:
                return value
        return ""

    def _workspace_evidence(*keys: str) -> list[str]:
        for key in keys:
            raw = workspace.get(key)
            if isinstance(raw, list):
                evidence = [str(item).strip() for item in raw if str(item).strip()]
                if evidence:
                    return evidence[:4]
            elif isinstance(raw, str):
                normalized = raw.strip()
                if normalized:
                    return [normalized]
        return []

    active_thread_decision = active_thread.decision.strip() if active_thread and preserve_active_thread else ""
    active_thread_teaching_note = (
        active_thread.teaching_note.strip() if active_thread and preserve_active_thread else ""
    )
    active_thread_confidence = active_thread.confidence.strip() if active_thread and preserve_active_thread else ""
    active_thread_evidence = (
        [str(item).strip() for item in active_thread.evidence if str(item).strip()]
        if active_thread and preserve_active_thread
        else []
    )
    if not preserve_active_thread:
        active_thread_focus = ""
        active_thread_summary = ""
        active_thread_next_step = ""
        active_thread_blocker = ""
        active_thread_verified = ""
    if preserve_active_thread and not active_thread_decision:
        active_thread_decision = _workspace_text("latest_coach_decision", "latest_turn_decision")
    if preserve_active_thread and not active_thread_blocker:
        active_thread_blocker = _workspace_text("latest_turn_blocker", "latest_coach_review_note")
    if preserve_active_thread and not active_thread_teaching_note:
        active_thread_teaching_note = _workspace_text("latest_coach_teaching_note", "latest_turn_teaching_note")
    if preserve_active_thread and not active_thread_confidence:
        active_thread_confidence = _workspace_text("latest_coach_confidence", "latest_turn_confidence")
    if preserve_active_thread and not active_thread_evidence:
        active_thread_evidence = _workspace_evidence("latest_coach_evidence", "latest_turn_evidence")

    if resolved_scenario == "review" and evaluation:
        summary = localized_text(
            f"Top fix first: {evaluation.next_step}",
            f"\u5148\u4fee\u6700\u5173\u952e\u7684\u4e00\u6b65\uff1a{evaluation.next_step}",
            response_language,
        )
        next_step = evaluation.next_step
    elif resolved_scenario == "review":
        summary = localized_text(
            "Current focus: name the failing path from current evidence before generating a plan or task.",
            "当前聚焦点：先从当前证据里点出失败路径，不要生成计划或任务。",
            response_language,
        )
        next_step = localized_text(
            "Point at the failing check, error, or code boundary you can see right now.",
            "先指出你现在能看到的失败检查、报错或代码边界。",
            response_language,
        )
    elif resolved_scenario == "onboarding":
        summary = localized_text(
            "First build the coaching relationship: understand the goal, current level, project context, and the best lane to start with.",
            "\u5148\u5efa\u7acb\u6559\u7ec3\u5173\u7cfb\uff1a\u7406\u89e3\u4f60\u7684\u76ee\u6807\u3001\u5f53\u524d\u6c34\u5e73\u3001project \u8bed\u5883\uff0c\u4ee5\u53ca\u6700\u9002\u5408\u5f00\u59cb\u7684\u90a3\u6761\u4e3b\u7ebf\u3002",
            response_language,
        )
        next_step = localized_text(
            "Clarify the first coaching lane, the current blocker, and the rhythm that will make the next few turns easy to follow.",
            "\u5148\u660e\u786e\u7b2c\u4e00\u6761\u6559\u7ec3\u4e3b\u7ebf\u3001\u5f53\u524d\u5361\u70b9\uff0c\u4ee5\u53ca\u80fd\u8ba9\u63a5\u4e0b\u6765\u51e0\u8f6e\u66f4\u597d\u8ddf\u4e0a\u7684\u8bad\u7ec3\u8282\u594f\u3002",
            response_language,
        )
    elif resolved_scenario == "plan" and active_stage:
        live_stage_label = (
            persist_chrome["stage_focus"]
            or active_stage.title
            or active_stage.goal
        )
        summary = localized_text(
            f"Stay inside the current stage: {live_stage_label}",
            f"\u5148\u7a33\u4f4f\u5f53\u524d\u9636\u6bb5\uff1a{live_stage_label}",
            response_language,
        )
        next_step = (
            live_task_suggested_title(
                plan=plan,
                task=task,
                runtime=coach_focus_runtime_from_snapshot(snapshot),
                existing=coach_focus_runtime_from_snapshot(snapshot),
                title=task.natural_language_goal,
                goal=task.natural_language_goal,
                task_title=task.title,
            )
            if task
            else persist_chrome["next_step"]
        )
    elif resolved_scenario in {"task", "next_task"} and task:
        leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
        thin_slice = live_task_thin_slice_copy(
            plan=plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=task.title,
        )
        summary = localized_text(thin_slice["en"], thin_slice["zh"], response_language)
        next_step = live_task_suggested_title(
            plan=plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            title=task.natural_language_goal,
            goal=task.natural_language_goal,
            task_title=task.title,
        )
    elif resolved_scenario == "idea_implementation":
        summary = localized_text(
            (
                f"Current focus: keep the work inside {current_file_name} and land one tiny, verifiable code move."
                if current_file_name
                else "Current focus: keep the work inside the current file and land one tiny, verifiable code move."
            ),
            (
                f"\u5f53\u524d\u7126\u70b9\uff1a\u5148\u628a\u5de5\u4f5c\u6536\u5728 {current_file_name} \u91cc\uff0c\u843d\u4e0b\u4e00\u6761\u5f88\u8584\u3001\u53ef\u9a8c\u8bc1\u7684 code \u52a8\u4f5c\u3002"
                if current_file_name
                else "\u5f53\u524d\u7126\u70b9\uff1a\u5148\u628a\u5de5\u4f5c\u6536\u5728\u5f53\u524d\u6587\u4ef6\u91cc\uff0c\u843d\u4e0b\u4e00\u6761\u5f88\u8584\u3001\u53ef\u9a8c\u8bc1\u7684 code \u52a8\u4f5c\u3002"
            ),
            response_language,
        )
        next_step = localized_text(
            (
                f"Change one tiny spot in {current_file_name}, run one quick check, and use the result to decide the next move."
                if current_file_name
                else "Change one tiny spot in the current file, run one quick check, and use the result to decide the next move."
            ),
            (
                f"\u5148\u5728 {current_file_name} \u91cc\u6539\u4e00\u4e2a\u5c0f\u70b9\uff0c\u8dd1\u4e00\u6b21\u5f88\u5feb\u7684\u9a8c\u8bc1\uff0c\u518d\u7528\u7ed3\u679c\u51b3\u5b9a\u4e0b\u4e00\u6b65\u3002"
                if current_file_name
                else "\u5148\u5728\u5f53\u524d\u6587\u4ef6\u91cc\u6539\u4e00\u4e2a\u5c0f\u70b9\uff0c\u8dd1\u4e00\u6b21\u5f88\u5feb\u7684\u9a8c\u8bc1\uff0c\u518d\u7528\u7ed3\u679c\u51b3\u5b9a\u4e0b\u4e00\u6b65\u3002"
            ),
            response_language,
        )
        if prefers_chinese(response_language):
            summary = (
                f"\u5f53\u524d\u7126\u70b9\uff1a\u5148\u628a\u5de5\u4f5c\u6536\u5728 {current_file_name} \u91cc\uff0c\u843d\u4e0b\u4e00\u6761\u5f88\u8584\u3001\u53ef\u9a8c\u8bc1\u7684 code \u52a8\u4f5c\u3002"
                if current_file_name
                else "\u5f53\u524d\u7126\u70b9\uff1a\u5148\u628a\u5de5\u4f5c\u6536\u5728\u5f53\u524d\u6587\u4ef6\u91cc\uff0c\u843d\u4e0b\u4e00\u6761\u5f88\u8584\u3001\u53ef\u9a8c\u8bc1\u7684 code \u52a8\u4f5c\u3002"
            )
            next_step = (
                f"\u5148\u5728 {current_file_name} \u91cc\u6539\u4e00\u4e2a\u5c0f\u70b9\uff0c\u8dd1\u4e00\u6b21\u5f88\u5feb\u7684\u9a8c\u8bc1\uff0c\u518d\u7528\u7ed3\u679c\u51b3\u5b9a\u4e0b\u4e00\u6b65\u3002"
                if current_file_name
                else "\u5148\u5728\u5f53\u524d\u6587\u4ef6\u91cc\u6539\u4e00\u4e2a\u5c0f\u70b9\uff0c\u8dd1\u4e00\u6b21\u5f88\u5feb\u7684\u9a8c\u8bc1\uff0c\u518d\u7528\u7ed3\u679c\u51b3\u5b9a\u4e0b\u4e00\u6b65\u3002"
            )
    elif resolved_scenario == "principle":
        if resource_grounded_turn:
            summary = localized_text(
                "Current focus: answer the grounded library question directly before widening into adjacent coaching.",
                "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u5148\u76f4\u63a5\u56de\u7b54\u8fd9\u4e2a\u5df2\u7ecf grounded \u7684\u8d44\u6599\u95ee\u9898\uff0c\u518d\u51b3\u5b9a\u8981\u4e0d\u8981\u5f80\u76f8\u90bb\u6559\u5b66\u6269\u5c55\u3002",
                response_language,
            )
            next_step = localized_text(
                "State the requested rule in plain language, name the source boundary it comes from, then turn it into one visible verification check.",
                "\u5148\u7528\u76f4\u767d\u7684\u8bdd\u8bf4\u51fa\u7528\u6237\u95ee\u7684\u89c4\u5219\uff0c\u518d\u8bf4\u6e05\u5b83\u6765\u81ea\u54ea\u6761\u8d44\u6599\u8fb9\u754c\uff0c\u6700\u540e\u628a\u5b83\u538b\u6210\u4e00\u6761\u53ef\u89c1\u7684\u9a8c\u8bc1\u68c0\u67e5\u3002",
                response_language,
            )
        else:
            summary = localized_text(
                "Current focus: explain the mechanism behind the current code before widening the patch.",
                "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u5148\u8bb2\u6e05\u5f53\u524d code \u80cc\u540e\u7684\u673a\u5236\uff0c\u518d\u6269\u5927 patch \u8303\u56f4\u3002",
                response_language,
            )
            next_step = localized_text(
                "Name the rule, then point at the exact line where it matters, then verify it in code review.",
                "\u5148\u8bf4\u6e05\u89c4\u5219\uff0c\u518d\u6307\u51fa\u5b83\u5728\u54ea\u4e00\u884c\u771f\u6b63\u751f\u6548\uff0c\u7136\u540e\u5728 code review \u91cc\u9a8c\u8bc1\u5b83\u3002",
                response_language,
            )
    elif resolved_scenario == "remote_workspace":
        summary = localized_text(
            "Current focus: establish the VS Code remote workspace boundary before widening the lesson.",
            "\u5f53\u524d\u7126\u70b9\uff1a\u5148\u5efa\u7acb VS Code remote workspace \u7684\u8fb9\u754c\uff0c\u518d\u6269\u5927\u8fd9\u8f6e\u6559\u5b66\u8303\u56f4\u3002",
            response_language,
        )
        next_step = localized_text(
            "Return one real boundary signal from the current VS Code window, such as an Explorer path, `pwd`, or the remote host label.",
            "\u5728\u4f60\u5f53\u524d\u7684 VS Code \u7a97\u53e3\u91cc\uff0c\u5e26\u56de\u4e00\u4e2a\u80fd\u8bc1\u660e\u5de5\u4f5c\u533a\u843d\u70b9\u7684\u771f\u5b9e\u4fe1\u53f7\uff0c\u6bd4\u5982 Explorer \u91cc\u7684\u8def\u5f84\u3001\u7ec8\u7aef\u91cc\u7684 `pwd`\uff0c\u6216\u8005\u5de6\u4e0b\u89d2\u7684 remote host \u6807\u7b7e\u3002",
            response_language,
        )
    elif resolved_scenario == "debug_loop":
        summary = localized_text(
            "Current focus: build one trustworthy VS Code debug loop before widening the investigation.",
            "\u5f53\u524d\u7126\u70b9\uff1a\u5148\u5efa\u7acb\u4e00\u6761\u53ef\u4fe1\u7684 VS Code \u8c03\u8bd5\u95ed\u73af\uff0c\u518d\u6269\u5927\u6392\u67e5\u8303\u56f4\u3002",
            response_language,
        )
        next_step = localized_text(
            "Choose one breakpoint or launch.json move, then tell me where you will pause and what single value or branch you expect to inspect there.",
            "\u5148\u9009\u4e00\u4e2a breakpoint \u6216 launch.json \u52a8\u4f5c\uff0c\u518d\u544a\u8bc9\u6211\u4f60\u51c6\u5907\u505c\u5728\u54ea\u513f\uff0c\u4ee5\u53ca\u4f60\u8981\u6838\u5bf9\u7684\u90a3\u4e2a\u503c\u6216\u5206\u652f\u662f\u4ec0\u4e48\u3002",
            response_language,
        )
    elif resolved_scenario == "function_guidance":
        summary = localized_text(
            "Current focus: anchor function guidance to one live call site before widening the explanation.",
            "\u5f53\u524d\u7126\u70b9\uff1a\u5148\u628a function guidance \u951a\u5b9a\u5230\u4e00\u4e2a\u771f\u5b9e call site\uff0c\u518d\u6269\u5c55\u8bf4\u660e\u3002",
            response_language,
        )
        if current_file_name:
            next_step = localized_text(
                f"Go back to {current_file_name}, name the selected function's parameter contract and return contract, then verify that reading against the nearest call site you can see.",
                f"\u56de\u5230 {current_file_name}\uff0c\u5148\u8bf4\u6e05\u5f53\u524d\u9009\u4e2d\u51fd\u6570\u7684\u53c2\u6570 contract \u548c return contract\uff1b\u5982\u679c\u65c1\u8fb9\u5c31\u6709\u6700\u8fd1\u7684 call site\uff0c\u518d\u7528\u5b83\u9a8c\u8bc1\u4f60\u521a\u624d\u7684\u5224\u65ad\u3002",
                response_language,
            )
        else:
            next_step = localized_text(
                "Return the function name, what it expects, and which call site proves that reading.",
                "\u5e26\u56de\u51fd\u6570\u540d\u3001\u5b83\u671f\u671b\u4ec0\u4e48\uff0c\u4ee5\u53ca\u54ea\u4e2a call site \u8bc1\u660e\u4e86\u8fd9\u4e2a contract\u3002",
                response_language,
            )
    elif resolved_scenario == "project_adaptation":
        summary = localized_text(
            "Current focus: keep stable modules stable and move one boundary at a time.",
            "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u7a33\u4f4f\u4e0d\u8be5\u52a8\u7684\u6a21\u5757\uff0c\u4e00\u6b21\u53ea\u6539\u4e00\u5c42\u8fb9\u754c\u3002",
            response_language,
        )
        next_step = localized_text(
            "Choose the first affected layer, land the smallest safe patch, and verify it before touching the next one.",
            "\u5148\u6311\u7b2c\u4e00\u5c42\u53d7\u5f71\u54cd\u7684\u8fb9\u754c\uff0c\u843d\u4e0b\u6700\u5c0f\u5b89\u5168 patch\uff0c\u9a8c\u8bc1\u5b8c\u518d\u52a8\u4e0b\u4e00\u5c42\u3002",
            response_language,
        )
    elif resolved_scenario == "project_sourcing":
        summary = localized_text(
            "Current focus: recommend one outside project source that keeps training realistic and easy to start.",
            "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u63a8\u8350\u4e00\u4e2a\u65e2\u771f\u5b9e\u53c8\u5bb9\u6613\u4e0a\u624b\u7684\u5916\u90e8 project \u6765\u6e90\u3002",
            response_language,
        )
        next_step = localized_text(
            "Choose one small maintained source, reject setup-heavy options, then turn it into the first training task.",
            "\u5148\u9009\u4e00\u4e2a\u5c0f\u800c\u6301\u7eed\u7ef4\u62a4\u7684\u6765\u6e90\uff0c\u6392\u9664\u642d\u5efa\u6210\u672c\u8fc7\u9ad8\u7684\u9009\u9879\uff0c\u518d\u628a\u5b83\u538b\u6210\u7b2c\u4e00\u9053\u8bad\u7ec3\u9898\u3002",
            response_language,
        )
    elif resolved_scenario == "project_idea":
        summary = localized_text(
            "Pull one training opportunity from the current project and keep the scope tight.",
            "\u4ece\u5f53\u524d project \u91cc\u63d0\u70bc\u4e00\u4e2a\u8bad\u7ec3\u673a\u4f1a\uff0c\u5e76\u628a\u8303\u56f4\u538b\u7d27\u3002",
            response_language,
        )
        next_step = localized_text(
            "Pick the smallest idea that teaches one real engineering move.",
            "\u5148\u9009\u4e00\u4e2a\u53ea\u8bad\u7ec3\u4e00\u4e2a\u5173\u952e\u5de5\u7a0b\u52a8\u4f5c\u7684\u5c0f\u60f3\u6cd5\u3002",
            response_language,
        )
    else:
        summary = (
            localized_text(
                f"Current focus: {turn_focus_hint}",
                f"\u5f53\u524d\u805a\u7126\u70b9\uff1a{turn_focus_hint}",
                response_language,
            )
            if turn_focus_hint and not preserve_active_thread
            else memory.current_focus or localized_text(
                "Keep the next step concrete and verifiable.",
                "\u628a\u4e0b\u4e00\u6b65\u538b\u6210\u5177\u4f53\u4e14\u53ef\u9a8c\u8bc1\u7684\u52a8\u4f5c\u3002",
                response_language,
            )
        )
        leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
        live_goal = live_coaching_next_step(
            plan=plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            next_step=task.natural_language_goal if task else "",
            goal=task.natural_language_goal if task else "",
            task_title=task.title if task else "",
        )
        next_step = (
            localized_text(
                f"On '{turn_focus_hint}': one small step, then report back.",
                f"围绕「{turn_focus_hint}」先做一个小动作，把结果带回来。",
                response_language,
            )
            if turn_focus_hint and not preserve_active_thread
            else live_goal
            or (evaluation.next_step if evaluation else memory.review_rhythm or localized_text(
                "Implement the smallest slice you can check quickly.",
                "\u5148\u5b9e\u73b0\u4f60\u80fd\u5feb\u901f\u9a8c\u8bc1\u7684\u6700\u5c0f\u5207\u7247\u3002",
                response_language,
            ))
        )

    if view_owned_lane:
        lane_override = deps.active_view_coaching_lane_override(
            active_view=active_view,
            snapshot=snapshot,
            response_language=response_language,
        )
        if lane_override is not None:
            summary, next_step = lane_override

    if active_thread_focus and resolved_scenario == "general":
        summary = localized_text(
            f"Stay on the live thread '{active_thread_focus}' before opening a new lane.",
            f"\u5148\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u300c{active_thread_focus}\u300d\u7ee7\u7eed\uff0c\u4e0d\u8981\u65b0\u5f00\u5206\u652f\u3002",
            response_language,
        )
    elif active_thread_summary and resolved_scenario == "general":
        summary = active_thread_summary

    if active_thread_next_step:
        next_step = active_thread_next_step

    encouragement = {
        "blocked": localized_text(
            "Reduce scope and land one tiny win before expanding again.",
            "先缩小范围，拿下一个很小的确定性进展再继续。",
            response_language,
        ),
        "uncertain": localized_text(
            "Use the next step to turn ambiguity into one observable result.",
            "用下一步把模糊感压成一个可观察的结果。",
            response_language,
        ),
        "curious": localized_text(
            "Keep the exploration grounded in one concrete code path.",
            "让探索落在一条具体代码路径上，不要散开。",
            response_language,
        ),
        "steady": localized_text(
            "Keep the loop tight: implement, verify, reflect.",
            "把循环保持紧凑：实现、验证、复盘。",
            response_language,
        ),
    }[resolved_signal]
    intervention_strategy = localized_text(
        "First compress the problem into one visible, verifiable move before expanding explanation or scope.",
        "先把问题压成一个可见、可验证的小动作，再决定是否扩大解释和范围。",
        response_language,
    )
    teaching_goal = localized_text(
        "Train implementation judgment inside the current project instead of only giving an answer.",
        "在当前项目里训练实现判断，而不是只给结果。",
        response_language,
    )
    if resolved_scenario == "onboarding":
        teaching_goal = localized_text(
            "Establish trust, understand the learner's real situation, and choose the right coaching lane before pushing execution.",
            "先建立信任、理解学习者的真实处境，再决定对的教练主线，而不是急着推进执行。",
            response_language,
        )
    if active_thread_focus or active_thread_next_step:
        resume_parts = [
            localized_text(
                f"Resume the live thread '{active_thread_focus}'.",
                f"\u4e0b\u4e00\u8f6e\u7ee7\u7eed\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u300c{active_thread_focus}\u300d\u63a5\u4e0a\u3002",
                response_language,
            )
            if active_thread_focus
            else "",
            localized_text(
                f"Do this next before widening scope: {active_thread_next_step}",
                f"\u5148\u5b8c\u6210\u8fd9\u4e00\u6b65\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u6269\u5c55\uff1a{active_thread_next_step}",
                response_language,
            )
            if active_thread_next_step
            else "",
            localized_text(
                f"Current blocker to respect: {active_thread_blocker}",
                f"\u5f53\u524d\u8981\u907f\u5f00\u7684\u5361\u70b9\uff1a{active_thread_blocker}",
                response_language,
            )
            if active_thread_blocker
            else "",
            localized_text(
                f"Last verified result to build on: {active_thread_verified}",
                f"\u4e0a\u4e00\u6b21\u5df2\u9a8c\u8bc1\u7684\u7ed3\u679c\uff0c\u53ef\u4ee5\u63a5\u7740\u5f80\u4e0a\u505a\uff1a{active_thread_verified}",
                response_language,
            )
            if active_thread_verified
            else "",
        ]
        resume_thread = " ".join(part for part in resume_parts if part).strip()
    else:
        resume_thread = localized_text(
            "Resume from the current coaching lane, verify this slice, then decide whether to widen.",
            "下一轮继续沿着当前训练主线接上，先验证这一小步，再决定是否扩展。",
            response_language,
        )
    support_strategy = localized_text(
        "If the learner feels blocked, reduce scope and keep the next move extremely concrete.",
        "如果用户开始卡住，就继续缩小范围，把下一步压得更具体。",
        response_language,
    )

    if resolved_scenario == "principle":
        teaching_goal = localized_text(
            "Reconnect the current code decision back to a transferable principle.",
            "把当前代码判断重新连回一个可迁移的原理。",
            response_language,
        )
    elif resolved_scenario == "project_idea":
        teaching_goal = localized_text(
            "Mine one worthwhile practice opportunity from the current project and keep it thin.",
            "从当前项目里提炼一个值得练的方向，并把范围收薄。",
            response_language,
        )
    elif resolved_scenario == "project_adaptation":
        teaching_goal = localized_text(
            "Reshape the existing project toward the new intention without losing boundary control.",
            "",
            response_language,
        )
    elif resolved_scenario == "project_sourcing":
        teaching_goal = localized_text(
            "Recommend an outside project source without breaking the same coach-first training lane.",
            "",
            response_language,
        )
    elif resolved_scenario == "review":
        teaching_goal = localized_text(
            "Use review to sharpen prioritization and boundary judgment, not just to list issues.",
            "",
            response_language,
        )

    return CoachingState(
        scenario=resolved_scenario,
        answer_mode=resolved_mode,
        learner_signal=resolved_signal,
        summary=summary,
        next_step=next_step,
        encouragement=encouragement,
        intervention_strategy=intervention_strategy,
        teaching_goal=teaching_goal,
        resume_thread=resume_thread,
        decision=active_thread_decision,
        blocker=active_thread_blocker,
        teaching_note=active_thread_teaching_note,
        confidence=active_thread_confidence,
        evidence=active_thread_evidence,
        support_strategy=support_strategy,
    )


def hydrate_snapshot(deps: CoachSupportDeps,
    snapshot: WorkbenchSnapshot,
    *,
    response_language: str | None,
    answer_mode: str | None,
    scenario: str | None = None,
    learner_signal: str | None = None,
    message: str | None = None,
    current_file=None,
    grounding_context: dict[str, object] | None = None,
    active_view: str | None = None,
    session_workspace_id: str | None = None,
    preserve_session_history: bool = False,
    preserve_turn_coaching_state: bool = False,
) -> WorkbenchSnapshot:
    snapshot.session_history_restored = preserve_session_history
    due_reviews = snapshot.memory.due_reviews
    snapshot.review_queue_summary = deps.summarize_review_queue(due_reviews, response_language)
    snapshot.next_review_due = due_reviews[0].due_at if due_reviews else None
    # T-0048: when the turn already authored coaching state (agent_meta
    # apply after the T-0027 repair), re-deriving here would rebuild from
    # pre-turn memory and re-mint the generic「围绕…先做一个小动作」lane,
    # desynchronizing the learning surfaces from the coach reply in the
    # SAME response. Derive only when no turn-authored state exists.
    if preserve_turn_coaching_state and snapshot.coaching_state is not None:
        pass
    else:
        snapshot.coaching_state = deps.derive_coaching_state(
            snapshot=snapshot,
            response_language=response_language,
            answer_mode=answer_mode,
            scenario=scenario,
            learner_signal=learner_signal,
            message=message,
            current_file=current_file,
            grounding_context=grounding_context,
            active_view=active_view,
        )
    profile = snapshot.profile
    workspace_memory = snapshot.memory.workspace if isinstance(snapshot.memory.workspace, dict) else {}
    workspace_id = (
        str(
            workspace_memory.get("workspace_id")
            or snapshot.context_id
            or session_workspace_id
            or ""
        ).strip()
        or None
    )
    live_for_hydrate = False
    if workspace_id:
        leftover_plan, leftover_runtime_early = deps.leftover_runtime_for_workspace(workspace_id)
        # Empty restore / no recovered runtime: do not resurrect leftover as live
        # (leftover_formal_plan_is_live_for_fill first-persist True does not apply here).
        live_for_hydrate = bool(leftover_runtime_early) and leftover_formal_plan_is_live_for_fill(
            plan=snapshot.plan or leftover_plan,
            runtime=leftover_runtime_early,
            existing=leftover_runtime_early,
        )
        if not live_for_hydrate:
            snapshot.plan = None
        snapshot.plan = stamp_produced_workspace_record(snapshot.plan, workspace_id)
        snapshot.current_task = stamp_produced_workspace_record(
            snapshot.current_task, workspace_id
        )
        snapshot.evaluation = stamp_produced_workspace_record(
            snapshot.evaluation, workspace_id
        )
        snapshot.plan_runtime_status = deps.attach_plan_runtime_status(
            workspace_id=workspace_id,
            snapshot=snapshot,
            response_language=response_language,
            profile=profile,
        )
        evidence_queue = snapshot.memory.evidence_queue
        pending = getattr(evidence_queue, "pending", None) if evidence_queue is not None else None
        pending_ids = [
            str(getattr(item, "id", "") or "").strip()
            for item in (pending if isinstance(pending, list) else [])
            if str(getattr(item, "id", "") or "").strip()
        ]
        first_pending = pending_ids[0] if pending_ids else ""
        runtime_status = (
            snapshot.plan_runtime_status if isinstance(snapshot.plan_runtime_status, dict) else {}
        )
        existing_runtime = deps.runtime.memory_service.recover_workspace_facts_for_scope(
            workspace_id
        ).get(PLAN_RUNTIME_KEY)
        persist_runtime = dict(existing_runtime) if isinstance(existing_runtime, dict) else {}
        for key, value in runtime_status.items():
            if persist_runtime.get(key) not in (None, "", [], {}):
                continue
            if value not in (None, "", [], {}):
                persist_runtime[key] = value
        existing_binding = str(
            (existing_runtime or {}).get("evidence_binding")
            or (existing_runtime or {}).get("evidenceBinding")
            or ""
        ).strip()
        evidence_binding = live_evidence_binding(
            binding=existing_binding or first_pending,
            pending_ids=pending_ids,
            recovered=bool(runtime_status.get("recovered") or existing_runtime),
            current_step=str(
                persist_runtime.get("current_step")
                or persist_runtime.get("currentStep")
                or runtime_status.get("current_step")
                or runtime_status.get("currentStep")
                or ""
            ),
        )
        existing_step = str(
            (existing_runtime or {}).get("current_step")
            or (existing_runtime or {}).get("currentStep")
            or ""
        ).strip()
        existing_plan_id = str(
            (existing_runtime or {}).get("plan_id")
            or (existing_runtime or {}).get("planId")
            or ""
        ).strip()
        formal_id = str(
            getattr(snapshot.plan, "id", "") or getattr(snapshot.plan, "plan_id", "") or ""
        ).strip() if snapshot.plan is not None else ""
        independent_recovered = bool(existing_step and not existing_plan_id)
        mismatched_leftover = bool(
            existing_plan_id and formal_id and existing_plan_id != formal_id
        )
        # Fail-closed: only persist formal plan when recovered runtime already
        # carries matching plan_id. Empty restore must not invent/bind leftover.
        matching_live_id = bool(
            existing_plan_id and formal_id and existing_plan_id == formal_id
        )
        plan_for_persist = (
            snapshot.plan
            if matching_live_id and not independent_recovered and not mismatched_leftover
            else None
        )
        deps.runtime.memory_service.persist_plan_runtime_recovery(
            workspace_id,
            plan=plan_for_persist,
            plan_runtime=persist_runtime or None,
            evidence_binding=evidence_binding,
            request_id=str(
                persist_runtime.get("request_id")
                or persist_runtime.get("requestId")
                or runtime_status.get("request_id")
                or ""
            ),
            replace_evidence_binding=True,
        )
        provider = snapshot.provider
        recovered = deps.runtime.memory_service.recover_workspace_facts_for_scope(
            workspace_id,
            provider_profile_id=str(getattr(provider, "profile_id", "") or "").strip(),
            provider_name=str(getattr(provider, "name", "") or "").strip(),
            base_url=str(getattr(provider, "base_url", "") or "").strip(),
            model=str(getattr(provider, "model", "") or "").strip(),
        )
        workspace_memory = {
            key: value
            for key, value in workspace_memory.items()
            if key
            not in {
                "latest_plan_runtime",
                "latestPlanRuntime",
                "latest_provider_capability",
                "latestProviderCapability",
                "latest_streaming_checkpoint",
                "latestStreamingCheckpoint",
            }
        }
        workspace_memory = {
            **workspace_memory,
            "workspace_id": workspace_id,
            **{key: value for key, value in recovered.items() if value},
        }
        snapshot.memory.workspace = workspace_memory
        # Cold-start leftover-not-live: stored formal plan with empty/mismatched
        # runtime must stamp recovered so FE leftover overlay lights. snapshot.plan
        # stays None; never auto-bind leftover plan_id as live.
        if leftover_plan is not None and not live_for_hydrate:
            status = (
                dict(snapshot.plan_runtime_status)
                if isinstance(snapshot.plan_runtime_status, dict)
                else {}
            )
            status["recovered"] = True
            leftover_id = str(
                getattr(leftover_plan, "id", "")
                or getattr(leftover_plan, "plan_id", "")
                or ""
            ).strip()
            status_plan_id = str(status.get("plan_id") or status.get("planId") or "").strip()
            if leftover_id and status_plan_id == leftover_id:
                status["plan_id"] = None
                status.pop("planId", None)
            snapshot.plan_runtime_status = status
    from ..pedagogy.coach_orientation import (
        build_coach_orientation_from_snapshot,
        normalize_coach_orientation,
    )

    leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
    leftover_plan_for_chrome = None
    if workspace_id:
        leftover_plan_for_chrome, _leftover_runtime_for_chrome = deps.leftover_runtime_for_workspace(
            workspace_id
        )
    if leftover_task_guide_focus_is_not_live(
        runtime=leftover_runtime,
        existing=leftover_runtime,
    ) and snapshot.implementation_guide is not None:
        snapshot.implementation_guide = snapshot.implementation_guide.model_copy(
            update={
                "idea_summary": "",
                "scope_boundary": "",
                "current_step": "",
                "teaching_goal": "",
                "success_signal": "",
                "fallback_step": "",
            }
        )
    if leftover_runtime:
        leftover_focus = workspace_memory.get("latest_coach_focus")
        if not isinstance(leftover_focus, dict):
            leftover_focus = workspace_memory.get("latestCoachFocus")
        leftover_focus = leftover_focus if isinstance(leftover_focus, dict) else {}
        leftover_judgment = (
            snapshot.plan_runtime_status.get("coach_judgment")
            if isinstance(snapshot.plan_runtime_status, dict)
            else None
        )
        leftover_judgment = leftover_judgment if isinstance(leftover_judgment, dict) else {}
        turn_chrome = prefer_recovered_coach_turn_chrome(
            runtime=leftover_runtime,
            existing=leftover_runtime,
            coaching_state_next_step=(
                snapshot.coaching_state.next_step if snapshot.coaching_state else ""
            ),
            coaching_state_summary=(
                snapshot.coaching_state.summary if snapshot.coaching_state else ""
            ),
            coaching_state_teaching_goal=(
                snapshot.coaching_state.teaching_goal if snapshot.coaching_state else ""
            ),
            coaching_state_encouragement=(
                snapshot.coaching_state.encouragement if snapshot.coaching_state else ""
            ),
            evaluation_next_step=(
                snapshot.evaluation.next_step if snapshot.evaluation else ""
            ),
            resume_thread=(
                snapshot.coaching_state.resume_thread if snapshot.coaching_state else ""
            ),
            support_strategy=(
                snapshot.coaching_state.support_strategy if snapshot.coaching_state else ""
            ),
            review_queue_summary=snapshot.review_queue_summary,
            continuity_summary=str(
                leftover_focus.get("continuity_summary")
                or leftover_focus.get("continuitySummary")
                or ""
            ),
            coach_judgment_summary=str(
                leftover_judgment.get("summary")
                or (snapshot.coaching_state.summary if snapshot.coaching_state else "")
                or ""
            ),
            coach_judgment_teaching_goal=str(
                leftover_judgment.get("teaching_goal")
                or leftover_judgment.get("teachingGoal")
                or (snapshot.coaching_state.teaching_goal if snapshot.coaching_state else "")
                or ""
            ),
        )
        if not live_for_hydrate:
            if snapshot.coaching_state is not None:
                snapshot.coaching_state = snapshot.coaching_state.model_copy(
                    update={
                        "next_step": turn_chrome.get("coaching_state_next_step", ""),
                        "summary": turn_chrome.get("coaching_state_summary", ""),
                        "teaching_goal": turn_chrome.get("coaching_state_teaching_goal", ""),
                        "encouragement": turn_chrome.get("coaching_state_encouragement", ""),
                        "resume_thread": turn_chrome.get("resume_thread", ""),
                        "support_strategy": turn_chrome.get("support_strategy", ""),
                    }
                )
            if snapshot.evaluation is not None:
                snapshot.evaluation = snapshot.evaluation.model_copy(
                    update={"next_step": turn_chrome.get("evaluation_next_step", "")},
                )
            snapshot.review_queue_summary = turn_chrome.get("review_queue_summary", "")
            runtime_status = (
                snapshot.plan_runtime_status if isinstance(snapshot.plan_runtime_status, dict) else None
            )
            if runtime_status is not None:
                coach_judgment = runtime_status.get("coach_judgment")
                if not isinstance(coach_judgment, dict):
                    coach_judgment = {}
                snapshot.plan_runtime_status = {
                    **runtime_status,
                    "review_queue_summary": turn_chrome.get("review_queue_summary", ""),
                    "coach_judgment": {
                        **coach_judgment,
                        "resume_thread": turn_chrome.get("resume_thread", ""),
                        "support_strategy": turn_chrome.get("support_strategy", ""),
                        "summary": turn_chrome.get("coach_judgment_summary", ""),
                        "teaching_goal": turn_chrome.get("coach_judgment_teaching_goal", ""),
                    },
                }
        if leftover_focus:
            workspace_memory = {
                **workspace_memory,
                "latest_coach_focus": {
                    **leftover_focus,
                    "continuity_summary": turn_chrome.get("continuity_summary", ""),
                },
            }
            snapshot.memory.workspace = workspace_memory
        focus_chrome = prefer_recovered_training_focus_chrome(
            runtime=leftover_runtime,
            existing=leftover_runtime,
            plan=leftover_plan_for_chrome,
            teaching_decision_focus_area=(
                snapshot.teaching_decision.focus_area if snapshot.teaching_decision else ""
            ),
            learner_state_active_focus=(
                snapshot.learner_state.active_focus if snapshot.learner_state else ""
            ),
            latest_learning_focus_area=str(
                workspace_memory.get("latest_learning_focus_area")
                or workspace_memory.get("latestLearningFocusArea")
                or ""
            ),
        )
        if snapshot.learner_state is not None:
            snapshot.learner_state = snapshot.learner_state.model_copy(
                update={
                    "active_focus": focus_chrome.get("learner_state_active_focus", ""),
                }
            )
        if snapshot.teaching_decision is not None:
            snapshot.teaching_decision = snapshot.teaching_decision.model_copy(
                update={
                    "focus_area": focus_chrome.get("teaching_decision_focus_area", ""),
                }
            )
        leftover_handoff = workspace_memory.get("latest_training_handoff")
        if not isinstance(leftover_handoff, dict):
            leftover_handoff = workspace_memory.get("latestTrainingHandoff")
        leftover_handoff = leftover_handoff if isinstance(leftover_handoff, dict) else {}
        leftover_next_hop = workspace_memory.get("latest_training_next_hop")
        if not isinstance(leftover_next_hop, dict):
            leftover_next_hop = workspace_memory.get("latestTrainingNextHop")
        leftover_next_hop = leftover_next_hop if isinstance(leftover_next_hop, dict) else {}
        leftover_routing = workspace_memory.get("active_training_card_routing")
        if not isinstance(leftover_routing, dict):
            leftover_routing = workspace_memory.get("activeTrainingCardRouting")
        leftover_routing = leftover_routing if isinstance(leftover_routing, dict) else {}
        handoff_chrome = prefer_recovered_training_handoff_chrome(
            runtime=leftover_runtime,
            existing=leftover_runtime,
            plan=leftover_plan_for_chrome,
            success_signal=str(
                leftover_handoff.get("success_signal")
                or leftover_handoff.get("successSignal")
                or ""
            ),
            return_with=str(
                leftover_handoff.get("return_with") or leftover_handoff.get("returnWith") or ""
            ),
            card_title=str(
                leftover_handoff.get("card_title") or leftover_handoff.get("cardTitle") or ""
            ),
            selected_card_title=str(
                workspace_memory.get("selected_card_title")
                or workspace_memory.get("selectedCardTitle")
                or ""
            ),
            followup=str(
                workspace_memory.get("latest_learning_followup")
                or workspace_memory.get("latestLearningFollowup")
                or ""
            ),
            blocker=str(
                workspace_memory.get("latest_learning_blocker")
                or workspace_memory.get("latestLearningBlocker")
                or leftover_handoff.get("blocked_by")
                or leftover_handoff.get("blockedBy")
                or ""
            ),
            handoff_summary=str(
                leftover_handoff.get("handoff_summary")
                or leftover_handoff.get("handoffSummary")
                or ""
            ),
            next_after_completion=str(
                leftover_handoff.get("next_after_completion")
                or leftover_handoff.get("nextAfterCompletion")
                or ""
            ),
            fallback_action=str(
                leftover_handoff.get("fallback_action")
                or leftover_handoff.get("fallbackAction")
                or ""
            ),
            next_hop_title=str(leftover_next_hop.get("title") or ""),
            next_hop_card_title=str(
                leftover_next_hop.get("card_title") or leftover_next_hop.get("cardTitle") or ""
            ),
            next_hop_handoff_summary=str(
                leftover_next_hop.get("handoff_summary")
                or leftover_next_hop.get("handoffSummary")
                or ""
            ),
            next_hop_next_after_completion=str(
                leftover_next_hop.get("next_after_completion")
                or leftover_next_hop.get("nextAfterCompletion")
                or ""
            ),
            next_hop_fallback_action=str(
                leftover_next_hop.get("fallback_action")
                or leftover_next_hop.get("fallbackAction")
                or ""
            ),
            routing_next_after_completion=str(
                leftover_routing.get("next_after_completion")
                or leftover_routing.get("nextAfterCompletion")
                or ""
            ),
            routing_fallback_action=str(
                leftover_routing.get("fallback_action")
                or leftover_routing.get("fallbackAction")
                or ""
            ),
            why_this_card=str(
                leftover_routing.get("why_this_card")
                or leftover_routing.get("whyThisCard")
                or ""
            ),
            return_summary=str(
                leftover_handoff.get("return_summary")
                or leftover_handoff.get("returnSummary")
                or ""
            ),
            next_hop_return_summary=str(
                leftover_next_hop.get("return_summary")
                or leftover_next_hop.get("returnSummary")
                or ""
            ),
            next_hop_summary=str(leftover_next_hop.get("summary") or ""),
            next_hop_why_now=str(
                leftover_next_hop.get("why_now") or leftover_next_hop.get("whyNow") or ""
            ),
        )
        workspace_memory = {
            **workspace_memory,
            "latest_learning_focus_area": focus_chrome.get(
                "latest_learning_focus_area", ""
            ),
            "selected_card_title": handoff_chrome.get("selected_card_title", ""),
            "latest_learning_followup": handoff_chrome.get("followup", ""),
            "latest_learning_blocker": handoff_chrome.get("blocker")
            or workspace_memory.get("latest_learning_blocker", ""),
        }
        if leftover_handoff:
            workspace_memory["latest_training_handoff"] = {
                **leftover_handoff,
                "success_signal": handoff_chrome.get("success_signal", ""),
                "return_with": handoff_chrome.get("return_with", ""),
                "card_title": handoff_chrome.get("card_title", ""),
                "blocked_by": handoff_chrome.get("blocker", ""),
                "handoff_summary": handoff_chrome.get("handoff_summary", ""),
                "next_after_completion": handoff_chrome.get("next_after_completion", ""),
                "fallback_action": handoff_chrome.get("fallback_action", ""),
                "return_summary": handoff_chrome.get("return_summary", ""),
            }
        if leftover_next_hop:
            workspace_memory["latest_training_next_hop"] = {
                **leftover_next_hop,
                "title": handoff_chrome.get("next_hop_title", ""),
                "card_title": handoff_chrome.get("next_hop_card_title", ""),
                "handoff_summary": handoff_chrome.get("next_hop_handoff_summary", ""),
                "next_after_completion": handoff_chrome.get(
                    "next_hop_next_after_completion", ""
                ),
                "fallback_action": handoff_chrome.get("next_hop_fallback_action", ""),
                "return_summary": handoff_chrome.get("next_hop_return_summary", ""),
                "summary": handoff_chrome.get("next_hop_summary", ""),
                "why_now": handoff_chrome.get("next_hop_why_now", ""),
            }
        if leftover_routing:
            workspace_memory["active_training_card_routing"] = {
                **leftover_routing,
                "next_after_completion": handoff_chrome.get(
                    "routing_next_after_completion", ""
                ),
                "fallback_action": handoff_chrome.get("routing_fallback_action", ""),
                "why_this_card": handoff_chrome.get("why_this_card", ""),
            }
        if not preserve_session_history and not live_for_hydrate and leftover_settings_profile_rhythm_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            workspace_memory = {
                **workspace_memory,
                "preferred_rhythm": "",
                "preferredRhythm": "",
                "preferred_learning_mode": "",
                "preferredLearningMode": "",
            }
            workspace_memory.pop("coach_defaults", None)
            workspace_memory.pop("coachDefaults", None)
        if not preserve_session_history and leftover_settings_learner_project_onboarding_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            workspace_memory = {
                **workspace_memory,
                "learner_name": "",
                "learnerName": "",
                "project_context": "",
                "projectContext": "",
                "onboarding_request": "",
                "onboardingRequest": "",
                "target_project": "",
                "targetProject": "",
            }
            if snapshot.profile is not None:
                snapshot.profile = snapshot.profile.model_copy(update={"target_project": None})
        if leftover_resource_sandbox_preview_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
            plan=leftover_plan_for_chrome,
        ):
            workspace_memory.pop("sandbox_preview", None)
            workspace_memory.pop("sandboxPreview", None)
        if leftover_resource_sandbox_state_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
            plan=leftover_plan_for_chrome,
        ):
            workspace_memory.pop("sandbox_state", None)
            workspace_memory.pop("sandboxState", None)
        if leftover_resource_selected_detail_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
            plan=leftover_plan_for_chrome,
        ):
            workspace_memory.pop("selected_resource_detail", None)
            workspace_memory.pop("selectedResourceDetail", None)
        if leftover_resource_library_list_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
            plan=leftover_plan_for_chrome,
        ):
            live_resources = list(getattr(snapshot.memory, "resources", None) or [])
            kept_resources = [
                item
                for item in live_resources
                if resource_record_is_acknowledged_upload(item)
            ]
            if len(kept_resources) != len(live_resources):
                snapshot.memory = snapshot.memory.model_copy(update={"resources": kept_resources})
        independent_selection = workspace_memory.get("live_training_selection")
        independent_card_is_live = (
            isinstance(independent_selection, dict)
            and isinstance(workspace_id, str)
            and independent_selection.get("workspace_id") == workspace_id
            and bool(independent_selection.get("selected_at"))
            and bool(independent_selection.get("card_id"))
            and independent_selection.get("card_id") == deps.runtime.memory_service.live_selected_training_card_id(workspace_id or "")
        )
        if not independent_card_is_live and leftover_training_handoff_chrome_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
            plan=leftover_plan_for_chrome,
        ):
            workspace_memory.pop("selected_card_id", None)
            workspace_memory.pop("selectedCardId", None)
            workspace_memory.pop("selected_card_title", None)
            workspace_memory.pop("selectedCardTitle", None)
            workspace_memory.pop("active_training_card_routing", None)
            workspace_memory.pop("activeTrainingCardRouting", None)
            if snapshot.memory is not None:
                snapshot.memory = snapshot.memory.model_copy(
                    update={"active_training_card_routing": None}
                )
        competing_plan, competing_runtime = deps.leftover_runtime_for_workspace(workspace_id or "")
        competing_identity = leftover_bound_plan_competing_identity_labels(
            plan=snapshot.plan or competing_plan,
            runtime=competing_runtime or leftover_runtime,
            existing=competing_runtime or leftover_runtime,
            card_titles=[
                str(getattr(card, "title", "") or "")
                for card in (
                    deps.runtime.memory_service.get_cards(workspace_id) if workspace_id else []
                )
            ],
            leftover_plans=(
                deps.runtime.repository.list_plans(workspace_id)
                if workspace_id and hasattr(deps.runtime.repository, "list_plans")
                else []
            ),
        )
        if competing_identity:
            sandbox = workspace_memory.get("sandbox_preview") or workspace_memory.get(
                "sandboxPreview"
            )
            if isinstance(sandbox, dict) and str(sandbox.get("title") or "").strip() in competing_identity:
                workspace_memory.pop("sandbox_preview", None)
                workspace_memory.pop("sandboxPreview", None)
            live_resources = list(getattr(snapshot.memory, "resources", None) or [])
            kept_resources = [
                item
                for item in live_resources
                if str(getattr(item, "name", "") or getattr(item, "title", "") or "").strip()
                not in competing_identity
            ]
            if len(kept_resources) != len(live_resources):
                snapshot.memory = snapshot.memory.model_copy(update={"resources": kept_resources})
            for key in (
                "onboarding_request",
                "onboardingRequest",
                "project_context",
                "projectContext",
            ):
                if str(workspace_memory.get(key) or "").strip() in competing_identity:
                    workspace_memory[key] = ""
            selected_detail = workspace_memory.get("selected_resource_detail")
            if not isinstance(selected_detail, dict):
                selected_detail = workspace_memory.get("selectedResourceDetail")
            if isinstance(selected_detail, dict):
                detail_title = str(
                    selected_detail.get("title")
                    or selected_detail.get("name")
                    or selected_detail.get("match_summary")
                    or selected_detail.get("matchSummary")
                    or ""
                ).strip()
                if detail_title in competing_identity:
                    workspace_memory.pop("selected_resource_detail", None)
                    workspace_memory.pop("selectedResourceDetail", None)
            selected_card = str(
                workspace_memory.get("selected_card_title")
                or workspace_memory.get("selectedCardTitle")
                or ""
            ).strip()
            if selected_card in competing_identity:
                workspace_memory["selected_card_title"] = ""
                workspace_memory.pop("selectedCardTitle", None)
            leftover_handoff = workspace_memory.get("latest_training_handoff")
            if not isinstance(leftover_handoff, dict):
                leftover_handoff = workspace_memory.get("latestTrainingHandoff")
            if isinstance(leftover_handoff, dict):
                handoff_title = str(
                    leftover_handoff.get("card_title") or leftover_handoff.get("cardTitle") or ""
                ).strip()
                if handoff_title in competing_identity:
                    workspace_memory["latest_training_handoff"] = {
                        **leftover_handoff,
                        "card_title": "",
                    }
                    workspace_memory.pop("latestTrainingHandoff", None)
        if leftover_coach_conversation_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            if not preserve_session_history:
                snapshot.messages = []
            snapshot.memory = snapshot.memory.model_copy(update={"active_thread": None})
            workspace_memory.pop("active_thread", None)
            workspace_memory.pop("activeThread", None)
            workspace_memory.pop("latest_conversation", None)
            workspace_memory.pop("latestConversation", None)
        if leftover_suggested_actions_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            leftover_turn = workspace_memory.get("latest_coach_turn") or workspace_memory.get(
                "latestCoachTurn"
            )
            if isinstance(leftover_turn, dict):
                workspace_memory["latest_coach_turn"] = {
                    **leftover_turn,
                    "suggested_actions": [],
                }
                workspace_memory.pop("latestCoachTurn", None)
            workspace_memory.pop("suggested_actions", None)
        if leftover_first_look_headline_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            understanding = snapshot.memory.workspace_understanding
            if understanding is not None:
                snapshot.memory = snapshot.memory.model_copy(
                    update={
                        "workspace_understanding": understanding.model_copy(
                            update={"first_look_summary": None}
                        )
                    }
                )
        if leftover_evaluation_headline_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ) and snapshot.evaluation is not None:
            snapshot.evaluation = snapshot.evaluation.model_copy(update={"summary": ""})
        if leftover_streaming_checkpoint_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            workspace_memory.pop("latest_streaming_checkpoint", None)
            workspace_memory.pop("latestStreamingCheckpoint", None)
        leftover_transfer = workspace_memory.get("latest_transfer_state")
        if not isinstance(leftover_transfer, dict):
            leftover_transfer = workspace_memory.get("latestTransferState")
        honest_transfer = prefer_recovered_transfer_skill(
            runtime=leftover_runtime,
            existing=leftover_runtime,
            transfer=leftover_transfer if isinstance(leftover_transfer, dict) else None,
        )
        if leftover_transfer_skill_is_not_live(
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            if honest_transfer is None:
                workspace_memory.pop("latest_transfer_state", None)
                workspace_memory.pop("latestTransferState", None)
            else:
                workspace_memory["latest_transfer_state"] = honest_transfer
                workspace_memory.pop("latestTransferState", None)
        snapshot.memory.workspace = workspace_memory
    if workspace_id:
        honest_source: list[dict[str, object]] = []
        for item in snapshot.suggested_actions or []:
            if isinstance(item, SuggestedAction):
                honest_source.append(item.model_dump())
            elif isinstance(item, dict):
                honest_source.append(item)
        leftover_turn = workspace_memory.get("latest_coach_turn")
        if not isinstance(leftover_turn, dict):
            leftover_turn = workspace_memory.get("latestCoachTurn")
        leftover_turn = leftover_turn if isinstance(leftover_turn, dict) else {}
        for item in leftover_turn.get("suggested_actions") or leftover_turn.get("suggestedActions") or []:
            if isinstance(item, dict):
                honest_source.append(item)
        honest_actions = deps.honest_suggested_actions_without_live_object(
            honest_source,
            workspace_id=workspace_id,
            response_language=response_language,
            snapshot=snapshot,
            current_task=snapshot.current_task,
            current_plan=snapshot.plan,
            current_evaluation=snapshot.evaluation,
            message=message,
        )
        minting_not_live = leftover_minting_suggested_actions_are_not_live(
            plan=snapshot.plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=str(getattr(snapshot.current_task, "title", "") or ""),
        )
        if minting_not_live:
            kept_honest = [
                item
                for item in honest_actions
                if str(
                    item.get("action")
                    if isinstance(item, dict)
                    else getattr(item, "action", "")
                )
                not in {"plan", "task", "next_task"}
            ]
            honest_actions = kept_honest or deps.structured_suggested_actions(
                [
                    {
                        "label": localized_text(
                            "Continue from the recovered step",
                            "从已恢复的这一步继续",
                            response_language,
                        ),
                        "action": "hint",
                    }
                ],
                response_language=response_language,
                scenario="general",
            )
        coerced_actions: list[SuggestedAction] = []
        for item in honest_actions:
            if isinstance(item, SuggestedAction):
                coerced_actions.append(item)
                continue
            if not isinstance(item, dict):
                continue
            payload = dict(item)
            if not str(payload.get("label") or "").strip():
                continue
            if not str(payload.get("id") or "").strip():
                payload["id"] = f"suggested-{len(coerced_actions) + 1}"
            try:
                coerced_actions.append(SuggestedAction.model_validate(payload))
            except ValidationError:
                continue
        snapshot.suggested_actions = coerced_actions
        if (minting_not_live or deps.recovered_overlay_without_live_object(workspace_id)) and leftover_turn:
            workspace_memory["latest_coach_turn"] = {
                **leftover_turn,
                "suggested_actions": [
                    item.model_dump() if isinstance(item, SuggestedAction) else dict(item)
                    for item in coerced_actions
                ],
            }
            workspace_memory.pop("latestCoachTurn", None)
            snapshot.memory.workspace = workspace_memory
    orientation = build_coach_orientation_from_snapshot(
        snapshot,
        response_language=response_language,
    )
    snapshot.coach_orientation = orientation
    if workspace_id:
        existing = normalize_coach_orientation(workspace_memory.get("latest_coach_orientation"))
        if existing != orientation:
            deps.runtime.memory_service.update_workspace_state(
                workspace_id,
                latest_coach_orientation=orientation,
            )
            snapshot.memory.workspace = {
                **workspace_memory,
                "latest_coach_orientation": orientation,
            }
    from ..pedagogy.stage_material_state import stage_material_state

    snapshot.stage_materials = stage_material_state(
        snapshot.plan,
        deps.runtime.memory_service.list_teaching_assets(workspace_id, scope=None, limit=10000)
        if workspace_id and snapshot.plan else [],
    )
    return snapshot


def review_aware_next_task(deps: CoachSupportDeps,
    *,
    workspace_id: str,
    profile: UserProfile | None,
    focus_area: str | None,
    response_language: str | None,
) -> TaskSpec:
    memory = deps.runtime.memory_service.snapshot(workspace_id)
    first_look_summary = (
        memory.workspace_understanding.first_look_summary
        if memory.workspace_understanding is not None
        else None
    )
    first_look_available = first_look_summary is not None
    coach_defaults = memory.workspace.get("coach_defaults") if isinstance(memory.workspace, dict) else None
    actionable_due_reviews = [
        item
        for item in memory.due_reviews
        if item.concept != "resource-grounding"
        and not (
            item.concept == "new-workspace"
            and (memory.active_plan is not None or first_look_available)
        )
    ]
    if first_look_available and not focus_area:
        actionable_due_reviews = [item for item in actionable_due_reviews if item.concept != "new-workspace"]
    active_thread = memory.active_thread
    if (
        active_thread
        and active_thread.focus_area.strip()
        and active_thread.next_step.strip()
    ):
        visible_thread_focus = deps.display_focus_label(active_thread.focus_area, response_language)
        return TaskSpec(
            id=f"thread-{uuid4().hex[:10]}",
            title=localized_text(
                f"Continue: {visible_thread_focus}",
                f"\u63a5\u7740\u505a\uff1a{visible_thread_focus}",
                response_language,
            ),
            natural_language_goal=localized_text(
                f"Stay on the live coaching thread and finish this next thin move before opening another lane: {active_thread.next_step}",
                f"沿着当前教练主线继续推进，先完成这一条最薄、可验证的下一步，再考虑开新分支：{active_thread.next_step}",
                response_language,
            ),
            inputs=["Current project context", "Current file if relevant"],
            outputs=[
                "",
                "",
            ],
            constraints=[
                "",
                *(
                    [
                        localized_text(
                            f"Respect this blocker: {active_thread.blocker}",
                            f"\u6ce8\u610f\u8fd9\u4e2a\u5361\u70b9\uff1a{active_thread.blocker}",
                            response_language,
                        )
                    ]
                    if active_thread.blocker.strip()
                    else []
                ),
            ],
            edge_cases=[],
            failure_conditions=[],
            verification_strategy=[
                localized_text("Verify the exact active-thread step after the patch lands.", "\u8865\u4e01\u843d\u5730\u540e\u9a8c\u8bc1\u5f53\u524d\u4e3b\u7ebf\u8fd9\u4e00\u6b65\u662f\u5426\u771f\u7684\u5b8c\u6210\u3002", response_language),
            ],
            metadata={
                "concepts": [active_thread.focus_area],
                "scenario": active_thread.scenario or "general",
                "source": "active_thread",
            },
        )
    if actionable_due_reviews:
        due_review = actionable_due_reviews[0]
        review_title = localized_text(
            f"Review: {due_review.concept}",
            f"\u590d\u4e60\uff1a{due_review.concept}",
            response_language,
        )
        return TaskSpec(
            id=f"review-{uuid4().hex[:10]}",
            title=review_title,
            natural_language_goal=localized_text(
                f"Revisit '{due_review.concept}' through one very small implementation step. Focus on: {due_review.reason}",
                f"\u56f4\u7ed5\u300c{due_review.concept}\u300d\u505a\u4e00\u4e2a\u5f88\u5c0f\u7684\u5b9e\u73b0\u590d\u4e60\uff0c\u91cd\u70b9\u89e3\u51b3\uff1a{due_review.reason}",
                response_language,
            ),
            inputs=["Current project context", "Current file if relevant"],
            outputs=[
                "",
                localized_text("A short explanation of what changed", "一段简短的复盘说明", response_language),
            ],
            constraints=[
                localized_text("Keep the review slice narrow.", "\u590d\u4e60\u8303\u56f4\u5fc5\u987b\u5f88\u5c0f\u3002", response_language),
                localized_text(
                    "Prefer code over passive explanation.",
                    "",
                    response_language,
                ),
            ],
            edge_cases=[
                "",
            ],
            failure_conditions=[
                "",
            ],
            verification_strategy=[
                localized_text(
                    "Explain what improved and verify the small patch.",
                    "",
                    response_language,
                )
            ],
            metadata={
                "concepts": [due_review.concept],
                "source": "due_review",
                "review": True,
            },
        )
    if (
        active_thread
        and active_thread.focus_area.strip()
        and active_thread.next_step.strip()
    ):
        visible_thread_focus = deps.display_focus_label(active_thread.focus_area, response_language)
        return TaskSpec(
            id=f"thread-{uuid4().hex[:10]}",
            title=localized_text(
                f"Continue: {visible_thread_focus}",
                f"\u7ee7\u7eed\u63a8\u8fdb\uff1a{visible_thread_focus}",
                response_language,
            ),
            natural_language_goal=localized_text(
                f"Stay on the live coaching thread and finish this next thin move before opening another lane: {active_thread.next_step}",
                f"继续沿着当前主线，把这一条最薄的下一步先做完，再考虑开新分支：{active_thread.next_step}",
                response_language,
            ),
            inputs=["Current project context", "Current file if relevant"],
            outputs=[
                "",
                "",
            ],
            constraints=[
                localized_text("Do not widen scope before this move lands.", "\u8fd9\u4e00\u6b65\u6ca1\u843d\u5730\u524d\u4e0d\u8981\u6269\u5927\u8303\u56f4\u3002", response_language),
                *( [localized_text(f"Respect this blocker: {active_thread.blocker}", f"\u6ce8\u610f\u8fd9\u4e2a\u5361\u70b9\uff1a{active_thread.blocker}", response_language)] if active_thread.blocker.strip() else [] ),
            ],
            edge_cases=[],
            failure_conditions=[],
            verification_strategy=[
                localized_text("Verify the exact active-thread step after the patch lands.", "\u8865\u4e01\u843d\u5730\u540e\u9a8c\u8bc1\u5f53\u524d\u4e3b\u7ebf\u8fd9\u4e00\u6b65\u662f\u5426\u771f\u7684\u5b8c\u6210\u3002", response_language),
            ],
            metadata={
                "concepts": [active_thread.focus_area],
                "scenario": active_thread.scenario or "general",
                "source": "active_thread",
            },
        )
    if actionable_due_reviews:
        due_review = actionable_due_reviews[0]
        review_title = localized_text(
            f"Review: {due_review.concept}",
            f"\u590d\u4e60\uff1a{due_review.concept}",
            response_language,
        )
        return TaskSpec(
            id=f"review-{uuid4().hex[:10]}",
            title=review_title,
            natural_language_goal=localized_text(
                f"Revisit '{due_review.concept}' through one very small implementation step. Focus on: {due_review.reason}",
                f"\u56f4\u7ed5\u300c{due_review.concept}\u300d\u505a\u4e00\u4e2a\u5f88\u5c0f\u7684\u5b9e\u73b0\u590d\u4e60\uff0c\u91cd\u70b9\u89e3\u51b3\uff1a{due_review.reason}",
                response_language,
            ),
            inputs=["Current project context", "Current file if relevant"],
            outputs=[
                "",
                localized_text("A short explanation of what changed", "一段简短的复盘说明", response_language),
            ],
            constraints=[
                localized_text("Keep the review slice narrow.", "\u590d\u4e60\u8303\u56f4\u5fc5\u987b\u5f88\u5c0f\u3002", response_language),
                localized_text(
                    "Prefer code over passive explanation.",
                    "",
                    response_language,
                ),
            ],
            edge_cases=[],
            failure_conditions=[
                "",
            ],
            verification_strategy=[
                localized_text(
                    "Explain what improved and verify the small patch.",
                    "",
                    response_language,
                )
            ],
            metadata={
                "concepts": [due_review.concept],
                "source": "due_review",
                "review": True,
            },
        )
    def first_look_focus_hint_from_summary(summary: FirstLookSummary | None) -> str | None:
        if summary is None:
            return None
        candidates = [
            summary.training_opportunities[0] if summary.training_opportunities else "",
            summary.recommended_next_step,
            summary.project_type_guess.replace("_", " ") if summary.project_type_guess else "",
            summary.folder_role.replace("_", " ") if summary.folder_role else "",
            summary.entry_points[0] if summary.entry_points else "",
        ]
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text:
                return text
        return None

    resolved_focus_area = focus_area or first_look_focus_hint_from_summary(first_look_summary)
    return deps.runtime.planner_service.next_task(
        profile,
        resolved_focus_area,
        current_plan=memory.active_plan,
        memory_snapshot=memory,
        response_language=response_language,
        coach_defaults=coach_defaults if isinstance(coach_defaults, dict) else None,
    )


def persist_turn_reflection(deps: CoachSupportDeps,
    *,
    workspace_id: str,
    session_id: str | None,
    user_message: str | None = None,
    scenario: str,
    response_language: str | None,
    answer_mode: str | None,
    coach_defaults: CoachDefaults | dict[str, object] | None,
    coach_turn_data: dict[str, object] | None,
    grounding_decision: GroundingDecision | None = None,
    stop_reason: str | None = None,
    recovered_stop_reason: str | None = None,
    local_sequence_fallback: bool = False,
) -> None:
    if not coach_turn_data:
        return

    coach_context = coach_turn_data.get("coach_context")
    turn_summary = coach_turn_data.get("coach_turn")
    if not isinstance(turn_summary, CoachTurnSummary):
        return

    # Field-level memory admission (§2.7): the resolve step cached the
    # facts-derived provenance mapping on the payload; pass it through.
    # None keeps the memory-side defaults when no resolve step ran.
    memory_provenance: dict[str, str] | None = None
    cached_provenance = coach_turn_data.get(deps.GROUNDING_MEMORY_PROVENANCE_CACHE_KEY)
    if isinstance(cached_provenance, dict):
        memory_provenance = {
            str(key): str(value)
            for key, value in cached_provenance.items()
            if value is not None
        }

    focus_area: str | None = None
    review_note: str | None = None
    teaching_note: str | None = None
    current_file_name = ""
    focus_candidates: list[object] = []
    thread_summary = turn_summary.summary.strip()
    thread_next_step = turn_summary.next_step.strip()
    turn_decision = turn_summary.decision.strip()
    turn_blocker = turn_summary.blocker.strip()
    turn_teaching_note = turn_summary.teaching_note.strip()
    turn_confidence = turn_summary.confidence.strip()
    turn_evidence = [str(item).strip() for item in turn_summary.evidence if str(item).strip()]
    review_queue_summary = turn_summary.review_queue_summary.strip()
    recovery_without_learning_evidence = deps.recovery_turn_has_no_learning_evidence(
        stop_reason=stop_reason,
        recovered_stop_reason=recovered_stop_reason,
        local_sequence_fallback=local_sequence_fallback,
    )
    provider_recovery_blocked = recovery_without_learning_evidence
    existing_memory_snapshot = deps.runtime.memory_service.snapshot(workspace_id)
    existing_active_thread_snapshot = existing_memory_snapshot.active_thread
    existing_active_thread_payload = existing_memory_snapshot.workspace.get("active_thread")
    existing_provider_recovery = deps.is_provider_recovery_thread_payload(
        existing_active_thread_payload
    )
    existing_provider_blocker = (
        existing_active_thread_snapshot.blocker.strip()
        if existing_provider_recovery and existing_active_thread_snapshot is not None
        else ""
    )
    existing_provider_summary = (
        existing_active_thread_snapshot.summary.strip()
        if existing_provider_recovery and existing_active_thread_snapshot is not None
        else ""
    )
    existing_provider_next_step = (
        existing_active_thread_snapshot.next_step.strip()
        if existing_provider_recovery and existing_active_thread_snapshot is not None
        else ""
    )
    recovered_provider_thread = existing_provider_recovery and not recovery_without_learning_evidence
    if recovered_provider_thread and existing_provider_blocker and turn_blocker == existing_provider_blocker:
        turn_blocker = ""
    if recovered_provider_thread and thread_summary == existing_provider_summary:
        thread_summary = ""
    if recovered_provider_thread and thread_next_step == existing_provider_next_step:
        thread_next_step = ""
    preserve_existing_thread = bool(
        scenario == "general"
        and deps.message_requests_lane_continuation(user_message)
        and existing_active_thread_snapshot is not None
    )
    if preserve_existing_thread and existing_active_thread_snapshot is not None:
        focus_area = existing_active_thread_snapshot.focus_area.strip() or focus_area
        scenario = existing_active_thread_snapshot.scenario.strip() or scenario
        if recovered_provider_thread:
            if thread_summary == existing_provider_summary:
                thread_summary = ""
            if thread_next_step == existing_provider_next_step:
                thread_next_step = deps.local_continuation_step_for_scenario(
                    scenario,
                    response_language,
                )
        else:
            thread_summary = existing_active_thread_snapshot.summary.strip() or thread_summary
            thread_next_step = existing_active_thread_snapshot.next_step.strip() or thread_next_step
        if not turn_decision:
            turn_decision = existing_active_thread_snapshot.decision.strip()
        if not turn_blocker and not recovered_provider_thread:
            turn_blocker = existing_active_thread_snapshot.blocker.strip()
        if not turn_teaching_note:
            turn_teaching_note = existing_active_thread_snapshot.teaching_note.strip()
        if not turn_confidence:
            turn_confidence = existing_active_thread_snapshot.confidence.strip()
        if not turn_evidence:
            turn_evidence = [
                str(item).strip()
                for item in existing_active_thread_snapshot.evidence
                if str(item).strip()
            ]
    if isinstance(coach_context, dict):
        current_file_name = str(coach_context.get("current_file_name") or "").strip()
        focus_candidates.extend(
            [
                coach_context.get("coach_anchor"),
                coach_context.get("current_focus"),
                coach_context.get("active_task"),
                coach_context.get("active_stage"),
            ]
        )
        teaching_observations = coach_context.get("teaching_observations")
        if isinstance(teaching_observations, list) and teaching_observations:
            first_observation = str(teaching_observations[0]).strip()
            teaching_note = first_observation or None
        selected_teaching_asset_ids = coach_context.get("selected_teaching_asset_ids")
        if not isinstance(selected_teaching_asset_ids, list) or not selected_teaching_asset_ids:
            selected_teaching_asset_ids = coach_context.get("teaching_asset_ids")
        if isinstance(selected_teaching_asset_ids, list) and selected_teaching_asset_ids:
            deps.runtime.memory_service.mark_teaching_assets_used(
                workspace_id,
                [str(item) for item in selected_teaching_asset_ids if str(item).strip()],
            )
        active_thread = coach_context.get("active_thread")
        if isinstance(active_thread, dict):
            focus_candidates.insert(0, active_thread.get("focus_area"))
            active_thread_summary = str(active_thread.get("summary") or "").strip()
            active_thread_next_step = str(active_thread.get("next_step") or "").strip()
            if not (
                recovered_provider_thread
                and active_thread_summary == existing_provider_summary
            ):
                thread_summary = active_thread_summary or thread_summary
            if not (
                recovered_provider_thread
                and active_thread_next_step == existing_provider_next_step
            ):
                thread_next_step = active_thread_next_step or thread_next_step
            if not review_note:
                blocker = str(active_thread.get("blocker") or "").strip()
                if not (recovered_provider_thread and blocker == existing_provider_blocker):
                    review_note = blocker or review_note
    # Memory-anchor anti-drift: the persisted focus may reuse thread/task
    # anchors and extracted technical concepts, but never the raw opening
    # clause of the learner message (2026-10-08 real-teaching review).
    focus_area = deps.resolve_focus_hint(
        user_message=user_message,
        candidates=focus_candidates,
        fallback_current_file=current_file_name,
        allow_message_prefix=False,
    )
    focus_area = sanitize_memory_anchor(focus_area, user_message) or None
    if preserve_existing_thread and existing_active_thread_snapshot is not None:
        focus_area = existing_active_thread_snapshot.focus_area.strip() or focus_area
    if not provider_recovery_blocked and scenario in deps.GUIDED_LANE_SCENARIOS:
        focus_area = deps.guided_focus_display_value(
            focus_area,
            scenario=scenario,
            response_language=response_language,
        )
    if turn_blocker:
        review_note = turn_blocker
    elif recovered_provider_thread and review_note == existing_provider_blocker:
        review_note = None
    if recovered_provider_thread:
        if thread_summary == existing_provider_summary:
            thread_summary = ""
        if thread_next_step == existing_provider_next_step:
            thread_next_step = ""
        thread_summary = thread_summary or deps.provider_recovery_resumed_summary(response_language)
        thread_next_step = thread_next_step or deps.provider_recovery_resumed_next_step(
            scenario,
            response_language,
        )
    if turn_teaching_note:
        teaching_note = turn_teaching_note
    if review_note:
        normalized_review_note = review_note.strip().lower()
        if (
            (review_queue_summary and review_note.strip() == review_queue_summary)
            or any(
                token in normalized_review_note
                for token in ("new-workspace", "plan-discipline", "resource-grounding")
            )
        ):
            review_note = None
    if not provider_recovery_blocked and scenario in deps.GUIDED_LANE_SCENARIOS and (
        deps.continuation_step_needs_local_repair(thread_next_step)
        or deps.generic_guided_review_fallback_needs_repair(thread_next_step)
    ):
        repaired_thread_next_step = deps.extract_lane_continuation_step(thread_next_step)
        if (
            not repaired_thread_next_step
            or deps.continuation_step_needs_local_repair(repaired_thread_next_step)
            or deps.generic_guided_review_fallback_needs_repair(repaired_thread_next_step)
        ):
            repaired_thread_next_step = deps.local_continuation_step_for_scenario(
                scenario,
                response_language,
            )
        if repaired_thread_next_step:
            thread_next_step = repaired_thread_next_step

    # Grounding downgrade: an ungrounded next step is a suggestion pending
    # confirmation, not a plan-ready instruction — it must not become the
    # remembered thread next step or review-task hint (2026-10-08 review,
    # case 03 leak into memory.current_focus / review hints).
    ungrounded_next_step = bool(turn_summary.requires_confirmation)
    if grounding_decision is not None and grounding_decision.requires_confirmation:
        # Same-signal belt for the cached decision: a downgraded decision can
        # never leave its next step in thread memory or review hints.
        ungrounded_next_step = True
    if ungrounded_next_step:
        thread_next_step = ""
    reflection_next_step = "" if ungrounded_next_step else turn_summary.next_step
    if teaching_note and teaching_note not in reflection_next_step:
        reflection_next_step = f"{reflection_next_step} {teaching_note}".strip()
    if thread_next_step and thread_next_step not in reflection_next_step:
        reflection_next_step = thread_next_step

    resolved_defaults: CoachDefaults | None = None
    # The turn runs on a concrete mode, but workspace memory must retain
    # the user's durable preference (including auto and coach-first).
    persisted_answer_mode = str(answer_mode or "").strip()
    if persisted_answer_mode not in {"auto", "coach-first", "guided", "balanced", "direct"}:
        persisted_answer_mode = deps.normalize_answer_mode(answer_mode)
    if isinstance(coach_defaults, CoachDefaults):
        resolved_defaults = coach_defaults
    elif isinstance(coach_defaults, dict):
        try:
            resolved_defaults = CoachDefaults.model_validate(coach_defaults)
        except Exception:
            resolved_defaults = None

    if recovery_without_learning_evidence:
        deps.runtime.memory_service.record_recoverable_turn(
            workspace_id=workspace_id,
            session_id=session_id,
            user_message=user_message,
            scenario=scenario,
            focus_area=focus_area,
            summary=thread_summary,
            next_step=thread_next_step,
            blocker=review_note or turn_blocker,
            decision=turn_decision,
            teaching_note=teaching_note or turn_teaching_note,
            confidence=turn_confidence,
            evidence=turn_evidence,
            answer_mode=persisted_answer_mode,
            response_language=response_language,
            coach_defaults=resolved_defaults,
            stop_reason=str(stop_reason or recovered_stop_reason or "").strip(),
        )
        return

    deps.runtime.memory_service.record_coaching_reflection(
        workspace_id=workspace_id,
        scenario=scenario,
        focus_area=focus_area,
        summary=thread_summary,
        next_step=reflection_next_step,
        review_note=review_note,
        decision=turn_decision,
        teaching_note=teaching_note or turn_teaching_note,
        confidence=turn_confidence,
        evidence=turn_evidence,
        user_message=user_message,
        memory_provenance=memory_provenance,
    )
    deps.runtime.memory_service.record_turn_memory(
        workspace_id=workspace_id,
        session_id=session_id,
        user_message=user_message,
        scenario=scenario,
        focus_area=focus_area,
        summary=thread_summary,
        next_step=thread_next_step,
        answer_mode=persisted_answer_mode,
        response_language=response_language,
        review_note=review_note,
        coach_defaults=resolved_defaults,
        teaching_goal=turn_summary.teaching_goal,
        exercise_prompt=coach_context.get("exercise_prompt") if isinstance(coach_context, dict) else None,
        decision=turn_decision,
        teaching_note=teaching_note or turn_teaching_note,
        confidence=turn_confidence,
        evidence=turn_evidence,
        memory_provenance=memory_provenance,
    )


def build_coach_context(deps: CoachSupportDeps, 
    snapshot: WorkbenchSnapshot,
    resource_context: dict[str, object] | None = None,
    *,
    response_language: str | None = None,
    message: str | None = None,
    active_view: str | None = None,
    current_file=None,
    external_references: list[dict[str, object]] | None = None,
    curated_background_references: list[dict[str, object]] | None = None,
    recent_background_findings: list[dict[str, object]] | None = None,
    plan_runtime_recovery: dict[str, object] | None = None,
    context_tier: str = "full",
) -> dict[str, object]:
    minimal_context = context_tier == "minimal"
    coaching_state = snapshot.coaching_state
    memory = snapshot.memory
    active_stage = deps.active_plan_stage(snapshot.plan)
    failing_checks: list[str] = []
    if snapshot.evaluation:
        failing_checks = [
            check.label
            for check in [
                *snapshot.evaluation.static_checks,
                *snapshot.evaluation.dynamic_checks,
                *snapshot.evaluation.semantic_checks,
            ]
            if check.status in {"failed", "warning"}
        ]
    current_focus = deps.language_aligned_context_text(
        memory.current_focus or (coaching_state.summary if coaching_state else ""),
        response_language,
    )
    summary = deps.language_aligned_context_text(
        coaching_state.summary if coaching_state else memory.current_focus,
        response_language,
    )
    coaching_scenario = str(coaching_state.scenario if coaching_state else "general")
    keeps_review_signals = deps.turn_keeps_review_signals(
        coaching_scenario,
        snapshot.teaching_decision,
    )
    review_rhythm = deps.language_aligned_review_rhythm(memory.review_rhythm, response_language)
    if (
        not review_rhythm
        and keeps_review_signals
        and memory.due_reviews
    ):
        due_concept = str(memory.due_reviews[0].concept or "current review").strip()
        review_rhythm = localized_text(
            f"Review '{due_concept}' before opening another lane.",
            f"先回看「{due_concept}」，再开启新的主线。",
            response_language,
        )
    current_file_name = deps.function_guidance_current_file_name(
        current_file,
        scenario=coaching_scenario,
    )
    persist_chrome = live_plan_update_persist_chrome(
        plan=snapshot.plan,
        runtime=plan_runtime_recovery if isinstance(plan_runtime_recovery, dict) else coach_focus_runtime_from_snapshot(snapshot),
        existing=plan_runtime_recovery if isinstance(plan_runtime_recovery, dict) else coach_focus_runtime_from_snapshot(snapshot),
        stage_title=active_stage.title if active_stage else "",
        task_title=snapshot.current_task.title if snapshot.current_task else "",
        stage_goal=active_stage.goal if active_stage else "",
    )
    turn_focus_hint = deps.resolve_turn_focus_hint(
        user_message=message,
        current_file_name=current_file_name or None,
        task_focus=persist_chrome["task_focus"] or None,
        stage_focus=persist_chrome["stage_focus"] or None,
    )
    scenario_focus = deps.canonical_focus_for_scenario(coaching_scenario, response_language) or ""
    lane_focus = (
        turn_focus_hint
        or scenario_focus
        or persist_chrome["lane_focus"]
        or current_file_name
        or summary
    )
    coach_anchor = deps.language_aligned_context_text(memory.coach_anchor, response_language)
    active_thread = deps.language_aligned_thread_payload(
        memory.active_thread.model_dump() if memory.active_thread else None,
        response_language,
    )
    preserve_active_thread = deps.should_preserve_active_thread_for_turn(
        coaching_scenario,
        active_thread,
        message=message,
        grounding_context=resource_context,
        active_view=active_view,
    )
    preserve_relationship_continuity = deps.should_preserve_relationship_continuity_for_turn(
        memory,
        message=message,
        grounding_context=resource_context,
        active_view=active_view,
    )
    continuity_thread = (
        active_thread
        if preserve_active_thread or preserve_relationship_continuity
        else None
    )
    view_owned_lane = deps.active_view_owns_turn_lane(active_view)
    fresh_lane = view_owned_lane
    if not preserve_active_thread:
        active_thread = None
        fresh_lane = fresh_lane or coaching_scenario != "general" or bool(turn_focus_hint)
        current_focus = (
            deps.guided_focus_display_value(
                turn_focus_hint or lane_focus,
                scenario=coaching_scenario,
                response_language=response_language,
            )
            if fresh_lane
            else ""
        )
        if fresh_lane:
            if not keeps_review_signals:
                review_rhythm = ""
            coach_anchor = deps.guided_focus_display_value(
                turn_focus_hint or lane_focus or coach_anchor,
                scenario=coaching_scenario,
                response_language=response_language,
            )
    suppress_review_signals = fresh_lane and not keeps_review_signals
    thread_decision = ""
    thread_blocker = ""
    thread_teaching_note = ""
    thread_confidence = ""
    thread_evidence: list[str] = []
    if isinstance(active_thread, dict):
        thread_decision = str(active_thread.get("decision") or "").strip()
        thread_blocker = str(active_thread.get("blocker") or "").strip()
        thread_teaching_note = str(active_thread.get("teaching_note") or "").strip()
        thread_confidence = str(active_thread.get("confidence") or "").strip()
        raw_thread_evidence = active_thread.get("evidence")
        if isinstance(raw_thread_evidence, list):
            thread_evidence = [str(item).strip() for item in raw_thread_evidence if str(item).strip()][:4]
    next_step_hint = deps.language_aligned_flat_payload(
        deps.build_next_step_hint(
            snapshot=snapshot,
            response_language=response_language,
        ),
        response_language,
    )
    if not preserve_active_thread:
        next_step_hint = None
    next_step = deps.strip_visible_next_step_prefix(
        str(next_step_hint.get("title") or "").strip()
        if isinstance(next_step_hint, dict)
        else coaching_state.next_step if coaching_state else ""
    )
    selected_teaching_assets = snapshot.selected_teaching_assets
    selected_teaching_asset_ids = [item.id for item in selected_teaching_assets if item.id]
    workspace_understanding = (
        memory.workspace_understanding.model_dump() if memory.workspace_understanding else None
    )
    teaching_decision_payload = deps.language_aligned_flat_payload(
        snapshot.teaching_decision.model_dump() if snapshot.teaching_decision else None,
        response_language,
    )
    tone_decision_payload = deps.language_aligned_flat_payload(
        snapshot.tone_decision.model_dump() if snapshot.tone_decision else None,
        response_language,
    )
    affect_state_payload = deps.language_aligned_flat_payload(
        snapshot.affect_state.model_dump() if snapshot.affect_state else None,
        response_language,
    )
    implementation_guide_payload = deps.language_aligned_flat_payload(
        snapshot.implementation_guide.model_dump()
        if snapshot.implementation_guide
        else None,
        response_language,
    )
    exercise_prompt_payload = deps.language_aligned_flat_payload(
        snapshot.exercise_prompt if isinstance(snapshot.exercise_prompt, dict) else None,
        response_language,
    )
    principle_notes_payload = deps.language_aligned_flat_payload(
        snapshot.principle_notes.model_dump() if snapshot.principle_notes else None,
        response_language,
    )
    coach_defaults = memory.workspace.get("coach_defaults") if isinstance(memory.workspace, dict) else None
    workspace_id = (
        str(memory.workspace.get("workspace_id") or "").strip()
        if isinstance(memory.workspace, dict)
        else ""
    )
    memory_evidence = deps.runtime.memory_service.memory_evidence(workspace_id) if workspace_id else []
    preferred_strategy = (
        memory.teaching_strategy_effectiveness[0]
        if memory.teaching_strategy_effectiveness
        else None
    )
    strategy_preference_summary = ""
    if isinstance(preferred_strategy, dict):
        focus_label = preferred_strategy.get("focus_area") or preferred_strategy.get("scenario") or "current lane"
        success_count = preferred_strategy.get("success_count")
        total_count = preferred_strategy.get("total_count")
        challenge_level = preferred_strategy.get("challenge_level")
        hint_depth = preferred_strategy.get("hint_depth")
        explanation_mode = preferred_strategy.get("explanation_mode")
        next_step_bias = preferred_strategy.get("next_step_bias")
        strategy_preference_summary = deps.language_aligned_context_text(
            (
            f"{focus_label}: {success_count}/{total_count} useful outcomes with "
            f"{challenge_level}/{hint_depth}/{explanation_mode}/{next_step_bias}"
            ),
            response_language,
        )
    if fresh_lane:
        strategy_preference_summary = ""
        memory_evidence = []
    recent_teaching_signals: list[str] = []
    if isinstance(memory.workspace, dict):
        latest_signal = deps.language_aligned_context_text(
            memory.workspace.get("latest_turn_teaching_signal"),
            response_language,
        )
        if latest_signal:
            recent_teaching_signals.append(latest_signal)
    for item in memory.teaching_observations[:2]:
        normalized = deps.language_aligned_context_text(item, response_language)
        if normalized and normalized not in recent_teaching_signals:
            recent_teaching_signals.append(normalized)
    if not preserve_active_thread:
        recent_teaching_signals = []
    teaching_observations = [] if fresh_lane else memory.teaching_observations
    recent_wins = [] if fresh_lane else memory.recent_wins
    continuity_parts: list[str] = []
    if continuity_thread and isinstance(continuity_thread, dict):
        for candidate in (
            continuity_thread.get("focus_area"),
            continuity_thread.get("next_step"),
            continuity_thread.get("blocker"),
        ):
            normalized = deps.language_aligned_context_text(candidate, response_language)
            if normalized and normalized not in continuity_parts:
                continuity_parts.append(normalized)
            if len(continuity_parts) >= 2:
                break
    if not continuity_parts and preserve_relationship_continuity:
        for learning_outcome in reversed(memory.learning_outcomes[-3:]):
            if not isinstance(learning_outcome, dict):
                continue
            for candidate in (
                learning_outcome.get("concept"),
                learning_outcome.get("summary"),
            ):
                normalized = deps.language_aligned_context_text(candidate, response_language)
                if normalized and normalized not in continuity_parts:
                    continuity_parts.append(normalized)
                if len(continuity_parts) >= 2:
                    break
            if len(continuity_parts) >= 2:
                break
    if not continuity_parts:
        for candidate in (
            current_focus,
            next_step,
            recent_teaching_signals[0] if recent_teaching_signals else "",
        ):
            normalized = deps.language_aligned_context_text(candidate, response_language)
            if normalized and normalized not in continuity_parts:
                continuity_parts.append(normalized)
            if len(continuity_parts) >= 2:
                break
    continuity_summary = " -> ".join(continuity_parts[:2])
    if not preserve_active_thread and not preserve_relationship_continuity:
        continuity_summary = ""
    due_review_concepts = {
        str(getattr(item, "concept", "") or "").strip().lower()
        for item in getattr(memory, "due_reviews", []) or []
    }
    synthetic_due_reviews = bool(due_review_concepts) and due_review_concepts.issubset(
        {"new-workspace", "plan-discipline", "resource-grounding"}
    )
    relationship_stage = "active"
    first_turn_priority = ""
    if (
        not memory.active_thread
        and not memory.learning_outcomes
        and not (memory.due_reviews and not synthetic_due_reviews)
    ):
        relationship_stage = "intake"
        first_turn_priority = "orient, reassure, clarify learner goal and choose one coaching lane"
    if coaching_state and coaching_state.scenario == "onboarding":
        relationship_stage = "intake"
        first_look_next = deps.first_look_recommended_next_from_snapshot(snapshot)
        first_turn_priority = (
            (
                f"stay with the first-look next: {first_look_next}. "
                "Do not invent a plan, card, or task."
            )
            if first_look_next
            else "orient, reassure, clarify learner goal and choose one coaching lane"
        )
    elif fresh_lane:
        relationship_stage = "intake"
        if deps.resource_grounding_turn_prefers_fresh_lane(message, resource_context):
            first_turn_priority = (
                "answer the grounded library question directly before widening into adjacent coaching"
            )
        else:
            first_turn_priority = "re-anchor on the newly requested coaching lane and keep the first move compact"
    normalized_active_view_text = str(active_view or "").strip().lower()
    normalized_active_view = (
        normalized_active_view_text
        if normalized_active_view_text in {"coach", "plan", "resources", "training", "progress", "settings"}
        else None
    )
    coach_context = {
        "scenario": coaching_state.scenario if coaching_state else "general",
        "active_view": normalized_active_view,
        "learner_signal": coaching_state.learner_signal if coaching_state else "steady",
        "relationship_stage": relationship_stage,
        "first_turn_priority": first_turn_priority,
        "explicit_training_card_request": message_requests_explicit_training_card(message),
        "explicit_learning_note_request": message_requests_explicit_learning_note(message),
        "history_mode": (
            "fresh_lane" if fresh_lane else "resume"
        ),
        "summary": summary,
        "next_step": next_step,
        "decision": deps.language_aligned_context_text(
            thread_decision or (coaching_state.decision if coaching_state else ""),
            response_language,
        ),
        "blocker": deps.language_aligned_context_text(
            thread_blocker or (coaching_state.blocker if coaching_state else ""),
            response_language,
        ),
        "teaching_note": deps.language_aligned_context_text(
            thread_teaching_note or (coaching_state.teaching_note if coaching_state else ""),
            response_language,
        ),
        "confidence": deps.language_aligned_context_text(
            thread_confidence or (coaching_state.confidence if coaching_state else ""),
            response_language,
        ),
        "evidence": thread_evidence or (coaching_state.evidence if coaching_state else []),
        "next_step_hint": next_step_hint,
        "encouragement": deps.language_aligned_context_text(
            coaching_state.encouragement if coaching_state else "",
            response_language,
        ),
        "intervention_strategy": deps.language_aligned_context_text(
            coaching_state.intervention_strategy if coaching_state else "",
            response_language,
        ),
        "teaching_goal": deps.language_aligned_context_text(
            coaching_state.teaching_goal if coaching_state else "",
            response_language,
        ),
        "resume_thread": deps.language_aligned_context_text(
            coaching_state.resume_thread if coaching_state else "",
            response_language,
        ),
        "support_strategy": deps.language_aligned_context_text(
            coaching_state.support_strategy if coaching_state else "",
            response_language,
        ),
        "current_focus": current_focus,
        "current_file_name": current_file_name or None,
        "active_stage": deps.live_stage_object_label(
            snapshot.plan,
            snapshot=snapshot,
            stage=active_stage,
        )
        or None,
        "active_task": persist_chrome["active_task"] or None,
        "learner_state": snapshot.learner_state.model_dump() if snapshot.learner_state else None,
        "teaching_decision": teaching_decision_payload,
        "teaching_mode_strategy": {
            "lesson_shape": snapshot.teaching_decision.lesson_shape if snapshot.teaching_decision else "",
            "exercise_shape": snapshot.teaching_decision.exercise_shape if snapshot.teaching_decision else "",
            "teaching_strategy": snapshot.teaching_decision.teaching_strategy if snapshot.teaching_decision else "",
            "closing_move": snapshot.teaching_decision.closing_move if snapshot.teaching_decision else "",
            "artifact_priority": snapshot.teaching_decision.artifact_priority if snapshot.teaching_decision else [],
        },
        "coaching_adaptation": memory.coaching_adaptation.model_dump() if memory.coaching_adaptation else None,
        "affect_state": affect_state_payload,
        "tone_decision": tone_decision_payload,
        "recent_wins": deps.language_aligned_context_list(recent_wins, response_language),
        "weak_spots": deps.language_aligned_context_list(memory.weaknesses, response_language),
        "coach_anchor": coach_anchor,
        "top_weakness": deps.language_aligned_context_text(memory.top_weakness, response_language),
        "lowest_mastery_concepts": deps.language_aligned_context_list(
            memory.lowest_mastery_concepts,
            response_language,
        ),
        "review_rhythm": review_rhythm,
        "due_reviews": [] if suppress_review_signals else [item.model_dump() for item in memory.due_reviews],
        "due_review_count": 0 if suppress_review_signals else memory.due_review_count,
        "pace_signal": deps.language_aligned_context_text(memory.pace_signal, response_language),
        "memory_evidence": memory_evidence,
        "strategy_preference_summary": strategy_preference_summary,
        "recent_teaching_signals": recent_teaching_signals[:3],
        "continuity_summary": continuity_summary,
        "teaching_observations": deps.language_aligned_context_list(
            teaching_observations,
            response_language,
        ),
        "teaching_knowledge_catalog": memory.teaching_knowledge_catalog,
        "workspace_understanding": workspace_understanding,
        "project_summary": deps.language_aligned_context_text(
            workspace_understanding.get("repo_summary") if workspace_understanding else "",
            response_language,
        ),
        "project_entry_points": deps.function_guidance_entry_points(
            workspace_understanding.get("entry_points", []) if workspace_understanding else [],
            scenario=coaching_scenario,
        ),
        "project_feature_lanes": workspace_understanding.get("feature_lanes", [])
        if workspace_understanding
        else [],
        "project_risk_zones": workspace_understanding.get("risk_zones", []) if workspace_understanding else [],
        "project_training_opportunities": workspace_understanding.get("training_opportunities", [])
        if workspace_understanding
        else [],
        "learner_name": deps.language_aligned_context_text(
            memory.workspace.get("learner_name") if isinstance(memory.workspace, dict) else "",
            response_language,
        ),
        "target_project": deps.language_aligned_context_text(
            memory.profile.target_project if memory.profile else "",
            response_language,
        ),
        "preferred_stack": deps.language_aligned_context_text(
            memory.workspace.get("preferred_stack") if isinstance(memory.workspace, dict) else "",
            response_language,
        ),
        "preferred_rhythm": deps.language_aligned_context_text(
            memory.workspace.get("preferred_rhythm") if isinstance(memory.workspace, dict) else "",
            response_language,
        ),
        "preferred_learning_mode": (
            deps.language_aligned_context_text(
                memory.workspace.get("preferred_learning_mode") if isinstance(memory.workspace, dict) else "",
                response_language,
            )
        ),
        "onboarding_request": deps.language_aligned_context_text(
            memory.workspace.get("onboarding_request") if isinstance(memory.workspace, dict) else "",
            response_language,
        ),
        "review_queue_summary": ""
        if suppress_review_signals
        else deps.language_aligned_context_text(
            snapshot.review_queue_summary,
            response_language,
        ),
        "next_review_due": None if suppress_review_signals else snapshot.next_review_due,
        "failing_checks": failing_checks,
        "implementation_guide": implementation_guide_payload,
        "project_ideas": [item.model_dump() for item in snapshot.project_ideas],
        "project_adaptation_guide": snapshot.project_adaptation_guide.model_dump()
        if snapshot.project_adaptation_guide
        else None,
        "project_sources": [item.model_dump() for item in snapshot.project_sources],
        "principle_notes": principle_notes_payload,
        "selected_teaching_assets": [item.model_dump() for item in selected_teaching_assets],
        "selected_teaching_asset_ids": selected_teaching_asset_ids,
        "exercise_prompt": exercise_prompt_payload,
        "provider_mode": "background-embedded",
        "active_thread": active_thread,
        "coach_defaults": coach_defaults,
        "coach_focus": {
            "current_focus": current_focus,
            "review_rhythm": review_rhythm,
            "summary": summary,
            "next_step": next_step,
            "next_step_hint": next_step_hint,
            "active_stage": persist_chrome["stage_focus"] or None,
            "stage_focus": persist_chrome["stage_focus"] or None,
            "lane_focus": lane_focus or None,
            "active_task": persist_chrome["active_task"] or None,
            "due_review_count": 0 if suppress_review_signals else memory.due_review_count,
        },
        "memory": deps.language_aligned_memory_payload(memory.model_dump(), response_language),
        "coaching_state": deps.language_aligned_coaching_state_payload(
            coaching_state.model_dump() if coaching_state else None,
            response_language,
        ),
    }
    if fresh_lane and isinstance(coach_context.get("memory"), dict):
        fresh_memory = dict(coach_context["memory"])
        fresh_memory["current_focus"] = ""
        fresh_memory["recent_summary"] = ""
        fresh_memory["recent_wins"] = []
        fresh_memory["teaching_observations"] = []
        fresh_memory["memory_evidence"] = []
        if suppress_review_signals:
            fresh_memory["due_reviews"] = []
            fresh_memory["due_review_count"] = 0
            fresh_memory["review_rhythm"] = ""
        fresh_memory["active_thread"] = None
        coach_context["memory"] = fresh_memory
    if minimal_context and isinstance(coach_context.get("memory"), dict):
        # Pure Q&A: the transcript itself carries continuity. Blank the
        # learner-archive projections so the prompt stays lean and the
        # answer is not steered by plan/review machinery.
        minimal_memory = dict(coach_context["memory"])
        minimal_memory["current_focus"] = ""
        minimal_memory["recent_summary"] = ""
        minimal_memory["recent_wins"] = []
        minimal_memory["teaching_observations"] = []
        minimal_memory["memory_evidence"] = []
        minimal_memory["due_reviews"] = []
        minimal_memory["due_review_count"] = 0
        minimal_memory["review_rhythm"] = ""
        minimal_memory["active_thread"] = None
        coach_context["memory"] = minimal_memory
        coach_context["context_tier"] = "minimal"
    if resource_context:
        coach_context.update(resource_context)
    effective_focus = current_focus or summary
    if workspace_id and not minimal_context:
        teaching_knowledge_fragments = deps.runtime.resource_service.top_knowledge_fragments(
            workspace_id,
            max_fragments=6,
        )
        if (
            external_references is None
            or curated_background_references is None
            or recent_background_findings is None
        ):
            (
                resolved_external_references,
                resolved_curated_background_references,
                resolved_recent_background_findings,
            ) = deps.resolve_external_references(
                workspace_id=workspace_id,
                resource_context=coach_context,
                focus_area=effective_focus,
                limit=4,
                additional_curated_fragments=teaching_knowledge_fragments,
            )
            if external_references is None:
                external_references = resolved_external_references
            if curated_background_references is None:
                curated_background_references = resolved_curated_background_references
            if recent_background_findings is None:
                recent_background_findings = resolved_recent_background_findings
        if curated_background_references:
            coach_context["background_references"] = curated_background_references
        if recent_background_findings:
            coach_context["recent_background_findings"] = recent_background_findings
    if external_references and not minimal_context:
        coach_context["external_references"] = external_references
        background_reference_summary_parts: list[str] = []
        for item in external_references[:2]:
            if not isinstance(item, dict):
                continue
            summary_text = str(
                item.get("evidence_summary")
                or item.get("summary")
                or item.get("snippet")
                or ""
            ).strip()
            if not summary_text:
                continue
            source_text = str(item.get("source", "") or "").strip()
            if source_text:
                background_reference_summary_parts.append(f"{summary_text} ({source_text})")
            else:
                background_reference_summary_parts.append(summary_text)
        if background_reference_summary_parts:
            coach_context["background_reference_summary"] = "; ".join(background_reference_summary_parts)
        recalled_coaching_memories = deps.runtime.memory_service.recalled_coaching_memories(
            workspace_id,
            scenario=coach_context.get("scenario"),
            focus_area=effective_focus,
            query=" ".join(part for part in [summary, next_step, current_focus] if part).strip(),
            exclude_asset_ids=selected_teaching_asset_ids,
            limit=3,
        )
        if recalled_coaching_memories:
            coach_context["recalled_coaching_memories"] = recalled_coaching_memories
            coach_context["recalled_memory_summary"] = "; ".join(
                (
                    f"{item['title']}: {item['lesson']}"
                    if item.get("title") and item.get("lesson")
                    else str(item.get("lesson") or item.get("summary") or "").strip()
                )
                for item in recalled_coaching_memories[:2]
                if str(item.get("lesson") or item.get("summary") or "").strip()
            )
        teaching_assets = selected_teaching_assets
        if teaching_assets:
            selected_payload = [item.model_dump() for item in teaching_assets]
            selected_summary = "; ".join(
                f"{item.kind}: {item.summary or item.title}"
                for item in teaching_assets[:2]
                if (item.summary or item.title)
            )
            coach_context["selected_teaching_assets"] = selected_payload
            coach_context["selected_teaching_asset_ids"] = selected_teaching_asset_ids
            coach_context["teaching_assets"] = [item.model_dump() for item in teaching_assets]
            coach_context["teaching_asset_ids"] = selected_teaching_asset_ids
            coach_context["teaching_asset_summary"] = selected_summary
    accepted_recovery = accept_plan_runtime_resume_request(
        plan_runtime_recovery,
        recovered_status=snapshot.plan_runtime_status
        if isinstance(snapshot.plan_runtime_status, dict)
        else None,
    )
    if accepted_recovery:
        coach_context["plan_runtime_recovery"] = accepted_recovery
        recovered_step = str(accepted_recovery.get("current_step") or "").strip()
        recovered_blocker = str(accepted_recovery.get("blocked_reason") or "").strip()
        if recovered_step:
            coach_context["current_focus"] = recovered_step
        if recovered_blocker:
            coach_context["blocker"] = recovered_blocker
        coach_context["formal_plan_mutation"] = False
    if isinstance(message, str) and message.strip():
        coach_context["learner_message"] = message
    return apply_training_review_context(coach_context, memory, normalized_active_view)


def resolve_coach_turn(deps: CoachSupportDeps, 
    *,
    state,
    profile: UserProfile,
    request: TurnRequest | SessionMessageRequest,
    message: str,
    coaching_service: ProviderService,
    current_task: TaskSpec | None = None,
    current_plan: LearningPlan | None = None,
    current_evaluation=None,
    force_scenario: str | None = None,
    stream: bool = False,
) -> CoachTurnPayload:
    learner_signal = deps.infer_learner_signal(message, getattr(request, "current_file", None))
    requested_scenario = force_scenario or deps.infer_coaching_scenario(
        request,
        current_task=current_task,
        evaluation_summary=current_evaluation.summary if current_evaluation else None,
    )
    scenario = requested_scenario
    selected_resource_ids = deps.request_resource_ids(request)
    pedagogy_request = (
        request
        if isinstance(request, TurnRequest)
        else TurnRequest(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
            message=request.message,
            resource_ids=selected_resource_ids,
            resourceComposerIntent=request.resource_composer_intent,
            current_file=request.current_file,
            responseLanguage=request.response_language,
            answer_mode=request.answer_mode,
            intent="coach",
        )
    )
    state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
    state.snapshot.profile = profile
    completed_return = bool(
        current_evaluation is not None and current_evaluation.passed
        and completed_return_feedback(deps.runtime, state.workspace_id, request)
    )
    if completed_return and current_evaluation is not None and current_evaluation.passed:
        current_evaluation = current_evaluation.model_copy(update={"next_step": localized_text(
            "Verification, reflection and Return are complete. Review the returned evidence in Plan before deciding whether to adopt it.",
            "这张卡的验证、复盘和回流已完成。在学习页查看回流证据，再决定是否接纳到当前计划。",
            request.response_language,
        )})
        state.snapshot.evaluation = current_evaluation
    scenario = deps.inherit_active_thread_scenario_for_continuation(
        scenario,
        message=request.message,
        active_thread=state.snapshot.memory.active_thread,
    )
    resource_context = deps.compose_resource_context(
        state.workspace_id,
        selected_resource_ids,
        message=request.message,
        resource_composer_intent=request.resource_composer_intent,
    )
    if pedagogy_request.current_file is not None or resource_context:
        workspace_understanding = deps.runtime.pedagogy_service.build_workspace_understanding(
            request=pedagogy_request,
            memory_snapshot=state.snapshot.memory,
            resource_context=resource_context,
        )
        if workspace_understanding is not None:
            deps.runtime.memory_service.save_workspace_understanding(
                state.workspace_id,
                workspace_understanding,
            )
            state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
    pedagogy_learner_state_raw = deps.runtime.pedagogy_service.infer_learner_state(
        request=pedagogy_request,
        profile=profile,
        memory_snapshot=state.snapshot.memory,
    )
    modeled_learner_state = deps.model_learner_state(pedagogy_learner_state_raw)
    modeled_affect_state = deps.runtime.affect_service.infer_state(
        message=message,
        learner_state=modeled_learner_state or LearnerState(),
        memory_snapshot=state.snapshot.memory,
    )
    memory_workspace_payload = (
        state.snapshot.memory.workspace
        if isinstance(getattr(state.snapshot.memory, "workspace", None), dict)
        else {}
    )
    pedagogy_decision_raw = deps.runtime.pedagogy_service.decide_teaching(
        request=pedagogy_request,
        learner_state=pedagogy_learner_state_raw,
        profile=profile,
        memory_snapshot=state.snapshot.memory,
        affect_state=modeled_affect_state,
        skill_projection=(
            memory_workspace_payload.get("training_skill_projection")
            if isinstance(memory_workspace_payload, dict)
            else None
        ),
    )
    lowered_message = request.message.lower()
    first_user_turn = sum(
        1
        for item in state.snapshot.messages
        if str(getattr(item, "role", "") or "").strip().lower() == "user"
    ) == 1
    structured_onboarding_intake = first_user_turn and all(
        (
            any(
                token in lowered_message
                for token in (
                    "long-term goal",
                    "long term goal",
                    "career goal",
                    "\u957f\u671f\u76ee\u6807",
                    "\u804c\u4e1a\u76ee\u6807",
                )
            ),
            bool(
                re.search(
                    r"\b(?:right now\s+)?i(?:'m| am)\s+(?:an?\s+)?"
                    r"(?:beginner|junior|intermediate|senior|experienced|self-taught)\b",
                    lowered_message,
                )
                or re.search(
                    r"(?:\u76ee\u524d|\u73b0\u5728|\u6211\u662f).{0,8}"
                    r"(?:\u521d\u7ea7|\u4e2d\u7ea7|\u9ad8\u7ea7|\u6709\u7ecf\u9a8c)",
                    lowered_message,
                )
            ),
            bool(
                re.search(
                    r"\b\d+(?:\.\d+)?\s*(?:hours?|hrs?)\s*(?:per|a)\s+week\b",
                    lowered_message,
                )
                or re.search(
                    r"(?:\u6bcf\u5468.{0,8}\d+(?:\.\d+)?\s*\u5c0f\u65f6|"
                    r"\d+(?:\.\d+)?\s*\u5c0f\u65f6.{0,8}\u6bcf\u5468)",
                    lowered_message,
                )
            ),
            any(
                token in lowered_message
                for token in (
                    "guide me",
                    "coach me",
                    "help me learn",
                    "teach me step by step",
                    "\u5e26\u6211\u5b66",
                    "\u6307\u5bfc\u6211",
                    "\u4e00\u6b65\u4e00\u6b65\u5e26\u6211",
                )
            ),
        )
    )
    beginner_goal_opening = first_user_turn and all(
        (
            pedagogy_request.current_file is None,
            not resource_context,
            any(
                token in lowered_message
                for token in (
                    "complete beginner",
                    "total beginner",
                    "new to programming",
                    "no programming experience",
                    "never coded",
                    "zero experience",
                    "\u5b8c\u5168\u4e0d\u4f1a",
                    "\u96f6\u57fa\u7840",
                    "\u6ca1\u5b66\u8fc7\u7f16\u7a0b",
                    "\u6ca1\u6709\u7f16\u7a0b\u7ecf\u9a8c",
                    "\u4ece\u6ca1\u5199\u8fc7\u4ee3\u7801",
                    "\u65b0\u624b",
                    "\u521d\u5b66\u8005",
                )
            ),
            any(
                token in lowered_message
                for token in (
                    "i want to",
                    "i'd like to",
                    "want to learn",
                    "want to build",
                    "my goal",
                    "\u60f3\u5b66",
                    "\u60f3\u505a",
                    "\u60f3\u5728",
                    "\u76ee\u6807",
                    "\u5e0c\u671b",
                )
            ),
        )
    )
    preserve_requested_first_lane = requested_scenario in {
        "remote_workspace",
        "debug_loop",
        "function_guidance",
        "idea_implementation",
        "project_adaptation",
        "project_sourcing",
    }
    continuation_of_active_thread = (
        deps.message_keeps_existing_thread(request.message)
        and state.snapshot.memory.active_thread is not None
    )
    relationship_first_opening = (
        not continuation_of_active_thread
        and (
            structured_onboarding_intake
            or beginner_goal_opening
            or (
                not preserve_requested_first_lane
        and pedagogy_request.current_file is None
        and not resource_context
        and any(
            token in lowered_message
            for token in (
                "how do we start",
                "where should we start",
                "help me get started",
                "before we start",
                "want to practice with you",
                "coach me through",
                "不知道从哪里开始",
                "从哪里开始",
                "带我开始",
                "帮我开始",
                "\u600e\u4e48\u5f00\u59cb",
                "\u5148\u5e2e\u6211\u770b\u770b\u600e\u4e48\u5f00\u59cb",
                "\u4e00\u6b65\u4e00\u6b65\u5e26\u6211",
                "\u5148\u966a\u6211\u770b\u770b",
                "\u5148\u4e00\u8d77\u5b9a\u4e00\u4e2a",
            )
        )
            )
        )
    )
    if relationship_first_opening:
        onboarding_focus = deps.runtime.pedagogy_service._onboarding_focus(  # noqa: SLF001
            pedagogy_request,
            pedagogy_learner_state_raw,
            profile,
            state.snapshot.memory,
        )
        adaptive_bias = deps.runtime.pedagogy_service._adaptive_bias(state.snapshot.memory)  # noqa: SLF001
        (
            lesson_shape,
            exercise_shape,
            teaching_strategy,
            closing_move,
            artifact_priority,
        ) = deps.runtime.pedagogy_service._mode_playbook(  # noqa: SLF001
            mode="onboarding",
            scenario="guided",
            focus_area=onboarding_focus or getattr(pedagogy_learner_state_raw, "active_focus", ""),
            learner_state=pedagogy_learner_state_raw,
            memory_snapshot=state.snapshot.memory,
            adaptive_bias=adaptive_bias,
            decision_should_generate_exercise=False,
            decision_should_produce_plan_artifact=False,
        )
        reason_parts = [
            *list(getattr(pedagogy_decision_raw, "evidence", []) or []),
            "relationship_first_opening",
        ]
        override_payload = {
            "mode": "onboarding",
            "scenario": "guided",
            "focus_area": onboarding_focus,
            "reason": "; ".join(
                item for item in reason_parts if str(item or "").strip()
            ),
            "primary_goal": deps.runtime.pedagogy_service._build_primary_goal(  # noqa: SLF001
                "onboarding",
                onboarding_focus,
                getattr(pedagogy_learner_state_raw, "active_focus", ""),
            ),
            "lesson_shape": lesson_shape,
            "exercise_shape": exercise_shape,
            "teaching_strategy": teaching_strategy,
            "closing_move": closing_move,
            "artifact_priority": artifact_priority,
            "should_end_with_question": True,
            "should_generate_exercise": False,
            "should_reveal_code": False,
            "should_produce_plan_artifact": False,
            "should_trigger_deep_analysis": False,
            "should_focus_on_implementation_steps": False,
            "tone_profile": "steady",
            "evidence": reason_parts,
        }
        pedagogy_decision_raw = replace(pedagogy_decision_raw, **override_payload)
    if requested_scenario == "project_sourcing":
        scenario_override = {
            "mode": "project_sourcing",
            "scenario": "project_sourcing",
        }
        pedagogy_decision_raw = replace(pedagogy_decision_raw, **scenario_override)
    request_focus_area = request.focus_area if isinstance(request, TurnRequest) else None
    focus_area_hint = (
        str(pedagogy_decision_raw.focus_area or "").strip()
        or str(pedagogy_learner_state_raw.active_focus or "").strip()
        or str(state.snapshot.memory.current_focus or "").strip()
        or str(request_focus_area or "").strip()
        or str(message or "").strip()
    )
    context_tier = deps._resolve_context_tier(request)
    if context_tier == "minimal":
        # Pure Q&A: skip resource/knowledge retrieval entirely. The turn
        # answers from the model plus the recent conversation.
        resolved_external_references = None
        resolved_curated_background_references = None
        resolved_recent_background_findings = None
    else:
        (
            resolved_external_references,
            resolved_curated_background_references,
            resolved_recent_background_findings,
        ) = deps.resolve_external_references(
            workspace_id=state.workspace_id,
            resource_context=resource_context,
            focus_area=focus_area_hint,
            limit=4,
        )
    pedagogy_artifacts_raw = deps.runtime.pedagogy_service.build_artifacts(
        request=pedagogy_request,
        learner_state=pedagogy_learner_state_raw,
        decision=pedagogy_decision_raw,
        profile=profile,
        memory_snapshot=state.snapshot.memory,
        affect_state=modeled_affect_state,
        external_references=resolved_external_references,
    )
    modeled_teaching_decision = deps.model_teaching_decision(pedagogy_decision_raw)
    modeled_tone_decision = deps.runtime.affect_service.decide_tone(
        profile=profile,
        learner_state=modeled_learner_state or LearnerState(),
        teaching_decision=modeled_teaching_decision or TeachingDecision(),
        affect_state=modeled_affect_state,
    )
    pedagogy_payload = pedagogy_artifacts_raw.to_payload()
    modeled_adaptation_guide = deps.model_project_adaptation_guide(
        pedagogy_payload.get("project_adaptation_guide") or pedagogy_payload.get("adaptation_guide")
    )
    modeled_project_sources = deps.model_project_sources(pedagogy_payload.get("project_sources"))
    modeled_principle_notes = deps.model_principle_notes(
        pedagogy_payload.get("principle_notes") or pedagogy_payload.get("principle_note")
    )
    deps.apply_pedagogy_snapshot(
        snapshot=state.snapshot,
        learner_state=modeled_learner_state,
        teaching_decision=modeled_teaching_decision,
        affect_state=modeled_affect_state,
        tone_decision=modeled_tone_decision,
        implementation_guide=deps.model_implementation_guide(pedagogy_payload.get("implementation_guide")),
        project_ideas=deps.model_project_ideas(pedagogy_payload.get("project_ideas")),
        project_adaptation_guide=modeled_adaptation_guide,
        project_sources=modeled_project_sources,
        principle_notes=modeled_principle_notes,
        selected_teaching_assets=[
            TeachingKnowledgeAsset.model_validate(item)
            for item in pedagogy_payload.get("selected_teaching_assets", [])
            if isinstance(item, dict)
        ]
        if isinstance(pedagogy_payload.get("selected_teaching_assets"), list)
        else None,
        exercise_prompt=pedagogy_payload.get("exercise_prompt")
        if isinstance(pedagogy_payload.get("exercise_prompt"), dict)
        else None,
    )
    deps.runtime.memory_service.persist_turn_context_pressure(
        state.workspace_id,
        current_task=current_task or state.snapshot.current_task,
        affect_state=modeled_affect_state,
        learner_state=modeled_learner_state,
        teaching_decision=modeled_teaching_decision,
        tone_decision=modeled_tone_decision,
        adaptation_guide=modeled_adaptation_guide,
        project_sources=modeled_project_sources,
        principle_notes=modeled_principle_notes,
        coach_focus={
            "current_focus": getattr(state.snapshot.memory, "current_focus", "")
            if state.snapshot.memory
            else "",
            "next_step": getattr(state.snapshot.coaching_state, "next_step", "")
            if state.snapshot.coaching_state
            else "",
        },
        coach_turn=getattr(state.snapshot, "coach_turn", None),
        next_step_hint=getattr(state.snapshot, "next_step_hint", None),
        coaching_adaptation=(
            state.snapshot.memory.coaching_adaptation if state.snapshot.memory else None
        ),
    )
    # High urgency (affect) is persisted above; refresh so invent gates and
    # hint-only chips see task_urgency without waiting for weekly_hours/tight budget.
    state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
    if modeled_learner_state and modeled_learner_state.learner_signal:
        learner_signal = modeled_learner_state.learner_signal
    if deps.infer_learner_signal(message, getattr(request, "current_file", None)) == "blocked":
        learner_signal = "blocked"
    if modeled_teaching_decision:
        raw_scenario_value = getattr(
            pedagogy_decision_raw,
            "scenario",
            getattr(modeled_teaching_decision, "mode", ""),
        )
        if getattr(modeled_teaching_decision, "mode", "") == "onboarding":
            raw_scenario_value = "onboarding"
        scenario_alias_map = {
            "guided": "onboarding" if getattr(modeled_teaching_decision, "mode", "") == "onboarding" else "guided",
            "project_idea_mining": "project_idea",
            "project_sourcing": "project_sourcing",
            "principle_explanation": "principle",
            "review_reflection": "review",
        }
        mapped_scenario = scenario_alias_map.get(raw_scenario_value, raw_scenario_value)
        if mapped_scenario not in {
            "general",
            "onboarding",
            "idea_implementation",
            "project_idea",
            "project_adaptation",
            "project_sourcing",
            "principle",
            "remote_workspace",
            "debug_loop",
            "function_guidance",
            "review",
            "plan",
            "task",
            "next_task",
        }:
            mapped_scenario = "onboarding" if getattr(modeled_teaching_decision, "mode", "") == "onboarding" else scenario or "general"
        if (
            requested_scenario == "principle"
            and mapped_scenario in {"idea_implementation", "project_adaptation", "project_idea"}
            and pedagogy_request.current_file is None
            and resource_context
        ):
            mapped_scenario = "principle"
        scenario = force_scenario or deps.preserve_requested_domain_scenario(
            requested_scenario=requested_scenario,
            decided_scenario=mapped_scenario,
        )
    scenario = deps.inherit_active_thread_scenario_for_continuation(
        scenario,
        message=request.message,
        active_thread=state.snapshot.memory.active_thread,
    )
    if (
        (
            deps.should_remap_task_intent_without_live_plan(
                state.workspace_id,
                message=request.message,
                snapshot=state.snapshot,
                current_task=state.snapshot.current_task,
                current_plan=state.snapshot.plan,
            )
        )
        and scenario
        in {
            "plan",
            "task",
            "next_task",
            "idea_implementation",
            "project_adaptation",
            "project_idea",
            "project_sourcing",
        }
        and (
            not force_scenario
            or deps.closed_loop_return_blocks_task_mint(state.workspace_id)
            or not deps.runtime.provider_connection_verified(coaching_service)
        )
    ):
        # The gate controls artifacts/tasks; non-minting domain lanes (plan,
        # idea, project) stay as classified. TaskSpec-minting lanes are
        # different: without a live plan there is nothing to execute, so a
        # "task"/"next_task" coach turn would advertise a mint path that
        # /task/next and /task/specify fail-close. Coerce to the honest
        # general coaching lane.
        if scenario in {"task", "next_task"}:
            scenario = "general"
    deps.hydrate_snapshot(state.snapshot,
        response_language=request.response_language,
        answer_mode=request.answer_mode or profile.answer_policy,
        scenario=scenario,
        learner_signal=learner_signal,
        message=request.message,
        current_file=request.current_file,
        grounding_context=resource_context,
        active_view=request.active_view,
        session_workspace_id=state.workspace_id,
    )
    memory = state.snapshot.memory
    coach_context = deps.build_coach_context(
        state.snapshot,
        resource_context,
        response_language=request.response_language,
        message=request.message,
        active_view=request.active_view,
        current_file=request.current_file,
        external_references=resolved_external_references,
        curated_background_references=resolved_curated_background_references,
        recent_background_findings=resolved_recent_background_findings,
        plan_runtime_recovery=getattr(request, "plan_runtime_recovery", None),
        context_tier=context_tier,
    )
    if completed_return and current_evaluation is not None and current_evaluation.passed:
        coach_context["completed_training_return_feedback"] = True
        coach_context["next_step_hint"] = current_evaluation.next_step
    if isinstance(request, TurnRequest) and request.intent == "plan" and request.formal_plan_mutation:
        coach_context["formal_plan_mutation"] = True
        coach_context["allow_coach_only_tools"] = True
    _stamp_library_sandbox_work(coach_context, request)
    if deps.pressure_without_live_object_blocks_mint(
        state.workspace_id,
        snapshot=state.snapshot,
        current_task=current_task or state.snapshot.current_task,
        current_plan=current_plan or state.snapshot.plan,
        message=request.message,
    ):
        # High urgency / tight budget: ReAct tools stay hint-only.
        # Chat "create a card" is not the mint path; POST /plan/generate and
        # /training/generate-card remain the explicit leftover binders.
        coach_context["pressure_blocks_live_object_mint"] = True
    if deps.streak_without_live_object_blocks_mint(
        state.workspace_id,
        snapshot=state.snapshot,
        current_task=current_task or state.snapshot.current_task,
        current_plan=current_plan or state.snapshot.plan,
    ):
        # Consecutive fail/success without a live object: adapt pace only.
        # Fail-closed like evidence_controls — do not invent TaskSpec/card.
        coach_context["streak_blocks_live_object_mint"] = True
    if deps.live_formal_plan_for_explicit_task_next(state.workspace_id) is not None:
        # ReAct specify_task / next_task may mint only for this live identity.
        coach_context["live_formal_plan_for_task_mint"] = True
    if deps.closed_loop_return_blocks_task_mint(state.workspace_id):
        # Live plan + completed/verified Return: host/webview fail-closed mint chips.
        # Explicit POST /task/next and /task/specify remain the mint paths.
        coach_context["closed_loop_return_blocks_task_mint"] = True
    # Host/user attestation only — never trust model tool-arg self-attestation.
    # Fail-closed: Direct API resourceOrganizationConfirmed without a prior
    # organize_resources proposal for this workspace must not stamp.
    if getattr(request, "resource_organization_confirmed", False) is True:
        pending = getattr(deps.runtime, "resource_organization_pending", None)
        if isinstance(pending, dict) and state.workspace_id in pending:
            coach_context["resource_organization_confirmed"] = True
    suggested_actions = deps.honest_suggested_actions_without_live_object(
        deps.structured_suggested_actions(
            deps.coach_suggested_actions(request.response_language,
                scenario=scenario,
                snapshot=state.snapshot,
            ),
            response_language=request.response_language,
            scenario=scenario,
            focus_area=deps.stateful_focus_area(
                current_task,
                current_plan,
                current_evaluation,
                snapshot=state.snapshot,
            ),
        ),
        workspace_id=state.workspace_id,
        response_language=request.response_language,
        snapshot=state.snapshot,
        current_task=current_task,
        current_plan=current_plan,
        current_evaluation=current_evaluation,
        message=request.message,
        scenario=scenario,
    )
    artifacts = deps.build_coaching_artifacts(scenario=scenario,
        response_language=request.response_language,
        coaching_state=state.snapshot.coaching_state,
        memory=memory,
        message=request.message,
        task=current_task,
        plan=current_plan,
        evaluation=current_evaluation,
        snapshot=state.snapshot,
        grounding_context=resource_context,
        completed_return=completed_return,
        active_view=request.active_view,
    )
    if active_training_review(memory, deps.normalize_active_view_name(request.active_view)) is not None:
        suggested_actions = []
    return {
        "scenario": scenario,
        "learner_signal": learner_signal,
        "coach_context": coach_context,
        "suggested_actions": suggested_actions,
        "artifacts": artifacts,
        "coach_turn": deps.build_turn_summary(
            snapshot=state.snapshot,
            scenario=scenario,
            learner_signal=learner_signal,
            artifacts=artifacts,
            suggested_actions=suggested_actions,
            coach_context=coach_context,
            response_language=request.response_language,
        ),
        "stream": stream,
    }


def build_session_response(deps: CoachSupportDeps, 
    *,
    state,
    request: TurnRequest | SessionMessageRequest,
    reply_content: str,
    artifacts: dict[str, object],
    suggested_actions: list[dict[str, object]],
    scenario: str,
    learner_signal: str,
    coach_turn_data: dict[str, object] | None = None,
    response_snapshot: WorkbenchSnapshot | None = None,
    agent_meta: dict[str, object] | None = None,
    attachment_delivery: dict[str, object] | None = None,
) -> SessionMessageResponse:
    if isinstance(agent_meta, dict):
        agent_meta = {key: value for key, value in agent_meta.items() if value is not None}
    snapshot_for_response = response_snapshot if response_snapshot is not None else state.snapshot
    snapshot_for_response.snapshot_revision = deps.runtime.next_snapshot_revision(state.workspace_id)
    deps.repair_legacy_assistant_messages(snapshot_for_response, request.response_language)
    response_scenario = scenario
    fresh_lane_coach_turn = False
    if isinstance(coach_turn_data, dict):
        coach_turn_scenario = str(coach_turn_data.get("scenario") or "").strip()
        coach_context = coach_turn_data.get("coach_context")
        fresh_lane_coach_turn = (
            isinstance(coach_context, dict)
            and str(coach_context.get("history_mode") or "").strip().lower() == "fresh_lane"
        )
        if fresh_lane_coach_turn and coach_turn_scenario == "general":
            response_scenario = "general"
        elif coach_turn_scenario and coach_turn_scenario != "general" and response_scenario == "general":
            response_scenario = coach_turn_scenario
    if isinstance(agent_meta, dict):
        agent_scenario = str(agent_meta.get("scenario") or "").strip()
        if (
            not fresh_lane_coach_turn
            and agent_scenario
            and agent_scenario != "general"
            and response_scenario == "general"
        ):
            response_scenario = agent_scenario
        latest_user_message = ""
        for message in reversed(snapshot_for_response.messages):
            role = str(getattr(message, "role", "") or "").strip().lower()
            if role != "user":
                continue
            latest_user_message = str(getattr(message, "content", "") or "").strip()
            if latest_user_message:
                break
        short_continuation_request = latest_user_message in {
            "continue",
            "Continue",
            "\u7ee7\u7eed",
            "\u8bf7\u7ee7\u7eed",
            "\u7ee7\u7eed\u5427",
            "\u63a5\u7740",
            "\u4e0b\u4e00\u6b65",
        } or deps.message_requests_lane_continuation(latest_user_message)
        if (
            str(agent_meta.get("stop_reason") or "").strip() == "language_corruption"
            and short_continuation_request
        ):
            continuation_active_thread = None
            if isinstance(coach_turn_data, dict):
                coach_context = coach_turn_data.get("coach_context")
                if isinstance(coach_context, dict) and isinstance(coach_context.get("active_thread"), dict):
                    continuation_active_thread = coach_context.get("active_thread")
            continuation_scenario = response_scenario
            if continuation_scenario == "general":
                continuation_scenario = deps.active_thread_scenario_value(
                    continuation_active_thread or snapshot_for_response.memory.active_thread
                ) or response_scenario
            if continuation_scenario and continuation_scenario != "general":
                response_scenario = continuation_scenario
            current_next_step = deps.strip_visible_next_step_prefix(agent_meta.get("next_step") or "")
            repaired_next_step = current_next_step
            if looks_like_mojibake_text(current_next_step):
                repaired_next_step = ""
            if deps.continuation_step_needs_local_repair(current_next_step) or deps.generic_guided_review_fallback_needs_repair(current_next_step):
                repaired_next_step = deps.resolve_local_continuation_step(
                    snapshot=snapshot_for_response,
                    coach_turn=coach_turn_data if isinstance(coach_turn_data, dict) else {},
                    fallback_next_step=current_next_step,
                )
            if deps.continuation_step_needs_local_repair(repaired_next_step) or deps.generic_guided_review_fallback_needs_repair(repaired_next_step):
                repaired_next_step = deps.extract_lane_continuation_step(current_next_step)
            if deps.continuation_step_needs_local_repair(repaired_next_step) or deps.generic_guided_review_fallback_needs_repair(repaired_next_step):
                repaired_next_step = deps.local_continuation_step_for_scenario(
                    response_scenario,
                    request.response_language,
                )
            if repaired_next_step and repaired_next_step != current_next_step:
                repaired_summary = str(agent_meta.get("summary") or "").strip()
                repaired_blocker = str(agent_meta.get("blocker") or repaired_summary).strip()
                repaired_teaching_note = localized_text(
                    "Keep the same learning lane. When a short continuation is corrupted, resume from the saved thread locally and verify the next visible move.",
                    "\u7ee7\u7eed\u7559\u5728\u540c\u4e00\u6761\u5b66\u4e60\u4e3b\u7ebf\u91cc\u3002\u5f53\u77ed continuation \u88ab\u7834\u574f\u65f6\uff0c\u5148\u4ece\u5df2\u4fdd\u5b58\u7684 thread \u5728\u672c\u5730\u7eed\u4e0a\uff0c\u518d\u9a8c\u8bc1\u4e0b\u4e00\u4e2a\u53ef\u89c1\u52a8\u4f5c\u3002",
                    request.response_language,
                )
                repaired_resume_thread = localized_text(
                    f"Continue the saved coaching thread. Next: {repaired_next_step}",
                    f"\u7ee7\u7eed\u6cbf\u7740\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u63a8\u8fdb\u3002\u4e0b\u4e00\u6b65\uff1a{repaired_next_step}",
                    request.response_language,
                )
                agent_meta = dict(agent_meta)
                agent_meta["next_step"] = repaired_next_step
                agent_meta["resume_thread"] = repaired_resume_thread
                agent_meta["teaching_note"] = repaired_teaching_note
                if response_scenario and response_scenario != "general":
                    agent_meta["scenario"] = response_scenario
                reply_content = localized_text(
                    f"{repaired_summary}\n\nThe provider did not preserve this short continuation cleanly, so Trainer resumed the saved thread locally instead of repeating the provider setup blocker.\n\nNext step: {repaired_next_step}",
                    f"{repaired_summary}\n\nprovider \u6ca1\u6709\u7a33\u5b9a\u4fdd\u7559\u8fd9\u6761\u5f88\u77ed\u7684 continuation\uff0c\u6240\u4ee5 Trainer \u5148\u6309\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u5728\u672c\u5730\u7eed\u4e0a\uff0c\u4e0d\u518d\u91cd\u590d provider \u914d\u7f6e\u963b\u585e\u3002\n\n\u4e0b\u4e00\u6b65\uff1a{repaired_next_step}",
                    request.response_language,
                )
                if snapshot_for_response.coaching_state:
                    snapshot_for_response.coaching_state = snapshot_for_response.coaching_state.model_copy(
                        update={
                            "summary": repaired_summary,
                            "next_step": repaired_next_step,
                            "resume_thread": repaired_resume_thread,
                        }
                    )
                if isinstance(coach_turn_data, dict):
                    coach_turn_data = deps.merge_agent_finalize_into_coach_turn(
                        {
                            **coach_turn_data,
                            "scenario": response_scenario,
                        },
                        summary=repaired_summary,
                        next_step=repaired_next_step,
                        blocker=repaired_blocker,
                        resume_thread=repaired_resume_thread,
                        teaching_note=repaired_teaching_note,
                    )
    refreshed_coach_turn_data = coach_turn_data
    if isinstance(coach_turn_data, dict):
        original_coach_context = (
            coach_turn_data.get("coach_context")
            if isinstance(coach_turn_data.get("coach_context"), dict)
            else None
        )
        original_turn_summary = (
            coach_turn_data.get("coach_turn")
            if isinstance(coach_turn_data.get("coach_turn"), CoachTurnSummary)
            else None
        )
        requested_resource_ids = deps.request_resource_ids(request)
        refreshed_resource_context = deps.compose_resource_context(
            state.workspace_id,
            requested_resource_ids,
            message=request.message,
            resource_composer_intent=request.resource_composer_intent,
        )
        refreshed_coach_context = deps.build_coach_context(
            snapshot_for_response,
            refreshed_resource_context,
            message=request.message,
            active_view=request.active_view,
            current_file=getattr(request, "current_file", None),
            response_language=request.response_language,
            plan_runtime_recovery=getattr(request, "plan_runtime_recovery", None),
        )
        original_history_mode = (
            str(original_coach_context.get("history_mode") or "").strip().lower()
            if isinstance(original_coach_context, dict)
            else ""
        )
        if original_history_mode == "fresh_lane":
            refreshed_coach_context["history_mode"] = "fresh_lane"
            refreshed_coach_context["current_focus"] = (
                str(original_coach_context.get("current_focus") or "").strip()
                if isinstance(original_coach_context, dict)
                else ""
            )
            preserve_relationship_continuity = deps.should_preserve_relationship_continuity_for_turn(
                snapshot_for_response.memory,
                message=request.message,
                grounding_context=refreshed_resource_context,
                active_view=request.active_view,
            )
            refreshed_coach_context["memory_evidence"] = []
            refreshed_coach_context["recent_teaching_signals"] = []
            refreshed_coach_context["recent_wins"] = []
            refreshed_coach_context["teaching_observations"] = []
            if not preserve_relationship_continuity:
                refreshed_coach_context["continuity_summary"] = ""
            refreshed_coach_context["active_thread"] = None
            refreshed_memory_payload = deps.normalized_object_mapping(
                refreshed_coach_context.get("memory")
            )
            if refreshed_memory_payload is not None:
                refreshed_memory = refreshed_memory_payload
                refreshed_memory["current_focus"] = ""
                refreshed_memory["recent_summary"] = ""
                refreshed_memory["recent_wins"] = []
                refreshed_memory["teaching_observations"] = []
                refreshed_memory["memory_evidence"] = []
                refreshed_memory["active_thread"] = None
                if not deps.turn_keeps_review_signals(
                    response_scenario,
                    snapshot_for_response.teaching_decision,
                ):
                    refreshed_memory["due_reviews"] = []
                    refreshed_memory["due_review_count"] = 0
                    refreshed_memory["review_rhythm"] = ""
                refreshed_coach_context["memory"] = refreshed_memory
            if not deps.turn_keeps_review_signals(
                response_scenario,
                snapshot_for_response.teaching_decision,
            ):
                refreshed_coach_context["review_rhythm"] = ""
                refreshed_coach_context["review_queue_summary"] = ""
                refreshed_coach_context["due_reviews"] = []
                refreshed_coach_context["due_review_count"] = 0
        # Refresh rebuilds coach_context; keep mint-block stamps from resolve_coach_turn
        # (or re-evaluate) so /session/message + /turn (+ streams) still surface them.
        if (
            isinstance(original_coach_context, dict)
            and original_coach_context.get("pressure_blocks_live_object_mint") is True
        ) or deps.pressure_without_live_object_blocks_mint(
            state.workspace_id,
            snapshot=snapshot_for_response,
            current_task=snapshot_for_response.current_task,
            current_plan=snapshot_for_response.plan,
            message=getattr(request, "message", None),
        ):
            refreshed_coach_context["pressure_blocks_live_object_mint"] = True
        if (
            isinstance(original_coach_context, dict)
            and original_coach_context.get("streak_blocks_live_object_mint") is True
        ) or deps.streak_without_live_object_blocks_mint(
            state.workspace_id,
            snapshot=snapshot_for_response,
            current_task=snapshot_for_response.current_task,
            current_plan=snapshot_for_response.plan,
        ):
            refreshed_coach_context["streak_blocks_live_object_mint"] = True
        if (
            isinstance(original_coach_context, dict)
            and original_coach_context.get("live_formal_plan_for_task_mint") is True
        ) or deps.live_formal_plan_for_explicit_task_next(state.workspace_id) is not None:
            refreshed_coach_context["live_formal_plan_for_task_mint"] = True
        if (
            isinstance(original_coach_context, dict)
            and original_coach_context.get("closed_loop_return_blocks_task_mint") is True
        ) or deps.closed_loop_return_blocks_task_mint(state.workspace_id):
            refreshed_coach_context["closed_loop_return_blocks_task_mint"] = True
        refreshed_coach_turn_data = {
            "scenario": response_scenario,
            "learner_signal": learner_signal,
            "artifacts": artifacts,
            "suggested_actions": suggested_actions,
            "coach_context": refreshed_coach_context,
            "coach_turn": (
                original_turn_summary
                if original_turn_summary is not None
                else deps.build_turn_summary(
                snapshot=snapshot_for_response,
                scenario=response_scenario,
                learner_signal=learner_signal,
                artifacts=artifacts,
                suggested_actions=suggested_actions,
                coach_context=refreshed_coach_context,
                response_language=request.response_language,
                )
            ),
        }
    if isinstance(agent_meta, dict):
        refreshed_coach_turn_data = deps.merge_agent_finalize_into_coach_turn(
            refreshed_coach_turn_data,
            summary=agent_meta.get("summary"),
            next_step=agent_meta.get("next_step"),
            blocker=agent_meta.get("blocker"),
            resume_thread=agent_meta.get("resume_thread") or agent_meta.get("resumeThread"),
            decision=agent_meta.get("decision"),
            teaching_note=agent_meta.get("teaching_note") or agent_meta.get("teachingNote"),
            confidence=agent_meta.get("confidence"),
            evidence=agent_meta.get("evidence"),
        )
        normalized_agent_summary = str(agent_meta.get("summary") or "").strip()
        normalized_agent_next_step = deps.strip_visible_next_step_prefix(
            agent_meta.get("next_step") or ""
        )
        resume_thread = str(
            agent_meta.get("resume_thread") or agent_meta.get("resumeThread") or ""
        ).strip()
        if (
            normalized_agent_next_step
            and normalized_agent_summary
            and (not resume_thread or normalized_agent_next_step not in resume_thread)
        ):
            resume_thread = deps.build_resume_thread_text(
                normalized_agent_summary,
                normalized_agent_next_step,
                response_language=request.response_language,
            )
            agent_meta = dict(agent_meta)
            agent_meta["resume_thread"] = resume_thread
        if str(agent_meta.get("stop_reason") or "").strip() == "coach_finalize":
            if resume_thread and state.snapshot.coaching_state:
                state.snapshot.coaching_state = state.snapshot.coaching_state.model_copy(
                    update={"resume_thread": resume_thread}
                )
            if resume_thread and isinstance(refreshed_coach_turn_data, dict):
                coach_context = refreshed_coach_turn_data.get("coach_context")
                if isinstance(coach_context, dict):
                    coach_context["resume_thread"] = resume_thread
                refreshed_coach_turn_data = deps.merge_agent_finalize_into_coach_turn(
                    refreshed_coach_turn_data,
                    resume_thread=resume_thread,
                )
        if (
            str(agent_meta.get("stop_reason") or "").strip() == "empty_response"
            and agent_meta.get("local_sequence_fallback") is not True
        ):
            reply_content = deps.build_empty_response_visible_reply(
                summary=agent_meta.get("summary"),
                next_step=agent_meta.get("next_step"),
                response_language=request.response_language,
            )
    reply_content, refreshed_coach_turn_data, repaired_agent_meta, _guided_lane_repaired = (
        deps.apply_guided_lane_visible_fallback(
            reply=reply_content,
            scenario=response_scenario,
            learner_message=getattr(request, "message", None),
            response_language=request.response_language,
            coach_turn=refreshed_coach_turn_data,
            agent_meta=agent_meta,
        )
    )
    reply_content = deps.sanitize_visible_coach_reply_content(
        reply_content,
        request.response_language,
    )
    agent_meta = repaired_agent_meta or None
    # T-0027/T-0035/T-0048 repair — see repair_generic_finalize_next_step.
    refreshed_coach_turn_data = deps.repair_generic_finalize_next_step(
        reply_content,
        agent_meta,
        refreshed_coach_turn_data,
        response_language=request.response_language,
    )
    if (
        not deps.message_requests_explicit_explanation_or_example(getattr(request, "message", None))
        and str(response_scenario or "").strip().lower() in deps.GUIDED_VISIBLE_REPAIR_SCENARIOS
        and (
            deps.guided_lane_visible_reply_is_generic(reply_content)
            or deps.guided_lane_visible_reply_has_foreign_markers(
                reply_content,
                scenario=response_scenario,
            )
        )
    ):
        coach_context = (
            deps.normalized_object_mapping(refreshed_coach_turn_data.get("coach_context"))
            if isinstance(refreshed_coach_turn_data, dict)
            else None
        )
        stable_reply = deps.build_guided_lane_stable_visible_reply(
            scenario=response_scenario,
            response_language=request.response_language,
            coach_context=coach_context,
        )
        if stable_reply is not None:
            reply_content = stable_reply["reply"]
            stabilized_agent_meta = dict(agent_meta or {})
            stabilized_agent_meta["summary"] = stable_reply["summary"]
            stabilized_agent_meta["next_step"] = stable_reply["next_step"]
            stabilized_agent_meta["teaching_note"] = stable_reply["teaching_note"]
            stabilized_agent_meta["resume_thread"] = stable_reply["resume_thread"]
            stabilized_agent_meta["scenario"] = str(response_scenario or "").strip() or "general"
            stabilized_agent_meta["guided_lane_visible_repaired"] = True
            agent_meta = stabilized_agent_meta
            if isinstance(refreshed_coach_turn_data, dict):
                refreshed_coach_turn_data = deps.merge_agent_finalize_into_coach_turn(
                    {
                        **refreshed_coach_turn_data,
                        "scenario": str(response_scenario or "").strip() or "general",
                    },
                    summary=stable_reply["summary"],
                    next_step=stable_reply["next_step"],
                    blocker=stabilized_agent_meta.get("blocker"),
                    resume_thread=stable_reply["resume_thread"],
                    decision=stabilized_agent_meta.get("decision"),
                    teaching_note=stable_reply["teaching_note"],
                    confidence=stabilized_agent_meta.get("confidence"),
                    evidence=stabilized_agent_meta.get("evidence"),
                )
    plan_commit_verified = deps.formal_plan_commit_verified(
        state=state,
        request=request,
        agent_meta=agent_meta,
    )
    if deps.requires_formal_plan_commit(request) and not plan_commit_verified:
        reply_content = deps.formal_plan_commit_missing_reply(request.response_language)
        next_step = deps.formal_plan_commit_missing_next_step(request.response_language)
        blocker = localized_text(
            "The model did not complete the required save_formal_plan tool call, so no formal plan was committed.",
            "模型没有完成必须的 save_formal_plan 工具调用，因此没有正式计划被提交。",
            request.response_language,
        )
        agent_meta = {
            **(agent_meta or {}),
            "agentic": True,
            "formal_plan_commit": "missing",
            "stop_reason": "formal_plan_commit_missing",
            "summary": blocker,
            "next_step": next_step,
            "blocker": blocker,
        }
        refreshed_coach_turn_data = deps.merge_agent_finalize_into_coach_turn(
            refreshed_coach_turn_data,
            summary=blocker,
            next_step=next_step,
            blocker=blocker,
        )
    if isinstance(agent_meta, dict):
        deps.apply_agent_meta_to_coaching_state(
            snapshot_for_response,
            agent_meta,
            response_scenario=response_scenario,
        )
        if snapshot_for_response is not state.snapshot:
            deps.apply_agent_meta_to_coaching_state(
                state.snapshot,
                agent_meta,
                response_scenario=response_scenario,
            )
    repaired_memory_snapshot = deps.repair_guided_lane_memory_snapshot_for_response(
        snapshot_for_response.memory,
        scenario=response_scenario,
        response_language=request.response_language,
        learner_message=getattr(request, "message", None),
    )
    if repaired_memory_snapshot is not snapshot_for_response.memory:
        snapshot_for_response.memory = repaired_memory_snapshot
        if snapshot_for_response is not state.snapshot:
            state.snapshot.memory = deps.repair_guided_lane_memory_snapshot_for_response(
                state.snapshot.memory,
                scenario=response_scenario,
                response_language=request.response_language,
                learner_message=getattr(request, "message", None),
            )
    assistant_reply = ChatMessage(
        id=f"message-{uuid4().hex[:10]}",
        role="assistant",
        content=reply_content,
        timestamp=datetime.now(UTC),
        metadata=deps.build_assistant_metadata(
            request,
            artifacts,
            snapshot_for_response,
            snapshot_for_response.coaching_state.summary if snapshot_for_response.coaching_state else None,
            refreshed_coach_turn_data,
            agent_meta,
            attachment_delivery,
        ),
    )
    state.snapshot.messages.append(assistant_reply)
    # Make the matching session durable before its replay-only trace is committed.
    deps.runtime.save_session_state(state.session_id)
    if isinstance(agent_meta, dict) and agent_meta.get("agentic") is True:
        checkpoint = deps.runtime.record_agent_turn_checkpoint(
            state=state,
            request=request,
            assistant_reply=assistant_reply,
            agent_meta=agent_meta,
            coach_turn_data=refreshed_coach_turn_data,
        )
        agent_meta = dict(agent_meta)
        agent_meta["checkpoint_id"] = str(checkpoint.get("checkpoint_id") or "")
        recovery = checkpoint.get("recovery")
        agent_meta["recovery_available"] = bool(
            recovery.get("recovery_available") if isinstance(recovery, dict) else False
        )
        assistant_reply.metadata["agent_checkpoint"] = {
            "checkpoint_id": agent_meta["checkpoint_id"],
            "recovery_available": agent_meta["recovery_available"],
        }
    deps.runtime.memory_service.record_session_message(
        state.session_id,
        f"assistant: {assistant_reply.content}",
        workspace_id=state.workspace_id,
    )
    deps.update_snapshot_plan_from_turn(
        state=state,
        reply_content=reply_content,
        coach_turn=refreshed_coach_turn_data,
        allow_formal_plan_mutation=bool(
            deps.requires_formal_plan_commit(request) and plan_commit_verified
        ),
    )
    state.snapshot.plan_runtime_status = deps.attach_plan_runtime_status(
        workspace_id=state.workspace_id,
        snapshot=state.snapshot,
        response_language=request.response_language,
        profile=state.snapshot.profile,
        coach_turn=refreshed_coach_turn_data,
        agent_meta=agent_meta,
    )
    if snapshot_for_response is state.snapshot:
        response_payload_snapshot = state.snapshot.model_copy(deep=True)
    else:
        response_payload_snapshot = snapshot_for_response.model_copy(deep=True)
        response_payload_snapshot.messages.append(assistant_reply)
    response_payload_snapshot.plan_runtime_status = deps.attach_plan_runtime_status(
        workspace_id=state.workspace_id,
        snapshot=response_payload_snapshot,
        response_language=request.response_language,
        profile=response_payload_snapshot.profile,
        coach_turn=refreshed_coach_turn_data,
        agent_meta=agent_meta,
    )
    response_payload_snapshot.memory = deps.repair_guided_lane_memory_snapshot_for_response(
        response_payload_snapshot.memory,
        scenario=response_scenario,
        response_language=request.response_language,
        learner_message=getattr(request, "message", None),
    )
    if snapshot_for_response is not state.snapshot:
        response_payload_snapshot.memory = response_payload_snapshot.memory.model_copy(
            update={
                "due_reviews": [],
                "due_review_count": 0,
            }
        )
        response_payload_snapshot.review_queue_summary = deps.summarize_review_queue(
            [],
            request.response_language,
        )
        response_payload_snapshot.next_review_due = None
    response_payload_snapshot.memory = deps.repair_guided_lane_memory_snapshot_for_response(
        response_payload_snapshot.memory,
        scenario=response_scenario,
        response_language=request.response_language,
        learner_message=getattr(request, "message", None),
    )
    if response_payload_snapshot.coaching_state is not None:
        aligned_coaching_state_payload = deps.language_aligned_coaching_state_payload(
            response_payload_snapshot.coaching_state.model_dump(),
            request.response_language,
        )
        if isinstance(aligned_coaching_state_payload, dict):
            response_payload_snapshot.coaching_state = type(
                response_payload_snapshot.coaching_state
            ).model_validate(aligned_coaching_state_payload)
    deps.runtime.save_session_state(state.session_id)
    raw_response_coach_turn = (
        refreshed_coach_turn_data.get("coach_turn")
        if isinstance(refreshed_coach_turn_data, dict)
        else None
    )
    response_coach_context = (
        deps.normalized_object_mapping(refreshed_coach_turn_data.get("coach_context"))
        if isinstance(refreshed_coach_turn_data, dict)
        else None
    )
    if isinstance(raw_response_coach_turn, CoachTurnSummary):
        response_coach_turn = raw_response_coach_turn
    else:
        response_coach_turn = deps.build_turn_summary(
            snapshot=response_payload_snapshot,
            scenario=response_scenario,
            learner_signal=learner_signal,
            artifacts=artifacts,
            suggested_actions=suggested_actions,
            coach_context=response_coach_context,
            response_language=request.response_language,
        )
    if isinstance(agent_meta, dict):
        raw_agent_evidence = agent_meta.get("evidence")
        agent_turn_update = {
            key: value
            for key, value in {
                "summary": str(agent_meta.get("summary") or "").strip(),
                "next_step": deps.strip_visible_next_step_prefix(agent_meta.get("next_step") or ""),
                "resume_thread": str(
                    agent_meta.get("resume_thread") or agent_meta.get("resumeThread") or ""
                ).strip(),
                "decision": str(agent_meta.get("decision") or "").strip(),
                "blocker": str(agent_meta.get("blocker") or "").strip(),
                "teaching_note": str(
                    agent_meta.get("teaching_note") or agent_meta.get("teachingNote") or ""
                ).strip(),
                "confidence": str(agent_meta.get("confidence") or "").strip(),
                "evidence": [
                    str(item).strip()
                    for item in raw_agent_evidence
                    if str(item).strip()
                ]
                if isinstance(raw_agent_evidence, list)
                else [],
            }.items()
            if value
        }
        response_coach_turn = response_coach_turn.model_copy(update=agent_turn_update)
    if (
        isinstance(response_coach_context, dict)
        and response_coach_context.get("pressure_blocks_live_object_mint") is True
    ):
        # Non-agent paths pass agent_meta=None; still stamp so host adapter can camelCase.
        agent_meta = dict(agent_meta) if isinstance(agent_meta, dict) else {"agentic": False}
        agent_meta["pressure_blocks_live_object_mint"] = True
    if (
        isinstance(response_coach_context, dict)
        and response_coach_context.get("streak_blocks_live_object_mint") is True
    ):
        agent_meta = dict(agent_meta) if isinstance(agent_meta, dict) else {"agentic": False}
        agent_meta["streak_blocks_live_object_mint"] = True
    if (
        isinstance(response_coach_context, dict)
        and response_coach_context.get("closed_loop_return_blocks_task_mint") is True
    ):
        agent_meta = dict(agent_meta) if isinstance(agent_meta, dict) else {"agentic": False}
        agent_meta["closed_loop_return_blocks_task_mint"] = True
    suggested_actions = deps.honest_suggested_actions_without_live_object(
        suggested_actions,
        workspace_id=state.workspace_id,
        response_language=request.response_language,
        snapshot=snapshot_for_response,
        current_task=snapshot_for_response.current_task,
        current_plan=snapshot_for_response.plan,
        current_evaluation=snapshot_for_response.evaluation,
        message=getattr(request, "message", None),
        scenario=str(response_scenario or "general"),
    )
    response_suggested_actions = [
        SuggestedAction.model_validate(action) for action in suggested_actions
    ]
    response_cached_grounding_decision = deps.grounding_decision_from_payload(coach_turn_data)
    if response_cached_grounding_decision is not None:
        # Consume the per-turn decision resolved before persistence — the
        # response must never re-evaluate the turn (DESIGN.md §2.3).
        response_coach_turn = deps.grounding_response_coach_turn(
            coach_turn=response_coach_turn,
            decision=response_cached_grounding_decision,
        )
    else:
        # Legacy path: a caller that never ran the resolve step still gets
        # the synchronous gate (kept for compatibility, not for wire flows).
        response_coach_turn = deps.apply_next_step_grounding_policy(
            coach_turn=response_coach_turn,
            reply_content=reply_content,
            request=request,
            agent_meta=agent_meta,
            coach_turn_data=coach_turn_data,
            history_text=deps.turn_history_text(snapshot_for_response),
        )
    response_agent_meta = AgentMeta.model_validate(agent_meta) if isinstance(agent_meta, dict) else None
    return SessionMessageResponse(
        session_id=state.session_id,
        reply=assistant_reply,
        snapshot=response_payload_snapshot,
        suggested_actions=response_suggested_actions,
        artifacts=artifacts,
        coach_turn=response_coach_turn,
        agent_meta=response_agent_meta,
        agent=response_agent_meta,
    )


async def execute_turn(deps: CoachSupportDeps, 
    request: TurnRequest,
    payload: dict,
    *,
    stream: bool = False,
    stream_id: str | None = None,
) -> tuple[object, object, object]:
    workspace_id = deps.current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
    state = deps.runtime.ensure_session(request.session_id, workspace_id=workspace_id)
    profile = deps.resolved_profile(state.workspace_id)
    frozen_formal_plan_mutation_requested = bool(
        request.intent == "plan"
        and request.formal_plan_mutation
        and deps.leftover_frozen_blocks_turn_generation(state.workspace_id)
    )
    raw_requested_answer_mode = str(
        payload.get("answer_mode") or payload.get("answerMode") or ""
    ).strip()
    saved_answer_mode = str(deps.workspace_preferences(workspace_id).get("answer_mode") or "").strip()
    request = deps.request_with_workspace_defaults(
        request,
        workspace_id=workspace_id,
        profile=profile,
    )
    profile = deps.profile_with_teaching_style(profile, request.teaching_style)
    coaching_service = deps.build_coaching_service(payload)
    use_agent_loop = _resolve_agent_loop_enabled(
        request, coaching_service, stream=stream, payload=payload
    )
    deps.ensure_coach_provider_ready(
        coaching_service,
        response_language=request.response_language,
    )
    provider_live_usable = deps.provider_is_live_usable(coaching_service, payload)
    if provider_live_usable:
        deps.ensure_agent_tools_ready(request, coaching_service)
    attachments_payload = [a.model_dump() for a in request.attachments]
    attachment_delivery = deps.describe_request_attachment_delivery(
        request,
        coaching_service,
        use_agent_loop=use_agent_loop,
    )

    user_message = ChatMessage(
        id=f"message-{uuid4().hex[:10]}",
        role="user",
        content=request.message,
        timestamp=datetime.now(UTC),
        metadata=deps.build_user_message_metadata(
            request,
            profile,
            attachment_delivery,
            stream_id=stream_id,
            stream_state="in_progress" if stream_id else None,
        ),
    )
    state.snapshot.messages.append(user_message)
    state.snapshot.profile = profile
    if stream:
        deps.runtime.save_session_state(state.session_id)

    scenario = deps.infer_coaching_scenario(request)
    suggested_actions = deps.honest_suggested_actions_without_live_object(
        deps.structured_suggested_actions(
            deps.coach_suggested_actions(request.response_language,
                scenario=scenario,
                snapshot=state.snapshot,
            ),
            response_language=request.response_language,
            scenario=scenario,
            focus_area=deps.stateful_focus_area(
                state.snapshot.current_task,
                state.snapshot.plan,
                state.snapshot.evaluation,
                snapshot=state.snapshot,
            ),
        ),
        workspace_id=workspace_id,
        response_language=request.response_language,
        snapshot=state.snapshot,
        current_task=state.snapshot.current_task,
        current_plan=state.snapshot.plan,
        current_evaluation=state.snapshot.evaluation,
        message=request.message,
        scenario=scenario,
    )
    artifacts: dict[str, object] = {}
    assistant_content = ""
    learner_signal = deps.infer_learner_signal(request.message, getattr(request, "current_file", None))
    agent_meta: dict[str, object] = {}
    language_corruption_detected = False
    provider_failure_detected = False

    if request.intent == "coach" and provider_live_usable:
        if stream:
            return state, coaching_service, user_message
        deps.safe_activate_training_card_from_coach_request(
            workspace_id=state.workspace_id,
            snapshot=state.snapshot,
            message=request.message,
            current_file=request.current_file,
            response_language=request.response_language,
            provider_service_override=coaching_service,
        )
        state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.profile = profile
        coach_turn: CoachTurnPayload = deps.resolve_coach_turn(
            state=state,
            profile=profile,
            request=request,
            message=request.message,
            coaching_service=coaching_service,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
            current_evaluation=state.snapshot.evaluation,
        )
        scenario = str(coach_turn.get("scenario") or "general")
        if deps.guarantee_guided_learn_first_training_card(
            workspace_id=state.workspace_id,
            scenario=str(coach_turn["scenario"] or ""),
            message=request.message,
            current_file=request.current_file,
            response_language=request.response_language,
            active_thread=state.snapshot.memory.active_thread,
            requested_answer_mode=raw_requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        ):
            state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
        scenario = str(coach_turn["scenario"])
        learner_signal = str(coach_turn["learner_signal"])
        if deps.infer_learner_signal(request.message, getattr(request, "current_file", None)) == "blocked":
            learner_signal = "blocked"
        artifacts = dict(coach_turn["artifacts"])
        suggested_actions = list(coach_turn["suggested_actions"])
        if not provider_live_usable:
            suggested_actions = deps.honest_suggested_actions_without_usable_provider(
                suggested_actions,
                response_language=request.response_language,
                snapshot=state.snapshot,
                current_task=state.snapshot.current_task,
                current_plan=state.snapshot.plan,
                current_evaluation=state.snapshot.evaluation,
            )
        guided_training_prefers_local_reply = deps.should_bypass_agent_loop_for_guided_training(
            workspace_id=state.workspace_id,
            scenario=scenario,
            message=request.message,
            active_view=request.active_view,
            requested_answer_mode=raw_requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        )
        guided_training_local_reply = (
            deps.build_guided_training_visible_fallback(
                workspace_id=state.workspace_id,
                response_language=request.response_language,
            )
            if guided_training_prefers_local_reply
            else None
        )
        preflight_language_probe = deps.detect_provider_language_corruption(
            coaching_service,
            message=request.message,
            response_language=request.response_language,
            coach_context=dict(coach_turn["coach_context"]),
        )
        if preflight_language_probe is not None:
            language_corruption_detected = True
            coach_turn = deps.extract_coach_turn_payload(
                deps.isolate_preflight_language_corruption_turn(
                    deps.coach_turn_mapping(coach_turn),
                    message=request.message,
                    current_file=request.current_file.model_dump() if request.current_file else None,
                )
            )
            assistant_content, updated_coach_turn, agent_meta = deps.apply_language_corruption_override(
                coaching_service=coaching_service,
                snapshot=state.snapshot,
                coach_turn=deps.coach_turn_mapping(coach_turn),
                message=request.message,
                response_language=request.response_language,
                allow_guided_recovery=False,
            )
            coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
            deps.ensure_explicit_training_card_after_language_block(
                state=state,
                message=request.message,
                current_file=request.current_file,
                response_language=request.response_language,
                fallback_scenario=str(coach_turn.get("scenario") or scenario),
                force_training_card=(
                    deps.auto_preference_requests_training_card(
                        request.message,
                        requested_scenario=str(coach_turn.get("scenario") or scenario),
                        requested_answer_mode=raw_requested_answer_mode,
                        saved_answer_mode=saved_answer_mode,
                        profile=profile,
                    )
                    or deps.auto_lane_learn_first_force_training_card(
                        request.message,
                        requested_scenario=str(coach_turn.get("scenario") or scenario),
                        requested_answer_mode=raw_requested_answer_mode,
                        saved_answer_mode=saved_answer_mode,
                        profile=profile,
                    )
            ),
            provider_service_override=coaching_service,
        )
            scenario = str(coach_turn.get("scenario") or scenario)
            agent_meta["scenario"] = scenario
        else:
            if guided_training_local_reply is not None:
                assistant_content, updated_coach_turn, agent_meta = deps.apply_guided_training_visible_fallback(
                    coach_turn=deps.coach_turn_mapping(coach_turn),
                    fallback=guided_training_local_reply,
                )
                coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
            elif use_agent_loop and not guided_training_prefers_local_reply:
                agent_context = dict(coach_turn["coach_context"])
                agent_context["__runtime__"] = deps.runtime
                agent_context["workspace_id"] = workspace_id
                agent_context["session_id"] = state.session_id
                _stamp_library_sandbox_work(agent_context, request, payload)
                agent_outcome = await coaching_service.coaching_reply_agentic(
                    profile,
                    request.message,
                    request.current_file.model_dump() if request.current_file else None,
                    response_language=request.response_language,
                    answer_mode=request.answer_mode,
                    coach_context=agent_context,
                    attachments=attachments_payload,
                    protocol=getattr(coaching_service._config, "protocol", None) if coaching_service._config else None,
                    history=deps.build_conversation_history(
                        state.snapshot.messages,
                        drop_latest_user=True,
                    ),
                )
                assistant_content = str(agent_outcome.get("content") or "").strip()
                agent_resume_thread = str(agent_outcome.get("resume_thread") or "").strip()
                if not agent_resume_thread:
                    agent_resume_thread = deps.build_resume_thread_text(
                        str(agent_outcome.get("summary") or "").strip(),
                        str(agent_outcome.get("next_step") or "").strip(),
                        response_language=request.response_language,
                    )
                agent_meta = {
                    "stop_reason": agent_outcome.get("stop_reason"),
                    "summary": agent_outcome.get("summary"),
                    "next_step": agent_outcome.get("next_step"),
                    "decision": agent_outcome.get("decision"),
                    "blocker": agent_outcome.get("blocker"),
                    "teaching_note": agent_outcome.get("teaching_note"),
                    "resume_thread": agent_resume_thread,
                    "confidence": agent_outcome.get("confidence"),
                    "evidence": agent_outcome.get("evidence"),
                    "steps": agent_outcome.get("steps", []),
                    "tool_events": agent_outcome.get("tool_events", []),
                    "fell_back": bool(agent_outcome.get("fell_back")),
                    "recovered_stop_reason": agent_outcome.get("recovered_stop_reason"),
                    "agentic": True,
                }
                deps.apply_attachment_delivery_metadata(agent_meta, agent_outcome)
                original_agent_stop_reason = str(agent_outcome.get("stop_reason") or "").strip()
                local_sequence_fallback = deps.build_local_sequence_visible_fallback(
                    coach_context=dict(coach_turn["coach_context"]),
                    response_language=request.response_language,
                )
                force_local_sequence = bool(
                    local_sequence_fallback is not None
                    and (
                        original_agent_stop_reason == "empty_response"
                        or not deps.reply_explicitly_lists_prepared_sequence(
                            assistant_content,
                            coach_context=dict(coach_turn["coach_context"]),
                        )
                    )
                )
                if force_local_sequence and local_sequence_fallback is not None:
                    assistant_content = local_sequence_fallback["reply"]
                    coaching_service.clear_last_reply_override()
                    agent_meta["summary"] = (
                        agent_meta.get("summary") or local_sequence_fallback["summary"]
                    )
                    agent_meta["next_step"] = (
                        agent_meta.get("next_step") or local_sequence_fallback["next_step"]
                    )
                    agent_meta["teaching_note"] = (
                        agent_meta.get("teaching_note") or local_sequence_fallback["teaching_note"]
                    )
                    if not str(agent_meta.get("resume_thread") or "").strip():
                        agent_meta["resume_thread"] = local_sequence_fallback["resume_thread"]
                    if original_agent_stop_reason == "empty_response":
                        agent_meta["fell_back"] = True
                        agent_meta["recovered_stop_reason"] = original_agent_stop_reason
                        agent_meta["stop_reason"] = "completed"
                    else:
                        agent_meta["grounded_sequence_enforced"] = True
                    agent_meta["local_sequence_fallback"] = True
                elif not assistant_content:
                    if local_sequence_fallback is None:
                        assistant_content = await coaching_service.coaching_reply(
                            profile,
                            request.message,
                            request.current_file.model_dump() if request.current_file else None,
                            response_language=request.response_language,
                            answer_mode=request.answer_mode,
                            coach_context=dict(coach_turn["coach_context"]),
                            history=deps.build_conversation_history(
                                state.snapshot.messages,
                                drop_latest_user=True,
                            ),
                        )
                    else:
                        assistant_content = local_sequence_fallback["reply"]
                        coaching_service.clear_last_reply_override()
                        agent_meta["summary"] = (
                            agent_meta.get("summary") or local_sequence_fallback["summary"]
                        )
                        agent_meta["next_step"] = (
                            agent_meta.get("next_step") or local_sequence_fallback["next_step"]
                        )
                        agent_meta["teaching_note"] = (
                            agent_meta.get("teaching_note") or local_sequence_fallback["teaching_note"]
                        )
                        if not str(agent_meta.get("resume_thread") or "").strip():
                            agent_meta["resume_thread"] = local_sequence_fallback["resume_thread"]
                    agent_meta["fell_back"] = True
                    if original_agent_stop_reason == "empty_response":
                        agent_meta["recovered_stop_reason"] = original_agent_stop_reason
                        agent_meta["stop_reason"] = "completed"
                    agent_meta["local_sequence_fallback"] = local_sequence_fallback is not None
                updated_coach_turn = deps.merge_agent_finalize_into_coach_turn(
                    deps.coach_turn_mapping(coach_turn),
                    summary=agent_outcome.get("summary")
                    or (local_sequence_fallback or {}).get("summary"),
                    next_step=agent_outcome.get("next_step")
                    or (local_sequence_fallback or {}).get("next_step"),
                    blocker=agent_outcome.get("blocker"),
                    resume_thread=agent_resume_thread
                    or (local_sequence_fallback or {}).get("resume_thread"),
                    decision=agent_outcome.get("decision"),
                    teaching_note=agent_outcome.get("teaching_note")
                    or (local_sequence_fallback or {}).get("teaching_note"),
                    confidence=agent_outcome.get("confidence"),
                    evidence=agent_outcome.get("evidence"),
                )
                coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
            else:
                assistant_content = await coaching_service.coaching_reply(
                    profile,
                    request.message,
                    request.current_file.model_dump() if request.current_file else None,
                    response_language=request.response_language,
                    answer_mode=request.answer_mode,
                    coach_context=dict(coach_turn["coach_context"]),
                    history=deps.build_conversation_history(
                        state.snapshot.messages,
                        drop_latest_user=True,
                    ),
                )
            provider_empty_reply_override = deps.consume_provider_empty_reply_override(
                coaching_service=coaching_service,
                snapshot=state.snapshot,
                coach_turn=deps.coach_turn_mapping(coach_turn),
                response_language=request.response_language,
                assistant_content=assistant_content,
            )
            if provider_empty_reply_override is not None:
                provider_failure_detected = True
                assistant_content, updated_coach_turn, override_meta = provider_empty_reply_override
                coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
                agent_meta.update(override_meta)
            else:
                provider_failure_override = deps.consume_provider_reply_failure_override(
                    coaching_service=coaching_service,
                    snapshot=state.snapshot,
                    coach_turn=deps.coach_turn_mapping(coach_turn),
                    message=request.message,
                    response_language=request.response_language,
                    workspace_id=state.workspace_id,
                )
                if provider_failure_override is not None:
                    provider_failure_detected = True
                    assistant_content, updated_coach_turn, override_meta = provider_failure_override
                    coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
                    agent_meta.update(override_meta)
                elif not language_corruption_detected and coaching_service.detect_language_corruption(
                    message=request.message,
                    reply=assistant_content,
                    response_language=request.response_language,
                ):
                    language_corruption_detected = True
                    assistant_content, updated_coach_turn, override_meta = deps.apply_language_corruption_override(
                        coaching_service=coaching_service,
                        snapshot=state.snapshot,
                        coach_turn=deps.coach_turn_mapping(coach_turn),
                        message=request.message,
                        response_language=request.response_language,
                        reply_corruption=True,
                    )
                    coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
                    deps.ensure_explicit_training_card_after_language_block(
                        state=state,
                        message=request.message,
                        current_file=request.current_file,
                        response_language=request.response_language,
                        fallback_scenario=str(coach_turn.get("scenario") or scenario),
                        force_training_card=(
                            deps.auto_preference_requests_training_card(
                                request.message,
                                requested_scenario=str(coach_turn.get("scenario") or scenario),
                                requested_answer_mode=raw_requested_answer_mode,
                                saved_answer_mode=saved_answer_mode,
                                profile=profile,
                            )
                            or deps.auto_lane_learn_first_force_training_card(
                                request.message,
                                requested_scenario=str(coach_turn.get("scenario") or scenario),
                                requested_answer_mode=raw_requested_answer_mode,
                                saved_answer_mode=saved_answer_mode,
                                profile=profile,
                            )
                        ),
                        provider_service_override=coaching_service,
                    )
                    scenario = str(coach_turn.get("scenario") or scenario)
                    agent_meta.update(override_meta)
            if not provider_failure_detected:
                resource_contract_fallback = None
                if deps.grounded_resource_contract_needs_repair(
                    assistant_content,
                    coach_context=dict(coach_turn["coach_context"]),
                ):
                    resource_contract_fallback = deps.build_grounded_resource_contract_visible_fallback(
                        workspace_id=workspace_id,
                        coach_context=dict(coach_turn["coach_context"]),
                        agent_meta=agent_meta,
                        response_language=request.response_language,
                    )
                if resource_contract_fallback is not None:
                    assistant_content = resource_contract_fallback["reply"]
                    agent_meta["summary"] = resource_contract_fallback["summary"]
                    agent_meta["next_step"] = resource_contract_fallback["next_step"]
                    agent_meta["teaching_note"] = resource_contract_fallback["teaching_note"]
                    agent_meta["resume_thread"] = resource_contract_fallback["resume_thread"]
                    agent_meta["grounded_resource_contract_repaired"] = True
                    agent_meta["scenario"] = str(coach_turn.get("scenario") or scenario)
                    updated_coach_turn = deps.merge_agent_finalize_into_coach_turn(
                        deps.coach_turn_mapping(coach_turn),
                        summary=resource_contract_fallback["summary"],
                        next_step=resource_contract_fallback["next_step"],
                        blocker=agent_meta.get("blocker"),
                        resume_thread=resource_contract_fallback["resume_thread"],
                        decision=agent_meta.get("decision"),
                        teaching_note=resource_contract_fallback["teaching_note"],
                        confidence=agent_meta.get("confidence"),
                        evidence=agent_meta.get("evidence"),
                    )
                    coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
                assistant_content, updated_coach_turn, agent_meta, _guided_lane_repaired = (
                    deps.apply_guided_lane_visible_fallback(
                        reply=assistant_content,
                        scenario=str(coach_turn.get("scenario") or scenario),
                        learner_message=request.message,
                        response_language=request.response_language,
                        coach_turn=deps.coach_turn_mapping(coach_turn),
                        agent_meta=agent_meta,
                    )
                )
                coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
                deps.ensure_explicit_training_card_after_coach_reply(
                    state=state,
                    message=request.message,
                    current_file=request.current_file,
                    response_language=request.response_language,
                    fallback_scenario=str(coach_turn.get("scenario") or scenario),
                    force_training_card=deps.auto_preference_requests_training_card(
                        request.message,
                        requested_scenario=str(coach_turn.get("scenario") or scenario),
                        requested_answer_mode=raw_requested_answer_mode,
                        saved_answer_mode=saved_answer_mode,
                        profile=profile,
                    )
                    or deps.auto_lane_learn_first_force_training_card(
                        request.message,
                        requested_scenario=str(coach_turn.get("scenario") or scenario),
                        requested_answer_mode=raw_requested_answer_mode,
                        saved_answer_mode=saved_answer_mode,
                        profile=profile,
                    ),
                    provider_service_override=coaching_service,
                )
    elif request.intent == "coach":
        # Remapped task/next_task (no live plan) still uses task honesty copy so
        # the learner hears "did not invent a task" rather than bare coach failure.
        raw_intent = str(payload.get("intent") or "").strip()
        unusable_kind: Literal["task", "plan", "coach"] = (
            "task" if raw_intent in {"task", "next_task"} else "coach"
        )
        if scenario == "general":
            scenario = infer_message_coaching_scenario(
                request.message,
                deps.normalize_current_file_payload(getattr(request, "current_file", None)),
                default="general",
            )
            if deps.message_requests_project_sourcing(request.message):
                scenario = "project_sourcing"
        coach_turn = deps.honest_unusable_provider_coach_turn(
            response_language=request.response_language,
            snapshot=state.snapshot,
            coaching_service=coaching_service,
            object_kind=unusable_kind,
            # infer_coaching_scenario/infer_message_coaching_scenario only
            # return valid scenario names.
            scenario=cast(CoachScenario, scenario),
        )
        scenario = str(coach_turn["scenario"] or scenario)
        artifacts = {}
        suggested_actions = list(coach_turn["suggested_actions"])
        assistant_content = str(coach_turn["coach_turn"].summary)
        agent_meta = {
            "summary": coach_turn["coach_turn"].summary,
            "next_step": coach_turn["coach_turn"].next_step,
        }
    elif request.intent == "next_task":
        if not provider_live_usable:
            coach_turn = deps.honest_unusable_provider_coach_turn(
                response_language=request.response_language,
                snapshot=state.snapshot,
                coaching_service=coaching_service,
                object_kind="task",
            )
            scenario = "general"
            artifacts = {}
            suggested_actions = list(coach_turn["suggested_actions"])
            assistant_content = str(coach_turn["coach_turn"].summary)
            agent_meta = {
                "summary": coach_turn["coach_turn"].summary,
                "next_step": coach_turn["coach_turn"].next_step,
            }
        else:
            task = deps.review_aware_next_task(workspace_id=workspace_id,
                profile=profile,
                focus_area=request.focus_area,
                response_language=request.response_language,
            )
            task = deps.clean_active_thread_task(
                task,
                request.response_language,
                deps.runtime.memory_service.snapshot(state.workspace_id).active_thread,
                plan=state.snapshot.plan,
                snapshot=state.snapshot,
            )
            state.snapshot.current_task = task
            state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
            state.snapshot.profile = profile
            coach_turn = deps.resolve_coach_turn(
                state=state,
                profile=profile,
                request=request,
                message=request.message,
                coaching_service=coaching_service,
                current_task=task,
                current_plan=state.snapshot.plan,
                current_evaluation=state.snapshot.evaluation,
                force_scenario="next_task",
            )
            scenario = "next_task"
            learner_signal = str(coach_turn["learner_signal"])
            artifacts = dict(coach_turn["artifacts"])
            suggested_actions = list(coach_turn["suggested_actions"])
            leftover_runtime = coach_focus_runtime_from_snapshot(state.snapshot)
            picked = live_task_picked_copy(
                plan=state.snapshot.plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                task_title=task.title,
            )
            assistant_content = localized_text(picked["en"], picked["zh"], request.response_language)
    elif request.intent == "task":
        if not provider_live_usable:
            coach_turn = deps.honest_unusable_provider_coach_turn(
                response_language=request.response_language,
                snapshot=state.snapshot,
                coaching_service=coaching_service,
                object_kind="task",
            )
            scenario = "general"
            artifacts = {}
            suggested_actions = list(coach_turn["suggested_actions"])
            assistant_content = str(coach_turn["coach_turn"].summary)
            agent_meta = {
                "summary": coach_turn["coach_turn"].summary,
                "next_step": coach_turn["coach_turn"].next_step,
            }
        else:
            task = deps.runtime.spec_service.specify(
                TaskSpecifyRequest(
                    session_id=request.session_id,
                    workspace_id=workspace_id,
                    natural_language_goal=request.message,
                )
            )
            state.snapshot.current_task = task
            state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
            state.snapshot.profile = profile
            coach_turn = deps.resolve_coach_turn(
                state=state,
                profile=profile,
                request=request,
                message=request.message,
                coaching_service=coaching_service,
                current_task=task,
                current_plan=state.snapshot.plan,
                current_evaluation=state.snapshot.evaluation,
                force_scenario="task",
            )
            scenario = "task"
            learner_signal = str(coach_turn["learner_signal"])
            artifacts = dict(coach_turn["artifacts"])
            suggested_actions = list(coach_turn["suggested_actions"])
            leftover_runtime = coach_focus_runtime_from_snapshot(state.snapshot)
            converted = live_task_converted_copy(
                plan=state.snapshot.plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                task_title=task.title,
            )
            assistant_content = localized_text(converted["en"], converted["zh"], request.response_language)
    elif request.intent == "plan":
        # Formal plans are committed by the model through save_formal_plan.
        # Leftover stored plans stay stored. Do not paint them live without
        # recovered runtime identity, and do not synthesize a replacement.
        leftover_plan, leftover_runtime = deps.leftover_runtime_for_workspace(workspace_id)
        plan = (
            leftover_plan
            if leftover_formal_plan_is_live_for_fill(
                plan=leftover_plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            else None
        )
        deps.runtime.memory_service.record_profile(workspace_id, profile)
        state.snapshot.plan = plan
        state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.profile = profile
        if not provider_live_usable:
            coach_turn = deps.honest_unusable_provider_coach_turn(
                response_language=request.response_language,
                snapshot=state.snapshot,
                coaching_service=coaching_service,
                object_kind="plan",
                scenario="plan",
            )
            scenario = "plan"
            artifacts = {}
            suggested_actions = list(coach_turn["suggested_actions"])
            assistant_content = str(coach_turn["coach_turn"].summary)
            agent_meta = {
                "summary": coach_turn["coach_turn"].summary,
                "next_step": coach_turn["coach_turn"].next_step,
            }
        else:
            coach_turn = deps.resolve_coach_turn(
                state=state,
                profile=profile,
                request=request,
                message=request.message,
                coaching_service=coaching_service,
                current_task=state.snapshot.current_task,
                current_plan=plan,
                current_evaluation=state.snapshot.evaluation,
                force_scenario="plan",
            )
            stage_count = len(plan.phases) if plan is not None else 0
            scenario = "plan"
            learner_signal = str(coach_turn["learner_signal"])
            artifacts = dict(coach_turn["artifacts"])
            suggested_actions = list(coach_turn["suggested_actions"])
            assistant_content = (
                ""
                if request.formal_plan_mutation
                else localized_text(
                    (
                        f"I refreshed your learning plan with {stage_count} stages. "
                        "Anchor on the current stage first, then convert it into a small set of actions you can actually finish."
                    ),
                    f"\u6211\u5df2\u7ecf\u66f4\u65b0\u4e86\u4f60\u7684\u5b66\u4e60\u8ba1\u5212\uff0c\u5171 {stage_count} \u4e2a\u9636\u6bb5\u3002"
                    "\u5148\u56f4\u7ed5\u5f53\u524d\u9636\u6bb5\u63a8\u8fdb\uff0c\u518d\u628a\u5b83\u62c6\u6210\u4f60\u73b0\u5728\u80fd\u5b8c\u6210\u7684\u5c0f\u52a8\u4f5c\u3002",
                    request.response_language,
                )
            )
    elif request.intent == "review":
        if request.current_file is None:
            raise HTTPException(status_code=400, detail="Current file is required for review turns.")
        leftover = deps.leftover_plan_state_fields(workspace_id)
        leftover_runtime = leftover.get("leftover_runtime")
        report = stamp_produced_workspace_record(
            deps.runtime.evaluator_service.evaluate_current_file(
                EvaluateCurrentFileRequest(
                    session_id=request.session_id,
                    workspace_id=workspace_id,
                    task_spec_id=state.snapshot.current_task.id if state.snapshot.current_task else None,
                    file_path=request.current_file.path,
                    language_id=request.current_file.language_id,
                    content=request.current_file.content,
                ),
                state.snapshot.current_task,
                leftover_plan=leftover.get("leftover_plan"),
                leftover_runtime=leftover_runtime if isinstance(leftover_runtime, dict) else {},
                leftover_task_title=str(leftover.get("leftover_task_title") or ""),
                response_language=(
                    supported_response_language(request.response_language)
                    or deps.workspace_response_language(workspace_id)
                ),
            ),
            workspace_id,
        )
        state.snapshot.evaluation = report
        deps.persist_evaluation_learning_loop(
            workspace_id=workspace_id,
            state=state,
            report=report,
            action_type="review",
            fallback_focus_area=(
                Path(str(request.current_file.path or "")).stem.strip() or "review"
            ),
        )
        deps.advance_plan_after_evaluation(
            workspace_id=workspace_id,
            state=state,
            report=report,
        )
        state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.profile = profile
        coach_turn = deps.resolve_coach_turn(
            state=state,
            profile=profile,
            request=request,
            message=request.message,
            coaching_service=coaching_service,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
            current_evaluation=report,
            force_scenario="review",
        )
        scenario = "review"
        learner_signal = str(coach_turn["learner_signal"])
        artifacts = dict(coach_turn["artifacts"])
        suggested_actions = list(coach_turn["suggested_actions"])
        assistant_content = localized_text(
            f"Review finished. {report.summary} Highest-leverage next step: {report.next_step}",
            f"\u8bc4\u5ba1\u5b8c\u6210\u3002{report.summary} \u5f53\u524d\u6700\u503c\u5f97\u5148\u505a\u7684\u4e0b\u4e00\u6b65\uff1a{report.next_step}",
            request.response_language,
        )
    else:
        raise HTTPException(status_code=400, detail="Unsupported turn intent.")

    final_resource_context = deps.compose_resource_context(
        state.workspace_id,
        deps.request_resource_ids(request),
        message=request.message,
        resource_composer_intent=request.resource_composer_intent,
    )
    deps.runtime.memory_service.record_session_message(
        state.session_id,
        f"user: {request.message}",
        workspace_id=state.workspace_id,
    )
    request_coach_context = coach_turn.get("coach_context")
    if isinstance(request_coach_context, dict):
        request_coach_context = dict(request_coach_context)
        if final_resource_context:
            for key, value in final_resource_context.items():
                request_coach_context.setdefault(key, value)
    else:
        request_coach_context = deps.build_coach_context(
            state.snapshot,
            final_resource_context,
            message=request.message,
            active_view=request.active_view,
            current_file=request.current_file,
            response_language=request.response_language,
            plan_runtime_recovery=getattr(request, "plan_runtime_recovery", None),
        )
    if request.intent == "plan" and not stream and provider_live_usable:
        history = deps.build_conversation_history(
            state.snapshot.messages,
            drop_latest_user=True,
        )
        if use_agent_loop:
            agent_context = dict(request_coach_context or {})
            agent_context["__runtime__"] = deps.runtime
            agent_context["workspace_id"] = workspace_id
            agent_context["session_id"] = state.session_id
            _stamp_library_sandbox_work(agent_context, request, payload)
            agent_outcome = await coaching_service.coaching_reply_agentic(
                profile,
                request.message,
                request.current_file.model_dump() if request.current_file else None,
                response_language=request.response_language,
                answer_mode=request.answer_mode,
                coach_context=agent_context,
                attachments=attachments_payload,
                protocol=(
                    getattr(coaching_service._config, "protocol", None)
                    if coaching_service._config
                    else None
                ),
                history=history,
            )
            assistant_content = str(agent_outcome.get("content") or "").strip()
            agent_resume_thread = str(agent_outcome.get("resume_thread") or "").strip()
            if not agent_resume_thread:
                agent_resume_thread = deps.build_resume_thread_text(
                    str(agent_outcome.get("summary") or "").strip(),
                    str(agent_outcome.get("next_step") or "").strip(),
                    response_language=request.response_language,
                )
            agent_meta = {
                "stop_reason": agent_outcome.get("stop_reason"),
                "summary": agent_outcome.get("summary"),
                "next_step": agent_outcome.get("next_step"),
                "decision": agent_outcome.get("decision"),
                "blocker": agent_outcome.get("blocker"),
                "teaching_note": agent_outcome.get("teaching_note"),
                "resume_thread": agent_resume_thread,
                "confidence": agent_outcome.get("confidence"),
                "evidence": agent_outcome.get("evidence"),
                "steps": agent_outcome.get("steps", []),
                "tool_events": agent_outcome.get("tool_events", []),
                "fell_back": bool(agent_outcome.get("fell_back")),
                "recovered_stop_reason": agent_outcome.get("recovered_stop_reason"),
                "agentic": True,
            }
            deps.apply_attachment_delivery_metadata(agent_meta, agent_outcome)
            if request.formal_plan_mutation:
                persisted_plan = deps.runtime.repository.get_latest_plan(workspace_id)
                _leftover_after, leftover_runtime_after = deps.leftover_runtime_for_workspace(
                    workspace_id
                )
                if persisted_plan is not None and leftover_formal_plan_is_live_for_fill(
                    plan=persisted_plan,
                    runtime=leftover_runtime_after,
                    existing=leftover_runtime_after,
                ):
                    state.snapshot.plan = persisted_plan
        else:
            # When the Agent loop is disabled, keep the legacy provider
            # reply path. It still cannot synthesize or persist a formal
            # plan because this branch is discussion-only.
            assistant_content = await coaching_service.coaching_reply(
                profile,
                request.message,
                request.current_file.model_dump() if request.current_file else None,
                response_language=request.response_language,
                answer_mode=request.answer_mode,
                coach_context=request_coach_context,
                history=history,
            )
    if deps.should_attach_auto_resource_events(agent_meta):
        agent_meta = deps.apply_auto_resource_agent_evidence(
            agent_meta,
            deps.auto_resource_lookup_tool_events(
                request_coach_context if isinstance(request_coach_context, dict) else None,
                request.message,
            ),
        )
    if not use_agent_loop and agent_meta:
        agent_meta["agentic"] = False
    request_turn_summary = coach_turn.get("coach_turn")
    coach_turn_payload = {
        "scenario": scenario,
        "learner_signal": learner_signal,
        "coach_context": request_coach_context,
        "coach_turn": (
            request_turn_summary
            if isinstance(request_turn_summary, CoachTurnSummary)
            else deps.build_turn_summary(
                snapshot=state.snapshot,
                scenario=scenario,
                learner_signal=learner_signal,
                artifacts=artifacts,
                suggested_actions=suggested_actions,
                coach_context=request_coach_context,
                response_language=request.response_language,
            )
        ),
    }
    if isinstance(agent_meta, dict):
        coach_turn_payload = deps.merge_agent_finalize_into_coach_turn(
            coach_turn_payload,
            summary=agent_meta.get("summary"),
            next_step=agent_meta.get("next_step"),
            blocker=agent_meta.get("blocker"),
            resume_thread=agent_meta.get("resume_thread") or agent_meta.get("resumeThread"),
            decision=agent_meta.get("decision"),
            teaching_note=agent_meta.get("teaching_note") or agent_meta.get("teachingNote"),
            confidence=agent_meta.get("confidence"),
            evidence=agent_meta.get("evidence"),
        )
        stop_reason = str(agent_meta.get("stop_reason") or "").strip()
        preserve_active_thread = deps.should_preserve_active_thread_for_turn(
            scenario,
            state.snapshot.memory.active_thread,
            message=request.message,
            grounding_context=request_coach_context if isinstance(request_coach_context, dict) else None,
            active_view=request.active_view,
        )
        if (
            not preserve_active_thread
            and stop_reason in deps.PROVIDER_REPLY_STOP_REASONS
            and isinstance(coach_turn_payload, dict)
        ):
            coach_context = coach_turn_payload.get("coach_context")
            turn_summary = coach_turn_payload.get("coach_turn")
            if isinstance(coach_context, dict) and isinstance(turn_summary, CoachTurnSummary):
                focus_hint = deps.extract_focus_hint_from_message(request.message) or ""
                visible_focus_hint = deps.guided_focus_display_value(
                    focus_hint,
                    scenario=scenario,
                    response_language=request.response_language,
                )
                if visible_focus_hint:
                    coach_context["current_focus"] = visible_focus_hint
                coach_context["active_thread"] = {
                    "scenario": scenario,
                    "focus_area": visible_focus_hint or focus_hint,
                    "summary": turn_summary.summary,
                    "next_step": turn_summary.next_step,
                    "blocker": turn_summary.blocker,
                    "decision": turn_summary.decision,
                    "teaching_note": turn_summary.teaching_note,
                    "confidence": turn_summary.confidence,
                    "evidence": list(turn_summary.evidence or []),
                }
    response_snapshot = state.snapshot.model_copy(deep=True)
    # T-0048: repair a generic finalize step BEFORE grounding and memory
    # persistence so the recorded thread, the grounding gate and the
    # response surfaces all ship the same step. Only a non-empty
    # agent_meta carries a finalize step; an empty dict is the legacy
    # (non-agent) lane and must stay empty or the turn surfaces as agentic.
    coach_turn_payload = deps.repair_generic_finalize_next_step(
        assistant_content,
        agent_meta if isinstance(agent_meta, dict) and agent_meta else None,
        coach_turn_payload,
        response_language=request.response_language,
    ) or coach_turn_payload
    grounding_decision = await deps.resolve_turn_grounding_async(
        coach_turn_payload=coach_turn_payload,
        reply_content=assistant_content,
        request=request,
        agent_meta=agent_meta if isinstance(agent_meta, dict) else None,
        history_text=deps.turn_history_text(state.snapshot),
        coaching_service=coaching_service,
    )
    agent_meta = deps.apply_grounding_decision(
        coach_turn_payload=coach_turn_payload,
        decision=grounding_decision,
        agent_meta=agent_meta if isinstance(agent_meta, dict) else None,
    ) or agent_meta
    deps.persist_turn_reflection(workspace_id=workspace_id,
        session_id=state.session_id,
        user_message=request.message,
        scenario=scenario,
        response_language=request.response_language,
        answer_mode=deps.answer_mode_preference_for_persistence(
            raw_requested_answer_mode,
            saved_answer_mode,
            request.answer_mode,
            profile.answer_policy,
        ),
        coach_defaults=request.coach_defaults,
        coach_turn_data=coach_turn_payload,
        grounding_decision=grounding_decision,
        stop_reason=str(agent_meta.get("stop_reason") or ""),
        recovered_stop_reason=str(agent_meta.get("recovered_stop_reason") or ""),
        local_sequence_fallback=bool(agent_meta.get("local_sequence_fallback")),
    )
    deps.persist_recovered_plan_resume_after_turn(
        workspace_id=workspace_id,
        request=request,
        reply_content=assistant_content,
        agent_meta=agent_meta if isinstance(agent_meta, dict) else None,
        coach_context=request_coach_context if isinstance(request_coach_context, dict) else None,
        recovered_status=state.snapshot.plan_runtime_status
        if isinstance(state.snapshot.plan_runtime_status, dict)
        else None,
    )
    if not language_corruption_detected and not provider_failure_detected:
        deps.persist_external_references_as_background(
            workspace_id=workspace_id,
            scenario=scenario,
            coach_turn_data=coach_turn_payload,
        )
    if not provider_live_usable:
        suggested_actions = deps.honest_suggested_actions_without_usable_provider(
            suggested_actions,
            response_language=request.response_language,
            snapshot=state.snapshot,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
            current_evaluation=state.snapshot.evaluation,
        )
    if agent_meta:
        # Stamp reliability only onto a real agent meta. Stamping an empty
        # dict would resurrect agent_meta for clean non-agent turns and the
        # AgentMeta default (agentic=True) would mislabel the reply lane.
        agent_meta["reliability"] = deps.operation_reliability_record(
            phase="acked",
            outcome=(
                "failure"
                if not provider_live_usable or provider_failure_detected
                else "success"
            ),
            request_id=str(request.request_id or "").strip() or None,
        )
    state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
    state.snapshot.profile = deps.runtime.repository.get_profile(workspace_id) or profile
    deps.hydrate_snapshot(state.snapshot,
        response_language=request.response_language,
        answer_mode=request.answer_mode or profile.answer_policy,
        scenario=scenario,
        learner_signal=learner_signal,
        message=request.message,
        current_file=request.current_file,
        active_view=request.active_view,
        session_workspace_id=workspace_id,
    )
    if frozen_formal_plan_mutation_requested:
        assistant_content = "\n\n".join(
            part
            for part in (deps.frozen_plan_mutation_notice(request.response_language), assistant_content)
            if part
        )
        agent_meta["formal_plan_mutation_blocked"] = True
    if not (scenario == "idea_implementation" and request.current_file is not None):
        response_snapshot = state.snapshot

    if stream and request.intent != "coach":
        return (
            {
                "__turn_stream_preparation__": True,
                "state": state,
                "request": request,
                "profile": profile,
                "scenario": scenario,
                "learner_signal": learner_signal,
                "coach_turn_data": coach_turn_payload,
                "artifacts": artifacts,
                "suggested_actions": suggested_actions,
                "agent_meta": agent_meta,
                "response_snapshot": response_snapshot,
                "attachment_delivery": attachment_delivery,
                "fallback_reply": assistant_content,
                "use_agent_loop": use_agent_loop,
            },
            artifacts,
            coaching_service,
        )

    return (
        deps.build_session_response(
            state=state,
            request=request,
            reply_content=assistant_content,
            artifacts=artifacts,
            suggested_actions=suggested_actions,
            scenario=scenario,
            learner_signal=learner_signal,
            coach_turn_data=coach_turn_payload,
            response_snapshot=response_snapshot,
            agent_meta=agent_meta or None,
            attachment_delivery=attachment_delivery,
        ),
        artifacts,
        coaching_service,
    )

