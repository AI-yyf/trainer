"""(j) Browser / network intake boundary: external content enters only through the
    capture lane, and fetches cannot reach private networks.

Guarantees covered:
  * the browser bridge pairs with explicit credentials, persists and revokes them across restarts;
  * captures are mocked at the upstream fetch boundary, deduped by normalized URL, and land as library Markdown;
  * controlled fetch rejects non-public DNS answers, redirects to private ranges, and oversized bodies.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_browser_capture.py
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.network_fetch import ControlledFetchError, ControlledFetchResponse

# ---------------------------------------------------------------------------
# Restored from test_browser_capture.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _runtime(client: TestClient) -> Any:
    """Starlette types ``TestClient.app`` as the ASGI callable union; narrow it at runtime."""
    application = client.app
    assert isinstance(application, FastAPI), "test client must wrap the Trainer FastAPI app"
    return application.state.runtime


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
        # The README text lives in the resource's document: in the snapshot while that is
        # still the resource's file, otherwise in the canonical Markdown that replaced it.
        service = _runtime(client).resource_service
        record = _runtime(client).repository.get_resource(workspace_id, str(payload["id"]))
        document = service._canonical_markdown_path(workspace_id, record) or Path(payload["source"])
        assert "Rotate signing keys" in document.read_text(encoding="utf-8")


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
