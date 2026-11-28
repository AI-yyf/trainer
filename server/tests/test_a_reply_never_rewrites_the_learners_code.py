"""A reply never contains a new version of the learner's own code.

The prompt asks for it in every mode ("Never write a new version of the learner's function, file or
config for them, even as an illustration"). On 2026-11-28, with the gateway's MiniMax-M3 and
M3.1-Flash, the guided reply to "这段为什么会报 KeyError？" carried the learner's own function,
fixed:

    ```python
    def get(d, k, default=None):
        return d.get(k, default)
    ```

With MiniMax-M2.7 the same turn did not. The rule is the product's, so the server keeps it too, on
both lanes, while the reply streams and when it is finished.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from client_fixtures import build_client
from fastapi import FastAPI
from provider_fixtures import seed_verified_capabilities

from app.api.runtime import TrainerRuntime
from app.core.models import CapabilityFlags, ProviderConfig, UserProfile
from app.llm.learner_code_guard import (
    LEARNER_CODE_NOTE_ZH,
    MAX_GUARDED_BLOCK_CHARS,
    LearnerCode,
    redact_learner_code_rewrites,
    streamable_learner_reply,
)
from app.llm.provider_service import ProviderService

APP_PY = """def get(d, k):
    return d[k]


if __name__ == "__main__":
    config = {"host": "localhost", "port": 8000}
    print(get(config, "port"))
    print(get(config, "retries"))
"""
CURRENT_FILE: dict[str, object] = {"path": "/repo/app.py", "language_id": "python", "content": APP_PY}
QUESTION = "这段为什么会报 KeyError？"
LEARNER = LearnerCode.for_turn(current_file=CURRENT_FILE, message=QUESTION)

REWRITE = "```python\ndef get(d, k, default=None):\n    return d.get(k, default)\n```"
QUOTE = "```python\ndef get(d, k):\n    return d[k]\n```"
RECORDED_REPLY = (
    "问题出在 `get` 的第二个调用点。\n\n" + REWRITE + "\n\n下一步：改完再跑一次 `python app.py`。"
)


def _feed(text: str, learner: LearnerCode = LEARNER, *, chunk: int = 1) -> list[str]:
    guard_note = LEARNER_CODE_NOTE_ZH
    return [
        streamable_learner_reply(text[: index + chunk], learner, note=guard_note)
        for index in range(0, len(text), chunk)
    ]


# --- a finished reply -------------------------------------------------------------


def test_a_new_version_of_the_learners_function_is_left_out_and_named() -> None:
    reply = redact_learner_code_rewrites(RECORDED_REPLY, LEARNER, note=LEARNER_CODE_NOTE_ZH)

    assert "def get(d, k, default=None)" not in reply
    assert LEARNER_CODE_NOTE_ZH in reply
    assert reply.startswith("问题出在 `get` 的第二个调用点。\n\n")
    assert reply.endswith("\n\n下一步：改完再跑一次 `python app.py`。")


@pytest.mark.parametrize(
    "block",
    [
        QUOTE,
        "```python\ndef get(d, k):\n    return d[k]   # ← 这里抛 KeyError\n```",
        "```python\nimport app\n\napp.get({}, \"retries\")\n```",
        "```python\ndef safe_get(d, k, default=None):\n    return d.get(k, default)\n```",
        "```python\nconfig = {\"host\": \"localhost\", \"port\": 8000}\n```",
    ],
)
def test_the_learners_own_code_and_a_standalone_example_stay(block: str) -> None:
    reply = "先看这里：\n\n" + block + "\n\n下一步：说出区别。"

    assert redact_learner_code_rewrites(reply, LEARNER, note=LEARNER_CODE_NOTE_ZH) == reply


def test_a_quoted_empty_block_and_a_block_with_a_closing_fence_only_stay() -> None:
    reply = "```\n```\n\n```\npython\n```\n"

    assert redact_learner_code_rewrites(reply, LEARNER, note=LEARNER_CODE_NOTE_ZH) == reply


def test_a_new_version_of_a_class_is_left_out() -> None:
    learner = LearnerCode.for_turn(
        current_file={"content": "class Ledger:\n    def add(self, item):\n        self.items.append(item)\n"},
        message="怎么改成线程安全？",
    )
    reply = "```python\nclass Ledger:\n    def add(self, item):\n        with self.lock:\n            self.items.append(item)\n```"

    assert "with self.lock" not in redact_learner_code_rewrites(reply, learner, note=LEARNER_CODE_NOTE_ZH)


@pytest.mark.parametrize(
    "block",
    [
        "```javascript\nfunction charge(orderId, amount) {\n  return post(orderId, amount, { retry: 2 });\n}\n```",
        "```javascript\nconst charge = (orderId, amount) => post(orderId, amount, { retry: 2 });\n```",
    ],
)
def test_a_new_version_in_javascript_is_left_out(block: str) -> None:
    learner = LearnerCode.for_turn(
        current_file={"content": "function charge(orderId, amount) {\n  return post(orderId, amount);\n}\n"},
        message="why does it time out?",
    )

    assert "retry: 2" not in redact_learner_code_rewrites(block, learner, note=LEARNER_CODE_NOTE_ZH)


def test_code_the_learner_pasted_in_the_message_is_theirs() -> None:
    message = "我改成这样了，对吗？\n\n```python\ndef get(d, k, default=None):\n    return d.get(k, default)\n```"
    learner = LearnerCode.for_turn(current_file=CURRENT_FILE, message=message)

    assert redact_learner_code_rewrites(RECORDED_REPLY, learner, note=LEARNER_CODE_NOTE_ZH) == RECORDED_REPLY


def test_a_block_the_learner_did_not_declare_anything_against_is_untouched() -> None:
    learner = LearnerCode.for_turn(current_file={"content": "print(1)\n"}, message=QUESTION)

    assert redact_learner_code_rewrites(RECORDED_REPLY, learner, note=LEARNER_CODE_NOTE_ZH) == RECORDED_REPLY


def test_an_unclosed_block_at_the_end_of_a_reply_is_left_as_it_is() -> None:
    assert redact_learner_code_rewrites(REWRITE[:-3], LEARNER, note=LEARNER_CODE_NOTE_ZH) == REWRITE[:-3]


def test_a_block_past_the_cap_is_never_touched() -> None:
    body = "def get(d, k, default=None):\n    return d.get(k, default)\n" + "    # " + "x" * MAX_GUARDED_BLOCK_CHARS + "\n"
    block = "```python\n" + body + "```"

    assert redact_learner_code_rewrites(block, LEARNER, note=LEARNER_CODE_NOTE_ZH) == block


def test_every_recorded_rewrite_from_the_five_model_run_is_left_out() -> None:
    """The blocks MiniMax-M3 and M3.1-Flash wrote on 2026-11-28 (latency_models_final.json)."""
    cases = [
        ("def get(d, k):\n    return d[k]\n", "def get(d, k):\n    return d.get(k)\n"),
        (
            "def charge(order_id, amount):\n    CHARGED.append((order_id, amount))\n",
            "def charge(order_id, amount):\n    resp = gateway.post(order_id, amount)\n    raise TimeoutError\n",
        ),
    ]
    for learner_source, new_version in cases:
        learner = LearnerCode.for_turn(current_file={"content": learner_source}, message=QUESTION)

        assert learner.rewrites(new_version)
        assert not learner.rewrites(learner_source)


# --- a reply that is still streaming ------------------------------------------------


@pytest.mark.parametrize("chunk", [1, 2, 5, 17])
def test_while_streaming_nothing_shown_is_ever_taken_back_and_the_rewrite_never_shows(chunk: int) -> None:
    shown = _feed(RECORDED_REPLY, chunk=chunk)

    assert all(later.startswith(earlier) for earlier, later in zip(shown, shown[1:], strict=False)), shown
    assert shown[-1] == redact_learner_code_rewrites(RECORDED_REPLY, LEARNER, note=LEARNER_CODE_NOTE_ZH)
    assert not any("default=None" in text for text in shown)


@pytest.mark.parametrize("chunk", [1, 3, 40])
def test_a_legitimate_block_is_shown_whole_once_it_closes(chunk: int) -> None:
    reply = "先看这里：\n\n" + QUOTE + "\n\n下一步：说出区别。"
    shown = _feed(reply, chunk=chunk)

    assert shown[-1] == reply
    for text in shown:
        opened = text.count("```")
        assert opened in (0, 2), text  # never a fence that is open in what the learner sees


def test_a_fence_marker_that_is_still_arriving_is_held() -> None:
    assert streamable_learner_reply("先看这里：\n``", LEARNER, note=LEARNER_CODE_NOTE_ZH) == "先看这里：\n"
    assert streamable_learner_reply("先看这里：\n`", LEARNER, note=LEARNER_CODE_NOTE_ZH) == "先看这里：\n"
    assert streamable_learner_reply("先看这里：\n`get`", LEARNER, note=LEARNER_CODE_NOTE_ZH) == "先看这里：\n`get`"


def test_a_block_past_the_cap_streams_live() -> None:
    block = "```python\n" + "x = 1\n" * (MAX_GUARDED_BLOCK_CHARS // 2) + "```"
    shown = _feed(block, chunk=1000)

    assert shown[-1] == block


# --- the lanes ---------------------------------------------------------------------


def _profile() -> UserProfile:
    return UserProfile.model_validate(
        {"long_term_goal": "Build a FastAPI trainer", "weekly_hours": 6, "teaching_style": "guided", "answer_policy": "guided"}
    )


def _config() -> ProviderConfig:
    return ProviderConfig(
        name="learner-code",
        baseUrl="https://api.openai.com/v1",
        apiKeyRef="trainer.test",
        model="gpt-4o-mini",
        capabilities=CapabilityFlags(chat=True, streaming=True, tools=True),
    )


def _service() -> ProviderService:
    return ProviderService(config=_config(), api_key="sk-test")


def _chunk(content: str, finish_reason: str | None = None) -> SimpleNamespace:
    choice = SimpleNamespace(finish_reason=finish_reason, delta=SimpleNamespace(content=content))
    return SimpleNamespace(choices=[choice])


def _assert_left_out(reply: str) -> None:
    assert "default=None" not in reply
    assert LEARNER_CODE_NOTE_ZH in reply


@pytest.mark.asyncio
async def test_the_plain_stream_never_shows_the_rewrite(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service()
    parts = [RECORDED_REPLY[:14], RECORDED_REPLY[14:60], RECORDED_REPLY[60:]]

    async def _iterate() -> Any:
        for part in parts:
            yield _chunk(part)
        yield _chunk("", finish_reason="stop")

    async def fake_create(**_kwargs: object) -> tuple[Any, None]:
        return _iterate(), None

    monkeypatch.setattr(service, "_get_client", lambda: object())
    monkeypatch.setattr(service, "_create_chat_completion", fake_create)
    monkeypatch.setattr(service, "_plain_completion_uses_agent_binding", lambda: False)

    chunks: list[str] = []
    async for chunk in service.coaching_reply_stream(
        _profile(), QUESTION, CURRENT_FILE, response_language="zh-CN", answer_mode="guided"
    ):
        chunks.append(chunk)

    joined = "".join(chunks)
    _assert_left_out(joined)
    assert "问题出在 `get` 的第二个调用点。" in joined
    assert joined.rstrip().endswith("下一步：改完再跑一次 `python app.py`。")
    assert not any("default=None" in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_the_plain_reply_never_contains_the_rewrite(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    service = _service()
    choice = MagicMock()
    choice.message.content = RECORDED_REPLY
    response = MagicMock()
    response.choices = [choice]
    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)
        mock_get_client.return_value = mock_client

        reply = await service.coaching_reply(_profile(), QUESTION, CURRENT_FILE, response_language="zh-CN", answer_mode="guided")

    _assert_left_out(reply)


async def _agent_stream_events(
    monkeypatch: pytest.MonkeyPatch, reply: str, *, native_stream: bool
) -> list[dict[str, Any]]:
    service = _service()

    async def _fake_call_stream(messages: list[dict[str, object]], tools: list[dict[str, object]] | None) -> Any:
        for part in (reply[:9], reply[9:41], reply[41:70], reply[70:]):
            event: dict[str, Any] = {"type": "delta", "delta": part}
            if native_stream:
                event["safe_to_stream"] = True
            yield event
        yield {"type": "final", "content": reply, "tool_calls": [], "stop_reason": "stop"}

    fake_provider = SimpleNamespace(protocol="openai_chat_completions", call_stream=_fake_call_stream)

    def _fake_build_agent_provider(self: ProviderService, **_kwargs: object) -> tuple[object, object]:
        return fake_provider, fake_provider

    monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    return [
        event
        async for event in service.coaching_reply_agentic_stream(
            _profile(),
            QUESTION,
            CURRENT_FILE,
            answer_mode="guided",
            response_language="zh-CN",
            coach_context={"__runtime__": SimpleNamespace(), "workspace_id": "workspace-x", "session_id": "session-x"},
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("native_stream", [False, True])
async def test_the_agent_stream_never_shows_the_rewrite(monkeypatch: pytest.MonkeyPatch, native_stream: bool) -> None:
    events = await _agent_stream_events(monkeypatch, RECORDED_REPLY, native_stream=native_stream)

    streamed = "".join(str(event["delta"]) for event in events if event["type"] == "text")
    final = next(event for event in events if event["type"] == "final")
    _assert_left_out(streamed)
    _assert_left_out(str(final["content"]))
    assert re.search(r"下一步[:：]", streamed), streamed


@pytest.mark.asyncio
@pytest.mark.parametrize("native_stream", [False, True])
async def test_the_agent_stream_shows_a_legitimate_block_whole(monkeypatch: pytest.MonkeyPatch, native_stream: bool) -> None:
    """A block held while it was open comes out whole. This lane keeps its holdback on the last
    characters of a reply; the route sends the rest of the final text when the stream completes."""
    reply = "先看这里：\n\n" + QUOTE + "\n\n下一步：说出区别。"
    events = await _agent_stream_events(monkeypatch, reply, native_stream=native_stream)

    streamed = "".join(str(event["delta"]) for event in events if event["type"] == "text")
    final = str(next(event for event in events if event["type"] == "final")["content"])
    shown = streamed + (final[len(streamed) :] if final.startswith(streamed) else "")
    assert "```python\ndef get(d, k):\n    return d[k]\n```" in shown, shown
    assert shown.rstrip().endswith("下一步：说出区别。"), shown


# --- the turn route, end to end ---------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_loop", [True, False])
async def test_the_turn_route_never_streams_the_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent_loop: bool
) -> None:
    """Through ``/turn/stream``: what the chat receives as chunks, and the completed reply."""
    project = tmp_path / "repo"
    project.mkdir()
    (project / "app.py").write_text(APP_PY, encoding="utf-8")

    if agent_loop:

        async def _fake_call_stream(messages: list[dict[str, object]], tools: list[dict[str, object]] | None) -> Any:
            for part in (RECORDED_REPLY[:14], RECORDED_REPLY[14:57], RECORDED_REPLY[57:]):
                yield {"type": "delta", "delta": part, "safe_to_stream": True}
            yield {"type": "final", "content": RECORDED_REPLY, "tool_calls": [], "stop_reason": "stop"}

        fake_provider = SimpleNamespace(protocol="openai_chat_completions", call_stream=_fake_call_stream)

        def _fake_build_agent_provider(self: ProviderService, **_kwargs: object) -> tuple[object, object]:
            return fake_provider, fake_provider

        monkeypatch.setattr("app.llm.provider_service.ProviderService.build_agent_provider", _fake_build_agent_provider)
    else:

        async def _iterate() -> Any:
            for part in (RECORDED_REPLY[:14], RECORDED_REPLY[14:57], RECORDED_REPLY[57:]):
                yield _chunk(part)
            yield _chunk("", finish_reason="stop")

        async def _fake_create(self: ProviderService, **_kwargs: object) -> tuple[Any, None]:
            return _iterate(), None

        monkeypatch.setattr(ProviderService, "_plain_completion_uses_agent_binding", lambda self: False)
        monkeypatch.setattr(ProviderService, "_get_client", lambda self: object())
        monkeypatch.setattr(ProviderService, "_create_chat_completion", _fake_create)

    with build_client(tmp_path / "sidecar", configure_provider=False) as client:
        application = client.app
        assert isinstance(application, FastAPI)
        runtime = application.state.runtime
        assert isinstance(runtime, TrainerRuntime)
        seed_verified_capabilities(runtime, _config(), "test-only-key")
        started = client.post(
            "/session/start",
            json={"workspace_id": "ws-learner-code", "workspace_name": "Learner code", "workspace_path": str(project)},
        )
        assert started.status_code == 200, started.text
        body = {
            "session_id": started.json()["session_id"],
            "workspace_id": "ws-learner-code",
            "intent": "coach",
            "message": QUESTION,
            "answer_mode": "guided",
            "response_language": "zh-CN",
            "use_agent_loop": agent_loop,
            "provider": _config().model_dump(by_alias=True),
            "api_key": "test-only-key",
            "current_file": {**CURRENT_FILE, "path": str(project / "app.py")},
        }
        chunks: list[str] = []
        complete: dict[str, Any] = {}
        with client.stream("POST", "/turn/stream", json=body, headers={"accept": "text/event-stream"}) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                frame = json.loads(line[5:].strip())
                if isinstance(frame.get("chunk"), str):
                    chunks.append(frame["chunk"])
                if isinstance(frame.get("response"), dict):
                    complete = frame["response"]

    streamed = "".join(chunks)
    _assert_left_out(streamed)
    assert "问题出在 `get` 的第二个调用点。" in streamed
    reply = complete.get("reply") or {}
    _assert_left_out(str(reply.get("content") or ""))
