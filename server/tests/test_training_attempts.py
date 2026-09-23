"""Phase-D slice tests: training attempt persistence, evidence binding
(TR-049/TR-059 semantics) and the per-instance RPC auth token (TR-077)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.training.attempt_store import AttemptStore


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-attempts.db",
        default_session_stage="intake",
        summary_message_limit=6,
    )


# ---------------------------------------------------------------------------
# Attempt store lifecycle (TR-049 persistence contract)
# ---------------------------------------------------------------------------


def test_attempt_lifecycle_persists_answer_and_assistance(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "attempts.db")
    attempt = store.start_attempt(
        workspace_id="ws-1",
        card_id="card-1",
        file_path="src/q_learning.py",
        file_hash="hash-v1",
        assistance_level="hint_level_2",
    )
    assert attempt["status"] == "active"
    assert attempt["assistance_level"] == "hint_level_2"

    updated = store.update_attempt(
        attempt["attempt_id"],
        answer_draft="My draft answer",
        assistance_level="hint_level_3",
        status="answered",
    )
    assert updated["answer_draft"] == "My draft answer"
    assert updated["assistance_level"] == "hint_level_3"
    assert updated["status"] == "answered"

    loaded = store.get_attempt(attempt["attempt_id"])
    assert loaded is not None
    assert loaded["answer_draft"] == "My draft answer"
    assert loaded["file_path"] == "src/q_learning.py"


# ---------------------------------------------------------------------------
# TR-059: evidence version expiry semantics
# ---------------------------------------------------------------------------


def test_evidence_supersedes_previous_and_flags_expiry_on_hash_change(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "attempts.db")
    attempt = store.start_attempt(
        workspace_id="ws-1",
        card_id="card-1",
        file_hash="hash-version-A",
    )

    first = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-version-A",
        result="passed",
        runner_version="pytest/8",
        execution_location="workspace",
        trust_level="controlled_check",
    )
    assert first["is_current"] is True
    assert first["superseded_by_evidence_id"] is None

    # Learner edits the file: the old pass no longer counts for this version.
    store.update_attempt(attempt["attempt_id"], file_hash="hash-version-B")

    items = store.list_evidence(attempt["attempt_id"])
    assert [item["is_current"] for item in items] == [False], (
        "evidence bound to the old artifact version must not read as current",
    )

    second = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-version-B",
        result="passed",
    )
    assert second["is_current"] is True
    assert first["evidence_id"] != second["evidence_id"]
    # ...and recording the new pass supersedes the stale one explicitly.
    refreshed = store.list_evidence(attempt["attempt_id"])
    stale = next(item for item in refreshed if item["evidence_id"] == first["evidence_id"])
    assert stale["superseded_by_evidence_id"] == second["evidence_id"]
    assert stale["artifact_hash"] == "hash-version-A"


def test_evidence_record_requires_known_attempt(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "attempts.db")
    assert (
        store.record_evidence(
            attempt_id="attempt-missing",
            artifact_hash="hash",
            result="passed",
        )
        is None
    )


# ---------------------------------------------------------------------------
# Endpoints + TR-077 per-instance token
# ---------------------------------------------------------------------------


@pytest.fixture()
def tokened_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", "unit-test-token")
    app = create_app(_settings(tmp_path))
    return TestClient(app)


def test_rpc_rejects_requests_without_the_instance_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", "unit-test-token")
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 401
    assert "per-instance token" in response.json()["detail"]

    authorized = client.get("/health", headers={"x-trainer-token": "unit-test-token"})
    assert authorized.status_code == 200


def test_attempt_endpoints_require_and_accept_the_instance_token(tokened_client: TestClient) -> None:
    start = tokened_client.post(
        "/training/attempt/start",
        json={"workspace_id": "ws-default", "card_id": "card-1"},
    )
    assert start.status_code == 401, "untokenized attempt start must be rejected"

    authorized = tokened_client.post(
        "/training/attempt/start",
        headers={"x-trainer-token": "unit-test-token"},
        json={"workspace_id": "ws-default", "card_id": "card-1"},
    )
    assert authorized.status_code == 200
    attempt = authorized.json()["attempt"]
    assert attempt["status"] == "active"

    fetched = tokened_client.get(
        f"/training/attempt/{attempt['attempt_id']}",
        headers={"x-trainer-token": "unit-test-token"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["attempt"]["card_id"] == "card-1"


def test_projection_aggregates_distinct_attempts_for_repeat_verification(
    tokened_client: TestClient,
) -> None:
    headers = {"x-trainer-token": "unit-test-token"}
    first_start = tokened_client.post(
        "/training/attempt/start",
        headers=headers,
        json={
            "workspace_id": "ws-repeat",
            "card_id": "card-repeat",
            "file_hash": "hash-1",
        },
    )
    assert first_start.status_code == 200
    first = first_start.json()["attempt"]

    first_evidence = tokened_client.post(
        "/training/attempt/evidence",
        headers=headers,
        json={
            "attempt_id": first["attempt_id"],
            "artifact_hash": "hash-1",
            "result": "passed",
        },
    )
    assert first_evidence.status_code == 200

    closed = tokened_client.post(
        "/training/attempt/update",
        headers=headers,
        json={
            "workspace_id": "ws-repeat",
            "attempt_id": first["attempt_id"],
            "status": "returned",
        },
    )
    assert closed.status_code == 200, closed.text

    second_start = tokened_client.post(
        "/training/attempt/start",
        headers=headers,
        json={
            "workspace_id": "ws-repeat",
            "card_id": "card-repeat",
            "file_hash": "hash-2",
        },
    )
    assert second_start.status_code == 200
    second = second_start.json()["attempt"]
    assert second["attempt_id"] != first["attempt_id"]

    second_evidence = tokened_client.post(
        "/training/attempt/evidence",
        headers=headers,
        json={
            "attempt_id": second["attempt_id"],
            "artifact_hash": "hash-2",
            "result": "passed",
        },
    )
    assert second_evidence.status_code == 200

    projection = tokened_client.get(
        f"/training/attempt/{second['attempt_id']}/projection",
        headers=headers,
        params={"workspace_id": "ws-repeat"},
    )
    assert projection.status_code == 200
    implementation = projection.json()["projection"]["implementation"]
    assert implementation["state"] == "repeat_verified"
    assert implementation["independent_attempt_count"] == 2


def test_attempt_evidence_roundtrip_over_rpc(tokened_client: TestClient) -> None:
    headers = {"x-trainer-token": "unit-test-token"}
    started = tokened_client.post(
        "/training/attempt/start",
        headers=headers,
        json={"workspace_id": "ws-default", "card_id": "card-9", "file_hash": "hash-A"},
    )
    attempt = started.json()["attempt"]

    evidence = tokened_client.post(
        "/training/attempt/evidence",
        headers=headers,
        json={
            "attempt_id": attempt["attempt_id"],
            "workspace_id": "ws-default",
            "card_id": "card-9",
            "artifact_hash": "hash-A",
            "result": "passed",
            "runner_version": "pytest/8",
            "execution_location": "workspace",
            # A client claiming controlled_check over the self-report channel
            # must be downgraded: only the host attestation channel is trusted.
            "trust_level": "controlled_check",
        },
    )
    assert evidence.status_code == 200
    body = evidence.json()["evidence"]
    assert body["artifact_hash"] == "hash-A"
    assert body["runner_version"] == "pytest/8"
    assert body["execution_location"] == "workspace"
    assert body["trust_level"] == "self_reported"
    assert body["is_current"] is True

    fetched = tokened_client.get(
        f"/training/attempt/{attempt['attempt_id']}",
        headers=headers,
    )
    items = fetched.json()["attempt"]["evidence"]
    assert [item["is_current"] for item in items] == [True]
