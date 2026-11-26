"""Module-level singleflight helpers for coach session/turn request dedup.

Extracted verbatim from ``api/routers.py`` (pure code motion, zero behavior
change) so the streaming route clusters can consume them without pulling in
the whole ``build_router`` module.
"""

from __future__ import annotations

import asyncio
from threading import Lock
from typing import Literal

# The replay window exists for a prompt client resend (transport timeout, lost
# response) and for restoring the last response after a reload. It used to be
# unbounded: every completed turn kept a full WorkbenchSnapshot — including the
# whole conversation — for the life of the sidecar, so memory grew with the
# square of a long session. Keys beyond the bound execute again on a resend,
# exactly as they already do after a sidecar restart.
COMPLETED_REQUEST_REPLAY_LIMIT = 64


def _touch_and_trim_lru(
    completed: dict[tuple[str, str, str], dict[str, object]],
    request_key: tuple[str, str, str],
    payload: dict[str, object],
    *,
    limit: int,
) -> None:
    effective_limit = max(1, int(limit))
    completed.pop(request_key, None)
    completed[request_key] = payload
    while len(completed) > effective_limit:
        completed.pop(next(iter(completed)), None)


def get_completed_request(
    completed: dict[tuple[str, str, str], dict[str, object]],
    request_key: tuple[str, str, str],
    *,
    guard: Lock,
    limit: int = COMPLETED_REQUEST_REPLAY_LIMIT,
) -> dict[str, object] | None:
    """Fetch a completed request payload with true LRU touch-on-hit ordering."""
    with guard:
        cached = completed.get(request_key)
        if cached is None:
            return None
        _touch_and_trim_lru(completed, request_key, cached, limit=limit)
        return cached


def remember_completed_request(
    completed: dict[tuple[str, str, str], dict[str, object]],
    request_key: tuple[str, str, str],
    payload: dict[str, object],
    *,
    guard: Lock,
    limit: int = COMPLETED_REQUEST_REPLAY_LIMIT,
) -> None:
    """Store one completed response for replay, most-recently-used last, bounded."""
    with guard:
        _touch_and_trim_lru(completed, request_key, payload, limit=limit)


def claim_session_request_singleflight(
    request_key: tuple[str, str, str],
    *,
    completed: dict[tuple[str, str, str], dict[str, object]],
    inflight: dict[tuple[str, str, str], asyncio.Future],
    guard: Lock,
    limit: int = COMPLETED_REQUEST_REPLAY_LIMIT,
) -> tuple[Literal["cached", "owner", "wait"], dict[str, object] | None, asyncio.Future | None]:
    """Fail-closed: same request_id is single-flight — wait or own, never double-exec."""
    with guard:
        cached = completed.get(request_key)
        if cached is not None:
            _touch_and_trim_lru(completed, request_key, cached, limit=limit)
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
    limit: int = COMPLETED_REQUEST_REPLAY_LIMIT,
) -> dict[str, object]:
    """Store completed payload (LRU-bounded) and release any same-request_id waiters."""
    with guard:
        _touch_and_trim_lru(completed, request_key, payload, limit=limit)
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
