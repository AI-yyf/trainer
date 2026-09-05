"""End-to-end human simulation: drive the real FastAPI app through the
agent-loop coaching turn with a scripted provider — no API key needed.

These tests prove the agent loop is wired all the way through the public
HTTP surface:

* ``/session/start`` accepts the workspace path so workspace tools can
  resolve files, then ``/session/message`` routes through
  ``coaching_reply_agentic`` because the ProviderService is configured for
  tool-capable turns.
* The scripted provider returns a tool-call on turn 1 (``recall_memory``),
  then a final reply on turn 2. The turn 1 tool runs against the real
  ``MemoryService`` snapshot, so we know the runtime-shaped ToolContext
  reached the registry.
* The streaming endpoint emits ``event: tool_call`` and
  ``event: tool_result`` SSE frames + a ``data: {chunk}`` for the final
  assistant text + a single ``event: complete`` envelope.

We avoid Qdrant by passing ``semantic_memory=None`` to ``ResourceService``
the same way ``test_training_flow_integration.py`` already does.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.api.routers import build_router
from app.api.runtime import TrainerRuntime
from app.core.models import (
    ActiveCardSelectionResult,
    ImplementationGuide,
    ProviderConfig,
    TrainingCardCandidateSnapshot,
)
from app.db.repository import TrainerRepository
from app.evaluator.service import EvaluatorService
from app.llm.provider_service import ProviderService
from app.memory.service import MemoryService
from app.planner.service import PlannerService, TrainingPlannerService
from app.resources.service import ResourceService
from app.specs.service import SpecService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime(tmp_path: Path) -> TrainerRuntime:
    repo = TrainerRepository(tmp_path / "trainer.db")
    provider_config = ProviderConfig(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_ref="trainer.test",
        model="gpt-4o-mini",
        capabilities={"tools": True, "streaming": True},
    )
    provider_service = ProviderService(
        config=provider_config,
        api_key="sk-test-fake",
    )
    runtime = TrainerRuntime(
        repository=repo,
        provider_service=provider_service,
        planner_service=PlannerService(TrainingPlannerService()),
        memory_service=MemoryService(repo),
        resource_service=ResourceService(
            repo,
            ingest_service=None,  # type: ignore[arg-type]
            semantic_memory=None,  # type: ignore[arg-type]
        ),
        spec_service=SpecService(),
        evaluator_service=EvaluatorService(),
    )
    seed_verified_capabilities(runtime, provider_config, "sk-test-fake")
    return runtime


@pytest.fixture(autouse=True)
def verified_provider_capabilities(
    runtime: TrainerRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_verified_capabilities(
        runtime,
        runtime.provider_service._config,
        runtime.provider_service._api_key,
    )
    original = runtime.provider_service_for

    def provider_service_for(provider_config: ProviderConfig, api_key: str | None) -> ProviderService:
        service = original(provider_config, api_key)
        seed_verified_capabilities(runtime, provider_config, api_key or "")
        return service

    monkeypatch.setattr(runtime, "provider_service_for", provider_service_for)


@pytest.fixture
def app(runtime: TrainerRuntime) -> FastAPI:
    instance = FastAPI()
    instance.include_router(build_router(runtime))
    return instance


# ---------------------------------------------------------------------------
# Scripted provider — replaces the real OpenAI client
# ---------------------------------------------------------------------------


class ScriptedAgentProvider:
    """Drop-in for ``ProviderAgentBinding`` returned by
    ``ProviderService.build_agent_provider`` in tests. Plays back a fixed
    sequence of provider responses (one per loop step).
    """

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.protocol = "openai_chat_completions"
        self.calls_seen: list[list[dict[str, Any]]] = []
        self.tools_seen: list[list[dict[str, Any]] | None] = []
        self.attachments_will_be_sent = lambda: False  # type: ignore[assignment]

    async def call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        self.calls_seen.append(list(messages))
        self.tools_seen.append(tools)
        if self._index >= len(self._responses):
            return {"content": "(scripted provider exhausted)", "tool_calls": []}
        response = self._responses[self._index]
        self._index += 1
        return {
            "content": str(response.get("content") or ""),
            "tool_calls": list(response.get("tool_calls") or []),
        }

    async def call_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls_seen.append(list(messages))
        self.tools_seen.append(tools)
        if self._index >= len(self._responses):
            yield {
                "type": "final",
                "content": "(scripted provider exhausted)",
                "tool_calls": [],
                "stop_reason": "stop",
            }
            return
        response = self._responses[self._index]
        self._index += 1
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


def _patch_provider(
    monkeypatch: pytest.MonkeyPatch,
    runtime: TrainerRuntime,
    responses: list[dict[str, Any]],
) -> ScriptedAgentProvider:
    scripted = ScriptedAgentProvider(responses)

    def _build(self: ProviderService, **_: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", _build)
    return scripted


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _seed_session(client: TestClient, *, workspace_id: str, workspace_path: str | None = None) -> str:
    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "workspace_name": "Trainer Test",
        "profile": {
            "long_term_goal": "ship fast feedback loops",
            "weekly_hours": 4,
            "teaching_style": "hands-on",
            "answer_policy": "guided",
        },
    }
    if workspace_path is not None:
        payload["workspace_path"] = workspace_path
    response = client.post("/session/start", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    return str(body["session_id"])


def _upload_and_index_markdown(
    client: TestClient,
    *,
    workspace_id: str,
    name: str,
    text: str,
) -> dict[str, Any]:
    upload = client.post(
        "/resource/upload",
        json={
            "workspace_id": workspace_id,
            "kind": "markdown",
            "name": name,
            "source": f"inline://{name}",
            "content": text,
            "content_encoding": "utf-8",
            "tags": ["agent-loop", "library-first"],
        },
    )
    assert upload.status_code == 200, upload.text
    uploaded = upload.json()

    indexed = client.post(
        "/resource/index",
        json={
            "workspace_id": workspace_id,
            "resource_id": uploaded["id"],
            "enable_network": False,
        },
    )
    assert indexed.status_code == 200, indexed.text
    return indexed.json()


def test_session_message_runs_agent_loop_and_returns_tool_events(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_path = tmp_path / "ws"
    workspace_path.mkdir()
    (workspace_path / "main.py").write_text("print('hi')\n", encoding="utf-8")

    scripted = _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "recall_memory", "arguments": {"focus": "async"}},
                ],
            },
            {
                "content": "Re-anchor on async iteration. Try one minimal patch.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(
            client,
            workspace_id="ws-1",
            workspace_path=str(workspace_path),
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-1",
                "use_agent_loop": True,
                "message": "I keep losing the thread on async iteration.",
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    # Reply text from the second scripted turn must end up in the snapshot reply.
    reply_content = body["reply"]["content"]
    assert "async iteration" in reply_content or reply_content.strip() != ""
    # agent_meta must reflect that the loop ran.
    assert body.get("agent_meta", {}).get("agentic") is True
    tool_events = body["agent_meta"]["tool_events"]
    assert any(
        event["type"] == "tool_call" and event.get("name") == "recall_memory"
        for event in tool_events
    )
    assert any(event["type"] == "tool_result" for event in tool_events)
    coach_visible_status = body["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["type"] == "coach_visible_status"
    assert coach_visible_status["status"] == "done"
    assert coach_visible_status["source"] == "agent_loop"
    assert coach_visible_status["stopReason"] == "completed"
    assert coach_visible_status["toolNames"] == ["recall_memory"]
    assert coach_visible_status["stepCount"] == 1
    reply_parts = body["reply"]["metadata"]["parts"]
    assert sum(1 for part in reply_parts if part["type"] == "coach_visible_status") == 1
    assert any(
        part["type"] == "tool_call" and part.get("name") == "recall_memory"
        for part in reply_parts
    )
    assert any(
        part["type"] == "tool_result" and part.get("name") == "recall_memory"
        for part in reply_parts
    )
    # Two scripted responses → two model calls observed.
    assert len(scripted.calls_seen) == 2
    assert "attachments_present" not in body["reply"]["metadata"]
    assert "attachments_delivered_to_model" not in body["reply"]["metadata"]


def test_session_message_provider_override_infers_anthropic_tool_capabilities(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "recall_memory", "arguments": {"focus": "remote boundary"}},
                ],
            },
            {
                "content": "Start by naming which host owns the workspace path.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-override-anthropic")
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-override-anthropic",
                "use_agent_loop": True,
                "message": "Help me reason about remote workspace ownership.",
                "provider": {
                    "name": "MiniMax gateway",
                    "api": "anthropic",
                    "baseUrl": "http://minimax.redfast.top",
                    "apiKeyRef": "trainer.override",
                    "model": "MiniMax-M3",
                },
                "api_key": "sk-test-override",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("agent_meta", {}).get("agentic") is True
    coach_visible_status = body["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["toolNames"] == ["recall_memory"]
    assert "workspace path" in body["reply"]["content"]
    assert len(scripted.calls_seen) == 2
    assert scripted.tools_seen
    assert any(
        (tool.get("name") or tool.get("function", {}).get("name")) == "recall_memory"
        for tool in (scripted.tools_seen[0] or [])
    )


def test_session_message_auto_library_lookup_primes_agent_prompt(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime.resource_service.semantic_memory = SimpleNamespace(
        upsert_text=lambda *_args, **_kwargs: None,
    )
    scripted = _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "Start by naming which host owns the workspace path.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-auto-library")
        _upload_and_index_markdown(
            client,
            workspace_id="ws-auto-library",
            name="mirrorlock-remote.md",
            text=(
                "# MirrorLock protocol\n"
                "MirrorLock protocol is a teaching-only remote boundary mnemonic for VS Code Remote SSH.\n"
                "\n"
                "Step 1 - Name the host: say whether the path belongs to local Windows or remote Linux.\n"
                "Step 2 - Verify the owner: run `pwd` in the remote terminal and compare it with the VS Code Explorer path.\n"
                "Step 3 - Lock the action: only install, debug, or edit on the host that owns the workspace path.\n"
                "Boundary sentinel: host-ownership lockstep.\n"
            ),
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-auto-library",
                "use_agent_loop": True,
                "message": "Teach me MirrorLock protocol for VS Code Remote SSH.",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("agent_meta", {}).get("agentic") is True
    assert len(scripted.calls_seen) == 1
    system_prompt = str(scripted.calls_seen[0][0].get("content") or "")
    user_prompt = str(scripted.calls_seen[0][1].get("content") or "")
    assert "Requested grounding: Auto-grounded this turn" in system_prompt
    assert "prepared library grounding for this turn" in system_prompt
    assert "preserve this prepared library sequence exactly" in system_prompt
    assert "restate every step in order in the visible reply" in system_prompt
    assert user_prompt == "Teach me MirrorLock protocol for VS Code Remote SSH."
    assert "Auto-grounded this turn in 1 likely library hits" in system_prompt
    assert "mirrorlock-remote.md" in system_prompt
    assert "Prepared library sequence:" in system_prompt
    assert "Restate every library step in order before you continue." in system_prompt
    assert "Step 3: Lock the action: only install, debug, or edit on the host that owns the workspace path." in system_prompt
    assert "Boundary sentinel: host-ownership lockstep." in system_prompt
    tool_events = body["agent_meta"]["tool_events"]
    assert [event["type"] for event in tool_events[:2]] == ["tool_call", "tool_result"]
    assert tool_events[0]["name"] == "search_resources"
    assert tool_events[0]["auto"] is True
    assert tool_events[1]["name"] == "search_resources"
    assert tool_events[1]["result"]["auto"] is True
    assert tool_events[1]["result"]["hits"][0]["title"] == "mirrorlock-remote.md"
    coach_visible_status = body["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["source"] == "agent_loop"
    assert coach_visible_status["toolNames"] == ["search_resources"]
    assert "resources" in coach_visible_status["summary"].lower()


def test_session_message_auto_library_lookup_is_visible_for_plain_chat(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime.resource_service.semantic_memory = SimpleNamespace(
        upsert_text=lambda *_args, **_kwargs: None,
    )

    async def fake_coaching_reply(
        self: ProviderService,
        profile: object,
        message: str,
        *args: object,
        **kwargs: object,
    ) -> str:
        return "Start by naming which host owns the workspace path."

    monkeypatch.setattr(ProviderService, "coaching_reply", fake_coaching_reply)

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-auto-library-plain")
        _upload_and_index_markdown(
            client,
            workspace_id="ws-auto-library-plain",
            name="mirrorlock-remote.md",
            text=(
                "# MirrorLock protocol\n"
                "MirrorLock protocol is a teaching-only remote boundary mnemonic for VS Code Remote SSH.\n"
                "\n"
                "Step 1 - Name the host: say whether the path belongs to local Windows or remote Linux.\n"
                "Step 2 - Verify the owner: run `pwd` in the remote terminal and compare it with the VS Code Explorer path.\n"
                "Step 3 - Lock the action: only install, debug, or edit on the host that owns the workspace path.\n"
            ),
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-auto-library-plain",
                "message": "Teach me MirrorLock protocol for VS Code Remote SSH.",
                "provider": {
                    "name": "plain-compatible",
                    "baseUrl": "https://gateway.example/v1",
                    "apiKeyRef": "trainer.plain",
                    "model": "MiniMax-M3",
                },
                "apiKey": "sk-test",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_meta"]["agentic"] is False
    assert body["agent_meta"]["auto_resource_lookup"] is True
    tool_events = body["agent_meta"]["tool_events"]
    assert [event["type"] for event in tool_events] == ["tool_call", "tool_result"]
    assert tool_events[0]["name"] == "search_resources"
    coach_visible_status = body["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["source"] == "resource_context"
    assert coach_visible_status["toolNames"] == ["search_resources"]
    assert coach_visible_status["status"] == "done"


def test_session_message_auto_library_lookup_handles_mixed_language_doc_questions(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime.resource_service.semantic_memory = SimpleNamespace(
        upsert_text=lambda *_args, **_kwargs: None,
    )
    scripted = _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": (
                    "这个结论可以直接从设计文档里 verified："
                    "Resources 视图的 first viewport promise 是让学习者在不丢失 provenance 的前提下找到、信任、预览并转化资料；"
                    "它绝不能变成 raw filesystem browser。"
                ),
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-auto-library-zh-doc")
        _upload_and_index_markdown(
            client,
            workspace_id="ws-auto-library-zh-doc",
            name="resources-view-contract.md",
            text=(
                "# Resources view contract\n"
                "First viewport promise: the learner can find, trust, preview, and convert resources without losing provenance.\n"
                "Must not become: a raw filesystem browser.\n"
            ),
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-auto-library-zh-doc",
                "use_agent_loop": True,
                "message": "我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise，以及它绝不能变成什么。",
                "response_language": "zh-CN",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_meta"]["agentic"] is True
    assert body["agent_meta"]["auto_resource_lookup"] is True
    assert body["agent_meta"]["stop_reason"] == "completed"
    assert body["coach_turn"]["scenario"] == "principle"
    assert len(scripted.calls_seen) == 1
    system_prompt = str(scripted.calls_seen[0][0].get("content") or "")
    user_prompt = str(scripted.calls_seen[0][1].get("content") or "")
    assert user_prompt == "我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise，以及它绝不能变成什么。"
    assert "Auto-grounded this turn in 1 likely library hits" in system_prompt
    assert "resources-view-contract.md" in system_prompt

    tool_events = body["agent_meta"]["tool_events"]
    assert [event["type"] for event in tool_events[:2]] == ["tool_call", "tool_result"]
    assert tool_events[0]["name"] == "search_resources"
    assert tool_events[1]["name"] == "search_resources"
    first_hit = tool_events[1]["result"]["hits"][0]
    assert first_hit["title"] == "resources-view-contract.md"
    result_query = str(tool_events[1]["result"]["query"] or "")
    assert result_query != "我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise，以及它绝不能变成什么。"
    assert "resources" in result_query.lower()
    assert "first viewport" in result_query.lower()
    assert any(
        "first viewport" in str(candidate or "").lower()
        for candidate in tool_events[1]["result"].get("queries_tried", [])
    )
    coach_visible_status = body["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["source"] == "agent_loop"
    assert coach_visible_status["toolNames"] == ["search_resources"]


def test_session_message_preserves_auto_resource_evidence_when_agent_searches_again(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime.resource_service.semantic_memory = SimpleNamespace(
        upsert_text=lambda *_args, **_kwargs: None,
    )
    scripted = _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "search_resources",
                        "arguments": {
                            "query": "first viewport promise",
                            "mode": "verify",
                        },
                    }
                ],
            },
            {
                "content": "The first viewport promise is to help the learner find and trust the right resource.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-auto-library-preserve")
        _upload_and_index_markdown(
            client,
            workspace_id="ws-auto-library-preserve",
            name="resources-view-contract.md",
            text=(
                "# Resources view contract\n"
                "First viewport promise: the learner can find, trust, preview, and convert resources without losing provenance.\n"
                "Must not become: a raw filesystem browser.\n"
            ),
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-auto-library-preserve",
                "use_agent_loop": True,
                "message": "我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise，以及它绝不能变成什么。",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_meta"]["agentic"] is True
    assert body["agent_meta"]["auto_resource_lookup"] is True
    assert len(scripted.calls_seen) == 2

    tool_events = body["agent_meta"]["tool_events"]
    assert len(tool_events) >= 4
    assert tool_events[0]["name"] == "search_resources"
    assert tool_events[0]["auto"] is True
    assert tool_events[1]["name"] == "search_resources"
    assert tool_events[1]["auto"] is True
    assert tool_events[1]["result"]["hits"][0]["title"] == "resources-view-contract.md"
    assert any(
        event.get("name") == "search_resources"
        and event.get("type") == "tool_call"
        and event.get("auto") is not True
        for event in tool_events[2:]
    )
    assert any(
        event.get("name") == "search_resources"
        and event.get("type") == "tool_result"
        and event.get("auto") is not True
        for event in tool_events[2:]
    )


def test_session_message_filters_mixed_language_coach_context_for_english(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "Start by naming which machine owns the workspace path.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-language-align")
        state = runtime.ensure_session(session_id, workspace_id="ws-language-align")
        state.snapshot.implementation_guide = ImplementationGuide(
            current_step="先找到文件实际在哪台机器上。",
            scope_boundary="先贴着当前焦点，不要一下子扩展到所有 remote 类型。",
            validation_strategy=["先跑一个小检查。", "再确认 whoami 和 pwd。"],
            success_signal="学习者能说清 workspace 归属。",
            fallback_step="如果还是太大，就先只看终端里的 pwd。",
        )
        state.snapshot.exercise_prompt = {
            "prompt": "先找到边界，再写最小变化。",
            "success_signal": "学习者能指出拥有者边界。",
            "fallback_step": "如果还是太大，就先只看 pwd 和 whoami。",
        }
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-language-align",
                "use_agent_loop": True,
                "message": "Help me reason about remote workspace ownership.",
                "response_language": "en-US",
            },
        )

    assert response.status_code == 200, response.text
    assert len(scripted.calls_seen) == 1
    system_prompt = str(scripted.calls_seen[0][0].get("content") or "")
    user_prompt = str(scripted.calls_seen[0][1].get("content") or "")
    cjk_pattern = re.compile(r"[\u3400-\u9fff]")
    assert not cjk_pattern.search(system_prompt)
    assert not cjk_pattern.search(user_prompt)


def test_session_message_strips_meta_coach_scaffolding_from_function_guidance_prompt(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "Start from the live call site.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-function-guidance-clean")
        state = runtime.ensure_session(session_id, workspace_id="ws-function-guidance-clean")
        state.snapshot.implementation_guide = ImplementationGuide(
            current_step=(
                "Current coaching focus: stay with 'fetchUserSummary' and keep the next loop "
                "attached to this latest move: read the live call site."
            ),
            scope_boundary=(
                "Current coaching focus: continue 'fetchUserSummary' before widening scope."
            ),
            validation_strategy=[
                "Review rhythm: verify it immediately before widening the change.",
            ],
        )
        state.snapshot.exercise_prompt = {
            "prompt": (
                "Use src/user.ts to teach this concept back: point at one branch, restate "
                "'Current coaching focus: keep following the learner\\'s latest concrete thread' "
                "in plain words."
            ),
            "fallback_step": (
                "Resume from the current coaching lane, verify this slice, then decide whether to widen."
            ),
        }
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-function-guidance-clean",
                "use_agent_loop": True,
                "message": (
                    "Help me understand what fetchUserSummary does. "
                    "Stay in function guidance and teach it from the current call site."
                ),
                "response_language": "en-US",
                "current_file": {
                    "path": "src/user.ts",
                    "language_id": "typescript",
                    "content": (
                        "export function fetchUserSummary(user: UserRecord, taxRate: number) { return { total: 1, active: true }; }\n"
                        "const summary = fetchUserSummary({ id: 'u1', orders: [20, 30] }, 0.1);"
                    ),
                    "selection_text": "fetchUserSummary({ id: 'u1', orders: [20, 30] }, 0.1)",
                    "diagnostics": [],
                    "recent_files": ["src/user.ts"],
                    "related_files": [],
                },
            },
        )

    assert response.status_code == 200, response.text
    assert len(scripted.calls_seen) == 1
    system_prompt = str(scripted.calls_seen[0][0].get("content") or "")
    user_prompt = str(scripted.calls_seen[0][1].get("content") or "")
    assert "Current coaching focus:" not in system_prompt
    assert "Current coaching focus:" not in user_prompt
    assert "Resume from the current coaching lane" not in system_prompt
    assert "Resume from the current coaching lane" not in user_prompt
    assert "fetchUserSummary" in system_prompt or "fetchUserSummary" in user_prompt


def test_session_message_empty_agent_reply_uses_local_sequence_fallback(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime.resource_service.semantic_memory = SimpleNamespace(
        upsert_text=lambda *_args, **_kwargs: None,
    )

    async def _empty_agentic(
        self: ProviderService,
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.clear_last_reply_override()
        return {
            "content": "",
            "tool_events": [],
            "stop_reason": "empty_response",
            "summary": "",
            "next_step": "",
            "decision": "",
            "blocker": "",
            "teaching_note": "",
            "resume_thread": "",
            "confidence": "",
            "evidence": [],
            "fell_back": False,
        }

    async def _unexpected_fallback(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("local sequence fallback should avoid provider fallback text generation")

    monkeypatch.setattr(ProviderService, "coaching_reply_agentic", _empty_agentic)
    monkeypatch.setattr(ProviderService, "coaching_reply", _unexpected_fallback)

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-local-sequence-fallback")
        _upload_and_index_markdown(
            client,
            workspace_id="ws-local-sequence-fallback",
            name="mirrorlock-remote.md",
            text=(
                "# MirrorLock protocol\n"
                "MirrorLock protocol is a teaching-only remote boundary mnemonic for VS Code Remote SSH.\n"
                "\n"
                "Step 1 - Name the host: say whether the path belongs to local Windows or remote Linux.\n"
                "Step 2 - Verify the owner: run `pwd` in the remote terminal and compare it with the VS Code Explorer path.\n"
                "Step 3 - Lock the action: only install, debug, or edit on the host that owns the workspace path.\n"
                "Boundary sentinel: host-ownership lockstep.\n"
            ),
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-local-sequence-fallback",
                "use_agent_loop": True,
                "message": "Teach me MirrorLock protocol for VS Code Remote SSH.",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("agent_meta", {}).get("stop_reason") == "completed"
    assert body.get("agent_meta", {}).get("recovered_stop_reason") == "empty_response"
    assert body.get("agent_meta", {}).get("fell_back") is True
    assert body.get("agent_meta", {}).get("local_sequence_fallback") is True
    reply = str(body["reply"]["content"])
    assert "Step 1" in reply
    assert "Step 2" in reply
    assert "Step 3" in reply
    assert "host-ownership lockstep" in reply
    coach_visible_status = body["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["status"] == "degraded"
    assert coach_visible_status["stopReason"] == "completed"


def test_session_message_terse_sequence_summary_is_replaced_with_visible_steps(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime.resource_service.semantic_memory = SimpleNamespace(
        upsert_text=lambda *_args, **_kwargs: None,
    )

    async def _terse_agentic(
        self: ProviderService,
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.clear_last_reply_override()
        return {
            "content": "Re-state the 3-step protocol and ask for pwd.",
            "tool_events": [],
            "stop_reason": "coach_finalize",
            "summary": "Re-state the 3-step protocol and ask for pwd.",
            "next_step": "Ask for the current workspace tag and pwd output.",
            "decision": "",
            "blocker": "",
            "teaching_note": "",
            "resume_thread": "",
            "confidence": "",
            "evidence": [],
            "fell_back": False,
        }

    monkeypatch.setattr(ProviderService, "coaching_reply_agentic", _terse_agentic)

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-terse-sequence-fallback")
        _upload_and_index_markdown(
            client,
            workspace_id="ws-terse-sequence-fallback",
            name="mirrorlock-remote.md",
            text=(
                "# MirrorLock protocol\n"
                "MirrorLock protocol is a teaching-only remote boundary mnemonic for VS Code Remote SSH.\n"
                "\n"
                "Step 1 - Name the host: say whether the path belongs to local Windows or remote Linux.\n"
                "Step 2 - Verify the owner: run `pwd` in the remote terminal and compare it with the VS Code Explorer path.\n"
                "Step 3 - Lock the action: only install, debug, or edit on the host that owns the workspace path.\n"
                "Boundary sentinel: host-ownership lockstep.\n"
            ),
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-terse-sequence-fallback",
                "use_agent_loop": True,
                "message": "Teach me MirrorLock protocol for VS Code Remote SSH.",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("agent_meta", {}).get("local_sequence_fallback") is True
    assert body.get("agent_meta", {}).get("fell_back") is False
    assert body.get("agent_meta", {}).get("grounded_sequence_enforced") is True
    reply = str(body["reply"]["content"])
    assert "Step 1" in reply
    assert "Step 2" in reply
    assert "Step 3" in reply
    coach_visible_status = body["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["status"] == "done"


def test_session_message_debug_loop_does_not_force_remote_sequence_on_fresh_lane(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime.resource_service.semantic_memory = SimpleNamespace(
        upsert_text=lambda *_args, **_kwargs: None,
    )

    async def _terse_agentic(
        self: ProviderService,
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.clear_last_reply_override()
        return {
            "content": "Stay on the VS Code debug loop and show me the stack frame where the value diverges.",
            "tool_events": [],
            "stop_reason": "coach_finalize",
            "summary": "Stay on the smallest trustworthy VS Code debug loop.",
            "next_step": "Ask for the breakpoint file and the current stack frame.",
            "decision": "",
            "blocker": "",
            "teaching_note": "",
            "resume_thread": "",
            "confidence": "",
            "evidence": [],
            "fell_back": False,
        }

    monkeypatch.setattr(ProviderService, "coaching_reply_agentic", _terse_agentic)

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-sequence-lane-mismatch")
        resource = _upload_and_index_markdown(
            client,
            workspace_id="ws-sequence-lane-mismatch",
            name="mirrorlock-remote.md",
            text=(
                "# MirrorLock protocol\n"
                "MirrorLock protocol is a teaching-only remote boundary mnemonic for VS Code Remote SSH.\n"
                "\n"
                "Step 1 - Name the host: say whether the path belongs to local Windows or remote Linux.\n"
                "Step 2 - Verify the owner: run `pwd` in the remote terminal and compare it with the VS Code Explorer path.\n"
                "Step 3 - Lock the action: only install, debug, or edit on the host that owns the workspace path.\n"
                "Boundary sentinel: host-ownership lockstep.\n"
            ),
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-sequence-lane-mismatch",
                "use_agent_loop": True,
                "message": "Keep this in the VS Code debug loop and use one breakpoint before you widen scope.",
                "response_language": "en-US",
                "resource_ids": [resource["id"]],
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coach_turn"]["scenario"] == "debug_loop"
    assert body.get("agent_meta", {}).get("local_sequence_fallback") is not True
    assert body.get("agent_meta", {}).get("grounded_sequence_enforced") is not True
    reply = str(body["reply"]["content"])
    assert "stack frame" in reply
    assert "Step 1" not in reply
    assert "host-ownership lockstep" not in reply
    assert "remote workspace" not in reply.lower()


def test_session_message_surfaces_practice_verification_as_coach_visible_status(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_path = tmp_path / "ws"
    workspace_path.mkdir()
    seeded_card = TrainingCardCandidateSnapshot(
        card_id="card-practice-search",
        card_type="practice",
        title="Verify debounce search",
        status="active",
        focus_area="search input",
        target_skill="current-file practice verification",
    )
    runtime.memory_service.upsert_card("ws-practice-pass", seeded_card)
    runtime.memory_service.persist_active_card_selection(
        "ws-practice-pass",
        ActiveCardSelectionResult(
            selected_card=seeded_card,
            selected_card_id=seeded_card.card_id,
            why_this_card="The learner needs proof from the current IDE file.",
            next_after_completion="Route the next practice card.",
            fallback_action="Bring blockers back to Coach.",
            candidate_count=1,
            eligible_count=1,
        ),
    )

    _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "verify-1",
                        "name": "verify_practice_current_file",
                        "arguments": {
                            "acceptance_criteria": ["Implement debounceSearch for the search input"],
                            "expected_symbols": ["debounceSearch", "normalizedQuery"],
                            "training_card_id": "card-practice-search",
                            "training_card_title": "Verify debounce search",
                        },
                    },
                ],
            },
            {
                "content": "The current-file verification passed; return this evidence to Training.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(
            client,
            workspace_id="ws-practice-pass",
            workspace_path=str(workspace_path),
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-practice-pass",
                "use_agent_loop": True,
                "message": "Verify this practice card from my current IDE file.",
                "response_language": "en-US",
                "current_file": {
                    "path": "src/search.ts",
                    "language_id": "typescript",
                    "content": (
                        "export function debounceSearch(query: string) {\n"
                        "  const normalizedQuery = query.trim();\n"
                        "  return normalizedQuery.length > 0 ? normalizedQuery : '';\n"
                        "}\n"
                    ),
                    "diagnostics": [],
                },
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    tool_events = body["agent_meta"]["tool_events"]
    assert [
        event.get("name")
        for event in tool_events
        if event.get("type") == "tool_call"
    ] == ["verify_practice_current_file"]

    coach_visible_status = body["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["type"] == "coach_visible_status"
    assert coach_visible_status["status"] == "done"
    assert coach_visible_status["displayKind"] == "practice_verification"
    assert coach_visible_status["toolNames"] == ["verify_practice_current_file"]
    assert "active IDE file" in coach_visible_status["summary"]
    assert coach_visible_status["nextStep"]

    reply_parts = body["reply"]["metadata"]["parts"]
    assert sum(1 for part in reply_parts if part["type"] == "coach_visible_status") == 1
    verify_result_part = next(
        part
        for part in reply_parts
        if part.get("type") == "tool_result"
        and part.get("name") == "verify_practice_current_file"
    )
    assert verify_result_part["displayKind"] == "practice_verification"
    assert verify_result_part["status"] == "passed"
    assert verify_result_part["passed"] is True
    assert verify_result_part["path"] == "src/search.ts"
    assert "active IDE file" in verify_result_part["summary"]
    assert verify_result_part["nextStep"]

    memory = body["snapshot"]["memory"]
    workspace_memory = memory["workspace"]
    assert workspace_memory["selected_card_id"] == "card-practice-search"
    assert workspace_memory["selected_card_status"] == "active"
    assert not workspace_memory["latest_learning_verified_result"]
    assert workspace_memory["latest_training_handoff"]["handoff_status"] == "needs_reflection"
    assert workspace_memory["latest_training_handoff"]["learning_phase"] == "verify"
    assert workspace_memory["latest_training_next_hop"]["status"] == "reflection_required"
    assert any(
        card["card_id"] == "card-practice-search" and card["status"] == "active"
        for card in memory["training_card_candidates"]
    )
    assert memory["active_training_card_routing"]["selected_card"]["status"] == "active"
    assert memory["training_event_ledger"][-1]["event_type"] == "practice_evaluation_recorded"
    assert memory["training_event_ledger"][-1]["selected_card_id"] == "card-practice-search"


def test_session_message_surfaces_practice_verification_needs_review(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_path = tmp_path / "ws"
    workspace_path.mkdir()
    seeded_card = TrainingCardCandidateSnapshot(
        card_id="card-practice-request-queue",
        card_type="practice",
        title="Verify request queue backoff",
        status="active",
        focus_area="request queue",
        target_skill="current-file practice verification",
    )
    runtime.memory_service.upsert_card("ws-practice-review", seeded_card)
    runtime.memory_service.persist_active_card_selection(
        "ws-practice-review",
        ActiveCardSelectionResult(
            selected_card=seeded_card,
            selected_card_id=seeded_card.card_id,
            why_this_card="The learner needs a concrete missing-signal blocker.",
            next_after_completion="Retry current-file verification.",
            fallback_action="Bring blockers back to Coach.",
            candidate_count=1,
            eligible_count=1,
        ),
    )

    _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "verify-2",
                        "name": "verify_practice_current_file",
                        "arguments": {
                            "acceptance_criteria": ["Implement retryBackoff in the request queue"],
                            "expected_symbols": ["retryBackoff"],
                            "training_card_id": "card-practice-request-queue",
                            "training_card_title": "Verify request queue backoff",
                        },
                    },
                ],
            },
            {
                "content": "The card is not ready yet; add the missing signal first.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(
            client,
            workspace_id="ws-practice-review",
            workspace_path=str(workspace_path),
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-practice-review",
                "use_agent_loop": True,
                "message": "Verify whether this practice card is done.",
                "response_language": "en-US",
                "current_file": {
                    "path": "src/requestQueue.ts",
                    "language_id": "typescript",
                    "content": "export function enqueueRequest() { return true; }\n",
                    "diagnostics": [],
                },
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    coach_visible_status = body["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["status"] == "degraded"
    assert coach_visible_status["displayKind"] == "practice_verification"
    assert "one more signal" in coach_visible_status["summary"]
    assert coach_visible_status["nextStep"]

    verify_result_part = next(
        part
        for part in body["reply"]["metadata"]["parts"]
        if part.get("type") == "tool_result"
        and part.get("name") == "verify_practice_current_file"
    )
    assert verify_result_part["displayKind"] == "practice_verification"
    assert verify_result_part["status"] == "needs_review"
    assert verify_result_part["passed"] is False
    assert verify_result_part["path"] == "src/requestQueue.ts"

    memory = body["snapshot"]["memory"]
    workspace_memory = memory["workspace"]
    assert workspace_memory["selected_card_id"] == "card-practice-request-queue"
    assert workspace_memory["selected_card_status"] == "blocked"
    assert workspace_memory["latest_learning_blocker"]
    assert workspace_memory["latest_training_handoff"]["handoff_status"] == "needs_revision"
    assert workspace_memory["latest_training_next_hop"]["status"] == "blocked"
    assert any(
        card["card_id"] == "card-practice-request-queue" and card["status"] == "blocked"
        for card in memory["training_card_candidates"]
    )
    assert memory["training_event_ledger"][-1]["event_type"] == "practice_evaluation_recorded"
    assert memory["training_event_ledger"][-1]["selected_card_id"] == "card-practice-request-queue"


def test_session_message_repeated_tool_calls_surface_degraded_status(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_path = tmp_path / "ws"
    workspace_path.mkdir()
    (workspace_path / "main.py").write_text("print('hi')\n", encoding="utf-8")

    _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "recall_memory", "arguments": {"focus": "async"}},
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {"id": "c2", "name": "recall_memory", "arguments": {"focus": "async"}},
                ],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(
            client,
            workspace_id="ws-no-progress",
            workspace_path=str(workspace_path),
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-no-progress",
                "use_agent_loop": True,
                "message": "I keep losing the thread on async iteration.",
                "response_language": "en-US",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_meta"]["stop_reason"] == "no_progress"
    coach_visible_status = body["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["status"] == "degraded"
    assert coach_visible_status["source"] == "agent_loop"
    assert coach_visible_status["stopReason"] == "no_progress"
    assert "repeated the same tool path" in coach_visible_status["summary"]
    assert coach_visible_status["nextStep"]
    assert "recall_memory" in coach_visible_status["nextStep"]
    assert coach_visible_status["resumeThread"]
    assert "Resume the live thread" not in coach_visible_status["resumeThread"]
    assert "recall_memory" in coach_visible_status["resumeThread"]


def test_session_message_publishes_visible_status_for_direct_agentic_reply(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "Keep the next move tiny and stay on the current thread.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-direct-status")
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-direct-status",
                "use_agent_loop": True,
                "message": "Give me the smallest next step.",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    agent_meta = body["agent_meta"]
    assert agent_meta["agentic"] is True
    assert agent_meta["summary"]
    assert agent_meta["next_step"]
    coach_visible_status = body["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["type"] == "coach_visible_status"
    assert coach_visible_status["status"] == "done"
    assert coach_visible_status["source"] == "agent_loop"
    assert coach_visible_status["summary"]
    assert "toolNames" not in coach_visible_status
    reply_parts = body["reply"]["metadata"]["parts"]
    assert sum(1 for part in reply_parts if part["type"] == "coach_visible_status") == 1
    assert all(part["type"] != "tool_call" for part in reply_parts)
    assert all(part["type"] != "tool_result" for part in reply_parts)


def test_session_message_marks_empty_agentic_reply_status_as_degraded(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-empty-status")
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-empty-status",
                "use_agent_loop": True,
                "message": "Give me the smallest next step.",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_meta"]["agentic"] is True
    assert body["agent_meta"]["stop_reason"] == "empty_response"
    assert "empty visible answer" in body["reply"]["content"]
    coach_visible_status = body["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["type"] == "coach_visible_status"
    assert coach_visible_status["status"] == "degraded"
    assert coach_visible_status["source"] == "agent_loop"
    assert coach_visible_status["stopReason"] == "empty_response"
    assert "empty visible answer" in coach_visible_status["summary"]
    assert "empty visible answer" in coach_visible_status["detail"]
    assert coach_visible_status["nextStep"]
    assert "toolNames" not in coach_visible_status
    reply_parts = body["reply"]["metadata"]["parts"]
    assert sum(1 for part in reply_parts if part["type"] == "coach_visible_status") == 1
    assert all(part["type"] != "tool_call" for part in reply_parts)
    assert all(part["type"] != "tool_result" for part in reply_parts)


def test_session_message_agent_loop_reuses_prior_conversation_history(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "Start with the login boundary, not the whole auth flow.",
                "tool_calls": [],
            },
            {
                "content": "Yes - continue from that same boundary and verify one branch.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-history")

        response_1 = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-history",
                "use_agent_loop": True,
                "message": "I keep losing the thread on auth.",
            },
        )
        assert response_1.status_code == 200, response_1.text

        response_2 = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-history",
                "use_agent_loop": True,
                "message": "Continue from the last step, don't restart.",
            },
        )
        assert response_2.status_code == 200, response_2.text

    assert len(scripted.calls_seen) >= 2
    second_turn_messages = scripted.calls_seen[1]
    assert second_turn_messages[0]["role"] == "system"
    assert any(
        msg.get("role") == "user"
        and "I keep losing the thread on auth." in str(msg.get("content") or "")
        for msg in second_turn_messages
    ), second_turn_messages
    assert any(
        msg.get("role") == "assistant"
        and "Start with the login boundary" in str(msg.get("content") or "")
        for msg in second_turn_messages
    ), second_turn_messages
    assert second_turn_messages[-1]["role"] == "user"
    assert "Continue from the last step" in str(second_turn_messages[-1].get("content") or "")


def test_session_message_surfaces_agent_finalize_as_next_step_artifact(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "I have enough context to close this loop.",
                "tool_calls": [
                    {
                        "id": "fin-1",
                        "name": "coach_finalize",
                        "arguments": {
                            "summary": "We narrowed the issue to one async iterator boundary.",
                            "next_step": "Patch the smallest async iterator call site and rerun the check.",
                            "decision": "Choose the smallest verified fix.",
                            "blocker": "Need one more workspace confirmation before widening scope.",
                            "teaching_note": "Name the blocker before widening scope.",
                            "confidence": "high",
                            "evidence": [
                                "The async iterator boundary is the only failing branch.",
                                "The latest diagnostics are still pointing at the same call site.",
                            ],
                        },
                    },
                ],
            },
            {
                "content": "Patch the smallest async iterator call site, rerun the check, then share the exact result.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-finalize")
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-finalize",
                "use_agent_loop": True,
                "message": "Help me close the loop and tell me the next step.",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("agent_meta", {}).get("summary") == "We narrowed the issue to one async iterator boundary."
    assert body.get("agent_meta", {}).get("next_step") == (
        "Patch the smallest async iterator call site and rerun the check."
    )
    assert body.get("agent_meta", {}).get("resume_thread") == (
        "We narrowed the issue to one async iterator boundary. "
        "Next: Patch the smallest async iterator call site and rerun the check."
    )
    assert "Patch the smallest async iterator call site" in body["reply"]["content"]
    assert "(scripted provider exhausted)" not in body["reply"]["content"]
    artifacts = body["reply"]["metadata"].get("artifacts", [])
    next_step_artifact = next(
        (item for item in artifacts if item.get("kind") == "next_step"),
        None,
    )
    assert next_step_artifact is not None
    assert next_step_artifact.get("title") == (
        "Patch the smallest async iterator call site and rerun the check."
    )
    assert next_step_artifact.get("summary") == (
        "We narrowed the issue to one async iterator boundary."
    )
    assert next_step_artifact.get("recommended_action") == "task"
    assert next_step_artifact.get("verification") == [
        "The async iterator boundary is the only failing branch.",
        "The latest diagnostics are still pointing at the same call site.",
    ]
    assert next_step_artifact.get("metadata", {}).get("decision") == "Choose the smallest verified fix."
    assert (
        next_step_artifact.get("metadata", {}).get("blocker")
        == "Need one more workspace confirmation before widening scope."
    )
    assert next_step_artifact.get("metadata", {}).get("teaching_note") == (
        "Name the blocker before widening scope."
    )
    assert next_step_artifact.get("metadata", {}).get("confidence") == "high"
    assert body["coach_turn"]["decision"] == "Choose the smallest verified fix."
    assert body["coach_turn"]["blocker"] == "Need one more workspace confirmation before widening scope."
    assert body["coach_turn"]["teaching_note"] == "Name the blocker before widening scope."
    assert body["coach_turn"]["confidence"] == "high"
    assert body["coach_turn"]["evidence"] == [
        "The async iterator boundary is the only failing branch.",
        "The latest diagnostics are still pointing at the same call site.",
    ]
    assert body["snapshot"]["coaching_state"]["decision"] == "Choose the smallest verified fix."
    assert (
        body["snapshot"]["coaching_state"]["blocker"]
        == "Need one more workspace confirmation before widening scope."
    )
    assert body["snapshot"]["coaching_state"]["teaching_note"] == "Name the blocker before widening scope."
    assert body["snapshot"]["coaching_state"]["confidence"] == "high"
    assert body["snapshot"]["coaching_state"]["evidence"] == [
        "The async iterator boundary is the only failing branch.",
        "The latest diagnostics are still pointing at the same call site.",
    ]
    next_step_hint = body["reply"]["metadata"]["next_step_hint"]
    assert next_step_hint["title"] == (
        "Patch the smallest async iterator call site and rerun the check."
    )
    assert next_step_hint["summary"] == (
        "We narrowed the issue to one async iterator boundary."
    )
    assert next_step_hint["recommended_action"] == "task"
    assert next_step_hint["source"] == "agent_loop"
    assert next_step_hint["continue_in"] == "coach"
    assert next_step_hint["resume_thread"] == (
        "We narrowed the issue to one async iterator boundary. "
        "Next: Patch the smallest async iterator call site and rerun the check."
    )
    assert body["coach_turn"]["resume_thread"] == (
        "We narrowed the issue to one async iterator boundary. "
        "Next: Patch the smallest async iterator call site and rerun the check."
    )
    assert body["reply"]["metadata"]["coach_turn"]["resume_thread"] == body["coach_turn"]["resume_thread"]
    assert body["snapshot"]["plan_runtime_status"]["next_step_hint"]["title"] == (
        "Patch the smallest async iterator call site and rerun the check."
    )
    assert body["snapshot"]["plan_runtime_status"]["next_step_hint"]["resume_thread"] == (
        "We narrowed the issue to one async iterator boundary. "
        "Next: Patch the smallest async iterator call site and rerun the check."
    )
    assert "coach_visible_status" not in body["reply"]["metadata"]


def test_session_message_publishes_one_coach_visible_status_for_multi_tool_turn(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "recall_memory", "arguments": {"focus": "resume"}},
                    {"id": "c2", "name": "inspect_plan", "arguments": {}},
                ],
            },
            {
                "content": "Stay on the same thread and land one verifiable patch.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-visible-status")
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-visible-status",
                "use_agent_loop": True,
                "message": "Continue the current thread and keep the next step verifiable.",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    reply_parts = body["reply"]["metadata"]["parts"]
    coach_status_parts = [
        part for part in reply_parts if part.get("type") == "coach_visible_status"
    ]
    assert len(coach_status_parts) == 1
    coach_status = coach_status_parts[0]
    assert coach_status["status"] == "done"
    assert coach_status["toolNames"] == ["recall_memory", "inspect_plan"]
    assert coach_status["stepCount"] == 2
    assert body["reply"]["metadata"]["coach_visible_status"] == coach_status


def test_session_message_stream_emits_agent_sse_events(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "recall_memory", "arguments": {}},
                ],
            },
            {
                "content": "Take one tiny next step.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-stream")
        with client.stream(
            "POST",
            "/session/message/stream",
            json={
                "session_id": session_id,
                "workspace_id": "ws-stream",
                "use_agent_loop": True,
                "message": "Help me stay un-stuck.",
            },
        ) as response:
            assert response.status_code == 200
            raw = b"".join(response.iter_bytes()).decode("utf-8", errors="replace")

    # Parse SSE blocks (events separated by blank lines).
    blocks = [block for block in raw.split("\n\n") if block.strip()]
    event_names: list[str] = []
    chunk_payloads: list[str] = []
    complete_payload: dict[str, Any] | None = None
    for block in blocks:
        event_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        data_text = "".join(data_lines)
        event_names.append(event_name)
        if event_name == "message" and data_text:
            try:
                payload = json.loads(data_text)
                chunk = payload.get("chunk") if isinstance(payload, dict) else None
                if isinstance(chunk, str):
                    chunk_payloads.append(chunk)
            except json.JSONDecodeError:
                pass
        elif event_name == "complete" and data_text:
            try:
                complete_payload = json.loads(data_text)
            except json.JSONDecodeError:
                complete_payload = None

    # Required event types must all appear at least once.
    assert "tool_call" in event_names, f"missing tool_call event in {event_names}"
    assert "tool_result" in event_names, f"missing tool_result event in {event_names}"
    assert "complete" in event_names
    # The final assistant text must have been streamed via at least one chunk.
    joined_chunks = "".join(chunk_payloads)
    assert "tiny next step" in joined_chunks or joined_chunks.strip() != ""
    # The complete envelope carries the full structured response.
    assert complete_payload is not None
    assert "response" in complete_payload
    response_payload = complete_payload["response"]
    assert response_payload["reply"]["content"]
    assert response_payload.get("agent", {}).get("agentic") is True
    coach_visible_status = response_payload["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["type"] == "coach_visible_status"
    assert coach_visible_status["status"] == "done"
    assert coach_visible_status["toolNames"] == ["recall_memory"]
    reply_parts = response_payload["reply"]["metadata"]["parts"]
    assert sum(1 for part in reply_parts if part["type"] == "coach_visible_status") == 1
    assert any(
        part["type"] == "tool_call" and part.get("name") == "recall_memory"
        for part in reply_parts
    )
    assert any(
        part["type"] == "tool_result" and part.get("name") == "recall_memory"
        for part in reply_parts
    )
    assert "attachments_delivered_to_model" not in response_payload["reply"]["metadata"]


def test_session_message_stream_publishes_visible_status_for_direct_agentic_reply(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "Keep the next move tiny and stay on the current thread.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-stream-direct-status")
        with client.stream(
            "POST",
            "/session/message/stream",
            json={
                "session_id": session_id,
                "workspace_id": "ws-stream-direct-status",
                "use_agent_loop": True,
                "message": "Give me the smallest next step.",
            },
        ) as response:
            assert response.status_code == 200
            raw = b"".join(response.iter_bytes()).decode("utf-8", errors="replace")

    blocks = [block for block in raw.split("\n\n") if block.strip()]
    complete_payload: dict[str, Any] | None = None
    for block in blocks:
        event_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        if event_name != "complete" or not data_lines:
            continue
        try:
            complete_payload = json.loads("".join(data_lines))
        except json.JSONDecodeError:
            complete_payload = None
        break

    assert complete_payload is not None
    response_payload = complete_payload["response"]
    assert response_payload["agent"]["agentic"] is True
    assert response_payload["agent"]["stop_reason"] == "completed"
    assert response_payload["reply"]["content"].strip()
    coach_visible_status = response_payload["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["type"] == "coach_visible_status"
    assert coach_visible_status["status"] == "done"
    assert coach_visible_status["source"] == "agent_loop"
    assert coach_visible_status["stopReason"] == "completed"
    assert coach_visible_status["summary"] == "I answered directly from the current thread."
    assert coach_visible_status["detail"] == "No extra tool lookup was needed."
    assert "toolNames" not in coach_visible_status
    reply_parts = response_payload["reply"]["metadata"]["parts"]
    assert sum(1 for part in reply_parts if part["type"] == "coach_visible_status") == 1
    assert all(part["type"] != "tool_call" for part in reply_parts)
    assert all(part["type"] != "tool_result" for part in reply_parts)


def test_active_view_metadata_survives_non_stream_stream_and_session_restore(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_coaching_reply_stream(*_: Any, **__: Any) -> AsyncIterator[str]:
        yield "Resources reply."

    monkeypatch.setattr(
        ProviderService,
        "coaching_reply",
        AsyncMock(return_value="Plan reply."),
    )
    monkeypatch.setattr(
        ProviderService,
        "coaching_reply_stream",
        fake_coaching_reply_stream,
    )
    monkeypatch.setattr(runtime, "provider_connection_verified", lambda _provider: True)
    monkeypatch.setattr(
        runtime,
        "provider_capability_state_for",
        lambda _provider, _name: "verified",
    )

    with TestClient(app) as client:
        non_stream_session_id = _seed_session(
            client,
            workspace_id="ws-active-view-non-stream",
        )
        non_stream_response = client.post(
            "/session/message",
            json={
                "session_id": non_stream_session_id,
                "workspace_id": "ws-active-view-non-stream",
                "use_agent_loop": False,
                "active_view": "plan",
                "message": "Keep this plan step narrow.",
            },
        )
        assert non_stream_response.status_code == 200, non_stream_response.text
        non_stream_snapshot_messages = non_stream_response.json()["snapshot"]["messages"]
        assert non_stream_snapshot_messages[-2]["metadata"]["active_view"] == "plan"
        assert non_stream_snapshot_messages[-1]["metadata"]["active_view"] == "plan"
        assert non_stream_response.json()["reply"]["metadata"]["active_view"] == "plan"

        stream_session_id = _seed_session(
            client,
            workspace_id="ws-active-view-stream",
        )
        with client.stream(
            "POST",
            "/session/message/stream",
            json={
                "session_id": stream_session_id,
                "workspace_id": "ws-active-view-stream",
                "use_agent_loop": False,
                "active_view": "resources",
                "message": "Find the source for this next step.",
            },
        ) as response:
            assert response.status_code == 200
            raw = b"".join(response.iter_bytes()).decode("utf-8", errors="replace")

        complete_payload: dict[str, Any] | None = None
        for block in (item for item in raw.split("\n\n") if item.strip()):
            event_name = "message"
            data_lines: list[str] = []
            for line in block.split("\n"):
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].lstrip())
            if event_name == "complete" and data_lines:
                complete_payload = json.loads("".join(data_lines))
                break

        assert complete_payload is not None
        stream_response = complete_payload["response"]
        assert stream_response["reply"]["metadata"]["active_view"] == "resources"

        persisted = runtime.repository.load_session(stream_session_id)
        assert persisted is not None
        persisted_messages = persisted["snapshot"]["messages"]
        assert persisted_messages[-2]["metadata"]["active_view"] == "resources"
        assert persisted_messages[-1]["metadata"]["active_view"] == "resources"

        runtime.sessions.pop(stream_session_id, None)
        restored = runtime.restore_latest_session_for_workspace("ws-active-view-stream")
        assert restored is not None
        assert restored.snapshot.messages[-2].metadata["active_view"] == "resources"
        assert restored.snapshot.messages[-1].metadata["active_view"] == "resources"


def test_session_message_stream_surfaces_empty_agentic_reply_as_recovery_chunk(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-stream-empty-recovery")
        with client.stream(
            "POST",
            "/session/message/stream",
            json={
                "session_id": session_id,
                "workspace_id": "ws-stream-empty-recovery",
                "use_agent_loop": True,
                "message": "Give me the smallest next step.",
            },
        ) as response:
            assert response.status_code == 200
            raw = b"".join(response.iter_bytes()).decode("utf-8", errors="replace")

    blocks = [block for block in raw.split("\n\n") if block.strip()]
    chunks: list[str] = []
    complete_payload: dict[str, Any] | None = None
    for block in blocks:
        event_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        if not data_lines:
            continue
        payload = json.loads("".join(data_lines))
        if event_name == "message" and isinstance(payload, dict) and payload.get("chunk"):
            chunks.append(str(payload["chunk"]))
        if event_name == "complete":
            complete_payload = payload

    assert complete_payload is not None
    streamed_text = "".join(chunks)
    assert "empty visible answer" in streamed_text
    response_payload = complete_payload["response"]
    assert response_payload["agent"]["agentic"] is True
    assert response_payload["agent"]["stop_reason"] == "empty_response"
    assert "empty visible answer" in response_payload["agent"]["summary"]
    assert response_payload["reply"]["content"].strip()
    assert "empty visible answer" in response_payload["reply"]["content"]
    coach_visible_status = response_payload["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["type"] == "coach_visible_status"
    assert coach_visible_status["status"] == "degraded"
    assert coach_visible_status["source"] == "agent_loop"
    assert coach_visible_status["stopReason"] == "empty_response"
    assert "empty visible answer" in coach_visible_status["summary"]
    assert "empty visible answer" in coach_visible_status["detail"]
    assert coach_visible_status["nextStep"]
    assert "toolNames" not in coach_visible_status
    reply_parts = response_payload["reply"]["metadata"]["parts"]
    assert sum(1 for part in reply_parts if part["type"] == "coach_visible_status") == 1
    assert all(part["type"] != "tool_call" for part in reply_parts)
    assert all(part["type"] != "tool_result" for part in reply_parts)


def test_turn_stream_coach_path_reports_attachment_delivery_truth(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_attachments: list[list[dict[str, Any]]] = []
    scripted = ScriptedAgentProvider(
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "recall_memory", "arguments": {"focus": "screenshot"}},
                ],
            },
            {
                "content": "I can still coach from the screenshot context, but the image did not reach the model.",
                "tool_calls": [],
            },
        ]
    )

    def _build(
        self: ProviderService,
        *,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> tuple[Any, Any]:
        captured_attachments.append(list(attachments or []))
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", _build)

    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
        "EQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-turn-stream-image")
        response = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": "ws-turn-stream-image",
                "intent": "coach",
                "message": "Please inspect this screenshot and keep the loop going.",
                "attachments": [
                    {
                        "id": "att-1",
                        "kind": "image",
                        "mimeType": "image/png",
                        "dataBase64": png_b64,
                        "name": "screenshot.png",
                    }
                ],
            },
        )

    assert response.status_code == 200, response.text
    raw = response.text
    blocks = [block for block in raw.split("\n\n") if block.strip()]
    event_names: list[str] = []
    complete_payload: dict[str, Any] | None = None
    for block in blocks:
        event_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        event_names.append(event_name)
        if event_name == "complete" and data_lines:
            complete_payload = json.loads("".join(data_lines))

    assert "tool_call" in event_names
    assert "tool_result" in event_names
    assert complete_payload is not None
    response_payload = complete_payload["response"]
    assert response_payload["agent"]["agentic"] is True
    assert response_payload["agent"]["attachments_delivered_to_model"] is False
    assert response_payload["agent"]["attachments_delivery_reason"] == "vision_not_available"
    assert response_payload["reply"]["metadata"]["attachments_delivered_to_model"] is False
    assert response_payload["reply"]["metadata"]["attachments_delivery_reason"] == "vision_not_available"
    support_lines = response_payload["reply"]["metadata"]["support"]["lines"]
    assert any("not vision-ready" in line for line in support_lines)
    assert all(len(batch) == 0 for batch in captured_attachments), captured_attachments


def test_turn_stream_coach_publishes_visible_status_for_direct_agentic_reply(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "Keep the next move tiny and stay on the current thread.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-turn-stream-direct-status")
        with client.stream(
            "POST",
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": "ws-turn-stream-direct-status",
                "use_agent_loop": True,
                "intent": "coach",
                "message": "Give me the smallest next step.",
            },
        ) as response:
            assert response.status_code == 200
            raw = b"".join(response.iter_bytes()).decode("utf-8", errors="replace")

    blocks = [block for block in raw.split("\n\n") if block.strip()]
    complete_payload: dict[str, Any] | None = None
    for block in blocks:
        event_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        if event_name != "complete" or not data_lines:
            continue
        try:
            complete_payload = json.loads("".join(data_lines))
        except json.JSONDecodeError:
            complete_payload = None
        break

    assert complete_payload is not None
    response_payload = complete_payload["response"]
    assert response_payload["intent"] == "coach"
    assert response_payload["agent"]["agentic"] is True
    assert response_payload["agent"]["stop_reason"] == "completed"
    coach_visible_status = response_payload["reply"]["metadata"]["coach_visible_status"]
    assert coach_visible_status["type"] == "coach_visible_status"
    assert coach_visible_status["status"] == "done"
    assert coach_visible_status["source"] == "agent_loop"
    assert coach_visible_status["stopReason"] == "completed"
    assert coach_visible_status["summary"] == "I answered directly from the current thread."
    assert coach_visible_status["detail"] == "No extra tool lookup was needed."
    assert "toolNames" not in coach_visible_status


def test_session_message_stream_persists_agent_finalize_into_followup_memory(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_text = "Streaming loop anchored on one smoke test."
    next_step_text = "Run the focused smoke test and paste the exact failure."
    _patch_provider(
        monkeypatch,
        runtime,
        responses=[
            {
                "content": "Good, we have a narrow loop now.",
                "tool_calls": [
                    {
                        "id": "fin-stream",
                        "name": "coach_finalize",
                        "arguments": {
                            "summary": summary_text,
                            "next_step": next_step_text,
                        },
                    },
                ],
            },
            {
                "content": "Stay on that same smoke-test loop and paste the failure output.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-stream-finalize")
        with client.stream(
            "POST",
            "/session/message/stream",
            json={
                "session_id": session_id,
                "workspace_id": "ws-stream-finalize",
                "use_agent_loop": True,
                "message": "Close this loop and keep the next step alive.",
            },
        ) as response:
            assert response.status_code == 200
            raw = b"".join(response.iter_bytes()).decode("utf-8", errors="replace")

        blocks = [block for block in raw.split("\n\n") if block.strip()]
        complete_payload: dict[str, Any] | None = None
        for block in blocks:
            event_name = "message"
            data_lines: list[str] = []
            for line in block.split("\n"):
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].lstrip())
            if event_name != "complete" or not data_lines:
                continue
            complete_payload = json.loads("".join(data_lines))
            break

        assert complete_payload is not None
        response_payload = complete_payload["response"]
        assert response_payload["agent"]["stop_reason"] == "coach_finalize"
        assert response_payload["agent"]["summary"] == summary_text
        assert response_payload["agent"]["next_step"] == next_step_text
        assert response_payload["snapshot"]["memory"]["active_thread"]["summary"] == summary_text
        assert response_payload["snapshot"]["memory"]["active_thread"]["next_step"] == next_step_text

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        summary_payload = summary_response.json()
        assert summary_payload["memory"]["active_thread"]["summary"] == summary_text
        assert summary_payload["memory"]["active_thread"]["next_step"] == next_step_text

        followup = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-stream-finalize",
                "use_agent_loop": True,
                "message": "Continue from the same live thread and do not restart.",
            },
        )

    assert followup.status_code == 200, followup.text
    followup_payload = followup.json()
    assert followup_payload["snapshot"]["memory"]["active_thread"]["summary"] == summary_text
    assert followup_payload["snapshot"]["memory"]["active_thread"]["next_step"] == next_step_text
    assert followup_payload["reply"]["metadata"]["next_step_hint"]["title"] == next_step_text
    assert followup_payload["reply"]["metadata"]["next_step_hint"]["summary"] == summary_text


def test_workspace_path_resolves_in_runtime_and_unblocks_workspace_tools(
    runtime: TrainerRuntime,
    app: FastAPI,
    tmp_path: Path,
) -> None:
    workspace_path = tmp_path / "ws-tool"
    workspace_path.mkdir()
    (workspace_path / "alpha.py").write_text("# hello\n", encoding="utf-8")

    with TestClient(app) as client:
        _seed_session(
            client,
            workspace_id="ws-tool",
            workspace_path=str(workspace_path),
        )

    # The runtime must remember the workspace path so workspace tools can
    # resolve a real on-disk root.
    resolved = runtime.resolve_workspace_path("ws-tool")
    assert resolved is not None
    assert Path(resolved).resolve() == workspace_path.resolve()


async def test_agent_can_read_workspace_file_via_real_tool_registry(
    runtime: TrainerRuntime,
    tmp_path: Path,
) -> None:
    """Drive the agent loop directly against the real tool registry +
    runtime, and prove that the model's ``read_workspace_file`` tool call
    resolves the configured workspace path and returns the file content.

    This is the ground-truth check that workspace-scoped tools are not
    just registered but actually wired through ``register_workspace_path``
    on session start.
    """
    workspace_path = tmp_path / "ws-read"
    workspace_path.mkdir()
    target = workspace_path / "fizzbuzz.py"
    target.write_text(
        "def fizzbuzz(n):\n    return 'fizz' if n % 3 == 0 else str(n)\n",
        encoding="utf-8",
    )
    runtime.register_workspace_path("ws-read", str(workspace_path))

    from app.llm.agent_loop import AgentProvider, CoachAgentLoop
    from app.llm.tools import ToolContext, build_default_tool_registry

    # Two-turn script: turn 1 calls read_workspace_file with the relative
    # path; turn 2 returns a coaching reply that quotes part of the file.
    iterator = iter(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "read_workspace_file",
                        "arguments": {"path": "fizzbuzz.py", "max_chars": 1024},
                    }
                ],
            },
            {
                "content": (
                    "I see your fizzbuzz returns 'fizz' on multiples of 3. "
                    "Try adding the multiples-of-5 branch next."
                ),
                "tool_calls": [],
            },
        ]
    )

    async def _call(_messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        try:
            return next(iterator)
        except StopIteration:  # pragma: no cover - defensive
            return {"content": "(exhausted)", "tool_calls": []}

    provider = AgentProvider(protocol="openai_chat_completions", call=_call)
    registry = build_default_tool_registry()
    context = ToolContext(
        runtime=runtime,
        workspace_id="ws-read",
        session_id="s-read",
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=context, max_steps=4)
    result = await loop.run([{"role": "user", "content": "Look at fizzbuzz.py"}])

    # Tool ran and saw the actual file content from the resolved root.
    assert result.stop_reason == "completed"
    assert result.steps, "expected at least one tool step"
    tool_results = result.steps[0].tool_results
    assert tool_results, "tool result should be present"
    payload = tool_results[0]["result"]
    assert payload["ok"] is True
    assert "fizzbuzz" in payload["content"]
    assert payload["path"].endswith("fizzbuzz.py")
    # And the agent's final reply made it to the result.
    assert "fizzbuzz" in result.final_content


async def test_agent_can_run_diagnostics_against_real_workspace_file(
    runtime: TrainerRuntime,
    tmp_path: Path,
) -> None:
    """``run_diagnostics`` must run the static checks against the real file
    and surface findings (line count, language hint).
    """
    workspace_path = tmp_path / "ws-diag"
    workspace_path.mkdir()
    target = workspace_path / "loose.py"
    target.write_text(
        "def stale():    \n    return 1\n# TODO: tighten\n",
        encoding="utf-8",
    )
    runtime.register_workspace_path("ws-diag", str(workspace_path))

    from app.llm.agent_loop import AgentProvider, CoachAgentLoop
    from app.llm.tools import ToolContext, build_default_tool_registry

    responses = iter(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "run_diagnostics",
                        "arguments": {"path": "loose.py"},
                    }
                ],
            },
            {"content": "Tighten the trailing whitespace first.", "tool_calls": []},
        ]
    )

    async def _call(_messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        try:
            return next(responses)
        except StopIteration:  # pragma: no cover
            return {"content": "(exhausted)", "tool_calls": []}

    provider = AgentProvider(protocol="openai_chat_completions", call=_call)
    registry = build_default_tool_registry()
    context = ToolContext(
        runtime=runtime,
        workspace_id="ws-diag",
        session_id="s-diag",
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=context, max_steps=4)
    result = await loop.run([{"role": "user", "content": "Check loose.py"}])

    assert result.stop_reason == "completed"
    payload = result.steps[0].tool_results[0]["result"]
    assert payload["ok"] is True
    assert payload["language"] == "python"
    finding_kinds = {finding.get("kind") for finding in payload.get("findings", [])}
    assert "style" in finding_kinds  # trailing whitespace caught
    assert "note" in finding_kinds   # TODO/FIXME caught


def test_provider_falls_back_when_agent_provider_raises(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the agent provider raises mid-flight, the route still returns a
    coaching reply rather than 500ing. The non-empty content can come from
    the agent-loop scaffold fallback or the single-call fallback; either
    is acceptable, but the response must be honest about what happened.
    """
    failing = SimpleNamespace(
        protocol="openai_chat_completions",
        attachments_will_be_sent=lambda: False,
    )

    async def _explode(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("simulated provider outage")

    failing.call = _explode  # type: ignore[attr-defined]
    failing.call_stream = _explode  # type: ignore[attr-defined]

    def _build(self: ProviderService, **_: Any) -> tuple[Any, Any]:
        return failing, failing

    monkeypatch.setattr(ProviderService, "build_agent_provider", _build)

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-fallback")
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-fallback",
                "use_agent_loop": True,
                "message": "anything",
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    # Reply must still carry usable text — agent loop falls back to its
    # scaffold reply when the provider explodes.
    assert body["reply"]["content"].strip(), body
    agent_meta = body.get("agent_meta") or {}
    assert agent_meta.get("agentic") is True
    stop_reason = str(agent_meta.get("stop_reason") or "")
    # The runtime should report the failure honestly, either as
    # "provider_error" (from CoachAgentLoop swallowing the exception) or
    # the scaffold-fallback envelope ("agent_error: …").
    assert "error" in stop_reason or stop_reason in {"max_steps", "provider_error"}, agent_meta
    assert agent_meta.get("summary")
    assert agent_meta.get("next_step")


# ---------------------------------------------------------------------------
# Multi-turn human simulation: image attachment + coach_finalize
# ---------------------------------------------------------------------------


def test_multi_turn_simulation_with_attachment_and_coach_finalize(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Walk a real user through three coaching turns and verify the agent
    layer behaves correctly across them:

    1. **Vague intake**: user says "I'm stuck"; agent calls
       ``recall_memory`` then writes a steering reply.
    2. **Screenshot turn**: user attaches an image; we record the
       attachment payload reaching the route, prove it would flow into
       the provider binding, and the agent calls ``run_diagnostics``
       on a workspace file before replying.
        3. **Finalize turn**: user signals they will try the next step; the
           agent calls ``coach_finalize`` and returns its verified summary +
           next step without another model round trip.

    Each turn drives the SAME monkeypatched scripted provider, so it
    is safe to run without an API key.
    """
    captured_attachments: list[list[dict[str, Any]]] = []
    captured_protocols: list[str] = []

    def _build(
        self: ProviderService,
        *,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> tuple[Any, Any]:
        captured_attachments.append(list(attachments or []))
        captured_protocols.append(str(protocol or ""))
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", _build)

    scripted = ScriptedAgentProvider(
        responses=[
            # Turn 1: recall_memory then a calm steering reply.
            {
                "content": "",
                "tool_calls": [
                    {"id": "t1", "name": "recall_memory", "arguments": {"focus": "stuck"}},
                ],
            },
            {
                "content": "Tell me which line you ran last and what you saw.",
                "tool_calls": [],
            },
            # Turn 2: run_diagnostics then a focused next step.
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "t2",
                        "name": "run_diagnostics",
                        "arguments": {"path": "stuck.py"},
                    }
                ],
            },
            {
                "content": "Trim the trailing whitespace, then re-run.",
                "tool_calls": [],
            },
            # Turn 3: coach_finalize attaches summary + next_step.
            {
                "content": "Glad you have a clear next step.",
                "tool_calls": [
                    {
                        "id": "t3",
                        "name": "coach_finalize",
                        "arguments": {
                            "summary": "Whitespace tightened; rerun pending.",
                            "next_step": "Run pytest on stuck.py and report the result.",
                        },
                    }
                ],
            },
        ]
    )

    with TestClient(app) as client:
        # Seed a real workspace path so run_diagnostics has a file to read.
        from pathlib import Path as _Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as raw_tmp:
            workspace = _Path(raw_tmp) / "ws-multi"
            workspace.mkdir()
            (workspace / "stuck.py").write_text(
                "def stuck():    \n    return None\n",
                encoding="utf-8",
            )
            session_id = _seed_session(
                client,
                workspace_id="ws-multi",
                workspace_path=str(workspace),
            )

            # --- Turn 1: vague intake -----------------------------------------
            response_1 = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": "ws-multi",
                    "use_agent_loop": True,
                    "message": "I'm stuck.",
                },
            )
            assert response_1.status_code == 200, response_1.text
            body_1 = response_1.json()
            assert body_1["agent_meta"]["agentic"] is True
            assert any(
                event["type"] == "tool_call" and event.get("name") == "recall_memory"
                for event in body_1["agent_meta"]["tool_events"]
            )
            assert "tell me" in body_1["reply"]["content"].lower()

            # --- Turn 2: screenshot attachment + run_diagnostics --------------
            png_b64 = (
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
                "EQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
            )
            response_2 = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": "ws-multi",
                    "use_agent_loop": True,
                    "message": "Here is what I see.",
                    "attachments": [
                        {
                            "id": "att-1",
                            "kind": "image",
                            "mimeType": "image/png",
                            "dataBase64": png_b64,
                            "name": "screenshot.png",
                        }
                    ],
                },
            )
            assert response_2.status_code == 200, response_2.text
            body_2 = response_2.json()
            tool_events_2 = body_2["agent_meta"]["tool_events"]
            assert any(
                event["type"] == "tool_call" and event.get("name") == "run_diagnostics"
                for event in tool_events_2
            )
            assert body_2["agent_meta"]["attachments_delivered_to_model"] is False
            assert body_2["agent_meta"]["attachments_delivery_reason"] == "vision_not_available"
            assert body_2["reply"]["metadata"]["attachments_delivered_to_model"] is False
            assert body_2["reply"]["metadata"]["attachments_delivery_reason"] == "vision_not_available"
            assert any(
                "not vision-ready" in line
                for line in body_2["reply"]["metadata"]["support"]["lines"]
            )
            assert all(len(batch) == 0 for batch in captured_attachments), captured_attachments

            # --- Turn 3: coach_finalize -------------------------------------
            response_3 = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": "ws-multi",
                    "use_agent_loop": True,
                    "message": "Got it, thanks.",
                },
            )
            assert response_3.status_code == 200, response_3.text
            body_3 = response_3.json()
            agent_meta_3 = body_3["agent_meta"]
            assert agent_meta_3["stop_reason"] == "coach_finalize"
            assert agent_meta_3["summary"] == "Whitespace tightened; rerun pending."
            assert "next_step" in agent_meta_3 and agent_meta_3["next_step"]
            assert agent_meta_3["resume_thread"] == (
                "Whitespace tightened; rerun pending. Next: Run pytest on stuck.py and report the result."
            )
            assert "Whitespace tightened; rerun pending." in body_3["reply"]["content"]
            assert "Run pytest on stuck.py and report the result." in body_3["reply"]["content"]
            assert scripted._index == 5
            assert "Glad" not in body_3["reply"]["content"]
            assert body_3["snapshot"]["memory"]["active_thread"]["summary"] == (
                "Whitespace tightened; rerun pending."
            )
            assert body_3["snapshot"]["memory"]["active_thread"]["next_step"] == (
                "Run pytest on stuck.py and report the result."
            )
            assert body_3["coach_turn"]["resume_thread"] == (
                "Whitespace tightened; rerun pending. Next: Run pytest on stuck.py and report the result."
            )
            assert body_3["reply"]["metadata"]["coach_turn"]["resume_thread"] == body_3["coach_turn"]["resume_thread"]

            summary_response = client.get("/memory/summary", params={"session_id": session_id})
            assert summary_response.status_code == 200
            summary_payload = summary_response.json()
            assert summary_payload["memory"]["active_thread"]["summary"] == (
                "Whitespace tightened; rerun pending."
            )
            assert summary_payload["memory"]["active_thread"]["next_step"] == (
                "Run pytest on stuck.py and report the result."
            )

            # --- Turn 4: follow-up resumes the same live thread -------------
            response_4 = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": "ws-multi",
                    "use_agent_loop": True,
                    "message": "Continue from the same live thread and keep it narrow.",
                },
            )
            assert response_4.status_code == 200, response_4.text
            body_4 = response_4.json()
            assert body_4["snapshot"]["memory"]["active_thread"]["summary"] == (
                "Whitespace tightened; rerun pending."
            )
            assert body_4["snapshot"]["memory"]["active_thread"]["next_step"] == (
                "Run pytest on stuck.py and report the result."
            )
            assert body_4["reply"]["metadata"]["next_step_hint"]["title"] == (
                "Run pytest on stuck.py and report the result."
            )
            assert body_4["reply"]["metadata"]["next_step_hint"]["summary"] == (
                "Whitespace tightened; rerun pending."
            )
            assert body_4["coach_turn"]["next_step"] == (
                "Run pytest on stuck.py and report the result."
            )


def test_session_message_marks_image_attachments_delivered_when_provider_is_vision_ready(
    runtime: TrainerRuntime,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vision_provider_config = ProviderConfig(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_ref="trainer.test",
        model="gpt-4o-mini",
        capabilities={"tools": True, "streaming": True, "vision": True},
    )
    runtime.provider_service = ProviderService(
        config=vision_provider_config,
        api_key="sk-test-fake",
    )
    seed_verified_capabilities(runtime, vision_provider_config, "sk-test-fake")

    captured_attachments: list[list[dict[str, Any]]] = []
    scripted = ScriptedAgentProvider(
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "recall_memory", "arguments": {"focus": "screenshot"}},
                ],
            },
            {
                "content": "The screenshot reached the model, so stay on the exact failing edge you highlighted.",
                "tool_calls": [],
            },
        ]
    )

    def _build(
        self: ProviderService,
        *,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> tuple[Any, Any]:
        captured_attachments.append(list(attachments or []))
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", _build)

    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
        "EQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-image-delivered")
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-image-delivered",
                "message": "Please inspect this screenshot and keep the next step narrow.",
                "attachments": [
                    {
                        "id": "att-vision-1",
                        "kind": "image",
                        "mimeType": "image/png",
                        "dataBase64": png_b64,
                        "name": "failing-edge.png",
                    }
                ],
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_meta"]["attachments_delivered_to_model"] is True
    assert body["agent_meta"]["attachments_delivery_reason"] == "image_sent_to_model"
    assert body["reply"]["metadata"]["attachments_delivered_to_model"] is True
    assert body["reply"]["metadata"]["attachments_delivery_reason"] == "image_sent_to_model"
    assert any(
        len(batch) == 1 and batch[0].get("kind") == "image"
        for batch in captured_attachments
    ), captured_attachments
    support_lines = body["reply"]["metadata"]["support"]["lines"]
    assert any("reached the model as image input" in line for line in support_lines)
