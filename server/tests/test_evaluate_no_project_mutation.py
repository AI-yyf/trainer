"""Prove evaluate endpoints never mutate workspace project files."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import EvaluateCurrentFileRequest, EvaluateSnippetRequest
from app.core.settings import AppSettings
from app.evaluator.models import (
    CheckCommand,
    CheckResult,
    CheckStatus,
    EvaluationRequest,
    SemanticReview,
)
from app.evaluator.service import EvaluationPipeline, EvaluatorService
from app.main import create_app
from app.specs.models import RequirementItem, TaskSpec

SENTINEL_MARKER = "TRAINER_EVAL_SENTINEL_UNCHANGED_v1\n"


class _SilentRunner:
    def run(self, command: CheckCommand) -> CheckResult:
        return CheckResult(
            name=command.name,
            status=CheckStatus.SKIPPED,
            command=command.argv,
            summary="skipped for mutation proof",
        )


class _SilentHypothesis:
    def run(self, request: EvaluationRequest) -> CheckResult:
        return CheckResult(
            name="hypothesis",
            status=CheckStatus.SKIPPED,
            summary="skipped for mutation proof",
        )


class _SilentSemantic:
    def review(self, spec: TaskSpec, code: str, checks: list[CheckResult]) -> SemanticReview:
        return SemanticReview(
            status=CheckStatus.PASSED,
            summary="mutation-proof semantic skip",
        )


def _pipeline() -> EvaluationPipeline:
    return EvaluationPipeline(
        runner=_SilentRunner(),
        hypothesis_hook=_SilentHypothesis(),
        semantic_reviewer=_SilentSemantic(),
    )


def _minimal_spec() -> TaskSpec:
    return TaskSpec(
        id="mutation-proof-spec",
        title="mutation proof",
        objective="prove evaluate does not rewrite files",
        requirements=[RequirementItem(category="behavior", text="noop")],
    )


def test_evaluate_snippet_does_not_mutate_workspace_sentinel(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    sentinel = workspace / "sentinel.py"
    sentinel.write_text(SENTINEL_MARKER, encoding="utf-8")
    before = sentinel.read_bytes()

    pipeline = _pipeline()
    report = pipeline.evaluate(
        EvaluationRequest(
            spec=_minimal_spec(),
            code="def add(a: int, b: int) -> int:\n    return a + b\n",
        )
    )

    assert sentinel.read_bytes() == before
    assert report.target != str(sentinel)
    assert "trainer_snippet.py" in report.target.replace("\\", "/")


def test_evaluate_current_file_does_not_rewrite_divergent_content(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    sentinel = workspace / "learner_file.py"
    sentinel.write_text(SENTINEL_MARKER, encoding="utf-8")
    before = sentinel.read_bytes()
    divergent = "def mutated() -> str:\n    return 'should-not-land-on-disk'\n"

    service = EvaluatorService(pipeline=_pipeline())
    report = service.evaluate_current_file(
        EvaluateCurrentFileRequest(
            session_id="session-mutation-proof",
            workspace_id="workspace-mutation-proof",
            file_path=str(sentinel),
            language_id="python",
            content=divergent,
        )
    )

    assert sentinel.read_bytes() == before
    assert SENTINEL_MARKER.strip() not in divergent
    assert report.summary  # report-only path still returns a report


def test_evaluate_snippet_service_leaves_workspace_files_alone(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    sentinel = workspace / "keep_me.py"
    sentinel.write_text(SENTINEL_MARKER, encoding="utf-8")
    before = sentinel.read_bytes()

    service = EvaluatorService(pipeline=_pipeline())
    service.evaluate_snippet(
        EvaluateSnippetRequest(
            session_id="session-mutation-proof",
            workspace_id="workspace-mutation-proof",
            language_id="python",
            content="print('snippet-only')\n",
        )
    )

    assert sentinel.read_bytes() == before


def test_api_evaluate_snippet_and_current_file_preserve_sentinel(tmp_path: Path) -> None:
    workspace = tmp_path / "learner-workspace"
    workspace.mkdir()
    sentinel = workspace / "sentinel.py"
    sentinel.write_text(SENTINEL_MARKER, encoding="utf-8")
    before = sentinel.read_bytes()

    settings = AppSettings(
        app_name="Trainer Evaluate Mutation Proof",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-eval-mutation.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    client = TestClient(create_app(settings))
    runtime = client.app.state.runtime
    runtime.evaluator_service = EvaluatorService(pipeline=_pipeline())

    start = client.post(
        "/session/start",
        json={
            "workspace_id": "workspace-eval-mutation",
            "workspace_name": "eval-mutation",
            "profile": {
                "long_term_goal": "Prove evaluate is verify-only",
                "weekly_hours": 2,
                "teaching_style": "guided",
                "answer_policy": "guided",
            },
        },
    )
    assert start.status_code == 200
    session_id = start.json()["session_id"]

    snippet = client.post(
        "/evaluate/snippet",
        json={
            "session_id": session_id,
            "workspace_id": "workspace-eval-mutation",
            "language_id": "python",
            "content": "def add(a: int, b: int) -> int:\n    return a + b\n",
        },
    )
    assert snippet.status_code == 200, snippet.text
    assert sentinel.read_bytes() == before

    current = client.post(
        "/evaluate/current-file",
        json={
            "session_id": session_id,
            "workspace_id": "workspace-eval-mutation",
            "file_path": str(sentinel),
            "language_id": "python",
            "content": "def should_not_overwrite() -> int:\n    return 42\n",
        },
    )
    assert current.status_code == 200, current.text
    assert sentinel.read_bytes() == before


class _CwdSpyRunner:
    """Records tool cwd; simulates pytest writing .pytest_cache into that cwd."""

    def __init__(self) -> None:
        self.cwds: list[str | None] = []

    def run(self, command: CheckCommand) -> CheckResult:
        self.cwds.append(command.cwd)
        if command.cwd:
            cache = Path(command.cwd) / ".pytest_cache"
            cache.mkdir(exist_ok=True)
            (cache / "CACHEDIR.TAG").write_text("marker\n", encoding="utf-8")
        return CheckResult(
            name=command.name,
            status=CheckStatus.SKIPPED,
            command=command.argv,
            summary="cwd spy",
        )


def test_evaluate_tool_cwd_is_sandbox_not_project(tmp_path: Path) -> None:
    """Live side-effect hole: silent runners hid project-cwd cache writes."""
    project = tmp_path / "learner-project"
    project.mkdir()
    target = project / "exercise.py"
    target.write_text("def ok() -> int:\n    return 1\n", encoding="utf-8")
    spy = _CwdSpyRunner()
    pipeline = EvaluationPipeline(
        runner=spy,
        hypothesis_hook=_SilentHypothesis(),
        semantic_reviewer=_SilentSemantic(),
    )

    # Even if a caller wrongly passes the project as workspace, evaluate must ignore it.
    pipeline.evaluate(
        EvaluationRequest(
            spec=_minimal_spec(),
            target_path=str(target),
            code=target.read_text(encoding="utf-8"),
            workspace=str(project),
        )
    )

    assert spy.cwds, "expected tool commands to run"
    project_resolved = project.resolve()
    for cwd in spy.cwds:
        assert cwd is not None
        cwd_resolved = Path(cwd).resolve()
        # Tool cwd must not be the learner project (cache writes stay in sandbox).
        assert cwd_resolved != project_resolved
        assert not cwd_resolved.is_relative_to(project_resolved)

    assert not (project / ".pytest_cache").exists()
    assert target.read_text(encoding="utf-8").startswith("def ok")


def test_evaluate_snippet_tool_cwd_not_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "sentinel.py").write_text(SENTINEL_MARKER, encoding="utf-8")
    spy = _CwdSpyRunner()
    pipeline = EvaluationPipeline(
        runner=spy,
        hypothesis_hook=_SilentHypothesis(),
        semantic_reviewer=_SilentSemantic(),
    )

    pipeline.evaluate(
        EvaluationRequest(
            spec=_minimal_spec(),
            code="print('snippet')\n",
            workspace=str(project),
        )
    )

    project_resolved = project.resolve()
    for cwd in spy.cwds:
        assert cwd is not None
        cwd_resolved = Path(cwd).resolve()
        assert cwd_resolved != project_resolved
        assert not cwd_resolved.is_relative_to(project_resolved)
    assert not (project / ".pytest_cache").exists()


def test_plan_commands_refuses_missing_sandbox_cwd() -> None:
    pipeline = EvaluationPipeline(
        runner=_SilentRunner(),
        hypothesis_hook=_SilentHypothesis(),
        semantic_reviewer=_SilentSemantic(),
    )
    try:
        pipeline.plan_commands(
            EvaluationRequest(spec=_minimal_spec(), target_path="/tmp/x.py", code="x=1\n")
        )
        raise AssertionError("expected ValueError when workspace sandbox cwd is missing")
    except ValueError as exc:
        assert "sandbox cwd" in str(exc).lower() or "workspace" in str(exc).lower()
