"""End-to-end resource pipeline: import -> canonical Markdown -> search/cite."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.resources.canonical import read_front_matter
from tests.test_canonical_markdown import _docx_bytes, _pdf_bytes, _pptx_bytes


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Canonical Pipeline Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-canonical.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def start_session(client: TestClient, workspace_root: Path, workspace_id: str) -> str:
    workspace_root.mkdir(parents=True, exist_ok=True)
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": workspace_id,
            "workspace_path": str(workspace_root),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def upload_and_index(
    client: TestClient,
    *,
    workspace_id: str,
    kind: str,
    name: str,
    source: Path,
) -> dict:
    upload = client.post(
        "/resource/upload",
        json={
            "workspace_id": workspace_id,
            "kind": kind,
            "name": name,
            "source": str(source),
        },
    )
    assert upload.status_code == 200, upload.text
    resource_id = upload.json()["id"]
    indexed = client.post(
        "/resource/index",
        json={
            "workspace_id": workspace_id,
            "resource_id": resource_id,
            "enable_network": False,
        },
    )
    assert indexed.status_code == 200, indexed.text
    return indexed.json()


def test_docx_becomes_canonical_markdown_and_is_searchable(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-docx"
    docx_path = workspace_root / "docs" / "distributed-systems.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())

    with build_client(tmp_path) as client:
        session_id = start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="docx",
            name="Distributed Systems Notes",
            source=docx_path,
        )

        assert indexed["parse_status"] == "parsed", indexed.get("warnings")
        assert indexed["index_status"] == "indexed"
        assert indexed["parser"] == "docx-v1"
        assert indexed["page_count"] == 2
        markdown_relative = indexed["canonical_markdown_path"]
        assert markdown_relative.startswith("Trainer Library/.trainer-resources/markdown/")
        markdown_path = workspace_root / markdown_relative
        assert markdown_path.is_file()
        markdown = markdown_path.read_text(encoding="utf-8")
        front = read_front_matter(markdown)
        assert front["resource_id"] == indexed["id"]
        assert front["source_type"] == "docx"
        assert front["parser"] == "docx-v1"
        assert front["content_hash"].startswith("sha256:")
        assert front["version_id"]
        assert "## Replication" in markdown
        assert "| Quorum | Meaning |" in markdown

        original_relative = indexed["canonical_original_path"]
        assert original_relative.startswith("Trainer Library/.trainer-resources/originals/")
        original = workspace_root / original_relative
        assert original.is_file()
        assert original.read_bytes() == docx_path.read_bytes()

        search = client.post(
            "/resource/search",
            json={
                "workspace_id": workspace_id,
                "session_id": session_id,
                "query": "quorum reads intersect",
                "top_k": 5,
            },
        )
        assert search.status_code == 200, search.text
        hits = search.json()["hits"]
        assert hits, search.json()
        hit = hits[0]
        assert hit["resource_id"] == indexed["id"]
        assert hit["location"]["path"] == markdown_relative
        assert hit["location"].get("heading") == "Quorum"
        assert hit["location"].get("markdown_path") == markdown_relative

        # The agent context reads the Markdown body, not the binary source.
        runtime = client.app.state.runtime
        context = runtime.resource_service.build_requested_resource_context(
            workspace_id,
            [indexed["id"]],
        )
        fragments = context.get("resource_fragments") or []
        assert fragments, context
        assert "Quorum" in fragments[0]["snippet"] or "quorum" in fragments[0]["snippet"]
        assert fragments[0]["location"]["markdown_path"] == markdown_relative
        assert fragments[0]["location"]["heading"] == "Distributed Systems Notes"


def test_pptx_citations_point_to_slide_anchors(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-pptx"
    pptx_path = workspace_root / "slides" / "consensus.pptx"
    pptx_path.parent.mkdir(parents=True, exist_ok=True)
    pptx_path.write_bytes(_pptx_bytes())

    with build_client(tmp_path) as client:
        session_id = start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="pptx",
            name="Consensus Deck",
            source=pptx_path,
        )
        assert indexed["parse_status"] == "parsed", indexed.get("warnings")
        assert indexed["parser"] == "pptx-v1"
        assert indexed["slide_count"] == 3
        markdown = (workspace_root / indexed["canonical_markdown_path"]).read_text(encoding="utf-8")
        front = read_front_matter(markdown)
        assert front["slide_count"] == 3
        assert {"kind": "slide", "index": 1, "line": 1, "label": "Consensus"} in front["anchors"]
        assert "## Slide 2 — Draft appendix" in markdown
        assert any("Slide 2 is hidden" in warning for warning in indexed["warnings"])

        search = client.post(
            "/resource/search",
            json={
                "workspace_id": workspace_id,
                "session_id": session_id,
                "query": "Explain why a majority is enough",
                "top_k": 5,
            },
        )
        assert search.status_code == 200, search.text
        hits = search.json()["hits"]
        assert hits
        assert hits[0]["location"].get("slide") == 1


def test_pdf_citations_point_to_page_anchors(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-pdf"
    pdf_path = workspace_root / "papers" / "replication.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(
        _pdf_bytes(["Chapter one describes leases.", "Chapter two describes quorum reads."])
    )

    with build_client(tmp_path) as client:
        session_id = start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="pdf",
            name="Replication Paper",
            source=pdf_path,
        )
        assert indexed["index_status"] == "indexed", indexed.get("warnings")
        assert indexed["parser"] == "pdf-v1"
        assert indexed["page_count"] == 2

        search = client.post(
            "/resource/search",
            json={
                "workspace_id": workspace_id,
                "session_id": session_id,
                "query": "quorum reads",
                "top_k": 5,
            },
        )
        assert search.status_code == 200, search.text
        hits = search.json()["hits"]
        assert hits
        assert hits[0]["location"].get("page") == 2


def test_legacy_doc_reports_actionable_failure_not_a_fake_import(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-legacy"
    doc_path = workspace_root / "old.doc"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_bytes(b"\xd0\xcf\x11\xe0legacy-word")

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="docx",
            name="Legacy Doc",
            source=doc_path,
        )
        assert indexed["index_status"] == "failed"
        assert indexed["parse_status"] == "failed"
        assert any("save the file as .docx" in warning for warning in indexed["warnings"])
        assert indexed["canonical_markdown_path"] in {None, ""}


def test_importing_identical_bytes_under_two_names_dedupes_by_content_hash(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-dedupe"
    first = workspace_root / "a" / "notes.docx"
    second = workspace_root / "b" / "notes-copy.docx"
    first.parent.mkdir(parents=True, exist_ok=True)
    second.parent.mkdir(parents=True, exist_ok=True)
    first.write_bytes(_docx_bytes())
    second.write_bytes(_docx_bytes())

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        first_index = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="docx",
            name="Notes A",
            source=first,
        )
        second_index = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="docx",
            name="Notes B",
            source=second,
        )
        assert "duplicate" in first_index["quality_flags"] or "duplicate" in second_index["quality_flags"]
        assert second_index["content_hash"] == first_index["content_hash"]


def test_resource_excerpt_tool_survives_a_cold_registry(tmp_path: Path) -> None:
    """A restarted sidecar keeps a durable Markdown read path for the agent."""

    import asyncio

    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-excerpt-restart"
    docx_path = workspace_root / "docs" / "storage.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="docx",
            name="Storage Notes",
            source=docx_path,
        )
        runtime = client.app.state.runtime
        service = runtime.resource_service
        # Cold registry: a fresh process has no in-memory resources or chunks.
        service.registry._resources.clear()
        service.registry._chunks.clear()

        from app.llm.tools import ToolContext, _handle_read_resource_excerpt

        context = ToolContext(runtime=runtime, workspace_id=workspace_id)
        result = asyncio.run(
            _handle_read_resource_excerpt(
                context,
                {"resource_id": indexed["id"], "chars": 800},
            )
        )
        assert result["ok"] is True, result
        excerpt = result["excerpts"][0]["text"]
        assert "Distributed Systems Notes" in excerpt
        assert "Replication" in excerpt


def test_reindex_after_source_change_regenerates_markdown_and_keeps_history(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-reindex"
    docx_path = workspace_root / "notes.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        first = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="docx",
            name="Notes",
            source=docx_path,
        )
        first_path = workspace_root / first["canonical_markdown_path"]
        first_front = read_front_matter(first_path.read_text(encoding="utf-8"))
        first_hash = first_front["content_hash"]

        # Replace the document with different text and refresh the index.
        import zipfile

        replacement = tmp_path / "replacement.docx"
        replacement.write_bytes(_docx_bytes())
        with zipfile.ZipFile(replacement) as source_archive, zipfile.ZipFile(
            docx_path, "w"
        ) as target_archive:
            for item in source_archive.infolist():
                data = source_archive.read(item.filename)
                if item.filename == "word/document.xml":
                    data = data.replace(b"Replication keeps copies consistent.", b"Leases bound staleness.")
                target_archive.writestr(item, data)

        refreshed = client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": first["id"]},
        ).json()
        assert refreshed["index_status"] == "indexed"
        second_front = read_front_matter(
            (workspace_root / refreshed["canonical_markdown_path"]).read_text(encoding="utf-8")
        )
        assert second_front["content_hash"] != first_hash
        assert second_front["version_id"] != first_front["version_id"]
        assert "Leases bound staleness." in (
            workspace_root / refreshed["canonical_markdown_path"]
        ).read_text(encoding="utf-8")


def test_import_stages_analyze_materialize_index_do_real_work(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-staged-import"
    docx_path = workspace_root / "docs" / "staged-notes.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        upload = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "docx",
                "name": "Staged Notes",
                "source": str(docx_path),
            },
        )
        assert upload.status_code == 200, upload.text
        resource_id = upload.json()["id"]

        analyzed = client.post(
            "/resource/canonicalize/analyze",
            json={"workspace_id": workspace_id, "resource_ids": [resource_id]},
        )
        assert analyzed.status_code == 200, analyzed.text
        analyze_item = analyzed.json()["items"][0]
        assert analyze_item["ok"] is True
        assert analyze_item["parser"] == "docx-v1"
        assert analyze_item["page_count"] == 2
        assert analyze_item["image_count"] == 1
        assert analyze_item["table_count"] == 1

        materialized = client.post(
            "/resource/canonicalize/materialize",
            json={"workspace_id": workspace_id, "resource_ids": [resource_id]},
        )
        assert materialized.status_code == 200, materialized.text
        materialize_item = materialized.json()["items"][0]
        assert materialize_item["ok"] is True
        assert materialize_item["asset_count"] == 1
        assert materialize_item["table_count"] == 1
        markdown_path = workspace_root / materialize_item["markdown_path"]
        assert markdown_path.is_file()
        first_write = markdown_path.stat().st_mtime_ns

        indexed = client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": resource_id},
        )
        assert indexed.status_code == 200, indexed.text
        assert indexed.json()["index_status"] == "indexed"
        assert indexed.json()["canonical_markdown_path"] == materialize_item["markdown_path"]
        # Indexing reuses the materialized document instead of rewriting it.
        assert markdown_path.stat().st_mtime_ns == first_write
        assert indexed.json()["knowledge_fragments"]


def test_analyze_reports_legacy_office_failure_without_writing(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-staged-legacy"
    legacy = workspace_root / "old.doc"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"\xd0\xcf\x11\xe0legacy")

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        upload = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "docx",
                "name": "Legacy",
                "source": str(legacy),
            },
        ).json()
        analyzed = client.post(
            "/resource/canonicalize/analyze",
            json={"workspace_id": workspace_id, "resource_ids": [upload["id"]]},
        )
        item = analyzed.json()["items"][0]
        assert analyzed.json()["ok"] is False
        assert item["ok"] is False
        assert "save the file as .docx" in item["error"]


def test_identical_search_within_ttl_reuses_cached_response(tmp_path: Path) -> None:
    """P1 检索复用: the same query inside the TTL window must not re-run FTS5."""


    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-search-cache"
    docx_path = workspace_root / "notes.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="docx",
            name="Cache Probe",
            source=docx_path,
        )

        runtime = client.app.state.runtime
        service = runtime.resource_service
        search_calls = {"count": 0}
        original_search = service._search_index(workspace_id).search

        def counting_search(*args, **kwargs):
            search_calls["count"] += 1
            return original_search(*args, **kwargs)

        service._search_cache.clear()
        probe_index = service._search_index(workspace_id)
        probe_index.search = counting_search

        first = client.post(
            "/resource/search",
            json={"workspace_id": workspace_id, "query": "quorum", "top_k": 5},
        ).json()
        assert first["hits"], first
        calls_after_first = search_calls["count"]

        second = client.post(
            "/resource/search",
            json={"workspace_id": workspace_id, "query": "quorum", "top_k": 5},
        ).json()
        assert second["hits"] == first["hits"] or second["total"] == first["total"]
        assert search_calls["count"] == calls_after_first  # served from cache

        # A corpus change invalidates the cache: indexing runs FTS5 again.
        client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )
        client.post(
            "/resource/search",
            json={"workspace_id": workspace_id, "query": "quorum", "top_k": 5},
        )
        assert search_calls["count"] > calls_after_first
