"""Teaching-turn fact grounding (TeachingTurnFacts contract, slice 2).

Follow-up to the 2026-10-08 real-teaching-quality review: the visible reply,
``coach_turn.next_step`` and the memory anchors must describe the same facts.
The worst observed failure mode is a next step that demands code symbols
(function names / call sites) which appear nowhere in the learner's code, the
visible reply, or the conversation — a fabricated requirement that then leaks
into ``memory.current_focus`` and review task hints.

Slice 2 (2026-10-13) replaces the "one referenced symbol hit lets the whole
step pass" rule with **per-claim full anchoring** and adds the
``TeachingTurnFacts`` contract shared by the four assembly flows:

- ``TeachingFact`` / ``TeachingTurnFacts`` — the turn's claim-level facts:
  what the learner provided, what workspace tools verified, what the reply and
  the next step claim, and the resulting per-claim verdicts.
- ``build_teaching_turn_facts`` — the only fact-extraction implementation.
  The structured next step enters through the ``next_step_text`` keyword
  (preferred) or ``agent_evidence["next_step"]``.
- ``evaluate_turn_grounding`` — per-claim decision with an at-most-once
  corrective-retry carrier (``corrected_next_step``) and honest downgrade.
  Retry legality (model-completed reply, provider available) is the assembly
  layer's call; this layer only runs the injected hook at most once.
- file pointers: anchored in the turn corpora, or checked through the injected
  ``file_exists`` input; when checking is impossible (no checker, remote
  workspace, checker answers ``None``) the verdict is ``unverifiable`` — never
  a downgrade, never claimed as verified.

Unchanged here: memory-anchor anti-drift (``sanitize_memory_anchor`` and the
narration / message-prefix rules) and the legacy ``next_step_is_grounded`` /
``evaluate_next_step_grounding`` entry points, which now route through the
strict per-claim core.

Symbol extraction mirrors the acceptance-criteria signal rule in
``app/training/card_generator.py`` (``_criterion_code_signals``): a backticked
literal or a bare snake_case/camelCase identifier counts as a code symbol;
free-form prose without any code symbol never does.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

# Identifier-shaped token: ASCII letters/digits/underscore, optionally dotted
# (``asyncio.gather``). CJK and other scripts never form code identifiers, but
# backticked non-ASCII literals are still checked verbatim.
_IDENTIFIER_PART = r"[A-Za-z_][A-Za-z0-9_]*"
_DOTTED_IDENTIFIER = re.compile(rf"{_IDENTIFIER_PART}(?:\.{_IDENTIFIER_PART})*")
_BACKTICK_LITERAL = re.compile(r"`([^`\n]+)`")
_PLAIN_IDENTIFIER = re.compile(_IDENTIFIER_PART)

# Toolchain vocabulary that is grounded by construction: generic next-step
# templates may mention these without tying the turn to learner code. Slice 2
# narrowed this to language builtins / command words: project nouns such as
# ``log`` / ``todo`` / ``fixme`` no longer bypass anchoring.
_COMMON_TOOLCHAIN_SYMBOLS = frozenset(
    {
        "asyncio", "await", "async", "def", "class", "import", "return", "yield",
        "main", "python", "python3", "pytest", "unittest", "node", "npm", "npx",
        "deno", "bun", "jest", "vitest", "mocha", "cargo", "rustc", "go", "javac",
        "java", "dotnet", "json", "yaml", "toml", "csv", "http", "https", "curl",
        "git", "docker", "make", "cmake", "bash", "shell", "sql", "sqlite", "redis",
        "print", "console", "README",
    }
)
# NOTE: ``log``, ``todo`` and ``fixme`` were removed from this set on purpose
# (2026-10-13 slice 2): a next step demanding them is a real project-noun
# reference and must anchor like any other symbol.

# Language keywords are never claim-worthy symbols: a backticked code literal
# such as ``for i, x in enumerate(xs)`` must not turn ``for`` / ``in`` into
# fabricated-requirement claims.
_LANGUAGE_KEYWORDS = frozenset(
    {
        "for", "if", "while", "in", "and", "or", "not", "is", "try", "except",
        "finally", "with", "as", "lambda", "elif", "else", "pass", "break",
        "continue", "del", "assert", "from", "global", "nonlocal", "raise",
        "none", "true", "false", "null", "undefined", "self", "this", "let",
        "const", "var", "new", "typeof", "instanceof", "await", "async", "yield",
        "def", "class", "import", "return",
    }
)

# File extensions that make a dotted symbol a workspace file reference
# (``stuck.py``, ``README.md``) rather than a demanded function/call site.
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

# ---------------------------------------------------------------------------
# Slice-2 claim vocabulary (DESIGN.md §2.1)
# ---------------------------------------------------------------------------

FACT_KIND_ERROR_TEXT = "error_text"
FACT_KIND_CODE_FRAGMENT = "code_fragment"
FACT_KIND_SYMBOL = "symbol"
FACT_KIND_FILE_PATH = "file_path"
FACT_KIND_CALL_SITE = "call_site"
FACT_KIND_BEHAVIOR_CLAIM = "behavior_claim"
FACT_KINDS = frozenset(
    {
        FACT_KIND_ERROR_TEXT,
        FACT_KIND_CODE_FRAGMENT,
        FACT_KIND_SYMBOL,
        FACT_KIND_FILE_PATH,
        FACT_KIND_CALL_SITE,
        FACT_KIND_BEHAVIOR_CLAIM,
    }
)

PROVENANCE_TOOL_VERIFIED = "tool_verified"
PROVENANCE_LEARNER_PROVIDED = "learner_provided"
PROVENANCE_MODEL_CLAIM = "model_claim"
PROVENANCE_LOCAL_FALLBACK = "local_fallback"
FACT_PROVENANCES = frozenset(
    {
        PROVENANCE_TOOL_VERIFIED,
        PROVENANCE_LEARNER_PROVIDED,
        PROVENANCE_MODEL_CLAIM,
        PROVENANCE_LOCAL_FALLBACK,
    }
)

SOURCE_USER_MESSAGE = "user_message"
SOURCE_CURRENT_FILE = "current_file"
SOURCE_WORKSPACE_TOOLS = "workspace_tools"
SOURCE_REPLY_BODY = "reply_body"
SOURCE_NEXT_STEP = "next_step"
SOURCE_HISTORY = "history"
FACT_SOURCES = frozenset(
    {
        SOURCE_USER_MESSAGE,
        SOURCE_CURRENT_FILE,
        SOURCE_WORKSPACE_TOOLS,
        SOURCE_REPLY_BODY,
        SOURCE_NEXT_STEP,
        SOURCE_HISTORY,
    }
)

VERDICT_GROUNDED = "grounded"
VERDICT_UNGROUNDED = "ungrounded"
VERDICT_UNVERIFIABLE = "unverifiable"

OUTCOME_GROUNDED = "grounded"
OUTCOME_CORRECTED = "corrected"
OUTCOME_DOWNGRADED = "downgraded"
# Set by the assembly layer when it deliberately skips grounding on a
# recovery / local-fallback turn (DESIGN.md §2.1); this pure layer never
# fabricates it.
OUTCOME_RECOVERY_OVERRIDE = "recovery_override"

# Memory fields whose provenance one turn records (DESIGN.md §2.1/§2.7).
MEMORY_PROVENANCE_FIELDS = (
    "summary",
    "next_step",
    "decision",
    "teaching_note",
    "review_note",
    "review_queue_summary",
    "evidence",
    "focus",
)

# Bounds keep the pure layer predictable on pathological texts.
_MAX_NEXT_STEP_CLAIMS = 24
_MAX_REPLY_CLAIMS = 48
_MAX_LEARNER_FACTS = 64
_MAX_WORKSPACE_FACTS = 64

# Claim boundaries: sentence enders and line breaks. Commas are deliberately
# kept inside a claim — splitting granularity never changes the "every symbol
# of every claim must anchor" verdict, only diagnostics.
_CLAIM_BOUNDARY = re.compile(r"[\n。！？!?；;]+")
_LEADING_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)、])\s*")
_ERROR_TOKEN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning|Fault)\b")
_FILE_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_./-]*\.[A-Za-z0-9]+")


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
    not a demanded function or call site. Slice 2 keeps classifying these as
    file pointers but no longer lets them pass unconditionally: they anchor in
    the turn corpora or through the injected ``file_exists`` check, and stay
    ``unverifiable`` (never a downgrade) when no check is possible.
    """
    parts = symbol.split(".")
    return len(parts) == 2 and parts[-1].lower() in _FILE_SUFFIX_SYMBOLS


def _is_abbreviation(token: str) -> bool:
    """Dotted abbreviations such as ``e.g`` / ``i.e`` are prose, not symbols."""
    parts = [part for part in token.split(".") if part]
    return bool(parts) and all(len(part) <= 2 for part in parts) and token.islower()


def _normalize_claim_path(value: object) -> str:
    """Normalize a file-pointer claim value (backslashes, ``./`` prefix)."""
    text = str(value or "").strip().strip("`").strip()
    text = text.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class TeachingFact:
    """One claim-level fact of a teaching turn (DESIGN.md §2.1)."""

    kind: str
    value: str
    provenance: str = PROVENANCE_MODEL_CLAIM
    source: str = ""
    turn_id: str = ""


@dataclass(frozen=True)
class GroundingConflict:
    """A same-domain conflict between a reply claim and a next-step claim.

    The element type is part of the frozen ``TeachingTurnFacts`` structure.
    Population and winner arbitration land with the R2 consistency rules
    (DESIGN.md §2.5③); R1 only carries the contract.
    """

    domain: str
    reply_claim: TeachingFact
    next_step_claim: TeachingFact
    winner: str = ""


@dataclass(frozen=True)
class TeachingTurnFacts:
    """The turn's facts and verdicts — the single grounding authority.

    The raw corpus texts are kept on the object because
    ``evaluate_turn_grounding`` is a pure function of the facts alone; the
    claim/list fields are mutable containers (frozen guards rebinding, and
    ``evaluate_turn_grounding`` is the designated single writer of
    ``verdicts`` / ``gate_outcome`` for its own turn).
    """

    turn_id: str = ""
    request_id: str = ""
    reply_text: str = ""
    code_text: str = ""
    history_text: str = ""
    user_message: str = ""
    learner_provided: list[TeachingFact] = field(default_factory=list)
    workspace_verified: list[TeachingFact] = field(default_factory=list)
    next_step_claims: list[TeachingFact] = field(default_factory=list)
    reply_claims: list[TeachingFact] = field(default_factory=list)
    conflicts: list[GroundingConflict] = field(default_factory=list)
    verdicts: dict[str, str] = field(default_factory=dict)
    gate_outcome: str = OUTCOME_GROUNDED
    memory_provenance: dict[str, str] = field(default_factory=dict)
    # Live file-existence input injected by the assembly layer; ``None`` means
    # existence cannot be checked (file-pointer verdicts stay ``unverifiable``).
    file_exists: Callable[[str], bool | None] | None = None


@dataclass(frozen=True)
class WorkspaceEvidence:
    """Workspace verification input for ``build_teaching_turn_facts``.

    ``file_exists`` answers ``True`` / ``False`` / ``None`` (``None`` = cannot
    verify: remote or URI workspace, ``tools.py`` URL roots). ``unverifiable``
    additionally declares the whole turn unverifiable, which is equivalent to
    passing no checker.
    """

    verified_facts: tuple[TeachingFact, ...] = ()
    file_exists: Callable[[str], bool | None] | None = None
    unverifiable: bool = False


def claim_key(kind: str, value: object) -> str:
    """Stable key for a claim: ``kind:normalized_value`` (DESIGN.md §2.1)."""
    normalized = normalize_code_symbol(value)
    base = normalized or normalize_anchor_text(value)
    return f"{kind}:{base}"


def claim_domain(fact: TeachingFact) -> str:
    """Normalized symbol / file-path domain used for cross-claim arbitration.

    Symbol domains keep their case (``parse`` vs ``Parse`` are different
    symbols); free-text fragments fall back to whitespace-normalized lowercase
    text.
    """
    if fact.kind == FACT_KIND_FILE_PATH:
        return _normalize_claim_path(fact.value)
    symbol = normalize_code_symbol(fact.value)
    if symbol:
        return symbol
    return normalize_anchor_text(fact.value).lower()


def _claim_segments(text: str) -> list[str]:
    segments: list[str] = []
    for raw in _CLAIM_BOUNDARY.split(text):
        segment = _LEADING_LIST_MARKER.sub("", raw).strip()
        if segment:
            segments.append(segment)
    return segments


def _claim_tokens(segment: str) -> list[str]:
    """Significant symbol-bearing tokens of one claim segment, in text order."""
    tokens: list[str] = []

    def _add(candidate: str) -> None:
        value = normalize_code_symbol(candidate)
        if value and value not in tokens:
            tokens.append(value)

    for literal in _BACKTICK_LITERAL.findall(segment):
        stripped = literal.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) > 1:
            # Multi-token literals are commands/fragments ("python stuck.py",
            # "hi = len(xs) - 1", "for i, x in enumerate(xs)"): requiring
            # verbatim containment of the whole literal would demand the
            # coach's exact phrasing appear in the learner's code. Clean
            # identifier sub-tokens carry the claim; keywords and punctuation
            # fragments never do. File pointers and dotted identifiers inside
            # the literal are covered by the scans below.
            for part in parts:
                candidate = part.strip(":;,.!?)]}\"'")
                if _is_identifier_like(candidate) and candidate.lower() not in _LANGUAGE_KEYWORDS:
                    _add(candidate)
            continue
        if _is_abbreviation(stripped) and not _is_file_reference_symbol(stripped):
            continue
        _add(stripped)
    # Workspace file pointers can carry hyphens and directories that the
    # dotted-identifier regex cannot span (``mutable-default.py``,
    # ``src/utils.py``); collect them through the file-token scan first.
    for match in _FILE_TOKEN.finditer(segment):
        candidate = _normalize_claim_path(match.group(0))
        if _is_file_reference_symbol(candidate):
            _add(candidate)
    for match in _DOTTED_IDENTIFIER.finditer(segment):
        dotted = match.group(0)
        if "." not in dotted:
            continue
        if _is_abbreviation(dotted) and not _is_file_reference_symbol(dotted):
            continue
        # A dotted token glued to a hyphen/slash is the tail of a compound
        # file reference already collected ("mutable-default.py" must not also
        # contribute "default.py").
        before = segment[match.start() - 1] if match.start() > 0 else ""
        if before in {"-", "/"}:
            continue
        _add(dotted)
    for match in _PLAIN_IDENTIFIER.finditer(segment):
        token = match.group(0)
        if not _looks_like_code_identifier(token):
            continue
        # A token touching a dot is part of a dotted token already collected
        # ("legacy_report.py" must not also contribute the bare "legacy_report").
        before = segment[match.start() - 1] if match.start() > 0 else ""
        after = segment[match.end()] if match.end() < len(segment) else ""
        if before == "." or after == ".":
            continue
        _add(token)
    return tokens


def _classify_claim(token: str, *, source: str, turn_id: str, provenance: str) -> TeachingFact:
    value = normalize_code_symbol(token)
    if _is_file_reference_symbol(value):
        return TeachingFact(
            kind=FACT_KIND_FILE_PATH,
            value=_normalize_claim_path(value),
            provenance=provenance,
            source=source,
            turn_id=turn_id,
        )
    if _is_identifier_like(value):
        kind = FACT_KIND_SYMBOL
    elif "(" in value:
        kind = FACT_KIND_CALL_SITE
    else:
        kind = FACT_KIND_CODE_FRAGMENT
    return TeachingFact(kind=kind, value=value, provenance=provenance, source=source, turn_id=turn_id)


def extract_claim_facts(
    text: object,
    *,
    source: str,
    turn_id: str = "",
    provenance: str = PROVENANCE_MODEL_CLAIM,
    limit: int = _MAX_NEXT_STEP_CLAIMS,
) -> list[TeachingFact]:
    """Extract per-claim facts from free text (claim-level, deduplicated).

    Backticked literals always count; bare snake_case/camelCase identifiers and
    file pointers count; bare lowercase prose words and dotted abbreviations
    (``e.g``) never do. Common toolchain words (``pytest``, ``print``) are not
    claims. Multi-token backticked literals contribute their significant
    sub-tokens only.
    """
    source_text = str(text or "")
    if not source_text.strip():
        return []
    facts: list[TeachingFact] = []
    seen: set[str] = set()
    for segment in _claim_segments(source_text):
        for token in _claim_tokens(segment):
            if _is_common_toolchain_symbol(token):
                continue
            fact = _classify_claim(token, source=source, turn_id=turn_id, provenance=provenance)
            key = claim_key(fact.kind, fact.value)
            if key in seen:
                continue
            seen.add(key)
            facts.append(fact)
            if len(facts) >= limit:
                return facts
    return facts


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _next_step_value_to_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        for key in ("title", "label", "next_step", "nextStep", "summary"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""
    attribute = getattr(value, "next_step", None)
    if isinstance(attribute, str) and attribute.strip():
        return attribute.strip()
    return ""


def _next_step_text_from_agent_evidence(agent_meta: Mapping[str, object]) -> str:
    for key in ("next_step", "nextStep", "structured_next_step"):
        text = _next_step_value_to_text(agent_meta.get(key))
        if text:
            return text
    return ""


def _coerce_workspace_fact(item: object) -> TeachingFact | None:
    if isinstance(item, TeachingFact):
        return item
    if not isinstance(item, Mapping):
        return None
    kind = str(item.get("kind") or FACT_KIND_SYMBOL).strip() or FACT_KIND_SYMBOL
    value = str(item.get("value") or "").strip()
    if not value:
        return None
    if kind == FACT_KIND_FILE_PATH:
        normalized = _normalize_claim_path(value)
    else:
        normalized = normalize_code_symbol(value) or normalize_anchor_text(value)
    if not normalized:
        return None
    provenance = str(item.get("provenance") or PROVENANCE_TOOL_VERIFIED).strip()
    source = str(item.get("source") or SOURCE_WORKSPACE_TOOLS).strip()
    return TeachingFact(
        kind=kind,
        value=normalized,
        provenance=provenance or PROVENANCE_TOOL_VERIFIED,
        source=source or SOURCE_WORKSPACE_TOOLS,
        turn_id=str(item.get("turn_id") or ""),
    )


def _as_file_checker(value: object) -> Callable[[str], bool | None] | None:
    """Wrap an untrusted callable into the precise file-checker contract.

    Only a literal ``True`` / ``False`` answer counts; anything else (including
    ``None`` and non-boolean returns) means "cannot verify" and maps to the
    ``unverifiable`` verdict.
    """
    if not callable(value):
        return None

    def _checked(path: str) -> bool | None:
        result = value(path)
        if result is True:
            return True
        if result is False:
            return False
        return None

    return _checked


def _normalize_workspace_evidence(raw: object) -> tuple[list[TeachingFact], Callable[[str], bool | None] | None]:
    """Accept None / WorkspaceEvidence / mapping / fact sequence."""
    facts_raw: object = None
    file_exists: object = None
    unverifiable = False
    if isinstance(raw, WorkspaceEvidence):
        return list(raw.verified_facts), None if raw.unverifiable else raw.file_exists
    if isinstance(raw, Mapping):
        facts_raw = raw.get("verified_facts")
        if facts_raw is None:
            facts_raw = raw.get("facts")
        file_exists = raw.get("file_exists")
        unverifiable = _as_bool(raw.get("unverifiable"))
    elif isinstance(raw, (list, tuple)):
        facts_raw = raw
    else:
        return [], None
    facts: list[TeachingFact] = []
    if isinstance(facts_raw, (list, tuple)):
        for item in facts_raw:
            fact = _coerce_workspace_fact(item)
            if fact is not None:
                facts.append(fact)
            if len(facts) >= _MAX_WORKSPACE_FACTS:
                break
    checker: Callable[[str], bool | None] | None = None
    if not unverifiable:
        checker = _as_file_checker(file_exists)
    return facts, checker


def _learner_provided_facts(
    user_message: str,
    code_text: str,
    *,
    turn_id: str,
) -> list[TeachingFact]:
    facts = extract_claim_facts(
        user_message,
        source=SOURCE_USER_MESSAGE,
        turn_id=turn_id,
        provenance=PROVENANCE_LEARNER_PROVIDED,
        limit=_MAX_LEARNER_FACTS,
    )
    seen = {claim_key(fact.kind, fact.value) for fact in facts}

    def _add(fact: TeachingFact) -> bool:
        key = claim_key(fact.kind, fact.value)
        if key in seen:
            return False
        seen.add(key)
        facts.append(fact)
        return len(facts) >= _MAX_LEARNER_FACTS

    for match in _ERROR_TOKEN.finditer(user_message):
        if _add(
            TeachingFact(
                kind=FACT_KIND_ERROR_TEXT,
                value=match.group(0),
                provenance=PROVENANCE_LEARNER_PROVIDED,
                source=SOURCE_USER_MESSAGE,
                turn_id=turn_id,
            )
        ):
            return facts
    for match in _FILE_TOKEN.finditer(code_text):
        candidate = _normalize_claim_path(match.group(0))
        if not _is_file_reference_symbol(candidate):
            continue
        if _add(
            TeachingFact(
                kind=FACT_KIND_FILE_PATH,
                value=candidate,
                provenance=PROVENANCE_LEARNER_PROVIDED,
                source=SOURCE_CURRENT_FILE,
                turn_id=turn_id,
            )
        ):
            return facts
    return facts


def build_teaching_turn_facts(
    *,
    turn_id: str,
    reply_text: str,
    code_text: str,
    history_text: str,
    user_message: str,
    workspace_evidence: object = None,
    agent_evidence: object = None,
    next_step_text: str | None = None,
) -> TeachingTurnFacts:
    """Build the turn's facts (the single extraction implementation).

    The structured next step enters through ``next_step_text`` (preferred) or
    ``agent_evidence["next_step"]``; ``agent_evidence`` is the structured agent
    output (``agent_meta`` shape: ``next_step`` / ``fell_back`` / optional
    ``verified_facts`` / ``request_id``). ``workspace_evidence`` carries the
    workspace verification facts and the optional ``file_exists`` checker
    (see ``WorkspaceEvidence``).
    """
    agent_meta: Mapping[str, object] = agent_evidence if isinstance(agent_evidence, Mapping) else {}
    fell_back = _as_bool(agent_meta.get("fell_back"))
    provenance = PROVENANCE_LOCAL_FALLBACK if fell_back else PROVENANCE_MODEL_CLAIM

    resolved_next_step = str(next_step_text or "") if next_step_text is not None else ""
    if not resolved_next_step:
        resolved_next_step = _next_step_text_from_agent_evidence(agent_meta)

    reply_source = str(reply_text or "")
    code_source = str(code_text or "")
    user_source = str(user_message or "")

    workspace_facts, checker = _normalize_workspace_evidence(workspace_evidence)
    for key in ("verified_facts", "workspace_verified"):
        extra = agent_meta.get(key)
        if isinstance(extra, (list, tuple)):
            for item in extra:
                fact = _coerce_workspace_fact(item)
                if fact is not None:
                    workspace_facts.append(fact)
                if len(workspace_facts) >= _MAX_WORKSPACE_FACTS:
                    break

    return TeachingTurnFacts(
        turn_id=turn_id,
        request_id=str(agent_meta.get("request_id") or ""),
        reply_text=reply_source,
        code_text=code_source,
        history_text=str(history_text or ""),
        user_message=user_source,
        learner_provided=_learner_provided_facts(user_source, code_source, turn_id=turn_id),
        workspace_verified=workspace_facts,
        next_step_claims=extract_claim_facts(
            resolved_next_step,
            source=SOURCE_NEXT_STEP,
            turn_id=turn_id,
            provenance=provenance,
            limit=_MAX_NEXT_STEP_CLAIMS,
        ),
        reply_claims=extract_claim_facts(
            reply_source,
            source=SOURCE_REPLY_BODY,
            turn_id=turn_id,
            provenance=PROVENANCE_MODEL_CLAIM,
            limit=_MAX_REPLY_CLAIMS,
        ),
        memory_provenance={name: provenance for name in MEMORY_PROVENANCE_FIELDS},
        file_exists=checker,
    )


def _anchoring_corpora(facts: TeachingTurnFacts) -> list[str]:
    """reply ∪ current code ∪ history ∪ workspace_verified ∪ learner_provided."""
    corpora: list[str] = []
    for text in (facts.reply_text, facts.code_text, facts.history_text, facts.user_message):
        if str(text or "").strip():
            corpora.append(str(text))
    for fact in (*facts.learner_provided, *facts.workspace_verified):
        if fact.value:
            corpora.append(fact.value)
    return corpora


def _file_claim_verdict(
    value: str,
    corpora: list[str],
    *,
    file_exists: Callable[[str], bool | None] | None,
) -> str:
    for corpus in corpora:
        if symbol_in_text(value, corpus):
            return VERDICT_GROUNDED
    if file_exists is None:
        return VERDICT_UNVERIFIABLE
    try:
        exists = file_exists(value)
    except OSError:
        # A filesystem that cannot answer is "cannot verify", never a
        # fabricated downgrade.
        return VERDICT_UNVERIFIABLE
    if exists is True:
        return VERDICT_GROUNDED
    if exists is False:
        return VERDICT_UNGROUNDED
    return VERDICT_UNVERIFIABLE


def _claim_verdict(fact: TeachingFact, corpora: list[str], *, file_exists: Callable[[str], bool | None] | None) -> str:
    if fact.kind == FACT_KIND_FILE_PATH:
        return _file_claim_verdict(fact.value, corpora, file_exists=file_exists)
    if any(symbol_in_text(fact.value, corpus) for corpus in corpora):
        return VERDICT_GROUNDED
    return VERDICT_UNGROUNDED


def _evaluate_claims(
    claims: list[TeachingFact],
    facts: TeachingTurnFacts,
) -> tuple[dict[str, str], list[str]]:
    corpora = _anchoring_corpora(facts)
    verdicts: dict[str, str] = {}
    ungrounded: list[str] = []
    for fact in claims:
        verdict = _claim_verdict(fact, corpora, file_exists=facts.file_exists)
        verdicts[claim_key(fact.kind, fact.value)] = verdict
        if verdict == VERDICT_UNGROUNDED and fact.value not in ungrounded:
            ungrounded.append(fact.value)
    return verdicts, ungrounded


def _apply_facts_outcome(
    facts: TeachingTurnFacts,
    *,
    verdicts: dict[str, str],
    gate_outcome: str,
) -> None:
    """Record the decision on the facts object (single designated writer).

    ``TeachingTurnFacts`` is frozen against rebinding; the grounding decision
    function is the one writer of ``verdicts`` / ``gate_outcome`` for its own
    turn, and it writes at most once per evaluation.
    """
    facts.verdicts.clear()
    facts.verdicts.update(verdicts)
    object.__setattr__(facts, "gate_outcome", gate_outcome)


def _retry_text(retry_generate: Callable[[], object]) -> str:
    return str(retry_generate() or "").strip()


@dataclass(frozen=True)
class GroundingDecision:
    """Outcome of validating one coach turn's structured next step."""

    grounded: bool
    referenced_symbols: list[str] = field(default_factory=list)
    retry_used: bool = False
    requires_confirmation: bool = False
    corrected_next_step: str | None = None

    @property
    def downgraded(self) -> bool:
        return self.requires_confirmation


def evaluate_turn_grounding(
    facts: TeachingTurnFacts,
    *,
    retry_generate: Callable[[], object] | None = None,
) -> GroundingDecision:
    """Validate the turn's next-step claims; retry at most once; then downgrade.

    Every symbol of every next-step claim must anchor in the turn corpora
    (reply ∪ code ∪ history ∪ workspace_verified ∪ learner_provided); file
    pointers use the injected existence checker with the ``unverifiable``
    escape. When ``retry_generate`` is provided it is called at most once; a
    grounded regeneration travels back in ``corrected_next_step`` (the caller
    writes it back via ``model_copy``), an ungrounded or empty regeneration
    downgrades to ``requires_confirmation``.

    The decision is computed once per turn by its caller (the assembly layer
    caches it on the payload); this function is pure and deterministic, and
    performs its single facts write through ``_apply_facts_outcome``.
    """
    claims = list(facts.next_step_claims)
    verdicts, ungrounded = _evaluate_claims(claims, facts)
    if not ungrounded:
        _apply_facts_outcome(facts, verdicts=verdicts, gate_outcome=OUTCOME_GROUNDED)
        return GroundingDecision(
            grounded=True,
            referenced_symbols=[],
            retry_used=False,
            requires_confirmation=False,
            corrected_next_step=None,
        )
    if retry_generate is not None:
        retried_text = _retry_text(retry_generate)
        if retried_text:
            retried_claims = extract_claim_facts(
                retried_text,
                source=SOURCE_NEXT_STEP,
                turn_id=facts.turn_id,
                provenance=facts.memory_provenance.get("next_step", PROVENANCE_MODEL_CLAIM),
                limit=_MAX_NEXT_STEP_CLAIMS,
            )
            retried_verdicts, retried_ungrounded = _evaluate_claims(retried_claims, facts)
            if not retried_ungrounded:
                facts.next_step_claims[:] = retried_claims
                _apply_facts_outcome(
                    facts,
                    verdicts=retried_verdicts,
                    gate_outcome=OUTCOME_CORRECTED,
                )
                return GroundingDecision(
                    grounded=True,
                    referenced_symbols=[],
                    retry_used=True,
                    requires_confirmation=False,
                    corrected_next_step=retried_text,
                )
        _apply_facts_outcome(facts, verdicts=verdicts, gate_outcome=OUTCOME_DOWNGRADED)
        return GroundingDecision(
            grounded=False,
            referenced_symbols=ungrounded,
            retry_used=True,
            requires_confirmation=True,
            corrected_next_step=None,
        )
    _apply_facts_outcome(facts, verdicts=verdicts, gate_outcome=OUTCOME_DOWNGRADED)
    return GroundingDecision(
        grounded=False,
        referenced_symbols=ungrounded,
        retry_used=False,
        requires_confirmation=True,
        corrected_next_step=None,
    )


def grounding_outcome(decision: GroundingDecision) -> str:
    """Assembly-facing outcome vocabulary: grounded | corrected | downgraded."""
    if decision.requires_confirmation:
        return OUTCOME_DOWNGRADED
    if decision.retry_used and decision.corrected_next_step:
        return OUTCOME_CORRECTED
    return OUTCOME_GROUNDED


def _legacy_turn_facts(
    next_step_text: object,
    reply_text: object,
    code_text: object,
    extra_context: object,
) -> TeachingTurnFacts:
    return build_teaching_turn_facts(
        turn_id="",
        reply_text=str(reply_text or ""),
        code_text=str(code_text or ""),
        history_text=str(extra_context or ""),
        user_message="",
        next_step_text=str(next_step_text or ""),
    )


def next_step_is_grounded(
    next_step_text: object,
    reply_text: object,
    code_text: object,
    *,
    extra_context: object = "",
) -> bool:
    """Validate that a structured next step is grounded in the turn's facts.

    Slice 2: every symbol of every claim must anchor (the former
    "any referenced symbol hit" rule is gone); file pointers anchor through
    the corpora and stay ``unverifiable`` without a checker; common toolchain
    words and dotted abbreviations are not claims. Prose-only next steps are
    grounded by definition.
    """
    return evaluate_turn_grounding(
        _legacy_turn_facts(next_step_text, reply_text, code_text, extra_context)
    ).grounded


def evaluate_next_step_grounding(
    next_step_text: object,
    reply_text: object,
    code_text: object,
    *,
    extra_context: object = "",
    retry_generate: Callable[[], object] | None = None,
) -> GroundingDecision:
    """Legacy entry point routed through the strict per-claim core.

    Kept for existing assembly callers and the maturity harness; new callers
    should build ``TeachingTurnFacts`` once and call
    ``evaluate_turn_grounding``. ``referenced_symbols`` now lists the
    **ungrounded** symbols only.
    """
    return evaluate_turn_grounding(
        _legacy_turn_facts(next_step_text, reply_text, code_text, extra_context),
        retry_generate=retry_generate,
    )


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
