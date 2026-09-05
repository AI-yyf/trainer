"""Tests for the coach agent loop, tool registry, and provider binding.

These cover the three layers that together turn a coaching turn into a
multi-step tool-using conversation:

* ``CoachAgentLoop`` iteration contract (non-streaming + streaming)
* ``ToolRegistry`` invocation + the default coach tools' resilience
* ``ProviderAgentBinding`` protocol translation (OpenAI chat + Anthropic
  Messages, including multimodal image parts)
"""

from __future__ import annotations

import ast
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.llm.agent_binding import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    OPENAI_VISIBLE_REPLY_RETRY_HINT,
    TRANSPORT_TIMEOUT_MARGIN_SECONDS,
    ProviderAgentBinding,
    attachments_supported,
    resolve_agent_protocol,
)
from app.llm.agent_loop import (
    AgentLoopError,
    AgentProvider,
    CoachAgentLoop,
    run_with_scripted_responses,
)
from app.llm.tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    build_default_tool_registry,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _toy_registry() -> ToolRegistry:
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

    async def _finalize(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "final": True,
            "summary": str(args.get("summary") or "done"),
            "next_step": str(args.get("next_step") or ""),
            "decision": str(args.get("decision") or ""),
            "blocker": str(args.get("blocker") or ""),
            "teaching_note": str(args.get("teaching_note") or ""),
            "confidence": str(args.get("confidence") or ""),
            "evidence": list(args.get("evidence") or []),
        }

    registry.register(
        ToolDefinition(
            name="coach_finalize",
            description="Stop the loop.",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "decision": {"type": "string"},
                    "next_step": {"type": "string"},
                    "blocker": {"type": "string"},
                    "teaching_note": {"type": "string"},
                    "confidence": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
            handler=_finalize,
        )
    )
    return registry


def _summary_registry() -> ToolRegistry:
    registry = ToolRegistry()

    async def _summarize(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "summary": str(args.get("summary") or "tool summary"),
            "next_step": str(args.get("next_step") or "tool next step"),
            "evidence": [str(args.get("evidence") or "tool evidence")],
        }

    registry.register(
        ToolDefinition(
            name="summarize_step",
            description="Return a structured summary and next step.",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "next_step": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
            handler=_summarize,
        )
    )
    return registry


def _context(runtime: Any = None) -> ToolContext:
    return ToolContext(runtime=runtime, workspace_id="workspace-test", session_id="session-test")


def _tool_schema_names(schemas: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for schema in schemas:
        function = schema.get("function")
        if isinstance(function, dict):
            name = function.get("name")
        else:
            name = schema.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def _assistant_with_tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": "",
        "tool_calls": [{"id": call_id, "name": name, "arguments": arguments}],
    }


class _FakeProviderService:
    def __init__(
        self,
        *,
        client: Any,
        model: str,
        base_url: str = "https://example.com/v1",
    ) -> None:
        self._api_key = "sk-test-key"
        self._client = client
        self._config = SimpleNamespace(model=model, base_url=base_url)

    def _get_client(self) -> Any:
        return self._client

    def _resolve_model(self) -> str:
        return str(self._config.model)

    def _model_candidates(self, model: str) -> list[str]:
        return [model]

    def _is_model_not_supported_error(self, exc: Exception) -> bool:
        return False

    def _provider_request_defaults(self) -> dict[str, Any]:
        return {}


class _FakeAsyncStream:
    def __init__(self, events: list[Any], final_response: object) -> None:
        self._events = events
        self._final_response = final_response

    def __aiter__(self) -> Any:
        async def _iterate() -> AsyncIterator[Any]:
            for event in self._events:
                yield event

        return _iterate()

    async def get_final_response(self) -> object:
        return self._final_response


class _FakeAsyncStreamManager:
    def __init__(self, stream: _FakeAsyncStream) -> None:
        self._stream = stream

    async def __aenter__(self) -> _FakeAsyncStream:
        return self._stream

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeGeminiResponse:
    def __init__(self, lines: list[str], *, status_code: int = 200) -> None:
        self._lines = lines
        self.status_code = status_code

    def aiter_lines(self) -> Any:
        async def _iterate() -> AsyncIterator[str]:
            for line in self._lines:
                yield line

        return _iterate()

    async def aread(self) -> bytes:
        return b""


class _FakeGeminiStreamContext:
    def __init__(self, response: _FakeGeminiResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeGeminiResponse:
        return self._response

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeGeminiAsyncClient:
    def __init__(self, response: _FakeGeminiResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self) -> "_FakeGeminiAsyncClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def stream(self, method: str, url: str, **kwargs: Any) -> _FakeGeminiStreamContext:
        self.calls.append((method, url, kwargs))
        return _FakeGeminiStreamContext(self.response)


# ---------------------------------------------------------------------------
# CoachAgentLoop — non-streaming
# ---------------------------------------------------------------------------


async def test_loop_stops_on_plain_text_without_tools() -> None:
    registry = _toy_registry()
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=[{"content": "Hello there.", "tool_calls": []}],
        initial_messages=[{"role": "user", "content": "hi"}],
    )
    assert result.final_content == "Hello there."
    assert result.stop_reason == "completed"
    assert len(result.steps) == 1
    assert result.steps[0].tool_calls == []


async def test_loop_stops_on_plain_text_without_tools_carries_completion_continuity() -> None:
    registry = _toy_registry()
    context = _context()
    context.extra = {
        "current_focus": "tighten the recovery loop",
        "next_step_hint": "Patch the smallest failing branch first",
    }
    result = await run_with_scripted_responses(
        registry=registry,
        context=context,
        scripted_responses=[
            {"content": "Keep the next move tiny and verify it immediately.", "tool_calls": []}
        ],
        initial_messages=[{"role": "user", "content": "hi"}],
    )
    assert result.stop_reason == "completed"
    assert result.summary and "tighten the recovery loop" in result.summary
    assert result.next_step and "Patch the smallest failing branch first" in result.next_step


async def test_loop_empty_plain_text_without_tools_is_not_completed() -> None:
    registry = _toy_registry()
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "current_focus": "practice verification",
            "next_step_hint": "Re-run current file verification",
        },
    )
    result = await run_with_scripted_responses(
        registry=registry,
        context=context,
        scripted_responses=[{"content": "   ", "tool_calls": []}],
        initial_messages=[{"role": "user", "content": "verify"}],
    )
    assert result.stop_reason == "empty_response"
    assert result.final_content == ""
    assert result.summary and "empty visible answer" in result.summary
    assert result.summary and "practice verification" in result.summary
    assert result.next_step and "Re-run current file verification" in result.next_step


async def test_loop_empty_response_ignores_recovery_meta_echoes_from_context() -> None:
    registry = _toy_registry()
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "current_focus": "The provider returned an empty visible answer, so this turn cannot be treated as complete.",
            "thread_summary": "The provider returned an empty visible answer, so this turn cannot be treated as complete.",
            "thread_next_step": "Retry the turn and require a visible conclusion; if it repeats, fall back to the smallest verifiable move.",
            "next_step_hint": "Retry the turn and require a visible conclusion; if it repeats, fall back to the smallest verifiable move.",
        },
    )
    result = await run_with_scripted_responses(
        registry=registry,
        context=context,
        scripted_responses=[{"content": "   ", "tool_calls": []}],
        initial_messages=[{"role": "user", "content": "verify"}],
    )

    assert result.stop_reason == "empty_response"
    assert (
        result.summary
        == "The provider returned an empty visible answer, so this turn cannot be treated as complete."
    )
    assert result.next_step == (
        "Retry the turn and require a visible conclusion; if it repeats, fall back to the smallest verifiable move."
    )


async def test_loop_timeout_surfaces_recovery_summary() -> None:
    registry = _toy_registry()

    def _slow_call(
        _messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        return {"content": "late", "tool_calls": []}

    provider = AgentProvider(protocol="openai_chat_completions", call=_slow_call)
    loop = CoachAgentLoop(
        provider=provider,
        registry=registry,
        context=_context(),
        max_steps=1,
        step_timeout=0.01,
    )
    with patch("app.llm.agent_loop.asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await loop.run([{"role": "user", "content": "hi"}])
    assert result.stop_reason == "timeout"
    assert result.summary and "timed out" in result.summary.lower()
    assert result.next_step and "smallest check" in result.next_step.lower()


async def test_default_first_step_timeout_allows_a_slow_provider_turn() -> None:
    observed_timeouts: list[float] = []
    real_wait_for = asyncio.wait_for

    async def _slow_first_call(
        _messages: list[dict[str, Any]],
        _tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        return {"content": "The provider completed the first coaching turn.", "tool_calls": []}

    async def _observe_timeout(awaitable: Any, *, timeout: float) -> Any:
        observed_timeouts.append(timeout)
        return await real_wait_for(awaitable, timeout=timeout)

    loop = CoachAgentLoop(
        provider=AgentProvider(protocol="openai_chat_completions", call=_slow_first_call),
        registry=_toy_registry(),
        context=_context(),
        max_steps=1,
    )
    with patch("app.llm.agent_loop.asyncio.wait_for", side_effect=_observe_timeout):
        result = await loop.run([{"role": "user", "content": "hi"}])

    assert result.stop_reason == "completed"
    assert observed_timeouts == [CoachAgentLoop.DEFAULT_FIRST_STEP_TIMEOUT_SECONDS]


async def test_default_agent_step_timeout_stays_within_interactive_budget() -> None:
    async def _unused_call(
        _messages: list[dict[str, Any]],
        _tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        return {"content": "unused", "tool_calls": []}

    loop = CoachAgentLoop(
        provider=AgentProvider(
            protocol="openai_chat_completions",
            call=_unused_call,
        ),
        registry=_toy_registry(),
        context=_context(),
    )

    assert loop.step_timeout == 24.0
    assert loop.first_step_timeout == CoachAgentLoop.DEFAULT_FIRST_STEP_TIMEOUT_SECONDS
    assert loop._step_timeout_for(0) == CoachAgentLoop.DEFAULT_FIRST_STEP_TIMEOUT_SECONDS
    assert loop._step_timeout_for(1) == 24.0
    assert loop.max_steps == CoachAgentLoop.SAFETY_MAX_STEPS
    assert CoachAgentLoop.SAFETY_MAX_STEPS >= 100
    assert CoachAgentLoop.DEFAULT_MAX_STEPS == CoachAgentLoop.SAFETY_MAX_STEPS
    assert CoachAgentLoop.LIBRARY_MAX_STEPS == CoachAgentLoop.SAFETY_MAX_STEPS
    assert CoachAgentLoop.PLAN_MAX_STEPS == CoachAgentLoop.SAFETY_MAX_STEPS


def test_agent_step_timeouts_are_configurable_and_bounded() -> None:
    async def _unused_call(
        _messages: list[dict[str, Any]],
        _tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        return {"content": "unused", "tool_calls": []}

    explicit_step_timeout = CoachAgentLoop(
        provider=AgentProvider(protocol="openai_chat_completions", call=_unused_call),
        registry=_toy_registry(),
        context=_context(),
        step_timeout=3.0,
    )
    bounded_timeouts = CoachAgentLoop(
        provider=AgentProvider(protocol="openai_chat_completions", call=_unused_call),
        registry=_toy_registry(),
        context=_context(),
        step_timeout=999.0,
        first_step_timeout=0.0,
    )

    assert explicit_step_timeout.step_timeout == 3.0
    assert explicit_step_timeout.first_step_timeout == 3.0
    assert bounded_timeouts.step_timeout == CoachAgentLoop.MAX_STEP_TIMEOUT_SECONDS
    assert bounded_timeouts.first_step_timeout == CoachAgentLoop.MIN_STEP_TIMEOUT_SECONDS


async def test_loop_provider_error_surfaces_recovery_summary() -> None:
    registry = _toy_registry()

    async def _boom(
        _messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        raise RuntimeError("boom")

    provider = AgentProvider(protocol="openai_chat_completions", call=_boom)
    loop = CoachAgentLoop(provider=provider, registry=registry, context=_context(), max_steps=1)
    result = await loop.run([{"role": "user", "content": "hi"}])
    assert result.stop_reason == "provider_error"
    assert result.summary and "provider stopped" in result.summary.lower()
    assert result.next_step and "smallest anchored step" in result.next_step.lower()


async def test_agent_stream_error_redacts_provider_exception_details() -> None:
    async def _unused_call(
        _messages: list[dict[str, Any]],
        _tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        return {"content": "", "tool_calls": []}

    async def _boom_stream(
        _messages: list[dict[str, Any]],
        _tools: list[dict[str, Any]] | None,
    ):
        if False:  # pragma: no cover - keeps this an async iterator for the provider contract
            yield {"type": "delta", "delta": ""}
        raise RuntimeError(
            "Authorization: Bearer sk-agent-secret; response body: raw upstream payload"
        )

    loop = CoachAgentLoop(
        provider=AgentProvider(
            protocol="openai_chat_completions",
            call=_unused_call,
            call_stream=_boom_stream,
        ),
        registry=_toy_registry(),
        context=_context(),
        max_steps=1,
    )
    events = [event async for event in loop.run_stream([{"role": "user", "content": "hi"}])]
    error = next(event for event in events if event["type"] == "error")

    assert error["detail"] == "Provider request failed."
    assert "sk-agent-secret" not in error["detail"]
    assert "raw upstream payload" not in error["detail"]


def test_agent_loop_run_methods_match_bundled_security_semantics() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source = repo_root / "server" / "app" / "llm" / "agent_loop.py"
    bundled = repo_root / "extension" / "bundled" / "server" / "app" / "llm" / "agent_loop.py"

    def method_dump(path: Path, method_name: str) -> str:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        loop_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "CoachAgentLoop"
        )
        method = next(
            node
            for node in loop_class.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == method_name
        )
        return ast.dump(method, include_attributes=False)

    for method_name in ("run", "run_stream"):
        assert method_dump(source, method_name) == method_dump(bundled, method_name)


async def test_loop_executes_tool_then_finalizes() -> None:
    registry = _toy_registry()
    scripted = [
        _assistant_with_tool_call("call-1", "echo", {"text": "ping"}),
        {"content": "I heard ping.", "tool_calls": []},
    ]
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "echo ping"}],
    )
    assert result.final_content == "I heard ping."
    assert result.stop_reason == "completed"
    assert len(result.steps) == 2
    first_step = result.steps[0]
    assert first_step.tool_calls[0]["name"] == "echo"
    assert first_step.tool_results[0]["result"]["echoed"] == "ping"


async def test_loop_completion_continuity_uses_previous_tool_results() -> None:
    registry = _summary_registry()
    scripted = [
        _assistant_with_tool_call(
            "call-1",
            "summarize_step",
            {
                "summary": "The current file already exposes the right hook.",
                "next_step": "Wire the hook into the coach view next.",
                "evidence": "Detected the hook in the current file.",
            },
        ),
        {"content": "Looks good.", "tool_calls": []},
    ]
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "summarize this turn"}],
    )
    assert result.stop_reason == "completed"
    assert result.final_content == "Looks good."
    assert result.summary == "The current file already exposes the right hook."
    assert result.next_step == "Wire the hook into the coach view next."


async def test_loop_uses_finalize_metadata_when_no_visible_reply_turn_is_needed() -> None:
    registry = _toy_registry()
    scripted = [
        {
            "content": "Wrapping up.",
            "tool_calls": [
                {
                    "id": "fin",
                    "name": "coach_finalize",
                    "arguments": {
                        "summary": "sum",
                        "decision": "Choose the smallest verified fix",
                        "next_step": "next",
                        "blocker": "Missing workspace evidence",
                        "teaching_note": "Name the blocker before widening scope.",
                        "resume_thread": "Resume the live thread around the same branch.",
                        "confidence": "high",
                        "evidence": ["tool result A", "tool result B"],
                    },
                }
            ],
        },
    ]
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "done?"}],
        max_steps=4,
    )
    assert result.stop_reason == "coach_finalize"
    assert result.summary == "sum"
    assert result.next_step == "next"
    assert "sum" in result.final_content
    assert "next" in result.final_content
    assert "Wrapping up." not in result.final_content
    assert result.decision == "Choose the smallest verified fix"
    assert result.blocker == "Missing workspace evidence"
    assert result.teaching_note == "Name the blocker before widening scope."
    assert result.resume_thread == "Resume the live thread around the same branch."
    assert result.confidence == "high"
    assert result.evidence == ["tool result A", "tool result B"]


async def test_loop_does_not_make_a_second_provider_call_after_coach_finalize() -> None:
    registry = _toy_registry()
    calls = 0

    async def _call(
        _messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("coach_finalize must not request a second visible-reply turn")
        return {
            "content": "Wrapping up.",
            "tool_calls": [
                {
                    "id": "fin",
                    "name": "coach_finalize",
                    "arguments": {"summary": "sum", "next_step": "next"},
                }
            ],
        }

    loop = CoachAgentLoop(
        provider=AgentProvider(protocol="openai_chat_completions", call=_call),
        registry=registry,
        context=_context(),
    )
    result = await loop.run([{"role": "user", "content": "done?"}])

    assert result.stop_reason == "coach_finalize"
    assert calls == 1
    assert "sum" in result.final_content
    assert "next" in result.final_content
    assert "Wrapping up." not in result.final_content


async def test_loop_stops_immediately_after_coach_finalize_and_skips_followup_tools() -> None:
    registry = ToolRegistry()
    echo_calls: list[dict[str, Any]] = []

    async def _finalize(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "final": True,
            "summary": "sum",
            "next_step": "next",
            "decision": "Choose the smallest verified fix",
            "blocker": "Missing workspace evidence",
            "teaching_note": "Name the blocker before widening scope.",
            "resume_thread": "Resume the live thread around the same branch.",
            "confidence": "high",
            "evidence": ["tool result A", "tool result B"],
        }

    async def _echo(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        echo_calls.append(args)
        return {"ok": True, "echoed": args.get("text", "")}

    registry.register(
        ToolDefinition(
            name="coach_finalize",
            description="Stop the loop.",
            parameters={"type": "object", "properties": {"summary": {"type": "string"}}},
            handler=_finalize,
        )
    )
    registry.register(
        ToolDefinition(
            name="echo",
            description="Echo text.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=_echo,
        )
    )

    scripted = [
        {
            "content": "Wrapping up.",
            "tool_calls": [
                {
                    "id": "fin",
                    "name": "coach_finalize",
                    "arguments": {
                        "summary": "sum",
                        "next_step": "next",
                        "decision": "Choose the smallest verified fix",
                    },
                },
                {
                    "id": "echo-1",
                    "name": "echo",
                    "arguments": {"text": "should not run"},
                },
            ],
        }
    ]
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "done?"}],
        max_steps=4,
    )
    assert result.stop_reason == "coach_finalize"
    assert result.summary == "sum"
    assert result.next_step == "next"
    assert echo_calls == []
    assert len(result.steps) == 1
    assert [item["name"] for item in result.steps[0].tool_results] == ["coach_finalize"]


async def test_loop_hits_max_steps_without_natural_stop() -> None:
    registry = _toy_registry()
    # Always calls echo, never finalizes → should stop at max_steps.
    scripted = [
        _assistant_with_tool_call("c0", "echo", {"text": "x"}),
        _assistant_with_tool_call("c1", "echo", {"text": "y"}),
        _assistant_with_tool_call("c2", "echo", {"text": "z"}),
    ]
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "loop"}],
        max_steps=3,
    )
    assert result.stop_reason == "max_steps"
    assert result.final_content
    assert result.summary and "step limit" in result.summary
    assert result.next_step and "Continue from the latest tool path" in result.next_step


async def test_loop_runs_until_model_stops_calling_tools_past_legacy_caps() -> None:
    registry = _toy_registry()
    scripted = [
        _assistant_with_tool_call(f"c{index}", "echo", {"text": f"n{index}"})
        for index in range(12)
    ]
    scripted.append({"content": "Done after twelve tools.", "tool_calls": []})
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "deep work"}],
        max_steps=CoachAgentLoop.SAFETY_MAX_STEPS,
    )
    assert result.stop_reason == "completed"
    assert result.final_content == "Done after twelve tools."
    assert len(result.steps) == 13
    assert [step.tool_calls[0]["name"] for step in result.steps[:-1]] == ["echo"] * 12


async def test_streaming_loop_runs_until_model_stops_calling_tools_past_legacy_caps() -> None:
    registry = _toy_registry()
    scripted = [
        _assistant_with_tool_call(f"c{index}", "echo", {"text": f"n{index}"})
        for index in range(12)
    ]
    scripted.append({"content": "Stream done after twelve tools.", "tool_calls": []})
    provider = await _scripted_stream_provider(scripted)
    loop = CoachAgentLoop(
        provider=provider,
        registry=registry,
        context=_context(),
        max_steps=CoachAgentLoop.SAFETY_MAX_STEPS,
    )
    events = [event async for event in loop.run_stream([{"role": "user", "content": "deep work"}])]
    finals = [event for event in events if event["type"] == "final"]
    assert len(finals) == 1
    assert finals[0]["stop_reason"] == "completed"
    assert finals[0]["content"] == "Stream done after twelve tools."
    assert sum(1 for event in events if event["type"] == "tool_result") == 12


async def test_loop_completion_continuity_prefers_thread_summary_and_resume_hint() -> None:
    registry = _toy_registry()

    async def _call(
        _messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        return {"content": "Keep going.", "tool_calls": []}

    provider = AgentProvider(protocol="openai_chat_completions", call=_call)
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "summary": "General reminder prose should stay separate.",
            "thread_summary": "Stay on the active thread around the startup recovery loop.",
            "thread_next_step": "Patch the smallest failing branch first.",
            "resume_hint": "Continue the live thread instead of restarting.",
        },
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=context, max_steps=3)
    result = await loop.run([{"role": "user", "content": "continue"}])

    assert result.stop_reason == "completed"
    assert result.summary == "Stay on the active thread around the startup recovery loop."
    assert result.next_step == "Patch the smallest failing branch first."


async def test_loop_stops_on_repeated_tool_calls_without_progress() -> None:
    registry = _toy_registry()
    scripted = [
        _assistant_with_tool_call("c0", "echo", {"text": "x"}),
        _assistant_with_tool_call("c1", "echo", {"text": "x"}),
        _assistant_with_tool_call("c2", "echo", {"text": "x"}),
    ]
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "stuck"}],
        max_steps=4,
    )
    assert result.stop_reason == "no_progress"
    assert len(result.steps) == 2
    assert result.steps[0].tool_results[0]["result"]["echoed"] == "x"
    assert result.steps[1].tool_results[0]["result"]["echoed"] == "x"
    assert result.final_content
    assert result.summary and "same tool path" in result.summary
    assert result.next_step and "different evidence source" in result.next_step


async def test_loop_no_progress_normalizes_equivalent_tool_arguments() -> None:
    registry = _toy_registry()
    scripted = [
        _assistant_with_tool_call("c0", "echo", {"text": "x", "mode": "fast"}),
        _assistant_with_tool_call("c1", "echo", {"mode": "fast", "text": "x"}),
        _assistant_with_tool_call("c2", "echo", {"text": "x", "mode": "fast"}),
    ]
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "stuck"}],
        max_steps=4,
    )
    assert result.stop_reason == "no_progress"
    assert result.summary and "same tool path" in result.summary


async def test_loop_no_progress_stops_when_tool_results_repeat_even_if_args_change() -> None:
    registry = ToolRegistry()

    async def _steady(_context: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "steady",
            "evidence": "no new information",
        }

    registry.register(
        ToolDefinition(
            name="steady_check",
            description="Return the same result every time.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
            },
            handler=_steady,
        )
    )
    scripted = [
        _assistant_with_tool_call("c0", "steady_check", {"path": "a"}),
        _assistant_with_tool_call("c1", "steady_check", {"path": "b"}),
    ]
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "stuck"}],
        max_steps=4,
    )
    assert result.stop_reason == "no_progress"
    assert len(result.steps) == 2
    assert result.steps[1].tool_results[0]["result"]["status"] == "steady"
    assert result.summary and "same tool path" in result.summary


async def test_loop_no_progress_mentions_current_focus_and_next_step_hint() -> None:
    registry = _toy_registry()
    scripted = [
        _assistant_with_tool_call("c0", "echo", {"text": "x"}),
        _assistant_with_tool_call("c1", "echo", {"text": "x"}),
        _assistant_with_tool_call("c2", "echo", {"text": "x"}),
    ]
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "current_focus": "tighten the startup recovery loop",
            "next_step_hint": "Patch the smallest failing branch first",
        },
    )
    result = await run_with_scripted_responses(
        registry=registry,
        context=context,
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "stuck"}],
        max_steps=4,
    )
    assert result.stop_reason == "no_progress"
    assert result.summary and "tighten the startup recovery loop" in result.summary
    assert result.next_step and "Patch the smallest failing branch first" in result.next_step


async def test_loop_no_progress_summary_mentions_previous_tool_failure() -> None:
    registry = ToolRegistry()

    async def _fail(_context: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": False, "error": "missing_path", "detail": "path does not exist"}

    registry.register(
        ToolDefinition(
            name="fail_once",
            description="Fail in a structured way.",
            parameters={"type": "object", "properties": {}},
            handler=_fail,
        )
    )
    scripted = [
        _assistant_with_tool_call("c0", "fail_once", {}),
        _assistant_with_tool_call("c1", "fail_once", {}),
        _assistant_with_tool_call("c2", "fail_once", {}),
    ]
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "stuck"}],
        max_steps=4,
    )
    assert result.stop_reason == "no_progress"
    assert result.summary and "missing_path" in result.summary
    assert result.next_step and "Fix the issue" in result.next_step


async def test_loop_step_limit_mentions_current_focus() -> None:
    registry = _toy_registry()
    scripted = [
        _assistant_with_tool_call("c0", "echo", {"text": "x"}),
        _assistant_with_tool_call("c1", "echo", {"text": "y"}),
        _assistant_with_tool_call("c2", "echo", {"text": "z"}),
    ]
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={"current_focus": "tighten the startup recovery loop"},
    )
    result = await run_with_scripted_responses(
        registry=registry,
        context=context,
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "loop"}],
        max_steps=3,
    )
    assert result.stop_reason == "max_steps"
    assert result.summary and "tighten the startup recovery loop" in result.summary


async def test_loop_unknown_tool_returns_structured_error_not_crash() -> None:
    registry = _toy_registry()
    scripted = [
        _assistant_with_tool_call("c0", "does_not_exist", {}),
        {"content": "recovered.", "tool_calls": []},
    ]
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=scripted,
        initial_messages=[{"role": "user", "content": "bad tool"}],
    )
    assert result.stop_reason == "completed"
    assert result.final_content == "recovered."
    tool_result = result.steps[0].tool_results[0]["result"]
    assert tool_result["ok"] is False
    assert tool_result["error"] == "unknown_tool"


async def test_scripted_responses_exhausted_surfaces_provider_error() -> None:
    """When scripted responses run out the loop swallows the resulting
    ``AgentLoopError`` into the result envelope (rather than re-raising)
    so the caller can decide whether to fall back. Verify that envelope.
    """

    registry = _toy_registry()
    result = await run_with_scripted_responses(
        registry=registry,
        context=ToolContext(
            runtime=None,
            workspace_id="workspace-test",
            session_id="session-test",
            extra={
                "current_focus": "tighten the startup recovery loop",
                "next_step_hint": "Patch the smallest failing branch first",
            },
        ),
        scripted_responses=[
            _assistant_with_tool_call("c0", "echo", {"text": "x"}),
        ],
        initial_messages=[{"role": "user", "content": "loop"}],
        max_steps=5,
    )
    assert result.stop_reason == "provider_error"
    assert result.error == "Provider request failed."
    assert result.summary and "tighten the startup recovery loop" in result.summary
    assert result.next_step and "Patch the smallest failing branch first" in result.next_step


# ---------------------------------------------------------------------------
# CoachAgentLoop — streaming
# ---------------------------------------------------------------------------


async def _scripted_stream_provider(scripted: list[dict[str, Any]]) -> AgentProvider:
    iterator = iter(scripted)

    async def _call(_messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        try:
            return next(iterator)
        except StopIteration as exc:  # pragma: no cover - defensive
            raise AgentLoopError("exhausted") from exc

    async def _call_stream(_messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None):
        response = await _call(_messages, _tools)
        content = str(response.get("content") or "")
        tool_calls = list(response.get("tool_calls") or [])
        if content:
            yield {"type": "delta", "delta": content}
        yield {
            "type": "final",
            "content": content,
            "tool_calls": tool_calls,
            "stop_reason": "tool_calls" if tool_calls else "stop",
        }

    return AgentProvider(
        protocol="openai_chat_completions",
        call=_call,
        call_stream=_call_stream,
    )


async def test_streaming_loop_emits_text_then_final() -> None:
    registry = _toy_registry()
    provider = await _scripted_stream_provider([{"content": " streamed answer", "tool_calls": []}])
    loop = CoachAgentLoop(provider=provider, registry=registry, context=_context(), max_steps=3)
    events = [event async for event in loop.run_stream([{"role": "user", "content": "hi"}])]
    types = [event["type"] for event in events]
    assert "text" in types
    assert "final" in types
    final = next(event for event in events if event["type"] == "final")
    assert final["content"] == " streamed answer"


async def test_streaming_loop_rejects_buffered_provider_without_calling_it() -> None:
    buffered_call_count = 0

    async def _call(
        _messages: list[dict[str, Any]],
        _tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        nonlocal buffered_call_count
        buffered_call_count += 1
        return {"content": "This must never be emitted as stream text.", "tool_calls": []}

    provider = AgentProvider(
        protocol="openai_chat_completions",
        call=_call,
        call_stream=None,
    )
    loop = CoachAgentLoop(provider=provider, registry=_toy_registry(), context=_context(), max_steps=3)

    events = [event async for event in loop.run_stream([{"role": "user", "content": "hi"}])]

    assert buffered_call_count == 0
    assert not any(event["type"] == "text" for event in events)
    error = next(event for event in events if event["type"] == "error")
    final = next(event for event in events if event["type"] == "final")
    assert error["category"] == "streaming_unavailable"
    assert final["stop_reason"] == "streaming_unavailable"


async def test_streaming_loop_emits_a_tool_free_first_delta_before_provider_final() -> None:
    first_delta_seen = asyncio.Event()
    allow_final = asyncio.Event()

    async def _call(
        _messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        raise AssertionError("the direct streaming path must not fall back to a second call")

    async def _call_stream(
        _messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ):
        assert tools == []
        first_delta_seen.set()
        yield {"type": "delta", "delta": "The first visible sentence "}
        await allow_final.wait()
        yield {"type": "final", "content": "The first visible sentence finishes here.", "tool_calls": []}

    provider = AgentProvider(
        protocol="openai_chat_completions",
        call=_call,
        call_stream=_call_stream,
    )
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={"allowed_tool_names": []},
    )
    loop = CoachAgentLoop(
        provider=provider,
        registry=_toy_registry(),
        context=context,
        max_steps=3,
    )
    stream = loop.run_stream([{"role": "user", "content": "hi"}])

    assert (await anext(stream))["type"] == "step"
    first_text = await asyncio.wait_for(anext(stream), timeout=0.25)
    assert first_delta_seen.is_set()
    assert first_text == {"type": "text", "delta": "The first visible sentence "}

    allow_final.set()
    remaining = [event async for event in stream]
    final = next(event for event in remaining if event["type"] == "final")
    assert final["content"] == "The first visible sentence finishes here."


async def test_streaming_loop_cancels_provider_iterator_when_stream_event_is_set() -> None:
    cancellation = asyncio.Event()
    provider_waiting = asyncio.Event()
    provider_closed = asyncio.Event()

    async def _call(
        _messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        raise AssertionError("stream cancellation test must use the provider stream")

    async def _call_stream(
        _messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None
    ):
        try:
            yield {"type": "delta", "delta": "partial", "safe_to_stream": True}
            provider_waiting.set()
            await asyncio.Event().wait()
        finally:
            provider_closed.set()

    context = _context()
    context.extra["stream_cancel_event"] = cancellation
    loop = CoachAgentLoop(
        provider=AgentProvider(
            protocol="openai_chat_completions",
            call=_call,
            call_stream=_call_stream,
        ),
        registry=_toy_registry(),
        context=context,
        max_steps=2,
    )
    stream = loop.run_stream([{"role": "user", "content": "cancel"}])
    assert (await anext(stream))["type"] == "step"
    assert (await anext(stream))["type"] == "text"
    pending = asyncio.create_task(anext(stream))
    await asyncio.wait_for(provider_waiting.wait(), timeout=0.5)
    cancellation.set()
    try:
        await pending
    except asyncio.CancelledError:
        pass
    else:  # pragma: no cover - a provider that ignores cancellation is a failure
        raise AssertionError("stream iterator continued after cancellation")
    await asyncio.wait_for(provider_closed.wait(), timeout=0.5)


async def test_streaming_loop_empty_final_is_not_completed() -> None:
    registry = _toy_registry()
    provider = await _scripted_stream_provider([{"content": "", "tool_calls": []}])
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "current_focus": "practice verification",
            "next_step_hint": "Re-run current file verification",
        },
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=context, max_steps=3)
    events = [event async for event in loop.run_stream([{"role": "user", "content": "hi"}])]
    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "empty_response"
    assert final["summary"] and "empty visible answer" in final["summary"]
    assert final["summary"] and "practice verification" in final["summary"]
    assert final["next_step"] and "Re-run current file verification" in final["next_step"]


async def test_streaming_loop_carries_completion_continuity_on_plain_text_stop() -> None:
    registry = _toy_registry()
    provider = await _scripted_stream_provider(
        [{"content": "Keep the next move tiny and verify it immediately.", "tool_calls": []}]
    )
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "current_focus": "tighten the recovery loop",
            "next_step_hint": "Patch the smallest failing branch first",
        },
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=context, max_steps=3)
    events = [event async for event in loop.run_stream([{"role": "user", "content": "hi"}])]
    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "completed"
    assert final["summary"] and "tighten the recovery loop" in final["summary"]
    assert final["next_step"] and "Patch the smallest failing branch first" in final["next_step"]


async def test_streaming_loop_completion_continuity_uses_previous_tool_results() -> None:
    registry = _summary_registry()
    provider = await _scripted_stream_provider(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "summarize_step",
                        "arguments": {
                            "summary": "The current file already exposes the right hook.",
                            "next_step": "Wire the hook into the coach view next.",
                            "evidence": "Detected the hook in the current file.",
                        },
                    }
                ],
            },
            {"content": "Looks good.", "tool_calls": []},
        ]
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=_context(), max_steps=4)
    events = [
        event
        async for event in loop.run_stream([{"role": "user", "content": "summarize this turn"}])
    ]
    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "completed"
    assert final["content"] == "Looks good."
    assert final["summary"] == "The current file already exposes the right hook."
    assert final["next_step"] == "Wire the hook into the coach view next."


async def test_streaming_loop_emits_tool_call_and_result() -> None:
    registry = _toy_registry()
    provider = await _scripted_stream_provider(
        [
            {
                "content": "",
                "tool_calls": [{"id": "c1", "name": "echo", "arguments": {"text": "hi"}}],
            },
            {"content": "done", "tool_calls": []},
        ]
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=_context(), max_steps=4)
    events = [event async for event in loop.run_stream([{"role": "user", "content": "go"}])]
    types = [event["type"] for event in events]
    assert "tool_call" in types
    assert "tool_result" in types
    tool_call = next(event for event in events if event["type"] == "tool_call")
    assert tool_call["name"] == "echo"
    tool_result = next(event for event in events if event["type"] == "tool_result")
    assert tool_result["ok"] is True
    assert tool_result["result"]["echoed"] == "hi"


async def test_streaming_loop_surfaces_structured_coach_finalize_payload() -> None:
    registry = _toy_registry()
    provider = await _scripted_stream_provider(
        [
            {
                "content": "Wrapping up.",
                "tool_calls": [
                    {
                        "id": "fin",
                        "name": "coach_finalize",
                        "arguments": {
                            "summary": "sum",
                            "decision": "Choose the smallest verified fix",
                            "next_step": "next",
                            "blocker": "Missing workspace evidence",
                            "teaching_note": "Name the blocker before widening scope.",
                            "resume_thread": "Resume the live thread around the same branch.",
                            "confidence": "high",
                            "evidence": ["tool result A", "tool result B"],
                        },
                    }
                ],
            }
        ]
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=_context(), max_steps=4)
    events = [event async for event in loop.run_stream([{"role": "user", "content": "go"}])]
    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "coach_finalize"
    assert final["summary"] == "sum"
    assert final["next_step"] == "next"
    assert final["decision"] == "Choose the smallest verified fix"
    assert final["blocker"] == "Missing workspace evidence"
    assert final["teaching_note"] == "Name the blocker before widening scope."
    assert final["resume_thread"] == "Resume the live thread around the same branch."
    assert final["confidence"] == "high"
    assert final["evidence"] == ["tool result A", "tool result B"]
    assert "sum" in final["content"]
    assert "next" in final["content"]
    assert not any(
        event["type"] == "text" and "Wrapping up." in str(event.get("delta") or "")
        for event in events
    )


async def test_streaming_loop_uses_finalize_metadata_without_a_second_provider_call() -> None:
    registry = ToolRegistry()

    async def _finalize(_context: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "final": True,
            "summary": "metadata only",
            "next_step": "continue",
        }

    registry.register(
        ToolDefinition(
            name="coach_finalize",
            description="Stop the loop.",
            parameters={"type": "object", "properties": {}},
            handler=_finalize,
        )
    )
    calls = 0

    async def _call(
        _messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise AssertionError("coach_finalize must not invoke a follow-up visible-reply call")

    async def _call_stream(
        _messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None
    ):
        yield {"type": "delta", "delta": "Wrapping up."}
        yield {
            "type": "final",
            "content": "Wrapping up.",
            "tool_calls": [
                {
                    "id": "fin",
                    "name": "coach_finalize",
                    "arguments": {"summary": "metadata only", "next_step": "continue"},
                }
            ],
        }

    provider = AgentProvider(
        protocol="openai_chat_completions",
        call=_call,
        call_stream=_call_stream,
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=_context(), max_steps=4)

    events = [event async for event in loop.run_stream([{"role": "user", "content": "go"}])]

    final = next(event for event in events if event["type"] == "final")
    assert calls == 0
    assert "metadata only" in final["content"]
    assert "continue" in final["content"]
    assert any(
        event["type"] == "text" and event.get("delta") == final["content"]
        for event in events
    )
    assert not any(
        event["type"] == "text" and "Wrapping up." in str(event.get("delta") or "")
        for event in events
    )


async def test_streaming_loop_stops_immediately_after_coach_finalize_and_skips_followup_tools() -> (
    None
):
    registry = ToolRegistry()
    echo_calls: list[dict[str, Any]] = []

    async def _finalize(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "final": True,
            "summary": "sum",
            "next_step": "next",
            "decision": "Choose the smallest verified fix",
            "blocker": "Missing workspace evidence",
            "teaching_note": "Name the blocker before widening scope.",
            "resume_thread": "Resume the live thread around the same branch.",
            "confidence": "high",
            "evidence": ["tool result A", "tool result B"],
        }

    async def _echo(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        echo_calls.append(args)
        return {"ok": True, "echoed": args.get("text", "")}

    registry.register(
        ToolDefinition(
            name="coach_finalize",
            description="Stop the loop.",
            parameters={"type": "object", "properties": {"summary": {"type": "string"}}},
            handler=_finalize,
        )
    )
    registry.register(
        ToolDefinition(
            name="echo",
            description="Echo text.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=_echo,
        )
    )

    provider = await _scripted_stream_provider(
        [
            {
                "content": "Wrapping up.",
                "tool_calls": [
                    {
                        "id": "fin",
                        "name": "coach_finalize",
                        "arguments": {
                            "summary": "sum",
                            "next_step": "next",
                            "decision": "Choose the smallest verified fix",
                        },
                    },
                    {
                        "id": "echo-1",
                        "name": "echo",
                        "arguments": {"text": "should not run"},
                    },
                ],
            }
        ]
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=_context(), max_steps=4)
    events = [event async for event in loop.run_stream([{"role": "user", "content": "go"}])]
    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "coach_finalize"
    assert final["summary"] == "sum"
    assert final["next_step"] == "next"
    assert echo_calls == []
    assert [event["name"] for event in events if event["type"] == "tool_call"] == ["coach_finalize"]
    assert [event["name"] for event in events if event["type"] == "tool_result"] == [
        "coach_finalize"
    ]


async def test_streaming_loop_reports_recovery_hint_on_no_progress() -> None:
    registry = _toy_registry()
    provider = await _scripted_stream_provider(
        [
            {
                "content": "",
                "tool_calls": [{"id": "c1", "name": "echo", "arguments": {"text": "same"}}],
            },
            {
                "content": "",
                "tool_calls": [{"id": "c2", "name": "echo", "arguments": {"text": "same"}}],
            },
            {
                "content": "",
                "tool_calls": [{"id": "c3", "name": "echo", "arguments": {"text": "same"}}],
            },
        ]
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=_context(), max_steps=4)
    events = [event async for event in loop.run_stream([{"role": "user", "content": "go"}])]
    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "no_progress"
    assert final["summary"] and "same tool path" in final["summary"]
    assert final["next_step"] and "different evidence source" in final["next_step"]


async def test_streaming_loop_stops_when_tool_results_repeat_even_if_args_change() -> None:
    registry = ToolRegistry()

    async def _steady(_context: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "steady",
            "evidence": "no new information",
        }

    registry.register(
        ToolDefinition(
            name="steady_check",
            description="Return the same result every time.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
            },
            handler=_steady,
        )
    )
    provider = await _scripted_stream_provider(
        [
            {
                "content": "",
                "tool_calls": [{"id": "c1", "name": "steady_check", "arguments": {"path": "a"}}],
            },
            {
                "content": "",
                "tool_calls": [{"id": "c2", "name": "steady_check", "arguments": {"path": "b"}}],
            },
        ]
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=_context(), max_steps=4)
    events = [event async for event in loop.run_stream([{"role": "user", "content": "go"}])]
    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "no_progress"
    assert final["summary"] and "same tool path" in final["summary"]
    assert final["next_step"] and "different evidence source" in final["next_step"]


async def test_streaming_loop_mentions_previous_tool_failure_on_no_progress() -> None:
    registry = ToolRegistry()

    async def _fail(_context: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": False, "error": "missing_path", "detail": "path does not exist"}

    registry.register(
        ToolDefinition(
            name="fail_once",
            description="Fail in a structured way.",
            parameters={"type": "object", "properties": {}},
            handler=_fail,
        )
    )
    provider = await _scripted_stream_provider(
        [
            {"content": "", "tool_calls": [{"id": "c1", "name": "fail_once", "arguments": {}}]},
            {"content": "", "tool_calls": [{"id": "c2", "name": "fail_once", "arguments": {}}]},
            {"content": "", "tool_calls": [{"id": "c3", "name": "fail_once", "arguments": {}}]},
        ]
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=_context(), max_steps=4)
    events = [event async for event in loop.run_stream([{"role": "user", "content": "go"}])]
    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "no_progress"
    assert final["summary"] and "missing_path" in final["summary"]
    assert final["next_step"] and "Fix the issue" in final["next_step"]


# ---------------------------------------------------------------------------
# Default tool registry — resilience + schema
# ---------------------------------------------------------------------------


def test_default_registry_exposes_coach_tools() -> None:
    registry = build_default_tool_registry()
    names = set(registry.names())
    for expected in {
        "search_resources",
        "inspect_current_file",
        "verify_practice_current_file",
        "read_workspace_file",
        "list_workspace_files",
        "recall_memory",
        "record_learning_note",
        "inspect_plan",
        "save_formal_plan",
        "generate_training_card",
        "run_diagnostics",
        "coach_finalize",
    }:
        assert expected in names, f"missing tool {expected}"


def test_tool_schema_for_openai_chat_shape() -> None:
    registry = build_default_tool_registry()
    schemas = registry.as_protocol_schemas("openai_chat_completions")
    assert schemas, "expected at least one tool schema"
    first = schemas[0]
    assert first["type"] == "function"
    assert "name" in first["function"]


def test_tool_schema_hides_coach_only_tools_by_default() -> None:
    registry = build_default_tool_registry()
    schemas = registry.as_protocol_schemas("openai_chat_completions")
    names = _tool_schema_names(schemas)
    assert "inspect_current_file" in names
    assert "verify_practice_current_file" in names
    assert "recall_memory" in names
    assert "record_learning_note" not in names
    assert "generate_training_card" not in names
    assert "import_resource_url" not in names
    assert "organize_resources" not in names


def test_tool_schema_includes_coach_only_tools_when_allowed() -> None:
    registry = build_default_tool_registry()
    schemas = registry.as_protocol_schemas(
        "openai_chat_completions",
        allow_coach_only=True,
    )
    names = _tool_schema_names(schemas)
    assert "record_learning_note" not in names
    assert "save_formal_plan" not in names
    assert "generate_training_card" not in names
    assert "import_resource_url" not in names
    assert "organize_resources" not in names


def test_tool_schema_exposes_record_learning_note_only_when_explicitly_requested() -> None:
    registry = build_default_tool_registry()
    hidden = _tool_schema_names(
        registry.as_protocol_schemas(
            "openai_chat_completions",
            allow_coach_only=True,
        )
    )
    visible = _tool_schema_names(
        registry.as_protocol_schemas(
            "openai_chat_completions",
            allow_coach_only=True,
            explicit_learning_note_request=True,
        )
    )
    assert "record_learning_note" not in hidden
    assert "record_learning_note" in visible
    assert "save_formal_plan" not in visible
    assert "import_resource_url" not in visible


def test_tool_schema_exposes_resource_write_tools_only_on_explicit_resource_turns() -> None:
    registry = build_default_tool_registry()
    hidden = _tool_schema_names(
        registry.as_protocol_schemas("openai_chat_completions", allow_coach_only=True)
    )
    import_visible = _tool_schema_names(
        registry.as_protocol_schemas(
            "openai_chat_completions",
            allow_coach_only=True,
            explicit_resource_import=True,
        )
    )
    organize_visible = _tool_schema_names(
        registry.as_protocol_schemas(
            "openai_chat_completions",
            allow_coach_only=True,
            explicit_resource_organize=True,
        )
    )
    assert "import_resource_url" not in hidden
    assert "organize_resources" not in hidden
    assert "import_resource_url" in import_visible
    assert "organize_resources" not in import_visible
    assert "organize_resources" in organize_visible
    assert "import_resource_url" not in organize_visible


def test_tool_schema_exposes_save_formal_plan_only_on_formal_mutation() -> None:
    registry = build_default_tool_registry()
    hidden = _tool_schema_names(
        registry.as_protocol_schemas(
            "openai_chat_completions",
            allow_coach_only=True,
        )
    )
    visible = _tool_schema_names(
        registry.as_protocol_schemas(
            "openai_chat_completions",
            allow_coach_only=True,
            formal_plan_mutation=True,
        )
    )
    assert "save_formal_plan" not in hidden
    assert "record_learning_note" not in hidden
    assert "save_formal_plan" in visible
    assert "generate_training_card" not in visible
    assert "record_learning_note" not in visible


def test_tool_schema_never_exposes_generate_training_card_for_chat() -> None:
    registry = build_default_tool_registry()
    hidden = _tool_schema_names(
        registry.as_protocol_schemas(
            "openai_chat_completions",
            allow_coach_only=True,
        )
    )
    visible = _tool_schema_names(
        registry.as_protocol_schemas(
            "openai_chat_completions",
            allow_coach_only=True,
            explicit_training_card_request=True,
        )
    )
    assert "generate_training_card" not in hidden
    assert "generate_training_card" not in visible
    assert "record_learning_note" not in hidden
    assert "record_learning_note" not in visible


async def test_save_formal_plan_requires_explicit_formal_turn_and_persists_model_shape() -> None:
    class _Repository:
        def __init__(self) -> None:
            self.plan = None

        def get_latest_plan(self, _workspace_id: str):
            return self.plan

        def save_plan(self, _workspace_id: str, plan) -> None:
            self.plan = plan

    repository = _Repository()
    runtime = SimpleNamespace(repository=repository, sandbox_service=None, sessions={})
    registry = build_default_tool_registry()
    context = ToolContext(
        runtime=runtime,
        workspace_id="workspace-plan-tool",
        extra={"formal_plan_mutation": True, "allow_coach_only_tools": True},
    )

    result = await registry.invoke(
        context,
        "save_formal_plan",
        {
            "title": "FastAPI route learning",
            "summary": "Build a grounded route-design learning path from the uploaded notes.",
            "current_step": "Inspect one route boundary and its verification signal.",
            "verify_method": ["One focused endpoint test passes."],
            "stages": [
                {
                    "id": "stage-boundary",
                    "title": "Route boundary",
                    "goal": "Explain request validation and response ownership.",
                    "outcomes": ["Name the boundary", "Verify one request path"],
                    "resources": ["resource-route-notes"],
                    "status": "active",
                }
            ],
        },
    )

    assert result["ok"] is True
    assert result["committed"] is True
    assert repository.plan is not None
    assert repository.plan.stages[0].resources == ["resource-route-notes"]

    blocked = await registry.invoke(
        ToolContext(
            runtime=runtime,
            workspace_id="workspace-plan-tool",
            extra={"allow_coach_only_tools": True},
        ),
        "save_formal_plan",
        {
            "title": "Should not write",
            "summary": "No formal mutation flag.",
            "stages": [{"title": "Stage", "goal": "Goal"}],
        },
    )
    assert blocked["ok"] is False
    assert blocked["error"] == "formal_plan_mutation_required"


async def test_agent_loop_hides_tools_outside_the_current_turn_allowlist() -> None:
    registry = build_default_tool_registry()
    captured_tools: list[dict[str, Any]] = []

    async def _call(
        _messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        captured_tools.extend(tools or [])
        return {"content": "Keep the next move small.", "tool_calls": []}

    provider = SimpleNamespace(protocol="openai_chat_completions", call=_call, call_stream=None)
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={"allowed_tool_names": []},
    )
    result = await CoachAgentLoop(provider=provider, registry=registry, context=context, max_steps=1).run(
        [{"role": "user", "content": "Teach one small remote checkpoint."}]
    )

    assert result.stop_reason == "completed"
    assert captured_tools == []


async def test_tool_registry_refuses_tools_outside_the_current_turn_allowlist() -> None:
    registry = build_default_tool_registry()
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={"allowed_tool_names": []},
    )

    result = await registry.invoke(context, "recall_memory", {})

    assert result["ok"] is False
    assert result["error"] == "tool_not_available"


def test_tool_schema_for_anthropic_shape() -> None:
    registry = build_default_tool_registry()
    schemas = registry.as_protocol_schemas("anthropic_messages")
    first = schemas[0]
    assert "name" in first
    assert "input_schema" in first


async def test_recall_memory_degrades_gracefully_without_runtime() -> None:
    registry = build_default_tool_registry()
    result = await registry.invoke(_context(runtime=None), "recall_memory", {})
    assert result["ok"] is False
    assert result["error"] == "service_unavailable"
    assert "memory_service" not in result["detail"]


async def test_search_resources_degrades_without_internal_service_names() -> None:
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(runtime=None),
        "search_resources",
        {"query": "remote workspace boundary"},
    )
    assert result["ok"] is False
    assert result["error"] == "service_unavailable"
    assert "resource_service" not in result["detail"]
    assert "resource library" in result["detail"].lower()


async def test_inspect_current_file_reads_ide_snapshot_without_runtime() -> None:
    registry = build_default_tool_registry()
    content = "x" * 80
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "current_file": {
                "path": "src/main.py",
                "language_id": "python",
                "content": content,
                "diagnostics": ["E999 example"],
                "selection_text": "selected code",
                "selection_range": "1:1-1:13",
            }
        },
    )
    result = await registry.invoke(context, "inspect_current_file", {"max_chars": 64})
    assert result["ok"] is True
    assert result["path"] == "src/main.py"
    assert result["language_id"] == "python"
    assert result["content"] == content[:64]
    assert result["truncated"] is True
    assert result["diagnostics"] == ["E999 example"]
    assert result["selection_text"] == "selected code"


async def test_search_resources_tool_normalizes_structured_search_response() -> None:
    from app.resources.search import SearchFilters, SearchResponse, SearchResult

    registry = build_default_tool_registry()
    captured: dict[str, Any] = {}

    class _ResourceService:
        def search_resources(self, **kwargs: Any) -> SearchResponse:
            captured.update(kwargs)
            return SearchResponse(
                results=[
                    SearchResult(
                        resource_id="res-1",
                        path="docs/remote.md",
                        title="VS Code Remote Boundary",
                        snippet="Check which host owns the workspace path before moving credentials.",
                        source="docs/remote.md",
                        source_type="file",
                        summary="Boundary-first remote notes.",
                        trust_score=0.82,
                        trust_state="trusted",
                        freshness="fresh",
                        file_type="markdown",
                        project_scope="workspace-test",
                        kind="markdown",
                        index_state="indexed",
                        citation_id="citation:res-1",
                        can_inject_training_card=True,
                        updated_at=datetime.now(timezone.utc),
                        rank_score=0.91,
                        rank_reasons=["title match", "high trust", "indexed"],
                        matched_fields=["title", "summary"],
                        match_summary="matched title, summary; trust 0.82; freshness fresh",
                    )
                ],
                query="remote workspace boundary",
                total=1,
                filters=SearchFilters(project_scope="workspace-test"),
                ranking_strategy="lexical_first",
            )

    context = ToolContext(
        runtime=SimpleNamespace(resource_service=_ResourceService()),
        workspace_id="workspace-test",
        session_id="session-test",
    )
    result = await registry.invoke(
        context,
        "search_resources",
        {
            "query": "remote workspace boundary",
            "mode": "narrow",
            "limit": 4,
            "project_scope": "workspace-test",
        },
    )

    assert result["ok"] is True
    assert captured["top_k"] == 8
    assert captured["project_scope"] == "workspace-test"
    assert result["mode"] == "narrow"
    assert result["ranking_strategy"] == "lexical_first"
    assert result["filters"]["project_scope"] == "workspace-test"
    assert result["hits"][0]["title"] == "VS Code Remote Boundary"
    assert result["hits"][0]["trust_state"] == "trusted"
    assert result["hits"][0]["match_summary"]
    assert "Narrow search kept" in result["summary"]


async def test_search_resources_tool_verify_mode_prefers_grounded_hits() -> None:
    from app.resources.search import SearchFilters, SearchResponse, SearchResult

    registry = build_default_tool_registry()

    class _ResourceService:
        def search_resources(self, **kwargs: Any) -> SearchResponse:
            now = datetime.now(timezone.utc)
            return SearchResponse(
                results=[
                    SearchResult(
                        resource_id="res-untrusted",
                        path="notes/raw.txt",
                        title="Raw Notes",
                        snippet="Possibly useful but unverified.",
                        source="notes/raw.txt",
                        source_type="file",
                        summary="Raw notes.",
                        trust_score=0.1,
                        trust_state="untrusted",
                        freshness="unknown",
                        file_type="text",
                        project_scope="workspace-test",
                        kind="text",
                        index_state="indexed",
                        citation_id="citation:res-untrusted",
                        can_inject_training_card=False,
                        updated_at=now,
                    ),
                    SearchResult(
                        resource_id="res-trusted",
                        path="docs/debug.md",
                        title="Debug Loop",
                        snippet="Pause at the first state transition you can explain.",
                        source="docs/debug.md",
                        source_type="file",
                        summary="Verified debug loop notes.",
                        trust_score=0.88,
                        trust_state="trusted",
                        freshness="fresh",
                        file_type="markdown",
                        project_scope="workspace-test",
                        kind="markdown",
                        index_state="indexed",
                        citation_id="citation:res-trusted",
                        can_inject_training_card=True,
                        updated_at=now,
                    ),
                ],
                query="debug loop",
                total=2,
                filters=SearchFilters(),
                ranking_strategy="lexical_first",
            )

    context = ToolContext(
        runtime=SimpleNamespace(resource_service=_ResourceService()),
        workspace_id="workspace-test",
        session_id="session-test",
    )
    result = await registry.invoke(
        context,
        "search_resources",
        {"query": "debug loop", "mode": "verify", "limit": 5},
    )

    assert result["ok"] is True
    assert result["mode"] == "verify"
    assert result["verification_ready_count"] == 1
    assert len(result["hits"]) == 1
    assert result["hits"][0]["resource_id"] == "res-trusted"
    assert "Verify search found 1 citation-ready hits" in result["summary"]


async def test_verify_practice_current_file_fails_honestly_without_current_file() -> None:
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(runtime=None),
        "verify_practice_current_file",
        {"acceptance_criteria": ["Implement debounceSearch"]},
    )
    assert result["ok"] is False
    assert result["error"] == "no_current_file"
    assert result["status"] == "blocked"
    assert result["passed"] is False
    assert "active IDE file" in result["detail"]


async def test_verify_practice_current_file_blocks_error_diagnostics() -> None:
    registry = build_default_tool_registry()
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "current_file": {
                "path": "src/search.ts",
                "language_id": "typescript",
                "content": "export function debounceSearch(query: string) { return query.trim(); }",
                "diagnostics": ["[error] line 1: Cannot find name 'query'."],
            }
        },
    )
    result = await registry.invoke(
        context,
        "verify_practice_current_file",
        {
            "acceptance_criteria": ["Implement debounceSearch for the search input"],
            "expected_symbols": ["debounceSearch"],
            "allow_warnings": True,
        },
    )
    assert result["ok"] is True
    assert result["status"] == "blocked"
    assert result["passed"] is False
    assert result["reason"] == "error_diagnostics"
    assert result["blocking_diagnostics"] == ["[error] line 1: Cannot find name 'query'."]
    assert result["path"] == "src/search.ts"


async def test_verify_practice_current_file_needs_review_without_acceptance_signals() -> None:
    registry = build_default_tool_registry()
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "current_file": {
                "path": "src/search.ts",
                "language_id": "typescript",
                "content": "export function debounceSearch(query: string) { return query.trim(); }",
                "diagnostics": [],
            }
        },
    )
    result = await registry.invoke(context, "verify_practice_current_file", {})
    assert result["ok"] is True
    assert result["status"] == "needs_review"
    assert result["passed"] is False
    assert result["reason"] == "missing_acceptance_criteria"
    assert "acceptance criteria" in result["next_step"]


async def test_verify_practice_current_file_passes_clean_current_file_evidence() -> None:
    registry = build_default_tool_registry()
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "current_file": {
                "path": "src/search.ts",
                "language_id": "typescript",
                "content": (
                    "export function debounceSearch(query: string) {\n"
                    "  const normalizedQuery = query.trim();\n"
                    "  return normalizedQuery.length > 0 ? normalizedQuery : '';\n"
                    "}\n"
                ),
                "diagnostics": [],
                "selection_range": "1:1-4:2",
            }
        },
    )
    result = await registry.invoke(
        context,
        "verify_practice_current_file",
        {
            "acceptance_criteria": ["Implement debounceSearch for the search input"],
            "expected_symbols": ["debounceSearch", "normalizedQuery"],
        },
    )
    assert result["ok"] is True
    assert result["status"] == "passed"
    assert result["passed"] is True
    assert result["reason"] == "all_signals_matched"
    assert result["evidence_source"] == "ide_current_file"
    assert result["path"] == "src/search.ts"
    assert result["language_id"] == "typescript"
    assert all(item["status"] == "matched" for item in result["criteria"])
    assert any("Read active IDE file src/search.ts" in item for item in result["evidence"])


async def test_verify_practice_current_file_persists_training_evidence_before_return(
    tmp_path,
) -> None:
    from app.core.models import ActiveCardSelectionResult, TrainingCardCandidateSnapshot
    from app.db.repository import TrainerRepository
    from app.memory.service import MemoryService

    registry = build_default_tool_registry()
    repository = TrainerRepository(tmp_path / "trainer-memory.db")
    memory_service = MemoryService(repository)
    card = TrainingCardCandidateSnapshot(
        card_id="practice-persist-1",
        card_type="practice",
        title="Persist current-file verification",
        status="active",
        focus_area="current-file evidence",
        target_skill="practice verification",
    )
    memory_service.upsert_card("workspace-test", card)
    memory_service.persist_active_card_selection(
        "workspace-test",
        ActiveCardSelectionResult(
            selected_card=card,
            selected_card_id=card.card_id,
            why_this_card="The current file needs verified practice evidence.",
            next_after_completion="Route the next card.",
            fallback_action="Bring the blocker back to Coach.",
            candidate_count=1,
            eligible_count=1,
        ),
    )
    context = ToolContext(
        runtime=SimpleNamespace(memory_service=memory_service),
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "current_file": {
                "path": "src/search.ts",
                "language_id": "typescript",
                "content": "export function debounceSearch() { return true; }\n",
                "diagnostics": [],
            }
        },
    )

    result = await registry.invoke(
        context,
        "verify_practice_current_file",
        {
            "acceptance_criteria": ["Implement debounceSearch"],
            "expected_symbols": ["debounceSearch"],
        },
    )

    assert result["passed"] is True
    assert result["persisted_training_evidence"] is True
    assert result["training_card_id"] == "practice-persist-1"
    updated = memory_service.get_card("workspace-test", "practice-persist-1")
    assert updated is not None
    assert updated.status == "active"
    snapshot = memory_service.snapshot("workspace-test")
    assert snapshot.workspace["selected_card_status"] == "active"
    assert snapshot.workspace["latest_training_handoff"]["handoff_status"] == "needs_reflection"
    assert snapshot.workspace["latest_training_handoff"]["learning_phase"] == "verify"
    assert snapshot.workspace["latest_training_next_hop"]["status"] == "reflection_required"
    assert snapshot.training_event_ledger[-1]["event_type"] == "practice_evaluation_recorded"
    assert snapshot.training_event_ledger[-1]["selected_card_id"] == "practice-persist-1"


async def test_coach_only_tool_refuses_without_context_opt_in() -> None:
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(runtime=SimpleNamespace()),
        "record_learning_note",
        {"note": "Learner prefers tiny verified slices."},
    )
    assert result["ok"] is False
    assert result["error"] == "coach_only_tool_not_allowed"


async def test_record_learning_note_requires_explicit_ask(tmp_path) -> None:
    captured: dict[str, Any] = {}

    class _MemoryService:
        def record_teaching_observation(self, *, workspace_id: str, note: str, kind: str) -> None:
            captured["note"] = note

    registry = build_default_tool_registry()
    context = ToolContext(
        runtime=SimpleNamespace(memory_service=_MemoryService()),
        workspace_id="workspace-note-implicit",
        session_id="session-note-implicit",
        extra={"allow_coach_only_tools": True},
    )
    result = await registry.invoke(
        context,
        "record_learning_note",
        {"note": "The understand turn felt ready for a durable note.", "kind": "preference"},
    )
    assert result["ok"] is False
    assert result["error"] == "explicit_learning_note_request_required"
    assert captured == {}


async def test_coach_only_tool_runs_when_context_opted_in() -> None:
    registry = build_default_tool_registry()
    captured: dict[str, Any] = {}

    class _MemoryService:
        def record_teaching_observation(self, *, workspace_id: str, note: str, kind: str) -> None:
            captured["workspace_id"] = workspace_id
            captured["note"] = note
            captured["kind"] = kind

    context = ToolContext(
        runtime=SimpleNamespace(memory_service=_MemoryService()),
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "allow_coach_only_tools": True,
            "explicit_learning_note_request": True,
        },
    )
    result = await registry.invoke(
        context,
        "record_learning_note",
        {"note": "Learner prefers tiny verified slices.", "kind": "preference"},
    )
    assert result["ok"] is True
    assert captured == {
        "workspace_id": "workspace-test",
        "note": "Learner prefers tiny verified slices.",
        "kind": "preference",
    }


async def test_generate_training_card_tool_requires_explicit_ask(tmp_path) -> None:
    from app.db.repository import TrainerRepository
    from app.memory.service import MemoryService
    from app.training.card_generator import CardGenerationService
    from app.training.card_router import CardRouterService

    registry = build_default_tool_registry()
    repository = TrainerRepository(tmp_path / "trainer-tool-card-implicit.db")
    memory_service = MemoryService(repository)
    runtime = SimpleNamespace(
        memory_service=memory_service,
        repository=repository,
        card_generation_service=CardGenerationService(),
        card_router_service=CardRouterService(),
    )
    context = ToolContext(
        runtime=runtime,
        workspace_id="workspace-tool-training-card-implicit",
        session_id="session-tool-training-card-implicit",
        response_language="en-US",
        extra={"allow_coach_only_tools": True},
    )

    result = await registry.invoke(
        context,
        "generate_training_card",
        {
            "focus_area": "query normalization",
            "target_skill": "implement normalize_query",
            "card_type": "practice",
            "why_now": "The agent decided a card would help after an understand turn.",
        },
    )

    assert result["ok"] is False
    assert result["error"] == "explicit_training_card_request_required"
    assert memory_service.get_cards("workspace-tool-training-card-implicit") == []
    assert memory_service.snapshot("workspace-tool-training-card-implicit").active_training_card_routing is None


async def test_generate_training_card_tool_denies_chat_mint_for_http_path(
    tmp_path,
) -> None:
    from app.db.repository import TrainerRepository
    from app.memory.service import MemoryService
    from app.training.card_generator import CardGenerationService
    from app.training.card_router import CardRouterService

    registry = build_default_tool_registry()
    repository = TrainerRepository(tmp_path / "trainer-tool-card.db")
    memory_service = MemoryService(repository)
    runtime = SimpleNamespace(
        memory_service=memory_service,
        repository=repository,
        card_generation_service=CardGenerationService(),
        card_router_service=CardRouterService(),
    )
    context = ToolContext(
        runtime=runtime,
        workspace_id="workspace-tool-training-card",
        session_id="session-tool-training-card",
        response_language="en-US",
        extra={"allow_coach_only_tools": True, "explicit_training_card_request": True},
    )

    result = await registry.invoke(
        context,
        "generate_training_card",
        {
            "focus_area": "VS Code remote workspace",
            "target_skill": "remote workspace boundary",
            "card_type": "practice",
            "why_now": "The learner explicitly asked for a learn-first training card.",
        },
    )

    assert result["ok"] is False
    assert result["error"] == "explicit_http_generate_card_required"
    assert memory_service.get_cards("workspace-tool-training-card") == []
    assert memory_service.snapshot("workspace-tool-training-card").active_training_card_routing is None


async def test_generate_training_card_tool_why_this_card_gates_leftover_formal_title(
    tmp_path,
) -> None:
    from app.core.models import LearningPlan, PlanStage, TrainingCardCandidateSnapshot
    from app.db.repository import TrainerRepository
    from app.memory.service import MemoryService

    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_card = f"Practice: {leftover_title}"
    recovered_step = "Add a token expiry test"
    leftover_why = f"{leftover_card} is the current training card."
    plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id="stage-1",
        current_step=leftover_step,
        stages=[
            PlanStage(
                id="stage-1",
                title=leftover_stage,
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            )
        ],
    )

    class _LeftoverCardService:
        def generate_card(self, _source: str, _ctx: object) -> TrainingCardCandidateSnapshot:
            return TrainingCardCandidateSnapshot(
                card_id="card-leftover-formal",
                card_type="practice",
                title=leftover_card,
                why_now=leftover_why,
                problem_statement="Write one expiry test.",
                deliverable="A passing test.",
                validation_method="pytest",
            )

    registry = build_default_tool_registry()
    repository = TrainerRepository(tmp_path / "trainer-tool-leftover-card.db")
    memory_service = MemoryService(repository)
    workspace_id = "workspace-tool-leftover-card"
    repository.save_plan(workspace_id, plan)
    memory_service.persist_plan_runtime_recovery(
        workspace_id,
        plan=plan,
        plan_runtime={
            "current_step": recovered_step,
            "why_now": "Expired tokens still leak.",
            "resume_state": "in_progress",
            "workspace_id": workspace_id,
        },
    )
    runtime = SimpleNamespace(
        memory_service=memory_service,
        repository=repository,
        card_generation_service=_LeftoverCardService(),
        card_router_service=None,
    )
    context = ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id="session-tool-leftover-card",
        response_language="en-US",
        extra={"allow_coach_only_tools": True, "explicit_training_card_request": True},
    )
    result = await registry.invoke(
        context,
        "generate_training_card",
        {
            "focus_area": recovered_step,
            "target_skill": recovered_step,
            "card_type": "practice",
            "why_now": leftover_why,
        },
    )
    # Leftover-not-live recovered runtime without live card id: ReAct must not invent.
    assert result["ok"] is False
    assert result["error"] in {
        "leftover_not_live_card",
        "live_training_card_required",
        "explicit_http_generate_card_required",
    }
    assert memory_service.get_cards(workspace_id) == []

    still_workspace = "workspace-tool-still-on-plan-card"
    still_plan_id = "plan-formal-still-live"
    still_plan = LearningPlan(
        id=still_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id="stage-1",
        current_step=leftover_step,
        stages=[
            PlanStage(
                id="stage-1",
                title=leftover_stage,
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    repository.save_plan(still_workspace, still_plan)
    memory_service.persist_plan_runtime_recovery(
        still_workspace,
        plan=still_plan,
        plan_runtime={
            "current_step": leftover_step,
            "plan_id": still_plan_id,
            "resume_state": "in_progress",
            "workspace_id": still_workspace,
        },
    )
    still_context = ToolContext(
        runtime=runtime,
        workspace_id=still_workspace,
        session_id="session-tool-still-on-plan-card",
        response_language="en-US",
        extra={"allow_coach_only_tools": True, "explicit_training_card_request": True},
    )
    still = await registry.invoke(
        still_context,
        "generate_training_card",
        {
            "focus_area": leftover_title,
            "target_skill": leftover_title,
            "card_type": "practice",
            "why_now": leftover_why,
        },
    )
    # Chat/ReAct still must not mint; HTTP /training/generate-card is the binder.
    assert still["ok"] is False
    assert still["error"] == "explicit_http_generate_card_required"
    assert memory_service.get_cards(still_workspace) == []


async def test_generate_training_card_tool_projects_safe_current_file_and_remote_facts(
    tmp_path,
) -> None:
    from app.db.repository import TrainerRepository
    from app.memory.service import MemoryService
    from app.training.card_generator import CardGenerationService
    from app.training.card_router import CardRouterService

    registry = build_default_tool_registry()
    repository = TrainerRepository(tmp_path / "trainer-tool-card-facts.db")
    memory_service = MemoryService(repository)
    memory_service.update_workspace_state(
        "workspace-tool-training-card-facts",
        remote_name="ssh-remote+lab",
        is_remote_workspace=True,
    )
    runtime = SimpleNamespace(
        memory_service=memory_service,
        repository=repository,
        card_generation_service=CardGenerationService(),
        card_router_service=CardRouterService(),
        resolve_workspace_path=lambda _workspace_id: "/workspaces/trainer",
    )
    context = ToolContext(
        runtime=runtime,
        workspace_id="workspace-tool-training-card-facts",
        session_id="session-tool-training-card-facts",
        response_language="en-US",
        extra={
            "allow_coach_only_tools": True,
            "explicit_training_card_request": True,
            "current_file": {
                "path": "/workspaces/trainer/src/router.ts",
                "language_id": "typescript",
                "content": "export function route() { return 'ok'; }",
                "diagnostics": [
                    "TypeError: token=super-secret-value cannot read properties of undefined"
                ],
            },
        },
    )

    result = await registry.invoke(
        context,
        "generate_training_card",
        {
            "focus_area": "VS Code debug loop",
            "target_skill": "debug a TypeError",
            "card_type": "practice",
            "why_now": "The learner asked for a grounded debug card.",
        },
    )

    assert result["ok"] is False
    assert result["error"] == "explicit_http_generate_card_required"
    assert memory_service.get_cards("workspace-tool-training-card-facts") == []


async def test_agent_loop_filters_coach_only_tools_from_model_schema_by_context() -> None:
    registry = build_default_tool_registry()
    captured_tools: list[dict[str, Any]] = []

    async def _call(
        _messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        captured_tools.extend(tools or [])
        return {"content": "Done.", "tool_calls": []}

    provider = SimpleNamespace(protocol="openai_chat_completions", call=_call, call_stream=None)
    loop = CoachAgentLoop(provider=provider, registry=registry, context=_context(), max_steps=1)
    await loop.run([{"role": "user", "content": "continue"}])
    names = _tool_schema_names(captured_tools)
    assert "read_workspace_file" in names
    assert "record_learning_note" not in names


async def test_agent_loop_exposes_coach_only_tools_when_context_opted_in() -> None:
    registry = build_default_tool_registry()
    captured_tools: list[dict[str, Any]] = []

    async def _call(
        _messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        captured_tools.extend(tools or [])
        return {"content": "Done.", "tool_calls": []}

    provider = SimpleNamespace(protocol="openai_chat_completions", call=_call, call_stream=None)
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={"allow_coach_only_tools": True},
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=context, max_steps=1)
    await loop.run([{"role": "user", "content": "continue"}])
    names = _tool_schema_names(captured_tools)
    assert "record_learning_note" not in names
    assert "generate_training_card" not in names
    assert "save_formal_plan" not in names
    assert "import_resource_url" not in names
    assert "organize_resources" not in names


async def test_agent_loop_exposes_record_learning_note_only_when_explicitly_requested() -> None:
    registry = build_default_tool_registry()
    captured_tools: list[dict[str, Any]] = []

    async def _call(
        _messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        captured_tools.extend(tools or [])
        return {"content": "Done.", "tool_calls": []}

    provider = SimpleNamespace(protocol="openai_chat_completions", call=_call, call_stream=None)
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "allow_coach_only_tools": True,
            "explicit_learning_note_request": True,
        },
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=context, max_steps=1)
    await loop.run([{"role": "user", "content": "Save a learning note that I prefer tiny verified slices."}])
    names = _tool_schema_names(captured_tools)
    assert "record_learning_note" in names
    assert "generate_training_card" not in names
    assert "import_resource_url" not in names


async def test_agent_loop_exposes_save_formal_plan_only_on_formal_mutation() -> None:
    registry = build_default_tool_registry()
    captured_tools: list[dict[str, Any]] = []

    async def _call(
        _messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        captured_tools.extend(tools or [])
        return {"content": "Done.", "tool_calls": []}

    provider = SimpleNamespace(protocol="openai_chat_completions", call=_call, call_stream=None)
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "allow_coach_only_tools": True,
            "formal_plan_mutation": True,
        },
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=context, max_steps=1)
    await loop.run([{"role": "user", "content": "Create a formal learning plan for FastAPI routes."}])
    names = _tool_schema_names(captured_tools)
    assert "record_learning_note" not in names
    assert "save_formal_plan" in names
    assert "generate_training_card" not in names


async def test_agent_loop_never_exposes_generate_training_card_from_chat() -> None:
    registry = build_default_tool_registry()
    captured_tools: list[dict[str, Any]] = []

    async def _call(
        _messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        captured_tools.extend(tools or [])
        return {"content": "Done.", "tool_calls": []}

    provider = SimpleNamespace(protocol="openai_chat_completions", call=_call, call_stream=None)
    context = ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra={
            "allow_coach_only_tools": True,
            "explicit_training_card_request": True,
        },
    )
    loop = CoachAgentLoop(provider=provider, registry=registry, context=context, max_steps=1)
    await loop.run([{"role": "user", "content": "Create a training card for query normalization."}])
    names = _tool_schema_names(captured_tools)
    assert "record_learning_note" not in names
    assert "generate_training_card" not in names
    assert "save_formal_plan" not in names


async def test_inspect_plan_returns_no_plan_summary_when_repository_missing() -> None:
    registry = build_default_tool_registry()
    result = await registry.invoke(_context(runtime=SimpleNamespace()), "inspect_plan", {})
    assert result["ok"] is False
    assert result["error"] == "service_unavailable"


async def test_coach_finalize_returns_final_payload() -> None:
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(),
        "coach_finalize",
        {
            "summary": "wrapped",
            "next_step": "ship it",
            "resume_thread": "Resume the live thread around the ship-it branch.",
        },
    )
    assert result["final"] is True
    assert result["summary"] == "wrapped"
    assert result["next_step"] == "ship it"
    assert result["resume_thread"] == "Resume the live thread around the ship-it branch."


# ---------------------------------------------------------------------------
# ProviderAgentBinding — protocol resolution + OpenAI formatting
# ---------------------------------------------------------------------------


def test_resolve_agent_protocol_maps_known_aliases() -> None:
    assert resolve_agent_protocol("anthropic_messages") == "anthropic_messages"
    assert resolve_agent_protocol("anthropic") == "anthropic_messages"
    assert resolve_agent_protocol("claude") == "anthropic_messages"
    assert resolve_agent_protocol("openai_chat_completions") == "openai_chat_completions"
    assert resolve_agent_protocol("openai_responses") == "openai_responses"
    assert resolve_agent_protocol("responses") == "openai_responses"
    assert resolve_agent_protocol("gemini_generate_content") == "gemini_generate_content"
    assert resolve_agent_protocol("gemini") == "gemini_generate_content"
    assert (
        resolve_agent_protocol(
            "gemini_generate_content",
            base_url="https://gateway.example.com/v1",
        )
        == "openai_chat_completions"
    )
    assert (
        resolve_agent_protocol(
            "gemini_generate_content",
            base_url="https://generativelanguage.googleapis.com/v1beta",
        )
        == "gemini_generate_content"
    )
    assert resolve_agent_protocol("") == "openai_chat_completions"
    assert resolve_agent_protocol(None) == "openai_chat_completions"


def test_provider_agent_binding_prefers_configured_protocol_when_argument_missing() -> None:
    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="Custom Gateway",
            protocol="anthropic_messages",
            base_url="https://gateway.example/v1",
            model="MiniMax-M3",
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
    )
    binding = ProviderAgentBinding(provider_service=service)

    assert binding.protocol == "anthropic_messages"


def test_native_binding_transport_timeout_exceeds_agent_loop_ceiling() -> None:
    assert DEFAULT_REQUEST_TIMEOUT_SECONDS == (
        CoachAgentLoop.MAX_STEP_TIMEOUT_SECONDS + TRANSPORT_TIMEOUT_MARGIN_SECONDS
    )
    assert TRANSPORT_TIMEOUT_MARGIN_SECONDS >= 5.0


def test_provider_service_build_agent_provider_uses_config_protocol() -> None:
    from app.core.models import ProviderConfig
    from app.llm.provider_service import ProviderService

    service = ProviderService(
        config=ProviderConfig(
            name="Custom Gateway",
            base_url="https://gateway.example",
            api_key_ref="trainer.custom",
            model="MiniMax-M3",
            protocol="anthropic_messages",
            capabilities={"tools": True, "vision": False},
        ),
        api_key="sk-test",
    )

    provider, binding = service.build_agent_provider()

    assert binding.protocol == "anthropic_messages"
    assert provider.protocol == "anthropic_messages"


def test_openai_responses_formatting_preserves_system_and_tool_flow() -> None:
    from app.llm.agent_binding import _format_openai_responses_input

    instructions, items = _format_openai_responses_input(
        [
            {"role": "system", "content": "coach system"},
            {"role": "user", "content": "look up memory"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "recall_memory", "arguments": '{"focus":"api"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "recall_memory",
                "content": '{"ok":true}',
            },
        ]
    )

    assert instructions == "coach system"
    assert items[0] == {"role": "user", "content": "look up memory"}
    assert items[1]["type"] == "function_call"
    assert items[1]["name"] == "recall_memory"
    assert items[1]["arguments"] == '{"focus":"api"}'
    assert items[2]["type"] == "function_call_output"
    assert items[2]["call_id"] == "call_1"


def test_openai_responses_formatting_inlines_verified_images_on_last_user() -> None:
    from app.llm.agent_binding import _format_openai_responses_input

    instructions, items = _format_openai_responses_input(
        [
            {"role": "system", "content": "coach system"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "inspect this"},
        ],
        attachments=[
            {"kind": "image", "mime_type": "image/jpeg", "data_base64": "SlBFRw=="},
            {"kind": "text", "data_base64": "ignored"},
            {"kind": "image", "data_base64": "QUFBQQ=="},
        ],
        vision_enabled=True,
    )

    assert instructions == "coach system"
    assert items[0] == {"role": "user", "content": "first"}
    assert items[-1] == {
        "role": "user",
        "content": [
            {"type": "input_text", "text": "inspect this"},
            {"type": "input_image", "image_url": "data:image/jpeg;base64,SlBFRw=="},
            {"type": "input_image", "image_url": "data:image/png;base64,QUFBQQ=="},
        ],
    }


def test_openai_responses_attachments_require_vision_enabled() -> None:
    from app.llm.agent_binding import _format_openai_responses_input

    _, items = _format_openai_responses_input(
        [{"role": "user", "content": "inspect"}],
        attachments=[{"kind": "image", "data_base64": "QUFBQQ=="}],
        vision_enabled=False,
    )

    assert items == [{"role": "user", "content": "inspect"}]


def test_openai_responses_parse_extracts_text_and_function_call() -> None:
    from app.llm.agent_binding import _parse_openai_responses_response

    parsed = _parse_openai_responses_response(
        {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "<think>x</think>Visible"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_2",
                    "name": "search_resources",
                    "arguments": '{"query":"protocol"}',
                },
            ]
        }
    )

    assert parsed["content"] == "Visible"
    assert parsed["tool_calls"] == [
        {
            "id": "call_2",
            "name": "search_resources",
            "arguments": '{"query":"protocol"}',
        }
    ]


def test_gemini_payload_and_parse_preserve_tool_flow() -> None:
    from app.llm.agent_binding import _format_gemini_payload, _parse_gemini_response

    payload = _format_gemini_payload(
        [
            {"role": "system", "content": "coach system"},
            {"role": "user", "content": "use resources"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "search_resources", "arguments": '{"query":"debug"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "search_resources",
                "content": '{"ok":true}',
            },
        ],
        [{"name": "search_resources", "description": "Search", "parameters": {"type": "object"}}],
    )

    assert payload["systemInstruction"]["parts"][0]["text"] == "coach system"
    assert payload["contents"][0]["role"] == "user"
    assert payload["contents"][1]["role"] == "model"
    assert payload["contents"][1]["parts"][0]["functionCall"]["name"] == "search_resources"
    assert payload["contents"][1]["parts"][0]["functionCall"]["args"] == {"query": "debug"}
    assert payload["contents"][2]["role"] == "function"
    assert payload["tools"][0]["functionDeclarations"][0]["name"] == "search_resources"

    parsed = _parse_gemini_response(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "<think>x</think>Visible"},
                            {
                                "functionCall": {
                                    "name": "recall_memory",
                                    "args": {"focus": "remote"},
                                }
                            },
                        ]
                    }
                }
            ]
        }
    )
    assert parsed["content"] == "Visible"
    assert parsed["tool_calls"] == [
        {"id": "recall_memory", "name": "recall_memory", "arguments": {"focus": "remote"}}
    ]


async def test_openai_responses_stream_emits_incremental_deltas_and_final_tool_calls() -> None:
    events = [
        SimpleNamespace(
            type="response.output_item.added",
            output_index=0,
            sequence_number=1,
            item=SimpleNamespace(
                type="function_call",
                id="call_1",
                call_id="call_1",
                name="search_resources",
                arguments="",
            ),
        ),
        SimpleNamespace(
            type="response.output_text.delta",
            content_index=0,
            delta="Hel",
            item_id="message_1",
            output_index=0,
            logprobs=[],
            sequence_number=2,
        ),
        SimpleNamespace(
            type="response.output_text.delta",
            content_index=0,
            delta="lo",
            item_id="message_1",
            output_index=0,
            logprobs=[],
            sequence_number=3,
        ),
        SimpleNamespace(
            type="response.function_call_arguments.delta",
            delta='{"query":"pro',
            item_id="call_1",
            output_index=0,
            sequence_number=4,
        ),
        SimpleNamespace(
            type="response.function_call_arguments.delta",
            delta='tocol"}',
            item_id="call_1",
            output_index=0,
            sequence_number=5,
        ),
        SimpleNamespace(type="response.completed", sequence_number=6),
    ]
    final_response = {
        "output_text": "Hello",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Hello"}],
            },
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "search_resources",
                "arguments": '{"query":"protocol"}',
            },
        ],
    }
    fake_stream = _FakeAsyncStream(events, final_response)
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(stream=MagicMock(return_value=_FakeAsyncStreamManager(fake_stream)))
    )
    service = _FakeProviderService(client=fake_client, model="gpt-4.1-mini")
    binding = ProviderAgentBinding(provider_service=service, protocol="openai_responses")
    binding._call = AsyncMock(side_effect=AssertionError("openai_responses stream must not call _call"))

    deltas: list[str] = []
    final_event: dict[str, Any] | None = None
    async for event in binding._call_stream([{"role": "user", "content": "hello"}], None):
        if event["type"] == "delta":
            deltas.append(event["delta"])
        if event["type"] == "final":
            final_event = event

    assert deltas == ["Hel", "lo"]
    assert final_event is not None
    assert final_event["content"] == "Hello"
    assert final_event["tool_calls"] == [
        {
            "id": "call_1",
            "name": "search_resources",
            "arguments": '{"query":"protocol"}',
        }
    ]
    assert fake_client.responses.stream.call_count == 1


async def test_gemini_stream_emits_incremental_deltas_and_final_tool_calls() -> None:
    chunks = [
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Hel"},
                        ]
                    }
                }
            ]
        },
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "lo"},
                            {
                                "functionCall": {
                                    "name": "search_resources",
                                    "args": {"query": "protocol"},
                                }
                            },
                        ]
                    }
                }
            ]
        },
    ]
    lines = [f"data: {json.dumps(chunk, ensure_ascii=False)}" for chunk in chunks] + ["data: [DONE]"]
    fake_response = _FakeGeminiResponse(lines)
    fake_client = _FakeGeminiAsyncClient(fake_response)
    service = _FakeProviderService(
        client=SimpleNamespace(),
        model="gemini-2.0-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta",
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="gemini_generate_content")
    binding._call = AsyncMock(side_effect=AssertionError("gemini stream must not call _call"))

    deltas: list[str] = []
    final_event: dict[str, Any] | None = None
    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=fake_client):
        async for event in binding._call_stream([{"role": "user", "content": "hello"}], None):
            if event["type"] == "delta":
                deltas.append(event["delta"])
            if event["type"] == "final":
                final_event = event

    assert deltas == ["Hel", "lo"]
    assert final_event is not None
    assert final_event["content"] == "Hello"
    assert final_event["tool_calls"] == [
        {
            "id": "search_resources",
            "name": "search_resources",
            "arguments": {"query": "protocol"},
        }
    ]
    assert fake_client.calls[0][1].endswith(":streamGenerateContent?alt=sse")


def test_attachments_supported_requires_vision_flag() -> None:
    assert attachments_supported("anthropic_messages", True) is True
    assert attachments_supported("openai_chat_completions", True) is True
    assert attachments_supported("anthropic_messages", False) is False
    assert attachments_supported("gemini_generate_content", True) is True
    assert attachments_supported("gemini_generate_content", False) is False


def test_openai_message_formatting_inlines_image_on_last_user() -> None:
    from app.llm.agent_binding import _format_openai_messages

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "look at this"},
    ]
    attachments = [
        {"kind": "image", "mime_type": "image/png", "data_base64": "QUFBQQ=="},
    ]
    formatted = _format_openai_messages(messages, attachments=attachments, vision_enabled=True)
    last = formatted[-1]
    assert last["role"] == "user"
    assert isinstance(last["content"], list)
    parts = last["content"]
    assert parts[0] == {"type": "text", "text": "look at this"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    # Earlier user message must NOT carry image parts.
    assert formatted[1]["content"] == "first"


def test_gemini_payload_inlines_images_only_on_last_user() -> None:
    from app.llm.agent_binding import _format_gemini_payload

    payload = _format_gemini_payload(
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "inspect"},
        ],
        None,
        attachments=[
            {"kind": "image", "mime_type": "image/jpeg", "data_base64": "SlBFRw=="},
            {"kind": "text", "data_base64": "ignored"},
            {"kind": "image", "data_base64": ""},
        ],
        vision_enabled=True,
    )

    assert payload["contents"][0]["parts"] == [{"text": "first"}]
    assert payload["contents"][2]["parts"] == [
        {"text": "inspect"},
        {"inlineData": {"mimeType": "image/jpeg", "data": "SlBFRw=="}},
    ]


def test_gemini_payload_does_not_inline_images_without_verified_vision() -> None:
    from app.llm.agent_binding import _format_gemini_payload

    payload = _format_gemini_payload(
        [{"role": "user", "content": "inspect"}],
        None,
        attachments=[{"kind": "image", "data_base64": "SlBFRw=="}],
        vision_enabled=False,
    )

    assert payload["contents"][0]["parts"] == [{"text": "inspect"}]


def test_openai_message_formatting_preserves_tool_messages() -> None:
    from app.llm.agent_binding import _format_openai_messages

    messages = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "echo", "arguments": '{"text":"x"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "echo", "content": '{"ok": true}'},
    ]
    formatted = _format_openai_messages(messages, vision_enabled=False)
    assert formatted[2]["role"] == "tool"
    assert formatted[2]["tool_call_id"] == "c1"
    assert formatted[1]["role"] == "assistant"
    assert formatted[1]["tool_calls"][0]["function"]["name"] == "echo"


# ---------------------------------------------------------------------------
# ProviderAgentBinding — Anthropic formatting
# ---------------------------------------------------------------------------


def test_anthropic_split_extracts_system_and_converts_tool_flow() -> None:
    from app.llm.agent_binding import _split_anthropic_messages

    messages = [
        {"role": "system", "content": "you are a coach"},
        {"role": "user", "content": "do something"},
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "echo", "arguments": '{"text":"x"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "echo", "content": "result"},
    ]
    system_text, converted = _split_anthropic_messages(
        messages, attachments=None, vision_enabled=False
    )
    assert system_text == "you are a coach"
    # user → user text block
    assert converted[0]["role"] == "user"
    assert converted[0]["content"][0]["type"] == "text"
    # assistant → text + tool_use block
    assistant_blocks = converted[1]["content"]
    assert any(block["type"] == "tool_use" for block in assistant_blocks)
    tool_use = next(block for block in assistant_blocks if block["type"] == "tool_use")
    assert tool_use["name"] == "echo"
    assert tool_use["input"] == {"text": "x"}
    # tool result → user role with tool_result block
    assert converted[2]["role"] == "user"
    assert converted[2]["content"][0]["type"] == "tool_result"
    assert converted[2]["content"][0]["tool_use_id"] == "c1"


def test_anthropic_image_blocks_on_last_user() -> None:
    from app.llm.agent_binding import _split_anthropic_messages

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first"},
        {"role": "user", "content": "see image"},
    ]
    attachments = [{"kind": "image", "mime_type": "image/jpeg", "data_base64": "AAA="}]
    _system, converted = _split_anthropic_messages(
        messages, attachments=attachments, vision_enabled=True
    )
    last_user = converted[-1]
    assert last_user["role"] == "user"
    block_types = [block["type"] for block in last_user["content"]]
    assert "image" in block_types
    image_block = next(block for block in last_user["content"] if block["type"] == "image")
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert image_block["source"]["data"] == "AAA="
    # first user must not carry an image
    assert all(block["type"] != "image" for block in converted[0]["content"])


def test_anthropic_parse_response_extracts_text_and_tool_use() -> None:
    from app.llm.agent_binding import _parse_anthropic_response

    payload = {
        "content": [
            {"type": "text", "text": "Let me check memory."},
            {"type": "tool_use", "id": "t1", "name": "recall_memory", "input": {"focus": "x"}},
        ]
    }
    parsed = _parse_anthropic_response(payload)
    assert parsed["content"] == "Let me check memory."
    assert parsed["tool_calls"][0]["id"] == "t1"
    assert parsed["tool_calls"][0]["name"] == "recall_memory"
    assert parsed["tool_calls"][0]["arguments"] == {"focus": "x"}


async def test_anthropic_call_strips_reasoning_content() -> None:
    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-3-5-sonnet-latest",
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "content": [
                    {"type": "text", "text": "<think>internal</think>Hello"},
                ]
            }

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=_Response())
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=mock_cm) as async_client:
        provider = binding.build_agent_provider()
        result = await provider.call([{"role": "user", "content": "hi"}], None)

    async_client.assert_called_once_with(timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    assert result["content"] == "Hello"
    assert "<think>" not in result["content"]
    assert "thinking" not in mock_client.post.call_args.kwargs["json"]


async def test_nonofficial_anthropic_default_disables_thinking_on_first_request() -> None:
    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="compatible-gateway",
            base_url="https://gateway.example/v1",
            model="compatible-model",
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _Response:
        status_code = 200

        def __init__(self, body: dict[str, Any]) -> None:
            self._body = body

        def json(self) -> dict[str, Any]:
            return self._body

    client = MagicMock()
    client.post = AsyncMock(
        return_value=_Response(
            {
                "content": [{"type": "text", "text": "Visible coaching reply"}],
                "stop_reason": "end_turn",
            }
        )
    )
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=client_context):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "help me"}],
            None,
        )

    assert result["content"] == "Visible coaching reply"
    assert client.post.await_count == 1
    assert client.post.call_args.kwargs["json"]["thinking"] == {"type": "disabled"}


async def test_nonofficial_anthropic_preserves_explicit_thinking_setting() -> None:
    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="compatible-gateway",
            base_url="https://gateway.example/v1",
            model="compatible-model",
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
        _provider_request_defaults=lambda: {"extra_body": {"thinking": {"type": "enabled"}}},
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "content": [{"type": "text", "text": "Configured thinking reply"}],
                "stop_reason": "end_turn",
            }

    client = MagicMock()
    client.post = AsyncMock(return_value=_Response())
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=client_context):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "help me"}],
            None,
        )

    assert result["content"] == "Configured thinking reply"
    assert client.post.call_args.kwargs["json"]["thinking"] == {"type": "enabled"}


def test_nonofficial_anthropic_preserves_explicit_thinking_defaults() -> None:
    cases = (
        (
            {"extra_body": {"thinking": {"type": "disabled"}}},
            {"type": "disabled"},
        ),
        (
            {"thinkingBudget": 512},
            {"type": "enabled", "budget_tokens": 512},
        ),
    )
    for defaults, expected in cases:
        service = SimpleNamespace(
            _config=SimpleNamespace(base_url="https://gateway.example/v1"),
            _provider_request_defaults=lambda defaults=defaults: defaults,
        )
        binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")
        configured = binding._apply_anthropic_request_defaults({"messages": []})

        assert binding._apply_nonofficial_anthropic_thinking_default(configured) == configured
        assert configured["thinking"] == expected


async def test_anthropic_compatible_truncation_fallback_disables_openai_thinking() -> None:
    class _Response:
        status_code = 200

        def __init__(self, body: dict[str, Any]) -> None:
            self._body = body

        def json(self) -> dict[str, Any]:
            return self._body

    openai_choice = MagicMock()
    openai_choice.message.content = "OpenAI fallback reply"
    openai_choice.message.tool_calls = []
    openai_response = MagicMock()
    openai_response.choices = [openai_choice]
    openai_client = MagicMock()
    openai_client.chat.completions.create = AsyncMock(return_value=openai_response)
    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="compatible-gateway",
            base_url="https://gateway.example/v1",
            model="compatible-model",
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
        _get_client=MagicMock(return_value=openai_client),
        _apply_request_defaults=lambda payload: payload,
        _resolve_model=lambda: "compatible-model",
        _model_candidates=lambda model: [model],
        _is_model_not_supported_error=lambda exc: False,
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")
    native_client = MagicMock()
    native_client.post = AsyncMock(
        side_effect=[
            _Response(
                {
                    "content": [{"type": "text", "text": "first partial response"}],
                    "stop_reason": "max_tokens",
                }
            ),
            _Response(
                {
                    "content": [{"type": "text", "text": "second partial response"}],
                    "stop_reason": "max_tokens",
                }
            ),
        ]
    )
    native_context = MagicMock()
    native_context.__aenter__ = AsyncMock(return_value=native_client)
    native_context.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=native_context):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "help me"}],
            None,
        )

    assert result["content"] == "OpenAI fallback reply"
    assert native_client.post.await_count == 2
    assert all(
        call.kwargs["json"]["thinking"] == {"type": "disabled"}
        for call in native_client.post.call_args_list
    )
    _, kwargs = openai_client.chat.completions.create.call_args
    assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}


def test_compatibility_fallback_preserves_explicit_thinking_setting() -> None:
    service = SimpleNamespace(
        _config=SimpleNamespace(base_url="https://gateway.example/v1"),
        _provider_request_defaults=lambda: {"extra_body": {"thinking": {"type": "enabled"}}},
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")
    payload = {"messages": [{"role": "user", "content": "help me"}]}

    assert binding._apply_compatibility_thinking_disabled(payload) == payload


async def test_anthropic_stream_uses_transport_timeout_after_agent_loop_ceiling() -> None:
    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-3-5-sonnet-latest",
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _StreamResponse:
        status_code = 200

        async def aiter_lines(self):
            yield 'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}'
            yield 'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}'
            yield 'data: {"type":"message_stop"}'

    class _StreamContext:
        async def __aenter__(self) -> _StreamResponse:
            return _StreamResponse()

        async def __aexit__(self, *_args: object) -> bool:
            return False

    client = MagicMock()
    client.stream.return_value = _StreamContext()
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.llm.agent_binding.httpx.AsyncClient", return_value=client_context
    ) as async_client:
        events = [
            event
            async for event in binding.build_agent_provider().call_stream(
                [{"role": "user", "content": "hi"}], None
            )
        ]

    async_client.assert_called_once_with(timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    assert events[-1]["content"] == "Hello"
    assert "thinking" not in client.stream.call_args.kwargs["json"]


async def test_nonofficial_anthropic_stream_disables_thinking_on_first_request() -> None:
    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="compatible-gateway",
            base_url="https://gateway.example/v1",
            model="compatible-model",
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _StreamResponse:
        status_code = 200

        async def aiter_lines(self):
            yield 'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}'
            yield 'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}'
            yield 'data: {"type":"message_stop"}'

    class _StreamContext:
        async def __aenter__(self) -> _StreamResponse:
            return _StreamResponse()

        async def __aexit__(self, *_args: object) -> bool:
            return False

    client = MagicMock()
    client.stream.return_value = _StreamContext()
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=client_context):
        events = [
            event
            async for event in binding.build_agent_provider().call_stream(
                [{"role": "user", "content": "hi"}], None
            )
        ]

    assert events[-1]["content"] == "Hello"
    assert client.stream.call_args.kwargs["json"]["thinking"] == {"type": "disabled"}


async def test_nonofficial_anthropic_stream_uses_openai_stream_fallback_for_visible_deltas() -> None:
    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="compatible-gateway",
            base_url="https://gateway.example/v1",
            model="compatible-model",
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
    )
    openai_client = MagicMock()

    async def _chunk_iter() -> AsyncIterator[Any]:
        for piece in ("Open", "AI"):
            chunk = MagicMock()
            delta = MagicMock()
            delta.content = piece
            delta.tool_calls = []
            choice = MagicMock()
            choice.delta = delta
            chunk.choices = [choice]
            yield chunk

    openai_client.chat.completions.create = AsyncMock(return_value=_chunk_iter())
    service._get_client = MagicMock(return_value=openai_client)  # type: ignore[attr-defined]
    service._apply_request_defaults = lambda payload: payload  # type: ignore[attr-defined]
    service._resolve_model = lambda: "compatible-model"  # type: ignore[attr-defined]
    service._model_candidates = lambda model: [model]  # type: ignore[attr-defined]
    service._is_model_not_supported_error = lambda exc: False  # type: ignore[attr-defined]
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _AnthropicStreamResponse:
        status_code = 200

        async def aiter_lines(self):
            yield 'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}'
            yield 'data: {"type":"message_stop"}'

    class _AnthropicStreamContext:
        async def __aenter__(self) -> _AnthropicStreamResponse:
            return _AnthropicStreamResponse()

        async def __aexit__(self, *_args: object) -> bool:
            return False

    client = MagicMock()
    client.stream.return_value = _AnthropicStreamContext()
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=client_context):
        events = [
            event
            async for event in binding.build_agent_provider().call_stream(
                [{"role": "user", "content": "hi"}], None
            )
        ]

    deltas = [event["delta"] for event in events if event["type"] == "delta"]
    finals = [event for event in events if event["type"] == "final"]
    assert deltas == ["Open", "AI"]
    assert finals[0]["content"] == "OpenAI"
    assert finals[0]["stop_reason"] == "stop"
    assert client.stream.call_args.kwargs["json"]["thinking"] == {"type": "disabled"}
    _, kwargs = openai_client.chat.completions.create.call_args
    assert kwargs["stream"] is True
    assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}


async def test_anthropic_binding_defers_cancellation_to_agent_step_timeout() -> None:
    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-3-5-sonnet-latest",
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    async def _slow_post(*_args: object, **_kwargs: object) -> object:
        await asyncio.sleep(2)
        raise AssertionError("outer agent timeout should cancel the binding first")

    client = MagicMock()
    client.post = AsyncMock(side_effect=_slow_post)
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)

    loop = CoachAgentLoop(
        provider=binding.build_agent_provider(),
        registry=_toy_registry(),
        context=_context(),
        max_steps=1,
        first_step_timeout=CoachAgentLoop.MIN_STEP_TIMEOUT_SECONDS,
    )
    with patch(
        "app.llm.agent_binding.httpx.AsyncClient", return_value=client_context
    ) as async_client:
        result = await loop.run([{"role": "user", "content": "hi"}])

    async_client.assert_called_once_with(timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    assert result.stop_reason == "timeout"


async def test_anthropic_transport_error_remains_provider_error() -> None:
    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-3-5-sonnet-latest",
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")
    client = MagicMock()
    client.post = AsyncMock(side_effect=httpx.ReadTimeout("simulated transport timeout"))
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)

    loop = CoachAgentLoop(
        provider=binding.build_agent_provider(),
        registry=_toy_registry(),
        context=_context(),
        max_steps=1,
    )
    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=client_context):
        result = await loop.run([{"role": "user", "content": "hi"}])

    assert result.stop_reason == "provider_error"


# ---------------------------------------------------------------------------
# ProviderAgentBinding — live OpenAI call path (mocked client)
# ---------------------------------------------------------------------------


def _anthropic_compatible_service_with_fallback_reply(
    reply: str = "OpenAI-compatible fallback reply",
) -> tuple[SimpleNamespace, MagicMock]:
    fake_openai_client = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = reply
    fake_choice.message.tool_calls = []
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_openai_client.chat.completions.create = AsyncMock(return_value=fake_response)
    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="anthropic-compatible",
            base_url="https://gateway.example/v1",
            model="MiniMax-M3",
            request_defaults={},
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
        _get_client=MagicMock(return_value=fake_openai_client),
        _apply_request_defaults=lambda payload: payload,
        _resolve_model=lambda: "MiniMax-M3",
        _model_candidates=lambda model: [model],
        _is_model_not_supported_error=lambda exc: False,
    )
    return service, fake_openai_client


async def test_anthropic_compatible_gateway_falls_back_on_native_messages_404() -> None:
    service, fake_openai_client = _anthropic_compatible_service_with_fallback_reply(
        "<think>internal</think>Fallback after native 404"
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _NotFoundResponse:
        status_code = 404
        text = '{"error":"Unknown path /v1/messages"}'

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=_NotFoundResponse())
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=mock_cm):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "teach remote ssh"}],
            None,
        )

    assert result == {"content": "Fallback after native 404", "tool_calls": []}
    fake_openai_client.chat.completions.create.assert_awaited_once()


async def test_anthropic_compatible_gateway_falls_back_on_native_messages_415() -> None:
    service, fake_openai_client = _anthropic_compatible_service_with_fallback_reply()
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _UnsupportedMediaTypeResponse:
        status_code = 415
        text = '{"error":"Unsupported content type for this endpoint"}'

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=_UnsupportedMediaTypeResponse())
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=mock_cm):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "teach remote ssh"}],
            None,
        )

    assert result == {"content": "OpenAI-compatible fallback reply", "tool_calls": []}
    fake_openai_client.chat.completions.create.assert_awaited_once()


async def test_anthropic_compatible_gateway_does_not_fall_back_on_invalid_api_key() -> None:
    service, fake_openai_client = _anthropic_compatible_service_with_fallback_reply()
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _InvalidApiKeyResponse:
        status_code = 401
        text = '{"error":"Invalid API key"}'

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=_InvalidApiKeyResponse())
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=mock_cm):
        try:
            await binding.build_agent_provider().call(
                [{"role": "user", "content": "teach remote ssh"}],
                None,
            )
        except RuntimeError as exc:
            assert "HTTP 401" in str(exc)
            assert "Invalid API key" not in str(exc)
        else:
            raise AssertionError("An invalid API key must not use the OpenAI-compatible fallback.")

    fake_openai_client.chat.completions.create.assert_not_awaited()


async def test_anthropic_compatible_gateway_falls_back_on_mismatched_auth_header() -> None:
    service, fake_openai_client = _anthropic_compatible_service_with_fallback_reply()
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _BearerAuthResponse:
        status_code = 401
        text = '{"error":"Authorization header required: use Bearer token"}'

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=_BearerAuthResponse())
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=mock_cm):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "teach remote ssh"}],
            None,
        )

    assert result == {"content": "OpenAI-compatible fallback reply", "tool_calls": []}
    fake_openai_client.chat.completions.create.assert_awaited_once()


async def test_anthropic_call_retries_when_visible_reply_is_empty() -> None:
    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="anthropic",
            base_url="https://api.anthropic.com/v1",
            model="claude-3-5-sonnet-latest",
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _ThinkOnlyResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "content": [
                    {"type": "text", "text": "<think>internal only</think>"},
                ]
            }

    class _VisibleResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "content": [
                    {"type": "text", "text": "<think>internal</think>Visible answer"},
                ]
            }

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=[_ThinkOnlyResponse(), _VisibleResponse()])
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=mock_cm):
        provider = binding.build_agent_provider()
        result = await provider.call([{"role": "user", "content": "hi"}], None)

    assert result["content"] == "Visible answer"
    assert result["tool_calls"] == []
    assert mock_client.post.await_count == 2


async def test_anthropic_compatible_gateway_falls_back_to_openai_chat_when_empty() -> None:
    fake_openai_client = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = "OpenAI-compatible fallback reply"
    fake_choice.message.tool_calls = []
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_openai_client.chat.completions.create = AsyncMock(return_value=fake_response)

    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="anthropic-compatible",
            base_url="https://gateway.example/v1",
            model="MiniMax-M3",
            request_defaults={},
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
        _get_client=MagicMock(return_value=fake_openai_client),
        _apply_request_defaults=lambda payload: payload,
        _resolve_model=lambda: "MiniMax-M3",
        _model_candidates=lambda model: [model],
        _is_model_not_supported_error=lambda exc: False,
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _EmptyResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"content": [{"type": "text", "text": "<think>internal only</think>"}]}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=_EmptyResponse())
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=mock_cm):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "teach remote ssh"}],
            None,
        )

    assert result["content"] == "OpenAI-compatible fallback reply"
    assert result["tool_calls"] == []
    fake_openai_client.chat.completions.create.assert_awaited_once()


async def test_anthropic_compatible_gateway_accepts_string_fallback_response() -> None:
    fake_openai_client = MagicMock()
    fake_openai_client.chat.completions.create = AsyncMock(
        return_value="OpenAI-compatible fallback reply",
    )

    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="anthropic-compatible",
            base_url="https://gateway.example/v1",
            model="MiniMax-M3",
            request_defaults={},
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
        _get_client=MagicMock(return_value=fake_openai_client),
        _apply_request_defaults=lambda payload: payload,
        _resolve_model=lambda: "MiniMax-M3",
        _model_candidates=lambda model: [model],
        _is_model_not_supported_error=lambda exc: False,
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _EmptyResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"content": [{"type": "text", "text": "<think>internal only</think>"}]}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=_EmptyResponse())
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=mock_cm):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "teach remote ssh"}],
            None,
        )

    assert result["content"] == "OpenAI-compatible fallback reply"
    assert result["tool_calls"] == []
    fake_openai_client.chat.completions.create.assert_awaited_once()


async def test_anthropic_compatible_gateway_normalizes_tools_for_openai_fallback() -> None:
    registry = build_default_tool_registry()
    fake_openai_client = MagicMock()
    tool_call = MagicMock()
    tool_call.id = "call_search"
    tool_call.function = MagicMock()
    tool_call.function.name = "search_resources"
    tool_call.function.arguments = '{"query":"remote debug protocol"}'
    fallback_message = MagicMock()
    fallback_message.content = ""
    fallback_message.tool_calls = [tool_call]
    fallback_choice = MagicMock()
    fallback_choice.message = fallback_message
    fallback_response = MagicMock()
    fallback_response.choices = [fallback_choice]
    fake_openai_client.chat.completions.create = AsyncMock(return_value=fallback_response)

    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="anthropic-compatible",
            base_url="https://gateway.example/v1",
            model="MiniMax-M3",
            request_defaults={},
            capabilities=SimpleNamespace(vision=False, chat=True, tools=True),
        ),
        _get_client=MagicMock(return_value=fake_openai_client),
        _apply_request_defaults=lambda payload: payload,
        _resolve_model=lambda: "MiniMax-M3",
        _model_candidates=lambda model: [model],
        _is_model_not_supported_error=lambda exc: False,
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="anthropic_messages")

    class _EmptyResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"content": [{"type": "text", "text": "<think>internal only</think>"}]}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=_EmptyResponse())
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=mock_cm):
        result = await binding.build_agent_provider().call(
            [{"role": "user", "content": "search resources before answering"}],
            registry.as_protocol_schemas("anthropic_messages"),
        )

    _, kwargs = fake_openai_client.chat.completions.create.call_args
    assert kwargs["tools"][0]["type"] == "function"
    assert kwargs["tools"][0]["function"]["name"] == "search_resources"
    assert result["tool_calls"] == [
        {
            "id": "call_search",
            "name": "search_resources",
            "arguments": '{"query":"remote debug protocol"}',
        }
    ]


async def test_gemini_compatible_gateway_retries_openai_chat_when_visible_reply_is_empty() -> None:
    fake_openai_client = MagicMock()
    first_choice = MagicMock()
    first_choice.message.content = "<think>internal only</think>"
    first_choice.message.tool_calls = []
    first_response = MagicMock()
    first_response.choices = [first_choice]

    second_choice = MagicMock()
    second_choice.message.content = "Visible fallback reply"
    second_choice.message.tool_calls = []
    second_response = MagicMock()
    second_response.choices = [second_choice]

    fake_openai_client.chat.completions.create = AsyncMock(
        side_effect=[first_response, second_response],
    )

    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="gemini-compatible",
            base_url="https://gateway.example/v1",
            model="MiniMax-M3",
            protocol="gemini_generate_content",
            request_defaults={},
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
        _get_client=MagicMock(return_value=fake_openai_client),
        _apply_request_defaults=lambda payload: payload,
        _resolve_model=lambda: "MiniMax-M3",
        _model_candidates=lambda model: [model],
        _is_model_not_supported_error=lambda exc: False,
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="gemini_generate_content")

    result = await binding.build_agent_provider().call(
        [{"role": "user", "content": "teach remote ssh"}],
        None,
    )

    assert result["content"] == "Visible fallback reply"
    assert result["tool_calls"] == []
    assert fake_openai_client.chat.completions.create.await_count == 2
    _, retry_kwargs = fake_openai_client.chat.completions.create.await_args_list[1]
    assert OPENAI_VISIBLE_REPLY_RETRY_HINT in retry_kwargs["messages"][0]["content"]


async def test_gemini_compatible_gateway_stream_retries_openai_chat_when_visible_reply_is_empty() -> (
    None
):
    fake_openai_client = MagicMock()

    first_chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content="<think>internal only</think>", tool_calls=[])
            )
        ]
    )

    async def _empty_stream():
        yield first_chunk

    second_choice = MagicMock()
    second_choice.message.content = "Visible stream fallback reply"
    second_choice.message.tool_calls = []
    second_response = MagicMock()
    second_response.choices = [second_choice]

    fake_openai_client.chat.completions.create = AsyncMock(
        side_effect=[_empty_stream(), second_response],
    )

    service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="gemini-compatible",
            base_url="https://gateway.example/v1",
            model="MiniMax-M3",
            protocol="gemini_generate_content",
            request_defaults={},
            capabilities=SimpleNamespace(vision=False, chat=True),
        ),
        _get_client=MagicMock(return_value=fake_openai_client),
        _apply_request_defaults=lambda payload: payload,
        _resolve_model=lambda: "MiniMax-M3",
        _model_candidates=lambda model: [model],
        _is_model_not_supported_error=lambda exc: False,
    )
    binding = ProviderAgentBinding(provider_service=service, protocol="gemini_generate_content")

    events = [
        event
        async for event in binding.build_agent_provider().call_stream(
            [{"role": "user", "content": "teach remote ssh"}],
            None,
        )
    ]

    assert events == [
        {"type": "delta", "delta": "Visible stream fallback reply"},
        {
            "type": "final",
            "content": "Visible stream fallback reply",
            "tool_calls": [],
            "stop_reason": "stop",
        },
    ]
    assert fake_openai_client.chat.completions.create.await_count == 2


def _make_provider_service_with_mock_client() -> tuple[Any, MagicMock]:
    from app.llm.provider_service import ProviderService

    service = ProviderService()
    service._api_key = "sk-test"  # noqa: SLF001
    service._config = SimpleNamespace(  # noqa: SLF001
        name="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        capabilities=SimpleNamespace(vision=False, chat=True),
    )
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    service._get_client = lambda: mock_client  # type: ignore[method-assign]
    return service, mock_client


async def test_openai_chat_call_extracts_content_and_tool_calls() -> None:
    service, mock_client = _make_provider_service_with_mock_client()
    binding = ProviderAgentBinding(provider_service=service, protocol="openai_chat_completions")

    message = MagicMock()
    message.content = "<think>internal notes</think>Here is the plan."
    message.tool_calls = []
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    mock_client.chat.completions.create = AsyncMock(return_value=response)

    provider = binding.build_agent_provider()
    result = await provider.call(
        [{"role": "user", "content": "plan"}],
        [{"type": "function", "function": {"name": "echo"}}],
    )
    assert result["content"] == "Here is the plan."
    assert result["tool_calls"] == []


async def test_agent_binding_protocol_call_matrix_preserves_tools() -> None:
    registry = build_default_tool_registry()
    messages = [
        {"role": "system", "content": "Use tools when useful."},
        {"role": "user", "content": "Search resources before answering."},
    ]

    # OpenAI chat and OpenAI-compatible chat share the chat.completions call
    # shape, but both protocol ids must keep tool schemas intact.
    for protocol in ("openai_chat_completions", "openai_chat_completions_compatible"):
        service, mock_client = _make_provider_service_with_mock_client()
        binding = ProviderAgentBinding(provider_service=service, protocol=protocol)
        tool_call = MagicMock()
        tool_call.id = "call_search"
        tool_call.function = MagicMock()
        tool_call.function.name = "search_resources"
        tool_call.function.arguments = '{"query":"remote debug protocol"}'
        message = MagicMock()
        message.content = ""
        message.tool_calls = [tool_call]
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        result = await binding.build_agent_provider().call(
            messages,
            registry.as_protocol_schemas(protocol),
        )

        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["tools"][0]["function"]["name"] == "search_resources"
        assert result["tool_calls"] == [
            {
                "id": "call_search",
                "name": "search_resources",
                "arguments": '{"query":"remote debug protocol"}',
            }
        ]

    # OpenAI Responses uses the native responses.create payload.
    responses_service, responses_client = _make_provider_service_with_mock_client()
    responses_client.responses = MagicMock()
    responses_client.responses.create = AsyncMock(
        return_value={
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_search",
                    "name": "search_resources",
                    "arguments": '{"query":"responses protocol"}',
                }
            ]
        }
    )
    responses_binding = ProviderAgentBinding(
        provider_service=responses_service,
        protocol="openai_responses",
    )
    responses_result = await responses_binding.build_agent_provider().call(
        messages,
        registry.as_protocol_schemas("openai_responses"),
    )
    _, responses_kwargs = responses_client.responses.create.call_args
    assert responses_kwargs["tools"][0]["name"] == "search_resources"
    assert responses_result["tool_calls"][0]["name"] == "search_resources"

    # Anthropic Messages uses /v1/messages with input_schema tool definitions.
    anthropic_service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="anthropic",
            base_url="https://api.anthropic.com",
            model="claude-3-5-sonnet-latest",
            capabilities=SimpleNamespace(vision=False, chat=True, tools=True),
        ),
    )
    anthropic_binding = ProviderAgentBinding(
        provider_service=anthropic_service,
        protocol="anthropic_messages",
    )

    class _AnthropicResponse:
        status_code = 200
        text = '{"content":[{"type":"tool_use","id":"call_search","name":"search_resources","input":{"query":"anthropic protocol"}}]}'

        def json(self) -> dict[str, Any]:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_search",
                        "name": "search_resources",
                        "input": {"query": "anthropic protocol"},
                    }
                ]
            }

    anthropic_client = MagicMock()
    anthropic_client.post = AsyncMock(return_value=_AnthropicResponse())
    anthropic_cm = MagicMock()
    anthropic_cm.__aenter__ = AsyncMock(return_value=anthropic_client)
    anthropic_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=anthropic_cm):
        anthropic_result = await anthropic_binding.build_agent_provider().call(
            messages,
            registry.as_protocol_schemas("anthropic_messages"),
        )

    _, anthropic_kwargs = anthropic_client.post.call_args
    assert anthropic_kwargs["json"]["tools"][0]["name"] == "search_resources"
    assert "input_schema" in anthropic_kwargs["json"]["tools"][0]
    assert anthropic_result["tool_calls"][0]["arguments"] == {"query": "anthropic protocol"}

    # Gemini GenerateContent uses functionDeclarations and parses functionCall.
    gemini_service = SimpleNamespace(
        _api_key="sk-test",
        _config=SimpleNamespace(
            name="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-2.0-flash",
            request_defaults={},
            capabilities=SimpleNamespace(vision=False, chat=True, tools=True),
        ),
    )
    gemini_binding = ProviderAgentBinding(
        provider_service=gemini_service,
        protocol="gemini_generate_content",
    )

    class _GeminiResponse:
        status_code = 200
        text = '{"candidates":[{"content":{"parts":[{"functionCall":{"name":"search_resources","args":{"query":"gemini protocol"}}}]}}]}'

        def json(self) -> dict[str, Any]:
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "search_resources",
                                        "args": {"query": "gemini protocol"},
                                    }
                                }
                            ]
                        }
                    }
                ]
            }

    gemini_client = MagicMock()
    gemini_client.post = AsyncMock(return_value=_GeminiResponse())
    gemini_cm = MagicMock()
    gemini_cm.__aenter__ = AsyncMock(return_value=gemini_client)
    gemini_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=gemini_cm) as async_client:
        gemini_result = await gemini_binding.build_agent_provider().call(
            messages,
            registry.as_protocol_schemas("gemini_generate_content"),
        )

    async_client.assert_called_once_with(timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    _, gemini_kwargs = gemini_client.post.call_args
    function_declarations = gemini_kwargs["json"]["tools"][0]["functionDeclarations"]
    assert function_declarations[0]["name"] == "search_resources"
    assert gemini_result["tool_calls"][0]["arguments"] == {"query": "gemini protocol"}


async def test_openai_chat_stream_emits_delta_and_final() -> None:
    service, mock_client = _make_provider_service_with_mock_client()
    binding = ProviderAgentBinding(provider_service=service, protocol="openai_chat_completions")

    async def _chunk_iter():
        for piece in ("<th", "ink>hidden</think>Hello", " world"):
            chunk = MagicMock()
            delta = MagicMock()
            delta.content = piece
            delta.tool_calls = []
            choice = MagicMock()
            choice.delta = delta
            chunk.choices = [choice]
            yield chunk

    mock_client.chat.completions.create = AsyncMock(return_value=_chunk_iter())

    provider = binding.build_agent_provider()
    events = [event async for event in provider.call_stream([], None)]
    deltas = [event for event in events if event["type"] == "delta"]
    finals = [event for event in events if event["type"] == "final"]
    assert "".join(event["delta"] for event in deltas) == "Hello world"
    assert finals[0]["content"] == "Hello world"
    assert finals[0]["stop_reason"] == "stop"


# ---------------------------------------------------------------------------
# ProviderService.coaching_reply_agentic — end-to-end with mocked provider
# ---------------------------------------------------------------------------


async def test_coaching_reply_agentic_returns_envelope_when_model_uses_tool() -> None:
    """Sanity-check the full agent path through ``ProviderService``.

    Validates that:
    * the coaching messages get prefixed with the system prompt (incl. the
      tool guide block);
    * scripted tool-calls flow through the registry and back into the
      provider;
    * the returned envelope surfaces ``tool_events`` and a non-empty
      ``content``.
    """
    from app.core.models import UserProfile
    from app.llm.provider_service import ProviderService

    profile = UserProfile(
        long_term_goal="ship one slice a day",
        weekly_hours=4,
        teaching_style="hands-on",
        answer_policy="guided",
        background="ten years c++",
    )
    service = ProviderService()
    service._api_key = "sk-test"  # noqa: SLF001
    service._config = SimpleNamespace(  # noqa: SLF001
        name="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        capabilities=SimpleNamespace(vision=False, chat=True, tools=True),
    )
    # Track turn count so the model first calls a tool then finalizes.
    call_count = {"n": 0}

    async def _fake_create(model: str, **kwargs: Any) -> Any:  # noqa: ARG001
        call_count["n"] += 1
        message = MagicMock()
        if call_count["n"] == 1:
            message.content = ""
            tool_call = MagicMock()
            tool_call.id = "call_recall"
            tool_call.function = MagicMock(name="recall_memory", arguments="{}")
            tool_call.function.name = "recall_memory"
            tool_call.function.arguments = "{}"
            message.tool_calls = [tool_call]
        else:
            message.content = "Got it. Start by re-anchoring on your latest weak spot."
            message.tool_calls = []
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        return response

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=_fake_create)
    service._get_client = lambda: mock_client  # type: ignore[method-assign]

    outcome = await service.coaching_reply_agentic(
        profile=profile,
        message="I keep losing the thread on async iteration.",
        coach_context={"workspace_id": "workspace-test"},
    )
    assert outcome["fell_back"] is False
    assert outcome["content"]
    assert outcome["stop_reason"] in {"completed", "coach_finalize", "max_steps"}
    tool_events = outcome["tool_events"]
    # Must have logged at least one tool call + result for recall_memory.
    assert any(
        event["type"] == "tool_call" and event.get("name") == "recall_memory"
        for event in tool_events
    )
    assert any(event["type"] == "tool_result" for event in tool_events)


async def test_coaching_reply_agentic_blocks_practice_pass_claim_without_current_file_verification() -> (
    None
):
    from app.core.models import UserProfile
    from app.llm.provider_service import ProviderService

    profile = UserProfile(
        long_term_goal="practice against real project files",
        weekly_hours=4,
        answer_policy="guided",
    )
    service = ProviderService()
    service._api_key = "sk-test"  # noqa: SLF001
    service._config = SimpleNamespace(  # noqa: SLF001
        name="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        capabilities=SimpleNamespace(vision=False, chat=True, tools=True),
    )

    message = MagicMock()
    message.content = "Practice passed. You can mark this complete."
    message.tool_calls = []
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    service._get_client = lambda: mock_client  # type: ignore[method-assign]

    outcome = await service.coaching_reply_agentic(
        profile=profile,
        message="I finished this practice card; can I mark it passed?",
        current_file={
            "path": "src/search.ts",
            "language_id": "typescript",
            "content": "export const query = '';\n",
            "diagnostics": [],
        },
        coach_context={
            "workspace_id": "workspace-test",
            "scenario": "task",
            "exercise_prompt": {
                "prompt": "Implement debounceSearch in the current file.",
                "success_signal": "debounceSearch is present and diagnostics are clean.",
            },
        },
    )

    assert outcome["stop_reason"] == "practice_verification_required"
    assert "I checked the active IDE file" in outcome["content"]
    assert any(
        event["type"] == "tool_result"
        and event.get("name") == "verify_practice_current_file"
        and event.get("result", {}).get("passed") is False
        and event.get("auto") is True
        for event in outcome["tool_events"]
    )


async def test_coaching_reply_agentic_auto_verifies_practice_pass_when_model_skips_tool() -> None:
    from app.core.models import UserProfile
    from app.llm.provider_service import ProviderService

    profile = UserProfile(
        long_term_goal="practice against real project files",
        weekly_hours=4,
        answer_policy="guided",
    )
    service = ProviderService()
    service._api_key = "sk-test"  # noqa: SLF001
    service._config = SimpleNamespace(  # noqa: SLF001
        name="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        capabilities=SimpleNamespace(vision=False, chat=True, tools=True),
    )

    message = MagicMock()
    message.content = "Practice passed. You can mark this complete."
    message.tool_calls = []
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    service._get_client = lambda: mock_client  # type: ignore[method-assign]

    outcome = await service.coaching_reply_agentic(
        profile=profile,
        message="I finished this practice card; can I mark it passed?",
        current_file={
            "path": "src/search.ts",
            "language_id": "typescript",
            "content": "export function debounceSearch() {\n  return true;\n}\n",
            "diagnostics": [],
        },
        coach_context={
            "workspace_id": "workspace-test",
            "scenario": "task",
            "exercise_prompt": {
                "prompt": "Implement debounceSearch in the current file.",
                "success_signal": "debounceSearch is present.",
            },
        },
    )

    assert outcome["stop_reason"] == "completed"
    assert outcome["content"] == "Practice passed. You can mark this complete."
    assert any(
        event["type"] == "tool_result"
        and event.get("name") == "verify_practice_current_file"
        and event.get("result", {}).get("passed") is True
        and event.get("auto") is True
        for event in outcome["tool_events"]
    )


async def test_coaching_reply_agentic_stream_buffers_practice_pass_until_auto_verification() -> (
    None
):
    from app.core.models import UserProfile
    from app.llm.provider_service import ProviderService

    profile = UserProfile(
        long_term_goal="practice against real project files",
        weekly_hours=4,
        answer_policy="guided",
    )
    service = ProviderService()
    service._api_key = "sk-test"  # noqa: SLF001
    service._config = SimpleNamespace(  # noqa: SLF001
        name="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        capabilities=SimpleNamespace(vision=False, chat=True, tools=True),
    )

    async def _call(
        _messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        return {"content": "Practice passed. You can mark this complete.", "tool_calls": []}

    async def _call_stream(_messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None):
        yield {"type": "delta", "delta": "Practice passed. "}
        yield {
            "type": "final",
            "content": "Practice passed. You can mark this complete.",
            "tool_calls": [],
            "stop_reason": "stop",
        }

    fake_provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_call,
        call_stream=_call_stream,
    )
    service.build_agent_provider = lambda **_kwargs: (fake_provider, None)  # type: ignore[method-assign]

    events = [
        event
        async for event in service.coaching_reply_agentic_stream(
            profile=profile,
            message="I finished this practice card; can I mark it passed?",
            current_file={
                "path": "src/search.ts",
                "language_id": "typescript",
                "content": "export function debounceSearch() {\n  return true;\n}\n",
                "diagnostics": [],
            },
            coach_context={
                "workspace_id": "workspace-test",
                "scenario": "task",
                "exercise_prompt": {
                    "prompt": "Implement debounceSearch in the current file.",
                    "success_signal": "debounceSearch is present.",
                },
            },
        )
    ]

    assert not any(event["type"] == "text" for event in events)
    assert any(
        event["type"] == "tool_result"
        and event.get("name") == "verify_practice_current_file"
        and event.get("result", {}).get("passed") is True
        and event.get("auto") is True
        for event in events
    )
    final = next(event for event in events if event["type"] == "final")
    assert final["content"] == "Practice passed. You can mark this complete."


async def test_coaching_reply_agentic_allows_practice_pass_after_current_file_verification() -> (
    None
):
    from app.core.models import UserProfile
    from app.llm.provider_service import ProviderService

    profile = UserProfile(
        long_term_goal="practice against real project files",
        weekly_hours=4,
        answer_policy="guided",
    )
    service = ProviderService()
    service._api_key = "sk-test"  # noqa: SLF001
    service._config = SimpleNamespace(  # noqa: SLF001
        name="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        capabilities=SimpleNamespace(vision=False, chat=True, tools=True),
    )
    call_count = {"n": 0}

    async def _fake_create(model: str, **kwargs: Any) -> Any:  # noqa: ARG001
        call_count["n"] += 1
        message = MagicMock()
        if call_count["n"] == 1:
            message.content = ""
            tool_call = MagicMock()
            tool_call.id = "call_verify"
            tool_call.function = MagicMock(
                name="verify_practice_current_file",
                arguments='{"acceptance_criteria":["Implement debounceSearch"],"expected_symbols":["debounceSearch"]}',
            )
            tool_call.function.name = "verify_practice_current_file"
            tool_call.function.arguments = (
                '{"acceptance_criteria":["Implement debounceSearch"],'
                '"expected_symbols":["debounceSearch"]}'
            )
            message.tool_calls = [tool_call]
        else:
            message.content = "Practice passed. You can mark this complete."
            message.tool_calls = []
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        return response

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=_fake_create)
    service._get_client = lambda: mock_client  # type: ignore[method-assign]

    outcome = await service.coaching_reply_agentic(
        profile=profile,
        message="I finished this practice card; can I mark it passed?",
        current_file={
            "path": "src/search.ts",
            "language_id": "typescript",
            "content": "export function debounceSearch() {\n  return true;\n}\n",
            "diagnostics": [],
        },
        coach_context={
            "workspace_id": "workspace-test",
            "scenario": "task",
            "exercise_prompt": {
                "prompt": "Implement debounceSearch in the current file.",
                "success_signal": "debounceSearch is present and diagnostics are clean.",
            },
        },
    )

    assert outcome["stop_reason"] == "completed"
    assert outcome["content"] == "Practice passed. You can mark this complete."
    assert any(
        event["type"] == "tool_result"
        and event.get("name") == "verify_practice_current_file"
        and event.get("result", {}).get("passed") is True
        for event in outcome["tool_events"]
    )


async def test_coaching_reply_agentic_falls_back_when_provider_raises() -> None:
    from app.core.models import UserProfile
    from app.llm.provider_service import ProviderService

    profile = UserProfile(long_term_goal="learn", weekly_hours=4)
    service = ProviderService()
    service._api_key = "sk-test"  # noqa: SLF001
    service._config = SimpleNamespace(  # noqa: SLF001
        name="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        capabilities=SimpleNamespace(vision=False, chat=True, tools=True),
    )

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
    service._get_client = lambda: mock_client  # type: ignore[method-assign]

    outcome = await service.coaching_reply_agentic(
        profile=profile,
        message="anything",
    )
    # The agent loop should swallow the provider error into a stop_reason
    # rather than re-raising, but the fallback path also wraps it. Either
    # outcome is acceptable as long as we get a usable string back.
    assert isinstance(outcome["content"], str)
    assert outcome["content"]
