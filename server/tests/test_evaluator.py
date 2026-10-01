from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import EvaluateCurrentFileRequest, EvaluateSnippetRequest
from app.core.models import TaskSpec as ApiTaskSpec
from app.evaluator import (
    CheckResult,
    CheckStatus,
    EvaluationPipeline,
    EvaluationRequest,
    EvaluatorService,
    SemanticReview,
)
from app.evaluator.models import CheckCommand
from app.evaluator.models import EvaluationReport as LaneEvaluationReport
from app.evaluator.service import SubprocessCommandRunner
from app.specs import TaskSpecGenerator, TaskSpecificationRequest


class FakeRunner:
    def __init__(self, statuses: dict[str, CheckStatus] | None = None) -> None:
        self._statuses = statuses or {}

    def run(self, command: CheckCommand) -> CheckResult:
        status = self._statuses.get(command.name, CheckStatus.PASSED)
        summary = "ok" if status in {CheckStatus.PASSED, CheckStatus.SKIPPED} else "failed"
        return CheckResult(name=command.name, status=status, command=command.argv, summary=summary)


class FakeEvaluationPipeline(EvaluationPipeline):
    def __init__(self) -> None:
        self.requests: list[EvaluationRequest] = []

    def evaluate(self, request: EvaluationRequest) -> LaneEvaluationReport:
        self.requests.append(request)
        return LaneEvaluationReport(
            target=request.target_path or "<snippet>",
            overall_status=CheckStatus.PASSED,
            checks=[
                CheckResult(name="ruff", status=CheckStatus.PASSED, summary="ok"),
                CheckResult(name="pyright", status=CheckStatus.PASSED, summary="ok"),
                CheckResult(name="pytest", status=CheckStatus.PASSED, summary="ok"),
                CheckResult(
                    name="hypothesis", status=CheckStatus.SKIPPED, summary="not configured"
                ),
            ],
            semantic_review=SemanticReview(
                status=CheckStatus.PASSED,
                summary="Implementation satisfies the available signals.",
            ),
            reflection={"summary": "Implementation satisfies the available signals."},
        )


class RecordingEvaluationPipeline(EvaluationPipeline):
    def __init__(self, runner: FakeRunner) -> None:
        super().__init__(runner=runner)
        self.requests: list[EvaluationRequest] = []

    def evaluate(self, request: EvaluationRequest) -> LaneEvaluationReport:
        self.requests.append(request)
        return super().evaluate(request)


class EvaluatorTests(unittest.TestCase):
    def test_runner_uses_sibling_console_script_when_path_lookup_fails(self) -> None:
        command_name = "ruff"
        runtime_suffix = ".exe" if os.name == "nt" else ""

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir)
            runtime_python = runtime_dir / f"python{runtime_suffix}"
            runtime_python.touch()
            sibling_script = runtime_dir / f"{command_name}{runtime_suffix}"
            sibling_script.touch()
            command = CheckCommand(name=command_name, argv=[command_name, "check", "."], cwd=".")
            completed = CompletedProcess(
                [str(sibling_script), "check", "."],
                0,
                stdout="ok\n",
                stderr="",
            )

            with (
                patch("app.evaluator.service.shutil.which", return_value=None),
                patch("app.evaluator.service.sys.executable", str(runtime_python)),
                patch("app.evaluator.service.subprocess.run", return_value=completed) as mock_run,
            ):
                result = SubprocessCommandRunner().run(command)

            self.assertEqual(result.status, CheckStatus.PASSED)
            self.assertEqual(result.command[0], str(sibling_script.resolve(strict=False)))
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args.args[0][0], str(sibling_script.resolve(strict=False)))

    @pytest.mark.real_tools  # asserts on real subprocess / exit-code behaviour
    def test_missing_executable_stays_skipped_when_no_sibling_script_exists(self) -> None:
        runtime_suffix = ".exe" if os.name == "nt" else ""

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir)
            runtime_python = runtime_dir / f"python{runtime_suffix}"
            runtime_python.touch()
            command = CheckCommand(name="pytest", argv=["pytest"], cwd=".")

            with (
                patch("app.evaluator.service.shutil.which", return_value=None),
                patch("app.evaluator.service.sys.executable", str(runtime_python)),
                patch("app.evaluator.service.subprocess.run") as mock_run,
            ):
                result = SubprocessCommandRunner().run(command)

            self.assertEqual(result.status, CheckStatus.SKIPPED)
            self.assertEqual(result.command, command.argv)
            mock_run.assert_not_called()

    @pytest.mark.real_tools  # asserts on real subprocess / exit-code behaviour
    def test_runner_tolerates_missing_output_and_forces_utf8_decoding(self) -> None:
        command = CheckCommand(name="ruff", argv=["ruff", "check", "."], cwd=".")
        completed = CompletedProcess(command.argv, 0, stdout=None, stderr=None)

        with (
            patch("app.evaluator.service.shutil.which", return_value="ruff"),
            patch("app.evaluator.service.subprocess.run", return_value=completed) as mock_run,
        ):
            result = SubprocessCommandRunner().run(command)

        self.assertEqual(result.status, CheckStatus.PASSED)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertEqual(mock_run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(mock_run.call_args.kwargs["errors"], "replace")

    @pytest.mark.real_tools  # asserts on real subprocess / exit-code behaviour
    def test_runner_returns_error_when_check_times_out(self) -> None:
        command = CheckCommand(name="pytest", argv=["pytest"], cwd=".")
        timeout = TimeoutExpired(command.argv, 60, output=b"partial", stderr=b"still running")

        with (
            patch("app.evaluator.service.shutil.which", return_value="pytest"),
            patch("app.evaluator.service.subprocess.run", side_effect=timeout),
        ):
            result = SubprocessCommandRunner().run(command)

        self.assertEqual(result.status, CheckStatus.ERROR)
        self.assertEqual(result.stdout, "partial")
        self.assertEqual(result.stderr, "still running")
        self.assertIn("timed out after 60 seconds", result.summary)

    @pytest.mark.real_tools  # asserts on real subprocess / exit-code behaviour
    def test_pytest_no_tests_collected_is_skipped(self) -> None:
        command = CheckCommand(name="pytest", argv=["pytest"], cwd=".")
        completed = CompletedProcess(command.argv, 5, stdout="no tests ran in 0.01s\n", stderr="")

        with (
            patch("app.evaluator.service.shutil.which", return_value="pytest"),
            patch("app.evaluator.service.subprocess.run", return_value=completed),
        ):
            result = SubprocessCommandRunner().run(command)

        self.assertEqual(result.status, CheckStatus.SKIPPED)
        self.assertEqual(result.exit_code, 5)

    @pytest.mark.real_tools  # asserts on real subprocess / exit-code behaviour
    def test_pytest_failure_is_not_treated_as_no_tests(self) -> None:
        command = CheckCommand(name="pytest", argv=["pytest"], cwd=".")
        completed = CompletedProcess(command.argv, 1, stdout="1 failed in 0.01s\n", stderr="")

        with (
            patch("app.evaluator.service.shutil.which", return_value="pytest"),
            patch("app.evaluator.service.subprocess.run", return_value=completed),
        ):
            result = SubprocessCommandRunner().run(command)

        self.assertEqual(result.status, CheckStatus.FAILED)

    @pytest.mark.real_tools  # asserts on real subprocess / exit-code behaviour
    def test_uv_trampoline_failure_is_skipped_not_failed(self) -> None:
        command = CheckCommand(name="pyright", argv=["pyright", "x.py"], cwd=".")
        completed = CompletedProcess(
            command.argv,
            1,
            stdout="",
            stderr="error: uv trampoline failed to canonicalize script path\n",
        )

        with (
            patch("app.evaluator.service.shutil.which", return_value="pyright"),
            patch("app.evaluator.service.subprocess.run", return_value=completed),
        ):
            result = SubprocessCommandRunner().run(command)

        self.assertEqual(result.status, CheckStatus.SKIPPED)

    @pytest.mark.real_tools  # asserts on real subprocess / exit-code behaviour
    def test_pytest_exit_five_without_collection_evidence_stays_failed(self) -> None:
        command = CheckCommand(name="pytest", argv=["pytest"], cwd=".")
        completed = CompletedProcess(
            command.argv, 5, stdout="pytest encountered an unexpected error\n", stderr=""
        )

        with (
            patch("app.evaluator.service.shutil.which", return_value="pytest"),
            patch("app.evaluator.service.subprocess.run", return_value=completed),
        ):
            result = SubprocessCommandRunner().run(command)

        self.assertEqual(result.status, CheckStatus.FAILED)

    def test_pipeline_builds_python_checks(self) -> None:
        generator = TaskSpecGenerator()
        spec = generator.generate(
            TaskSpecificationRequest(prompt="Return the sum of two numbers.")
        ).spec
        pipeline = EvaluationPipeline(runner=FakeRunner())
        report = pipeline.evaluate(
            EvaluationRequest(spec=spec, code="def add(a, b):\n    return a + b\n")
        )
        self.assertEqual(report.overall_status, CheckStatus.PASSED)
        self.assertEqual([check.name for check in report.checks[:3]], ["ruff", "pyright", "pytest"])

    def test_current_file_evaluation_includes_vscode_diagnostics_and_training_context(self) -> None:
        pipeline = FakeEvaluationPipeline()
        service = EvaluatorService(pipeline=pipeline)

        report = service.evaluate_current_file(
            EvaluateCurrentFileRequest(
                session_id="session-1",
                workspace_id="workspace-1",
                task_spec_id="task-card",
                file_path="F:/trainer/workspace-a/src/exercise.ts",
                language_id="typescript",
                content="export const answer: number = 'oops';\n",
                diagnostics=[
                    "[Error] line 1: Type 'string' is not assignable to type 'number'.",
                    "[Warning] line 2: Unused local helper.",
                ],
                evaluation_source="training",
                training_card_id="card-practice-1",
                training_card_title="Refactor the async boundary",
            )
        )

        self.assertEqual(len(pipeline.requests), 1)
        self.assertEqual(pipeline.requests[0].code, "export const answer: number = 'oops';\n")
        self.assertEqual(pipeline.requests[0].target_path, "F:/trainer/workspace-a/src/exercise.ts")
        self.assertFalse(report.passed)
        self.assertIn("vscode-diagnostics", report.summary)
        diagnostics_check = next(
            check for check in report.static_checks if check.id == "vscode-diagnostics"
        )
        self.assertEqual(diagnostics_check.status, "failed")
        self.assertIn("Type 'string' is not assignable", diagnostics_check.detail)
        semantic_detail = report.semantic_checks[0].detail
        self.assertIn("Source: training practice verification.", semantic_detail)
        self.assertIn("Training card: Refactor the async boundary.", semantic_detail)
        self.assertIn(
            "Current file: F:/trainer/workspace-a/src/exercise.ts (typescript).", semantic_detail
        )
        self.assertIn("VS Code diagnostics attached: 2.", semantic_detail)

    def test_training_acceptance_signals_allow_current_file_practice_pass(self) -> None:
        pipeline = FakeEvaluationPipeline()
        service = EvaluatorService(pipeline=pipeline)

        report = service.evaluate_current_file(
            EvaluateCurrentFileRequest(
                session_id="session-1",
                workspace_id="workspace-1",
                task_spec_id="task-card",
                file_path="F:/trainer/workspace-a/src/search.ts",
                language_id="typescript",
                content=(
                    "export function debounceSearch(normalizedQuery: string) {\n"
                    "  return normalizedQuery.trim().toLowerCase();\n"
                    "}\n"
                ),
                diagnostics=[],
                evaluation_source="training",
                training_card_id="card-practice-1",
                training_card_title="Debounce resource search",
                acceptance_criteria=[
                    "Implement debounceSearch for the search input.",
                    "Use normalizedQuery before filtering resources.",
                ],
                learner_deliverables=[
                    "A current-file implementation that includes debounceSearch.",
                ],
                expected_symbols=["debounceSearch", "normalizedQuery"],
            )
        )

        self.assertTrue(report.passed)
        training_check = next(
            check for check in report.semantic_checks if check.id == "training-acceptance"
        )
        self.assertEqual(training_check.status, "passed")
        self.assertIn("Matched: Implement debounceSearch", training_check.detail)
        self.assertIn("Expected symbols supplied: 2.", training_check.detail)

    def test_training_acceptance_signals_block_missing_current_file_symbol(self) -> None:
        pipeline = FakeEvaluationPipeline()
        service = EvaluatorService(pipeline=pipeline)

        report = service.evaluate_current_file(
            EvaluateCurrentFileRequest(
                session_id="session-1",
                workspace_id="workspace-1",
                task_spec_id="task-card",
                file_path="F:/trainer/workspace-a/src/search.ts",
                language_id="typescript",
                content="export function searchNow(query: string) { return query; }\n",
                diagnostics=[],
                evaluation_source="training",
                training_card_id="card-practice-1",
                training_card_title="Debounce resource search",
                acceptance_criteria=["Implement debounceSearch for the search input."],
                expected_symbols=["debounceSearch"],
            )
        )

        self.assertFalse(report.passed)
        # Progressive feedback: the summary names the matched/total signals and
        # the first missing one instead of a bare failure sentence.
        self.assertIn("Training acceptance: 0/2 acceptance signals matched.", report.summary)
        self.assertIn(
            "Still missing: Implement debounceSearch for the search input.; debounceSearch.",
            report.summary,
        )
        self.assertIn(
            'starting with "Implement debounceSearch for the search input."', report.next_step
        )
        self.assertIn("missing practice acceptance signals", report.next_step)
        training_check = next(
            check for check in report.semantic_checks if check.id == "training-acceptance"
        )
        self.assertEqual(training_check.status, "failed")
        self.assertIn(
            "Acceptance progress: 0/2 acceptance signals matched.", training_check.detail
        )
        self.assertIn("Missing: debounceSearch (debounceSearch)", training_check.detail)

    def test_training_acceptance_rejects_comment_and_string_only_evidence(self) -> None:
        pipeline = FakeEvaluationPipeline()
        service = EvaluatorService(pipeline=pipeline)

        report = service.evaluate_current_file(
            EvaluateCurrentFileRequest(
                session_id="session-1",
                workspace_id="workspace-1",
                file_path="F:/trainer/workspace-a/src/search.ts",
                language_id="typescript",
                content=(
                    "// debounceSearch normalizedQuery\n"
                    "const label = 'debounceSearch normalizedQuery';\n"
                ),
                evaluation_source="training",
                acceptance_criteria=[
                    "Implement debounceSearch for the search input.",
                    "Use normalizedQuery before filtering resources.",
                ],
                expected_symbols=["debounceSearch", "normalizedQuery"],
            )
        )

        self.assertFalse(report.passed)
        training_check = next(
            check for check in report.semantic_checks if check.id == "training-acceptance"
        )
        self.assertEqual(training_check.status, "failed")
        self.assertIn("Missing: debounceSearch (debounceSearch)", training_check.detail)
        self.assertIn("Missing: normalizedQuery (normalizedQuery)", training_check.detail)

    def test_training_acceptance_rejects_generic_comment_word_as_implementation_evidence(
        self,
    ) -> None:
        pipeline = FakeEvaluationPipeline()
        service = EvaluatorService(pipeline=pipeline)

        report = service.evaluate_current_file(
            EvaluateCurrentFileRequest(
                session_id="session-1",
                workspace_id="workspace-1",
                file_path="F:/trainer/workspace-a/src/search.py",
                language_id="python",
                content="# search only; no debounce implementation\n",
                evaluation_source="training",
                acceptance_criteria=["Implement debounceSearch for the search input."],
            )
        )

        self.assertFalse(report.passed)
        training_check = next(
            check for check in report.semantic_checks if check.id == "training-acceptance"
        )
        self.assertEqual(training_check.status, "failed")
        self.assertIn(
            "Missing: Implement debounceSearch for the search input. (debounceSearch)",
            training_check.detail,
        )

    def test_training_acceptance_rejects_hash_comments_for_unknown_code_languages(self) -> None:
        pipeline = FakeEvaluationPipeline()
        service = EvaluatorService(pipeline=pipeline)

        report = service.evaluate_current_file(
            EvaluateCurrentFileRequest(
                session_id="session-1",
                workspace_id="workspace-1",
                file_path="F:/trainer/workspace-a/scripts/parse.sh",
                language_id="shellscript",
                content="# parse_input\n",
                evaluation_source="training",
                acceptance_criteria=["Implement parse_input for the practice input."],
                expected_symbols=["parse_input"],
            )
        )

        self.assertFalse(report.passed)
        training_check = next(
            check for check in report.semantic_checks if check.id == "training-acceptance"
        )
        self.assertEqual(training_check.status, "failed")

    def test_non_code_training_can_use_textual_acceptance(self) -> None:
        pipeline = FakeEvaluationPipeline()
        service = EvaluatorService(pipeline=pipeline)

        report = service.evaluate_snippet(
            EvaluateSnippetRequest(
                session_id="session-1",
                workspace_id="workspace-1",
                language_id="markdown",
                content="Caching improves repeated API responses by returning a stored result.",
                evaluation_source="training",
                acceptance_criteria=["Caching improves repeated API responses."],
            )
        )

        self.assertTrue(report.passed)

    def test_training_current_file_requires_verification_when_pytest_collects_no_tests_and_acceptance_matches(
        self,
    ) -> None:
        pipeline = RecordingEvaluationPipeline(FakeRunner({"pytest": CheckStatus.SKIPPED}))
        service = EvaluatorService(pipeline=pipeline)

        report = service.evaluate_current_file(
            EvaluateCurrentFileRequest(
                session_id="session-1",
                workspace_id="workspace-1",
                task_spec_id="training-card",
                file_path="F:/trainer/workspace-a/src/parse_input.py",
                language_id="python",
                content="def parse_input(raw: str) -> list[str]:\n    return raw.split(',')\n",
                evaluation_source="training",
                acceptance_criteria=["Implement parse_input for the practice input."],
                expected_symbols=["parse_input"],
            )
        )

        self.assertFalse(report.passed)
        self.assertIn("Verification is still required", report.summary)
        self.assertIn("Run at least one dynamic verifier", report.next_step)
        self.assertEqual(pipeline.requests[0].spec.requirements, [])
        pytest_check = next(check for check in report.dynamic_checks if check.id == "pytest")
        self.assertEqual(pytest_check.status, "skipped")

    def test_training_current_file_keeps_real_pytest_failure_blocking(self) -> None:
        pipeline = EvaluationPipeline(runner=FakeRunner({"pytest": CheckStatus.FAILED}))
        service = EvaluatorService(pipeline=pipeline)

        report = service.evaluate_current_file(
            EvaluateCurrentFileRequest(
                session_id="session-1",
                workspace_id="workspace-1",
                file_path="F:/trainer/workspace-a/src/parse_input.py",
                language_id="python",
                content="def parse_input(raw: str) -> list[str]:\n    return raw.split(',')\n",
                evaluation_source="training",
                acceptance_criteria=["Implement parse_input for the practice input."],
                expected_symbols=["parse_input"],
            )
        )

        self.assertFalse(report.passed)
        self.assertIn("pytest", report.summary)
        pytest_check = next(check for check in report.dynamic_checks if check.id == "pytest")
        self.assertEqual(pytest_check.status, "failed")

    def test_training_current_file_requires_acceptance_when_no_formal_task_exists(self) -> None:
        pipeline = EvaluationPipeline(runner=FakeRunner({"pytest": CheckStatus.SKIPPED}))
        service = EvaluatorService(pipeline=pipeline)

        report = service.evaluate_current_file(
            EvaluateCurrentFileRequest(
                session_id="session-1",
                workspace_id="workspace-1",
                file_path="F:/trainer/workspace-a/src/parse_input.py",
                language_id="python",
                content="def parse_input(raw: str) -> list[str]:\n    return raw.split(',')\n",
                evaluation_source="training",
            )
        )

        self.assertFalse(report.passed)
        acceptance_check = next(
            check for check in report.semantic_checks if check.id == "training-acceptance"
        )
        self.assertEqual(acceptance_check.status, "warning")

    def test_training_acceptance_does_not_replace_a_formal_task_spec(self) -> None:
        pipeline = EvaluationPipeline(runner=FakeRunner({"pytest": CheckStatus.SKIPPED}))
        service = EvaluatorService(pipeline=pipeline)
        formal_spec = ApiTaskSpec(
            id="formal-task",
            title="Formatter",
            natural_language_goal="Create a tokenized formatter for the response.",
        )

        report = service.evaluate_current_file(
            EvaluateCurrentFileRequest(
                session_id="session-1",
                workspace_id="workspace-1",
                task_spec_id="formal-task",
                file_path="F:/trainer/workspace-a/src/parse_input.py",
                language_id="python",
                content="def parse_input(raw: str) -> list[str]:\n    return raw.split(',')\n",
                evaluation_source="training",
                acceptance_criteria=["Implement parse_input for the practice input."],
                expected_symbols=["parse_input"],
            ),
            spec=formal_spec,
        )

        self.assertFalse(report.passed)
        self.assertIn("Verification is still required", report.summary)
        self.assertIn("Implement the requirement gaps", report.next_step)


def test_leftover_formal_card_title_does_not_live_in_evaluator_notes() -> None:
    from app.core.models import LearningPlan, PlanStage

    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_card = f"Practice: {leftover_title}"
    recovered_step = "Add a token expiry test"
    plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id="stage-1",
        current_step=leftover_step,
        stages=[
            PlanStage(
                id="stage-1",
                title=leftover_stage,
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    service = EvaluatorService()
    notes = service._evaluation_context_notes(
        source="training",
        file_path=None,
        language_id="python",
        training_card_title=leftover_card,
        leftover_plan=plan,
        leftover_runtime={
            "current_step": recovered_step,
            "why_now": "Expired tokens still leak.",
            "resume_state": "in_progress",
            "workspace_id": "workspace-eval-leftover",
        },
        leftover_task_title=leftover_title,
    )
    live_copy = " ".join(notes)
    assert leftover_title not in live_copy
    assert leftover_card not in live_copy
    assert leftover_stage not in live_copy
    assert leftover_step not in live_copy
    assert leftover_summary not in live_copy
    assert leftover_plan_id not in live_copy
    assert f"Training card: {recovered_step}." in notes
    empty_notes = service._evaluation_context_notes(
        source="training",
        file_path=None,
        language_id="python",
        training_card_title=leftover_card,
        leftover_plan=plan,
        leftover_runtime={"current_step": "", "resume_state": "in_progress"},
        leftover_task_title=leftover_title,
    )
    empty_copy = " ".join(empty_notes)
    assert leftover_title not in empty_copy
    assert leftover_card not in empty_copy
    assert all(not item.startswith("Training card:") for item in empty_notes)
    still_notes = service._evaluation_context_notes(
        source="training",
        file_path=None,
        language_id="python",
        training_card_title=leftover_card,
        leftover_plan=plan,
        leftover_runtime={
            "current_step": leftover_step,
            "plan_id": leftover_plan_id,
            "resume_state": "in_progress",
            "workspace_id": "workspace-eval-still-on-plan",
        },
        leftover_task_title=leftover_title,
    )
    assert f"Training card: {leftover_card}." in still_notes


if __name__ == "__main__":
    unittest.main()


class _SlowRunner:
    """Records concurrency by tracking overlapping calls."""

    def __init__(self, delay: float = 0.12) -> None:
        self._delay = delay
        self.calls: list[str] = []
        self.max_overlap = 0
        self._active = 0
        self._lock = threading.Lock()

    def run(self, command: CheckCommand) -> CheckResult:
        with self._lock:
            self.calls.append(command.name)
            self._active += 1
            self.max_overlap = max(self.max_overlap, self._active)
        try:
            time.sleep(self._delay)
            return CheckResult(
                name=command.name, status=CheckStatus.PASSED, command=list(command.argv), summary="ok"
            )
        finally:
            with self._lock:
                self._active -= 1


def _snippet_request(code: str = "def add(a: int, b: int) -> int:\n    return a + b\n"):
    spec = TaskSpecGenerator().generate(
        TaskSpecificationRequest(prompt="Add two integers and return the sum.")
    ).spec
    return EvaluationRequest(spec=spec, code=code)


class TestEvaluatorPerformanceInvariants(unittest.TestCase):
    """Locks in the three optimisations that keep "verify this file" responsive.

    None of these change behaviour, so every one of them is the kind of edit
    that slips through a green suite: a pipeline that runs the tools in series
    passes the same assertions, just five seconds slower per turn. Each test
    fails on the regression rather than on a changed string.
    """

    def setUp(self) -> None:
        from app.evaluator.check_cache import CHECK_RESULT_CACHE

        CHECK_RESULT_CACHE.clear()
        self.addCleanup(CHECK_RESULT_CACHE.clear)

    def test_pipeline_resolves_its_runner_through_the_default_factory(self) -> None:
        """The suite replaces `default_command_runner`, not the class.

        Inlining `SubprocessCommandRunner()` into `EvaluationPipeline.__init__`
        would silently bypass the deterministic stand-in the whole suite runs
        on, and every test would still pass — while the suite went from two
        minutes back to spawning real pyright for hundreds of fixtures.
        """
        from app.evaluator import service as evaluator_service

        sentinel = FakeRunner({CheckStatus.PASSED: CheckStatus.PASSED})
        original = evaluator_service.default_command_runner
        evaluator_service.default_command_runner = lambda: sentinel
        try:
            pipeline = EvaluationPipeline()
        finally:
            evaluator_service.default_command_runner = original
        self.assertIs(pipeline._runner, sentinel)  # noqa: SLF001

    def test_external_tools_run_concurrently_not_in_series(self) -> None:
        """ruff, pyright and pytest overlap instead of summing their startups.

        A verification turn is dominated by process startup — pyright alone
        spends 2-4s in Node before reading a line. Running the three in series
        cost the *sum*; this pins that they overlap.
        """
        runner = _SlowRunner()
        pipeline = EvaluationPipeline(runner=runner)
        pipeline.evaluate(_snippet_request())
        self.assertEqual(sorted(runner.calls), ["pyright", "pytest", "ruff"])
        self.assertGreater(
            runner.max_overlap,
            1,
            "external tools ran one after another; a verification turn pays the sum of three cold starts",
        )

    def test_unchanged_code_is_not_re_verified_from_scratch(self) -> None:
        """Re-checking identical content reuses the tool results.

        The coach asks for verification repeatedly; without the content-keyed
        cache every request re-spawned all three tools for a file that had not
        changed.
        """
        runner = _SlowRunner()
        pipeline = EvaluationPipeline(runner=runner)
        first = _snippet_request()
        pipeline.evaluate(first)
        second = _snippet_request()
        pipeline.evaluate(second)
        self.assertEqual(
            runner.calls.count("pyright"),
            1,
            "identical content was verified twice; the content-keyed cache is not wired into the pipeline",
        )

    def test_a_result_is_only_reused_by_the_runner_that_produced_it(self) -> None:
        """Swapping the runner must not inherit the previous runner's verdict.

        Two runners can legitimately disagree about identical content — a live
        pyright and a fixture, say. Keying the cache on content alone let a
        swapped runner silently return the old verdict, which is how
        `test_training_recovery_journey` caught this.
        """
        first = _SlowRunner()
        spec = TaskSpecGenerator().generate(
            TaskSpecificationRequest(prompt="Return the sum of two numbers.")
        ).spec
        EvaluationPipeline(runner=first).evaluate(
            EvaluationRequest(spec=spec, code="def add(a: int, b: int) -> int:\n    return a + b\n")
        )
        self.assertEqual(len(first.calls), 3)

        class DisagreeingRunner:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def run(self, command: CheckCommand) -> CheckResult:
                self.calls.append(command.name)
                return CheckResult(
                    name=command.name,
                    status=CheckStatus.FAILED,
                    command=list(command.argv),
                    summary="this runner disagrees",
                )

        second = DisagreeingRunner()
        report = EvaluationPipeline(runner=second).evaluate(
            EvaluationRequest(spec=spec, code="def add(a: int, b: int) -> int:\n    return a + b\n")
        )
        self.assertEqual(
            sorted(second.calls),
            ["pyright", "pytest", "ruff"],
            "the second runner inherited the first runner's cached verdict",
        )
        self.assertEqual(report.overall_status, CheckStatus.FAILED)

    def test_cache_survives_concurrent_verification_requests(self) -> None:
        """Two learners verifying at once must not corrupt the cache.

        The verify endpoints are *sync* FastAPI handlers, so Starlette runs
        them in its threadpool and the cache is genuinely shared across
        threads. Read-modify-evict is not atomic: without a lock, two threads
        reaching the eviction together pop the final entry and the second
        `popitem` raises, turning a verification the user asked for into a 500.
        """
        from app.evaluator.check_cache import CheckResultCache

        cache = CheckResultCache(max_entries=8)
        sandbox = tempfile.mkdtemp()
        files = []
        for index in range(40):
            path = os.path.join(sandbox, f"file_{index}.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(f"VALUE_{index} = {index}\n")
            files.append(CheckCommand(name="ruff", argv=["ruff", "check", path], cwd=sandbox))

        errors: list[BaseException] = []
        barrier = threading.Barrier(8)

        def hammer(subset: list[CheckCommand]) -> None:
            try:
                barrier.wait(timeout=10)
                for _ in range(6):
                    for command in subset:
                        cache.get(command, sandbox, runner=self)
                        cache.put(
                            command,
                            sandbox,
                            CheckResult(
                                name=command.name,
                                status=CheckStatus.PASSED,
                                command=list(command.argv),
                                summary="ok",
                            ),
                            runner=self,
                        )
            except BaseException as exc:  # noqa: BLE001 - the point is to surface it
                errors.append(exc)

        threads = [threading.Thread(target=hammer, args=(files[index::8],)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual([str(error) for error in errors], [], "concurrent cache access raised")
        self.assertLessEqual(len(cache), 8)
