from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import (
    AffectState,
    CoachingAdaptationProfile,
    CurrentFilePayload,
    MemorySnapshot,
    ResourceRecord,
    ReviewQueueItem,
    SourceIntakeGovernance,
    TeachingKnowledgeAsset,
    TurnRequest,
    UserProfile,
    WorkspaceUnderstandingSnapshot,
)
from app.pedagogy import PedagogyService


def _profile() -> UserProfile:
    return UserProfile(
        long_term_goal="Build a coach-first trainer",
        weekly_hours=6,
        teaching_style="guided",
        answer_policy="guided",
        preferred_libraries=["fastapi", "pytest"],
    )


def _current_file(**overrides: object) -> CurrentFilePayload:
    payload = {
        "path": "server/app/planner/service.py",
        "language_id": "python",
        "content": "def recommend_next_task():\n    pass\n",
        "diagnostics": ["Recommendation loses the current plan anchor."],
        "recent_files": ["server/app/api/routers.py", "server/app/memory/service.py"],
        "recent_edited_files": ["server/app/planner/service.py", "server/app/memory/service.py"],
        "related_files": [
            {"path": "server/tests/test_planner.py", "reason": "verification"},
            {"path": "server/app/core/models.py", "reason": "contracts"},
        ],
    }
    payload.update(overrides)
    return CurrentFilePayload(**payload)


def _memory_snapshot(**overrides: object) -> MemorySnapshot:
    payload = {
        "current_focus": "review rhythm",
        "coach_anchor": "plan progression",
        "top_weakness": "testing",
        "due_reviews": [
            ReviewQueueItem(
                concept="review loop",
                reason="Reinforce the follow-up habit.",
                due_at="2026-05-01T12:00:00Z",
                source="reflection",
                severity="high",
            )
        ],
        "due_review_count": 1,
        "pace_signal": "gentle",
        "recent_wins": ["Kept one patch narrow"],
        "teaching_observations": ["The learner moves faster when the next step stays concrete."],
        "coaching_adaptation": CoachingAdaptationProfile(
            challenge_level="steady",
            hint_depth="guided",
            review_urgency="normal",
            explanation_mode="grounded",
            next_step_bias="steady",
            summary="Keep the next step attached to the current coaching lane.",
            evidence=["The latest loop is still active."],
        ),
    }
    payload.update(overrides)
    return MemorySnapshot(**payload)


def _eligible_source_governance() -> SourceIntakeGovernance:
    return SourceIntakeGovernance(
        policy_version="source-intake-v1",
        assessed_at="2026-07-12T00:00:00+00:00",
        source_provenance_status="fetched",
        license_status="observed",
        license_expression="MIT",
        license_evidence_kind="source_spdx",
        license_evidence_source="https://example.com/coach-research",
        license_evidence_excerpt="SPDX-License-Identifier: MIT",
        maintenance_status="reported_recent",
        maintenance_updated_at="2026-07-01",
        maintenance_evidence_kind="source_last_updated",
        maintenance_evidence_source="https://example.com/coach-research",
        maintenance_evidence_excerpt="Last updated: 2026-07-01",
        commercial_reuse_policy="permissive-spdx-v1",
        commercial_reuse_status="eligible",
        commercial_reuse_reason_codes=[
            "license_permissive_spdx_observed",
            "maintenance_reported_recent",
        ],
    )


def _workspace_understanding(**overrides: object) -> WorkspaceUnderstandingSnapshot:
    payload = {
        "repo_summary": "Reply assembly currently flows through the coach router and planner boundary.",
        "entry_points": ["server/app/api/routers.py", "server/app/pedagogy/service.py"],
        "feature_lanes": ["Keep the reply assembly lane narrow and verifiable."],
        "risk_zones": ["Recent edits already span multiple coaching files."],
        "training_opportunities": ["Strengthen the first reply path before widening the workflow."],
        "resource_brief": "",
    }
    payload.update(overrides)
    return WorkspaceUnderstandingSnapshot(**payload)


class PedagogyServiceTests(unittest.TestCase):
    def test_decide_teaching_prefers_onboarding_when_relationship_is_not_built_yet(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message=(
                "我的长期目标是成为更强的后端工程师，我现在是中级 Python 开发，"
                "每周可以投入 8 小时，希望你一步一步带我。"
            ),
            current_file=None,
        )
        learner_state = service.infer_learner_state(
            request=request,
            profile=UserProfile(),
            memory_snapshot=MemorySnapshot(),
        )
        decision = service.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=UserProfile(),
            memory_snapshot=MemorySnapshot(),
        )
        self.assertEqual(decision.mode, "onboarding")
        self.assertEqual(decision.scenario, "guided")
        self.assertFalse(decision.should_generate_exercise)
        self.assertFalse(decision.should_focus_on_implementation_steps)
        self.assertTrue(decision.should_end_with_question)
        self.assertIn("relationship_first_onboarding", decision.reason)

    def test_decide_teaching_prefers_onboarding_for_low_context_relationship_opening(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="我们先对齐一下，你先一步一步带我看看怎么开始。",
            current_file=None,
        )
        learner_state = service.infer_learner_state(
            request=request,
            profile=UserProfile(),
            memory_snapshot=MemorySnapshot(),
        )
        decision = service.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=UserProfile(),
            memory_snapshot=MemorySnapshot(),
        )
        self.assertEqual(decision.mode, "onboarding")
        self.assertIn("relationship_first_onboarding", decision.reason)

    def test_decide_teaching_skips_onboarding_for_execution_ready_next_step_request(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message=(
                "Based on the current file and my goal, give me one very small next step "
                "with strong teaching value."
            ),
            current_file=_current_file(
                path="demo.py",
                content="def add(a, b):\n    return a + b\n",
                diagnostics=[],
                recent_files=[],
                recent_edited_files=[],
                related_files=[],
            ),
        )
        learner_state = service.infer_learner_state(
            request=request,
            profile=UserProfile(),
            memory_snapshot=MemorySnapshot(),
        )
        decision = service.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=UserProfile(),
            memory_snapshot=MemorySnapshot(),
        )
        self.assertEqual(decision.scenario, "idea_implementation")
        self.assertEqual(decision.mode, "idea_implementation")
        self.assertTrue(decision.should_focus_on_implementation_steps)
        self.assertNotIn("relationship_first_onboarding", decision.reason)

    def test_infer_learner_state_flags_rescue_and_review(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="I am stuck on this error, just tell me the next code fix",
            current_file=_current_file(),
        )
        learner_state = service.infer_learner_state(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(),
        )
        self.assertTrue(learner_state.needs_rescue)
        self.assertTrue(learner_state.needs_review)
        self.assertEqual(learner_state.learner_signal, "blocked")
        self.assertGreaterEqual(learner_state.frustration_level, 0.65)

    def test_decide_teaching_for_idea_implementation(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Help me implement a review scheduler for this trainer",
            current_file=_current_file(diagnostics=[]),
            focus_area="review scheduler",
        )
        learner_state = service.infer_learner_state(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
        )
        decision = service.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
        )
        self.assertEqual(decision.scenario, "idea_implementation")
        self.assertEqual(decision.mode, "idea_implementation")
        self.assertTrue(decision.should_focus_on_implementation_steps)
        self.assertIn("implementation", decision.reason)
        self.assertTrue(decision.lesson_shape)
        self.assertTrue(decision.exercise_shape)
        self.assertTrue(decision.teaching_strategy)
        self.assertTrue(decision.closing_move)
        self.assertTrue(decision.artifact_priority)

    def test_decide_teaching_embeds_due_review_when_affect_turns_fragile(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="I am stuck on the startup branch and need the next tiny recovery step.",
            current_file=_current_file(),
            focus_area="startup wiring",
        )
        memory_snapshot = _memory_snapshot(
            due_reviews=[
                ReviewQueueItem(
                    concept="startup wiring",
                    reason="Reinforce the recovery loop before widening scope.",
                    due_at="2026-05-01T12:00:00Z",
                    source="reflection",
                    severity="high",
                    focus_area="startup wiring",
                )
            ],
            due_review_count=1,
        )
        learner_state = service.infer_learner_state(
            request=request,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        decision = service.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
            affect_state=AffectState(
                frustration_level=0.74,
                confidence_level=0.31,
                momentum_level=0.22,
                needs_reassurance=True,
                urgency_level="high",
                recovery_signal="fragile",
            ),
        )
        self.assertEqual(decision.mode, "review_reflection")
        self.assertEqual(decision.focus_area, "startup wiring")
        self.assertIn("affect_recovery:fragile", decision.reason)
        self.assertIn("affect_embeds_due_review", decision.reason)

    def test_repeated_failure_bias_pushes_review_reflection_even_without_explicit_fragile_affect(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Help me continue fixing config validation.",
            current_file=_current_file(diagnostics=[]),
            focus_area="config validation",
        )
        memory_snapshot = _memory_snapshot(
            current_focus="config validation",
            due_reviews=[
                ReviewQueueItem(
                    concept="config validation",
                    reason="Recover the same failing branch before widening.",
                    due_at="2026-05-01T12:00:00Z",
                    source="reflection",
                    severity="high",
                    focus_area="config validation",
                )
            ],
            due_review_count=1,
            coaching_adaptation=CoachingAdaptationProfile(
                challenge_level="lower",
                hint_depth="direct",
                review_urgency="high",
                explanation_mode="rebuild",
                next_step_bias="shrink",
                summary="Recent failures mean the next loop must shrink.",
                evidence=["The same config validation branch failed twice."],
            ),
        )
        learner_state = service.infer_learner_state(
            request=request,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        decision = service.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
            affect_state=AffectState(
                frustration_level=0.49,
                confidence_level=0.43,
                momentum_level=0.35,
                needs_reassurance=False,
                urgency_level="medium",
                recovery_signal="steady",
            ),
        )
        self.assertEqual(decision.mode, "review_reflection")
        self.assertIn("adaptive_bias:shrink", decision.reason)
        self.assertIn("recoverable move", decision.primary_goal)

    def test_decide_teaching_uses_direct_rescue_when_overloaded_without_review_anchor(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="I am stuck and overwhelmed, just tell me the smallest safe fix.",
            current_file=_current_file(),
            focus_area="config validation",
        )
        memory_snapshot = _memory_snapshot(due_review_count=0, due_reviews=[], recent_wins=[])
        learner_state = service.infer_learner_state(
            request=request,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        decision = service.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
            affect_state=AffectState(
                frustration_level=0.91,
                confidence_level=0.2,
                momentum_level=0.18,
                needs_reassurance=True,
                urgency_level="high",
                recovery_signal="overloaded",
            ),
        )
        self.assertEqual(decision.mode, "direct_rescue")
        self.assertTrue(decision.should_reveal_code)
        self.assertFalse(decision.should_generate_exercise)
        self.assertIn("affect_recovery:overloaded", decision.reason)

    def test_analyze_turn_classifies_vague_idea_as_idea_implementation(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="I have an idea for a calmer coach reply flow.",
            current_file=None,
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[], current_focus=""),
        )
        self.assertEqual(decision.scenario, "idea_implementation")
        self.assertIsNotNone(artifacts.implementation_guide)

    def test_analyze_turn_keeps_concrete_chinese_idea_out_of_planning(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message=(
                "\u6211\u6709\u4e00\u4e2a AI idea\uff0c\u60f3\u628a\u5b83\u843d\u5730\u6210\u4e00\u4e2a\u6700\u5c0f\u53ef\u9a8c\u8bc1\u7684\u539f\u578b\u3002"
                "\u5148\u522b\u5c55\u5f00\u6210\u603b\u8ba1\u5212\uff0c\u5148\u966a\u6211\u538b\u51fa\u7b2c\u4e00\u6761\u6700\u5c0f\u5207\u7247\u3002"
            ),
            current_file=None,
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[], current_focus=""),
        )
        self.assertEqual(decision.scenario, "idea_implementation")
        self.assertIsNotNone(artifacts.implementation_guide)

    def test_analyze_turn_keeps_chinese_writing_request_out_of_project_adaptation(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message=(
                "\u5e2e\u6211\u6da6\u8272\u4e00\u6bb5\u4e2d\u6587\u9879\u76ee\u8fdb\u5c55\u66f4\u65b0\u3002"
                "\u5148\u53ea\u6539\u8fd9\u4e00\u4e2a\u6bb5\u843d\uff0c\u4e0d\u8981\u628a\u5b83\u53d8\u6210\u5b8c\u6574\u5b66\u4e60\u8ba1\u5212\u3002"
            ),
            current_file=None,
        )
        _, decision, _ = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[], current_focus=""),
        )
        self.assertEqual(decision.scenario, "general")

    def test_analyze_turn_clarifies_vague_idea_instead_of_reusing_memory_focus(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="I have an idea for a calmer onboarding reply flow.",
            current_file=None,
        )
        _, _, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(
                due_review_count=0,
                due_reviews=[],
                current_focus="review rhythm",
                coach_anchor="review rhythm",
            ),
        )
        guide = artifacts.implementation_guide
        assert guide is not None
        self.assertIn("calmer onboarding reply flow", guide.idea_summary.lower())
        self.assertTrue(any("user-visible behavior" in item.lower() for item in guide.open_questions))
        self.assertNotIn("review rhythm", guide.idea_summary.lower())

    def test_analyze_turn_builds_implementation_guide(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Help me build the next visible slice of a review scheduler",
            current_file=_current_file(diagnostics=[]),
            focus_area="review scheduler",
        )
        learner_state, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
        )
        assert learner_state is not None
        self.assertEqual(decision.scenario, "idea_implementation")
        self.assertIsNotNone(artifacts.implementation_guide)
        guide = artifacts.implementation_guide
        assert guide is not None
        self.assertIn("review scheduler", guide.idea_summary.lower())
        self.assertTrue(guide.next_steps)
        self.assertTrue(guide.validation_strategy)
        self.assertTrue(guide.teaching_goal)
        self.assertTrue(guide.success_signal)
        self.assertTrue(guide.fallback_step)
        self.assertIsNotNone(artifacts.exercise_prompt)
        assert artifacts.exercise_prompt is not None
        self.assertEqual(artifacts.exercise_prompt["scenario"], "idea_implementation")

    def test_implementation_guide_prefers_workspace_entry_points_for_project_idea(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="I want to build a steadier coach reply flow for this project.",
            current_file=None,
        )
        _, _, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(
                due_review_count=0,
                due_reviews=[],
                current_focus="",
                workspace_understanding=_workspace_understanding(),
            ),
        )
        guide = artifacts.implementation_guide
        assert guide is not None
        self.assertEqual(guide.codebase_entry_points[0], "server/app/api/routers.py")
        self.assertIn("server/app/api/routers.py", guide.current_step)

    def test_direct_rescue_still_builds_implementation_guide(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="I am stuck and overwhelmed, just tell me the smallest safe fix for the reply flow.",
            current_file=_current_file(diagnostics=[]),
            focus_area="reply flow",
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
            affect_state=AffectState(
                frustration_level=0.91,
                confidence_level=0.2,
                momentum_level=0.18,
                needs_reassurance=True,
                urgency_level="high",
                recovery_signal="overloaded",
            ),
        )
        self.assertEqual(decision.mode, "direct_rescue")
        guide = artifacts.implementation_guide
        assert guide is not None
        self.assertTrue(guide.current_step)
        self.assertTrue(guide.validation_strategy)
        self.assertTrue(guide.fallback_step)

    def test_analyze_turn_mines_project_ideas(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="What project idea should I extract from this codebase next?",
            current_file=_current_file(),
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(),
        )
        self.assertEqual(decision.scenario, "project_idea_mining")
        self.assertGreaterEqual(len(artifacts.project_ideas), 1)
        self.assertLessEqual(len(artifacts.project_ideas), 3)
        self.assertTrue(any(idea.idea_kind in {"feature", "test", "refactor"} for idea in artifacts.project_ideas))
        self.assertTrue(all(idea.difficulty in {"small", "medium", "stretch"} for idea in artifacts.project_ideas))
        self.assertTrue(all(idea.why_now for idea in artifacts.project_ideas))
        self.assertTrue(all(idea.first_step for idea in artifacts.project_ideas))
        self.assertIsNotNone(artifacts.exercise_prompt)
        assert artifacts.exercise_prompt is not None
        self.assertEqual(artifacts.exercise_prompt["scenario"], "project_idea_mining")

    def test_missing_test_idea_is_skipped_when_test_anchor_exists(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="What project idea should I extract from this codebase next?",
            current_file=_current_file(
                related_files=[
                    {"path": "server/tests/test_planner.py", "reason": "verification"},
                    {"path": "server/app/core/models.py", "reason": "contracts"},
                ]
            ),
        )
        _, _, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(),
        )
        self.assertTrue(all(idea.idea_kind != "test" for idea in artifacts.project_ideas))

    def test_analyze_turn_builds_project_adaptation_guide(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="按我的意图改造这个项目，让 planner 更像长期教练",
            current_file=_current_file(),
            focus_area="planner as a long-term coach",
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(),
        )
        self.assertEqual(decision.scenario, "project_adaptation")
        self.assertIsNotNone(artifacts.adaptation_guide)
        guide = artifacts.adaptation_guide
        assert guide is not None
        self.assertTrue(guide.affected_areas)
        self.assertTrue(guide.migration_sequence)
        self.assertTrue(guide.validation_checkpoints)
        self.assertTrue(guide.preserve_areas)
        self.assertTrue(guide.first_migration_step.startswith("先"))
        self.assertTrue(any("第一层边界" in item or "边界" in item for item in guide.validation_checkpoints))
        self.assertIsNotNone(artifacts.exercise_prompt)
        assert artifacts.exercise_prompt is not None
        self.assertEqual(artifacts.exercise_prompt["scenario"], "project_adaptation")

    def test_project_adaptation_classifier_handles_turn_this_project_into_language(self) -> None:
        service = PedagogyService()
        chinese = service.analyze_turn(
            request=TurnRequest(
                message="我想把项目改成长期教练模式。",
                current_file=_current_file(),
            ),
            profile=_profile(),
            memory_snapshot=_memory_snapshot(),
        )[1]
        english = service.analyze_turn(
            request=TurnRequest(
                message="Turn this project into a long-term coach.",
                current_file=_current_file(),
            ),
            profile=_profile(),
            memory_snapshot=_memory_snapshot(),
        )[1]
        self.assertEqual(chinese.scenario, "project_adaptation")
        self.assertEqual(english.scenario, "project_adaptation")

    def test_analyze_turn_suggests_project_sources(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="帮我找适合训练长期教练能力的公开项目来源。",
            current_file=_current_file(diagnostics=[]),
            focus_area="long-term coaching flow",
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
        )
        self.assertEqual(decision.scenario, "project_sourcing")
        self.assertGreaterEqual(len(artifacts.project_sources), 1)
        self.assertTrue(artifacts.project_sources[0].repo_hint)
        self.assertTrue(artifacts.project_sources[0].first_task)

    def test_project_sourcing_prefers_grounded_external_reference_when_available(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="帮我找适合训练长期教练能力的公开项目来源。",
            current_file=_current_file(diagnostics=[]),
            focus_area="long-term coaching flow",
        )
        memory_snapshot = _memory_snapshot(
            due_review_count=0,
            due_reviews=[],
            resources=[
                ResourceRecord(
                    id="resource-grounded",
                    kind="markdown",
                    name="Coach Research Note",
                    source="/tmp/coach-research.md",
                    canonical_source="https://example.com/coach-research",
                    summary="Grounded source for coaching flow.",
                    parse_status="parsed",
                    index_status="indexed",
                    trust_score=0.88,
                    freshness="fresh",
                    quality_flags=[],
                    source_governance=_eligible_source_governance(),
                    knowledge_fragments=[
                        {
                            "id": "frag-1",
                            "snippet": "Keep the next implementation slice thin and verifiable.",
                            "source": "https://example.com/coach-research",
                            "trust_score": 0.88,
                            "freshness": "fresh",
                            "why_it_matters": "Grounds a realistic coach-first implementation lane.",
                        }
                    ],
                )
            ],
            teaching_assets=[
                TeachingKnowledgeAsset(
                    kind="implementation_pattern",
                    scope="project",
                    workspace_id="workspace-grounded",
                    title="Thin verified coaching slice",
                    summary="Keep the next implementation slice thin and verifiable.",
                    implementation_pattern="Keep the next implementation slice thin and verifiable.",
                    focus_area="long-term coaching flow",
                    scenario="project_sourcing",
                    source_key="asset::thin-slice",
                    trust_score=0.79,
                )
            ],
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        self.assertEqual(decision.scenario, "project_sourcing")
        self.assertGreaterEqual(len(artifacts.project_sources), 1)
        self.assertIn("Grounded source", artifacts.project_sources[0].title)
        self.assertIn("https://example.com/coach-research", artifacts.project_sources[0].source_url)
        self.assertIn("commercial_reuse_eligible", artifacts.project_sources[0].quality_flags)
        self.assertIn("controlled_source", artifacts.project_sources[0].quality_flags)
        self.assertTrue(
            any("teaching_asset_grounded" in item.quality_flags for item in artifacts.project_sources[1:])
        )

    def test_project_sourcing_uses_relevant_teaching_asset_as_grounded_source(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="帮我找适合训练长期教练能力的公开项目来源。",
            current_file=_current_file(diagnostics=[]),
            focus_area="long-term coaching flow",
        )
        memory_snapshot = _memory_snapshot(
            due_review_count=0,
            due_reviews=[],
            resources=[],
            teaching_assets=[
                TeachingKnowledgeAsset(
                    kind="implementation_pattern",
                    scope="project",
                    workspace_id="workspace-grounded",
                    title="Thin verified coaching slice",
                    summary="Keep the next implementation slice thin and verifiable.",
                    implementation_pattern="Keep the next implementation slice thin and verifiable.",
                    focus_area="long-term coaching flow",
                    scenario="project_sourcing",
                    source_key="asset::thin-slice",
                    trust_score=0.82,
                ),
                TeachingKnowledgeAsset(
                    kind="concept_card",
                    scope="project",
                    workspace_id="workspace-grounded",
                    title="Unrelated deployment note",
                    summary="General deployment reminder.",
                    concept_card="General deployment reminder.",
                    focus_area="deployment",
                    scenario="planning",
                    source_key="asset::deployment",
                    trust_score=0.5,
                ),
            ],
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        self.assertEqual(decision.scenario, "project_sourcing")
        grounded = next(
            item for item in artifacts.project_sources if "teaching_asset_grounded" in item.quality_flags
        )
        self.assertIn("Thin verified coaching slice", grounded.title)
        self.assertIn("Thin verified coaching slice", grounded.repo_hint)
        self.assertIn("thin and verifiable", grounded.first_task.lower())

    def test_project_sourcing_uses_workspace_understanding_as_grounding_when_no_resources_exist(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="帮我找适合训练长期教练能力的公开项目来源。",
            current_file=_current_file(diagnostics=[]),
            focus_area="long-term coaching flow",
        )
        memory_snapshot = _memory_snapshot(
            due_review_count=0,
            due_reviews=[],
            resources=[],
            teaching_assets=[],
            workspace_understanding=WorkspaceUnderstandingSnapshot(
                repo_summary="Reply assembly currently flows through the coach router and planner boundary.",
                entry_points=["server/app/api/routers.py", "server/app/pedagogy/service.py"],
                feature_lanes=["Keep the reply assembly lane narrow and verifiable."],
                risk_zones=["Recent edits already span multiple coaching files."],
                training_opportunities=["Strengthen the first reply path before widening the workflow."],
                resource_brief="",
            ),
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        self.assertEqual(decision.scenario, "project_sourcing")
        grounded = next(
            item for item in artifacts.project_sources if "workspace_grounded" in item.quality_flags
        )
        self.assertIn("Current workspace training lane", grounded.title)
        self.assertIn("server/app/api/routers.py", grounded.repo_hint)
        self.assertIn("server/app/api/routers.py", grounded.first_task)

    def test_project_sourcing_uses_background_external_references_when_provided(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="帮我找适合训练长期教练能力的公开项目来源。",
            current_file=_current_file(diagnostics=[]),
            focus_area="long-term coaching flow",
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[], resources=[], teaching_assets=[]),
            external_references=[
                {
                    "title": "Boundary-first coach research",
                    "source": "https://example.com/coach-research",
                    "snippet": "Map one verified boundary before widening scope.",
                    "trust_score": 0.91,
                    "focus_area": "long-term coaching flow",
                    "source_type": "external:web",
                    "why_it_matters": "Keeps the first transfer concrete and verifiable.",
                    "source_governance": _eligible_source_governance().model_dump(mode="json"),
                }
            ],
        )
        self.assertEqual(decision.scenario, "project_sourcing")
        self.assertGreaterEqual(len(artifacts.project_sources), 1)
        self.assertEqual(artifacts.project_sources[0].source_url, "https://example.com/coach-research")
        self.assertIn("Boundary-first coach research", artifacts.project_sources[0].title)
        self.assertIn("verified boundary", artifacts.project_sources[0].first_task.lower())
        self.assertIn("commercial_reuse_eligible", artifacts.project_sources[0].quality_flags)

    def test_project_sourcing_excludes_external_sources_without_eligible_controlled_governance(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Find a public project source for long-term coaching practice.",
            current_file=_current_file(diagnostics=[]),
            focus_area="long-term coaching flow",
        )
        review_required = SourceIntakeGovernance(
            source_provenance_status="fetched",
            commercial_reuse_status="review_required",
            commercial_reuse_reason_codes=["license_unknown"],
        )
        blocked = SourceIntakeGovernance(
            source_provenance_status="fetched",
            commercial_reuse_status="blocked",
            commercial_reuse_reason_codes=["license_not_in_permissive_allowlist"],
        )
        uncontrolled_eligible = _eligible_source_governance().model_copy(
            update={"source_provenance_status": "unknown"}
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[], resources=[], teaching_assets=[]),
            external_references=[
                {
                    "title": "Eligible controlled source",
                    "source": "https://example.com/eligible",
                    "snippet": "Use one verified boundary.",
                    "source_governance": _eligible_source_governance().model_dump(mode="json"),
                },
                {
                    "title": "Needs review",
                    "source": "https://example.com/review",
                    "snippet": "Unverified license details.",
                    "source_governance": review_required.model_dump(mode="json"),
                },
                {
                    "title": "Blocked source",
                    "source": "https://example.com/blocked",
                    "snippet": "Copyleft source without reuse clearance.",
                    "source_governance": blocked.model_dump(mode="json"),
                },
                {
                    "title": "Missing governance",
                    "source": "https://example.com/missing",
                    "snippet": "No source review record is attached.",
                },
                {
                    "title": "Uncontrolled eligible claim",
                    "source": "https://example.com/uncontrolled",
                    "snippet": "The provenance was never controlled.",
                    "source_governance": uncontrolled_eligible.model_dump(mode="json"),
                },
                {
                    "title": "Spoofed URL source",
                    "source": "opaque-reference",
                    "source_type": "URL:example.com",
                    "snippet": "A top-level eligibility claim is not governance evidence.",
                    "commercial_reuse_status": "eligible",
                    "source_governance": SourceIntakeGovernance(
                        source_provenance_status="fetched",
                        commercial_reuse_status="review_required",
                        commercial_reuse_reason_codes=["license_unknown"],
                    ).model_dump(mode="json"),
                },
            ],
        )

        self.assertEqual(decision.scenario, "project_sourcing")
        source_urls = {item.source_url for item in artifacts.project_sources}
        self.assertIn("https://example.com/eligible", source_urls)
        self.assertNotIn("https://example.com/review", source_urls)
        self.assertNotIn("https://example.com/blocked", source_urls)
        self.assertNotIn("https://example.com/missing", source_urls)
        self.assertNotIn("https://example.com/uncontrolled", source_urls)
        self.assertNotIn("opaque-reference", source_urls)
        eligible = next(item for item in artifacts.project_sources if item.source_url.endswith("/eligible"))
        self.assertIn("commercial_reuse_eligible", eligible.quality_flags)
        self.assertIn("controlled_source", eligible.quality_flags)

    def test_analyze_turn_builds_principle_note(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Why is this a better approach? Explain the principle behind it.",
            current_file=_current_file(),
            focus_area="review-first planning",
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(),
        )
        self.assertEqual(decision.scenario, "principle_explanation")
        self.assertIsNotNone(artifacts.principle_note)
        note = artifacts.principle_note
        assert note is not None
        self.assertIn("review-first planning", note.current_principle.lower())
        self.assertTrue(note.related_checks)
        self.assertIn("server/app/planner/service.py", note.concrete_anchor)
        self.assertTrue(note.why_this_approach)
        self.assertTrue(note.common_wrong_intuition)
        self.assertTrue(note.transferable_lesson)
        self.assertTrue(note.follow_up_exercise)
        self.assertIsNotNone(artifacts.exercise_prompt)
        assert artifacts.exercise_prompt is not None
        self.assertEqual(artifacts.exercise_prompt["scenario"], "principle_explanation")
        self.assertTrue(artifacts.exercise_prompt["success_signal"])

    def test_diagnosis_does_not_collapse_into_principle_explanation(self) -> None:
        service = PedagogyService()
        _, decision, _ = service.analyze_turn(
            request=TurnRequest(
                message="Help me diagnose why auth.py fails before we generate a plan or a task.",
                current_file=_current_file(),
                focus_area="auth expiry",
            ),
            profile=_profile(),
            memory_snapshot=_memory_snapshot(),
        )
        self.assertEqual(decision.scenario, "review_reflection")
        self.assertNotEqual(decision.scenario, "principle_explanation")

    def test_decide_teaching_for_planning_mode(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Help me plan the next milestone and sequence it tightly.",
            current_file=_current_file(diagnostics=[]),
            intent="plan",
            focus_area="review scheduler rollout",
        )
        learner_state = service.infer_learner_state(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
        )
        decision = service.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
        )
        self.assertEqual(decision.scenario, "planning")
        self.assertEqual(decision.mode, "planning")
        self.assertTrue(decision.should_produce_plan_artifact)
        self.assertFalse(decision.should_end_with_question)
        self.assertIn("plan", decision.artifact_priority)

    def test_decide_teaching_for_concept_teaching_mode(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Teach me this concept through the current code, not abstract theory.",
            current_file=_current_file(),
            focus_area="review loop boundaries",
        )
        learner_state, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
        )
        assert learner_state is not None
        self.assertEqual(decision.scenario, "concept_teaching")
        self.assertEqual(decision.mode, "concept_teaching")
        self.assertIsNotNone(artifacts.principle_note)
        self.assertIsNotNone(artifacts.exercise_prompt)
        assert artifacts.exercise_prompt is not None
        self.assertEqual(artifacts.exercise_prompt["scenario"], "concept_teaching")
        self.assertEqual(artifacts.exercise_prompt["lesson_shape"], decision.lesson_shape)
        self.assertIn("plain words", artifacts.exercise_prompt["success_signal"].lower())
        self.assertTrue(
            any("plain language" in item.lower() or "transfer" in item.lower() for item in artifacts.exercise_prompt["constraints"])
        )

    def test_decide_teaching_for_engineering_challenge_mode(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Give me a project-backed engineering challenge around review scheduling.",
            current_file=_current_file(diagnostics=[]),
            intent="task",
            focus_area="review scheduling",
        )
        learner_state, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
        )
        assert learner_state is not None
        self.assertEqual(decision.scenario, "engineering_challenge")
        self.assertEqual(decision.mode, "engineering_challenge")
        self.assertTrue(decision.should_focus_on_implementation_steps)
        self.assertIsNotNone(artifacts.implementation_guide)
        self.assertIsNotNone(artifacts.exercise_prompt)
        assert artifacts.exercise_prompt is not None
        self.assertEqual(artifacts.exercise_prompt["scenario"], "engineering_challenge")
        self.assertIn("challenge", decision.artifact_priority)

    def test_engineering_challenge_biases_prompt_toward_top_weakness(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Give me a project-backed engineering challenge around review scheduling.",
            current_file=_current_file(diagnostics=[]),
            intent="task",
            focus_area="review scheduling",
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(
                due_review_count=0,
                due_reviews=[],
                top_weakness="testing",
            ),
        )
        self.assertEqual(decision.scenario, "engineering_challenge")
        assert artifacts.exercise_prompt is not None
        self.assertIn("testing", artifacts.exercise_prompt["prompt"].lower())
        self.assertTrue(
            any("weak spot" in item.lower() or "testing" in item.lower() for item in artifacts.exercise_prompt["constraints"])
        )

    def test_exercise_prompt_reuses_matching_teaching_asset_constraint(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Help me implement the next visible slice of a review scheduler.",
            current_file=_current_file(diagnostics=[]),
            focus_area="review scheduler",
        )
        memory_snapshot = _memory_snapshot(
            due_review_count=0,
            due_reviews=[],
            teaching_assets=[
                TeachingKnowledgeAsset(
                    kind="implementation_pattern",
                    scope="project",
                    workspace_id="workspace-pedagogy",
                    title="Review scheduler pattern",
                    summary="Keep the review scheduler inside one verified branch.",
                    implementation_pattern="Keep the review scheduler inside one verified branch.",
                    focus_area="review scheduler",
                    scenario="idea_implementation",
                    source_key="pattern::review-scheduler",
                    trust_score=0.8,
                ),
                TeachingKnowledgeAsset(
                    kind="concept_card",
                    scope="project",
                    workspace_id="workspace-pedagogy",
                    title="Unrelated note",
                    summary="General deployment reminder.",
                    concept_card="General deployment reminder.",
                    focus_area="deployment",
                    scenario="planning",
                    source_key="concept::deployment",
                    trust_score=0.6,
                ),
            ],
        )
        _, decision, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        assert artifacts.exercise_prompt is not None
        self.assertEqual(decision.scenario, "idea_implementation")
        self.assertTrue(
            any(
                "review scheduler inside one verified branch" in item.lower()
                for item in artifacts.exercise_prompt["constraints"]
            )
        )
        self.assertIn("verified pattern", decision.teaching_strategy.lower())

    def test_repeated_failures_shrink_the_next_coaching_move(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Help me keep fixing this config validation path.",
            current_file=_current_file(diagnostics=[]),
            focus_area="config validation",
        )
        memory_snapshot = _memory_snapshot(
            due_review_count=1,
            coaching_adaptation=CoachingAdaptationProfile(
                challenge_level="lower",
                hint_depth="direct",
                review_urgency="high",
                explanation_mode="rebuild",
                next_step_bias="shrink",
                summary="Recent failures mean the next loop must shrink.",
                evidence=["Still failing config validation twice in a row."],
            ),
        )
        learner_state = service.infer_learner_state(
            request=request,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        decision = service.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        artifacts = service.build_artifacts(
            request=request,
            learner_state=learner_state,
            decision=decision,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        self.assertIn("adaptive_bias:shrink", decision.reason)
        self.assertIn("recoverable move", decision.primary_goal)
        assert artifacts.exercise_prompt is not None
        self.assertTrue(
            any(
                "recoverable" in item.lower() or "do not widen" in item.lower()
                for item in artifacts.exercise_prompt["constraints"]
            )
        )

    def test_recent_success_can_raise_engineering_challenge_mode(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Give me a project-backed engineering challenge.",
            current_file=_current_file(diagnostics=[]),
            focus_area="review scheduler",
            intent="task",
        )
        memory_snapshot = _memory_snapshot(
            due_review_count=0,
            due_reviews=[],
            coaching_adaptation=CoachingAdaptationProfile(
                challenge_level="raise",
                hint_depth="lighter",
                review_urgency="low",
                explanation_mode="transfer",
                next_step_bias="widen",
                summary="Recent wins justify a slightly stronger next challenge.",
                evidence=["The last review scheduler slice was verified."],
            ),
        )
        learner_state = service.infer_learner_state(
            request=request,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        decision = service.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        artifacts = service.build_artifacts(
            request=request,
            learner_state=learner_state,
            decision=decision,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        self.assertEqual(decision.mode, "challenge")
        assert artifacts.exercise_prompt is not None
        self.assertIn("transfers", artifacts.exercise_prompt["success_signal"].lower())
        self.assertIn("avoid over-explaining", decision.teaching_strategy.lower())
        self.assertIn("transfer the idea", decision.lesson_shape.lower())

    def test_rebuild_explanation_mode_adds_explicit_recovery_guidance(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="Help me keep fixing this config validation path.",
            current_file=_current_file(diagnostics=[]),
            focus_area="config validation",
        )
        memory_snapshot = _memory_snapshot(
            due_review_count=1,
            coaching_adaptation=CoachingAdaptationProfile(
                challenge_level="lower",
                hint_depth="direct",
                review_urgency="high",
                explanation_mode="rebuild",
                next_step_bias="shrink",
                summary="Recent failures mean the next loop must shrink and rebuild.",
                evidence=["Still failing config validation twice in a row."],
            ),
        )
        learner_state = service.infer_learner_state(
            request=request,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        decision = service.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        artifacts = service.build_artifacts(
            request=request,
            learner_state=learner_state,
            decision=decision,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        self.assertEqual(learner_state.preferred_hint_depth, "direct")
        self.assertIn("explicit", decision.teaching_strategy.lower())
        self.assertIn("rebuild the mental model", decision.lesson_shape.lower())
        assert artifacts.exercise_prompt is not None
        self.assertTrue(
            any("recoverable" in item.lower() or "do not widen" in item.lower() for item in artifacts.exercise_prompt["constraints"])
        )

    def test_decide_teaching_modes_have_distinct_playbooks(self) -> None:
        service = PedagogyService()
        idea_decision = service.decide_teaching(
            request=TurnRequest(
                message="Help me implement a review scheduler for this trainer",
                current_file=_current_file(diagnostics=[]),
                focus_area="review scheduler",
            ),
            learner_state=service.infer_learner_state(
                request=TurnRequest(
                    message="Help me implement a review scheduler for this trainer",
                    current_file=_current_file(diagnostics=[]),
                    focus_area="review scheduler",
                ),
                profile=_profile(),
                memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
            ),
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
        )
        principle_decision = service.decide_teaching(
            request=TurnRequest(
                message="Why is this a better approach? Explain the principle behind it.",
                current_file=_current_file(),
                focus_area="review-first planning",
            ),
            learner_state=service.infer_learner_state(
                request=TurnRequest(
                    message="Why is this a better approach? Explain the principle behind it.",
                    current_file=_current_file(),
                    focus_area="review-first planning",
                ),
                profile=_profile(),
                memory_snapshot=_memory_snapshot(),
            ),
            profile=_profile(),
            memory_snapshot=_memory_snapshot(),
        )
        self.assertNotEqual(idea_decision.lesson_shape, principle_decision.lesson_shape)
        self.assertNotEqual(idea_decision.exercise_shape, principle_decision.exercise_shape)
        self.assertNotEqual(idea_decision.teaching_strategy, principle_decision.teaching_strategy)

    def test_artifacts_payload_is_router_friendly(self) -> None:
        service = PedagogyService()
        request = TurnRequest(
            message="What project idea should I extract from this codebase next?",
            current_file=_current_file(),
        )
        _, _, artifacts = service.analyze_turn(
            request=request,
            profile=_profile(),
            memory_snapshot=_memory_snapshot(),
        )
        payload = artifacts.to_payload()
        self.assertIn("project_ideas", payload)
        self.assertIsInstance(payload["project_ideas"], list)
        self.assertIn("title", payload["project_ideas"][0])
        source_payload = service.analyze_turn(
            request=TurnRequest(
                message="帮我找适合训练 review rhythm 的公开项目。",
                current_file=_current_file(diagnostics=[]),
                focus_area="review rhythm",
            ),
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
        )[2].to_payload()
        self.assertIn("project_sources", source_payload)
        self.assertIn("exercise_prompt", service.analyze_turn(
            request=TurnRequest(
                message="Help me build the next visible slice of a review scheduler",
                current_file=_current_file(diagnostics=[]),
                focus_area="review scheduler",
            ),
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
        )[2].to_payload())
        exercise_payload = service.analyze_turn(
            request=TurnRequest(
                message="Teach me this concept through the current code, not abstract theory.",
                current_file=_current_file(),
                focus_area="review loop boundaries",
            ),
            profile=_profile(),
            memory_snapshot=_memory_snapshot(),
        )[2].to_payload()
        self.assertIn("lesson_shape", exercise_payload["exercise_prompt"])
        self.assertIn("teaching_strategy", exercise_payload["exercise_prompt"])

    def test_exercise_prompt_uses_teaching_knowledge_catalog_hint(self) -> None:
        service = PedagogyService()
        memory_snapshot = _memory_snapshot(
            due_review_count=0,
            due_reviews=[],
            teaching_assets=[
                TeachingKnowledgeAsset(
                    kind="implementation_pattern",
                    scope="project",
                    workspace_id="workspace-pedagogy",
                    title="Review scheduler pattern",
                    summary="Keep the review scheduler inside one verified branch.",
                    implementation_pattern="Keep the review scheduler inside one verified branch.",
                    origin="learning_outcome",
                    focus_area="review scheduler",
                    scenario="idea_implementation",
                    source_key="pattern::review-scheduler",
                    trust_score=0.82,
                )
            ],
        )
        memory_snapshot.teaching_knowledge_catalog = {
            "total": 1,
            "top_assets": [
                {
                    "id": "asset-1",
                    "title": "Review scheduler pattern",
                    "kind": "implementation_pattern",
                    "scope": "project",
                    "origin": "learning_outcome",
                    "focus_area": "review scheduler",
                    "scenario": "idea_implementation",
                    "summary": "Keep the review scheduler inside one verified branch.",
                    "trust_score": 0.82,
                    "usage_count": 0,
                }
            ],
        }
        _, decision, artifacts = service.analyze_turn(
            request=TurnRequest(
                message="Help me implement the next visible slice of a review scheduler.",
                current_file=_current_file(diagnostics=[]),
                focus_area="review scheduler",
            ),
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        self.assertEqual(decision.scenario, "idea_implementation")
        assert artifacts.exercise_prompt is not None
        self.assertTrue(
            any(
                "teaching asset 'Review scheduler pattern'" in item
                for item in artifacts.exercise_prompt["constraints"]
            )
        )

    def test_principle_explanation_reuses_matching_teaching_asset(self) -> None:
        service = PedagogyService()
        memory_snapshot = _memory_snapshot(
            teaching_assets=[
                TeachingKnowledgeAsset(
                    kind="explanation_recipe",
                    scope="project",
                    workspace_id="workspace-pedagogy",
                    title="Boundary-first explanation",
                    summary="Start from the failing branch before widening into architecture.",
                    explanation_recipe="Start from the failing branch before widening into architecture.",
                    focus_area="review-first planning",
                    scenario="principle_explanation",
                    source_key="explanation::boundary-first",
                    trust_score=0.9,
                )
            ],
        )
        _, decision, artifacts = service.analyze_turn(
            request=TurnRequest(
                message="Why is this a better approach? Explain the principle behind it.",
                current_file=_current_file(),
                focus_area="review-first planning",
            ),
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        self.assertEqual(decision.scenario, "principle_explanation")
        assert artifacts.principle_note is not None
        self.assertIn("Boundary-first explanation", artifacts.principle_note.why_this_approach)
        assert artifacts.exercise_prompt is not None
        self.assertTrue(
            any("Boundary-first explanation" in item for item in artifacts.exercise_prompt["constraints"])
        )

    def test_principle_explanation_prefers_explanation_asset_and_catalog_hint(self) -> None:
        service = PedagogyService()
        memory_snapshot = _memory_snapshot(
            due_review_count=0,
            due_reviews=[],
            teaching_assets=[
                TeachingKnowledgeAsset(
                    kind="implementation_pattern",
                    scope="project",
                    workspace_id="workspace-pedagogy",
                    title="Implementation-first fallback",
                    summary="Ship the smallest patch before expanding.",
                    implementation_pattern="Ship the smallest patch before expanding.",
                    focus_area="review-first planning",
                    scenario="idea_implementation",
                    source_key="pattern::implementation-first",
                    trust_score=0.97,
                ),
                TeachingKnowledgeAsset(
                    kind="explanation_recipe",
                    scope="project",
                    workspace_id="workspace-pedagogy",
                    title="Boundary-first explanation",
                    summary="Start from the failing branch before widening into architecture.",
                    explanation_recipe="Start from the failing branch before widening into architecture.",
                    why_it_matters="It keeps the mechanism visible before the explanation turns abstract.",
                    example="Walk one failing branch, then name the rule it reveals.",
                    focus_area="review-first planning",
                    scenario="principle_explanation",
                    source_key="explanation::boundary-first",
                    trust_score=0.88,
                ),
            ],
        )
        memory_snapshot.teaching_knowledge_catalog = {
            "total": 2,
            "top_assets": [
                {
                    "id": "asset-boundary-first",
                    "title": "Boundary-first explanation",
                    "kind": "explanation_recipe",
                    "scope": "project",
                    "origin": "learning_outcome",
                    "focus_area": "review-first planning",
                    "scenario": "principle_explanation",
                    "summary": "Start from the failing branch before widening into architecture.",
                    "trust_score": 0.88,
                    "usage_count": 0,
                }
            ],
        }
        _, decision, artifacts = service.analyze_turn(
            request=TurnRequest(
                message="Why is this a better approach? Explain the principle behind it.",
                current_file=_current_file(),
                focus_area="review-first planning",
            ),
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        self.assertEqual(decision.scenario, "principle_explanation")
        assert artifacts.principle_note is not None
        self.assertIn("Boundary-first explanation", artifacts.principle_note.why_this_approach)
        self.assertIn("Walk one failing branch", artifacts.principle_note.follow_up_exercise)
        self.assertIn("It keeps the mechanism visible", artifacts.principle_note.transferable_lesson)
        assert artifacts.exercise_prompt is not None
        self.assertTrue(
            any(
                "Teach from the knowledge base asset 'Boundary-first explanation'" in item
                for item in artifacts.exercise_prompt["constraints"]
            )
        )

    def test_project_idea_mining_promotes_asset_backed_idea_into_exercise_prompt(self) -> None:
        service = PedagogyService()
        memory_snapshot = _memory_snapshot(
            due_review_count=0,
            due_reviews=[],
            teaching_assets=[
                TeachingKnowledgeAsset(
                    kind="exercise_seed",
                    scope="project",
                    workspace_id="workspace-pedagogy",
                    title="Review scheduler regression loop",
                    summary="Turn the saved review scheduler boundary into one regression-first exercise.",
                    exercise_seed="Turn the saved review scheduler boundary into one regression-first exercise.",
                    focus_area="review scheduler",
                    scenario="project_idea_mining",
                    source_key="exercise::review-scheduler-regression",
                    trust_score=0.9,
                )
            ],
        )
        _, decision, artifacts = service.analyze_turn(
            request=TurnRequest(
                message="What should I build or extract from this codebase next?",
                current_file=_current_file(diagnostics=[]),
                focus_area="review scheduler",
            ),
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        self.assertEqual(decision.scenario, "project_idea_mining")
        assert artifacts.project_ideas
        self.assertIn("Review scheduler regression loop", artifacts.project_ideas[0].title)
        self.assertEqual(artifacts.project_ideas[0].idea_kind, "test")
        assert artifacts.exercise_prompt is not None
        self.assertEqual(artifacts.exercise_prompt["title"], artifacts.project_ideas[0].title)
        self.assertEqual(artifacts.exercise_prompt["prompt"], artifacts.project_ideas[0].first_step)
        self.assertEqual(
            artifacts.exercise_prompt["success_signal"],
            artifacts.project_ideas[0].acceptance_signals[0],
        )

    def test_principle_explanation_mode_stays_distinct_from_idea_implementation(self) -> None:
        service = PedagogyService()
        principle = service.analyze_turn(
            request=TurnRequest(
                message="Why is this a better approach? Explain the principle behind it.",
                current_file=_current_file(),
                focus_area="review-first planning",
            ),
            profile=_profile(),
            memory_snapshot=_memory_snapshot(),
        )
        idea = service.analyze_turn(
            request=TurnRequest(
                message="Help me implement a review scheduler for this trainer",
                current_file=_current_file(diagnostics=[]),
                focus_area="review scheduler",
            ),
            profile=_profile(),
            memory_snapshot=_memory_snapshot(due_review_count=0, due_reviews=[]),
        )
        self.assertEqual(principle[1].scenario, "principle_explanation")
        self.assertEqual(principle[1].mode, "principle_explanation")
        self.assertEqual(idea[1].scenario, "idea_implementation")
        self.assertNotEqual(principle[1].lesson_shape, idea[1].lesson_shape)
        self.assertNotEqual(principle[1].teaching_strategy, idea[1].teaching_strategy)


if __name__ == "__main__":
    unittest.main()
