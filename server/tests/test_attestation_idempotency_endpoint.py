"""Host attestation endpoint: idempotency_key pass-through replays instead of
double-recording host-trusted evidence (R1)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import TrainingCardCandidateSnapshot
from app.core.settings import AppSettings
from app.main import create_app

WORKSPACE_ID = "ws-attest-idempotency"


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer attestation idempotency",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-attest-idempotency.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(_settings(tmp_path / "data"))
    card = TrainingCardCandidateSnapshot(
        card_id="card-attest-idem",
        card_type="practice",
        title="Persist the attestation path",
        target_skill="reliability",
        validation_method="Run the focused attestation test.",
        status="active",
    )
    app.state.runtime.memory_service.upsert_card(WORKSPACE_ID, card)
    return TestClient(app)


def _attest_payload(summary: str, idempotency_key: str) -> dict:
    return {
        "workspace_id": WORKSPACE_ID,
        "card_id": "card-attest-idem",
        "passed": True,
        "summary": summary,
        "tests_output": summary,
        "evidence_source": "test_runner",
        "idempotency_key": idempotency_key,
    }


def test_same_idempotency_key_replays_and_keeps_the_first_evidence(tmp_path: Path) -> None:
    client = _client(tmp_path)

    first = client.post(
        "/training/verification/attest", json=_attest_payload("first run summary", "run-7:card")
    )
    assert first.status_code == 200, first.text
    first_workspace = first.json()["workspace"]
    reliability = first_workspace["latest_training_reliability"]
    assert reliability["phase"] in {"succeeded", "acked"}
    assert reliability["idempotency_key"] == "run-7:card"
    first_revision = first_workspace["training_snapshot_revision"]
    assert first_revision >= 1

    # Same run, delivery retried: the ledger replays instead of recording a
    # second host-trusted evidence entry with the retry's payload.
    second = client.post(
        "/training/verification/attest", json=_attest_payload("retry with lost response", "run-7:card")
    )
    assert second.status_code == 200, second.text
    second_workspace = second.json()["workspace"]
    assert second_workspace["training_snapshot_revision"] == first_revision
    assert second_workspace["latest_training_reliability"]["idempotency_key"] == "run-7:card"


def test_a_new_run_key_executes_and_advances_the_ledger(tmp_path: Path) -> None:
    client = _client(tmp_path)

    first = client.post(
        "/training/verification/attest", json=_attest_payload("first run summary", "run-7:card")
    )
    assert first.status_code == 200, first.text
    first_revision = first.json()["workspace"]["training_snapshot_revision"]

    second = client.post(
        "/training/verification/attest", json=_attest_payload("second genuine run", "run-8:card")
    )
    assert second.status_code == 200, second.text
    second_workspace = second.json()["workspace"]
    assert second_workspace["training_snapshot_revision"] > first_revision
    assert second_workspace["latest_training_reliability"]["idempotency_key"] == "run-8:card"
