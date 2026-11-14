"""Stream creation and iteration cancellation (§五十二: extracted from provider_service.py)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from anyio import CancelScope

logger = logging.getLogger(__name__)

# Upstreams occasionally send finish_reason and then keep the HTTP stream open
# (observed with MiniMax M3.1). Without an idle bound the UI stays in
# "streaming" forever even though the visible answer is complete.
STREAM_IDLE_TIMEOUT_SECONDS = 30.0


def _stream_cancel_event(value: object | None) -> asyncio.Event | None:
    return value if isinstance(value, asyncio.Event) else None


async def _iterate_provider_stream_with_cancellation(
    stream: object,
    cancel_event: asyncio.Event | None,
    idle_timeout: float | None = STREAM_IDLE_TIMEOUT_SECONDS,
):
    """Iterate an upstream async stream while promptly closing it on cancel.

    A stream that stops producing chunks for ``idle_timeout`` seconds is
    treated as ended, so a missing [DONE] cannot pin the turn in streaming.
    """

    iterator = stream.__aiter__()  # type: ignore[attr-defined]
    iterator_closed = False
    iterator_exhausted = False

    async def close_iterator() -> None:
        nonlocal iterator_closed
        if iterator_closed:
            return
        iterator_closed = True
        close = getattr(iterator, "aclose", None)
        if close is not None and not iterator_exhausted:
            try:
                await close()
            except RuntimeError as exc:
                if "asynchronous generator is already running" not in str(exc):
                    raise
        if stream is not iterator:
            close_stream = getattr(stream, "close", None)
            if close_stream is not None:
                await close_stream()

    try:
        while True:
            if cancel_event is None:
                try:
                    if idle_timeout is None:
                        item = await iterator.__anext__()
                    else:
                        item = await asyncio.wait_for(
                            iterator.__anext__(), timeout=idle_timeout
                        )
                except StopAsyncIteration:
                    iterator_exhausted = True
                    return
                except asyncio.TimeoutError:
                    logger.warning(
                        "[provider] stream idle for %ss without closing; treating as end",
                        idle_timeout,
                    )
                    await close_iterator()
                    return
                yield item
                continue
            if cancel_event.is_set():
                await close_iterator()
                raise asyncio.CancelledError

            next_item = asyncio.ensure_future(iterator.__anext__())
            cancellation = asyncio.create_task(cancel_event.wait())
            try:
                done, _ = await asyncio.wait(
                    {next_item, cancellation},
                    timeout=idle_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    logger.warning(
                        "[provider] stream idle for %ss without closing; treating as end",
                        idle_timeout,
                    )
                    next_item.cancel()
                    await asyncio.gather(next_item, return_exceptions=True)
                    await close_iterator()
                    return
                if cancellation in done and cancel_event.is_set():
                    next_item.cancel()
                    await asyncio.gather(next_item, return_exceptions=True)
                    await close_iterator()
                    raise asyncio.CancelledError
                try:
                    yield next_item.result()
                except StopAsyncIteration:
                    iterator_exhausted = True
                    return
            finally:
                if not next_item.done():
                    next_item.cancel()
                if not cancellation.done():
                    cancellation.cancel()
                # Starlette cancels the whole scope on disconnect. Join the
                # cancelled read before closing the underlying iterator.
                with CancelScope(shield=True):
                    await asyncio.gather(next_item, cancellation, return_exceptions=True)
    finally:
        with CancelScope(shield=True):
            await close_iterator()


async def _await_provider_stream_with_cancellation(
    awaitable: Any,
    cancel_event: asyncio.Event | None,
) -> Any:
    """Cancel stream creation as well as iteration when a turn is cancelled."""

    if cancel_event is None:
        return await awaitable
    if cancel_event.is_set():
        pending = asyncio.ensure_future(awaitable)
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        raise asyncio.CancelledError

    operation = asyncio.ensure_future(awaitable)
    cancellation = asyncio.create_task(cancel_event.wait())
    try:
        done, _ = await asyncio.wait(
            {operation, cancellation},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation in done and cancel_event.is_set():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise asyncio.CancelledError
        return operation.result()
    finally:
        if not operation.done():
            operation.cancel()
        if not cancellation.done():
            cancellation.cancel()
        with CancelScope(shield=True):
            await asyncio.gather(operation, cancellation, return_exceptions=True)
