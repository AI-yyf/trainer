"""§7.2 Evidence adoption plan persistence tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import (
    EvidenceAdoptResponse,
    EvidenceItem,
    LearningPlan,
    PlanStage,
)
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService


def _cleanup_db(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


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
        self.assertEqual(saved_plan.current_stage_id, "stage-1")
        self.assertEqual(
            {s.id: s.status for s in saved_plan.stages},
            {"stage-1": "active", "stage-2": "pending"},
        )


if __name__ == "__main__":
    unittest.main()
