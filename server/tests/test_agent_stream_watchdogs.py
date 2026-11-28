"""Two guards on the model stream of a coaching turn, both found with a real model on 2026-11-28.

A stall: a stream that stops producing events is dead, not slow. The first step's own budget is 90 s,
so a dead connection used to hold the learner for 90 s. It is now reported after the idle budget
(60 s by default) and named as a stall.

A deliberating step: a reasoning-first model streams hidden reasoning for as long as it likes. One
measured turn spent 65 s on 1,317 reasoning tokens before its first tool call; another spent 18.5 s
before the answer that followed its tool calls. The step's budget allows that; the learner, who is
still waiting for a first word, should not wait for it. Until the learner has seen visible text in the
turn, any step that shows nothing within the first-output budget (20 s by default) is dropped and
made once more with an explicit instruction to stop deliberating — once per turn. The instruction is
sent to the provider only: the history that later steps and the session see never contains it.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from app.llm.agent_loop import (
    FIRST_OUTPUT_RESTART_HINT,
    AgentProvider,
    CoachAgentLoop,
    FirstOutputBudgetExceeded,
    ProviderStreamStalledError,
    _iterate_with_stream_cancellation,
)
from app.llm.tools import ToolContext, ToolDefinition, ToolRegistry

HISTORY: list[dict[str, Any]] = [
    {"role": "system", "content": "RULES"},
    {"role": "user", "content": "hi"},
]


class FastLoop(CoachAgentLoop):
    """The production bounds keep the guards between 5 s and 5 min; tests need fractions of a second."""

    MIN_AUX_TIMEOUT_SECONDS = 0.05
    MIN_STEP_TIMEOUT_SECONDS = 0.05


def _registry() -> ToolRegistry:
    registry = ToolRegistry()

    async def _echo(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "echoed": args.get("text", "")}

    registry.register(
        ToolDefinition(
            name="echo",
            description="Echo back the text argument.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=_echo,
        )
    )
    return registry


def _context() -> ToolContext:
    return ToolContext(runtime=None, workspace_id="workspace-test", session_id="session-test")


async def _drain(events: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event async for event in events]


async def _unused_call(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
    raise AssertionError("the streaming loop must not use the buffered call")


def _provider(stream_factory: Any) -> AgentProvider:
    return AgentProvider(protocol="openai_chat_completions", call=_unused_call, call_stream=stream_factory)


def _loop(provider: AgentProvider, **kwargs: Any) -> FastLoop:
    return FastLoop(
        provider=provider,
        registry=_registry(),
        context=_context(),
        max_steps=3,
        step_timeout=kwargs.pop("step_timeout", 5),
        first_step_timeout=kwargs.pop("first_step_timeout", 5),
        **kwargs,
    )


def _text(events: list[dict[str, Any]]) -> str:
    return "".join(str(event.get("delta") or "") for event in events if event["type"] == "text")


# --- the iteration wrapper ---------------------------------------------------


async def test_a_silent_stream_is_reported_as_stalled_and_closed() -> None:
    closed: list[bool] = []

    async def silent() -> AsyncIterator[dict[str, Any]]:
        try:
            await asyncio.sleep(30)
            yield {"type": "delta", "delta": "late"}
        finally:
            closed.append(True)

    started = asyncio.get_running_loop().time()
    with pytest.raises(ProviderStreamStalledError) as info:
        await _drain(_iterate_with_stream_cancellation(silent(), None, step_timeout=5.0, idle_timeout=0.2))

    assert info.value.idle_seconds == 0.2
    assert closed == [True]
    assert asyncio.get_running_loop().time() - started < 2


async def test_a_silent_stream_is_stalled_with_a_cancellation_event_too() -> None:
    async def silent() -> AsyncIterator[dict[str, Any]]:
        await asyncio.sleep(30)
        yield {"type": "delta", "delta": "late"}

    with pytest.raises(ProviderStreamStalledError):
        await _drain(
            _iterate_with_stream_cancellation(silent(), asyncio.Event(), step_timeout=5.0, idle_timeout=0.2)
        )


async def test_a_stream_that_keeps_talking_is_never_stalled() -> None:
    async def chatty() -> AsyncIterator[dict[str, Any]]:
        for _ in range(8):
            await asyncio.sleep(0.06)
            yield {"type": "delta", "delta": "x"}

    events = await _drain(_iterate_with_stream_cancellation(chatty(), None, idle_timeout=0.2))

    assert events == [{"type": "delta", "delta": "x"}] * 8


async def test_the_step_budget_still_ends_a_step_that_outlives_it() -> None:
    async def endless() -> AsyncIterator[dict[str, Any]]:
        while True:
            await asyncio.sleep(0.03)
            yield {"type": "delta", "delta": "x"}

    with pytest.raises(asyncio.TimeoutError) as info:
        await _drain(_iterate_with_stream_cancellation(endless(), None, step_timeout=0.3, idle_timeout=5.0))

    assert not isinstance(info.value, ProviderStreamStalledError)


# --- the first-output restart ------------------------------------------------


async def test_a_deliberating_first_step_is_restarted_once_with_an_explicit_hint() -> None:
    requests: list[list[dict[str, Any]]] = []

    async def stream(messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> AsyncIterator[dict[str, Any]]:
        requests.append([dict(message) for message in messages])
        if len(requests) == 1:
            for _ in range(40):  # hidden reasoning only, for two seconds
                await asyncio.sleep(0.05)
                yield {"type": "delta", "delta": "still thinking ", "safe_to_stream": False}
            return
        yield {"type": "delta", "delta": "Visible reply.", "safe_to_stream": True}
        yield {"type": "final", "content": "Visible reply.", "tool_calls": [], "stop_reason": "stop"}

    history = [dict(message) for message in HISTORY]
    loop = _loop(_provider(stream), first_output_restart_seconds=0.3)

    events = await _drain(loop.run_stream(history))

    assert len(requests) == 2
    assert requests[0][0]["content"] == "RULES"
    assert requests[1][0]["content"] == f"RULES\n\n{FIRST_OUTPUT_RESTART_HINT.format(budget=0.3)}"
    assert requests[1][1:] == requests[0][1:]
    assert [message["content"] for message in history] == ["RULES", "hi"]
    restarts = [event for event in events if event["type"] == "stream_restart"]
    assert restarts == [{"type": "stream_restart", "reason": "first_output_budget", "after_seconds": 0.3}]
    assert _text(events) == "Visible reply."
    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "completed"
    assert final["content"] == "Visible reply."


async def test_no_restart_when_the_first_step_shows_something_at_once() -> None:
    calls = 0

    async def stream(messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> AsyncIterator[dict[str, Any]]:
        nonlocal calls
        calls += 1
        assert "Do not deliberate further" not in str(messages[0]["content"])
        yield {"type": "delta", "delta": "Visible reply.", "safe_to_stream": True}
        yield {"type": "final", "content": "Visible reply.", "tool_calls": [], "stop_reason": "stop"}

    events = await _drain(_loop(_provider(stream), first_output_restart_seconds=0.3).run_stream(list(HISTORY)))

    assert calls == 1
    assert not [event for event in events if event["type"] == "stream_restart"]
    assert _text(events) == "Visible reply."


async def test_a_tool_call_also_counts_as_the_first_output() -> None:
    requests: list[list[dict[str, Any]]] = []

    async def stream(messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> AsyncIterator[dict[str, Any]]:
        requests.append([dict(message) for message in messages])
        if len(requests) == 1:
            yield {
                "type": "final",
                "content": "",
                "tool_calls": [{"id": "c1", "name": "echo", "arguments": {"text": "ping"}}],
                "stop_reason": "tool_calls",
            }
            return
        yield {"type": "delta", "delta": "I heard ping.", "safe_to_stream": True}
        yield {"type": "final", "content": "I heard ping.", "tool_calls": [], "stop_reason": "stop"}

    events = await _drain(_loop(_provider(stream), first_output_restart_seconds=0.3).run_stream(list(HISTORY)))

    assert len(requests) == 2
    assert not [event for event in events if event["type"] == "stream_restart"]
    assert "Do not deliberate further" not in str(requests[1][0]["content"])
    assert _text(events) == "I heard ping."


async def test_the_restart_happens_at_most_once() -> None:
    requests = 0

    async def stream(messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> AsyncIterator[dict[str, Any]]:
        nonlocal requests
        requests += 1
        for _ in range(40):
            await asyncio.sleep(0.05)
            yield {"type": "delta", "delta": "still thinking ", "safe_to_stream": False}

    events = await _drain(
        _loop(_provider(stream), first_output_restart_seconds=0.3, first_step_timeout=1.2).run_stream(list(HISTORY))
    )

    assert requests == 2
    assert len([event for event in events if event["type"] == "stream_restart"]) == 1
    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "timeout"


async def test_a_deliberating_step_after_the_tools_is_restarted_too() -> None:
    """The first visible text of a turn usually comes after its tool calls; that step owes the
    learner the first word as much as the first step does (measured: 18.5 s of reasoning there)."""
    requests: list[list[dict[str, Any]]] = []

    async def stream(messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> AsyncIterator[dict[str, Any]]:
        requests.append([dict(message) for message in messages])
        if len(requests) == 1:
            yield {
                "type": "final",
                "content": "",
                "tool_calls": [{"id": "c1", "name": "echo", "arguments": {"text": "ping"}}],
                "stop_reason": "tool_calls",
            }
            return
        if len(requests) == 2:
            for _ in range(12):  # three times the budget, with nothing for the learner
                await asyncio.sleep(0.05)
                yield {"type": "delta", "delta": "thinking ", "safe_to_stream": False}
            return
        yield {"type": "delta", "delta": "I heard ping.", "safe_to_stream": True}
        yield {"type": "final", "content": "I heard ping.", "tool_calls": [], "stop_reason": "stop"}

    events = await _drain(_loop(_provider(stream), first_output_restart_seconds=0.2).run_stream(list(HISTORY)))

    assert len(requests) == 3
    assert "Do not deliberate further" not in str(requests[1][0]["content"])
    assert "Do not deliberate further" in requests[2][0]["content"]
    assert len([event for event in events if event["type"] == "stream_restart"]) == 1
    assert _text(events) == "I heard ping."
    assert next(event for event in events if event["type"] == "final")["stop_reason"] == "completed"


async def test_once_the_learner_has_seen_text_no_step_is_restarted_for_being_slow() -> None:
    requests = 0

    async def stream(messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> AsyncIterator[dict[str, Any]]:
        nonlocal requests
        requests += 1
        if requests == 1:
            yield {"type": "delta", "delta": "I will look at that.", "safe_to_stream": True}
            yield {
                "type": "final",
                "content": "I will look at that.",
                "tool_calls": [{"id": "c1", "name": "echo", "arguments": {"text": "ping"}}],
                "stop_reason": "tool_calls",
            }
            return
        await asyncio.sleep(0.6)
        yield {"type": "delta", "delta": "I heard ping.", "safe_to_stream": True}
        yield {"type": "final", "content": "I heard ping.", "tool_calls": [], "stop_reason": "stop"}

    events = await _drain(_loop(_provider(stream), first_output_restart_seconds=0.2).run_stream(list(HISTORY)))

    assert requests == 2
    assert not [event for event in events if event["type"] == "stream_restart"]
    assert _text(events) == "I will look at that.I heard ping."


async def test_the_restart_hint_is_absent_from_what_the_tool_step_receives() -> None:
    requests: list[list[dict[str, Any]]] = []

    async def stream(messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> AsyncIterator[dict[str, Any]]:
        requests.append([dict(message) for message in messages])
        if len(requests) == 1:
            for _ in range(20):
                await asyncio.sleep(0.05)
                yield {"type": "delta", "delta": "thinking", "safe_to_stream": False}
            return
        if len(requests) == 2:
            yield {
                "type": "final",
                "content": "",
                "tool_calls": [{"id": "c1", "name": "echo", "arguments": {"text": "ping"}}],
                "stop_reason": "tool_calls",
            }
            return
        yield {"type": "delta", "delta": "I heard ping.", "safe_to_stream": True}
        yield {"type": "final", "content": "I heard ping.", "tool_calls": [], "stop_reason": "stop"}

    await _drain(_loop(_provider(stream), first_output_restart_seconds=0.3).run_stream(list(HISTORY)))

    assert len(requests) == 3
    assert "Do not deliberate further" in requests[1][0]["content"]
    assert "Do not deliberate further" not in requests[2][0]["content"]


# --- a stalled first step through the loop -------------------------------------


async def test_a_stalled_first_step_ends_the_turn_as_a_stall() -> None:
    async def stream(messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> AsyncIterator[dict[str, Any]]:
        await asyncio.sleep(30)
        yield {"type": "delta", "delta": "late", "safe_to_stream": True}

    started = asyncio.get_running_loop().time()
    events = await _drain(
        _loop(_provider(stream), stream_idle_timeout=0.2, first_output_restart_seconds=0).run_stream(list(HISTORY))
    )
    elapsed = asyncio.get_running_loop().time() - started

    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "timeout"
    assert final["stalled"] is True
    assert "stalled" in str(final["error"]) and "0.2s" in str(final["error"])
    assert elapsed < 3


def _production_loop(**kwargs: Any) -> CoachAgentLoop:
    return CoachAgentLoop(provider=_provider(None), registry=_registry(), context=_context(), **kwargs)


def test_the_default_budgets_and_their_bounds() -> None:
    loop = _production_loop()

    assert loop.stream_idle_timeout == CoachAgentLoop.DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS == 60.0
    assert loop.first_output_restart_seconds == CoachAgentLoop.DEFAULT_FIRST_OUTPUT_RESTART_SECONDS == 20.0
    off = _production_loop(stream_idle_timeout=0, first_output_restart_seconds=0)
    assert off.stream_idle_timeout == 0 and off.first_output_restart_seconds == 0
    huge = _production_loop(stream_idle_timeout=10_000, first_output_restart_seconds=10_000)
    assert huge.stream_idle_timeout == CoachAgentLoop.MAX_STEP_TIMEOUT_SECONDS
    assert huge.first_output_restart_seconds == CoachAgentLoop.MAX_STEP_TIMEOUT_SECONDS
    assert _production_loop(first_output_restart_seconds=1).first_output_restart_seconds == 5.0


def test_the_first_output_error_is_not_a_timeout() -> None:
    error = FirstOutputBudgetExceeded(20.0)

    assert error.budget_seconds == 20.0
    assert not isinstance(error, asyncio.TimeoutError)
    assert isinstance(ProviderStreamStalledError(60.0), asyncio.TimeoutError)
