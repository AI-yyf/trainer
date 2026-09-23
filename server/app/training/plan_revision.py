
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
from typing import Any, Callable, cast

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


class PlanRevisionPreconditionRequired(Exception):
    """Raised when a formal save omits its optimistic-lock base revision."""

    def __init__(self, workspace_id: str, plan_id: str, actual: int) -> None:
        super().__init__(
            f"Plan revision is required for workspace={workspace_id} plan={plan_id}; "
            f"current revision is {actual}"
        )
        self.workspace_id = workspace_id
        self.plan_id = plan_id
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
        allow_legacy: bool = True,
    ) -> dict[str, Any]:
        """Persist a plan mutation with optimistic locking.

        Returns the new revision info on success.
        Raises PlanRevisionConflict on a stale expected_revision.
        """
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            # Read the head revision on the SAME connection that holds the
            # write lock; a second connection here would self-deadlock.
            row = connection.execute(
                "SELECT MAX(revision) AS rev FROM plan_revisions WHERE workspace_id = ? AND plan_id = ?",
                (workspace_id, plan_id),
            ).fetchone()
            current = row["rev"] if row and row["rev"] is not None else 0
            new_revision = current + 1

            if expected_revision is None and not allow_legacy and current > 0:
                connection.rollback()
                raise PlanRevisionPreconditionRequired(workspace_id, plan_id, current)
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


def save_plan_checked(
    repository: Any,
    workspace_id: str,
    plan: Any,
    *,
    expected_revision: int,
    allow_legacy: bool = False,
) -> dict[str, Any]:
    """Persist a plan under optimistic locking, raising on conflict.

    Thin wrapper over TrainerRepository.save_plan_with_revision that turns a
    rejected save into PlanRevisionConflict carrying the current head
    revision, so callers can tell the other window exactly what it lost to.
    """
    saved = repository.save_plan_with_revision(
        workspace_id,
        plan,
        expected_revision=expected_revision,
        allow_legacy=allow_legacy,
    )
    if saved is None:
        current = repository.get_plan_revision(workspace_id, plan.id)
        raise PlanRevisionConflict(workspace_id, plan.id, expected_revision, current)
    return saved


def save_plan_advancing_revision(
    repository: Any,
    workspace_id: str,
    plan: Any,
    *,
    max_attempts: int = 4,
) -> int | None:
    """Persist an internal plan mutation without losing concurrent writes.

    Internal writers (coach tool commit, evidence-adopt stage advance) hold no
    client base revision, so instead of an unconditional overwrite they
    compare-and-write against the head revision under the SQLite write lock,
    retrying when another writer moved the plan first. Repositories without
    revision support (test doubles) fall back to the legacy save. Returns the
    new head revision when known.
    """
    save_method = getattr(repository, "save_plan_with_revision", None)
    read_method = getattr(repository, "get_plan_revision", None)
    if not callable(save_method) or not callable(read_method):
        repository.save_plan(workspace_id, plan)
        legacy_read = getattr(repository, "get_plan_revision", None)
        if callable(legacy_read):
            return cast(int, legacy_read(workspace_id, plan.id))
        return None
    read_revision = cast(Callable[[str, str], int], read_method)
    save_with_revision = cast(Callable[..., dict[str, Any] | None], save_method)
    for _ in range(max(1, max_attempts)):
        current = read_revision(workspace_id, plan.id)
        saved = save_with_revision(workspace_id, plan, expected_revision=current)
        if saved is not None:
            return int(saved.get("revision") or (current + 1))
    # Every attempt lost the race. The legacy save still advances the
    # revision counter under the write lock, so other windows detect the
    # change instead of silently keeping a stale base.
    repository.save_plan(workspace_id, plan)
    return read_revision(workspace_id, plan.id)
