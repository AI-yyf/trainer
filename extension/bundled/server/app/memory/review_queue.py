from __future__ import annotations

from datetime import datetime

from ..core.models import ReviewQueueAction, ReviewQueueItem
from .models import WeaknessRecord


def visible_review_queue_items(
    items: list[ReviewQueueItem],
    actions: list[ReviewQueueAction],
    weaknesses: dict[str, WeaknessRecord],
    *,
    now: datetime,
) -> list[ReviewQueueItem]:
    """Honor durable queue decisions without hiding a later observed failure."""
    latest = {action.concept.strip(): action for action in actions}
    deferred: set[str] = set()
    for concept, action in latest.items():
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
        weakness = weaknesses.get(concept)
        if weakness and weakness.updated_at.tzinfo and weakness.updated_at > recorded_at:
            continue
        if deadline > now:
            deferred.add(concept)
    return [item for item in items if item.concept.strip() not in deferred]
