from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from ..core.models import ReviewQueueAction, ReviewQueueItem
from .models import WeaknessRecord


def visible_review_queue_items(
    items: list[ReviewQueueItem],
    actions: Sequence[ReviewQueueAction],
    weaknesses: dict[str, WeaknessRecord],
    *,
    now: datetime,
) -> list[ReviewQueueItem]:
    """Honor durable queue decisions without hiding a later observed failure."""
    latest = {
        (action.training_card_id, "" if action.training_card_id else action.concept.strip()): action
        for action in actions
    }
    deferred: set[tuple[str | None, str]] = set()
    for (card_id, concept), action in latest.items():
        if action.action not in {"snooze", "skip", "done"} or not action.next_review_at:
            continue
        try:
            deadline = datetime.fromisoformat(action.next_review_at)
            recorded_at = datetime.fromisoformat(action.created_at)
        except ValueError:
            # Legacy records with an invalid timestamp remain visible for recovery.
            continue
        if deadline.tzinfo is None or recorded_at.tzinfo is None:
            continue
        weakness = weaknesses.get(concept) if card_id is None else None
        if weakness and weakness.updated_at.tzinfo and weakness.updated_at > recorded_at:
            continue
        if deadline > now:
            deferred.add((card_id, concept))
    return [
        item for item in items
        if (item.training_card_id, "" if item.training_card_id else item.concept.strip()) not in deferred
    ]
