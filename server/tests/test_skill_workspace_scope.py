"""Cross-project isolation for project-distilled skills."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.skills.registry import SkillRegistry
from app.skills.runtime import build_skill_guidance_block, select_active_skills


def _distilled(registry: SkillRegistry, workspace_id: str, *, body: str = "Project knowledge body."):
    return registry.upsert_knowledge_skill(
        skill_id="project-queue",
        name="Queue project knowledge",
        description="Queue lock architecture and module map.",
        body=body,
        metadata={
            "origin": "project-analysis",
            "workspace_id": workspace_id,
            "commit_sha": f"commit-{workspace_id}",
            "front_matter": {
                "name": "project-queue",
                "description": "Queue lock architecture and module map.",
                "triggers": "queue lock, module map",
            },
        },
        workspace_id=workspace_id,
    )


def test_same_project_name_in_two_workspaces_stays_separate(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    first, created_first = _distilled(registry, "workspace-a", body="A body")
    second, created_second = _distilled(registry, "workspace-b", body="B body")

    assert created_first is True
    assert created_second is True
    assert first.skill_id != second.skill_id
    assert first.workspace_id == "workspace-a"
    assert second.workspace_id == "workspace-b"
    assert first.body == "A body"
    assert second.body == "B body"

    a_ids = {skill.skill_id for skill in registry.list_skills(workspace_id="workspace-a")}
    b_ids = {skill.skill_id for skill in registry.list_skills(workspace_id="workspace-b")}
    assert first.skill_id in a_ids
    assert second.skill_id not in a_ids
    assert second.skill_id in b_ids
    assert first.skill_id not in b_ids
    # Global first-party skills remain visible in every workspace.
    assert any(skill.workspace_id == "" for skill in registry.list_skills(workspace_id="workspace-a"))


def test_selection_and_injection_never_cross_workspaces(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    first, _ = _distilled(registry, "workspace-a", body="A-specific queue guidance.")
    second, _ = _distilled(registry, "workspace-b", body="B-specific queue guidance.")

    selected_a = select_active_skills(registry, "explain the queue lock module map", workspace_id="workspace-a")
    selected_b = select_active_skills(registry, "explain the queue lock module map", workspace_id="workspace-b")
    assert [skill.skill_id for skill in selected_a] == [first.skill_id]
    assert [skill.skill_id for skill in selected_b] == [second.skill_id]

    guidance_a = build_skill_guidance_block(selected_a, workspace_id="workspace-a")
    guidance_b = build_skill_guidance_block(selected_b, workspace_id="workspace-b")
    assert "A-specific queue guidance." in guidance_a
    assert "B-specific queue guidance." not in guidance_a
    assert "B-specific queue guidance." in guidance_b
    assert "A-specific queue guidance." not in guidance_b

    # A selected skill cannot be injected into another workspace even when the
    # caller passes the wrong selection object.
    assert build_skill_guidance_block(selected_a, workspace_id="workspace-b") == ""
    # Missing workspace context exposes only global skills, never project ones.
    selected_without_scope = select_active_skills(registry, "queue lock module map")
    assert all(skill.workspace_id == "" for skill in selected_without_scope)


def test_review_activation_and_usage_reject_other_workspace(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    record = registry.register(
        skill_id="queue-action",
        kind="action",
        name="Queue action",
        description="Queue lock mutation workflow.",
        permissions=["read:workspace"],
        workspace_id="workspace-a",
    )
    assert record.workspace_id == "workspace-a"

    with pytest.raises(KeyError):
        registry.mark_reviewed("queue-action", workspace_id="workspace-b")
    reviewed = registry.mark_reviewed("queue-action", workspace_id="workspace-a")
    assert reviewed.reviewed is True

    with pytest.raises(KeyError):
        registry.activate("queue-action", workspace_id="workspace-b")
    activated = registry.activate("queue-action", workspace_id="workspace-a")
    assert activated.active is True

    with pytest.raises(KeyError):
        registry.record_usage("queue-action", applied=True, workspace_id="workspace-b")
    with pytest.raises(KeyError):
        registry.record_failure("queue-action", error="boom", workspace_id="workspace-b")

    usage = registry.record_usage("queue-action", applied=True, workspace_id="workspace-a")
    assert usage.metadata["last_used_workspace"] == "workspace-a"


def test_registration_rejects_cross_workspace_skill_id_reuse(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    registry.register(
        skill_id="shared-id",
        kind="knowledge",
        name="Shared",
        workspace_id="workspace-a",
    )
    with pytest.raises(ValueError, match="another workspace"):
        registry.register(
            skill_id="shared-id",
            kind="knowledge",
            name="Shared",
            workspace_id="workspace-b",
        )


def test_workspace_scope_survives_registry_restart(tmp_path: Path) -> None:
    storage = tmp_path / "skills"
    registry = SkillRegistry(storage)
    first, _ = _distilled(registry, "workspace-a")
    second, _ = _distilled(registry, "workspace-b")

    reloaded = SkillRegistry(storage)
    a_ids = {skill.skill_id for skill in reloaded.list_skills(workspace_id="workspace-a")}
    b_ids = {skill.skill_id for skill in reloaded.list_skills(workspace_id="workspace-b")}
    assert first.skill_id in a_ids and first.skill_id not in b_ids
    assert second.skill_id in b_ids and second.skill_id not in a_ids
    assert reloaded._skills[first.skill_id].workspace_id == "workspace-a"


def test_skill_api_filters_list_and_rejects_cross_workspace_review(tmp_path: Path) -> None:
    settings = AppSettings(
        app_name="Trainer skill scope",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-skill-scope.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        registered = client.post(
            "/skill/register",
            json={
                "skill_id": "api-scoped",
                "kind": "knowledge",
                "name": "API scoped",
                "description": "Workspace A only.",
                "workspace_id": "workspace-a",
            },
        )
        assert registered.status_code == 200
        assert registered.json()["skill"]["workspace_id"] == "workspace-a"

        listing_a = client.get("/skill/list", params={"workspace_id": "workspace-a"}).json()
        listing_b = client.get("/skill/list", params={"workspace_id": "workspace-b"}).json()
        assert "api-scoped" in {skill["skill_id"] for skill in listing_a["skills"]}
        assert "api-scoped" not in {skill["skill_id"] for skill in listing_b["skills"]}

        denied = client.post(
            "/skill/review",
            json={
                "skill_id": "api-scoped",
                "workspace_id": "workspace-b",
                "approved": True,
            },
        )
        assert denied.status_code == 404
        allowed = client.post(
            "/skill/review",
            json={
                "skill_id": "api-scoped",
                "workspace_id": "workspace-a",
                "approved": True,
            },
        )
        assert allowed.status_code == 200


def test_router_is_mounted_in_the_application(tmp_path: Path) -> None:
    app = create_app(
        AppSettings(
            app_name="Trainer skill router",
            host="127.0.0.1",
            port=8765,
            data_dir=tmp_path / "data",
            database_name="trainer-skill-router.db",
            default_session_stage="intake",
            summary_message_limit=6,
            enable_network_fetch=False,
        )
    )
    with TestClient(app) as client:
        assert client.get("/skill/status").status_code == 200
