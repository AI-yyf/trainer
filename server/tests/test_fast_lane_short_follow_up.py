"""A short follow-up next to a live error is answered in one model call.

"然后呢？" typed beside a file that shows an error needs nothing the prompt does not already hold:
the open file, its diagnostics, the thread's last step. With tools mounted the model went looking
anyway — with a real model on 2026-11-28 it spent two or three model round trips (7-28 s to its
first visible word) reading a file whose content was already in the prompt and re-running the
diagnostics. Without tools the same turn took one call: first visible word at a median of 3 s, reply
complete at about 4 s, and the replies kept to a pointed next move.

The lane is deliberately narrow: a short message, no word that asks for a tool, the open file has
live diagnostics, and no other lane (plan, cards, resources, attachments) is involved.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.models import CapabilityFlags, ProviderConfig, UserProfile
from app.llm.agent_tool_context import (
    _build_agent_tool_context_extra,
    short_follow_up_next_to_live_error,
)
from app.llm.provider_service import ProviderService

ERROR_FILE: dict[str, object] = {
    "path": "/repo/app.py",
    "language_id": "python",
    "content": "print(get(config, 'retries'))\n",
    "diagnostics": ["[Error] line 8: KeyError: 'retries'"],
}
CLEAN_FILE: dict[str, object] = {"path": "/repo/app.py", "language_id": "python", "content": "print(1)\n"}


def _profile() -> UserProfile:
    return UserProfile.model_validate(
        {
            "long_term_goal": "Build a FastAPI trainer",
            "weekly_hours": 6,
            "teaching_style": "guided",
            "answer_policy": "guided",
        }
    )


def _config() -> ProviderConfig:
    return ProviderConfig(
        name="fast-lane",
        baseUrl="https://api.openai.com/v1",
        apiKeyRef="trainer.test",
        model="gpt-4o-mini",
        capabilities=CapabilityFlags(chat=True, streaming=True, tools=True),
    )


def _lane(message: str, *, current_file: dict[str, object] | None = ERROR_FILE, coach_context: dict[str, Any] | None = None, **kw: Any) -> bool:
    return short_follow_up_next_to_live_error(
        message=message, current_file=current_file, coach_context=coach_context or {}, **kw
    )


@pytest.mark.parametrize("message", ["然后呢？", "下一步？", "然后呢", "这样对吗？", "改好了", "ok", "好了，然后呢", "And now?"])
def test_a_nudge_next_to_a_live_error_takes_the_lane(message: str) -> None:
    assert _lane(message) is True


@pytest.mark.parametrize(
    ("message", "current_file", "coach_context", "kw"),
    [
        ("然后呢？", CLEAN_FILE, {}, {}),
        ("然后呢？", None, {}, {}),
        ("然后呢？", ERROR_FILE, {}, {"attachments_present": True}),
        ("然后呢？\n\n```python\nprint(1)\n```", ERROR_FILE, {}, {}),
        ("我改了三处：先是把 get 换成 dict.get，然后给 config 补了 retries，再删掉了那行 print，接下来该看哪儿？", ERROR_FILE, {}, {}),
        ("帮我运行一下看看", ERROR_FILE, {}, {}),
        ("然后呢？先验证一下", ERROR_FILE, {}, {}),
        ("看看项目里还有哪里用到它", ERROR_FILE, {}, {}),
        ("讲解一下这个项目", ERROR_FILE, {}, {}),
        ("然后呢？", ERROR_FILE, {"formal_plan_mutation": True}, {}),
        ("然后呢？", ERROR_FILE, {"explicit_training_card_request": True}, {}),
        ("然后呢？", ERROR_FILE, {"auto_resource_lookup": True}, {}),
        ("然后呢？", ERROR_FILE, {"resource_composer_intent": {"mode": "ask"}}, {}),
        ("然后呢？", ERROR_FILE, {"active_view": "resources"}, {}),
        ("然后呢？", ERROR_FILE, {"completed_training_return_feedback": True}, {}),
    ],
)
def test_the_lane_stays_out_of_the_way(
    message: str,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any],
    kw: dict[str, Any],
) -> None:
    assert _lane(message, current_file=current_file, coach_context=coach_context, **kw) is False


def test_the_lane_mounts_no_tools_and_says_so() -> None:
    extra = _build_agent_tool_context_extra(
        coach_context={"workspace_id": "w", "session_id": "s"},
        attachment_delivery={},
        answer_mode="guided",
        current_file=ERROR_FILE,
        provider_config=_config(),
        learner_message="然后呢？",
    )
    project_question = _build_agent_tool_context_extra(
        coach_context={"workspace_id": "w", "session_id": "s"},
        attachment_delivery={},
        answer_mode="guided",
        current_file=ERROR_FILE,
        provider_config=_config(),
        learner_message="讲解一下这个项目",
    )

    assert extra["allowed_tool_names"] == []
    assert extra["tool_free_fast_lane"] is True
    assert project_question["allowed_tool_names"]
    assert "tool_free_fast_lane" not in project_question


def _service_with_streaming_provider(monkeypatch: pytest.MonkeyPatch) -> tuple[ProviderService, list[dict[str, Any]]]:
    service = ProviderService(config=_config(), api_key="sk-test")
    calls: list[dict[str, Any]] = []

    async def _fake_call(messages: list[dict[str, object]], tools: list[dict[str, object]] | None) -> dict[str, object]:
        calls.append({"messages": messages, "tools": tools})
        return {"content": "Decide whether retries is required, then fix that one place.", "tool_calls": []}

    async def _fake_call_stream(messages: list[dict[str, object]], tools: list[dict[str, object]] | None):
        calls.append({"messages": messages, "tools": tools})
        yield {"type": "delta", "delta": "Decide whether retries is required, then fix that one place."}
        yield {
            "type": "final",
            "content": "Decide whether retries is required, then fix that one place.",
            "tool_calls": [],
            "stop_reason": "stop",
        }

    fake_provider = SimpleNamespace(protocol="openai_chat_completions", call=_fake_call, call_stream=_fake_call_stream)

    def _fake_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr(
        "app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider
    )
    return service, calls


async def _run(service: ProviderService, message: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        _profile(),
        message,
        ERROR_FILE,
        answer_mode="guided",
        coach_context={"__runtime__": SimpleNamespace(), "workspace_id": "workspace-x", "session_id": "session-x"},
    ):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_a_nudge_is_answered_in_one_call_without_tools_or_tool_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    service, calls = _service_with_streaming_provider(monkeypatch)

    events = await _run(service, "然后呢？")

    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "completed"
    assert len(calls) == 1
    system_message = str(calls[0]["messages"][0]["content"])
    assert "## Agent Loop & Tools" not in system_message
    assert not calls[0]["tools"]


@pytest.mark.asyncio
async def test_a_project_question_still_gets_the_tools_and_their_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    service, calls = _service_with_streaming_provider(monkeypatch)

    events = await _run(service, "讲解一下这个项目")

    assert next(event for event in events if event["type"] == "final")["stop_reason"] == "completed"
    assert calls[0]["tools"], "the project question keeps its tools"
    assert "## Agent Loop & Tools" in str(calls[0]["messages"][0]["content"])
