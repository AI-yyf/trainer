"""Module-level singleflight helpers for coach session/turn request dedup.

Extracted verbatim from ``api/routers.py`` (pure code motion, zero behavior
change) so the streaming route clusters can consume them without pulling in
the whole ``build_router`` module.
"""

from __future__ import annotations

import asyncio
from threading import Lock
from typing import Literal


def claim_session_request_singleflight(
    request_key: tuple[str, str, str],
    *,
    completed: dict[tuple[str, str, str], dict[str, object]],
    inflight: dict[tuple[str, str, str], asyncio.Future],
    guard: Lock,
) -> tuple[Literal["cached", "owner", "wait"], dict[str, object] | None, asyncio.Future | None]:
    """Fail-closed: same request_id is single-flight — wait or own, never double-exec."""
    with guard:
        cached = completed.get(request_key)
        if cached is not None:
            return "cached", cached, None
        existing = inflight.get(request_key)
        if existing is not None and not existing.done():
            return "wait", None, existing
        if existing is not None:
            inflight.pop(request_key, None)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        inflight[request_key] = future
        return "owner", None, future


def publish_session_request_singleflight(
    request_key: tuple[str, str, str],
    payload: dict[str, object],
    *,
    completed: dict[tuple[str, str, str], dict[str, object]],
    inflight: dict[tuple[str, str, str], asyncio.Future],
    guard: Lock,
) -> dict[str, object]:
    """Store completed payload and release any same-request_id waiters."""
    with guard:
        completed[request_key] = payload
        future = inflight.pop(request_key, None)
    if future is not None and not future.done():
        future.set_result(payload)
    return payload


def fail_session_request_singleflight(
    request_key: tuple[str, str, str],
    error: BaseException,
    *,
    inflight: dict[tuple[str, str, str], asyncio.Future],
    guard: Lock,
) -> None:
    """Release waiters with the owner failure — do not leave them hung."""
    with guard:
        future = inflight.pop(request_key, None)
    if future is not None and not future.done():
        future.set_exception(error)
