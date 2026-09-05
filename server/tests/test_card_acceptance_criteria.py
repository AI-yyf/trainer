"""Tests for symbol-anchored acceptance criteria on generated training cards.

Goal F2: every generated card must carry acceptance_criteria that can pass the
training-acceptance check in ``app/evaluator/service.py`` — each criterion
needs at least one "verifiable code symbol" (a backticked literal such as
``asyncio.gather`` or a snake_case/camelCase identifier) that can appear in the
learner's submitted code. Free-form prose criteria structurally never pass.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import CardGenerationContext, TrainingCardCandidateSnapshot
from app.training.card_generator import (
    CardGenerationService,
    _build_prompt,
    derive_acceptance_criteria,
)

# --- Mini replica of the evaluator's signal rule (app/evaluator/service.py) ---

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


# --- Fixtures ----------------------------------------------------------------


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


# --- Tests -------------------------------------------------------------------


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


if __name__ == "__main__":
    unittest.main()
