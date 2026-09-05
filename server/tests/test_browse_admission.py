from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.admission import BROWSE_ONLY_BLOCK_CODE
from app.core.settings import AppSettings
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer browse-admission test server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


@pytest.mark.parametrize(
    ("mode", "headers", "payload"),
    [
        ("browse", {}, {"admissionMode": "browse"}),
        ("ignored", {"X-Trainer-Admission-Mode": "ignored"}, {}),
    ],
)
@pytest.mark.parametrize(
    "path",
    [
        "/session/start",
        "/session/message",
        "/plan/generate",
        "/training/generate-card",
        "/evidence/enqueue",
        "/memory/settings",
        "/learning/signal",
        "/resource/upload",
        "/research/create",
    ],
)
def test_browse_admission_rejects_persistent_routes_before_validation(
    tmp_path: Path,
    path: str,
    mode: str,
    headers: dict[str, str],
    payload: dict[str, str],
) -> None:
    with build_client(tmp_path) as client:
        response = client.post(path, json=payload, headers=headers)

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Browse-only admission does not allow persistent Trainer operations.",
        "code": BROWSE_ONLY_BLOCK_CODE,
        "admission_mode": mode,
    }


def test_browse_session_start_creates_no_long_lived_session_or_memory(tmp_path: Path) -> None:
    workspace_id = "workspace-browse-only"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Browse-only project",
                "admission_mode": "browse",
            },
            headers={"Origin": "http://127.0.0.1:5173"},
        )

        assert response.status_code == 409
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
        assert runtime.sessions == {}
        assert runtime.repository.load_latest_session_for_workspace(workspace_id) is None
        assert runtime.repository.get_profile(workspace_id) is None
        assert runtime.repository.get_latest_plan(workspace_id) is None


def test_browse_header_blocks_get_route_with_memory_side_effect(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.get(
            "/training/active-card",
            params={"workspace_id": "workspace-browse-only"},
            headers={"X-Trainer-Admission-Mode": "browse"},
        )

    assert response.status_code == 409
    assert response.json()["code"] == BROWSE_ONLY_BLOCK_CODE


def test_ignored_header_blocks_get_route_with_memory_side_effect(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.get(
            "/training/active-card",
            params={"workspace_id": "workspace-ignored"},
            headers={"X-Trainer-Admission-Mode": "ignored"},
        )

    assert response.status_code == 409
    assert response.json()["code"] == BROWSE_ONLY_BLOCK_CODE
    assert response.json()["admission_mode"] == "ignored"


def test_browse_allows_read_only_resource_search_without_creating_a_session(tmp_path: Path) -> None:
    workspace_id = "workspace-browse-search"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        response = client.post(
            "/resource/search",
            json={
                "workspace_id": workspace_id,
                "query": "FastAPI",
                "admissionMode": "browse",
            },
        )

        assert response.status_code == 200
        assert runtime.sessions == {}
        assert runtime.repository.list_resources(workspace_id) == []


def test_ignored_header_allows_read_only_resource_search_without_creating_a_session(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-ignored-search"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        response = client.post(
            "/resource/search",
            json={"workspace_id": workspace_id, "query": "FastAPI"},
            headers={"X-Trainer-Admission-Mode": "ignored"},
        )

        assert response.status_code == 200
        assert runtime.sessions == {}
        assert runtime.repository.list_resources(workspace_id) == []


def test_managed_admission_keeps_existing_session_start_behavior(tmp_path: Path) -> None:
    workspace_id = "workspace-managed"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Managed project",
                "admissionMode": "managed",
            },
        )

        assert response.status_code == 200
        session_id = response.json()["session_id"]
        assert session_id in runtime.sessions
        assert runtime.repository.load_session(session_id) is not None
