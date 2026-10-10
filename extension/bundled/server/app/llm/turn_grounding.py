"""Teaching-turn fact grounding (TeachingTurn fact object, first slice).

Follow-up to the 2026-10-08 real-teaching-quality review: the visible reply,
``coach_turn.next_step`` and the memory anchors must describe the same facts.
The worst observed failure mode is a next step that demands code symbols
(function names / call sites) which appear nowhere in the learner's code, the
visible reply, or the conversation — a fabricated requirement that then leaks
into ``memory.current_focus`` and review task hints.

This module holds the pure, provider-free validation rules:

- ``next_step_is_grounded`` — every symbol-bearing next step must keep at least
  one referenced symbol anchored in the reply text or the code text.
- ``sanitize_memory_anchor`` — a memory anchor candidate that is a verbatim
  message prefix is rejected; anchors fall back to empty instead of drifting
  onto the learner's phrasing.

Symbol extraction mirrors the acceptance-criteria signal rule in
``app/training/card_generator.py`` (``_criterion_code_signals``): a backticked
literal or a bare snake_case/camelCase identifier counts as a code symbol;
free-form prose without any code symbol never does.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# Identifier-shaped token: ASCII letters/digits/underscore, optionally dotted
# (``asyncio.gather``). CJK and other scripts never form code identifiers, but
# backticked non-ASCII literals are still checked verbatim.
_IDENTIFIER_PART = r"[A-Za-z_][A-Za-z0-9_]*"
_DOTTED_IDENTIFIER = re.compile(rf"{_IDENTIFIER_PART}(?:\.{_IDENTIFIER_PART})*")
_BACKTICK_LITERAL = re.compile(r"`([^`\n]+)`")
_PLAIN_IDENTIFIER = re.compile(_IDENTIFIER_PART)

# Toolchain vocabulary that is grounded by construction: generic next-step
# templates may mention these without tying the turn to learner code.
_COMMON_TOOLCHAIN_SYMBOLS = frozenset(
    {
        "asyncio", "await", "async", "def", "class", "import", "return", "yield",
        "main", "python", "python3", "pytest", "unittest", "node", "npm", "npx",
        "deno", "bun", "jest", "vitest", "mocha", "cargo", "rustc", "go", "javac",
        "java", "dotnet", "json", "yaml", "toml", "csv", "http", "https", "curl",
        "git", "docker", "make", "cmake", "bash", "shell", "sql", "sqlite", "redis",
        "print", "console", "log", "README", "todo", "fixme",
    }
)

# File extensions that make a dotted symbol a workspace file reference
# (``stuck.py``, ``README.md``) rather than a demanded function/call site.
# File pointers are legitimately forward-looking across turns — the file may
# exist in the workspace or have been introduced by an earlier turn's tool
# call — so they are never treated as ungrounded code symbols here. Verifying
# file existence needs workspace filesystem access, out of scope for this
# pure gate.
_FILE_SUFFIX_SYMBOLS = frozenset(
    {
        "py", "pyi", "ipynb", "js", "mjs", "cjs", "jsx", "ts", "tsx", "go", "rs",
        "java", "kt", "rb", "php", "c", "h", "cpp", "hpp", "cs", "swift", "m",
        "md", "rst", "txt", "json", "yaml", "yml", "toml", "ini", "cfg", "csv",
        "sql", "sh", "bat", "ps1", "html", "css", "scss", "vue", "svelte",
    }
)

# A candidate shorter than this is never treated as a "message prefix": short
# anchors such as a file name that legitimately opens the message stay valid.
_MESSAGE_PREFIX_MIN_LENGTH = 10

# First-clause narration signals: the clause reports an event ("我的脚本
# assert 失败了", "我亲自写了下面的修改", "我只改了 grid[0][0]") instead of
# naming a topic. These override the Latin-token exemption — an English word
# inside a narration clause ("assert", "None") does not make it a technical
# anchor — and they gate the first-clause focus-hint fallback.
_NARRATION_OPENING_PATTERN = re.compile(
    r"(?:亲自|失败|报错|报了|改了|写了|通过了|消失了|断言|断言失败|下面的修改"
    r"|越界|崩溃|跑不通|对吗|这样写|error|exception|traceback|assert)",
    re.IGNORECASE,
)
# Bracket/brace characters mark a copied code fragment ("find([1], 2)"), not
# a concept label.
_NARRATION_FRAGMENT_CHARS = "[](){}（）、【】「」『》"


def looks_like_narration_opening(text: object) -> bool:
    """True when the text reads as an event report or code fragment.

    Used on message-derived focus/anchor candidates: a narration opening or a
    truncated code fragment is the learner's phrasing, never a technical
    topic label.
    """
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return False
    if any(character in cleaned for character in _NARRATION_FRAGMENT_CHARS):
        return True
    if cleaned.endswith(("了", "呢", "吧", "吗")):
        return True
    return _NARRATION_OPENING_PATTERN.search(cleaned) is not None


def normalize_code_symbol(value: object) -> str:
    """Normalize a candidate symbol literal; empty string when not symbol-like."""
    cleaned = str(value or "").strip().strip("`").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\(\s*\)$", "", cleaned).strip()
    if not cleaned or len(cleaned) < 2:
        return ""
    return cleaned


def _is_identifier_like(symbol: str) -> bool:
    return _DOTTED_IDENTIFIER.fullmatch(symbol) is not None


def _looks_like_code_identifier(token: str) -> bool:
    """snake_case or camelCase heuristic, mirroring card_generator's rule."""
    if "_" in token:
        return True
    return token[0].islower() and any(character.isupper() for character in token[1:])


def extract_code_symbols(text: object, *, max_symbols: int = 8) -> list[str]:
    """Collect referenced code symbols from free text.

    Backticked literals win first, then dotted identifiers, then bare
    snake_case/camelCase identifiers. Plain prose words are never symbols.
    """
    source = str(text or "")
    if not source.strip():
        return []
    symbols: list[str] = []

    def _add(candidate: str) -> None:
        normalized = normalize_code_symbol(candidate)
        if not normalized or normalized in symbols:
            return
        symbols.append(normalized)

    for literal in _BACKTICK_LITERAL.findall(source):
        _add(literal)
        if len(symbols) >= max_symbols:
            return symbols[:max_symbols]
    for dotted in _DOTTED_IDENTIFIER.findall(source):
        if "." in dotted:
            _add(dotted)
            if len(symbols) >= max_symbols:
                return symbols[:max_symbols]
    for token in _PLAIN_IDENTIFIER.findall(source):
        if _looks_like_code_identifier(token):
            _add(token)
            if len(symbols) >= max_symbols:
                break
    return symbols[:max_symbols]


def _contains_identifier(identifier: str, corpus: str) -> bool:
    pattern = re.sub(
        r"[A-Za-z0-9_]+",
        lambda match: re.escape(match.group(0)),
        identifier,
    )
    return re.search(rf"(?<![A-Za-z0-9_]){pattern}(?![A-Za-z0-9_])", corpus) is not None


def symbol_in_text(symbol: str, text: object) -> bool:
    """True when ``symbol`` appears in ``text`` as a standalone token."""
    corpus = str(text or "")
    if not corpus or not symbol:
        return False
    if _is_identifier_like(symbol):
        return _contains_identifier(symbol, corpus)
    # Non-identifier backticked literal (CJK phrase, "grid[0] is grid[1]", ...):
    # fall back to verbatim containment of the significant part.
    needle = symbol.strip()
    if _is_identifier_like(needle.replace(" ", "")):
        return _contains_identifier(needle.replace(" ", ""), corpus)
    return needle in corpus


def _is_common_toolchain_symbol(symbol: str) -> bool:
    if symbol.lower() in _COMMON_TOOLCHAIN_SYMBOLS:
        return True
    parts = symbol.split(".")
    return bool(parts) and parts[-1].lower() in _COMMON_TOOLCHAIN_SYMBOLS


def _is_file_reference_symbol(symbol: str) -> bool:
    """True for workspace file pointers (``stuck.py``, ``README.md``).

    A next step that names a file is a "look at / create this file" pointer,
    not a demanded function or call site; the file may live in the workspace
    or have been introduced by an earlier turn (tool call, previous reply), so
    this turn's reply/code corpus cannot refute it.
    """
    parts = symbol.split(".")
    return len(parts) == 2 and parts[-1].lower() in _FILE_SUFFIX_SYMBOLS


def _groundable_symbols(text: object) -> list[str]:
    """Symbols whose absence would make a next step ungrounded."""
    return [
        symbol
        for symbol in extract_code_symbols(str(text or ""))
        if not (
            _is_common_toolchain_symbol(symbol)
            or _is_file_reference_symbol(symbol)
        )
    ]


def next_step_is_grounded(
    next_step_text: object,
    reply_text: object,
    code_text: object,
    *,
    extra_context: object = "",
) -> bool:
    """Validate that a structured next step is grounded in the turn's facts.

    A next step that references no code symbol is grounded prose. A next step
    that references symbols must keep at least one of them present in the
    visible reply, the learner's code (current file, prior message code), or
    extra context (conversation history, artifact text). Common toolchain
    vocabulary (``pytest``, ``python``, ...) and workspace file pointers
    (``stuck.py``) never count as ungrounded references.
    """
    next_step_source = str(next_step_text or "").strip()
    if not next_step_source:
        return True
    referenced = _groundable_symbols(next_step_source)
    if not referenced:
        return True
    corpus_sources = (reply_text, code_text, extra_context)
    for symbol in referenced:
        for corpus in corpus_sources:
            if symbol_in_text(symbol, corpus):
                return True
    return False


def normalize_anchor_text(value: object) -> str:
    """Collapse whitespace for stable anchor comparisons."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_verbatim_message_prefix(candidate: object, message_text: object) -> bool:
    """True when the candidate repeats the opening of the learner message.

    The 2026-10-08 review flagged anchors drifting onto the message prefix
    ("我亲自写了下面的修改…"). A candidate counts as a message prefix when the
    normalized message starts with the normalized candidate and the candidate is
    long enough not to be a trivial keyword overlap. Three exemptions keep
    technical facts and deliberate lane labels usable as anchors:

    - identifier-like anchors (``lesson.py``, ``mutable_default``), and
    - anchors that carry a Latin-letter token but are NOT narration-shaped
      (``我有一个 AI idea``): short mixed-script openings are the lane/topic
      label the coach thread is deliberately re-anchored on. Narration-shaped
      openings ("我的脚本 assert 失败了", "我亲自写了下面的修改（用 None 哨兵")
      are event reports about the learner's edit — the exact drift recorded by
      the real-model maturity runs — so the narration check runs FIRST and an
      embedded English word ("assert", "None") does not rescue them.
    """
    anchor = normalize_anchor_text(candidate)
    message = normalize_anchor_text(message_text)
    if not anchor or not message:
        return False
    if len(anchor) < _MESSAGE_PREFIX_MIN_LENGTH:
        return False
    if _is_identifier_like(anchor.replace(" ", "_")):
        return False
    if looks_like_narration_opening(anchor):
        return True
    if re.search(r"[A-Za-z]", anchor):
        return False
    return message.startswith(anchor)


def sanitize_memory_anchor(
    candidate: object,
    message_text: object,
    *,
    previous_anchor: object = "",
) -> str:
    """Anchor fallback: keep technical anchors, drop message-prefix drift.

    Order enforced here: a non-empty candidate that is not a verbatim message
    prefix passes through; a message-prefix candidate falls back to the
    previous anchor when that itself is not the same prefix; otherwise the
    anchor is empty — never the raw message prefix.
    """
    anchor = normalize_anchor_text(candidate)
    if not anchor:
        previous = normalize_anchor_text(previous_anchor)
        return previous
    if not is_verbatim_message_prefix(anchor, message_text):
        return anchor
    previous = normalize_anchor_text(previous_anchor)
    if previous and not is_verbatim_message_prefix(previous, message_text):
        return previous
    return ""


def grounding_correction_instruction(response_language: object = None) -> str:
    """Corrective instruction for the one allowed regeneration attempt.

    Wired at the coach turn assembly point: when the first next step is
    ungrounded, the caller may re-ask the provider once with this instruction
    appended; if the retry is still ungrounded the turn is downgraded to
    ``requires_confirmation`` instead of shipping a fabricated requirement.
    """
    chinese = isinstance(response_language, str) and response_language.lower().startswith("zh")
    if chinese:
        return (
            "下一步必须只引用当前对话与代码中真实存在的事实；"
            "不得索要未出现的函数名/文件。"
        )
    return (
        "The next step must only reference facts that really exist in the current "
        "conversation and code; do not demand function names or files that never appear."
    )


@dataclass(frozen=True)
class GroundingDecision:
    """Outcome of validating one coach turn's structured next step."""

    grounded: bool
    referenced_symbols: list[str] = field(default_factory=list)
    retry_used: bool = False
    requires_confirmation: bool = False

    @property
    def downgraded(self) -> bool:
        return self.requires_confirmation


def evaluate_next_step_grounding(
    next_step_text: object,
    reply_text: object,
    code_text: object,
    *,
    extra_context: object = "",
    retry_generate: Callable[[], object] | None = None,
) -> GroundingDecision:
    """Validate the next step, optionally regenerating it once, then downgrade.

    ``retry_generate`` is the corrective retry hook: called at most once with
    no arguments, it must return the regenerated next-step text (or an empty
    value to skip). When no retry is wired, an ungrounded step is downgraded
    immediately.
    """
    referenced = _groundable_symbols(next_step_text)
    if next_step_is_grounded(
        next_step_text,
        reply_text,
        code_text,
        extra_context=extra_context,
    ):
        return GroundingDecision(
            grounded=True,
            referenced_symbols=referenced,
            retry_used=False,
            requires_confirmation=False,
        )
    if retry_generate is not None:
        retried_text = retry_generate()
        if next_step_is_grounded(
            retried_text,
            reply_text,
            code_text,
            extra_context=extra_context,
        ):
            return GroundingDecision(
                grounded=True,
                referenced_symbols=_groundable_symbols(retried_text),
                retry_used=True,
                requires_confirmation=False,
            )
    return GroundingDecision(
        grounded=False,
        referenced_symbols=referenced,
        retry_used=retry_generate is not None,
        requires_confirmation=True,
    )
