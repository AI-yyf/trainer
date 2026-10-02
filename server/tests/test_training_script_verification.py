from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.core.models import EvaluateCurrentFileRequest
from app.evaluator.models import CheckCommand, CheckResult, CheckStatus
from app.evaluator.service import EvaluationPipeline, EvaluatorService, SubprocessCommandRunner


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
