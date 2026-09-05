from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app


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


@pytest.mark.asyncio
async def test_path_only_organize_updates_search_and_does_not_resurrect(tmp_path: Path) -> None:
    workspace_id = "workspace-organize-library"
    settings = AppSettings(
        app_name="Trainer organize library",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-organize-library.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Organize library"},
        )
        assert started.status_code == 200, started.text
        upload = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "notes.md",
                "source": "inline://notes.md",
                "content": "unique-token-7731 login error handling notes",
            },
        )
        assert upload.status_code == 200, upload.text
        indexed = client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": upload.json()["id"]},
        )
        assert indexed.status_code == 200, indexed.text
        resource = indexed.json()
        sandbox_path = str(resource.get("sandbox_path") or "").strip()
        assert sandbox_path
        runtime = app.state.runtime
        root = runtime.sandbox_service.ensure_workspace_root(workspace_id)
        relative = Path(sandbox_path).resolve().relative_to(Path(root).resolve()).as_posix()
        target = f"archive/{Path(relative).name}"
        extra = {
            "active_view": "resources",
            "resource_composer_intent": {"mode": "organize"},
        }
        registry = build_default_tool_registry()
        proposal = await registry.invoke(
            ToolContext(
                runtime=runtime,
                workspace_id=workspace_id,
                session_id=started.json()["session_id"],
                extra=extra,
            ),
            "organize_resources",
            {"operations": [{"op": "move", "source": relative, "target": target}]},
        )
        assert proposal["committed"] is False
        committed = await registry.invoke(
            ToolContext(
                runtime=runtime,
                workspace_id=workspace_id,
                session_id=started.json()["session_id"],
                extra={**extra, "resource_organization_confirmed": True},
            ),
            "organize_resources",
            {"operations": [{"op": "move", "source": relative, "target": target}]},
        )
        assert committed["ok"] is True
        assert committed["committed"] is True
        stored = runtime.repository.get_resource(workspace_id, resource["id"])
        assert stored is not None
        assert stored.sandbox_path is not None
        assert Path(stored.sandbox_path).resolve() == (Path(root) / target).resolve()
        assert not Path(sandbox_path).exists()
        assert Path(stored.sandbox_path).exists()

        search = client.post(
            "/resource/search",
            json={"workspace_id": workspace_id, "query": "archive"},
        )
        assert search.status_code == 200, search.text
        hits = search.json().get("results") or search.json().get("hits") or []
        assert any(str(item.get("resource_id") or item.get("id") or "") == resource["id"] for item in hits)

        runtime.sandbox_service.sync_resource(workspace_id, stored)
        assert not Path(sandbox_path).exists()
        assert Path(stored.sandbox_path).exists()
