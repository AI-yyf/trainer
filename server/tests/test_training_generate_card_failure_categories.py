"""POST /training/generate-card must keep failure categories distinct and explainable."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.training.card_generator import (
    CardGenerationProviderFailure,
    _card_generation_failure_category,
    _classify_card_provider_exception,
)
from tests.provider_fixtures import seed_verified_capabilities


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-training-card-failcat.db",
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


def test_card_failure_categories_stay_distinct() -> None:
    assert _card_generation_failure_category("invalid_json") == "invalid_json"
    assert (
        _card_generation_failure_category("exception")
        == "provider_request_failed_training_card"
    )
    assert (
        _classify_card_provider_exception(RuntimeError("Provider request failed (HTTP 401)."))
        == "invalid_key_or_permission"
    )
    failure = CardGenerationProviderFailure(
        "invalid_key_or_permission",
        response_language="en-US",
    )
    detail = failure.http_detail()
    assert detail["category"] == "invalid_key_or_permission"
    assert "API key" in str(detail["detail"])
    assert "not accepted" not in str(detail["detail"]).lower()


def test_generate_card_provider_401_is_explainable(tmp_path: Path, monkeypatch) -> None:
    with build_client(tmp_path) as client:
        session = client.post(
            "/session/start",
            json={
                "workspace_id": "ws-training-failcat-401",
                "workspace_name": "Training failcat",
                "workspace_path": str(tmp_path / "ws"),
                "profile": {
                    "long_term_goal": "Explain training card failure categories",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "coach-first",
                },
            },
        )
        assert session.status_code == 200, session.text
        session_id = session.json()["session_id"]

        async def boom(*_args, **_kwargs):
            raise RuntimeError("Provider request failed (HTTP 401).")

        monkeypatch.setattr(
            ProviderService,
            "chat_completion",
            boom,
        )

        response = client.post(
            "/training/generate-card",
            json={
                "workspace_id": "ws-training-failcat-401",
                "session_id": session_id,
                "response_language": "en-US",
                "source": "conversation_gap",
                "card_type": "practice",
                "focus_area": "fail-closed auth",
                "target_skill": "reject bad tokens",
            },
        )

    assert response.status_code == 400, response.text
    payload = response.json()
    detail = payload.get("detail")
    assert isinstance(detail, dict), payload
    assert detail.get("category") == "invalid_key_or_permission"
    assert detail.get("state") == "invalid_key_or_permission"
    assert "API key" in str(detail.get("detail") or "")
    assert "not accepted" not in str(detail.get("detail") or "").lower()


def test_generate_card_invalid_json_category(tmp_path: Path, monkeypatch) -> None:
    with build_client(tmp_path) as client:
        session = client.post(
            "/session/start",
            json={
                "workspace_id": "ws-training-failcat-json",
                "workspace_name": "Training failcat json",
                "workspace_path": str(tmp_path / "ws-json"),
                "profile": {
                    "long_term_goal": "Explain invalid_json training card failures",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "coach-first",
                },
            },
        )
        assert session.status_code == 200, session.text
        session_id = session.json()["session_id"]

        monkeypatch.setattr(
            ProviderService,
            "chat_completion",
            AsyncMock(return_value="not-json-at-all"),
        )

        response = client.post(
            "/training/generate-card",
            json={
                "workspace_id": "ws-training-failcat-json",
                "session_id": session_id,
                "response_language": "en-US",
                "source": "conversation_gap",
                "card_type": "practice",
                "focus_area": "json honesty",
                "target_skill": "fail closed on invalid json",
            },
        )

    assert response.status_code == 400, response.text
    detail = response.json().get("detail")
    assert isinstance(detail, dict), response.text
    assert detail.get("category") == "invalid_json"
    assert "JSON" in str(detail.get("detail") or "")


def test_auth_failure_not_washed_by_retry_network_noise(tmp_path: Path, monkeypatch) -> None:
    """First-attempt 401 must win over retry bridge Connection error."""
    from app.training.card_generator import CardGenerationService, CardGenerationContext

    calls = {"n": 0}

    async def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Provider request failed (HTTP 401).")
        raise RuntimeError("Connection error.")

    monkeypatch.setattr(ProviderService, "chat_completion", flaky)
    provider = ProviderConfig(
        name="test-openai-compatible",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={"chat": True, "streaming": True},
    )
    service = CardGenerationService(
        provider_service=ProviderService(config=provider, api_key="sk-test")
    )
    ctx = CardGenerationContext(
        workspace_id="ws-auth-noise",
        response_language="en-US",
        card_type="practice",
        focus_area="auth",
        target_skill="reject",
    )
    try:
        service.generate_card("conversation_gap", ctx)
        assert False, "expected CardGenerationProviderFailure"
    except CardGenerationProviderFailure as exc:
        assert exc.category == "invalid_key_or_permission"
        assert calls["n"] == 1  # auth fails closed without washing retry
