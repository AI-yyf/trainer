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
