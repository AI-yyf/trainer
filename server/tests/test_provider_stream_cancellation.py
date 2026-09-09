from __future__ import annotations

import asyncio

import pytest
from app.llm.provider_service import _iterate_provider_stream_with_cancellation


@pytest.mark.asyncio
async def test_provider_stream_iterator_closes_when_cancelled_while_waiting() -> None:
    release = asyncio.Event()
    cancelled = asyncio.Event()
    cancel_event = asyncio.Event()

    async def upstream():
        try:
            yield "first"
            await release.wait()
            yield "never reached"
        finally:
            cancelled.set()

    stream = _iterate_provider_stream_with_cancellation(upstream(), cancel_event)
    assert await anext(stream) == "first"

    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    cancel_event.set()

    with pytest.raises(asyncio.CancelledError):
        await pending

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_provider_stream_iterator_closes_when_outer_task_cancelled() -> None:
    """StreamingResponse cancel must aclose upstream even before cancel_event arms."""
    release = asyncio.Event()
    cancelled = asyncio.Event()
    cancel_event = asyncio.Event()

    async def upstream():
        try:
            yield "first"
            await release.wait()
            yield "never reached"
        finally:
            cancelled.set()

    stream = _iterate_provider_stream_with_cancellation(upstream(), cancel_event)
    assert await anext(stream) == "first"

    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    await asyncio.wait_for(cancelled.wait(), timeout=1.0)
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_await_provider_create_cancels_when_outer_task_cancelled() -> None:
    from app.llm.provider_service import _await_provider_stream_with_cancellation

    started = asyncio.Event()
    cancelled = asyncio.Event()
    cancel_event = asyncio.Event()

    async def slow_create():
        started.set()
        try:
            await asyncio.Event().wait()
            return "never"
        finally:
            cancelled.set()

    async def runner():
        return await _await_provider_stream_with_cancellation(slow_create(), cancel_event)

    task = asyncio.create_task(runner())
    await asyncio.wait_for(started.wait(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(cancelled.wait(), timeout=1.0)
