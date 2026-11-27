"""Stream creation and iteration cancellation (§五十二: extracted from provider_service.py)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from inspect import isawaitable
from typing import Any

logger = logging.getLogger(__name__)

# Upstreams occasionally send finish_reason and then keep the HTTP stream open
# (observed with MiniMax M3.1). Use a tight post-finish drain once finish_seen()
# is true, while keeping the pre-finish idle ceiling generous so slow reasoning
# models are not prematurely cut off mid-thought.
STREAM_IDLE_TIMEOUT_SECONDS = 120.0
POST_FINISH_DRAIN_TIMEOUT_SECONDS = 1.0


def _stream_cancel_event(value: object | None) -> asyncio.Event | None:
    return value if isinstance(value, asyncio.Event) else None


def extract_non_sse_json_stream_payload(stream: object) -> dict[str, Any] | None:
    """Recover a complete JSON payload when an OpenAI-compatible proxy ignores stream=true."""
    response = getattr(stream, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    content_type = str(headers.get("content-type") or "").lower() if headers is not None else ""
    if "application/json" not in content_type:
        return None
    try:
        payload = response.json()
    except Exception as exc:
        logger.debug("Suppressed exception in streaming: %s", exc)
        return None
    return payload if isinstance(payload, dict) else None


async def _iterate_provider_stream_with_cancellation(
    stream: object,
    cancel_event: asyncio.Event | None,
    idle_timeout: float | None = STREAM_IDLE_TIMEOUT_SECONDS,
    *,
    finish_seen: Callable[[], bool] | None = None,
    post_finish_timeout: float | None = None,
):
    """Iterate an upstream async stream while promptly closing it on cancel.

    A stream that stops producing chunks for ``idle_timeout`` seconds (or
    ``post_finish_timeout`` seconds once ``finish_seen()`` becomes true) is
    treated as ended, so a missing [DONE] cannot pin the turn in streaming.
    """

    iterator = stream.__aiter__()  # type: ignore[attr-defined]
    iterator_closed = False
    iterator_exhausted = False
    resolved_post_finish = (
        POST_FINISH_DRAIN_TIMEOUT_SECONDS
        if post_finish_timeout is None
        else post_finish_timeout
    )

    async def _close_target(target: object | None) -> None:
        if target is None:
            return
        close = getattr(target, "aclose", None) or getattr(target, "close", None)
        if close is None:
            return
        try:
            outcome = close()
            if isawaitable(outcome):
                await outcome
        except RuntimeError as exc:
            if "asynchronous generator is already running" not in str(exc):
                raise

    async def close_iterator() -> None:
        nonlocal iterator_closed
        if iterator_closed:
            return
        iterator_closed = True
        if not iterator_exhausted:
            await _close_target(iterator)
        if stream is not iterator:
            await _close_target(stream)

    try:
        while True:
            effective_timeout = (
                resolved_post_finish
                if (finish_seen is not None and finish_seen())
                else idle_timeout
            )
            if cancel_event is None:
                try:
                    if effective_timeout is None:
                        item = await iterator.__anext__()
                    else:
                        item = await asyncio.wait_for(
                            iterator.__anext__(), timeout=effective_timeout
                        )
                except StopAsyncIteration:
                    iterator_exhausted = True
                    return
                except asyncio.TimeoutError:
                    logger.warning(
                        "[provider] stream idle for %ss without closing; treating as end",
                        effective_timeout,
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
                    timeout=effective_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    logger.warning(
                        "[provider] stream idle for %ss without closing; treating as end",
                        effective_timeout,
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
                if not cancellation.done():
                    cancellation.cancel()
                await asyncio.gather(cancellation, return_exceptions=True)
    finally:
        await close_iterator()


async def _await_provider_stream_with_cancellation(
    awaitable: Any,
    cancel_event: asyncio.Event | None,
) -> Any:
    """Cancel stream creation as well as iteration when a turn is cancelled."""

    if cancel_event is None:
        return await awaitable
    if cancel_event.is_set():
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
        if not cancellation.done():
            cancellation.cancel()
        await asyncio.gather(cancellation, return_exceptions=True)
