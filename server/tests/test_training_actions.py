"""Tests for training action endpoints: flashcard, theory drill, skill map, review queue, scenario lab."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import TrainingCardCandidateSnapshot
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService


class TrainingActionEndpointTests(unittest.TestCase):
    """Unit tests for training action service methods used by API endpoints."""

    def setUp(self) -> None:
        database_path = Path(f".tmp-test/training-actions-{id(self)}.db")
        if database_path.exists():
            database_path.unlink()
        self.repository = TrainerRepository(database_path)
        self.service = MemoryService(self.repository)
        self.workspace_id = "ws-training-actions"

    def test_submit_flashcard_answer_records_attempt(self) -> None:
        """S1: Flashcard answer submission records the attempt."""
        self.service.upsert_card(
            self.workspace_id,
            TrainingCardCandidateSnapshot(
                card_id="flash-001",
                card_type="flash",
                title="Answer check",
                status="active",
                expected_answer="The answer is 42",
            ),
        )
        result = self.service.submit_flashcard_answer(
            self.workspace_id,
            card_id="flash-001",
            learner_answer="The answer is 42",
            selected_option_index=None,
        )
        self.assertTrue(hasattr(result, "correct"))
        self.assertIsInstance(result.correct, bool)
        self.assertTrue(result.correct)

    def test_submit_flashcard_answer_short_answer_marked_incorrect(self) -> None:
        """S2: Short answers are marked incorrect."""
        self.service.upsert_card(
            self.workspace_id,
            TrainingCardCandidateSnapshot(
                card_id="flash-002",
                card_type="flash",
                title="Answer check",
                status="active",
                expected_answer="yes",
            ),
        )
        result = self.service.submit_flashcard_answer(
            self.workspace_id,
            card_id="flash-002",
            learner_answer="no",
            selected_option_index=None,
        )
        self.assertFalse(result.correct)

    def test_apply_dependency_skill_map_action_updates_version(self) -> None:
        """S3: Dependency skill map action increments version."""
        # Seed a dependency mastery entry
        self.service._structured_for(self.workspace_id)._dependency_mastery["react"] = {
            "mastery_stage": "understood",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        maps, history, scenario_lab = self.service.apply_dependency_skill_map_action(
            self.workspace_id,
            dependency_key="react",
            action="mark_practiced",
            note="Used useState hook",
            focus_item_key="useState",
            related_api="useState",
            scenario="todo-app",
            verified_by_evaluator=True,
            verification_source="current_file_evaluator",
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].action, "mark_practiced")
        self.assertEqual(history[0].version, 1)
        self.assertIsNotNone(scenario_lab)

    def test_apply_dependency_skill_map_action_missing_key_returns_not_found(self) -> None:
        """S4: A missing dependency map cannot report a successful action."""
        with self.assertRaises(HTTPException) as raised:
            self.service.apply_dependency_skill_map_action(
                self.workspace_id,
                dependency_key="nonexistent",
                action="mark_practiced",
                verified_by_evaluator=True,
                verification_source="current_file_evaluator",
            )
        self.assertEqual(raised.exception.status_code, 404)
        self.assertIn("Refresh Training", str(raised.exception.detail))

    def test_record_learning_outcome_creates_evidence(self) -> None:
        """S5: Learning outcome recording creates evidence."""
        self.service.record_learning_outcome(
            workspace_id=self.workspace_id,
            concepts=["python decorators"],
            outcome="concept_answered_correctly",
            summary="Understood @decorator syntax",
        )
        # Learning outcome should be stored in memory
        structured = self.service._structured_for(self.workspace_id)
        outcomes = list(structured._learning_outcomes.values())
        self.assertGreaterEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].outcome, "concept_answered_correctly")

        queue = self.service.evidence_queue(self.workspace_id)
        self.assertGreaterEqual(len(queue.pending), 1)
        self.assertEqual(queue.pending[0].source, "learning_signal")
        self.assertEqual(queue.pending[0].outcome, "partial")

    def test_practice_evaluation_pass_requires_reflect_then_return(self) -> None:
        """S6: Trusted Verify stays provisional until Reflect and Return are complete."""
        card = TrainingCardCandidateSnapshot(
            card_id="practice-001",
            card_type="practice",
            title="Verify evaluator handoff",
            status="active",
            focus_area="evaluation handoff",
            target_skill="practice verification",
            scenario_pack="remote_workspace",
            next_after_completion="Return with the verified IDE evidence.",
        )
        self.service.upsert_card(self.workspace_id, card)

        workspace = self.service.record_training_practice_evaluation_result(
            workspace_id=self.workspace_id,
            card_id="practice-001",
            passed=True,
            summary="VS Code diagnostics and focused checks passed.",
            next_step="Return to Coach and ask for the next card.",
            focus_area="evaluation handoff",
            failed_checks=[],
            missing_requirements=[],
            verified_by_evaluator=True,
        )

        updated = self.service.get_card(self.workspace_id, "practice-001")
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.status, "active")
        self.assertEqual(workspace["selected_card_status"], "active")
        self.assertEqual(workspace["latest_learning_verified_result"], "")
        self.assertEqual(workspace["latest_learning_blocker"], "")
        self.assertEqual(workspace["latest_training_handoff"]["scenario_pack"], "remote_workspace")
        self.assertEqual(
            workspace["latest_training_handoff"]["next_after_completion"],
            "Return with the verified IDE evidence.",
        )
        self.assertEqual(workspace["latest_training_handoff"]["learning_phase"], "verify")
        self.assertEqual(workspace["latest_training_handoff"]["return_mode"], "reflection_required")
        self.assertEqual(workspace["latest_training_handoff"]["continue_in"], "training")
        self.assertEqual(workspace["latest_training_handoff"]["accepted_into"], "training")
        self.assertEqual(workspace["latest_training_next_hop"]["scenario_pack"], "remote_workspace")
        self.assertEqual(
            workspace["latest_training_next_hop"]["next_after_completion"],
            "Return with the verified IDE evidence.",
        )
        self.assertEqual(workspace["latest_training_next_hop"]["status"], "reflection_required")

        handoff_id = workspace["latest_training_handoff"]["handoff_id"]
        reflected = self.service.record_training_handoff_reflection(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            handoff_id=handoff_id,
            reflection="The focused checks proved the result instead of relying on my own report.",
        )
        self.assertEqual(reflected["latest_training_handoff"]["learning_phase"], "reflect")
        self.assertEqual(reflected["latest_training_next_hop"]["status"], "return_required")

        returned = self.service.return_training_handoff(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            handoff_id=handoff_id,
        )
        self.assertEqual(returned["selected_card_status"], "implemented")
        self.assertEqual(returned["latest_learning_verified_result"], "VS Code diagnostics and focused checks passed.")
        self.assertEqual(returned["latest_training_handoff"]["return_mode"], "result")
        self.assertEqual(returned["latest_training_next_hop"]["continue_in"], "chat")
        self.assertEqual(returned["latest_training_next_hop"]["accepted_into"], "coach")
        self.assertEqual(returned["latest_training_next_hop"]["status"], "continued_in_chat")

    def test_practice_evaluation_advances_related_dependency_only_after_trusted_verification(self) -> None:
        """S6a: A practice card can promote its dependency only after trusted verification."""
        structured = self.service.structured_for_workspace(self.workspace_id)
        structured.upsert_dependency_mastery(
            "fastapi",
            dependency_name="FastAPI",
            apis=["Depends"],
            scenarios=["Inject one dependency into a route"],
            weakest_points=["Cannot yet justify the route dependency boundary."],
            evidence=["Initial dependency map."],
            mastery_stage="understood",
            mastery_stage_progress=["understood"],
        )
        card = TrainingCardCandidateSnapshot(
            card_id="practice-fastapi-dependency",
            card_type="practice",
            title="Verify one FastAPI dependency boundary",
            status="active",
            focus_area="FastAPI dependency injection",
            target_skill="dependency injection",
            dependency_key="fastapi",
        )
        self.service.upsert_card(self.workspace_id, card)

        self.service.record_training_practice_evaluation_result(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            passed=True,
            summary="The learner says the route test passed.",
            next_step="Run current-file verification.",
            focus_area=card.focus_area,
            verified_by_evaluator=False,
        )
        unverified = next(
            item
            for item in self.service.snapshot(self.workspace_id).dependency_mastery
            if item.dependency_key == "fastapi"
        )
        self.assertEqual(unverified.mastery_stage, "understood")
        self.assertFalse(
            any(
                item.action == "mark_applied"
                for item in self.service.snapshot(self.workspace_id).dependency_skill_map_history
            )
        )

        self.service.record_training_practice_evaluation_result(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            passed=True,
            summary="Current-file diagnostics and focused route test passed.",
            next_step="Record what the verification proved.",
            focus_area=card.focus_area,
            verified_by_evaluator=True,
        )
        verified_snapshot = self.service.snapshot(self.workspace_id)
        verified = next(
            item for item in verified_snapshot.dependency_mastery if item.dependency_key == "fastapi"
        )
        self.assertEqual(verified.mastery_stage, "applied")
        self.assertTrue(
            any(item.action == "mark_applied" for item in verified_snapshot.dependency_skill_map_history)
        )

    def test_practice_evaluation_failure_keeps_card_retryable(self) -> None:
        """S7: Failed IDE verification keeps the active practice card retryable."""
        card = TrainingCardCandidateSnapshot(
            card_id="practice-002",
            card_type="practice",
            title="Fix current file diagnostics",
            status="active",
            focus_area="diagnostic recovery",
            target_skill="practice verification",
            scenario_pack="debug_loop",
            next_after_completion="Return with the failing diagnostic details.",
        )
        self.service.upsert_card(self.workspace_id, card)

        workspace = self.service.record_training_practice_evaluation_result(
            workspace_id=self.workspace_id,
            card_id="practice-002",
            passed=False,
            summary="Evaluation failed on: vscode-diagnostics.",
            next_step="Fix the VS Code diagnostics attached to the current file.",
            focus_area="diagnostic recovery",
            failed_checks=["vscode-diagnostics"],
            missing_requirements=["Type mismatch in current file."],
        )

        updated = self.service.get_card(self.workspace_id, "practice-002")
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.status, "blocked")
        self.assertEqual(workspace["selected_card_status"], "blocked")
        self.assertEqual(
            workspace["latest_learning_blocker"],
            "Fix the VS Code diagnostics attached to the current file.",
        )
        self.assertEqual(workspace["latest_learning_partial_progress"], "Evaluation failed on: vscode-diagnostics.")
        self.assertEqual(workspace["latest_training_handoff"]["scenario_pack"], "debug_loop")
        self.assertEqual(
            workspace["latest_training_handoff"]["next_after_completion"],
            "Return with the failing diagnostic details.",
        )
        self.assertEqual(workspace["latest_training_handoff"]["continue_in"], "training")
        self.assertEqual(workspace["latest_training_handoff"]["accepted_into"], "training")
        self.assertEqual(workspace["latest_training_next_hop"]["scenario_pack"], "debug_loop")
        self.assertEqual(
            workspace["latest_training_next_hop"]["next_after_completion"],
            "Return with the failing diagnostic details.",
        )
        self.assertEqual(workspace["latest_training_handoff"]["return_mode"], "blocker")
        self.assertEqual(workspace["latest_training_next_hop"]["continue_in"], "training")
        self.assertEqual(workspace["latest_training_next_hop"]["accepted_into"], "training")
        self.assertEqual(workspace["latest_training_next_hop"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
