from __future__ import annotations

import re
from typing import Any

from .provider.text import _prefers_chinese

_PRACTICE_REQUEST = re.compile(
    r"(?:给我|安排|设计|出|生成|留)(?:一[道个项份]?)?\s*(?:题|练习|训练任务|训练卡)"
    r"|下一阶段学习"
    r"|\b(?:give|design|suggest|include|generate|create|write)\b[^.!?]{0,55}\b(?:exercise|practice task|quiz)\b"
    r"|\b(?:next stage of learning|next stage of study)\b",
    re.IGNORECASE,
)
_NO_PRACTICE = re.compile(
    r"(?:不用|不需要|不要|无需|别)(?:给我|安排|设计|出|生成)?(?:一[道个项份]?)?(?:题|练习|训练任务|训练卡)"
    r"|\b(?:no|without|skip|don't include)\s+(?:an?\s+)?(?:exercise|practice|quiz)\b",
    re.IGNORECASE,
)
_EXERCISE_APPENDIX = re.compile(
    r"(?:[，,；;。]\s*|(?<=\n))(?:再|然后|并|最后)?\s*(?:请|帮我)?"
    r"(?:给我(?:出|留)?|出|安排|设计|生成|留)(?:一[道个项份]?)?\s*(?:练习题|练习|题|训练任务)"
    r"[。！!？?]?(?=[ \t]*(?:\n|$))"
    r"|(?:,\s*(?:(?:and )?then )?|\s+and\s+)(?:give me|add|include|suggest|write|create) "
    r"(?:an?|one) (?:exercise|practice task|quiz)[.!?]?(?=[ \t]*(?:\n|$))",
    re.IGNORECASE,
)
_PRACTICE_SECTION = re.compile(
    r"(?:练习(?:题目?|问题)?|(?:自测|复习|思考)题|巩固练习|小测验|"
    r"(?:practice(?: question| exercise)?|exercise|quiz)(?:\s+\d+)?)",
    re.IGNORECASE,
)
_PRACTICE_SUPPORT_SECTION = re.compile(
    r"(?:参考答案|答案|解答|解析|提示|验收标准|自查标准|answer|solution|hint|self-check)",
    re.IGNORECASE,
)
_CONTRAST = re.compile(
    r"^(?:in contrast|by contrast|on the other hand|conversely)\b|^(?:相比之下|相反[，、])",
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


def library_analysis_question(message: str) -> str:
    """Keep the analysis request and context while Trainer owns the exercise."""
    return _EXERCISE_APPENDIX.sub("", message).strip() or message


def remove_model_practice(reply: str) -> str:
    lines: list[str] = []
    practice_depth: int | None = None
    fence = ""
    for line in reply.splitlines(keepends=True):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker and (not fence or marker[1].startswith(fence)):
            fence = "" if fence else marker[1]
        if not fence and not marker:
            heading = re.match(r"^\s*(#{1,6})\s+(.+)$", line)
            title = (heading[2] if heading else line).strip().strip("*").rstrip("：:").strip("*").strip()
            if _PRACTICE_SECTION.fullmatch(title):
                practice_depth = len(heading[1]) if heading else 6
                continue
            if practice_depth is not None and heading and len(heading[1]) <= practice_depth:
                if not _PRACTICE_SUPPORT_SECTION.fullmatch(title):
                    practice_depth = None
        if practice_depth is None:
            lines.append(line)
    return "".join(lines).strip()


def _practice_passages(excerpt: object) -> list[str]:
    if not isinstance(excerpt, str):
        return []
    prose = " ".join(
        line.strip().removeprefix("> ") for line in excerpt.splitlines()
        if not line.strip().startswith(("#", "User-selected excerpt."))
    )
    return [passage for sentence in re.split(r"(?<=[.!?])\s+|(?<=[。！？])", prose)
            if 12 <= len(passage := " ".join(sentence.split())) <= 320]


def _practice_passage(passages: list[str]) -> str:
    return next((passage for passage in passages if re.search(
        r"学习|预测|训练|使用|输出|\b(?:learn\w*|predict\w*|train\w*|uses?|outputs?)\b",
        passage, re.IGNORECASE,
    )), passages[0] if passages else "")


def _practice_contrast(passages: list[str]) -> list[str]:
    for index, passage in enumerate(passages[1:], start=1):
        if _CONTRAST.match(passage):
            return passages[max(0, index - 2):index + 2]
    return []


def _quoted_passage(text: str) -> str:
    return re.sub(r"([\\`*_[\]<>])", r"\\\1", text)


def build_library_practice(context: dict[str, Any], response_language: str | None) -> str:
    fragments = context.get("resource_fragments")
    chinese = _prefers_chinese(response_language)
    if not isinstance(fragments, list):
        return ""
    sources: list[tuple[int, list[str]]] = []
    for number, fragment in enumerate(fragments[:4], start=1):
        passages = _practice_passages(fragment.get("excerpt")) if isinstance(fragment, dict) else []
        if passages:
            sources.append((number, passages))
            if len(sources) == 2:
                break
    if not sources:
        return ""
    quotes = [(number, _practice_passage(passages)) for number, passages in sources]
    heading = "练习" if chinese else "Practice"
    criteria = "自查标准" if chinese else "Self-check"
    if len(sources) == 2:
        question = (
            "按「先做什么 → 要学习或预测什么」各写一行，再指出两条路线最关键的一处区别。"
            if chinese else "For each approach, write what it does first and what it learns or predicts. "
            "Then name the most important difference."
        )
    else:
        number, passages = sources[0]
        contrast = _practice_contrast(passages)
        if contrast:
            quotes = [(number, passage) for passage in contrast]
            question = (
                "把原文中的两种情况各写成一行「什么时候发生 → 结果怎么处理」，再用一句话解释处理为什么不同。"
                if chinese else "For each of the two cases, write when it occurs and how the result is handled. "
                "Then explain why the handling differs."
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
    evidence = [f"> [{number}] {_quoted_passage(passage)}" for number, passage in quotes]
    return "\n\n".join([f"### {heading}", question, f"**{criteria}**  {check}", *evidence])
