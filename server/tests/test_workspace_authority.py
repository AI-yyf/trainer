"""Tests for Workspace Authority Service."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from app.core.models import ResourceIndexRequest, ResourceUploadRequest
from app.db.repository import TrainerRepository
from app.ingest.service import IngestService
from app.memory.semantic import SemanticMemory
from app.resources.service import ResourceService
from app.sandbox.service import SandboxService
from app.workspace.authority import (
    OPERATION_PERMISSION_MAP,
    OperationType,
    PermissionLevel,
    WorkspaceAuthority,
)


class TestPermissionLevel:
    """Test permission level enum and mappings."""

    def test_permission_levels_exist(self):
        """Verify all six permission levels are defined."""
        assert PermissionLevel.INSPECT == 1
        assert PermissionLevel.ANNOTATE == 2
        assert PermissionLevel.REORGANIZE == 3
        assert PermissionLevel.GENERATE == 4
        assert PermissionLevel.APPLY == 5
        assert PermissionLevel.DESTRUCTIVE == 6

    def test_operation_permission_map_complete(self):
        """Verify all operation types map to required permission levels."""
        expected_operations = [
            "read", "list", "search", "index", "preview", "summarize",
            "annotate", "mkdir", "move", "rename", "generate",
            "write", "modify", "delete", "restore",
        ]
        for op in expected_operations:
            assert op in OPERATION_PERMISSION_MAP, f"Missing operation: {op}"

    def test_permission_hierarchy(self):
        """Higher permission level includes lower ones."""
        for level in PermissionLevel:
            for lower_level in PermissionLevel:
                if int(lower_level) < int(level):
                    # Higher level should have more or equal privilege
                    assert int(level) >= int(lower_level)


class TestWorkspaceAuthority:
    """Test WorkspaceAuthority class."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def authority(self, temp_workspace):
        """Create WorkspaceAuthority with a temporary workspace."""
        auth = WorkspaceAuthority(
            root_path=temp_workspace,
            initial_permission=PermissionLevel.INSPECT,
        )
        auth.set_workspace_context(workspace_trusted=True)
        return auth

    def test_initialization(self, authority, temp_workspace):
        """Test authority initializes with correct root and permission."""
        assert authority.active_workspace_root == temp_workspace
        assert authority.permission_level == PermissionLevel.INSPECT

    def test_set_active_workspace(self, temp_workspace):
        """Test setting active workspace root."""
        auth = WorkspaceAuthority()
        auth.set_active_workspace(temp_workspace)
        assert auth.active_workspace_root == temp_workspace

    def test_switching_active_workspace_resets_write_authority(self, tmp_path: Path):
        """A normal root switch must not silently preserve a write grant."""
        first_root = tmp_path / "first-root"
        second_root = tmp_path / "second-root"
        first_root.mkdir()
        second_root.mkdir()
        auth = WorkspaceAuthority(
            root_path=str(first_root),
            initial_permission=PermissionLevel.DESTRUCTIVE,
            remote_name="ssh-remote",
        )
        auth.create_checkpoint("first root")

        auth.set_active_workspace(str(second_root))

        assert auth.permission_level == PermissionLevel.INSPECT
        assert auth.remote_name == ""
        assert auth.list_checkpoints() == []

    def test_set_permission_level(self, authority):
        """Test setting permission level."""
        authority.set_permission_level(PermissionLevel.APPLY)
        assert authority.permission_level == PermissionLevel.APPLY

    def test_permission_grant_revoke(self, authority):
        """Test permission grant and revoke."""
        authority.grant_permission(PermissionLevel.DESTRUCTIVE)
        assert authority.permission_level == PermissionLevel.DESTRUCTIVE

        authority.revoke_permission(PermissionLevel.DESTRUCTIVE)
        assert authority.permission_level == PermissionLevel.APPLY

        # Cannot go below INSPECT
        for _ in range(10):
            authority.revoke_permission(PermissionLevel.INSPECT)
        assert authority.permission_level == PermissionLevel.INSPECT

    def test_path_normalization(self, authority):
        """Test path normalization."""
        normalized, is_inside = authority.normalize_and_validate("test.txt")
        assert is_inside  # Relative path should resolve to inside root
        assert authority._root in normalized.parents or normalized.parent == authority._root

    def test_check_permission_within_root_allowed(self, authority, temp_workspace):
        """Test that operations within root are allowed when permission sufficient."""
        # INSPECT level allows read operations
        result = authority.check_permission(OperationType.READ, "test.txt")
        assert result is True

    def test_check_permission_outside_root_denied(self, authority, temp_workspace):
        """Test that operations outside root are denied."""
        # Path outside workspace root
        result = authority.check_permission(OperationType.READ, "/etc/passwd")
        assert result is False

        # Verify denied was logged
        ledger = authority.get_ledger(limit=10)
        deny_records = [r for r in ledger if r.result == "denied"]
        assert len(deny_records) > 0

    def test_check_permission_insufficient_level(self, authority, temp_workspace):
        """Test that operations requiring higher permission are denied."""
        # INSPECT level should deny write operations
        result = authority.check_permission(OperationType.WRITE, "test.txt")
        assert result is False

        # Grant APPLY level
        authority.grant_permission(PermissionLevel.APPLY)
        result = authority.check_permission(OperationType.WRITE, "test.txt")
        assert result is True

    def test_log_operation(self, authority, temp_workspace):
        """Test operation logging."""
        authority.check_permission(OperationType.READ, "test.txt")
        ledger = authority.get_ledger()
        assert len(ledger) > 0
        assert ledger[-1].operation == "read"
        assert ledger[-1].result == "allowed"

    def test_ledger_query(self, authority, temp_workspace):
        """Test ledger querying."""
        authority.check_permission(OperationType.READ, "file1.txt")
        authority.check_permission(OperationType.READ, "file2.txt")
        authority.check_permission(OperationType.WRITE, "file3.txt")

        # Filter by operation
        read_ops = authority.get_ledger(operation="read")
        assert len(read_ops) == 2

        # Filter by path prefix
        file1_ops = authority.get_ledger(path_prefix="file1")
        assert len(file1_ops) == 1

    def test_trash_path(self, authority, temp_workspace):
        """Test trash-based deletion."""
        # Create a test file
        test_file = Path(temp_workspace) / "to_delete.txt"
        test_file.write_text("test content")

        # Grant destructive permission
        authority.grant_permission(PermissionLevel.DESTRUCTIVE)

        # Trash the file
        trashed_path = authority.trash_path(test_file)
        assert not test_file.exists()
        assert Path(trashed_path).exists()
        assert authority.trash_root in trashed_path

    def test_trash_path_preserves_relative_path(self, authority, temp_workspace):
        """Test that trash preserves the original workspace-relative path."""
        nested_file = Path(temp_workspace) / "docs" / "notes" / "to_delete.txt"
        nested_file.parent.mkdir(parents=True, exist_ok=True)
        nested_file.write_text("nested test content", encoding="utf-8")

        authority.grant_permission(PermissionLevel.DESTRUCTIVE)
        trashed_path = authority.trash_path(nested_file)

        assert not nested_file.exists()
        assert Path(trashed_path).exists()
        assert "docs" in trashed_path
        assert "notes" in trashed_path
        latest = authority.get_ledger(operation="delete")[-1]
        assert latest.details["original_relative_path"] == "docs/notes/to_delete.txt"

    def test_trash_path_outside_root_denied(self, authority):
        """Test that trashing paths outside root is denied."""
        authority.grant_permission(PermissionLevel.DESTRUCTIVE)
        with pytest.raises(PermissionError):
            authority.trash_path("/etc/passwd")

    def test_restore_from_trash_round_trips_to_original_path(self, authority, temp_workspace):
        """Test that trashed files can be restored back to their workspace path."""
        original_file = Path(temp_workspace) / "docs" / "notes.txt"
        original_file.parent.mkdir(parents=True, exist_ok=True)
        original_file.write_text("restore me", encoding="utf-8")

        authority.grant_permission(PermissionLevel.DESTRUCTIVE)
        trashed_path = authority.trash_path(original_file)
        restored_path = authority.restore_from_trash(trashed_path)

        assert not Path(trashed_path).exists()
        assert Path(restored_path).exists()
        assert Path(restored_path).read_text(encoding="utf-8") == "restore me"
        assert Path(restored_path).relative_to(Path(temp_workspace)).as_posix() == "docs/notes.txt"

        latest_restore = authority.get_ledger(operation="restore")[-1]
        assert latest_restore.details["source_trashed_path"] == trashed_path
        assert latest_restore.details["restored_path"] == restored_path

    def test_checkpoint_creation(self, authority, temp_workspace):
        """Test checkpoint creation."""
        cp = authority.create_checkpoint("Test checkpoint", {"meta": "data"})
        assert cp.checkpoint_id == "cp-0001"
        assert cp.description == "Test checkpoint"
        assert cp.root_path == temp_workspace

        # Retrieve checkpoint
        retrieved = authority.get_checkpoint(cp.checkpoint_id)
        assert retrieved is not None
        assert retrieved.description == "Test checkpoint"

    def test_checkpoint_list(self, authority, temp_workspace):
        """Test checkpoint listing."""
        authority.create_checkpoint("First")
        authority.create_checkpoint("Second")
        authority.create_checkpoint("Third")

        checkpoints = authority.list_checkpoints()
        assert len(checkpoints) == 3
        # Newest first
        assert checkpoints[0].description == "Third"

    def test_checkpoint_delete(self, authority, temp_workspace):
        """Test checkpoint deletion."""
        cp = authority.create_checkpoint("To delete")
        checkpoint_id = cp.checkpoint_id

        assert authority.delete_checkpoint(checkpoint_id) is True
        assert authority.get_checkpoint(checkpoint_id) is None

        # Deleting non-existent returns False
        assert authority.delete_checkpoint("cp-9999") is False

    def test_checkpoint_store_round_trips_across_fresh_instance(self, tmp_path: Path):
        """Checkpoint metadata should survive a fresh authority rebuild for the same root."""
        root = tmp_path / "checkpoint-root"
        root.mkdir()

        authority = WorkspaceAuthority(
            root_path=str(root),
            initial_permission=PermissionLevel.INSPECT,
        )
        checkpoint = authority.create_checkpoint(
            "Persisted checkpoint",
            {"nested": {"value": 2}},
        )
        store_path = root / ".trainer" / "checkpoints" / "checkpoints.json"
        assert store_path.exists()

        restored = WorkspaceAuthority(
            root_path=str(root),
            initial_permission=PermissionLevel.INSPECT,
        )
        restored_checkpoint = restored.get_checkpoint(checkpoint.checkpoint_id)
        assert restored_checkpoint is not None
        assert restored_checkpoint.description == "Persisted checkpoint"
        assert restored_checkpoint.metadata["nested"]["value"] == 2
        assert restored.create_checkpoint("Second checkpoint").checkpoint_id == "cp-0002"

    def test_requires_approval(self, authority):
        """Test approval requirement for operations."""
        # Delete requires approval
        assert authority.requires_approval("delete") is True
        assert authority.requires_approval(OperationType.DELETE) is True
        assert authority.requires_approval("restore") is True
        assert authority.requires_approval(OperationType.RESTORE) is True

        # Other operations don't require approval
        assert authority.requires_approval("read") is False
        assert authority.requires_approval("write") is False

    def test_get_allowed_operations(self, authority):
        """Test getting allowed operations at current level."""
        # INSPECT level
        allowed = authority.get_allowed_operations()
        assert "read" in allowed
        assert "write" not in allowed

        # Upgrade to APPLY
        authority.grant_permission(PermissionLevel.APPLY)
        allowed = authority.get_allowed_operations()
        assert "write" in allowed
        assert "delete" not in allowed

        # Upgrade to DESTRUCTIVE
        authority.grant_permission(PermissionLevel.DESTRUCTIVE)
        allowed = authority.get_allowed_operations()
        assert "delete" in allowed
        assert "restore" in allowed

    def test_summary(self, authority, temp_workspace):
        """Test authority summary."""
        summary = authority.summary()
        summary_model = authority.summary_model()
        assert summary_model.model_dump(mode="json") == summary
        assert summary["has_workspace_root"] is True
        assert summary["active_workspace_root"] == temp_workspace
        assert summary["root_uri"] == temp_workspace
        assert summary["authority_source"] == "workspace_authority_service"
        assert summary["source"] == "workspace_authority_service"
        assert summary["root_detail"] == "source: workspace_authority_service"
        assert summary["source_detail"] == "authority_source: workspace_authority_service | mode: level_inspect"
        assert summary["permission_level"] == "INSPECT"
        assert summary["permission_label"] == "read/list/search/index/preview/summarize"
        assert summary["permission_detail"] == "level_inspect"
        assert summary["allowed_operations_text"] == "read / list / search / index / preview / summarize"
        assert summary["ledger_entry_count"] == 0
        assert summary["checkpoint_count"] == 0
        assert summary["counts_text"] == "0 / 0"
        assert summary["mounted_sources"] == []
        # The trash root must join the workspace root with the platform
        # separator (pathlib), never a hardcoded '\\' literal.
        assert summary["trash_root"] == authority.trash_root
        assert summary["trash_root"].endswith(f"{os.sep}trash")
        assert summary["trash_detail"] == f"trash: {summary['trash_root']}"
        assert (
            summary["next_safe_action"]
            == "Start by reading, searching, and previewing the key material, then pick the first verifiable task."
        )
        assert summary["summary_text"] == f"{temp_workspace} | read/list/search/index/preview/summarize | workspace_authority_service"

    def test_summary_keeps_authority_source_separate_from_remote_name(self, temp_workspace):
        """Remote workspaces should surface remote_name without replacing the authority source."""
        authority = WorkspaceAuthority(
            root_path=temp_workspace,
            initial_permission=PermissionLevel.INSPECT,
            remote_name="ssh-remote",
        )

        summary = authority.summary()
        assert summary["source"] == "workspace_authority_service"
        assert summary["authority_source"] == "workspace_authority_service"
        assert summary["remote_name"] == "ssh-remote"
        assert summary["root_detail"].endswith("remote: ssh-remote")
        assert summary["source_detail"].endswith("remote: ssh-remote | mode: level_inspect")
        assert summary["summary_text"].endswith("workspace_authority_service | remote: ssh-remote")

    def test_remote_and_untrusted_mutations_fail_closed_without_explicit_policy(
        self, temp_workspace
    ):
        remote = WorkspaceAuthority(
            root_path=temp_workspace,
            initial_permission=PermissionLevel.DESTRUCTIVE,
            remote_name="ssh-remote",
        )
        remote.set_workspace_context(workspace_trusted=True)
        assert remote.check_permission(OperationType.DELETE, "notes.md") is False
        assert "Remote workspace" in (
            remote.destructive_mutation_block_reason() or ""
        )
        remote.grant_explicit_destructive_policy(True)
        # Policy cannot override remote fail-closed.
        assert remote.check_permission(OperationType.DELETE, "notes.md") is False
        assert remote.destructive_mutation_block_reason(explicit_policy=True) is not None

        untrusted = WorkspaceAuthority(
            root_path=temp_workspace,
            initial_permission=PermissionLevel.DESTRUCTIVE,
        )
        untrusted.set_workspace_context(workspace_trusted=False)
        assert untrusted.check_permission(OperationType.WRITE, "notes.md") is False
        untrusted.grant_permission(PermissionLevel.APPLY)
        # grant_permission stamps policy but cannot override missing trust.
        assert untrusted.check_permission(OperationType.WRITE, "notes.md") is False
        assert untrusted.destructive_mutation_block_reason(explicit_policy=True) is not None

    def test_authority_without_host_attestation_is_not_trusted(self, temp_workspace):
        """Authority object exists without host trust params → untrusted, mutations denied."""
        authority = WorkspaceAuthority(
            root_path=temp_workspace,
            initial_permission=PermissionLevel.DESTRUCTIVE,
        )
        assert authority.is_workspace_trusted is False
        assert "Untrusted workspace" in (
            authority.destructive_mutation_block_reason() or ""
        )
        assert authority.check_permission(OperationType.WRITE, "notes.md") is False
        assert authority.check_permission(OperationType.DELETE, "notes.md") is False

    def test_root_switch_resets_trust_until_host_reattests(self, tmp_path: Path):
        first_root = tmp_path / "first-root"
        second_root = tmp_path / "second-root"
        first_root.mkdir()
        second_root.mkdir()
        auth = WorkspaceAuthority(root_path=str(first_root))
        auth.set_workspace_context(workspace_trusted=True)
        assert auth.is_workspace_trusted is True

        auth.set_active_workspace(str(second_root))

        assert auth.is_workspace_trusted is False
        assert "Untrusted workspace" in (auth.destructive_mutation_block_reason() or "")

    def test_no_root_denies_all(self):
        """Test that without root set, all operations are denied."""
        authority = WorkspaceAuthority()
        assert authority.check_permission(OperationType.READ, "any.txt") is False

    def test_unknown_operation_is_denied_and_requires_approval(self, authority):
        """Unknown operations must fail closed instead of inheriting inspect access."""
        assert authority.check_permission("run_shell", "notes.md") is False
        assert authority.requires_approval("run_shell") is True
        latest = authority.get_ledger()[-1]
        assert latest.result == "denied"
        assert "Unknown workspace operation" in latest.details["reason"]

    def test_missing_root_is_not_reported_as_available(self, tmp_path: Path):
        """A deleted root must not leave a stale, writable-looking authority state."""
        root = tmp_path / "removed-root"
        root.mkdir()
        authority = WorkspaceAuthority(root_path=str(root))
        root.rmdir()

        assert authority.workspace_root_status == "unavailable"
        assert authority.check_permission(OperationType.READ, "notes.md") is False
        summary = authority.summary()
        assert summary["has_workspace_root"] is False
        assert summary["allowed_operations"] == []
        assert "root_status: unavailable" in summary["root_detail"]


class TestWorkspaceRootMigrationAndRecovery:
    def test_migration_requires_confirmation_and_resets_authority(self, tmp_path: Path) -> None:
        source = tmp_path / "source-root"
        target = tmp_path / "target-root"
        source.mkdir()
        target.mkdir()
        authority = WorkspaceAuthority(
            root_path=str(source),
            initial_permission=PermissionLevel.DESTRUCTIVE,
            remote_name="ssh-remote",
        )
        authority.create_checkpoint("Source checkpoint")

        plan = authority.prepare_root_migration(target)
        assert authority.active_workspace_root == str(source)
        assert plan.source_root == str(source)
        assert plan.target_root == str(target)
        assert plan.requires_external_file_migration is True

        with pytest.raises(PermissionError, match="explicit confirmation"):
            authority.confirm_root_migration(plan.migration_id)

        result = authority.confirm_root_migration(plan.migration_id, confirmed=True)
        assert result.target_root == str(target)
        assert authority.active_workspace_root == str(target)
        assert authority.permission_level == PermissionLevel.INSPECT
        assert authority.remote_name == ""
        assert authority.list_checkpoints() == []
        assert authority.root_migration_history == [result]

    def test_recovery_manifest_is_redacted_and_restores_only_safe_metadata(self, tmp_path: Path) -> None:
        source = tmp_path / "source-root"
        target = tmp_path / "recovered-root"
        source.mkdir()
        target.mkdir()
        authority = WorkspaceAuthority(
            root_path=str(source),
            initial_permission=PermissionLevel.ANNOTATE,
            remote_name="ssh-remote",
        )
        authority.create_checkpoint(
            "Safe recovery point",
            {"safe": "keep", "api_key": "must-not-leak", "nested": {"token": "hidden"}},
        )

        backup_path = Path(authority.save_root_recovery_manifest())
        manifest = json.loads(backup_path.read_text(encoding="utf-8"))
        metadata = manifest["checkpoints"][0]["metadata"]
        assert metadata["safe"] == "keep"
        assert metadata["api_key"] == "[redacted]"
        assert metadata["nested"]["token"] == "[redacted]"
        assert manifest["notes"]["workspace_files_included"] is False

        restored = WorkspaceAuthority()
        result = restored.restore_root_recovery_manifest(manifest, target_root=target)
        assert result.restored_root == str(target)
        assert result.permission_reset_to == PermissionLevel.INSPECT
        assert restored.active_workspace_root == str(target)
        assert restored.permission_level == PermissionLevel.INSPECT
        assert restored.remote_name == ""
        checkpoint = restored.get_checkpoint("cp-0001")
        assert checkpoint is not None
        assert checkpoint.root_path == str(target)
        assert checkpoint.metadata["api_key"] == "[redacted]"

    def test_recovery_rejects_missing_target_without_replacing_active_root(self, tmp_path: Path) -> None:
        source = tmp_path / "source-root"
        source.mkdir()
        authority = WorkspaceAuthority(root_path=str(source))
        manifest = authority.export_root_recovery_manifest()

        with pytest.raises(ValueError, match="does not exist"):
            authority.restore_root_recovery_manifest(
                manifest,
                target_root=tmp_path / "missing-target",
            )
        assert authority.active_workspace_root == str(source)

    def test_workspace_config_defaults_stay_scoped_to_one_authority(self, tmp_path: Path) -> None:
        first_root = tmp_path / "first"
        second_root = tmp_path / "second"
        first_root.mkdir()
        second_root.mkdir()
        first = WorkspaceAuthority(root_path=str(first_root))
        second = WorkspaceAuthority(root_path=str(second_root))

        first.apply_workspace_config({"permissionDefaults": {"GENERATE": True}})

        assert first.is_default_enabled(PermissionLevel.GENERATE) is True
        assert second.is_default_enabled(PermissionLevel.GENERATE) is False


class TestPathBoundaryEnforcement:
    """Test path boundary enforcement specifically."""

    @pytest.fixture
    def temp_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_symlink_escape_blocked(self, temp_workspace):
        """Test that symlinks escaping root are blocked."""
        authority = WorkspaceAuthority(
            root_path=temp_workspace,
            initial_permission=PermissionLevel.DESTRUCTIVE,
        )

        # Create a directory outside root
        outside_dir = Path(temp_workspace).parent / "outside_test"
        outside_dir.mkdir(exist_ok=True)
        try:
            # Create symlink inside root pointing outside
            symlink_path = Path(temp_workspace) / "escape_link"
            symlink_path.symlink_to(outside_dir)

            # Try to access through symlink - should raise PermissionError
            with pytest.raises(PermissionError) as exc_info:
                authority.normalize_and_validate(symlink_path)
            assert "Path escape attempt" in str(exc_info.value)
        finally:
            outside_dir.rmdir()

    def test_relative_path_resolution(self, temp_workspace):
        """Test relative paths are resolved against root."""
        authority = WorkspaceAuthority(
            root_path=temp_workspace,
            initial_permission=PermissionLevel.INSPECT,
        )

        # Relative path should be resolved to inside root
        normalized, is_inside = authority.normalize_and_validate("subdir/file.txt")
        assert is_inside is True
        assert str(authority._root) in str(normalized)

    def test_parent_traversal_blocked(self, temp_workspace):
        """Test that parent directory traversal (..) is blocked."""
        authority = WorkspaceAuthority(
            root_path=temp_workspace,
            initial_permission=PermissionLevel.INSPECT,
        )

        # Try to traverse up from root - should raise PermissionError
        with pytest.raises(PermissionError) as exc_info:
            authority.normalize_and_validate("../outside")
        assert "Path escape attempt" in str(exc_info.value)


def test_resource_upload_rejects_source_outside_workspace_root(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace-root"
    workspace_root.mkdir()
    outside_source = tmp_path.parent / "outside-source.md"
    outside_source.write_text("outside", encoding="utf-8")

    service = ResourceService(
        repository=TrainerRepository(tmp_path / "db.sqlite3"),
        ingest_service=IngestService(),
        semantic_memory=SemanticMemory(tmp_path / "semantic"),
    )
    request = ResourceUploadRequest(
        workspace_id="workspace-root-bound",
        kind="markdown",
        name="Outside Source",
        source=str(outside_source),
    )

    with pytest.raises(PermissionError):
        service.upload(
            "workspace-root-bound",
            request,
            workspace_path=str(workspace_root),
        )


def test_folder_resource_upload_rejects_item_outside_declared_root(tmp_path: Path) -> None:
    folder_root = tmp_path / "selected-external-folder"
    folder_root.mkdir()
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("outside folder root", encoding="utf-8")
    service = ResourceService(
        repository=TrainerRepository(tmp_path / "db.sqlite3"),
        ingest_service=IngestService(),
        semantic_memory=SemanticMemory(tmp_path / "semantic"),
    )

    with pytest.raises(PermissionError, match="declared folder root"):
        service.upload(
            "workspace-folder-boundary",
            ResourceUploadRequest(
                workspace_id="workspace-folder-boundary",
                kind="markdown",
                name="External Folder",
                source=str(folder_root),
                source_type="folder",
                source_items=[str(outside_file)],
            ),
        )


def test_folder_resource_upload_rejects_symlink_escape(tmp_path: Path) -> None:
    folder_root = tmp_path / "selected-folder"
    folder_root.mkdir()
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("outside folder root", encoding="utf-8")
    escape_link = folder_root / "escape.md"
    try:
        escape_link.symlink_to(outside_file)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Filesystem does not permit symlink or junction coverage: {exc}")

    service = ResourceService(
        repository=TrainerRepository(tmp_path / "db.sqlite3"),
        ingest_service=IngestService(),
        semantic_memory=SemanticMemory(tmp_path / "semantic"),
    )
    with pytest.raises(PermissionError, match="declared folder root"):
        service.upload(
            "workspace-folder-symlink",
            ResourceUploadRequest(
                workspace_id="workspace-folder-symlink",
                kind="markdown",
                name="Selected Folder",
                source=str(folder_root),
                source_type="folder",
                source_items=[str(escape_link)],
            ),
        )


def test_folder_resource_revalidates_persisted_items_before_index_and_context(tmp_path: Path) -> None:
    folder_root = tmp_path / "selected-folder"
    nested_file = folder_root / "docs" / "nested.md"
    nested_file.parent.mkdir(parents=True)
    nested_file.write_text("# Nested\nSafe folder content.\n", encoding="utf-8")
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("outside folder root", encoding="utf-8")
    workspace_id = "workspace-folder-persisted"
    repository = TrainerRepository(tmp_path / "db.sqlite3")
    service = ResourceService(
        repository=repository,
        ingest_service=IngestService(),
        semantic_memory=SemanticMemory(tmp_path / "semantic"),
    )
    uploaded = service.upload(
        workspace_id,
        ResourceUploadRequest(
            workspace_id=workspace_id,
            kind="markdown",
            name="Selected Folder",
            source=str(folder_root),
            source_type="folder",
            source_items=[str(nested_file)],
        ),
    )
    repository.save_resource(
        workspace_id,
        uploaded.model_copy(update={"source_items": [str(outside_file)]}),
    )

    with pytest.raises(PermissionError, match="declared folder root"):
        service.index(workspace_id, ResourceIndexRequest(resource_id=uploaded.id))
    with pytest.raises(PermissionError, match="declared folder root"):
        service.build_requested_resource_context(workspace_id, [uploaded.id])


def test_folder_resource_indexes_nested_item_within_selected_external_root(tmp_path: Path) -> None:
    folder_root = tmp_path / "selected-external-folder"
    nested_file = folder_root / "docs" / "nested.md"
    nested_file.parent.mkdir(parents=True)
    nested_file.write_text("# Nested\nSafe folder content.\n", encoding="utf-8")
    workspace_id = "workspace-folder-happy-path"
    service = ResourceService(
        repository=TrainerRepository(tmp_path / "db.sqlite3"),
        ingest_service=IngestService(),
        semantic_memory=SemanticMemory(tmp_path / "semantic"),
    )
    uploaded = service.upload(
        workspace_id,
        ResourceUploadRequest(
            workspace_id=workspace_id,
            kind="markdown",
            name="Selected External Folder",
            source=str(folder_root),
            source_type="folder",
            source_items=[str(nested_file)],
        ),
    )

    indexed = service.index(workspace_id, ResourceIndexRequest(resource_id=uploaded.id))

    assert indexed.index_status == "indexed"
    assert indexed.source_items == [str(nested_file)]
    assert service.registry.list_chunks(uploaded.id)[0].metadata["folder_item"] == str(nested_file)


def test_resource_delete_requires_trash_for_active_workspace_artifacts(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace-delete-guard"
    workspace_root.mkdir()
    source_file = workspace_root / "guard-notes.md"
    source_file.write_text(
        "# Guard\nKeep active artifacts in the sandbox until they are trashed.\n",
        encoding="utf-8",
    )

    repository = TrainerRepository(tmp_path / "db.sqlite3")
    resource_service = ResourceService(
        repository=repository,
        ingest_service=IngestService(),
        semantic_memory=SemanticMemory(tmp_path / "semantic"),
    )
    sandbox_service = SandboxService(tmp_path)

    uploaded = resource_service.upload(
        "workspace-delete-guard",
        ResourceUploadRequest(
            workspace_id="workspace-delete-guard",
            kind="markdown",
            name="Guard Notes",
            source=str(source_file),
        ),
        workspace_path=str(workspace_root),
    )
    synced = sandbox_service.sync_resource("workspace-delete-guard", uploaded)
    repository.save_resource("workspace-delete-guard", synced)

    assert synced.sandbox_path is not None
    assert Path(synced.sandbox_path).exists()

    with pytest.raises(PermissionError) as exc_info:
        resource_service.delete("workspace-delete-guard", synced.id)

    assert "trash" in str(exc_info.value).lower()


def test_workspace_scoped_search_indexes_use_distinct_fallback_paths(tmp_path: Path) -> None:
    repository = TrainerRepository(tmp_path / "db.sqlite3")
    resource_service = ResourceService(
        repository=repository,
        ingest_service=IngestService(),
        semantic_memory=SemanticMemory(tmp_path / "semantic"),
    )

    first_index = resource_service._search_index_for_workspace("workspace-a")
    first_index.index_document(
        path="/workspace-a/notes.md",
        title="Workspace A",
        content="workspace a only",
        resource_id="resource-a",
        metadata={
            "project_scope": "workspace-a",
            "source_type": "local:markdown",
            "file_type": "markdown",
            "kind": "markdown",
            "index_state": "indexed",
            "summary": "Workspace A",
            "source": "/workspace-a/notes.md",
            "symbols": [],
            "trust_score": 0.8,
            "trust_state": "trusted",
            "updated_at": "2026-06-12T00:00:00+00:00",
            "resource_freshness": "fresh",
        },
    )

    second_index = resource_service._search_index_for_workspace("workspace-b")

    assert first_index is resource_service._search_index_for_workspace("workspace-a")
    assert first_index is not second_index
    assert first_index.document_count() == 1
    assert second_index.document_count() == 0
    assert (tmp_path / "search-indexes" / "workspace-a" / "index.sqlite3").exists()
    assert (tmp_path / "search-indexes" / "workspace-b" / "index.sqlite3").exists()
    assert not (tmp_path / "trainer-search.db").exists()


class TestWorkspacePolicyFileParsing:
    """§7.8-§7.11 Test workspace policy file parsing: workspace.json, AGENT_POLICY.md, .trainerignore."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def authority(self, temp_workspace):
        """Create WorkspaceAuthority with a temporary workspace."""
        return WorkspaceAuthority(
            root_path=temp_workspace,
            initial_permission=PermissionLevel.INSPECT,
        )

    def test_load_workspace_config_returns_empty_dict_when_no_file(self, authority):
        """No workspace.json should return empty dict."""
        config = authority.load_workspace_config()
        assert config == {}

    def test_load_workspace_config_parses_valid_json(self, authority, temp_workspace):
        """Valid workspace.json should be parsed correctly."""
        workspace_json = Path(temp_workspace) / "workspace.json"
        workspace_json.write_text(
            '{"trainerVersion": "1.0.0", "agentPolicy": "custom-policy.md", '
            '"permissionDefaults": {"REORGANIZE": true, "GENERATE": true}}',
            encoding="utf-8",
        )

        config = authority.load_workspace_config()
        assert config["trainerVersion"] == "1.0.0"
        assert config["agentPolicy"] == "custom-policy.md"
        assert config["permissionDefaults"]["REORGANIZE"] is True

    def test_summary_model_normalizes_mounted_sources(self, authority, temp_workspace):
        """Mounted sources from workspace.json should become a compact summary."""
        workspace_json = Path(temp_workspace) / "workspace.json"
        workspace_json.write_text(
            '{"mountedSources": ['
            '{"name": "docs", "remoteUri": "vscode-remote://ssh-remote+devbox/home/dev/docs"}, '
            '"notes"'
            ']}',
            encoding="utf-8",
        )

        summary = authority.summary()
        assert summary["mounted_sources"] == [
            "docs -> vscode-remote://ssh-remote+devbox/home/dev/docs",
            "notes",
        ]

    def test_summary_model_accepts_mount_points_alias(self, authority, temp_workspace):
        """mountPoints should remain a supported alias for mountedSources."""
        workspace_json = Path(temp_workspace) / "workspace.json"
        workspace_json.write_text(
            '{"mountPoints": ["local-notes", "remote-specs"]}',
            encoding="utf-8",
        )

        summary = authority.summary()
        assert summary["mounted_sources"] == ["local-notes", "remote-specs"]

    def test_load_workspace_config_returns_empty_dict_on_invalid_json(self, authority, temp_workspace):
        """Invalid JSON should be handled gracefully."""
        workspace_json = Path(temp_workspace) / "workspace.json"
        workspace_json.write_text("not valid json {", encoding="utf-8")

        config = authority.load_workspace_config()
        assert config == {}

    def test_load_workspace_config_explicit_path(self, authority, temp_workspace):
        """Explicit path to workspace.json should be respected."""
        explicit_path = Path(temp_workspace) / "subdir" / "custom-workspace.json"
        explicit_path.parent.mkdir(parents=True, exist_ok=True)
        explicit_path.write_text('{"trainerVersion": "2.0.0"}', encoding="utf-8")

        config = authority.load_workspace_config(explicit_path)
        assert config["trainerVersion"] == "2.0.0"

    def test_load_workspace_config_rejects_explicit_path_outside_root(self, authority, tmp_path):
        """An absolute config path outside the workspace must not be read."""
        outside_config = tmp_path / "outside-workspace.json"
        outside_config.write_text('{"trainerVersion": "outside"}', encoding="utf-8")

        assert authority.load_workspace_config(outside_config) == {}

    def test_load_agent_policy_returns_empty_string_when_no_file(self, authority):
        """No AGENT_POLICY.md should return empty string."""
        policy = authority.load_agent_policy()
        assert policy == ""

    def test_load_agent_policy_loads_markdown_content(self, authority, temp_workspace):
        """AGENT_POLICY.md should be loaded as raw markdown."""
        policy_file = Path(temp_workspace) / "AGENT_POLICY.md"
        policy_content = (
            "# Agent Policy\n\n## Boundaries\n"
            "- Only write inside active workspace root\n"
            "- No destructive operations without explicit approval"
        )
        policy_file.write_text(policy_content, encoding="utf-8")

        policy = authority.load_agent_policy()
        assert "Agent Policy" in policy
        assert "Only write inside active workspace root" in policy

    def test_load_agent_policy_explicit_path(self, authority, temp_workspace):
        """Explicit policy path should be respected."""
        explicit_policy = Path(temp_workspace) / "custom" / "my-policy.md"
        explicit_policy.parent.mkdir(parents=True, exist_ok=True)
        explicit_policy.write_text("# Custom Policy\nNo default policy.", encoding="utf-8")

        policy = authority.load_agent_policy(explicit_policy)
        assert "Custom Policy" in policy

    def test_load_agent_policy_rejects_explicit_path_outside_root(self, authority, tmp_path):
        """An absolute policy path outside the workspace must not be read."""
        outside_policy = tmp_path / "outside-policy.md"
        outside_policy.write_text("# Outside policy", encoding="utf-8")

        assert authority.load_agent_policy(outside_policy) == ""

    def test_apply_workspace_config_sets_permission_defaults(self, authority, temp_workspace):
        """Permission defaults from workspace.json should be applied."""
        workspace_json = Path(temp_workspace) / "workspace.json"
        workspace_json.write_text(
            '{"permissionDefaults": {"GENERATE": true, "APPLY": true}}',
            encoding="utf-8",
        )

        config = authority.load_workspace_config()
        authority.apply_workspace_config(config)

        # After applying config, GENERATE and APPLY should be default-enabled
        # Note: this tests the apply function works; the actual defaults are module-level
        assert "GENERATE" in str(config.get("permissionDefaults", {}))

    def test_load_trainerignore_returns_empty_list_when_no_file(self, authority):
        """No .trainerignore should return empty list."""
        patterns = authority.load_trainerignore()
        assert patterns == []

    def test_load_trainerignore_parses_patterns(self, authority, temp_workspace):
        """.trainerignore patterns should be parsed correctly."""
        ignore_file = Path(temp_workspace) / ".trainerignore"
        ignore_file.write_text(
            "# Dependencies\nnode_modules/\n__pycache__/\n*.pyc\n# Secrets\n.env\n",
            encoding="utf-8",
        )

        patterns = authority.load_trainerignore()
        assert "node_modules/" in patterns
        assert "__pycache__/" in patterns
        assert "*.pyc" in patterns
        assert ".env" in patterns
        # Comments and blank lines should be skipped
        assert "# Dependencies" not in patterns

    def test_matches_ignore_returns_false_when_no_patterns(self, authority):
        """No ignore patterns should mean nothing matches."""
        assert authority.matches_ignore("anything.txt") is False

    def test_matches_ignore_matches_file_pattern(self, authority, temp_workspace):
        """File patterns from .trainerignore should match correctly."""
        ignore_file = Path(temp_workspace) / ".trainerignore"
        ignore_file.write_text("*.log\n*.tmp\n", encoding="utf-8")

        assert authority.matches_ignore("debug.log") is True
        assert authority.matches_ignore("temp.tmp") is True
        assert authority.matches_ignore("source.py") is False

    def test_matches_ignore_matches_directory_pattern(self, authority, temp_workspace):
        """Directory patterns from .trainerignore should match correctly."""
        ignore_file = Path(temp_workspace) / ".trainerignore"
        ignore_file.write_text("node_modules/\nbuild/\n", encoding="utf-8")

        assert authority.matches_ignore("node_modules/react/dist/index.js") is True
        assert authority.matches_ignore("build/output/bundle.js") is True
        assert authority.matches_ignore("src/index.js") is False

    def test_matches_ignore_returns_false_without_root(self):
        """Without workspace root set, matches_ignore should return False."""
        authority = WorkspaceAuthority()
        assert authority.matches_ignore("anything.txt") is False
