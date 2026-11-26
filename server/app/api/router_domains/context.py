"""Composed domain context and dependency wiring for sidecar API routers."""

from __future__ import annotations

import asyncio
import contextvars
from threading import Lock
from typing import Any

from .. import coach_support
from .._helpers import normalized_object_mapping
from ..coach_language_alignment import (
    language_aligned_coaching_state_payload,
    language_aligned_context_list,
    language_aligned_context_text,
    language_aligned_flat_payload,
    language_aligned_memory_payload,
    language_aligned_review_rhythm,
    language_aligned_thread_payload,
)
from ..coach_support import CoachSupportDeps
from ..coach_text_sanitizer import (
    repair_legacy_assistant_messages,
    sanitize_visible_coach_reply_content,
    strip_visible_next_step_prefix,
)
from ..provider_payload import (
    provider_api_key_from_payload,
    provider_capabilities_from_payload,
    provider_config_from_payload,
    provider_connection_type_from_payload,
    provider_protocol_from_payload,
)
from ..routes._deps import RouterDeps
from ..runtime import TrainerRuntime
from .coach_turn_artifacts import CoachTurnArtifactsDomainMixin
from .constants import (
    GROUNDING_MEMORY_PROVENANCE_CACHE_KEY,
    GUIDED_LANE_SCENARIOS,
    GUIDED_VISIBLE_REPAIR_SCENARIOS,
    PROVIDER_REPLY_STOP_REASONS,
)
from .guided_focus import GuidedFocusDomainMixin
from .pedagogy_and_evaluation import PedagogyAndEvaluationDomainMixin
from .provider_recovery import ProviderRecoveryDomainMixin
from .resource_grounding import ResourceGroundingDomainMixin
from .stream_and_locks import StreamAndLocksDomainMixin
from .training_cards import TrainingCardsDomainMixin
from .turn_grounding import TurnGroundingDomainMixin
from .workspace_and_honesty import WorkspaceAndHonestyDomainMixin


class RouterDomainContext(
    StreamAndLocksDomainMixin,
    GuidedFocusDomainMixin,
    ProviderRecoveryDomainMixin,
    ResourceGroundingDomainMixin,
    CoachTurnArtifactsDomainMixin,
    TurnGroundingDomainMixin,
    WorkspaceAndHonestyDomainMixin,
    TrainingCardsDomainMixin,
    PedagogyAndEvaluationDomainMixin,
):
    """Per-router state and cohesive domain methods formerly nested in build_router."""

    runtime: TrainerRuntime
    coach_support_deps: CoachSupportDeps

    normalized_object_mapping = staticmethod(normalized_object_mapping)
    provider_config_from_payload = staticmethod(provider_config_from_payload)
    provider_api_key_from_payload = staticmethod(provider_api_key_from_payload)

    def __init__(self, runtime: TrainerRuntime) -> None:
        self.runtime = runtime
        self.action_id_counter: int = 0
        self.training_card_locks: dict[str, Lock] = {}
        self.training_card_locks_guard = Lock()
        self.stream_cancellation_events: dict[str, asyncio.Event] = {}
        self.stream_cancellation_guard = Lock()
        self.completed_session_requests: dict[tuple[str, str, str], dict[str, object]] = {}
        self.completed_session_requests_guard = Lock()
        self.inflight_session_requests: dict[tuple[str, str, str], asyncio.Future[Any]] = {}
        self.completed_training_card_requests: dict[tuple[str, str, str], dict[str, object]] = {}
        self.completed_training_card_requests_guard = Lock()
        self.inflight_training_card_requests: dict[tuple[str, str, str], asyncio.Future[Any]] = {}
        self._stream_snapshot_fields: contextvars.ContextVar[str] = contextvars.ContextVar(
            f"trainer_stream_snapshot_fields_{id(runtime)}",
            default="full",
        )

    def bind_coach_support_deps(self, coach_support_deps: CoachSupportDeps) -> None:
        self.coach_support_deps = coach_support_deps


def build_coach_support_deps(domain: RouterDomainContext) -> CoachSupportDeps:
    deps = CoachSupportDeps(
        coach_suggested_actions=lambda *args, **kwargs: coach_support.coach_suggested_actions(domain.coach_support_deps, *args, **kwargs),
        hydrate_snapshot=lambda *args, **kwargs: coach_support.hydrate_snapshot(domain.coach_support_deps, *args, **kwargs),
        review_aware_next_task=lambda *args, **kwargs: coach_support.review_aware_next_task(domain.coach_support_deps, *args, **kwargs),
        persist_turn_reflection=lambda *args, **kwargs: coach_support.persist_turn_reflection(domain.coach_support_deps, *args, **kwargs),
        build_coaching_artifacts=lambda *args, **kwargs: coach_support.build_coaching_artifacts(domain.coach_support_deps, *args, **kwargs),
        workspace_response_language=domain.workspace_response_language,
        workspace_preferences=domain.workspace_preferences,
        update_snapshot_plan_from_turn=domain.update_snapshot_plan_from_turn,
        turn_keeps_review_signals=domain.turn_keeps_review_signals,
        turn_history_text=domain.turn_history_text,
        streak_without_live_object_blocks_mint=domain.streak_without_live_object_blocks_mint,
        should_remap_task_intent_without_live_plan=domain.should_remap_task_intent_without_live_plan,
        should_preserve_relationship_continuity_for_turn=domain.should_preserve_relationship_continuity_for_turn,
        should_bypass_agent_loop_for_guided_training=domain.should_bypass_agent_loop_for_guided_training,
        should_attach_auto_resource_events=domain.should_attach_auto_resource_events,
        sanitize_visible_coach_reply_content=sanitize_visible_coach_reply_content,
        safe_activate_training_card_from_coach_request=domain.safe_activate_training_card_from_coach_request,
        resolved_profile=domain.resolved_profile,
        resolve_turn_grounding_async=domain.resolve_turn_grounding_async,
        resolve_local_continuation_step=domain.resolve_local_continuation_step,
        resolve_external_references=domain.resolve_external_references,
        resolve_coach_turn=lambda *args, **kwargs: coach_support.resolve_coach_turn(domain.coach_support_deps, *args, **kwargs),
        request_with_workspace_defaults=domain.request_with_workspace_defaults,
        requires_formal_plan_commit=domain.requires_formal_plan_commit,
        request_resource_ids=domain.request_resource_ids,
        reply_explicitly_lists_prepared_sequence=domain.reply_explicitly_lists_prepared_sequence,
        repair_legacy_assistant_messages=repair_legacy_assistant_messages,
        repair_guided_lane_memory_snapshot_for_response=domain.repair_guided_lane_memory_snapshot_for_response,
        repair_generic_finalize_next_step=domain.repair_generic_finalize_next_step,
        provider_is_live_usable=domain.provider_is_live_usable,
        profile_with_teaching_style=domain.profile_with_teaching_style,
        pressure_without_live_object_blocks_mint=domain.pressure_without_live_object_blocks_mint,
        preserve_requested_domain_scenario=domain.preserve_requested_domain_scenario,
        persist_recovered_plan_resume_after_turn=domain.persist_recovered_plan_resume_after_turn,
        persist_external_references_as_background=domain.persist_external_references_as_background,
        persist_evaluation_learning_loop=domain.persist_evaluation_learning_loop,
        operation_reliability_record=domain.operation_reliability_record,
        normalize_current_file_payload=domain.normalize_current_file_payload,
        model_teaching_decision=domain.model_teaching_decision,
        model_project_sources=domain.model_project_sources,
        model_project_ideas=domain.model_project_ideas,
        model_project_adaptation_guide=domain.model_project_adaptation_guide,
        model_principle_notes=domain.model_principle_notes,
        model_learner_state=domain.model_learner_state,
        model_implementation_guide=domain.model_implementation_guide,
        message_requests_project_sourcing=domain.message_requests_project_sourcing,
        message_requests_explicit_explanation_or_example=domain.message_requests_explicit_explanation_or_example,
        message_keeps_existing_thread=domain.message_keeps_existing_thread,
        merge_agent_finalize_into_coach_turn=domain.merge_agent_finalize_into_coach_turn,
        live_formal_plan_for_explicit_task_next=domain.live_formal_plan_for_explicit_task_next,
        leftover_plan_state_fields=domain.leftover_plan_state_fields,
        leftover_frozen_blocks_turn_generation=domain.leftover_frozen_blocks_turn_generation,
        language_aligned_thread_payload=language_aligned_thread_payload,
        language_aligned_review_rhythm=language_aligned_review_rhythm,
        language_aligned_memory_payload=language_aligned_memory_payload,
        language_aligned_flat_payload=language_aligned_flat_payload,
        language_aligned_context_text=language_aligned_context_text,
        language_aligned_context_list=language_aligned_context_list,
        language_aligned_coaching_state_payload=language_aligned_coaching_state_payload,
        isolate_preflight_language_corruption_turn=domain.isolate_preflight_language_corruption_turn,
        inherit_active_thread_scenario_for_continuation=domain.inherit_active_thread_scenario_for_continuation,
        infer_learner_signal=domain.infer_learner_signal,
        infer_coaching_scenario=domain.infer_coaching_scenario,
        honest_unusable_provider_coach_turn=domain.honest_unusable_provider_coach_turn,
        honest_suggested_actions_without_usable_provider=domain.honest_suggested_actions_without_usable_provider,
        guided_lane_visible_reply_is_generic=domain.guided_lane_visible_reply_is_generic,
        guided_lane_visible_reply_has_foreign_markers=domain.guided_lane_visible_reply_has_foreign_markers,
        guarantee_guided_learn_first_training_card=domain.guarantee_guided_learn_first_training_card,
        grounding_response_coach_turn=domain.grounding_response_coach_turn,
        grounding_decision_from_payload=domain.grounding_decision_from_payload,
        grounded_resource_contract_needs_repair=domain.grounded_resource_contract_needs_repair,
        function_guidance_entry_points=domain.function_guidance_entry_points,
        frozen_plan_mutation_notice=domain.frozen_plan_mutation_notice,
        formal_plan_commit_verified=domain.formal_plan_commit_verified,
        formal_plan_commit_missing_reply=domain.formal_plan_commit_missing_reply,
        formal_plan_commit_missing_next_step=domain.formal_plan_commit_missing_next_step,
        extract_focus_hint_from_message=domain.extract_focus_hint_from_message,
        extract_coach_turn_payload=domain.extract_coach_turn_payload,
        ensure_explicit_training_card_after_language_block=domain.ensure_explicit_training_card_after_language_block,
        ensure_explicit_training_card_after_coach_reply=domain.ensure_explicit_training_card_after_coach_reply,
        ensure_coach_provider_ready=domain.ensure_coach_provider_ready,
        ensure_agent_tools_ready=domain.ensure_agent_tools_ready,
        detect_provider_language_corruption=domain.detect_provider_language_corruption,
        describe_request_attachment_delivery=domain.describe_request_attachment_delivery,
        current_workspace_id=domain.current_workspace_id,
        consume_provider_reply_failure_override=domain.consume_provider_reply_failure_override,
        consume_provider_empty_reply_override=domain.consume_provider_empty_reply_override,
        compose_resource_context=domain.compose_resource_context,
        coach_turn_mapping=domain.coach_turn_mapping,
        closed_loop_return_blocks_task_mint=domain.closed_loop_return_blocks_task_mint,
        clean_active_thread_task=domain.clean_active_thread_task,
        canonical_focus_for_scenario=domain.canonical_focus_for_scenario,
        build_user_message_metadata=domain.build_user_message_metadata,
        build_turn_summary=domain.build_turn_summary,
        build_session_response=lambda *args, **kwargs: coach_support.build_session_response(domain.coach_support_deps, *args, **kwargs),
        build_local_sequence_visible_fallback=domain.build_local_sequence_visible_fallback,
        build_guided_training_visible_fallback=domain.build_guided_training_visible_fallback,
        build_guided_lane_stable_visible_reply=domain.build_guided_lane_stable_visible_reply,
        build_grounded_resource_contract_visible_fallback=domain.build_grounded_resource_contract_visible_fallback,
        build_empty_response_visible_reply=domain.build_empty_response_visible_reply,
        build_conversation_history=domain.build_conversation_history,
        build_coaching_service=domain.build_coaching_service,
        build_coach_context=lambda *args, **kwargs: coach_support.build_coach_context(domain.coach_support_deps, *args, **kwargs),
        build_assistant_metadata=domain.build_assistant_metadata,
        auto_resource_lookup_tool_events=domain.auto_resource_lookup_tool_events,
        auto_preference_requests_training_card=domain.auto_preference_requests_training_card,
        auto_lane_learn_first_force_training_card=domain.auto_lane_learn_first_force_training_card,
        apply_pedagogy_snapshot=domain.apply_pedagogy_snapshot,
        apply_next_step_grounding_policy=domain.apply_next_step_grounding_policy,
        apply_language_corruption_override=domain.apply_language_corruption_override,
        apply_guided_training_visible_fallback=domain.apply_guided_training_visible_fallback,
        apply_guided_lane_visible_fallback=domain.apply_guided_lane_visible_fallback,
        apply_grounding_decision=domain.apply_grounding_decision,
        apply_auto_resource_agent_evidence=domain.apply_auto_resource_agent_evidence,
        apply_attachment_delivery_metadata=domain.apply_attachment_delivery_metadata,
        apply_agent_meta_to_coaching_state=domain.apply_agent_meta_to_coaching_state,
        answer_mode_preference_for_persistence=domain.answer_mode_preference_for_persistence,
        advance_plan_after_evaluation=domain.advance_plan_after_evaluation,
        active_thread_scenario_value=domain.active_thread_scenario_value,
        _resolve_context_tier=domain._resolve_context_tier,
        PROVIDER_REPLY_STOP_REASONS=PROVIDER_REPLY_STOP_REASONS,
        GUIDED_VISIBLE_REPAIR_SCENARIOS=GUIDED_VISIBLE_REPAIR_SCENARIOS,
        runtime=domain.runtime,
        GROUNDING_MEMORY_PROVENANCE_CACHE_KEY=GROUNDING_MEMORY_PROVENANCE_CACHE_KEY,
        GUIDED_LANE_SCENARIOS=GUIDED_LANE_SCENARIOS,
        active_plan_stage=domain.active_plan_stage,
        active_view_coaching_lane_override=domain.active_view_coaching_lane_override,
        active_view_owns_turn_lane=domain.active_view_owns_turn_lane,
        artifact_payload=domain.artifact_payload,
        attach_plan_runtime_status=domain.attach_plan_runtime_status,
        build_next_step_hint=domain.build_next_step_hint,
        build_resume_thread_text=domain.build_resume_thread_text,
        coach_artifact_title=domain.coach_artifact_title,
        coach_focus_bundle=domain.coach_focus_bundle,
        continuation_step_needs_local_repair=domain.continuation_step_needs_local_repair,
        derive_coaching_state=lambda *args, **kwargs: coach_support.derive_coaching_state(domain.coach_support_deps, *args, **kwargs),
        display_focus_label=domain.display_focus_label,
        exercise_lines=domain.exercise_lines,
        extract_lane_continuation_step=domain.extract_lane_continuation_step,
        first_look_recommended_next_from_snapshot=domain.first_look_recommended_next_from_snapshot,
        function_guidance_current_file_name=domain.function_guidance_current_file_name,
        generic_guided_review_fallback_needs_repair=domain.generic_guided_review_fallback_needs_repair,
        guided_focus_display_value=domain.guided_focus_display_value,
        honest_suggested_actions_without_live_object=domain.honest_suggested_actions_without_live_object,
        is_provider_recovery_thread_payload=domain.is_provider_recovery_thread_payload,
        leftover_runtime_for_workspace=domain.leftover_runtime_for_workspace,
        live_stage_object_label=domain.live_stage_object_label,
        local_continuation_step_for_scenario=domain.local_continuation_step_for_scenario,
        localized_actions=domain.localized_actions,
        localized_agent_tool_label=domain.localized_agent_tool_label,
        message_requests_lane_continuation=domain.message_requests_lane_continuation,
        normalize_active_view_name=domain.normalize_active_view_name,
        normalize_answer_mode=domain.normalize_answer_mode,
        normalized_object_mapping=normalized_object_mapping,
        provider_recovery_resumed_next_step=domain.provider_recovery_resumed_next_step,
        provider_recovery_resumed_summary=domain.provider_recovery_resumed_summary,
        recovered_overlay_without_live_object=domain.recovered_overlay_without_live_object,
        recovery_turn_has_no_learning_evidence=domain.recovery_turn_has_no_learning_evidence,
        render_artifact_content=domain.render_artifact_content,
        resolve_focus_hint=domain.resolve_focus_hint,
        resolve_turn_focus_hint=domain.resolve_turn_focus_hint,
        resource_grounding_turn_prefers_fresh_lane=domain.resource_grounding_turn_prefers_fresh_lane,
        should_preserve_active_thread_for_turn=domain.should_preserve_active_thread_for_turn,
        stateful_focus_area=domain.stateful_focus_area,
        strip_visible_next_step_prefix=strip_visible_next_step_prefix,
        structured_plan_progress_signal=domain.structured_plan_progress_signal,
        structured_suggested_actions=domain.structured_suggested_actions,
        summarize_review_queue=domain.summarize_review_queue,
    )
    domain.bind_coach_support_deps(deps)
    return deps


def build_router_deps(domain: RouterDomainContext) -> RouterDeps:
    return RouterDeps(
        current_workspace_id=domain.current_workspace_id,
        trusted_write_workspace_id=domain.trusted_write_workspace_id,
        current_snapshot=domain.current_snapshot,
        refresh_workspace_sessions=domain.refresh_workspace_sessions,
        hydrate_snapshot=lambda *args, **kwargs: coach_support.hydrate_snapshot(domain.coach_support_deps, *args, **kwargs),
        effective_response_language=domain.effective_response_language,
        persist_first_look_summary=domain.persist_first_look_summary,
        provider_config_from_payload=provider_config_from_payload,
        provider_api_key_from_payload=provider_api_key_from_payload,
        normalize_trainer_root_path=domain.normalize_trainer_root_path,
        routing_learner_state=domain.routing_learner_state,
        operation_reliability_record=domain.operation_reliability_record,
        provider_capabilities_from_payload=provider_capabilities_from_payload,
        provider_connection_type_from_payload=provider_connection_type_from_payload,
        provider_protocol_from_payload=provider_protocol_from_payload,
        provider_model_policy_detail=domain.provider_model_policy_detail,
        provider_model_policy_violation=domain.provider_model_policy_violation,
        require_sandbox_service=domain.require_sandbox_service,
        apply_host_workspace_trust_attestation=domain.apply_host_workspace_trust_attestation,
        workspace_learning_project_state=domain.workspace_learning_project_state,
        active_plan_stage=domain.active_plan_stage,
        attach_plan_runtime_status=domain.attach_plan_runtime_status,
        coach_suggested_actions=lambda *args, **kwargs: coach_support.coach_suggested_actions(domain.coach_support_deps, *args, **kwargs),
        ensure_coach_provider_ready=domain.ensure_coach_provider_ready,
        frozen_plan_mutation_notice=domain.frozen_plan_mutation_notice,
        leftover_runtime_for_workspace=domain.leftover_runtime_for_workspace,
        persist_plan_to_sandbox=domain.persist_plan_to_sandbox,
        provider_is_live_usable=domain.provider_is_live_usable,
        stateful_focus_area=domain.stateful_focus_area,
        structured_suggested_actions=domain.structured_suggested_actions,
        workspace_first_look_summary=domain.workspace_first_look_summary,
        sync_resource_record_to_sandbox=domain.sync_resource_record_to_sandbox,
    )
