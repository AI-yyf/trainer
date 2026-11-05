"""Incremental project update: Git Diff → stale symbol detection → surgical re-index.

When a repository's HEAD advances, only the files touched by the diff need
re-indexing. This module detects those files, surgically updates the symbol
index, and returns a change summary so callers can report what actually
changed without re-reading the entire repository (P2 §六 增量更新).
"""

from __future__ import annotations

import subprocess  # noqa: S404 - git is invoked with an argv list, no shell
from pathlib import Path
from typing import Any

from app.project.symbols import (
    SOURCE_SUFFIXES,
    extract_symbols,
)

_MAX_DIFF_FILES = 500


def _git(args: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def current_commit(repo_root: Path) -> str:
    return _git(["rev-parse", "HEAD"], repo_root)


def detect_changed_files(
    repo_root: Path,
    old_commit: str,
    new_commit: str,
) -> list[str]:
    """Return POSIX-relative paths changed between two commits."""

    if old_commit == new_commit:
        return []
    raw = _git(
        ["diff", "--name-only", f"{old_commit}..{new_commit}"],
        repo_root,
    )
    if not raw:
        return []
    paths: list[str] = []
    for line in raw.splitlines():
        cleaned = line.strip().replace("\\", "/")
        if cleaned and cleaned not in paths:
            paths.append(cleaned)
    return paths[:_MAX_DIFF_FILES]


def update_symbol_index_incremental(
    repo_root: Path,
    old_symbols: list[dict[str, Any]],
    changed_paths: list[str],
) -> dict[str, Any]:
    """Surgically update the symbol table for changed files only.

    Returns ``{"symbols": [...], "added": N, "removed": N, "unchanged_files": N}``
    where ``symbols`` is the new full symbol list (bounded to 2000 entries),
    ready to be written into the symbol-index artifact.
    """

    changed_set = set(changed_paths)
    # Keep symbols from files that did not change.
    surviving: list[dict[str, Any]] = [
        symbol for symbol in old_symbols if symbol.get("path") not in changed_set
    ]
    # Re-extract symbols only for changed source files.
    added = 0
    removed = len(old_symbols) - len(surviving)
    for relative in sorted(changed_set):
        absolute = repo_root / relative
        if not absolute.is_file():
            continue  # deleted file
        if absolute.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        new_symbols = extract_symbols(absolute)
        for symbol in new_symbols:
            symbol.path = relative
        surviving.extend(
            {"path": s.path, "name": s.name, "line": s.line, "kind": s.kind}
            for s in new_symbols
        )
        added += len(new_symbols)
    surviving.sort(key=lambda s: (s.get("path", ""), s.get("line", 0)))
    return {
        "symbols": surviving[:2_000],
        "added": added,
        "removed": removed,
        "unchanged_files": len(
            {s.get("path") for s in old_symbols} - changed_set
        ),
    }


def refresh_project(
    repo_root: Path,
    old_commit: str,
    *,
    old_symbols: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pull latest, detect the diff, surgically update the symbol index.

    This is the P2 "版本更新" acceptance entry point: the repository HEAD
    advances, only changed files are re-extracted, and the caller receives
    a summary of what changed for reporting.
    """

    _git(["pull", "--ff-only"], repo_root)
    new_commit = current_commit(repo_root)
    if not new_commit:
        return {"ok": False, "error": "Could not resolve the new HEAD commit."}
    changed = detect_changed_files(repo_root, old_commit, new_commit)
    if not changed:
        return {
            "ok": True,
            "old_commit": old_commit,
            "new_commit": new_commit,
            "changed_files": [],
            "symbols_added": 0,
            "symbols_removed": 0,
            "symbol_count": len(old_symbols),
            "updated": False,
        }
    updated_index = update_symbol_index_incremental(
        repo_root, old_symbols, changed
    )
    return {
        "ok": True,
        "old_commit": old_commit,
        "new_commit": new_commit,
        "changed_files": changed,
        "symbols_added": updated_index["added"],
        "symbols_removed": updated_index["removed"],
        "symbol_count": len(updated_index["symbols"]),
        "updated": True,
    }
