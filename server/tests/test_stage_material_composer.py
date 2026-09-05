"""Tests for StageMaterialComposer and the principle explainer asset facade."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pedagogy.stage_material_composer import (
    StageMaterialComposer,
    compose_principle_explainer_asset,
)

_MATERIAL_KINDS = ("study_guide", "cheat_sheet", "exercise_set", "code_examples")

_COMPOSE_KWARGS: dict[str, Any] = {
    "workspace_id": "ws-stage",
    "plan_title": "Plan: HTTPX mastery",
    "stage_id": "stage-1",
    "stage_title": "Timeouts and retries",
    "stage_goal": "Understand connect vs read timeouts.",
    "stage_outcomes": ["outcome-a", "outcome-b"],
    "stage_exercises": ["exercise-a"],
}


class _ScriptedProvider:
    """Fake provider returning the same payload on every chat_completion call."""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls = 0
        self.temperatures: list[float] = []

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        self.calls += 1
        self.temperatures.append(temperature)
        return self.payload


def _llm_material(kind: str, title: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "title": title,
        "summary": f"Summary of {title}",
        "content": f"Full content for {title}",
        "sources": ["Indexed resource A"],
    }


def _valid_materials_payload() -> str:
    return json.dumps(
        {
            "materials": [
                _llm_material("study_guide", "LLM study guide"),
                _llm_material("cheat_sheet", "LLM cheat sheet"),
                _llm_material("exercise_set", "LLM exercise set"),
                _llm_material("code_examples", "LLM code examples"),
            ],
        },
    )


class TestStageMaterialComposerFallback(unittest.TestCase):
    """Without a provider the composer must produce deterministic templates."""

    def test_provider_none_returns_four_fallback_assets(self) -> None:
        composer = StageMaterialComposer(provider_service=None)
        assets = asyncio.run(composer.compose_stage_materials(**_COMPOSE_KWARGS))

        self.assertEqual(len(assets), 4)
        self.assertEqual({asset.kind for asset in assets}, set(_MATERIAL_KINDS))
        for asset in assets:
            self.assertEqual(asset.plan_stage_id, "stage-1")
            self.assertEqual(asset.workspace_id, "ws-stage")
            self.assertEqual(asset.scope, "project")
            self.assertEqual(asset.source_ids, ["plan_stage:stage-1"])
            self.assertTrue(asset.title.strip())
            content = asset.concept_card or asset.example or asset.exercise_seed
            self.assertTrue(content.strip())
            if asset.kind == "exercise_set":
                self.assertIn("exercise-a", content)
            elif asset.kind == "code_examples":
                self.assertIn("Understand connect vs read timeouts.", content)
            else:
                self.assertIn("outcome-a", content)

    def test_fallback_reflects_stage_language(self) -> None:
        composer = StageMaterialComposer(provider_service=None)
        assets = asyncio.run(
            composer.compose_stage_materials(**_COMPOSE_KWARGS, response_language="zh-CN"),
        )
        study_guide = next(asset for asset in assets if asset.kind == "study_guide")
        self.assertIn("学习指南", study_guide.title)


class TestStageMaterialComposerLLM(unittest.TestCase):
    """With a provider the composer should use the LLM payload verbatim."""

    def test_valid_llm_payload_becomes_assets_without_fallback_marker(self) -> None:
        provider = _ScriptedProvider(_valid_materials_payload())
        composer = StageMaterialComposer(provider_service=provider)
        assets = asyncio.run(composer.compose_stage_materials(**_COMPOSE_KWARGS))

        self.assertEqual(provider.calls, 1)
        self.assertEqual(provider.temperatures, [0.7])
        self.assertEqual(len(assets), 4)
        titles = {asset.title for asset in assets}
        self.assertIn("LLM study guide", titles)
        self.assertIn("LLM code examples", titles)
        for asset in assets:
            self.assertNotIn("stage-material-fallback", asset.tags)
        guide = next(asset for asset in assets if asset.kind == "study_guide")
        self.assertEqual(guide.concept_card, "Full content for LLM study guide")
        self.assertEqual(guide.evidence_snippets, ["Indexed resource A"])

    def test_invalid_materials_are_dropped(self) -> None:
        payload = json.dumps(
            {
                "materials": [
                    _llm_material("study_guide", "Kept guide"),
                    _llm_material("unknown_kind", "Dropped unknown kind"),
                    {"kind": "cheat_sheet", "title": "Dropped empty content", "content": "  "},
                ],
            },
        )
        provider = _ScriptedProvider(payload)
        composer = StageMaterialComposer(provider_service=provider)
        assets = asyncio.run(composer.compose_stage_materials(**_COMPOSE_KWARGS))

        self.assertEqual([asset.kind for asset in assets], ["study_guide"])
        self.assertEqual(assets[0].title, "Kept guide")

    def test_garbage_json_retries_once_then_falls_back(self) -> None:
        provider = _ScriptedProvider("this is not json at all {")
        composer = StageMaterialComposer(provider_service=provider)
        assets = asyncio.run(composer.compose_stage_materials(**_COMPOSE_KWARGS))

        self.assertEqual(provider.calls, 2)
        self.assertEqual(provider.temperatures, [0.7, 0.9])
        self.assertEqual(len(assets), 4)
        self.assertEqual({asset.kind for asset in assets}, set(_MATERIAL_KINDS))
        for asset in assets:
            self.assertIn("stage-material-fallback", asset.tags)


class TestComposePrincipleExplainerAsset(unittest.TestCase):
    """The deterministic facade should map PrincipleNote into a concept asset."""

    def test_returns_non_empty_concept_card_asset(self) -> None:
        asset = compose_principle_explainer_asset(
            workspace_id="ws-stage",
            principle="Small verifiable steps",
            context="Learner is refactoring an HTTP client timeout path.",
            focus_area="httpx timeouts",
        )

        self.assertEqual(asset.kind, "concept_card")
        self.assertEqual(asset.plan_stage_id, "")
        self.assertEqual(asset.origin, "manual")
        self.assertEqual(asset.workspace_id, "ws-stage")
        self.assertEqual(asset.title, "Small verifiable steps")
        self.assertTrue(asset.concept_card.strip())
        self.assertTrue(asset.summary.strip())
        self.assertTrue(asset.why_it_matters.strip())
        self.assertTrue(asset.example.strip())


if __name__ == "__main__":
    unittest.main()
