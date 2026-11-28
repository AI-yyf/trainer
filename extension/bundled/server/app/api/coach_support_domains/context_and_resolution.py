"""Coach turn helpers moved out of build_router (§五十二 extraction).

The helpers share one dependency bundle (``CoachSupportDeps``) assembled by
``build_router``. Keeping the bundle explicit makes the closure graph visible
instead of hiding 45 names inside a 25k-line function.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from ...core.models import (
    LearnerState,
    LearningPlan,
    SessionMessageRequest,
    TaskSpec,
    TeachingDecision,
    TeachingKnowledgeAsset,
    TurnRequest,
    UserProfile,
    WorkbenchSnapshot,
)
from ...llm.provider_service import (
    ProviderService,
)
from ...llm.training_review_context import active_training_review, apply_training_review_context
from ...memory.conversation_feedback import explanation_feedback
from ...memory.note_request import (
    message_requests_explicit_learning_note,
    message_requests_lecture_note_save,
)
from ...memory.proactive_budget import match_diagnostic_to_weakness
from ...memory.review_intervention import derive_review_budget
from ...memory.workspace_recovery import (
    accept_plan_runtime_resume_request,
    coach_focus_runtime_from_snapshot,
    live_plan_update_persist_chrome,
)
from ...pedagogy.productivity import (
    assess_conversation_productivity,
    recent_ledger_learning_output,
    trailing_unproductive_streak_start,
)
from ...training.card_request import message_requests_explicit_training_card
from .._helpers import (
    localized_text,
)
from ..router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from ..router_support import (
    _stamp_library_sandbox_work,
)
from ..router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from ..training_return_feedback import completed_return_feedback
from .types_and_deps import CoachSupportDeps, CoachTurnPayload


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
        "explicit_lecture_note_save_request": message_requests_lecture_note_save(message),
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
    feedback = None
    if getattr(request, "intent", "coach") == "coach":
        feedback = explanation_feedback(
            state.snapshot.messages,
            message=request.message,
            active_view=request.active_view,
        )
        if feedback:
            kind, reply_message_id = feedback
            deps.runtime.memory_service.record_user_feedback(
                workspace_id=state.workspace_id,
                kind=kind,
                message=request.message.strip()[:1000],
                scenario="explanation_revision",
                reply_message_id=reply_message_id,
            )
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
    # One read projection for the turn. Goal/Profile/Memory/Mastery/Evidence/
    # Review come from the same workspace-scoped LearnerState, not from
    # separately re-derived snapshots inside the coach path.
    learner_state_projection = None
    learner_state_service = getattr(deps.runtime, "learner_state_service", None)
    if learner_state_service is not None:
        learner_state_projection = learner_state_service.snapshot(state.workspace_id)
        if learner_state_projection.profile.value is not None:
            profile = learner_state_projection.profile.value
    decision_memory = (
        learner_state_projection.memory_snapshot
        if learner_state_projection is not None
        else state.snapshot.memory
    )
    projection_mastery = (
        learner_state_projection.mastery.value.get("dimensions")
        if learner_state_projection is not None
        and isinstance(learner_state_projection.mastery.value.get("dimensions"), dict)
        else None
    )
    pedagogy_learner_state_raw = deps.runtime.pedagogy_service.infer_learner_state(
        request=pedagogy_request,
        profile=profile,
        memory_snapshot=decision_memory,
    )
    modeled_learner_state = deps.model_learner_state(pedagogy_learner_state_raw)
    modeled_affect_state = deps.runtime.affect_service.infer_state(
        message=message,
        learner_state=modeled_learner_state or LearnerState(),
        memory_snapshot=decision_memory,
    )
    memory_workspace_payload = (
        decision_memory.workspace
        if isinstance(getattr(decision_memory, "workspace", None), dict)
        else {}
    )
    intervention_now = datetime.now(UTC)
    intervention_session_id = str(
        getattr(state, "session_id", "") or request.session_id or ""
    )
    review_budget = derive_review_budget(
        memory_workspace_payload,
        due_count=decision_memory.due_review_count,
        now=intervention_now,
        session_id=intervention_session_id,
        message=request.message,
    )
    if review_budget.message_refusal and review_budget.total_due > 0:
        deps.runtime.memory_service.record_review_refusal(
            state.workspace_id,
            reason=review_budget.message_refusal,
            session_id=intervention_session_id,
            now=intervention_now,
        )
    pedagogy_decision_raw = deps.runtime.pedagogy_service.decide_teaching(
        request=pedagogy_request,
        learner_state=pedagogy_learner_state_raw,
        profile=profile,
        memory_snapshot=decision_memory,
        affect_state=modeled_affect_state,
        skill_projection=(
            projection_mastery
            if projection_mastery is not None
            else memory_workspace_payload.get("training_skill_projection")
            if isinstance(memory_workspace_payload, dict)
            else None
        ),
        active_goal=(
            learner_state_projection.goal.value is not None
            if learner_state_projection is not None
            else None
        ),
        intervention_allowed=review_budget.allowed,
        intervention_reason=review_budget.reason,
    )
    if getattr(pedagogy_decision_raw, "turn_may_interrupt", False):
        deps.runtime.memory_service.record_review_offer(
            state.workspace_id,
            session_id=intervention_session_id,
            now=intervention_now,
        )
    elif not (review_budget.message_refusal and review_budget.total_due > 0):
        deps.runtime.memory_service.mark_workspace_active(
            state.workspace_id,
            now=intervention_now,
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
            decision_memory,
        )
        adaptive_bias = deps.runtime.pedagogy_service._adaptive_bias(decision_memory)  # noqa: SLF001
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
            memory_snapshot=decision_memory,
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
        memory_snapshot=decision_memory,
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
    if feedback:
        # The standard fresh-lane prompt drops history. A revision explicitly
        # depends on the prior reply in this same conversation.
        coach_context["history_mode"] = "resume"
        coach_context["relationship_stage"] = "active"
        coach_context["first_turn_priority"] = ""
    if getattr(request, "goal_mode", False):
        coach_context["goal_mode"] = True
    if completed_return and current_evaluation is not None and current_evaluation.passed:
        coach_context["completed_training_return_feedback"] = True
        coach_context["next_step_hint"] = current_evaluation.next_step
    if isinstance(request, TurnRequest) and request.intent == "plan" and request.formal_plan_mutation:
        coach_context["formal_plan_mutation"] = True
        coach_context["allow_coach_only_tools"] = True
    _stamp_library_sandbox_work(coach_context, request)
    streak_start = trailing_unproductive_streak_start(state.snapshot.messages)
    ledger_attempt, ledger_review = recent_ledger_learning_output(
        getattr(deps.runtime, "event_ledger", None),
        workspace_id=state.workspace_id,
        since=streak_start,
    )
    effective_answer_mode = str(
        request.answer_mode or (profile.answer_policy if profile else "") or ""
    ).strip().lower()
    decision_mode = (
        "direct_answer"
        if effective_answer_mode == "direct"
        else str(getattr(pedagogy_decision_raw, "mode", "") or "teach")
    )
    productivity = assess_conversation_productivity(
        messages=state.snapshot.messages,
        turn_mode=decision_mode,
        has_recent_attempt_or_evidence=bool(completed_return) or ledger_attempt,
        has_recent_review_action=ledger_review or scenario == "review",
    )
    if productivity.should_converge:
        coach_context["productivity_convergence"] = productivity.to_payload()
    # The Weakness Recall Cue (contract §7) is a few hundred characters and is computed in
    # every context tier. The minimal tier is a prompt and IO reduction for short questions,
    # never a behavior gate: a learner with a live error in the editor who types "and now?"
    # is exactly the case the cue exists for, and the tier resolver reads only the message.
    raw_cf = request.current_file
    raw_diagnostics = (
        raw_cf.get("diagnostics") if isinstance(raw_cf, dict) else getattr(raw_cf, "diagnostics", None)
    )
    live_diagnostics = list(raw_diagnostics or []) if raw_cf is not None else []
    if live_diagnostics:
        recorded_weaknesses: list[Any] = (
            deps.runtime.memory_service.weakness_records(state.workspace_id)
            or list(getattr(memory, "weaknesses", None) or [])
        )
        diagnostic_hit = match_diagnostic_to_weakness(live_diagnostics, recorded_weaknesses)
        if diagnostic_hit is not None:
            hint_concept, hint_diag = diagnostic_hit
            coach_context["diagnostic_weakness_hint"] = {
                "concept": hint_concept,
                "diagnostic": hint_diag[:160],
            }
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
