from pathlib import Path

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import ProviderConfig
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
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
    runtime.provider_service_cache.clear()
    seed_verified_capabilities(runtime, provider, "sk-test", tools=False)


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "database_path" in payload


def test_browser_preview_origin_is_allowed() -> None:
    client = TestClient(create_app())
    origin = "http://127.0.0.1:4189"
    response = client.get("/health", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_plan_generation() -> None:
    client = TestClient(create_app())
    _seed_live_usable_provider(client)
    response = client.post(
        "/plan/generate",
        json={
            "profile": {
                "long_term_goal": "Build FastAPI training tools",
                "background": "Intermediate Python",
                "weekly_hours": 6,
                "teaching_style": "guided",
                "answer_policy": "guided",
                "preferred_libraries": ["fastapi", "pytest"],
            },
            "goals": ["Build FastAPI training tools"],
            "constraints": ["6 hours/week"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["title"].startswith("Trainer plan")
    assert len(payload["stages"]) == 3


def test_task_and_evaluate_routes_allow_missing_session_id(tmp_path) -> None:
    client = TestClient(create_app())
    _seed_live_usable_provider(client)
    workspace_id = "workspace-isolated"

    plan_response = client.post(
        "/plan/generate",
        json={
            "workspace_id": workspace_id,
            "profile": {
                "long_term_goal": "Build FastAPI training tools",
                "weekly_hours": 4,
                "teaching_style": "guided",
                "answer_policy": "guided",
            },
            "goals": ["Build FastAPI training tools"],
        },
    )
    assert plan_response.status_code == 200, plan_response.text
    plan_id = str(
        (plan_response.json().get("plan") or plan_response.json()).get("id")
        or (plan_response.json().get("plan") or plan_response.json()).get("plan_id")
        or ""
    ).strip()
    assert plan_id

    specify_response = client.post(
        "/task/specify",
        json={
            "session_id": None,
            "workspace_id": workspace_id,
            "natural_language_goal": (
                "Input: accept a list of integers.\n"
                "Output: return the sorted list.\n"
                "Must preserve duplicates.\n"
                "Raise an error for null input."
            ),
        },
    )
    assert specify_response.status_code == 200
    specify_payload = specify_response.json()
    assert specify_payload["title"]
    assert specify_payload["constraints"]
    assert str((specify_payload.get("metadata") or {}).get("plan_id") or "").strip() == plan_id

    task_response = client.post("/task/next", json={"workspace_id": workspace_id})
    assert task_response.status_code == 200
    task_payload = task_response.json()
    assert task_payload["id"]

    file_path = tmp_path / "snippet.py"
    file_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    evaluation_response = client.post(
        "/evaluate/current-file",
        json={
            "workspace_id": workspace_id,
            "file_path": str(file_path),
            "language_id": "python",
            "content": file_path.read_text(encoding="utf-8"),
        },
    )
    assert evaluation_response.status_code == 200
    evaluation_payload = evaluation_response.json()
    assert "summary" in evaluation_payload


def test_app_shutdown_closes_semantic_memory_handles(tmp_path: Path) -> None:
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
    client = TestClient(create_app(settings))
    semantic_memory = client.app.state.runtime.resource_service.semantic_memory
    close_calls: list[bool] = []

    original_close = semantic_memory.close

    def fake_close() -> None:
        close_calls.append(True)
        original_close()

    semantic_memory.close = fake_close  # type: ignore[assignment]

    with client:
        response = client.get("/health")
        assert response.status_code == 200

    assert close_calls == [True]
