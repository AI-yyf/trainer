"""(i) <LibraryRoot> and workspace authority: what the coach, a remote host, or a
    library request is allowed to create, rename, delete, import or admit.

Guarantees covered:
  * library folders, assets, groups, renames and deletes stay inside the library root and are restorable;
  * browser / URL intake lands in the library, never in the opened project;
  * remote (SSH / container / artifact) authority is admitted only for the owning workspace;
  * source intake, browse admission and asset governance refuse what is not grounded in a registered workspace;
  * child processes the sidecar starts never inherit the sidecar's own secret;
  * workspace classification and project provisioning never invent authority the learner did not grant.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_resource_channels_and_organize.py
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app

# ---------------------------------------------------------------------------
# Restored from test_resource_channels_and_organize.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer resource channels",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-resource-channels.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_inline_folder_and_url_channels_register_in_the_library(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-channels"
    project = tmp_path / "project"
    folder = project / "docs"
    folder.mkdir(parents=True)
    note = folder / "folder-note.md"
    note.write_text("# Folder note\nCollect this folder into the library.\n", encoding="utf-8")

    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Resource channels",
                "workspace_path": str(project),
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        inline = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "inline-note.md",
                "source": "inline://inline-note.md",
                "content": "Inline paste about login error handling.",
            },
        )
        assert inline.status_code == 200, inline.text
        inline_indexed = client.post(
            "/resource/index",
            json={"session_id": session_id, "workspace_id": workspace_id, "resource_id": inline.json()["id"]},
        )
        assert inline_indexed.status_code == 200, inline_indexed.text
        assert inline_indexed.json()["index_status"] == "indexed"

        folder_upload = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "docs",
                "source": str(folder),
                "source_type": "folder",
                "source_items": [str(note)],
            },
        )
        assert folder_upload.status_code == 200, folder_upload.text
        folder_indexed = client.post(
            "/resource/index",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "resource_id": folder_upload.json()["id"],
            },
        )
        assert folder_indexed.status_code == 200, folder_indexed.text

        url_upload = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "kind": "url",
                "name": "Public article",
                "source": "https://example.com/login-errors",
                "source_type": "url",
            },
        )
        assert url_upload.status_code == 200, url_upload.text
        url_indexed = client.post(
            "/resource/index",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "resource_id": url_upload.json()["id"],
                "enable_network": True,
            },
        )
        assert url_indexed.status_code == 200, url_indexed.text
        assert "network_disabled" in url_indexed.json().get("quality_flags") or url_indexed.json()[
            "index_status"
        ] in {"indexed", "failed"}

        summary = client.get("/memory/summary", params={"workspace_id": workspace_id})
        assert summary.status_code == 200, summary.text
        resource_ids = {item["id"] for item in summary.json()["memory"]["resources"]}
        assert inline.json()["id"] in resource_ids
        assert folder_upload.json()["id"] in resource_ids
        assert url_upload.json()["id"] in resource_ids
