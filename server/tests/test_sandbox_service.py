from __future__ import annotations

from pathlib import Path

import pytest

from app.api.runtime import TrainerRuntime
from app.core.event_ledger import EventLedgerService
from app.core.models import (
    LearningPlan,
    PlanStage,
    ResourceRecord,
    SandboxBatchRenameRequest,
    SandboxDeleteRequest,
    SandboxMkdirRequest,
    SandboxPatchOperation,
    SandboxPatchRequest,
    SandboxRenameRequest,
    SandboxRestoreRequest,
    SandboxWriteRequest,
    TrainingCardCandidateSnapshot,
)
from app.sandbox.service import SandboxService
from app.workspace.authority import PermissionLevel, WorkspaceAuthority

DESTINATION_ESCAPE_PATHS = (
    "/foreign/destination.md",
    r"C:\\foreign\\destination.md",
    r"\\\\server\\share\\destination.md",
    "../foreign/destination.md",
    r"..\\foreign\\destination.md",
)


def test_workspace_root_scaffolds_trainer_layout(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    root = service.ensure_workspace_root("workspace-layout")

    expected_paths = [
        root / "plan",
        root / "cards" / "current",
        root / "cards" / "flash",
        root / "cards" / "practice",
        root / "cards" / "scenario",
        root / "cards" / "review",
        root / "knowledge" / "remote",
        root / "knowledge" / "debug",
        root / "knowledge" / "function-guidance",
        root / "knowledge" / "apis",
        root / "sources" / "inbox",
        root / "sources" / "web",
        root / "sources" / "folders",
        root / "notes",
        root / "outputs",
    ]

    for expected_path in expected_paths:
        assert expected_path.exists()
        assert expected_path.is_dir()


def test_clear_workspace_uses_trash_and_checkpoint(tmp_path: Path) -> None:
    ledger = EventLedgerService()
    service = SandboxService(data_root=tmp_path, event_ledger=ledger)
    workspace_id = "workspace-clear-root"

    root = service.ensure_workspace_root(workspace_id)
    lesson_file = root / "lesson.md"
    lesson_file.write_text("lesson", encoding="utf-8")
    nested_dir = root / "nested"
    nested_dir.mkdir()
    (nested_dir / "note.txt").write_text("nested", encoding="utf-8")

    authority = service._workspace_authority(workspace_id)

    service.clear_workspace(workspace_id)

    assert root.exists()
    assert not lesson_file.exists()
    assert not nested_dir.exists()

    summary = authority.summary()
    assert summary["checkpoint_count"] == 1
    assert (root / ".trainer" / "checkpoints" / "checkpoints.json").exists()

    delete_records = authority.get_ledger(operation="delete")
    trashed_records = [record for record in delete_records if record.details.get("trashed_path")]
    assert len(trashed_records) == 2
    assert {Path(record.details["trashed_path"]).name for record in trashed_records} == {"lesson.md", "nested"}

    trash_root = root / "trash"
    assert trash_root.exists()
    assert any(path.name == "lesson.md" for path in trash_root.rglob("lesson.md"))
    assert any(path.name == "nested" for path in trash_root.rglob("nested"))

    clear_events = ledger.query(event_type="sandbox_workspace_cleared", project_id=workspace_id)
    assert len(clear_events) == 1
    assert clear_events[0].payload_ref["checkpoint_id"] == "cp-0001"
    assert clear_events[0].payload_ref["trashed_count"] == 2
    assert len(clear_events[0].payload_ref["trashed_paths"]) == 2
    assert clear_events[0].payload_ref["patch"] == ["trash lesson.md -> lesson.md", "trash nested -> nested"]
    assert clear_events[0].payload_ref["diff_summary"] == "trash lesson.md -> lesson.md; trash nested -> nested"
    assert clear_events[0].before_state_ref["root_child_count"] >= 8
    assert clear_events[0].after_state_ref["remaining_children"] == [
        ".trainer",
        "cards",
        "knowledge",
        "notes",
        "outputs",
        "plan",
        "sources",
    ]


def test_sandbox_authority_defaults_to_inspect(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    authority = service._sandbox_authority("workspace-default-permission")

    assert authority.summary()["permission_level"] == "INSPECT"
    assert authority.permission_level.name == "INSPECT"


def test_adopted_project_authority_stays_separate_from_trainer_sandbox_writes(tmp_path: Path) -> None:
    project_root = tmp_path / "opened-project"
    project_root.mkdir()
    source_file = project_root / "main.py"
    source_file.write_text("print('original')\n", encoding="utf-8")
    project_authority = WorkspaceAuthority(
        root_path=str(project_root),
        initial_permission=PermissionLevel.INSPECT,
    )
    service = SandboxService(
        data_root=tmp_path,
        workspace_path_resolver=lambda _workspace_id: str(project_root),
        workspace_authority_resolver=lambda _workspace_id: project_authority,
    )
    workspace_id = "workspace-adopted-project-authority"

    sandbox_root = service.ensure_workspace_root(workspace_id)
    service.write(
        workspace_id,
        SandboxWriteRequest(
            workspace_id=workspace_id,
            path="notes/project-link.md",
            content="linked",
            create=True,
        ),
    )

    assert (sandbox_root / "notes" / "project-link.md").read_text(encoding="utf-8") == "linked"
    assert project_authority.permission_level is PermissionLevel.INSPECT
    assert not project_authority.check_permission("write", source_file)
    assert source_file.read_text(encoding="utf-8") == "print('original')\n"


def test_remote_project_allows_local_sandbox_write_without_touching_project(tmp_path: Path) -> None:
    project_root = tmp_path / "remote-project"
    project_root.mkdir()
    sentinel = project_root / "user-project.txt"
    sentinel.write_text("project-owned", encoding="utf-8")
    project_authority = WorkspaceAuthority(
        root_path=str(project_root),
        initial_permission=PermissionLevel.INSPECT,
        remote_name="ssh-remote",
    )
    project_authority.set_workspace_context(workspace_trusted=True)
    service = SandboxService(
        data_root=tmp_path,
        workspace_path_resolver=lambda _workspace_id: str(project_root),
        workspace_authority_resolver=lambda _workspace_id: project_authority,
    )
    workspace_id = "workspace-remote-sandbox-local-library"

    written = service.write(
        workspace_id,
        SandboxWriteRequest(
            workspace_id=workspace_id,
            path="notes/remote.md",
            content="library-local",
            create=True,
        ),
    )

    sandbox_file = service.ensure_workspace_root(workspace_id) / "notes" / "remote.md"
    assert sandbox_file.read_text(encoding="utf-8") == "library-local"
    assert written.path.replace("\\", "/").endswith("notes/remote.md")
    assert sentinel.read_text(encoding="utf-8") == "project-owned"
    assert not (project_root / "notes" / "remote.md").exists()
    summary = service.authority_summary(workspace_id)
    assert summary["resource_write_allowed"] is True
    assert summary["is_remote_workspace"] is True
    assert project_authority.check_permission("write", "user-project.txt") is False


def test_remote_project_still_denies_project_writes_when_sandbox_write_is_allowed(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "remote-project-policy-ignored"
    project_root.mkdir()
    project_authority = WorkspaceAuthority(
        root_path=str(project_root),
        initial_permission=PermissionLevel.INSPECT,
        remote_name="ssh-remote",
    )
    project_authority.set_workspace_context(workspace_trusted=True)
    service = SandboxService(
        data_root=tmp_path,
        workspace_path_resolver=lambda _workspace_id: str(project_root),
        workspace_authority_resolver=lambda _workspace_id: project_authority,
    )
    workspace_id = "workspace-remote-sandbox-project-deny"

    service.write(
        workspace_id,
        SandboxWriteRequest(
            workspace_id=workspace_id,
            path="notes/remote.md",
            content="library-local",
            create=True,
            explicit_destructive_policy=True,
        ),
    )

    assert (service.ensure_workspace_root(workspace_id) / "notes" / "remote.md").exists()
    assert "Remote workspace" in (project_authority.destructive_mutation_block_reason() or "")
    assert project_authority.check_permission("write", "notes/remote.md") is False


def test_untrusted_project_allows_local_sandbox_write_without_touching_project(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "untrusted-project-policy-ignored"
    project_root.mkdir()
    sentinel = project_root / "user-project.txt"
    sentinel.write_text("project-owned", encoding="utf-8")
    project_authority = WorkspaceAuthority(
        root_path=str(project_root),
        initial_permission=PermissionLevel.INSPECT,
    )
    project_authority.set_workspace_context(workspace_trusted=False)
    service = SandboxService(
        data_root=tmp_path,
        workspace_path_resolver=lambda _workspace_id: str(project_root),
        workspace_authority_resolver=lambda _workspace_id: project_authority,
    )
    workspace_id = "workspace-untrusted-sandbox-local-library"

    service.write(
        workspace_id,
        SandboxWriteRequest(
            workspace_id=workspace_id,
            path="notes/untrusted.md",
            content="library-local",
            create=True,
            explicit_destructive_policy=True,
        ),
    )

    assert (
        service.ensure_workspace_root(workspace_id) / "notes" / "untrusted.md"
    ).read_text(encoding="utf-8") == "library-local"
    assert sentinel.read_text(encoding="utf-8") == "project-owned"
    assert project_authority.check_permission("write", "user-project.txt") is False


def test_remote_uri_is_not_a_local_trainer_data_root() -> None:
    assert (
        TrainerRuntime._local_filesystem_root("vscode-remote://ssh-remote+lab/home/dev/project")
        is None
    )
    assert TrainerRuntime._local_filesystem_root("ssh://lab/home/dev/project") is None
    assert TrainerRuntime._local_filesystem_root("") is None


def test_trusted_local_managed_sandbox_write_allowed_without_policy(tmp_path: Path) -> None:
    project_root = tmp_path / "trusted-local-project"
    project_root.mkdir()
    project_authority = WorkspaceAuthority(
        root_path=str(project_root),
        initial_permission=PermissionLevel.INSPECT,
    )
    project_authority.set_workspace_context(workspace_trusted=True)
    service = SandboxService(
        data_root=tmp_path,
        workspace_path_resolver=lambda _workspace_id: str(project_root),
        workspace_authority_resolver=lambda _workspace_id: project_authority,
    )
    workspace_id = "workspace-trusted-local-sandbox-allow"

    service.write(
        workspace_id,
        SandboxWriteRequest(
            workspace_id=workspace_id,
            path="notes/local.md",
            content="allowed",
            create=True,
            explicit_destructive_policy=False,
        ),
    )

    assert (
        service.ensure_workspace_root(workspace_id) / "notes" / "local.md"
    ).read_text(encoding="utf-8") == "allowed"


def test_authority_without_host_attestation_blocks_sandbox_write(tmp_path: Path) -> None:
    """Authority object present but host never attested → fail-closed, not trusted theater."""
    project_root = tmp_path / "unattested-project"
    project_root.mkdir()
    project_authority = WorkspaceAuthority(
        root_path=str(project_root),
        initial_permission=PermissionLevel.DESTRUCTIVE,
    )
    assert project_authority.is_workspace_trusted is False
    service = SandboxService(
        data_root=tmp_path,
        workspace_path_resolver=lambda _workspace_id: str(project_root),
        workspace_authority_resolver=lambda _workspace_id: project_authority,
    )
    workspace_id = "workspace-unattested-sandbox-local-library"

    service.write(
        workspace_id,
        SandboxWriteRequest(
            workspace_id=workspace_id,
            path="notes/unattested.md",
            content="library-local",
            create=True,
        ),
    )

    assert (
        service.ensure_workspace_root(workspace_id) / "notes" / "unattested.md"
    ).read_text(encoding="utf-8") == "library-local"
    state = service.list_state(workspace_id, [])
    assert state.capability_summary is not None
    assert state.capability_summary.platform.workspace_trust_state == "untrusted"


def test_untrusted_project_blocks_sandbox_delete_without_explicit_policy(tmp_path: Path) -> None:
    project_root = tmp_path / "untrusted-project"
    project_root.mkdir()
    project_authority = WorkspaceAuthority(
        root_path=str(project_root),
        initial_permission=PermissionLevel.INSPECT,
    )
    project_authority.set_workspace_context(workspace_trusted=False)
    service = SandboxService(
        data_root=tmp_path,
        workspace_path_resolver=lambda _workspace_id: str(project_root),
        workspace_authority_resolver=lambda _workspace_id: project_authority,
    )
    workspace_id = "workspace-untrusted-sandbox-deny"
    root = service.ensure_workspace_root(workspace_id)
    target = root / "notes.md"
    target.write_text("keep", encoding="utf-8")

    service.delete(
        workspace_id,
        SandboxDeleteRequest(workspace_id=workspace_id, path="notes.md"),
    )

    assert not target.exists()
    assert project_authority.check_permission("delete", "notes.md") is False


def test_batch_rename_records_checkpoint_and_change_summary(tmp_path: Path) -> None:
    ledger = EventLedgerService()
    service = SandboxService(data_root=tmp_path, event_ledger=ledger)
    workspace_id = "workspace-batch-rename"

    root = service.ensure_workspace_root(workspace_id)
    first = root / "notes-a.md"
    second = root / "notes-b.md"
    first.write_text("A", encoding="utf-8")
    second.write_text("B", encoding="utf-8")

    result = service.batch_rename(
        workspace_id,
        SandboxBatchRenameRequest(
            workspace_id=workspace_id,
            items=[
                SandboxRenameRequest(path="notes-a.md", new_path="archive/notes-a.md"),
                SandboxRenameRequest(path="notes-b.md", new_path="archive/notes-b-2.md"),
            ],
        ),
    )

    assert result["ok"] is True
    assert result["item_count"] == 2
    assert result["checkpoint_id"] == "cp-0001"
    assert result["before_paths"] == ["notes-a.md", "notes-b.md"]
    assert result["after_paths"] == ["archive/notes-a.md", "archive/notes-b-2.md"]
    assert result["patch"] == ["rename notes-a.md -> archive/notes-a.md", "rename notes-b.md -> archive/notes-b-2.md"]
    assert result["diff_summary"] == "rename notes-a.md -> archive/notes-a.md; rename notes-b.md -> archive/notes-b-2.md"
    assert Path(root / "archive" / "notes-a.md").exists()
    assert Path(root / "archive" / "notes-b-2.md").exists()

    batch_events = ledger.query(event_type="sandbox_files_reorganized", project_id=workspace_id)
    assert len(batch_events) == 1
    assert batch_events[0].payload_ref["checkpoint_id"] == "cp-0001"
    assert batch_events[0].payload_ref["item_count"] == 2
    assert batch_events[0].payload_ref["patch"] == ["rename notes-a.md -> archive/notes-a.md", "rename notes-b.md -> archive/notes-b-2.md"]
    assert batch_events[0].payload_ref["diff_summary"] == "rename notes-a.md -> archive/notes-a.md; rename notes-b.md -> archive/notes-b-2.md"
    assert batch_events[0].before_state_ref["paths"] == ["notes-a.md", "notes-b.md"]
    assert batch_events[0].after_state_ref["paths"] == ["archive/notes-a.md", "archive/notes-b-2.md"]


def test_batch_rename_is_atomic_when_a_later_item_escapes_root(tmp_path: Path) -> None:
    ledger = EventLedgerService()
    service = SandboxService(data_root=tmp_path, event_ledger=ledger)
    workspace_id = "workspace-batch-rename-atomic"

    root = service.ensure_workspace_root(workspace_id)
    first = root / "notes-a.md"
    second = root / "notes-b.md"
    first.write_text("A", encoding="utf-8")
    second.write_text("B", encoding="utf-8")

    with pytest.raises(ValueError):
        service.batch_rename(
            workspace_id,
            SandboxBatchRenameRequest(
                workspace_id=workspace_id,
                items=[
                    SandboxRenameRequest(path="notes-a.md", new_path="archive/notes-a.md"),
                    SandboxRenameRequest(path="notes-b.md", new_path="../outside/notes-b.md"),
                ],
            ),
        )

    assert first.exists()
    assert second.exists()
    assert not (root / "archive").exists()
    authority = service._workspace_authority(workspace_id)
    assert authority.summary()["checkpoint_count"] == 0
    assert ledger.query(event_type="sandbox_files_reorganized", project_id=workspace_id) == []


def test_write_rejects_paths_outside_the_active_workspace_root(tmp_path: Path) -> None:
    ledger = EventLedgerService()
    service = SandboxService(data_root=tmp_path, event_ledger=ledger)
    workspace_id = "workspace-write-escape"

    root = service.ensure_workspace_root(workspace_id)
    outside_candidate = root.parent / "outside.md"

    with pytest.raises(ValueError, match="active workspace root"):
        service.write(
            workspace_id,
            SandboxWriteRequest(
                workspace_id=workspace_id,
                path="../outside.md",
                content="escape attempt",
            ),
        )

    assert not outside_candidate.exists()
    authority = service._workspace_authority(workspace_id)
    boundary_records = authority.get_ledger(operation="write")
    assert boundary_records
    assert boundary_records[-1].result == "denied"
    assert boundary_records[-1].details["reason"] == "Path is outside the active workspace root."
    assert boundary_records[-1].details["activeWorkspaceRoot"] == authority.active_workspace_root


@pytest.mark.parametrize("destination", DESTINATION_ESCAPE_PATHS)
def test_write_rejects_nonrelative_destinations_without_writes_or_checkpoints(
    tmp_path: Path,
    destination: str,
) -> None:
    service = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-write-destination-escape"
    service.ensure_workspace_root(workspace_id)

    with pytest.raises(ValueError, match="active workspace root"):
        service.write(
            workspace_id,
            SandboxWriteRequest(
                workspace_id=workspace_id,
                path=destination,
                content="foreign write attempt",
                create=True,
            ),
        )

    authority = service._workspace_authority(workspace_id)
    assert not (tmp_path / "foreign" / "destination.md").exists()
    assert authority.summary()["checkpoint_count"] == 0
    denied = authority.get_ledger(operation="write")[-1]
    assert denied.result == "denied"
    assert denied.path == destination


@pytest.mark.parametrize("destination", DESTINATION_ESCAPE_PATHS)
def test_rename_rejects_nonrelative_destinations_without_writes_or_checkpoints(
    tmp_path: Path,
    destination: str,
) -> None:
    service = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-rename-destination-escape"
    root = service.ensure_workspace_root(workspace_id)
    source = root / "source.md"
    source.write_text("rename source", encoding="utf-8")

    with pytest.raises(ValueError, match="active workspace root"):
        service.rename(
            workspace_id,
            SandboxRenameRequest(path="source.md", new_path=destination),
        )

    authority = service._workspace_authority(workspace_id)
    assert source.exists()
    assert not (tmp_path / "foreign" / "destination.md").exists()
    assert authority.summary()["checkpoint_count"] == 0
    denied = authority.get_ledger(operation="rename")[-1]
    assert denied.result == "denied"
    assert denied.path == "source.md"
    assert denied.details["newPath"] == destination


@pytest.mark.parametrize("destination", DESTINATION_ESCAPE_PATHS)
def test_restore_rejects_nonrelative_destinations_before_creating_a_checkpoint(
    tmp_path: Path,
    destination: str,
) -> None:
    service = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-restore-destination-escape"
    root = service.ensure_workspace_root(workspace_id)
    source = root / "restore.md"
    source.write_text("restore source", encoding="utf-8")
    service.delete(workspace_id, SandboxDeleteRequest(workspace_id=workspace_id, path="restore.md"))
    trashed_path = next((root / "trash").rglob("restore.md"))
    authority = service._workspace_authority(workspace_id)
    checkpoints_before = authority.summary()["checkpoint_count"]

    with pytest.raises(ValueError, match="active workspace root"):
        service.restore(
            workspace_id,
            SandboxRestoreRequest(path=str(trashed_path), restore_path=destination, workspace_id=workspace_id),
        )

    assert trashed_path.exists()
    assert not source.exists()
    assert not (tmp_path / "foreign" / "destination.md").exists()
    assert authority.summary()["checkpoint_count"] == checkpoints_before
    denied = authority.get_ledger(operation="restore")[-1]
    assert denied.result == "denied"
    assert denied.path == str(trashed_path)
    assert denied.details["restorePath"] == destination


def test_destinations_through_escaping_symlinks_are_rejected_before_side_effects(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-symlink-destination-escape"
    root = service.ensure_workspace_root(workspace_id)
    outside = tmp_path / "outside"
    outside.mkdir()
    escape_link = root / "escape"
    try:
        escape_link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink or junction creation is unavailable: {exc}")

    source = root / "source.md"
    source.write_text("source", encoding="utf-8")
    with pytest.raises(ValueError, match="active workspace root"):
        service.write(
            workspace_id,
            SandboxWriteRequest(
                workspace_id=workspace_id,
                path="escape/written.md",
                content="foreign write attempt",
                create=True,
            ),
        )
    with pytest.raises(ValueError, match="active workspace root"):
        service.rename(
            workspace_id,
            SandboxRenameRequest(path="source.md", new_path="escape/renamed.md"),
        )

    service.delete(workspace_id, SandboxDeleteRequest(workspace_id=workspace_id, path="source.md"))
    trashed_path = next((root / "trash").rglob("source.md"))
    authority = service._workspace_authority(workspace_id)
    checkpoints_before = authority.summary()["checkpoint_count"]
    with pytest.raises(ValueError, match="active workspace root"):
        service.restore(
            workspace_id,
            SandboxRestoreRequest(
                workspace_id=workspace_id,
                path=str(trashed_path),
                restore_path="escape/restored.md",
            ),
        )

    assert source.exists() is False
    assert trashed_path.exists()
    assert not (outside / "written.md").exists()
    assert not (outside / "renamed.md").exists()
    assert not (outside / "restored.md").exists()
    assert authority.summary()["checkpoint_count"] == checkpoints_before
    assert {record.operation for record in authority.get_ledger() if record.result == "denied"} >= {
        "write",
        "rename",
        "restore",
    }


def test_mkdir_creates_nested_directories_and_returns_selected_state(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-mkdir"

    state = service.mkdir(
        workspace_id,
        SandboxMkdirRequest(workspace_id=workspace_id, path="packs/remote/ssh"),
    )

    root = service.ensure_workspace_root(workspace_id)
    target = root / "packs" / "remote" / "ssh"
    assert target.exists()
    assert target.is_dir()
    assert state.selected_path == str(target)
    assert state.preview is not None
    assert state.preview.path == str(target)
    assert state.preview.node_kind == "directory"
    assert state.preview.metadata["child_count"] == 0
    assert state.total_directories >= 18


def test_sync_resource_defaults_to_trainer_sources_layout(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-sync-layout"
    local_source = tmp_path / "lesson.md"
    local_source.write_text("# Lesson\n", encoding="utf-8")

    resource = ResourceRecord(
        id="resource-1",
        workspace_id=workspace_id,
        kind="markdown",
        name="lesson.md",
        source=str(local_source),
    )

    synced = service.sync_resource(workspace_id, resource)

    assert synced.sandbox_path is not None
    assert synced.sandbox_path.replace("\\", "/").endswith("/sources/inbox/resource-1/lesson.md")
    assert Path(str(synced.sandbox_path)).exists()


def test_sync_resource_preserves_nested_collection_paths_without_flattening(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-collection-paths"
    source_root = tmp_path / "source-root"
    alpha_source = source_root / "nested" / "alpha" / "readme.md"
    beta_source = source_root / "nested" / "beta" / "readme.md"
    alpha_source.parent.mkdir(parents=True)
    beta_source.parent.mkdir(parents=True)
    alpha_source.write_text("alpha", encoding="utf-8")
    beta_source.write_text("beta", encoding="utf-8")

    alpha = service.sync_resource(
        workspace_id,
        ResourceRecord(
            id="resource-alpha",
            kind="markdown",
            name="readme.md",
            source=str(alpha_source),
            collection_path=f"{source_root.name}/nested/alpha/readme.md",
            collection_root=str(source_root),
        ),
    )
    beta = service.sync_resource(
        workspace_id,
        ResourceRecord(
            id="resource-beta",
            kind="markdown",
            name="readme.md",
            source=str(beta_source),
            collection_path=f"{source_root.name}/nested/beta/readme.md",
            collection_root=str(source_root),
        ),
    )

    root = service.ensure_workspace_root(workspace_id)
    alpha_path = Path(str(alpha.sandbox_path))
    beta_path = Path(str(beta.sandbox_path))
    assert alpha_path != beta_path
    assert alpha_path.parents[2] == beta_path.parents[2]
    assert alpha_path.parents[2].parent.name == "collections"
    assert alpha_path.relative_to(root).as_posix().startswith("sources/collections/")
    assert beta_path.relative_to(root).as_posix().startswith("sources/collections/")
    assert alpha_path.parent != beta_path.parent
    assert alpha_path.read_text(encoding="utf-8") == "alpha"
    assert beta_path.read_text(encoding="utf-8") == "beta"


def test_sync_resource_isolates_equal_collection_paths_from_distinct_source_roots(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-collection-isolation"
    first_root = tmp_path / "first-root"
    second_root = tmp_path / "second-root"
    first_source = first_root / "nested" / "alpha" / "readme.md"
    second_source = second_root / "nested" / "alpha" / "readme.md"
    first_source.parent.mkdir(parents=True)
    second_source.parent.mkdir(parents=True)
    first_source.write_text("first source", encoding="utf-8")
    second_source.write_text("second source", encoding="utf-8")

    first = service.sync_resource(
        workspace_id,
        ResourceRecord(
            id="resource-first",
            kind="markdown",
            name="readme.md",
            source=str(first_source),
            collection_path=f"{first_root.name}/nested/alpha/readme.md",
            collection_root=str(first_root),
        ),
    )
    second = service.sync_resource(
        workspace_id,
        ResourceRecord(
            id="resource-second",
            kind="markdown",
            name="readme.md",
            source=str(second_source),
            collection_path=f"{second_root.name}/nested/alpha/readme.md",
            collection_root=str(second_root),
        ),
    )

    first_path = Path(str(first.sandbox_path))
    second_path = Path(str(second.sandbox_path))
    assert first_path != second_path
    assert first_path.parents[2] != second_path.parents[2]
    assert first_path.read_text(encoding="utf-8") == "first source"
    assert second_path.read_text(encoding="utf-8") == "second source"


def test_sync_resource_isolates_duplicate_collection_records_and_delete_keeps_peer(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-duplicate-collection-records"
    source_root = tmp_path / "source-root"
    source = source_root / "nested" / "readme.md"
    source.parent.mkdir(parents=True)
    source.write_text("shared source", encoding="utf-8")
    collection_path = f"{source_root.name}/nested/readme.md"

    first = service.sync_resource(
        workspace_id,
        ResourceRecord(
            id="resource-first",
            kind="markdown",
            name="readme.md",
            source=str(source),
            collection_path=collection_path,
            collection_root=str(source_root),
        ),
    )
    second = service.sync_resource(
        workspace_id,
        ResourceRecord(
            id="resource-second",
            kind="markdown",
            name="readme.md",
            source=str(source),
            collection_path=collection_path,
            collection_root=str(source_root),
        ),
    )

    first_path = Path(str(first.sandbox_path))
    second_path = Path(str(second.sandbox_path))
    service.remove_resource(workspace_id, first, linked_resources=[first, second])

    assert first_path != second_path
    assert not first_path.exists()
    assert second_path.exists()
    assert second_path.read_text(encoding="utf-8") == "shared source"


def test_remove_resource_accepts_absolute_artifact_path_with_relative_sandbox_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    service = SandboxService(data_root=Path("data"))
    workspace_id = "workspace-inline-absolute-path"
    root = service.ensure_workspace_root(workspace_id)
    artifact = (root / "knowledge" / "inline.md").resolve()
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("inline resource", encoding="utf-8")

    resource = ResourceRecord(
        id="resource-inline-absolute",
        kind="markdown",
        name="inline.md",
        source="inline://resource-inline-absolute",
        sandbox_path=str(artifact),
    )

    result = service.remove_resource(workspace_id, resource, linked_resources=[resource])

    assert result["primary_trashed_path"]
    assert not artifact.exists()


def test_sync_resource_without_collection_proof_falls_back_to_resource_scoped_inbox(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-legacy-collection-paths"
    source_root = tmp_path / "source-root"
    alpha_source = source_root / "nested" / "alpha" / "readme.md"
    beta_source = source_root / "nested" / "beta" / "readme.md"
    alpha_source.parent.mkdir(parents=True)
    beta_source.parent.mkdir(parents=True)
    alpha_source.write_text("alpha", encoding="utf-8")
    beta_source.write_text("beta", encoding="utf-8")

    alpha = service.sync_resource(
        workspace_id,
        ResourceRecord(
            id="legacy-resource-alpha",
            kind="markdown",
            name="readme.md",
            source=str(alpha_source),
            collection_path="nested/alpha/readme.md",
        ),
    )
    beta = service.sync_resource(
        workspace_id,
        ResourceRecord(
            id="legacy-resource-beta",
            kind="markdown",
            name="readme.md",
            source=str(beta_source),
            collection_path="nested/beta/readme.md",
        ),
    )

    alpha_path = Path(str(alpha.sandbox_path))
    beta_path = Path(str(beta.sandbox_path))
    root = service.ensure_workspace_root(workspace_id)
    assert alpha_path.relative_to(root).as_posix().startswith("sources/inbox/legacy-resource-alpha/")
    assert beta_path.relative_to(root).as_posix().startswith("sources/inbox/legacy-resource-beta/")
    assert alpha_path.read_text(encoding="utf-8") == "alpha"
    assert beta_path.read_text(encoding="utf-8") == "beta"


@pytest.mark.parametrize("collection_path", ["../escape.md", "/absolute/readme.md", r"nested\\readme.md"])
def test_sync_resource_rejects_unsafe_collection_paths(tmp_path: Path, collection_path: str) -> None:
    service = SandboxService(data_root=tmp_path)
    source = tmp_path / "source" / "readme.md"
    source.parent.mkdir()
    source.write_text("safe source", encoding="utf-8")

    with pytest.raises(ValueError, match="collection_path"):
        service.sync_resource(
            "workspace-invalid-collection",
            ResourceRecord(
                id="resource-invalid-collection",
                kind="markdown",
                name="readme.md",
                source=str(source),
                collection_path=collection_path,
            ),
        )


def test_workspace_root_can_follow_fixed_project_root(tmp_path: Path) -> None:
    fixed_root = (tmp_path / "projects" / "opened-folder").resolve(strict=False)
    service = SandboxService(
        data_root=tmp_path,
        workspace_sandbox_root_resolver=lambda workspace_id: str(fixed_root)
        if workspace_id == "workspace-fixed-root"
        else None,
    )

    root = service.ensure_workspace_root("workspace-fixed-root")

    assert root == fixed_root
    assert (root / "plan").exists()
    assert (root / "cards" / "current").exists()
    assert (root / "knowledge" / "function-guidance").exists()


@pytest.mark.parametrize("override_kind", ["equal", "ancestor", "descendant"])
def test_persisted_unsafe_sandbox_root_override_falls_back_to_managed_root(
    tmp_path: Path,
    override_kind: str,
) -> None:
    workspace_id = "workspace-persisted-root-boundary"
    workspace_root = tmp_path / "opened-workspace"
    workspace_root.mkdir()
    if override_kind == "equal":
        persisted_override = workspace_root
    elif override_kind == "ancestor":
        persisted_override = workspace_root.parent
    else:
        persisted_override = workspace_root / "nested-sandbox"
        persisted_override.mkdir()
    data_root = tmp_path / "sidecar-data"
    service = SandboxService(
        data_root=data_root,
        workspace_path_resolver=lambda _: str(workspace_root),
        workspace_sandbox_root_resolver=lambda _: str(persisted_override),
    )

    root = service.ensure_workspace_root(workspace_id)

    assert root == (data_root / "sandboxes" / workspace_id).resolve(strict=False)
    assert root != persisted_override.resolve(strict=False)
    assert (root / "plan").exists()


def test_validate_workspace_sandbox_root_rejects_nested_project_path(tmp_path: Path) -> None:
    workspace_root = tmp_path / "opened-workspace"
    workspace_root.mkdir()
    nested = workspace_root / "trainer-sandbox"
    nested.mkdir()
    sibling = tmp_path / "sibling-sandbox"
    service = SandboxService(
        data_root=tmp_path / "sidecar-data",
        workspace_path_resolver=lambda _: str(workspace_root),
    )

    with pytest.raises(ValueError, match="live inside it"):
        service.validate_workspace_sandbox_root("workspace-nested-sandbox", nested)

    assert service.validate_workspace_sandbox_root("workspace-nested-sandbox", sibling) == sibling.resolve(
        strict=False
    )


def test_active_workspace_root_path_does_not_fallback_to_sandbox(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path / "sidecar-data")
    workspace_id = "workspace-no-project-root"
    sandbox_root = service.ensure_workspace_root(workspace_id)

    assert service._active_workspace_root_path(workspace_id) == ""
    assert service._active_workspace_root_path(workspace_id) != str(sandbox_root)
    summary = service.authority_summary(workspace_id)
    assert summary["active_workspace_root"] == ""
    assert summary["root_uri"] == str(sandbox_root)
    assert summary["authority_scope"] == "trainer_sandbox"


def test_suggest_workspace_project_root_uses_workspace_folder_name_and_suffixes_duplicates(
    tmp_path: Path,
) -> None:
    service = SandboxService(data_root=tmp_path)
    workspace_root = tmp_path / "opened-folder"
    workspace_root.mkdir(parents=True, exist_ok=True)

    first = service.suggest_workspace_project_root(
        "workspace-project-root",
        workspace_name="Trainer",
        workspace_path=str(workspace_root),
    )
    first.mkdir(parents=True, exist_ok=True)
    second = service.suggest_workspace_project_root(
        "workspace-project-root",
        workspace_name="Trainer",
        workspace_path=str(workspace_root),
    )

    assert first == (tmp_path / "projects" / "opened-folder").resolve(strict=False)
    assert second == (tmp_path / "projects" / "opened-folder-2").resolve(strict=False)


def test_persist_plan_card_and_evaluation_note_use_managed_paths(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-persisted-artifacts"
    plan = LearningPlan(
        id="plan-1",
        title="Remote workspace boundary",
        summary="Learn the boundary before the exercise.",
        stages=[
            PlanStage(
                id="stage-1",
                title="Boundary",
                goal="Explain the remote boundary",
                outcomes=["One trusted path fact"],
                status="active",
            )
        ],
        current_stage_id="stage-1",
        current_step="Open the current path and identify which machine owns it.",
        next_after_current="Return to Coach with the path fact.",
    )
    card = TrainingCardCandidateSnapshot(
        card_id="practice-card-1",
        title="Verify the workspace boundary",
        card_type="practice",
        status="active",
        why_now="Deeper remote coaching is unsafe until the boundary is explicit.",
        target_skill="remote boundary",
    )

    plan_preview = service.persist_plan_snapshot(workspace_id, plan, reason="generated")
    card_previews = service.persist_training_card(workspace_id, card, mark_current=True)
    evaluation_preview = service.persist_training_evaluation_note(
        workspace_id,
        card=card,
        passed=False,
        summary="Need one concrete path fact before continuing.",
        next_step="Open the mounted folder and confirm the host machine.",
        focus_area="remote boundary",
        failed_checks=["Path fact missing"],
        missing_requirements=["One real path or mount point"],
    )

    assert Path(plan_preview.path).exists()
    assert Path(card_previews["family"].path).exists()
    assert Path(card_previews["current"].path).exists()
    assert Path(evaluation_preview.path).exists()
    assert Path(plan_preview.path).read_text(encoding="utf-8").startswith("# Remote workspace boundary")
    assert "Verify the workspace boundary" in Path(card_previews["current"].path).read_text(encoding="utf-8")
    assert "Need one concrete path fact before continuing." in Path(evaluation_preview.path).read_text(
        encoding="utf-8"
    )


def test_leftover_formal_card_title_does_not_live_in_sandbox_markdown(tmp_path: Path) -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_card = f"Practice: {leftover_title}"
    recovered_step = "Add a token expiry test"
    plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id="stage-1",
        current_step=leftover_step,
        stages=[
            PlanStage(
                id="stage-1",
                title=leftover_stage,
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    card = TrainingCardCandidateSnapshot(
        card_id="card-leftover-sandbox",
        title=leftover_card,
        card_type="practice",
        status="active",
    )
    service = SandboxService(data_root=tmp_path)
    heading = service._render_training_card_markdown(
        card,
        leftover_plan=plan,
        leftover_runtime={
            "current_step": recovered_step,
            "why_now": "Expired tokens still leak.",
            "resume_state": "in_progress",
            "workspace_id": "workspace-sandbox-leftover",
        },
        leftover_task_title=leftover_title,
    ).splitlines()[0]
    assert leftover_title not in heading
    assert leftover_card not in heading
    assert leftover_stage not in heading
    assert leftover_step not in heading
    assert leftover_summary not in heading
    assert leftover_plan_id not in heading
    assert heading == f"# {recovered_step}"
    still_heading = service._render_training_card_markdown(
        card,
        leftover_plan=plan,
        leftover_runtime={
            "current_step": leftover_step,
            "plan_id": leftover_plan_id,
            "resume_state": "in_progress",
            "workspace_id": "workspace-sandbox-still-on-plan",
        },
        leftover_task_title=leftover_title,
    ).splitlines()[0]
    assert leftover_card in still_heading


def test_leftover_formal_plan_titles_do_not_live_in_sandbox_plan_markdown(tmp_path: Path) -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_goal = "Keep one check"
    leftover_task = leftover_title
    leftover_verify = "Keep the leftover verify"
    leftover_blocked = "Keep the leftover blocker"
    recovered_step = "Add a token expiry test"
    plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id="stage-1",
        current_step=leftover_step,
        verify_method=[leftover_verify],
        blocked_reason=leftover_blocked,
        stages=[
            PlanStage(
                id="stage-1",
                title=leftover_stage,
                goal=leftover_goal,
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    service = SandboxService(data_root=tmp_path)
    leftover_md = service._render_plan_markdown(
        plan,
        reason="updated",
        leftover_runtime={
            "current_step": recovered_step,
            "why_now": "Expired tokens still leak.",
            "resume_state": "in_progress",
            "workspace_id": "workspace-sandbox-leftover-plan",
        },
        leftover_task_title=leftover_task,
    )
    persisted = Path(
        service.persist_plan_snapshot(
            "workspace-sandbox-leftover-plan",
            plan,
            reason="updated",
            leftover_runtime={
                "current_step": recovered_step,
                "why_now": "Expired tokens still leak.",
                "resume_state": "in_progress",
                "workspace_id": "workspace-sandbox-leftover-plan",
            },
            leftover_task_title=leftover_task,
        ).path
    ).read_text(encoding="utf-8")
    empty_md = service._render_plan_markdown(
        plan,
        reason="updated",
        leftover_runtime={
            "current_step": "",
            "resume_state": "in_progress",
            "workspace_id": "workspace-sandbox-empty-plan",
        },
        leftover_task_title=leftover_task,
    )
    for text in (leftover_md, persisted, empty_md):
        assert leftover_title not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
        assert leftover_goal not in text
        assert leftover_verify not in text
        assert leftover_blocked not in text
        assert "## Stages" not in text
        assert "## Verify" not in text
        assert "## Blocked by" not in text
        assert "- Plan ID:" not in text
    assert leftover_md.splitlines()[0] == f"# {recovered_step}"
    assert persisted.splitlines()[0] == f"# {recovered_step}"
    assert recovered_step in leftover_md
    assert recovered_step in persisted
    assert empty_md.splitlines()[0] == "# Trainer Plan"
    still_md = service._render_plan_markdown(
        plan,
        reason="updated",
        leftover_runtime={
            "current_step": leftover_step,
            "plan_id": leftover_plan_id,
            "resume_state": "in_progress",
            "workspace_id": "workspace-sandbox-still-on-plan",
        },
        leftover_task_title=leftover_task,
    )
    assert leftover_title in still_md
    assert leftover_stage in still_md
    assert leftover_goal in still_md
    assert leftover_verify in still_md
    assert leftover_blocked in still_md
    assert "## Stages" in still_md
    assert "## Verify" in still_md
    assert "## Blocked by" in still_md
    assert f"### 1. {leftover_stage}" in still_md
    assert f"- Plan ID: {leftover_plan_id}" in still_md


def test_leftover_formal_card_title_does_not_live_in_evaluation_note_markdown(tmp_path: Path) -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_card = f"Practice: {leftover_title}"
    recovered_step = "Add a token expiry test"
    plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id="stage-1",
        current_step=leftover_step,
        stages=[
            PlanStage(
                id="stage-1",
                title=leftover_stage,
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    card = TrainingCardCandidateSnapshot(
        card_id="card-leftover-eval-note",
        title=leftover_card,
        card_type="practice",
        status="active",
    )
    service = SandboxService(data_root=tmp_path)
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-eval-note-leftover",
    }
    heading = service._render_training_evaluation_note_markdown(
        card=card,
        passed=True,
        summary="Current-file checks passed.",
        next_step="Return to Coach.",
        focus_area=leftover_title,
        failed_checks=[],
        missing_requirements=[],
        evidence_source="ide_current_file",
        leftover_plan=plan,
        leftover_runtime=advanced,
        leftover_task_title=leftover_title,
    ).splitlines()[0]
    assert leftover_title not in heading
    assert leftover_card not in heading
    assert leftover_stage not in heading
    assert leftover_step not in heading
    assert leftover_summary not in heading
    assert leftover_plan_id not in heading
    assert heading == f"# {recovered_step}"
    empty_heading = service._render_training_evaluation_note_markdown(
        card=card,
        passed=True,
        summary="Current-file checks passed.",
        next_step="Return to Coach.",
        focus_area=leftover_title,
        failed_checks=[],
        missing_requirements=[],
        evidence_source="ide_current_file",
        leftover_plan=plan,
        leftover_runtime={"current_step": "", "resume_state": "in_progress"},
        leftover_task_title=leftover_title,
    ).splitlines()[0]
    assert leftover_title not in empty_heading
    assert leftover_card not in empty_heading
    assert empty_heading == "# Training handoff"
    still_heading = service._render_training_evaluation_note_markdown(
        card=card,
        passed=True,
        summary="Current-file checks passed.",
        next_step="Return to Coach.",
        focus_area=leftover_title,
        failed_checks=[],
        missing_requirements=[],
        evidence_source="ide_current_file",
        leftover_plan=plan,
        leftover_runtime={
            "current_step": leftover_step,
            "plan_id": leftover_plan_id,
            "resume_state": "in_progress",
            "workspace_id": "workspace-eval-note-still-on-plan",
        },
        leftover_task_title=leftover_title,
    ).splitlines()[0]
    assert leftover_card in still_heading


def test_apply_patch_records_checkpoint_and_patch_summary(tmp_path: Path) -> None:
    ledger = EventLedgerService()
    service = SandboxService(data_root=tmp_path, event_ledger=ledger)
    workspace_id = "workspace-patch"

    root = service.ensure_workspace_root(workspace_id)
    first = root / "alpha.md"
    second = root / "beta.md"
    third = root / "gamma.md"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    third.write_text("gamma", encoding="utf-8")

    result = service.apply_patch(
        workspace_id,
        SandboxPatchRequest(
            workspace_id=workspace_id,
            label="Patch the workspace slice",
            note="Keep the patch narrow and reversible.",
            items=[
                SandboxPatchOperation(op="write", path="alpha.md", content="alpha updated"),
                SandboxPatchOperation(op="rename", path="beta.md", new_path="archive/beta.md"),
                SandboxPatchOperation(op="delete", path="gamma.md"),
            ],
        ),
    )

    assert result["ok"] is True
    assert result["item_count"] == 3
    assert result["checkpoint_id"] == "cp-0001"
    assert result["patch"][0] == "write alpha.md [update]"
    assert result["patch"][1] == "rename beta.md -> archive/beta.md"
    assert result["patch"][2].startswith("trash gamma.md -> trash/")
    assert result["diff_summary"].startswith("write alpha.md [update]; rename beta.md -> archive/beta.md; trash gamma.md -> trash/")
    assert first.read_text(encoding="utf-8") == "alpha updated"
    assert not second.exists()
    assert Path(root / "archive" / "beta.md").exists()
    assert not third.exists()

    patch_events = ledger.query(event_type="sandbox_patch_applied", project_id=workspace_id)
    assert len(patch_events) == 1
    assert patch_events[0].payload_ref["checkpoint_id"] == "cp-0001"
    assert patch_events[0].payload_ref["item_count"] == 3
    assert patch_events[0].payload_ref["diff_summary"] == result["diff_summary"]


def test_apply_patch_rolls_back_if_later_operation_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = EventLedgerService()
    service = SandboxService(data_root=tmp_path, event_ledger=ledger)
    workspace_id = "workspace-patch-rollback"

    root = service.ensure_workspace_root(workspace_id)
    first = root / "alpha.md"
    second = root / "beta.md"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")

    write_calls = {"count": 0}
    original_write_text = service._write_text

    def failing_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
        write_calls["count"] += 1
        if write_calls["count"] == 2:
            raise RuntimeError("forced patch failure")
        original_write_text(path, content, encoding=encoding)

    monkeypatch.setattr(service, "_write_text", failing_write_text)

    with pytest.raises(RuntimeError, match="forced patch failure"):
        service.apply_patch(
            workspace_id,
            SandboxPatchRequest(
                workspace_id=workspace_id,
                label="Rollback patch",
                items=[
                    SandboxPatchOperation(op="write", path="alpha.md", content="alpha updated"),
                    SandboxPatchOperation(op="write", path="beta.md", content="beta updated"),
                ],
            ),
        )

    assert first.read_text(encoding="utf-8") == "alpha"
    assert second.read_text(encoding="utf-8") == "beta"
    assert ledger.query(event_type="sandbox_patch_failed", project_id=workspace_id)
    authority = service._workspace_authority(workspace_id)
    assert authority.summary()["checkpoint_count"] == 1


def test_restore_restores_trashed_path_and_records_checkpoint(tmp_path: Path) -> None:
    ledger = EventLedgerService()
    service = SandboxService(data_root=tmp_path, event_ledger=ledger)
    workspace_id = "workspace-restore"

    root = service.ensure_workspace_root(workspace_id)
    lesson_file = root / "lesson.md"
    lesson_file.write_text("restore me", encoding="utf-8")

    service.delete(
        workspace_id,
        SandboxDeleteRequest(workspace_id=workspace_id, path="lesson.md"),
    )

    authority = service._workspace_authority(workspace_id)
    delete_record = authority.get_ledger(operation="delete")[-1]
    trashed_path = str(delete_record.details["trashed_path"])
    assert not lesson_file.exists()
    assert Path(trashed_path).exists()

    restored_state = service.restore(
        workspace_id,
        SandboxRestoreRequest(workspace_id=workspace_id, path=trashed_path),
    )

    assert lesson_file.exists()
    assert lesson_file.read_text(encoding="utf-8") == "restore me"
    assert not Path(trashed_path).exists()
    assert restored_state.selected_path == "lesson.md"
    assert restored_state.authority is not None
    assert restored_state.authority.checkpoint_count >= 2

    restore_events = ledger.query(event_type="sandbox_file_restored", project_id=workspace_id)
    assert len(restore_events) == 1
    assert restore_events[0].payload_ref["path"] == trashed_path
    assert restore_events[0].payload_ref["restored_path"].endswith("lesson.md")

def test_capability_summary_trust_fails_closed_without_host_authority(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    state = service.list_state("workspace-trust-unknown", [])
    assert state.capability_summary is not None
    assert state.capability_summary.platform.workspace_trust_state == "unknown"


def test_capability_summary_reflects_host_trust_and_remote(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    project_root = tmp_path / "opened-project"
    project_root.mkdir()
    authority = WorkspaceAuthority(root_path=str(project_root))
    service.set_workspace_authority_resolver(lambda _workspace_id: authority)

    authority.set_workspace_context(workspace_trusted=False)
    untrusted = service.list_state("workspace-trust-host", [])
    assert untrusted.capability_summary is not None
    assert untrusted.capability_summary.platform.workspace_trust_state == "untrusted"

    authority.set_workspace_context(
        remote_name="ssh-remote",
        workspace_trusted=True,
        replace_remote=True,
    )
    remote = service.list_state("workspace-trust-host", [])
    assert remote.capability_summary is not None
    assert remote.capability_summary.platform.workspace_trust_state == "remote"

    authority.set_workspace_context(remote_name="", workspace_trusted=True, replace_remote=True)
    trusted = service.list_state("workspace-trust-host", [])
    assert trusted.capability_summary is not None
    assert trusted.capability_summary.platform.workspace_trust_state == "trusted"


def test_capability_summary_remote_without_local_project_root(tmp_path: Path) -> None:
    service = SandboxService(data_root=tmp_path)
    authority = WorkspaceAuthority()
    authority.set_workspace_context(
        remote_name="ssh-remote",
        workspace_trusted=True,
        replace_remote=True,
    )
    service.set_workspace_authority_resolver(lambda _workspace_id: authority)
    state = service.list_state("workspace-remote-rootless", [])
    assert state.capability_summary is not None
    assert state.capability_summary.platform.workspace_trust_state == "remote"
    assert state.authority is not None
    assert state.authority.is_remote_workspace is True
    assert state.authority.remote_name == "ssh-remote"
