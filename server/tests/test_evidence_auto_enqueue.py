"""Regression coverage for verified training evidence provenance."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import LearningPlan, PlanStage, TrainingCardCandidateSnapshot, TrainingCardStatus
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService


def _make_card(
    card_id: str = "card-evidence-001",
    status: TrainingCardStatus = "active",
    card_type: str = "practice",
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

    def test_server_verified_evaluation_requires_reflect_and_return_before_evidence_credit(self) -> None:
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
        assert next_hop["why_now"] == "Return evidence was not persisted, so this card is not credited."
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
        assert self.repository.get_latest_plan(self.workspace_id).id == "plan-formal-old"

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
        assert self.repository.get_latest_plan(still_workspace).id == "plan-formal-still"
        assert still_returned["selected_card_title"] == leftover_title
        still_queue = self.service.evidence_queue(still_workspace)
        assert any(
            item.source == "training_handoff_return" and item.source_card_id == still_card.card_id
            for item in (*still_queue.pending, *still_queue.history)
        )

    def test_return_binds_pending_evidence_then_adopt_advances_training_next_without_painting_b(self) -> None:
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
        next_hop = self.service.snapshot(workspace_a).workspace.get("latest_training_next_hop") or {}
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


if __name__ == "__main__":
    unittest.main()
