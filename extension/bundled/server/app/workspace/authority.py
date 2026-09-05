"""§7.8-§7.9 Workspace Authority Service — folder sovereignty with permission levels.

This module implements the activeWorkspaceRoot permission contract:
- Permission level enum (six levels: inspect, annotate, reorganize, generate, apply, destructive)
- Path normalization + boundary enforcement
- Operation ledger (append-only audit)
- Trash-based deletion
- Checkpoint capability

Reference: docs/open-source-fit-and-provider-strategy.md 7.8-7.9
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from hashlib import sha1
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from ..core.models import WorkspaceAuthoritySummary

# ---------------------------------------------------------------------------
# Permission Level Enum — six-level hierarchy
# ---------------------------------------------------------------------------


class PermissionLevel(IntEnum):
    """Six-level permission hierarchy (higher = more privilege)."""

    INSPECT = 1  # read/list/search/index/preview/summarize
    ANNOTATE = 2  # write notes, plans, evidence (no source code changes)
    REORGANIZE = 3  # mkdir/move/rename within root
    GENERATE = 4  # generate new files, cards, summaries, scripts
    APPLY = 5  # modify existing files
    DESTRUCTIVE = 6  # delete, overwrite, batch move (via trash only)


# Permission-level metadata
PERMISSION_DEFAULT: dict[PermissionLevel, bool] = {
    PermissionLevel.INSPECT: True,
    PermissionLevel.ANNOTATE: True,
    PermissionLevel.REORGANIZE: False,
    PermissionLevel.GENERATE: False,
    PermissionLevel.APPLY: False,
    PermissionLevel.DESTRUCTIVE: False,
}

PERMISSION_LABELS: dict[PermissionLevel, str] = {
    PermissionLevel.INSPECT: "read/list/search/index/preview/summarize",
    PermissionLevel.ANNOTATE: "write notes/plans/evidence (no source changes)",
    PermissionLevel.REORGANIZE: "mkdir/move/rename within root",
    PermissionLevel.GENERATE: "generate new files/cards/summaries/scripts",
    PermissionLevel.APPLY: "modify existing files",
    PermissionLevel.DESTRUCTIVE: "delete/overwrite/batch move (via trash)",
}


ROOT_RECOVERY_MANIFEST_VERSION = 1
ROOT_RECOVERY_MANIFEST_TYPE = "trainer.workspace_root_recovery"
CHECKPOINT_STORE_VERSION = 1
CHECKPOINT_STORE_TYPE = "trainer.workspace_checkpoints"
CHECKPOINT_STORE_FILENAME = "checkpoints.json"
_SENSITIVE_METADATA_TOKENS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


# ---------------------------------------------------------------------------
# Operation Types
# ---------------------------------------------------------------------------


class OperationType:
    """Canonical operation types for ledger tracking."""

    READ = "read"
    LIST = "list"
    SEARCH = "search"
    INDEX = "index"
    PREVIEW = "preview"
    SUMMARIZE = "summarize"
    ANNOTATE = "annotate"
    MKDIR = "mkdir"
    MOVE = "move"
    RENAME = "rename"
    GENERATE = "generate"
    WRITE = "write"
    MODIFY = "modify"
    DELETE = "delete"
    RESTORE = "restore"


# Map operation types to required permission levels
OPERATION_PERMISSION_MAP: dict[str, PermissionLevel] = {
    OperationType.READ: PermissionLevel.INSPECT,
    OperationType.LIST: PermissionLevel.INSPECT,
    OperationType.SEARCH: PermissionLevel.INSPECT,
    OperationType.INDEX: PermissionLevel.INSPECT,
    OperationType.PREVIEW: PermissionLevel.INSPECT,
    OperationType.SUMMARIZE: PermissionLevel.INSPECT,
    OperationType.ANNOTATE: PermissionLevel.ANNOTATE,
    OperationType.MKDIR: PermissionLevel.REORGANIZE,
    OperationType.MOVE: PermissionLevel.REORGANIZE,
    OperationType.RENAME: PermissionLevel.REORGANIZE,
    OperationType.GENERATE: PermissionLevel.GENERATE,
    OperationType.WRITE: PermissionLevel.APPLY,
    OperationType.MODIFY: PermissionLevel.APPLY,
    OperationType.DELETE: PermissionLevel.DESTRUCTIVE,
    OperationType.RESTORE: PermissionLevel.DESTRUCTIVE,
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class OperationRecord:
    """Single operation entry in the ledger."""

    record_id: str
    operation: str
    path: str
    result: str  # "allowed" | "denied" | "error"
    permission_level: PermissionLevel
    timestamp: str
    actor: str = "agent"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Checkpoint:
    """Workspace checkpoint for rollback capability."""

    checkpoint_id: str
    created_at: str
    description: str
    root_path: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceRootMigrationPlan:
    """A pending, explicit workspace-root switch.

    Preparing a plan never changes the active root or copies workspace files.
    The caller must confirm it after the user has moved or restored the data.
    """

    migration_id: str
    source_root: str
    target_root: str
    prepared_at: str
    target_has_trainer_state: bool
    target_is_empty: bool
    requires_external_file_migration: bool = True


@dataclass(frozen=True)
class WorkspaceRootMigrationResult:
    """Evidence that a root switch completed with write authority reset."""

    migration_id: str
    source_root: str
    target_root: str
    completed_at: str
    permission_reset_to: PermissionLevel


@dataclass(frozen=True)
class WorkspaceRootRecoveryResult:
    """Result of restoring authority metadata onto a verified local root."""

    source_root: str
    restored_root: str
    restored_checkpoint_count: int
    restored_at: str
    permission_reset_to: PermissionLevel


# ---------------------------------------------------------------------------
# Workspace Authority Service
# ---------------------------------------------------------------------------


class WorkspaceAuthority:
    """§7.8-§7.9 Folder sovereignty with permission levels.

    Attributes:
        active_workspace_root: Current workspace root path (local or remote URI)
        permission_level: Current effective permission level
    """

    def __init__(
        self,
        root_path: str | None = None,
        initial_permission: PermissionLevel = PermissionLevel.INSPECT,
        remote_name: str | None = None,
    ) -> None:
        """Initialize workspace authority.

        Args:
            root_path: Initial active workspace root (None = not configured)
            initial_permission: Starting permission level
        """
        self._root: Path | None = self._resolve_workspace_root(root_path) if root_path else None
        self._permission: PermissionLevel = initial_permission
        # Workspace configuration must not change defaults for other workspace instances.
        self._permission_defaults: dict[PermissionLevel, bool] = dict(PERMISSION_DEFAULT)
        self._ledger: list[OperationRecord] = []
        self._checkpoint_counter: int = 0
        self._checkpoints: dict[str, Checkpoint] = {}
        self._pending_root_migrations: dict[str, WorkspaceRootMigrationPlan] = {}
        self._root_migration_history: list[WorkspaceRootMigrationResult] = []
        self._trash_base: str = "trash"
        self._remote_name: str = str(remote_name or "").strip() or ""
        # Host-attested VS Code workspace trust. Missing host signal stays untrusted
        # (fail-closed); only an explicit host attestation may open destructive paths.
        self._workspace_trusted: bool = False
        # One-shot / host-granted escape hatch for remote or untrusted mutations.
        self._explicit_destructive_policy: bool = False
        self._load_persisted_checkpoints()

    # ---------------------------------------------------------------------------
    # Properties
    # ---------------------------------------------------------------------------

    @property
    def active_workspace_root(self) -> str | None:
        """Return the active workspace root as string, or None if not set."""
        return str(self._root) if self._root else None

    @property
    def has_active_workspace_root(self) -> bool:
        """Whether the configured root still exists and is safe to operate on."""
        return bool(self._root and self._root.is_dir())

    @property
    def workspace_root_status(self) -> str:
        """Return ``unconfigured``, ``available``, or ``unavailable``."""
        if self._root is None:
            return "unconfigured"
        return "available" if self.has_active_workspace_root else "unavailable"

    @property
    def permission_level(self) -> PermissionLevel:
        """Return current permission level."""
        return self._permission

    @property
    def root_uri(self) -> str | None:
        """Alias for active_workspace_root (URI form)."""
        return self.active_workspace_root

    @property
    def remote_name(self) -> str:
        """Return the VS Code remote name for this workspace, if any."""
        return self._remote_name

    @property
    def is_remote_workspace(self) -> bool:
        """Whether the current workspace is running under a VS Code remote host."""
        return bool(self._remote_name)

    @property
    def is_workspace_trusted(self) -> bool:
        """Whether the host attested VS Code workspace trust for this root."""
        return bool(self._workspace_trusted)

    @property
    def explicit_destructive_policy(self) -> bool:
        """Whether the host granted an explicit destructive-edit policy."""
        return bool(self._explicit_destructive_policy)

    @property
    def authority_mode(self) -> str:
        """Return current authority mode string."""
        return f"level_{self._permission.name.lower()}"

    @property
    def operation_ledger(self) -> list[OperationRecord]:
        """Return copy of operation ledger."""
        return list(self._ledger)

    @property
    def checkpoint_ids(self) -> list[str]:
        """Return list of checkpoint IDs."""
        return list(self._checkpoints.keys())

    @property
    def root_migration_history(self) -> list[WorkspaceRootMigrationResult]:
        """Return completed root migrations without exposing pending plans."""
        return list(self._root_migration_history)

    # ---------------------------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------------------------

    @staticmethod
    def _resolve_workspace_root(root_path: str | Path) -> Path:
        """Resolve and validate a local directory before treating it as a root."""
        raw_path = str(root_path).strip()
        if not raw_path:
            raise ValueError("Workspace path is required")
        try:
            resolved = Path(raw_path).expanduser().resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Workspace path cannot be resolved: {root_path}") from exc
        if not resolved.exists():
            raise ValueError(f"Workspace path does not exist: {root_path}")
        if not resolved.is_dir():
            raise ValueError(f"Workspace path is not a directory: {root_path}")
        return resolved

    def set_active_workspace(self, root_path: str) -> None:
        """Set the active workspace root.

        Args:
            root_path: Absolute path to workspace root

        Raises:
            ValueError: If path does not exist or is not a directory
        """
        resolved = self._resolve_workspace_root(root_path)
        previous_root = self._root
        root_changed = previous_root is not None and previous_root != resolved
        self._root = resolved
        if root_changed:
            # A root change is a new trust boundary, never a silent privilege carry-over.
            self._permission = PermissionLevel.INSPECT
            self._remote_name = ""
            self._workspace_trusted = False
            self._explicit_destructive_policy = False
            self._checkpoints = {}
            self._checkpoint_counter = 0
            self._pending_root_migrations.clear()
        self._load_persisted_checkpoints()
        self.log_operation(
            "set_active_workspace",
            str(resolved),
            "allowed",
            details={
                "root_path": str(resolved),
                "previous_root": str(previous_root) if previous_root else "",
                "permission_reset_to": PermissionLevel.INSPECT.name if root_changed else "",
                "checkpoints_carried_over": not root_changed,
            },
        )

    def set_permission_level(self, level: PermissionLevel) -> None:
        """Set the current permission level.

        Args:
            level: New permission level
        """
        self._permission = level

    def set_workspace_context(
        self,
        remote_name: str | None = None,
        *,
        workspace_trusted: bool | None = None,
        replace_remote: bool = False,
    ) -> None:
        """Update workspace-host context such as remote identity and trust."""
        if replace_remote or (remote_name is not None and str(remote_name).strip()):
            self._remote_name = str(remote_name or "").strip()
        if workspace_trusted is not None:
            self._workspace_trusted = bool(workspace_trusted)

    def grant_explicit_destructive_policy(self, allowed: bool = True) -> None:
        """Record host/user confirmed destructive intent (organize confirm stamp).

        This flag is informational for trusted local flows. It must never override
        missing workspace trust or remote fail-closed denial.
        """
        self._explicit_destructive_policy = bool(allowed)

    def destructive_mutation_block_reason(self, *, explicit_policy: bool = False) -> str | None:
        """Fail-closed gate for remote/untrusted destructive filesystem edits.

        ``explicit_destructive_policy`` cannot override untrusted or remote
        context. Trusted local Trainer-managed sandboxes may mutate without
        that flag; the flag is only a confirmed-organize stamp, not a bypass.
        """
        _ = explicit_policy  # cannot override trust / remote
        if not self._workspace_trusted:
            return "Untrusted workspace denies destructive edits."
        if self.is_remote_workspace:
            return "Remote workspace denies destructive edits."
        return None

    def grant_permission(self, level: PermissionLevel) -> None:
        """Grant a permission level (convenience method).

        Elevating to REORGANIZE or higher records confirmed-organize intent on
        trusted local workspaces. It does not bypass untrusted/remote denial.
        """
        self.set_permission_level(level)
        if int(level) >= int(PermissionLevel.REORGANIZE):
            self._explicit_destructive_policy = True

    def revoke_permission(self, level: PermissionLevel) -> None:
        """Revoke permission by dropping to the level below.

        If current level is INSPECT, remains unchanged.
        """
        current = int(self._permission)
        new_level = max(1, current - 1)
        self._permission = PermissionLevel(new_level)

    # ---------------------------------------------------------------------------
    # Workspace-root migration and recovery
    # ---------------------------------------------------------------------------

    @staticmethod
    def _redact_recovery_metadata(value: Any) -> Any:
        """Remove credential-like values before serializing recovery state."""
        if isinstance(value, Mapping):
            sanitized: dict[str, Any] = {}
            for key, nested_value in value.items():
                normalized_key = str(key).lower().replace("-", "_")
                if any(token in normalized_key for token in _SENSITIVE_METADATA_TOKENS):
                    sanitized[str(key)] = "[redacted]"
                else:
                    sanitized[str(key)] = WorkspaceAuthority._redact_recovery_metadata(nested_value)
            return sanitized
        if isinstance(value, list):
            return [WorkspaceAuthority._redact_recovery_metadata(item) for item in value]
        if isinstance(value, tuple):
            return [WorkspaceAuthority._redact_recovery_metadata(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    def prepare_root_migration(self, target_root: str | Path) -> WorkspaceRootMigrationPlan:
        """Create a pending root switch without moving data or changing authority.

        File movement is intentionally outside this method: copying or moving an
        entire workspace is a destructive, host-owned operation. The prepared
        plan gives a route or UI enough information to ask for explicit user
        confirmation after backup or restore has happened.
        """
        if not self.has_active_workspace_root or self._root is None:
            raise RuntimeError("An available active workspace root is required before migration.")

        target = self._resolve_workspace_root(target_root)
        if target == self._root:
            raise ValueError("Migration target must differ from the active workspace root.")

        try:
            target_is_empty = next(target.iterdir(), None) is None
        except OSError as exc:
            raise ValueError(f"Workspace migration target cannot be inspected: {target}") from exc

        plan = WorkspaceRootMigrationPlan(
            migration_id=f"workspace-migration-{uuid4().hex[:12]}",
            source_root=str(self._root),
            target_root=str(target),
            prepared_at=datetime.now(UTC).isoformat(),
            target_has_trainer_state=(target / ".trainer").is_dir(),
            target_is_empty=target_is_empty,
        )
        self._pending_root_migrations[plan.migration_id] = plan
        self.log_operation(
            "workspace_root_migration_prepared",
            str(target),
            "allowed",
            details={
                "migration_id": plan.migration_id,
                "source_root": plan.source_root,
                "requires_external_file_migration": True,
            },
        )
        return plan

    def confirm_root_migration(
        self,
        migration_id: str,
        *,
        confirmed: bool = False,
    ) -> WorkspaceRootMigrationResult:
        """Activate a prepared root only after an explicit confirmation.

        Switching roots deliberately drops authority to ``INSPECT`` and clears
        remote-host display context. The caller must rediscover host context and
        explicitly re-authorize any write capabilities for the new root.
        """
        plan = self._pending_root_migrations.get(migration_id)
        if plan is None:
            raise ValueError("Unknown or expired workspace root migration plan.")
        if not confirmed:
            raise PermissionError("Workspace root migration requires explicit confirmation.")
        if self.active_workspace_root != plan.source_root:
            raise RuntimeError("Active workspace root changed after migration was prepared.")

        target = self._resolve_workspace_root(plan.target_root)
        source_checkpoint_count = len(self._checkpoints)
        self._root = target
        self._permission = PermissionLevel.INSPECT
        self._remote_name = ""
        # Source-root checkpoints cannot prove recoverability for a new root.
        self._checkpoints = {}
        self._checkpoint_counter = 0
        self._load_persisted_checkpoints()
        completed_at = datetime.now(UTC).isoformat()
        result = WorkspaceRootMigrationResult(
            migration_id=plan.migration_id,
            source_root=plan.source_root,
            target_root=str(target),
            completed_at=completed_at,
            permission_reset_to=PermissionLevel.INSPECT,
        )
        self._pending_root_migrations.clear()
        self._root_migration_history.append(result)
        self.log_operation(
            "workspace_root_migrated",
            str(target),
            "allowed",
            details={
                "migration_id": result.migration_id,
                "source_root": result.source_root,
                "permission_reset_to": result.permission_reset_to.name,
                "remote_context_cleared": True,
                "source_checkpoint_count": source_checkpoint_count,
                "checkpoints_carried_over": False,
            },
        )
        return result

    def export_root_recovery_manifest(self) -> dict[str, Any]:
        """Return portable, credential-free authority metadata for recovery.

        The manifest is deliberately metadata-only. It describes which root and
        checkpoints to restore after a user-controlled backup or copy operation;
        it never claims that workspace files have been copied successfully.
        """
        if not self.has_active_workspace_root or self._root is None:
            raise RuntimeError("An available active workspace root is required for recovery export.")

        return {
            "manifest_type": ROOT_RECOVERY_MANIFEST_TYPE,
            "manifest_version": ROOT_RECOVERY_MANIFEST_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "source_root": str(self._root),
            "permission_level": self._permission.name,
            "remote_name": self._remote_name,
            "checkpoint_counter": self._checkpoint_counter,
            "checkpoints": [
                {
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "created_at": checkpoint.created_at,
                    "description": checkpoint.description,
                    "metadata": self._redact_recovery_metadata(checkpoint.metadata),
                }
                for checkpoint in self.list_checkpoints()
            ],
            "notes": {
                "workspace_files_included": False,
                "permission_restore_requires_reauthorization": True,
                "remote_context_must_be_revalidated": True,
            },
        }

    def save_root_recovery_manifest(self, destination: str | Path | None = None) -> str:
        """Persist a credential-free recovery manifest inside the active root."""
        if not self.has_active_workspace_root or self._root is None:
            raise RuntimeError("An available active workspace root is required for recovery backup.")

        default_destination = (
            self._root
            / ".trainer"
            / "checkpoints"
            / f"workspace-root-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}.json"
        )
        resolved_destination, is_within_root = self.normalize_and_validate(
            destination or default_destination,
            allow_outside=True,
        )
        if not is_within_root:
            raise PermissionError("Recovery manifest destination must stay inside the active workspace root.")
        if not self.check_permission(OperationType.ANNOTATE, resolved_destination):
            raise PermissionError("Annotate permission is required to save a recovery manifest.")

        resolved_destination.parent.mkdir(parents=True, exist_ok=True)
        resolved_destination.write_text(
            json.dumps(self.export_root_recovery_manifest(), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        self.log_operation(
            "workspace_root_backup",
            str(resolved_destination),
            "allowed",
            details={"manifest_type": ROOT_RECOVERY_MANIFEST_TYPE},
        )
        return str(resolved_destination)

    def restore_root_recovery_manifest(
        self,
        manifest: Mapping[str, Any],
        *,
        target_root: str | Path | None = None,
    ) -> WorkspaceRootRecoveryResult:
        """Restore authority metadata onto an existing root with no privilege carry-over.

        A manifest can be copied or edited outside the service, so recovery
        always resets permissions to ``INSPECT`` and drops remote context. The
        host must revalidate both before a write or remote action is permitted.
        """
        if not isinstance(manifest, Mapping):
            raise ValueError("Workspace recovery manifest must be an object.")
        if manifest.get("manifest_type") != ROOT_RECOVERY_MANIFEST_TYPE:
            raise ValueError("Unsupported workspace recovery manifest type.")
        if manifest.get("manifest_version") != ROOT_RECOVERY_MANIFEST_VERSION:
            raise ValueError("Unsupported workspace recovery manifest version.")

        source_root = str(manifest.get("source_root") or "").strip()
        raw_target = target_root if target_root is not None else source_root
        target = self._resolve_workspace_root(raw_target)
        raw_checkpoints = manifest.get("checkpoints", [])
        if not isinstance(raw_checkpoints, list):
            raise ValueError("Workspace recovery manifest checkpoints must be a list.")

        restored_checkpoints: dict[str, Checkpoint] = {}
        for item in raw_checkpoints:
            if not isinstance(item, Mapping):
                continue
            checkpoint_id = str(item.get("checkpoint_id") or "").strip()
            if not checkpoint_id or checkpoint_id in restored_checkpoints:
                continue
            description = str(item.get("description") or "Workspace recovery checkpoint").strip()
            created_at = str(item.get("created_at") or datetime.now(UTC).isoformat()).strip()
            metadata = item.get("metadata")
            restored_checkpoints[checkpoint_id] = Checkpoint(
                checkpoint_id=checkpoint_id,
                created_at=created_at,
                description=description or "Workspace recovery checkpoint",
                root_path=str(target),
                metadata=(
                    self._redact_recovery_metadata(metadata)
                    if isinstance(metadata, Mapping)
                    else {}
                ),
            )

        self._root = target
        self._permission = PermissionLevel.INSPECT
        self._remote_name = ""
        self._workspace_trusted = False
        self._explicit_destructive_policy = False
        self._checkpoints = restored_checkpoints
        self._pending_root_migrations.clear()
        configured_counter = manifest.get("checkpoint_counter", 0)
        try:
            normalized_counter = max(0, int(configured_counter))
        except (TypeError, ValueError):
            normalized_counter = 0
        recovered_sequence = 0
        for checkpoint_id in restored_checkpoints:
            if checkpoint_id.startswith("cp-") and checkpoint_id[3:].isdigit():
                recovered_sequence = max(recovered_sequence, int(checkpoint_id[3:]))
        self._checkpoint_counter = max(
            normalized_counter,
            recovered_sequence,
            len(restored_checkpoints),
        )
        self._persist_checkpoints()
        restored_at = datetime.now(UTC).isoformat()
        result = WorkspaceRootRecoveryResult(
            source_root=source_root,
            restored_root=str(target),
            restored_checkpoint_count=len(restored_checkpoints),
            restored_at=restored_at,
            permission_reset_to=PermissionLevel.INSPECT,
        )
        self.log_operation(
            "workspace_root_recovered",
            str(target),
            "allowed",
            details={
                "source_root": source_root,
                "restored_checkpoint_count": result.restored_checkpoint_count,
                "permission_reset_to": result.permission_reset_to.name,
                "remote_context_cleared": True,
            },
        )
        return result

    def _checkpoint_store_path(self) -> Path | None:
        if self._root is None or not self.has_active_workspace_root:
            return None
        return self._root / ".trainer" / "checkpoints" / CHECKPOINT_STORE_FILENAME

    def _load_persisted_checkpoints(self) -> None:
        store_path = self._checkpoint_store_path()
        if store_path is None or not store_path.exists():
            self._checkpoints = {}
            self._checkpoint_counter = 0
            return

        try:
            payload = json.loads(store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        if not isinstance(payload, dict):
            return
        if payload.get("store_type") != CHECKPOINT_STORE_TYPE:
            return
        if payload.get("store_version") != CHECKPOINT_STORE_VERSION:
            return

        stored_root = str(payload.get("root_path") or "").strip()
        if stored_root and self._root is not None and stored_root != str(self._root):
            return

        raw_checkpoints = payload.get("checkpoints", [])
        if not isinstance(raw_checkpoints, list):
            return

        restored_checkpoints: dict[str, Checkpoint] = {}
        for item in raw_checkpoints:
            if not isinstance(item, Mapping):
                continue
            checkpoint_id = str(item.get("checkpoint_id") or "").strip()
            if not checkpoint_id or checkpoint_id in restored_checkpoints:
                continue
            description = str(item.get("description") or "Workspace checkpoint").strip()
            created_at = str(item.get("created_at") or datetime.now(UTC).isoformat()).strip()
            metadata = item.get("metadata")
            restored_checkpoints[checkpoint_id] = Checkpoint(
                checkpoint_id=checkpoint_id,
                created_at=created_at,
                description=description or "Workspace checkpoint",
                root_path=str(self._root),
                metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
            )

        configured_counter = payload.get("checkpoint_counter", 0)
        try:
            normalized_counter = max(0, int(configured_counter))
        except (TypeError, ValueError):
            normalized_counter = 0
        recovered_sequence = 0
        for checkpoint_id in restored_checkpoints:
            if checkpoint_id.startswith("cp-") and checkpoint_id[3:].isdigit():
                recovered_sequence = max(recovered_sequence, int(checkpoint_id[3:]))

        self._checkpoints = restored_checkpoints
        self._checkpoint_counter = max(
            normalized_counter,
            recovered_sequence,
            len(restored_checkpoints),
        )

    def _persist_checkpoints(self) -> None:
        store_path = self._checkpoint_store_path()
        if store_path is None:
            return

        payload = {
            "store_type": CHECKPOINT_STORE_TYPE,
            "store_version": CHECKPOINT_STORE_VERSION,
            "root_path": str(self._root),
            "checkpoint_counter": self._checkpoint_counter,
            "checkpoints": [
                {
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "created_at": checkpoint.created_at,
                    "description": checkpoint.description,
                    "root_path": checkpoint.root_path,
                    "metadata": checkpoint.metadata,
                }
                for checkpoint in self.list_checkpoints()
            ],
        }

        store_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=store_path.parent,
                delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=True, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            temp_path.replace(store_path)
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    # ---------------------------------------------------------------------------
    # Path Normalization & Boundary Enforcement
    # ---------------------------------------------------------------------------

    def _normalize_path(self, path: str | Path) -> Path:
        """Normalize a path (resolve symlinks, handle relative paths).

        Args:
            path: Input path (absolute or relative)

        Returns:
            Resolved absolute Path
        """
        p = Path(path)
        if not p.is_absolute() and self._root:
            p = self._root / p
        return p.resolve(strict=False)

    def _is_within_root(self, path: Path) -> bool:
        """Check if normalized path is within the active workspace root.

        Args:
            path: Normalized absolute path

        Returns:
            True if path is at or under root
        """
        if not self._root:
            return False
        try:
            path.relative_to(self._root)
            return True
        except ValueError:
            return False

    def normalize_and_validate(
        self, path: str | Path, allow_outside: bool = False
    ) -> tuple[Path, bool]:
        """Normalize path and validate it's within workspace root.

        Args:
            path: Input path
            allow_outside: If True, returns (normalized, False) instead of raising

        Returns:
            (normalized_path, is_within_root)

        Raises:
            PermissionError: If path escapes root and allow_outside=False
        """
        normalized = self._normalize_path(path)
        is_inside = self._is_within_root(normalized)

        if not is_inside and not allow_outside:
            raise PermissionError(
                f"Path escape attempt: {path} resolves to {normalized} "
                f"which is outside workspace root {self._root}"
            )
        return normalized, is_inside

    # ---------------------------------------------------------------------------
    # Permission Checking
    # ---------------------------------------------------------------------------

    def check_permission(
        self, operation: str | OperationType, path: str | Path
    ) -> bool:
        """Check if operation is allowed on path with current permission level.

        Args:
            operation: Operation type (string or OperationType)
            path: Target path

        Returns:
            True if operation is permitted, False otherwise
        """
        op_str = str(operation).strip().lower()
        if op_str not in OPERATION_PERMISSION_MAP:
            self.log_operation(
                op_str or "unknown",
                str(path),
                "denied",
                details={"reason": "Unknown workspace operation is denied by default."},
            )
            return False

        if not self.has_active_workspace_root:
            self.log_operation(
                op_str,
                str(path),
                "denied",
                details={
                    "reason": "Active workspace root is not available.",
                    "workspaceRootStatus": self.workspace_root_status,
                },
            )
            return False

        required_level = OPERATION_PERMISSION_MAP[op_str]

        # Check path boundary
        _, is_within = self.normalize_and_validate(path, allow_outside=True)
        if not is_within:
            self.log_operation(
                op_str,
                str(path),
                "denied",
                details={
                    "reason": "Path is outside the active workspace root.",
                    "activeWorkspaceRoot": str(self._root),
                },
            )
            return False

        # Remote / untrusted workspaces: no REORGANIZE+ edits (policy cannot override).
        if int(required_level) >= int(PermissionLevel.REORGANIZE):
            block_reason = self.destructive_mutation_block_reason()
            if block_reason:
                self.log_operation(
                    op_str,
                    str(path),
                    "denied",
                    details={
                        "reason": block_reason,
                        "remoteName": self._remote_name,
                        "workspaceTrusted": self._workspace_trusted,
                        "explicitDestructivePolicy": self._explicit_destructive_policy,
                    },
                )
                return False

        # Check permission level
        allowed = int(self._permission) >= int(required_level)
        self.log_operation(
            op_str,
            str(path),
            "allowed" if allowed else "denied",
            details=(
                None
                if allowed
                else {
                    "reason": (
                        f"{op_str} requires {required_level.name} permission but current level is "
                        f"{self._permission.name}."
                    ),
                    "requiredPermissionLevel": required_level.name,
                    "currentPermissionLevel": self._permission.name,
                }
            ),
        )
        return allowed

    def can_perform(self, operation: str | OperationType, path: str | Path) -> bool:
        """Convenience method: check if current authority can perform operation."""
        return self.check_permission(operation, path)

    def requires_approval(self, operation: str | OperationType) -> bool:
        """Check if operation requires explicit user approval.

        Destructive operations always require approval.
        """
        op_str = str(operation).strip().lower()
        # Unknown operations must never be treated as pre-approved.
        return op_str not in OPERATION_PERMISSION_MAP or op_str in {"delete", "restore"}

    # ---------------------------------------------------------------------------
    # Operation Ledger
    # ---------------------------------------------------------------------------

    def log_operation(
        self,
        operation: str,
        path: str,
        result: str,
        actor: str = "agent",
        details: dict[str, Any] | None = None,
    ) -> OperationRecord:
        """Record an operation to the ledger.

        Args:
            operation: Operation type string
            path: Target path
            result: "allowed" | "denied" | "error"
            actor: Actor performing the operation
            details: Additional metadata

        Returns:
            Created OperationRecord
        """
        record = OperationRecord(
            record_id=f"op-{uuid4().hex[:12]}",
            operation=operation,
            path=path,
            result=result,
            permission_level=self._permission,
            timestamp=datetime.now(UTC).isoformat(),
            actor=actor,
            details=dict(details or {}),
        )
        self._ledger.append(record)
        return record

    def get_ledger(
        self,
        operation: str | None = None,
        path_prefix: str | None = None,
        limit: int = 100,
    ) -> list[OperationRecord]:
        """Query operation ledger.

        Args:
            operation: Filter by operation type
            path_prefix: Filter by path prefix
            limit: Maximum records to return

        Returns:
            Matching OperationRecord entries
        """
        results = self._ledger

        if operation:
            results = [r for r in results if r.operation == operation]
        if path_prefix:
            results = [r for r in results if r.path.startswith(path_prefix)]

        return results[-limit:]

    def clear_ledger(self) -> None:
        """Clear operation ledger (for testing)."""
        self._ledger.clear()

    # ---------------------------------------------------------------------------
    # Trash Operations
    # ---------------------------------------------------------------------------

    def trash_path(self, path: str | Path) -> str:
        """Move a file or directory to trash instead of direct deletion.

        Args:
            path: Path to trash (must be within workspace root)

        Returns:
            New trash path

        Raises:
            PermissionError: If path not within root or permission denied
        """
        if self._root is None or not self.has_active_workspace_root:
            raise PermissionError("No active workspace root configured")

        normalized, is_within = self.normalize_and_validate(path)
        if not is_within:
            raise PermissionError(f"Cannot trash path outside workspace: {path}")

        if not self.check_permission(OperationType.DELETE, path):
            raise PermissionError(
                f"Delete permission denied for {path} (current level: {self._permission.name})"
            )

        # Create trash directory structure: root/trash/YYYYMMDD-XXXXXXXX/
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        unique_id = uuid4().hex[:8]
        trash_subdir = self._root / self._trash_base / f"{timestamp}-{unique_id}"

        # Ensure parent exists
        trash_subdir.mkdir(parents=True, exist_ok=True)

        # Preserve the original relative path inside trash for better recovery/auditability.
        relative_target = normalized.relative_to(self._root)
        trashed_path = trash_subdir / relative_target
        if len(str(trashed_path)) >= 240:
            suffix = "".join(Path(relative_target.name).suffixes)
            stem = Path(relative_target.name).stem or normalized.stem or normalized.name or "trashed-entry"
            compact_stem = stem[:48].rstrip(" .-_") or "trashed-entry"
            compact_hash = sha1(relative_target.as_posix().encode("utf-8")).hexdigest()[:10]
            compact_name = f"{compact_stem}-{compact_hash}{suffix}"
            trashed_path = trash_subdir / compact_name
        trashed_path.parent.mkdir(parents=True, exist_ok=True)
        counter = 1
        while trashed_path.exists():
            stem = trashed_path.stem
            suffix = trashed_path.suffix
            trashed_path = trashed_path.with_name(f"{stem}_{counter}{suffix}")
            counter += 1

        # Move to trash
        normalized.rename(trashed_path)

        self.log_operation(
            OperationType.DELETE,
            str(path),
            "allowed",
            details={
                "trashed_path": str(trashed_path),
                "original_relative_path": relative_target.as_posix(),
            },
        )

        return str(trashed_path)

    def restore_from_trash(self, path: str | Path, restore_path: str | Path | None = None) -> str:
        """Restore a trashed file or directory back into the active workspace."""
        if self._root is None or not self.has_active_workspace_root:
            raise PermissionError("No active workspace root configured")

        normalized, is_within = self.normalize_and_validate(path)
        if not is_within:
            raise PermissionError(f"Cannot restore path outside workspace: {path}")

        trash_root = self._root / self._trash_base
        try:
            relative_to_trash = normalized.relative_to(trash_root)
        except ValueError:
            raise PermissionError(f"Cannot restore path outside workspace trash: {path}") from None

        if not self.check_permission(OperationType.RESTORE, path):
            raise PermissionError(
                f"Restore permission denied for {path} (current level: {self._permission.name})"
            )

        if restore_path is None or not str(restore_path).strip():
            trash_parts = relative_to_trash.parts
            if len(trash_parts) < 2:
                raise ValueError(f"Cannot infer restore destination from trashed path: {path}")
            restored_relative = Path(*trash_parts[1:])
            destination = self._root / restored_relative
        else:
            destination, _ = self.normalize_and_validate(restore_path)
            restored_relative = destination.relative_to(self._root)

        try:
            destination.relative_to(trash_root)
        except ValueError:
            pass
        else:
            raise ValueError("Restore destination cannot remain inside workspace trash")

        if destination.exists():
            raise FileExistsError(f"Restore destination already exists: {destination}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        normalized.rename(destination)

        self.log_operation(
            OperationType.RESTORE,
            str(path),
            "allowed",
            details={
                "restored_path": str(destination),
                "source_trashed_path": str(normalized),
                "original_relative_path": restored_relative.as_posix(),
            },
        )

        return str(destination)

    def create_trash_checkpoint(
        self,
        path: str | Path,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Checkpoint:
        if self._root is None or not self.has_active_workspace_root:
            raise PermissionError("No active workspace root configured")
        normalized, is_within = self.normalize_and_validate(path)
        if not is_within:
            raise PermissionError(f"Cannot checkpoint path outside workspace: {path}")
        checkpoint = self.create_checkpoint(
            description or f"Checkpoint before trashing {normalized.name}",
            {
                **dict(metadata or {}),
                "path": str(normalized),
                "trash_root": self.trash_root,
            },
        )
        self.log_operation(
            "checkpoint",
            str(normalized),
            "allowed",
            details={"checkpoint_id": checkpoint.checkpoint_id},
        )
        return checkpoint

    @property
    def trash_root(self) -> str | None:
        """Return trash root directory path."""
        if self._root is None or not self.has_active_workspace_root:
            return None
        return str(self._root / self._trash_base)

    # ---------------------------------------------------------------------------
    # Checkpoint Management
    # ---------------------------------------------------------------------------

    def create_checkpoint(
        self,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> Checkpoint:
        """Create a checkpoint for potential rollback.

        Args:
            description: Checkpoint description
            metadata: Additional metadata

        Returns:
            Created Checkpoint

        Raises:
            RuntimeError: If no workspace root is configured
        """
        if self._root is None or not self.has_active_workspace_root:
            raise RuntimeError("No active workspace root configured")

        self._checkpoint_counter += 1
        checkpoint = Checkpoint(
            checkpoint_id=f"cp-{self._checkpoint_counter:04d}",
            created_at=datetime.now(UTC).isoformat(),
            description=description,
            root_path=str(self._root),
            metadata=dict(metadata or {}),
        )
        self._checkpoints[checkpoint.checkpoint_id] = checkpoint
        self._persist_checkpoints()
        return checkpoint

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Retrieve a checkpoint by ID."""
        return self._checkpoints.get(checkpoint_id)

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint.

        Returns:
            True if checkpoint was deleted, False if not found
        """
        if checkpoint_id in self._checkpoints:
            del self._checkpoints[checkpoint_id]
            self._persist_checkpoints()
            return True
        return False

    def list_checkpoints(self) -> list[Checkpoint]:
        """List all checkpoints, newest first."""
        return sorted(
            self._checkpoints.values(),
            key=lambda c: c.created_at,
            reverse=True,
        )

    # ---------------------------------------------------------------------------
    # Utility
    # ---------------------------------------------------------------------------

    def get_allowed_operations(self) -> list[str]:
        """Return list of operation names allowed at current permission level."""
        if not self.has_active_workspace_root:
            return []
        allowed = []
        for op, level in OPERATION_PERMISSION_MAP.items():
            if int(self._permission) >= int(level):
                # op is already a string key from the dict
                allowed.append(op if isinstance(op, str) else str(op))
        return allowed

    def get_permission_label(self) -> str:
        """Get human-readable description of current permission level."""
        return PERMISSION_LABELS.get(self._permission, "unknown")

    def is_default_enabled(self, level: PermissionLevel) -> bool:
        """Check if a permission level is enabled by default."""
        return self._permission_defaults.get(level, False)

    def _derive_next_safe_action(self, allowed_operations: list[str]) -> str:
        """Return the next safe action in plain English for the current boundary."""
        if not self.has_active_workspace_root:
            return "Open or connect a workspace root first so I can read the boundary and choose a next step."

        def has_any(*operations: str) -> bool:
            return any(operation in allowed_operations for operation in operations)

        has_inspect_only = not has_any(
            "annotate",
            "mkdir",
            "move",
            "rename",
            "generate",
            "write",
            "modify",
            "delete",
            "restore",
        )
        if has_inspect_only or self._permission == PermissionLevel.INSPECT:
            return "Start by reading, searching, and previewing the key material, then pick the first verifiable task."

        has_annotate_only = has_any("annotate") and not has_any(
            "mkdir",
            "move",
            "rename",
            "generate",
            "write",
            "modify",
            "delete",
            "restore",
        )
        if has_annotate_only or self._permission == PermissionLevel.ANNOTATE:
            return "Write the judgment down as notes, a plan, or evidence first, then decide whether source code should move."

        if has_any("delete", "restore") or self._permission == PermissionLevel.DESTRUCTIVE:
            return "Move risky content into trash or a checkpoint first, then make the smallest change in this round."

        if has_any("write", "modify") or self._permission == PermissionLevel.APPLY:
            return "Start with the thinnest edit, then verify immediately that it actually holds."

        if has_any("generate") or self._permission == PermissionLevel.GENERATE:
            return "Generate the smallest useful card, summary, or script first, then check whether it matches the current task."

        if has_any("mkdir", "move", "rename") or self._permission == PermissionLevel.REORGANIZE:
            return "First reorganize the workspace shape, then place the current task into a clearer folder."

        return "Confirm the boundary first, then make the smallest verifiable move."

    def _normalize_mounted_source_entry(self, entry: Any) -> str:
        """Return a compact human-readable label for one mounted source entry."""
        if isinstance(entry, str):
            return entry.strip()
        if not isinstance(entry, dict):
            return ""

        def first_text(*keys: str) -> str:
            for key in keys:
                value = entry.get(key)
                if isinstance(value, str):
                    cleaned = value.strip()
                    if cleaned:
                        return cleaned
            return ""

        label = first_text("label", "name", "title", "id", "mount_id")
        target = first_text(
            "remoteUri",
            "remote_uri",
            "uri",
            "mountPoint",
            "mount_point",
            "localMountPoint",
            "local_mount_point",
            "path",
            "source",
        )
        if label and target:
            return f"{label} -> {target}"
        return label or target

    def _extract_mounted_sources(self, config: dict[str, Any] | None) -> list[str]:
        """Extract mounted source labels from workspace.json configuration."""
        if not config:
            return []

        raw_sources_candidates = []
        if config.get("mountedSources") is not None:
            raw_sources_candidates.append(config.get("mountedSources"))
        if config.get("mountPoints") is not None:
            raw_sources_candidates.append(config.get("mountPoints"))

        entries: list[Any] = []
        for raw_sources in raw_sources_candidates:
            if isinstance(raw_sources, list):
                entries.extend(raw_sources)
                continue
            if isinstance(raw_sources, dict):
                if any(
                    key in raw_sources
                    for key in (
                        "label",
                        "name",
                        "title",
                        "id",
                        "mount_id",
                        "remoteUri",
                        "remote_uri",
                        "mountPoint",
                        "mount_point",
                        "localMountPoint",
                        "local_mount_point",
                        "path",
                        "source",
                    )
                ):
                    entries.append(raw_sources)
                    continue
                nested = raw_sources.get("items") or raw_sources.get("entries") or raw_sources.get("sources")
                if isinstance(nested, list):
                    entries.extend(nested)
                else:
                    entries.extend(raw_sources.values())
                continue
            entries.append(raw_sources)

        seen: set[str] = set()
        mounted_sources: list[str] = []
        for entry in entries:
            label = self._normalize_mounted_source_entry(entry)
            normalized = label.strip()
            if not normalized:
                continue
            dedupe_key = normalized.lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            mounted_sources.append(normalized)
        return mounted_sources

    def summary_model(self) -> WorkspaceAuthoritySummary:
        """Return a typed authority summary for API consumers."""
        allowed_operations = self.get_allowed_operations()
        root = self.active_workspace_root or ""
        root_available = self.has_active_workspace_root
        source = "workspace_authority_service"
        permission_label = self.get_permission_label()
        permission_detail = self.authority_mode
        root_detail_parts = [
            f"root_uri: {self.root_uri}" if self.root_uri and self.root_uri != root else "",
            f"source: {source}" if source else "",
            f"remote: {self._remote_name}" if self._remote_name else "",
            f"root_status: {self.workspace_root_status}" if not root_available else "",
        ]
        source_detail_parts = [
            "authority_source: workspace_authority_service",
            f"remote: {self._remote_name}" if self._remote_name else "",
            f"mode: {self.authority_mode}" if self.authority_mode else "",
        ]
        trash_root = self.trash_root or ""
        mounted_sources = self._extract_mounted_sources(self.load_workspace_config())
        summary_parts = [root, permission_label, source]
        if self._remote_name:
            summary_parts.append(f"remote: {self._remote_name}")
        return WorkspaceAuthoritySummary(
            has_workspace_root=root_available,
            active_workspace_root=root,
            root_uri=self.root_uri or "",
            root_detail=" | ".join(part for part in root_detail_parts if part),
            source=source,
            source_detail=" | ".join(part for part in source_detail_parts if part),
            authority_source="workspace_authority_service",
            remote_name=self.remote_name,
            is_remote_workspace=self.is_remote_workspace,
            permission_level=self._permission.name,
            permission_label=permission_label,
            permission_detail=permission_detail,
            authority_mode=self.authority_mode,
            authority_scope="project",
            resource_write_allowed=False,
            resource_write_evidence={
                "operation": "write",
                "scope": "project",
                "allowed": False,
                "reason": "Project source writes require an explicit host-side operation grant.",
            },
            allowed_operations=allowed_operations,
            allowed_operations_text=" / ".join(allowed_operations[:6]),
            mounted_sources=mounted_sources,
            ledger_entry_count=len(self._ledger),
            checkpoint_count=len(self._checkpoints),
            counts_text=f"{len(self._ledger)} / {len(self._checkpoints)}",
            trash_root=trash_root,
            trash_detail=f"trash: {trash_root}" if trash_root else "",
            next_safe_action=self._derive_next_safe_action(allowed_operations),
            summary_text=" | ".join(part for part in summary_parts if part),
        )

    def summary(self) -> dict[str, Any]:
        """Return authority summary for debugging/API."""
        return self.summary_model().model_dump(mode="json")

    # ---------------------------------------------------------------------------
    # Workspace Policy File Parsing — §7.8, §7.11
    # ---------------------------------------------------------------------------

    def load_workspace_config(self, path: str | Path | None = None) -> dict[str, Any]:
        """Load and parse workspace.json from the workspace root.

        Reads workspace.json for Trainer-specific configuration including:
        - trainerVersion: minimum Trainer version
        - agentPolicy: path to AGENT_POLICY.md (default: AGENT_POLICY.md)
        - permissionDefaults: override default permission levels
        - ignorePatterns: paths to exclude from agent operations
        - mountedSources / mountPoints: remote mount configurations

        Args:
            path: Path to workspace.json (defaults to <root>/workspace.json)

        Returns:
            Parsed workspace config dict, or empty dict if not found
        """
        if self._root is None or not self.has_active_workspace_root:
            return {}

        config_path = self._normalize_path(path or self._root / "workspace.json")
        if not self._is_within_root(config_path):
            return {}

        if not config_path.exists():
            return {}

        try:
            with open(config_path, encoding="utf-8") as f:
                raw = f.read()
            return dict(json.loads(raw)) if raw.strip() else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def load_agent_policy(self, policy_path: str | Path | None = None) -> str:
        """Load AGENT_POLICY.md from the workspace root.

        Returns the raw markdown content of the agent policy file, which
        defines the agent's operational boundaries, coaching principles,
        and workspace-specific rules.

        Args:
            policy_path: Explicit path to policy file (defaults to <root>/AGENT_POLICY.md)

        Returns:
            Raw markdown content, or empty string if not found
        """
        if self._root is None or not self.has_active_workspace_root:
            return ""

        resolved_path = self._normalize_path(policy_path or self._root / "AGENT_POLICY.md")
        if not self._is_within_root(resolved_path):
            return ""

        if not resolved_path.exists():
            return ""

        try:
            with open(resolved_path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def apply_workspace_config(self, config: dict[str, Any] | None = None) -> None:
        """Apply workspace.json configuration to this authority instance.

        Supports the following config keys:
        - permissionDefaults: dict mapping PermissionLevel names to enabled booleans
        - trainerVersion: minimum version string (checked for compatibility)

        Args:
            config: Workspace config dict (loads from root if not provided)
        """
        if config is None:
            config = self.load_workspace_config()

        if not config:
            return

        # Apply permission defaults override if present
        perm_defaults = config.get("permissionDefaults")
        if perm_defaults and isinstance(perm_defaults, dict):
            for level_name, enabled in perm_defaults.items():
                if not isinstance(level_name, str):
                    continue
                try:
                    level = PermissionLevel[level_name.upper()]
                    self._permission_defaults[level] = bool(enabled)
                except KeyError:
                    pass  # Skip unknown permission levels

    def load_trainerignore(self) -> list[str]:
        """Load .trainerignore patterns from workspace root.

        Returns a list of glob patterns (one per line) that should be
        excluded from agent operations, similar to .gitignore semantics.

        Returns:
            List of ignore patterns, or empty list if not found
        """
        if self._root is None or not self.has_active_workspace_root:
            return []

        ignore_file = self._normalize_path(self._root / ".trainerignore")
        if not self._is_within_root(ignore_file) or not ignore_file.exists() or not ignore_file.is_file():
            return []

        try:
            with open(ignore_file, encoding="utf-8") as f:
                patterns = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            return patterns
        except OSError:
            return []

    def matches_ignore(self, path: str | Path) -> bool:
        """Check if a path matches any .trainerignore pattern.

        Args:
            path: Path to check against ignore patterns

        Returns:
            True if path should be ignored
        """
        import fnmatch

        patterns = self.load_trainerignore()
        if not patterns:
            return False

        path_str = str(Path(path).as_posix())
        for pattern in patterns:
            # Normalize: remove trailing slash for directory patterns
            normalized_pattern = pattern.rstrip("/")
            if fnmatch.fnmatch(path_str, normalized_pattern):
                return True
            # Directory pattern: "node_modules/" should match "node_modules/react/..."
            if pattern.endswith("/"):
                if path_str.startswith(normalized_pattern + "/"):
                    return True
            # Also check if pattern matches any parent directory
            if "/" in path_str:
                for parent in Path(path_str).parents:
                    parent_str = parent.as_posix()
                    if fnmatch.fnmatch(parent_str, normalized_pattern):
                        return True
                    if pattern.endswith("/") and parent_str.startswith(normalized_pattern + "/"):
                        return True
        return False
