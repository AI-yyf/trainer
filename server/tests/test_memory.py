from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import (
    CoachDefaults,
    FirstLookSummary,
    LearningPlan,
    PlanStage,
    TeachingKnowledgeAsset,
    UserProfile,
    WorkspaceUnderstandingSnapshot,
)
from app.core.models import ResourceRecord as ApiResourceRecord
from app.db.repository import TrainerRepository
from app.memory import MemoryDocument, SemanticMemoryService, StructuredMemoryService
from app.memory.service import MemoryService


class MemoryServiceTests(unittest.TestCase):
    def test_profile_defaults_keep_adaptive_coach_preferences(self) -> None:
        profile = UserProfile()

        self.assertEqual(profile.teaching_style, "auto")
        self.assertEqual(profile.answer_policy, "auto")

    def test_learning_plan_defaults_answer_policy_to_auto(self) -> None:
        plan = LearningPlan(
            id="plan-auto-defaults",
            title="Adaptive defaults",
            stages=[],
        )

        self.assertEqual(plan.default_answer_policy, "auto")

    def test_semantic_search_prefers_matching_document(self) -> None:
        service = SemanticMemoryService(collection_name="test-memory")
        try:
            service.upsert_documents(
                [
                    MemoryDocument(id="1", text="fastapi dependency injection guide", metadata={"kind": "resource"}),
                    MemoryDocument(id="2", text="pytest fixtures and assertions", metadata={"kind": "resource"}),
                ]
            )
            hits = service.search("dependency injection", top_k=1)
            self.assertEqual(hits[0].document.id, "1")
        finally:
            service.close()

    def test_structured_snapshot_contains_recent_state(self) -> None:
        memory = StructuredMemoryService()
        memory.update_profile(goal="learn fastapi")
        memory.update_workspace(name="trainer")
        memory.update_mastery("fastapi", delta=0.2)
        memory.record_weakness("testing", "missed edge cases", severity=2)
        snapshot = memory.snapshot()
        self.assertEqual(snapshot.profile["goal"], "learn fastapi")
        self.assertEqual(snapshot.workspace["name"], "trainer")
        self.assertEqual(snapshot.mastery[0].concept, "fastapi")
        self.assertEqual(snapshot.weaknesses[0].concept, "testing")

    def test_memory_snapshot_exposes_structured_coach_fields(self) -> None:
        database_path = Path(".tmp-test/memory-structured.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)
        workspace_id = "workspace-structured-memory"

        repository.save_profile(
            workspace_id,
            UserProfile(
                long_term_goal="Build a coach-first trainer",
                weekly_hours=6,
                teaching_style="guided",
                answer_policy="guided",
            ),
        )
        repository.save_plan(
            workspace_id,
            LearningPlan(
                id="plan-structured",
                title="Coach-first trainer",
                summary="Tighten the current coaching lane.",
                stages=[
                    PlanStage(
                        id="stage-practice",
                        title="Practice",
                        goal="Deepen coach memory and review rhythm",
                        outcomes=["Keep the next move narrow"],
                        status="active",
                    )
                ],
                cadence="6 hours/week",
                current_stage_id="stage-practice",
            ),
        )

        structured = service.structured_for_workspace(workspace_id)
        structured.update_mastery("planner", delta=0.2)
        structured.update_mastery("memory", delta=0.05)
        structured.record_weakness("review-rhythm", "Loses the follow-up loop", severity=3)
        service.record_session_message(
            "session-structured",
            "user: tighten the coach lane",
            workspace_id=workspace_id,
        )
        service.record_coaching_reflection(
            workspace_id=workspace_id,
            scenario="plan",
            focus_area="review rhythm",
            summary="Keep the next patch tied to one review loop.",
            next_step="Land one visible review-oriented patch.",
            review_note="Do not widen scope before the first verification.",
        )

        snapshot = service.snapshot(workspace_id)
        self.assertEqual(snapshot.coach_anchor, "review rhythm")
        self.assertEqual(snapshot.top_weakness, "review-rhythm")
        self.assertGreaterEqual(snapshot.due_review_count, 1)
        self.assertTrue(snapshot.lowest_mastery_concepts)
        self.assertEqual(snapshot.pace_signal, "gentle")
        self.assertTrue(snapshot.due_reviews[0].task_hint)
        self.assertTrue(snapshot.due_reviews[0].surface_mode in {"due", "ahead", "digest"})
        self.assertIsNotNone(snapshot.due_reviews[0].interval_days)

    def test_dependency_training_views_follow_response_language(self) -> None:
        database_path = Path(".tmp-test/memory-dependency-language.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)
        workspace_id = "workspace-dependency-language"

        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id="session-dependency-language",
            scenario="coach",
            focus_area="dependency mastery",
            summary="先把依赖边界说清楚。",
            next_step="用一个最小场景证明它成立。",
            response_language="zh-CN",
            answer_mode="guided",
        )
        structured = service.structured_for_workspace(workspace_id)
        structured.upsert_dependency_mastery(
            "fastapi-depends",
            dependency_name="fastapi Depends",
            apis=["Depends"],
            use_cases=["inject shared dependencies"],
            scenarios=["route dependency injection"],
            weakest_points=["parameter semantics"],
            evidence=["route slice"],
            mastery_stage="understood",
        )

        snapshot = service.snapshot(workspace_id)
        self.assertIsNotNone(snapshot.flash_deck)
        self.assertIsNotNone(snapshot.theory_drill)
        self.assertTrue(any("\u4e00" <= ch <= "\u9fff" for ch in snapshot.flash_deck.title))
        self.assertTrue(any("\u4e00" <= ch <= "\u9fff" for ch in snapshot.theory_drill.title))
        self.assertTrue(any("\u4e00" <= ch <= "\u9fff" for ch in snapshot.dependency_skill_maps[0].priority_summary))
        self.assertTrue(any("\u4e00" <= ch <= "\u9fff" for ch in snapshot.theory_drill.questions[0].answer))
        self.assertTrue(any("\u4e00" <= ch <= "\u9fff" for ch in snapshot.theory_drill.questions[0].prompt))

        localized_strings = [
            snapshot.flash_deck.title,
            snapshot.flash_deck.focus_area,
            snapshot.theory_drill.title,
            snapshot.theory_drill.summary,
            snapshot.theory_drill.success_signal,
            snapshot.theory_drill.return_with,
        ]
        for card in snapshot.flash_deck.cards:
            localized_strings.extend(
                [
                    card.title,
                    card.question,
                    card.expected_answer,
                    *card.hint_ladder,
                    *card.common_mistakes,
                    card.feedback.get("correct", ""),
                    card.feedback.get("incorrect", ""),
                ]
            )
        for question in snapshot.theory_drill.questions:
            localized_strings.extend([question.prompt, question.answer, question.explanation])

        for value in localized_strings:
            self.assertNotIn("???", value)
            self.assertNotIn("????", value)

    def test_workspace_understanding_with_only_first_look_is_preserved(self) -> None:
        database_path = Path(".tmp-test/memory-first-look.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)
        workspace_id = "workspace-first-look"

        service.save_workspace_understanding(
            workspace_id,
            WorkspaceUnderstandingSnapshot(
                first_look_summary=FirstLookSummary(
                    folder_role="empty_new_project",
                    project_type_guess="unknown",
                    confidence=0.9,
                    recommended_next_step="Scaffold the first thin slice.",
                ),
            ),
        )

        snapshot = service.snapshot(workspace_id)
        self.assertIsNotNone(snapshot.workspace_understanding)
        self.assertIsNotNone(snapshot.workspace_understanding.first_look_summary)
        self.assertEqual(snapshot.workspace_understanding.first_look_summary.folder_role, "empty_new_project")
        self.assertEqual(
            snapshot.workspace_understanding.first_look_summary.recommended_next_step,
            "Scaffold the first thin slice.",
        )

    def test_new_workspace_snapshot_hides_synthetic_bootstrap_review_noise(self) -> None:
        database_path = Path(".tmp-test/memory-bootstrap-clean.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)

        snapshot = service.snapshot("workspace-bootstrap-clean")

        self.assertEqual(snapshot.due_review_count, 0)
        self.assertEqual(snapshot.due_reviews, [])
        self.assertEqual(snapshot.weaknesses, [])
        self.assertEqual(snapshot.top_weakness, "")
        self.assertNotIn("new-workspace", snapshot.review_rhythm.lower())
        self.assertTrue(
            all("new-workspace" not in item.lower() for item in snapshot.teaching_observations)
        )

    def test_first_turn_implementation_snapshot_hides_immediate_live_thread_due_reviews(self) -> None:
        database_path = Path(".tmp-test/memory-first-turn-live-thread.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)
        workspace_id = "workspace-first-turn-live-thread"
        session_id = "session-first-turn-live-thread"

        service.record_session_message(session_id, "user: help me with demo.py", workspace_id=workspace_id)
        service.record_session_message(session_id, "assistant: let's take one tiny step", workspace_id=workspace_id)
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id=session_id,
            scenario="idea_implementation",
            focus_area="demo.py",
            summary="Current focus: turn the idea into one thin, verifiable patch before widening scope.",
            next_step=(
                "Change one tiny spot in demo.py, run one quick check, and use the result "
                "to decide the next move."
            ),
            response_language="en-US",
            answer_mode="guided",
        )
        service.record_coaching_reflection(
            workspace_id=workspace_id,
            scenario="idea_implementation",
            focus_area="demo.py",
            summary="Current focus: turn the idea into one thin, verifiable patch before widening scope.",
            next_step=(
                "Change one tiny spot in demo.py, run one quick check, and use the result "
                "to decide the next move."
            ),
        )

        snapshot = service.snapshot(workspace_id)

        self.assertEqual(snapshot.due_review_count, 0)
        self.assertEqual(snapshot.due_reviews, [])

    def test_structured_memory_is_isolated_per_workspace(self) -> None:
        database_path = Path(".tmp-test/memory-isolated.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)

        service.record_profile(
            "workspace-a",
            UserProfile(long_term_goal="Learn FastAPI", weekly_hours=4, teaching_style="guided", answer_policy="guided"),
        )
        service.record_profile(
            "workspace-b",
            UserProfile(long_term_goal="Learn React", weekly_hours=5, teaching_style="balanced", answer_policy="balanced"),
        )
        service.record_turn_memory(
            workspace_id="workspace-a",
            session_id="session-a",
            scenario="idea_implementation",
            focus_area="router design",
            summary="Focus on one endpoint first.",
            next_step="Implement the first handler.",
            response_language="zh-CN",
        )
        service.record_turn_memory(
            workspace_id="workspace-b",
            session_id="session-b",
            scenario="project_adaptation",
            focus_area="state management",
            summary="Keep component state local first.",
            next_step="Refactor one panel state.",
            response_language="en-US",
        )

        snapshot_a = service.snapshot("workspace-a")
        snapshot_b = service.snapshot("workspace-b")

        self.assertEqual(snapshot_a.coach_anchor, "router design")
        self.assertEqual(snapshot_b.coach_anchor, "state management")
        self.assertNotEqual(snapshot_a.current_focus, snapshot_b.current_focus)
        self.assertIn("Implement the first handler.", snapshot_a.current_focus)
        self.assertIn("Refactor one panel state.", snapshot_b.current_focus)

    def test_structured_memory_persists_across_service_rebuild(self) -> None:
        database_path = Path(".tmp-test/memory-persisted.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-persisted"

        service = MemoryService(TrainerRepository(database_path))
        service.record_profile(
            workspace_id,
            UserProfile(
                long_term_goal="Build a coach-first trainer",
                weekly_hours=6,
                teaching_style="guided",
                answer_policy="guided",
            ),
        )
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id="session-persisted",
            scenario="idea_implementation",
            focus_area="memory persistence",
            summary="Persist structured memory per workspace.",
            next_step="Load it back on the next runtime boot.",
            response_language="zh-CN",
            answer_mode="guided",
        )
        service.record_coaching_reflection(
            workspace_id=workspace_id,
            scenario="idea_implementation",
            focus_area="memory persistence",
            summary="Keep memory continuity across restarts.",
            next_step="Verify the restored focus on boot.",
            review_note="Do not fall back to a process-global memory store.",
        )

        rebuilt = MemoryService(TrainerRepository(database_path))
        snapshot = rebuilt.snapshot(workspace_id)

        self.assertEqual(snapshot.coach_anchor, "memory persistence")
        self.assertIn("memory persistence", snapshot.current_focus)
        self.assertIn("Load it back on the next runtime boot.", snapshot.current_focus)
        self.assertEqual(snapshot.workspace.get("workspace_id"), workspace_id)
        self.assertGreaterEqual(snapshot.due_review_count, 1)
        self.assertTrue(
            any(
                "remembered preference" in item.lower() or "response_language" in item
                for item in snapshot.teaching_observations
            )
        )

    def test_active_thread_is_persisted_and_restored(self) -> None:
        database_path = Path(".tmp-test/memory-active-thread.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-active-thread"

        service = MemoryService(TrainerRepository(database_path))
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id="session-active-thread",
            scenario="idea_implementation",
            focus_area="session restore",
            summary="Keep the current lane attached to one persisted session snapshot.",
            next_step="Restore the session from sqlite before starting a new one.",
            response_language="zh-CN",
            review_note="Do not create a fresh session when a persisted one already exists.",
            decision="Keep the live thread narrow until the restore path is verified.",
            teaching_note="Name the blocker before widening scope.",
            confidence="high",
            evidence=["The restore path is already persisted in sqlite."],
        )

        rebuilt = MemoryService(TrainerRepository(database_path))
        snapshot = rebuilt.snapshot(workspace_id)

        self.assertIn("session restore", snapshot.current_focus.lower())
        self.assertTrue(any("session restore" in item.lower() for item in snapshot.teaching_observations))
        self.assertTrue(any("Name the blocker before widening scope." in item for item in snapshot.teaching_observations))
        self.assertEqual(snapshot.active_thread.decision, "Keep the live thread narrow until the restore path is verified.")
        self.assertEqual(snapshot.active_thread.teaching_note, "Name the blocker before widening scope.")
        self.assertEqual(snapshot.active_thread.confidence, "high")
        self.assertEqual(snapshot.active_thread.evidence, ["The restore path is already persisted in sqlite."])
        self.assertTrue(any("Latest finalized decision:" in item for item in snapshot.memory_evidence))

    def test_onboarding_intake_persists_project_and_learning_preferences(self) -> None:
        database_path = Path(".tmp-test/memory-intake-fields.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-intake-fields"

        service = MemoryService(TrainerRepository(database_path))
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id="session-intake-fields",
            scenario="onboarding",
            focus_area="Trainer 插件改造",
            summary="先了解目标、项目语境和偏好的带法。",
            next_step="围绕当前插件先定这轮最小改造切片。",
            user_message=(
                "你可以叫我阿泽。我想用 React + FastAPI 把现在这个 Trainer 插件继续打磨，"
                "我最想推进的是让它更像长期代码教练，先讲原理再带我实现，按计划稳一点推进。"
            ),
            response_language="zh-CN",
        )

        snapshot = service.snapshot(workspace_id)
        workspace = snapshot.workspace
        profile = snapshot.profile

        self.assertEqual(workspace.get("learner_name"), "阿泽")
        self.assertEqual(workspace.get("preferred_learning_mode"), "concept-first")
        self.assertEqual(workspace.get("preferred_rhythm"), "steady")
        self.assertIn("Trainer 插件继续打磨", str(workspace.get("preferred_stack") or ""))
        self.assertIn("长期代码教练", str(workspace.get("onboarding_request") or ""))
        self.assertEqual(profile.target_project, "Trainer 插件改造")

    def test_learning_outcome_repeated_failure_increases_weakness_pressure(self) -> None:
        database_path = Path(".tmp-test/memory-learning-outcome-failure.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-learning-outcome-failure"
        service = MemoryService(TrainerRepository(database_path))

        service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["review loop"],
            outcome="repeated_error",
            summary="Missed the same verification step twice.",
            checks=["pytest"],
            missing_requirements=["Add the failing verification path."],
            action_type="evaluate_snippet",
            focus_area="review loop",
            scenario="review_reflection",
            blocked_reason="Still failing the same test.",
        )
        service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["review loop"],
            outcome="repeated_error",
            summary="Missed the same verification step twice.",
            checks=["pytest"],
            missing_requirements=["Add the failing verification path."],
            action_type="evaluate_snippet",
            repetition_count=2,
            focus_area="review loop",
            scenario="review_reflection",
            blocked_reason="Still failing the same test.",
        )

        structured = service.structured_for_workspace(workspace_id).snapshot()
        assert structured.learning_outcomes
        latest = structured.learning_outcomes[0]
        assert latest.outcome == "repeated_error"
        assert latest.repetition_count >= 2

        snapshot = service.snapshot(workspace_id)
        assert snapshot.top_weakness in {"review loop", "add"}
        assert snapshot.due_reviews
        assert snapshot.due_reviews[0].severity in {"high", "medium"}
        assert any("稳定错误模式" in item or "Recurring blocker pattern" in item for item in snapshot.teaching_observations)

    def test_blocked_learning_outcome_without_reason_persists_canonical_blocker(self) -> None:
        database_path = Path(".tmp-test/memory-learning-outcome-blocked-default.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-learning-outcome-blocked-default"
        service = MemoryService(TrainerRepository(database_path))

        service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["verification boundary"],
            outcome="blocked",
        )

        snapshot = service.snapshot(workspace_id)
        assert snapshot.workspace["latest_learning_outcome"] == "blocked"
        assert snapshot.workspace["latest_learning_blocker"] == "The current slice is blocked."

    def test_learning_outcome_success_updates_mastery_and_teaching_assets(self) -> None:
        database_path = Path(".tmp-test/memory-learning-outcome-success.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-learning-outcome-success"
        service = MemoryService(TrainerRepository(database_path))

        service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["startup wiring"],
            outcome="tests_passed",
            summary="The focused startup test now passes.",
            checks=[],
            missing_requirements=[],
            action_type="evaluate_current_file",
            focus_area="startup wiring",
            scenario="review_reflection",
            verified_result="The focused startup test now passes.",
            verified_by_evaluator=True,
        )

        structured = service.structured_for_workspace(workspace_id).snapshot()
        mastery = next((item for item in structured.mastery if item.concept == "startup wiring"), None)
        assert mastery is not None
        assert mastery.score > 0

        snapshot = service.snapshot(workspace_id)
        assert snapshot.recent_wins
        assert snapshot.teaching_assets
        assert any("verified" in item.lower() or "验证" in item for item in snapshot.memory_evidence)
        assert any(asset.kind == "implementation_pattern" for asset in snapshot.teaching_assets)

    def test_learning_outcome_records_teaching_strategy_effectiveness(self) -> None:
        database_path = Path(".tmp-test/memory-strategy-effectiveness.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-strategy-effectiveness"
        service = MemoryService(TrainerRepository(database_path))

        service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["review recovery"],
            outcome="tests_passed",
            summary="The narrow recovery loop verified cleanly.",
            action_type="evaluate_current_file",
            focus_area="review recovery",
            scenario="review_reflection",
            verified_result="The narrow recovery loop verified cleanly.",
            teaching_strategy_context={
                "challenge_level": "steady",
                "hint_depth": "guided",
                "review_urgency": "low",
                "explanation_mode": "transfer",
                "next_step_bias": "widen",
            },
        )

        structured = service.structured_for_workspace(workspace_id).snapshot()
        assert structured.teaching_strategy_effectiveness
        latest = structured.teaching_strategy_effectiveness[0]
        assert latest.scenario == "review_reflection"
        assert latest.focus_area == "review recovery"
        assert latest.success_count == 1
        assert latest.failure_count == 0
        assert latest.total_count == 1
        assert latest.explanation_mode == "transfer"
        assert latest.next_step_bias == "widen"

    def test_select_teaching_assets_prefers_focus_and_scenario_match_and_tracks_usage(self) -> None:
        database_path = Path(".tmp-test/memory-select-assets.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-select-assets"
        service = MemoryService(TrainerRepository(database_path))

        relevant = service.record_teaching_asset(
            workspace_id,
            TeachingKnowledgeAsset(
                kind="implementation_pattern",
                scope="project",
                workspace_id=workspace_id,
                title="Review scheduler pattern",
                summary="Keep the review scheduler inside one verified branch.",
                implementation_pattern="Keep the review scheduler inside one verified branch.",
                focus_area="review scheduler",
                scenario="idea_implementation",
                source_key="pattern::review-scheduler",
                trust_score=0.82,
            ),
        )
        service.record_teaching_asset(
            workspace_id,
            TeachingKnowledgeAsset(
                kind="concept_card",
                scope="project",
                workspace_id=workspace_id,
                title="Deployment note",
                summary="General deployment reminder.",
                concept_card="General deployment reminder.",
                focus_area="deployment",
                scenario="planning",
                source_key="concept::deployment",
                trust_score=0.61,
            ),
        )

        selected = service.select_teaching_assets(
            workspace_id,
            scenario="idea_implementation",
            focus_area="review scheduler",
            query="next thin slice for the review scheduler",
            limit=1,
        )
        self.assertEqual(selected[0].id, relevant.id)

        service.mark_teaching_assets_used(workspace_id, [relevant.id])
        rebuilt = MemoryService(TrainerRepository(database_path))
        rebuilt_asset = next(
            asset for asset in rebuilt.list_teaching_assets(workspace_id, limit=6) if asset.id == relevant.id
        )
        self.assertEqual(rebuilt_asset.usage_count, 1)
        self.assertIsNotNone(rebuilt_asset.last_used_at)

    def test_recalled_coaching_memories_prefers_relevant_effective_assets_and_excludes_selected(self) -> None:
        database_path = Path(".tmp-test/memory-recalled-assets.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-recalled-assets"
        service = MemoryService(TrainerRepository(database_path))

        selected = service.record_teaching_asset(
            workspace_id,
            TeachingKnowledgeAsset(
                id="asset-selected",
                kind="implementation_pattern",
                scope="project",
                workspace_id=workspace_id,
                title="Primary startup branch fix",
                summary="Patch the first startup branch before widening.",
                implementation_pattern="Patch the first startup branch before widening.",
                focus_area="startup wiring",
                scenario="review_reflection",
                source_key="pattern::startup-selected",
                trust_score=0.9,
            ),
        )
        recalled = service.record_teaching_asset(
            workspace_id,
            TeachingKnowledgeAsset(
                id="asset-recalled",
                kind="implementation_pattern",
                scope="project",
                workspace_id=workspace_id,
                title="Verified startup recovery lane",
                summary="Keep the recovery inside one verified branch.",
                implementation_pattern="Keep the recovery inside one verified branch.",
                focus_area="startup wiring",
                scenario="review_reflection",
                source_key="pattern::startup-recalled",
                retrieval_hints=["startup wiring", "recovery loop", "verified branch"],
                evidence_snippets=["The focused startup branch passed after the branch stayed narrow."],
                trust_score=0.82,
                usage_count=3,
                success_count=2,
            ),
        )
        service.record_teaching_asset(
            workspace_id,
            TeachingKnowledgeAsset(
                id="asset-irrelevant",
                kind="concept_card",
                scope="project",
                workspace_id=workspace_id,
                title="Deployment reminder",
                summary="General deployment reminder.",
                concept_card="General deployment reminder.",
                focus_area="deployment",
                scenario="planning",
                source_key="concept::deployment-irrelevant",
                trust_score=0.7,
            ),
        )

        recalled_memories = service.recalled_coaching_memories(
            workspace_id,
            scenario="review_reflection",
            focus_area="startup wiring",
            query="recover the startup branch with one verified loop",
            exclude_asset_ids=[selected.id],
            limit=2,
        )

        self.assertEqual(recalled_memories[0]["id"], recalled.id)
        self.assertIn("verified branch", recalled_memories[0]["lesson"])
        self.assertIn("worked_before", recalled_memories[0]["match_reasons"])
        self.assertIn("focus_match", recalled_memories[0]["match_reasons"])
        self.assertNotIn(selected.id, [item["id"] for item in recalled_memories])

    def test_learning_outcome_updates_teaching_asset_effectiveness_and_future_ranking(self) -> None:
        database_path = Path(".tmp-test/memory-asset-effectiveness.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-asset-effectiveness"
        service = MemoryService(TrainerRepository(database_path))

        stronger_focus = "startup wiring"
        successful = service.record_teaching_asset(
            workspace_id,
            TeachingKnowledgeAsset(
                id="asset-success",
                kind="implementation_pattern",
                scope="project",
                workspace_id=workspace_id,
                title="Startup wiring verified pattern",
                summary="Keep startup fixes inside one verified branch.",
                implementation_pattern="Keep startup fixes inside one verified branch.",
                focus_area=stronger_focus,
                scenario="review_reflection",
                source_key="pattern::startup-success",
                trust_score=0.62,
            ),
        )
        failing = service.record_teaching_asset(
            workspace_id,
            TeachingKnowledgeAsset(
                id="asset-failure",
                kind="implementation_pattern",
                scope="project",
                workspace_id=workspace_id,
                title="Startup wiring broad patch",
                summary="Widen the startup patch early.",
                implementation_pattern="Widen the startup patch early.",
                focus_area=stronger_focus,
                scenario="review_reflection",
                source_key="pattern::startup-failure",
                trust_score=0.7,
            ),
        )

        service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=[stronger_focus],
            outcome="tests_passed",
            summary="The focused startup branch now passes.",
            action_type="evaluate_current_file",
            focus_area=stronger_focus,
            scenario="review_reflection",
            verified_result="The focused startup branch now passes.",
            selected_teaching_asset_ids=[successful.id],
        )
        service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=[stronger_focus],
            outcome="repeated_error",
            summary="The broad startup patch failed again.",
            checks=["pytest"],
            missing_requirements=["Keep the branch narrow."],
            action_type="evaluate_current_file",
            repetition_count=2,
            focus_area=stronger_focus,
            scenario="review_reflection",
            blocked_reason="The same broad branch still fails.",
            selected_teaching_asset_ids=[failing.id],
        )

        rebuilt = MemoryService(TrainerRepository(database_path))
        assets = {asset.id: asset for asset in rebuilt.list_teaching_assets(workspace_id, limit=8)}
        success_asset = assets[successful.id]
        failure_asset = assets[failing.id]

        self.assertEqual(success_asset.success_count, 1)
        self.assertEqual(success_asset.failure_count, 0)
        self.assertEqual(success_asset.last_outcome, "tests_passed")
        self.assertIn("review_reflection", success_asset.effectiveness_by_scenario)
        self.assertGreater(success_asset.trust_score, 0.62)

        self.assertEqual(failure_asset.success_count, 0)
        self.assertEqual(failure_asset.failure_count, 1)
        self.assertEqual(failure_asset.last_outcome, "repeated_error")
        self.assertLess(failure_asset.trust_score, 0.7)

        selected = rebuilt.select_teaching_assets(
            workspace_id,
            scenario="review_reflection",
            focus_area=stronger_focus,
            query="startup wiring next recovery step",
            limit=4,
        )
        selected_ids = [item.id for item in selected]
        self.assertIn(successful.id, selected_ids)
        success_rank = rebuilt._teaching_asset_rank(  # type: ignore[attr-defined]
            success_asset,
            workspace_id=workspace_id,
            scenario="review_reflection",
            normalized_focus=stronger_focus,
            normalized_query="startup wiring next recovery step",
            focus_tokens=rebuilt._teaching_asset_tokens("startup wiring next recovery step"),  # type: ignore[attr-defined]
        )
        failure_rank = rebuilt._teaching_asset_rank(  # type: ignore[attr-defined]
            failure_asset,
            workspace_id=workspace_id,
            scenario="review_reflection",
            normalized_focus=stronger_focus,
            normalized_query="startup wiring next recovery step",
            focus_tokens=rebuilt._teaching_asset_tokens("startup wiring next recovery step"),  # type: ignore[attr-defined]
        )
        self.assertGreater(success_rank, failure_rank)

    def test_teaching_knowledge_catalog_groups_assets_by_scope_kind_and_origin(self) -> None:
        database_path = Path(".tmp-test/memory-knowledge-catalog.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-knowledge-catalog"
        service = MemoryService(TrainerRepository(database_path))

        service.record_teaching_asset(
            workspace_id,
            TeachingKnowledgeAsset(
                kind="implementation_pattern",
                scope="project",
                workspace_id=workspace_id,
                title="Review scheduler pattern",
                summary="Keep the review scheduler inside one verified branch.",
                implementation_pattern="Keep the review scheduler inside one verified branch.",
                origin="learning_outcome",
                focus_area="review scheduler",
                scenario="idea_implementation",
                source_key="pattern::review-scheduler",
                trust_score=0.82,
            ),
        )
        service.record_teaching_asset(
            workspace_id,
            TeachingKnowledgeAsset(
                kind="concept_card",
                scope="personal",
                workspace_id=workspace_id,
                title="Explain before widening",
                summary="Name the rule before writing the second branch.",
                concept_card="Name the rule before writing the second branch.",
                origin="reflection",
                focus_area="teaching style",
                scenario="principle_explanation",
                source_key="concept::teaching-style",
                trust_score=0.67,
            ),
        )

        catalog = service.teaching_knowledge_catalog(workspace_id)
        self.assertEqual(catalog["total"], 2)
        self.assertIn("project", catalog["by_scope"])
        self.assertIn("personal", catalog["by_scope"])
        self.assertIn("implementation_pattern", catalog["by_kind"])
        self.assertIn("learning_outcome", catalog["by_origin"])
        self.assertEqual(catalog["top_assets"][0]["kind"], "implementation_pattern")

    def test_memory_evidence_prioritizes_verified_result_blocker_and_next_step(self) -> None:
        database_path = Path(".tmp-test/memory-evidence-priority.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-evidence-priority"

        service = MemoryService(TrainerRepository(database_path))
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id="session-evidence-priority",
            scenario="review",
            focus_area="startup wiring",
            summary="Verified the startup path until config load.",
            next_step="Patch the config branch and rerun the focused check.",
            response_language="en-US",
            review_note="The config branch still fails before app boot completes.",
        )

        evidence = service.memory_evidence(workspace_id, limit=4)
        snapshot = service.snapshot(workspace_id)
        self.assertIsNotNone(snapshot.active_thread)
        self.assertTrue(evidence[0].startswith("Last verified result:"))
        self.assertTrue(evidence[1].startswith("Current blocker:"))
        self.assertTrue(evidence[2].startswith("Continue startup wiring with this next move:"))
        self.assertTrue(any("Current blocker:" in item for item in evidence))
        self.assertTrue(any("Continue startup wiring with this next move:" in item for item in evidence))
        self.assertEqual(snapshot.active_thread.focus_area, "startup wiring")
        self.assertEqual(snapshot.memory_evidence[:4], evidence)

    def test_onboarding_message_is_written_into_long_term_memory_and_profile(self) -> None:
        database_path = Path(".tmp-test/memory-onboarding-signals.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-onboarding-signals"

        service = MemoryService(TrainerRepository(database_path))
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id="session-onboarding-signals",
            user_message=(
                "我的长期目标是成为更强的后端工程师。我现在是中级 Python 开发，"
                "每周能投入 8 小时，希望你一步一步引导我。"
                "我现在卡在 Trainer 的 session restore 这条链路。"
            ),
            scenario="idea_implementation",
            focus_area="session restore",
            summary="先把 session restore 主线压到一个可验证步骤。",
            next_step="先验证 restore branch 是否拿到了正确 session id。",
            response_language="zh-CN",
            answer_mode="guided",
        )

        profile = service.profile(workspace_id)
        assert profile is not None
        self.assertEqual(profile.long_term_goal, "成为更强的后端工程师")
        self.assertIn("成为更强的后端工程师", profile.long_term_goals)
        self.assertEqual(profile.background, "中级 Python 开发")
        self.assertEqual(profile.weekly_hours, 8)
        self.assertEqual(profile.teaching_style, "auto")

        snapshot = service.snapshot(workspace_id)
        joined_observations = " ".join(snapshot.teaching_observations)
        joined_evidence = " ".join(snapshot.memory_evidence)
        self.assertIn("长期目标", joined_evidence)
        self.assertTrue("session restore" in joined_observations.lower() or "session restore" in joined_evidence.lower())
        self.assertTrue(
            any(
                item.key in {"long_term_goal", "learner_background", "preferred_rhythm", "current_blocker"}
                for item in service.structured_for_workspace(workspace_id).snapshot().preferences
            )
        )

    def test_active_thread_continues_same_mainline_across_three_turns(self) -> None:
        database_path = Path(".tmp-test/memory-mainline-three-turns.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-mainline-three-turns"
        session_id = "session-mainline-three-turns"

        service = MemoryService(TrainerRepository(database_path))
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id=session_id,
            scenario="idea_implementation",
            focus_area="session continuity",
            summary="Verified the first persistence write path.",
            next_step="Reconnect the restored session before opening a new one.",
            response_language="en-US",
            review_note="Session restore still diverges after the first bootstrap.",
            teaching_goal="Keep the learner on one visible thread.",
        )
        service.record_coaching_reflection(
            workspace_id=workspace_id,
            scenario="idea_implementation",
            focus_area="session continuity",
            summary="Keep the thread attached to one restore path.",
            next_step="Patch the resume branch before widening.",
            review_note="Do not fall back to creating a new session.",
        )
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id=session_id,
            scenario="idea_implementation",
            focus_area="session continuity",
            summary="Verified the resume branch after patching.",
            next_step="Wire the latest restored session id into runtime recovery.",
            response_language="en-US",
            review_note="The runtime still forgets which session to resume after restart.",
            teaching_goal="Preserve one stable recovery thread.",
        )

        snapshot = service.snapshot(workspace_id)

        self.assertEqual(snapshot.active_thread.focus_area, "session continuity")
        self.assertEqual(snapshot.coach_anchor, "session continuity")
        self.assertIn("Wire the latest restored session id into runtime recovery.", snapshot.current_focus)
        self.assertIn("runtime still forgets which session to resume", snapshot.current_focus.lower())
        self.assertTrue(
            any(
                "session continuity" in item.lower() or "stable recovery thread" in item.lower()
                for item in snapshot.teaching_observations
            )
        )
        self.assertIn("session continuity", str(snapshot.workspace.get("latest_turn_continuity_note", "")).lower())

    def test_followup_turn_keeps_verified_result_on_same_mainline(self) -> None:
        database_path = Path(".tmp-test/memory-preserve-verified-result.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-preserve-verified-result"
        session_id = "session-preserve-verified-result"

        service = MemoryService(TrainerRepository(database_path))
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id=session_id,
            scenario="idea_implementation",
            focus_area="session continuity",
            summary="Verified the first persistence write path.",
            next_step="Reconnect the restored session before opening a new one.",
            response_language="en-US",
            review_note="Session restore still diverges after the first bootstrap.",
            teaching_goal="Keep the learner on one visible thread.",
        )
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id=session_id,
            scenario="idea_implementation",
            focus_area="session continuity",
            summary="Keep the resume branch narrow and continue the same thread.",
            next_step="Wire the restored session id into runtime recovery.",
            response_language="en-US",
            review_note="The runtime still forgets which session to resume after restart.",
            teaching_goal="Preserve one stable recovery thread.",
        )

        snapshot = service.snapshot(workspace_id)

        self.assertIsNotNone(snapshot.active_thread)
        self.assertEqual(
            snapshot.active_thread.verified_result,
            "Verified the first persistence write path.",
        )
        self.assertIn(
            "Verified the first persistence write path.",
            " ".join(snapshot.memory_evidence),
        )

    def test_personal_memory_recalls_authorized_preferences_after_restart(self) -> None:
        database_path = Path(".tmp-test/memory-personal-long-term.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)

        service.record_profile(
            "workspace-source",
            UserProfile(
                long_term_goal="Become excellent at codebase recovery and adaptation",
                weekly_hours=7,
                teaching_style="guided",
                answer_policy="guided",
            ),
        )
        service.record_turn_memory(
            workspace_id="workspace-source",
            session_id="session-source",
            scenario="project_adaptation",
            focus_area="runtime recovery",
            summary="Keep the recovery branch narrow.",
            next_step="Restore the latest saved runtime session first.",
            response_language="en-US",
            answer_mode="guided",
        )
        service.record_coaching_reflection(
            workspace_id="workspace-source",
            scenario="project_adaptation",
            focus_area="runtime recovery",
            summary="The learner repeatedly widens scope too early.",
            next_step="Stay on one recovery branch until verified.",
            review_note="Expands into unrelated recovery paths before verifying the first branch.",
        )
        service.save_memory_share_grant(
            source_workspace_id="workspace-source",
            target_workspace_id="workspace-live",
            categories=["preferences"],
        )
        service.record_coaching_reflection(
            workspace_id="workspace-source",
            scenario="project_adaptation",
            focus_area="runtime recovery",
            summary="The learner still widens recovery scope too early.",
            next_step="Keep the resume path isolated and verified first.",
            review_note="Expands into unrelated recovery paths before verifying the first branch.",
        )

        service.record_turn_memory(
            workspace_id="workspace-live",
            session_id="session-live",
            scenario="idea_implementation",
            focus_area="message layout",
            summary="消息流需要更凝练。",
            next_step="先只保留一条主线和一个展开入口。",
            response_language="zh-CN",
            coach_defaults=CoachDefaults(memory_scope="personal"),
        )

        rebuilt = MemoryService(TrainerRepository(database_path))
        snapshot = rebuilt.snapshot("workspace-live")

        joined_observations = " ".join(snapshot.teaching_observations)
        self.assertTrue("长期目标" in joined_observations or "long-term goal" in joined_observations.lower())
        self.assertTrue("guided" in joined_observations.lower() or "偏好" in joined_observations)
        self.assertNotIn("recurring blocker pattern", joined_observations.lower())

    def test_personal_memory_stays_isolated_without_grant(self) -> None:
        database_path = Path(".tmp-test/memory-cross-workspace-priority.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)

        service.record_turn_memory(
            workspace_id="workspace-a",
            session_id="session-a",
            scenario="idea_implementation",
            focus_area="api boundaries",
            summary="Keep request contracts narrow.",
            next_step="Define one request object before widening.",
            response_language="en-US",
        )

        service.record_turn_memory(
            workspace_id="workspace-b",
            session_id="session-b",
            scenario="project_adaptation",
            focus_area="message density",
            summary="消息流要更轻。",
            next_step="先去掉最抢注意力的辅助块。",
            response_language="zh-CN",
            coach_defaults=CoachDefaults(memory_scope="personal"),
        )

        snapshot = service.snapshot("workspace-b")

        self.assertEqual(snapshot.active_thread.focus_area, "message density")
        self.assertIn("message density", snapshot.current_focus.lower())
        self.assertNotIn("api boundaries", snapshot.current_focus.lower())
        self.assertFalse(any("api boundaries" in item.lower() for item in snapshot.teaching_observations))

    def test_coach_defaults_shape_memory_scope_and_toggles(self) -> None:
        database_path = Path(".tmp-test/memory-coach-defaults.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)
        workspace_id = "workspace-coach-defaults"

        repository.save_resource(
            workspace_id,
            ApiResourceRecord(
                id="resource-defaults",
                kind="markdown",
                name="Defaults Note",
                source="defaults.md",
                tags=["defaults"],
                summary="Should be hidden when resource toggles are off.",
                parse_status="parsed",
                index_status="indexed",
            ),
        )
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id="session-defaults",
            scenario="idea_implementation",
            focus_area="workspace defaults",
            summary="Keep the thread short.",
            next_step="Do the smallest verified step.",
            response_language="en-US",
            coach_defaults=CoachDefaults(
                memory_scope="session",
                working_set_mode="focused",
                review_cadence="active",
                review_reminder_mode="ahead",
                workspace_memory_toggles={"decisions": False, "patterns": False, "resources": False},
            ),
        )

        snapshot = service.snapshot(workspace_id)
        self.assertIn("memory scope is session", snapshot.current_focus.lower())
        self.assertEqual(snapshot.resources, [])
        self.assertTrue(all("progress" not in item.lower() for item in snapshot.recent_wins))
        self.assertTrue(all("remembered preference" not in item.lower() for item in snapshot.teaching_observations))

    def test_personal_memory_aggregates_across_workspaces(self) -> None:
        database_path = Path(".tmp-test/memory-personal-aggregate.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)

        service.record_profile(
            "workspace-a",
            UserProfile(
                long_term_goal="Build product-grade tools",
                weekly_hours=6,
                teaching_style="guided",
                answer_policy="guided",
            ),
        )
        service.record_profile(
            "workspace-b",
            UserProfile(
                long_term_goal="Ship stronger React systems",
                weekly_hours=5,
                teaching_style="balanced",
                answer_policy="balanced",
            ),
        )

        service.record_turn_memory(
            workspace_id="workspace-a",
            session_id="session-a",
            scenario="idea_implementation",
            focus_area="state machines",
            summary="Keep the component transitions explicit.",
            next_step="Implement the reducer transition table first.",
            response_language="en-US",
        )
        service.record_coaching_reflection(
            workspace_id="workspace-a",
            scenario="idea_implementation",
            focus_area="state machines",
            summary="The learner benefits from explicit state boundaries.",
            next_step="Verify one reducer path before widening.",
            review_note="Do not hide transitions inside ad hoc booleans.",
        )
        source_structured = service.structured_for_workspace("workspace-a")
        source_structured.update_mastery("state machines", delta=0.25)
        service._persist_structured("workspace-a")

        service.record_turn_memory(
            workspace_id="workspace-b",
            session_id="session-b",
            scenario="project_adaptation",
            focus_area="streaming ui",
            summary="先把消息流折叠逻辑做简单。",
            next_step="先只保留正文和一个展开入口。",
            response_language="zh-CN",
            coach_defaults=CoachDefaults(memory_scope="personal"),
        )
        service.record_coaching_reflection(
            workspace_id="workspace-b",
            scenario="project_adaptation",
            focus_area="streaming ui",
            summary="当前工作区继续保留对窄侧栏可读性的要求。",
            next_step="把长消息流先压成一条主线。",
            review_note="不要把计划页重新做成仪表盘。",
        )
        service.save_memory_share_grant(
            source_workspace_id="workspace-a",
            target_workspace_id="workspace-b",
            categories=["preferences", "mastery"],
        )

        snapshot = service.snapshot("workspace-b")

        self.assertEqual(snapshot.active_thread.focus_area, "streaming ui")
        self.assertTrue(
            "个人长期记忆" in snapshot.current_focus or "memory scope is personal" in snapshot.current_focus.lower()
        )
        self.assertTrue(
            any("remembered preference" in item.lower() or "已记住你的偏好" in item for item in snapshot.recent_wins)
        )
        self.assertIn("streaming ui", snapshot.coach_anchor.lower())
        self.assertTrue(any(concept in {"state machines", "streaming ui"} for concept in snapshot.lowest_mastery_concepts))

    def test_memory_share_grants_filter_categories_persist_and_revoke(self) -> None:
        database_path = Path(".tmp-test/memory-share-grants.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)
        source_workspace_id = "workspace-share-source"
        target_workspace_id = "workspace-share-target"

        source = service.structured_for_workspace(source_workspace_id)
        source.remember_preference("shared_preference", "source-only preference", source="test")
        source.update_mastery("shared-mastery", delta=0.4)
        service._persist_structured(source_workspace_id)

        target = service.structured_for_workspace(target_workspace_id)
        target.update_workspace(memory_scope="personal")
        service._persist_structured(target_workspace_id)

        def aggregated(current: MemoryService):
            lane = current.structured_for_workspace(target_workspace_id).snapshot()
            return current._build_personal_lane_snapshot(target_workspace_id, lane)

        isolated = aggregated(service)
        self.assertFalse(any(item.value == "source-only preference" for item in isolated.preferences))
        self.assertFalse(any(item.concept == "shared-mastery" for item in isolated.mastery))

        service.save_memory_share_grant(
            source_workspace_id=source_workspace_id,
            target_workspace_id=target_workspace_id,
            categories=["preferences"],
        )
        preferences_only = aggregated(service)
        self.assertTrue(any(item.value == "source-only preference" for item in preferences_only.preferences))
        self.assertFalse(any(item.concept == "shared-mastery" for item in preferences_only.mastery))

        service.save_memory_share_grant(
            source_workspace_id=source_workspace_id,
            target_workspace_id=target_workspace_id,
            categories=["mastery"],
        )
        rebuilt = MemoryService(TrainerRepository(database_path))
        mastery_only = aggregated(rebuilt)
        self.assertFalse(any(item.value == "source-only preference" for item in mastery_only.preferences))
        self.assertTrue(any(item.concept == "shared-mastery" for item in mastery_only.mastery))

        self.assertTrue(
            rebuilt.revoke_memory_share_grant(
                source_workspace_id=source_workspace_id,
                target_workspace_id=target_workspace_id,
            )
        )
        revoked = aggregated(rebuilt)
        self.assertFalse(any(item.concept == "shared-mastery" for item in revoked.mastery))

    def test_project_scope_current_focus_stays_concise_when_thread_next_step_is_already_present(self) -> None:
        database_path = Path(".tmp-test/memory-project-focus-compact.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)
        workspace_id = "workspace-project-focus-compact"
        next_step = "Verify one remote workspace boundary before widening."

        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id="session-project-focus-compact",
            scenario="coach",
            focus_area="remote workspace boundaries",
            summary="Keep the coach on one live boundary question.",
            next_step=next_step,
            response_language="en-US",
        )

        snapshot = service.snapshot(workspace_id)

        self.assertIn("remote workspace boundaries", snapshot.current_focus.lower())
        self.assertEqual(snapshot.current_focus.count(next_step), 1)
        self.assertNotIn("memory scope is project", snapshot.current_focus.lower())

    def test_project_scope_current_focus_strips_prefixed_next_step_labels(self) -> None:
        database_path = Path(".tmp-test/memory-project-focus-next-step-prefix.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)
        workspace_id = "workspace-project-focus-next-step-prefix"
        bare_next_step = "验证一个远程工作区边界，再考虑扩展。"

        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id="session-project-focus-next-step-prefix",
            scenario="coach",
            focus_area="remote workspace boundaries",
            summary="Keep the coach on one live boundary question.",
            next_step=f"下一步：{bare_next_step}",
            response_language="zh-CN",
        )

        snapshot = service.snapshot(workspace_id)

        self.assertEqual(snapshot.active_thread.next_step, bare_next_step)
        self.assertEqual(snapshot.current_focus.count(bare_next_step), 1)
        self.assertNotIn("下一步是：下一步：", snapshot.current_focus)
        self.assertNotIn("下一步：下一步：", snapshot.current_focus)

    def test_personal_memory_keeps_workspace_state_isolated_after_service_rebuild(self) -> None:
        database_path = Path(".tmp-test/memory-personal-persist.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)

        service.record_turn_memory(
            workspace_id="workspace-history",
            session_id="session-history",
            scenario="idea_implementation",
            focus_area="api boundaries",
            summary="Keep the provider contract narrow.",
            next_step="Define one stable request model first.",
            response_language="en-US",
        )
        service.record_coaching_reflection(
            workspace_id="workspace-history",
            scenario="idea_implementation",
            focus_area="api boundaries",
            summary="Good API coaching starts with narrow contracts.",
            next_step="Verify one request path.",
            review_note="Do not mix transport and pedagogy concerns.",
        )

        service.record_turn_memory(
            workspace_id="workspace-live",
            session_id="session-live",
            scenario="project_adaptation",
            focus_area="message density",
            summary="消息流需要更轻。",
            next_step="先去掉最抢注意力的辅助模块。",
            response_language="zh-CN",
            coach_defaults=CoachDefaults(memory_scope="personal"),
        )

        rebuilt = MemoryService(TrainerRepository(database_path))
        snapshot = rebuilt.snapshot("workspace-live")

        self.assertEqual(snapshot.active_thread.focus_area, "message density")
        self.assertTrue(
            "个人长期记忆" in snapshot.current_focus or "memory scope is personal" in snapshot.current_focus.lower()
        )
        self.assertNotIn("api boundaries", " ".join(snapshot.teaching_observations).lower())

    def test_workspace_defaults_and_active_thread_survive_service_rebuild_together(self) -> None:
        database_path = Path(".tmp-test/memory-defaults-thread-rebuild.db")
        if database_path.exists():
            database_path.unlink()
        workspace_id = "workspace-defaults-thread-rebuild"

        service = MemoryService(TrainerRepository(database_path))
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id="session-defaults-thread-rebuild",
            scenario="idea_implementation",
            focus_area="coach-first continuity",
            summary="Keep the same coaching lane alive across restarts.",
            next_step="Resume the same tiny verified slice after restart.",
            response_language="zh-CN",
            answer_mode="guided",
            coach_defaults=CoachDefaults(
                memory_scope="project",
                working_set_mode="focused",
                review_cadence="active",
                review_reminder_mode="ahead",
            ),
        )

        rebuilt = MemoryService(TrainerRepository(database_path))
        snapshot = rebuilt.snapshot(workspace_id)

        self.assertEqual(snapshot.workspace.get("response_language"), "zh-CN")
        self.assertEqual(snapshot.workspace.get("answer_mode"), "guided")
        self.assertEqual(snapshot.workspace.get("coach_defaults", {}).get("working_set_mode"), "focused")
        self.assertEqual(snapshot.active_thread.focus_area, "coach-first continuity")
        self.assertIn("Resume the same tiny verified slice after restart.", snapshot.active_thread.next_step)

    def test_review_rhythm_continues_across_followup_turns_for_same_active_thread(self) -> None:
        database_path = Path(".tmp-test/memory-review-rhythm-continuity.db")
        if database_path.exists():
            database_path.unlink()
        repository = TrainerRepository(database_path)
        service = MemoryService(repository)
        workspace_id = "workspace-review-rhythm-continuity"
        session_id = "session-review-rhythm-continuity"

        defaults = CoachDefaults(
            memory_scope="project",
            working_set_mode="focused",
            review_cadence="active",
            review_reminder_mode="ahead",
        )
        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id=session_id,
            scenario="review",
            focus_area="startup wiring",
            summary="Verified the first startup branch and kept the review lane narrow.",
            next_step="Patch the config path and rerun the focused startup check.",
            response_language="zh-CN",
            review_note="The config branch still breaks before the app is ready.",
            coach_defaults=defaults,
        )
        first_snapshot = service.snapshot(workspace_id)

        service.record_turn_memory(
            workspace_id=workspace_id,
            session_id=session_id,
            scenario="review",
            focus_area="startup wiring",
            summary="Verified the config branch and kept the same review loop alive.",
            next_step="Reconnect the final readiness check without widening into a refactor.",
            response_language="zh-CN",
            review_note="The readiness check still needs one more focused pass.",
            coach_defaults=defaults,
        )
        second_snapshot = service.snapshot(workspace_id)

        self.assertEqual(first_snapshot.active_thread.focus_area, "startup wiring")
        self.assertEqual(second_snapshot.active_thread.focus_area, "startup wiring")
        self.assertIn("startup wiring", second_snapshot.coach_anchor.lower())
        self.assertTrue(second_snapshot.review_rhythm)
        self.assertGreaterEqual(second_snapshot.due_review_count, first_snapshot.due_review_count)
        self.assertIn("startup wiring", second_snapshot.current_focus.lower())
        self.assertIn(
            "Reconnect the final readiness check without widening into a refactor.",
            second_snapshot.current_focus,
        )


if __name__ == "__main__":
    unittest.main()
