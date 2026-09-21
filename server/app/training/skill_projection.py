
from __future__ import annotations

"""
Phase-D: evidence → skill projection (design §10/§11).

A pure, recalculable projection from evidence records to skill states.
No hidden state: the projection is fully determined by its input, so
removing an evidence record (or superseding it) recalculates the skill
state from scratch — "deleting evidence recalculates the projection".

Skill dimensions follow the design:
- comprehension (概念理解)
- implementation (实现)
- debugging (调试)
- transfer (迁移)

Skill state ladder: not_verified → assisted → independent → repeat_verified → needs_review
"""


from typing import Any

_DIMENSIONS = ("comprehension", "implementation", "debugging", "transfer")

# Evidence result → contribution to the skill state ladder.
_RESULT_WEIGHT: dict[str, int] = {
    "passed": 2,
    "partial": 1,
    "failed": -1,
    "execution_error": 0,
    "cancelled": 0,
    "stale": 0,
}

_TRUST_BONUS: dict[str, int] = {
    "controlled_check": 1,
    "static_analysis": 0,
    "model_review": -1,
    "self_reported": -2,
}

_ASSISTANCE_PENALTY: dict[str, int] = {
    "independent": 0,
    "hint_level_1": -1,
    "hint_level_2": -2,
    "hint_level_3": -3,
}


def _state_from_score(score: int) -> str:
    if score <= -2:
        return "needs_review"
    if score == -1:
        return "assisted"
    if score == 0:
        return "not_verified"
    if score <= 2:
        return "assisted"
    if score <= 4:
        return "independent"
    return "repeat_verified"


def project_skills(
    evidence_records: list[dict[str, Any]],
    *,
    card_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Pure projection: evidence records → skill states per dimension.

    Only evidence records where `is_current` is truthy and `superseded_by_
    evidence_id` is falsy contribute. Stale evidence is excluded because it
    belongs to an older artifact version.

    Returns: {dimension: {state, score, evidence_ids, verified_count}}
    """
    result: dict[str, dict[str, Any]] = {}
    for dim in _DIMENSIONS:
        result[dim] = {
            "state": "not_verified",
            "score": 0,
            "evidence_ids": [],
            "verified_count": 0,
        }

    for rec in evidence_records:
        if rec.get("superseded_by_evidence_id"):
            continue
        if not rec.get("is_current"):
            continue
        result_str = str(rec.get("result") or "")
        weight = _RESULT_WEIGHT.get(result_str, 0)
        # Trust bonus only amplifies positive results — a failed controlled
        # check should not score higher because the runner was trusted.
        trust = _TRUST_BONUS.get(str(rec.get("trust_level") or ""), 0) if weight > 0 else 0
        assistance = _ASSISTANCE_PENALTY.get(str(rec.get("assistance_level") or ""), 0)
        score = weight + trust + assistance

        # All evidence contributes to implementation; failed evidence
        # contributes to debugging; static/diagnostic to comprehension.
        dims = {rec.get("dimension", "implementation")}
        if rec.get("execution_location") in ("preview", "sandbox"):
            dims.add("transfer")
        if result_str in ("failed", "execution_error"):
            dims.add("debugging")

        for dim in dims:
            if dim in result:
                result[dim]["score"] += score
                result[dim]["evidence_ids"].append(rec.get("evidence_id"))
                if result_str == "passed":
                    result[dim]["verified_count"] += 1

    for dim in _DIMENSIONS:
        result[dim]["state"] = _state_from_score(result[dim]["score"])

    if card_id:
        for dim in result:
            result[dim]["card_id"] = card_id

    return result


def evidence_is_current_for_hash(
    evidence: dict[str, Any],
    current_artifact_hash: str | None,
) -> bool:
    """TR-059: an evidence record is only current if its artifact hash
    matches the current artifact AND it has not been superseded."""
    if evidence.get("superseded_by_evidence_id"):
        return False
    return bool(
        current_artifact_hash
        and evidence.get("artifact_hash") == current_artifact_hash
    )
