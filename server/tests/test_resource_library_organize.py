"""Library organization: rename, tags, group moves and local export.

These capabilities operate on the existing resource record structure
(``name``/``tags``/``collection_path``+``collection_root``) and only move
Trainer-owned snapshots; project and sandbox artifacts stay with the Coach
organize flow.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.resources.ingest import ExtractedContent


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer library organize",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-library-organize.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    return TestClient(create_app(settings))


def _capture_page(client: TestClient, monkeypatch, workspace_id: str, url: str) -> dict:
    def fake_extract(value: str, *, network_enabled: bool = False) -> ExtractedContent:
        return ExtractedContent(
            title="Rotation notes",
            text="The rotation guard runs before the retry queue drains.",
            author=None,
            date=None,
            url=value,
        )

    monkeypatch.setattr("app.resources.capture.extract_from_url", fake_extract)
    session_id = client.post(
        "/session/start",
        json={"workspace_id": workspace_id, "workspace_name": "Organize"},
    ).json()["session_id"]
    response = client.post(
        "/resources/capture",
        json={
            "session_id": session_id,
            "workspace_id": workspace_id,
            "url": url,
            "kind": "web",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_rename_updates_the_display_name_only(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-organize-rename"
    with build_client(tmp_path) as client:
        captured = _capture_page(client, monkeypatch, workspace_id, "https://docs.example.com/rename")
        source_before = captured["source"]

        renamed = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": captured["id"],
                "action": "rename",
                "title": "Guard ordering notes",
            },
        )

        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["name"] == "Guard ordering notes"
        assert renamed.json()["source"] == source_before
        assert Path(source_before).is_file()

        empty = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": captured["id"],
                "action": "rename",
                "title": "   ",
            },
        )
        assert empty.status_code == 422


def test_set_tags_dedupes_truncates_and_clears(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-organize-tags"
    with build_client(tmp_path) as client:
        captured = _capture_page(client, monkeypatch, workspace_id, "https://docs.example.com/tags")

        tagged = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": captured["id"],
                "action": "set_tags",
                "tags": ["networking", "auth", "Networking", "  ", "x" * 80],
            },
        )
        assert tagged.status_code == 200, tagged.text
        tags = tagged.json()["tags"]
        assert tags[0:2] == ["networking", "auth"]
        assert len(tags) == 3
        assert len(tags[2]) == 40

        cleared = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": captured["id"],
                "action": "set_tags",
                "tags": [],
            },
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["tags"] == []


def test_group_move_relocates_the_snapshot_and_can_be_cleared(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-organize-group"
    with build_client(tmp_path) as client:
        captured = _capture_page(client, monkeypatch, workspace_id, "https://docs.example.com/group")
        original_source = Path(captured["source"])

        grouped = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": captured["id"],
                "action": "set_group",
                "group": "Web snapshots/Docs",
            },
        )
        assert grouped.status_code == 200, grouped.text
        payload = grouped.json()
        assert payload["collection_path"] == "Docs/" + Path(payload["source"]).name
        assert payload["collection_root"]
        assert Path(payload["source"]).is_file()
        assert not original_source.exists()

        # The moved snapshot is still searchable and still opens/exports.
        found = client.post(
            "/resource/search",
            json={"workspace_id": workspace_id, "query": "rotation guard"},
        )
        assert found.status_code == 200, found.text
        assert captured["id"] in {hit["id"] for hit in found.json()["hits"]}

        exported = client.get(
            "/resource/export",
            params={"workspace_id": workspace_id, "resource_id": captured["id"]},
        )
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-disposition"].startswith("attachment;")
        assert "rotation guard" in exported.text

        ungrouped = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": captured["id"],
                "action": "set_group",
                "group": "",
            },
        )
        assert ungrouped.status_code == 200, ungrouped.text
        assert ungrouped.json()["collection_path"] is None
        assert ungrouped.json()["collection_root"] is None


def test_group_move_refuses_unsafe_and_reserved_names(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-organize-guard"
    with build_client(tmp_path) as client:
        captured = _capture_page(client, monkeypatch, workspace_id, "https://docs.example.com/guard")
        for group in ("../escape", "a//b", "trainer", ".trainer", "x/../../y"):
            response = client.post(
                "/resource/organize",
                json={
                    "workspace_id": workspace_id,
                    "resource_id": captured["id"],
                    "action": "set_group",
                    "group": group,
                },
            )
            assert response.status_code == 422, (group, response.text)


def test_organize_refuses_unknown_resources(tmp_path) -> None:
    with build_client(tmp_path) as client:
        client.post(
            "/session/start",
            json={"workspace_id": "workspace-organize-404", "workspace_name": "Organize"},
        )
        response = client.post(
            "/resource/organize",
            json={
                "workspace_id": "workspace-organize-404",
                "resource_id": "resource-missing",
                "action": "rename",
                "title": "Nope",
            },
        )
    assert response.status_code == 404, response.text


def test_export_reports_missing_snapshots_honestly(tmp_path) -> None:
    workspace_id = "workspace-organize-export-missing"
    with build_client(tmp_path) as client:
        session_id = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Organize"},
        ).json()["session_id"]
        uploaded = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "kind": "url",
                "name": "Remote page",
                "source": "https://docs.example.com/remote-only",
            },
        )
        assert uploaded.status_code == 200, uploaded.text

        exported = client.get(
            "/resource/export",
            params={"workspace_id": workspace_id, "resource_id": uploaded.json()["id"]},
        )
        assert exported.status_code == 409, exported.text
        assert exported.json()["detail"]["code"] == "no_local_snapshot"
