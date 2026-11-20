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
        r"\b(?:record|save|write\s+down|capture)\s+(?:this\s+as\s+)?(?:a|an|one)?\s*(?:learning|coach|teaching|lecture)?\s*notes?\b",
        r"\bremember\s+this\s+as\s+a\s+(?:learning\s+)?note\b",
        r"\bsave\s+(?:this|that|it|the\s+lecture|the\s+explanation)\s+(?:as\s+a\s+(?:learning|lecture)?\s*note|to\s+(?:my\s+)?(?:library|resources))\b",
    )
    chinese_phrases = (
        "\u8bb0\u4e0b\u4e00\u6761\u5b66\u4e60\u7b14\u8bb0",
        "\u8bb0\u5f55\u4e00\u6761\u5b66\u4e60\u8bb0\u5f55",
        "\u4fdd\u5b58\u4e00\u6761\u5b66\u4e60\u7b14\u8bb0",
        "\u5e2e\u6211\u8bb0\u4e00\u6761\u7b14\u8bb0",
        "\u8bb0\u4e00\u6761\u5b66\u4e60\u7b14\u8bb0",
        "\u6574\u7406\u6210\u7b14\u8bb0",
        "\u6574\u7406\u6210\u8bb2\u7a3f",
        "\u5b58\u8fdb\u8d44\u6599\u5e93",
        "\u5b58\u5165\u8d44\u6599\u5e93",
        "\u4fdd\u5b58\u5230\u8d44\u6599\u5e93",
        "\u4fdd\u5b58\u4e3a\u8bb2\u7a3f",
        "\u4fdd\u5b58\u4e3a\u7b14\u8bb0",
        "\u6c89\u6dc0\u4e3a\u7b14\u8bb0",
        "\u6c89\u6dc0\u5230\u8d44\u6599\u5e93",
    )
    if any(re.search(pattern, lowered) for pattern in english_patterns):
        return True
    return any(phrase in lowered for phrase in chinese_phrases)


def message_requests_lecture_note_save(message: str | None) -> bool:
    """Return True when the learner explicitly asks to save a lecture/note into Resources."""
    lowered = " ".join(str(message or "").strip().lower().split())
    if not lowered:
        return False
    rejected_patterns = (
        r"\b(?:do not|don't|dont|not now|no)\b.{0,48}\b(?:save|store|write)\b.{0,32}\b(?:note|lecture|library|resources?)\b",
        r"(?:\u4e0d\u8981|\u4e0d\u9700\u8981|\u5148\u4e0d\u8981|\u6682\u65f6\u4e0d\u8981).{0,36}(?:\u5b58\u8fdb|\u5b58\u5165|\u4fdd\u5b58|\u6c89\u6dc0|\u7b14\u8bb0|\u8bb2\u7a3f|\u8d44\u6599\u5e93)",
    )
    if any(re.search(pattern, lowered) for pattern in rejected_patterns):
        return False
    english_patterns = (
        r"\b(?:save|store|export|turn)\s+(?:this|that|it|the\s+lecture|the\s+explanation|above)\b.{0,48}\b(?:library|resources?|markdown|\.md|lecture\s+note)\b",
        r"\b(?:save|create|write)\s+(?:a|an|this)?\s*lecture\s+note\b",
    )
    if any(re.search(pattern, lowered) for pattern in english_patterns):
        return True
    chinese_patterns = (
        r"(?:保存|存成|存为|存进|存入|存到|整理成|沉淀为|沉淀到|写成).{0,16}(?:资料库|笔记|讲稿|markdown|\.md)",
    )
    if any(re.search(pattern, lowered) for pattern in chinese_patterns):
        return True
    chinese_phrases = (
        "\u6574\u7406\u6210\u7b14\u8bb0",
        "\u6574\u7406\u6210\u8bb2\u7a3f",
        "\u5b58\u8fdb\u8d44\u6599\u5e93",
        "\u5b58\u5165\u8d44\u6599\u5e93",
        "\u4fdd\u5b58\u5230\u8d44\u6599\u5e93",
        "\u4fdd\u5b58\u4e3a\u8bb2\u7a3f",
        "\u4fdd\u5b58\u4e3a\u7b14\u8bb0",
        "\u6c89\u6dc0\u4e3a\u7b14\u8bb0",
        "\u6c89\u6dc0\u5230\u8d44\u6599\u5e93",
        "\u5b58\u6210\u7b14\u8bb0",
        "\u5b58\u6210\u8bb2\u7a3f",
    )
    return any(phrase in lowered for phrase in chinese_phrases)
