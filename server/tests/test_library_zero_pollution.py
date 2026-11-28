"""A cold-start workspace never receives Trainer library files.

Before a ``<LibraryRoot>`` is bound, the extension host keeps the sidecar data dir under
``globalStorage`` and the workspace has no project provisioning. The server used to fall
back to the workspace folder as the library root in that state, so one library write
created ``Trainer Library/`` inside the learner's code repository. The product contract
(§4) promises the opposite: the code project stays untouched and the learner is guided to
bind a library folder instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _cold_start_app(tmp_path: Path) -> tuple[Any, Any, ToolContext, Path]:
    project_root = tmp_path / "learner_project"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "main.py").write_text("print('learner code')\n", encoding="utf-8")
    (project_root / ".git").mkdir()
    (project_root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    # What the host passes when no library folder is bound yet: <globalStorage>/sidecar.
    app = create_app(Settings(data_dir=tmp_path / "globalStorage" / "sidecar"))
    runtime = app.state.runtime
    workspace_id = "ws-cold-start"
    runtime.register_workspace_path(workspace_id, str(project_root))
    ctx = ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id="sess-cold-start",
        response_language="zh-CN",
        extra={},
    )
    return app, runtime, ctx, project_root


def _cold_start(tmp_path: Path) -> tuple[Any, ToolContext, Path]:
    _app, runtime, ctx, project_root = _cold_start_app(tmp_path)
    return runtime, ctx, project_root


async def test_cold_start_library_write_leaves_the_code_project_untouched(tmp_path: Path) -> None:
    runtime, ctx, project_root = _cold_start(tmp_path)
    registry = build_default_tool_registry()
    before = _snapshot(project_root)

    written = await registry.invoke(
        ctx,
        "library_write",
        {"action": "write", "path": "notes/sample.md", "content": "# 我的笔记\n\nhello\n"},
    )

    assert written["ok"] is True, written
    assert _snapshot(project_root) == before
    assert runtime.resolve_library_carrier_root(ctx.workspace_id) is None
    # The carrier authority may still exist to carry trust/remote context, but it
    # must have no writable root: no library folder is bound yet.
    authority = runtime.library_carrier_authority(ctx.workspace_id)
    assert authority is None or not authority.active_workspace_root


async def test_cold_start_lecture_note_does_not_land_in_the_code_project(tmp_path: Path) -> None:
    runtime, ctx, project_root = _cold_start(tmp_path)
    registry = build_default_tool_registry()
    before = _snapshot(project_root)

    ctx.extra["explicit_lecture_note_save_request"] = True
    saved = await registry.invoke(
        ctx,
        "library_write",
        {
            "action": "save_lecture_note",
            "title": "幂等",
            "content": "# 幂等\n\n为什么需要幂等键。\n",
        },
    )

    assert _snapshot(project_root) == before
    # Either an honest refusal, or a file somewhere other than the code project.
    if saved.get("ok") is True:
        saved_path = Path(str(saved.get("path") or saved.get("note_path") or saved.get("saved_path") or ""))
        assert saved_path and not saved_path.is_absolute() and not (project_root / saved_path).exists(), saved
        assert not saved_path.is_file() or project_root.resolve() not in saved_path.resolve().parents, saved
    else:
        assert saved.get("error"), saved
    assert not (project_root / "Trainer Library").exists()


async def test_bound_library_root_still_receives_library_files(tmp_path: Path) -> None:
    project_root = tmp_path / "learner_project"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "main.py").write_text("print('learner code')\n", encoding="utf-8")
    library_root = tmp_path / "Trainer Library Root"
    # What the host passes once a library folder is bound: <LibraryRoot>/.trainer/runtime.
    app = create_app(Settings(data_dir=library_root / ".trainer" / "runtime"))
    runtime = app.state.runtime
    workspace_id = "ws-bound"
    runtime.register_workspace_path(workspace_id, str(project_root))
    ctx = ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id="sess-bound",
        response_language="zh-CN",
        extra={},
    )
    registry = build_default_tool_registry()
    before = _snapshot(project_root)

    written = await registry.invoke(
        ctx,
        "library_write",
        {"action": "write", "path": "notes/sample.md", "content": "# 我的笔记\n\nhello\n"},
    )

    assert written["ok"] is True, written
    assert runtime.resolve_library_carrier_root(workspace_id) == library_root.resolve()
    assert _snapshot(project_root) == before
    assert any(
        path.is_file()
        for path in (library_root / "Trainer Library").rglob("*.md")
    )


async def test_cold_start_resource_import_stays_searchable_and_out_of_the_code_project(
    tmp_path: Path,
) -> None:
    """The one write the cold-start Resources page offers: import. It must work, stay
    searchable, and put everything under the data dir rather than the code project."""
    app, runtime, ctx, project_root = _cold_start_app(tmp_path)
    before = _snapshot(project_root)
    data_dir = Path(runtime.repository.database_path).parent.resolve()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
    ) as client:
        started = await client.post(
            "/session/start", json={"workspace_id": ctx.workspace_id, "workspace_name": "P"}
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        uploaded = await client.post(
            "/resource/upload",
            json={
                "workspace_id": ctx.workspace_id,
                "session_id": session_id,
                "name": "queue_lock.py",
                "kind": "code",
                "source": "file",
                "content": "import threading\n\n\nclass Queue:\n    def __init__(self):\n        self._lock = threading.Lock()\n",
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        resource_id = uploaded.json().get("id") or uploaded.json().get("resource_id")
        indexed = await client.post(
            "/resource/index",
            json={"workspace_id": ctx.workspace_id, "resource_id": resource_id, "enable_network": False},
        )
        assert indexed.status_code == 200, indexed.text
        searched = await client.post(
            "/resource/search",
            json={
                "session_id": session_id,
                "workspace_id": ctx.workspace_id,
                "query": "threading Lock",
            },
        )
        assert searched.status_code == 200, searched.text
        assert resource_id in [hit.get("id") for hit in searched.json().get("hits", [])], searched.text

    assert _snapshot(project_root) == before
    assert not (project_root / "Trainer Library").exists()
    record = runtime.repository.get_resource(ctx.workspace_id, str(resource_id))
    for raw in (getattr(record, "sandbox_path", None), getattr(record, "source", None)):
        text = str(raw or "")
        if text.startswith("/"):
            assert project_root.resolve() not in Path(text).resolve().parents, raw
            assert data_dir == Path(text).resolve() or data_dir in Path(text).resolve().parents, raw

