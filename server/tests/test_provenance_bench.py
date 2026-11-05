"""bench:provenance — citation verifiability ≥ 95% (§四 P1 验收)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app

_DOCS = [
    {"name": "Classifier Guide", "filename": "docs/classifier.md",
     "content": "# Classifier\nThe workspace classifier uses heuristic rules.\n"},
    {"name": "Ledger Guide", "filename": "docs/ledger.md",
     "content": "# Cost Ledger\nToken usage is recorded per workspace.\n"},
    {"name": "Reader Guide", "filename": "docs/reader.md",
     "content": "# Reader\nThe reader renders canonical markdown.\n"},
]

_QUERIES = ["classifier heuristic", "cost ledger", "canonical markdown"]


def test_provenance_verifiability(tmp_path: Path) -> None:
    settings = AppSettings(
        app_name="Trainer Provenance Bench",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-provenance.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    with TestClient(create_app(settings)) as client:
        client.post(
            "/session/start",
            json={"workspace_id": "ws-prov", "workspace_name": "prov", "workspace_path": str(workspace)},
        ).json()
        workspace_id = "ws-prov"
        for doc in _DOCS:
            path = workspace / doc["filename"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(doc["content"], encoding="utf-8")
            upload = client.post(
                "/resource/upload",
                json={"workspace_id": workspace_id, "kind": "markdown", "name": doc["name"], "source": str(path)},
            )
            assert upload.status_code == 200, upload.text
            indexed = client.post(
                "/resource/index",
                json={"workspace_id": workspace_id, "resource_id": upload.json()["id"]},
            ).json()
            assert indexed["index_status"] == "indexed"

        total = 0
        verifiable = 0
        for query in _QUERIES:
            search = client.post(
                "/resource/search",
                json={"workspace_id": workspace_id, "query": query, "top_k": 5},
            ).json()
            for hit in search.get("hits", []):
                total += 1
                if hit.get("version_id") and hit.get("content_hash"):
                    verifiable += 1

        assert total >= 3, f"Expected ≥3 citations, got {total}"
        rate = verifiable / total
        assert rate >= 0.95, f"Provenance verifiability {rate:.2%} < 95%"
