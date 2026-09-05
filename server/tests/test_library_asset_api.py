from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.models import (
    LearningPlan,
    ProjectContext,
    ResourceRecord,
    TrainerProject,
    TrainerRoot,
    UserProfile,
)
from app.core.settings import AppSettings
from app.main import create_app


def _client(data_dir: Path) -> TestClient:
    return TestClient(
        create_app(
            AppSettings(
                app_name="Trainer Asset Library Test",
                host="127.0.0.1",
                port=8765,
                data_dir=data_dir,
                database_name="asset-library.db",
                default_session_stage="intake",
                summary_message_limit=6,
            )
        )
    )


def _seed_context(
    client: TestClient,
    root_path: Path,
    suffix: str,
    *,
    legacy_workspace_id: str | None = None,
) -> ProjectContext:
    root_path.mkdir(parents=True, exist_ok=True)
    project_path = root_path / f"project-{suffix}"
    project_path.mkdir(exist_ok=True)
    context = ProjectContext(
        context_id=f"context-{suffix}",
        root_id=f"root-{suffix}",
        project_id=f"project-{suffix}",
        project_memory_id=f"memory-{suffix}",
        project_plan_id=f"plan-{suffix}",
        project_training_id=f"training-{suffix}",
        project_agent_context_id=f"agent-{suffix}",
        agent_session_id=f"session-{suffix}",
        legacy_workspace_id=legacy_workspace_id or f"legacy-{suffix}",
    )
    provisioning = client.app.state.runtime.repository.create_project_context_bundle(
        root=TrainerRoot(
            root_id=context.root_id,
            root_path=str(root_path),
            display_name=f"Root {suffix}",
        ),
        project=TrainerProject(
            project_id=context.project_id,
            root_id=context.root_id,
            project_path=str(project_path),
            project_name=f"Project {suffix}",
        ),
        context=context,
        profile=UserProfile(),
        plan=LearningPlan(id=context.project_plan_id, title=f"Plan {suffix}"),
        structured_memory={
            "workspace": {
                "workspace_id": context.context_id,
                "context_id": context.context_id,
                "root_id": context.root_id,
                "root_path": str(root_path),
                "project_id": context.project_id,
                "project_path": str(project_path),
                "canonical_project_path": str(project_path),
                "project_name": f"Project {suffix}",
                "project_memory": {"id": context.project_memory_id},
                "project_training_state": {"id": context.project_training_id},
                "project_agent_context": {"id": context.project_agent_context_id},
                "project_provisioning": context.model_dump(mode="json", by_alias=True),
            }
        },
        session_payload={
            "session_id": context.agent_session_id,
            "workspace_id": context.context_id,
            "workspace_name": f"Project {suffix}",
            "snapshot": {},
        },
    )
    client.app.state.runtime.memory_service.update_workspace_state(
        context.context_id,
        context_id=context.context_id,
        root_id=context.root_id,
        root_path=str(root_path),
        project_id=context.project_id,
        project_path=str(project_path),
        canonical_project_path=str(project_path),
        project_name=f"Project {suffix}",
        project_memory={"id": context.project_memory_id},
        project_training_state={"id": context.project_training_id},
        project_agent_context={"id": context.project_agent_context_id},
        project_provisioning=provisioning.model_dump(mode="json", by_alias=True),
    )
    return context


def _start_session(client: TestClient, context: ProjectContext) -> str:
    response = client.post(
        "/session/start",
        json={"workspace_id": context.context_id, "workspace_name": f"Project {context.project_id}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _catalog_asset_ids(client: TestClient, session_id: str, group: str) -> list[str]:
    state = client.app.state.runtime.get_session(session_id)
    assert state is not None
    return [entry.asset.id for entry in getattr(state.snapshot.memory.asset_catalog, group)]


def test_memory_snapshot_uses_an_empty_asset_catalog_for_unmanaged_workspace(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/memory/summary", params={"workspace_id": "workspace-default"})

        assert response.status_code == 200, response.text
        catalog = response.json()["memory"]["assetCatalog"]
        assert catalog == {"contextId": "", "revision": "", "active": [], "deleted": []}


def test_session_snapshot_uses_canonical_context_for_legacy_workspace_alias(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        context = _seed_context(client, tmp_path / "root", "alias")
        response = client.post(
            "/session/start",
            json={
                "workspace_id": context.legacy_workspace_id,
                "workspace_name": "Legacy workspace",
            },
        )

        assert response.status_code == 200, response.text
        snapshot = response.json()
        assert snapshot["contextId"] == context.context_id
        assert snapshot["memory"]["assetCatalog"]["contextId"] == context.context_id

        summary = client.get(
            "/memory/summary",
            params={"workspace_id": context.legacy_workspace_id},
        )
        assert summary.status_code == 200, summary.text
        assert summary.json()["contextId"] == context.context_id
        assert summary.json()["memory"]["assetCatalog"]["contextId"] == context.context_id


def test_legacy_workspace_alias_keeps_learning_and_dependency_maps_in_its_context(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        context = _seed_context(client, tmp_path / "root", "learning")
        started = client.post(
            "/session/start",
            json={
                "workspace_id": context.legacy_workspace_id,
                "workspace_name": "Legacy learning workspace",
                "profile": {"preferred_libraries": ["FastAPI"]},
            },
        )

        assert started.status_code == 200, started.text
        assert started.json()["contextId"] == context.context_id
        profile = client.app.state.runtime.repository.get_profile(context.context_id)
        assert profile is not None
        assert profile.preferred_libraries == ["FastAPI"]
        assert client.app.state.runtime.repository.get_profile(context.legacy_workspace_id) is None

        signal = client.post(
            "/learning/signal",
            json={
                "workspace_id": context.legacy_workspace_id,
                "concepts": ["FastAPI"],
                "outcome": "concept_answered_correctly",
                "summary": "Explained dependency injection at a route boundary.",
            },
        )

        assert signal.status_code == 200, signal.text
        mastery = signal.json()["memory"]["dependency_mastery"]
        assert [item["dependency_key"] for item in mastery] == ["fastapi"]
        prior_fastapi = next(item for item in mastery if item["dependency_key"] == "fastapi")

        action = client.post(
            "/training/dependency-skill-map/action",
            json={
                "workspace_id": context.legacy_workspace_id,
                "dependency_key": "fastapi",
                "action": "mark_practiced",
            },
        )

        assert action.status_code == 409, action.text
        assert "Verify current file" in action.json()["detail"]

        summary = client.get(
            "/memory/summary",
            params={"workspace_id": context.legacy_workspace_id},
        )
        assert summary.status_code == 200, summary.text
        assert summary.json()["contextId"] == context.context_id
        persisted_fastapi = next(
            item
            for item in summary.json()["memory"]["dependency_mastery"]
            if item["dependency_key"] == "fastapi"
        )
        assert persisted_fastapi["mastery_stage"] == prior_fastapi["mastery_stage"]
        assert persisted_fastapi["mastery_stage_progress"] == prior_fastapi["mastery_stage_progress"]
        assert client.app.state.runtime.repository.get_profile(context.legacy_workspace_id) is None


def test_windows_workspace_alias_case_keeps_learning_and_dependency_maps_in_its_context(
    tmp_path: Path,
) -> None:
    canonical_alias = r"C:\Trainer\WindowsAlias"
    alias_with_different_case = r"c:\trainer\windowsalias"

    with _client(tmp_path) as client:
        context = _seed_context(
            client,
            tmp_path / "root",
            "windows-alias",
            legacy_workspace_id=canonical_alias,
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": alias_with_different_case,
                "workspace_name": "Windows alias workspace",
                "profile": {"preferred_libraries": ["FastAPI"]},
            },
        )

        assert started.status_code == 200, started.text
        assert started.json()["contextId"] == context.context_id
        assert client.app.state.runtime.repository.resolve_context_id(canonical_alias) == context.context_id
        assert (
            client.app.state.runtime.repository.resolve_context_id(alias_with_different_case)
            == context.context_id
        )

        signal = client.post(
            "/learning/signal",
            json={
                "workspace_id": canonical_alias,
                "concepts": ["FastAPI"],
                "outcome": "concept_answered_correctly",
                "summary": "Explained dependency injection across a Windows path alias.",
            },
        )
        assert signal.status_code == 200, signal.text
        prior_fastapi = next(
            item
            for item in signal.json()["memory"]["dependency_mastery"]
            if item["dependency_key"] == "fastapi"
        )

        action = client.post(
            "/training/dependency-skill-map/action",
            json={
                "workspace_id": alias_with_different_case,
                "dependency_key": "fastapi",
                "action": "mark_practiced",
            },
        )
        assert action.status_code == 409, action.text
        assert "Verify current file" in action.json()["detail"]

        summary = client.get(
            "/memory/summary",
            params={"workspace_id": alias_with_different_case},
        )
        assert summary.status_code == 200, summary.text
        assert summary.json()["contextId"] == context.context_id
        persisted_fastapi = next(
            item
            for item in summary.json()["memory"]["dependency_mastery"]
            if item["dependency_key"] == "fastapi"
        )
        assert persisted_fastapi["mastery_stage"] == prior_fastapi["mastery_stage"]
        assert persisted_fastapi["mastery_stage_progress"] == prior_fastapi["mastery_stage_progress"]
        assert client.app.state.runtime.repository.resolve_context_id(alias_with_different_case) == context.context_id


def test_windows_workspace_alias_case_cannot_create_a_second_context(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _seed_context(
            client,
            tmp_path / "root-a",
            "windows-first",
            legacy_workspace_id=r"C:\Trainer\SharedAlias",
        )

        with pytest.raises(ValueError, match="legacy workspace alias already belongs"):
            _seed_context(
                client,
                tmp_path / "root-b",
                "windows-second",
                legacy_workspace_id=r"c:\trainer\sharedalias",
            )


@pytest.mark.parametrize(
    "asset_type",
    ["knowledge", "project", "skill", "agent", "asset", "memory", "runtime_artifact"],
)
def test_asset_api_persists_each_canonical_type(tmp_path: Path, asset_type: str) -> None:
    with _client(tmp_path) as client:
        context = _seed_context(client, tmp_path / "root", "types")
        response = client.post(
            "/assets",
            json={
                "assetType": asset_type,
                "scope": "project",
                "title": f"{asset_type} asset",
                "canonicalSource": f"manual:{asset_type}",
                "contextId": context.context_id,
                "approved": True,
            },
        )

        assert response.status_code == 200, response.text
        asset = response.json()["asset"]
        assert asset["assetType"] == asset_type
        assert asset["contextId"] == context.context_id
        assert asset["projectId"] == context.project_id
        assert asset["status"] == "active"
        assert asset["sourceChain"] == [
            {
                "kind": "manual",
                "ref": f"manual:{asset_type}",
                "label": "canonical source",
                "metadata": {},
            }
        ]
        if asset_type == "agent":
            assert asset["capabilities"]["agent_execution"] == "unsupported"
        if asset_type == "runtime_artifact":
            assert asset["capabilities"]["runtime_execution"] == "unsupported"


def test_asset_api_isolates_project_assets_and_requires_approval_for_cross_project_links(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        first = _seed_context(client, tmp_path / "root-a", "a")
        second = _seed_context(client, tmp_path / "root-b", "b")
        created = client.post(
            "/assets",
            json={
                "assetType": "knowledge",
                "scope": "project",
                "title": "Scoped reference",
                "contextId": first.context_id,
                "sourceChain": [{"kind": "manual", "ref": "note:scoped"}],
            },
        )
        assert created.status_code == 200, created.text
        asset_id = created.json()["asset"]["id"]

        isolated = client.get("/assets", params={"context_id": second.context_id})
        assert isolated.status_code == 200
        assert isolated.json()["items"] == []

        denied = client.post(
            f"/assets/{asset_id}/links",
            json={"contextId": second.context_id, "relation": "available_to"},
        )
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "approval_required"

        linked = client.post(
            f"/assets/{asset_id}/links",
            json={
                "contextId": second.context_id,
                "relation": "available_to",
                "approved": True,
                "sourceRef": "share:manual",
            },
        )
        assert linked.status_code == 200, linked.text
        assert linked.json()["link"]["contextId"] == second.context_id
        assert linked.json()["link"]["projectId"] == second.project_id

        shared = client.get("/assets", params={"context_id": second.context_id, "query": "scoped"})
        assert shared.status_code == 200
        assert [item["id"] for item in shared.json()["items"]] == [asset_id]


def test_asset_api_fails_closed_for_unknown_project_context(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        denied = client.post(
            "/assets",
            json={
                "assetType": "knowledge",
                "scope": "project",
                "title": "Unowned asset",
                "contextId": "context-missing",
            },
        )

        assert denied.status_code == 404
        assert denied.json()["detail"] == "Unknown project context."


def test_asset_api_keeps_source_resources_intact_through_archive_restore_and_restart(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        context = _seed_context(client, tmp_path / "root", "lifecycle")
        resource = ResourceRecord(
            id="resource-source",
            kind="text",
            name="Source note",
            source="memory://source-note",
        )
        repository = client.app.state.runtime.repository
        repository.save_resource(context.context_id, resource)
        created = client.post(
            "/assets",
            json={
                "assetType": "knowledge",
                "scope": "project",
                "title": "Source-backed asset",
                "contextId": context.context_id,
                "sourceChain": [{"kind": "resource", "ref": resource.id}],
            },
        )
        assert created.status_code == 200, created.text
        asset_id = created.json()["asset"]["id"]
        assert created.json()["asset"]["sourceState"] == [
            {"kind": "resource", "ref": resource.id, "state": "available"}
        ]

        denied = client.post(f"/assets/{asset_id}/archive", json={"reason": "outdated"})
        assert denied.status_code == 409
        archived = client.post(
            f"/assets/{asset_id}/archive",
            json={"approved": True, "reason": "outdated"},
        )
        assert archived.status_code == 200, archived.text
        assert archived.json()["asset"]["status"] == "deleted"
        assert archived.json()["asset"]["sourceState"] == [
            {"kind": "resource", "ref": resource.id, "state": "available"}
        ]
        assert repository.get_resource(context.context_id, resource.id) is not None
        hidden = client.get("/assets", params={"context_id": context.context_id})
        assert hidden.status_code == 200
        assert hidden.json()["items"] == []
        deleted = client.get(
            "/assets",
            params={"context_id": context.context_id, "include_deleted": "true"},
        )
        assert [item["id"] for item in deleted.json()["items"]] == [asset_id]

    with _client(tmp_path) as restarted:
        restored = restarted.post(f"/assets/{asset_id}/restore", json={"approved": True})
        assert restored.status_code == 200, restored.text
        assert restored.json()["asset"]["status"] == "active"
        visible = restarted.get("/assets", params={"context_id": context.context_id})
        assert visible.status_code == 200
        assert [item["id"] for item in visible.json()["items"]] == [asset_id]


def test_asset_catalog_refreshes_open_sessions_for_isolation_sharing_and_lifecycle(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = _seed_context(client, tmp_path / "root-a", "catalog-a")
        second = _seed_context(client, tmp_path / "root-b", "catalog-b")
        first_session_id = _start_session(client, first)
        second_session_id = _start_session(client, second)
        assert _catalog_asset_ids(client, first_session_id, "active") == []
        assert _catalog_asset_ids(client, second_session_id, "active") == []

        library = client.post(
            "/assets",
            json={"assetType": "knowledge", "scope": "library", "title": "Reusable note"},
        )
        assert library.status_code == 200, library.text
        library_asset_id = library.json()["asset"]["id"]
        assert library_asset_id in _catalog_asset_ids(client, first_session_id, "active")
        assert library_asset_id in _catalog_asset_ids(client, second_session_id, "active")

        created = client.post(
            "/assets",
            json={
                "assetType": "knowledge",
                "scope": "project",
                "title": "Project-only note",
                "contextId": first.context_id,
            },
        )
        assert created.status_code == 200, created.text
        asset_id = created.json()["asset"]["id"]
        assert asset_id in _catalog_asset_ids(client, first_session_id, "active")
        assert asset_id not in _catalog_asset_ids(client, second_session_id, "active")

        linked = client.post(
            f"/assets/{asset_id}/links",
            json={"contextId": second.context_id, "approved": True},
        )
        assert linked.status_code == 200, linked.text
        assert asset_id in _catalog_asset_ids(client, second_session_id, "active")

        archived = client.post(f"/assets/{asset_id}/archive", json={"approved": True})
        assert archived.status_code == 200, archived.text
        assert asset_id not in _catalog_asset_ids(client, first_session_id, "active")
        assert asset_id not in _catalog_asset_ids(client, second_session_id, "active")
        assert asset_id in _catalog_asset_ids(client, first_session_id, "deleted")
        assert asset_id in _catalog_asset_ids(client, second_session_id, "deleted")

        restored = client.post(f"/assets/{asset_id}/restore", json={"approved": True})
        assert restored.status_code == 200, restored.text
        assert asset_id in _catalog_asset_ids(client, first_session_id, "active")
        assert asset_id in _catalog_asset_ids(client, second_session_id, "active")

    with _client(tmp_path) as restarted:
        summary = restarted.get("/memory/summary", params={"workspace_id": second.context_id})
        assert summary.status_code == 200, summary.text
        catalog = summary.json()["memory"]["assetCatalog"]
        assert catalog["contextId"] == second.context_id
        assert catalog["revision"]
        assert asset_id in [entry["asset"]["id"] for entry in catalog["active"]]
