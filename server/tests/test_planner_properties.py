"""Property-based tests for TrainingPlannerService using Hypothesis."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.memory.models import MasteryRecord, WeaknessRecord, utc_now
from app.planner import NextTaskContext, TrainingPlannerService
from app.planner.models import TaskDifficulty


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


if __name__ == "__main__":
    import unittest
    unittest.main()
