"""Behavior tests for the unified Evidence contract across three stores."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import EvidenceItem
from app.core.settings import AppSettings
from app.main import create_app


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer unified evidence",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-evidence.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _seed_attempt(
    app,
    *,
    workspace_id: str,
    card_id: str,
    result: str = "success",
    trust_level: str = "self_reported",
    artifact_hash: str = "artifact-1",
) -> dict:
    store = app.state.runtime.attempt_store
    attempt = store.start_attempt(
        workspace_id=workspace_id,
        card_id=card_id,
        file_path="src/queue_lock.py",
        file_hash=artifact_hash,
    )
    evidence = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash=artifact_hash,
        result=result,
        trust_level=trust_level,
        resource_id="resource-1",
        resource_version_id="version-1",
        resource_content_hash="content-1",
        resource_location={"line": 12},
        limitations=["fixture"],
    )
    assert evidence is not None
    return evidence


def _seed_handoff(app, *, workspace_id: str, card_id: str, summary: str) -> None:
    runtime = app.state.runtime
    service = runtime.memory_service
    handoff_id = f"handoff-{card_id}"
    now = datetime.now(UTC).isoformat()
    payload = {
        "version": 3,
        "handoff_id": handoff_id,
        "card_id": card_id,
        "card_title": "Queue lock practice",
        "status": "completed",
        "verification_state": "verified",
        "return_state": "resume_training",
        "learning_phase": "return",
        "handoff_content": {
            "card_id": card_id,
            "card_title": "Queue lock practice",
            "card_type": "practice",
            "concept_practiced": "empty queue guard",
            "key_takeaway": "Check the method contract, not list.pop().",
        },
        "evidence": [
            {
                "id": f"handoff-evidence-{card_id}",
                "card_id": card_id,
                "concept": "empty queue guard",
                "content": summary,
                "source": "host_test_runner",
                "created_at": now,
                "verified": True,
                "verification_source": "host_test_runner",
                "verified_at": now,
                "schema_version": 1,
                "trust_level": "controlled_check",
                "result": "passed",
            }
        ],
    }
    structured = service._structured_for(workspace_id)
    structured._workspace["latest_training_handoff"] = payload
    service._persist_structured(workspace_id)


def _seed_memory(app, *, workspace_id: str, card_id: str, summary: str) -> EvidenceItem:
    return app.state.runtime.memory_service.enqueue_evidence(
        workspace_id,
        EvidenceItem(
            summary=summary,
            source="training_handoff_return",
            source_card_id=card_id,
            concepts=["empty queue guard"],
            outcome="pass",
            confidence=0.9,
            trust_level="self_reported",
        ),
        verified=True,
        verification_source="host_test_runner",
    )


def test_unified_evidence_normalizes_all_three_stores(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        workspace = "workspace-evidence"
        attempt_evidence = _seed_attempt(
            app,
            workspace_id=workspace,
            card_id="card-1",
        )
        _seed_handoff(
            app,
            workspace_id=workspace,
            card_id="card-1",
            summary="Guard returns None instead of raising.",
        )
        memory_item = _seed_memory(
            app,
            workspace_id=workspace,
            card_id="card-1",
            summary="Guard returns None instead of raising.",
        )

        response = client.get(
            "/evidence/records",
            params={"workspace_id": workspace, "limit": 20},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["schema_version"] == 1
        records = payload["evidence"]
        by_store = {record["source_store"]: record for record in records}
        assert set(by_store) == {"attempt", "handoff", "memory"}

        attempt = by_store["attempt"]
        assert attempt["evidence_id"] == attempt_evidence["evidence_id"]
        assert attempt["source_id"] == attempt_evidence["attempt_id"]
        assert attempt["result"] == "passed"  # success -> passed
        assert attempt["trust_level"] == "self_reported"
        assert attempt["verified"] is False
        assert attempt["artifact_hash"] == "artifact-1"
        assert attempt["resource_id"] == "resource-1"
        assert attempt["resource_version_id"] == "version-1"
        assert attempt["resource_content_hash"] == "content-1"
        assert attempt["resource_location"] == {"line": 12}
        assert attempt["limitations"] == ["fixture"]
        assert attempt["schema_version"] == 1

        handoff = by_store["handoff"]
        assert handoff["source_id"] == "handoff-card-1"
        assert handoff["trust_level"] == "controlled_check"
        assert handoff["verified"] is True
        assert handoff["result"] == "passed"
        assert handoff["verification_source"] == "host_test_runner"

        memory = by_store["memory"]
        assert memory["evidence_id"] == memory_item.id
        assert memory["trust_level"] == "controlled_check"
        assert memory["verified"] is True
        assert memory["result"] == "passed"

        # Handoff and memory carry identical content; the higher-trust store is
        # canonical and the other keeps a visible link instead of disappearing.
        assert handoff["fingerprint"] == memory["fingerprint"]
        assert memory["duplicate_of"] == handoff["evidence_id"]
        assert handoff["duplicate_of"] == ""


def test_unified_evidence_is_workspace_scoped_and_bounded(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        _seed_attempt(app, workspace_id="workspace-a", card_id="card-a")
        _seed_memory(
            app,
            workspace_id="workspace-a",
            card_id="card-a",
            summary="Workspace A evidence.",
        )

        only_a = client.get(
            "/evidence/records",
            params={"workspace_id": "workspace-a", "limit": 1},
        ).json()
        assert only_a["total"] == 1
        assert len(only_a["evidence"]) == 1
        assert all(
            record["workspace_id"] == "workspace-a"
            for record in only_a["evidence"]
        )

        other = client.get(
            "/evidence/records",
            params={"workspace_id": "workspace-b"},
        ).json()
        assert other["evidence"] == []
        assert other["total"] == 0

        # A non-positive/oversized limit is clamped, never unbounded.
        clamped = client.get(
            "/evidence/records",
            params={"workspace_id": "workspace-a", "limit": 0},
        ).json()
        assert len(clamped["evidence"]) == 1


def test_handoff_evidence_survives_persistence_with_unified_fields(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    workspace = "workspace-restart"
    _seed_handoff(
        app,
        workspace_id=workspace,
        card_id="card-restart",
        summary="Persisted handoff evidence.",
    )
    payload = app.state.runtime.memory_service._structured_for(
        workspace
    )._workspace["latest_training_handoff"]
    assert payload["version"] == 3
    assert payload["evidence"][0]["trust_level"] == "controlled_check"
    assert payload["evidence"][0]["result"] == "passed"
    assert payload["evidence"][0]["schema_version"] == 1

    with TestClient(create_app(_settings(tmp_path / "data"))) as client:
        records = client.get(
            "/evidence/records",
            params={"workspace_id": workspace},
        ).json()["evidence"]
        handoff = next(item for item in records if item["source_store"] == "handoff")
        assert handoff["trust_level"] == "controlled_check"
        assert handoff["result"] == "passed"
        assert handoff["content"] == "Persisted handoff evidence."


def test_unified_evidence_prefers_newest_first_and_keeps_unknown_honest(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        workspace = "workspace-order"
        older = _seed_attempt(
            app,
            workspace_id=workspace,
            card_id="card-old",
            artifact_hash="artifact-old",
        )
        newer = _seed_attempt(
            app,
            workspace_id=workspace,
            card_id="card-new",
            artifact_hash="artifact-new",
        )
        # Make the ordering independent of fixture execution order.
        store = app.state.runtime.attempt_store
        for evidence, created_at in (
            (older, (datetime.now(UTC) - timedelta(days=1)).isoformat()),
            (newer, datetime.now(UTC).isoformat()),
        ):
            payload = dict(evidence)
            payload["created_at"] = created_at
            store._write_evidence_row(payload["evidence_id"], payload)

        records = client.get(
            "/evidence/records",
            params={"workspace_id": workspace, "limit": 10},
        ).json()["evidence"]
        assert [item["evidence_id"] for item in records] == [
            newer["evidence_id"],
            older["evidence_id"],
        ]
        assert all(item["result"] == "passed" for item in records)
