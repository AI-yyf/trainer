"""Integration tests for training action API endpoints."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.api.runtime import TrainerRuntime
from app.core.models import (
    CardGenerationRequest,
    TheoryDrillQuestion,
    TheoryDrillSnapshot,
    TrainingCardCandidateSnapshot,
    UserProfile,
)
from app.main import app
from app.memory.models import utc_now


class TrainingEndpointIntegrationTests(unittest.TestCase):
    """Integration tests for POST /training/* endpoints via FastAPI TestClient."""

    def setUp(self) -> None:
        self.client = TestClient(app)
        self.workspace_id = "ws-integration-test"

    def _runtime(self) -> TrainerRuntime:
        return app.state.runtime

    def test_unknown_flashcard_answer_returns_not_found(self) -> None:
        """E1: A missing flashcard cannot be graded from answer length."""
        response = self.client.post(
            "/training/flashcard/answer",
            json={
                "workspace_id": self.workspace_id,
                "card_id": "flash-integration-001",
                "learner_answer": "This long answer must not turn a missing card into a success.",
                "selected_option_index": None,
            },
        )
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn("Refresh Training", data["detail"])

    def test_long_unrelated_flashcard_answer_returns_incorrect(self) -> None:
        """E2: A real card is still graded, but a long unrelated answer does not pass."""
        workspace_id = f"{self.workspace_id}-flash-{uuid4().hex}"
        self._runtime().memory_service.upsert_card(
            workspace_id,
            TrainingCardCandidateSnapshot(
                card_id="flash-integration-002",
                card_type="flash",
                title="FastAPI dependency check",
                status="active",
                expected_answer="FastAPI injects the dependency into the route.",
            ),
        )
        response = self.client.post(
            "/training/flashcard/answer",
            json={
                "workspace_id": workspace_id,
                "card_id": "flash-integration-002",
                "learner_answer": "This is deliberately long, but it discusses an unrelated CSS animation topic.",
                "selected_option_index": None,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["correct"])

    def test_structured_flashcard_answer_modes_round_trip_feedback(self) -> None:
        """E2a: multi-answer payloads reach the route and return structured grading."""
        workspace_id = f"{self.workspace_id}-structured-{uuid4().hex}"
        self._runtime().memory_service.upsert_card(
            workspace_id,
            TrainingCardCandidateSnapshot(
                card_id="flash-structured-001",
                card_type="flash",
                title="Ordering check",
                status="active",
                answer_mode="sorting",
                options=["Define", "Implement", "Verify"],
                correct_sort_order=[0, 1, 2],
            ),
        )
        response = self.client.post(
            "/training/flashcard/answer",
            json={
                "workspace_id": workspace_id,
                "card_id": "flash-structured-001",
                "sort_order": [0, 2, 1],
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["correct"])
        self.assertAlmostEqual(data["score"], 1 / 3, places=3)
        self.assertEqual(data["feedback"]["answer_mode"], "sorting")
        self.assertIn("sort_order", data["feedback"]["mismatches"])
        self.assertEqual(data["attempt"]["sort_order"], [0, 2, 1])

    def test_missing_theory_drill_answer_returns_not_found(self) -> None:
        """E3: A missing theory drill cannot be graded from answer length."""
        workspace_id = f"{self.workspace_id}-missing-theory-{uuid4().hex}"
        response = self.client.post(
            "/training/theory-drill/answer",
            json={
                "workspace_id": workspace_id,
                "theory_drill_id": "theory-001",
                "question_id": "q-001",
                "learner_answer": "Integration theory answer",
                "selected_option_index": None,
            },
        )
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn("Refresh Training", data["detail"])

    def test_theory_drill_rejects_stale_ids_and_persists_grounded_answer(self) -> None:
        """E3a: Current theory questions are saved; stale drill and question IDs request a refresh."""
        workspace_id = f"{self.workspace_id}-theory-{uuid4().hex}"
        structured = self._runtime().memory_service.structured_for_workspace(workspace_id)
        structured.upsert_dependency_mastery(
            "fastapi",
            dependency_name="FastAPI",
            apis=["Depends"],
            scenarios=["Inject a dependency into one route"],
            weakest_points=["Cannot yet explain the route boundary."],
            evidence=["Initial theory check."],
        )
        theory_drill = self._runtime().memory_service.snapshot(workspace_id).theory_drill
        self.assertIsNotNone(theory_drill)
        assert theory_drill is not None
        question = theory_drill.questions[0]

        stale_drill = self.client.post(
            "/training/theory-drill/answer",
            json={
                "workspace_id": workspace_id,
                "theory_drill_id": "theory-stale",
                "question_id": question.id,
                "learner_answer": question.answer,
            },
        )
        self.assertEqual(stale_drill.status_code, 409)
        self.assertIn("Refresh Training", stale_drill.json()["detail"])

        stale_question = self.client.post(
            "/training/theory-drill/answer",
            json={
                "workspace_id": workspace_id,
                "theory_drill_id": theory_drill.id,
                "question_id": "theory-question-stale",
                "learner_answer": question.answer,
            },
        )
        self.assertEqual(stale_question.status_code, 409)
        self.assertIn("Refresh Training", stale_question.json()["detail"])

        long_unrelated_answer = self.client.post(
            "/training/theory-drill/answer",
            json={
                "workspace_id": workspace_id,
                "theory_drill_id": theory_drill.id,
                "question_id": question.id,
                "learner_answer": "This is a long unrelated browser styling and animation description.",
            },
        )
        self.assertEqual(long_unrelated_answer.status_code, 200)
        self.assertFalse(long_unrelated_answer.json()["correct"])

        grounded_answer = self.client.post(
            "/training/theory-drill/answer",
            json={
                "workspace_id": workspace_id,
                "theory_drill_id": theory_drill.id,
                "question_id": question.id,
                "learner_answer": question.answer,
            },
        )
        self.assertEqual(grounded_answer.status_code, 200)
        self.assertTrue(grounded_answer.json()["correct"])
        saved_drill = self._runtime().memory_service.snapshot(workspace_id).theory_drill
        self.assertIsNotNone(saved_drill)
        assert saved_drill is not None
        self.assertEqual(saved_drill.last_action, "reopened")

    def test_theory_question_without_answer_key_requests_refresh(self) -> None:
        """E3b: A present-but-ungradeable theory question cannot report a result."""
        workspace_id = f"{self.workspace_id}-ungradeable-theory-{uuid4().hex}"
        structured = self._runtime().memory_service.structured_for_workspace(workspace_id)
        structured._theory_drill = TheoryDrillSnapshot(
            id="theory-ungradeable",
            questions=[
                TheoryDrillQuestion(
                    id="theory-question-ungradeable",
                    prompt="Explain the current dependency boundary.",
                    answer="",
                    dependency_key="fastapi",
                )
            ],
        )

        response = self.client.post(
            "/training/theory-drill/answer",
            json={
                "workspace_id": workspace_id,
                "theory_drill_id": "theory-ungradeable",
                "question_id": "theory-question-ungradeable",
                "learner_answer": "This long answer must not become a successful grade.",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("Refresh Training", response.json()["detail"])

    def test_dependency_skill_map_verification_request_returns_200_without_advancement(self) -> None:
        """E4: A verification request is recorded but does not advance mastery."""
        workspace_id = f"{self.workspace_id}-dependency-{uuid4().hex}"
        structured = self._runtime().memory_service.structured_for_workspace(workspace_id)
        structured.upsert_dependency_mastery(
            "react",
            dependency_name="React",
            apis=["useState"],
            scenarios=["Update one todo item"],
            weakest_points=["Cannot explain state ownership."],
            evidence=["Initial dependency map."],
        )
        self._runtime().memory_service.snapshot(workspace_id)

        response = self.client.post(
            "/training/dependency-skill-map/action",
            json={
                "workspace_id": workspace_id,
                "dependency_key": "react",
                "action": "request_verification",
                "note": "Integration test",
                "focus_item_key": "useState",
                "related_api": "useState",
                "scenario": "test-app",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn("maps", data)
        self.assertIn("history", data)
        self.assertTrue(data["maps"])
        self.assertTrue(data["history"])
        updated = next(
            item
            for item in self._runtime().memory_service.snapshot(workspace_id).dependency_mastery
            if item.dependency_key == "react"
        )
        self.assertEqual(updated.mastery_stage, "understood")

    def test_dependency_skill_map_public_advancement_is_rejected_without_state_change(self) -> None:
        """E4a: A client cannot raise dependency mastery by submitting its own result."""
        workspace_id = f"{self.workspace_id}-dependency-unverified-{uuid4().hex}"
        structured = self._runtime().memory_service.structured_for_workspace(workspace_id)
        structured.upsert_dependency_mastery(
            "react",
            dependency_name="React",
            apis=["useState"],
            scenarios=["Update one todo item"],
            weakest_points=["Cannot explain state ownership."],
            evidence=["Initial dependency map."],
            mastery_stage="understood",
            mastery_stage_progress=["understood"],
        )
        self._runtime().memory_service.snapshot(workspace_id)

        response = self.client.post(
            "/training/dependency-skill-map/action",
            json={
                "workspace_id": workspace_id,
                "dependency_key": "react",
                "action": "mark_practiced",
                "note": "The learner says this passed.",
                "focus_item_key": "useState",
                "related_api": "useState",
                "scenario": "test-app",
                "verified_result": "A client supplied this result.",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("Verify current file", response.json()["detail"])
        self.assertIn("not changed", response.json()["detail"])

        after = next(
            item
            for item in self._runtime().memory_service.snapshot(workspace_id).dependency_mastery
            if item.dependency_key == "react"
        )
        self.assertEqual(after.mastery_stage, "understood")
        self.assertFalse(
            any(
                item.action == "mark_practiced"
                for item in self._runtime().memory_service.snapshot(workspace_id).dependency_skill_map_history
            )
        )

    def test_dependency_skill_map_action_missing_key_returns_not_found(self) -> None:
        """E4a: A missing dependency map cannot report success without a state change."""
        response = self.client.post(
            "/training/dependency-skill-map/action",
            json={
                "workspace_id": f"{self.workspace_id}-missing-map-{uuid4().hex}",
                "dependency_key": "react",
                "action": "request_verification",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("Refresh Training", response.json()["detail"])

    def test_review_queue_action_endpoint_returns_200(self) -> None:
        """E5: POST /training/review-queue/action returns 200."""
        response = self.client.post(
            "/training/review-queue/action",
            json={
                "workspace_id": self.workspace_id,
                "concept": "python decorators",
                "action": "accept",
                "note": "Integration test",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])

    def test_review_queue_minimum_actions_are_accepted(self) -> None:
        for action in ("accept", "snooze", "reset", "skip", "done"):
            response = self.client.post(
                "/training/review-queue/action",
                json={
                    "workspace_id": f"{self.workspace_id}-{action}",
                    "concept": "python decorators",
                    "action": action,
                    "focus_area": "decorator boundaries",
                    "task_hint": "Explain one wrapper boundary.",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["ok"])

    def test_review_artifact_action_resolves_review_and_moves_its_due_date(self) -> None:
        """E5a: a saved review result resolves its artifact and schedules the next review."""
        workspace_id = f"{self.workspace_id}-review-artifact-{uuid4().hex}"
        runtime = self._runtime()
        structured = runtime.memory_service.structured_for_workspace(workspace_id)
        structured.record_weakness(
            "python decorators",
            "Needs one concise explanation of the wrapper boundary.",
            severity=2,
            review_after_days=0,
        )

        accepted = self.client.post(
            "/training/review-queue/action",
            json={
                "workspace_id": workspace_id,
                "concept": "python decorators",
                "action": "accept",
                "task_hint": "Explain the wrapper boundary in one sentence.",
            },
        )
        self.assertEqual(accepted.status_code, 200)
        artifact = runtime.memory_service.snapshot(workspace_id).review_artifact
        self.assertIsNotNone(artifact)
        assert artifact is not None and artifact.id is not None

        response = self.client.post(
            "/training/review-artifact/action",
            json={
                "workspace_id": workspace_id,
                "review_artifact_id": artifact.id,
                "action": "resolved",
                "note": "The decorator returns a wrapper that preserves the boundary.",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["review_artifact"]["status"], "resolved")
        self.assertGreater(structured._weaknesses["python decorators"].next_review_at, utc_now())

    def test_scenario_lab_action_endpoint_rejects_a_stale_lab_id(self) -> None:
        """E6: stale Scenario Lab actions return a recoverable conflict without creating evidence."""
        workspace_id = f"{self.workspace_id}-scenario-stale-{uuid4().hex}"
        response = self.client.post(
            "/training/scenario-lab/action",
            json={
                "workspace_id": workspace_id,
                "scenario_lab_id": "scenario-stale",
                "action": "complete",
                "note": "Integration test",
            },
        )
        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertIn("Refresh Training", data["detail"])
        snapshot = self._runtime().memory_service.snapshot(workspace_id)
        self.assertIsNone(snapshot.scenario_lab)
        self.assertFalse(snapshot.learning_outcomes)
        self.assertIsNone(snapshot.review_artifact)

    def test_scenario_lab_complete_endpoint_requires_server_verification(self) -> None:
        """E6a: a client complete request cannot turn a lab into verified growth evidence."""
        workspace_id = f"{self.workspace_id}-scenario-unverified-{uuid4().hex}"
        runtime = self._runtime()
        structured = runtime.memory_service.structured_for_workspace(workspace_id)
        structured.upsert_dependency_mastery(
            "fastapi",
            dependency_name="FastAPI",
            apis=["Depends"],
            scenarios=["Inject one dependency into a route"],
        )
        scenario_lab = runtime.memory_service.build_scenario_lab(workspace_id)
        self.assertIsNotNone(scenario_lab)
        assert scenario_lab is not None
        started = self.client.post(
            "/training/scenario-lab/action",
            json={
                "workspace_id": workspace_id,
                "scenario_lab_id": scenario_lab.id,
                "action": "start",
            },
        )
        self.assertEqual(started.status_code, 200)

        completed = self.client.post(
            "/training/scenario-lab/action",
            json={
                "workspace_id": workspace_id,
                "scenario_lab_id": scenario_lab.id,
                "action": "complete",
                "note": "A client note must not count as test evidence.",
                "review_outcome": "Client-claimed success.",
            },
        )
        self.assertEqual(completed.status_code, 409)
        self.assertIn("server-side verification", completed.json()["detail"])
        snapshot = runtime.memory_service.snapshot(workspace_id)
        self.assertIsNotNone(snapshot.scenario_lab)
        assert snapshot.scenario_lab is not None
        self.assertEqual(snapshot.scenario_lab.status, "in_progress")
        self.assertFalse(snapshot.learning_outcomes)
        self.assertIsNone(snapshot.review_artifact)

    def test_scenario_lab_restore_endpoint_restores_governed_history_and_updates_summary(self) -> None:
        """E7: POST /training/scenario-lab/restore restores the targeted governed history entry."""
        runtime = self._runtime()
        workspace_id = f"{self.workspace_id}-scenario-restore"
        runtime.memory_service.record_profile(
            workspace_id,
            UserProfile(
                long_term_goal="Practice minimum governed scenarios",
                weekly_hours=4,
                teaching_style="guided",
                answer_policy="guided",
                preferred_libraries=["FastAPI"],
            ),
        )
        structured = runtime.memory_service.structured_for_workspace(workspace_id)
        structured.upsert_dependency_mastery(
            "fastapi",
            dependency_name="FastAPI",
            apis=["Depends"],
            scenarios=["Inject one dependency into a route"],
            weakest_points=["Still mixes up when Depends belongs."],
            evidence=["Needs one minimum scenario first."],
        )
        structured.update_workspace(
            latest_learning_focus_area="dependency injection",
            latest_learning_scenario="scenario_lab_or_project",
            latest_flashcard_recovery_mode="scenario_lab_or_project",
        )
        created = runtime.memory_service.build_scenario_lab(workspace_id)
        self.assertIsNotNone(created)
        started, started_history = runtime.memory_service.apply_scenario_lab_action(
            workspace_id,
            scenario_lab_id=created.id,
            action="start",
            note="Start the scenario lab.",
        )
        self.assertIsNotNone(started)
        restore_target = min(started_history, key=lambda item: item.version)

        response = self.client.post(
            "/training/scenario-lab/restore",
            json={
                "workspace_id": workspace_id,
                "scenario_lab_id": created.id,
                "history_entry_id": restore_target.entry_id,
                "history_version": restore_target.version,
                "note": "Restore the earlier scenario lab state.",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["scenario_lab"]["last_action"], "restore_history")

        summary = self.client.get(f"/memory/summary?workspace_id={workspace_id}")
        self.assertEqual(summary.status_code, 200)
        summary_data = summary.json()
        self.assertEqual(summary_data["memory"]["scenario_lab"]["last_action"], "restore_history")
        self.assertEqual(summary_data["memory"]["workspace"]["latest_training_submode"], "practice")

    def test_review_artifact_restore_endpoint_restores_governed_history_and_updates_summary(self) -> None:
        """E8: POST /training/review-artifact/restore restores the targeted governed history entry."""
        runtime = self._runtime()
        workspace_id = f"{self.workspace_id}-review-restore-{uuid4().hex[:8]}"
        runtime.memory_service.record_profile(
            workspace_id,
            UserProfile(
                long_term_goal="Practice governed review recovery",
                weekly_hours=4,
                teaching_style="guided",
                answer_policy="guided",
                preferred_libraries=["FastAPI"],
            ),
        )
        runtime.memory_service.apply_review_queue_action(
            workspace_id,
            concept="fastapi Depends",
            action="accept",
            focus_area="dependency injection",
            task_hint="Build one route with Depends.",
            note="Pull this into training.",
        )
        first_snapshot = runtime.memory_service.snapshot(workspace_id)
        initial_artifact = first_snapshot.review_artifact
        self.assertIsNotNone(initial_artifact)
        runtime.memory_service.apply_review_queue_action(
            workspace_id,
            concept="fastapi Depends",
            action="reset",
            focus_area="dependency injection",
            task_hint="Go back to one minimum route first.",
            note="Still needs more practice.",
        )
        updated_snapshot = runtime.memory_service.snapshot(workspace_id)
        updated_artifact = updated_snapshot.review_artifact
        self.assertIsNotNone(updated_artifact)
        restore_target = min(updated_snapshot.review_artifact_history, key=lambda item: item.version)

        response = self.client.post(
            "/training/review-artifact/restore",
            json={
                "workspace_id": workspace_id,
                "review_artifact_id": updated_artifact.id,
                "history_entry_id": restore_target.entry_id,
                "history_version": restore_target.version,
                "note": "Restore the earlier governed review state.",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["review_artifact"]["last_action"], "restore_history")

        summary = self.client.get(f"/memory/summary?workspace_id={workspace_id}")
        self.assertEqual(summary.status_code, 200)
        summary_data = summary.json()
        self.assertEqual(summary_data["memory"]["review_artifact"]["last_action"], "restore_history")
        self.assertEqual(summary_data["memory"]["workspace"]["latest_training_submode"], "review")

    def test_theory_drill_restore_endpoint_restores_governed_history_and_updates_summary(self) -> None:
        """E9: POST /training/theory-drill/restore restores the targeted governed history entry."""
        runtime = self._runtime()
        workspace_id = f"{self.workspace_id}-theory-restore"
        runtime.memory_service.record_profile(
            workspace_id,
            UserProfile(
                long_term_goal="Practice governed theory recovery",
                weekly_hours=4,
                teaching_style="guided",
                answer_policy="guided",
                preferred_libraries=["FastAPI"],
            ),
        )
        structured = runtime.memory_service.structured_for_workspace(workspace_id)
        structured.upsert_dependency_mastery(
            "fastapi",
            dependency_name="FastAPI",
            apis=["Depends"],
            scenarios=["Inject one dependency into a route"],
            weakest_points=["Still cannot explain when Depends belongs in a route."],
            evidence=["Theory recall is unstable."],
        )
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["dependency injection", "Depends"],
            outcome="repeated_error",
            summary="Still cannot explain when Depends belongs in a real route.",
            focus_area="dependency injection",
            scenario="dependency_mastery",
            blocked_reason="Cannot connect Depends back to a concrete route handler.",
        )
        initial_snapshot = runtime.memory_service.snapshot(workspace_id)
        theory_drill = initial_snapshot.theory_drill
        self.assertIsNotNone(theory_drill)
        archived, archived_history = runtime.memory_service.apply_theory_drill_action(
            workspace_id,
            theory_drill_id=theory_drill.id,
            action="archive",
            note="Archive this governed theory drill for now.",
        )
        self.assertIsNotNone(archived)
        restore_target = min(archived_history, key=lambda item: item.version)

        response = self.client.post(
            "/training/theory-drill/restore",
            json={
                "workspace_id": workspace_id,
                "theory_drill_id": theory_drill.id,
                "history_entry_id": restore_target.entry_id,
                "history_version": restore_target.version,
                "note": "Restore the earlier governed theory drill state.",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["theory_drill"]["last_action"], "restore_history")

        summary = self.client.get(f"/memory/summary?workspace_id={workspace_id}")
        self.assertEqual(summary.status_code, 200)
        summary_data = summary.json()
        self.assertEqual(summary_data["memory"]["theory_drill"]["last_action"], "restore_history")
        self.assertEqual(summary_data["memory"]["workspace"]["latest_learning_scenario"], "theory_drill")

    def test_card_completion_evidence_persists_and_surfaces_in_memory_summary_after_runtime_rebuild(self) -> None:
        """E10: Training evidence stays authoritative after rebuild and remains visible via /memory/summary."""
        from app.core.settings import AppSettings
        from app.main import create_app

        workspace_id = f"{self.workspace_id}-evidence-persist-{uuid4().hex[:8]}"
        runtime = self._runtime()
        card = runtime.card_generation_service.generate_card(
            "dependency_mastery",
            CardGenerationRequest(
                workspace_id=workspace_id,
                source="dependency_mastery",
                card_type="practice",
                focus_area="dependency injection",
                target_skill="fastapi Depends",
                why_now="Need one real route slice before widening scope.",
            ),
        )
        runtime.memory_service.upsert_card(workspace_id, card)
        runtime.memory_service.transition_card_status(
            workspace_id,
            card.card_id,
            "active",
            reason="Route the learner into the live card first.",
        )
        pending_workspace = runtime.memory_service.record_training_practice_evaluation_result(
            workspace_id=workspace_id,
            card_id=card.card_id,
            passed=True,
            summary="Current-file verification passed the minimum dependency-injection slice.",
            next_step="Return to Coach with the verified result.",
            focus_area="dependency injection",
            evidence_source="ide_current_file",
            verified_by_evaluator=True,
        )
        handoff_id = pending_workspace["latest_training_handoff"]["handoff_id"]

        summary_before = self.client.get(f"/memory/summary?workspace_id={workspace_id}")
        self.assertEqual(summary_before.status_code, 200)
        before_payload = summary_before.json()
        evidence_before = before_payload["memory"].get("evidence_queue") or {}
        self.assertEqual(evidence_before.get("pending") or [], [])

        reflected = self.client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace_id,
                "card_id": card.card_id,
                "handoff_id": handoff_id,
                "reflection": "The current-file result proves the dependency is injected at the route boundary.",
            },
        )
        self.assertEqual(reflected.status_code, 200)
        self.assertEqual(
            reflected.json()["workspace"]["latest_training_handoff"]["return_mode"],
            "return_required",
        )

        returned = self.client.post(
            "/training/return",
            json={
                "workspace_id": workspace_id,
                "card_id": card.card_id,
                "handoff_id": handoff_id,
            },
        )
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(returned.json()["workspace"]["selected_card_status"], "implemented")

        completed_summary = self.client.get(f"/memory/summary?workspace_id={workspace_id}")
        self.assertEqual(completed_summary.status_code, 200)
        completed_evidence = completed_summary.json()["memory"].get("evidence_queue") or {}
        self.assertEqual(len(completed_evidence.get("pending") or []), 1)

        rebuilt_app = create_app(
            AppSettings(
                app_name="Trainer Rebuild Test",
                host="127.0.0.1",
                port=8765,
                data_dir=Path(runtime.repository.database_path).parent,
                database_name=Path(runtime.repository.database_path).name,
                default_session_stage="intake",
                summary_message_limit=6,
                enable_network_fetch=True,
            )
        )
        rebuilt_client = TestClient(rebuilt_app)
        rebuilt_summary = rebuilt_client.get(f"/memory/summary?workspace_id={workspace_id}")
        self.assertEqual(rebuilt_summary.status_code, 200)
        rebuilt_payload = rebuilt_summary.json()
        evidence_after = rebuilt_payload["memory"].get("evidence_queue") or {}
        pending_after = evidence_after.get("pending") or []
        self.assertEqual(len(pending_after), 1)
        self.assertEqual(pending_after[0]["source"], "training_handoff_return")
        self.assertTrue(pending_after[0]["verified"])
        self.assertEqual(pending_after[0]["verification_source"], "ide_current_file")
        self.assertEqual(pending_after[0]["source_card_id"], card.card_id)


if __name__ == "__main__":
    unittest.main()
