from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.models import (
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderTestResponse,
)
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
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
        capabilities={"tools": True, "streaming": True},
    )
    runtime = app.state.runtime
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test-fake"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test-fake")
    runtime.provider_service_cache.clear()
    runtime.remember_provider_capability_test(
        provider,
        "sk-test-fake",
        ProviderTestResponse(
            ok=True,
            detail="mocked provider capability test",
            capability_evidence=[
                ProviderCapabilityEvidence(
                    name="streaming",
                    declared=True,
                    observed=True,
                    state="verified",
                ),
                ProviderCapabilityEvidence(
                    name="tools",
                    declared=True,
                    observed=True,
                    state="verified",
                ),
            ],
            tools_ready=True,
            tool_probe_status="verified",
        ),
    )
    return TestClient(app)


def seed_session(client: TestClient, *, workspace_id: str) -> str:
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": "Trainer Test",
            "profile": {"long_term_goal": "Ship a focused test", "weekly_hours": 4},
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["session_id"])


def stream_error_payload(raw: str) -> dict[str, object]:
    for block in raw.split("\n\n"):
        if not block.startswith("event: error\n"):
            continue
        for line in block.splitlines():
            if line.startswith("data:"):
                return json.loads(line.removeprefix("data:").strip())
    raise AssertionError(f"missing SSE error event: {raw}")


@pytest.mark.parametrize("endpoint", ["/session/message/stream", "/turn/stream"])
@pytest.mark.parametrize("failure_kind", ["event", "exception"])
def test_stream_routes_redact_provider_error_details(
    tmp_path: Path,
    endpoint: str,
    failure_kind: str,
) -> None:
    unsafe_detail = (
        "provider rejected request (HTTP 429): literal sk-test-fake; "
        "Authorization: Bearer bearer-route-secret; "
        "https://provider.invalid/chat?api_key=query-route-secret; "
        "response body: raw upstream response"
    )

    class ProviderFailure(RuntimeError):
        status_code = 429

    async def fake_agentic_stream(self: ProviderService, *_: Any, **__: Any):
        if failure_kind == "event":
            yield {"type": "error", "detail": unsafe_detail}
            return
        raise ProviderFailure(unsafe_detail)

    with build_client(tmp_path) as client, patch.object(
        ProviderService,
        "coaching_reply_agentic_stream",
        new=fake_agentic_stream,
    ):
        session_id = seed_session(client, workspace_id=f"ws-{failure_kind}-{endpoint.count('/')}")
        payload: dict[str, object] = {
            "session_id": session_id,
            "workspace_id": f"ws-{failure_kind}-{endpoint.count('/')}",
            "message": "Give me one small next step.",
            "use_agent_loop": True,
        }
        if endpoint == "/turn/stream":
            payload["intent"] = "coach"
        with client.stream("POST", endpoint, json=payload) as response:
            assert response.status_code == 200
            raw = b"".join(response.iter_bytes()).decode("utf-8", errors="replace")

    error = stream_error_payload(raw)
    detail = str(error["error"])
    assert "HTTP 429" in detail
    assert "sk-test-fake" not in raw
    assert "bearer-route-secret" not in raw
    assert "query-route-secret" not in raw
    assert "raw upstream response" not in raw
    if failure_kind == "exception":
        assert detail == "Provider request failed (HTTP 429)."
    else:
        assert "[REDACTED]" in detail


@pytest.mark.parametrize("endpoint", ["/session/message/stream", "/turn/stream"])
def test_stream_provider_failure_persists_user_turn_once_for_retry(
    tmp_path: Path,
    endpoint: str,
) -> None:
    async def failing_agentic_stream(self: ProviderService, *_args: Any, **__: Any):
        raise RuntimeError("provider unavailable")
        yield {}

    workspace_id = f"ws-stream-persistence-{endpoint.rsplit('/', 1)[-1]}"
    stream_id = f"stream-retry-{endpoint.rsplit('/', 1)[-1]}"
    with build_client(tmp_path) as client, patch.object(
        ProviderService,
        "coaching_reply_agentic_stream",
        new=failing_agentic_stream,
    ):
        started = seed_session(client, workspace_id=workspace_id)
        payload: dict[str, object] = {
            "session_id": started,
            "workspace_id": workspace_id,
            "message": "Keep this turn recoverable.",
            "use_agent_loop": True,
            "stream_id": stream_id,
        }
        if endpoint == "/turn/stream":
            payload["intent"] = "coach"

        first = client.post(endpoint, json=payload)
        second = client.post(endpoint, json=payload)
        restored = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Trainer Test"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert restored.status_code == 200
    snapshot = restored.json()
    messages = snapshot["messages"]
    matching_users = [
        item
        for item in messages
        if item["role"] == "user"
        and item["metadata"].get("stream_id") == stream_id
    ]
    assert len(matching_users) == 1
    assert matching_users[0]["metadata"]["stream_state"] == "failed"
    assert not any(
        item["role"] == "assistant" and "Keep this turn recoverable." in item["content"]
        for item in messages
    )


@pytest.mark.parametrize("endpoint", ["/session/message/stream", "/turn/stream"])
def test_stream_abort_persists_interrupted_user_turn_without_fake_assistant(
    tmp_path: Path,
    endpoint: str,
) -> None:
    async def partial_stream(self: ProviderService, *_args: Any, **__: Any):
        yield "partial provider text that must not become a completed reply"
        yield "late provider text"

    disconnect_checks = 0

    async def disconnect_after_start(_request: Any) -> bool:
        nonlocal disconnect_checks
        disconnect_checks += 1
        return disconnect_checks >= 2

    workspace_id = f"ws-stream-abort-{endpoint.rsplit('/', 1)[-1]}"
    stream_id = f"stream-abort-{endpoint.rsplit('/', 1)[-1]}"
    with (
        build_client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=partial_stream),
        patch("starlette.requests.Request.is_disconnected", new=disconnect_after_start),
    ):
        started = seed_session(client, workspace_id=workspace_id)
        payload: dict[str, object] = {
            "session_id": started,
            "workspace_id": workspace_id,
            "message": "Keep this aborted turn recoverable.",
            "response_language": "en-US",
            "use_agent_loop": False,
            "stream_id": stream_id,
        }
        if endpoint == "/turn/stream":
            payload["intent"] = "coach"
        response = client.post(endpoint, json=payload)
        restored = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Trainer Test"},
        )

    assert response.status_code == 200
    assert "event: complete" not in response.text
    assert "partial provider text" not in response.text
    assert restored.status_code == 200
    messages = restored.json()["messages"]
    matching_users = [
        item
        for item in messages
        if item["role"] == "user"
        and item["metadata"].get("stream_id") == stream_id
    ]
    assert len(matching_users) == 1
    assert matching_users[0]["metadata"]["stream_state"] == "interrupted"
    assert not any(
        item["role"] == "assistant" and "partial provider text" in item["content"]
        for item in messages
    )
