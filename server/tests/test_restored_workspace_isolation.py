"""(e) Workspace isolation: memory, attempts, handoffs and recovery of one workspace never leak into another.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real objects;
nothing here asserts on source text or code shape):
  * server/tests/test_memory_scope_isolation.py
  * server/tests/test_global_memory.py
  * server/tests/test_memory_workspace_alias.py
  * server/tests/test_training_attempt_isolation.py
  * server/tests/test_training_handoff_rebind.py
  * server/tests/test_recovery_review_filter.py
  * server/tests/test_root_scope_recovery.py
  * server/tests/test_runtime_path_recovery.py

Guarantees covered:
  * memory scopes are partitioned per workspace (global vs project);
  * training attempts and handoff rebinding stay workspace-bound;
  * workspace aliases resolve to the same isolated scope;
  * root-scope and runtime-path recovery stay inside their workspace.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.runtime import TrainerRuntime
from app.api.training_card_identity import require_live_selected_card_for_status
from app.core.config import Settings
from app.core.models import (
    ActiveCardSelectionResult,
    CapabilityFlags,
    EvidenceItem,
    ResourceRecord,
    ReviewQueueItem,
    SandboxPreviewRequest,
    TeachingKnowledgeAsset,
    TrainerRoot,
    TrainingCardCandidateSnapshot,
    UserProfile,
    utc_now_iso,
)
from app.core.settings import AppSettings
from app.db.repository import TrainerRepository
from app.main import create_app
from app.memory.models import MemorySnapshot
from app.memory.review_scheduler import ReviewScheduler
from app.memory.service import MemoryService, StructuredMemoryService
from app.planner.service import PlannerService
from app.training.attempt_store import AttemptStore
from app.training.skill_projection import project_skills
from app.workspace.provisioning import ProjectProvisioningService
from app.workspace.root_scope_recovery import recover_legacy_root_registrations
from app.workspace.runtime_path_recovery import recover_runtime_paths

# ---------------------------------------------------------------------------
# Restored from test_memory_scope_isolation.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _runtime(client: TestClient) -> TrainerRuntime:
    """The sidecar runtime behind a test client.

    Starlette declares ``TestClient.app`` as the ``ASGIApp`` callable union, so the
    ``FastAPI`` (and runtime) narrowing has to happen at runtime before ``.state``.
    """
    application = client.app
    assert isinstance(application, FastAPI), "test client must wrap the Trainer FastAPI app"
    runtime = application.state.runtime
    assert isinstance(runtime, TrainerRuntime), "FastAPI app must expose a TrainerRuntime"
    return runtime


def build_memory_service(tmp_path: Path) -> MemoryService:
    return MemoryService(TrainerRepository(tmp_path / "trainer-scope-isolation.db"))


def test_single_project_success_does_not_become_global_mastery(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)

    service.record_learning_outcome(
        workspace_id="minimax-project",
        concepts=["MiniMax tool calling"],
        outcome="tests_passed",
        summary="The MiniMax project test suite passed.",
        verified_result="evaluator confirmed MiniMax project tests.",
        verified_by_evaluator=True,
        focus_area="MiniMax tool calling",
    )

    global_memory = service.global_memory()
    assert global_memory.capability_profile == {}
    assert global_memory.growth_history == []

    other = service.snapshot("unrelated-project")
    assert other.learning_outcomes == []
    assert all("MiniMax" not in asset.title for asset in other.teaching_assets)
    assert all(asset.scope != "general" for asset in other.teaching_assets)


def test_project_facts_do_not_leak_into_other_workspace_surfaces(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    project_a = "project-alpha"
    project_b = "project-beta"

    service.repository.save_resource(
        project_a,
        ResourceRecord(
            id="resource-alpha",
            kind="markdown",
            name="alpha-private-resource",
            source="alpha/private.md",
            summary="alpha-only-resource-summary",
        ),
    )
    service.record_turn_memory(
        workspace_id=project_a,
        session_id="session-alpha",
        scenario="project",
        focus_area="alpha-focus",
        summary="alpha-private-summary",
        next_step="alpha-private-next-step",
        decision="alpha-private-decision",
        evidence=["alpha-private-evidence"],
    )
    service.record_learning_outcome(
        workspace_id=project_a,
        concepts=["alpha-only-skill"],
        outcome="tests_passed",
        summary="alpha-only-success-summary",
        verified_result="alpha-only-verified-result",
        verified_by_evaluator=True,
        focus_area="alpha-only-skill",
    )
    service.enqueue_evidence(
        project_a,
        EvidenceItem(
            summary="alpha-only-evidence", concepts=["alpha-only-skill"], outcome="passed"
        ),
        verified=True,
        verification_source="evaluator",
    )

    snapshot_b = service.snapshot(project_b)
    snapshot_text = " ".join(
        [
            snapshot_b.recent_summary,
            snapshot_b.current_focus,
            " ".join(snapshot_b.reflections),
            " ".join(item.get("summary", "") for item in snapshot_b.learning_outcomes),
            " ".join(asset.title for asset in snapshot_b.teaching_assets),
            " ".join(asset.summary for asset in snapshot_b.teaching_assets),
            " ".join(resource.name for resource in snapshot_b.resources),
        ]
    )
    for private_value in (
        "alpha-private-resource",
        "alpha-private-summary",
        "alpha-private-decision",
        "alpha-private-evidence",
        "alpha-only-skill",
        "alpha-only-success-summary",
        "alpha-only-verified-result",
        "alpha-only-evidence",
    ):
        assert private_value not in snapshot_text

    assert snapshot_b.resources == []
    assert snapshot_b.learning_outcomes == []
    assert service.evidence_queue(project_b).total_count == 0
    assert service.global_memory().capability_profile == {}


def test_general_teaching_asset_requires_second_workspace_verification(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)

    service.record_learning_outcome(
        workspace_id="project-one",
        concepts=["shared rhythm"],
        outcome="tests_passed",
        summary="First workspace verified the rhythm.",
        verified_result="first workspace verified",
        verified_by_evaluator=True,
        focus_area="shared rhythm",
    )
    first_assets = service.list_teaching_assets("project-one", limit=16)
    assert all(asset.scope != "general" for asset in first_assets)
    assert service.global_memory().capability_profile == {}

    service.record_learning_outcome(
        workspace_id="project-two",
        concepts=["shared rhythm"],
        outcome="tests_passed",
        summary="Second workspace verified the same rhythm.",
        verified_result="second workspace verified",
        verified_by_evaluator=True,
        focus_area="shared rhythm",
    )

    global_memory = service.global_memory()
    assert "shared rhythm" in global_memory.capability_profile
    transferred = service.list_teaching_assets("project-one", limit=16)
    assert any(
        asset.scope == "general" and "reusable pattern" in asset.title.lower()
        for asset in transferred
    )


def test_repository_does_not_list_foreign_general_assets(tmp_path: Path) -> None:
    repository = TrainerRepository(tmp_path / "trainer-asset-isolation.db")
    foreign_general = TeachingKnowledgeAsset(
        kind="concept_card",
        scope="general",
        workspace_id="project-foreign",
        title="Foreign general leak",
        summary="Should stay inside the writing project until promoted.",
        concept_card="Should stay inside the writing project until promoted.",
        source_key="general::foreign",
        trust_score=0.8,
    )
    empty_workspace = TeachingKnowledgeAsset(
        kind="concept_card",
        scope="general",
        workspace_id="",
        title="Empty workspace leak",
        summary="Empty workspace ids must not leak.",
        concept_card="Empty workspace ids must not leak.",
        source_key="general::empty",
        trust_score=0.8,
    )
    promoted = TeachingKnowledgeAsset(
        kind="concept_card",
        scope="general",
        workspace_id="__global__",
        title="Promoted transferable concept",
        summary="Multi-scene verified concept.",
        concept_card="Multi-scene verified concept.",
        source_key="general::promoted",
        trust_score=0.8,
    )
    repository.save_teaching_asset("project-foreign", foreign_general)
    repository.save_teaching_asset("project-other", empty_workspace)
    repository.save_teaching_asset("__global__", promoted)

    titles = {asset.title for asset in repository.list_teaching_assets("project-reader")}
    assert "Promoted transferable concept" in titles
    assert "Foreign general leak" not in titles
    assert "Empty workspace leak" not in titles


def _success_outcome(
    service: MemoryService,
    workspace_id: str,
    concept: str,
    summary: str,
    **extra: object,
) -> None:
    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=[concept],
        outcome="tests_passed",
        summary=summary,
        verified_result=summary,
        verified_by_evaluator=True,
        focus_area=concept,
        **extra,
    )


def test_two_cards_in_one_workspace_do_not_promote(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    _success_outcome(service, "solo-project", "boundary guard", "First card passed.")
    _success_outcome(
        service, "solo-project", "boundary guard", "Second card in the same project passed."
    )

    snapshot = service.snapshot("solo-project")
    transfer = snapshot.workspace.get("latest_transfer_state") or {}
    assert service.global_memory().capability_profile == {}
    assert transfer.get("state") == "awaiting_second_scene"
    assert all(item.linked_context != "transfer" for item in snapshot.due_reviews)
    assert "only" in str(transfer.get("why") or "").lower() or "项目" in str(
        transfer.get("why") or ""
    )


def test_transfer_ids_without_evidence_do_not_promote(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    _success_outcome(
        service,
        "project-target",
        "schema guard",
        "Target workspace passed without transfer evidence.",
        transfer_source_workspace_id="project-source",
        transfer_target_workspace_id="project-target",
    )
    assert service.global_memory().capability_profile == {}
    transfer = service.snapshot("project-target").workspace.get("latest_transfer_state") or {}
    assert transfer.get("state") == "awaiting_second_scene"


def test_distinct_evidenced_scenes_in_one_workspace_do_not_promote(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    _success_outcome(service, "same-project", "response model", "First task scene passed.")
    _success_outcome(
        service,
        "same-project",
        "response model",
        "Second distinct task scene passed.",
        transfer_source_context="billing route",
        transfer_target_context="docs sandbox",
        transfer_evidence_summary="Applied the same response model decision in a second task.",
        scenario="cross_project_transfer",
    )
    snapshot = service.snapshot("same-project")
    global_memory = service.global_memory()
    assert global_memory.capability_profile == {}
    transfer = snapshot.workspace.get("latest_transfer_state") or {}
    assert transfer.get("state") == "awaiting_second_scene"
    assert transfer.get("state") != "transferable"
    assert all(item.linked_context != "transfer" for item in snapshot.due_reviews)


def test_project_failure_does_not_negate_global_capability(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    _success_outcome(
        service, "project-one", "shared rhythm", "First workspace verified the rhythm."
    )
    _success_outcome(
        service, "project-two", "shared rhythm", "Second workspace verified the same rhythm."
    )

    before = service.global_memory().capability_profile["shared rhythm"]
    assets_before = [
        asset
        for asset in service.list_teaching_assets("project-one", limit=16)
        if asset.scope == "general"
    ]
    assert assets_before

    service.record_learning_outcome(
        workspace_id="project-one",
        concepts=["shared rhythm"],
        outcome="repeated_error",
        summary="This project failed after the skill was already transferable.",
        verified_result="local regression",
        verified_by_evaluator=True,
        focus_area="shared rhythm",
    )

    after = service.global_memory().capability_profile["shared rhythm"]
    assert after.verified_count == before.verified_count
    assert after.last_outcome == before.last_outcome == "tests_passed"
    assets_after = [
        asset
        for asset in service.list_teaching_assets("project-one", limit=16)
        if asset.scope == "general"
    ]
    assert assets_after
    transfer = service.snapshot("project-one").workspace.get("latest_transfer_state") or {}
    assert transfer.get("state") == "transferable"


def test_deleted_project_scenes_do_not_promote_a_later_project(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    _success_outcome(service, "project-a", "boundary guard", "Project A passed once.")
    assert service.global_memory().capability_profile == {}
    a_before = service.snapshot("project-a").workspace.get("latest_transfer_state") or {}
    assert a_before.get("state") == "awaiting_second_scene"

    service.exclude_workspaces_from_transfer_promotion(["project-a"])
    _success_outcome(
        service, "project-b", "boundary guard", "Project B passed after A was deleted."
    )

    assert service.global_memory().capability_profile == {}
    transfer_b = service.snapshot("project-b").workspace.get("latest_transfer_state") or {}
    assert transfer_b.get("state") == "awaiting_second_scene"
    assert transfer_b.get("state") != "transferable"
    assert all(
        asset.scope != "general" for asset in service.list_teaching_assets("project-b", limit=16)
    )

    leftover_a = service.snapshot("project-a").workspace.get("latest_transfer_state") or {}
    assert leftover_a.get("state") == "awaiting_second_scene"
    assert leftover_a.get("state") != "transferable"

    service.include_workspaces_in_transfer_promotion(["project-a"])
    _success_outcome(
        service, "project-b", "boundary guard", "Project B passed after A was restored."
    )
    assert "boundary guard" in service.global_memory().capability_profile
    restored = service.snapshot("project-b").workspace.get("latest_transfer_state") or {}
    assert restored.get("state") == "transferable"


def test_delete_a_demotes_b_and_restore_a_does_not_inherit_b_transferable(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    _success_outcome(service, "project-a", "boundary guard", "Project A passed once.")
    _success_outcome(
        service, "project-b", "boundary guard", "Project B passed as the second live scene."
    )
    assert (service.snapshot("project-b").workspace.get("latest_transfer_state") or {}).get(
        "state"
    ) == "transferable"
    assert (service.snapshot("project-a").workspace.get("latest_transfer_state") or {}).get(
        "state"
    ) == "transferable"

    service.exclude_workspaces_from_transfer_promotion(["project-a"])
    transfer_b = service.snapshot("project-b").workspace.get("latest_transfer_state") or {}
    assert transfer_b.get("state") != "transferable"
    assert transfer_b.get("state") == "awaiting_second_scene"
    leftover_a = service.snapshot("project-a").workspace.get("latest_transfer_state") or {}
    assert leftover_a.get("state") == "awaiting_second_scene"
    assert leftover_a.get("state") != "transferable"
    assert leftover_a.get("concept") == "boundary guard"

    service.include_workspaces_in_transfer_promotion(["project-a"])
    restored_a = service.snapshot("project-a").workspace.get("latest_transfer_state") or {}
    restored_b = service.snapshot("project-b").workspace.get("latest_transfer_state") or {}
    assert restored_a.get("state") == "awaiting_second_scene"
    assert restored_a.get("state") != "transferable"
    assert restored_b.get("state") == "awaiting_second_scene"
    assert restored_b.get("state") != "transferable"
    assert service.repository.list_transfer_promotion_exclusions() == set()

    _success_outcome(
        service, "project-b", "boundary guard", "Project B passed after A was restored."
    )
    after_b = service.snapshot("project-b").workspace.get("latest_transfer_state") or {}
    after_a = service.snapshot("project-a").workspace.get("latest_transfer_state") or {}
    assert after_b.get("state") == "transferable"
    assert after_a.get("state") == "awaiting_second_scene"
    assert after_a.get("state") != "transferable"
    assert "project-a" in (after_b.get("workspace_ids") or [])
    assert (after_a.get("workspace_ids") or []) == ["project-a"]


def test_http_two_workspace_roots_keep_plan_resources_cards_and_evidence_isolated(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient
    from provider_fixtures import seed_verified_capabilities

    from app.core.models import ProviderConfig
    from app.core.settings import AppSettings
    from app.llm.provider_service import ProviderService
    from app.main import create_app

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "alpha.py").write_text("def alpha() -> str:\n    return 'alpha'\n", encoding="utf-8")
    (root_b / "beta.py").write_text("def beta() -> str:\n    return 'beta'\n", encoding="utf-8")
    app = create_app(
        AppSettings(
            app_name="Trainer Scope Isolation HTTP",
            host="127.0.0.1",
            port=8765,
            data_dir=tmp_path / "data",
            database_name="trainer-scope-http.db",
            default_session_stage="intake",
            summary_message_limit=6,
            enable_network_fetch=False,
        )
    )
    provider = ProviderConfig(
        name="test-openai-compatible",
        baseUrl="http://127.0.0.1:9/v1",
        apiKeyRef="trainer.default",
        model="gpt-4o-mini",
        capabilities=CapabilityFlags(
            chat=True,
            responses=True,
            vision=False,
            embeddings=False,
            tools=False,
            jsonSchema=False,
            streaming=True,
        ),
    )
    runtime = app.state.runtime
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
    runtime.provider_service = ProviderService(
        config=provider,
        api_key="sk-test-not-a-real-key-aaaaaaaa",
    )
    runtime.provider_service_cache.clear()
    seed_verified_capabilities(
        runtime,
        provider,
        "sk-test-not-a-real-key-aaaaaaaa",
        tools=False,
    )
    client = TestClient(app)
    workspace_a = "workspace-root-a"
    workspace_b = "workspace-root-b"
    with client:
        started_a = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_a,
                "workspace_name": "Alpha",
                "workspace_path": str(root_a),
            },
        )
        started_b = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_b,
                "workspace_name": "Beta",
                "workspace_path": str(root_b),
            },
        )
        assert started_a.status_code == 200, started_a.text
        assert started_b.status_code == 200, started_b.text
        session_a = started_a.json()["session_id"]
        plan_a = client.post(
            "/plan/generate",
            json={
                "session_id": session_a,
                "workspace_id": workspace_a,
                "objectives": ["Ship alpha"],
            },
        )
        assert plan_a.status_code == 200, plan_a.text
        plan_id_a = str((plan_a.json().get("plan") or {}).get("id") or "")
        assert plan_id_a
        uploaded = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_a,
                "kind": "markdown",
                "name": "alpha-only.md",
                "source": "inline://alpha-only.md",
                "content": "# Alpha private\nKeep this out of Beta.\n",
                "content_encoding": "utf-8",
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        card_a = client.post(
            "/training/generate-card",
            json={
                "workspace_id": workspace_a,
                "session_id": session_a,
                "source": "conversation_gap",
                "card_type": "practice",
                "focus_area": "alpha-only-skill",
                "target_skill": "alpha-only-skill",
                "context_hint": "Reproduce the alpha-only-skill diagnostic with one breakpoint.",
                "response_language": "en-US",
            },
        )
        assert card_a.status_code == 200, card_a.text
        card_id_a = str((card_a.json().get("card") or {}).get("card_id") or "")
        assert card_id_a
        summary_b = client.get(f"/memory/summary?workspace_id={workspace_b}").json()
        memory_b = summary_b.get("memory") or {}
        plan_b = summary_b.get("plan") or (summary_b.get("snapshot") or {}).get("plan")
        resources_b = memory_b.get("resources") or []
        text_b = " ".join(
            [
                str(plan_b or ""),
                str(resources_b),
                str(memory_b.get("learning_outcomes") or []),
                str(memory_b.get("workspace") or {}),
            ]
        )
        assert plan_b in (None, {})
        assert plan_id_a not in text_b
        assert card_id_a not in text_b
        assert "alpha-only.md" not in text_b
        assert "alpha-only-skill" not in text_b
        assert all(item.get("name") != "alpha-only.md" for item in resources_b)
        runtime = _runtime(client)
        assert runtime.repository.get_latest_plan(workspace_b) is None
        assert runtime.memory_service.get_card(workspace_b, card_id_a) is None
        assert runtime.memory_service.global_memory().capability_profile == {}


def test_exclude_workspace_route_does_not_invent_a_plan(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.core.settings import AppSettings
    from app.main import create_app

    client = TestClient(
        create_app(
            AppSettings(
                app_name="Trainer Transfer Exclusion Test Server",
                host="127.0.0.1",
                port=8765,
                data_dir=tmp_path,
                database_name="trainer-test.db",
                default_session_stage="intake",
                summary_message_limit=6,
            )
        )
    )
    excluded = client.post(
        "/memory/transfer/exclude-workspace",
        json={"workspaceIds": ["project-a"]},
    )
    assert excluded.status_code == 200
    excluded_body = excluded.json()
    assert excluded_body["ok"] is True
    assert "project-a" in excluded_body["workspace_ids"]
    assert "plan" not in excluded_body
    assert "stages" not in excluded_body
    assert "current_task" not in excluded_body

    included = client.post(
        "/memory/transfer/include-workspace",
        json={"workspaceId": "project-a"},
    )
    assert included.status_code == 200
    included_body = included.json()
    assert included_body["ok"] is True
    assert "project-a" in included_body["workspace_ids"]
    assert "plan" not in included_body


def test_transfer_state_survives_sidecar_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-scope-isolation.db"
    service = MemoryService(TrainerRepository(db_path))
    _success_outcome(
        service, "project-one", "shared rhythm", "First workspace verified the rhythm."
    )
    _success_outcome(
        service, "project-two", "shared rhythm", "Second workspace verified the same rhythm."
    )

    restarted = MemoryService(TrainerRepository(db_path))
    restored = restarted.snapshot("project-two")
    transfer = restored.workspace.get("latest_transfer_state") or {}
    assert transfer.get("state") == "transferable"
    assert "shared rhythm" in restarted.global_memory().capability_profile
    assert any("transfer" in str(item.linked_context) for item in restored.due_reviews)


# ---------------------------------------------------------------------------
# Restored from test_global_memory.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def build_memory_service__global_memory(tmp_path: Path) -> MemoryService:
    return MemoryService(TrainerRepository(tmp_path / "trainer-memory.db"))


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Global Memory Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-global-memory.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_global_memory_persists_explicit_preferences_and_goals(tmp_path: Path) -> None:
    service = build_memory_service__global_memory(tmp_path)

    updated = service.update_global_memory(
        preferences={" response_style ": " concise ", "language": "zh-CN"},
        long_term_goals=[
            "Build reliable FastAPI services",
            "Build reliable FastAPI services",
            "Learn testing",
        ],
    )

    restarted = build_memory_service__global_memory(tmp_path).global_memory()

    assert updated.owner_id == "local-trainer"
    assert restarted.preferences == {"response_style": "concise", "language": "zh-CN"}
    assert restarted.long_term_goals == ["Build reliable FastAPI services", "Learn testing"]


def test_global_memory_excludes_workspace_resources_and_decisions(tmp_path: Path) -> None:
    service = build_memory_service__global_memory(tmp_path)
    workspace_a = "project-a"
    workspace_b = "project-b"
    service.repository.save_resource(
        workspace_a,
        ResourceRecord(
            id="resource-a",
            kind="markdown",
            name="project-a-private-resource",
            source="project-a/private.md",
            summary="project-a-only-summary",
        ),
    )
    service.record_turn_memory(
        workspace_id=workspace_a,
        session_id="session-a",
        scenario="project",
        focus_area="project-a-focus",
        summary="project-a-private-summary",
        next_step="project-a-private-next-step",
        decision="project-a-private-decision",
        evidence=["project-a-private-evidence"],
    )
    service.update_global_memory(long_term_goals=["Become a reliable backend engineer"])

    snapshot_a = service.snapshot(workspace_a)
    snapshot_b = service.snapshot(workspace_b)
    assert snapshot_a.global_memory is not None
    assert snapshot_b.global_memory is not None
    assert [resource.id for resource in snapshot_a.resources] == ["resource-a"]
    assert snapshot_b.resources == []
    assert snapshot_a.global_memory == snapshot_b.global_memory

    global_payload = snapshot_a.global_memory.model_dump(by_alias=True, mode="json")
    assert set(global_payload) == {
        "ownerId",
        "preferences",
        "longTermGoals",
        "capabilityProfile",
        "growthHistory",
        "createdAt",
        "updatedAt",
    }
    global_text = json.dumps(global_payload, sort_keys=True)
    for private_value in (
        "project-a-private-resource",
        "project-a-private-summary",
        "project-a-private-decision",
        "project-a-private-evidence",
        "project-a-private-next-step",
    ):
        assert private_value not in global_text


def test_global_memory_only_records_verified_positive_outcomes(tmp_path: Path) -> None:
    service = build_memory_service__global_memory(tmp_path)

    service.record_learning_outcome(
        workspace_id="project-a",
        concepts=["API contracts"],
        outcome="tests_passed",
        verified_result="tests passed",
        verified_by_evaluator=False,
    )
    service.record_learning_outcome(
        workspace_id="project-a",
        concepts=["API contracts"],
        outcome="tests_passed",
        verified_result="",
        verified_by_evaluator=True,
    )
    service.record_learning_outcome(
        workspace_id="project-a",
        concepts=["API contracts"],
        outcome="evaluation",
        verified_result="partial result",
        verified_by_evaluator=True,
    )
    service.record_learning_outcome(
        workspace_id="project-a",
        concepts=["API contracts"],
        outcome="repeated_error",
        verified_result="failed result",
        verified_by_evaluator=True,
    )

    before_verified_result = service.global_memory()
    assert before_verified_result.capability_profile == {}
    assert before_verified_result.growth_history == []

    service.record_learning_outcome(
        workspace_id="project-b",
        concepts=["API contracts", " API contracts "],
        outcome="tests_passed",
        verified_result="The evaluator confirmed the test suite passed.",
        verified_by_evaluator=True,
    )

    after_single_workspace = service.global_memory()
    assert after_single_workspace.capability_profile == {}
    assert after_single_workspace.growth_history == []

    service.record_learning_outcome(
        workspace_id="project-a",
        concepts=["API contracts"],
        outcome="tests_passed",
        verified_result="The evaluator confirmed the same contract in a second workspace.",
        verified_by_evaluator=True,
    )

    global_memory = service.global_memory()
    capability = global_memory.capability_profile["api contracts"]
    assert capability.concept == "API contracts"
    assert capability.verified_count == 1
    assert capability.last_outcome == "tests_passed"
    assert [(record.outcome, record.concepts) for record in global_memory.growth_history] == [
        ("tests_passed", ["API contracts"])
    ]


def test_global_memory_api_uses_camel_case_and_refreshes_snapshot(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={"workspace_id": "project-api", "workspace_name": "Project API"},
        )
        assert start.status_code == 200
        session_id = start.json()["session_id"]

        updated = client.post(
            "/memory/global",
            json={
                "sessionId": session_id,
                "workspaceId": "project-api",
                "preferences": {"responseStyle": "concise"},
                "longTermGoals": ["Master dependable API design"],
            },
        )
        assert updated.status_code == 200
        global_memory = updated.json()["memory"]["globalMemory"]
        assert global_memory["ownerId"] == "local-trainer"
        assert global_memory["preferences"] == {"responseStyle": "concise"}
        assert global_memory["longTermGoals"] == ["Master dependable API design"]

        fetched = client.get("/memory/global")
        assert fetched.status_code == 200
        assert fetched.json()["ownerId"] == "local-trainer"
        assert fetched.json()["longTermGoals"] == ["Master dependable API design"]


# ---------------------------------------------------------------------------
# Restored from test_memory_workspace_alias.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------

LEGACY_PATH = "/Users/learner/project"

CONTEXT_ID = "context-test-1"


def _repository(tmp_path: Path) -> TrainerRepository:
    repository = TrainerRepository(tmp_path / "trainer-memory-alias.db")
    with repository._connect() as connection:
        connection.execute(
            "INSERT INTO workspace_context_aliases (alias, context_id, created_at) VALUES (?, ?, ?)",
            (LEGACY_PATH, CONTEXT_ID, utc_now_iso()),
        )
    return repository


def test_snapshot_reads_context_memory_through_the_legacy_path(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    structured = StructuredMemoryService()
    structured.remember_preference("answer_mode", "hands_on", source="settings")
    repository.save_structured_memory(CONTEXT_ID, structured.export_state())

    service = MemoryService(repository)
    lane = service._structured_for(LEGACY_PATH).snapshot()

    assert [preference.key for preference in lane.preferences] == ["answer_mode"]
    assert lane.preferences[0].value == "hands_on"


def test_persisting_through_the_legacy_path_writes_the_context_row(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    service = MemoryService(repository)
    service._structured_for(LEGACY_PATH).remember_preference(
        "review_cadence", "daily", source="settings"
    )
    service._persist_structured(LEGACY_PATH)

    context_row = repository.load_structured_memory(CONTEXT_ID) or {}
    path_row = repository.load_structured_memory(LEGACY_PATH)
    assert [preference["key"] for preference in context_row.get("preferences", [])] == [
        "review_cadence"
    ]
    assert path_row is None


def test_unaliased_workspace_stays_unchanged(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    service = MemoryService(repository)
    service._structured_for("plain-workspace").remember_preference(
        "answer_mode", "concept_first", source="coach-turn"
    )
    service._persist_structured("plain-workspace")

    row = repository.load_structured_memory("plain-workspace") or {}
    assert [preference["key"] for preference in row.get("preferences", [])] == ["answer_mode"]
    assert repository.load_structured_memory(CONTEXT_ID) is None


"""Structured memory must follow the provisioned project context.

A project can be addressed by its folder path (the visible chat session) or by
its provisioned context id (training/plan writes). Both must share one memory
row; otherwise a due review or mastery written by training never reaches the
Learning surface of the path-based session.
"""

# ---------------------------------------------------------------------------
# Restored from test_training_attempt_isolation.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def make_store(tmp_path: Path) -> AttemptStore:
    return AttemptStore(tmp_path / "attempts.db")


def test_reentering_a_card_resumes_the_same_attempt_id(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = store.start_attempt(workspace_id="ws-1", card_id="card-1", file_hash="h1")
    again = store.start_attempt(workspace_id="ws-1", card_id="card-1", file_hash="h2")

    assert again["attempt_id"] == first["attempt_id"], (
        "re-entering the card must resume the in-flight attempt",
    )
    assert again["file_hash"] == "h2", "refresh keeps the latest binding"

    # The store never duplicates the in-flight attempt.
    rows = []
    connection = store._connect()
    try:
        rows = connection.execute(
            "SELECT attempt_id FROM training_attempts WHERE workspace_id = ? AND card_id = ?",
            ("ws-1", "card-1"),
        ).fetchall()
    finally:
        connection.close()
    assert len(rows) == 1


def test_return_closes_the_lifecycle_then_reenter_starts_fresh(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = store.start_attempt(workspace_id="ws-1", card_id="card-1")
    store.close_attempt(first["attempt_id"], workspace_id="ws-1")

    closed = store.get_attempt(first["attempt_id"])
    assert closed is not None and closed["status"] == "returned"
    assert closed["answer_draft"] is not None or "answer_draft" in closed, (
        "history stays queryable after close",
    )

    second = store.start_attempt(workspace_id="ws-1", card_id="card-1")
    assert second["attempt_id"] != first["attempt_id"]
    assert second["status"] == "active"


def test_workspace_isolation_fails_closed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    attempt = store.start_attempt(workspace_id="ws-1", card_id="card-1")

    # Another workspace cannot read the attempt.
    assert store.get_attempt(attempt["attempt_id"], workspace_id="ws-2") is None
    # ...nor update it.
    assert (
        store.update_attempt(attempt["attempt_id"], workspace_id="ws-2", answer_draft="hijack")
        is None
    )
    untouched = store.get_attempt(attempt["attempt_id"], workspace_id="ws-1")
    assert untouched is not None and untouched["answer_draft"] == ""

    # ...nor re-enter it as its own in-flight attempt.
    assert store.find_active_attempt("ws-2", "card-1") is None


def test_double_evidence_recording_keeps_a_single_current_record(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    attempt = store.start_attempt(workspace_id="ws-1", card_id="card-1", file_hash="hash-A")

    first = store.record_evidence(
        attempt_id=attempt["attempt_id"], artifact_hash="hash-A", result="passed"
    )
    second = store.record_evidence(
        attempt_id=attempt["attempt_id"], artifact_hash="hash-A", result="passed"
    )
    assert first is not None, "the first evidence record must be stored"
    assert second is not None, "the second evidence record must be stored"

    items = store.list_evidence(attempt["attempt_id"])
    assert [item["is_current"] for item in items].count(True) == 1
    assert items[-1]["evidence_id"] == second["evidence_id"]
    assert first["evidence_id"] != second["evidence_id"]
    # The stored record (not the stale return copy) carries the supersession.
    stored_first = store.list_evidence(attempt["attempt_id"])
    stored_first_row = next(
        item for item in stored_first if item["evidence_id"] == first["evidence_id"]
    )
    assert stored_first_row["superseded_by_evidence_id"] == second["evidence_id"]


def test_distinct_attempts_produce_repeat_verified(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = store.start_attempt(workspace_id="ws-1", card_id="card-1", file_hash="hash-A")
    store.record_evidence(attempt_id=first["attempt_id"], artifact_hash="hash-A", result="passed")

    # Verify alone keeps the same attempt through Reflect. An explicit Return
    # retires it before a genuinely new practice cycle can count as repetition.
    store.close_attempt(first["attempt_id"], workspace_id="ws-1")
    second = store.start_attempt(workspace_id="ws-1", card_id="card-1", file_hash="hash-B")
    assert second["attempt_id"] != first["attempt_id"]
    store.record_evidence(attempt_id=second["attempt_id"], artifact_hash="hash-B", result="passed")

    records = []
    for attempt in store.list_attempts(workspace_id="ws-1", card_id="card-1"):
        records.extend(store.list_evidence(attempt["attempt_id"]))

    projection = project_skills(records)
    assert projection["implementation"]["state"] == "repeat_verified"
    assert projection["implementation"]["independent_attempt_count"] == 2


def test_assistance_level_and_draft_survive_workspace_scoped_updates(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    attempt = store.start_attempt(
        workspace_id="ws-1", card_id="card-1", assistance_level="hint_level_1"
    )

    store.update_attempt(
        attempt["attempt_id"],
        workspace_id="ws-1",
        answer_draft="draft v1",
        assistance_level="hint_level_2",
    )
    # A cross-workspace write attempt must not disturb the record.
    assert (
        store.update_attempt_for_workspace(
            attempt["attempt_id"],
            workspace_id="ws-other",
            answer_draft="hijack",
        )
        is None
    )
    loaded = store.get_attempt(attempt["attempt_id"], workspace_id="ws-1")
    assert loaded is not None
    assert loaded["answer_draft"] == "draft v1"
    assert loaded["assistance_level"] == "hint_level_2"


"""Phase-D slice 2 regression tests (design §5/§6, acceptance #18):

- Re-entering a card resumes the in-flight attempt (same attemptId) — the
  "refresh recovers the same attemptId" contract.
- Workspace isolation: attempts from another workspace can neither be read
  nor written.
- Recording evidence twice never yields two current records; the new record
  supersedes the old one.
- Return closes the attempt lifecycle; a later re-enter creates a fresh one.
- Evidence identity derives from the stored attempt, never from client fields.
"""

# ---------------------------------------------------------------------------
# Restored from test_training_handoff_rebind.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _practice_card(card_id: str, title: str) -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type="practice",
        title=title,
        target_skill=title,
        validation_method="Run the focused parser test.",
        status="active",
    )


def _select_card(
    service: MemoryService, workspace_id: str, card: TrainingCardCandidateSnapshot
) -> None:
    service.persist_active_card_selection(
        workspace_id,
        ActiveCardSelectionResult(
            selected_card=card,
            selected_card_id=card.card_id,
            why_this_card=f"{card.card_id} is the next card.",
            next_after_completion="Return to coach.",
            fallback_action="Ask the coach for the next card.",
            candidate_count=1,
            eligible_count=1,
        ),
    )


def _verify_card(service: MemoryService, workspace_id: str, card_id: str) -> dict:
    return service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card_id,
        passed=True,
        summary="pytest tests/test_parser.py -k boundary: 1 passed",
        next_step="Record the reflection.",
        focus_area="parser boundary",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )


def test_rebind_lets_first_card_finish_after_second_card_steals_handoff(tmp_path: Path) -> None:
    workspace_id = "ws-handoff-rebind"
    service = MemoryService(TrainerRepository(tmp_path / "rebind.db"))

    card_a = service.upsert_card(workspace_id, _practice_card("card-rebind-a", "Parser guard"))
    card_b = service.upsert_card(workspace_id, _practice_card("card-rebind-b", "Retry backoff"))

    # Card A verifies first: the current training handoff belongs to A.
    _select_card(service, workspace_id, card_a)
    first = _verify_card(service, workspace_id, card_a.card_id)
    first_handoff_id = first["latest_training_handoff"]["handoff_id"]
    assert first["latest_training_handoff"]["card_id"] == card_a.card_id

    # Minting/selecting card B demotes A and verification moves the handoff to B.
    _select_card(service, workspace_id, card_b)
    second = _verify_card(service, workspace_id, card_b.card_id)
    assert second["latest_training_handoff"]["card_id"] == card_b.card_id

    # Deadlock: card A can neither reflect nor pass the live-card guard.
    with pytest.raises(ValueError, match="different card"):
        service.record_training_handoff_reflection(
            workspace_id=workspace_id,
            card_id=card_a.card_id,
            reflection="The failing boundary case is why the guard runs first.",
            handoff_id=first_handoff_id,
        )
    runtime = SimpleNamespace(memory_service=service)
    with pytest.raises(HTTPException) as blocked:
        require_live_selected_card_for_status(runtime, workspace_id, card_a.card_id)
    assert blocked.value.status_code == 409

    # Rebind hands the current handoff back to card A and restores its live stamps.
    rebound = service.rebind_training_handoff(workspace_id, card_a.card_id)
    handoff = rebound["handoff"]
    assert handoff["card_id"] == card_a.card_id
    assert handoff["handoff_id"].startswith(f"handoff-{card_a.card_id}-")
    assert handoff["handoff_id"] != second["latest_training_handoff"]["handoff_id"]
    assert rebound["card"]["card_id"] == card_a.card_id
    workspace_state = service.snapshot(workspace_id).workspace
    assert str(workspace_state.get("selected_card_id") or "") == card_a.card_id
    assert service.live_selected_training_card_id(workspace_id) == card_a.card_id

    # The leftover guard no longer blocks activation of the handoff owner.
    require_live_selected_card_for_status(runtime, workspace_id, card_a.card_id)
    activated = service.transition_card_status(
        workspace_id, card_a.card_id, "active", reason="Rebound handoff owner."
    )
    assert activated.card.status == "active"

    # The rebound handoff stayed verify+verified, so card A can reflect and return.
    reflected = service.record_training_handoff_reflection(
        workspace_id=workspace_id,
        card_id=card_a.card_id,
        reflection="The failing boundary case is why the guard runs first.",
        handoff_id=handoff["handoff_id"],
    )
    assert reflected["latest_training_handoff"]["card_id"] == card_a.card_id
    assert reflected["latest_training_handoff"]["learning_phase"] == "reflect"

    returned = service.return_training_handoff(
        workspace_id=workspace_id,
        card_id=card_a.card_id,
        handoff_id=reflected["latest_training_handoff"]["handoff_id"],
    )
    assert returned["latest_training_handoff"]["learning_phase"] == "return"
    assert returned["latest_training_handoff"]["status"] == "completed"


def test_rebind_never_transfers_another_cards_trusted_evidence(tmp_path: Path) -> None:
    workspace_id = "ws-rebind-no-transfer"
    service = MemoryService(TrainerRepository(tmp_path / "rebind-transfer.db"))
    card_a = service.upsert_card(workspace_id, _practice_card("card-transfer-a", "Boundary A"))
    card_b = service.upsert_card(workspace_id, _practice_card("card-transfer-b", "Retry B"))

    _select_card(service, workspace_id, card_a)
    _verify_card(service, workspace_id, card_a.card_id)
    _select_card(service, workspace_id, card_b)
    _verify_card(service, workspace_id, card_b.card_id)

    rebound = service.rebind_training_handoff(workspace_id, card_a.card_id)
    handoff = rebound["handoff"]
    assert handoff["card_id"] == card_a.card_id
    assert "Retry B" not in str(handoff.get("evidence", []))
    assert all(record.get("card_id") == card_a.card_id for record in handoff.get("evidence", []))

    reflected = service.record_training_handoff_reflection(
        workspace_id=workspace_id,
        card_id=card_a.card_id,
        reflection="A's own verification remains the only evidence.",
        handoff_id=handoff["handoff_id"],
    )
    returned = service.return_training_handoff(
        workspace_id=workspace_id,
        card_id=card_a.card_id,
        handoff_id=reflected["latest_training_handoff"]["handoff_id"],
    )
    summary = returned["latest_training_handoff"].get("return_summary", "")
    assert "Retry B" not in summary


def test_rebind_without_own_cached_handoff_mints_fresh_unverified(tmp_path: Path) -> None:
    workspace_id = "ws-rebind-fresh-unverified"
    service = MemoryService(TrainerRepository(tmp_path / "rebind-unverified.db"))
    card_a = service.upsert_card(workspace_id, _practice_card("card-unverified-a", "A"))
    card_b = service.upsert_card(workspace_id, _practice_card("card-unverified-b", "B"))

    # A never verified; B is the live verified handoff.
    _select_card(service, workspace_id, card_a)
    _select_card(service, workspace_id, card_b)
    _verify_card(service, workspace_id, card_b.card_id)

    rebound = service.rebind_training_handoff(workspace_id, card_a.card_id)
    handoff = rebound["handoff"]
    assert handoff["card_id"] == card_a.card_id
    assert handoff["learning_phase"] == "learn"
    assert handoff["verification_state"] != "verified"
    assert not handoff.get("evidence")


def test_rebind_mints_fresh_handoff_when_none_exists(tmp_path: Path) -> None:
    workspace_id = "ws-handoff-rebind-fresh"
    service = MemoryService(TrainerRepository(tmp_path / "rebind-fresh.db"))
    card = service.upsert_card(workspace_id, _practice_card("card-rebind-fresh", "Fresh card"))

    rebound = service.rebind_training_handoff(workspace_id, card.card_id)

    handoff = rebound["handoff"]
    assert handoff["card_id"] == card.card_id
    assert handoff["handoff_id"].startswith(f"handoff-{card.card_id}-")
    assert handoff["learning_phase"] == "learn"
    assert rebound["card"]["card_id"] == card.card_id
    assert service.live_selected_training_card_id(workspace_id) == card.card_id


def test_rebind_refuses_missing_or_finished_cards(tmp_path: Path) -> None:
    workspace_id = "ws-handoff-rebind-refuse"
    service = MemoryService(TrainerRepository(tmp_path / "rebind-refuse.db"))

    with pytest.raises(LookupError, match="Training card not found."):
        service.rebind_training_handoff(workspace_id, "card-missing")

    finished = service.upsert_card(
        workspace_id,
        _practice_card("card-rebind-done", "Finished card").model_copy(
            update={"status": "implemented"}
        ),
    )
    with pytest.raises(ValueError, match="already finished"):
        service.rebind_training_handoff(workspace_id, finished.card_id)


def test_open_handoff_owner_counts_as_live_without_selection(tmp_path: Path) -> None:
    workspace_id = "ws-handoff-owner-live"
    service = MemoryService(TrainerRepository(tmp_path / "owner-live.db"))
    card = service.upsert_card(workspace_id, _practice_card("card-owner-live", "Owner card"))
    _verify_card(service, workspace_id, card.card_id)

    # A later mint cleared the painted selection; the open handoff owner stays live.
    service.update_workspace_state(workspace_id, selected_card_id="")
    assert service.live_selected_training_card_id(workspace_id) == card.card_id


"""L1 regressions: training handoff rebind clears the second-card deadlock."""

# ---------------------------------------------------------------------------
# Restored from test_recovery_review_filter.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _review(
    concept: str,
    task_hint: str,
    *,
    source: Literal["weakness", "mastery", "reflection", "plan"] = "weakness",
) -> ReviewQueueItem:
    return ReviewQueueItem(
        concept=concept,
        reason="review this",
        source=source,
        task_hint=task_hint,
        focus_area="queue_lock.py",
        linked_context="src/queue_lock.py",
    )


def test_provider_recovery_sentence_never_becomes_a_review_card() -> None:
    recovery = _review("queue_lock.py", "请把刚才的问题再发一次。")
    truncated_recovery = _review("queue_lock.py", "请把刚才的问题再发一")
    legitimate = _review("queue_lock.py", "解释 with self._lock 的异常释放路径。")
    service = object.__new__(MemoryService)
    # Duck-typed test double standing in for ReviewScheduler.
    service._review_scheduler = cast(
        ReviewScheduler,
        SimpleNamespace(
            derive_due_reviews=lambda **_: [recovery, truncated_recovery, legitimate]
        ),
    )
    lane = SimpleNamespace(
        workspace={
            "active_thread": {
                "recovery_state": "provider_or_local",
                "focus_area": "queue_lock.py",
                "next_step": "请把刚才的问题再发一次。",
                "blocker": (
                    "The provider returned English-only visible prose while zh-CN is selected."
                ),
            }
        }
    )

    reviews = service._derive_due_reviews(
        plan=None,
        # Duck-typed test double standing in for LaneMemorySnapshot (an import
        # alias of MemorySnapshot in app.memory.coaching_adaptation_mixin).
        lane_snapshot=cast(MemorySnapshot, lane),
        weakness_records=[],
    )

    assert [item.task_hint for item in reviews] == ["解释 with self._lock 的异常释放路径。"]


# ---------------------------------------------------------------------------
# Restored from test_root_scope_recovery.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _provision(repository: TrainerRepository, tmp_path: Path, root_id: str):
    root_path = tmp_path / root_id
    root_path.mkdir()
    project_path = tmp_path / f"project-{root_id}"
    project_path.mkdir()
    repository.register_trainer_root(
        TrainerRoot(
            rootId=root_id,
            rootPath=str(root_path),
            displayName=root_id,
        )
    )
    return ProjectProvisioningService(
        repository=repository,
        memory_service=MemoryService(repository),
        planner_service=PlannerService(repository=repository),
    ).provision(
        project_path=str(project_path),
        project_name="Python practice",
        workspace_id=str(project_path),
        root_id=root_id,
        root_path=str(root_path),
    )


def test_root_recovery_preserves_current_learning_data_and_is_readonly_and_idempotent(tmp_path):
    legacy = TrainerRepository(tmp_path / "sidecar" / "trainer.sqlite3")
    project = _provision(legacy, tmp_path, "root-one")
    other = _provision(legacy, tmp_path, "root-two")
    before = hashlib.sha256(legacy.database_path.read_bytes()).hexdigest()
    current = TrainerRepository(tmp_path / "sidecar" / "roots" / "root-one" / "trainer.sqlite3")
    profile = UserProfile(long_term_goal="My updated goal")
    current.save_profile(project.context_id, profile)
    current.save_structured_memory(
        project.context_id,
        {
            "workspace": {"response_language": "zh-CN", "latest_conversation": "New conversation"},
            "active_thread": {"summary": "Current work"},
        },
    )
    current.save_session(
        "new-session",
        project.context_id,
        {
            "session_id": "new-session",
            "workspace_id": project.context_id,
            "snapshot": {"messages": [{"id": "new-message", "content": "Keep this question"}]},
        },
    )

    assert recover_legacy_root_registrations(current) == 1
    recovered_provisioning = current.get_project_provisioning(project.context_id)
    assert recovered_provisioning is not None, "the recovered project must be registered"
    assert recovered_provisioning.project_id == project.project_id
    assert current.get_project_provisioning(other.context_id) is None
    recovered_profile = current.get_profile(project.context_id)
    assert recovered_profile is not None, "the recovered project must keep its profile"
    assert recovered_profile.long_term_goal == "My updated goal"
    memory = current.load_structured_memory(project.context_id)
    assert memory is not None, "the recovered project must keep its structured memory"
    assert memory["workspace"]["latest_conversation"] == "New conversation"
    assert memory["workspace"]["response_language"] == "zh-CN"
    assert memory["workspace"]["project_memory"]["id"] == project.project_memory_id
    assert memory["active_thread"]["summary"] == "Current work"
    new_session = current.load_session("new-session")
    assert new_session is not None, "the recovered project must keep its new session"
    assert new_session["snapshot"]["messages"][0]["id"] == "new-message"
    assert current.load_session(project.agent_session_id) is not None
    service = ProjectProvisioningService(
        repository=current,
        memory_service=MemoryService(current),
        planner_service=PlannerService(repository=current),
    )
    recovered = service.get(project.context_id)
    assert recovered is not None, "the recovered project must still resolve"
    assert recovered.context_id == project.context_id
    assert recover_legacy_root_registrations(current) == 0
    assert hashlib.sha256(legacy.database_path.read_bytes()).hexdigest() == before


def test_custom_data_directories_do_not_import_unrelated_legacy_registrations(tmp_path):
    legacy = TrainerRepository(tmp_path / "sidecar" / "trainer.sqlite3")
    project = _provision(legacy, tmp_path, "root-one")
    current = TrainerRepository(tmp_path / "custom" / "trainer.sqlite3")
    assert recover_legacy_root_registrations(current) == 0
    assert current.get_project_context(project.context_id) is None


@pytest.mark.parametrize("conflict", ["root_path", "context_id", "root_id", "project_id"])
def test_recovery_does_not_replace_conflicting_scoped_identity(tmp_path, conflict):
    legacy = TrainerRepository(tmp_path / "sidecar" / "trainer.sqlite3")
    project = _provision(legacy, tmp_path, "root-one")
    current = TrainerRepository(tmp_path / "sidecar" / "roots" / "root-one" / "trainer.sqlite3")
    if conflict == "root_path":
        current.register_trainer_root(
            TrainerRoot(
                rootId="root-one",
                rootPath=str(tmp_path / "another-root"),
                displayName="Another root",
            )
        )
    else:
        current.save_structured_memory(project.context_id, {"workspace": {conflict: "another-id"}})
    current.save_profile(project.context_id, UserProfile(long_term_goal="Keep my current goal"))
    before_memory = current.load_structured_memory(project.context_id)
    assert recover_legacy_root_registrations(current) == 0
    assert current.get_project_context(project.context_id) is None
    assert current.load_structured_memory(project.context_id) == before_memory
    kept_profile = current.get_profile(project.context_id)
    assert kept_profile is not None, "the conflicting identity must keep its profile"
    assert kept_profile.long_term_goal == "Keep my current goal"


def test_incomplete_legacy_registration_does_not_admit_a_project(tmp_path):
    legacy = TrainerRepository(tmp_path / "sidecar" / "trainer.sqlite3")
    project = _provision(legacy, tmp_path, "root-one")
    with legacy._connect() as connection:
        connection.execute("DELETE FROM sessions WHERE session_id = ?", (project.agent_session_id,))
    current = TrainerRepository(tmp_path / "sidecar" / "roots" / "root-one" / "trainer.sqlite3")
    assert recover_legacy_root_registrations(current) == 0
    assert current.get_trainer_root("root-one") is not None
    assert current.get_project_context(project.context_id) is None
    assert current.get_profile(project.context_id) is None


# ---------------------------------------------------------------------------
# Restored from test_runtime_path_recovery.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _snapshot(tmp_path: Path, *, marker: bool = False, old_root: str | None = None):
    source = tmp_path / "original data"
    repository = TrainerRepository(source / "trainer.sqlite3")
    relative = Path("sandboxes/context-one/sources/inbox/resource-one/lesson.md")
    file = source / relative
    file.parent.mkdir(parents=True)
    content = "# 元组\n\n内部列表可变。\n"
    file.write_text(content, encoding="utf-8")
    # On Windows str(file) joins with backslashes, so the stored sandbox root
    # must be composed from the stored prefix instead of split off the native
    # path string (rsplit("/sources/") never matches a backslash path).
    base = old_root if old_root is not None else str(source)
    original = str(file) if old_root is None else base + "/" + relative.as_posix()
    external = str(tmp_path / "external-original.md")
    resource = ResourceRecord(
        id="resource-one",
        name="lesson.md",
        kind="markdown",
        source=external,
        canonical_source=external,
        sandbox_path=original,
        content_hash=hashlib.sha256(file.read_bytes()).hexdigest(),
    )
    repository.save_resource("context-one", resource)
    repository.save_structured_memory(
        "context-one",
        {
            "workspace": {"sandbox_root_override": base + "/sandboxes/context-one"},
            "active_thread": {"summary": "Read " + original},
        },
    )
    repository.save_session(
        "session-one",
        "context-one",
        {
            "session_id": "session-one",
            "workspace_id": "context-one",
            "snapshot": {
                "resources": [resource.model_dump()],
                "messages": [
                    {"content": original, "metadata": {"path": original}},
                ],
            },
        },
    )
    if marker:
        (source / "runtime-location.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "dataRoot": old_root or str(source),
                }
            ),
            encoding="utf-8",
        )
    target = tmp_path / "restored" / ".trainer" / "runtime"
    shutil.copytree(source, target)
    # Recovery cannot fall back to the source, even when it no longer exists.
    before = hashlib.sha256((source / "trainer.sqlite3").read_bytes()).hexdigest()
    return source, target, relative, original, external, before


@pytest.mark.parametrize("marker", [False, True])
@pytest.mark.parametrize("old_root", [None, "C:/Users/Learner/AppData/Trainer"])
def test_moved_snapshot_rebases_owned_paths_without_changing_sources_or_history(
    tmp_path, marker, old_root
):
    source, target, relative, old, external, before = _snapshot(
        tmp_path, marker=marker, old_root=old_root
    )
    database = target / "trainer.sqlite3"
    assert recover_runtime_paths(database, target) >= 3
    restored = TrainerRepository(database)
    resource = restored.get_resource("context-one", "resource-one")
    assert resource is not None, "the restored resource record must resolve"
    assert resource.sandbox_path == str(target / relative)
    assert resource.source == resource.canonical_source == external
    assert resource.content_hash == hashlib.sha256((target / relative).read_bytes()).hexdigest()
    memory = restored.load_structured_memory("context-one")
    assert memory is not None, "the restored structured memory must load"
    assert memory["workspace"]["sandbox_root_override"] == str(target / "sandboxes/context-one")
    assert memory["active_thread"]["summary"] == "Read " + old
    session = restored.load_session("session-one")
    assert session is not None, "the restored session must load"
    assert session["snapshot"]["messages"][0]["content"] == old
    assert session["snapshot"]["messages"][0]["metadata"]["path"] == str(target / relative)
    assert hashlib.sha256((source / "trainer.sqlite3").read_bytes()).hexdigest() == before
    assert recover_runtime_paths(database, target) == 0


@pytest.mark.parametrize("invalid_copy", ["missing", "different", "symlink"])
def test_legacy_recovery_requires_same_hash_copy_inside_current_data_root(tmp_path, invalid_copy):
    _, target, relative, original, _, _ = _snapshot(tmp_path)
    copied = target / relative
    if invalid_copy == "missing":
        copied.unlink()
    elif invalid_copy == "different":
        copied.write_text("Different lesson", encoding="utf-8")
    else:
        copied.unlink()
        outside = tmp_path / "outside.md"
        outside.write_text("# 元组\n\n内部列表可变。\n", encoding="utf-8")
        copied.symlink_to(outside)
    assert recover_runtime_paths(target / "trainer.sqlite3", target) == 0
    untouched = TrainerRepository(target / "trainer.sqlite3").get_resource(
        "context-one", "resource-one"
    )
    assert untouched is not None, "the legacy resource record must still resolve"
    assert untouched.sandbox_path == original


def test_snapshot_startup_recovery_makes_resource_preview_use_restored_copy(tmp_path):
    source, target, relative, _, _, _ = _snapshot(tmp_path)
    shutil.rmtree(source)
    application = create_app(Settings(data_dir=target))
    runtime = application.state.runtime
    resource = runtime.repository.get_resource("context-one", "resource-one")
    assert resource.sandbox_path == str(target / relative)
    assert (
        runtime.sandbox_service.ensure_workspace_root("context-one")
        == target / "sandboxes/context-one"
    )
    preview = runtime.sandbox_service.preview(
        "context-one", SandboxPreviewRequest(workspace_id="context-one", path=resource.sandbox_path)
    )
    assert "内部列表可变" in preview.content
    runtime.resource_service.close()


def test_location_marker_rebases_inline_paths_and_file_uris_but_rejects_traversal(tmp_path):
    _, target, _, _, _, _ = _snapshot(tmp_path, marker=True)
    old = tmp_path / "original data"
    database = target / "trainer.sqlite3"
    repository = TrainerRepository(database)
    repository.save_structured_memory(
        "context-two",
        {
            "workspace": {
                "path": (old / "inline-resources/context-two/reply.md").as_uri(),
                "source": str(old / "../external.md"),
                "content": str(old / "inline-resources/context-two/reply.md"),
            }
        },
    )
    recover_runtime_paths(database, target)
    rebased_memory = repository.load_structured_memory("context-two")
    assert rebased_memory is not None, "the rebased structured memory must load"
    workspace = rebased_memory["workspace"]
    assert workspace["path"] == (target / "inline-resources/context-two/reply.md").as_uri()
    assert workspace["source"] == str(old / "../external.md")
    assert workspace["content"] == str(old / "inline-resources/context-two/reply.md")


def test_recovery_rolls_back_all_references_on_corrupt_json(tmp_path):
    _, target, _, original, _, _ = _snapshot(tmp_path, marker=True)
    database = target / "trainer.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE structured_memory SET payload = '{broken'")
    with pytest.raises(json.JSONDecodeError):
        recover_runtime_paths(database, target)
    rolled_back = TrainerRepository(database).get_resource("context-one", "resource-one")
    assert rolled_back is not None, "the resource record must survive the failed recovery"
    assert rolled_back.sandbox_path == original
