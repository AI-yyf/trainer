from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.models import ProviderConfig, UserProfile
from app.llm.agent_loop import CoachAgentLoop
from app.llm.prompts import (
    build_coaching_messages,
    build_coaching_system_prompt,
    coaching_scenario_label,
    extract_coaching_context,
    infer_coaching_scenario,
    infer_learner_signal,
)
from app.llm.provider_service import (
    _LANGUAGE_PROBE_VARIANTS,
    _NATURAL_LANGUAGE_PROBE_PROMPT,
    DEFAULT_OPENAI_CLIENT_MAX_RETRIES,
    DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS,
    ProviderService,
    _agentic_practice_verification_context_active,
    _build_agent_tool_context_extra,
    _build_language_corruption_recovery_override,
    _build_provider_error_recovery_override,
    _build_timeout_recovery_override,
    _claims_verified_practice_completion,
    _first_turn_guided_lane,
    _localized_text,
    _mixed_script_reply_corruption_detail,
    _sanitize_agentic_continuity_text,
    _visible_model_text,
    redact_provider_error,
)


def _make_profile(**overrides: object) -> UserProfile:
    defaults = {
        "long_term_goal": "Build a FastAPI trainer",
        "background": "Intermediate Python developer",
        "weekly_hours": 6,
        "teaching_style": "guided",
        "answer_policy": "guided",
        "preferred_libraries": ["fastapi", "pytest"],
    }
    defaults.update(overrides)
    return UserProfile(**defaults)  # type: ignore[arg-type]


def _chat_completion_user_text(kwargs: dict[str, object]) -> str:
    messages = kwargs.get("messages")
    if not isinstance(messages, list) or not messages:
        return ""
    last = messages[-1]
    if isinstance(last, dict):
        return str(last.get("content") or "")
    return str(getattr(last, "content", "") or "")


def _is_openai_capability_probe_call(kwargs: dict[str, object]) -> bool:
    if kwargs.get("tools"):
        return True
    content = _chat_completion_user_text(kwargs)
    return "THINKING_OK" in content or "trainer_capability_probe" in content


def _provider_test_reply_for_prompt(last_user: str, primary_reply: str) -> str:
    if "Reply with exactly: pong" in last_user or "provider ready" in last_user:
        return primary_reply
    for prompt_text, expected_output in _LANGUAGE_PROBE_VARIANTS:
        if prompt_text in last_user:
            return expected_output
    return primary_reply


def _make_config() -> ProviderConfig:
    return ProviderConfig(
        name="test-provider",
        base_url="https://api.openai.com/v1",
        api_key_ref="trainer.test",
        model="gpt-4o-mini",
    )


async def _unused_native_stream(*_args: object, **_kwargs: object):
    if False:
        yield {}


def test_redact_provider_error_removes_credentials_and_upstream_bodies() -> None:
    api_key = "sk-live-provider-secret"
    redacted = redact_provider_error(
        (
            f"Authorization: Bearer {api_key}; x-api-key={api_key}; "
            f"https://gateway.example/v1?api_key={api_key}&access_token=token-secret&x-goog-api-key=google-secret"
        ),
        api_key=api_key,
    )
    body_redacted = redact_provider_error(
        {"upstream_body": {"message": "raw provider body", "api_key": api_key}},
        api_key=api_key,
        fallback="Provider test failed (HTTP 401)",
    )
    exception_redacted = redact_provider_error(
        RuntimeError(f"Error code: 401 - {{'body': 'raw provider body', 'token': '{api_key}'}}"),
        api_key=api_key,
    )

    assert api_key not in redacted
    assert "token-secret" not in redacted
    assert "google-secret" not in redacted
    assert "[REDACTED]" in redacted
    assert "api_key=[REDACTED]" in redacted
    assert body_redacted == "Provider test failed (HTTP 401); upstream response body redacted."
    assert "raw provider body" not in exception_redacted
    assert api_key not in exception_redacted


def test_redact_provider_error_hides_traceback_json_and_think_text() -> None:
    fake_key = "sk-test-not-a-real-key-aaaaaaaa"
    traceback_redacted = redact_provider_error(
        'Traceback (most recent call last):\n  File "app.py", line 12, in run\nKeyError'
    )
    json_redacted = redact_provider_error(
        '{"choices":[{"message":{"content":"hidden"}}],"token":"fake-token-zzzz"}'
    )
    think_redacted = redact_provider_error(
        f"<think>do not leak {fake_key}</think> Provider request failed"
    )

    assert "Traceback" not in traceback_redacted
    assert "File \"" not in traceback_redacted
    assert "technical details hidden" in traceback_redacted
    assert "choices" not in json_redacted
    assert "fake-token-zzzz" not in json_redacted
    assert "upstream response body redacted" in json_redacted
    assert fake_key not in think_redacted
    assert "<think>" not in think_redacted
    assert "hidden reasoning redacted" in think_redacted


def test_provider_config_accepts_camel_case_fields() -> None:
    config = ProviderConfig.model_validate(
        {
            "name": "camel-provider",
            "baseUrl": "https://example.com/v1",
            "apiKeyRef": "trainer.camel",
            "model": "MiMo-V2.5",
            "protocol": "anthropic_messages",
            "label": "Camel Provider",
            "mode": "direct",
            "credentialMode": "workspace_secret",
            "availableModels": ["MiniMax-M3"],
            "allowedModels": ["MiniMax-M3"],
            "deniedModels": ["MiniMax-M1"],
            "modelAliases": {"coach-fast": "MiniMax-M3"},
            "modelCapabilities": {
                "MiniMax-M3": {
                    "chat": True,
                    "responses": False,
                    "vision": True,
                    "embeddings": False,
                    "tools": True,
                    "jsonSchema": False,
                    "streaming": True,
                }
            },
            "taskBindings": {"coach_reply": {"alias": "coach-fast"}},
            "contextWindowTokens": 131072,
            "maxOutputTokens": 8192,
            "embeddingModel": None,
            "catalogSource": "manual",
            "cacheTtlSeconds": 3600,
            "profileId": "profile-anthropic",
            "profileLabel": "Anthropic Test",
            "profileMode": "direct",
            "requestDefaults": {
                "extra_body": {
                    "thinking": {
                        "type": "disabled",
                    }
                }
            },
            "capabilities": {
                "chat": True,
                "responses": True,
                "vision": False,
                "embeddings": False,
                "tools": False,
                "jsonSchema": False,
                "streaming": True,
            },
        }
    )
    assert config.base_url == "https://example.com/v1"
    assert config.api_key_ref == "trainer.camel"
    assert config.model == "MiMo-V2.5"
    assert config.protocol == "anthropic_messages"
    assert config.credential_mode == "workspace_secret"
    assert config.available_models == ["MiniMax-M3"]
    assert config.model_aliases["coach-fast"] == "MiniMax-M3"
    assert config.model_capabilities["MiniMax-M3"].tools is True
    assert config.task_bindings["coach_reply"]["alias"] == "coach-fast"
    assert config.context_window_tokens == 131072
    assert config.max_output_tokens == 8192
    assert config.cache_ttl_seconds == 3600
    assert config.profile_id == "profile-anthropic"
    assert config.request_defaults["extra_body"]["thinking"]["type"] == "disabled"
    assert config.capabilities.json_schema is False


def test_visible_model_text_normalizes_problematic_unicode_punctuation() -> None:
    assert _visible_model_text("Good call \u2014 teach this first\u2026 then test it.") == (
        "Good call - teach this first... then test it."
    )
    assert _visible_model_text("Set the breakpoint \u2013 then inspect one value.") == (
        "Set the breakpoint - then inspect one value."
    )


def test_visible_model_text_removes_provider_control_tool_markers() -> None:
    assert _visible_model_text("]<]minimax[>[<tool_call>\n]<]minimax[>[") == ""
    assert _visible_model_text(
        "先确认 remote host。\n]<]minimax[>[<tool_call>{}\n]</tool_call>"
    ) == "先确认 remote host。"


def test_provider_test_returns_failure_when_model_is_not_supported() -> None:
    config = _make_config()
    service = ProviderService()
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = Exception(
        "Error code: 400 - {'error': {'message': 'Not supported model MiMo-V2.5'}}"
    )

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test", response_language="zh-CN")

    assert result.ok is False
    assert result.detail is not None
    assert "not accepted" in result.detail.lower()
    assert config.model in result.detail


def test_provider_test_applies_passed_provider_request_defaults_without_self_config() -> None:
    config = ProviderConfig(
        name="minimax-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        request_defaults={
            "extra_body": {
                "thinking": {
                    "type": "disabled"
                }
            }
        },
    )
    service = ProviderService()
    fake_client = MagicMock()

    def completion_side_effect(*, messages: list[dict[str, str]], **kwargs: object):
        fake_response = MagicMock()
        fake_choice = MagicMock()
        last_user = messages[-1]["content"]
        if "只返回一个可见中文短句：provider ready。" in last_user:
            fake_choice.message.content = ""
        elif "请只输出可见文字：provider ready。" in last_user:
            fake_choice.message.content = "Provider is ready."
        else:
            fake_choice.message.content = _provider_test_reply_for_prompt(last_user, "pong")
        fake_response.choices = [fake_choice]
        return fake_response

    fake_client.chat.completions.create.side_effect = completion_side_effect

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test", response_language="zh-CN")

    assert result.ok is True
    prompts: list[str] = []
    for _, kwargs in fake_client.chat.completions.create.call_args_list:
        extra_body = kwargs["extra_body"]
        thinking_type = extra_body["thinking"]["type"]
        user_text = _chat_completion_user_text(kwargs)
        if "THINKING_OK" in user_text:
            assert thinking_type == "enabled"
        else:
            assert thinking_type == "disabled"
        messages = kwargs["messages"]
        if isinstance(messages, list) and messages:
            prompts.append(messages[-1]["content"])
    assert "只返回一个可见中文短句：provider ready。" in prompts
    assert any(
        "请只输出可见文字：provider ready。" in prompt
        for prompt in prompts
    )


def test_provider_test_openai_compatible_probe_matches_response_language() -> None:
    config = ProviderConfig(
        name="minimax-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="openai_chat_completions_compatible",
    )
    service = ProviderService()
    fake_client = MagicMock()

    def completion_side_effect(*, messages: list[dict[str, str]], **_: object):
        last_user = messages[-1]["content"]
        mock_choice = MagicMock()
        if "provider ready" in last_user:
            mock_choice.message.content = "provider ready。"
        else:
            mock_choice.message.content = _provider_test_reply_for_prompt(last_user, "pong")
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    fake_client.chat.completions.create.side_effect = completion_side_effect

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test", response_language="zh-CN")

    assert result.ok is True
    prompts = [
        kwargs["messages"][-1]["content"]
        for _, kwargs in fake_client.chat.completions.create.call_args_list
        if isinstance(kwargs.get("messages"), list)
    ]
    connectivity_calls = [
        kwargs
        for _, kwargs in fake_client.chat.completions.create.call_args_list
        if not _is_openai_capability_probe_call(kwargs)
    ]
    assert connectivity_calls
    assert all(kwargs["max_tokens"] == 1024 for kwargs in connectivity_calls)
    assert "只返回一个可见中文短句：provider ready。" in prompts
    assert all("Reply with exactly: pong" not in prompt for prompt in prompts)


def test_native_provider_probe_prompts_are_readable_and_language_aware() -> None:
    service = ProviderService()

    zh_prompts = service._native_probe_prompts("zh-CN")  # noqa: SLF001
    en_prompts = service._native_probe_prompts("en-US")  # noqa: SLF001

    assert zh_prompts == [
        "只返回一个可见中文短句：provider ready。",
        "请只输出可见文字：provider ready。不要只返回 reasoning、tool call 或 hidden text。",
    ]
    assert en_prompts[0] == "Reply with exactly: pong"
    assert all("鍙" not in prompt and "璇" not in prompt for prompt in zh_prompts)


def test_provider_test_flags_question_mark_language_corruption_as_unusable_reply() -> None:
    config = ProviderConfig(
        name="minimax-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
    )
    service = ProviderService()
    fake_client = MagicMock()

    def completion_side_effect(*, messages: list[dict[str, str]], **_: object):
        last_user = messages[-1]["content"]
        mock_choice = MagicMock()
        if "Reply with exactly: pong" in last_user:
            mock_choice.message.content = "pong"
        else:
            mock_choice.message.content = (
                "The message looks garbled and I only saw question marks: ????? ABC123"
            )
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    fake_client.chat.completions.create.side_effect = completion_side_effect

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test", response_language="zh-CN")

    assert result.ok is False
    assert result.error_category == "language_corruption"
    assert result.provider_reachable is True
    assert result.model_supported is True
    assert "问号" in (result.detail or "")


def test_provider_test_accepts_natural_zh_probe_when_exact_echo_is_unstable() -> None:
    config = ProviderConfig(
        name="minimax-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
    )
    service = ProviderService()
    fake_client = MagicMock()

    def completion_side_effect(*, messages: list[dict[str, str]], **_: object):
        last_user = messages[-1]["content"]
        mock_choice = MagicMock()
        if "只返回一个可见中文短句：provider ready。" in last_user:
            mock_choice.message.content = "provider ready。"
        elif "Reply with exactly: pong" in last_user:
            mock_choice.message.content = "pong"
        elif last_user == _NATURAL_LANGUAGE_PROBE_PROMPT:
            mock_choice.message.content = "先学再测，先确认 VS Code 远程工作区边界。"
        else:
            mock_choice.message.content = ""
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    fake_client.chat.completions.create.side_effect = completion_side_effect

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test", response_language="zh-CN")

    assert result.ok is True
    assert "自然" in (result.detail or "")
    assert "zh-CN" in (result.detail or "")
    prompts = [
        kwargs["messages"][-1]["content"]
        for _, kwargs in fake_client.chat.completions.create.call_args_list
        if isinstance(kwargs.get("messages"), list)
    ]
    assert any(prompt == _NATURAL_LANGUAGE_PROBE_PROMPT for prompt in prompts)


def test_provider_test_retries_blank_chat_probe_before_reporting_empty_response() -> None:
    config = ProviderConfig(
        name="minimax-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
    )
    service = ProviderService()
    fake_client = MagicMock()
    compact_attempts = 0
    visible_attempts = 0

    def completion_side_effect(*, messages: list[dict[str, str]], **_: object):
        nonlocal compact_attempts, visible_attempts
        last_user = messages[-1]["content"]
        mock_choice = MagicMock()
        if "只返回一个可见中文短句：provider ready。" in last_user:
            compact_attempts += 1
            mock_choice.message.content = "" if compact_attempts == 1 else "provider ready。"
        elif "请只输出可见文字：provider ready。" in last_user:
            visible_attempts += 1
            mock_choice.message.content = ""
        else:
            mock_choice.message.content = _provider_test_reply_for_prompt(last_user, "pong")
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    fake_client.chat.completions.create.side_effect = completion_side_effect

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test", response_language="zh-CN")

    assert result.ok is True
    assert compact_attempts >= 2
    assert visible_attempts >= 1
    assert any("retried the compact chat probe" in item.lower() for item in result.diagnostics)


def test_provider_test_keeps_a_trusted_visible_reply_when_language_probe_is_inconclusive() -> None:
    config = ProviderConfig(
        name="minimax-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
    )
    service = ProviderService()
    fake_client = MagicMock()

    def completion_side_effect(*, messages: list[dict[str, str]], **_: object):
        last_user = messages[-1]["content"]
        mock_choice = MagicMock()
        if "Reply with exactly: pong" in last_user:
            mock_choice.message.content = "pong"
        else:
            mock_choice.message.content = "边界判断最小教学步骤"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    fake_client.chat.completions.create.side_effect = completion_side_effect

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test", response_language="zh-CN")

    assert result.ok is True
    assert result.error_category is None
    assert result.provider_reachable is True
    assert result.model_supported is True
    assert "可用的可见回复" in (result.detail or "")
    assert any("not blocking this connection" in item for item in result.diagnostics)


def test_provider_test_uses_message_derived_probe_for_real_coach_message() -> None:
    config = ProviderConfig(
        name="minimax-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
    )
    service = ProviderService()
    fake_client = MagicMock()
    coach_message = (
        "请先解释 VS Code remote workspace boundary"
        "然后只给我一?tiny verification step ABC123"
    )

    def completion_side_effect(*, messages: list[dict[str, str]], **_: object):
        last_user = messages[-1]["content"]
        mock_choice = MagicMock()
        if "Reply with exactly: pong" in last_user:
            mock_choice.message.content = "pong"
        elif (
            last_user.startswith("Repeat exactly:")
            and "remote workspace" in last_user
            and "ABC123" in last_user
        ):
            mock_choice.message.content = "I only saw question marks: ????? ABC123"
        else:
            mock_choice.message.content = _provider_test_reply_for_prompt(last_user, "pong")
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    fake_client.chat.completions.create.side_effect = completion_side_effect

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        baseline = service.test(config, "sk-test")
        result = service.test(
            config,
            "sk-test",
            probe_message=coach_message,
            response_language="zh-CN",
        )

    assert baseline.ok is True
    assert result.ok is False
    assert result.error_category == "language_corruption"
    assert any(
        "remote workspace" in kwargs["messages"][-1]["content"]
        and "ABC123" in kwargs["messages"][-1]["content"]
        for _, kwargs in fake_client.chat.completions.create.call_args_list
        if isinstance(kwargs.get("messages"), list)
    )


def test_provider_test_skips_cjk_probe_for_english_only_flow() -> None:
    config = ProviderConfig(
        name="minimax-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
    )
    service = ProviderService()
    fake_client = MagicMock()

    def completion_side_effect(*, messages: list[dict[str, str]], **_: object):
        _ = messages[-1]["content"]
        mock_choice = MagicMock()
        mock_choice.message.content = "pong"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    fake_client.chat.completions.create.side_effect = completion_side_effect

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test", response_language="en-US")

    assert result.ok is True
    prompts = [
        kwargs["messages"][-1]["content"]
        for _, kwargs in fake_client.chat.completions.create.call_args_list
        if isinstance(kwargs.get("messages"), list)
    ]
    connectivity_prompts = [
        prompt
        for prompt in prompts
        if "trainer_capability_probe" not in prompt and "THINKING_OK" not in prompt
    ]
    assert connectivity_prompts == ["Reply with exactly: pong"]
    assert all("只返回" not in prompt and "请只输出" not in prompt for prompt in prompts)
    assert any("Language integrity probe skipped for this English-only flow." in item for item in result.diagnostics)


def test_provider_test_uses_native_anthropic_messages_probe() -> None:
    config = ProviderConfig(
        name="minimax-anthropic",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="anthropic_messages",
        request_defaults={
            "thinkingBudget": 2048,
            "extra_body": {
                "gateway_option": "keep-me",
            },
        },
    )
    service = ProviderService()

    class _Response:
        status_code = 200
        text = '{"content":[{"type":"text","text":"pong"}]}'

        def json(self) -> dict[str, object]:
            return {"content": [{"type": "text", "text": "pong"}]}

    mock_client = MagicMock()
    mock_client.post.return_value = _Response()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with patch("app.llm.provider_service.httpx.Client", return_value=mock_cm):
        result = service.test(config, "sk-test", response_language="en-US")

    assert result.ok is True
    assert result.provider_reachable is True
    assert any("native anthropic_messages" in item for item in result.diagnostics)
    _, kwargs = mock_client.post.call_args
    assert kwargs["headers"]["x-api-key"] == "sk-test"
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"
    assert kwargs["json"]["model"] == "MiniMax-M3"
    assert kwargs["json"]["thinking"] == {"type": "disabled"}
    assert kwargs["json"]["gateway_option"] == "keep-me"
    assert "thinkingBudget" not in kwargs["json"]


@pytest.mark.parametrize(
    ("protocol", "base_url"),
    [
        ("anthropic_messages", "http://anthropic.example"),
        ("gemini_generate_content", "https://generativelanguage.googleapis.com/v1beta"),
    ],
)
def test_native_http_502_is_retryable_network_failure(
    protocol: str,
    base_url: str,
) -> None:
    config = ProviderConfig(
        name=f"{protocol}-gateway",
        base_url=base_url,
        api_key_ref="trainer.native",
        model="demo-model",
        protocol=protocol,
        capabilities={
            "chat": True,
            "responses": False,
            "vision": False,
            "embeddings": False,
            "tools": False,
            "json_schema": False,
            "structured_output": False,
            "streaming": False,
            "thinking": False,
        },
    )
    service = ProviderService()

    class _Response:
        status_code = 502
        text = "bad gateway"

        def json(self) -> dict[str, object]:
            return {"error": "bad gateway"}

    mock_client = MagicMock()
    mock_client.post.return_value = _Response()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with patch("app.llm.provider_service.httpx.Client", return_value=mock_cm):
        result = service.test(config, "sk-test", response_language="en-US")

    assert result.ok is False
    assert result.error_category == "network"
    assert result.retryable is True
    assert result.status_code == 502
    assert result.provider_reachable is False
    assert result.model_supported is None


@pytest.mark.parametrize(
    "error, expected_category",
    [
        (httpx.ConnectTimeout("simulated connect timeout"), "timeout"),
        (httpx.ReadTimeout("simulated read timeout"), "timeout"),
        (httpx.WriteTimeout("simulated write timeout"), "timeout"),
        (httpx.PoolTimeout("simulated pool timeout"), "timeout"),
        (httpx.ConnectError("simulated connect error"), "network"),
        (httpx.ReadError("simulated read error"), "network"),
        (httpx.WriteError("simulated write error"), "network"),
    ],
)
def test_classify_httpx_transport_errors_as_retryable(
    error: Exception,
    expected_category: str,
) -> None:
    category, retryable, status_code, provider_reachable, model_supported = ProviderService()._classify_error(
        error
    )

    assert category == expected_category
    assert retryable is True
    assert status_code is None
    assert provider_reachable is False
    assert model_supported is None


def test_provider_test_retries_native_anthropic_empty_probe_once() -> None:
    config = ProviderConfig(
        name="minimax-anthropic",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="anthropic_messages",
    )
    service = ProviderService()

    class _Response:
        status_code = 200
        text = "{}"

        def __init__(self, text: str) -> None:
            self._text = text

        def json(self) -> dict[str, object]:
            return {"content": [{"type": "text", "text": self._text}]}

    mock_client = MagicMock()
    mock_client.post.side_effect = [_Response(""), _Response("pong")]
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with patch("app.llm.provider_service.httpx.Client", return_value=mock_cm):
        result = service.test(config, "sk-test", response_language="en-US")

    assert result.ok is True
    assert mock_client.post.call_count == 2
    prompts = [call.kwargs["json"]["messages"][0]["content"] for call in mock_client.post.call_args_list]
    assert prompts == [
        "Reply with exactly: pong",
        (
            "Return one short visible sentence only: provider ready. "
            "Do not return only reasoning, tool calls, or hidden text."
        ),
    ]
    assert any("empty first attempt" in item.lower() for item in result.diagnostics)


def test_provider_test_classifies_native_anthropic_thinking_only_reply_without_leaking_it() -> None:
    config = ProviderConfig(
        name="minimax-anthropic",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="anthropic_messages",
    )
    service = ProviderService()

    class _Response:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, object]:
            return {"content": [{"type": "thinking", "thinking": "private chain of thought"}]}

    mock_client = MagicMock()
    mock_client.post.return_value = _Response()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with patch("app.llm.provider_service.httpx.Client", return_value=mock_cm):
        result = service.test(config, "sk-test", response_language="en-US")

    assert result.ok is False
    assert result.error_category == "reasoning_leak"
    assert result.provider_reachable is True
    assert result.model_supported is True
    assert "private chain of thought" not in (result.detail or "")
    assert all("private chain of thought" not in item for item in result.diagnostics)


def test_provider_test_recovers_native_anthropic_blank_visible_probe_via_language_probe() -> None:
    config = ProviderConfig(
        name="minimax-anthropic",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="anthropic_messages",
    )
    service = ProviderService()

    class _Response:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, object]:
            return {"content": [{"type": "text", "text": ""}]}

    mock_client = MagicMock()
    mock_client.post.side_effect = [_Response(), _Response()]
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with (
        patch("app.llm.provider_service.httpx.Client", return_value=mock_cm),
        patch.object(
            service,
            "_native_protocol_language_probe_result_resilient",
            return_value={
                "ok": True,
                "detail": (
                    "Language integrity probe preserved the message-derived and mixed "
                    "CJK/ASCII probe text across all checks."
                ),
                "preview": "不要直接考试，先学再测。请判断 VS Code 远程工作区边界。ABC123",
                "kind": "strict_integrity",
            },
        ),
    ):
        result = service.test(
            config,
            "sk-test",
            probe_message="请先解释 remote workspace boundary，再给我一个 tiny verification step ABC123。",
            response_language="zh-CN",
        )

    assert result.ok is True
    assert mock_client.post.call_count == 2
    assert any("language integrity probe recovered usable visible text" in item.lower() for item in result.diagnostics)
    assert "MiniMax-M3" in (result.detail or "")


def test_provider_test_threads_anthropic_probe_request_defaults() -> None:
    config = ProviderConfig(
        name="minimax-anthropic",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="anthropic_messages",
        request_defaults={"extra_body": {"thinking": {"type": "disabled"}}},
    )
    service = ProviderService()

    class _Response:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, object]:
            return {"content": [{"type": "text", "text": "provider ready"}]}

    mock_client = MagicMock()
    mock_client.post.return_value = _Response()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with patch("app.llm.provider_service.httpx.Client", return_value=mock_cm):
        result = service.test(config, "sk-test", response_language="en-US")

    assert result.ok is True
    _, kwargs = mock_client.post.call_args
    payload = kwargs["json"]
    assert payload["thinking"] == {"type": "disabled"}
    assert "visible text" in payload["system"]


def test_provider_test_native_anthropic_probe_catches_language_corruption() -> None:
    config = ProviderConfig(
        name="minimax-anthropic",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="anthropic_messages",
    )
    service = ProviderService()

    class _Response:
        status_code = 200

        def __init__(self, text: str) -> None:
            self.text = text
            self._text = text

        def json(self) -> dict[str, object]:
            return {"content": [{"type": "text", "text": self._text}]}

    mock_client = MagicMock()
    mock_client.post.side_effect = [
        _Response("provider ready。"),
        _Response("我只看到了 question marks: ????? ABC123"),
    ]
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with patch("app.llm.provider_service.httpx.Client", return_value=mock_cm):
        result = service.test(
            config,
            "sk-test",
            probe_message="请先解释 remote workspace boundary，再给我一个 tiny verification step ABC123。",
            response_language="zh-CN",
        )

    assert result.ok is False
    assert result.error_category == "language_corruption"
    assert result.provider_reachable is True
    assert result.model_supported is True
    assert "问号" in (result.detail or "")
    assert any("Language integrity probe failed" in item for item in result.diagnostics)
    assert any("question marks" in item for item in result.diagnostics)


def test_provider_test_native_probe_keeps_visible_reply_when_optional_language_probe_is_inconclusive() -> None:
    config = ProviderConfig(
        name="minimax-anthropic",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="anthropic_messages",
    )
    service = ProviderService()

    class _Response:
        status_code = 200
        text = '{"content":[{"type":"text","text":"provider ready。"}]}'

        def json(self) -> dict[str, object]:
            return {"content": [{"type": "text", "text": "provider ready。"}]}

    mock_client = MagicMock()
    mock_client.post.return_value = _Response()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with (
        patch("app.llm.provider_service.httpx.Client", return_value=mock_cm),
        patch.object(
            service,
            "_native_protocol_language_probe_result_resilient",
            return_value={
                "ok": False,
                "category": "language_probe_inconclusive",
                "detail": "Strict echo probe was not preserved exactly.",
                "preview": "正常中文回复。",
            },
        ),
    ):
        result = service.test(config, "sk-test", response_language="zh-CN")

    assert result.ok is True
    assert result.error_category is None
    assert result.provider_reachable is True
    assert result.model_supported is True
    assert "可用的可见回复" in (result.detail or "")
    assert any("not blocking this connection" in item for item in result.diagnostics)


def test_provider_test_native_anthropic_requires_every_language_probe_to_pass() -> None:
    config = ProviderConfig(
        name="minimax-anthropic",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="anthropic_messages",
    )
    service = ProviderService()
    coach_message = "请先解释 remote workspace boundary，再给我一个 tiny verification step ABC123。"

    class _Response:
        status_code = 200

        def __init__(self, text: str) -> None:
            self.text = text
            self._text = text

        def json(self) -> dict[str, object]:
            return {"content": [{"type": "text", "text": self._text}]}

    mock_client = MagicMock()
    mock_client.post.side_effect = [
        _Response("provider ready。"),
        _Response(coach_message),
        _Response("I only saw question marks: ????? ABC123"),
    ]
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with patch("app.llm.provider_service.httpx.Client", return_value=mock_cm):
        result = service.test(
            config,
            "sk-test",
            probe_message=coach_message,
            response_language="zh-CN",
        )

    assert result.ok is False
    assert result.error_category == "language_corruption"
    assert mock_client.post.call_count == 3


def test_provider_test_uses_native_openai_responses_probe() -> None:
    config = ProviderConfig(
        name="openai-responses",
        base_url="https://api.openai.com/v1",
        api_key_ref="trainer.openai",
        model="gpt-5.1-mini",
        protocol="openai_responses",
    )
    service = ProviderService()
    fake_client = MagicMock()
    fake_client.responses.create.return_value = SimpleNamespace(output_text="pong")

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test", response_language="en-US")

    assert result.ok is True
    assert any("native openai_responses" in item for item in result.diagnostics)
    _, kwargs = fake_client.responses.create.call_args
    assert kwargs["model"] == "gpt-5.1-mini"
    assert kwargs["input"] == "Reply with exactly: pong"


def test_provider_test_classifies_missing_responses_endpoint_as_protocol_mismatch() -> None:
    config = ProviderConfig(
        name="openai-responses",
        base_url="https://gateway.example.com/v1",
        api_key_ref="trainer.gateway",
        model="MiniMax-M3",
        protocol="openai_responses",
    )
    service = ProviderService()
    fake_client = MagicMock()
    fake_client.responses.create.side_effect = Exception(
        "Error code: 404 - {'error': {'message': 'Invalid URL (POST /v1/responses)', "
        "'type': 'invalid_request_error', 'param': '', 'code': ''}}"
    )

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test", response_language="en-US")

    assert result.ok is False
    assert result.error_category == "malformed_response"
    assert result.provider_reachable is True
    assert result.status_code == 404
    assert "unexpected or malformed payload" in (result.detail or "")


def test_provider_test_uses_native_gemini_generate_content_probe() -> None:
    config = ProviderConfig(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_ref="trainer.gemini",
        model="gemini-2.0-flash",
        protocol="gemini_generate_content",
    )
    service = ProviderService()

    class _Response:
        status_code = 200
        text = '{"candidates":[{"content":{"parts":[{"text":"pong"}]}}]}'

        def json(self) -> dict[str, object]:
            return {"candidates": [{"content": {"parts": [{"text": "pong"}]}}]}

    mock_client = MagicMock()
    mock_client.post.return_value = _Response()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with patch("app.llm.provider_service.httpx.Client", return_value=mock_cm):
        result = service.test(config, "sk-test", response_language="en-US")

    assert result.ok is True
    assert any("native gemini_generate_content" in item for item in result.diagnostics)
    endpoint, kwargs = mock_client.post.call_args.args[0], mock_client.post.call_args.kwargs
    assert endpoint.endswith("/models/gemini-2.0-flash:generateContent")
    assert kwargs["headers"]["x-goog-api-key"] == "sk-test"
    assert kwargs["json"]["contents"][0]["parts"][0]["text"] == "Reply with exactly: pong"


def test_provider_test_falls_back_for_gemini_compatible_gateway() -> None:
    config = ProviderConfig(
        name="minimax-gemini-compatible",
        base_url="https://gateway.example.com/v1",
        api_key_ref="trainer.gateway",
        model="MiniMax-M3",
        protocol="gemini_generate_content",
    )
    service = ProviderService()
    fake_client = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = "provider ready"
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_client.chat.completions.create.return_value = fake_response

    with (
        patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)),
        patch("app.llm.provider_service.httpx.Client", side_effect=AssertionError("native Gemini should not be used")),
    ):
        result = service.test(config, "sk-test", response_language="en-US")

    assert result.ok is True
    assert any("OpenAI-compatible chat probe" in item for item in result.diagnostics)
    _, kwargs = fake_client.chat.completions.create.call_args
    assert kwargs["model"] == "MiniMax-M3"


def test_provider_test_appends_v1_for_non_google_gemini_gateway_without_version_path() -> None:
    config = ProviderConfig(
        name="minimax-gemini-compatible",
        base_url="https://gateway.example.com",
        api_key_ref="trainer.gateway",
        model="MiniMax-M3",
        protocol="gemini_generate_content",
    )
    service = ProviderService()
    fake_client = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = "provider ready"
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_client.chat.completions.create.return_value = fake_response
    captured: dict[str, object] = {}

    def _fake_openai_ctor(
        *,
        api_key: str,
        base_url: str | None,
        timeout: float,
        max_retries: int,
    ) -> object:
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        captured["timeout"] = timeout
        captured["max_retries"] = max_retries
        return fake_client

    with (
        patch.object(service, "_get_sync_openai_class", return_value=_fake_openai_ctor),
        patch.object(
            service,
            "_language_probe_result_resilient",
            return_value={"ok": True, "detail": "Language probe preserved zh-CN input."},
        ),
        patch("app.llm.provider_service.httpx.Client", side_effect=AssertionError("native Gemini should not be used")),
    ):
        result = service.test(config, "sk-test", response_language="zh-CN")

    assert result.ok is True
    assert captured["api_key"] == "sk-test"
    assert captured["base_url"] == "https://gateway.example.com/v1"
    assert captured["timeout"] == DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS
    assert captured["max_retries"] == DEFAULT_OPENAI_CLIENT_MAX_RETRIES


def test_provider_test_falls_back_to_lowercase_model_candidate() -> None:
    config = ProviderConfig(
        name="mimo-provider",
        base_url="https://example.com/v1",
        api_key_ref="trainer.mimo",
        model="MiMo-V2.5",
    )
    service = ProviderService()
    fake_client = MagicMock()

    def completion_side_effect(*, model: str, messages: list[dict[str, str]], **_: object):
        if model == "MiMo-V2.5":
            raise Exception("Error code: 400 - {'error': {'message': 'Not supported model MiMo-V2.5'}}")
        last_user = messages[-1]["content"]
        mock_choice = MagicMock()
        mock_choice.message.content = _provider_test_reply_for_prompt(last_user, "pong")
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    fake_client.chat.completions.create.side_effect = completion_side_effect

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test")

    assert result.ok is True
    assert result.detail is not None
    assert "mimo-v2.5" in result.detail


@pytest.mark.asyncio
async def test_coaching_reply_applies_request_defaults_before_sending() -> None:
    config = ProviderConfig(
        name="minimax-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        request_defaults={
            "extra_body": {
                "thinking": {
                    "type": "disabled"
                }
            }
        },
    )
    service = ProviderService(config=config, api_key="sk-test")
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = "Hello from the coach"
    fake_response.choices = [fake_choice]
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch.object(service, "_get_client", return_value=fake_client):
        reply = await service.coaching_reply(_make_profile(), "Explain the next step.")

    assert "Hello from the coach" in reply
    _, kwargs = fake_client.chat.completions.create.call_args
    assert kwargs["extra_body"]["thinking"]["type"] == "disabled"


@pytest.mark.asyncio
async def test_chat_request_defaults_are_protocol_safe() -> None:
    config = ProviderConfig(
        name="minimax-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="openai_chat_completions_compatible",
        request_defaults={
            "extra_body": {"thinking": {"type": "disabled"}},
            "maxOutputTokens": 2048,
            "maxTokens": 1024,
            "reasoningEffort": "auto",
            "serviceTier": "auto",
            "generationConfig": {"maxOutputTokens": 2048},
            "thinkingBudget": "auto",
            "promptCache": "auto",
        },
    )
    service = ProviderService(config=config, api_key="sk-test")
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = "Hello from the coach"
    fake_response.choices = [fake_choice]
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch.object(service, "_get_client", return_value=fake_client):
        reply = await service.coaching_reply(_make_profile(), "Explain the next step.")

    assert "Hello from the coach" in reply
    _, kwargs = fake_client.chat.completions.create.call_args
    assert kwargs["max_tokens"] == 1024
    assert kwargs["extra_body"]["thinking"]["type"] == "disabled"
    assert "maxOutputTokens" not in kwargs
    assert "maxTokens" not in kwargs
    assert "generationConfig" not in kwargs
    assert "thinkingBudget" not in kwargs
    assert "promptCache" not in kwargs
    assert "reasoningEffort" not in kwargs
    assert "serviceTier" not in kwargs
    assert "reasoning_effort" not in kwargs
    assert "service_tier" not in kwargs


@pytest.mark.asyncio
async def test_non_agent_coaching_reply_dispatches_to_configured_native_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ProviderConfig(
        name="anthropic-compatible",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.anthropic",
        model="MiniMax-M3",
        protocol="anthropic_messages",
    )
    service = ProviderService(config=config, api_key="sk-test")
    captured: dict[str, object] = {}

    async def _fake_call(
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        captured["messages"] = messages
        captured["tools"] = tools
        return {
            "content": "Anthropic plain reply: learn the boundary, then verify one path.",
            "tool_calls": [],
        }

    fake_provider = SimpleNamespace(
        protocol="anthropic_messages",
        call=_fake_call,
        call_stream=None,
    )

    def _fake_build_agent_provider(self: ProviderService, **kwargs: object) -> tuple[object, object]:
        captured["binding_kwargs"] = kwargs
        return fake_provider, fake_provider

    monkeypatch.setattr(
        "app.llm.provider_service.ProviderService.build_agent_provider",
        _fake_build_agent_provider,
    )
    monkeypatch.setattr(
        service,
        "_get_client",
        MagicMock(side_effect=AssertionError("OpenAI chat client should not be used")),
    )

    reply = await service.coaching_reply(
        _make_profile(),
        "Continue the current VS Code remote lesson from the last verified step.",
        response_language="en-US",
    )

    assert "Anthropic plain reply" in reply
    assert captured["tools"] is None
    assert captured["binding_kwargs"] == {
        "protocol": "anthropic_messages",
        "temperature": 0.7,
        "max_tokens": 1024,
    }


@pytest.mark.asyncio
async def test_non_google_anthropic_gateway_falls_back_when_native_reply_is_html_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ProviderConfig(
        name="anthropic-compatible",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.anthropic",
        model="MiniMax-M3",
        protocol="anthropic_messages",
    )
    service = ProviderService(config=config, api_key="sk-test")

    class _AnthropicHtmlResponse:
        status_code = 200
        text = "<!doctype html><html><head><title>New API</title></head><body><div id='root'></div></body></html>"

        def json(self) -> dict[str, object]:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": self.text,
                    }
                ]
            }

    fake_choice = MagicMock()
    fake_choice.message.content = "\u5df2\u901a\u8fc7 OpenAI-compatible fallback \u6062\u590d\u53ef\u89c1\u4e2d\u6587\u6559\u7ec3\u56de\u590d\u3002"
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    async def _fake_anthropic_post_payload(self: object, payload: dict[str, object], api_key: str) -> object:
        return _AnthropicHtmlResponse()

    monkeypatch.setattr(
        "app.llm.agent_binding.ProviderAgentBinding._anthropic_post_payload",
        _fake_anthropic_post_payload,
    )

    with patch.object(service, "_get_client", return_value=fake_client):
        reply = await service.coaching_reply(
            _make_profile(),
            "Continue this lesson in Chinese.",
            response_language="zh-CN",
        )

    assert "OpenAI-compatible fallback" in reply
    assert any("\u3400" <= character <= "\u9fff" for character in reply)


@pytest.mark.asyncio
async def test_non_agent_coaching_stream_dispatches_to_configured_native_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ProviderConfig(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_ref="trainer.gemini",
        model="gemini-2.0-flash",
        protocol="gemini_generate_content",
    )
    service = ProviderService(config=config, api_key="sk-test")
    captured: dict[str, object] = {}

    async def _fake_stream(
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
    ):
        captured["messages"] = messages
        captured["tools"] = tools
        yield {"type": "delta", "delta": "Gemini plain stream "}
        yield {"type": "delta", "delta": "reply."}
        yield {"type": "final", "content": "Gemini plain stream reply.", "tool_calls": []}

    fake_provider = SimpleNamespace(
        protocol="gemini_generate_content",
        call=None,
        call_stream=_fake_stream,
    )

    def _fake_build_agent_provider(self: ProviderService, **kwargs: object) -> tuple[object, object]:
        captured["binding_kwargs"] = kwargs
        return fake_provider, fake_provider

    monkeypatch.setattr(
        "app.llm.provider_service.ProviderService.build_agent_provider",
        _fake_build_agent_provider,
    )
    monkeypatch.setattr(
        service,
        "_get_client",
        MagicMock(side_effect=AssertionError("OpenAI chat client should not be used")),
    )

    chunks = [
        chunk
        async for chunk in service.coaching_reply_stream(
            _make_profile(),
            "Continue the current function guidance card from the last verified call site.",
            response_language="en-US",
        )
    ]

    assert "".join(chunks) == "Gemini plain stream reply."
    assert captured["tools"] is None
    assert captured["binding_kwargs"] == {
        "protocol": "gemini_generate_content",
        "temperature": 0.7,
        "max_tokens": 1024,
    }


@pytest.mark.asyncio
async def test_agentic_stream_rejects_buffered_provider_without_fake_incremental_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")

    async def _fake_call(
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {
            "content": "This reply arrives as one buffered completion. " * 20,
            "tool_calls": [],
        }

    fake_provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_fake_call,
        call_stream=None,
    )
    monkeypatch.setattr(
        service,
        "_build_agent_provider_with_budget",
        lambda **_: (fake_provider, fake_provider),
    )

    events = [
        event
        async for event in service.coaching_reply_agentic_stream(
            _make_profile(),
            "Continue the current lesson.",
            response_language="en-US",
        )
    ]

    degraded = next(event for event in events if event.get("type") == "error")
    assert degraded["category"] == "streaming_unavailable"
    assert degraded["recoverable"] is True
    assert degraded["terminal"] is True
    assert degraded["degraded"] is False
    final = next(event for event in events if event.get("type") == "final")
    assert final["stop_reason"] == "streaming_unavailable"
    assert final["fell_back"] is False
    assert "native streaming" in str(final["content"])
    assert not any(event.get("type") == "text" for event in events)


@pytest.mark.asyncio
async def test_agent_binding_preserves_openai_compatible_request_defaults() -> None:
    from app.llm.agent_binding import ProviderAgentBinding

    config = ProviderConfig(
        name="minimax-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="openai_chat_completions_compatible",
        request_defaults={
            "extra_body": {
                "thinking": {
                    "type": "disabled",
                }
            },
            "maxOutputTokens": 2048,
            "generationConfig": {"maxOutputTokens": 2048},
            "thinkingBudget": "auto",
            "promptCache": "auto",
        },
    )
    service = ProviderService(config=config, api_key="sk-test")
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = "Compatible provider reply"
    fake_response.choices = [fake_choice]
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    binding = ProviderAgentBinding(
        provider_service=service,
        protocol="openai_chat_completions_compatible",
        temperature=0.2,
        max_tokens=321,
    )

    with patch.object(service, "_get_client", return_value=fake_client):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "hello"}],
            None,
        )

    assert result["content"] == "Compatible provider reply"
    _, kwargs = fake_client.chat.completions.create.call_args
    assert kwargs["model"] == "MiniMax-M3"
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 2048
    assert kwargs["extra_body"]["thinking"]["type"] == "disabled"
    assert "maxOutputTokens" not in kwargs
    assert "generationConfig" not in kwargs
    assert "thinkingBudget" not in kwargs
    assert "promptCache" not in kwargs


@pytest.mark.asyncio
async def test_minimax_direct_sidecar_config_forces_visible_reply_wire_defaults() -> None:
    """The API path must not depend on the webview to inject MiniMax defaults."""
    from openai import AsyncOpenAI

    config = ProviderConfig(
        name="custom-minimax-gateway",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="openai_chat_completions_compatible",
        request_defaults={
            "max_tokens": 256,
            "thinking": {"type": "enabled"},
            "extra_body": {
                "thinking": {"type": "enabled"},
                "gateway_option": "keep-me",
            },
        },
    )
    service = ProviderService(config=config, api_key="test-only")
    request_payload = service._apply_request_defaults(  # noqa: SLF001
        {
            "model": config.model,
            "messages": [{"role": "user", "content": "Explain one step."}],
            "max_tokens": 1024,
        }
    )
    captured: dict[str, object] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": config.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as http_client:
        client = AsyncOpenAI(
            api_key="test-only",
            base_url="http://gateway.example/v1",
            http_client=http_client,
        )
        await client.chat.completions.create(**request_payload)

    assert request_payload["max_tokens"] == 256
    assert request_payload["extra_body"] == {
        "thinking": {"type": "disabled"},
        "gateway_option": "keep-me",
    }
    assert captured["max_tokens"] == 256
    assert captured["thinking"] == {"type": "disabled"}
    assert captured["gateway_option"] == "keep-me"
    assert "extra_body" not in captured


@pytest.mark.asyncio
async def test_nonofficial_anthropic_agent_binding_forces_thinking_disabled() -> None:
    from app.llm.agent_binding import ProviderAgentBinding

    config = ProviderConfig(
        name="minimax-anthropic",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="anthropic_messages",
        request_defaults={
            "thinkingBudget": 2048,
            "extra_body": {
                "gateway_option": "keep-me",
            },
        },
    )
    service = ProviderService(config=config, api_key="sk-test")
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    payload = binding._apply_anthropic_request_defaults(  # noqa: SLF001
        {
            "model": config.model,
            "messages": [{"role": "user", "content": "Explain one step."}],
            "max_tokens": 256,
        }
    )
    payload = binding._apply_nonofficial_anthropic_thinking_default(payload)  # noqa: SLF001

    assert binding._should_default_compatibility_thinking() is True  # noqa: SLF001
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["gateway_option"] == "keep-me"


@pytest.mark.asyncio
async def test_openai_responses_binding_maps_safe_request_defaults() -> None:
    from app.llm.agent_binding import ProviderAgentBinding

    config = ProviderConfig(
        name="openai-responses",
        base_url="https://api.openai.com/v1",
        api_key_ref="trainer.openai",
        model="gpt-5.1-mini",
        protocol="openai_responses",
        request_defaults={
            "store": False,
            "reasoningEffort": "medium",
            "serviceTier": "auto",
            "maxOutputTokens": 456,
        },
    )
    service = ProviderService(config=config, api_key="sk-test")
    fake_client = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=SimpleNamespace(output_text="pong", output=[]))
    binding = ProviderAgentBinding(provider_service=service, protocol="openai_responses")

    with patch.object(service, "_get_client", return_value=fake_client):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "hello"}],
            None,
        )

    assert result["content"] == "pong"
    _, kwargs = fake_client.responses.create.call_args
    assert kwargs["model"] == "gpt-5.1-mini"
    assert kwargs["store"] is False
    assert kwargs["service_tier"] == "auto"
    assert kwargs["reasoning"] == {"effort": "medium"}
    assert kwargs["max_output_tokens"] == 456


@pytest.mark.asyncio
async def test_openai_responses_binding_sends_verified_images_without_changing_tools() -> None:
    from app.core.models import CapabilityFlags
    from app.llm.agent_binding import ProviderAgentBinding

    config = ProviderConfig(
        name="openai-responses-vision",
        base_url="https://api.openai.com/v1",
        api_key_ref="trainer.openai",
        model="gpt-4.1-mini",
        protocol="openai_responses",
        capabilities=CapabilityFlags(responses=True, vision=True, tools=True),
    )
    service = ProviderService(config=config, api_key="sk-test")
    service._capability_truth["vision"] = "verified"
    fake_client = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=SimpleNamespace(output_text="seen", output=[]))
    binding = ProviderAgentBinding(
        provider_service=service,
        protocol="openai_responses",
        attachments=[{"kind": "image", "mime_type": "image/png", "data_base64": "QUFBQQ=="}],
    )
    tools = [{"type": "function", "name": "search_resources", "parameters": {"type": "object"}}]

    with patch.object(service, "_get_client", return_value=fake_client):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "inspect this"}],
            tools,
        )

    assert result["content"] == "seen"
    kwargs = fake_client.responses.create.call_args.kwargs
    assert kwargs["tools"] == tools
    assert kwargs["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "inspect this"},
                {"type": "input_image", "image_url": "data:image/png;base64,QUFBQQ=="},
            ],
        }
    ]


def test_provider_list_models_returns_sorted_models_and_resolves_alias() -> None:
    config = ProviderConfig(
        name="mimo-provider",
        base_url="https://example.com/v1",
        api_key_ref="trainer.mimo",
        model="MiMo-V2.5",
    )
    service = ProviderService()
    fake_client = MagicMock()
    fake_client.models.list.return_value = [
        MagicMock(id="mimo-v2.5-pro"),
        MagicMock(id="mimo-v2.5"),
        MagicMock(id="mimo-v2-omni"),
    ]

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.list_models(config, "sk-test")

    assert result.ok is True
    assert result.listed is True
    assert result.available_models == ["mimo-v2-omni", "mimo-v2.5", "mimo-v2.5-pro"]
    assert result.resolved_model == "mimo-v2.5"
    assert result.resolved_from_input is True


def test_provider_list_models_uses_native_anthropic_models_endpoint() -> None:
    config = ProviderConfig(
        name="anthropic",
        base_url="https://api.anthropic.com",
        api_key_ref="trainer.anthropic",
        model="claude-sonnet-4-20250514",
        protocol="anthropic_messages",
    )
    service = ProviderService()

    class _Response:
        status_code = 200
        text = '{"data":[{"id":"claude-sonnet-4-20250514"},{"id":"claude-haiku-4-5-20250514"}]}'

        def json(self) -> dict[str, object]:
            return {
                "data": [
                    {"id": "claude-sonnet-4-20250514"},
                    {"id": "claude-haiku-4-5-20250514"},
                ]
            }

    mock_client = MagicMock()
    mock_client.get.return_value = _Response()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with (
        patch("app.llm.provider_service.httpx.Client", return_value=mock_cm),
        patch.object(
            service,
            "_create_sync_client",
            MagicMock(side_effect=AssertionError("OpenAI models.list should not be used")),
        ),
    ):
        result = service.list_models(config, "sk-test")

    assert result.ok is True
    assert result.available_models == ["claude-haiku-4-5-20250514", "claude-sonnet-4-20250514"]
    assert result.resolved_model == "claude-sonnet-4-20250514"
    endpoint, kwargs = mock_client.get.call_args.args[0], mock_client.get.call_args.kwargs
    assert endpoint == "https://api.anthropic.com/v1/models"
    assert kwargs["headers"]["x-api-key"] == "sk-test"
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"


def test_provider_list_models_falls_back_to_openai_for_compatible_anthropic_gateway() -> None:
    config = ProviderConfig(
        name="minimax-anthropic-gateway",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="anthropic_messages",
    )
    service = ProviderService()

    class _NativeResponse:
        status_code = 404
        text = '{"error":{"message":"not found"}}'

    native_client = MagicMock()
    native_client.get.return_value = _NativeResponse()
    native_cm = MagicMock()
    native_cm.__enter__.return_value = native_client
    native_cm.__exit__.return_value = False

    compatible_client = MagicMock()
    compatible_client.models.list.return_value = [
        MagicMock(id="MiniMax-M2.7-highspeed"),
        MagicMock(id="MiniMax-M3"),
    ]

    with (
        patch("app.llm.provider_service.httpx.Client", return_value=native_cm),
        patch.object(
            service,
            "_get_sync_openai_class",
            return_value=MagicMock(return_value=compatible_client),
        ),
    ):
        result = service.list_models(config, "sk-test")

    assert result.ok is True
    assert result.listed is True
    assert result.available_models == ["MiniMax-M2.7-highspeed", "MiniMax-M3"]
    assert result.resolved_model == "MiniMax-M3"
    assert compatible_client.models.list.call_count == 1
    assert any("OpenAI-compatible /models" in item for item in result.diagnostics)


def test_provider_list_models_does_not_mark_an_empty_native_response_as_listed() -> None:
    config = ProviderConfig(
        name="anthropic-compatible",
        base_url="https://gateway.example.com",
        api_key_ref="trainer.gateway",
        model="MiniMax-M3",
        protocol="anthropic_messages",
    )
    service = ProviderService()

    class _Response:
        status_code = 200
        text = '{"data":[]}'

        def json(self) -> dict[str, object]:
            return {"data": []}

    mock_client = MagicMock()
    mock_client.get.return_value = _Response()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with patch("app.llm.provider_service.httpx.Client", return_value=mock_cm):
        result = service.list_models(config, "sk-test")

    assert result.ok is False
    assert result.listed is False
    assert result.available_models == []
    assert result.resolved_model is None
    assert "did not return any visible models" in result.detail


def test_provider_list_models_uses_native_gemini_models_endpoint() -> None:
    config = ProviderConfig(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com",
        api_key_ref="trainer.gemini",
        model="gemini-2.0-flash",
        protocol="gemini_generate_content",
    )
    service = ProviderService()

    class _Response:
        status_code = 200
        text = (
            '{"models":[{"name":"models/gemini-2.0-flash","inputTokenLimit":1048576,'
            '"outputTokenLimit":8192},{"name":"models/gemini-2.0-flash-lite"}]}'
        )

        def json(self) -> dict[str, object]:
            return {
                "models": [
                    {
                        "name": "models/gemini-2.0-flash",
                        "inputTokenLimit": 1_048_576,
                        "outputTokenLimit": 8_192,
                    },
                    {"name": "models/gemini-2.0-flash-lite"},
                ]
            }

    mock_client = MagicMock()
    mock_client.get.return_value = _Response()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with (
        patch("app.llm.provider_service.httpx.Client", return_value=mock_cm),
        patch.object(
            service,
            "_create_sync_client",
            MagicMock(side_effect=AssertionError("OpenAI models.list should not be used")),
        ),
    ):
        result = service.list_models(config, "sk-test")

    assert result.ok is True
    assert result.available_models == ["gemini-2.0-flash", "gemini-2.0-flash-lite"]
    assert result.resolved_model == "gemini-2.0-flash"
    endpoint, kwargs = mock_client.get.call_args.args[0], mock_client.get.call_args.kwargs
    assert endpoint == "https://generativelanguage.googleapis.com/v1beta/models"
    assert kwargs["headers"]["x-goog-api-key"] == "sk-test"
    assert result.model_token_limits["gemini-2.0-flash"].context_window_tokens == 1_048_576
    assert result.model_token_limits["gemini-2.0-flash"].max_output_tokens == 8_192


def test_provider_list_models_extracts_openai_compatible_token_limits_when_exposed() -> None:
    config = ProviderConfig(
        name="minimax-gateway",
        base_url="https://gateway.example.com/v1",
        api_key_ref="trainer.gateway",
        model="MiniMax-M3",
    )
    service = ProviderService()

    class _ModelRecord:
        def __init__(self, model_id: str, **extra: object) -> None:
            self.id = model_id
            self.model_extra = extra

    fake_client = MagicMock()
    fake_client.models.list.return_value = [
        _ModelRecord(
            "MiniMax-M2.7-highspeed",
            context_window_tokens=1_048_576,
            max_output_tokens=16_384,
        ),
        _ModelRecord("MiniMax-M3"),
    ]

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.list_models(config, "sk-test")

    assert result.ok is True
    assert result.available_models == ["MiniMax-M2.7-highspeed", "MiniMax-M3"]
    assert result.model_token_limits["MiniMax-M2.7-highspeed"].context_window_tokens == 1_048_576
    assert result.model_token_limits["MiniMax-M2.7-highspeed"].max_output_tokens == 16_384
    assert "MiniMax-M3" not in result.model_token_limits


def test_provider_list_models_falls_back_for_gemini_compatible_gateway() -> None:
    config = ProviderConfig(
        name="minimax-gemini-compatible",
        base_url="https://gateway.example.com/v1",
        api_key_ref="trainer.gateway",
        model="MiniMax-M3",
        protocol="gemini_generate_content",
    )
    service = ProviderService()

    class _Response:
        status_code = 401
        text = '{"error":{"message":"Invalid token"}}'

    mock_client = MagicMock()
    mock_client.get.return_value = _Response()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    fake_openai_client = MagicMock()
    fake_openai_client.models.list.return_value = [
        MagicMock(id="MiniMax-M2.7-highspeed"),
        MagicMock(id="MiniMax-M3"),
    ]

    with (
        patch("app.llm.provider_service.httpx.Client", return_value=mock_cm),
        patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_openai_client)),
    ):
        result = service.list_models(config, "sk-test")

    assert result.ok is True
    assert result.available_models == ["MiniMax-M2.7-highspeed", "MiniMax-M3"]
    assert result.resolved_model == "MiniMax-M3"
    assert fake_openai_client.models.list.call_count == 1
    assert any("OpenAI-compatible /models" in item for item in result.diagnostics)


def test_provider_list_models_falls_back_when_gemini_gateway_returns_no_native_models() -> None:
    config = ProviderConfig(
        name="empty-gemini-compatible",
        base_url="https://gateway.example.com/v1",
        api_key_ref="trainer.gateway",
        model="MiniMax-M3",
        protocol="gemini_generate_content",
    )
    service = ProviderService()

    class _Response:
        status_code = 200
        text = '{"models":[]}'

        def json(self) -> dict[str, object]:
            return {"models": []}

    mock_client = MagicMock()
    mock_client.get.return_value = _Response()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    fake_openai_client = MagicMock()
    fake_openai_client.models.list.return_value = [MagicMock(id="MiniMax-M3")]

    with (
        patch("app.llm.provider_service.httpx.Client", return_value=mock_cm),
        patch.object(
            service,
            "_get_sync_openai_class",
            return_value=MagicMock(return_value=fake_openai_client),
        ),
    ):
        result = service.list_models(config, "sk-test")

    assert result.ok is True
    assert result.available_models == ["MiniMax-M3"]
    assert result.resolved_model == "MiniMax-M3"
    assert fake_openai_client.models.list.call_count == 1
    assert any("no usable native models" in item.lower() for item in result.diagnostics)


def test_provider_list_models_keeps_empty_gemini_gateway_fallback_non_ready() -> None:
    config = ProviderConfig(
        name="empty-gemini-compatible",
        base_url="https://gateway.example.com/v1",
        api_key_ref="trainer.gateway",
        model="MiniMax-M3",
        protocol="gemini_generate_content",
    )
    service = ProviderService()

    class _Response:
        status_code = 200
        text = '{"models":[]}'

        def json(self) -> dict[str, object]:
            return {"models": []}

    mock_client = MagicMock()
    mock_client.get.return_value = _Response()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    fake_openai_client = MagicMock()
    fake_openai_client.models.list.return_value = []

    with (
        patch("app.llm.provider_service.httpx.Client", return_value=mock_cm),
        patch.object(
            service,
            "_get_sync_openai_class",
            return_value=MagicMock(return_value=fake_openai_client),
        ),
    ):
        result = service.list_models(config, "sk-test")

    assert result.ok is False
    assert result.listed is False
    assert result.available_models == []
    assert result.resolved_model is None
    assert fake_openai_client.models.list.call_count == 1
    assert "did not return any visible models" in result.detail


def test_provider_list_models_reports_auth_errors_structurally() -> None:
    config = _make_config()
    service = ProviderService()
    fake_client = MagicMock()
    fake_client.models.list.side_effect = Exception("Error code: 401 - {'error': {'message': 'Invalid API key'}}")

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.list_models(config, "sk-test")

    assert result.ok is False
    assert result.error_category == "invalid_key_or_permission"
    assert result.retryable is False
    assert result.status_code == 401


def test_provider_test_reports_rate_limit_structurally() -> None:
    config = _make_config()
    service = ProviderService()
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = Exception(
        "Error code: 429 - {'error': {'message': 'Rate limit exceeded'}}"
    )

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test")

    assert result.ok is False
    assert result.error_category == "rate_limit"
    assert result.retryable is False
    assert "rate limit" in (result.detail or "").lower()


def test_native_probe_prompts_keep_chinese_visible_probe_legible() -> None:
    service = ProviderService()
    prompts = service._native_probe_prompts("zh-CN")
    assert prompts[0] == "只返回一个可见中文短句：provider ready。"
    assert "请只输出可见文字" in prompts[1]
    assert "reasoning" in prompts[1]


def test_provider_list_models_uses_short_lived_cache_for_same_provider() -> None:
    config = _make_config()
    service = ProviderService()
    fake_client = MagicMock()
    fake_client.models.list.return_value = [MagicMock(id="gpt-4o-mini")]

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        first = service.list_models(config, "sk-test")
        second = service.list_models(config, "sk-test")

    assert first.ok is True
    assert first.cache_hit is False
    assert second.ok is True
    assert second.cache_hit is True
    assert fake_client.models.list.call_count == 1


def test_provider_model_cache_key_hashes_api_key_without_losing_isolation() -> None:
    config = _make_config()
    service = ProviderService()
    api_key = "sk-provider-cache-secret"

    first = service._provider_cache_key(config, api_key)
    same = service._provider_cache_key(config, api_key)
    other = service._provider_cache_key(config, "sk-other-provider-cache-secret")

    assert first == same
    assert first != other
    assert first[1] == sha256(api_key.encode("utf-8")).hexdigest()
    assert all(api_key not in component for component in first)


@pytest.mark.parametrize(
    ("error", "expected_category"),
    [
        (Exception("Error code: 401 - {'error': {'message': 'Incorrect API key provided'}}"), "invalid_key_or_permission"),
        (Exception("Error code: 403 - {'error': {'message': 'Permission denied'}}"), "invalid_key_or_permission"),
        (Exception("Gemini Models list failed (status 401): {\"error\":{\"message\":\"Invalid token\"}}"), "invalid_key_or_permission"),
        (Exception("Error code: 429 - {'error': {'message': 'Rate limit exceeded'}}"), "rate_limit"),
        (TimeoutError("Request timeout while connecting to provider"), "timeout"),
        (OSError("Connection refused"), "network"),
        (Exception("Malformed response: invalid JSON from upstream"), "malformed_response"),
        (Exception("Error code: 400 - {'error': {'message': 'Not supported model gpt-4o-mini'}}"), "model_unsupported"),
        (
            Exception(
                "Error code: 503 - {'error': {'message': 'No available channel for model gpt-4o-mini under group default'}}"
            ),
            "model_not_found",
        ),
    ],
)
def test_provider_test_classifies_connection_failures(error: Exception, expected_category: str) -> None:
    config = _make_config()
    service = ProviderService()

    with patch.object(service, "_get_sync_openai_class", side_effect=error):
        result = service.test(config, "sk-test")

    assert result.ok is False
    assert result.error_category == expected_category
    assert result.detail
    assert result.diagnostics


def _make_rich_current_file(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "path": "app.py",
        "language_id": "python",
        "content": "from fastapi import FastAPI\napp = FastAPI()",
        "selection_range": "1:1-2:17",
        "diagnostics": ["NameError on app startup"],
        "coaching_state": {
            "scenario": "review",
            "learner_signal": "blocked",
            "summary": "The learner needs a tighter review loop.",
            "next_step": "Patch the startup wiring, then rerun the focused check.",
            "encouragement": "Stay with the first blocking path.",
        },
        "memory": {
            "current_focus": "Tighten the FastAPI startup feedback loop",
            "recent_wins": ["Mapped the relevant files before coding"],
            "weaknesses": ["Jumping into patches before restating the target behavior"],
            "coaching_adaptation": {
                "challenge_level": "lower",
                "hint_depth": "direct",
                "review_urgency": "high",
                "explanation_mode": "rebuild",
                "next_step_bias": "shrink",
                "summary": "Recent failures mean the next loop should shrink scope and verify one recovery step first.",
                "evidence": ["The same startup path failed twice."],
            },
            "review_rhythm": "2 follow-up reviews are ready or coming due soon.",
            "due_reviews": [
                {
                    "concept": "startup wiring",
                    "reason": "Repeat the verification flow after the next patch",
                    "due_at": "2026-05-01T10:00:00Z",
                }
            ],
            "teaching_observations": [
                "The learner moves faster after the next step is compressed into one clear patch."
            ],
            "recent_summary": "This workspace improves when the coach keeps the loop short.",
        },
    }
    payload.update(overrides)
    return payload


# 鈹€鈹€ build_coaching_system_prompt 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


def test_system_prompt_includes_profile_data() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(profile)
    assert "Build a FastAPI trainer" in prompt
    assert "Intermediate Python developer" in prompt
    assert "6" in prompt
    assert "guided" in prompt
    assert "fastapi, pytest" in prompt


def test_system_prompt_handles_missing_optional_fields() -> None:
    profile = _make_profile(target_project=None, preferred_libraries=[])
    prompt = build_coaching_system_prompt(profile)
    assert "Not specified" in prompt
    assert "None specified" in prompt


def test_system_prompt_includes_coaching_context_fields() -> None:
    profile = _make_profile()
    current_file = _make_rich_current_file()
    prompt = build_coaching_system_prompt(
        profile,
        response_language="zh-CN",
        message="帮我继续看这个报",
        current_file=current_file,
    )
    assert "Main lane: next step after review. Learner signal: blocked." in prompt
    assert "Stay with Tighten the FastAPI startup feedback loop." in prompt
    assert "Review rhythm: 2 follow-up reviews are ready or coming due soon." in prompt
    assert "Teaching observation:" in prompt or "Recent memory summary:" in prompt
    assert "Adaptation bias:" in prompt
    assert "Respond in natural, stable Simplified Chinese" in prompt


def test_system_prompt_includes_turn_contract_from_live_context() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(
        profile,
        coach_context={
            "scenario": "review",
            "current_focus": "tighten the startup recovery loop",
            "next_step_hint": {
                "title": "Patch the smallest failing branch first",
            },
            "failing_checks": ["pytest", "ruff"],
            "review_queue_summary": "One follow-up review is still due.",
            "pace_signal": "fragile",
            "exercise_prompt": {
                "success_signal": "the smallest focused check passes",
                "fallback_step": "shrink the patch to one file",
            },
            "implementation_guide": {
                "validation_strategy": ["rerun the focused test", "confirm the failure is gone"],
            },
        },
    )
    assert "## Turn Contract" in prompt
    assert "stay on tighten the startup recovery loop" in prompt
    assert "use this next move: Patch the smallest failing branch first" in prompt
    assert "verify against pytest; ruff" in prompt
    assert "shrink scope before widening" in prompt
    assert "treat success as: the smallest focused check passes" in prompt
    assert "fallback: shrink the patch to one file" in prompt
    assert "validate with rerun the focused test; confirm the failure is gone" in prompt


def test_build_coaching_messages_includes_explicit_active_thread_block() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "Continue the thread.",
        coach_context={
            "summary": "General reminder prose should stay separate.",
            "resume_thread": "Continue the live thread instead of restarting.",
            "decision": "Choose the smallest verified fix.",
            "blocker": "Need one more workspace confirmation before widening scope.",
            "teaching_note": "Name the blocker before widening scope.",
            "confidence": "high",
            "evidence": [
                "The async iterator boundary is the only failing branch.",
                "The latest diagnostics are still pointing at the same call site.",
            ],
            "active_thread": {
                "focus_area": "async iterator boundary",
                "summary": "Stay on one async iterator boundary until it is verified.",
                "next_step": "Patch the smallest async iterator call site and rerun the focused check.",
                "verified_result": "The parser is already isolated.",
            },
        },
    )
    system_content = messages[0]["content"]
    user_content = messages[1]["content"]
    assert "## Active Thread" in system_content
    assert "Thread summary: Stay on one async iterator boundary until it is verified." in system_content
    assert "Next step: Patch the smallest async iterator call site and rerun the focused check." in system_content
    assert "Latest finalized decision: Choose the smallest verified fix." in system_content
    assert "Teaching note: Name the blocker before widening scope." in system_content
    assert "Coach confidence: high." in system_content
    assert "Evidence: The async iterator boundary is the only failing branch." in system_content
    assert "keep the latest finalized decision in view: Choose the smallest verified fix" in system_content
    assert "ground the turn in The async iterator boundary is the only failing branch" in system_content
    assert "Resume hint: Continue the live thread instead of restarting." in system_content
    assert "Active thread to resume:" in system_content
    assert user_content == "Continue the thread."


def test_system_prompt_prefers_natural_chat_over_report_style() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(profile, response_language="zh-CN")
    assert "Write like a strong coach in chat" in prompt
    assert "Trainer can teach code, math, writing, English, Chinese, book-based study" in prompt
    assert "Do not force section headings or rigid templates" in prompt
    assert "When the learner writes in Chinese, answer fully in natural Simplified Chinese" in prompt
    assert "Do not mirror the context block structure in the reply." in prompt
    assert "Build trust before breadth" in prompt
    assert "## Request Priority" in prompt
    assert "requested format, requested length, and requested directness" in prompt


def test_system_prompt_includes_exercise_prompt_when_available() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(
        profile,
        coach_context={
            "scenario": "idea_implementation",
            "exercise_prompt": {
                "prompt": "Patch one branch and verify it immediately.",
                "success_signal": "The first focused check passes.",
            },
        },
    )
    assert "Exercise prompt: Patch one branch and verify it immediately." in prompt
    assert "Success signal: The first focused check passes." in prompt


def test_system_prompt_includes_principle_and_project_execution_anchors() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(
        profile,
        coach_context={
            "scenario": "principle",
            "principle_notes": {
                "current_principle": "Anchor the rule to one failing boundary.",
                "why_it_matters": "It prevents the learner from drifting into abstract theory.",
                "apply_now": "Explain the first failing branch before changing code.",
                "source_asset_title": "Boundary-first explanation",
            },
            "project_ideas": [
                {
                    "title": "Review recovery drill",
                    "why_now": "The learner is still unstable in the startup branch.",
                    "first_step": "Patch the first startup branch and rerun one focused check.",
                }
            ],
            "project_entry_points": ["app.py", "server/app/api/routers.py"],
            "failing_checks": ["pytest", "semantic-review"],
        },
    )
    assert "Why it matters: It prevents the learner from drifting into abstract theory." in prompt
    assert "Apply-now move: Explain the first failing branch before changing code." in prompt
    assert "Project idea worth reusing:" in prompt
    assert "First step: Patch the first startup branch and rerun one focused check." in prompt
    assert "Code entry points to name: app.py; server/app/api/routers.py." in prompt
    assert "Reduce these failing checks first: pytest; semantic-review." in prompt


def test_system_prompt_includes_recalled_coaching_memories() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(
        profile,
        coach_context={
            "scenario": "review",
            "recalled_memory_summary": (
                "Verified startup recovery lane: Keep the recovery inside one verified branch."
            ),
        },
    )
    assert "Useful recalled memory:" in prompt
    assert "Keep the recovery inside one verified branch." in prompt


def test_system_prompt_includes_explicit_teaching_style_bias() -> None:
    profile = _make_profile(teaching_style="concept-first")
    prompt = build_coaching_system_prompt(profile)
    assert "## Teaching Style Bias" in prompt
    assert "Active style: concept-first" in prompt
    assert "Start by explaining the mechanism or concept" in prompt


def test_system_prompt_uses_adaptive_teaching_style_for_auto() -> None:
    profile = _make_profile(teaching_style="auto")
    prompt = build_coaching_system_prompt(profile)
    assert "## Teaching Style Bias" in prompt
    assert "Active style: adaptive" in prompt
    assert "Adapt the teaching surface to the learner's evidence." in prompt


def test_system_prompt_uses_adaptive_answer_policy_for_auto() -> None:
    profile = _make_profile(answer_policy="auto")
    prompt = build_coaching_system_prompt(profile)
    assert "## Answer Policy Bias" in prompt
    assert "Active policy: adaptive" in prompt
    assert "Choose the teaching surface per turn." in prompt


def test_system_prompt_includes_state_driven_teaching_and_retrieval_rhythm() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(
        profile,
        message="Please search my resources for MirrorLock protocol before you answer.",
        agent_loop_enabled=True,
    )
    assert "## Teaching Method" in prompt
    assert "Teach in this order when understanding matters" in prompt
    assert "Make concepts feel necessary before naming them." in prompt
    assert "Every 2-3 new ideas, briefly recycle the state" in prompt
    assert "Retrieval rhythm for grounded teaching:" in prompt
    assert "search in passes: broad -> narrow -> verify." in prompt
    assert "prepared library grounding" in prompt
    assert "must call `search_resources` before answering." in prompt
    assert "do not invent from memory." in prompt
    assert "preserve its step count, labels, and boundaries." in prompt
    assert "live coach with a working library habit" in prompt
    assert "explicitly requires a library/resource lookup" in prompt
    assert "Keep 2-5 strong fragments, then synthesize." in prompt


def test_agent_prompt_prefers_direct_intake_when_no_evidence_lookup_was_requested() -> None:
    prompt = build_coaching_system_prompt(
        _make_profile(),
        message="Teach me one small VS Code Remote SSH checkpoint.",
        coach_context={"relationship_stage": "intake"},
        agent_loop_enabled=True,
    )

    assert "write one direct coaching reply without tool calls" in prompt
    assert "Do not recall memory merely to confirm an empty or already-visible state." in prompt
    assert "Do not search merely because a generic teaching topic might exist in a library." in prompt


def test_nonofficial_anthropic_intake_hides_unneeded_agent_tools() -> None:
    provider = ProviderConfig(
        name="compatibility-gateway",
        base_url="https://gateway.example/v1",
        api_key_ref="trainer.compatibility",
        model="compat-model",
        protocol="anthropic_messages",
    )
    context = {
        "relationship_stage": "intake",
        "first_turn_priority": "orient, reassure, clarify learner goal and choose one coaching lane",
        "scenario": "remote_workspace",
        "active_view": "coach",
    }

    extra = _build_agent_tool_context_extra(
        coach_context=context,
        attachment_delivery={"attachments_present": False},
        answer_mode="guided",
        current_file=None,
        provider_config=provider,
    )

    assert extra["allowed_tool_names"] == []


def test_nonofficial_anthropic_intake_keeps_tools_for_resource_grounding() -> None:
    provider = ProviderConfig(
        name="compatibility-gateway",
        base_url="https://gateway.example/v1",
        api_key_ref="trainer.compatibility",
        model="compat-model",
        protocol="anthropic_messages",
    )
    extra = _build_agent_tool_context_extra(
        coach_context={
            "relationship_stage": "intake",
            "first_turn_priority": "orient, reassure, clarify learner goal and choose one coaching lane",
            "scenario": "remote_workspace",
            "resource_fragments": [{"title": "remote-notes"}],
        },
        attachment_delivery={"attachments_present": False},
        answer_mode="guided",
        current_file=None,
        provider_config=provider,
    )

    assert "allowed_tool_names" not in extra


def test_pressure_blocks_denies_generate_training_card_even_when_explicitly_asked() -> None:
    from app.llm.provider_service import _build_agent_tool_context_extra

    extra = _build_agent_tool_context_extra(
        coach_context={
            "scenario": "general",
            "explicit_training_card_request": True,
            "pressure_blocks_live_object_mint": True,
        },
        attachment_delivery={"attachments_present": False},
        answer_mode="guided",
        current_file=None,
        learner_message="Create a practice card for token refresh.",
    )

    assert extra["pressure_blocks_live_object_mint"] is True
    assert extra["explicit_training_card_request"] is True
    assert "generate_training_card" in extra["denied_tool_names"]
    assert "save_formal_plan" in extra["denied_tool_names"]


def test_streak_blocks_denies_task_mint_tools_like_pressure() -> None:
    from app.llm.provider_service import _build_agent_tool_context_extra

    extra = _build_agent_tool_context_extra(
        coach_context={
            "scenario": "general",
            "streak_blocks_live_object_mint": True,
            "live_formal_plan_for_task_mint": True,
        },
        attachment_delivery={"attachments_present": False},
        answer_mode="guided",
        current_file=None,
        learner_message="Give me the next task.",
    )

    assert extra["streak_blocks_live_object_mint"] is True
    assert "generate_training_card" in extra["denied_tool_names"]
    assert "specify_task" in extra["denied_tool_names"]
    assert "next_task" in extra["denied_tool_names"]


def test_system_prompt_includes_tone_and_intake_bias_when_available() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(
        profile,
        coach_context={
            "relationship_stage": "intake",
            "first_turn_priority": "orient, reassure, clarify learner goal and choose one coaching lane",
            "pace_signal": "fragile",
            "coaching_adaptation": {
                "summary": "Recent failures mean the next loop should shrink scope.",
                "next_step_bias": "shrink",
                "hint_depth": "direct",
                "review_urgency": "high",
            },
            "tone_decision": {
                "tone": "encouraging",
                "verbosity_bias": "short",
                "acknowledge_progress": True,
                "avoid_overwhelm": True,
            },
            "learner_state": {
                "needs_rescue": True,
            },
        },
    )
    assert "## Tone And Continuity Bias" in prompt
    assert "Intake turn: start by orienting and understanding the learner" in prompt
    assert "Pace signal: fragile" in prompt
    assert "Scope bias: shrink." in prompt
    assert "Surface tone: encouraging. Keep verbosity short." in prompt
    assert "Rescue mode: stabilize the learner first" in prompt


def test_system_prompt_prefers_execution_ready_next_step_over_intake_bias() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(
        profile,
        message="Based on the current file and my goal, give me one very small next step with strong teaching value.",
        current_file={
            "path": "demo.py",
            "language_id": "python",
            "content": "def add(a, b):\n    return a + b\n",
            "diagnostics": [],
        },
        coach_context={
            "relationship_stage": "intake",
            "first_turn_priority": "orient, reassure, clarify learner goal and choose one coaching lane",
        },
    )
    assert "Execution-ready turn:" in prompt
    assert "Intake turn: start by orienting and understanding the learner" not in prompt


def test_system_prompt_explicitly_overrides_continuity_when_switching_lanes() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(
        profile,
        message="Teach me the VS Code remote workflow for SSH and dev containers.",
        coach_context={
            "history_mode": "fresh_lane",
            "relationship_stage": "intake",
            "first_turn_priority": "re-anchor on the newly requested coaching lane and keep the first move compact",
        },
    )
    assert "Lane switch: the learner clearly changed direction." in prompt
    assert "do not narrate the previous thread" in prompt


def test_system_prompt_tells_grounded_principle_turn_to_answer_resource_question_first() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(
        profile,
        message="我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise，以及它绝不能变成什么。",
        coach_context={
            "scenario": "principle",
            "history_mode": "fresh_lane",
            "auto_resource_lookup": True,
            "requested_resources": [
                {"id": "doc-1", "title": "resources-view-contract.md", "kind": "markdown"}
            ],
            "resource_question_facets": ["Resources", "first viewport promise", "must not become"],
        },
    )
    assert "answer the explicit resource question directly" in prompt
    assert "cover every explicitly requested resource facet" in prompt
    assert "state both the positive promise and the negative must-not-become boundary" in prompt


def test_system_prompt_treats_vscode_guidance_lanes_as_first_class_playbooks() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(
        profile,
        message="Continue.",
        coach_context={
            "scenario": "function_guidance",
            "thread_summary": "Read one function boundary from one live call site.",
            "thread_next_step": "Name what the function expects and which call site proves it.",
            "active_thread": {
                "scenario": "function_guidance",
                "focus_area": "signature help",
                "summary": "Read one function boundary from one live call site.",
                "next_step": "Name what the function expects and which call site proves it.",
            },
        },
    )
    assert "remote_workspace: teach the real VS Code remote boundary first" in prompt
    assert "debug_loop: keep debugging inside one trustworthy loop" in prompt
    assert "function_guidance: read one live function contract" in prompt
    assert coaching_scenario_label("function_guidance") == "function contract guidance"


def test_system_prompt_hides_review_reflection_mode_when_function_guidance_is_explicit() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(
        profile,
        message="Continue.",
        coach_context={
            "scenario": "function_guidance",
            "summary": "Read one function boundary instead of the whole module.",
            "thread_summary": "Read one function boundary instead of the whole module.",
            "thread_next_step": "Inspect the first call site and name one parameter contract.",
            "teaching_decision": {
                "mode": "review_reflection",
                "primary_goal": "Keep the learner inside one concrete function-reading loop.",
            },
            "active_thread": {
                "scenario": "function_guidance",
                "focus_area": "signature help",
                "summary": "Read one function boundary instead of the whole module.",
                "next_step": "Inspect the first call site and name one parameter contract.",
            },
        },
    )
    assert "Main lane: function contract guidance." in prompt
    assert "Teaching mode: review_reflection." not in prompt


def test_system_prompt_agent_loop_discourages_repeated_evidence_probing() -> None:
    profile = _make_profile()
    prompt = build_coaching_system_prompt(profile, agent_loop_enabled=True)
    assert "If the same evidence keeps coming back" in prompt
    assert "continue until the library or coaching question is settled" in prompt
    assert "coach_finalize" in prompt
    assert "use it last" in prompt.lower()
    assert "do not write learner-facing prose alongside it" in prompt.lower()
    assert "required fields are a short `summary` and a concrete `next_step`" in prompt
    assert "grounded `decision`, `blocker`, `teaching_note`, `confidence`, or `evidence` bullets" in prompt
    assert "resume_thread" in prompt
    assert "Keep evidence specific" in prompt


# 鈹€鈹€ extract_coaching_context 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


def test_extract_coaching_context_uses_nested_memory_and_state() -> None:
    context = extract_coaching_context("帮我继续看这个报", _make_rich_current_file())
    assert context["scenario"] == "review"
    assert context["learner_signal"] == "blocked"
    assert context["current_focus"] == "Tighten the FastAPI startup feedback loop"
    assert context["recent_wins"] == ["Mapped the relevant files before coding"]
    assert context["weak_spots"] == ["Jumping into patches before restating the target behavior"]
    assert len(context["due_reviews"]) == 1
    assert context["review_rhythm"] == "2 follow-up reviews are ready or coming due soon."
    assert context["teaching_observations"] == [
        "The learner moves faster after the next step is compressed into one clear patch."
    ]
    assert context["coaching_adaptation"]["next_step_bias"] == "shrink"


def test_extract_coaching_context_reads_reply_binding_fields() -> None:
    context = extract_coaching_context(
        "继续推进这个训练",
        None,
        {
            "teaching_asset_summary": "implementation_pattern: keep one branch narrow",
            "recalled_memory_summary": "Verified lane: keep the startup branch narrow",
            "summary": "The reply path still needs a tighter recovery loop.",
            "thread_summary": "Stay on the active startup branch until it is verified.",
            "thread_next_step": "Patch the smallest startup branch and rerun the focused check.",
            "resume_thread": "Continue the live thread instead of restarting.",
            "recalled_coaching_memories": [
                {
                    "title": "Verified lane",
                    "lesson": "keep the startup branch narrow",
                }
            ],
            "selected_teaching_asset_ids": ["asset-1", "asset-2"],
            "failing_checks": ["pytest"],
            "project_entry_points": ["app.py", "server/app/api/routers.py"],
            "project_summary": "The reply path still needs a tighter recovery loop.",
            "review_queue_summary": "One review is overdue.",
            "next_review_due": "2026-05-04T10:00:00Z",
            "pace_signal": "fragile",
            "recent_teaching_signals": [
                "Keep the startup branch narrow",
                "Re-verify before widening",
            ],
            "continuity_summary": "startup branch -> rerun one focused check",
            "learning_outcomes": [
                {
                    "concept": "startup wiring",
                    "outcome": "repeated_error",
                    "summary": "The same branch failed twice.",
                }
            ],
            "active_thread": {
                "focus_area": "startup branch",
                "summary": "Stay on the active startup branch until it is verified.",
                "next_step": "Patch the smallest startup branch and rerun the focused check.",
                "blocker": "The same startup path failed twice.",
                "verified_result": "The parser step is already isolated.",
            },
        },
    )
    assert context["teaching_asset_summary"] == "implementation_pattern: keep one branch narrow"
    assert context["recalled_memory_summary"] == "Verified lane: keep the startup branch narrow"
    assert context["recalled_coaching_memories"][0]["title"] == "Verified lane"
    assert context["selected_teaching_asset_ids"] == ["asset-1", "asset-2"]
    assert context["failing_checks"] == ["pytest"]
    assert context["project_entry_points"] == ["app.py", "server/app/api/routers.py"]
    assert context["project_summary"] == "The reply path still needs a tighter recovery loop."
    assert context["review_queue_summary"] == "One review is overdue."
    assert context["next_review_due"] == "2026-05-04T10:00:00Z"
    assert context["pace_signal"] == "fragile"
    assert context["summary"] == "The reply path still needs a tighter recovery loop."
    assert context["thread_summary"] == "Stay on the active startup branch until it is verified."
    assert context["thread_next_step"] == "Patch the smallest startup branch and rerun the focused check."
    assert "Continue the live thread instead of restarting." in context["resume_hint"]
    assert context["recent_teaching_signals"] == [
        "Keep the startup branch narrow",
        "Re-verify before widening",
    ]
    assert context["continuity_summary"] == "startup branch -> rerun one focused check"
    assert isinstance(context["learning_outcomes"], list)


def test_extract_coaching_context_tolerates_missing_active_view() -> None:
    context = extract_coaching_context(
        "请先告诉我 Resources 视图的 first viewport promise。",
        None,
        {
            "summary": "Use the imported resource before widening scope.",
            "requested_resource_summary": "One imported design document is ready.",
        },
    )

    assert context["active_view"] is None
    assert context["requested_resource_summary"] == "One imported design document is ready."


# 鈹€鈹€ build_coaching_messages 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€



def test_infer_coaching_scenario_handles_chinese_keywords() -> None:
    assert infer_coaching_scenario("请帮我复盘这个报", default="general") == "review"
    assert infer_coaching_scenario("把这个现有项目改造一", default="general") == "project_adaptation"
    assert infer_coaching_scenario("我想提炼一个练什么都能用的小练习", default="general") == "project_idea"
    assert infer_coaching_scenario("下一题该怎么", default="general") == "next_task"
    assert infer_coaching_scenario("只是随便聊聊", default="general") == "general"


def test_infer_coaching_scenario_diagnose_why_fail_is_review_not_principle() -> None:
    assert infer_coaching_scenario(
        "Help me diagnose why auth.py fails before we generate a plan or a task.",
        default="general",
    ) == "review"


def test_infer_coaching_scenario_prefers_guided_domain_lanes() -> None:
    assert infer_coaching_scenario(
        "Teach me VS Code Remote SSH step by step before you test me.",
        default="general",
    ) == "remote_workspace"
    assert infer_coaching_scenario(
        "Teach me how to debug Python in VS Code with one breakpoint first.",
        default="general",
    ) == "debug_loop"
    assert infer_coaching_scenario(
        "Teach me signature help and function hints in VS Code before any quiz.",
        default="general",
    ) == "function_guidance"


def test_infer_coaching_scenario_prefers_guided_domain_lanes_in_chinese() -> None:
    assert infer_coaching_scenario(
        "请先教我 VS Code 远程 SSH 和 dev container 的工作区边界。",
        default="general",
    ) == "remote_workspace"
    assert infer_coaching_scenario(
        "请先教我怎么在 VS Code 里调试 Python，只盯住一个断点和调用栈。",
        default="general",
    ) == "debug_loop"
    assert infer_coaching_scenario(
        "请先教我看懂这个函数的参数提示、签名和定义，先看一个调用点。",
        default="general",
    ) == "function_guidance"
    assert infer_coaching_scenario(
        "请陪我把一个现有项目改造到新的目标上，先分清哪些必须保持不变。",
        default="general",
    ) == "project_adaptation"


def test_infer_coaching_scenario_uses_code_anchor_for_function_guidance() -> None:
    assert infer_coaching_scenario(
        "请教我如何判断一个 TypeScript 函数的 contract。先学习，再让我做一个很小的 try。",
        {
            "path": "src/demo.ts",
            "language_id": "typescript",
            "selection_text": (
                "export async function fetchLesson(lessonId: string, policy: RetryPolicy): Promise<Response> {\n"
                "  return request(`/api/lessons/${lessonId}`, policy);\n"
                "}"
            ),
            "content_excerpt": (
                "export async function fetchLesson(lessonId: string, policy: RetryPolicy): Promise<Response> {\n"
                "  return request(`/api/lessons/${lessonId}`, policy);\n"
                "}"
            ),
        },
        default="general",
    ) == "function_guidance"


def test_infer_coaching_scenario_routes_direct_resource_doc_question_to_principle() -> None:
    assert infer_coaching_scenario(
        "我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise，以及它绝不能变成什么。",
        default="general",
    ) == "principle"


def test_agentic_practice_verification_context_ignores_doc_question_with_task_flavored_summary() -> None:
    assert (
        _agentic_practice_verification_context_active(
            message="我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise。",
            current_file=None,
            coach_context={
                "coaching_state": {"scenario": "task"},
                "summary": "Practice loop: verify one card before widening scope.",
                "next_step": "Return to the practice card after one more verification pass.",
            },
        )
        is False
    )


def test_agentic_practice_verification_context_accepts_explicit_current_file_verification_request() -> None:
    assert (
        _agentic_practice_verification_context_active(
            message="Verify this practice card from my current IDE file.",
            current_file={
                "path": "src/search.ts",
                "content": "export const search = () => true;\n",
            },
            coach_context=None,
        )
        is True
    )


def test_claims_verified_practice_completion_ignores_generic_verified_doc_language() -> None:
    assert _claims_verified_practice_completion(
        "This point is verified by the design doc and should stay grounded to the cited source."
    ) is False
    assert _claims_verified_practice_completion(
        "Current-file verification passed, so you can mark this complete."
    ) is True


def test_first_turn_guided_lane_recognizes_call_site_function_prompt() -> None:
    assert (
        _first_turn_guided_lane(
            "general",
            "Teach me a TypeScript function from one real call site before I edit it.",
        )
        == "function_guidance"
    )


def test_infer_learner_signal_handles_chinese_keywords() -> None:
    assert infer_learner_signal("我卡住了，搞不定") == "blocked"
    assert infer_learner_signal("我不确定，大概还差一") == "uncertain"
    assert infer_learner_signal("我想试试这个原理") == "curious"


def test_build_coaching_messages_structure() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(profile, "Hello coach")
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Hello coach"
    assert "Learner context:" in messages[0]["content"]
    assert "- Treat this as `idea_implementation` with a `steady` learner." in messages[0]["content"]
    assert "Coaching defaults:" not in messages[0]["content"]


def test_build_coaching_messages_keeps_only_recent_history() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "Hello coach",
        history=[
            {"role": "system", "content": "ignore me"},
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "turn 2"},
            {"role": "tool", "content": "tool output"},
            {"role": "user", "content": "turn 3"},
        ],
        history_limit=2,
    )
    roles = [message["role"] for message in messages]
    contents = [message["content"] for message in messages]
    assert roles == ["system", "assistant", "user", "user"]
    assert contents[1] == "turn 2"
    assert contents[2] == "turn 3"
    assert contents[3].startswith("Hello coach")


def test_build_coaching_messages_can_drop_history_entirely() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "Hello coach",
        history=[
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "turn 2"},
        ],
        history_limit=0,
    )
    assert len(messages) == 2
    assert messages[1]["content"].startswith("Hello coach")


def test_build_coaching_messages_can_suppress_history_for_fresh_lane_reanchor() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "Teach me the VS Code remote workflow for SSH and dev containers.",
        coach_context={
            "history_mode": "fresh_lane",
            "relationship_stage": "intake",
            "first_turn_priority": "re-anchor on the newly requested coaching lane and keep the first move compact",
        },
        history=[
            {"role": "user", "content": "Help me learn debugging in VS Code."},
            {"role": "assistant", "content": "Choose one breakpoint and one observed value first."},
        ],
        history_limit=4,
    )
    assert len(messages) == 2
    assert messages[1]["content"].startswith("Teach me the VS Code remote workflow")
    assert "Help me learn debugging in VS Code." not in messages[1]["content"]


def test_current_file_included_in_system_context() -> None:
    profile = _make_profile()
    current_file = {"path": "main.py", "language_id": "python", "content": "print('hello')"}
    messages = build_coaching_messages(profile, "Review this", current_file=current_file)
    assert len(messages) == 2
    system_content = messages[0]["content"]
    assert "main.py" in system_content
    assert "python" in system_content
    assert "print('hello')" in system_content
    assert messages[1]["content"] == "Review this"


def test_build_coaching_messages_ignores_html_preview_current_file_for_function_guidance() -> None:
    profile = _make_profile()
    current_file = {
        "path": "index.html",
        "language_id": "html",
        "content": "<!doctype html>\n<html lang=\"en\"><body><script>function renderUser() {}</script></body></html>",
    }
    messages = build_coaching_messages(
        profile,
        "Help me understand this function contract before I edit it.",
        current_file=current_file,
    )
    system_content = messages[0]["content"]
    user_content = messages[1]["content"]
    assert "<!doctype html>" not in system_content
    assert "<!doctype html>" not in user_content
    assert "index.html" not in system_content
    assert "index.html" not in user_content


def test_build_coaching_messages_surfaces_trainer_owned_function_guidance_starter() -> None:
    profile = _make_profile()
    starter = {
        "status": "ready",
        "language_id": "typescript",
        "boundary_note": (
            "Trainer-owned sandbox starter. Use it as a practice scaffold until a real project call site is available."
        ),
        "coach_instruction": (
            "Use this starter as the live call site for learn-first teaching instead of asking the learner for project code first."
        ),
        "call_site_path": "knowledge/function-guidance/typescript/src/usage.ts",
        "definition_path": "knowledge/function-guidance/typescript/src/client.ts",
        "call_site_content": (
            "import { fetchJson } from \"./client\";\n\n"
            "export async function loadUser(userId: string) {\n"
            "  return fetchJson(`/api/users/${userId}`);\n"
            "}\n"
        ),
        "definition_content": (
            "export async function fetchJson(url: string): Promise<unknown> {\n"
            "  return fetch(url).then((response) => response.json());\n"
            "}\n"
        ),
        "suggested_sequence": [
            "Open the prepared call site first.",
            "Use hover, then signature help.",
            "Jump to definition and name the contract.",
        ],
    }
    messages = build_coaching_messages(
        profile,
        "Teach me this function in VS Code before you test me.",
        coach_context={
            "scenario": "function_guidance",
            "function_guidance_starter": starter,
        },
    )
    system_content = messages[0]["content"]
    user_content = messages[1]["content"]
    assert "Trainer sandbox starter" in system_content
    assert "Trainer sandbox starter: begin in knowledge/function-guidance/typescript/src/usage.ts" in system_content
    assert "Trainer-owned sandbox starter" in system_content
    assert "usage.ts" in system_content
    assert "client.ts" in system_content
    assert "fetchJson" in system_content
    assert "signature help" in system_content
    assert user_content == "Teach me this function in VS Code before you test me."


def test_finalize_coaching_reply_strips_leading_html_shell_artifact() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service.finalize_coaching_reply(
        (
            "<!doctype html>\n"
            "<html lang=\"en\"><head><meta charset=\"UTF-8\" /></head><body><div id=\"app\"></div></body></html>\n\n"
            "I will keep this on one trustworthy debug loop: reproduce once, pause at the first meaningful state change, then inspect one value."
        ),
        profile=_make_profile(),
        message="Teach me how to debug Python in VS Code before any quiz.",
        response_language="en-US",
        answer_mode="guided",
        coach_context={
            "scenario": "debug_loop",
            "history_mode": "fresh_lane",
            "relationship_stage": "active",
            "current_focus": "VS Code debug loop",
        },
    )
    lowered = reply.lower()
    assert "<!doctype html>" not in lowered
    assert "<html" not in lowered
    assert "trustworthy debug loop" in lowered
    assert "state change" in lowered


def test_finalize_coaching_reply_blocks_pure_provider_html_shell() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service.finalize_coaching_reply(
        (
            "<!doctype html>\n"
            "<html lang=\"en\"><head><title>New API</title></head>"
            "<body><div id=\"root\"></div><script src=\"/static/js/index.js\"></script></body></html>"
        ),
        profile=_make_profile(),
        message="Teach me how to debug Python in VS Code before any quiz.",
        response_language="en-US",
        answer_mode="guided",
        coach_context={
            "scenario": "debug_loop",
            "history_mode": "fresh_lane",
            "relationship_stage": "active",
            "current_focus": "VS Code debug loop",
        },
    )
    lowered = reply.lower()
    assert "<!doctype html>" not in lowered
    assert "<html" not in lowered
    assert "provider" in lowered
    assert "protocol" in lowered
    assert service.peek_last_reply_failure()["error_category"] == "malformed_response"


def test_build_coaching_messages_includes_coach_context_block() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(profile, "Please review this", current_file=_make_rich_current_file())
    system_content = messages[0]["content"]
    assert "Learner context:" in system_content
    assert "- Treat this as `review` with a `blocked` learner." in system_content
    assert "Adaptive bias:" in system_content
    assert "Review rhythm to keep alive: 2 follow-up reviews are ready or coming due soon." in system_content
    assert "Teaching observation:" in system_content
    assert messages[1]["content"] == "Please review this"


def test_build_coaching_messages_prefers_background_reference_summary_over_raw_snippet() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "Please keep the grounding tight.",
        coach_context={
            "background_reference_summary": "The distilled proof path is here.",
            "external_references": [
                {
                    "snippet": "Raw title and BOM noise should stay out of the prompt.",
                    "evidence_summary": "The distilled proof path is here.",
                    "source": "https://example.com/paper",
                }
            ],
        },
    )
    system_content = messages[0]["content"]
    assert "Background research summary: The distilled proof path is here." in system_content
    assert "One useful reference: The distilled proof path is here. (https://example.com/paper)." in system_content
    assert "Raw title and BOM noise should stay out of the prompt." not in system_content
    assert "Teaching knowledge fragment:" not in system_content


def test_build_coaching_messages_compacts_runtime_bias() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "Please keep going",
        coach_context={
            "coach_defaults": {
                "memory_scope": "project",
                "working_set_mode": "focused",
                "workspace_memory_toggles": {
                    "decisions": True,
                    "patterns": True,
                    "resources": False,
                },
            }
        },
    )
    system_content = messages[0]["content"]
    assert "Coaching defaults:" in system_content
    assert "- Memory scope: project." in system_content
    assert "- Working set mode: focused." in system_content
    assert messages[1]["content"] == "Please keep going"


@pytest.mark.asyncio
async def test_coaching_reply_uses_structured_next_step_hint_payload() -> None:
    service = ProviderService()
    profile = _make_profile()

    reply = await service.coaching_reply(
        profile,
        "Help me continue the current thread.",
        coach_context={
            "scenario": "general",
            "summary": "Stay on one async iterator boundary until it is verified.",
            "next_step_hint": {
                "title": "Patch the smallest async iterator call site and rerun the focused check.",
                "summary": "Keep this slice narrow and verify it before widening scope.",
            },
        },
    )

    assert "Patch the smallest async iterator call site and rerun the focused check." in reply
    assert "Stay on one async iterator boundary until it is verified." in reply


def test_build_coaching_messages_includes_exercise_prompt_block() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "Help me implement this",
        coach_context={
            "scenario": "idea_implementation",
            "exercise_prompt": {
                "prompt": "Patch one thin behavior first.",
                "fallback_step": "Reduce it to one helper and one check.",
            },
        },
    )
    system_content = messages[0]["content"]
    assert "Exercise prompt: Patch one thin behavior first." in system_content
    assert "Fallback if needed: Reduce it to one helper and one check." in system_content
    assert messages[1]["content"] == "Help me implement this"


def test_build_coaching_messages_includes_reply_binding_hints() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "Please keep the next reply grounded.",
        coach_context={
            "scenario": "review_reflection",
            "teaching_asset_summary": "implementation_pattern: keep one branch narrow",
            "failing_checks": ["pytest"],
            "project_entry_points": ["app.py", "server/app/api/routers.py"],
            "project_ideas": [
                {
                    "title": "Startup recovery drill",
                    "why_now": "The startup branch is still unstable.",
                    "first_step": "Patch the startup branch and rerun one focused check.",
                }
            ],
            "principle_notes": {
                "current_principle": "Explain the first failing boundary before widening.",
                "why_it_matters": "It reduces drift and premature abstraction.",
                "apply_now": "Name the first failing branch and why it breaks.",
            },
            "learning_outcomes": [
                {
                    "concept": "startup wiring",
                    "outcome": "repeated_error",
                    "summary": "The same branch failed twice.",
                }
            ],
        },
    )
    system_content = messages[0]["content"]
    assert "Preferred teaching asset: implementation_pattern: keep one branch narrow." in system_content
    assert "Reduce these checks first: pytest." in system_content
    assert "Code entry points: app.py; server/app/api/routers.py." in system_content
    assert "Project idea anchor: Startup recovery drill. First step: Patch the startup branch and rerun one focused check." in system_content
    assert "Principle apply-now move: Name the first failing branch and why it breaks." in system_content
    assert "Latest outcome: startup wiring / repeated_error." in system_content
    assert messages[1]["content"] == "Please keep the next reply grounded."


def test_build_coaching_messages_keeps_first_turn_onboarding_when_only_workspace_context_exists() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "我想先说丢下我现在的想法",
        coach_context={
            "project_summary": "This repo already contains the trainer shell and sidecar.",
            "project_entry_points": ["server/app/api/routers.py"],
            "current_focus": "当前聚焦：先沿着「trainer shell」继续推进",
            "learning_outcomes": [],
            "due_reviews": [],
            "memory_evidence": [],
            "teaching_observations": [],
        },
    )
    system_content = messages[0]["content"]
    assert "First-turn rule:" in system_content
    assert messages[1]["content"] == "我想先说丢下我现在的想法"


def test_build_coaching_messages_keeps_direct_question_as_final_user_message() -> None:
    profile = _make_profile()
    question = "Does Trainer currently support Windows, macOS, and Linux?"

    messages = build_coaching_messages(profile, question)

    assert messages[-1] == {"role": "user", "content": question}


def test_direct_answer_mode_keeps_a_substantive_first_reply_intact() -> None:
    service = ProviderService(api_key="sk-test")
    question = "Does Trainer currently support Windows, macOS, and Linux?"
    direct_answer = (
        "Trainer supports Windows, macOS, and Linux for its TypeScript, React, and Python source.\n\n"
        "The packaged helper scripts are currently Windows-specific, so macOS and Linux use the documented cross-platform commands.\n\n"
        "Use Python 3.12 or newer, build with npm, and run the sidecar manually on those platforms."
    )

    reply = service.finalize_coaching_reply(
        direct_answer,
        profile=_make_profile(),
        message=question,
        response_language="en-US",
        answer_mode="direct",
    )

    assert reply == direct_answer


def test_clear_auto_mode_reply_is_not_replaced_with_intake_copy() -> None:
    service = ProviderService(api_key="sk-test")
    question = "Explain Python closures in three sentences without asking a question first."
    reply_text = (
        "A closure is a function that keeps access to variables from its enclosing scope.\n\n"
        "It still has that access after the enclosing function returns.\n\n"
        "This makes it useful for callbacks and small pieces of private state."
    )

    reply = service.finalize_coaching_reply(
        reply_text,
        profile=_make_profile(),
        message=question,
        response_language="en-US",
        answer_mode="auto",
        coach_context={
            "relationship_stage": "intake",
            "scenario": "function_guidance",
            "function_guidance_starter": {
                "call_site_path": "src/example.py",
                "definition_path": "src/closure.py",
            },
        },
    )

    assert reply == reply_text


def test_build_coaching_messages_keeps_file_context_out_of_final_user_message() -> None:
    profile = _make_profile()
    message = "Can you explain this error?"
    current_file = {
        "path": "main.py",
        "language_id": "python",
        "content": "print(missing_value)",
        "diagnostics": ["NameError: name 'missing_value' is not defined"],
    }

    messages = build_coaching_messages(profile, message, current_file=current_file)

    assert messages[-1] == {"role": "user", "content": message}
    assert "main.py" in messages[0]["content"]
    assert "print(missing_value)" in messages[0]["content"]
    assert "NameError: name 'missing_value' is not defined" in messages[0]["content"]


def test_build_coaching_messages_skips_first_turn_priority_for_execution_ready_request() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "Based on the current file and my goal, give me one very small next step with strong teaching value.",
        current_file={
            "path": "demo.py",
            "language_id": "python",
            "content": "def add(a, b):\n    return a + b\n",
            "diagnostics": [],
        },
        coach_context={
            "relationship_stage": "intake",
            "first_turn_priority": "orient, reassure, clarify learner goal and choose one coaching lane",
        },
    )
    assert messages[1]["content"] == (
        "Based on the current file and my goal, give me one very small next step with strong teaching value."
    )


def test_build_coaching_messages_skips_first_turn_priority_for_remote_learn_first_verification_request() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "我在 VS Code 里通过 remote SSH 连到服务器后，哪些路径不该让 Trainer 直接写？先学习，再给我一个最小验证动作。",
        coach_context={
            "relationship_stage": "intake",
            "first_turn_priority": "orient, reassure, clarify learner goal and choose one coaching lane",
        },
    )
    assert messages[1]["content"] == (
        "我在 VS Code 里通过 remote SSH 连到服务器后，哪些路径不该让 Trainer 直接写？先学习，再给我一个最小验证动作。"
    )


def test_build_coaching_messages_treats_finalized_thread_metadata_as_live_context() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "Continue from the latest decision.",
        coach_context={
            "decision": "Choose the smallest verified fix.",
            "blocker": "Need one more workspace confirmation before widening scope.",
            "teaching_note": "Name the blocker before widening scope.",
            "confidence": "high",
            "evidence": [
                "The same async iterator boundary remains the only failing branch.",
            ],
        },
    )
    system_content = messages[0]["content"]
    assert messages[1]["content"] == "Continue from the latest decision."
    assert "Latest finalized decision: Choose the smallest verified fix." in system_content
    assert "Coach confidence: high." in system_content


def test_build_coaching_messages_includes_project_sources_when_available() -> None:
    profile = _make_profile()
    messages = build_coaching_messages(
        profile,
        "Help me find a good public training repo.",
        coach_context={
            "scenario": "project_sourcing",
            "project_sources": [
                {
                    "title": "FastAPI RealWorld",
                    "repo_hint": "Start from the API slice and trace one request end to end.",
                    "why_it_fits": "It gives the learner a realistic backend and frontend boundary.",
                }
            ],
        },
    )
    system_content = messages[0]["content"]
    assert "source angle" in system_content.lower() or "repo angle" in system_content.lower()
    assert "FastAPI RealWorld" in system_content
    assert "trace one request end to end" in system_content
    assert messages[1]["content"] == "Help me find a good public training repo."


# 鈹€鈹€ coaching_reply: no profile 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


@pytest.mark.asyncio
async def test_no_profile_returns_onboarding_message() -> None:
    service = ProviderService()
    reply = await service.coaching_reply(None, "Hello")
    assert "cannot start working yet" in reply
    assert "API key" in reply


def test_onboarding_reply_sets_relationship_first_tone_in_chinese() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._onboarding_reply("zh-CN")
    assert "先别急着直接上方案" in reply
    assert "目标、项目语境" in reply
    assert "手上的项目" in reply
    assert "我会记住这些判断" in reply
    assert "你现在更需要我带你做哪一类" in reply


def test_onboarding_reply_sets_relationship_first_tone_in_english() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._onboarding_reply("en-US")
    assert "Let's not jump straight into a solution" in reply
    assert "Let闂" not in reply
    assert "not jump straight into a solution" in reply
    assert "project context" in reply
    assert "how you prefer to be coached" in reply
    assert "few things that matter most" in reply
    assert "implement an idea, adapt a project, or shape the training thread" in reply


def test_postprocess_first_turn_reply_uses_clean_ascii_ellipsis_when_trimming() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        (
            "Debugging should feel like one tight loop you can trust before you widen the lesson. "
            "We will first stabilize the exact breakpoint, then verify one observed value before doing anything else. "
            "That is the whole point of this first turn."
            "\n\n"
            "The first answer should stay compact even when the raw scaffold starts long, because the learner needs one calm entry point rather than a wall of instructions."
        ),
        response_language="en-US",
        learner_message="Help me start this coaching thread with one tiny verified move.",
    )
    assert "..." in reply
    assert "Next step: tell me where you will pause first" in reply


def test_postprocess_first_turn_reply_describes_continuity_in_chinese() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        "先从你的目标开始，再决定怎么推进。",
        response_language="zh-CN",
        learner_message="我想让你带我把一个现有项目改成我真正想要的样子。",
    )
    assert "我会先理解你的目标、项目语境和当前阻塞点" in reply
    assert "现有项目里哪些必须稳定、哪些必须改变" in reply
    assert "真实例子、片段或输入" in reply
    assert "告诉我现在更接近哪一类" not in reply


def legacy_postprocess_first_turn_reply_promises_continuity_in_english() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        "Let鈥檚 start from your goal before we choose a path.",
        response_language="en-US",
        learner_message="I want you to guide me while reshaping an existing project around my own intent.",
    )
    assert "remember that context for the next turn" in reply
    assert "implementing an idea" in reply
    assert "adapting a project" in reply
    assert "training thread first" in reply


# 鈹€鈹€ coaching_reply: no API key (scaffold mode) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


@pytest.mark.asyncio
async def test_no_api_key_returns_high_quality_scaffold_reply() -> None:
    service = ProviderService()
    profile = _make_profile()
    reply = await service.coaching_reply(profile, "Help me turn this idea into code")
    assert "cannot start working yet" in reply
    assert "Settings" in reply


@pytest.mark.asyncio
async def test_agentic_reply_routes_history_and_loop_mode_into_agent_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()
    captured: dict[str, object] = {}

    async def _fake_call(_messages: list[dict[str, object]], _tools: list[dict[str, object]] | None) -> dict[str, object]:
        return {"content": "Agentic reply.", "tool_calls": []}

    fake_provider = SimpleNamespace(protocol="openai_chat_completions", call=_fake_call, call_stream=None)

    class _FakeLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            captured["provider"] = provider
            captured["registry"] = registry
            captured["context"] = context
            captured["max_steps"] = max_steps

        async def run(self, messages: list[dict[str, object]]):
            captured["messages"] = messages
            return SimpleNamespace(
                final_content="Agentic reply.",
                steps=[],
                summary="loop summary",
                next_step="loop next step",
                stop_reason="completed",
                decision="lock the smallest verified branch",
                blocker="missing workspace proof",
                teaching_note="state the blocker before widening scope",
                confidence="high",
                evidence=["tool result A", "tool result B"],
            )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    def _fake_build_coaching_messages(*args: object, **kwargs: object) -> list[dict[str, object]]:
        captured["build_messages_kwargs"] = kwargs
        return [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]

    monkeypatch.setattr("app.llm.provider_service.build_coaching_messages", _fake_build_coaching_messages)
    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _FakeLoop)

    reply = await service.coaching_reply_agentic(
        profile,
        "Continue the current thread.",
        current_file={"path": "src/app.py", "language_id": "python", "content": "print('hi')"},
        history=[
            {"role": "user", "content": "earlier turn"},
            {"role": "assistant", "content": "earlier reply"},
        ],
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
        },
    )

    assert reply["content"] == "Agentic reply."
    assert reply["summary"] == "loop summary"
    assert reply["next_step"] == "loop next step"
    assert reply["stop_reason"] == "completed"
    assert reply["decision"] == "lock the smallest verified branch"
    assert reply["blocker"] == "missing workspace proof"
    assert reply["teaching_note"] == "state the blocker before widening scope"
    assert reply["resume_thread"] == "Resume the live thread around loop summary. Next: loop next step"
    assert reply["confidence"] == "high"
    assert reply["evidence"] == ["tool result A", "tool result B"]
    assert reply["fell_back"] is False
    assert captured["build_messages_kwargs"]["agent_loop_enabled"] is True
    assert captured["build_messages_kwargs"]["history"] == [
        {"role": "user", "content": "earlier turn"},
        {"role": "assistant", "content": "earlier reply"},
    ]
    assert captured["max_steps"] == CoachAgentLoop.SAFETY_MAX_STEPS
    context = captured["context"]
    assert context.extra["answer_mode"] == "guided"
    assert context.extra["allow_coach_only_tools"] is True
    assert context.extra["explicit_training_card_request"] is False
    assert context.extra["denied_tool_names"] == [
        "apply_patch",
        "edit_file",
        "write_file",
        "generate_training_card",
        "save_formal_plan",
        "record_learning_note",
        "import_resource_url",
        "organize_resources",
        "specify_task",
        "next_task",
    ]
    assert context.extra["current_file"]["path"] == "src/app.py"


@pytest.mark.asyncio
async def test_agentic_reply_keeps_coach_only_tools_off_in_direct_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile(answer_policy="direct")
    captured: dict[str, object] = {}

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "Direct reply.", "tool_calls": []}

    fake_provider = SimpleNamespace(protocol="openai_chat_completions", call=_fake_call, call_stream=None)

    class _FakeLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            captured["context"] = context
            captured["max_steps"] = max_steps

        async def run(self, messages: list[dict[str, object]]):
            captured["messages"] = messages
            return SimpleNamespace(
                final_content="Direct reply.",
                steps=[],
                summary=None,
                next_step=None,
                stop_reason="completed",
            )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _FakeLoop)

    reply = await service.coaching_reply_agentic(
        profile,
        "Give me the direct path.",
        answer_mode="direct",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
        },
    )

    assert reply["content"] == "Direct reply."
    context = captured["context"]
    assert context.extra["answer_mode"] == "direct"
    assert context.extra["allow_coach_only_tools"] is False


@pytest.mark.asyncio
async def test_agentic_reply_uses_calm_scaffold_when_agent_loop_returns_empty_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()
    empty_reply_scaffold = "Stay on the live thread and verify one visible move."

    async def _fake_call(_messages: list[dict[str, object]], _tools: list[dict[str, object]] | None) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(protocol="openai_chat_completions", call=_fake_call, call_stream=None)

    class _EmptyLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run(self, messages: list[dict[str, object]]):
            return SimpleNamespace(
                final_content="",
                steps=[],
                summary="The provider returned an empty visible answer.",
                next_step="Retry with a visible conclusion.",
                stop_reason="empty_response",
                resume_thread="Resume the live thread instead of restarting.",
            )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _EmptyLoop)
    monkeypatch.setattr(service, "_scaffold_reply", lambda *args, **kwargs: empty_reply_scaffold)
    monkeypatch.setattr(service, "_llm_reply", AsyncMock(return_value=""))

    reply = await service.coaching_reply_agentic(
        profile,
        "Continue the current thread.",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "practice verification",
        },
    )

    assert reply["fell_back"] is False
    assert reply["stop_reason"] == "empty_response"
    assert reply["content"] == empty_reply_scaffold
    assert "empty visible answer" not in reply["content"]
    assert reply["summary"] == "The provider returned an empty visible answer."
    assert reply["next_step"] == "Retry with a visible conclusion."
    assert reply["resume_thread"] == "Resume the live thread instead of restarting."


@pytest.mark.asyncio
async def test_agentic_reply_marks_guided_lane_empty_response_as_recovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(protocol="openai_chat_completions", call=_fake_call, call_stream=None)

    class _EmptyLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run(self, messages: list[dict[str, object]]):
            return SimpleNamespace(
                final_content="",
                steps=[],
                summary="The provider returned an empty visible answer.",
                next_step="Retry with a visible conclusion.",
                stop_reason="empty_response",
                resume_thread="Resume the live thread instead of restarting.",
            )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _EmptyLoop)
    monkeypatch.setattr(service, "_llm_reply", AsyncMock(return_value=""))

    reply = await service.coaching_reply_agentic(
        profile,
        "我在 VS Code Remote SSH 里分不清本地路径和 remote workspace。",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-remote",
            "session_id": "session-remote",
            "scenario": "remote_workspace",
        },
    )

    assert reply["stop_reason"] == "completed"
    assert reply["recovered_stop_reason"] == "empty_response"
    assert "VS Code remote" in reply["content"]
    assert "credential mode" in reply["content"]
    assert "VS Code remote" in reply["summary"]


@pytest.mark.asyncio
async def test_agentic_reply_uses_plain_reply_when_finalize_has_no_visible_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()
    direct_reply = (
        "闭包会记住创建它时的外层变量。"
        "外层函数结束后，内部函数仍能使用这些变量。"
        "它常用于封装状态和回调。"
    )

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(protocol="openai_chat_completions", call=_fake_call, call_stream=None)

    class _FinalizeWithoutVisibleReplyLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run(self, messages: list[dict[str, object]]):
            return SimpleNamespace(
                final_content="",
                steps=[],
                summary="metadata only",
                next_step="continue",
                stop_reason="coach_finalize",
                resume_thread=None,
            )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    plain_reply = AsyncMock(return_value=direct_reply)
    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _FinalizeWithoutVisibleReplyLoop)
    monkeypatch.setattr(service, "_llm_reply", plain_reply)

    reply = await service.coaching_reply_agentic(
        profile,
        "请用三句话解释 Python 闭包，不要问问题也不要下一步。",
        response_language="zh-CN",
        answer_mode="direct",
        coach_context={"__runtime__": object(), "workspace_id": "workspace-x", "session_id": "session-x"},
    )

    plain_reply.assert_awaited_once()
    assert reply["content"] == direct_reply
    assert reply["stop_reason"] == "completed"
    assert "Wrapping up." not in reply["content"]


def test_postprocess_first_turn_reply_stays_in_debug_lane_when_scenario_is_clear() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        (
            "Debugging should feel like one tight loop you can trust before you widen the lesson. "
            "We will stabilize the first breakpoint and verify one real value before changing more code."
        ),
        response_language="en-US",
        learner_message="Help me debug this in VS Code with one breakpoint and one observed value first.",
        scenario="debug_loop",
    )
    lowered = reply.lower()
    assert "which lane is closest" not in lowered
    assert "trustworthy debug loop" in lowered
    assert "where you will pause first" in lowered
    assert "single value, branch, or stack frame" in lowered


def test_postprocess_first_turn_reply_stays_in_remote_lane_when_scenario_is_clear() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        "Remote work gets easier once we stop mixing local assumptions with the actual workspace boundary.",
        response_language="en-US",
        learner_message="Teach me VS Code remote for SSH and dev container work without skipping the setup logic.",
        scenario="remote_workspace",
    )
    lowered = reply.lower()
    assert "which lane is closest" not in lowered
    assert "vs code remote lane" in lowered
    assert "minimal verification move" in lowered
    assert "explorer path" in lowered
    assert "remote host label" in lowered


def test_postprocess_first_turn_reply_stays_in_function_guidance_lane_when_scenario_is_clear() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        "We can understand this API faster if we anchor it to one live call site before the explanation drifts.",
        response_language="en-US",
        learner_message="Guide me through hover, signature help, and definition so I can understand this function.",
        scenario="function_guidance",
    )
    lowered = reply.lower()
    assert "which lane is closest" not in lowered
    assert "one live call site" in lowered
    assert "function contract stops moving" in lowered
    assert "function name and one call site" in lowered


def test_postprocess_first_turn_reply_anchors_function_guidance_to_current_file_selection() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        "We should learn this function from the code already on screen before we widen to a broader API explanation.",
        response_language="en-US",
        learner_message="Please teach me how to read this TypeScript function contract. Learn first, then give me a tiny try.",
        scenario="function_guidance",
        coach_context={
            "scenario": "function_guidance",
            "file_path": "src/demo.ts",
            "selection_range": "2:1-4:2",
            "selection_text": (
                "export async function fetchLesson(lessonId: string, policy: RetryPolicy): Promise<Response> {\n"
                "  return request(`/api/lessons/${lessonId}`, policy);\n"
                "}"
            ),
        },
    )
    assert "give me the function name" not in reply.lower()
    assert "src/demo.ts" in reply
    assert "fetchLesson" in reply
    assert "parameter contract" in reply
    assert "return contract" in reply


def test_postprocess_first_turn_reply_uses_trainer_owned_function_guidance_starter_when_available() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        "先从 `knowledge/function-guidance/typescript/src/usage.ts` 里的 `fetchJson` 看 call site，再跳到 `knowledge/function-guidance/typescript/src/client.ts`。",
        response_language="zh-CN",
        learner_message="请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
        scenario="function_guidance",
        coach_context={
            "scenario": "function_guidance",
            "function_guidance_starter": {
                "status": "ready",
                "language": "TypeScript",
                "call_site_path": "knowledge/function-guidance/typescript/src/usage.ts",
                "definition_path": "knowledge/function-guidance/typescript/src/client.ts",
                "call_site_symbol": "fetchJson",
                "definition_symbol": "fetchJson",
            },
        },
    )
    assert "给我函数名" not in reply
    assert "usage.ts" in reply
    assert "fetchJson" in reply
    assert reply.count("下一步") <= 1


def test_sanitize_agentic_visible_reply_recovers_function_guidance_lane_from_message_when_context_stays_general() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._sanitize_agentic_visible_reply(
        "先不急着把调试闭环讲完，我们先在一个真实 call site 上看 fetch options，再用 hover、signature help 和 definition 把 contract 读稳。",
        profile=_make_profile(),
        message="请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "scenario": "general",
            "history_mode": "fresh_lane",
            "relationship_stage": "active",
        },
    )
    reply_lower = reply.lower()
    assert "调试闭环" not in reply
    assert "debug loop" not in reply_lower
    assert "call site" in reply_lower
    assert "contract" in reply_lower


def test_visible_empty_reply_guidance_keeps_function_guidance_lane_on_plain_continue() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._visible_empty_reply_guidance(
        profile=_make_profile(),
        message="Continue.",
        response_language="en-US",
        answer_mode="guided",
        coach_context={
            "scenario": "function_guidance",
            "summary": "Read one function boundary instead of the whole module.",
            "thread_summary": "Read one function boundary instead of the whole module.",
            "thread_next_step": "Inspect the first call site and name one parameter contract.",
            "active_thread": {
                "scenario": "function_guidance",
                "focus_area": "signature help",
                "summary": "Read one function boundary instead of the whole module.",
                "next_step": "Inspect the first call site and name one parameter contract.",
            },
        },
    )
    lowered = reply.lower()
    assert "general coaching" not in lowered
    assert "function-guidance lane" in lowered
    assert "live call site" in lowered
    assert "what the function expects" in lowered
    assert "return in 2 short lines" in lowered


def test_visible_empty_reply_guidance_keeps_remote_lane_coach_like_on_plain_continue() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._visible_empty_reply_guidance(
        profile=_make_profile(),
        message="Continue.",
        response_language="en-US",
        answer_mode="guided",
        coach_context={
            "scenario": "remote_workspace",
            "summary": (
                "Re-establish the real workspace boundary before changing tools."
            ),
            "thread_summary": (
                "Re-establish the real workspace boundary before changing tools."
            ),
            "thread_next_step": (
                "Identify the workspace type and the safe credential mode."
            ),
            "active_thread": {
                "scenario": "remote_workspace",
                "focus_area": "remote boundary",
                "summary": (
                    "Re-establish the real workspace boundary before changing tools."
                ),
                "next_step": (
                    "Identify the workspace type and the safe credential mode."
                ),
            },
        },
    )
    lowered = reply.lower()
    assert "general coaching" not in lowered
    assert "remote work gets easier" in lowered
    assert "vs code remote lane" in lowered
    assert "safe credential mode" in lowered
    assert "return in 2 short lines" in lowered


def test_postprocess_first_turn_reply_keeps_idea_lane_concrete_without_generic_lane_prompt() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        "先把这个 idea 压成一个最小可运行切片，再用一个清楚的 success signal 去证明第一步已经落地。",
        response_language="zh-CN",
        learner_message="我想把一个小工具 idea 做出来，先陪我把第一个最小功能走通。",
        scenario="idea_implementation",
    )

    assert "告诉我现在更接近哪一类" not in reply
    assert "which lane is closest" not in reply.lower()
    assert "最小可运行切片" in reply
    assert "真实例子、片段或输入" in reply


def test_postprocess_first_turn_reply_keeps_concrete_writing_request_out_of_generic_lane_prompt() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        "We can improve this writing faster if we keep one audience, one paragraph goal, and one revision target in view.",
        response_language="en-US",
        learner_message="Help me revise an English project update paragraph without turning this into a full study plan.",
        scenario="general",
    )

    lowered = reply.lower()
    assert "which lane is closest" not in lowered
    assert "improve this writing faster" in lowered
    assert "one real example, snippet, or input" in lowered


def test_postprocess_first_turn_reply_keeps_concrete_word_request_out_of_generic_lane_prompt() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        "We can learn this word better by pinning it to one sentence you would actually use today.",
        response_language="en-US",
        learner_message="Teach me the word resilient with one sentence, one contrast, and one correction if I misuse it.",
        scenario="general",
    )

    lowered = reply.lower()
    assert "which lane is closest" not in lowered
    assert "learn this word better" in lowered
    assert "one real example, snippet, or input" in lowered


def test_timeout_recovery_override_for_general_non_code_request_returns_learn_first_step() -> None:
    reply = _build_timeout_recovery_override(
        "请先教我用配方法理解一元二次方程，不要一上来就考试我。",
        current_file=None,
        coach_context={
            "scenario": "general",
            "current_focus": "用配方法理解一元二次方程",
        },
        response_language="zh-CN",
    )

    next_step = str(reply["next_step"])
    assert any(token in next_step for token in ("解释", "例题", "推导"))
    assert "本地可见" not in next_step
    assert "Learn-first" in str(reply["reply"])
    assert "学习主线" in str(reply["summary"])


@pytest.mark.parametrize(
    ("active_view", "expected_summary", "expected_next_step"),
    [
        ("plan", "Plan 视图", "正式计划"),
        ("resources", "Resources 视图", "sources、knowledge、cards"),
        ("training", "Training 视图", "Learn -> Try -> Verify -> Reflect -> Return"),
    ],
)
def test_timeout_recovery_override_stays_view_specific_for_five_view_lanes(
    active_view: str,
    expected_summary: str,
    expected_next_step: str,
) -> None:
    reply = _build_timeout_recovery_override(
        "请继续这一轮。",
        current_file=None,
        coach_context={
            "scenario": "general",
            "active_view": active_view,
        },
        response_language="zh-CN",
    )

    assert expected_summary in str(reply["summary"])
    assert expected_next_step in str(reply["next_step"])
    assert "下一步：" in str(reply["reply"])


def test_timeout_recovery_override_prefers_training_view_over_remote_timeout_lane() -> None:
    reply = _build_timeout_recovery_override(
        "请给我一张关于 VS Code Remote SSH host ownership 的训练卡。",
        current_file=None,
        coach_context={
            "scenario": "remote_workspace",
            "active_view": "training",
        },
        response_language="zh-CN",
    )

    assert "Training 视图" in str(reply["summary"])
    assert "单卡" in str(reply["next_step"])
    assert "why now" in str(reply["next_step"])


@pytest.mark.parametrize(
    ("active_view", "field_kind", "value", "expected_token"),
    [
        ("plan", "summary", "先讲清当前 code 背后的机制，再扩大 patch 范围。", "Plan 视图"),
        ("resources", "next_step", "Reduce the explanation to one branch, one boundary, and one breakage.", "sources、knowledge、cards"),
        ("training", "next_step", "Reduce the explanation to one branch, one boundary, and one breakage.", "Learn -> Try -> Verify -> Reflect -> Return"),
    ],
)
def test_sanitize_agentic_continuity_text_reanchors_structured_views(
    active_view: str,
    field_kind: str,
    value: str,
    expected_token: str,
) -> None:
    repaired = _sanitize_agentic_continuity_text(
        value,
        scenario="principle",
        learner_message="请继续这一轮。",
        chinese=True,
        history_mode="fresh_lane",
        field_kind=field_kind,
        response_language="zh-CN",
        coach_context={"active_view": active_view},
    )

    assert expected_token in repaired


def test_postprocess_coaching_reply_reanchors_plan_view_from_stale_code_reply() -> None:
    service = ProviderService(api_key="sk-test")

    reply = service._postprocess_coaching_reply(  # noqa: SLF001
        "先讲清当前 code 背后的机制，再扩大 patch 范围。",
        profile=_make_profile(),
        message="继续。",
        response_language="zh-CN",
        coach_context={
            "active_view": "plan",
            "scenario": "principle",
            "execution_ready": True,
        },
    )

    assert "Plan 视图" in reply
    assert "下一步：" in reply
    assert "正式计划" in reply


def test_sanitize_agentic_visible_reply_reanchors_resources_view_from_stale_code_reply() -> None:
    service = ProviderService(api_key="sk-test")

    reply = service._sanitize_agentic_visible_reply(  # noqa: SLF001
        "先讲清当前 code 背后的机制，再扩大 patch 范围。",
        profile=_make_profile(),
        message="继续。",
        response_language="zh-CN",
        coach_context={
            "active_view": "resources",
            "scenario": "principle",
            "execution_ready": True,
        },
    )

    assert "Resources 视图" in reply
    assert "sources、knowledge、cards" in reply


def test_sanitize_agentic_visible_reply_keeps_training_reply_when_card_loop_is_already_clear() -> None:
    service = ProviderService(api_key="sk-test")
    source = "先学这张卡，再尝试写出 deliverable，然后用 verify method 自查，最后 return。"

    reply = service._sanitize_agentic_visible_reply(  # noqa: SLF001
        source,
        profile=_make_profile(),
        message="继续训练。",
        response_language="zh-CN",
        coach_context={
            "active_view": "training",
            "scenario": "general",
            "execution_ready": True,
        },
    )

    assert reply == source


def test_provider_error_recovery_override_for_general_non_code_request_returns_learn_first_step() -> None:
    reply = _build_provider_error_recovery_override(
        "Teach me the word resilient with one sentence and one contrast before any quiz.",
        current_file=None,
        coach_context={
            "scenario": "general",
            "current_focus": "the word resilient in one sentence",
        },
        response_language="en-US",
        error_detail="status 502",
    )

    next_step = str(reply["next_step"]).lower()
    assert "sentence" in next_step or "contrast" in next_step
    assert "local, visible, verifiable move" not in next_step
    assert "learn-first" in str(reply["reply"]).lower()
    assert "learning thread" in str(reply["summary"]).lower()


def test_postprocess_first_turn_reply_promises_continuity_in_chinese() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        "先从你的目标开始，再决定怎么推进。",
        response_language="zh-CN",
        learner_message="我想让你带我把一个现有项目改成我真正想要的样子。",
    )

    assert "告诉我现在更接近哪一类" not in reply
    assert "which lane is closest" not in reply.lower()
    assert "先从你的目标开始，再决定怎么推进" in reply
    assert "真实例子、片段或输入" in reply


@pytest.mark.parametrize(
    ("scenario", "expected_fragment", "expected_term"),
    [
        ("remote_workspace", "请用 2 行回复", "credential mode"),
        ("function_guidance", "请用 3 行回复", "函数名"),
    ],
)
def test_visible_empty_reply_guidance_matches_chinese_default_language_in_guided_lanes(
    scenario: str,
    expected_fragment: str,
    expected_term: str,
) -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._visible_empty_reply_guidance(
        profile=_make_profile(),
        message="继续。",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "scenario": scenario,
            "summary": "继续沿着同一条教学线往前走。",
            "thread_summary": "继续沿着同一条教学线往前走。",
            "thread_next_step": "返回当前这一步的最小可验证结论。",
            "active_thread": {
                "scenario": scenario,
                "focus_area": "guided lane",
                "summary": "继续沿着同一条教学线往前走。",
                "next_step": "返回当前这一步的最小可验证结论。",
            },
        },
    )
    assert expected_fragment in reply
    assert expected_term in reply


@pytest.mark.parametrize(
    ("scenario", "must_include"),
    [
        ("debug_loop", ("请用 2 行回复", "state change", "stack frame")),
        ("project_adaptation", ("请用 3 行回复", "必须保持不变", "第一条边界")),
    ],
)
def test_visible_empty_reply_guidance_covers_additional_guided_lanes_in_chinese(
    scenario: str,
    must_include: tuple[str, str, str],
) -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._visible_empty_reply_guidance(
        profile=_make_profile(),
        message="继续。",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "scenario": scenario,
            "summary": "继续沿着同一条教学线往前走。",
            "thread_summary": "继续沿着同一条教学线往前走。",
            "thread_next_step": "返回当前这一步的最小可验证结论。",
        },
    )
    for fragment in must_include:
        assert fragment in reply


def test_postprocess_coaching_reply_adds_remote_lane_continuity_when_visible_reply_is_generic() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        "Keep the reply visible and grounded in one small verified move.",
        profile=_make_profile(),
        message="Teach me the VS Code remote workflow for SSH and dev containers.",
        response_language="en-US",
        answer_mode="guided",
        coach_context={
            "scenario": "remote_workspace",
            "pace_signal": "steady",
        },
    )
    lowered = reply.lower()
    assert "vs code remote lane" in lowered
    assert "workspace boundary" in lowered
    assert "debug loop" not in lowered


def test_postprocess_coaching_reply_adds_function_lane_continuity_when_visible_reply_is_generic() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        "Keep the reply visible and grounded in one small verified move.",
        profile=_make_profile(),
        message="Guide me through function hints in VS Code on one real call site first.",
        response_language="en-US",
        answer_mode="guided",
        coach_context={
            "scenario": "function_guidance",
            "pace_signal": "steady",
        },
    )
    lowered = reply.lower()
    assert "live call site" in lowered
    assert "signature help" in lowered
    assert "credential mode" not in lowered


def test_postprocess_coaching_reply_strips_generic_lane_chooser_when_remote_scenario_is_clear() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "Before we get into a full step-by-step, let me anchor on the workspace boundary first.\n\n"
            "Tell me which lane is closest right now: implementing an idea, adapting a project, or shaping the training thread first."
        ),
        profile=_make_profile(),
        message="Teach me the VS Code remote workflow for SSH and dev containers.",
        response_language="en-US",
        answer_mode="guided",
        coach_context={
            "scenario": "remote_workspace",
        },
    )
    lowered = reply.lower()
    assert "workspace boundary" in lowered
    assert "which lane is closest right now" not in lowered


def test_postprocess_coaching_reply_strips_generic_lane_chooser_when_function_scenario_is_clear() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "Start from one live call site, then read the contract from hover and signature help.\n\n"
            "Tell me which lane is closest right now: implementing an idea, adapting a project, or shaping the training thread first."
        ),
        profile=_make_profile(),
        message="Guide me through function hints in VS Code on one real call site first.",
        response_language="en-US",
        answer_mode="guided",
        coach_context={
            "scenario": "function_guidance",
        },
    )
    lowered = reply.lower()
    assert "live call site" in lowered
    assert "which lane is closest right now" not in lowered


def test_postprocess_coaching_reply_strips_generic_lane_chooser_when_function_lane_is_inferred() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "What signature help actually is.\n\n"
            "Tell me which lane is closest right now: implementing an idea, adapting a project, or shaping the training thread first."
        ),
        profile=_make_profile(),
        message="Teach me function hints and signature help in VS Code before any quiz.",
        response_language="en-US",
        answer_mode="guided",
        coach_context=None,
    )
    lowered = reply.lower()
    assert "what signature help actually is" in lowered
    assert "which lane is closest right now" not in lowered


def test_postprocess_coaching_reply_strips_previous_lane_carryover_on_fresh_lane_switch() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "Glad you want to ground this on one real call site - that's the right instinct, and it fits where we already were with the debug loop.\n\n"
            "I will keep this anchored to one live call site, then use hover, signature help, and definition until the function contract stops moving."
        ),
        profile=_make_profile(),
        message="Guide me through function hints in VS Code on one real call site first.",
        response_language="en-US",
        answer_mode="guided",
        coach_context={
            "scenario": "function_guidance",
            "history_mode": "fresh_lane",
            "relationship_stage": "active",
            "current_focus": "function contract",
        },
    )
    lowered = reply.lower()
    assert "debug loop" not in lowered
    assert "live call site" in lowered
    assert "function contract" in lowered


def test_postprocess_coaching_reply_strips_keep_circling_cross_lane_carryover_on_fresh_lane_switch() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "Good - function guidance is the right lane to start in, and it's a great fit for the VS Code debug loop we keep circling.\n\n"
            "I will keep this anchored to one live call site, then use hover, signature help, and definition until the function contract stops moving."
        ),
        profile=_make_profile(),
        message="Guide me through function hints in VS Code on one real call site first.",
        response_language="en-US",
        answer_mode="guided",
        coach_context={
            "scenario": "function_guidance",
            "history_mode": "fresh_lane",
            "relationship_stage": "active",
            "current_focus": "function contract",
        },
    )
    lowered = reply.lower()
    assert "debug loop" not in lowered
    assert "keep circling" not in lowered
    assert "live call site" in lowered
    assert "function contract" in lowered


def test_postprocess_coaching_reply_strips_sentence_level_cross_lane_carryover_on_fresh_lane_switch_in_chinese() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "听起来你想从一个真实的调用点开始，先把“函数提示”这件事在 VS Code 里稳住，再去看 debug loop。"
            "这是对的顺序。\n\n"
            "我会先把函数理解锚定在一个 live call site 上，再用 hover、signature help 和 definition 把 contract 读稳。"
        ),
        profile=_make_profile(),
        message="请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "scenario": "function_guidance",
            "history_mode": "fresh_lane",
            "relationship_stage": "active",
            "current_focus": "function contract",
        },
    )
    lowered = reply.lower()
    assert "debug loop" not in lowered
    assert "live call site" in lowered
    assert "contract" in lowered


def test_postprocess_coaching_reply_strips_sentence_level_cross_lane_carryover_without_bridge_cue() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "If you can read one contract from one live call site, the bigger debug loop idea stops feeling abstract.\n\n"
            "Start with one live call site, then use hover and signature help until the function contract is stable."
        ),
        profile=_make_profile(),
        message="Guide me through function hints in VS Code on one real call site first.",
        response_language="en-US",
        answer_mode="guided",
        coach_context={
            "scenario": "function_guidance",
            "history_mode": "fresh_lane",
            "relationship_stage": "active",
            "current_focus": "function contract",
        },
    )
    lowered = reply.lower()
    assert "debug loop" not in lowered
    assert "live call site" in lowered
    assert "function contract" in lowered


def test_postprocess_coaching_reply_repairs_chinese_function_lane_when_debug_loop_lingers() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "先别急着铺开整套调试闭环，我们先在一个真实 call site 上看 fetch options，"
            "再用 hover、signature help 和 definition 把 contract 读稳。"
        ),
        profile=_make_profile(),
        message="请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "scenario": "function_guidance",
            "history_mode": "fresh_lane",
            "relationship_stage": "active",
            "current_focus": "function contract",
        },
    )
    lowered = reply.lower()
    assert "调试闭环" not in reply
    assert "debug loop" not in lowered
    assert "call site" in lowered
    assert "contract" in lowered


def test_postprocess_coaching_reply_repairs_function_lane_without_fresh_lane_metadata() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "好，咱们先把节奏放慢一点，定在一件很具体的小事上：你现在打开 VS Code，"
            "先别想整个调试闭环，而是找一个「真实的 call site」，把一个真实的函数先看透。 "
            "我会先把函数理解锚定在一个 live call site 上，再用 hover、signature help 和 definition 把 contract 读稳。"
        ),
        profile=_make_profile(),
        message="Guide me through function hints in VS Code on one real call site first.",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "scenario": "function_guidance",
            "relationship_stage": "active",
            "current_focus": "function contract",
        },
    )
    lowered = reply.lower()
    assert "调试闭环" not in reply
    assert "debug loop" not in lowered
    assert "call site" in lowered
    assert "contract" in lowered


def test_postprocess_coaching_reply_strips_debug_theory_preface_from_function_guidance_reply() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "好，我们先收住，不急着铺开「调试闭环」的全部理论。"
            "函数提示（hover、签名帮助、转到定义）最有用的地方，就是它能让你在一个真实的调用现场看到这个函数到底要什么。"
            "所以这一轮我们只做这一件小事：选一个真实的 call site。"
            "我会先把函数理解锚定在一个 live call site 上，再用 hover、signature help 和 definition 把 contract 读稳。"
        ),
        profile=_make_profile(),
        message="Guide me through function hints in VS Code on one real call site first.",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "scenario": "function_guidance",
            "relationship_stage": "active",
            "current_focus": "function contract",
        },
    )
    lowered = reply.lower()
    assert "调试闭环" not in reply
    assert "debug loop" not in lowered
    assert "call site" in lowered
    assert "contract" in lowered


def test_postprocess_coaching_reply_strips_remote_carryover_from_debug_loop_in_chinese() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "好，我们就从「一个断点 + 一个值」开始。先不去碰 SSH、tunnels、dev container 这些远端的东西，"
            "先把本地这条最小回路走通，因为远程场景下的 debug，本质上就是在这条回路外面再加一层“在哪台机器”的边界。\n\n"
            "我会先把这一轮收束成一个可信的 debug loop：先复现一次，在第一个有意义的 state change 停下，再检查一个值。"
        ),
        profile=_make_profile(),
        message="请先一步一步教我怎么在 VS Code 里 debug Python，再测试我。先从一个 breakpoint 和一个可验证的 value 开始。",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "scenario": "debug_loop",
            "history_mode": "fresh_lane",
            "relationship_stage": "active",
            "current_focus": "VS Code debug loop",
        },
    )
    lowered = reply.lower()
    assert "ssh" not in lowered
    assert "tunnels" not in lowered
    assert "dev container" not in lowered
    assert "远程场景" not in reply
    assert "debug loop" in lowered
    assert "state change" in lowered


def test_postprocess_coaching_reply_strips_remote_carryover_without_english_markers_in_debug_loop() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "好，我们先停在最小的一步上：今天只收束一个断点和一个值。先不去碰远程、容器这些边界。 "
            "我会先把这一轮收束成一个可信的 debug loop：先复现一次，在第一个有意义的 state change 停下，再检查一个值。"
        ),
        profile=_make_profile(),
        message="请先一步一步教我怎么在 VS Code 里 debug Python，再测试我。先从一个 breakpoint 和一个可验证的 value 开始。",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "scenario": "debug_loop",
            "history_mode": "fresh_lane",
            "relationship_stage": "active",
            "current_focus": "VS Code debug loop",
        },
    )
    lowered = reply.lower()
    assert "远程" not in reply
    assert "容器" not in reply
    assert "debug loop" in lowered
    assert "state change" in lowered


def test_postprocess_coaching_reply_strips_same_paragraph_remote_carryover_from_debug_loop_in_chinese() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_coaching_reply(
        (
            "先不动其他配置，也不急着讲远程工作区那些分支。"
            "我们先把这一轮收束成一个可信的 debug loop：先复现一次，在第一个有意义的 state change 停下，再检查一个值。"
        ),
        profile=_make_profile(),
        message="请先一步一步教我怎么在 VS Code 里 debug Python，再测试我。先从一个 breakpoint 和一个可验证的 value 开始。",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "scenario": "debug_loop",
            "history_mode": "fresh_lane",
            "relationship_stage": "active",
            "current_focus": "VS Code debug loop",
        },
    )
    lowered = reply.lower()
    assert "远程工作区" not in reply
    assert "那些分支" not in reply
    assert "debug loop" in lowered
    assert "state change" in lowered


def test_postprocess_first_turn_reply_recovers_function_lane_from_reply_when_inputs_are_sparse() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        (
            "Signature help becomes reliable once you anchor it to one live call site first.\n\n"
            "Function hints are only useful when you keep the contract tied to one definition and one call site."
        ),
        response_language="en-US",
        learner_message="",
        scenario=None,
    )
    lowered = reply.lower()
    assert "live call site" in lowered
    assert "function name and one call site" in lowered
    assert "which lane is closest right now" not in lowered


def test_postprocess_first_turn_reply_keeps_project_adaptation_compact_in_english() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        "Let's start from your goal before we choose a path.",
        response_language="en-US",
        learner_message="I want you to guide me while reshaping an existing project around my own intent.",
        scenario="project_adaptation",
    )
    lowered = reply.lower()
    assert "which lane is closest" not in lowered
    assert "existing-project lane" in lowered
    assert "must stay stable" in lowered
    assert "first boundary you want to adapt" in lowered


def test_postprocess_first_turn_reply_keeps_project_adaptation_compact_in_chinese() -> None:
    service = ProviderService(api_key="sk-test")
    reply = service._postprocess_first_turn_reply(
        "先从你的目标开始，再决定怎么推进。",
        response_language="zh-CN",
        learner_message="我想让你带我把一个现有项目改成我真正想要的样子。",
        scenario="project_adaptation",
    )
    assert "现有项目里哪些必须稳定" in reply
    assert "必须改变" in reply
    assert "第一道边界" in reply


@pytest.mark.parametrize(
    ("scenario", "expected_summary_fragment", "expected_step_fragment"),
    [
        ("remote_workspace", "VS Code remote lane", "SSH, tunnels, dev container, WSL, or local"),
        ("debug_loop", "VS Code debug lane", "single value, branch, or stack frame"),
        ("function_guidance", "function-guidance lane", "function name and one call site"),
        ("project_adaptation", "existing-project adaptation lane", "must stay stable"),
    ],
)
def test_language_corruption_copy_stays_lane_specific_in_english(
    scenario: str,
    expected_summary_fragment: str,
    expected_step_fragment: str,
) -> None:
    service = ProviderService(api_key="sk-test")

    summary = service.language_corruption_summary("en-US", scenario=scenario)
    next_step = service.language_corruption_next_step("en-US", scenario=scenario)
    reply = service.language_corruption_reply("en-US", scenario=scenario)

    assert "question marks" in summary
    assert expected_summary_fragment in summary
    assert "Switch provider or gateway" in next_step
    assert expected_step_fragment in next_step
    assert expected_step_fragment in reply


def test_language_corruption_copy_stays_lane_specific_in_chinese() -> None:
    service = ProviderService(api_key="sk-test")

    summary = service.language_corruption_summary("zh-CN", scenario="project_adaptation")
    next_step = service.language_corruption_next_step("zh-CN", scenario="project_adaptation")
    reply = service.language_corruption_reply("zh-CN", scenario="project_adaptation")

    assert "模型服务可以连接" in summary
    assert "existing-project adaptation" in summary
    assert "先切换 provider 或 gateway" in next_step
    assert "什么必须保持稳定" in next_step
    assert "provider" in reply
    assert "existing-project adaptation" in reply
    assert "什么必须保持稳定" in reply
    assert "为了避免误导你" in reply


def test_missing_api_key_reply_is_clear_in_chinese() -> None:
    service = ProviderService(api_key=None)

    reply = service._missing_api_key_reply("zh-CN")

    assert reply == "还没有设置可用的 API 密钥。请到设置里填写模型服务和密钥，然后就可以开始对话。"


def test_language_corruption_recovery_ignores_stale_remote_context_for_fresh_general_lane() -> None:
    override = _build_language_corruption_recovery_override(
        "Help me revise one English project update paragraph. Only fix this paragraph and keep it natural.",
        current_file=None,
        coach_context={
            "scenario": "general",
            "history_mode": "fresh_lane",
            "current_focus": "Switch provider or gateway, or continue this remote lesson in English first.",
            "summary": "I am still keeping this turn in the VS Code remote lane.",
            "thread_summary": "Teach me VS Code Remote SSH step by step.",
            "thread_next_step": "Tell me whether the workspace is SSH, tunnels, dev container, WSL, or local.",
        },
        response_language="en-US",
    )

    assert override is not None
    assert override["scenario"] == "general"
    assert "remote lane" not in str(override["reply"]).lower()
    assert "revise one sentence" in str(override["next_step"]).lower()


def test_language_corruption_recovery_keeps_requested_remote_lane_on_fresh_lane() -> None:
    override = _build_language_corruption_recovery_override(
        "请先教我 VS Code Remote SSH 的第一个可验证 checkpoint。",
        current_file=None,
        coach_context={
            "scenario": "remote_workspace",
            "history_mode": "fresh_lane",
            "current_focus": "VS Code remote workspace boundary",
        },
        response_language="zh-CN",
    )

    assert override is not None
    assert override["scenario"] == "remote_workspace"
    assert "VS Code remote" in str(override["reply"])
    assert "真实的工作区标签或路径" in str(override["reply"])
    assert "安全 credential mode" in str(override["next_step"])


@pytest.mark.asyncio
async def test_agentic_reply_uses_plain_reply_before_empty_response_scaffold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()
    recovered_reply = "Start with one breakpoint, then inspect the branch value."

    async def _fake_call(_messages: list[dict[str, object]], _tools: list[dict[str, object]] | None) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(protocol="openai_chat_completions", call=_fake_call, call_stream=None)

    class _EmptyLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run(self, messages: list[dict[str, object]]):
            return SimpleNamespace(
                final_content="",
                steps=[],
                summary="The provider returned an empty visible answer.",
                next_step="Retry with a visible conclusion.",
                stop_reason="empty_response",
                resume_thread="Resume the live thread instead of restarting.",
            )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    plain_reply = AsyncMock(return_value=recovered_reply)
    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _EmptyLoop)
    monkeypatch.setattr(service, "_llm_reply", plain_reply)

    reply = await service.coaching_reply_agentic(
        profile,
        "Help me stabilize this VS Code debug loop.",
        response_language="en-US",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "debug verification",
        },
    )

    plain_reply.assert_awaited_once()
    assert reply["content"] == recovered_reply
    assert reply["stop_reason"] == "completed"
    assert reply["fell_back"] is False
    assert "debug" in reply["summary"].lower()
    assert str(reply["next_step"]).strip()
    assert "empty visible answer" not in reply["content"]


@pytest.mark.asyncio
async def test_agentic_reply_uses_one_plain_recovery_after_an_empty_agent_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()
    captured_messages: list[list[dict[str, object]]] = []

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(protocol="openai_chat_completions", call=_fake_call, call_stream=None)

    class _RecoveringLoop:
        call_count = 0

        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run(self, messages: list[dict[str, object]]):
            type(self).call_count += 1
            captured_messages.append(messages)
            if type(self).call_count == 1:
                return SimpleNamespace(
                    final_content="",
                    steps=[],
                    summary="The provider returned an empty visible answer.",
                    next_step="Retry with a visible conclusion.",
                    stop_reason="empty_response",
                    resume_thread="Resume the live thread instead of restarting.",
                )
            return SimpleNamespace(
                final_content=(
                    "\u5148\u786e\u8ba4 remote \u8fb9\u754c\uff0c\u518d\u8bfb\u4e00\u6761\u8def\u5f84\uff0c"
                    "\u6700\u540e\u4e0e VS Code \u7684\u5b9e\u9645\u72b6\u6001\u5bf9\u7167\u3002"
                ),
                steps=[],
                summary="remote boundary",
                next_step="read one path",
                stop_reason="completed",
                resume_thread=None,
            )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    plain_reply = AsyncMock(
        return_value="Start with one breakpoint, then record the value that changes first."
    )
    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _RecoveringLoop)
    monkeypatch.setattr(service, "_llm_reply", plain_reply)

    reply = await service.coaching_reply_agentic(
        profile,
        "Teach me the smallest VS Code debugging step.",
        response_language="en-US",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "debug target",
        },
    )

    plain_reply.assert_awaited_once()
    assert _RecoveringLoop.call_count == 1
    assert reply["stop_reason"] == "completed"
    assert reply["content"] == "Start with one breakpoint, then record the value that changes first."


@pytest.mark.asyncio
async def test_agentic_reply_recovers_grounded_resource_max_steps_with_plain_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()
    recovered_reply = "我已经根据 Resources 文档收束好了：首屏 promise 是先让用户能 trust、preview、convert 资料。"

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(protocol="anthropic_messages", call=_fake_call, call_stream=None)

    class _GroundedMaxStepsLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run(self, messages: list[dict[str, object]]):
            return SimpleNamespace(
                final_content="模型已经跑到步数上限，但还没有自然收束。",
                steps=[
                    SimpleNamespace(
                        index=0,
                        tool_calls=[{"name": "search_resources", "arguments": {"query": "first viewport promise"}}],
                        tool_results=[
                            {
                                "name": "search_resources",
                                "result": {"query": "first viewport promise", "hits": [{"title": "doc.md"}]},
                            }
                        ],
                    )
                ],
                summary="The model hit max steps before finishing.",
                next_step="Try again.",
                stop_reason="max_steps",
                resume_thread="Resume the live thread instead of restarting.",
            )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    plain_reply = AsyncMock(return_value=recovered_reply)
    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _GroundedMaxStepsLoop)
    monkeypatch.setattr(service, "_llm_reply", plain_reply)

    reply = await service.coaching_reply_agentic(
        profile,
        "我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise。",
        response_language="zh-CN",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "resource grounding",
            "auto_resource_lookup": True,
        },
    )

    plain_reply.assert_awaited_once()
    assert reply["content"] == recovered_reply
    assert reply["stop_reason"] == "completed"
    assert reply["recovered_stop_reason"] == "max_steps"
    assert reply["fell_back"] is True
    assert "步数上限" not in reply["content"]


@pytest.mark.asyncio
async def test_agentic_reply_normalizes_unicode_punctuation_in_final_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()

    async def _fake_call(_messages: list[dict[str, object]], _tools: list[dict[str, object]] | None) -> dict[str, object]:
        return {"content": "Good call \u2014 start here\u2026", "tool_calls": []}

    fake_provider = SimpleNamespace(protocol="openai_chat_completions", call=_fake_call, call_stream=None)

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)

    reply = await service.coaching_reply_agentic(
        profile,
        "Teach me the smallest next move.",
        response_language="en-US",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
        },
    )

    assert reply["content"] == "Good call - start here..."
    assert "\u2014" not in reply["content"]
    assert "\u2026" not in reply["content"]


@pytest.mark.asyncio
async def test_agentic_reply_blocks_visible_mixed_script_corruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {
            "content": (
                "Let's build one trustworthy debug loop before we zoom out. "
                "Place one breakpoint, then pau"
                "\u0431\u043d"
                " and inspect the value."
            ),
            "tool_calls": [],
        }

    fake_provider = SimpleNamespace(protocol="openai_chat_completions", call=_fake_call, call_stream=None)

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)

    reply = await service.coaching_reply_agentic(
        profile,
        "Help me stabilize this VS Code debug loop.",
        response_language="en-US",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
        },
    )
    failure = service.consume_last_reply_failure()

    assert failure is not None
    assert failure["error_category"] == "language_corruption"
    assert reply["stop_reason"] == "language_corruption_recovered"
    assert "local recovery scaffold" in reply["content"].lower()
    assert "\u0431\u043d" not in reply["content"]
    assert "visibly corrupted coaching reply" not in reply["content"]


def test_mixed_script_reply_corruption_detail_flags_unexpected_cjk_fragment_in_english() -> None:
    detail = _mixed_script_reply_corruption_detail(
        "Let's build one trustworthy debug loop before we zoom out. Debugging\u95c2? Keep the first breakpoint small.",
        message="Help me debug Python in VS Code through one verified step.",
    )
    assert detail is not None
    assert "unexpected CJK fragments" in detail


def test_mixed_script_reply_corruption_detail_flags_full_wrong_language_reply_in_english() -> None:
    detail = _mixed_script_reply_corruption_detail(
        "我们先把这个英语写作任务压到一句话上，再看 tone 和 meaning 的区别。",
        message="Help me revise one English project update paragraph and keep the reply in English.",
        response_language="en-US",
    )
    assert detail is not None
    assert "wrong language" in detail


def test_mixed_script_reply_corruption_detail_allows_requested_chinese_reply() -> None:
    detail = _mixed_script_reply_corruption_detail(
        (
            "很高兴你把这个主题拉进来，我们先把远程工作区这件事拆成一个真实可验证的小目标。\n\n"
            "我会继续把这一轮留在 VS Code remote 这条线上：先确认工作区边界和文件实际在哪台机器上，"
            "再决定 credential mode。\n\n"
            "下一步：告诉我当前工作区是 SSH、tunnels、dev container、WSL 还是 local，"
            "再给我一个你能看到的真实路径或主机标签。"
        ),
        message="Teach me the VS Code remote workflow for SSH and dev containers.",
        response_language="zh-CN",
    )
    assert detail is None


@pytest.mark.asyncio
async def test_agentic_reply_backfills_completion_metadata_from_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {
            "content": "Start with the current file and keep the patch tiny.",
            "tool_calls": [],
        }

    fake_provider = SimpleNamespace(protocol="openai_chat_completions", call=_fake_call, call_stream=None)

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)

    reply = await service.coaching_reply_agentic(
        profile,
        "Give me the smallest next step.",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "summary": "General reminder prose should stay separate.",
            "thread_summary": "tighten the recovery loop",
            "thread_next_step": "retry the smallest verified branch",
            "resume_hint": "Continue the live thread instead of restarting.",
        },
    )

    assert reply["stop_reason"] == "completed"
    assert reply["content"] == "Start with the current file and keep the patch tiny."
    assert reply["summary"] == "tighten the recovery loop"
    assert reply["next_step"] == "retry the smallest verified branch"


@pytest.mark.asyncio
async def test_agentic_stream_backfills_completion_metadata_from_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {
            "content": "Start with the current file and keep the patch tiny.",
            "tool_calls": [],
        }

    async def _fake_call_stream(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ):
        yield {"type": "delta", "delta": "Start with the current file and keep the patch tiny."}
        yield {
            "type": "final",
            "content": "Start with the current file and keep the patch tiny.",
            "tool_calls": [],
            "stop_reason": "stop",
        }

    fake_provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_fake_call,
        call_stream=_fake_call_stream,
    )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "Give me the smallest next step.",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "tighten the recovery loop",
            "next_step_hint": {"title": "retry the smallest verified branch"},
        },
    ):
        events.append(event)

    final = next(event for event in events if event["type"] == "final")
    assert final["content"] == "Start with the current file and keep the patch tiny."
    assert final["summary"] == "tighten the recovery loop"
    assert final["next_step"] == "retry the smallest verified branch"


@pytest.mark.asyncio
async def test_agentic_stream_marks_a_checked_direct_prefix_before_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()
    reply = (
        "Start with one observable fact in the current behavior, then write down the value that "
        "would prove the assumption wrong before widening the task."
    )

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": reply, "tool_calls": []}

    async def _fake_call_stream(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ):
        yield {"type": "delta", "delta": reply}
        yield {"type": "final", "content": reply, "tool_calls": [], "stop_reason": "stop"}

    fake_provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_fake_call,
        call_stream=_fake_call_stream,
    )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "Answer directly with the smallest next debugging step.",
        response_language="en-US",
        answer_mode="direct",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
        },
    ):
        events.append(event)

    text_event = next(event for event in events if event["type"] == "text")
    final_index = next(index for index, event in enumerate(events) if event["type"] == "final")
    text_index = events.index(text_event)
    final = events[final_index]

    assert text_event["safe_to_stream"] is True
    assert text_event["delta"] == reply[:-32]
    assert text_index < final_index
    assert final["content"] == reply


@pytest.mark.asyncio
async def test_agentic_stream_marks_a_checked_direct_prefix_before_final_for_zh_cn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()
    reply = (
        "先从当前调试主线里取一个可见信号，再把它写成下一步并带回证据，"
        "然后再决定是否扩展范围。"
    )

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": reply, "tool_calls": []}

    async def _fake_call_stream(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ):
        yield {"type": "delta", "delta": reply}
        yield {"type": "final", "content": reply, "tool_calls": [], "stop_reason": "stop"}

    fake_provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_fake_call,
        call_stream=_fake_call_stream,
    )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "请直接给我下一步。",
        response_language="zh-CN",
        answer_mode="direct",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
        },
    ):
        events.append(event)

    text_event = next(event for event in events if event["type"] == "text")
    final_index = next(index for index, event in enumerate(events) if event["type"] == "final")
    text_index = events.index(text_event)
    final = events[final_index]

    assert text_event["safe_to_stream"] is True
    assert text_event["delta"] == reply[:-24]
    assert text_index < final_index
    assert final["content"] == reply


@pytest.mark.asyncio
async def test_agentic_stream_blocks_visible_mixed_script_corruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "unused", "tool_calls": []}

    async def _fake_call_stream(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ):
        yield {"type": "delta", "delta": "Place one breakpoint, then pau"}
        yield {
            "type": "final",
            "content": "Place one breakpoint, then pau\u0431\u043d and inspect the value.",
            "tool_calls": [],
            "stop_reason": "stop",
        }

    fake_provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_fake_call,
        call_stream=_fake_call_stream,
    )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "Help me stabilize this VS Code debug loop.",
        response_language="en-US",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
        },
    ):
        events.append(event)

    failure = service.consume_last_reply_failure()
    final = next(event for event in events if event["type"] == "final")

    assert failure is not None
    assert failure["error_category"] == "language_corruption"
    assert final["stop_reason"] == "language_corruption_recovered"
    assert "local recovery scaffold" in str(final["content"]).lower()
    assert "\u0431\u043d" not in str(final["content"])
    assert "visibly corrupted coaching reply" not in str(final["content"])
    assert not any(event["type"] == "text" for event in events)


@pytest.mark.asyncio
async def test_agentic_reply_falls_back_with_continuity_when_loop_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test")
    profile = _make_profile()

    async def _fake_call(_messages: list[dict[str, object]], _tools: list[dict[str, object]] | None) -> dict[str, object]:
        return {"content": "unused", "tool_calls": []}

    fake_provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_fake_call,
        call_stream=None,
    )

    class _ExplodingLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run(self, messages: list[dict[str, object]]):
            raise RuntimeError("simulated agent loop crash")

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _ExplodingLoop)

    reply = await service.coaching_reply_agentic(
        profile,
        "Continue the current thread.",
        current_file={"path": "main.py", "language_id": "python", "content": "print('hi')"},
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "tighten the recovery loop",
            "next_step_hint": {"title": "retry the smallest verified branch"},
        },
    )

    assert reply["fell_back"] is True
    assert reply["stop_reason"] == "agent_error: RuntimeError"
    assert reply["summary"] == "tighten the recovery loop"
    assert reply["next_step"] == "retry the smallest verified branch"
    assert reply["resume_thread"] == "Resume the live thread around tighten the recovery loop. Next: retry the smallest verified branch"
    assert reply["content"].strip()


@pytest.mark.asyncio
async def test_agentic_reply_recovers_timeout_with_guided_lane_visible_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    profile = _make_profile()

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(protocol="anthropic_messages", call=_fake_call, call_stream=None)

    class _TimeoutLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run(self, messages: list[dict[str, object]]):
            return SimpleNamespace(
                final_content="This turn timed out before the provider could finish.",
                steps=[],
                summary="This turn timed out before the provider could finish.",
                next_step="Retry the same request.",
                stop_reason="timeout",
                resume_thread=None,
                teaching_note=None,
                blocker="step 0 timed out",
            )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _TimeoutLoop)

    reply = await service.coaching_reply_agentic(
        profile,
        "Teach me VS Code Remote SSH step by step before you test me.",
        response_language="en-US",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "VS Code remote boundary",
        },
    )

    assert reply["stop_reason"] == "timeout"
    assert reply["fell_back"] is True
    assert reply["summary"].startswith("The provider timed out before it could finish")
    assert "Remote work gets easier once the workspace boundary stops moving." in reply["content"]
    assert "timed out" not in reply["content"]


@pytest.mark.asyncio
async def test_agentic_reply_recovers_provider_error_with_function_guidance_visible_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    profile = _make_profile()

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(protocol="anthropic_messages", call=_fake_call, call_stream=None)

    class _ProviderErrorLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run(self, messages: list[dict[str, object]]):
            return SimpleNamespace(
                final_content="这一轮教练服务在中途断开了，但我们可以沿着同一条主线续回去。",
                steps=[],
                summary="这一轮教练服务在中途断开了，但我们可以沿着同一条主线续回去。",
                next_step="当前主线还是：function contract 判断。",
                stop_reason="provider_error",
                resume_thread=None,
                teaching_note=None,
                blocker="provider overloaded",
                error=(
                    "Anthropic Messages call failed (status 529): "
                    "the server cluster is currently under high load"
                ),
            )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    plain_reply = AsyncMock(return_value="plain fallback should not be used")
    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _ProviderErrorLoop)
    monkeypatch.setattr(service, "_llm_reply", plain_reply)

    reply = await service.coaching_reply_agentic(
        profile,
        "请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
        response_language="zh-CN",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "function contract 判断",
        },
    )

    plain_reply.assert_not_awaited()
    assert reply["stop_reason"] == "provider_error"
    assert reply["fell_back"] is True
    assert "function guidance" in str(reply["content"])
    assert "live call site" in str(reply["content"])
    assert "教练服务在中途断开了" not in str(reply["content"])
    assert "同一条主线续回去" not in str(reply["content"])


@pytest.mark.asyncio
async def test_no_api_key_with_current_file_uses_memory_and_review_context() -> None:
    service = ProviderService()
    profile = _make_profile()
    reply = await service.coaching_reply(
        profile,
        "Please review this startup issue",
        current_file=_make_rich_current_file(),
    )
    assert "cannot start working yet" in reply
    assert "Open Settings" in reply
    assert "I will help you reduce it one step further" in reply


@pytest.mark.asyncio
async def test_no_api_key_chinese_reply_stays_natural_and_stable() -> None:
    service = ProviderService()
    profile = _make_profile()
    reply = await service.coaching_reply(
        profile,
        "帮我继续看这个报错",
        current_file=_make_rich_current_file(),
        response_language="zh-CN",
    )
    assert "API 密钥" in reply
    assert "还没有设置可用" in reply
    assert "设置里" in reply
    assert "模型服务和密钥" in reply


@pytest.mark.asyncio
async def test_scaffold_reply_preserves_direct_mode_logic() -> None:
    service = ProviderService()
    profile = _make_profile(answer_policy="direct")
    reply = await service.coaching_reply(
        profile,
        "Explain how to patch this directly",
        current_file=_make_rich_current_file(),
        answer_mode="direct",
    )
    assert "cannot start working yet" in reply
    assert "Open Settings, save a provider, model, and API key" in reply


@pytest.mark.asyncio
async def test_scaffold_reply_changes_shape_for_concept_teaching() -> None:
    service = ProviderService()
    profile = _make_profile()
    reply = await service.coaching_reply(
        profile,
        "Teach me this concept through the current code, not abstract theory.",
        current_file=_make_rich_current_file(
            coaching_state={
                "scenario": "concept_teaching",
                "learner_signal": "uncertain",
                "summary": "Tie the concept to the current failing boundary.",
                "next_step": "Point at the first boundary and explain what fails there.",
            }
        ),
        coach_context={
            "scenario": "concept_teaching",
            "principle_note": {
                "current_principle": "Tie the concept to one boundary before abstracting.",
                "follow_up_exercise": "Explain the first failing boundary in app.py.",
                },
            },
        )
    assert "usable API key" in reply
    assert "Settings" in reply


@pytest.mark.asyncio
async def test_scaffold_reply_changes_shape_for_engineering_challenge() -> None:
    service = ProviderService()
    profile = _make_profile()
    reply = await service.coaching_reply(
        profile,
        "Give me a project-backed engineering challenge.",
        current_file=_make_rich_current_file(
            coaching_state={
                "scenario": "engineering_challenge",
                "learner_signal": "steady",
                "summary": "Keep the challenge tied to the current project.",
                "next_step": "Land the first thin slice in app.py.",
            }
        ),
        coach_context={
            "scenario": "engineering_challenge",
            "exercise_prompt": {
                "prompt": "Land one thin project-backed slice in app.py.",
                "success_signal": "One focused check passes.",
                },
            },
        )
    assert "usable API key" in reply
    assert "Settings" in reply


@pytest.mark.asyncio
async def test_scaffold_reply_keeps_project_adaptation_lane_and_review_rhythm_visible() -> None:
    service = ProviderService()
    profile = _make_profile()
    reply = await service.coaching_reply(
        profile,
        "Help me reshape this existing trainer without widening scope.",
        current_file=_make_rich_current_file(
            coaching_state={
                "scenario": "project_adaptation",
                "learner_signal": "steady",
                "summary": "Keep the migration thread attached to one visible boundary.",
                "next_step": "Split stable areas from changed interfaces before landing the first patch.",
            }
        ),
        coach_context={
            "scenario": "project_adaptation",
            "current_focus": "trainer adaptation lane",
            "review_rhythm": "2 follow-up reviews are ready or coming due soon.",
            "coach_defaults": {
                "working_set_mode": "focused",
                "review_cadence": "active",
            },
            "project_adaptation_guide": {
                "first_migration_step": "Split stable layers from the first interface that must change.",
            },
        },
    )
    lowered = reply.lower()
    assert "usable api key" in lowered
    assert "settings" in lowered


@pytest.mark.asyncio
async def test_scaffold_reply_for_principle_uses_principle_anchor_and_avoids_implementation_drift() -> None:
    service = ProviderService()
    profile = _make_profile()
    reply = await service.coaching_reply(
        profile,
        "Explain the principle behind this boundary first.",
        current_file=_make_rich_current_file(
            coaching_state={
                "scenario": "principle",
                "learner_signal": "curious",
                "summary": "Explain the mechanism before asking for a bigger patch.",
                "next_step": "Point at the first boundary and explain the concrete failure it prevents.",
            }
        ),
        coach_context={
            "scenario": "principle",
            "principle_note": {
                "current_principle": "Tie the rule to one code boundary before abstracting.",
                "follow_up_exercise": "Name the first boundary and the failure it prevents.",
            },
        },
        response_language="en-US",
    )
    lowered = reply.lower()
    assert "usable api key" in lowered
    assert "settings" in lowered


@pytest.mark.asyncio
async def test_scaffold_reply_for_project_sourcing_stays_in_discovery_mode() -> None:
    service = ProviderService()
    profile = _make_profile()
    reply = await service.coaching_reply(
        profile,
        "Help me find a realistic repo source for long-term coaching practice.",
        coach_context={
            "scenario": "project_sourcing",
            "current_focus": "training repo search",
            "project_sources": [
                {
                    "title": "FastAPI full-stack template",
                    "repo_hint": "github.com/example/fullstack-fastapi-template",
                }
            ],
            "review_rhythm": "Keep source selection lightweight until one repo is chosen.",
        },
        response_language="en-US",
    )
    lowered = reply.lower()
    assert "usable api key" in lowered
    assert "settings" in lowered


# 鈹€鈹€ coaching_reply: with API key (LLM mode) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


@pytest.mark.asyncio
async def test_calls_openai_chat_completion() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = "Great question! Let me guide you through this."
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(profile, "How do I create a FastAPI route?")
        assert reply == "Great question! Let me guide you through this."
        mock_client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_coaching_reply_falls_back_to_lowercase_model_candidate() -> None:
    config = ProviderConfig(
        name="mimo-provider",
        base_url="https://example.com/v1",
        api_key_ref="trainer.mimo",
        model="MiMo-V2.5",
    )
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = "Use a tiny route first."
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    async def create_side_effect(*, model: str, **_: object):
        if model == "MiMo-V2.5":
            raise Exception("Error code: 400 - {'error': {'message': 'Not supported model MiMo-V2.5'}}")
        return mock_response

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=create_side_effect)
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(profile, "How do I create a FastAPI route?")
        assert reply == "Use a tiny route first."
        assert mock_client.chat.completions.create.await_count >= 2


@pytest.mark.asyncio
async def test_coaching_reply_postprocesses_principle_reply_when_apply_now_is_missing() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = "先看这个边界背后的机制，它解释了为什么这里会出错。"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(
            profile,
            "请你解释这里的原理，但要能马上落地。",
            current_file=_make_rich_current_file(
                coaching_state={
                    "scenario": "principle",
                    "learner_signal": "curious",
                }
            ),
            response_language="zh-CN",
            coach_context={
                "scenario": "principle",
                "principle_notes": {
                    "current_principle": "先把规则钉在一处真实边界上。",
                    "why_it_matters": "这样不会把理解漂到抽象层，能直接服务当前修复",
                    "apply_now": "先指出 app.py 里第一个失败边界，再解释它为什么会错",
                    "source_asset_title": "Boundary-first explanation",
                },
            },
        )

    assert "它在这里重要，是因为" in reply
    assert "先指出 app.py 里第一个失败边界" in reply
    assert "Boundary-first explanation" in reply
    assert "先把这个原理落成动作" in reply


@pytest.mark.asyncio
async def test_coaching_reply_postprocesses_project_idea_with_first_step() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = "这个项目很适合拿来练工程判断，因为它已经有真实代码边界。"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(
            profile,
            "基于当前项目给我一个训练题。",
            current_file=_make_rich_current_file(
                coaching_state={
                    "scenario": "project_idea",
                    "learner_signal": "steady",
                }
            ),
            response_language="zh-CN",
            coach_context={
                "scenario": "project_idea",
                "project_entry_points": ["app.py"],
                "project_ideas": [
                    {
                        "title": "Startup recovery drill",
                        "why_now": "The startup branch is still unstable.",
                        "first_step": "先补 app.py 里启动分支的一处防线，再只跑一个聚焦检查",
                    }
                ],
            },
        )

    assert "先别把它讲成更大的计划" in reply
    assert "先补 app.py 里启动分支的一处防线" in reply


@pytest.mark.asyncio
async def test_coaching_reply_tightens_scope_after_repeated_failure() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = "我们可以把整个启动流程都重构一下，再顺便把相关模块一起整理。"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(
            profile,
            "继续帮我修这个启动问题。",
            current_file=_make_rich_current_file(),
            response_language="zh-CN",
            coach_context={
                "scenario": "review",
                "failing_checks": ["pytest"],
                "pace_signal": "fragile",
                "learning_outcomes": [
                    {
                        "concept": "startup wiring",
                        "outcome": "repeated_error",
                        "summary": "The same branch failed twice.",
                    }
                ],
            },
        )

    assert "先别扩范围" in reply
    assert "`pytest`" in reply
    assert "最小反馈链" in reply


@pytest.mark.asyncio
async def test_coaching_reply_postprocesses_success_signal_when_missing() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = "先把这条启动分支补起来，再跑一次聚焦检查。"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(
            profile,
            "继续带我做这个练习。",
            response_language="zh-CN",
            coach_context={
                "scenario": "idea_implementation",
                "exercise_prompt": {
                    "prompt": "先补启动分支，再做一次聚焦验证。",
                    "success_signal": "聚焦检查通过，并且你能说清这一步为什么足够证明判断。",
                },
            },
        )

    assert "这一步算过的信号是" in reply
    assert "聚焦检查通过" in reply


@pytest.mark.asyncio
async def test_coaching_reply_reuses_recalled_memory_when_reply_drifts() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = "我们可以直接把启动流程整体重做一遍，这样以后也更省事"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(
            profile,
            "继续帮我修启动恢复这条线。",
            response_language="zh-CN",
            coach_context={
                "scenario": "review",
                "recalled_coaching_memories": [
                    {
                        "title": "Verified startup recovery lane",
                        "lesson": "先把恢复动作压在一条已经验证过的分支里。",
                    }
                ],
                "failing_checks": ["pytest"],
            },
        )

    assert "之前已经验证过" in reply or "已经验证过的分支" in reply
    assert "先把恢复动作压在一条已经验证过的分支里" in reply


@pytest.mark.asyncio
async def test_coaching_reply_postprocessor_keeps_natural_chinese_when_reply_is_already_good() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = (
        "先别急着改太多。这个原理在这里重要，是因为它决定了启动分支为什么会错。"
        "你现在先指出 app.py 里第一个失败边界，再跑一次最小检查确认判断对不对。"
    )
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(
            profile,
            "请继续解释这个原理。",
            current_file=_make_rich_current_file(
                coaching_state={
                    "scenario": "principle",
                    "learner_signal": "curious",
                }
            ),
            response_language="zh-CN",
            coach_context={
                "scenario": "principle",
                "principle_notes": {
                    "why_it_matters": "它决定了启动分支为什么会错",
                    "apply_now": "指出 app.py 里第一个失败边界",
                },
            },
        )

    assert reply.count("你现在先") == 1
    assert "先别急着改太多" in reply
    assert "指出 app.py 里第一个失败边界" in reply


@pytest.mark.asyncio
async def test_coaching_reply_postprocessor_does_not_expand_good_english_start_with_reply() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = "Start with one thin boundary."
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(
            profile,
            "Help me implement the first thin slice of this feature.",
            response_language="en-US",
            coach_context={
                "review_rhythm": "Review rhythm: 1 review checkpoint(s) are due now. Start with 'new-workspace' by doing this next code move: Turn the repeated weakness in 'new-workspace' into one narrow patch with a visible check.",
            },
        )

    assert reply == "Start with one thin boundary."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected_snippet"),
    [
        (
            "Teach me VS Code Remote SSH step by step before you test me.",
            "SSH, tunnels, dev container, WSL, or local",
        ),
        (
            "Teach me how to debug Python in VS Code before you quiz me.",
            "state change",
        ),
        (
            "Teach me function hints and signature help in VS Code before any quiz.",
            "hover, signature help, and definition",
        ),
    ],
)
async def test_empty_reply_keeps_domain_specific_lane_locally(
    message: str,
    expected_snippet: str,
) -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = ""
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        reply = await service.coaching_reply(
            _make_profile(),
            message,
            response_language="en-US",
        )

    assert "without any visible coaching reply" not in reply
    assert expected_snippet in reply
    assert "Tell me which lane is closest right now" not in reply


@pytest.mark.asyncio
async def test_coaching_reply_threads_prior_history_into_model_messages() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = "Continue from that same boundary."
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(
            profile,
            "Keep going from the previous step.",
            history=[
                {"role": "user", "content": "I keep losing the thread on auth."},
                {"role": "assistant", "content": "Start with the login boundary first."},
            ],
        )

    assert reply == "Continue from that same boundary."
    request_messages = mock_client.chat.completions.create.await_args.kwargs["messages"]
    assert request_messages[0]["role"] == "system"
    assert request_messages[1] == {
        "role": "user",
        "content": "I keep losing the thread on auth.",
    }
    assert request_messages[2] == {
        "role": "assistant",
        "content": "Start with the login boundary first.",
    }
    assert request_messages[-1]["role"] == "user"
    assert str(request_messages[-1]["content"]).startswith(
        "Keep going from the previous step."
    )


@pytest.mark.asyncio
async def test_api_error_returns_user_friendly_message() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("Connection refused"))
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(profile, "Help me")
        assert "could not reach the model service" in reply
        assert "Connection refused" not in reply
        assert "Settings" in reply


@pytest.mark.asyncio
async def test_coaching_reply_records_structured_provider_failure_metadata() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Error code: 401 - {'error': {'message': 'Incorrect API key provided'}}")
        )
        mock_get_client.return_value = mock_client

        reply = await service.coaching_reply(_make_profile(), "Help me continue this thread.")
        failure = service.consume_last_reply_failure()

    assert "could not reach the model service" in reply
    assert failure is not None
    assert failure["error_category"] == "invalid_key_or_permission"
    assert failure["status_code"] == 401
    assert failure["retryable"] is False
    assert "Incorrect API key provided" not in failure["detail"]
    assert "Provider request failed" in failure["detail"]
    assert service.consume_last_reply_failure() is None


def test_provider_failure_reply_uses_visible_zh_fallback_with_detail() -> None:
    service = ProviderService(api_key="sk-test-key")

    reply = service.provider_failure_reply(
        "invalid_key_or_permission",
        "  Error code: 401 - Invalid token  ",
        "zh-CN",
    )

    assert reply.strip()
    assert "Trainer 当前卡在 provider path" in reply
    assert "API key 或 permission" in reply
    assert "Error code: 401 - Invalid token" not in reply
    assert "upstream response body redacted" in reply
    assert "下一步" in reply


@pytest.mark.parametrize(
    ("category", "expected_summary", "expected_next_step"),
    [
        (
            "invalid_key_or_permission",
            "API key",
            "重新测试连接",
        ),
        (
            "model_unsupported",
            "model name",
            "真正支持的 model name",
        ),
        (
            "language_corruption",
            "肉眼可见的乱码回复",
            "先切换 provider 或 gateway",
        ),
    ],
)
def test_provider_failure_copy_stays_readable_in_chinese(
    category: str,
    expected_summary: str,
    expected_next_step: str,
) -> None:
    service = ProviderService(api_key="sk-test-key")

    summary = service.provider_failure_summary(category, "zh-CN")
    next_step = service.provider_failure_next_step(category, "zh-CN")

    assert expected_summary in summary
    assert expected_next_step in next_step
    for text in (summary, next_step):
        assert "\ufffd" not in text
        assert "闂" not in text
        assert "鈧" not in text
        assert "鍏" not in text
        assert "杩" not in text
        assert "鐩" not in text
        assert "閳" not in text


def test_localized_text_keeps_zh_cn_when_chinese_fallback_is_mojibake() -> None:
    result = _localized_text(
        "Provider test failed. Check API key and protocol.",
        "provider \ue1ec\u9227\u95b8\u9420 API key",
        "zh-CN",
    )

    assert "\u4e2d\u6587\u63d0\u793a" in result
    assert "provider" in result
    assert "Provider test failed" not in result

@pytest.mark.asyncio
async def test_coaching_reply_blocks_visible_mixed_script_corruption() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    mock_choice = MagicMock()
    mock_choice.message.content = (
        "Glad you want to start with VS Code remote "
        "\u0431\u043a"
        " it's a great target because once the model clicks, debugging and run confi"
        "\u0431\u043d"
        " stay more stable."
    )
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        reply = await service.coaching_reply(
            _make_profile(),
            "I want to learn VS Code remote workflows first.",
            response_language="en-US",
        )
        failure = service.consume_last_reply_failure()
    assert failure is not None
    assert failure["error_category"] == "language_corruption"
    assert failure["status_code"] == 200
    assert failure["provider_reachable"] is True
    assert failure["model_supported"] is True
    assert "mixed-script fragments" in failure["detail"]
    assert reply == "I could not read that reply. Please send the same question again."
    assert "\u0431\u043a" not in reply
    assert "confi\u0431\u043d" not in reply


@pytest.mark.asyncio
async def test_coaching_reply_records_empty_response_override_for_guided_domain() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    mock_choice = MagicMock()
    mock_choice.message.content = ""
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        reply = await service.coaching_reply(
            _make_profile(),
            "Help me keep this VS Code debug loop stable.",
            response_language="en-US",
        )
        override = service.consume_last_reply_override()

    assert "VS Code debug loop" in reply
    assert override is not None
    assert override["stop_reason"] == "empty_response"
    assert override["summary"] == (
        "The provider returned no visible answer, so this turn stays in the VS Code debug lane."
    )
    assert override["next_step"] == (
        "Tell me where you will pause first and which single value, branch, or stack frame you expect to inspect there."
    )
    assert override["fell_back"] is True
    assert service.consume_last_reply_override() is None


@pytest.mark.asyncio
async def test_api_error_falls_back_to_local_coach_scaffold() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("Connection refused"))
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(
            profile,
            "Please review this startup issue",
            current_file=_make_rich_current_file(),
        )
        lowered = reply.lower()
        assert "could not reach the model service" in lowered
        assert "tighten the fastapi startup feedback loop" in lowered
        assert "the next move i recommend is this" in lowered
        assert "one step further" in lowered


@pytest.mark.asyncio
async def test_api_error_stream_falls_back_to_local_coach_scaffold_in_chinese() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("连接异常"))
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        chunks: list[str] = []
        async for chunk in service.coaching_reply_stream(
            profile,
            "帮我继续看这个报错",
            current_file=_make_rich_current_file(),
            response_language="zh-CN",
        ):
            chunks.append(chunk)
        reply = "".join(chunks)
        assert "这次没能连上模型服务" in reply
        assert "Á¬½ÓÒì³£" not in reply
        assert "本地恢复逻辑" not in reply
        assert "app.py" in reply
        assert "当前文件里还有" in reply
        assert "如果你一动手又卡住" in reply


@pytest.mark.asyncio
async def test_coaching_reply_stream_without_api_key_yields_scaffold_instead_of_raising() -> None:
    service = ProviderService()
    profile = _make_profile()

    chunks: list[str] = []
    async for chunk in service.coaching_reply_stream(
        profile,
        "帮我继续看这个报错",
        current_file=_make_rich_current_file(),
        response_language="zh-CN",
    ):
        chunks.append(chunk)

    reply = "".join(chunks)
    assert "API 密钥" in reply
    assert "设置里" in reply
    assert "app.py" in reply
    assert "当前文件里还有" in reply
    assert "如果你一动手又卡住" in reply


@pytest.mark.asyncio
async def test_agentic_stream_surfaces_recovery_continuity_on_loop_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    profile = _make_profile()

    async def _fake_call(_messages: list[dict[str, object]], _tools: list[dict[str, object]] | None) -> dict[str, object]:
        return {"content": "unused", "tool_calls": []}

    fake_provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_fake_call,
        call_stream=_unused_native_stream,
    )

    class _ExplodingLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run_stream(self, messages: list[dict[str, object]]):
            raise RuntimeError("simulated stream crash")
            if False:
                yield {}

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _ExplodingLoop)

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "Continue the current thread.",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "tighten the recovery loop",
            "next_step_hint": {"title": "retry the smallest verified branch"},
        },
    ):
        events.append(event)

    assert events[0]["type"] == "error"
    assert events[-1]["type"] == "final"
    assert events[-1]["stop_reason"] == "agent_error"
    assert "tighten the recovery loop" in str(events[-1]["summary"])
    assert "retry the smallest verified branch" in str(events[-1]["next_step"])
    assert events[-1]["resume_thread"] == (
        "Resume the live thread around tighten the recovery loop. "
        "Next: retry the smallest verified branch"
    )


@pytest.mark.asyncio
async def test_agentic_stream_surfaces_empty_final_summary_as_visible_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    profile = _make_profile()

    async def _fake_call(_messages: list[dict[str, object]], _tools: list[dict[str, object]] | None) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_fake_call,
        call_stream=_unused_native_stream,
    )

    class _EmptyStreamLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run_stream(self, messages: list[dict[str, object]]):
            yield {
                "type": "final",
                "content": "",
                "summary": "The provider returned an empty visible answer.",
                "next_step": "Retry with a visible conclusion.",
                "stop_reason": "empty_response",
            }

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _EmptyStreamLoop)
    monkeypatch.setattr(service, "_llm_reply", AsyncMock(return_value=""))

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "Continue the current thread.",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "practice verification",
        },
    ):
        events.append(event)

    assert events[-1]["type"] == "final"
    assert events[-1]["stop_reason"] == "empty_response"
    assert events[-1]["content"] == "The provider returned an empty visible answer."
    assert events[-1]["summary"] == "The provider returned an empty visible answer."
    assert events[-1]["next_step"] == "Retry with a visible conclusion."
    assert events[-1]["resume_thread"] == (
        "Resume the live thread around The provider returned an empty visible answer. "
        "Next: Retry with a visible conclusion."
    )


@pytest.mark.asyncio
async def test_agentic_stream_uses_plain_reply_before_empty_response_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    profile = _make_profile()
    recovered_reply = "Start by checking the remote boundary, then verify one real workspace path."

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_fake_call,
        call_stream=_unused_native_stream,
    )

    class _EmptyStreamLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run_stream(self, messages: list[dict[str, object]]):
            yield {
                "type": "final",
                "content": "",
                "summary": "The provider returned an empty visible answer.",
                "next_step": "Retry with a visible conclusion.",
                "stop_reason": "empty_response",
            }

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    plain_reply = AsyncMock(return_value=recovered_reply)
    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _EmptyStreamLoop)
    monkeypatch.setattr(service, "_llm_reply", plain_reply)

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "Teach me VS Code Remote SSH step by step before you test me.",
        response_language="en-US",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "remote boundary",
        },
    ):
        events.append(event)

    final = next(event for event in events if event["type"] == "final")

    plain_reply.assert_awaited_once()
    assert final["content"] == recovered_reply
    assert final["stop_reason"] == "completed"
    assert "remote" in str(final["summary"]).lower()
    assert str(final["next_step"]).strip()


@pytest.mark.asyncio
async def test_agentic_stream_uses_plain_reply_when_finalize_has_no_visible_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test-key")
    profile = _make_profile()
    direct_reply = (
        "闭包会记住创建它时的外层变量。"
        "外层函数结束后，内部函数仍能使用这些变量。"
        "它常用于封装状态和回调。"
    )

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_fake_call,
        call_stream=_unused_native_stream,
    )

    class _FinalizeWithoutVisibleReplyStreamLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run_stream(self, messages: list[dict[str, object]]):
            yield {"type": "tool_call", "id": "fin", "name": "coach_finalize", "arguments": {}}
            yield {
                "type": "tool_result",
                "id": "fin",
                "name": "coach_finalize",
                "ok": True,
                "result": {"final": True},
            }
            yield {
                "type": "final",
                "content": "",
                "summary": "metadata only",
                "next_step": "continue",
                "stop_reason": "coach_finalize",
            }

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    plain_reply = AsyncMock(return_value=direct_reply)
    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _FinalizeWithoutVisibleReplyStreamLoop)
    monkeypatch.setattr(service, "_llm_reply", plain_reply)

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "请用三句话解释 Python 闭包，不要问问题也不要下一步。",
        response_language="zh-CN",
        answer_mode="direct",
        coach_context={"__runtime__": object(), "workspace_id": "workspace-x", "session_id": "session-x"},
    ):
        events.append(event)

    final = next(event for event in events if event["type"] == "final")
    plain_reply.assert_awaited_once()
    assert final["content"] == direct_reply
    assert final["stop_reason"] == "completed"
    assert not any("Wrapping up." in str(event.get("delta") or "") for event in events)


@pytest.mark.asyncio
async def test_agentic_stream_uses_one_plain_recovery_after_an_empty_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    profile = _make_profile()
    captured_messages: list[list[dict[str, object]]] = []

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_fake_call,
        call_stream=_unused_native_stream,
    )

    class _RecoveringStreamLoop:
        run_count = 0

        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run_stream(self, messages: list[dict[str, object]]):
            yield {
                "type": "final",
                "content": "",
                "summary": "The provider returned an empty visible answer.",
                "next_step": "Retry with a visible conclusion.",
                "stop_reason": "empty_response",
            }

        async def run(self, messages: list[dict[str, object]]):
            type(self).run_count += 1
            captured_messages.append(messages)
            return SimpleNamespace(
                final_content="Learn: inspect the debug target. Try: set one breakpoint. Verify: record one value.",
                steps=[],
                summary="debug target",
                next_step="record one value",
                stop_reason="completed",
                resume_thread=None,
            )

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    plain_reply = AsyncMock(
        return_value="Learn: inspect the debug target. Try: set one breakpoint. Verify: record one value."
    )
    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _RecoveringStreamLoop)
    monkeypatch.setattr(service, "_llm_reply", plain_reply)

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "Teach a tiny VS Code debug loop before testing me.",
        response_language="en-US",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "debug target",
        },
    ):
        events.append(event)

    final = next(event for event in events if event["type"] == "final")

    plain_reply.assert_awaited_once()
    assert _RecoveringStreamLoop.run_count == 0
    assert final["stop_reason"] == "completed"
    assert final["content"].startswith("Learn: inspect the debug target")


@pytest.mark.asyncio
async def test_agentic_stream_recovers_grounded_resource_max_steps_with_plain_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    profile = _make_profile()
    recovered_reply = "我已经根据命中的资料收束好了：Resources 首屏 promise 是先让用户能 find、trust、preview、convert。"

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(
        protocol="anthropic_messages",
        call=_fake_call,
        call_stream=_unused_native_stream,
    )

    class _GroundedMaxStepsStreamLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run_stream(self, messages: list[dict[str, object]]):
            yield {
                "type": "tool_call",
                "name": "search_resources",
                "arguments": {"query": "first viewport promise"},
            }
            yield {
                "type": "tool_result",
                "name": "search_resources",
                "result": {"query": "first viewport promise", "hits": [{"title": "doc.md"}]},
            }
            yield {
                "type": "final",
                "content": "模型已经跑到步数上限，但还没有自然收束。",
                "summary": "The model hit max steps before finishing.",
                "next_step": "Try again.",
                "stop_reason": "max_steps",
            }

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    plain_reply = AsyncMock(return_value=recovered_reply)
    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _GroundedMaxStepsStreamLoop)
    monkeypatch.setattr(service, "_llm_reply", plain_reply)

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise。",
        response_language="zh-CN",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "resource grounding",
            "auto_resource_lookup": True,
        },
    ):
        events.append(event)

    final = next(event for event in events if event["type"] == "final")

    plain_reply.assert_awaited_once()
    assert final["content"] == recovered_reply
    assert final["stop_reason"] == "completed"
    assert final["recovered_stop_reason"] == "max_steps"
    assert final["fell_back"] is True
    assert "步数上限" not in str(final["content"])


@pytest.mark.asyncio
async def test_agentic_stream_recovers_timeout_with_guided_lane_visible_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    profile = _make_profile()

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(
        protocol="anthropic_messages",
        call=_fake_call,
        call_stream=_unused_native_stream,
    )

    class _TimeoutStreamLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run_stream(self, messages: list[dict[str, object]]):
            yield {
                "type": "final",
                "content": "This turn timed out before the provider could finish.",
                "summary": "This turn timed out before the provider could finish.",
                "next_step": "Retry the same request.",
                "stop_reason": "timeout",
            }

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    plain_reply = AsyncMock(return_value="plain fallback should not be used")
    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _TimeoutStreamLoop)
    monkeypatch.setattr(service, "_llm_reply", plain_reply)

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "Teach me how to debug Python in VS Code step by step before you test me.",
        response_language="en-US",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "debug target",
        },
    ):
        events.append(event)

    final = next(event for event in events if event["type"] == "final")

    plain_reply.assert_not_awaited()
    assert final["stop_reason"] == "timeout"
    assert final["fell_back"] is True
    assert final["summary"].startswith("The provider timed out before it could finish")
    assert "trustworthy VS Code debug loop" in str(final["content"])
    assert "timed out" not in str(final["content"])


@pytest.mark.asyncio
async def test_agentic_stream_recovers_provider_error_with_function_guidance_visible_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    profile = _make_profile()

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": "", "tool_calls": []}

    fake_provider = SimpleNamespace(
        protocol="anthropic_messages",
        call=_fake_call,
        call_stream=_unused_native_stream,
    )

    class _ProviderErrorStreamLoop:
        def __init__(self, *, provider: object, registry: object, context: object, max_steps: int) -> None:
            self.provider = provider
            self.registry = registry
            self.context = context
            self.max_steps = max_steps

        async def run_stream(self, messages: list[dict[str, object]]):
            yield {
                "type": "final",
                "content": "这一轮教练服务在中途断开了，但我们可以沿着同一条主线续回去。",
                "summary": "这一轮教练服务在中途断开了，但我们可以沿着同一条主线续回去。",
                "next_step": "当前主线还是：function contract 判断。",
                "stop_reason": "provider_error",
                "error": (
                    "Anthropic Messages call failed (status 529): "
                    "the server cluster is currently under high load"
                ),
            }

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    plain_reply = AsyncMock(return_value="plain fallback should not be used")
    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    monkeypatch.setattr("app.llm.agent_loop.CoachAgentLoop", _ProviderErrorStreamLoop)
    monkeypatch.setattr(service, "_llm_reply", plain_reply)

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
        response_language="zh-CN",
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-x",
            "session_id": "session-x",
            "current_focus": "function contract 判断",
        },
    ):
        events.append(event)

    final = next(event for event in events if event["type"] == "final")

    plain_reply.assert_not_awaited()
    assert final["stop_reason"] == "provider_error"
    assert final["fell_back"] is True
    assert "function guidance" in str(final["content"])
    assert "live call site" in str(final["content"])
    assert "教练服务在中途断开了" not in str(final["content"])
    assert "同一条主线续回去" not in str(final["content"])


@pytest.mark.asyncio
async def test_coaching_reply_stream_appends_postprocessed_suffix() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_chunk_1 = MagicMock()
    mock_chunk_1.choices = [MagicMock()]
    mock_chunk_1.choices[0].delta.content = "先看这个边界背后的机制。"

    async def async_iter():
        yield mock_chunk_1

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=async_iter())
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        chunks: list[str] = []
        async for chunk in service.coaching_reply_stream(
            profile,
            "请继续解释这个原理。",
            current_file=_make_rich_current_file(
                coaching_state={
                    "scenario": "principle",
                    "learner_signal": "curious",
                }
            ),
            response_language="zh-CN",
            coach_context={
                "scenario": "principle",
                "principle_notes": {
                    "why_it_matters": "它决定了启动分支为什么会错",
                    "apply_now": "指出 app.py 里第一个失败边界",
                    "source_asset_title": "Boundary-first explanation",
                },
            },
        ):
            chunks.append(chunk)

    reply = "".join(chunks)
    assert reply.startswith("先看这个边界背后的机制")
    assert "它决定了启动分支为什么会错" in reply
    assert "指出 app.py 里第一个失败边界" in reply
    assert "Boundary-first explanation" in reply
    assert "先把这个原理落成动作" in reply
    assert len(chunks) >= 2


# 鈹€鈹€ has_api_key property 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


def test_has_api_key_true() -> None:
    service = ProviderService(api_key="sk-test-key")
    assert service.has_api_key is True


def test_has_api_key_false() -> None:
    service = ProviderService()
    assert service.has_api_key is False


def test_has_api_key_false_empty_string() -> None:
    service = ProviderService(api_key="")
    assert service.has_api_key is False


# 鈹€鈹€ test() method 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


def test_provider_test_with_api_key() -> None:
    service = ProviderService()
    config = _make_config()
    mock_client = MagicMock()

    def completion_side_effect(*, messages: list[dict[str, str]], **_: object):
        last_user = messages[-1]["content"]
        mock_choice = MagicMock()
        mock_choice.message.content = _provider_test_reply_for_prompt(last_user, "pong")
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    mock_client.chat.completions.create.side_effect = completion_side_effect
    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=mock_client)):
        result = service.test(config, "sk-test-key")
        assert result.ok is True
        assert "reachable" in result.detail.lower()
        assert result.provider_reachable is True
        assert result.model_supported is True


def test_provider_test_strips_reasoning_from_preview() -> None:
    service = ProviderService()
    config = _make_config()
    mock_client = MagicMock()

    def completion_side_effect(*, messages: list[dict[str, str]], **_: object):
        last_user = messages[-1]["content"]
        mock_choice = MagicMock()
        if "provider ready" in last_user and "Reply with exactly: pong" not in last_user:
            mock_choice.message.content = "Provider ready."
        else:
            mock_choice.message.content = _provider_test_reply_for_prompt(
                last_user,
                "<think>internal notes only</think>",
            )
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    mock_client.chat.completions.create.side_effect = completion_side_effect
    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=mock_client)):
        result = service.test(config, "sk-test-key")

    assert result.ok is True
    assert "provider ready" in result.detail.lower()
    assert "<think>" not in result.detail
    assert all("<think>" not in item for item in result.diagnostics)
    assert any("retried with a visible-text probe" in item.lower() for item in result.diagnostics)


def test_provider_test_fails_when_both_compact_and_visible_text_probes_return_empty() -> None:
    service = ProviderService()
    config = _make_config()
    mock_client = MagicMock()

    def completion_side_effect(*, messages: list[dict[str, str]], **_: object):
        last_user = messages[-1]["content"]
        mock_choice = MagicMock()
        mock_choice.message.content = _provider_test_reply_for_prompt(
            last_user,
            "<think>internal notes only</think>",
        )
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    mock_client.chat.completions.create.side_effect = completion_side_effect
    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=mock_client)):
        result = service.test(config, "sk-test-key")

    assert result.ok is False
    assert result.error_category == "reasoning_leak"
    assert result.provider_reachable is True
    assert result.model_supported is True
    assert "no usable visible reply" in result.detail.lower()
    assert "internal notes only" not in (result.detail or "")
    assert all("internal notes only" not in item for item in result.diagnostics)


def test_provider_test_classifies_reasoning_content_without_leaking_it() -> None:
    service = ProviderService()
    config = _make_config()
    mock_client = MagicMock()

    def completion_side_effect(**_: object):
        mock_choice = MagicMock()
        mock_choice.message.content = ""
        mock_choice.message.reasoning_content = "private chain of thought"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    mock_client.chat.completions.create.side_effect = completion_side_effect
    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=mock_client)):
        result = service.test(config, "sk-test-key")

    assert result.ok is False
    assert result.error_category == "reasoning_leak"
    assert result.provider_reachable is True
    assert result.model_supported is True
    assert "private chain of thought" not in (result.detail or "")
    assert all("private chain of thought" not in item for item in result.diagnostics)


def test_provider_test_without_api_key() -> None:
    service = ProviderService()
    config = _make_config()
    result = service.test(config, None)
    assert result.ok is False
    assert result.error_category == "missing_api_key"
    assert "no api key" in result.detail.lower() or "cannot work until you add one" in result.detail.lower()


def test_provider_test_reports_invalid_key_from_chat_probe() -> None:
    config = _make_config()
    service = ProviderService()
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = Exception(
        "Error code: 401 - {'error': {'message': 'Incorrect API key provided'}}"
    )

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test")

    assert result.ok is False
    assert result.error_category == "invalid_key_or_permission"
    assert result.provider_reachable is True
    assert all("Incorrect API key" not in item for item in result.diagnostics)
    assert any("Provider request failed" in item for item in result.diagnostics)


def test_provider_test_reports_model_unsupported_when_chat_probe_rejects_model() -> None:
    config = _make_config()
    service = ProviderService()
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = Exception(
        "Error code: 400 - {'error': {'message': 'Not supported model gpt-4o-mini'}}"
    )

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test")

    assert result.ok is False
    assert result.error_category == "model_unsupported"
    assert result.provider_reachable is True
    assert result.model_supported is False


def test_provider_test_reports_model_not_found_when_gateway_has_no_available_channel() -> None:
    config = _make_config()
    service = ProviderService()
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = Exception(
        "Error code: 503 - {'error': {'message': 'No available channel for model gpt-4o-mini under group default'}}"
    )

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=fake_client)):
        result = service.test(config, "sk-test")

    assert result.ok is False
    assert result.error_category == "model_not_found"
    assert result.provider_reachable is True
    assert result.model_supported is False


# 鈹€鈹€ chat_completion 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


@pytest.mark.asyncio
async def test_chat_completion_no_api_key() -> None:
    service = ProviderService()
    with pytest.raises(RuntimeError, match="API key not configured"):
        await service.chat_completion([{"role": "user", "content": "Hello"}])


@pytest.mark.asyncio
async def test_chat_completion_with_api_key() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = "Hello there!"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await service.chat_completion([{"role": "user", "content": "Hello"}])
        assert result == "Hello there!"


@pytest.mark.asyncio
async def test_chat_completion_appends_v1_for_non_google_gemini_gateway_without_version_path() -> None:
    config = ProviderConfig(
        name="minimax-gemini-compatible",
        base_url="https://gateway.example.com",
        api_key_ref="trainer.gateway",
        model="MiniMax-M3",
        protocol="gemini_generate_content",
    )
    service = ProviderService(config=config, api_key="sk-test-key")
    captured: dict[str, object] = {}

    fake_choice = MagicMock()
    fake_choice.message.content = "pong"
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]

    class _FakeAsyncCompletions:
        async def create(self, **kwargs: object) -> object:
            captured["request"] = kwargs
            return fake_response

    class _FakeAsyncClient:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=_FakeAsyncCompletions())

    def _fake_async_openai_ctor(
        *,
        api_key: str,
        base_url: str | None,
        timeout: float,
        max_retries: int,
    ) -> object:
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        captured["timeout"] = timeout
        captured["max_retries"] = max_retries
        return _FakeAsyncClient()

    with patch.object(service, "_get_async_openai_class", return_value=_fake_async_openai_ctor):
        result = await service.chat_completion([{"role": "user", "content": "Reply with exactly: pong"}])

    assert result == "pong"
    assert captured["api_key"] == "sk-test-key"
    assert captured["base_url"] == "https://gateway.example.com/v1"
    assert captured["timeout"] == DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS
    assert captured["max_retries"] == DEFAULT_OPENAI_CLIENT_MAX_RETRIES


# 鈹€鈹€ chat_completion_stream 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€


@pytest.mark.asyncio
async def test_chat_completion_stream_no_api_key() -> None:
    service = ProviderService()
    with pytest.raises(RuntimeError, match="API key not configured"):
        async for _chunk in service.chat_completion_stream([{"role": "user", "content": "Hello"}]):
            pass


@pytest.mark.asyncio
async def test_chat_completion_stream_with_api_key() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_chunk_1 = MagicMock()
    mock_chunk_1.choices = [MagicMock()]
    mock_chunk_1.choices[0].delta.content = "Hello"

    mock_chunk_2 = MagicMock()
    mock_chunk_2.choices = [MagicMock()]
    mock_chunk_2.choices[0].delta.content = " there"

    async def async_iter():
        yield mock_chunk_1
        yield mock_chunk_2

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=async_iter())
        mock_get_client.return_value = mock_client

        chunks: list[str] = []
        async for chunk in service.chat_completion_stream([{"role": "user", "content": "Hello"}]):
            chunks.append(chunk)
        assert chunks == ["Hello", " there"]


@pytest.mark.asyncio
async def test_chat_completion_stream_cancels_pending_upstream_stream_creation() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    creation_started = asyncio.Event()
    release_creation = asyncio.Event()

    async def _slow_create(**_: object) -> object:
        creation_started.set()
        await release_creation.wait()
        return object()

    with patch.object(service, "_get_client", return_value=SimpleNamespace()), patch.object(
        service,
        "_create_chat_completion",
        side_effect=_slow_create,
    ):
        cancel_event = asyncio.Event()
        stream = service.chat_completion_stream(
            [{"role": "user", "content": "Hello"}],
            cancel_event=cancel_event,
        )
        pending = asyncio.create_task(stream.__anext__())
        await asyncio.wait_for(creation_started.wait(), timeout=1)
        cancel_event.set()
        with pytest.raises(asyncio.CancelledError):
            await pending


@pytest.mark.asyncio
async def test_chat_completion_strips_reasoning_blocks() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = "<think>internal notes</think>Hello there!"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        result = await service.chat_completion([{"role": "user", "content": "Hello"}])

    assert result == "Hello there!"
    assert "<think>" not in result


@pytest.mark.asyncio
async def test_chat_completion_stream_strips_reasoning_blocks_across_chunks() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_chunk_1 = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="<th"))])
    mock_chunk_2 = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="ink>hidden</think>Hel"))])
    mock_chunk_3 = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="lo world"))])

    async def async_iter():
        yield mock_chunk_1
        yield mock_chunk_2
        yield mock_chunk_3

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=async_iter())
        mock_get_client.return_value = mock_client

        chunks: list[str] = []
        async for chunk in service.chat_completion_stream([{"role": "user", "content": "Hello"}]):
            chunks.append(chunk)

    assert "".join(chunks) == "Hello world"
    assert all("<think>" not in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_coaching_reply_strips_reasoning_blocks_before_postprocessing() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    profile = _make_profile()

    mock_choice = MagicMock()
    mock_choice.message.content = "<think>planning</think>Hello coach"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        reply = await service.coaching_reply(profile, "Help me continue.")

    assert reply == "Hello coach"
    assert "<think>" not in reply


def test_finalize_coaching_reply_strips_internal_meta_prefix_but_keeps_visible_remainder() -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test-key")
    profile = _make_profile()

    reply = service.finalize_coaching_reply(
        "Current coaching focus: Keep the remote boundary attached to one verified workspace path.",
        profile=profile,
        message="Continue the remote workspace thread.",
        response_language="en-US",
    )

    assert "Current coaching focus:" not in reply
    assert "Keep the remote boundary attached to one verified workspace path." in reply


def test_visible_agentic_final_event_strips_internal_meta_from_visible_fields() -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test-key")
    profile = _make_profile()

    final_event = service._visible_agentic_final_event(
        {
            "type": "final",
            "content": "Current coaching focus: Keep the remote boundary attached.",
            "summary": "Project implementation",
            "next_step": "Review rhythm: Re-open one workspace path.",
            "resume_thread": (
                "Resume the live thread around the verified remote boundary. "
                "Next: re-open one workspace path."
            ),
        },
        profile=profile,
        message="Continue the remote workspace thread.",
        current_file=None,
        response_language="en-US",
        answer_mode=None,
        coach_context={"current_focus": "remote boundary verification"},
        tool_events=[],
    )

    assert final_event["content"] == "Keep the remote boundary attached."
    assert "Project implementation" not in str(final_event["summary"])
    assert str(final_event["summary"]).strip()
    assert final_event["next_step"] == "Re-open one workspace path."
    assert "Resume the live thread around" not in str(final_event["resume_thread"])
    assert "workspace boundary" in str(final_event["resume_thread"])
    assert "minimal verification move" in str(final_event["resume_thread"])


def test_visible_agentic_final_event_repairs_function_guidance_generic_fallback() -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test-key")
    profile = _make_profile()

    final_event = service._visible_agentic_final_event(
        {
            "type": "final",
            "content": "Start with one live call site and keep the contract visible.",
            "summary": "Ignore secondary issues and only describe the first fix plus one verification.",
            "next_step": "Ignore secondary issues and only name the first fix plus one verification.",
            "resume_thread": (
                "Resume the live thread around the current function thread. "
                "Next: Ignore secondary issues and only name the first fix plus one verification."
            ),
        },
        profile=profile,
        message="Guide me through one TypeScript function by reading a live call site first.",
        current_file=None,
        response_language="en-US",
        answer_mode="guided",
        coach_context={"scenario": "function_guidance"},
        tool_events=[],
    )

    assert final_event["summary"] == (
        "I will keep this anchored to one live call site, then use hover, signature help, "
        "and definition until the function contract stops moving."
    )
    assert final_event["next_step"] == (
        "Next step: give me the function name and one call site you can open right now, "
        "and we will read the parameters, return value, and context from there."
    )
    assert final_event["resume_thread"] == (
        "I will keep this anchored to one live call site, then use hover, signature help, and "
        "definition until the function contract stops moving. Next: give me the function name "
        "and one call site you can open right now, and we will read the parameters, return "
        "value, and context from there."
    )


def test_visible_agentic_final_event_repairs_weak_remote_summary_in_chinese() -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test-key")
    profile = _make_profile()

    final_event = service._visible_agentic_final_event(
        {
            "type": "final",
            "content": "好的，我们先把 VS Code remote 的工作区边界看清楚。",
            "summary": "VS Code remote workspace",
            "next_step": "告诉我当前工作区是 SSH、tunnels、dev container、WSL 还是 local。",
            "resume_thread": (
                "回到同一条教练线程：VS Code remote workspace。 "
                "下一步：告诉我当前工作区是 SSH、tunnels、dev container、WSL 还是 local。"
            ),
        },
        profile=profile,
        message="请先一步一步教我 VS Code Remote SSH，再测试我。",
        current_file=None,
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={"scenario": "remote_workspace"},
        tool_events=[],
    )

    assert final_event["summary"] != "VS Code remote workspace"
    assert "VS Code remote" in str(final_event["summary"])
    assert "工作区边界" in str(final_event["summary"])
    assert "最小验证动作" in str(final_event["summary"])
    assert not str(final_event["resume_thread"]).startswith("回到同一条教练线程")
    assert str(final_event["resume_thread"]).count("下一步") == 1
    assert "工作区边界" in str(final_event["resume_thread"])


def test_visible_agentic_final_event_repairs_duplicate_next_step_prefix_in_chinese() -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test-key")
    profile = _make_profile()

    final_event = service._visible_agentic_final_event(
        {
            "type": "final",
            "content": "先从一个 live call site 读这个函数 contract。",
            "summary": "function guidance call site",
            "next_step": "下一步：给我函数名和一个你现在就能打开的 call site。",
            "resume_thread": (
                "回到同一条教练线程：function guidance call site。 "
                "下一步：下一步：给我函数名和一个你现在就能打开的 call site。"
            ),
        },
        profile=profile,
        message="请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
        current_file=None,
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={"scenario": "function_guidance"},
        tool_events=[],
    )

    assert final_event["summary"] != "function guidance call site"
    assert "live call site" in str(final_event["summary"])
    assert not str(final_event["resume_thread"]).startswith("回到同一条教练线程")
    assert "下一步：下一步：" not in str(final_event["resume_thread"])
    assert str(final_event["resume_thread"]).count("下一步") == 1


def test_visible_agentic_final_event_repairs_function_guidance_next_step_with_trainer_starter() -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test-key")
    profile = _make_profile()

    final_event = service._visible_agentic_final_event(
        {
            "type": "final",
            "content": "先从 `knowledge/function-guidance/typescript/src/usage.ts` 里的 `fetchJson` 看这个函数。",
            "summary": "function guidance call site",
            "next_step": "下一步：给我函数名和一个你现在就能打开的 call site。",
            "resume_thread": (
                "回到同一条教练线程：function guidance call site。 "
                "下一步：下一步：给我函数名和一个你现在就能打开的 call site。"
            ),
        },
        profile=profile,
        message="请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
        current_file=None,
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "scenario": "function_guidance",
            "function_guidance_starter": {
                "status": "ready",
                "language": "TypeScript",
                "call_site_path": "knowledge/function-guidance/typescript/src/usage.ts",
                "definition_path": "knowledge/function-guidance/typescript/src/client.ts",
                "call_site_symbol": "fetchJson",
                "definition_symbol": "fetchJson",
            },
        },
        tool_events=[],
    )

    assert "给我函数名" not in str(final_event["next_step"])
    assert "usage.ts" in str(final_event["next_step"])
    assert "client.ts" in str(final_event["next_step"])
    assert "给我函数名" not in str(final_event["resume_thread"])
    assert str(final_event["resume_thread"]).count("下一步") == 1


def test_visible_agentic_final_event_repairs_non_localized_function_next_step_in_chinese() -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test-key")
    profile = _make_profile()

    final_event = service._visible_agentic_final_event(
        {
            "type": "final",
            "content": "先从一个 live call site 读这个函数 contract。",
            "summary": "我会先把函数理解锚定在一个 live call site 上，再用 hover、signature help 和 definition 把 contract 读稳。",
            "next_step": "Verify this slice, then decide whether to widen.",
        },
        profile=profile,
        message="请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
        current_file=None,
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={"scenario": "function_guidance"},
        tool_events=[],
    )

    assert final_event["next_step"] != "Verify this slice, then decide whether to widen."
    assert "函数名" in str(final_event["next_step"])
    assert "call site" in str(final_event["next_step"])
    assert "Verify this slice" not in str(final_event["resume_thread"])


def test_visible_agentic_final_event_repairs_overlong_remote_next_step_in_chinese() -> None:
    service = ProviderService(config=_make_config(), api_key="sk-test-key")
    profile = _make_profile()

    final_event = service._visible_agentic_final_event(
        {
            "type": "final",
            "content": "先把 VS Code Remote SSH 的工作区边界看清楚。",
            "summary": "我会继续把这一轮留在 VS Code remote 这条线上：先确认工作区边界和文件实际在哪台机器上，再决定 credential move。",
            "next_step": (
                "先把你拉回到这一次的具体动作上：VS Code Remote SSH 这条线，我们最怕的就是一上来 wide-net "
                "试一堆配置，所以你先把当前工作区类型、主机标签、路径、连接方式、扩展状态和报错位置都给我讲一遍，再决定下一步。"
            ),
        },
        profile=profile,
        message="请先一步一步教我 VS Code Remote SSH，再测试我。",
        current_file=None,
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={"scenario": "remote_workspace"},
        tool_events=[],
    )

    assert "工作区落点" in str(final_event["next_step"])
    assert any(
        marker in str(final_event["next_step"])
        for marker in ("Explorer", "`pwd`", "remote host")
    )
    assert len(str(final_event["next_step"])) < 120


@pytest.mark.asyncio
async def test_coaching_reply_stream_strips_reasoning_blocks() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")
    profile = _make_profile()

    mock_chunk_1 = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="<think>internal"))])
    mock_chunk_2 = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=" reasoning</think>Hello"))])
    mock_chunk_3 = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=" coach"))])

    async def async_iter():
        yield mock_chunk_1
        yield mock_chunk_2
        yield mock_chunk_3

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=async_iter())
        mock_get_client.return_value = mock_client

        chunks: list[str] = []
        async for chunk in service.coaching_reply_stream(profile, "Help me continue."):
            chunks.append(chunk)

    assert "".join(chunks) == "Hello coach"
    assert all("<think>" not in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_coaching_reply_does_not_reframe_execution_ready_turn_into_lane_selection() -> None:
    config = _make_config()
    service = ProviderService(config=config, api_key="sk-test-key")

    mock_choice = MagicMock()
    mock_choice.message.content = (
        "Start from `demo.py` and keep the scope tight.\n\n"
        "Your next move is to add one focused assertion for `add(-1, 1)` and run only that check.\n\n"
        "That has teaching value because it forces you to pin the behavior before you widen the function."
    )
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        profile = _make_profile()
        reply = await service.coaching_reply(
            profile,
            "Based on the current file and my goal, give me one very small next step with strong teaching value.",
            current_file={
                "path": "demo.py",
                "language_id": "python",
                "content": "def add(a, b):\n    return a + b\n",
                "diagnostics": [],
            },
            coach_context={
                "relationship_stage": "intake",
                "first_turn_priority": "orient, reassure, clarify learner goal and choose one coaching lane",
            },
        )

    lowered = reply.lower()
    assert "add one focused assertion" in lowered
    assert "teaching value" in lowered
    assert "which lane is closest" not in lowered
