"""
Phase-D slice: training attempt persistence with evidence binding (design
§10-§11). Every training attempt gets a stable attempt_id and persists the
learner's answer draft, assistance (hint) level, bound file version and
verification status. Evidence records bind artifact hash / runner version /
execution location / trust level, and follow the honesty contract:

    说会了 ≠ 验证过;一次通过 ≠ 长期掌握。
    An evidence record only counts as *current* while its artifact hash
    matches the attempt's bound file version.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS training_attempts (
    attempt_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    card_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS training_evidence (
    evidence_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_training_attempts_card
    ON training_attempts(workspace_id, card_id);
CREATE INDEX IF NOT EXISTS idx_training_evidence_attempt
    ON training_evidence(attempt_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AttemptStore:
    """SQLite-backed store for training attempts and their evidence records."""

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

    # -- attempts -----------------------------------------------------------

    def start_attempt(
        self,
        *,
        workspace_id: str,
        card_id: str,
        file_path: str | None = None,
        file_hash: str | None = None,
        file_version: int = 1,
        assistance_level: str = "independent",
    ) -> dict[str, Any]:
        # Idempotent enter: an in-flight attempt for the same workspace+card is
        # resumed, never duplicated (return/close retires it first).
        active = self.find_active_attempt(workspace_id, card_id)
        if active is not None:
            refreshed = self.update_attempt(
                active["attempt_id"],
                file_path=file_path,
                file_hash=file_hash,
                file_version=file_version,
            )
            return refreshed or active
        attempt_id = f"attempt-{uuid.uuid4().hex}"
        now = utc_now()
        payload = {
            "attempt_id": attempt_id,
            "workspace_id": workspace_id,
            "card_id": card_id,
            "status": "active",
            "answer_draft": "",
            "assistance_level": assistance_level,
            "file_path": file_path,
            "file_hash": file_hash,
            "file_version": file_version,
            "created_at": now,
            "updated_at": now,
        }
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO training_attempts (attempt_id, workspace_id, card_id, payload) VALUES (?, ?, ?, ?)",
                (attempt_id, workspace_id, card_id, json.dumps(payload, ensure_ascii=False)),
            )
            connection.commit()
        finally:
            connection.close()
        return payload

    def find_active_attempt(self, workspace_id: str, card_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT payload FROM training_attempts WHERE workspace_id = ? AND card_id = ? ORDER BY rowid",
                (workspace_id, card_id),
            ).fetchall()
        finally:
            connection.close()
        for row in rows:
            payload = json.loads(row["payload"])
            if payload.get("status") in ("active", "answered", "implemented"):
                return payload
        return None

    def close_attempt(self, attempt_id: str, *, workspace_id: str) -> dict[str, Any] | None:
        # Return retires the attempt lifecycle without deleting history.
        return self.update_attempt_for_workspace(
            attempt_id, workspace_id=workspace_id, status="returned"
        )

    def update_attempt_for_workspace(
        self,
        attempt_id: str,
        *,
        workspace_id: str,
        **updates: Any,
    ) -> dict[str, Any] | None:
        # Workspace isolation: a caller bound to another workspace can neither
        # read nor write this attempt — fail closed.
        attempt = self.get_attempt_payload_for_workspace(attempt_id, workspace_id)
        if attempt is None:
            return None
        return self.update_attempt(attempt_id, **updates)

    def update_attempt(
        self,
        attempt_id: str,
        *,
        workspace_id: str | None = None,
        answer_draft: str | None = None,
        assistance_level: str | None = None,
        status: str | None = None,
        file_path: str | None = None,
        file_hash: str | None = None,
        file_version: int | None = None,
    ) -> dict[str, Any] | None:
        existing = self._read_attempt_row(attempt_id)
        if existing is None:
            return None
        # Workspace isolation: cross-workspace writes fail closed.
        if (
            workspace_id is not None
            and json.loads(existing["payload"]).get("workspace_id") != workspace_id
        ):
            return None
        payload = json.loads(existing["payload"])
        if answer_draft is not None:
            payload["answer_draft"] = answer_draft
        if assistance_level is not None:
            payload["assistance_level"] = assistance_level
        if status is not None:
            payload["status"] = status
        if file_path is not None:
            payload["file_path"] = file_path
        if file_hash is not None:
            payload["file_hash"] = file_hash
        if file_version is not None:
            payload["file_version"] = file_version
        payload["updated_at"] = utc_now()
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE training_attempts SET payload = ? WHERE attempt_id = ?",
                (json.dumps(payload, ensure_ascii=False), attempt_id),
            )
            connection.commit()
        finally:
            connection.close()
        return payload

    def get_attempt(
        self, attempt_id: str, *, workspace_id: str | None = None
    ) -> dict[str, Any] | None:
        payload = self.get_attempt_payload(attempt_id)
        if payload is None:
            return None
        if workspace_id is not None and payload.get("workspace_id") != workspace_id:
            return None
        evidence = self.list_evidence(attempt_id)
        payload["evidence"] = evidence
        payload["has_current_evidence"] = any(item.get("is_current") for item in evidence)
        return payload

    # -- evidence -----------------------------------------------------------

    def record_evidence(
        self,
        *,
        attempt_id: str,
        artifact_hash: str,
        result: str,
        runner_version: str = "trainer-sidecar",
        execution_location: str = "workspace",
        trust_level: str = "controlled_check",
        limitations: list[str] | None = None,
    ) -> dict[str, Any] | None:
        # Identity derives from the stored attempt — the client cannot forge
        # another workspace's or card's evidence.
        attempt = self.get_attempt_payload(attempt_id)
        if attempt is None:
            return None
        workspace_id = attempt["workspace_id"]
        card_id = attempt["card_id"]
        now = utc_now()
        evidence_id = f"evidence-{uuid.uuid4().hex}"

        # Honesty contract: recording new evidence supersedes the previous
        # current record for this attempt.
        for row in self.list_evidence_rows(attempt_id):
            payload = json.loads(row["payload"])
            if payload.get("superseded_by_evidence_id") is None:
                payload["superseded_by_evidence_id"] = evidence_id
                self._write_evidence_row(row["evidence_id"], payload)

        payload = {
            "evidence_id": evidence_id,
            "attempt_id": attempt_id,
            "card_id": card_id,
            "artifact_hash": artifact_hash,
            "artifact_version": attempt.get("file_version", 1),
            "runner_version": runner_version,
            "execution_location": execution_location,
            "trust_level": trust_level,
            "assistance_level": attempt.get("assistance_level", "independent"),
            "result": result,
            "limitations": limitations or [],
            "created_at": now,
            "superseded_by_evidence_id": None,
        }
        self._write_evidence_row(evidence_id, payload)
        self.update_attempt(
            attempt_id,
            status="verified" if result == "passed" else attempt.get("status"),
            file_hash=artifact_hash,
        )
        # The brand-new record is current by definition: the attempt's bound
        # artifact hash now matches it.
        payload["is_current"] = True
        return payload

    def list_evidence(self, attempt_id: str) -> list[dict[str, Any]]:
        rows = self.list_evidence_rows(attempt_id)
        items = [json.loads(row["payload"]) for row in rows]
        attempt = self.get_attempt_payload(attempt_id)
        current_hash = (attempt or {}).get("file_hash")
        for item in items:
            item["is_current"] = bool(
                item.get("superseded_by_evidence_id") is None
                and current_hash
                and item.get("artifact_hash") == current_hash
            )
        return items

    # -- internals ----------------------------------------------------------

    def _write_evidence_row(self, evidence_id: str, payload: dict[str, Any]) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "INSERT OR REPLACE INTO training_evidence (evidence_id, workspace_id, attempt_id, created_at, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    evidence_id,
                    payload.get("workspace_id", ""),
                    payload.get("attempt_id", ""),
                    payload.get("created_at", utc_now()),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def list_evidence_rows(self, attempt_id: str) -> list[sqlite3.Row]:
        connection = self._connect()
        try:
            return connection.execute(
                "SELECT evidence_id, workspace_id, attempt_id, created_at, payload FROM training_evidence WHERE attempt_id = ? ORDER BY created_at",
                (attempt_id,),
            ).fetchall()
        finally:
            connection.close()

    def get_attempt_payload(self, attempt_id: str) -> dict[str, Any] | None:
        row = self._read_attempt_row(attempt_id)
        if row is None:
            return None
        return json.loads(row["payload"])

    def get_attempt_payload_for_workspace(
        self, attempt_id: str, workspace_id: str
    ) -> dict[str, Any] | None:
        payload = self.get_attempt_payload(attempt_id)
        if payload is None or payload.get("workspace_id") != workspace_id:
            return None
        return payload

    def _read_attempt_row(self, attempt_id: str) -> sqlite3.Row | None:
        connection = self._connect()
        try:
            return connection.execute(
                "SELECT attempt_id, workspace_id, card_id, payload FROM training_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        finally:
            connection.close()
