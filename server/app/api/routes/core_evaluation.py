"""Task specification, deterministic file/snippet evaluation, learning signals, and plan candidates."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ...core.models import (
    EvaluateCurrentFileRequest,
    EvaluateSnippetRequest,
    LearningSignalRequest,
    PlanChangeCandidate,
    TaskNextRequest,
    TaskSpec,
    TaskSpecifyRequest,
    UserFeedbackRequest,
    WorkbenchSnapshot,
)
from ...memory.workspace_recovery import (
    PLAN_RUNTIME_KEY,
    live_plan_mismatch_candidate_plan_id,
    live_plan_mismatch_candidate_step,
    live_runtime_stage_id,
    select_plan_runtime_for_scope,
    stamp_produced_workspace_record,
)
from .. import coach_support
from ..runtime import TrainerRuntime
from ..training_card_identity import (
    prepare_training_file_evaluation,
    training_card_is_live_for_verify,
)
from .core_shared import record_goal_evaluation

if TYPE_CHECKING:
    from .core import CoreRouteDeps


def register_core_evaluation_routes(
    router: APIRouter,
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
) -> None:
    """Register task, evaluation, learning-signal, feedback, and plan-candidate routes."""

    @router.post("/task/next", response_model=TaskSpec)
    def task_next(request: TaskNextRequest) -> TaskSpec:
        workspace_id = core.domain.current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        live_plan = core.domain.require_live_formal_plan_for_explicit_task_next(workspace_id)
        plan_id = str(getattr(live_plan, "id", "") or getattr(live_plan, "plan_id", "") or "").strip()
        profile = runtime.repository.get_profile(workspace_id)
        resolved_response_language = core.domain.effective_response_language(
            workspace_id,
            request.response_language,
        )
        task = coach_support.review_aware_next_task(
            core.coach_support_deps,
            workspace_id=workspace_id,
            profile=profile,
            focus_area=request.focus_area,
            response_language=resolved_response_language,
        )
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        task = core.domain.clean_active_thread_task(
            task,
            resolved_response_language,
            runtime.memory_service.snapshot(workspace_id).active_thread,
            plan=state.snapshot.plan or live_plan,
            snapshot=state.snapshot,
        )
        meta = dict(task.metadata or {})
        meta["plan_id"] = plan_id
        task = task.model_copy(update={"metadata": meta})
        task = stamp_produced_workspace_record(task, workspace_id)
        state.snapshot.current_task = task
        if state.snapshot.plan is None:
            state.snapshot.plan = stamp_produced_workspace_record(live_plan, workspace_id)
        runtime.memory_service.persist_turn_context_pressure(workspace_id, current_task=task)
        runtime.save_session_state(state.session_id)
        return task

    @router.post("/task/specify", response_model=TaskSpec)
    def task_specify(request: TaskSpecifyRequest) -> TaskSpec:
        workspace_id = core.domain.current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        live_plan = core.domain.require_live_formal_plan_for_explicit_task_next(
            workspace_id,
            route="/task/specify",
        )
        plan_id = str(getattr(live_plan, "id", "") or getattr(live_plan, "plan_id", "") or "").strip()
        task = stamp_produced_workspace_record(
            runtime.spec_service.specify(request),
            workspace_id,
        )
        meta = dict(task.metadata or {})
        meta["plan_id"] = plan_id
        task = task.model_copy(update={"metadata": meta})
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        state.snapshot.current_task = task
        if state.snapshot.plan is None:
            state.snapshot.plan = stamp_produced_workspace_record(live_plan, workspace_id)
        runtime.memory_service.persist_turn_context_pressure(workspace_id, current_task=task)
        runtime.save_session_state(state.session_id)
        return task

    @router.post("/evaluate/current-file")
    def evaluate_current_file(request: EvaluateCurrentFileRequest):
        workspace_id = core.domain.current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        request = prepare_training_file_evaluation(runtime, workspace_id, request)
        training_verification_live = True
        if str(request.evaluation_source or "").strip().lower() == "training":
            training_verification_live = training_card_is_live_for_verify(
                runtime,
                workspace_id,
                str(request.training_card_id or ""),
            )
        leftover = core.domain.leftover_plan_state_fields(workspace_id)
        leftover_runtime = leftover.get("leftover_runtime")
        training_project_root: str | None = None
        if str(request.evaluation_source or "").strip().lower() == "training":
            workspace_payload = runtime.memory_service.snapshot(workspace_id).workspace
            training_project_root = (
                str(
                    workspace_payload.get("canonical_project_path")
                    or workspace_payload.get("project_path")
                    or ""
                ).strip()
                or None
            )
        report = stamp_produced_workspace_record(
            runtime.evaluator_service.evaluate_current_file(
                request,
                state.snapshot.current_task,
                leftover_plan=leftover.get("leftover_plan"),
                leftover_runtime=leftover_runtime if isinstance(leftover_runtime, dict) else {},
                leftover_task_title=str(leftover.get("leftover_task_title") or ""),
                response_language=core.domain.workspace_response_language(workspace_id),
                project_root=training_project_root,
            ),
            workspace_id,
        )
        state.snapshot.evaluation = report
        if not training_verification_live:
            state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
            runtime.save_session_state(state.session_id)
            return report
        core.domain.persist_evaluation_learning_loop(
            workspace_id=workspace_id,
            state=state,
            report=report,
            action_type="evaluate_current_file",
            fallback_focus_area=Path(str(request.file_path or "")).stem.strip() or "current-file",
        )
        core.domain.advance_plan_after_evaluation(
            workspace_id=workspace_id,
            state=state,
            report=report,
        )
        core.domain.record_training_practice_evaluation(
            workspace_id=workspace_id,
            state=state,
            request=request,
            report=report,
            evidence_source="ide_current_file",
        )
        record_goal_evaluation(runtime, workspace_id, request, report)
        state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        runtime.save_session_state(state.session_id)
        return report

    @router.post("/evaluate/snippet")
    def evaluate_snippet(request: EvaluateSnippetRequest):
        workspace_id = core.domain.current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        if str(request.evaluation_source or "").strip().lower() == "training":
            core.domain.require_live_selected_card_for_status(
                workspace_id,
                str(request.training_card_id or ""),
            )
            report = stamp_produced_workspace_record(
                core.domain.training_practice_blocked_report(
                    request,
                    response_language=core.domain.workspace_response_language(workspace_id),
                ),
                workspace_id,
            )
            state.snapshot.evaluation = report
            core.domain.persist_evaluation_learning_loop(
                workspace_id=workspace_id,
                state=state,
                report=report,
                action_type="evaluate_snippet",
                fallback_focus_area="snippet",
            )
            core.domain.advance_plan_after_evaluation(
                workspace_id=workspace_id,
                state=state,
                report=report,
            )
            core.domain.record_training_practice_evaluation(
                workspace_id=workspace_id,
                state=state,
                request=request,
                report=report,
                evidence_source="snippet_or_selection",
            )
            record_goal_evaluation(runtime, workspace_id, request, report)
            state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
            runtime.save_session_state(state.session_id)
            return report
        leftover = core.domain.leftover_plan_state_fields(workspace_id)
        leftover_runtime = leftover.get("leftover_runtime")
        report = stamp_produced_workspace_record(
            runtime.evaluator_service.evaluate_snippet(
                request,
                state.snapshot.current_task,
                leftover_plan=leftover.get("leftover_plan"),
                leftover_runtime=leftover_runtime if isinstance(leftover_runtime, dict) else {},
                leftover_task_title=str(leftover.get("leftover_task_title") or ""),
                response_language=core.domain.workspace_response_language(workspace_id),
            ),
            workspace_id,
        )
        state.snapshot.evaluation = report
        core.domain.persist_evaluation_learning_loop(
            workspace_id=workspace_id,
            state=state,
            report=report,
            action_type="evaluate_snippet",
            fallback_focus_area="snippet",
        )
        core.domain.advance_plan_after_evaluation(
            workspace_id=workspace_id,
            state=state,
            report=report,
        )
        record_goal_evaluation(runtime, workspace_id, request, report)
        state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        runtime.save_session_state(state.session_id)
        return report

    @router.post("/learning/signal", response_model=WorkbenchSnapshot)
    def record_learning_signal(request: LearningSignalRequest) -> WorkbenchSnapshot:
        workspace_id = core.domain.current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        concepts = [item.strip() for item in request.concepts if item and item.strip()]
        if not concepts and state.snapshot.current_task is not None:
            concepts = core.domain.task_training_concepts(
                state.snapshot.current_task,
                snapshot=state.snapshot,
                plan=state.snapshot.plan,
            )
        focus_area = (
            (request.focus_area or "").strip()
            or core.domain.live_current_task_focus(state.snapshot)
            or "learning-signal"
        )
        adaptation_outcome = runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=concepts,
            outcome=request.outcome,
            summary=request.summary,
            checks=request.checks,
            missing_requirements=request.missing_requirements,
            action_type=request.action_type,
            repetition_count=None,
            focus_area=focus_area,
            scenario=request.scenario,
            verified_result=None,
            blocked_reason=request.blocked_reason,
            abandoned_reason=request.abandoned_reason,
            selected_teaching_asset_ids=request.selected_teaching_asset_ids
            or [item.id for item in state.snapshot.selected_teaching_assets if getattr(item, "id", "")],
            teaching_strategy_context=core.domain.teaching_strategy_context_from_snapshot(state.snapshot),
            verified_by_evaluator=False,
        )
        server_repetition_count = int(getattr(adaptation_outcome, "repetition_count", 1) or 1)
        adaptation_snapshot = runtime.memory_service.snapshot(state.workspace_id)
        adaptation_profile = adaptation_snapshot.coaching_adaptation
        adaptation_workspace = (
            adaptation_snapshot.workspace if isinstance(adaptation_snapshot.workspace, dict) else {}
        )
        recovered_runtime = select_plan_runtime_for_scope(
            adaptation_workspace.get(PLAN_RUNTIME_KEY) or adaptation_workspace.get("latestPlanRuntime"),
            workspace_id,
        )
        updated_plan = None
        signal_base_plan = state.snapshot.plan or runtime.repository.get_latest_plan(workspace_id)
        signal_base_revision = (
            core.domain.head_plan_revision(workspace_id, signal_base_plan.id)
            if signal_base_plan is not None
            else 0
        )
        if request.outcome not in {"code_landed", "tests_passed"}:
            updated_plan = runtime.planner_service.advance_plan_from_learning_signal(
                signal_base_plan,
                state.snapshot.current_task,
                outcome=request.outcome,
                summary=request.summary,
                verified_result=None,
                blocked_reason=request.blocked_reason,
                abandoned_reason=request.abandoned_reason,
                repetition_count=server_repetition_count,
                focus_area=focus_area,
                next_step_bias=adaptation_profile.next_step_bias if adaptation_profile else None,
                runtime=recovered_runtime,
                existing=recovered_runtime,
            )
        if updated_plan is not None:
            state.snapshot.plan = updated_plan
            core.domain.save_plan_or_conflict(
                workspace_id,
                updated_plan,
                expected_revision=signal_base_revision,
            )
            core.domain.persist_plan_to_sandbox(workspace_id, updated_plan, reason="learning-signal")
        state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        runtime.save_session_state(state.session_id)
        return state.snapshot

    @router.post("/memory/feedback", response_model=WorkbenchSnapshot)
    def record_user_feedback(request: UserFeedbackRequest) -> WorkbenchSnapshot:
        workspace_id = core.domain.current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        focus_area = (request.focus_area or "").strip() or "general"
        runtime.memory_service.record_user_feedback(
            workspace_id=workspace_id,
            kind=request.kind,
            message=request.message,
            focus_area=focus_area,
            scenario=request.scenario or "coach",
            training_card_id=request.training_card_id or "",
            plan_id=request.plan_id or "",
        )
        state.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
        plan = runtime.repository.get_latest_plan(workspace_id)
        state.snapshot.memory.plan_change_candidates = runtime.repository.list_plan_change_candidates(
            workspace_id
        )
        if request.kind == "plan_mismatch" and plan is not None:
            _, mismatch_runtime = core.domain.leftover_runtime_for_workspace(workspace_id)
            mismatch_step = live_plan_mismatch_candidate_step(
                plan=plan,
                runtime=mismatch_runtime,
                existing=mismatch_runtime,
                current_step=plan.current_step,
            )
            candidate = PlanChangeCandidate(
                id=f"plan-change:{uuid4().hex}",
                workspace_id=workspace_id,
                plan_id=live_plan_mismatch_candidate_plan_id(
                    plan=plan,
                    runtime=mismatch_runtime,
                    existing=mismatch_runtime,
                    request_plan_id=request.plan_id or "",
                    current_step=plan.current_step,
                ),
                feedback_id=f"feedback:{uuid4().hex}",
                reason=request.message,
                diff={
                    "current_step": mismatch_step,
                    "suggested_action": "Re-scope or reorder the current plan after explicit review.",
                },
                impact={
                    "stage_id": live_runtime_stage_id(
                        plan=plan,
                        runtime=mismatch_runtime,
                        existing=mismatch_runtime,
                        current_step=mismatch_step,
                    ),
                    "verification": plan.verify_method,
                    "formal_plan_changed": False,
                },
            )
            runtime.repository.save_plan_change_candidate(candidate)
            state.snapshot.memory.plan_change_candidates = (
                runtime.repository.list_plan_change_candidates(workspace_id)
            )
        runtime.save_session_state(state.session_id)
        return state.snapshot

    @router.get("/plan/change-candidates", response_model=list[PlanChangeCandidate])
    def list_plan_change_candidates(
        workspace_id: str,
        plan_id: str | None = None,
    ) -> list[PlanChangeCandidate]:
        return runtime.repository.list_plan_change_candidates(workspace_id, plan_id)

    @router.post("/plan/change-candidates/{candidate_id}/ack", response_model=PlanChangeCandidate)
    def acknowledge_plan_change_candidate(
        candidate_id: str,
        payload: dict[str, str] | None = None,
    ) -> PlanChangeCandidate:
        candidate = runtime.repository.get_plan_change_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Plan change candidate not found.")
        workspace_id = str((payload or {}).get("workspace_id") or "").strip()
        if workspace_id and workspace_id != candidate.workspace_id:
            raise HTTPException(status_code=409, detail="Candidate belongs to another workspace.")
        if candidate.status != "pending":
            return candidate
        acknowledged = candidate.model_copy(
            update={
                "status": "acknowledged",
                "acknowledged_at": datetime.now(UTC).isoformat(),
                "acknowledgement_note": str((payload or {}).get("note") or "").strip(),
            }
        )
        runtime.repository.save_plan_change_candidate(acknowledged)
        return acknowledged

    @router.post("/plan/change-candidates/{candidate_id}/reject", response_model=PlanChangeCandidate)
    def reject_plan_change_candidate(
        candidate_id: str,
        payload: dict[str, str] | None = None,
    ) -> PlanChangeCandidate:
        candidate = runtime.repository.get_plan_change_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Plan change candidate not found.")
        workspace_id = str((payload or {}).get("workspace_id") or "").strip()
        if workspace_id and workspace_id != candidate.workspace_id:
            raise HTTPException(status_code=409, detail="Candidate belongs to another workspace.")
        if candidate.status != "pending":
            return candidate
        rejected = candidate.model_copy(
            update={
                "status": "rejected",
                "acknowledged_at": datetime.now(UTC).isoformat(),
                "acknowledgement_note": str((payload or {}).get("note") or "").strip(),
            }
        )
        runtime.repository.save_plan_change_candidate(rejected)
        return rejected
