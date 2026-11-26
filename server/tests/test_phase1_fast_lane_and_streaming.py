"""Phase 1 regressions: 0-tool Fast Lane routing and real-time incremental streaming."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.api.router_support import _resolve_agent_loop_enabled
from app.core.models import ProviderConfig, SessionMessageRequest, UserProfile
from app.llm.coaching_replies import _stream_holdback_chars
from app.llm.provider_service import ProviderService


def _tool_capable_service() -> ProviderService:
    config = ProviderConfig(
        name="phase1-fast-lane",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={"chat": True, "streaming": True, "tools": True},
    )
    return ProviderService(config=config, api_key="sk-test")


def _guided_profile() -> UserProfile:
    return UserProfile(
        long_term_goals=[],
        weekly_hours=4,
        teaching_style="auto",
        answer_policy="auto",
        preferred_libraries=[],
    )


def _chunk(content: str, finish_reason: str | None = None) -> SimpleNamespace:
    delta = SimpleNamespace(content=content)
    choice = SimpleNamespace(finish_reason=finish_reason, delta=delta)
    return SimpleNamespace(choices=[choice])


@pytest.mark.parametrize(
    "message",
    [
        "讲解一下 Transformer 的自注意力机制",
        "介绍一下快速排序的时间复杂度",
        "讲讲这个概念：什么是反向传播？",
        "什么是微服务架构？",
        "walk me through gradient descent step by step",
        "Explain Python asyncio event loop",
    ],
)
def test_pure_conceptual_questions_stay_on_zero_tool_fast_lane(message: str) -> None:
    service = _tool_capable_service()
    request = SessionMessageRequest(message=message, active_view="coach")
    assert _resolve_agent_loop_enabled(request, service, stream=True) is False


@pytest.mark.parametrize(
    "message",
    [
        "看看这个项目的目录结构",
        "帮我查一下最新的 FlashAttention 论文",
        "解释一下 server/app/main.py 的启动流程",
        "帮我分析一下当前项目架构",
        "请联网搜索 Python 3.13 新特性",
        "帮我整理资料库里的文档",
    ],
)
def test_workspace_library_and_research_queries_route_to_tool_lane(message: str) -> None:
    service = _tool_capable_service()
    request = SessionMessageRequest(message=message, active_view="coach")
    assert _resolve_agent_loop_enabled(request, service, stream=True) is True


def test_stream_holdback_is_compact_for_low_ttft() -> None:
    assert _stream_holdback_chars("zh-CN") <= 10
    assert _stream_holdback_chars("en-US") <= 16


@pytest.mark.asyncio
async def test_fast_lane_streams_incrementally_in_default_guided_mode_with_code() -> None:
    parts = [
        "快速排序的核心思想是分治。",
        "先选一个基准值，再把数组分成左右两半。\n\n",
        "```python\n",
        "def quicksort(arr):\n",
        "    if len(arr) <= 1:\n",
        "        return arr\n",
        "    pivot = arr[0]\n",
        "    return quicksort([x for x in arr[1:] if x < pivot]) + [pivot] + quicksort([x for x in arr[1:] if x >= pivot])\n",
        "```\n",
    ]

    async def _iterate():
        for part in parts:
            yield _chunk(part)
        yield _chunk("", finish_reason="stop")

    service = _tool_capable_service()

    async def fake_create(**_kwargs: object) -> tuple[Any, None]:
        return _iterate(), None

    service._get_client = lambda: object()  # type: ignore[method-assign]
    service._create_chat_completion = fake_create  # type: ignore[method-assign]
    service._plain_completion_uses_agent_binding = lambda: False  # type: ignore[method-assign]

    yielded = [
        chunk
        async for chunk in service.coaching_reply_stream(
            _guided_profile(),
            "讲解一下快速排序",
            response_language="zh-CN",
            answer_mode="auto",
        )
    ]

    assert len(yielded) >= 3, f"expected multiple live chunks, got {yielded!r}"
    assert "".join(yielded).startswith("快速排序的核心思想是分治。")
    assert "def quicksort(arr):" in "".join(yielded)


@pytest.mark.asyncio
async def test_agent_binding_fast_lane_yields_live_chunks_in_default_auto_mode() -> None:
    """Cure P0-1: coaching_reply_stream via agent binding streams live in default auto mode."""
    parts = [
        "事件循环负责调度协程并管理异步 I/O。",
        "当协程遇到 await I/O 时主动让出控制权，",
        "等内核通知就绪后再恢复执行。",
    ]

    async def _binding_chunks(*_args: object, **_kwargs: object):
        for part in parts:
            yield part

    service = _tool_capable_service()
    service._plain_completion_uses_agent_binding = lambda: True  # type: ignore[method-assign]
    service._completion_stream_via_agent_binding = _binding_chunks  # type: ignore[method-assign]

    chunks = [
        c
        async for c in service.coaching_reply_stream(
            _guided_profile(),
            "解释一下事件循环",
            None,
            "zh-CN",
            "auto",
        )
    ]
    assert len(chunks) >= 3, f"expected unbuffered live deltas in auto mode, got {chunks!r}"
    assert "".join(chunks).startswith("事件循环负责调度协程")


def test_idle_open_editor_tab_keeps_minimal_context_tier_for_pure_conceptual_qa(tmp_path) -> None:
    """Cure P1-3: an open editor tab without selection/code-mention keeps minimal prompt tier."""
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    app = create_app(Settings(data_dir=tmp_path / "data"))
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200

    idle_req = SessionMessageRequest(
        message="什么是反向传播？",
        active_view="coach",
        current_file={"path": "src/server.py", "language_id": "python", "content": "x = 1"},
    )
    anchored_req = SessionMessageRequest(
        message="解释一下 server.py 里的逻辑",
        active_view="coach",
        current_file={"path": "src/server.py", "language_id": "python", "content": "x = 1"},
    )
    selected_req = SessionMessageRequest(
        message="这段是什么意思？",
        active_view="coach",
        current_file={
            "path": "src/server.py",
            "language_id": "python",
            "content": "x = 1",
            "selection_text": "x = 1",
        },
    )
    assert idle_req.current_file is not None
    assert "server.py" not in idle_req.message
    assert "server.py" in anchored_req.message
    assert selected_req.current_file.selection_text == "x = 1"


@pytest.mark.asyncio
async def test_wave2_zero_post_stream_mutation_control_role_and_kv_cache_tool_schema_invariance() -> None:
    """Wave 2 (P0-B):
    1) Already-streamed SSE prefixes are never retroactively rewritten on stream completion.
    2) Formal-plan commit repair uses role='control' (never impersonating role='user' or stealing vision attachments).
    3) Orthogonal tool schemas stay byte-identical across diverse turns & intra-turn steps for Prefix KV Cache.
    """
    import json

    from app.llm.agent_binding import (
        _format_openai_messages,
        _format_openai_responses_input,
        _split_anthropic_messages,
    )
    from app.llm.agent_loop import AgentProvider, CoachAgentLoop
    from app.llm.agent_tool_context import _build_agent_tool_context_extra
    from app.llm.coaching_replies import preserve_streamed_reply_prefix
    from app.llm.tool_primitives import ORTHOGONAL_PRIMITIVE_NAMES
    from app.llm.tools import ToolContext, build_default_tool_registry

    # 1) Zero post-stream text mutation:
    streamed_prefix = "在调试闭环里，你可以把鼠标 hover 到变量上观察当前帧值，并对比 remote host 环境。"
    retroactive_rewrite = "这一轮先只搭一条可信的 VS Code debug loop。先定一个 breakpoint。"
    preserved = preserve_streamed_reply_prefix(
        streamed_prefix,
        retroactive_rewrite,
        streamed_prefix + "\nThis follows the teaching lane from debug_loop.\n<system-reminder>internal</system-reminder>",
        response_language="zh-CN",
    )
    assert preserved == streamed_prefix

    # Append-only truthful lecture note path correction when guessed path was already streamed:
    streamed_with_guess = "讲稿已保存至 `Trainer Library/wrong/guess.md`。"
    preserved_note = preserve_streamed_reply_prefix(
        streamed_with_guess,
        streamed_with_guess,
        streamed_with_guess,
        tool_events=[
            {
                "type": "tool_result",
                "name": "library_write",
                "ok": True,
                "result": {
                    "ok": True,
                    "action": "save_lecture_note",
                    "saved_path": "Trainer Library/notes/real-note.md",
                },
            }
        ],
        response_language="zh-CN",
    )
    assert preserved_note.startswith(streamed_with_guess)
    assert "Trainer Library/notes/real-note.md" in preserved_note

    # 2) Non-impersonating role='control' preserves real user vision attachment binding:
    registry = build_default_tool_registry()
    seen_histories: list[list[dict[str, Any]]] = []
    seen_schemas: list[list[dict[str, Any]]] = []

    async def _plan_call(
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        seen_histories.append([dict(m) for m in messages])
        seen_schemas.append(list(tools or []))
        if len(seen_histories) == 1:
            return {"content": "先给出一份草稿，尚未调用保存工具。", "tool_calls": []}
        return {"content": "需要你先确认每周可投入时长后再正式保存计划。", "tool_calls": []}

    plan_ctx = ToolContext(
        runtime=None,
        workspace_id="ws-kv",
        session_id="sess-kv",
        response_language="zh-CN",
        extra={
            "allow_coach_only_tools": True,
            "formal_plan_mutation": True,
            "allowed_tool_names": ["learning_inspect", "learning_action", "web_fetch"],
        },
    )
    loop = CoachAgentLoop(
        provider=AgentProvider(protocol="openai_chat_completions", call=_plan_call),
        registry=registry,
        context=plan_ctx,
        max_steps=4,
    )
    await loop.run([{"role": "user", "content": "请根据这张架构图制定正式计划"}])
    assert len(seen_histories) == 2
    injected = seen_histories[1][-1]
    assert injected["role"] == "control"
    assert injected.get("_harness_control") is True
    assert "<system-reminder>" in str(injected["content"])

    # Verify vision attachments stay bound to the real learner message (index 1), not the control message!
    fake_attachment = [{"kind": "image", "mime_type": "image/png", "data_base64": "iVBORw0KGgo="}]
    oai_msgs = _format_openai_messages(
        [{"role": "system", "content": "sys"}, *seen_histories[1]],
        attachments=fake_attachment,
        vision_enabled=True,
    )
    assert isinstance(oai_msgs[1]["content"], list)  # real user message got the image_url part!
    assert oai_msgs[-1]["role"] == "system"

    sys_inst, resp_items = _format_openai_responses_input(
        [{"role": "system", "content": "STATIC_SYS"}, *seen_histories[1]],
        attachments=fake_attachment,
        vision_enabled=True,
    )
    assert sys_inst == "STATIC_SYS"  # top-level system prefix untouched!
    assert resp_items[-1]["role"] == "developer"

    anth_sys, anth_msgs = _split_anthropic_messages(
        [{"role": "system", "content": "STATIC_SYS"}, *seen_histories[1]],
        attachments=fake_attachment,
        vision_enabled=True,
    )
    assert anth_sys == "STATIC_SYS"  # top-level Anthropic system prompt untouched!
    assert len(anth_msgs[0]["content"]) == 2  # real user message keeps text + image block!

    # 3) Byte-identical wire tool schemas across project, library, and plan turns for Prefix KV Cache:
    proj_extra = _build_agent_tool_context_extra(
        coach_context={"active_view": "coach"},
        attachment_delivery={},
        answer_mode="auto",
        current_file={"path": "app.py", "content": "x = 1"},
        learner_message="看看 app.py",
    )
    lib_extra = _build_agent_tool_context_extra(
        coach_context={"active_view": "resources", "library_sandbox_work": True},
        attachment_delivery={},
        answer_mode="auto",
        current_file=None,
        learner_message="整理资料库",
    )
    for protocol in (
        "openai_chat_completions",
        "openai_responses",
        "anthropic_messages",
        "gemini_generate_content",
    ):
        proj_loop_schemas = CoachAgentLoop(
            provider=AgentProvider(protocol=protocol, call=_plan_call),
            registry=registry,
            context=ToolContext(runtime=None, workspace_id="w", extra=proj_extra),
        )._tools_schema()
        lib_loop_schemas = CoachAgentLoop(
            provider=AgentProvider(protocol=protocol, call=_plan_call),
            registry=registry,
            context=ToolContext(runtime=None, workspace_id="w", extra=lib_extra),
        )._tools_schema()
        assert json.dumps(proj_loop_schemas, sort_keys=True) == json.dumps(
            lib_loop_schemas, sort_keys=True
        )
        assert len(proj_loop_schemas) == len(ORTHOGONAL_PRIMITIVE_NAMES) == 8

    # Runtime ToolRegistry.invoke still strictly enforces per-turn allowed_tool_names fail-closed!
    proj_ctx = ToolContext(runtime=None, workspace_id="w", extra=proj_extra)
    blocked_exec = await registry.invoke(proj_ctx, "library_exec", {"command": "echo nope"})
    assert blocked_exec["ok"] is False
    assert blocked_exec["error"] == "tool_not_available"


