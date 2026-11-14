from __future__ import annotations

import asyncio

import pytest
from server.app.llm.provider_service import _iterate_provider_stream_with_cancellation


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
async def test_provider_stream_iterator_closes_when_consumer_stops_after_first_chunk() -> None:
    closed = asyncio.Event()

    async def upstream():
        try:
            yield "first"
            await asyncio.Event().wait()
        finally:
            closed.set()

    stream = _iterate_provider_stream_with_cancellation(upstream(), None)
    assert await anext(stream) == "first"
    await stream.aclose()

    assert closed.is_set()


@pytest.mark.asyncio
async def test_cancelling_consumer_cancels_the_pending_upstream_read() -> None:
    reading = asyncio.Event()
    closed = asyncio.Event()

    async def upstream():
        try:
            reading.set()
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            closed.set()

    stream = _iterate_provider_stream_with_cancellation(upstream(), asyncio.Event())
    pending = asyncio.create_task(anext(stream))
    await reading.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert closed.is_set()
