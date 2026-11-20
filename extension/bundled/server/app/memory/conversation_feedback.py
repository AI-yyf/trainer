"""Recognize direct feedback about the coach's preceding explanation."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from ..core.models import ChatMessage
from ..llm.conversation_scope import composer_conversation_scope

ExplanationFeedback = Literal["too_hard", "too_simple"]

_HARD = re.compile(
    r"^(?:你(?:这次|刚才|上次)?(?:的)?(?:讲解|解释|回答)(?:得)?|"
    r"(?:这个|这次|刚才的)(?:讲解|解释|回答))\s*(?:太|有点太)(?:复杂|难懂|抽象|晦涩)"
    r"|^(?:(?:your|that|the previous|this)\s+(?:explanation|answer)\s+(?:was|is|felt)\s+"
    r"|you explained (?:it|that)\s+)(?:a (?:bit|little)\s+)?too\s+"
    r"(?:complicated|complex|abstract|technical|hard to (?:understand|follow))\b",
    re.IGNORECASE,
)
_EASY = re.compile(
    r"^(?:你(?:这次|刚才|上次)?(?:的)?(?:讲解|解释|回答)(?:得)?|"
    r"(?:这个|这次|刚才的)(?:讲解|解释|回答))\s*(?:太|有点太)(?:简单|浅显|基础)"
    r"|^(?:your|that|the previous|this)\s+(?:explanation|answer)\s+(?:was|is|felt)\s+"
    r"(?:a (?:bit|little)\s+)?too\s+(?:simple|basic|shallow)\b",
    re.IGNORECASE,
)


def explanation_feedback(
    messages: Sequence[ChatMessage],
    *,
    message: str,
    active_view: str | None,
) -> tuple[ExplanationFeedback, str] | None:
    """Return the feedback kind and the reply it refers to, in the same conversation.

    The current user turn is already in the transcript. A welcome message or
    an explanation in another destination cannot be the subject of feedback.
    """
    if (
        not messages
        or messages[-1].role != "user"
        or messages[-1].content != message
    ):
        return None
    feedback: ExplanationFeedback
    if _HARD.search(message.strip()):
        feedback = "too_hard"
    elif _EASY.search(message.strip()):
        feedback = "too_simple"
    else:
        return None

    scope = composer_conversation_scope(active_view)
    reply_id = ""
    for entry in reversed(messages[:-1]):
        if composer_conversation_scope(entry.metadata.get("active_view")) != scope:
            continue
        if not entry.content.strip():
            continue
        if entry.role == "assistant" and not reply_id:
            if entry.metadata.get("intent") != "coach" or entry.metadata.get("stream_state") in {
                "interrupted", "failed", "in_progress",
            }:
                return None
            reply_id = entry.id
        elif entry.role == "user":
            return (feedback, reply_id) if reply_id else None
    return None
