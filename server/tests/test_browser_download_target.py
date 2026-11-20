"""Where a browser download lands: the library root, always."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from tests.test_browser_capture import _pair_browser
from tests.test_library_folders import provision_workspace


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Browser Download Target",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-browser-download-target.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_browser_download_target_always_lands_in_the_library_root(tmp_path: Path) -> None:
    """One place for every capture: the library root.

    Even when a knowledge base folder carries the project's name, the browser
    download target stays at the library root, so captures do not scatter over
    per-project folders.
    """

    with build_client(tmp_path) as client:
        workspace_id, _project, _root = provision_workspace(
            client, tmp_path, workspace_id="workspace-download-target"
        )
        credential = _pair_browser(client, workspace_id)
        headers = {"Authorization": f"Bearer {credential}"}

        # A knowledge base folder named after the project exists.
        created = client.post(
            "/library/groups",
            json={"workspace_id": workspace_id, "path": workspace_id},
        )
        assert created.status_code == 200, created.text

        status = client.get("/browser/status", headers=headers)
        assert status.status_code == 200, status.text
        payload = status.json()
        target = str(payload.get("download_target") or "")
        assert target == "Trainer Library", payload
        # The popup shows this target verbatim; it never names a subfolder.
        assert "/" not in target, payload
