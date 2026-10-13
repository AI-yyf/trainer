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

R2 additions (2026-10-13):

- ``reply_claims`` verdicts (anchored in the learner's turn facts or not;
  diagnostic only — they never downgrade a turn, explicit false-positive
  budget) plus ``domain_backing`` implementing the
  ``workspace_verified > learner_provided > model_claim`` ranking.
- ``conflicts``: same-domain reply/next-step pairs that no workspace/learner
  fact backs and that the next step *demands* (the reply's own introduction of
  a new symbol — ``enumerate`` — is never a conflict); the record prefers the
  reply's visible next step and flags whether it corroborated the demand.
- demand guard: a next step request whose marker *directly governs* a fact the
  learner already provided (repeat-asking) or a symbol with no backing at all
  (fabrication demand) is ungrounded. Running a function and pasting its output
  (「运行 X，把输出贴回来」) is not a demand on X (2026-10-13 review).
- file pointers in a creation context ("创建/新建/create ...") stay
  ``unverifiable`` instead of tripping the existence checker.
- ``retry_used`` means "a regeneration was attempted for this decision"
  (including empty/unusable regenerations) — both the rules layer and the
  assembly derive it from this one implementation;
  ``memory_provenance_summary`` builds the field-level mapping consumed by
  ``MemoryService.record_turn_reflection``.

Symbol extraction mirrors the acceptance-criteria signal rule in
``app/training/card_generator.py`` (``_criterion_code_signals``): a backticked
literal or a bare snake_case/camelCase identifier counts as a code symbol;
free-form prose without any code symbol never does.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .reply_continuity import visible_next_step

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
_MESSAGE_PREFIX_MIN_LENGTH = 6
# The idea lane deliberately re-anchors on the learner's stated idea
# ("我有一个 AI idea") — a topic declaration, not an event report — so a
# message-opening anchor carrying a topic marker survives the drift check.
_IDEA_LANE_ANCHOR_MARKERS = ("idea", "点子")

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
# Reserved keys of the mapping ``record_turn_reflection`` consumes (§2.6/§2.7).
MEMORY_PROVENANCE_GROUNDING_OUTCOME = "grounding_outcome"
MEMORY_PROVENANCE_CONFLICTED_CLAIMS = "conflicted_claims"

# Domain backing ranks (DESIGN.md §2.5③): the ranking that decides which side
# of a same-domain pair wins; "" means no workspace/learner fact backs it.
BACKING_WORKSPACE_VERIFIED = "workspace_verified"
BACKING_LEARNER_PROVIDED = "learner_provided"

# Bounds keep the pure layer predictable on pathological texts.
_MAX_NEXT_STEP_CLAIMS = 24
_MAX_REPLY_CLAIMS = 48
_MAX_LEARNER_FACTS = 96
_MAX_WORKSPACE_FACTS = 64

# Claim boundaries: sentence enders and line breaks. Commas are deliberately
# kept inside a claim — splitting granularity never changes the "every symbol
# of every claim must anchor" verdict, only diagnostics.
_CLAIM_BOUNDARY = re.compile(r"[\n。！？!?；;]+")
_LEADING_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)、])\s*")
_ERROR_TOKEN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning|Fault)\b")
_FILE_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_./-]*\.[A-Za-z0-9]+")

# Creation/forward-looking instructions: the named file does not exist yet by
# design ("创建/新建/create ..."), so a missing-file checker answer must not be
# read as a fabrication (DESIGN.md §2.5⑥).
_CREATION_VERB_PATTERN = re.compile(
    r"(?:创建|新建|新增|建立|生成|写一个|写个|建一个|建个|补充一个|加一个新|"
    r"create|new file|add a new|scaffold|generate|write a|make a)",
    re.IGNORECASE,
)
# Info-transfer request markers (DESIGN.md §2.5③): asking the learner to
# hand over a fact they already provided (repeat-asking), or to hand over a
# fact with no workspace/learner backing at all (fabrication demand). A marker
# only fires when it *directly governs* the claimed symbol (see
# ``_DEMAND_TARGET_PATTERNS``) — "运行 X，把输出贴回来" asks for the run's
# output, not for X's source, and must stay grounded (2026-10-13 review).
# Direct-object forms: the captured ``target`` span is what the request asks
# the learner to hand over. Only a claim whose value appears inside a target
# span is "demanded".
_DEMAND_TARGET_PATTERNS = (
    # 把 X（的实现/定义/代码/报错…）贴出来 / 发我 / …
    re.compile(
        r"把\s*(?:你的|你写的|那个|这个|刚才的)?\s*(?P<target>[^，。；;,\n]{1,60}?)"
        r"\s*(?:贴出来|贴一下|贴给我|贴回来|贴回|发我|发一下|发给|粘贴|分享|给我看|给我)",
    ),
    # 给我 X / 请提供 X / 贴出 X（marker 直接后接对象）
    re.compile(
        r"(?:请提供|提供一下|贴出|发我|发一下|分享|给我)\s*(?:你的|你写的|那个|这个|一下)?\s*"
        r"(?P<target>[^\s，。；;,]{1,60})",
    ),
    # English: paste/share/provide/send me/give me/show me + direct object
    re.compile(
        r"(?:please\s+)?(?:paste|share|provide|send\s+me|upload|give\s+me|show\s+me)"
        r"\s+(?:me\s+)?(?:the\s+|your\s+)?(?P<target>[A-Za-z0-9_.`()\[\]{}<>/=:+-]{1,60})",
        re.IGNORECASE,
    ),
)


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

    ``reply_step_corroborated`` records that the reply's own visible next step
    (``visible_next_step``) mentioned the domain — i.e. the visible step and
    the structured step were compared, and this demand was (not) promised by
    the reply itself.
    """

    domain: str
    reply_claim: TeachingFact
    next_step_claim: TeachingFact
    winner: str = ""
    reply_step_corroborated: bool = False


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
    next_step_text: str = ""
    visible_next_step: str = ""
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
    # Current-file symbols count as learner-provided facts too (§2.2): the
    # repeat-asking guard must see that the coach already has the learner's
    # code in hand ("给我 `find` 的函数名" when `find` sits in the file).
    for fact in extract_claim_facts(
        code_text,
        source=SOURCE_CURRENT_FILE,
        turn_id=turn_id,
        provenance=PROVENANCE_LEARNER_PROVIDED,
        limit=_MAX_LEARNER_FACTS,
    ):
        if _add(fact):
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
        next_step_text=resolved_next_step,
        visible_next_step=visible_next_step(reply_source),
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


def domain_backing(facts: TeachingTurnFacts, domain: str) -> str:
    """Best fact backing for one claim domain (DESIGN.md §2.5③ ranking).

    Returns ``"workspace_verified"`` when a workspace fact shares the domain,
    ``"learner_provided"`` when a learner fact does, and ``""`` when only the
    model's own text carries it (the model-claim rank loses to both facts).
    """
    if not domain:
        return ""
    for fact in facts.workspace_verified:
        if claim_domain(fact) == domain:
            return BACKING_WORKSPACE_VERIFIED
    for fact in facts.learner_provided:
        if claim_domain(fact) == domain:
            return BACKING_LEARNER_PROVIDED
    return ""


def memory_provenance_summary(
    facts: TeachingTurnFacts,
    decision: GroundingDecision | None = None,
) -> dict[str, str]:
    """Build the field→provenance mapping ``record_turn_reflection`` consumes.

    Adds the reserved ``grounding_outcome`` key (from the decision) and the
    reserved ``conflicted_claims`` key (newline-joined argument domains of the
    turn's recorded conflicts, if any) on top of the per-field provenance.
    """
    summary = dict(facts.memory_provenance)
    if decision is not None:
        summary[MEMORY_PROVENANCE_GROUNDING_OUTCOME] = grounding_outcome(decision)
    conflicted = [conflict.domain for conflict in facts.conflicts if conflict.domain]
    if conflicted:
        summary[MEMORY_PROVENANCE_CONFLICTED_CLAIMS] = "\n".join(dict.fromkeys(conflicted))
    return summary


def _anchoring_corpora(facts: TeachingTurnFacts, *, include_reply: bool = True) -> list[str]:
    """reply ∪ current code ∪ history ∪ workspace_verified ∪ learner_provided.

    ``include_reply=False`` is the reply-claim view: a claim inside the reply
    must not be anchored by the reply text itself (that would be trivially
    true and useless as a diagnostic).
    """
    corpora: list[str] = []
    texts: list[str] = [facts.code_text, facts.history_text, facts.user_message]
    if include_reply:
        texts.insert(0, facts.reply_text)
    for text in texts:
        if str(text or "").strip():
            corpora.append(str(text))
    for fact in (*facts.learner_provided, *facts.workspace_verified):
        if fact.value:
            corpora.append(fact.value)
    return corpora


def _claim_segments_for(
    facts: TeachingTurnFacts,
    value: str,
    *,
    context_text: str | None = None,
) -> list[str]:
    """Claim segments that mention ``value`` (claim-level context).

    ``context_text`` defaults to ``facts.next_step_text``; the retry re-check
    passes the regenerated text so creation/demand context follows the text
    actually being evaluated (2026-10-13 review).
    """
    source = facts.next_step_text if context_text is None else context_text
    if not value or not str(source or "").strip():
        return []
    return [
        segment
        for segment in _claim_segments(str(source))
        if symbol_in_text(value, segment)
    ]


def _is_demanded_target(segment: str, value: str) -> bool:
    """True when an info-transfer request in ``segment`` governs ``value``.

    The marker must *directly govern* the symbol (「把 X 的实现贴出来」、
    「给我 X」、``paste X``); "运行 X，把输出贴回来" asks for X's runtime
    output, not for X itself (2026-10-13 review), so it is not a demand.
    """
    for pattern in _DEMAND_TARGET_PATTERNS:
        for match in pattern.finditer(segment):
            target = match.group("target") or ""
            if target and symbol_in_text(value, target):
                return True
    return False


def _claim_context(
    facts: TeachingTurnFacts,
    value: str,
    *,
    context_text: str | None = None,
) -> tuple[bool, bool]:
    """(creation_context, demand_context) of the segments claiming ``value``.

    Creation context: the instruction creates the artifact ("创建/新建/create
    ..."), so a missing file proves nothing. Demand context: a direct-object
    info-transfer request (「把 X 贴出来」/"paste X") that is not itself a
    creation instruction.
    """
    segments = _claim_segments_for(facts, value, context_text=context_text)
    creation = any(_CREATION_VERB_PATTERN.search(segment) for segment in segments)
    demand = any(
        not _CREATION_VERB_PATTERN.search(segment) and _is_demanded_target(segment, value)
        for segment in segments
    )
    return creation, demand


def _file_claim_verdict(
    value: str,
    corpora: list[str],
    *,
    file_exists: Callable[[str], bool | None] | None,
    creation_context: bool = False,
) -> str:
    for corpus in corpora:
        if symbol_in_text(value, corpus):
            return VERDICT_GROUNDED
    if creation_context or file_exists is None:
        # A file the instruction asks to create does not exist yet by design
        # (DESIGN.md §2.5⑥): neither "verified" nor a downgrade reason.
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


def _claim_verdict(
    fact: TeachingFact,
    corpora: list[str],
    *,
    file_exists: Callable[[str], bool | None] | None,
    creation_context: bool = False,
) -> str:
    if fact.kind == FACT_KIND_FILE_PATH:
        return _file_claim_verdict(
            fact.value,
            corpora,
            file_exists=file_exists,
            creation_context=creation_context,
        )
    if any(symbol_in_text(fact.value, corpus) for corpus in corpora):
        return VERDICT_GROUNDED
    return VERDICT_UNGROUNDED


def _evaluate_claims(
    claims: list[TeachingFact],
    facts: TeachingTurnFacts,
    *,
    include_reply: bool = True,
    apply_demand_guard: bool = False,
    context_text: str | None = None,
) -> tuple[dict[str, str], list[str]]:
    corpora = _anchoring_corpora(facts, include_reply=include_reply)
    verdicts: dict[str, str] = {}
    ungrounded: list[str] = []
    for fact in claims:
        creation_context, demand_context = _claim_context(
            facts,
            fact.value,
            context_text=context_text,
        )
        verdict = _claim_verdict(
            fact,
            corpora,
            file_exists=facts.file_exists,
            creation_context=creation_context,
        )
        if verdict == VERDICT_GROUNDED and apply_demand_guard and demand_context:
            backing = domain_backing(facts, claim_domain(fact))
            if backing in ("", BACKING_LEARNER_PROVIDED):
                # Repeat-asking a fact the learner already provided, or
                # demanding a fact no workspace/learner fact backs at all
                # (DESIGN.md §2.5③) — the reply merely claiming it does not
                # count as evidence.
                verdict = VERDICT_UNGROUNDED
        verdicts[claim_key(fact.kind, fact.value)] = verdict
        if verdict == VERDICT_UNGROUNDED and fact.value not in ungrounded:
            ungrounded.append(fact.value)
    return verdicts, ungrounded


def _collect_conflicts(
    facts: TeachingTurnFacts,
    claims: list[TeachingFact],
    *,
    context_text: str | None = None,
) -> list[GroundingConflict]:
    """Record the actionable same-domain conflicts (DESIGN.md §2.5②③).

    Only a *direct-object demand* on a domain that the model merely claims (no
    workspace/learner backing) is recorded — a reply introducing a new symbol
    (``enumerate``) and the next step suggesting it stays clean (explicit
    false-positive budget). The reply side prefers the reply's own visible next
    step so ``reply_step_corroborated`` records whether the reply *itself*
    promised the demanded domain (``visible_next_step`` participation).
    """
    if not facts.reply_claims:
        return []
    reply_by_domain: dict[str, TeachingFact] = {}
    for fact in facts.reply_claims:
        reply_by_domain.setdefault(claim_domain(fact), fact)
    visible_by_domain: dict[str, TeachingFact] = {}
    if facts.visible_next_step.strip():
        for fact in extract_claim_facts(
            facts.visible_next_step,
            source=SOURCE_REPLY_BODY,
            turn_id=facts.turn_id,
            provenance=PROVENANCE_MODEL_CLAIM,
            limit=_MAX_REPLY_CLAIMS,
        ):
            visible_by_domain.setdefault(claim_domain(fact), fact)
    conflicts: list[GroundingConflict] = []
    seen: set[str] = set()
    for fact in claims:
        domain = claim_domain(fact)
        if not domain or domain in seen:
            continue
        reply_claim = visible_by_domain.get(domain) or reply_by_domain.get(domain)
        if reply_claim is None:
            continue
        _creation, demand = _claim_context(facts, fact.value, context_text=context_text)
        if not demand:
            continue
        seen.add(domain)
        conflicts.append(
            GroundingConflict(
                domain=domain,
                reply_claim=reply_claim,
                next_step_claim=fact,
                winner=domain_backing(facts, domain) or PROVENANCE_MODEL_CLAIM,
                reply_step_corroborated=domain in visible_by_domain,
            )
        )
    return conflicts


def _evaluate_all(
    facts: TeachingTurnFacts,
    next_step_claims: list[TeachingFact],
    *,
    context_text: str | None = None,
) -> tuple[dict[str, str], list[str], list[GroundingConflict]]:
    reply_verdicts, _ = _evaluate_claims(facts.reply_claims, facts, include_reply=False)
    next_verdicts, ungrounded = _evaluate_claims(
        next_step_claims,
        facts,
        include_reply=True,
        apply_demand_guard=True,
        context_text=context_text,
    )
    verdicts = {**reply_verdicts, **next_verdicts}
    return (
        verdicts,
        ungrounded,
        _collect_conflicts(facts, next_step_claims, context_text=context_text),
    )


def _apply_facts_outcome(
    facts: TeachingTurnFacts,
    *,
    verdicts: dict[str, str],
    gate_outcome: str,
    conflicts: list[GroundingConflict],
) -> None:
    """Record the decision on the facts object (single designated writer).

    ``TeachingTurnFacts`` is frozen against rebinding; the grounding decision
    function is the one writer of ``verdicts`` / ``conflicts`` /
    ``gate_outcome`` for its own turn, and it writes at most once per
    evaluation.
    """
    facts.verdicts.clear()
    facts.verdicts.update(verdicts)
    facts.conflicts[:] = conflicts
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
    escape (creation instructions skip the checker); a demand/request for a
    learner-provided fact (repeat-asking) or for a fact with no backing at all
    (fabrication demand) is ungrounded. When ``retry_generate`` is provided it
    is called at most once; a grounded regeneration travels back in
    ``corrected_next_step`` (the caller writes it back via ``model_copy``) with
    ``retry_used=True``, an ungrounded or empty regeneration downgrades to
    ``requires_confirmation``. ``retry_used`` means "a regeneration was
    attempted for this decision" (an empty regeneration is still an attempt) —
    the assembly always routes its attempt through this implementation so both
    layers agree (2026-10-13 review); the corrected outcome stays detectable
    through ``corrected_next_step``.

    The decision is computed once per turn by its caller (the assembly layer
    caches it on the payload); this function is pure and deterministic, and
    performs its single facts write through ``_apply_facts_outcome``.
    """
    claims = list(facts.next_step_claims)
    verdicts, ungrounded, conflicts = _evaluate_all(facts, claims)
    if not ungrounded:
        _apply_facts_outcome(
            facts,
            verdicts=verdicts,
            gate_outcome=OUTCOME_GROUNDED,
            conflicts=conflicts,
        )
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
            retried_verdicts, retried_ungrounded, retried_conflicts = _evaluate_all(
                facts,
                retried_claims,
                context_text=retried_text,
            )
            if not retried_ungrounded:
                facts.next_step_claims[:] = retried_claims
                # The decision now ships the regenerated step: keep the facts
                # text in sync so later context reads (claims/conflicts) see
                # the text that was actually evaluated (same single writer).
                object.__setattr__(facts, "next_step_text", retried_text)
                _apply_facts_outcome(
                    facts,
                    verdicts=retried_verdicts,
                    gate_outcome=OUTCOME_CORRECTED,
                    conflicts=retried_conflicts,
                )
                return GroundingDecision(
                    grounded=True,
                    referenced_symbols=[],
                    retry_used=True,
                    requires_confirmation=False,
                    corrected_next_step=retried_text,
                )
        _apply_facts_outcome(
            facts,
            verdicts=verdicts,
            gate_outcome=OUTCOME_DOWNGRADED,
            conflicts=conflicts,
        )
        return GroundingDecision(
            grounded=False,
            referenced_symbols=ungrounded,
            retry_used=True,
            requires_confirmation=True,
            corrected_next_step=None,
        )
    _apply_facts_outcome(
        facts,
        verdicts=verdicts,
        gate_outcome=OUTCOME_DOWNGRADED,
        conflicts=conflicts,
    )
    return GroundingDecision(
        grounded=False,
        referenced_symbols=ungrounded,
        retry_used=False,
        requires_confirmation=True,
        corrected_next_step=None,
    )


def grounding_outcome(decision: GroundingDecision) -> str:
    """Assembly-facing outcome vocabulary: grounded | corrected | downgraded.

    ``retry_used`` records that a regeneration was attempted; ``corrected``
    requires both the attempt and a usable corrected step.
    """
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
    ("我亲自写了下面的修改…"), and the 2026-10-13 real-model maturity runs
    recorded the dominant drift form: technical fragments lifted from the
    learner's opening ("items 打印出来是空的", "我加了 or 0") — anchors whose
    embedded identifier ("items", "task", "await", "or", "JS") used to exempt
    them via a blanket Latin-letter carve-out. That carve-out is narrowed to
    the idea lane's topic declaration (``_IDEA_LANE_ANCHOR_MARKERS``); every
    other fragment of the learner's opening is drift whatever script it
    mixes, because the memory anchor must describe the teaching state, not
    echo the learner. Remaining exemptions keep technical anchors usable:

    - identifier-like anchors (``lesson.py``, ``mutable_default``) — filenames
      and symbols stay valid even when the message opens with them;
    - anchors shorter than ``_MESSAGE_PREFIX_MIN_LENGTH`` — trivial keyword
      overlap, not an echo of the message.
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
    lowered = anchor.lower()
    if any(marker in lowered for marker in _IDEA_LANE_ANCHOR_MARKERS):
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
