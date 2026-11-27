from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from ..core.models import ResourceRecord as ApiResourceRecord
from .canonical import (
    CanonicalDocument,
)
from .capture import capture_url_from_tags
from .models import (
    IndexStatus,
    IngestStatus,
    ResourceChunk,
    ResourceRecord,
    utc_now,
)
from .version_check import (
    effective_capture_tags,
)


def _canonical_version_bytes(document: CanonicalDocument) -> bytes:
    """Stable content identity for the Markdown body.

    Asset references are qualified with the resource id for storage, but that
    id must not make two byte-identical imports look like different content.
    """

    body = document.body.replace(f"assets/{document.resource_id}/", "assets/")
    return body.encode("utf-8")


def _captured_pdf_source_url(resource: ApiResourceRecord) -> str:
    if resource.kind != "pdf":
        return ""
    return capture_url_from_tags(effective_capture_tags(resource))


def _count_markdown_tables(body: str) -> int:
    """Count Markdown table blocks (header row + separator row)."""

    return len(
        re.findall(
            r"(?m)^\|[^\n]*\|\s*\n\|[\s:|-]+\|\s*$",
            body or "",
        )
    )


def _original_filename_for(resource: Any, source_path: Path) -> str:
    """Prefer the resource's display name over the internal materialized name."""

    suffix = source_path.suffix
    display = str(getattr(resource, "name", "") or "").strip()
    if not display:
        return source_path.name
    display_name = Path(display).name
    if Path(display_name).suffix.lower() == suffix.lower():
        return display_name
    return f"{Path(display_name).stem}{suffix}" if Path(display_name).suffix else f"{display_name}{suffix}"


def _best_match_position(content: str, terms: list[str]) -> int:
    """Return a line in the section that best covers the query terms.

    Picking the earliest occurrence of any single term misroutes citations to
    an earlier section that happens to repeat a common word. Scoring lines
    alone over-rewards a footnote that quotes every term. Score sections first
    (heading match + distinct-term coverage), then pick the strongest line
    inside the winning section. Ties keep the earliest section/line.
    """

    lines = str(content or "").splitlines()
    if not lines or not terms:
        return -1
    normalized_terms = [term.lower() for term in terms if len(term) >= 2]
    if not normalized_terms:
        return -1

    heading_pattern = re.compile(r"^#{1,6}\s+(.+?)\s*$")
    headings: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = heading_pattern.match(line.strip())
        if match:
            headings.append((index, match.group(1).strip()))
    sections: list[tuple[int, int, str]] = []
    if headings:
        if headings[0][0] > 0:
            sections.append((0, headings[0][0] - 1, ""))
        for position, (start, title) in enumerate(headings):
            end = headings[position + 1][0] - 1 if position + 1 < len(headings) else len(lines) - 1
            sections.append((start, end, title))
    else:
        sections.append((0, len(lines) - 1, ""))

    def _line_score(index: int) -> int:
        line = lines[index].lower()
        return sum(1 for term in normalized_terms if term in line)

    best_section: tuple[int, int, str] | None = None
    best_section_score = -1
    for section in sections:
        start, end, title = section
        section_text = "\n".join(lines[start : end + 1]).lower()
        covered = sum(1 for term in normalized_terms if term in section_text)
        if covered == 0:
            continue
        heading_match = bool(title) and any(term in title.lower() for term in normalized_terms)
        score = covered * 10 + (20 if heading_match else 0)
        if score > best_section_score:
            best_section_score = score
            best_section = section
    if best_section is None:
        return -1

    start, end, _title = best_section
    best_line = start
    best_line_score = -1
    for index in range(start, end + 1):
        score = _line_score(index)
        if score > best_line_score:
            best_line = index
            best_line_score = score
    if best_line_score <= 0:
        best_line = start
    return sum(len(line) + 1 for line in lines[:best_line])


def _resolve_document_location(
    anchors: list[dict[str, Any]],
    line: int,
) -> dict[str, Any]:
    """Resolve a Markdown line to the nearest page/slide/heading anchor."""

    resolved: dict[str, Any] = {}
    for kind in ("page", "slide", "heading"):
        best: dict[str, Any] | None = None
        for anchor in anchors:
            if str(anchor.get("kind") or "") != kind:
                continue
            try:
                anchor_line = int(anchor.get("line") or 0)
            except (TypeError, ValueError):
                continue
            if anchor_line <= line:
                best = anchor
            else:
                break
        if best is None:
            continue
        if kind == "page":
            resolved["page"] = best.get("index")
            resolved["anchor_id"] = f"¶page{best.get('index')}@{line}"
        elif kind == "slide":
            resolved["slide"] = best.get("index")
            if best.get("label"):
                resolved["slide_title"] = best.get("label")
            resolved.setdefault("anchor_id", f"¶slide{best.get('index')}@{line}")
        else:
            resolved["heading"] = best.get("label") or ""
            resolved.setdefault("anchor_id", f"¶h{best.get('index')}@{line}")
        resolved["line_start"] = line
    return resolved


class _AnchorView:
    """Read-only view over an anchor payload stored in search metadata."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        try:
            self.line_start = int(payload.get("line_start") or 0)
        except (TypeError, ValueError):
            self.line_start = 0
        try:
            self.line_end = int(payload.get("line_end") or 0)
        except (TypeError, ValueError):
            self.line_end = 0
        self.line = self.line_start
        self.index = int(payload.get("page") or payload.get("slide") or 0) or 0
        self.label = str(payload.get("heading") or payload.get("slide_title") or "")
        self.payload: dict[str, Any] = {}
        for key in ("anchor_id", "page", "slide", "slide_title", "heading", "markdown_path"):
            value = payload.get(key)
            if value not in {None, ""}:
                self.payload[key] = value


def _compact_anchors(chunks: list[ResourceChunk]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for chunk in chunks:
        metadata = chunk.metadata if isinstance(chunk.metadata, dict) else {}
        if not metadata:
            continue
        compact = {
            key: metadata[key]
            for key in (
                "anchor_id",
                "page",
                "slide",
                "slide_title",
                "heading",
                "markdown_path",
                "line_start",
                "line_end",
            )
            if metadata.get(key) not in {None, ""}
        }
        if compact:
            anchors.append(compact)
    return anchors


def _last_anchor_before(anchors: list[Any], line: int) -> Any | None:
    match = None
    for anchor in anchors:
        if anchor.line <= line:
            match = anchor
        else:
            break
    return match


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

# Loud, never-silent folder index cap (评估 P0 问题 B): a folder larger than
# this is processed up to the cap and the truncation is recorded in metadata
# (`folder_item_truncated`) plus a returned warning — never dropped silently.
MAX_FOLDER_INGEST_ITEMS = 2000


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
