"""(f) Training cards and FSRS review scheduling.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real objects;
nothing here asserts on source text or code shape):
  * server/tests/test_card_generator.py
  * server/tests/test_review_scheduler.py
  * server/tests/test_review_scheduler_fsrs.py
  * server/tests/test_training_fsrs_scheduler.py

Guarantees covered:
  * card generation stays grounded in real facts and applies the missing-fact gate to every pack;
  * review scheduling derives due items from real training pressure and recalls evidence, not from invented state.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.core.event_ledger import EventLedgerService
from app.core.models import (
    CardGenerationContext,
    CardGenerationRequest,
    CardGenerationResponse,
    DependencyUsageEvidence,
    LearningPlan,
    PlanStage,
    ResourceKnowledgeEvidence,
    TrainingCardCandidateSnapshot,
)
from app.memory.models import MasteryRecord, WeaknessRecord, utc_now
from app.memory.review_scheduler import ReviewRating, ReviewScheduler
from app.memory.service import StructuredMemoryService
from app.memory.workspace_recovery import (
    apply_live_training_mint_to_card,
    leftover_formal_training_labels,
    live_training_mint_anchors,
)
from app.training.card_generator import (
    CardGenerationProviderFailure,
    CardGenerationService,
    CardGenerationStreamError,
    CardGenerationStreamEvent,
    _build_prompt,
    _has_expected_card_language,
    _parse_llm_json,
)
from app.training.fsrs_scheduler import FSRSTrainerCardScheduler, TrainingRating

# ---------------------------------------------------------------------------
# Restored from test_card_generator.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _ctx(**overrides: object) -> CardGenerationContext:
    defaults: dict[str, Any] = {
        "workspace_id": "ws-test",
        "source": "conversation_gap",
        "card_type": "practice",
        "context_hint": "",
        "target_skill": "",
        "focus_area": "",
        "plan_stage_id": "",
    }
    defaults.update(overrides)
    return CardGenerationContext(**defaults)


def _contains_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _resource_evidence(
    resource_id: str,
    *,
    fragment_id: str = "fragment-httpx-timeouts",
    source_type: str = "url",
    focus_area: str = "httpx timeout behavior",
    summary: str = "HTTPX timeout behavior distinguishes connect and read limits.",
) -> ResourceKnowledgeEvidence:
    return ResourceKnowledgeEvidence(
        resourceId=resource_id,
        fragmentId=fragment_id,
        sourceType=source_type,
        focusArea=focus_area,
        summary=summary,
    )


def _dependency_evidence(
    identifier: str,
    *,
    path: str = "src/client.py",
    kind: str = "import",
    summary: str | None = None,
) -> list[DependencyUsageEvidence]:
    return [
        DependencyUsageEvidence(
            filePath=path,
            kind=kind,
            identifier=identifier,
            summary=summary or f"{kind} {identifier}",
        )
    ]


class TestCardGenerationFromConversationGap(unittest.TestCase):
    """conversation_gap source should produce a practice card."""

    def test_practice_card_type(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card("conversation_gap", _ctx(focus_area="async patterns"))
        self.assertEqual(card.card_type, "practice")

    def test_focus_area_populated(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card("conversation_gap", _ctx(focus_area="generics"))
        self.assertEqual(card.focus_area, "generics")

    def test_title_includes_focus_area(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card("conversation_gap", _ctx(focus_area="error handling"))
        self.assertIn("error handling", card.title)

    def test_scenario_populated_from_context_hint(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(focus_area="decorators", context_hint="Learner struggled with @property"),
        )
        self.assertIn("@property", card.scenario)

    def test_guided_remote_conversation_gap_skips_llm_generation(self) -> None:
        svc = CardGenerationService()

        with patch.object(
            svc,
            "_try_llm_generation",
            side_effect=AssertionError(
                "guided scenario packs must not drift through LLM generation"
            ),
        ) as llm_generation:
            card = svc.generate_card(
                "conversation_gap",
                _ctx(
                    focus_area="VS Code Remote SSH credential mode",
                    context_hint="Teach the remote workspace boundary before a verification step.",
                    response_language="zh-CN",
                ),
            )

        llm_generation.assert_not_called()
        self.assertEqual(card.scenario_pack, "remote_workspace")
        self.assertTrue(card.verification_steps)
        self.assertTrue(card.return_with)
        self.assertTrue(card.next_after_completion)

    def test_non_code_conversation_gap_avoids_code_first_fallback(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="二次函数顶点式",
                target_skill="用配方法解释顶点式",
                response_language="zh-CN",
            ),
        )
        self.assertNotIn("代码", card.suggested_workspace_action)
        self.assertTrue(card.verification_steps)
        self.assertTrue(card.learner_deliverables)
        self.assertTrue(card.return_with)

    def test_memorization_conversation_gap_uses_recall_language(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="medical anatomy terms",
                target_skill="memorize three cranial nerve names",
                response_language="en-US",
            ),
        )
        self.assertIn("recall", card.suggested_workspace_action.lower())
        self.assertIn("recall", " ".join(card.verification_steps).lower())
        self.assertNotIn("patch", card.deliverable.lower())

    def test_guided_cards_keep_each_selected_non_english_locale_without_an_llm(self) -> None:
        service = CardGenerationService()

        for language in ("es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR"):
            with self.subTest(language=language):
                card = service.generate_card(
                    "conversation_gap",
                    _ctx(
                        focus_area="VS Code remote workspace boundary",
                        target_skill="credential placement",
                        context_hint="Learn the remote workspace boundary before verification.",
                        response_language=language,
                    ),
                )

                self.assertEqual(card.scenario_pack, "remote_workspace")
                self.assertTrue(_has_expected_card_language(card.model_dump(), language))
                self.assertTrue(card.title)
                self.assertTrue(card.verification_steps)
                self.assertTrue(card.return_with)


class TestCardGenerationFromPlanRequirement(unittest.TestCase):
    """plan_requirement source should default to flash but respect explicit submode."""

    def test_flash_card_type(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "plan_requirement",
            _ctx(target_skill="fastapi routing", card_type="flash"),
        )
        self.assertEqual(card.card_type, "flash")

    def test_question_populated(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "plan_requirement",
            _ctx(target_skill="pytest fixtures", card_type="flash"),
        )
        self.assertIn("pytest fixtures", card.question)

    def test_plan_links_when_stage_id_provided(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "plan_requirement",
            _ctx(target_skill="dependency injection", plan_stage_id="stage-3", card_type="flash"),
        )
        self.assertIn("stage-3", card.plan_links)

    def test_knowledge_type_set(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "plan_requirement",
            _ctx(target_skill="closures", card_type="flash"),
        )
        self.assertEqual(card.knowledge_type, "engineering_concept")

    def test_explicit_practice_card_type_is_respected(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "plan_requirement",
            _ctx(
                target_skill="provider truth chain",
                card_type="practice",
                response_language="zh-CN",
            ),
        )
        self.assertEqual(card.card_type, "practice")
        self.assertTrue(_contains_chinese(card.title))
        self.assertIn("provider truth chain", card.title)
        self.assertTrue(card.problem_statement)
        self.assertTrue(card.suggested_workspace_action)
        self.assertTrue(card.verification_steps)

    def test_plan_requirement_non_code_practice_avoids_patch_bias(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "plan_requirement",
            _ctx(
                focus_area="古诗赏析",
                target_skill="抓意象和情感转折",
                card_type="practice",
                response_language="zh-CN",
            ),
        )
        self.assertNotIn("补丁", card.deliverable)
        self.assertNotIn("补丁", card.return_with)
        self.assertNotIn("重构", " ".join(card.common_mistakes))


class TestPriorityScoring(unittest.TestCase):
    """_score_card returns a float in [0, 1]."""

    def test_score_in_range(self) -> None:
        svc = CardGenerationService()
        card = TrainingCardCandidateSnapshot(focus_area="testing", target_skill="unit tests")
        score = svc._score_card(card, {})
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_score_default_card(self) -> None:
        svc = CardGenerationService()
        card = TrainingCardCandidateSnapshot(focus_area="basics")
        score = svc._score_card(card, {})
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_review_due_boost(self) -> None:
        svc = CardGenerationService()
        card = TrainingCardCandidateSnapshot(
            focus_area="async",
            target_skill="asyncio",
            created_from="review_due",
        )
        score = svc._score_card(card, {})
        # review_due gets +0.2, target_skill gets +0.15, focus_area present (no -0.15)
        self.assertGreaterEqual(score, 0.85)

    def test_no_focus_area_penalty(self) -> None:
        svc = CardGenerationService()
        card = TrainingCardCandidateSnapshot()
        score = svc._score_card(card, {})
        # base 0.5, no focus_area => -0.15
        self.assertLessEqual(score, 0.5)

    def test_weakness_boost(self) -> None:
        svc = CardGenerationService()
        card = TrainingCardCandidateSnapshot(
            focus_area="error handling",
            target_skill="exceptions",
        )
        score = svc._score_card(card, {"weaknesses": ["error handling", "testing"]})
        score_no_weakness = svc._score_card(card, {"weaknesses": []})
        self.assertGreater(score, score_no_weakness)


class TestFallbackSources(unittest.TestCase):
    """Fallback sources and governed source packs return truthful cards without LLM drift."""

    def test_resource_knowledge_flash_card(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "resource_knowledge",
            _ctx(
                focus_area="API design",
                card_type="flash",
            ),
        )
        self.assertIsInstance(card, TrainingCardCandidateSnapshot)
        self.assertEqual(card.scenario_pack, "resource_knowledge")
        self.assertEqual(card.status, "needs_primer")
        self.assertIn("trusted indexed resource fragment", card.return_with)

    def test_resource_knowledge_card_marks_untrusted_resource_truth(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "resource_knowledge",
            _ctx(
                focus_area="API design",
                card_type="flash",
                resource_id="resource-api-design",
                context_hint="Indexed API design reference.",
                resource_knowledge_evidence=_resource_evidence("resource-api-design"),
                resource_quality_flags=["network_disabled"],
                resource_trust_score=0.2,
                resource_trust_state="untrusted",
            ),
        )
        self.assertEqual(card.scenario_pack, "resource_knowledge")
        self.assertEqual(card.status, "needs_primer")
        self.assertEqual(card.trust_state, "untrusted")
        self.assertIn("trusted indexed resource", card.return_with)

    def test_practice_feedback_practice_card(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "practice_feedback",
            _ctx(
                focus_area="refactoring",
                card_type="practice",
            ),
        )
        self.assertIn("refactoring", card.title)

    def test_practice_feedback_non_code_avoids_refactor_language(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "practice_feedback",
            _ctx(
                focus_area="English email opening",
                target_skill="tone control",
                card_type="practice",
                response_language="zh-CN",
            ),
        )
        self.assertNotIn("代码", card.suggested_workspace_action)
        self.assertNotIn("API 文档", " ".join(card.api_hints))
        self.assertIn("参考材料", " ".join(card.api_hints))

    def test_dependency_mastery_flash_card(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "dependency_mastery",
            _ctx(
                target_skill="typing",
                card_type="flash",
            ),
        )
        self.assertEqual(card.scenario_pack, "dependency_mastery")
        self.assertEqual(card.status, "needs_primer")
        self.assertIn("verified import, call, or declaration", card.return_with)

    def test_dependency_mastery_flash_card_respects_response_language(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "dependency_mastery",
            _ctx(
                target_skill="typing",
                card_type="flash",
                response_language="zh-CN",
            ),
        )
        self.assertTrue(_contains_chinese(card.title))
        self.assertEqual(card.scenario_pack, "dependency_mastery")
        self.assertEqual(card.status, "needs_primer")
        self.assertTrue(_contains_chinese(card.question))
        self.assertTrue(_contains_chinese(card.feedback["correct"]))

    def test_review_due_flash_card(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "review_due",
            _ctx(
                focus_area="closures",
                card_type="flash",
            ),
        )
        self.assertIn("closures", card.title)

    def test_conversation_gap_guided_pack_marks_missing_zh_workspace_facts(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="VS Code remote workspace boundary",
                context_hint="Remote SSH workspace",
                card_type="practice",
                response_language="zh-CN",
            ),
        )
        self.assertTrue(_contains_chinese(card.title))
        self.assertIn("API key", card.problem_statement)
        self.assertEqual(card.status, "needs_primer")
        self.assertEqual(card.files_to_touch, [])
        self.assertIn("\u7f3a\u5c11\u53ef\u9a8c\u8bc1\u4e8b\u5b9e", " ".join(card.source_chain))

    def test_unknown_source_uses_truthful_fallback_card(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card("unknown_source", _ctx(focus_area="session restore"))
        self.assertFalse(card.title.startswith("[Stub]"))
        self.assertIn("session restore", card.title)
        self.assertTrue(card.problem_statement or card.question)

    def test_unknown_source_non_code_practice_keeps_verification_shape(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "unknown_source",
            _ctx(
                focus_area="《小王子》阅读理解",
                target_skill="用证据支撑主题判断",
                response_language="zh-CN",
            ),
        )
        self.assertNotIn("代码", card.suggested_workspace_action)
        self.assertTrue(card.verification_steps)
        self.assertTrue(card.learner_deliverables)

    def test_remote_workspace_pack_degrades_without_remote_facts(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="VS Code Remote SSH credential mode",
                context_hint="The learner is confused about where the API key should live in a remote workspace.",
            ),
        )
        self.assertEqual(card.card_type, "practice")
        self.assertEqual(card.scenario_pack, "remote_workspace")
        self.assertIn("remote", card.title.lower())
        self.assertIn("detectRemoteWorkspaceType", card.expected_symbols)
        self.assertIn("getRecommendedCredentialMode(workspaceType)", card.api_hints)
        self.assertEqual(card.status, "needs_primer")
        self.assertEqual(card.files_to_touch, [])
        self.assertIn("remote identity", card.suggested_workspace_action)
        self.assertEqual(card.next_after_completion, "Return with the remote boundary proof")
        self.assertTrue(card.return_with)

    def test_debug_pack_degrades_without_a_diagnostic(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "practice_feedback",
            _ctx(
                focus_area="debugging a launch.json failure",
                context_hint="Breakpoints never hit and the learner keeps changing code too early.",
            ),
        )
        self.assertEqual(card.card_type, "practice")
        self.assertEqual(card.scenario_pack, "debug_loop")
        self.assertIn("debug", card.title.lower())
        self.assertEqual(card.status, "needs_primer")
        self.assertEqual(card.files_to_touch, [])
        self.assertIn("at least one diagnostic", card.verification_steps[0])
        self.assertIn("launch.json configurations", card.api_hints)
        self.assertEqual(card.next_after_completion, "Return with the debug evidence")
        self.assertTrue(card.stuck_recovery)

    def test_function_guidance_pack_turns_signature_help_into_flash_card(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "plan_requirement",
            _ctx(
                card_type="flash",
                target_skill="signature help and hover",
                context_hint="The learner guesses function parameters instead of checking editor guidance.",
            ),
        )
        self.assertEqual(card.card_type, "flash")
        self.assertEqual(card.scenario_pack, "function_guidance")
        self.assertIn("function", card.title.lower())
        self.assertIn("signature help", card.question.lower())
        self.assertGreaterEqual(len(card.hint_ladder), 2)
        self.assertIn("autocomplete", " ".join(card.common_mistakes).lower())
        self.assertEqual(
            card.next_after_completion,
            "Return with the contract rule, then recover one real call site in the paired practice step.",
        )
        self.assertTrue(card.verification_steps)
        self.assertTrue(card.return_with)

    def test_function_guidance_practice_pack_degrades_without_current_code(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="function contract recovery",
                context_hint="The learner edits unfamiliar call sites without checking hover or definition first.",
            ),
        )
        self.assertEqual(card.card_type, "practice")
        self.assertIn("function", card.title.lower())
        self.assertIn("Hover / Peek Definition", card.api_hints)
        self.assertEqual(card.status, "needs_primer")
        self.assertEqual(card.files_to_touch, [])
        self.assertNotIn("<live call site>", " ".join(card.files_to_touch))
        self.assertIn("code-file path", card.suggested_workspace_action)

    def test_function_guidance_pack_matches_plain_call_site_request(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="VS Code function guidance",
                context_hint="Understand one function and its call sites in VS Code before editing.",
            ),
        )
        self.assertEqual(card.card_type, "practice")
        self.assertEqual(card.scenario_pack, "function_guidance")
        self.assertIn("function", card.title.lower())
        self.assertTrue(card.return_with)

    def test_function_guidance_pack_keeps_english_terms_in_zh(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="VS Code function guidance",
                context_hint="Understand one function and its call sites in VS Code before editing.",
                response_language="zh-CN",
            ),
        )
        self.assertEqual(card.scenario_pack, "function_guidance")
        self.assertIn("函数", card.title)
        self.assertEqual(card.status, "needs_primer")
        self.assertIn("\u4ee3\u7801\u6587\u4ef6\u8def\u5f84", card.return_with)
        self.assertIn("call site", card.problem_statement.lower())
        self.assertIn("hover", card.problem_statement.lower())

    def test_function_guidance_pack_anchors_real_current_code(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="function contract recovery",
                context_hint="Use signature help before editing.",
                current_file_path="src/demo.ts",
                current_file_language_id="typescript",
                current_file_selection=(
                    "export async function fetchLesson(lessonId: string): Promise<Response> {\n"
                    "  return request(`/api/lessons/${lessonId}`);\n"
                    "}"
                ),
                current_file_selection_range="2:1-4:2",
            ),
        )
        self.assertEqual(card.scenario_pack, "function_guidance")
        self.assertEqual(card.files_to_touch, ["src/demo.ts"])
        self.assertTrue(any("fetchLesson" in step for step in card.verification_steps))
        self.assertTrue(any("src/demo.ts" in step for step in card.verification_steps))
        self.assertNotIn("<live call site>", " ".join(card.files_to_touch))

    def test_debug_pack_anchors_real_current_diagnostic(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="debugging a TypeError",
                context_hint="Create a tiny learn-first debug card.",
                current_file_path="src/router.ts",
                current_file_language_id="typescript",
                current_file_diagnostics=[
                    "TypeError: cannot read properties of undefined (reading 'id')"
                ],
            ),
        )
        self.assertEqual(card.scenario_pack, "debug_loop")
        self.assertEqual(card.files_to_touch, ["src/router.ts"])
        self.assertTrue(any("TypeError" in step for step in card.verification_steps))
        self.assertTrue(any("src/router.ts" in step for step in card.verification_steps))
        self.assertNotIn(".vscode/launch.json", card.files_to_touch)

    def test_remote_workspace_pack_anchors_remote_identity_and_boundary(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="VS Code Remote SSH credential mode",
                context_hint="Learn the remote boundary first.",
                current_file_path="src/remote.ts",
                workspace_root_path="/workspaces/trainer",
                remote_workspace_name="ssh-remote+lab",
                remote_workspace_facts=[
                    "remote identity: ssh-remote+lab",
                    "workspace root: /workspaces/trainer",
                ],
            ),
        )
        self.assertEqual(card.scenario_pack, "remote_workspace")
        self.assertEqual(card.files_to_touch, ["src/remote.ts"])
        self.assertTrue(any("ssh-remote+lab" in step for step in card.verification_steps))
        self.assertTrue(any("/workspaces/trainer" in step for step in card.verification_steps))
        self.assertNotIn("shared/src/remoteWorkspace.ts", card.files_to_touch)

    def test_conversation_gap_explicit_flash_uses_guided_remote_pack(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="VS Code Remote SSH credential mode",
                context_hint="The learner is confused about where the API key should live in a remote workspace.",
                card_type="flash",
            ),
        )
        self.assertEqual(card.card_type, "flash")
        self.assertEqual(card.scenario_pack, "remote_workspace")
        self.assertIn("remote", card.title.lower())
        self.assertTrue(card.question)
        self.assertTrue(card.expected_answer)
        self.assertEqual(
            card.next_after_completion,
            "Return with the boundary rule, then continue the paired remote practice step.",
        )
        self.assertTrue(card.learner_deliverables)
        self.assertTrue(card.verification_steps)
        self.assertTrue(card.return_with)


class TestRequiredFields(unittest.TestCase):
    """All generated cards must have required fields populated."""

    def _check_required(self, card: TrainingCardCandidateSnapshot, source: str) -> None:
        self.assertTrue(card.card_id, "card_id must be set")
        self.assertEqual(card.status, "candidate")
        self.assertEqual(card.source_chain, ["card_generation_router"])
        self.assertTrue(card.why_now, "why_now must be set")
        self.assertTrue(card.created_at, "created_at must be set")
        self.assertTrue(card.updated_at, "updated_at must be set")

    def _check_governed_required(self, card: TrainingCardCandidateSnapshot) -> None:
        self.assertTrue(card.card_id, "card_id must be set")
        self.assertEqual(card.status, "candidate")
        self.assertTrue(card.source_chain, "governed cards must retain a source chain")
        self.assertTrue(card.why_now, "why_now must be set")
        self.assertTrue(card.created_at, "created_at must be set")
        self.assertTrue(card.updated_at, "updated_at must be set")

    def _check_flash_contract(self, card: TrainingCardCandidateSnapshot) -> None:
        self.assertEqual(card.card_type, "flash")
        self.assertTrue(card.problem_statement, "flash cards must explain the gap")
        self.assertTrue(card.learner_deliverables, "flash cards must carry learner deliverables")
        self.assertTrue(card.verification_steps, "flash cards must carry verification steps")
        self.assertTrue(card.success_signal, "flash cards must carry a success signal")
        self.assertTrue(card.reflection_prompt, "flash cards must carry a reflection prompt")
        self.assertTrue(card.return_with, "flash cards must carry a return path")
        self.assertTrue(
            card.next_after_completion, "flash cards must carry the next step after completion"
        )

    def test_conversation_gap_required_fields(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card("conversation_gap", _ctx(focus_area="testing"))
        self._check_required(card, "conversation_gap")

    def test_leftover_formal_title_does_not_mint_conversation_gap_why_or_skill(self) -> None:
        leftover_title = "Keep the current stage"
        plan = LearningPlan(
            id="plan-formal-old",
            title=leftover_title,
            summary=leftover_title,
            current_stage_id="stage-1",
            current_step="Keep one auth check",
            why_now="Expired tokens still leak the session.",
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
        advanced = {
            "current_step": "Add a token expiry test",
            "why_now": "",
            "resume_state": "in_progress",
        }
        anchors = live_training_mint_anchors(
            plan=plan,
            runtime=advanced,
            existing=advanced,
            task_title=leftover_title,
            why_now=leftover_title,
            target_skill=leftover_title,
            focus_area=leftover_title,
        )
        self.assertNotEqual(anchors["why_now"], leftover_title)
        self.assertNotEqual(anchors["target_skill"], leftover_title)
        svc = CardGenerationService()
        card = svc.generate_card("conversation_gap", _ctx(**anchors))
        leftover = leftover_formal_training_labels(
            plan=plan,
            task_title=leftover_title,
            live_plan=False,
            live_task=False,
        )
        card = apply_live_training_mint_to_card(
            card,
            anchors=anchors,
            leftover_labels=leftover,
            recovered_step="Add a token expiry test",
        )
        self.assertNotEqual(card.why_now, leftover_title)
        self.assertNotEqual(card.target_skill, leftover_title)
        self.assertNotIn(leftover_title, card.why_now or "")
        self.assertNotIn(leftover_title, card.target_skill or "")
        still_on_plan = {
            "current_step": "Keep one auth check",
            "why_now": leftover_title,
            "plan_id": "plan-formal-old",
            "resume_state": "in_progress",
        }
        still_anchors = live_training_mint_anchors(
            plan=plan,
            runtime=still_on_plan,
            existing=still_on_plan,
            task_title=leftover_title,
            why_now=leftover_title,
            target_skill=leftover_title,
            focus_area=leftover_title,
        )
        self.assertEqual(still_anchors["why_now"], leftover_title)
        self.assertEqual(still_anchors["target_skill"], leftover_title)
        still_card = svc.generate_card("conversation_gap", _ctx(**still_anchors))
        self.assertEqual(still_card.target_skill, leftover_title)

    def test_plan_requirement_required_fields(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card("plan_requirement", _ctx(target_skill="fastapi"))
        self._check_required(card, "plan_requirement")

    def test_fallback_required_fields(self) -> None:
        svc = CardGenerationService()
        for source in ["practice_feedback", "review_due", "unknown_source"]:
            card = svc.generate_card(source, _ctx(focus_area="x"))
            self._check_required(card, source)
        resource_card = svc.generate_card(
            "resource_knowledge",
            _ctx(
                resource_id="resource-required-fields",
                resource_trust_state="trusted",
                resource_knowledge_evidence=_resource_evidence("resource-required-fields"),
            ),
        )
        dependency_card = svc.generate_card(
            "dependency_mastery",
            _ctx(
                target_skill="typing",
                dependency_usage_evidence=_dependency_evidence("typing"),
            ),
        )
        self._check_governed_required(resource_card)
        self._check_governed_required(dependency_card)

    def test_flash_cards_fill_loop_contract_fields(self) -> None:
        svc = CardGenerationService()
        cards = [
            svc.generate_card(
                "plan_requirement", _ctx(target_skill="pytest fixtures", card_type="flash")
            ),
            svc.generate_card(
                "resource_knowledge",
                _ctx(
                    resource_id="resource-api-design",
                    card_type="flash",
                    resource_trust_state="trusted",
                    resource_knowledge_evidence=_resource_evidence("resource-api-design"),
                ),
            ),
            svc.generate_card(
                "dependency_mastery",
                _ctx(
                    target_skill="retry semantics",
                    card_type="flash",
                    dependency_usage_evidence=_dependency_evidence("retry"),
                ),
            ),
            svc.generate_card("review_due", _ctx(focus_area="closures", card_type="flash")),
        ]
        for card in cards:
            self._check_flash_contract(card)

    def test_card_id_is_uuid_format(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card("conversation_gap", _ctx(focus_area="testing"))
        # UUID4 is 36 chars with hyphens
        self.assertEqual(len(card.card_id), 36)
        self.assertEqual(card.card_id.count("-"), 4)

    def test_created_from_mapped_correctly(self) -> None:
        svc = CardGenerationService()
        mapping = {
            "conversation_gap": "conversation",
            "plan_requirement": "plan",
            "resource_knowledge": "resource",
            "practice_feedback": "practice_feedback",
            "dependency_mastery": "dependency_mastery",
            "review_due": "review_due",
        }
        for source, expected in mapping.items():
            card = svc.generate_card(source, _ctx(focus_area="x"))
            self.assertEqual(
                card.created_from,
                expected,
                f"Source {source!r} should map to created_from={expected!r}",
            )


class TestLearningLoopTruthfulness(unittest.TestCase):
    """Generated cards must remain one-problem, evidence-first learning units."""

    def test_practice_card_scopes_a_compound_request_to_one_problem(self) -> None:
        card = CardGenerationService().generate_card(
            "conversation_gap",
            _ctx(
                focus_area="timeouts and retries",
                target_skill="timeouts and retries",
            ),
        )

        self.assertEqual(card.focus_area, "timeouts")
        self.assertEqual(card.target_skill, "timeouts")
        self.assertIn("timeouts", card.title)
        assert card.model_extra is not None
        loop = card.model_extra["learning_loop"]
        self.assertIsInstance(loop, dict)
        self.assertEqual(loop["single_problem_focus"], "timeouts")
        self.assertTrue(loop["completion_requires_verification"])
        self.assertFalse(loop["durable_mastery_claimed"])
        self.assertTrue(loop["learn"])
        self.assertTrue(loop["try"])
        self.assertTrue(loop["verify"])
        self.assertTrue(loop["reflect"])
        self.assertTrue(loop["return"])

    def test_provider_mastery_claim_is_rewritten_to_evidence_requirement(self) -> None:
        response = _practice_llm_response()
        response["success_signal"] = "You mastered async error handling and are ready to advance."
        card = CardGenerationService(provider_service=_MockProviderService(response)).generate_card(
            "conversation_gap",
            _ctx(focus_area="async patterns", target_skill="async error handling"),
        )

        self.assertNotIn("master", card.success_signal.lower())
        self.assertIn("verifiable evidence", card.success_signal.lower())
        assert card.model_extra is not None
        self.assertTrue(card.model_extra["completion_requires_verification"])


class TestRequestResponseModels(unittest.TestCase):
    """Pydantic models round-trip correctly."""

    def test_card_generation_request_defaults(self) -> None:
        req = CardGenerationRequest()
        self.assertEqual(req.source, "conversation_gap")
        self.assertEqual(req.card_type, "practice")

    def test_card_generation_response_serialization(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card("conversation_gap", _ctx(focus_area="testing"))
        score = svc._score_card(card, {})
        resp = CardGenerationResponse(card=card, score=score)
        data = resp.model_dump()
        self.assertIn("card", data)
        self.assertIn("score", data)
        self.assertIsInstance(data["score"], float)


class TestCurrentIdeFileGrounding(unittest.TestCase):
    def test_latest_code_selection_and_diagnostics_reach_model_as_source_data(self) -> None:
        context = _ctx(
            current_file_path="/workspace/.tmp-native-training/list_pairs.py",
            current_file_language_id="python",
            current_file_content="def test_nested_mutability():\n    assert [1, 2, 4] == [1, 2, 4]\n",
            current_file_selection="assert [1, 2, 4] == [1, 2, 4]",
            current_file_selection_range="2:5-2:38",
            current_file_diagnostics=["No active diagnostics"],
        )
        messages = CardGenerationService()._llm_messages(context, "conversation_gap", "practice")
        snapshot = json.loads(messages[1]["content"].split("(source data):\n", 1)[1])
        self.assertEqual(snapshot["code"], context.current_file_content)
        self.assertEqual(snapshot["selection"], context.current_file_selection)
        self.assertEqual(snapshot["path"], context.current_file_path)
        self.assertEqual(snapshot["diagnostics"], context.current_file_diagnostics)
        self.assertFalse(snapshot["code_truncated"])
        self.assertIn("not guesses from its filename", messages[0]["content"])

    def test_large_file_snapshot_is_bounded_and_marks_truncation(self) -> None:
        context = _ctx(current_file_path="/workspace/large.py", current_file_content="x" * 13000)
        messages = CardGenerationService()._llm_messages(context, "conversation_gap", "practice")
        snapshot = json.loads(messages[1]["content"].split("(source data):\n", 1)[1])
        self.assertEqual(len(snapshot["code"]), 12000)
        self.assertTrue(snapshot["code_truncated"])

    def test_model_basename_and_missing_target_use_exact_host_file(self) -> None:
        context = _ctx(
            current_file_path="/workspace/nested/list_pairs.py",
            current_file_content="pair = ([1, 2], 3)",
        )
        for targets in (["list_pairs.py"], []):
            with self.subTest(targets=targets):
                card = CardGenerationService()._finalize_card(
                    TrainingCardCandidateSnapshot(card_type="practice", files_to_touch=targets),
                    "conversation_gap",
                    context,
                )
                self.assertEqual(card.files_to_touch, [context.current_file_path])

    def test_indexed_material_and_current_file_share_one_verification_target(self) -> None:
        evidence = _resource_evidence("paper-a")
        context = _ctx(
            resource_id=evidence.resource_id,
            resource_version_id="rv-paper",
            resource_content_hash="abc123",
            resource_knowledge_evidence=evidence,
            current_file_path="/workspace/src/client.py",
            current_file_content="import httpx",
        )
        service = CardGenerationService()
        messages = service._llm_messages(context, "plan_requirement", "practice")
        self.assertIn(context.current_file_path, messages[1]["content"])
        self.assertIn(evidence.summary, messages[1]["content"])
        card = service._finalize_card(
            TrainingCardCandidateSnapshot(card_type="practice", files_to_touch=["made-up.py"]),
            "plan_requirement",
            context,
        )
        self.assertEqual(card.files_to_touch, [context.current_file_path])
        self.assertEqual(card.resource_version_id, "rv-paper")
        self.assertEqual(card.resource_content_hash, "abc123")

    def test_other_file_same_basename_is_not_rebound_and_flash_has_no_file_target(self) -> None:
        context = _ctx(
            current_file_path="/workspace/nested/sample.py", current_file_content="x = 1"
        )
        service = CardGenerationService()
        card = service._finalize_card(
            TrainingCardCandidateSnapshot(card_type="practice", files_to_touch=["other/sample.py"]),
            "conversation_gap",
            context,
        )
        self.assertEqual(card.files_to_touch, ["other/sample.py"])
        flash = service._finalize_card(
            TrainingCardCandidateSnapshot(card_type="flash"),
            "conversation_gap",
            context,
        )
        self.assertEqual(flash.files_to_touch, [])


class _MockProviderService:
    """Minimal mock that returns a canned JSON string from chat_completion."""

    def __init__(self, response_json: dict) -> None:
        self._response = response_json

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        import json

        return json.dumps(self._response)


class _RecordingMockProviderService(_MockProviderService):
    """A valid provider response that makes an unexpected guided LLM call observable."""

    def __init__(self, response_json: dict) -> None:
        super().__init__(response_json)
        self.calls = 0
        self.messages = []

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        self.calls += 1
        self.messages = messages
        return await super().chat_completion(messages, model, temperature, max_tokens)


class _StreamingMockProviderService:
    """Minimal async provider used to exercise the card stream contract."""

    def __init__(self, chunks: list[str], error: Exception | None = None) -> None:
        self._chunks = chunks
        self._error = error

    async def chat_completion_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        cancel_event: asyncio.Event | None = None,
    ):
        del messages, model, temperature, max_tokens, cancel_event
        for chunk in self._chunks:
            yield chunk
        if self._error is not None:
            raise self._error


def _practice_llm_response() -> dict:
    return {
        "title": "Practice: Async Error Handling",
        "focus_area": "async patterns",
        "target_skill": "async error handling",
        "scenario": "You are building a web scraper that fetches multiple pages concurrently.",
        "problem_statement": "Handle exceptions from concurrent HTTP requests gracefully.",
        "api_hints": ["asyncio.gather(return_exceptions=True)", "try/except inside async function"],
        "deliverable": "A function that fetches URLs concurrently and reports failures without crashing.",
        "self_check": [
            "Does the function handle network errors?",
            "Are all results collected even if some fail?",
        ],
        "grading_rubric": [
            "All exceptions are caught and logged",
            "Successful results are still returned",
        ],
        "learner_deliverables": [
            "A short note describing the failure boundary",
            "A working async function with graceful error handling",
        ],
        "verification_steps": [
            "Run the function with one failing URL",
            "Confirm successful URLs still return data",
        ],
        "success_signal": "One failing request no longer crashes the whole concurrent batch.",
        "stuck_recovery": "Start with a single URL fetch, then add concurrency.",
        "reflection_prompt": "How does return_exceptions change the behavior of asyncio.gather?",
        "return_with": "Bring back the failing case you proved and the result you observed.",
        "next_after_completion": "Turn the same pattern into one smaller retry or timeout guard.",
        "difficulty": "medium",
        "constraints": ["Use asyncio only, no threading."],
    }


def _flash_llm_response() -> dict:
    return {
        "title": "Flash: Python Decorators",
        "why_now": "You need one stable rule for decorators before you widen the current Python thread.",
        "focus_area": "decorators",
        "target_skill": "python decorators",
        "knowledge_type": "engineering_concept",
        "question": "What is a Python decorator and how does the @ syntax work?",
        "answer_mode": "text",
        "expected_answer": "A decorator is a callable that takes a function and returns a modified function. The @ syntax is syntactic sugar for func = decorator(func).",
        "problem_statement": "State the smallest decorator rule that keeps higher-order function behavior grounded.",
        "suggested_workspace_action": "Answer first, then name one function boundary where the rule applies.",
        "deliverable": "One short rule plus one concrete decorator anchor.",
        "learner_deliverables": [
            "One sentence explaining what the decorator returns.",
            "One real decorator-shaped example.",
        ],
        "verification_steps": [
            "Keep the answer tied to the function-in, function-out boundary.",
            "Name one concrete anchor instead of staying at the slogan level.",
        ],
        "success_signal": "You can explain the decorator rule and attach it to one concrete example without guessing.",
        "reflection_prompt": "Which boundary made the @ syntax click: decoration time or call time?",
        "return_with": "Return with the decorator rule and one concrete example.",
        "next_after_completion": "Return with the checked rule, then open one small decorator practice step in the live workspace.",
        "hint_ladder": [
            "Think about higher-order functions.",
            "Consider what happens when you call decorator(func).",
        ],
        "common_mistakes": [
            "Forgetting that decorators execute at import time.",
            "Not using functools.wraps to preserve metadata.",
        ],
        "feedback": {
            "correct": "Great understanding of decorators!",
            "incorrect": "Review how higher-order functions work in Python.",
        },
        "difficulty": "medium",
    }


def _complete_llm_response() -> dict:
    """Return a response that satisfies either card contract if it is ever called."""
    return {**_practice_llm_response(), **_flash_llm_response()}


class TestCardGenerationStreamingTruth(unittest.TestCase):
    """Streaming generation must distinguish degradation from interruption."""

    def test_localizes_an_english_draft_without_changing_project_checks(self) -> None:
        translated = {
            "title": "让单个请求失败时仍能返回其他结果",
            "scenario": "批量请求中可能有一个请求失败。",
            "problem_statement": "修改 fetch_all，让单个请求失败时仍然保留其他结果。",
            "deliverable": "提交修改后的 fetch_all。",
        }

        class Provider(_StreamingMockProviderService):
            async def chat_completion(self, messages, **kwargs):
                assert set(json.loads(messages[-1]["content"])) == set(translated)
                return json.dumps(translated, ensure_ascii=False)

        checks = ["`assert fetch_all(True)` · `test_client.py:10`"]
        service = CardGenerationService(
            provider_service=Provider([json.dumps(_practice_llm_response())]),
        )
        context = _ctx(
            response_language="zh-CN",
            resource_id="paper-a",
            resource_knowledge_evidence=_resource_evidence("paper-a"),
            current_file_path="client.py",
            current_file_content="def fetch_all(): pass",
            project_verification_steps=checks,
        )

        async def collect() -> list[TrainingCardCandidateSnapshot]:
            return [
                event.card
                async for event in service.generate_card_stream("plan_requirement", context)
                if event.card is not None
            ]

        (card,) = asyncio.run(collect())
        self.assertEqual(card.title, translated["title"])
        self.assertEqual(card.problem_statement, translated["problem_statement"])
        self.assertEqual(card.verification_steps, checks)
        self.assertEqual(card.expected_symbols, ["fetch_all"])
        # generation_* provenance is attached as an undeclared extra (extra="allow")
        # by CardGenerationService._finalize_card, so read it through model_extra.
        provenance = card.model_extra
        assert provenance is not None, "candidate snapshots keep extras (extra=allow)"
        self.assertEqual(provenance["generation_source"], "model")

    def test_indexed_file_practice_binds_the_host_target_before_validating_model_fields(
        self,
    ) -> None:
        evidence = _resource_evidence("paper-a")
        context = _ctx(
            plan_stage_id="stage-1",
            resource_id=evidence.resource_id,
            resource_version_id="rv-paper",
            resource_content_hash="abc123",
            resource_knowledge_evidence=evidence,
            current_file_path="/workspace/src/client  demo.py",
            current_file_content="import httpx",
        )
        # The live model returned a scalar here, even though the prompt uses an array.
        response = {
            **_practice_llm_response(),
            "files_to_touch": "made-up.py",
            "target_skill": "unspecified",
            "self_check": "Can the errors be observed?",
        }
        response["verification_steps"].append(response["verification_steps"][0])
        streaming = CardGenerationService(
            provider_service=_StreamingMockProviderService([json.dumps(response)]),
        )

        async def collect() -> list[TrainingCardCandidateSnapshot]:
            return [
                event.card
                async for event in streaming.generate_card_stream("plan_requirement", context)
                if event.card is not None
            ]

        blocking = CardGenerationService(provider_service=_MockProviderService(response))
        streamed_cards = asyncio.run(collect())
        self.assertEqual(len(streamed_cards), 1)
        for card in [*streamed_cards, blocking.generate_card("plan_requirement", context)]:
            self.assertEqual(card.title, response["title"])
            self.assertEqual(card.target_skill, response["focus_area"])
            self.assertEqual(card.verification_steps, response["verification_steps"][:2])
            self.assertEqual(card.self_check, [response["self_check"]])
            self.assertEqual(card.files_to_touch, [context.current_file_path])
            self.assertEqual(card.resource_id, evidence.resource_id)
            self.assertEqual(card.resource_version_id, context.resource_version_id)
            self.assertEqual(card.resource_content_hash, context.resource_content_hash)

    def test_partial_stream_json_is_rejected_without_a_candidate(self) -> None:
        ledger = EventLedgerService()
        service = CardGenerationService(
            provider_service=_StreamingMockProviderService(['{"title":"partial"']),
            event_ledger=ledger,
        )

        async def collect() -> list[object]:
            return [
                event
                async for event in service.generate_card_stream(
                    "conversation_gap",
                    _ctx(
                        workspace_id="ws-stream-partial-json",
                        focus_area="stream parsing",
                    ),
                )
            ]

        with self.assertRaises(CardGenerationStreamError) as raised:
            asyncio.run(collect())
        self.assertEqual(raised.exception.reason, "invalid_json")
        self.assertEqual(
            ledger.count(
                event_type="card_candidate_created",
                project_id="ws-stream-partial-json",
            ),
            0,
        )
        failures = ledger.query(
            event_type="card_generation_failed",
            project_id="ws-stream-partial-json",
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].payload_ref["reason"], "invalid_json")

    def test_invalid_stream_json_marks_fallback_provenance_and_ledger(self) -> None:
        ledger = EventLedgerService()
        service = CardGenerationService(
            provider_service=_StreamingMockProviderService(["not valid card JSON"]),
            event_ledger=ledger,
        )

        async def collect() -> list[object]:
            return [
                event
                async for event in service.generate_card_stream(
                    "conversation_gap",
                    _ctx(
                        workspace_id="ws-stream-invalid-json",
                        focus_area="stream parsing",
                    ),
                )
            ]

        with self.assertRaises(CardGenerationStreamError) as raised:
            asyncio.run(collect())
        self.assertEqual(raised.exception.reason, "invalid_json")
        self.assertEqual(
            ledger.count(
                event_type="card_candidate_created",
                project_id="ws-stream-invalid-json",
            ),
            0,
        )

    def test_interrupted_provider_stream_raises_recoverable_error_without_fake_card(
        self,
    ) -> None:
        ledger = EventLedgerService()
        service = CardGenerationService(
            provider_service=_StreamingMockProviderService(
                ['{"title":"partial"'],
                error=RuntimeError("upstream secret should not escape"),
            ),
            event_ledger=ledger,
        )

        async def consume() -> list[object]:
            events: list[object] = []
            async for event in service.generate_card_stream(
                "conversation_gap",
                _ctx(
                    workspace_id="ws-stream-interrupted",
                    focus_area="stream recovery",
                ),
            ):
                events.append(event)
            return events

        with self.assertRaises(CardGenerationStreamError) as raised:
            asyncio.run(consume())

        error = raised.exception
        self.assertTrue(error.recoverable)
        self.assertTrue(error.retryable)
        self.assertEqual(error.source, "conversation_gap")
        self.assertIn("recoverable=true", str(error))
        self.assertNotIn("upstream secret", str(error))
        self.assertEqual(
            ledger.count(
                event_type="card_candidate_created",
                project_id="ws-stream-interrupted",
            ),
            0,
        )
        failures = ledger.query(
            event_type="card_generation_failed",
            project_id="ws-stream-interrupted",
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].payload_ref["reason"], "stream_interrupted")
        self.assertTrue(failures[0].payload_ref["recoverable"])
        self.assertTrue(failures[0].payload_ref["retryable"])

    def test_guided_pack_stream_does_not_call_the_provider(self) -> None:
        ledger = EventLedgerService()
        provider = _StreamingMockProviderService(
            [],
            error=RuntimeError("provider disconnected"),
        )
        service = CardGenerationService(
            provider_service=provider,
            event_ledger=ledger,
        )

        async def collect() -> list[CardGenerationStreamEvent]:
            return [
                event
                async for event in service.generate_card_stream(
                    "conversation_gap",
                    _ctx(
                        workspace_id="ws-stream-guided-pack",
                        focus_area="debugging a launch.json failure",
                        context_hint="Breakpoints never hit.",
                    ),
                )
            ]

        events = asyncio.run(collect())
        card_events = [event.card for event in events if event.card is not None]
        self.assertEqual(len(card_events), 1)
        self.assertEqual(card_events[0].scenario_pack, "debug_loop")
        self.assertEqual(
            ledger.count(
                event_type="card_candidate_created",
                project_id="ws-stream-guided-pack",
            ),
            1,
        )


class TestGuidedScenarioFactGate(unittest.TestCase):
    """Guided scenario packs are deterministic and must be grounded before any LLM call."""

    def test_legacy_keyword_packs_keep_priority_over_governed_source_fallbacks(self) -> None:
        provider = _RecordingMockProviderService(_complete_llm_response())
        service = CardGenerationService(provider_service=provider)
        cases = (
            (
                "resource_knowledge",
                _ctx(
                    focus_area="debug a launch.json failure",
                    resource_id="resource-unverified-debug-note",
                    card_type="practice",
                ),
                "debug_loop",
            ),
            (
                "dependency_mastery",
                _ctx(target_skill="signature help and hover", card_type="flash"),
                "function_guidance",
            ),
        )

        for source, context, expected_pack in cases:
            with self.subTest(source=source):
                card = service.generate_card(source, context)
                self.assertEqual(card.scenario_pack, expected_pack)
                self.assertEqual(card.status, "needs_primer")
                self.assertEqual(card.files_to_touch, [])

        self.assertEqual(provider.calls, 0)

    def test_guided_sources_bypass_a_successful_provider_before_generation(self) -> None:
        provider = _RecordingMockProviderService(_complete_llm_response())
        service = CardGenerationService(provider_service=provider)
        cases = (
            (
                "conversation_gap",
                _ctx(
                    focus_area="debugging a launch.json failure",
                    card_type="practice",
                ),
                "debug_loop",
            ),
            (
                "plan_requirement",
                _ctx(
                    focus_area="VS Code Remote SSH credential mode",
                    card_type="flash",
                    plan_stage_id="stage-guided",
                ),
                "remote_workspace",
            ),
            (
                "practice_feedback",
                _ctx(
                    focus_area="debugging a breakpoint that never hits",
                    card_type="practice",
                ),
                "debug_loop",
            ),
            (
                "dependency_mastery",
                _ctx(
                    target_skill="signature help and hover",
                    card_type="flash",
                ),
                "function_guidance",
            ),
            (
                "review_due",
                _ctx(
                    focus_area="VS Code remote workspace boundary",
                    card_type="flash",
                ),
                "remote_workspace",
            ),
            (
                "conversation",
                _ctx(
                    focus_area="function hint recovery",
                    context_hint="Use Hover before editing one unfamiliar call site.",
                    card_type="practice",
                ),
                "function_guidance",
            ),
        )

        for source, context, expected_pack in cases:
            with self.subTest(source=source):
                card = service.generate_card(source, context)
                self.assertEqual(card.scenario_pack, expected_pack)
                self.assertEqual(card.status, "needs_primer")
                self.assertEqual(card.files_to_touch, [])
                if source == "plan_requirement":
                    self.assertEqual(card.plan_links, ["stage-guided"])

        self.assertEqual(provider.calls, 0)

    def test_catalog_fallback_applies_missing_fact_gate_to_every_pack(self) -> None:
        cases = (
            ("remote workspace credential mode", "remote_workspace"),
            ("debug a launch.json failure", "debug_loop"),
            ("signature help for an unfamiliar function", "function_guidance"),
        )

        with patch(
            "app.training.card_generator._load_guided_scenario_pack_catalog", return_value={}
        ):
            for focus_area, expected_pack in cases:
                with self.subTest(pack=expected_pack):
                    card = CardGenerationService().generate_card(
                        "review_due",
                        _ctx(focus_area=focus_area, card_type="flash"),
                    )
                    rendered = repr(card.model_dump())

                    self.assertEqual(card.scenario_pack, expected_pack)
                    self.assertEqual(card.status, "needs_primer")
                    self.assertEqual(card.files_to_touch, [])
                    self.assertNotIn("<live call site>", rendered)
                    self.assertNotIn("<current failing file>", rendered)
                    self.assertNotIn("shared/src/remoteWorkspace.ts", rendered)
                    self.assertNotIn("extension/src/commands/workspaceContext.ts", rendered)

    def test_catalog_fallback_keeps_a_real_anchor_without_leaking_file_content(self) -> None:
        source_code = (
            "export async function fetchLesson(lessonId: string) {\n"
            '  const internalToken = "do-not-leak-this-secret";\n'
            "  return request(`/api/lessons/${lessonId}`);\n"
            "}\n"
        )

        with patch(
            "app.training.card_generator._load_guided_scenario_pack_catalog", return_value={}
        ):
            card = CardGenerationService().generate_card(
                "dependency_mastery",
                _ctx(
                    target_skill="signature help for fetchLesson",
                    card_type="flash",
                    current_file_path="src/demo.ts",
                    current_file_content=source_code,
                ),
            )

        rendered = repr(card.model_dump())
        self.assertEqual(card.scenario_pack, "function_guidance")
        self.assertEqual(card.status, "candidate")
        self.assertEqual(card.files_to_touch, ["src/demo.ts"])
        self.assertIn("fetchLesson", rendered)
        self.assertNotIn("do-not-leak-this-secret", rendered)
        self.assertNotIn("const internalToken", rendered)

    def test_resource_knowledge_teaches_content_using_only_derived_evidence(self) -> None:
        response = {
            **_complete_llm_response(),
            "title": "HTTPX timeout boundaries",
            "focus_area": "HTTPX timeouts",
            "target_skill": "Connect versus read timeout",
            "question": "How do connect and read timeout limits differ?",
        }
        provider = _RecordingMockProviderService(response)
        card = CardGenerationService(provider_service=provider).generate_card(
            "resource_knowledge",
            _ctx(
                resource_id="resource-httpx-timeouts",
                focus_area="client-selected focus must not pass the fact gate",
                context_hint="Indexed URL: https://www.python-httpx.org/advanced/timeouts/",
                resource_trust_state="trusted",
                resource_trust_score=0.95,
                resource_knowledge_evidence=_resource_evidence("resource-httpx-timeouts"),
                card_type="practice",
                response_language="en-US",
            ),
        )

        self.assertEqual(card.scenario_pack, "resource_knowledge")
        self.assertEqual(card.status, "candidate")
        self.assertEqual(card.created_from, "resource")
        self.assertEqual(card.title, response["title"])
        self.assertIn("Resource ID: resource-httpx-timeouts", card.source_chain)
        self.assertIn("Trust state: trusted", card.source_chain)
        self.assertNotIn(
            "https://www.python-httpx.org/advanced/timeouts/", " ".join(card.source_chain)
        )
        rendered = repr(card.model_dump())
        self.assertIn("fragment-httpx-timeouts", " ".join(card.source_chain))
        self.assertIn(
            "HTTPX timeout behavior distinguishes connect and read limits.",
            " ".join(card.source_chain),
        )
        self.assertNotIn("https://www.python-httpx.org/advanced/timeouts/", rendered)
        self.assertNotIn("client-selected focus", rendered)
        prompt = provider.messages[0]["content"]
        self.assertIn("HTTPX timeout behavior distinguishes connect and read limits.", prompt)
        self.assertNotIn("client-selected focus", prompt)
        self.assertNotIn("https://www.python-httpx.org/advanced/timeouts/", prompt)
        self.assertEqual(provider.calls, 1)

    def test_resource_knowledge_pack_needs_primer_without_derived_evidence(self) -> None:
        provider = _RecordingMockProviderService(_complete_llm_response())
        card = CardGenerationService(provider_service=provider).generate_card(
            "resource_knowledge",
            _ctx(
                resource_id="resource-httpx-timeouts",
                focus_area="httpx timeout behavior",
                resource_trust_state="trusted",
                resource_trust_score=0.95,
                card_type="flash",
            ),
        )

        self.assertEqual(card.scenario_pack, "resource_knowledge")
        self.assertEqual(card.status, "needs_primer")
        self.assertEqual(card.files_to_touch, [])
        self.assertIn("trusted indexed resource fragment", card.return_with)
        self.assertEqual(provider.calls, 0)

    def test_dependency_mastery_pack_uses_real_context_before_llm(self) -> None:
        provider = _RecordingMockProviderService(_complete_llm_response())
        card = CardGenerationService(provider_service=provider).generate_card(
            "dependency_mastery",
            _ctx(
                target_skill="httpx.Client.get API",
                context_hint="Inspect the existing request path before changing timeout behavior.",
                current_file_path="src/client.py",
                dependency_usage_evidence=_dependency_evidence("httpx"),
                card_type="practice",
            ),
        )

        self.assertEqual(card.scenario_pack, "dependency_mastery")
        self.assertEqual(card.status, "candidate")
        self.assertEqual(card.created_from, "dependency_mastery")
        self.assertEqual(card.files_to_touch, ["src/client.py"])
        self.assertIn("Dependency/API: httpx.Client.get API", card.source_chain)
        self.assertIn("Verified import: import httpx in src/client.py", card.source_chain)
        self.assertIn("Verification target: one real output", card.source_chain)
        self.assertEqual(provider.calls, 0)

    def test_dependency_mastery_pack_needs_primer_without_verified_usage(self) -> None:
        provider = _RecordingMockProviderService(_complete_llm_response())
        card = CardGenerationService(provider_service=provider).generate_card(
            "dependency_mastery",
            _ctx(target_skill="httpx.Client API", card_type="flash"),
        )

        self.assertEqual(card.scenario_pack, "dependency_mastery")
        self.assertEqual(card.status, "needs_primer")
        self.assertEqual(card.files_to_touch, [])
        self.assertIn("verified import, call, or declaration", card.return_with)
        self.assertEqual(provider.calls, 0)

    def test_dependency_mastery_rejects_raw_hint_path_and_unmatched_evidence(self) -> None:
        provider = _RecordingMockProviderService(_complete_llm_response())
        service = CardGenerationService(provider_service=provider)
        cases = (
            _ctx(
                target_skill="httpx.Client API",
                context_hint="The current request path already uses httpx.",
                current_file_path="src/invented-client.py",
                card_type="flash",
            ),
            _ctx(
                target_skill="httpx.Client API",
                current_file_path="src/client.py",
                dependency_usage_evidence=_dependency_evidence("requests"),
                card_type="flash",
            ),
        )

        for context in cases:
            with self.subTest(context=context.model_dump()):
                card = service.generate_card("dependency_mastery", context)
                self.assertEqual(card.scenario_pack, "dependency_mastery")
                self.assertEqual(card.status, "needs_primer")
                self.assertEqual(card.files_to_touch, [])
                self.assertIn("verified import, call, or declaration", card.return_with)

        self.assertEqual(provider.calls, 0)

    def test_new_pack_catalog_fallback_stays_deterministic_and_bilingual(self) -> None:
        with patch(
            "app.training.card_generator._load_guided_scenario_pack_catalog", return_value={}
        ):
            resource_card = CardGenerationService().generate_card(
                "resource_knowledge",
                _ctx(
                    resource_id="resource-httpx-timeouts",
                    focus_area="httpx timeout behavior",
                    context_hint="Indexed timeout documentation.",
                    resource_trust_state="trusted",
                    resource_knowledge_evidence=_resource_evidence("resource-httpx-timeouts"),
                    card_type="practice",
                    response_language="zh-CN",
                ),
            )
            dependency_card = CardGenerationService().generate_card(
                "dependency_mastery",
                _ctx(
                    target_skill="httpx.Client API",
                    context_hint="Existing request path uses httpx.Client.",
                    dependency_usage_evidence=_dependency_evidence("httpx"),
                    card_type="flash",
                ),
            )

        self.assertEqual(resource_card.scenario_pack, "resource_knowledge")
        self.assertEqual(resource_card.status, "candidate")
        self.assertTrue(_contains_chinese(resource_card.title))
        self.assertEqual(dependency_card.scenario_pack, "dependency_mastery")
        self.assertEqual(dependency_card.status, "candidate")
        self.assertIn("Dependency/API safe usage", dependency_card.title)


class TestLLMConversationGap(unittest.TestCase):
    """conversation_gap with mock LLM produces enriched practice card."""

    def test_card_generation_reserves_a_structured_output_budget(self) -> None:
        class _BudgetRecordingProvider:
            def __init__(self) -> None:
                self.max_tokens: list[int | None] = []

            async def chat_completion(
                self,
                messages: list[dict[str, str]],
                model: str | None = None,
                temperature: float = 0.7,
                max_tokens: int | None = None,
            ) -> str:
                del messages, model, temperature
                self.max_tokens.append(max_tokens)
                return json.dumps(_flash_llm_response())

        provider = _BudgetRecordingProvider()
        card = CardGenerationService(provider_service=provider).generate_card(
            "conversation_gap",
            _ctx(
                card_type="flash",
                focus_area="decorators",
                target_skill="python decorators",
            ),
        )

        self.assertEqual(card.card_type, "flash")
        self.assertEqual(provider.max_tokens, [2048])

    def test_llm_practice_card_fields(self) -> None:
        svc = CardGenerationService(provider_service=_MockProviderService(_practice_llm_response()))
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="async patterns",
                target_skill="async error handling",
            ),
        )
        self.assertEqual(card.card_type, "practice")
        self.assertEqual(card.title, "Practice: Async Error Handling")
        self.assertTrue(card.scenario)
        self.assertTrue(card.problem_statement)
        self.assertEqual(len(card.api_hints), 2)
        self.assertTrue(card.deliverable)
        self.assertEqual(len(card.self_check), 2)
        self.assertEqual(len(card.grading_rubric), 2)
        self.assertTrue(card.stuck_recovery)
        self.assertTrue(card.reflection_prompt)
        self.assertEqual(len(card.learner_deliverables), 2)
        self.assertEqual(len(card.verification_steps), 2)
        self.assertEqual(
            card.success_signal, "One failing request no longer crashes the whole concurrent batch."
        )
        self.assertTrue(card.return_with)
        self.assertTrue(card.next_after_completion)

    def test_llm_fallback_on_bad_json(self) -> None:
        """A live provider parse failure must not persist a generic template card."""
        bad_provider = _MockProviderService({"not": "a valid card"})
        svc = CardGenerationService(provider_service=bad_provider)
        with self.assertRaises(CardGenerationProviderFailure) as raised:
            svc.generate_card("conversation_gap", _ctx(focus_area="testing"))
        self.assertEqual(raised.exception.reason, "missing_required_fields")

    def test_llm_english_prose_falls_back_for_zh_cn_card(self) -> None:
        svc = CardGenerationService(provider_service=_MockProviderService(_practice_llm_response()))

        with self.assertRaises(CardGenerationProviderFailure) as raised:
            svc.generate_card(
                "conversation_gap",
                _ctx(
                    response_language="zh-CN",
                    focus_area="async patterns",
                    target_skill="async error handling",
                ),
            )
        self.assertEqual(raised.exception.reason, "language_mismatch")


class TestLLMPlanRequirement(unittest.TestCase):
    """plan_requirement with mock LLM produces enriched flash card."""

    def test_llm_flash_card_fields(self) -> None:
        svc = CardGenerationService(provider_service=_MockProviderService(_flash_llm_response()))
        card = svc.generate_card(
            "plan_requirement",
            _ctx(
                target_skill="python decorators",
                plan_stage_id="stage-1",
                card_type="flash",
            ),
        )
        self.assertEqual(card.card_type, "flash")
        self.assertEqual(card.title, "Flash: Python Decorators")
        self.assertEqual(card.knowledge_type, "engineering_concept")
        self.assertTrue(card.question)
        self.assertTrue(card.expected_answer)
        self.assertTrue(card.problem_statement)
        self.assertTrue(card.learner_deliverables)
        self.assertTrue(card.verification_steps)
        self.assertTrue(card.return_with)
        self.assertTrue(card.next_after_completion)
        self.assertEqual(len(card.hint_ladder), 2)
        self.assertEqual(len(card.common_mistakes), 2)
        self.assertIn("stage-1", card.plan_links)

    def test_llm_flash_card_has_feedback(self) -> None:
        svc = CardGenerationService(provider_service=_MockProviderService(_flash_llm_response()))
        card = svc.generate_card(
            "plan_requirement",
            _ctx(target_skill="decorators", card_type="flash"),
        )
        self.assertIn("correct", card.feedback)
        self.assertIn("incorrect", card.feedback)


class TestGovernedResourceKnowledge(unittest.TestCase):
    """Verified resource content can be taught; missing evidence still blocks model generation."""

    def test_resource_flash_card_uses_a_successful_provider_with_verified_content(self) -> None:
        provider = _RecordingMockProviderService(_flash_llm_response())
        card = CardGenerationService(provider_service=provider).generate_card(
            "resource_knowledge",
            _ctx(
                resource_id="resource-decorators",
                resource_trust_state="trusted",
                resource_knowledge_evidence=_resource_evidence(
                    "resource-decorators",
                    focus_area="decorator ordering",
                    summary="Decorator order changes which wrapper receives the call.",
                ),
                card_type="flash",
            ),
        )
        self.assertEqual(card.card_type, "flash")
        self.assertEqual(card.status, "candidate")
        self.assertTrue(card.question)
        self.assertTrue(card.expected_answer)
        self.assertTrue(card.hint_ladder)
        self.assertEqual(card.question, _flash_llm_response()["question"])
        self.assertIn(
            "Decorator order changes which wrapper receives the call.",
            provider.messages[0]["content"],
        )
        self.assertEqual(provider.calls, 1)

    def test_resource_flash_without_evidence_stays_needs_primer(self) -> None:
        provider = _RecordingMockProviderService(_flash_llm_response())
        card = CardGenerationService(provider_service=provider).generate_card(
            "resource_knowledge",
            _ctx(
                resource_id="resource-api-design",
                resource_trust_state="trusted",
                focus_area="API design",
                card_type="flash",
            ),
        )
        self.assertEqual(card.card_type, "flash")
        self.assertEqual(card.status, "needs_primer")
        self.assertIn("trusted indexed resource fragment", card.return_with)
        self.assertEqual(provider.calls, 0)


class TestLLMPracticeFeedback(unittest.TestCase):
    """practice_feedback with mock LLM produces enriched practice card."""

    def test_llm_practice_feedback_card(self) -> None:
        svc = CardGenerationService(provider_service=_MockProviderService(_practice_llm_response()))
        card = svc.generate_card(
            "practice_feedback",
            _ctx(
                focus_area="async patterns",
                card_type="practice",
            ),
        )
        self.assertEqual(card.card_type, "practice")
        self.assertTrue(card.scenario)
        self.assertTrue(card.deliverable)
        self.assertTrue(card.self_check)
        self.assertTrue(card.grading_rubric)
        self.assertTrue(card.stuck_recovery)
        self.assertTrue(card.reflection_prompt)

    def test_practice_feedback_template_fallback(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "practice_feedback",
            _ctx(
                focus_area="refactoring",
                card_type="practice",
            ),
        )
        self.assertEqual(card.card_type, "practice")
        self.assertTrue(card.scenario)
        self.assertTrue(card.deliverable)
        self.assertTrue(card.api_hints)
        self.assertTrue(card.self_check)
        self.assertTrue(card.grading_rubric)
        self.assertTrue(card.stuck_recovery)
        self.assertTrue(card.reflection_prompt)


class TestGovernedDependencyMastery(unittest.TestCase):
    """dependency_mastery remains deterministic and evidence-gated even with a provider."""

    def test_dependency_flash_card_bypasses_a_successful_provider(self) -> None:
        provider = _RecordingMockProviderService(_flash_llm_response())
        card = CardGenerationService(provider_service=provider).generate_card(
            "dependency_mastery",
            _ctx(
                target_skill="typing",
                dependency_usage_evidence=_dependency_evidence("typing", path="src/types.py"),
                card_type="flash",
            ),
        )
        self.assertEqual(card.card_type, "flash")
        self.assertEqual(card.status, "candidate")
        self.assertTrue(card.knowledge_type)
        self.assertTrue(card.question)
        self.assertTrue(card.hint_ladder)
        self.assertTrue(card.feedback)
        self.assertEqual(provider.calls, 0)

    def test_dependency_catalog_fallback_uses_verified_usage(self) -> None:
        with patch(
            "app.training.card_generator._load_guided_scenario_pack_catalog", return_value={}
        ):
            card = CardGenerationService().generate_card(
                "dependency_mastery",
                _ctx(
                    target_skill="typing",
                    dependency_usage_evidence=_dependency_evidence("typing", path="src/types.py"),
                    card_type="flash",
                ),
            )
        self.assertEqual(card.card_type, "flash")
        self.assertEqual(card.status, "candidate")
        self.assertIn("Dependency/API safe usage", card.title)
        self.assertTrue(card.question)
        self.assertTrue(card.hint_ladder)
        self.assertTrue(card.common_mistakes)
        self.assertIn("correct", card.feedback)
        self.assertIn("incorrect", card.feedback)


class TestLLMReviewDue(unittest.TestCase):
    """review_due with mock LLM produces enriched card."""

    def test_llm_review_due_card(self) -> None:
        svc = CardGenerationService(provider_service=_MockProviderService(_flash_llm_response()))
        card = svc.generate_card(
            "review_due",
            _ctx(
                focus_area="decorators",
                card_type="flash",
            ),
        )
        self.assertEqual(card.card_type, "flash")
        self.assertTrue(card.question)
        self.assertTrue(card.expected_answer)
        self.assertTrue(card.hint_ladder)

    def test_review_due_template_fallback(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "review_due",
            _ctx(
                focus_area="closures",
                card_type="flash",
            ),
        )
        self.assertEqual(card.card_type, "flash")
        self.assertIn("Review", card.title)
        self.assertTrue(card.question)
        self.assertTrue(card.hint_ladder)
        self.assertTrue(card.common_mistakes)
        self.assertIn("correct", card.feedback)
        self.assertIn("incorrect", card.feedback)


class TestCardGenerationPrompts(unittest.TestCase):
    def test_practice_prompt_enforces_learn_first_state_flow(self) -> None:
        prompt = _build_prompt(
            _ctx(
                focus_area="VS Code remote SSH",
                target_skill="remote workspace boundary",
                response_language="zh-CN",
                context_hint="Coach request: teach the remote boundary before any quiz.",
            ),
            "conversation_gap",
            "practice",
        )
        self.assertIn("Learn -> Try -> Verify -> Reflect", prompt)
        self.assertIn("wrong choice changes the result", prompt)
        self.assertIn("specific starting state or input and the observable result", prompt)
        self.assertIn("Output valid JSON only", prompt)
        self.assertIn("Respond in zh-CN", prompt)

    def test_flash_prompt_prefers_grounded_understanding_over_trivia(self) -> None:
        prompt = _build_prompt(
            _ctx(
                focus_area="signature help",
                target_skill="function contract reading",
                response_language="en-US",
                card_type="flash",
            ),
            "resource_knowledge",
            "flash",
        )
        self.assertIn("test real understanding, not detached trivia", prompt)
        self.assertIn("Learn -> Verify -> Reflect -> Return", prompt)
        self.assertIn("one misconception that matters most", prompt)
        self.assertIn("one short question in everyday language", prompt)
        self.assertIn('"next_after_completion": string', prompt)
        self.assertIn("Match the learner's active language", prompt)


class TestCardGenerationJsonParsing(unittest.TestCase):
    def test_parse_llm_json_accepts_think_block_wrapped_json(self) -> None:
        raw = """
<think>
reasoning that should never reach the parser
</think>
```json
{"title":"Flash: Boundary","focus_area":"remote","target_skill":"boundary"}
```
""".strip()
        parsed = _parse_llm_json(raw)
        assert parsed is not None, "think-block-wrapped JSON must parse"
        self.assertEqual(parsed["title"], "Flash: Boundary")

    def test_parse_llm_json_accepts_prose_wrapped_first_object(self) -> None:
        raw = """
Here is the card:
{"title":"Practice: One step","focus_area":"debug","target_skill":"debug loop"}
Use it carefully.
""".strip()
        parsed = _parse_llm_json(raw)
        assert parsed is not None, "prose-wrapped JSON must parse"
        self.assertEqual(parsed["focus_area"], "debug")

    def test_parse_llm_json_rejects_an_incomplete_object(self) -> None:
        self.assertIsNone(_parse_llm_json('{"title":"partial"'))


class _StallingStreamProvider:
    async def chat_completion_stream(self, *args, **kwargs):
        del args, kwargs
        await asyncio.sleep(30)
        yield ""


class TestCardGenerationStreamIdleFallback(unittest.TestCase):
    def test_stalled_stream_yields_a_marked_deterministic_fallback_card(self) -> None:
        service = CardGenerationService(provider_service=_StallingStreamProvider())

        async def collect():
            return [
                event
                async for event in service.generate_card_stream(
                    "conversation_gap",
                    _ctx(
                        workspace_id="ws-stream-stalled",
                        response_language="zh-CN",
                        focus_area="queue_lock.py exception safety",
                        target_skill="with self._lock / finally release",
                    ),
                )
            ]

        with patch(
            "app.training.card_generator._CARD_STREAM_IDLE_TIMEOUT_SECONDS",
            0.01,
        ):
            events = asyncio.run(collect())

        cards = [event.card for event in events if event.card is not None]
        self.assertEqual(len(cards), 1)
        card = cards[0]
        # generation_* provenance is an undeclared extra (extra="allow") attached via
        # model_copy in CardGenerationService._finalize_card, so read it via model_extra.
        provenance = card.model_extra
        assert provenance is not None, "candidate snapshots keep extras (extra=allow)"
        self.assertEqual(provenance["generation_source"], "deterministic_fallback")
        self.assertEqual(provenance["generation_fallback_reason"], "provider_stalled")
        self.assertEqual(provenance["generation_status"], "degraded")
        self.assertTrue(provenance["generation_recoverable"])
        self.assertIn("降级", card.why_now)


"""Tests for CardGenerationService — card_generation_router skeleton."""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if __name__ == "__main__":
    unittest.main()

# ---------------------------------------------------------------------------
# Restored from test_review_scheduler.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def contains_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def build_lane_snapshot(
    *,
    response_language: str = "en-US",
    latest_turn_summary: str = "Keep the startup thread narrow.",
    latest_turn_focus_area: str = "startup wiring",
    latest_turn_next_step: str = "Patch the config branch and rerun the focused check.",
):
    structured = StructuredMemoryService()
    structured.update_workspace(
        latest_turn_summary=latest_turn_summary,
        latest_turn_focus_area=latest_turn_focus_area,
        latest_turn_next_step=latest_turn_next_step,
        latest_coach_review_note="The config branch still fails before boot completes.",
        review_cadence="active",
        review_reminder_mode="ahead",
        response_language=response_language,
        active_thread={
            "focus_area": latest_turn_focus_area,
            "next_step": latest_turn_next_step,
            "blocker": "The config branch still fails before boot completes.",
            "verified_result": "Boot succeeds until config load.",
        },
    )
    structured.update_mastery(
        latest_turn_focus_area, delta=0.15, confidence=0.7, review_after_days=1
    )
    structured.update_mastery("config validation", delta=0.05, confidence=0.6, review_after_days=3)
    structured.schedule_mastery_review(
        latest_turn_focus_area, next_review_at=utc_now() + timedelta(days=1)
    )
    structured.schedule_mastery_review(
        "config validation", next_review_at=utc_now() + timedelta(days=3)
    )
    structured.record_weakness(
        latest_turn_focus_area,
        "The config branch still fails before boot completes.",
        severity=3,
        review_after_days=1,
        context="server/app/bootstrap.py",
    )
    structured.add_reflection(
        "startup-checkpoint",
        "Re-state the boot boundary before widening scope.",
        ["Patch the config branch and rerun the focused check."],
    )
    return structured.snapshot()


def build_plan() -> LearningPlan:
    return LearningPlan(
        id="plan-review",
        title="Coach-first trainer",
        summary="Keep the current lane attached to one real patch.",
        stages=[
            PlanStage(
                id="stage-practice",
                title="Practice",
                goal="Deepen startup review rhythm",
                outcomes=["Land one visible startup patch"],
                status="active",
            )
        ],
        cadence="8 hours per week",
        current_stage_id="stage-practice",
    )


def test_review_scheduler_derives_due_ahead_and_digest_items() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot()
    plan = build_plan()
    weakness_records = [
        WeaknessRecord(
            concept="startup wiring",
            reason="The config branch still fails before boot completes.",
            severity=3,
            recurrence_count=2,
            latest_example="Patch the config branch and rerun the focused check.",
            last_seen_context="server/app/bootstrap.py",
            updated_at=utc_now(),
            next_review_at=utc_now() + timedelta(hours=12),
        )
    ]

    reviews = scheduler.derive_due_reviews(
        plan=plan,
        lane_snapshot=lane_snapshot,
        weakness_records=weakness_records,
    )

    assert reviews
    assert reviews[0].focus_area == "startup wiring"
    assert reviews[0].surface_mode in {"due", "ahead"}
    assert reviews[0].task_hint
    assert reviews[0].linked_context
    assert reviews[0].interval_days is not None
    assert any(item.source == "plan" for item in reviews)


def test_review_scheduler_review_rhythm_mentions_real_training_pressure() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot()
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[
            WeaknessRecord(
                concept="startup wiring",
                reason="The config branch still fails before boot completes.",
                severity=3,
                recurrence_count=2,
                latest_example="Patch the config branch and rerun the focused check.",
                last_seen_context="server/app/bootstrap.py",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    rhythm = scheduler.derive_review_rhythm(
        due_reviews=reviews,
        lane_snapshot=lane_snapshot,
    )

    assert "startup wiring" in rhythm.lower() or "startup wiring" in rhythm
    assert "code move" not in rhythm.lower()


def test_review_scheduler_remote_workspace_hints_stay_learn_first() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot(
        latest_turn_summary="Keep the remote boundary grounded in one real host fact.",
        latest_turn_focus_area="VS Code remote workspace",
        latest_turn_next_step="Verify one host label and the safe credential mode before editing.",
    )
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[
            WeaknessRecord(
                concept="VS Code remote workspace",
                reason="The remote boundary is still blurry.",
                severity=3,
                recurrence_count=2,
                latest_example="Verify one host label and the safe credential mode before editing.",
                last_seen_context="remote-ssh",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    assert reviews
    assert any("workspace boundary" in item.task_hint.lower() for item in reviews)
    assert all("code move" not in item.task_hint.lower() for item in reviews)


def test_review_scheduler_debug_loop_hints_stay_learn_first() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot(
        latest_turn_summary="Shrink the debug loop back to one trustworthy pause point.",
        latest_turn_focus_area="VS Code debug loop",
        latest_turn_next_step="Reproduce once, pause at the first state change, and inspect one value.",
    )
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[
            WeaknessRecord(
                concept="VS Code debug loop",
                reason="The learner keeps widening scope before the first breakpoint.",
                severity=3,
                recurrence_count=2,
                latest_example="Reproduce once, pause at the first state change, and inspect one value.",
                last_seen_context="launch.json",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    assert reviews
    assert any("debug loop" in item.task_hint.lower() for item in reviews)
    assert all("code move" not in item.task_hint.lower() for item in reviews)


def test_review_scheduler_function_guidance_hints_stay_learn_first() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot(
        latest_turn_summary="Read the function boundary before touching the module.",
        latest_turn_focus_area="VS Code function guidance",
        latest_turn_next_step="Anchor on one call site, then check hover, signature help, and definition.",
    )
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[
            WeaknessRecord(
                concept="VS Code function guidance",
                reason="The learner edits unfamiliar functions before reading the contract.",
                severity=3,
                recurrence_count=2,
                latest_example="Anchor on one call site, then check hover, signature help, and definition.",
                last_seen_context="src/app.ts",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    assert reviews
    assert any(
        "hover" in item.task_hint.lower() and "signature help" in item.task_hint.lower()
        for item in reviews
    )
    assert all("code move" not in item.task_hint.lower() for item in reviews)


def test_review_scheduler_prefers_explicit_en_us_over_chinese_workspace_text() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot(
        response_language="en-US",
        latest_turn_summary="先围绕 dependency injection 保持这一条主线。",
        latest_turn_focus_area="dependency injection",
        latest_turn_next_step="先把 provider branch 补成一个可验证的小改动。",
    )
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[
            WeaknessRecord(
                concept="dependency injection",
                reason="这里的 provider branch 还没有被验证。",
                severity=3,
                recurrence_count=2,
                latest_example="先把 provider branch 补成一个可验证的小改动。",
                last_seen_context="server/app/main.py",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    rhythm = scheduler.derive_review_rhythm(
        due_reviews=reviews,
        lane_snapshot=lane_snapshot,
    )

    assert reviews
    assert reviews[0].task_hint
    assert not contains_chinese(reviews[0].task_hint)
    assert rhythm.startswith("Review rhythm:")
    assert not contains_chinese(rhythm)


def test_review_scheduler_prefers_explicit_zh_cn_over_english_workspace_text() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot(
        response_language="zh-CN",
        latest_turn_summary="Keep the dependency injection lane narrow.",
        latest_turn_focus_area="dependency injection",
        latest_turn_next_step="Patch the provider branch and rerun the focused check.",
    )
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[
            WeaknessRecord(
                concept="dependency injection",
                reason="The provider branch still is not verified.",
                severity=3,
                recurrence_count=2,
                latest_example="Patch the provider branch and rerun the focused check.",
                last_seen_context="server/app/main.py",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    rhythm = scheduler.derive_review_rhythm(
        due_reviews=reviews,
        lane_snapshot=lane_snapshot,
    )

    assert reviews
    assert reviews[0].task_hint
    assert contains_chinese(reviews[0].task_hint)
    assert contains_chinese(rhythm)


def test_chinese_review_queue_drops_english_evaluator_prose() -> None:
    scheduler = ReviewScheduler()
    lane_snapshot = build_lane_snapshot(
        response_language="zh-CN",
        latest_turn_summary="Widen the scope only after the verified result is preserved.",
        latest_turn_next_step="Widen the scope only after the verified result is preserved.",
    )
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=lane_snapshot,
        weakness_records=[],
    )
    assert reviews
    for item in reviews:
        haystack = " ".join(
            str(getattr(item, field, "") or "")
            for field in ("concept", "reason", "task_hint", "focus_area", "linked_context")
        )
        assert "Widen the scope only after the verified result is preserved" not in haystack
    assert any("当前这一步" in item.task_hint or "当前这一步" in item.reason for item in reviews)


def test_language_safe_dynamic_value_falls_back_for_english_prose_in_chinese() -> None:
    scheduler = ReviewScheduler()
    assert (
        scheduler._language_safe_dynamic_value(
            "Widen the scope only after the verified result is preserved.",
            "zh-CN",
            fallback_english="the current next step",
            fallback_chinese="当前这一步",
        )
        == "当前这一步"
    )


def test_review_scheduler_skips_heuristic_mastery_without_recall_evidence() -> None:
    scheduler = ReviewScheduler()
    structured = StructuredMemoryService()
    structured.update_mastery("unrecalled concept", delta=0.2, review_after_days=1)
    snapshot = structured.snapshot()

    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=snapshot,
        weakness_records=[],
    )

    assert all(item.concept != "unrecalled concept" for item in reviews)


def test_later_score_update_preserves_the_fsrs_owned_due_date() -> None:
    structured = StructuredMemoryService()
    structured.update_mastery("fsrs concept", delta=0.2, review_after_days=1)
    due = utc_now() + timedelta(days=9)
    structured.schedule_mastery_review("fsrs concept", next_review_at=due)
    scheduled = structured._mastery["fsrs concept"]
    assert scheduled.review_source == "fsrs"
    assert scheduled.next_review_at == due

    structured.update_mastery("fsrs concept", delta=0.1, review_after_days=2)
    updated = structured._mastery["fsrs concept"]
    assert updated.review_source == "fsrs"
    assert updated.next_review_at == due
    assert updated.score == scheduled.score + 0.1


def test_due_items_mark_fsrs_recall_vs_no_recall_evidence() -> None:
    scheduler = ReviewScheduler()
    reviews = scheduler.derive_due_reviews(
        plan=build_plan(),
        lane_snapshot=build_lane_snapshot(),
        weakness_records=[
            WeaknessRecord(
                concept="startup wiring",
                reason="The config branch still fails before boot completes.",
                severity=3,
                recurrence_count=2,
                latest_example="Patch the config branch and rerun the focused check.",
                last_seen_context="server/app/bootstrap.py",
                updated_at=utc_now(),
                next_review_at=utc_now() + timedelta(hours=12),
            )
        ],
    )

    mastery_items = [item for item in reviews if item.source == "mastery"]
    assert mastery_items
    assert all(item.evidence_basis == "fsrs_recall" for item in mastery_items)
    assert all(
        item.evidence_basis == "no_recall_evidence" for item in reviews if item.source != "mastery"
    )


# ---------------------------------------------------------------------------
# Restored from test_review_scheduler_fsrs.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_review_scheduler_processes_fsrs_state_with_human_readable_state() -> None:
    scheduler = ReviewScheduler()
    mastery = MasteryRecord(
        concept="startup wiring",
        score=0.3,
        confidence=0.7,
        updated_at=utc_now() - timedelta(days=2),
        next_review_at=utc_now() - timedelta(hours=12),
        due_date=utc_now() - timedelta(hours=12),
    )

    updated = scheduler.process_mastery_review(mastery, ReviewRating.GOOD)

    assert updated.state in {"learning", "review", "relearning"}
    assert updated.next_review_at is not None
    assert updated.retrievability >= 0.0
    assert updated.review_source == "fsrs"
    assert updated.fsrs_reps >= 1


def test_fsrs_rating_changes_the_interval_not_a_fixed_table() -> None:
    scheduler = ReviewScheduler()
    mastery = MasteryRecord(
        concept="retry budget",
        score=0.3,
        confidence=0.6,
        updated_at=utc_now() - timedelta(days=1),
        next_review_at=utc_now() - timedelta(days=1),
        due_date=utc_now() - timedelta(days=1),
    )

    again = scheduler.process_mastery_review(mastery, ReviewRating.AGAIN)
    good = scheduler.process_mastery_review(mastery, ReviewRating.GOOD)

    assert again.review_source == good.review_source == "fsrs"
    assert again.next_review_at is not None and good.next_review_at is not None
    assert again.next_review_at < good.next_review_at


# ---------------------------------------------------------------------------
# Restored from test_training_fsrs_scheduler.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_process_review_reports_elapsed_time_before_refresh() -> None:
    scheduler = FSRSTrainerCardScheduler()
    card = scheduler.create_card("card-1", "concept-1")
    previous_review = datetime.now(timezone.utc) - timedelta(days=2)
    card.last_reviewed_at = previous_review
    card.due = previous_review + timedelta(hours=12)

    result = scheduler.process_review("card-1", TrainingRating.GOOD)

    assert result.elapsed_days == pytest.approx(2.0, abs=0.05)
    assert result.new_interval >= 0
