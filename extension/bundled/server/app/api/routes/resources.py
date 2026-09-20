from __future__ import annotations

import logging
import re
from typing import cast

from fastapi import APIRouter, HTTPException

from ...core.models import (
    LibraryAsset,
    LibraryAssetLifecycleRequest,
    LibraryAssetLinkRequest,
    LibraryAssetUpsertRequest,
    LibraryDeleteRequest,
    ResourceDeleteRequest,
    ResourceIndexRequest,
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
from ...workspace.authority import PermissionLevel, WorkspaceAuthority
from ..runtime import TrainerRuntime
from ._deps import RouterDeps

logger = logging.getLogger(__name__)


def build_resources_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter(tags=["resources"])

    current_workspace_id = deps.current_workspace_id
    refresh_workspace_sessions = deps.refresh_workspace_sessions
    routing_learner_state = deps.routing_learner_state

    asset_library = AssetLibraryService(runtime.repository)

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
            return runtime.resource_service.upload(workspace_id, request)
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail="Resource source is outside an authorized workspace or collection.",
            ) from exc
        except (FileNotFoundError, IsADirectoryError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/resource/index", response_model=ResourceRecord)
    def resource_index(request: ResourceIndexRequest) -> ResourceRecord:
        workspace_id = current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        try:
            indexed = runtime.resource_service.index(workspace_id, request)
            indexed, _ = runtime.postprocess_indexed_resource(workspace_id, indexed)
            return indexed
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail="Resource source is outside an authorized workspace or collection.",
            ) from exc
        except (FileNotFoundError, IsADirectoryError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    @router.get("/library/overview")
    def library_overview(
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, object]:
        """One management surface for everything the learner owns:
        conversation history, learning plans, training cards, and materials."""
        resolved_workspace_id = current_workspace_id(session_id=session_id, workspace_id=workspace_id)

        sessions: list[dict[str, object]] = []
        active_session_id = str(session_id or getattr(runtime.latest_session(), "session_id", "") or "").strip()
        for stored in runtime.repository.list_sessions_for_workspace(resolved_workspace_id, limit=30):
            snapshot = stored.get("snapshot")
            messages = snapshot.get("messages") if isinstance(snapshot, dict) else None
            message_items = messages if isinstance(messages, list) else []
            latest_user = next(
                (
                    str(item.get("content") or item.get("body") or "").strip()
                    for item in reversed(message_items)
                    if isinstance(item, dict) and item.get("role") == "user"
                ),
                "",
            )
            updated_at = ""
            if message_items and isinstance(message_items[-1], dict):
                updated_at = str(
                    message_items[-1].get("created_at")
                    or message_items[-1].get("timestamp")
                    or ""
                ).strip()
            stored_session_id = str(stored.get("session_id") or "")
            sessions.append(
                {
                    "id": stored_session_id,
                    "title": (latest_user[:80] or str(stored.get("workspace_name") or "").strip() or "Trainer session"),
                    "messageCount": len(message_items),
                    "updatedAt": updated_at,
                    "isActive": bool(active_session_id and stored_session_id == active_session_id),
                },
            )

        plans: list[dict[str, object]] = []
        for plan in runtime.repository.list_plans(resolved_workspace_id):
            plans.append(
                {
                    "id": str(plan.plan_id or plan.id or ""),
                    "title": str(getattr(plan, "title", "") or getattr(plan, "objective", "") or "Learning plan")[:100],
                    "frozen": bool(getattr(plan, "frozen", False)),
                    "updatedAt": str(getattr(plan, "updated_at", None) or getattr(plan, "created_at", None) or ""),
                },
            )

        cards: list[dict[str, object]] = []
        for card in runtime.memory_service.get_cards(resolved_workspace_id):
            cards.append(
                {
                    "id": card.card_id,
                    "title": card.title or card.focus_area or "Training card",
                    "status": card.status,
                    "focusArea": card.focus_area,
                    "cardType": card.card_type,
                    "updatedAt": card.updated_at if isinstance(card.updated_at, str) else str(card.updated_at),
                },
            )

        return {
            "workspaceId": resolved_workspace_id,
            "sessions": sessions,
            "plans": plans,
            "cards": cards,
            "resources": [
                {"id": item.id, "title": item.name, "kind": item.kind}
                for item in runtime.repository.list_resources(resolved_workspace_id)
            ],
            "activity": runtime.repository.list_library_activity(resolved_workspace_id),
        }

    @router.post("/library/delete")
    def library_delete(request: LibraryDeleteRequest) -> dict[str, object]:
        """Delete one library item. Cards are removed from training routing,
        plans drop with their subplans, sessions remove their history."""
        item_type = request.item_type
        item_id = request.item_id
        workspace_id = current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )

        item_title = item_id
        if item_type == "card":
            existing_card = runtime.memory_service.get_card(workspace_id, item_id)
            if existing_card is not None:
                item_title = existing_card.title or existing_card.focus_area or item_id
            deleted = runtime.memory_service.delete_training_card(workspace_id, item_id)
        elif item_type == "plan":
            existing_plan = runtime.repository.get_plan_by_id(item_id)
            if existing_plan is not None and existing_plan[0] == workspace_id:
                plan = existing_plan[1]
                item_title = str(plan.title or plan.objective or item_id)
            deleted = runtime.repository.delete_plan(workspace_id, item_id)
        elif item_type == "session":
            if request.session_id and request.session_id == item_id:
                raise HTTPException(
                    status_code=409,
                    detail="Switch to another conversation before deleting the current one.",
                )
            stored_session = next(
                (
                    item
                    for item in runtime.repository.list_sessions_for_workspace(workspace_id)
                    if str(item.get("session_id") or "") == item_id
                ),
                None,
            )
            if stored_session is not None:
                snapshot = stored_session.get("snapshot")
                messages = snapshot.get("messages") if isinstance(snapshot, dict) else None
                if isinstance(messages, list):
                    item_title = next(
                        (
                            str(item.get("content") or item.get("body") or "").strip()
                            for item in reversed(messages)
                            if isinstance(item, dict) and item.get("role") == "user"
                        ),
                        item_id,
                    )
            deleted = runtime.repository.delete_session(workspace_id, item_id)
            if deleted:
                runtime.sessions.pop(item_id, None)
        else:
            raise HTTPException(status_code=422, detail="Unknown library item type.")

        if not deleted:
            raise HTTPException(status_code=404, detail="Library item was not found.")

        activity = runtime.repository.record_library_activity(
            workspace_id,
            item_type=item_type,
            item_id=item_id,
            action="deleted",
            payload={"title": item_title[:100]},
        )
        if runtime.event_ledger is not None:
            ledger_event_type = {
                "card": "training_card_deleted",
                "plan": "training_plan_deleted",
                "session": "coach_session_deleted",
            }[item_type]
            runtime.event_ledger.record_event(
                ledger_event_type,
                actor="learner",
                scope="library",
                project_id=workspace_id,
                payload_ref={"type": item_type, "id": item_id, "title": item_title[:100]},
                reversibility="irreversible",
                audit_note="Deleted from the learner's library management surface.",
            )
        refresh_workspace_sessions(workspace_id)
        return {
            "ok": True,
            "type": item_type,
            "id": item_id,
            "requestId": request.request_id,
            "activity": activity,
        }

    return router
