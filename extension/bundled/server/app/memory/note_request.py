"""Shared language bar for an explicit learning-note request.

Coach turns must not persist a teaching observation unless the learner
asked to record or save a learning note. The agent tool and coach context
share this helper so the bar cannot drift.
"""

from __future__ import annotations

import re


def message_requests_explicit_learning_note(message: str | None) -> bool:
    lowered = " ".join(str(message or "").strip().lower().split())
    if not lowered:
        return False

    rejected_patterns = (
        r"\b(?:do not|don't|dont|not now|no)\b.{0,48}\b(?:learning\s+)?notes?\b",
        r"(?:\u4e0d\u8981|\u4e0d\u9700\u8981|\u5148\u4e0d\u8981|\u6682\u65f6\u4e0d\u8981).{0,36}(?:\u5b66\u4e60\u7b14\u8bb0|\u5b66\u4e60\u8bb0\u5f55|\u7b14\u8bb0)",
    )
    if any(re.search(pattern, lowered) for pattern in rejected_patterns):
        return False

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
    note_nouns = (
        "learning note",
        "learning notes",
        "coach note",
        "teaching note",
        "\u5b66\u4e60\u7b14\u8bb0",
        "\u5b66\u4e60\u8bb0\u5f55",
    )
    if any(noun in lowered for noun in note_nouns) and lowered.startswith(explanation_prefixes):
        return False

    english_patterns = (
        r"\b(?:record|save|write\s+down|capture)\s+(?:this\s+as\s+)?(?:a|an|one)?\s*(?:learning|coach|teaching)?\s*notes?\b",
        r"\bremember\s+this\s+as\s+a\s+(?:learning\s+)?note\b",
        r"\bsave\s+this\s+as\s+a\s+(?:learning\s+)?note\b",
    )
    chinese_phrases = (
        "\u8bb0\u4e0b\u4e00\u6761\u5b66\u4e60\u7b14\u8bb0",
        "\u8bb0\u5f55\u4e00\u6761\u5b66\u4e60\u8bb0\u5f55",
        "\u4fdd\u5b58\u4e00\u6761\u5b66\u4e60\u7b14\u8bb0",
        "\u5e2e\u6211\u8bb0\u4e00\u6761\u7b14\u8bb0",
        "\u8bb0\u4e00\u6761\u5b66\u4e60\u7b14\u8bb0",
    )
    if any(re.search(pattern, lowered) for pattern in english_patterns):
        return True
    return any(phrase in lowered for phrase in chinese_phrases)
