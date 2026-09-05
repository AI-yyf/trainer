"""Shared language bar for an explicit training-card request.

Coach turns must not mint a card unless the learner asked to create or
generate one. Router force-paths and the ``generate_training_card`` tool
share this helper so the bar cannot drift.
"""

from __future__ import annotations

import re


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
