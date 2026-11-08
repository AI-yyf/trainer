"""The day-clock harness advances FSRS without sleeping or faking due dates."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.clock import utc_now
from app.training.fsrs_scheduler import (
    FSRSTrainerCardScheduler,
    TrainingRating,
    card_state_from_payload,
    card_state_to_payload,
)


def test_test_clock_reads_iso_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-01T09:00:00Z")
    assert utc_now() == datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    monkeypatch.setenv("TRAINER_TEST_NOW", "not-a-date")
    assert utc_now().year >= 2026


def test_fsrs_due_and_interval_advance_across_simulated_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-01T09:00:00Z")
    scheduler = FSRSTrainerCardScheduler()
    scheduler.create_card("clock-card", "tuple mutability")
    first = scheduler.process_review("clock-card", TrainingRating.GOOD)
    assert first.new_interval >= 0
    assert first.next_due > datetime(2026, 11, 1, 9, 0, tzinfo=UTC)

    # Halfway to the due date the card is not due; after it, it is.
    halfway = datetime(2026, 11, 1, 9, 5, tzinfo=UTC)
    monkeypatch.setenv("TRAINER_TEST_NOW", halfway.isoformat())
    assert scheduler.get_due_cards() == []

    monkeypatch.setenv("TRAINER_TEST_NOW", first.next_due.isoformat())
    assert [card.card_id for card in scheduler.get_due_cards()] == ["clock-card"]

    second = scheduler.process_review("clock-card", TrainingRating.GOOD)
    assert second.new_interval >= first.new_interval
    assert second.next_due >= first.next_due

    # Again shrinks the next interval; it must not be treated as a success.
    again = scheduler.process_review("clock-card", TrainingRating.AGAIN)
    assert again.lapses == 1
    assert again.new_interval <= second.new_interval


def test_learning_step_survives_persistence_and_graduates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-01T09:00:00Z")
    scheduler = FSRSTrainerCardScheduler()
    scheduler.create_card("persisted-step", "remote boundary")
    first = scheduler.process_review("persisted-step", TrainingRating.GOOD)
    payload = card_state_to_payload(scheduler.get_card_state("persisted-step"))

    restored = FSRSTrainerCardScheduler()
    restored_state = card_state_from_payload(payload)
    assert restored_state is not None
    assert restored_state.step == 1
    restored.load_card_states([restored_state])
    monkeypatch.setenv("TRAINER_TEST_NOW", first.next_due.isoformat())
    second = restored.process_review("persisted-step", TrainingRating.GOOD)
    assert second.new_interval >= 1
    assert restored.get_card_state("persisted-step").state == "review"
