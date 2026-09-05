"""Tests for SubPlan endpoints (§1.6 / §1.23)."""
from pathlib import Path

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import LearningPlan, PlanStage, ProviderConfig, SubPlan
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def build_client(tmp_path: Path, *, configure_provider: bool = True) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    app = create_app(settings)
    if configure_provider:
        provider = ProviderConfig(
            name="test-openai-compatible",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={
                "chat": True,
                "responses": True,
                "vision": False,
                "embeddings": True,
                "tools": False,
                "json_schema": False,
                "streaming": True,
            },
        )
        runtime = app.state.runtime
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()
        seed_verified_capabilities(runtime, provider, "sk-test", tools=False)
    return TestClient(app)


def test_list_subplans_empty_when_no_plan(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.get("/plan/nonexistent/subplans")
    assert response.status_code == 200
    assert response.json() == []


def test_create_subplan_roundtrip(tmp_path: Path) -> None:
    """Create a plan, add a subplan, list it, update it, delete it."""
    with build_client(tmp_path) as client:
        client.post("/session/start", json={"workspace_id": "ws-subplan", "workspace_name": "ws-subplan"})
        plan = LearningPlan(
            id="master-1",
            title="Master Plan",
            stages=[PlanStage(id="s1", title="Stage 1", goal="Goal 1", outcomes=["o1"])],
        )
        gen_resp = client.post("/plan/generate", json=plan.model_dump(mode="json"))
        assert gen_resp.status_code in (200, 201)
        plan_id = gen_resp.json().get("id", "master-1")

        sub = SubPlan(title="Frontend React", description="React hooks training")
        resp = client.post(f"/plan/{plan_id}/subplan", json=sub.model_dump(mode="json"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Frontend React"
        assert data["parent_plan_id"] == plan_id
        sub_id = data["id"]

        resp = client.get(f"/plan/{plan_id}/subplans")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        updated = SubPlan(
            id=sub_id,
            parent_plan_id=plan_id,
            title="Frontend React Advanced",
            description="Advanced React patterns",
            status="active",
            progress_percent=50.0,
        )
        resp = client.put(
            f"/plan/{plan_id}/subplan/{sub_id}", json=updated.model_dump(mode="json")
        )
        assert resp.status_code == 200
        assert resp.json()["progress_percent"] == 50.0

        resp = client.delete(f"/plan/{plan_id}/subplan/{sub_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        resp = client.get(f"/plan/{plan_id}/subplans")
        assert resp.json() == []


def test_subplans_survive_sidecar_restart_and_restore_into_memory_snapshot(tmp_path: Path) -> None:
    workspace_id = "ws-subplan-restart"

    with build_client(tmp_path) as client:
        session_id = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Restart workspace"},
        ).json()["session_id"]
        plan = LearningPlan(id="restart-parent-plan", title="Restart parent plan", stages=[])
        response = client.post(
            "/plan/generate",
            json={**plan.model_dump(mode="json"), "session_id": session_id},
        )
        assert response.status_code == 200
        plan_id = response.json()["id"]
        created = client.post(
            f"/plan/{plan_id}/subplan",
            json=SubPlan(title="Durable sub-plan").model_dump(mode="json"),
        )
        assert created.status_code == 200

    with build_client(tmp_path) as restarted_client:
        listed = restarted_client.get(f"/plan/{plan_id}/subplans")
        assert listed.status_code == 200
        assert [item["title"] for item in listed.json()] == ["Durable sub-plan"]

        restored_session_id = restarted_client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Restart workspace"},
        ).json()["session_id"]
        snapshot = restarted_client.get(
            "/memory/summary",
            params={"session_id": restored_session_id},
        )
        assert snapshot.status_code == 200
        assert [item["title"] for item in snapshot.json()["memory"]["subplans"]] == [
            "Durable sub-plan"
        ]


def test_update_subplan_not_found(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        client.post("/session/start", json={"workspace_id": "ws-sp-2", "workspace_name": "ws-sp-2"})
        plan = LearningPlan(id="master-2", title="Plan", stages=[])
        client.post("/plan/generate", json=plan.model_dump(mode="json"))
        resp = client.put(
            "/plan/master-2/subplan/nonexistent",
            json={
                "id": "nonexistent",
                "parent_plan_id": "master-2",
                "title": "x",
                "description": "",
                "stages": [],
                "status": "draft",
                "created_at": "",
                "updated_at": "",
                "progress_percent": 0,
            },
        )
    assert resp.status_code == 404


def test_delete_subplan_not_found(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        client.post("/session/start", json={"workspace_id": "ws-sp-3", "workspace_name": "ws-sp-3"})
        plan = LearningPlan(id="master-3", title="Plan", stages=[])
        client.post("/plan/generate", json=plan.model_dump(mode="json"))
        resp = client.delete("/plan/master-3/subplan/nonexistent")
    assert resp.status_code == 404
