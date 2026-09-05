"""Tests for submit_flashcard_answer: real grading, status transition, and mastery update."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import TrainingCardCandidateSnapshot
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService


def _make_flash_card(
    card_id: str = "flash-001",
    expected_answer: str = "flex-direction: column",
    question: str = "CSS Flexbox: How do you stack children vertically?",
    options: list[str] | None = None,
    correct_option_index: int | None = None,
    answer_mode: str | None = None,
    correct_option_indices: list[int] | None = None,
    correct_sort_order: list[int] | None = None,
    fill_blank_answers: dict[str, str] | None = None,
    status: str = "active",
) -> TrainingCardCandidateSnapshot:
    card = TrainingCardCandidateSnapshot(
        card_id=card_id,
        title=question[:40],
        card_type="flash",
        status=status,
        expected_answer=expected_answer,
        question=question,
        focus_area="css-flexbox",
        target_skill="flex-direction",
        answer_mode=answer_mode or ("single_choice" if options is not None else "text"),
        correct_option_indices=correct_option_indices or [],
        correct_sort_order=correct_sort_order or [],
        fill_blank_answers=fill_blank_answers or {},
    )
    if options is not None:
        card.options = options
    if correct_option_index is not None:
        card.correct_option_index = correct_option_index
    return card


def _cleanup_db(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


class FlashcardAnswerUnitTests(unittest.TestCase):
    """Verify submit_flashcard_answer uses real grading and transitions status."""

    def setUp(self) -> None:
        db_path = Path(f".tmp-test/flashcard-answer-{id(self)}.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _cleanup_db(db_path)
        self.repository = TrainerRepository(db_path)
        self.service = MemoryService(self.repository)
        self.ws = "ws-flash-test"

    def tearDown(self) -> None:
        for p in Path(".tmp-test").rglob(f"flashcard-answer-{id(self)}*"):
            _cleanup_db(p)

    # ---------- Scenario 1: Correct text answer ----------
    def test_correct_text_answer_marks_correct_and_transitions(self) -> None:
        card = _make_flash_card(expected_answer="flex-direction: column")
        self.service.upsert_card(self.ws, card)
        result = self.service.submit_flashcard_answer(
            self.ws, card.card_id, "flex-direction: column"
        )
        self.assertTrue(result.correct)
        updated = self.service.get_card(self.ws, card.card_id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "answered")  # Must transition

    # ---------- Scenario 2: Wrong text answer ----------
    def test_wrong_text_answer_marks_incorrect_and_transitions(self) -> None:
        card = _make_flash_card(expected_answer="flex-direction: column")
        self.service.upsert_card(self.ws, card)
        result = self.service.submit_flashcard_answer(
            self.ws, card.card_id, "display: block"
        )
        self.assertFalse(result.correct)
        updated = self.service.get_card(self.ws, card.card_id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "needs_primer")
        self.assertEqual(result.feedback["retry_required"], True)

    def test_long_unrelated_text_does_not_pass(self) -> None:
        card = _make_flash_card(expected_answer="flex-direction: column")
        self.service.upsert_card(self.ws, card)
        result = self.service.submit_flashcard_answer(
            self.ws,
            card.card_id,
            "This is a long answer about browser colors and typography, not the requested layout rule.",
        )
        self.assertFalse(result.correct)

    def test_weak_token_overlap_does_not_pass(self) -> None:
        card = _make_flash_card(expected_answer="configure the request timeout policy")
        self.service.upsert_card(self.ws, card)
        result = self.service.submit_flashcard_answer(
            self.ws,
            card.card_id,
            "The request should use a retry policy.",
        )
        self.assertFalse(result.correct)
        self.assertEqual(result.feedback["retry_required"], True)

    # ---------- Scenario 3: Empty answer is wrong ----------
    def test_empty_answer_is_wrong(self) -> None:
        card = _make_flash_card(expected_answer="flex-direction: column")
        self.service.upsert_card(self.ws, card)
        result = self.service.submit_flashcard_answer(self.ws, card.card_id, "")
        self.assertFalse(result.correct)

    # ---------- Scenario 4: Single choice correct ----------
    def test_single_choice_correct(self) -> None:
        card = _make_flash_card(
            expected_answer="B",
            options=["display: grid", "flex-direction: column", "position: absolute"],
            correct_option_index=1,
        )
        self.service.upsert_card(self.ws, card)
        result = self.service.submit_flashcard_answer(
            self.ws, card.card_id, "", selected_option_index=1
        )
        self.assertTrue(result.correct)
        updated = self.service.get_card(self.ws, card.card_id)
        self.assertEqual(updated.status, "answered")

    # ---------- Scenario 5: Single choice wrong ----------
    def test_single_choice_wrong(self) -> None:
        card = _make_flash_card(
            expected_answer="B",
            options=["display: grid", "flex-direction: column", "position: absolute"],
            correct_option_index=1,
        )
        self.service.upsert_card(self.ws, card)
        result = self.service.submit_flashcard_answer(
            self.ws, card.card_id, "", selected_option_index=0
        )
        self.assertFalse(result.correct)

    def test_multiple_choice_scores_only_when_all_expected_options_are_selected(self) -> None:
        card = _make_flash_card(
            answer_mode="multiple_choice",
            options=["GET", "POST", "PATCH"],
            correct_option_indices=[0, 2],
        )
        self.service.upsert_card(self.ws, card)
        partial = self.service.submit_flashcard_answer(
            self.ws, card.card_id, selected_option_indices=[0],
        )
        self.assertFalse(partial.correct)
        self.assertEqual(partial.score, 0.5)
        self.assertEqual(partial.feedback["mismatches"], ["missing_options"])

        self.service.upsert_card(self.ws, card.model_copy(update={"status": "active"}))
        complete = self.service.submit_flashcard_answer(
            self.ws, card.card_id, selected_option_indices=[2, 0],
        )
        self.assertTrue(complete.correct)
        self.assertEqual(complete.score, 1.0)

    def test_fill_blank_compares_each_answer_and_returns_structured_feedback(self) -> None:
        card = _make_flash_card(
            answer_mode="fill_blank",
            question="Use {{1}} to register {{2}}.",
            fill_blank_answers={"1": "router", "2": "middleware"},
        )
        self.service.upsert_card(self.ws, card)
        result = self.service.submit_flashcard_answer(
            self.ws,
            card.card_id,
            fill_blank_answers={"0": "router", "1": "middleware"},
        )
        self.assertTrue(result.correct)
        self.assertEqual(result.feedback["answer_mode"], "fill_blank")
        self.assertEqual(result.feedback["score"], 1.0)

    def test_sorting_requires_exact_order_but_reports_partial_score(self) -> None:
        card = _make_flash_card(
            answer_mode="sorting",
            options=["Define", "Implement", "Verify"],
            correct_sort_order=[0, 1, 2],
        )
        self.service.upsert_card(self.ws, card)
        result = self.service.submit_flashcard_answer(
            self.ws, card.card_id, sort_order=[0, 2, 1],
        )
        self.assertFalse(result.correct)
        self.assertAlmostEqual(result.score, 1 / 3, places=3)
        self.assertIn("sort_order", result.feedback["mismatches"])

    def test_true_false_uses_single_choice_contract(self) -> None:
        card = _make_flash_card(
            answer_mode="true_false",
            options=["True", "False"],
            correct_option_index=0,
        )
        self.service.upsert_card(self.ws, card)
        result = self.service.submit_flashcard_answer(
            self.ws, card.card_id, selected_option_index=0,
        )
        self.assertTrue(result.correct)
        self.assertEqual(result.answer_mode, "true_false")

    # ---------- Scenario 6: Adjacent-surface regression: card_id not found ----------
    def test_missing_card_returns_not_found(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self.service.submit_flashcard_answer(
                self.ws,
                "nonexistent-card",
                "This long answer must not create a successful attempt.",
            )
        self.assertEqual(raised.exception.status_code, 404)
        self.assertIn("Refresh Training", str(raised.exception.detail))

    # ---------- Scenario 7: Mastery update on correct ----------
    def test_correct_answer_updates_mastery(self) -> None:
        card = _make_flash_card(expected_answer="flex-direction: column")
        self.service.upsert_card(self.ws, card)
        self.service.submit_flashcard_answer(
            self.ws, card.card_id, "flex-direction: column"
        )
        structured = self.service.structured_for_workspace(self.ws).snapshot()
        mastery = next((item for item in structured.mastery if item.concept == "css-flexbox"), None)
        self.assertIsNotNone(mastery)
        self.assertGreater(mastery.score, 0.0)
        self.assertLess(mastery.score, 0.12)

        snapshot = self.service.snapshot(self.ws)
        self.assertEqual(snapshot.dependency_mastery, [])


if __name__ == "__main__":
    unittest.main()
