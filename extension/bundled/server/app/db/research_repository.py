"""SQLite persistence layer for research entities.

Follows the TrainerRepository pattern: typed columns for queryable fields
plus ``payload_json`` for the full serialised domain object.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from ..research.models import (
    AgentState,
    Approval,
    Artifact,
    Checkpoint,
    Finding,
    ResearchProject,
    ResearchTheme,
    ResearchThread,
    ThemeStatus,
    utc_now,
)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS research_projects (
    project_id  TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_themes (
    theme_id    TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS research_threads (
    thread_id   TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    theme_id    TEXT NOT NULL,
    angle       TEXT NOT NULL,
    depth       TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY (theme_id)   REFERENCES research_themes(theme_id)   ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS research_findings (
    finding_id  TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    theme_id    TEXT NOT NULL,
    thread_id   TEXT NOT NULL,
    source      TEXT NOT NULL,
    confidence  REAL NOT NULL,
    created_at  TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY (theme_id)   REFERENCES research_themes(theme_id)   ON DELETE CASCADE,
    FOREIGN KEY (thread_id)  REFERENCES research_threads(thread_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS research_artifacts (
    artifact_id TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    theme_id    TEXT NOT NULL,
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL,
    version     INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY (theme_id)   REFERENCES research_themes(theme_id)   ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS research_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL,
    theme_id      TEXT NOT NULL,
    label         TEXT NOT NULL,
    due_date      TEXT NOT NULL,
    completed     INTEGER NOT NULL DEFAULT 0,
    completed_at  TEXT,
    payload_json  TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE,
    FOREIGN KEY (theme_id)   REFERENCES research_themes(theme_id)   ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS research_approvals (
    approval_id TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    resolved_at TEXT,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS research_gate_messages (
    message_id  TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS research_agent_state (
    project_id        TEXT PRIMARY KEY,
    current_role      TEXT NOT NULL,
    current_iteration INTEGER NOT NULL,
    self_review_count INTEGER NOT NULL,
    payload_json      TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES research_projects(project_id) ON DELETE CASCADE
);
"""


class ResearchRepository:
    """SQLite-backed persistence for all nine research entity types."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> ResearchProject:
        return ResearchProject.from_dict(json.loads(row["payload_json"]))

    @staticmethod
    def _row_to_theme(row: sqlite3.Row) -> ResearchTheme:
        return ResearchTheme.from_dict(json.loads(row["payload_json"]))

    @staticmethod
    def _row_to_thread(row: sqlite3.Row) -> ResearchThread:
        return ResearchThread.from_dict(json.loads(row["payload_json"]))

    @staticmethod
    def _row_to_finding(row: sqlite3.Row) -> Finding:
        return Finding.from_dict(json.loads(row["payload_json"]))

    @staticmethod
    def _row_to_artifact(row: sqlite3.Row) -> Artifact:
        return Artifact.from_dict(json.loads(row["payload_json"]))

    @staticmethod
    def _row_to_checkpoint(row: sqlite3.Row) -> Checkpoint:
        return Checkpoint.from_dict(json.loads(row["payload_json"]))

    @staticmethod
    def _row_to_approval(row: sqlite3.Row) -> Approval:
        return Approval.from_dict(json.loads(row["payload_json"]))

    @staticmethod
    def _row_to_agent_state(row: sqlite3.Row) -> AgentState:
        return AgentState.from_dict(json.loads(row["payload_json"]))

    # ------------------------------------------------------------------
    # Project CRUD
    # ------------------------------------------------------------------

    def save_project(self, project: ResearchProject) -> None:
        payload = json.dumps(project.to_full_dict())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_projects (project_id, title, description, created_at, updated_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (project.id, project.title, project.description, project.created_at.isoformat(), project.updated_at.isoformat(), payload),
            )

    def get_project(self, project_id: str) -> ResearchProject | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return self._row_to_project(row) if row else None

    def list_projects(self) -> list[ResearchProject]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM research_projects ORDER BY created_at DESC").fetchall()
        return [self._row_to_project(r) for r in rows]

    def delete_project(self, project_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM research_projects WHERE project_id = ?", (project_id,))
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Theme CRUD
    # ------------------------------------------------------------------

    def save_theme(self, project_id: str, theme: ResearchTheme) -> None:
        payload = json.dumps(theme.to_full_dict())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_themes (theme_id, project_id, title, status, created_at, updated_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(theme_id) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (theme.id, project_id, theme.title, theme.status, theme.created_at.isoformat(), theme.updated_at.isoformat(), payload),
            )

    def get_themes_by_project(self, project_id: str) -> list[ResearchTheme]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_themes WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        return [self._row_to_theme(r) for r in rows]

    def update_theme_status(self, theme_id: str, status: ThemeStatus) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM research_themes WHERE theme_id = ?", (theme_id,)).fetchone()
            if not row:
                return
            theme = ResearchTheme.from_dict(json.loads(row["payload_json"]))
            theme.status = status
            theme.updated_at = utc_now()
            payload = json.dumps(theme.to_full_dict())
            conn.execute(
                "UPDATE research_themes SET status = ?, updated_at = ?, payload_json = ? WHERE theme_id = ?",
                (status, theme.updated_at.isoformat(), payload, theme_id),
            )

    # ------------------------------------------------------------------
    # Thread CRUD
    # ------------------------------------------------------------------

    def save_thread(self, project_id: str, theme_id: str, thread: ResearchThread) -> None:
        payload = json.dumps(thread.to_full_dict())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_threads (thread_id, project_id, theme_id, angle, depth, status, created_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    angle = excluded.angle,
                    depth = excluded.depth,
                    status = excluded.status,
                    payload_json = excluded.payload_json
                """,
                (thread.id, project_id, theme_id, thread.angle, thread.depth, thread.status, thread.created_at.isoformat(), payload),
            )

    def get_threads_by_theme(self, theme_id: str) -> list[ResearchThread]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_threads WHERE theme_id = ? ORDER BY created_at",
                (theme_id,),
            ).fetchall()
        return [self._row_to_thread(r) for r in rows]

    # ------------------------------------------------------------------
    # Finding CRUD
    # ------------------------------------------------------------------

    def save_finding(self, project_id: str, theme_id: str, thread_id: str, finding: Finding) -> None:
        payload = json.dumps(finding.to_full_dict())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_findings (finding_id, project_id, theme_id, thread_id, source, confidence, created_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(finding_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (finding.id, project_id, theme_id, thread_id, finding.source, finding.confidence, finding.created_at.isoformat(), payload),
            )

    def get_findings_by_thread(self, thread_id: str) -> list[Finding]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_findings WHERE thread_id = ? ORDER BY created_at",
                (thread_id,),
            ).fetchall()
        return [self._row_to_finding(r) for r in rows]

    # ------------------------------------------------------------------
    # Artifact CRUD
    # ------------------------------------------------------------------

    def save_artifact(self, project_id: str, theme_id: str, artifact: Artifact) -> None:
        payload = json.dumps(artifact.to_full_dict())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_artifacts (artifact_id, project_id, theme_id, title, kind, version, created_at, updated_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    title = excluded.title,
                    version = excluded.version,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (
                    artifact.id,
                    project_id,
                    theme_id,
                    artifact.title,
                    artifact.kind,
                    artifact.version,
                    artifact.created_at.isoformat(),
                    artifact.updated_at.isoformat(),
                    payload,
                ),
            )

    def get_artifacts_by_theme(self, theme_id: str) -> list[Artifact]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_artifacts WHERE theme_id = ? ORDER BY created_at",
                (theme_id,),
            ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    # ------------------------------------------------------------------
    # Checkpoint CRUD
    # ------------------------------------------------------------------

    def save_checkpoint(self, project_id: str, theme_id: str, checkpoint: Checkpoint) -> None:
        payload = json.dumps(checkpoint.to_full_dict())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_checkpoints (checkpoint_id, project_id, theme_id, label, due_date, completed, completed_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                    completed = excluded.completed,
                    completed_at = excluded.completed_at,
                    payload_json = excluded.payload_json
                """,
                (
                    checkpoint.id,
                    project_id,
                    theme_id,
                    checkpoint.label,
                    checkpoint.due_date.isoformat(),
                    int(checkpoint.completed),
                    checkpoint.completed_at.isoformat() if checkpoint.completed_at else None,
                    payload,
                ),
            )

    def get_checkpoints_by_theme(self, theme_id: str) -> list[Checkpoint]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_checkpoints WHERE theme_id = ? ORDER BY due_date",
                (theme_id,),
            ).fetchall()
        return [self._row_to_checkpoint(r) for r in rows]

    def update_checkpoint(self, checkpoint_id: str, completed: bool, completed_at: str | None) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM research_checkpoints WHERE checkpoint_id = ?", (checkpoint_id,)).fetchone()
            if not row:
                return
            cp = Checkpoint.from_dict(json.loads(row["payload_json"]))
            cp.completed = completed
            cp.completed_at = datetime.fromisoformat(completed_at) if completed_at else None
            payload = json.dumps(cp.to_full_dict())
            conn.execute(
                "UPDATE research_checkpoints SET completed = ?, completed_at = ?, payload_json = ? WHERE checkpoint_id = ?",
                (int(completed), completed_at, payload, checkpoint_id),
            )

    # ------------------------------------------------------------------
    # Approval CRUD
    # ------------------------------------------------------------------

    def save_approval(self, project_id: str, approval: Approval) -> None:
        payload = json.dumps(approval.to_full_dict())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_approvals (approval_id, project_id, title, status, created_at, resolved_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(approval_id) DO UPDATE SET
                    status = excluded.status,
                    resolved_at = excluded.resolved_at,
                    payload_json = excluded.payload_json
                """,
                (
                    approval.id,
                    project_id,
                    approval.title,
                    approval.status,
                    approval.created_at.isoformat(),
                    approval.resolved_at.isoformat() if approval.resolved_at else None,
                    payload,
                ),
            )

    def get_pending_approvals(self, project_id: str) -> list[Approval]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_approvals WHERE project_id = ? AND status = ? ORDER BY created_at",
                (project_id, "pending"),
            ).fetchall()
        return [self._row_to_approval(r) for r in rows]

    def resolve_approval(self, approval_id: str, approved: bool) -> None:
        from ..research.models import ApprovalStatus

        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM research_approvals WHERE approval_id = ?", (approval_id,)).fetchone()
            if not row:
                return
            approval = Approval.from_dict(json.loads(row["payload_json"]))
            new_status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
            now = utc_now()
            approval.status = new_status
            approval.resolved_at = now
            payload = json.dumps(approval.to_full_dict())
            conn.execute(
                "UPDATE research_approvals SET status = ?, resolved_at = ?, payload_json = ? WHERE approval_id = ?",
                (new_status, now.isoformat(), payload, approval_id),
            )

    # ------------------------------------------------------------------
    # Gate Message CRUD
    # ------------------------------------------------------------------

    def save_gate_message(self, project_id: str, message: dict[str, Any]) -> None:
        message_id = message.get("id", f"gate_msg_{id(message)}")
        payload = json.dumps(message)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_gate_messages (message_id, project_id, role, timestamp, payload_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (message_id, project_id, message.get("role", ""), message.get("timestamp", ""), payload),
            )

    def get_gate_messages(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM research_gate_messages WHERE project_id = ? ORDER BY timestamp",
                (project_id,),
            ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    # ------------------------------------------------------------------
    # Agent State CRUD
    # ------------------------------------------------------------------

    def save_agent_state(self, project_id: str, state: AgentState) -> None:
        payload = json.dumps(state.to_full_dict())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO research_agent_state (project_id, current_role, current_iteration, self_review_count, payload_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    current_role = excluded.current_role,
                    current_iteration = excluded.current_iteration,
                    self_review_count = excluded.self_review_count,
                    payload_json = excluded.payload_json
                """,
                (project_id, state.current_role, state.current_iteration, state.self_review_count, payload),
            )

    def get_agent_state(self, project_id: str) -> AgentState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_agent_state WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return self._row_to_agent_state(row) if row else None
