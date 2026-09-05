from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.models import ProviderConfig, ProviderModelsResponse, UserProfile
from app.llm.prompts import build_coaching_messages
from app.llm.provider_service import (
    MIN_CONTEXT_OUTPUT_TOKENS,
    ContextBudgetExhaustedError,
    ProviderService,
)


def _profile() -> UserProfile:
    return UserProfile(
        long_term_goal="Build a dependable trainer",
        background="Intermediate Python developer",
        weekly_hours=6,
        teaching_style="guided",
        answer_policy="guided",
    )


def _token_limited_config(*, protocol: str = "openai_chat_completions") -> ProviderConfig:
    return ProviderConfig(
        name="token-limited-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.token-limited",
        model="selected-model",
        protocol=protocol,
        context_window_tokens=32_768,
        max_output_tokens=4_096,
        model_token_limits={
            "selected-model": {
                "contextWindowTokens": 8_192,
                "maxOutputTokens": 2_048,
            }
        },
        request_defaults={
            "maxOutputTokens": 9_999,
            "generationConfig": {"maxOutputTokens": 9_999},
        },
    )


def test_selected_model_limits_override_global_limits_and_request_defaults() -> None:
    service = ProviderService(config=_token_limited_config(), api_key="sk-test")

    assert service._configured_token_limits() == (8_192, 2_048)  # noqa: SLF001
    assert service._coaching_output_token_budget([{"role": "user", "content": "Explain one step."}]) == 2_048  # noqa: SLF001
    assert "maxOutputTokens" not in service._provider_request_defaults()  # noqa: SLF001
    assert "generationConfig" not in service._provider_request_defaults()  # noqa: SLF001


def test_context_budget_reduces_output_before_the_context_window_is_exhausted() -> None:
    config = ProviderConfig(
        name="small-context-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.small-context",
        model="small-context-model",
        context_window_tokens=1_024,
        max_output_tokens=900,
    )
    service = ProviderService(config=config, api_key="sk-test")
    messages = [{"role": "user", "content": "x" * 1_800}]

    budget = service._coaching_output_token_budget(messages)  # noqa: SLF001

    assert 1 <= budget < 900
    assert budget + service._estimate_request_input_tokens(messages) + 256 <= 1_024  # noqa: SLF001


def _small_context_config(*, context_window_tokens: int = 1_024) -> ProviderConfig:
    return ProviderConfig(
        name="small-context-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.small-context",
        model="small-context-model",
        context_window_tokens=context_window_tokens,
        max_output_tokens=512,
    )


@pytest.mark.asyncio
async def test_chat_request_compacts_history_before_sending_a_visible_reply_budget() -> None:
    service = ProviderService(config=_small_context_config(), api_key="sk-test")
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="A visible reply."))]
        )
    )
    original_messages = [
        {"role": "system", "content": "s" * 1_000},
        {"role": "assistant", "content": "a" * 1_000},
        {"role": "user", "content": "u" * 1_000},
    ]

    await service._create_chat_completion(  # noqa: SLF001
        client=fake_client,
        messages=original_messages,
        model="small-context-model",
        max_tokens=512,
    )

    _, payload = fake_client.chat.completions.create.call_args
    sent_messages = payload["messages"]
    assert payload["max_tokens"] >= MIN_CONTEXT_OUTPUT_TOKENS
    assert sum(len(str(item.get("content") or "")) for item in sent_messages) < sum(
        len(str(item.get("content") or "")) for item in original_messages
    )
    assert str(sent_messages[-1].get("role") or "") == "user"
    assert any(str(item.get("role") or "") == "assistant" for item in sent_messages) or len(sent_messages) < len(
        original_messages
    )


def test_context_compaction_shrinks_middle_history_before_dropping_the_latest_user() -> None:
    service = ProviderService(config=_small_context_config(context_window_tokens=1_024), api_key="sk-test")
    messages = [
        {"role": "system", "content": "Keep the language instruction."},
        {"role": "assistant", "content": "a" * 2_400},
        {"role": "user", "content": "Remember marker-ECONNREFUSED-锚点-7731 and continue."},
    ]

    compacted = service._compact_messages_for_context_budget(  # noqa: SLF001
        messages,
        desired_output_tokens=256,
        minimum_output_tokens=MIN_CONTEXT_OUTPUT_TOKENS,
        context_window_tokens=1_024,
    )

    assert compacted
    assert str(compacted[-1].get("role") or "") == "user"
    assert "ECONNREFUSED-锚点-7731" in str(compacted[-1].get("content") or "")
    assert sum(len(str(item.get("content") or "")) for item in compacted) < sum(
        len(str(item.get("content") or "")) for item in messages
    )


def test_context_compaction_retains_the_requested_language_instruction() -> None:
    service = ProviderService(config=_small_context_config(context_window_tokens=4_096), api_key="sk-test")
    message = "\u8bf7\u7528\u4e2d\u6587\u5e2e\u6211\u603b\u7ed3\uff1a" + "\u8be6\u7ec6\u80cc\u666f" * 1_800
    messages = build_coaching_messages(
        _profile(),
        message,
        response_language="zh-CN",
        answer_mode="direct",
    )

    prepared_messages, budget = service._prepare_context_budget(  # noqa: SLF001
        messages,
        prefer_configured_output=True,
    )

    prepared_system = next(item["content"] for item in prepared_messages if item["role"] == "system")
    assert prepared_messages is not messages
    assert "Respond in natural, stable Simplified Chinese." in prepared_system
    assert budget >= MIN_CONTEXT_OUTPUT_TOKENS


@pytest.mark.asyncio
async def test_unfit_chat_request_never_calls_upstream() -> None:
    service = ProviderService(config=_small_context_config(context_window_tokens=384), api_key="sk-test")
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock()

    with pytest.raises(ContextBudgetExhaustedError):
        await service._create_chat_completion(  # noqa: SLF001
            client=fake_client,
            messages=[
                {"role": "system", "content": "system context" * 1_000},
                {"role": "user", "content": "current input" * 1_000},
            ],
            model="small-context-model",
            max_tokens=512,
        )

    fake_client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_unfit_agent_binding_request_never_builds_an_upstream_call() -> None:
    service = ProviderService(config=_small_context_config(context_window_tokens=384), api_key="sk-test")

    with patch.object(service, "build_agent_provider") as build_agent_provider:
        with pytest.raises(ContextBudgetExhaustedError):
            await service._completion_via_agent_binding(  # noqa: SLF001
                [
                    {"role": "system", "content": "system context" * 1_000},
                    {"role": "user", "content": "current input" * 1_000},
                ],
                temperature=0.7,
                max_tokens=512,
                prefer_configured_output=True,
            )

    build_agent_provider.assert_not_called()


@pytest.mark.asyncio
async def test_agent_provider_wrapper_blocks_late_oversized_tool_history() -> None:
    service = ProviderService(config=_small_context_config(context_window_tokens=384), api_key="sk-test")
    original_call = AsyncMock(return_value={"content": "unexpected", "tool_calls": []})
    provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=original_call,
        call_stream=None,
    )
    binding = SimpleNamespace(_max_tokens=128)

    with patch(
        "app.llm.agent_binding.build_agent_provider_for",
        return_value=(provider, binding),
    ):
        guarded_provider, _ = service.build_agent_provider(messages=[])
        result = await guarded_provider.call(
            [
                {"role": "system", "content": "system context" * 1_000},
                {"role": "user", "content": "current input" * 1_000},
            ],
            [],
        )

    assert result == {"content": "", "tool_calls": []}
    original_call.assert_not_awaited()
    assert service._agent_provider_context_budget_exhausted(guarded_provider)  # noqa: SLF001


@pytest.mark.asyncio
async def test_coaching_reply_reports_context_budget_without_provider_failure() -> None:
    service = ProviderService(config=_small_context_config(context_window_tokens=384), api_key="sk-test")

    with patch.object(service, "_get_client") as get_client:
        reply = await service.coaching_reply(
            _profile(),
            "x" * 8_000,
            response_language="zh-CN",
        )

    assert "\u8fd9\u6b21\u5185\u5bb9\u592a\u957f" in reply
    get_client.assert_not_called()
    assert service.peek_last_reply_failure() is None
    assert service.peek_last_reply_override() == {
        "stop_reason": "context_budget_exhausted",
        "fell_back": False,
        "context_budget_exhausted": True,
    }


@pytest.mark.asyncio
async def test_coaching_stream_reports_context_budget_without_calling_upstream() -> None:
    service = ProviderService(config=_small_context_config(context_window_tokens=384), api_key="sk-test")

    with patch.object(service, "_get_client") as get_client:
        chunks = [
            chunk
            async for chunk in service.coaching_reply_stream(
                _profile(),
                "x" * 8_000,
                response_language="zh-CN",
            )
        ]

    assert "\u8fd9\u6b21\u5185\u5bb9\u592a\u957f" in "".join(chunks)
    get_client.assert_not_called()
    assert service.peek_last_reply_failure() is None
    assert service.peek_last_reply_override()["stop_reason"] == "context_budget_exhausted"


@pytest.mark.asyncio
async def test_agentic_paths_return_context_budget_status_without_fallback() -> None:
    service = ProviderService(config=_small_context_config(context_window_tokens=384), api_key="sk-test")

    with patch.object(service, "build_agent_provider") as build_agent_provider:
        reply = await service.coaching_reply_agentic(
            _profile(),
            "x" * 8_000,
            response_language="zh-CN",
        )
        events = [
            event
            async for event in service.coaching_reply_agentic_stream(
                _profile(),
                "x" * 8_000,
                response_language="zh-CN",
            )
        ]

    build_agent_provider.assert_not_called()
    assert reply["stop_reason"] == "context_budget_exhausted"
    assert reply["fell_back"] is False
    assert "\u8fd9\u6b21\u5185\u5bb9\u592a\u957f" in reply["content"]
    assert len(events) == 1
    assert events[0]["type"] == "final"
    assert events[0]["stop_reason"] == "context_budget_exhausted"
    assert events[0]["fell_back"] is False
    assert "\u8fd9\u6b21\u5185\u5bb9\u592a\u957f" in events[0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "provider_name",
        "model",
        "catalog_model",
        "catalog_metadata",
        "expected_context_window",
        "expected_max_output",
    ),
    (
        (
            "MiniMax",
            "MiniMax-M3",
            "minimax-m3",
            {"contextWindowTokens": 1_000_000, "maxOutputTokens": 16_384},
            1_000_000,
            16_384,
        ),
        (
            "Qwen",
            "Qwen2.5-72B-Instruct",
            "qwen2_5_72b_instruct",
            {"context_length": 131_072, "max_completion_tokens": 8_192},
            131_072,
            8_192,
        ),
        (
            "DeepSeek",
            "deepseek-chat",
            "deepseek_chat",
            {"input_token_limit": 64_000, "output_token_limit": 8_192},
            64_000,
            8_192,
        ),
        (
            "Ollama Llama",
            "Meta-Llama/Llama-3.3-70B-Instruct",
            "meta-llama/llama-3-3-70b-instruct",
            {"context_window": 131_072, "max_tokens": 8_192},
            131_072,
            8_192,
        ),
        (
            "vLLM Llama",
            "meta-llama/Llama-3.1-8B-Instruct",
            "meta-llama/llama-3.1-8b-instruct",
            {"max_model_len": 131_072, "max_new_tokens": 4_096},
            131_072,
            4_096,
        ),
    ),
)
async def test_openai_compatible_catalog_limits_control_final_chat_budget(
    provider_name: str,
    model: str,
    catalog_model: str,
    catalog_metadata: dict[str, int],
    expected_context_window: int,
    expected_max_output: int,
) -> None:
    class _ModelRecord:
        def __init__(self, model_id: str, **extra: object) -> None:
            self.id = model_id
            self.model_extra = extra

    config = ProviderConfig(
        name=provider_name,
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.catalog-limits",
        model=model,
        context_window_tokens=262_144,
        max_output_tokens=32_768,
        model_token_limits={},
        request_defaults={
            "max_tokens": 65_536,
            "extra_body": {"thinking": {"type": "enabled"}},
        },
    )
    catalog_service = ProviderService()
    catalog_client = MagicMock()
    catalog_client.models.list.return_value = [_ModelRecord(catalog_model, **catalog_metadata)]

    with patch.object(
        catalog_service,
        "_get_sync_openai_class",
        return_value=MagicMock(return_value=catalog_client),
    ):
        listed = catalog_service.list_models(config, "sk-test")

    assert listed.ok is True
    discovered_limit = listed.model_token_limits[catalog_model]
    assert discovered_limit.context_window_tokens == expected_context_window
    assert discovered_limit.max_output_tokens == expected_max_output

    saved_config = config.model_copy(update={"model_token_limits": listed.model_token_limits})
    service = ProviderService(config=saved_config, api_key="sk-test")
    chat_client = MagicMock()
    chat_client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Ready."))])
    )

    response, selected_model = await service._create_chat_completion(  # noqa: SLF001
        client=chat_client,
        messages=[{"role": "user", "content": "Reply with one short sentence."}],
        model=model,
        max_tokens=65_536,
    )

    assert response.choices[0].message.content == "Ready."
    assert selected_model.lower() == model.lower()
    _, payload = chat_client.chat.completions.create.call_args
    assert payload["max_tokens"] == expected_max_output
    assert payload["max_tokens"] < config.request_defaults["max_tokens"]
    expected_thinking = "disabled" if provider_name == "MiniMax" else "enabled"
    assert payload["extra_body"]["thinking"]["type"] == expected_thinking


@pytest.mark.asyncio
async def test_coaching_chat_request_uses_selected_model_output_limit() -> None:
    service = ProviderService(config=_token_limited_config(), api_key="sk-test")
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Keep this patch focused."))]
        )
    )

    with patch.object(service, "_get_client", return_value=fake_client):
        reply = await service.coaching_reply(_profile(), "Help me scope the next patch.")

    assert reply == "Keep this patch focused."
    _, kwargs = fake_client.chat.completions.create.call_args
    assert kwargs["max_tokens"] == 2_048


@pytest.mark.asyncio
async def test_coaching_chat_request_uses_global_output_limit_without_model_metadata() -> None:
    config = ProviderConfig(
        name="global-token-limited-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.global-token-limited",
        model="global-model",
        context_window_tokens=32_768,
        max_output_tokens=1_536,
        request_defaults={"maxOutputTokens": 9_999},
    )
    service = ProviderService(config=config, api_key="sk-test")
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Use the verified global limit."))]
        )
    )

    with patch.object(service, "_get_client", return_value=fake_client):
        reply = await service.coaching_reply(_profile(), "Keep this response within the configured limit.")

    assert reply == "Use the verified global limit."
    _, kwargs = fake_client.chat.completions.create.call_args
    assert kwargs["max_tokens"] == 1_536


@pytest.mark.parametrize(
    "protocol",
    (
        "openai_chat_completions",
        "openai_responses",
        "anthropic_messages",
        "gemini_generate_content",
    ),
)
def test_agent_bindings_receive_selected_model_output_limit_for_every_protocol(protocol: str) -> None:
    service = ProviderService(config=_token_limited_config(protocol=protocol), api_key="sk-test")

    _provider, binding = service.build_agent_provider(
        protocol=protocol,
        messages=[{"role": "user", "content": "Return a short visible reply."}],
    )

    assert binding._max_tokens == 2_048  # noqa: SLF001


def test_model_listing_does_not_report_an_unprobed_model_as_ready() -> None:
    config = _token_limited_config()
    service = ProviderService()
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = TimeoutError("gateway timeout")
    listed_models = ProviderModelsResponse(
        ok=True,
        detail="Fetched 1 models.",
        available_models=["selected-model"],
        resolved_model="selected-model",
        listed=True,
    )

    with (
        patch.object(service, "_create_sync_client", return_value=fake_client),
        patch.object(service, "list_models", return_value=listed_models),
    ):
        result = service.test(config, "sk-test")

    assert result.ok is False
    assert result.provider_reachable is True
    assert result.model_supported is False
    assert result.error_category == "model_not_tested"
    assert "did not verify a usable reply" in result.detail
