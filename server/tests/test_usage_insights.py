"""P1 #12: the local usage dashboard reads the event ledger, and only reads it.

What must stay true:

* aggregation is deterministic (injectable ``now``) and window-clamped;
* malformed timestamps and out-of-window events are skipped, never inflate a
  number and never crash the lane;
* the daily series carries exactly the four actionable signals;
* the streak counts consecutive active days ending today (or yesterday);
* the HTTP lane is GET-only and reflects what the runtime ledger recorded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.event_ledger import (
    EVENT_CARD_CANDIDATE_CREATED,
    EVENT_EVIDENCE_ADOPTED,
    EVENT_PLAN_STAGE_ADVANCED,
    EVENT_PRACTICE_SUBMISSION_RECORDED,
    EVENT_RESOURCE_INDEXED,
    EVENT_RESOURCE_UPLOADED,
    EventLedgerEntry,
)
from app.core.usage_insights import build_local_usage_insights

_NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


def _entry(event_type: str, occurred_at: str, **overrides: Any) -> EventLedgerEntry:
    payload: dict[str, Any] = {
        "event_id": f"evt-{event_type}-{occurred_at}",
        "event_type": event_type,
        "occurred_at": occurred_at,
    }
    payload.update(overrides)
    return EventLedgerEntry(**payload)


def _day(offset_days: int, hour: int = 9) -> str:
    return (_NOW - timedelta(days=offset_days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    ).isoformat()


def test_empty_ledger_yields_zeroes_and_a_full_daily_series() -> None:
    result = build_local_usage_insights([], window_days=7, now=_NOW)
    assert result["total_events"] == 0
    assert result["active_days"] == 0
    assert result["streak_days"] == 0
    assert result["totals"] == {
        "cards": 0,
        "plans": 0,
        "evidence": 0,
        "practice_submissions": 0,
        "resources": 0,
        "reflections": 0,
        "teaching_assets": 0,
    }
    assert result["last_activity_at"] is None
    assert len(result["daily"]) == 7
    assert result["daily"][-1]["date"] == _NOW.date().isoformat()
    assert all(item["any_activity"] is False for item in result["daily"])


def test_totals_group_the_canonical_event_types() -> None:
    entries = [
        _entry(EVENT_CARD_CANDIDATE_CREATED, _day(0)),
        _entry(EVENT_CARD_CANDIDATE_CREATED, _day(1)),
        _entry(EVENT_PLAN_STAGE_ADVANCED, _day(0)),
        _entry(EVENT_EVIDENCE_ADOPTED, _day(0)),
        _entry(EVENT_RESOURCE_UPLOADED, _day(2)),
        _entry(EVENT_RESOURCE_INDEXED, _day(2)),
        _entry(EVENT_PRACTICE_SUBMISSION_RECORDED, _day(0)),
    ]
    result = build_local_usage_insights(entries, window_days=7, now=_NOW)
    assert result["totals"] == {
        "cards": 2,
        "plans": 1,
        "evidence": 1,
        "practice_submissions": 1,
        "resources": 2,
        "reflections": 0,
        "teaching_assets": 0,
    }
    assert result["active_days"] == 3
    assert result["last_activity_at"] == _day(0, 9)


def test_daily_series_counts_the_four_signals() -> None:
    entries = [
        _entry(EVENT_PRACTICE_SUBMISSION_RECORDED, _day(0, 8)),
        _entry(EVENT_PRACTICE_SUBMISSION_RECORDED, _day(0, 10)),
        _entry(EVENT_PLAN_STAGE_ADVANCED, _day(1)),
        _entry(EVENT_EVIDENCE_ADOPTED, _day(2)),
        _entry(EVENT_RESOURCE_INDEXED, _day(3)),
    ]
    result = build_local_usage_insights(entries, window_days=7, now=_NOW)
    daily = {item["date"]: item for item in result["daily"]}
    today = _NOW.date().isoformat()
    assert daily[today]["practice_submissions"] == 2
    assert daily[(_NOW - timedelta(days=1)).date().isoformat()]["stage_advances"] == 1
    assert daily[(_NOW - timedelta(days=2)).date().isoformat()]["evidence_adopted"] == 1
    assert daily[(_NOW - timedelta(days=3)).date().isoformat()]["resources_indexed"] == 1
    assert daily[today]["any_activity"] is True
    assert daily[(_NOW - timedelta(days=4)).date().isoformat()]["any_activity"] is False


def test_streak_counts_consecutive_active_days_ending_today() -> None:
    entries = [
        _entry(EVENT_PRACTICE_SUBMISSION_RECORDED, _day(0)),
        _entry(EVENT_PLAN_STAGE_ADVANCED, _day(1)),
        _entry(EVENT_EVIDENCE_ADOPTED, _day(2)),
    ]
    result = build_local_usage_insights(entries, window_days=7, now=_NOW)
    assert result["streak_days"] == 3

    # Yesterday-only streaks still count before today produces its first event.
    yesterday_only = [_entry(EVENT_EVIDENCE_ADOPTED, _day(1))]
    assert build_local_usage_insights(yesterday_only, window_days=7, now=_NOW)["streak_days"] == 1

    # A gap breaks the streak even with older activity.
    gapped = [_entry(EVENT_EVIDENCE_ADOPTED, _day(3))]
    assert build_local_usage_insights(gapped, window_days=7, now=_NOW)["streak_days"] == 0


def test_malformed_and_out_of_window_entries_are_skipped() -> None:
    entries = [
        _entry(EVENT_EVIDENCE_ADOPTED, "not-a-timestamp"),
        _entry(EVENT_EVIDENCE_ADOPTED, ""),
        _entry(EVENT_EVIDENCE_ADOPTED, (_NOW - timedelta(days=400)).isoformat()),
        _entry(EVENT_EVIDENCE_ADOPTED, _day(0)),
    ]
    result = build_local_usage_insights(entries, window_days=30, now=_NOW)
    assert result["total_events"] == 1
    assert result["totals"]["evidence"] == 1
    assert result["active_days"] == 1


def test_window_days_is_clamped() -> None:
    result = build_local_usage_insights([], window_days=0, now=_NOW)
    assert result["window_days"] == 1
    result = build_local_usage_insights([], window_days=9999, now=_NOW)
    assert result["window_days"] == 365
    result = build_local_usage_insights([], window_days="nonsense", now=_NOW)  # type: ignore[arg-type]
    assert result["window_days"] == 30


def test_local_usage_endpoint_reflects_the_runtime_ledger(tmp_path: Any) -> None:
    from test_api import build_client

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        assert runtime.event_ledger is not None
        runtime.event_ledger.record_event(EVENT_EVIDENCE_ADOPTED, scope="test")

        response = client.get("/insights/local-usage")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["window_days"] == 30
        assert body["total_events"] >= 1
        assert body["totals"]["evidence"] >= 1
        assert isinstance(body["daily"], list) and len(body["daily"]) == 30

        clamped = client.get("/insights/local-usage?window_days=7")
        assert clamped.status_code == 200
        assert clamped.json()["window_days"] == 7

        rejected = client.get("/insights/local-usage?window_days=0")
        assert rejected.status_code == 422

        # The dashboard lane never writes.
        total_after = runtime.event_ledger.count()
        client.get("/insights/local-usage")
        assert runtime.event_ledger.count() == total_after
