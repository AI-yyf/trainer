"""Regression coverage for training handoff persistence in MemoryService."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models import TrainingCardCandidateSnapshot
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService
from app.training.handoff import HandoffStatus, TrainingHandoffGenerator, TrainingPhase


@pytest.mark.parametrize(
    (
        "case",
        "passed",
        "summary",
        "evidence_source",
        "verified_by_evaluator",
        "expected_card_status",
        "expected_verification_state",
        "expected_return_state",
        "expected_return_mode",
    ),
    [
        pytest.param(
            "verified",
            True,
            "Focused test passed with no diagnostics.",
            "test_runner",
            True,
            "active",
            "verified",
            "return_to_coach",
            "reflection_required",
            id="trusted-verification",
        ),
        pytest.param(
            "pending",
            True,
            "Focused test output is awaiting evaluator attestation.",
            "test_runner",
            False,
            "active",
            "verification_required",
            "verify_then_return",
            "verification_required",
            id="pending-verification",
        ),
        pytest.param(
            "blocked",
            False,
            "The focused check still fails on the boundary case.",
            "ide_current_file",
            True,
            "blocked",
            "blocked",
            "resume_training",
            "blocker",
            id="explicit-blocker",
        ),
        pytest.param(
            "self-report",
            True,
            "I ran it locally and it works.",
            "learner_return",
            True,
            "active",
            "verification_required",
            "verify_then_return",
            "verification_required",
            id="untrusted-self-report",
        ),
        pytest.param(
            "missing-evidence",
            True,
            "",
            "test_runner",
            True,
            "active",
            "evidence_required",
            "resume_training",
            "verification_required",
            id="evaluator-attestation-without-evidence",
        ),
    ],
)
def test_practice_handoff_state_is_persisted_without_overclaiming_completion(
    tmp_path: Path,
    case: str,
    passed: bool,
    summary: str,
    evidence_source: str,
    verified_by_evaluator: bool,
    expected_card_status: str,
    expected_verification_state: str,
    expected_return_state: str,
    expected_return_mode: str,
) -> None:
    database_path = tmp_path / f"{case}.db"
    workspace_id = f"workspace-{case}"
    card = TrainingCardCandidateSnapshot(
        card_id=f"card-{case}",
        card_type="practice",
        title="Verify one parser boundary",
        target_skill="parser boundary",
        status="active",
        validation_method="Run the focused parser test.",
    )
    service = MemoryService(TrainerRepository(database_path))
    service.upsert_card(workspace_id, card)

    result = service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=passed,
        summary=summary,
        next_step="Run the focused parser test again.",
        focus_area="parser boundary",
        evidence_source=evidence_source,
        verified_by_evaluator=verified_by_evaluator,
    )

    handoff = result["latest_training_handoff"]
    assert result["selected_card_status"] == expected_card_status
    assert handoff["verification_state"] == expected_verification_state
    assert handoff["return_state"] == expected_return_state
    assert handoff["return_mode"] == expected_return_mode
    assert handoff["resume_token"]
    assert handoff["handoff_id"]

    if expected_verification_state == "verified":
        assert handoff["handoff_content"]["success_signal"]
        assert "not a claim of durable mastery" in handoff["handoff_content"]["completion_claim"]
        assert handoff["evidence"] and handoff["evidence"][0]["verified"] is True
        assert handoff["learning_phase"] == TrainingPhase.VERIFY.value
        assert handoff["status"] != HandoffStatus.COMPLETED.value
        assert result["latest_learning_verified_result"] == ""
    else:
        success_signal = handoff["handoff_content"]["success_signal"].lower()
        completion_claim = handoff["handoff_content"]["completion_claim"].lower()
        assert "mastered" not in success_signal
        assert "supports this card result" not in completion_claim
        assert all(item["verified"] is False for item in handoff["evidence"])

    rebuilt = MemoryService(TrainerRepository(database_path))
    persisted_handoff = rebuilt.snapshot(workspace_id).workspace["latest_training_handoff"]
    assert persisted_handoff["handoff_id"] == handoff["handoff_id"]
    assert persisted_handoff["verification_state"] == expected_verification_state
    assert persisted_handoff["return_state"] == expected_return_state

    restored_record = TrainingHandoffGenerator._handoff_from_payload(persisted_handoff)
    assert restored_record is not None
    assert restored_record.verification_state == expected_verification_state
    assert restored_record.return_state == expected_return_state


def test_practice_handoff_implements_only_after_recovered_terminal_return(tmp_path: Path) -> None:
    database_path = tmp_path / "returned-handoff.db"
    workspace_id = "workspace-returned-handoff"
    card = TrainingCardCandidateSnapshot(
        card_id="card-returned-handoff",
        card_type="practice",
        title="Verify one parser boundary",
        target_skill="parser boundary",
        status="active",
        validation_method="Run the focused parser test.",
    )
    service = MemoryService(TrainerRepository(database_path))
    service.upsert_card(workspace_id, card)

    generator = TrainingHandoffGenerator()
    terminal = generator.build_handoff_record(
        card,
        {
            "correct": True,
            "evidence": ["Focused test passed with no diagnostics."],
            "evidence_source": "test_runner",
            "verified_by_evaluator": True,
        },
    )
    generator.record_reflection(terminal.handoff_id, "The focused check proved the parser boundary.")
    generator.return_handoff(terminal.handoff_id)
    assert terminal.phase is TrainingPhase.RETURN
    assert terminal.status is HandoffStatus.COMPLETED

    service._structured_for(workspace_id).update_workspace(
        latest_training_handoff=TrainingHandoffGenerator._handoff_payload(terminal)
    )
    service._persist_structured(workspace_id)
    restarted = MemoryService(TrainerRepository(database_path))

    result = restarted.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="Focused test passed with no diagnostics.",
        next_step="Continue with the next card.",
        focus_area="parser boundary",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )

    stored = restarted.get_card(workspace_id, card.card_id)
    assert stored is not None
    assert stored.status == "implemented"
    assert result["selected_card_status"] == "implemented"
    assert result["latest_training_handoff"]["learning_phase"] == TrainingPhase.RETURN.value
    assert result["latest_training_handoff"]["status"] == HandoffStatus.COMPLETED.value
