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


# --------------------------------------------------------------------------
# The capture lane is a full ingestion pipeline: normalized-URL dedup, content
# hashing, idempotency, selection metadata, focus binding and the deep link.
# --------------------------------------------------------------------------


def _pair_browser(client: TestClient, workspace_id: str, code: str = "246813") -> str:
    session_id = _start_session(client, workspace_id)
    registered = client.post(
        "/browser/pair-code",
        json={"code": code, "expires_in": 600, "session_id": session_id, "workspace_id": workspace_id},
    )
    assert registered.status_code == 200, registered.text
    paired = client.post("/browser/pair", json={"code": code})
    assert paired.status_code == 200, paired.text
    return str(paired.json()["credential"])


def _capture_body(url: str) -> str:
    return f"Retry queues drain after the guard run for {url}.\n"



def _patch_github(monkeypatch, readme_text="# Learning Repo\n") -> None:
    monkeypatch.setattr(
        "app.resources.capture._fetch_github_readme",
        lambda owner, name: (readme_text, "README.md"),
    )
    monkeypatch.setattr(
        "app.resources.capture._fetch_github_docs_listing",
        lambda owner, name: "docs/setup.md\n",
    )

def _patch_web_extract(monkeypatch, body_for) -> list[str]:
    calls: list[str] = []

    def fake_extract(url: str, *, network_enabled: bool = False) -> ExtractedContent:
        calls.append(url)
        return ExtractedContent(
            title="Rotation notes",
            text=body_for(url),
            author=None,
            date=None,
            url=url,
        )

    monkeypatch.setattr("app.resources.capture.extract_from_url", fake_extract)
    return calls


def test_capture_persists_a_self_describing_markdown_snapshot(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-snapshot"
    _patch_web_extract(monkeypatch, _capture_body)

    with build_client(tmp_path) as client:
        token = _pair_browser(client, workspace_id)
        captured = client.post(
            "/resources/capture",
            json={
                "url": "https://docs.example.com/rotation/",
                "kind": "web",
                "selection": "the guard run",
                "client_capture_id": "snap-1",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert captured.status_code == 200, captured.text
        payload = captured.json()
        snapshot = Path(payload["source"]).read_text(encoding="utf-8")

        # Metadata: title, source, capture time, kind and the selection flag.
        assert snapshot.startswith("---\n")
        assert "title: Rotation notes" in snapshot
        assert "source: https://docs.example.com/rotation/" in snapshot
        assert "capture_kind: web" in snapshot
        assert "selection: true" in snapshot
        assert "captured_at:" in snapshot
        # The captured selection is preserved inside the snapshot.
        assert "## Captured selection" in snapshot
        assert "> the guard run" in snapshot
        # Metadata tags: kind, domain, capture time and the selection flag.
        assert "capture-selection" in payload["tags"]
        assert "capture-domain:docs.example.com" in payload["tags"]
        assert any(tag.startswith("captured-at:") for tag in payload["tags"])
        assert any(tag.startswith("capture-key:") for tag in payload["tags"])
        # Capture envelope fields for the extension.
        assert payload["resource_id"] == payload["id"]
        assert payload["deduped"] is False
        assert payload["deep_link"] == (
            f"vscode://local.trainer-extension/library/{payload['id']}"
        )


def test_repeated_capture_dedupes_by_normalized_url_and_client_id(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-dedup"
    calls = _patch_web_extract(monkeypatch, _capture_body)

    with build_client(tmp_path) as client:
        token = _pair_browser(client, workspace_id, code="135792")
        headers = {"Authorization": f"Bearer {token}"}
        first = client.post(
            "/resources/capture",
            json={
                "url": "https://docs.example.com/rotation/#section",
                "kind": "web",
                "client_capture_id": "dedup-1",
            },
            headers=headers,
        )
        assert first.status_code == 200, first.text
        resource_id = first.json()["id"]

        # Same client_capture_id: replayed verbatim (no second fetch, no new entry).
        replayed = client.post(
            "/resources/capture",
            json={
                "url": "https://docs.example.com/rotation/#section",
                "kind": "web",
                "client_capture_id": "dedup-1",
            },
            headers=headers,
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["id"] == resource_id
        assert replayed.json()["deduped"] is True

        # Same URL with tracking parameters / fragment / trailing slash: deduped.
        duplicate = client.post(
            "/resources/capture",
            json={
                "url": "https://docs.example.com/rotation/?utm_source=newsletter&utm_medium=email",
                "kind": "web",
                "client_capture_id": "dedup-2",
            },
            headers=headers,
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["id"] == resource_id
        assert duplicate.json()["deduped"] is True

        # A different id for the same URL that was already captured by id…
        assert len(calls) == 1

        summary = client.get("/memory/summary", params={"workspace_id": workspace_id})
        assert summary.status_code == 200, summary.text
        assert [item["id"] for item in summary.json()["memory"]["resources"]] == [resource_id]


def test_capture_dedupes_identical_content_from_a_different_url(tmp_path, monkeypatch) -> None:
    """Content identity follows the Library's content-hash mechanism.

    Two mirror URLs serving byte-identical PDFs are the same material: the
    second capture answers with the existing resource id instead of a copy.
    """

    workspace_id = "workspace-capture-content-dedup"
    pdf_body = minimal_pdf(["Mirrored handover checklist marker 8891."])

    def fake_fetch(url: str, **kwargs):
        return _readonly_response(pdf_body, url, "application/pdf")

    monkeypatch.setattr("app.resources.capture.fetch_url", fake_fetch)

    with build_client(tmp_path) as client:
        token = _pair_browser(client, workspace_id, code="864209")
        headers = {"Authorization": f"Bearer {token}"}
        first = client.post(
            "/resources/capture",
            json={
                "url": "https://mirror-a.example.com/handover.pdf",
                "kind": "pdf",
                "client_capture_id": "c-a",
            },
            headers=headers,
        )
        assert first.status_code == 200, first.text

        second = client.post(
            "/resources/capture",
            json={
                "url": "https://mirror-b.example.com/handover.pdf",
                "kind": "pdf",
                "client_capture_id": "c-b",
            },
            headers=headers,
        )
        assert second.status_code == 200, second.text
        assert second.json()["deduped"] is True
        assert second.json()["id"] == first.json()["id"]


def test_capture_binds_a_known_learning_focus_and_ignores_an_unknown_one(
    tmp_path, monkeypatch
) -> None:
    from app.core.models import LearningPlan, PlanStage

    workspace_id = "workspace-capture-focus"
    _patch_web_extract(monkeypatch, lambda url: f"Focus body for {url}.\n")

    with build_client(tmp_path) as client:
        token = _pair_browser(client, workspace_id, code="975310")
        headers = {"Authorization": f"Bearer {token}"}
        runtime = client.app.state.runtime  # type: ignore[attr-defined]
        runtime.repository.save_plan(
            workspace_id,
            LearningPlan(
                id="plan-focus",
                title="Focus plan",
                stages=[
                    PlanStage(
                        id="stage-guards",
                        title="Guard ordering",
                        goal="Order guards before retries",
                        outcomes=["one ordered guard"],
                        status="active",
                    )
                ],
                current_stage_id="stage-guards",
            ),
        )

        bound = client.post(
            "/resources/capture",
            json={
                "url": "https://docs.example.com/guards",
                "kind": "web",
                "bind_focus_id": "stage-guards",
                "client_capture_id": "focus-1",
            },
            headers=headers,
        )
        assert bound.status_code == 200, bound.text
        assert "focus_binding:bound" in bound.json()["warnings"]

        plan = runtime.repository.get_latest_plan(workspace_id)
        assert plan is not None
        assert plan.stages[0].resources == [bound.json()["id"]]

        unknown = client.post(
            "/resources/capture",
            json={
                "url": "https://docs.example.com/other-guards",
                "kind": "web",
                "bind_focus_id": "stage-does-not-exist",
                "client_capture_id": "focus-2",
            },
            headers=headers,
        )
        assert unknown.status_code == 200, unknown.text
        assert "focus_binding:focus_not_found" in unknown.json()["warnings"]
        # The capture itself still landed.
        assert unknown.json()["index_status"] == "indexed"


def test_capture_rejects_a_credential_paired_to_another_workspace(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-mismatch"
    _patch_web_extract(monkeypatch, _capture_body)

    with build_client(tmp_path) as client:
        token = _pair_browser(client, workspace_id, code="102030")
        response = client.post(
            "/resources/capture",
            json={
                "url": "https://docs.example.com/mismatch",
                "kind": "web",
                "workspace_id": "some-other-workspace",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "workspace_mismatch"


def test_capture_requires_a_valid_credential_when_one_is_presented(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-bad-credential"
    _patch_web_extract(monkeypatch, _capture_body)

    with build_client(tmp_path) as client:
        _start_session(client, workspace_id)
        response = client.post(
            "/resources/capture",
            json={"url": "https://docs.example.com/x", "kind": "web"},
            headers={"Authorization": "Bearer revoked-or-made-up"},
        )

    assert response.status_code == 401, response.text
    assert response.json()["detail"]["code"] == "invalid_credential"


def test_github_capture_can_include_the_docs_listing(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-capture-github-docs"
    repo_url = "https://github.com/example-org/session-tools"
    readme = "# Session Tools\n\nRotate signing keys before the deploy window.\n"
    fetched: list[str] = []

    def fake_fetch(url: str, **kwargs):
        fetched.append(url)
        if url.endswith("/readme"):
            payload = json.dumps(
                {
                    "name": "README.md",
                    "path": "README.md",
                    "encoding": "base64",
                    "content": base64.b64encode(readme.encode("utf-8")).decode("ascii"),
                }
            ).encode("utf-8")
            return _readonly_response(payload, url, "application/json")
        listing = json.dumps(
            [{"path": "docs/keys.md"}, {"path": "docs/rotation.md"}]
        ).encode("utf-8")
        return _readonly_response(listing, url, "application/json")

    monkeypatch.setattr("app.resources.capture.fetch_url", fake_fetch)

    with build_client(tmp_path) as client:
        token = _pair_browser(client, workspace_id, code="556677")
        response = client.post(
            "/resources/capture",
            json={"url": repo_url, "kind": "github_repo", "include_docs": True},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200, response.text
        snapshot = Path(response.json()["source"]).read_text(encoding="utf-8")

    assert fetched == [
        "https://api.github.com/repos/example-org/session-tools/readme",
        "https://api.github.com/repos/example-org/session-tools/contents/docs",
    ]
    assert "## Repository docs/ layout" in snapshot
    assert "- `docs/keys.md`" in snapshot


def test_deduped_capture_still_binds_a_new_learning_focus(tmp_path, monkeypatch) -> None:
    """T-0012: dedup reuses content but executes the request's new intent."""
    from app.core.models import LearningPlan, PlanStage

    workspace_id = "workspace-dedup-focus"
    _patch_web_extract(monkeypatch, lambda url: f"Dedup body for {url}.\n")

    with build_client(tmp_path) as client:
        token = _pair_browser(client, workspace_id, code="246810")
        headers = {"Authorization": f"Bearer {token}"}
        runtime = client.app.state.runtime  # type: ignore[attr-defined]
        runtime.repository.save_plan(
            workspace_id,
            LearningPlan(
                id="plan-dedup",
                title="Dedup plan",
                stages=[
                    PlanStage(
                        id="stage-second",
                        title="Second pass",
                        goal="Revisit with focus",
                        outcomes=["one revisit"],
                        status="active",
                    )
                ],
                current_stage_id="stage-second",
            ),
        )

        first = client.post(
            "/resources/capture",
            json={"url": "https://docs.example.com/revisit", "kind": "web", "client_capture_id": "d-1"},
            headers=headers,
        )
        assert first.status_code == 200, first.text
        assert first.json()["deduped"] is False

        second = client.post(
            "/resources/capture",
            json={
                "url": "https://docs.example.com/revisit",
                "kind": "web",
                "bind_focus_id": "stage-second",
                "client_capture_id": "d-2",
            },
            headers=headers,
        )
        assert second.status_code == 200, second.text
        assert second.json()["deduped"] is True
        assert second.json()["id"] == first.json()["id"]
        assert "focus_binding:bound" in second.json()["warnings"]

        plan = runtime.repository.get_latest_plan(workspace_id)
        assert plan is not None
        assert plan.stages[0].resources == [first.json()["id"]]


def test_deduped_repo_capture_with_include_docs_supplements_once(tmp_path, monkeypatch) -> None:
    """T-0012 (docs half): include_docs on a dedup hit appends the docs/ layout
    exactly once, reindexes, and reports the real result."""
    workspace_id = "workspace-dedup-docs"
    _patch_web_extract(monkeypatch, lambda url: f"Repo body for {url}.\n")
    _patch_github(monkeypatch)
    monkeypatch.setattr(
        "app.resources.capture._fetch_github_docs_listing",
        lambda owner, name: "docs/setup.md\n",
    )

    with build_client(tmp_path) as client:
        token = _pair_browser(client, workspace_id, code="135790")
        headers = {"Authorization": f"Bearer {token}"}
        repo_url = "https://github.com/example/learning-repo"

        first = client.post(
            "/resources/capture",
            json={"url": repo_url, "kind": "github_repo", "client_capture_id": "docs-0"},
            headers=headers,
        )
        assert first.status_code == 200, first.text
        resource_id = first.json()["id"]
        assert first.json()["deduped"] is False

        def read_snapshot() -> str:
            record = next(
                item
                for item in client.app.state.runtime.repository.list_resources(workspace_id)
                if item.id == resource_id
            )
            return open(record.source, encoding="utf-8").read()

        assert "Repository docs/ layout" not in read_snapshot()

        second = client.post(
            "/resources/capture",
            json={
                "url": repo_url,
                "kind": "github_repo",
                "include_docs": True,
                "client_capture_id": "docs-1",
            },
            headers=headers,
        )
        assert second.status_code == 200, second.text
        assert second.json()["deduped"] is True
        assert second.json()["id"] == resource_id
        assert "docs-supplemented" in second.json()["tags"]
        assert "Repository docs/ layout" in read_snapshot()
        assert "docs/setup.md" in read_snapshot()

        # Idempotent: a third request does not append twice.
        third = client.post(
            "/resources/capture",
            json={
                "url": repo_url,
                "kind": "github_repo",
                "include_docs": True,
                "client_capture_id": "docs-2",
            },
            headers=headers,
        )
        assert third.status_code == 200, third.text
        assert read_snapshot().count("Repository docs/ layout") == 1


def test_deduped_repo_capture_reports_docs_listing_failure(tmp_path, monkeypatch) -> None:
    """A failed docs listing returns an honest warning and stays retryable."""
    workspace_id = "workspace-dedup-docs-fail"
    _patch_web_extract(monkeypatch, lambda url: f"Repo body for {url}.\n")
    _patch_github(monkeypatch, readme_text="# Broken Docs Repo\n")
    monkeypatch.setattr(
        "app.resources.capture._fetch_github_docs_listing",
        lambda owner, name: "",
    )

    with build_client(tmp_path) as client:
        token = _pair_browser(client, workspace_id, code="246800")
        headers = {"Authorization": f"Bearer {token}"}
        repo_url = "https://github.com/example/broken-docs"

        first = client.post(
            "/resources/capture",
            json={"url": repo_url, "kind": "github_repo", "client_capture_id": "df-0"},
            headers=headers,
        )
        assert first.status_code == 200, first.text

        second = client.post(
            "/resources/capture",
            json={
                "url": repo_url,
                "kind": "github_repo",
                "include_docs": True,
                "client_capture_id": "df-1",
            },
            headers=headers,
        )
        assert second.status_code == 200, second.text
        assert second.json()["deduped"] is True
        assert any("docs/ listing" in str(w) for w in second.json()["warnings"])
        assert "docs-supplemented" not in second.json()["tags"]


def test_link_capture_is_honest_and_deduped_within_its_intent(tmp_path) -> None:
    workspace_id = "workspace-capture-link-intent"
    with build_client(tmp_path, enable_network_fetch=False) as client:
        session_id = _start_session(client, workspace_id)
        body = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "url": "https://docs.example.com/links/rotation",
            "kind": "web",
            "title": "Rotation link",
            "capture_mode": "link",
            "client_capture_id": "link-1",
        }
        first = client.post("/resources/capture", json=body)
        assert first.status_code == 200, first.text
        payload = first.json()
        assert payload["deduped"] is False
        assert "capture-intent:link" in payload["tags"]
        snapshot = Path(payload["source"]).read_text(encoding="utf-8")
        assert "Source link only" in snapshot
        assert "Full source content has not been captured" in snapshot

        replay = client.post(
            "/resources/capture",
            json={**body, "client_capture_id": "link-2"},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["deduped"] is True
        assert replay.json()["id"] == payload["id"]


def test_selection_capture_keeps_its_excerpt_and_does_not_collide_with_other_intents(
    tmp_path,
) -> None:
    workspace_id = "workspace-capture-selection-intent"
    with build_client(tmp_path, enable_network_fetch=False) as client:
        session_id = _start_session(client, workspace_id)
        body = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "url": "https://docs.example.com/links/rotation",
            "kind": "web",
            "title": "Rotation excerpt",
            "capture_mode": "selection",
            "selection": "The rotation guard runs before the retry queue drains.",
            "client_capture_id": "selection-1",
        }
        first = client.post("/resources/capture", json=body)
        assert first.status_code == 200, first.text
        payload = first.json()
        assert payload["deduped"] is False
        assert any(tag.startswith("capture-intent:selection:") for tag in payload["tags"])
        snapshot = Path(payload["source"]).read_text(encoding="utf-8")
        assert "The rotation guard runs before the retry queue drains." in snapshot

        different = client.post(
            "/resources/capture",
            json={
                **body,
                "selection": "A different passage from the same source.",
                "client_capture_id": "selection-2",
            },
        )
        assert different.status_code == 200, different.text
        assert different.json()["deduped"] is False
        assert different.json()["id"] != payload["id"]

        missing = client.post(
            "/resources/capture",
            json={
                **body,
                "selection": "",
                "client_capture_id": "selection-3",
            },
        )
        assert missing.status_code == 422
        assert "Selection capture requires a non-empty excerpt" in missing.text


def test_non_snapshot_capture_cannot_request_an_artifact_download(tmp_path) -> None:
    workspace_id = "workspace-capture-link-download"
    with build_client(tmp_path, enable_network_fetch=False) as client:
        session_id = _start_session(client, workspace_id)
        response = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "url": "https://docs.example.com/links/rotation",
                "kind": "web",
                "capture_mode": "link",
                "download": True,
                "target_dir": "Trainer Library/",
            },
        )
        assert response.status_code == 422
        assert "Only a full source capture can download an artifact" in response.text
