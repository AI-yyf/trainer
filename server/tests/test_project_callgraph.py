"""P1 项目理解深化验收 — 调用链解析 + git-diff 改动影响面 (callgraph).

外部评估 P1 "完整 GitHub 项目理解能力" 的剩余面:
- 函数级 caller/callee 边 (Python 函数级; brace 语言诚实的文件级 caller)
- git diff → 变更符号 (含 removed) → 受影响调用方 (带跳数, 有界)
- GET /project/impact (治理: resource_id 或托管 lane) + Agent 工具
"""

from __future__ import annotations

import asyncio
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
        app_name="Trainer CallGraph Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-callgraph.db",
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


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c", "user.email=trainer@test",
        "-c", "user.name=Trainer",
        "commit", "-m", message,
    )


def _init_fixture_repo(repo: Path) -> str:
    """utils.format_name ← service.handle ← main (module-level call)."""

    repo.mkdir(parents=True, exist_ok=True)
    files = {
        "utils.py": (
            "def format_name(name: str) -> str:\n"
            "    return name.strip().title()\n"
            "\n"
            "def legacy_render(name: str) -> str:\n"
            "    return f'[{name}]'\n"
        ),
        "service.py": (
            "from utils import format_name, legacy_render\n"
            "\n"
            "\n"
            "def handle(name: str) -> str:\n"
            "    return format_name(name)\n"
            "\n"
            "def render(name: str) -> str:\n"
            "    return legacy_render(name)\n"
        ),
        "main.py": (
            "from service import handle\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    print(handle('ada'))\n"
        ),
    }
    for relative, text in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo, "init", "-b", "main")
    _commit_all(repo, "fixture")
    return _git(repo, "rev-parse", "HEAD")


def test_callgraph_function_level_edges(tmp_path: Path) -> None:
    from app.project.callgraph import build_call_graph
    from app.project.symbols import build_repo_index

    repo = tmp_path / "repos" / "graph-repo"
    _init_fixture_repo(repo)
    repo_index = build_repo_index(repo)
    graph = build_call_graph(repo, repo_index)

    # Function-level edge: service.handle → utils.format_name.
    edge_pairs = {
        (e.caller_symbol, e.callee_symbol, e.caller_kind)
        for e in graph.edges
    }
    assert ("handle", "format_name", "function") in edge_pairs
    assert ("render", "legacy_render", "function") in edge_pairs
    # Module-level call (main.py top-level handle()) → honest file-level caller.
    assert any(
        e.caller_kind == "file" and e.caller_file == "main.py" and e.callee_symbol == "handle"
        for e in graph.edges
    )
    # Reverse index: callers of format_name resolve to service.handle.
    callers = {e.caller_symbol for e in graph.callers_by_symbol.get("format_name", [])}
    assert "handle" in callers


def test_change_impact_working_tree_and_removed_symbols(tmp_path: Path) -> None:
    """改动影响面: working-tree diff → changed symbols → affected callers."""

    from app.project.callgraph import build_call_graph, compute_change_impact
    from app.project.symbols import build_repo_index

    repo = tmp_path / "repos" / "impact-repo"
    _init_fixture_repo(repo)

    # Working-tree change: rewrite utils.py, REMOVING legacy_render.
    (repo / "utils.py").write_text(
        "def format_name(name: str) -> str:\n    return name.strip().title()\n",
        encoding="utf-8",
    )
    repo_index = build_repo_index(repo)
    graph = build_call_graph(repo, repo_index)
    impact = compute_change_impact(repo, repo_index, graph)

    assert impact.changed_files == ["utils.py"]
    assert "format_name" in impact.changed_symbols
    # Removed symbol detection needs the old blob → since is empty for the
    # working tree, so removed_symbols stay empty there (honest limitation).
    assert impact.removed_symbols == []

    # With a since commit the removed symbol is detected and its caller flagged.
    since = _git(repo, "rev-parse", "HEAD")
    _commit_all(repo, "remove legacy_render")
    (repo / "utils.py").write_text(
        "def format_name(name: str) -> str:\n    return name.strip().title()\n",
        encoding="utf-8",
    )
    repo_index2 = build_repo_index(repo)
    graph2 = build_call_graph(repo, repo_index2)
    impact2 = compute_change_impact(repo, repo_index2, graph2, since=since)
    assert "legacy_render" in impact2.removed_symbols
    caller_keys = {(c["caller_file"], c["caller_symbol"]) for c in impact2.affected_callers}
    assert ("service.py", "render") in caller_keys
    # Transitive: handle (changed-file symbol) affects main.py's file-level caller.
    assert any(c["caller_file"] == "main.py" for c in impact2.affected_callers)
    assert all(1 <= c["hops"] <= 2 for c in impact2.affected_callers)

    # Depth 1 narrows the closure (no main.py file-level caller via transit).
    impact_d1 = compute_change_impact(repo, repo_index2, graph2, since=since, depth=1)
    assert impact_d1.affected_callers
    assert all(c["hops"] == 1 for c in impact_d1.affected_callers)

    # Clean tree (working tree == HEAD) → empty impact.
    impact_clean = compute_change_impact(repo, repo_index2, graph2)
    assert impact_clean.changed_files == []
    assert impact_clean.affected_callers == []


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is required for the impact route fixture")
def test_project_impact_route_governance_and_payload(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    repo = tmp_path / "repos" / "route-repo"
    _init_fixture_repo(repo)
    (repo / "utils.py").write_text(
        "def format_name(name: str) -> str:\n    return name.strip().title()\n",
        encoding="utf-8",
    )

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, "ws-impact")
        imported = client.post(
            "/project/import/local",
            json={"workspace_id": "ws-impact", "path": str(repo)},
        )
        assert imported.status_code == 200, imported.text
        resource_id = imported.json()["resource_id"]

        impact = client.get(
            "/project/impact",
            params={"workspace_id": "ws-impact", "resource_id": resource_id, "depth": 2},
        )
        assert impact.status_code == 200, impact.text
        payload = impact.json()
        assert payload["ok"] is True
        assert payload["basis"]
        # legacy_render was removed before import → its call site is unresolved.
        assert payload["callgraph"]["edge_count"] >= 2
        assert payload["callgraph"]["unresolved_caller_count"] >= 1
        caller_files = {c["caller_file"] for c in payload["affected_callers"]}
        assert "service.py" in caller_files

        # Governance: bare path outside the managed lane is refused.
        forbidden = client.get(
            "/project/impact",
            params={"workspace_id": "ws-impact", "path": str(repo)},
        )
        assert forbidden.status_code == 403

        # Unknown resource → 404; missing identifiers → 400.
        missing = client.get(
            "/project/impact",
            params={"workspace_id": "ws-impact", "resource_id": "resource-none"},
        )
        assert missing.status_code == 404
        no_id = client.get("/project/impact", params={"workspace_id": "ws-impact"})
        assert no_id.status_code == 400


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is required for the agent tool fixture")
def test_analyze_project_impact_agent_tool(tmp_path: Path) -> None:
    from app.llm.tools import ToolContext, _handle_analyze_project_impact

    workspace_root = tmp_path / "workspace"
    repo = tmp_path / "repos" / "tool-repo"
    _init_fixture_repo(repo)
    (repo / "service.py").write_text(
        "from utils import format_name, legacy_render\n\n\n"
        "def handle(name: str) -> str:\n    return format_name(name)\n"
        "\ndef render(name: str) -> str:\n    return legacy_render(name)\n"
        "\ndef handle_v2(name: str) -> str:\n    return format_name(name) + '!'\n",
        encoding="utf-8",
    )

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, "ws-tool")
        imported = client.post(
            "/project/import/local",
            json={"workspace_id": "ws-tool", "path": str(repo)},
        )
        assert imported.status_code == 200, imported.text
        runtime = client.app.state.runtime
        context = ToolContext(runtime=runtime, workspace_id="ws-tool")

        result = asyncio.run(_handle_analyze_project_impact(context, {}))
        assert result["ok"] is True
        assert result["callgraph"]["edge_count"] >= 3
        assert "handle_v2" in result["changed_symbols"]
        caller_symbols = {c["caller_symbol"] for c in result["affected_callers"]}
        assert "main.py" in caller_symbols or "main.py" in {
            c["caller_file"] for c in result["affected_callers"]
        }

        unknown = asyncio.run(
            _handle_analyze_project_impact(context, {"resource_id": "resource-none"})
        )
        assert unknown["ok"] is False
        assert unknown["error"] == "project_not_found"
