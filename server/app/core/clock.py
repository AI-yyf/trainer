"""Test-controllable UTC clock.

Production always uses the real clock. Setting ``TRAINER_TEST_NOW`` to an ISO
timestamp lets verification harnesses advance days without sleeping; the
override is read on every call so a sidecar restart can move time forward.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime


def utc_now() -> datetime:
    raw = (os.getenv("TRAINER_TEST_NOW") or "").strip()
    if raw:
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            parsed = None
        if parsed is not None:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)
