"""One Evidence contract shared by AttemptStore, handoff and the memory queue.

The three stores keep their existing persistence and lifecycle fields. This
module is the single place that normalizes their trust vocabulary, result
values, resource-version facts and identity fingerprint, so readers never
have to interpret three subtly different evidence shapes.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..core.models import EvidenceItem, utc_now_iso
from ..training.handoff import EvidenceRecord

EvidenceSourceStore = Literal["attempt", "handoff", "memory"]
EvidenceTrustLevel = Literal["self_reported", "model_review", "static_analysis", "controlled_check"]
EvidenceResult = Literal["passed", "failed", "partial", "unknown"]

_TRUST_LEVELS: dict[str, EvidenceTrustLevel] = {
    "self_reported": "self_reported",
    "self-reported": "self_reported",
    "learner_submission": "self_reported",
    "model_review": "model_review",
    "model-reviewed": "model_review",
    "static": "static_analysis",
    "static_analysis": "static_analysis",
    "static-analysis": "static_analysis",
    "controlled": "controlled_check",
    "controlled_check": "controlled_check",
    "host": "controlled_check",
    "host_trusted": "controlled_check",
    "remote": "controlled_check",
    "remote_controlled": "controlled_check",
}

_RESULTS: dict[str, EvidenceResult] = {
    "passed": "passed",
    "pass": "passed",
    "success": "passed",
    "ok": "passed",
    "completed": "passed",
    "failed": "failed",
    "fail": "failed",
    "failure": "failed",
    "error": "failed",
    "partial": "partial",
    "incomplete": "partial",
    "unknown": "unknown",
    "pending": "unknown",
}

_SOURCE_PRIORITY: dict[EvidenceSourceStore, int] = {
    "attempt": 0,
    "handoff": 1,
    "memory": 2,
}


class UnifiedEvidence(BaseModel):
    """The only evidence shape readers should depend on."""

    model_config = ConfigDict(populate_by_name=True)

    evidence_id: str
    source_store: EvidenceSourceStore
    source_id: str = ""
    workspace_id: str = ""
    card_id: str = ""
    concept: str = ""
    summary: str = ""
    content: str = ""
    result: EvidenceResult = "unknown"
    trust_level: EvidenceTrustLevel = "self_reported"
    verified: bool = False
    verification_source: str = ""
    artifact_hash: str = ""
    resource_id: str = ""
    resource_version_id: str = ""
    resource_content_hash: str = ""
    resource_location: dict[str, Any] = Field(default_factory=dict)
    resource_git_sha: str | None = None
    assistance_level: str = "unknown"
    dimension: str = ""
    evidence_kind: str = ""
    recall_delay_days: float | None = None
    recall_rating: str = ""
    source_stale: bool = False
    source_stale_reason: str = ""
    limitations: list[str] = Field(default_factory=list)
    created_at: str = ""
    verified_at: str | None = None
    schema_version: int = 1
    fingerprint: str = ""
    duplicate_of: str = ""


def normalize_evidence_trust(value: object, *, verified: bool = False) -> EvidenceTrustLevel:
    if isinstance(value, str):
        normalized = _TRUST_LEVELS.get(value.strip().lower())
        if normalized is not None:
            return normalized
    return "controlled_check" if verified else "self_reported"


def normalize_evidence_result(value: object) -> EvidenceResult:
    if isinstance(value, str):
        return _RESULTS.get(value.strip().lower().replace("-", "_"), "unknown")
    return "unknown"


def _text(value: object) -> str:
    return str(value or "").strip()


def _iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return _text(value)


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fingerprint(
    *,
    workspace_id: str,
    card_id: str,
    artifact_hash: str,
    content: str,
    result: EvidenceResult,
) -> str:
    if artifact_hash:
        material = f"artifact|{workspace_id}|{card_id}|{artifact_hash}"
    else:
        digest = hashlib.sha256(re.sub(r"\s+", " ", content).strip().encode("utf-8")).hexdigest()[:24]
        material = f"content|{workspace_id}|{card_id}|{digest}|{result}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def evidence_from_attempt(record: dict[str, Any], *, workspace_id: str | None = None) -> UnifiedEvidence:
    scope = _text(workspace_id or record.get("workspace_id"))
    card_id = _text(record.get("card_id"))
    trust = normalize_evidence_trust(record.get("trust_level"))
    source_deleted = bool(record.get("source_deleted"))
    source_stale = bool(record.get("source_stale"))
    result = normalize_evidence_result(record.get("result"))
    summary = _text(record.get("failure_reason") or record.get("execution_status") or result)
    content = summary or f"{card_id}: {result}".strip()
    artifact_hash = _text(record.get("artifact_hash"))
    created_at = _iso(record.get("created_at")) or utc_now_iso()
    location = record.get("resource_location")
    resource_location = location if isinstance(location, dict) else {}
    verified = trust != "self_reported" and not source_deleted and not source_stale
    return UnifiedEvidence(
        evidence_id=_text(record.get("evidence_id")),
        source_store="attempt",
        source_id=_text(record.get("attempt_id")),
        workspace_id=scope,
        card_id=card_id,
        concept=card_id,
        summary=summary,
        content=content,
        result=result,
        trust_level=trust,
        verified=verified,
        verification_source=_text(record.get("verification_source") or record.get("runner_version") or trust),
        artifact_hash=artifact_hash,
        resource_id=_text(record.get("resource_id")),
        resource_version_id=_text(record.get("resource_version_id")),
        resource_content_hash=_text(record.get("resource_content_hash")),
        resource_location=resource_location,
        resource_git_sha=_text(record.get("resource_git_sha")) or None,
        assistance_level=_text(record.get("assistance_level")) or "unknown",
        dimension=_text(record.get("dimension")),
        evidence_kind=_text(record.get("evidence_kind")),
        recall_delay_days=_optional_float(record.get("recall_delay_days")),
        recall_rating=_text(record.get("recall_rating")),
        source_stale=source_stale,
        source_stale_reason=_text(record.get("source_stale_reason")),
        limitations=[_text(item) for item in (record.get("limitations") or []) if _text(item)],
        created_at=created_at,
        verified_at=created_at if verified else None,
        schema_version=int(record.get("schema_version") or 1),
        fingerprint=_fingerprint(
            workspace_id=scope,
            card_id=card_id,
            artifact_hash=artifact_hash,
            content=content,
            result=result,
        ),
    )


def evidence_from_handoff(
    record: EvidenceRecord,
    *,
    workspace_id: str,
    handoff_id: str,
) -> UnifiedEvidence:
    trust = normalize_evidence_trust(record.trust_level, verified=record.verified)
    result = normalize_evidence_result(record.result or ("passed" if record.verified else "unknown"))
    content = _text(record.content)
    created_at = _iso(record.created_at) or utc_now_iso()
    verified = bool(record.verified)
    return UnifiedEvidence(
        evidence_id=_text(record.id),
        source_store="handoff",
        source_id=_text(handoff_id),
        workspace_id=workspace_id,
        card_id=_text(record.card_id),
        concept=_text(record.concept),
        summary=content[:240],
        content=content,
        result=result,
        trust_level=trust,
        verified=verified,
        verification_source=_text(record.verification_source),
        artifact_hash=_text(record.artifact_hash),
        resource_id=_text(record.resource_id),
        resource_version_id=_text(record.resource_version_id),
        resource_content_hash=_text(record.resource_content_hash),
        resource_location=dict(record.resource_location or {}),
        resource_git_sha=_text(record.resource_git_sha) or None,
        created_at=created_at,
        verified_at=_iso(record.verified_at) or (created_at if verified else None),
        schema_version=int(record.schema_version or 1),
        fingerprint=_fingerprint(
            workspace_id=workspace_id,
            card_id=_text(record.card_id),
            artifact_hash=_text(record.artifact_hash),
            content=content,
            result=result,
        ),
    )


def evidence_from_memory(item: EvidenceItem) -> UnifiedEvidence:
    trust = normalize_evidence_trust(item.trust_level, verified=item.verified)
    result = normalize_evidence_result(item.outcome)
    content = _text(item.summary)
    artifact = item.verification_artifact if isinstance(item.verification_artifact, dict) else {}
    artifact_hash = _text(item.artifact_hash or artifact.get("sha256"))
    created_at = _iso(item.timestamp) or utc_now_iso()
    return UnifiedEvidence(
        evidence_id=_text(item.id),
        source_store="memory",
        source_id=_text(item.id),
        workspace_id=_text(item.workspace_id),
        card_id=_text(item.source_card_id),
        concept=_text(item.concepts[0]) if item.concepts else "",
        summary=content[:240],
        content=content,
        result=result,
        trust_level=trust,
        verified=bool(item.verified),
        verification_source=_text(item.verification_source),
        artifact_hash=artifact_hash,
        resource_id=_text(item.resource_id),
        resource_version_id=_text(item.resource_version_id),
        resource_content_hash=_text(item.resource_content_hash),
        resource_location=dict(item.resource_location or {}),
        resource_git_sha=_text(item.resource_git_sha) or None,
        created_at=created_at,
        verified_at=_iso(item.adopted_at) or (created_at if item.verified else None),
        schema_version=int(item.schema_version or 1),
        fingerprint=_fingerprint(
            workspace_id=_text(item.workspace_id),
            card_id=_text(item.source_card_id),
            artifact_hash=artifact_hash,
            content=content,
            result=result,
        ),
    )


def finalize_unified_evidence(
    records: Iterable[UnifiedEvidence],
    *,
    limit: int = 50,
) -> list[UnifiedEvidence]:
    """Order newest-first and mark duplicate sources without dropping them."""
    materialized = list(records)
    canonical_by_fingerprint: dict[str, UnifiedEvidence] = {}
    for record in materialized:
        if not record.evidence_id or not record.workspace_id:
            continue
        current = canonical_by_fingerprint.get(record.fingerprint)
        if current is None or _SOURCE_PRIORITY[record.source_store] < _SOURCE_PRIORITY[current.source_store]:
            canonical_by_fingerprint[record.fingerprint] = record
    for record in materialized:
        canonical = canonical_by_fingerprint.get(record.fingerprint)
        if canonical is not None and canonical.evidence_id != record.evidence_id:
            record.duplicate_of = canonical.evidence_id
        elif canonical is record:
            record.duplicate_of = ""
    materialized.sort(
        key=lambda item: (
            item.created_at,
            -_SOURCE_PRIORITY[item.source_store],
        ),
        reverse=True,
    )
    return materialized[: max(1, min(int(limit), 200))]
