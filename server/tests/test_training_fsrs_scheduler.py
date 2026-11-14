from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.training.fsrs_scheduler import (
    FSRSTrainerCardScheduler,
    TrainingRating,
    card_state_from_payload,
    card_state_to_payload,
)


def test_process_review_reports_elapsed_time_before_refresh() -> None:
    scheduler = FSRSTrainerCardScheduler()
    card = scheduler.create_card("card-1", "concept-1")
    previous_review = datetime.now(timezone.utc) - timedelta(days=2)
    card.last_reviewed_at = previous_review
    card.due = previous_review + timedelta(hours=12)

    result = scheduler.process_review("card-1", TrainingRating.GOOD)

    assert result.elapsed_days == pytest.approx(2.0, abs=0.05)
    assert result.new_interval >= 0


def test_first_recall_uses_recorded_learning_time_after_reload(monkeypatch) -> None:
    monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-01T09:00:00Z")
    state = FSRSTrainerCardScheduler().create_card("practice-card", "tuple unpacking")
    state.first_learned_at = state.created_at
    payload = card_state_to_payload(state)
    assert payload["reps"] == 0
    assert payload["last_reviewed_at"] is None

    monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-02T09:00:00Z")
    restored = card_state_from_payload(payload)
    assert restored is not None
    scheduler = FSRSTrainerCardScheduler()
    scheduler.load_card_states([restored])
    review = scheduler.process_review("practice-card", TrainingRating.GOOD)

    assert review.elapsed_days == pytest.approx(1.0)
    assert review.reps == 1
