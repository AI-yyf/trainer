from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import CardGenerationContext
from app.training.card_generator import CardGenerationService
from app.training.subject_taxonomy import LearningSubject, classify_learning_subject


def _ctx(**overrides: object) -> CardGenerationContext:
    defaults = {
        "workspace_id": "ws-test",
        "source": "plan_requirement",
        "card_type": "practice",
        "context_hint": "",
        "target_skill": "",
        "focus_area": "",
        "plan_stage_id": "",
    }
    defaults.update(overrides)
    return CardGenerationContext(**defaults)  # type: ignore[arg-type]


class TestSubjectTaxonomy(unittest.TestCase):
    def test_sse_routes_to_code_implementation(self) -> None:
        subject = classify_learning_subject("SSE", "server-sent events", "streaming response")
        self.assertEqual(subject, LearningSubject("code", "implementation"))

    def test_engineering_practice_routes_to_code_implementation(self) -> None:
        subject = classify_learning_subject("engineering practice", "implementation slice")
        self.assertEqual(subject, LearningSubject("code", "implementation"))


class TestPlanRequirementCardGeneration(unittest.TestCase):
    def test_sse_practice_card_uses_code_lane_language(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "plan_requirement",
            _ctx(
                focus_area="SSE server-sent events engineering practice",
                target_skill="streaming response handling",
                card_type="practice",
            ),
        )

        self.assertEqual(card.card_type, "practice")
        self.assertIn("implementation slice", card.problem_statement.lower())
        self.assertIn("narrow change", card.suggested_workspace_action.lower())
        self.assertIn("patch", card.deliverable.lower())
        self.assertNotIn("worked step", card.problem_statement.lower())
        self.assertNotIn("proof", card.deliverable.lower())

    def test_sse_completion_event_does_not_select_function_guidance_pack(self) -> None:
        svc = CardGenerationService()
        card = svc.generate_card(
            "conversation_gap",
            _ctx(
                focus_area="SSE server-sent events",
                target_skill="streaming response handling",
                context_hint=(
                    "API configuration, first-chunk latency, incremental chunks, "
                    "completion event, failure recovery"
                ),
                response_language="en-US",
            ),
        )

        self.assertNotEqual(card.scenario_pack, "function_guidance")
        self.assertEqual(card.learning_family, "code")
        self.assertEqual(card.learning_subtype, "implementation")
        self.assertEqual(card.expected_symbols, [])
        self.assertIn("SSE", card.title)
