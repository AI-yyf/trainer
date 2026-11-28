"""(c) Evidence honesty: only the host verification path yields verified evidence.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real objects;
nothing here asserts on source text or code shape):
  * server/tests/test_evidence_queue.py
  * server/tests/test_evidence_unscoped.py
  * server/tests/test_evidence_auto_enqueue.py
  * server/tests/test_evidence_plan_persist.py
  * server/tests/test_memory_evidence_view.py
  * server/tests/test_five_dimension_evidence.py
  * server/tests/test_attestation_idempotency_endpoint.py
  * server/tests/test_evidence_controls.py

Guarantees covered:
  * client- or learner-submitted outcomes stay pending / unverified until the server verifies;
  * unverified pass evidence cannot advance a plan; wrong-stage, frozen-plan and fail outcomes do not update;
  * untrusted outcome labels, unverified streaks and client repetition counts are not mastery;
  * missing assistance / recall delay facts never advance a dimension; host attestation is idempotent per evidence id.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.runtime import TrainerRuntime
from app.core.models import (
    CapabilityFlags,
    EvidenceAdoptResponse,
    EvidenceItem,
    EvidenceQueueSnapshot,
    LearningPlan,
    PlanStage,
    ProviderConfig,
    TrainingCardCandidateSnapshot,
    TrainingCardStatus,
    TrainingCardType,
)
from app.core.settings import AppSettings
from app.db.repository import TrainerRepository
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.memory.evidence_view import build_evidence_queue_snapshot
from app.memory.service import MemoryService
from app.memory.transfer_skills import should_promote_transferable_skill
from app.memory.workspace_recovery import (
    PLAN_RUNTIME_KEY,
    scope_evidence_queue_to_runtime_step,
)
from app.pedagogy.evidence_controls import (
    LearningEvidenceSignals,
    analyze_learning_evidence,
    apply_controls_to_card,
    pedagogy_evidence_confidence,
    resolve_pedagogy_controls,
    review_after_days_for_frequency,
    routing_learner_overrides,
    streak_adapts_without_inventing_live_objects,
)
from app.planner.service import PlannerService
from app.training.attempt_store import AttemptStore
from app.training.skill_projection import project_skills
from tests.client_fixtures import build_client

# ---------------------------------------------------------------------------
# Restored from test_evidence_queue.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _cleanup_db(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


def _runtime(client: TestClient) -> TrainerRuntime:
    """The sidecar runtime behind a test client.

    Starlette declares ``TestClient.app`` as the ``ASGIApp`` callable union, so the
    ``FastAPI`` (and runtime) narrowing has to happen at runtime before ``.state``.
    """
    application = client.app
    assert isinstance(application, FastAPI), "test client must wrap the Trainer FastAPI app"
    runtime = application.state.runtime
    assert isinstance(runtime, TrainerRuntime), "FastAPI app must expose a TrainerRuntime"
    return runtime


class EvidenceEnqueueTests(unittest.TestCase):
    """Test enqueue creates evidence with id and timestamp."""

    def setUp(self) -> None:
        self.database_path = Path(f".tmp-test/evidence-enqueue-{id(self)}.db")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        _cleanup_db(self.database_path)
        self.repository = TrainerRepository(self.database_path)
        self.service = MemoryService(self.repository)

    def tearDown(self) -> None:
        _cleanup_db(self.database_path)

    def test_enqueue_assigns_id_when_missing(self) -> None:
        item = EvidenceItem(summary="test evidence", source="card_result")
        result = self.service.enqueue_evidence("ws-test", item)
        self.assertTrue(result.id.startswith("ev-"))
        self.assertTrue(len(result.id) > 3)

    def test_enqueue_assigns_timestamp_when_missing(self) -> None:
        item = EvidenceItem(summary="test evidence")
        result = self.service.enqueue_evidence("ws-test", item)
        self.assertTrue(result.timestamp)
        self.assertIn("T", result.timestamp)

    def test_enqueue_preserves_existing_id(self) -> None:
        item = EvidenceItem(id="custom-id-123", summary="test")
        result = self.service.enqueue_evidence("ws-test", item)
        self.assertEqual(result.id, "custom-id-123")

    def test_enqueue_sets_workspace_id(self) -> None:
        item = EvidenceItem(summary="test")
        result = self.service.enqueue_evidence("ws-test", item)
        self.assertEqual(result.workspace_id, "ws-test")


class EvidenceQueueSnapshotTests(unittest.TestCase):
    """Test evidence_queue returns correct snapshot."""

    def setUp(self) -> None:
        self.database_path = Path(f".tmp-test/evidence-queue-{id(self)}.db")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        _cleanup_db(self.database_path)
        self.repository = TrainerRepository(self.database_path)
        self.service = MemoryService(self.repository)

    def tearDown(self) -> None:
        _cleanup_db(self.database_path)

    def test_empty_queue_returns_empty_snapshot(self) -> None:
        snapshot = self.service.evidence_queue("ws-test")
        self.assertIsInstance(snapshot, EvidenceQueueSnapshot)
        self.assertEqual(len(snapshot.pending), 0)
        self.assertEqual(len(snapshot.adopted), 0)

    def test_queue_shows_pending_items(self) -> None:
        self.service.enqueue_evidence("ws-test", EvidenceItem(summary="first"))
        self.service.enqueue_evidence("ws-test", EvidenceItem(summary="second"))
        snapshot = self.service.evidence_queue("ws-test")
        self.assertEqual(len(snapshot.pending), 2)
        self.assertEqual(snapshot.pending[0].summary, "first")
        self.assertEqual(snapshot.pending[1].summary, "second")

    def test_queues_are_per_workspace(self) -> None:
        self.service.enqueue_evidence("ws-a", EvidenceItem(summary="a-item"))
        self.service.enqueue_evidence("ws-b", EvidenceItem(summary="b-item"))
        snapshot_a = self.service.evidence_queue("ws-a")
        snapshot_b = self.service.evidence_queue("ws-b")
        self.assertEqual(len(snapshot_a.pending), 1)
        self.assertEqual(snapshot_a.pending[0].summary, "a-item")
        self.assertEqual(len(snapshot_b.pending), 1)
        self.assertEqual(snapshot_b.pending[0].summary, "b-item")

    def test_queue_persists_across_service_rebuild(self) -> None:
        self.service.enqueue_evidence(
            "ws-test", EvidenceItem(summary="persist-me", source="learning_signal")
        )
        rebuilt = MemoryService(TrainerRepository(self.database_path))
        snapshot = rebuilt.evidence_queue("ws-test")
        self.assertEqual(len(snapshot.pending), 1)
        self.assertEqual(snapshot.pending[0].summary, "persist-me")
        self.assertEqual(snapshot.total_count, 1)


class EvidenceAdoptTests(unittest.TestCase):
    """Test adopt moves evidence from pending to adopted."""

    def setUp(self) -> None:
        self.database_path = Path(f".tmp-test/evidence-adopt-{id(self)}.db")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        _cleanup_db(self.database_path)
        self.repository = TrainerRepository(self.database_path)
        self.service = MemoryService(self.repository)

    def tearDown(self) -> None:
        _cleanup_db(self.database_path)

    def test_adopt_moves_from_pending_to_adopted(self) -> None:
        item = self.service.enqueue_evidence("ws-test", EvidenceItem(summary="adopt-me"))
        response = self.service.adopt_evidence("ws-test", item.id)
        self.assertTrue(response.evidence.adopted)
        self.assertIsNotNone(response.evidence.adopted_at)
        snapshot = self.service.evidence_queue("ws-test")
        self.assertEqual(len(snapshot.pending), 0)
        self.assertEqual(len(snapshot.adopted), 1)
        self.assertEqual(snapshot.adopted[0].id, item.id)
        self.assertEqual(snapshot.total_count, 1)

    def test_adopt_nonexistent_raises_404(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self.service.adopt_evidence("ws-test", "nonexistent-id")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_adopt_already_adopted_raises_404(self) -> None:
        item = self.service.enqueue_evidence("ws-test", EvidenceItem(summary="already"))
        self.service.adopt_evidence("ws-test", item.id)
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self.service.adopt_evidence("ws-test", item.id)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_adopt_triggers_plan_evaluation(self) -> None:
        plan = LearningPlan(
            id="plan-1",
            title="Test Plan",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Foundation",
                    goal="Learn basics",
                    outcomes=["error handling", "state management"],
                    status="active",
                ),
                PlanStage(
                    id="stage-2",
                    title="Practice",
                    goal="Practice more",
                    outcomes=["integration testing"],
                ),
            ],
            current_stage_id="stage-1",
        )
        self.repository.save_plan("ws-test", plan)

        item = self.service.enqueue_evidence(
            "ws-test",
            EvidenceItem(
                summary="Passed error handling",
                concepts=["error handling"],
                outcome="pass",
                target_plan_stage_id="stage-1",
            ),
            verified=True,
            verification_source="current_file_evaluation",
        )
        response = self.service.adopt_evidence("ws-test", item.id)
        self.assertIsInstance(response, EvidenceAdoptResponse)
        self.assertTrue(response.plan_updated)
        self.assertIn("Foundation", response.plan_change_summary)
        self.assertIn("Practice", response.plan_change_summary)


class EvidenceRejectTests(unittest.TestCase):
    """Test reject removes from pending."""

    def setUp(self) -> None:
        self.database_path = Path(f".tmp-test/evidence-reject-{id(self)}.db")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        _cleanup_db(self.database_path)
        self.repository = TrainerRepository(self.database_path)
        self.service = MemoryService(self.repository)

    def tearDown(self) -> None:
        _cleanup_db(self.database_path)

    def test_reject_removes_from_pending(self) -> None:
        item = self.service.enqueue_evidence("ws-test", EvidenceItem(summary="reject-me"))
        rejected = self.service.reject_evidence("ws-test", item.id, reason="not relevant")
        self.assertEqual(rejected.id, item.id)
        self.assertFalse(rejected.adopted)
        self.assertIsNotNone(rejected.rejected_at)
        self.assertEqual(rejected.rejection_reason, "not relevant")
        snapshot = self.service.evidence_queue("ws-test")
        self.assertEqual(len(snapshot.pending), 0)
        self.assertEqual(len(snapshot.adopted), 0)
        self.assertEqual(len(snapshot.rejected), 1)
        self.assertEqual(snapshot.total_count, 1)

    def test_reject_nonexistent_raises_404(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self.service.reject_evidence("ws-test", "nonexistent-id")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_reject_does_not_affect_other_items(self) -> None:
        item1 = self.service.enqueue_evidence("ws-test", EvidenceItem(summary="keep"))
        item2 = self.service.enqueue_evidence("ws-test", EvidenceItem(summary="remove"))
        self.service.reject_evidence("ws-test", item2.id)
        snapshot = self.service.evidence_queue("ws-test")
        self.assertEqual(len(snapshot.pending), 1)
        self.assertEqual(snapshot.pending[0].id, item1.id)


class PlannerEvidenceEvaluationTests(unittest.TestCase):
    """Test planner evaluate_evidence_for_plan."""

    def setUp(self) -> None:
        self.planner = PlannerService()
        self.plan = LearningPlan(
            id="plan-1",
            title="Test Plan",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Foundation",
                    goal="Learn basics",
                    outcomes=["error handling", "state management"],
                    status="active",
                ),
                PlanStage(
                    id="stage-2",
                    title="Practice",
                    goal="Practice more",
                    outcomes=["integration testing"],
                    status="pending",
                ),
            ],
            current_stage_id="stage-1",
        )

    def test_matching_pass_evidence_suggests_advance(self) -> None:
        evidence = EvidenceItem(
            id="ev-1",
            summary="Mastered error handling",
            concepts=["error handling"],
            outcome="pass",
        )
        result = self.planner.evaluate_evidence_for_plan(evidence, self.plan)
        self.assertTrue(result.plan_updated)
        self.assertIn("advance", result.plan_change_summary.lower())

    def test_matching_partial_evidence_suggests_review(self) -> None:
        evidence = EvidenceItem(
            id="ev-2",
            summary="Partial error handling",
            concepts=["error handling"],
            outcome="partial",
        )
        result = self.planner.evaluate_evidence_for_plan(evidence, self.plan)
        self.assertFalse(result.plan_updated)
        self.assertIn("review", result.plan_change_summary.lower())

    def test_non_matching_concepts_no_update(self) -> None:
        evidence = EvidenceItem(
            id="ev-3",
            summary="Unrelated concept",
            concepts=["machine learning"],
            outcome="pass",
        )
        result = self.planner.evaluate_evidence_for_plan(evidence, self.plan)
        self.assertFalse(result.plan_updated)
        self.assertIn("do not match", result.plan_change_summary.lower())

    def test_frozen_plan_no_update(self) -> None:
        frozen_plan = self.plan.model_copy(update={"frozen": True})
        evidence = EvidenceItem(
            id="ev-4",
            summary="Mastered error handling",
            concepts=["error handling"],
            outcome="pass",
        )
        result = self.planner.evaluate_evidence_for_plan(evidence, frozen_plan)
        self.assertFalse(result.plan_updated)
        self.assertIn("frozen", result.plan_change_summary.lower())

    def test_wrong_target_stage_no_update(self) -> None:
        evidence = EvidenceItem(
            id="ev-5",
            summary="Some evidence",
            concepts=["error handling"],
            outcome="pass",
            target_plan_stage_id="stage-2",
        )
        result = self.planner.evaluate_evidence_for_plan(evidence, self.plan)
        self.assertFalse(result.plan_updated)
        self.assertIn("not the active stage", result.plan_change_summary.lower())

    def test_last_stage_pass_plan_complete(self) -> None:
        last_stage_plan = LearningPlan(
            id="plan-last",
            title="Single Stage Plan",
            stages=[
                PlanStage(
                    id="stage-final",
                    title="Final",
                    goal="Complete everything",
                    outcomes=["final outcome"],
                    status="active",
                ),
            ],
            current_stage_id="stage-final",
        )
        evidence = EvidenceItem(
            id="ev-6",
            summary="Done",
            concepts=["final outcome"],
            outcome="pass",
        )
        result = self.planner.evaluate_evidence_for_plan(evidence, last_stage_plan)
        self.assertTrue(result.plan_updated)
        self.assertIn("complete", result.plan_change_summary.lower())

    def test_fail_outcome_no_update(self) -> None:
        evidence = EvidenceItem(
            id="ev-7",
            summary="Failed error handling",
            concepts=["error handling"],
            outcome="fail",
        )
        result = self.planner.evaluate_evidence_for_plan(evidence, self.plan)
        self.assertFalse(result.plan_updated)


"""§7.1 Evidence queue lifecycle tests."""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if __name__ == "__main__":
    unittest.main()

# ---------------------------------------------------------------------------
# Restored from test_evidence_unscoped.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------

CURRENT_STEP = "Review the refresh path"


def test_historical_verified_evidence_cannot_complete_revised_stage(tmp_path: Path) -> None:
    workspace_id = "ws-history-adopt"
    repository = TrainerRepository(tmp_path / "history-adopt.db")
    service = MemoryService(repository)
    plan = LearningPlan(
        id="plan-refresh",
        title="Refresh boundaries",
        current_stage_id="stage-1",
        current_step=CURRENT_STEP,
        stages=[
            PlanStage(
                id="stage-1",
                title="Boundary checks",
                goal=CURRENT_STEP,
                status="active",
                outcomes=["boundary"],
            )
        ],
    )
    repository.save_plan(workspace_id, plan)
    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(
            summary="Earlier boundary passed", outcome="pass", target_plan_stage_id="stage-1"
        ),
        verified=True,
        verification_source="current_file_evaluation",
    )
    _seed_recovered_runtime(service, workspace_id)
    plan_before = repository.get_latest_plan(workspace_id)
    assert plan_before is not None, "the plan must be stored before adoption"
    before = plan_before.model_dump()
    with pytest.raises(HTTPException) as error:
        service.adopt_evidence(workspace_id, item.id)
    assert error.value.status_code == 409
    plan_after = repository.get_latest_plan(workspace_id)
    assert plan_after is not None, "the plan must still be stored after adoption"
    assert plan_after.model_dump() == before
    rebuilt = MemoryService(TrainerRepository(tmp_path / "history-adopt.db"))
    history = rebuilt.evidence_queue(workspace_id).history
    assert len(history) == 1
    assert history[0].id == item.id
    assert not history[0].adopted


def test_independent_verified_evidence_is_recorded_without_advancing_plan(tmp_path: Path) -> None:
    workspace_id = "ws-independent-adopt"
    repository = TrainerRepository(tmp_path / "independent-adopt.db")
    service = MemoryService(repository)
    plan = LearningPlan(
        id="plan-refresh",
        title="Refresh boundaries",
        current_stage_id="stage-1",
        current_step=CURRENT_STEP,
        stages=[
            PlanStage(
                id="stage-1",
                title="Boundary checks",
                goal=CURRENT_STEP,
                status="active",
                outcomes=["boundary"],
            )
        ],
    )
    repository.save_plan(workspace_id, plan)
    _seed_recovered_runtime(service, workspace_id)
    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(summary="Independent boundary check", outcome="pass", concepts=["boundary"]),
        verified=True,
        verification_source="current_file_evaluation",
        auto_bind_current_plan=False,
    )
    plan_before = repository.get_latest_plan(workspace_id)
    assert plan_before is not None, "the plan must be stored before adoption"
    before = plan_before.model_dump()
    service.update_workspace_state(
        workspace_id,
        selected_card_id="current-review",
        selected_card_title="Recall: Python",
        latest_training_next_hop={"title": "Recall: Python"},
    )
    workspace_before = service.snapshot(workspace_id).workspace.copy()
    response = service.adopt_evidence(workspace_id, item.id)
    assert response.evidence.adopted
    assert not response.plan_updated
    plan_after = repository.get_latest_plan(workspace_id)
    assert plan_after is not None, "the plan must still be stored after adoption"
    assert plan_after.model_dump() == before
    assert service.snapshot(workspace_id).workspace == workspace_before
    assert (
        service.recover_workspace_facts(workspace_id)["latest_plan_runtime"]["current_step"]
        == CURRENT_STEP
    )


def test_fresh_stage_evidence_keeps_its_step_binding_after_plan_revision(tmp_path: Path) -> None:
    workspace_id = "ws-fresh-stage-binding"
    repository = TrainerRepository(tmp_path / "fresh-binding.db")
    service = MemoryService(repository)
    plan = LearningPlan(
        id="plan-refresh",
        title="Refresh boundaries",
        current_stage_id="stage-1",
        current_step=CURRENT_STEP,
        stages=[
            PlanStage(
                id="stage-1",
                title="Boundary checks",
                goal=CURRENT_STEP,
                status="active",
                outcomes=["boundary"],
            )
        ],
    )
    repository.save_plan(workspace_id, plan)
    _seed_recovered_runtime(service, workspace_id)
    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(
            summary="Current stage check",
            outcome="pass",
            target_plan_stage_id="stage-1",
            target_plan_step="Client-supplied step must be ignored",
        ),
        verified=True,
        verification_source="current_file_evaluation",
    )
    assert item.target_plan_step == CURRENT_STEP
    assert [entry.id for entry in service.evidence_queue(workspace_id).pending] == [item.id]
    revised_step = "Add the missing hash boundary"
    revised = plan.model_copy(update={"current_step": revised_step})
    repository.save_plan(workspace_id, revised)
    service.bind_explicit_generated_plan(workspace_id, revised)
    rebuilt = MemoryService(TrainerRepository(tmp_path / "fresh-binding.db"))
    assert [entry.id for entry in rebuilt.evidence_queue(workspace_id).history] == [item.id]
    with pytest.raises(HTTPException) as error:
        rebuilt.adopt_evidence(workspace_id, item.id)
    assert error.value.status_code == 409
    rebound_plan = repository.get_latest_plan(workspace_id)
    assert rebound_plan is not None, "the explicitly bound plan must be stored"
    assert rebound_plan.current_step == revised_step


def _seed_recovered_runtime(service: MemoryService, workspace_id: str) -> None:
    service.update_workspace_state(
        workspace_id,
        **{
            PLAN_RUNTIME_KEY: {
                "workspace_id": workspace_id,
                "plan_id": "plan-refresh",
                "current_step": CURRENT_STEP,
                "why_now": "Recovered runtime is current for this workspace.",
                "resume_state": "in_progress",
            }
        },
    )


def test_enqueue_autobinds_to_recovered_current_step(tmp_path: Path) -> None:
    workspace_id = "ws-evidence-autobind"
    service = MemoryService(TrainerRepository(tmp_path / "autobind.db"))
    _seed_recovered_runtime(service, workspace_id)

    item = service.enqueue_evidence(
        workspace_id, EvidenceItem(id="ev-autobind", summary="Fresh verify note", outcome="pass")
    )

    assert item.target_plan_stage_id == CURRENT_STEP
    snapshot = service.evidence_queue(workspace_id)
    assert [pending.id for pending in snapshot.pending] == [item.id]
    assert snapshot.unscoped == []


def test_unbound_pending_item_surfaces_unscoped_after_recovery(tmp_path: Path) -> None:
    workspace_id = "ws-evidence-unscoped"
    service = MemoryService(TrainerRepository(tmp_path / "unscoped.db"))
    # Enqueue before the runtime exists, so no auto-bind can stamp a target.
    item = service.enqueue_evidence(
        workspace_id, EvidenceItem(id="ev-loose", summary="Pre-recovery note")
    )
    assert item.target_plan_stage_id == ""

    _seed_recovered_runtime(service, workspace_id)
    snapshot = service.evidence_queue(workspace_id)

    assert [unscoped.id for unscoped in snapshot.unscoped] == [item.id]
    assert snapshot.pending == []
    assert all(history.id != item.id for history in snapshot.history)


def test_item_bound_to_other_step_stays_history(tmp_path: Path) -> None:
    workspace_id = "ws-evidence-other-step"
    service = MemoryService(TrainerRepository(tmp_path / "other-step.db"))
    _seed_recovered_runtime(service, workspace_id)

    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(
            id="ev-earlier", summary="Earlier stage note", target_plan_stage_id="stage-earlier"
        ),
    )

    snapshot = service.evidence_queue(workspace_id)
    assert snapshot.pending == []
    assert snapshot.unscoped == []
    assert [history.id for history in snapshot.history] == [item.id]


def test_no_recovery_keeps_pass_through_without_unscoped(tmp_path: Path) -> None:
    workspace_id = "ws-evidence-no-recovery"
    service = MemoryService(TrainerRepository(tmp_path / "no-recovery.db"))

    item = service.enqueue_evidence(workspace_id, EvidenceItem(id="ev-plain", summary="Plain note"))

    snapshot = service.evidence_queue(workspace_id)
    assert [pending.id for pending in snapshot.pending] == [item.id]
    assert snapshot.unscoped == []
    assert snapshot.history == []


def test_explicit_target_still_wins_over_autobind(tmp_path: Path) -> None:
    workspace_id = "ws-evidence-explicit-target"
    service = MemoryService(TrainerRepository(tmp_path / "explicit-target.db"))
    _seed_recovered_runtime(service, workspace_id)

    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(
            id="ev-explicit", summary="Bound at enqueue", target_plan_stage_id="stage-next"
        ),
    )

    assert item.target_plan_stage_id == "stage-next"


def test_scope_helper_partitions_pending_unscoped_and_history() -> None:
    bound = EvidenceItem(id="ev-bound", summary="bound", concepts=[CURRENT_STEP])
    other = EvidenceItem(id="ev-other", summary="other", target_plan_stage_id="stage-earlier")
    loose = EvidenceItem(id="ev-loose", summary="loose")
    deferred = EvidenceItem(
        id="ev-deferred", summary="deferred", deferred_at="2026-01-01T00:00:00Z"
    )

    scoped = scope_evidence_queue_to_runtime_step(
        pending=[bound, other, loose],
        deferred=[deferred],
        adopted=[],
        rejected=[],
        current_step=CURRENT_STEP,
        recovered=True,
    )

    assert [item.id for item in scoped["pending"]] == [bound.id]
    assert [item.id for item in scoped["unscoped"]] == [loose.id]
    assert {item.id for item in scoped["history"]} == {other.id, deferred.id}

    passthrough = scope_evidence_queue_to_runtime_step(
        pending=[loose],
        deferred=[],
        adopted=[],
        rejected=[],
        current_step="",
        recovered=False,
    )
    assert [item.id for item in passthrough["pending"]] == [loose.id]
    assert passthrough["unscoped"] == []


"""L4 regressions: evidence auto-bind and the unscoped queue bucket."""

# ---------------------------------------------------------------------------
# Restored from test_evidence_auto_enqueue.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _make_card(
    card_id: str = "card-evidence-001",
    status: TrainingCardStatus = "active",
    card_type: TrainingCardType = "practice",
    title: str = "Verify one focused practice result",
) -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        title=title,
        status=status,
        card_type=card_type,
        target_skill="error handling",
        focus_area="reliable Python",
        plan_links=["stage-1"],
    )


def _seed_reflected_handoff(
    service: MemoryService,
    workspace_id: str,
    card: TrainingCardCandidateSnapshot,
) -> str:
    service.upsert_card(workspace_id, card)
    workspace = service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="Current-file checks passed.",
        next_step="Return to Coach.",
        focus_area=card.focus_area,
        evidence_source="ide_current_file",
        verified_by_evaluator=True,
    )
    handoff_id = workspace["latest_training_handoff"]["handoff_id"]
    service.record_training_handoff_reflection(
        workspace_id=workspace_id,
        card_id=card.card_id,
        handoff_id=handoff_id,
        reflection="The current-file checks proved the focused error-handling branch works.",
    )
    return handoff_id


class TrainingEvidenceProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        database_path = Path(f".tmp-test/evidence-provenance-{id(self)}.db")
        database_path.parent.mkdir(parents=True, exist_ok=True)
        database_path.unlink(missing_ok=True)
        self.repository = TrainerRepository(database_path)
        self.service = MemoryService(self.repository)
        self.workspace_id = "ws-evidence-provenance"

    def test_status_transition_does_not_create_mastery_evidence(self) -> None:
        card = _make_card(status="active", card_type="flash")
        self.service.upsert_card(self.workspace_id, card)

        self.service.transition_card_status(self.workspace_id, card.card_id, "answered")
        self.service.transition_card_status(self.workspace_id, card.card_id, "reviewed")

        assert self.service.evidence_queue(self.workspace_id).pending == []

    def test_learner_report_stays_pending_until_server_verification(self) -> None:
        card = _make_card(status="active")
        self.service.upsert_card(self.workspace_id, card)

        workspace = self.service.record_training_practice_evaluation_result(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            passed=True,
            summary="I completed the exercise.",
            next_step="Verify the current file.",
            focus_area="reliable Python",
            evidence_source="learner_return",
        )

        stored = self.service.get_card(self.workspace_id, card.card_id)
        assert stored is not None
        assert stored.status == "active"
        assert workspace["latest_training_handoff"]["return_mode"] == "verification_required"
        assert workspace["latest_learning_verified_result"] == ""
        assert self.service.evidence_queue(self.workspace_id).pending == []

    def test_server_verified_evaluation_requires_reflect_and_return_before_evidence_credit(
        self,
    ) -> None:
        card = _make_card(status="active")
        self.service.upsert_card(self.workspace_id, card)

        workspace = self.service.record_training_practice_evaluation_result(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            passed=True,
            summary="Current-file checks passed.",
            next_step="Return to Coach.",
            focus_area="reliable Python",
            evidence_source="ide_current_file",
            verified_by_evaluator=True,
        )

        stored = self.service.get_card(self.workspace_id, card.card_id)
        assert stored is not None
        assert stored.status == "active"
        assert workspace["latest_training_handoff"]["learning_phase"] == "verify"
        assert workspace["latest_training_handoff"]["return_mode"] == "reflection_required"
        assert workspace["latest_learning_verified_result"] == ""
        assert self.service.evidence_queue(self.workspace_id).pending == []

        handoff_id = workspace["latest_training_handoff"]["handoff_id"]
        reflected = self.service.record_training_handoff_reflection(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            handoff_id=handoff_id,
            reflection="The current-file checks proved the focused error-handling branch works.",
        )

        assert reflected["latest_training_handoff"]["learning_phase"] == "reflect"
        assert reflected["latest_training_handoff"]["return_mode"] == "return_required"
        assert self.service.get_card(self.workspace_id, card.card_id).status == "active"
        assert self.service.evidence_queue(self.workspace_id).pending == []

        returned = self.service.return_training_handoff(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            handoff_id=handoff_id,
        )

        stored = self.service.get_card(self.workspace_id, card.card_id)
        queue = self.service.evidence_queue(self.workspace_id)
        assert stored is not None
        assert stored.status == "implemented"
        assert returned["latest_training_handoff"]["learning_phase"] == "return"
        assert returned["latest_training_handoff"]["return_mode"] == "result"
        assert returned["latest_learning_verified_result"] == "Current-file checks passed."
        assert len(queue.pending) == 1
        evidence = queue.pending[0]
        assert evidence.verified is True
        assert evidence.verification_source == "ide_current_file"
        assert evidence.source == "training_handoff_return"
        assert evidence.source_card_id == card.card_id
        assert evidence.target_plan_stage_id == "stage-1"

        reviewed = self.service.transition_card_status(
            self.workspace_id,
            card.card_id,
            "reviewed",
        )
        assert reviewed.card.status == "reviewed"

    def test_completed_return_evidence_is_on_snapshot_and_persist(self) -> None:
        card = _make_card()
        handoff_id = _seed_reflected_handoff(self.service, self.workspace_id, card)

        returned = self.service.return_training_handoff(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            handoff_id=handoff_id,
        )
        snapshot = self.service.snapshot(self.workspace_id)
        assert snapshot.evidence_queue is not None
        live = [
            item
            for item in (*snapshot.evidence_queue.pending, *snapshot.evidence_queue.history)
            if item.source == "training_handoff_return" and item.source_card_id == card.card_id
        ]
        assert len(live) == 1
        assert live[0].verified is True
        assert live[0].verification_source == "ide_current_file"
        assert returned["latest_training_handoff"]["return_mode"] == "result"
        assert returned["latest_learning_outcome"] == "tests_passed"

        restarted = MemoryService(TrainerRepository(self.repository.database_path))
        persisted = restarted.snapshot(self.workspace_id)
        assert persisted.evidence_queue is not None
        persisted_live = [
            item
            for item in (*persisted.evidence_queue.pending, *persisted.evidence_queue.history)
            if item.source == "training_handoff_return" and item.source_card_id == card.card_id
        ]
        assert len(persisted_live) == 1
        assert persisted_live[0].verified is True
        assert restarted.get_card(self.workspace_id, card.card_id).status == "implemented"

    def test_failed_return_evidence_write_stays_unverified(self) -> None:
        card = _make_card(card_id="card-evidence-unverified")
        handoff_id = _seed_reflected_handoff(self.service, self.workspace_id, card)

        with patch.object(self.service, "enqueue_evidence", side_effect=OSError("disk full")):
            failed = self.service.return_training_handoff(
                workspace_id=self.workspace_id,
                card_id=card.card_id,
                handoff_id=handoff_id,
            )

        stored = self.service.get_card(self.workspace_id, card.card_id)
        queue = self.service.evidence_queue(self.workspace_id)
        handoff = failed["latest_training_handoff"]
        next_hop = failed["latest_training_next_hop"]
        assert stored is not None
        assert stored.status == "active"
        assert queue.pending == []
        assert all(item.source != "training_handoff_return" for item in queue.history)
        assert handoff["return_mode"] != "result"
        assert handoff["return_mode"] == "return_required"
        assert handoff["handoff_status"] == "unverified"
        assert handoff["learning_phase"] == "reflect"
        assert next_hop["status"] == "evidence_unverified"
        assert failed["latest_learning_outcome"] == "unverified"
        assert failed["latest_learning_verified_result"] == ""
        assert failed.get("latest_learning_blocker") in {None, ""}
        assert (
            next_hop["why_now"]
            == "Return evidence was not persisted, so this card is not credited."
        )
        assert "persist" in (handoff.get("fallback_action") or "").lower()

        retried = self.service.return_training_handoff(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            handoff_id=handoff_id,
        )
        retried_queue = self.service.evidence_queue(self.workspace_id)
        assert self.service.get_card(self.workspace_id, card.card_id).status == "implemented"
        assert retried["latest_training_handoff"]["return_mode"] == "result"
        assert retried["latest_learning_outcome"] == "tests_passed"
        assert len(retried_queue.pending) == 1
        assert retried_queue.pending[0].source == "training_handoff_return"
        assert retried_queue.pending[0].verified is True

    def test_one_project_card_success_does_not_become_global_mastery(self) -> None:
        card = _make_card(card_id="card-evidence-project-only")
        handoff_id = _seed_reflected_handoff(self.service, self.workspace_id, card)
        returned = self.service.return_training_handoff(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            handoff_id=handoff_id,
        )

        transfer = returned.get("latest_transfer_state") or {}
        assert transfer.get("state") != "transferable"
        assert (
            self.service._should_promote_verified_outcome_to_global(
                concepts=["error handling", "reliable Python"],
                workspace_id=self.workspace_id,
            )
            is False
        )
        global_memory = self.service.global_memory()
        assert "error handling" not in global_memory.capability_profile
        assert "error handling".casefold() not in global_memory.capability_profile
        assert all(
            "error handling" not in record.concepts for record in global_memory.growth_history
        )

    def test_return_after_recovered_without_plan_does_not_invent_or_paint_leftover(self) -> None:
        leftover_title = "Keep the current stage"
        leftover_step = "Keep one auth check"
        leftover_plan = LearningPlan(
            id="plan-formal-old",
            title=leftover_title,
            current_step=leftover_step,
            why_now="Keep the leftover why",
            next_after_current="Then review the leftover path",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Auth",
                    goal="Keep one check",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        self.repository.save_plan(self.workspace_id, leftover_plan)
        self.service.persist_plan_runtime_recovery(
            self.workspace_id,
            plan_runtime={
                "current_step": "Add a token expiry test",
                "why_now": "Expired tokens still leak.",
                "resume_state": "in_progress",
                "plan_id": "",
            },
            request_id="recovered-without-plan-return",
        )
        formal_plan = self.repository.get_latest_plan(self.workspace_id)
        assert formal_plan is not None, "the formal plan must still be stored"
        assert formal_plan.id == "plan-formal-old"

        card = _make_card(card_id="card-evidence-leftover", title=leftover_title)
        handoff_id = _seed_reflected_handoff(self.service, self.workspace_id, card)
        returned = self.service.return_training_handoff(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            handoff_id=handoff_id,
        )

        stored_plan = self.repository.get_latest_plan(self.workspace_id)
        assert stored_plan is not None
        assert stored_plan.id == "plan-formal-old"
        assert stored_plan.title == leftover_title
        assert returned["selected_card_title"] != leftover_title
        assert leftover_title not in str(returned.get("selected_card_title") or "")
        assert leftover_step not in str(returned.get("selected_card_title") or "")
        snapshot = self.service.snapshot(self.workspace_id)
        assert snapshot.evidence_queue is not None
        pending = [
            item
            for item in snapshot.evidence_queue.pending
            if item.source == "training_handoff_return" and item.source_card_id == card.card_id
        ]
        assert len(pending) == 1
        assert pending[0].verified is True
        assert "Add a token expiry test" in pending[0].concepts
        assert leftover_title not in pending[0].concepts

        still_workspace = "ws-evidence-still-on-plan"
        still_plan = leftover_plan.model_copy(update={"id": "plan-formal-still"})
        self.repository.save_plan(still_workspace, still_plan)
        self.service.persist_plan_runtime_recovery(
            still_workspace,
            plan_runtime={
                "current_step": leftover_step,
                "plan_id": still_plan.id,
                "resume_state": "in_progress",
            },
            request_id="still-on-plan-return",
        )
        still_card = _make_card(card_id="card-evidence-still", title=leftover_title)
        still_handoff = _seed_reflected_handoff(self.service, still_workspace, still_card)
        still_returned = self.service.return_training_handoff(
            workspace_id=still_workspace,
            card_id=still_card.card_id,
            handoff_id=still_handoff,
        )
        still_formal_plan = self.repository.get_latest_plan(still_workspace)
        assert still_formal_plan is not None, "the formal plan must still be stored"
        assert still_formal_plan.id == "plan-formal-still"
        assert still_returned["selected_card_title"] == leftover_title
        still_queue = self.service.evidence_queue(still_workspace)
        assert any(
            item.source == "training_handoff_return" and item.source_card_id == still_card.card_id
            for item in (*still_queue.pending, *still_queue.history)
        )

    def test_return_binds_pending_evidence_then_adopt_advances_training_next_without_painting_b(
        self,
    ) -> None:
        workspace_a = "workspace-a-growth-loop"
        workspace_b = "workspace-b-growth-loop"
        next_step = "Add a token expiry test"
        card = TrainingCardCandidateSnapshot(
            card_id="card-growth-loop-a",
            title="Keep one auth check",
            status="active",
            card_type="practice",
            target_skill="auth expiry",
            focus_area="session tokens",
            plan_links=["stage-auth"],
            next_after_completion=next_step,
        )
        handoff_id = _seed_reflected_handoff(self.service, workspace_a, card)

        returned = self.service.return_training_handoff(
            workspace_id=workspace_a,
            card_id=card.card_id,
            handoff_id=handoff_id,
        )
        queue = self.service.evidence_queue(workspace_a)
        runtime = self.service.recover_workspace_facts(workspace_a)["latest_plan_runtime"]
        assert len(queue.pending) == 1
        evidence = queue.pending[0]
        assert evidence.source == "training_handoff_return"
        assert evidence.verified is True
        assert evidence.source_card_id == card.card_id
        assert runtime["resume_state"] == "waiting"
        assert runtime["current_step"] == "Keep one auth check"
        assert runtime["next_after_current"] == next_step
        assert runtime["evidence_binding"] == evidence.id
        assert self.service.repository.get_latest_plan(workspace_a) is None
        assert self.service.global_memory().capability_profile == {}
        transfer = returned.get("latest_transfer_state") or {}
        assert transfer.get("state") != "transferable"

        adopted = self.service.adopt_evidence(workspace_a, evidence.id)
        assert adopted.evidence.adopted is True
        assert adopted.plan_updated is False
        advanced = self.service.recover_workspace_facts(workspace_a)["latest_plan_runtime"]
        assert advanced["resume_state"] == "in_progress"
        assert advanced["current_step"] == next_step
        assert advanced.get("next_after_current") in {None, ""}
        assert advanced.get("evidence_binding") in {None, ""}
        assert self.service.repository.get_latest_plan(workspace_a) is None
        next_hop = (
            self.service.snapshot(workspace_a).workspace.get("latest_training_next_hop") or {}
        )
        assert next_hop.get("title") == next_step
        assert next_hop.get("card_title") == next_step
        assert self.service.global_memory().capability_profile == {}
        transfer_a = adopted.evidence and (
            self.service.snapshot(workspace_a).workspace.get("latest_transfer_state") or {}
        )
        assert transfer_a.get("state") == "awaiting_second_scene"
        assert transfer_a.get("state") != "transferable"
        assert transfer_a.get("concept") == "auth expiry"
        assert "workspace-a-growth-loop" in (transfer_a.get("workspace_ids") or [])

        foreign = self.service.snapshot(workspace_b)
        assert not (foreign.evidence_queue.pending if foreign.evidence_queue else [])
        assert (foreign.workspace.get("latest_plan_runtime") or {}).get("current_step") not in {
            "Keep one auth check",
            next_step,
        }
        assert (foreign.workspace.get("latest_training_next_hop") or {}).get("title") != next_step
        assert (foreign.workspace.get("selected_card_title") or "") != "Keep one auth check"
        assert (foreign.workspace.get("latest_transfer_state") or {}).get("state") != "transferable"
        assert all("auth check" not in asset.title.lower() for asset in foreign.teaching_assets)
        assert self.service.global_memory().capability_profile == {}


"""Regression coverage for verified training evidence provenance."""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if __name__ == "__main__":
    unittest.main()

# ---------------------------------------------------------------------------
# Restored from test_evidence_plan_persist.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


class PlanPersistenceAfterEvidenceAdoptTests(unittest.TestCase):
    """Test that adopt_evidence actually persists plan changes to the repository."""

    def setUp(self) -> None:
        self.database_path = Path(f".tmp-test/evidence-plan-persist-{id(self)}.db")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        _cleanup_db(self.database_path)
        self.repository = TrainerRepository(self.database_path)
        self.service = MemoryService(self.repository)

    def tearDown(self) -> None:
        _cleanup_db(self.database_path)

    # ---------------------------------------------------------------
    # Test 1: Pass outcome advances stage and persists
    # ---------------------------------------------------------------
    def test_pass_outcome_advances_stage_and_persists(self) -> None:
        """Pass evidence on active stage advances current_stage_id and persists."""
        plan = LearningPlan(
            id="plan-advance",
            title="Advance Plan",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Foundation",
                    goal="Learn basics",
                    outcomes=["error handling", "state management"],
                    status="active",
                ),
                PlanStage(
                    id="stage-2",
                    title="Practice",
                    goal="Practice more",
                    outcomes=["integration testing"],
                    status="pending",
                ),
                PlanStage(
                    id="stage-3",
                    title="Mastery",
                    goal="Master concepts",
                    outcomes=["final project"],
                    status="pending",
                ),
            ],
            current_stage_id="stage-1",
        )
        self.repository.save_plan("ws-test", plan)

        item = self.service.enqueue_evidence(
            "ws-test",
            EvidenceItem(
                summary="Passed error handling",
                concepts=["error handling"],
                outcome="pass",
                target_plan_stage_id="stage-1",
            ),
            verified=True,
            verification_source="current_file_evaluation",
        )
        response = self.service.adopt_evidence("ws-test", item.id)
        self.assertIsInstance(response, EvidenceAdoptResponse)
        self.assertTrue(response.plan_updated)

        # Reload from repository — the plan must be persisted
        saved_plan = self.repository.get_latest_plan("ws-test")
        assert saved_plan is not None, "adopting evidence must leave a stored plan"
        self.assertIsNotNone(saved_plan)
        self.assertEqual(saved_plan.current_stage_id, "stage-2")

        # Check stage statuses
        stage_map = {s.id: s for s in saved_plan.stages}
        self.assertEqual(stage_map["stage-1"].status, "completed")
        self.assertEqual(stage_map["stage-2"].status, "active")
        self.assertEqual(stage_map["stage-3"].status, "pending")

    def test_unverified_pass_evidence_cannot_advance_a_plan(self) -> None:
        plan = LearningPlan(
            id="plan-unverified",
            title="Unverified Plan",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Foundation",
                    goal="Learn basics",
                    outcomes=["error handling"],
                    status="active",
                ),
                PlanStage(
                    id="stage-2",
                    title="Practice",
                    goal="Practice more",
                    outcomes=["integration testing"],
                    status="pending",
                ),
            ],
            current_stage_id="stage-1",
        )
        self.repository.save_plan("ws-test", plan)

        item = self.service.enqueue_evidence(
            "ws-test",
            EvidenceItem(
                summary="Learner reports passing error handling",
                concepts=["error handling"],
                outcome="pass",
                verified=True,
                target_plan_stage_id="stage-1",
            ),
        )
        response = self.service.adopt_evidence("ws-test", item.id)

        self.assertFalse(item.verified)
        self.assertFalse(response.plan_updated)
        saved_plan = self.repository.get_latest_plan("ws-test")
        assert saved_plan is not None, "adopting evidence must leave a stored plan"
        self.assertEqual(saved_plan.current_stage_id, "stage-1")

    # ---------------------------------------------------------------
    # Test 2: Frozen plan → no stage change
    # ---------------------------------------------------------------
    def test_frozen_plan_no_stage_change(self) -> None:
        """Frozen plan stays unchanged after evidence adoption."""
        plan = LearningPlan(
            id="plan-frozen",
            title="Frozen Plan",
            frozen=True,
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Foundation",
                    goal="Learn basics",
                    outcomes=["error handling"],
                    status="active",
                ),
                PlanStage(
                    id="stage-2",
                    title="Practice",
                    goal="Practice more",
                    outcomes=["integration testing"],
                    status="pending",
                ),
            ],
            current_stage_id="stage-1",
        )
        self.repository.save_plan("ws-test", plan)

        item = self.service.enqueue_evidence(
            "ws-test",
            EvidenceItem(
                summary="Passed error handling",
                concepts=["error handling"],
                outcome="pass",
                target_plan_stage_id="stage-1",
            ),
            verified=True,
            verification_source="current_file_evaluation",
        )
        response = self.service.adopt_evidence("ws-test", item.id)
        self.assertFalse(response.plan_updated)

        saved_plan = self.repository.get_latest_plan("ws-test")
        assert saved_plan is not None, "adopting evidence must leave a stored plan"
        self.assertEqual(saved_plan.current_stage_id, "stage-1")

        stage_map = {s.id: s for s in saved_plan.stages}
        self.assertEqual(stage_map["stage-1"].status, "active")
        self.assertEqual(stage_map["stage-2"].status, "pending")

    # ---------------------------------------------------------------
    # Test 3: Fail outcome → no stage change
    # ---------------------------------------------------------------
    def test_fail_outcome_no_stage_change(self) -> None:
        """Fail evidence outcome does not advance stages."""
        plan = LearningPlan(
            id="plan-fail",
            title="Fail Plan",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Foundation",
                    goal="Learn basics",
                    outcomes=["error handling"],
                    status="active",
                ),
                PlanStage(
                    id="stage-2",
                    title="Practice",
                    goal="Practice more",
                    outcomes=["integration testing"],
                    status="pending",
                ),
            ],
            current_stage_id="stage-1",
        )
        self.repository.save_plan("ws-test", plan)

        item = self.service.enqueue_evidence(
            "ws-test",
            EvidenceItem(
                summary="Failed error handling",
                concepts=["error handling"],
                outcome="fail",
                target_plan_stage_id="stage-1",
            ),
        )
        response = self.service.adopt_evidence("ws-test", item.id)
        self.assertFalse(response.plan_updated)

        saved_plan = self.repository.get_latest_plan("ws-test")
        assert saved_plan is not None, "adopting evidence must leave a stored plan"
        self.assertEqual(saved_plan.current_stage_id, "stage-1")
        self.assertEqual(
            {s.id: s.status for s in saved_plan.stages},
            {"stage-1": "active", "stage-2": "pending"},
        )

    # ---------------------------------------------------------------
    # Test 4: Partial outcome → no stage change
    # ---------------------------------------------------------------
    def test_partial_outcome_no_stage_change(self) -> None:
        """Partial evidence outcome does not advance stages."""
        plan = LearningPlan(
            id="plan-partial",
            title="Partial Plan",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Foundation",
                    goal="Learn basics",
                    outcomes=["error handling"],
                    status="active",
                ),
                PlanStage(
                    id="stage-2",
                    title="Practice",
                    goal="Practice more",
                    outcomes=["integration testing"],
                    status="pending",
                ),
            ],
            current_stage_id="stage-1",
        )
        self.repository.save_plan("ws-test", plan)

        item = self.service.enqueue_evidence(
            "ws-test",
            EvidenceItem(
                summary="Partial error handling",
                concepts=["error handling"],
                outcome="partial",
                target_plan_stage_id="stage-1",
            ),
        )
        response = self.service.adopt_evidence("ws-test", item.id)
        self.assertFalse(response.plan_updated)

        saved_plan = self.repository.get_latest_plan("ws-test")
        assert saved_plan is not None, "adopting evidence must leave a stored plan"
        self.assertEqual(saved_plan.current_stage_id, "stage-1")
        self.assertEqual(
            {s.id: s.status for s in saved_plan.stages},
            {"stage-1": "active", "stage-2": "pending"},
        )


"""§7.2 Evidence adoption plan persistence tests."""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if __name__ == "__main__":
    unittest.main()

# ---------------------------------------------------------------------------
# Restored from test_memory_evidence_view.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _item(item_id: str, **updates: object) -> EvidenceItem:
    values: dict[str, Any] = {
        "id": item_id,
        "workspace_id": "workspace-a",
        "summary": f"evidence {item_id}",
        "source": "training_handoff_return",
    }
    values.update(updates)
    return EvidenceItem(**values)


def test_queue_projection_classifies_lifecycle_without_memory_service() -> None:
    items = [
        _item("pending"),
        _item("deferred", deferred_at="2026-11-08T00:00:00+00:00"),
        _item("adopted", adopted=True),
        _item("rejected", rejected_at="2026-11-08T00:00:00+00:00"),
    ]
    snapshot = build_evidence_queue_snapshot(
        items=items,
        workspace_id="workspace-a",
        recovered=None,
        recovered_runtime=False,
    )
    assert [item.id for item in snapshot.pending] == ["pending"]
    assert [item.id for item in snapshot.deferred] == ["deferred"]
    assert [item.id for item in snapshot.adopted] == ["adopted"]
    assert [item.id for item in snapshot.rejected] == ["rejected"]
    assert snapshot.total_count == 4


def test_queue_projection_keeps_workspace_scope() -> None:
    items = [
        _item("mine"),
        _item("foreign", workspace_id="workspace-b"),
    ]
    snapshot = build_evidence_queue_snapshot(
        items=items,
        workspace_id="workspace-a",
        recovered=None,
        recovered_runtime=False,
    )
    assert [item.id for item in snapshot.pending] == ["mine"]
    assert snapshot.total_count == 2


"""Pure evidence queue projection extracted from MemoryService."""

# ---------------------------------------------------------------------------
# Restored from test_five_dimension_evidence.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------

DIMENSIONS = (
    "comprehension",
    "implementation",
    "debugging",
    "transfer",
    "delayed_recall",
)


def _ev(evidence_id: str, *, dimension: str, **overrides: object) -> dict:
    record = {
        "evidence_id": evidence_id,
        "attempt_id": f"attempt-{evidence_id}",
        "result": "passed",
        "trust_level": "controlled_check",
        "assistance_level": "independent",
        "is_current": True,
        "superseded_by_evidence_id": None,
        "dimension": dimension,
    }
    record.update(overrides)
    return record


def test_missing_assistance_never_advances_any_dimension() -> None:
    for dimension in DIMENSIONS:
        record = _ev(
            f"missing-{dimension}",
            dimension=dimension,
            evidence_kind="recall" if dimension == "delayed_recall" else "controlled_evaluation",
            recall_delay_days=2.0 if dimension == "delayed_recall" else None,
            scenario="new context" if dimension == "transfer" else None,
        )
        record.pop("assistance_level")
        projected = project_skills([record])[dimension]
        assert projected["state"] == "not_verified", dimension
        assert projected["independent_attempt_count"] == 0, dimension


@pytest.mark.parametrize("dimension", ["comprehension", "implementation", "debugging"])
def test_assisted_and_independent_stay_distinct(dimension: str) -> None:
    assisted = project_skills(
        [_ev(f"assisted-{dimension}", dimension=dimension, assistance_level="hint_level_2")]
    )[dimension]
    independent = project_skills([_ev(f"independent-{dimension}", dimension=dimension)])[dimension]

    assert assisted["state"] == "assisted"
    assert assisted["independent_attempt_count"] == 0
    assert independent["state"] == "independent"
    assert independent["independent_attempt_count"] == 1


def test_explicit_implementation_failure_does_not_claim_debugging() -> None:
    failed = _ev(
        "impl-failure",
        dimension="implementation",
        result="failed",
    )
    projected = project_skills([failed])

    assert projected["implementation"]["state"] == "needs_review"
    assert projected["debugging"]["state"] == "not_verified"
    assert projected["debugging"]["verified_count"] == 0


def test_transfer_needs_an_explicit_transfer_fact_not_an_incidental_scenario() -> None:
    implementation_with_scenario = _ev(
        "impl-scenario",
        dimension="implementation",
        scenario="new deployment context",
        environment={"runtime": "container"},
    )
    transfer = _ev(
        "transfer-context",
        dimension="transfer",
        scenario="new deployment context",
        environment={"runtime": "container"},
    )

    not_transfer = project_skills([implementation_with_scenario])
    assert not_transfer["implementation"]["state"] == "independent"
    assert not_transfer["transfer"]["state"] == "not_verified"
    assert not_transfer["transfer"]["evidence_ids"] == []

    assert project_skills([transfer])["transfer"]["state"] == "independent"


def test_transfer_repeat_verification_requires_distinct_contexts() -> None:
    same_context = [
        _ev(
            "transfer-same-1",
            dimension="transfer",
            scenario="same scenario",
            attempt_id="attempt-transfer-1",
        ),
        _ev(
            "transfer-same-2",
            dimension="transfer",
            scenario="same scenario",
            attempt_id="attempt-transfer-2",
        ),
    ]
    distinct_context = [
        _ev(
            "transfer-diff-1",
            dimension="transfer",
            scenario="scenario one",
            attempt_id="attempt-transfer-1",
        ),
        _ev(
            "transfer-diff-2",
            dimension="transfer",
            scenario="scenario two",
            attempt_id="attempt-transfer-2",
        ),
    ]

    assert project_skills(same_context)["transfer"]["state"] == "independent"
    assert project_skills(distinct_context)["transfer"]["state"] == "repeat_verified"


def test_immediate_or_missing_recall_delay_cannot_advance_delayed_recall() -> None:
    immediate = _ev(
        "immediate-recall",
        dimension="delayed_recall",
        evidence_kind="recall",
        recall_delay_days=0.25,
    )
    missing_delay = _ev(
        "missing-delay",
        dimension="delayed_recall",
        evidence_kind="recall",
    )
    wrong_kind = _ev(
        "code-check",
        dimension="delayed_recall",
        evidence_kind="controlled_evaluation",
        recall_delay_days=3.0,
    )

    for record, evidence_id in (
        (immediate, "immediate-recall"),
        (missing_delay, "missing-delay"),
        (wrong_kind, "code-check"),
    ):
        projected = project_skills([record])["delayed_recall"]
        assert projected["state"] == "not_verified", evidence_id
        assert projected["verified_count"] == 0, evidence_id
        assert projected["independent_attempt_count"] == 0, evidence_id
        row = next(item for item in projected["evidence"] if item["evidence_id"] == evidence_id)
        assert row["delayed_recall_qualified"] is False


def test_delayed_recall_ladder_and_failure() -> None:
    first = _ev(
        "recall-1",
        dimension="delayed_recall",
        evidence_kind="recall",
        recall_delay_days=2.0,
        attempt_id="attempt-recall-1",
    )
    second = _ev(
        "recall-2",
        dimension="delayed_recall",
        evidence_kind="recall",
        recall_delay_days=5.0,
        attempt_id="attempt-recall-2",
    )
    same_attempt = _ev(
        "recall-same-attempt",
        dimension="delayed_recall",
        evidence_kind="recall",
        recall_delay_days=5.0,
        attempt_id="attempt-recall-1",
    )
    failed = _ev(
        "recall-failed",
        dimension="delayed_recall",
        evidence_kind="recall",
        recall_delay_days=4.0,
        result="failed",
    )
    assisted = _ev(
        "recall-assisted",
        dimension="delayed_recall",
        evidence_kind="recall",
        recall_delay_days=4.0,
        assistance_level="hint_level_1",
    )

    assert project_skills([first])["delayed_recall"]["state"] == "independent"
    assert project_skills([first, second])["delayed_recall"]["state"] == "repeat_verified"
    assert project_skills([first, same_attempt])["delayed_recall"]["state"] == "independent"
    assert project_skills([failed])["delayed_recall"]["state"] == "needs_review"
    assert project_skills([assisted])["delayed_recall"]["state"] == "assisted"


def test_code_verification_cannot_advance_delayed_recall() -> None:
    code_pass = _ev(
        "code-pass",
        dimension="implementation",
        evidence_kind="controlled_evaluation",
    )
    projected = project_skills([code_pass])

    assert projected["implementation"]["state"] == "independent"
    assert projected["delayed_recall"]["state"] == "not_verified"
    assert projected["delayed_recall"]["verified_count"] == 0


def test_flashcard_recall_advances_only_after_a_real_delay(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-01T09:00:00Z")
    with build_client(tmp_path) as client:
        runtime = _runtime(client)
        workspace = "ws-delayed-recall"
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Recall lab"},
        )
        assert started.status_code == 200, started.text
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-recall-1",
            card_type="flash",
            status="active",
            title="Tuple immutability",
            focus_area="tuple immutability",
            answer_mode="single_choice",
            options=["mutable", "immutable"],
            correct_option_index=1,
        )
        runtime.memory_service.upsert_card(workspace, card)

        first = client.post(
            "/training/flashcard/answer",
            json={
                "workspace_id": workspace,
                "card_id": card.card_id,
                "selected_option_index": 1,
            },
        )
        assert first.status_code == 200, first.text
        first_evidence = first.json()["recall_evidence"]
        assert first_evidence is not None
        assert first_evidence["delayed_recall"] is False
        dimensions = (
            (runtime.memory_service.snapshot(workspace).workspace or {})
            .get("training_skill_projection", {})
            .get("dimensions", {})
        )
        assert dimensions["delayed_recall"]["state"] == "not_verified"
        assert dimensions["comprehension"]["state"] == "not_verified"

        monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-03T09:00:00Z")
        second = client.post(
            "/training/flashcard/answer",
            json={
                "workspace_id": workspace,
                "card_id": card.card_id,
                "selected_option_index": 1,
            },
        )
        assert second.status_code == 200, second.text
        second_evidence = second.json()["recall_evidence"]
        assert second_evidence is not None
        assert second_evidence["delayed_recall"] is True
        assert second_evidence["delay_days"] >= 1.0
        dimensions = (
            (runtime.memory_service.snapshot(workspace).workspace or {})
            .get("training_skill_projection", {})
            .get("dimensions", {})
        )
        assert dimensions["delayed_recall"]["state"] == "independent"


def test_review_queue_done_without_an_answer_does_not_grade_fsrs(tmp_path) -> None:
    from app.memory.models import MasteryRecord, WeaknessRecord

    with build_client(tmp_path) as client:
        runtime = _runtime(client)
        workspace = "ws-review-done"
        structured = runtime.memory_service.structured_for_workspace(workspace)
        past = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
        structured._mastery["tuple slot"] = MasteryRecord(
            concept="tuple slot",
            score=0.6,
            confidence=0.7,
            review_source="fsrs",
            fsrs_stability=7.5,
            fsrs_difficulty=4.2,
            fsrs_reps=3,
            next_review_at=past,
            due_date=past,
        )
        structured._weaknesses["tuple slot"] = WeaknessRecord(
            concept="tuple slot",
            reason="Explain the assignment boundary.",
            severity=3,
            next_review_at=past,
        )
        runtime.memory_service._persist_structured(workspace)

        response = client.post(
            "/training/review-queue/action",
            json={"workspace_id": workspace, "concept": "tuple slot", "action": "done"},
        )
        assert response.status_code == 200, response.text

        refreshed = runtime.memory_service.structured_for_workspace(workspace)
        mastery = refreshed._mastery["tuple slot"]
        assert mastery.fsrs_stability == 7.5
        assert mastery.fsrs_difficulty == 4.2
        assert mastery.fsrs_reps == 3
        assert mastery.review_source == "fsrs"
        assert mastery.next_review_at is not None
        assert mastery.next_review_at > datetime.now(UTC) - timedelta(minutes=5)


def test_return_card_controlled_pass_counts_as_transfer(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from app.core.models import (
        EvaluationCheck,
        EvaluationReport,
        TrainingCardCandidateSnapshot,
    )

    with build_client(tmp_path) as client:
        runtime = _runtime(client)
        workspace = "ws-return-transfer"
        session = client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Transfer lab"},
        ).json()["session_id"]
        path = str(tmp_path / "transfer.py")
        card = TrainingCardCandidateSnapshot(
            card_id="card-return-transfer",
            card_type="practice",
            status="active",
            learning_phase="return",
            title="Apply the lock pattern in the project",
            focus_area="lock pattern migration",
            scenario="new project context",
            files_to_touch=[path],
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(workspace, selected_card_id=card.card_id)
        attempt_store = runtime.attempt_store
        assert attempt_store is not None, "the sidecar runtime must own an attempt store"
        attempt = attempt_store.start_attempt(
            workspace_id=workspace,
            card_id=card.card_id,
            file_path=path,
        )
        runtime.evaluator_service.evaluate_current_file = MagicMock(
            return_value=EvaluationReport(
                passed=True,
                summary="1 test passed",
                next_step="Reflect",
                reflection="",
                dynamic_checks=[
                    EvaluationCheck(
                        id="pytest",
                        label="pytest",
                        status="passed",
                        detail="1 passed",
                    )
                ],
            )
        )
        response = client.post(
            "/evaluate/current-file",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "evaluation_source": "training",
                "training_card_id": card.card_id,
                "training_phase": "verify",
                "file_path": path,
                "content": "def test_boundary():\n    assert True\n",
                "language_id": "python",
            },
        )
        assert response.status_code == 200, response.text
        evidence = attempt_store.list_evidence(attempt["attempt_id"])
        current = [item for item in evidence if item.get("is_current")]
        assert current and current[0]["dimension"] == "transfer"
        assert current[0]["transfer_metadata"] == {"source": "training_return"}
        dimensions = (
            (runtime.memory_service.snapshot(workspace).workspace or {})
            .get("training_skill_projection", {})
            .get("dimensions", {})
        )
        assert dimensions["transfer"]["state"] == "independent"
        assert dimensions["implementation"]["state"] == "not_verified"


def test_unified_evidence_preserves_evidence_kind_and_delay() -> None:
    from app.evidence.contract import evidence_from_attempt

    item = evidence_from_attempt(
        {
            "evidence_id": "recall-unified",
            "attempt_id": "attempt-recall-unified",
            "workspace_id": "ws",
            "card_id": "card",
            "result": "passed",
            "trust_level": "controlled_check",
            "assistance_level": "none",
            "dimension": "delayed_recall",
            "evidence_kind": "recall",
            "recall_delay_days": 2.5,
            "recall_rating": "good",
            "artifact_hash": "hash",
            "created_at": "2026-11-04T09:00:00+00:00",
        },
        workspace_id="ws",
    )

    assert item.dimension == "delayed_recall"
    assert item.evidence_kind == "recall"
    assert item.recall_delay_days == 2.5
    assert item.recall_rating == "good"
    assert item.assistance_level == "none"


def test_theory_drill_answer_records_comprehension_not_delayed_recall(tmp_path) -> None:
    with build_client(tmp_path) as client:
        runtime = _runtime(client)
        workspace = "ws-theory-comprehension"
        structured = runtime.memory_service.structured_for_workspace(workspace)
        structured.upsert_dependency_mastery(
            "fastapi",
            dependency_name="FastAPI",
            apis=["Depends"],
            scenarios=["Inject a dependency into one route"],
            weakest_points=["Cannot yet explain the route boundary."],
            evidence=["Initial theory check."],
        )
        theory_drill = runtime.memory_service.snapshot(workspace).theory_drill
        assert theory_drill is not None
        question = theory_drill.questions[0]

        response = client.post(
            "/training/theory-drill/answer",
            json={
                "workspace_id": workspace,
                "theory_drill_id": theory_drill.id,
                "question_id": question.id,
                "learner_answer": question.answer,
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["correct"] is True
        assert payload["recall_evidence"]["dimension"] == "comprehension"
        assert payload["recall_evidence"]["delayed_recall"] is False
        dimensions = (
            (runtime.memory_service.snapshot(workspace).workspace or {})
            .get("training_skill_projection", {})
            .get("dimensions", {})
        )
        assert dimensions["comprehension"]["state"] == "independent"
        assert dimensions["delayed_recall"]["state"] == "not_verified"


def test_attempt_store_marks_no_hint_as_none_not_independent(tmp_path) -> None:
    store = AttemptStore(tmp_path / "attempts.db")
    attempt = store.start_attempt(workspace_id="ws", card_id="card")
    assert attempt["assistance_level"] == "none"

    evidence = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash",
        result="passed",
    )
    assert evidence is not None
    assert evidence["assistance_level"] == "none"
    projected = project_skills([evidence])["implementation"]
    assert projected["state"] == "independent"


"""Five capability dimensions advance only from real, qualified evidence.

The ladder is intentionally strict:
* assisted needs a controlled pass with an explicitly assisted level;
* independent needs a controlled pass with explicitly no assistance;
* transfer needs an explicit cross-context fact, not an incidental scenario;
* delayed_recall needs an answered recall after a real retention interval;
* missing/unknown facts never become independent or verified.
"""

# ---------------------------------------------------------------------------
# Restored from test_attestation_idempotency_endpoint.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------

WORKSPACE_ID = "ws-attest-idempotency"


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer attestation idempotency",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-attest-idempotency.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(_settings(tmp_path / "data"))
    card = TrainingCardCandidateSnapshot(
        card_id="card-attest-idem",
        card_type="practice",
        title="Persist the attestation path",
        target_skill="reliability",
        validation_method="Run the focused attestation test.",
        status="active",
    )
    app.state.runtime.memory_service.upsert_card(WORKSPACE_ID, card)
    return TestClient(app)


def _attest_payload(summary: str, idempotency_key: str) -> dict:
    return {
        "workspace_id": WORKSPACE_ID,
        "card_id": "card-attest-idem",
        "passed": True,
        "summary": summary,
        "tests_output": summary,
        "evidence_source": "test_runner",
        "idempotency_key": idempotency_key,
    }


def test_same_idempotency_key_replays_and_keeps_the_first_evidence(tmp_path: Path) -> None:
    client = _client(tmp_path)

    first = client.post(
        "/training/verification/attest", json=_attest_payload("first run summary", "run-7:card")
    )
    assert first.status_code == 200, first.text
    first_workspace = first.json()["workspace"]
    reliability = first_workspace["latest_training_reliability"]
    assert reliability["phase"] in {"succeeded", "acked"}
    assert reliability["idempotency_key"] == "run-7:card"
    first_revision = first_workspace["training_snapshot_revision"]
    assert first_revision >= 1

    # Same run, delivery retried: the ledger replays instead of recording a
    # second host-trusted evidence entry with the retry's payload.
    second = client.post(
        "/training/verification/attest",
        json=_attest_payload("retry with lost response", "run-7:card"),
    )
    assert second.status_code == 200, second.text
    second_workspace = second.json()["workspace"]
    assert second_workspace["training_snapshot_revision"] == first_revision
    assert second_workspace["latest_training_reliability"]["idempotency_key"] == "run-7:card"


def test_a_new_run_key_executes_and_advances_the_ledger(tmp_path: Path) -> None:
    client = _client(tmp_path)

    first = client.post(
        "/training/verification/attest", json=_attest_payload("first run summary", "run-7:card")
    )
    assert first.status_code == 200, first.text
    first_revision = first.json()["workspace"]["training_snapshot_revision"]

    second = client.post(
        "/training/verification/attest", json=_attest_payload("second genuine run", "run-8:card")
    )
    assert second.status_code == 200, second.text
    second_workspace = second.json()["workspace"]
    assert second_workspace["training_snapshot_revision"] > first_revision
    assert second_workspace["latest_training_reliability"]["idempotency_key"] == "run-8:card"


"""Host attestation endpoint: idempotency_key pass-through replays instead of
double-recording host-trusted evidence (R1)."""

# ---------------------------------------------------------------------------
# Restored from test_evidence_controls.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_consecutive_failures_degrade_to_easier_scaffolding() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(
            success_streak=0, failure_streak=2, failure_count=2, historical_error_count=2
        )
    )

    assert controls.difficulty == "easy"
    assert controls.hint_count == 3
    assert controls.should_reveal_code is True
    assert controls.code_reveal == "full"
    assert controls.practice_type == "recover"
    assert controls.review_frequency == "sooner"
    assert controls.material_recommendation == "simpler"
    assert controls.next_plan_step == "shrink"
    assert controls.challenge_level == "lower"
    assert controls.pedagogy_mode == "debug_guide"
    overrides = routing_learner_overrides(controls)
    assert overrides["difficulty_preference"] == "easy"
    assert overrides["needs_rescue"] is True
    assert review_after_days_for_frequency(controls.review_frequency) == 1


def test_consecutive_successes_upgrade_and_withhold_code() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(
            success_streak=2,
            failure_streak=0,
            success_count=2,
            concept_success=True,
            verified_success=True,
        )
    )

    assert controls.difficulty == "hard"
    assert controls.hint_count == 1
    assert controls.should_reveal_code is False
    assert controls.code_reveal == "withhold"
    assert controls.practice_type == "stretch"
    assert controls.review_frequency == "later"
    assert controls.next_plan_step == "widen"
    assert controls.challenge_level == "raise"
    assert routing_learner_overrides(controls)["difficulty_preference"] == "hard"
    assert review_after_days_for_frequency(controls.review_frequency) == 4


def test_success_streak_overrides_older_repeated_failure() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(
            success_streak=2,
            failure_streak=0,
            success_count=2,
            failure_count=2,
            repeated_failure=True,
            concept_success=True,
            verified_success=True,
            historical_error_count=2,
        )
    )
    assert controls.difficulty == "hard"
    assert controls.next_plan_step == "widen"
    assert controls.challenge_level == "raise"


def test_single_success_does_not_raise_difficulty() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=1, success_count=1, concept_success=True)
    )

    assert controls.difficulty == "medium"
    assert controls.challenge_level == "steady"
    assert controls.hint_count == 2
    assert controls.code_reveal == "scaffold"
    assert controls.should_reveal_code is False
    assert controls.explanation_mode == "transfer"


def test_one_scene_success_does_not_recommend_transfer_or_promote() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(
            success_streak=2,
            success_count=2,
            concept_success=True,
            verified_success=True,
        ),
        transfer_scene_count=1,
        transfer_state="awaiting_second_scene",
    )

    assert controls.difficulty == "hard"
    assert controls.material_recommendation == "current"
    assert controls.explanation_depth == "grounded"
    assert controls.transferable is False
    assert (
        should_promote_transferable_skill(
            concept="router design",
            workspace_id="project-a",
            current_scene_key="default",
            existing_scenes=[{"workspace_id": "project-a", "scene_key": "default"}],
            outcome_success=True,
        )
        is False
    )


def test_two_scenes_can_recommend_transfer_without_claiming_one_project_mastery() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=2, success_count=2, concept_success=True),
        transfer_scene_count=2,
        transfer_state="transferable",
    )
    assert controls.material_recommendation == "transfer"
    assert controls.explanation_depth == "transfer"
    assert controls.transferable is True
    assert (
        should_promote_transferable_skill(
            concept="router design",
            workspace_id="project-b",
            current_scene_key="default",
            existing_scenes=[{"workspace_id": "project-a", "scene_key": "default"}],
            outcome_success=True,
        )
        is True
    )


def test_card_application_adds_hints_on_failure_and_strips_code_on_success() -> None:
    starter = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="Practice router",
        suggested_workspace_action="```python\ndef fix():\n    return True\n```",
        hint_ladder=["Name the failing test."],
        difficulty="medium",
    )
    easier = apply_controls_to_card(
        starter,
        resolve_pedagogy_controls(LearningEvidenceSignals(failure_streak=2, failure_count=2)),
        language="en-US",
    )
    assert easier.difficulty == "easy"
    assert len(easier.hint_ladder) == 3
    assert "```" in (easier.suggested_workspace_action or "")

    harder = apply_controls_to_card(
        starter,
        resolve_pedagogy_controls(
            LearningEvidenceSignals(success_streak=2, success_count=2, verified_success=True)
        ),
        language="en-US",
    )
    assert harder.difficulty == "hard"
    assert len(harder.hint_ladder) == 1
    assert "```" not in (harder.suggested_workspace_action or "")
    assert "full solution" in (harder.suggested_workspace_action or "").lower()


def test_user_preference_can_raise_but_affect_overload_stays_degraded() -> None:
    raised = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=1, success_count=1),
        user_preference="too_simple",
    )
    assert raised.difficulty == "hard"
    assert raised.challenge_level == "raise"

    overloaded = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=2, success_count=2),
        user_preference="too_simple",
        affect_recovery="overloaded",
    )
    assert overloaded.difficulty == "easy"
    assert overloaded.pedagogy_mode == "debug_guide"


def _client__evidence_controls(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Evidence Controls Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-evidence-controls.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def _start(client: TestClient, workspace_id: str) -> str:
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": workspace_id,
            "profile": {
                "long_term_goal": "Let evidence change difficulty",
                "weekly_hours": 4,
                "teaching_style": "guided",
                "answer_policy": "guided",
            },
        },
    )
    assert response.status_code == 200
    return str(response.json()["session_id"])


def _signal(
    client: TestClient, session_id: str, workspace_id: str, outcome: str, summary: str
) -> dict:
    response = client.post(
        "/learning/signal",
        json={
            "session_id": session_id,
            "workspace_id": workspace_id,
            "concepts": ["config validation"],
            "outcome": outcome,
            "summary": summary,
            "action_type": "evaluate_current_file",
            "focus_area": "config validation",
            "scenario": "review_reflection",
            "repetition_count": 2 if outcome in {"repeated_error", "evaluation"} else 1,
        },
    )
    assert response.status_code == 200
    return response.json()


def _model_practice_card_json() -> str:
    return json.dumps(
        {
            "title": "Practice config validation",
            "focus_area": "config validation",
            "target_skill": "verify one config branch",
            "scenario": "A config branch keeps failing and needs one verified slice.",
            "problem_statement": "Reproduce the failing config branch and verify one fix.",
            "api_hints": ["Run the config check", "Fix one failing branch"],
            "deliverable": "A snippet that validates the fixed branch.",
            "self_check": ["The branch passes", "No other branch changed"],
            "grading_rubric": ["Fixes the failing branch", "Includes verification output"],
            "stuck_recovery": "Write the expected config shape on paper first.",
            "reflection_prompt": "What assumption made the branch fail?",
        }
    )


def _configure_verified_provider(client: TestClient) -> None:
    provider = ProviderConfig(
        name="test",
        baseUrl="http://127.0.0.1:9/v1",
        apiKeyRef="trainer.test",
        model="gpt-4o-mini",
        capabilities=CapabilityFlags(chat=True, streaming=True),
    )
    runtime = _runtime(client)
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test")

    from tests.provider_fixtures import seed_verified_capabilities

    seed_verified_capabilities(runtime, provider, "sk-test", tools=False)


def test_generate_card_follows_failure_and_success_streaks(tmp_path: Path) -> None:
    with _client__evidence_controls(tmp_path) as client:
        _configure_verified_provider(client)
        fail_workspace = "workspace-evidence-failures"
        session_id = _start(client, fail_workspace)
        _signal(client, session_id, fail_workspace, "evaluation", "Config validation still fails.")
        fail_payload = _signal(
            client,
            session_id,
            fail_workspace,
            "repeated_error",
            "Config validation still fails.",
        )
        adaptation = fail_payload["memory"]["coaching_adaptation"]
        assert adaptation["difficulty"] == "easy"
        assert adaptation["hint_count"] == 3
        assert adaptation["should_reveal_code"] is True
        assert adaptation["failure_streak"] >= 2
        with patch.object(
            ProviderService,
            "chat_completion",
            new=AsyncMock(return_value=_model_practice_card_json()),
        ):
            generated = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": fail_workspace,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "config validation",
                    "context_hint": "The learner is stuck on one failing config branch.",
                    "response_language": "en-US",
                },
            )
        assert generated.status_code == 200
        fail_card = generated.json()["card"]
        assert fail_card["difficulty"] == "easy"
        assert len(fail_card.get("hint_ladder") or []) >= 3

        win_workspace = "workspace-evidence-successes"
        win_session = _start(client, win_workspace)
        # Client-claimed tests_passed via /learning/signal is low-trust: not proof.
        _signal(client, win_session, win_workspace, "tests_passed", "The focused tests now pass.")
        win_payload = _signal(
            client,
            win_session,
            win_workspace,
            "concept_answered_correctly",
            "The learner explained the config boundary correctly.",
        )
        win_adaptation = win_payload["memory"]["coaching_adaptation"]
        assert win_adaptation["difficulty"] == "medium"
        assert win_adaptation["challenge_level"] == "steady"
        assert win_adaptation["material_recommendation"] == "current"
        assert win_adaptation["next_plan_step"] == "hold"
        transfer = win_payload["memory"]["workspace"].get("latest_transfer_state") or {}
        assert transfer.get("state") in {"", None, "project_only", "awaiting_second_scene"}
        assert transfer.get("state") != "transferable"
        assert not (win_payload.get("global_memory") or {}).get("capability_profile")
        with patch.object(
            ProviderService,
            "chat_completion",
            new=AsyncMock(return_value=_model_practice_card_json()),
        ):
            win_card = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": win_workspace,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "config validation",
                    "context_hint": "The learner just verified one local slice.",
                    "response_language": "en-US",
                },
            )
        assert win_card.status_code == 200
        steady_card = win_card.json()["card"]
        assert steady_card["difficulty"] == "medium"


def test_socratic_mode_is_evidence_gated() -> None:
    socratic = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=2, success_count=2),
        preferred_teaching_style="guided",
    )
    assert socratic.pedagogy_mode == "socratic"
    assert socratic.should_reveal_code is False

    debug = resolve_pedagogy_controls(
        LearningEvidenceSignals(failure_streak=2, failure_count=2),
        preferred_teaching_style="socratic",
    )
    assert debug.pedagogy_mode == "debug_guide"
    assert debug.should_reveal_code is True


def test_unverified_success_streak_does_not_raise_or_claim_mastery() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=2, success_count=2, concept_success=True)
    )
    assert controls.difficulty == "medium"
    assert controls.challenge_level == "steady"
    assert controls.next_plan_step == "hold"
    assert controls.transferable is False
    assert controls.material_recommendation == "current"
    assert pedagogy_evidence_confidence(verified_success=False, success_count=2) == 0.25
    assert pedagogy_evidence_confidence(verified_success=True, success_count=2) == 0.8
    assert pedagogy_evidence_confidence(verified_success=False, success_count=0) == 0.5
    assert (
        pedagogy_evidence_confidence(
            verified_success=False,
            success_count=0,
            outcomes=[
                {
                    "outcome": "tests_passed",
                    "summary": "Client claimed",
                    "verified_by_evaluator": False,
                }
            ],
        )
        == 0.25
    )


def test_untrusted_outcome_labels_are_not_verified_proof() -> None:
    signals = analyze_learning_evidence(
        [
            {
                "outcome": "tests_passed",
                "summary": "Client claimed pass",
                "verified_by_evaluator": False,
            },
            {
                "outcome": "tests_passed",
                "summary": "Empty verified_result",
                "verified_by_evaluator": True,
                "verified_result": "",
            },
            {"outcome": "concept_answered_correctly", "summary": "Explained locally"},
        ]
    )
    assert signals.verified_success is False
    # Untrusted labels break the streak; concept alone may still count but cannot raise.
    assert signals.success_streak == 0
    assert signals.success_count == 1
    controls = resolve_pedagogy_controls(signals)
    assert controls.difficulty == "medium"
    assert controls.challenge_level == "steady"
    assert controls.transferable is False

    trusted = analyze_learning_evidence(
        [
            {
                "outcome": "tests_passed",
                "summary": "Evaluator ack",
                "verified_by_evaluator": True,
                "verified_result": "Focused checks passed.",
            },
            {
                "outcome": "code_landed",
                "summary": "Second ack",
                "verified_by_evaluator": True,
                "verified_result": "Slice landed under the same boundary.",
            },
        ]
    )
    assert trusted.verified_success is True
    assert trusted.success_streak == 2
    raised = resolve_pedagogy_controls(trusted)
    assert raised.difficulty == "hard"
    assert raised.challenge_level == "raise"
    assert raised.transferable is False


def test_streak_adapts_without_inventing_live_objects() -> None:
    assert (
        streak_adapts_without_inventing_live_objects(
            failure_streak=2,
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is True
    )
    assert (
        streak_adapts_without_inventing_live_objects(
            failure_streak=2,
            live_plan=True,
            live_task=False,
            live_card=False,
        )
        is False
    )
    assert (
        streak_adapts_without_inventing_live_objects(
            success_streak=2,
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is True
    )
    assert (
        streak_adapts_without_inventing_live_objects(
            success_streak=2,
            live_card=True,
        )
        is False
    )


def test_consecutive_unverified_tests_passed_does_not_mark_mastery_or_mint(
    tmp_path: Path,
) -> None:
    """Client tests_passed without evaluator+verified_result is not mastery."""

    workspace_id = "workspace-unverified-tests-passed-streak"
    with _client__evidence_controls(tmp_path) as client:
        session_id = _start(client, workspace_id)
        first = _signal(
            client,
            session_id,
            workspace_id,
            "tests_passed",
            "Client claimed pass one.",
        )
        second = _signal(
            client,
            session_id,
            workspace_id,
            "tests_passed",
            "Client claimed pass two.",
        )
        coaching = (second.get("memory") or {}).get("coaching_adaptation") or {}
        assert int(coaching.get("success_streak") or 0) == 0
        assert coaching.get("challenge_level") == "steady"
        assert coaching.get("next_plan_step") == "hold"
        assert coaching.get("material_recommendation") != "transfer"
        assert second.get("plan") in (None, {})
        assert not (second.get("current_task") or second.get("currentTask") or {}).get("title")
        mastery = (second.get("memory") or {}).get("mastery") or []
        assert mastery == []
        structured = _runtime(client).memory_service._structured_for(workspace_id)
        assert "config validation" not in structured._mastery
        transfer = ((second.get("memory") or {}).get("workspace") or {}).get(
            "latest_transfer_state"
        ) or {}
        assert transfer.get("state") not in {"transferable"}
        # First payload also must not have raised from a lone unverified label.
        first_coaching = (first.get("memory") or {}).get("coaching_adaptation") or {}
        assert int(first_coaching.get("success_streak") or 0) == 0


def test_consecutive_failure_signal_adapts_hints_without_live_objects(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-fail-streak-hint-only"
    with _client__evidence_controls(tmp_path) as client:
        session_id = _start(client, workspace_id)
        _signal(client, session_id, workspace_id, "evaluation", "Still failing check A.")
        payload = _signal(
            client,
            session_id,
            workspace_id,
            "repeated_error",
            "Still failing check A again.",
        )
        coaching = (payload.get("memory") or {}).get("coaching_adaptation") or {}
        assert int(coaching.get("failure_streak") or 0) >= 2
        assert coaching.get("hint_count") == 3
        assert coaching.get("challenge_level") == "lower"
        assert coaching.get("next_plan_step") == "shrink"
        assert payload.get("plan") in (None, {})
        assert not (payload.get("current_task") or payload.get("currentTask") or {}).get("title")
        assert streak_adapts_without_inventing_live_objects(
            failure_streak=int(coaching.get("failure_streak") or 0),
            live_plan=False,
            live_task=False,
            live_card=False,
        )


def test_identical_failure_signals_still_raise_consecutive_streak(
    tmp_path: Path,
) -> None:
    """Same concept+outcome+action overwrites one record; streak uses repetition."""

    workspace_id = "workspace-identical-fail-overwrite"
    with _client__evidence_controls(tmp_path) as client:
        session_id = _start(client, workspace_id)
        body = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "concepts": ["config validation"],
            "outcome": "evaluation",
            "summary": "Same failing check.",
            "action_type": "evaluate_current_file",
            "focus_area": "config validation",
            "scenario": "review_reflection",
        }
        first = client.post("/learning/signal", json=body)
        assert first.status_code == 200
        second = client.post(
            "/learning/signal",
            json={**body, "summary": "Same failing check again."},
        )
        assert second.status_code == 200
        payload = second.json()
        coaching = (payload.get("memory") or {}).get("coaching_adaptation") or {}
        assert int(coaching.get("failure_streak") or 0) >= 2
        assert coaching.get("hint_count") == 3
        assert coaching.get("challenge_level") == "lower"
        structured = _runtime(client).memory_service._structured_for(workspace_id)
        assert len(structured._learning_outcomes) == 1
        only = next(iter(structured._learning_outcomes.values()))
        assert int(only.repetition_count or 0) >= 2
        assert payload.get("plan") in (None, {})
        assert not (payload.get("current_task") or payload.get("currentTask") or {}).get("title")
        assert streak_adapts_without_inventing_live_objects(
            failure_streak=int(coaching.get("failure_streak") or 0),
            live_plan=False,
            live_task=False,
            live_card=False,
        )


def test_client_repetition_count_99_is_not_mastery_theater(tmp_path: Path) -> None:
    """Client-claimed repetition_count must not inflate streak/mastery theater."""
    workspace_id = "workspace-client-rep-99"
    with _client__evidence_controls(tmp_path) as client:
        session_id = _start(client, workspace_id)
        response = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "concepts": ["config validation"],
                "outcome": "evaluation",
                "summary": "Client claims ninety-nine repeats of the same miss.",
                "action_type": "evaluate_current_file",
                "focus_area": "config validation",
                "scenario": "review_reflection",
                "repetition_count": 99,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        coaching = (payload.get("memory") or {}).get("coaching_adaptation") or {}
        assert int(coaching.get("failure_streak") or 0) < 99
        assert int(coaching.get("success_streak") or 0) < 99
        assert int(coaching.get("failure_streak") or 0) <= 1
        mastery = (payload.get("memory") or {}).get("mastery") or []
        assert mastery == []
        structured = _runtime(client).memory_service._structured_for(workspace_id)
        only = next(iter(structured._learning_outcomes.values()))
        assert int(only.repetition_count or 0) == 1
        assert "config validation" not in structured._mastery


def test_analyze_learning_evidence_counts_repetition_as_streak() -> None:
    signals = analyze_learning_evidence(
        [
            {
                "outcome": "evaluation",
                "repetition_count": 2,
                "summary": "Same miss twice via overwrite key.",
            }
        ]
    )
    assert signals.failure_streak >= 2
    assert signals.failure_count >= 2
    assert signals.repeated_failure is True
