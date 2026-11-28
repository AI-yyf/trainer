"""Provider protocol must never reach the learner.

Seen with a real model on 2026-11-28 (MiniMax-M2.7 on the tool-free stream, one turn in six): the
visible reply was

    ]<]minimax[>[<tool_call>
    <mm:think>Let me read payments.py to see if there's a pattern.</mm:think>]<]minimax[>[<tool_call>
    <mm:think>Let me read payments.py to see context — maybe there's a similar function pattern.</mm:think>…

The model tried to call a tool on a request that carries none, so the attempt arrived as content:
the provider's control marker, its tool-call tag and its ``<mm:think>`` reasoning (a spelling the
filter did not know). The plain stream releases chunks as they arrive, so all of it reached the
learner. The reasoning filter now hides every one of them, on every streaming path.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.models import CapabilityFlags, ProviderConfig, UserProfile
from app.llm.provider.text import ReasoningBlockFilter, _visible_model_text
from app.llm.provider_service import ProviderService

SENTINEL = "[System: Empty message content sanitised to satisfy protocol]"
LEAK = (
    "]<]minimax[>[<tool_call>\n"
    "<mm:think>Let me read payments.py to see if there's a pattern.</mm:think>]<]minimax[>[<tool_call>\n\n"
    "<mm:think>Let me read payments.py to see context — maybe there's a similar function pattern."
    "</mm:think>]<]minimax[>[<tool_call>\n\n"
    "<mm:think>I should read payments.py maybe for context, but is it needed?</mm:think>]<]minimax[>[<tool_call>"
)


def _feed(parts: list[str]) -> str:
    reasoning_filter = ReasoningBlockFilter()
    return "".join([*(reasoning_filter.push(part) for part in parts), reasoning_filter.flush()])


def test_the_recorded_leak_yields_nothing() -> None:
    assert _feed([LEAK]) == ""


def test_the_leak_is_hidden_whatever_the_chunk_boundaries() -> None:
    for size in (1, 2, 3, 5, 7, 13):
        chunks = [LEAK[i : i + size] for i in range(0, len(LEAK), size)]
        assert _feed(chunks) == "", f"chunk size {size}"


def test_text_before_the_protocol_is_kept_and_nothing_after_it() -> None:
    assert _feed(["The error is on line 8. ", LEAK]) == "The error is on line 8. "


def test_minimax_thinking_is_reasoning_like_plain_think() -> None:
    assert _feed(["<mm:think>plan the answer</mm:think>", "Visible answer."]) == "Visible answer."
    assert _feed(["<think>plan</think>Visible."]) == "Visible."
    # Reasoning cut off by the end of the stream never surfaces.
    assert _feed(["Fine. <mm:think>and then I would"]) == "Fine. "
    assert _visible_model_text("<mm:think>hidden</mm:think>Answer") == "Answer"


def test_a_tool_call_sent_as_content_is_hidden() -> None:
    assert _feed(['Before <tool_call>{"name": "project_read"}</tool_call> After']) == "Before  After"
    assert _feed(['Before <tool_call>{"name": "project_read", "arg']) == "Before "


def test_ordinary_text_with_brackets_and_angle_brackets_is_untouched() -> None:
    text = "Use d[k] (not d[k - 1]) and compare a < b; 3 < 4 and x[0] ] is fine. <notatag> stays."
    for size in (1, 4, 9):
        chunks = [text[i : i + size] for i in range(0, len(text), size)]
        assert _feed(chunks) == text, f"chunk size {size}"


# --- the plain coaching stream end to end ---------------------------------------


def _profile() -> UserProfile:
    return UserProfile(weekly_hours=4, teaching_style="auto", answer_policy="direct")


def _config() -> ProviderConfig:
    return ProviderConfig(
        name="protocol-leak",
        baseUrl="http://127.0.0.1:9/v1",
        apiKeyRef="trainer.default",
        model="minimax-m2",
        capabilities=CapabilityFlags(chat=True, streaming=True),
    )


def _chunk(content: str, finish_reason: str | None = None) -> SimpleNamespace:
    delta = SimpleNamespace(content=content)
    choice = SimpleNamespace(finish_reason=finish_reason, delta=delta)
    return SimpleNamespace(choices=[choice])


@pytest.mark.asyncio
async def test_the_plain_stream_never_yields_provider_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ProviderService(config=_config(), api_key="sk-test")

    async def _iterate() -> Any:
        yield _chunk(LEAK[:120])
        yield _chunk(LEAK[120:])
        yield _chunk("", finish_reason="stop")

    async def fake_create(**_kwargs: object) -> tuple[Any, None]:
        return _iterate(), None

    # monkeypatch keeps the test free of type-ignore comments for the replaced private members.
    monkeypatch.setattr(service, "_get_client", lambda: object())
    monkeypatch.setattr(service, "_create_chat_completion", fake_create)
    monkeypatch.setattr(service, "_plain_completion_uses_agent_binding", lambda: False)

    yielded: list[str] = []
    # Whether the lane then fails or recovers is the lane's business; what matters here is that
    # no chunk it releases carries provider protocol.
    with contextlib.suppress(RuntimeError):
        async for chunk in service.coaching_reply_stream(
            _profile(), "然后呢？", response_language="zh-CN", answer_mode="guided"
        ):
            yielded.append(chunk)

    streamed = "".join(yielded)
    for token in ("minimax", "mm:think", "tool_call", "Let me read"):
        assert token not in streamed, token


# --- the gateway's empty-content sentinel -----------------------------------------


def test_the_empty_content_sentinel_is_never_text() -> None:
    """A gateway puts this sentence where a model message has no content of its own (a step that
    only calls a tool). It entered the history, and the next turn the model echoed it as the last
    line of its reply (seen with a real model on 2026-11-28)."""
    assert _feed([SENTINEL]) == ""
    assert _feed(["Answer.\n", SENTINEL]) == "Answer.\n"
    assert _feed([SENTINEL[:20], SENTINEL[20:] + "After"]) == "After"
    assert _feed(list("A " + SENTINEL + " B")) == "A  B"
    assert _visible_model_text("Answer.\n" + SENTINEL) == "Answer."  # that helper strips whitespace
    # An ordinary sentence that merely starts like it is text.
    assert _feed(["A [System: Empty message content sanitised to satisfy protocols list] B"]) != ""
