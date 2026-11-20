"""Conversation productivity convergence check.

Every teaching conversation should produce at least one learning output
(an attempt, verified evidence, or a scheduled review) rather than drifting
into endless explanation. Explicit ``direct_answer`` requests are exempt.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_PRODUCTIVE_METADATA_KEYS = (
    "completed_training_return_feedback",
    "practice_return",
    "attempt_id",
    "training_card_id",
    "review_scheduled",
    "review_completed",
    "evidence",
)
_PRODUCTIVE_SCENARIOS = frozenset({"review", "task", "next_task"})


@dataclass(slots=True)
class ProductivityAssessment:
    """Result of checking whether a thread should converge toward action."""

    should_converge: bool
    consecutive_unproductive_turns: int
    threshold: int
    reason: str

    def to_payload(self) -> dict[str, object]:
        return {
            "should_converge": self.should_converge,
            "consecutive_unproductive_turns": self.consecutive_unproductive_turns,
            "threshold": self.threshold,
            "reason": self.reason,
        }


def _parse_iso(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _message_field(message: object, key: str, default: Any = None) -> Any:
    if isinstance(message, Mapping):
        return message.get(key, default)
    return getattr(message, key, default)


def _is_productive_message(message: object) -> bool:
    raw_metadata = _message_field(message, "metadata", None)
    if not isinstance(raw_metadata, Mapping):
        return False
    for key in _PRODUCTIVE_METADATA_KEYS:
        val = raw_metadata.get(key)
        if val is True or (isinstance(val, str) and bool(val.strip())) or (
            isinstance(val, (list, dict)) and bool(val)
        ):
            return True
    answer_mode = str(raw_metadata.get("answer_mode") or "").strip().lower()
    if answer_mode == "direct":
        return True
    turn_mode = str(raw_metadata.get("turn_mode") or "").strip().lower()
    if turn_mode in {"direct", "direct_answer"}:
        return True
    coach_turn = raw_metadata.get("coach_turn")
    if isinstance(coach_turn, Mapping):
        scenario = str(coach_turn.get("scenario") or "").strip().lower()
        if scenario in _PRODUCTIVE_SCENARIOS:
            return True
        if coach_turn.get("artifacts"):
            return True
    return False


def trailing_unproductive_streak_start(messages: Sequence[object]) -> datetime | None:
    """Return the earliest timestamp inside the trailing unproductive assistant streak."""
    earliest: datetime | None = None
    saw_assistant = False
    for message in reversed(messages):
        if _is_productive_message(message):
            break
        role = str(_message_field(message, "role", "") or "").strip().lower()
        if role == "assistant":
            saw_assistant = True
        ts = _parse_iso(
            _message_field(message, "created_at", None)
            or _message_field(message, "timestamp", None)
        )
        if ts is not None and (earliest is None or ts < earliest):
            earliest = ts
    return earliest if saw_assistant else None


def recent_ledger_learning_output(
    ledger: Any,
    *,
    workspace_id: str,
    since: datetime | None,
) -> tuple[bool, bool]:
    """Return ``(has_attempt_or_evidence, has_review_action)`` from ledger events since ``since``."""
    if ledger is None or not str(workspace_id or "").strip():
        return (False, False)
    recent_fn = getattr(ledger, "recent_learning_activity", None)
    if not callable(recent_fn):
        return (False, False)
    try:
        entries = recent_fn(workspace_id, limit=25)
    except Exception:
        return (False, False)
    has_attempt_or_evidence = False
    has_review = False
    if not isinstance(entries, Iterable):
        return (False, False)
    for entry in entries:
        event_type = str(getattr(entry, "event_type", "") or "").strip()
        if event_type not in {
            "practice_submission_recorded",
            "training_evidence_recorded",
            "evaluation_feedback_recorded",
            "review_scheduled",
        }:
            continue
        if since is not None:
            occurred_at = _parse_iso(getattr(entry, "occurred_at", None))
            if occurred_at is not None and occurred_at < since:
                continue
        if event_type == "review_scheduled":
            has_review = True
        else:
            has_attempt_or_evidence = True
    return (has_attempt_or_evidence, has_review)


def assess_conversation_productivity(
    *,
    messages: Sequence[Any],
    turn_mode: str = "teach",
    has_recent_attempt_or_evidence: bool = False,
    has_recent_review_action: bool = False,
    threshold: int = 2,
) -> ProductivityAssessment:
    """Decide whether a conversation should converge to a concrete micro-attempt or review."""
    normalized_threshold = max(1, int(threshold))
    normalized_mode = str(turn_mode or "").strip().lower()
    if normalized_mode in {"direct", "direct_answer"}:
        return ProductivityAssessment(
            should_converge=False,
            consecutive_unproductive_turns=0,
            threshold=normalized_threshold,
            reason="direct_answer_exempt",
        )
    if has_recent_attempt_or_evidence or has_recent_review_action:
        return ProductivityAssessment(
            should_converge=False,
            consecutive_unproductive_turns=0,
            threshold=normalized_threshold,
            reason="recent_learning_output",
        )
    consecutive = 0
    for message in reversed(messages):
        if _is_productive_message(message):
            break
        role = str(_message_field(message, "role", "") or "").strip().lower()
        if role == "assistant":
            consecutive += 1
    if consecutive >= normalized_threshold:
        return ProductivityAssessment(
            should_converge=True,
            consecutive_unproductive_turns=consecutive,
            threshold=normalized_threshold,
            reason="converge_to_attempt_or_review",
        )
    return ProductivityAssessment(
        should_converge=False,
        consecutive_unproductive_turns=consecutive,
        threshold=normalized_threshold,
        reason="within_budget",
    )
