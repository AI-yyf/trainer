from __future__ import annotations

from typing import Any

from ...core.models import UserProfile
from ..library_practice import library_analysis_question, library_practice_requested
from .messages_and_turn_signals import (
    _build_learner_context_block,
    _build_turn_contract_block,
    _coerce_due_reviews,
    _coerce_resource_sequence_guidance,
    _coerce_str_list,
    _extract_next_step_hint_text,
    _first_str,
    _first_value,
    _format_due_review_item,
    _function_guidance_prompt_inputs,
    _has_execution_ready_next_step_request,
    _library_analysis_system_prompt,
    _looks_like_first_turn,
    _nested_get,
    build_static_coaching_prefix,
    infer_coaching_scenario,
    infer_learner_signal,
)
from .templates_and_system import (
    DEFAULT_COACHING_HISTORY_TOKEN_BUDGET,
    _agent_loop_lane_skill_suffix,
    _append_depth_clauses,
    _attached_material_grounding,
    _budget_coaching_history,
    _build_active_thread_block,
    _build_resource_composer_boundary,
    _build_state_driven_teaching_block,
    _build_tone_adaptation_block,
    _coerce_resource_composer_intent,
    _compact_list,
    _compact_text,
    _estimate_coaching_history_tokens,
    _filter_function_guidance_entry_points,
    _first_external_reference_summary,
    _first_learning_outcome_summary,
    _first_project_idea_summary,
    _first_project_source_summary,
    _growth_loop_honesty_block,
    _is_rethinkfun_lecture_request,
    _join_clauses,
    _pedagogy_mode_instruction,
    _prioritize_current_request_context,
    _prompt_visible_teaching_mode,
    _resolve_pedagogy_mode,
    _resource_composer_focus,
    _resource_composer_mode,
    _truncate_coaching_history_content,
    active_view_guidance,
    active_view_label,
    coaching_scenario_label,
    first_look_recommended_next_from_context,
    learner_signal_label,
)


def _build_context_block(context: dict[str, Any]) -> str:
    scenario = coaching_scenario_label(str(context.get("scenario", "idea_implementation")))
    signal = learner_signal_label(str(context.get("learner_signal", "steady")))
    lines: list[str] = [f"- Main lane: {scenario}. Learner signal: {signal}."]
    active_view = _compact_text(context.get("active_view"), 24)
    if active_view:
        lines.append(
            f"- Input surface: {active_view_label(active_view)}. {active_view_guidance(active_view)}"
        )
    recovery = context.get("plan_runtime_recovery")
    if isinstance(recovery, dict) and recovery.get("recovered") is True:
        recovered_step = _compact_text(recovery.get("current_step"), 120)
        recovered_blocker = _compact_text(recovery.get("blocked_reason"), 140)
        recovered_action = _compact_text(recovery.get("action"), 32)
        recovery_clauses: list[str] = ["Resume recovered plan runtime. Do not invent a formal plan."]
        if recovered_action:
            recovery_clauses.append(f"Action: {recovered_action}.")
        if recovered_step:
            recovery_clauses.append(f"Recovered step: {recovered_step}.")
        if recovered_blocker:
            recovery_clauses.append(f"Recovered blocker: {recovered_blocker}.")
        recovery_line = _join_clauses(*recovery_clauses)
        if recovery_line:
            lines.append(f"- {recovery_line}")

    resource_composer_mode = _resource_composer_mode(context)
    if resource_composer_mode:
        lines.append(f"- Resource task: {_resource_composer_focus(resource_composer_mode)}.")

    current_focus = _compact_text(context.get("current_focus"), 120)
    continuity_summary = _compact_text(context.get("continuity_summary"), 140)
    thread_clauses: list[str] = []
    if current_focus:
        thread_clauses.append(f"Stay with {current_focus}.")
    if continuity_summary:
        thread_clauses.append(f"Continuity thread: {continuity_summary}.")
    thread_line = _join_clauses(*thread_clauses)
    if thread_line:
        lines.append(f"- {thread_line}")

    teaching_decision = context.get("teaching_decision")
    coaching_adaptation = context.get("coaching_adaptation")
    tone_decision = context.get("tone_decision")
    learner_state = context.get("learner_state")
    coaching_bias_clauses: list[str] = []
    if isinstance(teaching_decision, dict):
        mode = _prompt_visible_teaching_mode(context)
        primary_goal = _compact_text(teaching_decision.get("primary_goal"), 110)
        reason = _compact_text(teaching_decision.get("reason"), 120)
        if mode:
            coaching_bias_clauses.append(f"Teaching mode: {mode}.")
        if primary_goal:
            coaching_bias_clauses.append(f"Primary teaching goal: {primary_goal}.")
        if reason:
            coaching_bias_clauses.append(f"Why this fits: {reason}.")
        _append_depth_clauses(teaching_decision, coaching_bias_clauses)
    if isinstance(coaching_adaptation, dict):
        adaptation_summary = _compact_text(coaching_adaptation.get("summary"), 140)
        if adaptation_summary:
            coaching_bias_clauses.append(f"Adaptation bias: {adaptation_summary}.")
    if isinstance(tone_decision, dict):
        tone = _compact_text(tone_decision.get("tone"), 32)
        verbosity = _compact_text(tone_decision.get("verbosity_bias"), 32)
        if tone or verbosity:
            coaching_bias_clauses.append(
                f"Keep the tone {tone or 'steady'} and verbosity {verbosity or 'medium'}."
            )
        if tone_decision.get("avoid_overwhelm"):
            coaching_bias_clauses.append("Keep cognitive load low.")
    if isinstance(learner_state, dict):
        confidence = learner_state.get("current_confidence")
        frustration = learner_state.get("frustration_level")
        if isinstance(confidence, (int, float)) or isinstance(frustration, (int, float)):
            coaching_bias_clauses.append(
                f"Confidence / frustration: {confidence or 0} / {frustration or 0}."
            )
        if learner_state.get("needs_rescue"):
            coaching_bias_clauses.append("Bias toward rescue over breadth.")
        if learner_state.get("needs_review"):
            coaching_bias_clauses.append("Expect a follow-up review loop.")
    coaching_bias_line = _join_clauses(*coaching_bias_clauses)
    if coaching_bias_line:
        lines.append(f"- {coaching_bias_line}")

    summary = _compact_text(context.get("summary"), 140)
    recent_wins = _compact_list(context.get("recent_wins"), 1)
    weak_spots = _compact_list(context.get("weak_spots"), 2)
    recalled_memory_summary = _compact_text(context.get("recalled_memory_summary"), 140)
    memory_evidence = _compact_list(context.get("memory_evidence"), 2)
    memory_clauses: list[str] = []
    if summary:
        memory_clauses.append(f"Recent memory summary: {summary}.")
    if recent_wins:
        memory_clauses.append(f"Recent win to preserve: {recent_wins[0]}.")
    if weak_spots:
        memory_clauses.append(f"Pattern to watch: {'; '.join(weak_spots)}.")
    if recalled_memory_summary:
        memory_clauses.append(f"Useful recalled memory: {recalled_memory_summary}.")
    if memory_evidence:
        memory_clauses.append(f"Continuity evidence: {'; '.join(memory_evidence)}.")
    memory_line = _join_clauses(*memory_clauses)
    if memory_line:
        lines.append(f"- {memory_line}")

    review_rhythm = _compact_text(context.get("review_rhythm"), 120)
    due_reviews = context.get("due_reviews") or []
    next_review_due = _compact_text(context.get("next_review_due"), 72)
    review_queue_summary = _compact_text(context.get("review_queue_summary"), 120)
    pace_signal = _compact_text(context.get("pace_signal"), 48)
    review_clauses: list[str] = []
    if review_rhythm:
        review_clauses.append(f"Review rhythm: {review_rhythm}.")
    if isinstance(due_reviews, list) and due_reviews:
        due_text = "; ".join(_format_due_review_item(item) for item in due_reviews[:2])
        if due_text:
            review_clauses.append(f"Due review points: {due_text}.")
    if review_queue_summary:
        review_clauses.append(f"Review queue: {review_queue_summary}.")
    if next_review_due:
        review_clauses.append(f"Next review due: {next_review_due}.")
    if pace_signal:
        review_clauses.append(f"Pace signal: {pace_signal}.")
    review_line = _join_clauses(*review_clauses)
    if review_line:
        lines.append(f"- {review_line}")

    grounding_clauses: list[str] = []
    requested_resource_summary = _compact_text(context.get("requested_resource_summary"), 120)
    if requested_resource_summary:
        grounding_clauses.append(f"Requested grounding: {requested_resource_summary}.")
    resource_fragments = context.get("resource_fragments")
    if isinstance(resource_fragments, list) and resource_fragments:
        evidence_lines: list[str] = []
        for item in resource_fragments[:4]:
            if not isinstance(item, dict):
                continue
            resource_id = _compact_text(item.get("resource_id") or item.get("id"), 80)
            title = _compact_text(item.get("title") or resource_id or "resource", 100)
            snippet = _compact_text(
                item.get("snippet") or item.get("summary") or item.get("evidence_summary"),
                260,
            )
            if not snippet:
                continue
            label = f"{title} ({resource_id})" if resource_id else title
            evidence_lines.append(f"{label}: {snippet}")
        if evidence_lines:
            grounding_clauses.append(
                "Prepared library evidence: " + " | ".join(evidence_lines)
            )
    else:
        requested_resource_ids = _compact_list(context.get("requested_resource_ids"), 4)
        if requested_resource_ids:
            grounding_clauses.append(
                f"Prepared resource IDs: {', '.join(requested_resource_ids)}. Search them before making claims."
            )
    resource_question_facets = _compact_list(context.get("resource_question_facets"), 4)
    if resource_question_facets:
        grounding_clauses.append(f"Requested resource facets: {'; '.join(resource_question_facets)}.")
    teaching_asset_summary = _compact_text(context.get("teaching_asset_summary"), 120)
    if teaching_asset_summary:
        grounding_clauses.append(f"Preferred teaching asset: {teaching_asset_summary}.")
    background_reference_summary = _compact_text(context.get("background_reference_summary"), 120)
    if background_reference_summary:
        grounding_clauses.append(f"Background research summary: {background_reference_summary}.")
    reference_summary = _first_external_reference_summary(context)
    if reference_summary:
        grounding_clauses.append(f"One useful reference: {reference_summary}.")
    grounding_line = _join_clauses(*grounding_clauses)
    if grounding_line:
        lines.append(f"- {grounding_line}")

    execution_clauses: list[str] = []
    failing_checks = _compact_list(context.get("failing_checks"), 3)
    if failing_checks:
        execution_clauses.append(f"Reduce these failing checks first: {'; '.join(failing_checks)}.")
    next_step_hint = _compact_text(_extract_next_step_hint_text(context.get("next_step_hint")), 110)
    if next_step_hint:
        execution_clauses.append(f"Prior next-step hint: {next_step_hint}.")
    implementation_guide = context.get("implementation_guide")
    if isinstance(implementation_guide, dict):
        current_step = _compact_text(implementation_guide.get("current_step"), 120)
        scope_boundary = _compact_text(implementation_guide.get("scope_boundary"), 120)
        validation = implementation_guide.get("validation_strategy")
        validation_items = _compact_list(validation, 2)
        if current_step:
            execution_clauses.append(f"Implementation anchor: {current_step}.")
        if scope_boundary:
            execution_clauses.append(f"Scope boundary: {scope_boundary}.")
        if validation_items:
            execution_clauses.append(f"Verification anchor: {'; '.join(validation_items)}.")
    project_entry_points = _compact_list(context.get("project_entry_points"), 3)
    if project_entry_points:
        execution_clauses.append(f"Code entry points to name: {'; '.join(project_entry_points)}.")
    project_summary = _compact_text(context.get("project_summary"), 120)
    if project_summary:
        execution_clauses.append(f"Project summary: {project_summary}.")
    function_guidance_starter = context.get("function_guidance_starter")
    if isinstance(function_guidance_starter, dict):
        starter_call_site = _compact_text(function_guidance_starter.get("call_site_path"), 110)
        starter_definition = _compact_text(function_guidance_starter.get("definition_path"), 110)
        starter_boundary = _compact_text(function_guidance_starter.get("boundary_note"), 140)
        starter_instruction = _compact_text(function_guidance_starter.get("coach_instruction"), 140)
        starter_clauses: list[str] = []
        if starter_call_site or starter_definition:
            starter_clauses.append(
                "Trainer sandbox starter: "
                f"begin in {starter_call_site or 'the prepared call site'}"
                + (
                    f", then jump to {starter_definition}."
                    if starter_definition
                    else "."
                )
            )
        if starter_instruction:
            starter_clauses.append(starter_instruction)
        if starter_boundary:
            starter_clauses.append(f"Boundary note: {starter_boundary}.")
        execution_clauses.extend(starter_clauses)
    project_idea_summary = _first_project_idea_summary(context)
    if project_idea_summary:
        execution_clauses.append(f"Project idea worth reusing: {project_idea_summary}.")
    project_source_summary = _first_project_source_summary(context)
    if project_source_summary:
        execution_clauses.append(f"Project source angle: {project_source_summary}.")
    adaptation_guide = context.get("project_adaptation_guide") or context.get("adaptation_guide")
    if isinstance(adaptation_guide, dict):
        first_migration_step = _compact_text(adaptation_guide.get("first_migration_step"), 120)
        if first_migration_step:
            execution_clauses.append(f"Adaptation anchor: {first_migration_step}.")
    principle_notes = context.get("principle_notes") or context.get("principle_note")
    if isinstance(principle_notes, dict):
        current_principle = _compact_text(principle_notes.get("current_principle"), 96)
        apply_now = _compact_text(principle_notes.get("apply_now"), 110)
        why_it_matters = _compact_text(principle_notes.get("why_it_matters"), 110)
        if current_principle:
            execution_clauses.append(f"Principle anchor: {current_principle}.")
        if apply_now:
            execution_clauses.append(f"Apply-now move: {apply_now}.")
        if why_it_matters:
            execution_clauses.append(f"Why it matters: {why_it_matters}.")
    exercise_prompt = context.get("exercise_prompt")
    if isinstance(exercise_prompt, dict):
        prompt = _compact_text(exercise_prompt.get("prompt"), 110)
        success_signal = _compact_text(exercise_prompt.get("success_signal"), 110)
        fallback_step = _compact_text(exercise_prompt.get("fallback_step"), 110)
        if prompt:
            execution_clauses.append(f"Exercise prompt: {prompt}.")
        if success_signal:
            execution_clauses.append(f"Success signal: {success_signal}.")
        if fallback_step:
            execution_clauses.append(f"Fallback step: {fallback_step}.")
    learning_outcome_summary = _first_learning_outcome_summary(context)
    if learning_outcome_summary:
        execution_clauses.append(learning_outcome_summary)
    selection_range = _compact_text(context.get("selection_range"), 48)
    selection_text = _compact_text(context.get("selection_text"), 140)
    diagnostics_count = context.get("diagnostics_count")
    if scenario == "function_guidance" and (selection_text or context.get("file_path")):
        execution_clauses.append(
            "Use the attached current file or selection as the first live function anchor before asking for another call site."
        )
    if scenario == "remote_workspace" and context.get("execution_ready"):
        execution_clauses.append(
            "Teach the remote boundary first, then end with one minimal verification move before asking for more setup detail."
        )
    if selection_range:
        execution_clauses.append(f"Selection attached: {selection_range}.")
    if diagnostics_count:
        execution_clauses.append(f"Diagnostics attached: {diagnostics_count}.")
    execution_line = _join_clauses(*execution_clauses)
    if execution_line:
        lines.append(f"- {execution_line}")

    return "\n".join(lines)


def _coerce_requested_resources(value: object | None) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    results: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = _first_str(item.get("title"), item.get("name"), item.get("id")) or "resource"
        kind = _first_str(item.get("kind")) or "resource"
        summary = _first_str(item.get("summary")) or ""
        source = _first_str(item.get("source")) or ""
        trust_score = _first_str(item.get("trust_score")) or ""
        freshness = _first_str(item.get("freshness")) or ""
        results.append(
            {
                "title": title,
                "kind": kind,
                "summary": summary,
                "source": source,
                "trust_score": trust_score,
                "freshness": freshness,
            }
        )
    return results


def extract_coaching_context(
    message: str | None,
    current_file: dict[str, object] | None = None,
    coach_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenario = infer_coaching_scenario(message or "", current_file, coach_context)
    learner_signal = infer_learner_signal(message or "", current_file, coach_context)
    current_focus = _first_str(
        _nested_get(coach_context, "current_focus") if coach_context else None,
        _nested_get(coach_context, "coach_context", "current_focus") if coach_context else None,
        _nested_get(coach_context, "memory", "current_focus") if coach_context else None,
        _nested_get(current_file, "current_focus"),
        _nested_get(current_file, "coach_context", "current_focus"),
        _nested_get(current_file, "memory", "current_focus"),
    )
    recent_wins = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "recent_wins") if coach_context else None,
            _nested_get(coach_context, "coach_context", "recent_wins") if coach_context else None,
            _nested_get(coach_context, "memory", "recent_wins") if coach_context else None,
            _nested_get(current_file, "recent_wins"),
            _nested_get(current_file, "coach_context", "recent_wins"),
            _nested_get(current_file, "memory", "recent_wins"),
        )
    )
    weak_spots = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "weak_spots") if coach_context else None,
            _nested_get(coach_context, "weaknesses") if coach_context else None,
            _nested_get(coach_context, "coach_context", "weak_spots") if coach_context else None,
            _nested_get(coach_context, "memory", "weak_spots") if coach_context else None,
            _nested_get(coach_context, "memory", "weaknesses") if coach_context else None,
            _nested_get(current_file, "weak_spots"),
            _nested_get(current_file, "weaknesses"),
            _nested_get(current_file, "coach_context", "weak_spots"),
            _nested_get(current_file, "memory", "weak_spots"),
            _nested_get(current_file, "memory", "weaknesses"),
        )
    )
    due_reviews = _coerce_due_reviews(
        _first_value(
            _nested_get(coach_context, "due_reviews") if coach_context else None,
            _nested_get(coach_context, "coach_context", "due_reviews") if coach_context else None,
            _nested_get(coach_context, "memory", "due_reviews") if coach_context else None,
            _nested_get(current_file, "due_reviews"),
            _nested_get(current_file, "coach_context", "due_reviews"),
            _nested_get(current_file, "memory", "due_reviews"),
        )
    )
    requested_resources = _coerce_requested_resources(
        _first_value(
            _nested_get(coach_context, "requested_resources") if coach_context else None,
            _nested_get(coach_context, "coach_context", "requested_resources") if coach_context else None,
            _nested_get(current_file, "requested_resources"),
            _nested_get(current_file, "coach_context", "requested_resources"),
        )
    )
    resource_composer_intent = _coerce_resource_composer_intent(
        _first_value(
            _nested_get(coach_context, "resource_composer_intent") if coach_context else None,
            _nested_get(coach_context, "coach_context", "resource_composer_intent")
            if coach_context
            else None,
            _nested_get(current_file, "resource_composer_intent"),
            _nested_get(current_file, "coach_context", "resource_composer_intent"),
        )
    )
    requested_resource_summary = _first_str(
        _nested_get(coach_context, "requested_resource_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "requested_resource_summary") if coach_context else None,
        _nested_get(current_file, "requested_resource_summary"),
        _nested_get(current_file, "coach_context", "requested_resource_summary"),
    )
    resource_sequence_summary = _first_str(
        _nested_get(coach_context, "resource_sequence_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "resource_sequence_summary") if coach_context else None,
        _nested_get(current_file, "resource_sequence_summary"),
        _nested_get(current_file, "coach_context", "resource_sequence_summary"),
    )
    resource_sequence_guidance = _coerce_resource_sequence_guidance(
        _first_value(
            _nested_get(coach_context, "resource_sequence_guidance") if coach_context else None,
            _nested_get(coach_context, "coach_context", "resource_sequence_guidance")
            if coach_context
            else None,
            _nested_get(current_file, "resource_sequence_guidance"),
            _nested_get(current_file, "coach_context", "resource_sequence_guidance"),
        )
    )
    resource_question_facets = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "resource_question_facets") if coach_context else None,
            _nested_get(coach_context, "coach_context", "resource_question_facets")
            if coach_context
            else None,
            _nested_get(current_file, "resource_question_facets"),
            _nested_get(current_file, "coach_context", "resource_question_facets"),
        )
    )
    auto_resource_lookup = bool(
        _first_value(
            _nested_get(coach_context, "auto_resource_lookup") if coach_context else None,
            _nested_get(coach_context, "coach_context", "auto_resource_lookup") if coach_context else None,
            _nested_get(current_file, "auto_resource_lookup"),
            _nested_get(current_file, "coach_context", "auto_resource_lookup"),
        )
    )
    missing_resource_ids = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "missing_resource_ids") if coach_context else None,
            _nested_get(coach_context, "coach_context", "missing_resource_ids") if coach_context else None,
            _nested_get(current_file, "missing_resource_ids"),
            _nested_get(current_file, "coach_context", "missing_resource_ids"),
        )
    )
    teaching_observations = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "teaching_observations") if coach_context else None,
            _nested_get(coach_context, "coach_context", "teaching_observations") if coach_context else None,
            _nested_get(coach_context, "memory", "teaching_observations") if coach_context else None,
            _nested_get(current_file, "teaching_observations"),
            _nested_get(current_file, "coach_context", "teaching_observations"),
            _nested_get(current_file, "memory", "teaching_observations"),
        )
    )
    memory_evidence = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "memory_evidence") if coach_context else None,
            _nested_get(coach_context, "coach_context", "memory_evidence") if coach_context else None,
            _nested_get(current_file, "memory_evidence"),
            _nested_get(current_file, "coach_context", "memory_evidence"),
        )
    )
    teaching_assets = _first_value(
        _nested_get(coach_context, "selected_teaching_assets") if coach_context else None,
        _nested_get(coach_context, "coach_context", "selected_teaching_assets") if coach_context else None,
        _nested_get(coach_context, "teaching_assets") if coach_context else None,
        _nested_get(coach_context, "coach_context", "teaching_assets") if coach_context else None,
        _nested_get(coach_context, "memory", "teaching_assets") if coach_context else None,
        _nested_get(current_file, "selected_teaching_assets"),
        _nested_get(current_file, "coach_context", "selected_teaching_assets"),
        _nested_get(current_file, "teaching_assets"),
        _nested_get(current_file, "coach_context", "teaching_assets"),
    )
    recalled_coaching_memories = _first_value(
        _nested_get(coach_context, "recalled_coaching_memories") if coach_context else None,
        _nested_get(coach_context, "coach_context", "recalled_coaching_memories") if coach_context else None,
        _nested_get(current_file, "recalled_coaching_memories"),
        _nested_get(current_file, "coach_context", "recalled_coaching_memories"),
    )
    teaching_knowledge_catalog = _first_value(
        _nested_get(coach_context, "teaching_knowledge_catalog") if coach_context else None,
        _nested_get(coach_context, "coach_context", "teaching_knowledge_catalog") if coach_context else None,
        _nested_get(coach_context, "memory", "teaching_knowledge_catalog") if coach_context else None,
        _nested_get(current_file, "teaching_knowledge_catalog"),
        _nested_get(current_file, "coach_context", "teaching_knowledge_catalog"),
    )
    coaching_adaptation = _first_value(
        _nested_get(coach_context, "coaching_adaptation") if coach_context else None,
        _nested_get(coach_context, "coach_context", "coaching_adaptation") if coach_context else None,
        _nested_get(coach_context, "memory", "coaching_adaptation") if coach_context else None,
        _nested_get(current_file, "coaching_adaptation"),
        _nested_get(current_file, "coach_context", "coaching_adaptation"),
        _nested_get(current_file, "memory", "coaching_adaptation"),
    )
    review_rhythm = _first_str(
        _nested_get(coach_context, "review_rhythm") if coach_context else None,
        _nested_get(coach_context, "coach_context", "review_rhythm") if coach_context else None,
        _nested_get(coach_context, "memory", "review_rhythm") if coach_context else None,
        _nested_get(current_file, "review_rhythm"),
        _nested_get(current_file, "coach_context", "review_rhythm"),
        _nested_get(current_file, "memory", "review_rhythm"),
    )
    summary = _first_str(
        _nested_get(coach_context, "summary") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "summary") if coach_context else None,
        _nested_get(coach_context, "memory", "recent_summary") if coach_context else None,
        _nested_get(current_file, "summary"),
        _nested_get(current_file, "coaching_state", "summary"),
        _nested_get(current_file, "coach_context", "summary"),
        _nested_get(current_file, "memory", "recent_summary"),
    )
    next_step_hint = _first_str(
        _extract_next_step_hint_text(
            _nested_get(coach_context, "next_step_hint") if coach_context else None,
        ),
        _nested_get(coach_context, "next_step") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "next_step") if coach_context else None,
        _nested_get(coach_context, "coach_context", "next_step") if coach_context else None,
        _extract_next_step_hint_text(
            _nested_get(current_file, "next_step_hint") if current_file else None,
        ),
        _nested_get(current_file, "next_step"),
        _nested_get(current_file, "coaching_state", "next_step"),
        _nested_get(current_file, "coach_context", "next_step"),
    )
    encouragement = _first_str(
        _nested_get(coach_context, "encouragement") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "encouragement") if coach_context else None,
        _nested_get(coach_context, "coach_context", "encouragement") if coach_context else None,
        _nested_get(current_file, "encouragement"),
        _nested_get(current_file, "coaching_state", "encouragement"),
        _nested_get(current_file, "coach_context", "encouragement"),
    )
    active_thread = _first_value(
        _nested_get(coach_context, "active_thread") if coach_context else None,
        _nested_get(coach_context, "coach_context", "active_thread") if coach_context else None,
        _nested_get(current_file, "active_thread"),
        _nested_get(current_file, "coach_context", "active_thread"),
    )
    decision = _first_str(
        _nested_get(coach_context, "decision") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "decision") if coach_context else None,
        _nested_get(coach_context, "coach_context", "decision") if coach_context else None,
        _nested_get(current_file, "decision"),
        _nested_get(current_file, "coaching_state", "decision"),
        _nested_get(current_file, "coach_context", "decision"),
        _nested_get(active_thread, "decision") if isinstance(active_thread, dict) else None,
    )
    blocker = _first_str(
        _nested_get(coach_context, "blocker") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "blocker") if coach_context else None,
        _nested_get(coach_context, "coach_context", "blocker") if coach_context else None,
        _nested_get(current_file, "blocker"),
        _nested_get(current_file, "coaching_state", "blocker"),
        _nested_get(current_file, "coach_context", "blocker"),
        _nested_get(active_thread, "blocker") if isinstance(active_thread, dict) else None,
    )
    teaching_note = _first_str(
        _nested_get(coach_context, "teaching_note") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "teaching_note") if coach_context else None,
        _nested_get(coach_context, "coach_context", "teaching_note") if coach_context else None,
        _nested_get(current_file, "teaching_note"),
        _nested_get(current_file, "coaching_state", "teaching_note"),
        _nested_get(current_file, "coach_context", "teaching_note"),
        _nested_get(active_thread, "teaching_note") if isinstance(active_thread, dict) else None,
    )
    confidence = _first_str(
        _nested_get(coach_context, "confidence") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "confidence") if coach_context else None,
        _nested_get(coach_context, "coach_context", "confidence") if coach_context else None,
        _nested_get(current_file, "confidence"),
        _nested_get(current_file, "coaching_state", "confidence"),
        _nested_get(current_file, "coach_context", "confidence"),
        _nested_get(active_thread, "confidence") if isinstance(active_thread, dict) else None,
    )
    evidence = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "evidence") if coach_context else None,
            _nested_get(coach_context, "coaching_state", "evidence") if coach_context else None,
            _nested_get(coach_context, "coach_context", "evidence") if coach_context else None,
            _nested_get(current_file, "evidence"),
            _nested_get(current_file, "coaching_state", "evidence"),
            _nested_get(current_file, "coach_context", "evidence"),
            _nested_get(active_thread, "evidence") if isinstance(active_thread, dict) else None,
        )
    )
    thread_summary = _first_str(
        _nested_get(coach_context, "thread_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "thread_summary") if coach_context else None,
        _nested_get(current_file, "thread_summary"),
        _nested_get(current_file, "coach_context", "thread_summary"),
        _nested_get(active_thread, "summary") if isinstance(active_thread, dict) else None,
        _nested_get(active_thread, "focus_area") if isinstance(active_thread, dict) else None,
    )
    thread_next_step = _first_str(
        _extract_next_step_hint_text(
            _nested_get(coach_context, "thread_next_step") if coach_context else None,
        ),
        _nested_get(coach_context, "coach_context", "thread_next_step") if coach_context else None,
        _nested_get(current_file, "thread_next_step"),
        _nested_get(current_file, "coach_context", "thread_next_step"),
        _nested_get(active_thread, "next_step") if isinstance(active_thread, dict) else None,
    )
    resume_hint = _first_str(
        _nested_get(coach_context, "resume_thread") if coach_context else None,
        _nested_get(coach_context, "resume_hint") if coach_context else None,
        _nested_get(coach_context, "coach_context", "resume_thread") if coach_context else None,
        _nested_get(coach_context, "coach_context", "resume_hint") if coach_context else None,
        _nested_get(current_file, "resume_thread"),
        _nested_get(current_file, "resume_hint"),
        _nested_get(current_file, "coach_context", "resume_thread"),
        _nested_get(current_file, "coach_context", "resume_hint"),
    )
    if not resume_hint:
        resume_hint_parts: list[str] = []
        if thread_summary:
            resume_hint_parts.append(f"Resume the live thread around {thread_summary}.")
        if thread_next_step:
            resume_hint_parts.append(f"Keep the next move as {thread_next_step}.")
        if blocker:
            resume_hint_parts.append(f"Keep the blocker in view: {blocker}.")
        if isinstance(active_thread, dict):
            verified_result = _compact_text(active_thread.get("verified_result"), 96)
            if verified_result:
                resume_hint_parts.append(f"Build on the verified result: {verified_result}.")
        if decision:
            resume_hint_parts.append(f"Keep the latest finalized decision in view: {decision}.")
        if teaching_note:
            resume_hint_parts.append(f"Carry this teaching note forward: {teaching_note}.")
        if confidence:
            resume_hint_parts.append(f"Coach confidence: {confidence}.")
        if evidence:
            resume_hint_parts.append(f"Evidence to anchor on: {'; '.join(evidence)}.")
        resume_hint = " ".join(resume_hint_parts).strip()
    coach_defaults = _first_value(
        _nested_get(coach_context, "coach_defaults") if coach_context else None,
        _nested_get(coach_context, "coach_context", "coach_defaults") if coach_context else None,
        _nested_get(current_file, "coach_defaults"),
        _nested_get(current_file, "coach_context", "coach_defaults"),
    )
    exercise_prompt = _first_value(
        _nested_get(coach_context, "exercise_prompt") if coach_context else None,
        _nested_get(coach_context, "coach_context", "exercise_prompt") if coach_context else None,
        _nested_get(current_file, "exercise_prompt"),
        _nested_get(current_file, "coach_context", "exercise_prompt"),
    )
    project_sources = _first_value(
        _nested_get(coach_context, "project_sources") if coach_context else None,
        _nested_get(coach_context, "coach_context", "project_sources") if coach_context else None,
        _nested_get(current_file, "project_sources"),
        _nested_get(current_file, "coach_context", "project_sources"),
    )
    background_references = _first_value(
        _nested_get(coach_context, "background_references") if coach_context else None,
        _nested_get(coach_context, "coach_context", "background_references") if coach_context else None,
        _nested_get(current_file, "background_references"),
        _nested_get(current_file, "coach_context", "background_references"),
    )
    recent_background_findings = _first_value(
        _nested_get(coach_context, "recent_background_findings") if coach_context else None,
        _nested_get(coach_context, "coach_context", "recent_background_findings") if coach_context else None,
        _nested_get(current_file, "recent_background_findings"),
        _nested_get(current_file, "coach_context", "recent_background_findings"),
    )
    external_references = _first_value(
        _nested_get(coach_context, "external_references") if coach_context else None,
        _nested_get(coach_context, "coach_context", "external_references") if coach_context else None,
        _nested_get(current_file, "external_references"),
        _nested_get(current_file, "coach_context", "external_references"),
    )
    background_reference_summary = _first_str(
        _nested_get(coach_context, "background_reference_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "background_reference_summary") if coach_context else None,
        _nested_get(current_file, "background_reference_summary"),
        _nested_get(current_file, "coach_context", "background_reference_summary"),
    )
    requested_resource_ids = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "requested_resource_ids") if coach_context else None,
            _nested_get(coach_context, "coach_context", "requested_resource_ids")
            if coach_context
            else None,
            _nested_get(current_file, "requested_resource_ids"),
            _nested_get(current_file, "coach_context", "requested_resource_ids"),
        )
    )
    resource_fragments = _first_value(
        _nested_get(coach_context, "resource_fragments") if coach_context else None,
        _nested_get(coach_context, "coach_context", "resource_fragments") if coach_context else None,
        _nested_get(current_file, "resource_fragments"),
        _nested_get(current_file, "coach_context", "resource_fragments"),
    )
    current_resource_grounding = bool(
        requested_resource_ids or (isinstance(resource_fragments, list) and resource_fragments)
    )
    teaching_decision = _first_value(
        _nested_get(coach_context, "teaching_decision") if coach_context else None,
        _nested_get(coach_context, "coach_context", "teaching_decision") if coach_context else None,
        _nested_get(current_file, "teaching_decision"),
        _nested_get(current_file, "coach_context", "teaching_decision"),
    )
    learner_state = _first_value(
        _nested_get(coach_context, "learner_state") if coach_context else None,
        _nested_get(coach_context, "coach_context", "learner_state") if coach_context else None,
        _nested_get(current_file, "learner_state"),
        _nested_get(current_file, "coach_context", "learner_state"),
    )
    tone_decision = _first_value(
        _nested_get(coach_context, "tone_decision") if coach_context else None,
        _nested_get(coach_context, "coach_context", "tone_decision") if coach_context else None,
        _nested_get(current_file, "tone_decision"),
        _nested_get(current_file, "coach_context", "tone_decision"),
    )
    implementation_guide = _first_value(
        _nested_get(coach_context, "implementation_guide") if coach_context else None,
        _nested_get(coach_context, "coach_context", "implementation_guide") if coach_context else None,
        _nested_get(current_file, "implementation_guide"),
        _nested_get(current_file, "coach_context", "implementation_guide"),
    )
    project_ideas = _first_value(
        _nested_get(coach_context, "project_ideas") if coach_context else None,
        _nested_get(coach_context, "coach_context", "project_ideas") if coach_context else None,
        _nested_get(current_file, "project_ideas"),
        _nested_get(current_file, "coach_context", "project_ideas"),
    )
    adaptation_guide = _first_value(
        _nested_get(coach_context, "project_adaptation_guide") if coach_context else None,
        _nested_get(coach_context, "adaptation_guide") if coach_context else None,
        _nested_get(coach_context, "coach_context", "project_adaptation_guide") if coach_context else None,
        _nested_get(current_file, "project_adaptation_guide"),
        _nested_get(current_file, "adaptation_guide"),
        _nested_get(current_file, "coach_context", "project_adaptation_guide"),
    )
    principle_notes = _first_value(
        _nested_get(coach_context, "principle_notes") if coach_context else None,
        _nested_get(coach_context, "principle_note") if coach_context else None,
        _nested_get(coach_context, "coach_context", "principle_notes") if coach_context else None,
        _nested_get(current_file, "principle_notes"),
        _nested_get(current_file, "principle_note"),
        _nested_get(current_file, "coach_context", "principle_notes"),
    )
    selected_teaching_asset_ids = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "selected_teaching_asset_ids") if coach_context else None,
            _nested_get(coach_context, "teaching_asset_ids") if coach_context else None,
            _nested_get(coach_context, "coach_context", "selected_teaching_asset_ids") if coach_context else None,
            _nested_get(current_file, "selected_teaching_asset_ids"),
            _nested_get(current_file, "coach_context", "selected_teaching_asset_ids"),
        )
    )
    teaching_asset_summary = _first_str(
        _nested_get(coach_context, "teaching_asset_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "teaching_asset_summary") if coach_context else None,
        _nested_get(current_file, "teaching_asset_summary"),
        _nested_get(current_file, "coach_context", "teaching_asset_summary"),
    )
    recalled_memory_summary = _first_str(
        _nested_get(coach_context, "recalled_memory_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "recalled_memory_summary") if coach_context else None,
        _nested_get(current_file, "recalled_memory_summary"),
        _nested_get(current_file, "coach_context", "recalled_memory_summary"),
    )
    failing_checks = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "failing_checks") if coach_context else None,
            _nested_get(coach_context, "coach_context", "failing_checks") if coach_context else None,
            _nested_get(current_file, "failing_checks"),
            _nested_get(current_file, "coach_context", "failing_checks"),
        )
    )
    project_entry_points = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "project_entry_points") if coach_context else None,
            _nested_get(coach_context, "coach_context", "project_entry_points") if coach_context else None,
            _nested_get(current_file, "project_entry_points"),
            _nested_get(current_file, "coach_context", "project_entry_points"),
        )
    )
    project_summary = _first_str(
        _nested_get(coach_context, "project_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "project_summary") if coach_context else None,
        _nested_get(current_file, "project_summary"),
        _nested_get(current_file, "coach_context", "project_summary"),
    )
    function_guidance_starter = _first_value(
        _nested_get(coach_context, "function_guidance_starter") if coach_context else None,
        _nested_get(coach_context, "coach_context", "function_guidance_starter") if coach_context else None,
        _nested_get(current_file, "function_guidance_starter"),
        _nested_get(current_file, "coach_context", "function_guidance_starter"),
    )
    review_queue_summary = _first_str(
        _nested_get(coach_context, "review_queue_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "review_queue_summary") if coach_context else None,
        _nested_get(current_file, "review_queue_summary"),
        _nested_get(current_file, "coach_context", "review_queue_summary"),
    )
    next_review_due = _first_str(
        _nested_get(coach_context, "next_review_due") if coach_context else None,
        _nested_get(coach_context, "coach_context", "next_review_due") if coach_context else None,
        _nested_get(current_file, "next_review_due"),
        _nested_get(current_file, "coach_context", "next_review_due"),
    )
    pace_signal = _first_str(
        _nested_get(coach_context, "pace_signal") if coach_context else None,
        _nested_get(coach_context, "coach_context", "pace_signal") if coach_context else None,
        _nested_get(coach_context, "memory", "pace_signal") if coach_context else None,
        _nested_get(current_file, "pace_signal"),
        _nested_get(current_file, "coach_context", "pace_signal"),
        _nested_get(current_file, "memory", "pace_signal"),
    )
    relationship_stage = _first_str(
        _nested_get(coach_context, "relationship_stage") if coach_context else None,
        _nested_get(coach_context, "coach_context", "relationship_stage") if coach_context else None,
        _nested_get(current_file, "relationship_stage"),
        _nested_get(current_file, "coach_context", "relationship_stage"),
    )
    first_turn_priority = _first_str(
        _nested_get(coach_context, "first_turn_priority") if coach_context else None,
        _nested_get(coach_context, "coach_context", "first_turn_priority") if coach_context else None,
        _nested_get(current_file, "first_turn_priority"),
        _nested_get(current_file, "coach_context", "first_turn_priority"),
    )
    learning_outcomes = _first_value(
        _nested_get(coach_context, "learning_outcomes") if coach_context else None,
        _nested_get(coach_context, "memory", "learning_outcomes") if coach_context else None,
        _nested_get(coach_context, "coach_context", "learning_outcomes") if coach_context else None,
        _nested_get(current_file, "learning_outcomes"),
        _nested_get(current_file, "coach_context", "learning_outcomes"),
        _nested_get(current_file, "memory", "learning_outcomes"),
    )
    recent_teaching_signals = _coerce_str_list(
        _first_value(
            _nested_get(coach_context, "recent_teaching_signals") if coach_context else None,
            _nested_get(coach_context, "coach_context", "recent_teaching_signals") if coach_context else None,
            _nested_get(current_file, "recent_teaching_signals"),
            _nested_get(current_file, "coach_context", "recent_teaching_signals"),
        )
    )
    continuity_summary = _first_str(
        _nested_get(coach_context, "continuity_summary") if coach_context else None,
        _nested_get(coach_context, "coach_context", "continuity_summary") if coach_context else None,
        _nested_get(current_file, "continuity_summary"),
        _nested_get(current_file, "coach_context", "continuity_summary"),
    )
    history_mode = _first_str(
        _nested_get(coach_context, "history_mode") if coach_context else None,
        _nested_get(coach_context, "coach_context", "history_mode") if coach_context else None,
        _nested_get(current_file, "history_mode"),
        _nested_get(current_file, "coach_context", "history_mode"),
    )
    active_view_value = _first_str(
        _nested_get(coach_context, "active_view") if coach_context else None,
        _nested_get(coach_context, "coach_context", "active_view") if coach_context else None,
        _nested_get(current_file, "active_view"),
        _nested_get(current_file, "coach_context", "active_view"),
    )
    active_view = active_view_value.lower() if active_view_value else None

    diagnostics = current_file.get("diagnostics") if current_file else None
    diagnostics_count = len(diagnostics) if isinstance(diagnostics, list) else 0
    return {
        "scenario": scenario,
        "active_view": active_view,
        "learner_signal": learner_signal,
        "execution_ready": _has_execution_ready_next_step_request(message, current_file),
        "current_focus": current_focus,
        "recent_wins": recent_wins,
        "weak_spots": weak_spots,
        "due_reviews": due_reviews,
        "requested_resources": requested_resources,
        "requested_resource_ids": requested_resource_ids,
        "resource_fragments": resource_fragments if isinstance(resource_fragments, list) else [],
        "resource_composer_intent": resource_composer_intent,
        "requested_resource_summary": requested_resource_summary,
        "resource_sequence_summary": resource_sequence_summary,
        "resource_sequence_guidance": resource_sequence_guidance,
        "resource_question_facets": resource_question_facets,
        "auto_resource_lookup": auto_resource_lookup,
        "missing_resource_ids": missing_resource_ids,
        "review_rhythm": review_rhythm,
        "memory_evidence": memory_evidence,
        "teaching_observations": teaching_observations,
        "teaching_assets": teaching_assets if isinstance(teaching_assets, list) else [],
        "recalled_coaching_memories": recalled_coaching_memories
        if isinstance(recalled_coaching_memories, list)
        else [],
        "teaching_knowledge_catalog": teaching_knowledge_catalog
        if isinstance(teaching_knowledge_catalog, dict)
        else {},
        "coaching_adaptation": coaching_adaptation if isinstance(coaching_adaptation, dict) else None,
        "summary": summary,
        "next_step_hint": next_step_hint,
        "thread_summary": thread_summary,
        "thread_next_step": thread_next_step,
        "resume_hint": resume_hint,
        "decision": decision,
        "blocker": blocker,
        "teaching_note": teaching_note,
        "confidence": confidence,
        "evidence": evidence,
        "encouragement": encouragement,
        "active_thread": active_thread,
        "coach_defaults": coach_defaults,
        "teaching_decision": teaching_decision if isinstance(teaching_decision, dict) else None,
        "learner_state": learner_state if isinstance(learner_state, dict) else None,
        "tone_decision": tone_decision if isinstance(tone_decision, dict) else None,
        "implementation_guide": implementation_guide if isinstance(implementation_guide, dict) else None,
        "project_ideas": project_ideas if isinstance(project_ideas, list) else [],
        "adaptation_guide": adaptation_guide if isinstance(adaptation_guide, dict) else None,
        "principle_notes": principle_notes if isinstance(principle_notes, dict) else None,
        "exercise_prompt": exercise_prompt if isinstance(exercise_prompt, dict) else None,
        "selected_teaching_asset_ids": selected_teaching_asset_ids,
        "teaching_asset_summary": teaching_asset_summary,
        "recalled_memory_summary": recalled_memory_summary,
        "failing_checks": failing_checks,
        "project_entry_points": project_entry_points,
        "project_summary": project_summary,
        "function_guidance_starter": function_guidance_starter
        if isinstance(function_guidance_starter, dict)
        else None,
        "review_queue_summary": review_queue_summary,
        "next_review_due": next_review_due,
        "pace_signal": pace_signal,
        "relationship_stage": relationship_stage,
        "first_turn_priority": first_turn_priority,
        "history_mode": history_mode,
        "review_artifact": (
            coach_context.get("review_artifact")
            if isinstance(coach_context, dict)
            and isinstance(coach_context.get("review_artifact"), dict)
            else None
        ),
        "learning_outcomes": learning_outcomes if isinstance(learning_outcomes, list) else [],
        "recent_teaching_signals": recent_teaching_signals,
        "continuity_summary": continuity_summary,
        "project_sources": project_sources if isinstance(project_sources, list) else [],
        "external_references": external_references if isinstance(external_references, list) else [],
        "background_references": background_references if isinstance(background_references, list) else [],
        "recent_background_findings": recent_background_findings
        if isinstance(recent_background_findings, list)
        else [],
        "background_reference_summary": background_reference_summary,
        "current_resource_grounding": current_resource_grounding,
        "diagnostics_count": diagnostics_count,
        "selection_range": current_file.get("selection_range") if current_file else None,
        "selection_text": current_file.get("selection_text") if current_file else None,
        "content_excerpt": current_file.get("content_excerpt") if current_file else None,
        "file_path": current_file.get("path") if current_file else None,
        "language_id": current_file.get("language_id") if current_file else None,
        "plan_runtime_recovery": (
            coach_context.get("plan_runtime_recovery")
            if isinstance(coach_context, dict)
            else None
        ),
        "first_look_recommended_next": first_look_recommended_next_from_context(
            coach_context if isinstance(coach_context, dict) else None
        ),
        "workspace_understanding": (
            coach_context.get("workspace_understanding")
            if isinstance(coach_context, dict)
            else None
        ),
        "active_task": _first_str(
            _nested_get(coach_context, "active_task") if coach_context else None,
            _nested_get(coach_context, "coach_context", "active_task") if coach_context else None,
        ),
    }


#: How many project file names the per-turn context lists before it says "and N more".
PROJECT_FILES_SHOWN_LIMIT = 60


def _snapshot_entry_is_current_file(entry_path: str, current_path: str, root_uri: object) -> bool:
    """Whether a snapshot entry (relative to the workspace root) is the open file.

    The host sends the open file as an absolute path and the snapshot entries relative to the
    workspace root (`root_uri`), so the entry is resolved against that root and compared exactly; a
    bare suffix match would take `pkg/app.py` for `app.py`.
    """
    if not current_path or not entry_path:
        return False
    entry = entry_path.replace("\\", "/")
    if entry == current_path:
        return True
    root = str(root_uri or "").strip()
    for prefix in ("file://", "vscode-remote://"):
        if root.startswith(prefix):
            root = root[len(prefix):]
            break
    root = root.rstrip("/")
    if not root:
        return False
    return f"{root}/{entry}" == current_path


def _build_project_files_block(
    coach_context: dict[str, Any] | None,
    current_file: dict[str, object] | None = None,
) -> str:
    """Names, never contents, of the project files the host handed over for this turn.

    The host sends the list on every turn; it used to reach only the `project_read` tool, so the
    model could not know which files exist and every project question began with `list`, then a
    read, then the answer. With the names in front of it a read is needed only for a file it
    actually wants to see. The open file is marked as already in the prompt: the model kept reading
    it again before answering (measured with a real model, 2026-11-28).
    """
    context = coach_context if isinstance(coach_context, dict) else {}
    snapshot = context.get("workspace_file_snapshot")
    if not isinstance(snapshot, dict):
        return ""
    files = snapshot.get("files")
    if not isinstance(files, list):
        return ""
    current_path = str((current_file or {}).get("path") or "").strip().replace("\\", "/")
    names: list[str] = []
    total = 0
    for item in files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        total += 1
        if len(names) >= PROJECT_FILES_SHOWN_LIMIT:
            continue
        in_prompt = _snapshot_entry_is_current_file(path, current_path, snapshot.get("root_uri"))
        names.append(
            f"{path} — its content (the lines shown above) and its diagnostics are already in your context; "
            "read it again only for lines outside that window"
            if in_prompt
            else path
        )
    if not names:
        return ""
    more = (
        f"\n- … and {total - len(names)} more (`project_read` with action `list` shows them all)"
        if total > len(names)
        else ""
    )
    return (
        "Project files (names only; this list is already in front of you, so do not call `project_read` "
        "with action `list` again — read a file only when you need its content and it is not already in "
        "your context):\n"
        + "\n".join(f"- {name}" for name in names)
        + more
    )


def build_coaching_system_prompt(
    profile: UserProfile,
    response_language: str | None = None,
    answer_mode: str | None = None,
    message: str | None = None,
    current_file: dict[str, object] | None = None,
    coach_context: dict[str, Any] | None = None,
    *,
    agent_loop_enabled: bool = False,
    omit_active_thread_block: bool = False,
) -> str:
    if coach_context is not None and _resource_composer_mode(coach_context) == "analyze":
        return _library_analysis_system_prompt(profile, coach_context, response_language, message)
    raw_answer_policy = answer_mode or profile.answer_policy
    minimal_context = isinstance(coach_context, dict) and (
        coach_context.get("context_tier") == "minimal"
    )
    use_minimal_template = minimal_context and not (
        isinstance(coach_context, dict)
        and (
            coach_context.get("goal_mode") is True
            or coach_context.get("completed_training_return_feedback") is True
        )
    )
    # 1. Session-invariant static prefix at byte 0 (protects LLM Prompt KV Cache across turns).
    system_prompt = build_static_coaching_prefix(
        profile,
        response_language,
        answer_mode,
        minimal_context=minimal_context,
        use_minimal_template=use_minimal_template,
        agent_loop_enabled=agent_loop_enabled,
    )

    # 2. Turn-dynamic state & progressive lane instructions appended after the cached prefix.
    pedagogy_mode = None if minimal_context else _resolve_pedagogy_mode(coach_context)
    if pedagogy_mode:
        system_prompt += (
            "\n\n## Pedagogy Mode\n"
            f"- Active mode: {pedagogy_mode}\n"
            f"- {_pedagogy_mode_instruction(pedagogy_mode)}"
        )

    if isinstance(coach_context, dict) and coach_context.get("completed_training_return_feedback") is True:
        system_prompt += (
            "\n\nCurrent returned training artifact: Trainer has verified the unchanged "
            "current file against current server-controlled evidence for this card. "
            "Verification, reflection and Return are already recorded. This is server "
            "state, not an unverified learner claim. Evaluate the reflection and the "
            "scope of the evidence. Do not demand pasted tool logs as a prerequisite "
            "for acknowledging the recorded verification or ask to repeat it unless "
            "the learner explicitly requests new checks. Do not infer unrecorded "
            "test counts, outputs, plan adoption or stage completion. Plan adoption "
            "is a separate explicit action."
        )

    coaching_scenario, current_file = _function_guidance_prompt_inputs(
        message,
        current_file,
        coach_context,
    )
    coaching_context = _prioritize_current_request_context(
        extract_coaching_context(message, current_file, coach_context)
    )
    coaching_context = _filter_function_guidance_entry_points(coaching_context, coaching_scenario)
    context_block = _build_context_block(coaching_context)
    if context_block:
        system_prompt += f"\n\n## Current Coaching Context\n{context_block}"

    active_thread_block = (
        None
        if (minimal_context or omit_active_thread_block)
        else _build_active_thread_block(coaching_context)
    )
    if active_thread_block:
        system_prompt += f"\n\n## Active Thread\n{active_thread_block}"

    turn_contract_block = (
        None if minimal_context else _build_turn_contract_block(coaching_context)
    )
    if turn_contract_block:
        system_prompt += f"\n\n## Turn Contract\n{turn_contract_block}"

    resource_composer_boundary = _build_resource_composer_boundary(coaching_context)
    if resource_composer_boundary:
        system_prompt += f"\n\n## Resource Task Boundary\n{resource_composer_boundary}"

    if minimal_context:
        pass
    elif isinstance(coach_context, dict) and coach_context.get("formal_plan_mutation") is True:
        system_prompt += (
            "\n\n## Formal Plan Turn\n"
            "This is an explicit request to create or revise the formal learning plan. "
            "Treat the learner's message as a conversation step, not as permission to "
            "silently synthesize a template. First use the current plan, learner profile, "
            "and prepared resource evidence to identify what is known and what still needs "
            "confirmation. Ask one concise clarification when the goal, weekly time, or "
            "scope is ambiguous. Reuse facts already in the prompt and read only missing evidence. "
            "Describe planned checks as acceptance criteria for the learner; executing them "
            "is a separate learning step. Respect any explicit restriction on source scope. "
            "Once the request is sufficiently clear, call `web_fetch(action='learning_materials', ...)` first "
            "only when the requested plan depends on current external sources, then call "
            "`learning_action(action='save_formal_plan', ...)` with concrete stages, outcomes, resources, and verification "
            "signals, then explain the committed plan in natural language. The tool result "
            "is the source of truth for persisted plan state."
        )
    elif isinstance(coach_context, dict):
        recovery = coach_context.get("plan_runtime_recovery")
        if isinstance(recovery, dict) and recovery.get("recovered") is True:
            recovered_action = str(recovery.get("action") or "").strip()
            recovered_step = str(recovery.get("current_step") or "").strip()
            recovered_step_id = str(recovery.get("current_step_id") or "").strip()
            recovered_blocker = str(recovery.get("blocked_reason") or "").strip()
            recovered_why = str(recovery.get("why_now") or "").strip()
            resume_lines = [
                "Resume the recovered current step. Do not create, replace, or invent a formal learning plan.",
                "Do not call learning_action(action='save_formal_plan').",
            ]
            if recovered_action:
                resume_lines.append(f"- Recovered action: {recovered_action}.")
            if recovered_step:
                resume_lines.append(f"- Recovered step: {recovered_step}.")
            if recovered_step_id:
                resume_lines.append(f"- Recovered step id: {recovered_step_id}.")
            if recovered_blocker:
                resume_lines.append(f"- Recovered blocker: {recovered_blocker}.")
            if recovered_why:
                resume_lines.append(f"- Why now: {recovered_why}.")
            system_prompt += "\n\n## Recovered Plan Runtime\n" + "\n".join(resume_lines)

    honesty_block = (
        None
        if minimal_context
        else _growth_loop_honesty_block(coach_context if isinstance(coach_context, dict) else None)
    )
    if honesty_block:
        system_prompt += honesty_block

    recall = coaching_context.get("review_artifact")
    if isinstance(recall, dict):
        system_prompt += (
            "\n\n## Current Recall Review\n"
            "Evaluate this recall's own prompt and answer. This is self-reported concept recall; "
            "do not require old coding checks, infer a passed verification, or invent test counts. "
            "Other practice or plan requirements are outside this question.\n"
            f"Prompt: {_compact_text(recall.get('summary'), 600)}\n"
            f"Recall rule: {_compact_text(recall.get('guardrail'), 240)}\n"
            f"Recorded answer: {_compact_text(recall.get('verified_result'), 1000)}"
        )

    tone_block = (
        None
        if minimal_context
        else _build_tone_adaptation_block(coaching_context)
    )
    if tone_block:
        system_prompt += f"\n\n## Tone And Continuity Bias\n{tone_block}"

    if not minimal_context or _is_rethinkfun_lecture_request(message):
        system_prompt += _build_state_driven_teaching_block(
            message,
            coach_context if isinstance(coach_context, dict) else None,
            response_language=response_language,
        )

    if agent_loop_enabled:
        system_prompt += _agent_loop_lane_skill_suffix(
            message=message,
            coach_context=coach_context if isinstance(coach_context, dict) else None,
        )

    if isinstance(coach_context, dict) and coach_context.get("goal_mode") is True:
        system_prompt += (
            "\n\n## Goal Mode — the learner does the work\n"
            "The learner set ONE small goal and wants to be able to do it, not just hear about it.\n"
            "- Do not open with a lecture or a full explanation. In the first reply, restate the target capability in one short sentence, then give exactly ONE tiny concrete action, question, or observation for the learner to do now.\n"
            "- Wait for their attempt. Then judge it honestly, correct at most one misconception, and give the next micro-action.\n"
            "- Never dump the full solution before they have tried. Give the smallest hint that unblocks them.\n"
            "- A correct action alone is not mastery. After they can do it, ask them to explain the reasoning in their own words, then give one small variation or transfer task.\n"
            "- Never declare the goal complete, never say the learner has mastered it, and never accept a self-claim such as \"I've got it\" or \"mark it done\". Even after a correct teach-back and transfer, name the capability and ask whether they want to end the goal; the learner ends it with the goal control. If they ask to finish before both checks, refuse and ask for the missing explanation or variation.\n"
            "- Keep each reply under about 120 words. One action per turn. In each micro-step, state the current known/unknown/goal/obstacle in one short sentence before the action, and recycle it after the learner's attempt; no lecture.\n"
            "- Do not claim formal evidence, do not write files, and do not create a plan unless the learner explicitly asks."
        )
    raw_productivity = (
        coach_context.get("productivity_convergence")
        if isinstance(coach_context, dict)
        else None
    )
    if (
        isinstance(raw_productivity, dict)
        and raw_productivity.get("should_converge") is True
        and raw_answer_policy != "direct"
    ):
        unproductive_turns = int(raw_productivity.get("consecutive_unproductive_turns") or 2)
        system_prompt += (
            "\n\n## Conversation Productivity Convergence\n"
            f"This learning thread has spent {unproductive_turns} turns explaining without a learner attempt, "
            "verified evidence, or a scheduled review. Keep any explanation brief and end with ONE concrete "
            "micro-attempt the learner can try right now, or offer to schedule a quick recall check — "
            "do not open another long lecture, and do not fabricate a formal task or evidence."
        )
    raw_diag_hint = (
        coach_context.get("diagnostic_weakness_hint")
        if isinstance(coach_context, dict)
        else None
    )
    if (
        isinstance(raw_diag_hint, dict)
        and str(raw_diag_hint.get("concept") or "").strip()
        and raw_answer_policy != "direct"
    ):
        hint_concept = _compact_text(raw_diag_hint.get("concept"), 80)
        hint_diag = _compact_text(raw_diag_hint.get("diagnostic"), 140)
        system_prompt += (
            "\n\n## Weakness Recall Cue\n"
            f"Live IDE diagnostic ({hint_diag}) touches a previously recorded weakness around \"{hint_concept}\". "
            "When relevant to the learner's question, connect this symptom back to that concept in one calm sentence "
            "and suggest one small verification step; do not nag or interrupt if they asked about something else."
        )
    return system_prompt


def _format_requested_resource(item: dict[str, str]) -> str:
    title = item.get("title", "resource")
    kind = item.get("kind", "resource")
    summary = item.get("summary", "")
    source = item.get("source", "")
    trust_score = item.get("trust_score", "")
    freshness = item.get("freshness", "")
    source_part = f" source={source}" if source else ""
    trust_part = f" trust={trust_score}" if trust_score else ""
    freshness_part = f" freshness={freshness}" if freshness else ""
    if summary:
        return f"{title} ({kind}): {summary}{source_part}{trust_part}{freshness_part}"
    return f"{title} ({kind}){source_part}{trust_part}{freshness_part}"


def _build_resource_sequence_block(context: dict[str, Any]) -> str:
    sequences = context.get("resource_sequence_guidance")
    if not isinstance(sequences, list) or not sequences:
        return ""
    lines = [
        "Restate every library step in order before you continue. Preserve the exact library step count unless you explicitly say you are extending it."
    ]
    for item in sequences[:2]:
        if not isinstance(item, dict):
            continue
        title = _compact_text(item.get("title"), 96) or "resource"
        source = _compact_text(item.get("source"), 96)
        step_count = int(item.get("step_count") or 0)
        header = f"- {title}"
        if step_count >= 2:
            header += f" ({step_count} steps)"
        if source:
            header += f" [{source}]"
        lines.append(header)
        raw_steps = item.get("steps")
        if isinstance(raw_steps, list):
            for step in raw_steps[:6]:
                if not isinstance(step, dict):
                    continue
                label = _compact_text(step.get("label"), 32)
                text = _compact_text(step.get("text"), 180)
                if not label or not text:
                    continue
                lines.append(f"  - {label}: {text}")
        boundary_sentinel = _compact_text(item.get("boundary_sentinel"), 120)
        if boundary_sentinel:
            lines.append(f"  - Boundary sentinel: {boundary_sentinel}")
    return "\n".join(lines)


def _build_function_guidance_starter_block(context: dict[str, Any]) -> str:
    starter = context.get("function_guidance_starter")
    if not isinstance(starter, dict):
        return ""
    call_site_path = _compact_text(starter.get("call_site_path"), 120)
    definition_path = _compact_text(starter.get("definition_path"), 120)
    boundary_note = _compact_text(starter.get("boundary_note"), 180)
    coach_instruction = _compact_text(starter.get("coach_instruction"), 180)
    suggested_sequence = _compact_list(starter.get("suggested_sequence"), 4)
    call_site_content = str(starter.get("call_site_content") or "").strip()
    definition_content = str(starter.get("definition_content") or "").strip()
    language_id = _compact_text(starter.get("language_id"), 24) or ""
    lines: list[str] = []
    if boundary_note:
        lines.append(boundary_note)
    if coach_instruction:
        lines.append(coach_instruction)
    if call_site_path:
        lines.append(f"Live call site: `{call_site_path}`")
    if definition_path:
        lines.append(f"Definition file: `{definition_path}`")
    if suggested_sequence:
        lines.append("Suggested reading order:")
        lines.extend(f"- {item}" for item in suggested_sequence)
    if call_site_content:
        lines.append(
            "\n# Live call site\n"
            f"Path: `{call_site_path or 'unknown'}`\n"
            f"```{language_id}\n{call_site_content}\n```"
        )
    if definition_content:
        lines.append(
            "\n# Definition\n"
            f"Path: `{definition_path or 'unknown'}`\n"
            f"```{language_id}\n{definition_content}\n```"
        )
    return "\n".join(lines)


def build_coaching_messages(
    profile: UserProfile,
    message: str,
    current_file: dict[str, object] | None = None,
    response_language: str | None = None,
    answer_mode: str | None = None,
    coach_context: dict[str, Any] | None = None,
    *,
    agent_loop_enabled: bool = False,
    history: list[dict[str, str]] | None = None,
    history_limit: int = 12,
    history_token_budget: int = DEFAULT_COACHING_HISTORY_TOKEN_BUDGET,
) -> list[dict[str, str]]:
    """Build the canonical message list for one coaching turn.

    Parameters
    ----------
    history:
        Prior conversation messages (already in OpenAI canonical shape with
        ``role`` and ``content``). Inserted between the system prompt and the
        current user turn so the model sees the actual back-and-forth; this
        is what makes the coach a long-running thread rather than a series of
        amnesiac one-shots. ``role="system"`` items in ``history`` are
        dropped; the system prompt is always rebuilt fresh from the latest
        coaching context.
    history_limit:
        Keep at most this many of the most recent prior messages. The system
        prompt + current user message are NOT counted in this budget.
    history_token_budget:
        Bound retained history by an approximate token budget. The newest
        question and answer take priority over older turns.
    """
    if coach_context is not None and _resource_composer_mode(coach_context) == "analyze":
        return [
            {"role": "system", "content": _library_analysis_system_prompt(
                profile, coach_context, response_language, message,
            )},
            {"role": "user", "content": library_analysis_question(message)
             if library_practice_requested(message, coach_context) else message},
        ]
    _, current_file = _function_guidance_prompt_inputs(
        message,
        current_file,
        coach_context,
    )
    system_prompt = build_coaching_system_prompt(
        profile,
        response_language,
        answer_mode,
        message=message,
        current_file=current_file,
        coach_context=coach_context,
        agent_loop_enabled=agent_loop_enabled,
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    extracted_ctx = extract_coaching_context(message, current_file, coach_context)
    history_mode = str(extracted_ctx.get("history_mode") or "").strip().lower()
    explicit_turn_scenario = str((coach_context or {}).get("scenario") or "").strip().lower()
    inferred_turn_scenario = infer_coaching_scenario(
        message or "",
        current_file,
        {"history_mode": "fresh_lane"},
        default="general",
    )
    resolved_scenario = (
        explicit_turn_scenario
        if explicit_turn_scenario not in {"", "general"}
        else inferred_turn_scenario
    )
    active_view_name = str((coach_context or {}).get("active_view") or "").strip().lower()
    suppress_history = history_mode == "fresh_lane" and (
        resolved_scenario not in {"", "general"}
        or active_view_name in {"plan", "resources", "training", "settings"}
    )

    if history and not suppress_history:
        # Pi-style transcript preservation: keep user/assistant text turns AND
        # atomically paired assistant(tool_calls) -> tool(tool_call_id) groups,
        # dropping only orphan tool entries or stale system messages.
        atomic_groups: list[list[dict[str, Any]]] = []
        idx = 0
        raw_items = list(history)
        while idx < len(raw_items):
            item = raw_items[idx]
            if not isinstance(item, dict):
                idx += 1
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            raw_tool_calls = item.get("tool_calls")
            if role == "assistant" and isinstance(raw_tool_calls, list) and raw_tool_calls:
                call_ids = {
                    str(tc.get("id") or "").strip()
                    for tc in raw_tool_calls
                    if isinstance(tc, dict) and str(tc.get("id") or "").strip()
                }
                paired_tools: list[dict[str, Any]] = []
                lookahead = idx + 1
                while lookahead < len(raw_items):
                    nxt = raw_items[lookahead]
                    if not isinstance(nxt, dict) or str(nxt.get("role") or "").strip() != "tool":
                        break
                    tc_id = str(nxt.get("tool_call_id") or "").strip()
                    if tc_id and tc_id in call_ids:
                        paired_tools.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                **({"name": str(nxt["name"])} if nxt.get("name") else {}),
                                "content": _truncate_coaching_history_content(
                                    str(nxt.get("content") or ""), token_budget=600
                                ),
                            }
                        )
                    lookahead += 1
                returned_ids = {t["tool_call_id"] for t in paired_tools}
                if call_ids and call_ids.issubset(returned_ids):
                    assistant_entry: dict[str, Any] = {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": raw_tool_calls,
                    }
                    atomic_groups.append([assistant_entry, *paired_tools])
                    idx = lookahead
                    continue
                if content:
                    atomic_groups.append([{"role": "assistant", "content": content}])
                idx = lookahead
                continue
            if role in {"user", "assistant"} and content:
                atomic_groups.append([{"role": role, "content": content}])
            idx += 1

        if atomic_groups:
            has_tool_groups = any(len(g) > 1 for g in atomic_groups)
            if not has_tool_groups:
                flat_history = [g[0] for g in atomic_groups]
                messages.extend(
                    _budget_coaching_history(
                        flat_history,
                        history_limit=max(0, int(history_limit)),
                        history_token_budget=max(0, int(history_token_budget)),
                    )
                )
            else:
                kept_groups: list[list[dict[str, Any]]] = []
                remaining_msgs = max(0, int(history_limit))
                remaining_tokens = max(0, int(history_token_budget))
                for group in reversed(atomic_groups):
                    if remaining_msgs <= 0 or remaining_tokens <= 0:
                        break
                    group_tokens = sum(
                        _estimate_coaching_history_tokens(str(m.get("content") or ""))
                        for m in group
                    )
                    if kept_groups and group_tokens > remaining_tokens:
                        break
                    kept_groups.append(group)
                    remaining_msgs -= 1
                    remaining_tokens = max(0, remaining_tokens - group_tokens)
                for group in reversed(kept_groups):
                    messages.extend(group)

    coaching_context = _prioritize_current_request_context(
        extract_coaching_context(message, current_file, coach_context)
    )
    coaching_context = _filter_function_guidance_entry_points(
        coaching_context,
        str(coaching_context.get("scenario") or ""),
    )
    runtime_context_blocks: list[str] = []
    first_turn = _looks_like_first_turn(coaching_context)
    raw_coach_defaults = coaching_context.get("coach_defaults")
    coach_defaults = raw_coach_defaults if isinstance(raw_coach_defaults, dict) else {}
    memory_scope = str(coach_defaults.get("memory_scope") or "").strip()
    working_set_mode = str(coach_defaults.get("working_set_mode") or "").strip()
    raw_workspace_memory_toggles = coach_defaults.get("workspace_memory_toggles")
    workspace_memory_toggles = (
        raw_workspace_memory_toggles if isinstance(raw_workspace_memory_toggles, dict) else {}
    )
    learner_context_block = _build_learner_context_block(coaching_context)
    if learner_context_block:
        runtime_context_blocks.append(f"Learner context:\n{learner_context_block}")

    active_thread_block = _build_active_thread_block(coaching_context)
    if active_thread_block:
        runtime_context_blocks.append(f"Active thread to resume:\n{active_thread_block}")

    resource_sequence_block = _build_resource_sequence_block(coaching_context)
    if resource_sequence_block:
        runtime_context_blocks.append(
            f"Prepared library sequence:\n{resource_sequence_block}"
        )

    function_guidance_starter_block = ""
    if not current_file:
        function_guidance_starter_block = _build_function_guidance_starter_block(coaching_context)
    if function_guidance_starter_block:
        runtime_context_blocks.append(
            f"Trainer sandbox starter:\n{function_guidance_starter_block}"
        )

    if current_file:
        file_content = current_file.get("content_excerpt") or current_file.get("content", "")
        file_span = current_file.get("content_line_span")
        file_strategy = current_file.get("content_strategy")
        file_block = (
            f"Current file: `{current_file.get('path', 'unknown')}` "
            f"({current_file.get('language_id', 'unknown')})"
        )
        if file_span:
            file_block += f"\nContext window: lines {file_span}"
        if file_strategy:
            file_block += f"\nContext strategy: {file_strategy}"
        file_block += (
            f"\n```{current_file.get('language_id', '')}\n"
            f"{file_content}\n```\n---"
        )
        file_context_parts = [file_block]

        selection_text = current_file.get("selection_text")
        selection_range = current_file.get("selection_range")
        if selection_text:
            file_context_parts.append(
                "\nSelected range: "
                f"{selection_range or 'unspecified'}\n```\n{selection_text}\n```"
            )

        include_patterns = bool(workspace_memory_toggles.get("patterns", True))
        include_resources = bool(workspace_memory_toggles.get("resources", False))
        diagnostics = current_file.get("diagnostics")
        if include_patterns and isinstance(diagnostics, list) and diagnostics:
            file_context_parts.append(
                "\nRecent diagnostics:\n" + "\n".join(f"- {item}" for item in diagnostics)
            )

        recent_edited_files = current_file.get("recent_edited_files")
        if include_patterns and isinstance(recent_edited_files, list) and recent_edited_files:
            file_context_parts.append(
                "\nRecently edited files:\n"
                + "\n".join(f"- {item}" for item in recent_edited_files[:5])
            )

        recent_files = current_file.get("recent_files")
        if include_patterns and isinstance(recent_files, list) and recent_files:
            file_context_parts.append(
                "\nRecently opened files:\n"
                + "\n".join(f"- {item}" for item in recent_files[:5])
            )

        related_files = current_file.get("related_files")
        if include_resources and isinstance(related_files, list) and related_files:
            related_lines: list[str] = []
            for item in related_files[:4]:
                if isinstance(item, dict):
                    line = f"- {item.get('path', 'unknown')} ({item.get('reason', 'related')})"
                    if item.get("line_span"):
                        line += f" lines {item.get('line_span')}"
                    related_lines.append(line)
            if related_lines:
                file_context_parts.append("\nRelated files:\n" + "\n".join(related_lines))

            related_snippets: list[str] = []
            for item in related_files[:3]:
                if isinstance(item, dict) and item.get("excerpt"):
                    related_snippets.append(
                        f"\n# {item.get('path', 'unknown')}\n```{current_file.get('language_id', '')}\n{item.get('excerpt', '')}\n```"
                    )
            if related_snippets:
                file_context_parts.append("\nRelated snippets:\n" + "\n".join(related_snippets))

        runtime_context_blocks.append("".join(file_context_parts))

    project_files_block = _build_project_files_block(coach_context, current_file)
    if project_files_block:
        runtime_context_blocks.append(project_files_block)

    runtime_bias_lines: list[str] = []
    if memory_scope == "session":
        runtime_bias_lines.append(
            "Memory scope: session. Resume the live coaching thread first and keep the next answer tied to the latest step."
        )
    elif memory_scope == "personal":
        runtime_bias_lines.append(
            "Memory scope: personal. Bias toward repeated preferences, habits, and recurring friction."
        )
    elif memory_scope:
        runtime_bias_lines.append(
            "Memory scope: project. Bias toward the current workspace plan, active thread, and directly related artifacts."
        )
    if working_set_mode == "focused":
        runtime_bias_lines.append(
            "Working set mode: focused. Prefer the smallest local boundary and the nearest files only."
        )
    elif working_set_mode == "broad":
        runtime_bias_lines.append(
            "Working set mode: broad. It is acceptable to widen into nearby context when it improves verification."
        )
    if runtime_bias_lines:
        runtime_context_blocks.append(
            "Coaching defaults:\n" + "\n".join(f"- {line}" for line in runtime_bias_lines)
        )

    if first_turn:
        runtime_context_blocks.append(
            "First-turn rule:\n"
            "- The learner's final message is the task. If it asks a clear question, answer it directly before any orientation.\n"
            "- Ask one short follow-up only when the request is genuinely ambiguous or lacks information needed to answer."
        )

    runtime_context_section = ""
    if runtime_context_blocks:
        runtime_context_section = (
            "## Runtime Context\n"
            "Use this only as background. The final user message is the learner's actual request: answer it first, "
            "and do not treat these notes as a second request.\n\n"
            + "\n\n".join(runtime_context_blocks)
        )
        if len(messages) == 1:
            # Single-turn call with no prior history: append to messages[0].
            system_prompt += "\n\n" + runtime_context_section
            messages[0]["content"] = system_prompt

    # The system prompt carries the same material under Runtime Context, but
    # learners explicitly attach a file/resource to *this* request. Put the
    # bounded source next to the request as well so instruction-following
    # models cannot treat it as unrelated background.
    attached_material = _attached_material_grounding(coaching_context, current_file, message)
    user_message = message
    if len(messages) > 1 and runtime_context_section:
        # Multi-turn KV-cache preservation: keep messages[0] + prior history
        # byte-stable and append per-turn dynamic runtime context to the latest turn.
        user_message = f"{user_message}\n\n{runtime_context_section}"
    if attached_material:
        user_message = (
            f"{user_message}\n\n## Attached material for this request\n"
            "This is the source of truth for the answer; quote or use it before general recall.\n\n"
            f"{attached_material}"
        )
    messages.append({"role": "user", "content": user_message})
    return messages
