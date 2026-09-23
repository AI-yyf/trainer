from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ...core.models import (
    CoachTurnSummary,
    GlobalPlan,
    GlobalPlanProjectLink,
    GlobalPlanProjectLinkRequest,
    GlobalPlanUpdateRequest,
    LearningPlan,
    PlanGenerateRequest,
    PlanUpdateRequest,
    SubPlan,
    UserProfile,
    WorkbenchSnapshot,
)
from ...memory.models import utc_now
from ...memory.workspace_recovery import (
    coach_focus_runtime_from_snapshot,
    leftover_formal_plan_is_live_for_fill,
    leftover_frozen_plan_blocks_generation,
    live_plan_update_persist_chrome,
    stamp_produced_workspace_record,
)
from .._helpers import localized_text
from ..runtime import TrainerRuntime
from ._deps import RouterDeps


def build_plan_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter(tags=["plan"])

    current_workspace_id = deps.current_workspace_id
    current_snapshot = deps.current_snapshot
    hydrate_snapshot = deps.hydrate_snapshot
    operation_reliability_record = deps.operation_reliability_record
    provider_config_from_payload = deps.provider_config_from_payload
    provider_api_key_from_payload = deps.provider_api_key_from_payload
    active_plan_stage = deps.active_plan_stage
    attach_plan_runtime_status = deps.attach_plan_runtime_status
    coach_suggested_actions = deps.coach_suggested_actions
    ensure_coach_provider_ready = deps.ensure_coach_provider_ready
    frozen_plan_mutation_notice = deps.frozen_plan_mutation_notice
    leftover_runtime_for_workspace = deps.leftover_runtime_for_workspace
    persist_plan_to_sandbox = deps.persist_plan_to_sandbox
    provider_is_live_usable = deps.provider_is_live_usable
    stateful_focus_area = deps.stateful_focus_area
    structured_suggested_actions = deps.structured_suggested_actions
    workspace_first_look_summary = deps.workspace_first_look_summary

    def explicit_legacy_plan_save(payload: dict) -> bool:
        """Allow compatibility saves only when the caller labels the mode."""
        return any(
            payload.get(key) is True
            for key in (
                "legacy",
                "legacy_save",
                "legacySave",
                "migration",
                "migration_mode",
                "migrationMode",
            )
        )

    def save_plan_or_conflict(
        workspace_id: str,
        plan: LearningPlan,
        *,
        expected_revision: int,
        allow_legacy: bool = False,
    ) -> int:
        """Persist under optimistic locking; 409 with the current revision on
        conflict so the losing window can re-read and re-apply its change."""
        from ...training.plan_revision import (
            PlanRevisionConflict,
            PlanRevisionPreconditionRequired,
            save_plan_checked,
        )

        try:
            saved = save_plan_checked(
                runtime.repository,
                workspace_id,
                plan,
                expected_revision=expected_revision,
                allow_legacy=allow_legacy,
            )
        except PlanRevisionPreconditionRequired as precondition:
            raise HTTPException(
                status_code=428,
                detail={
                    "code": "plan_revision_required",
                    "message": "expected_revision is required for a formal plan save.",
                    "plan_id": plan.id,
                    "current_revision": precondition.actual_revision,
                },
            ) from precondition
        except PlanRevisionConflict as conflict:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "plan_revision_conflict",
                    "message": localized_text(
                        "This plan changed in another window. Re-read the plan and re-apply your change; nothing was overwritten.",
                        "计划已在另一个窗口被修改。请重新读取计划后再次应用你的修改；本次没有覆盖任何内容。",
                        None,
                    ),
                    "plan_id": plan.id,
                    "expected_revision": conflict.expected_revision,
                    "current_revision": conflict.actual_revision,
                },
            ) from conflict
        return saved["revision"]

    def head_plan_revision(workspace_id: str, plan_id: str) -> int:
        return runtime.repository.get_plan_revision(workspace_id, plan_id)


    def first_look_goal_hint(workspace_id: str) -> str | None:
        summary = workspace_first_look_summary(workspace_id)
        if summary is None:
            return None
        candidates = [
            summary.recommended_next_step,
            summary.training_opportunities[0] if summary.training_opportunities else "",
            summary.why_this_guess,
            summary.project_type_guess.replace("_", " ") if summary.project_type_guess else "",
            summary.folder_role.replace("_", " ") if summary.folder_role else "",
        ]
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text:
                return text
        return None


    def seed_plan_from_coach_outputs(
        plan: LearningPlan,
        snapshot: WorkbenchSnapshot,
    ) -> LearningPlan:
        current_step = ""
        why_now = ""
        verify_method: list[str] = []

        adaptation_guide = snapshot.project_adaptation_guide
        if adaptation_guide and adaptation_guide.first_migration_step:
            current_step = adaptation_guide.first_migration_step
            why_now = adaptation_guide.target_outcome or (
                snapshot.coaching_state.summary if snapshot.coaching_state else ""
            )
            verify_method = [item for item in adaptation_guide.validation_checkpoints[:3] if item]
        elif snapshot.project_ideas:
            top_idea = snapshot.project_ideas[0]
            current_step = top_idea.first_step or ""
            why_now = top_idea.why_now or top_idea.summary
            verify_method = [item for item in top_idea.acceptance_signals[:3] if item]
        elif snapshot.implementation_guide:
            guide = snapshot.implementation_guide
            current_step = guide.current_step or ""
            why_now = guide.mvp_definition or guide.idea_summary
            verify_method = [item for item in guide.validation_strategy[:3] if item]

        if not current_step and not why_now and not verify_method:
            return plan
        return runtime.planner_service.refresh_plan_lifecycle(
            plan,
            current_step=current_step or None,
            why_now=why_now or None,
            verify_method=verify_method or None,
        )

    def subplan_payload(subplan: SubPlan) -> dict[str, object]:
        return subplan.model_dump(mode="json", by_alias=False)

    def require_plan(plan_id: str) -> LearningPlan:
        plan_record = runtime.repository.get_plan_by_id(plan_id)
        if plan_record is None:
            raise HTTPException(status_code=404, detail=f"Learning plan '{plan_id}' was not found.")
        _, plan = plan_record
        return plan

    def plan_context_snapshot(
        *,
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> WorkbenchSnapshot:
        resolved_workspace_id = current_workspace_id(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        snapshot = current_snapshot(session_id=session_id, workspace_id=resolved_workspace_id)
        runtime.hydrate_plan_context(snapshot, resolved_workspace_id)
        return snapshot

    def global_plan_context_payload(snapshot: WorkbenchSnapshot) -> dict[str, object]:
        return {
            "global_plan": (
                snapshot.global_plan.model_dump(mode="json", by_alias=False)
                if snapshot.global_plan is not None
                else None
            ),
            "project_plan_link": (
                snapshot.project_plan_link.model_dump(mode="json", by_alias=False)
                if snapshot.project_plan_link is not None
                else None
            ),
            "snapshot": snapshot.model_dump(mode="json", by_alias=False),
        }

    def global_plan_seed(profile: UserProfile, request: GlobalPlanUpdateRequest) -> GlobalPlan:
        goals = [item.strip() for item in (request.goals or profile.long_term_goals) if item.strip()]
        if not goals and profile.long_term_goal.strip():
            goals = [profile.long_term_goal.strip()]
        generated = runtime.planner_service.generate_plan(
            PlanGenerateRequest(profile=profile, goals=goals)
        )
        owner = runtime.repository.ensure_default_local_owner()
        title = (request.title or generated.title or "Master plan").strip()
        if not title:
            raise HTTPException(status_code=422, detail="A master plan title is required.")
        return GlobalPlan(
            id=f"global-{uuid4().hex}",
            ownerId=owner.id,
            title=title,
            summary=(request.summary if request.summary is not None else generated.summary).strip(),
            goals=goals,
            stages=request.stages if request.stages is not None else generated.stages,
            frozen=bool(request.frozen),
            currentProjectPlanId=request.current_project_plan_id,
            currentStageId=request.current_stage_id or generated.current_stage_id,
            currentStep=request.current_step if request.current_step is not None else generated.current_step,
            whyNow=request.why_now if request.why_now is not None else generated.why_now,
            verifyMethod=(
                request.verify_method if request.verify_method is not None else generated.verify_method
            ),
        )

    def auto_link_project_plan_to_global_plan(
        *,
        workspace_id: str,
        project_plan: LearningPlan,
    ) -> GlobalPlanProjectLink | None:
        """Keep the active project plan attached to the editable global plan."""
        global_plan = runtime.repository.get_default_global_plan()
        if global_plan is None or global_plan.frozen:
            return None
        link = GlobalPlanProjectLink(
            globalPlanId=global_plan.id,
            workspaceId=workspace_id,
            projectPlanId=project_plan.id,
        )
        runtime.repository.save_global_plan_project_link(link)
        return link

    def validate_global_plan_project_reference(
        *,
        workspace_id: str,
        project_plan_id: str | None,
    ) -> None:
        """Reject global-plan pointers that cross the active project boundary."""
        normalized_id = str(project_plan_id or "").strip()
        if not normalized_id:
            return
        project_plan = runtime.repository.get_plan_by_id(normalized_id)
        if project_plan is None:
            raise HTTPException(status_code=409, detail="The referenced project plan does not exist.")
        project_workspace_id, _ = project_plan
        if project_workspace_id != workspace_id:
            raise HTTPException(
                status_code=409,
                detail="The referenced project plan belongs to another workspace.",
            )


    @router.get("/plan/context", response_model=None)
    def get_plan_context(
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, object]:
        snapshot = plan_context_snapshot(session_id=session_id, workspace_id=workspace_id)
        return global_plan_context_payload(snapshot)

    @router.post("/plan/global", response_model=None)
    def create_global_plan(request: GlobalPlanUpdateRequest) -> dict[str, object]:
        existing = runtime.repository.get_default_global_plan()
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="A global plan already exists. Use PATCH /plan/global for an explicit update.",
            )
        workspace_id = current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        validate_global_plan_project_reference(
            workspace_id=workspace_id,
            project_plan_id=request.current_project_plan_id,
        )
        profile = runtime.repository.get_profile(workspace_id) or UserProfile(long_term_goal="Trainer")
        global_plan = global_plan_seed(profile, request)
        runtime.repository.save_global_plan(global_plan)
        existing_project_plan = runtime.repository.get_latest_plan(workspace_id)
        if existing_project_plan is not None:
            auto_link_project_plan_to_global_plan(
                workspace_id=workspace_id,
                project_plan=existing_project_plan,
            )
        snapshot = plan_context_snapshot(
            session_id=request.session_id,
            workspace_id=workspace_id,
        )
        return global_plan_context_payload(snapshot)

    @router.patch("/plan/global", response_model=None)
    def update_global_plan(request: GlobalPlanUpdateRequest) -> dict[str, object]:
        existing = runtime.repository.get_default_global_plan()
        if existing is None:
            raise HTTPException(status_code=404, detail="No global plan is available yet.")
        if request.title is not None and not request.title.strip():
            raise HTTPException(status_code=422, detail="A master plan title is required.")
        workspace_id = current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        validate_global_plan_project_reference(
            workspace_id=workspace_id,
            project_plan_id=request.current_project_plan_id,
        )
        updates: dict[str, object] = {"updated_at": utc_now().isoformat()}
        for field_name in (
            "title",
            "summary",
            "goals",
            "stages",
            "frozen",
            "current_project_plan_id",
            "current_stage_id",
            "current_step",
            "why_now",
            "verify_method",
        ):
            value = getattr(request, field_name)
            if value is not None:
                updates[field_name] = value.strip() if isinstance(value, str) else value
        updated = existing.model_copy(update=updates)
        runtime.repository.save_global_plan(updated)
        snapshot = plan_context_snapshot(
            session_id=request.session_id,
            workspace_id=workspace_id,
        )
        return global_plan_context_payload(snapshot)

    @router.put("/plan/global/projects", response_model=None)
    def link_current_project_plan(request: GlobalPlanProjectLinkRequest) -> dict[str, object]:
        global_plan = runtime.repository.get_default_global_plan()
        if global_plan is None:
            raise HTTPException(status_code=404, detail="Create a global plan before linking a project plan.")
        if global_plan.frozen:
            raise HTTPException(status_code=409, detail="The global plan is frozen.")
        workspace_id = current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        project_plan = (
            runtime.repository.get_plan_by_id(request.project_plan_id)
            if request.project_plan_id
            else None
        )
        if project_plan is None:
            current_plan = runtime.repository.get_latest_plan(workspace_id)
            if current_plan is None:
                raise HTTPException(status_code=404, detail="No project plan is available to link.")
            project_plan = (workspace_id, current_plan)
        project_workspace_id, project_plan_value = project_plan
        if project_workspace_id != workspace_id:
            raise HTTPException(status_code=409, detail="The project plan belongs to another workspace.")
        link = GlobalPlanProjectLink(
            globalPlanId=global_plan.id,
            workspaceId=workspace_id,
            projectPlanId=project_plan_value.id,
        )
        runtime.repository.save_global_plan_project_link(link)
        snapshot = plan_context_snapshot(
            session_id=request.session_id,
            workspace_id=workspace_id,
        )
        return global_plan_context_payload(snapshot)

    @router.delete("/plan/global/projects/{workspace_id}", response_model=None)
    def unlink_project_plan(workspace_id: str) -> dict[str, object]:
        global_plan = runtime.repository.get_default_global_plan()
        if global_plan is None:
            raise HTTPException(status_code=404, detail="No global plan is available yet.")
        if global_plan.frozen:
            raise HTTPException(status_code=409, detail="The global plan is frozen.")
        runtime.repository.delete_global_plan_project_link(global_plan.id, workspace_id)
        snapshot = plan_context_snapshot(workspace_id=workspace_id)
        return global_plan_context_payload(snapshot)

    def frozen_plan_generation_detail(payload: dict) -> str:
        response_language = str(
            payload.get("response_language") or payload.get("responseLanguage") or ""
        ).strip()
        messages = {
            "zh-CN": "这条计划已冻结。先恢复为可编辑状态，再生成新的版本。",
            "en-US": "This plan is frozen. Resume it before creating a new version.",
            "es-ES": "Este plan esta congelado. Reanudalo antes de crear una nueva version.",
            "fr-FR": "Ce plan est gele. Reprenez-le avant de creer une nouvelle version.",
            "de-DE": "Dieser Plan ist eingefroren. Setzen Sie ihn fort, bevor Sie eine neue Version erstellen.",
            "ja-JP": "この計画は固定されています。新しい版を作る前に、再開してください。",
            "ko-KR": "이 계획은 고정되어 있습니다. 새 버전을 만들기 전에 다시 시작하세요.",
            "pt-BR": "Este plano esta congelado. Retome-o antes de criar uma nova versao.",
        }
        return messages.get(response_language, messages["en-US"])

    def reject_frozen_plan_generation(workspace_id: str, payload: dict) -> None:
        current_plan = runtime.repository.get_latest_plan(workspace_id)
        if current_plan is None or not current_plan.frozen:
            return
        leftover_plan, leftover_runtime, _leftover_task = runtime.memory_service._leftover_persist_context(
            workspace_id
        )
        if leftover_frozen_plan_blocks_generation(
            plan=leftover_plan or current_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            raise HTTPException(status_code=409, detail=frozen_plan_generation_detail(payload))

    def seed_generated_plan_if_leftover_live(
        plan: LearningPlan,
        snapshot: WorkbenchSnapshot,
        workspace_id: str,
    ) -> LearningPlan:
        # Explicit /plan/generate only. Coaching turns must never seed formal plan
        # identity from coach chrome (including under high urgency).
        leftover_plan, leftover_runtime, _leftover_task = runtime.memory_service._leftover_persist_context(
            workspace_id
        )
        if leftover_formal_plan_is_live_for_fill(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            return seed_plan_from_coach_outputs(plan, snapshot)
        return plan

    def generated_plan_five_view_payload(
        *,
        plan_payload: dict[str, object],
        runtime_status: dict[str, object],
        snapshot: WorkbenchSnapshot,
        diagnostics: list[str],
        workspace_id: str,
    ) -> dict[str, object]:
        return {
            **plan_payload,
            "plan": plan_payload,
            "plan_runtime_status": runtime_status,
            "context_id": workspace_id,
            "workspace_id": workspace_id,
            "coach_orientation": snapshot.coach_orientation,
            "suggested_actions": [
                item.model_dump() if hasattr(item, "model_dump") else item
                for item in (snapshot.suggested_actions or [])
            ],
            "current_task": snapshot.current_task.model_dump() if snapshot.current_task else None,
            "memory": snapshot.memory.model_dump() if snapshot.memory is not None else {},
            "diagnostics": diagnostics,
            "reliability": operation_reliability_record(phase="acked", outcome="success"),
        }

    @router.post("/plan/generate", response_model=None)
    def generate_plan(payload: dict) -> object:
        requested_response_language = str(
            payload.get("response_language") or payload.get("responseLanguage") or ""
        ).strip() or None
        coaching_service = runtime.provider_service
        override_config = provider_config_from_payload(payload)
        api_key_override = provider_api_key_from_payload(payload)
        if override_config is not None or api_key_override is not None:
            coaching_service = runtime.provider_service_for(override_config, api_key_override)
        ensure_coach_provider_ready(
            coaching_service,
            response_language=requested_response_language,
        )
        if not provider_is_live_usable(coaching_service, payload):
            raise HTTPException(
                status_code=400,
                detail=localized_text(
                    "This connection is not ready. Test it in Settings, then resend this turn. Trainer did not invent a plan.",
                    "当前连接还不能用。请先在设置里测试，再重发这一轮。Trainer 没有生成新计划。",
                    requested_response_language,
                ),
            )
        if "session_id" in payload:
            session_id = payload["session_id"]
            state = runtime.ensure_session(session_id)
            reject_frozen_plan_generation(state.workspace_id, payload)
            profile = runtime.repository.get_profile(state.workspace_id) or UserProfile(long_term_goal="Trainer")
            workspace_memory = (
                state.snapshot.memory.workspace if isinstance(state.snapshot.memory.workspace, dict) else {}
            )
            workspace_response_language = (
                str(workspace_memory.get("response_language")).strip()
                if workspace_memory.get("response_language")
                else requested_response_language
            )
            objectives = [
                str(item).strip()
                for item in payload.get("objectives", [])
                if str(item).strip()
            ]
            if not objectives:
                first_look_goal = first_look_goal_hint(state.workspace_id)
                if first_look_goal:
                    objectives = [first_look_goal]
                elif profile.long_term_goal.strip():
                    objectives = [profile.long_term_goal.strip()]
            request = PlanGenerateRequest(
                profile=profile,
                goals=objectives,
                constraints=[
                    str(item).strip()
                    for item in payload.get("constraints", [])
                    if str(item).strip()
                ],
            )
            try:
                plan = runtime.planner_service.generate_plan(request)
                plan = seed_generated_plan_if_leftover_live(plan, state.snapshot, state.workspace_id)
                plan = runtime.planner_service.localize_plan(plan, workspace_response_language)
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(
                    status_code=500,
                    detail="Plan generation failed. The stored plan and recovered runtime were left unchanged.",
                ) from None
            plan.session_id = session_id
            runtime.memory_service.record_profile(state.workspace_id, profile)
            # Generation is authoritative replacement of a fresh plan id, so
            # the save is guarded but expected from the current head (0 for a
            # genuinely new plan).
            save_plan_or_conflict(
                state.workspace_id,
                plan,
                expected_revision=head_plan_revision(state.workspace_id, plan.id),
            )
            runtime.memory_service.bind_explicit_generated_plan(state.workspace_id, plan)
            auto_link_project_plan_to_global_plan(
                workspace_id=state.workspace_id,
                project_plan=plan,
            )
            state.snapshot.profile = profile
            state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
            runtime.hydrate_plan_context(state.snapshot, state.workspace_id)
            workspace_memory = (
                state.snapshot.memory.workspace if isinstance(state.snapshot.memory.workspace, dict) else {}
            )
            workspace_response_language = (
                str(workspace_memory.get("response_language")).strip()
                if workspace_memory.get("response_language")
                else None
            )
            workspace_answer_mode = (
                str(workspace_memory.get("answer_mode")).strip()
                if workspace_memory.get("answer_mode")
                else profile.answer_policy
            )
            hydrate_snapshot(
                state.snapshot,
                response_language=workspace_response_language,
                answer_mode=workspace_answer_mode,
            )
            runtime_status = attach_plan_runtime_status(
                workspace_id=state.workspace_id,
                snapshot=state.snapshot,
                response_language=workspace_response_language,
                profile=profile,
            )
            runtime.save_session_state(state.session_id)
            resolved_plan = stamp_produced_workspace_record(
                state.snapshot.plan or plan,
                state.workspace_id,
            )
            persist_plan_to_sandbox(state.workspace_id, resolved_plan, reason="generated")
            plan_payload = resolved_plan.model_dump()
            return generated_plan_five_view_payload(
                plan_payload=plan_payload,
                runtime_status=runtime_status,
                snapshot=state.snapshot,
                diagnostics=[
                    localized_text(
                        f"Constraints captured: {', '.join(payload.get('constraints', []))}",
                        f"已记录约束：{', '.join(payload.get('constraints', []))}",
                        workspace_response_language,
                    )
                ]
                if payload.get("constraints")
                else [],
                workspace_id=state.workspace_id,
            )

        request = PlanGenerateRequest.model_validate(payload)
        workspace_id = current_workspace_id(workspace_id=request.workspace_id)
        reject_frozen_plan_generation(workspace_id, payload)
        goals = [str(item).strip() for item in request.goals if str(item).strip()]
        if not goals:
            first_look_goal = first_look_goal_hint(workspace_id)
            if first_look_goal:
                goals = [first_look_goal]
            elif request.profile.long_term_goal.strip():
                goals = [request.profile.long_term_goal.strip()]
        request = request.model_copy(update={"goals": goals})
        try:
            plan = runtime.planner_service.generate_plan(request)
            plan = runtime.planner_service.localize_plan(plan, requested_response_language)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Plan generation failed. The stored plan and recovered runtime were left unchanged.",
            ) from None
        runtime.memory_service.record_profile(workspace_id, request.profile)
        save_plan_or_conflict(
            workspace_id,
            plan,
            expected_revision=head_plan_revision(workspace_id, plan.id),
        )
        runtime.memory_service.bind_explicit_generated_plan(workspace_id, plan)
        auto_link_project_plan_to_global_plan(
            workspace_id=workspace_id,
            project_plan=plan,
        )
        snapshot = WorkbenchSnapshot(
            profile=request.profile,
            memory=runtime.memory_service.snapshot(workspace_id),
            plan=plan,
        )
        runtime.hydrate_plan_context(snapshot, workspace_id)
        workspace_memory = snapshot.memory.workspace if isinstance(snapshot.memory.workspace, dict) else {}
        workspace_response_language = (
            str(workspace_memory.get("response_language")).strip()
            if workspace_memory.get("response_language")
            else None
        )
        hydrate_snapshot(
            snapshot,
            response_language=workspace_response_language,
            answer_mode=(
                str(workspace_memory.get("answer_mode")).strip()
                if workspace_memory.get("answer_mode")
                else request.profile.answer_policy
            ),
        )
        runtime_status = attach_plan_runtime_status(
            workspace_id=workspace_id,
            snapshot=snapshot,
            response_language=workspace_response_language,
            profile=request.profile,
        )
        resolved_plan = stamp_produced_workspace_record(snapshot.plan or plan, workspace_id)
        persist_plan_to_sandbox(workspace_id, resolved_plan, reason="generated")
        plan_payload = resolved_plan.model_dump()
        return generated_plan_five_view_payload(
            plan_payload=plan_payload,
            runtime_status=runtime_status,
            snapshot=snapshot,
            diagnostics=[],
            workspace_id=workspace_id,
        )

    @router.post("/plan/update", response_model=None)
    def update_plan(payload: dict) -> object:
        request = PlanUpdateRequest.model_validate(payload)
        workspace_id = current_workspace_id(workspace_id=request.workspace_id)
        current: LearningPlan | None = None
        if request.plan_id:
            current_record = runtime.repository.get_plan_by_id(request.plan_id)
            if current_record:
                workspace_id, current = current_record
        if current is None:
            current = runtime.repository.get_latest_plan(workspace_id)
        if not current:
            raise HTTPException(status_code=404, detail="No learning plan is available yet.")
        # Formal UI/API saves must carry the revision observed by the caller.
        # A zero-head compatibility seed is still accepted for internal
        # initialization; once a revision exists, omission is rejected unless
        # the caller explicitly labels legacy/migration mode.
        current_head_revision = head_plan_revision(workspace_id, current.id)
        if (
            request.formal_plan_mutation
            and request.expected_revision is None
            and not explicit_legacy_plan_save(payload)
        ):
            raise HTTPException(
                status_code=428,
                detail={
                    "code": "plan_revision_required",
                    "message": "expected_revision is required for a formal plan save.",
                    "plan_id": current.id,
                    "current_revision": current_head_revision,
                },
            )
        expected_revision = (
            request.expected_revision
            if request.expected_revision is not None
            else current_head_revision
        )
        # Explicit mutate by plan_id only when recovered runtime still matches that id.
        # Leftover stored plan with empty/mismatched recovered plan_id must not fill snapshot.plan.
        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        if not leftover_formal_plan_is_live_for_fill(
            plan=current,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            if leftover_plan is not None and leftover_runtime:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Recovered plan runtime is leftover-not-live. "
                        "/plan/update will not mutate or resurrect the leftover as live."
                    ),
                )
            raise HTTPException(
                status_code=409,
                detail=(
                    "No live learning plan is bound. Generate a plan first; "
                    "/plan/update does not resurrect leftover as live."
                ),
            )
        if current.frozen:
            has_content_update = bool(
                request.title or request.weekly_cadence or request.instructions.strip()
            )
            if has_content_update or request.frozen is not False:
                response_language = str(
                    payload.get("response_language") or payload.get("responseLanguage") or ""
                ).strip() or None
                raise HTTPException(
                    status_code=409,
                    detail=frozen_plan_mutation_notice(response_language),
                )
        has_content_update = bool(
            request.title or request.weekly_cadence or request.instructions.strip()
        )
        if has_content_update:
            requested_response_language = str(
                payload.get("response_language") or payload.get("responseLanguage") or ""
            ).strip() or None
            coaching_service = runtime.provider_service
            override_config = provider_config_from_payload(payload)
            api_key_override = provider_api_key_from_payload(payload)
            if override_config is not None or api_key_override is not None:
                coaching_service = runtime.provider_service_for(override_config, api_key_override)
            ensure_coach_provider_ready(
                coaching_service,
                response_language=requested_response_language,
            )
            if not provider_is_live_usable(coaching_service, payload):
                raise HTTPException(
                    status_code=400,
                    detail=localized_text(
                        "This connection is not ready. Test it in Settings, then resend this turn. Trainer did not invent a plan.",
                        "当前连接还不能用。请先在设置里测试，再重发这一轮。Trainer 没有生成新计划。",
                        requested_response_language,
                    ),
                )
        if request.title:
            current.title = request.title
        if request.frozen is not None:
            request.freeze = request.frozen
        if request.weekly_cadence:
            current.weekly_cadence = request.weekly_cadence
            current.cadence = request.weekly_cadence
        workspace_snapshot = runtime.memory_service.snapshot(workspace_id)
        workspace_memory = workspace_snapshot.workspace if isinstance(workspace_snapshot.workspace, dict) else {}
        workspace_response_language = (
            str(workspace_memory.get("response_language")).strip()
            if workspace_memory.get("response_language")
            else None
        )
        updated = runtime.planner_service.update_plan(current, request)
        updated = runtime.planner_service.localize_plan(updated, workspace_response_language)
        new_revision = save_plan_or_conflict(
            workspace_id, updated, expected_revision=expected_revision
        )
        # Keep the recovered runtime identity in sync with the mutated plan:
        # update_plan may rewrite current_step/why_now, and a stale runtime record
        # would make /task/next and /task/specify see this live plan as leftover-not-live.
        runtime.memory_service.bind_explicit_generated_plan(workspace_id, updated)
        profile = runtime.repository.get_profile(workspace_id)
        snapshot = current_snapshot(workspace_id=workspace_id)
        snapshot.plan = updated
        workspace_memory = snapshot.memory.workspace if isinstance(snapshot.memory.workspace, dict) else {}
        workspace_response_language = (
            str(workspace_memory.get("response_language")).strip()
            if workspace_memory.get("response_language")
            else None
        )
        workspace_answer_mode = (
            str(workspace_memory.get("answer_mode")).strip()
            if workspace_memory.get("answer_mode")
            else (profile.answer_policy if profile else None)
        )
        hydrate_snapshot(
            snapshot,
            response_language=workspace_response_language,
            answer_mode=workspace_answer_mode,
            scenario="plan",
            learner_signal="steady",
        )
        snapshot.plan = runtime.planner_service.refresh_plan_lifecycle(
            snapshot.plan or updated,
            current_step=(updated.current_step or updated.summary or updated.title),
            why_now=(updated.why_now or updated.summary or updated.title),
            verify_method=list(updated.verify_method),
            blocked_reason=updated.blocked_reason,
            next_after_current=updated.next_after_current,
        )
        runtime_status = attach_plan_runtime_status(
            workspace_id=workspace_id,
            snapshot=snapshot,
            response_language=workspace_response_language,
            profile=profile,
        )
        updated_plan = stamp_produced_workspace_record(snapshot.plan or updated, workspace_id)
        persist_plan_to_sandbox(workspace_id, updated_plan, reason="updated")
        active_stage = active_plan_stage(updated_plan)
        persist_chrome = live_plan_update_persist_chrome(
            plan=updated_plan,
            runtime=coach_focus_runtime_from_snapshot(snapshot)
            or (runtime_status if isinstance(runtime_status, dict) else None),
            existing=runtime_status if isinstance(runtime_status, dict) else None,
            stage_title=active_stage.title if active_stage else "",
            stage_goal=active_stage.goal if active_stage else "",
        )
        diagnostics: list[str] = []
        if request.instructions.strip():
            diagnostics.append(
                localized_text(
                    f"Coach instruction captured: {request.instructions}",
                    f"已记录教练指令：{request.instructions}",
                    workspace_response_language,
                )
            )
        if request.weekly_cadence:
            diagnostics.append(f"Cadence updated to {request.weekly_cadence}.")
        if request.freeze:
            diagnostics.append("Plan is now frozen for execution focus.")
        response_payload = {
            "plan": updated_plan.model_dump(),
            # Surface the post-save revision so editing windows can chain
            # expected_revision on their next update without re-reading.
            "plan_revision": new_revision,
            "plan_runtime_status": runtime_status,
            "coach_turn": CoachTurnSummary(
                scenario="plan",
                learner_signal="steady",
                summary=localized_text(
                    persist_chrome["summary_en"],
                    persist_chrome["summary_zh"],
                    workspace_response_language,
                ),
                next_step=persist_chrome["next_step"]
                or (
                    "Turn the active stage into today's first task."
                    if active_stage is None
                    else ""
                ),
                encouragement=localized_text(
                    "Keep the next move visible and small.",
                    "把下一步保持得清晰而且足够小。",
                    workspace_response_language,
                ),
                active_stage=persist_chrome["stage_focus"] or None,
                due_review_count=0,
                review_queue_summary=localized_text(
                    "Background review stays embedded in future turns.",
                    "背景复习会继续嵌在后续轮次里。",
                    workspace_response_language,
                ),
                artifact_kinds=["plan_update"],
                suggested_action_types=["plan", "next_task"],
            ).model_dump(),
            "suggested_actions": structured_suggested_actions(
                coach_suggested_actions(workspace_response_language, scenario="plan"),
                response_language=workspace_response_language,
                scenario="plan",
                focus_area=stateful_focus_area(
                    None,
                    updated_plan,
                    runtime=runtime_status if isinstance(runtime_status, dict) else None,
                ),
            ),
            "diagnostics": diagnostics,
        }
        if "weekly_cadence" in payload or "frozen" in payload or "title" in payload or request.instructions:
            return response_payload
        return response_payload["plan"]

    @router.get("/plan/{plan_id}/subplans", response_model=None)
    def list_plan_subplans(plan_id: str) -> list[dict[str, object]]:
        return [subplan_payload(item) for item in runtime.planner_service.get_subplans_for_plan(plan_id)]

    @router.post("/plan/{plan_id}/subplan", response_model=None)
    def create_plan_subplan(plan_id: str, payload: dict) -> dict[str, object]:
        require_plan(plan_id)
        subplan = SubPlan.model_validate(payload)
        created = runtime.planner_service.create_subplan(plan_id, subplan)
        return subplan_payload(created)

    @router.put("/plan/{plan_id}/subplan/{subplan_id}", response_model=None)
    def update_plan_subplan(plan_id: str, subplan_id: str, payload: dict) -> dict[str, object]:
        require_plan(plan_id)
        subplan = SubPlan.model_validate(payload)
        updated = runtime.planner_service.update_subplan(plan_id, subplan_id, subplan)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Sub-plan '{subplan_id}' was not found.")
        return subplan_payload(updated)

    @router.delete("/plan/{plan_id}/subplan/{subplan_id}", response_model=None)
    def delete_plan_subplan(plan_id: str, subplan_id: str) -> dict[str, str]:
        require_plan(plan_id)
        deleted = runtime.planner_service.delete_subplan(plan_id, subplan_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Sub-plan '{subplan_id}' was not found.")
        return {"status": "deleted", "subplan_id": subplan_id, "plan_id": plan_id}



    return router
