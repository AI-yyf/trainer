"""Deterministic stand-in for the external lint/type/test tools.

`EvaluationPipeline` shells out to ruff, pyright and pytest. Measured on this
machine that is **half the wall time of the whole server suite**: pyright alone
spends 2-4s in Node startup before it reads a line of the learner's code, and
the suite paid that cold start again for hundreds of fixture snippets.

What those runs verify is ruff, pyright and pytest — third-party tools whose
output format does not change when we edit Trainer. What the suite is supposed
to verify is Trainer: that it builds the right command line, runs it in a
sandbox, maps the outcome onto a status honestly, and reacts to it.

So by default the pipeline gets a deterministic runner, and the tests that
genuinely need the real subprocess path (missing executable, uv trampoline
failure, timeout, encoding, pytest exit codes) opt back in with
``@pytest.mark.real_tools``. `SubprocessCommandRunner` itself is still
constructed and tested directly in `tests/test_evaluator.py`.

Run the whole suite against the real tools with ``TRAINER_REAL_TOOLS=1``.
"""

from __future__ import annotations

import ast
import os

import pytest

from app.evaluator.models import CheckCommand, CheckResult, CheckStatus

#: Marker that puts a test back on the real subprocess path.
REAL_TOOLS_MARKER = "real_tools"


def _parses(source: str) -> bool:
    """Mirror the tools' reaction to unparseable Python, and nothing vaguer."""
    try:
        ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    return True


def _collects_tests(source: str) -> bool:
    """Whether pytest would actually collect anything from this source.

    A snippet with no test function is *not* a pass — pytest reports "no tests
    ran" and the evaluator treats that as unverified rather than verified. Fake
    tools that answered "passed" there turned a learner's unverified work into
    a green tick, which is exactly the dishonesty this evaluator exists to
    prevent.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            return True
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            return True
    return False


class DeterministicToolRunner:
    """Reproducible verdicts derived from the file under test."""

    @staticmethod
    def _target_of(command: CheckCommand) -> str | None:
        """Find the file a check runs against.

        Not simply "the first token that is not a flag": the real command lines
        are `ruff check <file>`, `pyright <file>` and
        `<python> -m pytest <file> -p no:cacheprovider`, so the first positional
        token is `check` or `pytest`, not the file. Picking the wrong one made
        a sound snippet report ERROR on two tools while pyright passed.
        """
        candidates = [token for token in command.argv[1:] if not token.startswith("-")]
        for token in candidates:
            if os.path.isfile(token):
                return token
        return candidates[-1] if candidates else None

    def run(self, command: CheckCommand) -> CheckResult:
        name = command.name
        argv = list(command.argv)
        target = self._target_of(command)

        if target is None:
            return CheckResult(
                name=name,
                status=CheckStatus.SKIPPED,
                command=argv,
                summary=f"{name} has no target to run against.",
            )

        try:
            with open(target, "r", encoding="utf-8", errors="replace") as handle:
                source = handle.read()
        except OSError as exc:
            return CheckResult(
                name=name,
                status=CheckStatus.ERROR,
                command=argv,
                stderr=str(exc),
                exit_code=None,
                summary=f"{name} could not read the target.",
            )

        if name == "pytest" and (not source.strip() or not _collects_tests(source)):
            # Matches pytest's real behaviour: nothing collected is skipped,
            # never a silent pass.
            return CheckResult(
                name=name,
                status=CheckStatus.SKIPPED,
                command=argv,
                stdout="no tests ran in 0.01s\n",
                exit_code=5,
                summary="pytest collected no tests.",
            )

        if not _parses(source):
            return CheckResult(
                name=name,
                status=CheckStatus.FAILED,
                command=argv,
                stdout=(
                    "1 failed in 0.01s\n"
                    if name == "pytest"
                    else f"{target}:1:1: error: invalid syntax\n"
                ),
                exit_code=1,
                summary=f"{name} reported an error.",
            )

        return CheckResult(
            name=name,
            status=CheckStatus.PASSED,
            command=argv,
            stdout="1 passed in 0.01s\n" if name == "pytest" else "",
            exit_code=0,
            summary=f"{name} passed.",
        )


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        f"{REAL_TOOLS_MARKER}: run the real ruff/pyright/pytest subprocesses",
    )


@pytest.fixture(autouse=True)
def _use_deterministic_tools(request):
    """Swap the pipeline's default runner, unless the test opts out.

    Patching `default_command_runner` rather than the class keeps
    `SubprocessCommandRunner` itself reachable, so the tests that construct it
    directly still exercise the real implementation.
    """
    if os.environ.get("TRAINER_REAL_TOOLS") == "1":
        yield
        return
    if request.node.get_closest_marker(REAL_TOOLS_MARKER):
        yield
        return

    from app.evaluator import service as evaluator_service

    original = evaluator_service.default_command_runner
    evaluator_service.default_command_runner = DeterministicToolRunner
    try:
        yield
    finally:
        evaluator_service.default_command_runner = original
