"""Background library organizer: resources that were only *registered*
(``index_status="pending"``) get parsed and indexed by the runtime sweep, so
the coach organizes the library without the learner pressing 索引."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app

WORKSPACE_ID = "ws-bg-organizer"


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer background organizer",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-bg-organizer.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _upload_inline_markdown(client: TestClient) -> dict:
    session_id = client.post(
        "/session/start",
        json={"workspace_id": WORKSPACE_ID, "workspace_name": "Organizer"},
    ).json()["session_id"]
    response = client.post(
        "/resource/upload",
        json={
            "session_id": session_id,
            "workspace_id": WORKSPACE_ID,
            "kind": "markdown",
            "name": "Rotation guard notes",
            "source": "notes/rotation-guard.md",
            "content": "# Rotation guard\n\nThe rotation guard runs before the retry queue drains.",
            "source_type": "file",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_background_sweep_indexes_pending_resources(tmp_path: Path) -> None:
    import asyncio

    app = create_app(_settings(tmp_path / "data"))
    record = _upload_inline_markdown(TestClient(app))
    assert record["index_status"] == "pending"

    organized = asyncio.run(app.state.runtime.organize_pending_resources_once())
    assert organized >= 1

    listed = app.state.runtime.repository.list_resources(WORKSPACE_ID)
    swept = next(item for item in listed if item.id == record["id"])
    assert swept.index_status == "indexed"
    assert swept.summary != "Registered and waiting for parsing."


def test_background_sweep_skips_already_indexed_and_never_raises(tmp_path: Path) -> None:
    import asyncio

    app = create_app(_settings(tmp_path / "data"))
    runtime = app.state.runtime
    organized = asyncio.run(runtime.organize_pending_resources_once())
    assert organized == 0

    record = _upload_inline_markdown(TestClient(app))
    first = asyncio.run(runtime.organize_pending_resources_once())
    assert first >= 1
    # A second pass finds nothing pending: the sweep is bounded and quiet.
    second = asyncio.run(runtime.organize_pending_resources_once())
    assert second == 0
    listed = runtime.repository.list_resources(WORKSPACE_ID)
    swept = next(item for item in listed if item.id == record["id"])
    assert swept.index_status == "indexed"
