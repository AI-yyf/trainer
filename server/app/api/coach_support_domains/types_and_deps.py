"""Coach turn helpers moved out of build_router (§五十二 extraction).

The helpers share one dependency bundle (``CoachSupportDeps``) assembled by
``build_router``. Keeping the bundle explicit makes the closure graph visible
instead of hiding 45 names inside a 25k-line function.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

from ...core.models import (
    CoachTurnSummary,
)
from ...llm.turn_grounding import (
    GroundingDecision,
)
from ..router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from ..router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)


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
