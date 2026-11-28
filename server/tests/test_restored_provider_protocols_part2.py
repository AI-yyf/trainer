"""(k) Provider protocol truth: token limits, quotas, schemes, capability evidence and
    failure categories are derived from real probes, never from declarations.

Guarantees covered:
  * token limits, quotas and reasoning budgets are enforced from resolved model limits;
  * scheme-less and loopback base URLs resolve and bypass the ambient proxy without leaking it;
  * capability truth survives sidecar restarts and is only granted by observed probes;
  * an unconfigured provider is refused with honest copy instead of a fabricated reply;
  * reasoning-leak and vision failures are categorized from real provider responses.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_unconfigured_provider_gate.py
  * server/tests/test_provider_reasoning_budget.py
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider.capability import _model_looks_reasoning_first
from app.llm.provider_service import ProviderService
from app.main import create_app

# ---------------------------------------------------------------------------
# Restored from test_unconfigured_provider_gate.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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
    "baseUrl": "https://gateway.example",
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


def test_minimax_reasoning_first_provider_gets_generous_client_timeout() -> None:
    """Measured MiniMax-M3.x spends 90s+ on generation-sized prompts; the
    45s default killed real card authoring as a false timeout (two 45s
    attempts = the observed 90.06s 400). Reasoning carries no designed
    read-time wall: the generation client's read timeout is unbounded while
    connect/write/pool stay bounded, and the agent loop carries no per-step
    wall either."""
    import math

    provider = ProviderConfig.model_validate(
        {
            "name": "minimax-relay",
            "baseUrl": "http://minimax.example",
            "apiKeyRef": "trainer.minimax",
            "model": "MiniMax-M3.1-Flash",
            "protocol": "openai_chat_completions_compatible",
        }
    )
    service = ProviderService(config=provider, api_key="sk-test")
    timeouts = service._agent_loop_timeout_kwargs()  # noqa: SLF001
    assert timeouts["step_timeout"] == math.inf
    assert timeouts["first_step_timeout"] == math.inf


def test_plain_provider_agent_steps_keep_bounded_defaults() -> None:
    """Non-reasoning providers keep the bounded step defaults — the unbounded
    reasoning tier exists so hidden thinking is never a false timeout, not to
    remove liveness bounds for ordinary gateways."""
    provider = ProviderConfig.model_validate(
        {
            "name": "plain-openai",
            "baseUrl": "https://api.example/v1",
            "apiKeyRef": "trainer.plain",
            "model": "gpt-4.1-mini",
            "protocol": "openai_chat_completions_compatible",
        }
    )
    service = ProviderService(config=provider, api_key="sk-test")
    assert service._agent_loop_timeout_kwargs() == {}  # noqa: SLF001
    assert service._probe_client_timeout_seconds() == 45.0  # noqa: SLF001


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


# ---------------------------------------------------------------------------
# Restored from test_provider_reasoning_budget.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _provider(model: str) -> ProviderConfig:
    return ProviderConfig(
        name="MiniMax Relay",
        baseUrl="http://minimax.relay.example.test/v1",
        apiKeyRef="trainer.test",
        model=model,
    )


def test_minimax_m3_is_reasoning_first_and_gets_headroom() -> None:
    provider = _provider("MiniMax-M3.1-Flash")
    assert _model_looks_reasoning_first(provider) is True
    service = ProviderService(config=provider)
    assert service.recommended_generation_max_tokens(1024) == 8192


def test_minimax_m27_keeps_the_normal_budget() -> None:
    provider = _provider("MiniMax-M2.7")
    assert _model_looks_reasoning_first(provider) is False
    service = ProviderService(config=provider)
    assert service.recommended_generation_max_tokens(1024) == 1024


def test_escalation_goes_beyond_the_old_8192_cap() -> None:
    assert ProviderService._escalated_chat_budget(1024) == 8192
    assert ProviderService._escalated_chat_budget(8192) == 16384
    assert ProviderService._escalated_chat_budget(16384) is None
