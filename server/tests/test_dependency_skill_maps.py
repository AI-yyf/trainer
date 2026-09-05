from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import UserProfile
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService


def _make_service(tmp_path: Path) -> tuple[MemoryService, str]:
    repository = TrainerRepository(tmp_path / "dependency-skill-map.db")
    service = MemoryService(repository)
    workspace_id = "workspace-dependency-skill-map"
    repository.save_profile(
        workspace_id,
        UserProfile(
            long_term_goal="Master dependency APIs through project-first coaching",
            weekly_hours=4,
            teaching_style="guided",
            answer_policy="guided",
            preferred_libraries=["FastAPI"],
        ),
    )
    return service, workspace_id


def test_dependency_skill_maps_split_dependency_into_layers(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends", "APIRouter"],
        use_cases=["Route dependency injection", "Router composition"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still confuses when Depends is worth introducing."],
        evidence=["Flash recall is unstable.", "One route test still fails."],
        mastery_stage="practiced",
        mastery_stage_progress=["understood", "recalled", "practiced"],
    )
    structured.update_workspace(
        latest_learning_followup="Add one focused route boundary and verify the dependency executes once.",
        latest_learning_verified_result="The scratch route resolves the dependency correctly.",
        latest_learning_blocker="The learner still widens scope before proving the first route.",
    )

    snapshot = service.snapshot(workspace_id)

    assert snapshot.dependency_skill_maps
    fastapi_map = snapshot.dependency_skill_maps[0]
    assert fastapi_map.dependency_key == "fastapi"
    assert "api" in fastapi_map.covered_layers
    assert "scenario" in fastapi_map.covered_layers
    assert "verification" in fastapi_map.covered_layers
    assert fastapi_map.top_review_items
    assert any(item.layer == "api" and item.related_api == "Depends" for item in fastapi_map.items)
    assert any(item.layer == "misuse" for item in fastapi_map.items)
    assert fastapi_map.project_first_cut
    assert fastapi_map.suggested_scenario_lab


def test_dependency_skill_map_actions_persist_version_and_history(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        use_cases=["Route dependency injection"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still confuses when Depends is worth introducing."],
        evidence=["Flash recall is unstable."],
        mastery_stage="practiced",
        mastery_stage_progress=["understood", "recalled", "practiced"],
    )
    structured.update_workspace(
        latest_learning_followup="Add one focused route boundary and verify the dependency executes once.",
        latest_learning_verified_result="The scratch route resolves the dependency correctly.",
    )

    initial_snapshot = service.snapshot(workspace_id)
    assert initial_snapshot.dependency_skill_maps
    initial_map = initial_snapshot.dependency_skill_maps[0]
    initial_version = initial_map.version
    top_item = initial_map.top_review_items[0]

    synced_maps, history, scenario_lab = service.apply_dependency_skill_map_action(
        workspace_id,
        dependency_key="fastapi",
        action="start_scenario_lab",
        note="Start with one minimum dependency-injection lab.",
        focus_item_key=top_item.key,
        related_api=top_item.related_api,
        scenario=top_item.scenario,
    )

    assert synced_maps
    updated_map = synced_maps[0]
    assert updated_map.dependency_key == "fastapi"
    assert updated_map.version >= initial_version + 1
    assert updated_map.last_action == "start_scenario_lab"
    assert updated_map.last_action_note == "Start with one minimum dependency-injection lab."
    assert scenario_lab is not None
    assert scenario_lab.status in {"ready", "in_progress", "completed"}

    assert history
    latest_history = history[0]
    assert latest_history.dependency_key == "fastapi"
    assert latest_history.action == "start_scenario_lab"
    assert latest_history.version == updated_map.version
    assert latest_history.focus_item_key == top_item.key
    assert latest_history.focus_label == top_item.label
    assert latest_history.after_summary == updated_map.priority_summary

    persisted_snapshot = service.snapshot(workspace_id)
    assert persisted_snapshot.dependency_skill_maps[0].version == updated_map.version
    assert persisted_snapshot.dependency_skill_maps[0].last_action == "start_scenario_lab"
    assert persisted_snapshot.dependency_skill_map_history
    assert any(
        item.action == "start_scenario_lab"
        and item.version == updated_map.version
        and item.dependency_key == "fastapi"
        for item in persisted_snapshot.dependency_skill_map_history
    )


def test_dependency_skill_maps_prioritize_parameter_and_return_layers_for_review(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        use_cases=["Route dependency injection"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still cannot state the Depends parameter meaning or return semantics clearly."],
        evidence=["The learner only names Depends but cannot explain what gets passed or returned."],
        mastery_stage="understood",
        mastery_stage_progress=["understood"],
    )

    snapshot = service.snapshot(workspace_id)
    fastapi_map = snapshot.dependency_skill_maps[0]
    top_layers = [item.layer for item in fastapi_map.top_review_items]

    assert "parameter" in top_layers
    assert "return_value" in top_layers


def test_dependency_skill_map_flashcards_and_theory_drill_expose_knowledge_types(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        use_cases=["Route dependency injection"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still cannot state the Depends parameter meaning or return semantics clearly."],
        evidence=["The learner only names Depends but cannot explain what gets passed or returned."],
        mastery_stage="understood",
        mastery_stage_progress=["understood"],
    )

    snapshot = service.snapshot(workspace_id)
    assert snapshot.flash_deck is not None
    assert snapshot.theory_drill is not None

    parameter_flash = next(
        item for item in snapshot.flash_deck.cards if item.dependency_layer == "parameter"
    )
    return_theory = next(
        item for item in snapshot.theory_drill.questions if item.dependency_layer == "return_value"
    )
    misuse_theory = next(
        item for item in snapshot.theory_drill.questions if item.dependency_layer == "misuse"
    )

    assert parameter_flash.knowledge_type in {"parameter_semantics", "engineering_concept"}
    assert parameter_flash.question_style == "parameter_check"
    assert parameter_flash.verification_method
    assert parameter_flash.hint_ladder
    assert return_theory.knowledge_type == "return_value_semantics"
    assert return_theory.question_style == "return_value_check"
    assert misuse_theory.knowledge_type == "misuse_correction"
    assert misuse_theory.question_style == "misuse_correction"


def test_dependency_skill_map_exposes_selection_verification_and_transfer_knowledge_types(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=[],
        use_cases=[],
        scenarios=[],
        weakest_points=[],
        evidence=["The first route works but transfer is not yet proven."],
        mastery_stage="applied",
        mastery_stage_progress=["understood", "recalled", "practiced", "applied"],
        latest_transfer_blocked_reason="Transferable mastery needs explicit cross-project migration evidence.",
    )

    snapshot = service.snapshot(workspace_id)
    assert snapshot.flash_deck is not None

    concept_flash = next(item for item in snapshot.flash_deck.cards if item.dependency_layer == "concept")
    verification_flash = next(
        item for item in snapshot.flash_deck.cards if item.dependency_layer == "verification"
    )
    transfer_flash = next(item for item in snapshot.flash_deck.cards if item.dependency_layer == "transfer")
    fallback_dependency_flash = next(
        item for item in snapshot.flash_deck.cards if item.dependency_key == "fastapi" and item.dependency_layer == ""
    )

    assert concept_flash.knowledge_type == "dependency_selection"
    assert concept_flash.question_style == "short_answer"
    assert concept_flash.verification_method
    assert verification_flash.knowledge_type == "verification_method"
    assert verification_flash.question_style == "short_answer"
    assert verification_flash.verification_method
    assert transfer_flash.knowledge_type == "cross_context_transfer"
    assert transfer_flash.question_style == "scenario_answer"
    assert transfer_flash.verification_method
    assert fallback_dependency_flash.knowledge_type == "scenario_judgment"
    assert fallback_dependency_flash.question_style == "scenario_answer"


def test_dependency_skill_maps_restore_from_repository_after_service_rebuild(tmp_path: Path) -> None:
    repository = TrainerRepository(tmp_path / "dependency-skill-map-rebuild.db")
    service = MemoryService(repository)
    workspace_id = "workspace-dependency-skill-map-rebuild"
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        use_cases=["Route dependency injection"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still cannot state the Depends parameter meaning."],
        evidence=["The learner only names Depends but cannot explain the parameter."],
        mastery_stage="practiced",
        mastery_stage_progress=["understood", "recalled", "practiced"],
    )
    snapshot_before = service.snapshot(workspace_id)
    assert snapshot_before.dependency_skill_maps

    rebuilt = MemoryService(repository)
    rebuilt.clear_workspace_memory(workspace_id)
    snapshot_after = rebuilt.snapshot(workspace_id)
    assert snapshot_after.dependency_skill_maps
    assert snapshot_after.dependency_skill_maps[0].dependency_key == "fastapi"
    assert snapshot_after.dependency_skill_maps[0].priority_summary == snapshot_before.dependency_skill_maps[0].priority_summary


def test_dependency_skill_map_history_can_restore_prior_version(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        use_cases=["Route dependency injection"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still confuses when Depends is worth introducing."],
        evidence=["Flash recall is unstable."],
        mastery_stage="practiced",
        mastery_stage_progress=["understood", "recalled", "practiced"],
    )
    initial_snapshot = service.snapshot(workspace_id)
    initial_map = initial_snapshot.dependency_skill_maps[0]
    focus_item = initial_map.top_review_items[0]

    service.apply_dependency_skill_map_action(
        workspace_id,
        dependency_key="fastapi",
        action="mark_applied",
        note="Applied FastAPI Depends in a real route boundary.",
        focus_item_key=focus_item.key,
        related_api=focus_item.related_api,
        scenario=focus_item.scenario,
        verified_result="One focused route now resolves Depends exactly once.",
        verified_by_evaluator=True,
        verification_source="current_file_evaluator",
    )
    after_apply = service.snapshot(workspace_id)
    assert after_apply.dependency_skill_maps[0].last_action == "mark_applied"
    restore_target = min(
        after_apply.dependency_skill_map_history,
        key=lambda item: item.version,
    )

    restored_maps, restored_history = service.restore_dependency_skill_map_history(
        workspace_id,
        dependency_key="fastapi",
        history_entry_id=restore_target.entry_id,
        note="Restore the earlier governed dependency training state.",
    )

    assert restored_maps
    assert restored_maps[0].last_action == "restore_history"
    assert restored_maps[0].version > after_apply.dependency_skill_maps[0].version
    assert restored_maps[0].priority_summary == initial_map.priority_summary
    assert restored_history
    assert restored_history[0].action == "restore_history"
    assert restored_history[0].before_snapshot["last_action"] == "mark_applied"


def test_dependency_skill_map_stage_actions_advance_mastery_progress(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        use_cases=["Route dependency injection"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still cannot explain when Depends belongs in a route boundary."],
        evidence=["Theory recall is still unstable."],
        mastery_stage="understood",
        mastery_stage_progress=["understood"],
    )

    initial_snapshot = service.snapshot(workspace_id)
    assert initial_snapshot.dependency_skill_maps
    focus_item = initial_snapshot.dependency_skill_maps[0].top_review_items[0]

    service.apply_dependency_skill_map_action(
        workspace_id,
        dependency_key="fastapi",
        action="mark_practiced",
        note="Practiced one minimum Depends slice.",
        focus_item_key=focus_item.key,
        related_api=focus_item.related_api,
        scenario=focus_item.scenario,
        verified_result="The minimum route resolves one dependency correctly.",
        verified_by_evaluator=True,
        verification_source="current_file_evaluator",
    )
    practiced_snapshot = service.snapshot(workspace_id)
    practiced_mastery = next(
        item for item in practiced_snapshot.dependency_mastery if item.dependency_key == "fastapi"
    )
    assert practiced_mastery.mastery_stage == "practiced"
    assert "practiced" in (practiced_mastery.mastery_stage_progress or [])

    service.apply_dependency_skill_map_action(
        workspace_id,
        dependency_key="fastapi",
        action="mark_transferable",
        note="Reused the same Depends pattern in a new slice.",
        focus_item_key=focus_item.key,
        related_api=focus_item.related_api,
        scenario="cross_project_transfer",
        verified_result="The same boundary works in a second module without widening scope.",
        verified_by_evaluator=True,
        verification_source="current_file_evaluator",
    )
    blocked_snapshot = service.snapshot(workspace_id)
    blocked_mastery = next(
        item for item in blocked_snapshot.dependency_mastery if item.dependency_key == "fastapi"
    )
    assert blocked_mastery.mastery_stage == "applied"
    assert blocked_mastery.latest_transfer_blocked_reason

    service.apply_dependency_skill_map_action(
        workspace_id,
        dependency_key="fastapi",
        action="mark_transferable",
        note="Reused the same Depends pattern in another workspace slice.",
        focus_item_key=focus_item.key,
        related_api=focus_item.related_api,
        scenario="cross_project_transfer",
        verified_result="The same boundary works in a second workspace without widening scope.",
        transfer_source_workspace_id=workspace_id,
        transfer_target_workspace_id="workspace-fastapi-transfer-target",
        transfer_source_context="Original FastAPI route boundary",
        transfer_target_context="Second workspace route boundary",
        transfer_evidence_summary="Cross-project transfer verified in a second workspace.",
        verified_by_evaluator=True,
        verification_source="current_file_evaluator",
    )
    transfer_snapshot = service.snapshot(workspace_id)
    transfer_mastery = next(
        item for item in transfer_snapshot.dependency_mastery if item.dependency_key == "fastapi"
    )
    assert transfer_mastery.mastery_stage == "transferable"
    assert "transferable" in (transfer_mastery.mastery_stage_progress or [])


def test_dependency_skill_map_rejects_unverified_mastery_advancement(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        use_cases=["Route dependency injection"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still cannot explain when Depends belongs in a route boundary."],
        evidence=["Theory recall is still unstable."],
        mastery_stage="understood",
        mastery_stage_progress=["understood"],
    )
    before = service.snapshot(workspace_id)
    focus_item = before.dependency_skill_maps[0].top_review_items[0]

    with pytest.raises(ValueError, match="current-file verification"):
        service.apply_dependency_skill_map_action(
            workspace_id,
            dependency_key="fastapi",
            action="mark_practiced",
            note="The learner says this practice passed.",
            focus_item_key=focus_item.key,
            related_api=focus_item.related_api,
            scenario=focus_item.scenario,
            verified_result="A client supplied this result.",
        )

    after = service.snapshot(workspace_id)
    mastery = next(item for item in after.dependency_mastery if item.dependency_key == "fastapi")
    assert mastery.mastery_stage == "understood"
    assert after.dependency_skill_maps[0].version == before.dependency_skill_maps[0].version
    assert not any(item.action == "mark_practiced" for item in after.dependency_skill_map_history)


def test_only_verified_learning_outcome_advances_dependency_mastery(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        use_cases=["Route dependency injection"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still cannot explain when Depends belongs in a route boundary."],
        evidence=["Theory recall is still unstable."],
        mastery_stage="understood",
        mastery_stage_progress=["understood"],
    )

    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["FastAPI"],
        outcome="tests_passed",
        summary="The learner says the focused route test passed.",
        verified_result="A client supplied this result.",
    )
    unverified = next(
        item for item in service.snapshot(workspace_id).dependency_mastery if item.dependency_key == "fastapi"
    )
    assert unverified.mastery_stage == "understood"

    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["FastAPI"],
        outcome="tests_passed",
        summary="The evaluator confirmed the focused route test passed.",
        verified_result="The focused route now resolves its dependency once.",
        verified_by_evaluator=True,
    )
    verified = next(
        item for item in service.snapshot(workspace_id).dependency_mastery if item.dependency_key == "fastapi"
    )
    assert verified.mastery_stage == "applied"
