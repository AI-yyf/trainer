"""Managed artifacts stay under the sidecar data root; a captured PDF uses the PDF ingest.

Restored from server/tests/test_resource_sidecar_routes.py and
server/tests/test_browser_capture.py at df0a3e2a^ (both deleted in df0a3e2a). Every old
assertion is kept.

* ``test_workspace_path_keeps_managed_artifacts_under_sidecar_data_root`` is verbatim: it
  never located the canonical copy and passes on the current tree unchanged.
* ``test_pdf_capture_downloads_bounded_bytes_and_uses_existing_pdf_ingest``: only the line
  that read the canonical Markdown at ``workspace_root / <relative>`` was adapted. This is a
  cold start (no learning folder bound), and the workspace folder is the learner's code
  project, so the copy now lives under the sidecar data root at
  ``<data_dir>/canonical-resources/<workspace slug>/Trainer Library/...``. The test also
  asserts the workspace folder gained no ``Trainer Library`` directory.
* The two old ``build_client`` helpers differ only in their settings; they are recreated
  verbatim as ``build_sidecar_client`` and ``build_capture_client``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.network_fetch import ControlledFetchResponse
from app.resources.canonical import read_front_matter
from app.resources.canonical_store import managed_workspace_root
from app.resources.capture import PDF_FETCH_TIMEOUT_SECONDS, PDF_MAX_RESPONSE_BYTES

# ---------------------------------------------------------------------------
# Restored from test_resource_sidecar_routes.py (df0a3e2a^)
# ---------------------------------------------------------------------------


def build_sidecar_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Resource Route Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-resource-routes.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_workspace_path_keeps_managed_artifacts_under_sidecar_data_root(tmp_path: Path) -> None:
    workspace_id = "workspace-carrier-root"
    data_root = tmp_path / "sidecar-data"
    workspace_root = tmp_path / "project-root"
    workspace_root.mkdir(parents=True, exist_ok=True)

    with build_sidecar_client(data_root) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Carrier Root Proof",
                "workspace_path": str(workspace_root),
            },
        )
        assert started.status_code == 200

        uploaded = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "text",
                "name": "coach-table.csv",
                "source": "inline://coach-table.csv",
                "content": "name,value\ncoach,1\n",
                "content_encoding": "utf-8",
                "tags": ["carrier-root", "csv"],
            },
        )
        assert uploaded.status_code == 200
        uploaded_payload = uploaded.json()
        uploaded_source = Path(uploaded_payload["source"]).resolve(strict=False)
        expected_inline_root = (data_root / "inline-resources" / workspace_id).resolve(strict=False)
        uploaded_source.relative_to(expected_inline_root)
        assert not (workspace_root / ".trainer" / "search" / "index.sqlite3").exists()

        indexed = client.post(
            "/resource/index",
            json={
                "workspace_id": workspace_id,
                "resource_id": uploaded_payload["id"],
                "enable_network": False,
            },
        )
        assert indexed.status_code == 200
        indexed_payload = indexed.json()
        sandbox_path = Path(indexed_payload["sandbox_path"]).resolve(strict=False)
        expected_sandbox_root = (data_root / "sandboxes" / workspace_id).resolve(strict=False)
        sandbox_path.relative_to(expected_sandbox_root)
        assert sandbox_path.suffix == ".md"
        assert (data_root / "search-indexes" / workspace_id / "index.sqlite3").exists()
        assert not (workspace_root / ".trainer" / "search" / "index.sqlite3").exists()

        csv_preview_path = sandbox_path.with_name("coach-table.csv")
        csv_preview_path.write_text("name,value\ncoach,1\n", encoding="utf-8")

        state = client.get(
            "/sandbox/state",
            params={
                "workspace_id": workspace_id,
                "selected_path": str(csv_preview_path),
                "preview_path": str(csv_preview_path),
            },
        )

    assert state.status_code == 200
    payload = state.json()
    preview_artifact_path = Path(
        payload["preview"]["metadata"]["preview_artifact_path"]
    ).resolve(strict=False)
    expected_preview_root = (data_root / "previews" / workspace_id).resolve(strict=False)
    preview_artifact_path.relative_to(expected_preview_root)
    assert payload["root_path"] == str(expected_sandbox_root)
    assert payload["sandbox_root_path"] == str(expected_sandbox_root)
    assert payload["managed_roots"] == ["plan", "cards", "knowledge", "sources", "notes", "outputs"]
    assert payload["workspace_root_path"] == str(workspace_root.resolve(strict=False))
    assert payload["active_workspace_root"] == str(workspace_root.resolve(strict=False))
    assert payload["authority"]["root_uri"] == str(expected_sandbox_root)
    assert payload["authority"]["active_workspace_root"] == str(workspace_root.resolve(strict=False))


# ---------------------------------------------------------------------------
# Restored from test_browser_capture.py (df0a3e2a^)
# ---------------------------------------------------------------------------


def minimal_pdf(lines: list[str]) -> bytes:
    """A structurally valid single-page PDF carrying extractable text."""

    content = "BT /F1 12 Tf 40 700 Td 16 TL\n" + "\n".join(f"({line}) Tj T*" for line in lines) + "\nET"
    stream = content.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_position = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF\n"
    ).encode()
    return bytes(out)


def build_capture_client(tmp_path: Path, *, enable_network_fetch: bool = True) -> TestClient:
    settings = AppSettings(
        app_name="Trainer browser capture",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-browser-capture.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=enable_network_fetch,
    )
    return TestClient(create_app(settings))


def _readonly_response(body: bytes, url: str, content_type: str) -> ControlledFetchResponse:
    return ControlledFetchResponse(
        body=body,
        final_url=url,
        status=200,
        headers={"content-type": content_type},
        fetched_at="2026-10-14T00:00:00+00:00",
    )


def test_pdf_capture_downloads_bounded_bytes_and_uses_existing_pdf_ingest(
    tmp_path,
    monkeypatch,
) -> None:
    workspace_id = "workspace-capture-pdf"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    pdf_url = "https://arxiv.org/pdf/2407.17032v3#page=1"
    pdf_body = minimal_pdf(["Trainer capture PDF ingest marker 4471."])
    fetch_calls: list[tuple[str, int | None, float | None]] = []

    def fake_fetch(url: str, **kwargs):
        fetch_calls.append(
            (url, kwargs.get("max_response_bytes"), kwargs.get("timeout_seconds"))
        )
        return _readonly_response(pdf_body, url, "application/pdf")

    monkeypatch.setattr("app.resources.capture.fetch_url", fake_fetch)

    with build_capture_client(tmp_path) as client:
        session = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Browser capture",
                "workspace_path": str(workspace_root),
            },
        )
        assert session.status_code == 200, session.text
        response = client.post(
            "/resources/capture",
            json={
                "session_id": session.json()["session_id"],
                "workspace_id": workspace_id,
                "url": pdf_url,
                "kind": "pdf",
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert fetch_calls == [(pdf_url, PDF_MAX_RESPONSE_BYTES, PDF_FETCH_TIMEOUT_SECONDS)]
        # md-only: the captured PDF is converted to canonical Markdown and the
        # inline binary upload is removed after indexing.
        assert payload["kind"] == "markdown"
        assert payload["index_status"] == "indexed"
        assert f"captured-from:{pdf_url}" in payload["tags"]
        assert not Path(payload["source"]).exists()
        assert payload["canonical_original_path"] == ""
        assert "Trainer capture PDF ingest marker 4471" in payload["summary"]
        # The capture client's data root is ``tmp_path``: a cold start keeps the
        # canonical copy under it, never in the workspace folder.
        markdown = (
            managed_workspace_root(tmp_path, workspace_id) / payload["canonical_markdown_path"]
        ).read_text("utf-8")
        assert read_front_matter(markdown)["source_url"] == pdf_url

        # The workspace folder is the learner's code project: no library was created in it.
        assert not (workspace_root / "Trainer Library").exists()
