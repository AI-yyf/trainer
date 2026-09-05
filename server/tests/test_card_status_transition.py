"""Tests for card status transition: state machine validation, ledger, and API endpoint."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import (
    ActiveCardSelectionResult,
    CardStatusTransitionResponse,
    EvaluationReport,
    LearningPlan,
    PlanStage,
    TrainingCardCandidateSnapshot,
    TrainingCardStatus,
    TrainingCardType,
)
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService
from app.training.handoff import HandoffStatus, TrainingHandoffGenerator, TrainingPhase


def _make_card(
    card_id: str = "card-001",
    status: TrainingCardStatus = "candidate",
    title: str = "Test Card",
    scenario_pack: str = "",
    card_type: TrainingCardType = "practice",
) -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type=card_type,
        title=title,
        status=status,
        scenario_pack=scenario_pack,
    )


class CardStatusTransitionUnitTests(unittest.TestCase):
    """Unit tests for MemoryService.transition_card_status."""

    def setUp(self) -> None:
        database_path = Path(f".tmp-test/card-transition-{id(self)}.db")
        if database_path.exists():
            database_path.unlink()
        self.repository = TrainerRepository(database_path)
        self.service = MemoryService(self.repository)
        self.workspace_id = "ws-test"

    def _seed_card(self, card: TrainingCardCandidateSnapshot) -> None:
        self.service.upsert_card(self.workspace_id, card)

    def test_valid_transition_candidate_to_active(self) -> None:
        card = _make_card(status="candidate")
        self._seed_card(card)

        result = self.service.transition_card_status(
            self.workspace_id, card.card_id, "active", reason="activated by coach"
        )

        assert isinstance(result, CardStatusTransitionResponse)
        assert result.card.status == "active"
        assert result.card.card_id == "card-001"
        assert result.ledger_entry is not None
        assert result.ledger_entry["previous_status"] == "candidate"
        assert result.ledger_entry["new_status"] == "active"
        assert result.ledger_entry["reason"] == "activated by coach"

    def test_valid_transition_active_to_answered(self) -> None:
        card = _make_card(status="active")
        self._seed_card(card)

        result = self.service.transition_card_status(
            self.workspace_id, card.card_id, "answered"
        )

        assert result.card.status == "answered"
        assert result.ledger_entry is not None
        assert result.ledger_entry["previous_status"] == "active"

    def test_active_to_implemented_requires_server_side_verification(self) -> None:
        card = _make_card(status="active")
        self._seed_card(card)

        with self.assertRaises(ValueError) as ctx:
            self.service.transition_card_status(
                self.workspace_id, card.card_id, "implemented"
            )

        assert "server-side verification" in str(ctx.exception)

    def test_verified_transition_active_to_implemented(self) -> None:
        card = _make_card(status="active")
        self._seed_card(card)

        result = self.service.transition_card_status(
            self.workspace_id,
            card.card_id,
            "implemented",
            verified_by_evaluator=True,
        )
        assert result.card.status == "implemented"

    def test_valid_transition_answered_to_reviewed(self) -> None:
        card = _make_card(status="answered", card_type="flash")
        self._seed_card(card)

        result = self.service.transition_card_status(
            self.workspace_id, card.card_id, "reviewed"
        )

        assert result.card.status == "reviewed"

    def test_practice_card_cannot_be_reviewed_without_verified_evidence(self) -> None:
        card = _make_card(status="answered", card_type="practice")
        self._seed_card(card)

        with self.assertRaises(ValueError) as ctx:
            self.service.transition_card_status(
                self.workspace_id,
                card.card_id,
                "reviewed",
            )

        assert "server-side evidence" in str(ctx.exception)

    def test_valid_transition_implemented_to_reviewed(self) -> None:
        card = _make_card(status="implemented", card_type="flash")
        self._seed_card(card)

        result = self.service.transition_card_status(
            self.workspace_id, card.card_id, "reviewed"
        )

        assert result.card.status == "reviewed"

    def test_valid_transition_reviewed_to_fed_back(self) -> None:
        card = _make_card(status="reviewed", card_type="flash")
        self._seed_card(card)

        result = self.service.transition_card_status(
            self.workspace_id, card.card_id, "fed_back"
        )

        assert result.card.status == "fed_back"

    def test_valid_transition_fed_back_to_archived(self) -> None:
        card = _make_card(status="fed_back", card_type="flash")
        self._seed_card(card)

        result = self.service.transition_card_status(
            self.workspace_id, card.card_id, "archived"
        )

        assert result.card.status == "archived"

    def test_invalid_transition_candidate_to_archived_directly(self) -> None:
        card = _make_card(status="candidate")
        self._seed_card(card)

        with self.assertRaises(ValueError) as ctx:
            self.service.transition_card_status(
                self.workspace_id, card.card_id, "archived"
            )

        assert "Invalid transition" in str(ctx.exception)
        assert "candidate" in str(ctx.exception)
        assert "archived" in str(ctx.exception)

    def test_terminal_state_rejection_archived_to_active(self) -> None:
        card = _make_card(status="archived")
        self._seed_card(card)

        with self.assertRaises(ValueError) as ctx:
            self.service.transition_card_status(
                self.workspace_id, card.card_id, "active"
            )

        assert "Invalid transition" in str(ctx.exception)
        assert "archived" in str(ctx.exception)

    def test_terminal_state_rejection_archived_to_reviewed(self) -> None:
        card = _make_card(status="archived")
        self._seed_card(card)

        with self.assertRaises(ValueError) as ctx:
            self.service.transition_card_status(
                self.workspace_id, card.card_id, "reviewed"
            )

        assert "Invalid transition" in str(ctx.exception)

    def test_invalid_transition_reviewed_to_active(self) -> None:
        card = _make_card(status="reviewed")
        self._seed_card(card)

        with self.assertRaises(ValueError) as ctx:
            self.service.transition_card_status(
                self.workspace_id, card.card_id, "active"
            )

        assert "Invalid transition" in str(ctx.exception)

    def test_card_not_found_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service.transition_card_status(
                self.workspace_id, "nonexistent-card", "active"
            )

        assert "not found" in str(ctx.exception)

    def test_ledger_entry_created(self) -> None:
        card = _make_card(card_id="card-ledger", status="candidate")
        self._seed_card(card)

        self.service.transition_card_status(
            self.workspace_id, "card-ledger", "active", reason="initial activation"
        )

        assert len(self.service._card_ledger) == 1
        entry = self.service._card_ledger[0]
        assert entry["card_id"] == "card-ledger"
        assert entry["workspace_id"] == self.workspace_id
        assert entry["previous_status"] == "candidate"
        assert entry["new_status"] == "active"
        assert entry["reason"] == "initial activation"
        assert "transitioned_at" in entry

    def test_ledger_accumulates_across_transitions(self) -> None:
        card = _make_card(card_id="card-chain", status="candidate")
        self._seed_card(card)

        self.service.transition_card_status(
            self.workspace_id, "card-chain", "active"
        )
        self.service.transition_card_status(
            self.workspace_id, "card-chain", "answered"
        )

        assert len(self.service._card_ledger) == 2
        assert self.service._card_ledger[0]["new_status"] == "active"
        assert self.service._card_ledger[1]["new_status"] == "answered"

    def test_updated_at_timestamp_set(self) -> None:
        card = _make_card(status="candidate")
        self._seed_card(card)

        result = self.service.transition_card_status(
            self.workspace_id, card.card_id, "active"
        )

        assert result.card.updated_at != ""

    def test_full_lifecycle_candidate_to_archived(self) -> None:
        card = _make_card(card_id="card-life", status="candidate", card_type="flash")
        self._seed_card(card)

        transitions = ["active", "answered", "reviewed", "fed_back", "archived"]
        for new_status in transitions:
            result = self.service.transition_card_status(
                self.workspace_id, "card-life", new_status
            )
            assert result.card.status == new_status

        assert len(self.service._card_ledger) == 5

    def test_upsert_card_updates_existing(self) -> None:
        card = _make_card(card_id="card-upsert", title="Original")
        self._seed_card(card)

        updated = _make_card(card_id="card-upsert", title="Updated", status="active")
        self._seed_card(updated)

        retrieved = self.service.get_card(self.workspace_id, "card-upsert")
        assert retrieved is not None
        assert retrieved.title == "Updated"
        assert retrieved.status == "active"

    def test_get_cards_returns_only_routable_cards(self) -> None:
        self._seed_card(_make_card(card_id="card-candidate", status="candidate"))
        self._seed_card(_make_card(card_id="card-active", status="active"))
        self._seed_card(_make_card(card_id="card-archived", status="archived"))

        cards = self.service.get_cards(self.workspace_id)

        assert [card.card_id for card in cards] == ["card-active", "card-candidate"]

    def test_persist_active_card_selection_projects_workspace_truth(self) -> None:
        card = _make_card(
            card_id="card-selected",
            status="candidate",
            title="Practice transition",
            scenario_pack="remote_workspace",
        )
        self._seed_card(card)

        persisted = self.service.persist_active_card_selection(
            self.workspace_id,
            ActiveCardSelectionResult(
                selected_card=card,
                selected_card_id=card.card_id,
                selection_score=81.2,
                why_this_card="Highest leverage next card.",
                fallback_action="Return to coach with blocker details.",
                next_after_completion="Queue next flash review.",
                candidate_count=1,
                eligible_count=1,
            ),
        )

        snapshot = self.service.snapshot(self.workspace_id)
        assert persisted.selected_card is not None
        assert persisted.selected_card.status == "active"
        assert snapshot.workspace["selected_card_id"] == "card-selected"
        assert snapshot.workspace["selected_card_status"] == "active"
        assert snapshot.active_training_card_routing is not None
        assert snapshot.active_training_card_routing.selected_card_id == "card-selected"
        assert snapshot.active_training_card_routing.why_this_card == "Highest leverage next card."
        assert snapshot.active_training_card_routing.selected_card is not None
        assert snapshot.active_training_card_routing.selected_card.scenario_pack == "remote_workspace"
        assert snapshot.workspace["latest_training_next_hop"]["selected_card_id"] == "card-selected"
        assert snapshot.workspace["latest_training_next_hop"]["scenario_pack"] == "remote_workspace"

    def test_persist_active_card_selection_preserves_needs_primer_status(self) -> None:
        card = _make_card(
            card_id="card-primer",
            status="needs_primer",
            title="Study before try",
            scenario_pack="function_guidance",
        )
        self._seed_card(card)

        persisted = self.service.persist_active_card_selection(
            self.workspace_id,
            ActiveCardSelectionResult(
                selected_card=card,
                selected_card_id=card.card_id,
                selection_score=73.4,
                why_this_card="The learner still needs the smallest concept frame.",
                fallback_action="Return to Coach with the missing rule.",
                next_after_completion="Move into the smallest real call site.",
                candidate_count=1,
                eligible_count=1,
            ),
        )

        snapshot = self.service.snapshot(self.workspace_id)
        assert persisted.selected_card is not None
        assert persisted.selected_card.status == "needs_primer"
        assert snapshot.workspace["selected_card_id"] == "card-primer"
        assert snapshot.workspace["selected_card_status"] == "needs_primer"
        assert snapshot.active_training_card_routing is not None
        assert snapshot.active_training_card_routing.selected_card is not None
        assert snapshot.active_training_card_routing.selected_card.status == "needs_primer"
        assert snapshot.active_training_card_routing.selected_card.scenario_pack == "function_guidance"

    def test_training_card_snapshot_infers_code_learning_family_from_remote_context(self) -> None:
        card = TrainingCardCandidateSnapshot(
            card_id="card-remote-family",
            title="Verify the remote workspace boundary",
            status="candidate",
            scenario_pack="remote_boundary",
            focus_area="remote workspace onboarding",
            target_skill="Explain host ownership and safe credential placement",
            problem_statement="Prove which machine owns the workspace files and whether credentials should stay local or remote.",
        )

        assert card.learning_family == "code"
        assert card.learning_subtype == "remote"

    def test_record_training_practice_result_requires_server_verification_before_implementation(self) -> None:
        card = _make_card(
            card_id="card-practice-return",
            status="active",
            title="Ground the explanation with one excerpt",
        )
        self._seed_card(card)

        blocked = self.service.record_training_practice_evaluation_result(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            passed=False,
            summary="The evidence chain is still too thin.",
            next_step="Shrink back to one sentence and one excerpt.",
            focus_area="reading inference",
            failed_checks=["Support the claim with one quoted sentence."],
            evidence_source="learner_return",
        )

        assert blocked["selected_card_status"] == "blocked"
        assert blocked["latest_training_handoff"]["return_mode"] == "blocker"
        assert blocked["latest_training_next_hop"]["status"] == "blocked"
        assert blocked["latest_learning_blocker"] == "Shrink back to one sentence and one excerpt."
        stored_blocked = self.service.get_card(self.workspace_id, card.card_id)
        assert stored_blocked is not None
        assert stored_blocked.status == "blocked"

        submitted = self.service.record_training_practice_evaluation_result(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            passed=True,
            summary="The claim is now grounded in one sentence and one quoted excerpt.",
            next_step="Return to Coach with the verified explanation.",
            focus_area="reading inference",
            evidence_source="learner_return",
        )

        assert submitted["selected_card_status"] == "active"
        assert submitted["latest_training_handoff"]["return_mode"] == "verification_required"
        assert submitted["latest_training_next_hop"]["status"] == "verification_required"
        assert submitted["latest_learning_verified_result"] == ""
        submitted_card = self.service.get_card(self.workspace_id, card.card_id)
        assert submitted_card is not None
        assert submitted_card.status == "active"

        verified = self.service.record_training_practice_evaluation_result(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            passed=True,
            summary="The claim is now grounded in one sentence and one quoted excerpt.",
            next_step="Return to Coach with the verified explanation.",
            focus_area="reading inference",
            evidence_source="ide_current_file",
            verified_by_evaluator=True,
        )

        assert verified["selected_card_status"] == "active"
        assert verified["latest_training_handoff"]["return_mode"] == "reflection_required"
        assert verified["latest_training_handoff"]["learning_phase"] == TrainingPhase.VERIFY.value
        assert verified["latest_training_handoff"]["status"] != HandoffStatus.COMPLETED.value
        assert verified["latest_training_next_hop"]["status"] == "reflection_required"
        assert verified["latest_learning_verified_result"] == ""
        stored_verified = self.service.get_card(self.workspace_id, card.card_id)
        assert stored_verified is not None
        assert stored_verified.status == "active"

        generator = TrainingHandoffGenerator()
        terminal = generator.build_handoff_record(
            card,
            {
                "correct": True,
                "evidence": ["The focused evaluator verified the quoted excerpt."],
                "evidence_source": "ide_current_file",
                "verified_by_evaluator": True,
            },
        )
        generator.record_reflection(
            terminal.handoff_id,
            "The excerpt made the inference boundary inspectable.",
        )
        generator.return_handoff(terminal.handoff_id)
        assert terminal.phase is TrainingPhase.RETURN
        assert terminal.status is HandoffStatus.COMPLETED
        self.service._structured_for(self.workspace_id).update_workspace(
            latest_training_handoff=TrainingHandoffGenerator._handoff_payload(terminal)
        )

        returned = self.service.record_training_practice_evaluation_result(
            workspace_id=self.workspace_id,
            card_id=card.card_id,
            passed=True,
            summary="The focused evaluator verified the quoted excerpt.",
            next_step="Continue with the next card.",
            focus_area="reading inference",
            evidence_source="ide_current_file",
            verified_by_evaluator=True,
        )

        assert returned["selected_card_status"] == "implemented"
        assert returned["latest_training_handoff"]["learning_phase"] == TrainingPhase.RETURN.value
        assert returned["latest_training_handoff"]["status"] == HandoffStatus.COMPLETED.value
        stored_returned = self.service.get_card(self.workspace_id, card.card_id)
        assert stored_returned is not None
        assert stored_returned.status == "implemented"


class CardStatusTransitionAPITests(unittest.TestCase):
    """Integration tests for POST /training/card-status API endpoint."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from app.core.settings import AppSettings
        from app.llm.provider_service import ProviderService
        from app.main import create_app

        self.tmp_path = Path(f".tmp-test/card-api-{id(self)}")
        self.tmp_path.mkdir(parents=True, exist_ok=True)

        settings = AppSettings(
            app_name="Trainer Test",
            host="127.0.0.1",
            port=8765,
            data_dir=self.tmp_path,
            database_name="trainer-test.db",
            default_session_stage="intake",
            summary_message_limit=6,
        )
        app = create_app(settings)
        runtime = app.state.runtime

        from app.core.models import ProviderConfig

        provider = ProviderConfig(
            name="test",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.test",
            model="gpt-4o-mini",
            capabilities={"chat": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")

        from tests.provider_fixtures import seed_verified_capabilities

        seed_verified_capabilities(runtime, provider, "sk-test", tools=False)

        self.client = TestClient(app)
        self.client.__enter__()
        self.runtime = runtime

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def _seed_card_via_service(self, workspace_id: str, card: TrainingCardCandidateSnapshot) -> None:
        self.runtime.memory_service.upsert_card(workspace_id, card)

    def test_api_valid_transition(self) -> None:
        workspace_id = "ws-api-test"
        card = _make_card(card_id="api-card-1", status="candidate")
        self._seed_card_via_service(workspace_id, card)

        response = self.client.post(
            "/training/card-status",
            json={
                "workspace_id": workspace_id,
                "card_id": "api-card-1",
                "new_status": "active",
                "reason": "coach activated",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["card"]["status"] == "active"
        assert data["ledger_entry"]["reason"] == "coach activated"

    def test_api_invalid_transition_returns_422(self) -> None:
        workspace_id = "ws-api-test"
        card = _make_card(card_id="api-card-2", status="candidate")
        self._seed_card_via_service(workspace_id, card)

        response = self.client.post(
            "/training/card-status",
            json={
                "workspace_id": workspace_id,
                "card_id": "api-card-2",
                "new_status": "archived",
            },
        )

        assert response.status_code == 422
        assert "Invalid transition" in response.json()["detail"]

    def test_api_rejects_completion_without_current_file_verification(self) -> None:
        workspace_id = "ws-api-test"
        card = _make_card(card_id="api-card-completion", status="active")
        self._seed_card_via_service(workspace_id, card)

        response = self.client.post(
            "/training/card-status",
            json={
                "workspace_id": workspace_id,
                "card_id": card.card_id,
                "new_status": "completed",
                "verified_by_evaluator": True,
            },
        )

        assert response.status_code == 422
        assert "current-file verification" in response.json()["detail"]

    def test_evidence_enqueue_ignores_client_lifecycle_and_verification_fields(self) -> None:
        response = self.client.post(
            "/evidence/enqueue",
            json={
                "workspace_id": "ws-api-test",
                "id": "client-controlled-id",
                "summary": "Learner-submitted note",
                "source": "learning_signal",
                "concepts": ["state transitions"],
                "outcome": "pass",
                "confidence": 1.0,
                "verified": True,
                "adopted": True,
                "adopted_at": "2026-01-01T00:00:00Z",
                "rejected_at": "2026-01-01T00:00:00Z",
            },
        )

        assert response.status_code == 200
        evidence = response.json()
        assert evidence["id"] != "client-controlled-id"
        assert evidence["verified"] is False
        assert evidence["adopted"] is False
        assert evidence["adopted_at"] is None
        assert evidence["rejected_at"] is None

    def test_api_card_not_found_returns_422(self) -> None:
        response = self.client.post(
            "/training/card-status",
            json={
                "workspace_id": "ws-missing",
                "card_id": "no-such-card",
                "new_status": "active",
            },
        )

        assert response.status_code == 422
        assert "not found" in response.json()["detail"]

    def test_api_terminal_state_rejection(self) -> None:
        workspace_id = "ws-api-test"
        card = _make_card(card_id="api-card-3", status="archived")
        self._seed_card_via_service(workspace_id, card)

        response = self.client.post(
            "/training/card-status",
            json={
                "workspace_id": workspace_id,
                "card_id": "api-card-3",
                "new_status": "active",
            },
        )

        assert response.status_code == 422
        assert "Invalid transition" in response.json()["detail"]

    def test_generate_card_persists_into_memory_and_summary(self) -> None:
        import json
        from unittest.mock import AsyncMock, patch

        from app.llm.provider_service import ProviderService

        workspace_id = "ws-training-generate"
        model_card_json = json.dumps(
            {
                "title": "练习：状态流转",
                "focus_area": "状态流转",
                "target_skill": "卡片路由",
                "scenario": "围绕教练发现的知识缺口做一次聚焦练习。",
                "problem_statement": "把状态流转收成一个你能逐行说明理由的短步骤。",
                "api_hints": ["先写出状态迁移表", "再实现一个转移函数"],
                "deliverable": "一段实现状态流转的代码。",
                "self_check": ["每个状态都有明确出口", "非法转移被拒绝"],
                "grading_rubric": ["状态机覆盖所有转移", "测试通过"],
                "stuck_recovery": "先在纸上画出状态图，再写代码。",
                "reflection_prompt": "哪个状态转移最容易漏掉？",
            },
            ensure_ascii=False,
        )

        with patch.object(
            ProviderService,
            "chat_completion",
            new=AsyncMock(return_value=model_card_json),
        ):
            response = self.client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "status transitions",
                    "target_skill": "card routing",
                    "response_language": "zh-CN",
                },
            )

        assert response.status_code == 200
        card = response.json()["card"]
        assert card["title"].startswith("练习")
        stored = self.runtime.memory_service.get_card(workspace_id, card["card_id"])
        assert stored is not None

        summary = self.client.get("/memory/summary", params={"workspace_id": workspace_id})
        assert summary.status_code == 200
        memory = summary.json()["memory"]
        assert memory["training_card_candidates"][0]["card_id"] == card["card_id"]
        assert memory["workspace"]["selected_card_id"] == card["card_id"]
        assert memory["workspace"]["selected_card_status"] == "active"
        assert memory["active_training_card_routing"]["selected_card_id"] == card["card_id"]
        assert len(memory["training_event_ledger"]) >= 1

    def test_generate_flash_card_does_not_reactivate_answered_practice_card(self) -> None:
        from unittest.mock import AsyncMock, patch

        from app.llm.provider_service import ProviderService

        workspace_id = "ws-training-flash-after-answer"
        answered_practice = _make_card(
            card_id="answered-practice",
            status="candidate",
            title="Practice state transition guard",
            card_type="practice",
        )
        answered_practice.focus_area = "state transition guard"
        answered_practice.target_skill = "card status routing"
        self._seed_card_via_service(workspace_id, answered_practice)
        self.runtime.memory_service.transition_card_status(
            workspace_id,
            answered_practice.card_id,
            "active",
            reason="start practice",
        )
        self.runtime.memory_service.transition_card_status(
            workspace_id,
            answered_practice.card_id,
            "answered",
            reason="practice completed",
        )

        model_card_json = json.dumps(
            {
                "title": "Flash: state transition guard",
                "why_now": "Recall the status boundary before the next training step.",
                "focus_area": "state transition guard",
                "target_skill": "card status routing",
                "knowledge_type": "engineering_concept",
                "question": "Which card statuses are eligible to become active again?",
                "context": "A completed answer should stay in review instead of being reopened.",
                "answer_mode": "text",
                "expected_answer": "Only open candidate, active, or needs_primer cards are eligible.",
                "problem_statement": "Keep answered practice cards out of the active handoff.",
                "suggested_workspace_action": "Name the eligible statuses and check the route predicate.",
                "deliverable": "A short status eligibility rule.",
                "learner_deliverables": ["The status rule"],
                "verification_steps": ["Confirm an answered card remains answered."],
                "success_signal": "The new flash card becomes active without reopening the answered practice card.",
                "reflection_prompt": "Why should answered cards remain available for review?",
                "return_with": "The status rule and the observed routing result.",
                "next_after_completion": "Continue with the next eligible card.",
                "hint_ladder": ["Separate open cards from review history."],
                "common_mistakes": ["Treating answered as active."],
                "feedback": {"correct": "The boundary is clear.", "incorrect": "Keep answered cards out of active routing."},
            }
        )

        with patch.object(
            ProviderService,
            "chat_completion",
            new=AsyncMock(return_value=model_card_json),
        ):
            response = self.client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "source": "conversation_gap",
                    "card_type": "flash",
                    "focus_area": "state transition guard",
                    "target_skill": "card status routing",
                    "response_language": "en-US",
                },
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["card"]["card_type"] == "flash"
        assert payload["active_routing"]["selected_card_id"] == payload["card"]["card_id"]
        stored_answered = self.runtime.memory_service.get_card(
            workspace_id,
            answered_practice.card_id,
        )
        assert stored_answered is not None
        assert stored_answered.status == "answered"

    def test_generate_card_from_degraded_resource_is_rejected_before_training(self) -> None:
        trainer_root = self.tmp_path / "trainer-resource-card-root"
        workspace_root = trainer_root / "degraded-resource-project"
        workspace_root.mkdir(parents=True, exist_ok=True)
        provisioning = self.runtime.provision_project_adoption(
            workspace_id="ws-training-resource-degraded",
            root_path=str(trainer_root),
            project_path=str(workspace_root),
            project_name="degraded-resource-project",
        )
        workspace_id = provisioning.context_id
        degraded_resource = self.client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "url",
                "name": "Disabled URL",
                "source": "https://example.com/degraded-training-resource",
            },
        )
        assert degraded_resource.status_code == 200
        resource = degraded_resource.json()

        indexed = self.client.post(
            "/resource/index",
            json={
                "workspace_id": workspace_id,
                "resource_id": resource["id"],
                "enable_network": True,
            },
        )
        assert indexed.status_code == 200
        indexed_payload = indexed.json()
        assert "network_disabled" in indexed_payload["quality_flags"]

        generated = self.client.post(
            "/training/generate-card",
            json={
                "workspace_id": workspace_id,
                "source": "resource_knowledge",
                "resource_id": resource["id"],
                "card_type": "flash",
                "focus_area": "network fetch boundaries",
                "target_skill": "resource trust",
            },
        )
        assert generated.status_code == 409
        assert "resource" in generated.json()["detail"].lower()
        assert self.runtime.memory_service.get_cards(workspace_id) == []

        active = self.client.get("/training/active-card", params={"workspace_id": workspace_id})
        assert active.status_code == 200
        active_payload = active.json()
        assert active_payload["selected_card_id"] is None
        assert active_payload["blocked_candidates"] == []

    def test_active_card_returns_persisted_routing_shape(self) -> None:
        workspace_id = "ws-training-active"
        card = TrainingCardCandidateSnapshot(
            card_id="route-card-1",
            title="Practice route truth",
            card_type="practice",
            focus_area="routing",
            target_skill="state sync",
            problem_statement="Make active routing truthful.",
            deliverable="A persisted selected card.",
            validation_method="Summary reflects selected card.",
            source_chain=["manual"],
            status="candidate",
        )
        self._seed_card_via_service(workspace_id, card)
        self.runtime.memory_service.persist_active_card_selection(
            workspace_id,
            ActiveCardSelectionResult(
                selected_card=card,
                selected_card_id=card.card_id,
                selection_score=88.0,
                why_this_card="Only eligible practice card.",
                fallback_action="Return to coach with the exact blocker.",
                next_after_completion="Record evidence and route the next card.",
                candidate_count=1,
                eligible_count=1,
            ),
        )

        response = self.client.get("/training/active-card", params={"workspace_id": workspace_id})

        assert response.status_code == 200
        data = response.json()
        assert data["selected_card_id"] == "route-card-1"
        assert data["selected_card"]["card_id"] == "route-card-1"
        assert data["why_this_card"] != ""
        assert data["candidate_count"] == 1
        assert data["eligible_count"] == 1

    def test_api_practice_return_updates_workspace_truth(self) -> None:
        workspace_id = "ws-training-return"
        card = _make_card(card_id="api-practice-return", status="active", title="Verify one explanation")
        self._seed_card_via_service(workspace_id, card)

        blocked = self.client.post(
            "/training/practice-return",
            json={
                "workspace_id": workspace_id,
                "card_id": card.card_id,
                "passed": False,
                "summary": "The explanation still skips the key step.",
                "next_step": "Shrink back to one step and re-check it.",
                "focus_area": "derivation",
                "failed_checks": ["State the rule used in the key step."],
                "evidence_source": "learner_return",
            },
        )

        assert blocked.status_code == 200
        blocked_payload = blocked.json()["workspace"]
        assert blocked_payload["selected_card_status"] == "blocked"
        assert blocked_payload["latest_training_handoff"]["return_mode"] == "blocker"
        assert blocked_payload["latest_training_next_hop"]["status"] == "blocked"

        submitted = self.client.post(
            "/training/practice-return",
            json={
                "workspace_id": workspace_id,
                "card_id": card.card_id,
                "passed": True,
                "summary": "The derivation now names the rule and closes with a substitution check.",
                "next_step": "Return to Coach with the verified step.",
                "focus_area": "derivation",
                "evidence_source": "learner_return",
            },
        )

        assert submitted.status_code == 200
        submitted_payload = submitted.json()["workspace"]
        assert submitted_payload["selected_card_status"] == "active"
        assert submitted_payload["latest_training_handoff"]["return_mode"] == "verification_required"
        assert submitted_payload["latest_training_next_hop"]["status"] == "verification_required"

    def test_training_evaluation_with_an_unknown_card_does_not_write_completion_state(self) -> None:
        workspace_id = "ws-training-unknown-card"
        self.runtime.evaluator_service.evaluate_current_file = lambda _request, _task, **_kwargs: EvaluationReport(
            summary="Current-file verification passed.",
            next_step="Return to Coach.",
            passed=True,
        )
        session = self.client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert session.status_code == 200

        evaluated = self.client.post(
            "/evaluate/current-file",
            json={
                "session_id": session.json()["session_id"],
                "workspace_id": workspace_id,
                "language_id": "python",
                "file_path": str(self.tmp_path / "unknown_card.py"),
                "content": "def ok() -> bool:\n    return True\n",
                "diagnostics": [],
                "evaluation_source": "training",
                "training_card_id": "missing-card",
                "training_card_title": "Missing card",
            },
        )

        assert evaluated.status_code == 200
        summary = self.client.get("/memory/summary", params={"workspace_id": workspace_id})
        assert summary.status_code == 200
        workspace = summary.json()["memory"]["workspace"]
        assert workspace.get("selected_card_id", "") != "missing-card"
        assert workspace.get("selected_card_status", "") != "implemented"

    def test_learning_signal_success_does_not_advance_a_formal_plan(self) -> None:
        workspace_id = "ws-learning-signal-unverified"
        session = self.client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert session.status_code == 200
        self.runtime.repository.save_plan(
            workspace_id,
            LearningPlan(
                id="plan-learning-signal-unverified",
                title="Evidence-bound plan",
                stages=[
                    PlanStage(
                        id="stage-1",
                        title="Foundation",
                        goal="Prove the first slice",
                        outcomes=["state transitions"],
                        status="active",
                    ),
                    PlanStage(
                        id="stage-2",
                        title="Practice",
                        goal="Practice the next slice",
                        outcomes=["integration testing"],
                        status="pending",
                    ),
                ],
                current_stage_id="stage-1",
            ),
        )

        signal = self.client.post(
            "/learning/signal",
            json={
                "session_id": session.json()["session_id"],
                "workspace_id": workspace_id,
                "concepts": ["state transitions"],
                "outcome": "tests_passed",
                "summary": "A learner-reported test result.",
                "verified_result": "Client-provided success text.",
            },
        )

        assert signal.status_code == 200
        saved = self.runtime.repository.get_latest_plan(workspace_id)
        assert saved is not None
        assert saved.current_stage_id == "stage-1"
        evidence = self.runtime.memory_service.evidence_queue(workspace_id).pending[-1]
        assert evidence.outcome == "partial"


    def test_api_duplicate_request_id_applies_card_status_once(self) -> None:
        workspace_id = "ws-api-card-status-idempotent"
        card = _make_card(card_id="api-card-idempotent-1", status="candidate")
        self._seed_card_via_service(workspace_id, card)
        request_id = "training-persistence-card-status-1"
        payload = {
            "workspace_id": workspace_id,
            "card_id": "api-card-idempotent-1",
            "new_status": "active",
            "reason": "coach activated",
            "request_id": request_id,
            "idempotency_key": request_id,
        }

        first = self.client.post("/training/card-status", json=payload)
        second = self.client.post("/training/card-status", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["card"]["status"] == "active"
        assert second.json()["card"]["status"] == "active"
        ledger = [
            entry
            for entry in self.runtime.memory_service._card_ledger
            if entry.get("card_id") == "api-card-idempotent-1"
            and entry.get("workspace_id") == workspace_id
        ]
        assert len(ledger) == 1
        reliability = self.runtime.memory_service.latest_training_reliability(workspace_id)
        assert reliability is not None
        assert reliability["request_id"] == request_id
        assert reliability["phase"] == "acked"


if __name__ == "__main__":
    unittest.main()
