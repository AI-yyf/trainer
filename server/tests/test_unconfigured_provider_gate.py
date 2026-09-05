from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.models import ProviderConfig, ProviderTestResponse
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Unconfigured Provider Gate",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-unconfigured-gate.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


KIMI_PROVIDER = {
    "name": "kimi-k3-longai",
    "baseUrl": "https://llm.longai.vip",
    "apiKeyRef": "trainer.live-kimi",
    "model": "kimi-k3",
    "protocol": "openai_chat_completions_compatible",
    "contextWindowTokens": 1_048_576,
    "modelTokenLimits": {"kimi-k3": {"contextWindowTokens": 1_048_576}},
    "capabilities": {
        "chat": True,
        "responses": True,
        "vision": True,
        "embeddings": False,
        "tools": True,
        "jsonSchema": False,
        "structuredOutput": False,
        "streaming": True,
        "thinking": False,
    },
}


def test_session_message_without_api_key_does_not_invent_a_coach_turn(tmp_path: Path) -> None:
    workspace_id = "workspace-unconfigured-gate"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Unconfigured",
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": "帮我出一张训练卡片",
                "response_language": "zh-CN",
            },
        )

    assert response.status_code == 400
    detail = str(response.json().get("detail") or "")
    assert "API key" in detail or "provider" in detail.lower()
    assert "session_id" not in response.json()


def test_plan_update_content_without_live_provider_does_not_invent_a_revision(
    tmp_path: Path,
) -> None:
    from app.core.models import LearningPlan, PlanStage

    workspace_id = "workspace-unconfigured-plan-update"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Unconfigured plan update",
            },
        )
        assert started.status_code == 200, started.text
        runtime = client.app.state.runtime
        plan = LearningPlan(
            id="plan-unconfigured-update",
            title="Keep this plan until a live coach revises it",
            current_step="Do not invent a revision while disconnected",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Stay honest",
                    goal="Do not invent a revision while disconnected",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        runtime.repository.save_plan(workspace_id, plan)
        runtime.memory_service.bind_explicit_generated_plan(workspace_id, plan)
        frozen = client.post(
            "/plan/update",
            json={
                "plan_id": plan.id,
                "workspace_id": workspace_id,
                "frozen": True,
            },
        )
        assert frozen.status_code == 200, frozen.text
        resumed = client.post(
            "/plan/update",
            json={
                "plan_id": plan.id,
                "workspace_id": workspace_id,
                "frozen": False,
            },
        )
        assert resumed.status_code == 200, resumed.text
        response = client.post(
            "/plan/update",
            json={
                "plan_id": plan.id,
                "workspace_id": workspace_id,
                "title": "Invented disconnected revision",
                "instructions": "Rewrite the formal plan without a live provider.",
                "response_language": "zh-CN",
            },
        )

    assert response.status_code == 400, response.text
    body = response.json()
    detail = str(body.get("detail") or "")
    assert "不能用" in detail or "not ready" in detail.lower() or "API key" in detail
    stored = runtime.repository.get_latest_plan(workspace_id)
    assert stored is not None
    assert stored.title == plan.title
    assert stored.current_step == plan.current_step


def test_plan_generate_without_live_provider_does_not_invent_a_plan(tmp_path: Path) -> None:
    workspace_id = "workspace-unconfigured-plan"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Unconfigured plan",
            },
        )
        assert started.status_code == 200, started.text
        response = client.post(
            "/plan/generate",
            json={
                "session_id": started.json()["session_id"],
                "workspace_id": workspace_id,
                "goals": ["学会写一个登录接口"],
                "response_language": "zh-CN",
            },
        )

    assert response.status_code == 400, response.text
    body = response.json()
    detail = str(body.get("detail") or "")
    assert "不能用" in detail or "API key" in detail or "provider" in detail.lower()
    assert not body.get("plan")
    assert not body.get("stages")


def test_training_generate_card_without_live_provider_does_not_mint_a_stub(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-unconfigured-card"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Unconfigured card",
            },
        )
        assert started.status_code == 200, started.text
        response = client.post(
            "/training/generate-card",
            json={
                "session_id": started.json()["session_id"],
                "workspace_id": workspace_id,
                "source": "conversation_gap",
                "card_type": "practice",
                "response_language": "zh-CN",
            },
        )

    assert response.status_code == 400, response.text
    body = response.json()
    assert not body.get("card")
    assert not body.get("card_id")
    sandbox_root = client.app.state.runtime.sandbox_service.ensure_workspace_root(workspace_id)
    cards_root = sandbox_root / "cards"
    assert not cards_root.exists() or not list(cards_root.rglob("*.md"))


def test_turn_rejects_unknown_resource_composer_mode_as_unprocessable(tmp_path: Path) -> None:
    workspace_id = "workspace-invalid-resource-mode"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Invalid mode",
            },
        )
        assert started.status_code == 200, started.text
        response = client.post(
            "/turn",
            json={
                "session_id": started.json()["session_id"],
                "workspace_id": workspace_id,
                "intent": "resources",
                "message": "查找资料",
                "resourceComposerIntent": {"mode": "search"},
            },
        )

    assert response.status_code == 422, response.text
    assert response.status_code != 500


def test_turn_with_untested_provider_does_not_run_a_mock_coach(tmp_path: Path) -> None:
    workspace_id = "workspace-untested-provider"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Untested",
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "帮我出一张训练卡片",
                "response_language": "zh-CN",
                "provider": KIMI_PROVIDER,
                "api_key": "sk-untested-not-live",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    reply = str((body.get("reply") or {}).get("content") or "")
    summary = str((body.get("coach_turn") or {}).get("summary") or "")
    visible = reply or summary
    assert "provider" in visible.lower()
    assert "API key" in visible or "permission" in visible.lower()
    assert "训练卡片" not in visible
    current_task = body.get("current_task") or (body.get("snapshot") or {}).get("currentTask")
    assert not current_task or not str(
        (current_task or {}).get("id") or (current_task or {}).get("title") or ""
    ).strip()


def test_provider_test_records_declared_vision_and_context_window(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_test(
        self: ProviderService,
        provider: ProviderConfig,
        api_key: str | None,
        **_: object,
    ) -> ProviderTestResponse:
        captured["provider"] = provider
        captured["api_key"] = api_key
        return ProviderTestResponse(
            ok=True,
            detail="connected",
            diagnostics=["mocked"],
            provider_reachable=True,
            model_supported=True,
            vision_ready=True,
            vision_probe_status="verified",
            capability_evidence=[
                {
                    "name": "vision",
                    "declared": True,
                    "observed": True,
                    "state": "verified",
                }
            ],
        )

    with patch.object(ProviderService, "test", fake_test):
        with build_client(tmp_path) as client:
            response = client.post(
                "/provider/test",
                json={
                    "apiKey": "sk-test",
                    "provider": KIMI_PROVIDER,
                },
            )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["success"] is True
    assert payload["model"] == "kimi-k3"
    assert payload["context_window_tokens"] == 1_048_576
    assert payload["model_token_limits"]["kimi-k3"]["contextWindowTokens"] == 1_048_576
    assert payload["capabilities"]["vision"] is True
    assert payload["model_capabilities"]["kimi-k3"]["vision"] is True
    assert payload["vision_ready"] is True
    assert payload["vision_probe_status"] == "verified"
    provider = captured["provider"]
    assert isinstance(provider, ProviderConfig)
    assert provider.model == "kimi-k3"
    assert provider.context_window_tokens == 1_048_576
    assert provider.capabilities.vision is True


def test_kimi_like_provider_uses_generous_agent_and_http_timeouts() -> None:
    from app.llm.agent_loop import CoachAgentLoop

    provider = ProviderConfig.model_validate(KIMI_PROVIDER)
    service = ProviderService(config=provider, api_key="sk-test")
    timeouts = service._agent_loop_timeout_kwargs()  # noqa: SLF001
    assert timeouts["step_timeout"] == 120.0
    assert timeouts["first_step_timeout"] == 180.0
    assert service._provider_client_timeout_seconds() == 180.0  # noqa: SLF001
    loop = CoachAgentLoop(
        provider=__import__("app.llm.agent_loop", fromlist=["AgentProvider"]).AgentProvider(
            protocol="openai_chat_completions_compatible",
            call=lambda *_args, **_kwargs: None,  # type: ignore[misc]
        ),
        registry=__import__("app.llm.tools", fromlist=["ToolRegistry"]).ToolRegistry(),
        context=__import__("app.llm.tools", fromlist=["ToolContext"]).ToolContext(
            runtime=None,
            workspace_id="ws",
        ),
        **timeouts,
    )
    assert loop.step_timeout == 120.0
    assert loop.first_step_timeout == 180.0


def test_observed_capability_cache_unlocks_vision_delivery_on_a_new_service() -> None:
    provider = ProviderConfig.model_validate(KIMI_PROVIDER)
    service = ProviderService(config=provider, api_key="sk-test")
    before = service.describe_attachment_delivery(
        attachments=[{"kind": "image", "mime_type": "image/png", "data_base64": "xx"}],
        use_agent_loop=True,
    )
    assert before["attachments_delivery_reason"] == "vision_not_available"
    service.apply_observed_capability_states({"vision": "verified"})
    after = service.describe_attachment_delivery(
        attachments=[{"kind": "image", "mime_type": "image/png", "data_base64": "xx"}],
        use_agent_loop=True,
    )
    assert after["attachments_delivered_to_model"] is True
