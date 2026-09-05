from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import LearningPlan as ApiLearningPlan
from app.core.models import MemorySnapshot as ApiMemorySnapshot
from app.core.models import PlanPhase as ApiPlanPhase
from app.core.models import PlanStage, ReviewQueueItem, UserProfile
from app.memory.models import MasteryRecord, WeaknessRecord, utc_now
from app.planner import NextTaskContext, PlannerService, TrainingPlannerService


class PlannerTests(unittest.TestCase):
    def test_due_weakness_beats_phase_progression(self) -> None:
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal="Learn FastAPI and testing",
            weekly_hours=6,
            teaching_style="guided",
            direct_answer_policy="hint-first",
        )
        weakness = WeaknessRecord(concept="testing", reason="missed assertions", severity=3, next_review_at=utc_now())
        recommendation = planner.recommend_next_task(NextTaskContext(plan=plan, weaknesses=[weakness]))
        self.assertTrue(recommendation.review)
        self.assertEqual(recommendation.concepts, ["testing"])

    def test_success_streak_increases_difficulty(self) -> None:
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal="Learn resource ingestion",
            weekly_hours=4,
            teaching_style="coach",
            direct_answer_policy="hint-first",
        )
        recommendation = planner.recommend_next_task(
            NextTaskContext(
                plan=plan,
                mastery=[MasteryRecord(concept="learn", score=0.8, confidence=0.8)],
                recent_attempts=[{"passed": True}, {"passed": True}, {"passed": True}],
            )
        )
        self.assertEqual(recommendation.difficulty.value, "hard")

    def test_due_review_beats_due_weakness(self) -> None:
        planner = TrainingPlannerService()
        plan = planner.generate_plan(
            goal="Learn FastAPI testing and review rhythm",
            weekly_hours=6,
            teaching_style="guided",
            direct_answer_policy="hint-first",
        )
        weakness = WeaknessRecord(
            concept="testing",
            reason="missed assertions",
            severity=3,
            next_review_at=utc_now(),
        )
        recommendation = planner.recommend_next_task(
            NextTaskContext(
                plan=plan,
                weaknesses=[weakness],
                due_reviews=[
                    ReviewQueueItem(
                        concept="recursion",
                        reason="A real recall item is due now.",
                        due_at=(utc_now() - timedelta(hours=1)).isoformat(),
                        source="mastery",
                        severity="high",
                        surface_mode="due",
                        task_hint="Patch the recursive base case and rerun the smallest check.",
                        focus_area="recursion",
                        linked_context="server/app/solver.py",
                        interval_days=0,
                        mastery_score=0.2,
                    )
                ],
            )
        )
        self.assertTrue(recommendation.review)
        self.assertEqual(recommendation.metadata["source"], "due_review")
        self.assertEqual(recommendation.concepts, ["recursion"])
        self.assertEqual(recommendation.metadata["review_surface_mode"], "due")
        self.assertIn("base case", recommendation.prompt.lower())

    def test_focus_area_generates_progression_not_fake_review(self) -> None:
        planner = PlannerService(TrainingPlannerService())
        profile = UserProfile(
            long_term_goal="Learn FastAPI testing",
            weekly_hours=4,
            teaching_style="guided",
            answer_policy="guided",
        )
        task = planner.next_task(profile, "testing")
        self.assertIn("testing", task.natural_language_goal.lower())
        self.assertFalse(task.title.startswith("Review:"))
        self.assertFalse(task.title.startswith("复习："))

    def test_existing_plan_stage_is_preserved_for_next_task(self) -> None:
        planner = PlannerService(TrainingPlannerService())
        profile = UserProfile(
            long_term_goal="Build a coach-first trainer",
            weekly_hours=6,
            teaching_style="guided",
            answer_policy="guided",
        )
        plan = ApiLearningPlan(
            id="plan-existing",
            title="Coach-first trainer",
            summary="Keep pushing the existing project forward.",
            stages=[
                PlanStage(
                    id="stage-foundation",
                    title="Foundation",
                    goal="Stabilize the shell",
                    outcomes=["Keep top-level IA narrow"],
                    status="completed",
                ),
                PlanStage(
                    id="stage-practice",
                    title="Practice",
                    goal="Deepen coach-first backend behavior",
                    outcomes=["Push planner and memory deeper"],
                    status="active",
                ),
            ],
            current_stage_id="stage-practice",
            phases=[
                ApiPlanPhase(
                    title="Foundation",
                    objective="Stabilize the shell",
                    exercises=["Keep top-level IA narrow"],
                    completion_signal="Done",
                ),
                ApiPlanPhase(
                    title="Practice",
                    objective="Deepen coach-first backend behavior",
                    exercises=["Push planner and memory deeper"],
                    completion_signal="Done",
                ),
            ],
        )
        task = planner.next_task(profile, current_plan=plan)
        self.assertIn("Practice", task.title)
        self.assertIn("planner", task.natural_language_goal.lower())

    def test_low_weekly_hours_narrows_plan(self) -> None:
        planner = TrainingPlannerService()
        narrow_plan = planner.generate_plan(
            goal="Learn FastAPI testing and error handling in Python",
            weekly_hours=2,
            teaching_style="guided",
            direct_answer_policy="hint-first",
        )
        wide_plan = planner.generate_plan(
            goal="Learn FastAPI testing and error handling in Python",
            weekly_hours=8,
            teaching_style="guided",
            direct_answer_policy="hint-first",
        )
        self.assertTrue(all(len(phase.concepts) <= 1 for phase in narrow_plan.phases))
        self.assertTrue(any(len(phase.concepts) >= 2 for phase in wide_plan.phases))

    def test_extract_concepts_prefers_technical_terms(self) -> None:
        planner = TrainingPlannerService()
        concepts = planner._extract_concepts("Learn FastAPI testing and error handling in Python")
        self.assertIn("fastapi", concepts)
        self.assertIn("testing", concepts)
        self.assertIn("error handling", concepts)
        self.assertNotEqual(concepts[0], "learn")

    def test_memory_snapshot_anchor_feeds_progression_focus(self) -> None:
        planner = PlannerService(TrainingPlannerService())
        profile = UserProfile(
            long_term_goal="Build a coach-first trainer",
            weekly_hours=4,
            teaching_style="guided",
            answer_policy="guided",
        )
        snapshot = ApiMemorySnapshot(
            coach_anchor="review rhythm",
            top_weakness="testing",
            due_review_count=0,
            pace_signal="steady",
        )
        task = planner.next_task(profile, memory_snapshot=snapshot)
        self.assertIn("review rhythm", task.natural_language_goal.lower())

    def test_coach_defaults_influence_next_task_prompt(self) -> None:
        planner = PlannerService(TrainingPlannerService())
        profile = UserProfile(
            long_term_goal="Build a coach-first trainer",
            weekly_hours=4,
            teaching_style="guided",
            answer_policy="guided",
        )
        snapshot = ApiMemorySnapshot(
            coach_anchor="review rhythm",
            top_weakness="testing",
            due_review_count=1,
            pace_signal="steady",
            due_reviews=[
                ReviewQueueItem(
                    concept="testing",
                    reason="missed assertions",
                    source="weakness",
                    severity="high",
                    surface_mode="due",
                    task_hint="Patch one failing assertion path first.",
                    focus_area="testing",
                    linked_context="tests/test_api.py",
                    interval_days=0,
                    mastery_score=0.2,
                )
            ],
        )
        task = planner.next_task(
            profile,
            memory_snapshot=snapshot,
            coach_defaults={
                "memory_scope": "project",
                "working_set_mode": "focused",
                "review_cadence": "active",
                "review_reminder_mode": "ahead",
            },
        )
        self.assertIn("review", task.title.lower())
        self.assertIn("surface this review ahead", task.natural_language_goal.lower())
        self.assertIn("focused", task.natural_language_goal.lower())

    def test_advance_plan_after_success_moves_to_next_stage(self) -> None:
        planner = PlannerService(TrainingPlannerService())
        plan = ApiLearningPlan(
            id="plan-advance",
            title="Coach-first trainer",
            summary="Keep moving forward.",
            stages=[
                PlanStage(
                    id="stage-foundation",
                    title="Foundation",
                    goal="Stabilize the shell",
                    outcomes=["Tighten the IA"],
                    status="active",
                ),
                PlanStage(
                    id="stage-practice",
                    title="Practice",
                    goal="Deepen planner and memory",
                    outcomes=["Strengthen the coach loop"],
                    status="pending",
                ),
            ],
            current_stage_id="stage-foundation",
        )
        updated = planner.advance_plan_after_success(plan, None, passed=True)
        assert updated is not None
        self.assertEqual(updated.current_stage_id, "stage-practice")
        self.assertEqual(updated.stages[0].status, "completed")
        self.assertEqual(updated.stages[1].status, "active")

    def test_advance_plan_after_success_refreshes_runtime_fields(self) -> None:
        planner = PlannerService(TrainingPlannerService())
        plan = ApiLearningPlan(
            id="plan-advance-fields",
            title="Coach-first trainer",
            summary="Keep moving forward.",
            stages=[
                PlanStage(
                    id="stage-foundation",
                    title="Foundation",
                    goal="Stabilize the shell",
                    outcomes=["Tighten the IA"],
                    status="active",
                ),
                PlanStage(
                    id="stage-practice",
                    title="Practice",
                    goal="Deepen planner and memory",
                    outcomes=["Strengthen the coach loop"],
                    status="pending",
                ),
            ],
            current_stage_id="stage-foundation",
            blocked_reason="The current shell is still unstable.",
            current_step="Fix the smallest broken shell path.",
        )
        updated = planner.advance_plan_after_success(
            plan,
            None,
            passed=True,
            verified_result="The shell path now passes.",
            summary="The shell path passed, so move to planner depth.",
            next_step="Start the first planner-depth patch.",
        )
        assert updated is not None
        self.assertEqual(updated.current_stage_id, "stage-practice")
        self.assertEqual(updated.current_step, "Start the first planner-depth patch.")
        self.assertEqual(updated.why_now, "The shell path passed, so move to planner depth.")
        self.assertEqual(updated.verify_method, ["Strengthen the coach loop"])
        self.assertEqual(updated.blocked_reason, "")

    def test_replan_after_failure_shrinks_live_step_and_preserves_return_path(self) -> None:
        planner = PlannerService(TrainingPlannerService())
        plan = ApiLearningPlan(
            id="plan-replan",
            title="Coach-first trainer",
            summary="Keep moving forward.",
            stages=[
                PlanStage(
                    id="stage-practice",
                    title="Practice",
                    goal="Deepen planner and memory",
                    outcomes=["Strengthen the coach loop"],
                    status="active",
                )
            ],
            current_stage_id="stage-practice",
            current_step="Refactor the entire planner loop.",
            next_after_current="Then review the new planner loop.",
        )
        updated = planner.replan_after_failure(
            plan,
            None,
            blocker="The refactor widened too far.",
            summary="The learner lost the thread after broadening too much.",
            repeated_failure=True,
            focus_area="planner loop",
        )
        assert updated is not None
        self.assertEqual(updated.current_stage_id, "stage-practice")
        self.assertEqual(updated.blocked_reason, "The refactor widened too far.")
        self.assertIn("Shrink the slice", updated.current_step)
        self.assertIn("planner loop", updated.current_step)
        self.assertIn("return to", updated.next_after_current.lower())
        self.assertIn("Repeated failure", updated.why_now)

    def test_advance_plan_from_learning_signal_replans_abandonment(self) -> None:
        planner = PlannerService(TrainingPlannerService())
        plan = ApiLearningPlan(
            id="plan-learning-signal",
            title="Coach-first trainer",
            summary="Keep moving forward.",
            stages=[
                PlanStage(
                    id="stage-practice",
                    title="Practice",
                    goal="Deepen planner and memory",
                    outcomes=["Strengthen the coach loop"],
                    status="active",
                )
            ],
            current_stage_id="stage-practice",
            current_step="Rebuild the whole planner loop at once.",
        )
        updated = planner.advance_plan_from_learning_signal(
            plan,
            None,
            outcome="task_abandoned",
            summary="The learner abandoned the patch after broadening too much.",
            blocked_reason="Too many branches changed at once.",
            abandoned_reason="The patch became too broad to reason about.",
            repetition_count=2,
            focus_area="planner loop",
            next_step_bias="shrink",
        )
        assert updated is not None
        self.assertEqual(updated.blocked_reason, "Too many branches changed at once.")
        self.assertIn("Shrink the slice", updated.current_step)
        self.assertIn("planner loop", updated.current_step)

    def test_refresh_plan_lifecycle_updates_core_fields(self) -> None:
        planner = PlannerService(TrainingPlannerService())
        plan = ApiLearningPlan(
            id="plan-refresh",
            title="Coach-first trainer",
            summary="Keep moving forward.",
            stages=[
                PlanStage(
                    id="stage-foundation",
                    title="Foundation",
                    goal="Stabilize the shell",
                    outcomes=["Tighten the IA"],
                    status="active",
                )
            ],
            current_stage_id="stage-foundation",
        )
        updated = planner.refresh_plan_lifecycle(
            plan,
            current_step="Implement the smallest visible slice.",
            why_now="A live patch is needed now.",
            verify_method=["Run the smallest relevant check."],
            blocked_reason="",
            next_after_current="Then review the result and widen only if needed.",
        )
        self.assertEqual(updated.current_step, "Implement the smallest visible slice.")
        self.assertEqual(updated.why_now, "A live patch is needed now.")
        self.assertEqual(updated.verify_method, ["Run the smallest relevant check."])
        self.assertEqual(updated.next_after_current, "Then review the result and widen only if needed.")

    def test_broad_working_set_preserves_plan_stage_context_for_non_review_next_task(self) -> None:
        planner = PlannerService(TrainingPlannerService())
        profile = UserProfile(
            long_term_goal="Keep plan continuity visible while widening context carefully",
            weekly_hours=5,
            teaching_style="guided",
            answer_policy="guided",
        )
        plan = ApiLearningPlan(
            id="plan-broad-context",
            title="Plan continuity",
            summary="Keep the current stage visible.",
            stages=[
                PlanStage(
                    id="stage-adaptation",
                    title="Adaptation",
                    goal="Reshape one existing lane without losing continuity",
                    outcomes=["Keep the active thread visible"],
                    status="active",
                )
            ],
            current_stage_id="stage-adaptation",
        )
        task = planner.next_task(
            profile,
            current_plan=plan,
            coach_defaults={
                "working_set_mode": "broad",
                "review_cadence": "steady",
            },
        )
        self.assertIn("Adaptation", task.title)
        self.assertIn("directly connected context", task.natural_language_goal)
        self.assertIn("plan and memory state", task.inputs[2].lower())

    def test_ahead_review_mode_surfaces_review_before_lane_change_with_plan_context(self) -> None:
        planner = PlannerService(TrainingPlannerService())
        profile = UserProfile(
            long_term_goal="Use reviews to preserve the active plan state",
            weekly_hours=4,
            teaching_style="guided",
            answer_policy="guided",
        )
        plan = ApiLearningPlan(
            id="plan-review-ahead",
            title="Review continuity",
            summary="Keep due reviews connected to the live stage.",
            stages=[
                PlanStage(
                    id="stage-review",
                    title="Review stage",
                    goal="Close the live review loop before widening",
                    outcomes=["Verify the next focused patch"],
                    status="active",
                )
            ],
            current_stage_id="stage-review",
        )
        snapshot = ApiMemorySnapshot(
            active_plan=plan,
            coach_anchor="review loop",
            due_review_count=1,
            pace_signal="steady",
            due_reviews=[
                ReviewQueueItem(
                    concept="startup wiring",
                    reason="The next visible review is already due.",
                    source="weakness",
                    severity="high",
                    surface_mode="due",
                    task_hint="Patch the startup config path before switching lanes.",
                    focus_area="startup wiring",
                    linked_context="server/app/api/routers.py",
                    interval_days=0,
                    mastery_score=0.2,
                )
            ],
        )
        task = planner.next_task(
            profile,
            memory_snapshot=snapshot,
            coach_defaults={
                "working_set_mode": "focused",
                "review_cadence": "active",
                "review_reminder_mode": "ahead",
            },
        )
        self.assertIn("Review", task.title)
        self.assertIn("Surface this review ahead of the next lane change", task.natural_language_goal)
        self.assertIn("focused working set", task.natural_language_goal)


if __name__ == "__main__":
    unittest.main()
