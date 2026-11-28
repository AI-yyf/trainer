"""Phase 3 regressions: unified request-level reasoning_effort across protocols."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.models import ProviderConfig
from app.llm.agent_binding import ProviderAgentBinding
from app.llm.provider.thinking import (
    REASONING_EFFORT_BUDGET_TOKENS,
    apply_reasoning_effort_to_payload,
    normalize_reasoning_effort,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("off", "off"),
        ("none", "off"),
        ("disabled", "off"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("auto", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_reasoning_effort(raw: object, expected: str | None) -> None:
    assert normalize_reasoning_effort(raw) == expected


def test_apply_reasoning_effort_maps_all_four_protocols() -> None:
    # OpenAI Chat Completions
    chat_high = apply_reasoning_effort_to_payload({"model": "o3-mini"}, "high", "openai_chat_completions")
    assert chat_high["reasoning_effort"] == "high"
    chat_off = apply_reasoning_effort_to_payload({"model": "o3-mini", "reasoning_effort": "high"}, "off", "openai_chat_completions")
    assert "reasoning_effort" not in chat_off

    # OpenAI Responses
    resp_med = apply_reasoning_effort_to_payload({"model": "o3-mini"}, "medium", "openai_responses")
    assert resp_med["reasoning"] == {"effort": "medium"}
    resp_off = apply_reasoning_effort_to_payload({"model": "o3-mini", "reasoning": {"effort": "high"}}, "off", "openai_responses")
    assert "reasoning" not in resp_off

    # Anthropic Messages
    anth_low = apply_reasoning_effort_to_payload({"model": "claude-sonnet-4-5"}, "low", "anthropic_messages")
    assert anth_low["thinking"] == {"type": "enabled", "budget_tokens": REASONING_EFFORT_BUDGET_TOKENS["low"]}
    anth_off = apply_reasoning_effort_to_payload({"model": "claude-sonnet-4-5"}, "off", "anthropic_messages")
    assert anth_off["thinking"] == {"type": "disabled"}

    # Gemini GenerateContent
    gem_high = apply_reasoning_effort_to_payload({"generationConfig": {"maxOutputTokens": 32768}}, "high", "gemini_generate_content")
    assert gem_high["generationConfig"]["thinkingConfig"]["thinkingBudget"] == REASONING_EFFORT_BUDGET_TOKENS["high"]
    gem_off = apply_reasoning_effort_to_payload({"generationConfig": {"maxOutputTokens": 4096}}, "off", "gemini_generate_content")
    assert gem_off["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 0


def test_agent_binding_applies_reasoning_effort_to_anthropic_and_gemini_and_responses() -> None:
    def _binding(protocol: str, effort: str) -> ProviderAgentBinding:
        config = ProviderConfig(
            name="phase3-effort",
            baseUrl="https://api.example.com/v1",
            apiKeyRef="trainer.phase3",
            model="demo-model",
            protocol=protocol,  # type: ignore[arg-type]
            requestDefaults={"reasoning_effort": effort},
        )
        fake_service = SimpleNamespace(_config=config, _api_key="sk-test")
        return ProviderAgentBinding(provider_service=fake_service)

    anth_payload = _binding("anthropic_messages", "medium")._apply_anthropic_request_defaults(
        {"model": "claude-sonnet-4-5", "max_tokens": 16384}
    )
    assert anth_payload["thinking"] == {"type": "enabled", "budget_tokens": 8192}

    anth_off_payload = _binding("anthropic_messages", "off")._apply_anthropic_request_defaults(
        {"model": "claude-sonnet-4-5", "max_tokens": 4096}
    )
    assert anth_off_payload["thinking"] == {"type": "disabled"}

    gem_payload = _binding("gemini_generate_content", "low")._apply_gemini_request_defaults(
        {"generationConfig": {"maxOutputTokens": 8192}}
    )
    assert gem_payload["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 2048

    resp_payload = _binding("openai_responses", "high")._apply_openai_responses_request_defaults(
        {"model": "o3-mini"}
    )
    assert resp_payload["reasoning"] == {"effort": "high"}
