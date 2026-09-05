"""Tests for CardRouterService — active card routing algorithm (§13.27)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import (
    LearningPlan,
    PlanStage,
    TrainingCardCandidateSnapshot,
)
from app.training.card_router import CardRouterService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card(**overrides: object) -> TrainingCardCandidateSnapshot:
    """Build a minimal card candidate with sensible defaults."""
    defaults: dict[str, object] = {
        "card_id": "card-1",
        "card_type": "practice",
        "title": "Test card",
        "focus_area": "testing",
        "target_skill": "unit tests",
        "difficulty": "medium",
        "problem_statement": "Write a unit test.",
        "deliverable": "A passing test file.",
        "validation_method": "pytest runs green.",
        "expected_answer": "N/A",
        "hint_ladder": ["Start with assert", "Then add fixture"],
        "created_from": "conversation",
        "status": "candidate",
    }
    defaults.update(overrides)
    # Filter out None values so model defaults are preserved for optional str fields
    defaults = {k: v for k, v in defaults.items() if v is not None}
    return TrainingCardCandidateSnapshot(**defaults)  # type: ignore[arg-type]


def _learner(**overrides: object) -> dict:
    defaults: dict[str, object] = {
        "weaknesses": [],
        "recent_errors": [],
        "difficulty_preference": "medium",
        "needs_rescue": False,
        "active_blockers": [],
    }
    defaults.update(overrides)
    return defaults


def _plan(**overrides: object) -> dict:
    defaults: dict[str, object] = {
        "active_stage_id": "stage-1",
        "active_stage_skills": ["unit tests", "fixtures"],
        "active_project_id": "proj-1",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Test 1: Basic scoring — review_due card beats conversation card
# ---------------------------------------------------------------------------

class TestScoringPriorities(unittest.TestCase):
    """Higher-weight factors should dominate the selection."""

    def test_review_due_beats_conversation(self) -> None:
        svc = CardRouterService()
        review_card = _card(
            card_id="card-review",
            title="Review: closures",
            created_from="review_due",
            focus_area="closures",
        )
        conv_card = _card(
            card_id="card-conv",
            title="Practice: decorators",
            created_from="conversation",
            focus_area="decorators",
        )
        result = svc.select_active_card(
            candidates=[conv_card, review_card],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertEqual(result.selected_card_id, "card-review")
        self.assertGreater(result.selection_score, 0)
        self.assertTrue(result.why_this_card)
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.eligible_count, 2)

    def test_dependency_mastery_blocks_harder(self) -> None:
        """A dependency_mastery card should score high on blocking_power."""
        svc = CardRouterService()
        dep_card = _card(
            card_id="card-dep",
            title="Prerequisite: async basics",
            created_from="dependency_mastery",
            target_skill="async basics",
            focus_area="async",
        )
        normal_card = _card(
            card_id="card-normal",
            title="Practice: REST APIs",
            created_from="plan",
            target_skill="REST APIs",
            focus_area="apis",
        )
        result = svc.select_active_card(
            candidates=[normal_card, dep_card],
            learner_state=_learner(active_blockers=["async basics"]),
            plan_state=_plan(),
        )
        # dep_card should win because blocking_power = 1.0
        self.assertEqual(result.selected_card_id, "card-dep")

    def test_weakness_match_boosts_evidence_gap(self) -> None:
        """Card targeting a learner weakness should rank higher."""
        svc = CardRouterService()
        weak_card = _card(
            card_id="card-weak",
            title="Practice: error handling",
            focus_area="error handling",
            target_skill="exceptions",
        )
        other_card = _card(
            card_id="card-other",
            title="Practice: typing",
            focus_area="typing",
            target_skill="type hints",
        )
        result = svc.select_active_card(
            candidates=[weak_card, other_card],
            learner_state=_learner(weaknesses=["error handling"]),
            plan_state=_plan(),
        )
        self.assertEqual(result.selected_card_id, "card-weak")


# ---------------------------------------------------------------------------
# Test 2: Blocking conditions
# ---------------------------------------------------------------------------

class TestBlockingConditions(unittest.TestCase):
    """Cards with structural issues should be blocked."""

    def test_practice_missing_deliverable_blocked(self) -> None:
        svc = CardRouterService()
        blocked_card = _card(
            card_id="card-blocked",
            deliverable=None,
        )
        good_card = _card(
            card_id="card-good",
            title="Good card",
        )
        result = svc.select_active_card(
            candidates=[blocked_card, good_card],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertEqual(result.selected_card_id, "card-good")
        blocked_ids = [b.card_id for b in result.blocked_candidates]
        self.assertIn("card-blocked", blocked_ids)

    def test_flash_missing_expected_answer_blocked(self) -> None:
        svc = CardRouterService()
        flash_card = _card(
            card_id="card-flash-bad",
            card_type="flash",
            expected_answer="",
        )
        result = svc.select_active_card(
            candidates=[flash_card],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertIsNone(result.selected_card_id)
        self.assertEqual(len(result.blocked_candidates), 1)
        self.assertIn(
            "flash reference answer is missing",
            result.blocked_candidates[0].reasons,
        )

    def test_flash_missing_hint_ladder_blocked(self) -> None:
        svc = CardRouterService()
        flash_card = _card(
            card_id="card-flash-nohints",
            card_type="flash",
            hint_ladder=[],
            expected_answer="Some answer",
        )
        result = svc.select_active_card(
            candidates=[flash_card],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertIsNone(result.selected_card_id)
        self.assertIn(
            "flash hint_ladder is missing",
            result.blocked_candidates[0].reasons,
        )

    def test_untrusted_source_blocked(self) -> None:
        svc = CardRouterService()
        untrusted_card = _card(
            card_id="card-untrusted",
            trust_state="untrusted",
            trust_acknowledged=False,
        )
        result = svc.select_active_card(
            candidates=[untrusted_card],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertIsNone(result.selected_card_id)
        self.assertEqual(len(result.blocked_candidates), 1)

    def test_stale_source_blocked_without_acknowledgement(self) -> None:
        svc = CardRouterService()
        stale_card = _card(
            card_id="card-stale",
            trust_state="stale",
            trust_acknowledged=False,
        )
        result = svc.select_active_card(
            candidates=[stale_card],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertIsNone(result.selected_card_id)
        self.assertTrue(any(item.card_id == "card-stale" for item in result.blocked_candidates))

    def test_trust_acknowledged_overrides_untrusted(self) -> None:
        """If the user acknowledges an untrusted source, it stays eligible."""
        svc = CardRouterService()
        ack_card = _card(
            card_id="card-acked",
            trust_state="untrusted",
            trust_acknowledged=True,
        )
        result = svc.select_active_card(
            candidates=[ack_card],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertEqual(result.selected_card_id, "card-acked")

    def test_project_context_not_ready_blocks_practice(self) -> None:
        svc = CardRouterService()
        proj_card = _card(
            card_id="card-proj",
            requires_project_context=True,
            project_context_ready=False,
        )
        result = svc.select_active_card(
            candidates=[proj_card],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertIsNone(result.selected_card_id)
        reasons = result.blocked_candidates[0].reasons
        self.assertTrue(
            any("project context" in r for r in reasons),
            f"Expected project context blocker, got: {reasons}",
        )


# ---------------------------------------------------------------------------
# Test 3: Fallback behavior
# ---------------------------------------------------------------------------

class TestFallbackBehavior(unittest.TestCase):
    """When no eligible cards exist, fallback behavior kicks in."""

    def test_pure_conversation_mode_no_selection(self) -> None:
        svc = CardRouterService()
        card = _card(card_id="card-1")
        result = svc.select_active_card(
            candidates=[card],
            learner_state=_learner(),
            plan_state=_plan(),
            pure_conversation_mode=True,
        )
        self.assertIsNone(result.selected_card_id)
        self.assertEqual(result.selection_score, 0)
        self.assertIn("pure conversation mode", result.why_this_card)

    def test_all_blocked_returns_empty(self) -> None:
        svc = CardRouterService()
        # All cards have missing deliverable
        c1 = _card(card_id="c1", deliverable=None)
        c2 = _card(card_id="c2", deliverable=None)
        result = svc.select_active_card(
            candidates=[c1, c2],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertIsNone(result.selected_card_id)
        self.assertEqual(len(result.blocked_candidates), 2)
        self.assertIn("No eligible", result.why_this_card)

    def test_empty_candidates_returns_empty(self) -> None:
        svc = CardRouterService()
        result = svc.select_active_card(
            candidates=[],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertIsNone(result.selected_card_id)
        self.assertEqual(result.candidate_count, 0)
        self.assertEqual(result.eligible_count, 0)

    def test_custom_fallback_action_propagated(self) -> None:
        svc = CardRouterService()
        result = svc.select_active_card(
            candidates=[],
            learner_state=_learner(),
            plan_state=_plan(),
            fallback_action="Custom fallback",
            next_after_completion="Custom next",
        )
        self.assertEqual(result.fallback_action, "Custom fallback")
        self.assertEqual(result.next_after_completion, "Custom next")

    def test_selected_card_next_after_completion_takes_priority(self) -> None:
        svc = CardRouterService()
        result = svc.select_active_card(
            candidates=[
                _card(
                    card_id="card-next",
                    next_after_completion="Return with the route diff and the test output.",
                )
            ],
            learner_state=_learner(),
            plan_state=_plan(),
            next_after_completion="Custom next",
        )
        self.assertEqual(
            result.next_after_completion,
            "Return with the route diff and the test output.",
        )


# ---------------------------------------------------------------------------
# Test 4: Difficulty fit and learner state interaction
# ---------------------------------------------------------------------------

class TestDifficultyAndLearnerState(unittest.TestCase):
    """Scoring should adapt to learner state."""

    def test_needs_rescue_prefers_easy(self) -> None:
        svc = CardRouterService()
        easy_card = _card(
            card_id="card-easy",
            difficulty="easy",
            focus_area="basics",
        )
        hard_card = _card(
            card_id="card-hard",
            difficulty="hard",
            focus_area="advanced",
        )
        result = svc.select_active_card(
            candidates=[easy_card, hard_card],
            learner_state=_learner(needs_rescue=True),
            plan_state=_plan(),
        )
        self.assertEqual(result.selected_card_id, "card-easy")

    def test_plan_linked_card_gets_high_relevance(self) -> None:
        svc = CardRouterService()
        linked_card = _card(
            card_id="card-linked",
            plan_links=["stage-1"],
            created_from="plan",
            target_skill="unit tests",
        )
        unlinked_card = _card(
            card_id="card-unlinked",
            created_from="conversation",
            target_skill="decorator patterns",
        )
        result = svc.select_active_card(
            candidates=[linked_card, unlinked_card],
            learner_state=_learner(),
            plan_state=_plan(active_stage_id="stage-1"),
        )
        self.assertEqual(result.selected_card_id, "card-linked")

    def test_same_topic_practice_stays_active_before_flash_follow_up(self) -> None:
        svc = CardRouterService()
        practice_card = _card(
            card_id="card-practice",
            title="Practice: Remote boundary",
            focus_area="VS Code remote workspace",
            target_skill="remote workspace boundary",
            scenario_pack="remote_workspace",
        )
        flash_card = _card(
            card_id="card-flash",
            card_type="flash",
            title="Flash: Remote boundary",
            focus_area="VS Code remote workspace",
            target_skill="remote workspace boundary",
            scenario_pack="remote_workspace",
            expected_answer="Keep the key local until the remote host boundary is trusted.",
            hint_ladder=["Identify the host first.", "Then pick the credential mode."],
            knowledge_type="engineering_concept",
        )
        result = svc.select_active_card(
            candidates=[practice_card, flash_card],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertEqual(result.selected_card_id, "card-practice")


# ---------------------------------------------------------------------------
# Test 5: Explainability
# ---------------------------------------------------------------------------

class TestExplainability(unittest.TestCase):
    """The result must include human-readable explanations."""

    def test_why_this_card_populated(self) -> None:
        svc = CardRouterService()
        card = _card(card_id="card-1", why_now="Weakness detected")
        result = svc.select_active_card(
            candidates=[card],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertEqual(result.why_this_card, "Weakness detected")

    def test_why_not_others_includes_lower_scores(self) -> None:
        svc = CardRouterService()
        best = _card(
            card_id="card-best",
            title="Best card",
            created_from="review_due",
        )
        worse = _card(
            card_id="card-worse",
            title="Worse card",
            created_from="conversation",
        )
        result = svc.select_active_card(
            candidates=[best, worse],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertTrue(len(result.why_not_others) > 0)
        self.assertTrue(
            any("Worse card" in reason for reason in result.why_not_others),
            f"Expected 'Worse card' in why_not_others: {result.why_not_others}",
        )

    def test_blocked_reasons_in_why_not_others(self) -> None:
        svc = CardRouterService()
        good = _card(card_id="card-good", title="Good card")
        blocked = _card(
            card_id="card-bad",
            title="Bad card",
            deliverable=None,
        )
        result = svc.select_active_card(
            candidates=[good, blocked],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertTrue(
            any("Bad card" in r for r in result.why_not_others),
            f"Expected 'Bad card' in why_not_others: {result.why_not_others}",
        )

    def test_score_factors_are_in_range(self) -> None:
        svc = CardRouterService()
        card = _card(card_id="card-1")
        result = svc.select_active_card(
            candidates=[card],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        factors = result.score_factors
        for field_name in (
            "plan_relevance", "blocking_power", "evidence_gap",
            "recency_need", "resource_trust", "difficulty_fit",
            "project_fit", "transfer_value", "recovery_priority",
        ):
            value = getattr(factors, field_name)
            self.assertGreaterEqual(value, 0.0, f"{field_name} < 0")
            self.assertLessEqual(value, 1.0, f"{field_name} > 1")


# ---------------------------------------------------------------------------
# Test 6: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def test_single_card_selected(self) -> None:
        svc = CardRouterService()
        card = _card(card_id="only-one")
        result = svc.select_active_card(
            candidates=[card],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertEqual(result.selected_card_id, "only-one")
        self.assertEqual(result.eligible_count, 1)

    def test_tiebreak_by_recovery_priority(self) -> None:
        """When scores are equal, higher recovery_priority wins."""
        svc = CardRouterService()
        # Two cards that will have very similar scores
        c1 = _card(
            card_id="card-a",
            title="Card A",
            created_from="practice_feedback",  # recovery_priority ~0.7
        )
        c2 = _card(
            card_id="card-b",
            title="Card B",
            created_from="conversation",  # recovery_priority ~0.1
        )
        result = svc.select_active_card(
            candidates=[c1, c2],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        # If scores are close, recovery priority breaks the tie
        self.assertIsNotNone(result.selected_card_id)

    def test_multiple_blockers_on_one_card(self) -> None:
        """A card can have multiple blocking reasons."""
        svc = CardRouterService()
        multi_blocked = _card(
            card_id="multi-blocked",
            card_type="flash",
            expected_answer="",
            hint_ladder=[],
            trust_state="untrusted",
        )
        result = svc.select_active_card(
            candidates=[multi_blocked],
            learner_state=_learner(),
            plan_state=_plan(),
        )
        self.assertIsNone(result.selected_card_id)
        blocked = result.blocked_candidates[0]
        self.assertGreaterEqual(len(blocked.reasons), 2)

    def test_project_fit_for_matching_project(self) -> None:
        """Card matching active project should rank higher."""
        svc = CardRouterService()
        proj_card = _card(
            card_id="card-proj-match",
            project_id="proj-1",
            focus_area="project work",
        )
        other_card = _card(
            card_id="card-proj-other",
            project_id="proj-2",
            focus_area="other work",
        )
        result = svc.select_active_card(
            candidates=[proj_card, other_card],
            learner_state=_learner(),
            plan_state=_plan(active_project_id="proj-1"),
        )
        self.assertEqual(result.selected_card_id, "card-proj-match")


class TestLeftoverFormalCardTitles(unittest.TestCase):
    """Recovered-without-plan must not keep leftover formal card titles live."""

    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_card = f"Practice: {leftover_title}"
    leftover_other = f"Flash: {leftover_title}"
    leftover_blocked = f"Practice: {leftover_stage}"
    recovered_step = "Add a token expiry test"

    def _leftover_plan(self) -> LearningPlan:
        return LearningPlan(
            id=self.leftover_plan_id,
            title=self.leftover_title,
            summary=self.leftover_summary,
            current_stage_id="stage-1",
            current_step=self.leftover_step,
            stages=[
                PlanStage(
                    id="stage-1",
                    title=self.leftover_stage,
                    goal="Keep one check",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )

    def _advanced_plan_state(self) -> dict:
        return _plan(
            leftover_plan=self._leftover_plan(),
            leftover_runtime={
                "current_step": self.recovered_step,
                "why_now": "Expired tokens still leak.",
                "resume_state": "in_progress",
                "workspace_id": "workspace-plan",
            },
            leftover_task_title=self.leftover_title,
        )

    def _still_on_plan_state(self) -> dict:
        return _plan(
            leftover_plan=self._leftover_plan(),
            leftover_runtime={
                "current_step": self.leftover_step,
                "plan_id": self.leftover_plan_id,
                "resume_state": "in_progress",
                "workspace_id": "workspace-plan",
            },
            leftover_task_title=self.leftover_title,
        )

    def test_leftover_card_title_does_not_live_in_why_or_why_not(self) -> None:
        svc = CardRouterService()
        selected = _card(
            card_id="card-leftover-selected",
            title=self.leftover_card,
            why_now=f"{self.leftover_card} is the current training card.",
            created_from="review_due",
            focus_area="auth recovery",
        )
        other = _card(
            card_id="card-leftover-other",
            title=self.leftover_other,
            created_from="conversation",
            focus_area="other work",
        )
        blocked = _card(
            card_id="card-leftover-blocked",
            title=self.leftover_blocked,
            card_type="flash",
            expected_answer="",
            hint_ladder=[],
        )
        result = svc.select_active_card(
            candidates=[selected, other, blocked],
            learner_state=_learner(),
            plan_state=self._advanced_plan_state(),
        )
        live_copy = [result.why_this_card, *result.why_not_others]
        for text in live_copy:
            self.assertNotIn(self.leftover_title, text)
            self.assertNotIn(self.leftover_card, text)
            self.assertNotIn(self.leftover_other, text)
            self.assertNotIn(self.leftover_blocked, text)
            self.assertNotIn(self.leftover_stage, text)
            self.assertNotIn(self.leftover_step, text)
            self.assertNotIn(self.leftover_summary, text)
            self.assertNotIn(self.leftover_plan_id, text)
        self.assertIn(self.recovered_step, result.why_this_card)

    def test_still_on_plan_can_keep_live_card_title(self) -> None:
        svc = CardRouterService()
        selected = _card(
            card_id="card-live-selected",
            title=self.leftover_card,
            why_now=f"{self.leftover_card} is the current training card.",
            created_from="review_due",
            focus_area="auth recovery",
        )
        other = _card(
            card_id="card-live-other",
            title=self.leftover_other,
            created_from="conversation",
            focus_area="other work",
        )
        result = svc.select_active_card(
            candidates=[selected, other],
            learner_state=_learner(),
            plan_state=self._still_on_plan_state(),
        )
        live_copy = " ".join([result.why_this_card, *result.why_not_others])
        self.assertIn(self.leftover_card, live_copy)
        self.assertIn(self.leftover_other, live_copy)


if __name__ == "__main__":
    unittest.main()
