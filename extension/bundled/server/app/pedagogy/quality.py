"""Phase 3 — Teaching quality evaluation (deterministic, evidence-driven).

Five dimensions, each computed ONLY from persisted learning evidence — never
from a model judging itself, and never from fabricated data:

1. ``independent_solving``  独立解题 — share of passed evidence produced at
   ``assistance_level == "independent"``.
2. ``hint_effectiveness``   提示有效性 — of evidence produced under assistance,
   the share that ended passed (hints that did not lead to a pass are counted
   against the hint).
3. ``difficulty_fit``       难度适配 — pass rate of the latest attempts; a rate
   inside the healthy band reads as adapted, above/below is reported as too
   easy/hard rather than scored as success.
4. ``transfer``             跨项目迁移 — passed evidence carrying
   ``transfer_metadata`` over all transfer-marked evidence.
5. ``citation_completeness`` 解释有据率 — evidence citations that carry the
   full server-resolved identity (resource_id + version + content_hash +
   location). This measures grounded citations, not prose quality — prose
   accuracy stays a human review item and is stated as a limitation.

Insufficient samples are reported as ``insufficient_evidence`` with
``score=None`` — a missing sample is never scored as 0 or 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

MIN_SAMPLE = 3
_HEALTHY_PASS_RATE = (0.4, 0.85)
MAX_ATTEMPTS = 200
_ASSISTED_LEVELS = {
    "hint",
    "hint_level_1",
    "hint_level_2",
    "hint_level_3",
    "assisted",
    "guided",
    "scaffolded",
}


@dataclass(slots=True)
class QualityDimension:
    key: str
    score: float | None
    sample_size: int
    evidence: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "score": None if self.score is None else round(self.score, 3),
            "sample_size": self.sample_size,
            "status": "insufficient_evidence" if self.score is None else "measured",
            "evidence": self.evidence,
            "limitations": self.limitations,
        }


@dataclass(slots=True)
class TeachingQualityReport:
    workspace_id: str
    generated_at: str
    dimensions: list[QualityDimension]

    def as_payload(self) -> dict[str, Any]:
        measured = [d for d in self.dimensions if d.score is not None]
        return {
            "artifact": "trainer.teaching.quality",
            "version": 1,
            "workspace_id": self.workspace_id,
            "generated_at": self.generated_at,
            "overall": (
                round(sum(d.score or 0.0 for d in measured) / len(measured), 3)
                if measured
                else None
            ),
            "measured_dimensions": len(measured),
            "dimensions": [d.as_payload() for d in self.dimensions],
            "limitations": [
                "Scores come from persisted training evidence only; prose quality "
                "(explanation accuracy as judged by a human) remains a manual review.",
                "Insufficient samples read as insufficient_evidence, never 0 or 1.",
            ],
        }


def _citation_complete(evidence: dict[str, Any]) -> bool:
    return all(
        evidence.get(name)
        for name in (
            "resource_id",
            "resource_version_id",
            "resource_content_hash",
            "resource_location",
        )
    )


def _is_passed(evidence: dict[str, Any]) -> bool:
    return str(evidence.get("result") or "").strip().lower() == "passed"


def _assistance_level(evidence: dict[str, Any]) -> str:
    return str(evidence.get("assistance_level") or "").strip().lower()


def _is_transfer(evidence: dict[str, Any]) -> bool:
    metadata = evidence.get("transfer_metadata")
    return isinstance(metadata, dict) and bool(metadata)


def evaluate_teaching_quality(
    attempt_store: Any,
    workspace_id: str,
    *,
    max_attempts: int = MAX_ATTEMPTS,
) -> TeachingQualityReport:
    """Build the five-dimension report from the attempt/evidence store."""

    attempts = attempt_store.list_attempts(workspace_id=workspace_id)[-max_attempts:]
    current_evidence: list[dict[str, Any]] = []
    for attempt in attempts:
        for item in attempt_store.list_evidence(attempt["attempt_id"]):
            if item.get("is_current"):
                current_evidence.append(item)

    passed = [item for item in current_evidence if _is_passed(item)]
    independent = [item for item in current_evidence if _assistance_level(item) == "independent"]
    assisted = [item for item in current_evidence if _assistance_level(item) in _ASSISTED_LEVELS]
    # A missing or unrecognized assistance level is unknown, not independent.
    # It is excluded from the known-assistance denominator instead of silently
    # inflating the independent-solving score.
    unknown_assistance = [
        item
        for item in current_evidence
        if _assistance_level(item) not in {"independent"} | _ASSISTED_LEVELS
    ]
    known_assistance = independent + assisted
    assisted_passed = [item for item in assisted if _is_passed(item)]
    transfer_marked = [item for item in current_evidence if _is_transfer(item)]
    transfer_passed = [item for item in transfer_marked if _is_passed(item)]
    cited = [item for item in current_evidence if _citation_complete(item)]
    cited_passed = [item for item in cited if _is_passed(item)]

    def ratio(numerator: int, denominator: int, *, min_sample: int = MIN_SAMPLE) -> float | None:
        if denominator < min_sample:
            return None
        return numerator / denominator

    dimensions: list[QualityDimension] = []
    dimensions.append(
        QualityDimension(
            key="independent_solving",
            score=ratio(len(independent), len(known_assistance)),
            sample_size=len(known_assistance),
            evidence={
                "independent_evidence": len(independent),
                "known_assistance_evidence": len(known_assistance),
                "unknown_assistance_evidence": len(unknown_assistance),
                "passed_evidence": len(passed),
                "current_evidence": len(current_evidence),
            },
            limitations=[
                "Only attempts with current (non-superseded) evidence count.",
                "Missing or unknown assistance_level is excluded; it is never treated as independent.",
            ],
        )
    )

    hint_score = ratio(len(assisted_passed), len(assisted))
    dimensions.append(
        QualityDimension(
            key="hint_effectiveness",
            score=hint_score,
            sample_size=len(assisted),
            evidence={
                "assisted_evidence": len(assisted),
                "assisted_passed": len(assisted_passed),
                "unknown_assistance_evidence": len(unknown_assistance),
            },
            limitations=[
                "Assistance level is recorded per attempt; fine-grained hint events "
                "are not persisted separately, so this is a per-attempt proxy.",
                "Unknown assistance is excluded, not counted as a hint or as independent.",
            ],
        )
    )

    pass_rate = ratio(len(passed), len(current_evidence))
    if pass_rate is None:
        fit_score: float | None = None
        fit_note = "insufficient_evidence"
    else:
        low, high = _HEALTHY_PASS_RATE
        fit_score = 1.0 if low <= pass_rate <= high else max(0.0, 1.0 - abs(
            pass_rate - (low if pass_rate < low else high)
        ) / max(high, 1e-6))
        fit_note = "adapted" if low <= pass_rate <= high else (
            "too_hard" if pass_rate < low else "too_easy"
        )
    dimensions.append(
        QualityDimension(
            key="difficulty_fit",
            score=fit_score,
            sample_size=len(current_evidence),
            evidence={"pass_rate": None if pass_rate is None else round(pass_rate, 3),
                      "band": list(_HEALTHY_PASS_RATE), "read": fit_note},
            limitations=[
                "Healthy band is a product policy (0.4-0.85), not a learner-specific "
                "calibration; per-concept difficulty is not modelled yet.",
            ],
        )
    )

    dimensions.append(
        QualityDimension(
            key="transfer",
            score=ratio(len(transfer_passed), len(transfer_marked)),
            sample_size=len(transfer_marked),
            evidence={
                "transfer_evidence": len(transfer_marked),
                "transfer_passed": len(transfer_passed),
            },
            limitations=["Only evidence recorded with transfer_metadata counts."],
        )
    )

    dimensions.append(
        QualityDimension(
            key="citation_completeness",
            score=ratio(len(cited_passed), len(cited)),
            sample_size=len(cited),
            evidence={
                "cited_evidence": len(cited),
                "cited_passed": len(cited_passed),
                "current_evidence": len(current_evidence),
            },
            limitations=[
                "Measures server-resolved citation identity (resource/version/hash/"
                "location), not whether the prose is correct.",
            ],
        )
    )

    return TeachingQualityReport(
        workspace_id=workspace_id,
        generated_at=datetime.now(UTC).isoformat(),
        dimensions=dimensions,
    )
