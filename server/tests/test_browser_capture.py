"""POST /resources/capture — the Trainer Capture browser extension intake.

The upstream fetches are mocked (per the capture boundary contract), but the
whole sidecar-side chain below them is real: upload → ingest → index →
search/library registration.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.network_fetch import ControlledFetchError, ControlledFetchResponse
from app.resources.capture import PDF_FETCH_TIMEOUT_SECONDS, PDF_MAX_RESPONSE_BYTES
from app.resources.ingest import ExtractedContent

WEB_URL = "https://blog.example.com/login-errors"
WEB_BODY = (
    "Reset the session cookie after a failed login handler run.\n\n"
    "The rotation guard runs before the retry queue drains.\n"
)


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


def build_client(tmp_path: Path, *, enable_network_fetch: bool = True) -> TestClient:
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


def _start_session(client: TestClient, workspace_id: str) -> str:
    started = client.post(
        "/session/start",
        json={"workspace_id": workspace_id, "workspace_name": "Browser capture"},
    )
    assert started.status_code == 200, started.text
    return started.json()["session_id"]


def _readonly_response(body: bytes, url: str, content_type: str) -> ControlledFetchResponse:
    return ControlledFetchResponse(
        body=body,
        final_url=url,
        status=200,
        headers={"content-type": content_type},
        fetched_at="2026-10-14T00:00:00+00:00",
    )


def test_web_capture_extracts_body_and_registers_it_in_the_library(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-web"
    calls: list[tuple[str, bool]] = []

    def fake_extract(url: str, *, network_enabled: bool = False) -> ExtractedContent:
        calls.append((url, network_enabled))
        return ExtractedContent(
            title="Login error handling",
            text=WEB_BODY,
            author="Ada",
            date="2026-10-01",
            url="https://blog.example.com/login-errors?utm=1",
        )

    monkeypatch.setattr("app.resources.capture.extract_from_url", fake_extract)

    with build_client(tmp_path) as client:
        session_id = _start_session(client, workspace_id)
        response = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "url": WEB_URL,
                "kind": "web",
                "title": "Login errors",
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert calls == [(WEB_URL, True)]
        assert payload["name"] == "Login errors"
        assert payload["kind"] == "markdown"
        assert payload["index_status"] == "indexed"
        assert "trainer-capture:web" in payload["tags"]
        assert f"captured-from:{WEB_URL}" in payload["tags"]
        # The captured body — not a placeholder — is what got stored and indexed.
        assert "rotation guard" in Path(payload["source"]).read_text(encoding="utf-8")

        found = client.post(
            "/resource/search",
            json={"session_id": session_id, "workspace_id": workspace_id, "query": "rotation guard"},
        )
        assert found.status_code == 200, found.text
        assert payload["id"] in {hit["id"] for hit in found.json()["hits"]}

        summary = client.get("/memory/summary", params={"workspace_id": workspace_id})
        assert summary.status_code == 200, summary.text
        assert payload["id"] in {item["id"] for item in summary.json()["memory"]["resources"]}


def test_pdf_capture_downloads_bounded_bytes_and_uses_existing_pdf_ingest(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-pdf"
    pdf_url = "https://files.example.com/papers/session-rotation.pdf"
    pdf_body = minimal_pdf(["Trainer capture PDF ingest marker 4471."])
    fetch_calls: list[tuple[str, int | None, float | None]] = []

    def fake_fetch(url: str, **kwargs):
        fetch_calls.append(
            (url, kwargs.get("max_response_bytes"), kwargs.get("timeout_seconds"))
        )
        return _readonly_response(pdf_body, url, "application/pdf")

    monkeypatch.setattr("app.resources.capture.fetch_url", fake_fetch)

    with build_client(tmp_path) as client:
        session_id = _start_session(client, workspace_id)
        response = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "url": pdf_url,
                "kind": "pdf",
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert fetch_calls == [(pdf_url, PDF_MAX_RESPONSE_BYTES, PDF_FETCH_TIMEOUT_SECONDS)]
        assert payload["kind"] == "pdf"
        assert payload["name"].endswith(".pdf")
        assert payload["index_status"] == "indexed"
        assert f"captured-from:{pdf_url}" in payload["tags"]
        # The downloaded bytes were materialized byte-for-byte, then read by the
        # existing PyMuPDF ingest path.
        assert Path(payload["source"]).read_bytes() == pdf_body
        assert "Trainer capture PDF ingest marker 4471" in payload["summary"]


def test_pdf_capture_rejects_non_pdf_payloads(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-not-pdf"
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(b"<html>not a pdf</html>", url, "text/html"),
    )

    with build_client(tmp_path) as client:
        session_id = _start_session(client, workspace_id)
        response = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "url": "https://files.example.com/papers/not-a-pdf",
                "kind": "pdf",
            },
        )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "not_a_pdf"


def test_github_repo_capture_records_repo_url_and_reads_readme(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-github"
    repo_url = "https://github.com/example-org/session-tools"
    readme = "# Session Tools\n\nRotate signing keys before the deploy window.\n"
    readme_api_payload = json.dumps(
        {
            "name": "README.md",
            "path": "README.md",
            "encoding": "base64",
            "content": base64.b64encode(readme.encode("utf-8")).decode("ascii"),
        }
    ).encode("utf-8")
    fetched: list[tuple[str, str | None]] = []

    def fake_fetch(url: str, **kwargs):
        headers = kwargs.get("headers") or {}
        fetched.append((url, headers.get("Accept")))
        return _readonly_response(readme_api_payload, url, "application/json")

    monkeypatch.setattr("app.resources.capture.fetch_url", fake_fetch)

    with build_client(tmp_path) as client:
        session_id = _start_session(client, workspace_id)
        response = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "url": f"{repo_url}/tree/main",
                "kind": "github_repo",
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert fetched == [
            ("https://api.github.com/repos/example-org/session-tools/readme", "application/vnd.github+json")
        ]
        assert payload["name"] == "example-org/session-tools"
        assert payload["kind"] == "markdown"
        assert payload["index_status"] == "indexed"
        assert "trainer-capture:github_repo" in payload["tags"]
        assert f"captured-from:{repo_url}" in payload["tags"]
        assert "Rotate signing keys" in Path(payload["source"]).read_text(encoding="utf-8")


def test_github_capture_requires_a_repository_url_but_allows_any_github_url(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-github-invalid"
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(b"# README\n", url, "text/plain"),
    )

    with build_client(tmp_path) as client:
        session_id = _start_session(client, workspace_id)
        profile = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "url": "https://github.com/example-org",
                "kind": "github_repo",
            },
        )

    assert profile.status_code == 422, profile.text
    assert profile.json()["detail"]["code"] == "not_a_github_repo"


def test_capture_reports_a_missing_readme_instead_of_inventing_content(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-github-missing"

    def fake_fetch(url: str, **kwargs):
        raise ControlledFetchError("http_status", "URL request returned HTTP 404.")

    monkeypatch.setattr("app.resources.capture.fetch_url", fake_fetch)

    with build_client(tmp_path) as client:
        session_id = _start_session(client, workspace_id)
        response = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "url": "https://github.com/example-org/no-readme",
                "kind": "github_repo",
            },
        )

        assert response.status_code == 404, response.text
        assert response.json()["detail"]["code"] == "readme_not_found"

        summary = client.get("/memory/summary", params={"workspace_id": workspace_id})
        assert summary.status_code == 200, summary.text
        assert summary.json()["memory"]["resources"] == []


def test_github_rate_limits_are_not_reported_as_missing_readmes(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-github-rate-limited"

    def fake_fetch(url: str, **kwargs):
        raise ControlledFetchError("http_status", "URL request returned HTTP 403.")

    monkeypatch.setattr("app.resources.capture.fetch_url", fake_fetch)

    with build_client(tmp_path) as client:
        session_id = _start_session(client, workspace_id)
        response = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "url": "https://github.com/example-org/session-tools",
                "kind": "github_repo",
            },
        )

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "fetch_failed"


def test_capture_is_refused_while_network_fetch_is_disabled(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-network-off"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("capture must not reach the network when it is disabled")

    monkeypatch.setattr("app.resources.capture.extract_from_url", fail_if_called)

    with build_client(tmp_path, enable_network_fetch=False) as client:
        session_id = _start_session(client, workspace_id)
        response = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "url": WEB_URL,
                "kind": "web",
            },
        )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "network_disabled"


def test_capture_rejects_non_public_and_malformed_urls(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-invalid-url"
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(b"# README\n", url, "text/plain"),
    )

    with build_client(tmp_path) as client:
        session_id = _start_session(client, workspace_id)
        for url in ("ftp://example.com/file", "http://127.0.0.1:9000/local", "https://"):
            response = client.post(
                "/resources/capture",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "url": url,
                    "kind": "web",
                },
            )
            assert response.status_code == 422, (url, response.text)
            assert response.json()["detail"]["code"] == "invalid_url"

        unsupported = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "url": WEB_URL,
                "kind": "video",
            },
        )
        assert unsupported.status_code == 422, unsupported.text


def test_capture_reports_upstream_fetch_failures_as_bad_gateway(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-fetch-failed"

    def fake_fetch(url: str, **kwargs):
        raise ControlledFetchError("timeout", "URL request timed out.")

    monkeypatch.setattr("app.resources.capture.fetch_url", fake_fetch)

    with build_client(tmp_path) as client:
        session_id = _start_session(client, workspace_id)
        response = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "url": "https://files.example.com/papers/slow.pdf",
                "kind": "pdf",
            },
        )

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "fetch_failed"


def test_capture_keeps_web_extraction_failures_out_of_the_library(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-empty"

    def fake_extract(url: str, *, network_enabled: bool = False) -> ExtractedContent:
        raise ValueError(f"Extracted content is empty for URL: {url}")

    monkeypatch.setattr("app.resources.capture.extract_from_url", fake_extract)

    with build_client(tmp_path) as client:
        session_id = _start_session(client, workspace_id)
        response = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "url": WEB_URL,
                "kind": "web",
            },
        )

        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "empty_content"

        summary = client.get("/memory/summary", params={"workspace_id": workspace_id})
        assert summary.status_code == 200, summary.text
        assert summary.json()["memory"]["resources"] == []
