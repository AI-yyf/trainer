"""Pure approval policy for agent-originated resource asset operations.

This module deliberately has no repository, network, or filesystem dependency.
Callers can use its decision before they prepare an operation, then route proposal
decisions through an explicit learner or workspace-owner approval surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AssetGovernanceOperation(StrEnum):
    """Operations an agent may request against the resource asset library."""

    DERIVED_LINK = "derived_link"
    SUMMARY_CANDIDATE = "summary_candidate"
    FETCH_URL = "fetch_url"
    SHARE_CROSS_PROJECT = "share_cross_project"
    DELETE = "delete"
    PROMOTE_LONG_TERM_MEMORY = "promote_long_term_memory"
    DEFINE_HABIT = "define_habit"
    DEFINE_SKILL = "define_skill"


class AssetGovernanceDisposition(StrEnum):
    """Whether the caller may persist the requested operation immediately."""

    AUTO_COMMIT = "auto_commit"
    PROPOSAL = "proposal"


@dataclass(frozen=True, slots=True)
class AssetGovernanceDecision:
    """A side-effect-free decision returned before asset mutation."""

    operation: str
    disposition: AssetGovernanceDisposition
    requires_approval: bool
    reason: str


_AUTO_COMMIT_OPERATIONS = frozenset(
    {
        AssetGovernanceOperation.DERIVED_LINK,
        AssetGovernanceOperation.SUMMARY_CANDIDATE,
    }
)

_APPROVAL_REQUIRED_OPERATIONS = frozenset(
    {
        AssetGovernanceOperation.FETCH_URL,
        AssetGovernanceOperation.SHARE_CROSS_PROJECT,
        AssetGovernanceOperation.DELETE,
        AssetGovernanceOperation.PROMOTE_LONG_TERM_MEMORY,
        AssetGovernanceOperation.DEFINE_HABIT,
        AssetGovernanceOperation.DEFINE_SKILL,
    }
)


def evaluate_asset_governance(
    operation: AssetGovernanceOperation | str,
    *,
    recomputable: bool,
) -> AssetGovernanceDecision:
    """Classify an agent request without performing the request itself.

    Only a recomputable derived link or summary candidate may be committed
    automatically. Every other known operation, plus unknown operations, remains
    a proposal so that no external fetch, cross-project boundary change, deletion,
    durable-memory promotion, or behavior definition happens silently.
    """

    normalized_operation = _normalize_operation(operation)
    if normalized_operation in _AUTO_COMMIT_OPERATIONS and recomputable:
        return AssetGovernanceDecision(
            operation=normalized_operation,
            disposition=AssetGovernanceDisposition.AUTO_COMMIT,
            requires_approval=False,
            reason="recomputable_derived_artifact",
        )

    if normalized_operation in _APPROVAL_REQUIRED_OPERATIONS:
        reason = "protected_asset_operation"
    elif normalized_operation in _AUTO_COMMIT_OPERATIONS:
        reason = "derived_artifact_not_recomputable"
    else:
        reason = "unknown_asset_operation"

    return AssetGovernanceDecision(
        operation=normalized_operation,
        disposition=AssetGovernanceDisposition.PROPOSAL,
        requires_approval=True,
        reason=reason,
    )


def _normalize_operation(operation: AssetGovernanceOperation | str) -> str:
    if isinstance(operation, AssetGovernanceOperation):
        return operation.value
    return str(operation).strip().lower().replace("-", "_")
