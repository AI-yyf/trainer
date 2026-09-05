from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import UserProfile
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService


def _make_service(tmp_path: Path) -> tuple[MemoryService, str]:
    repository = TrainerRepository(tmp_path / "dependency-mastery.db")
    service = MemoryService(repository)
    workspace_id = "workspace-dependency-mastery"
    repository.save_profile(
        workspace_id,
        UserProfile(
            long_term_goal="Master dependency APIs through practice",
            weekly_hours=4,
            teaching_style="guided",
            answer_policy="guided",
            preferred_libraries=["FastAPI"],
        ),
    )
    return service, workspace_id


def test_flashcard_success_promotes_dependency_to_recalled(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        scenarios=["Use dependency injection in one route"],
        weakest_points=["Still cannot recall when Depends fits best."],
        evidence=["Initial weakness from practice."],
    )

    deck = service.build_flash_deck(workspace_id)
    dependency_card = next(card for card in deck.cards if card.dependency_key == "fastapi")
    response = service.submit_flashcard_answer(
        workspace_id,
        card_id=dependency_card.card_id,
        learner_answer="Depends injects a dependency into a FastAPI route.",
        selected_option_index=0 if dependency_card.answer_mode == "choice" else None,
    )

    fastapi = next(item for item in response.dependency_mastery if item.dependency_key == "fastapi")
    assert fastapi.mastery_stage == "recalled"
    assert "recalled" in fastapi.mastery_stage_progress


def test_learning_signal_transfer_requires_explicit_cross_project_evidence(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)

    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["FastAPI"],
        outcome="tests_passed",
        summary="Used Depends correctly in the live route and verified the behavior.",
        focus_area="dependency injection",
        scenario="dependency_project",
        verified_result="The route now resolves the injected dependency correctly.",
        verified_by_evaluator=True,
    )
    first = next(item for item in service.snapshot(workspace_id).dependency_mastery if item.dependency_key == "fastapi")
    assert first.mastery_stage == "applied"

    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["FastAPI"],
        outcome="tests_passed",
        summary="Reused the same dependency injection pattern in another project slice.",
        focus_area="dependency injection transfer",
        scenario="cross_project_transfer",
        verified_result="The same pattern held in a second project scenario.",
        verified_by_evaluator=True,
    )
    second = next(item for item in service.snapshot(workspace_id).dependency_mastery if item.dependency_key == "fastapi")
    assert second.mastery_stage == "applied"
    assert second.latest_transfer_blocked_reason

    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["FastAPI"],
        outcome="tests_passed",
        summary="Migrated the same dependency injection judgment into a second workspace.",
        focus_area="dependency injection transfer",
        scenario="cross_project_transfer",
        verified_result="The same dependency boundary passed in a second workspace.",
        transfer_source_workspace_id=workspace_id,
        transfer_target_workspace_id="workspace-fastapi-transfer-target",
        transfer_source_context="Original FastAPI sidecar route",
        transfer_target_context="Second project route boundary",
        transfer_evidence_summary="Cross-project migration verified in a second workspace.",
        verified_by_evaluator=True,
    )
    third = next(item for item in service.snapshot(workspace_id).dependency_mastery if item.dependency_key == "fastapi")
    assert third.mastery_stage == "transferable"
    assert third.latest_transfer_evidence_id
    assert third.mastery_stage_progress == [
        "understood",
        "recalled",
        "practiced",
        "applied",
        "transferable",
    ]

    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["FastAPI"],
        outcome="tests_passed",
        summary="The evaluator confirmed another focused route test passed.",
        focus_area="dependency injection",
        scenario="dependency_project",
        verified_result="The focused route still resolves the dependency correctly.",
        verified_by_evaluator=True,
    )
    preserved = next(
        item for item in service.snapshot(workspace_id).dependency_mastery if item.dependency_key == "fastapi"
    )
    assert preserved.mastery_stage == "transferable"


def test_parameter_flashcard_requires_semantic_answer_and_writes_back_skill_item_key(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        scenarios=["Use dependency injection in one route"],
        weakest_points=["Still cannot explain the parameter meaning for Depends."],
        evidence=["The learner only repeats the API name."],
        mastery_stage="understood",
        mastery_stage_progress=["understood"],
    )

    deck = service.build_flash_deck(workspace_id)
    parameter_card = next(card for card in deck.cards if card.card_id.startswith("skill-fastapi-parameter-"))

    failed = service.submit_flashcard_answer(
        workspace_id,
        card_id=parameter_card.card_id,
        learner_answer="Depends",
    )
    assert not failed.correct
    assert failed.dependency_skill_map_history
    assert failed.dependency_skill_map_history[0].focus_item_key
    assert failed.dependency_skill_map_history[0].focus_item_key != parameter_card.card_id

    refreshed = service.snapshot(workspace_id)
    assert refreshed.recent_flash_attempts[0].dependency_layer == "parameter"
    assert refreshed.workspace["latest_flashcard_recovery_mode"] == "flashcards"
