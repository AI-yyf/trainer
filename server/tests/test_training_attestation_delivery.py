"""Public host attestation delivery preserves the per-run replay identity."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.models import TrainingCardCandidateSnapshot
from app.core.settings import AppSettings
from app.main import create_app


def _app(tmp_path):
    return create_app(AppSettings(
        app_name="Host attestation replay", host="127.0.0.1", port=8765,
        data_dir=tmp_path, database_name="attestation.db", default_session_stage="intake",
        summary_message_limit=6, enable_network_fetch=False,
    ))


@pytest.mark.parametrize("key_field", ["idempotency_key", "idempotencyKey"])
@pytest.mark.parametrize("passed", [True, False])
def test_host_attestation_retry_replays_without_recording_a_second_result(
    tmp_path, key_field, passed
):
    app = _app(tmp_path)
    runtime = app.state.runtime
    workspace_id = "host-attestation-replay"
    with TestClient(app) as client:
        start = client.post("/session/start", json={
            "workspace_id": workspace_id, "workspace_name": workspace_id,
        })
        assert start.status_code == 200, start.text
        card = runtime.memory_service.upsert_card(workspace_id, TrainingCardCandidateSnapshot(
            card_id="host-replay-card", card_type="practice", title="Verify one boundary",
            target_skill="reliability", validation_method="Run the focused test", status="active",
        ))
        payload = {
            "workspace_id": workspace_id, "card_id": card.card_id,
            "evidence_source": "test_runner", "tests_output": "exit 0" if passed else "exit 1",
            "passed": passed, key_field: f"remote-verify:run-1:{card.card_id}",
        }
        service = runtime.memory_service
        with patch.object(service, "_record_training_practice_evaluation_result_body",
                          wraps=service._record_training_practice_evaluation_result_body) as record:
            first = client.post("/training/verification/attest", json=payload)
            assert first.status_code == 200, first.text
            persisted = runtime.repository.load_structured_memory(workspace_id)
            second = client.post("/training/verification/attest", json=payload)
            assert second.status_code == 200, second.text
            assert record.call_count == 1
            assert runtime.repository.load_structured_memory(workspace_id) == persisted
        assert second.json()["workspace"] == first.json()["workspace"]
        ledger = service.latest_training_reliability(workspace_id)
        assert ledger["idempotency_key"] == payload[key_field]


def test_invalid_attestation_source_never_reaches_the_replay_ledger(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        service = app.state.runtime.memory_service
        with patch.object(service, "record_training_practice_evaluation_result") as record:
            response = client.post("/training/verification/attest", json={
                "workspace_id": "invalid-host-source", "card_id": "card",
                "passed": True, "evidence_source": "self_reported",
                "idempotency_key": "remote-verify:run-2:card",
            })
        assert response.status_code == 422
        record.assert_not_called()
