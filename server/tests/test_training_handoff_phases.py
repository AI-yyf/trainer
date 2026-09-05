"""Phase-order regressions for recoverable training handoffs."""

from __future__ import annotations

import pytest

from app.core.models import TrainingCardCandidateSnapshot
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService
from app.training.handoff import HandoffStatus, TrainingHandoffGenerator, TrainingPhase


def _card(card_id: str = "phase-card") -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type="practice",
        title="Verify one parser boundary",
        target_skill="parser boundary",
        validation_method="Run the focused parser test.",
    )


def test_handoff_blocks_verification_and_return_before_try() -> None:
    generator = TrainingHandoffGenerator()
    handoff = generator.build_handoff_record(_card(), {})

    assert handoff.phase is TrainingPhase.LEARN
    unchanged = generator.record_verification(
        handoff.handoff_id,
        "pytest: 1 passed",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )

    assert unchanged is handoff
    assert handoff.phase is TrainingPhase.LEARN
    assert handoff.verification_state == "evidence_required"
    assert handoff.status is not HandoffStatus.COMPLETED
    with pytest.raises(ValueError, match="Return requires Learn, Try"):
        generator.return_handoff(handoff.handoff_id)


def test_handoff_requires_reflection_before_return_and_never_claims_mastery() -> None:
    generator = TrainingHandoffGenerator()
    handoff = generator.build_handoff_record(_card(), {})

    tried = generator.record_try(handoff.handoff_id, "Implemented the parser guard and ran the target case.")
    assert tried is handoff
    assert handoff.phase is TrainingPhase.TRY

    verified = generator.record_verification(
        handoff.handoff_id,
        "pytest tests/test_parser.py -k boundary: 1 passed",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )
    assert verified is handoff
    assert handoff.phase is TrainingPhase.VERIFY
    assert handoff.verification_state == "verified"

    with pytest.raises(ValueError, match="Return requires Learn, Try"):
        generator.return_handoff(handoff.handoff_id)

    reflected = generator.record_reflection(
        handoff.handoff_id,
        "The failing edge case showed why the guard belongs before token parsing.",
    )
    assert reflected is handoff
    assert handoff.phase is TrainingPhase.REFLECT

    returned = generator.return_handoff(handoff.handoff_id)
    assert returned is handoff
    assert handoff.phase is TrainingPhase.RETURN
    assert handoff.status is HandoffStatus.COMPLETED
    assert handoff.returned_at is not None
    assert "mastered" not in handoff.handoff_content.success_signal.lower()
    assert [event.phase for event in handoff.phase_history] == [
        TrainingPhase.LEARN,
        TrainingPhase.TRY,
        TrainingPhase.VERIFY,
        TrainingPhase.REFLECT,
        TrainingPhase.RETURN,
    ]


def test_handoff_recovers_reflection_gate_after_interruption(tmp_path) -> None:
    generator = TrainingHandoffGenerator(workspace_root=tmp_path)
    handoff = generator.build_handoff_record(
        _card("resume-phase-card"),
        {
            "correct": True,
            "evidence": ["Learner supplied a local test summary."],
            "evidence_source": "learner_submission",
        },
    )
    generator.write_handoff_to_workspace(handoff)

    generator.record_verification(
        handoff.handoff_id,
        "pytest tests/test_parser.py -k boundary: 1 passed",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )
    generator.record_reflection(handoff.handoff_id, "The evidence separated a passing branch from a guess.")

    recovered = TrainingHandoffGenerator(workspace_root=tmp_path).resume_handoff(handoff.handoff_id)
    assert recovered is not None
    assert recovered.phase is TrainingPhase.REFLECT
    assert recovered.verification_state == "verified"
    assert recovered.status is HandoffStatus.WRITTEN

    returned = TrainingHandoffGenerator(workspace_root=tmp_path).return_handoff(handoff.handoff_id)
    assert returned is not None
    assert returned.phase is TrainingPhase.RETURN
    assert returned.status is HandoffStatus.COMPLETED

    resumed_after_return = TrainingHandoffGenerator(workspace_root=tmp_path).resume_handoff(handoff.handoff_id)
    assert resumed_after_return is not None
    assert resumed_after_return.phase is TrainingPhase.RETURN
    assert resumed_after_return.returned_at is not None


def test_verified_initial_evidence_still_requires_explicit_reflection() -> None:
    generator = TrainingHandoffGenerator()
    handoff = generator.build_handoff_record(
        _card("trusted-start"),
        {
            "correct": True,
            "evidence": ["focused test: passed"],
            "evidence_source": "test_runner",
            "verified_by_evaluator": True,
        },
    )

    assert handoff.phase is TrainingPhase.VERIFY
    assert handoff.verification_state == "verified"
    with pytest.raises(ValueError, match="Return requires Learn, Try"):
        generator.complete_return(handoff.handoff_id)


def test_practice_evaluation_keeps_active_card_pending_after_verify_only(tmp_path) -> None:
    workspace_id = "phase-memory-pending"
    service = MemoryService(TrainerRepository(tmp_path / "pending.db"))
    card = _card("pending-card").model_copy(update={"status": "active"})
    service.upsert_card(workspace_id, card)

    result = service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="pytest tests/test_parser.py -k boundary: 1 passed",
        next_step="Return to Coach with the test output.",
        focus_area="parser boundary",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )

    stored = service.get_card(workspace_id, card.card_id)
    assert stored is not None
    assert stored.status == "active"
    assert result["selected_card_status"] == "active"
    assert result["latest_training_handoff"]["learning_phase"] == "verify"
    assert result["latest_training_handoff"]["status"] != HandoffStatus.COMPLETED.value
    assert result["latest_training_handoff"]["return_mode"] == "reflection_required"
    assert result["latest_learning_verified_result"] == ""


def test_practice_evaluation_accepts_only_recovered_terminal_handoff(tmp_path) -> None:
    workspace_id = "phase-memory-returned"
    database_path = tmp_path / "returned.db"
    service = MemoryService(TrainerRepository(database_path))
    card = _card("returned-card").model_copy(update={"status": "active"})
    service.upsert_card(workspace_id, card)

    generator = TrainingHandoffGenerator()
    terminal = generator.build_handoff_record(
        card,
        {
            "correct": True,
            "evidence": ["pytest tests/test_parser.py -k boundary: 1 passed"],
            "evidence_source": "test_runner",
            "verified_by_evaluator": True,
        },
    )
    generator.record_reflection(terminal.handoff_id, "The check proved the guard belongs before parsing.")
    generator.return_handoff(terminal.handoff_id)

    structured = service._structured_for(workspace_id)
    structured.update_workspace(
        workspace_id=workspace_id,
        latest_training_handoff=TrainingHandoffGenerator._handoff_payload(terminal),
    )
    service._persist_structured(workspace_id)
    restarted = MemoryService(TrainerRepository(database_path))

    result = restarted.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="pytest tests/test_parser.py -k boundary: 1 passed",
        next_step="Continue with the next card.",
        focus_area="parser boundary",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )

    stored = restarted.get_card(workspace_id, card.card_id)
    assert stored is not None
    assert stored.status == "implemented"
    assert result["selected_card_status"] == "implemented"
    assert result["latest_training_handoff"]["learning_phase"] == "return"
    assert result["latest_training_handoff"]["status"] == HandoffStatus.COMPLETED.value


def test_card_learning_phase_persists_through_try_verify_reflect_return(tmp_path) -> None:
    database_path = tmp_path / "trainer-card-learning-phase.db"
    service = MemoryService(TrainerRepository(database_path))
    workspace_id = "workspace-learning-phase"
    card = service.upsert_card(
        workspace_id,
        TrainingCardCandidateSnapshot(
            card_id="loop-card",
            card_type="practice",
            title="Keep the learning loop on the card",
            target_skill="learning loop",
            validation_method="Run the focused loop test.",
            status="candidate",
        ),
    )
    assert card.learning_phase == "learn"

    active = service.transition_card_status(workspace_id, card.card_id, "active", reason="Start try.")
    assert active.card.learning_phase == "try"

    workspace = service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="pytest tests/test_loop.py: 1 passed",
        next_step="Record the reflection.",
        focus_area="learning loop",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )
    stored = service.get_card(workspace_id, card.card_id)
    assert stored is not None
    assert stored.learning_phase == "verify"
    assert workspace["latest_training_handoff"]["learning_phase"] == "verify"

    reflected = service.record_training_handoff_reflection(
        workspace_id=workspace_id,
        card_id=card.card_id,
        reflection="The failing case showed why the loop must stay on the card.",
        handoff_id=workspace["latest_training_handoff"]["handoff_id"],
    )
    stored = service.get_card(workspace_id, card.card_id)
    assert stored is not None
    assert stored.learning_phase == "reflect"
    assert reflected["latest_training_handoff"]["learning_phase"] == "reflect"

    returned = service.return_training_handoff(
        workspace_id=workspace_id,
        card_id=card.card_id,
        handoff_id=workspace["latest_training_handoff"]["handoff_id"],
    )
    stored = service.get_card(workspace_id, card.card_id)
    assert stored is not None
    assert stored.learning_phase == "return"
    assert returned["latest_training_handoff"]["learning_phase"] == "return"
