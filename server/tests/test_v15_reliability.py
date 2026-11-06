"""v1.5 P0 可靠性 — importer 全量注册 + incremental git 失败显式化。

失败优先：以下行为在修复前分别是
- importer 只注册前 100 个 source_items（第 101 个文件永不可索引/搜索）；
- incremental 的 git diff 失败返回空列表，refresh_project 报 ok=True,updated=False。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.project.incremental import (
    IncrementalUpdateError,
    detect_changed_files,
    refresh_project,
)
from app.project.symbols import build_repo_index

GIT_AVAILABLE = __import__("shutil").which("git") is not None


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer v15 Reliability",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-v15-reliability.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _init_repo_with_files(repo: Path, count: int) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    for number in range(count):
        target = repo / "pkg" / f"mod_{number:03d}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"def sentinel_{number:03d}():\n    return {number}\n", encoding="utf-8")
    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", "fixture")
    return _git(repo, "rev-parse", "HEAD")


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git fixture")
def test_import_registers_every_file_beyond_the_old_100_cut(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    repo = tmp_path / "repos" / "many-files"
    _init_repo_with_files(repo, 120)

    with build_client(tmp_path) as client:
        workspace_root.mkdir()
        client.post(
            "/session/start",
            json={"workspace_id": "ws-v15", "workspace_name": "ws-v15", "workspace_path": str(workspace_root)},
        )
        imported = client.post("/project/import/local", json={"workspace_id": "ws-v15", "path": str(repo)})
        assert imported.status_code == 200, imported.text
        payload = imported.json()
        assert payload["source_item_count"] == 120, "all files must register, not the first 100"
        assert payload["index_status"] == "indexed"

        runtime = client.app.state.runtime
        api_record = next(
            item
            for item in runtime.resource_service.repository.list_resources("ws-v15")
            if item.id == payload["resource_id"]
        )
        assert len(api_record.source_items) == 120
        registry_record = runtime.resource_service.registry.get(payload["resource_id"])
        assert registry_record.metadata.get("folder_item_indexed") == 120
        assert not registry_record.metadata.get("folder_item_truncated")

        # File #117 must be searchable — impossible before the fix.
        found = client.post(
            "/resource/search",
            json={"workspace_id": "ws-v15", "query": "sentinel 117", "top_k": 5},
        )
        assert found.status_code == 200, found.text
        assert found.json().get("hits"), "file beyond the old 100-item cut must be indexed and searchable"


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git fixture")
def test_git_failure_is_never_reported_as_no_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repos" / "diff-repo"
    commit = _init_repo_with_files(repo, 3)

    with pytest.raises(IncrementalUpdateError, match="diff"):
        detect_changed_files(repo, "0000000000000000000000000000000000000000", commit)

    # A non-git directory must fail loudly, not return [].
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(IncrementalUpdateError):
        detect_changed_files(plain, commit, commit + "0")


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git fixture")
def test_refresh_project_exposes_symbols_only_on_success(tmp_path: Path) -> None:
    repo = tmp_path / "repos" / "refresh-repo"
    commit = _init_repo_with_files(repo, 4)
    old_symbols = build_repo_index(repo).to_payload()["symbols"]

    # refresh_project pulls first; a repo without an upstream legitimately
    # fails that step, so give it a real (bare) origin.
    origin = tmp_path / "repos" / "refresh-origin.git"
    _git(tmp_path, "init", "--bare", str(origin))
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")

    (repo / "pkg" / "mod_001.py").write_text(
        "def sentinel_001():\n    return 1\n\ndef extra_symbol():\n    return 2\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", "change")
    _git(repo, "push", "origin", "main")

    result = refresh_project(repo, commit, old_symbols=old_symbols)
    assert result["ok"] is True
    assert result["updated"] is True
    assert result["changed_files"] == ["pkg/mod_001.py"]
    assert any(s["name"] == "extra_symbol" for s in result["symbols"])

    # A local repo with no upstream is not an update failure: the diff is
    # still valid and the state is explicit.
    local_only = tmp_path / "repos" / "no-origin"
    _init_repo_with_files(local_only, 2)
    local_result = refresh_project(
        local_only, _git(local_only, "rev-parse", "HEAD"), old_symbols=[]
    )
    assert local_result["ok"] is True
    assert local_result["pull"] == "skipped_no_upstream"
    assert local_result["updated"] is False

    # A real pull failure (upstream configured but unreachable) stays fatal.
    unreachable = tmp_path / "repos" / "unreachable"
    _init_repo_with_files(unreachable, 2)
    _git(unreachable, "remote", "add", "origin", str(tmp_path / "repos" / "missing.git"))
    _git(unreachable, "config", "branch.main.remote", "origin")
    _git(unreachable, "config", "branch.main.merge", "refs/heads/main")
    failed = refresh_project(unreachable, _git(unreachable, "rev-parse", "HEAD"), old_symbols=[])
    assert failed["ok"] is False
    assert failed["error"] == "git_pull_failed"
    assert "symbols" not in failed
