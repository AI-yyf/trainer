"""Regression coverage for explicit global-plan governance."""
from pathlib import Path

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import ProviderConfig, UserProfile
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def _seed_live_usable_provider(client: TestClient) -> None:
    runtime = client.app.state.runtime
    provider = ProviderConfig(
        name="test-openai-compatible",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={"chat": True, "streaming": True, "tools": False},
    )
    test_credential = "fixture-credential"
    runtime.provider_config = provider
    runtime.provider_api_key = test_credential
    runtime.provider_service = ProviderService(config=provider, api_key=test_credential)
    runtime.provider_service_cache.clear()
    seed_verified_capabilities(runtime, provider, test_credential, tools=False)


def build_client(tmp_path: Path) -> TestClient:
    client = TestClient(
        create_app(
            AppSettings(
                app_name="Trainer Global Plan Test Server",
                host="127.0.0.1",
                port=8765,
                data_dir=tmp_path,
                database_name="trainer-test.db",
                default_session_stage="intake",
                summary_message_limit=6,
            )
        )
    )
    _seed_live_usable_provider(client)
    return client


def create_project_plan(client: TestClient, workspace_id: str) -> tuple[str, str]:
    session_response = client.post(
        "/session/start",
        json={"workspace_id": workspace_id, "workspace_name": workspace_id},
    )
    assert session_response.status_code == 200
    session_id = session_response.json()["session_id"]
    response = client.post(
        "/plan/generate",
        json={
            "workspace_id": workspace_id,
            "profile": UserProfile(long_term_goal="Build reliable software").model_dump(mode="json"),
            "goals": ["Build reliable software"],
        },
    )
    assert response.status_code == 200
    return session_id, response.json()["id"]


def test_global_plan_links_the_existing_project_plan_and_survives_restart(tmp_path: Path) -> None:
    workspace_id = "workspace-global-plan"
    with build_client(tmp_path) as client:
        session_id, project_plan_id = create_project_plan(client, workspace_id)

        before_creation = client.get("/plan/context", params={"workspace_id": workspace_id})
        assert before_creation.status_code == 200
        assert before_creation.json()["global_plan"] is None

        created = client.post(
            "/plan/global",
            json={
                "workspace_id": workspace_id,
                "title": "Long-term engineering mastery",
                "goals": ["Build reliable software across projects"],
            },
        )
        assert created.status_code == 200
        assert created.json()["global_plan"]["title"] == "Long-term engineering mastery"
        assert created.json()["project_plan_link"]["project_plan_id"] == project_plan_id

        memory_snapshot = client.get("/memory/summary", params={"session_id": session_id})
        assert memory_snapshot.status_code == 200
        assert memory_snapshot.json()["global_plan"]["title"] == "Long-term engineering mastery"
        assert memory_snapshot.json()["project_plan_link"]["projectPlanId"] == project_plan_id

    with build_client(tmp_path) as restarted_client:
        restored = restarted_client.get("/plan/context", params={"workspace_id": workspace_id})
        assert restored.status_code == 200
        assert restored.json()["global_plan"]["title"] == "Long-term engineering mastery"
        assert restored.json()["project_plan_link"]["project_plan_id"] == project_plan_id


def test_generated_project_plans_auto_link_through_both_generation_paths(tmp_path: Path) -> None:
    workspace_id = "workspace-auto-link"
    with build_client(tmp_path) as client:
        session_response = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert session_response.status_code == 200
        session_id = session_response.json()["session_id"]

        created = client.post(
            "/plan/global",
            json={"workspace_id": workspace_id, "title": "Long-term engineering mastery"},
        )
        assert created.status_code == 200
        assert created.json()["project_plan_link"] is None

        direct = client.post(
            "/plan/generate",
            json={
                "workspace_id": workspace_id,
                "profile": UserProfile(long_term_goal="Build reliable software").model_dump(mode="json"),
                "goals": ["Build reliable software"],
            },
        )
        assert direct.status_code == 200
        direct_plan_id = direct.json()["id"]
        direct_context = client.get("/plan/context", params={"workspace_id": workspace_id})
        assert direct_context.status_code == 200
        assert direct_context.json()["project_plan_link"]["project_plan_id"] == direct_plan_id

        session_generated = client.post(
            "/plan/generate",
            json={"session_id": session_id, "objectives": ["Practice reliable refactoring"]},
        )
        assert session_generated.status_code == 200
        session_plan_id = session_generated.json()["id"]
        session_context = client.get("/plan/context", params={"session_id": session_id})
        assert session_context.status_code == 200
        assert session_context.json()["project_plan_link"]["project_plan_id"] == session_plan_id


def test_frozen_global_plan_does_not_auto_link_project_plans(tmp_path: Path) -> None:
    workspace_id = "workspace-frozen-global-plan"
    with build_client(tmp_path) as client:
        created = client.post(
            "/plan/global",
            json={"workspace_id": workspace_id, "title": "Frozen roadmap", "frozen": True},
        )
        assert created.status_code == 200
        assert created.json()["global_plan"]["frozen"] is True

        generated = client.post(
            "/plan/generate",
            json={
                "workspace_id": workspace_id,
                "profile": UserProfile(long_term_goal="Build reliable software").model_dump(mode="json"),
                "goals": ["Build reliable software"],
            },
        )
        assert generated.status_code == 200

        context = client.get("/plan/context", params={"workspace_id": workspace_id})
        assert context.status_code == 200
        assert context.json()["project_plan_link"] is None


def test_global_plan_link_rejects_a_project_plan_from_another_workspace(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        _, project_plan_a = create_project_plan(client, "workspace-a")
        _, project_plan_b = create_project_plan(client, "workspace-b")
        created = client.post(
            "/plan/global",
            json={"workspace_id": "workspace-a", "title": "One global plan"},
        )
        assert created.status_code == 200

        rejected = client.put(
            "/plan/global/projects",
            json={"workspace_id": "workspace-a", "project_plan_id": project_plan_b},
        )
        assert rejected.status_code == 409

        linked = client.put(
            "/plan/global/projects",
            json={"workspace_id": "workspace-a", "project_plan_id": project_plan_a},
        )
        assert linked.status_code == 200


def test_global_plan_changes_only_through_explicit_global_routes(tmp_path: Path) -> None:
    workspace_id = "workspace-explicit-global-plan"
    with build_client(tmp_path) as client:
        create_project_plan(client, workspace_id)
        created = client.post(
            "/plan/global",
            json={"workspace_id": workspace_id, "title": "Original master plan"},
        )
        assert created.status_code == 200

        client.post(
            "/plan/generate",
            json={
                "workspace_id": workspace_id,
                "profile": UserProfile(long_term_goal="A new project goal").model_dump(mode="json"),
                "goals": ["A new project goal"],
            },
        )
        unchanged = client.get("/plan/context", params={"workspace_id": workspace_id})
        assert unchanged.json()["global_plan"]["title"] == "Original master plan"

        updated = client.patch(
            "/plan/global",
            json={"workspace_id": workspace_id, "title": "Explicitly updated master plan"},
        )
        assert updated.status_code == 200
        assert updated.json()["global_plan"]["title"] == "Explicitly updated master plan"


def test_global_plan_creation_rejects_missing_or_cross_workspace_project_plan(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        _, project_plan_b = create_project_plan(client, "workspace-b")

        missing = client.post(
            "/plan/global",
            json={
                "workspace_id": "workspace-a",
                "title": "Invalid roadmap",
                "current_project_plan_id": "missing-plan",
            },
        )
        assert missing.status_code == 409
        assert client.get("/plan/context", params={"workspace_id": "workspace-a"}).json()["global_plan"] is None

        cross_workspace = client.post(
            "/plan/global",
            json={
                "workspace_id": "workspace-a",
                "title": "Invalid roadmap",
                "current_project_plan_id": project_plan_b,
            },
        )
        assert cross_workspace.status_code == 409
        assert client.get("/plan/context", params={"workspace_id": "workspace-a"}).json()["global_plan"] is None


def test_global_plan_pointer_rejects_missing_or_cross_workspace_project_plan(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        _, project_plan_a = create_project_plan(client, "workspace-a")
        _, project_plan_b = create_project_plan(client, "workspace-b")
        created = client.post(
            "/plan/global",
            json={"workspace_id": "workspace-a", "title": "Isolated roadmap"},
        )
        assert created.status_code == 200

        missing = client.patch(
            "/plan/global",
            json={"workspace_id": "workspace-a", "current_project_plan_id": "missing-plan"},
        )
        assert missing.status_code == 409

        cross_workspace = client.patch(
            "/plan/global",
            json={"workspace_id": "workspace-a", "current_project_plan_id": project_plan_b},
        )
        assert cross_workspace.status_code == 409

        restored = client.get("/plan/context", params={"workspace_id": "workspace-a"})
        assert restored.status_code == 200
        assert restored.json()["global_plan"]["current_project_plan_id"] is None
        assert restored.json()["project_plan_link"]["project_plan_id"] == project_plan_a
