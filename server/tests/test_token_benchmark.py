"""bench:token acceptance: layered understanding must beat the baselines."""

from __future__ import annotations

import json
from pathlib import Path

from app.benchmarks.token_benchmark import run_token_benchmark

QUERIES = [
    {
        "question": "Where is the workspace classifier heuristic defined?",
        "expect_paths": ["trainer_workspace/classifier.py"],
        "keywords": ["classify", "heuristic", "workspace"],
    },
    {
        "question": "How does the cost ledger record estimated token usage?",
        "expect_paths": ["llm/cost_ledger.py"],
        "keywords": ["cost", "ledger", "token"],
    },
    {
        "question": "Which module ingests documents into canonical markdown?",
        "expect_paths": ["resources/canonical.py", "resources/canonical_store.py"],
        "keywords": ["canonical", "markdown", "ingest"],
    },
    {
        "question": "Where does the agent loop handle tool calls?",
        "expect_paths": ["llm/agent_loop.py"],
        "keywords": ["agent", "loop", "tool"],
    },
]


def _build_fixture_repo(root: Path) -> None:
    """A miniature repo shaped like Trainer: deep dirs, realistic symbols."""

    sources = {
        "trainer_workspace/classifier.py": (
            '"""Classify workspace folders."""\n\n'
            "def classify_heuristic(folder: str) -> str:\n"
            "    return 'existing_engineering'\n\n"
            "class WorkspaceClassifier:\n"
            "    def classify(self, folder: str) -> str:\n"
            "        return classify_heuristic(folder)\n"
        ),
        "llm/cost_ledger.py": (
            '"""Append-only cost ledger."""\n\n'
            "class CostLedger:\n"
            "    def record(self, workspace: str, tokens: int) -> None:\n"
            "        pass\n"
        ),
        "llm/agent_loop.py": (
            "class AgentLoop:\n"
            "    def handle_tool_call(self, name: str) -> str:\n"
            "        return name\n"
        ),
        "resources/canonical.py": (
            "def digest_document(path: str) -> str:\n"
            "    return 'canonical markdown'\n"
        ),
        "resources/canonical_store.py": (
            "class CanonicalStore:\n"
            "    def write(self, path: str, body: str) -> None:\n"
            "        pass\n"
        ),
        "llm/provider_service.py": (
            "class ProviderService:\n"
            "    def chat(self, message: str) -> str:\n"
            "        return message\n"
        ),
        "README.md": "# Trainer\nLearning workspace tooling.\n",
    }
    for relative, text in sources.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    # Scale: filler modules make the naive full-repo dump genuinely large, the
    # way a real repository is. Without them the toy fixture flatters the dump.
    for index in range(24):
        filler = (
            f"# generated filler module {index}\n\n"
            f"class Filler{index}:\n"
            f"    def run_{index}(self, value: str) -> str:\n"
            f"        return value.strip()\n\n"
            f"    def helper_{index}(self, a: int, b: int) -> int:\n"
            f"        return a + b\n\n"
            f"def entry_{index}(payload: dict) -> bool:\n"
            f"    return bool(payload)\n"
        )
        target = root / "services" / f"gen_module_{index:02d}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(filler, encoding="utf-8")
    (root / "node_modules" / "leftpad" / "index.js").parent.mkdir(parents=True, exist_ok=True)
    (root / "node_modules" / "leftpad" / "index.js").write_text("noise", encoding="utf-8")


def test_layered_mode_beats_full_tokens_and_matches_rag_localization(tmp_path: Path) -> None:
    repo = tmp_path / "trainer-fixture"
    _build_fixture_repo(repo)
    report = run_token_benchmark(repo, QUERIES)

    modes = report["modes"]
    assert modes["full_repository"]["tokens"] > modes["layered"]["tokens"]
    assert modes["layered"]["localization_hit_rate"] >= 0.75
    assert report["verdict"]["layered_qualifies"] is True
    # Deterministic symbol index found the expected anchors.
    assert report["repo_symbol_count"] >= 8
    assert report["repo_file_count"] >= 6
    serialized = json.dumps(report)
    assert "node_modules" not in serialized


def test_queries_without_expected_path_still_report_selections(tmp_path: Path) -> None:
    repo = tmp_path / "trainer-fixture"
    _build_fixture_repo(repo)
    report = run_token_benchmark(
        repo,
        [
            {
                "question": "provider service chat behaviour",
                "expect_paths": [],
                "keywords": ["provider", "chat"],
            }
        ],
    )
    assert report["query_count"] == 1
    assert report["modes"]["layered"]["tokens"] > 0


def test_report_is_json_serializable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_fixture_repo(repo)
    report = run_token_benchmark(repo, QUERIES[:1])
    assert isinstance(json.dumps(report), str)
