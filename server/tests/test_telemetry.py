"""Opt-in anonymous telemetry (P2 #18) — consent lifecycle + fail-closed export.

Locks the design rules of ``app/telemetry/service.py``:

- consent defaults off and is durable across app restarts on the same data dir;
- consent changes are appended (capped) and idempotent — a repeat call with
  the same answer extends neither history nor ledger;
- a consent-less machine exports an EMPTY payload (no counts can leak);
- an opted-in export is coarse: whitelist event names only, a daily series,
  and no consent history / identifiers / paths / keys anywhere;
- unknown ledger event types are dropped, never bucketed into ``other``.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.event_ledger import EVENT_RESOURCE_UPLOADED
from app.core.settings import AppSettings
from app.main import create_app
from app.telemetry.service import CONSENT_FILE_NAME

FORBIDDEN_SUBSTRINGS = ("path", "content", "api", "key", "token", "email", "user_id", "workspace")


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


def test_opt_out_export_is_fail_closed(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    ledger = client.app.state.runtime.event_ledger
    ledger.record_event(EVENT_RESOURCE_UPLOADED)
    ledger.record_event("some_unknown_future_event")
    payload = client.get("/telemetry/export", params={"window_days": 7}).json()
    assert payload["schema"] == "trainer.telemetry.v1"
    assert payload["opt_in"] is False
    assert payload["daily"] == []
    assert payload["by_event"] == {}
    assert payload["total_events"] == 0
    # The schema must stay constant even when the machine is dark.
    body = json.dumps(payload, ensure_ascii=False)
    assert "resource_uploaded" not in body


def test_consent_then_export_aggregates_whitelisted_counts(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    status = client.post("/telemetry/consent", json={"opt_in": True, "source": "settings"}).json()
    assert status["opt_in"] is True
    assert status["consent_changes"] == 1
    ledger = client.app.state.runtime.event_ledger
    ledger.record_event(EVENT_RESOURCE_UPLOADED)
    ledger.record_event(EVENT_RESOURCE_UPLOADED)
    ledger.record_event("not_a_known_event")
    payload = client.get("/telemetry/export", params={"window_days": 3}).json()
    assert payload["opt_in"] is True
    assert payload["window_days"] == 3
    # The consent change itself is a ledger event and is counted like the rest.
    assert payload["by_event"] == {"telemetry_consent_changed": 1, EVENT_RESOURCE_UPLOADED: 2}
    assert payload["unknown_ledger_events_dropped"] == 1
    assert payload["total_events"] == 3  # sum(by_event): consent + 2 uploads
    assert len(payload["daily"]) == 3
    assert all(item["events"] >= 0 and len(item["date"]) == 10 for item in payload["daily"])
    body = json.dumps(payload, ensure_ascii=False).lower()
    for needle in FORBIDDEN_SUBSTRINGS:
        assert needle not in body, needle
    # Consent HISTORY (the audit trail) must never travel in the export
    # payload, while the event NAME telemetry_consent_changed may (it is a
    # coarse counter key, not data).
    assert not any(
        isinstance(value, list) and value and isinstance(value[0], dict) and "at" in value[0]
        for value in payload.values()
    )


def test_consent_is_idempotent_and_history_is_capped(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    for _ in range(3):
        status = client.post("/telemetry/consent", json={"opt_in": False}).json()
    assert status["consent_changes"] == 0
    ledger = client.app.state.runtime.event_ledger
    for flag in (True, False, True, False):
        client.post("/telemetry/consent", json={"opt_in": flag})
    for _ in range(60):
        client.post("/telemetry/consent", json={"opt_in": True})
        client.post("/telemetry/consent", json={"opt_in": False})
    state = json.loads((tmp_path / CONSENT_FILE_NAME).read_text(encoding="utf-8"))
    assert len(state["history"]) <= 50
    assert state["history"][-1]["opted_in"] is False
    assert state["history"][-1]["source"] == "unspecified"
    consent_events = [
        entry for entry in ledger.all_entries() if entry.event_type == "telemetry_consent_changed"
    ]
    assert consent_events and consent_events[-1].payload_ref == {"opted_in": False, "source": "unspecified"}


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


def test_runtime_without_telemetry_service_fails_closed(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    runtime = client.app.state.runtime
    runtime.telemetry_service = None
    assert client.get("/telemetry/status").status_code == 503
    assert client.get("/telemetry/export").status_code == 503
    assert client.post("/telemetry/consent", json={"opt_in": True}).status_code == 503


def test_export_window_is_clamped(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    client.post("/telemetry/consent", json={"opt_in": True})
    wide = client.get("/telemetry/export", params={"window_days": 4242})
    assert wide.status_code == 422  # ge=1/le=90 query validation
    payload = client.get("/telemetry/export", params={"window_days": 90}).json()
    assert payload["window_days"] == 90
