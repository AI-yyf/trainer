"""Stage 3 budgeted proactivity, weakness diagnostic cue, and plan-proposal gate tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.models import (
    LearningPlan,
    PlanStage,
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderTestResponse,
    UserProfile,
)
from app.core.settings import AppSettings
from app.llm.prompts import build_coaching_system_prompt
from app.llm.provider_service import ProviderService
from app.llm.tools import ToolContext, _handle_save_formal_plan
from app.main import create_app
from app.memory.proactive_budget import (
    DAILY_PROACTIVE_BUDGET,
    MIN_NUDGE_SPACING_MINUTES,
    evaluate_proactive_opportunity,
    match_diagnostic_to_weakness,
    record_proactive_nudge,
)
from app.memory.review_intervention import derive_review_budget


def _build_client(trainer_root: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Proactive Budget Test",
        host="127.0.0.1",
        port=8765,
        data_dir=trainer_root / ".trainer" / "runtime",
        database_name="proactive-budget.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_proactive_whisper_enforces_daily_budget_spacing_dedup_and_typing_guard() -> None:
    base = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    weaknesses = ["idempotency: forgot conflict handling on replay"]

    typing_blocked = evaluate_proactive_opportunity(
        {},
        now=base,
        diagnostics=["KeyError: idempotency key not handled in replay handler"],
        weaknesses=weaknesses,
        response_language="zh-CN",
        learner_actively_typing=True,
    )
    assert typing_blocked.should_nudge is False
    assert typing_blocked.reason == "learner_typing"

    review_typing_blocked = derive_review_budget(
        {},
        due_count=2,
        now=base,
        learner_actively_typing=True,
    )
    assert review_typing_blocked.allowed is False
    assert review_typing_blocked.reason == "learner_typing"

    # Info-level diagnostics stay quiet even when idle.
    info_only = evaluate_proactive_opportunity(
        {},
        now=base,
        diagnostics=[{"severity": "info", "message": "idempotency docstring note"}],
        weaknesses=weaknesses,
        response_language="en",
    )
    assert info_only.should_nudge is False
    assert info_only.reason == "no_nudge_candidate"

    first = evaluate_proactive_opportunity(
        {},
        now=base,
        diagnostics=["TypeError: idempotency conflict check returns wrong status"],
        weaknesses=weaknesses,
        due_reviews=[{"concept": "retry-backoff"}],
        due_count=1,
        response_language="zh-CN",
    )
    assert first.should_nudge is True
    assert first.kind == "diagnostic_weakness"
    assert first.remaining_daily_budget == DAILY_PROACTIVE_BUDGET - 1

    budget_state = record_proactive_nudge(
        None,
        now=base,
        kind=first.kind,
        dedup_key=first.dedup_key,
        session_id="sess-1",
    )

    # Inside the 45-minute spacing window, another nudge is blocked.
    too_soon = evaluate_proactive_opportunity(
        {"proactive_budget": budget_state},
        now=base + timedelta(minutes=MIN_NUDGE_SPACING_MINUTES - 5),
        diagnostics=["TypeError: idempotency conflict check returns wrong status"],
        weaknesses=weaknesses,
        due_reviews=[{"concept": "retry-backoff"}],
        due_count=1,
        response_language="zh-CN",
    )
    assert too_soon.should_nudge is False
    assert too_soon.reason == "nudge_spacing_cooldown"

    # After cooldown, the same diagnostic weakness is deduplicated for today, while a
    # distinct review item uses the second (and final) daily slot.
    t2 = base + timedelta(minutes=MIN_NUDGE_SPACING_MINUTES + 1)
    same_diag_only = evaluate_proactive_opportunity(
        {"proactive_budget": budget_state},
        now=t2,
        diagnostics=["TypeError: idempotency conflict check returns wrong status"],
        weaknesses=weaknesses,
        due_reviews=[],
        due_count=0,
        response_language="zh-CN",
    )
    assert same_diag_only.should_nudge is False
    assert same_diag_only.reason == "already_nudged_today"

    second = evaluate_proactive_opportunity(
        {"proactive_budget": budget_state},
        now=t2,
        diagnostics=["TypeError: idempotency conflict check returns wrong status"],
        weaknesses=weaknesses,
        due_reviews=[{"concept": "retry-backoff"}],
        due_count=1,
        response_language="zh-CN",
    )
    assert second.should_nudge is True
    assert second.kind == "review_gap"
    assert second.remaining_daily_budget == 0

    budget_state = record_proactive_nudge(
        budget_state,
        now=t2,
        kind=second.kind,
        dedup_key=second.dedup_key,
        session_id="sess-1",
    )

    # Third nudge on the same day is strictly blocked by the daily cap.
    third = evaluate_proactive_opportunity(
        {"proactive_budget": budget_state},
        now=t2 + timedelta(hours=3),
        diagnostics=["KeyError: another idempotency error"],
        weaknesses=["backoff: jitter formula"],
        due_reviews=[{"concept": "lock-lease"}],
        due_count=1,
        response_language="zh-CN",
    )
    assert third.should_nudge is False
    assert third.reason == "daily_budget_exhausted"
    assert third.remaining_daily_budget == 0

    # Next UTC day rolls over the daily budget and clears yesterday's dedup keys.
    next_day = evaluate_proactive_opportunity(
        {"proactive_budget": budget_state},
        now=base + timedelta(days=1),
        diagnostics=["TypeError: idempotency conflict check returns wrong status"],
        weaknesses=weaknesses,
        response_language="en",
    )
    assert next_day.should_nudge is True
    assert next_day.kind == "diagnostic_weakness"
    assert next_day.remaining_daily_budget == DAILY_PROACTIVE_BUDGET - 1


def test_proactive_evaluate_endpoint_and_coach_weakness_diagnostic_cue(tmp_path: Path) -> None:
    trainer_root = tmp_path / "library-root"
    trainer_root.mkdir(parents=True)

    with _build_client(trainer_root) as client:
        runtime = client.app.state.runtime
        started = client.post(
            "/session/start",
            json={"workspace_id": "ws-proactive", "workspace_name": "Proactive Repo"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        structured = runtime.memory_service.structured_for_workspace("ws-proactive")
        structured.record_weakness(
            "idempotency",
            "forgot idempotent replay status check on conflict",
            severity=2,
            review_after_days=1,
        )
        runtime.memory_service._persist_structured("ws-proactive")
        assert runtime.memory_service.weaknesses("ws-proactive")

        t0 = "2026-11-20T10:00:00Z"
        blocked_typing = client.post(
            "/proactive/evaluate",
            json={
                "session_id": session_id,
                "workspace_id": "ws-proactive",
                "diagnostics": ["AssertionError: idempotency key replay returned 500"],
                "learner_actively_typing": True,
                "record": True,
                "now": t0,
            },
        )
        assert blocked_typing.status_code == 200, blocked_typing.text
        assert blocked_typing.json()["should_nudge"] is False
        assert blocked_typing.json()["reason"] == "learner_typing"

        nudge = client.post(
            "/proactive/evaluate",
            json={
                "session_id": session_id,
                "workspace_id": "ws-proactive",
                "diagnostics": ["AssertionError: idempotency key replay returned 500"],
                "learner_actively_typing": False,
                "record": True,
                "now": t0,
            },
        )
        assert nudge.status_code == 200, nudge.text
        nudge_body = nudge.json()
        assert nudge_body["should_nudge"] is True
        assert nudge_body["kind"] == "diagnostic_weakness"
        assert nudge_body["concept"] == "idempotency"
        assert nudge_body["remaining_daily_budget"] == 1

        # Busy/refusal signal suppresses nudges even after cooldown.
        busy = client.post(
            "/proactive/evaluate",
            json={
                "session_id": session_id,
                "workspace_id": "ws-proactive",
                "diagnostics": ["AssertionError: idempotency key replay returned 500"],
                "message": "先跳过，别复习，我现在正忙",
                "now": "2026-11-20T12:00:00Z",
            },
        )
        assert busy.status_code == 200
        assert busy.json()["should_nudge"] is False
        assert busy.json()["reason"] == "message_refusal"

        # Coach turn context surfaces Weakness Recall Cue when current_file has a matching diagnostic,
        # stays silent in minimal context tier (no current_file), and is suppressed in direct-answer mode.
        hit = match_diagnostic_to_weakness(
            ["AssertionError: idempotency replay status mismatch"],
            runtime.memory_service.weakness_records("ws-proactive"),
        )
        assert hit is not None
        assert hit[0] == "idempotency"

        provider_payload = {
            "name": "proactive-coach",
            "baseUrl": "https://example.com/v1",
            "apiKeyRef": "trainer.proactive",
            "model": "MiniMax-M3",
            "capabilities": {"streaming": True, "tools": False},
        }
        provider_config = ProviderConfig.model_validate(provider_payload)
        runtime.provider_config = provider_config
        runtime.provider_api_key = "sk-proactive"
        runtime.remember_provider_capability_test(
            provider_config,
            "sk-proactive",
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
        runtime.provider_service_for(provider_config, "sk-proactive").mark_language_integrity_success(
            response_language="zh-CN"
        )

        captured_contexts: list[dict] = []

        async def fake_stream(
            _self: ProviderService,
            _profile: UserProfile | None,
            _message: str,
            current_file: dict | None = None,
            response_language: str | None = None,
            answer_mode: str | None = None,
            coach_context: dict | None = None,
            **_kwargs: object,
        ):
            captured_contexts.append(dict(coach_context or {}))
            yield "先检查这一行幂等键的冲突状态码。"

        with patch.object(ProviderService, "coaching_reply_stream", fake_stream):
            full_resp = client.post(
                "/turn/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": "ws-proactive",
                    "message": "这一行测试为什么没过？",
                    "intent": "coach",
                    "response_language": "zh-CN",
                    "provider": provider_payload,
                    "api_key": "sk-proactive",
                    "current_file": {
                        "path": "handlers.py",
                        "language_id": "python",
                        "content": "def handle(): pass\n",
                        "diagnostics": ["AssertionError: idempotency replay status mismatch"],
                    },
                },
            )
            assert full_resp.status_code == 200, full_resp.text

            minimal_resp = client.post(
                "/turn/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": "ws-proactive",
                    "message": "用一句话总结幂等键的作用",
                    "intent": "coach",
                    "response_language": "zh-CN",
                    "provider": provider_payload,
                    "api_key": "sk-proactive",
                },
            )
            assert minimal_resp.status_code == 200, minimal_resp.text

        assert len(captured_contexts) == 2
        full_ctx, minimal_ctx = captured_contexts
        assert full_ctx["diagnostic_weakness_hint"]["concept"] == "idempotency"
        assert minimal_ctx.get("context_tier") == "minimal"
        assert "diagnostic_weakness_hint" not in minimal_ctx

        profile = UserProfile(
            long_term_goal="Build idempotent APIs",
            background="Backend dev",
            weekly_hours=4,
            teaching_style="guided",
            answer_policy="guided",
        )
        guided_prompt = build_coaching_system_prompt(
            profile,
            message="这一行测试为什么没过？",
            coach_context=full_ctx,
        )
        assert "## Weakness Recall Cue" in guided_prompt
        assert "idempotency" in guided_prompt

        direct_prompt = build_coaching_system_prompt(
            profile,
            message="直接告诉我写法",
            answer_mode="direct",
            coach_context=full_ctx,
        )
        assert "## Weakness Recall Cue" not in direct_prompt


async def test_plan_change_proposals_stay_pending_until_explicit_ack_or_reject(tmp_path: Path) -> None:
    trainer_root = tmp_path / "library-root"
    trainer_root.mkdir(parents=True)

    with _build_client(trainer_root) as client:
        runtime = client.app.state.runtime
        started = client.post(
            "/session/start",
            json={"workspace_id": "ws-plan-gate", "workspace_name": "Plan Gate Repo"},
        )
        assert started.status_code == 200
        session_id = started.json()["session_id"]

        plan = LearningPlan(
            id="plan-idempotency",
            title="Idempotent request handlers",
            summary="Handle duplicate requests safely",
            current_stage_id="stage-1",
            current_step="Verify replay conflict status",
            verify_method=["pytest"],
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Replay Safety",
                    goal="Handle replay conflict status",
                    outcomes=["Return deterministic replay status"],
                    status="active",
                )
            ],
        )
        runtime.repository.save_plan("ws-plan-gate", plan)

        blocked_tool = await _handle_save_formal_plan(
            ToolContext(
                runtime=runtime,
                workspace_id="ws-plan-gate",
                session_id=session_id,
                extra={"formal_plan_mutation": False},
            ),
            {"goal": "Rewrite plan silently"},
        )
        assert blocked_tool["ok"] is False
        assert blocked_tool["error"] == "formal_plan_mutation_required"

        feedback = client.post(
            "/memory/feedback",
            json={
                "session_id": session_id,
                "workspace_id": "ws-plan-gate",
                "kind": "plan_mismatch",
                "message": "先跳过并发锁，专注幂等键存储",
                "focus_area": "idempotency",
            },
        )
        assert feedback.status_code == 200, feedback.text
        memory_payload = feedback.json()["memory"]
        candidates = memory_payload.get("planChangeCandidates") or memory_payload.get(
            "plan_change_candidates"
        )
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate["status"] == "pending"
        assert candidate["impact"]["formal_plan_changed"] is False
        latest_plan = runtime.repository.get_latest_plan("ws-plan-gate")
        assert latest_plan is not None
        assert latest_plan.title == "Idempotent request handlers"

        acked = client.post(
            f"/plan/change-candidates/{candidate['id']}/ack",
            json={"workspace_id": "ws-plan-gate", "note": "确认记录调整建议"},
        )
        assert acked.status_code == 200
        assert acked.json()["status"] == "acknowledged"
