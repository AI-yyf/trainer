"""Open-answer grading preserves assessment and uncertainty for CJK recall."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from app.core.models import TrainingCardCandidateSnapshot
from app.db.repository import TrainerRepository
from app.llm.provider_service import ProviderService
from app.memory.service import MemoryService
from app.training.flashcard_grading import RecallAssessment, assess_open_recall


def _flash_card(card_id: str, expected_answer: str) -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type="flash",
        title="Event loop",
        target_skill="event loop",
        expected_answer=expected_answer,
        answer_mode="text",
        status="candidate",
    )


def test_cjk_paraphrase_keeps_the_model_assessment(tmp_path: Path) -> None:
    workspace_id = "ws-cjk-flash-paraphrase"
    service = MemoryService(TrainerRepository(tmp_path / "cjk-paraphrase.db"))
    card = service.upsert_card(
        workspace_id,
        _flash_card("card-cjk-paraphrase", "事件循环是调度协程执行的核心机制"),
    )

    attempt = service.submit_flashcard_answer(
        workspace_id,
        card.card_id,
        learner_answer="事件循环负责调度协程的执行",
        assessment=RecallAssessment("correct", "正确解释了调度职责。", "调度协程的执行", "test"),
    )

    assert attempt.correct is True
    assert attempt.score == 1.0
    assert attempt.feedback["correct"] is True
    assert attempt.feedback["assessment"]["quote"] == "调度协程的执行"


def test_cjk_contradiction_with_high_similarity_stays_unconfirmed_without_model(tmp_path: Path) -> None:
    workspace_id = "ws-cjk-flash-unrelated"
    service = MemoryService(TrainerRepository(tmp_path / "cjk-unrelated.db"))
    card = service.upsert_card(
        workspace_id,
        _flash_card("card-cjk-unrelated", "事件循环是调度协程执行的核心机制"),
    )

    attempt = service.submit_flashcard_answer(
        workspace_id,
        card.card_id,
        learner_answer="事件循环不是调度协程执行的核心机制",
    )

    assert attempt.correct is None
    assert attempt.score is None
    assert attempt.feedback["grading_source"] == "ungraded"


def test_english_exact_match_is_unchanged(tmp_path: Path) -> None:
    workspace_id = "ws-cjk-flash-english"
    service = MemoryService(TrainerRepository(tmp_path / "cjk-english.db"))
    expected = "An event loop schedules coroutine execution"
    card = service.upsert_card(workspace_id, _flash_card("card-cjk-english", expected))

    attempt = service.submit_flashcard_answer(workspace_id, card.card_id, learner_answer=expected)

    assert attempt.correct is True
    assert attempt.score == 1.0


def test_english_nonmatch_is_unconfirmed_without_model(tmp_path: Path) -> None:
    workspace_id = "ws-cjk-flash-mixed"
    service = MemoryService(TrainerRepository(tmp_path / "cjk-mixed.db"))
    english = service.upsert_card(
        workspace_id,
        _flash_card("card-mixed-english", "An event loop schedules coroutine execution"),
    )
    wrong = service.submit_flashcard_answer(
        workspace_id,
        english.card_id,
        learner_answer="A quicksort partitions the array",
    )
    assert wrong.correct is None
    assert wrong.score is None


async def test_numeric_check_can_veto_a_model_pass_only_for_a_learner_claim() -> None:
    provider = Mock(spec=ProviderService, has_api_key=True, configured_model="test")
    provider.recommended_generation_max_tokens.return_value = 4096
    provider.chat_completion = AsyncMock()
    card = _flash_card("card-numeric", "Multiplication by a negative reverses the order.")
    answer = "For a negative multiplier, (1-eps)*A > r*A. The lower bound is used."
    verdict = {
        "verdict": "correct", "reason": "The lower bound is used.", "quote": "The lower bound is used.",
    }
    contradiction = {"quote": "(1-eps)*A > r*A", "left": -0.8, "right": -0.5}
    provider.chat_completion.return_value = json.dumps({**verdict, "numeric_checks": [contradiction]})
    unresolved = await assess_open_recall(provider, card, answer, language="en-US")
    assert unresolved is not None and unresolved.verdict == "uncertain"
    assert unresolved.quote == contradiction["quote"]

    invented_check = {**contradiction, "quote": "(1-eps)*A >= r*A"}
    provider.chat_completion.return_value = json.dumps({**verdict, "numeric_checks": [invented_check]})
    assessment = await assess_open_recall(provider, card, answer, language="en-US")
    assert assessment is not None and assessment.verdict == "correct"
