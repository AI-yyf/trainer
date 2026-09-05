"""Evidence-conservative policy for source intake and commercial reuse.

The evaluator deliberately makes no network request and never treats a caller's
license or maintenance declaration as proof. It only promotes a source when its
own imported content contains a narrow, auditable SPDX signal and a dated
maintenance signal. Everything else stays explicit review-required or blocked.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Literal

from ..core.models import SourceIntakeDeclaration, SourceIntakeGovernance

POLICY_VERSION = "source-intake-v1"
COMMERCIAL_REUSE_POLICY = "permissive-spdx-v1"
MAINTENANCE_RECENCY_DAYS = 365

# This is intentionally a small policy allowlist, not a license compatibility
# engine. Expressions outside it require review instead of an inferred verdict.
PERMISSIVE_SPDX_IDENTIFIERS = frozenset(
    {
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "CC0-1.0",
        "ISC",
        "MIT",
        "0BSD",
        "Unlicense",
        "Zlib",
    }
)
_PERMISSIVE_SPDX_BY_CASEFOLD = {
    identifier.casefold(): identifier for identifier in PERMISSIVE_SPDX_IDENTIFIERS
}

_SPDX_LICENSE_PATTERN = re.compile(
    r"\bSPDX-License-Identifier\s*:\s*([A-Za-z0-9][A-Za-z0-9.+-]*)\b",
    re.IGNORECASE,
)
_LAST_UPDATED_PATTERN = re.compile(
    r"\b(?:last\s+(?:updated|modified)|updated)\s*(?:on)?\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)
_URI_SCHEME_PATTERN = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")
_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
_GIT_SSH_REFERENCE_PATTERN = re.compile(r"^[^@\s/:]+@[^\s/:]+:.+")

_EXTERNAL_SOURCE_TYPE_PREFIXES = ("url:", "external:", "research:")
_LOCAL_SOURCE_TYPE_PREFIXES = (
    "local:",
    "memory:teaching-asset",
    "workspace:understanding",
)
_LOCAL_URI_PREFIXES = (
    "file:",
    "local:",
    "teaching-asset://",
    "workspace-understanding://",
)
_LOCAL_URI_SCHEMES = {"file", "local", "teaching-asset", "workspace-understanding"}

CommercialReuseStatus = Literal["eligible", "review_required", "blocked"]


def evaluate_source_intake_governance(
    *,
    source_uri: str,
    source_text: str,
    source_provenance: Mapping[str, object] | None = None,
    declaration: SourceIntakeDeclaration | None = None,
    assessed_at: datetime | None = None,
) -> SourceIntakeGovernance:
    """Return an auditable, fail-closed commercial-reuse assessment.

    ``source_text`` is already obtained through the caller's normal controlled
    ingest path. This function does not fetch declaration evidence URLs or infer
    a license from a host name, a title, or a successful HTTP request.
    """

    normalized_declaration = declaration or SourceIntakeDeclaration()
    provenance = source_provenance or {}
    provenance_status = _provenance_status(provenance)
    assessment_time = _assessment_time(provenance, assessed_at=assessed_at)
    evidence_source = _evidence_source(source_uri, provenance)
    text = str(source_text or "")[:100_000]
    reason_codes: list[str] = []

    license_match = _SPDX_LICENSE_PATTERN.search(text)
    declared_license = _normalized_text(normalized_declaration.license_expression)
    if license_match is not None:
        license_expression = _canonical_spdx_identifier(license_match.group(1))
        license_status = "observed"
        license_evidence_kind = "source_spdx"
        license_evidence_source = evidence_source
        license_evidence_excerpt = license_match.group(0)
        if declared_license and declared_license.lower() != license_expression.lower():
            reason_codes.append("license_declaration_conflicts_with_observed_signal")
    elif declared_license:
        license_expression = declared_license
        license_status = "declared"
        license_evidence_kind = "user_declaration"
        license_evidence_source = _normalized_text(normalized_declaration.license_evidence_uri)
        license_evidence_excerpt = ""
    else:
        license_expression = ""
        license_status = "unknown"
        license_evidence_kind = "none"
        license_evidence_source = ""
        license_evidence_excerpt = ""

    maintenance_match = _LAST_UPDATED_PATTERN.search(text)
    declared_maintenance_at = _normalized_text(normalized_declaration.maintenance_updated_at)
    maintenance_updated_at: str | None = None
    if maintenance_match is not None:
        reported_date = _parse_date(maintenance_match.group(1))
        if reported_date is None or reported_date > assessment_time.date():
            maintenance_status = "unknown"
            maintenance_evidence_kind = "none"
            maintenance_evidence_source = ""
            maintenance_evidence_excerpt = ""
            reason_codes.append("maintenance_reported_date_invalid")
        else:
            maintenance_updated_at = reported_date.isoformat()
            maintenance_evidence_kind = "source_last_updated"
            maintenance_evidence_source = evidence_source
            maintenance_evidence_excerpt = maintenance_match.group(0)
            age_days = (assessment_time.date() - reported_date).days
            maintenance_status = (
                "reported_recent" if age_days <= MAINTENANCE_RECENCY_DAYS else "reported_stale"
            )
    elif declared_maintenance_at:
        maintenance_status = "declared"
        maintenance_updated_at = declared_maintenance_at
        maintenance_evidence_kind = "user_declaration"
        maintenance_evidence_source = _normalized_text(
            normalized_declaration.maintenance_evidence_uri
        )
        maintenance_evidence_excerpt = ""
    else:
        maintenance_status = "unknown"
        maintenance_evidence_kind = "none"
        maintenance_evidence_source = ""
        maintenance_evidence_excerpt = ""

    commercial_reuse_status = _commercial_reuse_status(
        license_status=license_status,
        license_expression=license_expression,
        maintenance_status=maintenance_status,
        controlled_provenance=provenance_status == "fetched",
        reason_codes=reason_codes,
    )

    return SourceIntakeGovernance(
        policy_version=POLICY_VERSION,
        assessed_at=assessment_time.isoformat(),
        source_provenance_status=provenance_status,
        license_status=license_status,
        license_expression=license_expression,
        license_evidence_kind=license_evidence_kind,
        license_evidence_source=license_evidence_source,
        license_evidence_excerpt=license_evidence_excerpt,
        maintenance_status=maintenance_status,
        maintenance_updated_at=maintenance_updated_at,
        maintenance_evidence_kind=maintenance_evidence_kind,
        maintenance_evidence_source=maintenance_evidence_source,
        maintenance_evidence_excerpt=maintenance_evidence_excerpt,
        commercial_reuse_policy=COMMERCIAL_REUSE_POLICY,
        commercial_reuse_status=commercial_reuse_status,
        commercial_reuse_reason_codes=reason_codes,
    )


def source_governance_payload(
    value: SourceIntakeGovernance | Mapping[str, object] | object | None,
) -> dict[str, object] | None:
    """Return the nested governance record without trusting sibling item fields."""

    if isinstance(value, SourceIntakeGovernance):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): raw_value for key, raw_value in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json")
        if isinstance(payload, dict):
            return {str(key): raw_value for key, raw_value in payload.items()}
    return None


def commercial_reuse_governance_status(
    value: SourceIntakeGovernance | Mapping[str, object] | object | None,
) -> CommercialReuseStatus | None:
    """Return a declared nested governance status when it is one of the policy states."""

    payload = source_governance_payload(value)
    if payload is None:
        return None
    status = _normalized_text(str(payload.get("commercial_reuse_status") or "")).lower()
    if status == "eligible":
        return "eligible"
    if status == "review_required":
        return "review_required"
    if status == "blocked":
        return "blocked"
    return None


def commercial_reuse_eligibility_reason_codes(
    value: SourceIntakeGovernance | Mapping[str, object] | object | None,
) -> list[str]:
    """Validate the complete audit record required for automatic external reuse.

    This is intentionally stricter than a status comparison. Callers can carry
    arbitrary reference metadata, so a top-level ``eligible`` field or a partial
    nested record must not turn an external source into a reusable project seed.
    """

    governance = _coerce_source_governance(value)
    if governance is None:
        return ["source_governance_missing"]

    reason_codes: list[str] = []
    if governance.policy_version != POLICY_VERSION:
        reason_codes.append("source_governance_policy_invalid")
    if governance.commercial_reuse_policy != COMMERCIAL_REUSE_POLICY:
        reason_codes.append("commercial_reuse_policy_invalid")
    if governance.commercial_reuse_status != "eligible":
        reason_codes.append("commercial_reuse_status_not_eligible")
    if governance.source_provenance_status.casefold() != "fetched":
        reason_codes.append("controlled_provenance_missing")

    if governance.license_status != "observed":
        reason_codes.append("license_not_observed")
    canonical_license = _canonical_spdx_identifier(governance.license_expression)
    if canonical_license not in PERMISSIVE_SPDX_IDENTIFIERS:
        reason_codes.append("license_not_in_permissive_allowlist")
    if governance.license_evidence_kind != "source_spdx":
        reason_codes.append("license_evidence_not_source_spdx")
    if not _normalized_text(governance.license_evidence_source):
        reason_codes.append("license_evidence_source_missing")
    license_match = _SPDX_LICENSE_PATTERN.search(governance.license_evidence_excerpt)
    if license_match is None:
        reason_codes.append("license_evidence_excerpt_missing")
    elif _canonical_spdx_identifier(license_match.group(1)) != canonical_license:
        reason_codes.append("license_evidence_expression_mismatch")

    if governance.maintenance_status != "reported_recent":
        reason_codes.append("maintenance_not_reported_recent")
    if governance.maintenance_evidence_kind != "source_last_updated":
        reason_codes.append("maintenance_evidence_not_source_report")
    if not _normalized_text(governance.maintenance_evidence_source):
        reason_codes.append("maintenance_evidence_source_missing")
    maintenance_match = _LAST_UPDATED_PATTERN.search(governance.maintenance_evidence_excerpt)
    if maintenance_match is None:
        reason_codes.append("maintenance_evidence_excerpt_missing")

    assessment_time = _parse_datetime(governance.assessed_at or "")
    if assessment_time is None:
        reason_codes.append("assessment_time_missing")
    maintenance_date = _parse_date(governance.maintenance_updated_at or "")
    if maintenance_date is None:
        reason_codes.append("maintenance_date_invalid")
    elif assessment_time is not None:
        if maintenance_date > assessment_time.date():
            reason_codes.append("maintenance_reported_date_invalid")
        elif (assessment_time.date() - maintenance_date).days > MAINTENANCE_RECENCY_DAYS:
            reason_codes.append("maintenance_reported_stale")
    if maintenance_match is not None and maintenance_date is not None:
        evidence_date = _parse_date(maintenance_match.group(1))
        if evidence_date != maintenance_date:
            reason_codes.append("maintenance_evidence_date_mismatch")

    expected_audit_signals = {
        "license_permissive_spdx_observed",
        "maintenance_reported_recent",
    }
    if not expected_audit_signals.issubset(set(governance.commercial_reuse_reason_codes)):
        reason_codes.append("commercial_reuse_audit_signals_missing")
    return list(dict.fromkeys(reason_codes))


def is_commercial_reuse_eligible(
    governance: SourceIntakeGovernance | Mapping[str, object] | object | None,
) -> bool:
    """Whether a nested governance record permits automatic commercial reuse."""

    return not commercial_reuse_eligibility_reason_codes(governance)


def is_external_reference_source(source_uri: str, source_type: str = "") -> bool:
    """Classify project-source references conservatively without hiding local work.

    Explicit local paths and Trainer-owned URI schemes keep their normal learning
    path. Every other nonempty reference is external unless it can be identified
    as local, which prevents unknown URI forms from bypassing reuse governance.
    """

    source = str(source_uri or "").strip()
    normalized_source = source.casefold()
    normalized_source_type = str(source_type or "").strip().casefold()
    if _is_remote_reference_uri(source, normalized_source):
        return True
    if normalized_source_type.startswith(_EXTERNAL_SOURCE_TYPE_PREFIXES):
        return True
    if _is_explicit_local_reference(
        source,
        normalized_source,
        normalized_source_type,
    ):
        return False
    return bool(source or normalized_source_type)


def _coerce_source_governance(
    value: SourceIntakeGovernance | Mapping[str, object] | object | None,
) -> SourceIntakeGovernance | None:
    if isinstance(value, SourceIntakeGovernance):
        return value
    payload = source_governance_payload(value)
    if payload is None:
        return None
    try:
        return SourceIntakeGovernance.model_validate(payload)
    except ValueError:
        return None


def _is_remote_reference_uri(source: str, normalized_source: str) -> bool:
    if not source or _WINDOWS_ABSOLUTE_PATH_PATTERN.match(source):
        return False
    if _GIT_SSH_REFERENCE_PATTERN.match(source):
        return True
    scheme_match = _URI_SCHEME_PATTERN.match(source)
    if scheme_match is None:
        return False
    return scheme_match.group(1).casefold() not in _LOCAL_URI_SCHEMES


def _is_explicit_local_reference(
    source: str,
    normalized_source: str,
    normalized_source_type: str,
) -> bool:
    if normalized_source.startswith(_LOCAL_URI_PREFIXES):
        return True
    if normalized_source_type.startswith(_LOCAL_SOURCE_TYPE_PREFIXES):
        return True
    if _WINDOWS_ABSOLUTE_PATH_PATTERN.match(source) or source.startswith(("\\\\", "/")):
        return True
    return source.startswith(("./", "../", ".\\", "..\\", "~/", "~\\"))


def _commercial_reuse_status(
    *,
    license_status: str,
    license_expression: str,
    maintenance_status: str,
    controlled_provenance: bool,
    reason_codes: list[str],
) -> CommercialReuseStatus:
    if not controlled_provenance:
        reason_codes.append("controlled_provenance_missing")
    if license_status != "observed":
        reason_codes.append(
            "license_declared_unverified" if license_status == "declared" else "license_unknown"
        )
    elif license_expression not in PERMISSIVE_SPDX_IDENTIFIERS:
        reason_codes.append("license_not_in_permissive_allowlist")
        return "blocked"
    else:
        reason_codes.append("license_permissive_spdx_observed")

    if maintenance_status == "reported_stale":
        reason_codes.append("maintenance_reported_stale")
        return "blocked"
    if maintenance_status == "reported_recent":
        reason_codes.append("maintenance_reported_recent")
    elif maintenance_status == "declared":
        reason_codes.append("maintenance_declared_unverified")
    else:
        reason_codes.append("maintenance_unknown")

    if (
        license_status == "observed"
        and license_expression in PERMISSIVE_SPDX_IDENTIFIERS
        and maintenance_status == "reported_recent"
        and controlled_provenance
    ):
        return "eligible"
    return "review_required"


def _assessment_time(
    provenance: Mapping[str, object],
    *,
    assessed_at: datetime | None,
) -> datetime:
    if assessed_at is not None:
        return _as_utc(assessed_at)
    fetched_at = _parse_datetime(str(provenance.get("fetched_at") or ""))
    return fetched_at or datetime.now(UTC)


def _evidence_source(source_uri: str, provenance: Mapping[str, object]) -> str:
    if _provenance_status(provenance) == "fetched":
        final_url = _normalized_text(str(provenance.get("final_url") or ""))
        if final_url:
            return final_url
    return _normalized_text(source_uri)


def _provenance_status(provenance: Mapping[str, object]) -> str:
    status = _normalized_text(str(provenance.get("status") or "")).lower()
    return status or "unknown"


def _parse_datetime(value: str) -> datetime | None:
    normalized = _normalized_text(value)
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalized_text(value: str) -> str:
    return " ".join(value.strip().split())[:512]


def _canonical_spdx_identifier(value: str) -> str:
    normalized = _normalized_text(value)
    return _PERMISSIVE_SPDX_BY_CASEFOLD.get(normalized.casefold(), normalized)
