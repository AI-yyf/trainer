"""A reply never contains a new version of the learner's own code.

The prompt says so in every mode ("Never write a new version of the learner's function, file or
config for them, even as an illustration"). A prompt is a request to the model. On 2026-11-28, with
the gateway's MiniMax-M3 and M3.1-Flash, the guided reply to "这段为什么会报 KeyError？" carried

    ```python
    def get(d, k, default=None):
        return d.get(k, default)
    ```

— the learner's own function, fixed. With MiniMax-M2.7 the same turn did not. The rule is the
product's, so it is kept here as well: a fenced block that declares a function or class the
learner's own code declares, with different code in it, is left out and named in one line. The
learner's code quoted as it stands stays, and so does a standalone example.

While a reply streams, a block is held until it closes — the decision needs the whole block — and
shown whole when it does. Prose streams as before, and nothing shown is ever taken back.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

#: A longer block is never held back and never left out: a whole-file rewrite of this size has not
#: been seen, and an unclosed fence must not swallow the rest of a reply.
MAX_GUARDED_BLOCK_CHARS = 6000

_DECLARATION_PATTERN = re.compile(
    r"\b(?:def|class|function)\s+([A-Za-z_]\w*)"
    r"|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:function\b|\()"
)
_OPENING_FENCE_PATTERN = re.compile(r"(?m)^[ \t]*(`{3,}|~{3,})")
_CLOSING_FENCE_LINE_PATTERN = re.compile(r"[ \t]*[`~]{3,}[ \t]*")
_PARTIAL_FENCE_AT_END_PATTERN = re.compile(r"(?m)^[ \t]*[`~]{1,2}\Z")

LEARNER_CODE_NOTE_ZH = "（这里原本是一段替你改好的代码，已略去：你项目里的代码由你来写。）"
LEARNER_CODE_NOTE_EN = (
    "(A rewritten version of your code stood here and is left out: your project's code is yours to write.)"
)


def learner_code_note(*, chinese: bool) -> str:
    return LEARNER_CODE_NOTE_ZH if chinese else LEARNER_CODE_NOTE_EN


def _declarations(code: str) -> set[str]:
    return {match.group(1) or match.group(2) for match in _DECLARATION_PATTERN.finditer(code)}


def _without_comments(text: str) -> str:
    text = re.sub(r"#[^\n]*", "", text)
    return re.sub(r"//[^\n]*", "", text)


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


@dataclass(frozen=True)
class LearnerCode:
    """What the learner wrote this turn: the open file, its selection, the code in the message."""

    names: frozenset[str]
    sources: tuple[str, ...]

    @classmethod
    def for_turn(cls, *, current_file: dict[str, object] | None, message: str | None) -> LearnerCode:
        pieces: list[str] = []
        if isinstance(current_file, dict):
            for key in ("content", "selection_text"):
                value = current_file.get(key)
                if isinstance(value, str) and value.strip():
                    pieces.append(value)
        if isinstance(message, str) and message.strip():
            pieces.append(message)
        names: set[str] = set()
        for piece in pieces:
            names |= _declarations(piece)
        return cls(names=frozenset(names), sources=tuple(_normalized(_without_comments(piece)) for piece in pieces))

    def rewrites(self, block_content: str) -> bool:
        """Whether a block's content is a new version of something the learner wrote."""
        if not self.names or not (_declarations(block_content) & self.names):
            return False
        code = _normalized(_without_comments(block_content.replace("\r", "")))
        return bool(code) and not any(code in source for source in self.sources)


@functools.lru_cache(maxsize=16)
def _closing_fence_pattern(char: str, length: int) -> re.Pattern[str]:
    """The line that closes a fence: at least as many of the same character, alone on its line."""
    return re.compile(r"(?m)^[ \t]*" + re.escape(char) + f"{{{length},}}" + r"[ \t]*(?=\r?\n|\Z)")


def _pieces(text: str) -> list[tuple[str, str]]:
    """``("text", s)`` and ``("block" | "open", s)``; a block's piece runs from its opening fence to
    its closing fence, an open one has no closing fence yet and is always last."""
    pieces: list[tuple[str, str]] = []
    position = 0
    while True:
        opening = _OPENING_FENCE_PATTERN.search(text, position)
        if opening is None:
            break
        fence = opening.group(1)
        close = _closing_fence_pattern(fence[0], len(fence)).search(text, opening.end())
        pieces.append(("text", text[position : opening.start()]))
        if close is None:
            pieces.append(("open", text[opening.start() :]))
            return pieces
        pieces.append(("block", text[opening.start() : close.end()]))
        position = close.end()
    pieces.append(("text", text[position:]))
    return pieces


def _block_content(piece: str) -> str:
    lines = piece.split("\n")[1:]
    if lines and _CLOSING_FENCE_LINE_PATTERN.fullmatch(lines[-1].rstrip("\r")):
        lines = lines[:-1]
    return "\n".join(lines)


def _leave_out(text: str, learner: LearnerCode, note: str) -> str:
    pieces: list[str] = []
    for kind, piece in _pieces(text):
        if (
            kind == "block"
            and len(piece) <= MAX_GUARDED_BLOCK_CHARS
            and learner.rewrites(_block_content(piece))
        ):
            pieces.append(note)
        else:
            pieces.append(piece)
    return "".join(pieces)


def redact_learner_code_rewrites(text: str, learner: LearnerCode, *, note: str) -> str:
    """A finished reply with every rewritten version of the learner's code left out."""
    if not learner.names or not text:
        return text
    return _leave_out(text, learner, note)


def streamable_learner_reply(buffered: str, learner: LearnerCode, *, note: str) -> str:
    """What of a reply that is still streaming may be shown now.

    Every closed block is decided; an open one is held until it closes; a fence marker that is
    still arriving is held with it. The result only ever grows as the reply does, so nothing shown
    is ever taken back.
    """
    if not learner.names or not buffered:
        return buffered
    pieces = _pieces(buffered)
    held_open = pieces and pieces[-1][0] == "open"
    if held_open and len(pieces[-1][1]) <= MAX_GUARDED_BLOCK_CHARS:
        pieces = pieces[:-1]
    shown = _leave_out("".join(piece for _kind, piece in pieces), learner, note)
    partial = _PARTIAL_FENCE_AT_END_PATTERN.search(shown)
    return shown[: partial.start()] if partial else shown


class LearnerCodeStreamEmitter:
    """Yields what may be shown of a reply that streams, a prefix at a time.

    Wraps the hold a lane already keeps on the last characters of a stream: the text that may be
    shown is ``streamable_learner_reply`` of everything the model has written so far, and the lane's
    holdback is kept on that. ``finish`` releases what is still held once the model's text is
    complete, so a block that was open is shown (or left out) as a whole.
    """

    def __init__(self, learner: LearnerCode, *, note: str, holdback_chars: int) -> None:
        self._learner = learner
        self._note = note
        self._holdback_chars = holdback_chars
        self.emitted = 0
        self.shown = ""

    def push(self, text_so_far: str) -> str:
        self.shown = streamable_learner_reply(text_so_far, self._learner, note=self._note)
        pending = self.shown[self.emitted :]
        if len(pending) <= self._holdback_chars:
            return ""
        safe = pending if self._holdback_chars <= 0 else pending[: -self._holdback_chars]
        self.emitted += len(safe)
        return safe

    def finish(self, text: str) -> str:
        """Everything of the finished text that has not been shown yet."""
        self.shown = redact_learner_code_rewrites(text, self._learner, note=self._note)
        rest = self.shown[self.emitted :]
        self.emitted = len(self.shown)
        return rest

    def restart(self) -> None:
        """The lane replaced the whole text before anything of it was shown."""
        self.emitted = 0
        self.shown = ""
