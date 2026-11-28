"""Behavior regression tests for Model Config and Information Flow root-cause fixes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.provider_payload import provider_api_key_from_payload, provider_config_from_payload
from app.api.runtime import (
    TrainerRuntime,
    _capability_cache_key_matches_transport,
    _provider_capability_cache_key,
)
from app.core.models import CapabilityFlags, ProviderConfig
from app.db.repository import TrainerRepository
from app.llm.agent_binding import (
    _format_gemini_payload,
    _format_openai_responses_input,
    _split_anthropic_messages,
)
from app.llm.agent_loop import AgentProvider, CoachAgentLoop
from app.llm.harness import compact_history
from app.llm.provider.capability import _allows_keyless_local_provider
from app.llm.provider.text import (
    _allows_cjk_response_language,
    _looks_like_input_corruption_reply,
    _looks_like_mojibake_text,
    _unexpected_cjk_corruption_fragments,
    _wrong_language_cjk_reply_detail,
)
from app.llm.provider.thinking import (
    clamp_anthropic_thinking_budget,
    learned_param_repairs,
    learned_policy,
    remember_param_repairs,
    remember_policy,
    reset_learned_policies,
)
from app.llm.provider_service import ProviderService
from app.llm.tools import ToolContext, _handle_run_diagnostics


def test_provider_payload_distinguishes_empty_key_and_preserves_local_no_auth_and_zero_ttl() -> None:
    assert provider_api_key_from_payload({}) is None
    assert provider_api_key_from_payload({"api_key": ""}) == ""
    assert provider_api_key_from_payload({"apiKey": ""}) == ""
    assert provider_api_key_from_payload({"api_key": "sk-live"}) == "sk-live"

    parsed = provider_config_from_payload(
        {
            "provider": {
                "name": "Local LM Studio",
                "baseUrl": "http://127.0.0.1:1234/v1",
                "model": "qwen2.5-coder",
                "credentialMode": "local_no_auth",
                "cacheTtlSeconds": 0,
            }
        }
    )
    assert parsed is not None
    assert parsed.credential_mode == "local_no_auth"
    assert parsed.cache_ttl_seconds == 0


def test_keyless_local_provider_allows_lm_studio_and_explicit_mode_only() -> None:
    lm_studio = ProviderConfig(
        name="Local Model",
        baseUrl="http://127.0.0.1:1234/v1",
        apiKeyRef="",
        model="qwen2.5-coder",
    )
    explicit = ProviderConfig(
        name="Private Relay",
        baseUrl="http://127.0.0.1:9000/v1",
        apiKeyRef="",
        model="demo",
        credentialMode="local_no_auth",
    )
    private_relay = ProviderConfig(
        name="Private Relay",
        baseUrl="http://127.0.0.1:9000/v1",
        apiKeyRef="",
        model="demo",
    )
    assert _allows_keyless_local_provider(lm_studio) is True
    assert _allows_keyless_local_provider(explicit) is True
    assert _allows_keyless_local_provider(private_relay) is False


def test_clamp_anthropic_thinking_budget_and_protocol_scoped_learning() -> None:
    clamped = clamp_anthropic_thinking_budget(
        {
            "max_tokens": 1000,
            "temperature": 0.4,
            "top_k": 40,
            "top_p": 0.8,
            "thinking": {"type": "enabled", "budgetTokens": 512},
        },
        enforce_min_budget=True,
    )
    assert clamped["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    assert clamped["max_tokens"] == 2048
    assert "temperature" not in clamped
    assert "top_k" not in clamped
    assert "top_p" not in clamped

    reset_learned_policies()
    cfg_chat = ProviderConfig(
        name="GW",
        protocol="openai_chat_completions_compatible",
        baseUrl="https://gw.example/v1",
        model="model-x",
        apiKeyRef="",
    )
    cfg_anthropic = ProviderConfig(
        name="GW",
        protocol="anthropic_messages",
        baseUrl="https://gw.example/v1",
        model="model-x",
        apiKeyRef="",
    )
    remember_policy(cfg_chat, "disabled")
    remember_param_repairs(cfg_chat, ("max_tokens", "temperature"))
    assert learned_policy(cfg_chat) == "disabled"
    assert learned_policy(cfg_anthropic) is None
    assert learned_param_repairs(cfg_chat) == ("max_tokens", "temperature")
    assert learned_param_repairs(cfg_anthropic) == ()
    reset_learned_policies()


def test_error_classification_json_decode_and_4xx_reachability() -> None:
    service = ProviderService(api_key="sk-test")
    category, _retryable, _status, _reachable, _supported = service._classify_error(  # noqa: SLF001
        json.JSONDecodeError("Expecting value", "", 0)
    )
    assert category == "malformed_response"

    class _Fake401(Exception):
        status_code = 401

    auth_cat, _retry, auth_status, auth_reachable, _sup = service._classify_error(  # noqa: SLF001
        _Fake401("Unauthorized")
    )
    assert auth_status == 401
    assert auth_reachable is True
    assert auth_cat != "network_error"


def test_describe_attachment_delivery_ignores_vision_when_no_attachments() -> None:
    cfg = ProviderConfig(
        name="TextOnly",
        baseUrl="https://api.example.com/v1",
        model="text-only-model",
        apiKeyRef="",
        capabilities=CapabilityFlags(vision=False, chat=True),
    )
    service = ProviderService(config=cfg, api_key="sk-test")
    info = service.describe_attachment_delivery(attachments=[], use_agent_loop=True)
    assert info["attachments_present"] is False
    assert info["attachments_delivery_reason"] == "no_attachments"


@pytest.mark.asyncio
async def test_negotiated_chat_completion_repairs_multiple_params_and_caches() -> None:
    reset_learned_policies()
    cfg = ProviderConfig(
        name="ReasoningGW",
        protocol="openai_chat_completions_compatible",
        baseUrl="https://reasoning.example/v1",
        model="o3-mini",
        apiKeyRef="",
    )
    service = ProviderService(config=cfg, api_key="sk-test")

    class _BadRequestError(Exception):
        def __init__(self, msg: str) -> None:
            super().__init__(msg)
            self.status_code = 400

    seen_payloads: list[dict[str, object]] = []

    async def _create(**kwargs: object) -> object:
        seen_payloads.append(dict(kwargs))
        if "max_tokens" in kwargs:
            raise _BadRequestError("Unsupported parameter: 'max_tokens' is not supported, use max_completion_tokens")
        if "temperature" in kwargs:
            raise _BadRequestError("Unsupported parameter: 'temperature' is not supported with this model")
        return SimpleNamespace(ok=True)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=_create))))
    result = await service._create_chat_completion_negotiated_async(  # noqa: SLF001
        client,
        {"model": "o3-mini", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 512, "temperature": 0.2},
        provider=cfg,
    )
    assert getattr(result, "ok", False) is True
    assert len(seen_payloads) == 3
    assert "max_completion_tokens" in seen_payloads[-1]
    assert "max_tokens" not in seen_payloads[-1]
    assert "temperature" not in seen_payloads[-1]
    assert set(learned_param_repairs(cfg)) == {"max_tokens", "temperature"}
    reset_learned_policies()


def test_four_protocol_reasoning_replay_preserves_provider_blocks() -> None:
    anthropic_history = [
        {"role": "user", "content": "inspect"},
        {
            "role": "assistant",
            "content": "Checking file",
            "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "a.py"}}],
            "_provider_reasoning": {
                "anthropic_blocks": [
                    {"type": "thinking", "thinking": "step 1", "signature": "sig-abc"},
                    {"type": "redacted_thinking", "data": "opaque"},
                ]
            },
        },
        {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "ok"},
    ]
    _, anth_msgs = _split_anthropic_messages(anthropic_history, attachments=None, vision_enabled=False)
    assistant_blocks = anth_msgs[1]["content"]
    assert assistant_blocks[0]["type"] == "thinking"
    assert assistant_blocks[0]["signature"] == "sig-abc"
    assert assistant_blocks[1]["type"] == "redacted_thinking"

    gemini_history = [
        {"role": "user", "content": "inspect"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "a.py"}}],
            "_provider_reasoning": {"gemini_thought_signatures": ["tsig-1"]},
        },
    ]
    gem_payload = _format_gemini_payload(gemini_history, None, attachments=None, vision_enabled=False)
    gem_msgs = gem_payload["contents"]
    fc_part = next(part for part in gem_msgs[1]["parts"] if "functionCall" in part)
    assert fc_part["thoughtSignature"] == "tsig-1"

    responses_history = [
        {"role": "user", "content": "inspect"},
        {
            "role": "assistant",
            "content": "checking",
            "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "a.py"}}],
            "_provider_reasoning": {
                "responses_reasoning_items": [{"type": "reasoning", "id": "rs_1", "summary": []}]
            },
        },
    ]
    _, resp_items = _format_openai_responses_input(responses_history, attachments=None, vision_enabled=False)
    assert any(item.get("type") == "reasoning" and item.get("id") == "rs_1" for item in resp_items)


def test_capability_cache_key_exact_transport_matching() -> None:
    cfg_4 = ProviderConfig(name="A", baseUrl="https://api.example.com", model="gpt-4", apiKeyRef="")
    cfg_4o = ProviderConfig(name="B", baseUrl="https://api.example.com", model="gpt-4o", apiKeyRef="")
    cfg_v2 = ProviderConfig(name="C", baseUrl="https://api.example.com/v2", model="gpt-4", apiKeyRef="")

    key_4o = _provider_capability_cache_key(cfg_4o, "sk-1")
    key_v2 = _provider_capability_cache_key(cfg_v2, "sk-1")
    assert (
        _capability_cache_key_matches_transport(
            key_4o, base_url="https://api.example.com", model="gpt-4"
        )
        is False
    )
    assert (
        _capability_cache_key_matches_transport(
            key_v2, base_url="https://api.example.com", model="gpt-4"
        )
        is False
    )
    key_4 = _provider_capability_cache_key(cfg_4, "sk-1")
    assert (
        _capability_cache_key_matches_transport(
            key_4, base_url="https://api.example.com", model="gpt-4"
        )
        is True
    )


def test_context_budget_and_harness_preserve_system_messages_and_tool_call_pairs() -> None:
    history = [
        {"role": "system", "content": "Primary system prompt"},
        {"role": "system", "content": "Secondary policy prompt"},
        {"role": "user", "content": "turn 1 " + ("x" * 600)},
        {
            "role": "assistant",
            "content": "calling tool",
            "tool_calls": [{"id": "call_1", "function": {"name": "search", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "search", "content": "result " + ("y" * 600)},
        {"role": "user", "content": "latest user question"},
    ]
    compact_history(
        history,
        keep_recent_tokens=80,
        force=True,
    )
    system_msgs = [m for m in history if m.get("role") == "system"]
    assert len(system_msgs) >= 2
    # Never leave an orphan tool message without its assistant(tool_calls) parent.
    for idx, msg in enumerate(history):
        if msg.get("role") == "tool":
            assert idx > 0 and history[idx - 1].get("role") == "assistant"
            assert history[idx - 1].get("tool_calls")


def test_text_helpers_fences_japanese_mojibake_and_encoding_qa() -> None:
    assert _allows_cjk_response_language("ja-JP") is True
    assert _wrong_language_cjk_reply_detail(
        "こんにちは、今日は関数を学びます。", response_language="ja-JP"
    ) is None
    # Code fences containing CJK inside an English reply must not trigger corruption.
    en_with_fence = "Here is an example:\n```python\n# 中文注释：打印问候\nprint('你好世界')\n```\nRun it."
    assert _unexpected_cjk_corruption_fragments(en_with_fence, response_language="en-US") == []

    assert _looks_like_mojibake_text("这是一个包含锟字的单独测试") is False
    assert _looks_like_mojibake_text("乱码示例：锟斤拷 烫烫烫") is True
    assert _looks_like_input_corruption_reply(
        "What is mojibake and why do garbled characters appear when decoding UTF-8 as Latin-1?"
    ) is False


@pytest.mark.asyncio
async def test_agent_loop_stream_enforces_step_timeout() -> None:
    async def _stalled_stream(
        _history: list[dict[str, object]], _tools: list[dict[str, object]] | None
    ):
        await asyncio.sleep(5)
        yield {"type": "delta", "delta": "never"}

    provider = AgentProvider(
        protocol="openai_chat_completions_compatible",
        call=AsyncMock(),
        call_stream=_stalled_stream,
    )
    from app.llm.tools import ToolRegistry

    loop = CoachAgentLoop(
        provider=provider,
        registry=ToolRegistry(),
        context=ToolContext(runtime=None, workspace_id="ws-timeout"),
        step_timeout=0.05,
        first_step_timeout=0.05,
    )
    # Bypass min clamp only to keep test instant.
    loop.step_timeout = 0.05
    loop.first_step_timeout = 0.05

    events = [event async for event in loop.run_stream([{"role": "user", "content": "hi"}])]
    final = next(event for event in events if event.get("type") == "final")
    assert final["stop_reason"] == "timeout"


@pytest.mark.asyncio
async def test_run_diagnostics_fails_closed_when_workspace_root_is_none() -> None:
    context = ToolContext(runtime=None, workspace_id="ws-no-root")
    result = await _handle_run_diagnostics(context, {"path": "main.py"})
    assert result.get("ok") is False
    assert "workspace" in str(result.get("error") or "").lower() or "root" in str(result.get("error") or "").lower()


def test_repository_sessions_order_by_updated_at_desc(tmp_path: Path) -> None:
    repo = TrainerRepository(tmp_path / "trainer.db")
    repo.save_session("session-old", "ws-1", {"session_id": "session-old", "turn": 1})
    repo.save_session("session-new", "ws-1", {"session_id": "session-new", "turn": 1})
    latest_first = repo.load_latest_session_for_workspace("ws-1")
    assert latest_first is not None and latest_first["session_id"] == "session-new"

    # Updating the older session must move it ahead of session-new.
    import time

    time.sleep(0.01)
    repo.save_session("session-old", "ws-1", {"session_id": "session-old", "turn": 2})
    latest_after = repo.load_latest_session_for_workspace("ws-1")
    assert latest_after is not None and latest_after["session_id"] == "session-old"
    listed = repo.list_sessions_for_workspace("ws-1")
    assert [item["session_id"] for item in listed[:2]] == ["session-old", "session-new"]


@pytest.mark.asyncio
async def test_runtime_session_lock_serializes_concurrent_turns_and_is_reentrant(tmp_path: Path) -> None:
    from app.core.config import Settings
    from app.main import create_app

    app = create_app(Settings(data_dir=tmp_path))
    runtime: TrainerRuntime = app.state.runtime

    order: list[str] = []
    entered_first = asyncio.Event()
    release_first = asyncio.Event()

    async def _first() -> None:
        async with runtime.acquire_session_lock("sess-lock-1"):
            order.append("first-start")
            entered_first.set()
            # Reentrant lock on the same asyncio task must never deadlock.
            async with runtime.acquire_session_lock("sess-lock-1"):
                order.append("first-reentrant")
            await release_first.wait()
            order.append("first-end")

    async def _second() -> None:
        await entered_first.wait()
        async with runtime.acquire_session_lock("sess-lock-1"):
            order.append("second-start")

    t1 = asyncio.create_task(_first())
    t2 = asyncio.create_task(_second())
    await entered_first.wait()
    await asyncio.sleep(0.02)
    assert order == ["first-start", "first-reentrant"]
    release_first.set()
    await asyncio.gather(t1, t2)
    assert order == ["first-start", "first-reentrant", "first-end", "second-start"]
