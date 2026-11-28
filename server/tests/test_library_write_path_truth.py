"""``library_write`` must report the file that exists after auto-indexing.

Auto-indexing canonicalises a non-Markdown file in place (``notes/sample.py`` becomes
``notes/sample.md``) and removes the requested one, in both layouts: with a bound library
root, and on a cold-start workspace, where the canonical copy goes under Trainer's data
root. The tool used to be able to answer with a path that was not on disk, and the
resource record kept pointing at it, so the coach's next read, edit or soft delete on that
path returned "not found". Either way the learner's code project must stay byte-identical.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app

LAYOUTS = ["bound_library_root", "cold_start"]


def _setup_ctx(tmp_path: Path, layout: str) -> tuple[Any, ToolContext, Path, Path]:
    """An adopted-style layout: the project is registered, never adopted as a library."""
    project_root = tmp_path / "learner_project"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    if layout == "bound_library_root":
        # What the host passes once a library folder is bound: <LibraryRoot>/.trainer/runtime.
        data_dir = tmp_path / "Trainer Library Root" / ".trainer" / "runtime"
    else:
        # What the host passes before any library folder is bound: <globalStorage>/sidecar.
        data_dir = tmp_path / "globalStorage" / "sidecar"
    app = create_app(Settings(data_dir=data_dir))
    runtime = app.state.runtime
    workspace_id = "ws-write-path"
    runtime.register_workspace_path(workspace_id, str(project_root))
    library_root = Path(runtime.sandbox_service.ensure_operation_root(workspace_id)).resolve()
    ctx = ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id="sess-write-path",
        response_language="zh-CN",
        extra={},
    )
    return runtime, ctx, project_root, library_root


def _expected_after_index(requested: str, layout: str) -> str:
    # The layout is kept in the signature so every call site states which one it means;
    # the canonical copy exists in both, so the outcome does not depend on it.
    assert layout in LAYOUTS
    if not requested.lower().endswith(".md"):
        return requested.rsplit(".", 1)[0] + ".md"
    return requested


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_write_reports_a_file_that_exists_and_every_follow_up_succeeds(
    tmp_path: Path, layout: str
) -> None:
    _runtime, ctx, project_root, library_root = _setup_ctx(tmp_path, layout)
    registry = build_default_tool_registry()
    project_before = _snapshot(project_root)

    for requested in ("notes/sample.py", "notes/plain.txt", "notes/note.md"):
        written = await registry.invoke(
            ctx,
            "library_write",
            {"action": "write", "path": requested, "content": "print('hello')\n"},
        )

        assert written["ok"] is True, written
        expected = _expected_after_index(requested, layout)
        assert written["path"] == expected, written
        assert (library_root / written["path"]).is_file()
        if expected != requested:
            assert written["requested_path"] == requested, written
            assert not (library_root / requested).exists()
        else:
            assert "requested_path" not in written, written

        read_back = await registry.invoke(
            ctx, "library_read", {"action": "read_file", "path": written["path"]}
        )
        assert read_back["ok"] is True, read_back
        assert "hello" in read_back["content"]

        edited = await registry.invoke(
            ctx,
            "library_write",
            {
                "action": "edit",
                "path": written["path"],
                "old_text": "hello",
                "new_text": "goodbye",
            },
        )
        assert edited["ok"] is True, edited

        deleted = await registry.invoke(
            ctx, "library_write", {"action": "soft_delete", "path": written["path"]}
        )
        assert deleted["ok"] is True, deleted

    assert _snapshot(project_root) == project_before


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_resource_record_points_at_the_file_on_disk(tmp_path: Path, layout: str) -> None:
    runtime, ctx, project_root, library_root = _setup_ctx(tmp_path, layout)
    registry = build_default_tool_registry()

    written = await registry.invoke(
        ctx,
        "library_write",
        {"action": "write", "path": "notes/sample.py", "content": "print('hello')\n"},
    )

    assert written["ok"] is True, written
    record = runtime.repository.get_resource(ctx.workspace_id, str(written["resource_id"]))
    recorded = Path(str(record.sandbox_path))
    assert recorded.is_file(), (record.sandbox_path, sorted(p.name for p in library_root.rglob("*")))
    assert recorded == library_root / _expected_after_index("notes/sample.py", layout)
    assert recorded.is_relative_to(library_root)
    assert _snapshot(project_root) == {"app.py": b"def greet():\n    return 'hi'\n"}


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_rename_reports_the_destination_that_exists(tmp_path: Path, layout: str) -> None:
    _runtime, ctx, project_root, library_root = _setup_ctx(tmp_path, layout)
    registry = build_default_tool_registry()
    await registry.invoke(
        ctx,
        "library_write",
        {"action": "write", "path": "notes/note.md", "content": "# Note\n\nhello\n"},
    )

    renamed = await registry.invoke(
        ctx,
        "library_write",
        {"action": "rename", "path": "notes/note.md", "new_path": "notes/renamed.md"},
    )

    assert renamed["ok"] is True, renamed
    assert renamed["path"] == "notes/note.md"
    assert renamed["new_path"] == "notes/renamed.md"
    assert (library_root / renamed["new_path"]).is_file()
    assert (project_root / "app.py").read_text(encoding="utf-8") == "def greet():\n    return 'hi'\n"
    assert [p.name for p in project_root.iterdir()] == ["app.py"]


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_restore_reports_the_file_that_exists_and_reindexes_it(
    tmp_path: Path, layout: str
) -> None:
    _runtime, ctx, project_root, library_root = _setup_ctx(tmp_path, layout)
    registry = build_default_tool_registry()
    await registry.invoke(
        ctx,
        "library_write",
        {"action": "write", "path": "notes/note.md", "content": "# Note\n\nhello\n"},
    )

    deleted = await registry.invoke(
        ctx, "library_write", {"action": "soft_delete", "path": "notes/note.md"}
    )
    assert deleted["ok"] is True, deleted
    trashed = str(deleted["trashed_path"])
    assert not (library_root / "notes" / "note.md").exists()

    restored = await registry.invoke(ctx, "library_write", {"action": "restore", "path": trashed})

    assert restored["ok"] is True, restored
    assert restored["path"] == "notes/note.md", restored
    assert restored["trashed_path"] == trashed, restored
    assert restored["restored_path"] == "notes/note.md", restored
    assert restored["auto_indexed"] is True, restored
    assert (library_root / restored["path"]).is_file()
    read_back = await registry.invoke(
        ctx, "library_read", {"action": "read_file", "path": restored["path"]}
    )
    assert read_back["ok"] is True, read_back
    assert "hello" in read_back["content"]

    # An explicit destination is reported as the place the file now lives.
    deleted_again = await registry.invoke(
        ctx, "library_write", {"action": "soft_delete", "path": "notes/note.md"}
    )
    moved = await registry.invoke(
        ctx,
        "library_write",
        {
            "action": "restore",
            "path": str(deleted_again["trashed_path"]),
            "restore_path": "notes/back.md",
        },
    )
    assert moved["ok"] is True, moved
    assert moved["path"] == "notes/back.md", moved
    assert moved["restored_path"] == "notes/back.md", moved
    assert (library_root / "notes" / "back.md").is_file()
    assert [p.name for p in project_root.iterdir()] == ["app.py"]
