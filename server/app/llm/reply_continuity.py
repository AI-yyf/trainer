"""Read a reply's explicit next step without inferring new teaching content."""

from __future__ import annotations

import re

_NEXT_STEP = re.compile(
    r"^(?:#{1,6}\s*)?(?:\*\*)?"
    r"(?:下一步|next step|siguiente paso|étape suivante|nächster schritt|"
    r"次のステップ|다음 단계|próximo passo)"
    r"(?:\*\*)?\s*(?:[:：,，]\s*(.*)|$)",
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
        if matched is not None:
            action = (matched.group(1) or "").strip()
            if action:
                return action[:240]
            waiting = True
            continue
        if waiting and stripped:
            if stripped.startswith("#"):
                return ""
            return re.sub(r"^(?:[-*]\s+|\d+[.)]\s+)", "", stripped)[:240]
    return ""
