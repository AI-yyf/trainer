from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core.models import CapabilityFlags, ProviderConfig, ProviderTestResponse
from app.llm.provider_service import ProviderService, _visible_probe_max_tokens


def _tool_evidence(result: ProviderTestResponse):
    return next(item for item in result.capability_evidence if item.name == "tools")


def _vision_evidence(result: ProviderTestResponse):
    return next(item for item in result.capability_evidence if item.name == "vision")


def _openai_provider() -> ProviderConfig:
    return ProviderConfig(
        name="capability-truth",
        base_url="https://gateway.example.com/v1",
        api_key_ref="trainer.capability-truth",
        model="test-model",
        protocol="openai_chat_completions_compatible",
        capabilities=CapabilityFlags(
            chat=True,
            responses=False,
            embeddings=False,
            tools=True,
            streaming=False,
        ),
    )


def _vision_provider() -> ProviderConfig:
    return _openai_provider().model_copy(
        update={"capabilities": CapabilityFlags(chat=True, vision=True, tools=False, streaming=False)}
    )


def _openai_response(
    content: str | None,
    *,
    tool_calls: list[object] | None = None,
    reasoning_content: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    tool_calls=tool_calls or [],
                    reasoning_content=reasoning_content,
                ),
                finish_reason="tool_calls" if tool_calls else "stop",
            )
        ]
    )


def test_openai_responses_vision_probe_uses_input_image_and_bounded_tokens() -> None:
    service = ProviderService()
    provider = _openai_provider().model_copy(
        update={
            "protocol": "openai_responses",
            "capabilities": CapabilityFlags(responses=True, vision=True, tools=False, streaming=False),
        }
    )
    client = MagicMock()
    client.responses.create.return_value = SimpleNamespace(output_text="VISION_OK")

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=client)):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="responses probe passed"),
            provider,
            "sk-test-secret",
        )

    evidence = _vision_evidence(result)
    assert evidence.observed is True
    assert evidence.state == "verified"
    _, kwargs = client.responses.create.call_args
    assert kwargs["max_output_tokens"] == 16
    assert kwargs["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Inspect the supplied image and reply with exactly VISION_OK if you can see it. Do not explain your answer."},
                {"type": "input_image", "image_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="},
            ],
        }
    ]


def test_minimax_vision_probe_ignores_think_text_and_disables_thinking() -> None:
    service = ProviderService()
    provider = ProviderConfig(
        name="MiniMax",
        base_url="http://gateway.example/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="openai_chat_completions_compatible",
        capabilities=CapabilityFlags(chat=True, vision=True, tools=False, streaming=False),
    )
    captured: dict[str, object] = {}

    def create(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _openai_response("<think>I can see the image VISION_OK</think>")

    client = MagicMock()
    client.chat.completions.create.side_effect = create
    with patch.object(service, "_create_sync_client", return_value=client):
        observed, diagnostic = service._probe_vision_capability(provider, "sk-test-secret")

    assert observed is not True
    assert "hidden reasoning" in diagnostic or "trustworthy visible" in diagnostic
    assert captured["max_tokens"] == 256
    extra_body = captured.get("extra_body")
    assert isinstance(extra_body, dict)
    assert extra_body["thinking"] == {"type": "disabled"}
    assert "sk-test-secret" not in diagnostic


def test_minimax_capability_truth_does_not_mark_vision_ready_from_think_text() -> None:
    service = ProviderService()
    provider = ProviderConfig(
        name="MiniMax",
        base_url="http://gateway.example/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
        protocol="openai_chat_completions_compatible",
        capabilities=CapabilityFlags(chat=True, vision=True, thinking=False, tools=False, streaming=False),
    )
    client = MagicMock()
    client.chat.completions.create.return_value = _openai_response(
        "<think>I inspected the image and the answer is VISION_OK</think>"
    )
    with patch.object(service, "_create_sync_client", return_value=client):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            provider,
            "sk-test-secret",
        )

    evidence = _vision_evidence(result)
    assert evidence.observed is not True
    assert evidence.state != "verified"
    assert result.vision_ready is not True
    assert "sk-test-secret" not in " ".join(result.diagnostics)


def test_openai_vision_probe_requires_image_and_exact_token() -> None:
    service = ProviderService()
    client = MagicMock()

    def create(**kwargs: object) -> SimpleNamespace:
        messages = kwargs["messages"]
        content = messages[0]["content"]
        assert content[0]["text"].startswith("Inspect the supplied image")
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        return _openai_response("VISION_OK")

    client.chat.completions.create.side_effect = create
    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=client)):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            _vision_provider(),
            "sk-test-secret",
        )

    evidence = _vision_evidence(result)
    assert evidence.observed is True
    assert evidence.state == "verified"
    assert result.vision_ready is True
    assert result.vision_probe_status == "verified"
    assert "sk-test-secret" not in " ".join(result.diagnostics)


def test_anthropic_vision_probe_uses_native_image_block_and_exact_token() -> None:
    provider = ProviderConfig(
        name="anthropic-compatible",
        base_url="https://gateway.example.com",
        api_key_ref="trainer.anthropic-compatible",
        model="test-model",
        protocol="anthropic_messages",
        capabilities=CapabilityFlags(chat=True, vision=True, tools=False, streaming=False),
    )
    service = ProviderService()

    response = MagicMock(status_code=200)
    response.json.return_value = {"content": [{"type": "text", "text": "VISION_OK"}]}
    client = MagicMock()
    client.post.return_value = response
    client_context = MagicMock()
    client_context.__enter__.return_value = client
    client_context.__exit__.return_value = False

    with patch("app.llm.provider_service.httpx.Client", return_value=client_context):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            provider,
            "sk-test-secret",
        )

    payload = client.post.call_args.kwargs["json"]
    image = payload["messages"][0]["content"][1]
    assert image == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
        },
    }
    assert payload["messages"][0]["content"][0]["text"].startswith("Inspect the supplied image")
    assert client.post.call_args.kwargs["headers"]["x-api-key"] == "sk-test-secret"
    evidence = _vision_evidence(result)
    assert evidence.observed is True
    assert evidence.state == "verified"
    assert result.vision_ready is True
    assert result.vision_probe_status == "verified"
    assert "sk-test-secret" not in " ".join(result.diagnostics)


def test_gemini_vision_probe_uses_native_inline_data_and_exact_token() -> None:
    provider = ProviderConfig(
        name="gemini-native",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_ref="trainer.gemini-native",
        model="gemini-2.0-flash",
        protocol="gemini_generate_content",
        capabilities=CapabilityFlags(chat=True, vision=True, tools=False, streaming=False),
    )
    service = ProviderService()
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "VISION_OK"}]}}]
    }
    client = MagicMock()
    client.post.return_value = response
    client_context = MagicMock()
    client_context.__enter__.return_value = client
    client_context.__exit__.return_value = False

    with patch("app.llm.provider_service.httpx.Client", return_value=client_context):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            provider,
            "sk-test-secret",
        )

    endpoint, kwargs = client.post.call_args.args[0], client.post.call_args.kwargs
    assert endpoint.endswith("/models/gemini-2.0-flash:generateContent")
    assert kwargs["headers"]["x-goog-api-key"] == "sk-test-secret"
    parts = kwargs["json"]["contents"][0]["parts"]
    assert parts[0]["text"].startswith("Inspect the supplied image")
    assert parts[1]["inlineData"]["mimeType"] == "image/png"
    assert parts[1]["inlineData"]["data"].startswith("iVBORw0KGgo")
    evidence = _vision_evidence(result)
    assert evidence.observed is True
    assert evidence.state == "verified"
    assert result.vision_ready is True
    assert result.vision_probe_status == "verified"
    assert "sk-test-secret" not in " ".join(result.diagnostics)


def test_openai_vision_probe_does_not_verify_non_token_reply_or_leak_data() -> None:
    service = ProviderService()
    client = MagicMock()
    private_body = "private upstream response body"
    client.chat.completions.create.return_value = _openai_response(private_body)

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=client)):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            _vision_provider(),
            "sk-test-secret",
        )

    evidence = _vision_evidence(result)
    assert evidence.observed is False
    assert evidence.state == "unsupported"
    assert result.vision_ready is False
    assert private_body not in " ".join(result.diagnostics)
    assert "sk-test-secret" not in " ".join(result.diagnostics)


def test_openai_tool_probe_marks_tools_verified_only_after_structured_call() -> None:
    service = ProviderService()
    client = MagicMock()

    def create(**kwargs: object) -> SimpleNamespace:
        if "tools" not in kwargs:
            return _openai_response("pong")
        return _openai_response(
            None,
            tool_calls=[
                SimpleNamespace(
                    id="probe-1",
                    function=SimpleNamespace(
                        name="trainer_capability_probe",
                        arguments='{"probe":"ok"}',
                    ),
                )
            ],
        )

    client.chat.completions.create.side_effect = create
    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=client)):
        result = service.test(_openai_provider(), "sk-test", response_language="en-US")

    evidence = _tool_evidence(result)
    assert result.ok is True
    assert result.tools_ready is True
    assert result.tool_probe_status == "verified"
    assert evidence.declared is True
    assert evidence.observed is True
    assert evidence.state == "verified"
    _, probe_kwargs = client.chat.completions.create.call_args
    assert probe_kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "trainer_capability_probe"},
    }


def test_openai_tool_probe_does_not_mark_text_only_reply_as_ready() -> None:
    service = ProviderService()
    client = MagicMock()
    client.chat.completions.create.side_effect = lambda **kwargs: _openai_response(
        "The tool exists but I will only describe it." if "tools" in kwargs else "pong"
    )

    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=client)):
        result = service.test(_openai_provider(), "sk-test", response_language="en-US")

    evidence = _tool_evidence(result)
    assert result.ok is True
    assert result.tools_ready is False
    assert result.tool_probe_status == "unsupported"
    assert evidence.observed is False
    assert evidence.state == "unsupported"


def test_openai_tool_probe_keeps_damaged_no_tool_reply_unverified_and_redacted() -> None:
    service = ProviderService()
    client = MagicMock()
    private_trace = "private provider trace must not surface"

    def create(**kwargs: object) -> SimpleNamespace:
        if "tools" not in kwargs:
            return _openai_response("pong")
        return _openai_response(
            f"<think>{private_trace}</think>",
            reasoning_content=private_trace,
        )

    client.chat.completions.create.side_effect = create
    with patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=client)):
        result = service.test(_openai_provider(), "sk-test", response_language="en-US")

    evidence = _tool_evidence(result)
    assert result.ok is True
    assert result.tools_ready is False
    assert result.tool_probe_status == "unverified"
    assert evidence.observed is None
    assert evidence.state == "unverified"
    assert private_trace not in " ".join(result.diagnostics)


def test_indeterminate_capability_probe_retries_once_before_caching_success() -> None:
    service = ProviderService()

    with patch.object(
        service,
        "_probe_tool_capability",
        side_effect=[
            (None, "Tool-call capability probe could not complete safely."),
            (True, "Tool-call capability probe observed the required call."),
        ],
    ) as probe:
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            _openai_provider(),
            "sk-test",
        )

    evidence = _tool_evidence(result)
    assert probe.call_count == 2
    assert evidence.state == "verified"
    assert result.tools_ready is True
    assert result.tool_probe_status == "verified"
    assert "retried once" in " ".join(result.diagnostics)


def test_negative_capability_probe_is_not_retried_into_a_positive_claim() -> None:
    service = ProviderService()

    with patch.object(
        service,
        "_probe_tool_capability",
        side_effect=[
            (False, "Tool-call capability probe completed without the required call."),
            (True, "This result must not be reached."),
        ],
    ) as probe:
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            _openai_provider(),
            "sk-test",
        )

    evidence = _tool_evidence(result)
    assert probe.call_count == 1
    assert evidence.state == "unsupported"
    assert result.tools_ready is False
    assert result.tool_probe_status == "unsupported"


def test_anthropic_tool_probe_uses_forced_noop_tool_without_executing_it() -> None:
    provider = ProviderConfig(
        name="anthropic-compatible",
        base_url="https://gateway.example.com",
        api_key_ref="trainer.anthropic-compatible",
        model="test-model",
        protocol="anthropic_messages",
        capabilities=CapabilityFlags(
            chat=True,
            responses=False,
            embeddings=False,
            tools=True,
            streaming=False,
        ),
    )
    service = ProviderService()

    class Response:
        status_code = 200
        text = "provider response"

        def __init__(self, body: dict[str, object]) -> None:
            self._body = body

        def json(self) -> dict[str, object]:
            return self._body

    client = MagicMock()
    client.post.side_effect = [
        Response({"content": [{"type": "text", "text": "pong"}]}),
        Response(
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "probe-1",
                        "name": "trainer_capability_probe",
                        "input": {"probe": "ok"},
                    }
                ],
                "stop_reason": "tool_use",
            }
        ),
    ]
    client_context = MagicMock()
    client_context.__enter__.return_value = client
    client_context.__exit__.return_value = False

    with patch("app.llm.provider_service.httpx.Client", return_value=client_context):
        result = service.test(provider, "sk-test", response_language="en-US")

    evidence = _tool_evidence(result)
    assert result.ok is True
    assert result.tools_ready is True
    assert evidence.state == "verified"
    probe_payload = client.post.call_args_list[-1].kwargs["json"]
    assert probe_payload["tool_choice"] == {
        "type": "tool",
        "name": "trainer_capability_probe",
    }
    assert probe_payload["tools"][0]["name"] == "trainer_capability_probe"


def test_streaming_probe_marks_capability_verified_only_after_visible_chunks() -> None:
    provider = ProviderConfig(
        name="stream-capability-truth",
        base_url="https://gateway.example.com/v1",
        api_key_ref="trainer.stream-capability-truth",
        model="test-model",
        protocol="openai_chat_completions_compatible",
        capabilities=CapabilityFlags(
            chat=True,
            responses=False,
            embeddings=False,
            tools=False,
            streaming=True,
        ),
    )
    service = ProviderService(config=provider, api_key="sk-test")

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "OK"

    with patch.object(service, "chat_completion_stream", new=fake_stream):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            provider,
            "sk-test",
        )

    streaming = next(item for item in result.capability_evidence if item.name == "streaming")
    assert streaming.declared is True
    assert streaming.observed is True
    assert streaming.state == "verified"
    assert result.streaming_ready is True
    assert result.stream_probe_status == "verified"


def test_chat_ok_but_stream_unverified_is_not_streaming_ready() -> None:
    provider = ProviderConfig(
        name="stream-capability-truth",
        base_url="https://gateway.example.com/v1",
        api_key_ref="trainer.stream-capability-truth",
        model="test-model",
        protocol="openai_chat_completions_compatible",
        capabilities=CapabilityFlags(
            chat=True,
            responses=False,
            embeddings=False,
            tools=False,
            streaming=True,
        ),
    )
    service = ProviderService(config=provider, api_key="sk-test")

    async def failing_stream(*_args: object, **_kwargs: object):
        raise RuntimeError("stream probe unavailable")
        if False:  # pragma: no cover - keep async generator shape
            yield ""

    with patch.object(service, "chat_completion_stream", new=failing_stream):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            provider,
            "sk-test",
        )

    streaming = next(item for item in result.capability_evidence if item.name == "streaming")
    assert result.ok is True
    assert streaming.declared is True
    assert streaming.observed is None
    assert streaming.state == "unverified"
    assert result.streaming_ready is False
    assert result.stream_probe_status == "unverified"
    assert result.tools_ready is False
    assert "sk-test" not in " ".join(result.diagnostics)


def test_streaming_probe_returns_after_first_visible_chunk_even_if_stream_never_finishes() -> None:
    provider = ProviderConfig(
        name="stream-capability-truth",
        base_url="https://gateway.example.com/v1",
        api_key_ref="trainer.stream-capability-truth",
        model="test-model",
        protocol="openai_chat_completions_compatible",
        capabilities=CapabilityFlags(
            chat=True,
            responses=False,
            embeddings=False,
            tools=False,
            streaming=True,
        ),
    )
    service = ProviderService(config=provider, api_key="sk-test")

    async def hanging_stream(*_args: object, **_kwargs: object):
        yield "OK"
        await asyncio.Event().wait()

    with patch.object(service, "chat_completion_stream", new=hanging_stream):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            provider,
            "sk-test",
        )

    streaming = next(item for item in result.capability_evidence if item.name == "streaming")
    assert streaming.declared is True
    assert streaming.observed is True
    assert streaming.state == "verified"
    assert result.streaming_ready is True
    assert result.stream_probe_status == "verified"


def test_minimax_streaming_probe_uses_generous_visible_budget() -> None:
    provider = ProviderConfig(
        name="MiniMax",
        base_url="http://minimax.example/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M2.7",
        protocol="openai_chat_completions_compatible",
        connection_type="newapi_channel_conn",
        capabilities=CapabilityFlags(
            chat=True,
            responses=False,
            embeddings=False,
            tools=False,
            streaming=True,
        ),
    )
    service = ProviderService(config=provider, api_key="sk-test")
    observed: dict[str, object] = {}

    async def visible_stream(*_args: object, **kwargs: object):
        observed["max_tokens"] = kwargs.get("max_tokens")
        yield "OK"

    with patch.object(service, "chat_completion_stream", new=visible_stream):
        result, _ = service._probe_streaming_capability(provider, "sk-test")

    assert result is True
    assert observed["max_tokens"] == 256


def test_reasoning_first_provider_visible_probes_reserve_a_generous_budget() -> None:
    minimax = ProviderConfig(
        name="MiniMax",
        base_url="https://api.minimax.example/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M2.7",
    )
    kimi = ProviderConfig(
        name="Kimi",
        base_url="https://api.moonshot.example/v1",
        api_key_ref="trainer.kimi",
        model="moonshot-v1-8k",
    )
    ordinary = ProviderConfig(
        name="ordinary",
        base_url="https://gateway.example/v1",
        api_key_ref="trainer.ordinary",
        model="ordinary-chat-model",
    )

    assert _visible_probe_max_tokens(minimax) == 1024
    assert _visible_probe_max_tokens(kimi) == 1024
    assert _visible_probe_max_tokens(ordinary) == 96


def test_minimax_tools_and_thinking_are_probed_even_when_undeclared() -> None:
    provider = ProviderConfig(
        name="MiniMax",
        base_url="http://minimax.example/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M2.7",
        protocol="openai_chat_completions_compatible",
        connection_type="newapi_channel_conn",
        capabilities=CapabilityFlags(
            chat=True,
            tools=False,
            streaming=False,
            vision=False,
            thinking=False,
        ),
    )
    service = ProviderService()
    client = MagicMock()
    tool_call = SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(name="trainer_capability_probe", arguments='{"probe":"ok"}'),
    )

    def create(**kwargs: object) -> SimpleNamespace:
        extra_body = kwargs.get("extra_body")
        if isinstance(extra_body, dict) and extra_body.get("thinking") == {"type": "enabled"}:
            return _openai_response("<think>plan</think>\nTHINKING_OK")
        if kwargs.get("tools"):
            return _openai_response("<think>plan</think>", tool_calls=[tool_call])
        return _openai_response("OK")

    client.chat.completions.create.side_effect = create
    with (
        patch.object(service, "_get_sync_openai_class", return_value=MagicMock(return_value=client)),
        patch.object(
            service,
            "_gateway_fingerprint_diagnostics",
            return_value=[
                "Gateway fingerprint: newapi_channel_conn (New API v1.0.0-rc.14). "
                "Catalog endpoint types are claims, not live protocol evidence. "
                "Unknown fields will not be sent."
            ],
        ),
    ):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            provider,
            "sk-test-secret",
        )

    tools = _tool_evidence(result)
    thinking = next(item for item in result.capability_evidence if item.name == "thinking")
    assert tools.declared is False
    assert tools.observed is True
    assert tools.state == "verified"
    assert result.tools_ready is True
    assert thinking.state in {"verified", "unverified"}
    assert "sk-test-secret" not in " ".join(result.diagnostics)
    assert any("newapi_channel_conn" in item for item in result.diagnostics)


def _evidence(result: ProviderTestResponse, name: str):
    return next(item for item in result.capability_evidence if item.name == name)


def test_openai_compatible_default_probes_tools_even_when_template_pins_false() -> None:
    provider = ProviderConfig(
        name="Kimi",
        base_url="https://api.moonshot.cn/v1",
        api_key_ref="kimi.default",
        model="moonshot-v1-8k",
        protocol="openai_chat_completions_compatible",
        capabilities=CapabilityFlags(chat=True, tools=False, streaming=True),
    )
    service = ProviderService()
    with (
        patch.object(service, "_probe_tool_capability", return_value=(True, "tools ok")),
        patch.object(service, "_probe_model_listing_capability", return_value=(True, "listed")),
    ):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            provider,
            "sk-kimi",
        )
    assert _evidence(result, "tools").declared is False
    assert _evidence(result, "tools").state == "verified"
    assert result.tools_ready is True
    service.apply_observed_capability_states(
        {item.name: item.state for item in result.capability_evidence}
    )
    service._api_key = "sk-kimi"
    service._config = provider
    assert service.supports_executable_tools() is True


def test_capability_probes_succeed_or_fail_independently() -> None:
    provider = ProviderConfig(
        name="independent-caps",
        base_url="https://gateway.example.com/v1",
        api_key_ref="trainer.independent",
        model="cap-model",
        protocol="openai_chat_completions_compatible",
        capabilities=CapabilityFlags(
            chat=True,
            tools=True,
            streaming=True,
            vision=True,
            thinking=True,
            embeddings=True,
            structured_output=True,
            json_schema=True,
        ),
    )
    service = ProviderService()
    with (
        patch.object(service, "_probe_tool_capability", return_value=(True, "tools ok")),
        patch.object(service, "_probe_streaming_capability", return_value=(False, "stream down")),
        patch.object(service, "_probe_thinking_capability", return_value=(None, "thinking unknown")),
        patch.object(service, "_probe_vision_capability", return_value=(True, "vision ok")),
        patch.object(service, "_probe_embeddings_capability", return_value=(False, "embed down")),
        patch.object(
            service, "_probe_structured_output_capability", return_value=(True, "json ok")
        ),
        patch.object(service, "_probe_model_listing_capability", return_value=(True, "listed")),
    ):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            provider,
            "sk-independent-secret",
        )

    names = {item.name for item in result.capability_evidence}
    assert {
        "chat",
        "streaming",
        "thinking",
        "tools",
        "vision",
        "structured_output",
        "embeddings",
        "model_listing",
    }.issubset(names)
    assert _evidence(result, "chat").state == "verified"
    assert _evidence(result, "tools").state == "verified"
    assert _evidence(result, "streaming").state == "unsupported"
    assert _evidence(result, "thinking").state == "unverified"
    assert _evidence(result, "vision").state == "verified"
    assert _evidence(result, "embeddings").state == "unsupported"
    assert _evidence(result, "structured_output").state == "verified"
    assert _evidence(result, "model_listing").state == "verified"
    assert result.tools_ready is True
    assert result.streaming_ready is False
    assert result.thinking_ready is False
    assert result.vision_ready is True
    assert "sk-independent-secret" not in " ".join(result.diagnostics)


def test_failed_listing_does_not_flip_chat_or_invent_ok() -> None:
    provider = _openai_provider()
    service = ProviderService()
    with (
        patch.object(service, "_probe_tool_capability", return_value=(False, "tools down")),
        patch.object(service, "_probe_embeddings_capability", return_value=(None, "embed skip")),
        patch.object(service, "_probe_model_listing_capability", return_value=(False, "listing 401")),
    ):
        result = service._with_capability_truth(
            ProviderTestResponse(ok=True, detail="chat probe passed"),
            provider,
            "sk-listing-secret",
        )

    assert result.ok is True
    assert _evidence(result, "chat").state == "verified"
    assert _evidence(result, "model_listing").state == "unsupported"
    assert _evidence(result, "tools").state == "unsupported"
    assert "sk-listing-secret" not in " ".join(result.diagnostics)
