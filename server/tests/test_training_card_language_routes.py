from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.models import ProviderConfig, ProviderTestResponse
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from tests.test_router_stream_scenarios import mark_provider_capabilities_verified


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Training Route Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
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
    mark_provider_capabilities_verified(
        runtime,
        provider,
        "sk-test",
        tools=False,
    )
    return TestClient(app)


def test_turn_chinese_training_card_request_stays_hint_only(tmp_path: Path) -> None:
    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="先把 remote workspace 边界讲清楚，再进入练习。"),
        ),
    ):
        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-zh-training-card",
                "intent": "coach",
                "message": "请先给我一张关于 VS Code remote workspace 的训练卡，先学习再练习，不要先考试。",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["snapshot"]["memory"]["active_training_card_routing"] is None
    assert payload["coach_turn"]["scenario"] == "remote_workspace"


def test_turn_debug_training_request_stays_hint_only_without_mint(tmp_path: Path) -> None:
    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Start with one tiny debug loop before any wider review."),
        ),
    ):
        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-debug-training-card",
                "intent": "coach",
                "message": "Create a learn-first practice card for debugging in VS Code before any quiz.",
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["snapshot"]["memory"]["active_training_card_routing"] is None
    assert payload["coach_turn"]["scenario"] == "debug_loop"


def test_turn_chinese_continue_inherits_active_thread_lane(tmp_path: Path) -> None:
    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="继续沿着当前 debug 这条线往下走。"),
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-zh-continue-lane",
                "workspace_name": "trainer-zh-continue-lane",
                "profile": {
                    "long_term_goal": "Keep Chinese continuation inside the same coaching lane",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        runtime = client.app.state.runtime
        runtime.memory_service.record_turn_memory(
            workspace_id="workspace-zh-continue-lane",
            session_id=session_id,
            scenario="debug_loop",
            focus_area="launch diagnostics",
            summary="Pinned the first breakpoint branch.",
            next_step="Re-run one launch target and inspect the first failing frame.",
            response_language="zh-CN",
            answer_mode="guided",
        )

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-zh-continue-lane",
                "intent": "coach",
                "message": "继续",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "debug_loop"
    assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "debug_loop"
    assert payload["snapshot"]["memory"]["active_thread"]["scenario"] == "debug_loop"


def test_turn_language_corruption_does_not_mint_training_card(tmp_path: Path) -> None:
    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "test",
            return_value=ProviderTestResponse(
                ok=False,
                detail="Provider reachable, but it corrupted Chinese input into question marks before the model saw it.",
                error_category="language_corruption",
                provider_reachable=True,
                model_supported=True,
            ),
        ),
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="This should not be used once language corruption is detected."),
        ),
    ):
        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-zh-training-card-corruption",
                "intent": "coach",
                "message": "请先给我一张关于 VS Code remote workspace 的训练卡，先学习再练习，不要先考试。",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["snapshot"]["memory"]["active_training_card_routing"] is None
    assert payload["coach_turn"]["scenario"] == "remote_workspace"
