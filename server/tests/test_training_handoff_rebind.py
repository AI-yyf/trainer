"""L1 regressions: training handoff rebind clears the second-card deadlock."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.training_card_identity import require_live_selected_card_for_status
from app.core.models import ActiveCardSelectionResult, TrainingCardCandidateSnapshot
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService


def _practice_card(card_id: str, title: str) -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type="practice",
        title=title,
        target_skill=title,
        validation_method="Run the focused parser test.",
        status="active",
    )


def _select_card(
    service: MemoryService, workspace_id: str, card: TrainingCardCandidateSnapshot
) -> None:
    service.persist_active_card_selection(
        workspace_id,
        ActiveCardSelectionResult(
            selected_card=card,
            selected_card_id=card.card_id,
            why_this_card=f"{card.card_id} is the next card.",
            next_after_completion="Return to coach.",
            fallback_action="Ask the coach for the next card.",
            candidate_count=1,
            eligible_count=1,
        ),
    )


def _verify_card(service: MemoryService, workspace_id: str, card_id: str) -> dict:
    return service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card_id,
        passed=True,
        summary="pytest tests/test_parser.py -k boundary: 1 passed",
        next_step="Record the reflection.",
        focus_area="parser boundary",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )


def test_rebind_lets_first_card_finish_after_second_card_steals_handoff(tmp_path: Path) -> None:
    workspace_id = "ws-handoff-rebind"
    service = MemoryService(TrainerRepository(tmp_path / "rebind.db"))

    card_a = service.upsert_card(workspace_id, _practice_card("card-rebind-a", "Parser guard"))
    card_b = service.upsert_card(workspace_id, _practice_card("card-rebind-b", "Retry backoff"))

    # Card A verifies first: the current training handoff belongs to A.
    _select_card(service, workspace_id, card_a)
    first = _verify_card(service, workspace_id, card_a.card_id)
    first_handoff_id = first["latest_training_handoff"]["handoff_id"]
    assert first["latest_training_handoff"]["card_id"] == card_a.card_id

    # Minting/selecting card B demotes A and verification moves the handoff to B.
    _select_card(service, workspace_id, card_b)
    second = _verify_card(service, workspace_id, card_b.card_id)
    assert second["latest_training_handoff"]["card_id"] == card_b.card_id

    # Deadlock: card A can neither reflect nor pass the live-card guard.
    with pytest.raises(ValueError, match="different card"):
        service.record_training_handoff_reflection(
            workspace_id=workspace_id,
            card_id=card_a.card_id,
            reflection="The failing boundary case is why the guard runs first.",
            handoff_id=first_handoff_id,
        )
    runtime = SimpleNamespace(memory_service=service)
    with pytest.raises(HTTPException) as blocked:
        require_live_selected_card_for_status(runtime, workspace_id, card_a.card_id)
    assert blocked.value.status_code == 409

    # Rebind hands the current handoff back to card A and restores its live stamps.
    rebound = service.rebind_training_handoff(workspace_id, card_a.card_id)
    handoff = rebound["handoff"]
    assert handoff["card_id"] == card_a.card_id
    assert handoff["handoff_id"].startswith(f"handoff-{card_a.card_id}-")
    assert handoff["handoff_id"] != second["latest_training_handoff"]["handoff_id"]
    assert rebound["card"]["card_id"] == card_a.card_id
    workspace_state = service.snapshot(workspace_id).workspace
    assert str(workspace_state.get("selected_card_id") or "") == card_a.card_id
    assert service.live_selected_training_card_id(workspace_id) == card_a.card_id

    # The leftover guard no longer blocks activation of the handoff owner.
    require_live_selected_card_for_status(runtime, workspace_id, card_a.card_id)
    activated = service.transition_card_status(
        workspace_id, card_a.card_id, "active", reason="Rebound handoff owner."
    )
    assert activated.card.status == "active"

    # The rebound handoff stayed verify+verified, so card A can reflect and return.
    reflected = service.record_training_handoff_reflection(
        workspace_id=workspace_id,
        card_id=card_a.card_id,
        reflection="The failing boundary case is why the guard runs first.",
        handoff_id=handoff["handoff_id"],
    )
    assert reflected["latest_training_handoff"]["card_id"] == card_a.card_id
    assert reflected["latest_training_handoff"]["learning_phase"] == "reflect"

    returned = service.return_training_handoff(
        workspace_id=workspace_id,
        card_id=card_a.card_id,
        handoff_id=reflected["latest_training_handoff"]["handoff_id"],
    )
    assert returned["latest_training_handoff"]["learning_phase"] == "return"
    assert returned["latest_training_handoff"]["status"] == "completed"


def test_rebind_mints_fresh_handoff_when_none_exists(tmp_path: Path) -> None:
    workspace_id = "ws-handoff-rebind-fresh"
    service = MemoryService(TrainerRepository(tmp_path / "rebind-fresh.db"))
    card = service.upsert_card(workspace_id, _practice_card("card-rebind-fresh", "Fresh card"))

    rebound = service.rebind_training_handoff(workspace_id, card.card_id)

    handoff = rebound["handoff"]
    assert handoff["card_id"] == card.card_id
    assert handoff["handoff_id"].startswith(f"handoff-{card.card_id}-")
    assert handoff["learning_phase"] == "learn"
    assert rebound["card"]["card_id"] == card.card_id
    assert service.live_selected_training_card_id(workspace_id) == card.card_id


def test_rebind_refuses_missing_or_finished_cards(tmp_path: Path) -> None:
    workspace_id = "ws-handoff-rebind-refuse"
    service = MemoryService(TrainerRepository(tmp_path / "rebind-refuse.db"))

    with pytest.raises(LookupError, match="Training card not found."):
        service.rebind_training_handoff(workspace_id, "card-missing")

    finished = service.upsert_card(
        workspace_id,
        _practice_card("card-rebind-done", "Finished card").model_copy(update={"status": "implemented"}),
    )
    with pytest.raises(ValueError, match="already finished"):
        service.rebind_training_handoff(workspace_id, finished.card_id)


def test_open_handoff_owner_counts_as_live_without_selection(tmp_path: Path) -> None:
    workspace_id = "ws-handoff-owner-live"
    service = MemoryService(TrainerRepository(tmp_path / "owner-live.db"))
    card = service.upsert_card(workspace_id, _practice_card("card-owner-live", "Owner card"))
    _verify_card(service, workspace_id, card.card_id)

    # A later mint cleared the painted selection; the open handoff owner stays live.
    service.update_workspace_state(workspace_id, selected_card_id="")
    assert service.live_selected_training_card_id(workspace_id) == card.card_id
