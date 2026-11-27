from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from ..llm.turn_grounding import (
    FACT_PROVENANCES,
    MEMORY_PROVENANCE_CONFLICTED_CLAIMS,
    MEMORY_PROVENANCE_FIELDS,
    MEMORY_PROVENANCE_GROUNDING_OUTCOME,
    OUTCOME_CORRECTED,
    OUTCOME_GROUNDED,
    PROVENANCE_LEARNER_PROVIDED,
    PROVENANCE_LOCAL_FALLBACK,
    PROVENANCE_MODEL_CLAIM,
    PROVENANCE_TOOL_VERIFIED,
)

logger = logging.getLogger(__name__)




_BACKED_PROVENANCES = frozenset({PROVENANCE_TOOL_VERIFIED, PROVENANCE_LEARNER_PROVIDED})


@dataclass(frozen=True)
class _MemoryProvenanceAdmission:
    """Resolved DESIGN.md §2.7 admission for one ``record_turn_reflection``."""

    requested: bool
    outcome: str
    provenance: dict[str, str]
    conflicted_claims: tuple[str, ...]

    def next_step_admitted(self) -> bool:
        if not self.requested:
            return True
        if self.outcome:
            return self.outcome in {OUTCOME_GROUNDED, OUTCOME_CORRECTED}
        return (
            self.provenance.get("next_step", PROVENANCE_MODEL_CLAIM)
            != PROVENANCE_LOCAL_FALLBACK
        )

    def focus_backing(self) -> str | None:
        if not self.requested:
            return None  # legacy callers keep the ungated behaviour
        return self.provenance.get("focus", PROVENANCE_MODEL_CLAIM)

    def summary_verification_trusted(self) -> bool:
        if not self.requested:
            return True
        return self.provenance.get("summary", PROVENANCE_MODEL_CLAIM) in _BACKED_PROVENANCES


def _resolve_memory_provenance_admission(
    raw: Mapping[str, str] | None,
) -> _MemoryProvenanceAdmission:
    """Normalize the mapping built by ``memory_provenance_summary`` (§2.6)."""
    if raw is None:
        return _MemoryProvenanceAdmission(False, "", {}, ())
    provenance: dict[str, str] = {}
    outcome = ""
    conflicted: list[str] = []
    for key, value in raw.items():
        text = str(value or "").strip()
        if key == MEMORY_PROVENANCE_GROUNDING_OUTCOME:
            outcome = text
        elif key == MEMORY_PROVENANCE_CONFLICTED_CLAIMS:
            conflicted = [part.strip() for part in text.splitlines() if part.strip()]
        elif key in MEMORY_PROVENANCE_FIELDS:
            provenance[key] = text if text in FACT_PROVENANCES else PROVENANCE_MODEL_CLAIM
    return _MemoryProvenanceAdmission(True, outcome, provenance, tuple(conflicted))


def _strip_conflicted_claim_texts(text: str | None, claims: tuple[str, ...]) -> str:
    """Remove exact conflicting claim texts (field+claim level, §2.7)."""
    cleaned = str(text or "")
    for claim in claims:
        if claim:
            cleaned = cleaned.replace(claim, "")
    return cleaned.strip()


@dataclass(frozen=True)
class _AdmittedReflectionFields:
    """One reflection's field values after the §2.7 admission."""

    focus_area: str | None
    summary: str
    next_step: str
    review_note: str | None
    decision: str | None
    teaching_note: str | None
    evidence: list[str] | None


def _admit_reflection_fields(
    admission: _MemoryProvenanceAdmission,
    *,
    focus_area: str | None,
    summary: str,
    next_step: str,
    review_note: str | None,
    decision: str | None,
    teaching_note: str | None,
    evidence: list[str] | None,
) -> _AdmittedReflectionFields:
    """Apply the DESIGN.md §2.7 admission to one reflection's fields.

    Single implementation shared by ``record_coaching_reflection`` and
    ``record_turn_memory`` (both accept ``memory_provenance``); a ``None``
    admission keeps every value untouched (legacy callers).
    """
    claims = admission.conflicted_claims
    admitted_focus = focus_area
    if admission.requested and admission.focus_backing() == PROVENANCE_LOCAL_FALLBACK:
        # local_fallback turns never write focus/anchor (DESIGN §2.1).
        admitted_focus = None
    admitted_evidence: list[str] | None = None
    if evidence is not None:
        admitted_evidence = [
            stripped
            for item in evidence
            if (stripped := _strip_conflicted_claim_texts(item, claims))
        ]
    return _AdmittedReflectionFields(
        focus_area=admitted_focus,
        summary=_strip_conflicted_claim_texts(summary, claims),
        next_step=next_step if admission.next_step_admitted() else "",
        review_note=_strip_conflicted_claim_texts(review_note, claims) or None,
        decision=_strip_conflicted_claim_texts(decision, claims) or None,
        teaching_note=_strip_conflicted_claim_texts(teaching_note, claims) or None,
        evidence=admitted_evidence,
    )
