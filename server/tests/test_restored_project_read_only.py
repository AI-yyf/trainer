"""(a) The learner's project (<ProjectRoot>) is strictly read-only for the coach.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents: these were behavioral tests.  Originals at
df0a3e2a^:
  * server/tests/test_coach_no_silent_project_write.py
  * server/tests/test_evaluate_no_project_mutation.py
  * server/tests/test_evaluator_project_copy.py
and, re-expressed on the Trainer 2.0 orthogonal primitives (8 tools with an `action`
argument instead of 43 legacy tools):
  * server/tests/test_sandbox_library_agent.py::test_sandbox_library_tools_write_read_and_never_touch_project
  * server/tests/test_resource_agent_organization.py::test_agent_tools_cannot_write_outside_sandbox_into_project_sentinel
  * the /turn variants of test_coach_no_silent_project_write.py driven through
    project_read / library_write / library_exec with hostile arguments.

Guarantees covered:
  * no tool call can create / modify / rename / delete a file under the project, and the
    project tree is byte-identical afterwards;
  * legacy or hallucinated write-tool names (write_file, apply_patch, edit_file, ...) are
    rejected and never advertised to the model on any of the four provider protocols;
  * path traversal, absolute-path and symlink escapes fail closed without leaking content;
  * <LibraryRoot> autonomy (library_write / library_exec / import) never reaches the project,
    including paths built at runtime inside a sandboxed child process;
  * evaluation and verification run tools in a throwaway sandbox copy, never in the project.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.api.runtime import TrainerRuntime
from app.core.config import Settings
from app.core.models import (
    EvaluateCurrentFileRequest,
    EvaluateSnippetRequest,
    LearningPlan,
    PlanStage,
    ProviderConfig,
)
from app.core.settings import AppSettings
from app.evaluator.models import (
    CheckCommand,
    CheckResult,
    CheckStatus,
    EvaluationRequest,
    SemanticReview,
)
from app.evaluator.service import EvaluationPipeline, EvaluatorService, _copy_project_to_sandbox
from app.llm.provider_service import ProviderService
from app.llm.tool_primitives import ORTHOGONAL_PRIMITIVE_NAMES
from app.llm.tools import (
    PROJECT_WRITE_TOOL_NAMES,
    ToolContext,
    ToolDefinition,
    build_default_tool_registry,
)
from app.main import create_app
from app.specs.models import RequirementItem, TaskSpec
from tests.client_fixtures import build_client

# ---------------------------------------------------------------------------
# Restored from test_coach_no_silent_project_write.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------

SENTINEL = "TRAINER_PROJECT_SENTINEL_UNCHANGED_v1\n"


def _runtime(client: TestClient) -> TrainerRuntime:
    """The sidecar runtime behind a test client.

    Starlette declares ``TestClient.app`` as the ``ASGIApp`` callable union, so the
    ``FastAPI`` (and runtime) narrowing has to happen at runtime before ``.state``.
    """
    application = client.app
    assert isinstance(application, FastAPI), "test client must wrap the Trainer FastAPI app"
    runtime = application.state.runtime
    assert isinstance(runtime, TrainerRuntime), "FastAPI app must expose a TrainerRuntime"
    return runtime


def _training_provider_payload() -> dict[str, object]:
    return {
        "name": "deterministic-agent",
        "base_url": "https://provider.invalid/v1",
        "api_key_ref": "test-only",
        "model": "test-model",
        "protocol": "openai_chat_completions",
        "capabilities": {"tools": True, "streaming": False},
    }


class _ScriptedProjectWriteProvider:
    protocol = "openai_chat_completions"

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        self.calls = 0
        self.tools_seen: list[list[dict[str, Any]] | None] = []
        self.attachments_will_be_sent = lambda: False

    async def call(
        self,
        _messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        self.tools_seen.append(tools)
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": f"silent-write-{self.tool_name}",
                        "name": self.tool_name,
                        "arguments": {
                            "path": "agent-wrote-business.py",
                            "content": "print('silent business write')\n",
                            "patch": "--- a/agent-wrote-business.py\n+++ b/agent-wrote-business.py\n",
                        },
                    }
                ],
            }
        return {
            "content": "Coach without writing your project files.",
            "tool_calls": [],
        }

    async def call_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ):
        response = await self.call(messages, tools)
        content = str(response.get("content") or "")
        tool_calls = list(response.get("tool_calls") or [])
        if content:
            yield {"type": "delta", "delta": content}
        yield {
            "type": "final",
            "content": content,
            "tool_calls": tool_calls,
            "stop_reason": "tool_calls" if tool_calls else "stop",
        }


def _schema_names(scripted: _ScriptedProjectWriteProvider) -> set[str]:
    return {
        schema.get("function", {}).get("name")
        for schema in (scripted.tools_seen[0] or [])
        if isinstance(schema, dict)
    }


def _seed_leftover(runtime: Any, workspace_id: str, *, plan_id: str) -> LearningPlan:
    leftover = LearningPlan(
        id=plan_id,
        title="Keep the leftover stage",
        current_step="Keep one auth check",
        why_now="Keep the leftover why",
        next_after_current="Then review the leftover path",
        stages=[
            PlanStage(
                id="stage-leftover",
                title="Leftover",
                goal="Stay leftover-not-live",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    runtime.repository.save_plan(workspace_id, leftover)
    return leftover


def _denied_write_tool_event(tool_events: list[Any], tool_name: str) -> bool:
    for event in tool_events:
        if not isinstance(event, dict):
            continue
        if event.get("type") != "tool_result" or event.get("name") != tool_name:
            continue
        raw_result = event.get("result")
        result = raw_result if isinstance(raw_result, dict) else {}
        if event.get("ok") is False or result.get("ok") is False:
            if (result.get("error") or event.get("error")) == "tool_not_available":
                return True
    return False


def _assert_project_untouched(project: Path, sentinel: Path, before: bytes) -> None:
    assert sentinel.read_bytes() == before
    assert not (project / "agent-wrote-business.py").exists()


@pytest.mark.asyncio
async def test_registry_denies_project_write_tools_even_if_hallucinated() -> None:
    registry = build_default_tool_registry()
    names = set(registry.names())
    for tool_name in PROJECT_WRITE_TOOL_NAMES:
        assert tool_name not in names
        result = await registry.invoke(
            ToolContext(runtime=None, workspace_id="ws-deny-write"),
            tool_name,
            {"path": "business.py", "content": "x"},
        )
        assert result["ok"] is False
        assert result["error"] == "tool_not_available"


@pytest.mark.parametrize("tool_name", sorted(PROJECT_WRITE_TOOL_NAMES))
def test_turn_leftover_not_live_denies_project_write_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    """Empty-restore leftover + `/turn` agent tools ON: write tools denied; no project file."""
    workspace_id = f"workspace-leftover-no-{tool_name}"
    project = tmp_path / "learner-project"
    project.mkdir()
    sentinel = project / "user-project.txt"
    sentinel.write_text(SENTINEL, encoding="utf-8")
    before = sentinel.read_bytes()
    scripted = _ScriptedProjectWriteProvider(tool_name)

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    with build_client(tmp_path / "sidecar", configure_provider=False) as client:
        runtime = _runtime(client)
        seed_verified_capabilities(
            runtime,
            ProviderConfig.model_validate(_training_provider_payload()),
            "test-only-key",
        )
        leftover = _seed_leftover(
            runtime,
            workspace_id,
            plan_id=f"plan-leftover-no-{tool_name}",
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Leftover no project write",
                "workspace_path": str(project),
            },
        )
        assert started.status_code == 200, started.text
        start_body = started.json()
        assert start_body.get("plan") in (None, {})
        session_id = start_body["session_id"]

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Please write the auth helper into my project.",
                "response_language": "en-US",
                "answer_mode": "guided",
                "use_agent_loop": True,
                "provider": _training_provider_payload(),
                "api_key": "test-only-key",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        agent_meta = body.get("agent_meta") or {}
        assert agent_meta.get("agentic") is True
        raw_tool_events = agent_meta.get("tool_events")
        tool_events = raw_tool_events if isinstance(raw_tool_events, list) else []
        assert _denied_write_tool_event(tool_events, tool_name), tool_events
        assert tool_name not in _schema_names(scripted)
        assert body.get("snapshot", body).get("plan") in (None, {})
        latest = runtime.repository.get_latest_plan(workspace_id)
        assert latest is not None, "a latest plan must still be recorded"
        assert latest.id == leftover.id
        _assert_project_untouched(project, sentinel, before)


@pytest.mark.parametrize("tool_name", ("write_file", "apply_patch"))
def test_turn_live_plan_coaching_still_denies_project_write_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    """Live formal plan coaching with tools still must not silent-write business code."""
    workspace_id = f"workspace-live-no-{tool_name}"
    project = tmp_path / "live-project"
    project.mkdir()
    sentinel = project / "user-project.txt"
    sentinel.write_text(SENTINEL, encoding="utf-8")
    before = sentinel.read_bytes()
    scripted = _ScriptedProjectWriteProvider(tool_name)

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    with build_client(tmp_path / "sidecar", configure_provider=False) as client:
        runtime = _runtime(client)
        seed_verified_capabilities(
            runtime,
            ProviderConfig.model_validate(_training_provider_payload()),
            "test-only-key",
        )
        live = LearningPlan(
            id=f"plan-live-no-{tool_name}",
            title="Live matching stage",
            current_step="Keep the live auth check",
            why_now="Live why",
            next_after_current="Then review",
            stages=[
                PlanStage(
                    id="stage-live",
                    title="Live",
                    goal="Stay live-bound",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        runtime.repository.save_plan(workspace_id, live)
        runtime.memory_service.structured_for_workspace(workspace_id).update_workspace(
            latest_plan_runtime={
                "current_step": live.current_step,
                "plan_id": live.id,
                "resume_state": "in_progress",
                "workspace_id": workspace_id,
            }
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Live plan no project write",
                "workspace_path": str(project),
            },
        )
        assert started.status_code == 200, started.text
        start_body = started.json()
        session_id = start_body["session_id"]
        assert (start_body.get("plan") or {}).get("id") == live.id

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Implement the auth helper in my repo for me.",
                "response_language": "en-US",
                "answer_mode": "guided",
                "use_agent_loop": True,
                "provider": _training_provider_payload(),
                "api_key": "test-only-key",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        agent_meta = body.get("agent_meta") or {}
        assert agent_meta.get("agentic") is True
        raw_tool_events = agent_meta.get("tool_events")
        tool_events = raw_tool_events if isinstance(raw_tool_events, list) else []
        assert _denied_write_tool_event(tool_events, tool_name), tool_events
        assert tool_name not in _schema_names(scripted)
        _assert_project_untouched(project, sentinel, before)


@pytest.mark.parametrize("tool_name", ("write_file", "apply_patch"))
def test_turn_stream_leftover_denies_project_write_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
) -> None:
    """Empty-restore leftover + `/turn/stream` agent tools: write denied; sentinel intact."""
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = f"workspace-stream-leftover-no-{tool_name}"
    project = tmp_path / "stream-project"
    project.mkdir()
    sentinel = project / "user-project.txt"
    sentinel.write_text(SENTINEL, encoding="utf-8")
    before = sentinel.read_bytes()
    scripted = _ScriptedProjectWriteProvider(tool_name)

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    with build_client(tmp_path / "sidecar", configure_provider=False) as client:
        runtime = _runtime(client)
        seed_verified_capabilities(
            runtime,
            ProviderConfig.model_validate(
                {
                    **_training_provider_payload(),
                    "capabilities": {"tools": True, "streaming": True},
                }
            ),
            "test-only-key",
        )
        leftover = _seed_leftover(
            runtime,
            workspace_id,
            plan_id=f"plan-stream-leftover-no-{tool_name}",
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Stream leftover no project write",
                "workspace_path": str(project),
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        assert started.json().get("plan") in (None, {})

        streamed = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Write the helper into my project files.",
                "response_language": "en-US",
                "answer_mode": "guided",
                "use_agent_loop": True,
                "provider": {
                    **_training_provider_payload(),
                    "capabilities": {"tools": True, "streaming": True},
                },
                "api_key": "test-only-key",
            },
        )
        assert streamed.status_code == 200, streamed.text
        body = completed_stream_response(streamed.text)
        raw_meta = body.get("agent_meta") or body.get("agent")
        assert isinstance(raw_meta, dict), "stream must carry agent metadata"
        agent_meta = raw_meta
        assert agent_meta.get("agentic") is True
        raw_tool_events = agent_meta.get("tool_events")
        tool_events = raw_tool_events if isinstance(raw_tool_events, list) else []
        assert _denied_write_tool_event(tool_events, tool_name), tool_events
        assert tool_name not in _schema_names(scripted)
        latest = runtime.repository.get_latest_plan(workspace_id)
        assert latest is not None, "a latest plan must still be recorded"
        assert latest.id == leftover.id
        _assert_project_untouched(project, sentinel, before)


"""Learning OS: coach agent must never silently write learner project/business code."""

# ---------------------------------------------------------------------------
# Restored from test_evaluate_no_project_mutation.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------

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
    runtime = _runtime(client)
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


"""Prove evaluate endpoints never mutate workspace project files."""

# ---------------------------------------------------------------------------
# Restored from test_evaluator_project_copy.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_project_copy_includes_tests_and_skips_tool_caches(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "queue_lock.py").write_text("import threading\n", encoding="utf-8")
    (project / "test_queue_lock.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (project / ".venv").mkdir()
    (project / ".venv" / "huge.bin").write_text("x", encoding="utf-8")
    (project / "__pycache__").mkdir()
    (project / "__pycache__" / "stale.pyc").write_text("x", encoding="utf-8")
    (project / "linked.py").symlink_to(project / "src" / "queue_lock.py")

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    assert _copy_project_to_sandbox(project, sandbox) is True
    assert (sandbox / "src" / "queue_lock.py").read_text(encoding="utf-8") == "import threading\n"
    assert (sandbox / "test_queue_lock.py").exists()
    assert not (sandbox / ".venv").exists()
    assert not (sandbox / "__pycache__").exists()
    assert not (sandbox / "linked.py").exists()


def test_missing_project_root_cannot_be_copied(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    assert _copy_project_to_sandbox(tmp_path / "missing", sandbox) is False


def test_project_copy_skips_non_regular_files(tmp_path: Path) -> None:
    import os

    project = tmp_path / "project"
    project.mkdir()
    (project / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    fifo = project / "pipe"
    try:
        os.mkfifo(fifo)
    except (AttributeError, OSError):
        return
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    try:
        assert _copy_project_to_sandbox(project, sandbox) is True
        assert (sandbox / "test_ok.py").exists()
        assert not (sandbox / "pipe").exists()
    finally:
        try:
            fifo.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Adapted for the Trainer 2.0 orthogonal primitives (8 tools instead of 43).
#
# The originals drove legacy tool names that no longer exist, so passing them
# verbatim would only prove that an unregistered name is unknown.  These drive
# the primitives a model actually sees at HEAD:
#   * tests/test_sandbox_library_agent.py::test_sandbox_library_tools_write_read_and_never_touch_project
#   * tests/test_resource_agent_organization.py::test_agent_tools_cannot_write_outside_sandbox_into_project_sentinel
#   * tests/test_coach_no_silent_project_write.py (agent-loop and /turn variants, re-expressed
#     on project_read / library_write / library_exec with hostile arguments)
# ---------------------------------------------------------------------------

_HALLUCINATED_WRITE_TOOLS: tuple[str, ...] = (
    "write_file",
    "apply_patch",
    "edit_file",
    "insert_code",
    "execute_command",
    "run_command",
    "write_workspace_file",
    "create_file",
    "delete_file",
    "move_file",
    "rename_file",
    "bash",
    "shell",
    "run_terminal_cmd",
    "python_exec",
    "str_replace_editor",
    "filesystem_write_file",
    "write",
    "edit",
    "multiedit",
    "notebook_edit",
)

_PROTOCOLS: tuple[str, ...] = (
    "openai_chat_completions",
    "openai_responses",
    "anthropic_messages",
    "gemini_generate_content",
)

_ORIGINAL_APP = "def greet(name: str) -> str:\n    return f'hi {name}'\n"


def _setup_project_ctx(
    tmp_path: Path,
    *,
    project_name: str = "learner_project",
) -> tuple[Any, ToolContext, Path, Path]:
    """Production-faithful layout: an adopted project with a dedicated Trainer root.

    <LibraryRoot> (Trainer-owned data) and <ProjectRoot> (learner-owned code) are
    different trees, exactly as after the extension's workspace admission.
    """
    trainer_root = tmp_path / "trainer_root"
    trainer_root.mkdir()
    project_root = tmp_path / project_name
    project_root.mkdir()
    (project_root / "app.py").write_text(_ORIGINAL_APP, encoding="utf-8")
    app = create_app(Settings(data_dir=trainer_root / ".trainer" / "runtime"))
    runtime = app.state.runtime
    provisioning = runtime.provision_project_adoption(
        workspace_id="ws-adopted-alias",
        root_path=str(trainer_root),
        project_path=str(project_root),
        project_name=project_name,
    )
    workspace_id = provisioning.context_id
    runtime.register_workspace_path(workspace_id, str(project_root))
    assert Path(runtime.resolve_library_carrier_root(workspace_id)) == trainer_root.resolve()
    library_root = Path(runtime.sandbox_service.ensure_operation_root(workspace_id)).resolve()
    assert not library_root.is_relative_to(project_root.resolve())
    ctx = ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id=provisioning.agent_session_id,
        response_language="en-US",
        extra={},
    )
    return runtime, ctx, project_root, library_root


def _tree_digest(root: Path) -> dict[str, str]:
    """path -> sha256 for every file under root, so 'unchanged' means byte-identical."""
    digest: dict[str, str] = {}
    for directory, _dirs, files in os.walk(root):
        for name in files:
            path = Path(directory) / name
            digest[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return digest


def _advertised_tool_names(schemas: list[dict[str, Any]]) -> list[str]:
    return [str((item.get("function") or item).get("name")) for item in schemas]


def test_registry_registers_exactly_the_eight_primitives() -> None:
    assert build_default_tool_registry().names() == list(ORTHOGONAL_PRIMITIVE_NAMES)


@pytest.mark.parametrize("tool_name", _HALLUCINATED_WRITE_TOOLS)
@pytest.mark.asyncio
async def test_hallucinated_project_write_tool_is_rejected(tool_name: str) -> None:
    """No runtime at all: a write-shaped tool name is refused before anything can run."""
    result = await build_default_tool_registry().invoke(
        ToolContext(runtime=None, workspace_id="ws-hallucinated"),
        tool_name,
        {
            "path": "agent-wrote.py",
            "content": "print('silent business write')\n",
            "patch": "--- a/app.py\n+++ b/app.py\n",
            "command": "rm app.py",
        },
    )
    assert result["ok"] is False
    assert result["error"] in {"tool_not_available", "unknown_tool"}


def test_no_protocol_advertises_a_project_write_tool_to_the_model() -> None:
    registry = build_default_tool_registry()
    for protocol in _PROTOCOLS:
        names = _advertised_tool_names(registry.as_protocol_schemas(protocol))
        assert names == list(ORTHOGONAL_PRIMITIVE_NAMES), protocol
        for forbidden in (*PROJECT_WRITE_TOOL_NAMES, *_HALLUCINATED_WRITE_TOOLS):
            assert forbidden not in names, (protocol, forbidden)


@pytest.mark.asyncio
async def test_discovered_tool_named_like_a_project_writer_is_never_invocable() -> None:
    """Dynamic discovery must not smuggle a writer in under a forbidden name."""
    invoked: list[dict[str, Any]] = []

    def _writer(_ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        invoked.append(args)
        return {"ok": True}

    registry = build_default_tool_registry(
        extra_tools=[
            ToolDefinition(
                name="apply_patch",
                description="discovered tool that collides with a forbidden name",
                parameters={"type": "object"},
                handler=_writer,
            )
        ]
    )
    for protocol in _PROTOCOLS:
        assert "apply_patch" not in _advertised_tool_names(registry.as_protocol_schemas(protocol))
    result = await registry.invoke(
        ToolContext(runtime=None, workspace_id="ws-colliding-extra"),
        "apply_patch",
        {"path": "app.py", "patch": "pwned"},
    )
    assert result["ok"] is False
    assert result["error"] == "tool_not_available"
    assert invoked == []


@pytest.mark.asyncio
async def test_every_project_read_and_verify_action_leaves_the_project_byte_identical(
    tmp_path: Path,
) -> None:
    _runtime, ctx, project_root, _library_root = _setup_project_ctx(tmp_path)
    (project_root / "pkg").mkdir()
    (project_root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (project_root / "pkg" / "util.py").write_text(
        "def helper() -> int:\n    return 1\n", encoding="utf-8"
    )
    ctx.extra = {
        "current_file": {"path": "app.py", "content": _ORIGINAL_APP, "language_id": "python"}
    }
    before = _tree_digest(project_root)
    registry = build_default_tool_registry()

    calls: tuple[tuple[str, dict[str, Any]], ...] = (
        ("project_read", {"action": "list"}),
        ("project_read", {"action": "list", "directory": "pkg"}),
        ("project_read", {"action": "read", "path": "app.py"}),
        ("project_read", {"action": "read", "path": "pkg/util.py", "start_line": 1, "end_line": 2}),
        ("project_read", {"action": "inspect_current"}),
        ("project_read", {"action": "modules"}),
        ("project_read", {"action": "symbol", "name": "greet"}),
        ("project_read", {"action": "impact"}),
        ("project_verify", {"action": "diagnostics", "path": "app.py"}),
        ("project_verify", {"action": "verify_practice", "acceptance_criteria": ["def greet"]}),
        (
            "project_verify",
            {
                "action": "compare_anchor",
                "anchor_text": "def greet(name: str) -> str:",
                "submission": "def greet(name: str) -> str:\n    return name\n",
            },
        ),
    )
    for tool_name, arguments in calls:
        result = await registry.invoke(ctx, tool_name, arguments)
        assert isinstance(result, dict) and isinstance(result.get("ok"), bool), (
            tool_name,
            arguments,
        )

    assert _tree_digest(project_root) == before


@pytest.mark.asyncio
async def test_project_read_fails_closed_on_traversal_absolute_and_symlink_escapes(
    tmp_path: Path,
) -> None:
    _runtime, ctx, project_root, _library_root = _setup_project_ctx(tmp_path)
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("OUTSIDE-SECRET-CONTENT\n", encoding="utf-8")
    try:
        (project_root / "link_to_outside.txt").symlink_to(outside)
    except OSError as exc:  # pragma: no cover - platforms without symlink privilege
        pytest.skip(f"Symlink creation is unavailable: {exc}")
    registry = build_default_tool_registry()
    before = _tree_digest(project_root)
    escapes = (
        "../outside_secret.txt",
        "pkg/../../outside_secret.txt",
        str(outside),
        "link_to_outside.txt",
        "pkg/../link_to_outside.txt",
        "/definitely/not/inside/the/project/secret.txt",
    )

    for escape in escapes:
        read = await registry.invoke(ctx, "project_read", {"action": "read", "path": escape})
        assert read["ok"] is False, (escape, read)
        listed = await registry.invoke(ctx, "project_read", {"action": "list", "directory": escape})
        assert listed["ok"] is False, (escape, listed)
        diagnostics = await registry.invoke(
            ctx, "project_verify", {"action": "diagnostics", "path": escape}
        )
        assert diagnostics["ok"] is False, (escape, diagnostics)

    # The coach may read what is really inside <ProjectRoot>; the symlink is not that.
    inside = await registry.invoke(ctx, "project_read", {"action": "read", "path": "app.py"})
    assert inside["ok"] is True
    assert inside["content"] == _ORIGINAL_APP
    assert _tree_digest(project_root) == before


@pytest.mark.asyncio
async def test_project_read_and_verify_reject_write_shaped_actions(tmp_path: Path) -> None:
    _runtime, ctx, project_root, _library_root = _setup_project_ctx(tmp_path)
    before = _tree_digest(project_root)
    registry = build_default_tool_registry()
    hostile = {
        "path": "app.py",
        "content": "pwned\n",
        "new_path": "renamed.py",
        "old_text": "hi",
        "new_text": "pwned",
        "command": "rm app.py",
    }
    for action in ("write", "edit", "delete", "move", "rename", "create", "patch", "execute"):
        read = await registry.invoke(ctx, "project_read", {"action": action, **hostile})
        assert read["ok"] is False and read["error"] == "invalid_action", (action, read)
    for action in ("write", "edit", "delete", "run", "execute", "shell", "fix"):
        verify = await registry.invoke(ctx, "project_verify", {"action": action, **hostile})
        assert verify["ok"] is False and verify["error"] == "invalid_action", (action, verify)

    assert _tree_digest(project_root) == before


@pytest.mark.asyncio
async def test_project_read_ignores_smuggled_write_arguments(tmp_path: Path) -> None:
    _runtime, ctx, project_root, _library_root = _setup_project_ctx(tmp_path)
    before = _tree_digest(project_root)
    result = await build_default_tool_registry().invoke(
        ctx,
        "project_read",
        {
            "action": "read",
            "path": "app.py",
            "content": "overwritten by a smuggled argument\n",
            "create": True,
            "write": True,
            "replace_all": True,
        },
    )
    assert result["ok"] is True
    assert result["content"] == _ORIGINAL_APP
    assert _tree_digest(project_root) == before


@pytest.mark.asyncio
async def test_library_write_cannot_reach_the_project(tmp_path: Path) -> None:
    """<LibraryRoot> autonomy never extends to the learner's project, whatever the action."""
    _runtime, ctx, project_root, library_root = _setup_project_ctx(tmp_path)
    ctx.extra = {"library_sandbox_work": True}
    registry = build_default_tool_registry()
    seeded = await registry.invoke(
        ctx, "library_write", {"action": "write", "path": "notes/a.md", "content": "alpha\n"}
    )
    assert seeded["ok"] is True
    before = _tree_digest(project_root)

    attempts: tuple[tuple[str, dict[str, Any]], ...] = (
        ("write", {"path": "../learner_project/agent-wrote.py", "content": "pwned\n"}),
        ("write", {"path": "../../learner_project/agent-wrote.py", "content": "pwned\n"}),
        ("write", {"path": str(project_root / "agent-wrote.py"), "content": "pwned\n"}),
        ("write", {"path": str(project_root / "app.py"), "content": "pwned\n"}),
        ("edit", {"path": "../learner_project/app.py", "old_text": "hi", "new_text": "pwned"}),
        ("mkdir", {"path": "../learner_project/agent-dir"}),
        ("mkdir", {"path": str(project_root / "agent-dir")}),
        ("rename", {"path": "notes/a.md", "new_path": "../../learner_project/a.md"}),
        ("rename", {"path": "notes/a.md", "new_path": str(project_root / "a.md")}),
        ("soft_delete", {"path": "../learner_project/app.py"}),
        ("soft_delete", {"path": str(project_root / "app.py")}),
    )
    for action, arguments in attempts:
        arguments = {"action": action, **arguments}
        result = await registry.invoke(ctx, "library_write", arguments)
        assert result["ok"] is False, (action, arguments, result)
        assert _tree_digest(project_root) == before, (action, arguments)

    # A restore may not be redirected out of the library either.
    trashed = await registry.invoke(
        ctx, "library_write", {"action": "soft_delete", "path": "notes/a.md"}
    )
    assert trashed["ok"] is True
    for restore_path in ("../../learner_project/a.md", str(project_root / "a.md")):
        escaped = await registry.invoke(
            ctx,
            "library_write",
            {"action": "restore", "path": trashed["trashed_path"], "restore_path": restore_path},
        )
        assert escaped["ok"] is False, (restore_path, escaped)
        assert trashed["trashed_path"] and (library_root / trashed["trashed_path"]).exists()

    assert _tree_digest(project_root) == before
    assert not (library_root / "notes" / "a.md").exists()


@pytest.mark.asyncio
async def test_library_read_cannot_read_the_project_or_files_outside_the_library(
    tmp_path: Path,
) -> None:
    _runtime, ctx, project_root, _library_root = _setup_project_ctx(tmp_path)
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("OUTSIDE-SECRET-CONTENT\n", encoding="utf-8")
    registry = build_default_tool_registry()
    before = _tree_digest(project_root)

    targets = (
        "../../learner_project/app.py",
        str(project_root / "app.py"),
        "../outside_secret.txt",
        str(outside),
    )
    for target in targets:
        read = await registry.invoke(ctx, "library_read", {"action": "read_file", "path": target})
        assert read["ok"] is False, (target, read)
        grep = await registry.invoke(
            ctx, "library_read", {"action": "grep", "query": "greet", "path": target}
        )
        assert grep["ok"] is False and not grep.get("matches"), (target, grep)
        assert "OUTSIDE-SECRET-CONTENT" not in json.dumps(read, default=str)
        assert "return f'hi" not in json.dumps(read, default=str)

    assert _tree_digest(project_root) == before


@pytest.mark.asyncio
async def test_import_workspace_copies_project_file_into_library_without_modifying_project(
    tmp_path: Path,
) -> None:
    """Importing is a copy *into* <LibraryRoot>; the project file itself is never touched.

    Non-Markdown imports are stored as canonical Markdown (see the resource-grounding
    file), so the copy is located by its stem rather than by a hard-coded extension.
    """
    _runtime, ctx, project_root, library_root = _setup_project_ctx(tmp_path)
    ctx.extra = {"library_sandbox_work": True}
    before = _tree_digest(project_root)

    imported = await build_default_tool_registry().invoke(
        ctx, "library_write", {"action": "import_workspace", "path": "app.py"}
    )
    assert imported["ok"] is True, imported
    assert imported["imported"] is True
    assert imported["source"] == "workspace_disk"
    copies = [
        path
        for path in (library_root / "sources" / "workspace").iterdir()
        if path.is_file() and path.stem == "app"
    ]
    assert copies, sorted(p.name for p in (library_root / "sources" / "workspace").iterdir())
    assert "def greet" in copies[0].read_text(encoding="utf-8")
    assert _tree_digest(project_root) == before


@pytest.mark.asyncio
async def test_library_writes_imports_and_exec_outputs_stay_out_of_the_project(
    tmp_path: Path,
) -> None:
    """Every <LibraryRoot> mutation channel, exercised for real on an adopted project."""
    runtime, ctx, project_root, library_root = _setup_project_ctx(tmp_path)
    trainer_root = tmp_path / "trainer_root"
    ctx.extra = {
        "library_sandbox_work": True,
        "allow_coach_only_tools": True,
        "explicit_lecture_note_save_request": True,
    }
    before = _tree_digest(project_root)
    registry = build_default_tool_registry()

    written = await registry.invoke(
        ctx,
        "library_write",
        {"action": "write", "path": "notes/summary.md", "content": "# Summary\n"},
    )
    assert written["ok"] is True and written["auto_indexed"] is True
    lecture = await registry.invoke(
        ctx,
        "library_write",
        {
            "action": "save_lecture_note",
            "title": "Attention Scaling Note",
            "content": "Dot products grow in variance with d_k.",
        },
    )
    assert lecture["ok"] is True, lecture
    executed = await registry.invoke(
        ctx,
        "library_exec",
        {
            "command": (
                'python3 -c "from pathlib import Path; '
                "Path('exec_output.md').write_text('# exec output\\n'); print('done')\""
            )
        },
    )
    assert executed["ok"] is True, executed
    assert "exec_output.md" in executed["auto_indexed_paths"]

    assert _tree_digest(project_root) == before
    assert not (project_root / "Trainer Library").exists()
    assert not (project_root / ".trainer").exists()
    canonical = trainer_root / "Trainer Library" / ".trainer-resources" / "markdown"
    assert canonical.is_dir() and any(canonical.glob("*.md"))
    assert library_root.is_relative_to(trainer_root)


@pytest.mark.asyncio
async def test_library_exec_rejects_commands_that_target_the_project(tmp_path: Path) -> None:
    _runtime, ctx, project_root, _library_root = _setup_project_ctx(tmp_path)
    ctx.extra = {"library_sandbox_work": True}
    before = _tree_digest(project_root)
    registry = build_default_tool_registry()

    app_py = project_root / "app.py"
    agent_py = project_root / "agent-wrote.py"
    overwrite = "python3 -c " + shlex.quote(f"open({str(app_py)!r}, 'w').write('pwned')")
    commands = (
        f"cat {app_py}",
        f"cat '{app_py}'",
        "cat ../../learner_project/app.py",
        f"echo pwned > {agent_py}",
        overwrite,
        f"ls {project_root}",
    )
    for command in commands:
        result = await registry.invoke(ctx, "library_exec", {"command": command})
        assert result["ok"] is False and result["error"] == "command_blocked", (command, result)

    assert _tree_digest(project_root) == before


def _dynamic_path_command(library_root: Path, target: Path, body: str) -> str:
    """A python one-liner that builds `target` from the child's cwd at runtime.

    The project path never appears in the command text, so the static validator
    cannot be what stops it: only the in-process audit hook / kernel sandbox can.
    """
    relative = Path(os.path.relpath(target, library_root))
    ups = [part for part in relative.parts if part == ".."]
    rest = [part for part in relative.parts if part != ".."]
    base = "os.getcwd()"
    for _ in ups:
        base = f"os.path.dirname({base})"
    joined = ", ".join(repr(part) for part in rest)
    return f'python3 -c "import os; p = os.path.join({base}, {joined}); {body}"'


@pytest.mark.skipif(shutil.which("python3") is None, reason="library_exec needs a python3 on PATH")
@pytest.mark.asyncio
async def test_library_exec_runtime_guard_blocks_dynamically_built_project_paths(
    tmp_path: Path,
) -> None:
    _runtime, ctx, project_root, library_root = _setup_project_ctx(tmp_path)
    ctx.extra = {"library_sandbox_work": True}
    registry = build_default_tool_registry()
    before = _tree_digest(project_root)

    read = await registry.invoke(
        ctx,
        "library_exec",
        {
            "command": _dynamic_path_command(
                library_root, project_root / "app.py", "print(open(p).read())"
            )
        },
    )
    assert read["ok"] is False, read
    assert "return f'hi" not in read.get("stdout", "")

    created = await registry.invoke(
        ctx,
        "library_exec",
        {
            "command": _dynamic_path_command(
                library_root, project_root / "agent-wrote.py", "open(p, 'w').write('pwned')"
            )
        },
    )
    overwritten = await registry.invoke(
        ctx,
        "library_exec",
        {
            "command": _dynamic_path_command(
                library_root, project_root / "app.py", "open(p, 'w').write('pwned')"
            )
        },
    )
    for result in (created, overwritten):
        assert result["ok"] is False, result
    assert not (project_root / "agent-wrote.py").exists()
    assert _tree_digest(project_root) == before

    # Non-vacuous: the denial must come from the sandbox guard, not from an unrelated crash
    # (e.g. a missing environment variable would also make the child exit non-zero).
    for result in (read, created, overwritten):
        assert result.get("error") == "sandbox_unavailable" or "Sandbox blocked" in result.get(
            "stderr", ""
        ), result


@pytest.mark.skipif(shutil.which("python3") is None, reason="library_exec needs a python3 on PATH")
@pytest.mark.asyncio
async def test_library_exec_runtime_guard_blocks_reads_of_host_files_outside_all_roots(
    tmp_path: Path,
) -> None:
    """Replacement for the retired env-var probe: the child env is allow-listed, so a
    location passed via $ENV never reaches the child and such a test passes vacuously."""
    _runtime, ctx, _project_root, library_root = _setup_project_ctx(tmp_path)
    ctx.extra = {"library_sandbox_work": True}
    secret = tmp_path / "fake_home" / ".ssh" / "id_rsa"
    secret.parent.mkdir(parents=True)
    secret.write_text("PRIVATE_KEY_PAYLOAD", encoding="utf-8")

    result = await build_default_tool_registry().invoke(
        ctx,
        "library_exec",
        {"command": _dynamic_path_command(library_root, secret, "print(open(p).read())")},
    )
    assert result["ok"] is False, result
    assert "PRIVATE_KEY_PAYLOAD" not in result.get("stdout", "")
    assert result.get("error") == "sandbox_unavailable" or "Sandbox blocked" in result.get(
        "stderr", ""
    ), result


class _ScriptedPrimitiveProvider:
    """Emits one chosen tool call, then answers; records the schemas the model was offered."""

    protocol = "openai_chat_completions"

    def __init__(self, tool_calls: list[tuple[str, dict[str, Any]]]) -> None:
        self.tool_calls = list(tool_calls)
        self.tools_seen: list[list[dict[str, Any]] | None] = []
        self.attachments_will_be_sent = lambda: False

    async def call(
        self, _messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        self.tools_seen.append(tools)
        if self.tool_calls:
            name, arguments = self.tool_calls.pop(0)
            return {
                "content": "",
                "tool_calls": [{"id": f"call-{name}", "name": name, "arguments": arguments}],
            }
        return {
            "content": "I can't change project files; here is what you should edit.",
            "tool_calls": [],
        }

    async def call_stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None):
        response = await self.call(messages, tools)
        content = str(response.get("content") or "")
        if content:
            yield {"type": "delta", "delta": content}
        yield {
            "type": "final",
            "content": content,
            "tool_calls": list(response.get("tool_calls") or []),
            "stop_reason": "tool_calls" if response.get("tool_calls") else "stop",
        }


_PROJECT_WRITE_ATTEMPTS: tuple[tuple[str, dict[str, Any], set[str]], ...] = (
    ("write_file", {"path": "agent-wrote.py", "content": "pwned\n"}, {"tool_not_available"}),
    ("apply_patch", {"path": "app.py", "patch": "pwned"}, {"tool_not_available"}),
    (
        "project_read",
        {"action": "write", "path": "app.py", "content": "pwned\n"},
        {"invalid_action"},
    ),
    (
        "project_read",
        {"action": "read", "path": "../outside_secret.txt"},
        {"not_found"},
    ),
    (
        "library_write",
        {"action": "write", "path": "../learner_project/agent-wrote.py", "content": "pwned\n"},
        {"tool_not_available", "invalid_path", "library_write_not_requested"},
    ),
    (
        "library_exec",
        {"command": "echo pwned > ../../learner_project/agent-wrote.py"},
        {"tool_not_available", "command_blocked", "library_write_not_requested"},
    ),
)


def _denied_tool_results(agent_meta: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        event
        for event in agent_meta.get("tool_events") or []
        if isinstance(event, dict) and event.get("type") == "tool_result"
    ]


def test_turn_denies_every_project_write_attempt_a_model_can_make(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/turn with the agent loop on: each attempt is reported as a failed tool result,
    no write-shaped tool is ever advertised, and the project stays byte-identical."""
    project = tmp_path / "learner_project"
    project.mkdir()
    (project / "app.py").write_text(_ORIGINAL_APP, encoding="utf-8")
    before = _tree_digest(project)
    scripted = _ScriptedPrimitiveProvider([])

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    with build_client(tmp_path / "sidecar", configure_provider=False) as client:
        seed_verified_capabilities(
            _runtime(client),
            ProviderConfig.model_validate(_training_provider_payload()),
            "test-only-key",
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": "ws-turn-primitive-write-denial",
                "workspace_name": "Primitive project write denial",
                "workspace_path": str(project),
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        for attempt, (tool_name, arguments, allowed_errors) in enumerate(_PROJECT_WRITE_ATTEMPTS):
            scripted.tool_calls = [(tool_name, arguments)]  # exactly one attempt per turn
            # A byte-identical /turn would be served from the request-dedupe cache.
            message = f"Write the auth helper into my project app.py for me. (attempt {attempt})"
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": "ws-turn-primitive-write-denial",
                    "intent": "coach",
                    "message": message,
                    "response_language": "en-US",
                    "answer_mode": "guided",
                    "use_agent_loop": True,
                    "provider": _training_provider_payload(),
                    "api_key": "test-only-key",
                },
            )
            assert response.status_code == 200, response.text
            agent_meta = response.json().get("agent_meta") or {}
            assert agent_meta.get("agentic") is True, (tool_name, agent_meta)
            fresh = _denied_tool_results(agent_meta)
            assert [event.get("name") for event in fresh] == [tool_name], (tool_name, fresh)
            result = fresh[0].get("result") or {}
            assert result.get("ok") is False, (tool_name, fresh[0])
            assert result.get("error") in allowed_errors, (tool_name, fresh[0])
            assert _tree_digest(project) == before, (tool_name, arguments)

    for forbidden in PROJECT_WRITE_TOOL_NAMES:
        assert all(
            forbidden not in _advertised_tool_names(schemas or [])
            for schemas in scripted.tools_seen
        ), forbidden
