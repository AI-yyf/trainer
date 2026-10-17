"""Local usage insights — the event ledger's read-only consumer (P1 #12, §6.1).

Local-first by construction: everything here is derived from this machine's
own append-only ledger, aggregated into coarse counts. No identifiers, no
content, no network. This module only ever *reads* the ledger — it can never
append, mutate or delete an entry, so a dashboard bug cannot corrupt the audit
trail it reports on.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .event_ledger import (
    EVENT_CARD_CANDIDATE_CREATED,
    EVENT_CARD_STATUS_TRANSITIONED,
    EVENT_EVIDENCE_ADOPTED,
    EVENT_EVIDENCE_ENQUEUED,
    EVENT_EVIDENCE_REJECTED,
    EVENT_PLAN_GENERATED,
    EVENT_PLAN_STAGE_ADVANCED,
    EVENT_PRACTICE_SUBMISSION_RECORDED,
    EVENT_REFLECTION_RECORDED,
    EVENT_RESOURCE_INDEXED,
    EVENT_RESOURCE_UPLOADED,
    EVENT_TEACHING_ASSET_UPSERTED,
    EventLedgerEntry,
)

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365

# The daily series: the four signals a learner actually acts on.
_DAILY_SIGNALS: tuple[tuple[str, str], ...] = (
    (EVENT_PRACTICE_SUBMISSION_RECORDED, "practice_submissions"),
    (EVENT_PLAN_STAGE_ADVANCED, "stage_advances"),
    (EVENT_EVIDENCE_ADOPTED, "evidence_adopted"),
    (EVENT_RESOURCE_INDEXED, "resources_indexed"),
)

_ACTIVITY_EVENT_TYPES = frozenset(
    {
        EVENT_PRACTICE_SUBMISSION_RECORDED,
        EVENT_PLAN_STAGE_ADVANCED,
        EVENT_EVIDENCE_ADOPTED,
        EVENT_RESOURCE_INDEXED,
        EVENT_CARD_CANDIDATE_CREATED,
        EVENT_CARD_STATUS_TRANSITIONED,
        EVENT_PLAN_GENERATED,
        EVENT_EVIDENCE_ENQUEUED,
        EVENT_REFLECTION_RECORDED,
        EVENT_TEACHING_ASSET_UPSERTED,
    }
)

_TOTAL_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cards", (EVENT_CARD_CANDIDATE_CREATED, EVENT_CARD_STATUS_TRANSITIONED)),
    ("plans", (EVENT_PLAN_GENERATED, EVENT_PLAN_STAGE_ADVANCED)),
    (
        "evidence",
        (EVENT_EVIDENCE_ENQUEUED, EVENT_EVIDENCE_ADOPTED, EVENT_EVIDENCE_REJECTED),
    ),
    ("practice_submissions", (EVENT_PRACTICE_SUBMISSION_RECORDED,)),
    ("resources", (EVENT_RESOURCE_UPLOADED, EVENT_RESOURCE_INDEXED)),
    ("reflections", (EVENT_REFLECTION_RECORDED,)),
    ("teaching_assets", (EVENT_TEACHING_ASSET_UPSERTED,)),
)


def _parse_occurred_at(value: Any) -> datetime | None:
    """Parse a ledger timestamp; malformed entries are skipped, never crash."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_local_usage_insights(
    entries: Iterable[EventLedgerEntry],
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate ledger entries inside the window into local-only usage facts.

    ``now`` is injectable so the aggregation is deterministic under test; the
    window is ``[now - window_days, now]`` on the UTC calendar and unknown
    timestamps fall outside it (silence never inflates a number).
    """
    resolved_now = (now or _utc_now()).astimezone(timezone.utc)
    try:
        requested = int(window_days)
    except (TypeError, ValueError):
        requested = DEFAULT_WINDOW_DAYS
    span = max(1, min(requested, MAX_WINDOW_DAYS))
    window_start = resolved_now - timedelta(days=span)

    daily_practice: Counter[str] = Counter()
    daily_stage: Counter[str] = Counter()
    daily_adopted: Counter[str] = Counter()
    daily_indexed: Counter[str] = Counter()
    active_days: set[str] = set()
    # Zero-count groups stay in the report: an absent group is a fact, not an
    # omission, and the dashboard must not change shape with the data.
    totals: Counter[str] = Counter({name: 0 for name, _ in _TOTAL_GROUPS})
    last_activity: datetime | None = None
    total_events = 0

    for entry in entries:
        occurred = _parse_occurred_at(getattr(entry, "occurred_at", None))
        if occurred is None or occurred < window_start or occurred > resolved_now:
            continue
        event_type = str(getattr(entry, "event_type", "") or "")
        total_events += 1
        day = occurred.date().isoformat()
        if event_type in _ACTIVITY_EVENT_TYPES:
            active_days.add(day)
            if last_activity is None or occurred > last_activity:
                last_activity = occurred
        for group_name, members in _TOTAL_GROUPS:
            if event_type in members:
                totals[group_name] += 1
        if event_type == EVENT_PRACTICE_SUBMISSION_RECORDED:
            daily_practice[day] += 1
        elif event_type == EVENT_PLAN_STAGE_ADVANCED:
            daily_stage[day] += 1
        elif event_type == EVENT_EVIDENCE_ADOPTED:
            daily_adopted[day] += 1
        elif event_type == EVENT_RESOURCE_INDEXED:
            daily_indexed[day] += 1

    daily: list[dict[str, Any]] = []
    for offset in range(span):
        day = (resolved_now - timedelta(days=span - 1 - offset)).date().isoformat()
        daily.append(
            {
                "date": day,
                "practice_submissions": daily_practice.get(day, 0),
                "stage_advances": daily_stage.get(day, 0),
                "evidence_adopted": daily_adopted.get(day, 0),
                "resources_indexed": daily_indexed.get(day, 0),
                "any_activity": day in active_days,
            }
        )

    streak_days = 0
    cursor = resolved_now.date()
    # A streak survives until the end of the current day, so "yesterday only"
    # still counts before today produces its first event.
    if cursor.isoformat() not in active_days:
        cursor -= timedelta(days=1)
    while cursor.isoformat() in active_days:
        streak_days += 1
        cursor -= timedelta(days=1)

    return {
        "window_days": span,
        "window_start": window_start.isoformat(),
        "window_end": resolved_now.isoformat(),
        "total_events": total_events,
        "active_days": len(active_days),
        "streak_days": streak_days,
        "totals": dict(totals),
        "daily": daily,
        "last_activity_at": last_activity.isoformat() if last_activity else None,
    }
