from __future__ import annotations

from datetime import timedelta

from app.memory.models import MasteryRecord, utc_now
from app.memory.review_scheduler import ReviewRating, ReviewScheduler


def test_review_scheduler_processes_fsrs_state_with_human_readable_state() -> None:
    scheduler = ReviewScheduler()
    mastery = MasteryRecord(
        concept="startup wiring",
        score=0.3,
        confidence=0.7,
        updated_at=utc_now() - timedelta(days=2),
        next_review_at=utc_now() - timedelta(hours=12),
        due_date=utc_now() - timedelta(hours=12),
    )

    updated = scheduler.process_mastery_review(mastery, ReviewRating.GOOD)

    assert updated.state in {"learning", "review", "relearning"}
    assert updated.next_review_at is not None
    assert updated.retrievability >= 0.0
