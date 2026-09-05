from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import UserProfile
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService


def _make_service(tmp_path: Path) -> tuple[MemoryService, str]:
    repository = TrainerRepository(tmp_path / "scenario-lab.db")
    service = MemoryService(repository)
    workspace_id = "workspace-scenario-lab"
    repository.save_profile(
        workspace_id,
        UserProfile(
            long_term_goal="Master dependency APIs through minimum scenarios",
            weekly_hours=4,
            teaching_style="guided",
            answer_policy="guided",
            preferred_libraries=["FastAPI"],
        ),
    )
    return service, workspace_id


def test_build_scenario_lab_from_dependency_mastery_and_workspace_signals(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends", "APIRouter"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still confuses when Depends is worth introducing."],
        evidence=["Flash recall is unstable."],
    )
    structured.update_workspace(
        latest_learning_focus_area="dependency injection",
        latest_learning_scenario="scenario_lab_or_project",
        latest_learning_blocker="The live project does not yet have a clean route boundary.",
        latest_flashcard_recovery_mode="scenario_lab_or_project",
        latest_turn_exercise_prompt="Build one minimal Depends example before touching the production route.",
        latest_turn_expected_artifact="One route plus one dependency function.",
        latest_turn_success_signal="The route resolves the dependency and returns the expected payload.",
        latest_turn_after_try="Bring back the route, the check result, and one migration step.",
        latest_turn_teach_back_prompt="Explain why Depends fits this scenario.",
        latest_turn_coach_checks=["State the boundary first", "Verify before widening scope"],
    )

    scenario_lab = service.build_scenario_lab(workspace_id)

    assert scenario_lab is not None
    assert scenario_lab.focus_area == "dependency injection"
    assert scenario_lab.dependency_keys == ["fastapi"]
    assert "Depends" in scenario_lab.related_apis
    assert scenario_lab.minimum_environment
    assert scenario_lab.learner_deliverables
    assert scenario_lab.verification_steps
    assert scenario_lab.migrate_back_guidance

    snapshot = service.snapshot(workspace_id)
    assert snapshot.scenario_lab is not None
    assert snapshot.scenario_lab.title == scenario_lab.title
    assert snapshot.scenario_lab.success_signal == scenario_lab.success_signal
    assert snapshot.scenario_lab.version == 1
    assert snapshot.scenario_lab.last_action == "created"
    assert snapshot.scenario_lab.status == "ready"
    assert snapshot.scenario_lab_history
    assert snapshot.scenario_lab_history[-1].action == "created"


def test_scenario_lab_actions_update_status_version_and_history(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still mixes up when to introduce Depends."],
        evidence=["Needs one minimum scenario first."],
    )
    structured.update_workspace(
        latest_learning_focus_area="dependency injection",
        latest_learning_scenario="scenario_lab_or_project",
        latest_flashcard_recovery_mode="scenario_lab_or_project",
    )

    created = service.build_scenario_lab(workspace_id)
    assert created is not None

    started, started_history = service.apply_scenario_lab_action(
        workspace_id,
        scenario_lab_id=created.id,
        action="start",
        note="Start the lab now.",
    )
    assert started is not None
    assert started.status == "in_progress"
    assert started.version == 2
    assert started.last_action == "start"
    assert started_history[0].action in {"started", "reviewed"}
    assert started_history[0].version == 2
    assert started_history[0].before_snapshot["version"] == 1
    assert started_history[0].after_snapshot["status"] == "in_progress"

    completed, completed_history = service.apply_scenario_lab_action(
        workspace_id,
        scenario_lab_id=created.id,
        action="complete",
        note="Finished and ready to migrate back.",
        review_outcome="The route resolves the dependency correctly.",
        verified_by_evaluator=True,
        verification_source="current_file_evaluator",
    )
    assert completed is not None
    assert completed.status == "completed"
    assert completed.version == 3
    assert completed.last_action == "complete"
    assert completed.review_outcome == "The route resolves the dependency correctly."
    assert completed_history[0].action in {"completed", "reviewed"}
    assert completed_history[0].version == 3
    assert completed_history[0].before_snapshot["status"] == "in_progress"
    assert completed_history[0].after_snapshot["status"] == "completed"
    snapshot = service.snapshot(workspace_id)
    assert snapshot.scenario_lab is not None
    assert snapshot.scenario_lab.status == "completed"
    assert snapshot.scenario_lab.review_outcome == "The route resolves the dependency correctly."
    assert snapshot.workspace["latest_training_submode"] in {"practice", "review"}
    assert snapshot.learning_outcomes
    assert snapshot.scenario_lab_history[-1].version >= 1
    assert snapshot.review_artifact is not None
    assert snapshot.review_artifact.focus_area == "dependency injection"
    assert snapshot.review_artifact.source == "scenario_lab"
    assert snapshot.review_artifact.status == "resolved"
    assert snapshot.review_artifact.verified_result == "The route resolves the dependency correctly."
    assert snapshot.review_artifact.metadata["verification_source"] == "current_file_evaluator"
    assert snapshot.review_artifact_history
    assert snapshot.review_artifact_history[0].action in {"resolved", "reviewed"}


def test_scenario_lab_rejects_stale_ids_and_unverified_completion(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        scenarios=["Inject one dependency into a route"],
    )
    scenario_lab = service.build_scenario_lab(workspace_id)
    assert scenario_lab is not None

    stale, stale_history = service.apply_scenario_lab_action(
        workspace_id,
        scenario_lab_id="scenario-stale",
        action="complete",
        note="A stale client must not create another lab.",
    )
    assert stale is None
    assert stale_history == []
    assert service.snapshot(workspace_id).scenario_lab is not None
    assert service.snapshot(workspace_id).scenario_lab.id == scenario_lab.id

    started, _ = service.apply_scenario_lab_action(
        workspace_id,
        scenario_lab_id=scenario_lab.id,
        action="start",
    )
    assert started is not None
    with pytest.raises(ValueError, match="server-side verification"):
        service.apply_scenario_lab_action(
            workspace_id,
            scenario_lab_id=scenario_lab.id,
            action="complete",
            note="A client note is not verification.",
            review_outcome="A client cannot claim this result.",
        )

    snapshot = service.snapshot(workspace_id)
    assert snapshot.scenario_lab is not None
    assert snapshot.scenario_lab.status == "in_progress"
    assert snapshot.learning_outcomes == []
    assert snapshot.review_artifact is None


def test_review_queue_actions_record_governed_history(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)

    accepted = service.apply_review_queue_action(
        workspace_id,
        concept="fastapi Depends",
        action="accept",
        focus_area="dependency injection",
        task_hint="Build one route with Depends.",
        note="Pull this into training.",
    )
    assert accepted
    assert accepted[0].action == "accept"
    assert accepted[0].outcome == "queued"

    reset = service.apply_review_queue_action(
        workspace_id,
        concept="fastapi Depends",
        action="reset",
        focus_area="dependency injection",
        task_hint="Go back to a minimum route first.",
        note="Still needs more practice.",
    )
    assert reset
    assert reset[0].action == "reset"
    assert reset[0].outcome == "needs_more_practice"

    snapshot = service.snapshot(workspace_id)
    assert snapshot.review_queue_actions
    assert snapshot.review_queue_actions[-1].action == "reset"
    assert "Still needs more practice." in snapshot.weaknesses[0]
    assert snapshot.review_artifact is not None
    assert snapshot.review_artifact.focus_area == "fastapi Depends"
    assert snapshot.review_artifact.source == "review_queue"
    assert snapshot.review_artifact.recommended_recovery_mode == "review_queue"
    assert snapshot.review_artifact_history
    assert snapshot.review_artifact_history[0].action == "reviewed"


def test_review_queue_focus_area_batch_actions_apply_to_matching_items(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.record_weakness(
        "fastapi Depends",
        "Still mixes up when to introduce Depends.",
        severity=2,
        review_after_days=0,
        context="dependency injection",
    )
    structured.record_weakness(
        "router boundary",
        "Still widens scope too early.",
        severity=2,
        review_after_days=0,
        context="dependency injection",
    )
    structured.record_weakness(
        "pytest fixture",
        "Still forgets what the fixture should isolate.",
        severity=2,
        review_after_days=0,
        context="testing",
    )

    accepted = service.apply_review_queue_action(
        workspace_id,
        concept="fastapi Depends",
        action="accept",
        scope="focus_area",
        focus_area="dependency injection",
        batch_limit=4,
        note="Pull the dependency injection group back into training.",
    )
    assert len(accepted) >= 2
    assert all(item.action == "accept" for item in accepted[:2])
    assert all(item.focus_area == "dependency injection" for item in accepted[:2])

    snapshot = service.snapshot(workspace_id)
    concepts = [item.concept for item in snapshot.review_queue_actions]
    assert "fastapi Depends" in concepts
    assert "router boundary" in concepts


def test_scenario_lab_history_can_restore_prior_version(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still mixes up when to introduce Depends."],
        evidence=["Needs one minimum scenario first."],
    )
    structured.update_workspace(
        latest_learning_focus_area="dependency injection",
        latest_learning_scenario="scenario_lab_or_project",
        latest_flashcard_recovery_mode="scenario_lab_or_project",
    )

    created = service.build_scenario_lab(workspace_id)
    assert created is not None

    started, started_history = service.apply_scenario_lab_action(
        workspace_id,
        scenario_lab_id=created.id,
        action="start",
        note="Start the lab now.",
    )
    assert started is not None
    restore_target = min(started_history, key=lambda item: item.version)

    restored, restored_history = service.restore_scenario_lab_history(
        workspace_id,
        scenario_lab_id=created.id,
        history_entry_id=restore_target.entry_id,
        history_version=restore_target.version,
        note="Restore the original minimum training state.",
    )
    assert restored is not None
    assert restored.last_action == "restore_history"
    assert restored.status == created.status
    assert restored.title == created.title
    assert restored.version > started.version
    assert restored_history[0].action == "restore_history"
    assert restored_history[0].before_snapshot["last_action"] == "start"

    snapshot = service.snapshot(workspace_id)
    assert snapshot.scenario_lab is not None
    assert snapshot.scenario_lab.last_action == "restore_history"
    assert snapshot.workspace["latest_training_submode"] == "practice"


def test_review_artifact_history_can_restore_prior_version(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)

    service.apply_review_queue_action(
        workspace_id,
        concept="fastapi Depends",
        action="accept",
        focus_area="dependency injection",
        task_hint="Build one route with Depends.",
        note="Pull this into training.",
    )
    initial_snapshot = service.snapshot(workspace_id)
    initial_artifact = initial_snapshot.review_artifact
    assert initial_artifact is not None

    structured.record_weakness(
        "fastapi Depends",
        "Still cannot keep the route boundary stable.",
        severity=2,
        review_after_days=0,
        context="dependency injection",
    )
    service.apply_review_queue_action(
        workspace_id,
        concept="fastapi Depends",
        action="reset",
        focus_area="dependency injection",
        task_hint="Go back to one minimum route first.",
        note="Still needs more practice.",
    )
    updated_snapshot = service.snapshot(workspace_id)
    updated_artifact = updated_snapshot.review_artifact
    assert updated_artifact is not None
    assert updated_artifact.version > initial_artifact.version

    restore_target = min(updated_snapshot.review_artifact_history, key=lambda item: item.version)
    restored, restored_history = service.restore_review_artifact_history(
        workspace_id,
        review_artifact_id=updated_artifact.id,
        history_entry_id=restore_target.entry_id,
        history_version=restore_target.version,
        note="Restore the earlier governed review state.",
    )
    assert restored is not None
    assert restored.last_action == "restore_history"
    assert restored.focus_area == initial_artifact.focus_area
    assert restored.summary == initial_artifact.summary
    assert restored.recommended_recovery_mode == initial_artifact.recommended_recovery_mode
    assert restored.version > updated_artifact.version
    assert restored_history[0].action == "restore_history"
    assert restored_history[0].before_snapshot["last_action"] == "reviewed"

    snapshot = service.snapshot(workspace_id)
    assert snapshot.review_artifact is not None
    assert snapshot.review_artifact.last_action == "restore_history"
    assert snapshot.workspace["latest_training_submode"] == "review"


def test_review_artifact_actions_update_status_history_and_training_signals(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)

    service.apply_review_queue_action(
        workspace_id,
        concept="fastapi Depends",
        action="accept",
        focus_area="dependency injection",
        task_hint="Build one route with Depends.",
        note="Pull this into training.",
    )
    snapshot = service.snapshot(workspace_id)
    artifact = snapshot.review_artifact
    assert artifact is not None

    reviewed, reviewed_history = service.apply_review_artifact_action(
        workspace_id,
        review_artifact_id=artifact.id,
        action="reviewed",
        note="Review the current blocker before the next self-implementation.",
    )
    assert reviewed is not None
    assert reviewed.status == "active"
    assert reviewed.last_action == "reviewed"
    assert reviewed_history[0].action == "reviewed"

    resolved, resolved_history = service.apply_review_artifact_action(
        workspace_id,
        review_artifact_id=artifact.id,
        action="resolved",
        note="The review is now explicit enough to drive the next self-owned slice.",
    )
    assert resolved is not None
    assert resolved.status == "resolved"
    assert resolved.last_action == "resolved"
    assert resolved.verified_result
    assert resolved.blocker == ""
    assert resolved.partial_progress == ""
    assert resolved_history[0].action == "resolved"
    assert resolved_history[0].before_snapshot["status"] == "active"
    assert resolved_history[0].after_snapshot["status"] == "resolved"

    reopened, reopened_history = service.apply_review_artifact_action(
        workspace_id,
        review_artifact_id=artifact.id,
        action="reopened",
        note="Pull the review back into the active loop because one boundary is still shaky.",
    )
    assert reopened is not None
    assert reopened.status == "active"
    assert reopened.last_action == "reopened"
    assert reopened_history[0].action == "reopened"

    archived, archived_history = service.apply_review_artifact_action(
        workspace_id,
        review_artifact_id=artifact.id,
        action="archived",
        note="Archive this governed review as historical evidence.",
    )
    assert archived is not None
    assert archived.status == "archived"
    assert archived.last_action == "archived"
    assert archived_history[0].action == "archived"

    final_snapshot = service.snapshot(workspace_id)
    assert final_snapshot.review_artifact is not None
    assert final_snapshot.review_artifact.status == "archived"
    assert final_snapshot.workspace["latest_training_submode"] == "review_queue"


def test_review_artifact_updated_action_rewrites_fields_and_history(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)

    service.apply_review_queue_action(
        workspace_id,
        concept="fastapi Depends",
        action="accept",
        focus_area="dependency injection",
        task_hint="Build one route with Depends.",
        note="Pull this into training.",
    )
    snapshot = service.snapshot(workspace_id)
    artifact = snapshot.review_artifact
    assert artifact is not None

    updated, history = service.apply_review_artifact_action(
        workspace_id,
        review_artifact_id=artifact.id,
        action="updated",
        note="Refine the review before the next self-owned slice.",
        edit_patch={
            "summary": "The learner can describe the route shape but still confuses dependency boundaries.",
            "root_cause": "They recognize Depends but cannot explain where the boundary should stay.",
            "guardrail": "Keep exactly one route and one dependency until the verification stays stable.",
            "next_self_implementation_rule": "Rebuild the same route without widening scope first.",
            "recommended_recovery_mode": "review",
            "recommended_actions": [
                "Rebuild one route with one dependency.",
                "Verify the same route twice before adding another branch.",
            ],
            "verified_result": "One controlled route now resolves the dependency correctly.",
            "partial_progress": "The learner already stabilized the handler signature.",
        },
    )
    assert updated is not None
    assert updated.last_action == "updated"
    assert updated.summary.startswith("The learner can describe")
    assert updated.root_cause.startswith("They recognize Depends")
    assert updated.guardrail.startswith("Keep exactly one route")
    assert updated.next_self_implementation_rule.startswith("Rebuild the same route")
    assert updated.recommended_recovery_mode == "review"
    assert updated.recommended_actions[0] == "Rebuild one route with one dependency."
    assert history[0].action == "updated"
    assert history[0].before_snapshot["summary"] == artifact.summary
    assert history[0].after_snapshot["summary"] == updated.summary

    refreshed = service.snapshot(workspace_id)
    assert refreshed.workspace["latest_training_submode"] == "review"
    assert refreshed.workspace["latest_learning_followup"] == updated.next_self_implementation_rule
    assert refreshed.workspace["latest_learning_verified_result"] == updated.verified_result


def test_theory_drill_actions_update_status_history_and_training_signals(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still cannot explain when Depends belongs in a concrete route."],
        evidence=["Theory recall around Depends is still unstable."],
    )
    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["dependency injection", "Depends"],
        outcome="repeated_error",
        summary="Still cannot explain when Depends belongs in a real route.",
        focus_area="dependency injection",
        scenario="dependency_mastery",
        blocked_reason="Cannot connect Depends back to a concrete route handler.",
    )

    initial_snapshot = service.snapshot(workspace_id)
    theory_drill = initial_snapshot.theory_drill
    assert theory_drill is not None

    archived, archived_history = service.apply_theory_drill_action(
        workspace_id,
        theory_drill_id=theory_drill.id,
        action="archive",
        note="Archive this governed theory drill for now.",
    )
    assert archived is not None
    assert archived.status == "archived"
    assert archived.last_action == "archived"
    assert archived.version > theory_drill.version
    assert archived_history[0].action == "archived"
    assert archived_history[0].before_snapshot["status"] == theory_drill.status
    assert archived_history[0].after_snapshot["status"] == "archived"

    reopened, reopened_history = service.apply_theory_drill_action(
        workspace_id,
        theory_drill_id=theory_drill.id,
        action="reopen",
        note="Pull the theory drill back into the active training lane.",
    )
    assert reopened is not None
    assert reopened.status == "in_progress"
    assert reopened.last_action == "reopened"
    assert reopened.version > archived.version
    assert reopened_history[0].action == "reopened"
    assert reopened_history[0].before_snapshot["status"] == "archived"
    assert reopened_history[0].after_snapshot["status"] == "in_progress"

    final_snapshot = service.snapshot(workspace_id)
    assert final_snapshot.theory_drill is not None
    assert final_snapshot.theory_drill.status == "in_progress"
    assert final_snapshot.workspace["latest_training_submode"] == "review"
    assert final_snapshot.workspace["latest_learning_scenario"] == "theory_drill"


def test_theory_drill_history_can_restore_prior_version(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        scenarios=["Inject one dependency into a route"],
        weakest_points=["Still cannot explain when Depends belongs in a concrete route."],
        evidence=["Theory recall around Depends is still unstable."],
    )
    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["dependency injection", "Depends"],
        outcome="repeated_error",
        summary="Still cannot explain when Depends belongs in a real route.",
        focus_area="dependency injection",
        scenario="dependency_mastery",
        blocked_reason="Cannot connect Depends back to a concrete route handler.",
    )

    initial_snapshot = service.snapshot(workspace_id)
    theory_drill = initial_snapshot.theory_drill
    assert theory_drill is not None

    archived, archived_history = service.apply_theory_drill_action(
        workspace_id,
        theory_drill_id=theory_drill.id,
        action="archive",
        note="Archive this governed theory drill for now.",
    )
    assert archived is not None
    restore_target = min(archived_history, key=lambda item: item.version)

    restored, restored_history = service.restore_theory_drill_history(
        workspace_id,
        theory_drill_id=theory_drill.id,
        history_entry_id=restore_target.entry_id,
        history_version=restore_target.version,
        note="Restore the earlier governed theory drill state.",
    )
    assert restored is not None
    assert restored.last_action == "restore_history"
    assert restored.title == theory_drill.title
    assert restored.status == theory_drill.status
    assert restored.version > archived.version
    assert restored_history[0].action == "restore_history"
    assert restored_history[0].before_snapshot["last_action"] == "archived"

    final_snapshot = service.snapshot(workspace_id)
    assert final_snapshot.theory_drill is not None
    assert final_snapshot.theory_drill.last_action == "restore_history"
    assert final_snapshot.workspace["latest_learning_scenario"] == "theory_drill"
