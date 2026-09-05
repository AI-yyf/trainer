from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.runtime import TrainerRuntime
from app.core.models import ProviderCapabilityEvidence, ProviderConfig, ProviderTestResponse
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Router Scenario Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-router-scenarios.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    provider = ProviderConfig(
        name="test-openai-compatible",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={
            "chat": True,
            "responses": True,
            "vision": False,
            "embeddings": False,
            "tools": False,
            "json_schema": False,
            "streaming": True,
        },
    )
    runtime = app.state.runtime
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
    runtime.provider_service_cache.clear()
    mark_provider_capabilities_verified(runtime, provider, "sk-test", tools=False)
    return TestClient(app)


def mark_provider_capabilities_verified(
    runtime: TrainerRuntime,
    provider: ProviderConfig,
    api_key: str,
    *,
    tools: bool,
) -> None:
    """Seed an explicit probe result for route tests that mock the upstream."""

    evidence = [
        ProviderCapabilityEvidence(
            name="streaming",
            declared=True,
            observed=True,
            state="verified",
        ),
        ProviderCapabilityEvidence(
            name="tools",
            declared=tools,
            observed=True if tools else None,
            state="verified" if tools else "disabled",
        ),
    ]
    runtime.remember_provider_capability_test(
        provider,
        api_key,
        ProviderTestResponse(
            ok=True,
            detail="mocked provider capability test",
            capability_evidence=evidence,
            tools_ready=tools,
            tool_probe_status="verified" if tools else "disabled",
        ),
    )


def completed_stream_response(body: str) -> dict[str, object]:
    marker = 'data: {"tokens":'
    payload = [line for line in body.splitlines() if line.startswith(marker)][-1]
    return json.loads(payload[len("data: ") :])["response"]


def streamed_chunks(body: str) -> list[str]:
    chunks: list[str] = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: ") :])
        if isinstance(payload, dict) and isinstance(payload.get("chunk"), str):
            chunks.append(payload["chunk"])
    return chunks


def streamed_status_phases(body: str) -> list[str]:
    phases: list[str] = []
    for block in body.split("\n\n"):
        if not block.startswith("event: status\n"):
            continue
        for line in block.splitlines():
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[len("data: ") :])
            phase = payload.get("phase") if isinstance(payload, dict) else None
            if isinstance(phase, str):
                phases.append(phase)
    return phases


def find_route_by_path(container: object, path: str) -> object | None:
    routes = getattr(container, "routes", None)
    if not routes:
        return None
    for route in routes:
        if getattr(route, "path", None) == path:
            return route
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            found = find_route_by_path(original_router, path)
            if found is not None:
                return found
    return None


def test_stream_route_completes_honestly_when_provider_was_never_tested(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        runtime.provider_capability_cache.clear()
        start = client.post(
            "/session/start",
            json={"workspace_id": "workspace-unverified-stream", "workspace_name": "Unverified stream"},
        )
        response = client.post(
            "/session/message/stream",
            json={
                "session_id": start.json()["session_id"],
                "workspace_id": "workspace-unverified-stream",
                "message": "Give me the next small debugging step.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    phases = streamed_status_phases(response.text)
    assert "pending" in phases
    assert "executing" in phases
    assert "failed" in phases
    assert "acked" in phases
    body = completed_stream_response(response.text)
    reliability = body.get("reliability") or {}
    assert reliability.get("phase") == "acked"
    assert reliability.get("outcome") == "failure"
    blob = str(body)
    assert (
        "connection is not ready" in blob.lower()
        or "连接还不能用" in blob
        or "Repair the provider" in blob
    )
    actions = [
        str(item.get("action") or "")
        for item in (body.get("suggested_actions") or body.get("suggestedActions") or [])
        if isinstance(item, dict)
    ]
    assert "plan" not in actions
    assert "task" not in actions
    assert "next_task" not in actions


def test_stream_route_rejects_verified_chat_without_streaming_probe(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        provider = runtime.provider_config
        assert isinstance(provider, ProviderConfig)
        runtime.provider_capability_cache.clear()
        runtime.remember_provider_capability_test(
            provider,
            "sk-test",
            ProviderTestResponse(
                ok=True,
                detail="chat probe passed; streaming not observed",
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=None,
                        state="unverified",
                    )
                ],
                tools_ready=False,
                streaming_ready=False,
                stream_probe_status="unverified",
            ),
        )
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-chat-without-stream",
                "workspace_name": "Chat without stream",
            },
        )
        response = client.post(
            "/session/message/stream",
            json={
                "session_id": start.json()["session_id"],
                "workspace_id": "workspace-chat-without-stream",
                "message": "Give me the next small debugging step.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 409
    assert "real streaming probe" in response.json()["detail"]


def test_provider_test_caches_verified_streaming_for_the_matching_service(tmp_path: Path) -> None:
    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Start with the smallest reproducible case."

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        provider = runtime.provider_config
        assert isinstance(provider, ProviderConfig)
        runtime.provider_capability_cache.clear()
        test_result = ProviderTestResponse(
            ok=True,
            detail="mocked provider probe",
            capability_evidence=[
                ProviderCapabilityEvidence(
                    name="streaming",
                    declared=True,
                    observed=True,
                    state="verified",
                )
            ],
        )
        with patch.object(ProviderService, "test", return_value=test_result):
            tested = client.post(
                "/provider/test",
                json={
                    "provider": provider.model_dump(mode="json", by_alias=True),
                    "api_key": "sk-test",
                    "response_language": "en-US",
                },
            )
        assert tested.status_code == 200
        assert runtime.provider_connection_verified(runtime.provider_service)
        assert runtime.provider_capability_state_for(runtime.provider_service, "streaming") == "verified"

        start = client.post(
            "/session/start",
            json={"workspace_id": "workspace-verified-stream", "workspace_name": "Verified stream"},
        )
        with patch.object(ProviderService, "coaching_reply_stream", new=fake_stream):
            response = client.post(
                "/session/message/stream",
                json={
                    "session_id": start.json()["session_id"],
                    "workspace_id": "workspace-verified-stream",
                    "message": "Give me the next small debugging step.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )

    assert response.status_code == 200, response.text
    assert "Start with the smallest reproducible case." in response.text


def test_coach_routes_keep_resolved_scenario_available_to_streaming_paths(tmp_path: Path) -> None:
    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Start by naming the host that owns the workspace."

    with (
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Start by naming the host that owns the workspace."),
        ),
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        build_client(tmp_path) as client,
    ):
        start = client.post(
            "/session/start",
            json={"workspace_id": "workspace-stream-scenarios", "workspace_name": "Stream scenarios"},
        )
        assert start.status_code == 200
        session_id = start.json()["session_id"]
        request = {
            "session_id": session_id,
            "workspace_id": "workspace-stream-scenarios",
            "message": "Teach me VS Code Remote SSH step by step.",
            "response_language": "en-US",
            "use_agent_loop": False,
        }

        message = client.post("/session/message", json=request)
        assert message.status_code == 200
        assert message.json()["coach_turn"]["scenario"] == "remote_workspace"

        message_stream = client.post("/session/message/stream", json=request)
        assert message_stream.status_code == 200
        assert "NameError" not in message_stream.text
        assert completed_stream_response(message_stream.text)["coach_turn"]["scenario"] == "remote_workspace"

        turn_stream = client.post("/turn/stream", json={**request, "intent": "coach"})
        assert turn_stream.status_code == 200
        assert "NameError" not in turn_stream.text
        assert completed_stream_response(turn_stream.text)["coach_turn"]["scenario"] == "remote_workspace"


@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
def test_coach_stream_emits_checked_text_before_the_completion_event(
    tmp_path: Path,
    path: str,
) -> None:
    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Start with one observable fact. "
        yield "Then verify that fact before you widen the task."

    workspace_id = f"workspace-live-stream-{path.rsplit('/', 1)[-1]}"
    with (
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        build_client(tmp_path) as client,
    ):
        start = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Live stream"},
        )
        assert start.status_code == 200
        payload: dict[str, object] = {
            "session_id": start.json()["session_id"],
            "workspace_id": workspace_id,
            "message": "Help me make the next debugging step smaller.",
            "response_language": "en-US",
            "use_agent_loop": False,
        }
        if path == "/turn/stream":
            payload["intent"] = "coach"
        response = client.post(path, json=payload)

    assert response.status_code == 200, response.text
    first_chunk = 'data: {"chunk": "Start with one observable fact. "}'
    second_chunk = 'data: {"chunk": "Then verify that fact before you widen the task."}'
    assert first_chunk in response.text
    assert second_chunk in response.text
    assert response.text.index(first_chunk) < response.text.index(second_chunk)
    assert response.text.index(second_chunk) < response.text.index("event: complete")


@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
def test_coach_stream_reports_real_preparation_phases_outside_reply_text(
    tmp_path: Path,
    path: str,
) -> None:
    first_reply_chunk = "Start with one observable fact. "

    async def fake_stream(*_args: object, **_kwargs: object):
        yield first_reply_chunk

    workspace_id = f"workspace-stream-status-{path.rsplit('/', 1)[-1]}"
    with (
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        build_client(tmp_path) as client,
    ):
        start = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Stream status"},
        )
        assert start.status_code == 200
        payload: dict[str, object] = {
            "session_id": start.json()["session_id"],
            "workspace_id": workspace_id,
            "message": "Help me make the next debugging step smaller.",
            "response_language": "en-US",
            "use_agent_loop": False,
        }
        if path == "/turn/stream":
            payload["intent"] = "coach"
        response = client.post(path, json=payload)

    assert response.status_code == 200, response.text
    assert streamed_status_phases(response.text) == ["preparing_context", "requesting_model"]
    first_chunk = f'data: {{"chunk": "{first_reply_chunk}"}}'
    assert response.text.index("event: status") < response.text.index(first_chunk)
    assert response.text.index(first_chunk) < response.text.index("event: complete")
    assert all("phase" not in chunk for chunk in streamed_chunks(response.text))


@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
def test_coach_stream_does_not_repeat_the_final_reply(
    tmp_path: Path,
    path: str,
) -> None:
    first = "Start with one observable fact. "
    second = "Then verify that fact before you widen the task."

    async def fake_stream(*_args: object, **_kwargs: object):
        yield first
        yield second

    workspace_id = f"workspace-stream-no-repeat-{path.rsplit('/', 1)[-1]}"
    with (
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        build_client(tmp_path) as client,
    ):
        start = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "No repeat"},
        )
        assert start.status_code == 200
        payload: dict[str, object] = {
            "session_id": start.json()["session_id"],
            "workspace_id": workspace_id,
            "message": "Help me make the next debugging step smaller.",
            "response_language": "en-US",
            "use_agent_loop": False,
        }
        if path == "/turn/stream":
            payload["intent"] = "coach"
        response = client.post(path, json=payload)

    assert response.status_code == 200, response.text
    assert streamed_chunks(response.text) == [first, second]
    complete = completed_stream_response(response.text)
    assert "".join(streamed_chunks(response.text)) == complete["reply"]["content"]


def test_turn_stream_non_coach_uses_provider_stream_and_keeps_structured_snapshot(
    tmp_path: Path,
) -> None:
    provider_chunks = [
        "Use one observable fact. ",
        "Then verify it before widening the task.",
    ]
    calls: list[str] = []

    async def fake_stream(*_args: object, **_kwargs: object):
        calls.append("stream")
        for chunk in provider_chunks:
            yield chunk

    with (
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        build_client(tmp_path) as client,
    ):
        start = client.post(
            "/session/start",
            json={"workspace_id": "workspace-turn-stream-non-coach", "workspace_name": "Non coach"},
        )
        assert start.status_code == 200
        session_id = start.json()["session_id"]
        plan = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-turn-stream-non-coach",
                "objectives": ["Break this into a task"],
            },
        )
        assert plan.status_code == 200, plan.text
        payload: dict[str, object] = {
            "session_id": session_id,
            "workspace_id": "workspace-turn-stream-non-coach",
            "intent": "task",
            "message": "Break this into a task.",
            "response_language": "en-US",
            "use_agent_loop": False,
        }
        response = client.post("/turn/stream", json=payload)

    assert response.status_code == 200, response.text
    assert calls == ["stream"]
    chunks = streamed_chunks(response.text)
    assert chunks == provider_chunks
    assert response.text.index('data: {"chunk": "Use one observable fact. "}') < response.text.index(
        'data: {"chunk": "Then verify it before widening the task."}'
    )
    assert response.text.index("event: complete") > response.text.index(
        'data: {"chunk": "Then verify it before widening the task."}'
    )
    complete = completed_stream_response(response.text)
    assert complete["reply"]["content"] == "".join(chunks)
    assert complete["intent"] == "task"
    assert complete["snapshot"]["current_task"]["title"] == "Break this into a task"
    assert complete["artifacts"]


@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
def test_agent_stream_rejects_an_unsafe_text_event_even_when_marked_checked(
    tmp_path: Path,
    path: str,
) -> None:
    async def fake_agent_stream(*_args: object, **_kwargs: object):
        yield {
            "type": "text",
            "delta": f"{chr(0xE000)}坏片段",
            "safe_to_stream": True,
        }
        yield {
            "type": "final",
            "content": "这是一条已检查的回答。",
            "summary": "",
            "next_step": "",
            "stop_reason": "completed",
        }

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="test-agent-stream",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()
        mark_provider_capabilities_verified(runtime, provider, "sk-test", tools=True)

        with patch.object(ProviderService, "coaching_reply_agentic_stream", new=fake_agent_stream):
            workspace_id = f"workspace-agent-stream-{path.rsplit('/', 1)[-1]}"
            start = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": "Agent stream"},
            )
            assert start.status_code == 200
            payload: dict[str, object] = {
                "session_id": start.json()["session_id"],
                "workspace_id": workspace_id,
                "message": "请直接回答这个问题。",
                "response_language": "zh-CN",
                "answer_mode": "direct",
                "use_agent_loop": True,
            }
            if path == "/turn/stream":
                payload["intent"] = "coach"
            response = client.post(path, json=payload)

    assert response.status_code == 200, response.text
    assert "\\ue000" not in response.text.lower()
    assert chr(0xE000) not in response.text
    complete = completed_stream_response(response.text)
    assert complete["reply"]["content"] == "这是一条已检查的回答。"
    chunks = [line for line in response.text.splitlines() if '"chunk"' in line]
    assert len(chunks) == 1


@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
@pytest.mark.parametrize("use_agent_loop", [False, True])
def test_stream_never_emits_gbk_mojibake_split_across_chunks(
    tmp_path: Path,
    path: str,
    use_agent_loop: bool,
) -> None:
    corrupted = "\u6d93\u5b29\u7af4\u9352\u20ac"

    async def fake_reply_stream(*_args: object, **_kwargs: object):
        for character in corrupted:
            yield character

    async def fake_agent_stream(*_args: object, **_kwargs: object):
        for character in corrupted:
            yield {"type": "text", "delta": character, "safe_to_stream": True}
        yield {
            "type": "final",
            "content": "Use the clean final reply instead.",
            "summary": "",
            "next_step": "",
            "stop_reason": "completed",
        }

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="test-split-mojibake-stream",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()
        mark_provider_capabilities_verified(runtime, provider, "sk-test", tools=True)

        stream_patch = patch.object(
            ProviderService,
            "coaching_reply_agentic_stream" if use_agent_loop else "coaching_reply_stream",
            new=fake_agent_stream if use_agent_loop else fake_reply_stream,
        )
        with stream_patch:
            workspace_id = (
                f"workspace-split-mojibake-{'agent' if use_agent_loop else 'plain'}-"
                f"{path.rsplit('/', 1)[-1]}"
            )
            start = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": "Split mojibake"},
            )
            assert start.status_code == 200
            payload: dict[str, object] = {
                "session_id": start.json()["session_id"],
                "workspace_id": workspace_id,
                "message": "Give me one small debugging step.",
                "response_language": "en-US",
                "answer_mode": "direct",
                "use_agent_loop": use_agent_loop,
            }
            if path == "/turn/stream":
                payload["intent"] = "coach"
            response = client.post(path, json=payload)

    assert response.status_code == 200, response.text
    assert corrupted not in "".join(streamed_chunks(response.text))
    complete = completed_stream_response(response.text)
    assert corrupted not in complete["reply"]["content"]


@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
def test_agent_stream_forwards_checked_prefix_and_only_the_final_suffix(
    tmp_path: Path,
    path: str,
) -> None:
    prefix = "Start with one observable fact in the current behavior. "
    final_content = prefix + "Then verify that fact before you widen the task."

    async def fake_agent_stream(*_args: object, **_kwargs: object):
        yield {"type": "text", "delta": prefix, "safe_to_stream": True}
        yield {
            "type": "final",
            "content": final_content,
            "summary": "",
            "next_step": "",
            "stop_reason": "completed",
        }

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="test-agent-stream-checked-prefix",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()
        mark_provider_capabilities_verified(runtime, provider, "sk-test", tools=True)

        with patch.object(ProviderService, "coaching_reply_agentic_stream", new=fake_agent_stream):
            workspace_id = f"workspace-agent-prefix-{path.rsplit('/', 1)[-1]}"
            start = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": "Agent prefix"},
            )
            assert start.status_code == 200
            payload: dict[str, object] = {
                "session_id": start.json()["session_id"],
                "workspace_id": workspace_id,
                "message": "Answer directly with the smallest next debugging step.",
                "response_language": "en-US",
                "answer_mode": "direct",
                "use_agent_loop": True,
            }
            if path == "/turn/stream":
                payload["intent"] = "coach"
            response = client.post(path, json=payload)

    assert response.status_code == 200, response.text
    assert streamed_chunks(response.text) == [prefix, final_content[len(prefix) :]]
    complete = completed_stream_response(response.text)
    assert "".join(streamed_chunks(response.text)) == complete["reply"]["content"]


@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
def test_agent_stream_uses_local_recovery_without_a_second_model_call(
    tmp_path: Path,
    path: str,
) -> None:
    async def fake_agent_stream(*_args: object, **_kwargs: object):
        yield {
            "type": "final",
            "content": "",
            "summary": "The provider returned an empty visible answer.",
            "next_step": "Retry with a visible conclusion.",
            "stop_reason": "empty_response",
        }

    plain_reply = AsyncMock(return_value="This second model call must not happen.")
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="test-agent-stream-local-recovery",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()
        mark_provider_capabilities_verified(runtime, provider, "sk-test", tools=True)

        with (
            patch.object(ProviderService, "coaching_reply_agentic_stream", new=fake_agent_stream),
            patch.object(ProviderService, "coaching_reply", new=plain_reply),
        ):
            workspace_id = f"workspace-agent-local-recovery-{path.rsplit('/', 1)[-1]}"
            start = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": "Agent local recovery"},
            )
            assert start.status_code == 200
            payload: dict[str, object] = {
                "session_id": start.json()["session_id"],
                "workspace_id": workspace_id,
                "message": "Keep the current learning thread moving.",
                "response_language": "en-US",
                "answer_mode": "direct",
                "use_agent_loop": True,
            }
            if path == "/turn/stream":
                payload["intent"] = "coach"
            response = client.post(path, json=payload)

    assert response.status_code == 200, response.text
    plain_reply.assert_not_awaited()
    complete = completed_stream_response(response.text)
    assert "This second model call must not happen." not in complete["reply"]["content"]


def test_training_card_stream_emits_fragments_before_complete_and_persists_card(
    tmp_path: Path,
) -> None:
    card_payload = {
        "title": "Practice streaming JSON",
        "focus_area": "JSON",
        "target_skill": "stream parsing",
        "scenario": "Build a safe parser",
        "problem_statement": "Parse one response without losing boundaries.",
        "api_hints": ["Use the accumulated visible chunks."],
        "deliverable": "A parsed card",
        "self_check": ["Verify the JSON before persistence."],
        "grading_rubric": ["The card is complete and grounded."],
        "stuck_recovery": "Inspect the accumulated response.",
        "reflection_prompt": "What boundary made the parse reliable?",
    }
    raw = json.dumps(card_payload)
    first_chunk, second_chunk = raw[: len(raw) // 2], raw[len(raw) // 2 :]

    async def fake_stream(*_args: object, **_kwargs: object):
        yield first_chunk
        yield second_chunk

    with patch.object(ProviderService, "chat_completion_stream", new=fake_stream):
        with build_client(tmp_path) as client:
            workspace_id = "workspace-training-card-stream"
            response = client.post(
                "/training/generate-card/stream",
                json={
                    "workspace_id": workspace_id,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "JSON",
                    "target_skill": "stream parsing",
                    "context_hint": "Generate one small practice card.",
                    "response_language": "en-US",
                },
            )
            cards = client.app.state.runtime.memory_service.get_cards(workspace_id)

    assert response.status_code == 200, response.text
    assert f'data: {{"chunk": {json.dumps(first_chunk)}}}' in response.text
    assert f'data: {{"chunk": {json.dumps(second_chunk)}}}' in response.text
    first_line = f'data: {{"chunk": {json.dumps(first_chunk)}}}'
    assert response.text.index(first_line) < response.text.index("event: complete")
    complete = completed_stream_response(response.text)
    assert complete["card"]["title"] == card_payload["title"]
    assert any(card.title == card_payload["title"] for card in cards)


def test_training_card_stream_uses_request_provider_without_mutating_runtime_service(
    tmp_path: Path,
) -> None:
    card_payload = {
        "title": "Practice request-scoped provider",
        "focus_area": "provider binding",
        "target_skill": "keep a training stream request-scoped",
        "scenario": "Generate one card through an override provider.",
        "problem_statement": "Keep the provider isolated to this request.",
        "api_hints": ["Use the configured request provider only."],
        "deliverable": "A routed practice card",
        "self_check": ["The runtime provider was not overwritten."],
        "grading_rubric": ["The card is persisted."],
        "stuck_recovery": "Check the request provider transport.",
        "reflection_prompt": "Why should provider state stay request-scoped?",
    }
    observed_services: list[ProviderService] = []

    async def fake_stream(self: ProviderService, *_args: object, **_kwargs: object):
        observed_services.append(self)
        yield json.dumps(card_payload)

    with patch.object(ProviderService, "chat_completion_stream", new=fake_stream):
        with build_client(tmp_path) as client:
            runtime = client.app.state.runtime
            default_provider = runtime.provider_service
            assert runtime.card_generation_service is not None
            original_card_provider = runtime.card_generation_service._provider
            override_provider = ProviderConfig(
                name="preview-card-provider",
                base_url="http://127.0.0.1:9/v1",
                api_key_ref="preview.training",
                model="preview-card-model",
                capabilities={"chat": True, "streaming": True},
            )
            mark_provider_capabilities_verified(
                runtime,
                override_provider,
                "test-preview-card-key",
                tools=False,
            )
            response = client.post(
                "/training/generate-card/stream",
                json={
                    "workspace_id": "workspace-training-card-provider-override",
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "provider binding",
                    "target_skill": "request-scoped training stream",
                    "provider": {
                        "name": "preview-card-provider",
                        "baseUrl": "http://127.0.0.1:9/v1",
                        "apiKeyRef": "preview.training",
                        "model": "preview-card-model",
                        "capabilities": {"chat": True, "streaming": True},
                    },
                    "api_key": "test-preview-card-key",
                },
            )

            assert response.status_code == 200, response.text
            assert "event: complete" in response.text
            assert runtime.provider_service is default_provider
            assert runtime.card_generation_service._provider is original_card_provider

    assert len(observed_services) == 1
    assert observed_services[0] is not default_provider
    assert observed_services[0]._config is not None
    assert observed_services[0]._config.model == "preview-card-model"


def test_training_card_stream_redacts_provider_error(tmp_path: Path) -> None:
    async def fake_stream(*_args: object, **_kwargs: object):
        raise RuntimeError("upstream rejected key sk-training-card-secret")
        yield "unreachable"

    with patch.object(ProviderService, "chat_completion_stream", new=fake_stream):
        with build_client(tmp_path) as client:
            response = client.post(
                "/training/generate-card/stream",
                json={
                    "workspace_id": "workspace-training-card-error",
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "JSON",
                    "target_skill": "stream parsing",
                    "response_language": "en-US",
                },
            )

    assert response.status_code == 200
    assert "event: error" in response.text
    assert "sk-training-card-secret" not in response.text
    assert "event: complete" in response.text
    assert '"phase": "failed"' in response.text
    assert '"phase": "acked"' in response.text
    assert '"outcome": "failure"' in response.text


def test_training_card_stream_falls_back_without_a_second_provider_call(tmp_path: Path) -> None:
    calls = 0

    async def fake_stream(*_args: object, **_kwargs: object):
        nonlocal calls
        calls += 1
        yield "not valid card JSON"

    with patch.object(ProviderService, "chat_completion_stream", new=fake_stream):
        with build_client(tmp_path) as client:
            response = client.post(
                "/training/generate-card/stream",
                json={
                    "workspace_id": "workspace-training-card-fallback",
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "JSON",
                    "target_skill": "stream parsing",
                    "response_language": "en-US",
                },
            )

    assert response.status_code == 200
    assert calls == 1
    assert "event: error" in response.text
    completed = completed_stream_response(response.text)
    assert not completed.get("card")
    runtime_cards = tmp_path / "sandboxes"
    if runtime_cards.exists():
        assert not list(runtime_cards.rglob("cards/**/*.md"))
