from __future__ import annotations

from .prompt_domains.messages_and_turn_signals import (
    _build_learner_context_block as _build_learner_context_block,
)
from .prompt_domains.messages_and_turn_signals import (
    _build_turn_contract_block as _build_turn_contract_block,
)
from .prompt_domains.messages_and_turn_signals import (
    _coaching_history_mode as _coaching_history_mode,
)
from .prompt_domains.messages_and_turn_signals import (
    _coerce_due_reviews as _coerce_due_reviews,
)
from .prompt_domains.messages_and_turn_signals import (
    _coerce_resource_sequence_guidance as _coerce_resource_sequence_guidance,
)
from .prompt_domains.messages_and_turn_signals import (
    _coerce_str_list as _coerce_str_list,
)
from .prompt_domains.messages_and_turn_signals import (
    _extract_next_step_hint_text as _extract_next_step_hint_text,
)
from .prompt_domains.messages_and_turn_signals import (
    _first_str as _first_str,
)
from .prompt_domains.messages_and_turn_signals import (
    _first_value as _first_value,
)
from .prompt_domains.messages_and_turn_signals import (
    _format_due_review_item as _format_due_review_item,
)
from .prompt_domains.messages_and_turn_signals import (
    _function_guidance_prompt_inputs as _function_guidance_prompt_inputs,
)
from .prompt_domains.messages_and_turn_signals import (
    _has_execution_ready_next_step_request as _has_execution_ready_next_step_request,
)
from .prompt_domains.messages_and_turn_signals import (
    _language_instruction as _language_instruction,
)
from .prompt_domains.messages_and_turn_signals import (
    _library_analysis_system_prompt as _library_analysis_system_prompt,
)
from .prompt_domains.messages_and_turn_signals import (
    _looks_like_first_turn as _looks_like_first_turn,
)
from .prompt_domains.messages_and_turn_signals import (
    _nested_get as _nested_get,
)
from .prompt_domains.messages_and_turn_signals import (
    build_static_coaching_prefix as build_static_coaching_prefix,
)
from .prompt_domains.messages_and_turn_signals import (
    infer_coaching_scenario as infer_coaching_scenario,
)
from .prompt_domains.messages_and_turn_signals import (
    infer_learner_signal as infer_learner_signal,
)
from .prompt_domains.scenario_and_context_blocks import (
    _build_context_block as _build_context_block,
)
from .prompt_domains.scenario_and_context_blocks import (
    _build_function_guidance_starter_block as _build_function_guidance_starter_block,
)
from .prompt_domains.scenario_and_context_blocks import (
    _build_resource_sequence_block as _build_resource_sequence_block,
)
from .prompt_domains.scenario_and_context_blocks import (
    _coerce_requested_resources as _coerce_requested_resources,
)
from .prompt_domains.scenario_and_context_blocks import (
    _format_requested_resource as _format_requested_resource,
)
from .prompt_domains.scenario_and_context_blocks import (
    build_coaching_messages as build_coaching_messages,
)
from .prompt_domains.scenario_and_context_blocks import (
    build_coaching_system_prompt as build_coaching_system_prompt,
)
from .prompt_domains.scenario_and_context_blocks import (
    extract_coaching_context as extract_coaching_context,
)
from .prompt_domains.templates_and_system import (
    _FRESH_LANE_STALE_CONTEXT_KEYS as _FRESH_LANE_STALE_CONTEXT_KEYS,
)
from .prompt_domains.templates_and_system import (
    _HISTORY_TRUNCATION_MARKER as _HISTORY_TRUNCATION_MARKER,
)
from .prompt_domains.templates_and_system import (
    _RETHINKFUN_LECTURE_MARKERS as _RETHINKFUN_LECTURE_MARKERS,
)
from .prompt_domains.templates_and_system import (
    CARD_FLASH_SYSTEM as CARD_FLASH_SYSTEM,
)
from .prompt_domains.templates_and_system import (
    CARD_PRACTICE_SYSTEM as CARD_PRACTICE_SYSTEM,
)
from .prompt_domains.templates_and_system import (
    COACHING_SYSTEM_TEMPLATE as COACHING_SYSTEM_TEMPLATE,
)
from .prompt_domains.templates_and_system import (
    DEFAULT_COACHING_HISTORY_TOKEN_BUDGET as DEFAULT_COACHING_HISTORY_TOKEN_BUDGET,
)
from .prompt_domains.templates_and_system import (
    MINIMAL_COACHING_SYSTEM_TEMPLATE as MINIMAL_COACHING_SYSTEM_TEMPLATE,
)
from .prompt_domains.templates_and_system import (
    _agent_loop_core_instructions as _agent_loop_core_instructions,
)
from .prompt_domains.templates_and_system import (
    _agent_loop_lane_skill_suffix as _agent_loop_lane_skill_suffix,
)
from .prompt_domains.templates_and_system import (
    _agent_loop_library_instructions as _agent_loop_library_instructions,
)
from .prompt_domains.templates_and_system import (
    _agent_loop_plan_instructions as _agent_loop_plan_instructions,
)
from .prompt_domains.templates_and_system import (
    _agent_loop_skill_instructions as _agent_loop_skill_instructions,
)
from .prompt_domains.templates_and_system import (
    _agent_loop_training_instructions as _agent_loop_training_instructions,
)
from .prompt_domains.templates_and_system import (
    _answer_policy_instruction as _answer_policy_instruction,
)
from .prompt_domains.templates_and_system import (
    _answer_policy_label as _answer_policy_label,
)
from .prompt_domains.templates_and_system import (
    _append_depth_clauses as _append_depth_clauses,
)
from .prompt_domains.templates_and_system import (
    _attached_material_grounding as _attached_material_grounding,
)
from .prompt_domains.templates_and_system import (
    _budget_coaching_history as _budget_coaching_history,
)
from .prompt_domains.templates_and_system import (
    _build_active_thread_block as _build_active_thread_block,
)
from .prompt_domains.templates_and_system import (
    _build_resource_composer_boundary as _build_resource_composer_boundary,
)
from .prompt_domains.templates_and_system import (
    _build_state_driven_teaching_block as _build_state_driven_teaching_block,
)
from .prompt_domains.templates_and_system import (
    _build_tone_adaptation_block as _build_tone_adaptation_block,
)
from .prompt_domains.templates_and_system import (
    _coaching_history_token_units as _coaching_history_token_units,
)
from .prompt_domains.templates_and_system import (
    _coerce_resource_composer_intent as _coerce_resource_composer_intent,
)
from .prompt_domains.templates_and_system import (
    _compact_list as _compact_list,
)
from .prompt_domains.templates_and_system import (
    _compact_text as _compact_text,
)
from .prompt_domains.templates_and_system import (
    _estimate_coaching_history_tokens as _estimate_coaching_history_tokens,
)
from .prompt_domains.templates_and_system import (
    _filter_function_guidance_entry_points as _filter_function_guidance_entry_points,
)
from .prompt_domains.templates_and_system import (
    _first_external_reference_summary as _first_external_reference_summary,
)
from .prompt_domains.templates_and_system import (
    _first_learning_outcome_summary as _first_learning_outcome_summary,
)
from .prompt_domains.templates_and_system import (
    _first_project_idea_summary as _first_project_idea_summary,
)
from .prompt_domains.templates_and_system import (
    _first_project_source_summary as _first_project_source_summary,
)
from .prompt_domains.templates_and_system import (
    _growth_loop_honesty_block as _growth_loop_honesty_block,
)
from .prompt_domains.templates_and_system import (
    _guided_mode_requirements as _guided_mode_requirements,
)
from .prompt_domains.templates_and_system import (
    _is_rethinkfun_lecture_request as _is_rethinkfun_lecture_request,
)
from .prompt_domains.templates_and_system import (
    _join_clauses as _join_clauses,
)
from .prompt_domains.templates_and_system import (
    _message_explicitly_requests_resource_search as _message_explicitly_requests_resource_search,
)
from .prompt_domains.templates_and_system import (
    _pedagogy_mode_instruction as _pedagogy_mode_instruction,
)
from .prompt_domains.templates_and_system import (
    _prioritize_current_request_context as _prioritize_current_request_context,
)
from .prompt_domains.templates_and_system import (
    _prompt_visible_teaching_mode as _prompt_visible_teaching_mode,
)
from .prompt_domains.templates_and_system import (
    _resolve_pedagogy_mode as _resolve_pedagogy_mode,
)
from .prompt_domains.templates_and_system import (
    _resource_composer_focus as _resource_composer_focus,
)
from .prompt_domains.templates_and_system import (
    _resource_composer_mode as _resource_composer_mode,
)
from .prompt_domains.templates_and_system import (
    _take_history_text_within_budget as _take_history_text_within_budget,
)
from .prompt_domains.templates_and_system import (
    _teaching_style_instruction as _teaching_style_instruction,
)
from .prompt_domains.templates_and_system import (
    _teaching_style_label as _teaching_style_label,
)
from .prompt_domains.templates_and_system import (
    _truncate_coaching_history_content as _truncate_coaching_history_content,
)
from .prompt_domains.templates_and_system import (
    active_view_guidance as active_view_guidance,
)
from .prompt_domains.templates_and_system import (
    active_view_label as active_view_label,
)
from .prompt_domains.templates_and_system import (
    coaching_scenario_label as coaching_scenario_label,
)
from .prompt_domains.templates_and_system import (
    first_look_recommended_next_from_context as first_look_recommended_next_from_context,
)
from .prompt_domains.templates_and_system import (
    learner_signal_label as learner_signal_label,
)
from .prompt_domains.templates_and_system import (
    normalize_answer_policy as normalize_answer_policy,
)
from .prompt_domains.templates_and_system import (
    resolve_smart_history_budget as resolve_smart_history_budget,
)
