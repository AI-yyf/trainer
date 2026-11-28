"""(x) Small contracts: task specs, restore-list schema evolution, scenario lab,
    project identity and maturity-harness classification.

Guarantees covered:
  * task specification extracts verifiable requirements from natural language;
  * the restore list tolerates schema evolution without losing items;
  * scenario lab and project identity keep their documented contracts;
  * the maturity harness classifies turns from real grounding outcomes.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_scenario_lab.py
  * server/tests/test_maturity_harness_classification.py
  * server/tests/test_project_identity_model.py
  * server/tests/test_maturity_harness_literature.py
  * server/tests/test_specs.py
  * server/tests/test_restore_list.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.models import GlobalPlan, TaskSpecifyRequest, UserProfile
from app.core.settings import AppSettings
from app.db.repository import TrainerRepository
from app.main import create_app
from app.memory.models import TeachingStrategyEffectivenessRecord
from app.memory.service import MemoryService, StructuredMemoryService
from app.specs import TaskSpecGenerator, TaskSpecificationRequest
from app.specs.service import SpecService
from app.workspace.provisioning import ProjectProvisioningConflictError

# ---------------------------------------------------------------------------
# Restored from test_scenario_lab.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Restored from test_maturity_harness_classification.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]


HARNESS_PATH = REPO_ROOT / "scripts" / "maturity" / "real_teaching_journeys_minimax.py"


CASE = {
    "id": "probe-case",
    "topic_tokens": ["grid"],
    "runtime": "python",
    "primary_file": "x.py",
}


@pytest.fixture(scope="module")
def harness() -> Any:
    sys.path.insert(0, str(REPO_ROOT / "server"))
    spec = importlib.util.spec_from_file_location("maturity_harness", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(
    *,
    next_step: str,
    reply: str = "我们看一下边界。",
    outcome: str | None = None,
    symbols: tuple[str, ...] = (),
    retry_used: bool = False,
    flag: bool = False,
    fell_back: bool = False,
    clean_stamp: bool = False,
) -> dict:
    if fell_back:
        agent_meta: dict[str, object] = {"fell_back": True}
    elif clean_stamp:
        agent_meta = {}
    else:
        agent_meta = {
            "grounding_outcome": outcome,
            "grounding_ungrounded_symbols": list(symbols),
            "grounding_retry_used": retry_used,
            "next_step_requires_confirmation": flag,
        }
    return {
        "reply": {"content": reply},
        "coach_turn": {"next_step": next_step, "requires_confirmation": flag},
        "agent_meta": agent_meta,
        "snapshot": {"memory": {}},
    }


def test_downgraded_server_turn_is_never_passed(harness: Any) -> None:
    """M2: a downgraded turn is a grounding failure even when M5 agrees."""
    payload = _payload(
        outcome="downgraded",
        next_step="给我 `parse_header()` 的函数名。",
        symbols=("parse_header",),
        flag=True,
    )

    result = harness.classify_and_check_turn(
        CASE, 1, payload, None, code_text="grid = 1\n", message="为什么失败"
    )

    assert result["classification"] == "failed"
    assert result["grounding_pass"] is False
    assert result["flagged"] is True
    # The reconciliation itself agrees (M5 ok) — the failure is M2, not M5.
    assert result["reconciliation"] == "ok"


def test_grounded_stamp_with_matching_local_recompute_passes(harness: Any) -> None:
    payload = _payload(outcome="grounded", next_step="再对 `grid` 做一次实验。")

    result = harness.classify_and_check_turn(
        CASE, 1, payload, None, code_text="grid = 1\n", message="我们看边界"
    )

    assert result["classification"] == "passed"
    assert result["grounding_pass"] is True
    assert result["reconciliation"] == "ok"


def test_clean_reply_without_stamp_requires_a_grounded_step(harness: Any) -> None:
    grounded = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(next_step="再对 `grid` 做一次实验。", clean_stamp=True),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert grounded["classification"] == "passed"

    ungrounded = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(next_step="给我 `parse_header()` 的函数名。", clean_stamp=True),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert ungrounded["classification"] == "failed"
    assert "no grounding stamp" in ungrounded["reconciliation"]


def test_corrected_outcome_requires_retry_flag_and_no_downgrade_flag(harness: Any) -> None:
    ok = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(
            outcome="corrected",
            next_step="再对 `grid` 做一次实验。",
            retry_used=True,
        ),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert ok["classification"] == "passed"

    missing_retry = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(
            outcome="corrected",
            next_step="再对 `grid` 做一次实验。",
            retry_used=False,
        ),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert missing_retry["classification"] == "failed"
    assert "without retry_used" in missing_retry["reconciliation"]

    flagged = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(
            outcome="corrected",
            next_step="再对 `grid` 做一次实验。",
            retry_used=True,
            flag=True,
        ),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert flagged["classification"] == "failed"
    assert "requires_confirmation" in flagged["reconciliation"]


def test_recovery_override_is_not_a_teaching_pass(harness: Any) -> None:
    result = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(outcome="recovery_override", next_step="继续上一轮。"),
        None,
        code_text="grid = 1\n",
        message="继续",
    )
    assert result["classification"] == "failed"
    assert "recovery override" in result["reconciliation"]


def test_provider_error_and_local_fallback_classification(harness: Any) -> None:
    error = harness.classify_and_check_turn(
        CASE, 1, None, "HTTP 502", code_text="grid = 1\n", message="为什么失败"
    )
    assert error["classification"] == "provider_error"

    fallback = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(next_step="继续。", fell_back=True),
        None,
        code_text="grid = 1\n",
        message="继续",
    )
    assert fallback["classification"] == "local_fallback"


def test_history_anchored_symbol_reconciles_with_history(harness: Any) -> None:
    """M5 parity: the server anchors symbols in the conversation history; the
    local recompute needs the same history to agree."""
    payload = _payload(
        outcome="grounded",
        next_step="在 `history_helper` 里补一个边界判断。",
        reply="我们看之前那条线。",
    )
    history_text = "user: 我们之前定义了 history_helper\nassistant: 好，记住它。"
    code_text = "grid = 1\n"

    with_history = harness.classify_and_check_turn(
        CASE,
        1,
        payload,
        None,
        code_text=code_text,
        message="继续之前那条线",
        history_text=history_text,
    )
    assert with_history["classification"] == "passed"

    # Control: without the history corpus the local recompute disagrees and
    # the same turn is failed — the exact mismatch the parity fix removes.
    without_history = harness.classify_and_check_turn(
        CASE,
        1,
        payload,
        None,
        code_text=code_text,
        message="继续之前那条线",
        history_text="",
    )
    assert without_history["classification"] == "failed"


def test_file_pointer_reconciles_with_workspace_checker(harness: Any, tmp_path: Path) -> None:
    """M5 parity: the local recompute mirrors the server's workspace-scoped
    file checker instead of guessing."""
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()
    next_step = "查看 `legacy_report.py` 的第 10 行。"

    missing = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(outcome="downgraded", next_step=next_step, symbols=("legacy_report.py",), flag=True),
        None,
        code_text="grid = 1\n",
        message="看一下旧报告",
        workspace_root=workspace_root,
    )
    assert missing["classification"] == "failed"
    assert missing["reconciliation"] == "ok"  # both sides agree it is missing

    (workspace_root / "legacy_report.py").write_text("x = 1\n", encoding="utf-8")
    present = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(outcome="grounded", next_step=next_step),
        None,
        code_text="grid = 1\n",
        message="看一下旧报告",
        workspace_root=workspace_root,
    )
    assert present["classification"] == "passed"


def test_classification_enum_has_no_unreachable_members(harness: Any) -> None:
    """``mock`` had no assignment path anywhere in the harness (2026-10-13
    review): the enum now lists exactly the producible states."""
    assert set(harness.TURN_CLASSIFICATIONS) == {
        "passed",
        "failed",
        "provider_error",
        "local_fallback",
        "skipped_no_credentials",
    }


# ---------------------------------------------------------------------------
# Restored from test_project_identity_model.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _runtime(tmp_path: Path):
    app = create_app(
        AppSettings(
            app_name="Trainer Identity Test",
            host="127.0.0.1",
            port=8765,
            data_dir=tmp_path,
            database_name="identity-runtime.db",
            default_session_stage="intake",
            summary_message_limit=6,
        )
    )
    return app.state.runtime


def test_one_root_creates_isolated_project_contexts(tmp_path: Path) -> None:
    root_path = tmp_path / "TrainerWorkspace"
    alpha_path = root_path / "Projects" / "alpha"
    beta_path = root_path / "Projects" / "beta"
    alpha_path.mkdir(parents=True)
    beta_path.mkdir(parents=True)
    runtime = _runtime(tmp_path)
    runtime.repository.ensure_default_local_owner()
    runtime.repository.save_global_plan(
        GlobalPlan(
            id="global-identity-plan",
            ownerId="local-trainer",
            title="Long-term growth",
            summary="Keep separate projects connected to one growth record.",
        )
    )
    runtime.register_workspace_path("legacy-alpha", str(root_path))

    alpha = runtime.provision_project_adoption(
        workspace_id="legacy-alpha",
        root_path=str(root_path),
        project_path=str(alpha_path),
        project_name="alpha",
    )
    beta = runtime.provision_project_adoption(
        workspace_id="legacy-beta",
        root_id=alpha.root_id,
        project_path=str(beta_path),
        project_name="beta",
    )

    assert alpha.root_id == beta.root_id
    assert alpha.project_id != beta.project_id
    assert alpha.context_id != beta.context_id
    assert alpha.workspace_id == alpha.context_id
    assert beta.workspace_id == beta.context_id
    assert alpha.project_plan_id != beta.project_plan_id
    assert alpha.project_memory_id != beta.project_memory_id
    assert alpha.project_training_id != beta.project_training_id
    assert alpha.agent_session_id != beta.agent_session_id
    assert runtime.repository.resolve_context_id("legacy-alpha") == alpha.context_id
    assert runtime.repository.resolve_context_id("legacy-beta") == beta.context_id
    # Adoption records the global-plan identity, but must not invent a
    # project plan or a link before an explicit project-plan action.
    assert runtime.repository.get_global_plan_project_link(
        "global-identity-plan", alpha.context_id, alpha.project_plan_id
    ) is None
    assert runtime.repository.get_global_plan_project_link(
        "global-identity-plan", beta.context_id, beta.project_plan_id
    ) is None

    repeated = runtime.provision_project_adoption(
        workspace_id="legacy-alpha",
        context_id=alpha.context_id,
        root_id=alpha.root_id,
        root_path=str(root_path),
        project_path=str(alpha_path),
        project_name="alpha",
    )
    assert repeated.context_id == alpha.context_id
    assert runtime.resolve_workspace_path("legacy-alpha") == str(alpha_path.resolve())
    assert runtime.resolve_workspace_path("legacy-beta") == str(beta_path.resolve())


def test_provisioning_keeps_camel_case_json_aliases(tmp_path: Path) -> None:
    root_path = tmp_path / "workspace"
    project_path = root_path / "project"
    project_path.mkdir(parents=True)
    runtime = _runtime(tmp_path)
    runtime.register_workspace_path("legacy-alias", str(root_path))

    provisioning = runtime.provision_project_adoption(
        workspace_id="legacy-alias",
        root_path=str(root_path),
        project_path=str(project_path),
        project_name="project",
    )

    payload = provisioning.model_dump(by_alias=True, mode="json")
    assert payload["workspaceId"] == provisioning.context_id
    assert payload["contextId"] == provisioning.context_id
    assert payload["rootId"] == provisioning.root_id
    assert payload["projectId"] == provisioning.project_id
    assert "workspace_id" not in payload
    assert "context_id" not in payload


def test_reconcile_root_and_project_location_preserves_identity(tmp_path: Path) -> None:
    root_path = tmp_path / "root-one"
    project_path = root_path / "project"
    moved_root_path = tmp_path / "root-two"
    moved_project_path = moved_root_path / "project-renamed"
    project_path.mkdir(parents=True)
    moved_project_path.mkdir(parents=True)
    runtime = _runtime(tmp_path)
    runtime.register_workspace_path("legacy-reconcile", str(root_path))
    provisioning = runtime.provision_project_adoption(
        workspace_id="legacy-reconcile",
        root_path=str(root_path),
        project_path=str(project_path),
        project_name="project",
    )

    root = runtime.reconcile_trainer_root(provisioning.root_id, str(moved_root_path))
    project = runtime.reconcile_project_location(
        root_id=provisioning.root_id,
        project_id=provisioning.project_id,
        project_path=str(moved_project_path),
        project_name="project-renamed",
    )
    restored = runtime.get_project_provisioning(provisioning.context_id)

    assert root.root_id == provisioning.root_id
    assert root.revision == 2
    assert str(root_path.resolve()) in root.path_history
    assert project.project_id == provisioning.project_id
    assert project.revision == 2
    assert str(project_path.resolve()) in project.path_history
    assert restored is not None
    assert restored.context_id == provisioning.context_id
    assert restored.root_path == str(moved_root_path.resolve())
    assert restored.project_path == str(moved_project_path.resolve())
    assert restored.root_revision == 2
    assert restored.project_revision == 2


def test_selected_trainer_root_and_external_project_keep_distinct_identities(tmp_path: Path) -> None:
    root_path = tmp_path / "root"
    external_project = tmp_path / "external-project"
    root_path.mkdir()
    external_project.mkdir()
    runtime = _runtime(tmp_path)
    runtime.register_workspace_path("legacy-root", str(root_path))
    provisioning = runtime.provision_project_adoption(
        workspace_id="legacy-root",
        root_path=str(root_path),
        project_path=str(external_project),
        project_name="external-project",
    )

    assert provisioning.root_path == str(root_path.resolve())
    assert provisioning.project_path == str(external_project.resolve())
    assert provisioning.root_path != provisioning.project_path

    with pytest.raises(ProjectProvisioningConflictError, match="must be different directories"):
        runtime.provision_project_adoption(
            workspace_id="legacy-invalid-root-project",
            root_id=provisioning.root_id,
            root_path=str(root_path),
            project_path=str(root_path),
            project_name="root-is-not-a-project",
        )


def test_identity_routes_expose_reconcile_state(tmp_path: Path) -> None:
    first_root = tmp_path / "first-root"
    first_project = first_root / "project"
    moved_root = tmp_path / "moved-root"
    moved_project = moved_root / "project"
    first_project.mkdir(parents=True)
    moved_project.mkdir(parents=True)
    app = create_app(
        AppSettings(
            app_name="Trainer Identity Route Test",
            host="127.0.0.1",
            port=8765,
            data_dir=tmp_path,
            database_name="identity-routes.db",
            default_session_stage="intake",
            summary_message_limit=6,
        )
    )
    with TestClient(app) as client:
        runtime = app.state.runtime
        runtime.register_workspace_path("legacy-route", str(first_root))
        provisioning = runtime.provision_project_adoption(
            workspace_id="legacy-route",
            root_path=str(first_root),
            project_path=str(first_project),
            project_name="project",
        )
        root_response = client.post(
            f"/workspace/roots/{provisioning.root_id}/reconcile",
            json={"rootId": provisioning.root_id, "rootPath": str(moved_root)},
        )
        assert root_response.status_code == 200
        root_identity = root_response.json()["root_identity"]
        assert root_identity["rootId"] == provisioning.root_id
        assert root_identity["pending"] is True
        assert root_identity["reconcile"]["pendingProjectIds"] == [provisioning.project_id]

        project_response = client.post(
            f"/workspace/projects/{provisioning.project_id}/reconcile",
            json={"rootId": provisioning.root_id, "projectPath": str(moved_project)},
        )
        assert project_response.status_code == 200
        identity = project_response.json()["project_identity"]
        assert identity["contextId"] == provisioning.context_id
        assert identity["canonicalProjectPath"] == str(moved_project.resolve())
        assert identity["pending"] is False
        assert identity["reconcile"]["project"]["state"] == "reconciled"

        identity_response = client.get("/workspace/identity", params={"workspace_id": "legacy-route"})
        assert identity_response.status_code == 200
        assert identity_response.json()["contextId"] == provisioning.context_id


# ---------------------------------------------------------------------------
# Restored from test_maturity_harness_literature.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


LITERATURE_IDS = (
    "L1-close-read-annotate",
    "L2-imitation-transfer",
    "L3-theory-concept-card",
    "L4-compare-two-pieces",
)


def test_matrix_shape_code_and_literature(harness: Any) -> None:
    ids = {case["id"] for case in harness.CASES}
    assert len(harness.CASES) == 32
    assert set(LITERATURE_IDS) <= ids
    by_id = {case["id"]: case for case in harness.CASES}
    code_ids = [case["id"] for case in harness.CASES if case.get("subject", "code") == "code"]
    assert len(code_ids) == 28
    # The original code cases are untouched: their ids stay unique and their
    # subject defaults to code.
    for legacy in ("01-mutable-default", "A4-dict-mutation", "G4-return-after-days"):
        assert by_id[legacy].get("subject", "code") == "code"
    literature = [id_ for id_ in LITERATURE_IDS]
    subjects = {by_id[id_]["subject"] for id_ in literature}
    assert subjects == {"literature"}
    assert {by_id[id_]["category"] for id_ in literature} == {"L"}
    assert all(by_id[id_]["language_id"] == "markdown" for id_ in literature)


def test_literature_fixture_backbone_is_locally_real(harness: Any, tmp_path: Any) -> None:
    """Stub deliverable fails the checker; the completed work passes it."""
    by_id = {case["id"]: case for case in harness.CASES}
    for id_ in LITERATURE_IDS:
        fixture = harness.check_case_fixture(by_id[id_], tmp_path / id_)
        assert fixture["fixture_ok"] is True, (id_, fixture)
        assert fixture["pre_fix_exit"] != 0
        assert fixture["post_fix_exit"] == 0


def test_literature_turn_payload_keeps_markdown_language(harness: Any) -> None:
    by_id = {case["id"]: case for case in harness.CASES}
    code_case = by_id["01-mutable-default"]
    literature_case = by_id["L1-close-read-annotate"]
    provider = {"name": "probe"}
    code_payload = harness.turn_payload(
        "session", code_case, "msg", "grid = 1\n",
        file_path="projects/x/x.py", provider=provider, api_key="k",
    )
    assert code_payload["current_file"]["language_id"] == "python"
    literature_payload = harness.turn_payload(
        "session", literature_case, "msg", "¶1 渡船离开码头时，灯还没熄。",
        file_path="projects/L1/夜航.md", provider=provider, api_key="k",
    )
    assert literature_payload["current_file"]["language_id"] == "markdown"
    # The material is the primary file and must not claim a code language.
    assert literature_case["primary_file"].endswith(".md")
    assert {"精读", "批注", "锚点"} & set(literature_case["topic_tokens"])


def test_subset_selection_still_validates_literature_ids(harness: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("TRAINER_MATURITY_CASE_IDS", ",".join(LITERATURE_IDS))
    selected = harness.selected_cases()
    assert [case["id"] for case in selected] == list(LITERATURE_IDS)
    monkeypatch.setenv("TRAINER_MATURITY_CASE_IDS", "L9-imaginary")
    with pytest.raises(RuntimeError, match="TRAINER_MATURITY_CASE_IDS"):
        harness.selected_cases()


def test_skip_mode_report_never_targets_the_standing_report(harness: Any, monkeypatch: Any, tmp_path: Any) -> None:
    """No-credential runs (subset OR full) write their own dated file."""
    monkeypatch.delenv("TRAINER_MATURITY_REPORT_PATH", raising=False)
    cases = [case for case in harness.CASES]  # full matrix
    standing = harness.report_target_path(cases, mode="skipped_no_credentials")
    assert standing.name != "2026-10-13-teaching-journeys-report.md"
    subset = cases[:2]
    subset_path = harness.report_target_path(subset, mode="skipped_no_credentials")
    assert "subset" in subset_path.name and standing.name != subset_path.name
    override = tmp_path / "custom-report.md"
    monkeypatch.setenv("TRAINER_MATURITY_REPORT_PATH", str(override))
    assert harness.report_target_path(cases, mode="skipped_no_credentials") == override


# ---------------------------------------------------------------------------
# Restored from test_specs.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


class TaskSpecTests(unittest.TestCase):
    def test_generator_extracts_constraint_signals(self) -> None:
        generator = TaskSpecGenerator()
        result = generator.generate(
            TaskSpecificationRequest(
                prompt=(
                    "Build a parser.\n"
                    "- Input: accept a markdown string.\n"
                    "- Output: return headings.\n"
                    "- Must ignore empty lines.\n"
                    "- Raise an error on invalid indentation."
                )
            )
        )
        self.assertEqual(result.spec.inputs[0], "Input: accept a markdown string.")
        self.assertTrue(any("Must ignore empty lines." == item for item in result.spec.constraints))
        self.assertTrue(any("Raise an error on invalid indentation." == item for item in result.spec.failure_conditions))

    def test_generator_extracts_chinese_verifiable_requirement_signals(self) -> None:
        generator = TaskSpecGenerator()
        result = generator.generate(
            TaskSpecificationRequest(
                prompt=(
                    "实现一个用户注册校验器。输入：用户名、邮箱和密码；输出：校验结果和提示信息；"
                    "必须拒绝空值；验收标准：有效邮箱可以通过；错误时返回明确错误信息。"
                )
            )
        )

        self.assertEqual(result.spec.title, "实现一个用户注册校验器")
        self.assertEqual(result.spec.inputs, ["输入：用户名、邮箱和密码；"])
        self.assertEqual(result.spec.outputs[0], "输出：校验结果和提示信息；")
        self.assertIn("必须拒绝空值；", result.spec.constraints)
        self.assertIn("验收标准：有效邮箱可以通过；", result.spec.constraints)
        self.assertIn("必须拒绝空值；", result.spec.edge_cases)
        self.assertIn("错误时返回明确错误信息。", result.spec.failure_conditions)

    def test_spec_service_exposes_chinese_task_requirements(self) -> None:
        task = SpecService().specify(
            TaskSpecifyRequest(
                natural_language_goal=(
                    "写一个折扣计算函数，输入是商品价格和会员等级，输出最终价格，"
                    "必须拒绝空值，验收标准是会员折扣计算正确，错误时返回可读提示。"
                )
            )
        )

        self.assertTrue(any(item.startswith("输入是") for item in task.inputs))
        self.assertTrue(any(item.startswith("输出最终价格") for item in task.outputs))
        self.assertTrue(any(item.startswith("必须拒绝空值") for item in task.constraints))
        self.assertTrue(any(item.startswith("验收标准") for item in task.constraints))
        self.assertTrue(any(item.startswith("必须拒绝空值") for item in task.edge_cases))
        self.assertTrue(any(item.startswith("错误时") for item in task.failure_conditions))


# ---------------------------------------------------------------------------
# Restored from test_restore_list.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


class FakeModel:
    def __init__(self, key: str, value: str = ""):
        self.key = key
        self.value = value


def test_restore_list_filters_unknown_fields():
    """Unknown fields should be silently ignored during deserialization."""
    payload = [
        {"key": "a", "value": "1", "relationship_stage": "intake"},
        {"key": "b", "unknown_field": "x"},
    ]
    result = StructuredMemoryService._restore_list(payload, FakeModel)
    assert len(result) == 2
    assert result[0].key == "a"
    assert result[0].value == "1"
    assert result[1].key == "b"
    assert result[1].value == ""


def test_restore_list_skips_empty_dicts():
    """Empty dicts should be skipped to avoid Pydantic validation failures."""
    payload = [
        {"key": "a", "value": "1"},
        {},
        {"key": "b"},
    ]
    result = StructuredMemoryService._restore_list(payload, FakeModel)
    assert len(result) == 2
    assert result[0].key == "a"
    assert result[1].key == "b"


def test_restore_list_dataclass_with_unknown_field():
    """Dataclass models should ignore unknown fields gracefully."""
    payload = [
        {
            "key": "test",
            "scenario": "s1",
            "relationship_stage": "active",  # field no longer exists
            "focus_area": "fa",
        }
    ]
    result = StructuredMemoryService._restore_list(payload, TeachingStrategyEffectivenessRecord)
    assert len(result) == 1
    assert result[0].key == "test"
    assert result[0].scenario == "s1"
    assert result[0].focus_area == "fa"
