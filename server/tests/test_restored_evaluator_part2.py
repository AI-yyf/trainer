"""(n) Evaluator: verification of the learner's code is real, bounded and honest about
    what it could not check.

Guarantees covered:
  * evaluation is deterministic and produces valid reports for any task spec and code (property-based);
  * acceptance criteria need real code evidence, not file names or explanations alone;
  * Python verification executes the learner's tests and reports their real outcome;
  * project analysis, call graphs and symbol indexes come from real AST / LSP / git evidence and degrade honestly.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_training_script_verification.py
  * server/tests/test_verification_python.py
  * server/tests/test_practice_subject_routing.py
  * server/tests/test_project_overview.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from app.core.models import EvaluateCurrentFileRequest
from app.evaluator.check_cache import CheckResultCache
from app.evaluator.models import CheckCommand, CheckResult, CheckStatus
from app.evaluator.service import EvaluationPipeline, EvaluatorService, SubprocessCommandRunner
from app.evaluator.verifiers import (
    IDE_CURRENT_FILE_EVIDENCE_SOURCE,
    RUBRIC_DUAL_REVIEW_EVIDENCE_SOURCE,
    literature_pack,
    python_toolchain_pack,
    verify_submission_with_pack,
)

# ---------------------------------------------------------------------------
# Restored from test_training_script_verification.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


class ScriptRunner:
    """Keep unrelated tool availability deterministic; execute the real script."""

    def __init__(self, pytest_status: CheckStatus = CheckStatus.SKIPPED):
        self.pytest_status = pytest_status
        self.script_calls = 0
        self.script_workspaces: list[str] = []

    def run(self, command: CheckCommand) -> CheckResult:
        if command.name == "python-script":
            self.script_calls += 1
            self.script_workspaces.append(command.cwd or "")
            return SubprocessCommandRunner().run(command)
        return CheckResult(
            name=command.name,
            status=self.pytest_status if command.name == "pytest" else CheckStatus.PASSED,
            summary="No tests collected" if command.name == "pytest" else "ok",
        )


def request(code: str, criteria: list[str] | None = None) -> EvaluateCurrentFileRequest:
    return EvaluateCurrentFileRequest(
        session_id="script-test", workspace_id="script-test",
        file_path="/unused/learner/sum_nested.py", language_id="python", content=code,
        verification_python=sys.executable, evaluation_source="training",
        acceptance_criteria=criteria or ["定义 `sum_nested` 并使其对 `[]` 返回 0"],
        expected_symbols=["sum_nested", "[]"],
    )


SCRIPT = '''def sum_nested(values):
    return sum(sum_nested(value) for value in values) if isinstance(values, list) else values

if __name__ == "__main__":
    assert sum_nested([]) == 0
    assert sum_nested([1, [2, [3, 4]], 5]) == 15
    print(sum_nested([]))
    print(sum_nested([1, 2, 3]))
    print(sum_nested([1, [2, [3, 4]], 5]))
'''


@pytest.mark.real_tools
def test_real_script_without_pytest_tests_counts_as_dynamic_verification_and_runs_fresh():
    runner = ScriptRunner()
    service = EvaluatorService(pipeline=EvaluationPipeline(runner=runner))
    for _ in range(2):
        report = service.evaluate_current_file(request(SCRIPT, [
            "定义 `sum_nested` 并使其对 `[]` 返回 0",
            "使用 `python sum_nested.py` 跑通并 print 0、6、15",
        ]))
        assert report.passed, report.summary
        assert next(c for c in report.dynamic_checks if c.id == "python-script").status == "passed"
    assert runner.script_calls == 2
    assert all(not Path(path).exists() for path in runner.script_workspaces)


@pytest.mark.real_tools
@pytest.mark.parametrize("code", [
    SCRIPT.replace("== 15", "== 99"),
    SCRIPT.replace("print(sum_nested([1, 2, 3]))", "print(99)"),
    SCRIPT.replace("print(sum_nested([1, 2, 3]))", "print('debug: 6')"),
])
def test_failed_assertion_or_wrong_stdout_cannot_pass(code):
    report = EvaluatorService(pipeline=EvaluationPipeline(runner=ScriptRunner())).evaluate_current_file(
        request(code, ["使用 `python sum_nested.py` 跑通并 print 0、6、15"])
    )
    assert not report.passed


@pytest.mark.real_tools
def test_real_pytest_failure_still_blocks_a_successful_script():
    report = EvaluatorService(pipeline=EvaluationPipeline(
        runner=ScriptRunner(CheckStatus.FAILED),
    )).evaluate_current_file(request(SCRIPT))
    assert not report.passed
    assert "pytest" in report.summary


@pytest.mark.real_tools
def test_library_module_with_no_entrypoint_still_requires_dynamic_verification():
    runner = ScriptRunner()
    report = EvaluatorService(pipeline=EvaluationPipeline(runner=runner)).evaluate_current_file(
        request(SCRIPT.split('if __name__')[0])
    )
    assert not report.passed
    assert runner.script_calls == 0
    assert "Verification is still required" in report.summary


@pytest.mark.real_tools
def test_cross_file_preservation_is_not_inferred_from_successful_script():
    report = EvaluatorService(pipeline=EvaluationPipeline(runner=ScriptRunner())).evaluate_current_file(
        request(SCRIPT, ["在 `sum_nested.py` 中不修改 `list_pairs.py`"])
    )
    assert not report.passed
    assert "不修改" in report.summary


# ---------------------------------------------------------------------------
# Restored from test_verification_python.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


@pytest.mark.real_tools
def test_missing_pytest_module_is_skipped_and_cli_error_is_not_hidden_by_warning():
    command = CheckCommand(name='pytest', argv=[sys.executable, '-m', 'pytest'], cwd='.')
    completed = CompletedProcess(command.argv, 1, stdout='', stderr=f'{sys.executable}: No module named pytest\n')
    with patch('app.evaluator.service.subprocess.run', return_value=completed):
        result = SubprocessCommandRunner().run(command)
    assert result.status == CheckStatus.SKIPPED
    completed.stderr = 'launcher: error: unrecognized arguments: -m pytest\nwarning: deprecated API\n'
    with patch('app.evaluator.service.subprocess.run', return_value=completed):
        result = SubprocessCommandRunner().run(command)
    assert result.status == CheckStatus.FAILED
    assert result.summary == 'launcher: error: unrecognized arguments: -m pytest'


def test_verifier_cache_does_not_cross_python_environments(tmp_path):
    target = tmp_path / 'sample.py'
    target.write_text('def test_example():\n    assert True\n')
    cache = CheckResultCache()
    first = CheckCommand(name='pytest', argv=['/env-a/python', '-m', 'pytest', str(target)], cwd=str(tmp_path))
    second = CheckCommand(name='pytest', argv=['/env-b/python', '-m', 'pytest', str(target)], cwd=str(tmp_path))
    assert cache.key(first, str(tmp_path)) != cache.key(second, str(tmp_path))


@pytest.mark.real_tools
def test_missing_interpreter_is_a_bounded_check_error(tmp_path):
    command = CheckCommand(name='pytest', argv=[str(tmp_path / 'missing-python'), '-m', 'pytest'], cwd=str(tmp_path))
    result = SubprocessCommandRunner().run(command)
    assert result.status == CheckStatus.ERROR
    assert 'Could not start pytest' in result.summary


def test_failure_report_preserves_the_actionable_diagnostic():
    check = CheckResult(name='ruff', status=CheckStatus.FAILED, summary='Found 1 error.',
        stdout='S102 Use of exec detected\nFound 1 error.')
    report = EvaluatorService()._to_api_check(check)
    assert 'S102 Use of exec detected' in report.detail


# ---------------------------------------------------------------------------
# Restored from test_practice_subject_routing.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


_ESSAY = (
    "The lantern keeper walked the pier every night.\n"
    "\n"
    "He counted the boats and let the dark do the rest.\n"
)


def test_malformed_card_declaration_yields_no_hooks_and_no_pass() -> None:
    """A broken declaration must degrade to "no evidence", not to a pass."""
    pack = literature_pack()
    verdict = verify_submission_with_pack(
        pack,
        submission=_ESSAY,
        card_config={"word_count": {"min": 50, "max": 10}},
    )
    assert verdict.status == CheckStatus.PENDING
    assert verdict.hook_results == ()


def test_pack_trust_declarations() -> None:
    code_pack = python_toolchain_pack()
    assert code_pack.evidence_source == IDE_CURRENT_FILE_EVIDENCE_SOURCE
    assert code_pack.persists_practice_evidence is True

    lit_pack = literature_pack()
    assert lit_pack.evidence_source == RUBRIC_DUAL_REVIEW_EVIDENCE_SOURCE
    assert lit_pack.persists_practice_evidence is False


# ---------------------------------------------------------------------------
# Restored from test_project_overview.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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
