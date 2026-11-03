from __future__ import annotations

from types import SimpleNamespace

from app.core.models import ReviewQueueItem
from app.memory.service import MemoryService


def _review(concept: str, task_hint: str, *, source: str = "weakness") -> ReviewQueueItem:
    return ReviewQueueItem(
        concept=concept,
        reason="review this",
        source=source,
        task_hint=task_hint,
        focus_area="queue_lock.py",
        linked_context="src/queue_lock.py",
    )


def test_provider_recovery_sentence_never_becomes_a_review_card() -> None:
    recovery = _review("queue_lock.py", "请把刚才的问题再发一次。")
    truncated_recovery = _review("queue_lock.py", "请把刚才的问题再发一")
    legitimate = _review("queue_lock.py", "解释 with self._lock 的异常释放路径。")
    service = object.__new__(MemoryService)
    service._review_scheduler = SimpleNamespace(
        derive_due_reviews=lambda **_: [recovery, truncated_recovery, legitimate]
    )
    lane = SimpleNamespace(
        workspace={
            "active_thread": {
                "recovery_state": "provider_or_local",
                "focus_area": "queue_lock.py",
                "next_step": "请把刚才的问题再发一次。",
                "blocker": (
                    "The provider returned English-only visible prose while zh-CN is selected."
                ),
            }
        }
    )

    reviews = service._derive_due_reviews(  # pyright: ignore[reportAttributeAccessIssue]
        plan=None,
        lane_snapshot=lane,  # type: ignore[arg-type]
        weakness_records=[],
    )

    assert [item.task_hint for item in reviews] == ["解释 with self._lock 的异常释放路径。"]
