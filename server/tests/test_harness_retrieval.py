"""Phase 2 — Harness 分层检索强化验收.

失败优先：此前 search_resources 返回未截断的命中全文（全库无差别注入），
且缓存对 agent 不可见。现在：
- 每个 mode 有 excerpt 预算，命中文本超预算即截断并标 truncated；
- 响应携带 retrieval_plan（分层读取入口）与 cache 命中统计；
- verify 模式仍只保留可验证命中。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.llm.tools import ToolContext, _handle_search_resources, _retrieval_plan, _trim_hit_text
from app.resources.service import ResourceService
from app.db.repository import TrainerRepository


def test_retrieval_plan_budgets_are_layered() -> None:
    assert _retrieval_plan("broad", 5)["excerpt_budget"] == 180
    assert _retrieval_plan("narrow", 5)["excerpt_budget"] == 300
    assert _retrieval_plan("verify", 4)["excerpt_budget"] == 420
    assert _retrieval_plan("narrow", 5)["read_more"].startswith("read_resource_excerpt")


def test_trim_hit_text_respects_budget_and_marks_truncation() -> None:
    hit = {
        "resource_id": "r1",
        "summary": "x" * 500,
        "excerpt": "short",
        "version_id": "v1",
        "content_hash": "h1",
    }
    trimmed = _trim_hit_text(hit, 180)
    assert len(trimmed["summary"]) <= 181
    assert trimmed["summary"].endswith("…")
    assert trimmed["truncated"] is True
    # Citations and identifiers are never touched.
    assert trimmed["version_id"] == "v1"
    assert trimmed["content_hash"] == "h1"
    assert trimmed["excerpt"] == "short"


class _StubSearchService:
    def __init__(self, hits: list[dict]) -> None:
        self._hits = hits
        self.calls: list[dict] = []

    def search(self, **kwargs):  # noqa: ANN003 - mirrors ResourceService.search
        self.calls.append(kwargs)
        return {
            "query": kwargs["query"],
            "total": len(self._hits),
            "ranking_strategy": "lexical_first",
            "filters": {},
            "hits": self._hits,
        }

    def search_cache_stats(self) -> dict:
        return {"hits": 1, "misses": 2, "hit_rate": 0.333, "ttl_seconds": 120}


def _context(service: object) -> ToolContext:
    return ToolContext(runtime=SimpleNamespace(resource_service=service), workspace_id="ws")


def test_search_tool_applies_budget_and_reports_cache() -> None:
    long_hits = [
        {
            "resource_id": f"r{index}",
            "summary": "y" * 900,
            "trust_score": 0.9,
            "index_state": "indexed",
        }
        for index in range(3)
    ]
    service = _StubSearchService(long_hits)
    result = asyncio.run(_handle_search_resources(_context(service), {"query": "state flow", "limit": 3}))
    assert result["ok"] is True
    assert result["retrieval_plan"]["excerpt_budget"] == 300
    for hit in result["hits"]:
        assert len(hit["summary"]) <= 301
        assert hit["truncated"] is True
    assert result["cache"]["ttl_seconds"] == 120
    assert result["cache"]["hits"] == 1


def test_verify_mode_keeps_only_verification_ready_hits() -> None:
    hits = [
        {"resource_id": "good", "summary": "ok", "trust_score": 0.9, "index_state": "indexed", "freshness": "fresh"},
        {"resource_id": "weak", "summary": "weak", "trust_score": 0.1, "index_state": "indexed"},
    ]
    service = _StubSearchService(hits)
    result = asyncio.run(
        _handle_search_resources(_context(service), {"query": "evidence", "mode": "verify", "limit": 4})
    )
    assert [hit["resource_id"] for hit in result["hits"]] == ["good"]
    assert result["retrieval_plan"]["excerpt_budget"] == 420


def test_resource_service_exposes_cache_evidence(tmp_path: Path) -> None:
    from app.ingest.service import IngestService
    from app.memory.semantic import SemanticMemory

    repository = TrainerRepository(tmp_path / "harness.db")
    service = ResourceService(
        repository=repository,
        ingest_service=IngestService(),
        semantic_memory=SemanticMemory(tmp_path / "semantic"),
        data_root=tmp_path,
    )
    stats = service.search_cache_stats()
    assert stats["hits"] == 0 and stats["misses"] == 0
    assert stats["ttl_seconds"] == 120
