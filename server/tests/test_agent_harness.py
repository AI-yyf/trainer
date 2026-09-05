"""Pi-inspired harness primitives: compaction, prune cut points, steer, idempotency."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.agent_loop import (
    AgentProvider,
    CoachAgentLoop,
    _shrink_older_tool_history,
    _tool_message,
    run_with_scripted_responses,
)
from app.llm.harness import (
    compact_history,
    drain_steering_messages,
    find_cut_point,
    is_prompt_too_long_error,
    is_truncated_stop,
    lookup_sandbox_operation,
    message_role,
    prepare_next_turn,
    sandbox_operation_key,
    store_sandbox_operation,
    structured_compaction_summary,
    tool_output_limit,
    tools_are_read_only,
)
from app.llm.prompts import build_coaching_system_prompt
from app.llm.tools import ToolContext, ToolDefinition, ToolRegistry


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def _assistant(text: str, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": str(call.get("id") or call.get("name") or ""),
                "type": "function",
                "function": {
                    "name": str(call.get("name") or ""),
                    "arguments": "{}",
                },
            }
            for call in tool_calls
        ]
    return message


def _context(**extra: Any) -> ToolContext:
    return ToolContext(
        runtime=None,
        workspace_id="workspace-harness",
        session_id="session-harness",
        extra=dict(extra),
    )


def test_cut_point_never_lands_on_a_tool_result() -> None:
    history = [
        {"role": "system", "content": "sys"},
        _user("start"),
        _assistant("", [{"id": "c1", "name": "list_sandbox"}]),
        _tool_message("c1", "list_sandbox", {"ok": True, "items": ["a" * 4000]}),
        _user("continue"),
        _assistant("ok"),
    ]
    cut = find_cut_point(history, keep_recent_tokens=50)
    assert message_role(history[cut]) != "tool"
    assert cut >= 1


def test_structured_summary_keeps_goal_and_sandbox_paths() -> None:
    messages = [
        _user("Organize login notes"),
        _assistant("", [{"id": "w1", "name": "write_sandbox_file"}]),
        _tool_message(
            "w1",
            "write_sandbox_file",
            {"ok": True, "path": "notes/login.md", "written": True},
        ),
    ]
    summary = structured_compaction_summary(
        messages,
        extra={"thread_summary": "Map login errors to return codes.", "thread_next_step": "Index the note."},
    )
    assert "## Goal" in summary
    assert "Map login errors to return codes." in summary
    assert "write_sandbox_file" in summary
    assert "notes/login.md" in summary
    assert "## Next Steps" in summary


def test_compact_history_inserts_summary_and_keeps_recent_turn() -> None:
    history = [{"role": "system", "content": "You are Trainer."}]
    for index in range(8):
        history.append(_user(f"turn {index} " + ("q" * 800)))
        history.append(_assistant("a" * 800))
    history.append(_user("latest request"))
    history.append(_assistant("latest reply"))
    record = compact_history(
        history,
        extra={"current_focus": "startup recovery"},
        keep_recent_tokens=200,
        force=True,
    )
    assert record is not None
    assert any(item.get("name") == "compaction" for item in history)
    assert history[-1]["content"] == "latest reply"
    assert history[0]["role"] == "system"
    assert "startup recovery" in str(history[1].get("content") or "")


def test_prepare_next_turn_prunes_old_tool_bodies() -> None:
    history = [
        _tool_message("old", "read_sandbox_file", {"ok": True, "body": "x" * 8_000}),
        _tool_message("mid", "list_sandbox", {"ok": True, "items": ["y" * 8_000]}),
        _tool_message("new", "write_sandbox_file", {"ok": True, "path": "notes.md"}),
        _tool_message("newer", "index_sandbox_file", {"ok": True, "path": "notes.md"}),
    ]
    prepare_next_turn(history, extra={"context_window_tokens": 8_000}, history_char_budget=12_000)
    assert "notes.md" in str(history[-1]["content"])
    assert len(str(history[0]["content"])) <= 2_400 + 40 or "pruned" in str(history[0]["content"])


def test_read_tool_output_limit_is_larger_than_default_write_cap() -> None:
    assert tool_output_limit("read_sandbox_file") >= 100_000
    assert tool_output_limit("write_sandbox_file") < tool_output_limit("read_sandbox_file")
    huge = {"ok": True, "body": "n" * 140_000}
    message = _tool_message("call-1", "read_sandbox_file", huge)
    assert len(str(message["content"])) <= tool_output_limit("read_sandbox_file") + 20
    assert "truncated" in str(message["content"])


def test_truncated_stop_and_prompt_too_long_detection() -> None:
    assert is_truncated_stop("length") is True
    assert is_truncated_stop("max_tokens") is True
    assert is_truncated_stop("stop") is False
    assert is_prompt_too_long_error(RuntimeError("This model's maximum context length was exceeded"))
    assert is_prompt_too_long_error(ValueError("not this")) is False


def test_read_only_batch_is_parallel_safe() -> None:
    assert tools_are_read_only(
        [{"name": "list_sandbox"}, {"name": "search_resources"}]
    )
    assert not tools_are_read_only(
        [{"name": "list_sandbox"}, {"name": "write_sandbox_file"}]
    )


def test_sandbox_operation_log_replays_identical_write() -> None:
    runtime = SimpleNamespace(sandbox_operation_log={}, event_ledger=None)
    arguments = {"path": "notes.md", "content": "hello"}
    key = sandbox_operation_key("workspace-a", "write_sandbox_file", arguments)
    store_sandbox_operation(runtime, key, {"ok": True, "path": "notes.md", "written": True})
    cached = lookup_sandbox_operation(runtime, key)
    assert cached is not None
    assert cached["written"] is True
    other = sandbox_operation_key("workspace-a", "write_sandbox_file", {"path": "notes.md", "content": "other"})
    assert lookup_sandbox_operation(runtime, other) is None


@pytest.mark.asyncio
async def test_truncated_tool_calls_are_not_executed() -> None:
    registry = ToolRegistry()
    calls: list[str] = []

    async def _echo(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        calls.append("echo")
        return {"ok": True, "echoed": args.get("text")}

    registry.register(
        ToolDefinition(
            name="echo",
            description="echo",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            handler=_echo,
        )
    )

    steps = {"n": 0}

    async def _call(_messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        steps["n"] += 1
        if steps["n"] == 1:
            return {
                "content": "",
                "stop_reason": "length",
                "tool_calls": [{"id": "c0", "name": "echo", "arguments": {"text": "partial"}}],
            }
        return {"content": "Re-issued with complete arguments.", "tool_calls": []}

    loop = CoachAgentLoop(
        provider=AgentProvider(protocol="openai_chat_completions", call=_call),
        registry=registry,
        context=_context(),
        max_steps=4,
    )
    result = await loop.run([_user("go")])
    assert calls == []
    assert result.stop_reason == "completed"
    assert "complete arguments" in result.final_content


@pytest.mark.asyncio
async def test_steering_message_is_injected_before_next_llm_call() -> None:
    seen: list[str] = []

    async def _echo(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "echoed": args.get("text")}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="echo",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            handler=_echo,
        )
    )
    context = _context(steering_messages=["Do not delete login.md"])

    async def _call(messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        seen.append(str(messages[-1].get("content") or ""))
        if len(seen) == 1:
            return {
                "content": "",
                "tool_calls": [{"id": "c0", "name": "echo", "arguments": {"text": "x"}}],
            }
        return {"content": "Kept login.md.", "tool_calls": []}

    loop = CoachAgentLoop(
        provider=AgentProvider(protocol="openai_chat_completions", call=_call),
        registry=registry,
        context=context,
        max_steps=4,
    )
    result = await loop.run([_user("organize notes")])
    assert result.stop_reason == "completed"
    assert any("Do not delete login.md" in item for item in seen)
    assert drain_steering_messages(context) == []


@pytest.mark.asyncio
async def test_overflow_compacts_and_retries_same_step() -> None:
    calls = 0

    async def _call(messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("This model's maximum context length was exceeded")
        compacted = any(item.get("name") == "compaction" for item in messages)
        assert compacted or any("compacted" in str(item.get("content") or "").lower() for item in messages)
        return {"content": "Recovered after compaction.", "tool_calls": []}

    history = [{"role": "system", "content": "sys"}]
    for index in range(6):
        history.append(_user(f"old {index} " + ("m" * 400)))
        history.append(_assistant("n" * 400))
    history.append(_user("now"))

    loop = CoachAgentLoop(
        provider=AgentProvider(protocol="openai_chat_completions", call=_call),
        registry=ToolRegistry(),
        context=_context(),
        max_steps=3,
    )
    result = await loop.run(history)
    assert calls == 2
    assert result.stop_reason == "completed"
    assert "Recovered after compaction." in result.final_content


def test_core_prompt_stays_until_done_and_library_skill_is_gated() -> None:
    from app.core.models import UserProfile

    profile = UserProfile(
        long_term_goal="Learn FastAPI",
        background="Python",
        weekly_hours=6,
        teaching_style="guided",
        answer_policy="guided",
    )
    core = build_coaching_system_prompt(profile, agent_loop_enabled=True)
    assert "continue until the library or coaching question is settled" in core
    assert "coach_finalize" in core
    assert "If the same evidence keeps coming back" in core
    assert "list_sandbox" not in core
    library = build_coaching_system_prompt(
        profile,
        agent_loop_enabled=True,
        coach_context={"active_view": "resources", "library_sandbox_work": True},
    )
    assert "list_sandbox" in library
    assert "write_sandbox_file" in library


@pytest.mark.asyncio
async def test_scripted_echo_loop_still_completes() -> None:
    registry = ToolRegistry()

    async def _echo(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "echoed": args.get("text")}

    registry.register(
        ToolDefinition(
            name="echo",
            description="echo",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            handler=_echo,
        )
    )
    result = await run_with_scripted_responses(
        registry=registry,
        context=_context(),
        scripted_responses=[
            {
                "content": "",
                "tool_calls": [{"id": "c0", "name": "echo", "arguments": {"text": "ping"}}],
            },
            {"content": "pong", "tool_calls": []},
        ],
        initial_messages=[_user("echo ping")],
        max_steps=4,
    )
    assert result.stop_reason == "completed"
    assert result.final_content == "pong"


def test_shrink_helper_still_delegates_to_harness_prune() -> None:
    history = [
        _tool_message("call-old-1", "list_sandbox", {"ok": True, "items": ["a" * 5_000]}),
        _tool_message("call-old-2", "read_sandbox_file", {"ok": True, "content": "b" * 5_000}),
        _tool_message("call-old-3", "read_sandbox_file", {"ok": True, "content": "c" * 5_000}),
        _tool_message("call-new", "write_sandbox_file", {"ok": True, "path": "notes.md"}),
    ]
    _shrink_older_tool_history(history)
    assert len(str(history[0]["content"])) <= CoachAgentLoop.MAX_KEPT_TOOL_RESULT_CHARS + 20
    assert "notes.md" in str(history[3]["content"])
