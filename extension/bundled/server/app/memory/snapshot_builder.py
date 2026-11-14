"""Memory snapshot assembly.

Extracted from ``MemoryService.snapshot`` so the service module stays focused on
writes and the snapshot's cache/projection rules have one owner. The builder
receives the live service (typed ``Any`` to avoid a circular import) and only
reads its public attributes/methods.
"""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, cast

from ..core.models import (
    LibraryAssetCatalogSnapshot,
    MemorySnapshot,
)
from .coaching_adaptation_mixin import (
    _localized_memory_text,
    _memory_language_context,
    _strip_visible_next_step_prefix,
)
from .models import utc_now
from .onboarding_extraction import _contains_chinese
from .review_queue import visible_review_queue_items
from .workspace_recovery import (
    PLAN_RUNTIME_KEY,
    apply_affect_tone_scope,
    apply_coaching_focus_scope,
    apply_current_task_scope,
    apply_evaluation_chrome_scope,
    apply_teaching_artifact_scope,
    apply_training_chrome_scope,
    leftover_bound_plan_competing_identity_labels,
    live_memory_snapshot_overlay,
    select_plan_runtime_for_scope,
    select_resources_for_scope,
)


def _prefers_chinese_text(context: str = "") -> bool:
    normalized_context = context.strip().lower()
    return normalized_context.startswith("zh") or _contains_chinese(context)


_GENERIC_NEXT_AFTER_CURRENT_EN = "Review the result and decide whether to widen scope."
_GENERIC_NEXT_AFTER_CURRENT_ZH = "复核结果，再决定是否扩大范围。"


def _localized_plan_next_after(plan, language_context: str):
    """Localize the English generic plan fallback for a Chinese workspace."""
    if plan is None or not _prefers_chinese_text(language_context):
        return plan
    if str(getattr(plan, "next_after_current", "") or "").strip() != _GENERIC_NEXT_AFTER_CURRENT_EN:
        return plan
    return plan.model_copy(update={"next_after_current": _GENERIC_NEXT_AFTER_CURRENT_ZH})


def _localize_plan_runtime_next_after(payload: dict, language_context: str) -> None:
    if not isinstance(payload, dict) or not _prefers_chinese_text(language_context):
        return
    for key in ("latest_plan_runtime", "latestPlanRuntime"):
        runtime = payload.get(key)
        if not isinstance(runtime, dict):
            continue
        if str(runtime.get("next_after_current") or "").strip() == _GENERIC_NEXT_AFTER_CURRENT_EN:
            runtime["next_after_current"] = _GENERIC_NEXT_AFTER_CURRENT_ZH

def build_memory_snapshot(service: Any, workspace_id: str) -> MemorySnapshot:
    repo_generation = getattr(service.repository, "write_generation", 0)
    time_bucket = int(time.time())
    cached = service._snapshot_cache.get(workspace_id)
    if (
        cached is not None
        and cached[0] == repo_generation
        and cached[1] == service._persist_generation
        and cached[2] == time_bucket
    ):
        # Fresh object graph per call: callers may mutate the returned
        # snapshot (e.g. rebind .workspace), so never hand out the master.
        return deepcopy(cached[3])
    context_id = service.repository.resolve_context_id(workspace_id)
    asset_catalog = (
        service._asset_library.catalog(context_id)
        if context_id
        else LibraryAssetCatalogSnapshot()
    )
    profile = service.repository.get_profile(workspace_id)
    global_memory = service.global_memory()
    plan = service.repository.get_latest_plan(workspace_id)
    plan_id = (plan.id or plan.plan_id) if plan else ""
    subplans = service.repository.list_subplans(plan_id) if plan_id else []
    resources = service.repository.list_resources(workspace_id)
    if callable(service._resource_dedupe_hook):
        resources = service._resource_dedupe_hook(resources)
    resources = select_resources_for_scope(resources, workspace_id)
    structured_service = service._structured_for(workspace_id)
    service._sync_dependency_training_views(structured_service)
    lane_snapshot = structured_service.snapshot()
    workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
    coach_defaults = service._coach_defaults_from_workspace(workspace)
    toggles = service._workspace_memory_toggles(workspace)
    memory_scope = service._memory_scope(workspace)
    personal_lane_snapshot = (
        service._build_personal_lane_snapshot(workspace_id, lane_snapshot)
        if memory_scope == "personal"
        else lane_snapshot
    )
    active_lane_snapshot = personal_lane_snapshot if memory_scope == "personal" else lane_snapshot
    active_thread = service._active_thread_snapshot(lane_snapshot)
    provider_recovery_blocked = service._is_provider_recovery_thread(
        lane_snapshot.workspace.get("active_thread")
    )
    workspace_understanding = service._workspace_understanding_snapshot(lane_snapshot)
    current_focus_context = _memory_language_context(
        workspace,
        service._workspace_value(active_lane_snapshot, "summary"),
        service._workspace_value(active_lane_snapshot, "focus_area"),
    )
    plan = _localized_plan_next_after(plan, current_focus_context)
    profile_goal = (
        profile.long_term_goal
        if profile and profile.long_term_goal
        else profile.long_term_goals[0]
        if profile and profile.long_term_goals
        else ""
    )
    if not profile_goal:
        for preference in getattr(active_lane_snapshot, "preferences", []):
            if preference.key == "long_term_goal":
                profile_goal = preference.value.strip()
                if profile_goal:
                    break
    raw_weakness_records = service._derive_weakness_records(resources, plan, active_lane_snapshot)
    visible_weakness_records = service._visible_weakness_records(raw_weakness_records)
    weaknesses = [item.reason for item in visible_weakness_records]
    reflections = [item.summary for item in active_lane_snapshot.reflections[-5:]]
    if not reflections:
        reflections = [
            _localized_memory_text(
                "Prefer spec-first feedback over direct answers.",
                "优先先对齐目标和约束，再决定要不要直接给答案。",
                current_focus_context,
            ),
            _localized_memory_text(
                "Track repeated boundary-condition misses.",
                "持续盯住那些容易被跳过的边界条件和验证点。",
                current_focus_context,
            ),
        ]
    if not toggles["decisions"]:
        reflections = reflections[:1]
    recent_summary = lane_snapshot.session.rolling_summary if lane_snapshot.session else ""
    session_highlights = lane_snapshot.session.highlights if lane_snapshot.session else []
    if not recent_summary:
        recent_summary = _localized_memory_text(
            "Trainer is maintaining a local memory snapshot for this workspace.",
            "教练正在为当前工作区持续维护一份本地训练记忆。",
            current_focus_context,
        )
    due_reviews = service._visible_due_reviews(
        service._prepend_transfer_review(
            service._derive_due_reviews(
                plan, active_lane_snapshot, raw_weakness_records,
                queue_actions=tuple(structured_service._review_queue_actions),
                reviewable_card_ids={
                    card.card_id for card in structured_service._training_cards.values()
                    if card.status not in {"archived", "skipped"}
                },
            ),
            active_lane_snapshot,
        )
    )
    due_reviews = visible_review_queue_items(
        due_reviews, structured_service._review_queue_actions,
        structured_service._weaknesses, now=utc_now(),
    )
    teaching_observations = service._derive_teaching_observations(
        plan,
        active_lane_snapshot,
        visible_weakness_records,
        language_context=current_focus_context,
    )
    recent_wins = service._derive_recent_wins(plan, resources, active_lane_snapshot)
    current_focus = service._derive_current_focus(
        plan,
        recent_summary,
        active_lane_snapshot,
        language_context=current_focus_context,
    )
    review_rhythm = service._derive_review_rhythm(due_reviews, active_lane_snapshot)
    coach_anchor = service._derive_coach_anchor(plan, active_lane_snapshot)
    top_weakness = service._top_actionable_weakness(raw_weakness_records)
    lowest_mastery_concepts = service._derive_lowest_mastery_concepts(active_lane_snapshot)
    pace_signal = service._derive_pace_signal(plan, due_reviews, active_lane_snapshot)
    remembered_preference_record = service._preferred_preference(active_lane_snapshot)
    remembered_preference_text = ""
    preference_summary = service._summarize_preferences(active_lane_snapshot)
    personal_transfer_summary = service._personal_transfer_observation(active_lane_snapshot)
    decision_summary = service._summarize_decisions(active_lane_snapshot)
    progress_summary = service._summarize_progress(active_lane_snapshot)
    goal_summary = service._summarize_goal(profile_goal, active_lane_snapshot)
    latest_turn_summary = service._summarize_latest_turn(active_lane_snapshot)
    teaching_signal_summary = service._summarize_teaching_signal(active_lane_snapshot)
    weakness_pattern_summary = service._summarize_weakness_patterns(active_lane_snapshot)
    prefers_chinese = _prefers_chinese_text(
        " ".join(
            [
                current_focus_context,
                recent_summary,
                active_lane_snapshot.session.rolling_summary if active_lane_snapshot.session else "",
            ]
        )
    )
    if (
        remembered_preference_record
        and toggles["decisions"]
        and memory_scope != "session"
        and not provider_recovery_blocked
    ):
        remembered_preference_text = _localized_memory_text(
            f"Remembered preference: {remembered_preference_record.key} = {remembered_preference_record.value}",
            f"已记住你的偏好：{remembered_preference_record.key} = {remembered_preference_record.value}",
            current_focus_context or recent_summary or remembered_preference_record.value,
        )
    if provider_recovery_blocked:
        pass
    elif memory_scope == "session":
        thread_focus = active_thread.focus_area if active_thread else ""
        thread_next_step = (
            _strip_visible_next_step_prefix(active_thread.next_step) if active_thread else ""
        )
        session_anchor = thread_next_step or (lane_snapshot.session.rolling_summary if lane_snapshot.session else "")
        if thread_focus or session_anchor:
            current_focus = _localized_memory_text(
                f"Current coaching focus: stay on the live session thread around '{thread_focus}' and keep the next reply attached to: {session_anchor}"
                if thread_focus and session_anchor
                else f"Current coaching focus: stay on the live session thread and keep the next reply attached to: {session_anchor or thread_focus}",
                f"当前聚焦：先紧贴这次会话里正在推进的主线继续，不要切题。下一轮继续接着这一步：{session_anchor}"
                if session_anchor
                else f"当前聚焦：先紧贴这次会话里正在推进的主线继续，不要切题。当前主线是：{thread_focus}",
                current_focus_context or recent_summary or thread_focus or session_anchor,
            )
        if lane_snapshot.session and lane_snapshot.session.rolling_summary:
            recent_summary = lane_snapshot.session.rolling_summary
        if lane_snapshot.session and lane_snapshot.session.highlights:
            recent_wins = lane_snapshot.session.highlights[-3:] + recent_wins
        due_reviews = due_reviews[:1]
        current_focus = (
            f"{current_focus} 当前记忆范围：仅本次会话。"
            if prefers_chinese
            else f"{current_focus} Memory scope is session."
        )
    elif memory_scope == "personal":
        base_focus = current_focus
        personal_prefix = (
            _localized_memory_text(
                f"Long-term goal remains in view: {profile_goal}.",
                f"长期目标仍在前面：{profile_goal}。",
                current_focus_context or recent_summary or profile_goal,
            )
            if goal_summary
            else _localized_memory_text(
                "Personal memory is active, so keep the reusable habits and judgment in play.",
                "个人长期记忆已开启，继续把那些可迁移的习惯和判断带在身上。",
                current_focus_context or recent_summary or current_focus,
            )
        )
        if preference_summary:
            personal_prefix = f"{personal_prefix} {preference_summary}".strip()
        current_focus = f"{base_focus} {personal_prefix}".strip()
        if remembered_preference_text:
            recent_wins = [remembered_preference_text] + recent_wins
        if personal_transfer_summary and personal_transfer_summary not in teaching_observations:
            teaching_observations = [personal_transfer_summary, *teaching_observations][:4]
        if teaching_signal_summary and teaching_signal_summary not in teaching_observations:
            teaching_observations = [teaching_signal_summary, *teaching_observations][:4]
        if weakness_pattern_summary and weakness_pattern_summary not in teaching_observations:
            teaching_observations = [weakness_pattern_summary, *teaching_observations][:4]
        if active_lane_snapshot.mastery:
            lowest_mastery_concepts = service._derive_lowest_mastery_concepts(active_lane_snapshot)[:2]
        current_focus = (
            f"{current_focus} 当前记忆范围：个人长期记忆。"
            if prefers_chinese
            else f"{current_focus} Memory scope is personal."
        )
    else:
        current_focus = current_focus.strip()
    if (
        not provider_recovery_blocked
        and coach_defaults.get("working_set_mode") == "focused"
        and current_focus
    ):
        current_focus = _localized_memory_text(
            f"{current_focus} Focused working set: stay tight on the smallest verifiable slice and only the nearest files.",
            f"{current_focus} 当前工作集策略：尽量只盯住最小可验证切片和最近的相关文件。",
            current_focus,
        )
    elif (
        not provider_recovery_blocked
        and coach_defaults.get("working_set_mode") == "broad"
        and current_focus
    ):
        current_focus = _localized_memory_text(
            f"{current_focus} You may widen into directly connected context if it helps verify the patch.",
            f"{current_focus} 如果有助于验证这次改动，可以适度带上直接相关的更宽上下文。",
            current_focus,
        )
    teaching_observations = teaching_observations[:4]

    def ensure_observation(value: str, preferred_index: int | None = None) -> None:
        nonlocal teaching_observations
        if not value:
            return
        if value in teaching_observations:
            return
        if preferred_index is None:
            if len(teaching_observations) < 4:
                teaching_observations.append(value)
            else:
                teaching_observations[-1] = value
            return
        bounded_index = max(0, min(preferred_index, len(teaching_observations)))
        teaching_observations.insert(bounded_index, value)
        teaching_observations = teaching_observations[:4]

    if not provider_recovery_blocked and preference_summary and toggles["decisions"]:
        ensure_observation(preference_summary, preferred_index=2)
    if not provider_recovery_blocked and goal_summary:
        ensure_observation(goal_summary, preferred_index=2)
    if not provider_recovery_blocked and teaching_signal_summary and toggles["patterns"]:
        ensure_observation(teaching_signal_summary)
    if not provider_recovery_blocked and weakness_pattern_summary:
        ensure_observation(weakness_pattern_summary)
    if not provider_recovery_blocked and remembered_preference_text and toggles["decisions"]:
        ensure_observation(remembered_preference_text, preferred_index=3)
    if not provider_recovery_blocked and latest_turn_summary:
        ensure_observation(latest_turn_summary, preferred_index=1)
    if (
        not provider_recovery_blocked
        and decision_summary
        and toggles["decisions"]
        and decision_summary not in recent_wins
    ):
        recent_wins = [decision_summary, *recent_wins][:3]
    if (
        not provider_recovery_blocked
        and goal_summary
        and goal_summary not in recent_wins
        and memory_scope == "personal"
    ):
        recent_wins = [goal_summary, *recent_wins][:3]
    if (
        not provider_recovery_blocked
        and personal_transfer_summary
        and personal_transfer_summary not in recent_wins
        and memory_scope == "personal"
    ):
        recent_wins = [personal_transfer_summary, *recent_wins][:3]
    if (
        not provider_recovery_blocked
        and
        remembered_preference_text
        and remembered_preference_text not in recent_wins
        and memory_scope == "personal"
    ):
        recent_wins = [remembered_preference_text, *recent_wins][:3]
    if session_highlights and memory_scope != "project":
        recent_summary = " ".join([recent_summary, *session_highlights[-2:]]).strip()
    active_thread_next_step = (
        str(active_thread.next_step or "").strip() if active_thread and active_thread.next_step else ""
    )
    progress_repeats_active_thread_next_step = (
        bool(active_thread_next_step)
        and active_thread_next_step in current_focus
        and active_thread_next_step in progress_summary
    )
    if (
        not provider_recovery_blocked
        and progress_summary
        and toggles["patterns"]
        and progress_summary not in current_focus
        and not progress_repeats_active_thread_next_step
    ):
        current_focus = f"{current_focus} {progress_summary}".strip()
    if not toggles["patterns"]:
        recent_wins = [item for item in recent_wins if "progress" not in item.lower()]
    if not toggles["resources"]:
        resources = []

    foreground_observation = teaching_observations[0] if teaching_observations else ""
    preferred_observation = remembered_preference_text or (
        preference_summary if toggles["decisions"] else ""
    )
    curated_teaching_observations: list[str] = []

    def append_curated_observation(value: str) -> None:
        cleaned = value.strip()
        if not cleaned or cleaned in curated_teaching_observations:
            return
        curated_teaching_observations.append(cleaned)

    if provider_recovery_blocked:
        for candidate in (
            foreground_observation,
            latest_turn_summary,
        ):
            append_curated_observation(candidate)
    elif memory_scope == "personal":
        for candidate in (
            weakness_pattern_summary,
            personal_transfer_summary,
            preferred_observation,
            goal_summary,
            latest_turn_summary,
            foreground_observation,
            teaching_signal_summary,
        ):
            append_curated_observation(candidate)
    else:
        for candidate in (
            foreground_observation,
            latest_turn_summary,
            service._onboarding_blocker_summary(active_lane_snapshot),
            preferred_observation,
            goal_summary,
            weakness_pattern_summary,
            teaching_signal_summary,
        ):
            append_curated_observation(candidate)

    for candidate in teaching_observations:
        append_curated_observation(candidate)

    transfer_observation = service._transfer_skill_observation(active_lane_snapshot)
    if transfer_observation:
        curated_teaching_observations = [
            transfer_observation,
            *[item for item in curated_teaching_observations if item != transfer_observation],
        ]
    teaching_observations = curated_teaching_observations[:4]
    workspace_payload = dict(lane_snapshot.workspace)
    workspace_payload["coach_habit"] = (
        global_memory.coach_habit.model_dump(mode="json") if global_memory.coach_habit else None
    )
    workspace_payload.setdefault("workspace_id", workspace_id)
    _localize_plan_runtime_next_after(workspace_payload, current_focus_context)
    user_feedback_items = [
        {
            "kind": item.kind,
            "message": item.message,
            "focus_area": item.focus_area,
            "scenario": item.scenario,
            "training_card_id": item.training_card_id,
            "plan_id": item.plan_id,
            "created_at": item.created_at.isoformat(),
        }
        for item in active_lane_snapshot.user_feedback[:8]
    ]
    teaching_strategy_items = [
        {
            "key": item.key,
            "scenario": item.scenario,
            "focus_area": item.focus_area,
            "challenge_level": item.challenge_level,
            "hint_depth": item.hint_depth,
            "review_urgency": item.review_urgency,
            "explanation_mode": item.explanation_mode,
            "next_step_bias": item.next_step_bias,
            "success_count": item.success_count,
            "failure_count": item.failure_count,
            "total_count": item.total_count,
            "last_outcome": item.last_outcome,
            "last_summary": item.last_summary,
            "last_verified_result": item.last_verified_result,
            "last_updated_at": item.last_updated_at.isoformat(),
        }
        for item in active_lane_snapshot.teaching_strategy_effectiveness[:6]
    ]
    learning_outcome_items = [
        {
            "concept": item.concept,
            "outcome": item.outcome,
            "summary": item.summary,
            "checks": list(item.checks),
            "missing_requirements": list(item.missing_requirements),
            "repetition_count": item.repetition_count,
            "action_type": item.action_type,
            "updated_at": item.updated_at.isoformat(),
        }
        for item in active_lane_snapshot.learning_outcomes[:8]
    ]
    recovered = select_plan_runtime_for_scope(
        workspace_payload.get(PLAN_RUNTIME_KEY) or workspace_payload.get("latestPlanRuntime"),
        workspace_id,
    )
    teaching_asset_items = service.list_teaching_assets(workspace_id=workspace_id)
    training_card_items = service.get_cards(workspace_id)
    leftover_plans: list[Any] | tuple[Any, ...] | None = []
    list_plans = getattr(service.repository, "list_plans", None)
    if callable(list_plans):
        leftover_plans = cast("list[Any]", list_plans(workspace_id))
    competing_identity = leftover_bound_plan_competing_identity_labels(
        plan=plan,
        runtime=recovered if isinstance(recovered, dict) else {},
        existing=recovered if isinstance(recovered, dict) else {},
        card_titles=[
            str(getattr(card, "title", "") or "")
            for card in training_card_items
        ],
        leftover_plans=leftover_plans,
    )
    if competing_identity:
        resources = [
            item
            for item in resources
            if str(getattr(item, "name", "") or getattr(item, "title", "") or "").strip()
            not in competing_identity
        ]
    review_artifact_item = structured_service._review_artifact
    dependency_mastery = service._dependency_mastery_snapshots(structured_service)
    flash_deck = structured_service._flash_deck or (
        service._build_flash_deck_snapshot(structured_service) if dependency_mastery else None
    )
    scenario_lab_item = structured_service._scenario_lab
    theory_drill = structured_service._theory_drill or service._build_theory_drill_snapshot(structured_service)
    snapshot_overlay = live_memory_snapshot_overlay(
        plan=plan,
        runtime=recovered,
        existing=recovered,
        recent_summary=recent_summary,
        workspace=workspace_payload,
        active_thread=active_thread,
        teaching_observations=teaching_observations,
        user_feedback=user_feedback_items,
        recent_wins=recent_wins,
        weaknesses=weaknesses,
        teaching_strategy_effectiveness=teaching_strategy_items,
        learning_outcomes=learning_outcome_items,
        top_weakness=top_weakness,
        reflections=reflections,
        lowest_mastery_concepts=lowest_mastery_concepts,
        due_reviews=[
            {
                "concept": item.concept,
                "reason": item.reason,
                "focus_area": item.focus_area,
                "task_hint": item.task_hint,
            }
            for item in due_reviews
        ],
        teaching_assets=[
            {
                "title": item.title,
                "summary": item.summary,
                "focus_area": item.focus_area,
                "concept_card": item.concept_card,
                "source_summary": item.source_summary,
            }
            for item in teaching_asset_items
        ],
        training_cards=[
            {
                "title": item.title,
                "why_now": item.why_now,
                "focus_area": item.focus_area,
                "target_skill": item.target_skill,
                "problem_statement": item.problem_statement,
                "question": item.question,
                "scenario": item.scenario,
                "suggested_workspace_action": item.suggested_workspace_action,
                "deliverable": item.deliverable,
                "context": item.context,
                "expected_answer": item.expected_answer,
                "stuck_recovery": item.stuck_recovery,
                "reflection_prompt": item.reflection_prompt,
                "success_signal": item.success_signal,
                "return_with": item.return_with,
                "next_after_completion": item.next_after_completion,
                "learner_deliverables": list(item.learner_deliverables),
                "next_steps": list(item.next_steps),
            }
            for item in training_card_items
        ],
        review_artifact=(
            {
                "title": review_artifact_item.title,
                "focus_area": review_artifact_item.focus_area,
                "summary": review_artifact_item.summary,
                "root_cause": review_artifact_item.root_cause,
                "guardrail": review_artifact_item.guardrail,
                "verified_result": review_artifact_item.verified_result,
                "blocker": review_artifact_item.blocker,
            }
            if review_artifact_item is not None
            else None
        ),
        review_artifact_history=[
            {
                "note": item.note,
                "before_snapshot": dict(item.before_snapshot),
                "after_snapshot": dict(item.after_snapshot),
            }
            for item in structured_service._review_artifact_history
        ],
        scenario_lab=(
            {
                "title": scenario_lab_item.title,
                "focus_area": scenario_lab_item.focus_area,
                "summary": scenario_lab_item.summary,
                "success_signal": scenario_lab_item.success_signal,
                "review_outcome": scenario_lab_item.review_outcome,
                "learner_deliverables": list(scenario_lab_item.learner_deliverables),
                "verification_steps": list(scenario_lab_item.verification_steps),
                "migrate_back_guidance": list(scenario_lab_item.migrate_back_guidance),
            }
            if scenario_lab_item is not None
            else None
        ),
        scenario_lab_history=[
            {
                "note": item.note,
                "before_snapshot": dict(item.before_snapshot),
                "after_snapshot": dict(item.after_snapshot),
            }
            for item in structured_service._scenario_lab_history
        ],
        flash_deck=(
            {
                "title": flash_deck.title,
                "focus_area": flash_deck.focus_area,
                "cards": [
                    {
                        "title": card.title,
                        "why_now": card.why_now,
                        "focus_area": card.focus_area,
                        "target_skill": card.target_skill,
                        "problem_statement": card.problem_statement,
                        "question": card.question,
                        "scenario": card.scenario,
                        "deliverable": card.deliverable,
                        "success_signal": card.success_signal,
                    }
                    for card in flash_deck.cards
                ],
            }
            if flash_deck is not None
            else None
        ),
        theory_drill=(
            {
                "title": theory_drill.title,
                "focus_area": theory_drill.focus_area,
                "summary": theory_drill.summary,
                "success_signal": theory_drill.success_signal,
                "return_with": theory_drill.return_with,
                "questions": [
                    {
                        "prompt": question.prompt,
                        "answer": question.answer,
                        "explanation": question.explanation,
                        "knowledge_type": question.knowledge_type,
                        "choices": list(question.choices),
                    }
                    for question in theory_drill.questions
                ],
            }
            if theory_drill is not None
            else None
        ),
        theory_drill_history=[
            {
                "note": item.note,
                "before_snapshot": dict(item.before_snapshot),
                "after_snapshot": dict(item.after_snapshot),
            }
            for item in structured_service._theory_drill_history
        ],
    )
    recent_summary = snapshot_overlay["recent_summary"]
    workspace_payload = apply_teaching_artifact_scope(
        apply_affect_tone_scope(
            apply_evaluation_chrome_scope(
                apply_coaching_focus_scope(
                    apply_current_task_scope(
                        apply_training_chrome_scope(
                            snapshot_overlay["workspace"],
                            workspace_id,
                        ),
                        workspace_id,
                    ),
                    workspace_id,
                ),
                workspace_id,
            ),
            workspace_id,
        ),
        workspace_id,
    )
    # Keep the recovered runtime step visible after all scope/gating passes,
    # but only while a live card selection still owns it. A skipped/archived
    # selection was already released above; re-adding its runtime step here
    # would resurrect the dead card as a "next hop" in Training.
    current_runtime = structured_service._workspace.get(PLAN_RUNTIME_KEY)
    recovered_step = str(
        (current_runtime or {}).get("current_step")
        or (recovered or {}).get("current_step")
        or ""
    ).strip()
    live_selected_card_id = str(workspace_payload.get("selected_card_id") or "").strip()
    if recovered_step and live_selected_card_id:
        current_hop = workspace_payload.get("latest_training_next_hop")
        if not isinstance(current_hop, dict):
            current_hop = structured_service._workspace.get("latest_training_next_hop")
        workspace_payload["latest_training_next_hop"] = {
            **(current_hop if isinstance(current_hop, dict) else {}),
            "title": recovered_step,
            "card_title": recovered_step,
        }
    teaching_observations = snapshot_overlay["teaching_observations"]
    user_feedback_items = snapshot_overlay["user_feedback"]
    recent_wins = snapshot_overlay["recent_wins"]
    weaknesses = snapshot_overlay["weaknesses"]
    teaching_strategy_items = snapshot_overlay["teaching_strategy_effectiveness"]
    learning_outcome_items = snapshot_overlay["learning_outcomes"]
    top_weakness = snapshot_overlay["top_weakness"]
    reflections = snapshot_overlay["reflections"]
    lowest_mastery_concepts = snapshot_overlay["lowest_mastery_concepts"]
    due_reviews = [
        item.model_copy(
            update={
                "concept": payload.get("concept", item.concept),
                "reason": payload.get("reason", item.reason),
                "focus_area": payload.get("focus_area", item.focus_area),
                "task_hint": payload.get("task_hint", item.task_hint),
            }
        )
        for item, payload in zip(due_reviews, snapshot_overlay["due_reviews"], strict=True)
    ]
    teaching_asset_items = [
        item.model_copy(
            update={
                "title": payload.get("title", item.title),
                "summary": payload.get("summary", item.summary),
                "focus_area": payload.get("focus_area", item.focus_area),
                "concept_card": payload.get("concept_card", item.concept_card),
                "source_summary": payload.get("source_summary", item.source_summary),
            }
        )
        for item, payload in zip(teaching_asset_items, snapshot_overlay["teaching_assets"], strict=True)
    ]
    training_card_items = [
        item.model_copy(
            update={
                "title": payload.get("title", item.title),
                "why_now": payload.get("why_now", item.why_now),
                "focus_area": payload.get("focus_area", item.focus_area),
                "target_skill": payload.get("target_skill", item.target_skill),
                "problem_statement": payload.get("problem_statement", item.problem_statement),
                "question": payload.get("question", item.question),
                "scenario": payload.get("scenario", item.scenario),
                "suggested_workspace_action": payload.get(
                    "suggested_workspace_action",
                    item.suggested_workspace_action,
                ),
                "deliverable": payload.get("deliverable", item.deliverable),
                "context": payload.get("context", item.context),
                "expected_answer": payload.get("expected_answer", item.expected_answer),
                "stuck_recovery": payload.get("stuck_recovery", item.stuck_recovery),
                "reflection_prompt": payload.get("reflection_prompt", item.reflection_prompt),
                "success_signal": payload.get("success_signal", item.success_signal),
                "return_with": payload.get("return_with", item.return_with),
                "next_after_completion": payload.get(
                    "next_after_completion",
                    item.next_after_completion,
                ),
                "learner_deliverables": payload.get(
                    "learner_deliverables",
                    item.learner_deliverables,
                ),
                "next_steps": payload.get("next_steps", item.next_steps),
            }
        )
        for item, payload in zip(training_card_items, snapshot_overlay["training_cards"], strict=True)
    ]
    if review_artifact_item is not None and snapshot_overlay["review_artifact"]:
        gated_artifact = snapshot_overlay["review_artifact"]
        review_artifact_item = review_artifact_item.model_copy(
            update={
                "title": gated_artifact.get("title", review_artifact_item.title),
                "focus_area": gated_artifact.get("focus_area", review_artifact_item.focus_area),
                "summary": gated_artifact.get("summary", review_artifact_item.summary),
                "root_cause": gated_artifact.get("root_cause", review_artifact_item.root_cause),
                "guardrail": gated_artifact.get("guardrail", review_artifact_item.guardrail),
                "verified_result": gated_artifact.get(
                    "verified_result",
                    review_artifact_item.verified_result,
                ),
                "blocker": gated_artifact.get("blocker", review_artifact_item.blocker),
            }
        )
    review_artifact_history_items = [
        item.model_copy(
            update={
                "note": payload.get("note", item.note),
                "before_snapshot": payload.get("before_snapshot", item.before_snapshot),
                "after_snapshot": payload.get("after_snapshot", item.after_snapshot),
            }
        )
        for item, payload in zip(
            structured_service._review_artifact_history,
            snapshot_overlay["review_artifact_history"],
            strict=True,
        )
    ]
    if scenario_lab_item is not None and snapshot_overlay["scenario_lab"]:
        gated_lab = snapshot_overlay["scenario_lab"]
        scenario_lab_item = scenario_lab_item.model_copy(
            update={
                "title": gated_lab.get("title", scenario_lab_item.title),
                "focus_area": gated_lab.get("focus_area", scenario_lab_item.focus_area),
                "summary": gated_lab.get("summary", scenario_lab_item.summary),
                "success_signal": gated_lab.get("success_signal", scenario_lab_item.success_signal),
                "review_outcome": gated_lab.get("review_outcome", scenario_lab_item.review_outcome),
                "learner_deliverables": gated_lab.get(
                    "learner_deliverables",
                    scenario_lab_item.learner_deliverables,
                ),
                "verification_steps": gated_lab.get(
                    "verification_steps",
                    scenario_lab_item.verification_steps,
                ),
                "migrate_back_guidance": gated_lab.get(
                    "migrate_back_guidance",
                    scenario_lab_item.migrate_back_guidance,
                ),
            }
        )
    scenario_lab_history_items = [
        item.model_copy(
            update={
                "note": payload.get("note", item.note),
                "before_snapshot": payload.get("before_snapshot", item.before_snapshot),
                "after_snapshot": payload.get("after_snapshot", item.after_snapshot),
            }
        )
        for item, payload in zip(
            structured_service._scenario_lab_history,
            snapshot_overlay["scenario_lab_history"],
            strict=True,
        )
    ]
    if flash_deck is not None and snapshot_overlay["flash_deck"]:
        gated_deck = snapshot_overlay["flash_deck"]
        gated_flash_cards = list(gated_deck.get("cards") or [])
        flash_deck = flash_deck.model_copy(
            update={
                "title": gated_deck.get("title", flash_deck.title),
                "focus_area": gated_deck.get("focus_area", flash_deck.focus_area),
                "cards": [
                    card.model_copy(
                        update={
                            "title": payload.get("title", card.title),
                            "why_now": payload.get("why_now", card.why_now),
                            "focus_area": payload.get("focus_area", card.focus_area),
                            "target_skill": payload.get("target_skill", card.target_skill),
                            "problem_statement": payload.get(
                                "problem_statement",
                                card.problem_statement,
                            ),
                            "question": payload.get("question", card.question),
                            "scenario": payload.get("scenario", card.scenario),
                            "deliverable": payload.get("deliverable", card.deliverable),
                            "success_signal": payload.get("success_signal", card.success_signal),
                        }
                    )
                    for card, payload in zip(flash_deck.cards, gated_flash_cards, strict=True)
                ],
            }
        )
    if theory_drill is not None and snapshot_overlay["theory_drill"]:
        gated_drill = snapshot_overlay["theory_drill"]
        gated_questions = list(gated_drill.get("questions") or [])
        theory_drill = theory_drill.model_copy(
            update={
                "title": gated_drill.get("title", theory_drill.title),
                "focus_area": gated_drill.get("focus_area", theory_drill.focus_area),
                "summary": gated_drill.get("summary", theory_drill.summary),
                "success_signal": gated_drill.get("success_signal", theory_drill.success_signal),
                "return_with": gated_drill.get("return_with", theory_drill.return_with),
                "questions": [
                    question.model_copy(
                        update={
                            "prompt": payload.get("prompt", question.prompt),
                            "answer": payload.get("answer", question.answer),
                            "explanation": payload.get("explanation", question.explanation),
                            "knowledge_type": payload.get(
                                "knowledge_type",
                                question.knowledge_type,
                            ),
                            "choices": payload.get("choices", question.choices),
                        }
                    )
                    for question, payload in zip(theory_drill.questions, gated_questions, strict=True)
                ],
            }
        )
    theory_drill_history_items = [
        item.model_copy(
            update={
                "note": payload.get("note", item.note),
                "before_snapshot": payload.get("before_snapshot", item.before_snapshot),
                "after_snapshot": payload.get("after_snapshot", item.after_snapshot),
            }
        )
        for item, payload in zip(
            structured_service._theory_drill_history,
            snapshot_overlay["theory_drill_history"],
            strict=True,
        )
    ]
    if active_thread is not None and snapshot_overlay["active_thread"]:
        active_thread = active_thread.model_copy(update=snapshot_overlay["active_thread"])
    dependency_skill_maps = list(structured_service._dependency_skill_maps.values())
    evidence_queue = service.evidence_queue(workspace_id)
    coaching_adaptation = service._derive_coaching_adaptation_profile(
        active_lane_snapshot,
        profile=profile,
        plan=plan,
        due_reviews=due_reviews,
        workspace_id=workspace_id,
    )
    if coaching_adaptation is not None:
        gated_adaptation = live_memory_snapshot_overlay(
            plan=plan,
            runtime=recovered,
            existing=recovered,
            coaching_adaptation={
                "summary": coaching_adaptation.summary,
                "evidence": list(coaching_adaptation.evidence),
            },
        )["coaching_adaptation"]
        coaching_adaptation = coaching_adaptation.model_copy(
            update={
                "summary": gated_adaptation.get("summary", ""),
                "evidence": list(gated_adaptation.get("evidence") or []),
            }
        )
    # Read-side guard: a terminal card must never be exposed as the live
    # selection. Existing profiles can still carry a selected_card_id that
    # was skipped/archived before the write-side release landed; clearing it
    # here keeps Training from rendering an unactionable card after restart.
    selected_card_id = str(workspace_payload.get("selected_card_id") or "").strip()
    if selected_card_id:
        selected_card = next(
            (item for item in training_card_items if item.card_id == selected_card_id),
            None,
        )
        if selected_card is None or selected_card.status in {"skipped", "archived"}:
            workspace_payload["selected_card_id"] = ""
            workspace_payload["selected_card_status"] = ""
            workspace_payload["latest_training_next_hop"] = {}
            workspace_payload["live_training_selection"] = {}
            live_handoff = workspace_payload.get("latest_training_handoff")
            if isinstance(live_handoff, dict) and selected_card_id in {
                str(live_handoff.get("card_id") or "").strip(),
                str(live_handoff.get("candidate_id") or "").strip(),
                str(live_handoff.get("target_id") or "").strip(),
            }:
                workspace_payload["latest_training_handoff"] = {}
            if (
                structured_service._active_training_card_routing is not None
                and structured_service._active_training_card_routing.selected_card_id
                == selected_card_id
            ):
                structured_service._active_training_card_routing = None
    structured_service.sync_active_card_routing()
    snapshot = MemorySnapshot(
        profile=profile,
        globalMemory=global_memory,
        active_plan=plan,
        subplans=subplans,
        resources=resources,
        assetCatalog=asset_catalog,
        teaching_assets=teaching_asset_items,
        memory_share_grants=service.list_memory_share_grants(workspace_id),
        coaching_adaptation=coaching_adaptation,
        teaching_strategy_effectiveness=teaching_strategy_items,
        learning_outcomes=learning_outcome_items,
        weaknesses=weaknesses,
        reflections=reflections,
        recent_summary=recent_summary,
        current_focus=current_focus,
        coach_anchor=coach_anchor,
        top_weakness=top_weakness,
        lowest_mastery_concepts=lowest_mastery_concepts,
        recent_wins=recent_wins,
        review_rhythm=review_rhythm,
        due_reviews=due_reviews,
        due_review_count=len(due_reviews),
        pace_signal=pace_signal,
        teaching_observations=teaching_observations,
        userFeedback=user_feedback_items,
        workspace=workspace_payload,
        active_thread=active_thread,
        workspace_understanding=workspace_understanding,
        dependency_mastery=dependency_mastery,
        dependency_skill_maps=dependency_skill_maps,
        dependency_skill_map_history=list(structured_service._dependency_skill_map_history),
        flash_deck=flash_deck,
        recent_flash_attempts=list(structured_service._recent_flash_attempts),
        theory_drill=theory_drill,
        theory_drill_history=theory_drill_history_items,
        scenario_lab=scenario_lab_item,
        scenario_lab_history=scenario_lab_history_items,
        review_queue_actions=list(structured_service._review_queue_actions),
        review_artifact=review_artifact_item,
        review_artifact_history=review_artifact_history_items,
        training_card_candidates=training_card_items,
        active_training_card_routing=structured_service._active_training_card_routing,
        training_event_ledger=list(structured_service._training_event_ledger),
        evidence_queue=evidence_queue,
        planChangeCandidates=service.repository.list_plan_change_candidates(workspace_id),
    )
    snapshot.teaching_knowledge_catalog = service.teaching_knowledge_catalog(workspace_id, snapshot=snapshot)
    snapshot.memory_evidence = live_memory_snapshot_overlay(
        plan=plan,
        runtime=recovered,
        existing=recovered,
        memory_evidence=service._build_memory_evidence(snapshot, limit=5),
    )["memory_evidence"]
    # The persisted runtime is authoritative over any stale gated chrome.
    current_runtime = structured_service._workspace.get(PLAN_RUNTIME_KEY)
    current_step = str((current_runtime or {}).get("current_step") or "").strip()
    if current_step and isinstance(snapshot.workspace, dict):
        current_hop = snapshot.workspace.get("latest_training_next_hop")
        snapshot.workspace["latest_training_next_hop"] = {
            **(current_hop if isinstance(current_hop, dict) else {}),
            "title": current_step,
            "card_title": current_step,
        }
    service._persist_structured(workspace_id)
    service._snapshot_cache[workspace_id] = (
        getattr(service.repository, "write_generation", 0),
        service._persist_generation,
        time_bucket,
        snapshot,
    )
    return snapshot
