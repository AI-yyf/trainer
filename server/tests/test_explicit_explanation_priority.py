"""Explicit explanations must not be replaced by generic coaching recovery copy."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.core.models import ProviderTestResponse
from app.llm.provider_service import ProviderService
from tests.test_api import build_client


def test_explicit_zh_explanation_uses_a_direct_answer_even_with_guided_defaults(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-explicit-explanation-priority"
    user_message = (
        "\u8bf7\u7528\u4e24\u53e5\u4e2d\u6587\u89e3\u91ca Python "
        "\u5217\u8868\u63a8\u5bfc\u5f0f\uff0c\u5e76\u7ed9\u4e00\u4e2a\u5e73\u65b9\u793a\u4f8b"
    )
    provider_reply = (
        "列表推导式对每个输入元素应用同一个表达式，并把结果组成新列表。"
        "例如，把 0 到 4 的每个数平方，会依次得到 0、1、4、9、16。"
    )

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "test",
            autospec=True,
            return_value=ProviderTestResponse(
                ok=False,
                detail="A stale language probe incorrectly reported corruption.",
                error_category="language_corruption",
            ),
        ) as language_probe,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value=provider_reply),
        ) as coaching_reply,
    ):
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Explicit explanation",
                "profile": {
                    "long_term_goal": "Learn Python basics",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert started.status_code == 200, started.text

        response = client.post(
            "/session/message",
            json={
                "session_id": started.json()["session_id"],
                "workspace_id": workspace_id,
                "message": user_message,
                "response_language": "zh-CN",
                "answer_mode": "guided",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert language_probe.call_count == 1
    assert coaching_reply.await_args is not None
    assert coaching_reply.await_args.kwargs["answer_mode"] == "direct"
    assert payload["reply"]["content"] == provider_reply
    assert "\u5217\u8868\u63a8\u5bfc\u5f0f" in payload["reply"]["content"]
    assert "0、1、4、9、16" in payload["reply"]["content"]
    assert "\u5148\u522b\u76f4\u63a5\u7ed9\u7b54\u6848" not in payload["reply"]["content"]
