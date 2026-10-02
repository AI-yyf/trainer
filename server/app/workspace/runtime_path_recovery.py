"""Rebase owned file references after a managed data snapshot moves.

Never read the old data directory. Legacy snapshots can establish their old
location only through a resource whose copied bytes match its recorded hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote, urlsplit

logger = logging.getLogger(__name__)
_LOCATION_FILE = "runtime-location.json"
_PATH_KEYS = {
    "path", "source", "canonical_source", "sandbox_path", "sandbox_origin",
    "extracted_artifact_path", "file_path", "artifact_path", "root_path",
    "sandbox_root", "sandbox_root_path", "sandbox_root_override", "trash_path",
    "source_path", "target_path", "directory", "local_path", "uri",
    "source_items", "expected_files", "expected_file_paths",
}


def _parts(value: str) -> tuple[str, ...] | None:
    parsed = PureWindowsPath(value) if re.match(r"^[A-Za-z]:[\\/]", value) else PurePosixPath(value)
    if not parsed.is_absolute() or ".." in parsed.parts:
        return None
    return parsed.parts


def _relative(value: str, old_root: str) -> tuple[str, ...] | None:
    candidate, root = _parts(value), _parts(old_root)
    if candidate is None or root is None or len(root) < 2:
        return None
    windows = bool(re.match(r"^[A-Za-z]:[\\/]", old_root))
    prefix = candidate[:len(root)]
    if windows:
        prefix, root = tuple(x.casefold() for x in prefix), tuple(x.casefold() for x in root)
    return candidate[len(root):] if prefix == root else None


def _mapped_path(value: str, roots: list[str], target: Path) -> str:
    is_uri = value.startswith("file://")
    parsed = urlsplit(value) if is_uri else None
    if parsed is not None and parsed.netloc not in {"", "localhost"}:
        return value
    raw = unquote(parsed.path) if parsed is not None else value
    if is_uri and re.match(r"^/[A-Za-z]:/", raw):
        raw = raw[1:]
    for root in roots:
        relative = _relative(raw, root)
        if relative is None:
            continue
        destination = target.joinpath(*relative)
        if not destination.resolve(strict=False).is_relative_to(target):
            return value
        return destination.as_uri() if is_uri else str(destination)
    return value


def _rewrite(value: object, roots: list[str], target: Path, *, path_field: bool = False) -> object:
    if isinstance(value, dict):
        return {
            key: _rewrite(item, roots, target, path_field=(
                re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower() in _PATH_KEYS
            ))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite(item, roots, target, path_field=path_field) for item in value]
    if isinstance(value, str) and path_field:
        return _mapped_path(value, roots, target)
    return value


def _legacy_resource_roots(connection: sqlite3.Connection, target: Path) -> list[str]:
    roots: list[str] = []
    for row in connection.execute("SELECT workspace_id, payload FROM resources"):
        resource = json.loads(row["payload"])
        workspace = "".join(
            character if character.isalnum() else "-" for character in row["workspace_id"].lower()
        ).strip("-") or "workspace"
        for field, folder in (("sandbox_path", "sandboxes"), ("source", "inline-resources")):
            raw = str(resource.get(field) or "")
            parts = _parts(raw)
            if parts is None:
                continue
            for index in range(1, len(parts) - 2):
                if parts[index:index + 2] != (folder, workspace):
                    continue
                relative = parts[index:]
                copied = target.joinpath(*relative)
                if not copied.resolve(strict=False).is_relative_to(target) or not copied.is_file():
                    continue
                recorded_hash = str(resource.get("content_hash") or "")
                if not recorded_hash or hashlib.sha256(copied.read_bytes()).hexdigest() != recorded_hash:
                    continue
                old = str(PureWindowsPath(*parts[:index])) if re.match(r"^[A-Za-z]:", raw) else str(PurePosixPath(*parts[:index]))
                if old not in roots and _relative(str(target), old) != ():
                    roots.append(old)
    return roots


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def recover_runtime_paths(database_path: Path, data_dir: Path) -> int:
    target = data_dir.resolve()
    marker = target / _LOCATION_FILE
    roots: list[str] = []
    if marker.is_file():
        location = json.loads(marker.read_text(encoding="utf-8"))
        old = location.get("dataRoot") if isinstance(location, dict) else None
        if not isinstance(location, dict) or location.get("schemaVersion") != 1 or not isinstance(old, str) or _parts(old) is None or len(_parts(old) or ()) < 2:
            raise ValueError("Trainer runtime location record is invalid.")
        if _relative(str(target), old) != ():
            roots.append(old)

    changed = 0
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        roots.extend(root for root in _legacy_resource_roots(connection, target) if root not in roots)
        if roots:
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            for table_row in tables:
                table = _quote_identifier(table_row["name"])
                columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
                json_columns = [col["name"] for col in columns if col["name"] in {"payload", "location", "metadata"}]
                for column in json_columns:
                    quoted = _quote_identifier(column)
                    for row in connection.execute(f"SELECT rowid AS record_id, {quoted} AS value FROM {table}").fetchall():
                        if not isinstance(row["value"], str) or not row["value"].lstrip().startswith(("{", "[")):
                            continue
                        original = json.loads(row["value"])
                        updated = _rewrite(original, roots, target)
                        if updated == original:
                            continue
                        connection.execute(
                            f"UPDATE {table} SET {quoted} = ? WHERE rowid = ?",
                            (json.dumps(updated, ensure_ascii=False), row["record_id"]),
                        )
                        changed += 1
    # Write only after the database transaction commits. A failed marker write
    # can safely retry; neither hashes nor identities/revisions are regenerated.
    if roots or marker.exists():
        temporary = marker.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"schemaVersion": 1, "dataRoot": str(target)}), encoding="utf-8")
        temporary.replace(marker)
    if changed:
        logger.info("Rebased %d owned runtime path records in the moved snapshot.", changed)
    return changed
