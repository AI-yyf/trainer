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
    return ""
