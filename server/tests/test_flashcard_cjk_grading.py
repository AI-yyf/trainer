"""Open-answer grading preserves assessment and uncertainty for CJK recall."""

from __future__ import annotations

from pathlib import Path

from app.core.models import TrainingCardCandidateSnapshot
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService
from app.training.flashcard_grading import RecallAssessment


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
