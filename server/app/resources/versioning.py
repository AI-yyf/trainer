"""Resource content versions and durable citation provenance.

Resource versions remain after a resource is tombstoned.  Search and teaching
projections can therefore carry a precise content anchor while old records
that only contain a resource id continue to load unchanged.
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
CREATE TABLE IF NOT EXISTS resource_versions (
    version_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    location TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resource_versions
    ON resource_versions(workspace_id, resource_id, version DESC);
CREATE TABLE IF NOT EXISTS resource_citations (
    citation_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    version_id TEXT,
    content_hash TEXT,
    location TEXT NOT NULL DEFAULT '{}',
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resource_citations_resource
    ON resource_citations(workspace_id, resource_id, created_at);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_content_hash(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def normalize_location(location: object | None, *, fallback_path: str = "") -> dict[str, Any]:
    """Normalize a location while accepting legacy string and missing values."""
    if isinstance(location, str):
        value = location.strip()
        normalized: dict[str, Any] = {"path": value} if value else {}
    elif isinstance(location, dict):
        normalized = {
            str(key): value
            for key, value in location.items()
            if value is not None and (not isinstance(value, str) or value.strip())
        }
    else:
        normalized = {}
    if not normalized and fallback_path.strip():
        normalized["path"] = fallback_path.strip()
    return normalized


def provenance_payload(
    *,
    resource_id: str,
    version_id: str | None = None,
    content_hash: str | None = None,
    location: object | None = None,
    fallback_path: str = "",
) -> dict[str, Any]:
    """Build the stable provenance envelope used by citations and fragments."""
    return {
        "resource_id": str(resource_id or "").strip(),
        "version_id": str(version_id or "").strip() or None,
        "content_hash": str(content_hash or "").strip() or None,
        "location": normalize_location(location, fallback_path=fallback_path),
    }


class ResourceVersionStore:
    """Tracks retained content versions and citations per resource."""

    def __init__(self, database_path: str | Path) -> None:
        self._path = Path(database_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        try:
            connection.executescript(_SCHEMA)
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(resource_versions)").fetchall()
            }
            if "location" not in columns:
                connection.execute(
                    "ALTER TABLE resource_versions ADD COLUMN location TEXT NOT NULL DEFAULT ''"
                )
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
        location: object | None = None,
    ) -> dict[str, Any]:
        """Record a new content version and return its provenance metadata."""
        content_hash = compute_content_hash(content)
        normalized_location = normalize_location(location)
        connection = self._connect()
        try:
            existing = connection.execute(
                """SELECT version_id, workspace_id, resource_id, content_hash,
                          version, location, created_at
                   FROM resource_versions
                   WHERE workspace_id = ? AND resource_id = ?
                   ORDER BY version DESC LIMIT 1""",
                (workspace_id, resource_id),
            ).fetchone()
            if existing is not None and str(existing["content_hash"]) == content_hash:
                return self._version_payload(existing)
            row = connection.execute(
                "SELECT MAX(version) AS max_v FROM resource_versions "
                "WHERE workspace_id = ? AND resource_id = ?",
                (workspace_id, resource_id),
            ).fetchone()
            version = (row["max_v"] or 0) + 1
            version_id = f"rv-{uuid.uuid4().hex}"
            now = utc_now()
            connection.execute(
                """INSERT INTO resource_versions
                   (version_id, workspace_id, resource_id, content_hash, version, location, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    version_id,
                    workspace_id,
                    resource_id,
                    content_hash,
                    version,
                    json.dumps(normalized_location, ensure_ascii=False),
                    now,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return provenance_payload(
            resource_id=resource_id,
            version_id=version_id,
            content_hash=content_hash,
            location=normalized_location,
        ) | {
            "workspace_id": workspace_id,
            "version": version,
            "created_at": now,
        }

    def current_content_hash(self, workspace_id: str, resource_id: str) -> str | None:
        current = self.current_version(workspace_id, resource_id)
        return str(current["content_hash"]) if current else None

    def current_version(self, workspace_id: str, resource_id: str) -> dict[str, Any] | None:
        """Return the current version row, or ``None`` for a legacy resource."""
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT version_id, workspace_id, resource_id, content_hash,
                          version, location, created_at
                   FROM resource_versions
                   WHERE workspace_id = ? AND resource_id = ?
                   ORDER BY version DESC LIMIT 1""",
                (workspace_id, resource_id),
            ).fetchone()
        finally:
            connection.close()
        return self._version_payload(row) if row else None

    def provenance(
        self,
        workspace_id: str,
        resource_id: str,
        *,
        location: object | None = None,
        fallback_path: str = "",
        content_hash: str | None = None,
    ) -> dict[str, Any]:
        """Return a backward-compatible provenance envelope for a resource."""
        current = self.current_version(workspace_id, resource_id) or {}
        return provenance_payload(
            resource_id=resource_id,
            version_id=current.get("version_id"),
            content_hash=current.get("content_hash") or content_hash,
            location=location if location is not None else current.get("location"),
            fallback_path=fallback_path,
        )

    def record_citation(
        self,
        *,
        workspace_id: str,
        resource_id: str,
        version_id: str | None,
        content_hash: str | None,
        location: object | None = None,
        citation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a citation independently of resource deletion or restore."""
        normalized_location = normalize_location(location)
        location_key = json.dumps(normalized_location, ensure_ascii=False, sort_keys=True)
        stable_id = citation_id or (
            f"citation:{resource_id}:{version_id or 'legacy'}:"
            f"{hashlib.sha256(location_key.encode('utf-8')).hexdigest()[:16]}"
        )
        now = utc_now()
        citation = provenance_payload(
            resource_id=resource_id,
            version_id=version_id,
            content_hash=content_hash,
            location=normalized_location,
        ) | {
            "citation_id": stable_id,
            "workspace_id": workspace_id,
            "created_at": now,
            "payload": dict(payload or {}),
        }
        connection = self._connect()
        try:
            connection.execute(
                """INSERT OR IGNORE INTO resource_citations
                   (citation_id, workspace_id, resource_id, version_id, content_hash,
                    location, payload, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    stable_id,
                    workspace_id,
                    resource_id,
                    version_id,
                    content_hash,
                    location_key,
                    json.dumps(dict(payload or {}), ensure_ascii=False),
                    now,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return citation

    def list_citations(self, workspace_id: str, resource_id: str) -> list[dict[str, Any]]:
        """List retained citations, including citations from deleted resources."""
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT citation_id, workspace_id, resource_id, version_id,
                          content_hash, location, payload, created_at
                   FROM resource_citations
                   WHERE workspace_id = ? AND resource_id = ?
                   ORDER BY created_at ASC, citation_id ASC""",
                (workspace_id, resource_id),
            ).fetchall()
        finally:
            connection.close()
        citations: list[dict[str, Any]] = []
        for row in rows:
            try:
                location = json.loads(str(row["location"] or "{}"))
            except (TypeError, ValueError):
                location = normalize_location(row["location"])
            try:
                payload = json.loads(str(row["payload"] or "{}"))
            except (TypeError, ValueError):
                payload = {}
            citations.append(
                provenance_payload(
                    resource_id=str(row["resource_id"]),
                    version_id=row["version_id"],
                    content_hash=row["content_hash"],
                    location=location,
                )
                | {
                    "citation_id": str(row["citation_id"]),
                    "workspace_id": str(row["workspace_id"]),
                    "created_at": str(row["created_at"]),
                    "payload": payload if isinstance(payload, dict) else {},
                }
            )
        return citations

    def record_version_if_changed(
        self,
        *,
        workspace_id: str,
        resource_id: str,
        content: str | bytes,
        location: object | None = None,
    ) -> dict[str, Any] | None:
        """Append a version only when content differs from the current head."""
        if self.current_content_hash(workspace_id, resource_id) == compute_content_hash(content):
            return None
        return self.record_version(
            workspace_id=workspace_id,
            resource_id=resource_id,
            content=content,
            location=location,
        )

    @staticmethod
    def _version_payload(row: sqlite3.Row) -> dict[str, Any]:
        raw_location = row["location"] if "location" in row.keys() else ""
        try:
            location = json.loads(str(raw_location or "{}"))
        except (TypeError, ValueError):
            location = normalize_location(raw_location)
        return {
            "version_id": str(row["version_id"]),
            "workspace_id": str(row["workspace_id"]),
            "resource_id": str(row["resource_id"]),
            "content_hash": str(row["content_hash"]),
            "version": int(row["version"]),
            "location": location if isinstance(location, dict) else {},
            "created_at": str(row["created_at"]),
        }


def check_remote_runner_boundary(
    *,
    is_remote_workspace: bool,
    has_remote_runner: bool = False,
) -> str | None:
    """Return an honest limitation when local verification is unsafe remotely."""
    if not is_remote_workspace:
        return None
    if has_remote_runner:
        return None
    return (
        "Remote workspace detected but no remote verification runner is available. "
        "Trainer will not run local checks against a remote project."
    )
