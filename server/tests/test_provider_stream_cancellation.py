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
