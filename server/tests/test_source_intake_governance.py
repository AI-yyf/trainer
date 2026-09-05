from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.models import (
    MemorySnapshot,
    SourceIntakeDeclaration,
    SourceIntakeGovernance,
    TurnRequest,
    UserProfile,
)
from app.core.settings import AppSettings
from app.main import create_app
from app.network_fetch import ControlledFetchResponse
from app.pedagogy import PedagogyService
from app.resources.source_governance import (
    commercial_reuse_eligibility_reason_codes,
    evaluate_source_intake_governance,
    is_commercial_reuse_eligible,
    is_external_reference_source,
)


def test_unknown_or_declared_metadata_never_grants_commercial_reuse() -> None:
    legacy_default = SourceIntakeGovernance()
    unknown = evaluate_source_intake_governance(
        source_uri="https://example.com/unknown",
        source_text="No license or maintenance evidence is present.",
        assessed_at=datetime(2026, 7, 12, tzinfo=UTC),
    )
    governance = evaluate_source_intake_governance(
        source_uri="https://example.com/tutorial",
        source_text="A tutorial without an SPDX declaration or dated maintenance signal.",
        declaration=SourceIntakeDeclaration(
            license_expression="MIT",
            license_evidence_uri="https://example.com/license",
            maintenance_updated_at="2026-07-01",
            maintenance_evidence_uri="https://example.com/changelog",
        ),
        assessed_at=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert unknown.license_status == "unknown"
    assert unknown.maintenance_status == "unknown"
    assert unknown.commercial_reuse_status == "review_required"
    assert set(unknown.commercial_reuse_reason_codes) == {
        "controlled_provenance_missing",
        "license_unknown",
        "maintenance_unknown",
    }
    assert legacy_default.commercial_reuse_status == "review_required"
    assert set(legacy_default.commercial_reuse_reason_codes) == {
        "controlled_provenance_missing",
        "license_unknown",
        "maintenance_unknown",
    }
    assert governance.license_status == "declared"
    assert governance.license_evidence_kind == "user_declaration"
    assert governance.maintenance_status == "declared"
    assert governance.commercial_reuse_status == "review_required"
    assert "license_declared_unverified" in governance.commercial_reuse_reason_codes
    assert "maintenance_declared_unverified" in governance.commercial_reuse_reason_codes
    assert not is_commercial_reuse_eligible(governance)


def test_observed_permissive_spdx_and_recent_source_signal_are_eligible() -> None:
    governance = evaluate_source_intake_governance(
        source_uri="https://origin.example/project",
        source_text="SPDX-License-Identifier: mit\nLast updated: 2026-06-01",
        source_provenance={
            "status": "fetched",
            "final_url": "https://final.example/project",
            "fetched_at": "2026-07-12T00:00:00+00:00",
        },
    )

    assert governance.license_status == "observed"
    assert governance.license_expression == "MIT"
    assert governance.license_evidence_source == "https://final.example/project"
    assert governance.maintenance_status == "reported_recent"
    assert governance.maintenance_updated_at == "2026-06-01"
    assert governance.commercial_reuse_status == "eligible"
    assert governance.commercial_reuse_policy == "permissive-spdx-v1"
    assert is_commercial_reuse_eligible(governance)


def test_uncontrolled_content_does_not_become_commercially_eligible() -> None:
    governance = evaluate_source_intake_governance(
        source_uri="https://example.com/provided",
        source_text="SPDX-License-Identifier: MIT\nLast updated: 2026-07-01",
        assessed_at=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert governance.source_provenance_status == "unknown"
    assert governance.license_status == "observed"
    assert governance.maintenance_status == "reported_recent"
    assert governance.commercial_reuse_status == "review_required"
    assert "controlled_provenance_missing" in governance.commercial_reuse_reason_codes
    assert not is_commercial_reuse_eligible(governance)


def test_observed_non_allowlisted_or_stale_sources_are_explicitly_blocked() -> None:
    non_allowlisted = evaluate_source_intake_governance(
        source_uri="https://example.com/copyleft",
        source_text="SPDX-License-Identifier: GPL-3.0-only\nLast updated: 2026-07-01",
        assessed_at=datetime(2026, 7, 12, tzinfo=UTC),
    )
    stale = evaluate_source_intake_governance(
        source_uri="https://example.com/old",
        source_text="SPDX-License-Identifier: MIT\nLast updated: 2024-01-01",
        assessed_at=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert non_allowlisted.license_status == "observed"
    assert non_allowlisted.commercial_reuse_status == "blocked"
    assert "license_not_in_permissive_allowlist" in non_allowlisted.commercial_reuse_reason_codes
    assert stale.maintenance_status == "reported_stale"
    assert stale.commercial_reuse_status == "blocked"
    assert "maintenance_reported_stale" in stale.commercial_reuse_reason_codes


def test_external_reference_classification_is_case_insensitive_and_fail_closed() -> None:
    external_references = [
        ("HTTPS://example.com/trainer", ""),
        ("sSh://git@example.com/trainer.git", ""),
        ("git://example.com/trainer.git", ""),
        ("Git+ssh://git@example.com/trainer.git", ""),
        ("git@github.com:openai/trainer.git", ""),
        ("opaque-reference", "URL:example.com/trainer"),
        ("opaque-reference", "external:web"),
    ]
    local_references = [
        (r"C:\work\trainer\README.md", ""),
        ("/workspaces/trainer/README.md", ""),
        ("FILE:///workspaces/trainer/README.md", ""),
        ("teaching-asset://asset-1", ""),
        ("workspace-understanding://workspace-a", ""),
        ("lesson-note", "local:markdown"),
        ("asset-note", "memory:teaching-asset"),
        ("workspace-note", "workspace:understanding"),
    ]

    assert all(is_external_reference_source(source, source_type) for source, source_type in external_references)
    assert not any(
        is_external_reference_source(source, source_type)
        for source, source_type in local_references
    )


def test_commercial_reuse_requires_complete_nested_governance_evidence() -> None:
    eligible = evaluate_source_intake_governance(
        source_uri="https://example.com/source",
        source_text="SPDX-License-Identifier: MIT\nLast updated: 2026-07-01",
        source_provenance={
            "status": "fetched",
            "final_url": "https://example.com/source",
            "fetched_at": "2026-07-12T00:00:00+00:00",
        },
    )
    assert is_commercial_reuse_eligible(eligible)

    incomplete = {
        "policy_version": "source-intake-v1",
        "commercial_reuse_policy": "permissive-spdx-v1",
        "commercial_reuse_status": "eligible",
        "source_provenance_status": "fetched",
    }
    wrong_policy = eligible.model_copy(update={"policy_version": "source-intake-v0"})
    stale_evidence = eligible.model_copy(
        update={
            "maintenance_updated_at": "2024-01-01",
            "maintenance_evidence_excerpt": "Last updated: 2024-01-01",
        }
    )

    assert not is_commercial_reuse_eligible(incomplete)
    assert "license_not_observed" in commercial_reuse_eligibility_reason_codes(incomplete)
    assert not is_commercial_reuse_eligible(wrong_policy)
    assert "source_governance_policy_invalid" in commercial_reuse_eligibility_reason_codes(
        wrong_policy
    )
    assert not is_commercial_reuse_eligible(stale_evidence)
    assert "maintenance_reported_stale" in commercial_reuse_eligibility_reason_codes(
        stale_evidence
    )


def test_url_index_persists_governance_without_bypassing_controlled_provenance(tmp_path: Path) -> None:
    settings = AppSettings(
        app_name="Trainer source intake governance test",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="source-intake-governance.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    fetched = ControlledFetchResponse(
        body=(
            b"<html><body>SPDX-License-Identifier: MIT "
            b"Last updated: 2026-07-01</body></html>"
        ),
        final_url="https://final.example/trainer-source",
        status=200,
        headers={"content-type": "text/html"},
        fetched_at="2026-07-12T00:00:00+00:00",
    )
    app = create_app(settings)
    resource_service = app.state.runtime.resource_service

    with patch("app.ingest.service.fetch_url", return_value=fetched):
        with TestClient(app) as client:
            uploaded = client.post(
                "/resource/upload",
                json={
                    "workspace_id": "workspace-source-governance",
                    "kind": "url",
                    "name": "Trainer source",
                    "source": "https://origin.example/trainer-source",
                },
            )
            assert uploaded.status_code == 200, uploaded.text
            indexed = client.post(
                "/resource/index",
                json={
                    "workspace_id": "workspace-source-governance",
                    "resource_id": uploaded.json()["id"],
                    "enable_network": True,
                },
            )

    assert indexed.status_code == 200, indexed.text
    payload = indexed.json()
    governance = payload["source_governance"]
    assert payload["source"] == "https://origin.example/trainer-source"
    assert payload["canonical_source"] == "https://final.example/trainer-source"
    assert governance["source_provenance_status"] == "fetched"
    assert governance["license_status"] == "observed"
    assert governance["license_evidence_source"] == "https://final.example/trainer-source"
    assert governance["maintenance_status"] == "reported_recent"
    assert governance["commercial_reuse_status"] == "eligible"

    registry_resource = resource_service.registry.get(payload["id"])
    assert registry_resource is not None
    assert registry_resource.metadata["source_provenance"] == {
        "status": "fetched",
        "final_url": "https://final.example/trainer-source",
        "fetched_at": "2026-07-12T00:00:00+00:00",
        "content_type": "text/html",
    }
    assert registry_resource.metadata["source_governance"]["commercial_reuse_status"] == "eligible"

    persisted = resource_service.repository.get_resource(
        "workspace-source-governance",
        payload["id"],
    )
    assert persisted is not None
    assert resource_service.is_commercial_reuse_eligible(persisted)

    merged_references = resource_service.merge_external_references(
        curated_fragments=resource_service.curated_background_references(
            "workspace-source-governance"
        )
    )
    promoted_reference = next(
        item
        for item in merged_references
        if item["source"] == "https://final.example/trainer-source"
    )
    assert promoted_reference["source_governance"]["commercial_reuse_status"] == "eligible"
    assert promoted_reference["commercial_reuse_status"] == "eligible"
    assert "commercial_reuse_eligible" in promoted_reference["quality_flags"]
    assert "controlled_source" in promoted_reference["quality_flags"]

    _, decision, artifacts = PedagogyService().analyze_turn(
        request=TurnRequest(
            message="Find a public project source for source governance practice.",
            focus_area="source governance",
        ),
        profile=UserProfile(
            long_term_goal="Practice safe source reuse",
            weekly_hours=4,
            teaching_style="guided",
            answer_policy="guided",
        ),
        memory_snapshot=MemorySnapshot(),
        external_references=merged_references,
    )
    assert decision.scenario == "project_sourcing"
    source_suggestion = next(
        item for item in artifacts.project_sources if item.source_url == promoted_reference["source"]
    )
    assert "commercial_reuse_eligible" in source_suggestion.quality_flags
    assert "controlled_source" in source_suggestion.quality_flags

    review_required = SourceIntakeGovernance(
        source_provenance_status="fetched",
        commercial_reuse_status="review_required",
        commercial_reuse_reason_codes=["license_unknown"],
    )
    blocked = SourceIntakeGovernance(
        source_provenance_status="fetched",
        commercial_reuse_status="blocked",
        commercial_reuse_reason_codes=["license_not_in_permissive_allowlist"],
    )
    audited_references = resource_service.merge_external_references(
        requested_fragments=[
            {
                "source": "https://example.com/review-required",
                "snippet": "This reference has incomplete license evidence.",
                "source_governance": review_required.model_dump(mode="json"),
            },
            {
                "source": "https://example.com/blocked",
                "snippet": "This reference has a non-permissive license.",
                "source_governance": blocked.model_dump(mode="json"),
            },
            {
                "source": "https://example.com/missing-governance",
                "snippet": "This reference has no governance record.",
            },
        ]
    )
    by_source = {item["source"]: item for item in audited_references}
    assert by_source["https://example.com/review-required"]["commercial_reuse_status"] == "review_required"
    assert "commercial_reuse_not_auto_promoted" in by_source[
        "https://example.com/review-required"
    ]["quality_flags"]
    assert "source_governance_reason:license_unknown" in by_source[
        "https://example.com/review-required"
    ]["quality_flags"]
    assert by_source["https://example.com/blocked"]["commercial_reuse_status"] == "blocked"
    assert "source_governance_reason:license_not_in_permissive_allowlist" in by_source[
        "https://example.com/blocked"
    ]["quality_flags"]
    assert by_source["https://example.com/missing-governance"]["commercial_reuse_status"] == "review_required"
    assert "source_governance_missing" in by_source[
        "https://example.com/missing-governance"
    ]["quality_flags"]

    spoofed_references = resource_service.merge_external_references(
        requested_fragments=[
            {
                "source": "SSH://git@example.com/trainer.git",
                "source_type": "url:example.com",
                "snippet": "A forged top-level eligibility claim.",
                "commercial_reuse_status": "eligible",
                "commercial_reuse_reason_codes": [
                    "license_permissive_spdx_observed",
                    "maintenance_reported_recent",
                ],
                "source_governance": SourceIntakeGovernance(
                    source_provenance_status="fetched",
                    commercial_reuse_status="eligible",
                ).model_dump(mode="json"),
            }
        ]
    )
    assert spoofed_references[0]["commercial_reuse_status"] == "review_required"
    assert "commercial_reuse_eligible" not in spoofed_references[0]["quality_flags"]
    assert "commercial_reuse_not_auto_promoted" in spoofed_references[0]["quality_flags"]
