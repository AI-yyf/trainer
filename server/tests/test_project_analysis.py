"""Phase 2 — Analysis Adapter 验收: 真实 AST 证据 + 诚实降级。

失败优先：以下断言在只有 regex callgraph 时会失败——
- tree-sitter 不可用时 provider 必须 available=False 且零边（绝不虚构）；
- 可用时 call-site 证据等级 syntax_exact，且与 regex 近似边合并时取高等级；
- LSP/SCIP 未配置时如实报告 reason。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.project.analysis_adapter import (
    AdapterEdge,
    AdapterReport,
    LspScipProvider,
    RegexCallGraphProvider,
    TreeSitterPythonProvider,
    run_analysis_adapters,
)
from app.project.symbols import build_repo_index

GIT = __import__("shutil").which("git") is not None


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "utils.py").write_text(
        "def format_name(name: str) -> str:\n    return name.strip().title()\n",
        encoding="utf-8",
    )
    (repo / "service.py").write_text(
        "from utils import format_name\n\n\ndef handle(name: str) -> str:\n    return format_name(name)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", "x"],
        capture_output=True,
    )
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()


def test_tree_sitter_provider_reports_syntax_exact_edges(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    index = build_repo_index(repo)
    report = TreeSitterPythonProvider().run(repo, index)
    if not report.available:
        pytest.skip(f"tree-sitter grammar unavailable: {report.reason}")
    assert report.confidence == "syntax_exact"
    assert any(
        edge.caller_symbol == "handle"
        and edge.callee_symbol == "format_name"
        and edge.confidence == "syntax_exact"
        for edge in report.edges
    )
    # Honest limitations are always stated.
    assert report.limitations
    assert any("name-based" in line or "name" in line for line in report.limitations)


def test_unavailable_providers_never_fabricate_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.project.analysis_adapter as adapter

    repo = tmp_path / "repo"
    _init_repo(repo)
    index = build_repo_index(repo)

    monkeypatch.setattr(adapter, "_tree_sitter_available", lambda: (False, "grammar missing"))
    tree = adapter.TreeSitterPythonProvider().run(repo, index)
    assert tree.available is False
    assert tree.reason == "grammar missing"
    assert tree.edges == []

    lsp = LspScipProvider().run(repo, index)
    assert lsp.available is False
    assert "No LSP" in lsp.reason
    assert lsp.edges == []


def test_merged_edges_prefer_higher_evidence_level(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    index = build_repo_index(repo)

    class ExactOnly:
        name = "fake-exact"

        def run(self, repo_root: Path, repo_index) -> AdapterReport:  # type: ignore[no-untyped-def]
            return AdapterReport(
                name=self.name,
                available=True,
                confidence="syntax_exact",
                edges=[
                    AdapterEdge(
                        caller_file="service.py",
                        caller_symbol="handle",
                        callee_symbol="format_name",
                        callee_file="utils.py",
                        confidence="syntax_exact",
                        provider=self.name,
                    )
                ],
            )

    merged = run_analysis_adapters(
        repo, index, providers=(RegexCallGraphProvider(), ExactOnly(), LspScipProvider())
    )
    handle_edges = [
        edge
        for edge in merged["merged_edges"]
        if edge["caller_symbol"] == "handle" and edge["callee_symbol"] == "format_name"
    ]
    assert len(handle_edges) == 1
    assert handle_edges[0]["confidence"] == "syntax_exact"
    assert handle_edges[0]["provider"] == "fake-exact"
    providers = {item["provider"]: item for item in merged["providers"]}
    assert providers["regex-callgraph"]["available"] is True
    assert providers["lsp-scip"]["available"] is False
    assert merged["limitation_summary"], "limitations must surface, not be hidden"


@pytest.mark.skipif(not GIT, reason="git fixture")
def test_analysis_route_reports_provider_availability(tmp_path: Path) -> None:
    settings = AppSettings(
        app_name="Trainer Analysis Route",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-analysis.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    repo = tmp_path / "repos" / "analysis-repo"
    _init_repo(repo)

    with TestClient(create_app(settings)) as client:
        (tmp_path / "workspace").mkdir()
        client.post(
            "/session/start",
            json={
                "workspace_id": "ws-analysis",
                "workspace_name": "ws-analysis",
                "workspace_path": str(tmp_path / "workspace"),
            },
        )
        imported = client.post(
            "/project/import/local", json={"workspace_id": "ws-analysis", "path": str(repo)}
        )
        assert imported.status_code == 200, imported.text
        resource_id = imported.json()["resource_id"]

        analysis = client.get(
            "/project/analysis", params={"workspace_id": "ws-analysis", "resource_id": resource_id}
        )
        assert analysis.status_code == 200, analysis.text
        payload = analysis.json()
        assert payload["ok"] is True
        provider_names = {item["provider"] for item in payload["providers"]}
        assert {"regex-callgraph", "tree-sitter-python", "lsp-scip"} <= provider_names
        for item in payload["providers"]:
            if not item["available"]:
                assert item["reason"], "unavailable providers must explain why"
            else:
                assert item["limitations"], "available providers must state limits"

        forbidden = client.get(
            "/project/analysis", params={"workspace_id": "ws-analysis", "path": str(repo)}
        )
        assert forbidden.status_code == 403
        missing = client.get("/project/analysis", params={"workspace_id": "ws-analysis"})
        assert missing.status_code == 400


def test_project_summary_route_is_single_bounded_call(tmp_path: Path) -> None:
    settings = AppSettings(
        app_name="Trainer Project Summary",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-summary.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    repo = tmp_path / "repos" / "summary-repo"
    _init_repo(repo)

    with TestClient(create_app(settings)) as client:
        (tmp_path / "workspace").mkdir()
        client.post(
            "/session/start",
            json={
                "workspace_id": "ws-summary",
                "workspace_name": "ws-summary",
                "workspace_path": str(tmp_path / "workspace"),
            },
        )
        imported = client.post(
            "/project/import/local", json={"workspace_id": "ws-summary", "path": str(repo)}
        )
        assert imported.status_code == 200, imported.text
        resource_id = imported.json()["resource_id"]

        summary = client.get(
            "/project/summary", params={"workspace_id": "ws-summary", "resource_id": resource_id}
        )
        assert summary.status_code == 200, summary.text
        payload = summary.json()
        assert payload["ok"] is True
        assert payload["file_count"] == 2
        assert payload["symbol_count"] >= 2
        assert payload["modules"], "module map must be present"
        assert len(payload["modules"]) <= 8
        assert payload["callgraph"]["edge_count"] >= 1
        providers = {item["provider"]: item for item in payload["analysis"]}
        assert "regex-callgraph" in providers
        assert providers["lsp-scip"]["available"] is False
        assert providers["lsp-scip"]["reason"]
        assert isinstance(payload["limitations"], list)

        forbidden = client.get(
            "/project/summary", params={"workspace_id": "ws-summary", "path": str(repo)}
        )
        assert forbidden.status_code == 403


def test_lsp_python_provider_resolves_real_references(tmp_path: Path) -> None:
    import importlib.util

    if importlib.util.find_spec("pylsp") is None:
        pytest.skip("python-lsp-server not installed")

    from app.project.analysis_adapter import LspPythonProvider

    repo = tmp_path / "repo"
    _init_repo(repo)
    index = build_repo_index(repo)
    report = LspPythonProvider().run(repo, index)
    assert report.available is True
    assert report.confidence == "lsp_reference"
    pairs = {(edge.caller_file, edge.callee_symbol, edge.confidence) for edge in report.edges}
    assert ("service.py", "format_name", "lsp_reference") in pairs
    assert report.limitations, "real LSP must state its bounds"


def test_lsp_python_provider_reports_unavailable_without_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.project.analysis_adapter import LspPythonProvider

    repo = tmp_path / "repo"
    _init_repo(repo)
    index = build_repo_index(repo)
    provider = LspPythonProvider()
    monkeypatch.setattr(provider, "_server_available", lambda: (False, "python-lsp-server is not installed"))
    report = provider.run(repo, index)
    assert report.available is False
    assert report.reason == "python-lsp-server is not installed"
    assert report.edges == []


def test_merge_prefers_lsp_reference_over_other_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    index = build_repo_index(repo)

    class LspOnly:
        name = "fake-lsp"

        def run(self, repo_root: Path, repo_index) -> AdapterReport:  # type: ignore[no-untyped-def]
            return AdapterReport(
                name=self.name,
                available=True,
                confidence="lsp_reference",
                edges=[
                    AdapterEdge(
                        caller_file="service.py",
                        caller_symbol="handle",
                        callee_symbol="format_name",
                        callee_file="utils.py",
                        confidence="lsp_reference",
                        provider=self.name,
                    )
                ],
            )

    merged = run_analysis_adapters(
        repo, index, providers=(RegexCallGraphProvider(), LspOnly())
    )
    match = [
        edge
        for edge in merged["merged_edges"]
        if edge["caller_file"] == "service.py" and edge["callee_symbol"] == "format_name"
    ]
    assert len(match) == 1
    assert match[0]["confidence"] == "lsp_reference"
    assert match[0]["provider"] == "fake-lsp"
