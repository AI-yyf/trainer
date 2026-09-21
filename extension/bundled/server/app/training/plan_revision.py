
"""
Phase-D: plan proposal versioning with optimistic locking (design §9).

Plans gain a monotonically increasing revision counter. Every persisted
mutation bumps the revision. Multi-window conflict detection: a save that
carries a stale expected_revision is rejected with a conflict marker
instead of silently overwriting the other window's changes.

Proposal lifecycle: draft → confirmed → persisted (the plan itself).
Only confirmed proposals mutate the live plan; drafts live in a separate
table and are never merged into the learning_plan silently.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_revisions (
    revision_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT 'learner'
);
CREATE INDEX IF NOT EXISTS idx_plan_revisions
    ON plan_revisions(workspace_id, plan_id, revision);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlanRevisionConflict(Exception):
    """Raised when the expected revision does not match the stored revision."""

    def __init__(self, workspace_id: str, plan_id: str, expected: int, actual: int) -> None:
        super().__init__(
            f"Plan revision conflict for workspace={workspace_id} plan={plan_id}: "
            f"expected revision {expected}, actual revision {actual}"
        )
        self.workspace_id = workspace_id
        self.plan_id = plan_id
        self.expected_revision = expected
        self.actual_revision = actual


class PlanRevisionStore:
    """Revision-tracked plan persistence with optimistic locking."""

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

    def current_revision(self, workspace_id: str, plan_id: str) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT MAX(revision) AS rev FROM plan_revisions WHERE workspace_id = ? AND plan_id = ?",
                (workspace_id, plan_id),
            ).fetchone()
            return (row["rev"] if row and row["rev"] is not None else 0)
        finally:
            connection.close()

    def save_with_revision(
        self,
        *,
        workspace_id: str,
        plan_id: str,
        payload: dict[str, Any],
        expected_revision: int | None = None,
        created_by: str = "learner",
    ) -> dict[str, Any]:
        """Persist a plan mutation with optimistic locking.

        Returns the new revision info on success.
        Raises PlanRevisionConflict on a stale expected_revision.
        """
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self.current_revision(workspace_id, plan_id)
            new_revision = current + 1

            if expected_revision is not None and expected_revision != current:
                connection.rollback()
                raise PlanRevisionConflict(workspace_id, plan_id, expected_revision, current)

            revision_id = f"rev-{uuid.uuid4().hex}"
            now = utc_now()
            connection.execute(
                """INSERT INTO plan_revisions
                   (revision_id, workspace_id, plan_id, revision, payload, created_at, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (revision_id, workspace_id, plan_id, new_revision,
                 json.dumps(payload, ensure_ascii=False), now, created_by),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return {
            "revision_id": revision_id,
            "revision": new_revision,
            "workspace_id": workspace_id,
            "plan_id": plan_id,
        }

    def get_latest_payload(self, workspace_id: str, plan_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT payload FROM plan_revisions
                   WHERE workspace_id = ? AND plan_id = ?
                   ORDER BY revision DESC LIMIT 1""",
                (workspace_id, plan_id),
            ).fetchone()
        finally:
            connection.close()
        return json.loads(row["payload"]) if row else None
