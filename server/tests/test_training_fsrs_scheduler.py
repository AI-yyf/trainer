from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.training.fsrs_scheduler import FSRSTrainerCardScheduler, TrainingRating


def test_process_review_reports_elapsed_time_before_refresh() -> None:
    scheduler = FSRSTrainerCardScheduler()
    card = scheduler.create_card("card-1", "concept-1")
    previous_review = datetime.now(timezone.utc) - timedelta(days=2)
    card.last_reviewed_at = previous_review
    card.due = previous_review + timedelta(hours=12)

    result = scheduler.process_review("card-1", TrainingRating.GOOD)

    assert result.elapsed_days == pytest.approx(2.0, abs=0.05)
    assert result.new_interval >= 0
