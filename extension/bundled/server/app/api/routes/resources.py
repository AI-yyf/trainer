from __future__ import annotations

import logging
import re
from typing import cast
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ...browser_bridge import BrowserBridgeService, BrowserCredential
from ...core.models import (
    LibraryAsset,
    LibraryAssetLifecycleRequest,
    LibraryAssetLinkRequest,
    LibraryAssetUpsertRequest,
    LibraryGroupNode,
    LibraryGroupsResponse,
    ResourceCaptureRequest,
    ResourceCaptureResponse,
    ResourceDeleteRequest,
    ResourceIndexRequest,
    ResourceOrganizeRequest,
    ResourceRecord,
    ResourceRestoreRequest,
    ResourceSearchRequest,
    ResourceTrashResponse,
    ResourceUploadRequest,
)
from ...resources.asset_library import (
    AssetApprovalRequired,
    AssetLibraryError,
    AssetLibraryService,
)
from ...resources.capture import (
    CapturedSource,
    CaptureError,
    capture_source,
    capture_url_key,
)
from ...resources.library import (
    LibraryDownload,
    LibraryError,
    LibraryService,
)
from ...resources.library_copy import library_message
from ...resources.library_downloads import ArtifactNote
from ...workspace.authority import PermissionLevel, WorkspaceAuthority
from ..runtime import TrainerRuntime
from ._deps import RouterDeps

logger = logging.getLogger(__name__)

# The deep link the capture lane hands back to the browser extension. The host
# registers this URI handler (extension/src/browserCapture/deepLink.ts) and
# focuses the resource in the workbench.
DEEP_LINK_PREFIX = "vscode://local.trainer-extension/library/"


def capture_deep_link(resource_id: str) -> str:
    return f"{DEEP_LINK_PREFIX}{quote(str(resource_id or '').strip(), safe='')}"


def build_resources_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter(tags=["resources"])

    current_workspace_id = deps.current_workspace_id
    refresh_workspace_sessions = deps.refresh_workspace_sessions
    routing_learner_state = deps.routing_learner_state
    effective_response_language = deps.effective_response_language

    asset_library = AssetLibraryService(runtime.repository)

    library = LibraryService(
        runtime.repository,
        workspace_authority_resolver=runtime.workspace_authority,
    )

    def library_language(workspace_id: str, text: str | None = None) -> str | None:
        """The workspace's effective response language for library copy."""

        language = effective_response_language(workspace_id, None, text)
        return str(language) if language else None

    def library_detail(exc: LibraryError, language: str | None) -> dict[str, str]:
        return exc.as_detail(language)

    def download_warning(note: ArtifactNote, language: str | None) -> str:
        """Stable ``download:<code>`` marker plus the localized explanation."""

        return f"download:{note.code}: {library_message(note.code, language, **note.params)}"

    def require_asset_context_authority(context_id: str | None) -> str | None:
        """Resolve only registered project contexts before mutating asset metadata."""

        normalized_context_id = str(context_id or "").strip()
        if not normalized_context_id:
            return None
        context = runtime.repository.get_project_context(normalized_context_id)
        if context is None:
            raise HTTPException(status_code=404, detail="Unknown project context.")
        root = runtime.repository.get_trainer_root(context.root_id)
        if root is None:
            raise HTTPException(status_code=409, detail="Project context has no registered Trainer root.")
        try:
            authority = WorkspaceAuthority(
                root_path=root.root_path,
                initial_permission=PermissionLevel.INSPECT,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail="Project context root is not available for asset operations.",
            ) from exc
        if not authority.can_perform("list", root.root_path):
            raise HTTPException(status_code=403, detail="Project context is not available for asset inspection.")
        return context.context_id

    def resolve_asset_context_identity(
        project_id: str | None,
        context_id: str | None,
    ) -> tuple[str | None, str | None]:
        normalized_project_id = str(project_id or "").strip() or None
        normalized_context_id = str(context_id or "").strip() or None
        if normalized_context_id:
            canonical_context_id = require_asset_context_authority(normalized_context_id)
            assert canonical_context_id is not None
            context = runtime.repository.get_project_context(canonical_context_id)
            assert context is not None
            if normalized_project_id and context.project_id != normalized_project_id:
                raise HTTPException(status_code=422, detail="projectId does not match contextId.")
            return context.project_id, context.context_id
        if normalized_project_id:
            context = runtime.repository.get_project_context_for_project(normalized_project_id)
            if context is None:
                raise HTTPException(status_code=404, detail="Unknown project.")
            require_asset_context_authority(context.context_id)
            return context.project_id, context.context_id
        return None, None

    def asset_response(asset: LibraryAsset) -> dict[str, object]:
        payload = cast(dict[str, object], asset.model_dump(by_alias=True, mode="json"))
        payload["capabilities"] = asset_library.capabilities(asset)
        payload["sourceState"] = asset_library.source_state(asset)
        return payload


    def serialize_resource_search_response(
        workspace_id: str,
        response: object,
    ) -> dict[str, object]:
        results = list(getattr(response, "results", []) or [])
        filters = getattr(response, "filters", None)
        return {
            "workspace_id": workspace_id,
            "query": str(getattr(response, "query", "") or ""),
            "total": int(getattr(response, "total", len(results)) or 0),
            "ranking_strategy": str(getattr(response, "ranking_strategy", "lexical_first") or "lexical_first"),
            "filters": {
                "project_scope": str(getattr(filters, "project_scope", "") or ""),
                "trust_state": str(getattr(filters, "trust_state", "") or ""),
                "file_type": str(getattr(filters, "file_type", "") or ""),
                "source_type": str(getattr(filters, "source_type", "") or ""),
                "kind": str(getattr(filters, "kind", "") or ""),
                "index_state": str(getattr(filters, "index_state", "") or ""),
            },
            "hits": [
                {
                    "id": str(getattr(item, "resource_id", "") or ""),
                    "resource_id": str(getattr(item, "resource_id", "") or ""),
                    "title": str(getattr(item, "title", "") or ""),
                    "source": str(getattr(item, "source", "") or ""),
                    "source_type": str(getattr(item, "source_type", "") or ""),
                    "summary": str(getattr(item, "summary", "") or ""),
                    "trust_score": float(getattr(item, "trust_score", 0.0) or 0.0),
                    "trust_state": str(getattr(item, "trust_state", "") or ""),
                    "freshness": str(getattr(item, "freshness", "") or ""),
                    "file_type": str(getattr(item, "file_type", "") or ""),
                    "project_scope": str(getattr(item, "project_scope", "") or ""),
                    "kind": str(getattr(item, "kind", "") or ""),
                    "index_state": str(getattr(item, "index_state", "") or ""),
                    "citation_id": str(getattr(item, "citation_id", "") or ""),
                    "version_id": str(getattr(item, "version_id", "") or "") or None,
                    "content_hash": str(getattr(item, "content_hash", "") or "") or None,
                    "location": dict(getattr(item, "location", {}) or {}),
                    "can_inject_training_card": bool(getattr(item, "can_inject_training_card", False)),
                    "preview_tier": str(getattr(item, "preview_tier", "") or ""),
                    "preview_kind": str(getattr(item, "preview_kind", "") or ""),
                    "rank_score": float(getattr(item, "rank_score", 0.0) or 0.0),
                    "rank_reasons": list(getattr(item, "rank_reasons", []) or []),
                    "matched_fields": list(getattr(item, "matched_fields", []) or []),
                    "match_summary": str(getattr(item, "match_summary", "") or ""),
                    "updated_at": getattr(item, "updated_at", None),
                }
                for item in results
            ],
        }


    def refresh_asset_sessions(
        *assets: LibraryAsset | None,
        context_ids: tuple[str | None, ...] = (),
    ) -> None:
        affected_context_ids = {
            context_id.strip()
            for context_id in context_ids
            if context_id and context_id.strip()
        }
        for asset in assets:
            if asset is None:
                continue
            if asset.context_id:
                affected_context_ids.add(asset.context_id)
            affected_context_ids.update(
                link.context_id or link.workspace_id
                for link in asset_library.links(asset.id)
                if link.context_id or link.workspace_id
            )
            if asset.scope != "project":
                affected_context_ids.update(
                    state.workspace_id
                    for state in runtime.sessions.values()
                    if runtime.repository.get_project_context(state.workspace_id) is not None
                )
        for context_id in affected_context_ids:
            refresh_workspace_sessions(context_id)


    @router.post("/assets")
    def upsert_library_asset(request: LibraryAssetUpsertRequest) -> dict[str, object]:
        project_id, context_id = resolve_asset_context_identity(request.project_id, request.context_id)
        previous = None
        if request.asset_id:
            try:
                previous = asset_library.get(request.asset_id, include_deleted=True)
            except KeyError:
                pass
        try:
            asset = asset_library.upsert(
                request.model_copy(update={"project_id": project_id, "context_id": context_id})
            )
        except AssetApprovalRequired as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "approval_required", "operation": exc.operation},
            ) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AssetLibraryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        refresh_asset_sessions(asset, previous)
        return {"asset": asset_response(asset)}

    @router.get("/assets")
    def list_library_assets(
        query: str = "",
        scope: str | None = None,
        asset_type: str | None = None,
        project_id: str | None = None,
        context_id: str | None = None,
        include_deleted: bool = False,
        limit: int = 50,
    ) -> dict[str, object]:
        resolved_project_id, resolved_context_id = resolve_asset_context_identity(project_id, context_id)
        try:
            result = asset_library.list(
                query=query,
                scope=scope,
                asset_type=asset_type,
                project_id=resolved_project_id,
                context_id=resolved_context_id,
                include_deleted=include_deleted,
                limit=limit,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AssetLibraryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "items": [asset_response(asset) for asset in result.items],
            "total": result.total,
            "query": query,
        }

    @router.get("/assets/{asset_id}")
    def get_library_asset(
        asset_id: str,
        context_id: str | None = None,
        include_deleted: bool = False,
    ) -> dict[str, object]:
        resolved_context_id = require_asset_context_authority(context_id)
        try:
            return {"asset": asset_response(asset_library.get(
                asset_id,
                context_id=resolved_context_id,
                include_deleted=include_deleted,
            ))}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.post("/assets/{asset_id}/links")
    def link_library_asset(asset_id: str, request: LibraryAssetLinkRequest) -> dict[str, object]:
        project_id, context_id = resolve_asset_context_identity(request.project_id, request.context_id)
        assert context_id is not None
        try:
            asset = asset_library.get(asset_id, include_deleted=True)
            link = asset_library.link(
                asset_id,
                request.model_copy(update={"project_id": project_id, "context_id": context_id}),
            )
        except AssetApprovalRequired as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "approval_required", "operation": exc.operation},
            ) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (AssetLibraryError, PermissionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        refresh_asset_sessions(asset, context_ids=(link.context_id,))
        return {"link": link.model_dump(by_alias=True, mode="json")}

    @router.get("/assets/{asset_id}/links")
    def list_library_asset_links(asset_id: str, context_id: str | None = None) -> dict[str, object]:
        resolved_context_id = require_asset_context_authority(context_id)
        try:
            links = asset_library.links(asset_id, context_id=resolved_context_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"items": [link.model_dump(by_alias=True, mode="json") for link in links]}

    @router.post("/assets/{asset_id}/archive")
    def archive_library_asset(
        asset_id: str,
        request: LibraryAssetLifecycleRequest,
    ) -> dict[str, object]:
        try:
            existing = asset_library.get(asset_id, include_deleted=True)
            require_asset_context_authority(existing.context_id)
            asset = asset_library.archive(asset_id, request)
        except AssetApprovalRequired as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "approval_required", "operation": exc.operation},
            ) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AssetLibraryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        refresh_asset_sessions(asset)
        return {"asset": asset_response(asset)}

    @router.post("/assets/{asset_id}/restore")
    def restore_library_asset(
        asset_id: str,
        request: LibraryAssetLifecycleRequest,
    ) -> dict[str, object]:
        try:
            existing = asset_library.get(asset_id, include_deleted=True)
            require_asset_context_authority(existing.context_id)
            asset = asset_library.restore(asset_id, request)
        except AssetApprovalRequired as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "approval_required", "operation": exc.operation},
            ) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AssetLibraryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        refresh_asset_sessions(asset)
        return {"asset": asset_response(asset)}

    @router.post("/resource/upload", response_model=ResourceRecord)
    def resource_upload(request: ResourceUploadRequest) -> ResourceRecord:
        workspace_id = current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        try:
            record = runtime.resource_service.upload(workspace_id, request)
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail="Resource source is outside an authorized workspace or collection.",
            ) from exc
        except (FileNotFoundError, IsADirectoryError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return record

    @router.post("/resource/index", response_model=ResourceRecord)
    def resource_index(request: ResourceIndexRequest) -> ResourceRecord:
        workspace_id = current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        try:
            indexed = runtime.resource_service.index(workspace_id, request)
            indexed, _ = runtime.postprocess_indexed_resource(workspace_id, indexed)
            attempt_store = getattr(runtime, "attempt_store", None)
            version_store = getattr(runtime, "resource_version_store", None)
            if not indexed.quality_flags and attempt_store is not None and version_store is not None:
                content_hash = version_store.current_content_hash(workspace_id, request.resource_id)
                if content_hash:
                    attempt_store.clear_evidence_source_deleted(
                        workspace_id=workspace_id,
                        content_hash=content_hash,
                        resource_id=request.resource_id,
                    )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail="Resource source is outside an authorized workspace or collection.",
            ) from exc
        except (FileNotFoundError, IsADirectoryError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return indexed

    def browser_bridge_service() -> BrowserBridgeService | None:
        service = getattr(runtime, "browser_bridge", None)
        return service if isinstance(service, BrowserBridgeService) else None

    def browser_credential_from_request(http_request: Request) -> BrowserCredential | None:
        """Resolve the optional Bearer credential (pairing lane) for a request.

        A present-but-invalid credential is a 401 — it must never silently fall
        back to the session workspace, because the browser extension would then
        write into whatever workspace the host last opened. A missing header
        keeps the existing session-based path (webview/host callers).
        """

        header = str(http_request.headers.get("authorization") or "").strip()
        if not header:
            return None
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_credential", "message": "Authorization must be 'Bearer <credential>'."},
            )
        bridge = browser_bridge_service()
        credential = bridge.credential_for_token(token) if bridge is not None else None
        if credential is None:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "invalid_credential",
                    "message": "This browser credential is invalid or was revoked; pair again.",
                },
            )
        return credential

    def find_captured_resource(
        workspace_id: str,
        *,
        url_key: str,
        content_hash: str = "",
    ) -> ResourceRecord | None:
        """Locate an earlier capture of the same URL or identical content.

        URL identity rides the ``capture-key:`` tag (normalized, tracking-free);
        content identity reuses the Library's SHA-256 content-hash mechanism, so
        the same page captured from a different URL still dedupes.
        """

        wanted_hash = str(content_hash or "").strip()
        try:
            resources = runtime.repository.list_resources(workspace_id)
        except Exception:
            logger.warning("Capture dedup scan failed for workspace %s.", workspace_id, exc_info=True)
            return None
        for resource in resources:
            if url_key and url_key in resource.tags:
                return resource
        if wanted_hash:
            for resource in resources:
                if str(resource.content_hash or "").strip() == wanted_hash:
                    return resource
        return None

    def bind_capture_to_learning_focus(
        workspace_id: str,
        resource_id: str,
        focus_id: str,
    ) -> str:
        """Bind a captured resource to a plan stage (best-effort).

        Returns ``bound`` | ``already_bound`` | ``focus_not_found`` | ``no_plan``
        | ``write_failed``. An unknown focus never fails the capture itself —
        the extension only needs to know that the binding did not happen.
        """

        plan = runtime.repository.get_latest_plan(workspace_id)
        if plan is None:
            return "no_plan"
        stage = next((item for item in plan.stages if item.id == focus_id), None)
        if stage is None:
            return "focus_not_found"
        if resource_id in stage.resources:
            return "already_bound"
        stage.resources = [*stage.resources, resource_id]
        try:
            from ...training.plan_revision import save_plan_advancing_revision

            save_plan_advancing_revision(runtime.repository, workspace_id, plan)
        except Exception:
            logger.warning(
                "Capture focus binding failed for resource %s in workspace %s.",
                resource_id,
                workspace_id,
                exc_info=True,
            )
            return "write_failed"
        refresh_workspace_sessions(workspace_id)
        return "bound"

    def _capture_response(
        resource: ResourceRecord,
        *,
        deduped: bool,
        warnings: list[str] | None = None,
        focus_binding: str = "",
        saved_path: str | None = None,
    ) -> ResourceCaptureResponse:
        payload = resource.model_dump()
        if warnings:
            payload["warnings"] = list(
                dict.fromkeys([*list(resource.warnings or []), *warnings])
            )
        response = ResourceCaptureResponse.model_validate(payload)
        response.resource_id = resource.id
        response.deduped = deduped
        response.deep_link = capture_deep_link(resource.id)
        recorded_paths = [str(item) for item in (resource.library_paths or [])]
        response.saved_path = saved_path or (recorded_paths[-1] if recorded_paths else None)
        if focus_binding:
            response.warnings = list(
                dict.fromkeys([*response.warnings, f"focus_binding:{focus_binding}"])
            )
        return response

    def _replayed_capture(
        workspace_id: str,
        replay: dict[str, object],
    ) -> ResourceCaptureResponse | None:
        resource_id = str(replay.get("resource_id") or "").strip()
        if not resource_id:
            return None
        resource = runtime.repository.get_resource(workspace_id, resource_id)
        if resource is None:
            # The recorded resource was deleted since; the idempotency record
            # cannot answer for it, so the capture runs again.
            return None
        replayed_path = str(replay.get("saved_path") or "").strip() or None
        return _capture_response(resource, deduped=True, saved_path=replayed_path)

    @router.post("/resources/capture", response_model=ResourceCaptureResponse)
    def resource_capture(
        request: ResourceCaptureRequest,
        http_request: Request,
    ) -> ResourceCaptureResponse:
        """Browser-capture intake: URL → Trainer-owned, indexed library material.

        Pipeline: controlled fetch → cleaned body (trafilatura) → durable
        Markdown snapshot → metadata tags → FTS index via the regular upload/
        index chain. Duplicate captures answer with ``deduped=true`` and the
        existing resource id; ``client_capture_id`` makes retries idempotent.
        With ``download=true`` the original artifact (PDF bytes or the whole
        GitHub repository) is written into a real workspace folder first (see
        ``app.resources.library``).
        """

        credential = browser_credential_from_request(http_request)
        if credential is not None:
            workspace_id = credential.workspace_id
            requested_workspace = str(request.workspace_id or "").strip()
            if requested_workspace and requested_workspace != workspace_id:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "workspace_mismatch",
                        "message": "This credential is paired to a different workspace.",
                    },
                )
        else:
            workspace_id = current_workspace_id(
                session_id=request.session_id,
                workspace_id=request.workspace_id,
            )
        language = library_language(
            workspace_id,
            request.selection or request.title or request.url,
        )
        if request.download and request.kind not in {"pdf", "github_repo"}:
            # Refuse before any fetch: only artifact kinds can be downloaded.
            raise HTTPException(
                status_code=422,
                detail=LibraryError("download_kind_unsupported", status_code=422).as_detail(language),
            )
        network_enabled = bool(getattr(runtime.resource_service, "enable_network_fetch", False))

        bridge = browser_bridge_service()
        client_capture_id = str(request.client_capture_id or "").strip()
        if bridge is not None and client_capture_id:
            replay = _replayed_capture(workspace_id, bridge.capture_replay(client_capture_id) or {})
            if replay is not None:
                return replay

        def download_capture_artifact(
            *,
            kind: str,
            title: str,
            language: str | None,
            captured: CapturedSource | None,
            existing: ResourceRecord | None,
        ) -> tuple[LibraryDownload | None, list[str]]:
            """Save the captured source into a real library folder (task two).

            The download runs before the library write so a failed download leaves
            nothing half-registered behind; a deduped capture re-downloads from the
            owned snapshot instead of fetching the source twice.
            """

            if not request.download:
                return None, []
            try:
                download = library.save_download(
                    workspace_id,
                    kind=kind,
                    url=request.url,
                    title=title,
                    target_dir=request.target_dir,
                    network_enabled=network_enabled,
                    content_base64=(
                        captured.content
                        if captured is not None and kind == "pdf"
                        else None
                    ),
                    existing_resource=existing,
                )
            except LibraryError as exc:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail=library_detail(exc, language),
                ) from exc
            warnings = [download_warning(note, language) for note in download.notes]
            return download, warnings

        # Fast path: the requested URL is already captured in this library.
        requested_key = capture_url_key(request.url)
        if requested_key:
            existing = find_captured_resource(workspace_id, url_key=requested_key)
            if existing is not None:
                download, download_warnings = download_capture_artifact(
                    kind=request.kind,
                    title=existing.name,
                    language=language,
                    captured=None,
                    existing=existing,
                )
                existing = library.remember_download(workspace_id, existing, download) or existing
                if bridge is not None and client_capture_id:
                    bridge.remember_capture(
                        client_capture_id,
                        {
                            "resource_id": existing.id,
                            "recorded_at": existing.fetched_at or "",
                            "saved_path": download.relative_path if download else "",
                        },
                    )
                return _capture_response(
                    existing,
                    deduped=True,
                    warnings=download_warnings,
                    saved_path=download.relative_path if download else None,
                )

        try:
            captured = capture_source(
                request.kind,
                request.url,
                network_enabled=network_enabled,
                declared_title=request.title,
                selection=request.selection,
                include_docs=request.include_docs,
            )
        except CaptureError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc

        # Content identity: same bytes as an earlier capture → reuse it.
        canonical_key = capture_url_key(captured.capture_url or captured.source_url)
        duplicate = find_captured_resource(
            workspace_id,
            url_key=canonical_key,
            content_hash=captured.content_hash,
        )
        if duplicate is not None:
            download, download_warnings = download_capture_artifact(
                kind=request.kind,
                title=duplicate.name,
                language=language,
                captured=captured,
                existing=duplicate,
            )
            duplicate = library.remember_download(workspace_id, duplicate, download) or duplicate
            if bridge is not None and client_capture_id:
                bridge.remember_capture(
                    client_capture_id,
                    {
                        "resource_id": duplicate.id,
                        "recorded_at": duplicate.fetched_at or "",
                        "saved_path": download.relative_path if download else "",
                    },
                )
            return _capture_response(
                duplicate,
                deduped=True,
                warnings=[*list(captured.warnings), *download_warnings],
                saved_path=download.relative_path if download else None,
            )

        download, download_warnings = download_capture_artifact(
            kind=request.kind,
            title=captured.title,
            language=language,
            captured=captured,
            existing=None,
        )

        def rollback_download() -> None:
            """A capture that fails to register must not leave a stray artifact."""

            if download is None or not download.created:
                return
            try:
                target = library.resolve_workspace_path(workspace_id, download.relative_path)
            except LibraryError:
                return
            if target is None:
                return
            try:
                if target.is_dir():
                    import shutil

                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Downloaded artifact rollback failed for %s in workspace %s.",
                    target,
                    workspace_id,
                    exc_info=True,
                )

        try:
            record = runtime.resource_service.upload(
                workspace_id,
                captured.as_upload_request(
                    session_id=request.session_id,
                    workspace_id=workspace_id,
                ),
            )
        except PermissionError as exc:
            rollback_download()
            raise HTTPException(
                status_code=403,
                detail="Resource source is outside an authorized workspace or collection.",
            ) from exc
        except (FileNotFoundError, IsADirectoryError, ValueError) as exc:
            rollback_download()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            indexed = runtime.resource_service.index(
                workspace_id,
                ResourceIndexRequest(
                    session_id=request.session_id,
                    workspace_id=workspace_id,
                    resource_id=record.id,
                    # The capture already materialized the fetched content; the
                    # index pass must not fetch anything on its own.
                    enable_network=False,
                ),
            )
            indexed, _ = runtime.postprocess_indexed_resource(workspace_id, indexed)
        except (
            KeyError,
            PermissionError,
            FileNotFoundError,
            IsADirectoryError,
            ValueError,
        ) as exc:
            # Keep the capture atomic: a registered-but-unindexed resource
            # would otherwise linger invisibly in the library.
            try:
                runtime.resource_service.delete(
                    workspace_id,
                    record.id,
                    sandbox_service=runtime.sandbox_service,
                )
            except Exception:
                logger.warning(
                    "Capture rollback failed for resource %s in workspace %s.",
                    record.id,
                    workspace_id,
                    exc_info=True,
                )
            rollback_download()
            raise HTTPException(
                status_code=409,
                detail={"code": "index_failed", "message": f"Captured resource could not be indexed: {exc}"},
            ) from exc
        indexed = library.remember_download(workspace_id, indexed, download) or indexed

        focus_binding = ""
        focus_id = str(request.bind_focus_id or "").strip()
        if focus_id:
            focus_binding = bind_capture_to_learning_focus(workspace_id, indexed.id, focus_id)

        if bridge is not None and client_capture_id:
            bridge.remember_capture(
                client_capture_id,
                {
                    "resource_id": indexed.id,
                    "recorded_at": indexed.fetched_at or "",
                    "saved_path": download.relative_path if download else "",
                },
            )
        refresh_workspace_sessions(workspace_id)
        return _capture_response(
            indexed,
            deduped=False,
            warnings=[*list(captured.warnings), *download_warnings],
            focus_binding=focus_binding,
            saved_path=download.relative_path if download else None,
        )

    @router.get("/library/groups", response_model=LibraryGroupsResponse)
    def library_groups(
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> LibraryGroupsResponse:
        """Real folders under the library root, with per-group resource counts."""

        resolved_workspace_id = current_workspace_id(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        language = library_language(resolved_workspace_id)
        try:
            snapshot = library.list_groups(resolved_workspace_id)
        except LibraryError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=library_detail(exc, language),
            ) from exc
        return LibraryGroupsResponse(
            workspace_id=resolved_workspace_id,
            managed_root=snapshot.managed_root,
            exists=snapshot.exists,
            trash_root=snapshot.trash_root,
            total_resource_count=snapshot.total_resource_count,
            groups=[
                LibraryGroupNode.model_validate(node) for node in snapshot.groups
            ],
        )

    @router.post("/library/groups")
    def library_create_group(payload: dict) -> dict[str, object]:
        """Create one library folder for real (``mkdir``, ``REORGANIZE`` level)."""

        body = payload if isinstance(payload, dict) else {}
        resolved_workspace_id = current_workspace_id(
            session_id=str(body.get("session_id") or body.get("sessionId") or "").strip()
            or None,
            workspace_id=str(body.get("workspace_id") or body.get("workspaceId") or "").strip()
            or None,
        )
        language = library_language(resolved_workspace_id)
        try:
            return library.create_group(
                resolved_workspace_id,
                str(body.get("path") or ""),
            )
        except LibraryError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=library_detail(exc, language),
            ) from exc

    @router.post("/library/groups/rename")
    def library_rename_group(payload: dict) -> dict[str, object]:
        """Rename (move) one library folder for real (``rename``, ``REORGANIZE``)."""

        body = payload if isinstance(payload, dict) else {}
        resolved_workspace_id = current_workspace_id(
            session_id=str(body.get("session_id") or body.get("sessionId") or "").strip()
            or None,
            workspace_id=str(body.get("workspace_id") or body.get("workspaceId") or "").strip()
            or None,
        )
        language = library_language(resolved_workspace_id)
        try:
            return library.rename_group(
                resolved_workspace_id,
                # ``from``/``to`` is the documented pair; ``path``/``new_path`` is
                # the workbench folder editor's spelling of the same move.
                str(body.get("from") or body.get("from_path") or body.get("fromPath") or body.get("path") or ""),
                str(
                    body.get("to")
                    or body.get("to_path")
                    or body.get("toPath")
                    or body.get("new_path")
                    or body.get("newPath")
                    or ""
                ),
            )
        except LibraryError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=library_detail(exc, language),
            ) from exc

    @router.delete("/library/groups")
    def library_trash_group(payload: dict) -> dict[str, object]:
        """Move a library folder into the library recycle bin (never a hard delete)."""

        body = payload if isinstance(payload, dict) else {}
        resolved_workspace_id = current_workspace_id(
            session_id=str(body.get("session_id") or body.get("sessionId") or "").strip()
            or None,
            workspace_id=str(body.get("workspace_id") or body.get("workspaceId") or "").strip()
            or None,
        )
        language = library_language(resolved_workspace_id)
        try:
            return library.trash_group(
                resolved_workspace_id,
                str(body.get("path") or ""),
            )
        except LibraryError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=library_detail(exc, language),
            ) from exc

    @router.post("/resource/organize", response_model=ResourceRecord)
    def resource_organize(request: ResourceOrganizeRequest) -> ResourceRecord:
        """User-driven library organization: rename, retag, regroup.

        Reuses the existing resource record structure and the managed-storage
        boundaries; sandbox/project artifacts keep belonging to the Coach
        organize flow.
        """

        workspace_id = current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        try:
            organized = runtime.resource_service.organize_resource(workspace_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Resource not found.") from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "resource_move_blocked", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        refresh_workspace_sessions(workspace_id)
        return organized

    @router.get("/resource/export")
    def resource_export(
        resource_id: str,
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> FileResponse:
        """Download one resource's owned snapshot to the local machine."""

        resolved_workspace_id = current_workspace_id(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        try:
            export = runtime.resource_service.export_resource(
                resolved_workspace_id,
                resource_id.strip(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Resource not found.") from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "no_local_snapshot", "message": str(exc)},
            ) from exc
        return FileResponse(
            export["path"],
            media_type=str(export["media_type"]),
            filename=str(export["filename"]),
        )

    @router.post("/resource/search")
    def resource_search(request: ResourceSearchRequest) -> dict[str, object]:
        workspace_id = current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        response = runtime.resource_service.search_resources(
            workspace_id,
            request.query,
            top_k=request.top_k,
            project_scope=request.project_scope,
            trust_state=request.trust_state,
            file_type=request.file_type,
            source_type=request.source_type,
            kind=request.kind,
            index_state=request.index_state,
        )
        from ...pedagogy.material_recommendation import (
            apply_material_recommendation_to_search_results,
            routing_from_learner_state,
        )

        response.results = apply_material_recommendation_to_search_results(
            list(response.results),
            routing_from_learner_state(routing_learner_state(workspace_id)),
            current_workspace_id=workspace_id,
        )
        return serialize_resource_search_response(workspace_id, response)

    @router.get("/resource/trash", response_model=ResourceTrashResponse)
    def resource_trash(
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> ResourceTrashResponse:
        resolved_workspace_id = current_workspace_id(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        return ResourceTrashResponse(
            workspace_id=resolved_workspace_id,
            items=runtime.resource_service.list_trash(
                resolved_workspace_id,
                sandbox_service=runtime.sandbox_service,
            ),
        )

    @router.post("/resource/delete")
    def resource_delete(request: ResourceDeleteRequest) -> dict[str, object]:
        workspace_id = current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        resource_id = request.resource_id.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", resource_id):
            raise HTTPException(
                status_code=422,
                detail="resource_id must be a non-empty safe identifier.",
            )
        try:
            deletion = runtime.resource_service.delete(
                workspace_id,
                resource_id,
                sandbox_service=runtime.sandbox_service,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Resource not found.") from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=409,
                detail="Resource cannot be deleted while its workspace artifact is active.",
            ) from exc

        if not deletion.get("removed"):
            raise HTTPException(status_code=409, detail="Resource deletion did not complete.")

        # Phase-E: propagate deletion to evidence records bound to this
        # resource's content hash, so old citations show "deleted source".
        attempt_store = getattr(runtime, "attempt_store", None)
        version_store = getattr(runtime, "resource_version_store", None)
        if attempt_store is not None and version_store is not None:
            content_hash = version_store.current_content_hash(workspace_id, resource_id)
            if content_hash:
                attempt_store.mark_evidence_source_deleted(
                    workspace_id=workspace_id,
                    content_hash=content_hash,
                    resource_id=resource_id,
                )

        refresh_workspace_sessions(workspace_id)
        return deletion

    @router.post("/resource/organization/cancel")
    def resource_organization_cancel(payload: dict) -> dict[str, object]:
        """Clear server-side organize pending for this workspace (host cancel)."""

        from app.llm.tools import cancel_resource_organization_pending

        workspace_id = current_workspace_id(
            session_id=str(payload.get("session_id") or payload.get("sessionId") or "").strip()
            or None,
            workspace_id=str(payload.get("workspace_id") or payload.get("workspaceId") or "").strip()
            or None,
        )
        # Latch even when pending already consumed by an in-flight confirm so abort
        # restore cannot resurrect a proposal the host cancelled mid-FS.
        # After a successful sandbox commit: honest failure-to-cancel (no pending restore).
        result = cancel_resource_organization_pending(runtime, workspace_id)
        return {
            **result,
            "workspace_id": workspace_id,
        }

    @router.post("/resource/restore")
    def resource_restore(request: ResourceRestoreRequest) -> dict[str, object]:
        workspace_id = current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        resource_id = request.resource_id.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", resource_id):
            raise HTTPException(
                status_code=422,
                detail="resource_id must be a non-empty safe identifier.",
            )
        try:
            restoration = runtime.resource_service.restore_resource(
                workspace_id,
                resource_id,
                sandbox_service=runtime.sandbox_service,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Deleted resource not found.") from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail="Resource could not be restored from Trash.",
            ) from exc

        if not restoration.get("restored"):
            raise HTTPException(status_code=409, detail="Resource restoration did not complete.")

        try:
            refresh_workspace_sessions(workspace_id)
        except Exception:
            logger.warning(
                "Resource restored but session refresh failed for workspace %s.",
                workspace_id,
                exc_info=True,
            )
        return restoration

    return router
