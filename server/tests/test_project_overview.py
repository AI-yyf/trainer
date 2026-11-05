"""P2 深化 acceptance: 项目概览 Artifact + Git SHA→Evidence + 项目问答 agent tools."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app

GIT_AVAILABLE = shutil.which("git") is not None


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer P2 Overview Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-p2-overview.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def start_session(client: TestClient, workspace_root: Path, workspace_id: str) -> None:
    workspace_root.mkdir(parents=True, exist_ok=True)
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": workspace_id,
            "workspace_path": str(workspace_root),
        },
    )
    assert response.status_code == 200, response.text


def _git(repo_dir: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _init_fixture_repo(repo_dir: Path) -> str:
    """Tiny repo with real cross-module imports + a __main__ entry point."""

    repo_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "main.py": (
            "from trainer_workspace.classifier import classify_heuristic\n\n"
            'if __name__ == "__main__":\n'
            "    print(classify_heuristic('demo'))\n"
        ),
        "trainer_workspace/classifier.py": (
            "from resources.canonical import digest_document\n\n\n"
            "def classify_heuristic(folder: str) -> str:\n"
            "    return digest_document(folder)\n"
        ),
        "resources/canonical.py": (
            "def digest_document(path: str) -> str:\n"
            "    return f'canonical:{path}'\n"
        ),
        "README.md": "# overview repo\n",
    }
    for relative, text in files.items():
        target = repo_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "add", ".")
    _git(
        repo_dir,
        "-c", "user.email=trainer@test",
        "-c", "user.name=Trainer",
        "commit", "-m", "fixture",
    )
    return _git(repo_dir, "rev-parse", "HEAD")


def test_build_project_overview_modules_edges_and_mermaid(tmp_path: Path) -> None:
    from app.project.overview import (
        build_project_overview,
        render_overview_markdown,
        write_overview_artifact,
    )
    from app.project.symbols import build_repo_index

    repo_root = tmp_path / "repos" / "overview-repo"
    commit_sha = _init_fixture_repo(repo_root)
    repo_index = build_repo_index(repo_root)

    overview = build_project_overview(
        repo_root,
        repo_index,
        repo_url="https://github.com/example/overview-repo",
        commit_sha=commit_sha,
        branch="main",
    )
    assert overview.commit_sha == commit_sha
    assert overview.file_count == 4
    assert overview.symbol_count == 2

    module_names = {m["module"] for m in overview.modules}
    assert module_names == {".", "resources", "trainer_workspace"}

    # File-level internal edges resolve across modules.
    edge_pairs = {(e["src"], e["dst"]) for e in overview.edges}
    assert ("main.py", "trainer_workspace/classifier.py") in edge_pairs
    assert ("trainer_workspace/classifier.py", "resources/canonical.py") in edge_pairs

    # Module-level aggregated edges: . → trainer_workspace → resources.
    module_edges = {(e["src"], e["dst"]) for e in overview.module_edges}
    assert (".", "trainer_workspace") in module_edges
    assert ("trainer_workspace", "resources") in module_edges

    # Entry point detection: main.py (conventional) + __main__ guard.
    assert "main.py" in overview.entry_points

    # Mermaid 架构图 renders with nodes and edges.
    artifact_path = write_overview_artifact(tmp_path / "overview.md", overview)
    markdown = render_overview_markdown(overview)
    assert artifact_path.is_file()
    assert "```mermaid" in markdown
    assert "graph LR" in markdown
    assert "trainer_workspace" in markdown
    assert f"commit_sha: {json.dumps(commit_sha)}" in markdown


def test_evidence_git_snapshot_and_non_repo(tmp_path: Path) -> None:
    from app.project.overview import evidence_git_snapshot

    repo_root = tmp_path / "repos" / "snapshot-repo"
    commit_sha = _init_fixture_repo(repo_root)

    snapshot = evidence_git_snapshot(repo_root)
    assert snapshot["commit_sha"] == commit_sha
    assert snapshot["branch"] == "main"
    assert snapshot["dirty"] is False

    # A working-tree edit flips dirty.
    (repo_root / "README.md").write_text("# dirty\n", encoding="utf-8")
    assert evidence_git_snapshot(repo_root)["dirty"] is True

    # A plain directory is not a repo: empty snapshot, never fabricated.
    plain = tmp_path / "plain"
    plain.mkdir()
    assert evidence_git_snapshot(plain) == {"commit_sha": "", "branch": "", "dirty": False}


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is required for the overview fixture")
def test_project_overview_route_and_artifact(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    repo_dir = tmp_path / "repos" / "overview-repo"
    commit_sha = _init_fixture_repo(repo_dir)

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, "ws-overview")
        imported = client.post(
            "/project/import/local",
            json={"workspace_id": "ws-overview", "path": str(repo_dir)},
        )
        assert imported.status_code == 200, imported.text
        resource_id = imported.json()["resource_id"]

        overview = client.post(
            "/project/overview",
            json={"workspace_id": "ws-overview", "resource_id": resource_id},
        )
        assert overview.status_code == 200, overview.text
        payload = overview.json()
        assert payload["ok"] is True
        assert payload["commit_sha"] == commit_sha
        assert payload["module_count"] == 3
        assert payload["edge_count"] == 2
        assert "main.py" in payload["entry_points"]

        artifact_path = Path(payload["artifact_path"])
        assert artifact_path.is_file()
        artifact_text = artifact_path.read_text(encoding="utf-8")
        assert "```mermaid" in artifact_text
        assert commit_sha in artifact_text

        stored = client.get(
            f"/project/overview/{resource_id}",
            params={"workspace_id": "ws-overview"},
        )
        assert stored.status_code == 200, stored.text
        assert "graph LR" in stored.json()["content"]

        # Governance: a bare path outside the managed lane is refused.
        forbidden = client.post(
            "/project/overview",
            json={"workspace_id": "ws-overview", "path": str(repo_dir)},
        )
        assert forbidden.status_code == 403


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is required for the evidence fixture")
def test_evidence_pins_git_sha_server_side(tmp_path: Path) -> None:
    """Git SHA→Evidence: the commit comes from the artifact, not the client."""

    workspace_root = tmp_path / "workspace"
    repo_dir = tmp_path / "repos" / "evidence-repo"
    commit_sha = _init_fixture_repo(repo_dir)

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, "ws-evidence")
        imported = client.post(
            "/project/import/local",
            json={"workspace_id": "ws-evidence", "path": str(repo_dir)},
        )
        assert imported.status_code == 200, imported.text
        resource_id = imported.json()["resource_id"]

        started = client.post(
            "/training/attempt/start",
            json={"workspace_id": "ws-evidence", "card_id": "card-git-sha"},
        )
        assert started.status_code == 200, started.text
        attempt_id = started.json()["attempt"]["attempt_id"]

        evidence = client.post(
            "/training/attempt/evidence",
            json={
                "attempt_id": attempt_id,
                "artifact_hash": "a" * 64,
                "result": "passed",
                "resource_id": resource_id,
            },
        )
        assert evidence.status_code == 200, evidence.text
        record = evidence.json()["evidence"]
        assert record["resource_id"] == resource_id
        assert record["resource_git_sha"] == commit_sha

        # A resource without a project artifact carries no fabricated SHA.
        doc = workspace_root / "notes.md"
        doc.write_text("# plain note\n", encoding="utf-8")
        upload = client.post(
            "/resource/upload",
            json={
                "workspace_id": "ws-evidence",
                "kind": "markdown",
                "name": "Plain Notes",
                "source": str(doc),
            },
        )
        assert upload.status_code == 200, upload.text
        plain_resource_id = upload.json()["id"]

        started2 = client.post(
            "/training/attempt/start",
            json={"workspace_id": "ws-evidence", "card_id": "card-plain"},
        )
        attempt_id2 = started2.json()["attempt"]["attempt_id"]
        evidence2 = client.post(
            "/training/attempt/evidence",
            json={
                "attempt_id": attempt_id2,
                "artifact_hash": "b" * 64,
                "result": "passed",
                "resource_id": plain_resource_id,
            },
        )
        assert evidence2.status_code == 200, evidence2.text
        assert evidence2.json()["evidence"]["resource_git_sha"] is None


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is required for the agent tool fixture")
def test_project_qa_agent_tools(tmp_path: Path) -> None:
    """read_project_symbol / list_project_modules answer from the real index."""

    from app.llm.tools import (
        ToolContext,
        _handle_list_project_modules,
        _handle_read_project_symbol,
    )

    workspace_root = tmp_path / "workspace"
    repo_dir = tmp_path / "repos" / "qa-repo"
    commit_sha = _init_fixture_repo(repo_dir)

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, "ws-qa")
        imported = client.post(
            "/project/import/local",
            json={"workspace_id": "ws-qa", "path": str(repo_dir)},
        )
        assert imported.status_code == 200, imported.text
        runtime = client.app.state.runtime
        context = ToolContext(runtime=runtime, workspace_id="ws-qa")

        modules = asyncio.run(_handle_list_project_modules(context, {}))
        assert modules["ok"] is True
        assert modules["commit_sha"] == commit_sha
        module_names = {m["module"] for m in modules["modules"]}
        assert module_names == {".", "resources", "trainer_workspace"}
        trainer_module = next(m for m in modules["modules"] if m["module"] == "trainer_workspace")
        assert trainer_module["symbol_count"] == 1

        symbol = asyncio.run(_handle_read_project_symbol(context, {"name": "classify_heuristic"}))
        assert symbol["ok"] is True
        assert symbol["path"] == "trainer_workspace/classifier.py"
        assert symbol["line"] == 4
        assert symbol["commit_sha"] == commit_sha
        assert "classify_heuristic" in (symbol["excerpt"] or "")

        # Prefix fallback + not-found carries suggestions.
        prefix = asyncio.run(_handle_read_project_symbol(context, {"name": "classify_"}))
        assert prefix["ok"] is True
        missing = asyncio.run(_handle_read_project_symbol(context, {"name": "no_such_thing"}))
        assert missing["ok"] is False
        assert missing["error"] == "symbol_not_found"

        # Project resolution failure is explicit, never silent.
        unknown = asyncio.run(
            _handle_read_project_symbol(context, {"name": "x", "resource_id": "resource-none"})
        )
        assert unknown["ok"] is False
        assert unknown["error"] == "project_not_found"
