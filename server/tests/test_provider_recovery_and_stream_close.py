"""Journey F offline -> online recovery & M3.1 post-finish SSE close behavior tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import openai
from fastapi.testclient import TestClient

from app.core.models import ProviderConfig, UserProfile
from app.core.settings import AppSettings
from app.llm.agent_binding import _iterate_and_close_provider_stream
from app.llm.provider import streaming
from app.llm.provider_service import ProviderService
from app.main import create_app


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Journey F Recovery Test",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="journey-f.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _sse_body(chunks: list[dict]) -> bytes:
    lines = [f"data: {json.dumps(item, ensure_ascii=False)}\n\n" for item in chunks]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode("utf-8")


async def test_error_classification_unwraps_openai_connection_and_timeout_chains() -> None:
    config = ProviderConfig(
        name="journey-f",
        baseUrl="http://127.0.0.1:19999/v1",
        apiKeyRef="trainer.journey_f",
        model="MiniMax-M3.1-Flash",
        protocol="openai_chat_completions_compatible",
    )
    service = ProviderService(config=config, api_key="sk-test-recovery")

    closed = False

    class DummyClient:
        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    service._client = DummyClient()
    req = httpx.Request("POST", "http://127.0.0.1:19999/v1/chat/completions")
    conn_exc: Exception
    try:
        try:
            raise httpx.ConnectError("All connection attempts failed", request=req)
        except httpx.ConnectError as root:
            raise openai.APIConnectionError(message="Connection error.", request=req) from root
    except Exception as exc:
        conn_exc = exc

    category, retryable, _status, reachable, _supported = service._classify_error(conn_exc)
    assert category == "network"
    assert retryable is True
    assert reachable is False

    service._record_last_reply_failure(
        category=category,
        detail=service._detail_from_category(category, provider=config, error=conn_exc),
        retryable=retryable,
        status_code=None,
        provider_reachable=reachable,
        model_supported=None,
        error=conn_exc,
    )
    await asyncio.sleep(0)
    assert service._client is None
    assert closed is True

    timeout_exc = openai.APITimeoutError(request=req)
    t_cat, t_retry, _t_status, t_reach, _ = service._classify_error(timeout_exc)
    assert t_cat == "timeout"
    assert t_retry is True
    assert t_reach is False


def test_journey_f_offline_then_recovery_over_real_http_transport_and_json_fallback(
    tmp_path: Path,
) -> None:
    provider_payload = {
        "name": "journey-f-local",
        "baseUrl": "http://127.0.0.1:19999",
        "apiKeyRef": "trainer.journey_f",
        "model": "MiniMax-M3.1-Flash",
        "protocol": "openai_chat_completions_compatible",
        "capabilities": {"streaming": True, "tools": False},
    }
    state = {"mode": "offline", "calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["mode"] == "offline":
            raise httpx.ConnectError("Connection refused", request=request)
        if state["mode"] == "json":
            return httpx.Response(
                200,
                json={
                    "id": "chat-json-1",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "服务恢复了。先告诉我这行幂等判断为什么能拦住重复请求？",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream; charset=utf-8"},
            content=_sse_body(
                [
                    {
                        "id": "chat-sse-1",
                        "object": "chat.completion.chunk",
                        "choices": [
                            {"index": 0, "delta": {"role": "assistant", "content": ""}},
                        ],
                    },
                    {
                        "id": "chat-sse-1",
                        "object": "chat.completion.chunk",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "连接恢复正常。先看这行条件判断，它会放行还是拦截重放？"},
                                "finish_reason": None,
                            }
                        ],
                    },
                    {
                        "id": "chat-sse-1",
                        "object": "chat.completion.chunk",
                        "choices": [
                            {"index": 0, "delta": {}, "finish_reason": "stop"},
                        ],
                    },
                ]
            ),
        )

    def make_mock_client(self: ProviderService) -> openai.AsyncOpenAI:
        if self._client is None:
            self._client = openai.AsyncOpenAI(
                api_key=self._api_key or "sk-test",
                base_url=self._normalized_openai_compatible_base_url(),
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            )
        return self._client

    with (
        patch.object(ProviderService, "_get_client", make_mock_client),
        patch.object(ProviderService, "has_recent_language_integrity_success", return_value=True),
        TestClient(create_app(_settings(tmp_path))) as client,
    ):
        started = client.post(
            "/session/start",
            json={
                "workspace_id": "ws-journey-f",
                "workspace_name": "Journey F Repo",
                "profile": {"long_term_goal": "Idempotent handlers", "answer_policy": "guided"},
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        # 1. Upstream offline -> turn reports provider failure cleanly, resets pooled client.
        stale_failed_test = {
            "ok": False,
            "status": "network",
            "detail": "Provider test failed: connection refused",
            "baseUrl": provider_payload["baseUrl"],
            "model": provider_payload["model"],
            "protocol": provider_payload["protocol"],
            "checkedAt": datetime.now(UTC).isoformat(),
        }
        offline_turn = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": "ws-journey-f",
                "message": "解释这行代码在干嘛",
                "intent": "coach",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-journey-f",
                "last_test_result": stale_failed_test,
            },
        )
        def _complete_event_payload(sse_text: str) -> dict[str, object]:
            lines = sse_text.splitlines()
            for idx, line in enumerate(lines):
                if line.strip() == "event: complete":
                    for data_line in lines[idx + 1 :]:
                        if data_line.startswith("data: "):
                            parsed = json.loads(data_line[6:])
                            assert isinstance(parsed, dict)
                            return parsed
                        if not data_line.strip():
                            break
            raise AssertionError(f"Missing event: complete payload in SSE stream: {sse_text!r}")

        assert offline_turn.status_code == 200, offline_turn.text
        offline_complete = _complete_event_payload(offline_turn.text)
        assert offline_complete["reliability"]["outcome"] == "failure"
        runtime = client.app.state.runtime
        service = runtime.provider_service_for(
            ProviderConfig.model_validate(provider_payload),
            "sk-journey-f",
        )
        assert runtime.provider_connection_verified(service) is False

        # 2. Upstream recovers (SSE) while host resend still carries the older stale failed last_test_result.
        state["mode"] = "sse"
        recovered_turn = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": "ws-journey-f",
                "message": "重发：解释这行代码在干嘛",
                "intent": "coach",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-journey-f",
                "last_test_result": stale_failed_test,
            },
        )
        assert recovered_turn.status_code == 200, recovered_turn.text
        assert "连接恢复正常" in recovered_turn.text
        recovered_complete = _complete_event_payload(recovered_turn.text)
        assert recovered_complete["reliability"]["outcome"] != "failure"
        assert runtime.provider_connection_verified(service) is True

        # 3. Non-SSE 200 application/json compatibility mock response also recovers cleanly, and stale
        # failed last_test_result from T0 cannot demote the verified live connection.
        state["mode"] = "json"
        json_turn = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": "ws-journey-f",
                "message": "再换个例子说明",
                "intent": "coach",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-journey-f",
                "last_test_result": stale_failed_test,
            },
        )
        assert json_turn.status_code == 200, json_turn.text
        assert "服务恢复了" in json_turn.text
        json_complete = _complete_event_payload(json_turn.text)
        assert json_complete["reliability"]["outcome"] != "failure"
        assert runtime.provider_connection_verified(service) is True


async def test_hanging_stream_after_finish_reason_closes_promptly() -> None:
    class HangingAfterFinishStream:
        def __init__(self) -> None:
            self.closed = False
            self._step = 0

        def __aiter__(self) -> "HangingAfterFinishStream":
            return self

        async def __anext__(self) -> SimpleNamespace:
            self._step += 1
            if self._step == 1:
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="幂等键确保重试不会重复扣款。"),
                            finish_reason="stop",
                        )
                    ]
                )
            await asyncio.sleep(30.0)
            raise StopAsyncIteration

        async def aclose(self) -> None:
            self.closed = True

    config = ProviderConfig(
        name="m31-stream-close",
        baseUrl="https://example.com/v1",
        apiKeyRef="trainer.m31",
        model="MiniMax-M3.1",
        protocol="openai_chat_completions_compatible",
    )
    service = ProviderService(config=config, api_key="sk-m31")
    profile = UserProfile(long_term_goal="Idempotency", answer_policy="guided")
    hanging_stream_1 = HangingAfterFinishStream()
    hanging_stream_2 = HangingAfterFinishStream()

    async def fake_create_completion(*_args: object, **_kwargs: object):
        return hanging_stream_1, "MiniMax-M3.1"

    with (
        patch.object(streaming, "POST_FINISH_DRAIN_TIMEOUT_SECONDS", 0.12),
        patch.object(streaming, "STREAM_IDLE_TIMEOUT_SECONDS", 5.0),
        patch.object(ProviderService, "_create_chat_completion", fake_create_completion),
    ):
        collected = []
        started = asyncio.get_running_loop().time()
        async for chunk in service.coaching_reply_stream(
            profile,
            "为什么需要幂等键？",
            response_language="zh-CN",
        ):
            collected.append(chunk)
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 1.2
        assert "幂等键确保重试不会重复扣款。" in "".join(collected)
        assert hanging_stream_1.closed is True

        # Also verify agent_binding helper closes a stream that stalls after finish_reason="stop".
        finish_flag = {"done": False}
        binding_started = asyncio.get_running_loop().time()
        binding_chunks = []
        async for chunk in _iterate_and_close_provider_stream(
            hanging_stream_2,
            finish_seen=lambda: finish_flag["done"],
        ):
            binding_chunks.append(chunk)
            if chunk.choices[0].finish_reason == "stop":
                finish_flag["done"] = True
        binding_elapsed = asyncio.get_running_loop().time() - binding_started

        assert binding_elapsed < 1.2
        assert len(binding_chunks) == 1
        assert hanging_stream_2.closed is True
