"""Stage 1 behavior tests: RethinkFun kernel, inspect_learning_truth, save_lecture_note, and proxy control."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
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
        assert saved["folder"] == "学习讲稿"
        assert saved["saved_path"] == "Trainer Library/学习讲稿/幂等性状态流讲稿.md"
        assert "resource_id" not in saved
        assert (library_root / "Trainer Library" / "学习讲稿" / "幂等性状态流讲稿.md").is_file()
        assert sorted(p.name for p in code_repo.iterdir()) == ["payments.py"]

        # Verify GET /library/groups sees the saved lecture note in "学习讲稿".
        groups_resp = client.get("/library/groups", params={"workspace_id": ws_id})
        assert groups_resp.status_code == 200, groups_resp.text
        groups_payload = groups_resp.json()
        assert groups_payload["total_resource_count"] >= 1
        assert any(
            g["path"] == "学习讲稿" and g["resource_count"] >= 1
            for g in groups_payload["groups"]
        )

        # Verify inspect_learning_truth hides raw IDs and internal telemetry enum codes.
        import json as _json

        truth_dumped = _json.dumps(truth, ensure_ascii=False)
        assert "goal-1" not in truth_dumped
        assert "plan-1" not in truth_dumped
        assert "stage-1" not in truth_dumped
        assert "insufficient_evidence" not in truth_dumped
        assert "no_recall_evidence" not in truth_dumped

        # Verify prose sanitizer strips leaked internal chunk anchors, IDs, and fixes guessed note paths.
        from app.llm.coaching_replies import (
            _strip_internal_coach_meta,
            enforce_truthful_saved_note_path,
        )

        dirty_prose = (
            "你的目标（goal-ca92fa8628a4）当前 evidence_records: []，处于 insufficient_evidence，"
            "复习状态为 no_recall_evidence。讲稿（resource-db2655504e，¶chunk:1@31）已保存在 "
            "`Trainer Library/wrong-guessed-name.md`。\n\n"
            "```python\n# code blocks must stay untouched\nx = 'insufficient_evidence ¶chunk:0@1'\n```"
        )
        cleaned_prose = _strip_internal_coach_meta(dirty_prose)
        cleaned_prose = enforce_truthful_saved_note_path(
            cleaned_prose,
            [
                {
                    "type": "tool_result",
                    "name": "save_lecture_note",
                    "result": {"ok": True, "saved_path": saved["saved_path"]},
                }
            ],
        )
        assert "goal-ca92fa8628a4" not in cleaned_prose
        assert "resource-db2655504e" not in cleaned_prose
        assert "insufficient_evidence" not in cleaned_prose.split("```")[0]
        assert "no_recall_evidence" not in cleaned_prose.split("```")[0]
        assert "¶chunk:" not in cleaned_prose.split("```")[0]
        assert saved["saved_path"] in cleaned_prose
        assert "Trainer Library/wrong-guessed-name.md" not in cleaned_prose
        assert "insufficient_evidence ¶chunk:0@1" in cleaned_prose.split("```python")[1]


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


def test_single_composer_truth_and_note_triggers_cover_all_eight_languages() -> None:
    from app.api.router_support import _message_requests_single_composer_truth_or_note
    from app.memory.note_request import message_requests_lecture_note_save

    truth_queries = [
        "给我看我的完整学习路线和掌握进度依据",
        "Show me all stages and mastery evidence",
        "Muéstrame las etapas completadas y la evidencia de dominio",
        "Montre-moi les étapes terminées et la preuve de maîtrise",
        "Zeige mir abgeschlossene Phasen und den Beherrschungsnachweis",
        "完了した段階と習得の根拠を教えてください",
        "완료한 단계와 숙달 근거를 보여줘",
        "Mostre as etapas concluídas e a evidência de domínio",
    ]
    for query in truth_queries:
        assert _message_requests_single_composer_truth_or_note(query) is True, query

    note_requests = [
        "把刚才的讲稿存进资料库",
        "Save this explanation as a lecture note to my library",
        "Guardar esta explicación como nota en recursos",
        "Enregistrer cette fiche dans les ressources",
        "Bitte als Notiz in Ressourcen speichern",
        "この解説をノートとして資料に保存して",
        "이 설명을 노트로 자료실에 저장해 줘",
        "Salvar esta explicação como nota em recursos",
    ]
    for req in note_requests:
        assert message_requests_lecture_note_save(req) is True, req
        assert _message_requests_single_composer_truth_or_note(req) is True, req

    for rejected in (
        "不要存进资料库",
        "Do not save this note to resources",
        "No guardes esta nota",
        "Bitte nicht speichern als Notiz",
        "ノートは保存しないで",
        "노트로 저장하지 마",
    ):
        assert message_requests_lecture_note_save(rejected) is False, rejected

    assert _message_requests_single_composer_truth_or_note("with 退出时会释放锁吗？") is False


def test_plan_generate_honors_goal_parameter_and_chinese_concepts(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path / "data"))) as client:
        runtime = client.app.state.runtime
        cfg = ProviderConfig.model_validate(
            {
                "name": "test-openai",
                "baseUrl": "https://api.example.com/v1",
                "apiKeyRef": "trainer.test",
                "model": "gpt-4.1-mini",
            }
        )
        runtime.provider_service = ProviderService(cfg, api_key="sk-test")
        from tests.provider_fixtures import seed_verified_capabilities

        seed_verified_capabilities(runtime, cfg, "sk-test")
        start = client.post(
            "/session/start",
            json={"workspace_id": "ws-plan-goal", "workspace_name": "Plan Goal"},
        )
        assert start.status_code == 200, start.text
        session_id = start.json()["session_id"]
        resp = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "goal": "掌握支付幂等键持久化与并发防重入",
                "response_language": "zh-CN",
            },
        )
        assert resp.status_code == 200, resp.text
        plan = resp.json()["plan"]
        text_dump = str(plan)
        assert "支付幂等键持久化" in text_dump or "并发防重入" in text_dump
        assert "problem framing" not in text_dump.lower()


def test_streamable_prefix_does_not_stall_on_fenced_code_blocks() -> None:
    from app.llm.coaching_replies import _streamable_visible_prefix

    chunks = [
        "<think>内部推演",
        "步骤</think>\n先看旧做法为什么卡住。\n",
        "```python\ndef check():\n",
        "    return 1\n```\n",
        "接着检验边界。",
    ]
    buf = ""
    emitted = ""
    deltas: list[str] = []
    for part in chunks:
        buf += part
        prefix = _streamable_visible_prefix(buf)
        if prefix and prefix.startswith(emitted):
            delta = prefix[len(emitted) :]
            if delta:
                emitted = prefix
                deltas.append(delta)
    assert len(deltas) >= 3
    assert "```python" in emitted
    assert "def check():" in emitted
    assert "内部推演" not in emitted


def test_turn_stream_emits_reasoning_status_tool_intent_and_split_timings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import json as _json

    cfg = ProviderConfig.model_validate(
        {
            "name": "test-openai",
            "baseUrl": "https://api.example.com/v1",
            "apiKeyRef": "trainer.test",
            "model": "MiniMax-M2.7",
            "capabilities": {"tools": True, "streaming": True},
        }
    )

    class _StreamBinding:
        protocol = "openai_chat_completions"

        @staticmethod
        def attachments_will_be_sent() -> bool:
            return False

        async def call_stream(self, _messages, _tools):
            yield {"type": "provider_activity", "phase": "model_reasoning"}
            yield {"type": "provider_activity", "phase": "tool_drafting", "name": "inspect_learning_truth"}
            yield {"type": "delta", "delta": "状态流说明：\n", "safe_to_stream": True}
            yield {"type": "delta", "delta": "```python\nx = 1\n```\n", "safe_to_stream": True}
            yield {"type": "delta", "delta": "最后检查变量角色。", "safe_to_stream": True}
            yield {"type": "final", "content": "状态流说明：\n```python\nx = 1\n```\n最后检查变量角色。", "tool_calls": [], "stop_reason": "stop"}

        async def call(self, _messages, _tools):
            return {"content": "状态流说明", "tool_calls": [], "stop_reason": "stop"}

    monkeypatch.setattr(
        ProviderService,
        "build_agent_provider",
        lambda self, **kwargs: (_StreamBinding(), _StreamBinding()),
    )

    with TestClient(create_app(_settings(tmp_path / "data"))) as client:
        runtime = client.app.state.runtime
        runtime.provider_service = ProviderService(cfg, api_key="sk-test")
        from tests.provider_fixtures import seed_verified_capabilities

        seed_verified_capabilities(runtime, cfg, "sk-test")
        start = client.post(
            "/session/start",
            json={"workspace_id": "ws-stream-timings", "workspace_name": "Timings"},
        )
        assert start.status_code == 200
        session_id = start.json()["session_id"]

        resp = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": "ws-stream-timings",
                "intent": "coach",
                "message": "用状态流解释一个变量并给代码",
                "response_language": "zh-CN",
                "use_agent_loop": True,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.text
        statuses = []
        chunks = []
        complete = None
        for block in body.split("\n\n"):
            if not block.strip():
                continue
            ev = "message"
            data_str = ""
            for line in block.splitlines():
                if line.startswith("event:"):
                    ev = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_str += line.split(":", 1)[1].strip()
            if not data_str:
                continue
            parsed = _json.loads(data_str)
            if ev == "status":
                statuses.append(parsed)
            elif "chunk" in parsed:
                chunks.append(parsed["chunk"])
            elif ev == "complete":
                complete = parsed
        assert any(s.get("phase") == "model_reasoning" for s in statuses), statuses
        assert any(s.get("phase") == "tool_intent" and s.get("name") == "inspect_learning_truth" for s in statuses), statuses
        assert len(chunks) >= 2, chunks
        assert complete is not None
        timings = complete["response"].get("timings")
        assert isinstance(timings, dict)
        assert timings["local_prep_ms"] is not None
        assert timings["provider_first_event_ms"] is not None
        assert timings["visible_ttft_ms"] is not None
        assert timings["total_ms"] >= timings["visible_ttft_ms"]


@pytest.mark.asyncio
async def test_leaked_token_stripper_preserves_code_calls_and_emit_activity_is_opt_in() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.llm.agent_binding import ProviderAgentBinding
    from app.llm.coaching_replies import _strip_leaked_internal_prose_tokens

    sample = "`pop()` 和 `self._items.pop()` 不该掉括号；但 (resource-deadbeef, ¶chunk:12) 和 insufficient_evidence 要清洗。"
    cleaned = _strip_leaked_internal_prose_tokens(sample)
    assert "`pop()`" in cleaned
    assert "`self._items.pop()`" in cleaned
    assert "resource-deadbeef" not in cleaned
    assert "¶chunk:12" not in cleaned
    assert "insufficient_evidence" not in cleaned

    async def _stream_once():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="<think>step",
                        tool_calls=[],
                    ),
                    finish_reason=None,
                )
            ]
        )
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="</think>回答。",
                        tool_calls=[],
                    ),
                    finish_reason="stop",
                )
            ]
        )

    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="openai-compat",
            base_url="https://api.example/v1",
            model="MiniMax-M2.7",
            protocol="openai_chat_completions_compatible",
            request_defaults={},
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
        _get_client=MagicMock(
            return_value=SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(create=AsyncMock(side_effect=[_stream_once(), _stream_once()]))
                )
            )
        ),
        _apply_request_defaults=lambda payload: payload,
        _resolve_model=lambda: "MiniMax-M2.7",
        _model_candidates=lambda model: [model],
        _is_model_not_supported_error=lambda exc: False,
    )
    quiet = ProviderAgentBinding(provider_service=service, emit_activity=False).build_agent_provider()
    quiet_types = [e["type"] async for e in quiet.call_stream([{"role": "user", "content": "hi"}], None)]
    assert "provider_activity" not in quiet_types

    loud = ProviderAgentBinding(provider_service=service, emit_activity=True).build_agent_provider()
    loud_types = [e["type"] async for e in loud.call_stream([{"role": "user", "content": "hi"}], None)]
    assert "provider_activity" in loud_types


def test_save_lecture_note_schema_exposed_for_lecture_save_request_without_learning_note_flag() -> None:
    from types import SimpleNamespace
    from typing import Any, cast

    from app.llm.agent_loop import CoachAgentLoop
    from app.llm.agent_tool_context import _build_agent_tool_context_extra
    from app.llm.coaching_replies import enforce_truthful_saved_note_path

    registry = build_default_tool_registry()
    save_msg = "请讲明白注意力缩放，并且把这份成品讲稿保存成我资料库里的 Markdown 笔记。"
    for answer_mode in ("guided", "direct"):
        extra = _build_agent_tool_context_extra(
            coach_context=None,
            attachment_delivery={},
            answer_mode=answer_mode,
            current_file=None,
            learner_message=save_msg,
        )
        assert extra["explicit_lecture_note_save_request"] is True
        assert extra["explicit_learning_note_request"] is False
        assert "save_lecture_note" not in extra["denied_tool_names"]
        if answer_mode == "direct":
            assert extra["allow_coach_only_tools"] is False

        loop = CoachAgentLoop(
            provider=cast(Any, SimpleNamespace(protocol="openai_chat_completions_compatible")),
            registry=registry,
            context=ToolContext(
                workspace_id="ws-lecture-schema",
                session_id="sess-lecture-schema",
                runtime=SimpleNamespace(),
                extra=extra,
            ),
        )
        tool_names = [
            item["function"]["name"]
            for item in loop._tools_schema()
            if isinstance(item, dict) and isinstance(item.get("function"), dict)
        ]
        assert "save_lecture_note" in tool_names

    for answer_mode in ("guided", "direct"):
        plain_extra = _build_agent_tool_context_extra(
            coach_context=None,
            attachment_delivery={},
            answer_mode=answer_mode,
            current_file=None,
            learner_message="请讲明白注意力缩放。",
        )
        assert "save_lecture_note" in plain_extra["denied_tool_names"]
        plain_loop = CoachAgentLoop(
            provider=cast(Any, SimpleNamespace(protocol="openai_chat_completions_compatible")),
            registry=registry,
            context=ToolContext(
                workspace_id="ws-lecture-schema",
                session_id="sess-lecture-schema",
                runtime=SimpleNamespace(),
                extra=plain_extra,
            ),
        )
        plain_tool_names = [
            item["function"]["name"]
            for item in plain_loop._tools_schema()
            if isinstance(item, dict) and isinstance(item.get("function"), dict)
        ]
        assert "save_lecture_note" not in plain_tool_names

    rewritten = enforce_truthful_saved_note_path(
        "已写入 `Trainer Library/Scaled Dot-Product Attention 讲稿.md`。",
        [
            {
                "type": "tool_result",
                "name": "save_lecture_note",
                "result": {"ok": True, "saved_path": "Trainer Library/学习讲稿/scaled-dot-product-attention.md"},
            }
        ],
    )
    assert "Trainer Library/学习讲稿/scaled-dot-product-attention.md" in rewritten
    assert "Trainer Library/Scaled Dot-Product Attention 讲稿.md" not in rewritten
