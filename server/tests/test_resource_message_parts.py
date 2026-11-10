"""Visible resource grounding for coach replies.

Contract under test:
- successful ``read_resource_excerpt`` results become compact citation parts
  carrying the exact version, anchor and open action (not a second copy of the
  passage text);
- successful ``search_resources`` hits become clickable citations with real
  provenance, and are skipped when the same turn read the resource;
- failed/empty tool results produce no visible part (no fabricated citation);
- web research sources become citable parts carrying their fetched URL.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.llm.resource_message_parts import build_resource_display_parts
from app.llm.tools import ToolContext, _normalize_search_hits, build_default_tool_registry
from app.resources.models import ResourceChunk, ResourceKind
from app.resources.models import ResourceRecord as RegistryResourceRecord


def _read_event(*, ok: bool = True, text: str = "A lock protects the write path.") -> dict[str, Any]:
    return {
        "type": "tool_result",
        "id": "read-1",
        "name": "read_resource_excerpt",
        "ok": ok,
        "result": {
            "ok": ok,
            "tool": "read_resource_excerpt",
            "resource": {
                "id": "resource-queue",
                "name": "Queue locks",
                "kind": "markdown",
                "source": "library/queue-locks.md",
                "content_hash": "sha256-1",
                "version_id": "rv-1",
                "trust_score": 0.82,
                "freshness": "fresh",
            },
            "excerpts": [
                {
                    "anchor_id": "¶chunk:0@4",
                    "paragraph_anchor": "¶spine:ch1:/body/p[3]",
                    "text": text,
                    "start_line": 4,
                    "end_line": 9,
                    "citation_id": "citation:resource-queue:rv-1:abc",
                    "version_id": "rv-1",
                    "content_hash": "sha256-1",
                    "location": {
                        "chunk_id": "chunk-1",
                        "paragraph_anchor": "¶spine:ch1:/body/p[3]",
                    },
                    "truncated": False,
                }
            ],
        },
    }


def test_read_result_becomes_a_visible_original_excerpt() -> None:
    parts = build_resource_display_parts([_read_event()], response_language="en-US")
    assert len(parts) == 1
    part = parts[0]
    assert part["type"] == "citation"
    assert part["resourceId"] == "resource-queue"
    assert part["versionId"] == "rv-1"
    assert part["contentHash"] == "sha256-1"
    assert part["chunkId"] == "¶spine:ch1:/body/p[3]"
    assert part["citationId"] == "citation:resource-queue:rv-1:abc"
    # The transcript carries the identity, not a second copy of the passage.
    assert "text" not in part
    assert part["referenceOrigin"] == "library_read"
    assert part["location"]["chunk_id"] == "chunk-1"
    assert part["location"]["anchor"] == "¶spine:ch1:/body/p[3]"
    assert part["location"]["start_line"] == 4


def test_old_version_excerpt_keeps_its_identity_and_marks_the_current_head() -> None:
    event = _read_event()
    excerpt = event["result"]["excerpts"][0]
    excerpt["stale"] = True
    excerpt["current_version_id"] = "rv-2"
    excerpt["current_content_hash"] = "sha256-2"
    part = build_resource_display_parts([event])[0]
    assert part["versionId"] == "rv-1"
    assert part["stale"] is True
    assert part["currentVersionId"] == "rv-2"
    assert part["currentContentHash"] == "sha256-2"


def test_failed_or_empty_tool_results_never_produce_a_citation() -> None:
    failed = _read_event(ok=False)
    failed["result"]["error"] = "index_missing"
    assert build_resource_display_parts([failed]) == []
    assert build_resource_display_parts([]) == []
    assert build_resource_display_parts([{"type": "tool_call", "name": "read_resource_excerpt"}]) == []


def test_no_match_search_produces_no_visible_citation() -> None:
    event = {
        "type": "tool_result",
        "id": "search-empty",
        "name": "search_resources",
        "ok": True,
        "result": {"ok": True, "total": 0, "hits": []},
    }
    assert build_resource_display_parts([event]) == []


def test_search_normalization_keeps_heading_anchor_from_location() -> None:
    hits = _normalize_search_hits(
        [
            {
                "resource_id": "resource-queue",
                "title": "Queue locks",
                "location": {"anchor_id": "¶h2@5", "line_start": 5, "heading": "Boundary"},
            }
        ]
    )
    assert len(hits) == 1
    assert hits[0]["anchor_id"] == "¶h2@5"
    assert hits[0]["line_start"] == 5


def test_search_hits_become_versioned_citations() -> None:
    event = {
        "type": "tool_result",
        "id": "search-1",
        "name": "search_resources",
        "ok": True,
        "result": {
            "ok": True,
            "tool": "search_resources",
            "auto": True,
            "hits": [
                {
                    "resource_id": "resource-queue",
                    "title": "Queue locks",
                    "source": "library/queue-locks.md",
                    "snippet": "A lock protects the write path.",
                    "citation_id": "citation:resource-queue:rv-1",
                    "version_id": "rv-1",
                    "content_hash": "sha256-1",
                    "location": {"anchor_id": "¶h2@5", "line_start": 5},
                    "source_type": "markdown",
                    "freshness": "fresh",
                    "trust_score": 0.82,
                }
            ],
        },
    }
    parts = build_resource_display_parts([event], response_language="zh-CN")
    assert len(parts) == 1
    part = parts[0]
    assert part["type"] == "citation"
    assert part["resourceId"] == "resource-queue"
    assert part["versionId"] == "rv-1"
    assert part["chunkId"] == "¶h2@5"
    assert part["location"]["start_line"] == 5
    assert part["citationId"] == "citation:resource-queue:rv-1"
    assert "snippet" not in part
    assert part["referenceOrigin"] == "library_auto"
    assert part["label"] == "资料库命中"


def test_search_hit_is_skipped_when_the_same_turn_read_the_resource() -> None:
    search = {
        "type": "tool_result",
        "id": "search-1",
        "name": "search_resources",
        "ok": True,
        "result": {
            "ok": True,
            "hits": [
                {
                    "resource_id": "resource-queue",
                    "title": "Queue locks",
                    "snippet": "A lock protects the write path.",
                }
            ],
        },
    }
    parts = build_resource_display_parts([search, _read_event()])
    assert [part["type"] for part in parts] == ["citation"]
    assert parts[0]["referenceOrigin"] == "library_read"


def test_web_sources_become_citable_with_their_fetched_url() -> None:
    event = {
        "type": "tool_result",
        "id": "web-1",
        "name": "search_learning_materials",
        "ok": True,
        "result": {
            "ok": True,
            "sources": [
                {
                    "id": "source-1",
                    "title": "SQLite locking",
                    "url": "https://sqlite.org/lockingv3.html",
                    "snippet": "A database lock protects the write path.",
                    "evidence_excerpt": "A database lock protects the write path.",
                    "fetched_at": "2026-11-10T01:02:03Z",
                    "freshness": "fresh",
                    "trust_score": 0.9,
                }
            ],
        },
    }
    parts = build_resource_display_parts([event])
    assert len(parts) == 1
    part = parts[0]
    assert part["type"] == "citation"
    assert part["resourceId"] == "web:https://sqlite.org/lockingv3.html"
    assert part["url"] == "https://sqlite.org/lockingv3.html"
    assert part["citationId"] == "source-1"
    assert part["referenceOrigin"] == "web_research"
    assert part["fetchedAt"] == "2026-11-10T01:02:03Z"
    assert "snippet" not in part


class _RegistryStub:
    def __init__(self, resource: RegistryResourceRecord, chunks: list[ResourceChunk]):
        self._resource = resource
        self._chunks = chunks

    def get(self, resource_id: str) -> RegistryResourceRecord | None:
        return self._resource if resource_id == self._resource.id else None

    def list_chunks(self, resource_id: str) -> list[ResourceChunk]:
        return list(self._chunks) if resource_id == self._resource.id else []


class _ResourceServiceStub:
    def __init__(self, registry: _RegistryStub):
        self.registry = registry


class _VersionStoreStub:
    def __init__(self, version_id: str = "rv-1", content_hash: str = "sha256-1"):
        self._version_id = version_id
        self._content_hash = content_hash

    def current_version(self, workspace_id: str, resource_id: str) -> dict[str, str]:
        return {"version_id": self._version_id, "content_hash": self._content_hash}


class _RuntimeStub:
    def __init__(
        self,
        resource_service: _ResourceServiceStub,
        *,
        version_store: _VersionStoreStub | None = None,
    ):
        self.resource_service = resource_service
        self.resource_version_store = version_store or _VersionStoreStub()


@pytest.mark.asyncio
async def test_read_tool_result_carries_anchor_version_and_location() -> None:
    resource = RegistryResourceRecord.create(
        kind=ResourceKind.MARKDOWN,
        source_uri="library/queue-locks.md",
        title="Queue locks",
        metadata={
            "knowledge_fragments": [
                {
                    "paragraph_anchor": "¶spine:ch1:/body/p[3]",
                    "citation_id": "citation:resource:rv-1:abc",
                    "version_id": "rv-1",
                    "content_hash": "sha256-1",
                    "location": {
                        "chunk_id": "chunk-1",
                        "paragraph_anchor": "¶spine:ch1:/body/p[3]",
                    },
                }
            ]
        },
    )
    chunks = [
        ResourceChunk(
            resource_id=resource.id,
            chunk_id="chunk-1",
            text="A lock protects the write path.",
            order=0,
            start_line=4,
            end_line=9,
        )
    ]
    runtime = _RuntimeStub(_ResourceServiceStub(_RegistryStub(resource, chunks)))
    result = await build_default_tool_registry().invoke(
        ToolContext(
            runtime=runtime,
            workspace_id="ws-1",
            session_id="session-1",
            extra={},
        ),
        "read_resource_excerpt",
        {"resource_id": resource.id, "anchor_id": "¶spine:ch1:/body/p[3]"},
    )
    assert result["ok"] is True
    excerpt = result["excerpts"][0]
    assert excerpt["citation_id"] == "citation:resource:rv-1:abc"
    assert excerpt["version_id"] == "rv-1"
    assert excerpt["content_hash"] == "sha256-1"
    assert excerpt["location"]["chunk_id"] == "chunk-1"
    assert excerpt["location"]["start_line"] == 4
    assert excerpt["truncated"] is False
    assert excerpt["stale"] is False

    synthetic_result = await build_default_tool_registry().invoke(
        ToolContext(
            runtime=runtime,
            workspace_id="ws-1",
            session_id="session-1",
            extra={},
        ),
        "read_resource_excerpt",
        {"resource_id": resource.id, "anchor_id": "¶chunk:0@4"},
    )
    synthetic_excerpt = synthetic_result["excerpts"][0]
    assert synthetic_excerpt["citation_id"] == f"citation:{resource.id}:rv-1"

    stale_runtime = _RuntimeStub(
        runtime.resource_service,
        version_store=_VersionStoreStub("rv-2", "sha256-2"),
    )
    stale_result = await build_default_tool_registry().invoke(
        ToolContext(
            runtime=stale_runtime,
            workspace_id="ws-1",
            session_id="session-1",
            extra={},
        ),
        "read_resource_excerpt",
        {"resource_id": resource.id, "anchor_id": "¶spine:ch1:/body/p[3]"},
    )
    stale_excerpt = stale_result["excerpts"][0]
    assert stale_excerpt["version_id"] == "rv-1"
    assert stale_excerpt["stale"] is True
    assert stale_excerpt["current_version_id"] == "rv-2"
    assert stale_excerpt["current_content_hash"] == "sha256-2"
