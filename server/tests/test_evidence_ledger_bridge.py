"""Training evidence joins the unified ledger (§P1-3c).

Every recorded controlled check is a learning fact: it must be auditable in
the same ledger as goals and coach turns, with the evidence id as the
idempotency key, and a superseded evidence must emit its own reversal-style
event so the ledger can reconstruct the live set.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Evidence Ledger Test",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="evidence-ledger.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _ledger(app):
    return app.state.runtime.event_ledger


def _recorded_events(app) -> list[dict]:
    return [
        {"payload": entry.payload_ref, "event_id": entry.event_id}
        for entry in _ledger(app).all_entries()
        if entry.event_type == "training_evidence_recorded"
    ]


def build_app(tmp_path: Path) -> TestClient:
    settings = _settings(tmp_path)
    return TestClient(create_app(settings))


def test_evidence_records_a_ledger_event(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    store = client.app.state.runtime.attempt_store
    attempt = store.start_attempt(workspace_id="w-ev", card_id="card-1")
    evidence = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-1",
        result="passed",
        trust_level="controlled_check",
        dimension="implementation",
    )
    assert evidence is not None

    events = _recorded_events(client.app)
    assert len(events) == 1
    assert events[0]["payload"]["evidence_id"] == evidence["evidence_id"]
    assert events[0]["payload"]["result"] == "passed"
    assert events[0]["payload"]["trust_level"] == "controlled_check"


def test_failed_reversal_rolls_back_evidence_and_ledger_together(tmp_path: Path, monkeypatch) -> None:
    client = build_app(tmp_path)
    store = client.app.state.runtime.attempt_store
    ledger = _ledger(client.app)
    attempt = store.start_attempt(workspace_id="w-ev", card_id="card-1")
    first = store.record_evidence(
        attempt_id=attempt["attempt_id"], artifact_hash="hash-1", result="passed",
    )
    before = ledger.all_entries()
    reverse = ledger.reverse_by_idempotency_key

    def unavailable(*args, **kwargs):
        reverse(*args, **kwargs)
        raise RuntimeError("Ledger write failed")

    monkeypatch.setattr(ledger, "reverse_by_idempotency_key", unavailable)
    with pytest.raises(RuntimeError, match="Ledger write failed"):
        store.record_evidence(
            attempt_id=attempt["attempt_id"], artifact_hash="hash-2", result="failed",
        )

    assert ledger.all_entries() == before
    evidence = store.list_evidence(attempt["attempt_id"])
    assert len(evidence) == 1
    assert evidence[0]["evidence_id"] == first["evidence_id"]
    assert evidence[0]["is_current"] is True


def test_evidence_event_is_idempotent_per_evidence_id(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    store = client.app.state.runtime.attempt_store
    attempt = store.start_attempt(workspace_id="w-ev", card_id="card-1")
    evidence = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-1",
        result="passed",
        trust_level="controlled_check",
    )
    # The same evidence id can never be recorded twice (primary key), but the
    # ledger bridge must also be replay-safe if a caller re-emits it.
    client.app.state.runtime.event_ledger.record_event(
        "training_evidence_recorded",
        actor="system",
        scope="training",
        workspace_id="w-ev",
        payload_ref={"evidence_id": evidence["evidence_id"]},
        idempotency_key=f"training_evidence_recorded:{evidence['evidence_id']}",
    )
    events = _recorded_events(client.app)
    assert len(events) == 1


def test_superseded_evidence_is_reversed_for_replay(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    store = client.app.state.runtime.attempt_store
    attempt = store.start_attempt(workspace_id="w-ev", card_id="card-1")
    stale = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-1",
        result="passed",
        trust_level="controlled_check",
    )
    fresh = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-2",
        result="passed",
        trust_level="controlled_check",
    )

    stale_ledger_event_id = next(
        entry.event_id
        for entry in _ledger(client.app).all_entries()
        if entry.event_type == "training_evidence_recorded"
        and entry.payload_ref.get("evidence_id") == stale["evidence_id"]
    )
    effective_ids = [
        entry.payload_ref.get("evidence_id")
        for entry in _ledger(client.app).effective_entries()
        if entry.event_type == "training_evidence_recorded"
    ]
    assert effective_ids == [fresh["evidence_id"]]
    reversal_events = [
        entry
        for entry in _ledger(client.app).all_entries()
        if entry.event_type == "event_reversed"
    ]
    assert [
        entry.payload_ref.get("reversed_event_id") for entry in reversal_events
    ] == [stale_ledger_event_id]


def test_reversal_persists_across_app_restart(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    first = create_app(_settings(data_dir))
    store = first.state.runtime.attempt_store
    attempt = store.start_attempt(workspace_id="w-ev", card_id="card-1")
    stale = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-1",
        result="passed",
        trust_level="controlled_check",
    )
    fresh = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-2",
        result="passed",
        trust_level="controlled_check",
    )

    restarted = create_app(_settings(data_dir))
    stale_ledger_event_id = next(
        entry.event_id
        for entry in restarted.state.runtime.event_ledger.all_entries()
        if entry.event_type == "training_evidence_recorded"
        and entry.payload_ref.get("evidence_id") == stale["evidence_id"]
    )
    effective_ids = [
        entry.payload_ref.get("evidence_id")
        for entry in restarted.state.runtime.event_ledger.effective_entries()
        if entry.event_type == "training_evidence_recorded"
    ]
    assert effective_ids == [fresh["evidence_id"]]
    assert stale["evidence_id"] not in effective_ids
    reversals = [
        entry
        for entry in restarted.state.runtime.event_ledger.all_entries()
        if entry.event_type == "event_reversed"
        and entry.payload_ref.get("reversed_event_id") == stale_ledger_event_id
    ]
    assert len(reversals) == 1
