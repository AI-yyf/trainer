from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from ...core.models import (
    ResourceRecord,
    SandboxDeleteRequest,
    SandboxMkdirRequest,
    SandboxPreview,
    SandboxPreviewRequest,
    SandboxRenamePathRequest,
    SandboxRenameRequest,
    SandboxRestoreRequest,
    SandboxState,
    SandboxWriteRequest,
)
from ..runtime import TrainerRuntime
from ._deps import RouterDeps


def build_sandbox_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter(tags=["sandbox"])

    current_workspace_id = deps.current_workspace_id
    require_sandbox_service = deps.require_sandbox_service
    apply_host_workspace_trust_attestation = deps.apply_host_workspace_trust_attestation
    workspace_learning_project_state = deps.workspace_learning_project_state
    sync_resource_record_to_sandbox = deps.sync_resource_record_to_sandbox

    def synced_workspace_resources(workspace_id: str) -> list[ResourceRecord]:
        resources = runtime.repository.list_resources(workspace_id)
        if runtime.sandbox_service is None:
            return resources
        synced_resources = [sync_resource_record_to_sandbox(workspace_id, resource) for resource in resources]
        return synced_resources


    @router.get("/workspace/authority", response_model=None)
    def workspace_authority(
        session_id: str | None = None,
        workspace_id: str | None = None,
        workspace_trusted: bool | None = None,
        remote_name: str | None = None,
        trusted: bool | None = None,
        remoteName: str | None = None,
    ) -> dict[str, object]:
        resolved_workspace_id = current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        # Host-attested trust on authority refresh so capability is not stuck fail-closed/unknown.
        host_trusted = workspace_trusted if workspace_trusted is not None else trusted
        host_remote = remote_name if remote_name is not None else remoteName
        if host_trusted is not None or host_remote is not None:
            trust_patch: dict[str, object] = {}
            if host_remote is not None:
                remote_value = str(host_remote or "").strip()
                trust_patch["remote_name"] = remote_value
                trust_patch["is_remote_workspace"] = bool(remote_value)
            if host_trusted is not None:
                trust_patch["workspace_trusted"] = bool(host_trusted)
            runtime.memory_service.update_workspace_state(resolved_workspace_id, **trust_patch)
            runtime.workspace_authority(resolved_workspace_id)
        sandbox_service = require_sandbox_service()
        sandbox_authority = sandbox_service.authority_summary(resolved_workspace_id)
        project_authority = runtime.workspace_authority(resolved_workspace_id)
        authority = dict(sandbox_authority)
        authority["project_authority"] = (
            project_authority.summary() if project_authority is not None else None
        )
        authority["sandbox_authority"] = sandbox_authority
        authority["authority_scope"] = "trainer_sandbox"
        return {
            "workspace_id": resolved_workspace_id,
            "authority": authority,
            **authority,
        }

    @router.get("/sandbox/state", response_model=SandboxState)
    def sandbox_state(
        session_id: str | None = None,
        workspace_id: str | None = None,
        selected_path: str | None = None,
        preview_path: str | None = None,
        workspace_trusted: bool | None = None,
        remote_name: str | None = None,
        trusted: bool | None = None,
        remoteName: str | None = None,
    ) -> SandboxState:
        resolved_workspace_id = current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        # Host-attested trust on live list_state so capability summary is not stuck unknown.
        host_trusted = workspace_trusted if workspace_trusted is not None else trusted
        host_remote = remote_name if remote_name is not None else remoteName
        if host_trusted is not None or host_remote is not None:
            trust_patch: dict[str, object] = {}
            if host_remote is not None:
                remote_value = str(host_remote or "").strip()
                trust_patch["remote_name"] = remote_value
                trust_patch["is_remote_workspace"] = bool(remote_value)
            if host_trusted is not None:
                trust_patch["workspace_trusted"] = bool(host_trusted)
            runtime.memory_service.update_workspace_state(resolved_workspace_id, **trust_patch)
            # Refresh in-memory authority from the just-written host attestation.
            runtime.workspace_authority(resolved_workspace_id)
        sandbox_service = require_sandbox_service()
        resources = synced_workspace_resources(resolved_workspace_id)
        return sandbox_service.list_state(
            resolved_workspace_id,
            resources,
            selected_path=selected_path,
            preview_path=preview_path,
            workspace_root_path=runtime.resolve_workspace_path(resolved_workspace_id),
        )

    @router.post("/sandbox/root", response_model=SandboxState)
    def sandbox_root(payload: dict) -> SandboxState:
        resolved_workspace_id = current_workspace_id(
            session_id=str(payload.get("session_id") or "").strip() or None,
            workspace_id=str(payload.get("workspace_id") or "").strip() or None,
        )
        # Host-attested trust before destructive root switch and list_state capability summary.
        apply_host_workspace_trust_attestation(resolved_workspace_id, payload)
        sandbox_service = require_sandbox_service()
        clear = bool(payload.get("clear"))
        requested_root = str(
            payload.get("root_path")
            or payload.get("sandbox_root_path")
            or payload.get("path")
            or ""
        ).strip()
        current_project_state = workspace_learning_project_state(resolved_workspace_id)
        if clear or not requested_root:
            runtime.register_workspace_sandbox_root(resolved_workspace_id, None)
            runtime.memory_service.update_workspace_state(
                resolved_workspace_id,
                sandbox_root_override="",
            )
        else:
            candidate = Path(requested_root).expanduser()
            if candidate.exists() and not candidate.is_dir():
                raise HTTPException(status_code=422, detail="Sandbox root must be a directory path.")
            try:
                resolved_root = str(
                    sandbox_service.validate_workspace_sandbox_root(
                        resolved_workspace_id,
                        candidate,
                    )
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            Path(resolved_root).mkdir(parents=True, exist_ok=True)
            runtime.register_workspace_sandbox_root(resolved_workspace_id, resolved_root)
            runtime.memory_service.update_workspace_state(
                resolved_workspace_id,
                sandbox_root_override=resolved_root,
                learning_project_prompt_status=current_project_state.get("prompt_status") or "linked",
                learning_project_folder_name=Path(resolved_root).name,
                learning_project_source_path=(
                    current_project_state.get("source_path")
                    or str(runtime.resolve_workspace_path(resolved_workspace_id) or "")
                ),
            )
        resources = synced_workspace_resources(resolved_workspace_id)
        return sandbox_service.list_state(
            resolved_workspace_id,
            resources,
            workspace_root_path=runtime.resolve_workspace_path(resolved_workspace_id),
        )

    @router.post("/sandbox/preview", response_model=SandboxPreview)
    def sandbox_preview(payload: dict) -> SandboxPreview:
        request = SandboxPreviewRequest.model_validate(payload)
        workspace_id = current_workspace_id(workspace_id=request.workspace_id)
        # Host-attested trust before preview (typed models would otherwise strip it).
        apply_host_workspace_trust_attestation(workspace_id, payload)
        sandbox_service = require_sandbox_service()
        try:
            return sandbox_service.preview(workspace_id, request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Sandbox path was not found.") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Sandbox preview permission was denied.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/sandbox/mkdir", response_model=SandboxState)
    def sandbox_mkdir(payload: dict) -> SandboxState:
        request = SandboxMkdirRequest.model_validate(payload)
        workspace_id = current_workspace_id(workspace_id=request.workspace_id)
        # Host-attested trust before mkdir and list_state capability summary.
        apply_host_workspace_trust_attestation(workspace_id, payload)
        sandbox_service = require_sandbox_service()
        resources = synced_workspace_resources(workspace_id)
        return sandbox_service.mkdir(
            workspace_id,
            request,
            resources=resources,
            workspace_root_path=runtime.resolve_workspace_path(workspace_id),
        )

    @router.post("/sandbox/write", response_model=SandboxPreview)
    def sandbox_write(payload: dict) -> SandboxPreview:
        request = SandboxWriteRequest.model_validate(payload)
        workspace_id = current_workspace_id(workspace_id=request.workspace_id)
        # Host-attested trust before write (typed models would otherwise strip it).
        apply_host_workspace_trust_attestation(workspace_id, payload)
        sandbox_service = require_sandbox_service()
        try:
            return sandbox_service.write(workspace_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.post("/sandbox/rename", response_model=SandboxPreview)
    def sandbox_rename(payload: dict) -> SandboxPreview:
        request = SandboxRenamePathRequest.model_validate(payload)
        workspace_id = current_workspace_id(workspace_id=request.workspace_id)
        apply_host_workspace_trust_attestation(workspace_id, payload)
        sandbox_service = require_sandbox_service()
        return sandbox_service.rename(
            workspace_id,
            SandboxRenameRequest(
                path=request.path,
                new_path=request.new_path,
                explicitDestructivePolicy=bool(
                    getattr(request, "explicit_destructive_policy", False)
                ),
            ),
        )

    @router.post("/sandbox/delete", response_model=SandboxState)
    def sandbox_delete(payload: dict) -> SandboxState:
        request = SandboxDeleteRequest.model_validate(payload)
        workspace_id = current_workspace_id(workspace_id=request.workspace_id)
        apply_host_workspace_trust_attestation(workspace_id, payload)
        sandbox_service = require_sandbox_service()
        resources = synced_workspace_resources(workspace_id)
        return sandbox_service.delete(
            workspace_id,
            request,
            resources=resources,
            workspace_root_path=runtime.resolve_workspace_path(workspace_id),
        )

    @router.post("/sandbox/restore", response_model=SandboxState)
    def sandbox_restore(payload: dict) -> SandboxState:
        request = SandboxRestoreRequest.model_validate(payload)
        workspace_id = current_workspace_id(workspace_id=request.workspace_id)
        apply_host_workspace_trust_attestation(workspace_id, payload)
        sandbox_service = require_sandbox_service()
        resources = synced_workspace_resources(workspace_id)
        return sandbox_service.restore(
            workspace_id,
            request,
            resources=resources,
            workspace_root_path=runtime.resolve_workspace_path(workspace_id),
        )
    return router
