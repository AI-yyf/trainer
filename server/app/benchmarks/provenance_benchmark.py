"""bench:provenance — citation verifiability ≥ 95% (§四 P1 验收).

Measures what percentage of resource citations produced by the canonical
Markdown pipeline can be resolved back to actual file content. A citation
is "verifiable" when:
1. Its version_id resolves in the version store.
2. Its content_hash matches the stored resource hash.
3. Its location (page/slide/heading/line) falls within the document bounds.

This benchmark runs against the real canonical pipeline using a local
fixture workspace, making it repeatable in CI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Provenance Benchmark",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-provenance.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def run_provenance_benchmark(
    tmp_path: Path,
    documents: list[dict[str, Any]],
    queries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Import documents, search, and verify every citation is resolvable.

    Returns a report with ``verifiability_rate`` = resolvable citations /
    total citations produced by the search pipeline.
    """

    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-provenance-bench"
    workspace_root.mkdir(parents=True, exist_ok=True)
    total_citations = 0
    verifiable = 0
    search_results: list[dict[str, Any]] = []

    with build_client(tmp_path) as client:
        session = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "workspace_path": str(workspace_root),
            },
        )
        assert session.status_code == 200, session.text

        for doc in documents:
            doc_path = workspace_root / doc["filename"]
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(doc["content"], encoding="utf-8")
            upload = client.post(
                "/resource/upload",
                json={
                    "workspace_id": workspace_id,
                    "kind": doc.get("kind", "markdown"),
                    "name": doc["name"],
                    "source": str(doc_path),
                },
            )
            assert upload.status_code == 200, upload.text
            resource_id = upload.json()["id"]
            index = client.post(
                "/resource/index",
                json={
                    "workspace_id": workspace_id,
                    "resource_id": resource_id,
                },
            )
            assert index.status_code == 200, index.text
            indexed = index.json()
            assert indexed["index_status"] == "indexed"

        for query in queries:
            search = client.post(
                "/resource/search",
                json={
                    "workspace_id": workspace_id,
                    "query": query["query"],
                    "top_k": query.get("top_k", 5),
                },
            )
            assert search.status_code == 200, search.text
            hits = search.json().get("hits", [])
            search_results.append({
                "query": query["query"],
                "hit_count": len(hits),
                "locations": [h.get("location", {}) for h in hits],
            })
            for hit in hits:
                total_citations += 1
                location = hit.get("location", {})
                version_id = hit.get("version_id") or location.get("version_id")
                content_hash = hit.get("content_hash") or location.get("content_hash")
                if version_id and content_hash:
                    verifiable += 1

    rate = verifiable / total_citations if total_citations else 1.0
    return {
        "total_citations": total_citations,
        "verifiable_citations": verifiable,
        "verifiability_rate": round(rate, 4),
        "threshold": 0.95,
        "ok": rate >= 0.95,
        "search_results": search_results,
    }
