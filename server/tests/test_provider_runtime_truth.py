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
async def test_coaching_reply_stream_recovers_from_truncated_output_without_exposing_it() -> None:
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
