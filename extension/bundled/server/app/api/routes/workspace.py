from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ...llm.provider_service import ProviderService
from ...workspace.adoption_index import ProjectAdoptionJobRecord
from ...workspace.authority import PermissionLevel, WorkspaceAuthority
from ...workspace.classifier import (
    ProjectDiscovery,
    classify_heuristic,
    classify_with_llm,
    complete_project_adoption,
    discover_project,
    resolve_project_discovery,
)
from ...workspace.provisioning import (
    ProjectProvisioningConflictError,
    ProjectProvisioningIntegrityError,
)
from ..runtime import TrainerRuntime
from ._deps import RouterDeps

logger = logging.getLogger(__name__)


def build_workspace_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter(tags=["workspace"])

    current_workspace_id = deps.current_workspace_id
    effective_response_language = deps.effective_response_language
    persist_first_look_summary = deps.persist_first_look_summary
    provider_config_from_payload = deps.provider_config_from_payload
    provider_api_key_from_payload = deps.provider_api_key_from_payload
    normalize_trainer_root_path = deps.normalize_trainer_root_path


    @dataclass(frozen=True)
    class TrainerRootSelection:
        """The user-selected Trainer data container, separate from a code project."""

        root_id: str | None
        root_path: str | None

    project_discoveries: dict[str, tuple[str, ProjectDiscovery, TrainerRootSelection]] = {}
    project_discoveries_guard = Lock()

    def workspace_discovery_owner_id(payload: dict) -> str:
        workspace_id = str(payload.get("workspace_id") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        # Discovery ownership is an ephemeral client key.  Resolving an old
        # workspace alias here would change the key immediately after adoption
        # and make a repeated decision look like a different discovery owner.
        if workspace_id:
            return workspace_id
        if session_id:
            return current_workspace_id(session_id=session_id)
        return ""

    def workspace_admission_conflict(
        code: str,
        category: str,
        path_state: str,
        detail: str,
    ) -> HTTPException:
        return HTTPException(
            status_code=409,
            detail={
                "code": code,
                "category": category,
                "path_state": path_state,
                "message": detail,
            },
        )

    def trainer_root_selection_from_payload(
        payload: dict,
        workspace_id: str,
    ) -> TrainerRootSelection:
        """Resolve the data root without treating the project path as that root."""
        requested_root_id = str(payload.get("root_id") or payload.get("rootId") or "").strip() or None
        requested_root_path = str(payload.get("root_path") or payload.get("rootPath") or "").strip() or None
        if requested_root_id:
            stored_root = runtime.repository.get_trainer_root(requested_root_id)
            if stored_root is None:
                raise ProjectProvisioningConflictError("The selected Trainer workspace root is unavailable.")
            if requested_root_path:
                try:
                    normalized_requested_path = str(Path(requested_root_path).expanduser().resolve(strict=False))
                except (OSError, RuntimeError) as exc:
                    raise ProjectProvisioningConflictError(
                        "The selected Trainer workspace root cannot be normalized."
                    ) from exc
                if normalized_requested_path != str(Path(stored_root.root_path).resolve(strict=False)):
                    raise ProjectProvisioningConflictError(
                        "The selected Trainer workspace root ID does not match its path."
                    )
            return TrainerRootSelection(
                root_id=stored_root.root_id,
                root_path=normalize_trainer_root_path(stored_root.root_path),
            )
        if requested_root_path:
            normalized_path = normalize_trainer_root_path(requested_root_path)
            stored_root = runtime.repository.get_trainer_root_by_path(normalized_path)
            return TrainerRootSelection(
                root_id=stored_root.root_id if stored_root is not None else None,
                root_path=normalized_path,
            )

        # Compatibility for direct API users that configured a root before the
        # discovery request. This is never used as a project-path fallback by
        # provisioning itself, so a project cannot silently become its own root.
        legacy_root_path = runtime.resolve_workspace_path(workspace_id)
        if legacy_root_path:
            normalized_path = normalize_trainer_root_path(legacy_root_path)
            stored_root = runtime.repository.get_trainer_root_by_path(normalized_path)
            return TrainerRootSelection(
                root_id=stored_root.root_id if stored_root is not None else None,
                root_path=normalized_path,
            )
        return TrainerRootSelection(root_id=None, root_path=None)

    def project_discovery_authority(
        project_path: str,
        root_selection: TrainerRootSelection,
    ) -> WorkspaceAuthority | None:
        """Authorize reads from the selected project, not from Trainer's data root."""
        if not root_selection.root_path:
            return None
        try:
            return WorkspaceAuthority(
                root_path=project_path,
                initial_permission=PermissionLevel.INSPECT,
            )
        except (OSError, ValueError):
            return None

    def root_selections_match(left: TrainerRootSelection, right: TrainerRootSelection) -> bool:
        return left.root_id == right.root_id and left.root_path == right.root_path

    def project_adoption_job_response(
        job: ProjectAdoptionJobRecord,
        discovery: ProjectDiscovery | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {"project_adoption_job": job.to_payload()}
        result = job.result
        if isinstance(result, dict):
            payload.update(result)
        elif discovery is not None:
            payload["project_discovery"] = discovery.to_payload()
        return payload

    @router.post("/workspace/classify", response_model=None)
    async def workspace_classify(payload: dict) -> dict[str, object]:
        workspace_id = workspace_discovery_owner_id(payload)
        requested_response_language = (
            str(payload.get("response_language") or payload.get("responseLanguage") or "").strip() or None
        )
        response_language = effective_response_language(workspace_id, requested_response_language)
        folder_path = str(
            payload.get("folder_path")
            or payload.get("project_path")
            or payload.get("workspace_path")
            or ""
        ).strip()
        if not folder_path and workspace_id:
            folder_path = runtime.resolve_workspace_path(workspace_id) or ""
        if not folder_path:
            raise HTTPException(status_code=400, detail="folder_path is required.")

        try:
            root_selection = trainer_root_selection_from_payload(payload, workspace_id)
        except ProjectProvisioningConflictError as exc:
            detail = str(exc)
            if "ID does not match" in detail:
                raise workspace_admission_conflict(
                    "root_id_mismatch", "workspace_root", "unknown", "The selected Trainer workspace root ID does not match its path."
                ) from exc
            if "unavailable" in detail or "available directory" in detail:
                raise workspace_admission_conflict(
                    "root_path_unavailable", "workspace_root", "unavailable", "The selected Trainer workspace root is unavailable."
                ) from exc
            raise workspace_admission_conflict(
                "root_missing", "workspace_root", "missing", "A Trainer workspace root is required."
            ) from exc

        # Register the explicitly selected Trainer data root before observing a
        # project. This does not adopt the project and never grants authority to
        # the candidate path; it only makes the root registry canonical.
        if root_selection.root_path:
            try:
                registered_root = runtime.register_trainer_root(
                    root_id=root_selection.root_id,
                    root_path=root_selection.root_path,
                )
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            root_selection = TrainerRootSelection(
                root_id=registered_root.root_id,
                root_path=registered_root.root_path,
            )
        snapshot = payload.get("workspace_file_snapshot") or payload.get("workspaceFileSnapshot")
        if not isinstance(snapshot, dict):
            snapshot = None
        remote_name = str(
            payload.get("remote_name") or payload.get("remoteName") or ""
        ).strip() or None
        summary = classify_heuristic(
            folder_path,
            response_language=response_language,
            workspace_file_snapshot=snapshot,
            remote_name=remote_name,
        )
        classification_service = runtime.provider_service
        override_config = provider_config_from_payload(payload)
        api_key_override = provider_api_key_from_payload(payload)
        if override_config is not None or api_key_override is not None:
            # Do not retain request-scoped credentials in the runtime service cache.
            classification_service = ProviderService(config=override_config, api_key=api_key_override)
        if (
            classification_service.has_api_key
            and runtime.provider_connection_verified(classification_service)
        ):
            summary = await classify_with_llm(
                folder_path,
                classification_service,
                heuristic_result=summary,
                response_language=response_language,
            )
        discovery = discover_project(
            folder_path,
            summary=summary,
            # Classification only observes the candidate. The project-specific
            # authority is created at the explicit decision boundary below.
            authority=None,
            remote_workspace=bool(
                remote_name
                or (isinstance(snapshot, dict) and snapshot.get("is_remote") is True)
                or "://" in folder_path
            ),
        )
        with project_discoveries_guard:
            project_discoveries[discovery.discovery_id] = (workspace_id, discovery, root_selection)

        response = summary.model_dump(mode="json")
        response["project_discovery"] = discovery.to_payload()
        if root_selection.root_path:
            response["root_identity"] = {
                "rootId": root_selection.root_id,
                "rootPath": root_selection.root_path,
            }
        return cast(dict[str, object], response)

    @router.post("/workspace/discovery/decision", response_model=None)
    def workspace_discovery_decision(payload: dict) -> dict[str, object]:
        workspace_id = workspace_discovery_owner_id(payload)
        context_id = str(payload.get("context_id") or payload.get("contextId") or "").strip() or None
        discovery_id = str(payload.get("discovery_id") or "").strip()
        decision = str(payload.get("decision") or "").strip().lower()
        if not discovery_id:
            raise HTTPException(status_code=400, detail="discovery_id is required.")
        if decision not in {"adopt", "browse", "ignore"}:
            raise HTTPException(status_code=422, detail="decision must be adopt, browse, or ignore.")

        with project_discoveries_guard:
            stored = project_discoveries.get(discovery_id)
        if stored is None or stored[0] != workspace_id:
            # Do not reveal a discovery record's path or ownership context.
            raise HTTPException(status_code=404, detail="Project discovery was not found.")

        _, discovery, stored_root_selection = stored
        has_explicit_root_selection = bool(
            str(payload.get("root_id") or payload.get("rootId") or "").strip()
            or str(payload.get("root_path") or payload.get("rootPath") or "").strip()
        )
        if has_explicit_root_selection:
            try:
                requested_root_selection = trainer_root_selection_from_payload(payload, workspace_id)
            except ProjectProvisioningConflictError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if not root_selections_match(stored_root_selection, requested_root_selection):
                raise HTTPException(
                    status_code=409,
                    detail="The selected Trainer workspace root changed after project discovery.",
                )
        root_selection = stored_root_selection
        if decision == "adopt" and discovery.status == "adopted":
            try:
                provisioning = runtime.get_project_provisioning(workspace_id)
            except ProjectProvisioningIntegrityError as exc:
                logger.error("Stored project provisioning evidence is incomplete: %s", type(exc).__name__)
                raise HTTPException(
                    status_code=409,
                    detail="The managed project needs repair before it can be resumed.",
                ) from exc
            if provisioning is None or provisioning.project_path != discovery.project_path:
                raise HTTPException(
                    status_code=409,
                    detail="The managed project record is unavailable for this discovery.",
                )
            persist_first_look_summary(provisioning.workspace_id, discovery.summary)
            return {
                "project_discovery": discovery.to_payload(),
                "project_provisioning": provisioning.model_dump(mode="json"),
                "project_identity": runtime.project_identity_payload(
                    provisioning,
                    idempotency="reused",
                ),
            }
        if decision == "adopt" and discovery.status == "adoption_requested" and discovery.adoption_job_id:
            if not root_selection.root_path:
                raise HTTPException(
                    status_code=409,
                    detail="The selected Trainer workspace root changed after project discovery.",
                )
            job = runtime.get_project_adoption_job(
                root_path=root_selection.root_path,
                job_id=discovery.adoption_job_id,
            )
            if job is None:
                raise HTTPException(
                    status_code=409,
                    detail="The project adoption job is no longer available and must be retried.",
                )
            return project_adoption_job_response(job, discovery)

        authority = project_discovery_authority(discovery.project_path, root_selection)
        try:
            resolved = resolve_project_discovery(
                discovery,
                decision,
                authority=authority,
            )
        except PermissionError as exc:
            logger.info("Workspace project discovery decision denied: %s", type(exc).__name__)
            raise HTTPException(
                status_code=403,
                detail="Choose a Trainer workspace root before opening this project.",
            ) from exc
        except ValueError as exc:
            message = str(exc).strip() or "The project discovery cannot be resolved in its current state."
            logger.info("Workspace project discovery decision could not be resolved: %s", type(exc).__name__)
            raise HTTPException(status_code=409, detail=message) from exc

        if decision != "adopt":
            with project_discoveries_guard:
                project_discoveries[discovery_id] = (workspace_id, resolved, root_selection)
            return {"project_discovery": resolved.to_payload()}

        if root_selection.root_path and Path(root_selection.root_path).resolve(strict=False) == Path(
            resolved.project_path
        ).resolve(strict=False):
            raise HTTPException(
                status_code=409,
                detail="This workspace is already associated with a different managed project.",
            )

        job_id = f"project-adoption-{uuid4().hex[:12]}"
        job_id_box: dict[str, str] = {"job_id": job_id}

        def finalize_adoption(inventory: dict[str, object]) -> dict[str, object]:
            existing = runtime.get_project_provisioning(context_id or workspace_id)
            provisioning = runtime.provision_project_adoption(
                workspace_id=workspace_id,
                context_id=context_id,
                root_id=root_selection.root_id,
                root_path=root_selection.root_path,
                project_path=resolved.project_path,
                project_name=resolved.project_name,
            )
            adopted = complete_project_adoption(
                replace(resolved, adoption_job_id=job_id_box.get("job_id")),
                provisioning.adoption_artifacts(),
            )
            persist_first_look_summary(provisioning.workspace_id, adopted.summary)
            with project_discoveries_guard:
                project_discoveries[discovery_id] = (workspace_id, adopted, root_selection)
            return {
                "project_discovery": adopted.to_payload(),
                "project_provisioning": provisioning.model_dump(mode="json"),
                "project_identity": runtime.project_identity_payload(
                    provisioning,
                    idempotency=(
                        "reused"
                        if existing is not None and existing.project_path == provisioning.project_path
                        else "created"
                    ),
                ),
                "project_adoption_inventory": inventory,
            }

        try:
            job = runtime.start_project_adoption_job(
                workspace_id=workspace_id,
                discovery_id=discovery_id,
                job_id=job_id,
                project_path=resolved.project_path,
                project_name=resolved.project_name,
                root_id=root_selection.root_id,
                root_path=root_selection.root_path or "",
                context_id=context_id,
                finalize=finalize_adoption,
            )
            requested = replace(resolved, adoption_job_id=job.job_id)
            with project_discoveries_guard:
                project_discoveries[discovery_id] = (workspace_id, requested, root_selection)
        except ProjectProvisioningConflictError as exc:
            logger.info("Workspace project provisioning conflict: %s", type(exc).__name__)
            raise HTTPException(
                status_code=409,
                detail="This workspace is already associated with a different managed project.",
            ) from exc
        except ProjectProvisioningIntegrityError as exc:
            logger.error("Workspace project provisioning integrity failure: %s", type(exc).__name__)
            raise HTTPException(
                status_code=409,
                detail="Project provisioning could not establish a complete recoverable project lane.",
            ) from exc

        return {
            "project_discovery": requested.to_payload(),
            "project_adoption_job": job.to_payload(),
        }

    @router.get("/workspace/adoption-job", response_model=None)
    def workspace_adoption_job(
        job_id: str | None = None,
        root_path: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, object]:
        if not job_id:
            raise HTTPException(status_code=400, detail="job_id is required.")
        if not root_path:
            raise HTTPException(status_code=400, detail="root_path is required.")
        job = runtime.get_project_adoption_job(root_path=root_path, job_id=job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Project adoption job was not found.")
        if workspace_id is not None and str(workspace_id).strip() and job.workspace_id != workspace_id.strip():
            raise HTTPException(status_code=404, detail="Project adoption job was not found.")
        response = project_adoption_job_response(job)
        if job.status == "completed" and job.context_id:
            try:
                provisioning = runtime.get_project_provisioning(job.context_id)
            except ProjectProvisioningIntegrityError as exc:
                logger.error("Project adoption job recovered incomplete provisioning: %s", type(exc).__name__)
                raise HTTPException(
                    status_code=409,
                    detail="The managed project needs repair before it can be resumed.",
                ) from exc
            if provisioning is not None:
                response.setdefault("project_provisioning", provisioning.model_dump(mode="json"))
                response.setdefault(
                    "project_identity",
                    runtime.project_identity_payload(provisioning, idempotency="existing"),
                )
        return response

    @router.get("/workspace/project-provisioning", response_model=None)
    def workspace_project_provisioning(
        workspace_id: str | None = None,
        context_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        if not (workspace_id or context_id or session_id):
            raise HTTPException(status_code=400, detail="workspace_id, context_id, or session_id is required.")
        resolved_workspace_id = current_workspace_id(
            session_id=session_id,
            workspace_id=context_id or workspace_id,
        )
        try:
            provisioning = runtime.get_project_provisioning(resolved_workspace_id)
        except ProjectProvisioningIntegrityError as exc:
            logger.error("Project provisioning lookup found incomplete evidence: %s", type(exc).__name__)
            raise HTTPException(
                status_code=409,
                detail="The managed project needs repair before it can be resumed.",
            ) from exc
        if provisioning is None:
            raise HTTPException(status_code=404, detail="No managed project was found for this workspace.")
        return {
            "project_provisioning": provisioning.model_dump(mode="json"),
            "project_identity": runtime.project_identity_payload(provisioning, idempotency="existing"),
        }

    @router.get("/workspace/identity", response_model=None)
    def workspace_identity(
        workspace_id: str | None = None,
        context_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        if not (workspace_id or context_id or session_id):
            raise HTTPException(status_code=400, detail="workspace_id, context_id, or session_id is required.")
        resolved_workspace_id = current_workspace_id(
            session_id=session_id,
            workspace_id=context_id or workspace_id,
        )
        try:
            provisioning = runtime.get_project_provisioning(resolved_workspace_id)
        except ProjectProvisioningIntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="The managed project needs repair before it can be resumed.",
            ) from exc
        if provisioning is None:
            raise HTTPException(status_code=404, detail="No managed project identity was found.")
        return runtime.project_identity_payload(provisioning, idempotency="existing")

    @router.post("/workspace/roots/{root_id}/reconcile", response_model=None)
    def workspace_root_reconcile(root_id: str, payload: dict) -> dict[str, object]:
        root_path = str(payload.get("root_path") or payload.get("rootPath") or "").strip()
        if not root_path:
            raise HTTPException(status_code=400, detail="root_path is required.")
        try:
            root = runtime.reconcile_trainer_root(root_id, root_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trainer root was not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Trainer root cannot be reconciled.") from exc
        pending_project_ids: list[str] = []
        for project in runtime.repository.list_trainer_projects(root.root_id):
            try:
                Path(project.project_path).relative_to(Path(root.root_path))
            except ValueError:
                pending_project_ids.append(project.project_id)
        pending = bool(pending_project_ids)
        return {
            "root": root.model_dump(mode="json"),
            "root_identity": {
                "rootId": root.root_id,
                "rootPath": root.root_path,
                "revisions": {"root": root.revision},
                "pending": pending,
                "reconcile": {
                    "state": "pending_projects" if pending else "reconciled",
                    "pendingProjectIds": pending_project_ids,
                },
            },
        }

    @router.post("/workspace/projects/{project_id}/reconcile", response_model=None)
    def workspace_project_reconcile(project_id: str, payload: dict) -> dict[str, object]:
        root_id = str(payload.get("root_id") or payload.get("rootId") or "").strip()
        project_path = str(payload.get("project_path") or payload.get("projectPath") or "").strip()
        project_name = str(payload.get("project_name") or payload.get("projectName") or "").strip() or None
        if not root_id or not project_path:
            raise HTTPException(status_code=400, detail="root_id and project_path are required.")
        try:
            project = runtime.reconcile_project_location(
                root_id=root_id,
                project_id=project_id,
                project_path=project_path,
                project_name=project_name,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trainer root or project was not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Project location cannot be reconciled.") from exc
        context = runtime.repository.get_project_context_for_project(project.project_id)
        if context is None:
            raise HTTPException(status_code=409, detail="Project context is incomplete.")
        try:
            provisioning = runtime.get_project_provisioning(context.context_id)
        except ProjectProvisioningIntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="The managed project needs repair before it can be resumed.",
            ) from exc
        if provisioning is None:
            raise HTTPException(status_code=409, detail="Project context cannot be loaded.")
        return {
            "project": project.model_dump(mode="json"),
            "project_identity": runtime.project_identity_payload(
                provisioning,
                idempotency="reconciled",
                reconcile_state="reconciled",
            ),
        }

    return router
