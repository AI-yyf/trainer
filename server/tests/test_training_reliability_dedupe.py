"""Training-reliability durability defects (2026-10-14 convergence):

1. Body-level idempotency: the single-slot replay window ends when a
   neighbouring training save replaces the slot — a resend of an
   already-executed idempotency key must never re-execute the body
   (the recorded duplicate host-evidence defect).
2. Sidecar startup expires in-flight records orphaned by the previous
   process honestly (failed/recoverable) instead of letting stale
   ``executing`` linger until timeout; succeeded records are never rewritten.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.models import TrainingCardCandidateSnapshot
from app.core.settings import AppSettings
from app.main import create_app
from app.training.reliability import begin_record, mark_executing

WORKSPACE_ID = "ws-reliability-dedupe"


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer reliability dedupe",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-reliability-dedupe.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _card() -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id="card-reliability-dedupe",
        card_type="practice",
        title="Persist through slot replacement",
        target_skill="reliability",
        validation_method="Run the focused reliability test.",
        status="active",
    )


def _attest_payload(summary: str, idempotency_key: str) -> dict:
    return {
        "workspace_id": WORKSPACE_ID,
        "card_id": "card-reliability-dedupe",
        "passed": True,
        "summary": summary,
        "tests_output": summary,
        "evidence_source": "test_runner",
        "idempotency_key": idempotency_key,
    }


def test_resend_after_slot_replacement_never_reexecutes_the_body(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    app.state.runtime.memory_service.upsert_card(WORKSPACE_ID, _card())
    client = TestClient(app)

    first = client.post("/training/verification/attest", json=_attest_payload("first run", "run-7:card"))
    assert first.status_code == 200, first.text
    first_revision = first.json()["workspace"]["training_snapshot_revision"]

    # A neighbouring training save replaces the single slot: the run-7 record
    # no longer sits on it.
    second = client.post("/training/verification/attest", json=_attest_payload("second run", "run-8:card"))
    assert second.status_code == 200, second.text
    replaced_revision = second.json()["workspace"]["training_snapshot_revision"]
    assert replaced_revision > first_revision
    assert second.json()["workspace"]["latest_training_reliability"]["idempotency_key"] == "run-8:card"

    # Delivery retry of run-7 arrives after the slot moved on: the body-level
    # ledger must replay instead of re-executing the attest body (which would
    # record the retry's payload as a second host-trusted evidence entry).
    resend = client.post("/training/verification/attest", json=_attest_payload("retry with lost response", "run-7:card"))
    assert resend.status_code == 200, resend.text
    resent_workspace = resend.json()["workspace"]
    assert resent_workspace["training_snapshot_revision"] == replaced_revision
    ledger = resent_workspace["training_reliability_dedupe"]
    assert ledger["run-7:card"]["outcome"] == "success"
    assert ledger["run-8:card"]["outcome"] == "success"


def test_a_ledgered_failure_keeps_the_retry_path_open(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    service = app.state.runtime.memory_service
    service.upsert_card(WORKSPACE_ID, _card())

    calls: list[int] = []
    body = service._record_training_practice_evaluation_result_body

    def flaky_body(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient persistence loss")
        return body(**kwargs)

    with patch.object(service, "_record_training_practice_evaluation_result_body", flaky_body):
        first = client_post_attest(
            app, _attest_payload("doomed first attempt", "run-9:card"), raise_server_exceptions=False
        )
        assert first.status_code in {200, 500}
        retry = client_post_attest(app, _attest_payload("genuine retry", "run-9:card"))
        assert retry.status_code == 200, retry.text
        retry_workspace = retry.json()["workspace"]
        assert retry_workspace["training_reliability_dedupe"]["run-9:card"]["outcome"] == "success"

        # Third delivery of the same key: the ledgered success replays — the
        # body ran exactly twice (one honest failure, one recovery).
        replay = client_post_attest(app, _attest_payload("late duplicate", "run-9:card"))
        assert replay.status_code == 200, replay.text

    assert len(calls) == 2
    assert retry_workspace["latest_training_reliability"]["idempotency_key"] == "run-9:card"


def client_post_attest(app, payload: dict, *, raise_server_exceptions: bool = True):
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    return client.post("/training/verification/attest", json=payload)


def test_startup_expires_in_flight_records_and_spares_succeeded_ones(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    app = create_app(_settings(data_dir))
    service = app.state.runtime.memory_service
    service.upsert_card(WORKSPACE_ID, _card())

    first = client_post_attest(app, _attest_payload("durable run", "run-10:card"))
    assert first.status_code == 200, first.text

    # Simulate the crash the maturity review recorded: an `executing` record
    # persisted, then the process died before any terminal transition.
    structured = service._structured_for(WORKSPACE_ID)
    orphan = mark_executing(begin_record(request_id="req-orphan", command_id="trainer.training.attest", card_id="card-reliability-dedupe"))
    service._save_training_reliability(WORKSPACE_ID, structured, orphan)

    # Restart on the same data dir: the lifespan startup sweep must expire the
    # orphan immediately and leave the durable success untouched.
    restarted = create_app(_settings(data_dir))
    with TestClient(restarted) as client:
        health = client.get("/health")
        assert health.status_code == 200, health.text

    service_after = restarted.state.runtime.memory_service
    resolved = service_after._resolve_workspace_for_write(WORKSPACE_ID)
    record = service_after._load_training_reliability(service_after._structured_for(resolved))
    assert record is not None
    assert record["phase"] == "failed"
    assert "restart" in str(record.get("error") or "")
    assert record["recoverable"] is True
    assert record["idempotency_key"] == "req-orphan"
    assert record["outcome"] == "failure"
    ledger = service_after._load_training_dedupe(service_after._structured_for(resolved))
    assert ledger["run-10:card"]["outcome"] == "success"
