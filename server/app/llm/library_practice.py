from __future__ import annotations

import re
from typing import Any

from .provider.text import _prefers_chinese

_PRACTICE_REQUEST = re.compile(
    r"(?:给我|安排|设计|出|生成|留)(?:一[道个项份]?)?\s*(?:题|练习|训练任务|训练卡)"
    r"|下一阶段学习"
    r"|\b(?:give|design|suggest|include|generate)\b[^.!?]{0,55}\b(?:exercise|practice task|quiz)\b"
    r"|\b(?:next stage of learning|next stage of study)\b",
    re.IGNORECASE,
)
_NO_PRACTICE = re.compile(
    r"(?:不用|不需要|不要|无需|别)(?:给我|安排|设计|出|生成)?(?:一[道个项份]?)?(?:题|练习|训练任务|训练卡)"
    r"|\b(?:no|without|skip|don't include)\s+(?:an?\s+)?(?:exercise|practice|quiz)\b",
    re.IGNORECASE,
)


def library_practice_requested(message: str, context: dict[str, Any]) -> bool:
    intent = context.get("resource_composer_intent")
    return (
        isinstance(intent, dict)
        and intent.get("mode") == "analyze"
        and bool(_PRACTICE_REQUEST.search(message))
        and not _NO_PRACTICE.search(message)
    )


def _practice_passage(excerpt: object) -> str:
    if not isinstance(excerpt, str):
        return ""
    passages = []
    for line in excerpt.splitlines():
        line = line.strip().removeprefix("> ")
        if line.startswith(("#", "User-selected excerpt.")):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|(?<=[。！？])", line):
            passage = " ".join(sentence.split())
            if 12 <= len(passage) <= 320:
                passages.append(passage)
    return next((passage for passage in passages if re.search(
        r"学习|预测|训练|使用|输出|\b(?:learn\w*|predict\w*|train\w*|uses?|outputs?)\b",
        passage, re.IGNORECASE,
    )), passages[0] if passages else "")


def _quoted_passage(text: str) -> str:
    return re.sub(r"([\\`*_[\]<>])", r"\\\1", text)


def build_library_practice(context: dict[str, Any], response_language: str | None) -> str:
    fragments = context.get("resource_fragments")
    chinese = _prefers_chinese(response_language)
    if not isinstance(fragments, list):
        return ""
    passages = []
    for number, fragment in enumerate(fragments[:4], start=1):
        passage = _practice_passage(fragment.get("excerpt")) if isinstance(fragment, dict) else ""
        if passage:
            passages.append(f"> [{number}] {_quoted_passage(passage)}")
            if len(passages) == 2:
                break
    if not passages:
        return ""
    heading = "练习" if chinese else "Practice"
    criteria = "自查标准" if chinese else "Self-check"
    if len(passages) == 2:
        question = (
            "按「先做什么 → 要学习或预测什么」各写一行，再指出两条路线最关键的一处区别。"
            if chinese else "For each approach, write what it does first and what it learns or predicts. "
            "Then name the most important difference."
        )
    else:
        question = (
            "根据摘录，用一行写出「先做什么 → 要学习或预测什么」。"
            if chinese else "Use the excerpt to write what the method does first and what it learns or predicts."
        )
    check = (
        "把答案中的每个目标对到下面的原文。遇到原文没交代的细节，标成「未说明」。"
        if chinese else "Check each target in your answer against its source passage. "
        "Mark any detail the passage leaves open as unspecified."
    )
    return "\n\n".join([f"### {heading}", question, f"**{criteria}**  {check}", *passages])
