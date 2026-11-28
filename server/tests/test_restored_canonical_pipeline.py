"""End-to-end resource pipeline: import -> canonical Markdown -> search/cite.

Restored from server/tests/test_canonical_resource_pipeline.py at df0a3e2a^ (deleted in
df0a3e2a). Every old assertion is kept. What was adapted, and why:

* the location of the canonical copy. The old tests read it at
  ``workspace_root / <relative>``, i.e. ``<workspace folder>/Trainer Library/...``. On a
  cold start (no learning folder bound, the old ``data_dir=tmp_path/"data"`` layout) that
  folder is the learner's code project, so the copy now lives under the sidecar data root
  at ``<data_dir>/canonical-resources/<workspace slug>/Trainer Library/...``. Each
  ``workspace_root`` in a location became ``carrier_root``, and every test that located the
  copy also asserts that the workspace folder gained no ``Trainer Library`` directory.
* each of those tests now also runs with a bound learning folder
  (``data_dir=<LibraryRoot>/.trainer/runtime``), where nothing changed: the copy is under
  ``<LibraryRoot>/Trainer Library/...``. ``test_pdf_citations_point_to_page_anchors`` never
  located the copy and is unchanged.
* the imports: the byte builders come from canonical_doc_fixtures.py instead of the deleted
  test_canonical_markdown.py, and pymupdf (installed) is imported directly instead of
  through ``pytest.importorskip``.
* the runtime is reached through a typed ``_runtime(client)`` helper instead of
  ``client.app.state.runtime``, which pyright rejects because Starlette types
  ``TestClient.app`` as the ASGI callable union. That also adds one not-None assert on the
  optional ``sandbox_service`` and a ``dict[str, Any]`` annotation on the agent context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf
import pytest
from canonical_doc_fixtures import _docx_bytes, _pdf_bytes, _pptx_bytes
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.runtime import TrainerRuntime
from app.core.settings import AppSettings
from app.main import create_app
from app.resources.canonical import read_front_matter
from app.resources.canonical_store import managed_workspace_root

LAYOUTS = pytest.mark.parametrize("bound", [False, True], ids=["cold-start", "bound-library"])


def _runtime(client: TestClient) -> TrainerRuntime:
    """The sidecar runtime behind a test client.

    Starlette declares ``TestClient.app`` as the ``ASGIApp`` callable union, so the
    ``FastAPI`` (and runtime) narrowing has to happen at runtime before ``.state``.
    """
    application = client.app
    assert isinstance(application, FastAPI), "test client must wrap the Trainer FastAPI app"
    runtime = application.state.runtime
    assert isinstance(runtime, TrainerRuntime), "FastAPI app must expose a TrainerRuntime"
    return runtime


def data_dir_for(tmp_path: Path, *, bound: bool) -> Path:
    """The sidecar data root: ``<LibraryRoot>/.trainer/runtime`` once a folder is bound."""
    if bound:
        return tmp_path / "Library Root" / ".trainer" / "runtime"
    return tmp_path / "data"


def carrier_root_for(tmp_path: Path, workspace_id: str, *, bound: bool) -> Path:
    """The root that owns ``Trainer Library/`` in this layout.

    A bound learning folder is the library root. On a cold start the workspace folder is
    the learner's code project, so Trainer keeps the library under its own data root.
    """
    if bound:
        return data_dir_for(tmp_path, bound=True).parent.parent
    return managed_workspace_root(data_dir_for(tmp_path, bound=False), workspace_id)


def build_client(tmp_path: Path, *, bound: bool = False) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Canonical Pipeline Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir_for(tmp_path, bound=bound),
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


@LAYOUTS
def test_docx_becomes_canonical_markdown_and_is_searchable(tmp_path: Path, bound: bool) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-docx"
    docx_path = workspace_root / "docs" / "distributed-systems.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())
    carrier_root = carrier_root_for(tmp_path, workspace_id, bound=bound)

    with build_client(tmp_path, bound=bound) as client:
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
        markdown_path = carrier_root / markdown_relative
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

        # md-only: the library keeps the canonical Markdown, never a binary
        # copy. The learner's own source file outside the library is untouched.
        assert indexed["kind"] == "markdown"
        assert indexed["canonical_original_path"] == ""
        originals = carrier_root / "Trainer Library/.trainer-resources/originals"
        assert not originals.exists() or not any(originals.rglob("*"))

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
        runtime = _runtime(client)
        context: dict[str, Any] = runtime.resource_service.build_requested_resource_context(
            workspace_id,
            [indexed["id"]],
        )
        fragments = context.get("resource_fragments") or []
        assert fragments, context
        assert "Quorum" in fragments[0]["snippet"] or "quorum" in fragments[0]["snippet"]
        assert fragments[0]["location"]["markdown_path"] == markdown_relative
        assert fragments[0]["location"]["heading"] == "Distributed Systems Notes"

        # The workspace folder is the learner's code project: no library was created in it.
        assert not (workspace_root / "Trainer Library").exists()


@LAYOUTS
def test_pptx_citations_point_to_slide_anchors(tmp_path: Path, bound: bool) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-pptx"
    pptx_path = workspace_root / "slides" / "consensus.pptx"
    pptx_path.parent.mkdir(parents=True, exist_ok=True)
    pptx_path.write_bytes(_pptx_bytes())
    carrier_root = carrier_root_for(tmp_path, workspace_id, bound=bound)

    with build_client(tmp_path, bound=bound) as client:
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
        markdown = (carrier_root / indexed["canonical_markdown_path"]).read_text(encoding="utf-8")
        front = read_front_matter(markdown)
        assert front["slide_count"] == 3
        assert {"kind": "slide", "index": 1, "line": 3, "label": "Consensus"} in front["anchors"]
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

        # The workspace folder is the learner's code project: no library was created in it.
        assert not (workspace_root / "Trainer Library").exists()


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


@LAYOUTS
def test_reindex_after_source_change_regenerates_markdown_and_keeps_history(
    tmp_path: Path,
    bound: bool,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-reindex"
    docx_path = workspace_root / "notes.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())
    carrier_root = carrier_root_for(tmp_path, workspace_id, bound=bound)

    with build_client(tmp_path, bound=bound) as client:
        start_session(client, workspace_root, workspace_id)
        first = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="docx",
            name="Notes",
            source=docx_path,
        )
        first_path = carrier_root / first["canonical_markdown_path"]
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
            (carrier_root / refreshed["canonical_markdown_path"]).read_text(encoding="utf-8")
        )
        assert second_front["content_hash"] != first_hash
        assert second_front["version_id"] != first_front["version_id"]
        assert "Leases bound staleness." in (
            carrier_root / refreshed["canonical_markdown_path"]
        ).read_text(encoding="utf-8")

        # The workspace folder is the learner's code project: no library was created in it.
        assert not (workspace_root / "Trainer Library").exists()


@LAYOUTS
def test_import_stages_analyze_materialize_index_do_real_work(
    tmp_path: Path,
    bound: bool,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-staged-import"
    docx_path = workspace_root / "docs" / "staged-notes.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())
    carrier_root = carrier_root_for(tmp_path, workspace_id, bound=bound)

    with build_client(tmp_path, bound=bound) as client:
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
        markdown_path = carrier_root / materialize_item["markdown_path"]
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

        # The workspace folder is the learner's code project: no library was created in it.
        assert not (workspace_root / "Trainer Library").exists()


@LAYOUTS
def test_pdf_with_image_syncs_only_markdown_and_images_into_sandbox(
    tmp_path: Path,
    bound: bool,
) -> None:
    """Indexing a PDF containing an embedded image must sync only .md + assets/*.png into the sandbox."""

    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-pdf-md-sandbox"
    pdf_path = workspace_root / "docs" / "architecture-guide.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    carrier_root = carrier_root_for(tmp_path, workspace_id, bound=bound)

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Idempotency architecture overview", fontsize=12)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 12, 12), 0)
    pixmap.set_rect(pixmap.irect, (0, 128, 255))
    page.insert_image(pymupdf.Rect(72, 100, 172, 200), pixmap=pixmap)
    pdf_path.write_bytes(document.tobytes())
    document.close()

    with build_client(tmp_path, bound=bound) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            kind="pdf",
            name="Architecture Guide",
            source=pdf_path,
        )
        runtime = _runtime(client)
        assert runtime.sandbox_service is not None
        sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)

    sandbox_path = Path(str(indexed["sandbox_path"]))
    assert sandbox_path.suffix == ".md"
    assert sandbox_path.is_file()
    sandbox_text = sandbox_path.read_text(encoding="utf-8")
    assert "Idempotency architecture overview" in sandbox_text
    assert f"assets/{indexed['id']}/" in sandbox_text

    assert list(sandbox_root.rglob("*.pdf")) == []
    assert list(sandbox_root.rglob("*.png")), "expected extracted PNG companion image in sandbox"

    library_root = carrier_root / "Trainer Library"
    assert list(library_root.rglob("*.pdf")) == []
    assert list((library_root / ".trainer-resources" / "markdown" / "assets" / indexed["id"]).glob("*.png"))

    # The workspace folder is the learner's code project: no library was created in it.
    assert not (workspace_root / "Trainer Library").exists()
