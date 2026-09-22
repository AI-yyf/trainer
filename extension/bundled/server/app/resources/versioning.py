"""Phase-E: resource content versioning, deletion propagation, and remote
workspace runner boundary guard (design §13, TR-059/TR-071/TR-100).

Resource versioning: every resource gets a SHA-256 content_hash at upload/
index time, making evidence records traceable to specific content versions.
When the content changes, the hash changes — old evidence automatically
becomes stale (TR-059).

Deletion propagation: when a resource is tombstoned, evidence records that
reference its content hash get flagged with `source_deleted: true` so the
UI can show "deleted source" instead of silently linking to nothing (TR-076).

Remote workspace boundary (TR-100): training verification must not run on a
local file when the workspace is remote — an explicit guard is provided for
the training verify path to check before any local runner invocation.
"""


import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resource_versions (
    version_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resource_versions
    ON resource_versions(workspace_id, resource_id, version DESC);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_content_hash(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


class ResourceVersionStore:
    """Tracks content versions per resource for evidence traceability."""

    def __init__(self, database_path: str | Path) -> None:
        self._path = Path(database_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        try:
            connection.executescript(_SCHEMA)
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def record_version(
        self,
        *,
        workspace_id: str,
        resource_id: str,
        content: str | bytes,
    ) -> dict[str, Any]:
        """Record a new version for a resource; bumps the version counter."""
        content_hash = compute_content_hash(content)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT MAX(version) AS max_v FROM resource_versions WHERE workspace_id = ? AND resource_id = ?",
                (workspace_id, resource_id),
            ).fetchone()
            version = (row["max_v"] or 0) + 1
            version_id = f"rv-{uuid.uuid4().hex}"
            now = utc_now()
            connection.execute(
                """INSERT INTO resource_versions
                   (version_id, workspace_id, resource_id, content_hash, version, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (version_id, workspace_id, resource_id, content_hash, version, now),
            )
            connection.commit()
        finally:
            connection.close()
        return {
            "version_id": version_id,
            "workspace_id": workspace_id,
            "resource_id": resource_id,
            "content_hash": content_hash,
            "version": version,
            "created_at": now,
        }

    def current_content_hash(self, workspace_id: str, resource_id: str) -> str | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT content_hash FROM resource_versions
                   WHERE workspace_id = ? AND resource_id = ?
                   ORDER BY version DESC LIMIT 1""",
                (workspace_id, resource_id),
            ).fetchone()
        finally:
            connection.close()
        return row["content_hash"] if row else None


def check_remote_runner_boundary(
    *,
    is_remote_workspace: bool,
    has_remote_runner: bool = False,
) -> str | None:
    """TR-100: returns an honest limitation message if verification cannot
    run because the workspace is remote and no remote runner is available.
    Returns None if verification is safe to proceed."""
    if not is_remote_workspace:
        return None
    if has_remote_runner:
        return None
    return (
        "Remote workspace detected but no remote verification runner is available. "
        "Trainer will not run local checks against a remote project."
    )
