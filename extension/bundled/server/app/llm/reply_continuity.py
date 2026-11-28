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

# Real models sometimes dress the label up: `下一步`：…, “Next step:” …, **`下一步`**：…. The reader wants
# the bare label followed by its colon, so wrappers around the label (and one right after the colon)
# are dropped before matching. Seen with MiniMax-M2.7 on 2026-11-28.
_WRAPPER_CHARS = "`'\"“”‘’「」『』"
_LABEL_IN_WRAPPERS = re.compile(
    "[" + re.escape(_WRAPPER_CHARS) + r"]*\s*"
    r"(下一步|第一个?[步歩]|next step|first step|siguiente paso|primer paso|"
    r"étape suivante|première étape|nächster schritt|erster schritt|"
    r"次のステップ|最初の一歩|다음 단계|첫 번째 단계|próximo passo|primeiro passo)"
    r"\s*[" + re.escape(_WRAPPER_CHARS) + r"]*(?:\s*\*\*)?\s*[:：]\s*[" + re.escape(_WRAPPER_CHARS) + r"]?",
    re.I,
)


def _unwrap_next_step_label(text: str) -> str:
    return _LABEL_IN_WRAPPERS.sub(lambda match: f"{match.group(1)}：", text)


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
        if _LABEL_IN_WRAPPERS.search(stripped[:32]):
            stripped = _unwrap_next_step_label(stripped)
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
    for matched in _INLINE_NEXT_STEP.finditer(_unwrap_next_step_label(_drop_code_fences(content))):
        if _past_tense_label(matched.group(0)):
            continue
        action = (matched.group(1) or "").strip()
        action = re.sub(r"\*+\s*$", "", action).strip()
        if action:
            return action[:240]
    return ""


# Coaching replies are asked to close with one instruction. When that closing carries no label,
# it is still the action the learner was just told to take, so it may serve as the next step — but
# only when it reads as an instruction. A closing that explains ("这意味着…") or a reply that ends
# on a heading or a code block yields nothing, and the caller falls through to its neutral default.
_ZH_IMPERATIVE_CUES = (
    "先", "请", "试", "跑", "运行", "执行", "打开", "把", "改成", "换成", "加上", "删掉", "改", "写", "说说",
    "说出", "说下", "检查", "验证", "接下来", "别", "记得", "给我", "贴", "读", "对照", "回答", "选", "挑",
    "标出", "动手", "回到", "暂停", "停下", "重新", "数一数", "列出", "记下", "补充", "重跑",
)
_EN_IMPERATIVE_CUES = frozenset(
    {
        "run", "try", "open", "change", "replace", "add", "remove", "delete", "write", "check",
        "test", "verify", "start", "go", "look", "read", "tell", "explain", "do", "make", "use",
        "put", "turn", "compare", "answer", "pick", "stop", "now", "next", "then", "keep", "set",
        "call", "print", "rename", "move", "copy", "paste", "apply", "revert", "swap", "rerun",
        "list", "note", "remember", "take", "show", "count", "reorder",
    }
)
_EN_LEADING_FILLERS = ("now,", "then,", "next,", "and ", "finally,", "now ", "then ", "next ")
_LIST_MARKER = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_COACH_NARRATION = re.compile(r"先(?:透露|说明|提醒|强调|声明|澄清|指出|交待|交代|说一句|说清楚|补充一句|确认一下)")


def _closing_prose_paragraph(content: str) -> str:
    """The last block of prose outside code fences, with headings and list markers removed."""
    fence = ""
    block: list[str] = []
    paragraphs: list[str] = []

    def flush() -> None:
        if block:
            paragraphs.append("\n".join(block))
            block.clear()

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            delimiter = stripped[:3]
            if not fence:
                fence = delimiter
            elif delimiter == fence:
                fence = ""
            flush()
            continue
        if fence:
            continue
        if not stripped or stripped == "---" or set(stripped) in ({"-"}, {"*"}, {"_"}):
            flush()
            continue
        block.append(stripped)
    flush()
    if not paragraphs:
        return ""
    lines = [line for line in paragraphs[-1].split("\n") if not line.startswith("#")]
    text = " ".join(_LIST_MARKER.sub("", line) for line in lines).strip()
    return text


def _reads_as_instruction(text: str) -> bool:
    if not text:
        return False
    # What the coach does first ("顺带说一句，先透露一个前提") is narration, not a step for the learner.
    head = _COACH_NARRATION.sub("", text[:40])[:12]
    # "别" is not looked for inside the opening words: it also sits inside "差别", "分别", "识别".
    if any(cue in head for cue in _ZH_IMPERATIVE_CUES if cue != "别"):
        return True
    lowered = text.lower()
    for filler in _EN_LEADING_FILLERS:
        if lowered.startswith(filler):
            lowered = lowered[len(filler):].lstrip()
    first = re.split(r"[^a-z]+", lowered, maxsplit=1)[0]
    if first in _EN_IMPERATIVE_CUES:
        return True
    # An instruction may follow a lead-in inside the sentence — "提示：和 payments.py 一样，先让
    # `refund()` …" — so a clause that opens with "先" or "请" counts. Only those two: a clause that
    # opens with a verb is often a noun phrase ("验证用的代码我放在沙箱里跑"). What the coach does
    # first ("先透露一个前提", "先说明…") is narration, not a step for the learner.
    return any(
        clause.strip().startswith(("先", "请")) and not _COACH_NARRATION.match(clause.strip())
        for clause in re.split(r"[，,；;：:。]", text)
    )


def closing_action_step(content: str) -> str:
    """The reply's closing instruction when it is not labelled; empty when the closing is not one."""
    text = _closing_prose_paragraph(content)
    text = re.sub(r"^\*\*(.+?)\*\*", r"\1", text).strip()
    if not _reads_as_instruction(text):
        return ""
    return text[:240]
