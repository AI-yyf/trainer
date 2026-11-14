from __future__ import annotations

from app.core.models import ProviderConfig
from app.llm.provider.capability import _model_looks_reasoning_first
from app.llm.provider_service import ProviderService


def _provider(model: str) -> ProviderConfig:
    return ProviderConfig(
        name="MiniMax Relay",
        base_url="http://minimax.relay.example.test/v1",
        api_key_ref="trainer.test",
        model=model,
    )


def test_minimax_m3_is_reasoning_first_and_gets_headroom() -> None:
    provider = _provider("MiniMax-M3.1-Flash")
    assert _model_looks_reasoning_first(provider) is True
    service = ProviderService(config=provider)
    assert service.recommended_generation_max_tokens(1024) == 16384


def test_minimax_m27_keeps_the_normal_budget() -> None:
    provider = _provider("MiniMax-M2.7")
    assert _model_looks_reasoning_first(provider) is False
    service = ProviderService(config=provider)
    assert service.recommended_generation_max_tokens(1024) == 1024


def test_escalation_goes_beyond_the_old_8192_cap() -> None:
    assert ProviderService._escalated_chat_budget(1024) == 8192
    assert ProviderService._escalated_chat_budget(8192) == 16384
    assert ProviderService._escalated_chat_budget(16384) is None
