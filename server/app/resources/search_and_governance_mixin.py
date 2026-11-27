from __future__ import annotations

import base64
import os
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha1
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal, Mapping
from urllib.parse import unquote, urlparse
from uuid import uuid4

from ..core.models import ResourceRecord as ApiResourceRecord
from ..core.models import (
    ResourceUploadRequest,
)
from ..ingest.models import IngestionResult, IngestionSummary
from .models import (
    ResourceChunk,
    ResourceKind,
    ResourceRecord,
)
from .service_support import (
    _REFERENCE_STOPWORDS,
    MAX_FOLDER_INGEST_ITEMS,
    _compact_anchors,
)
from .source_governance import (
    commercial_reuse_eligibility_reason_codes,
    commercial_reuse_governance_status,
    is_external_reference_source,
    source_governance_payload,
)
from .source_governance import (
    is_commercial_reuse_eligible as source_is_commercial_reuse_eligible,
)
from .versioning import provenance_payload


class SearchAndGovernanceMixin:
    if TYPE_CHECKING:
        _inline_resource_root: Any
        _search_index: Any
        enable_network_fetch: Any
        registry: Any
        repository: Any
        version_store: Any

    def _index_search_resource(
        self,
        workspace_id: str,
        resource: ApiResourceRecord,
        *,
        combined_text: str,
        chunks: list[ResourceChunk],
        document_anchors: list[dict[str, Any]] | None = None,
        canonical_body: str | None = None,
    ) -> None:
        preview_tier, preview_kind, source_extension = self._search_preview_metadata(resource)
        search_index = self._search_index(workspace_id)
        if canonical_body is None and document_anchors is None:
            previous, metadata = search_index.indexed_document(resource.id)
            length = metadata.get("content_length")
            if (
                metadata.get("canonical_text") is True
                and metadata.get("version_id") == resource.version_id
                and metadata.get("content_hash") == resource.content_hash
                and isinstance(length, int)
                and 0 < length <= len(previous)
            ):
                canonical_body = previous[:length]
                previous_anchors = metadata.get("document_anchors")
                if isinstance(previous_anchors, list):
                    document_anchors = previous_anchors
        content = (
            canonical_body
            or combined_text.strip()
            or "\n\n".join(chunk.text for chunk in chunks if chunk.text).strip()
            or resource.summary
            or resource.name
        )
        search_path = str(
            resource.canonical_markdown_path
            or resource.sandbox_path
            or resource.source
            or ""
        )
        current_version = self.version_store.current_version(workspace_id, resource.id)
        search_index.index_document(
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
                "version_id": current_version.get("version_id") if current_version else "",
                "content_hash": resource.content_hash or "",
                "content_length": len(content),
                "canonical_text": bool(canonical_body),
                "canonical_anchors": _compact_anchors(chunks),
                "document_anchors": list(document_anchors or []),
                "location": {
                    "path": search_path,
                    "resource_id": resource.id,
                    "markdown_path": resource.canonical_markdown_path or "",
                    "version_id": current_version.get("version_id") if current_version else "",
                    "content_hash": resource.content_hash or "",
                },
            },
        )

    def _search_file_type(self, resource: ApiResourceRecord) -> str:
        if resource.canonical_markdown_path:
            return "md"
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
        if resource.canonical_markdown_path:
            return "rich", "markdown", ".md"
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

    def _validate_source_within_allowed_roots(
        self,
        source: str,
        allowed_roots: list[Path],
        *,
        source_type: str = "file",
    ) -> None:
        local_path = self._local_source_path(source)
        if local_path is None:
            return
        if not local_path.exists():
            raise FileNotFoundError(f"Local resource source does not exist: {local_path}")
        normalized = local_path.resolve(strict=False)
        for root in allowed_roots:
            try:
                normalized.relative_to(root.resolve(strict=False))
                break
            except ValueError:
                continue
        else:
            raise PermissionError(
                f"Resource source must stay within the active workspace root: {normalized}"
            )
        if source_type == "folder" and not normalized.is_dir():
            raise NotADirectoryError(f"Local resource source must point to a folder: {normalized}")

    def _validate_source_within_workspace(
        self,
        source: str,
        workspace_root: Path,
        *,
        source_type: str = "file",
    ) -> None:
        self._validate_source_within_allowed_roots(
            source,
            [workspace_root],
            source_type=source_type,
        )

    def _materialize_inline_content(
        self,
        workspace_id: str,
        request: ResourceUploadRequest,
    ) -> ResourceUploadRequest:
        inline_content = request.content
        if not inline_content or request.kind == "url":
            return request

        normalized_source = str(request.source or "").strip()
        suffix = self._resource_suffix(request.kind, request.name, normalized_source)
        safe_name = self._safe_slug(request.name) or "resource"
        materialized_dir = self._inline_resource_root(workspace_id)
        collection_path = self._normalize_collection_path(request.collection_path)
        collection_root = request.collection_root
        if (collection_path is None) != (collection_root is None):
            raise ValueError("collection_path and collection_root must be supplied together.")
        if collection_path is not None:
            # Preserve the chosen collection's relative hierarchy within owned
            # storage. The original external directory never becomes authority.
            parts = PurePosixPath(collection_path).parts
            if len(parts) < 2:
                raise ValueError("An imported collection must include a relative file path.")
            root_path = materialized_dir / "collections" / uuid4().hex / parts[0]
            file_path = root_path.joinpath(*parts[1:])
            collection_root = str(root_path)
        else:
            file_path = materialized_dir / f"{safe_name}-{uuid4().hex[:8]}{suffix}"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        encoding = request.content_encoding or "utf-8"
        if encoding == "base64":
            file_path.write_bytes(base64.b64decode(inline_content))
        else:
            # Byte-exact write: newline translation would make the stored
            # bytes (and thus the TR-059 content hash) platform-dependent.
            file_path.write_bytes(inline_content.encode("utf-8"))
        return request.model_copy(
            update={"source": str(file_path), "content": None, "content_encoding": None,
                    "collection_root": collection_root}
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

    def _validate_folder_source_items(
        self,
        source: str,
        source_items: list[str] | None,
        *,
        allow_missing: bool = False,
    ) -> None:
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
                if allow_missing:
                    # 增量/失败隔离: a file deleted after upload must not block
                    # the whole folder index — the item falls through to the
                    # per-item failure record instead of a hard 400.
                    continue
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
            "epub": ".epub",
            "docx": ".docx",
            "pptx": ".pptx",
            "html": ".html",
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
            if len(normalized) >= MAX_FOLDER_INGEST_ITEMS:
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
        base = (
            0.84
            if kind in {"markdown", "code", "text", "pdf", "epub", "docx", "pptx", "html"}
            else 0.74
            if kind == "url"
            else 0.55
        )
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
        version: dict[str, Any] | None = None,
        workspace_id: str = "",
        paragraph_anchors: list[dict[str, Any]] | None = None,
        content_language: str | None = None,
    ) -> list[dict[str, Any]]:
        blocking_flags = {"duplicate", "source_conflict", "fetch_failed", "blocked_source", "network_disabled", "placeholder", "no_content"}
        if any(flag in blocking_flags for flag in quality_flags):
            return []
        fragments: list[dict[str, Any]] = []
        anchors = paragraph_anchors or []
        for idx, chunk in enumerate(chunks[:3]):
            snippet = self._truncate(chunk.text.strip(), max_chars=180)
            if not snippet:
                continue
            anchor_meta = anchors[idx] if idx < len(anchors) and isinstance(anchors[idx], dict) else {}
            paragraph_anchor = str(
                anchor_meta.get("anchor_id")
                or f"¶chunk:{chunk.order}@{chunk.start_line or 0}"
            )
            loc_dict: dict[str, Any] = {
                "path": canonical_source,
                "chunk_id": chunk.chunk_id,
                "line_start": chunk.start_line,
                "line_end": chunk.end_line,
                "paragraph_anchor": paragraph_anchor,
            }
            for key in (
                "page",
                "slide",
                "slide_title",
                "heading",
                "markdown_path",
                "paragraph_index",
                "char_offset",
                "char_length",
                "spine_index",
                "spine_id",
                "element_path",
                "href",
            ):
                if key in anchor_meta and anchor_meta[key] is not None:
                    loc_dict[key] = anchor_meta[key]
            fragment_payload = {
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
                "paragraph_anchor": paragraph_anchor,
                "content_language": content_language or resource.content_language,
                "location": loc_dict,
                "why_it_matters": self._why_it_matters(resource, chunk),
                **provenance_payload(
                    resource_id=resource.id,
                    version_id=(version or {}).get("version_id"),
                    content_hash=(version or {}).get("content_hash") or resource.content_hash,
                    location=loc_dict,
                ),
            }
            if workspace_id:
                # Version-scoped stable citation id (resource+version+location);
                # dropping the legacy resource-only override keeps each
                # fragment's citation distinct and deletion-verifiable.
                citation = self.version_store.record_citation(
                    workspace_id=workspace_id,
                    resource_id=resource.id,
                    version_id=fragment_payload.get("version_id"),
                    content_hash=fragment_payload.get("content_hash"),
                    location=fragment_payload.get("location"),
                    payload={"fragment_id": chunk.chunk_id},
                )
                fragment_payload["citation_id"] = citation["citation_id"]
            fragments.append(fragment_payload)
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

    def _canonical_resource_for_content_hash(
        self,
        workspace_id: str,
        content_hash: str,
        *,
        exclude_id: str,
    ) -> ApiResourceRecord | None:
        wanted = str(content_hash or "").strip()
        if not wanted or wanted == "no-content":
            return None
        for item in self.repository.list_resources(workspace_id):
            if item.id == exclude_id or item.index_status != "indexed":
                continue
            if str(item.content_hash or "").strip() == wanted:
                return item
            # md-only: the record's content_hash is the Markdown digest; the
            # original source digest stays available for duplicate detection.
            if str(item.indexed_source_hash or "").strip() == wanted:
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
        source = str(fragment.get("source", resource.canonical_source or resource.source))
        location = fragment.get("location")
        if not isinstance(location, dict):
            location = {
                "path": source,
                "chunk_id": str(fragment.get("id", "") or "").strip() or None,
                "line_start": fragment.get("line_start"),
                "line_end": fragment.get("line_end"),
            }
        normalized_provenance = provenance_payload(
            resource_id=str(fragment.get("resource_id", "") or resource.id),
            version_id=str(fragment.get("version_id", "") or "").strip() or None,
            content_hash=(
                str(fragment.get("content_hash", "") or "").strip()
                or resource.content_hash
            ),
            location=location,
            fallback_path=source,
        )
        return {
            "id": str(fragment.get("id", "") or resource.id),
            "resource_id": normalized_provenance["resource_id"],
            "title": str(fragment.get("title", "") or resource.name.strip() or resource.id),
            "snippet": snippet,
            "summary": self._truncate(str(fragment.get("summary", "") or snippet), max_chars=96),
            "evidence_summary": self._truncate(
                str(fragment.get("evidence_summary", "") or self._evidence_summary(snippet, title=resource.name)),
                max_chars=160,
            ),
            "source": source,
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
            "location": normalized_provenance["location"],
            "why_it_matters": str(
                fragment.get("why_it_matters")
                or f"Grounds follow-up coaching with {resource.name}."
            ).strip(),
            "source_governance": resource.source_governance.model_dump(mode="json"),
            **normalized_provenance,
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
