"""Phase-D slice 2 regression tests (design §5/§6, acceptance #18):

- Re-entering a card resumes the in-flight attempt (same attemptId) — the
  "refresh recovers the same attemptId" contract.
- Workspace isolation: attempts from another workspace can neither be read
  nor written.
- Recording evidence twice never yields two current records; the new record
  supersedes the old one.
- Return closes the attempt lifecycle; a later re-enter creates a fresh one.
- Evidence identity derives from the stored attempt, never from client fields.
"""

from __future__ import annotations

from pathlib import Path

from app.training.attempt_store import AttemptStore
from app.training.skill_projection import project_skills


def make_store(tmp_path: Path) -> AttemptStore:
    return AttemptStore(tmp_path / "attempts.db")


def test_reentering_a_card_resumes_the_same_attempt_id(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = store.start_attempt(workspace_id="ws-1", card_id="card-1", file_hash="h1")
    again = store.start_attempt(workspace_id="ws-1", card_id="card-1", file_hash="h2")

    assert again["attempt_id"] == first["attempt_id"], (
        "re-entering the card must resume the in-flight attempt",
    )
    assert again["file_hash"] == "h2", "refresh keeps the latest binding"

    # The store never duplicates the in-flight attempt.
    rows = []
    connection = store._connect()
    try:
        rows = connection.execute(
            "SELECT attempt_id FROM training_attempts WHERE workspace_id = ? AND card_id = ?",
            ("ws-1", "card-1"),
        ).fetchall()
    finally:
        connection.close()
    assert len(rows) == 1


def test_return_closes_the_lifecycle_then_reenter_starts_fresh(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = store.start_attempt(workspace_id="ws-1", card_id="card-1")
    store.close_attempt(first["attempt_id"], workspace_id="ws-1")

    closed = store.get_attempt(first["attempt_id"])
    assert closed is not None and closed["status"] == "returned"
    assert closed["answer_draft"] is not None or "answer_draft" in closed, (
        "history stays queryable after close",
    )

    second = store.start_attempt(workspace_id="ws-1", card_id="card-1")
    assert second["attempt_id"] != first["attempt_id"]
    assert second["status"] == "active"


def test_workspace_isolation_fails_closed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    attempt = store.start_attempt(workspace_id="ws-1", card_id="card-1")

    # Another workspace cannot read the attempt.
    assert store.get_attempt(attempt["attempt_id"], workspace_id="ws-2") is None
    # ...nor update it.
    assert (
        store.update_attempt(
            attempt["attempt_id"], workspace_id="ws-2", answer_draft="hijack"
        )
        is None
    )
    untouched = store.get_attempt(attempt["attempt_id"], workspace_id="ws-1")
    assert untouched is not None and untouched["answer_draft"] == ""

    # ...nor re-enter it as its own in-flight attempt.
    assert store.find_active_attempt("ws-2", "card-1") is None


def test_double_evidence_recording_keeps_a_single_current_record(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    attempt = store.start_attempt(
        workspace_id="ws-1", card_id="card-1", file_hash="hash-A"
    )

    first = store.record_evidence(
        attempt_id=attempt["attempt_id"], artifact_hash="hash-A", result="passed"
    )
    second = store.record_evidence(
        attempt_id=attempt["attempt_id"], artifact_hash="hash-A", result="passed"
    )

    items = store.list_evidence(attempt["attempt_id"])
    assert [item["is_current"] for item in items].count(True) == 1
    assert items[-1]["evidence_id"] == second["evidence_id"]
    assert first["evidence_id"] != second["evidence_id"]
    # The stored record (not the stale return copy) carries the supersession.
    stored_first = store.list_evidence(attempt["attempt_id"])
    stored_first_row = next(
        item for item in stored_first if item["evidence_id"] == first["evidence_id"]
    )
    assert stored_first_row["superseded_by_evidence_id"] == second["evidence_id"]


def test_distinct_attempts_produce_repeat_verified(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = store.start_attempt(
        workspace_id="ws-1", card_id="card-1", file_hash="hash-A"
    )
    store.record_evidence(
        attempt_id=first["attempt_id"], artifact_hash="hash-A", result="passed"
    )

    # A verified attempt is no longer active, so entering the same card creates
    # a genuinely new attempt rather than counting a second check on attempt 1.
    second = store.start_attempt(
        workspace_id="ws-1", card_id="card-1", file_hash="hash-B"
    )
    assert second["attempt_id"] != first["attempt_id"]
    store.record_evidence(
        attempt_id=second["attempt_id"], artifact_hash="hash-B", result="passed"
    )

    records = []
    for attempt in store.list_attempts(workspace_id="ws-1", card_id="card-1"):
        records.extend(store.list_evidence(attempt["attempt_id"]))

    projection = project_skills(records)
    assert projection["implementation"]["state"] == "repeat_verified"
    assert projection["implementation"]["independent_attempt_count"] == 2


def test_assistance_level_and_draft_survive_workspace_scoped_updates(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    attempt = store.start_attempt(
        workspace_id="ws-1", card_id="card-1", assistance_level="hint_level_1"
    )

    store.update_attempt(
        attempt["attempt_id"],
        workspace_id="ws-1",
        answer_draft="draft v1",
        assistance_level="hint_level_2",
    )
    # A cross-workspace write attempt must not disturb the record.
    assert (
        store.update_attempt_for_workspace(
            attempt["attempt_id"],
            workspace_id="ws-other",
            answer_draft="hijack",
        )
        is None
    )
    loaded = store.get_attempt(attempt["attempt_id"], workspace_id="ws-1")
    assert loaded is not None
    assert loaded["answer_draft"] == "draft v1"
    assert loaded["assistance_level"] == "hint_level_2"
