"""Read a reply's explicit next step without inferring new teaching content."""

from __future__ import annotations

import re

_NEXT_STEP = re.compile(
    r"^(?:#{1,6}\s*)?(?:\*\*)?"
    r"(?:下一步|第一个?[步歩]|next step|first step|siguiente paso|primer paso|"
    r"étape suivante|première étape|nächster schritt|erster schritt|"
    r"次のステップ|最初の一歩|다음 단계|첫 번째 단계|próximo passo|primeiro passo)"
    # A parenthetical qualifier may sit between label and colon, with the bold
    # close on either side (`第一步（今天 10 分钟）：…`, `**First step (10 min)**: …`).
    r"(?:\s*[（(][^）)]{0,40}[）)])?(?:\s*\*\*)?\s*(?:[:：,，]\s*(.*)|$)",
    re.I,
)

# A compact close (the non-stream finalize lane collapses the model's sections
# onto one line) can start a labelled action mid-text after a sentence
# boundary. Read such an action only at a sentence start — never mid-sentence,
# never inside a code fence — so prose that merely mentions the label stays
# prose (「…可验证的第一步：具体见下」has no sentence boundary before the label).
_INLINE_NEXT_STEP = re.compile(
    r"(?:^|[。！？!?])\s*"
    r"(?:\*\*)?(?:下一步|第一个?[步歩]|next step|first step|siguiente paso|primer paso|"
    r"étape suivante|première étape|nächster schritt|erster schritt|"
    r"次のステップ|最初の一歩|다음 단계|첫 번째 단계|próximo passo|primeiro passo)"
    r"(?:\s*[（(][^）)]{0,40}[）)])?(?:\s*\*\*)?\s*[:：]\s*"
    r"([^。！？\n]{4,240}。?)"
    r"(?=$|\n|[。！？]\s|$)",
    re.I,
)

_PAST_TENSE_QUALIFIERS = ("已完成", "已经完成", "已落地", "已解决", "已验证", "done", "completed", "resolved")


def _past_tense_label(segment: str) -> bool:
    return any(
        token in qualifier.casefold()
        for qualifier in re.findall(r"[（(]([^）)]{0,40})[）)]", segment)
        for token in _PAST_TENSE_QUALIFIERS
    )


def _drop_code_fences(content: str) -> str:
    kept: list[str] = []
    fence = ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            delimiter = stripped[:3]
            if not fence:
                fence = delimiter
            elif delimiter == fence:
                fence = ""
            continue
        if not fence:
            kept.append(line)
    return "\n".join(kept)


def visible_next_step(content: str) -> str:
    """Use only a labelled prose action outside code; no execution or evidence."""
    fence = ""
    waiting = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            delimiter = stripped[:3]
            if not fence:
                fence = delimiter
            elif delimiter == fence:
                fence = ""
            # A code-only section does not supply a prose action.
            waiting = False
            continue
        if fence:
            continue
        matched = _NEXT_STEP.fullmatch(stripped)
        if matched is not None and _past_tense_label(stripped):
            # A past-tense qualifier marks a recap label ("下一步（已完成）：…");
            # a completed action is never the learner's next move.
            matched = None
        if matched is None:
            # Label headed sections carry a short suffix noun before the
            # action (`## 第一步代码`, `### Next steps`); the action itself
            # lives on the following line. Only a bounded whitelist qualifies.
            for noun in ("代码", "练习", "实验", "检查", "步骤", "行动", "任务", "code", "s"):
                if stripped.lower().endswith(noun) and len(stripped) > len(noun):
                    matched = _NEXT_STEP.fullmatch(stripped[: -len(noun)].rstrip())
                    if matched is not None:
                        break
                    matched = None
        if matched is not None:
            action = (matched.group(1) or "").strip()
            action = re.sub(r"\*+\s*$", "", action).strip()
            if action:
                return action[:240]
            waiting = True
            continue
        if waiting and stripped:
            if stripped.startswith("#"):
                return ""
            return re.sub(r"^(?:[-*]\s+|\d+[.)]\s+)", "", stripped)[:240]
    # Sentence-boundary inline lane (compact closes): the LAST labelled action
    # wins, mirroring the line-level reader's end-of-reply preference.
    for matched in _INLINE_NEXT_STEP.finditer(_drop_code_fences(content)):
        if _past_tense_label(matched.group(0)):
            continue
        action = (matched.group(1) or "").strip()
        action = re.sub(r"\*+\s*$", "", action).strip()
        if action:
            return action[:240]
    return ""
