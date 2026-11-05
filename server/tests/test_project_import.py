"""P2 project import acceptance: clone/register/symbol-index/search."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.project.importer import parse_github_url


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name='Trainer P2 Import Tests',
        host='127.0.0.1',
        port=8765,
        data_dir=tmp_path / 'data',
        database_name='trainer-p2-import.db',
        default_session_stage='intake',
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def start_session(client: TestClient, workspace_root: Path, workspace_id: str) -> str:
    workspace_root.mkdir(parents=True, exist_ok=True)
    response = client.post(
        '/session/start',
        json={
            'workspace_id': workspace_id,
            'workspace_name': workspace_id,
            'workspace_path': str(workspace_root),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()['session_id']

GIT_AVAILABLE = shutil.which("git") is not None


def _init_fixture_repo(repo_dir: Path) -> str:
    repo_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "README.md": "# bench repo\nSmall project used by Trainer P2 tests.\n",
        "trainer_workspace/classifier.py": (
            "def classify_heuristic(folder: str) -> str:\n"
            "    return 'existing_engineering'\n"
        ),
        "resources/canonical.py": (
            "def digest_document(path: str) -> str:\n"
            "    return 'canonical markdown'\n"
        ),
    }
    for relative, text in files.items():
        target = repo_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return completed.stdout.strip()

    git("init", "-b", "main")
    git("add", ".")
    git("-c", "user.email=trainer@test", "-c", "user.name=Trainer", "commit", "-m", "fixture")
    return git("rev-parse", "HEAD")


def test_parse_github_url_accepts_url_tree_and_slug() -> None:
    assert parse_github_url("https://github.com/octocat/Hello-World") == {
        "owner": "octocat",
        "repo": "Hello-World",
        "branch": "",
        "clone_url": "https://github.com/octocat/Hello-World.git",
    }
    parsed = parse_github_url("https://github.com/psf/requests/tree/main")
    assert parsed["repo"] == "requests"
    assert parsed["branch"] == "main"
    assert parse_github_url("psf/requests")["clone_url"] == "https://github.com/psf/requests.git"
    with pytest.raises(ValueError, match="GitHub repository"):
        parse_github_url("https://gitlab.com/a/b")


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is required for the import fixture")
def test_local_repo_import_registers_source_symbol_index_and_search(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    repo_dir = tmp_path / "repos" / "bench-repo"
    commit_sha = _init_fixture_repo(repo_dir)

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, "workspace-p2")
        imported = client.post(
            "/project/import/local",
            json={"workspace_id": "workspace-p2", "path": str(repo_dir)},
        )
        assert imported.status_code == 200, imported.text
        payload = imported.json()
        assert payload["ok"] is True
        assert payload["commit_sha"] == commit_sha
        assert payload["file_count"] >= 3
        # README.md contributes a file but no symbols; two Python defs remain.
        assert payload["symbol_count"] == 2

        artifact = Path(payload["symbol_artifact_path"])
        assert artifact.is_file()
        artifact_payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert artifact_payload["commit_sha"] == commit_sha
        symbol_names = {symbol["name"] for symbol in artifact_payload["symbols"]}
        assert "classify_heuristic" in symbol_names
        assert "digest_document" in symbol_names

        resource_id = payload["resource_id"]
        assert payload["index_status"] == "indexed"

        # 追问/代码定位: FTS search over the imported source must locate the
        # exact file with a line-anchored location.
        located = client.post(
            "/resource/search",
            json={
                "workspace_id": "workspace-p2",
                "query": "classify heuristic folder",
                "top_k": 5,
            },
        )
        assert located.status_code == 200, located.text
        hits = located.json()["hits"]
        assert hits, "expected the imported classifier source to be searchable"
        top = hits[0]
        assert top["resource_id"] == resource_id
        # 代码定位: the FTS snippet must point at the classifier function body.
        assert "classify" in str(top.get("summary", "")).lower()


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is required for the import fixture")
def test_reimporting_same_repo_gets_a_unique_managed_dir(tmp_path: Path) -> None:
    """Re-import is idempotent-safe: unique managed dirs, no clobbering."""

    repo_dir = tmp_path / "repos" / "bench-repo"
    _init_fixture_repo(repo_dir)
    with build_client(tmp_path) as client:
        start_session(client, tmp_path / "workspace", "workspace-p2-dup")
        first = client.post(
            "/project/import/local",
            json={"workspace_id": "workspace-p2-dup", "path": str(repo_dir)},
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/project/import/local",
            json={"workspace_id": "workspace-p2-dup", "path": str(repo_dir)},
        )
        assert second.status_code == 200, second.text
        assert first.json()["repo_root"] != second.json()["repo_root"]
        assert second.json()["resource_id"] != first.json()["resource_id"]
