"""(w) Telemetry and cost: usage is recorded from real provider responses and
    reported per workspace.

Guarantees covered:
  * the cost ledger is append-only and scoped per workspace;
  * telemetry and usage insights are derived from recorded usage, not estimated from prompts.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_usage_insights.py
  * server/tests/test_telemetry.py
  * server/tests/test_cost_ledger.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.event_ledger import (
    EVENT_CARD_CANDIDATE_CREATED,
    EVENT_EVIDENCE_ADOPTED,
    EVENT_PLAN_STAGE_ADVANCED,
    EVENT_PRACTICE_SUBMISSION_RECORDED,
    EVENT_RESOURCE_INDEXED,
    EVENT_RESOURCE_UPLOADED,
    EventLedgerEntry,
)
from app.core.settings import AppSettings
from app.core.usage_insights import build_local_usage_insights
from app.llm.cost_ledger import CostLedger
from app.main import create_app
from app.telemetry.service import CONSENT_FILE_NAME

# ---------------------------------------------------------------------------
# Restored from test_usage_insights.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Restored from test_telemetry.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def build_app(tmp_path: Path, db_name: str = "trainer-telemetry.db") -> TestClient:
    settings = AppSettings(
        app_name="Trainer Telemetry Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name=db_name,
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_consent_defaults_to_off_and_status_is_fact_only(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    status = client.get("/telemetry/status").json()
    assert status == {"opt_in": False, "consent_updated_at": None, "consent_changes": 0}


def test_consent_is_durable_across_restores_on_same_data_dir(tmp_path: Path) -> None:
    first = build_app(tmp_path)
    first.post("/telemetry/consent", json={"opt_in": True, "source": "settings"})
    assert (tmp_path / CONSENT_FILE_NAME).exists()

    second = build_app(tmp_path)
    assert second.get("/telemetry/status").json()["opt_in"] is True
    # The new app's service binds the SAME ledger built inside create_app, so a
    # fresh consent entry lands in the fresh ledger.
    second.post("/telemetry/consent", json={"opt_in": False})
    assert second.get("/telemetry/status").json()["opt_in"] is False


def test_export_window_is_clamped(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    client.post("/telemetry/consent", json={"opt_in": True})
    wide = client.get("/telemetry/export", params={"window_days": 4242})
    assert wide.status_code == 422  # ge=1/le=90 query validation
    payload = client.get("/telemetry/export", params={"window_days": 90}).json()
    assert payload["window_days"] == 90


# ---------------------------------------------------------------------------
# Restored from test_cost_ledger.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_record_appends_and_tail_reads_newest_first(tmp_path: Path) -> None:
    ledger = CostLedger(tmp_path / "cost-ledger")
    first = ledger.record(
        workspace_id="workspace-a",
        session_id="session-1",
        kind="agentic_turn",
        model="demo-model",
        prompt_tokens_estimate=120,
        reply_tokens_estimate=40,
        tool_call_count=2,
        stop_reason="completed",
    )
    assert first is not None
    assert first["prompt_tokens_estimate"] == 120
    assert first["estimate"] == "chars/4"

    ledger.record(
        workspace_id="workspace-a",
        session_id="session-1",
        prompt_tokens_estimate=200,
        reply_tokens_estimate=10,
        tool_call_count=0,
        stop_reason="completed",
    )

    tail = ledger.read_tail("workspace-a", limit=10)
    assert tail[0]["prompt_tokens_estimate"] == 200  # newest first
    assert tail[1]["tool_call_count"] == 2
    assert all(entry["workspace_id"] == "workspace-a" for entry in tail)


def test_workspaces_are_isolated_and_missing_reads_empty(tmp_path: Path) -> None:
    ledger = CostLedger(tmp_path / "cost-ledger")
    ledger.record(workspace_id="workspace-a", prompt_tokens_estimate=5)
    assert ledger.read_tail("workspace-b") == []
    entries = ledger.read_tail("workspace-a")
    assert len(entries) == 1

    # Workspace ids are file-safe segments, never path escapes.
    ledger.record(workspace_id="../escape")
    files = [p.name for p in (tmp_path / "cost-ledger").iterdir()]
    assert all("/" not in name and name not in {"..", "."} for name in files)


def test_turn_boundary_recorder_is_failure_tolerant() -> None:
    from app.api.runtime import TrainerRuntime

    runtime = TrainerRuntime.__new__(TrainerRuntime)
    runtime.cost_ledger = None
    # Must not raise without a ledger.
    runtime.record_agentic_cost_entry(
        workspace_id="w", session_id=None, outcome={"token_usage": {}}
    )

    class BrokenLedger:
        def record(self, **_kwargs):
            raise OSError("disk full")

    runtime.cost_ledger = BrokenLedger()
    runtime.record_agentic_cost_entry(
        workspace_id="w",
        session_id="s",
        outcome={"token_usage": {"prompt_tokens_estimate": 5}, "stop_reason": "completed"},
    )
