"""Fail-closed workspace recovery for plan, provider last-test, and streams.

These records live on structured workspace memory — the same DB path as
training reliability, coach orientation, and transfer state. Incomplete
records are never treated as success. API keys are never stored.
"""

from __future__ import annotations

from .workspace_recovery_domains.evidence_and_scope import (
    RESUME_FAILURE_STOP_REASONS as RESUME_FAILURE_STOP_REASONS,
)
from .workspace_recovery_domains.evidence_and_scope import (
    STRUCTURED_STEP_FINISHED_KEYS as STRUCTURED_STEP_FINISHED_KEYS,
)
from .workspace_recovery_domains.evidence_and_scope import (
    STRUCTURED_STEP_FINISHED_TOKENS as STRUCTURED_STEP_FINISHED_TOKENS,
)
from .workspace_recovery_domains.evidence_and_scope import (
    WAITING_VERIFY_EVIDENCE_SOURCE as WAITING_VERIFY_EVIDENCE_SOURCE,
)
from .workspace_recovery_domains.evidence_and_scope import (
    _evidence_field as _evidence_field,
)
from .workspace_recovery_domains.evidence_and_scope import (
    _model_payload as _model_payload,
)
from .workspace_recovery_domains.evidence_and_scope import (
    accept_in_progress_plan_runtime_turn as accept_in_progress_plan_runtime_turn,
)
from .workspace_recovery_domains.evidence_and_scope import (
    accept_plan_runtime_resume_request as accept_plan_runtime_resume_request,
)
from .workspace_recovery_domains.evidence_and_scope import (
    apply_affect_tone_scope as apply_affect_tone_scope,
)
from .workspace_recovery_domains.evidence_and_scope import (
    apply_coaching_focus_scope as apply_coaching_focus_scope,
)
from .workspace_recovery_domains.evidence_and_scope import (
    apply_current_task_scope as apply_current_task_scope,
)
from .workspace_recovery_domains.evidence_and_scope import (
    apply_evaluation_chrome_scope as apply_evaluation_chrome_scope,
)
from .workspace_recovery_domains.evidence_and_scope import (
    apply_teaching_artifact_scope as apply_teaching_artifact_scope,
)
from .workspace_recovery_domains.evidence_and_scope import (
    attest_waiting_verify_on_adopt as attest_waiting_verify_on_adopt,
)
from .workspace_recovery_domains.evidence_and_scope import (
    build_plan_runtime_advance_after_adopt as build_plan_runtime_advance_after_adopt,
)
from .workspace_recovery_domains.evidence_and_scope import (
    build_plan_runtime_advance_after_verify as build_plan_runtime_advance_after_verify,
)
from .workspace_recovery_domains.evidence_and_scope import (
    build_plan_runtime_resume as build_plan_runtime_resume,
)
from .workspace_recovery_domains.evidence_and_scope import (
    build_waiting_composer_evidence as build_waiting_composer_evidence,
)
from .workspace_recovery_domains.evidence_and_scope import (
    build_waiting_verify_evidence as build_waiting_verify_evidence,
)
from .workspace_recovery_domains.evidence_and_scope import (
    extract_structured_next_step_runtime_facts as extract_structured_next_step_runtime_facts,
)
from .workspace_recovery_domains.evidence_and_scope import (
    extract_structured_plan_runtime_facts as extract_structured_plan_runtime_facts,
)
from .workspace_recovery_domains.evidence_and_scope import (
    extract_structured_verify_method as extract_structured_verify_method,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_adaptation_guide as normalize_latest_adaptation_guide,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_affect_state as normalize_latest_affect_state,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_coach_focus as normalize_latest_coach_focus,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_coach_turn as normalize_latest_coach_turn,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_coaching_adaptation as normalize_latest_coaching_adaptation,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_coaching_focus as normalize_latest_coaching_focus,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_current_task as normalize_latest_current_task,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_evaluation as normalize_latest_evaluation,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_learner_state as normalize_latest_learner_state,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_next_step_hint as normalize_latest_next_step_hint,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_principle_notes as normalize_latest_principle_notes,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_project_sources as normalize_latest_project_sources,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_teaching_decision as normalize_latest_teaching_decision,
)
from .workspace_recovery_domains.evidence_and_scope import (
    normalize_latest_tone_decision as normalize_latest_tone_decision,
)
from .workspace_recovery_domains.evidence_and_scope import (
    plan_runtime_status_from_recovery as plan_runtime_status_from_recovery,
)
from .workspace_recovery_domains.evidence_and_scope import (
    recovered_resume_turn_succeeded as recovered_resume_turn_succeeded,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_adaptation_guide as select_latest_adaptation_guide,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_affect_state as select_latest_affect_state,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_coach_focus as select_latest_coach_focus,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_coach_turn as select_latest_coach_turn,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_coaching_adaptation as select_latest_coaching_adaptation,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_coaching_focus as select_latest_coaching_focus,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_current_task as select_latest_current_task,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_evaluation as select_latest_evaluation,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_learner_state as select_latest_learner_state,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_next_step_hint as select_latest_next_step_hint,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_principle_notes as select_latest_principle_notes,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_project_sources as select_latest_project_sources,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_teaching_decision as select_latest_teaching_decision,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_latest_tone_decision as select_latest_tone_decision,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_provider_capability_for_scope as select_provider_capability_for_scope,
)
from .workspace_recovery_domains.evidence_and_scope import (
    select_streaming_checkpoint_for_scope as select_streaming_checkpoint_for_scope,
)
from .workspace_recovery_domains.evidence_and_scope import (
    structured_plan_step_finished as structured_plan_step_finished,
)
from .workspace_recovery_domains.evidence_and_scope import (
    verified_adopt_allows_runtime_advance as verified_adopt_allows_runtime_advance,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    ADAPTATION_GUIDE_KEY as ADAPTATION_GUIDE_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    AFFECT_STATE_KEY as AFFECT_STATE_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    COACH_FOCUS_KEY as COACH_FOCUS_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    COACH_TURN_KEY as COACH_TURN_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    COACHING_ADAPTATION_KEY as COACHING_ADAPTATION_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    COACHING_FOCUS_KEY as COACHING_FOCUS_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    CURRENT_TASK_KEY as CURRENT_TASK_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    EVALUATION_KEY as EVALUATION_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    LEARNER_STATE_KEY as LEARNER_STATE_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    NEXT_STEP_HINT_KEY as NEXT_STEP_HINT_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    PLAN_RUNTIME_KEY as PLAN_RUNTIME_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    PRINCIPLE_NOTES_KEY as PRINCIPLE_NOTES_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    PROJECT_SOURCES_KEY as PROJECT_SOURCES_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    PROVIDER_CAPABILITY_KEY as PROVIDER_CAPABILITY_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    SECRET_KEYS as SECRET_KEYS,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    STREAMING_CHECKPOINT_KEY as STREAMING_CHECKPOINT_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    STREAMING_PHASES as STREAMING_PHASES,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    TEACHING_DECISION_KEY as TEACHING_DECISION_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    TONE_DECISION_KEY as TONE_DECISION_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    TRAINING_CHROME_KEY as TRAINING_CHROME_KEY,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    _formal_plan_candidate_focus as _formal_plan_candidate_focus,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    _recovered_overlay_empty_step as _recovered_overlay_empty_step,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    _revision as _revision,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    _text as _text,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    _verify_plan_advance_payload as _verify_plan_advance_payload,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    bound_plan_leftover_training_live_identity_updates as bound_plan_leftover_training_live_identity_updates,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    formal_card_is_live_runtime_identity as formal_card_is_live_runtime_identity,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    formal_plan_is_live_runtime_identity as formal_plan_is_live_runtime_identity,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    formal_task_is_live_runtime_identity as formal_task_is_live_runtime_identity,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_bound_plan_competing_identity_labels as leftover_bound_plan_competing_identity_labels,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_coach_conversation_is_not_live as leftover_coach_conversation_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_coach_turn_chrome_is_not_live as leftover_coach_turn_chrome_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_evaluation_headline_is_not_live as leftover_evaluation_headline_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_first_look_headline_is_not_live as leftover_first_look_headline_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_formal_plan_identity_labels as leftover_formal_plan_identity_labels,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_formal_plan_is_live_for_fill as leftover_formal_plan_is_live_for_fill,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_formal_training_labels as leftover_formal_training_labels,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_frozen_plan_blocks_generation as leftover_frozen_plan_blocks_generation,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_minting_suggested_actions_are_not_live as leftover_minting_suggested_actions_are_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_resource_library_list_is_not_live as leftover_resource_library_list_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_resource_sandbox_preview_is_not_live as leftover_resource_sandbox_preview_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_resource_sandbox_state_is_not_live as leftover_resource_sandbox_state_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_resource_selected_detail_is_not_live as leftover_resource_selected_detail_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_settings_learner_project_onboarding_is_not_live as leftover_settings_learner_project_onboarding_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_settings_profile_rhythm_is_not_live as leftover_settings_profile_rhythm_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_streaming_checkpoint_is_not_live as leftover_streaming_checkpoint_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_suggested_actions_is_not_live as leftover_suggested_actions_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_task_guide_focus_is_not_live as leftover_task_guide_focus_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_training_focus_chrome_is_not_live as leftover_training_focus_chrome_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_training_handoff_chrome_is_not_live as leftover_training_handoff_chrome_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_transfer_skill_has_real_multi_scene_proof as leftover_transfer_skill_has_real_multi_scene_proof,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    leftover_transfer_skill_is_not_live as leftover_transfer_skill_is_not_live,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    live_coach_focus_area as live_coach_focus_area,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    live_coach_stage_label as live_coach_stage_label,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    live_evidence_binding as live_evidence_binding,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    live_plan_artifact_stage_chrome as live_plan_artifact_stage_chrome,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    live_plan_blocked_reason as live_plan_blocked_reason,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    live_plan_current_step_fill as live_plan_current_step_fill,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    live_plan_next_after_current as live_plan_next_after_current,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    live_plan_overlay_fields as live_plan_overlay_fields,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    live_plan_refresh_step_why as live_plan_refresh_step_why,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    live_plan_update_persist_chrome as live_plan_update_persist_chrome,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    live_training_mint_anchors as live_training_mint_anchors,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    normalize_plan_runtime_recovery as normalize_plan_runtime_recovery,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    prefer_recovered_coach_turn_chrome as prefer_recovered_coach_turn_chrome,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    prefer_recovered_training_focus_chrome as prefer_recovered_training_focus_chrome,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    prefer_recovered_training_handoff_chrome as prefer_recovered_training_handoff_chrome,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    prefer_recovered_transfer_skill as prefer_recovered_transfer_skill,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    resource_record_is_acknowledged_upload as resource_record_is_acknowledged_upload,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    stamp_workspace_scope as stamp_workspace_scope,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    strip_secrets as strip_secrets,
)
from .workspace_recovery_domains.plan_persist_chrome import (
    utc_now_iso as utc_now_iso,
)
from .workspace_recovery_domains.runtime_recovery import (
    _plan_identity_fields as _plan_identity_fields,
)
from .workspace_recovery_domains.runtime_recovery import (
    _plan_runtime_identity as _plan_runtime_identity,
)
from .workspace_recovery_domains.runtime_recovery import (
    _runtime_for_formal_plan_persist as _runtime_for_formal_plan_persist,
)
from .workspace_recovery_domains.runtime_recovery import (
    _runtime_still_on_formal_plan as _runtime_still_on_formal_plan,
)
from .workspace_recovery_domains.runtime_recovery import (
    _same_identity as _same_identity,
)
from .workspace_recovery_domains.runtime_recovery import (
    _structured_string_list as _structured_string_list,
)
from .workspace_recovery_domains.runtime_recovery import (
    _without_leftover_formal_identity as _without_leftover_formal_identity,
)
from .workspace_recovery_domains.runtime_recovery import (
    apply_live_training_mint_to_card as apply_live_training_mint_to_card,
)
from .workspace_recovery_domains.runtime_recovery import (
    apply_training_chrome_scope as apply_training_chrome_scope,
)
from .workspace_recovery_domains.runtime_recovery import (
    bind_explicit_generated_plan_runtime as bind_explicit_generated_plan_runtime,
)
from .workspace_recovery_domains.runtime_recovery import (
    build_plan_runtime_recovery as build_plan_runtime_recovery,
)
from .workspace_recovery_domains.runtime_recovery import (
    build_streaming_checkpoint as build_streaming_checkpoint,
)
from .workspace_recovery_domains.runtime_recovery import (
    coach_focus_runtime_from_snapshot as coach_focus_runtime_from_snapshot,
)
from .workspace_recovery_domains.runtime_recovery import (
    evidence_bound_to_runtime_step as evidence_bound_to_runtime_step,
)
from .workspace_recovery_domains.runtime_recovery import (
    evidence_item_concepts as evidence_item_concepts,
)
from .workspace_recovery_domains.runtime_recovery import (
    evidence_item_workspace_id as evidence_item_workspace_id,
)
from .workspace_recovery_domains.runtime_recovery import (
    is_current_for_provider as is_current_for_provider,
)
from .workspace_recovery_domains.runtime_recovery import (
    is_current_for_workspace as is_current_for_workspace,
)
from .workspace_recovery_domains.runtime_recovery import (
    is_interrupted_streaming_checkpoint as is_interrupted_streaming_checkpoint,
)
from .workspace_recovery_domains.runtime_recovery import (
    live_runtime_frozen as live_runtime_frozen,
)
from .workspace_recovery_domains.runtime_recovery import (
    live_runtime_next_text as live_runtime_next_text,
)
from .workspace_recovery_domains.runtime_recovery import (
    live_runtime_next_verify_method as live_runtime_next_verify_method,
)
from .workspace_recovery_domains.runtime_recovery import (
    live_runtime_plan_id as live_runtime_plan_id,
)
from .workspace_recovery_domains.runtime_recovery import (
    normalize_formal_plan_identity as normalize_formal_plan_identity,
)
from .workspace_recovery_domains.runtime_recovery import (
    normalize_provider_capability_recovery as normalize_provider_capability_recovery,
)
from .workspace_recovery_domains.runtime_recovery import (
    normalize_streaming_checkpoint as normalize_streaming_checkpoint,
)
from .workspace_recovery_domains.runtime_recovery import (
    normalize_training_chrome as normalize_training_chrome,
)
from .workspace_recovery_domains.runtime_recovery import (
    overlay_plan_runtime_current_stage as overlay_plan_runtime_current_stage,
)
from .workspace_recovery_domains.runtime_recovery import (
    overlay_plan_runtime_display_facts as overlay_plan_runtime_display_facts,
)
from .workspace_recovery_domains.runtime_recovery import (
    recover_streaming_checkpoint_after_restart as recover_streaming_checkpoint_after_restart,
)
from .workspace_recovery_domains.runtime_recovery import (
    scope_evidence_items_to_workspace as scope_evidence_items_to_workspace,
)
from .workspace_recovery_domains.runtime_recovery import (
    scope_evidence_queue_to_runtime_step as scope_evidence_queue_to_runtime_step,
)
from .workspace_recovery_domains.runtime_recovery import (
    select_plan_runtime_for_pressure as select_plan_runtime_for_pressure,
)
from .workspace_recovery_domains.runtime_recovery import (
    select_plan_runtime_for_scope as select_plan_runtime_for_scope,
)
from .workspace_recovery_domains.runtime_recovery import (
    select_resources_for_scope as select_resources_for_scope,
)
from .workspace_recovery_domains.runtime_recovery import (
    select_training_chrome_for_scope as select_training_chrome_for_scope,
)
from .workspace_recovery_domains.runtime_recovery import (
    select_training_record_for_scope as select_training_record_for_scope,
)
from .workspace_recovery_domains.runtime_recovery import (
    stamp_produced_workspace_record as stamp_produced_workspace_record,
)
from .workspace_recovery_domains.runtime_recovery import (
    training_record_matches_workspace as training_record_matches_workspace,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _MEMORY_LIVE_TEXT_KEYS as _MEMORY_LIVE_TEXT_KEYS,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _REVIEW_ARTIFACT_LIVE_TEXT_KEYS as _REVIEW_ARTIFACT_LIVE_TEXT_KEYS,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _SCENARIO_LAB_LIVE_LIST_KEYS as _SCENARIO_LAB_LIVE_LIST_KEYS,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _SCENARIO_LAB_LIVE_TEXT_KEYS as _SCENARIO_LAB_LIVE_TEXT_KEYS,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _THEORY_DRILL_LIVE_TEXT_KEYS as _THEORY_DRILL_LIVE_TEXT_KEYS,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _THEORY_DRILL_QUESTION_LIVE_TEXT_KEYS as _THEORY_DRILL_QUESTION_LIVE_TEXT_KEYS,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _TRAINING_CARD_LIVE_LIST_KEYS as _TRAINING_CARD_LIVE_LIST_KEYS,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _TRAINING_CARD_LIVE_TEXT_KEYS as _TRAINING_CARD_LIVE_TEXT_KEYS,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_embedded_texts as _gate_embedded_texts,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_flash_deck_payload as _gate_flash_deck_payload,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_memory_thread_fields as _gate_memory_thread_fields,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_record_list_fields as _gate_record_list_fields,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_record_title_fields as _gate_record_title_fields,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_review_artifact_history as _gate_review_artifact_history,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_review_artifact_payload as _gate_review_artifact_payload,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_scenario_lab_history as _gate_scenario_lab_history,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_scenario_lab_payload as _gate_scenario_lab_payload,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_theory_drill_history as _gate_theory_drill_history,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_theory_drill_payload as _gate_theory_drill_payload,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_theory_drill_question as _gate_theory_drill_question,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _gate_training_card_payload as _gate_training_card_payload,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    _replace_leftover_live_text as _replace_leftover_live_text,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_coaching_next_step as live_coaching_next_step,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_language_detection_hint as live_language_detection_hint,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_leftover_focus_candidate as live_leftover_focus_candidate,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_memory_snapshot_overlay as live_memory_snapshot_overlay,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_plan_lane_copy as live_plan_lane_copy,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_plan_mismatch_candidate_plan_id as live_plan_mismatch_candidate_plan_id,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_plan_mismatch_candidate_step as live_plan_mismatch_candidate_step,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_plan_snapshot_persist_chrome as live_plan_snapshot_persist_chrome,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_plan_update_heading as live_plan_update_heading,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_runtime_stage_id as live_runtime_stage_id,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_task_clean_step_candidates as live_task_clean_step_candidates,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_task_converted_copy as live_task_converted_copy,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_task_focus_area as live_task_focus_area,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_task_heading as live_task_heading,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_task_label as live_task_label,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_task_next_action as live_task_next_action,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_task_picked_copy as live_task_picked_copy,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_task_suggested_reason as live_task_suggested_reason,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_task_suggested_title as live_task_suggested_title,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_task_thin_slice_copy as live_task_thin_slice_copy,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_task_training_concepts as live_task_training_concepts,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_training_card_title as live_training_card_title,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_training_lane_copy as live_training_lane_copy,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_training_open_copy as live_training_open_copy,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_training_persist_chrome as live_training_persist_chrome,
)
from .workspace_recovery_domains.snapshot_and_overlay import (
    live_training_why_this_card as live_training_why_this_card,
)
