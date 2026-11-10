"""Visible resource-grounding parts for coach messages.

The agent's resource tools already return real chunk text, version-scoped
citation ids and paragraph anchors, but ``build_agent_message_parts`` used to
keep them inside opaque tool events.  This module turns successful tool results
into typed message parts so the workbench can show the actual passage, its
provenance and an explicit "open the full resource" action.

Only successful results are projected.  A failed, missing or empty result
produces no part, so the UI can never display a citation that the library did
not return.
"""

from __future__ import annotations

from typing import Any

_MAX_READ_EXCERPTS = 3
_MAX_SEARCH_CITATIONS = 3
_MAX_WEB_CITATIONS = 4


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_text(value: object) -> str:
    return str(value or "").strip()


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _labels(response_language: str | None) -> dict[str, str]:
    if str(response_language or "").lower().startswith("zh"):
        return {
            "excerpt": "资料原文",
            "library_match": "资料库命中",
            "web_source": "联网来源",
            "version": "版本",
            "location": "位置",
            "citation": "引用",
        }
    return {
        "excerpt": "Original passage",
        "library_match": "Library match",
        "web_source": "Web source",
        "version": "Version",
        "location": "Location",
        "citation": "Citation",
    }


def _event_result(item: dict[str, Any]) -> dict[str, Any] | None:
    if _as_text(item.get("type")) != "tool_result":
        return None
    result = item.get("result")
    if not isinstance(result, dict):
        return None
    if result.get("ok") is False:
        return None
    return result


def _event_tool_name(item: dict[str, Any], result: dict[str, Any]) -> str:
    return _as_text(item.get("name")) or _as_text(result.get("tool")) or _as_text(item.get("tool_name"))


def _part_key(part: dict[str, Any]) -> str:
    return "|".join(
        [
            _as_text(part.get("type")),
            _as_text(part.get("resourceId")),
            _as_text(part.get("versionId")),
            _as_text(part.get("chunkId")),
            _as_text(part.get("citationId")),
            _as_text(part.get("text"))[:80],
        ]
    )


def _append_unique(parts: list[dict[str, Any]], seen: set[str], part: dict[str, Any]) -> None:
    key = _part_key(part)
    if key in seen:
        return
    seen.add(key)
    parts.append(part)


def _provenance_location(
    base: object,
    *,
    anchor: str,
    start_line: int | None,
    end_line: int | None,
) -> dict[str, Any]:
    location = _as_dict(base)
    if anchor:
        location.setdefault("anchor", anchor)
    if start_line is not None:
        location.setdefault("start_line", start_line)
    if end_line is not None:
        location.setdefault("end_line", end_line)
    return location


def _read_resource_ids(events: list[dict[str, Any]]) -> set[str]:
    resource_ids: set[str] = set()
    for item in events:
        result = _event_result(item)
        if result is None:
            continue
        if _event_tool_name(item, result) != "read_resource_excerpt":
            continue
        resource = _as_dict(result.get("resource"))
        resource_id = _as_text(resource.get("id"))
        if resource_id:
            resource_ids.add(resource_id)
    return resource_ids


def _read_citation_parts(
    result: dict[str, Any],
    labels: dict[str, str],
) -> list[dict[str, Any]]:
    """Compact citations for the passages a read tool actually returned.

    The passage text stays in the tool result and in the resource itself; the
    transcript only carries the identity and the open-at-anchor action.
    """

    resource = _as_dict(result.get("resource"))
    resource_id = _as_text(resource.get("id"))
    if not resource_id:
        return []
    resource_name = _as_text(resource.get("name")) or resource_id
    source = _as_text(resource.get("source"))
    kind = _as_text(resource.get("kind"))
    content_hash = _as_text(resource.get("content_hash"))
    trust_score = _as_float(resource.get("trust_score"))
    freshness = _as_text(resource.get("freshness"))
    raw_excerpts = result.get("excerpts")
    if not isinstance(raw_excerpts, list):
        return []

    parts: list[dict[str, Any]] = []
    for raw in raw_excerpts[:_MAX_READ_EXCERPTS]:
        excerpt = _as_dict(raw)
        # A successful read always returns passage text; require it as the
        # evidence that this citation names a real, readable location.
        if not _as_text(excerpt.get("text")):
            continue
        anchor = _as_text(excerpt.get("paragraph_anchor")) or _as_text(excerpt.get("anchor_id"))
        start_line = _as_int(excerpt.get("start_line"))
        end_line = _as_int(excerpt.get("end_line"))
        version_id = _as_text(excerpt.get("version_id")) or _as_text(resource.get("version_id"))
        excerpt_hash = _as_text(excerpt.get("content_hash")) or content_hash
        citation_id = _as_text(excerpt.get("citation_id"))
        part: dict[str, Any] = {
            "type": "citation",
            "resourceId": resource_id,
            "label": labels["excerpt"],
            "title": resource_name,
            "referenceOrigin": "library_read",
            "location": _provenance_location(
                excerpt.get("location"),
                anchor=anchor,
                start_line=start_line,
                end_line=end_line,
            ),
        }
        if anchor:
            part["chunkId"] = anchor
        if version_id:
            part["versionId"] = version_id
        if excerpt_hash:
            part["contentHash"] = excerpt_hash
        if citation_id:
            part["citationId"] = citation_id
        if source:
            part["source"] = source
        part["sourceType"] = kind or "resource"
        if trust_score is not None:
            part["trustScore"] = trust_score
        if freshness:
            part["freshness"] = freshness
        if excerpt.get("stale") is True:
            part["stale"] = True
            current_version_id = _as_text(excerpt.get("current_version_id"))
            if current_version_id:
                part["currentVersionId"] = current_version_id
            current_content_hash = _as_text(excerpt.get("current_content_hash"))
            if current_content_hash:
                part["currentContentHash"] = current_content_hash
        parts.append(part)
    return parts


def _search_hit_parts(
    result: dict[str, Any],
    labels: dict[str, str],
    *,
    read_resource_ids: set[str],
    auto: bool,
) -> list[dict[str, Any]]:
    raw_hits = result.get("hits")
    if not isinstance(raw_hits, list):
        return []
    parts: list[dict[str, Any]] = []
    for raw in raw_hits[:_MAX_SEARCH_CITATIONS]:
        hit = _as_dict(raw)
        resource_id = _as_text(hit.get("resource_id")) or _as_text(hit.get("id"))
        if not resource_id or resource_id in read_resource_ids:
            continue
        title = _as_text(hit.get("title")) or resource_id
        location = _as_dict(hit.get("location"))
        anchor = (
            _as_text(hit.get("anchor_id"))
            or _as_text(location.get("anchor_id"))
            or _as_text(location.get("paragraph_anchor"))
            or _as_text(location.get("chunk_id"))
        )
        part: dict[str, Any] = {
            "type": "citation",
            "resourceId": resource_id,
            "label": labels["library_match"],
            "title": title,
            "referenceOrigin": "library_auto" if auto else "library",
        }
        source = _as_text(hit.get("source")) or _as_text(hit.get("path"))
        if source:
            part["source"] = source
        source_type = _as_text(hit.get("source_type")) or _as_text(hit.get("kind"))
        if source_type:
            part["sourceType"] = source_type
        version_id = _as_text(hit.get("version_id"))
        if version_id:
            part["versionId"] = version_id
        content_hash = _as_text(hit.get("content_hash"))
        if content_hash:
            part["contentHash"] = content_hash
        if anchor:
            part["chunkId"] = anchor
        if location or anchor:
            part["location"] = _provenance_location(
                location,
                anchor=anchor,
                start_line=_as_int(hit.get("line_start")) or _as_int(location.get("line_start")),
                end_line=_as_int(hit.get("line_end")) or _as_int(location.get("line_end")),
            )
        citation_id = _as_text(hit.get("citation_id"))
        if citation_id:
            part["citationId"] = citation_id
        trust_score = _as_float(hit.get("trust_score"))
        if trust_score is not None:
            part["trustScore"] = trust_score
        freshness = _as_text(hit.get("freshness"))
        if freshness:
            part["freshness"] = freshness
        if hit.get("stale") is True:
            part["stale"] = True
            current_version_id = _as_text(hit.get("current_version_id"))
            if current_version_id:
                part["currentVersionId"] = current_version_id
            current_content_hash = _as_text(hit.get("current_content_hash"))
            if current_content_hash:
                part["currentContentHash"] = current_content_hash
        parts.append(part)
    return parts


def _web_source_parts(result: dict[str, Any], labels: dict[str, str]) -> list[dict[str, Any]]:
    raw_sources = result.get("sources")
    if not isinstance(raw_sources, list):
        return []
    parts: list[dict[str, Any]] = []
    for raw in raw_sources[:_MAX_WEB_CITATIONS]:
        source = _as_dict(raw)
        url = _as_text(source.get("url"))
        title = _as_text(source.get("title")) or url
        if not url or not title:
            continue
        part: dict[str, Any] = {
            "type": "citation",
            "resourceId": f"web:{url}",
            "url": url,
            "label": labels["web_source"],
            "title": title,
            "source": url,
            "sourceType": _as_text(source.get("source")) or "web",
            "referenceOrigin": "web_research",
        }
        fetched_at = _as_text(source.get("fetched_at"))
        if fetched_at:
            part["fetchedAt"] = fetched_at
        freshness = _as_text(source.get("freshness"))
        if freshness:
            part["freshness"] = freshness
        trust_score = _as_float(source.get("trust_score"))
        if trust_score is not None:
            part["trustScore"] = trust_score
        source_id = _as_text(source.get("id"))
        if source_id:
            part["citationId"] = source_id
        parts.append(part)
    return parts


def build_resource_display_parts(
    raw_events: object,
    *,
    response_language: str | None = None,
) -> list[dict[str, Any]]:
    """Project successful library/web tool results into visible parts.

    Order follows the tool trail.  Search hits are skipped for resources that
    were also read in the same turn so the transcript shows the fuller excerpt
    instead of a duplicate snippet card.
    """

    if not isinstance(raw_events, list):
        return []
    events = [item for item in raw_events if isinstance(item, dict)]
    if not events:
        return []

    labels = _labels(response_language)
    read_resource_ids = _read_resource_ids(events)
    parts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in events:
        result = _event_result(item)
        if result is None:
            continue
        tool_name = _event_tool_name(item, result)
        if tool_name == "read_resource_excerpt":
            for part in _read_citation_parts(result, labels):
                _append_unique(parts, seen, part)
        elif tool_name == "search_resources":
            for part in _search_hit_parts(
                result,
                labels,
                read_resource_ids=read_resource_ids,
                auto=result.get("auto") is True,
            ):
                _append_unique(parts, seen, part)
        elif tool_name == "search_learning_materials":
            for part in _web_source_parts(result, labels):
                _append_unique(parts, seen, part)
    return parts
