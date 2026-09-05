import pytest

from app.resources.asset_governance import (
    AssetGovernanceDisposition,
    AssetGovernanceOperation,
    evaluate_asset_governance,
)


@pytest.mark.parametrize(
    "operation",
    [
        AssetGovernanceOperation.DERIVED_LINK,
        AssetGovernanceOperation.SUMMARY_CANDIDATE,
    ],
)
def test_recomputable_derived_artifacts_can_auto_commit(operation: AssetGovernanceOperation) -> None:
    decision = evaluate_asset_governance(operation, recomputable=True)

    assert decision.disposition is AssetGovernanceDisposition.AUTO_COMMIT
    assert decision.requires_approval is False
    assert decision.reason == "recomputable_derived_artifact"


@pytest.mark.parametrize(
    "operation",
    [
        AssetGovernanceOperation.DERIVED_LINK,
        AssetGovernanceOperation.SUMMARY_CANDIDATE,
    ],
)
def test_non_recomputable_derivatives_stay_proposals(operation: AssetGovernanceOperation) -> None:
    decision = evaluate_asset_governance(operation, recomputable=False)

    assert decision.disposition is AssetGovernanceDisposition.PROPOSAL
    assert decision.requires_approval is True
    assert decision.reason == "derived_artifact_not_recomputable"


@pytest.mark.parametrize(
    "operation",
    [
        AssetGovernanceOperation.FETCH_URL,
        AssetGovernanceOperation.SHARE_CROSS_PROJECT,
        AssetGovernanceOperation.DELETE,
        AssetGovernanceOperation.PROMOTE_LONG_TERM_MEMORY,
        AssetGovernanceOperation.DEFINE_HABIT,
        AssetGovernanceOperation.DEFINE_SKILL,
    ],
)
def test_protected_operations_always_require_approval(operation: AssetGovernanceOperation) -> None:
    decision = evaluate_asset_governance(operation, recomputable=True)

    assert decision.disposition is AssetGovernanceDisposition.PROPOSAL
    assert decision.requires_approval is True
    assert decision.reason == "protected_asset_operation"


def test_unknown_operations_fail_closed_as_proposals() -> None:
    decision = evaluate_asset_governance("invent_asset_policy", recomputable=True)

    assert decision.operation == "invent_asset_policy"
    assert decision.disposition is AssetGovernanceDisposition.PROPOSAL
    assert decision.requires_approval is True
    assert decision.reason == "unknown_asset_operation"


def test_string_operations_normalize_without_changing_governance() -> None:
    decision = evaluate_asset_governance("summary-candidate", recomputable=True)

    assert decision.operation == AssetGovernanceOperation.SUMMARY_CANDIDATE
    assert decision.disposition is AssetGovernanceDisposition.AUTO_COMMIT
