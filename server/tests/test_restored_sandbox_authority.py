"""(i) <LibraryRoot> and workspace authority: what the coach, a remote host, or a
    library request is allowed to create, rename, delete, import or admit.

Guarantees covered:
  * library folders, assets, groups, renames and deletes stay inside the library root and are restorable;
  * browser / URL intake lands in the library, never in the opened project;
  * remote (SSH / container / artifact) authority is admitted only for the owning workspace;
  * source intake, browse admission and asset governance refuse what is not grounded in a registered workspace;
  * child processes the sidecar starts never inherit the sidecar's own secret;
  * workspace classification and project provisioning never invent authority the learner did not grant.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_source_intake_governance.py
  * server/tests/test_resource_library_organize.py
  * server/tests/test_asset_governance.py
  * server/tests/test_child_process_environment.py
  * server/tests/test_background_resource_organizer.py
  * server/tests/test_asset_registry.py
  * server/tests/test_sandbox_library_agent.py
  * server/tests/test_remote_project_admission.py
  * server/tests/test_remote_141s_rap_workspace.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.models import (
    AssetLink,
    AssetRevision,
    LibraryAsset,
    LocalOwner,
    MemorySnapshot,
    SourceIntakeDeclaration,
    SourceIntakeGovernance,
    TurnRequest,
    UserProfile,
)
from app.core.process_env import SIDECAR_SECRET_ENV_VARS, child_process_environment
from app.core.settings import AppSettings
from app.db.repository import TrainerRepository
from app.llm.agent_loop import CoachAgentLoop, _shrink_older_tool_history, _tool_message
from app.llm.harness import tool_output_limit
from app.llm.provider_service import _agent_loop_max_steps
from app.main import create_app
from app.network_fetch import ControlledFetchResponse
from app.pedagogy import PedagogyService
from app.resources.asset_governance import (
    AssetGovernanceDisposition,
    AssetGovernanceOperation,
    evaluate_asset_governance,
)
from app.resources.ingest import ExtractedContent
from app.resources.source_governance import (
    commercial_reuse_eligibility_reason_codes,
    evaluate_source_intake_governance,
    is_commercial_reuse_eligible,
    is_external_reference_source,
)
from app.workspace.remote_identity import canonical_remote_project_uri

# ---------------------------------------------------------------------------
# Restored from test_source_intake_governance.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Restored from test_resource_library_organize.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer library organize",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-library-organize.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    return TestClient(create_app(settings))


def _capture_page(client: TestClient, monkeypatch, workspace_id: str, url: str) -> dict:
    def fake_extract(value: str, *, network_enabled: bool = False) -> ExtractedContent:
        return ExtractedContent(
            title="Rotation notes",
            text="The rotation guard runs before the retry queue drains.",
            author=None,
            date=None,
            url=value,
        )

    monkeypatch.setattr("app.resources.capture.extract_from_url", fake_extract)
    session_id = client.post(
        "/session/start",
        json={"workspace_id": workspace_id, "workspace_name": "Organize"},
    ).json()["session_id"]
    response = client.post(
        "/resources/capture",
        json={
            "session_id": session_id,
            "workspace_id": workspace_id,
            "url": url,
            "kind": "web",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_rename_updates_the_display_name_only(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-organize-rename"
    with build_client(tmp_path) as client:
        captured = _capture_page(client, monkeypatch, workspace_id, "https://docs.example.com/rename")
        source_before = captured["source"]
        # Whether the snapshot file exists is decided when the resource is indexed (a
        # resource with its canonical Markdown no longer keeps the upload), not by a
        # rename, so compare with the state right before the rename.
        snapshot_existed_before_rename = Path(source_before).is_file()

        renamed = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": captured["id"],
                "action": "rename",
                "title": "Guard ordering notes",
            },
        )

        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["name"] == "Guard ordering notes"
        assert renamed.json()["source"] == source_before
        assert Path(source_before).is_file() == snapshot_existed_before_rename

        empty = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": captured["id"],
                "action": "rename",
                "title": "   ",
            },
        )
        assert empty.status_code == 422


def test_set_tags_dedupes_truncates_and_clears(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-organize-tags"
    with build_client(tmp_path) as client:
        captured = _capture_page(client, monkeypatch, workspace_id, "https://docs.example.com/tags")

        tagged = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": captured["id"],
                "action": "set_tags",
                "tags": ["networking", "auth", "Networking", "  ", "x" * 80],
            },
        )
        assert tagged.status_code == 200, tagged.text
        tags = tagged.json()["tags"]
        assert tags[0:2] == ["networking", "auth"]
        assert len(tags) == 3
        assert len(tags[2]) == 40

        cleared = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": captured["id"],
                "action": "set_tags",
                "tags": [],
            },
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["tags"] == []


def test_group_move_relocates_the_snapshot_and_can_be_cleared(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-organize-group"
    with build_client(tmp_path) as client:
        captured = _capture_page(client, monkeypatch, workspace_id, "https://docs.example.com/group")
        original_source = Path(captured["source"])
        snapshot_still_exists = original_source.is_file()

        grouped = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": captured["id"],
                "action": "set_group",
                "group": "Web snapshots/Docs",
            },
        )
        assert grouped.status_code == 200, grouped.text
        payload = grouped.json()
        assert payload["collection_path"] == "Docs/" + Path(payload["source"]).name
        assert payload["collection_root"]
        if snapshot_still_exists:
            # A snapshot that is still the resource's file is really moved into the group.
            assert Path(payload["source"]).is_file()
            assert Path(payload["source"]).parts[-2:] == ("Docs", original_source.name)
        else:
            # The upload was already replaced by the resource's canonical Markdown: the
            # group is metadata, and nothing is written under a path that does not exist.
            assert payload["source"] == captured["source"]
        assert not original_source.exists()

        # The moved snapshot is still searchable and still opens/exports.
        found = client.post(
            "/resource/search",
            json={"workspace_id": workspace_id, "query": "rotation guard"},
        )
        assert found.status_code == 200, found.text
        assert captured["id"] in {hit["id"] for hit in found.json()["hits"]}

        exported = client.get(
            "/resource/export",
            params={"workspace_id": workspace_id, "resource_id": captured["id"]},
        )
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-disposition"].startswith("attachment;")
        assert "rotation guard" in exported.text

        ungrouped = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": captured["id"],
                "action": "set_group",
                "group": "",
            },
        )
        assert ungrouped.status_code == 200, ungrouped.text
        assert ungrouped.json()["collection_path"] is None
        assert ungrouped.json()["collection_root"] is None


def test_group_move_refuses_unsafe_and_reserved_names(tmp_path, monkeypatch) -> None:
    workspace_id = "workspace-organize-guard"
    with build_client(tmp_path) as client:
        captured = _capture_page(client, monkeypatch, workspace_id, "https://docs.example.com/guard")
        for group in ("../escape", "a//b", "trainer", ".trainer", "x/../../y"):
            response = client.post(
                "/resource/organize",
                json={
                    "workspace_id": workspace_id,
                    "resource_id": captured["id"],
                    "action": "set_group",
                    "group": group,
                },
            )
            assert response.status_code == 422, (group, response.text)


def test_organize_refuses_unknown_resources(tmp_path) -> None:
    with build_client(tmp_path) as client:
        client.post(
            "/session/start",
            json={"workspace_id": "workspace-organize-404", "workspace_name": "Organize"},
        )
        response = client.post(
            "/resource/organize",
            json={
                "workspace_id": "workspace-organize-404",
                "resource_id": "resource-missing",
                "action": "rename",
                "title": "Nope",
            },
        )
    assert response.status_code == 404, response.text


def test_export_reports_missing_snapshots_honestly(tmp_path) -> None:
    workspace_id = "workspace-organize-export-missing"
    with build_client(tmp_path) as client:
        session_id = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Organize"},
        ).json()["session_id"]
        uploaded = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "kind": "url",
                "name": "Remote page",
                "source": "https://docs.example.com/remote-only",
            },
        )
        assert uploaded.status_code == 200, uploaded.text

        exported = client.get(
            "/resource/export",
            params={"workspace_id": workspace_id, "resource_id": uploaded.json()["id"]},
        )
        assert exported.status_code == 409, exported.text
        assert exported.json()["detail"]["code"] == "no_local_snapshot"


# ---------------------------------------------------------------------------
# Restored from test_asset_governance.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Restored from test_child_process_environment.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_child_environment_drops_the_sidecar_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", "instance-secret")
    monkeypatch.setenv("TRAINER learner_KEEP_ME", "kept")
    monkeypatch.setenv("PATH", "/usr/bin")

    environment = child_process_environment()

    assert "TRAINER_SIDECAR_TOKEN" not in environment
    assert environment["PATH"] == "/usr/bin"
    # Nothing else about the learner's environment is hidden from their own tools.
    assert "TRAINER learner_KEEP_ME" in environment
    assert SIDECAR_SECRET_ENV_VARS == ("TRAINER_SIDECAR_TOKEN",)


def test_child_environment_applies_explicit_overrides_last() -> None:
    environment = child_process_environment(
        {"TRAINER_SIDECAR_TOKEN": "secret", "A": "1"},
        {"B": "2", "A": "overridden"},
    )
    assert environment == {"A": "overridden", "B": "2"}


def test_a_real_child_process_cannot_see_the_sidecar_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The property that matters, observed end to end: code the sidecar runs
    as a child cannot read the token out of its own environment."""
    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", "instance-secret")
    script = tmp_path / "print_env.py"
    script.write_text(
        "import os, sys\nsys.stdout.write(os.environ.get('TRAINER_SIDECAR_TOKEN', '<absent>'))\n",
        encoding="utf-8",
    )

    inherited = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=True
    )
    scrubbed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        check=True,
        env=child_process_environment(),
    )

    assert inherited.stdout == "instance-secret"
    assert scrubbed.stdout == "<absent>"


def test_evaluator_runner_starts_children_without_the_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.evaluator.models import CheckCommand
    from app.evaluator.service import SubprocessCommandRunner

    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", "instance-secret")
    probe = tmp_path / "token_env.py"
    probe.write_text(
        "import os\nprint(os.environ.get('TRAINER_SIDECAR_TOKEN', '<absent>'))\n",
        encoding="utf-8",
    )

    result = SubprocessCommandRunner().run(
        CheckCommand(
            name="python-script", argv=[sys.executable, "-B", str(probe)], cwd=str(tmp_path)
        )
    )

    assert result.stdout is not None
    assert "instance-secret" not in result.stdout
    assert "<absent>" in result.stdout


# ---------------------------------------------------------------------------
# Restored from test_background_resource_organizer.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


WORKSPACE_ID = "ws-bg-organizer"


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer background organizer",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-bg-organizer.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _upload_inline_markdown(client: TestClient) -> dict:
    session_id = client.post(
        "/session/start",
        json={"workspace_id": WORKSPACE_ID, "workspace_name": "Organizer"},
    ).json()["session_id"]
    response = client.post(
        "/resource/upload",
        json={
            "session_id": session_id,
            "workspace_id": WORKSPACE_ID,
            "kind": "markdown",
            "name": "Rotation guard notes",
            "source": "notes/rotation-guard.md",
            "content": "# Rotation guard\n\nThe rotation guard runs before the retry queue drains.",
            "source_type": "file",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_background_sweep_indexes_pending_resources(tmp_path: Path) -> None:
    import asyncio

    app = create_app(_settings(tmp_path / "data"))
    record = _upload_inline_markdown(TestClient(app))
    assert record["index_status"] == "pending"

    organized = asyncio.run(app.state.runtime.organize_pending_resources_once())
    assert organized >= 1

    listed = app.state.runtime.repository.list_resources(WORKSPACE_ID)
    swept = next(item for item in listed if item.id == record["id"])
    assert swept.index_status == "indexed"
    assert swept.summary != "Registered and waiting for parsing."


def test_background_sweep_skips_already_indexed_and_never_raises(tmp_path: Path) -> None:
    import asyncio

    app = create_app(_settings(tmp_path / "data"))
    runtime = app.state.runtime
    organized = asyncio.run(runtime.organize_pending_resources_once())
    assert organized == 0

    record = _upload_inline_markdown(TestClient(app))
    first = asyncio.run(runtime.organize_pending_resources_once())
    assert first >= 1
    # A second pass finds nothing pending: the sweep is bounded and quiet.
    second = asyncio.run(runtime.organize_pending_resources_once())
    assert second == 0
    listed = runtime.repository.list_resources(WORKSPACE_ID)
    swept = next(item for item in listed if item.id == record["id"])
    assert swept.index_status == "indexed"


def test_event_sweep_indexes_on_arrival_single_flight(tmp_path: Path, monkeypatch) -> None:
    """Arrival-driven sweep: a notification indexes the pending resource, and
    an arrival during a running pass carries over exactly once — no recurring
    timer exists to wake an idle Trainer."""
    import asyncio

    from app.api import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "BACKGROUND_ORGANIZER_DEBOUNCE_SECONDS", 0.05)
    app = create_app(_settings(tmp_path / "data"))
    runtime = app.state.runtime
    record = _upload_inline_markdown(TestClient(app))

    async def scenario() -> None:
        runtime.bind_organizer_loop(asyncio.get_running_loop())
        runtime.request_organizer_sweep()
        # An arrival while the pass is scheduled/running coalesces into the
        # same single-flight chain instead of forking a second timer.
        runtime.request_organizer_sweep()
        # request_organizer_sweep() hops through call_soon_threadsafe, so the
        # task attribute is set on a later turn of this loop.
        for _ in range(100):
            if runtime._organizer_sweep_task is not None:
                break
            await asyncio.sleep(0.01)
        # Wait on the real task, never a fixed sleep: indexing uses a worker
        # thread and Windows hosted runners can exceed any small wall-clock
        # budget (this exact assertion flaked the Windows CI job).
        for _ in range(4):
            task = runtime._organizer_sweep_task
            if task is None:
                break
            await asyncio.wait_for(task, timeout=60)
            if runtime._organizer_sweep_task is task:
                break
        assert runtime._organizer_sweep_pending is False
        assert (
            runtime._organizer_sweep_task is None or runtime._organizer_sweep_task.done()
        )

    asyncio.run(scenario())
    listed = runtime.repository.list_resources(WORKSPACE_ID)
    swept = next(item for item in listed if item.id == record["id"])
    assert swept.index_status == "indexed"


def test_unbound_loop_ignores_sweep_requests(tmp_path: Path) -> None:
    """A sync route may notify before the serving loop exists (tests, early
    startup): the request is dropped silently instead of raising."""
    app = create_app(_settings(tmp_path / "data"))
    app.state.runtime.request_organizer_sweep()


# ---------------------------------------------------------------------------
# Restored from test_asset_registry.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _repository_with_owner(tmp_path: Path) -> tuple[TrainerRepository, LocalOwner]:
    repository = TrainerRepository(tmp_path / "asset-registry.db")
    owner = LocalOwner(id="owner-local", displayName="Local Trainer")
    repository.save_local_owner(owner)
    return repository, owner


def _asset(owner_id: str, *, asset_id: str = "asset-url") -> LibraryAsset:
    return LibraryAsset(
        id=asset_id,
        ownerId=owner_id,
        assetType="external_source",
        scope="library",
        title="Reference page",
        canonicalSource="https://example.test/reference",
    )


def test_asset_registry_keeps_assets_and_revisions_owner_scoped(tmp_path: Path) -> None:
    repository, owner = _repository_with_owner(tmp_path)
    other_owner = LocalOwner(id="owner-other", displayName="Other Trainer")
    repository.save_local_owner(other_owner)
    asset = _asset(owner.id)
    repository.save_library_asset(asset)

    first = AssetRevision(
        id="revision-1",
        ownerId=owner.id,
        assetId=asset.id,
        contentHash="sha256:first",
        storagePath="snapshots/asset-url/revision-1/page.html",
        mediaType="text/html",
        sourceUrl=asset.canonical_source,
    )
    repository.save_asset_revision(first)
    repository.save_asset_revision(first)
    second = AssetRevision(
        id="revision-2",
        ownerId=owner.id,
        assetId=asset.id,
        parentRevisionId=first.id,
        contentHash="sha256:second",
        storagePath="snapshots/asset-url/revision-2/page.html",
        mediaType="text/html",
        sourceUrl=asset.canonical_source,
    )
    repository.save_asset_revision(second)
    repository.save_asset_revision(first)

    stored = repository.get_library_asset(owner.id, asset.id)
    assert stored is not None
    assert stored.current_revision_id == second.id
    repository.save_library_asset(asset.model_copy(update={"title": "Renamed reference page"}))
    stored_after_metadata_update = repository.get_library_asset(owner.id, asset.id)
    assert stored_after_metadata_update is not None
    assert stored_after_metadata_update.current_revision_id == second.id
    assert [item.id for item in repository.list_asset_revisions(owner.id, asset.id)] == [
        second.id,
        first.id,
    ]
    with pytest.raises(ValueError, match="descendants"):
        repository.delete_asset_revision(owner.id, asset.id, first.id)
    with pytest.raises(ValueError, match="cannot be modified"):
        repository.save_asset_revision(first.model_copy(update={"content_hash": "sha256:changed"}))
    assert repository.delete_asset_revision(owner.id, asset.id, second.id)
    restored_current = repository.get_library_asset(owner.id, asset.id)
    assert restored_current is not None
    assert restored_current.current_revision_id == first.id
    assert repository.get_library_asset(other_owner.id, asset.id) is None
    assert repository.get_asset_revision(other_owner.id, asset.id, first.id) is None
    with pytest.raises(PermissionError):
        repository.save_library_asset(asset.model_copy(update={"owner_id": other_owner.id}))
    with pytest.raises(PermissionError):
        repository.save_asset_revision(second.model_copy(update={"owner_id": other_owner.id}))


def test_asset_links_are_idempotent_and_owner_isolated(tmp_path: Path) -> None:
    repository, owner = _repository_with_owner(tmp_path)
    other_owner = LocalOwner(id="owner-other", displayName="Other Trainer")
    repository.save_local_owner(other_owner)
    asset = _asset(owner.id, asset_id="asset-plan")
    repository.save_library_asset(asset)

    link = AssetLink(
        id="link-plan-alpha",
        ownerId=owner.id,
        assetId=asset.id,
        workspaceId="workspace-alpha",
        relation="available_to",
        sourceRef="plan:plan-alpha",
        payload={"pinned": False},
    )
    repository.save_asset_link(link)
    repository.save_asset_link(
        link.model_copy(update={"id": "link-plan-alpha-updated", "payload": {"pinned": True}})
    )

    links = repository.list_asset_links(owner.id, workspace_id="workspace-alpha")
    assert len(links) == 1
    assert links[0].id == "link-plan-alpha"
    assert links[0].payload == {"pinned": True}
    assert repository.list_asset_links(other_owner.id, workspace_id="workspace-alpha") == []
    with pytest.raises(PermissionError):
        repository.save_asset_link(link.model_copy(update={"owner_id": other_owner.id}))
    assert repository.delete_asset_link(
        owner.id,
        asset.id,
        "workspace-alpha",
        "available_to",
        source_ref="plan:plan-alpha",
    )
    assert not repository.delete_asset_link(
        owner.id,
        asset.id,
        "workspace-alpha",
        "available_to",
        source_ref="plan:plan-alpha",
    )


def test_asset_deletion_cascades_links_and_revisions(tmp_path: Path) -> None:
    repository, owner = _repository_with_owner(tmp_path)
    asset = _asset(owner.id, asset_id="asset-memory")
    repository.save_library_asset(asset)
    repository.save_asset_revision(
        AssetRevision(
            id="revision-memory",
            ownerId=owner.id,
            assetId=asset.id,
            contentHash="sha256:memory",
            payload={"summary": "Durable reflection"},
        )
    )
    repository.save_asset_link(
        AssetLink(
            id="link-memory",
            ownerId=owner.id,
            assetId=asset.id,
            workspaceId="workspace-alpha",
            relation="references",
        )
    )

    assert repository.delete_library_asset(owner.id, asset.id)
    assert repository.get_library_asset(owner.id, asset.id) is None
    assert repository.list_asset_revisions(owner.id, asset.id) == []
    assert repository.list_asset_links(owner.id, asset_id=asset.id) == []


# ---------------------------------------------------------------------------
# Restored from test_sandbox_library_agent.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_agent_turns_share_a_high_safety_ceiling_not_lane_budgets() -> None:
    ceiling = CoachAgentLoop.SAFETY_MAX_STEPS
    assert ceiling >= 100
    assert _agent_loop_max_steps({"library_sandbox_work": True}) == ceiling
    assert _agent_loop_max_steps({"active_view": "resources"}) == ceiling
    assert _agent_loop_max_steps({"formal_plan_mutation": True}) == ceiling
    assert _agent_loop_max_steps({"active_view": "plan"}) == ceiling
    assert _agent_loop_max_steps({}) == ceiling
    assert _agent_loop_max_steps({"library_sandbox_work": True}, requested=3) == 3


def test_agent_loop_truncates_large_tool_payloads_and_shrinks_older_history() -> None:
    huge = {"ok": True, "body": "n" * 12_000}
    message = _tool_message("call-1", "write_sandbox_file", huge)
    assert len(str(message["content"])) <= tool_output_limit("write_sandbox_file") + 20
    history = [
        _tool_message("call-old-1", "list_sandbox", {"ok": True, "items": ["a" * 5_000]}),
        _tool_message("call-old-2", "read_sandbox_file", {"ok": True, "content": "b" * 5_000}),
        _tool_message("call-old-3", "read_sandbox_file", {"ok": True, "content": "c" * 5_000}),
        _tool_message("call-new", "write_sandbox_file", {"ok": True, "path": "notes.md"}),
    ]
    _shrink_older_tool_history(history)
    assert len(str(history[0]["content"])) <= CoachAgentLoop.MAX_KEPT_TOOL_RESULT_CHARS + 20
    assert "notes.md" in str(history[3]["content"])


# ---------------------------------------------------------------------------
# Restored from test_remote_project_admission.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("uri", [
    "file:///tmp/project", "vscode-remote://ssh-remote+owned/tmp/../outside",
    "vscode-remote://ssh-remote+owned/tmp/%2e%2e/outside",
    "vscode-remote://ssh-remote+owned/tmp/project?token=secret",
    "vscode-remote://user@ssh-remote+owned/tmp/project",
])
def test_remote_identity_rejects_ambiguous_or_credential_uris(uri: str) -> None:
    with pytest.raises(ValueError):
        canonical_remote_project_uri(uri)


# ---------------------------------------------------------------------------
# Restored from test_remote_141s_rap_workspace.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


REMOTE_ROOT = "/mnt/vdb1/yunfei.yan/RAP"


SNAPSHOT_CACHE = Path(r"G:\temp\rap_141s_snapshot.json")


def _fixture_snapshot() -> dict[str, Any]:
    contents = {
        "README.md": {
            "content": "RAP (Rasterization Augmented Planning) is a scalable data augmentation pipeline.",
            "language_id": "markdown",
        },
        "navsim/agents/abstract_agent.py": {
            "content": "class AbstractAgent:\n    def name(self) -> str:\n        raise NotImplementedError\n",
            "language_id": "python",
        },
        "setup.py": {
            "content": 'setuptools.setup(name="navsim", version="1.1.0")\n',
            "language_id": "python",
        },
        "requirements.txt": {
            "content": "pytorch-lightning==2.2.1\n",
            "language_id": "text",
        },
    }
    files = [
        {"path": key, "size": len(value["content"])} for key, value in contents.items()
    ]
    files.append({"path": "navsim/agents/rap_dino/rap_agent.py"})
    return {
        "is_remote": True,
        "root_uri": f"vscode-remote://ssh-remote+141s{REMOTE_ROOT}",
        "files": files,
        "contents": contents,
        "source": "fixture",
    }


def _pull_rap_snapshot() -> dict[str, Any]:
    if SNAPSHOT_CACHE.is_file():
        payload = json.loads(SNAPSHOT_CACHE.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("files"):
            payload["source"] = "ssh-cache"
            return payload
    return _fixture_snapshot()


def _first_look_from_session(payload: dict[str, Any]) -> dict[str, Any]:
    memory = payload.get("memory") or {}
    understanding = memory.get("workspaceUnderstanding") or memory.get("workspace_understanding") or {}
    first_look = understanding.get("firstLookSummary") or understanding.get("first_look_summary") or {}
    return first_look if isinstance(first_look, dict) else {}


def _client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer 141s RAP",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "sidecar-data",
        database_name="trainer-141s.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_remote_rap_session_start_without_snapshot_is_not_empty_new_project(tmp_path: Path) -> None:
    if SNAPSHOT_CACHE.is_file():
        assert _pull_rap_snapshot()["source"] == "ssh-cache"
    else:
        assert _pull_rap_snapshot()["source"] == "fixture"
    with _client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-141s-rap-no-snapshot",
                "workspace_name": "RAP remote",
                "workspace_path": REMOTE_ROOT,
                "remote_name": "ssh-remote",
                "workspace_trusted": True,
                "force_new": True,
            },
        )
    assert started.status_code == 200, started.text
    first_look = _first_look_from_session(started.json())
    role = first_look.get("folderRole") or first_look.get("folder_role")
    assert role != "empty_new_project"
    assert role == "mixed_uncertain"
    assert Path(REMOTE_ROOT).exists() is False
