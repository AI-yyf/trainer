"""Training/handoff reliability path: transitions, idempotency, timeout, recover."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from app.core.models import TrainingCardCandidateSnapshot
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService
from app.training.reliability import (
    begin_record,
    can_transition,
    expire_if_needed,
    mark_executing,
    mark_succeeded,
    recover_record,
    request_cancel,
    should_coalesce,
    should_replay,
    transition,
)


def _card(card_id: str = "reliability-card") -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type="practice",
        title="Persist the reliability path",
        target_skill="reliability",
        validation_method="Run the focused reliability test.",
        status="active",
    )


def test_reliability_transitions_and_rejects_illegal_moves() -> None:
    record = begin_record(request_id="req-1", command_id="trainer.training.reflect", card_id="card-1")
    assert record["phase"] == "intent"
    executing = mark_executing(record)
    assert executing["phase"] == "executing"
    acked = mark_succeeded(executing, snapshot_revision=3, learning_phase="reflect")
    assert acked["phase"] == "acked"
    assert acked["outcome"] == "success"
    assert acked["snapshot_revision"] == 3
    assert acked["acked_at"]
    assert can_transition("failed", "pending")
    assert not can_transition("acked", "failed")
    with pytest.raises(ValueError, match="cannot move"):
        transition(acked, "failed")


def test_reliability_replay_and_in_flight_coalesce() -> None:
    record = mark_succeeded(
        mark_executing(begin_record(request_id="req-2", command_id="trainer.training.return", card_id="card-2")),
        snapshot_revision=1,
    )
    assert should_replay(record, "req-2", "req-2")
    assert not should_replay(record, "req-other", "other-key")

    in_flight = mark_executing(
        begin_record(request_id="req-3", command_id="trainer.training.reflect", card_id="card-3")
    )
    assert should_coalesce(
        in_flight,
        request_id="req-duplicate",
        command_id="trainer.training.reflect",
        card_id="card-3",
    )
    assert not should_coalesce(
        in_flight,
        request_id="req-other",
        command_id="trainer.training.return",
        card_id="card-3",
    )


def test_reliability_timeout_cancel_and_recover() -> None:
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    record = begin_record(
        request_id="req-4",
        command_id="trainer.training.practiceReturn",
        card_id="card-4",
        timeout_ms=1_000,
        now=past,
    )
    executing = mark_executing(record, now=past)
    expired = expire_if_needed(executing)
    assert expired is not None
    assert expired["phase"] == "failed"
    assert expired["outcome"] == "timeout"
    assert expired["recoverable"] is True

    cancelled = request_cancel(mark_executing(begin_record(request_id="req-5", command_id="x", card_id="c")))
    assert cancelled["phase"] == "cancelled"
    recovered = recover_record(cancelled, request_id="req-5b")
    assert recovered["phase"] == "pending"
    assert recovered["revision"] == 2
    assert recovered["request_id"] == "req-5b"
    assert recovered["error"] == ""


def test_memory_service_persists_acked_reliability_through_reflect_and_replays(
    tmp_path,
) -> None:
    service = MemoryService(TrainerRepository(tmp_path / "reliability.db"))
    workspace_id = "workspace-reliability"
    card = service.upsert_card(workspace_id, _card())
    verified = service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="pytest tests/test_reliability.py: 1 passed",
        next_step="Record the reflection.",
        focus_area="reliability",
        evidence_source="test_runner",
        verified_by_evaluator=True,
        request_id="req-verify-1",
    )
    assert verified["latest_training_reliability"]["phase"] == "acked"
    assert verified["latest_training_reliability"]["request_id"] == "req-verify-1"
    assert verified["latest_training_reliability"]["snapshot_revision"] >= 1

    reflected = service.record_training_handoff_reflection(
        workspace_id=workspace_id,
        card_id=card.card_id,
        reflection="The timeout case showed why acknowledgement must be persisted.",
        handoff_id=verified["latest_training_handoff"]["handoff_id"],
        request_id="req-reflect-1",
    )
    assert reflected["latest_training_reliability"]["phase"] == "acked"
    assert reflected["latest_training_reliability"]["command_id"] == "trainer.training.reflect"
    assert reflected["latest_training_handoff"]["learning_phase"] == "reflect"

    replayed = service.record_training_handoff_reflection(
        workspace_id=workspace_id,
        card_id=card.card_id,
        reflection="A duplicate request must not rewrite current truth.",
        handoff_id=verified["latest_training_handoff"]["handoff_id"],
        request_id="req-reflect-1",
    )
    assert replayed["latest_training_reliability"]["request_id"] == "req-reflect-1"
    assert replayed["latest_training_reliability"]["phase"] == "acked"
    assert replayed["latest_training_handoff"]["learning_phase"] == "reflect"

    restarted = MemoryService(TrainerRepository(tmp_path / "reliability.db"))
    restored = restarted.latest_training_reliability(workspace_id)
    assert restored is not None
    assert restored["request_id"] == "req-reflect-1"
    assert restored["phase"] == "acked"
    assert restored["snapshot_revision"] >= 1


def test_memory_service_failure_cancel_and_recover_are_authoritative(tmp_path) -> None:
    service = MemoryService(TrainerRepository(tmp_path / "reliability-recover.db"))
    workspace_id = "workspace-reliability-recover"
    service.upsert_card(workspace_id, _card("recover-card"))

    with pytest.raises(LookupError, match="No training handoff"):
        service.record_training_handoff_reflection(
            workspace_id=workspace_id,
            card_id="recover-card",
            reflection="This should fail before a handoff exists.",
            request_id="req-fail-1",
        )

    failed = service.latest_training_reliability(workspace_id)
    assert failed is not None
    assert failed["phase"] == "failed"
    assert failed["recoverable"] is True
    assert failed["request_id"] == "req-fail-1"

    recovered = service.recover_training_reliability(
        workspace_id,
        request_id="req-fail-2",
    )
    assert recovered["latest_training_reliability"]["phase"] == "pending"
    assert recovered["latest_training_reliability"]["revision"] == 2
    assert recovered["latest_training_reliability"]["request_id"] == "req-fail-2"

    executing = mark_executing(recovered["latest_training_reliability"])
    structured = service._structured_for(workspace_id)
    service._save_training_reliability(workspace_id, structured, executing)

    cancelled = service.cancel_training_reliability(
        workspace_id,
        request_id="req-fail-2",
        command_id="trainer.training.reflect",
        card_id="recover-card",
    )
    assert cancelled["latest_training_reliability"]["phase"] == "cancelled"
    assert cancelled["latest_training_reliability"]["recoverable"] is True


def test_memory_service_expires_in_flight_reliability(tmp_path) -> None:
    service = MemoryService(TrainerRepository(tmp_path / "reliability-expire.db"))
    workspace_id = "workspace-reliability-expire"
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    record = mark_executing(
        begin_record(
            request_id="req-expire-1",
            command_id="trainer.training.return",
            card_id="expire-card",
            timeout_ms=1_000,
            now=past,
        ),
        now=past,
    )
    structured = service._structured_for(workspace_id)
    service._save_training_reliability(workspace_id, structured, record)

    expired = service.expire_training_reliability(workspace_id)
    assert expired["latest_training_reliability"]["phase"] == "failed"
    assert expired["latest_training_reliability"]["outcome"] == "timeout"
    assert expired["latest_training_reliability"]["recovery_action"] == "retry"


def test_memory_service_return_replays_same_request_id_without_second_credit(tmp_path) -> None:
    service = MemoryService(TrainerRepository(tmp_path / "reliability-return.db"))
    workspace_id = "workspace-reliability-return"
    card = service.upsert_card(workspace_id, _card("return-card"))
    verified = service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="pytest tests/test_return_idempotent.py: 1 passed",
        next_step="Return the verified result.",
        focus_area="reliability",
        evidence_source="test_runner",
        verified_by_evaluator=True,
        request_id="req-verify-return-1",
    )
    handoff_id = verified["latest_training_handoff"]["handoff_id"]
    service.record_training_handoff_reflection(
        workspace_id=workspace_id,
        card_id=card.card_id,
        reflection="Ready to return once.",
        handoff_id=handoff_id,
        request_id="req-reflect-return-1",
    )

    first = service.return_training_handoff(
        workspace_id=workspace_id,
        card_id=card.card_id,
        handoff_id=handoff_id,
        request_id="req-return-1",
    )
    assert first["latest_training_reliability"]["phase"] == "acked"
    credited = service.get_card(workspace_id, card.card_id)
    assert credited is not None
    ledger_count = len(
        [
            entry
            for entry in service._card_ledger
            if entry.get("card_id") == card.card_id and entry.get("workspace_id") == workspace_id
        ]
    )

    second = service.return_training_handoff(
        workspace_id=workspace_id,
        card_id=card.card_id,
        handoff_id=handoff_id,
        request_id="req-return-1",
    )
    assert second["latest_training_reliability"]["request_id"] == "req-return-1"
    assert second["latest_training_reliability"]["phase"] == "acked"
    ledger_after = [
        entry
        for entry in service._card_ledger
        if entry.get("card_id") == card.card_id and entry.get("workspace_id") == workspace_id
    ]
    assert len(ledger_after) == ledger_count
    unchanged = service.get_card(workspace_id, card.card_id)
    assert unchanged is not None
    assert unchanged.status == credited.status


def test_mark_succeeded_annotates_cancel_and_timeout_races() -> None:
    """Persisted work stays success; a raced cancel/timeout is annotated, never
    rewritten as failure (and a same-identity retry replays)."""
    cancel_flagged = mark_executing(
        begin_record(request_id="req-race-cancel", command_id="x", card_id="c")
    )
    cancel_flagged["cancel_requested"] = True
    acked = mark_succeeded(cancel_flagged, snapshot_revision=1)
    assert acked["phase"] == "acked"
    assert acked["outcome"] == "success"
    assert acked["error"] == ""
    assert acked["cancel_after"] is True
    assert acked["timeout_after"] is False

    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    expired_executing = mark_executing(
        begin_record(
            request_id="req-race-timeout",
            command_id="x",
            card_id="c",
            timeout_ms=1_000,
            now=past,
        )
    )
    acked_timeout = mark_succeeded(expired_executing, snapshot_revision=1)
    assert acked_timeout["phase"] == "acked"
    assert acked_timeout["outcome"] == "success"
    assert acked_timeout["timeout_after"] is True
    assert should_replay(acked_timeout, "req-race-timeout", "req-race-timeout")


def test_memory_service_cancel_race_keeps_work_as_succeeded_and_replays(tmp_path) -> None:
    """A cancel landing while work() runs must not rewrite the persisted work
    as cancelled, and the same-identity retry must replay without a second run."""
    service = MemoryService(TrainerRepository(tmp_path / "reliability-cancel-race.db"))
    workspace_id = "workspace-reliability-cancel-race"
    calls: list[str] = []

    def racing_work() -> dict[str, object]:
        # The cancel mutating the same slot while work() is still executing.
        service.cancel_training_reliability(workspace_id, request_id="req-cancel-race")
        calls.append("ran")
        return {"ok": True}

    first = service.run_training_reliability(
        workspace_id,
        request_id="req-cancel-race",
        command_id="trainer.training.practiceReturn",
        card_id="race-card",
        work=racing_work,
    )
    record = first["latest_training_reliability"]
    assert record["phase"] == "acked"
    assert record["outcome"] == "success"
    assert record["cancel_after"] is True
    assert calls == ["ran"]

    replayed = service.run_training_reliability(
        workspace_id,
        request_id="req-cancel-race",
        command_id="trainer.training.practiceReturn",
        card_id="race-card",
        work=lambda: calls.append("rerun") or {"ok": True},
    )
    assert replayed["latest_training_reliability"]["phase"] == "acked"
    assert calls == ["ran"]


def test_memory_service_timeout_race_keeps_work_as_succeeded(tmp_path) -> None:
    """Work that outlives timeout_at still records success (timeout_after=True),
    so the client is never told a persisted save failed."""
    service = MemoryService(TrainerRepository(tmp_path / "reliability-timeout-race.db"))
    workspace_id = "workspace-reliability-timeout-race"

    def slow_work() -> dict[str, object]:
        time.sleep(1.2)  # outlives the 1s bounded timeout below
        return {"ok": True}

    finished = service.run_training_reliability(
        workspace_id,
        request_id="req-timeout-race",
        command_id="trainer.training.practiceReturn",
        card_id="timeout-card",
        timeout_ms=1_000,
        work=slow_work,
    )
    record = finished["latest_training_reliability"]
    assert record["phase"] == "acked"
    assert record["outcome"] == "success"
    assert record["timeout_after"] is True
