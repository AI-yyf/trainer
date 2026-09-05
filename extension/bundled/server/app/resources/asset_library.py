"""Durable, owner-scoped asset library operations.

This registry is intentionally separate from ``ResourceRecord``. A resource is an
ingested workspace item; a library asset is a durable first-class object that can
be linked to a project context without deleting or restoring source resources.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Literal
from uuid import uuid4

from ..core.models import (
    AssetLink,
    AssetSourceReference,
    AssetSourceState,
    LibraryAsset,
    LibraryAssetCatalogEntry,
    LibraryAssetCatalogSnapshot,
    LibraryAssetLifecycleRequest,
    LibraryAssetLinkRequest,
    LibraryAssetUpsertRequest,
    ProjectContext,
    utc_now_iso,
)
from ..db.repository import TrainerRepository
from .asset_governance import AssetGovernanceOperation, evaluate_asset_governance


class AssetLibraryError(ValueError):
    """Base error for public asset library validation failures."""


class AssetApprovalRequired(AssetLibraryError):
    def __init__(self, operation: str) -> None:
        super().__init__(f"Explicit approval is required for asset operation: {operation}.")
        self.operation = operation


@dataclass(frozen=True, slots=True)
class AssetLibrarySearch:
    items: list[LibraryAsset]
    total: int


class AssetLibraryService:
    """Translate stable API requests into the existing asset registry."""

    def __init__(self, repository: TrainerRepository) -> None:
        self.repository = repository

    def upsert(self, request: LibraryAssetUpsertRequest) -> LibraryAsset:
        owner_id = self.repository.ensure_default_local_owner().id
        context = self._resolve_context(request.project_id, request.context_id)
        if request.scope == "project" and context is None:
            raise AssetLibraryError("Project-scoped assets require a project context.")
        self._assert_asset_operation_approved(request.asset_type, request.approved)
        source_chain = self._normalized_source_chain(request.canonical_source, request.source_chain)
        self._validate_source_chain(owner_id, source_chain, context)

        existing = (
            self.repository.get_library_asset(owner_id, request.asset_id)
            if request.asset_id
            else None
        )
        if existing is not None and existing.status == "deleted":
            raise AssetLibraryError("Restore a deleted asset before updating it.")

        timestamp = utc_now_iso()
        asset = LibraryAsset(
            id=request.asset_id or f"asset-{uuid4().hex}",
            ownerId=owner_id,
            assetType=request.asset_type,
            scope=request.scope,
            title=request.title,
            canonicalSource=request.canonical_source,
            sourceChain=source_chain,
            projectId=context.project_id if context else None,
            contextId=context.context_id if context else None,
            payload=dict(request.payload),
            createdAt=existing.created_at if existing else timestamp,
            updatedAt=timestamp,
        )
        self.repository.save_library_asset(asset)
        return self._require_asset(owner_id, asset.id)

    def get(
        self,
        asset_id: str,
        *,
        context_id: str | None = None,
        include_deleted: bool = False,
    ) -> LibraryAsset:
        owner_id = self.repository.ensure_default_local_owner().id
        asset = self._require_asset(owner_id, asset_id)
        if asset.status == "deleted" and not include_deleted:
            raise KeyError(f"Unknown library asset: {asset_id}")
        if context_id:
            context = self._resolve_context(None, context_id)
            assert context is not None
            if not self._is_available_to_context(owner_id, asset, context.context_id):
                raise PermissionError("Asset is not available to the requested project context.")
        return asset

    def list(
        self,
        *,
        query: str = "",
        scope: str | None = None,
        asset_type: str | None = None,
        project_id: str | None = None,
        context_id: str | None = None,
        include_deleted: bool = False,
        limit: int = 50,
    ) -> AssetLibrarySearch:
        owner_id = self.repository.ensure_default_local_owner().id
        context = self._resolve_context(project_id, context_id) if (project_id or context_id) else None
        assets = self.repository.search_library_assets(
            owner_id,
            query,
            scope=scope,
            asset_type=asset_type,
            include_deleted=include_deleted,
            limit=100,
        )
        if context is not None:
            assets = [
                asset
                for asset in assets
                if self._is_available_to_context(owner_id, asset, context.context_id)
            ]
        return AssetLibrarySearch(items=assets[: max(1, min(limit, 100))], total=len(assets))

    def catalog(self, context_id: str) -> LibraryAssetCatalogSnapshot:
        context = self._resolve_context(None, context_id)
        assert context is not None
        owner_id = self.repository.ensure_default_local_owner().id
        visible_assets = [
            asset
            for asset in self.repository.list_library_assets(owner_id, include_deleted=True)
            if self._is_available_to_context(owner_id, asset, context.context_id)
        ]
        entries = [
            LibraryAssetCatalogEntry(
                asset=asset,
                capabilities=self.capabilities(asset),
                sourceState=[
                    AssetSourceState.model_validate(state)
                    for state in self.source_state(asset)
                ],
            )
            for asset in visible_assets
        ]
        revision_payload = {
            "contextId": context.context_id,
            "entries": sorted(
                (entry.model_dump(by_alias=True, mode="json") for entry in entries),
                key=lambda entry: str(entry["asset"]["id"]),
            ),
            "links": sorted(
                (
                    link.model_dump(by_alias=True, mode="json")
                    for asset in visible_assets
                    for link in self.repository.list_asset_links(
                        owner_id,
                        asset_id=asset.id,
                        workspace_id=context.context_id,
                    )
                ),
                key=lambda link: str(link["id"]),
            ),
        }
        revision = hashlib.sha256(
            json.dumps(revision_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return LibraryAssetCatalogSnapshot(
            contextId=context.context_id,
            revision=revision,
            active=[entry for entry in entries if entry.asset.status == "active"],
            deleted=[entry for entry in entries if entry.asset.status == "deleted"],
        )

    def link(self, asset_id: str, request: LibraryAssetLinkRequest) -> AssetLink:
        owner_id = self.repository.ensure_default_local_owner().id
        asset = self._require_asset(owner_id, asset_id)
        if asset.status != "active":
            raise AssetLibraryError("Deleted assets cannot be linked until they are restored.")
        context = self._resolve_context(request.project_id, request.context_id)
        assert context is not None

        crosses_project_boundary = bool(
            asset.scope == "project"
            and asset.context_id
            and asset.context_id != context.context_id
        )
        if crosses_project_boundary:
            self._assert_approved(AssetGovernanceOperation.SHARE_CROSS_PROJECT, request.approved)

        link = AssetLink(
            id=f"asset-link-{uuid4().hex}",
            ownerId=owner_id,
            assetId=asset.id,
            workspaceId=context.context_id,
            projectId=context.project_id,
            contextId=context.context_id,
            relation=request.relation,
            sourceRef=request.source_ref.strip(),
            payload=dict(request.payload),
        )
        self.repository.save_asset_link(link)
        for stored in self.repository.list_asset_links(
            owner_id,
            asset_id=asset.id,
            workspace_id=context.context_id,
        ):
            if (
                stored.relation == link.relation
                and stored.source_ref == link.source_ref
                and stored.context_id == link.context_id
            ):
                return stored
        raise RuntimeError("Asset link could not be read after persistence.")

    def links(self, asset_id: str, *, context_id: str | None = None) -> list[AssetLink]:
        owner_id = self.repository.ensure_default_local_owner().id
        self._require_asset(owner_id, asset_id)
        canonical_context = self._resolve_context(None, context_id) if context_id else None
        return self.repository.list_asset_links(
            owner_id,
            asset_id=asset_id,
            workspace_id=canonical_context.context_id if canonical_context else None,
        )

    def archive(self, asset_id: str, request: LibraryAssetLifecycleRequest) -> LibraryAsset:
        self._assert_approved(AssetGovernanceOperation.DELETE, request.approved)
        owner_id = self.repository.ensure_default_local_owner().id
        return self.repository.archive_library_asset(
            owner_id,
            asset_id,
            deleted_at=utc_now_iso(),
            reason=request.reason,
        )

    def restore(self, asset_id: str, request: LibraryAssetLifecycleRequest) -> LibraryAsset:
        self._assert_approved(AssetGovernanceOperation.DELETE, request.approved)
        owner_id = self.repository.ensure_default_local_owner().id
        return self.repository.restore_library_asset(owner_id, asset_id, restored_at=utc_now_iso())

    @staticmethod
    def capabilities(asset: LibraryAsset) -> dict[str, Literal["supported", "unsupported"]]:
        capabilities: dict[str, Literal["supported", "unsupported"]] = {
            "registry": "supported",
            "search": "supported",
            "source_links": "supported",
            "project_links": "supported",
            "soft_delete": "supported",
        }
        if asset.asset_type == "agent":
            capabilities["agent_execution"] = "unsupported"
        if asset.asset_type == "runtime_artifact":
            capabilities["runtime_execution"] = "unsupported"
        return capabilities

    def source_state(self, asset: LibraryAsset) -> list[dict[str, str]]:
        """Report only source availability the local registry can actually verify."""

        states: list[dict[str, str]] = []
        for source in asset.source_chain:
            state = "unknown"
            if source.kind == "resource":
                state = (
                    "available"
                    if asset.context_id and self.repository.get_resource(asset.context_id, source.ref)
                    else "missing"
                )
            elif source.kind == "asset":
                linked_asset = self.repository.get_library_asset(asset.owner_id, source.ref)
                state = "available" if linked_asset and linked_asset.status == "active" else "missing"
            elif source.kind == "project":
                state = "available" if self.repository.get_trainer_project(source.ref) else "missing"
            elif source.kind == "context":
                state = "available" if self.repository.get_project_context(source.ref) else "missing"
            elif source.kind == "runtime":
                state = "unsupported"
            states.append({"kind": source.kind, "ref": source.ref, "state": state})
        return states

    def _resolve_context(
        self,
        project_id: str | None,
        context_id: str | None,
    ) -> ProjectContext | None:
        normalized_project_id = str(project_id or "").strip()
        normalized_context_id = str(context_id or "").strip()
        if normalized_context_id:
            context = self.repository.get_project_context(normalized_context_id)
            if context is None:
                raise KeyError(f"Unknown project context: {normalized_context_id}")
            if normalized_project_id and context.project_id != normalized_project_id:
                raise AssetLibraryError("projectId does not match contextId.")
            return context
        if normalized_project_id:
            context = self.repository.get_project_context_for_project(normalized_project_id)
            if context is None:
                raise KeyError(f"Unknown project: {normalized_project_id}")
            return context
        return None

    def _validate_source_chain(
        self,
        owner_id: str,
        source_chain: Iterable[AssetSourceReference],
        context: ProjectContext | None,
    ) -> None:
        for source in source_chain:
            if source.kind == "resource":
                if context is None:
                    raise AssetLibraryError("A resource source requires a project context.")
                if self.repository.get_resource(context.context_id, source.ref) is None:
                    raise KeyError(f"Unknown resource source: {source.ref}")
            elif source.kind == "asset" and self.repository.get_library_asset(owner_id, source.ref) is None:
                raise KeyError(f"Unknown asset source: {source.ref}")
            elif source.kind == "project" and self.repository.get_trainer_project(source.ref) is None:
                raise KeyError(f"Unknown project source: {source.ref}")
            elif source.kind == "context" and self.repository.get_project_context(source.ref) is None:
                raise KeyError(f"Unknown context source: {source.ref}")

    @staticmethod
    def _normalized_source_chain(
        canonical_source: str,
        source_chain: Iterable[AssetSourceReference],
    ) -> list[AssetSourceReference]:
        normalized = list(source_chain)
        canonical = canonical_source.strip()
        if canonical and not any(source.ref == canonical for source in normalized):
            normalized.append(
                AssetSourceReference(
                    kind="url" if "://" in canonical else "manual",
                    ref=canonical,
                    label="canonical source",
                )
            )
        return normalized

    def _is_available_to_context(self, owner_id: str, asset: LibraryAsset, context_id: str) -> bool:
        if asset.scope != "project":
            return True
        if asset.context_id == context_id:
            return True
        return any(
            link.workspace_id == context_id
            for link in self.repository.list_asset_links(owner_id, asset_id=asset.id, workspace_id=context_id)
        )

    def _require_asset(self, owner_id: str, asset_id: str) -> LibraryAsset:
        asset = self.repository.get_library_asset(owner_id, asset_id)
        if asset is None:
            raise KeyError(f"Unknown library asset: {asset_id}")
        return asset

    def _assert_asset_operation_approved(self, asset_type: str, approved: bool) -> None:
        operation = {
            "memory": AssetGovernanceOperation.PROMOTE_LONG_TERM_MEMORY,
            "habit": AssetGovernanceOperation.DEFINE_HABIT,
            "skill": AssetGovernanceOperation.DEFINE_SKILL,
            "skill_definition": AssetGovernanceOperation.DEFINE_SKILL,
        }.get(asset_type)
        if operation is not None:
            self._assert_approved(operation, approved)

    @staticmethod
    def _assert_approved(operation: AssetGovernanceOperation, approved: bool) -> None:
        decision = evaluate_asset_governance(operation, recomputable=False)
        if decision.requires_approval and not approved:
            raise AssetApprovalRequired(decision.operation)
