from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.models import ProviderConfig, UserProfile
from app.llm.agent_binding import ProviderAgentBinding
from app.llm.provider_service import ProviderRuntimeResponseError, ProviderService


def _profile() -> UserProfile:
    return UserProfile(
        long_term_goal="Build a reliable trainer",
        background="Intermediate Python developer",
        weekly_hours=6,
        teaching_style="guided",
        answer_policy="guided",
    )


def _config(protocol: str = "openai_chat_completions") -> ProviderConfig:
    return ProviderConfig(
        name="runtime-truth-test",
        base_url="https://gateway.example.com/v1",
        api_key_ref="trainer.runtime-truth",
        model="test-model",
        protocol=protocol,
    )


def _openai_response(content: str | None, finish_reason: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _openai_response(None),
        (
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="<think>private internal trace sk-runtime-secret</think>",
                            reasoning_content="private internal trace sk-runtime-secret",
                        ),
                        finish_reason="stop",
                    )
                ]
            )
        ),
    ],
)
async def test_coaching_reply_uses_local_recovery_for_empty_or_reasoning_only_response(
    response: SimpleNamespace,
) -> None:
    service = ProviderService(config=_config(), api_key="sk-runtime-secret")
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))
    )

    with patch.object(service, "_get_client", return_value=client):
        reply = await service.coaching_reply(_profile(), "Help me choose one safe next step.")

    override = service.consume_last_reply_override()
    assert override is not None
    assert override["stop_reason"] == "empty_response"
    assert "sk-runtime-secret" not in reply
    assert "private internal trace" not in reply
    assert "sk-runtime-secret" not in str(override)
    assert "private internal trace" not in str(override)


@pytest.mark.asyncio
async def test_coaching_reply_rejects_truncated_visible_text() -> None:
    service = ProviderService(config=_config(), api_key="sk-runtime-secret")
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=_openai_response(
                        "partial answer that must not be coach-ready",
                        "length",
                    )
                )
            )
        )
    )

    with patch.object(service, "_get_client", return_value=client):
        reply = await service.coaching_reply(_profile(), "Help me choose one safe next step.")

    failure = service.peek_last_reply_failure()
    assert failure is not None
    assert failure["error_category"] == "truncated_or_empty"
    assert "partial answer that must not be coach-ready" not in reply
    assert "sk-runtime-secret" not in str(failure)


@pytest.mark.asyncio
async def test_responses_binding_rejects_openai_chat_shape_as_protocol_mismatch() -> None:
    service = ProviderService(config=_config("openai_responses"), api_key="sk-runtime-secret")
    client = SimpleNamespace(
        responses=SimpleNamespace(
            create=AsyncMock(
                return_value={
                    "choices": [
                        {
                            "message": {
                                "content": "do not surface this incompatible body",
                            }
                        }
                    ]
                }
            )
        )
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="openai_responses")

    with patch.object(service, "_get_client", return_value=client):
        with pytest.raises(ProviderRuntimeResponseError) as raised:
            await binding.build_agent_provider().call([{"role": "user", "content": "hello"}], None)

    error = raised.value
    assert error.provider_error_category == "protocol_mismatch"
    assert "do not surface this incompatible body" not in str(error)
    assert "sk-runtime-secret" not in str(error)


@pytest.mark.asyncio
async def test_openai_binding_rejects_truncated_visible_text() -> None:
    service = ProviderService(config=_config(), api_key="sk-runtime-secret")
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=_openai_response("partial visible answer", "length")
                )
            )
        )
    )
    binding = ProviderAgentBinding(provider_service=service)

    with patch.object(service, "_get_client", return_value=client):
        with pytest.raises(ProviderRuntimeResponseError) as raised:
            await binding.build_agent_provider().call([{"role": "user", "content": "hello"}], None)

    assert raised.value.provider_error_category == "truncated_or_empty"
    assert "partial visible answer" not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_openai_binding_retries_truncated_formal_plan_arguments(streaming: bool) -> None:
    config = _config().model_copy(update={"max_output_tokens": 6144})
    service = ProviderService(config=config, api_key="sk-runtime-secret")
    tool_name = "save_formal_plan"
    incomplete_args = '{"title":"An incomplete plan'
    complete_args = '{"title":"A complete plan","stages":[{"title":"Practice","goal":"Run a check"}]}'

    def tool_call(arguments: str) -> SimpleNamespace:
        return SimpleNamespace(
            index=0, id="plan-save", type="function",
            function=SimpleNamespace(name=tool_name, arguments=arguments),
        )

    def response(arguments: str, finish_reason: str) -> SimpleNamespace:
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=None, tool_calls=[tool_call(arguments)]),
            finish_reason=finish_reason,
        )])

    async def stream():
        yield SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=None, tool_calls=[tool_call(incomplete_args)]),
            finish_reason="length",
        )])

    create = AsyncMock(side_effect=[
        stream() if streaming else response(incomplete_args, "length"),
        response(complete_args, "tool_calls"),
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    binding = ProviderAgentBinding(provider_service=service, max_tokens=1024)
    provider = binding.build_agent_provider()
    messages = [{"role": "user", "content": "Save the plan I confirmed."}]
    tools = [{"type": "function", "function": {"name": tool_name}}]
    with patch.object(service, "_get_client", return_value=client):
        if streaming:
            events = [event async for event in provider.call_stream(messages, tools)]
            assert [event["type"] for event in events] == ["final"]
            result = events[0]
        else:
            result = await provider.call(messages, tools)
    assert result["tool_calls"] == [{"id": "plan-save", "name": tool_name, "arguments": complete_args}]
    first, retry = create.await_args_list
    assert first.kwargs["max_tokens"] == 1024
    assert retry.kwargs["max_tokens"] == 6144
    assert first.kwargs["messages"] == retry.kwargs["messages"]
    assert first.kwargs["tools"] == retry.kwargs["tools"]


@pytest.mark.asyncio
async def test_openai_binding_stream_does_not_emit_a_final_event_for_truncated_output() -> None:
    service = ProviderService(config=_config(), api_key="sk-runtime-secret")

    async def _stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="partial visible answer"),
                    finish_reason="length",
                )
            ]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=_stream())))
    )
    binding = ProviderAgentBinding(provider_service=service)
    events: list[dict[str, object]] = []

    with patch.object(service, "_get_client", return_value=client):
        with pytest.raises(ProviderRuntimeResponseError) as raised:
            async for event in binding.build_agent_provider().call_stream(
                [{"role": "user", "content": "hello"}],
                None,
            ):
                events.append(event)

    assert raised.value.provider_error_category == "truncated_or_empty"
    assert not any(event.get("type") == "final" for event in events)


@pytest.mark.asyncio
async def test_coaching_reply_stream_keeps_failed_retry_out_of_visible_output() -> None:
    service = ProviderService(config=_config(), api_key="sk-runtime-secret")

    async def _stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="partial visible answer"),
                    finish_reason="length",
                )
            ]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=[
            _stream(),
            _openai_response("second partial answer", "length"),
        ])))
    )

    with patch.object(service, "_get_client", return_value=client):
        chunks = [
            chunk
            async for chunk in service.coaching_reply_stream(
                _profile(),
                "Help me choose one safe next step.",
            )
        ]

    failure = service.peek_last_reply_failure()
    assert failure is not None
    assert failure["error_category"] == "truncated_or_empty"
    assert "partial visible answer" not in "".join(chunks)
    assert "second partial answer" not in "".join(chunks)
    assert client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(("partial", "should_retry"), [("Held prefix", True), ("Visible prefix " * 4, False)])
async def test_coaching_reply_stream_retries_truncation_only_before_visible_text(
    partial: str, should_retry: bool,
) -> None:
    service = ProviderService(config=_config(), api_key="sk-runtime-secret")

    async def _stream():
        yield SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=partial), finish_reason="length",
        )])

    complete = "A task horizon ends the task. A collection cutoff preserves the value estimate."
    create = AsyncMock(side_effect=[_stream(), _openai_response(complete)])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(service, "_get_client", return_value=client):
        chunks = [chunk async for chunk in service.coaching_reply_stream(
            _profile(), "How do task horizons differ from collection cutoffs?", response_language="en-US",
        )]

    visible = "".join(chunks)
    if should_retry:
        assert create.await_count == 2
        assert create.await_args_list[1].kwargs["max_tokens"] > create.await_args_list[0].kwargs["max_tokens"]
        assert visible.count(complete) == 1
        assert partial not in visible
        assert service.peek_last_reply_failure() is None
    else:
        assert create.await_count == 1
        assert complete not in visible
        assert service.peek_last_reply_failure()["error_category"] == "truncated_or_empty"


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "provider_limit", "expected_tokens"), [
    ("analyze", None, 4096),
    ("analyze", 1536, 1536),
    ("search", None, 1024),
])
async def test_resources_analysis_has_room_for_comparisons_within_provider_limit(
    mode: str, provider_limit: int | None, expected_tokens: int,
) -> None:
    config = _config().model_copy(update={"max_output_tokens": provider_limit})
    service = ProviderService(config=config, api_key="sk-runtime-secret")

    async def _stream():
        yield SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content="A complete research reply."), finish_reason="stop",
        )])

    create = AsyncMock(return_value=_stream())
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(service, "_get_client", return_value=client):
        async for _ in service.coaching_reply_stream(
            _profile(), "Compare these learning resources.",
            coach_context={"active_view": "resources", "resource_composer_intent": {"mode": mode}},
        ):
            pass
    assert create.await_args.kwargs["max_tokens"] == expected_tokens


def test_binding_http_error_redacts_upstream_body_and_credentials() -> None:
    service = ProviderService(config=_config("gemini_generate_content"), api_key="sk-runtime-secret")
    binding = ProviderAgentBinding(provider_service=service, protocol="gemini_generate_content")

    error = binding._http_failure(
        status_code=500,
        body='{"token":"sk-runtime-secret","detail":"private upstream body"}',
    )

    assert error.provider_error_category == "provider_error"
    assert "sk-runtime-secret" not in str(error)
    assert "private upstream body" not in str(error)
