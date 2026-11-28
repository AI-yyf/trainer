"""(r) Coaching turn truth: the visible reply, its grounding and its next step are
    derived from real context, never from theater.

Guarantees covered:
  * visible coach text is sanitized, language-aligned and free of credential-shaped strings;
  * next steps and file references are grounded in real resources and the learner's project;
  * turn decisions, lanes and budgets are deterministic under context pressure;
  * pedagogy, teaching depth and explanation quality are derived from real turn facts.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_pedagogy.py
  * server/tests/test_explanation_quality.py
  * server/tests/test_prompt_lane_detection.py
  * server/tests/test_coach_orientation.py
  * server/tests/test_builtin_teaching_skill.py
  * server/tests/test_image_attachment_validation.py
  * server/tests/test_language_integrity_guards.py
  * server/tests/test_coach_language_alignment.py
  * server/tests/test_harness_retrieval.py
  * server/tests/test_stage1_rethinkfun_truth_and_proxy.py
  * server/tests/test_teaching_quality.py
  * server/tests/test_rethinkfun_teaching_prompt.py
  * server/tests/test_attached_material_prompt.py
  * server/tests/test_language_short_answer.py
  * server/tests/test_mixed_script_noise_sanitization.py
  * server/tests/test_smart_budget_and_rich_tools.py
  * server/tests/test_explicit_explanation_priority.py
  * server/tests/test_proactive_budget.py
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import struct
import sys
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import fitz
import pytest
from PIL import Image
from pydantic import ValidationError

from app.api.coach_language_alignment import (
    language_aligned_coaching_state_payload,
    language_aligned_context_list,
    language_aligned_context_text,
    language_aligned_flat_payload,
    language_aligned_review_rhythm,
    localize_known_context_phrases,
)
from app.core.image_attachments import MAX_IMAGE_BASE64_LENGTH, validate_image_payload
from app.core.models import (
    AffectState,
    CoachingAdaptationProfile,
    CurrentFilePayload,
    FirstLookSummary,
    LearningPlan,
    MemorySnapshot,
    MessageAttachment,
    PlanStage,
    ProviderConfig,
    ProviderTestResponse,
    ResourceRecord,
    ReviewQueueItem,
    SessionMessageRequest,
    SourceIntakeGovernance,
    TeachingKnowledgeAsset,
    TurnRequest,
    UserProfile,
    WorkbenchSnapshot,
    WorkspaceUnderstandingSnapshot,
)
from app.db.repository import TrainerRepository
from app.llm.agent_binding import ProviderAgentBinding
from app.llm.explanation_quality import (
    EXPLANATION_DIMENSIONS,
    EXPLANATION_VERDICTS,
    ExplanationQualityReport,
    evaluate_explanation_quality,
)
from app.llm.harness import DEFAULT_CONTEXT_WINDOW_TOKENS
from app.llm.image_generation import sanitize_generated_svg
from app.llm.prompts import (
    build_coaching_messages,
    build_coaching_system_prompt,
    infer_coaching_scenario,
    infer_learner_signal,
    resolve_smart_history_budget,
)
from app.llm.provider.text import _mixed_script_reply_corruption_detail
from app.llm.provider.thinking import clamp_wire_thinking_budget
from app.llm.provider_service import ProviderService, _strip_short_cyrillic_noise
from app.llm.tools import ToolContext, _handle_search_resources, _retrieval_plan, _trim_hit_text
from app.llm.turn_grounding import TeachingTurnFacts, build_teaching_turn_facts
from app.llm.vision_challenge import build_vision_challenge
from app.memory.proactive_budget import (
    DAILY_PROACTIVE_BUDGET,
    MIN_NUDGE_SPACING_MINUTES,
    evaluate_proactive_opportunity,
    record_proactive_nudge,
)
from app.memory.review_intervention import derive_review_budget
from app.memory.service import MemoryService
from app.memory.workspace_recovery import PLAN_RUNTIME_KEY
from app.pedagogy import PedagogyService
from app.pedagogy.coach_orientation import (
    build_coach_orientation_from_snapshot,
    derive_coach_orientation,
    normalize_coach_orientation,
)
from app.pedagogy.quality import MIN_SAMPLE, evaluate_teaching_quality
from app.resources.service import ResourceService
from app.skills.registry import SkillRegistry
from app.skills.runtime import build_skill_guidance_block, select_active_skills
from app.training.attempt_store import AttemptStore
from tests.client_fixtures import build_client

# ---------------------------------------------------------------------------
# Restored from test_pedagogy.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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

    def test_rescue_step_targets_the_turn_subject_not_the_lane_label(self) -> None:
        """T-0029: the rescue template must name THIS turn's subject. A bare
        lane label that never appears in the learner's message must not become
        the target (observed on real-provider samples: an asyncio first-step
        turn shipped 「先把 implementation 压成一个很小的补丁目标」)."""
        service = PedagogyService()
        request = TurnRequest(
            message="我在学 Python 的 asyncio。请给我一个最小、可验证的第一步，并说明成功信号。",
        )
        memory_snapshot = _memory_snapshot(due_review_count=0, due_reviews=[])
        learner_state = service.infer_learner_state(
            request=request,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        learner_state = replace(learner_state, needs_rescue=True)
        decision = service.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=_profile(),
            memory_snapshot=memory_snapshot,
        )
        # Force the unanchored lane-label condition that real turns hit when
        # the lane/thread focus is the scenario name.
        decision = replace(decision, focus_area="implementation")
        guide = service._implementation_coach.build_guide(
            request=request,
            learner_state=learner_state,
            decision=decision,
            memory_snapshot=memory_snapshot,
        )
        self.assertNotIn("implementation", guide.current_step)
        self.assertIn("asyncio", guide.current_step)


# ---------------------------------------------------------------------------
# Restored from test_explanation_quality.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]


HARNESS_PATH = REPO_ROOT / "scripts" / "maturity" / "real_teaching_journeys_minimax.py"


def _facts(**overrides: str) -> TeachingTurnFacts:
    values: dict[str, str] = {
        "turn_id": "t-explanation",
        "reply_text": "",
        "code_text": "",
        "history_text": "",
        "user_message": "",
        "next_step_text": "",
    }
    values.update(overrides)
    return build_teaching_turn_facts(**values)


def _quality(*, answer_mode: str = "guided", **overrides: str) -> ExplanationQualityReport:
    return evaluate_explanation_quality(_facts(**overrides), answer_mode=answer_mode)


def _dump_reply(line_count: int) -> str:
    """A reply carrying one fenced block with exactly ``line_count`` lines."""
    body = "\n".join(f"items.append({index})  # step {index}" for index in range(line_count))
    return f"完整改法如下：\n```python\n{body}\n```\n跑一次断言试试。"


def test_addresses_learner_ok_when_reply_restates_the_question() -> None:
    report = _quality(
        user_message="为什么可变默认参数会在两次调用之间共享？解释一下 mutable_default 的行为",
        reply_text=(
            "为什么可变默认参数会在两次调用之间共享：因为默认参数只在函数定义时"
            "求值一次，`mutable_default` 这一个列表被所有调用共享。"
        ),
    )
    assert report.dimensions["addresses_learner"] == "ok"
    assert "user content tokens" in report.evidence["addresses_learner"]


def test_addresses_learner_weak_when_reply_ignores_the_question() -> None:
    report = _quality(
        user_message="为什么我的测试断言在并发场景下会失败？asyncio 的事件循环是怎么调度的",
        reply_text=(
            "这是一份关于列表切片边界行为的说明，与当前问题无关。"
            "slice boundary semantics differ."
        ),
    )
    assert report.dimensions["addresses_learner"] == "weak"
    assert "0/" in report.evidence["addresses_learner"]


def test_addresses_learner_unclear_without_user_message() -> None:
    empty = _quality(reply_text="因为默认参数只在定义时求值一次。")
    assert empty.dimensions["addresses_learner"] == "unclear"

    tokenless = _quality(user_message="？？？", reply_text="因为默认参数只在定义时求值一次。")
    assert tokenless.dimensions["addresses_learner"] == "unclear"


def test_language_alignment_ok_for_matching_script_with_english_code() -> None:
    """Fenced English code must never outvote Chinese prose."""
    report = _quality(
        user_message="为什么这段代码会抛出异常？",
        reply_text=(
            "因为列表索引越界了。\n```python\nprint(xs[9])  # IndexError\n```\n"
            "所以你看到 IndexError。"
        ),
    )
    assert report.dimensions["language_alignment"] == "ok"
    assert "cjk vs cjk" in report.evidence["language_alignment"]


def test_language_alignment_weak_for_wrong_script_prose() -> None:
    report = _quality(
        user_message="为什么我的断言失败了？",
        reply_text=(
            "Your assertion failed because the list is empty. Therefore the "
            "lookup returns nothing and the comparison never matches."
        ),
    )
    assert report.dimensions["language_alignment"] == "weak"
    assert "latin vs cjk" in report.evidence["language_alignment"]


def test_language_alignment_unclear_without_judgeable_input() -> None:
    empty = _quality(reply_text="因为默认参数只在定义时求值一次。")
    assert empty.dimensions["language_alignment"] == "unclear"

    code_only = _quality(user_message="为什么失败？", reply_text="```python\nprint(xs)\n```")
    assert code_only.dimensions["language_alignment"] == "unclear"


def test_anchored_symbols_ok_when_reply_covers_next_step_symbols() -> None:
    report = _quality(
        user_message="为什么返回值是 None？",
        reply_text=(
            "因为 `find_first` 现在对空输入直接返回 None，所以先在 `find_first` "
            "里补一个空列表守卫，然后再次运行 `run_checks` 确认。"
        ),
        next_step_text="在 `find_first` 里补一个空列表守卫，再运行 `run_checks` 验证。",
    )
    assert report.dimensions["anchored_symbols"] == "ok"
    assert "2/2 next-step symbols" in report.evidence["anchored_symbols"]


def test_anchored_symbols_weak_when_partially_covered() -> None:
    report = _quality(
        user_message="为什么返回值是 None？",
        reply_text="因为 `find_first` 对空输入直接返回 None，所以先补一个空列表守卫。",
        next_step_text="在 `find_first` 里补一个空列表守卫，再运行 `run_checks` 验证。",
    )
    assert report.dimensions["anchored_symbols"] == "weak"
    assert "run_checks" in report.evidence["anchored_symbols"]


def test_anchored_symbols_unclear_without_symbols() -> None:
    prose_only = _quality(
        user_message="然后呢？",
        reply_text="把第一条实际输出贴回来，我们一起确认。",
        next_step_text="把第一条实际输出贴回来，我们一起确认。",
    )
    assert prose_only.dimensions["anchored_symbols"] == "unclear"

    no_next_symbols = _quality(
        user_message="为什么失败？",
        reply_text="问题出在 `run_checks` 的边界上。",
        next_step_text="把第一条实际输出贴回来，我们一起确认。",
    )
    assert no_next_symbols.dimensions["anchored_symbols"] == "unclear"


def test_solution_dump_guided_flags_large_fenced_block() -> None:
    report = _quality(answer_mode="guided", reply_text=_dump_reply(14))
    assert report.dimensions["no_solution_dump"] == "weak"
    assert report.solution_dump_suspected is True
    assert "14 code line(s)" in report.evidence["no_solution_dump"]


def test_solution_dump_guided_allows_small_snippets_and_prose() -> None:
    snippet = _quality(
        answer_mode="guided",
        reply_text="先试最小修改：\n```python\nitems = []\n```\n然后跑一次断言看看输出。",
    )
    assert snippet.dimensions["no_solution_dump"] == "ok"
    assert snippet.solution_dump_suspected is False

    prose = _quality(
        answer_mode="guided",
        reply_text="因为默认参数只在定义时求值一次，所以两次调用共享同一个列表。",
    )
    assert prose.dimensions["no_solution_dump"] == "ok"
    assert prose.solution_dump_suspected is False


def test_solution_dump_direct_and_practice_modes_are_not_judged() -> None:
    for mode in ("direct", "practice"):
        report = _quality(answer_mode=mode, reply_text=_dump_reply(14))
        assert report.dimensions["no_solution_dump"] == "unclear", mode
        assert report.solution_dump_suspected is False, mode
        assert "guided mode only" in report.evidence["no_solution_dump"]


def test_explains_reasoning_ok_when_marker_sits_near_code() -> None:
    report = _quality(
        user_message="为什么返回值是 None？",
        reply_text="因为 `find_first` 的空列表守卫缺失，函数直接返回了 None。",
    )
    assert report.dimensions["explains_reasoning"] == "ok"
    assert "1 within" in report.evidence["explains_reasoning"]


def test_explains_reasoning_weak_without_any_marker() -> None:
    report = _quality(
        user_message="然后呢？",
        reply_text="把 `find_first` 加上空列表守卫，再运行一次确认。",
    )
    assert report.dimensions["explains_reasoning"] == "weak"
    assert "no reasoning connective" in report.evidence["explains_reasoning"]


def test_explains_reasoning_weak_when_markers_are_far_from_code() -> None:
    filler = "这一段补充说明展开了很多相关的背景细节，供你参考。" * 10
    report = _quality(
        user_message="为什么会共享？",
        reply_text=(
            "因为默认参数在函数定义时只求值一次，所以两次调用共享同一个列表。"
            f"\n{filler}\n参见 `add_item` 的文档。"
        ),
    )
    assert report.dimensions["explains_reasoning"] == "weak"
    assert "0 within" in report.evidence["explains_reasoning"]


def test_explains_reasoning_unclear_for_empty_reply() -> None:
    report = _quality(user_message="为什么失败？")
    assert report.dimensions["explains_reasoning"] == "unclear"


def test_explains_reasoning_unclear_when_guidance_references_no_code() -> None:
    # Calibration (2026-10-14): guidance that references no code gives
    # reasoning-near-code nothing to attach to - recorded as unclear, not weak.
    report = _quality(
        user_message="接下来该怎么安排？",
        reply_text="先把当前这一小步做完，把结果带回来，我们再看下一步的方向。",
        next_step_text="先完成当前这一小步，然后记录结果。",
    )
    assert report.dimensions["explains_reasoning"] == "unclear"
    assert "references no code" in report.evidence["explains_reasoning"]


def test_evaluation_is_pure_and_reports_all_dimensions() -> None:
    facts = build_teaching_turn_facts(
        turn_id="t-purity",
        reply_text="因为 `grid` 的两行是同一个引用，所以修改一行会看到另一行变化。",
        code_text="grid = [[0]]\ngrid[0].append(1)\n",
        history_text="",
        user_message="为什么我改了 grid[0] 之后 grid[1] 也变了？",
        next_step_text="再对 `grid` 做一次实验。",
    )
    report = evaluate_explanation_quality(facts, answer_mode="guided")

    assert isinstance(report, ExplanationQualityReport)
    assert set(report.dimensions) == set(EXPLANATION_DIMENSIONS)
    assert set(report.evidence) == set(EXPLANATION_DIMENSIONS)
    assert all(verdict in EXPLANATION_VERDICTS for verdict in report.dimensions.values())
    assert all(report.evidence[dim].strip() for dim in EXPLANATION_DIMENSIONS)

    # Non-gating by contract: no grounding field was written.
    assert facts.gate_outcome == "grounded"
    assert facts.verdicts == {}
    assert facts.conflicts == []
    assert facts.next_step_claims  # untouched, still populated


CASE = {
    "id": "probe-case",
    "topic_tokens": ["grid"],
    "runtime": "python",
    "primary_file": "x.py",
    "answer_mode": "guided",
}


@pytest.fixture(scope="module")
def harness() -> Any:
    sys.path.insert(0, str(REPO_ROOT / "server"))
    spec = importlib.util.spec_from_file_location("maturity_harness_eq", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(*, next_step: str, reply: str) -> dict:
    return {
        "reply": {"content": reply},
        "coach_turn": {"next_step": next_step, "requires_confirmation": False},
        "agent_meta": {
            "grounding_outcome": "grounded",
            "grounding_ungrounded_symbols": [],
            "grounding_retry_used": False,
        },
        "snapshot": {"memory": {}},
    }


def test_harness_records_explanation_quality_without_changing_classification(
    harness: Any,
) -> None:
    grounded = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(
            next_step="再对 `grid` 做一次实验。",
            reply="因为 `grid` 的两行是同一个引用，所以我们再跑一次看输出。",
        ),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert grounded["classification"] == "passed"
    quality = grounded["explanation_quality"]
    assert set(quality["dimensions"]) == set(EXPLANATION_DIMENSIONS)
    assert quality["dimensions"]["no_solution_dump"] == "ok"
    assert quality["solution_dump_suspected"] is False

    # A failing turn still carries the reporting dimensions — attached to
    # every judged turn, never altering the verdict itself.
    failed = harness.classify_and_check_turn(
        CASE,
        1,
        {
            "reply": {"content": "我们看一下。"},
            "coach_turn": {"next_step": "给我 `parse_header()` 的函数名。", "requires_confirmation": True},
            "agent_meta": {
                "grounding_outcome": "downgraded",
                "grounding_ungrounded_symbols": ["parse_header"],
                "grounding_retry_used": False,
            },
            "snapshot": {"memory": {}},
        },
        None,
        code_text="grid = 1\n",
        message="为什么失败",
    )
    assert failed["classification"] == "failed"
    assert set(failed["explanation_quality"]["dimensions"]) == set(EXPLANATION_DIMENSIONS)


def test_harness_dump_suspected_flows_through_without_gating(harness: Any) -> None:
    """A guided-mode solution dump stays ``passed`` — reported, never gated."""
    dumped = harness.classify_and_check_turn(
        CASE,
        1,
        _payload(next_step="再对 `grid` 做一次实验。", reply=_dump_reply(14)),
        None,
        code_text="grid = 1\n",
        message="我们看边界",
    )
    assert dumped["classification"] == "passed"
    assert dumped["explanation_quality"]["solution_dump_suspected"] is True
    assert dumped["explanation_quality"]["dimensions"]["no_solution_dump"] == "weak"

    direct_case = {**CASE, "answer_mode": "direct"}
    direct = harness.classify_and_check_turn(
        direct_case,
        1,
        _payload(next_step="再对 `grid` 做一次实验。", reply=_dump_reply(14)),
        None,
        code_text="grid = 1\n",
        message="直接给改法",
    )
    assert direct["classification"] == "passed"
    assert direct["explanation_quality"]["solution_dump_suspected"] is False
    assert direct["explanation_quality"]["dimensions"]["no_solution_dump"] == "unclear"


def test_explanation_quality_summary_aggregates_counts_and_markdown(harness: Any) -> None:
    result = {
        "cases": [
            {
                "case": "a",
                "fixture": {"fixture_ok": True},
                "turns": [
                    {
                        "classification": "passed",
                        "explanation_quality": {
                            "dimensions": {
                                "addresses_learner": "ok",
                                "language_alignment": "ok",
                                "anchored_symbols": "ok",
                                "no_solution_dump": "ok",
                                "explains_reasoning": "weak",
                            },
                            "solution_dump_suspected": False,
                        },
                    },
                    {
                        "classification": "passed",
                        "explanation_quality": {
                            "dimensions": {
                                "addresses_learner": "weak",
                                "language_alignment": "unclear",
                                "anchored_symbols": "weak",
                                "no_solution_dump": "weak",
                                "explains_reasoning": "ok",
                            },
                            "solution_dump_suspected": True,
                        },
                    },
                ],
            },
            {
                "case": "b",
                "fixture": {"fixture_ok": True},
                "turns": [
                    # No explanation_quality record: skipped turns are not judged.
                    {"classification": "skipped_no_credentials"},
                ],
            },
        ]
    }

    summary = harness.explanation_quality_summary(result)
    assert summary["evaluated_turns"] == 2
    assert summary["solution_dump_suspected_turns"] == 1
    assert summary["dimensions"]["addresses_learner"] == {"ok": 1, "weak": 1, "unclear": 0}
    assert summary["dimensions"]["anchored_symbols"] == {"ok": 1, "weak": 1, "unclear": 0}
    assert summary["dimensions"]["no_solution_dump"] == {"ok": 1, "weak": 1, "unclear": 0}
    assert summary["dimensions"]["explains_reasoning"] == {"ok": 1, "weak": 1, "unclear": 0}
    assert summary["dimensions"]["language_alignment"] == {"ok": 1, "weak": 0, "unclear": 1}

    lines = harness.explanation_quality_markdown(summary)
    joined = "\n".join(lines)
    assert "解释质量汇总" in joined
    assert "solution_dump_suspected 回合：1/2" in joined
    assert "| addresses_learner | 1 | 1 | 0 |" in joined
    assert "非门控" in joined

    empty = harness.explanation_quality_summary({"cases": []})
    assert empty["evaluated_turns"] == 0
    assert empty["solution_dump_suspected_turns"] == 0


# ---------------------------------------------------------------------------
# Restored from test_prompt_lane_detection.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_infer_coaching_scenario_prefers_debug_loop_over_bug_substring() -> None:
    assert (
        infer_coaching_scenario(
            "Now teach me the smallest VS Code debug loop.",
            default="general",
        )
        == "debug_loop"
    )


def test_infer_coaching_scenario_recognizes_function_signature_navigation_language() -> None:
    assert (
        infer_coaching_scenario(
            "Now teach me how to inspect a function signature and jump to definition.",
            default="general",
        )
        == "function_guidance"
    )


def test_infer_coaching_scenario_recognizes_unfamiliar_function_before_editing() -> None:
    assert (
        infer_coaching_scenario(
            "This is an unfamiliar TypeScript function. Help me understand its contract before I edit it.",
            default="general",
        )
        == "function_guidance"
    )


def test_infer_coaching_scenario_recognizes_remote_workspace_chinese() -> None:
    assert (
        infer_coaching_scenario(
            "\u5148\u6559\u6211\u600e\u4e48\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\uff0c"
            "\u518d\u7ed9\u6211\u4e00\u4e2a\u5f88\u5c0f\u7684\u9a8c\u8bc1\u52a8\u4f5c\u3002",
            default="general",
        )
        == "remote_workspace"
    )


def test_infer_coaching_scenario_recognizes_vs_code_remote_workflows_phrase() -> None:
    assert (
        infer_coaching_scenario(
            "I want to learn VS Code remote workflows first, then verify my understanding with one tiny real step.",
            default="general",
        )
        == "remote_workspace"
    )


def test_infer_coaching_scenario_recognizes_review_in_chinese() -> None:
    assert infer_coaching_scenario("请帮我复盘这个报错", default="general") == "review"


def test_infer_coaching_scenario_recognizes_project_adaptation_in_chinese() -> None:
    assert infer_coaching_scenario("把这个现有项目改造一下", default="general") == "project_adaptation"
    assert infer_coaching_scenario("把一个现有项目改成我真正想要的样子", default="general") == "project_adaptation"


def test_infer_coaching_scenario_routes_direct_resource_doc_question_to_principle() -> None:
    assert (
        infer_coaching_scenario(
            "我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise，以及它绝不能变成什么。",
            default="general",
        )
        == "principle"
    )


def test_infer_coaching_scenario_recognizes_idea_implementation_in_chinese() -> None:
    assert (
        infer_coaching_scenario(
            "我有一个 AI idea，想把它落地成一个最小可验证的原型。",
            default="general",
        )
        == "idea_implementation"
    )


def test_infer_coaching_scenario_keeps_concrete_chinese_idea_out_of_plan() -> None:
    assert (
        infer_coaching_scenario(
            "\u6211\u6709\u4e00\u4e2a AI idea\uff0c\u60f3\u628a\u5b83\u843d\u5730\u6210\u4e00\u4e2a\u6700\u5c0f\u53ef\u9a8c\u8bc1\u7684\u539f\u578b\u3002"
            "\u5148\u522b\u5c55\u5f00\u6210\u603b\u8ba1\u5212\uff0c\u5148\u966a\u6211\u538b\u51fa\u7b2c\u4e00\u6761\u6700\u5c0f\u5207\u7247\u3002",
            default="general",
        )
        == "idea_implementation"
    )


def test_infer_coaching_scenario_keeps_chinese_writing_help_out_of_plan() -> None:
    assert (
        infer_coaching_scenario(
            "\u5e2e\u6211\u6da6\u8272\u4e00\u6bb5\u4e2d\u6587\u9879\u76ee\u8fdb\u5c55\u66f4\u65b0\u3002"
            "\u5148\u53ea\u6539\u8fd9\u4e00\u4e2a\u6bb5\u843d\uff0c\u4e0d\u8981\u628a\u5b83\u53d8\u6210\u5b8c\u6574\u5b66\u4e60\u8ba1\u5212\u3002",
            default="general",
        )
        == "general"
    )


def test_infer_learner_signal_recognizes_blocked_in_chinese() -> None:
    assert infer_learner_signal("我卡住了，搞不定") == "blocked"


def test_infer_learner_signal_recognizes_curious_in_chinese() -> None:
    assert infer_learner_signal("我想试试这个原理") == "curious"


# ---------------------------------------------------------------------------
# Restored from test_coach_orientation.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_provider_and_runtime_facts_beat_conversation_theater() -> None:
    ready_talk = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        conversation_count=3,
        plan_current_step="Ship the parser guard",
        language="en-US",
    )
    assert ready_talk["object_kind"] == "plan"
    assert ready_talk["primary_action"] == "open_plan"

    blocked = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=False,
        conversation_count=3,
        plan_current_step="Ship the parser guard",
        language="en-US",
    )
    assert blocked["object_kind"] == "provider"
    assert blocked["state"] == "needs_setup"
    assert blocked["primary_action"] == "open_settings"

    runtime = derive_coach_orientation(
        sidecar_status="error",
        has_provider_model=True,
        conversation_count=3,
        language="en-US",
    )
    assert runtime["object_kind"] == "workspace"
    assert runtime["state"] == "blocked"


def test_training_reliability_and_handoff_are_authoritative() -> None:
    waiting = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        training_reliability_phase="executing",
        selected_card_title="Parser boundary",
        plan_current_step="Ignore this plan step",
        language="en-US",
    )
    assert waiting["object_kind"] == "training"
    assert waiting["state"] == "waiting"
    assert waiting["primary_action"] == "wait"
    assert waiting["object_label"] == "Parser boundary"

    failed = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        training_reliability_phase="failed",
        selected_card_title="Parser boundary",
        language="en-US",
    )
    assert failed["state"] == "blocked"
    assert failed["primary_action"] == "retry"

    returning = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        training_learning_phase="return",
        training_handoff_status="ready_to_return",
        selected_card_title="Parser boundary",
        language="zh-CN",
    )
    assert returning["object_kind"] == "training"
    assert returning["primary_action"] == "open_training"


def test_transfer_state_overlays_ready_plan_not_provider_blockers() -> None:
    transfer = {
        "concept": "shared rhythm",
        "state": "transferable",
        "scene_count": 2,
        "workspace_ids": ["project-one", "project-two"],
        "scene_keys": ["default"],
        "why": "This skill has evidence in more than one scene.",
        "next": "Schedule a review, or apply it in a new challenge.",
    }
    ready = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        conversation_count=2,
        plan_current_step="Keep the parser guard",
        language="en-US",
        transfer_state=transfer,
    )
    assert ready["object_kind"] == "plan"
    assert ready["next_step"] == "Schedule a review, or apply it in a new challenge."

    blocked = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=False,
        conversation_count=2,
        plan_current_step="Keep the parser guard",
        language="en-US",
        transfer_state=transfer,
    )
    assert blocked["object_kind"] == "provider"
    assert blocked["next_step"] == "Save and test a provider first."


def test_incomplete_orientation_is_not_current_truth() -> None:
    assert normalize_coach_orientation({"object_kind": "conversation", "state": "ready"}) is None
    assert (
        normalize_coach_orientation(
            derive_coach_orientation(
                sidecar_status="ready",
                has_provider_model=True,
                conversation_count=0,
                language="en-US",
            )
        )
        is not None
    )


def test_plan_first_look_understand_does_not_make_generate_plan_the_only_next() -> None:
    from app.pedagogy.plan_orientation import derive_plan_orientation

    first_look_next = "Add a token expiry test"
    first_look_why = "auth.py already checks expired tokens."
    ready = derive_plan_orientation(
        has_formal_plan=False,
        first_look_recommended_next=first_look_next,
        first_look_why=first_look_why,
        language="en-US",
    )
    assert ready["primary_action"] != "generate_plan"
    assert ready["primary_action"] == "continue_without_plan"
    assert ready["next_step"] == first_look_next
    assert ready["why"] == first_look_why
    empty_recovered = derive_plan_orientation(
        has_formal_plan=False,
        recovered_runtime=True,
        current_step="",
        first_look_recommended_next=first_look_next,
        first_look_why=first_look_why,
        language="en-US",
    )
    assert empty_recovered["primary_action"] == "wait"
    assert empty_recovered["primary_action"] != "generate_plan"
    assert empty_recovered["next_step"] != first_look_next
    live = derive_plan_orientation(
        has_formal_plan=False,
        recovered_runtime=True,
        resume_state="in_progress",
        current_step=first_look_next,
        why_now=first_look_why,
        first_look_recommended_next="Invent a leftover first-look plan",
        language="en-US",
    )
    assert live["primary_action"] == "continue_step"
    assert live["primary_action"] != "generate_plan"
    assert live["primary_action"] != "continue_without_plan"
    empty = derive_plan_orientation(has_formal_plan=False, language="en-US")
    assert empty["primary_action"] == "generate_plan"


def test_ready_provider_uses_first_look_next_without_inventing_plan() -> None:
    first_look_next = "Add a token expiry test"
    first_look_why = "auth.py already checks expired tokens."
    ready = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        conversation_count=0,
        first_look_next=first_look_next,
        first_look_why=first_look_why,
        language="en-US",
    )
    assert ready["object_kind"] == "conversation"
    assert ready["primary_action"] == "compose"
    assert ready["next_step"] == first_look_next
    assert ready["why"] == first_look_why
    assert ready["object_kind"] != "provider"
    assert ready["primary_action"] != "open_plan"
    assert "Save and test a provider" not in ready["next_step"]

    blocked = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=False,
        conversation_count=0,
        first_look_next=first_look_next,
        first_look_why=first_look_why,
        language="en-US",
    )
    assert blocked["object_kind"] == "provider"
    assert blocked["primary_action"] == "open_settings"
    assert blocked["next_step"] == "Save and test a provider first."

    returning = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        training_learning_phase="return",
        training_handoff_status="ready_to_return",
        selected_card_title="Keep one auth check",
        first_look_next=first_look_next,
        language="en-US",
    )
    assert returning["object_kind"] == "training"
    assert returning["primary_action"] == "open_training"
    assert returning["next_step"] != first_look_next

    waiting = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        training_reliability_phase="executing",
        selected_card_title="Keep one auth check",
        first_look_next=first_look_next,
        language="en-US",
    )
    assert waiting["object_kind"] == "training"
    assert waiting["primary_action"] == "wait"
    assert waiting["next_step"] != first_look_next

    live_plan = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        plan_current_step="Ship the parser guard",
        first_look_next=first_look_next,
        language="en-US",
    )
    assert live_plan["object_kind"] == "plan"
    assert live_plan["primary_action"] == "open_plan"
    assert live_plan["next_step"] != first_look_next


def test_snapshot_first_look_leads_when_provider_ready() -> None:
    first_look_next = "Add a token expiry test"
    first_look_why = "auth.py already checks expired tokens."
    provider = ProviderConfig(
        name="ready-provider",
        baseUrl="http://example.test/v1",
        apiKeyRef="ready-ref",
        model="ready-model",
    )
    understanding = WorkspaceUnderstandingSnapshot(
        firstLookSummary=FirstLookSummary(
            recommended_next_step=first_look_next,
            why_this_guess=first_look_why,
        )
    )
    ready = build_coach_orientation_from_snapshot(
        WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            memory=MemorySnapshot(
                workspace={"workspace_id": "workspace-first-look"},
                workspace_understanding=understanding,
            ),
        ),
        response_language="en-US",
    )
    assert ready["object_kind"] == "conversation"
    assert ready["primary_action"] == "compose"
    assert ready["next_step"] == first_look_next
    assert ready["why"] == first_look_why

    missing_provider = build_coach_orientation_from_snapshot(
        WorkbenchSnapshot(
            sidecar_status="ready",
            provider=None,
            memory=MemorySnapshot(
                workspace={"workspace_id": "workspace-first-look"},
                workspace_understanding=understanding,
            ),
        ),
        response_language="en-US",
    )
    assert missing_provider["object_kind"] == "provider"
    assert missing_provider["primary_action"] == "open_settings"
    assert missing_provider["next_step"] == "Save and test a provider first."

    foreign = build_coach_orientation_from_snapshot(
        WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            memory=MemorySnapshot(
                workspace={
                    "workspace_id": "workspace-b",
                    "workspace_understanding": {
                        "workspace_id": "workspace-a",
                        "firstLookSummary": {
                            "recommendedNextStep": first_look_next,
                            "whyThisGuess": first_look_why,
                        },
                    },
                }
            ),
        ),
        response_language="en-US",
    )
    assert foreign["next_step"] != first_look_next
    assert foreign["object_kind"] == "conversation"
    assert foreign["primary_action"] == "compose"

    leftover_title = "Keep the current stage"
    leftover_plan = LearningPlan(
        id="plan-formal-old",
        title=leftover_title,
        summary="Leftover formal summary of the old stage path",
        current_stage_id="stage-1",
        current_step="Keep one auth check",
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
    leftover = build_coach_orientation_from_snapshot(
        WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            plan=leftover_plan,
            plan_runtime_status={
                "recovered": True,
                "current_step": "",
                "plan_id": "",
                "why_now": "",
            },
            memory=MemorySnapshot(
                workspace={
                    "workspace_id": "workspace-leftover-first-look",
                    PLAN_RUNTIME_KEY: {
                        "current_step": "",
                        "resume_state": "in_progress",
                        "workspace_id": "workspace-leftover-first-look",
                    },
                },
                workspace_understanding=WorkspaceUnderstandingSnapshot(
                    firstLookSummary=FirstLookSummary(
                        recommended_next_step=leftover_title,
                        why_this_guess="Leftover formal title must not become first-look next.",
                    )
                ),
            ),
        ),
        response_language="en-US",
    )
    assert leftover["next_step"] != leftover_title
    assert leftover["object_kind"] == "conversation"
    assert leftover["primary_action"] == "compose"
    assert leftover["primary_action"] != "open_plan"


def test_snapshot_and_restart_keep_persisted_orientation(tmp_path) -> None:
    snapshot = WorkbenchSnapshot(
        sidecar_status="ready",
        provider=ProviderConfig(
            name="minimax",
            baseUrl="http://example.test",
            apiKeyRef="secret-ref",
            model="MiniMax-M2.7",
        ),
        memory=MemorySnapshot(
            workspace={
                "latest_training_reliability": {
                    "phase": "acked",
                    "request_id": "req-1",
                },
                "latest_training_handoff": {
                    "learning_phase": "reflect",
                    "handoff_status": "needs_reflection",
                    "card_title": "Keep the loop on the card",
                },
                "selected_card_title": "Keep the loop on the card",
            }
        ),
    )
    orientation = build_coach_orientation_from_snapshot(snapshot, response_language="en-US")
    assert orientation["object_kind"] == "training"
    assert orientation["state"] == "ready"
    assert orientation["primary_action"] == "open_training"

    workspace_id = "workspace-coach-orientation"
    service = MemoryService(TrainerRepository(tmp_path / "coach-orientation.db"))
    service.update_workspace_state(workspace_id, latest_coach_orientation=orientation)
    restarted = MemoryService(TrainerRepository(tmp_path / "coach-orientation.db"))
    restored = restarted._structured_for(workspace_id)._workspace.get("latest_coach_orientation")
    assert normalize_coach_orientation(restored) == orientation


def test_snapshot_orientation_reads_persisted_transfer_state() -> None:
    snapshot = WorkbenchSnapshot(
        sidecar_status="ready",
        provider=ProviderConfig(
            name="minimax",
            baseUrl="http://example.test",
            apiKeyRef="secret-ref",
            model="MiniMax-M2.7",
        ),
        memory=MemorySnapshot(
            workspace={
                "latest_transfer_state": {
                    "concept": "shared rhythm",
                    "state": "transferable",
                    "scene_count": 2,
                    "workspace_ids": ["project-one", "project-two"],
                    "why": "This skill has evidence in more than one scene.",
                    "next": "Schedule a review, or apply it in a new challenge.",
                }
            }
        ),
        plan=None,
    )
    orientation = build_coach_orientation_from_snapshot(snapshot, response_language="en-US")
    assert orientation["object_kind"] == "conversation"
    assert orientation["next_step"] == "Schedule a review, or apply it in a new challenge."


def test_leftover_formal_card_title_does_not_live_in_orientation_object_label() -> None:
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
    provider = ProviderConfig(
        name="minimax",
        baseUrl="http://example.test",
        apiKeyRef="secret-ref",
        model="MiniMax-M2.7",
    )

    def _snapshot(workspace_id: str, runtime: dict[str, object]) -> WorkbenchSnapshot:
        return WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            plan=plan,
            plan_runtime_status={
                "recovered": True,
                "current_step": str(runtime.get("current_step") or ""),
                "plan_id": str(runtime.get("plan_id") or ""),
                "why_now": str(runtime.get("why_now") or ""),
            },
            memory=MemorySnapshot(
                workspace={
                    "workspace_id": workspace_id,
                    PLAN_RUNTIME_KEY: runtime,
                    "latest_training_reliability": {"phase": "executing"},
                    "selected_card_title": leftover_card,
                    "latest_training_handoff": {"card_title": leftover_card},
                }
            ),
        )

    orientation = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-leftover-card",
            {
                "current_step": recovered_step,
                "why_now": "Expired tokens still leak.",
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-leftover-card",
            },
        ),
        response_language="en-US",
    )
    empty = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-empty-step",
            {
                "current_step": "",
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-empty-step",
            },
        ),
        response_language="en-US",
    )
    for text in (orientation["object_label"], empty["object_label"]):
        assert leftover_title not in text
        assert leftover_card not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
    assert orientation["object_kind"] == "training"
    assert orientation["object_label"] == recovered_step
    assert empty["object_label"] == "Current training card"
    still = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-still-on-plan",
            {
                "current_step": leftover_step,
                "plan_id": leftover_plan_id,
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-still-on-plan",
            },
        ),
        response_language="en-US",
    )
    assert leftover_card in still["object_label"]


def test_leftover_formal_plan_step_does_not_live_in_orientation_object_label() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_why = "Keep the leftover why"
    recovered_step = "Add a token expiry test"
    recovered_why = "Expired tokens still leak."
    plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id="stage-1",
        current_step=leftover_step,
        why_now=leftover_why,
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
    provider = ProviderConfig(
        name="minimax",
        baseUrl="http://example.test",
        apiKeyRef="secret-ref",
        model="MiniMax-M2.7",
    )

    def _snapshot(workspace_id: str, runtime: dict[str, object]) -> WorkbenchSnapshot:
        return WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            plan=plan,
            plan_runtime_status={
                "recovered": True,
                "current_step": str(runtime.get("current_step") or ""),
                "plan_id": str(runtime.get("plan_id") or ""),
                "why_now": str(runtime.get("why_now") or ""),
            },
            memory=MemorySnapshot(
                workspace={
                    "workspace_id": workspace_id,
                    PLAN_RUNTIME_KEY: runtime,
                }
            ),
        )

    orientation = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-leftover-step",
            {
                "current_step": recovered_step,
                "why_now": recovered_why,
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-leftover-step",
            },
        ),
        response_language="en-US",
    )
    empty = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-empty-plan-step",
            {
                "current_step": "",
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-empty-plan-step",
            },
        ),
        response_language="en-US",
    )
    for text in (orientation["object_label"], orientation["why"], empty["object_label"], empty["why"]):
        assert leftover_title not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
        assert leftover_why not in text
    assert orientation["object_kind"] == "plan"
    assert orientation["object_label"] == recovered_step
    assert recovered_why in orientation["why"]
    assert leftover_step not in empty["object_label"]
    still = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-still-on-plan-step",
            {
                "current_step": leftover_step,
                "plan_id": leftover_plan_id,
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-still-on-plan-step",
            },
        ),
        response_language="en-US",
    )
    assert leftover_step in still["object_label"]


def test_leftover_formal_blocked_reason_does_not_live_in_orientation() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_blocked = "Keep the leftover blocker"
    recovered_step = "Add a token expiry test"
    recovered_blocked = "Expired tokens still leak the session."
    plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id="stage-1",
        current_step=leftover_step,
        blocked_reason=leftover_blocked,
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
    provider = ProviderConfig(
        name="minimax",
        baseUrl="http://example.test",
        apiKeyRef="secret-ref",
        model="MiniMax-M2.7",
    )

    def _snapshot(workspace_id: str, runtime: dict[str, object]) -> WorkbenchSnapshot:
        return WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            plan=plan,
            plan_runtime_status={
                "recovered": True,
                "current_step": str(runtime.get("current_step") or ""),
                "plan_id": str(runtime.get("plan_id") or ""),
                "blocked_reason": str(runtime.get("blocked_reason") or ""),
            },
            memory=MemorySnapshot(
                workspace={
                    "workspace_id": workspace_id,
                    PLAN_RUNTIME_KEY: runtime,
                }
            ),
        )

    orientation = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-leftover-blocker",
            {
                "current_step": recovered_step,
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-leftover-blocker",
            },
        ),
        response_language="en-US",
    )
    recovered = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-recovered-blocker",
            {
                "current_step": recovered_step,
                "blocked_reason": recovered_blocked,
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-recovered-blocker",
            },
        ),
        response_language="en-US",
    )
    empty = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-empty-blocker",
            {
                "current_step": "",
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-empty-blocker",
            },
        ),
        response_language="en-US",
    )
    for text in (
        orientation["why"],
        orientation["object_label"],
        recovered["why"],
        recovered["object_label"],
        empty["why"],
        empty["object_label"],
    ):
        assert leftover_title not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
        assert leftover_blocked not in text
    assert orientation["object_kind"] == "plan"
    assert orientation["state"] != "blocked"
    assert leftover_blocked not in orientation["why"]
    assert recovered["state"] == "blocked"
    assert recovered["why"] == recovered_blocked
    assert leftover_blocked not in empty["why"]
    still = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-still-on-plan-blocker",
            {
                "current_step": leftover_step,
                "plan_id": leftover_plan_id,
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-still-on-plan-blocker",
            },
        ),
        response_language="en-US",
    )
    assert leftover_blocked in still["why"]
    assert still["state"] == "blocked"


# ---------------------------------------------------------------------------
# Restored from test_builtin_teaching_skill.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_builtin_lecture_skill_is_seeded_active_and_reviewed(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    skill = registry._skills["rethinkfun-lecture"]
    assert skill.kind == "tutor"
    assert skill.active is True
    assert skill.reviewed is True
    assert skill.metadata["origin"] == "builtin"
    # The body carries the state-flow contract, not a definition dump.
    assert "状态流" in skill.body
    assert "缺口" in skill.body
    assert "公式晚出现" in skill.body
    assert "禁止" in skill.body and "代入即得" in skill.body
    assert len(skill.body) <= 1300  # stays within runtime injection budget


def test_builtin_seed_is_idempotent_and_never_overrides_user_records(tmp_path: Path) -> None:
    dir_path = tmp_path / "skills"
    first = SkillRegistry(dir_path)
    assert sum(1 for s in first.list_skills() if s.skill_id == "rethinkfun-lecture") == 1

    second = SkillRegistry(dir_path)
    assert sum(1 for s in second.list_skills() if s.skill_id == "rethinkfun-lecture") == 1

    # A user-created record with the same id must survive a reseed untouched.
    second._skills["rethinkfun-lecture"].body = "user override"
    second._persist()
    third = SkillRegistry(dir_path)
    assert third._skills["rethinkfun-lecture"].body == "user override"


def test_builtin_skill_selected_by_lecture_triggers(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")

    selected = select_active_skills(registry, "请彻底讲明白 Python 生成器的惰性求值")
    assert [s.skill_id for s in selected] == ["rethinkfun-lecture"]
    assert any(term in selected[0].matched_terms for term in ("讲明白", "彻底讲"))
    assert "状态流" in selected[0].body

    english = select_active_skills(registry, "give me a deep lecture on diffusion models")
    assert [s.skill_id for s in english] == ["rethinkfun-lecture"]

    # Ordinary bounded questions do not pull in the lecture contract.
    assert select_active_skills(registry, "what does this error mean?") == []


def test_builtin_guidance_block_keeps_tool_authority_neutral(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    selected = select_active_skills(registry, "好好讲讲状态管理")
    block = build_skill_guidance_block(selected)
    assert "### Skill: RethinkFun 讲解法" in block
    assert "缺口" in block
    assert "never expand your tool authority" in block


def test_coach_system_prompt_carries_deep_explanation_contract() -> None:
    from app.core.models import UserProfile
    from app.llm.prompts import build_coaching_system_prompt

    prompt = build_coaching_system_prompt(
        profile=UserProfile(long_term_goal="learn state flow", weekly_hours=4),
        current_file=None,
        response_language="zh-CN",
    )
    assert "state-flow lecture contract" in prompt
    assert "old approach's failure" in prompt
    assert "formulas appear late" in prompt
    assert "3-5 steps" in prompt
    assert "at least one contrast case" in prompt
    assert "minimal working example" in prompt
    assert "never pad with \"obviously\"" in prompt


def test_applied_is_evidence_driven_not_name_substring(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from app.skills.runtime import record_skill_usage

    registry = SkillRegistry(tmp_path / "skills")
    highlights: list[str] = []

    class FakeMemory:
        def add_session_highlight(self, session_id: str, highlight: str) -> None:
            highlights.append(highlight)

    runtime = SimpleNamespace(skill_registry=registry, memory_service=FakeMemory())
    selected = select_active_skills(registry, "彻底讲明白 Python 生成器")

    # A real state-flow lecture that never names the skill still counts as
    # applied: the contract markers are the evidence (v1.5 replacement for the
    # old display-name substring guess).
    lecture = (
        "先看旧方案的失败：readlines() 把整个文件装进内存。"
        "缺口出现了：文件大到装不下。为了补这个缺口，我们需要一个对象，"
        "它一次只产出一个值。状态因此推进了。"
    )
    usages = record_skill_usage(
        runtime,
        "ws-evi",
        "session-evi",
        selected,
        stop_reason="completed",
        final_content=lecture,
    )
    assert usages[0]["applied"] is True
    assert usages[0]["evidence"]["basis"] == "contract_markers"
    assert usages[0]["evidence"]["cited"] is False
    meta = registry._skills["rethinkfun-lecture"].metadata
    assert meta["last_applied"] is True
    assert meta["last_evidence"]["basis"] == "contract_markers"

    # A reply that drifts to an unrelated lane (no markers, no citation) is
    # only "provided", never "applied".
    drift = "先把工作区落点说清楚：告诉我当前工作区是 SSH 还是 local。"
    usages = record_skill_usage(
        runtime,
        "ws-evi",
        "session-evi",
        selected,
        stop_reason="completed",
        final_content=drift,
    )
    assert usages[0]["applied"] is False
    assert usages[0]["evidence"]["basis"] == "contract_markers"
    assert len(usages[0]["evidence"]["markers_hit"]) < 3


def test_action_skill_applied_requires_declared_tool_execution(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from app.skills.runtime import SelectedSkill, record_skill_usage

    registry = SkillRegistry(tmp_path / "skills")
    registry.register(
        skill_id="graph-builder",
        kind="action",
        name="Graph Builder",
        description="Build a call graph",
        reviewed=True,
        metadata={"front_matter": {"tools": "list_project_modules, read_project_symbol"}},
    )
    runtime = SimpleNamespace(skill_registry=registry)
    selected = [
        SelectedSkill(
            skill_id="graph-builder",
            name="Graph Builder",
            kind="action",
            permissions=["read:workspace"],
            body="build graph",
        )
    ]

    without_tool = record_skill_usage(
        runtime, "ws", "s", selected, final_content="done", tool_events=[]
    )
    assert without_tool[0]["applied"] is False
    assert without_tool[0]["evidence"]["basis"] == "tool_execution"

    with_tool = record_skill_usage(
        runtime,
        "ws",
        "s",
        selected,
        final_content="done",
        tool_events=[{"name": "list_project_modules"}],
    )
    assert with_tool[0]["applied"] is True
    assert with_tool[0]["evidence"]["tools_hit"] == ["list_project_modules"]


# ---------------------------------------------------------------------------
# Restored from test_image_attachment_validation.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def png_bytes() -> bytes:
    return base64.b64decode(build_vision_challenge().image_url.split(",", 1)[1])


@pytest.mark.parametrize("mime", ["image/png", "image/jpeg", "image/gif", "image/webp"])
def test_real_image_bytes_are_decoded_and_size_is_derived(mime: str) -> None:
    data = png_bytes()
    if mime == "image/jpeg":
        data = fitz.Pixmap(data).tobytes("jpeg")
    elif mime == "image/gif":
        data = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
    elif mime == "image/webp":
        data = base64.b64decode("UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoCAAIAAUAmJaQAA3AA/v02aAA=")
    attachment = MessageAttachment.model_validate({
        "mimeType": mime, "dataBase64": base64.b64encode(data).decode(),
    })
    assert attachment.byte_size == len(data)


def test_declared_type_and_size_cannot_override_actual_bytes() -> None:
    data = png_bytes()
    encoded = base64.b64encode(data).decode()
    with pytest.raises(ValueError, match="type_mismatch"):
        validate_image_payload(encoded, "image/jpeg", len(data))
    with pytest.raises(ValueError, match="size_mismatch"):
        validate_image_payload(encoded, "image/png", 1)


def test_oversized_base64_is_rejected_before_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_decode(*_args: object, **_kwargs: object) -> bytes:
        pytest.fail("oversized transport reached base64 decode")
    monkeypatch.setattr(base64, "b64decode", unexpected_decode)
    with pytest.raises(ValueError, match="size_exceeded"):
        validate_image_payload("A" * (MAX_IMAGE_BASE64_LENGTH + 1), "image/png", None)


def test_bomb_dimensions_are_rejected_before_pixel_allocation(monkeypatch: pytest.MonkeyPatch) -> None:
    data = bytearray(png_bytes())
    data[16:24] = struct.pack(">II", 8192, 8192)
    def unexpected_decode(*_args: object, **_kwargs: object) -> None:
        pytest.fail("oversized dimensions reached image decode")
    monkeypatch.setattr(Image, "open", unexpected_decode)
    with pytest.raises(ValueError, match="dimensions_exceeded"):
        validate_image_payload(base64.b64encode(data).decode(), "image/png", None)


@pytest.mark.parametrize("data", [b"hello", b"\x89PNG\r\n\x1a\n", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 1, 1)])
def test_a_filename_or_header_alone_is_not_an_image(data: bytes) -> None:
    with pytest.raises(ValueError):
        validate_image_payload(base64.b64encode(data).decode(), "image/png", None)


def test_invalid_base64_and_excess_attachment_count_fail_request_validation() -> None:
    with pytest.raises(ValidationError, match="base64_invalid"):
        MessageAttachment.model_validate({"dataBase64": "xx"})
    item = {"dataBase64": base64.b64encode(png_bytes()).decode()}
    with pytest.raises(ValidationError, match="at most 4 items"):
        SessionMessageRequest.model_validate({"message": "inspect", "attachments": [item] * 5})


# ---------------------------------------------------------------------------
# Restored from test_language_integrity_guards.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_detect_language_corruption_respects_response_language_even_for_english_message() -> None:
    service = ProviderService()

    detected = service.detect_language_corruption(
        message="Help me scope the first tiny slice.",
        reply="The provider only saw question marks: ?????",
        response_language="zh-CN",
    )

    assert detected is True


def test_detect_language_corruption_rejects_english_only_prose_for_zh_cn() -> None:
    service = ProviderService()

    detected = service.detect_language_corruption(
        message="\u8bf7\u89e3\u91ca VS Code remote workspace boundary\u3002",
        reply="First identify the host that owns the workspace, then verify one real path.",
        response_language="zh-CN",
    )

    assert detected is True


def test_finalize_coaching_reply_recovers_english_only_zh_cn_prose_in_chinese() -> None:
    service = ProviderService()
    profile = UserProfile(long_term_goal="\u5b66\u4e60 VS Code remote workflow")

    reply = service.finalize_coaching_reply(
        "First identify the host that owns the workspace, then verify one real path.",
        profile=profile,
        message="\u8bf7\u89e3\u91ca VS Code remote workspace boundary\u3002",
        response_language="zh-CN",
        coach_context={"scenario": "remote_workspace"},
    )

    assert any("\u3400" <= char <= "\u9fff" for char in reply)
    assert "First identify" not in reply
    failure = service.peek_last_reply_failure()
    assert failure is not None
    assert failure["error_category"] == "language_corruption"


def test_detect_language_corruption_flags_mixed_script_junk_in_english_reply() -> None:
    service = ProviderService()

    detected = service.detect_language_corruption(
        message="Help me learn VS Code remote workflows first.",
        reply=(
            "Glad you want to start with VS Code remote "
            "\u0431\u043a"
            " it's a great target because once the model clicks, debugging and run confi"
            "\u0431\u043d"
            " stay more stable."
        ),
        response_language="en-US",
    )

    assert detected is True


def test_detect_language_corruption_flags_latin1_style_mojibake_for_zh_reply() -> None:
    service = ProviderService()
    reply = "先沿着 VS Code 远程工作区 这条主线继续推进。".encode("utf-8").decode("latin-1")

    detected = service.detect_language_corruption(
        message="请继续",
        reply=reply,
        response_language="zh-CN",
    )

    assert detected is True


def test_provider_service_marks_recent_zh_integrity_success_after_clean_visible_reply() -> None:
    service = ProviderService()
    profile = UserProfile(
        long_term_goal="Keep Chinese coaching reliable",
        weekly_hours=4,
        teaching_style="guided",
        answer_policy="guided",
    )

    reply = service.finalize_coaching_reply(
        "好，我们继续沿着当前 debug 这条线往下走，先只盯住一个 breakpoint 和一个 value。",
        profile=profile,
        message="继续",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={"scenario": "debug_loop"},
    )

    assert "当前 debug" in reply
    assert service.has_recent_language_integrity_success(
        message="继续",
        response_language="zh-CN",
    )


# ---------------------------------------------------------------------------
# Restored from test_coach_language_alignment.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_localize_known_context_phrases_zh() -> None:
    assert localize_known_context_phrases("VS Code debug loop", "zh-CN") == "VS Code 调试闭环"
    assert localize_known_context_phrases("debug loop", "zh-CN") == "调试闭环"
    assert localize_known_context_phrases("plain english", "en-US") == "plain english"
    lane = localize_known_context_phrases(
        "Continue 'VS Code debug loop' and do not open a new lane before this next move lands: run pytest",
        "zh-CN",
    )
    assert "调试闭环" in lane and "run pytest" in lane


def test_context_text_language_guards() -> None:
    # Chinese learner with mojibake → dropped.
    assert language_aligned_context_text("涓嬩竴姝", "zh-CN") == ""
    # English learner with CJK → keep only latin fragments.
    aligned = language_aligned_context_text("先看门户 then run the test", "en-US")
    assert "then run the test" in aligned
    assert "先看" not in aligned
    # Non-string values → empty.
    assert language_aligned_context_text(None, "en-US") == ""


def test_context_list_dedupes_and_limits() -> None:
    assert language_aligned_context_list(["a", "a", "b"], "en-US") == ["a", "b"]
    assert language_aligned_context_list(["a", "b", "c"], "en-US", limit=2) == ["a", "b"]
    assert language_aligned_context_list("not-a-list", "en-US") == []


def test_flat_payload_aligns_strings_and_lists_only() -> None:
    aligned = language_aligned_flat_payload(
        {
            "summary": "VS Code debug loop",
            "steps": ["debug loop", "remote workspace boundary", "x"],
            "nested": [{"summary": "untouched"}],
        },
        "zh-CN",
        list_limit=2,
    )
    assert aligned is not None
    assert aligned["summary"] == "VS Code 调试闭环"
    assert aligned["steps"] == ["调试闭环", "远程工作区边界"]
    assert aligned["nested"] == [{"summary": "untouched"}]


def test_coaching_state_payload_and_review_rhythm() -> None:
    state = language_aligned_coaching_state_payload(
        {"summary": "debug loop", "next_step": "plain step"},
        "zh-CN",
    )
    assert state is not None
    assert state["summary"] == "调试闭环"
    assert state["next_step"] == "plain step"
    assert language_aligned_review_rhythm("", "zh-CN") is None
    assert language_aligned_review_rhythm("debug loop", "zh-CN") == "调试闭环"


# ---------------------------------------------------------------------------
# Restored from test_harness_retrieval.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_retrieval_plan_budgets_are_layered() -> None:
    assert _retrieval_plan("broad", 5)["excerpt_budget"] == 180
    assert _retrieval_plan("narrow", 5)["excerpt_budget"] == 300
    assert _retrieval_plan("verify", 4)["excerpt_budget"] == 420
    assert _retrieval_plan("narrow", 5)["read_more"].startswith("read_resource_excerpt")


def test_trim_hit_text_respects_budget_and_marks_truncation() -> None:
    hit = {
        "resource_id": "r1",
        "summary": "x" * 500,
        "excerpt": "short",
        "version_id": "v1",
        "content_hash": "h1",
    }
    trimmed = _trim_hit_text(hit, 180)
    assert len(trimmed["summary"]) <= 181
    assert trimmed["summary"].endswith("…")
    assert trimmed["truncated"] is True
    # Citations and identifiers are never touched.
    assert trimmed["version_id"] == "v1"
    assert trimmed["content_hash"] == "h1"
    assert trimmed["excerpt"] == "short"


class _StubSearchService:
    def __init__(self, hits: list[dict]) -> None:
        self._hits = hits
        self.calls: list[dict] = []

    def search(self, **kwargs):  # noqa: ANN003 - mirrors ResourceService.search
        self.calls.append(kwargs)
        return {
            "query": kwargs["query"],
            "total": len(self._hits),
            "ranking_strategy": "lexical_first",
            "filters": {},
            "hits": self._hits,
        }

    def search_cache_stats(self) -> dict:
        return {"hits": 1, "misses": 2, "hit_rate": 0.333, "ttl_seconds": 120}


def _context(service: object) -> ToolContext:
    return ToolContext(runtime=SimpleNamespace(resource_service=service), workspace_id="ws")


def test_search_tool_applies_budget_and_reports_cache() -> None:
    long_hits = [
        {
            "resource_id": f"r{index}",
            "summary": "y" * 900,
            "trust_score": 0.9,
            "index_state": "indexed",
        }
        for index in range(3)
    ]
    service = _StubSearchService(long_hits)
    result = asyncio.run(_handle_search_resources(_context(service), {"query": "state flow", "limit": 3}))
    assert result["ok"] is True
    assert result["retrieval_plan"]["excerpt_budget"] == 300
    for hit in result["hits"]:
        assert len(hit["summary"]) <= 301
        assert hit["truncated"] is True
    assert result["cache"]["ttl_seconds"] == 120
    assert result["cache"]["hits"] == 1


def test_verify_mode_keeps_only_verification_ready_hits() -> None:
    hits = [
        {"resource_id": "good", "summary": "ok", "trust_score": 0.9, "index_state": "indexed", "freshness": "fresh"},
        {"resource_id": "weak", "summary": "weak", "trust_score": 0.1, "index_state": "indexed"},
    ]
    service = _StubSearchService(hits)
    result = asyncio.run(
        _handle_search_resources(_context(service), {"query": "evidence", "mode": "verify", "limit": 4})
    )
    assert [hit["resource_id"] for hit in result["hits"]] == ["good"]
    assert result["retrieval_plan"]["excerpt_budget"] == 420


def test_resource_service_exposes_cache_evidence(tmp_path: Path) -> None:
    from app.ingest.service import IngestService
    from app.memory.semantic import SemanticMemory

    repository = TrainerRepository(tmp_path / "harness.db")
    service = ResourceService(
        repository=repository,
        ingest_service=IngestService(),
        semantic_memory=SemanticMemory(tmp_path / "semantic"),
        data_root=tmp_path,
    )
    stats = service.search_cache_stats()
    assert stats["hits"] == 0 and stats["misses"] == 0
    assert stats["ttl_seconds"] == 120


# ---------------------------------------------------------------------------
# Restored from test_stage1_rethinkfun_truth_and_proxy.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_ignore_system_proxy_bypasses_trust_env_and_surfaces_proxy_hint(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://secret-user:secret-pass@127.0.0.1:29290")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)

    proxied_config = ProviderConfig.model_validate(
        {
            "name": "remote-relay",
            "baseUrl": "https://relay.example.com/v1",
            "apiKeyRef": "trainer.remote",
            "model": "MiniMax-M2.7",
            "ignoreSystemProxy": False,
        }
    )
    direct_config = ProviderConfig.model_validate(
        {
            "name": "remote-relay",
            "baseUrl": "https://relay.example.com/v1",
            "apiKeyRef": "trainer.remote",
            "model": "MiniMax-M2.7",
            "ignoreSystemProxy": True,
        }
    )

    svc_proxied = ProviderService(proxied_config, api_key="sk-test")
    svc_direct = ProviderService(direct_config, api_key="sk-test")

    assert svc_proxied._should_bypass_system_proxy() is False
    assert svc_direct._should_bypass_system_proxy() is True

    binding_direct = ProviderAgentBinding(
        provider_service=svc_direct,
        protocol="openai_chat_completions_compatible",
    )
    assert binding_direct._should_bypass_system_proxy() is True

    detail_zh = svc_proxied._detail_from_category(
        "network",
        provider=proxied_config,
        error=RuntimeError("502 Bad Gateway"),
        response_language="zh-CN",
    )
    assert "HTTP_PROXY" in detail_zh
    assert "忽略系统代理" in detail_zh
    assert "secret-pass" not in detail_zh
    assert "29290" not in detail_zh

    detail_direct = svc_direct._detail_from_category(
        "network",
        provider=direct_config,
        error=RuntimeError("connection refused"),
        response_language="zh-CN",
    )
    assert "忽略系统代理" not in detail_direct


def test_english_system_prompt_contains_no_cjk_characters() -> None:
    import re

    profile = UserProfile(long_term_goal="Understand attention scaling")
    for context in ({"context_tier": "minimal"}, {}):
        prompt = build_coaching_system_prompt(
            profile,
            message="Explain why scaled dot-product attention divides by sqrt(d_k).",
            response_language="en-US",
            coach_context=context,
            agent_loop_enabled=True,
        )
        assert not re.search(r"[\u3400-\u9fff]", prompt)


def test_rethinkfun_deep_lecture_grants_generous_output_token_budget() -> None:
    standard_cfg = ProviderConfig.model_validate(
        {
            "name": "std",
            "baseUrl": "https://api.example.com/v1",
            "apiKeyRef": "trainer.std",
            "model": "gpt-4.1-mini",
        }
    )
    minimax_cfg = ProviderConfig.model_validate(
        {
            "name": "mm",
            "baseUrl": "https://api.example.com/v1",
            "apiKeyRef": "trainer.mm",
            "model": "MiniMax-M2.7",
        }
    )
    std_svc = ProviderService(standard_cfg, api_key="sk-test")
    mm_svc = ProviderService(minimax_cfg, api_key="sk-test")

    # Fast Q&A stays on the compact default budget (None -> 1024).
    assert std_svc._coaching_requested_output_tokens("with 退出时会释放锁吗？") is None
    assert mm_svc._coaching_requested_output_tokens("with 退出时会释放锁吗？") is None

    # Deep RethinkFun lecture grants headroom so reasoning + derivation + code never truncates.
    lecture_prompt = "请用状态流方式彻底讲明白 Scaled Dot-Product Attention 的公式推导与代码实现"
    assert std_svc._coaching_requested_output_tokens(lecture_prompt) == 4096
    assert mm_svc._coaching_requested_output_tokens(lecture_prompt) == 8192
    assert mm_svc._coaching_requested_output_tokens("帮我核查掌握进度的具体证据", agent_loop_enabled=True) == 4096


def test_single_composer_truth_and_note_triggers_cover_all_eight_languages() -> None:
    from app.api.router_support import _message_requests_single_composer_truth_or_note
    from app.memory.note_request import message_requests_lecture_note_save

    truth_queries = [
        "给我看我的完整学习路线和掌握进度依据",
        "Show me all stages and mastery evidence",
        "Muéstrame las etapas completadas y la evidencia de dominio",
        "Montre-moi les étapes terminées et la preuve de maîtrise",
        "Zeige mir abgeschlossene Phasen und den Beherrschungsnachweis",
        "完了した段階と習得の根拠を教えてください",
        "완료한 단계와 숙달 근거를 보여줘",
        "Mostre as etapas concluídas e a evidência de domínio",
    ]
    for query in truth_queries:
        assert _message_requests_single_composer_truth_or_note(query) is True, query

    note_requests = [
        "把刚才的讲稿存进资料库",
        "Save this explanation as a lecture note to my library",
        "Guardar esta explicación como nota en recursos",
        "Enregistrer cette fiche dans les ressources",
        "Bitte als Notiz in Ressourcen speichern",
        "この解説をノートとして資料に保存して",
        "이 설명을 노트로 자료실에 저장해 줘",
        "Salvar esta explicação como nota em recursos",
    ]
    for req in note_requests:
        assert message_requests_lecture_note_save(req) is True, req
        assert _message_requests_single_composer_truth_or_note(req) is True, req

    for rejected in (
        "不要存进资料库",
        "Do not save this note to resources",
        "No guardes esta nota",
        "Bitte nicht speichern als Notiz",
        "ノートは保存しないで",
        "노트로 저장하지 마",
    ):
        assert message_requests_lecture_note_save(rejected) is False, rejected

    assert _message_requests_single_composer_truth_or_note("with 退出时会释放锁吗？") is False


def test_streamable_prefix_does_not_stall_on_fenced_code_blocks() -> None:
    from app.llm.coaching_replies import _streamable_visible_prefix

    chunks = [
        "<think>内部推演",
        "步骤</think>\n先看旧做法为什么卡住。\n",
        "```python\ndef check():\n",
        "    return 1\n```\n",
        "接着检验边界。",
    ]
    buf = ""
    emitted = ""
    deltas: list[str] = []
    for part in chunks:
        buf += part
        prefix = _streamable_visible_prefix(buf)
        if prefix and prefix.startswith(emitted):
            delta = prefix[len(emitted) :]
            if delta:
                emitted = prefix
                deltas.append(delta)
    assert len(deltas) >= 3
    assert "```python" in emitted
    assert "def check():" in emitted
    assert "内部推演" not in emitted


# ---------------------------------------------------------------------------
# Restored from test_teaching_quality.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


HASH = "a" * 64


CITATION = {
    "resource_id": "resource-1",
    "resource_version_id": "version-1",
    "resource_content_hash": HASH,
    "resource_location": {"page": 2, "anchor_id": "¶p2.1@120"},
}


def _seed(
    store: AttemptStore,
    workspace_id: str,
    *,
    card_id: str,
    result: str,
    assistance_level: str = "independent",
    transfer: bool = False,
    citation: bool = False,
) -> str:
    attempt = store.start_attempt(
        workspace_id=workspace_id,
        card_id=card_id,
        file_path="main.py",
        file_hash=HASH,
        assistance_level=assistance_level,
    )
    kwargs = dict(CITATION) if citation else {}
    store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash=attempt.get("file_hash") or HASH,
        result=result,
        trust_level="self_reported",
        transfer_metadata={"source_workspace": "project-a", "target": "project-b"}
        if transfer
        else None,
        **kwargs,
    )
    return attempt["attempt_id"]


def test_empty_workspace_reports_insufficient_never_zero(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "q.db")
    report = evaluate_teaching_quality(store, "ws-empty")
    payload = report.as_payload()
    assert payload["overall"] is None
    assert payload["measured_dimensions"] == 0
    for dimension in payload["dimensions"]:
        assert dimension["score"] is None
        assert dimension["status"] == "insufficient_evidence"


def test_five_dimensions_measured_from_real_evidence(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "q.db")
    workspace = "ws-quality"
    # 4 independent passes with full citations.
    for index in range(4):
        _seed(store, workspace, card_id=f"card-i{index}", result="passed", citation=True)
    # 2 assisted outcomes: one passed, one failed (hint effectiveness 0.5).
    _seed(store, workspace, card_id="card-a1", result="passed", assistance_level="guided", citation=True)
    _seed(store, workspace, card_id="card-a2", result="failed", assistance_level="guided")
    # 3 transfer-marked outcomes: 2 passed, 1 failed (transfer 2/3).
    _seed(store, workspace, card_id="card-t1", result="passed", transfer=True, citation=True)
    _seed(store, workspace, card_id="card-t2", result="passed", transfer=True, citation=True)
    _seed(store, workspace, card_id="card-t3", result="failed", transfer=True)

    report = evaluate_teaching_quality(store, workspace)
    dims = {dimension["key"]: dimension for dimension in report.as_payload()["dimensions"]}

    # 9 attempts; independent = 4+3 transfer(independent default)=7 → 7/9
    assert dims["independent_solving"]["sample_size"] == 9
    assert dims["independent_solving"]["score"] == round(7 / 9, 3)

    # Assisted: 2 samples; one passed → 0.5 (>= MIN_SAMPLE? 2 < 3 → insufficient)
    assert MIN_SAMPLE == 3
    assert dims["hint_effectiveness"]["status"] == "insufficient_evidence"

    # Transfer: 3 samples; 2 passed → 0.667
    assert dims["transfer"]["score"] == round(2 / 3, 3)

    # Citations: passed+cited evidence = 7 cited passed? cited evidence count:
    # 4 independent + 1 assisted + 2 transfer = 7 cited, all passed → 1.0
    assert dims["citation_completeness"]["score"] == 1.0

    # Difficulty: pass rate = passed(7)/current(9) ≈ 0.778 → adapted, high score
    assert dims["difficulty_fit"]["evidence"]["read"] == "adapted"
    assert dims["difficulty_fit"]["score"] == 1.0

    payload = report.as_payload()
    assert payload["measured_dimensions"] >= 4
    assert payload["overall"] is not None
    assert any("human" in line for line in payload["limitations"])


def test_hint_effectiveness_measured_once_sample_is_enough(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "q.db")
    workspace = "ws-hints"
    for index in range(3):
        _seed(store, workspace, card_id=f"card-a{index}", result="passed", assistance_level="guided")
    for index in range(3):
        _seed(store, workspace, card_id=f"card-i{index}", result="passed")
    dims = {
        dimension["key"]: dimension
        for dimension in evaluate_teaching_quality(store, workspace).as_payload()["dimensions"]
    }
    assert dims["hint_effectiveness"]["score"] == 1.0
    assert dims["hint_effectiveness"]["evidence"]["assisted_evidence"] == 3


class _StubEvidenceStore:
    def __init__(self, evidence: list[dict]) -> None:
        self._evidence = evidence

    def list_attempts(self, *, workspace_id: str) -> list[dict]:
        return [{"attempt_id": f"a{index}"} for index in range(len(self._evidence))]

    def list_evidence(self, attempt_id: str) -> list[dict]:
        return [self._evidence[int(attempt_id[1:])]]


def test_missing_assistance_is_unknown_not_independent() -> None:
    evidence = [
        {"evidence_id": "e-independent", "result": "passed", "is_current": True, "assistance_level": "independent"},
        {"evidence_id": "e-guided-pass", "result": "passed", "is_current": True, "assistance_level": "guided"},
        {"evidence_id": "e-guided-fail", "result": "failed", "is_current": True, "assistance_level": "guided"},
        # Legacy/partial record: the field is absent. It must not be counted
        # as an independent success or as a guided hint outcome.
        {"evidence_id": "e-unknown", "result": "passed", "is_current": True},
    ]
    dims = {
        dimension["key"]: dimension
        for dimension in evaluate_teaching_quality(_StubEvidenceStore(evidence), "ws-unknown-assistance").as_payload()[
            "dimensions"
        ]
    }

    independent = dims["independent_solving"]
    assert independent["sample_size"] == 3
    assert independent["score"] == round(1 / 3, 3)
    assert independent["evidence"]["independent_evidence"] == 1
    assert independent["evidence"]["known_assistance_evidence"] == 3
    assert independent["evidence"]["unknown_assistance_evidence"] == 1
    assert independent["evidence"]["current_evidence"] == 4

    hints = dims["hint_effectiveness"]
    assert hints["evidence"]["assisted_evidence"] == 2
    assert hints["evidence"]["unknown_assistance_evidence"] == 1
    assert hints["score"] is None  # 2 known assisted samples < MIN_SAMPLE


# ---------------------------------------------------------------------------
# Restored from test_rethinkfun_teaching_prompt.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_lecture_request_gets_state_flow_and_claim_chain() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(),
        message="讲明白 KL 散度为什么需要，并推导它的形式。",
    )

    assert "State-Driven Teaching (RethinkFun)" in prompt
    assert "known, unknown, goal, obstacle" in prompt
    assert "Introduce a new object only because" in prompt
    assert "formulas arrive late" in prompt
    assert "This turn is a lecture/derivation request" in prompt
    assert "chain of claims" in prompt
    assert "predict each formula" in prompt
    assert "If the topic has no formula or no code, omit that part" in prompt


def test_short_factual_question_stays_direct() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(),
        message="with 退出时会释放锁吗？",
    )

    assert "State-Driven Teaching (RethinkFun)" in prompt
    assert "For a short factual question, answer it directly and stop." in prompt
    assert "This turn is a lecture/derivation request" not in prompt


# ---------------------------------------------------------------------------
# Restored from test_attached_material_prompt.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_requested_resource_and_current_file_are_repeated_in_user_turn() -> None:
    messages = build_coaching_messages(
        UserProfile(long_term_goal="learn queues"),
        "只根据资料回答：这个项目使用什么队列？",
        {"path": "/tmp/project/queue.py", "language_id": "python", "content": 'ALPHA_QUEUE = "AlphaQueue"\n'},
        coach_context={
            "requested_resources": [
                {"id": "res-1", "title": "project-a.md", "summary": "AlphaQueue protects shared items."}
            ],
            "requested_resource_summary": "project-a.md: AlphaQueue protects shared items.",
        },
    )
    user = messages[-1]
    assert user["role"] == "user"
    assert "## Attached material for this request" in user["content"]
    assert "AlphaQueue protects shared items." in user["content"]
    assert 'ALPHA_QUEUE = "AlphaQueue"' in user["content"]
    assert "只根据资料回答" in user["content"]


def test_plain_turn_does_not_add_attachment_block() -> None:
    messages = build_coaching_messages(
        UserProfile(long_term_goal="learn queues"),
        "PPO 是什么？",
    )
    assert messages[-1]["content"] == "PPO 是什么？"


# ---------------------------------------------------------------------------
# Restored from test_language_short_answer.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_short_english_technical_answer_is_not_language_corruption() -> None:
    detail = _mixed_script_reply_corruption_detail(
        "False. The lock is already held.",
        message="threading.Lock.acquire(blocking=False) 在锁已被占用时返回什么？",
        response_language="zh-CN",
    )
    assert detail is None


def test_prose_length_english_is_still_language_corruption() -> None:
    detail = _mixed_script_reply_corruption_detail(
        "First identify the host that owns the workspace, then verify one real path.",
        message="请解释 VS Code remote workspace boundary。",
        response_language="zh-CN",
    )
    assert detail is not None
    assert "English-only visible prose" in detail


# ---------------------------------------------------------------------------
# Restored from test_mixed_script_noise_sanitization.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_strip_short_cyrillic_noise_removes_isolated_token_between_english_words() -> None:
    reply = "Good бк staying tiny and grounded."

    sanitized = _strip_short_cyrillic_noise(
        reply,
        message="Help me keep the first training slice very small.",
    )

    assert sanitized == "Good staying tiny and grounded."


def test_strip_short_cyrillic_noise_removes_short_suffix_inside_english_token() -> None:
    reply = "Once the model clicks, debugging and run confiбн stay more stable."

    sanitized = _strip_short_cyrillic_noise(
        reply,
        message="Help me learn VS Code remote workflows first.",
    )

    assert "бн" not in sanitized
    assert "confi" in sanitized


# ---------------------------------------------------------------------------
# Restored from test_smart_budget_and_rich_tools.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_smart_token_budget_defaults_and_clamping() -> None:
    assert DEFAULT_CONTEXT_WINDOW_TOKENS == 1_000_000
    assert resolve_smart_history_budget(1_000_000) > (12, 1_800)
    assert resolve_smart_history_budget(128_000)[1] >= 8_000

    anthropic_payload = {
        "max_tokens": 8192,
        "thinking": {"type": "enabled", "budget_tokens": 32768},
    }
    clamped_anthropic = clamp_wire_thinking_budget(anthropic_payload)
    assert clamped_anthropic["thinking"]["budget_tokens"] < clamped_anthropic["max_tokens"]

    gemini_payload = {
        "generationConfig": {
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 16384},
        }
    }
    clamped_gemini = clamp_wire_thinking_budget(gemini_payload)
    assert (
        clamped_gemini["generationConfig"]["thinkingConfig"]["thinkingBudget"]
        < clamped_gemini["generationConfig"]["maxOutputTokens"]
    )


def test_svg_sanitizer_strips_script_and_foreign_object() -> None:
    unsafe = (
        '<svg viewBox="0 0 200 100" onload="alert(1)">'
        '<script>alert(1)</script>'
        '<foreignObject><div>bad</div></foreignObject>'
        '<a href="javascript:alert(1)"><rect x="10" y="10" width="80" height="40" /></a>'
        '</svg>'
    )
    sanitized = sanitize_generated_svg(unsafe)
    assert "<script" not in sanitized.lower()
    assert "<foreignobject" not in sanitized.lower()
    assert "onload=" not in sanitized.lower()
    assert "javascript:" not in sanitized.lower()
    assert "<rect" in sanitized


# ---------------------------------------------------------------------------
# Restored from test_explicit_explanation_priority.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_explicit_zh_explanation_uses_a_direct_answer_even_with_guided_defaults(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-explicit-explanation-priority"
    user_message = (
        "\u8bf7\u7528\u4e24\u53e5\u4e2d\u6587\u89e3\u91ca Python "
        "\u5217\u8868\u63a8\u5bfc\u5f0f\uff0c\u5e76\u7ed9\u4e00\u4e2a\u5e73\u65b9\u793a\u4f8b"
    )
    provider_reply = (
        "\u5217\u8868\u63a8\u5bfc\u5f0f\u4f1a\u7528\u4e00\u4e2a\u8868\u8fbe\u5f0f\u4e3a\u6bcf\u4e2a\u5143\u7d20"
        "\u751f\u6210\u65b0\u5217\u8868\u3002\u4f8b\u5982 `squares = [x * x for x in range(5)]` "
        "\u4f1a\u5f97\u5230 `[0, 1, 4, 9, 16]`\u3002"
    )

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "test",
            autospec=True,
            return_value=ProviderTestResponse(
                ok=False,
                detail="A stale language probe incorrectly reported corruption.",
                error_category="language_corruption",
            ),
        ) as language_probe,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value=provider_reply),
        ) as coaching_reply,
    ):
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Explicit explanation",
                "profile": {
                    "long_term_goal": "Learn Python basics",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert started.status_code == 200, started.text

        response = client.post(
            "/session/message",
            json={
                "session_id": started.json()["session_id"],
                "workspace_id": workspace_id,
                "message": user_message,
                "response_language": "zh-CN",
                "answer_mode": "guided",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert language_probe.call_count == 1
    assert coaching_reply.await_args is not None
    assert coaching_reply.await_args.kwargs["answer_mode"] == "direct"
    assert payload["reply"]["content"] == provider_reply
    assert "\u5217\u8868\u63a8\u5bfc\u5f0f" in payload["reply"]["content"]
    assert "squares = [x * x for x in range(5)]" in payload["reply"]["content"]
    assert "\u5148\u522b\u76f4\u63a5\u7ed9\u7b54\u6848" not in payload["reply"]["content"]


# ---------------------------------------------------------------------------
# Restored from test_proactive_budget.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_proactive_whisper_enforces_daily_budget_spacing_dedup_and_typing_guard() -> None:
    base = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    weaknesses = ["idempotency: forgot conflict handling on replay"]

    typing_blocked = evaluate_proactive_opportunity(
        {},
        now=base,
        diagnostics=["KeyError: idempotency key not handled in replay handler"],
        weaknesses=weaknesses,
        response_language="zh-CN",
        learner_actively_typing=True,
    )
    assert typing_blocked.should_nudge is False
    assert typing_blocked.reason == "learner_typing"

    review_typing_blocked = derive_review_budget(
        {},
        due_count=2,
        now=base,
        learner_actively_typing=True,
    )
    assert review_typing_blocked.allowed is False
    assert review_typing_blocked.reason == "learner_typing"

    # Info-level diagnostics stay quiet even when idle.
    info_only = evaluate_proactive_opportunity(
        {},
        now=base,
        diagnostics=[{"severity": "info", "message": "idempotency docstring note"}],
        weaknesses=weaknesses,
        response_language="en",
    )
    assert info_only.should_nudge is False
    assert info_only.reason == "no_nudge_candidate"

    first = evaluate_proactive_opportunity(
        {},
        now=base,
        diagnostics=["TypeError: idempotency conflict check returns wrong status"],
        weaknesses=weaknesses,
        due_reviews=[{"concept": "retry-backoff"}],
        due_count=1,
        response_language="zh-CN",
    )
    assert first.should_nudge is True
    assert first.kind == "diagnostic_weakness"
    assert first.remaining_daily_budget == DAILY_PROACTIVE_BUDGET - 1

    budget_state = record_proactive_nudge(
        None,
        now=base,
        kind=first.kind,
        dedup_key=first.dedup_key,
        session_id="sess-1",
    )

    # Inside the 45-minute spacing window, another nudge is blocked.
    too_soon = evaluate_proactive_opportunity(
        {"proactive_budget": budget_state},
        now=base + timedelta(minutes=MIN_NUDGE_SPACING_MINUTES - 5),
        diagnostics=["TypeError: idempotency conflict check returns wrong status"],
        weaknesses=weaknesses,
        due_reviews=[{"concept": "retry-backoff"}],
        due_count=1,
        response_language="zh-CN",
    )
    assert too_soon.should_nudge is False
    assert too_soon.reason == "nudge_spacing_cooldown"

    # After cooldown, the same diagnostic weakness is deduplicated for today, while a
    # distinct review item uses the second (and final) daily slot.
    t2 = base + timedelta(minutes=MIN_NUDGE_SPACING_MINUTES + 1)
    same_diag_only = evaluate_proactive_opportunity(
        {"proactive_budget": budget_state},
        now=t2,
        diagnostics=["TypeError: idempotency conflict check returns wrong status"],
        weaknesses=weaknesses,
        due_reviews=[],
        due_count=0,
        response_language="zh-CN",
    )
    assert same_diag_only.should_nudge is False
    assert same_diag_only.reason == "already_nudged_today"

    second = evaluate_proactive_opportunity(
        {"proactive_budget": budget_state},
        now=t2,
        diagnostics=["TypeError: idempotency conflict check returns wrong status"],
        weaknesses=weaknesses,
        due_reviews=[{"concept": "retry-backoff"}],
        due_count=1,
        response_language="zh-CN",
    )
    assert second.should_nudge is True
    assert second.kind == "review_gap"
    assert second.remaining_daily_budget == 0

    budget_state = record_proactive_nudge(
        budget_state,
        now=t2,
        kind=second.kind,
        dedup_key=second.dedup_key,
        session_id="sess-1",
    )

    # Third nudge on the same day is strictly blocked by the daily cap.
    third = evaluate_proactive_opportunity(
        {"proactive_budget": budget_state},
        now=t2 + timedelta(hours=3),
        diagnostics=["KeyError: another idempotency error"],
        weaknesses=["backoff: jitter formula"],
        due_reviews=[{"concept": "lock-lease"}],
        due_count=1,
        response_language="zh-CN",
    )
    assert third.should_nudge is False
    assert third.reason == "daily_budget_exhausted"
    assert third.remaining_daily_budget == 0

    # Next UTC day rolls over the daily budget and clears yesterday's dedup keys.
    next_day = evaluate_proactive_opportunity(
        {"proactive_budget": budget_state},
        now=base + timedelta(days=1),
        diagnostics=["TypeError: idempotency conflict check returns wrong status"],
        weaknesses=weaknesses,
        response_language="en",
    )
    assert next_day.should_nudge is True
    assert next_day.kind == "diagnostic_weakness"
    assert next_day.remaining_daily_budget == DAILY_PROACTIVE_BUDGET - 1
