"""Durable event ledger: restart recovery + idempotent replay.

Locks the first slice of §P1-3 convergence: the unified ledger must survive a
sidecar restart and a retried save with the same idempotency key must not append
the same learning fact twice. Undo/recompute is intentionally out of scope here.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.event_ledger import EventLedgerService
from app.core.event_ledger_store import EventLedgerStore
from app.core.settings import AppSettings
from app.main import create_app


def build_store(tmp_path: Path) -> EventLedgerStore:
    return EventLedgerStore(tmp_path / "trainer-ledger.db")


def build_app(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Ledger Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-ledger-app.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_store_persists_entries_across_service_restart(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    first = EventLedgerService(store)
    created = first.record_event(
        "learning_outcome_recorded",
        actor="system",
        scope="training",
        project_id="workspace-a",
        payload_ref={"outcome": "independent"},
        after_state_ref={"score": 0.8},
    )
    assert created.event_id.startswith("evt-")

    restarted = EventLedgerService(build_store(tmp_path))
    entries = restarted.all_entries()
    assert [entry.event_id for entry in entries] == [created.event_id]
    restored = entries[0]
    assert restored.event_type == "learning_outcome_recorded"
    assert restored.project_id == "workspace-a"
    assert restored.payload_ref == {"outcome": "independent"}
    assert restored.after_state_ref == {"score": 0.8}


def test_idempotency_key_replays_the_original_entry(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    first = service.record_event(
        "evidence_adopted",
        project_id="workspace-a",
        idempotency_key="attempt-42",
        payload_ref={"attempt_id": "attempt-42"},
    )
    replay = service.record_event(
        "evidence_adopted",
        project_id="workspace-a",
        idempotency_key="attempt-42",
        payload_ref={"attempt_id": "attempt-42"},
    )
    assert replay.event_id == first.event_id
    assert len(service.all_entries()) == 1
    assert build_store(tmp_path).count() == 1


def test_idempotency_key_replays_after_restart(tmp_path: Path) -> None:
    original = EventLedgerService(build_store(tmp_path)).record_event(
        "training_evidence_recorded",
        project_id="workspace-a",
        idempotency_key="remote-verify:card-1",
    )
    restarted = EventLedgerService(build_store(tmp_path))
    replay = restarted.record_event(
        "training_evidence_recorded",
        project_id="workspace-a",
        idempotency_key="remote-verify:card-1",
    )
    assert replay.event_id == original.event_id
    assert build_store(tmp_path).count() == 1
    assert len(restarted.all_entries()) == 1


def test_idempotency_keys_are_workspace_scoped(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    service = EventLedgerService(store)
    a = service.record_event("evidence_adopted", project_id="workspace-a", idempotency_key="k")
    b = service.record_event("evidence_adopted", project_id="workspace-b", idempotency_key="k")
    assert a.event_id != b.event_id
    assert store.count() == 2
    assert store.count(workspace_id="workspace-a") == 1
    assert store.count(workspace_id="workspace-b") == 1


def test_empty_idempotency_key_never_dedupes(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    first = service.record_event("plan_updated", project_id="workspace-a")
    second = service.record_event("plan_updated", project_id="workspace-a")
    assert first.event_id != second.event_id
    assert build_store(tmp_path).count() == 2


def test_query_and_count_still_filter_hydrated_entries(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    service.record_event("plan_updated", project_id="workspace-a", actor="learner")
    service.record_event("plan_updated", project_id="workspace-b", actor="system")
    service.record_event("resource_uploaded", project_id="workspace-a", actor="system")

    restarted = EventLedgerService(build_store(tmp_path))
    assert restarted.count(event_type="plan_updated") == 2
    assert restarted.count(project_id="workspace-b") == 1
    filtered = restarted.query(event_type="plan_updated", project_id="workspace-a")
    assert [entry.actor for entry in filtered] == ["learner"]
    assert restarted.query(limit=2) and len(restarted.query(limit=2)) == 2


def test_create_app_persists_and_replays_ledger_events(tmp_path: Path) -> None:
    first_client = build_app(tmp_path)
    ledger = first_client.app.state.runtime.event_ledger
    original = ledger.record_event(
        "learning_outcome_recorded",
        project_id="workspace-a",
        idempotency_key="turn-7",
    )

    second_client = build_app(tmp_path)
    restarted_ledger = second_client.app.state.runtime.event_ledger
    assert [entry.event_id for entry in restarted_ledger.all_entries()] == [original.event_id]
    replay = restarted_ledger.record_event(
        "learning_outcome_recorded",
        project_id="workspace-a",
        idempotency_key="turn-7",
    )
    assert replay.event_id == original.event_id
    assert len(restarted_ledger.all_entries()) == 1


def test_reversal_is_append_only_and_idempotent(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    original = service.record_event(
        "plan_updated",
        project_id="workspace-a",
        reversibility="reversible",
    )
    reversal = service.reverse_event(original.event_id, reason="wrong plan")
    assert reversal is not None
    assert reversal.event_type == "event_reversed"
    assert reversal.payload_ref["reversed_event_id"] == original.event_id
    assert service.is_reversed(original.event_id)

    replay = service.reverse_event(original.event_id, reason="wrong plan")
    assert replay is not None
    assert replay.event_id == reversal.event_id
    assert build_store(tmp_path).count() == 2  # original + one reversal


def test_irreversible_or_unknown_events_cannot_be_reversed(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    locked = service.record_event("plan_updated", project_id="workspace-a")
    assert service.reverse_event(locked.event_id) is None
    assert service.reverse_event("evt-does-not-exist") is None
    assert not service.is_reversed(locked.event_id)


def test_effective_entries_exclude_reversed_events(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    kept = service.record_event("resource_uploaded", project_id="workspace-a", reversibility="reversible")
    dropped = service.record_event("resource_uploaded", project_id="workspace-a", reversibility="reversible")
    service.reverse_event(dropped.event_id)

    effective_ids = [entry.event_id for entry in service.effective_entries()]
    assert effective_ids == [kept.event_id]
    assert len(service.all_entries()) == 3  # both originals + the reversal


def test_reversal_survives_restart(tmp_path: Path) -> None:
    original = EventLedgerService(build_store(tmp_path)).record_event(
        "plan_updated",
        project_id="workspace-a",
        reversibility="reversible",
    )
    first = EventLedgerService(build_store(tmp_path))
    first.reverse_event(original.event_id, reason="superseded")

    restarted = EventLedgerService(build_store(tmp_path))
    assert restarted.is_reversed(original.event_id)
    assert [entry.event_id for entry in restarted.effective_entries()] == []
    again = restarted.reverse_event(original.event_id)
    assert again is not None and again.event_type == "event_reversed"
    assert build_store(tmp_path).count() == 2


def test_replay_recomputes_without_reversed_entries(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    first = service.record_event("resource_uploaded", project_id="workspace-a", reversibility="reversible")
    service.record_event("resource_uploaded", project_id="workspace-a", reversibility="reversible")
    service.reverse_event(first.event_id)

    counts = service.replay({}, lambda acc, entry: {**acc, entry.event_type: acc.get(entry.event_type, 0) + 1})
    assert counts == {"resource_uploaded": 1}


def test_telemetry_export_ignores_reversed_events(tmp_path: Path) -> None:
    from app.telemetry.service import TelemetryService

    ledger = EventLedgerService(build_store(tmp_path))
    telemetry = TelemetryService(ledger, tmp_path)
    telemetry.set_opt_in(True, source="settings")
    event = ledger.record_event(
        "resource_uploaded",
        project_id="workspace-a",
        reversibility="reversible",
    )
    assert telemetry.build_export(window_days=7)["by_event"].get("resource_uploaded") == 1

    ledger.reverse_event(event.event_id, reason="upload retracted")
    assert "resource_uploaded" not in telemetry.build_export(window_days=7)["by_event"]
