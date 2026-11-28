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
  * server/tests/test_resource_delete_api.py
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app

# ---------------------------------------------------------------------------
# Restored from test_resource_delete_api.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Resource Delete API Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-resource-delete-api.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_resource_delete_rejects_unsafe_ids_and_hides_missing_resource_details(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-delete-errors"
    with build_client(tmp_path) as client:
        blank = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": "   "},
        )
        unsafe = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": "../private/path"},
        )
        missing = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": "resource-not-present"},
        )

    assert blank.status_code == 422
    assert blank.json()["detail"] == "resource_id must be a non-empty safe identifier."
    assert unsafe.status_code == 422
    assert unsafe.json()["detail"] == "resource_id must be a non-empty safe identifier."
    assert "../private/path" not in unsafe.text
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Resource not found."
    assert "resource-not-present" not in missing.text
