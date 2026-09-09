"""Plan /plan/generate must explain missing session_id instead of opaque 500."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from tests.provider_fixtures import seed_verified_capabilities


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
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


def test_plan_generate_missing_session_is_explainable_409(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/plan/generate",
            json={
                "session_id": "session-does-not-exist",
                "workspace_id": "ws-missing-plan-gen",
                "objectives": ["Ship one thin slice"],
                "response_language": "en-US",
            },
        )

    assert response.status_code == 409, response.text
    payload = response.json()
    detail = payload.get("detail")
    assert isinstance(detail, dict)
    assert detail.get("state") == "session_not_found"
    assert detail.get("category") == "session_not_found"
    assert detail.get("recoverable") is False
    assert detail.get("session_id") == "session-does-not-exist"
    assert "did not invent a plan" in str(detail.get("detail") or "").lower()
    assert "session_not_found" in str(detail.get("reason") or "")
