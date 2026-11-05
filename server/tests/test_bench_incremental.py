"""bench:incremental: re-analysis ≤ 20% of first-run cost (§四)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.benchmarks.incremental_benchmark import run_incremental_benchmark

GIT = __import__("shutil").which("git") is not None


@pytest.mark.skipif(not GIT, reason="git required")
def test_incremental_reanalysis_costs_le_than_20pct_of_full(tmp_path: Path) -> None:
    repo = tmp_path / "bench-repo"
    # Create enough files that a full pass is non-trivial.
    for i in range(20):
        target = repo / f"src/module_{i:02d}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"def function_{i}(value):\n"
            f"    result = value * {i}\n"
            f"    return result\n\n"
            f"class Handler_{i}:\n"
            f"    def handle(self):\n"
            f"        return function_{i}(42)\n",
            encoding="utf-8",
        )
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=T",
         "commit", "-m", "init"],
        capture_output=True,
    )

    result = run_incremental_benchmark(repo)
    assert result["ok"] is True, result
    assert result["incremental_ratio"] <= 0.20
    assert result["full_chars"] > 0
    assert result["incremental_chars"] > 0


def test_bench_provenance_verifiability(tmp_path: Path) -> None:
    """bench:provenance: citation verifiability ≥ 95% (§四 P1 验收)."""

    from app.benchmarks.provenance_benchmark import run_provenance_benchmark

    documents = [
        {
            "filename": "docs/classifier.md",
            "name": "Classifier Guide",
            "kind": "markdown",
            "content": "# Classifier\n\nThe workspace classifier uses heuristic rules.\n\n## Quorum\n\nA majority of replicas must agree.\n",
        },
        {
            "filename": "docs/ledger.md",
            "name": "Cost Ledger Guide",
            "kind": "markdown",
            "content": "# Cost Ledger\n\nToken usage is recorded per workspace.\n\n## Accuracy\n\nEstimates use chars/4.\n",
        },
        {
            "filename": "docs/reader.md",
            "name": "Reader Guide",
            "kind": "markdown",
            "content": "# Reader\n\nThe reader renders canonical markdown.\n",
        },
    ]
    queries = [
        {"query": "classifier heuristic"},
        {"query": "cost ledger"},
        {"query": "canonical markdown"},
    ]
    result = run_provenance_benchmark(tmp_path, documents, queries)
    assert result["total_citations"] >= 3
    assert result["ok"] is True
    assert result["verifiability_rate"] >= 0.95

