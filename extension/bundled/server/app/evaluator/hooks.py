"""Deterministic verification hooks for non-code subjects (P1 #8).

Pure-local, zero-cost checks behind the literature verifier pack: word-count
windows, banned-phrase lists, paragraph structure and quote balance. Hooks
return the same ``CheckResult`` shape as shell commands so downstream evidence
plumbing is unchanged. Locale-aware refinements (per-language counters) are
P1 #17; the counting rule below already treats CJK characters as units and
non-CJK runs as words so zh/ja/ko/en submissions measure sanely today.

Hooks are *deterministic evidence producers*: they never call a model, never
touch the network, and their PASSED/FAILED verdicts count toward the
"at least one deterministic check" rule in ``verifiers.combine_verdict``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .models import CheckResult, CheckStatus

_CJK_RANGES = (
    (0x4E00, 0x9FFF),   # CJK unified ideographs
    (0x3400, 0x4DBF),   # extension A
    (0x3040, 0x30FF),   # hiragana + katakana
    (0xAC00, 0xD7AF),   # hangul syllables
    (0xF900, 0xFAFF),   # CJK compatibility ideographs
)

_PAIR_QUOTE_DELIMITERS = (
    ("“", "”"),
    ("「", "」"),
    ("『", "』"),
    ("《", "》"),
    ("«", "»"),
    ("„", "“"),
    ("(", ")"),
    ("（", "）"),
)


SUPPORTED_HOOK_LOCALES: tuple[str, ...] = (
    "zh",
    "en",
    "ja",
    "de",
    "fr",
    "ko",
    "es",
    "pt",
)


def normalize_hook_locale(locale: str | None) -> str:
    """Normalize a content locale (e.g. 'zh-CN', 'ja_JP', 'de-DE') to one of the 8 supported language codes."""
    raw = str(locale or "").strip().lower().replace("_", "-")
    primary = raw.split("-")[0] if raw else ""
    return primary if primary in SUPPORTED_HOOK_LOCALES else "en"


class Hook(Protocol):
    """A deterministic, local, parameterized check over one submission."""

    @property
    def name(self) -> str: ...

    def run(self, submission: str, *, locale: str | None = None) -> CheckResult: ...


def _is_cjk_char(char: str) -> bool:
    code = ord(char)
    return any(start <= code <= end for start, end in _CJK_RANGES)


def unit_count(text: str, *, locale: str | None = None) -> int:
    """Count units according to content locale (P3):
    - CJK chars (zh/ja/ko) count individually;
    - Latin/alphabetic tokens (en/de/fr/es/pt) count by whitespace/apostrophe word boundaries.
    """
    norm = normalize_hook_locale(locale)
    cjk = sum(1 for char in text if _is_cjk_char(char))
    latin = re.sub(r"[\u0400-\uFFFF]", " ", text)
    if norm in ("fr", "es", "pt"):
        # French/Romance elisions like l'homme / d'accord count as distinct words when split on apostrophes
        latin = re.sub(r"['’]", " ", latin)
    words = len(latin.split())
    return cjk + words


@dataclass(frozen=True)
class WordCountHook:
    """Submission length must fall inside the card-declared window."""

    min_units: int
    max_units: int
    locale: str | None = None
    name: str = "word-count"

    def __post_init__(self) -> None:
        if self.min_units < 0 or self.max_units < self.min_units:
            raise ValueError("word-count hook requires 0 <= min_units <= max_units")

    def run(self, submission: str, *, locale: str | None = None) -> CheckResult:
        effective_locale = locale or self.locale
        units = unit_count(submission, locale=effective_locale)
        ok = self.min_units <= units <= self.max_units
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASSED if ok else CheckStatus.FAILED,
            summary=f"submission length {units} units (window {self.min_units}-{self.max_units})",
        )


@dataclass(frozen=True)
class BannedPhrasesHook:
    """User-declared avoidance list (e.g. "我要避免形容词堆砌"); any hit fails."""

    phrases: tuple[str, ...]
    locale: str | None = None
    name: str = "banned-phrases"

    def __post_init__(self) -> None:
        cleaned = tuple(phrase.strip() for phrase in self.phrases if phrase.strip())
        if not cleaned:
            raise ValueError("banned-phrases hook requires at least one non-empty phrase")
        object.__setattr__(self, "phrases", cleaned)

    def run(self, submission: str, *, locale: str | None = None) -> CheckResult:
        del locale
        lowered = submission.lower()
        hits = [phrase for phrase in self.phrases if phrase.lower() in lowered]
        if hits:
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILED,
                summary=f"banned phrases present: {', '.join(hits[:5])}",
            )
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASSED,
            summary=f"no banned phrases ({len(self.phrases)} watched)",
        )


@dataclass(frozen=True)
class ParagraphStructureHook:
    """At least ``min_paragraphs`` non-empty paragraphs (blank-line separated)."""

    min_paragraphs: int
    locale: str | None = None
    name: str = "paragraph-structure"

    def __post_init__(self) -> None:
        if self.min_paragraphs < 1:
            raise ValueError("paragraph-structure hook requires min_paragraphs >= 1")

    def run(self, submission: str, *, locale: str | None = None) -> CheckResult:
        del locale
        paragraphs = [block.strip() for block in re.split(r"\n\s*\n", submission) if block.strip()]
        ok = len(paragraphs) >= self.min_paragraphs
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASSED if ok else CheckStatus.FAILED,
            summary=f"{len(paragraphs)} paragraph(s), required {self.min_paragraphs}",
        )


@dataclass(frozen=True)
class QuoteBalanceHook:
    """Paired delimiters must close; stray quotes break the structural check."""

    locale: str | None = None
    name: str = "quote-balance"

    def run(self, submission: str, *, locale: str | None = None) -> CheckResult:
        effective_locale = normalize_hook_locale(locale or self.locale)
        # Paired delimiters: opening and closing glyphs are distinct.
        for opening, closing in _PAIR_QUOTE_DELIMITERS:
            if (opening, closing) == ("„", "“"):
                if effective_locale == "de" and submission.count("„") > 0:
                    if submission.count("„") != submission.count("“"):
                        return CheckResult(
                            name=self.name,
                            status=CheckStatus.FAILED,
                            summary=f"unbalanced pair {opening}{closing}",
                        )
                continue
            if (opening, closing) == ("“", "”") and effective_locale == "de" and submission.count("„") > 0:
                continue
            if submission.count(opening) != submission.count(closing):
                return CheckResult(
                    name=self.name,
                    status=CheckStatus.FAILED,
                    summary=f"unbalanced pair {opening}{closing}",
                )
        # Ambidirectional quotes ('", fullwidth) must appear an even number of times.
        # In French/English/Romance prose, ASCII/curly apostrophes inside words (l'homme, don't) are elisions, not unpaired quotes.
        cleaned_for_single = re.sub(r"(?<=\w)['’](?=\w)", "", submission)
        for glyph in ('"', "＂"):
            if submission.count(glyph) % 2 != 0:
                return CheckResult(
                    name=self.name,
                    status=CheckStatus.FAILED,
                    summary=f"odd number of {glyph!r} quotes",
                )
        if cleaned_for_single.count("'") % 2 != 0:
            return CheckResult(
                name=self.name,
                status=CheckStatus.FAILED,
                summary="odd number of \"'\" quotes",
            )
        return CheckResult(
            name=self.name,
            status=CheckStatus.PASSED,
            summary="quote pairs balanced",
        )


def hooks_from_card_config(config: Mapping[str, Any], *, locale: str | None = None) -> tuple[Hook, ...]:
    """Build a card's hook set from its declaration.

    Accepted keys (all optional): ``word_count: {min, max}``,
    ``banned_phrases: [..]``, ``min_paragraphs: int``, ``quote_balance: bool``,
    ``locale: str``. Rejects ``unbounded`` hooks fail-closed (§9 risk table).
    """
    if config.get("unbounded") is True or "unbounded" in (config.get("hooks") or ()):
        raise ValueError("unbounded hooks are forbidden by profile governance")
    resolved_locale = str(config.get("locale") or locale or "").strip() or None
    hooks: list[Hook] = []
    word_count = config.get("word_count")
    if isinstance(word_count, Mapping):
        if word_count.get("unbounded") is True:
            raise ValueError("unbounded word_count hook is forbidden")
        hooks.append(
            WordCountHook(
                min_units=int(word_count.get("min", 0)),
                max_units=int(word_count.get("max", word_count.get("min", 0))),
                locale=resolved_locale,
            )
        )
    banned = config.get("banned_phrases")
    if isinstance(banned, (list, tuple)) and banned:
        hooks.append(
            BannedPhrasesHook(
                phrases=tuple(str(phrase) for phrase in banned),
                locale=resolved_locale,
            )
        )
    min_paragraphs = config.get("min_paragraphs")
    if min_paragraphs is not None:
        hooks.append(
            ParagraphStructureHook(
                min_paragraphs=int(min_paragraphs),
                locale=resolved_locale,
            )
        )
    if bool(config.get("quote_balance")):
        hooks.append(QuoteBalanceHook(locale=resolved_locale))
    return tuple(hooks)


def run_hooks(
    hooks: tuple[Hook, ...],
    submission: str,
    *,
    locale: str | None = None,
) -> tuple[CheckResult, ...]:
    """Run every hook; hook crashes fail closed as ERROR, never crash the lane."""
    results: list[CheckResult] = []
    for hook in hooks:
        try:
            try:
                results.append(hook.run(submission, locale=locale))
            except TypeError:
                results.append(hook.run(submission))  # type: ignore[call-arg]
        except Exception as exc:  # noqa: BLE001 - a broken hook must not crash evaluation
            results.append(
                CheckResult(
                    name=hook.name,
                    status=CheckStatus.ERROR,
                    summary=f"hook crashed: {exc}",
                )
            )
    return tuple(results)
