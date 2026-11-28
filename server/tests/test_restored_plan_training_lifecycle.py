"""(q) Plan and training lifecycle: plans, tasks, cards and handoffs move only
    through their explicit transitions and stay bound to the live plan and workspace.

Guarantees covered:
  * formal plans mutate only under optimistic locking and never from a leftover;
  * live-plan gates on task tools, task specification and plan updates fail closed;
  * training cards change status only through valid transitions and stay workspace-bound;
  * handoffs, returns, reflections and attestations record only what really happened;
  * card generation retries once, stays honest on provider failure, and never invents facts.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_card_status_transition.py
  * server/tests/test_card_acceptance_criteria.py
  * server/tests/test_card_taxonomy.py
  * server/tests/test_planner_properties.py
  * server/tests/test_course_pack.py
  * server/tests/test_training_handoff.py
  * server/tests/test_dependency_skill_maps.py
  * server/tests/test_training_reliability.py
  * server/tests/test_training_actions.py
  * server/tests/test_training_expression_acceptance.py
  * server/tests/test_transfer_skills.py
  * server/tests/test_training_return_feedback.py
  * server/tests/test_training_attempts.py
  * server/tests/test_flashcard_cjk_grading.py
  * server/tests/test_growth_loop_honesty.py
  * server/tests/test_plan_update_live_plan_gate.py
  * server/tests/test_training_review_context.py
  * server/tests/test_training_skill_evidence.py
  * server/tests/test_task_tool_live_plan_gate.py
  * server/tests/test_training_runtime_handoff.py
  * server/tests/test_formal_plan_stage_constraints.py
  * server/tests/test_plan_change_candidates.py
  * server/tests/test_write_tool_implicit_activation.py
  * server/tests/test_training_plan_binding.py
  * server/tests/test_training_card_implicit_activation.py
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.api.training_return_feedback import completed_return_feedback
from app.core.models import (
    ActiveCardSelectionResult,
    CardGenerationContext,
    CardStatusTransitionResponse,
    LearningPlan,
    MemorySnapshot,
    PlanStage,
    ResourceRecord,
    ReviewArtifactSnapshot,
    TrainingCardCandidateSnapshot,
    TrainingCardStatus,
    TrainingCardType,
    UserProfile,
)
from app.core.settings import AppSettings
from app.db.repository import TrainerRepository
from app.evaluator.service import EvaluatorService
from app.evaluator.verifiers import verifier_pack_for
from app.llm.coaching_patches import _practice_verification_requested_or_claimed
from app.llm.prompts import build_coaching_system_prompt
from app.llm.provider_service import _build_agent_tool_context_extra
from app.llm.tools import _explicit_formal_plan_stage_count
from app.llm.training_review_context import active_training_review, apply_training_review_context
from app.main import create_app
from app.memory.models import MasteryRecord, WeaknessRecord, utc_now
from app.memory.note_request import message_requests_explicit_learning_note
from app.memory.service import MemoryService
from app.memory.transfer_skills import (
    apply_transfer_skill_to_coach_orientation,
    build_transfer_skill_state_record,
    resolve_skill_scene_key,
    should_promote_transferable_skill,
)
from app.memory.workspace_recovery import PLAN_RUNTIME_KEY, leftover_formal_plan_is_live_for_fill
from app.planner import NextTaskContext, TrainingPlannerService
from app.planner.models import TaskDifficulty
from app.training.attempt_store import AttemptStore, content_hash
from app.training.card_generator import (
    CardGenerationService,
    _build_prompt,
    derive_acceptance_criteria,
)
from app.training.card_request import message_requests_explicit_training_card
from app.training.course_pack import (
    COURSE_MANIFEST_TYPE,
    COURSE_MANIFEST_VERSION,
    build_course_manifest,
    inspect_course_manifest,
)
from app.training.handoff import (
    EvidenceRecord,
    HandoffStatus,
    ProjectHandoff,
    TrainingHandoffContent,
    TrainingHandoffGenerator,
    TrainingPhase,
)
from app.training.plan_binding import validated_mint_binding
from app.training.reliability import (
    begin_record,
    can_transition,
    expire_if_needed,
    mark_executing,
    mark_succeeded,
    recover_record,
    request_cancel,
    should_coalesce,
    should_replay,
    transition,
)
from app.training.skill_projection import project_skills
from app.training.subject_taxonomy import classify_learning_subject, verifier_subject_family
from tests.client_fixtures import build_client

# ---------------------------------------------------------------------------
# Restored from test_card_status_transition.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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
        database_path = Path(f".tmp-test/card-transition-{uuid4().hex}.db")
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

    def test_transitioning_selected_card_syncs_active_routing_snapshot(self) -> None:
        card = _make_card(card_id="card-routing-sync", status="candidate", card_type="practice")
        self._seed_card(card)
        self.service.persist_active_card_selection(
            self.workspace_id,
            ActiveCardSelectionResult(
                selected_card=card,
                selected_card_id=card.card_id,
                selection_score=70.0,
                why_this_card="Current card.",
                fallback_action="Return to coach.",
                next_after_completion="Queue next card.",
                candidate_count=1,
                eligible_count=1,
            ),
        )
        # persist_active_card_selection already lands the card on `active`.
        self.service.transition_card_status(
            self.workspace_id, card.card_id, "answered", reason="Learner submitted evidence."
        )
        snapshot = self.service.snapshot(self.workspace_id)
        routing = snapshot.active_training_card_routing
        assert routing is not None
        assert routing.selected_card is not None
        assert routing.selected_card.status == "answered"

        self.service.transition_card_status(
            self.workspace_id,
            card.card_id,
            "implemented",
            reason="Return completed with persisted evidence.",
            verified_by_evaluator=True,
        )
        snapshot = self.service.snapshot(self.workspace_id)
        routing = snapshot.active_training_card_routing
        assert routing is not None
        assert routing.selected_card is not None
        assert routing.selected_card.status == "implemented"

    def test_snapshot_reconciles_stale_active_routing_status(self) -> None:
        card = _make_card(card_id="card-stale-routing", status="implemented", card_type="practice")
        self._seed_card(card)
        structured = self.service._structured_for(self.workspace_id)
        stale = card.model_copy(update={"status": "active", "learning_phase": "verify"})
        structured._active_training_card_routing = ActiveCardSelectionResult(
            selected_card=stale,
            selected_card_id=card.card_id,
            selection_score=70.0,
            why_this_card="Current card.",
            fallback_action="Return to coach.",
            next_after_completion="Queue next card.",
            candidate_count=1,
            eligible_count=1,
        )

        snapshot = self.service.snapshot(self.workspace_id)
        routing = snapshot.active_training_card_routing
        assert routing is not None
        assert routing.selected_card is not None
        assert routing.selected_card.status == "implemented"

    def test_active_learn_card_start_advances_to_try(self) -> None:
        card = _make_card(card_id="card-start", status="active", card_type="practice")
        card = card.model_copy(update={"learning_phase": "learn"})
        self._seed_card(card)

        result = self.service.transition_card_status(
            self.workspace_id, card.card_id, "active", reason="start_step"
        )

        assert result.card.status == "active"
        assert result.card.learning_phase == "try"

    def test_active_to_active_without_start_reason_still_fails(self) -> None:
        card = _make_card(card_id="card-start-invalid", status="active")
        self._seed_card(card)

        with self.assertRaises(ValueError):
            self.service.transition_card_status(
                self.workspace_id, card.card_id, "active", reason="other"
            )

    def test_skipping_selected_card_releases_live_selection(self) -> None:
        card = _make_card(card_id="card-skip", status="candidate", card_type="practice")
        self._seed_card(card)
        self.service.persist_active_card_selection(
            self.workspace_id,
            ActiveCardSelectionResult(
                selected_card=card,
                selected_card_id=card.card_id,
                selection_score=70.0,
                why_this_card="Current card.",
                fallback_action="Return to coach.",
                next_after_completion="Queue next card.",
                candidate_count=1,
                eligible_count=1,
            ),
        )

        structured = self.service._structured_for(self.workspace_id)
        structured.update_workspace(
            latest_training_handoff={
                "card_id": "card-skip",
                "candidate_id": "card-skip",
                "handoff_status": "needs_verification",
            }
        )
        self.service.transition_card_status(
            self.workspace_id, "card-skip", "skipped", reason="Learner skipped"
        )

        snapshot = self.service.snapshot(self.workspace_id)
        assert snapshot.workspace["selected_card_id"] == ""
        assert snapshot.workspace["selected_card_status"] == ""
        assert snapshot.active_training_card_routing is None
        assert not snapshot.workspace.get("latest_training_next_hop")
        assert not snapshot.workspace.get("latest_training_handoff")
        assert self.service.get_card(self.workspace_id, "card-skip").status == "skipped"

    def test_skipping_unselected_card_keeps_live_selection(self) -> None:
        selected = _make_card(card_id="card-keep", status="candidate")
        other = _make_card(card_id="card-other", status="candidate")
        self._seed_card(selected)
        self._seed_card(other)
        self.service.persist_active_card_selection(
            self.workspace_id,
            ActiveCardSelectionResult(
                selected_card=selected,
                selected_card_id=selected.card_id,
                selection_score=70.0,
                why_this_card="Current card.",
                fallback_action="Return to coach.",
                next_after_completion="Queue next card.",
                candidate_count=2,
                eligible_count=2,
            ),
        )

        self.service.transition_card_status(
            self.workspace_id, "card-other", "skipped", reason="Learner skipped"
        )

        snapshot = self.service.snapshot(self.workspace_id)
        assert snapshot.workspace["selected_card_id"] == "card-keep"
        assert snapshot.active_training_card_routing is not None
        assert snapshot.active_training_card_routing.selected_card_id == "card-keep"
        assert snapshot.workspace["latest_training_next_hop"]["selected_card_id"] == "card-keep"

    def test_snapshot_hides_legacy_terminal_selected_card(self) -> None:
        card = _make_card(card_id="card-legacy-skip", status="candidate")
        self._seed_card(card)
        self.service.persist_active_card_selection(
            self.workspace_id,
            ActiveCardSelectionResult(
                selected_card=card,
                selected_card_id=card.card_id,
                selection_score=70.0,
                why_this_card="Current card.",
                fallback_action="Return to coach.",
                next_after_completion="Queue next card.",
                candidate_count=1,
                eligible_count=1,
            ),
        )
        structured = self.service._structured_for(self.workspace_id)
        structured._training_cards[card.card_id] = card.model_copy(
            update={"status": "skipped"}
        )
        structured.update_workspace(
            latest_training_handoff={
                "card_id": card.card_id,
                "candidate_id": card.card_id,
                "handoff_status": "needs_verification",
            }
        )

        snapshot = self.service.snapshot(self.workspace_id)

        assert snapshot.workspace["selected_card_id"] == ""
        assert snapshot.active_training_card_routing is None
        assert snapshot.workspace.get("latest_training_next_hop") in (None, {})
        assert snapshot.workspace.get("latest_training_handoff") in (None, {})

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


    def test_skipped_selected_card_is_not_live(self) -> None:
        card = _make_card(card_id="card-stale-skip", status="skipped")
        self._seed_card(card)
        self.service.update_workspace_state(
            self.workspace_id, selected_card_id=card.card_id
        )
        assert self.service.live_selected_training_card_id(self.workspace_id) == ""

    def test_skipped_card_handoff_owner_is_not_live(self) -> None:
        card = _make_card(card_id="card-stale-handoff", status="skipped")
        self._seed_card(card)
        structured = self.service._structured_for(self.workspace_id)
        structured.update_workspace(
            latest_training_handoff={
                "card_id": card.card_id,
                "candidate_id": card.card_id,
                "handoff_id": "handoff-stale",
                "learning_phase": "try",
                "status": "generated",
            }
        )
        assert self.service._training_handoff_owner_card_id(self.workspace_id) == ""


# ---------------------------------------------------------------------------
# Restored from test_card_acceptance_criteria.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*")


_CODE_SYMBOL_PATTERN = re.compile(
    r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*"
    r"(?:\s*\.\s*[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*)*"
)


def _normalize_code_symbol(value: str) -> str | None:
    normalized = value.strip().strip("`").strip()
    normalized = re.sub(r"\(\s*\)$", "", normalized)
    if not normalized or _CODE_SYMBOL_PATTERN.fullmatch(normalized) is None:
        return None
    return re.sub(r"\s*\.\s*", ".", normalized)


def _criterion_code_signals(criterion: str) -> list[str]:
    """Mirror ``_criterion_code_signals`` from the sidecar evaluator."""
    signals: list[str] = []
    for literal in re.findall(r"`([^`]+)`", criterion):
        normalized = _normalize_code_symbol(literal)
        if normalized and normalized not in signals:
            signals.append(normalized)
    for token in _IDENTIFIER_PATTERN.findall(criterion):
        if "_" in token or (
            token[0].islower() and any(character.isupper() for character in token[1:])
        ):
            if token not in signals:
                signals.append(token)
    return signals


def assert_symbol_anchored(test: unittest.TestCase, criteria: list[str]) -> None:
    """Requirement (d): every criterion matches the evaluator signal rule."""
    test.assertGreaterEqual(len(criteria), 3)
    test.assertLessEqual(len(criteria), 5)
    for criterion in criteria:
        test.assertTrue(
            _criterion_code_signals(criterion),
            f"criterion has no verifiable code symbol: {criterion!r}",
        )


def assert_backticked(test: unittest.TestCase, criteria: list[str]) -> None:
    for criterion in criteria:
        test.assertIn("`", criterion, f"criterion lacks a backticked symbol: {criterion!r}")


def _ctx(**overrides: Any) -> CardGenerationContext:
    defaults: dict[str, Any] = {
        "workspace_id": "ws-acceptance",
        "source": "conversation_gap",
        "card_type": "practice",
        "focus_area": "async concurrency",
        "target_skill": "使用 asyncio.gather 并发执行三个协程",
    }
    defaults.update(overrides)
    return CardGenerationContext(**defaults)


def _practice_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Practice: asyncio.gather concurrency",
        "focus_area": "async concurrency",
        "target_skill": "使用 asyncio.gather 并发执行三个协程",
        "scenario": "在真实脚本里并发调度三个协程并收集结果。",
        "problem_statement": "使用 asyncio.gather 并发执行三个协程并汇总返回值。",
        "api_hints": ["先写一个 async def 协程", "用 asyncio.run 启动入口"],
        "deliverable": "一个使用 asyncio.gather 并发执行三个协程的脚本，入口为 main。",
        "self_check": ["三个协程是否真的并发运行了？", "结果顺序是否符合预期？"],
        "grading_rubric": ["使用 asyncio.gather 调度三个协程", "通过 asyncio.run 启动 main"],
        "stuck_recovery": "先回到只有一个协程的最小示例。",
        "reflection_prompt": "哪一个 await 点让并发真正发生了？",
    }
    payload.update(overrides)
    return payload


def _flash_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Flash: asyncio.gather",
        "why_now": "对话中发现了关于并发的知识缺口。",
        "focus_area": "async concurrency",
        "target_skill": "使用 asyncio.gather 并发执行三个协程",
        "knowledge_type": "engineering_concept",
        "question": "asyncio.gather 的返回值是什么？",
        "answer_mode": "text",
        "expected_answer": "一个按传入顺序聚合各协程结果的 future。",
        "problem_statement": "说明 asyncio.gather 的聚合行为。",
        "learner_deliverables": ["一段说明 gather 返回值的文字"],
        "verification_steps": ["对照官方文档核对返回值顺序"],
        "success_signal": "能准确说出 gather 的聚合顺序。",
        "reflection_prompt": "gather 和 wait 的区别是什么？",
        "return_with": "带着你的解释和一个例子回来。",
        "next_after_completion": "回到练习卡验证并发行为。",
        "hint_ladder": ["想想 gather 接受什么参数", "再想它如何聚合结果"],
        "common_mistakes": ["把 gather 和 create_task 混为一谈"],
        "feedback": {"correct": "很好。", "incorrect": "再查一下文档。"},
    }
    payload.update(overrides)
    return payload


class _FakeProvider:
    """Returns one canned JSON payload, like a real chat completion would."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    async def chat_completion(self, messages: Any, **kwargs: Any) -> str:
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)


class TestLlmAcceptanceCriteria(unittest.TestCase):
    """LLM path: keep verifiable criteria, synthesize missing/invalid ones."""

    def test_valid_llm_criteria_are_preserved(self) -> None:
        criteria = [
            "使用 `asyncio.gather` 并发执行三个协程",
            "定义 `main` 入口并通过 `asyncio.run` 启动",
            "通过 `fetch_all` 收集全部结果",
        ]
        provider = _FakeProvider(_practice_payload(acceptance_criteria=criteria))
        card = CardGenerationService(provider_service=provider).generate_card(
            "conversation_gap",
            _ctx(),
        )
        self.assertEqual(provider.calls, 1)
        self.assertEqual(card.acceptance_criteria, criteria)
        assert_symbol_anchored(self, card.acceptance_criteria)

    def test_invalid_llm_criteria_are_replaced(self) -> None:
        provider = _FakeProvider(
            _practice_payload(
                acceptance_criteria=[
                    "解释并发的好处",
                    "run things concurrently without symbols",
                ]
            )
        )
        card = CardGenerationService(provider_service=provider).generate_card(
            "conversation_gap",
            _ctx(),
        )
        self.assertGreaterEqual(len(card.acceptance_criteria), 3)
        assert_symbol_anchored(self, card.acceptance_criteria)
        # Synthesized items are backticked and the free-form prose is gone.
        assert_backticked(self, card.acceptance_criteria)
        self.assertNotIn("解释并发的好处", card.acceptance_criteria)
        self.assertNotIn("run things concurrently without symbols", card.acceptance_criteria)

    def test_missing_llm_criteria_are_synthesized(self) -> None:
        provider = _FakeProvider(_practice_payload())
        card = CardGenerationService(provider_service=provider).generate_card(
            "conversation_gap",
            _ctx(),
        )
        self.assertGreaterEqual(len(card.acceptance_criteria), 3)
        assert_symbol_anchored(self, card.acceptance_criteria)
        assert_backticked(self, card.acceptance_criteria)

    def test_partial_llm_criteria_keep_valid_items_and_top_up(self) -> None:
        kept = "使用 `asyncio.gather` 并发执行三个协程"
        provider = _FakeProvider(
            _practice_payload(
                acceptance_criteria=[
                    kept,
                    "没有符号的自由发挥",
                ]
            )
        )
        card = CardGenerationService(provider_service=provider).generate_card(
            "plan_requirement",
            _ctx(source="plan_requirement"),
        )
        self.assertEqual(card.acceptance_criteria[0], kept)
        self.assertGreaterEqual(len(card.acceptance_criteria), 3)
        assert_symbol_anchored(self, card.acceptance_criteria)
        assert_backticked(self, card.acceptance_criteria)

    def test_stream_payload_builder_normalizes_criteria(self) -> None:
        service = CardGenerationService()
        card = service._build_card_from_llm_data(
            _practice_payload(
                acceptance_criteria=["自由发挥没有符号"],
            ),
            _ctx(),
            "conversation_gap",
            "practice",
        )
        self.assertIsInstance(card, TrainingCardCandidateSnapshot)
        assert card is not None
        assert_symbol_anchored(self, card.acceptance_criteria)
        assert_backticked(self, card.acceptance_criteria)

    def test_flash_llm_card_receives_criteria(self) -> None:
        provider = _FakeProvider(_flash_payload())
        card = CardGenerationService(provider_service=provider).generate_card(
            "conversation_gap",
            _ctx(card_type="flash"),
        )
        self.assertEqual(card.card_type, "flash")
        self.assertGreaterEqual(len(card.acceptance_criteria), 3)
        assert_symbol_anchored(self, card.acceptance_criteria)


class TestFallbackAcceptanceCriteria(unittest.TestCase):
    """Deterministic template cards must always carry symbol-anchored criteria."""

    def test_all_sources_practice_fallback(self) -> None:
        service = CardGenerationService()
        for source in (
            "conversation_gap",
            "plan_requirement",
            "resource_knowledge",
            "practice_feedback",
            "dependency_mastery",
            "review_due",
            "unknown_source",
        ):
            with self.subTest(source=source):
                card = service.generate_card(
                    source,
                    _ctx(source=source, card_type="practice"),
                    allow_llm=False,
                )
                self.assertEqual(card.card_type, "practice")
                assert_symbol_anchored(self, card.acceptance_criteria)
                assert_backticked(self, card.acceptance_criteria)

    def test_fallback_without_extractable_symbols_still_valid(self) -> None:
        service = CardGenerationService()
        card = service.generate_card(
            "conversation_gap",
            _ctx(focus_area="法国文学赏析", target_skill="法国自然主义文学的特点"),
            allow_llm=False,
        )
        assert_symbol_anchored(self, card.acceptance_criteria)
        assert_backticked(self, card.acceptance_criteria)

    def test_chinese_fallback_criteria_are_chinese_formatted(self) -> None:
        service = CardGenerationService()
        card = service.generate_card(
            "conversation_gap",
            _ctx(response_language="zh-CN"),
            allow_llm=False,
        )
        assert_symbol_anchored(self, card.acceptance_criteria)
        joined = " ".join(card.acceptance_criteria)
        self.assertTrue(
            any(criterion.startswith(("使用 `", "定义 `", "通过 `")) for criterion in card.acceptance_criteria),
            f"expected zh-CN criterion patterns, got: {joined}",
        )


class TestDeriveAcceptanceCriteria(unittest.TestCase):
    """Module-level helper used by fallbacks and the LLM synthesizer."""

    def test_derives_symbols_from_deliverable_and_rubric(self) -> None:
        criteria = derive_acceptance_criteria(
            "一个使用 asyncio.gather 并发执行三个协程的脚本",
            ["通过 asyncio.run 启动 main"],
            "使用 asyncio.gather 并发执行三个协程",
        )
        self.assertGreaterEqual(len(criteria), 3)
        self.assertLessEqual(len(criteria), 5)
        assert_symbol_anchored(self, criteria)
        self.assertTrue(any("`asyncio.gather`" in criterion for criterion in criteria))

    def test_chinese_formatting(self) -> None:
        criteria = derive_acceptance_criteria(
            "使用 httpx_client 重试失败请求",
            [],
            "httpx_client 重试",
            language="zh-CN",
        )
        self.assertGreaterEqual(len(criteria), 3)
        assert_symbol_anchored(self, criteria)
        self.assertTrue(criteria[0].startswith("使用 `httpx_client`"), criteria[0])

    def test_no_symbols_falls_back_to_generic_backticked_items(self) -> None:
        criteria = derive_acceptance_criteria("纯粹的文字说明", ["自由写作"], "散文赏析")
        self.assertGreaterEqual(len(criteria), 3)
        assert_symbol_anchored(self, criteria)
        assert_backticked(self, criteria)


class TestPromptAndSignalContract(unittest.TestCase):
    """The prompt must request backticked criteria; the mini-check must bite."""

    def test_prompt_requests_acceptance_criteria(self) -> None:
        prompt = _build_prompt(_ctx(), "conversation_gap", "practice")
        self.assertIn("acceptance_criteria", prompt)
        self.assertIn("3-5", prompt)
        self.assertIn("使用 `symbol`", prompt)
        self.assertIn("backtick", prompt)

    def test_free_form_chinese_criterion_has_no_signal(self) -> None:
        # Sanity: the mini-check really mirrors the evaluator's rejection of
        # free-form prose criteria.
        self.assertEqual(_criterion_code_signals("解释并发的好处并举例"), [])
        self.assertEqual(_criterion_code_signals("Run it and see"), [])

    def test_snake_and_camel_identifiers_count_as_signals(self) -> None:
        self.assertIn("fetch_all", _criterion_code_signals("实现 fetch_all 並回傳結果"))
        self.assertIn("fetchPage", _criterion_code_signals("fetchPage returns the payload"))


# ---------------------------------------------------------------------------
# Restored from test_card_taxonomy.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_implementation_card_without_files_downgrades_to_reading() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="Confirm the project purpose",
        learning_family="code",
        learning_subtype="implementation",
        files_to_touch=[],
    )

    assert card.learning_subtype == "reading"


def test_implementation_card_with_a_concrete_file_stays_implementation() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="Add a boundary test",
        learning_family="code",
        learning_subtype="implementation",
        files_to_touch=["src/queue_lock.py"],
    )

    assert card.learning_subtype == "implementation"


def test_placeholder_file_targets_do_not_count_as_concrete_files() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="Fill the implementation",
        learning_family="code",
        learning_subtype="implementation",
        files_to_touch=["<current failing file>"],
    )

    assert card.learning_subtype == "reading"


def test_files_to_touch_normalizes_markdown_and_keeps_concrete_target() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="Check lock boundary",
        learning_family="code",
        learning_subtype="implementation",
        files_to_touch=["`queue_lock.py`", " src/queue_lock.py ", "`queue_lock.py`"],
    )

    assert card.files_to_touch == ["queue_lock.py", "src/queue_lock.py"]
    assert card.learning_subtype == "implementation"


def test_markdown_wrapped_placeholder_still_downgrades_to_reading() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="Fill the implementation",
        learning_family="code",
        learning_subtype="implementation",
        files_to_touch=["`<current failing file>`"],
    )

    assert card.files_to_touch == ["<current failing file>"]
    assert card.learning_subtype == "reading"


def test_analysis_card_with_file_downgrades_to_reading() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="梳理 queue_lock.py 的加锁边界",
        learning_family="code",
        learning_subtype="function",
        files_to_touch=["queue_lock.py"],
        problem_statement="聚焦第 1-41 行，记录锁相关符号和调用点。不要先改生产代码。",
    )

    assert card.learning_subtype == "reading"


def test_implementation_card_with_change_verb_stays_implementation() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="为 Queue 增加受锁保护的快照",
        learning_family="code",
        learning_subtype="implementation",
        files_to_touch=["queue_lock.py"],
        problem_statement="实现 snapshot，返回副本。",
    )

    assert card.learning_subtype == "implementation"


def test_supplement_or_optimize_keeps_implementation() -> None:
    for title, statement in (
        ("检查 queue_lock.py 中的竞态并补充回归测试", "补充回归测试。"),
        ("分析 Queue 的锁设计并优化临界区", "优化临界区。"),
    ):
        card = TrainingCardCandidateSnapshot(
            card_type="practice",
            title=title,
            learning_family="code",
            learning_subtype="implementation",
            files_to_touch=["queue_lock.py"],
            problem_statement=statement,
        )
        assert card.learning_subtype == "implementation", title


def test_file_target_wrapped_in_prose_keeps_only_the_file() -> None:
    """A real-model card put a whole sentence in ``files_to_touch``.

    The entry was shown to the learner as the target file, and host
    verification refused every real artifact because its name never matched
    that "target".
    """
    for raw, expected in (
        ("ppo_clip_exercise.py（建议新建，具体路径由学习者选择）", "ppo_clip_exercise.py"),
        ("foo.py (create it)", "foo.py"),
        ("新建 foo.py", "foo.py"),
        ("src/app.py 的入口", "src/app.py"),
        ("My Project/app.py", "My Project/app.py"),
        ("C:\\work\\demo\\app.py", "C:/work/demo/app.py"),
        ("Dockerfile", "Dockerfile"),
        ("src/queue_lock.py:12", "src/queue_lock.py:12"),
    ):
        card = TrainingCardCandidateSnapshot(card_type="practice", files_to_touch=[raw])
        assert card.files_to_touch == [expected], raw


def test_prose_without_a_file_is_not_a_file_target() -> None:
    for raw in (
        "具体路径由学习者选择",
        "main entry point",
        "一个新建的文件",
        "Edit the module you prefer",
        "新建一个练习文件，验证裁剪行为。",
    ):
        card = TrainingCardCandidateSnapshot(
            card_type="practice",
            title="Implement the boundary",
            learning_family="code",
            learning_subtype="implementation",
            files_to_touch=[raw],
        )
        assert card.files_to_touch == [], raw
        assert card.learning_subtype == "reading", raw


def test_symbols_the_card_presents_as_alternatives_are_not_both_required() -> None:
    """A real-model card hinted "`torch.minimum`（或 `torch.min`）" and then
    listed both as expected symbols; a correct torch.minimum implementation
    failed on torch.min."""
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        acceptance_criteria=[
            "定义 `ppo_clip_loss`，用 `torch.minimum` 逐元素取两个代理目标的较小值。",
        ],
        api_hints=["`torch.minimum`（或双 tensor 形式的 `torch.min`）：逐元素取较小值。"],
        expected_symbols=["ppo_clip_loss", "torch.minimum", "torch.min"],
    )

    assert card.expected_symbols == ["ppo_clip_loss", "torch.minimum"]


def test_symbols_never_presented_as_alternatives_stay_required() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        acceptance_criteria=["用 `torch.min` 求最小值，再用 `torch.maximum` 取上界。"],
        api_hints=["`torch.clamp` 把 `ratio` 限制在 `[1 - epsilon, 1 + epsilon]`。"],
        expected_symbols=["torch.min", "torch.maximum", "torch.clamp"],
    )

    assert card.expected_symbols == ["torch.min", "torch.maximum", "torch.clamp"]


# ---------------------------------------------------------------------------
# Restored from test_planner_properties.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


# Custom strategies for generating test data
@st.composite
def valid_weekly_hours(draw):
    """Generate valid weekly hours (1-40)."""
    return draw(st.integers(min_value=1, max_value=40))


@st.composite
def valid_goal(draw):
    """Generate a valid learning goal string."""
    words = draw(st.lists(
        st.text(min_size=2, max_size=15, alphabet=st.characters(whitelist_categories=('Ll', 'Lu'))),
        min_size=3,
        max_size=10
    ))
    return " ".join(words)


@st.composite
def teaching_style(draw):
    """Generate a valid teaching style."""
    return draw(st.sampled_from(["guided", "coach", "mentor", "socratic", "direct"]))


@st.composite
def answer_policy(draw):
    """Generate a valid answer policy."""
    return draw(st.sampled_from(["hint-first", "spoon-feed", "withhold", "gradual"]))


@st.composite
def success_attempts(draw):
    """Generate a list of attempt records with pass/fail status."""
    count = draw(st.integers(min_value=0, max_value=10))
    attempts = []
    for _ in range(count):
        passed = draw(st.booleans())
        attempts.append({"passed": passed})
    return attempts


@st.composite
def weakness_records(draw):
    """Generate a list of weakness records with varying severity."""
    count = draw(st.integers(min_value=0, max_value=5))
    weaknesses = []
    for _ in range(count):
        concept = draw(st.text(min_size=3, max_size=20, alphabet=st.characters(whitelist_categories=('Ll',))))
        reason = draw(st.text(min_size=5, max_size=50, alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Zs'))))
        severity = draw(st.integers(min_value=1, max_value=10))
        # Randomly set next_review_at to be due or not
        is_due = draw(st.booleans())
        next_review = utc_now() - timedelta(hours=1) if is_due else utc_now() + timedelta(days=7)
        weaknesses.append(WeaknessRecord(
            concept=concept,
            reason=reason,
            severity=severity,
            next_review_at=next_review
        ))
    return weaknesses


@st.composite
def mastery_records(draw):
    """Generate a list of mastery records."""
    count = draw(st.integers(min_value=0, max_value=5))
    mastery = []
    for _ in range(count):
        concept = draw(st.text(min_size=3, max_size=20, alphabet=st.characters(whitelist_categories=('Ll',))))
        score = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
        confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
        mastery.append(MasteryRecord(concept=concept, score=score, confidence=confidence))
    return mastery


class TestPlannerProperties:
    """Property-based tests for TrainingPlannerService."""

    @given(
        success_count=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=50)
    def test_difficulty_progression(self, success_count):
        """Property: More consecutive successes -> harder tasks."""
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal="Learn Python testing",
            weekly_hours=4,
            teaching_style="guided",
            direct_answer_policy="hint-first",
        )
        # Create attempts with all successes
        attempts = [{"passed": True} for _ in range(success_count)]
        recommendation = planner.recommend_next_task(
            NextTaskContext(plan=plan, recent_attempts=attempts)
        )
        # Verify difficulty progression
        if success_count >= 3:
            assert recommendation.difficulty == TaskDifficulty.HARD
        elif success_count >= 1:
            assert recommendation.difficulty == TaskDifficulty.MEDIUM
        else:
            assert recommendation.difficulty == TaskDifficulty.EASY

    @given(
        weaknesses=weakness_records(),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_weakness_prioritization(self, weaknesses):
        """Property: Weaknesses with higher severity should be prioritized."""
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal="Learn Python",
            weekly_hours=4,
            teaching_style="guided",
            direct_answer_policy="hint-first",
        )
        # Filter to only due weaknesses
        due_weaknesses = [w for w in weaknesses if w.next_review_at and w.next_review_at <= utc_now()]
        if not due_weaknesses:
            return  # Skip if no due weaknesses
        recommendation = planner.recommend_next_task(
            NextTaskContext(plan=plan, weaknesses=weaknesses)
        )
        # If there are due weaknesses, the recommendation should be a review
        if due_weaknesses:
            assert recommendation.review is True

    @given(
        goal=valid_goal(),
        weekly_hours=valid_weekly_hours(),
        style=teaching_style(),
        policy=answer_policy(),
    )
    @settings(max_examples=50)
    def test_plan_stage_order(self, goal, weekly_hours, style, policy):
        """Property: Plans should always have Foundation -> Practice -> Integration."""
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal=goal,
            weekly_hours=weekly_hours,
            teaching_style=style,
            direct_answer_policy=policy,
        )
        # Verify phase order
        assert len(plan.phases) == 3
        assert plan.phases[0].title == "Foundation"
        assert plan.phases[1].title == "Practice"
        assert plan.phases[2].title == "Integration"

    @given(
        goal=valid_goal(),
        weekly_hours=valid_weekly_hours(),
        style=teaching_style(),
        policy=answer_policy(),
    )
    @settings(max_examples=50)
    def test_plan_has_valid_phase_ids(self, goal, weekly_hours, style, policy):
        """Property: All phases should have valid IDs."""
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal=goal,
            weekly_hours=weekly_hours,
            teaching_style=style,
            direct_answer_policy=policy,
        )
        for phase in plan.phases:
            assert phase.id.startswith("phase_")
            assert len(phase.id) > 6  # phase_ + hex

    @given(
        goal=valid_goal(),
        weekly_hours=valid_weekly_hours(),
        style=teaching_style(),
        policy=answer_policy(),
    )
    @settings(max_examples=50)
    def test_plan_current_phase_points_to_first(self, goal, weekly_hours, style, policy):
        """Property: New plans should have current_phase_id pointing to first phase."""
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal=goal,
            weekly_hours=weekly_hours,
            teaching_style=style,
            direct_answer_policy=policy,
        )
        assert plan.current_phase_id == plan.phases[0].id

    @given(
        goal=valid_goal(),
        weekly_hours=valid_weekly_hours(),
        style=teaching_style(),
        policy=answer_policy(),
        attempts=success_attempts(),
        mastery=mastery_records(),
        weaknesses=weakness_records(),
    )
    @settings(max_examples=30)
    def test_recommend_next_task_determinism(self, goal, weekly_hours, style, policy, attempts, mastery, weaknesses):
        """Property: Same state -> same recommendation (for non-random parts)."""
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal=goal,
            weekly_hours=weekly_hours,
            teaching_style=style,
            direct_answer_policy=policy,
        )
        context = NextTaskContext(
            plan=plan,
            recent_attempts=attempts,
            mastery=mastery,
            weaknesses=weaknesses,
        )
        # Call twice with same context
        rec1 = planner.recommend_next_task(context)
        rec2 = planner.recommend_next_task(context)
        # The difficulty should be the same (deterministic based on attempts)
        assert rec1.difficulty == rec2.difficulty
        # The review flag should be the same
        assert rec1.review == rec2.review

    @given(
        goal=valid_goal(),
        weekly_hours=valid_weekly_hours(),
        style=teaching_style(),
        policy=answer_policy(),
    )
    @settings(max_examples=50)
    def test_plan_has_valid_id(self, goal, weekly_hours, style, policy):
        """Property: Plans should have valid IDs."""
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal=goal,
            weekly_hours=weekly_hours,
            teaching_style=style,
            direct_answer_policy=policy,
        )
        assert plan.id.startswith("plan_")
        assert len(plan.id) > 5

    @given(
        goal=valid_goal(),
        weekly_hours=valid_weekly_hours(),
        style=teaching_style(),
        policy=answer_policy(),
    )
    @settings(max_examples=50)
    def test_plan_not_frozen_by_default(self, goal, weekly_hours, style, policy):
        """Property: New plans should not be frozen."""
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal=goal,
            weekly_hours=weekly_hours,
            teaching_style=style,
            direct_answer_policy=policy,
        )
        assert plan.frozen is False

    @given(
        goal=valid_goal(),
        weekly_hours=valid_weekly_hours(),
        style=teaching_style(),
        policy=answer_policy(),
    )
    @settings(max_examples=50)
    def test_freeze_plan_sets_frozen_flag(self, goal, weekly_hours, style, policy):
        """Property: freeze_plan should set frozen=True."""
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal=goal,
            weekly_hours=weekly_hours,
            teaching_style=style,
            direct_answer_policy=policy,
        )
        frozen_plan = planner.freeze_plan(plan)
        assert frozen_plan.frozen is True

    @given(
        attempts=success_attempts(),
    )
    @settings(max_examples=50)
    def test_difficulty_never_invalid(self, attempts):
        """Property: Difficulty should always be a valid TaskDifficulty enum."""
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal="Learn Python",
            weekly_hours=4,
            teaching_style="guided",
            direct_answer_policy="hint-first",
        )
        recommendation = planner.recommend_next_task(
            NextTaskContext(plan=plan, recent_attempts=attempts)
        )
        assert recommendation.difficulty in TaskDifficulty

    @given(
        goal=valid_goal(),
        weekly_hours=valid_weekly_hours(),
        style=teaching_style(),
        policy=answer_policy(),
    )
    @settings(max_examples=50)
    def test_phase_has_concepts(self, goal, weekly_hours, style, policy):
        """Property: Each phase should have at least one concept."""
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal=goal,
            weekly_hours=weekly_hours,
            teaching_style=style,
            direct_answer_policy=policy,
        )
        for phase in plan.phases:
            assert len(phase.concepts) >= 1

    @given(
        goal=valid_goal(),
        weekly_hours=valid_weekly_hours(),
        style=teaching_style(),
        policy=answer_policy(),
    )
    @settings(max_examples=50)
    def test_phase_has_objective(self, goal, weekly_hours, style, policy):
        """Property: Each phase should have a non-empty objective."""
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal=goal,
            weekly_hours=weekly_hours,
            teaching_style=style,
            direct_answer_policy=policy,
        )
        for phase in plan.phases:
            assert len(phase.objective) > 0


# ---------------------------------------------------------------------------
# Restored from test_course_pack.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _manifest(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "_type": COURSE_MANIFEST_TYPE,
        "version": COURSE_MANIFEST_VERSION,
        "title": "现代文学精读：从鲁迅到张爱玲",
        "subject_family": "literature",
        "summary": "三阶段精读计划",
        "stages": [
            {"id": "stage-1", "title": "精读《呐喊》", "goal": "建立细读方法", "outcomes": ["批注 3 处"]},
            {"id": "stage-2", "title": "仿写练习", "goal": "迁移叙事视角", "outcomes": []},
        ],
        "resources": [
            {"name": "呐喊.pdf", "kind": "pdf", "source": "resources/nahan.pdf", "contentHash": "abc123"}
        ],
        "card_pack": [
            {
                "card_type": "practice",
                "title": "批注练习",
                "learning_family": "literature",
                "acceptance_criteria": ["指出叙事视角"],
                "rubric": [
                    {"statement": "引用原文作为批注", "anchor": "他没有说自己不平"},
                    "说明修辞效果",
                ],
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_import_rejects_unknown_manifest_type() -> None:
    with pytest.raises(ValueError, match="unsupported course manifest _type"):
        inspect_course_manifest(_manifest(_type="other.pack"))


def test_import_rejects_unknown_version() -> None:
    with pytest.raises(ValueError, match="unsupported course manifest version"):
        inspect_course_manifest(_manifest(version=99))


def test_import_requires_title_and_stage() -> None:
    with pytest.raises(ValueError, match="non-empty title"):
        inspect_course_manifest(_manifest(title="   "))
    with pytest.raises(ValueError, match="at least one stage"):
        inspect_course_manifest(_manifest(stages=[]))
    with pytest.raises(ValueError, match="non-empty title"):
        inspect_course_manifest(_manifest(stages=[{"title": " "}]))


def test_import_rejects_unsupported_resource_kind() -> None:
    with pytest.raises(ValueError, match="unsupported kind 'exe'"):
        inspect_course_manifest(
            _manifest(resources=[{"name": "tool", "kind": "exe", "source": "x"}])
        )


def test_import_reports_anchor_trust() -> None:
    inspection = inspect_course_manifest(_manifest())
    trust = inspection.trust
    assert (trust.stages, trust.resources, trust.cards) == (2, 1, 1)
    assert trust.anchored_rubric_entries == 1
    assert trust.self_reported_rubric_entries == 1
    assert trust.downgraded_cards == ["批注练习"]
    assert any("self_reported" in note for note in trust.notes)
    assert any("never become verified evidence" in note for note in trust.notes)


def test_import_resolves_subject_family_through_the_registry() -> None:
    matched = inspect_course_manifest(_manifest())
    assert matched.trust.declared_subject_family == "literature"
    assert matched.trust.resolved_subject_family == "literature"
    assert matched.trust.subject_family_matched is True

    unknown = inspect_course_manifest(_manifest(subject_family="linguistics"))
    assert unknown.trust.resolved_subject_family == "code"
    assert unknown.trust.subject_family_matched is False
    assert any("falls back to 'code'" in note for note in unknown.trust.notes)
    # The resolution must equal what the registry itself would do.
    assert unknown.trust.resolved_subject_family == verifier_pack_for("linguistics").subject_family


def test_build_then_inspect_round_trip() -> None:
    stages = [
        PlanStage(id="s1", title="精读", goal="方法", outcomes=["批注"], resources=["res-1"]),
        PlanStage(id="s2", title="仿写", goal="迁移", outcomes=[]),
    ]
    resources = [
        ResourceRecord(
            id="res-1",
            kind="pdf",
            name="呐喊.pdf",
            source="library/nahan.pdf",
            content_hash="abc123",
            tags=["精读"],
            summary="短篇小说集",
        )
    ]
    manifest = build_course_manifest(
        title="现代文学精读",
        subject_family="literature",
        summary="三阶段",
        stages=stages,
        resources=resources,
    )
    assert manifest["_type"] == COURSE_MANIFEST_TYPE
    assert manifest["version"] == COURSE_MANIFEST_VERSION
    assert manifest["stages"][0]["resources"] == ["res-1"]
    assert manifest["resources"][0]["name"] == "呐喊.pdf"
    assert manifest["resources"][0]["contentHash"] == "abc123"
    assert manifest["resources"][0]["tags"] == ["精读"]

    inspection = inspect_course_manifest(manifest)
    assert inspection.manifest.title == "现代文学精读"
    assert inspection.manifest.subject_family == "literature"
    assert inspection.trust.stages == 2
    assert inspection.trust.resources == 1
    assert inspection.trust.subject_family_matched is True
    assert inspection.trust.self_reported_rubric_entries == 0
    assert inspection.trust.downgraded_cards == []


def test_classify_literature_family() -> None:
    assert classify_learning_subject("精读《呐喊》第一篇").family == "literature"
    assert classify_learning_subject("精读《呐喊》第一篇").subtype == "reading"
    assert classify_learning_subject("仿写鲁迅的白描笔法").family == "literature"
    assert classify_learning_subject("仿写鲁迅的白描笔法").subtype == "writing"
    assert classify_learning_subject("批注练习：意象与修辞").family == "literature"

    # Existing classifications must not drift: generic wording stays theory.
    assert classify_learning_subject("essay writing practice").family == "theory"
    assert classify_learning_subject("essay writing practice").subtype == "writing"
    assert classify_learning_subject("novel chapter theme").family == "theory"
    assert classify_learning_subject("novel chapter theme").subtype == "reading"

    # Code markers keep precedence over literature wording.
    code_subject = classify_learning_subject("debug loop 精读 traceback")
    assert code_subject.family == "code"
    assert code_subject.subtype == "debug"


def test_verifier_subject_family_mapping() -> None:
    assert verifier_subject_family("literature") == "literature"
    assert verifier_subject_family(" LITERATURE ") == "literature"
    assert verifier_subject_family("code") == "code"
    assert verifier_subject_family("theory") == "code"
    assert verifier_subject_family(None) == "code"
    assert verifier_subject_family("japanese") == "code"
    assert verifier_subject_family("literature") == verifier_pack_for("literature").subject_family


def test_card_snapshot_adopts_literature_family() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        focus_area="精读《呐喊》",
        target_skill="细读与批注",
    )
    assert card.learning_family == "literature"
    assert card.learning_subtype == "reading"


def test_card_snapshot_keeps_theory_for_generic_writing() -> None:
    card = TrainingCardCandidateSnapshot(
        card_type="practice",
        focus_area="英语写作",
        target_skill="opening sentence",
    )
    assert card.learning_family == "theory"
    assert card.learning_subtype == "writing"


# ---------------------------------------------------------------------------
# Restored from test_training_handoff.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


class TestTrainingHandoffGenerator:

    """Test the training handoff generator."""

    def test_generate_handoff_with_files(self):
        """Test handoff generation with file references."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-456",
            title="Fix async bug",
            card_type="practice",
            deliverable="Update src/main.py and src/utils.py",
            problem_statement="The async function in src/main.py has a race condition",
            status="candidate",
        )

        generator = TrainingHandoffGenerator()
        result = generator.generate_handoff(card, {"correct": True})

        assert result.files_to_touch == ["src/main.py", "src/utils.py"]
        assert len(result.verification_checklist) > 0

    def test_write_handoff_to_workspace(self):
        """Test writing handoff to a temporary workspace."""
        from datetime import datetime, timezone

        temp_dir = tempfile.mkdtemp()
        try:
            workspace_root = Path(temp_dir)

            content = TrainingHandoffContent(
                card_id="card-test",
                card_title="Test Card",
                card_type="practice",
                concept_practiced="test-concept",
                key_takeaway="Test takeaway",
                scenario_pack="remote_workspace",
                next_after_completion="Return with the route diff.",
                next_steps=["Step 1", "Step 2"],
                files_to_touch=["test.py"],
                verification_checklist=["Verify test"],
                success_signal="Test passed",
                project_scope="current",
                evidence_location="evidence",
                status=HandoffStatus.GENERATED,
            )

            handoff = ProjectHandoff(
                handoff_id="handoff-test",
                card_id="card-test",
                card_title="Test Card",
                evidence=[
                    EvidenceRecord(
                        id="ev-1",
                        card_id="card-test",
                        concept="test-concept",
                        content="Test evidence content",
                        source="learner",
                        created_at=datetime.now(timezone.utc),
                    )
                ],
                handoff_content=content,
                status=HandoffStatus.GENERATED,
            )

            generator = TrainingHandoffGenerator(workspace_root=workspace_root)
            written_path = generator.write_handoff_to_workspace(handoff, workspace_root)

            assert written_path is not None
            assert written_path.exists()
            assert written_path.relative_to(workspace_root) == Path(
                "notes/training-handoffs/current/card-test.md"
            )
            content_text = written_path.read_text()
            assert "Test Card" in content_text
            assert "Scenario Pack" in content_text
            assert "Next After Completion" in content_text
            assert "Step 1" in content_text
            assert "Test evidence content" in content_text

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_leftover_formal_card_title_does_not_live_in_handoff_markdown(self) -> None:
        from datetime import datetime, timezone

        from app.core.models import LearningPlan, PlanStage

        leftover_title = "Keep the current stage"
        leftover_stage = "Auth"
        leftover_step = "Keep one auth check"
        leftover_summary = "Leftover formal summary of the old stage path"
        leftover_plan_id = "plan-formal-old"
        leftover_card = f"Practice: {leftover_title}"
        recovered_step = "Add a token expiry test"
        plan = LearningPlan(
            id=leftover_plan_id,
            title=leftover_title,
            summary=leftover_summary,
            current_stage_id="stage-1",
            current_step=leftover_step,
            stages=[
                PlanStage(
                    id="stage-1",
                    title=leftover_stage,
                    goal="Keep one check",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        content = TrainingHandoffContent(
            card_id="card-leftover-handoff",
            card_title=leftover_card,
            card_type="practice",
            concept_practiced=recovered_step,
            key_takeaway="Recovered step only.",
            scenario_pack="auth-recovery",
            next_after_completion="Return with the expiry test.",
            next_steps=["Write the expiry test"],
            files_to_touch=[],
            verification_checklist=["pytest"],
            success_signal="Expiry test passes",
            project_scope="current",
            evidence_location="evidence",
            status=HandoffStatus.GENERATED,
        )
        handoff = ProjectHandoff(
            handoff_id="handoff-leftover",
            card_id="card-leftover-handoff",
            card_title=leftover_card,
            evidence=[
                EvidenceRecord(
                    id="ev-leftover",
                    card_id="card-leftover-handoff",
                    concept=recovered_step,
                    content="Recovered expiry evidence",
                    source="learner",
                    created_at=datetime.now(timezone.utc),
                )
            ],
            handoff_content=content,
            status=HandoffStatus.GENERATED,
        )
        generator = TrainingHandoffGenerator()
        advanced = {
            "current_step": recovered_step,
            "why_now": "Expired tokens still leak.",
            "resume_state": "in_progress",
            "workspace_id": "workspace-handoff-leftover",
        }
        heading = generator._render_handoff_markdown(
            handoff,
            leftover_plan=plan,
            leftover_runtime=advanced,
            leftover_task_title=leftover_title,
        ).splitlines()[0]
        assert leftover_title not in heading
        assert leftover_card not in heading
        assert leftover_stage not in heading
        assert leftover_step not in heading
        assert leftover_summary not in heading
        assert leftover_plan_id not in heading
        assert heading == f"# Training Handoff: {recovered_step}"
        empty_heading = generator._render_handoff_markdown(
            handoff,
            leftover_plan=plan,
            leftover_runtime={"current_step": "", "resume_state": "in_progress"},
            leftover_task_title=leftover_title,
        ).splitlines()[0]
        assert leftover_title not in empty_heading
        assert leftover_card not in empty_heading
        assert empty_heading == "# Training Handoff"
        still_heading = generator._render_handoff_markdown(
            handoff,
            leftover_plan=plan,
            leftover_runtime={
                "current_step": leftover_step,
                "plan_id": leftover_plan_id,
                "resume_state": "in_progress",
                "workspace_id": "workspace-handoff-still-on-plan",
            },
            leftover_task_title=leftover_title,
        ).splitlines()[0]
        assert leftover_card in still_heading

    def test_build_handoff_record(self):
        """Test building a complete handoff record."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-full",
            title="Full Card Test",
            card_type="practice",
            target_skill="transfer-skill",
            next_steps=["Apply to project", "Verify"],
            status="candidate",
        )

        generator = TrainingHandoffGenerator()
        result = generator.build_handoff_record(
            card,
            {"correct": True, "evidence": ["Learned this"]},
            mastery_delta=0.2,
        )

        assert result.handoff_id.startswith("handoff-card-full-")
        assert result.card_id == "card-full"
        assert len(result.evidence) == 1
        assert result.handoff_content.status == HandoffStatus.GENERATED

    def test_unverified_learner_submission_stays_provisional(self):
        """A learner-reported success cannot become a completion or mastery claim."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-unverified",
            title="Verify one route boundary",
            card_type="practice",
            target_skill="route boundary",
            validation_method="Run the focused route test and inspect the output.",
            reflection_prompt="What signal proved the boundary?",
            return_with="The test output and one sentence of reflection.",
        )

        handoff = TrainingHandoffGenerator().build_handoff_record(
            card,
            {
                "correct": True,
                "mastery_delta": 0.9,
                "evidence": ["I ran the route test locally."],
                "evidence_source": "learner_return",
            },
            mastery_delta=0.9,
        )

        assert handoff.status == HandoffStatus.GENERATED
        assert handoff.verification_state == "verification_required"
        assert handoff.return_state == "verify_then_return"
        assert handoff.evidence and handoff.evidence[0].verified is False
        assert "mastered" not in handoff.handoff_content.success_signal.lower()
        assert "server-side verification" in handoff.handoff_content.completion_claim
        assert any("learner self-report is not sufficient" in item for item in handoff.handoff_content.verification_checklist)

        # Language dispatch: zh request gets the zh honesty copy with identical
        # semantics — still no mastery claim, still server-side verification.
        zh_handoff = TrainingHandoffGenerator().build_handoff_record(
            card,
            {
                "correct": True,
                "mastery_delta": 0.9,
                "evidence": ["I ran the route test locally."],
                "evidence_source": "learner_return",
            },
            mastery_delta=0.9,
            response_language="zh-CN",
        )
        assert zh_handoff.verification_state == "verification_required"
        assert "服务端验证" in zh_handoff.handoff_content.completion_claim
        assert "掌握" not in zh_handoff.handoff_content.success_signal
        assert "server-side verification" not in zh_handoff.handoff_content.completion_claim
        assert any("自我报告并不足够" in item for item in zh_handoff.handoff_content.verification_checklist)

    def test_trusted_verification_supports_card_result_without_claiming_durable_mastery(self):
        """Verifier-attested evidence can support one card result, not broad mastery."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-verified",
            title="Verify one parser branch",
            card_type="practice",
            target_skill="parser branch",
            validation_method="Run the targeted parser test.",
        )
        handoff = TrainingHandoffGenerator().build_handoff_record(
            card,
            {
                "correct": True,
                "evidence": ["pytest tests/test_parser.py -k malformed_branch: 1 passed"],
                "evidence_source": "test_runner",
                "verified_by_evaluator": True,
            },
        )

        assert handoff.verification_state == "verified"
        assert handoff.return_state == "return_to_coach"
        assert handoff.evidence[0].verified is True
        assert handoff.evidence[0].verification_source == "test_runner"
        assert "supports one result" in handoff.handoff_content.success_signal
        assert "not a claim of durable mastery" in handoff.handoff_content.completion_claim

        # Language dispatch: zh request keeps the same honesty semantics.
        zh_handoff = TrainingHandoffGenerator().build_handoff_record(
            card,
            {
                "correct": True,
                "evidence": ["pytest tests/test_parser.py -k malformed_branch: 1 passed"],
                "evidence_source": "test_runner",
                "verified_by_evaluator": True,
            },
            response_language="zh-CN",
        )
        assert zh_handoff.verification_state == "verified"
        assert zh_handoff.return_state == "return_to_coach"
        assert "一次结果" in zh_handoff.handoff_content.success_signal
        assert "持久掌握" in zh_handoff.handoff_content.completion_claim
        assert "不是对持久掌握的断言" in zh_handoff.handoff_content.completion_claim
        assert "supports one result" not in zh_handoff.handoff_content.success_signal

    @pytest.mark.parametrize(
        ("evidence_source", "artifact"),
        [
            ("rubric_dual_review", "rubric review: 2/2 items matched; reviewer distinct from coach model"),
            ("deterministic_hook", "hook 字数区间: passed (156 chars within 120-200)"),
        ],
    )
    def test_literature_verification_sources_attest_with_artifact(self, evidence_source, artifact):
        """P2 #23: whitelisted literature sources verify only with an inspectable artifact."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-literature",
            title="Verify one annotation card",
            card_type="practice",
            target_skill="annotation card",
            validation_method="Run the anchored rubric review.",
        )
        handoff = TrainingHandoffGenerator().build_handoff_record(
            card,
            {
                "correct": True,
                "evidence": [artifact],
                "evidence_source": evidence_source,
                "verified_by_evaluator": True,
            },
        )

        assert handoff.verification_state == "verified"
        assert handoff.evidence[0].verification_source == evidence_source

        # Without the evaluator attestation the same source stays untrusted.
        unattested = TrainingHandoffGenerator().build_handoff_record(
            card,
            {"correct": True, "evidence": [artifact], "evidence_source": evidence_source},
        )
        assert unattested.verification_state == "verification_required"
        assert unattested.evidence[0].verification_source == ""

    def test_model_self_review_is_still_refused_as_untrusted(self):
        """The whitelist expansion cannot smuggle in an LLM-self-review source."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-self",
            title="Try one self-review",
            card_type="practice",
            target_skill="self review",
        )
        handoff = TrainingHandoffGenerator().build_handoff_record(
            card,
            {
                "correct": True,
                "evidence": ["模型自己说写得不错"],
                "evidence_source": "model_self_review",
                "verified_by_evaluator": True,
            },
        )
        assert handoff.verification_state == "verification_required"
        assert handoff.evidence[0].verification_source == ""

    def test_current_ide_file_verification_alias_remains_trusted_after_restart(self):
        """Older agent evidence must resolve to the canonical IDE verifier source."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-current-ide-file",
            title="Verify one active IDE file",
            card_type="practice",
            target_skill="active file verification",
        )
        handoff = TrainingHandoffGenerator().build_handoff_record(
            card,
            {
                "correct": True,
                "evidence": ["Active IDE file matched the focused acceptance criteria."],
                "evidence_source": "current_ide_file",
                "verified_by_evaluator": True,
            },
        )

        assert handoff.verification_state == "verified"
        assert handoff.phase.value == "verify"
        assert handoff.evidence[0].source == "ide_current_file"
        assert handoff.evidence[0].verification_source == "ide_current_file"

    def test_handoff_can_resume_from_disk_and_rejects_untrusted_verification(self):
        """Persistence keeps return state intact across interruption and restart."""
        from app.core.models import TrainingCardCandidateSnapshot

        temp_dir = tempfile.mkdtemp()
        try:
            workspace_root = Path(temp_dir)
            card = TrainingCardCandidateSnapshot(
                card_id="card-resume",
                title="Resume one diagnostic check",
                card_type="practice",
                target_skill="diagnostic check",
                validation_method="Run the focused diagnostic check.",
            )
            generator = TrainingHandoffGenerator(workspace_root=workspace_root)
            handoff = generator.build_handoff_record(
                card,
                {
                    "correct": True,
                    "evidence": ["Learner copied a diagnostic summary."],
                    "evidence_source": "learner_return",
                },
            )
            written = generator.write_handoff_to_workspace(handoff)
            assert written is not None
            assert written.with_suffix(".json").exists()

            restarted = TrainingHandoffGenerator(workspace_root=workspace_root)
            restored = restarted.resume_handoff(handoff.handoff_id)
            assert restored is not None
            assert restored.verification_state == "verification_required"
            assert restored.return_state == "verify_then_return"
            assert restored.evidence[0].verified is False

            untrusted = restarted.record_verification(
                restored.handoff_id,
                "The learner says it passed.",
                evidence_source="learner_return",
                verified_by_evaluator=True,
            )
            assert untrusted is not None
            assert untrusted.verification_state == "verification_required"

            verified = restarted.record_verification(
                restored.handoff_id,
                "diagnostics: no errors; focused test: passed",
                evidence_source="test_runner",
                verified_by_evaluator=True,
                reflection="The focused check exposed the exact parser boundary.",
            )
            assert verified is not None
            assert verified.verification_state == "verified"
            assert verified.return_state == "return_to_coach"
            assert verified.reflected_at is not None
            assert verified.reflection == "The focused check exposed the exact parser boundary."

            restored_after_verification = TrainingHandoffGenerator(
                workspace_root=workspace_root
            ).resume_handoff(handoff.handoff_id)
            assert restored_after_verification is not None
            assert restored_after_verification.verification_state == "verified"
            assert restored_after_verification.reflection == verified.reflection
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)



# ---------------------------------------------------------------------------
# Restored from test_dependency_skill_maps.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Restored from test_training_reliability.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _card(card_id: str = "reliability-card") -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type="practice",
        title="Persist the reliability path",
        target_skill="reliability",
        validation_method="Run the focused reliability test.",
        status="active",
    )


def test_reliability_transitions_and_rejects_illegal_moves() -> None:
    record = begin_record(request_id="req-1", command_id="trainer.training.reflect", card_id="card-1")
    assert record["phase"] == "intent"
    executing = mark_executing(record)
    assert executing["phase"] == "executing"
    acked = mark_succeeded(executing, snapshot_revision=3, learning_phase="reflect")
    assert acked["phase"] == "acked"
    assert acked["outcome"] == "success"
    assert acked["snapshot_revision"] == 3
    assert acked["acked_at"]
    assert can_transition("failed", "pending")
    assert not can_transition("acked", "failed")
    with pytest.raises(ValueError, match="cannot move"):
        transition(acked, "failed")


def test_reliability_replay_and_in_flight_coalesce() -> None:
    record = mark_succeeded(
        mark_executing(begin_record(request_id="req-2", command_id="trainer.training.return", card_id="card-2")),
        snapshot_revision=1,
    )
    assert should_replay(record, "req-2", "req-2")
    assert not should_replay(record, "req-other", "other-key")

    in_flight = mark_executing(
        begin_record(request_id="req-3", command_id="trainer.training.reflect", card_id="card-3")
    )
    # A resend of the same request coalesces with the in-flight owner.
    assert should_coalesce(
        in_flight,
        request_id="req-3",
        command_id="trainer.training.reflect",
        card_id="card-3",
    )
    # A different request for the same card is different work: it must not be
    # swallowed as a duplicate (the caller would report a success that never ran).
    assert not should_coalesce(
        in_flight,
        request_id="req-different-work",
        command_id="trainer.training.reflect",
        card_id="card-3",
    )
    assert not should_coalesce(
        in_flight,
        request_id="req-other",
        command_id="trainer.training.return",
        card_id="card-3",
    )


def test_reliability_timeout_cancel_and_recover() -> None:
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    record = begin_record(
        request_id="req-4",
        command_id="trainer.training.practiceReturn",
        card_id="card-4",
        timeout_ms=1_000,
        now=past,
    )
    executing = mark_executing(record, now=past)
    expired = expire_if_needed(executing)
    assert expired is not None
    assert expired["phase"] == "failed"
    assert expired["outcome"] == "timeout"
    assert expired["recoverable"] is True

    cancelled = request_cancel(mark_executing(begin_record(request_id="req-5", command_id="x", card_id="c")))
    assert cancelled["phase"] == "cancelled"
    recovered = recover_record(cancelled, request_id="req-5b")
    assert recovered["phase"] == "pending"
    assert recovered["revision"] == 2
    assert recovered["request_id"] == "req-5b"
    assert recovered["error"] == ""


def test_memory_service_persists_acked_reliability_through_reflect_and_replays(
    tmp_path,
) -> None:
    service = MemoryService(TrainerRepository(tmp_path / "reliability.db"))
    workspace_id = "workspace-reliability"
    card = service.upsert_card(workspace_id, _card())
    verified = service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="pytest tests/test_reliability.py: 1 passed",
        next_step="Record the reflection.",
        focus_area="reliability",
        evidence_source="test_runner",
        verified_by_evaluator=True,
        request_id="req-verify-1",
    )
    assert verified["latest_training_reliability"]["phase"] == "acked"
    assert verified["latest_training_reliability"]["request_id"] == "req-verify-1"
    assert verified["latest_training_reliability"]["snapshot_revision"] >= 1

    reflected = service.record_training_handoff_reflection(
        workspace_id=workspace_id,
        card_id=card.card_id,
        reflection="The timeout case showed why acknowledgement must be persisted.",
        handoff_id=verified["latest_training_handoff"]["handoff_id"],
        request_id="req-reflect-1",
    )
    assert reflected["latest_training_reliability"]["phase"] == "acked"
    assert reflected["latest_training_reliability"]["command_id"] == "trainer.training.reflect"
    assert reflected["latest_training_handoff"]["learning_phase"] == "reflect"

    replayed = service.record_training_handoff_reflection(
        workspace_id=workspace_id,
        card_id=card.card_id,
        reflection="A duplicate request must not rewrite current truth.",
        handoff_id=verified["latest_training_handoff"]["handoff_id"],
        request_id="req-reflect-1",
    )
    assert replayed["latest_training_reliability"]["request_id"] == "req-reflect-1"
    assert replayed["latest_training_reliability"]["phase"] == "acked"
    assert replayed["latest_training_handoff"]["learning_phase"] == "reflect"

    restarted = MemoryService(TrainerRepository(tmp_path / "reliability.db"))
    restored = restarted.latest_training_reliability(workspace_id)
    assert restored is not None
    assert restored["request_id"] == "req-reflect-1"
    assert restored["phase"] == "acked"
    assert restored["snapshot_revision"] >= 1


def test_memory_service_failure_cancel_and_recover_are_authoritative(tmp_path) -> None:
    service = MemoryService(TrainerRepository(tmp_path / "reliability-recover.db"))
    workspace_id = "workspace-reliability-recover"
    service.upsert_card(workspace_id, _card("recover-card"))

    with pytest.raises(LookupError, match="No training handoff"):
        service.record_training_handoff_reflection(
            workspace_id=workspace_id,
            card_id="recover-card",
            reflection="This should fail before a handoff exists.",
            request_id="req-fail-1",
        )

    failed = service.latest_training_reliability(workspace_id)
    assert failed is not None
    assert failed["phase"] == "failed"
    assert failed["recoverable"] is True
    assert failed["request_id"] == "req-fail-1"

    recovered = service.recover_training_reliability(
        workspace_id,
        request_id="req-fail-2",
    )
    assert recovered["latest_training_reliability"]["phase"] == "pending"
    assert recovered["latest_training_reliability"]["revision"] == 2
    assert recovered["latest_training_reliability"]["request_id"] == "req-fail-2"

    executing = mark_executing(recovered["latest_training_reliability"])
    structured = service._structured_for(workspace_id)
    service._save_training_reliability(workspace_id, structured, executing)

    cancelled = service.cancel_training_reliability(
        workspace_id,
        request_id="req-fail-2",
        command_id="trainer.training.reflect",
        card_id="recover-card",
    )
    assert cancelled["latest_training_reliability"]["phase"] == "cancelled"
    assert cancelled["latest_training_reliability"]["recoverable"] is True


def test_memory_service_expires_in_flight_reliability(tmp_path) -> None:
    service = MemoryService(TrainerRepository(tmp_path / "reliability-expire.db"))
    workspace_id = "workspace-reliability-expire"
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    record = mark_executing(
        begin_record(
            request_id="req-expire-1",
            command_id="trainer.training.return",
            card_id="expire-card",
            timeout_ms=1_000,
            now=past,
        ),
        now=past,
    )
    structured = service._structured_for(workspace_id)
    service._save_training_reliability(workspace_id, structured, record)

    expired = service.expire_training_reliability(workspace_id)
    assert expired["latest_training_reliability"]["phase"] == "failed"
    assert expired["latest_training_reliability"]["outcome"] == "timeout"
    assert expired["latest_training_reliability"]["recovery_action"] == "retry"


def test_memory_service_return_replays_same_request_id_without_second_credit(tmp_path) -> None:
    service = MemoryService(TrainerRepository(tmp_path / "reliability-return.db"))
    workspace_id = "workspace-reliability-return"
    card = service.upsert_card(workspace_id, _card("return-card"))
    verified = service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="pytest tests/test_return_idempotent.py: 1 passed",
        next_step="Return the verified result.",
        focus_area="reliability",
        evidence_source="test_runner",
        verified_by_evaluator=True,
        request_id="req-verify-return-1",
    )
    handoff_id = verified["latest_training_handoff"]["handoff_id"]
    service.record_training_handoff_reflection(
        workspace_id=workspace_id,
        card_id=card.card_id,
        reflection="Ready to return once.",
        handoff_id=handoff_id,
        request_id="req-reflect-return-1",
    )

    first = service.return_training_handoff(
        workspace_id=workspace_id,
        card_id=card.card_id,
        handoff_id=handoff_id,
        request_id="req-return-1",
    )
    assert first["latest_training_reliability"]["phase"] == "acked"
    credited = service.get_card(workspace_id, card.card_id)
    assert credited is not None
    ledger_count = len(
        [
            entry
            for entry in service._card_ledger
            if entry.get("card_id") == card.card_id and entry.get("workspace_id") == workspace_id
        ]
    )

    second = service.return_training_handoff(
        workspace_id=workspace_id,
        card_id=card.card_id,
        handoff_id=handoff_id,
        request_id="req-return-1",
    )
    assert second["latest_training_reliability"]["request_id"] == "req-return-1"
    assert second["latest_training_reliability"]["phase"] == "acked"
    ledger_after = [
        entry
        for entry in service._card_ledger
        if entry.get("card_id") == card.card_id and entry.get("workspace_id") == workspace_id
    ]
    assert len(ledger_after) == ledger_count
    unchanged = service.get_card(workspace_id, card.card_id)
    assert unchanged is not None
    assert unchanged.status == credited.status


def test_mark_succeeded_annotates_cancel_and_timeout_races() -> None:
    """Persisted work stays success; a raced cancel/timeout is annotated, never
    rewritten as failure (and a same-identity retry replays)."""
    cancel_flagged = mark_executing(
        begin_record(request_id="req-race-cancel", command_id="x", card_id="c")
    )
    cancel_flagged["cancel_requested"] = True
    acked = mark_succeeded(cancel_flagged, snapshot_revision=1)
    assert acked["phase"] == "acked"
    assert acked["outcome"] == "success"
    assert acked["error"] == ""
    assert acked["cancel_after"] is True
    assert acked["timeout_after"] is False

    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    expired_executing = mark_executing(
        begin_record(
            request_id="req-race-timeout",
            command_id="x",
            card_id="c",
            timeout_ms=1_000,
            now=past,
        )
    )
    acked_timeout = mark_succeeded(expired_executing, snapshot_revision=1)
    assert acked_timeout["phase"] == "acked"
    assert acked_timeout["outcome"] == "success"
    assert acked_timeout["timeout_after"] is True
    assert should_replay(acked_timeout, "req-race-timeout", "req-race-timeout")


def test_memory_service_cancel_race_keeps_work_as_succeeded_and_replays(tmp_path) -> None:
    """A cancel landing while work() runs must not rewrite the persisted work
    as cancelled, and the same-identity retry must replay without a second run."""
    service = MemoryService(TrainerRepository(tmp_path / "reliability-cancel-race.db"))
    workspace_id = "workspace-reliability-cancel-race"
    calls: list[str] = []

    def racing_work() -> dict[str, object]:
        # The cancel mutating the same slot while work() is still executing.
        service.cancel_training_reliability(workspace_id, request_id="req-cancel-race")
        calls.append("ran")
        return {"ok": True}

    first = service.run_training_reliability(
        workspace_id,
        request_id="req-cancel-race",
        command_id="trainer.training.practiceReturn",
        card_id="race-card",
        work=racing_work,
    )
    record = first["latest_training_reliability"]
    assert record["phase"] == "acked"
    assert record["outcome"] == "success"
    assert record["cancel_after"] is True
    assert calls == ["ran"]

    replayed = service.run_training_reliability(
        workspace_id,
        request_id="req-cancel-race",
        command_id="trainer.training.practiceReturn",
        card_id="race-card",
        work=lambda: calls.append("rerun") or {"ok": True},
    )
    assert replayed["latest_training_reliability"]["phase"] == "acked"
    assert calls == ["ran"]


# ---------------------------------------------------------------------------
# Restored from test_training_actions.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Restored from test_training_expression_acceptance.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def acceptance(code: str, symbols: list[str], criteria: list[str] | None = None):
    return EvaluatorService()._training_acceptance_check(
        source="training", code=code, language_id="python",
        acceptance_criteria=criteria or [], learner_deliverables=[],
        expected_symbols=symbols, execution_passed=True,
    )


def test_nested_list_calls_and_negative_hash_paths_are_real_code_signals():
    code = """
pair = ([1, 2], 3)
pair [0] . append(4)
value = ([1, 2], 3)
try:
    hash(value)
except TypeError:
    pass
try:
    {value: 1}
except TypeError:
    pass
"""
    result = acceptance(code, ["pair[0].append", "hash(value)", "{value: 1}", "TypeError"],
                        ["调用 `pair[0].append` 修改内部列表", "验证 `hash(value)` 的边界"])
    assert result is not None and result.status == "passed"


@pytest.mark.parametrize("code", [
    '# pair[0].append(4)\ntext = "hash(value), {value: 1}"',
    'text = "pair[0].append(4)"\n# hash(value), {value: 1}',
    "pair[1].append(4)\nhash(other)\n{other: 1}",
    "pair[0] = []\nvalue = 1",
])
def test_expression_lookalikes_do_not_verify_missing_operations(code):
    result = acceptance(code, ["pair[0].append", "hash(value)", "{value: 1}"])
    assert result is not None and result.status == "failed"


def test_expression_inside_string_argument_does_not_count_as_executed_code():
    result = acceptance('print("pair[0].append(4)")', ["pair[0].append"])
    assert result is not None and result.status == "failed"


def test_assignment_to_expression_does_not_count_as_reading_or_calling_it():
    result = acceptance("pair[0].append = custom_append", ["pair[0].append"])
    assert result is not None and result.status == "failed"


def test_nested_and_empty_list_literals_are_matched_as_real_syntax():
    result = acceptance(
        "assert sum_nested([]) == 0\nassert sum_nested([1, [2, [3, 4]], 5]) == 15",
        ["[]", "[1, [2, [3, 4]], 5]"],
    )
    assert result is not None and result.status == "passed"


@pytest.mark.parametrize("code", [
    'text = "[] and [1, [2, [3, 4]], 5]"',
    '# [] and [1, [2, [3, 4]], 5]',
    'assert sum_nested([1, [2, [3, 9]], 5]) == 20',
])
def test_list_literals_in_comments_strings_or_with_wrong_values_do_not_match(code):
    result = acceptance(code, ["[]", "[1, [2, [3, 4]], 5]"])
    assert result is not None and result.status == "failed"


def test_explicit_returned_string_values_can_satisfy_acceptance_signals():
    code = '''
class ConversationState:
    required_context: set[str]
    present_context: set[str]


def next_action(state: ConversationState) -> str:
    missing_context = set(state.required_context) - set(state.present_context)
    if missing_context:
        return "ask_clarification"
    return "answer"
'''
    result = acceptance(
        code,
        ["ConversationState", "next_action", "missing_context",
         "required_context", "present_context", "ask_clarification", "answer"],
        ['定义 `next_action` 在上下文缺失时返回 `"ask_clarification"` 的分支'],
    )
    assert result is not None
    assert result.status == "passed", result.detail


def test_string_values_only_in_comments_do_not_satisfy_symbol_acceptance():
    code = '# return "ask_clarification"\ndef next_action(state):\n    return "answer"\n'
    result = acceptance(code, ["ask_clarification"])
    assert result is not None
    assert result.status == "failed"


# ---------------------------------------------------------------------------
# Restored from test_transfer_skills.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_single_scene_does_not_promote() -> None:
    assert (
        should_promote_transferable_skill(
            concept="tool calling",
            workspace_id="project-a",
            outcome_success=True,
            existing_scenes=[],
        )
        is False
    )


def test_two_cards_same_default_scene_do_not_promote() -> None:
    scene = {"workspace_id": "project-a", "scene_key": "default"}
    assert (
        should_promote_transferable_skill(
            concept="tool calling",
            workspace_id="project-a",
            current_scene_key="default",
            existing_scenes=[scene],
            outcome_success=True,
        )
        is False
    )


def test_second_workspace_promotes() -> None:
    assert should_promote_transferable_skill(
        concept="tool calling",
        workspace_id="project-b",
        current_scene_key="default",
        existing_scenes=[{"workspace_id": "project-a", "scene_key": "default"}],
        outcome_success=True,
    )


def test_transfer_ids_without_evidence_stay_default_scene() -> None:
    assert (
        resolve_skill_scene_key(
            transfer_source_workspace_id="project-a",
            transfer_target_workspace_id="project-b",
            transfer_evidence_summary="",
        )
        == "default"
    )
    assert (
        should_promote_transferable_skill(
            concept="tool calling",
            workspace_id="project-b",
            outcome_success=True,
            transfer_source_workspace_id="project-a",
            transfer_target_workspace_id="project-b",
            existing_scenes=[],
        )
        is False
    )


def test_distinct_evidenced_scenes_in_same_workspace_do_not_promote() -> None:
    first = resolve_skill_scene_key()
    second = resolve_skill_scene_key(
        transfer_source_context="billing route",
        transfer_target_context="docs sandbox",
        transfer_evidence_summary="Applied the same guard in a second task.",
    )
    leftover = resolve_skill_scene_key(
        transfer_source_context="Keep the leftover plan",
        transfer_target_context="docs sandbox",
        transfer_evidence_summary="Applied the same guard against the leftover object.",
    )
    assert first == "default"
    assert second.startswith("transfer:")
    assert leftover.startswith("transfer:")
    assert (
        should_promote_transferable_skill(
            concept="response model",
            workspace_id="project-a",
            current_scene_key=second,
            existing_scenes=[{"workspace_id": "project-a", "scene_key": first}],
            outcome_success=True,
        )
        is False
    )
    assert (
        should_promote_transferable_skill(
            concept="response model",
            workspace_id="project-a",
            current_scene_key=leftover,
            existing_scenes=[{"workspace_id": "project-a", "scene_key": first}],
            outcome_success=True,
        )
        is False
    )


def test_failure_never_promotes() -> None:
    assert (
        should_promote_transferable_skill(
            concept="tool calling",
            workspace_id="project-b",
            existing_scenes=[{"workspace_id": "project-a", "scene_key": "default"}],
            outcome_success=False,
        )
        is False
    )


def test_copy_never_claims_global_mastery_from_one_scene() -> None:
    awaiting = build_transfer_skill_state_record(
        concept="tool calling",
        scenes=[{"workspace_id": "project-a", "scene_key": "default"}],
        language="en-US",
    )
    assert awaiting["state"] == "awaiting_second_scene"
    assert "mastered" not in awaiting["why"].lower()
    assert "global" not in awaiting["why"].lower()

    transferable = build_transfer_skill_state_record(
        concept="tool calling",
        scenes=[
            {"workspace_id": "project-a", "scene_key": "default"},
            {"workspace_id": "project-b", "scene_key": "default"},
        ],
        language="en-US",
    )
    assert transferable["state"] == "transferable"
    assert "mastered" not in transferable["why"].lower()


def test_orientation_overlay_does_not_steal_blockers() -> None:
    blocked = apply_transfer_skill_to_coach_orientation(
        {
            "object_kind": "provider",
            "state": "needs_setup",
            "next_step": "Save and test a provider first.",
            "advanced_where": "Settings · provider",
        },
        {
            "state": "transferable",
            "why": "This skill has evidence in more than one scene.",
            "next": "Schedule a review, or apply it in a new challenge.",
        },
    )
    assert blocked["next_step"] == "Save and test a provider first."

    ready = apply_transfer_skill_to_coach_orientation(
        {
            "object_kind": "plan",
            "state": "ready",
            "next_step": "Continue on this object, or check Plan.",
            "advanced_where": "Plan · current step",
        },
        {
            "state": "transferable",
            "why": "This skill has evidence in more than one scene.",
            "next": "Schedule a review, or apply it in a new challenge.",
        },
    )
    assert ready["next_step"] == "Schedule a review, or apply it in a new challenge."
    assert "more than one scene" in ready["advanced_where"]


# ---------------------------------------------------------------------------
# Restored from test_training_return_feedback.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _feedback(tmp_path):
    path = str(tmp_path / "lesson.py")
    content = "assert ([1], 2)[0] == [1]\n"
    store = AttemptStore(tmp_path / "trainer.sqlite3")
    attempt = store.start_attempt(workspace_id="context-one", card_id="card-one", file_path=path, file_hash=content_hash(content))
    store.record_evidence(attempt_id=attempt["attempt_id"], caller_workspace_id="context-one", artifact_hash=content_hash(content), result="passed", trust_level="controlled_check")
    store.close_attempt(attempt["attempt_id"], workspace_id="context-one")
    handoff = {"card_id": "card-one", "card_title": "嵌套元组边界", "status": "completed", "learning_phase": "return", "verification_state": "verified", "returned_at": "2026-10-02T00:00:00Z", "reflection": "槽位不可写，内部列表可变。"}
    memory = SimpleNamespace(workspace={"latest_training_handoff": handoff})
    runtime = SimpleNamespace(memory_service=SimpleNamespace(snapshot=lambda _: memory), attempt_store=store)
    request = SimpleNamespace(message="请评估我在「嵌套元组边界」中的提交和复盘。", current_file=SimpleNamespace(path=path, content=content))
    return runtime, request, handoff, attempt


def test_feedback_reuses_only_same_file_current_controlled_returned_evidence(tmp_path):
    runtime, request, _, _ = _feedback(tmp_path)
    assert completed_return_feedback(runtime, "context-one", request)
    assert not completed_return_feedback(runtime, "context-other", request)
    request.current_file.content += "# edited\n"
    assert not completed_return_feedback(runtime, "context-one", request)


@pytest.mark.parametrize("result", [
    "VS Code Testing 已重新执行 Ruff、Pyright、pytest、training-acceptance，4/4 通过。",
    "已经重新验证这份提交。", "不要重新执行，只评估复盘。",
    "I already rerun the checks. Please review the reflection.",
])
def test_return_bridge_past_checks_are_not_new_execution_requests(tmp_path, result):
    runtime, request, _, _ = _feedback(tmp_path)
    request.message += result
    assert completed_return_feedback(runtime, "context-one", request)
    request.message += "请重新验证。"
    assert not completed_return_feedback(runtime, "context-one", request)


@pytest.mark.parametrize("change", ["other_file", "other_card", "other_message", "rerun", "unreturned", "unreflected", "unverified", "self_reported", "deleted"])
def test_incomplete_or_unrelated_feedback_cannot_bypass_verification(tmp_path, change):
    runtime, request, handoff, attempt = _feedback(tmp_path)
    if change == "other_file":
        request.current_file.path += ".other"
    elif change == "other_card":
        handoff["card_id"] = "another-card"
    elif change == "other_message":
        request.message = "评估另外一张卡。"
    elif change == "rerun":
        request.message += "请重新验证。"
    elif change == "unreturned":
        handoff["status"] = "active"
    elif change == "unreflected":
        handoff["reflection"] = ""
    elif change == "unverified":
        handoff["verification_state"] = "unverified"
    else:
        evidence = runtime.attempt_store.list_evidence(attempt["attempt_id"])[0]
        evidence["trust_level" if change == "self_reported" else "source_deleted"] = "self_reported" if change == "self_reported" else True
        runtime.attempt_store._write_evidence_row(evidence["evidence_id"], evidence)
    assert not completed_return_feedback(runtime, "context-one", request)


@pytest.mark.parametrize("message", ["为什么元组内部的列表可以修改？", "Explain the current function.", "给我一个概念例子。"])
def test_plain_questions_do_not_always_request_execution(message):
    assert not _practice_verification_requested_or_claimed(message=message, content="先区分容器和它引用的对象。")
    assert not _practice_verification_requested_or_claimed(
        message=message,
        content="下一步，你可以做一个最小实验来验证这个原因。",
    )


@pytest.mark.parametrize("message", ["请核验我的训练提交。", "重新验证这张卡。", "Verify my practice."])
def test_explicit_execution_request_is_retained(message):
    assert _practice_verification_requested_or_claimed(message=message, content="")


def test_verified_return_authority_survives_minimal_prompt_context():
    from app.core.models import UserProfile
    from app.llm.prompts import build_coaching_system_prompt

    profile = UserProfile()
    context = {"context_tier": "minimal", "completed_training_return_feedback": True}
    prompt = build_coaching_system_prompt(profile, message="请评估这次复盘", coach_context=context)
    assert "current server-controlled evidence" in prompt
    assert "not an unverified learner claim" in prompt
    assert "Plan adoption is a separate explicit action" in prompt
    for context in ({"context_tier": "minimal"}, {"completed_training_return_feedback": False}):
        prompt = build_coaching_system_prompt(profile, message="我说已经通过", coach_context=context)
        assert "Current returned training artifact:" not in prompt


# ---------------------------------------------------------------------------
# Restored from test_training_attempts.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_evidence_record_requires_known_attempt(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "attempts.db")
    assert (
        store.record_evidence(
            attempt_id="attempt-missing",
            artifact_hash="hash",
            result="passed",
        )
        is None
    )


def test_concurrent_start_attempt_creates_single_active(tmp_path: Path) -> None:
    import threading

    store = AttemptStore(tmp_path / "attempts.db")
    barrier = threading.Barrier(8)
    results: list[dict] = []

    def start() -> None:
        barrier.wait()
        results.append(
            store.start_attempt(
                workspace_id="ws-race",
                card_id="card-race",
                file_path="src/a.py",
                file_hash="hash-race",
            )
        )

    threads = [threading.Thread(target=start) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    active_ids = {item["attempt_id"] for item in results}
    assert len(active_ids) == 1, f"racing starts produced {len(active_ids)} attempts"

    history = store.list_attempts(workspace_id="ws-race", card_id="card-race")
    active_history = [item for item in history if item["status"] == "active"]
    assert len(active_history) == 1


def test_concurrent_answer_and_hint_updates_merge(tmp_path: Path) -> None:
    import threading

    store = AttemptStore(tmp_path / "attempts.db")
    attempt = store.start_attempt(workspace_id="ws-merge", card_id="card-merge")
    attempt_id = attempt["attempt_id"]
    release = threading.Event()

    def write_answer() -> None:
        release.wait()
        store.update_attempt(attempt_id, answer_draft="NEW ANSWER")

    def write_hint() -> None:
        release.wait()
        store.update_attempt(attempt_id, assistance_level="hint_level_3")

    threads = [threading.Thread(target=write_answer), threading.Thread(target=write_hint)]
    for thread in threads:
        thread.start()
    release.set()
    for thread in threads:
        thread.join()

    merged = store.get_attempt(attempt_id)
    assert merged is not None
    assert merged["answer_draft"] == "NEW ANSWER"
    assert merged["assistance_level"] == "hint_level_3", "concurrent hint must survive"


def test_assistance_level_never_regresses(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "attempts.db")
    attempt = store.start_attempt(
        workspace_id="ws-hint", card_id="card-hint", assistance_level="hint_level_3"
    )
    attempt_id = attempt["attempt_id"]

    lowered = store.update_attempt(attempt_id, assistance_level="hint_level_1")
    assert lowered is not None
    assert lowered["assistance_level"] == "hint_level_3"

    lowered_again = store.update_attempt(attempt_id, assistance_level="independent")
    assert lowered_again is not None
    assert lowered_again["assistance_level"] == "hint_level_3"

    raised = store.update_attempt(attempt_id, assistance_level="hint_level_2")
    assert raised is not None
    assert raised["assistance_level"] == "hint_level_3"


# ---------------------------------------------------------------------------
# Restored from test_flashcard_cjk_grading.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _flash_card(card_id: str, expected_answer: str) -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type="flash",
        title="Event loop",
        target_skill="event loop",
        expected_answer=expected_answer,
        answer_mode="text",
        status="candidate",
    )


def test_cjk_paraphrase_passes_with_dice_score(tmp_path: Path) -> None:
    workspace_id = "ws-cjk-flash-paraphrase"
    service = MemoryService(TrainerRepository(tmp_path / "cjk-paraphrase.db"))
    card = service.upsert_card(
        workspace_id,
        _flash_card("card-cjk-paraphrase", "事件循环是调度协程执行的核心机制"),
    )

    attempt = service.submit_flashcard_answer(
        workspace_id,
        card.card_id,
        learner_answer="事件循环负责调度协程的执行",
    )

    assert attempt.correct is True
    assert attempt.score >= 0.6
    assert attempt.feedback["correct"] is True


def test_cjk_unrelated_answer_still_fails(tmp_path: Path) -> None:
    workspace_id = "ws-cjk-flash-unrelated"
    service = MemoryService(TrainerRepository(tmp_path / "cjk-unrelated.db"))
    card = service.upsert_card(
        workspace_id,
        _flash_card("card-cjk-unrelated", "事件循环是调度协程执行的核心机制"),
    )

    attempt = service.submit_flashcard_answer(
        workspace_id,
        card.card_id,
        learner_answer="快速排序需要递归",
    )

    assert attempt.correct is False
    assert attempt.score < 0.6
    assert "text_answer" in attempt.feedback["mismatches"]


def test_english_exact_match_is_unchanged(tmp_path: Path) -> None:
    workspace_id = "ws-cjk-flash-english"
    service = MemoryService(TrainerRepository(tmp_path / "cjk-english.db"))
    expected = "An event loop schedules coroutine execution"
    card = service.upsert_card(workspace_id, _flash_card("card-cjk-english", expected))

    attempt = service.submit_flashcard_answer(workspace_id, card.card_id, learner_answer=expected)

    assert attempt.correct is True
    assert attempt.score == 1.0


def test_english_exact_match_is_unchanged_when_cjk_appears_in_other_cards(tmp_path: Path) -> None:
    """The CJK fallback must not alter grading for answers without CJK text."""

    workspace_id = "ws-cjk-flash-mixed"
    service = MemoryService(TrainerRepository(tmp_path / "cjk-mixed.db"))
    english = service.upsert_card(
        workspace_id,
        _flash_card("card-mixed-english", "An event loop schedules coroutine execution"),
    )
    wrong = service.submit_flashcard_answer(
        workspace_id,
        english.card_id,
        learner_answer="A quicksort partitions the array",
    )
    assert wrong.correct is False
    assert wrong.score == 0.0


# ---------------------------------------------------------------------------
# Restored from test_growth_loop_honesty.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_growth_loop_honesty_prompt_uses_first_look_and_does_not_invite_mint() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(long_term_goal="Learn auth expiry", weekly_hours=5),
        "en-US",
        "guided",
        message="Help me understand this project first.",
        coach_context={
            "scenario": "onboarding",
            "workspace_understanding": {
                "first_look_summary": {
                    "recommended_next_step": "Add a token expiry test",
                }
            },
        },
    )
    assert "## Growth Loop Honesty" in prompt
    assert "Do not speak as if you created a learning plan" in prompt
    assert "The next step is the first-look recommended next: Add a token expiry test" in prompt
    assert "## Formal Plan Turn" not in prompt


def test_explicit_formal_plan_turn_skips_growth_loop_honesty_block() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(long_term_goal="Learn auth expiry", weekly_hours=5),
        "en-US",
        "guided",
        message="Generate a formal learning plan.",
        coach_context={"formal_plan_mutation": True},
    )
    assert "## Formal Plan Turn" in prompt
    assert "## Growth Loop Honesty" not in prompt


def test_pressure_blocks_keeps_growth_honesty_even_for_chat_card_ask() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(long_term_goal="Learn auth expiry", weekly_hours=5),
        "en-US",
        "guided",
        message="Create a practice card for token refresh.",
        coach_context={
            "explicit_training_card_request": True,
            "pressure_blocks_live_object_mint": True,
        },
    )
    assert "## Growth Loop Honesty" in prompt
    assert "hint-only" in prompt
    assert "Do not invent or mint a LearningPlan" in prompt


def test_chat_card_ask_keeps_growth_honesty_without_pressure() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(long_term_goal="Learn auth expiry", weekly_hours=5),
        "en-US",
        "guided",
        message="Create a practice card for token refresh.",
        coach_context={
            "explicit_training_card_request": True,
        },
    )
    assert "## Growth Loop Honesty" in prompt
    assert "POST /training/generate-card" in prompt
    assert "Do not invent a card_id" in prompt


# ---------------------------------------------------------------------------
# Restored from test_plan_update_live_plan_gate.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer plan-update live-plan gate",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-plan-update-gate.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _runtime(workspace: dict) -> dict:
    value = workspace.get("latest_plan_runtime") or workspace.get("latestPlanRuntime") or {}
    return value if isinstance(value, dict) else {}


def _seed_live_plan(runtime, workspace_id: str, *, plan_id: str) -> LearningPlan:
    plan = LearningPlan(
        id=plan_id,
        title="Ship token refresh under a live plan",
        current_step="Ship token refresh under a live plan",
        why_now="Keep the live stage visible",
        next_after_current="Review the refresh path",
        stages=[
            PlanStage(
                id="stage-live",
                title="Live",
                goal="Ship token refresh under a live plan",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    runtime.repository.save_plan(workspace_id, plan)
    runtime.memory_service.bind_explicit_generated_plan(workspace_id, plan)
    return plan


def test_plan_update_with_live_plan_freezes_without_changing_plan_id(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-update-live"
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Live plan update lab"},
        )
        assert started.status_code == 200, started.text
        seeded = _seed_live_plan(app.state.runtime, workspace_id, plan_id="plan-live-freeze")
        plan_id = seeded.id
        live_runtime = _runtime(
            (app.state.runtime.memory_service.snapshot(workspace_id).workspace or {})
        )
        assert str(live_runtime.get("plan_id") or live_runtime.get("planId") or "").strip() == plan_id

        frozen = client.post(
            "/plan/update",
            json={
                "plan_id": plan_id,
                "workspace_id": workspace_id,
                "frozen": True,
                "expected_revision": app.state.runtime.repository.get_plan_revision(
                    workspace_id, plan_id
                ),
            },
        )
        assert frozen.status_code == 200, frozen.text
        updated = frozen.json().get("plan") or frozen.json()
        assert updated.get("frozen") is True
        assert str(updated.get("id") or updated.get("plan_id") or "").strip() == plan_id
        after_runtime = _runtime((frozen.json().get("memory") or {}).get("workspace") or {})
        if after_runtime:
            asserted_id = str(
                after_runtime.get("plan_id") or after_runtime.get("planId") or ""
            ).strip()
            if asserted_id:
                assert asserted_id == plan_id
        stored = app.state.runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.id == plan_id
        assert stored.frozen is True


def test_plan_update_leftover_not_live_does_not_resurrect(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-update-leftover"
    leftover_title = "Keep the leftover stage"
    leftover_step = "Keep one auth check"
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Leftover plan update lab"},
        )
        assert started.status_code == 200, started.text
        leftover = LearningPlan(
            id="plan-leftover-update",
            title=leftover_title,
            current_step=leftover_step,
            why_now="Keep the leftover why",
            next_after_current="Then review the leftover path",
            stages=[
                PlanStage(
                    id="stage-leftover",
                    title="Leftover",
                    goal="Stay leftover-not-live",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        runtime = app.state.runtime
        runtime.repository.save_plan(workspace_id, leftover)
        runtime.memory_service.structured_for_workspace(workspace_id).update_workspace(
            latest_plan_runtime={
                "current_step": leftover_step,
                "plan_id": "",
                "resume_state": "in_progress",
                "workspace_id": workspace_id,
            }
        )
        recovered = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert not leftover_formal_plan_is_live_for_fill(
            plan=leftover,
            runtime=recovered,
            existing=recovered,
        )

        response = client.post(
            "/plan/update",
            json={
                "plan_id": leftover.id,
                "workspace_id": workspace_id,
                "frozen": True,
                "expected_revision": runtime.repository.get_plan_revision(
                    workspace_id, leftover.id
                ),
            },
        )
        assert response.status_code == 409, response.text
        detail = str(response.json().get("detail") or "")
        assert "leftover-not-live" in detail.lower() or "leftover" in detail.lower()
        body = response.json()
        assert body.get("plan") in (None, {}, "")
        stored = runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.id == leftover.id
        assert stored.title == leftover_title
        assert stored.current_step == leftover_step
        assert stored.frozen is False
        after = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert str(after.get("plan_id") or "").strip() in {"", "None"}
        assert after.get("current_step") == leftover_step


def test_plan_update_empty_recovered_plan_id_stays_fail_closed(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-update-empty-id"
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Empty plan_id lab"},
        )
        assert started.status_code == 200, started.text
        leftover = LearningPlan(
            id="plan-empty-runtime-id",
            title="Stored but not live",
            current_step="Do not resurrect this step",
            why_now="Leftover why",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Stored",
                    goal="Remain leftover",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        runtime = app.state.runtime
        runtime.repository.save_plan(workspace_id, leftover)
        runtime.memory_service.persist_plan_runtime_recovery(
            workspace_id,
            plan_runtime={
                "current_step": "Advanced overlay step",
                "plan_id": "",
                "resume_state": "in_progress",
            },
            request_id="plan-update-empty-id-1",
        )

        response = client.post(
            "/plan/update",
            json={
                "plan_id": leftover.id,
                "workspace_id": workspace_id,
                "instructions": "Rewrite leftover as if it were live.",
                "expected_revision": runtime.repository.get_plan_revision(
                    workspace_id, leftover.id
                ),
            },
        )
        assert response.status_code == 409, response.text
        stored = runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.id == leftover.id
        assert stored.current_step == "Do not resurrect this step"
        assert "rewrite leftover" not in (stored.summary or "").lower()
        recovered = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert recovered.get("current_step") == "Advanced overlay step"
        assert recovered.get("plan_id") in {None, ""}


# ---------------------------------------------------------------------------
# Restored from test_training_review_context.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def review_memory(status="active", mode="review_queue"):
    return MemorySnapshot(workspace={"latest_training_submode": mode}, review_artifact=ReviewArtifactSnapshot(
        id="review-one", title="复习：元组槽位", focus_area="元组槽位", status=status,
        summary="解释槽位与引用对象的区别。", guardrail="先闭卷，再核对例子。",
        verified_result="我的概念复述。" if status == "resolved" else "",
    ))


@pytest.mark.parametrize("status", ["active", "resolved"])
@pytest.mark.parametrize("mode", ["review", "review_queue", "review-queue"])
def test_review_feedback_does_not_inherit_old_practice_contract(status, mode):
    context = {"current_focus": "旧实现", "exercise_prompt": {"acceptance_criteria": ["旧断言"]},
               "review_rhythm": "旧断言", "weak_spots": ["旧断言"],
               "plan_runtime_recovery": {"current_step": "旧断言"},
               "active_training_card_routing": {"selected_card": {"title": "旧卡"}},
               "memory": {"review_rhythm": "旧断言", "weaknesses": ["旧断言"],
                          "workspace": {"latest_training_handoff": {"status": "completed"}},
                          "training_event_ledger": [{"verification_steps": ["旧断言"]}]}}
    before = copy.deepcopy(context)
    result = apply_training_review_context(context, review_memory(status, mode), "training")
    assert result["review_artifact"]["id"] == "review-one"
    assert result["review_evidence_scope"] == "self_reported_recall"
    assert result["current_focus"] == "元组槽位"
    assert result["exercise_prompt"] is None
    assert result["review_rhythm"] == ""
    assert result["weak_spots"] == []
    assert result["plan_runtime_recovery"] is None
    assert result["memory"]["review_rhythm"] == ""
    assert result["memory"]["weaknesses"] == []
    assert "active_training_card_routing" not in result
    assert "training_event_ledger" not in result["memory"]
    assert "latest_training_handoff" not in result["memory"]["workspace"]
    assert context == before


@pytest.mark.parametrize("view,mode,status", [("coach", "review", "active"),
                                               ("training", "practice", "active"),
                                               ("training", "review", "archived")])
def test_review_context_only_applies_to_the_selected_review_surface(view, mode, status):
    memory = review_memory(status, mode)
    context = {"current_focus": "Current practice"}
    assert active_training_review(memory, view) is None
    assert apply_training_review_context(context, memory, view) is context


def test_current_review_prompt_reaches_the_model_without_old_coding_history():
    from app.core.models import UserProfile
    from app.llm.prompts import build_coaching_messages

    context = apply_training_review_context({"scenario": "review"}, review_memory("resolved"),
                                            "training")
    messages = build_coaching_messages(UserProfile(long_term_goal="Learn Python"),
        "评价我的概念复习。", None, response_language="zh-CN", coach_context=context,
        history=[{"role": "assistant", "content": "旧断言已经通过4条，追加第5条。"}])
    prompt = str(messages)
    assert "Current Recall Review" in prompt
    assert "解释槽位与引用对象的区别。" in prompt
    assert "我的概念复述。" in prompt
    assert "self-reported concept recall" in prompt
    assert "旧断言" not in prompt


# ---------------------------------------------------------------------------
# Restored from test_training_skill_evidence.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("trust", ["self_reported", "model_review", "static_analysis", ""])
@pytest.mark.parametrize("assistance", ["independent", "hint_level_2"])
def test_unexecuted_success_cannot_verify_capability(trust: str, assistance: str) -> None:
    dimension = project_skills([{
        "evidence_id": "self-report", "result": "passed", "is_current": True,
        "trust_level": trust, "assistance_level": assistance,
    }])["implementation"]
    assert dimension["state"] == "not_verified"
    assert dimension["verified_count"] == 0
    assert dimension["independent_attempt_count"] == 0
    assert dimension["evidence_ids"] == ["self-report"]


def test_verified_attempt_is_resumed_until_explicit_return(tmp_path: Path) -> None:
    from app.training.attempt_store import AttemptStore

    store = AttemptStore(tmp_path / "attempts.db")
    original = store.start_attempt(workspace_id="ws", card_id="card", file_hash="hash", file_version=3)
    store.record_evidence(attempt_id=original["attempt_id"], artifact_hash="hash", result="passed")
    resumed = store.start_attempt(workspace_id="ws", card_id="card")
    assert resumed["attempt_id"] == original["attempt_id"]
    assert resumed["file_version"] == 3
    store.close_attempt(original["attempt_id"], workspace_id="ws")
    assert store.start_attempt(workspace_id="ws", card_id="card")["attempt_id"] != original["attempt_id"]


def test_missing_assistance_is_unknown_and_never_advances_the_skill_ladder() -> None:
    dimension = project_skills([{
        "evidence_id": "legacy-controlled-check",
        "result": "passed",
        "is_current": True,
        "trust_level": "controlled_check",
        # assistance_level is absent in legacy/partial records.
    }])["implementation"]

    assert dimension["state"] == "not_verified"
    assert dimension["independent_attempt_count"] == 0
    assert dimension["independent_evidence_count"] == 0
    assert dimension["evidence"][0]["assistance_level"] == "unknown"

    explicit = project_skills([{
        "evidence_id": "independent-controlled-check",
        "result": "passed",
        "is_current": True,
        "trust_level": "controlled_check",
        "assistance_level": "independent",
    }])["implementation"]
    assert explicit["state"] == "independent"
    assert explicit["independent_attempt_count"] == 1


# ---------------------------------------------------------------------------
# Restored from test_task_tool_live_plan_gate.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_pressure_deny_list_includes_specify_and_next_task() -> None:
    extra = _build_agent_tool_context_extra(
        coach_context={
            "scenario": "general",
            "live_formal_plan_for_task_mint": True,
            "pressure_blocks_live_object_mint": True,
        },
        attachment_delivery={"attachments_present": False},
        answer_mode="guided",
        current_file=None,
        learner_message="Specify the next task for token refresh.",
    )
    assert "specify_task" in extra["denied_tool_names"]
    assert "next_task" in extra["denied_tool_names"]
    assert "generate_training_card" in extra["denied_tool_names"]


def test_http_task_specify_after_plan_generate_still_works(tmp_path: Path) -> None:
    workspace_id = "workspace-http-specify-still"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "HTTP still works"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Ship one HTTP specify slice"],
            },
        )
        assert generated.status_code == 200, generated.text
        plan_id = str(
            (generated.json().get("plan") or generated.json()).get("id")
            or (generated.json().get("plan") or generated.json()).get("plan_id")
            or ""
        ).strip()
        assert plan_id
        specified = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "natural_language_goal": "Add one expiry check",
            },
        )
        assert specified.status_code == 200, specified.text
        task = specified.json()
        assert task.get("title")
        assert str((task.get("metadata") or {}).get("plan_id") or "").strip() == plan_id


# ---------------------------------------------------------------------------
# Restored from test_training_runtime_handoff.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    (
        "case",
        "passed",
        "summary",
        "evidence_source",
        "verified_by_evaluator",
        "expected_card_status",
        "expected_verification_state",
        "expected_return_state",
        "expected_return_mode",
    ),
    [
        pytest.param(
            "verified",
            True,
            "Focused test passed with no diagnostics.",
            "test_runner",
            True,
            "active",
            "verified",
            "return_to_coach",
            "reflection_required",
            id="trusted-verification",
        ),
        pytest.param(
            "pending",
            True,
            "Focused test output is awaiting evaluator attestation.",
            "test_runner",
            False,
            "active",
            "verification_required",
            "verify_then_return",
            "verification_required",
            id="pending-verification",
        ),
        pytest.param(
            "blocked",
            False,
            "The focused check still fails on the boundary case.",
            "ide_current_file",
            True,
            "blocked",
            "blocked",
            "resume_training",
            "blocker",
            id="explicit-blocker",
        ),
        pytest.param(
            "self-report",
            True,
            "I ran it locally and it works.",
            "learner_return",
            True,
            "active",
            "verification_required",
            "verify_then_return",
            "verification_required",
            id="untrusted-self-report",
        ),
        pytest.param(
            "missing-evidence",
            True,
            "",
            "test_runner",
            True,
            "active",
            "evidence_required",
            "resume_training",
            "verification_required",
            id="evaluator-attestation-without-evidence",
        ),
    ],
)
def test_practice_handoff_state_is_persisted_without_overclaiming_completion(
    tmp_path: Path,
    case: str,
    passed: bool,
    summary: str,
    evidence_source: str,
    verified_by_evaluator: bool,
    expected_card_status: str,
    expected_verification_state: str,
    expected_return_state: str,
    expected_return_mode: str,
) -> None:
    database_path = tmp_path / f"{case}.db"
    workspace_id = f"workspace-{case}"
    card = TrainingCardCandidateSnapshot(
        card_id=f"card-{case}",
        card_type="practice",
        title="Verify one parser boundary",
        target_skill="parser boundary",
        status="active",
        validation_method="Run the focused parser test.",
    )
    service = MemoryService(TrainerRepository(database_path))
    service.upsert_card(workspace_id, card)

    result = service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=passed,
        summary=summary,
        next_step="Run the focused parser test again.",
        focus_area="parser boundary",
        evidence_source=evidence_source,
        verified_by_evaluator=verified_by_evaluator,
    )

    handoff = result["latest_training_handoff"]
    assert result["selected_card_status"] == expected_card_status
    assert handoff["verification_state"] == expected_verification_state
    assert handoff["return_state"] == expected_return_state
    assert handoff["return_mode"] == expected_return_mode
    assert handoff["resume_token"]
    assert handoff["handoff_id"]

    if expected_verification_state == "verified":
        assert handoff["handoff_content"]["success_signal"]
        assert "not a claim of durable mastery" in handoff["handoff_content"]["completion_claim"]
        assert handoff["evidence"] and handoff["evidence"][0]["verified"] is True
        assert handoff["learning_phase"] == TrainingPhase.VERIFY.value
        assert handoff["status"] != HandoffStatus.COMPLETED.value
        assert result["latest_learning_verified_result"] == ""
    else:
        success_signal = handoff["handoff_content"]["success_signal"].lower()
        completion_claim = handoff["handoff_content"]["completion_claim"].lower()
        assert "mastered" not in success_signal
        assert "supports this card result" not in completion_claim
        assert all(item["verified"] is False for item in handoff["evidence"])

    rebuilt = MemoryService(TrainerRepository(database_path))
    persisted_handoff = rebuilt.snapshot(workspace_id).workspace["latest_training_handoff"]
    assert persisted_handoff["handoff_id"] == handoff["handoff_id"]
    assert persisted_handoff["verification_state"] == expected_verification_state
    assert persisted_handoff["return_state"] == expected_return_state

    restored_record = TrainingHandoffGenerator._handoff_from_payload(persisted_handoff)
    assert restored_record is not None
    assert restored_record.verification_state == expected_verification_state
    assert restored_record.return_state == expected_return_state


def test_practice_handoff_implements_only_after_recovered_terminal_return(tmp_path: Path) -> None:
    database_path = tmp_path / "returned-handoff.db"
    workspace_id = "workspace-returned-handoff"
    card = TrainingCardCandidateSnapshot(
        card_id="card-returned-handoff",
        card_type="practice",
        title="Verify one parser boundary",
        target_skill="parser boundary",
        status="active",
        validation_method="Run the focused parser test.",
    )
    service = MemoryService(TrainerRepository(database_path))
    service.upsert_card(workspace_id, card)

    generator = TrainingHandoffGenerator()
    terminal = generator.build_handoff_record(
        card,
        {
            "correct": True,
            "evidence": ["Focused test passed with no diagnostics."],
            "evidence_source": "test_runner",
            "verified_by_evaluator": True,
        },
    )
    generator.record_reflection(terminal.handoff_id, "The focused check proved the parser boundary.")
    generator.return_handoff(terminal.handoff_id)
    assert terminal.phase is TrainingPhase.RETURN
    assert terminal.status is HandoffStatus.COMPLETED

    service._structured_for(workspace_id).update_workspace(
        latest_training_handoff=TrainingHandoffGenerator._handoff_payload(terminal)
    )
    service._persist_structured(workspace_id)
    restarted = MemoryService(TrainerRepository(database_path))

    result = restarted.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="Focused test passed with no diagnostics.",
        next_step="Continue with the next card.",
        focus_area="parser boundary",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )

    stored = restarted.get_card(workspace_id, card.card_id)
    assert stored is not None
    assert stored.status == "implemented"
    assert result["selected_card_status"] == "implemented"
    assert result["latest_training_handoff"]["learning_phase"] == TrainingPhase.RETURN.value
    assert result["latest_training_handoff"]["status"] == HandoffStatus.COMPLETED.value


# ---------------------------------------------------------------------------
# Restored from test_formal_plan_stage_constraints.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('message', 'expected'),
    [
        ('分为3个阶段，从第1阶段开始，保留第3阶段', 3),
        ('生成三个阶段，每天20分钟', 3),
        ('Build a 3-stage plan. Start stage 1.', 3),
        ('Make a plan with 12 stages.', 12),
        ('解释第3阶段，保持第1阶段', None),
        ('Explain stage 3.', None),
    ],
)
def test_explicit_stage_count_does_not_confuse_stage_numbers(message, expected):
    assert _explicit_formal_plan_stage_count(message) == expected


# ---------------------------------------------------------------------------
# Restored from test_plan_change_candidates.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_non_plan_feedback_does_not_create_candidate(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            AppSettings(
                app_name="Candidate Test",
                host="127.0.0.1",
                port=8765,
                default_session_stage="intake",
                summary_message_limit=6,
                data_dir=tmp_path,
                database_name="candidate-noop.db",
                enable_network_fetch=False,
            )
        )
    )
    with client:
        response = client.post(
            "/memory/feedback",
            json={
                "workspace_id": "workspace-feedback-noop",
                "kind": "too_hard",
                "message": "This is too hard.",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["memory"]["planChangeCandidates"] == []


# ---------------------------------------------------------------------------
# Restored from test_write_tool_implicit_activation.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_explicit_learning_note_language_bar_stays_tight() -> None:
    assert message_requests_explicit_learning_note(
        "Save a learning note that I prefer tiny verified slices."
    )
    assert message_requests_explicit_learning_note("Record a learning note about the remote boundary.")
    assert message_requests_explicit_learning_note("\u8bb0\u4e0b\u4e00\u6761\u5b66\u4e60\u7b14\u8bb0")
    assert not message_requests_explicit_learning_note(
        "Help me understand this VS Code remote workspace first, then verify one tiny step."
    )
    assert not message_requests_explicit_learning_note("What is a learning note?")
    assert not message_requests_explicit_learning_note("Remember to check the remote host label.")
    assert not message_requests_explicit_learning_note("continue")


# ---------------------------------------------------------------------------
# Restored from test_training_plan_binding.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_unbound_request_cannot_invent_a_formal_identity():
    assert validated_mint_binding(None, source="conversation_gap", plan=None, runtime={}, revision=0) is None


# ---------------------------------------------------------------------------
# Restored from test_training_card_implicit_activation.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_explicit_training_card_language_bar_matches_router_and_tool() -> None:
    assert message_requests_explicit_training_card(
        "Create a practice card for debugging a Python traceback in VS Code."
    )
    assert message_requests_explicit_training_card("Give me a flash card for Remote SSH.")
    assert message_requests_explicit_training_card("把这道题保存为训练卡")
    assert not message_requests_explicit_training_card(
        "Help me understand this VS Code remote workspace first, then verify one tiny step."
    )
    assert not message_requests_explicit_training_card("What is a training card?")
    assert not message_requests_explicit_training_card("continue")
    # Instant practice: asking for an exercise never authorizes a card.
    assert not message_requests_explicit_training_card("给我一道练习。")
    assert not message_requests_explicit_training_card("来一道题，检验一下锁的行为。")
    assert not message_requests_explicit_training_card("考考我锁在异常时怎么释放")
    assert not message_requests_explicit_training_card(
        "Give me a practice exercise about locks and exceptions."
    )
    assert not message_requests_explicit_training_card("quiz me on Python locks")
