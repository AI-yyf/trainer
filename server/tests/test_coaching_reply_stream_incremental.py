"""§35 regression: the plain coaching lane streams incrementally.

The live implementation (``_provider_service_coaching_reply_stream``,
assigned over ``ProviderService.coaching_reply_stream`` at module bottom)
releases the visible prefix with a holdback tail, flushes the remainder,
and only emits a final extension when ``finalize_coaching_reply`` extends
the raw stream. Reasoning blocks never surface as visible text. These
tests pin that contract so a refactor cannot silently re-buffer the lane.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.models import ProviderConfig, UserProfile
from app.llm.provider_service import ProviderService


def _profile() -> UserProfile:
    return UserProfile(
        long_term_goals=[],
        weekly_hours=4,
        teaching_style="auto",
        answer_policy="direct",
        preferred_libraries=[],
    )


def _config() -> ProviderConfig:
    return ProviderConfig(
        name="incremental-stream",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={"chat": True, "streaming": True},
    )


def _chunk(content: str, finish_reason: str | None = None) -> SimpleNamespace:
    delta = SimpleNamespace(content=content)
    choice = SimpleNamespace(finish_reason=finish_reason, delta=delta)
    return SimpleNamespace(choices=[choice])


def _stream(parts: list[str]) -> Any:
    async def _iterate():
        for part in parts:
            yield _chunk(part)
        yield _chunk("", finish_reason="stop")

    return _iterate()


def _service_with_stream(parts: list[str]) -> ProviderService:
    service = ProviderService(config=_config(), api_key="sk-test")
    stream = _stream(parts)

    async def fake_create(**_kwargs: object) -> tuple[Any, None]:
        return stream, None

    service._get_client = lambda: object()  # type: ignore[method-assign]
    service._create_chat_completion = fake_create  # type: ignore[method-assign]
    service._plain_completion_uses_agent_binding = lambda: False  # type: ignore[method-assign]
    return service


async def _collect(service: ProviderService, message: str) -> list[str]:
    return [
        chunk
        async for chunk in service.coaching_reply_stream(
            _profile(),
            message,
            response_language="en-US",
            answer_mode="direct",
        )
    ]


@pytest.mark.asyncio
async def test_plain_stream_releases_visible_text_incrementally() -> None:
    sentences = [
        "Recursive functions call themselves on a smaller input. ",
        "Each call must move toward a base case. ",
        "The base case stops the recursion. ",
        "Without it the calls never return. ",
    ]
    service = _service_with_stream(sentences)
    yielded = await _collect(service, "Explain recursion briefly.")

    assert yielded, "stream produced nothing"
    assert len(yielded) >= 2, f"expected incremental deltas, got {yielded!r}"
    # Nothing lost, nothing duplicated: the streamed pieces compose the full
    # visible raw text the lane received from the provider.
    assert "".join(yielded) == "".join(sentences)


@pytest.mark.asyncio
async def test_plain_stream_hides_reasoning_and_releases_only_visible_text() -> None:
    reasoning = "<think>\nPlan the answer carefully"
    parts = [
        reasoning,
        " with one sentence and one example.\n</think>\n",
        "Recursion solves a problem by solving smaller copies of it. ",
        "Every recursive function needs a base case that stops the calls. ",
        "Forgetting the base case causes infinite recursion and a crash. ",
    ]
    service = _service_with_stream(parts)
    yielded = await _collect(service, "What makes recursion terminate?")

    streamed = "".join(yielded)
    assert "Plan the answer" not in streamed, "reasoning must never stream as visible text"
    assert "Recursion solves" in streamed
    assert "infinite recursion" in streamed
    # The visible payload is complete: every visible provider delta arrived.
    assert streamed == "".join(parts[2:])
