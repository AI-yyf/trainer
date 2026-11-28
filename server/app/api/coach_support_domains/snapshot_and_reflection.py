"""Coach turn helpers moved out of build_router (§五十二 extraction).

The helpers share one dependency bundle (``CoachSupportDeps``) assembled by
``build_router``. Keeping the bundle explicit makes the closure graph visible
instead of hiding 45 names inside a 25k-line function.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from pydantic import ValidationError

from ...core.models import (
    CoachDefaults,
    CoachTurnSummary,
    FirstLookSummary,
    SuggestedAction,
    TaskSpec,
    UserProfile,
    WorkbenchSnapshot,
)
from ...llm.turn_grounding import (
    GroundingDecision,
    sanitize_memory_anchor,
)
from ...memory.workspace_recovery import (
    PLAN_RUNTIME_KEY,
    coach_focus_runtime_from_snapshot,
    leftover_bound_plan_competing_identity_labels,
    leftover_coach_conversation_is_not_live,
    leftover_evaluation_headline_is_not_live,
    leftover_first_look_headline_is_not_live,
    leftover_formal_plan_is_live_for_fill,
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
    live_evidence_binding,
    prefer_recovered_coach_turn_chrome,
    prefer_recovered_training_focus_chrome,
    prefer_recovered_training_handoff_chrome,
    prefer_recovered_transfer_skill,
    resource_record_is_acknowledged_upload,
    stamp_produced_workspace_record,
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
from .artifacts_and_state import _scrub_bogus_smalltalk_steps
from .types_and_deps import CoachSupportDeps

logger = logging.getLogger(__name__)


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
    from ...pedagogy.coach_orientation import (
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
    _scrub_bogus_smalltalk_steps(snapshot)
    workspace_memory = snapshot.memory.workspace if isinstance(snapshot.memory.workspace, dict) else {}
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
    from ...pedagogy.stage_material_state import stage_material_state

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
        except Exception as exc:
            logger.debug("Ignoring invalid coach_defaults payload: %s", exc)
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
