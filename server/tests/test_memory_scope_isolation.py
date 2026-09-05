from __future__ import annotations

from pathlib import Path

from app.core.models import EvidenceItem, ResourceRecord, TeachingKnowledgeAsset
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService


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
        EvidenceItem(summary="alpha-only-evidence", concepts=["alpha-only-skill"], outcome="passed"),
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
    assert any(asset.scope == "general" and "reusable pattern" in asset.title.lower() for asset in transferred)


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
    _success_outcome(service, "solo-project", "boundary guard", "Second card in the same project passed.")

    snapshot = service.snapshot("solo-project")
    transfer = snapshot.workspace.get("latest_transfer_state") or {}
    assert service.global_memory().capability_profile == {}
    assert transfer.get("state") == "awaiting_second_scene"
    assert all(item.linked_context != "transfer" for item in snapshot.due_reviews)
    assert "only" in str(transfer.get("why") or "").lower() or "项目" in str(transfer.get("why") or "")


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
    _success_outcome(service, "project-one", "shared rhythm", "First workspace verified the rhythm.")
    _success_outcome(service, "project-two", "shared rhythm", "Second workspace verified the same rhythm.")

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
    _success_outcome(service, "project-b", "boundary guard", "Project B passed after A was deleted.")

    assert service.global_memory().capability_profile == {}
    transfer_b = service.snapshot("project-b").workspace.get("latest_transfer_state") or {}
    assert transfer_b.get("state") == "awaiting_second_scene"
    assert transfer_b.get("state") != "transferable"
    assert all(asset.scope != "general" for asset in service.list_teaching_assets("project-b", limit=16))

    leftover_a = service.snapshot("project-a").workspace.get("latest_transfer_state") or {}
    assert leftover_a.get("state") == "awaiting_second_scene"
    assert leftover_a.get("state") != "transferable"

    service.include_workspaces_in_transfer_promotion(["project-a"])
    _success_outcome(service, "project-b", "boundary guard", "Project B passed after A was restored.")
    assert "boundary guard" in service.global_memory().capability_profile
    restored = service.snapshot("project-b").workspace.get("latest_transfer_state") or {}
    assert restored.get("state") == "transferable"


def test_delete_a_demotes_b_and_restore_a_does_not_inherit_b_transferable(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    _success_outcome(service, "project-a", "boundary guard", "Project A passed once.")
    _success_outcome(service, "project-b", "boundary guard", "Project B passed as the second live scene.")
    assert (service.snapshot("project-b").workspace.get("latest_transfer_state") or {}).get("state") == "transferable"
    assert (service.snapshot("project-a").workspace.get("latest_transfer_state") or {}).get("state") == "transferable"

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

    _success_outcome(service, "project-b", "boundary guard", "Project B passed after A was restored.")
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
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={
            "chat": True,
            "responses": True,
            "vision": False,
            "embeddings": False,
            "tools": False,
            "json_schema": False,
            "streaming": True,
        },
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
            json={"session_id": session_a, "workspace_id": workspace_a, "objectives": ["Ship alpha"]},
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
        runtime = client.app.state.runtime
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
    _success_outcome(service, "project-one", "shared rhythm", "First workspace verified the rhythm.")
    _success_outcome(service, "project-two", "shared rhythm", "Second workspace verified the same rhythm.")

    restarted = MemoryService(TrainerRepository(db_path))
    restored = restarted.snapshot("project-two")
    transfer = restored.workspace.get("latest_transfer_state") or {}
    assert transfer.get("state") == "transferable"
    assert "shared rhythm" in restarted.global_memory().capability_profile
    assert any("transfer" in str(item.linked_context) for item in restored.due_reviews)
