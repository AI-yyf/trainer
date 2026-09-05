"""Sidecar-produced LearningPlan and TaskSpec carry the producing workspace stamp."""

from pathlib import Path

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import LearningPlan, ProviderConfig, TaskSpec, UserProfile
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.memory.workspace_recovery import stamp_produced_workspace_record


def build_client(tmp_path: Path) -> TestClient:
    app = create_app(
        AppSettings(
            app_name="Trainer Plan Task Stamp Test Server",
            host="127.0.0.1",
            port=8765,
            data_dir=tmp_path,
            database_name="trainer-test.db",
            default_session_stage="intake",
            summary_message_limit=6,
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
    return TestClient(app)


def test_stamp_produced_workspace_record_does_not_invent_a_plan() -> None:
    assert stamp_produced_workspace_record(None, "workspace-b") is None


def test_stamp_empty_plan_onto_producing_workspace_keeps_identity() -> None:
    plan = LearningPlan(
        id="plan-discussion-only",
        title="Persisted formal plan",
        current_step="Inspect the turn route before changing the plan.",
    )
    stamped = stamp_produced_workspace_record(plan, "workspace-plan-discussion-only")
    assert stamped is plan
    assert stamped.workspace_id == "workspace-plan-discussion-only"
    assert stamped.id == "plan-discussion-only"
    assert stamped.title == "Persisted formal plan"
    assert stamped.current_step == "Inspect the turn route before changing the plan."


def test_stamp_produced_workspace_record_keeps_a_foreign_stamp() -> None:
    plan = LearningPlan(id="plan-a", title="Leftover A", workspace_id="workspace-a")
    stamped = stamp_produced_workspace_record(plan, "workspace-b")
    assert stamped is plan
    assert stamped.workspace_id == "workspace-a"


def test_sidecar_generate_plan_on_b_stamps_b(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/plan/generate",
            json={
                "workspace_id": "workspace-b",
                "profile": UserProfile(long_term_goal="Build reliable software").model_dump(
                    mode="json"
                ),
                "goals": ["Build reliable software"],
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["workspace_id"] == "workspace-b"
        assert payload["plan"]["workspace_id"] == "workspace-b"
        assert payload["plan"]["title"]
        assert payload["plan"]["id"]


def produced_workspace_id(payload: dict[str, object]) -> str:
    return str(payload.get("workspace_id") or payload.get("workspaceId") or "")


def test_sidecar_next_task_on_b_stamps_b(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        plan_response = client.post(
            "/plan/generate",
            json={
                "workspace_id": "workspace-b",
                "profile": UserProfile(long_term_goal="Build reliable software").model_dump(
                    mode="json"
                ),
                "goals": ["Build reliable software"],
            },
        )
        assert plan_response.status_code == 200, plan_response.text
        response = client.post("/task/next", json={"workspace_id": "workspace-b"})
        assert response.status_code == 200
        payload = response.json()
        assert produced_workspace_id(payload) == "workspace-b"
        assert payload["id"]
        assert payload["title"]


def test_sidecar_specify_task_on_b_stamps_b(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        plan_response = client.post(
            "/plan/generate",
            json={
                "workspace_id": "workspace-b",
                "profile": UserProfile(long_term_goal="Build reliable software").model_dump(
                    mode="json"
                ),
                "goals": ["Build reliable software"],
            },
        )
        assert plan_response.status_code == 200, plan_response.text
        response = client.post(
            "/task/specify",
            json={
                "workspace_id": "workspace-b",
                "natural_language_goal": "Return a sorted list of integers and keep duplicates.",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert produced_workspace_id(payload) == "workspace-b"
        assert payload["title"]
        assert str((payload.get("metadata") or {}).get("plan_id") or "").strip()

def test_unscoped_leftover_plan_stays_unscoped_when_not_produced() -> None:
    leftover = LearningPlan(id="plan-leftover-a", title="Keep the leftover A plan")
    assert leftover.workspace_id == ""
    dumped = leftover.model_dump()
    assert not dumped.get("workspace_id")
    parsed = TaskSpec(
        id="task-1",
        title="Generated task",
        natural_language_goal="Invent a live task",
    )
    assert parsed.workspace_id == ""
