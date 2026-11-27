from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any

from ..core.models import ResourceRecord as ApiResourceRecord
from ..core.models import (
    ResourceTrashItem,
)
from ..ingest.models import IngestionRequest, IngestionResult, IngestionSummary
from .canonical import (
    CanonicalDocument,
    CanonicalParseError,
    build_canonical_document,
    build_canonical_from_text,
    canonicalizable,
    plain_text_preview,
)
from .canonical_store import write_canonical_artifact
from .models import (
    IndexStatus,
    ResourceChunk,
    ResourceKind,
)
from .search import SearchIndex
from .service_support import (
    MAX_FOLDER_INGEST_ITEMS,
    _canonical_version_bytes,
    _captured_pdf_source_url,
    _count_markdown_tables,
    _last_anchor_before,
    _original_filename_for,
)

logger = logging.getLogger(__name__)


class CanonicalAndCollectionMixin:
    if TYPE_CHECKING:
        _append_unique: Any
        _dedupe_text: Any
        _ensure_registry_resource: Any
        _format_context_resource: Any
        _fragment_signature: Any
        _has_readable_markdown: Any
        _ingestion_result: Any
        _library_root_resolver: Any
        _local_source_path: Any
        _materialize_fragment: Any
        _normalize_collection_path: Any
        _prepared_canonical: Any
        _record_resource_version: Any
        _resource_context_paths: Any
        _resource_path_kind: Any
        _resource_restore_locks: Any
        _resource_restore_locks_guard: Any
        _resource_summary_text: Any
        _safe_slug: Any
        _search_indexes: Any
        _validate_folder_source_items: Any
        _workspace_path_resolver: Any
        data_root: Any
        ingest_service: Any
        ingestor: Any
        invalidate_search_cache: Any
        registry: Any
        repository: Any
        semantic_memory: Any

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
        self.invalidate_search_cache(workspace_id)

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

    def invalidate_corpus_search_cache(self) -> None:
        """Alias kept explicit at delete/restore call sites (P1 检索复用)."""
        self.invalidate_search_cache()

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
                # Keep historical fragments and their provenance while the
                # resource is tombstoned; re-index may replace them later.
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

    # ------------------------------------------------------------- canonical md

    def analyze_canonical(
        self,
        workspace_id: str,
        resource_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Stage 1-2: recognise the document type and parse its structure.

        Parses each source, reports real counts (pages/slides/images/tables)
        and caches the parsed document for :meth:`materialize_canonical`.
        Nothing is written to the library until materialize runs.
        """

        results: list[dict[str, Any]] = []
        for resource_id in self._normalized_resource_ids(resource_ids):
            item: dict[str, Any] = {"resource_id": resource_id, "ok": False}
            try:
                resource = self._require_workspace_resource(workspace_id, resource_id)
            except KeyError:
                item["error"] = "resource_not_found"
                results.append(item)
                continue
            try:
                source_path = self._local_source_path(resource.source)
                if source_path is None or not source_path.is_file():
                    item["error"] = "source_not_local"
                    results.append(item)
                    continue
                if source_path.suffix.lower() in {".doc", ".ppt", ".xls"}:
                    replacement = {".doc": ".docx", ".ppt": ".pptx", ".xls": ".xlsx"}[
                        source_path.suffix.lower()
                    ]
                    item["error"] = (
                        f"Legacy {source_path.suffix.lower()} files are not supported; "
                        f"save the file as {replacement} and import it again."
                    )
                    results.append(item)
                    continue
                if not canonicalizable(source_path):
                    item["error"] = "unsupported_type"
                    results.append(item)
                    continue
                raw = source_path.read_bytes()
                content_hash = sha256(raw).hexdigest()
                document = build_canonical_document(
                    source_path,
                    resource_id=resource.id,
                    content_hash=f"sha256:{content_hash}",
                    source_url=_captured_pdf_source_url(resource),
                    original_name=_original_filename_for(resource, source_path),
                )
            except (OSError, CanonicalParseError) as exc:
                item["error"] = str(exc)
                if isinstance(exc, CanonicalParseError):
                    item["warnings"] = list(exc.warnings)
                results.append(item)
                continue
            table_count = _count_markdown_tables(document.body)
            self._prepared_canonical[resource.id] = {
                "hash": content_hash,
                "document": document,
                "table_count": table_count,
                "materialized": False,
            }
            item.update(
                {
                    "ok": True,
                    "source_type": document.source_type,
                    "parser": document.parser,
                    "page_count": document.page_count,
                    "slide_count": document.slide_count,
                    "image_count": len(document.assets),
                    "table_count": table_count,
                    "warning_count": len(document.warnings),
                    "warnings": list(document.warnings[:3]),
                }
            )
            results.append(item)
        return results

    def materialize_canonical(
        self,
        workspace_id: str,
        resource_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Stage 3-4: write the canonical Markdown, original and assets."""

        results: list[dict[str, Any]] = []
        workspace_root = self._canonical_writable_root(workspace_id)
        for resource_id in self._normalized_resource_ids(resource_ids):
            item: dict[str, Any] = {"resource_id": resource_id, "ok": False}
            try:
                resource = self._require_workspace_resource(workspace_id, resource_id)
            except KeyError:
                item["error"] = "resource_not_found"
                results.append(item)
                continue
            source_path = self._local_source_path(resource.source)
            if source_path is None or not source_path.is_file():
                item["error"] = "source_not_local"
                results.append(item)
                continue
            try:
                raw = source_path.read_bytes()
            except OSError as exc:
                item["error"] = f"Could not read the source file: {exc}"
                results.append(item)
                continue
            content_hash = sha256(raw).hexdigest()
            prepared = self._prepared_canonical.get(resource.id)
            document = prepared.get("document") if isinstance(prepared, dict) else None
            if (
                document is None
                or not isinstance(prepared, dict)
                or str(prepared.get("hash") or "") != content_hash
            ):
                try:
                    document = build_canonical_document(
                        source_path,
                        resource_id=resource.id,
                        content_hash=f"sha256:{content_hash}",
                        source_url=_captured_pdf_source_url(resource),
                        original_name=_original_filename_for(resource, source_path),
                    )
                except (OSError, CanonicalParseError) as exc:
                    item["error"] = str(exc)
                    results.append(item)
                    continue
            md_bytes = _canonical_version_bytes(document)
            current_version = self._record_resource_version(workspace_id, resource, md_bytes)
            version_id = str((current_version or {}).get("version_id") or "")
            document.version_id = version_id
            if current_version and current_version.get("content_hash"):
                document.content_hash = f"sha256:{current_version['content_hash']}"
            if workspace_root is None:
                item["error"] = "workspace_root_unavailable"
                results.append(item)
                continue
            try:
                artifact = write_canonical_artifact(
                    workspace_root,
                    document,
                    original_bytes=raw,
                    original_filename=_original_filename_for(resource, source_path),
                )
            except OSError as exc:
                item["error"] = f"Canonical Markdown could not be written: {exc}"
                results.append(item)
                continue
            table_count = _count_markdown_tables(document.body)
            self._prepared_canonical[resource.id] = {
                "hash": content_hash,
                "document": document,
                "table_count": table_count,
                "materialized": True,
                "canonical_markdown_path": artifact.markdown_relative,
                "canonical_original_path": artifact.original_relative or "",
                "asset_count": len(document.assets),
            }
            item.update(
                {
                    "ok": True,
                    "markdown_path": artifact.markdown_relative,
                    "original_path": artifact.original_relative or "",
                    "asset_count": len(document.assets),
                    "table_count": table_count,
                    "warnings": list(document.warnings[:3]),
                }
            )
            results.append(item)
        return results

    def _canonical_writable_root(self, workspace_id: str) -> Path | None:
        """Return the local library root (or standalone workspace root) when writable.

        Prefers the Trainer Library Root resolved via ``_library_root_resolver``
        so canonical Markdown and assets never pollute the user's code repo.
        Remote SSH paths without a local library root stay non-writable.
        """
        library_root = self._resolved_library_root(workspace_id)
        if library_root is not None:
            try:
                if library_root.exists() and library_root.is_dir():
                    return library_root
            except OSError:
                pass

        resolved = self._resolved_workspace_path(workspace_id)
        if resolved is None:
            return None
        try:
            if resolved.exists() and resolved.is_dir():
                return resolved
        except OSError:
            return None
        return None

    def _normalized_resource_ids(self, resource_ids: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in resource_ids or []:
            key = str(value or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            normalized.append(key)
            if len(normalized) >= 100:
                break
        return normalized

    def _canonical_local_ingest(
        self,
        workspace_id: str,
        resource: ApiResourceRecord,
    ) -> tuple[IngestionResult, dict[str, Any]] | None:
        """Digest a local document into its canonical Markdown projection.

        Returns ``None`` when the source is not a local file the canonical
        pipeline owns (folders, inline captures, unsupported extensions).
        """

        source_path = self._local_source_path(resource.source)
        if source_path is None or not source_path.is_file():
            return None
        suffix = source_path.suffix.lower()
        if suffix in {".doc", ".ppt", ".xls"}:
            replacement = {".doc": ".docx", ".ppt": ".pptx", ".xls": ".xlsx"}[suffix]
            warning = (
                f"Legacy {suffix} files are not supported; save the file as "
                f"{replacement} and import it again."
            )
            return self._canonical_failure(resource, [warning]), {}
        if not canonicalizable(source_path):
            return None
        try:
            # Probe the source: an unreadable file fails here, before a
            # document is prepared from it.
            source_path.read_bytes()
        except OSError as exc:
            return self._canonical_failure(
                resource,
                [f"Could not read the source file: {exc}"],
            ), {}
        prepared = self._prepared_canonical.get(resource.id)
        prepared_document = (
            prepared.get("document") if isinstance(prepared, dict) else None
        )
        if (
            isinstance(prepared, dict)
            and isinstance(prepared_document, CanonicalDocument)
            and prepared.get("materialized") is True
        ):
            document = prepared_document
            md_bytes = _canonical_version_bytes(document)
            current_version = self._record_resource_version(
                workspace_id, resource, md_bytes
            )
            document.version_id = str((current_version or {}).get("version_id") or "")
            document.content_hash = (
                f"sha256:{str((current_version or {}).get('content_hash') or '')}"
                if (current_version or {}).get("content_hash")
                else document.content_hash
            )
            # analyze + materialize already parsed and wrote this exact
            # content; indexing must not repeat either.
            return self._canonical_result(
                workspace_id,
                resource,
                document,
                original_bytes=md_bytes,
                original_filename=_original_filename_for(resource, source_path),
                prewritten=prepared,
            )
        try:
            document = build_canonical_document(
                source_path,
                resource_id=resource.id,
                source_url=_captured_pdf_source_url(resource),
                original_name=_original_filename_for(resource, source_path),
            )
        except CanonicalParseError as exc:
            return self._canonical_failure(resource, [str(exc), *exc.warnings]), {}
        # md-only: the version identity is the canonical Markdown body, not
        # the binary source or resource-specific front matter.
        md_bytes = _canonical_version_bytes(document)
        current_version = self._record_resource_version(
            workspace_id, resource, md_bytes
        )
        version_id = str((current_version or {}).get("version_id") or "")
        content_hash = str((current_version or {}).get("content_hash") or "")
        document.version_id = version_id
        if content_hash:
            document.content_hash = f"sha256:{content_hash}"
        return self._canonical_result(
            workspace_id,
            resource,
            document,
            original_bytes=md_bytes,
            original_filename=_original_filename_for(resource, source_path),
        )

    def _canonicalize_url_ingest(
        self,
        workspace_id: str,
        resource: ApiResourceRecord,
        ingest_result: IngestionResult,
    ) -> tuple[IngestionResult, dict[str, Any]] | None:
        """Re-project a fetched URL capture into a canonical Markdown snapshot."""

        if resource.kind != "url":
            return None
        provenance = getattr(ingest_result, "source_provenance", {}) or {}
        if str(provenance.get("status") or "") != "fetched":
            return None
        text = "\n\n".join(chunk.text for chunk in ingest_result.chunks if chunk.text).strip()
        if not text:
            return None
        final_url = str(provenance.get("final_url") or resource.source)
        fetched_at = str(provenance.get("fetched_at") or "").strip() or None
        filename = self._url_snapshot_filename(resource.name)
        try:
            document = build_canonical_from_text(
                text,
                resource_id=resource.id,
                original_filename=filename,
                source_url=final_url,
                imported_at=fetched_at,
            )
        except CanonicalParseError:
            return None
        md_bytes = _canonical_version_bytes(document)
        current_version = self._record_resource_version(
            workspace_id, resource, md_bytes
        )
        document.version_id = str((current_version or {}).get("version_id") or "")
        content_hash = str((current_version or {}).get("content_hash") or "")
        if content_hash:
            document.content_hash = f"sha256:{content_hash}"
        return self._canonical_result(
            workspace_id,
            resource,
            document,
            original_bytes=md_bytes,
            original_filename=filename,
            extra_provenance=dict(ingest_result.source_provenance or {}),
        )

    @staticmethod
    def _url_snapshot_filename(name: str) -> str:
        display_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name.strip()).strip() or "capture"
        if not display_name.lower().endswith(".md"):
            display_name = f"{display_name}.md"
        return display_name[:120]

    def _canonical_result(
        self,
        workspace_id: str,
        resource: ApiResourceRecord,
        document: Any,
        *,
        original_bytes: bytes,
        original_filename: str,
        extra_provenance: dict[str, Any] | None = None,
        prewritten: dict[str, Any] | None = None,
    ) -> tuple[IngestionResult, dict[str, Any]]:
        store_warnings: list[str] = []
        canonical_meta: dict[str, Any] = {
            "canonical_markdown_path": "",
            "canonical_original_path": "",
            "parser": document.parser,
            "parser_version": document.parser_version,
            "page_count": document.page_count,
            "slide_count": document.slide_count,
            "source_type": document.source_type,
        }
        if prewritten is not None:
            canonical_meta.update(
                {
                    "canonical_markdown_path": str(
                        prewritten.get("canonical_markdown_path") or ""
                    ),
                    # md-only: never expose a retained binary artifact.
                    "canonical_original_path": "",
                }
            )
        workspace_root = None if prewritten is not None else self._resolved_workspace_path(workspace_id)
        if prewritten is None:
            # Guard here too: index() reaches this helper on every path, and a
            # remote workspace root must never be materialized locally even
            # when a drive-relative reinterpretation of it happens to exist.
            workspace_root = self._canonical_writable_root(workspace_id)
        if prewritten is None and workspace_root is None:
            store_warnings.append(
                "Canonical Markdown was generated but no workspace root is available to store it."
            )
        elif prewritten is None and workspace_root is not None:
            try:
                artifact = write_canonical_artifact(
                    workspace_root,
                    document,
                    original_bytes=original_bytes,
                    original_filename=original_filename,
                )
            except OSError as exc:
                store_warnings.append(
                    f"Canonical Markdown could not be written to the library: {exc}"
                )
            else:
                canonical_meta["canonical_markdown_path"] = artifact.markdown_relative
                canonical_meta["canonical_original_path"] = ""
        chunks, paragraph_anchors = self._canonical_chunks(
            resource,
            document,
            markdown_path=str(canonical_meta["canonical_markdown_path"] or ""),
        )
        summary = IngestionSummary(
            text_preview=plain_text_preview(document.body, max_chars=240),
            detected_kind=ResourceKind(resource.kind),
            extracted_characters=len(document.body),
            chunk_count=len(chunks),
        )
        source_provenance: dict[str, Any] = dict(extra_provenance or {})
        source_provenance.update({
            "paragraph_anchors": paragraph_anchors,
            "document_anchors": [
                {**anchor.as_payload(), "label": anchor.label}
                for anchor in document.anchors
            ],
            "source_type": document.source_type,
            "parser": document.parser,
            "parser_version": document.parser_version,
            "page_count": document.page_count,
            "slide_count": document.slide_count,
            "canonical": canonical_meta,
        })
        result = IngestionResult(
            record=self.registry.clone_resource(resource.id),
            chunks=chunks,
            summary=summary,
            warnings=[*document.warnings, *store_warnings],
            vision_payload=None,
            source_provenance=source_provenance,
            canonical_body=document.body,
        )
        return result, canonical_meta

    def _canonical_failure(
        self,
        resource: ApiResourceRecord,
        warnings: list[str],
    ) -> IngestionResult:
        return IngestionResult(
            record=self.registry.clone_resource(resource.id),
            chunks=[
                ResourceChunk.create(
                    resource_id=resource.id,
                    order=0,
                    text="",
                    metadata={"kind": resource.kind},
                )
            ],
            summary=IngestionSummary(
                text_preview=warnings[0] if warnings else "The source could not be parsed.",
                detected_kind=ResourceKind(resource.kind),
                extracted_characters=0,
                chunk_count=0,
            ),
            warnings=list(warnings),
            vision_payload=None,
            source_provenance={},
        )

    def _canonical_chunks(
        self,
        resource: ApiResourceRecord,
        document: Any,
        *,
        markdown_path: str,
    ) -> tuple[list[ResourceChunk], list[dict[str, Any]]]:
        chunk_size = 1200
        chunk_overlap = 120
        body = document.body
        chunks = self.ingestor._chunk_text(
            resource.id,
            body,
            chunk_size,
            chunk_overlap,
            kind=ResourceKind(resource.kind),
        )
        step = max(chunk_size - chunk_overlap, 1)
        page_anchors = [anchor for anchor in document.anchors if anchor.kind == "page"]
        slide_anchors = [anchor for anchor in document.anchors if anchor.kind == "slide"]
        heading_anchors = [anchor for anchor in document.anchors if anchor.kind == "heading"]
        paragraph_anchors: list[dict[str, Any]] = []
        normalized: list[ResourceChunk] = []
        for index, chunk in enumerate(chunks):
            start_offset = min(index * step, len(body))
            end_offset = min(start_offset + chunk_size, len(body))
            start_line = body.count("\n", 0, start_offset) + 1
            end_line = body.count("\n", 0, end_offset) + 1
            metadata: dict[str, Any] = {
                "kind": document.source_type,
                "line_start": start_line,
                "line_end": end_line,
            }
            if markdown_path:
                metadata["markdown_path"] = markdown_path
            page = _last_anchor_before(page_anchors, start_line)
            slide = _last_anchor_before(slide_anchors, start_line)
            heading = _last_anchor_before(heading_anchors, start_line)
            if page is not None:
                metadata["page"] = page.index
                metadata["anchor_id"] = f"¶page{page.index}@{start_line}"
            elif slide is not None:
                metadata["slide"] = slide.index
                if slide.label:
                    metadata["slide_title"] = slide.label
                metadata["anchor_id"] = f"¶slide{slide.index}@{start_line}"
            if heading is not None:
                metadata["heading"] = heading.label
                metadata.setdefault("anchor_id", f"¶h{heading.index}@{start_line}")
            paragraph_anchors.append(dict(metadata))
            normalized.append(
                replace(
                    chunk,
                    start_line=start_line,
                    end_line=end_line,
                    metadata=metadata,
                )
            )
        return normalized, paragraph_anchors

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
            declared_items = list(resource.source_items)
            items = declared_items
            folder_truncated = False
            if len(items) > MAX_FOLDER_INGEST_ITEMS:
                items = items[:MAX_FOLDER_INGEST_ITEMS]
                folder_truncated = True

            # 增量续接: chunks of items whose file mtime is unchanged are
            # reused verbatim; only new/changed items are re-extracted.
            previous_chunks = self.registry.list_chunks(resource.id)
            reused_by_item: dict[str, list[ResourceChunk]] = {}
            for chunk in previous_chunks:
                item_path = str(chunk.metadata.get("folder_item") or "")
                if item_path:
                    reused_by_item.setdefault(item_path, []).append(chunk)
            registry_record = self.registry.get(resource.id)
            previous_metadata = dict(getattr(registry_record, "metadata", {}) or {})
            stored_mtimes: dict[str, Any] = dict(previous_metadata.get("folder_item_mtimes") or {})

            folder_chunks: list[ResourceChunk] = []
            folder_warnings: list[str] = []
            if folder_truncated:
                folder_warnings.append(
                    f"Folder index processed the first {MAX_FOLDER_INGEST_ITEMS} of "
                    f"{len(declared_items)} items; re-index to continue with the rest."
                )
            folder_summary_texts: list[str] = []
            folder_failures: list[dict[str, str]] = []
            indexed_count = 0
            current_mtimes: dict[str, Any] = {}
            for index, source_item in enumerate(items):
                try:
                    item_stat = Path(source_item).stat()
                except OSError as exc:
                    folder_failures.append({"item": source_item, "error": str(exc)})
                    folder_warnings.append(f"Folder item unavailable: {source_item} ({exc})")
                    continue
                item_key = str(source_item)
                current_mtime = item_stat.st_mtime_ns
                current_mtimes[item_key] = current_mtime
                if stored_mtimes.get(item_key) == current_mtime and reused_by_item.get(item_key):
                    folder_chunks.extend(reused_by_item[item_key])
                    indexed_count += 1
                    continue
                try:
                    child_request = IngestionRequest(
                        source_uri=source_item,
                        display_name=Path(source_item).name or source_item,
                        kind=self.ingestor._detect_kind(source_item),
                        metadata={"folder": resource.source, "folder_item_index": index},
                        enable_network=network_allowed,
                    )
                    text, item_warnings = self.ingest_service.describe_source(
                        child_request, vision_enabled=False
                    )
                except Exception as exc:  # noqa: BLE001 - one bad item must not kill the folder
                    folder_failures.append({"item": source_item, "error": f"{exc.__class__.__name__}: {exc}"})
                    folder_warnings.append(f"Folder item failed: {source_item} ({exc.__class__.__name__})")
                    continue
                folder_warnings.extend(item_warnings)
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
                indexed_count += 1

            summary = IngestionSummary(
                text_preview=" | ".join(folder_summary_texts[:3])[:240],
                detected_kind=ResourceKind(resource.kind),
                extracted_characters=sum(len(item) for item in folder_summary_texts),
                chunk_count=len(folder_chunks),
            )
            metadata_updates = {
                "character_count": sum(len(chunk.text) for chunk in folder_chunks),
                "chunk_count": len(folder_chunks),
                "folder_item_count": len(declared_items),
                "folder_item_indexed": indexed_count,
                "folder_item_preview": list(declared_items[:4]),
                "folder_item_mtimes": current_mtimes,
                "folder_item_failed": folder_failures[:20],
                "folder_item_failed_count": len(folder_failures),
            }
            if folder_truncated:
                metadata_updates["folder_item_truncated"] = True
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
        fragments_per_source: int = 2,
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
                self._validate_folder_source_items(
                    resource.source,
                    resource.source_items,
                    allow_missing=True,
                )
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
            for fragment in resource.knowledge_fragments[:fragments_per_source]:
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

    def _resolved_library_root(self, workspace_id: str) -> Path | None:
        if self._library_root_resolver is None:
            return None
        resolved = self._library_root_resolver(workspace_id)
        if resolved is None:
            return None
        return Path(resolved).expanduser().resolve(strict=False)

    def _resolve_canonical_markdown_file(
        self,
        workspace_id: str,
        canonical_markdown_path: str | None,
    ) -> Path | None:
        """Resolve a canonical Markdown file under ``<LibraryRoot>`` first, then legacy project fallback."""
        markdown = str(canonical_markdown_path or "").strip()
        if not markdown:
            return None
        path = Path(markdown)
        if path.is_absolute():
            return path
        candidates: list[Path] = []
        library_root = self._resolved_library_root(workspace_id)
        if library_root is not None:
            candidates.append(library_root / path)
        workspace_root = self._resolved_workspace_path(workspace_id)
        if workspace_root is not None and workspace_root != library_root:
            candidates.append(workspace_root / path)
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return candidates[0] if candidates else None

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

    def _canonical_markdown_path(
        self,
        workspace_id: str,
        resource: ApiResourceRecord,
    ) -> Path | None:
        """Where the canonical document of one resource lives, if it is named."""
        return self._resolve_canonical_markdown_file(
            workspace_id,
            resource.canonical_markdown_path,
        )

    def _discard_managed_inline_source(
        self,
        workspace_id: str,
        resource: ApiResourceRecord,
    ) -> None:
        """Remove a Trainer-owned inline upload — only behind a readable document.

        The inline copy is the last one of an upload, so it goes only once the
        canonical Markdown stands behind it. A missing or empty document leaves
        the upload in place.
        """

        local_path = self._local_source_path(resource.source)
        if local_path is None or not local_path.is_file():
            return
        if not self._is_managed_inline_source(workspace_id, resource.source):
            return
        if not self._has_readable_markdown(
            self._canonical_markdown_path(workspace_id, resource)
        ):
            return
        try:
            local_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove inline source %s", local_path, exc_info=True)

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
