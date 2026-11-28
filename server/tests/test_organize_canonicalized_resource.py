"""A resource that has its canonical Markdown can still be moved into a folder.

The library keeps one artifact per resource, its canonical Markdown (SPEC §11); once that
document exists the inline upload is removed. Grouping, however, was written around the
inline snapshot: it moved that file into ``inline-resources/<workspace>/groups/<name>/``.
So for every imported and indexed document — the normal state in the product's primary
layout — "move to folder" failed with ``Only local library snapshots can be grouped.``,
through the HTTP endpoint and through the coach's organize tool alike. A group is now
metadata for such a resource: the same ``collection_path`` the folder tree already reads.
Resources whose snapshot file still exists keep the real move.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app

LAYOUTS = ["bound_library_root", "cold_start"]
NOTE = "# Rotation guard\n\nThe rotation guard runs before the retry queue drains.\n"


def _files_under(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _layout(tmp_path: Path, layout: str) -> tuple[Any, Any, Path, Path]:
    project_root = tmp_path / "learner_project"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "main.py").write_text("print('learner code')\n", encoding="utf-8")
    if layout == "bound_library_root":
        data_dir = tmp_path / "Library Root" / ".trainer" / "runtime"
    else:
        data_dir = tmp_path / "globalStorage" / "sidecar"
    app = create_app(Settings(data_dir=data_dir))
    return app, app.state.runtime, project_root, data_dir


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765")


async def _import_note(
    client: httpx.AsyncClient, workspace_id: str, project_root: Path, *, index: bool
) -> dict[str, Any]:
    started = await client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": "Organizer",
            "workspace_path": str(project_root),
        },
    )
    assert started.status_code == 200, started.text
    uploaded = await client.post(
        "/resource/upload",
        json={
            "session_id": started.json()["session_id"],
            "workspace_id": workspace_id,
            "kind": "markdown",
            "name": "Rotation guard notes",
            "source": "notes/rotation-guard.md",
            "content": NOTE,
            "source_type": "file",
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    resource_id = uploaded.json()["id"]
    if not index:
        return dict(uploaded.json())
    indexed = await client.post(
        "/resource/index",
        json={"workspace_id": workspace_id, "resource_id": resource_id, "enable_network": False},
    )
    assert indexed.status_code == 200, indexed.text
    return dict(indexed.json())


async def _organize(
    client: httpx.AsyncClient, workspace_id: str, resource_id: str, **body: Any
) -> httpx.Response:
    return await client.post(
        "/resource/organize",
        json={"workspace_id": workspace_id, "resource_id": resource_id, **body},
    )


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_an_indexed_document_moves_into_a_folder_and_out_again(tmp_path: Path, layout: str) -> None:
    app, runtime, project_root, _data_dir = _layout(tmp_path, layout)
    workspace_id = f"ws-organize-{layout}"
    service = runtime.resource_service
    async with _client(app) as client:
        indexed = await _import_note(client, workspace_id, project_root, index=True)
        resource_id = str(indexed["id"])
        assert indexed["canonical_markdown_path"], indexed
        before = runtime.repository.get_resource(workspace_id, resource_id)
        # The inline upload has been replaced by the canonical document.
        assert not Path(str(before.source)).is_file()
        assert service._canonical_markdown_path(workspace_id, before) is not None
        project_before = _files_under(project_root)

        moved = await _organize(client, workspace_id, resource_id, action="set_group", group="Papers")

        assert moved.status_code == 200, moved.text
        after = runtime.repository.get_resource(workspace_id, resource_id)
        assert after.collection_path == f"Papers/{Path(str(before.source)).name}"
        assert after.collection_root and Path(after.collection_root).parts[-2:] == ("groups", "Papers")
        # Nothing on disk moved; the document is where it was and still readable.
        assert after.source == before.source
        canonical = service._canonical_markdown_path(workspace_id, after)
        assert canonical is not None and canonical.is_file()

        cleared = await _organize(client, workspace_id, resource_id, action="set_group", group="")

        assert cleared.status_code == 200, cleared.text
        ungrouped = runtime.repository.get_resource(workspace_id, resource_id)
        assert ungrouped.collection_path is None
        assert ungrouped.collection_root in (None, "")
        assert _files_under(project_root) == project_before
    app.state.runtime.resource_service.close()


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_a_resource_still_holding_its_snapshot_keeps_the_real_move(tmp_path: Path, layout: str) -> None:
    """Before indexing the snapshot exists; grouping moves it, as it always did."""
    app, runtime, project_root, data_dir = _layout(tmp_path, layout)
    workspace_id = f"ws-organize-snapshot-{layout}"
    async with _client(app) as client:
        uploaded = await _import_note(client, workspace_id, project_root, index=False)
        resource_id = str(uploaded["id"])
        before = runtime.repository.get_resource(workspace_id, resource_id)
        original = Path(str(before.source))
        assert original.is_file()

        moved = await _organize(client, workspace_id, resource_id, action="set_group", group="Papers")

        assert moved.status_code == 200, moved.text
        after = runtime.repository.get_resource(workspace_id, resource_id)
        assert Path(str(after.source)).is_file()
        assert Path(str(after.source)).parts[-2:] == ("Papers", original.name)
        assert not original.exists()
        assert data_dir.resolve() in Path(str(after.source)).resolve().parents
    app.state.runtime.resource_service.close()


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_renaming_an_indexed_document_only_changes_the_title(tmp_path: Path, layout: str) -> None:
    app, runtime, project_root, _data_dir = _layout(tmp_path, layout)
    workspace_id = f"ws-rename-{layout}"
    service = runtime.resource_service
    async with _client(app) as client:
        indexed = await _import_note(client, workspace_id, project_root, index=True)
        resource_id = str(indexed["id"])
        before = runtime.repository.get_resource(workspace_id, resource_id)
        canonical_before = service._canonical_markdown_path(workspace_id, before)

        renamed = await _organize(
            client, workspace_id, resource_id, action="rename", title="Guard ordering notes"
        )

        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["name"] == "Guard ordering notes"
        after = runtime.repository.get_resource(workspace_id, resource_id)
        assert after.source == before.source
        assert after.collection_path == before.collection_path
        assert service._canonical_markdown_path(workspace_id, after) == canonical_before
    app.state.runtime.resource_service.close()
