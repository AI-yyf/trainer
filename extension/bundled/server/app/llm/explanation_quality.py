"""Explanation-quality dimensions for the coach reply body (NON-GATING).

This module is a structured *reporting* layer and is deliberately outside the
grounding contract (``app/llm/turn_grounding.py``):

- it never participates in ``grounding_outcome`` and never writes
  ``TeachingTurnFacts.gate_outcome`` / ``verdicts`` /
  ``next_step_claims`` — ``evaluate_explanation_quality`` is a pure function
  of the turn facts and mutates nothing;
- production turns do NOT gate on it (a deliberate design decision: reply
  explanation quality is an observation, not a correctness gate — no router
  consumes it and no reply is retried or downgraded because of it);
- it exists for the maturity harness acceptance
  (``scripts/maturity/real_teaching_journeys_minimax.py``), which records the
  verdicts in its per-turn checks under the ``explanation_quality`` key, and
  for unit tests.

Five deterministic dimensions, each reported as ``ok`` / ``weak`` /
``unclear``. ``unclear`` means the turn facts alone cannot decide — the
honest answer, never guessed:

1. ``addresses_learner`` — content-word overlap between the reply and the
   learner message (lowercase Latin words plus CJK bigrams, stopwords
   removed); ``ok`` at >= 30% coverage of the message's content tokens.
2. ``language_alignment`` — the reply's prose script (CJK vs Latin; fenced
   code blocks excluded so code never votes) matches the learner message's
   dominant script. A majority of reply prose in a different script than the
   question is ``weak``.
3. ``anchored_symbols`` — how many of the structured next step's code
   symbols (via ``extract_code_symbols``) the reply body itself mentions;
   ``ok`` only when every next-step symbol appears in the reply.
4. ``no_solution_dump`` — judged ONLY when ``answer_mode == "guided"``: at
   least one fenced code block with >= 12 total fenced code lines reads as a
   written-out full solution in a guided turn (``weak`` +
   ``solution_dump_suspected=True``). ``direct`` / ``practice`` (or any other
   mode) are ``unclear`` and never suspected.
5. ``explains_reasoning`` — reasoning connectives (因为 / 所以 / 这意味着 /
   原原因是 / because / therefore / that means / ...) present in the reply
   prose, with at least one occurrence within ±200 chars of a code reference
   (backticked literal or code symbol); connectives far from any code, or
   absent entirely, are ``weak``.

Every evidence string carries the quantified numbers behind the verdict so
harness reports stay auditable without re-reading the raw reply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .turn_grounding import TeachingTurnFacts, extract_code_symbols, symbol_in_text

VERDICT_OK = "ok"
VERDICT_WEAK = "weak"
VERDICT_UNCLEAR = "unclear"
EXPLANATION_VERDICTS = (VERDICT_OK, VERDICT_WEAK, VERDICT_UNCLEAR)

DIM_ADDRESSES_LEARNER = "addresses_learner"
DIM_LANGUAGE_ALIGNMENT = "language_alignment"
DIM_ANCHORED_SYMBOLS = "anchored_symbols"
DIM_NO_SOLUTION_DUMP = "no_solution_dump"
DIM_EXPLAINS_REASONING = "explains_reasoning"
EXPLANATION_DIMENSIONS = (
    DIM_ADDRESSES_LEARNER,
    DIM_LANGUAGE_ALIGNMENT,
    DIM_ANCHORED_SYMBOLS,
    DIM_NO_SOLUTION_DUMP,
    DIM_EXPLAINS_REASONING,
)

# Guided-mode solution-dump thresholds: one fenced block carrying this many
# code lines is no longer a snippet, it is the answer written out for the
# learner.
DUMP_MIN_FENCED_LINES = 12
# Reasoning connective must sit within this many chars of a code reference.
REASONING_PROXIMITY_CHARS = 200
# Content-token coverage of the learner message that reads as "on topic".
ADDRESS_COVERAGE_OK = 0.3

_CJK_CHAR = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_CHAR = re.compile(r"[A-Za-z]")
_FENCE_LINE = re.compile(r"^\s*```")
_BACKTICK_SPAN = re.compile(r"`[^`\n]+`")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{2,}")

# Question/function words that carry no topic signal on either side; kept
# deliberately small — recall matters more than precision here because the
# coverage threshold is low.
_CONTENT_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "this", "that", "what", "why", "how",
        "when", "where", "which", "you", "your", "are", "was", "were", "can",
        "could", "should", "would", "but", "not", "from", "into", "about",
        "all", "any", "did", "does", "use", "using", "then", "than", "also",
        "very", "just", "like", "some", "one", "two", "have", "has", "had",
        "out", "get", "her", "his", "its", "who", "whom", "will", "shall",
    }
)

# Small maintained marker set (spec §5): connectives that signal the reply
# explains *why*, not just *what*. CJK markers match by substring; Latin
# markers match on word boundaries.
_REASONING_MARKERS_CJK = (
    "因为", "所以", "这意味着", "原因是", "这是因为", "这是由于",
    "由于", "因此", "也就是说", "为什么",
)
_REASONING_MARKERS_LATIN = (
    "because", "therefore", "that means", "the reason", "which means",
    "hence", "why",
)


@dataclass(frozen=True)
class ExplanationQualityReport:
    """Per-turn explanation-quality verdicts (reporting only, never gating).

    ``dimensions`` maps each of ``EXPLANATION_DIMENSIONS`` to ``ok`` /
    ``weak`` / ``unclear``; ``evidence`` carries one quantified sentence per
    dimension. ``solution_dump_suspected`` is True only when the guided-mode
    dump rule fired.
    """

    dimensions: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    solution_dump_suspected: bool = False


def _content_tokens(text: str) -> list[str]:
    """Topic-bearing tokens: lowercase Latin words (>= 3 chars, stopwords
    removed) plus CJK bigrams (Chinese has no word boundaries; contiguous
    two-character shingles give a deterministic overlap signal)."""
    tokens: list[str] = []
    for match in _LATIN_WORD.finditer(text):
        word = match.group(0).lower()
        if len(word) >= 3 and word not in _CONTENT_STOPWORDS:
            tokens.append(word)
    for run in _CJK_RUN.finditer(text):
        characters = run.group(0)
        tokens.extend(characters[index : index + 2] for index in range(len(characters) - 1))
    return tokens


def _mask_fenced_code(text: str) -> str:
    """Blank out fenced code blocks while PRESERVING character offsets.

    ``text.split("\\n")`` + rejoin keeps every remaining newline in place, so
    positions found in the masked prose are valid in the original text (used
    to reason about marker/code proximity without counting code comments as
    prose reasoning).
    """
    masked: list[str] = []
    inside = False
    for line in text.split("\n"):
        if _FENCE_LINE.match(line):
            inside = not inside
            masked.append("")
            continue
        masked.append("" if inside else line)
    return "\n".join(masked)


def _script_counts(text: str) -> tuple[int, int]:
    return len(_CJK_CHAR.findall(text)), len(_LATIN_CHAR.findall(text))


def _dominant_script(text: str) -> str:
    """``"cjk"`` / ``"latin"`` by letter majority, ``""`` when undecidable
    (no letters at all, or an exact tie)."""
    cjk, latin = _script_counts(text)
    if cjk > latin and cjk > 0:
        return "cjk"
    if latin > cjk and latin > 0:
        return "latin"
    return ""


def _fenced_code_stats(text: str) -> tuple[int, int]:
    """(#blocks, #code lines) of ```-fenced blocks; an unclosed fence still
    counts as a block, fence-marker lines never count as code lines."""
    blocks = 0
    lines = 0
    inside = False
    for line in text.split("\n"):
        if _FENCE_LINE.match(line):
            if not inside:
                blocks += 1
            inside = not inside
            continue
        if inside:
            lines += 1
    return blocks, lines


def _evaluate_addresses_learner(reply: str, user_message: str) -> tuple[str, str]:
    message = str(user_message or "")
    if not message.strip():
        return VERDICT_UNCLEAR, "user_message is empty; nothing to address"
    wanted = sorted(set(_content_tokens(message)))
    if not wanted:
        return VERDICT_UNCLEAR, "user_message carries no content tokens (stopwords/symbols only)"
    present = set(_content_tokens(reply))
    covered = sum(1 for token in wanted if token in present)
    coverage = covered / len(wanted)
    evidence = (
        f"reply covers {covered}/{len(wanted)} user content tokens "
        f"({round(coverage * 100)}%; ok threshold {round(ADDRESS_COVERAGE_OK * 100)}%)"
    )
    if coverage >= ADDRESS_COVERAGE_OK:
        return VERDICT_OK, evidence
    return VERDICT_WEAK, evidence


def _evaluate_language_alignment(reply: str, user_message: str) -> tuple[str, str]:
    message = str(user_message or "")
    if not message.strip():
        return VERDICT_UNCLEAR, "user_message is empty; nothing to align with"
    message_script = _dominant_script(message)
    if not message_script:
        return VERDICT_UNCLEAR, "user_message has no dominant script (no letters or exact tie)"
    # Fenced code is masked so an English code block never outvotes Chinese
    # prose (and vice versa); only prose votes on the reply's language.
    reply_prose = _mask_fenced_code(reply)
    reply_script = _dominant_script(reply_prose)
    reply_counts = _script_counts(reply_prose)
    message_counts = _script_counts(message)
    if not reply_script:
        return VERDICT_UNCLEAR, (
            f"reply prose has no dominant script "
            f"(cjk={reply_counts[0]}/latin={reply_counts[1]}; code-only or empty prose)"
        )
    evidence = (
        f"reply prose cjk={reply_counts[0]}/latin={reply_counts[1]} vs "
        f"user message cjk={message_counts[0]}/latin={message_counts[1]} "
        f"({reply_script} vs {message_script})"
    )
    if reply_script == message_script:
        return VERDICT_OK, evidence
    # Majority-of-prose in a different script than the question = the "large
    # amount of prose in the wrong language" case.
    return VERDICT_WEAK, evidence


def _evaluate_anchored_symbols(facts: TeachingTurnFacts) -> tuple[str, str]:
    reply = str(facts.reply_text or "")
    next_symbols = extract_code_symbols(facts.next_step_text)
    reply_symbols = extract_code_symbols(reply)
    if not next_symbols and not reply_symbols:
        return VERDICT_UNCLEAR, "neither the reply nor the next step names a code symbol"
    if not next_symbols:
        # Nothing demanded to anchor — the proportion is undefined.
        return VERDICT_UNCLEAR, (
            f"next step names no code symbol; nothing to anchor "
            f"(reply symbols: {', '.join(reply_symbols) or 'none'})"
        )
    covered = [symbol for symbol in next_symbols if symbol_in_text(symbol, reply)]
    missing = [symbol for symbol in next_symbols if symbol not in covered]
    evidence = (
        f"reply mentions {len(covered)}/{len(next_symbols)} next-step symbols "
        f"[{', '.join(next_symbols)}]; reply's own symbols: "
        f"{', '.join(reply_symbols) or 'none'}"
    )
    if missing:
        return VERDICT_WEAK, f"{evidence}; uncovered: {', '.join(missing)}"
    return VERDICT_OK, evidence


def _evaluate_no_solution_dump(reply: str, *, answer_mode: str) -> tuple[str, str, bool]:
    mode = str(answer_mode or "").strip().lower()
    if mode != "guided":
        # direct/practice modes legitimately ship full code; judging them
        # here would punish the agreed contract, so the honest verdict is
        # "not judged".
        return (
            VERDICT_UNCLEAR,
            f"answer_mode={mode or 'unspecified'}: dump rule is judged for guided mode only",
            False,
        )
    blocks, lines = _fenced_code_stats(reply)
    evidence = (
        f"{blocks} fenced code block(s) with {lines} code line(s) "
        f"(dump threshold: >=1 block and >={DUMP_MIN_FENCED_LINES} lines)"
    )
    if blocks >= 1 and lines >= DUMP_MIN_FENCED_LINES:
        return VERDICT_WEAK, evidence, True
    return VERDICT_OK, evidence, False


def _marker_spans(prose: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    lowered = prose.lower()
    for marker in _REASONING_MARKERS_CJK:
        start = 0
        while True:
            index = lowered.find(marker, start)
            if index < 0:
                break
            spans.append((index, index + len(marker)))
            start = index + len(marker)
    for marker in _REASONING_MARKERS_LATIN:
        for match in re.finditer(rf"(?<![A-Za-z]){re.escape(marker)}(?![A-Za-z])", lowered):
            spans.append((match.start(), match.end()))
    return spans


def _code_reference_spans(text: str) -> list[tuple[int, int]]:
    spans = [(match.start(), match.end()) for match in _BACKTICK_SPAN.finditer(text)]
    for symbol in extract_code_symbols(text):
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")
        spans.extend((match.start(), match.end()) for match in pattern.finditer(text))
    return spans


def _span_gap(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Character gap between two spans; 0 when they overlap or touch."""
    if a[0] <= b[1] and b[0] <= a[1]:
        return 0
    return b[0] - a[1] if b[0] >= a[1] else a[0] - b[1]


def _evaluate_explains_reasoning(reply: str, next_step: str = "") -> tuple[str, str]:
    if not reply.strip():
        return VERDICT_UNCLEAR, "reply is empty; no prose to inspect"
    prose = _mask_fenced_code(reply)
    markers = _marker_spans(prose)
    code_spans = _code_reference_spans(reply)
    guidance_symbols = extract_code_symbols(next_step) if next_step else []
    if not code_spans and not guidance_symbols:
        # Calibration (2026-10-14 real-model runs): guidance that references no
        # code at all gives reasoning-near-code nothing to attach to - "weak"
        # here measured the metric, not the teaching.
        return VERDICT_UNCLEAR, (
            "guidance references no code (no fenced block or code symbol in the "
            "reply or the next step); reasoning-near-code is unmeasurable"
        )
    if not markers:
        return VERDICT_WEAK, (
            f"no reasoning connective in the reply prose "
            f"({len(prose.strip())} prose chars; markers: CJK {len(_REASONING_MARKERS_CJK)} "
            f"+ Latin {len(_REASONING_MARKERS_LATIN)})"
        )
    code_spans = _code_reference_spans(reply)
    near = sum(
        1
        for marker in markers
        if any(_span_gap(marker, code) <= REASONING_PROXIMITY_CHARS for code in code_spans)
    )
    evidence = (
        f"{len(markers)} reasoning marker occurrence(s); {near} within "
        f"±{REASONING_PROXIMITY_CHARS} chars of a code reference "
        f"({len(code_spans)} reference span(s))"
    )
    if near >= 1:
        return VERDICT_OK, evidence
    return VERDICT_WEAK, evidence


def evaluate_explanation_quality(
    facts: TeachingTurnFacts,
    *,
    answer_mode: str = "guided",
) -> ExplanationQualityReport:
    """Score the reply body's explanation quality; pure, non-gating.

    Depends only on ``facts`` (reply / user message / next-step texts) and
    ``answer_mode``; never touches ``facts.gate_outcome`` / ``verdicts`` /
    claims. A dimension whose inputs cannot decide it returns ``unclear``
    (empty user message, no symbols on either side, non-guided dump rule,
    empty reply prose) rather than guessing.
    """
    reply = str(facts.reply_text or "")
    dimensions: dict[str, str] = {}
    evidence: dict[str, str] = {}

    dimensions[DIM_ADDRESSES_LEARNER], evidence[DIM_ADDRESSES_LEARNER] = (
        _evaluate_addresses_learner(reply, str(facts.user_message or ""))
    )
    dimensions[DIM_LANGUAGE_ALIGNMENT], evidence[DIM_LANGUAGE_ALIGNMENT] = (
        _evaluate_language_alignment(reply, str(facts.user_message or ""))
    )
    dimensions[DIM_ANCHORED_SYMBOLS], evidence[DIM_ANCHORED_SYMBOLS] = (
        _evaluate_anchored_symbols(facts)
    )
    dimensions[DIM_NO_SOLUTION_DUMP], evidence[DIM_NO_SOLUTION_DUMP], dump_suspected = (
        _evaluate_no_solution_dump(reply, answer_mode=answer_mode)
    )
    dimensions[DIM_EXPLAINS_REASONING], evidence[DIM_EXPLAINS_REASONING] = (
        _evaluate_explains_reasoning(reply, str(facts.next_step_text or ""))
    )

    return ExplanationQualityReport(
        dimensions=dimensions,
        evidence=evidence,
        solution_dump_suspected=dump_suspected,
    )
