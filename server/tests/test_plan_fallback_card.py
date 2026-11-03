from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.core.models import CardGenerationContext
from app.evaluator.service import EvaluatorService
from app.training.card_generator import CardGenerationService

QUEUE_LOCK_CODE = '''"""Lock-protected queue practice."""

import threading


class Queue:
    def __init__(self):
        self._items = []
        self._lock = threading.Lock()

    def push(self, item):
        with self._lock:
            self._items.append(item)

    def pop(self):
        with self._lock:
            if not self._items:
                raise IndexError("empty")
            return self._items.pop(0)

    def try_pop(self):
        self._lock.acquire()
        try:
            if not self._items:
                raise IndexError("empty")
            return self._items.pop(0)
        finally:
            self._lock.release()
'''


def _plan_context() -> CardGenerationContext:
    return CardGenerationContext(
        workspace_id="ws-plan-fallback",
        response_language="zh-CN",
        card_type="practice",
        plan_stage_id="stage-lock",
        plan_binding={
            "planId": "plan-lock",
            "stageId": "stage-lock",
            "step": "在 queue_lock.py 中标出 with self._lock 的进入、退出和异常路径",
            "revision": 3,
        },
        focus_area="验证异常释放",
        target_skill="证明 with/finally 在异常路径释放锁",
        current_file_path="src/queue_lock.py",
        current_file_language_id="python",
        current_file_content=QUEUE_LOCK_CODE,
    )


def test_plan_fallback_card_uses_real_file_symbols_and_passes_acceptance() -> None:
    card = CardGenerationService(provider_service=None).generate_card(
        "plan_requirement",
        _plan_context(),
        allow_llm=False,
        fallback_reason="provider_stalled",
    )

    assert card.plan_links == ["stage-lock"]
    assert card.files_to_touch == ["queue_lock.py"]
    assert {"self._lock", "acquire", "release", "finally"} <= set(card.expected_symbols)
    assert all("`" in criterion for criterion in card.acceptance_criteria)
    assert card.generation_status == "degraded"
    assert card.generation_fallback_reason == "provider_stalled"
    assert card.generation_recoverable is True

    check = EvaluatorService()._training_acceptance_check(
        source="training",
        code=QUEUE_LOCK_CODE,
        language_id="python",
        acceptance_criteria=card.acceptance_criteria,
        learner_deliverables=[],
        expected_symbols=card.expected_symbols,
        execution_passed=False,
    )
    assert check is not None
    assert check.status == "passed", check.detail
    assert "7/7 acceptance signals matched" in check.detail


class _StallingStreamProvider:
    async def chat_completion_stream(self, *args, **kwargs):
        del args, kwargs
        await asyncio.sleep(30)
        yield ""


def test_stalled_plan_stream_falls_back_to_the_plan_card() -> None:
    service = CardGenerationService(provider_service=_StallingStreamProvider())

    async def collect():
        return [
            event
            async for event in service.generate_card_stream(
                "plan_requirement",
                _plan_context(),
            )
        ]

    with patch(
        "app.training.card_generator._CARD_STREAM_IDLE_TIMEOUT_SECONDS",
        0.01,
    ):
        events = asyncio.run(collect())

    cards = [event.card for event in events if event.card is not None]
    assert len(cards) == 1
    card = cards[0]
    assert card.plan_links == ["stage-lock"]
    assert card.generation_fallback_reason == "provider_stalled"
    assert card.files_to_touch == ["queue_lock.py"]
    assert "`self._lock`" in card.acceptance_criteria[0]


class _PartialThenFailingProvider:
    async def chat_completion_stream(self, *args, **kwargs):
        del args, kwargs
        yield '{"title": "partial'
        raise RuntimeError("upstream reset")


def test_partial_stream_still_fails_honestly_instead_of_faking_a_card() -> None:
    service = CardGenerationService(provider_service=_PartialThenFailingProvider())

    async def collect():
        return [
            event
            async for event in service.generate_card_stream(
                "plan_requirement",
                _plan_context(),
            )
        ]

    try:
        asyncio.run(collect())
    except Exception as exc:  # noqa: BLE001 - the stream error type is the assertion
        assert "plan_requirement" in str(exc) or "card" in str(exc).lower()
    else:
        raise AssertionError("partial provider text must not be replaced by a fallback card")


def test_statement_symbol_and_reflection_evidence_pass_the_model_card_contract() -> None:
    check = EvaluatorService()._training_acceptance_check(
        source="training",
        code=QUEUE_LOCK_CODE,
        language_id="python",
        acceptance_criteria=[
            "使用 `with self._lock` 标出进入、正常退出和异常退出边界。",
            "通过 `self._lock` 的再次获取结果证明异常发生后锁已释放。",
            "定义 `self._lock` 异常退出时必须保留的上下文管理器释放路径。",
            "通过 `queue_lock.py` 的 Debug Console 或测试输出记录异常传播与释放证据。",
        ],
        learner_deliverables=[],
        expected_symbols=["self._lock", "with self._lock"],
        execution_passed=False,
    )
    assert check is not None
    assert check.status == "passed", check.detail
    assert "5/6 acceptance signals matched" in check.detail
    assert "Deferred to reflection" in check.detail
