from datetime import timedelta

from app.core.models import ReviewQueueAction, ReviewQueueItem
from app.memory.models import WeaknessRecord, utc_now
from app.memory.review_queue import visible_review_queue_items


def test_deferred_item_returns_when_its_deadline_arrives() -> None:
    now = utc_now()
    items = [ReviewQueueItem(concept="tuple slot", reason="Recall assignment semantics.")]
    actions = [ReviewQueueAction(
        concept="tuple slot", action="snooze", outcome="deferred", created_at=now.isoformat(),
        next_review_at=(now + timedelta(days=1)).isoformat(),
    )]
    assert not visible_review_queue_items(items, actions, {}, now=now)
    assert visible_review_queue_items(items, actions, {}, now=now + timedelta(days=1)) == items


def test_a_new_failure_overrides_a_previous_completion() -> None:
    now = utc_now()
    items = [ReviewQueueItem(concept="tuple slot", reason="The new attempt failed.")]
    actions = [ReviewQueueAction(
        concept="tuple slot", action="done", outcome="completed", created_at=now.isoformat(),
        next_review_at=(now + timedelta(days=2)).isoformat(),
    )]
    weaknesses = {"tuple slot": WeaknessRecord(
        concept="tuple slot", reason="The new attempt failed.",
        updated_at=now + timedelta(minutes=1),
    )}
    assert visible_review_queue_items(items, actions, weaknesses, now=now) == items


def test_reset_overrides_deferral_without_hiding_legacy_or_invalid_records() -> None:
    now = utc_now()
    items = [ReviewQueueItem(concept="tuple slot", reason="Recall assignment semantics.")]
    deferred = ReviewQueueAction(
        concept="tuple slot", action="snooze", outcome="deferred", created_at=now.isoformat(),
        next_review_at=(now + timedelta(days=1)).isoformat(),
    )
    reset = ReviewQueueAction(concept="tuple slot", action="reset", outcome="needs_more_practice")
    assert visible_review_queue_items(items, [deferred, reset], {}, now=now) == items
    for deadline in ("", "invalid", "2026-10-02T10:00:00"):
        legacy = deferred.model_copy(update={"next_review_at": deadline})
        assert visible_review_queue_items(items, [legacy], {}, now=now) == items
