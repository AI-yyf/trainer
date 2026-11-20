"""Stage 2 teaching latency & conversation productivity tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.models import (
    ChatMessage,
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderTestResponse,
    UserProfile,
)
from app.core.settings import AppSettings
from app.llm.prompts import build_coaching_system_prompt
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.pedagogy.productivity import assess_conversation_productivity


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Latency Budget Test",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="latency-budget.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _build_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(_settings(tmp_path)))


def test_minimal_prompt_shrinks_by_more_than_half_while_preserving_boundaries() -> None:
    profile = UserProfile(
        long_term_goal="Master idempotent HTTP handlers",
        background="Backend engineer",
        weekly_hours=5,
        teaching_style="guided",
        answer_policy="guided",
        target_project="payments-api",
        preferred_libraries=["fastapi", "pytest"],
    )
    full_prompt = build_coaching_system_prompt(
        profile,
        message="为什么幂等键不能只放在内存 dict 里？",
        response_language="zh-CN",
    )
    minimal_prompt = build_coaching_system_prompt(
        profile,
        message="为什么幂等键不能只放在内存 dict 里？",
        response_language="zh-CN",
        coach_context={"context_tier": "minimal"},
    )
    lecture_prompt = build_coaching_system_prompt(
        profile,
        message="讲明白幂等键为什么不能只放内存里，并推导它的状态机。",
        response_language="zh-CN",
        coach_context={"context_tier": "minimal"},
    )
    return_prompt = build_coaching_system_prompt(
        profile,
        message="请评估这次复盘",
        response_language="zh-CN",
        coach_context={
            "context_tier": "minimal",
            "completed_training_return_feedback": True,
        },
    )

    assert len(minimal_prompt) < len(full_prompt) * 0.5
    assert "Master idempotent HTTP handlers" in minimal_prompt
    assert "leave the learner's project files for the learner to author" in minimal_prompt
    assert "Simplified Chinese" in minimal_prompt or "中文" in minimal_prompt
    assert "State-Driven Teaching (RethinkFun)" in lecture_prompt
    assert "current server-controlled evidence" in return_prompt


def test_language_integrity_cache_shares_across_services_and_isolates_runtimes(tmp_path: Path) -> None:
    config_a = ProviderConfig(
        name="mini-max",
        base_url="https://example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
    )
    # Same transport signature with extra request defaults should share the bucket.
    config_b = ProviderConfig.model_validate(
        {
            "name": "mini-max-copy",
            "baseUrl": "https://example.com/v1/",
            "apiKeyRef": "trainer.other",
            "model": "MiniMax-M3",
            "requestDefaults": {"extra_body": {"thinking": {"type": "disabled"}}},
        }
    )
    with (
        _build_client(tmp_path / "rt-a") as client_a,
        _build_client(tmp_path / "rt-b") as client_b,
    ):
        runtime_a = client_a.app.state.runtime
        runtime_b = client_b.app.state.runtime

        svc_a1 = runtime_a.provider_service_for(config_a, "sk-shared")
        svc_a2 = runtime_a.provider_service_for(config_b, "sk-shared")
        svc_b = runtime_b.provider_service_for(config_a, "sk-shared")

        svc_a1.mark_language_integrity_success(
            message="解释一下幂等重试。",
            response_language="zh-CN",
        )
        assert svc_a2.has_recent_language_integrity_success(
            message="再举个例子",
            response_language="zh-CN",
        )
        # Runtime isolation prevents cross-runtime state leaks.
        assert not svc_b.has_recent_language_integrity_success(
            message="再举个例子",
            response_language="zh-CN",
        )

        # Failed provider probe invalidates the shared transport bucket immediately.
        runtime_a.remember_provider_capability_test(
            config_a,
            "sk-shared",
            ProviderTestResponse(
                ok=False,
                detail="language corruption",
                error_category="language_corruption",
                provider_reachable=True,
                model_supported=True,
                status_code=200,
            ),
        )
        assert not svc_a2.has_recent_language_integrity_success(
            message="再举个例子",
            response_language="zh-CN",
        )


def test_turn_stream_overhead_under_budget_without_extra_preflight(tmp_path: Path) -> None:
    provider_payload = {
        "name": "fast-coach",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.fast",
        "model": "MiniMax-M3",
        "capabilities": {"streaming": True, "tools": False},
    }
    provider_config = ProviderConfig.model_validate(provider_payload)

    async def fast_stream(*_args: object, **_kwargs: object):
        yield "幂等键让重试不会重复入账。"

    with (
        _build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "test",
            autospec=True,
            side_effect=AssertionError("preflight test() should not run on verified transport"),
        ),
        patch.object(
            ProviderService,
            "coaching_reply_stream",
            side_effect=fast_stream,
        ),
    ):
        runtime = client.app.state.runtime
        runtime.provider_config = provider_config
        runtime.provider_api_key = "sk-fast"
        runtime.remember_provider_capability_test(
            provider_config,
            "sk-fast",
            ProviderTestResponse(
                ok=True,
                detail="ok",
                provider_reachable=True,
                model_supported=True,
                status_code=200,
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    )
                ],
            ),
        )
        runtime.provider_service_for(provider_config, "sk-fast").mark_language_integrity_success(
            response_language="zh-CN"
        )

        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "ws-fast-stream",
                "workspace_name": "Fast Stream",
                "profile": {"long_term_goal": "Idempotency"},
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        started = monotonic()
        stream_response = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": "ws-fast-stream",
                "message": "幂等键怎么防重入？",
                "intent": "coach",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-fast",
            },
        )
        elapsed_ms = (monotonic() - started) * 1000.0

    assert stream_response.status_code == 200, stream_response.text
    assert elapsed_ms < 500.0
    import json

    chunks = [
        json.loads(line[6:]).get("chunk", "")
        for line in stream_response.text.splitlines()
        if line.startswith("data: ") and '"chunk"' in line
    ]
    assert "幂等键让重试不会重复入账。" in "".join(chunks)
    assert "event: complete" in stream_response.text


def _msg(role: str, content: str, metadata: dict | None = None, created_at: str | None = None) -> ChatMessage:
    return ChatMessage(
        id=f"msg-{abs(hash((role, content, str(metadata)))) % 100000}",
        role=role,  # type: ignore[arg-type]
        content=content,
        created_at=created_at or datetime.now(UTC).isoformat(),
        metadata=metadata or {},
    )


def test_productivity_convergence_tracks_streak_resets_and_exempts_direct_answer() -> None:
    turn1 = [_msg("user", "解释重试"), _msg("assistant", "说明1")]
    assert not assess_conversation_productivity(messages=turn1).should_converge

    turn2 = [*turn1, _msg("user", "为什么？"), _msg("assistant", "说明2")]
    converged = assess_conversation_productivity(messages=turn2)
    assert converged.should_converge is True
    assert converged.consecutive_unproductive_turns == 2
    assert converged.reason == "converge_to_attempt_or_review"

    # Prompt receives the convergence block in guided mode, never in direct mode.
    profile = UserProfile(answer_policy="guided")
    guided_prompt = build_coaching_system_prompt(
        profile,
        message="还有呢？",
        coach_context={"productivity_convergence": converged.to_payload()},
    )
    direct_prompt = build_coaching_system_prompt(
        profile,
        message="直接告诉我",
        answer_mode="direct",
        coach_context={"productivity_convergence": converged.to_payload()},
    )
    assert "Conversation Productivity Convergence" in guided_prompt
    assert "Conversation Productivity Convergence" not in direct_prompt

    # Direct answer mode itself never triggers convergence.
    assert assess_conversation_productivity(
        messages=turn2,
        turn_mode="direct_answer",
    ).reason == "direct_answer_exempt"

    # Attempting a practice card or scheduling review resets the counter.
    reset_messages = [
        *turn2,
        _msg("user", "提交练习", {"attempt_id": "att-1"}),
        _msg("assistant", "继续讨论新问题"),
    ]
    after_reset = assess_conversation_productivity(messages=reset_messages)
    assert after_reset.should_converge is False
    assert after_reset.consecutive_unproductive_turns == 1

    ledger_reset = assess_conversation_productivity(
        messages=turn2,
        has_recent_attempt_or_evidence=True,
    )
    assert ledger_reset.should_converge is False
    assert ledger_reset.reason == "recent_learning_output"

    # Non-trivial prompt path through build_coaching_system_prompt for turn 3 integration.
    no_convergence_prompt = build_coaching_system_prompt(
        profile,
        message="继续讲讲",
        coach_context={"context_tier": "minimal"},
    )
    assert "Conversation Productivity Convergence" not in no_convergence_prompt
