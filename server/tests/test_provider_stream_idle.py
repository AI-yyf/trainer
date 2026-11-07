"""Provider streams that never send [DONE] must not pin the turn open."""

from __future__ import annotations

import asyncio

import pytest

from app.llm.provider.streaming import _iterate_provider_stream_with_cancellation


async def _stalled_stream():
    yield "visible"
    await asyncio.sleep(10)


async def _normal_stream():
    yield "a"
    yield "b"


@pytest.mark.asyncio
async def test_idle_stream_ends_without_waiting_for_the_provider() -> None:
    started = asyncio.get_running_loop().time()
    items = [
        item
        async for item in _iterate_provider_stream_with_cancellation(
            _stalled_stream(), None, idle_timeout=0.05
        )
    ]
    elapsed = asyncio.get_running_loop().time() - started
    assert items == ["visible"]
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_normal_stream_is_unchanged() -> None:
    items = [
        item
        async for item in _iterate_provider_stream_with_cancellation(
            _normal_stream(), None, idle_timeout=1.0
        )
    ]
    assert items == ["a", "b"]


@pytest.mark.asyncio
async def test_cancel_event_still_closes_promptly() -> None:
    cancel_event = asyncio.Event()
    collected: list[str] = []

    async def consume() -> None:
        async for item in _iterate_provider_stream_with_cancellation(
            _stalled_stream(), cancel_event, idle_timeout=10.0
        ):
            collected.append(item)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    cancel_event.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert collected == ["visible"]
