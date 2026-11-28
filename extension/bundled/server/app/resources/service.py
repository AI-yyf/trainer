from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Any, Callable, Iterable
from uuid import uuid4

from ..core.models import (
    ResourceIndexRequest,
    ResourceOrganizeRequest,
    ResourceUploadRequest,
)
from ..core.models import ResourceRecord as ApiResourceRecord
from ..db.repository import TrainerRepository
from ..ingest.models import IngestionRequest
from ..ingest.service import IngestService, ResourceIngestor
from ..memory.semantic import SemanticMemory
from .canonical import (
    CANONICAL_PARSER_VERSION,
    CanonicalParseError,
    build_canonical_document,
    build_canonical_from_text,
    canonicalizable,
    strip_front_matter,
)
from .canonical_and_collection_mixin import CanonicalAndCollectionMixin
from .canonical_store import original_dir_for
from .models import (
    IndexStatus,
    IngestStatus,
    ResourceKind,
)
from .search import SearchFilters, SearchIndex, SearchResponse
from .search_and_governance_mixin import SearchAndGovernanceMixin
from .service_support import (
    _REFERENCE_STOPWORDS as _REFERENCE_STOPWORDS,
)
from .service_support import (
    MAX_FOLDER_INGEST_ITEMS as MAX_FOLDER_INGEST_ITEMS,
)
from .service_support import (
    ResourceRegistry as ResourceRegistry,
)
from .service_support import (
    _AnchorView as _AnchorView,
)
from .service_support import (
    _best_match_position as _best_match_position,
)
from .service_support import (
    _canonical_version_bytes as _canonical_version_bytes,
)
from .service_support import (
    _captured_pdf_source_url as _captured_pdf_source_url,
)
from .service_support import (
    _compact_anchors as _compact_anchors,
)
from .service_support import (
    _count_markdown_tables as _count_markdown_tables,
)
from .service_support import (
    _last_anchor_before as _last_anchor_before,
)
from .service_support import (
    _original_filename_for as _original_filename_for,
)
from .service_support import (
    _resolve_document_location as _resolve_document_location,
)
from .source_governance import (
    evaluate_source_intake_governance,
)
from .version_check import (
    ResourceVersionCheckResult,
    VersionCheckStatus,
    captured_source_kind,
    compare_captured_source,
    effective_capture_tags,
)
from .versioning import ResourceVersionStore, compute_content_hash

logger = logging.getLogger(__name__)


class ResourceService(
    CanonicalAndCollectionMixin,
    SearchAndGovernanceMixin,
):
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
        self.version_store = ResourceVersionStore(repository.database_path)
        self.registry = ResourceRegistry()
        self.ingestor = ResourceIngestor(self.registry, ingest_service)
        self._workspace_path_resolver: Callable[[str], str | None] | None = None
        self._library_root_resolver: Callable[[str], Path | None] | None = None
        self._search_indexes: dict[str, SearchIndex] = {}
        self._resource_restore_locks: dict[tuple[str, str], Any] = {}
        # Canonicalize stages (analyze -> materialize -> index) reuse one parse
        # per resource so each HTTP stage does real work without parsing twice.
        self._prepared_canonical: dict[str, dict[str, Any]] = {}
        # P1 检索复用: identical (workspace, query, filters, top_k) within the
        # TTL window return the same response instead of re-running FTS5.
        self._search_cache: dict[
            tuple[str, str, int, tuple[tuple[str, Any], ...]],
            tuple[float, SearchResponse],
        ] = {}
        self._search_cache_ttl_seconds = 120.0
        self._search_cache_hits = 0
        self._search_cache_misses = 0
        self._resource_restore_locks_guard = Lock()

    def set_workspace_path_resolver(
        self,
        resolver: Callable[[str], str | None] | None,
    ) -> None:
        self._workspace_path_resolver = resolver

    def set_library_root_resolver(
        self,
        resolver: Callable[[str], Path | None] | None,
    ) -> None:
        self._library_root_resolver = resolver

    def close(self) -> None:
        close = getattr(self.semantic_memory, "close", None)
        if callable(close):
            close()

    def _record_resource_version(
        self,
        workspace_id: str,
        resource: ApiResourceRecord,
        content: str | bytes,
    ) -> dict[str, Any] | None:
        version = self.version_store.record_version_if_changed(
            workspace_id=workspace_id,
            resource_id=resource.id,
            content=content,
            location={"path": resource.canonical_source or resource.source},
        )
        current = version or self.version_store.current_version(workspace_id, resource.id)
        if current is not None:
            resource.content_hash = current["content_hash"]
            resource.version_id = current["version_id"]
        return current

    def upload(
        self,
        workspace_id: str,
        request: ResourceUploadRequest,
        *,
        workspace_path: str | None = None,
    ) -> ApiResourceRecord:
        explicit_workspace_root = self._resolved_workspace_root(workspace_path)
        resolved_workspace_root = explicit_workspace_root or self._resolved_workspace_path(workspace_id)
        allowed_roots = [
            root
            for root in (resolved_workspace_root, self._resolved_library_root(workspace_id))
            if root is not None
        ]
        original_source = str(request.source or "").strip()
        had_inline_content = bool(request.content)
        request = self._materialize_inline_content(workspace_id, request)
        if allowed_roots and original_source and not had_inline_content:
            self._validate_source_within_allowed_roots(
                original_source,
                allowed_roots,
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
            content_language=str(request.content_language).strip() if request.content_language else None,
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
        # md-only: pin the same normalized Markdown identity index() will
        # record, so an upload→index sequence does not create two versions.
        source_path = self._local_source_path(resource.source)
        if source_path is not None and source_path.is_file():
            try:
                if canonicalizable(source_path):
                    document = build_canonical_document(
                        source_path,
                        resource_id=resource.id,
                        original_name=source_path.name,
                    )
                    self._record_resource_version(
                        workspace_id, resource, _canonical_version_bytes(document)
                    )
                else:
                    self._record_resource_version(
                        workspace_id, resource, source_path.read_bytes()
                    )
            except (OSError, CanonicalParseError, ValueError):
                pass
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

    def check_source_version(
        self,
        workspace_id: str,
        resource_id: str,
        version_id: str,
        content_hash: str,
    ) -> ResourceVersionCheckResult:
        resource = self.repository.get_resource(workspace_id, resource_id)
        result = ResourceVersionCheckResult(
            resource_id=resource_id,
            version_id=version_id,
            content_hash=content_hash,
            status="missing",
        )
        if resource is None:
            return result
        if (resource.version_id or "", resource.content_hash or "") != (version_id, content_hash):
            result.status = "stale"
            return result

        capture_kind = captured_source_kind(resource)
        if capture_kind:
            saved = self._read_captured_snapshot(workspace_id, resource) if capture_kind != "pdf" else ""
            result.status, result.basis = compare_captured_source(
                resource, capture_kind, saved, network_enabled=self.enable_network_fetch,
            )
        elif resource.kind == "url":
            result.status, result.basis = self._check_indexed_url(resource), "indexed_url"
        else:
            result.status = "no_source"

        current = self.repository.get_resource(workspace_id, resource_id)
        if current is None:
            result.status = "missing"
        elif (current.version_id or "", current.content_hash or "") != (version_id, content_hash):
            result.status = "stale"
        return result

    def _read_captured_snapshot(self, workspace_id: str, resource: ApiResourceRecord) -> str:
        """Read the capture baseline.

        The managed inline snapshot is preferred while it still exists. After
        md-only cleanup, the canonical Markdown file is the durable baseline;
        the search index is intentionally not used here because its stored
        content also contains title/path/summary metadata.
        """

        path = self._local_source_path(resource.source)
        if path is not None:
            try:
                path = path.resolve(strict=True)
                if self._is_managed_inline_source(workspace_id, str(path)):
                    with path.open("rb") as file:
                        data = file.read(4 * 1024 * 1024 + 1)
                    if len(data) <= 4 * 1024 * 1024:
                        return data.decode("utf-8")
            except (OSError, UnicodeError, ValueError):
                pass
        markdown_path = self._resolve_canonical_markdown_file(
            workspace_id,
            resource.canonical_markdown_path,
        )
        if markdown_path is not None:
            try:
                return strip_front_matter(markdown_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                pass
        return ""

    def _check_indexed_url(self, resource: ApiResourceRecord) -> VersionCheckStatus:
        if (
            not resource.version_id or not resource.content_hash or not resource.fetched_at
            or resource.index_status != "indexed"
            or (not resource.indexed_source_hash and resource.parser_version
                and resource.parser_version != CANONICAL_PARSER_VERSION)
        ):
            return "no_baseline"
        if not self.enable_network_fetch:
            return "network_disabled"
        request = IngestionRequest(
            source_uri=resource.source, kind=ResourceKind.URL, enable_network=True,
        )
        text, _, provenance = self.ingest_service.describe_url(request)
        if provenance.get("status") != "fetched" or not text.strip():
            return "fetch_failed"
        if resource.indexed_source_hash:
            return (
                "unchanged" if provenance.get("source_content_hash") == resource.indexed_source_hash
                else "changed"
            )
        chunks = self.ingestor._chunk_text(
            resource.id, text, request.chunk_size, request.chunk_overlap, kind=ResourceKind.URL,
        )
        indexed_text = "\n\n".join(chunk.text for chunk in chunks if chunk.text)
        if resource.parser:
            try:
                document = build_canonical_from_text(
                    indexed_text, resource_id=resource.id,
                    original_filename=(
                        PurePosixPath(resource.canonical_original_path).name
                        if resource.canonical_original_path else self._url_snapshot_filename(resource.name)
                    ),
                )
            except CanonicalParseError:
                return "fetch_failed"
            chunks, _ = self._canonical_chunks(resource, document, markdown_path="")
            indexed_text = "\n\n".join(chunk.text for chunk in chunks if chunk.text)
        return "unchanged" if compute_content_hash(indexed_text) == resource.content_hash else "changed"

    def index(self, workspace_id: str, request: ResourceIndexRequest) -> ApiResourceRecord:
        resource = self._require_workspace_resource(workspace_id, request.resource_id)
        self._ensure_registry_resource(resource)
        effective_source_type = "folder" if self._is_folder_resource(resource) else resource.source_type
        workspace_root = self._resolved_workspace_path(workspace_id)
        allowed_roots = [
            root
            for root in (workspace_root, self._resolved_library_root(workspace_id))
            if root is not None
        ]
        if allowed_roots and not self._is_managed_inline_source(
            workspace_id,
            resource.source,
        ) and not self._is_managed_sandbox_source(workspace_id, resource.source):
            self._validate_source_within_allowed_roots(
                resource.source,
                allowed_roots,
                source_type=effective_source_type,
            )
        self._validate_source(resource.source, source_type=effective_source_type)
        if self._is_folder_resource(resource):
            self._validate_folder_source_items(
                resource.source,
                resource.source_items,
                allow_missing=True,
            )
        network_allowed = self._network_fetch_enabled(request.enable_network)
        canonical_meta: dict[str, Any] = {}
        initial_source_hash: str | None = None
        # Capture the original source digest before canonicalization mutates
        # the record's content_hash to the Markdown body hash.
        local_source = self._local_source_path(resource.source)
        if local_source is not None and local_source.is_file():
            try:
                initial_source_hash = compute_content_hash(local_source.read_bytes())
            except OSError:
                initial_source_hash = None
        canonical_ingest = self._canonical_local_ingest(workspace_id, resource)
        if canonical_ingest is not None:
            ingest_result, canonical_meta = canonical_ingest
        else:
            ingest_result = self._ingest_resource_record(
                resource,
                network_allowed=network_allowed,
            )
            source_hash = (ingest_result.source_provenance or {}).get("source_content_hash")
            initial_source_hash = source_hash if isinstance(source_hash, str) else None
            if initial_source_hash is None:
                local_source = self._local_source_path(resource.source)
                if local_source is not None and local_source.is_file():
                    try:
                        initial_source_hash = compute_content_hash(local_source.read_bytes())
                    except OSError:
                        initial_source_hash = None
            url_canonical = self._canonicalize_url_ingest(workspace_id, resource, ingest_result)
            if url_canonical is not None:
                ingest_result, canonical_meta = url_canonical

        def canonical_field(name: str, fallback: Any) -> Any:
            value = canonical_meta.get(name)
            return fallback if value in {None, ""} else value

        normalized_chunks = [
            replace(chunk, resource_id=resource.id) if chunk.resource_id != resource.id else chunk
            for chunk in ingest_result.chunks
        ]
        combined_text = "\n\n".join(chunk.text for chunk in normalized_chunks if chunk.text)
        version_content: str | bytes = combined_text
        if ingest_result.canonical_body is not None:
            # md-only: the Markdown body is the versioned artifact. Asset
            # references are resource-qualified for storage, so neutralize the
            # id before hashing two identical imports.
            version_content = ingest_result.canonical_body.replace(
                f"assets/{resource.id}/", "assets/"
            ).encode("utf-8")
        else:
            source_path = self._local_source_path(resource.source)
            if not self._is_folder_resource(resource) and source_path is not None and source_path.is_file():
                try:
                    version_content = source_path.read_bytes()
                except OSError:
                    pass
        if ingest_result.canonical_body is not None:
            # Canonicalization already recorded the Markdown version. Recording
            # the chunk-joined fallback would create a second, semantically
            # equivalent version on every reindex.
            current_version = self.version_store.current_version(workspace_id, resource.id)
        else:
            current_version = self._record_resource_version(
                workspace_id, resource, version_content
            )
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
        dedupe_content_hash = initial_source_hash or resource.content_hash
        if canonical_duplicate is None and dedupe_content_hash:
            # Identical bytes imported under a different path/name are the same
            # source content; reuse the first indexed copy instead of creating a
            # second knowledge projection. md-only records keep the source
            # digest in indexed_source_hash.
            canonical_duplicate = self._canonical_resource_for_content_hash(
                workspace_id,
                dedupe_content_hash,
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
        paragraph_anchors_raw = source_provenance.get("paragraph_anchors")
        paragraph_anchors = (
            list(paragraph_anchors_raw)
            if isinstance(paragraph_anchors_raw, list)
            else []
        )
        detected_content_language = str(
            resource.content_language
            or source_provenance.get("content_language")
            or ""
        ).strip() or None
        knowledge_fragments = self._knowledge_fragments(
            resource=resource,
            canonical_source=canonical_source,
            trust_score=trust_score,
            freshness=freshness,
            chunks=normalized_chunks,
            quality_flags=quality_flags,
            duplicate_key=duplicate_key,
            version=current_version,
            workspace_id=workspace_id,
            paragraph_anchors=paragraph_anchors,
            content_language=detected_content_language,
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
                "kind": "markdown" if canonical_meta.get("canonical_markdown_path") else resource.kind,
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
                "paragraph_anchors": paragraph_anchors[:64],
                "content_language": detected_content_language or "",
                "canonical_markdown_path": str(canonical_meta.get("canonical_markdown_path") or ""),
                "canonical_original_path": str(canonical_meta.get("canonical_original_path") or ""),
                "parser": str(canonical_meta.get("parser") or ""),
                "parser_version": str(canonical_meta.get("parser_version") or ""),
                "page_count": canonical_meta.get("page_count"),
                "slide_count": canonical_meta.get("slide_count"),
            },
        )
        self.registry.mark_indexed(
            resource.id,
            index_status=IndexStatus.FAILED if indexing_failed else IndexStatus.INDEXED,
        )
        self.invalidate_search_cache(workspace_id)

        if indexing_failed:
            self.semantic_memory.delete_text(resource.id)
        else:
            self.semantic_memory.upsert_text(
                resource.id,
                combined_text[:4000],
                {"workspace_id": workspace_id, "kind": resource.kind, "name": resource.name},
            )
        canonical_markdown_path = str(
            canonical_field("canonical_markdown_path", resource.canonical_markdown_path) or ""
        ).strip()
        md_only = bool(canonical_markdown_path)
        updated = resource.model_copy(
            update={
                "parse_status": "failed" if indexing_failed else "parsed",
                "index_status": "failed" if indexing_failed else "indexed",
                "summary": canonical_duplicate.summary if canonical_duplicate and canonical_duplicate.summary else ingest_result.summary.text_preview or resource.summary,
                # The library's identity is Markdown; the original format is
                # provenance, not a library artifact.
                "kind": "markdown" if md_only else resource.kind,
                "source_type": "markdown" if md_only else self._source_type(resource.kind, resource.source),
                "canonical_source": canonical_source,
                "fetched_at": fetched_at,
                "trust_score": trust_score,
                "freshness": freshness,
                "duplicate_key": duplicate_key,
                "quality_flags": quality_flags,
                "warnings": list(warnings),
                "knowledge_fragments": knowledge_fragments,
                "source_governance": source_governance,
                "content_hash": (current_version or {}).get("content_hash") or resource.content_hash,
                # Keep the source digest for dedupe/version checks even though
                # the record's content_hash now identifies the Markdown.
                "indexed_source_hash": initial_source_hash or resource.indexed_source_hash,
                "content_language": detected_content_language or resource.content_language,
                "canonical_markdown_path": canonical_markdown_path,
                # md-only: the original binary is never a library artifact.
                "canonical_original_path": "",
                "parser": canonical_field("parser", resource.parser),
                "parser_version": canonical_field("parser_version", resource.parser_version),
                "page_count": canonical_field("page_count", resource.page_count),
                "slide_count": canonical_field("slide_count", resource.slide_count),
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
            document_anchors = source_provenance.get("document_anchors")
            self._index_search_resource(
                workspace_id,
                updated,
                combined_text=combined_text,
                chunks=normalized_chunks,
                canonical_body=ingest_result.canonical_body,
                document_anchors=(
                    list(document_anchors)
                    if isinstance(document_anchors, list)
                    else None
                ),
            )
        else:
            self._search_index(workspace_id).delete_document(updated.id)
        return updated

    @staticmethod
    def _has_readable_markdown(markdown_path: Path | None) -> bool:
        """A canonical document that can stand behind the originals.

        A missing or empty file replaces nothing, so the originals it would
        replace stay.
        """
        if markdown_path is None:
            return False
        try:
            return markdown_path.is_file() and markdown_path.stat().st_size > 0
        except OSError:
            return False

    def _remove_originals_behind_markdown(
        self,
        workspace_root: Path,
        resource: ApiResourceRecord,
    ) -> tuple[bool, str]:
        """Remove the legacy originals of one resource — behind a document.

        This is the only place the library drops an original, and it refuses
        unless a readable canonical Markdown stands behind it. The originals
        are then a leftover duplicate; without one they are the last copy of
        the learner's file, and they stay.

        Returns ``(removed, reason)``. The caller must not report a clean run
        when ``removed`` is false.
        """
        markdown = str(resource.canonical_markdown_path or "").strip()
        markdown_path = Path(markdown) if markdown else None
        if markdown_path is not None and not markdown_path.is_absolute():
            markdown_path = workspace_root / markdown_path
        if not self._has_readable_markdown(markdown_path):
            return False, "The canonical Markdown is missing; the originals were kept."
        original_dir = original_dir_for(workspace_root, resource.id)
        if not original_dir.is_dir():
            return True, ""
        for path in original_dir.rglob("*"):
            if path.is_file():
                path.unlink(missing_ok=True)
        for path in sorted(original_dir.rglob("*"), reverse=True):
            if path.is_dir():
                path.rmdir()
        original_dir.rmdir()
        return True, ""

    def markdown_only_migration(
        self,
        workspace_id: str,
        *,
        dry_run: bool = True,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Convert and clean an existing library into the Markdown-only shape.

        Dry-run is the default. The destructive pass requires ``confirm=True``,
        writes a manifest before deleting anything, and never deletes an
        original unless a readable canonical Markdown already exists.
        """

        workspace_root = self._canonical_writable_root(workspace_id)
        resources = self.repository.list_resources(workspace_id)
        manifest: list[dict[str, Any]] = []
        convertible: list[str] = []
        failures: list[dict[str, str]] = []
        # Resources whose legacy originals are the only copy of the resource:
        # no readable canonical Markdown stands behind them, so the migration
        # keeps them and reports them.
        unbacked_originals: list[str] = []

        for resource in resources:
            markdown = str(resource.canonical_markdown_path or "").strip()
            markdown_path = Path(markdown) if markdown else None
            if markdown_path is not None and not markdown_path.is_absolute() and workspace_root is not None:
                markdown_path = workspace_root / markdown_path
            has_markdown = bool(markdown_path and markdown_path.is_file())
            if has_markdown:
                # A readable canonical document: an empty file stands behind
                # nothing, so it cannot replace the originals.
                has_markdown = self._has_readable_markdown(markdown_path)
            if not has_markdown and resource.source_type != "folder":
                source_path = self._local_source_path(resource.source)
                if source_path is not None and source_path.is_file() and canonicalizable(source_path):
                    convertible.append(resource.id)
            if workspace_root is None:
                continue
            original_dir = original_dir_for(workspace_root, resource.id)
            original_files = (
                [path for path in original_dir.rglob("*") if path.is_file()]
                if original_dir.is_dir()
                else []
            )
            if original_files:
                if has_markdown:
                    # A readable canonical Markdown stands behind these
                    # originals, so they are a leftover duplicate. The
                    # destructive pass still re-checks that document before it
                    # removes anything (`_remove_originals_behind_markdown`).
                    manifest.append(
                        {
                            "resource_id": resource.id,
                            "action": "delete_originals",
                            "files": [
                                {
                                    "path": str(path.relative_to(workspace_root)),
                                    "size": path.stat().st_size,
                                }
                                for path in original_files
                            ],
                        }
                    )
                else:
                    # Nothing readable stands behind these originals, so they
                    # are the last copy of the resource. A convertible resource
                    # replaces them with its canonical Markdown (and only then
                    # drops them); anything else keeps them and is reported.
                    unbacked_originals.append(resource.id)
            if has_markdown and (
                resource.kind != "markdown"
                or resource.canonical_original_path
                or resource.source_type != "markdown"
            ):
                manifest.append(
                    {
                        "resource_id": resource.id,
                        "action": "mark_markdown",
                        "previous_kind": resource.kind,
                        "previous_source_type": resource.source_type,
                    }
                )

        summary = {
            "workspace_id": workspace_id,
            "dry_run": dry_run,
            "resources": len(resources),
            "originals_to_delete": sum(
                1 for item in manifest if item["action"] == "delete_originals"
            ),
            "records_to_mark": sum(
                1 for item in manifest if item["action"] == "mark_markdown"
            ),
            "convertible": len(convertible),
            "originals_kept": len(unbacked_originals),
            "kept_originals": unbacked_originals[:200],
            "manifest": manifest[:200],
        }
        if dry_run:
            return {"status": "preview", **summary}
        if not confirm:
            return {"status": "confirmation_required", **summary}

        if workspace_root is not None and manifest:
            manifest_dir = (
                self.data_root
                / "library-migrations"
                / (self._safe_slug(workspace_id) or "workspace")
            )
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            summary["manifest_path"] = str(manifest_path)

        # Convert first. A conversion writes the canonical Markdown and only
        # then drops the originals it replaced (the canonical store keeps that
        # order), so a failed conversion leaves the originals untouched.
        # Deleting first would destroy the only copy of a resource whose
        # conversion later fails.
        converted = 0
        for resource_id in convertible:
            try:
                self.index(
                    workspace_id,
                    ResourceIndexRequest(resource_id=resource_id, enable_network=False),
                )
                converted += 1
            except Exception as exc:  # noqa: BLE001 - report per-resource, never abort the batch
                logger.warning("Batch resource conversion failed for %s: %s", resource_id, exc)
                failures.append({"resource_id": resource_id, "error": str(exc)})
        summary["converted"] = converted

        for item in manifest:
            resource = next(
                (candidate for candidate in resources if candidate.id == item["resource_id"]),
                None,
            )
            if resource is None:
                continue
            if item["action"] == "delete_originals" and workspace_root is not None:
                # One chokepoint: the originals only go behind a readable
                # canonical document, and a refusal is reported.
                removed, reason = self._remove_originals_behind_markdown(
                    workspace_root, resource
                )
                if not removed:
                    failures.append({"resource_id": resource.id, "error": reason})
            if item["action"] == "mark_markdown":
                updated = resource.model_copy(
                    update={
                        "kind": "markdown",
                        "source_type": "markdown",
                        "canonical_original_path": "",
                    }
                )
                self.repository.save_resource(workspace_id, updated)

        for resource_id in unbacked_originals:
            failures.append(
                {
                    "resource_id": resource_id,
                    "error": (
                        "No canonical Markdown and no readable source; "
                        "the only copy of the original was kept."
                    ),
                }
            )
        summary["failures"] = failures
        summary["status"] = "complete" if not failures else "partial"
        return summary

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

    # ---------------------------------------------------------------- organize

    MAX_RESOURCE_TAGS = 20
    MAX_RESOURCE_TAG_CHARS = 40
    MAX_RESOURCE_TITLE_CHARS = 200
    _RESERVED_GROUP_SEGMENTS = frozenset(
        {
            ".trainer",
            ".trainer-sandbox",
            "collections",
            "groups",
            "inline-resources",
            "sandbox",
            "trainer",
        }
    )

    def organize_resource(
        self,
        workspace_id: str,
        request: ResourceOrganizeRequest,
    ) -> ApiResourceRecord:
        """Rename, retag or regroup one library resource.

        The three actions only touch the existing resource record structure —
        ``name``, ``tags`` and the proven ``collection_path``/``collection_root``
        pair — and never invent a second organizational model. Grouping is a
        real move inside Trainer's own managed storage; project and sandbox
        artifacts stay with the existing Coach organize flow.
        """

        resource = self._require_workspace_resource(workspace_id, request.resource_id)
        updates: dict[str, Any] = {}
        if request.action == "rename":
            updates["name"] = self._normalize_resource_title(request.title)
        elif request.action == "set_tags":
            updates["capture_provenance_tags"] = list(effective_capture_tags(resource))
            updates["tags"] = self._normalize_resource_tags(request.tags or [])
        elif request.action == "set_group":
            group_path, collection_root = self._group_resource_file(
                workspace_id,
                resource,
                request.group or "",
            )
            updates["source"] = group_path
            updates["collection_path"] = self._collection_path_for_group(group_path, collection_root)
            updates["collection_root"] = collection_root
        else:  # pragma: no cover - Literal already constrains the action
            raise ValueError(f"Unsupported organize action: {request.action}")

        updated = resource.model_copy(update=updates)
        self.repository.save_resource(workspace_id, updated)
        self._ensure_registry_resource(updated)
        if updated.index_status == "indexed":
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

    def _normalize_resource_title(self, value: str | None) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            raise ValueError("A resource title cannot be empty.")
        if any(ord(character) < 32 for character in text):
            raise ValueError("A resource title cannot contain control characters.")
        if len(text) > self.MAX_RESOURCE_TITLE_CHARS:
            text = text[: self.MAX_RESOURCE_TITLE_CHARS - 1].rstrip() + "…"
        return text

    def _normalize_resource_tags(self, values: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = " ".join(str(value or "").split())
            if not text:
                continue
            text = text[: self.MAX_RESOURCE_TAG_CHARS]
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(text)
            if len(normalized) >= self.MAX_RESOURCE_TAGS:
                break
        return normalized

    def _group_resource_file(
        self,
        workspace_id: str,
        resource: ApiResourceRecord,
        group: str,
    ) -> tuple[str, str | None]:
        """Put an owned snapshot into (or out of) a user-named group directory.

        Only Trainer's own managed snapshots move: the file lives under the
        workspace's inline-resource root, the project-side sandbox mirror (if
        any) keeps pointing at the same bytes, and imported folder collections
        keep their structure. Returns the new local file path and the proven
        collection root (None when the resource returns to the ungrouped root).

        A resource that already has its canonical document has no snapshot to
        move: the library replaced the upload with that document. Its group is
        metadata only — the same ``collection_path`` the folder tree reads.
        """

        source_path = self._local_source_path(resource.source)
        inline_root = self._inline_resource_root(workspace_id).resolve(strict=False)
        if source_path is None or not source_path.is_file():
            if self._has_readable_markdown(self._canonical_markdown_path(workspace_id, resource)):
                segments = self._normalize_group_segments(group)
                if not segments:
                    return str(resource.source), None
                return str(resource.source), str(inline_root.joinpath("groups", *segments))
            raise ValueError("Only local library snapshots can be grouped.")
        resolved_source = source_path.resolve(strict=False)
        try:
            relative = resolved_source.relative_to(inline_root)
        except ValueError as exc:
            raise PermissionError(
                "This resource is not in Trainer's managed library storage; use the Coach organize flow for project files."
            ) from exc
        if relative.parts and relative.parts[0] == "collections":
            raise PermissionError(
                "Imported folder collections keep their structure; group a copy instead."
            )
        segments = self._normalize_group_segments(group)
        target_dir = inline_root
        if segments:
            target_dir = inline_root.joinpath("groups", *segments)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / resolved_source.name
        if target_path.resolve(strict=False) == resolved_source:
            return str(resolved_source), self._existing_collection_root(resource)
        if target_path.exists():
            stem = target_path.stem
            suffix = target_path.suffix
            target_path = target_dir / f"{stem}-{resource.id.rsplit('-', 1)[-1][:8]}{suffix}"
        try:
            resolved_source.replace(target_path)
        except OSError as exc:
            raise ValueError(f"The resource file could not be moved: {exc}") from exc
        if not segments:
            return str(target_path), None
        return str(target_path), str(target_dir)

    def _normalize_group_segments(self, group: str) -> list[str]:
        candidate = str(group or "").strip().replace("\\", "/")
        candidate = candidate.strip("/")
        if not candidate:
            return []
        parts = [segment.strip() for segment in candidate.split("/")]
        if any(not segment or segment in {".", ".."} for segment in parts):
            raise ValueError("A group name cannot contain empty, current or parent segments.")
        if len(parts) > 3:
            raise ValueError("A group path may have at most three nested levels.")
        normalized: list[str] = []
        for segment in parts:
            if len(segment) > 60:
                raise ValueError("Each group segment must be 60 characters or fewer.")
            if any(ord(character) < 32 for character in segment):
                raise ValueError("Group names cannot contain control characters.")
            if segment.casefold() in self._RESERVED_GROUP_SEGMENTS:
                raise ValueError(f"'{segment}' is reserved for Trainer storage.")
            normalized.append(segment)
        return normalized

    @staticmethod
    def _collection_path_for_group(
        group_path: str,
        collection_root: str | None,
    ) -> str | None:
        if collection_root is None:
            return None
        root = Path(collection_root)
        return f"{root.name}/{Path(group_path).name}"

    @staticmethod
    def _existing_collection_root(resource: ApiResourceRecord) -> str | None:
        root = str(resource.collection_root or "").strip()
        return root or None

    def export_resource(
        self,
        workspace_id: str,
        resource_id: str,
        *,
        export_format: str = "markdown",
    ) -> dict[str, Any]:
        """Resolve the bytes that "download/export" hands to the user.

        Supports canonical Markdown (``.md``) and paginated PDF (``.pdf``)
        rendered from the resource's canonical Markdown document. A record with
        no readable source is refused honestly instead of exporting a binary
        original.
        """

        normalized_format = str(export_format or "markdown").strip().lower()
        if normalized_format in {"md", "markdown"}:
            normalized_format = "markdown"
        elif normalized_format != "pdf":
            raise ValueError(f"Unsupported export format: {export_format!r}")

        resource = self._require_workspace_resource(workspace_id, resource_id)
        resolved = self._resolve_markdown_export_target(workspace_id, resource)
        if normalized_format == "markdown":
            return resolved

        from .pdf_export import render_markdown_pdf_bytes

        md_path = Path(str(resolved["path"]))
        markdown_text = md_path.read_text(encoding="utf-8", errors="replace")
        pdf_bytes = render_markdown_pdf_bytes(resource.name or md_path.stem, markdown_text)
        cache_dir = md_path.parent / ".export-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        digest = sha256(pdf_bytes).hexdigest()[:12]
        pdf_path = cache_dir / f"{resource.id}-{digest}.pdf"
        if not pdf_path.is_file():
            pdf_path.write_bytes(pdf_bytes)
        md_name = str(resolved["filename"])
        stem = md_name[:-3] if md_name.lower().endswith(".md") else md_name
        return {
            "path": str(pdf_path),
            "filename": f"{stem}.pdf",
            "media_type": "application/pdf",
        }

    def _resolve_markdown_export_target(
        self, workspace_id: str, resource: ApiResourceRecord
    ) -> dict[str, Any]:
        resolved = self._canonical_export_target(workspace_id, resource)
        if resolved is not None:
            return resolved
        # A legacy record may still lack its canonical document. Convert it
        # once, then export the Markdown: the export never hands back a binary
        # original.
        try:
            self.analyze_canonical(workspace_id, [resource.id])
            self.materialize_canonical(workspace_id, [resource.id])
        except Exception as exc:
            logger.debug("On-demand canonical conversion failed for %s: %s", resource.id, exc)
        refreshed = self._require_workspace_resource(workspace_id, resource.id)
        resolved = self._canonical_export_target(workspace_id, refreshed)
        if resolved is not None:
            return resolved
        text_snapshot = self._text_snapshot_export_target(workspace_id, refreshed)
        if text_snapshot is not None:
            return text_snapshot
        raise ValueError(
            "This resource has no canonical Markdown to export; convert or index it first."
        )

    def _canonical_export_target(
        self, workspace_id: str, resource: ApiResourceRecord
    ) -> dict[str, Any] | None:
        markdown_path = self._resolve_canonical_markdown_file(
            workspace_id,
            resource.canonical_markdown_path,
        )
        if markdown_path is None:
            return None
        try:
            if not markdown_path.is_file():
                return None
        except OSError:
            return None
        stem = self._safe_export_name(resource.name) or markdown_path.stem
        if not stem.lower().endswith(".md"):
            stem = f"{stem}.md"
        return {
            "path": str(markdown_path),
            "filename": stem,
            "media_type": "text/markdown",
        }

    def _text_snapshot_export_target(
        self, workspace_id: str, resource: ApiResourceRecord
    ) -> dict[str, Any] | None:
        """Export a legacy text snapshot as Markdown.

        A capture taken before the Markdown-only library has no canonical
        document yet, but its managed snapshot *is* plain Markdown text. It is
        exported as `.md`; a binary snapshot (a captured PDF) never is.
        """

        if str(resource.kind or "").strip().lower() == "pdf":
            return None
        path = self._local_source_path(resource.source)
        if path is None or not path.is_file():
            return None
        if not self._is_managed_inline_source(workspace_id, str(path)):
            return None
        try:
            path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        stem = self._safe_export_name(resource.name) or path.stem
        if not stem.lower().endswith(".md"):
            stem = f"{stem}.md"
        return {
            "path": str(path),
            "filename": stem,
            "media_type": "text/markdown",
        }

    @staticmethod
    def _safe_export_name(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        cleaned = "".join(
            character if (character.isalnum() or character in "._- ") else "-"
            for character in text
        ).strip(" .")
        return cleaned[:120]

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
        cache_key = (
            str(workspace_id),
            query.strip().casefold(),
            max(1, min(top_k, 50)),
            tuple(sorted((k, v) for k, v in asdict(filters).items() if v)),
        )
        now = time.monotonic()
        cached = self._search_cache.get(cache_key)
        if cached is not None and now - cached[0] <= self._search_cache_ttl_seconds:
            self._search_cache_hits += 1
            return cached[1]
        self._search_cache_misses += 1
        response = self._search_index(workspace_id).search(
            query,
            filters=filters,
            top_k=max(1, min(top_k, 50)),
        )
        self._enrich_search_locations(workspace_id, response, query)
        self._mark_stale_search_versions(workspace_id, response)
        self._search_cache[cache_key] = (now, response)
        return response

    def read_canonical_text(
        self,
        workspace_id: str,
        resource_id: str,
    ) -> str | None:
        """Return the persisted Markdown body for a resource.

        Chunk lists live in the process registry and disappear on restart; the
        canonical Markdown (and the search index as a fallback) is durable, so
        agents can still read the library after a sidecar restart.
        """

        record = self._require_workspace_resource(workspace_id, resource_id)
        path = self._resolve_canonical_markdown_file(
            workspace_id,
            record.canonical_markdown_path,
        )
        if path is not None:
            try:
                return strip_front_matter(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                pass
        content = self._search_index(workspace_id).document_content(record.id)
        return content or None

    def read_indexed_fragment_text(
        self, workspace_id: str, resource: ApiResourceRecord, fragment: dict[str, Any],
    ) -> str:
        """Use the original indexed span for a teaching question, with its version verified."""
        location = fragment.get("location")
        if not isinstance(location, dict) or not resource.version_id or not resource.content_hash:
            return ""
        start, end = location.get("line_start"), location.get("line_end")
        if not isinstance(start, int) or start < 1:
            return ""
        if end is not None and (not isinstance(end, int) or end < start):
            return ""
        index = self._search_index(workspace_id)
        metadata = index.document_metadata(resource.id)
        if metadata.get("version_id") != resource.version_id or metadata.get("content_hash") != resource.content_hash:
            return ""
        if fragment.get("version_id") != resource.version_id or fragment.get("content_hash") != resource.content_hash:
            return ""
        content = index.document_content(resource.id)
        content_length = metadata.get("content_length")
        if isinstance(content_length, int) and content_length > 0:
            content = content[:content_length]
        lines = content.splitlines()
        if end is None:
            # Search locations can point to a single line. Use the indexed
            # chunk containing that line, bounded to a short excerpt.
            raw_anchors = metadata.get("canonical_anchors")
            enclosing_ends = [
                anchor["line_end"] for anchor in raw_anchors
                if isinstance(anchor, dict)
                and isinstance(anchor.get("line_start"), int)
                and isinstance(anchor.get("line_end"), int)
                and anchor["line_start"] <= start <= anchor["line_end"]
            ] if isinstance(raw_anchors, list) else []
            end = min(min(enclosing_ends, default=start), start + 11, len(lines))
        return "\n".join(lines[start - 1:end]).strip()[:1600]

    def indexed_source_text(
        self, workspace_id: str, resource: ApiResourceRecord,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Read the canonical indexed body and its document anchors for the current version."""
        if resource.index_status != "indexed" or not resource.version_id or not resource.content_hash:
            return "", []
        version = self.version_store.current_version(workspace_id, resource.id) or {}
        if version.get("version_id") != resource.version_id or version.get("content_hash") != resource.content_hash:
            return "", []
        content, metadata = self._search_index(workspace_id).indexed_document(resource.id)
        if metadata.get("version_id") != resource.version_id or metadata.get("content_hash") != resource.content_hash:
            return "", []
        length = metadata.get("content_length")
        if not isinstance(length, int) or length <= 0 or length > len(content):
            return "", []
        raw_anchors = metadata.get("document_anchors")
        anchors = [anchor for anchor in raw_anchors if isinstance(anchor, dict)] if isinstance(raw_anchors, list) else []
        if metadata.get("canonical_text") is not True:
            # Older indexes joined overlapping chunks. Reuse a recorded reader
            # body only when it matches an intact prefix of the pinned index.
            canonical = self.read_canonical_text(workspace_id, resource.id) if resource.canonical_markdown_path else None
            if not canonical or not content[:length].startswith(canonical.strip()):
                return "", []
            return canonical.strip(), anchors
        return content[:length], anchors

    def search_cache_stats(self) -> dict[str, Any]:
        """Cache evidence for the agent: hits/misses/TTL (token-cost transparency)."""

        total = self._search_cache_hits + self._search_cache_misses
        return {
            "hits": self._search_cache_hits,
            "misses": self._search_cache_misses,
            "hit_rate": round(self._search_cache_hits / total, 3) if total else 0.0,
            "ttl_seconds": int(self._search_cache_ttl_seconds),
        }

    def invalidate_search_cache(self, workspace_id: str | None = None) -> None:
        """Drop cached search responses after the corpus changes (P1 检索复用)."""
        if workspace_id is None:
            self._search_cache.clear()
            return
        prefix = str(workspace_id)
        for key in [k for k in self._search_cache if k[0] == prefix]:
            self._search_cache.pop(key, None)

    def _enrich_search_locations(
        self,
        workspace_id: str,
        response: SearchResponse,
        query: str,
    ) -> None:
        """Point each hit at the page/slide/heading that matched.

        Search indexes the whole canonical Markdown body; the first occurrence
        of a query term is mapped back to the anchor table recorded at index
        time so the reader can open the exact location instead of the file top.
        """

        terms = [
            term.lower()
            for term in re.split(r"\W+", str(query or ""))
            if len(term) >= 2
        ][:8]
        if not terms:
            return
        index = self._search_index(workspace_id)
        for hit in response.results:
            metadata = index.document_metadata(hit.resource_id)
            document_anchors = metadata.get("document_anchors")
            anchors = (
                document_anchors
                if isinstance(document_anchors, list) and document_anchors
                else metadata.get("canonical_anchors")
            )
            if not isinstance(anchors, list) or not anchors:
                continue
            content_length = metadata.get("content_length")
            content = index.document_content(hit.resource_id)
            if isinstance(content_length, int) and content_length > 0:
                content = content[:content_length]
            position = _best_match_position(content, terms)
            if position < 0:
                continue
            line = content.count("\n", 0, position) + 1
            resolved = _resolve_document_location(
                [item for item in anchors if isinstance(item, dict)],
                line,
            )
            if not resolved:
                continue
            location = dict(hit.location or {})
            location.update(resolved)
            hit.location = location

    def _mark_stale_search_versions(
        self,
        workspace_id: str,
        response: SearchResponse,
    ) -> None:
        """Flag indexed hits that no longer match the resource's current head."""

        for hit in response.results:
            indexed_version = str(hit.version_id or "").strip()
            if not indexed_version:
                continue
            try:
                current = self.version_store.current_version(workspace_id, hit.resource_id) or {}
            except Exception as exc:
                logger.debug("Failed to fetch current version for resource %s: %s", hit.resource_id, exc)
                current = {}
            current_version = str(current.get("version_id") or "").strip()
            if current_version and current_version != indexed_version:
                hit.stale = True
                hit.current_version_id = current_version
                hit.current_content_hash = str(current.get("content_hash") or "") or None
