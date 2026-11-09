"""Review intervention budget: when to surface review, and how much.

FSRS decides *when* a concept is due. This module decides whether the coach
may interrupt the current conversation and how many due items are visible at
once. It is a read decision plus a small set of facts persisted in the
workspace's existing memory dict — no parallel store.

Hard rules:
* an explicit refusal/busy signal wins until its cooldown expires;
* one proactive review offer per session, and no repeat inside the cross-session
  cooldown;
* a focused/blocked thread is not interrupted with unrelated review;
* after a long absence, show one highest-value item instead of the backlog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

REVIEW_INTERVENTION_KEY = "review_intervention"
LONG_OFFLINE_DAYS = 7.0
OFFER_COOLDOWN_HOURS = 4.0
REFUSAL_COOLDOWN_HOURS = 12.0
NORMAL_VISIBLE_LIMIT = 4
CURATED_VISIBLE_LIMIT = 1

_REFUSAL_PATTERN = re.compile(
    r"("
    r"not now|not today|maybe later|some other time|skip (the )?review|"
    r"no review|don'?t (want|need) (to )?(review|practice)|stop (the )?review|"
    r"i'?m busy|i am busy|busy right now|in the middle of (something|work|debugging|a bug)|"
    r"i'?m debugging|debugging this|fixing this bug|focus mode|"
    r"debugging right now|focusing on (this|the) (bug|debug|fix)|"
    r"现在(很|太)?忙|没空|稍后|待会|晚点|先不(复习|看)|不想复习|不要复习|"
    r"别提醒|别打扰|正在调试|在调试|调试这个|排查这个错误|先专注|正在专注|专注中|回头再说"
    r")",
    re.IGNORECASE,
)


def _parse(value: object) -> datetime | None:
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


def _iso(value: datetime) -> str:
    return value.isoformat()


def review_refusal_signal(message: str) -> str:
    """Return a refusal/busy marker from the learner's actual message, or ''."""
    text = " ".join(str(message or "").split())
    if not text:
        return ""
    match = _REFUSAL_PATTERN.search(text)
    if not match:
        return ""
    marker = match.group(1).lower()
    if any(
        token in marker
        for token in (
            "busy",
            "忙",
            "没空",
            "调试",
            "debug",
            "focus",
            "专注",
            "middle of",
        )
    ):
        return "busy"
    return "decline"


def _intervention_state(workspace: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(workspace, dict):
        return {}
    raw = workspace.get(REVIEW_INTERVENTION_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


@dataclass(slots=True)
class ReviewInterventionBudget:
    allowed: bool
    reason: str
    visible_limit: int
    total_due: int
    deferred_count: int = 0
    offline_days: float = 0.0
    refused_until: str | None = None
    last_offer_at: str | None = None
    last_offer_session_id: str = ""
    message_refusal: str = ""
    last_active_at: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "visible_limit": self.visible_limit,
            "total_due": self.total_due,
            "deferred_count": self.deferred_count,
            "offline_days": round(self.offline_days, 2),
            "refused_until": self.refused_until,
            "last_offer_at": self.last_offer_at,
            "last_offer_session_id": self.last_offer_session_id,
            "message_refusal": self.message_refusal,
            "last_active_at": self.last_active_at,
        }


def derive_review_budget(
    workspace: dict[str, Any] | None,
    *,
    due_count: int,
    now: datetime,
    session_id: str = "",
    message: str = "",
) -> ReviewInterventionBudget:
    """Decide whether this turn may proactively surface review."""
    state = _intervention_state(workspace)
    total_due = max(0, int(due_count))
    last_active = _parse((workspace or {}).get("last_active_at"))
    offline_days = (
        max(0.0, (now - last_active).total_seconds() / 86400)
        if last_active is not None
        else 0.0
    )
    message_refusal = review_refusal_signal(message)
    refused_until_dt = _parse(state.get("refused_until"))
    refused_until = _iso(refused_until_dt) if refused_until_dt else None
    last_offer_dt = _parse(state.get("last_offer_at"))
    last_offer_at = _iso(last_offer_dt) if last_offer_dt else None
    last_offer_session = str(state.get("last_offer_session_id") or "")

    def budget(
        allowed: bool,
        reason: str,
        limit: int,
    ) -> ReviewInterventionBudget:
        visible = min(max(0, limit), total_due)
        return ReviewInterventionBudget(
            allowed=allowed,
            reason=reason,
            visible_limit=visible,
            total_due=total_due,
            deferred_count=max(0, total_due - visible),
            offline_days=offline_days,
            refused_until=refused_until,
            last_offer_at=last_offer_at,
            last_offer_session_id=last_offer_session,
            message_refusal=message_refusal,
            last_active_at=_iso(last_active) if last_active else None,
        )

    if total_due <= 0:
        return budget(False, "no_due_reviews", 0)
    if message_refusal:
        return budget(False, f"message_{message_refusal}", CURATED_VISIBLE_LIMIT)
    if refused_until_dt is not None and refused_until_dt > now:
        return budget(False, "refused", CURATED_VISIBLE_LIMIT)
    active_thread = (workspace or {}).get("active_thread")
    if isinstance(active_thread, dict) and str(active_thread.get("blocker") or "").strip():
        # The focused task may still surface related review in Learning, but
        # the coach must not interrupt this turn. Keep the normal visible list
        # (it is ranked with the active focus first) and block the interruption.
        return budget(False, "focused_activity", NORMAL_VISIBLE_LIMIT)
    if last_offer_dt is not None:
        if session_id and last_offer_session == session_id:
            return budget(False, "same_session_interruption", CURATED_VISIBLE_LIMIT)
        if now - last_offer_dt < timedelta(hours=OFFER_COOLDOWN_HOURS):
            return budget(False, "offer_cooldown", CURATED_VISIBLE_LIMIT)
    if offline_days >= LONG_OFFLINE_DAYS:
        return budget(True, "long_offline_curated", CURATED_VISIBLE_LIMIT)
    return budget(True, "due_reviews", NORMAL_VISIBLE_LIMIT)


def curate_review_items(items: Iterable[Any], budget: ReviewInterventionBudget) -> list[Any]:
    """Keep the already-ranked head that the intervention budget allows."""
    materialized = list(items)
    if budget.visible_limit <= 0:
        return []
    head = materialized[: budget.visible_limit]
    if budget.reason == "long_offline_curated" and head:
        first = head[0]
        if hasattr(first, "model_copy"):
            head[0] = first.model_copy(update={"surface_mode": "due"})
    return head


def merge_review_offer(
    state: dict[str, Any] | None,
    *,
    now: datetime,
    session_id: str = "",
) -> dict[str, Any]:
    merged = dict(state or {})
    merged["last_offer_at"] = _iso(now)
    merged["last_offer_session_id"] = str(session_id or "")
    return merged


def merge_review_refusal(
    state: dict[str, Any] | None,
    *,
    now: datetime,
    reason: str,
    session_id: str = "",
) -> dict[str, Any]:
    merged = dict(state or {})
    merged["last_refusal_at"] = _iso(now)
    merged["refused_until"] = _iso(now + timedelta(hours=REFUSAL_COOLDOWN_HOURS))
    merged["last_refusal_reason"] = str(reason or "decline")
    merged["last_refusal_session_id"] = str(session_id or "")
    return merged


def merge_review_engagement(
    state: dict[str, Any] | None,
    *,
    now: datetime,
    session_id: str = "",
) -> dict[str, Any]:
    merged = dict(state or {})
    merged.pop("refused_until", None)
    merged["last_engaged_at"] = _iso(now)
    merged["last_engaged_session_id"] = str(session_id or "")
    return merged
