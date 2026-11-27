"""Durable append-only storage for the unified event ledger.

The store owns durable history and identity for
:class:`~app.core.event_ledger.EventLedgerService`:

* **restart-safe history** — recorded events survive a sidecar restart;
* **idempotent replay** — the same ``(workspace, idempotency_key)`` pair yields
  the original entry instead of a duplicate, so a retried save cannot append
  the same learning fact twice.

Workspace scoping is storage-only: two workspaces may reuse the same
idempotency key without colliding, and the public entry model is unchanged.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any, cast

from .models import EventLedgerEntry, EventReversibility, utc_now_iso

_EPOCH_BUMP_EVENT_TYPES = frozenset({"workspace_reset", "sandbox_workspace_cleared"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_ledger (
    event_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    scope TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    source_chain_json TEXT NOT NULL DEFAULT '[]',
    payload_ref_json TEXT NOT NULL DEFAULT '{}',
    before_state_ref_json TEXT NOT NULL DEFAULT '{}',
    after_state_ref_json TEXT NOT NULL DEFAULT '{}',
    reversibility TEXT NOT NULL DEFAULT 'irreversible',
    audit_note TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    workspace_epoch INTEGER NOT NULL DEFAULT 0,
    seq INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_event_ledger_workspace_time
    ON event_ledger(workspace_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_event_ledger_project_time
    ON event_ledger(project_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_event_ledger_reversed_event
    ON event_ledger(event_type, json_extract(payload_ref_json, '$.reversed_event_id'))
    WHERE event_type = 'event_reversed';
CREATE UNIQUE INDEX IF NOT EXISTS idx_event_ledger_idempotency
    ON event_ledger(workspace_id, idempotency_key)
    WHERE idempotency_key <> '';
"""

_INSERT_SQL = """
INSERT INTO event_ledger (
    event_id, workspace_id, event_type, occurred_at, actor, scope, project_id,
    source_chain_json, payload_ref_json, before_state_ref_json,
    after_state_ref_json, reversibility, audit_note, idempotency_key, created_at,
    workspace_epoch, seq
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(workspace_id, idempotency_key) WHERE idempotency_key <> '' DO NOTHING
"""


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_object(text: Any) -> dict[str, Any]:
    if not isinstance(text, str) or not text:
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(text: Any) -> list[str]:
    if not isinstance(text, str) or not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]


def entry_from_row(row: sqlite3.Row) -> EventLedgerEntry:
    keys = set(row.keys())
    return EventLedgerEntry(
        event_id=str(row["event_id"]),
        event_type=str(row["event_type"]),
        occurred_at=str(row["occurred_at"]),
        actor=str(row["actor"]),
        scope=str(row["scope"]),
        project_id=str(row["project_id"]),
        source_chain=_json_list(row["source_chain_json"]),
        payload_ref=_json_object(row["payload_ref_json"]),
        before_state_ref=_json_object(row["before_state_ref_json"]),
        after_state_ref=_json_object(row["after_state_ref_json"]),
        reversibility=cast(EventReversibility, str(row["reversibility"])),
        audit_note=str(row["audit_note"]),
        workspace_epoch=int(row["workspace_epoch"]) if "workspace_epoch" in keys and row["workspace_epoch"] is not None else 0,
        seq=int(row["seq"]) if "seq" in keys and row["seq"] is not None else 0,
    )


class EventLedgerStore:
    """SQLite-backed append-only ledger store on the sidecar database."""

    def __init__(self, database_path: str | Path) -> None:
        self._path = Path(database_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=5.0)
        try:
            connection.executescript(_SCHEMA)
            cols = {str(r[1]) for r in connection.execute("PRAGMA table_info(event_ledger)").fetchall()}
            if "workspace_epoch" not in cols:
                connection.execute("ALTER TABLE event_ledger ADD COLUMN workspace_epoch INTEGER NOT NULL DEFAULT 0")
            if "seq" not in cols:
                connection.execute("ALTER TABLE event_ledger ADD COLUMN seq INTEGER NOT NULL DEFAULT 0")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_event_ledger_workspace_seq ON event_ledger(workspace_id, seq)"
            )
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def append(
        self,
        entry: EventLedgerEntry,
        *,
        workspace_id: str = "",
        idempotency_key: str = "",
        transaction: sqlite3.Connection | None = None,
    ) -> tuple[EventLedgerEntry, bool]:
        """Append ``entry``; replay the stored entry for a repeated key.

        Returns ``(entry, created)`` where ``created`` is False when the
        ``(workspace_id, idempotency_key)`` pair already existed.
        """
        key = idempotency_key.strip()
        workspace = workspace_id or entry.project_id
        connection_scope = (
            nullcontext(transaction) if transaction is not None else closing(self._connect())
        )
        with connection_scope as connection:
            coord_row = connection.execute(
                "SELECT COALESCE(MAX(workspace_epoch), 0), COALESCE(MAX(seq), 0) FROM event_ledger WHERE workspace_id = ?",
                (workspace,),
            ).fetchone()
            current_epoch = int(coord_row[0]) if coord_row is not None else 0
            next_seq = (int(coord_row[1]) if coord_row is not None else 0) + 1
            assigned_epoch = (
                entry.workspace_epoch
                if entry.workspace_epoch > current_epoch
                else (current_epoch + 1 if entry.event_type in _EPOCH_BUMP_EVENT_TYPES else current_epoch)
            )
            assigned_seq = entry.seq if entry.seq >= next_seq else next_seq
            persisted_entry = entry.model_copy(
                update={"workspace_epoch": assigned_epoch, "seq": assigned_seq}
            )
            cursor = connection.execute(
                _INSERT_SQL,
                (
                    persisted_entry.event_id,
                    workspace,
                    persisted_entry.event_type,
                    persisted_entry.occurred_at,
                    persisted_entry.actor,
                    persisted_entry.scope,
                    persisted_entry.project_id,
                    _json_text(persisted_entry.source_chain),
                    _json_text(persisted_entry.payload_ref),
                    _json_text(persisted_entry.before_state_ref),
                    _json_text(persisted_entry.after_state_ref),
                    persisted_entry.reversibility,
                    persisted_entry.audit_note,
                    key,
                    utc_now_iso(),
                    assigned_epoch,
                    assigned_seq,
                ),
            )
            created = cursor.rowcount > 0
            if not created:
                row = connection.execute(
                    "SELECT * FROM event_ledger WHERE workspace_id = ? AND idempotency_key = ?",
                    (workspace, key),
                ).fetchone()
                if row is None:
                    raise RuntimeError(
                        "Event ledger reported a replay conflict without a stored entry."
                    )
                return entry_from_row(row), False
            if transaction is None:
                connection.commit()
        return persisted_entry, True

    def load_recent(self, *, limit: int = 2000) -> list[EventLedgerEntry]:
        """Return up to ``limit`` most recent entries in chronological order."""
        if limit <= 0:
            return []
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM event_ledger ORDER BY occurred_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            connection.close()
        return [entry_from_row(row) for row in reversed(rows)]

    def find_event(self, event_id: str) -> tuple[str, EventLedgerEntry] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM event_ledger WHERE event_id = ?", (event_id,)
            ).fetchone()
        return (str(row["workspace_id"]), entry_from_row(row)) if row is not None else None

    def find_reversal(self, event_id: str) -> EventLedgerEntry | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM event_ledger
                WHERE event_type = 'event_reversed'
                  AND json_extract(payload_ref_json, '$.reversed_event_id') = ?
                ORDER BY rowid LIMIT 1
                """,
                (event_id,),
            ).fetchone()
        return entry_from_row(row) if row is not None else None

    def current_workspace_coords(self, workspace_id: str) -> tuple[int, int]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(workspace_epoch), 0), COALESCE(MAX(seq), 0) FROM event_ledger WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        if row is None:
            return 0, 0
        return int(row[0]), int(row[1])

    def query(
        self,
        *,
        workspace_id: str | None = None,
        event_type: str | None = None,
        event_types: Collection[str] | None = None,
        project_id: str | None = None,
        scope: str | None = None,
        actor: str | None = None,
        min_epoch: int | None = None,
        limit: int | None = None,
        offset: int = 0,
        effective: bool = False,
        newest_first: bool = False,
    ) -> list[EventLedgerEntry]:
        filters = [
            ("workspace_id", workspace_id),
            ("event_type", event_type),
            ("project_id", project_id),
            ("scope", scope),
            ("actor", actor),
        ]
        clauses = [f"entry.{name} = ?" for name, value in filters if value is not None]
        args: list[Any] = [value for _, value in filters if value is not None]
        if min_epoch is not None:
            clauses.append("entry.workspace_epoch >= ?")
            args.append(int(min_epoch))
        if event_types is not None:
            types = tuple(event_types)
            if not types:
                return []
            placeholders = ", ".join("?" for _ in types)
            clauses.append(f"entry.event_type IN ({placeholders})")
            args.extend(types)
        if effective:
            clauses.extend([
                "entry.event_type <> 'event_reversed'",
                """NOT EXISTS (
                    SELECT 1 FROM event_ledger AS reversal
                    WHERE reversal.event_type = 'event_reversed'
                      AND json_extract(reversal.payload_ref_json, '$.reversed_event_id') = entry.event_id
                )""",
            ])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        if workspace_id is not None:
            order = (
                "ORDER BY entry.seq DESC, entry.rowid DESC"
                if newest_first
                else "ORDER BY entry.seq ASC, entry.rowid ASC"
            )
        else:
            order = (
                "ORDER BY entry.occurred_at DESC, entry.rowid DESC"
                if newest_first
                else "ORDER BY entry.occurred_at, entry.rowid"
            )
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT entry.* FROM event_ledger AS entry"
                + where + f" {order} LIMIT ? OFFSET ?",
                (*args, -1 if limit is None else max(0, limit), max(0, offset)),
            ).fetchall()
        return [entry_from_row(row) for row in rows]

    def count(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        event_type: str | None = None,
    ) -> int:
        filters = [("workspace_id", workspace_id), ("project_id", project_id), ("event_type", event_type)]
        clauses = [f"{name} = ?" for name, value in filters if value is not None]
        args = [value for _, value in filters if value is not None]
        with closing(self._connect()) as connection:
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            row = connection.execute("SELECT COUNT(*) AS n FROM event_ledger" + where, args).fetchone()
        return int(row["n"]) if row is not None else 0

    def find_by_idempotency_key(
        self,
        *,
        workspace_id: str,
        idempotency_key: str,
        transaction: sqlite3.Connection | None = None,
    ) -> EventLedgerEntry | None:
        key = idempotency_key.strip()
        if not key:
            return None
        connection_scope = (
            nullcontext(transaction) if transaction is not None else closing(self._connect())
        )
        with connection_scope as connection:
            row = connection.execute(
                "SELECT * FROM event_ledger WHERE workspace_id = ? AND idempotency_key = ?",
                (workspace_id, key),
            ).fetchone()
        return entry_from_row(row) if row is not None else None
