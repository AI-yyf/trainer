from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from provider_fixtures import seed_verified_capabilities

from app.api.routers import (
    provider_recovery_resumed_next_step_text,
    provider_recovery_resumed_summary_text,
)
from app.core.models import ProviderConfig, ProviderTestResponse
from app.llm.provider_service import ProviderService
from tests.test_api import build_client

PROVIDER_PAYLOAD = {
    "name": "mini-max",
    "baseUrl": "https://example.com/v1",
    "apiKeyRef": "trainer.minimax",
    "model": "MiniMax-M3",
}


def _language_corruption_failure() -> ProviderTestResponse:
    return ProviderTestResponse(
        ok=False,
        detail=(
            "Provider reachable, but it corrupted Chinese input into question marks "
            "before the model saw it."
        ),
        error_category="language_corruption",
        retryable=False,
        status_code=200,
        provider_reachable=True,
        model_supported=True,
    )


def _is_remote_workspace_focus(value: str) -> bool:
    return "remote workspace" in value.lower() or "远程工作区" in value


def _contains_cjk(value: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in value)


def test_session_message_language_block_persists_recovery_context_into_memory(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-zh-session-guard"
    provider_config = ProviderConfig.model_validate(PROVIDER_PAYLOAD)

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "test",
            autospec=True,
            return_value=_language_corruption_failure(),
        ),
    ):
        runtime = client.app.state.runtime
        runtime.provider_config = provider_config
        runtime.provider_api_key = "sk-test"
        runtime.provider_service_cache.clear()

        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "trainer-zh-session-guard",
                "profile": {
                    "long_term_goal": "Keep provider failures resumable",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]

        client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": (
                    "Please stay on VS Code remote workspace boundaries and give me the "
                    "smallest verifiable training move first."
                ),
                "provider": PROVIDER_PAYLOAD,
                "api_key": "sk-test",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    memory = payload["snapshot"]["memory"]
    active_thread = memory["active_thread"]
    assert active_thread["blocker"]
    assert "provider" in active_thread["blocker"]
    assert "gateway" in active_thread["next_step"]
    assert _is_remote_workspace_focus(active_thread["focus_area"])
    assert active_thread["focus_area"].lower() != "implementation"
    assert _is_remote_workspace_focus(memory["current_focus"])
    assert "当前记忆范围" not in memory["current_focus"]
    assert "Memory scope is" not in memory["current_focus"]
    assert any(
        "provider" in observation or "gateway" in observation
        for observation in memory["teaching_observations"]
    )

    with build_client(tmp_path, configure_provider=False) as restarted_client:
        restored_memory = restarted_client.app.state.runtime.memory_service.snapshot(workspace_id)

    assert restored_memory.active_thread is not None
    assert "provider" in restored_memory.active_thread.blocker
    assert "gateway" in restored_memory.active_thread.next_step
    assert _is_remote_workspace_focus(restored_memory.active_thread.focus_area)
    assert "gateway" in restored_memory.current_focus


def test_english_response_keeps_provider_recovery_after_chinese_input_damage(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-en-session-guard"
    provider_config = ProviderConfig.model_validate(PROVIDER_PAYLOAD)

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "test",
            autospec=True,
            return_value=_language_corruption_failure(),
        ),
    ):
        runtime = client.app.state.runtime
        runtime.provider_config = provider_config
        runtime.provider_api_key = "sk-test"
        runtime.provider_service_cache.clear()
        session_id = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "trainer-en-session-guard",
            },
        ).json()["session_id"]

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "请继续保持 VS Code remote workspace 边界，并给我一个最小可验证动作。",
                "provider": PROVIDER_PAYLOAD,
                "api_key": "sk-test",
                "responseLanguage": "en-US",
                "answer_mode": "coach-first",
            },
        )

    assert response.status_code == 200
    active_thread = response.json()["snapshot"]["memory"]["active_thread"]
    assert active_thread["blocker"]
    assert "provider" in active_thread["blocker"].lower()
    assert "switch provider or gateway" in active_thread["next_step"].lower()
    assert _is_remote_workspace_focus(active_thread["focus_area"])


def test_successful_provider_recovery_clears_stale_provider_context_for_a_new_turn(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-provider-recovery-resume"
    provider_config = ProviderConfig.model_validate(PROVIDER_PAYLOAD)

    async def coaching_reply(*args: object, **kwargs: object) -> str:
        del args, kwargs
        return "好，我们已经恢复连接。继续沿着当前 debug 主线，只验证一个最小动作。"

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "test",
            autospec=True,
            return_value=ProviderTestResponse(
                ok=True,
                detail="Provider reachable. Chat probe succeeded with model MiniMax-M3.",
                provider_reachable=True,
                model_supported=True,
            ),
        ),
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=coaching_reply),
        ),
    ):
        runtime = client.app.state.runtime
        runtime.provider_config = provider_config
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider_config, api_key="sk-test")
        runtime.provider_service_cache.clear()

        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "trainer-provider-recovery-resume",
                "profile": {
                    "long_term_goal": "Recover cleanly after provider setup failures",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        runtime.memory_service.record_recoverable_turn(
            workspace_id=workspace_id,
            session_id=session_id,
            user_message="请继续当前 debug 主线。",
            scenario="debug_loop",
            focus_area="launch diagnostics",
            summary="Provider path is blocked, but the saved debug lane is resumable.",
            next_step="Switch provider or gateway, then retry the same narrow probe.",
            blocker="Provider path is blocked by the configured key.",
            stop_reason="invalid_key_or_permission",
        )

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Explain one concrete verification step for the recovered training workflow.",
                "provider": PROVIDER_PAYLOAD,
                "api_key": "sk-test",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    active_thread = payload["snapshot"]["memory"]["active_thread"]
    assert active_thread["blocker"] == ""
    assert "Provider path is blocked" not in active_thread["summary"]
    assert "Switch provider or gateway" not in active_thread["next_step"]
    assert "gateway" not in active_thread["next_step"].lower()
    assert _contains_cjk(active_thread["summary"])
    assert _contains_cjk(active_thread["next_step"])
    assert "\\u" not in active_thread["summary"]
    assert "\\u" not in active_thread["next_step"]
    assert payload["snapshot"]["coaching_state"]["blocker"] == ""
    plan_runtime = payload["snapshot"]["plan_runtime_status"]
    assert plan_runtime["blocked_reason"] == ""
    assert "Provider path is blocked" not in json.dumps(plan_runtime, ensure_ascii=False)
    stored_active_thread = runtime.memory_service.snapshot(workspace_id).workspace["active_thread"]
    assert "recovery_state" not in stored_active_thread


def test_provider_recovery_fallback_texts_render_in_chinese_for_empty_saved_thread_state() -> None:
    summary = provider_recovery_resumed_summary_text("zh-CN")
    next_step = provider_recovery_resumed_next_step_text("general", "zh-CN")

    assert summary == "Provider 连接已恢复。继续当前学习主线，只完成一个小而可验证的动作。"
    assert next_step == "从最近的说明里选一个最小可验证动作，然后带着结果回来。"
    assert _contains_cjk(summary)
    assert _contains_cjk(next_step)
    assert "\\u" not in summary
    assert "\\u" not in next_step


def test_camel_case_response_language_localizes_session_language_fallback(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-camel-session-language"
    provider_config = ProviderConfig.model_validate(PROVIDER_PAYLOAD)

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "test",
            autospec=True,
            return_value=_language_corruption_failure(),
        ),
    ):
        runtime = client.app.state.runtime
        runtime.provider_config = provider_config
        runtime.provider_api_key = "sk-test"
        runtime.provider_service_cache.clear()
        session_id = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "trainer-camel-session-language",
            },
        ).json()["session_id"]

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Explain the VS Code remote workspace boundary first.",
                "provider": PROVIDER_PAYLOAD,
                "api_key": "sk-test",
                "responseLanguage": "zh-CN",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_meta"]["stop_reason"] == "language_corruption"
    assert payload["reply"]["metadata"]["response_language"] == "zh-CN"
    assert _contains_cjk(payload["reply"]["content"])
    assert _contains_cjk(payload["coach_turn"]["summary"])
    assert _contains_cjk(payload["coach_turn"]["next_step"])
    assert _contains_cjk(payload["coach_turn"]["resume_thread"])


def test_camel_case_response_language_localizes_turn_stream_language_fallback(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-camel-turn-stream-language"
    provider_config = ProviderConfig.model_validate(PROVIDER_PAYLOAD)

    async def corrupted_stream(*_args: object, **_kwargs: object):
        yield "Glad you want to start with VS Code remote \u0431\u043a and continue confi\u0431\u043d."

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "test",
            autospec=True,
            side_effect=AssertionError("streaming must not block on a language preflight"),
        ) as test_mock,
        patch.object(ProviderService, "coaching_reply_stream", new=corrupted_stream),
    ):
        runtime = client.app.state.runtime
        runtime.provider_config = provider_config
        runtime.provider_api_key = "sk-test"
        runtime.provider_service_cache.clear()
        request_service = runtime.provider_service_for(provider_config, "sk-test")
        request_provider = request_service._config
        seed_verified_capabilities(runtime, request_provider, "sk-test", tools=False)
        session_id = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "trainer-camel-turn-stream-language",
            },
        ).json()["session_id"]

        response = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Explain the VS Code remote workspace boundary first.",
                "provider": {
                    **PROVIDER_PAYLOAD,
                    "capabilities": {"tools": False, "streaming": True},
                },
                "api_key": "sk-test",
                "responseLanguage": "zh-CN",
            },
        )

    assert response.status_code == 200
    complete_line = [
        line for line in response.text.splitlines() if line.startswith('data: {"tokens":')
    ][-1]
    payload = json.loads(complete_line[len("data: ") :])["response"]
    assert test_mock.call_count == 0
    assert payload["agent_meta"]["stop_reason"] == "language_corruption_recovered"
    assert payload["reply"]["metadata"]["response_language"] == "zh-CN"
    assert _contains_cjk(payload["reply"]["content"])
    assert _contains_cjk(payload["coach_turn"]["summary"])
    assert _contains_cjk(payload["coach_turn"]["next_step"])
    assert _contains_cjk(payload["coach_turn"]["resume_thread"])
