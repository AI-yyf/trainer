
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

from __future__ import annotations

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

# These are inconclusive execution outcomes.  They must never become a
# learner failure merely because a transport/provider reported them using the
# legacy ``result=failed`` shape.
_NON_FAILURE_EXECUTION_MARKERS = {
    "cancelled",
    "canceled",
    "connection_error",
    "connection_loss",
    "connection_lost",
    "disconnected",
    "execution_interrupted",
    "interrupted",
    "network_error",
    "provider_stream_interrupted",
    "stream_interrupted",
    "timeout",
    "transport_error",
}


def _normalise_marker(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def normalize_evidence_result(
    result: Any,
    *,
    execution_status: Any = None,
    error_category: Any = None,
    failure_reason: Any = None,
    error_code: Any = None,
    limitations: Any = None,
) -> str:
    """Canonicalise execution interruptions without changing old payloads.

    Some older callers represented a provider disconnect as ``result=failed``
    and put the actual reason in another field.  Treat those records as
    ``execution_error`` so they carry no negative learning signal.
    """
    result_marker = _normalise_marker(result)
    markers = set()
    for value in (execution_status, error_category, failure_reason, error_code):
        if value:
            markers.add(_normalise_marker(value))
    if isinstance(limitations, (list, tuple, set)):
        markers.update(_normalise_marker(item) for item in limitations if item)
    elif limitations:
        markers.add(_normalise_marker(limitations))

    if result_marker in _NON_FAILURE_EXECUTION_MARKERS:
        return "execution_error"
    if result_marker == "failed" and any(
        marker in _NON_FAILURE_EXECUTION_MARKERS for marker in markers
    ):
        return "execution_error"
    return result_marker


def _has_transfer_fact(rec: dict[str, Any]) -> bool:
    """Require explicit cross-context metadata before projecting transfer."""
    for key in ("scenario", "environment", "constraints", "transfer_metadata"):
        value = rec.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (list, tuple, set, dict)) and value:
            return True
    return False


def _success_key(rec: dict[str, Any], index: int) -> tuple[str, str]:
    """Group independent success by attempt, with an evidence fallback."""
    attempt_id = str(rec.get("attempt_id") or "").strip()
    if attempt_id:
        return ("attempt", attempt_id)
    # Legacy records may not have an attempt id.  Their evidence id is the
    # finest available unit and remains compatible with the old payload shape.
    evidence_id = str(rec.get("evidence_id") or "").strip()
    if evidence_id:
        return ("evidence", evidence_id)
    return ("legacy", str(index))


def _state_from_evidence(
    *,
    independent_successes: int,
    assisted_successes: int,
    has_failed_evidence: bool,
    has_partial_evidence: bool,
) -> str:
    """Map qualified evidence to a state; do not infer state from score."""
    if independent_successes >= 2:
        return "repeat_verified"
    if independent_successes == 1:
        return "independent"
    if has_failed_evidence:
        return "needs_review"
    # The assisted state is only reachable from an assisted passed result.
    if assisted_successes:
        return "assisted"
    if has_partial_evidence:
        return "not_verified"
    return "not_verified"


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
            "independent_evidence_count": 0,
            "independent_attempt_count": 0,
        }

    independent_success_keys: dict[str, set[tuple[str, str]]] = {
        dim: set() for dim in _DIMENSIONS
    }
    independent_evidence_keys: dict[str, set[str]] = {
        dim: set() for dim in _DIMENSIONS
    }
    assisted_success_keys: dict[str, set[str]] = {dim: set() for dim in _DIMENSIONS}
    failed_dimensions: dict[str, bool] = {dim: False for dim in _DIMENSIONS}
    partial_dimensions: dict[str, bool] = {dim: False for dim in _DIMENSIONS}

    for index, rec in enumerate(evidence_records):
        if rec.get("superseded_by_evidence_id"):
            continue
        if not rec.get("is_current") or rec.get("source_deleted"):
            continue
        result_str = normalize_evidence_result(
            rec.get("result"),
            execution_status=rec.get("execution_status"),
            error_category=rec.get("error_category"),
            failure_reason=rec.get("failure_reason"),
            error_code=rec.get("error_code"),
            limitations=rec.get("limitations"),
        )
        weight = _RESULT_WEIGHT.get(result_str, 0)
        # Trust bonus only amplifies positive results — a failed controlled
        # check should not score higher because the runner was trusted.
        trust = _TRUST_BONUS.get(str(rec.get("trust_level") or ""), 0) if weight > 0 else 0
        assistance = (
            _ASSISTANCE_PENALTY.get(str(rec.get("assistance_level") or ""), 0)
            if result_str == "passed"
            else 0
        )
        score = weight + trust + assistance

        # All evidence contributes to implementation; failed evidence
        # contributes to debugging.  Preview/sandbox alone is not transfer.
        transfer_fact = _has_transfer_fact(rec)
        raw_dimension = rec.get("dimension", "implementation")
        dims = set()
        if raw_dimension != "transfer" or transfer_fact:
            dims.add(raw_dimension)
        if transfer_fact:
            dims.add("transfer")
        if result_str == "failed":
            dims.add("debugging")

        for dim in dims:
            if dim in result:
                result[dim]["score"] += score
                evidence_id = str(rec.get("evidence_id") or f"legacy-{index}")
                if evidence_id not in result[dim]["evidence_ids"]:
                    result[dim]["evidence_ids"].append(evidence_id)
                if result_str == "passed":
                    result[dim]["verified_count"] += 1
                    assistance_level = str(rec.get("assistance_level") or "independent")
                    if assistance_level == "independent":
                        independent_success_keys[dim].add(_success_key(rec, index))
                        independent_evidence_keys[dim].add(evidence_id)
                    else:
                        assisted_success_keys[dim].add(evidence_id)
                elif result_str == "failed":
                    failed_dimensions[dim] = True
                elif result_str == "partial":
                    partial_dimensions[dim] = True

    for dim in _DIMENSIONS:
        result[dim]["independent_evidence_count"] = len(independent_evidence_keys[dim])
        result[dim]["independent_attempt_count"] = len(independent_success_keys[dim])
        result[dim]["state"] = _state_from_evidence(
            independent_successes=len(independent_success_keys[dim]),
            assisted_successes=len(assisted_success_keys[dim]),
            has_failed_evidence=failed_dimensions[dim],
            has_partial_evidence=partial_dimensions[dim],
        )

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
