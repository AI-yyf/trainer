"""Contract tests for the four-view streaming workbench surface.

These tests reuse the canonical e2e runtime while replacing the provider stream.
No network calls or real API keys are involved.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import Mock

import pytest
import test_session_agent_e2e as _e2e
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_session_agent_e2e import _seed_session

from app.core.models import ProviderCapabilityEvidence, ProviderTestResponse
from app.llm.provider_service import ProviderService


@pytest.fixture
def runtime(tmp_path: Any) -> Any:
    """Reuse the canonical agent-e2e runtime fixture without duplicating setup."""

    return _e2e.runtime.__wrapped__(tmp_path)


@pytest.fixture
def app(runtime: Any) -> FastAPI:
    """Reuse the canonical agent-e2e FastAPI fixture."""

    return _e2e.app.__wrapped__(runtime)


@pytest.fixture
def streaming_verified_runtime(runtime: Any) -> Any:
    """Keep baseline SSE available while leaving tool execution unverified."""

    provider = runtime.provider_service._config
    assert provider is not None
    runtime.remember_provider_capability_test(
        provider,
        "sk-test-fake",
        ProviderTestResponse(
            ok=True,
            detail="mocked basic and streaming probes",
            capability_evidence=[
                ProviderCapabilityEvidence(
                    name="streaming",
                    declared=True,
                    observed=True,
                    state="verified",
                )
            ],
            streaming_ready=True,
            stream_probe_status="verified",
        ),
    )
    return runtime


def _sse_blocks(raw: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        if data_lines:
            events.append((event, json.loads("".join(data_lines))))
    return events


def _stream_payload(
    client: TestClient,
    *,
    session_id: str,
    workspace_id: str,
    active_view: str,
    message: str,
    resource_composer_intent: dict[str, Any] | None = None,
    resource_ids: list[str] | None = None,
    path: str = "/session/message/stream",
    stream_id: str | None = None,
    intent: str = "coach",
    use_agent_loop: bool | None = None,
    attachments: list[dict[str, Any]] | None = None,
    formal_plan_mutation: bool = False,
) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    payload: dict[str, Any] = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "active_view": active_view,
        "message": message,
        "response_language": "en-US",
    }
    if use_agent_loop is not None:
        payload["use_agent_loop"] = use_agent_loop
    if attachments is not None:
        payload["attachments"] = attachments
    if formal_plan_mutation:
        payload["formal_plan_mutation"] = True
    if stream_id is not None:
        payload["stream_id"] = stream_id
    if resource_composer_intent is not None:
        payload["resource_composer_intent"] = resource_composer_intent
    if resource_ids is not None:
        payload["resource_ids"] = resource_ids
    if path == "/turn/stream":
        payload["intent"] = intent
    with client.stream("POST", path, json=payload) as response:
        raw = b"".join(response.iter_bytes()).decode("utf-8", errors="replace")
        assert response.status_code == 200, raw
    return raw, _sse_blocks(raw)


@pytest.mark.parametrize("active_view", ["coach", "plan", "resources", "training"])
def test_each_primary_view_streams_plain_provider_reply_and_preserves_active_view(
    app: FastAPI,
    streaming_verified_runtime: object,
    monkeypatch: pytest.MonkeyPatch,
    active_view: str,
) -> None:
    provider_calls: list[dict[str, Any]] = []

    async def fake_provider_stream(
        _self: ProviderService,
        _profile: object,
        message: str,
        _current_file: object,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        provider_calls.append({"message": message, **kwargs})
        yield f"{active_view} provider-backed SSE reply."

    async def fake_agent_stream(
        _self: ProviderService,
        _profile: object,
        message: str,
        _current_file: object,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        provider_calls.append({"message": message, **kwargs})
        reply = f"{active_view} provider-backed SSE reply."
        yield {"type": "step", "index": 0, "stop_reason": None}
        yield {"type": "delta", "delta": reply}
        yield {"type": "final", "content": reply, "summary": None, "next_step": None, "stop_reason": "stop"}

    if active_view in {"plan", "resources"}:
        monkeypatch.setattr(ProviderService, "coaching_reply_agentic_stream", fake_agent_stream)
    else:
        monkeypatch.setattr(ProviderService, "coaching_reply_stream", fake_provider_stream)

    with TestClient(app) as client:
        workspace_id = f"four-view-{active_view}"
        session_id = _seed_session(client, workspace_id=workspace_id)
        raw, events = _stream_payload(
            client,
            session_id=session_id,
            workspace_id=workspace_id,
            active_view=active_view,
            message=f"Continue in the {active_view} view.",
            path="/session/message/stream" if active_view == "coach" else "/turn/stream",
            stream_id=f"stream-{active_view}",
            intent=active_view if active_view in {"plan", "resources"} else "coach",
        )

    assert provider_calls
    assert provider_calls[0]["message"] == f"Continue in the {active_view} view."
    assert '"use_agent_loop": true' not in raw
    event_names = [name for name, _ in events]
    assert "complete" in event_names
    complete_index = event_names.index("complete")
    assert complete_index > 0
    chunks = [
        payload["chunk"]
        for name, payload in events[:complete_index]
        if name == "message" and isinstance(payload.get("chunk"), str)
    ]
    assert chunks
    complete = events[complete_index][1]["response"]
    assert "".join(chunks) == complete["reply"]["content"]
    assert complete["reply"]["metadata"]["active_view"] == active_view
    assert provider_calls[0]["coach_context"]["active_view"] == active_view
    if active_view == "plan":
        assert complete["intent"] == "plan"
    if active_view == "resources":
        assert complete["intent"] == "resources"


def test_resources_stream_forwards_composer_intent_and_selected_context(
    app: FastAPI,
    streaming_verified_runtime: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_calls: list[dict[str, Any]] = []

    async def fake_agent_stream(
        _self: ProviderService,
        _profile: object,
        message: str,
        _current_file: object,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        provider_calls.append({"message": message, **kwargs})
        reply = "Resources are ready for review."
        yield {"type": "step", "index": 0, "stop_reason": None}
        yield {"type": "delta", "delta": reply}
        yield {"type": "final", "content": reply, "summary": None, "next_step": None, "stop_reason": "stop"}

    monkeypatch.setattr(ProviderService, "coaching_reply_agentic_stream", fake_agent_stream)
    workspace_id = "four-view-resources-context"
    resource_context = Mock(
        wraps=streaming_verified_runtime.resource_service.build_requested_resource_context
    )
    monkeypatch.setattr(
        streaming_verified_runtime.resource_service,
        "build_requested_resource_context",
        resource_context,
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id=workspace_id)
        uploaded = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "selected-source.md",
                "source": "inline://selected-source.md",
                "content": "# Selected source\nUse a bounded context for the next step.\n",
                "content_encoding": "utf-8",
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        resource = uploaded.json()
        intent = {"mode": "locate", "resource_ids": [resource["id"]]}
        _, events = _stream_payload(
            client,
            session_id=session_id,
            workspace_id=workspace_id,
            active_view="resources",
            message="Locate the selected source.",
            resource_composer_intent=intent,
            resource_ids=[resource["id"]],
            path="/turn/stream",
            stream_id="stream-resources-context",
            intent="resources",
        )

    assert provider_calls
    assert provider_calls[0]["message"] == "Locate the selected source."
    assert provider_calls[0]["coach_context"]["active_view"] == "resources"
    assert provider_calls[0]["coach_context"]["requested_resource_ids"] == [resource["id"]]
    assert provider_calls[0]["coach_context"]["resource_composer_intent"] == {
        "mode": "locate",
        "resource_ids": [resource["id"]],
    }
    state = streaming_verified_runtime.ensure_session(session_id, workspace_id=workspace_id)
    user_message = next(
        message for message in reversed(state.snapshot.messages) if message.role == "user"
    )
    assert user_message.metadata is not None
    assert user_message.metadata["active_view"] == "resources"
    assert resource_context.called
    assert resource_context.call_args.args[:2] == (workspace_id, [resource["id"]])
    complete = next(payload for name, payload in events if name == "complete")["response"]
    assert complete["intent"] == "resources"
    assert complete["reply"]["metadata"]["active_view"] == "resources"


def test_same_workspace_keeps_streamed_messages_across_all_primary_views(
    app: FastAPI,
    streaming_verified_runtime: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies = iter(
        [
            "coach continuity.",
            "plan continuity.",
            "resources continuity.",
            "training continuity.",
        ]
    )

    async def fake_agent_stream(
        _self: ProviderService,
        _profile: object,
        _message: str,
        _current_file: object,
        **_kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        reply = next(replies)
        yield {"type": "step", "index": 0, "stop_reason": None}
        yield {"type": "delta", "delta": reply}
        yield {"type": "final", "content": reply, "summary": None, "next_step": None, "stop_reason": "stop"}

    monkeypatch.setattr(ProviderService, "coaching_reply_agentic_stream", fake_agent_stream)
    workspace_id = "four-view-continuity"
    messages = [
        ("coach", "Start the coaching thread."),
        ("plan", "Carry the thread into planning."),
        ("resources", "Use the same thread for resources."),
        ("training", "Practice from the same thread."),
    ]

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id=workspace_id)
        for active_view, message in messages:
            _, events = _stream_payload(
                client,
                session_id=session_id,
                workspace_id=workspace_id,
            active_view=active_view,
            message=message,
            path="/session/message/stream" if active_view == "coach" else "/turn/stream",
            stream_id=f"stream-continuity-{active_view}",
            intent=active_view if active_view in {"plan", "resources"} else "coach",
        )
            complete = next(payload for name, payload in events if name == "complete")["response"]
            assert complete["session_id"] == session_id

        state = streaming_verified_runtime.ensure_session(session_id, workspace_id=workspace_id)
        persisted = state.snapshot.messages

    user_messages = [message.content for message in persisted if message.role == "user"]
    assert user_messages[-4:] == [message for _, message in messages]
    assert len([message for message in persisted if message.role == "assistant"]) >= 4
    assert all(message.metadata is not None for message in persisted[-8:])
    user_metadata = [
        message.metadata
        for message in persisted
        if message.role == "user" and message.metadata is not None
    ]
    assert [item["stream_state"] for item in user_metadata[-4:]] == ["completed"] * 4
    assert [item["stream_id"] for item in user_metadata[-4:]] == [
        f"stream-continuity-{view}" for view, _ in messages
    ]


@pytest.mark.parametrize(
    ("path", "active_view", "intent", "extra_payload"),
    [
        (
            "/session/message/stream",
            "coach",
            "coach",
            {"use_agent_loop": True},
        ),
        (
            "/session/message/stream",
            "coach",
            "coach",
            {
                "attachments": [
                    {
                        "id": "unverified-tool-attachment",
                        "kind": "file",
                        "name": "notes.md",
                    }
                ]
            },
        ),
        (
            "/turn/stream",
            "plan",
            "plan",
            {"formal_plan_mutation": True},
        ),
    ],
)
def test_streaming_tool_requests_are_rejected_without_verified_tools(
    app: FastAPI,
    streaming_verified_runtime: object,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    active_view: str,
    intent: str,
    extra_payload: dict[str, Any],
) -> None:
    async def unexpected_provider_stream(*_args: Any, **_kwargs: Any) -> AsyncIterator[str]:
        raise AssertionError("tools-gated request must not enter the plain provider stream")
        yield ""

    monkeypatch.setattr(ProviderService, "coaching_reply_stream", unexpected_provider_stream)

    with TestClient(app) as client:
        workspace_id = f"four-view-unverified-tools-{intent}"
        session_id = _seed_session(client, workspace_id=workspace_id)
        payload: dict[str, Any] = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "active_view": active_view,
            "intent": intent,
            "message": "Perform the tools-gated action.",
            "response_language": "en-US",
        }
        payload.update(extra_payload)
        response = client.post(path, json=payload)

    assert response.status_code == 409, response.text
    assert "verified tools-capable provider" in response.json()["detail"]
