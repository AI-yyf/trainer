"""One transparent auto-retry for LLM card generation.

``CardGenerationService._try_llm_generation`` must give every provider request
exactly one silent synchronous retry (higher temperature, same token budget)
before any failure is recorded or surfaced to the caller.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.event_ledger import EventLedgerService
from app.core.models import CardGenerationContext
from app.training.card_generator import (
    _CARD_GENERATION_MAX_TOKENS,
    CardGenerationProviderFailure,
    CardGenerationService,
)


def _ctx(**overrides: object) -> CardGenerationContext:
    defaults = {
        "workspace_id": "ws-retry",
        "source": "conversation_gap",
        "card_type": "practice",
        "context_hint": "",
        "target_skill": "",
        "focus_area": "",
        "plan_stage_id": "",
    }
    defaults.update(overrides)
    return CardGenerationContext(**defaults)  # type: ignore[arg-type]


def _practice_llm_payload() -> dict:
    """Payload that satisfies _PRACTICE_REQUIRED_FIELDS and the card model."""
    return {
        "title": "Practice: Async Error Handling",
        "focus_area": "async patterns",
        "target_skill": "async error handling",
        "scenario": "You are building a web scraper that fetches multiple pages concurrently.",
        "problem_statement": "Handle exceptions from concurrent HTTP requests gracefully.",
        "api_hints": ["asyncio.gather(return_exceptions=True)", "try/except inside async function"],
        "deliverable": "A function that fetches URLs concurrently and reports failures.",
        "self_check": [
            "Does the function handle network errors?",
            "Are all results collected even if some fail?",
        ],
        "grading_rubric": [
            "All exceptions are caught and logged",
            "Successful results are still returned",
        ],
        "stuck_recovery": "Start with a single URL fetch, then add concurrency.",
        "reflection_prompt": "How does return_exceptions change the behavior of asyncio.gather?",
    }


def _as_json(payload: dict) -> str:
    return json.dumps(payload)


class _ScriptedProvider:
    """Fake provider returning scripted outcomes from async chat_completion."""

    def __init__(self, outcomes: list[str | Exception]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        del model
        self.calls.append({"temperature": temperature, "max_tokens": max_tokens})
        if not self._outcomes:  # pragma: no cover - guards mis-scripted tests
            raise AssertionError("Provider received more calls than scripted.")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def temperatures(self) -> list[object]:
        return [call["temperature"] for call in self.calls]


class TestCardGenerationRetry(unittest.TestCase):
    """2-attempt loop: retry malformed first attempts, record failure only once."""

    def test_invalid_json_first_attempt_is_retried_and_returns_card(self) -> None:
        provider = _ScriptedProvider(
            ["<think>reasoning only, no JSON</think>", _as_json(_practice_llm_payload())],
        )
        service = CardGenerationService(provider_service=provider)

        card = service.generate_card("conversation_gap", _ctx(focus_area="async patterns"))

        self.assertIsNotNone(card)
        self.assertEqual(card.title, "Practice: Async Error Handling")
        self.assertEqual(card.card_type, "practice")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.temperatures, [0.7, 0.9])
        for call in provider.calls:
            self.assertEqual(call["max_tokens"], _CARD_GENERATION_MAX_TOKENS)

    def test_provider_exception_first_attempt_is_retried_and_returns_card(self) -> None:
        provider = _ScriptedProvider(
            [RuntimeError("transient gateway blip"), _as_json(_practice_llm_payload())],
        )
        service = CardGenerationService(provider_service=provider)

        card = service._try_llm_generation(_ctx(), "conversation_gap", "practice")

        self.assertIsNotNone(card)
        self.assertEqual(card.title, "Practice: Async Error Handling")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.temperatures, [0.7, 0.9])

    def test_missing_fields_first_attempt_is_retried_and_returns_card(self) -> None:
        incomplete = {"title": "Practice: half-written card"}
        provider = _ScriptedProvider([_as_json(incomplete), _as_json(_practice_llm_payload())])
        service = CardGenerationService(provider_service=provider)

        card = service._try_llm_generation(_ctx(), "conversation_gap", "practice")

        self.assertIsNotNone(card)
        self.assertEqual(len(provider.calls), 2)

    def test_valid_first_attempt_is_not_retried(self) -> None:
        provider = _ScriptedProvider([_as_json(_practice_llm_payload())])
        service = CardGenerationService(provider_service=provider)

        card = service._try_llm_generation(_ctx(), "conversation_gap", "practice")

        self.assertIsNotNone(card)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.temperatures, [0.7])

    def test_both_attempts_invalid_records_failure_once_and_raises(self) -> None:
        ledger = EventLedgerService()
        provider = _ScriptedProvider(
            ["<think>hidden reasoning attempt one</think>", "still not JSON"],
        )
        service = CardGenerationService(provider_service=provider, event_ledger=ledger)
        context = _ctx(focus_area="async patterns")

        with self.assertRaises(CardGenerationProviderFailure) as raised:
            service.generate_card("conversation_gap", context)
        self.assertEqual(raised.exception.reason, "invalid_json")

        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.temperatures, [0.7, 0.9])
        failures = ledger.query(
            event_type="card_generation_failed",
            project_id="ws-retry",
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].payload_ref["reason"], "invalid_json")

    def test_both_attempts_raise_records_exception_failure_once(self) -> None:
        ledger = EventLedgerService()
        provider = _ScriptedProvider(
            [RuntimeError("gateway down"), RuntimeError("gateway still down")],
        )
        service = CardGenerationService(provider_service=provider, event_ledger=ledger)

        card = service._try_llm_generation(_ctx(), "conversation_gap", "practice")

        self.assertIsNone(card)
        self.assertEqual(len(provider.calls), 2)
        failures = ledger.query(
            event_type="card_generation_failed",
            project_id="ws-retry",
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].payload_ref["reason"], "exception")

    def test_retry_reuses_thread_pool_helper_inside_running_loop(self) -> None:
        """The retry must work when invoked from within a running event loop."""
        provider = _ScriptedProvider(["not JSON", _as_json(_practice_llm_payload())])
        service = CardGenerationService(provider_service=provider)

        async def generate_from_loop() -> object:
            # Calling the sync helper on a thread with a live loop exercises
            # the thread-pool execution branch for both attempts.
            return service._try_llm_generation(_ctx(), "conversation_gap", "practice")

        card = asyncio.run(generate_from_loop())
        self.assertIsNotNone(card)
        self.assertEqual(len(provider.calls), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
