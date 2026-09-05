"""Learning OS: coach agent must never silently write learner project/business code."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from provider_fixtures import seed_verified_capabilities

from app.core.models import LearningPlan, PlanStage, ProviderConfig
from app.llm.provider_service import ProviderService
from app.llm.tools import PROJECT_WRITE_TOOL_NAMES, ToolContext, build_default_tool_registry
from tests.test_api import build_client

SENTINEL = "TRAINER_PROJECT_SENTINEL_UNCHANGED_v1\n"


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
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
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
        runtime = client.app.state.runtime
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
        tool_events = agent_meta.get("tool_events") or []
        assert _denied_write_tool_event(tool_events, tool_name), tool_events
        assert tool_name not in _schema_names(scripted)
        assert body.get("snapshot", body).get("plan") in (None, {})
        assert runtime.repository.get_latest_plan(workspace_id).id == leftover.id
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
        runtime = client.app.state.runtime
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
        tool_events = agent_meta.get("tool_events") or []
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
        runtime = client.app.state.runtime
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
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert agent_meta.get("agentic") is True
        tool_events = agent_meta.get("tool_events") or []
        assert _denied_write_tool_event(tool_events, tool_name), tool_events
        assert tool_name not in _schema_names(scripted)
        assert runtime.repository.get_latest_plan(workspace_id).id == leftover.id
        _assert_project_untouched(project, sentinel, before)
