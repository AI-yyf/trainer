"""P2 版本更新: Git Diff → incremental symbol index acceptance."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.project.incremental import (
    detect_changed_files,
    refresh_project,
    update_symbol_index_incremental,
)

GIT = shutil.which("git") is not None


def _init(repo: Path, files: dict[str, str]) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")

    def _git(*args: str) -> str:
        r = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True
        )
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    _git("init", "-b", "main")
    _git("add", ".")
    _git("-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", "init")
    return _git("rev-parse", "HEAD")


def _commit(repo: Path, files: dict[str, str | None], message: str = "update") -> str:
    for rel, text in files.items():
        target = repo / rel
        if text is None:
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    r = subprocess.run(
        [
            "git", "-C", str(repo),
            "-c", "user.email=t@t", "-c", "user.name=T",
            "commit", "-m", message,
        ],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()


@pytest.mark.skipif(not GIT, reason="git required")
def test_incremental_detects_changed_files_and_updates_symbols(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    old = _init(repo, {
        "src/calculator.py": "def add(a, b):\n    return a + b\nclass Calculator:\n    def multiply(self, a, b):\n        return a * b\n",
        "src/reader.py": "def read(path):\n    return open(path).read()\n",
    })

    # Advance HEAD: modify calculator.py, add writer.py, delete reader.py
    new = _commit(repo, {
        "src/calculator.py": "def subtract(a, b):\n    return a - b\n",
        "src/writer.py": "def write(path, data):\n    pass\n",
        "src/reader.py": None,
    })
    changed = detect_changed_files(repo, old, new)
    assert "src/calculator.py" in changed
    assert "src/writer.py" in changed
    assert "src/reader.py" in changed

    # Surgical update from old symbol table
    old_symbols = [
        {"path": "src/calculator.py", "name": "add", "line": 1, "kind": "function"},
        {"path": "src/calculator.py", "name": "Calculator", "line": 3, "kind": "class"},
        {"path": "src/reader.py", "name": "read", "line": 1, "kind": "function"},
    ]
    result = update_symbol_index_incremental(repo, old_symbols, changed)
    names = {s["name"] for s in result["symbols"]}
    assert "subtract" in names
    assert "write" in names
    assert "read" not in names
    assert result["added"] > 0
    assert result["removed"] == 3


@pytest.mark.skipif(not GIT, reason="git required")
def test_refresh_project_detects_change_between_commits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    old = _init(repo, {"src/main.py": "def main():\n    pass\n"})
    result = refresh_project(repo, old, old_symbols=[])
    assert result["ok"] is True
    assert result["updated"] is False  # old == current, nothing changed

    # Advance HEAD with a new commit
    _commit(repo, {"src/extra.py": "def extra():\n    pass\n"})
    result2 = refresh_project(repo, old, old_symbols=[])
    assert result2["updated"] is True
    assert "src/extra.py" in result2.get("changed_files", [])
