"""Shared language bar for an explicit training-card request.

Coach turns must not mint a card unless the learner asked to create or
generate one. Router force-paths and the ``generate_training_card`` tool
share this helper so the bar cannot drift.
"""

from __future__ import annotations

import re
from typing import Literal

DeliverableKind = Literal["file_based", "text_payload"]
DEFAULT_DELIVERABLE_KIND: DeliverableKind = "file_based"
ALLOWED_DELIVERABLE_KINDS: tuple[DeliverableKind, ...] = ("file_based", "text_payload")


def normalize_deliverable_kind(
    value: str | None,
    *,
    subject_family: str | None = None,
    learning_subtype: str | None = None,
) -> DeliverableKind:
    """Resolve a card's deliverable carrier (P1 #15, §7.2).

    ``file_based`` is the historical default (code/IDE file); ``text_payload``
    is the in-card text submission carrier for literature and theory concept /
    reading / writing / annotation cards. Unknown values fall back to
    ``file_based`` unless ``subject_family == "literature"`` where in-card text
    is the primary carrier.
    """
    raw = str(value or "").strip().lower()
    if raw == "text_payload":
        return "text_payload"
    if raw == "file_based":
        return "file_based"
    family = str(subject_family or "").strip().lower()
    subtype = str(learning_subtype or "").strip().lower()
    if family == "literature":
        return "text_payload"
    if family == "theory" and subtype in {"writing", "memorization", "reading", "concept"}:
        return "text_payload"
    return DEFAULT_DELIVERABLE_KIND



def message_requests_explicit_training_card(message: str | None) -> bool:
    lowered = " ".join(str(message or "").strip().lower().split())
    if not lowered:
        return False

    rejected_card_patterns = (
        r"\b(?:do not|don't|dont|not now|no)\b.{0,48}\b(?:training|practice|flash)\s*cards?\b",
        r"(?:\u4e0d\u8981|\u4e0d\u9700\u8981|\u5148\u4e0d\u8981|\u6682\u65f6\u4e0d\u8981).{0,36}(?:\u8bad\u7ec3\u5361|\u7ec3\u4e60\u5361|\u95ea\u5361|\u95ea\u8bb0\u5361|\u590d\u4e60\u5361)",
    )
    if any(re.search(pattern, lowered) for pattern in rejected_card_patterns):
        return False

    request_actions = (
        "create",
        "generate",
        "make",
        "build",
        "prepare",
        "route",
        "turn this into",
        "give me a",
        "i want a",
        "need a",
        "start me with",
        "\u751f\u6210",
        "\u521b\u5efa",
        "\u505a\u4e00\u5f20",
        "\u7ed9\u6211",
        "\u6765\u4e00\u5f20",
        "\u5b89\u6392",
        "\u51fa\u4e00\u5f20",
    )
    direct_training_card_nouns = (
        "\u8bad\u7ec3\u5361",
        "\u7ec3\u4e60\u5361",
        "\u8bad\u7ec3\u9898",
        "\u8bad\u7ec3\u4efb\u52a1",
    )
    flash_card_nouns = (
        "flash card",
        "flashcard",
        "\u95ea\u5361",
        "\u95ea\u8bb0\u5361",
        "\u590d\u4e60\u5361",
    )
    card_nouns = (
        *flash_card_nouns,
        *direct_training_card_nouns,
        "training card",
        "training cards",
        "practice card",
        "learn-first card",
        "learn-first practice",
        "hands-on card",
        "\u8bad\u7ec3\u5361\u7247",
    )
    explanation_prefixes = (
        "what is",
        "what are",
        "how does",
        "explain",
        "\u4ec0\u4e48\u662f",
        "\u600e\u4e48\u7528",
        "\u5982\u4f55\u4f7f\u7528",
        "\u4ecb\u7ecd",
    )
    if any(noun in lowered for noun in card_nouns) and lowered.startswith(explanation_prefixes):
        return False

    if any(token in lowered for token in card_nouns) and any(
        token in lowered for token in request_actions
    ):
        return True

    english_practice_patterns = (
        r"\b(?:give|make|create|start|prepare)\s+(?:me\s+)?(?:a|an)?\s*(?:practice|exercise|quiz|test)\b",
        r"^(?:please\s+)?(?:quiz|test)\s+me\b",
    )
    chinese_practice_phrases = (
        "\u7ed9\u6211\u4e00\u9053\u7ec3\u4e60",
        "\u51fa\u4e00\u9053\u7ec3\u4e60",
        "\u7ed9\u6211\u51fa\u9898",
        "\u6765\u4e00\u9053\u9898",
    )
    if any(re.search(pattern, lowered) for pattern in english_practice_patterns) or any(
        phrase in lowered for phrase in chinese_practice_phrases
    ):
        return True
    return lowered.startswith(
        ("\u6d4b\u9a8c\u6211", "\u8bf7\u6d4b\u9a8c\u6211", "\u8003\u8003\u6211", "\u8bf7\u8003\u8003\u6211")
    )


def message_requests_rubric_review(message: str | None) -> bool:
    """Explicit learner language asking for a rubric review (P2 #15).

    ``run_rubric_review`` is host-gated: the flag auto-arms only when the
    learner explicitly asks for a rubric/anchor review AND the host supplied a
    card rubric. Model-authored rubrics are refused at the tool boundary; this
    helper only detects the request.
    """
    lowered = " ".join(str(message or "").strip().lower().split())
    if not lowered:
        return False

    rejected_rubric_patterns = (
        r"\b(?:do not|don't|dont|no need|without)\b.{0,48}\b(?:rubric|scoring)\b",
        r"(?:\u4e0d\u8981|\u4e0d\u9700\u8981|\u5148\u4e0d|\u6682\u65f6\u4e0d).{0,24}(?:rubric|\u91cf\u89c4|\u8bc4\u5206\u6807\u51c6|\u8bc4\u5ba1)",
    )
    if any(re.search(pattern, lowered) for pattern in rejected_rubric_patterns):
        return False

    english_rubric_patterns = (
        r"\brubric\s+(?:review|check|grade|evaluation)\b",
        r"\b(?:review|check|grade|evaluate)\s+(?:it|this|the submission|my submission)?\s*(?:against|with|by|using)\s+(?:the\s+)?rubric\b",
        r"\b(?:run|do|perform)\s+(?:the\s+)?rubric\b",
    )
    chinese_rubric_phrases = (
        "\u6309\u8bc4\u5206\u6807\u51c6",
        "\u6309\u91cf\u89c4",
        "\u7528\u91cf\u89c4",
        "\u8bc4\u5206\u6807\u51c6\u8bc4\u5ba1",
        "\u91cf\u89c4\u8bc4\u5ba1",
        "\u8bc4\u5206\u6807\u51c6\u68c0\u67e5",
        "\u6309\u8bc4\u5ba1\u6807\u51c6",
        "\u5bf9\u7167\u8bc4\u5206\u6807\u51c6",
        "\u5bf9\u7167\u91cf\u89c4",
        "\u951a\u70b9\u8bc4\u5ba1",
    )
    japanese_rubric_phrases = (
        "\u30eb\u30d6\u30ea\u30c3\u30af\u8a55\u4fa1",
        "\u8a55\u4fa1\u57fa\u6e96\u3067\u8a55\u4fa1",
        "\u8a55\u4fa1\u57fa\u6e96\u3067\u30c1\u30a7\u30c3\u30af",
    )
    german_rubric_phrases = (
        "bewertungsraster",
        "bewertung mit dem raster",
        "anhand des bewertungsrasters",
    )
    french_rubric_phrases = (
        "grille d'\u00e9valuation",
        "grille d\u2019\u00e9valuation",
        "selon la grille",
    )
    return (
        any(re.search(pattern, lowered) for pattern in english_rubric_patterns)
        or any(phrase in lowered for phrase in chinese_rubric_phrases)
        or any(phrase in lowered for phrase in japanese_rubric_phrases)
        or any(phrase in lowered for phrase in german_rubric_phrases)
        or any(phrase in lowered for phrase in french_rubric_phrases)
    )
