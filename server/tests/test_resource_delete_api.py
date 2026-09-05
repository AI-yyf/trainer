from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app


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


def upload_and_index_resource(client: TestClient, *, workspace_id: str) -> dict[str, object]:
    uploaded = client.post(
        "/resource/upload",
        json={
            "workspace_id": workspace_id,
            "kind": "markdown",
            "name": "delete-me.md",
            "source": "inline://delete-me.md",
            "content": "# Delete me\nThis resource must be removed from persistent state.\n",
            "content_encoding": "utf-8",
        },
    )
    assert uploaded.status_code == 200, uploaded.text

    indexed = client.post(
        "/resource/index",
        json={
            "workspace_id": workspace_id,
            "resource_id": uploaded.json()["id"],
            "enable_network": False,
        },
    )
    assert indexed.status_code == 200, indexed.text
    return indexed.json()


def test_resource_delete_removes_repository_record_and_refreshes_open_session(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-delete-api"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        indexed = upload_and_index_resource(client, workspace_id=workspace_id)

        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Delete API"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        state = runtime.ensure_session(session_id, workspace_id=workspace_id)
        assert indexed["id"] in {resource.id for resource in state.snapshot.memory.resources}

        deleted = client.post(
            "/resource/delete",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "resource_id": indexed["id"],
            },
        )

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["removed"] is True
    assert runtime.repository.get_resource(workspace_id, indexed["id"]) is None
    assert indexed["id"] not in {resource.id for resource in state.snapshot.memory.resources}


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


def test_explicit_workspace_id_isolated_from_a_stale_session_across_resource_routes(
    tmp_path: Path,
) -> None:
    stale_workspace_id = "workspace-resource-stale-session"
    target_workspace_id = "workspace-resource-explicit-target"
    with build_client(tmp_path) as client:
        stale_resource = upload_and_index_resource(client, workspace_id=stale_workspace_id)
        started = client.post(
            "/session/start",
            json={"workspace_id": stale_workspace_id, "workspace_name": "Stale session"},
        )
        assert started.status_code == 200, started.text
        stale_session_id = started.json()["session_id"]
        runtime = client.app.state.runtime

        active_target_state = runtime.ensure_session(
            stale_session_id,
            workspace_id=target_workspace_id,
        )
        assert active_target_state.workspace_id == target_workspace_id
        assert active_target_state.session_id != stale_session_id

        runtime.sessions.pop(stale_session_id)

        target_state = runtime.ensure_session(
            stale_session_id,
            workspace_id=target_workspace_id,
        )
        assert target_state.workspace_id == target_workspace_id
        assert target_state.session_id != stale_session_id
        assert stale_session_id not in runtime.sessions

        uploaded = client.post(
            "/resource/upload",
            json={
                "session_id": stale_session_id,
                "workspace_id": target_workspace_id,
                "kind": "markdown",
                "name": "target.md",
                "source": "inline://target.md",
                "content": "# Target resource\nThis belongs only to the explicit workspace.\n",
                "content_encoding": "utf-8",
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        target_resource_id = uploaded.json()["id"]

        indexed = client.post(
            "/resource/index",
            json={
                "session_id": stale_session_id,
                "workspace_id": target_workspace_id,
                "resource_id": target_resource_id,
                "enable_network": False,
            },
        )
        search = client.post(
            "/resource/search",
            json={
                "session_id": stale_session_id,
                "workspace_id": target_workspace_id,
                "query": "explicit workspace",
            },
        )
        snapshot = client.get(
            "/memory/summary",
            params={"session_id": stale_session_id, "workspace_id": target_workspace_id},
        )

        assert indexed.status_code == 200, indexed.text
        assert search.status_code == 200, search.text
        assert search.json()["workspace_id"] == target_workspace_id
        assert [hit["resource_id"] for hit in search.json()["hits"]] == [target_resource_id]
        assert snapshot.status_code == 200, snapshot.text
        assert target_resource_id in {item["id"] for item in snapshot.json()["memory"]["resources"]}
        assert stale_resource["id"] not in {item["id"] for item in snapshot.json()["memory"]["resources"]}

        deleted = client.post(
            "/resource/delete",
            json={
                "session_id": stale_session_id,
                "workspace_id": target_workspace_id,
                "resource_id": target_resource_id,
            },
        )
        trash = client.get(
            "/resource/trash",
            params={"session_id": stale_session_id, "workspace_id": target_workspace_id},
        )
        restored = client.post(
            "/resource/restore",
            json={
                "session_id": stale_session_id,
                "workspace_id": target_workspace_id,
                "resource_id": target_resource_id,
            },
        )

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["removed"] is True
    assert trash.status_code == 200, trash.text
    assert trash.json()["workspace_id"] == target_workspace_id
    assert [item["resource_id"] for item in trash.json()["items"]] == [target_resource_id]
    assert restored.status_code == 200, restored.text
    assert restored.json()["restored"] is True
    assert runtime.repository.get_resource(stale_workspace_id, stale_resource["id"]) is not None
    assert runtime.repository.get_resource(target_workspace_id, target_resource_id) is not None
