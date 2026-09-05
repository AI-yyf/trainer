"""Reasoning-leak error taxonomy split for provider probe failures.

``_unusable_visible_reply_category`` must separate "hidden reasoning consumed
the whole output budget" (``reasoning_budget_exhausted`` — retryable, a larger
budget or a non-reasoning model helps) from "the model answered with hidden
reasoning only" (the historical ``reasoning_leak`` name, a model/protocol
choice issue), and fall back to ``empty_response`` otherwise.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import ProviderConfig
from app.llm.provider_service import (
    ProviderService,
    _reasoning_budget_exhausted,
    _unusable_visible_reply_category,
    _usage_output_tokens,
)


def _config() -> ProviderConfig:
    return ProviderConfig(
        name="test-provider",
        base_url="https://api.openai.com/v1",
        api_key_ref="trainer.test",
        model="gpt-4o-mini",
    )


class TestUnusableVisibleReplyCategory(unittest.TestCase):
    """Three outcomes: budget exhausted, reasoning only, plain empty."""

    def test_no_hidden_reasoning_is_empty_response(self) -> None:
        self.assertEqual(
            _unusable_visible_reply_category(hidden_reasoning_observed=False),
            "empty_response",
        )

    def test_hidden_reasoning_without_budget_exhaustion_keeps_reasoning_leak(self) -> None:
        self.assertEqual(
            _unusable_visible_reply_category(hidden_reasoning_observed=True),
            "reasoning_leak",
        )

    def test_hidden_reasoning_with_budget_exhaustion_is_budget_exhausted(self) -> None:
        self.assertEqual(
            _unusable_visible_reply_category(
                hidden_reasoning_observed=True,
                reasoning_budget_exhausted=True,
            ),
            "reasoning_budget_exhausted",
        )

    def test_budget_exhaustion_alone_does_not_claim_a_reasoning_category(self) -> None:
        self.assertEqual(
            _unusable_visible_reply_category(
                hidden_reasoning_observed=False,
                reasoning_budget_exhausted=True,
            ),
            "empty_response",
        )


class TestReasoningBudgetExhaustedSignal(unittest.TestCase):
    """Conservative usage-based exhaustion signal."""

    def test_completion_tokens_at_budget_is_exhausted(self) -> None:
        response = SimpleNamespace(usage=SimpleNamespace(completion_tokens=96))
        self.assertTrue(
            _reasoning_budget_exhausted(response, max_tokens=96),
        )

    def test_completion_tokens_below_budget_is_not_exhausted(self) -> None:
        response = SimpleNamespace(usage=SimpleNamespace(completion_tokens=40))
        self.assertFalse(
            _reasoning_budget_exhausted(response, max_tokens=96),
        )

    def test_missing_usage_defaults_to_false(self) -> None:
        self.assertFalse(_reasoning_budget_exhausted(SimpleNamespace(), max_tokens=96))
        self.assertFalse(_reasoning_budget_exhausted(None, max_tokens=96))
        self.assertFalse(_reasoning_budget_exhausted(SimpleNamespace(usage=None), max_tokens=96))

    def test_missing_budget_defaults_to_false(self) -> None:
        response = SimpleNamespace(usage=SimpleNamespace(completion_tokens=96))
        self.assertFalse(_reasoning_budget_exhausted(response, max_tokens=None))
        self.assertFalse(_reasoning_budget_exhausted(response, max_tokens=0))

    def test_output_tokens_field_is_supported(self) -> None:
        response = SimpleNamespace(usage=SimpleNamespace(output_tokens=32))
        self.assertTrue(_reasoning_budget_exhausted(response, max_tokens=32))

    def test_usage_from_payload_dict_is_supported(self) -> None:
        response = {"usage": {"completion_tokens": 128}}
        self.assertTrue(_reasoning_budget_exhausted(response, max_tokens=128))
        self.assertEqual(_usage_output_tokens(response), 128)


class TestBudgetExhaustedDetail(unittest.TestCase):
    """The new category yields actionable localized detail text."""

    def test_detail_is_actionable_english(self) -> None:
        detail = ProviderService()._detail_from_category(
            "reasoning_budget_exhausted",
            provider=_config(),
        )
        lowered = detail.lower()
        self.assertIn("provider is reachable", lowered)
        self.assertIn("hidden reasoning", lowered)
        self.assertIn("output budget", lowered)
        self.assertIn("retry", lowered)
        self.assertIn("non-reasoning model", lowered)

    def test_detail_localizes_to_chinese(self) -> None:
        detail = ProviderService()._detail_from_category(
            "reasoning_budget_exhausted",
            provider=_config(),
            response_language="zh-CN",
        )
        self.assertIn("provider 已连通", detail)
        self.assertIn("隐藏思考", detail)
        self.assertIn("非思考", detail)

    def test_detail_appends_safe_error_detail(self) -> None:
        from app.llm.provider_service import ProviderRuntimeResponseError

        detail = ProviderService()._detail_from_category(
            "reasoning_budget_exhausted",
            provider=_config(),
            error=ProviderRuntimeResponseError(
                category="reasoning_budget_exhausted",
                detail="the model burned the whole budget",
                retryable=True,
            ),
        )
        self.assertIn("the model burned the whole budget", detail)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
