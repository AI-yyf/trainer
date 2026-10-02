from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.models import ResourceRecord, SandboxPreviewRequest
from app.db.repository import TrainerRepository
from app.main import create_app
from app.workspace.runtime_path_recovery import recover_runtime_paths


def _snapshot(tmp_path: Path, *, marker: bool = False, old_root: str | None = None):
    source = tmp_path / "original data"
    repository = TrainerRepository(source / "trainer.sqlite3")
    relative = Path("sandboxes/context-one/sources/inbox/resource-one/lesson.md")
    file = source / relative
    file.parent.mkdir(parents=True)
    content = "# 元组\n\n内部列表可变。\n"
    file.write_text(content, encoding="utf-8")
    original = str(file) if old_root is None else old_root + "/" + relative.as_posix()
    external = str(tmp_path / "external-original.md")
    resource = ResourceRecord(
        id="resource-one", name="lesson.md", kind="markdown", source=external,
        canonical_source=external, sandbox_path=original,
        content_hash=hashlib.sha256(file.read_bytes()).hexdigest(),
    )
    repository.save_resource("context-one", resource)
    repository.save_structured_memory("context-one", {
        "workspace": {"sandbox_root_override": original.rsplit("/sources/", 1)[0]},
        "active_thread": {"summary": "Read " + original},
    })
    repository.save_session("session-one", "context-one", {
        "session_id": "session-one", "workspace_id": "context-one",
        "snapshot": {"resources": [resource.model_dump()], "messages": [
            {"content": original, "metadata": {"path": original}},
        ]},
    })
    if marker:
        (source / "runtime-location.json").write_text(json.dumps({
            "schemaVersion": 1, "dataRoot": old_root or str(source),
        }), encoding="utf-8")
    target = tmp_path / "restored" / ".trainer" / "runtime"
    shutil.copytree(source, target)
    # Recovery cannot fall back to the source, even when it no longer exists.
    before = hashlib.sha256((source / "trainer.sqlite3").read_bytes()).hexdigest()
    return source, target, relative, original, external, before


@pytest.mark.parametrize("marker", [False, True])
@pytest.mark.parametrize("old_root", [None, "C:/Users/Learner/AppData/Trainer"])
def test_moved_snapshot_rebases_owned_paths_without_changing_sources_or_history(tmp_path, marker, old_root):
    source, target, relative, old, external, before = _snapshot(tmp_path, marker=marker, old_root=old_root)
    database = target / "trainer.sqlite3"
    assert recover_runtime_paths(database, target) >= 3
    restored = TrainerRepository(database)
    resource = restored.get_resource("context-one", "resource-one")
    assert resource.sandbox_path == str(target / relative)
    assert resource.source == resource.canonical_source == external
    assert resource.content_hash == hashlib.sha256((target / relative).read_bytes()).hexdigest()
    memory = restored.load_structured_memory("context-one")
    assert memory["workspace"]["sandbox_root_override"] == str(target / "sandboxes/context-one")
    assert memory["active_thread"]["summary"] == "Read " + old
    session = restored.load_session("session-one")
    assert session["snapshot"]["messages"][0]["content"] == old
    assert session["snapshot"]["messages"][0]["metadata"]["path"] == str(target / relative)
    assert hashlib.sha256((source / "trainer.sqlite3").read_bytes()).hexdigest() == before
    assert recover_runtime_paths(database, target) == 0


@pytest.mark.parametrize("invalid_copy", ["missing", "different", "symlink"])
def test_legacy_recovery_requires_same_hash_copy_inside_current_data_root(tmp_path, invalid_copy):
    _, target, relative, original, _, _ = _snapshot(tmp_path)
    copied = target / relative
    if invalid_copy == "missing":
        copied.unlink()
    elif invalid_copy == "different":
        copied.write_text("Different lesson", encoding="utf-8")
    else:
        copied.unlink()
        outside = tmp_path / "outside.md"
        outside.write_text("# 元组\n\n内部列表可变。\n", encoding="utf-8")
        copied.symlink_to(outside)
    assert recover_runtime_paths(target / "trainer.sqlite3", target) == 0
    assert TrainerRepository(target / "trainer.sqlite3").get_resource("context-one", "resource-one").sandbox_path == original


def test_snapshot_startup_recovery_makes_resource_preview_use_restored_copy(tmp_path):
    source, target, relative, _, _, _ = _snapshot(tmp_path)
    shutil.rmtree(source)
    application = create_app(Settings(data_dir=target))
    runtime = application.state.runtime
    resource = runtime.repository.get_resource("context-one", "resource-one")
    assert resource.sandbox_path == str(target / relative)
    assert runtime.sandbox_service.ensure_workspace_root("context-one") == target / "sandboxes/context-one"
    preview = runtime.sandbox_service.preview("context-one", SandboxPreviewRequest(workspace_id="context-one", path=resource.sandbox_path))
    assert "内部列表可变" in preview.content
    runtime.resource_service.close()


def test_location_marker_rebases_inline_paths_and_file_uris_but_rejects_traversal(tmp_path):
    _, target, _, _, _, _ = _snapshot(tmp_path, marker=True)
    old = tmp_path / "original data"
    database = target / "trainer.sqlite3"
    repository = TrainerRepository(database)
    repository.save_structured_memory("context-two", {"workspace": {
        "path": (old / "inline-resources/context-two/reply.md").as_uri(),
        "source": str(old / "../external.md"),
        "content": str(old / "inline-resources/context-two/reply.md"),
    }})
    recover_runtime_paths(database, target)
    workspace = repository.load_structured_memory("context-two")["workspace"]
    assert workspace["path"] == (target / "inline-resources/context-two/reply.md").as_uri()
    assert workspace["source"] == str(old / "../external.md")
    assert workspace["content"] == str(old / "inline-resources/context-two/reply.md")


def test_recovery_rolls_back_all_references_on_corrupt_json(tmp_path):
    _, target, _, original, _, _ = _snapshot(tmp_path, marker=True)
    database = target / "trainer.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE structured_memory SET payload = '{broken'")
    with pytest.raises(json.JSONDecodeError):
        recover_runtime_paths(database, target)
    assert TrainerRepository(database).get_resource("context-one", "resource-one").sandbox_path == original
