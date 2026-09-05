from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.models import CapabilityFlags, ProviderConfig
from app.llm.agent_binding import ProviderAgentBinding
from app.llm.provider_service import ProviderService


@pytest.mark.asyncio
async def test_anthropic_wire_thinking_overrides_legacy_budget() -> None:
    config = ProviderConfig(
        name="compatible-minimax",
        base_url="https://gateway.example/v1",
        api_key_ref="trainer.test",
        model="MiniMax-M3",
        protocol="anthropic_messages",
        request_defaults={
            "thinkingBudget": 2048,
            "thinking": {"type": "disabled"},
        },
    )
    service = ProviderService(config=config, api_key="test-only")
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    payload = binding._apply_anthropic_request_defaults({
        "model": config.model,
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 128,
    })

    assert payload["thinking"] == {"type": "disabled"}
    assert "budget_tokens" not in payload["thinking"]


@pytest.mark.asyncio
async def test_openai_wire_payload_keeps_defaults_for_stream_and_tools() -> None:
    config = ProviderConfig(
        name="compatible-provider",
        base_url="https://gateway.example/v1",
        api_key_ref="trainer.test",
        model="model-1",
        protocol="openai_chat_completions_compatible",
        request_defaults={
            "maxOutputTokens": 321,
            "extra_body": {"thinking": {"type": "disabled"}},
        },
    )
    service = ProviderService(config=config, api_key="test-only")
    response = MagicMock()
    response.choices = [SimpleNamespace(message=SimpleNamespace(content="visible"))]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    binding = ProviderAgentBinding(provider_service=service)

    with patch.object(service, "_get_client", return_value=client):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "hello"}],
            [{"type": "function", "name": "probe", "parameters": {"type": "object"}}],
        )

    assert result["content"] == "visible"
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["max_tokens"] == 321
    assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}
    assert kwargs["tools"][0]["function"]["name"] == "probe"


def _binding_with_defaults(protocol: str, defaults: dict[str, object]) -> ProviderAgentBinding:
    config = ProviderConfig(
        name=f"wire-{protocol}",
        base_url="https://gateway.example/v1",
        api_key_ref="trainer.test",
        model="wire-model",
        protocol=protocol,
        request_defaults=defaults,
    )
    return ProviderAgentBinding(
        provider_service=ProviderService(config=config, api_key="test-only"),
        protocol=protocol,
        temperature=0.2,
        max_tokens=128,
    )


def test_openai_responses_defaults_map_temperature_stop_and_reasoning() -> None:
    binding = _binding_with_defaults(
        "openai_responses",
        {
            "temperature": 0.4,
            "stopSequences": ["DONE"],
            "reasoningEffort": "high",
            "maxOutputTokens": 512,
            "serviceTier": "auto",
        },
    )
    payload = binding._apply_openai_responses_request_defaults(  # noqa: SLF001
        {"input": [], "temperature": 0.2, "max_output_tokens": 128}
    )
    assert payload["temperature"] == 0.4
    assert "stop" not in payload
    assert payload["reasoning"] == {"effort": "high"}
    assert payload["max_output_tokens"] == 512
    assert payload["service_tier"] == "auto"


def test_minimax_explicit_thinking_enabled_survives_request_defaults() -> None:
    config = ProviderConfig(
        name="MiniMax",
        base_url="https://api.minimaxi.com/v1",
        api_key_ref="trainer.test",
        model="MiniMax-M2.7",
        protocol="openai_chat_completions_compatible",
        capabilities=CapabilityFlags(
            chat=True,
            tools=False,
            streaming=False,
            vision=False,
            thinking=True,
        ),
        request_defaults={"extra_body": {"thinking": {"type": "enabled"}, "option": "keep"}},
    )
    service = ProviderService(config=config, api_key="test-only")
    payload = service._apply_request_defaults(
        {
            "model": config.model,
            "messages": [{"role": "user", "content": "hello"}],
            "extra_body": {"thinking": {"type": "enabled"}},
        },
        config,
    )
    assert payload["extra_body"]["thinking"] == {"type": "enabled"}
    assert payload["extra_body"]["option"] == "keep"
    assert "reasoning_effort" not in payload


def test_anthropic_defaults_map_native_aliases_and_explicit_thinking_wins() -> None:
    binding = _binding_with_defaults(
        "anthropic_messages",
        {
            "temperature": 0.3,
            "topP": 0.8,
            "topK": 12,
            "stopSequences": ["DONE"],
            "maxOutputTokens": 700,
            "thinkingBudget": 2048,
            "thinking": {"type": "disabled"},
        },
    )
    payload = binding._apply_anthropic_request_defaults(  # noqa: SLF001
        {"model": "wire-model", "messages": [], "max_tokens": 128}
    )
    assert payload["temperature"] == 0.3
    assert payload["top_p"] == 0.8
    assert payload["top_k"] == 12
    assert payload["stop_sequences"] == ["DONE"]
    assert payload["max_tokens"] == 700
    assert payload["thinking"] == {"type": "disabled"}


def test_raw_http_minimax_thinking_is_flattened_off_extra_body() -> None:
    from app.llm.provider_service import _flatten_minimax_thinking_for_raw_http

    provider = ProviderConfig(
        name="MiniMax",
        base_url="http://gateway.example/v1",
        api_key_ref="trainer.test",
        model="MiniMax-M3",
        protocol="anthropic_messages",
    )
    payload = _flatten_minimax_thinking_for_raw_http(
        {
            "model": "MiniMax-M3",
            "messages": [{"role": "user", "content": "hello"}],
            "extra_body": {"thinking": {"type": "disabled"}, "keep": "yes"},
        },
        provider,
    )
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["extra_body"] == {"keep": "yes"}
    assert "thinking" not in payload["extra_body"]


def test_raw_http_unknown_provider_does_not_invent_thinking() -> None:
    from app.llm.provider_service import _flatten_minimax_thinking_for_raw_http

    provider = ProviderConfig(
        name="unknown-gateway",
        base_url="https://llm.example/v1",
        api_key_ref="trainer.test",
        model="mystery-model",
        protocol="openai_chat_completions_compatible",
    )
    payload = {
        "model": "mystery-model",
        "extra_body": {"keep": "yes"},
    }
    assert _flatten_minimax_thinking_for_raw_http(payload, provider) == payload


def test_unknown_minimax_named_model_does_not_invent_thinking() -> None:
    from app.llm.provider_service import (
        _flatten_minimax_thinking_for_raw_http,
        _normalized_provider_request_defaults,
    )

    provider = ProviderConfig(
        name="MiniMax",
        base_url="http://minimax.redfast.top/v1",
        api_key_ref="trainer.test",
        model="mystery-custom-7b",
        protocol="openai_chat_completions_compatible",
        request_defaults={"extra_body": {"thinking": {"type": "enabled"}, "keep": "yes"}},
    )
    defaults = _normalized_provider_request_defaults(provider)
    extra_body = defaults.get("extra_body") or {}
    assert "thinking" not in extra_body
    assert extra_body.get("keep") == "yes"
    assert "thinking" not in defaults
    payload = {
        "model": "mystery-custom-7b",
        "extra_body": {"keep": "yes"},
    }
    flattened = _flatten_minimax_thinking_for_raw_http(payload, provider)
    assert "thinking" not in flattened
    assert flattened["extra_body"]["keep"] == "yes"


def test_confirmed_minimax_model_keeps_native_thinking_field() -> None:
    from app.llm.provider_service import _normalized_provider_request_defaults

    provider = ProviderConfig(
        name="MiniMax",
        base_url="http://minimax.redfast.top/v1",
        api_key_ref="trainer.test",
        model="MiniMax-M2.7",
        protocol="openai_chat_completions_compatible",
        capabilities=CapabilityFlags(chat=True, thinking=True),
        request_defaults={"extra_body": {"thinking": {"type": "enabled"}}},
    )
    defaults = _normalized_provider_request_defaults(provider)
    assert defaults["extra_body"]["thinking"] == {"type": "enabled"}
    assert "reasoning_effort" not in defaults


def test_anthropic_http_defaults_drop_nested_minimax_extra_body_thinking() -> None:
    config = ProviderConfig(
        name="MiniMax",
        base_url="http://gateway.example/v1",
        api_key_ref="trainer.test",
        model="MiniMax-M3",
        protocol="anthropic_messages",
        request_defaults={"extra_body": {"thinking": {"type": "disabled"}, "option": "keep"}},
    )
    binding = ProviderAgentBinding(
        provider_service=ProviderService(config=config, api_key="test-only"),
        protocol="anthropic_messages",
    )
    payload = binding._apply_anthropic_request_defaults(
        {
            "model": config.model,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 64,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
    )
    assert payload["thinking"] == {"type": "disabled"}
    assert payload.get("extra_body", {}).get("thinking") is None


def test_gemini_defaults_map_snake_and_camel_aliases_into_generation_config() -> None:
    binding = _binding_with_defaults(
        "gemini_generate_content",
        {
            "temperature": 0.5,
            "top_p": 0.7,
            "top_k": 9,
            "candidate_count": 2,
            "stop_sequences": ["DONE"],
            "max_output_tokens": 600,
        },
    )
    payload = binding._apply_gemini_request_defaults(  # noqa: SLF001
        {"contents": [], "generationConfig": {"temperature": 0.2}}
    )
    assert payload["generationConfig"] == {
        "temperature": 0.5,
        "topP": 0.7,
        "topK": 9,
        "candidateCount": 2,
        "stopSequences": ["DONE"],
        "maxOutputTokens": 600,
    }
