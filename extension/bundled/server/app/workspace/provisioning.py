"""Durable Root/Project/Context provisioning for Trainer workspaces."""

from __future__ import annotations

from os.path import normcase, normpath
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..core.models import (
    LearningPlan,
    ProjectContext,
    ProjectProvisioning,
    TrainerProject,
    TrainerRoot,
    UserProfile,
    WorkbenchSnapshot,
)
from ..db.repository import TrainerRepository
from ..memory.service import MemoryService, StructuredMemoryService
from ..planner.service import PlannerService


class ProjectProvisioningConflictError(ValueError):
    """The requested project cannot be associated with the selected Root/context."""


class ProjectProvisioningIntegrityError(RuntimeError):
    """Stored provisioning evidence no longer describes a usable project lane."""


def _canonical_path(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ProjectProvisioningConflictError(f"A {label} path is required for provisioning.")
    try:
        return str(Path(normalized).expanduser().resolve(strict=False))
    except (OSError, RuntimeError) as exc:
        raise ProjectProvisioningConflictError(f"The {label} path cannot be normalized.") from exc


def _path_key(value: str) -> str:
    return normcase(normpath(value))


def _paths_equal(left: str, right: str) -> bool:
    return _path_key(left) == _path_key(right)


def _require_directory(path_value: str, label: str) -> None:
    try:
        is_directory = Path(path_value).is_dir()
    except OSError as exc:
        raise ProjectProvisioningConflictError(f"The {label} path cannot be inspected.") from exc
    if not is_directory:
        raise ProjectProvisioningConflictError(f"The {label} path must be an existing directory.")


def _assert_distinct_root_and_project(root_path: str, project_path: str) -> None:
    """Keep Trainer's state container separate from the selected code project."""
    if _paths_equal(root_path, project_path):
        raise ProjectProvisioningConflictError(
            "The Trainer workspace root and selected project must be different directories."
        )


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


class ProjectProvisioningService:
    """Creates the isolated state required before a discovery becomes managed."""

    def __init__(
        self,
        *,
        repository: TrainerRepository,
        memory_service: MemoryService,
        planner_service: PlannerService,
    ) -> None:
        self.repository = repository
        self.memory_service = memory_service
        self.planner_service = planner_service

    def get(self, context_id_or_alias: str) -> ProjectProvisioning | None:
        provisioning = self.repository.get_project_provisioning(context_id_or_alias.strip())
        if provisioning is not None:
            self._verify(provisioning)
        return provisioning

    def provision(
        self,
        *,
        project_path: str,
        project_name: str,
        workspace_id: str | None = None,
        context_id: str | None = None,
        root_id: str | None = None,
        root_path: str | None = None,
    ) -> ProjectProvisioning:
        """Create or recover one context without deriving identity from a path.

        ``workspace_id`` remains a read-compatible alias.  New persistence always
        uses the generated context ID so separate projects under one Root cannot
        share project memory, plans, training state, or agent sessions.
        """

        normalized_project_path = _canonical_path(project_path, "project")
        _require_directory(normalized_project_path, "project")
        normalized_project_name = project_name.strip() or Path(normalized_project_path).name
        if not normalized_project_name:
            raise ProjectProvisioningConflictError("A project name is required for provisioning.")

        normalized_workspace_id = str(workspace_id or "").strip()
        normalized_context_id = str(context_id or "").strip()
        lookup_id = normalized_context_id or normalized_workspace_id
        requested = self.repository.get_project_provisioning(lookup_id) if lookup_id else None
        if requested is not None and _path_key(requested.project_path) == _path_key(normalized_project_path):
            self._assert_requested_root(requested, root_id=root_id, root_path=root_path)
            self._verify(requested)
            return requested
        if normalized_context_id and requested is not None:
            raise ProjectProvisioningConflictError("This context already belongs to a different project.")
        if requested is not None and not (root_id or root_path):
            raise ProjectProvisioningConflictError(
                "This workspace alias already belongs to a different managed project."
            )

        root = self._resolve_root(
            root_id=root_id,
            root_path=root_path,
            project_path=normalized_project_path,
        )
        existing_project = self.repository.get_trainer_project_by_path(root.root_id, normalized_project_path)
        if existing_project is not None:
            existing_context = self.repository.get_project_context_for_project(existing_project.project_id)
            if existing_context is None:
                raise ProjectProvisioningIntegrityError("The existing project has no recoverable context.")
            existing = self.repository.get_project_provisioning(existing_context.context_id)
            if existing is None:
                raise ProjectProvisioningIntegrityError("The existing project context cannot be loaded.")
            self._verify(existing)
            return existing

        if normalized_context_id:
            raise ProjectProvisioningConflictError("An unknown context ID cannot be used to create a project.")

        legacy_workspace_id = (
            normalized_workspace_id
            if normalized_workspace_id and self.repository.resolve_context_id(normalized_workspace_id) is None
            else None
        )
        project = TrainerProject(
            projectId=_new_id("project"),
            rootId=root.root_id,
            projectPath=normalized_project_path,
            projectName=normalized_project_name,
        )
        context = ProjectContext(
            contextId=_new_id("context"),
            rootId=root.root_id,
            projectId=project.project_id,
            projectMemoryId=_new_id("project-memory"),
            projectPlanId=_new_id("project-plan"),
            projectTrainingId=_new_id("project-training"),
            projectAgentContextId=_new_id("project-agent"),
            agentSessionId=_new_id("session-project"),
            legacyWorkspaceId=legacy_workspace_id,
            globalPlanId=self._active_global_plan_id(),
        )
        provisioning = ProjectProvisioning(
            **context.model_dump(by_alias=True),
            workspaceId=context.context_id,
            rootPath=root.root_path,
            projectPath=project.project_path,
            projectName=project.project_name,
        )
        profile = self._project_profile(context.context_id, project.project_path, project.project_name)
        structured_memory = self._project_structured_memory(profile, provisioning)
        session_payload = self._project_session_payload(profile, None, provisioning)
        persisted = self.repository.create_project_context_bundle(
            root=root,
            project=project,
            context=context,
            profile=profile,
            plan=None,
            structured_memory=structured_memory,
            session_payload=session_payload,
            global_plan_link=None,
        )
        self.memory_service.clear_workspace_memory(persisted.context_id)
        self._verify(persisted)
        return persisted

    def _resolve_root(
        self,
        *,
        root_id: str | None,
        root_path: str | None,
        project_path: str,
    ) -> TrainerRoot:
        normalized_root_id = str(root_id or "").strip()
        normalized_root_path = _canonical_path(root_path, "workspace root") if root_path else None
        if normalized_root_id:
            root = self.repository.get_trainer_root(normalized_root_id)
            if root is None:
                raise ProjectProvisioningConflictError("The selected Trainer root does not exist.")
            if normalized_root_path and _path_key(root.root_path) != _path_key(normalized_root_path):
                raise ProjectProvisioningConflictError("The supplied root path does not match the selected Trainer root.")
        else:
            if normalized_root_path is None:
                raise ProjectProvisioningConflictError(
                    "An explicit Trainer workspace root is required before adopting a project."
                )
            selected_root_path = normalized_root_path
            root = self.repository.get_trainer_root_by_path(selected_root_path)
            if root is None:
                root = TrainerRoot(
                    rootId=_new_id("root"),
                    rootPath=selected_root_path,
                    displayName=Path(selected_root_path).name or "Trainer Workspace",
                )
        _require_directory(root.root_path, "Trainer workspace root")
        _assert_distinct_root_and_project(root.root_path, project_path)
        return root

    def _assert_requested_root(
        self,
        provisioning: ProjectProvisioning,
        *,
        root_id: str | None,
        root_path: str | None,
    ) -> None:
        normalized_root_id = str(root_id or "").strip()
        if normalized_root_id and normalized_root_id != provisioning.root_id:
            raise ProjectProvisioningConflictError("The context does not belong to the requested Trainer root.")
        if root_path and _path_key(_canonical_path(root_path, "workspace root")) != _path_key(provisioning.root_path):
            raise ProjectProvisioningConflictError("The context does not belong to the requested root path.")

    def _active_global_plan_id(self) -> str | None:
        global_plan = self.repository.get_default_global_plan()
        return global_plan.id if global_plan is not None and not global_plan.frozen else None

    def _project_profile(
        self,
        context_id: str,
        project_path: str,
        project_name: str,
    ) -> UserProfile:
        existing = self.repository.get_profile(context_id)
        if existing is None:
            goal = f"Understand and advance the {project_name} project."
            return UserProfile(
                long_term_goal=goal,
                long_term_goals=[goal],
                target_project=project_path,
            )
        return UserProfile(
            long_term_goal=existing.long_term_goal,
            long_term_goals=list(existing.long_term_goals),
            background=existing.background,
            weekly_hours=existing.weekly_hours,
            teaching_style=existing.teaching_style,
            answer_policy=existing.answer_policy,
            target_project=project_path,
            preferred_libraries=list(existing.preferred_libraries),
        )

    def _project_structured_memory(
        self,
        profile: UserProfile,
        provisioning: ProjectProvisioning,
    ) -> dict[str, Any]:
        existing = self.repository.load_structured_memory(provisioning.context_id)
        structured = StructuredMemoryService.from_state(existing)
        structured.update_profile(**profile.model_dump(mode="json"))
        structured.update_workspace(
            workspace_id=provisioning.context_id,
            context_id=provisioning.context_id,
            root_id=provisioning.root_id,
            root_path=provisioning.root_path,
            project_id=provisioning.project_id,
            project_path=provisioning.project_path,
            canonical_project_path=provisioning.project_path,
            project_name=provisioning.project_name,
            project_memory={
                "id": provisioning.project_memory_id,
                "scope": "project",
                "status": "ready",
            },
            project_training_state={
                "id": provisioning.project_training_id,
                "status": "ready",
                "active_card_id": None,
                "evidence_status": "awaiting_evidence",
            },
            project_agent_context={
                "id": provisioning.project_agent_context_id,
                "session_id": provisioning.agent_session_id,
                "checkpoint_id": f"checkpoint-{provisioning.context_id}",
                "status": "ready",
            },
            project_provisioning=provisioning.model_dump(mode="json", by_alias=True),
        )
        return structured.export_state()

    @staticmethod
    def _project_session_payload(
        profile: UserProfile,
        plan: LearningPlan | None,
        provisioning: ProjectProvisioning,
    ) -> dict[str, Any]:
        snapshot = WorkbenchSnapshot(profile=profile, plan=plan)
        return {
            "session_id": provisioning.agent_session_id,
            "workspace_id": provisioning.context_id,
            "workspace_name": provisioning.project_name,
            "snapshot": snapshot.model_dump(mode="json"),
        }

    def _verify(self, provisioning: ProjectProvisioning) -> None:
        context = self.repository.get_project_context(provisioning.context_id)
        root = self.repository.get_trainer_root(provisioning.root_id)
        project = self.repository.get_trainer_project(provisioning.project_id)
        if context is None or root is None or project is None:
            raise ProjectProvisioningIntegrityError("The managed project identity is incomplete.")
        if (
            context.context_id != provisioning.context_id
            or context.root_id != provisioning.root_id
            or context.project_id != provisioning.project_id
            or project.root_id != root.root_id
            or _path_key(project.project_path) != _path_key(provisioning.project_path)
        ):
            raise ProjectProvisioningIntegrityError("The managed project identity is inconsistent.")
        if _paths_equal(root.root_path, project.project_path):
            raise ProjectProvisioningIntegrityError(
                "The managed project cannot use its Trainer workspace root as the project directory."
            )
        if context.legacy_workspace_id:
            if self.repository.resolve_context_id(context.legacy_workspace_id) != context.context_id:
                raise ProjectProvisioningIntegrityError("The managed project legacy alias is inconsistent.")

        profile = self.repository.get_profile(provisioning.context_id)
        if profile is None:
            raise ProjectProvisioningIntegrityError("The managed project profile is missing.")
        stored_plan = self.repository.get_plan_by_id(provisioning.project_plan_id)
        if stored_plan is not None and stored_plan[0] != provisioning.context_id:
            raise ProjectProvisioningIntegrityError("The managed project plan belongs to another context.")
        structured = self.repository.load_structured_memory(provisioning.context_id)
        if not isinstance(structured, dict):
            raise ProjectProvisioningIntegrityError("The managed project memory is missing.")
        workspace = structured.get("workspace")
        if not isinstance(workspace, dict):
            raise ProjectProvisioningIntegrityError("The managed project memory is malformed.")
        self._verify_structured_value(workspace.get("project_memory"), provisioning.project_memory_id)
        self._verify_structured_value(workspace.get("project_training_state"), provisioning.project_training_id)
        self._verify_structured_value(workspace.get("project_agent_context"), provisioning.project_agent_context_id)
        self._verify_structured_value(workspace.get("project_provisioning"), provisioning.context_id, "contextId")

        session = self.repository.load_session(provisioning.agent_session_id)
        if not isinstance(session, dict):
            raise ProjectProvisioningIntegrityError("The managed project agent session is missing.")
        if (
            str(session.get("workspace_id") or "").strip() != provisioning.context_id
            or str(session.get("session_id") or "").strip() != provisioning.agent_session_id
        ):
            raise ProjectProvisioningIntegrityError("The managed project agent session is inconsistent.")
        latest_plan = self.repository.get_latest_plan(provisioning.context_id)
        if latest_plan is not None and provisioning.global_plan_id:
            link = self.repository.get_global_plan_project_link(
                provisioning.global_plan_id,
                provisioning.context_id,
                latest_plan.id,
            )
            if link is None:
                raise ProjectProvisioningIntegrityError("The managed project lost its global-plan link.")

    @staticmethod
    def _verify_structured_value(value: Any, expected_id: str, key: str = "id") -> None:
        if not isinstance(value, dict) or str(value.get(key) or "").strip() != expected_id:
            raise ProjectProvisioningIntegrityError("The managed project provisioning evidence is incomplete.")

    @staticmethod
    def _assert_same_project(provisioning: ProjectProvisioning, project_path: str) -> None:
        if _path_key(provisioning.project_path) != _path_key(project_path):
            raise ProjectProvisioningConflictError(
                "This context is already associated with a different managed project."
            )
