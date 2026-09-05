from app.core.models import CapabilityFlags
from app.llm.provider_protocols import (
    SUPPORTED_PROVIDER_PROTOCOLS,
    assess_provider_capabilities,
    assess_provider_error,
    assess_provider_tool_call_probe,
    assess_provider_vision_probe,
    default_capabilities_for_protocol,
    list_supported_provider_protocol_catalog,
    normalize_provider_protocol,
    normalize_provider_response,
    protocol_model_supported,
    provider_protocol_client_kind,
    provider_protocol_completion_label,
    provider_protocol_diagnostic_notes,
    provider_protocol_endpoint_hint,
    provider_protocol_family,
    provider_protocol_required_capability,
    provider_protocol_test_mode,
    provider_protocol_test_model_hint,
    safe_provider_diagnostic,
)


def test_provider_protocol_helpers_cover_supported_protocol_set() -> None:
    assert SUPPORTED_PROVIDER_PROTOCOLS == (
        "openai_responses",
        "openai_chat_completions",
        "anthropic_messages",
        "openai_chat_completions_compatible",
        "gemini_generate_content",
    )
    assert normalize_provider_protocol("unknown") is None
    assert normalize_provider_protocol(None) is None
    assert provider_protocol_family("unknown") is None
    assert provider_protocol_family("anthropic_messages") == "anthropic"
    assert provider_protocol_family("gemini_generate_content") == "gemini"
    assert provider_protocol_endpoint_hint("openai_responses") == "/v1/responses"
    assert provider_protocol_endpoint_hint("anthropic_messages") == "/v1/messages"
    assert provider_protocol_required_capability("openai_responses") == "responses"
    assert provider_protocol_required_capability("anthropic_messages") == "chat"
    assert provider_protocol_client_kind("openai_chat_completions_compatible") == "openai"
    assert provider_protocol_client_kind("anthropic_messages") == "anthropic"
    assert provider_protocol_diagnostic_notes("gemini_generate_content")[0].startswith(
        "Gemini GenerateContent"
    )
    assert (
        provider_protocol_completion_label("openai_chat_completions_compatible")
        == "OpenAI-compatible chat completions"
    )
    assert provider_protocol_test_mode("openai_responses") == "responses"
    assert provider_protocol_test_mode("openai_chat_completions") == "openai_chat"
    assert provider_protocol_test_mode("anthropic_messages") == "anthropic"
    assert provider_protocol_test_mode("openai_chat_completions_compatible") == "openai_chat"
    assert provider_protocol_test_model_hint("anthropic_messages") == "claude-3-haiku-20240307"
    assert provider_protocol_test_model_hint("gemini_generate_content") == "gemini-2.0-flash"
    assert provider_protocol_test_model_hint("openai_chat_completions_compatible") is None
    assert protocol_model_supported("openai_responses", CapabilityFlags(responses=True))
    catalog = list_supported_provider_protocol_catalog()
    assert [entry.protocol for entry in catalog] == list(SUPPORTED_PROVIDER_PROTOCOLS)
    assert catalog[0].protocol_family == "openai"
    assert catalog[0].completion_label == "OpenAI Responses"
    assert catalog[1].endpoint_hint == "/v1/chat/completions"
    assert catalog[2].test_mode == "anthropic"


def test_default_capabilities_for_protocol_enable_tool_capable_coach_defaults() -> None:
    anthropic = default_capabilities_for_protocol("anthropic_messages")
    openai_compatible = default_capabilities_for_protocol("openai_chat_completions_compatible")
    responses = default_capabilities_for_protocol("openai_responses")

    assert anthropic.chat is True
    assert anthropic.tools is True
    assert anthropic.streaming is True
    assert anthropic.json_schema is False
    assert anthropic.vision is True

    assert openai_compatible.chat is True
    assert openai_compatible.tools is False
    assert openai_compatible.streaming is True
    assert openai_compatible.json_schema is False
    assert openai_compatible.vision is False
    assert openai_compatible.thinking is False
    assert default_capabilities_for_protocol(None).chat is False

    assert responses.responses is True
    assert responses.tools is True
    assert responses.vision is False
    assert default_capabilities_for_protocol("gemini_generate_content").vision is False


def test_capability_assessment_distinguishes_declared_claims_from_probe_evidence() -> None:
    declared = CapabilityFlags(
        chat=True,
        responses=False,
        vision=False,
        embeddings=False,
        tools=True,
        jsonSchema=False,
        structuredOutput=False,
        streaming=True,
    )

    assessment = assess_provider_capabilities(
        "openai_chat_completions_compatible",
        declared,
        {
            "chat": True,
            "tools": None,
            "vision": False,
            "jsonSchema": True,
        },
    )

    chat = assessment.for_capability("chat")
    tools = assessment.for_capability("tools")
    vision = assessment.for_capability("vision")
    json_schema = assessment.for_capability("json_schema")
    assert chat is not None and chat.state == "verified"
    assert tools is not None and tools.state == "unverified"
    assert vision is not None and vision.state == "unsupported"
    assert json_schema is not None and json_schema.state == "verified"
    assert assessment.supports("tools") is False
    assert assessment.supports("tools", require_verified=False) is True
    assert assessment.supports("vision", require_verified=False) is False
    assert assessment.supports("jsonSchema") is True


def test_tool_probe_verifies_only_the_requested_structured_tool_call() -> None:
    assessment = assess_provider_tool_call_probe(
        "anthropic_messages",
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
        },
        expected_tool_name="trainer_capability_probe",
    )

    assert assessment.observed is True
    assert assessment.state == "verified"


def test_tool_probe_marks_forced_text_only_reply_as_not_tool_ready() -> None:
    assessment = assess_provider_tool_call_probe(
        "anthropic_messages",
        {
            "content": [{"type": "text", "text": "I will describe the tool instead."}],
            "stop_reason": "end_turn",
        },
        expected_tool_name="trainer_capability_probe",
    )

    assert assessment.observed is False
    assert assessment.state == "unsupported"


def test_tool_probe_keeps_hidden_or_damaged_response_unverified_without_leaking_it() -> None:
    private_trace = "private capability trace should never surface"
    assessment = assess_provider_tool_call_probe(
        "anthropic_messages",
        {
            "content": [{"type": "thinking", "thinking": private_trace}],
            "stop_reason": "end_turn",
        },
        expected_tool_name="trainer_capability_probe",
    )

    assert assessment.observed is None
    assert assessment.state == "unverified"
    assert private_trace not in assessment.diagnostic


def test_gemini_vision_probe_verifies_exact_token() -> None:
    assessment = assess_provider_vision_probe(
        "gemini_generate_content",
        {"candidates": [{"content": {"parts": [{"text": "VISION_OK"}]}}]},
        expected_token="VISION_OK",
    )

    assert assessment.observed is True
    assert assessment.state == "verified"


def test_gemini_vision_probe_rejects_token_mismatch() -> None:
    assessment = assess_provider_vision_probe(
        "gemini_generate_content",
        {"candidates": [{"content": {"parts": [{"text": "not the token"}]}}]},
        expected_token="VISION_OK",
    )

    assert assessment.observed is False
    assert assessment.state == "unsupported"


def test_gemini_vision_probe_keeps_error_unverified_without_leaking_body() -> None:
    private_body = "private gemini body should never surface"
    assessment = assess_provider_vision_probe(
        "gemini_generate_content",
        {"error": {"message": private_body}, "status": 400},
        expected_token="VISION_OK",
    )

    assert assessment.observed is None
    assert assessment.state == "unverified"
    assert private_body not in assessment.diagnostic


def test_normalize_reasoning_only_openai_payload_hides_reasoning() -> None:
    assessment = normalize_provider_response(
        "openai_chat_completions",
        {
            "choices": [
                {
                    "message": {
                        "content": "<think>private internal trace</think>",
                        "reasoning_content": "private internal trace",
                    },
                    "finish_reason": "stop",
                }
            ]
        },
    )

    assert assessment.outcome == "reasoning_only"
    assert assessment.error_category == "reasoning_leak"
    assert assessment.content == ""
    assert assessment.hidden_reasoning_observed is True
    assert "private internal trace" not in assessment.diagnostic


def test_normalize_provider_response_marks_native_empty_anthropic_payload() -> None:
    assessment = normalize_provider_response(
        "anthropic_messages",
        {"content": [], "stop_reason": "end_turn"},
    )

    assert assessment.outcome == "empty_response"
    assert assessment.error_category == "empty_response"
    assert assessment.retryable is True
    assert assessment.content == ""


def test_normalize_provider_response_accepts_a_direct_visible_text_reply() -> None:
    assessment = normalize_provider_response(
        "openai_chat_completions_compatible",
        "direct visible reply",
    )

    assert assessment.outcome == "visible_text"
    assert assessment.content == "direct visible reply"
    assert assessment.has_visible_text is True


def test_normalize_provider_response_preserves_partial_text_but_marks_gemini_truncation() -> None:
    assessment = normalize_provider_response(
        "gemini_generate_content",
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "partial visible answer"}]},
                    "finishReason": "MAX_TOKENS",
                }
            ]
        },
    )

    assert assessment.outcome == "truncated"
    assert assessment.error_category == "truncated_or_empty"
    assert assessment.content == "partial visible answer"
    assert assessment.truncated is True
    assert assessment.retryable is True


def test_normalize_responses_output_does_not_duplicate_aggregate_visible_text() -> None:
    assessment = normalize_provider_response(
        "openai_responses",
        {
            "output_text": "visible answer",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "visible answer"}],
                }
            ],
        },
    )

    assert assessment.outcome == "visible_text"
    assert assessment.content == "visible answer"


def test_normalize_provider_response_rejects_a_different_protocol_shape() -> None:
    assessment = normalize_provider_response(
        "openai_responses",
        {"choices": [{"message": {"content": "do not accept this as Responses output"}}]},
    )

    assert assessment.outcome == "protocol_mismatch"
    assert assessment.error_category == "protocol_mismatch"
    assert assessment.detected_protocol == "openai_chat_completions"
    assert assessment.content == ""
    assert assessment.retryable is False
    assert "do not accept this as Responses output" not in assessment.diagnostic


def test_protocol_detection_rejects_even_an_empty_anthropic_shape_for_openai() -> None:
    assessment = normalize_provider_response(
        "openai_chat_completions",
        {"content": [], "stop_reason": "end_turn"},
    )

    assert assessment.outcome == "protocol_mismatch"
    assert assessment.detected_protocol == "anthropic_messages"


def test_protocol_mismatch_error_and_diagnostic_do_not_expose_credentials_or_bodies() -> None:
    error = Exception(
        "Error code: 404 - Invalid URL (POST /v1/responses); "
        "Authorization: Bearer do-not-display-this-value"
    )

    assessment = assess_provider_error(
        "openai_responses",
        error,
        api_key="do-not-display-this-value",
    )
    diagnostic = safe_provider_diagnostic(
        "HTTP 400; token=do-not-display-this-value; "
        'response body: {"secret": "never-display-this"}',
        api_key="do-not-display-this-value",
    )

    assert assessment.category == "protocol_mismatch"
    assert assessment.status_code == 404
    assert assessment.retryable is False
    assert "do-not-display-this-value" not in assessment.diagnostic
    assert "never-display-this" not in diagnostic
    assert "do-not-display-this-value" not in diagnostic
    assert "[REDACTED" in diagnostic
