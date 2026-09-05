from __future__ import annotations

import base64
import logging
import os
import re
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha1
from pathlib import Path, PurePosixPath
from threading import Lock, RLock
from typing import Any, Callable, Iterable, Literal, Mapping
from urllib.parse import unquote, urlparse
from uuid import uuid4

from ..core.models import (
    ResourceIndexRequest,
    ResourceTrashItem,
    ResourceUploadRequest,
)
from ..core.models import ResourceRecord as ApiResourceRecord
from ..db.repository import TrainerRepository
from ..ingest.models import IngestionRequest, IngestionResult, IngestionSummary
from ..ingest.service import IngestService, ResourceIngestor
from ..memory.semantic import SemanticMemory
from .models import (
    IndexStatus,
    IngestStatus,
    ResourceChunk,
    ResourceKind,
    ResourceRecord,
    utc_now,
)
from .search import SearchFilters, SearchIndex, SearchResponse
from .source_governance import (
    commercial_reuse_eligibility_reason_codes,
    commercial_reuse_governance_status,
    evaluate_source_intake_governance,
    is_external_reference_source,
    source_governance_payload,
)
from .source_governance import (
    is_commercial_reuse_eligible as source_is_commercial_reuse_eligible,
)

_REFERENCE_STOPWORDS = {
    "a",
    "an",
    "and",
    "be",
    "before",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "one",
    "the",
    "to",
    "use",
    "with",
}

logger = logging.getLogger(__name__)


class ResourceRegistry:
    """Owned resource aggregate used by the richer ingest path and tests."""

    def __init__(self) -> None:
        self._resources: dict[str, ResourceRecord] = {}
        self._chunks: dict[str, list[ResourceChunk]] = defaultdict(list)

    def register(self, resource: ResourceRecord) -> ResourceRecord:
        resource.updated_at = utc_now()
        self._resources[resource.id] = resource
        return resource

    def get(self, resource_id: str) -> ResourceRecord | None:
        return self._resources.get(resource_id)

    def list_resources(self) -> list[ResourceRecord]:
        return sorted(self._resources.values(), key=lambda item: item.created_at)

    def list_chunks(self, resource_id: str) -> list[ResourceChunk]:
        return sorted(self._chunks.get(resource_id, []), key=lambda item: item.order)

    def attach_chunks(
        self,
        resource_id: str,
        chunks: Iterable[ResourceChunk],
        *,
        ingest_status: IngestStatus = IngestStatus.INGESTED,
        summary: str | None = None,
        metadata_updates: dict[str, object] | None = None,
    ) -> ResourceRecord:
        resource = self._require(resource_id)
        self._chunks[resource_id] = list(chunks)
        resource.ingest_status = ingest_status
        resource.summary = summary or resource.summary
        if metadata_updates:
            resource.metadata.update(metadata_updates)
        resource.updated_at = utc_now()
        return resource

    def mark_indexed(
        self,
        resource_id: str,
        *,
        index_status: IndexStatus,
        metadata_updates: dict[str, object] | None = None,
    ) -> ResourceRecord:
        resource = self._require(resource_id)
        resource.index_status = index_status
        if metadata_updates:
            resource.metadata.update(metadata_updates)
        resource.updated_at = utc_now()
        return resource

    def clone_resource(self, resource_id: str) -> ResourceRecord:
        return replace(self._require(resource_id))

    def _require(self, resource_id: str) -> ResourceRecord:
        resource = self.get(resource_id)
        if resource is None:
            raise KeyError(f"Unknown resource_id: {resource_id}")
        return resource


class ResourceService:
    def __init__(
        self,
        repository: TrainerRepository,
        ingest_service: IngestService,
        semantic_memory: SemanticMemory,
        *,
        enable_network_fetch: bool = False,
        data_root: Path | None = None,
    ) -> None:
        self.repository = repository
        self.ingest_service = ingest_service
        self.semantic_memory = semantic_memory
        self.enable_network_fetch = enable_network_fetch
        self.data_root = data_root or repository.database_path.parent
        self.registry = ResourceRegistry()
        self.ingestor = ResourceIngestor(self.registry, ingest_service)
        self._workspace_path_resolver: Callable[[str], str | None] | None = None
        self._search_indexes: dict[str, SearchIndex] = {}
        self._resource_restore_locks: dict[tuple[str, str], Any] = {}
        self._resource_restore_locks_guard = Lock()

    def set_workspace_path_resolver(
        self,
        resolver: Callable[[str], str | None] | None,
    ) -> None:
        self._workspace_path_resolver = resolver

    def close(self) -> None:
        close = getattr(self.semantic_memory, "close", None)
        if callable(close):
            close()

    def upload(
        self,
        workspace_id: str,
        request: ResourceUploadRequest,
        *,
        workspace_path: str | None = None,
    ) -> ApiResourceRecord:
        explicit_workspace_root = self._resolved_workspace_root(workspace_path)
        resolved_workspace_root = explicit_workspace_root or self._resolved_workspace_path(workspace_id)
        original_source = str(request.source or "").strip()
        had_inline_content = bool(request.content)
        request = self._materialize_inline_content(workspace_id, request)
        if resolved_workspace_root is not None and original_source and not had_inline_content:
            self._validate_source_within_workspace(
                original_source,
                resolved_workspace_root,
                source_type=request.source_type,
            )
        self._validate_source(request.source, source_type=request.source_type)
        canonical_source = self._canonical_source(request.source)
        source_items = self._normalize_source_items(request.source_items)
        collection_path = self._normalize_collection_path(request.collection_path)
        collection_root = self._normalize_collection_root(request.collection_root)
        self._validate_collection_identity(
            request.source,
            collection_path=collection_path,
            collection_root=collection_root,
        )
        if request.source_type == "folder" or source_items:
            self._validate_folder_source_items(request.source, source_items)
        source_governance = evaluate_source_intake_governance(
            source_uri=request.source,
            source_text="",
            declaration=request.source_declaration,
        )
        resource = ApiResourceRecord(
            id=f"resource-{uuid4().hex[:10]}",
            kind=request.kind,
            name=request.name,
            source=request.source,
            tags=request.tags,
            summary="Registered and waiting for parsing.",
            source_type=self._source_type(request.kind, request.source),
            canonical_source=canonical_source,
            freshness=self._initial_freshness(request.kind, request.source),
            source_items=source_items,
            collection_path=collection_path,
            collection_root=collection_root,
            source_declaration=request.source_declaration,
            source_governance=source_governance,
        )
        self.repository.save_resource(workspace_id, resource)
        self._ensure_registry_resource(resource)
        return resource

    def delete(
        self,
        workspace_id: str,
        resource_id: str,
        *,
        sandbox_service: Any | None = None,
    ) -> dict[str, Any]:
        return self.delete_resource(
            workspace_id,
            resource_id,
            sandbox_service=sandbox_service,
        )

    def index(self, workspace_id: str, request: ResourceIndexRequest) -> ApiResourceRecord:
        resource = self._require_workspace_resource(workspace_id, request.resource_id)
        self._ensure_registry_resource(resource)
        effective_source_type = "folder" if self._is_folder_resource(resource) else resource.source_type
        workspace_root = self._resolved_workspace_path(workspace_id)
        if workspace_root is not None and not self._is_managed_inline_source(
            workspace_id,
            resource.source,
        ) and not self._is_managed_sandbox_source(workspace_id, resource.source):
            self._validate_source_within_workspace(
                resource.source,
                workspace_root,
                source_type=effective_source_type,
            )
        self._validate_source(resource.source, source_type=effective_source_type)
        if self._is_folder_resource(resource):
            self._validate_folder_source_items(resource.source, resource.source_items)
        network_allowed = self._network_fetch_enabled(request.enable_network)
        ingest_result = self._ingest_resource_record(resource, network_allowed=network_allowed)
        normalized_chunks = [
            replace(chunk, resource_id=resource.id) if chunk.resource_id != resource.id else chunk
            for chunk in ingest_result.chunks
        ]
        combined_text = "\n\n".join(chunk.text for chunk in normalized_chunks if chunk.text)
        source_provenance = getattr(ingest_result, "source_provenance", {})
        if not isinstance(source_provenance, dict):
            source_provenance = {}
        url_fetch_succeeded = (
            resource.kind == "url" and source_provenance.get("status") == "fetched"
        )
        source_for_canonicalization = (
            str(source_provenance.get("final_url") or resource.source)
            if url_fetch_succeeded
            else resource.source
        )
        canonical_source = self._canonical_source(source_for_canonicalization)
        fetched_at = (
            str(source_provenance.get("fetched_at") or "").strip() or None
            if resource.kind == "url"
            else datetime.now(UTC).isoformat()
        )
        freshness = self._freshness(resource.kind, resource.source, fetched_at=fetched_at)
        duplicate_key = self._duplicate_key(resource.kind, resource.source, normalized_chunks)
        warnings = list(ingest_result.warnings)
        content_type = str(source_provenance.get("content_type") or "").strip()
        if url_fetch_succeeded and content_type:
            warnings = self._append_unique(
                warnings,
                [
                    "Source provenance: "
                    f"final_url={canonical_source}; content_type={content_type}."
                ],
            )
        source_governance = evaluate_source_intake_governance(
            source_uri=resource.source,
            source_text=combined_text,
            source_provenance=source_provenance,
            declaration=resource.source_declaration,
        )
        quality_flags = self._quality_flags(
            resource.kind,
            warnings,
            network_allowed=network_allowed,
            freshness=freshness,
            extracted_characters=ingest_result.summary.extracted_characters,
            chunks=normalized_chunks,
        )
        canonical_duplicate = self._canonical_resource_for_duplicate_key(
            workspace_id,
            duplicate_key,
            exclude_id=resource.id,
        )
        if canonical_duplicate is not None:
            quality_flags = self._append_unique(quality_flags, ["duplicate"])
        conflicting_resource = self._conflicting_resource_for_source(
            workspace_id,
            kind=resource.kind,
            canonical_source=canonical_source,
            duplicate_key=duplicate_key,
            exclude_id=resource.id,
        )
        if conflicting_resource is not None:
            quality_flags = self._append_unique(quality_flags, ["source_conflict"])
            warnings = self._append_unique(
                warnings,
                [f"Source content conflicts with an existing indexed version of {resource.name}."],
            )
        trust_score = self._trust_score(resource.kind, quality_flags)
        knowledge_fragments = self._knowledge_fragments(
            resource=resource,
            canonical_source=canonical_source,
            trust_score=trust_score,
            freshness=freshness,
            chunks=normalized_chunks,
            quality_flags=quality_flags,
            duplicate_key=duplicate_key,
        )
        if canonical_duplicate is not None:
            knowledge_fragments = []
        failure_flags = {
            "fetch_failed",
            "blocked_source",
            "network_disabled",
            "placeholder",
            "no_content",
        }
        indexing_failed = any(flag in failure_flags for flag in quality_flags)
        self.registry.attach_chunks(
            resource.id,
            normalized_chunks,
            ingest_status=IngestStatus.FAILED if indexing_failed else IngestStatus.INGESTED,
            summary=ingest_result.summary.text_preview or resource.summary,
            metadata_updates={
                "workspace_id": workspace_id,
                "kind": resource.kind,
                "name": resource.name,
                "chunk_count": len(normalized_chunks),
                "character_count": ingest_result.summary.extracted_characters,
                "warnings": list(warnings),
                "duplicate_key": duplicate_key,
                "trust_score": trust_score,
                "freshness": freshness,
                "quality_flags": list(quality_flags),
                "knowledge_fragments": list(knowledge_fragments),
                "source_governance": source_governance.model_dump(mode="json"),
                "source_provenance": {
                    "status": str(source_provenance.get("status") or ""),
                    "final_url": canonical_source if url_fetch_succeeded else "",
                    "fetched_at": fetched_at or "",
                    "content_type": content_type,
                },
            },
        )
        self.registry.mark_indexed(
            resource.id,
            index_status=IndexStatus.FAILED if indexing_failed else IndexStatus.INDEXED,
        )

        if indexing_failed:
            self.semantic_memory.delete_text(resource.id)
        else:
            self.semantic_memory.upsert_text(
                resource.id,
                combined_text[:4000],
                {"workspace_id": workspace_id, "kind": resource.kind, "name": resource.name},
            )
        updated = resource.model_copy(
            update={
                "parse_status": "failed" if indexing_failed else "parsed",
                "index_status": "failed" if indexing_failed else "indexed",
                "summary": canonical_duplicate.summary if canonical_duplicate and canonical_duplicate.summary else ingest_result.summary.text_preview or resource.summary,
                "source_type": self._source_type(resource.kind, resource.source),
                "canonical_source": canonical_source,
                "fetched_at": fetched_at,
                "trust_score": trust_score,
                "freshness": freshness,
                "duplicate_key": duplicate_key,
                "quality_flags": quality_flags,
                "warnings": list(warnings),
                "knowledge_fragments": knowledge_fragments,
                "source_governance": source_governance,
            }
        )
        if canonical_duplicate is not None:
            updated = updated.model_copy(
                update={
                    "quality_flags": self._append_unique(updated.quality_flags, ["duplicate"]),
                    "summary": canonical_duplicate.summary or updated.summary,
                    "knowledge_fragments": [],
                    "trust_score": max(updated.trust_score, canonical_duplicate.trust_score),
                }
            )
        self.repository.save_resource(workspace_id, updated)
        if updated.index_status == "indexed":
            self._index_search_resource(
                workspace_id,
                updated,
                combined_text=combined_text,
                chunks=normalized_chunks,
            )
        else:
            self._search_index(workspace_id).delete_document(updated.id)
        return updated

    def refresh_organized_resource(
        self,
        workspace_id: str,
        resource: ApiResourceRecord,
        *,
        sandbox_path: str,
    ) -> ApiResourceRecord:
        """Keep the library record and search index pointed at a sandbox move."""

        updated = resource.model_copy(
            update={
                "sandbox_path": str(sandbox_path),
                "sandbox_dirty": False,
            }
        )
        self.repository.save_resource(workspace_id, updated)
        self._ensure_registry_resource(updated)
        if updated.index_status != "indexed":
            return updated
        chunks = self.registry.list_chunks(updated.id)
        combined_text = "\n\n".join(
            chunk.text for chunk in chunks if getattr(chunk, "text", None)
        )
        if not combined_text.strip():
            combined_text = (
                self._search_index(workspace_id).document_content(updated.id)
                or updated.summary
                or updated.name
            )
        self._index_search_resource(
            workspace_id,
            updated,
            combined_text=combined_text,
            chunks=chunks,
        )
        return updated

    def search_resources(
        self,
        workspace_id: str,
        query: str,
        *,
        top_k: int = 10,
        project_scope: str | None = None,
        trust_state: str | None = None,
        file_type: str | None = None,
        source_type: str | None = None,
        kind: str | None = None,
        index_state: str | None = None,
    ) -> SearchResponse:
        filters = SearchFilters(
            project_scope=project_scope or workspace_id,
            trust_state=trust_state,
            file_type=file_type,
            source_type=source_type,
            kind=kind,
            index_state=index_state,
        )
        return self._search_index(workspace_id).search(
            query,
            filters=filters,
            top_k=max(1, min(top_k, 50)),
        )

    def delete_resource(
        self,
        workspace_id: str,
        resource_id: str,
        *,
        sandbox_service: Any | None = None,
    ) -> dict[str, Any]:
        resource = self._require_workspace_resource(workspace_id, resource_id)
        if sandbox_service is None and (
            str(resource.sandbox_path or "").strip() or str(resource.extracted_artifact_path or "").strip()
        ):
            raise PermissionError(
                "Resource is linked to an active workspace sandbox. Trash the workspace artifact first, then retry deletion."
            )
        removal_result: dict[str, Any]
        if sandbox_service is not None:
            removal_result = dict(
                sandbox_service.remove_resource(
                    workspace_id,
                    resource,
                    linked_resources=self.repository.list_resources(workspace_id),
                )
            )
        else:
            removal_result = {
                "primary_trashed_path": None,
                "trashed_paths": {},
                "patch": [],
                "diff_summary": "",
                "checkpoint_id": "",
                "ledger_entry_id": "",
                "authority_summary": {},
            }

        deleted_at = datetime.now(UTC).isoformat()
        removed = self.repository.archive_and_delete_resource(
            workspace_id,
            resource,
            deletion_payload=removal_result,
            deleted_at=deleted_at,
        )
        if not removed:
            return {
                "removed": False,
                "detail": "Resource deletion did not complete.",
                **removal_result,
            }

        search_index_removed = self._search_index(workspace_id).delete_document(resource_id)
        semantic_removed = False
        delete_text = getattr(self.semantic_memory, "delete_text", None)
        if callable(delete_text):
            try:
                semantic_removed = bool(delete_text(resource_id))
            except Exception:
                semantic_removed = False

        self.registry._resources.pop(resource_id, None)
        self.registry._chunks.pop(resource_id, None)

        try:
            artifact_paths = self._archived_artifact_paths(removal_result)
        except ValueError:
            recoverable = False
        else:
            recoverable = not artifact_paths or bool(
                sandbox_service
                and sandbox_service.can_restore_resource_artifacts(workspace_id, artifact_paths)
            )

        return {
            "removed": removed,
            "detail": (
                "Resource removed from workspace and sandbox trash updated."
                if removal_result.get("patch")
                else "Resource removed from workspace."
            ),
            "search_index_removed": search_index_removed,
            "semantic_removed": semantic_removed,
            "recoverable": recoverable,
            "deleted_at": deleted_at,
            **removal_result,
        }

    def restore_resource(
        self,
        workspace_id: str,
        resource_id: str,
        *,
        sandbox_service: Any | None = None,
    ) -> dict[str, Any]:
        with self._resource_restore_lock(workspace_id, resource_id):
            return self._restore_resource_locked(
                workspace_id,
                resource_id,
                sandbox_service=sandbox_service,
            )

    def _restore_resource_locked(
        self,
        workspace_id: str,
        resource_id: str,
        *,
        sandbox_service: Any | None = None,
    ) -> dict[str, Any]:
        archived = self.repository.get_deleted_resource(workspace_id, resource_id)
        if archived is None:
            raise KeyError(f"Unknown deleted resource_id: {resource_id}")
        resource, deletion_payload = archived
        artifact_paths = self._archived_artifact_paths(deletion_payload)

        sandbox_state = None
        artifact_restore: dict[str, Any] | None = None
        if artifact_paths:
            if sandbox_service is None:
                raise PermissionError("Resource artifacts require the workspace sandbox for restoration.")
            try:
                artifact_restore = sandbox_service.restore_resource_artifacts(
                    workspace_id,
                    artifact_paths,
                )
            except Exception as exc:
                raise ValueError("Resource artifacts could not be restored atomically.") from exc

        warnings = self._append_unique(
            list(resource.warnings),
            ["Restored from Trash. Re-index this resource before relying on search or mastery evidence."],
        )
        restored = resource.model_copy(
            update={
                "parse_status": "pending",
                "index_status": "pending",
                "fetched_at": None,
                "knowledge_fragments": [],
                "warnings": warnings,
            }
        )
        try:
            activated = self.repository.restore_deleted_resource(workspace_id, restored)
        except Exception as exc:
            self._compensate_tombstone_activation_failure(
                workspace_id,
                sandbox_service=sandbox_service,
                artifact_restore=artifact_restore,
            )
            raise ValueError("Resource record could not be activated from Trash.") from exc
        if not activated:
            self._compensate_tombstone_activation_failure(
                workspace_id,
                sandbox_service=sandbox_service,
                artifact_restore=artifact_restore,
            )
            raise ValueError("Resource record could not be activated from Trash.")
        self._ensure_registry_resource(restored)
        self.registry._chunks.pop(restored.id, None)

        if sandbox_service is not None:
            try:
                sandbox_state = sandbox_service.list_state(
                    workspace_id,
                    self.repository.list_resources(workspace_id),
                )
            except Exception:
                logger.warning(
                    "Resource restored but sandbox state refresh failed for %s/%s.",
                    workspace_id,
                    resource_id,
                    exc_info=True,
                )

        return {
            "restored": True,
            "resource": restored,
            "sandbox_state": sandbox_state,
            "reindex_required": True,
        }

    def _resource_restore_lock(self, workspace_id: str, resource_id: str) -> Any:
        key = (workspace_id, resource_id)
        with self._resource_restore_locks_guard:
            lock = self._resource_restore_locks.get(key)
            if lock is None:
                lock = RLock()
                self._resource_restore_locks[key] = lock
            return lock

    @staticmethod
    def _compensate_tombstone_activation_failure(
        workspace_id: str,
        *,
        sandbox_service: Any | None,
        artifact_restore: dict[str, Any] | None,
    ) -> None:
        if artifact_restore is None:
            return
        if sandbox_service is None:
            raise ValueError("Resource artifact compensation requires the workspace sandbox.")
        restore_handle = artifact_restore.get("restore_handle")
        if not isinstance(restore_handle, list):
            raise ValueError("Resource artifact restore did not return a valid compensation handle.")
        try:
            sandbox_service.compensate_resource_artifact_restore(workspace_id, restore_handle)
        except Exception as exc:
            raise ValueError(
                "Resource artifacts could not be returned to Trash after activation failed."
            ) from exc

    def list_trash(
        self,
        workspace_id: str,
        *,
        sandbox_service: Any | None = None,
    ) -> list[ResourceTrashItem]:
        """Project durable tombstones into the limited data the Trash UI needs."""
        items: list[ResourceTrashItem] = []
        for resource, deleted_at in self.repository.list_deleted_resources(workspace_id):
            try:
                collection_path = self._normalize_collection_path(resource.collection_path)
            except ValueError:
                # Legacy or corrupted records must not expose an unsafe path-like value.
                collection_path = None
            archived = self.repository.get_deleted_resource(workspace_id, resource.id)
            if archived is None:
                recoverable = False
            else:
                try:
                    artifact_paths = self._archived_artifact_paths(archived[1])
                    recoverable = not artifact_paths or bool(
                        sandbox_service
                        and sandbox_service.can_restore_resource_artifacts(workspace_id, artifact_paths)
                    )
                except ValueError:
                    recoverable = False
            items.append(
                ResourceTrashItem(
                    resource_id=resource.id,
                    title=resource.name,
                    collection_path=collection_path,
                    deleted_at=deleted_at,
                    recoverable=recoverable,
                )
            )
        return items

    @staticmethod
    def _archived_artifact_paths(deletion_payload: dict[str, Any]) -> dict[str, str]:
        raw_paths = deletion_payload.get("trashed_paths")
        if raw_paths is not None and not isinstance(raw_paths, dict):
            raise ValueError("Resource Trash metadata contains invalid artifact paths.")

        artifact_paths: dict[str, str] = {}
        for raw_destination, raw_source in (raw_paths or {}).items():
            destination = str(raw_destination or "").strip()
            source = str(raw_source or "").strip()
            if not destination or not source:
                raise ValueError("Resource Trash metadata contains an incomplete artifact path.")
            artifact_paths[destination] = source

        primary_path = str(deletion_payload.get("primary_trashed_path") or "").strip()
        if primary_path and primary_path not in artifact_paths.values():
            artifact_paths[""] = primary_path
        return artifact_paths

    def _ingest_resource_record(
        self,
        resource: ApiResourceRecord,
        *,
        network_allowed: bool,
    ) -> IngestionResult:
        base_request = IngestionRequest(
            source_uri=resource.source,
            display_name=resource.name,
            kind=ResourceKind(resource.kind),
            metadata={"tags": list(resource.tags), "source_items": list(resource.source_items)},
            enable_network=network_allowed,
        )
        if self._is_folder_resource(resource):
            folder_chunks: list[ResourceChunk] = []
            folder_warnings: list[str] = []
            folder_summary_texts: list[str] = []
            for index, source_item in enumerate(resource.source_items[:100]):
                child_request = IngestionRequest(
                    source_uri=source_item,
                    display_name=Path(source_item).name or source_item,
                    kind=self.ingestor._detect_kind(source_item),
                    metadata={"folder": resource.source, "folder_item_index": index},
                    enable_network=network_allowed,
                )
                text, warnings = self.ingest_service.describe_source(child_request, vision_enabled=False)
                folder_warnings.extend(warnings)
                folder_summary_texts.append(text[:240])
                child_chunks = self.ingestor._chunk_text(
                    resource.id,
                    text,
                    child_request.chunk_size,
                    child_request.chunk_overlap,
                    kind=child_request.kind or ResourceKind.UNKNOWN,
                )
                folder_chunks.extend(
                    [
                        replace(
                            chunk,
                            resource_id=resource.id,
                            metadata={
                                **chunk.metadata,
                                "folder_item": source_item,
                                "folder_item_index": index,
                            },
                        )
                        for chunk in child_chunks
                    ]
                )
            summary = IngestionSummary(
                text_preview=" | ".join(folder_summary_texts[:3])[:240],
                detected_kind=ResourceKind(resource.kind),
                extracted_characters=sum(len(item) for item in folder_summary_texts),
                chunk_count=len(folder_chunks),
            )
            metadata_updates = {
                "character_count": sum(len(chunk.text) for chunk in folder_chunks),
                "chunk_count": len(folder_chunks),
                "folder_item_count": len(resource.source_items),
                "folder_item_preview": list(resource.source_items[:4]),
            }
            self.registry.attach_chunks(
                resource.id,
                folder_chunks,
                summary=summary.text_preview,
                metadata_updates=metadata_updates,
            )
            self.registry.mark_indexed(resource.id, index_status=IndexStatus.NOT_INDEXED)
            return self._ingestion_result(resource.id, summary, folder_chunks, folder_warnings)
        return self.ingestor.ingest(base_request, vision_enabled=False)

    def _is_folder_resource(self, resource: ApiResourceRecord) -> bool:
        if resource.source_items:
            return True
        if resource.source_type == "folder":
            return True
        local_path = self._local_source_path(resource.source)
        return bool(local_path is not None and local_path.exists() and local_path.is_dir())

    def build_requested_resource_context(
        self,
        workspace_id: str,
        resource_ids: list[str],
        *,
        max_items: int = 4,
        summary_chars: int = 220,
    ) -> dict[str, object]:
        normalized_ids: list[str] = []
        seen_ids: set[str] = set()
        for resource_id in resource_ids:
            resource_key = str(resource_id).strip()
            if not resource_key or resource_key in seen_ids:
                continue
            seen_ids.add(resource_key)
            normalized_ids.append(resource_key)

        if not normalized_ids:
            return {}

        resources_by_id = {
            item.id: item for item in self.repository.list_resources(workspace_id)
        }
        requested_resources: list[dict[str, object]] = []
        requested_fragments: list[dict[str, object]] = []
        missing_resource_ids: list[str] = []
        requested_resource_paths: list[str] = []
        seen_duplicate_keys: set[str] = set()
        seen_fragment_signatures: set[str] = set()
        for resource_id in normalized_ids:
            resource = resources_by_id.get(resource_id)
            if resource is None:
                missing_resource_ids.append(resource_id)
                continue
            if self._is_folder_resource(resource):
                self._validate_folder_source_items(resource.source, resource.source_items)
            duplicate_key = resource.duplicate_key.strip()
            if duplicate_key and duplicate_key in seen_duplicate_keys:
                continue
            if duplicate_key:
                seen_duplicate_keys.add(duplicate_key)
            summary = self._resource_summary_text(resource, max_chars=summary_chars)
            resource_paths = self._resource_context_paths(resource, limit=8)
            requested_resource_paths.extend(resource_paths)
            requested_resources.append(
                {
                    "id": resource.id,
                    "title": resource.name.strip() or resource.id,
                    "kind": resource.kind,
                    "summary": summary,
                    "source": resource.canonical_source or resource.source,
                    "trust_score": f"{resource.trust_score:.2f}",
                    "freshness": resource.freshness,
                    "source_type": resource.source_type,
                    "source_items": resource_paths,
                    "item_count": len(resource.source_items),
                }
            )
            for fragment in resource.knowledge_fragments[:2]:
                if isinstance(fragment, dict):
                    signature = self._fragment_signature(fragment)
                    if signature in seen_fragment_signatures:
                        continue
                    seen_fragment_signatures.add(signature)
                    normalized_fragment = self._materialize_fragment(resource, fragment)
                    if normalized_fragment is None:
                        continue
                    requested_fragments.append(normalized_fragment)

        visible_resources = requested_resources[:max_items]
        context: dict[str, object] = {
            "requested_resource_ids": normalized_ids,
            "requested_resources": visible_resources,
            "requested_resource_count": len(requested_resources),
        }
        if visible_resources:
            context["requested_resource_summary"] = "; ".join(
                self._format_context_resource(item) for item in visible_resources
            )
        if requested_resource_paths:
            context["requested_resource_paths"] = self._dedupe_text(
                requested_resource_paths,
                limit=12,
            )
        if requested_fragments:
            context["resource_fragments"] = requested_fragments[:4]
        if missing_resource_ids:
            context["missing_resource_ids"] = missing_resource_ids
        return context

    def build_workspace_understanding_context(
        self,
        workspace_id: str,
        resource_ids: list[str],
        *,
        max_items: int = 100,
    ) -> dict[str, object]:
        requested = self.build_requested_resource_context(
            workspace_id,
            resource_ids,
            max_items=max_items,
            summary_chars=260,
        )
        if not requested:
            return {}
        requested_resources_value = requested.get("requested_resources")
        fragments_value = requested.get("resource_fragments")
        requested_paths_value = requested.get("requested_resource_paths")
        requested_resources = requested_resources_value if isinstance(requested_resources_value, list) else []
        fragments = fragments_value if isinstance(fragments_value, list) else []
        requested_paths = requested_paths_value if isinstance(requested_paths_value, list) else []
        entry_points: list[str] = []
        feature_lanes: list[str] = []
        risk_zones: list[str] = []
        training_opportunities: list[str] = []
        resource_names: list[str] = []
        code_paths: list[str] = []
        note_paths: list[str] = []
        test_paths: list[str] = []
        other_paths: list[str] = []
        if isinstance(requested_paths, list):
            for path in requested_paths[:max_items]:
                normalized_path = str(path or "").strip()
                if not normalized_path:
                    continue
                entry_points.append(normalized_path)
                path_kind = self._resource_path_kind(normalized_path)
                if path_kind == "code":
                    code_paths.append(normalized_path)
                elif path_kind == "note":
                    note_paths.append(normalized_path)
                elif path_kind == "test":
                    test_paths.append(normalized_path)
                else:
                    other_paths.append(normalized_path)
        if isinstance(requested_resources, list):
            for item in requested_resources[:max_items]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "") or "").strip()
                summary = str(item.get("summary", "") or "").strip()
                source = str(item.get("source", "") or "").strip()
                source_items = item.get("source_items", [])
                if title:
                    resource_names.append(title)
                    if title not in entry_points and not source_items:
                        entry_points.append(title)
                if source and source not in entry_points:
                    entry_points.append(source)
                if summary:
                    feature_lanes.append(summary)
                    if len(training_opportunities) < 4:
                        training_opportunities.append(summary)
                if isinstance(source_items, list):
                    for source_item in source_items[:4]:
                        source_item_text = str(source_item or "").strip()
                        if not source_item_text:
                            continue
                        entry_points.append(source_item_text)
        if code_paths:
            feature_lanes.append(f"Start from {code_paths[0]} as the first attached implementation boundary.")
            training_opportunities.append(f"Use {code_paths[0]} as the first attached implementation lane.")
            if len(code_paths) >= 2:
                feature_lanes.append(
                    f"Keep the first cut inside {code_paths[0]} before widening to {code_paths[1]}."
                )
        if note_paths:
            feature_lanes.append(f"Use {note_paths[0]} as the first explanation or spec anchor.")
            if code_paths:
                training_opportunities.append(
                    f"Cross-check {note_paths[0]} against {code_paths[0]} before widening the patch."
                )
        if test_paths:
            training_opportunities.append(f"Use {test_paths[0]} as the first verification anchor.")
        if len(entry_points) >= 5:
            risk_zones.append(
                "Attached resources span multiple files, so the first coaching step should stay inside one boundary."
            )
        if code_paths and note_paths:
            risk_zones.append(
                "The attached material mixes implementation and notes, so confirm whether the first move is code-facing or explanation-facing."
            )
        if isinstance(fragments, list):
            for fragment in fragments[:max_items]:
                if not isinstance(fragment, dict):
                    continue
                snippet = str(fragment.get("snippet", "") or "").strip()
                why = str(fragment.get("why_it_matters", "") or "").strip()
                if snippet:
                    training_opportunities.append(snippet)
                if why:
                    risk_zones.append(why)
        entry_points = self._dedupe_text(entry_points, limit=4)
        feature_lanes = self._dedupe_text(feature_lanes, limit=4)
        risk_zones = self._dedupe_text(risk_zones, limit=4)
        training_opportunities = self._dedupe_text(training_opportunities, limit=6)
        repo_summary = ""
        if resource_names:
            repo_summary = f"Attached resources: {', '.join(resource_names[:4])}."
        if requested_paths:
            repo_summary = (
                f"{repo_summary} Attached file anchors: {', '.join(self._dedupe_text([str(item) for item in requested_paths], limit=3))}."
            ).strip()
        if requested.get("requested_resource_summary"):
            repo_summary = f"{repo_summary} {requested['requested_resource_summary']}".strip()
        return {
            "repo_summary": repo_summary.strip(),
            "entry_points": entry_points,
            "feature_lanes": feature_lanes,
            "risk_zones": risk_zones,
            "training_opportunities": training_opportunities,
            "resource_brief": str(requested.get("requested_resource_summary") or "").strip(),
        }

    def _require_workspace_resource(self, workspace_id: str, resource_id: str) -> ApiResourceRecord:
        for item in self.repository.list_resources(workspace_id):
            if item.id == resource_id:
                return item
        raise KeyError(f"Unknown resource_id: {resource_id}")

    def _resolved_workspace_path(self, workspace_id: str) -> Path | None:
        if self._workspace_path_resolver is None:
            return None
        resolved = self._workspace_path_resolver(workspace_id)
        normalized = str(resolved or "").strip()
        if not normalized:
            return None
        return Path(normalized).expanduser().resolve(strict=False)

    def _search_index_path(self, workspace_id: str) -> Path:
        safe_workspace = self._safe_slug(workspace_id) or "workspace"
        return self.data_root / "search-indexes" / safe_workspace / "index.sqlite3"

    def _inline_resource_root(self, workspace_id: str) -> Path:
        safe_workspace = self._safe_slug(workspace_id) or "workspace"
        return self.data_root / "inline-resources" / safe_workspace

    def _is_managed_inline_source(self, workspace_id: str, source: str) -> bool:
        local_path = self._local_source_path(source)
        if local_path is None:
            return False
        inline_root = self._inline_resource_root(workspace_id).resolve(strict=False)
        try:
            local_path.resolve(strict=False).relative_to(inline_root)
        except ValueError:
            return False
        return True

    def _is_managed_sandbox_source(self, workspace_id: str, source: str) -> bool:
        """Allow indexing files previously copied into Trainer's own sandbox."""

        local_path = self._local_source_path(source)
        if local_path is None:
            return False
        safe_workspace = self._safe_slug(workspace_id) or "workspace"
        sandbox_root = (self.data_root / "sandboxes" / safe_workspace).resolve(strict=False)
        try:
            local_path.resolve(strict=False).relative_to(sandbox_root)
        except ValueError:
            return False
        return True

    def _search_index(self, workspace_id: str) -> SearchIndex:
        database_path = self._search_index_path(workspace_id)
        cache_key = str(database_path.resolve(strict=False)).lower()
        cached = self._search_indexes.get(cache_key)
        if cached is not None:
            return cached
        created = SearchIndex(database_path)
        self._search_indexes[cache_key] = created
        return created

    def _search_index_for_workspace(self, workspace_id: str) -> SearchIndex:
        return self._search_index(workspace_id)

    def _index_search_resource(
        self,
        workspace_id: str,
        resource: ApiResourceRecord,
        *,
        combined_text: str,
        chunks: list[ResourceChunk],
    ) -> None:
        preview_tier, preview_kind, source_extension = self._search_preview_metadata(resource)
        content = (
            combined_text.strip()
            or "\n\n".join(chunk.text for chunk in chunks if chunk.text).strip()
            or resource.summary
            or resource.name
        )
        search_path = str(resource.sandbox_path or resource.source or "")
        self._search_index(workspace_id).index_document(
            path=search_path,
            title=resource.name,
            content=content,
            resource_id=resource.id,
            metadata={
                "project_scope": workspace_id,
                "trust_score": resource.trust_score,
                "trust_state": self._search_trust_state(resource),
                "file_type": self._search_file_type(resource),
                "source_type": resource.source_type,
                "index_state": resource.index_status,
                "summary": resource.summary,
                "source": resource.canonical_source or resource.source,
                "sandbox_path": resource.sandbox_path or "",
                "kind": resource.kind,
                "symbols": [],
                "updated_at": resource.fetched_at or datetime.now(UTC).isoformat(),
                "freshness": resource.freshness,
                "resource_freshness": resource.freshness,
                "resource_preview_tier": preview_tier,
                "resource_preview_kind": preview_kind,
                "resource_source_extension": source_extension,
            },
        )

    def _search_file_type(self, resource: ApiResourceRecord) -> str:
        suffix = self._source_extension(resource.sandbox_path or resource.source)
        if suffix:
            return suffix.lstrip(".")
        return resource.kind

    def _search_trust_state(self, resource: ApiResourceRecord) -> str:
        blocking_flags = {
            "duplicate",
            "source_conflict",
            "fetch_failed",
            "blocked_source",
            "network_disabled",
            "placeholder",
            "no_content",
        }
        if resource.index_status == "failed" or any(flag in blocking_flags for flag in resource.quality_flags):
            return "blocked"
        if resource.trust_score >= 0.7:
            return "trusted"
        if resource.trust_score >= 0.35:
            return "review"
        return "unverified"

    def _search_preview_metadata(self, resource: ApiResourceRecord) -> tuple[str, str, str]:
        suffix = self._source_extension(resource.source)
        preview_kind = "text"
        preview_tier = "rich"

        if suffix in {".csv", ".tsv", ".xlsx", ".xls", ".xlsm", ".ods"}:
            preview_kind = "table"
        elif suffix in {".pdf", ".docx", ".docm", ".pptx", ".pptm", ".epub", ".eml", ".odt", ".odp", ".rtf"}:
            preview_kind = "document"
            preview_tier = "converted"
        elif suffix in {".zip", ".tar", ".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".7z", ".rar"}:
            preview_kind = "archive"
            preview_tier = "converted"
        elif suffix == ".ipynb":
            preview_kind = "notebook"
        elif suffix in {".html", ".htm", ".xml"}:
            preview_kind = "markup"
        elif resource.kind == "image":
            preview_kind = "image"
            preview_tier = "metadata"
        elif resource.kind == "markdown":
            preview_kind = "markdown"
        elif resource.kind == "code":
            preview_kind = "code"
        elif resource.kind == "url":
            preview_kind = "document"
            preview_tier = "converted"

        return preview_tier, preview_kind, suffix

    def _source_extension(self, source: str) -> str:
        normalized = str(source or "").strip().lower()
        for compound in (".tar.gz", ".tar.bz2", ".tar.xz"):
            if normalized.endswith(compound):
                return compound
        return Path(normalized).suffix.lower()

    def _resolved_workspace_root(self, workspace_path: str | None) -> Path | None:
        normalized = str(workspace_path or "").strip()
        if not normalized or "://" in normalized:
            return None
        root = Path(normalized).expanduser().resolve(strict=False)
        if not root.exists() or not root.is_dir():
            return None
        return root

    def _validate_source_within_workspace(
        self,
        source: str,
        workspace_root: Path,
        *,
        source_type: str = "file",
    ) -> None:
        local_path = self._local_source_path(source)
        if local_path is None:
            return
        if not local_path.exists():
            raise FileNotFoundError(f"Local resource source does not exist: {local_path}")
        normalized = local_path.resolve(strict=False)
        try:
            normalized.relative_to(workspace_root.resolve(strict=False))
        except ValueError as exc:
            raise PermissionError(
                f"Resource source must stay within the active workspace root: {normalized}"
            ) from exc
        if source_type == "folder" and not normalized.is_dir():
            raise NotADirectoryError(f"Local resource source must point to a folder: {normalized}")

    def _materialize_inline_content(
        self,
        workspace_id: str,
        request: ResourceUploadRequest,
    ) -> ResourceUploadRequest:
        inline_content = request.content
        if not inline_content or request.kind == "url":
            return request

        normalized_source = str(request.source or "").strip()
        has_real_local_source = False
        if normalized_source:
            local_path = self._local_source_path(normalized_source)
            has_real_local_source = local_path is not None and local_path.exists()

        if has_real_local_source:
            return request

        suffix = self._resource_suffix(request.kind, request.name, normalized_source)
        safe_name = self._safe_slug(request.name) or "resource"
        materialized_dir = self._inline_resource_root(workspace_id)
        materialized_dir.mkdir(parents=True, exist_ok=True)
        file_path = materialized_dir / f"{safe_name}-{uuid4().hex[:8]}{suffix}"
        encoding = request.content_encoding or "utf-8"
        if encoding == "base64":
            file_path.write_bytes(base64.b64decode(inline_content))
        else:
            file_path.write_text(inline_content, encoding="utf-8")
        return request.model_copy(
            update={"source": str(file_path), "content": None, "content_encoding": None}
        )

    def _validate_source(self, source: str, *, source_type: str = "file") -> None:
        local_path = self._local_source_path(source)
        if local_path is None:
            return
        if not local_path.exists():
            raise FileNotFoundError(f"Local resource source does not exist: {local_path}")
        if local_path.is_dir() and source_type != "folder":
            raise IsADirectoryError(f"Local resource source must point to a file, not a directory: {local_path}")
        if source_type == "folder" and not local_path.is_dir():
            raise NotADirectoryError(f"Local resource source must point to a folder: {local_path}")

    def _validate_folder_source_items(self, source: str, source_items: list[str] | None) -> None:
        folder_path = self._local_source_path(source)
        if folder_path is None:
            raise ValueError("Folder resource source must be a local filesystem path.")
        if not folder_path.exists():
            raise FileNotFoundError(f"Local resource source does not exist: {folder_path}")

        folder_root = folder_path.resolve(strict=True)
        if not folder_root.is_dir():
            raise NotADirectoryError(f"Local resource source must point to a folder: {folder_root}")

        for source_item in self._normalize_source_items(source_items):
            item_path = self._local_source_path(source_item)
            if item_path is None:
                raise ValueError("Folder resource source items must be local filesystem paths.")
            if not item_path.exists():
                raise FileNotFoundError(f"Folder resource source item does not exist: {item_path}")

            resolved_item = item_path.resolve(strict=True)
            try:
                resolved_item.relative_to(folder_root)
            except ValueError as exc:
                raise PermissionError(
                    "Folder resource source item must stay within its declared folder root: "
                    f"{resolved_item}"
                ) from exc

    @staticmethod
    def _normalize_collection_path(value: str | None) -> str | None:
        if value is None:
            return None

        candidate = value.strip()
        if not candidate:
            raise ValueError("collection_path must be a non-empty POSIX relative file path.")
        if "\\" in candidate or "\x00" in candidate:
            raise ValueError("collection_path must use safe POSIX path separators.")
        if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate) or "://" in candidate:
            raise ValueError("collection_path must be relative to its resource collection.")

        parts = candidate.split("/")
        if any(not part or part in {".", ".."} for part in parts):
            raise ValueError("collection_path must not contain empty, current, or parent segments.")

        normalized = PurePosixPath(*parts).as_posix()
        if normalized in {"", "."} or PurePosixPath(normalized).is_absolute():
            raise ValueError("collection_path must be a non-empty POSIX relative file path.")
        return normalized

    def _normalize_collection_root(self, value: str | None) -> str | None:
        if value is None:
            return None

        candidate = str(value).strip()
        if not candidate:
            raise ValueError("collection_root must be a non-empty local directory path.")

        root = self._local_source_path(candidate)
        if root is None:
            raise ValueError("collection_root must be a local filesystem directory.")
        absolute_root = Path(os.path.abspath(str(root))).expanduser()
        if not absolute_root.exists() or not absolute_root.is_dir():
            raise ValueError("collection_root must point to an existing local directory.")
        return str(absolute_root)

    def _validate_collection_identity(
        self,
        source: str,
        *,
        collection_path: str | None,
        collection_root: str | None,
    ) -> None:
        if (collection_path is None) != (collection_root is None):
            raise ValueError(
                "collection_path and collection_root must be supplied together to prove a resource collection."
            )
        if collection_path is None or collection_root is None:
            return

        source_path = self._local_source_path(source)
        if source_path is None or not source_path.exists():
            raise ValueError("collection_root requires a local resource source.")

        resolved_source = source_path.resolve(strict=True)
        root_path = Path(collection_root)
        resolved_root = root_path.resolve(strict=True)
        try:
            relative_source = resolved_source.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("Resource source must stay within collection_root.") from exc

        expected_path = PurePosixPath(root_path.name, *relative_source.parts).as_posix()
        if not self._collection_paths_match(collection_path, expected_path):
            raise ValueError(
                "collection_path must match collection_root basename and the source-relative path."
            )

    def _ensure_registry_resource(self, resource: ApiResourceRecord) -> ResourceRecord:
        """Rehydrate the transient ingest registry from the durable resource record when needed."""
        existing = self.registry.get(resource.id)
        if existing is not None:
            return existing
        return self.registry.register(
            ResourceRecord(
                id=resource.id,
                kind=ResourceKind(resource.kind),
                source_uri=resource.source,
                title=resource.name,
                summary=resource.summary,
                metadata={
                    "tags": list(resource.tags),
                    "source_items": list(resource.source_items),
                    "collection_path": resource.collection_path,
                    "collection_root": resource.collection_root,
                    "source_declaration": resource.source_declaration.model_dump(mode="json"),
                    "source_governance": resource.source_governance.model_dump(mode="json"),
                },
            )
        )

    @staticmethod
    def _collection_paths_match(value: str, expected: str) -> bool:
        return value == expected

    def _local_source_path(self, source: str) -> Path | None:
        normalized = str(source or "").strip()
        if not normalized:
            return None
        if normalized.startswith(("http://", "https://")):
            return None

        parsed = urlparse(normalized)
        if parsed.scheme == "file":
            raw_path = unquote(parsed.path or "")
            netloc = unquote(parsed.netloc or "")
            if netloc and netloc.lower() != "localhost":
                if len(netloc) == 2 and netloc[0].isalpha() and netloc[1] == ":":
                    raw_path = f"{netloc}{raw_path}"
                else:
                    raw_path = f"//{netloc}{raw_path}"
            if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[1].isalpha() and raw_path[2] == ":":
                raw_path = raw_path[1:]
            if not raw_path:
                raise ValueError("Local file URL must include a filesystem path.")
            return Path(raw_path).expanduser()
        if len(parsed.scheme) == 1 and len(normalized) >= 2 and normalized[1] == ":":
            return Path(normalized).expanduser()
        if parsed.scheme:
            return None
        return Path(normalized).expanduser()

    def _resource_summary_text(self, resource: ApiResourceRecord, *, max_chars: int) -> str:
        primary = (resource.summary or "").strip()
        if primary:
            return self._truncate(primary, max_chars=max_chars)
        source_hint = self._source_hint(resource.source)
        if resource.index_status == "indexed":
            fallback = f"Indexed {resource.kind} resource"
        elif resource.parse_status == "failed" or resource.index_status == "failed":
            fallback = f"{resource.kind} resource failed to process"
        elif source_hint:
            fallback = f"{resource.kind} resource from {source_hint}"
        else:
            fallback = f"{resource.kind} resource attached"
        return self._truncate(fallback, max_chars=max_chars)

    def _dedupe_text(self, values: list[str], *, limit: int) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = str(value or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            deduped.append(cleaned)
            if len(deduped) >= limit:
                break
        return deduped

    def _format_context_resource(self, resource: Mapping[str, object]) -> str:
        title = resource.get("title", "Untitled resource")
        kind = resource.get("kind", "resource")
        summary = resource.get("summary", "")
        trust = resource.get("trust_score", "")
        freshness = resource.get("freshness", "")
        trailer = f" [trust {trust}, {freshness}]" if trust or freshness else ""
        return f"{title} ({kind}): {summary}{trailer}" if summary else f"{title} ({kind}){trailer}"

    def _source_hint(self, source: str) -> str:
        local_path = self._local_source_path(source)
        if local_path is not None:
            return local_path.name or str(local_path)
        parsed = urlparse(source)
        if parsed.scheme and parsed.scheme != "file":
            return parsed.netloc or source
        return Path(source).name or source

    def _truncate(self, value: str, *, max_chars: int) -> str:
        text = " ".join(value.split())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"

    def _resource_suffix(self, kind: str, name: str, source: str) -> str:
        name_suffix = Path(name).suffix.lower()
        if name_suffix:
            return name_suffix
        source_suffix = Path(source).suffix.lower()
        if source_suffix:
            return source_suffix
        return {
            "markdown": ".md",
            "code": ".txt",
            "text": ".txt",
            "pdf": ".pdf",
            "image": ".txt",
        }.get(kind, ".txt")

    def _normalize_source_items(self, source_items: list[str] | None) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in source_items or []:
            cleaned = str(item or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
            if len(normalized) >= 100:
                break
        return normalized

    def _resource_context_paths(
        self,
        resource: ApiResourceRecord,
        *,
        limit: int,
    ) -> list[str]:
        normalized_items = self._normalize_source_items(resource.source_items)
        if not normalized_items:
            return []
        labels: list[str] = []
        seen: set[str] = set()
        for source_item in normalized_items:
            label = self._relative_source_item_label(resource.source, source_item)
            if not label or label in seen:
                continue
            seen.add(label)
            labels.append(label)
            if len(labels) >= limit:
                break
        return labels

    def _relative_source_item_label(self, source: str, source_item: str) -> str:
        item_path = self._local_source_path(source_item)
        if item_path is None:
            return self._truncate(str(source_item or "").strip(), max_chars=96)
        try:
            base_path = self._local_source_path(source)
        except ValueError:
            base_path = None
        if base_path is not None and base_path.exists() and base_path.is_dir():
            try:
                relative = item_path.relative_to(base_path)
                return f"{base_path.name}/{relative.as_posix()}"
            except ValueError:
                pass
        return self._path_tail(item_path.as_posix(), depth=3)

    def _path_tail(self, value: str, *, depth: int) -> str:
        parts = [part for part in value.replace("\\", "/").split("/") if part]
        if not parts:
            return value
        if len(parts) <= depth:
            return "/".join(parts)
        return "/".join(parts[-depth:])

    def _resource_path_kind(self, path: str) -> str:
        lowered = path.lower()
        suffix = Path(lowered).suffix
        if "test" in lowered:
            return "test"
        if suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".toml", ".go", ".rs"}:
            return "code"
        if suffix in {".md", ".markdown", ".txt", ".rst"}:
            return "note"
        return "other"

    def _ingestion_result(
        self,
        resource_id: str,
        summary: IngestionSummary,
        chunks: list[ResourceChunk],
        warnings: list[str],
    ) -> IngestionResult:
        return IngestionResult(
            record=self.registry.clone_resource(resource_id),
            chunks=chunks,
            summary=summary,
            warnings=warnings,
            vision_payload=None,
        )

    def _safe_slug(self, value: str) -> str:
        return "".join(character if character.isalnum() else "-" for character in value.lower()).strip("-")

    def _network_fetch_enabled(self, requested: bool | None) -> bool:
        return bool(requested) and self.enable_network_fetch

    def _source_type(self, kind: str, source: str) -> str:
        if kind == "url":
            parsed = urlparse(source)
            host = parsed.netloc or source
            return f"url:{host}"
        return f"local:{kind}"

    def _initial_freshness(self, kind: str, source: str) -> Literal["fresh", "stale", "unknown"]:
        return self._freshness(kind, source, fetched_at=None)

    def _freshness(
        self,
        kind: str,
        source: str,
        *,
        fetched_at: str | None,
    ) -> Literal["fresh", "stale", "unknown"]:
        if kind == "url":
            return "fresh" if fetched_at else "unknown"
        local_path = self._local_source_path(source)
        if local_path is None or not local_path.exists():
            return "unknown"
        modified_at = datetime.fromtimestamp(local_path.stat().st_mtime, tz=UTC)
        if datetime.now(UTC) - modified_at > timedelta(days=365):
            return "stale"
        return "fresh"

    def _canonical_source(self, source: str) -> str:
        local_path = self._local_source_path(source)
        if local_path is not None:
            return str(local_path)
        parsed = urlparse(source)
        if parsed.scheme and parsed.scheme != "file":
            path = parsed.path or "/"
            return f"{parsed.scheme}://{parsed.netloc}{path}"
        return str(Path(source).expanduser())

    def _duplicate_key(
        self,
        kind: str,
        source: str,
        chunks: list[ResourceChunk],
    ) -> str:
        canonical = self._canonical_source(source)
        text_seed = "\n".join(chunk.text for chunk in chunks[:3] if chunk.text)
        digest = sha1(text_seed.encode("utf-8")).hexdigest()[:16] if text_seed else "no-content"
        return f"{kind}:{canonical}:{digest}"

    def _quality_flags(
        self,
        kind: str,
        warnings: list[str],
        *,
        network_allowed: bool,
        freshness: str,
        extracted_characters: int,
        chunks: list[ResourceChunk],
    ) -> list[str]:
        flags: list[str] = []
        warning_blob = " ".join(warnings).lower()
        if kind == "url" and not network_allowed:
            flags.append("network_disabled")
        if "fetch failed" in warning_blob:
            flags.append("fetch_failed")
        if "fetch blocked" in warning_blob or "not allowed" in warning_blob:
            flags.append("blocked_source")
        if "placeholder" in warning_blob:
            flags.append("placeholder")
        if "vision capability disabled" in warning_blob:
            flags.append("vision_disabled")
        if freshness == "stale":
            flags.append("stale")
        if not any(chunk.text.strip() for chunk in chunks):
            flags.append("no_content")
        elif extracted_characters < 24:
            flags.append("thin_content")
        return flags

    def _trust_score(self, kind: str, quality_flags: list[str]) -> float:
        base = 0.84 if kind in {"markdown", "code", "text", "pdf"} else 0.74 if kind == "url" else 0.55
        if "network_disabled" in quality_flags:
            base -= 0.4
        if "fetch_failed" in quality_flags:
            base -= 0.55
        if "blocked_source" in quality_flags:
            base -= 0.6
        if "placeholder" in quality_flags:
            base -= 0.22
        if "vision_disabled" in quality_flags:
            base -= 0.1
        if "stale" in quality_flags:
            base -= 0.12
        if "thin_content" in quality_flags:
            base -= 0.08
        if "no_content" in quality_flags:
            base -= 0.25
        if "source_conflict" in quality_flags:
            base -= 0.18
        if "duplicate" in quality_flags:
            base -= 0.05
        return max(0.05, min(round(base, 2), 0.99))

    def _knowledge_fragments(
        self,
        *,
        resource: ApiResourceRecord,
        canonical_source: str,
        trust_score: float,
        freshness: str,
        chunks: list[ResourceChunk],
        quality_flags: list[str],
        duplicate_key: str,
    ) -> list[dict[str, Any]]:
        blocking_flags = {"duplicate", "source_conflict", "fetch_failed", "blocked_source", "network_disabled", "placeholder", "no_content"}
        if any(flag in blocking_flags for flag in quality_flags):
            return []
        fragments: list[dict[str, Any]] = []
        for chunk in chunks[:3]:
            snippet = self._truncate(chunk.text.strip(), max_chars=180)
            if not snippet:
                continue
            fragments.append(
                {
                    "id": chunk.chunk_id,
                    "resource_id": resource.id,
                    "title": resource.name.strip() or resource.id,
                    "snippet": snippet,
                    "summary": self._truncate(snippet, max_chars=96),
                    "evidence_summary": self._truncate(
                        self._evidence_summary(chunk.text, title=resource.name),
                        max_chars=160,
                    ),
                    "source": canonical_source,
                    "source_type": resource.source_type or self._source_type(resource.kind, resource.source),
                    "kind": resource.kind,
                    "trust_score": trust_score,
                    "freshness": freshness,
                    "fetched_at": datetime.now(UTC).isoformat() if resource.kind == "url" else None,
                    "duplicate_key": duplicate_key,
                    "quality_flags": list(quality_flags),
                    "focus_area": resource.name.strip() or resource.kind,
                    "line_start": chunk.start_line,
                    "line_end": chunk.end_line,
                    "why_it_matters": self._why_it_matters(resource, chunk),
                }
            )
        return fragments

    def _canonical_resource_for_duplicate_key(
        self,
        workspace_id: str,
        duplicate_key: str,
        *,
        exclude_id: str,
    ) -> ApiResourceRecord | None:
        for item in self.repository.list_resources(workspace_id):
            if item.id == exclude_id:
                continue
            if item.duplicate_key == duplicate_key:
                return item
        return None

    def _conflicting_resource_for_source(
        self,
        workspace_id: str,
        *,
        kind: str,
        canonical_source: str,
        duplicate_key: str,
        exclude_id: str,
    ) -> ApiResourceRecord | None:
        for item in self.repository.list_resources(workspace_id):
            if item.id == exclude_id:
                continue
            if item.kind != kind:
                continue
            if item.canonical_source != canonical_source:
                continue
            if not item.duplicate_key or item.duplicate_key == duplicate_key:
                continue
            return item
        return None

    def _append_unique(self, existing: list[str], extra: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for value in [*existing, *extra]:
            cleaned = str(value or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            merged.append(cleaned)
        return merged

    def dedupe_resources(self, resources: list[ApiResourceRecord]) -> list[ApiResourceRecord]:
        deduped: list[ApiResourceRecord] = []
        seen_ids: set[str] = set()
        seen_duplicate_keys: set[str] = set()
        for resource in resources:
            if resource.id in seen_ids:
                continue
            seen_ids.add(resource.id)
            duplicate_key = resource.duplicate_key.strip()
            if duplicate_key and duplicate_key in seen_duplicate_keys:
                continue
            if duplicate_key:
                seen_duplicate_keys.add(duplicate_key)
            deduped.append(resource)
        return deduped

    def top_knowledge_fragments(
        self,
        workspace_id: str,
        *,
        max_fragments: int = 8,
    ) -> list[dict[str, Any]]:
        resources = self.dedupe_resources(self.repository.list_resources(workspace_id))
        ranked = sorted(
            resources,
            key=self._resource_rank_key,
        )
        fragments: list[dict[str, Any]] = []
        seen_fragment_signatures: set[str] = set()
        for resource in ranked:
            if not self._resource_is_curatable(resource):
                continue
            for fragment in resource.knowledge_fragments:
                if not isinstance(fragment, dict):
                    continue
                normalized_fragment = self._materialize_fragment(resource, fragment)
                if normalized_fragment is None:
                    continue
                signature = self._fragment_signature(normalized_fragment)
                if signature in seen_fragment_signatures:
                    continue
                seen_fragment_signatures.add(signature)
                fragments.append(normalized_fragment)
                if len(fragments) >= max_fragments:
                    return fragments
        return fragments

    def curated_background_references(
        self,
        workspace_id: str,
        *,
        max_fragments: int = 6,
        focus_area: str | None = None,
    ) -> list[dict[str, Any]]:
        resources = self.dedupe_resources(self.repository.list_resources(workspace_id))
        ranked_resources = sorted(
            resources,
            key=lambda item: self._resource_rank_key(item),
        )
        normalized_focus = (focus_area or "").strip().lower()
        fragments: list[dict[str, Any]] = []
        seen_fragment_signatures: set[str] = set()
        for resource in ranked_resources:
            if not self._resource_is_curatable(resource):
                continue
            for fragment in resource.knowledge_fragments:
                if not isinstance(fragment, dict):
                    continue
                normalized_fragment = self._materialize_fragment(resource, fragment)
                if normalized_fragment is None:
                    continue
                if normalized_focus and not self._fragment_matches_focus(normalized_fragment, resource, normalized_focus):
                    continue
                signature = self._fragment_signature(normalized_fragment)
                if signature in seen_fragment_signatures:
                    continue
                seen_fragment_signatures.add(signature)
                snippet = str(normalized_fragment.get("snippet", "") or "").strip()
                if not snippet:
                    continue
                fragments.append(normalized_fragment)
                if len(fragments) >= max_fragments:
                    return fragments
        return fragments

    def merge_external_references(
        self,
        *,
        requested_fragments: list[dict[str, object]] | None = None,
        curated_fragments: list[dict[str, object]] | None = None,
        research_findings: list[dict[str, object]] | None = None,
        focus_area: str | None = None,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        normalized_focus = (focus_area or "").strip().lower()
        candidates: list[dict[str, Any]] = []
        for origin, items in (
            ("requested_resource", requested_fragments or []),
            ("curated_resource", curated_fragments or []),
            ("background_research", research_findings or []),
        ):
            for item in items:
                normalized = self._normalize_external_reference(item, origin=origin)
                if normalized is None:
                    continue
                candidates.append(normalized)

        ranked = sorted(
            candidates,
            key=lambda item: self._external_reference_rank_key(item, normalized_focus),
        )
        deduped: list[dict[str, Any]] = []
        seen_signatures: set[str] = set()
        seen_duplicate_keys: set[str] = set()
        for item in ranked:
            duplicate_key = self._normalize_reference_key(str(item.get("duplicate_key", "") or ""))
            if duplicate_key and duplicate_key in seen_duplicate_keys:
                continue
            signature = self._external_reference_content_signature(item)
            if signature and signature in seen_signatures:
                continue
            if duplicate_key:
                seen_duplicate_keys.add(duplicate_key)
            if signature:
                seen_signatures.add(signature)
            deduped.append(item)
            if len(deduped) >= limit:
                break
        return deduped

    def _normalize_external_reference(
        self,
        item: object,
        *,
        origin: str,
    ) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        snippet = self._truncate(str(item.get("snippet", "") or "").strip(), max_chars=180)
        if not snippet:
            return None
        source = str(item.get("source", "") or "").strip()
        title = str(
            item.get("title")
            or item.get("focus_area")
            or item.get("summary")
            or item.get("resource_id")
            or "External reference"
        ).strip()
        source_type = str(item.get("source_type", "") or "").strip()
        if not source_type:
            source_type = self._external_reference_source_type(source, origin=origin)
        freshness = str(item.get("freshness", "") or "").strip()
        if not freshness:
            freshness = "fresh" if origin != "background_research" else "recent"
        quality_flags = [
            str(flag).strip()
            for flag in item.get("quality_flags", [])
            if str(flag).strip()
        ]
        (
            source_governance,
            commercial_reuse_status,
            commercial_reuse_reason_codes,
            governance_quality_flags,
        ) = self._external_reference_governance_audit(
            item,
            source=source,
            source_type=source_type,
        )
        return {
            "id": str(item.get("id", "") or item.get("resource_id", "") or source or snippet[:32]).strip(),
            "resource_id": str(item.get("resource_id", "") or item.get("id", "")).strip(),
            "title": title,
            "snippet": snippet,
            "summary": self._truncate(str(item.get("summary", "") or snippet), max_chars=96),
            "evidence_summary": self._truncate(
                str(item.get("evidence_summary", "") or self._evidence_summary(snippet, title=title)),
                max_chars=160,
            ),
            "source": source,
            "source_type": source_type,
            "kind": str(
                item.get("kind", "research_finding" if origin == "background_research" else "reference")
            ).strip(),
            "trust_score": float(item.get("trust_score", 0.0) or 0.0),
            "freshness": freshness,
            "fetched_at": item.get("fetched_at") or item.get("created_at"),
            "created_at": item.get("created_at") or item.get("fetched_at"),
            "duplicate_key": str(item.get("duplicate_key", "") or "").strip(),
            "quality_flags": self._append_unique(
                quality_flags,
                [origin, *governance_quality_flags],
            ),
            "focus_area": str(item.get("focus_area", "") or title or "external reference").strip(),
            "why_it_matters": str(
                item.get("why_it_matters")
                or item.get("fit_reason")
                or item.get("training_value")
                or f"Grounds follow-up coaching with {title}."
            ).strip(),
            "reference_origin": origin,
            "source_governance": source_governance,
            "commercial_reuse_status": commercial_reuse_status,
            "commercial_reuse_reason_codes": commercial_reuse_reason_codes,
        }

    def _external_reference_governance_audit(
        self,
        item: Mapping[str, object],
        *,
        source: str,
        source_type: str,
    ) -> tuple[dict[str, Any] | None, str, list[str], list[str]]:
        source_governance = source_governance_payload(item.get("source_governance"))
        is_external = is_external_reference_source(source, source_type)
        if source_governance is None:
            if not is_external:
                return None, "", [], []
            return (
                None,
                "review_required",
                ["source_governance_missing"],
                [
                    "commercial_reuse_review_required",
                    "commercial_reuse_not_auto_promoted",
                    "source_governance_missing",
                ],
            )

        status = commercial_reuse_governance_status(source_governance)
        raw_reason_codes = source_governance.get("commercial_reuse_reason_codes", [])
        reason_code_values = raw_reason_codes if isinstance(raw_reason_codes, list) else []
        reason_codes = [
            str(code).strip()
            for code in reason_code_values
            if str(code).strip()
        ]
        if status is None:
            status = "review_required"
            reason_codes.append("source_governance_status_invalid")
        elif is_external and status == "eligible":
            eligibility_reasons = commercial_reuse_eligibility_reason_codes(source_governance)
            if eligibility_reasons:
                status = "review_required"
                reason_codes.extend(eligibility_reasons)
        reason_codes = self._append_unique([], reason_codes)
        if not is_external:
            return source_governance, status, reason_codes, []
        status_flag = f"commercial_reuse_{status}"
        reason_flags = [f"source_governance_reason:{code}" for code in reason_codes[:4]]
        if status == "eligible":
            return (
                source_governance,
                status,
                reason_codes,
                [status_flag, "commercial_reuse_eligible", "controlled_source", *reason_flags],
            )
        return (
            source_governance,
            status,
            reason_codes,
            [status_flag, "commercial_reuse_not_auto_promoted", *reason_flags],
        )

    def _external_reference_source_type(self, source: str, *, origin: str) -> str:
        if source.startswith("http://") or source.startswith("https://"):
            return "external:web"
        if source.startswith("teaching-asset://"):
            return "memory:teaching-asset"
        if source.startswith("workspace-understanding://"):
            return "workspace:understanding"
        if origin == "background_research":
            return "research:background"
        return "local:reference"

    def _external_reference_signature(self, item: dict[str, object]) -> str:
        return self._external_reference_content_signature(item)

    def _external_reference_content_signature(self, item: dict[str, object]) -> str:
        source = str(item.get("source", "") or "").strip().lower()
        fingerprint = self._external_reference_fingerprint(str(item.get("snippet", "") or ""))
        if not fingerprint:
            fingerprint = self._external_reference_fingerprint(
                str(item.get("summary", "") or ""),
                str(item.get("why_it_matters", "") or ""),
            )
        digest_source = f"{source}::{fingerprint}" if source else fingerprint
        digest = sha1(digest_source.encode("utf-8")).hexdigest()[:20] if digest_source else "empty"
        return digest

    def _external_reference_fingerprint(self, *parts: str) -> str:
        tokens: list[str] = []
        for part in parts:
            if not part:
                continue
            cleaned = re.findall(r"[a-z0-9]+", part.lower())
            tokens.extend(token for token in cleaned if token not in _REFERENCE_STOPWORDS)
        if not tokens:
            return ""
        return " ".join(tokens[:24])

    def _normalize_reference_key(self, value: str) -> str:
        return " ".join(value.strip().lower().split())

    def _evidence_summary(self, content: str, *, title: str = "") -> str:
        raw = content.strip()
        text = " ".join(raw.split())
        if not text:
            return ""
        prefer_two_sentences = False
        normalized = re.sub(r"^[\ufeff\s#>*-]+", "", raw).strip()
        title_hint = " ".join(title.lower().split())
        normalized_hint = " ".join(normalized.lower().split())
        if title_hint and normalized_hint.startswith(title_hint):
            normalized = normalized[len(title.strip()):].lstrip(" :-—–,.;")
            prefer_two_sentences = True
        elif ":" in normalized:
            head, tail = normalized.split(":", 1)
            if len(head.strip()) < 80 and tail.strip():
                normalized = tail.strip()
                prefer_two_sentences = True
        if "\n" in normalized:
            lines = [line.strip() for line in normalized.splitlines() if line.strip()]
            if len(lines) > 1:
                normalized = " ".join(lines[1:] or lines[:1])
                prefer_two_sentences = True
        if normalized:
            text = normalized
        parts = re.split(r"(?<=[.!?。！？])\s+", text, maxsplit=2)
        sentences = [part.strip() for part in parts if part.strip()]
        if sentences:
            text = " ".join(sentences[:2] if prefer_two_sentences and len(sentences) > 1 else sentences[:1])
        return text[:160]

    def _external_reference_rank_key(
        self,
        item: dict[str, object],
        normalized_focus: str,
    ) -> tuple[object, ...]:
        origin = str(item.get("reference_origin", "") or "").strip()
        origin_rank = {
            "requested_resource": 0,
            "curated_resource": 1,
            "background_research": 2,
        }.get(origin, 3)
        freshness = str(item.get("freshness", "") or "").strip().lower()
        freshness_rank = {
            "fresh": 0,
            "recent": 0,
            "stable": 1,
            "stale": 2,
            "old": 2,
        }.get(freshness, 1)
        raw_quality_flags = item.get("quality_flags", [])
        quality_flag_values = raw_quality_flags if isinstance(raw_quality_flags, list) else []
        quality_flags = {
            str(flag).strip()
            for flag in quality_flag_values
            if str(flag).strip()
        }
        blocking_penalty = 1 if quality_flags.intersection(
            {"duplicate", "source_conflict", "fetch_failed", "blocked_source", "network_disabled", "placeholder", "no_content"}
        ) else 0
        return (
            origin_rank,
            0 if self._external_reference_matches_focus(item, normalized_focus) else 1,
            blocking_penalty,
            -self._float_or_default(item.get("trust_score") or 0.0),
            freshness_rank,
            -self._timestamp_sort_value(item.get("fetched_at") or item.get("created_at")),
            str(item.get("title", "") or "").lower(),
        )

    def _external_reference_matches_focus(
        self,
        item: dict[str, object],
        normalized_focus: str,
    ) -> bool:
        if not normalized_focus:
            return True
        haystack = " ".join(
            [
                str(item.get("title", "") or ""),
                str(item.get("summary", "") or ""),
                str(item.get("snippet", "") or ""),
                str(item.get("focus_area", "") or ""),
                str(item.get("why_it_matters", "") or ""),
            ]
        ).lower()
        return normalized_focus in haystack

    def _timestamp_sort_value(self, value: object) -> float:
        raw = str(value or "").strip()
        if not raw:
            return 0.0
        normalized = raw.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            return 0.0

    @staticmethod
    def _float_or_default(value: object, default: float = 0.0) -> float:
        if not isinstance(value, (str, int, float)):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _fragment_signature(self, fragment: dict[str, object]) -> str:
        snippet = str(fragment.get("snippet", "") or "").strip().lower()
        kind = str(fragment.get("kind", "") or "").strip().lower()
        digest = sha1(snippet.encode("utf-8")).hexdigest()[:16] if snippet else "empty"
        return f"{kind}::{digest}"

    def _resource_rank_key(self, resource: ApiResourceRecord) -> tuple[object, ...]:
        return (
            "duplicate" in resource.quality_flags,
            "source_conflict" in resource.quality_flags,
            "blocked_source" in resource.quality_flags,
            "fetch_failed" in resource.quality_flags,
            "network_disabled" in resource.quality_flags,
            "placeholder" in resource.quality_flags,
            "no_content" in resource.quality_flags,
            -(resource.trust_score or 0.0),
            resource.freshness != "fresh",
            resource.fetched_at or "",
        )

    def _resource_is_curatable(self, resource: ApiResourceRecord) -> bool:
        blocking_flags = {"duplicate", "source_conflict", "fetch_failed", "blocked_source", "network_disabled", "placeholder", "no_content"}
        if any(flag in blocking_flags for flag in resource.quality_flags):
            return False
        return bool(resource.knowledge_fragments and resource.trust_score >= 0.35)

    def is_curatable_resource(self, resource: ApiResourceRecord) -> bool:
        return self._resource_is_curatable(resource)

    def is_commercial_reuse_eligible(self, resource: ApiResourceRecord) -> bool:
        """Return whether source evidence passes the narrow reuse policy.

        This deliberately does not change normal resource-to-learning flows:
        learners may still use their own material. It is the explicit filter for
        promotion or reuse in product-owned commercial material.
        """

        return source_is_commercial_reuse_eligible(resource.source_governance)

    def _materialize_fragment(
        self,
        resource: ApiResourceRecord,
        fragment: dict[str, object],
    ) -> dict[str, Any] | None:
        snippet = self._truncate(str(fragment.get("snippet", "") or "").strip(), max_chars=180)
        if not snippet:
            return None
        raw_quality_flags = fragment.get("quality_flags", [])
        fragment_quality_flags = raw_quality_flags if isinstance(raw_quality_flags, list) else []
        quality_flags = self._append_unique(
            [str(item) for item in resource.quality_flags],
            [item for item in fragment_quality_flags if isinstance(item, str)],
        )
        if any(
            flag in {"duplicate", "source_conflict", "fetch_failed", "blocked_source", "network_disabled", "placeholder", "no_content"}
            for flag in quality_flags
        ):
            return None
        return {
            "id": str(fragment.get("id", "") or resource.id),
            "resource_id": str(fragment.get("resource_id", "") or resource.id),
            "title": str(fragment.get("title", "") or resource.name.strip() or resource.id),
            "snippet": snippet,
            "summary": self._truncate(str(fragment.get("summary", "") or snippet), max_chars=96),
            "evidence_summary": self._truncate(
                str(fragment.get("evidence_summary", "") or self._evidence_summary(snippet, title=resource.name)),
                max_chars=160,
            ),
            "source": str(fragment.get("source", resource.canonical_source or resource.source)),
            "source_type": str(fragment.get("source_type", resource.source_type or self._source_type(resource.kind, resource.source))),
            "kind": str(fragment.get("kind", resource.kind)),
            "trust_score": self._float_or_default(
                fragment.get("trust_score") or resource.trust_score,
                default=resource.trust_score,
            ),
            "freshness": str(fragment.get("freshness", resource.freshness) or resource.freshness),
            "fetched_at": fragment.get("fetched_at", resource.fetched_at),
            "duplicate_key": str(fragment.get("duplicate_key", resource.duplicate_key)),
            "quality_flags": quality_flags,
            "focus_area": str(fragment.get("focus_area", resource.name.strip() or resource.kind)),
            "line_start": fragment.get("line_start"),
            "line_end": fragment.get("line_end"),
            "why_it_matters": str(
                fragment.get("why_it_matters")
                or f"Grounds follow-up coaching with {resource.name}."
            ).strip(),
            "source_governance": resource.source_governance.model_dump(mode="json"),
        }

    def _why_it_matters(self, resource: ApiResourceRecord, chunk: ResourceChunk) -> str:
        title = resource.name.strip() or resource.kind
        if resource.kind == "code" and chunk.start_line and chunk.end_line:
            return f"Shows a concrete implementation slice from {title} lines {chunk.start_line}-{chunk.end_line}."
        if resource.kind == "url":
            return f"Provides grounded external context from {title}."
        if resource.kind == "pdf":
            return f"Captures a reusable excerpt from {title}."
        return f"Grounds follow-up coaching with {title}."

    def _fragment_matches_focus(
        self,
        fragment: dict[str, object],
        resource: ApiResourceRecord,
        normalized_focus: str,
    ) -> bool:
        haystack = " ".join(
            [
                str(resource.name or ""),
                str(resource.summary or ""),
                str(fragment.get("snippet", "") or ""),
                str(fragment.get("why_it_matters", "") or ""),
            ]
        ).lower()
        return normalized_focus in haystack
