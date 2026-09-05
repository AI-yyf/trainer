"""Durable, replay-only agent checkpoint coverage."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.api.routers import build_router
from app.api.runtime import TrainerRuntime
from app.core.models import ProviderConfig
from app.db.repository import TrainerRepository
from app.evaluator.service import EvaluatorService
from app.llm.provider_service import ProviderService
from app.llm.tools import ToolRegistry
from app.memory.service import MemoryService
from app.planner.service import PlannerService, TrainingPlannerService
from app.resources.service import ResourceService
from app.specs.service import SpecService


class ScriptedProvider:
    """Small tool-capable provider used to create one real agent trace."""

    protocol = "openai_chat_completions"
    attachments_will_be_sent = staticmethod(lambda: False)

    def __init__(self) -> None:
        self.calls = 0

    async def call(
        self,
        _messages: list[dict[str, Any]],
        _tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {"id": "recall-1", "name": "recall_memory", "arguments": {"focus": "async"}}
                ],
            }
        return {"content": "Start with one small async iteration check.", "tool_calls": []}

    async def call_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        response = await self.call(messages, tools)
        yield {
            "type": "final",
            "content": response["content"],
            "tool_calls": response["tool_calls"],
            "stop_reason": "tool_calls" if response["tool_calls"] else "stop",
        }


def make_runtime(database_path: Path) -> TrainerRuntime:
    repository = TrainerRepository(database_path)
    provider_service = ProviderService(
        config=ProviderConfig(
            name="scripted",
            base_url="https://example.invalid/v1",
            api_key_ref="trainer.test",
            model="scripted-model",
            capabilities={"tools": True, "streaming": True},
        ),
        api_key="sk-test",
    )
    runtime = TrainerRuntime(
        repository=repository,
        provider_service=provider_service,
        planner_service=PlannerService(TrainingPlannerService()),
        memory_service=MemoryService(repository),
        resource_service=ResourceService(
            repository,
            ingest_service=None,  # type: ignore[arg-type]
            semantic_memory=None,  # type: ignore[arg-type]
        ),
        spec_service=SpecService(),
        evaluator_service=EvaluatorService(),
    )
    provider = provider_service._config
    assert provider is not None
    seed_verified_capabilities(runtime, provider, "sk-test", tools=True)
    return runtime


def make_app(runtime: TrainerRuntime) -> FastAPI:
    app = FastAPI()
    app.include_router(build_router(runtime))
    return app


def start_session(client: TestClient, workspace_id: str) -> str:
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": "Checkpoint test",
            "profile": {"long_term_goal": "learn async", "weekly_hours": 2},
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["session_id"])


def test_agent_checkpoint_replays_after_runtime_restart_without_reexecution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "trainer.sqlite3"
    runtime = make_runtime(database_path)
    scripted = ScriptedProvider()
    tool_calls = 0
    real_invoke = ToolRegistry.invoke

    def build_agent_provider(self: ProviderService, **_: Any) -> tuple[ScriptedProvider, ScriptedProvider]:
        return scripted, scripted

    async def count_tool_calls(self: ToolRegistry, *args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal tool_calls
        tool_calls += 1
        return await real_invoke(self, *args, **kwargs)

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    monkeypatch.setattr(ToolRegistry, "invoke", count_tool_calls)

    with TestClient(make_app(runtime)) as client:
        session_id = start_session(client, "ws-checkpoint")
        turn = client.post(
            "/session/message",
            json={
                "workspace_id": "ws-checkpoint",
                "session_id": session_id,
                "message": "I am stuck on async iteration.",
                "use_agent_loop": True,
            },
        )
        assert turn.status_code == 200, turn.text
        checkpoint_id = str(turn.json()["agent_meta"]["checkpoint_id"])
        assert checkpoint_id.startswith("agent-turn-")
        assert turn.json()["agent_meta"]["recovery_available"] is True

    assert scripted.calls == 2
    assert tool_calls == 1

    # New runtime proves the trace survives process-memory loss. Replay and resume
    # must only read SQLite, never create another provider or tool invocation.
    restarted_runtime = make_runtime(database_path)

    async def provider_must_not_run(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("checkpoint replay unexpectedly called the provider")

    async def tool_must_not_run(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("checkpoint replay unexpectedly invoked a tool")

    monkeypatch.setattr(ProviderService, "coaching_reply_agentic", provider_must_not_run)
    monkeypatch.setattr(ToolRegistry, "invoke", tool_must_not_run)

    with TestClient(make_app(restarted_runtime)) as client:
        listed = client.get(
            "/session/checkpoints",
            params={"workspace_id": "ws-checkpoint", "session_id": session_id},
        )
        assert listed.status_code == 200, listed.text
        assert [item["checkpoint_id"] for item in listed.json()["checkpoints"]] == [checkpoint_id]

        read = client.post(
            f"/session/checkpoints/{checkpoint_id}/read",
            json={"workspace_id": "ws-checkpoint", "session_id": session_id},
        )
        assert read.status_code == 200, read.text
        trace = read.json()["trace"]
        assert trace["steps"]
        assert any(event["type"] == "tool_call" for event in trace["tool_events"])
        assert any(event["type"] == "tool_result" for event in trace["tool_events"])
        assert read.json()["final"]["content"]

        replay = client.post(
            f"/session/checkpoints/{checkpoint_id}/replay",
            json={"workspace_id": "ws-checkpoint", "session_id": session_id},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["mode"] == "stored_trace"
        assert replay.json()["executed"] is False
        assert replay.json()["checkpoint"]["checkpoint_id"] == checkpoint_id

        resume = client.post(
            f"/session/checkpoints/{checkpoint_id}/resume",
            json={"workspace_id": "ws-checkpoint", "session_id": session_id},
        )
        assert resume.status_code == 200, resume.text
        assert resume.json()["session_id"] == session_id
        assert resume.json()["requires_new_turn"] is True
        assert resume.json()["executed"] is False
        assert session_id in restarted_runtime.sessions

        malformed = client.post(
            "/session/checkpoints/not-a-checkpoint/replay",
            json={"workspace_id": "ws-checkpoint"},
        )
        assert malformed.status_code == 422

        cross_workspace = client.post(
            f"/session/checkpoints/{checkpoint_id}/replay",
            json={"workspace_id": "ws-other"},
        )
        assert cross_workspace.status_code == 404

    assert scripted.calls == 2
    assert tool_calls == 1
