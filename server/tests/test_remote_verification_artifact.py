from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from test_project_provisioning import _client
from test_remote_project_admission import _payload

from app.core.models import TrainingCardCandidateSnapshot


def _admit(client, tmp_path: Path) -> dict:
    payload = _payload(client, tmp_path / "brain", "vscode-remote://ssh-remote+owned/tmp/project")
    response = client.post("/workspace/remote/adopt", json=payload)
    assert response.status_code == 200, response.text
    provision = response.json()["project_provisioning"]
    client.app.state.runtime.memory_service.upsert_card(provision["context_id"], TrainingCardCandidateSnapshot(
        card_id="owned-card", card_type="practice", title="Verify actual remote bytes",
        target_skill="reliability", validation_method="Run the owned file", status="active",
    ))
    return provision


def _artifact() -> dict[str, str]:
    return {"workspace_uri": "vscode-remote://ssh-remote+owned/tmp/project",
            "artifact_uri": "vscode-remote://ssh-remote+owned/tmp/project/practice.py",
            "sha256": "a" * 64, "companion_session_id": "owned-run", "execution_location": "remote"}


def _attest(provision: dict, artifact: dict | None) -> dict:
    payload = {"workspace_id": provision["context_id"], "session_id": provision["agent_session_id"],
               "card_id": "owned-card", "passed": True, "evidence_source": "test_runner",
               "summary": "Actual remote process passed", "idempotency_key": "remote-verify:owned-run:owned-card"}
    if artifact is not None:
        payload["verification_artifact"] = artifact
    return payload


def test_remote_artifact_survives_replay_restart_reflect_and_return(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        provision = _admit(client, tmp_path)
        payload = _attest(provision, _artifact())
        first = client.post("/training/verification/attest", json=payload)
        assert first.status_code == 200, first.text
        workspace = first.json()["workspace"]
        assert workspace["latest_training_verification"]["verification_artifact"] == _artifact()
        assert workspace["latest_training_handoff"]["verification_artifact"] == _artifact()
        repeat = client.post("/training/verification/attest", json=payload)
        assert repeat.status_code == 200
        assert repeat.json()["workspace"] == workspace
    with _client(tmp_path) as restarted:
        service = restarted.app.state.runtime.memory_service
        restored = service.snapshot(provision["context_id"]).workspace
        assert restored["latest_training_verification"]["verification_artifact"] == _artifact()
        reflected = service.record_training_handoff_reflection(
            workspace_id=provision["context_id"], card_id="owned-card",
            reflection="I checked the exact file hash and understand this boundary.",
        )
        assert reflected["latest_training_handoff"]["verification_artifact"] == _artifact()
        returned = service.return_training_handoff(workspace_id=provision["context_id"], card_id="owned-card")
        assert returned["latest_training_handoff"]["verification_state"] == "verified"
        evidence = next(item for item in service.evidence_queue(provision["context_id"]).pending if item.source_card_id == "owned-card")
        assert evidence.verified
        assert evidence.model_dump()["verification_artifact"] == _artifact()
        evidence_before = [item.model_dump() for item in service.evidence_queue(provision["context_id"]).pending]
        handoff_before = dict(returned["latest_training_handoff"])
        resubmission = restarted.post("/training/practice-return", json={
            "workspace_id": provision["context_id"], "card_id": "owned-card", "passed": True,
            "summary": "Later self-reported completion", "evidence_source": "self_reported",
            "next_step": "Continue", "focus_area": "reliability",
        })
        assert resubmission.status_code == 200, resubmission.text
        assert resubmission.json()["workspace"]["latest_training_handoff"] == handoff_before
        assert [item.model_dump() for item in service.evidence_queue(provision["context_id"]).pending] == evidence_before
    for _ in range(2):
        with _client(tmp_path) as after_return_restart:
            service = after_return_restart.app.state.runtime.memory_service
            restored_evidence = [
                item.model_dump()
                for item in service.evidence_queue(provision["context_id"]).pending
            ]
            assert restored_evidence == evidence_before
            repeated_return = after_return_restart.post("/training/return", json={
                "workspace_id": provision["context_id"], "card_id": "owned-card",
            })
            assert repeated_return.status_code == 200, repeated_return.text
            repeated_handoff = repeated_return.json()["workspace"]["latest_training_handoff"]
            for key in ("handoff_id", "card_id", "returned_at", "verification_state", "evidence", "verification_artifact"):
                assert repeated_handoff[key] == handoff_before[key]
            repeated_self_report = after_return_restart.post("/training/practice-return", json={
                "workspace_id": provision["context_id"], "card_id": "owned-card",
                "passed": True, "summary": "Repeated self-report after restart",
                "evidence_source": "self_reported", "focus_area": "reliability",
            })
            assert repeated_self_report.status_code == 200, repeated_self_report.text
            assert repeated_self_report.json()["workspace"]["latest_training_handoff"] == repeated_handoff
            assert [
                item.model_dump()
                for item in service.evidence_queue(provision["context_id"]).pending
            ] == evidence_before
            with sqlite3.connect(tmp_path / "trainer-provisioning-test.db") as connection:
                row = connection.execute(
                    "SELECT payload FROM structured_memory WHERE workspace_id = ?",
                    (provision["context_id"],),
                ).fetchone()
            persisted = json.loads(row[0])
            assert persisted["evidence_items"] == evidence_before
            assert persisted["workspace"]["latest_training_handoff"] == repeated_handoff


@pytest.mark.parametrize("failure", ["missing", "hash", "session", "authority", "project", "traversal", "local"])
def test_unbound_remote_artifact_never_writes_trusted_evidence(tmp_path: Path, failure: str) -> None:
    with _client(tmp_path) as client:
        provision = _admit(client, tmp_path)
        artifact = _artifact()
        if failure == "hash":
            artifact["sha256"] = "unknown"
        elif failure == "session":
            artifact["companion_session_id"] = ""
        elif failure == "authority":
            artifact["artifact_uri"] = "vscode-remote://ssh-remote+foreign/tmp/project/practice.py"
        elif failure == "project":
            artifact["artifact_uri"] = "vscode-remote://ssh-remote+owned/tmp/project-other/practice.py"
        elif failure == "traversal":
            artifact["artifact_uri"] = "vscode-remote://ssh-remote+owned/tmp/project/%2e%2e/practice.py"
        elif failure == "local":
            artifact["execution_location"] = "local"
        response = client.post("/training/verification/attest", json=_attest(provision, None if failure == "missing" else artifact))
        assert response.status_code == 422, response.text
        workspace = client.app.state.runtime.memory_service.snapshot(provision["context_id"]).workspace
        assert "latest_training_verification" not in workspace
        assert "latest_training_reliability" not in workspace


def test_remote_artifact_cannot_be_attested_into_another_provisioned_context(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = _admit(client, tmp_path)
        payload = _payload(client, tmp_path / "brain", "vscode-remote://ssh-remote+owned/tmp/other", alias="other")
        other = client.post("/workspace/remote/adopt", json=payload).json()["project_provisioning"]
        request = _attest(other, _artifact())
        request["card_id"] = "owned-card"
        response = client.post("/training/verification/attest", json=request)
        assert response.status_code == 422
        assert "latest_training_verification" not in client.app.state.runtime.memory_service.snapshot(first["context_id"]).workspace


def test_completed_local_return_self_report_preserves_trusted_evidence(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        workspace_id = "local-replay-workspace"
        service = client.app.state.runtime.memory_service
        service.upsert_card(workspace_id, TrainingCardCandidateSnapshot(
            card_id="local-card", card_type="practice", title="Keep the verified result",
            target_skill="reliability", status="active",
        ))
        attested = client.post("/training/verification/attest", json={
            "workspace_id": workspace_id, "card_id": "local-card", "passed": True,
            "evidence_source": "test_runner", "summary": "Local test passed",
            "idempotency_key": "local-verify:owned-run:local-card",
        })
        assert attested.status_code == 200, attested.text
        reflected = client.post("/training/reflect", json={
            "workspace_id": workspace_id, "card_id": "local-card",
            "reflection": "The trusted test checked the boundary before returning.",
        })
        assert reflected.status_code == 200, reflected.text
        returned = client.post("/training/return", json={
            "workspace_id": workspace_id, "card_id": "local-card",
        })
        assert returned.status_code == 200, returned.text
        handoff = dict(returned.json()["workspace"]["latest_training_handoff"])
        before = [item.model_dump() for item in service.evidence_queue(workspace_id).pending]
        assert len(before) == 1 and before[0]["verified"] is True
        repeated = client.post("/training/practice-return", json={
            "workspace_id": workspace_id, "card_id": "local-card", "passed": True,
            "summary": "Later self-reported completion", "evidence_source": "self_reported",
            "next_step": "Continue", "focus_area": "reliability",
        })
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["workspace"]["latest_training_handoff"] == handoff
        assert [item.model_dump() for item in service.evidence_queue(workspace_id).pending] == before
