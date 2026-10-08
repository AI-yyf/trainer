from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from test_project_provisioning import _client
from test_remote_verification_artifact import _admit, _artifact, _attest

from app.memory.service import StructuredMemoryService


def _returned(client, tmp_path: Path) -> tuple[dict, dict]:
    provision = _admit(client, tmp_path)
    workspace_id = provision["context_id"]
    attested = client.post("/training/verification/attest", json=_attest(provision, _artifact()))
    assert attested.status_code == 200, attested.text
    reflected = client.post("/training/reflect", json={
        "workspace_id": workspace_id, "card_id": "owned-card",
        "reflection": "The exact owned hash is the original trusted observation.",
    })
    assert reflected.status_code == 200, reflected.text
    returned = client.post("/training/return", json={
        "workspace_id": workspace_id, "card_id": "owned-card",
    })
    assert returned.status_code == 200, returned.text
    payload = client.app.state.runtime.repository.load_structured_memory(workspace_id)
    assert payload is not None
    return provision, payload


def test_stripped_return_artifact_recovers_from_original_trusted_persistence(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        provision, payload = _returned(client, tmp_path)
        expected = deepcopy(payload["evidence_items"])
        payload["evidence_items"][0].pop("verification_artifact")
        client.app.state.runtime.repository.save_structured_memory(provision["context_id"], payload)
    for _ in range(2):
        with _client(tmp_path) as restarted:
            service = restarted.app.state.runtime.memory_service
            restored = [item.model_dump() for item in service.evidence_queue(provision["context_id"]).pending]
            assert restored == expected
            replay = restarted.post("/training/practice-return", json={
                "workspace_id": provision["context_id"], "card_id": "owned-card",
                "passed": True, "summary": "Untrusted replay", "evidence_source": "self_reported",
            })
            assert replay.status_code == 200, replay.text
            persisted = restarted.app.state.runtime.repository.load_structured_memory(provision["context_id"])
            assert persisted["evidence_items"] == expected
            assert persisted["workspace"]["latest_training_handoff"] == payload["workspace"]["latest_training_handoff"]


@pytest.mark.parametrize("mismatch", [
    "artifact", "older_row", "ambiguous", "workspace", "summary", "source", "unverified", "incomplete",
])
def test_ambiguous_or_unbound_persisted_rows_are_never_reconstructed(tmp_path: Path, mismatch: str) -> None:
    with _client(tmp_path) as client:
        _, payload = _returned(client, tmp_path)
    row = payload["evidence_items"][0]
    row.pop("verification_artifact")
    if mismatch == "artifact":
        payload["workspace"]["latest_training_handoff"]["verification_artifact"]["companion_session_id"] = "another-run"
    elif mismatch == "older_row":
        row["timestamp"] = "2000-01-01T00:00:00+00:00"
    elif mismatch == "ambiguous":
        duplicate = deepcopy(row)
        duplicate["id"] = "another-evidence-row"
        payload["evidence_items"].append(duplicate)
    elif mismatch == "workspace":
        row["workspace_id"] = "another-context"
    elif mismatch == "summary":
        row["summary"] = "A different verification"
    elif mismatch == "source":
        row["verification_source"] = "self_reported"
    elif mismatch == "unverified":
        row["verified"] = False
    elif mismatch == "incomplete":
        payload["workspace"]["latest_training_handoff"]["status"] = "active"
    restored = StructuredMemoryService.from_state(payload).export_state()
    assert len(restored["evidence_items"]) == len(payload["evidence_items"])
    assert all(item["verification_artifact"] is None for item in restored["evidence_items"])
