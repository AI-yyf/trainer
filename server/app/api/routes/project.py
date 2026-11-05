"""P2 project import routes: GitHub clone → Source registration → symbol index.

Cloned repositories live under the workspace's managed sandbox lane
(``data_root/sandboxes/<workspace>/projects``) so the existing source-governance
lane accepts them, and the deterministic symbol-index artifact lands under
``data_root/project-artifacts`` — durable managed storage, never the user's
workspace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ..runtime import TrainerRuntime
from ._deps import RouterDeps


def build_project_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter()
    _ = deps  # reserved for auth/deps parity with other routers

    def data_root() -> Any:
        return runtime.resource_service.data_root

    def _sandbox_slug(workspace_id: str) -> str:
        safe = runtime.resource_service._safe_slug(workspace_id) or "workspace"
        return safe

    def projects_root(workspace_id: str) -> Any:
        return (
            data_root()
            / "sandboxes"
            / _sandbox_slug(workspace_id)
            / "projects"
        )

    def artifact_root() -> Any:
        return data_root() / "project-artifacts"

    def register_source(workspace_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from ...core.models import ResourceUploadRequest

        # The cloned repo lives inside Trainer's managed sandbox lane, so it
        # becomes its own containment root for this registration — the same
        # contract as sandbox-file imports, never the user's workspace.
        upload = runtime.resource_service.upload(
            workspace_id,
            ResourceUploadRequest(**body),
            workspace_path=str(projects_root(workspace_id)),
        )
        return upload.model_dump(mode="json", by_alias=True)

    def _run_import(payload: dict[str, Any], repo_url: str) -> dict[str, Any]:
        from ...project.importer import import_repository

        workspace_id = str(payload.get("workspace_id") or "").strip()
        if not workspace_id:
            raise HTTPException(status_code=400, detail="workspace_id is required.")
        local_path = str(payload.get("path") or "").strip()
        url = str(payload.get("url") or payload.get("repo_url") or "").strip()
        if repo_url and not url:
            raise HTTPException(status_code=400, detail="url is required.")
        if not repo_url and not local_path:
            raise HTTPException(status_code=400, detail="path is required.")
        try:
            result = import_repository(
                repo_url=repo_url,
                repo_root=local_path,
                clone_root=projects_root(workspace_id),
                artifact_root=artifact_root(),
                register_source=lambda body: register_source(workspace_id, body),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        # P2 contract: an imported project is searchable immediately — the
        # follow-up question must work without a second call.
        index_status = "not_indexed"
        if result.resource_id:
            from ...core.models import ResourceIndexRequest

            try:
                indexed = runtime.resource_service.index(
                    workspace_id,
                    ResourceIndexRequest(
                        session_id=payload.get("session_id"),
                        workspace_id=workspace_id,
                        resource_id=result.resource_id,
                    ),
                )
                index_status = indexed.index_status
            except (KeyError, ValueError, PermissionError, RuntimeError):
                index_status = "failed"

        return {
            "ok": True,
            "resource_id": result.resource_id,
            "resource_name": result.resource_name,
            "repo_root": str(result.repo_root),
            "commit_sha": result.commit_sha,
            "branch": result.branch,
            "file_count": result.file_count,
            "symbol_count": result.symbol_count,
            "symbol_artifact_path": (
                result.symbol_artifact_path.as_posix()
                if result.symbol_artifact_path
                else None
            ),
            "index_status": index_status,
            "warnings": result.warnings,
        }

    @router.post("/project/import/github")
    def project_import_github(payload: dict) -> dict[str, object]:
        return _run_import(payload, repo_url=str(payload.get("url") or "").strip())

    @router.post("/project/import/local")
    def project_import_local(payload: dict) -> dict[str, object]:
        return _run_import(payload, repo_url="")

    def _resolve_project_repo_root(
        workspace_id: str, payload: dict[str, Any]
    ) -> Any:
        """Locate an imported repo root from resource_id (preferred) or path.

        Governance: a bare ``path`` is only honored inside the workspace's
        managed sandbox lane — never an arbitrary user directory.
        """

        resource_id = str(payload.get("resource_id") or "").strip()
        if resource_id:
            repository = getattr(runtime.resource_service, "repository", None)
            resource = None
            if repository is not None:
                for item in repository.list_resources(workspace_id):
                    if str(getattr(item, "id", "")) == resource_id:
                        resource = item
                        break
            if resource is None:
                raise HTTPException(status_code=404, detail="Project resource not found in this workspace.")
            source = str(getattr(resource, "source", "") or "").strip()
            if not source:
                raise HTTPException(status_code=422, detail="Project resource has no source path.")
            return Path(source)
        local_path = str(payload.get("path") or "").strip()
        if not local_path:
            raise HTTPException(status_code=400, detail="resource_id or path is required.")
        root = Path(local_path)
        lane = projects_root(workspace_id).resolve(strict=False)
        try:
            root.resolve(strict=False).relative_to(lane)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=403,
                detail="Overview for a bare path is only available inside Trainer's managed project lane.",
            ) from exc
        return root

    @router.post("/project/overview")
    def project_overview(payload: dict) -> dict[str, object]:
        """项目概览 Artifact (架构图/模块依赖图) — deterministic, Git-SHA-pinned."""

        from ...project.overview import (
            build_project_overview,
            evidence_git_snapshot,
            write_overview_artifact,
        )
        from ...project.symbols import build_repo_index

        workspace_id = str(payload.get("workspace_id") or "").strip()
        if not workspace_id:
            raise HTTPException(status_code=400, detail="workspace_id is required.")
        repo_root = _resolve_project_repo_root(workspace_id, payload)
        if not repo_root.is_dir():
            raise HTTPException(status_code=422, detail=f"Project directory is missing: {repo_root}")

        resource_id = str(payload.get("resource_id") or "").strip()
        repo_index = build_repo_index(repo_root)
        snapshot = evidence_git_snapshot(repo_root)
        commit_sha = str(snapshot.get("commit_sha") or "")
        overview = build_project_overview(
            repo_root,
            repo_index,
            repo_url=str(payload.get("repo_url") or ""),
            commit_sha=commit_sha,
            branch=str(snapshot.get("branch") or ""),
        )
        artifact_name = resource_id or repo_root.name
        artifact_path = write_overview_artifact(
            artifact_root() / f"{artifact_name}.overview.md",
            overview,
        )
        return {
            "ok": True,
            "resource_id": resource_id or None,
            "repo_root": str(repo_root),
            "commit_sha": commit_sha,
            "branch": snapshot.get("branch") or "",
            "dirty": snapshot.get("dirty", False),
            "artifact_path": artifact_path.as_posix(),
            "file_count": overview.file_count,
            "symbol_count": overview.symbol_count,
            "module_count": len(overview.modules),
            "edge_count": len(overview.edges),
            "module_edges": overview.module_edges[:20],
            "entry_points": overview.entry_points,
            "hotspot_modules": overview.hotspot_modules,
            "modules": overview.modules[:40],
        }

    @router.get("/project/overview/{resource_id}")
    def project_overview_read(resource_id: str, workspace_id: str) -> dict[str, object]:
        """Return the stored overview artifact content (no regeneration)."""

        artifact_path = artifact_root() / f"{resource_id}.overview.md"
        if not artifact_path.is_file():
            raise HTTPException(status_code=404, detail="No overview artifact for that resource.")
        return {
            "ok": True,
            "resource_id": resource_id,
            "artifact_path": artifact_path.as_posix(),
            "content": artifact_path.read_text(encoding="utf-8"),
        }

    @router.get("/project/import/status")
    def project_import_status() -> dict[str, object]:
        return {
            "projects_root": str(projects_root("workspace")),
            "artifact_root": str(artifact_root()),
            "cost_ledger": runtime.cost_ledger is not None,
        }

    return router
