"""Workspace/session identity, trust attestation, sandbox sync, snapshot hydration, and honesty gates."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException

from ...core.models import (
    AgentCheckpointAccessRequest,
    EvaluationReport,
    LearnerState,
    LearningPlan,
    ProjectProvisioning,
    ResourceRecord,
    SandboxWriteRequest,
    TaskSpec,
    WorkbenchSnapshot,
)
from ...memory.workspace_recovery import (
    AFFECT_STATE_KEY,
    CURRENT_TASK_KEY,
    PLAN_RUNTIME_KEY,
    formal_task_is_live_runtime_identity,
    leftover_formal_plan_is_live_for_fill,
    leftover_frozen_plan_blocks_generation,
    live_plan_snapshot_persist_chrome,
    select_latest_current_task,
    select_plan_runtime_for_scope,
)
from ...workspace.provisioning import (
    ProjectProvisioningConflictError,
    ProjectProvisioningIntegrityError,
)
from .. import coach_support
from .._helpers import (
    localized_text,
)
from .._singleflight import (
    claim_session_request_singleflight as claim_session_request_singleflight,
)
from .._singleflight import (
    fail_session_request_singleflight as fail_session_request_singleflight,
)
from .._singleflight import (
    publish_session_request_singleflight as publish_session_request_singleflight,
)
from ..router_support import (
    _attach_requested_workspace_files as _attach_requested_workspace_files,
)
from ..router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from ..router_support import (
    _resolve_agent_loop_enabled as _resolve_agent_loop_enabled,
)
from ..router_support import (
    overlay_session_response_honesty_stamps as overlay_session_response_honesty_stamps,
)
from ..router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from ..runtime import SessionState, WorkspaceBindingError
from ..training_card_identity import (
    require_live_selected_card_for_status as require_live_selected_card_for_status_impl,
)
from ..training_card_identity import (
    training_card_is_live_for_verify as training_card_is_live_for_verify_impl,
)
from ._base import RouterDomainBase

logger = logging.getLogger(__name__)


class WorkspaceAndHonestyDomainMixin(RouterDomainBase):
    """Workspace/session identity, trust attestation, sandbox sync, snapshot hydration, and honesty gates."""

    def current_workspace_id(self, session_id: str | None = None, workspace_id: str | None = None) -> str:
        return self.runtime.resolve_workspace_id(session_id=session_id, workspace_id=workspace_id)

    def trusted_write_workspace_id(self, 
        session_id: str | None = None, workspace_id: str | None = None
    ) -> str:
        """Strict workspace binding for trust-sensitive writes (409, no fallback).

        A stale or mismatched caller must not land evidence/asset writes in an
        unrelated workspace: an explicit workspace_id has to agree with the
        session binding, and an unresolvable binding is refused instead of
        falling back to the latest session or the default workspace.
        """
        try:
            return self.runtime.resolve_workspace_id_for_write(
                session_id=session_id,
                workspace_id=workspace_id,
            )
        except WorkspaceBindingError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc

    def apply_host_workspace_trust_attestation(self, workspace_id: str, payload: dict) -> None:
        """Apply host-attested workspace_trusted + remote_name before authority/capability."""
        has_remote = "remote_name" in payload or "remoteName" in payload
        has_trusted = (
            "workspace_trusted" in payload
            or "workspaceTrusted" in payload
            or "trusted" in payload
        )
        if not has_remote and not has_trusted:
            return
        trust_patch: dict[str, object] = {}
        if has_remote:
            remote_value = str(
                payload.get("remote_name", payload.get("remoteName") or "") or ""
            ).strip()
            trust_patch["remote_name"] = remote_value
            trust_patch["is_remote_workspace"] = bool(remote_value)
        if has_trusted:
            trust_patch["workspace_trusted"] = bool(
                payload.get(
                    "workspace_trusted",
                    payload.get("workspaceTrusted", payload.get("trusted", False)),
                )
            )
        self.runtime.memory_service.update_workspace_state(workspace_id, **trust_patch)
        self.runtime.workspace_authority(workspace_id)

    def require_sandbox_service(self):
        if self.runtime.sandbox_service is None:
            raise HTTPException(status_code=503, detail="Sandbox service is not configured.")
        self.runtime.sandbox_service.set_workspace_sandbox_root_resolver(
            self.runtime.resolve_workspace_sandbox_root
        )
        return self.runtime.sandbox_service

    def sync_resource_record_to_sandbox(self, workspace_id: str, resource: ResourceRecord) -> ResourceRecord:
        sandbox_service = self.require_sandbox_service()
        synced = sandbox_service.sync_resource(workspace_id, resource)
        self.runtime.repository.save_resource(workspace_id, synced)
        return synced

    def persist_plan_to_sandbox(self, 
        workspace_id: str,
        plan: LearningPlan | None,
        *,
        reason: str,
    ) -> None:
        if self.runtime.sandbox_service is None or plan is None:
            return
        try:
            memory = self.runtime.memory_service.snapshot(workspace_id)
            workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
            recovered = select_plan_runtime_for_scope(
                workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
                workspace_id,
            )
            leftover_runtime = recovered if isinstance(recovered, dict) else {}
            overlay = live_plan_snapshot_persist_chrome(
                plan=plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            self.runtime.sandbox_service.persist_plan_snapshot(
                workspace_id,
                plan,
                reason=reason,
                overlay=overlay,
                leftover_runtime=leftover_runtime,
            )
        except Exception:
            logger.exception(
                "Failed to persist plan snapshot into Trainer sandbox.",
                extra={"workspace_id": workspace_id},
            )

    def persist_training_card_to_sandbox(self, 
        workspace_id: str,
        card,
        *,
        mark_current: bool = True,
    ) -> None:
        if self.runtime.sandbox_service is None or card is None:
            return
        leftover = self.leftover_plan_state_fields(workspace_id)
        leftover_runtime = leftover.get("leftover_runtime")
        try:
            self.runtime.sandbox_service.persist_training_card(
                workspace_id,
                card,
                mark_current=mark_current,
                leftover_plan=leftover.get("leftover_plan"),
                leftover_runtime=leftover_runtime if isinstance(leftover_runtime, dict) else {},
                leftover_task_title=str(leftover.get("leftover_task_title") or ""),
            )
        except Exception:
            logger.exception(
                "Failed to persist training card into Trainer sandbox.",
                extra={"workspace_id": workspace_id, "card_id": getattr(card, "card_id", "")},
            )

    def persist_training_evaluation_note_to_sandbox(self, 
        *,
        workspace_id: str,
        card,
        passed: bool,
        summary: str,
        next_step: str,
        focus_area: str,
        failed_checks: list[str],
        missing_requirements: list[str],
        evidence_source: str,
    ) -> None:
        if self.runtime.sandbox_service is None:
            return
        leftover = self.leftover_plan_state_fields(workspace_id)
        leftover_runtime = leftover.get("leftover_runtime")
        try:
            self.runtime.sandbox_service.persist_training_evaluation_note(
                workspace_id,
                card=card,
                passed=passed,
                summary=summary,
                next_step=next_step,
                focus_area=focus_area,
                failed_checks=failed_checks,
                missing_requirements=missing_requirements,
                evidence_source=evidence_source,
                leftover_plan=leftover.get("leftover_plan"),
                leftover_runtime=leftover_runtime if isinstance(leftover_runtime, dict) else {},
                leftover_task_title=str(leftover.get("leftover_task_title") or ""),
            )
        except Exception:
            logger.exception(
                "Failed to persist training evaluation note into Trainer sandbox.",
                extra={"workspace_id": workspace_id, "card_id": getattr(card, "card_id", "")},
            )

    def workspace_learning_project_state(self, workspace_id: str) -> dict[str, str]:
        workspace = self.runtime.memory_service.snapshot(workspace_id).workspace
        if not isinstance(workspace, dict):
            return {}
        return {
            "prompt_status": str(workspace.get("learning_project_prompt_status") or "").strip().lower(),
            "sandbox_root_override": str(workspace.get("sandbox_root_override") or "").strip(),
            "source_path": str(workspace.get("learning_project_source_path") or "").strip(),
            "folder_name": str(workspace.get("learning_project_folder_name") or "").strip(),
        }

    def workspace_learning_project_prompt_needed(self, workspace_id: str) -> bool:
        workspace_path = str(self.runtime.resolve_workspace_path(workspace_id) or "").strip()
        if not workspace_path:
            return False
        state = self.workspace_learning_project_state(workspace_id)
        return not state.get("prompt_status") and not state.get("sandbox_root_override")

    def workspace_learning_project_prompt_text(self, 
        *,
        workspace_path: str,
        response_language: str | None,
    ) -> str:
        folder_name = Path(workspace_path).name or workspace_path
        return localized_text(
            f"Should Trainer treat the current VS Code folder `{folder_name}` as this workspace's learning project folder? Reply `use this folder` and I will create the matching project folder in Resources and keep it as the sandbox root.",
            f"要把当前 VS Code 打开的文件夹 `{folder_name}` 当作这个 workspace 的学习项目文件夹吗？你回复“用这个文件夹”，我就会在资料库里创建对应的项目文件夹，并把它固定成 sandbox root。",
            response_language,
        )

    def message_confirms_learning_project_folder(self, message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        return lowered in {
            "yes",
            "ok",
            "okay",
            "sure",
            "use this folder",
            "use current folder",
            "yes use it",
            "同意",
            "可以",
            "好",
            "好的",
            "用这个文件夹",
            "用当前文件夹",
            "就用这个文件夹",
        }

    def message_rejects_learning_project_folder(self, message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        return lowered in {
            "no",
            "no thanks",
            "not now",
            "skip",
            "不用",
            "先不用",
            "不要",
            "跳过",
        }

    def adopt_workspace_learning_project_folder(self, 
        *,
        workspace_id: str,
        workspace_name: str,
        response_language: str | None,
    ) -> tuple[str, str]:
        sandbox_service = self.require_sandbox_service()
        workspace_path = str(self.runtime.resolve_workspace_path(workspace_id) or "").strip()
        suggested_root = self.runtime.resolve_workspace_sandbox_root(workspace_id)
        if not suggested_root:
            suggested_root = str(
                sandbox_service.suggest_workspace_project_root(
                    workspace_id,
                    workspace_name=workspace_name,
                    workspace_path=workspace_path,
                )
            )
        self.runtime.register_workspace_sandbox_root(workspace_id, suggested_root)
        self.runtime.memory_service.update_workspace_state(
            workspace_id,
            sandbox_root_override=suggested_root,
            learning_project_prompt_status="linked",
            learning_project_source_path=workspace_path,
            learning_project_folder_name=Path(suggested_root).name,
        )
        root = sandbox_service.ensure_workspace_root(workspace_id)
        sandbox_service.write(
            workspace_id,
            SandboxWriteRequest(
                workspace_id=workspace_id,
                path="notes/project-link.md",
                content=(
                    f"# {workspace_name or Path(root).name}\n\n"
                    f"- Workspace source: {workspace_path or '(unknown)'}\n"
                    f"- Sandbox root: {root}\n"
                    "- Status: linked as the learning project folder\n"
                ),
                create=True,
            ),
        )
        return str(root), localized_text(
            f"Linked the current VS Code folder to Trainer's learning project folder and fixed the sandbox root at `{root}`.",
            f"已经把当前 VS Code 文件夹绑定成 Trainer 的学习项目文件夹，并把 sandbox root 固定到 `{root}`。",
            response_language,
        )

    def current_snapshot(self, session_id: str | None = None, workspace_id: str | None = None) -> WorkbenchSnapshot:
        resolved_workspace_id = self.current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        _, state = self.resolve_session_history_state(
            session_id=session_id, workspace_id=resolved_workspace_id
        )
        snapshot = state.snapshot.model_copy(deep=True) if state and state.workspace_id == resolved_workspace_id else WorkbenchSnapshot()
        snapshot.context_id = resolved_workspace_id
        snapshot.memory = self.runtime.memory_service.snapshot(resolved_workspace_id)
        snapshot.profile = self.runtime.repository.get_profile(resolved_workspace_id)
        self.runtime.hydrate_plan_context(snapshot, resolved_workspace_id)
        workspace_memory = snapshot.memory.workspace if isinstance(snapshot.memory.workspace, dict) else {}
        workspace_response_language = (
            str(workspace_memory.get("response_language")).strip()
            if workspace_memory.get("response_language")
            else None
        )
        workspace_answer_mode = (
            str(workspace_memory.get("answer_mode")).strip()
            if workspace_memory.get("answer_mode")
            else None
        )
        coach_support.hydrate_snapshot(self.coach_support_deps,
            snapshot,
            response_language=workspace_response_language,
            answer_mode=workspace_answer_mode or (snapshot.profile.answer_policy if snapshot.profile else None),
            preserve_session_history=bool(state and state.workspace_id == resolved_workspace_id),
        )
        # Hydration may rebuild card routing; a recovered runtime step remains
        # authoritative for the visible training next hop.
        from ...pedagogy.smalltalk import is_bogus_smalltalk_step

        workspace = snapshot.memory.workspace if snapshot.memory is not None else {}
        runtime_record = workspace.get("latest_plan_runtime") if isinstance(workspace, dict) else None
        current_step = str((runtime_record or {}).get("current_step") or "").strip()
        if current_step and not is_bogus_smalltalk_step(current_step) and isinstance(workspace, dict):
            current_hop = workspace.get("latest_training_next_hop")
            workspace["latest_training_next_hop"] = {
                **(current_hop if isinstance(current_hop, dict) else {}),
                "title": current_step,
                "card_title": current_step,
            }
        return snapshot

    def resolve_session_history_state(self, 
        *,
        session_id: str | None,
        workspace_id: str,
    ) -> tuple[str, SessionState] | tuple[None, None]:
        if session_id:
            state = self.runtime.get_session(session_id)
            if state is not None and state.workspace_id == workspace_id:
                return state.session_id, state
            restored_payload = self.runtime.repository.load_session(session_id)
            if restored_payload:
                restored = self.runtime._restore_session(restored_payload)
                if restored is not None and restored.workspace_id == workspace_id:
                    self.runtime.sessions[restored.session_id] = restored
                    return restored.session_id, restored

        latest = self.runtime.latest_session()
        if latest is not None and latest.workspace_id == workspace_id:
            return latest.session_id, latest

        restored_payload = self.runtime.repository.load_latest_session_for_workspace(workspace_id)
        if restored_payload:
            restored = self.runtime._restore_session(restored_payload)
            if restored is not None:
                self.runtime.sessions[restored.session_id] = restored
                return restored.session_id, restored
        return None, None

    def summarize_session_state(self, state: object) -> str:
        snapshot = getattr(state, "snapshot", None)
        messages = list(getattr(snapshot, "messages", []) or [])
        latest_user = next(
            (
                message
                for message in reversed(messages)
                if getattr(message, "role", "") == "user" and str(getattr(message, "content", "") or "").strip()
            ),
            None,
        )
        if latest_user is not None:
            return str(getattr(latest_user, "content", "") or "").strip()
        if messages:
            last_message = messages[-1]
            return str(getattr(last_message, "content", "") or "").strip()
        workspace = self.runtime.memory_service.snapshot(getattr(state, "workspace_id", "")).workspace
        if isinstance(workspace, dict):
            for key in ("latest_session_summary", "recent_summary", "summary"):
                value = str(workspace.get(key) or "").strip()
                if value:
                    return value
        workspace_name = str(getattr(state, "workspace_name", "") or "").strip()
        return workspace_name or "Trainer session"

    def refresh_workspace_sessions(self, workspace_id: str) -> None:
        for state in self.runtime.sessions.values():
            if state.workspace_id != workspace_id:
                continue
            state.snapshot.context_id = workspace_id
            state.snapshot.memory = self.runtime.memory_service.snapshot(workspace_id)
            state.snapshot.profile = self.runtime.repository.get_profile(workspace_id)
            self.runtime.hydrate_plan_context(state.snapshot, workspace_id)
            self.runtime.save_session_state(state.session_id)

    def routing_plan_state(self, workspace_id: str) -> dict[str, object]:
        leftover_fields = self.leftover_plan_state_fields(workspace_id)
        plan = leftover_fields.get("leftover_plan")
        if not isinstance(plan, LearningPlan):
            return leftover_fields
        active_stage = next(
            (
                stage
                for stage in plan.stages
                if stage.id == plan.current_stage_id or stage.status == "active"
            ),
            plan.stages[0] if plan.stages else None,
        )
        if active_stage is None:
            return leftover_fields
        return {
            "active_stage_id": active_stage.id,
            "active_stage_skills": [item for item in active_stage.outcomes if item],
            "active_project_id": workspace_id,
            **leftover_fields,
        }

    def routing_learner_state(self, workspace_id: str) -> dict[str, object]:
        memory = self.runtime.memory_service.snapshot(workspace_id)
        workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
        recent_errors: list[str] = []
        for item in list(memory.learning_outcomes)[-6:]:
            outcome = str(getattr(item, "outcome", "") or "").strip().lower()
            if outcome not in {"fail", "blocked", "repeated_error", "abandoned", "partial"}:
                continue
            focus_area = str(getattr(item, "focus_area", "") or "").strip()
            if focus_area:
                recent_errors.append(focus_area)
            for concept in list(getattr(item, "concepts", []) or [])[:2]:
                cleaned = str(concept or "").strip()
                if cleaned:
                    recent_errors.append(cleaned)
        blocker_focus = str(workspace.get("latest_learning_focus_area") or "").strip()
        needs_rescue = bool(
            str(workspace.get("latest_learning_blocker") or "").strip()
            or str(workspace.get("latest_flashcard_recovery_mode") or "").strip()
        )
        from ...memory.transfer_skills import normalize_transfer_skill_state_record
        from ...pedagogy.evidence_controls import controls_from_profile, routing_learner_overrides

        overrides = routing_learner_overrides(controls_from_profile(memory.coaching_adaptation))
        transfer = normalize_transfer_skill_state_record(workspace.get("latest_transfer_state"))
        adaptation = memory.coaching_adaptation
        scene_count = 0
        if adaptation is not None:
            scene_count = int(getattr(adaptation, "transfer_scene_count", 0) or 0)
        if transfer and int(transfer.get("scene_count") or 0) > scene_count:
            scene_count = int(transfer.get("scene_count") or 0)
        return {
            "weaknesses": list(memory.weaknesses or []),
            "recent_errors": recent_errors,
            "difficulty_preference": overrides["difficulty_preference"],
            "needs_rescue": bool(overrides["needs_rescue"]) or needs_rescue,
            "active_blockers": [blocker_focus] if blocker_focus and needs_rescue else [],
            "preferred_practice_type": overrides.get("preferred_practice_type"),
            "review_frequency": overrides.get("review_frequency"),
            "material_recommendation": overrides.get("material_recommendation"),
            "transfer_scene_count": scene_count,
            "transfer_state": str((transfer or {}).get("state") or ""),
            "time_budget": overrides.get("time_budget"),
            "project_complexity": overrides.get("project_complexity"),
            "task_urgency": overrides.get("task_urgency"),
        }

    def resource_trust_state(self, resource: ResourceRecord) -> str:
        return resource.trust_state

    def leftover_runtime_for_workspace(self, workspace_id: str) -> tuple[LearningPlan | None, dict[str, object]]:
        plan = self.runtime.repository.get_latest_plan(workspace_id)
        memory = self.runtime.memory_service.snapshot(workspace_id)
        workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
        recovered = select_plan_runtime_for_scope(
            workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
            workspace_id,
        )
        return plan, recovered if isinstance(recovered, dict) else {}

    def require_live_selected_card_for_status(self, workspace_id: str, card_id: str) -> None:
        """Leftover-not-live dump must not skip/grade/reflect/return as live."""
        require_live_selected_card_for_status_impl(self.runtime, workspace_id, card_id)

    def training_card_is_live_for_verify(self, workspace_id: str, card_id: str) -> bool:
        return training_card_is_live_for_verify_impl(self.runtime, workspace_id, card_id)

    def leftover_task_title_for_workspace(self, workspace_id: str) -> str:
        memory = self.runtime.memory_service.snapshot(workspace_id)
        workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
        task = select_latest_current_task(
            workspace.get(CURRENT_TASK_KEY)
            or workspace.get("current_task")
            or workspace.get("currentTask"),
            workspace_id,
        ) or {}
        return str(task.get("title") or "").strip()

    def leftover_plan_state_fields(self, workspace_id: str) -> dict[str, object]:
        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        return {
            "leftover_plan": leftover_plan,
            "leftover_runtime": leftover_runtime,
            "leftover_task_title": self.leftover_task_title_for_workspace(workspace_id),
        }

    def leftover_frozen_blocks_turn_generation(self, workspace_id: str) -> bool:
        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        return leftover_frozen_plan_blocks_generation(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        )

    def recovered_overlay_without_live_object(self, workspace_id: str) -> bool:
        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        if leftover_plan is None and not leftover_runtime:
            return False
        # Empty recovered runtime (cold-start empty restore) is still a recovered
        # overlay: attach_plan_runtime_status stamps recovered=True for it, so the
        # leftover must read as not-live here too. leftover_formal_plan_is_live_for_fill
        # defaults to True on empty dicts (fill-permissive), hence the explicit guard.
        live_plan = bool(leftover_runtime) and leftover_formal_plan_is_live_for_fill(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        )
        live_task = bool(leftover_runtime) and formal_task_is_live_runtime_identity(
            recovered=True,
            runtime_current_step=str(
                leftover_runtime.get("current_step")
                or leftover_runtime.get("currentStep")
                or ""
            ),
            task_title=self.leftover_task_title_for_workspace(workspace_id),
        )
        return not live_plan and not live_task

    def closed_loop_return_blocks_task_mint(self, workspace_id: str) -> bool:
        """After Learn→Try→Verify→Reflect→Return with a live plan, do not invent TaskSpec.

        Explicit POST /task/next and /task/specify remain the mint paths. /turn next_task
        chips must stay hint/review only so the closed loop does not mint a parallel task.
        """
        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
        if not leftover_formal_plan_is_live_for_fill(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            return False
        workspace = self.runtime.memory_service.snapshot(workspace_id).workspace
        workspace = workspace if isinstance(workspace, dict) else {}
        handoff = workspace.get("latest_training_handoff") or workspace.get("latestTrainingHandoff")
        if not isinstance(handoff, dict) or not handoff:
            return False
        phase = str(handoff.get("phase") or "").strip().lower()
        status = str(handoff.get("status") or "").strip().lower()
        handoff_status = str(
            handoff.get("handoff_status") or handoff.get("handoffStatus") or ""
        ).strip().lower()
        continue_in = str(
            handoff.get("continue_in") or handoff.get("continueIn") or ""
        ).strip().lower()
        if phase == "return" and status in {"completed", "complete"}:
            return True
        return handoff_status == "verified" and continue_in in {"chat", "coach"}

    def live_formal_plan_for_explicit_task_next(self, workspace_id: str) -> LearningPlan | None:
        """Explicit POST /task/next may mint TaskSpec only for a live-bound formal plan.

        Empty recovered runtime or mismatched plan_id is leftover-not-live: do not invent.
        No formal plan at all: do not invent a plan+task pair (including under high urgency).
        /plan/generate remains the bind path; this route must not invent a LearningPlan.
        """
        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        if leftover_plan is None or not leftover_runtime:
            return None
        if not leftover_formal_plan_is_live_for_fill(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            return None
        return leftover_plan

    def should_remap_task_intent_without_live_plan(self, 
        workspace_id: str,
        *,
        message: str | None = None,
        snapshot: WorkbenchSnapshot | None = None,
        current_task: TaskSpec | None = None,
        current_plan: LearningPlan | None = None,
    ) -> bool:
        """Shared gate: task/next_task intent → coach; no TaskSpec / minting chips.

        Used by request_with_workspace_defaults (/turn, /turn/stream), scenario coerce,
        and honest_suggested_actions (/session/message(+stream) chat parity).
        """
        return (
            self.live_formal_plan_for_explicit_task_next(workspace_id) is None
            or self.recovered_overlay_without_live_object(workspace_id)
            or self.closed_loop_return_blocks_task_mint(workspace_id)
            or self.streak_without_live_object_blocks_mint(
                workspace_id,
                snapshot=snapshot,
                current_task=current_task,
                current_plan=current_plan,
            )
            or self.pressure_without_live_object_blocks_mint(
                workspace_id,
                snapshot=snapshot,
                current_task=current_task,
                current_plan=current_plan,
                message=message,
            )
        )

    def require_live_formal_plan_for_explicit_task_next(self, 
        workspace_id: str,
        *,
        route: str = "/task/next",
    ) -> LearningPlan:
        live = self.live_formal_plan_for_explicit_task_next(workspace_id)
        if live is not None:
            return live
        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        if leftover_plan is not None and leftover_runtime:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Recovered plan runtime is leftover-not-live. "
                    f"{route} will not invent a TaskSpec or resurrect the leftover as live."
                ),
            )
        raise HTTPException(
            status_code=409,
            detail=(
                "No live learning plan is bound. Generate a plan first; "
                f"{route} does not invent a plan or TaskSpec."
            ),
        )

    def streak_without_live_object_blocks_mint(self, 
        workspace_id: str,
        *,
        snapshot: WorkbenchSnapshot | None = None,
        current_task: TaskSpec | None = None,
        current_plan: LearningPlan | None = None,
    ) -> bool:
        from ...pedagogy.evidence_controls import streak_adapts_without_inventing_live_objects

        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        plan = current_plan or leftover_plan
        if plan is None and snapshot is not None:
            plan = snapshot.plan
        task = current_task
        if task is None and snapshot is not None:
            task = snapshot.current_task
        if leftover_runtime:
            live_plan = leftover_formal_plan_is_live_for_fill(
                plan=plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            live_task = formal_task_is_live_runtime_identity(
                recovered=True,
                runtime_current_step=str(
                    leftover_runtime.get("current_step")
                    or leftover_runtime.get("currentStep")
                    or ""
                ),
                task_title=str(
                    getattr(task, "title", "") or self.leftover_task_title_for_workspace(workspace_id)
                ),
            )
        else:
            live_plan = plan is not None and bool(
                str(getattr(plan, "id", "") or getattr(plan, "plan_id", "") or "").strip()
                or str(getattr(plan, "current_step", "") or "").strip()
            )
            live_task = task is not None and bool(
                str(getattr(task, "title", "") or getattr(task, "natural_language_goal", "") or "").strip()
            )
        live_card = bool(
            workspace_id
            and self.runtime.memory_service.live_selected_training_card_id(workspace_id)
        )
        adaptation = None
        if snapshot is not None and snapshot.memory is not None:
            adaptation = getattr(snapshot.memory, "coaching_adaptation", None)
        if adaptation is None and workspace_id:
            adaptation = getattr(
                self.runtime.memory_service.snapshot(workspace_id),
                "coaching_adaptation",
                None,
            )
        failure_streak = int(getattr(adaptation, "failure_streak", 0) or 0) if adaptation is not None else 0
        success_streak = int(getattr(adaptation, "success_streak", 0) or 0) if adaptation is not None else 0
        return streak_adapts_without_inventing_live_objects(
            failure_streak=failure_streak,
            success_streak=success_streak,
            live_plan=live_plan,
            live_task=live_task,
            live_card=live_card,
        )

    def pressure_without_live_object_blocks_mint(self, 
        workspace_id: str,
        *,
        snapshot: WorkbenchSnapshot | None = None,
        current_task: TaskSpec | None = None,
        current_plan: LearningPlan | None = None,
        message: str | None = None,
    ) -> bool:
        from ...pedagogy.context_pressure import (
            normalize_project_complexity,
            normalize_task_urgency,
            normalize_time_budget,
            pressure_adapts_without_inventing_live_objects,
        )

        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        plan = current_plan or leftover_plan
        if plan is None and snapshot is not None:
            plan = getattr(snapshot, "plan", None)
        task = current_task
        if task is None and snapshot is not None:
            task = getattr(snapshot, "current_task", None)
        if leftover_runtime:
            live_plan = leftover_formal_plan_is_live_for_fill(
                plan=plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            live_task = formal_task_is_live_runtime_identity(
                recovered=True,
                runtime_current_step=str(
                    leftover_runtime.get("current_step")
                    or leftover_runtime.get("currentStep")
                    or ""
                ),
                task_title=str(
                    getattr(task, "title", "") or self.leftover_task_title_for_workspace(workspace_id)
                ),
            )
        else:
            live_plan = plan is not None and bool(
                str(getattr(plan, "id", "") or getattr(plan, "plan_id", "") or "").strip()
                or str(getattr(plan, "current_step", "") or "").strip()
            )
            live_task = task is not None and bool(
                str(getattr(task, "title", "") or getattr(task, "natural_language_goal", "") or "").strip()
            )
        live_memory = self.runtime.memory_service.snapshot(workspace_id) if workspace_id else None
        memory = getattr(snapshot, "memory", None) if snapshot is not None else None
        workspace_state: dict[str, object] = {}
        if live_memory is not None and isinstance(getattr(live_memory, "workspace", None), dict):
            workspace_state = live_memory.workspace
        elif memory is not None and isinstance(getattr(memory, "workspace", None), dict):
            workspace_state = memory.workspace
        live_card = bool(
            workspace_id
            and self.runtime.memory_service.live_selected_training_card_id(workspace_id)
        )
        # Prefer live memory adaptation so just-persisted affect/urgency wins over a
        # stale snapshot coaching_adaptation (high urgency without weekly_hours).
        adaptation = (
            getattr(live_memory, "coaching_adaptation", None)
            if live_memory is not None
            else None
        )
        if adaptation is None and memory is not None:
            adaptation = getattr(memory, "coaching_adaptation", None)
        time_budget = (
            str(getattr(adaptation, "time_budget", "normal") or "normal")
            if adaptation is not None
            else "normal"
        )
        task_urgency = (
            str(getattr(adaptation, "task_urgency", "medium") or "medium")
            if adaptation is not None
            else "medium"
        )
        workspace_urgency = str(
            workspace_state.get("task_urgency")
            or workspace_state.get("taskUrgency")
            or ""
        ).strip()
        if workspace_urgency and normalize_task_urgency(workspace_urgency) == "high":
            task_urgency = "high"
        affect_payload = workspace_state.get(AFFECT_STATE_KEY) or workspace_state.get("affect_state")
        if isinstance(affect_payload, dict):
            affect_urgency = str(
                affect_payload.get("urgency_level") or affect_payload.get("urgencyLevel") or ""
            ).strip()
            if affect_urgency and normalize_task_urgency(affect_urgency) == "high":
                task_urgency = "high"
        # safe_activate runs before resolve_coach_turn persist; message-time high
        # urgency must still fail-close invent (same as tight budget).
        if message and normalize_task_urgency(task_urgency) != "high":
            memory_for_affect = memory if memory is not None else live_memory
            if memory_for_affect is not None:
                learner_state = (
                    getattr(snapshot, "learner_state", None) if snapshot is not None else None
                )
                if learner_state is None:
                    learner_state = LearnerState()
                turn_affect = self.runtime.affect_service.infer_state(
                    message=str(message or ""),
                    learner_state=learner_state,
                    memory_snapshot=memory_for_affect,
                )
                if (
                    turn_affect is not None
                    and normalize_task_urgency(turn_affect.urgency_level) == "high"
                ):
                    task_urgency = "high"
        if workspace_state.get("time_budget") and normalize_time_budget(
            workspace_state.get("time_budget")
        ) == "tight":
            time_budget = "tight"
        project_complexity = (
            str(getattr(adaptation, "project_complexity", "moderate") or "moderate")
            if adaptation is not None
            else "moderate"
        )
        if workspace_state.get("project_complexity") and normalize_project_complexity(
            workspace_state.get("project_complexity")
        ) == "complex":
            project_complexity = "complex"
        current_ability = str(
            workspace_state.get("current_ability")
            or workspace_state.get("currentAbility")
            or ""
        ).strip()
        user_preference = str(
            workspace_state.get("latest_user_feedback_kind")
            or workspace_state.get("latestUserFeedbackKind")
            or ""
        ).strip()
        if not user_preference:
            from ...pedagogy.context_pressure import preference_equivalent_from_strategy_bias

            user_preference = preference_equivalent_from_strategy_bias(
                challenge_level=(
                    str(getattr(adaptation, "challenge_level", "") or "")
                    if adaptation is not None
                    else ""
                ),
                hint_depth=(
                    str(getattr(adaptation, "hint_depth", "") or "")
                    if adaptation is not None
                    else ""
                ),
                next_step_bias=(
                    str(getattr(adaptation, "next_step_bias", "") or "")
                    if adaptation is not None
                    else ""
                ),
                feedback_next_step_bias=str(
                    workspace_state.get("feedback_next_step_bias")
                    or workspace_state.get("feedbackNextStepBias")
                    or ""
                ),
            )
        from ...pedagogy.evidence_controls import (
            analyze_learning_evidence,
            pedagogy_evidence_confidence,
        )

        outcomes: list[object] = []
        if live_memory is not None:
            outcomes = list(getattr(live_memory, "learning_outcomes", []) or [])
        elif memory is not None:
            outcomes = list(getattr(memory, "learning_outcomes", []) or [])
        evidence_signals = analyze_learning_evidence(outcomes)
        return pressure_adapts_without_inventing_live_objects(
            time_budget=time_budget,
            task_urgency=task_urgency,
            project_complexity=project_complexity,
            current_ability=current_ability,
            user_preference=user_preference,
            evidence_confidence=pedagogy_evidence_confidence(
                verified_success=bool(evidence_signals.verified_success),
                success_count=int(evidence_signals.success_count or 0),
                outcomes=outcomes,
            ),
            live_plan=live_plan,
            live_task=live_task,
            live_card=live_card,
        )

    def honest_suggested_actions_without_live_object(self, 
        actions: list[dict[str, object]],
        *,
        workspace_id: str,
        response_language: str | None,
        snapshot: WorkbenchSnapshot | None = None,
        current_task: TaskSpec | None = None,
        current_plan: LearningPlan | None = None,
        current_evaluation: EvaluationReport | None = None,
        message: str | None = None,
        scenario: str = "general",
    ) -> list[dict[str, object]]:
        if not self.should_remap_task_intent_without_live_plan(
            workspace_id,
            message=message,
            snapshot=snapshot,
            current_task=current_task,
            current_plan=current_plan,
        ):
            return actions
        # Domain lanes keep their chips: on plan / idea / project scenarios the
        # lane itself is the honest context (plan generation is the documented
        # recovery path, and a task chip click re-enters /turn where the intent
        # remap stays fail-closed). On generic lanes (general / review /
        # remapped task lanes) no mint chip is honest without a live object.
        # Exception: a leftover plan recovered as not-live must never offer
        # mint chips on any lane — clicking one would resurrect or rebind the
        # leftover, which the recovery contract forbids.
        if scenario in {
            "plan",
            "idea_implementation",
            "project_adaptation",
            "project_idea",
            "project_sourcing",
        } and not self.recovered_overlay_without_live_object(workspace_id):
            return list(actions)
        mint_actions = {"plan", "task", "next_task"}
        kept = [
            item
            for item in actions
            if str(item.get("action") or "").strip() not in mint_actions
        ]
        if kept:
            return kept
        fallback_label = localized_text(
            "Continue from the recovered step",
            "从已恢复的这一步继续",
            response_language,
        )
        if self.closed_loop_return_blocks_task_mint(workspace_id):
            fallback_label = localized_text(
                "Stay with the live plan step. Do not mint a task or second plan.",
                "继续当前正式计划这一步，不要另造任务或第二份计划。",
                response_language,
            )
        elif not self.recovered_overlay_without_live_object(workspace_id):
            fallback_label = localized_text(
                "Stay with a smaller hint. Do not generate a plan, card, or task.",
                "先给更小的提示，不要生成计划、卡片或任务。",
                response_language,
            )
        return self.structured_suggested_actions(
            [
                {
                    "label": fallback_label,
                    "action": "hint",
                }
            ],
            response_language=response_language,
            scenario="general",
            focus_area=self.stateful_focus_area(
                current_task,
                current_plan,
                current_evaluation,
                snapshot=snapshot,
            ),
        )

    def force_new_session_requested(self, payload: dict) -> bool:
        """Treat only an explicit truthy flag as a request to discard the active thread."""
        value = payload.get("force_new")
        if value is None:
            value = payload.get("forceNew")
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value == 1
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def normalize_trainer_root_path(self, value: str) -> str:
        raw_path = str(value or "").strip()
        if not raw_path:
            raise ProjectProvisioningConflictError("A Trainer workspace root is required.")
        try:
            normalized = Path(raw_path).expanduser().resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ProjectProvisioningConflictError(
                "The selected Trainer workspace root cannot be normalized."
            ) from exc
        if not normalized.is_dir():
            raise ProjectProvisioningConflictError(
                "The selected Trainer workspace root must be an available directory."
            )
        return str(normalized)

    def project_provisioning_repair_detail(self, response_language: str | None) -> dict[str, object]:
        return {
            "state": "repair_required",
            "status": "blocked",
            "recoverable": True,
            "detail": localized_text(
                "The managed project needs repair before it can be resumed.",
                "这个托管项目需要先修复，才能恢复会话。",
                response_language,
            ),
            "next_step": localized_text(
                "Restore the missing structured memory, then re-run /session/start.",
                "先恢复缺失的 structured_memory，然后重新调用 /session/start。",
                response_language,
            ),
        }

    def validate_project_provisioning_or_repair(self, workspace_id: str, response_language: str | None) -> ProjectProvisioning | None:
        try:
            return self.runtime.get_project_provisioning(workspace_id)
        except ProjectProvisioningIntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail=self.project_provisioning_repair_detail(response_language),
            ) from exc

    def summarize_session_list_payload(self, payload: dict[str, object]) -> dict[str, object] | None:
        snapshot = payload.get("snapshot")
        messages = list(snapshot.get("messages") or []) if isinstance(snapshot, dict) else []
        latest_user_message = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, dict)
                and message.get("role") == "user"
                and str(message.get("content") or "").strip()
            ),
            None,
        )
        latest_assistant_message = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, dict)
                and message.get("role") == "assistant"
                and str(message.get("content") or "").strip()
            ),
            None,
        )
        summary = str(
            (latest_user_message or {}).get("content")
            or (latest_assistant_message or {}).get("content")
            or payload.get("workspace_name")
            or ""
        ).strip()
        if not summary and not messages:
            return None
        updated_at = ""
        if messages:
            last_message = messages[-1]
            if isinstance(last_message, dict):
                updated_at = str(
                    last_message.get("created_at") or last_message.get("timestamp") or ""
                ).strip()
        item: dict[str, object] = {
            "session_id": str(payload.get("session_id") or "").strip(),
            "workspace_id": str(payload.get("workspace_id") or "").strip(),
            "workspace_name": str(payload.get("workspace_name") or "").strip(),
            "summary": summary,
            "message_count": len(messages),
            "updated_at": updated_at or None,
        }
        if latest_user_message is not None:
            item["latest_user_message"] = str(latest_user_message.get("content") or "").strip()
        if latest_assistant_message is not None:
            item["latest_assistant_message"] = str(latest_assistant_message.get("content") or "").strip()
        return item

    def read_agent_checkpoint_or_raise(self, 
        *,
        checkpoint_id: str,
        scope: AgentCheckpointAccessRequest,
    ) -> dict[str, object]:
        try:
            checkpoint = self.runtime.read_agent_turn_checkpoint(
                checkpoint_id=checkpoint_id,
                workspace_id=scope.workspace_id,
                session_id=scope.session_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Checkpoint access was denied.") from exc
        if checkpoint is None:
            raise HTTPException(status_code=404, detail="Checkpoint was not found for this workspace.")
        return checkpoint
