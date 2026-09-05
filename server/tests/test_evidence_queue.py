"""§7.1 Evidence queue lifecycle tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import (
    EvidenceAdoptResponse,
    EvidenceItem,
    EvidenceQueueSnapshot,
    LearningPlan,
    PlanStage,
)
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService
from app.planner.service import PlannerService


def _cleanup_db(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


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
        self.service.enqueue_evidence("ws-test", EvidenceItem(summary="persist-me", source="learning_signal"))
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


if __name__ == "__main__":
    unittest.main()
