"""Training evidence joins the unified ledger (§P1-3c).

Every recorded controlled check is a learning fact: it must be auditable in
the same ledger as goals and coach turns, with the evidence id as the
idempotency key, and a superseded evidence must emit its own reversal-style
event so the ledger can reconstruct the live set.
"""

from __future__ import annotations

from pathlib import Path

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


def _events_by_type(app, event_type: str) -> list[dict]:
    return [
        {"payload": entry.payload_ref, "id": entry.event_id}
        for entry in _ledger(app).all_entries()
        if entry.event_type == event_type
    ]


def test_evidence_records_a_ledger_event(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    store = app.state.runtime.attempt_store
    attempt = store.start_attempt(workspace_id="w-ev", card_id="card-1")
    evidence = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-1",
        result="passed",
        trust_level="controlled_check",
        dimension="implementation",
    )
    assert evidence is not None

    events = _events_by_type(app, "training_evidence_recorded")
    assert len(events) == 1
    assert events[0]["payload"]["evidence_id"] == evidence["evidence_id"]
    assert events[0]["payload"]["result"] == "passed"
    assert events[0]["payload"]["trust_level"] == "controlled_check"


def test_evidence_event_is_idempotent_per_evidence_id(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    store = app.state.runtime.attempt_store
    attempt = store.start_attempt(workspace_id="w-ev", card_id="card-1")
    evidence = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-1",
        result="passed",
        trust_level="controlled_check",
    )
    # The same evidence id can never be recorded twice (primary key), but the
    # ledger bridge must also be replay-safe if a caller re-emits it.
    app.state.runtime.event_ledger.record_event(
        "training_evidence_recorded",
        actor="system",
        scope="training",
        workspace_id="w-ev",
        payload_ref={"evidence_id": evidence["evidence_id"]},
        idempotency_key=f"training_evidence_recorded:{evidence['evidence_id']}",
    )
    events = _events_by_type(app, "training_evidence_recorded")
    assert len(events) == 1


def test_superseded_evidence_records_a_reversal_event(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    store = app.state.runtime.attempt_store
    attempt = store.start_attempt(workspace_id="w-ev", card_id="card-1")
    stale = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-1",
        result="passed",
        trust_level="controlled_check",
    )
    store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-2",
        result="failed",
        trust_level="controlled_check",
    )

    superseded_events = _events_by_type(app, "training_evidence_superseded")
    assert len(superseded_events) == 1
    assert superseded_events[0]["payload"]["evidence_id"] == stale["evidence_id"]

    recorded_events = _events_by_type(app, "training_evidence_recorded")
    assert len(recorded_events) == 2


def test_evidence_ledger_persists_across_app_restart(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    first = create_app(_settings(data_dir))
    store = first.state.runtime.attempt_store
    attempt = store.start_attempt(workspace_id="w-ev", card_id="card-1")
    store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-1",
        result="passed",
        trust_level="controlled_check",
        evidence_kind="controlled_evaluation",
    )

    restarted = create_app(_settings(data_dir))
    entries = [
        entry
        for entry in restarted.state.runtime.event_ledger.all_entries()
        if entry.event_type == "training_evidence_recorded"
    ]
    assert len(entries) == 1
    assert entries[0].payload_ref.get("evidence_kind") == "controlled_evaluation"
