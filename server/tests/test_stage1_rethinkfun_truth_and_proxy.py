"""Stage 1 behavior tests: RethinkFun kernel, inspect_learning_truth, save_lecture_note, and proxy control."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import (
    GoalSession,
    LearningPlan,
    PlanStage,
    ProviderConfig,
    UserProfile,
)
from app.core.settings import AppSettings
from app.llm.agent_binding import ProviderAgentBinding
from app.llm.agent_tool_context import _stamp_explicit_write_tool_flags
from app.llm.prompts import build_coaching_system_prompt
from app.llm.provider_service import ProviderService
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Stage1 Test",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="stage1.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def test_rethinkfun_prompt_covers_minimal_lecture_and_reasoning_review() -> None:
    profile = UserProfile(long_term_goal="Understand idempotency and KL divergence")

    minimal = build_coaching_system_prompt(
        profile,
        message="with 退出时会释放锁吗？",
        response_language="zh-CN",
        coach_context={"context_tier": "minimal"},
    )
    assert "大家都知道" in minimal
    assert "state, failure, or gap" in minimal

    lecture = build_coaching_system_prompt(
        profile,
        message="帮我讲明白 KL 散度为什么只能长这样，并给最小代码示例。",
        response_language="zh-CN",
        agent_loop_enabled=True,
    )
    assert "State-Driven Teaching (RethinkFun)" in lecture
    assert "4-feeling end bar" in lecture
    assert "inspect_learning_truth" in lecture
    assert "save_lecture_note" in lecture
    assert "代入即得" in lecture
    assert "希望对你有帮助" in lecture

    review = build_coaching_system_prompt(
        profile,
        message="开始复习幂等键",
        response_language="zh-CN",
        coach_context={"scenario": "review"},
    )
    assert "reasoning-based review check" in review
    assert "reconstruct the invariant" in review


def test_inspect_learning_truth_and_save_lecture_note_zero_code_repo_pollution(tmp_path: Path) -> None:
    library_root = tmp_path / "library-root"
    code_repo = tmp_path / "code-repo"
    library_root.mkdir()
    code_repo.mkdir()
    (code_repo / "payments.py").write_text("def retry():\n    return True\n", encoding="utf-8")

    with TestClient(create_app(_settings(library_root / ".trainer" / "runtime"))) as client:
        runtime = client.app.state.runtime
        ws_id = "ws-stage1-truth"
        runtime.register_workspace_path(ws_id, str(code_repo))
        runtime.resource_service.set_library_root_resolver(lambda _ws: library_root)

        plan = LearningPlan(
            id="plan-1",
            title="Idempotency Mastery",
            summary="Master idempotent retry handling",
            current_stage_id="stage-2",
            next_step="Guard duplicate writes in retry()",
            stages=[
                PlanStage(id="stage-1", title="Failure Mode", goal="Reproduce duplicate charge", outcomes=["Show duplicate ledger entry"], status="completed"),
                PlanStage(id="stage-2", title="Key Guard", goal="Add idempotency key check", outcomes=["Reject duplicate request key"], status="active"),
                PlanStage(id="stage-3", title="Concurrent Race", goal="Handle concurrent duplicates", outcomes=["Atomic lock or unique constraint"], status="pending"),
            ],
        )
        runtime.repository.save_plan(ws_id, plan)
        runtime.repository.save_goal(
            ws_id,
            GoalSession(goal_id="goal-1", title="Prevent duplicate writes in retry()", status="active"),
        )

        registry = build_default_tool_registry()
        truth_ctx = ToolContext(
            runtime=runtime,
            workspace_id=ws_id,
            response_language="zh-CN",
            extra={"allow_coach_only_tools": True, "learner_message": "我的完整学习路线和证据有哪些？"},
        )
        truth = asyncio.run(registry.invoke(truth_ctx, "inspect_learning_truth", {"section": "all"}))
        assert truth["ok"] is True
        assert truth["active_goal"]["title"] == "Prevent duplicate writes in retry()"
        assert truth["plan"]["summary"]["completed_stage_count"] == 1
        assert truth["plan"]["summary"]["completed_stages"][0]["title"] == "Failure Mode"
        assert truth["plan"]["summary"]["upcoming_stages"][0]["title"] == "Concurrent Race"
        assert isinstance(truth.get("evidence_records"), list)

        # Normal turn cannot silently save a lecture note.
        normal_extra: dict[str, object] = {"allow_coach_only_tools": True, "learner_message": "讲明白幂等性"}
        _stamp_explicit_write_tool_flags(normal_extra, coach_context=None, learner_message="讲明白幂等性")
        denied_ctx = ToolContext(
            runtime=runtime,
            workspace_id=ws_id,
            response_language="zh-CN",
            extra=normal_extra,
        )
        denied = asyncio.run(
            registry.invoke(
                denied_ctx,
                "save_lecture_note",
                {"title": "幂等性讲稿", "markdown_content": "# 幂等性\n\n内容"},
            )
        )
        assert denied["ok"] is False

        # Explicit save request persists canonical .md strictly under <LibraryRoot>, zero code-repo writes.
        save_msg = "把刚才讲透的幂等性整理成笔记存进资料库"
        save_extra: dict[str, object] = {"allow_coach_only_tools": True, "learner_message": save_msg}
        _stamp_explicit_write_tool_flags(save_extra, coach_context=None, learner_message=save_msg)
        save_ctx = ToolContext(
            runtime=runtime,
            workspace_id=ws_id,
            response_language="zh-CN",
            extra=save_extra,
        )
        saved = asyncio.run(
            registry.invoke(
                save_ctx,
                "save_lecture_note",
                {
                    "title": "幂等性状态流讲稿",
                    "markdown_content": "先看旧办法为什么会重复扣款，再构造幂等键对象。",
                },
            )
        )
        assert saved["ok"] is True, saved
        assert saved["stored_under_library_root"] is True
        assert saved["name"].endswith(".md")
        assert sorted(p.name for p in code_repo.iterdir()) == ["payments.py"]


def test_ignore_system_proxy_bypasses_trust_env_and_surfaces_proxy_hint(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://secret-user:secret-pass@127.0.0.1:29290")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)

    proxied_config = ProviderConfig.model_validate(
        {
            "name": "remote-relay",
            "baseUrl": "https://relay.example.com/v1",
            "apiKeyRef": "trainer.remote",
            "model": "MiniMax-M2.7",
            "ignoreSystemProxy": False,
        }
    )
    direct_config = ProviderConfig.model_validate(
        {
            "name": "remote-relay",
            "baseUrl": "https://relay.example.com/v1",
            "apiKeyRef": "trainer.remote",
            "model": "MiniMax-M2.7",
            "ignoreSystemProxy": True,
        }
    )

    svc_proxied = ProviderService(proxied_config, api_key="sk-test")
    svc_direct = ProviderService(direct_config, api_key="sk-test")

    assert svc_proxied._should_bypass_system_proxy() is False
    assert svc_direct._should_bypass_system_proxy() is True

    binding_direct = ProviderAgentBinding(
        provider_service=svc_direct,
        protocol="openai_chat_completions_compatible",
    )
    assert binding_direct._should_bypass_system_proxy() is True

    detail_zh = svc_proxied._detail_from_category(
        "network",
        provider=proxied_config,
        error=RuntimeError("502 Bad Gateway"),
        response_language="zh-CN",
    )
    assert "HTTP_PROXY" in detail_zh
    assert "忽略系统代理" in detail_zh
    assert "secret-pass" not in detail_zh
    assert "29290" not in detail_zh

    detail_direct = svc_direct._detail_from_category(
        "network",
        provider=direct_config,
        error=RuntimeError("connection refused"),
        response_language="zh-CN",
    )
    assert "忽略系统代理" not in detail_direct


def test_english_system_prompt_contains_no_cjk_characters() -> None:
    import re

    profile = UserProfile(long_term_goal="Understand attention scaling")
    for context in ({"context_tier": "minimal"}, {}):
        prompt = build_coaching_system_prompt(
            profile,
            message="Explain why scaled dot-product attention divides by sqrt(d_k).",
            response_language="en-US",
            coach_context=context,
            agent_loop_enabled=True,
        )
        assert not re.search(r"[\u3400-\u9fff]", prompt)


def test_rethinkfun_deep_lecture_grants_generous_output_token_budget() -> None:
    standard_cfg = ProviderConfig.model_validate(
        {
            "name": "std",
            "baseUrl": "https://api.example.com/v1",
            "apiKeyRef": "trainer.std",
            "model": "gpt-4.1-mini",
        }
    )
    minimax_cfg = ProviderConfig.model_validate(
        {
            "name": "mm",
            "baseUrl": "https://api.example.com/v1",
            "apiKeyRef": "trainer.mm",
            "model": "MiniMax-M2.7",
        }
    )
    std_svc = ProviderService(standard_cfg, api_key="sk-test")
    mm_svc = ProviderService(minimax_cfg, api_key="sk-test")

    # Fast Q&A stays on the compact default budget (None -> 1024).
    assert std_svc._coaching_requested_output_tokens("with 退出时会释放锁吗？") is None
    assert mm_svc._coaching_requested_output_tokens("with 退出时会释放锁吗？") is None

    # Deep RethinkFun lecture grants headroom so reasoning + derivation + code never truncates.
    lecture_prompt = "请用状态流方式彻底讲明白 Scaled Dot-Product Attention 的公式推导与代码实现"
    assert std_svc._coaching_requested_output_tokens(lecture_prompt) == 4096
    assert mm_svc._coaching_requested_output_tokens(lecture_prompt) == 8192
    assert mm_svc._coaching_requested_output_tokens("帮我核查掌握进度的具体证据", agent_loop_enabled=True) == 4096

    from app.api.router_support import _message_requests_single_composer_truth_or_note

    assert _message_requests_single_composer_truth_or_note("帮我核查完整学习计划阶段和掌握进度的具体验证证据") is True
    assert _message_requests_single_composer_truth_or_note("请把讲稿保存成我资料库里的 Markdown 笔记") is True
    assert _message_requests_single_composer_truth_or_note("with 退出时会释放锁吗？") is False
