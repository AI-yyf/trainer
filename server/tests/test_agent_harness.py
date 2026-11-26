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
from app.llm.tools import ToolContext, ToolDefinition, ToolRegistry, build_default_tool_registry


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


@pytest.mark.asyncio
async def test_one_million_token_compaction_preserves_research_evidence_ledger() -> None:
    research_state = {
        "status": "gaps_remain",
        "search_count": 11,
        "required_facets": ["context compression", "continuation after restart"],
        "covered_facets": ["context compression"],
        "evidence_standard": {
            "risk_level": "high_stakes",
            "minimum_independent_sources": 3,
            "requires_authoritative_source": True,
            "claim_types": ["factual", "procedural"],
            "freshness_requirement": "current",
            "applicability_scope": "Trainer long-horizon research and restart continuity.",
            "stopping_rule": "Stop only after all audit dimensions survive compaction and resume.",
            "unresolved_uncertainties": ["restart continuity still lacks evidence"],
            "quality_checks": [
                {
                    "dimension": dimension,
                    "status": "unresolved" if dimension == "coverage" else "satisfied",
                    "source_ids": ["official-context"],
                    "rationale": f"The checkpoint records the {dimension} audit result.",
                }
                for dimension in (
                    "coverage",
                    "source_quality",
                    "recency",
                    "contradictions",
                    "applicability",
                )
            ],
        },
        "sources": [
            {
                "id": "official-context",
                "title": "Official context guide",
                "url": "https://docs.example.test/context",
                "fetched_at": "2026-09-19T00:00:00+00:00",
            }
        ],
        "assessment": [
            {
                "facet": "context compression",
                "status": "covered",
                "source_ids": ["official-context"],
                "evidence_quotes": [
                    {
                        "source_id": "official-context",
                        "quote": "Preserve a compact evidence checkpoint",
                    }
                ],
                "rationale": "The source directly specifies a loss-resistant checkpoint.",
            },
            {
                "facet": "continuation after restart",
                "status": "missing",
                "source_ids": [],
                "evidence_quotes": [],
                "rationale": "No fetched source yet establishes restart continuation.",
            },
        ],
    }
    extra = {
        "context_window_tokens": 1_048_576,
        "current_focus": "Build a source-grounded long-horizon learning plan.",
        "formal_plan_mutation": True,
        "_learning_material_research_state": research_state,
    }
    # CJK characters are conservatively estimated as one token each. This crosses the
    # configured 1M threshold without relying on a mocked smaller context window.
    history = [{"role": "system", "content": "You are Trainer."}]
    for index in range(10):
        history.append(_user(f"research segment {index} " + ("证" * 105_000)))
        history.append(_assistant(f"checkpoint {index}"))
    history.extend([_user("Continue with the missing restart facet."), _assistant("Continuing.")])

    record = compact_history(history, extra=extra)

    assert record is not None
    assert record.tokens_before > 1_048_576 - 16_384
    assert record.tokens_after < record.tokens_before
    assert "## Research Evidence Ledger" in record.summary
    assert "Search rounds completed: 11" in record.summary
    assert "official-context" in record.summary
    assert "Preserve a compact evidence checkpoint" in record.summary
    assert "Open evidence gaps: continuation after restart" in record.summary
    assert "### Adaptive Evidence Standard" in record.summary
    assert "Quality contradictions" in record.summary
    assert extra["_learning_material_research_state"] is research_state
    assert extra["_last_context_compaction"]["research_state_preserved"] is True
    assert extra["_last_context_compaction"]["tokens_before"] == record.tokens_before

    class _ResearchService:
        def search_web(self, query: str, **_kwargs: Any) -> dict[str, Any]:
            return {
                "query": query,
                "results": [
                    {
                        "id": "official-restart",
                        "title": "Official restart guide",
                        "url": "https://docs.example.test/restart",
                        "source": "docs.example.test",
                        "snippet": "Continuation after restart restores the research checkpoint.",
                        "evidence_excerpt": (
                            "Continuation after restart restores the research checkpoint."
                        ),
                        "fetched_at": "2026-09-19T00:00:01+00:00",
                        "trust_score": 0.9,
                    }
                ],
            }

    context = ToolContext(
        runtime=SimpleNamespace(research_service=_ResearchService()),
        workspace_id="workspace-harness",
        session_id="session-harness",
        extra=extra,
    )
    continued = await build_default_tool_registry().invoke(
        context,
        "web_fetch",
        {
            "action": "learning_materials",
            "query": "site:docs.example.test continuation after restart",
            "required_facets": research_state["required_facets"],
            "preferred_domains": ["docs.example.test"],
        },
    )

    assert continued["ok"] is True
    assert continued["evidence_coverage"]["search_count"] == 12
    assert continued["source_count"] == 2
    assert {source["id"] for source in continued["sources"]} == {
        "official-context",
        "official-restart",
    }
    continued_state = context.extra["_learning_material_research_state"]
    assert continued_state["evidence_standard"]["risk_level"] == "high_stakes"
    assert len(continued_state["evidence_standard"]["quality_checks"]) == 5


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
    assert "project_read" in core
    assert "library_write" in core
    assert "coach_finalize" not in core
    assert "## Library Domain" not in core
    library = build_coaching_system_prompt(
        profile,
        agent_loop_enabled=True,
        coach_context={"active_view": "resources", "library_sandbox_work": True},
    )
    assert "## Library Domain" in library
    assert "library_exec" in library


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


def test_sandbox_operation_log_enforces_lru_bound_and_path_invalidation() -> None:
    from types import SimpleNamespace

    from app.llm.harness import (
        invalidate_sandbox_operations,
        lookup_sandbox_operation,
        sandbox_operation_key,
        store_sandbox_operation,
    )

    runtime = SimpleNamespace(sandbox_operation_log={})
    k1 = sandbox_operation_key("ws1", "library_write", {"action": "write", "path": "a.md", "content": "1"})
    k2 = sandbox_operation_key("ws1", "library_write", {"action": "write", "path": "b.md", "content": "2"})
    k3 = sandbox_operation_key("ws1", "library_write", {"action": "write", "path": "c.md", "content": "3"})
    assert k1 and k2 and k3

    store_sandbox_operation(runtime, k1, {"ok": True, "path": "a.md"}, limit=2)
    store_sandbox_operation(runtime, k2, {"ok": True, "path": "b.md"}, limit=2)
    # Touch k1 so k2 becomes the LRU victim when k3 arrives.
    assert lookup_sandbox_operation(runtime, k1, limit=2) is not None
    store_sandbox_operation(runtime, k3, {"ok": True, "path": "c.md"}, limit=2)
    assert lookup_sandbox_operation(runtime, k1, limit=2) is not None
    assert lookup_sandbox_operation(runtime, k2, limit=2) is None
    assert lookup_sandbox_operation(runtime, k3, limit=2) is not None

    # Writing a new version of a.md evicts the older key for a.md immediately.
    k1_v2 = sandbox_operation_key("ws1", "library_write", {"action": "write", "path": "a.md", "content": "2"})
    store_sandbox_operation(runtime, k1_v2, {"ok": True, "path": "a.md"}, limit=4)
    assert lookup_sandbox_operation(runtime, k1, limit=4) is None
    assert lookup_sandbox_operation(runtime, k1_v2, limit=4) is not None

    evicted = invalidate_sandbox_operations(runtime, "ws1", paths=["./a.md"])
    assert evicted == 1
    assert lookup_sandbox_operation(runtime, k1_v2, limit=4) is None


@pytest.mark.asyncio
async def test_singleflight_completed_requests_enforce_true_lru_touch_on_hit() -> None:
    from threading import Lock

    from app.api._singleflight import (
        claim_session_request_singleflight,
        get_completed_request,
        publish_session_request_singleflight,
        remember_completed_request,
    )

    completed: dict[tuple[str, str, str], dict[str, object]] = {}
    inflight: dict[tuple[str, str, str], Any] = {}
    guard = Lock()

    key_a = ("ws", "turn", "req-a")
    key_b = ("ws", "turn", "req-b")
    key_c = ("ws", "turn", "req-c")

    remember_completed_request(completed, key_a, {"id": "a"}, guard=guard, limit=2)
    remember_completed_request(completed, key_b, {"id": "b"}, guard=guard, limit=2)

    # Touch key_a via claim_session_request_singleflight so key_b becomes coldest.
    mode, cached_a, fut = claim_session_request_singleflight(
        key_a, completed=completed, inflight=inflight, guard=guard, limit=2
    )
    assert mode == "cached"
    assert cached_a == {"id": "a"}
    assert fut is None

    # Publishing key_c with limit=2 must evict cold key_b while retaining hot key_a.
    mode_c, _, fut_c = claim_session_request_singleflight(
        key_c, completed=completed, inflight=inflight, guard=guard, limit=2
    )
    assert mode_c == "owner"
    assert fut_c is not None
    publish_session_request_singleflight(
        key_c, {"id": "c"}, completed=completed, inflight=inflight, guard=guard, limit=2
    )
    assert fut_c.done() and fut_c.result() == {"id": "c"}
    assert list(completed.keys()) == [key_a, key_c]
    assert get_completed_request(completed, key_b, guard=guard, limit=2) is None
    assert get_completed_request(completed, key_a, guard=guard, limit=2) == {"id": "a"}
    # Touching key_a again moves it after key_c.
    assert list(completed.keys()) == [key_c, key_a]


def test_static_coaching_prefix_stays_byte_identical_across_diverse_turns_and_skill_append() -> None:
    from app.core.models import UserProfile
    from app.llm.prompts import build_coaching_messages, build_static_coaching_prefix

    profile = UserProfile(
        long_term_goal="Master distributed systems",
        background="Python backend developer",
        weekly_hours=8,
    )
    static_prefix = build_static_coaching_prefix(
        profile,
        "zh-CN",
        "auto",
        agent_loop_enabled=True,
    )
    turn1 = build_coaching_messages(
        profile,
        "解释一下 app.py 里的异步锁边界",
        current_file={"path": "app.py", "language_id": "python", "content": "async def run(): pass"},
        response_language="zh-CN",
        answer_mode="auto",
        coach_context={"active_view": "coach"},
        agent_loop_enabled=True,
    )
    turn2 = build_coaching_messages(
        profile,
        "帮我检索资料库里的 Raft 笔记并整理",
        current_file=None,
        response_language="zh-CN",
        answer_mode="auto",
        coach_context={"active_view": "resources", "library_sandbox_work": True},
        agent_loop_enabled=True,
    )
    # Appending skill guidance at the tail of messages[0] keeps byte-0 prefix intact.
    skill_guidance = "## Active Skill Guidance\nFollow Socratic micro-steps."
    turn2_with_skill = [
        {**turn2[0], "content": f"{turn2[0]['content']}\n\n{skill_guidance}"},
        *turn2[1:],
    ]
    assert len(static_prefix) > 3000
    assert turn1[0]["role"] == "system"
    assert turn2_with_skill[0]["role"] == "system"
    assert turn1[0]["content"].startswith(static_prefix)
    assert turn2[0]["content"].startswith(static_prefix)
    assert turn2_with_skill[0]["content"].startswith(static_prefix)
    assert skill_guidance in turn2_with_skill[0]["content"]


@pytest.mark.asyncio
async def test_dual_channel_tool_output_separates_llm_content_from_ui_details() -> None:
    registry = ToolRegistry()
    seen_messages: list[list[dict[str, Any]]] = []

    async def _verbose_write(_ctx: ToolContext, _args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "action": "write",
            "path": "notes/raft.md",
            "content": "# Huge echoed body\n" + ("x" * 2_000),
            "auto_indexed": True,
            "library": {"ok": True, "resource_id": "res-dup", "chunks": 12},
            "undo_operations": [{"op": "delete", "path": "notes/raft.md"}],
            "audit_recorded": True,
            "idempotent_key": "ws:library_write:abc",
        }

    registry.register(
        ToolDefinition(
            name="library_write",
            description="Write library note",
            parameters={"type": "object", "properties": {}},
            handler=_verbose_write,
        )
    )

    responses = [
        {
            "content": "",
            "tool_calls": [{"id": "cw-1", "name": "library_write", "arguments": {"action": "write"}}],
        },
        {"content": "Saved cleanly.", "tool_calls": []},
    ]

    async def _call(messages: list[dict[str, Any]], _tools: list[dict[str, Any]]) -> dict[str, Any]:
        seen_messages.append([dict(m) for m in messages])
        return responses[len(seen_messages) - 1]

    loop = CoachAgentLoop(
        provider=AgentProvider(protocol="openai_chat_completions", call=_call),
        registry=registry,
        context=_context(),
        max_steps=4,
    )
    result = await loop.run([_user("save note")])
    assert result.stop_reason == "completed"
    # UI/host details channel keeps full structured fields intact:
    ui_payload = result.steps[0].tool_results[0]["result"]
    assert ui_payload["undo_operations"] == [{"op": "delete", "path": "notes/raft.md"}]
    assert ui_payload["audit_recorded"] is True
    assert "Huge echoed body" in ui_payload["content"]

    # LLM tool channel strips UI plumbing & echoed write body, replacing with content_chars:
    tool_msgs = [m for m in seen_messages[1] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    llm_tool_text = str(tool_msgs[0]["content"])
    assert "notes/raft.md" in llm_tool_text
    assert "content_chars" in llm_tool_text
    assert "Huge echoed body" not in llm_tool_text
    assert "undo_operations" not in llm_tool_text
    assert "idempotent_key" not in llm_tool_text


def test_build_coaching_messages_preserves_atomic_tool_call_pairs_and_drops_orphans() -> None:
    from app.core.models import UserProfile
    from app.llm.prompts import build_coaching_messages

    profile = UserProfile()
    history: list[dict[str, Any]] = [
        {"role": "tool", "tool_call_id": "orphan-0", "name": "project_read", "content": "should drop"},
        {"role": "user", "content": "看看 app.py 里写了什么"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-read-1",
                    "type": "function",
                    "function": {"name": "project_read", "arguments": '{"action":"read","path":"app.py"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-read-1",
            "name": "project_read",
            "content": '{"ok":true,"path":"app.py","content":"def greet(): return 42"}',
        },
        {"role": "assistant", "content": "app.py 定义了 greet() 返回 42。"},
    ]
    built = build_coaching_messages(profile, "那如果改成返回字符串呢？", history=history)
    roles = [m["role"] for m in built]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "user"]
    assert all("orphan-0" not in str(m.get("tool_call_id") or "") for m in built)
    assert "def greet(): return 42" in built[3]["content"]


@pytest.mark.asyncio
async def test_library_exec_blocks_all_obfuscated_p0_4_bypasses_and_honors_cancel_event(
    tmp_path,
) -> None:
    import asyncio
    import base64
    import time

    from app.core.config import Settings
    from app.llm.tools import build_default_tool_registry
    from app.main import create_app

    proj = tmp_path / "proj"
    proj.mkdir()
    readme = proj / "README.md"
    readme.write_text("READ_ONLY_PROJECT", encoding="utf-8")

    app = create_app(Settings(data_dir=tmp_path / "data"))
    rt = app.state.runtime
    rt.register_workspace_path("ws-sec", str(proj))
    ctx = ToolContext(
        runtime=rt,
        workspace_id="ws-sec",
        session_id="sess-sec",
        extra={"library_sandbox_work": True},
    )
    reg = build_default_tool_registry()

    b64_write = base64.b64encode(f"open('{readme}', 'w').write('PWN')".encode()).decode()
    exploits = [
        'python3 -c "import os;os.chdir(chr(47));print(os.listdir())"',
        f'python3 -c "import base64;exec(base64.b64decode(\'{b64_write}\'))"',
        "echo L1VzZXJz | base64 -d | xargs ls",
        f'python3 -c "import pathlib;[q.write_text(\'\') for q in pathlib.Path(\'{proj.parent}\').glob(\'*/README.md\')]"',
        f'python3 -c "import os;fd=os.open(\'{readme}\', os.O_WRONLY);os.write(fd, b\'X\')"',
    ]
    for cmd in exploits:
        res = await reg.invoke(ctx, "library_exec", {"command": cmd})
        assert res["ok"] is False, f"Obfuscated exploit should fail closed: {cmd}"
    assert readme.read_text(encoding="utf-8") == "READ_ONLY_PROJECT"

    # Verify cancel_event kills process group promptly instead of waiting 15s timeout:
    cancel_ev = asyncio.Event()
    ctx.extra["_stream_cancel_event"] = cancel_ev

    async def _trigger_cancel() -> None:
        await asyncio.sleep(0.15)
        cancel_ev.set()

    t0 = time.monotonic()
    cancel_task = asyncio.create_task(_trigger_cancel())
    with pytest.raises(asyncio.CancelledError):
        await reg.invoke(
            ctx,
            "library_exec",
            {"command": "python3 -c \"import time; time.sleep(20)\"", "timeout_seconds": 20},
        )
    await cancel_task
    assert (time.monotonic() - t0) < 3.0


@pytest.mark.asyncio
async def test_provider_usage_compaction_math_inf_overflow_and_mid_batch_steering() -> None:
    import math

    from app.llm.harness import extract_provider_usage, truncate_tool_payload

    # 1. Gemini usageMetadata + Head+Tail truncation check
    gem_usage = extract_provider_usage(
        {
            "usageMetadata": {
                "promptTokenCount": 4200,
                "candidatesTokenCount": 300,
                "cachedContentTokenCount": 3800,
                "totalTokenCount": 4500,
            }
        }
    )
    assert gem_usage is not None
    assert gem_usage.estimated_input_tokens == 4200
    assert gem_usage.cache_read_tokens == 3800

    long_err = ("HEAD_LINE\n" * 80) + ("MIDDLE_NOISE\n" * 400) + "Traceback:\nZeroDivisionError: boom"
    truncated = truncate_tool_payload(long_err, limit=1200)
    assert "HEAD_LINE" in truncated
    assert "ZeroDivisionError: boom" in truncated
    assert "…[truncated]" in truncated

    # 2. Mid-batch steering + math.inf overflow retry check
    executed: list[str] = []
    ctx = _context(extra={"context_window_tokens": 4_096, "reserve_tokens": 1_024})
    reg = ToolRegistry()

    async def _mut_tool(c: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        step_id = str(args.get("step"))
        executed.append(step_id)
        if step_id == "1":
            c.extra["steering_messages"] = ["停一下，改看另一个文件"]
        return {"ok": True, "step": step_id}

    reg.register(
        ToolDefinition(
            name="library_write",
            description="Mutate",
            parameters={"type": "object", "properties": {}},
            handler=_mut_tool,
        )
    )

    call_idx = 0

    async def _provider_call(messages: list[dict[str, Any]], _tools: list[dict[str, Any]]) -> dict[str, Any]:
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            raise RuntimeError("prompt is too long: maximum context length exceeded")
        if call_idx == 2:
            return {
                "content": "",
                "usage": {"input_tokens": 3500, "output_tokens": 50, "total_tokens": 3550},
                "tool_calls": [
                    {"id": "t1", "name": "library_write", "arguments": {"step": "1"}},
                    {"id": "t2", "name": "library_write", "arguments": {"step": "2"}},
                    {"id": "t3", "name": "library_write", "arguments": {"step": "3"}},
                ],
            }
        # Confirm t2 and t3 were skipped with 1:1 paired tool messages and steering arrived:
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert [m["tool_call_id"] for m in tool_msgs] == ["t1", "t2", "t3"]
        assert "skipped" in tool_msgs[1]["content"]
        assert any("停一下，改看另一个文件" in str(m.get("content") or "") for m in messages if m.get("role") == "user")
        return {"content": "已按你的新指令切换。", "tool_calls": []}

    loop = CoachAgentLoop(
        provider=AgentProvider(protocol="openai_chat_completions", call=_provider_call),
        registry=reg,
        context=ctx,
        step_timeout=math.inf,
        first_step_timeout=math.inf,
    )
    res = await loop.run([_user("start"), _assistant("ok"), _user("more"), _assistant("ok2"), _user("go")])
    assert res.stop_reason == "completed"
    assert executed == ["1"]
    assert ctx.extra["_last_provider_usage"]["input_tokens"] == 3500


@pytest.mark.asyncio
async def test_schedule_background_tail_runs_sync_fn_off_event_loop_thread() -> None:
    import threading

    from app.api.routes.core import _schedule_background_tail, drain_background_tail_tasks

    main_tid = threading.get_ident()
    seen_tids: list[int] = []

    def _sync_sqlite_work(val: int) -> None:
        seen_tids.append(threading.get_ident() + val * 0)

    _schedule_background_tail(_sync_sqlite_work, 1)
    await drain_background_tail_tasks(timeout=2.0)
    assert len(seen_tids) == 1
    assert seen_tids[0] != main_tid


@pytest.mark.asyncio
async def test_four_protocol_streaming_usage_feeds_agent_loop() -> None:
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.llm.agent_binding import ProviderAgentBinding

    class _AsyncList:
        def __init__(self, items: list[Any]) -> None:
            self._items = items

        def __aiter__(self):
            async def _gen():
                for item in self._items:
                    yield item

            return _gen()

    # 1) OpenAI Chat Completions stream with trailing choices=[] usage chunk
    chat_svc = MagicMock()
    chat_svc._config = SimpleNamespace(
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        protocol="openai_chat_completions",
        capabilities=SimpleNamespace(vision=False),
        request_defaults={},
    )
    chat_svc._api_key = "sk-test"
    chat_svc._resolve_model.return_value = "gpt-4o-mini"
    chat_svc._model_candidates.return_value = ["gpt-4o-mini"]
    chat_svc._apply_request_defaults.side_effect = lambda d: d
    chat_svc._create_chat_completion_negotiated_async = AsyncMock(
        return_value=_AsyncList([
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="  Streamed ok.", tool_calls=None), finish_reason=None)],
                usage=None,
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=None), finish_reason="stop")],
                usage=None,
            ),
            SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=140,
                    completion_tokens=19,
                    total_tokens=159,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=80),
                    completion_tokens_details=SimpleNamespace(reasoning_tokens=5),
                ),
            ),
        ])
    )
    chat_provider = ProviderAgentBinding(
        provider_service=chat_svc, protocol="openai_chat_completions"
    ).build_agent_provider()
    ctx = ToolContext(runtime=SimpleNamespace(), workspace_id="ws-u", extra={})
    loop = CoachAgentLoop(provider=chat_provider, registry=ToolRegistry(), context=ctx)
    loop_events = [ev async for ev in loop.run_stream([_user("hello")])]
    assert any(ev.get("type") == "text" and ev.get("delta") == "Streamed ok." for ev in loop_events)
    assert ctx.extra["_last_provider_usage"]["input_tokens"] == 140
    assert ctx.extra["_last_provider_usage"]["cache_read_tokens"] == 80
    assert ctx.extra["_last_provider_usage"]["output_tokens"] == 19
    assert ctx.extra["_last_provider_usage"]["reasoning_tokens"] == 5

    # 2) Anthropic Messages stream (message_start + message_delta usage merge)
    class _FakeSSEResp:
        def __init__(self, lines: list[str]) -> None:
            self.status_code = 200
            self._lines = lines

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a: Any):
            return False

        async def aiter_lines(self):
            for ln in self._lines:
                yield ln

    class _FakeHTTP:
        def __init__(self, lines: list[str]) -> None:
            self._lines = lines

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a: Any):
            return False

        def stream(self, *_a: Any, **_kw: Any):
            return _FakeSSEResp(self._lines)

    anth_svc = MagicMock()
    anth_svc._config = SimpleNamespace(
        base_url="https://api.anthropic.com",
        model="claude-sonnet-4-20250514",
        protocol="anthropic_messages",
        capabilities=SimpleNamespace(vision=False),
        request_defaults={},
    )
    anth_svc._api_key = "sk-ant"
    anth_binding = ProviderAgentBinding(provider_service=anth_svc, protocol="anthropic_messages")
    anth_lines = [
        "data: " + json.dumps({
            "type": "message_start",
            "message": {"usage": {"input_tokens": 60, "cache_read_input_tokens": 30, "cache_creation_input_tokens": 10, "output_tokens": 1}},
        }),
        "data: " + json.dumps({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Claude ok."}}),
        "data: " + json.dumps({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 25}}),
        "data: " + json.dumps({"type": "message_stop"}),
    ]
    with patch.object(anth_binding, "_async_http_client", return_value=_FakeHTTP(anth_lines)):
        anth_events = [ev async for ev in anth_binding.build_agent_provider().call_stream([_user("hi")], None)]
    assert anth_events[-1]["usage"]["input_tokens"] == 100
    assert anth_events[-1]["usage"]["output_tokens"] == 25
    assert anth_events[-1]["usage"]["cache_read_tokens"] == 30
    assert anth_events[-1]["usage"]["cache_write_tokens"] == 10

    # 3) Gemini GenerateContent stream usageMetadata
    gem_svc = MagicMock()
    gem_svc._config = SimpleNamespace(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-2.5-flash",
        protocol="gemini_generate_content",
        capabilities=SimpleNamespace(vision=False),
        request_defaults={},
    )
    gem_svc._api_key = "gem-key"
    gem_binding = ProviderAgentBinding(provider_service=gem_svc, protocol="gemini_generate_content")
    gem_lines = [
        "data: " + json.dumps({
            "candidates": [{"content": {"parts": [{"text": "Gemini ok."}]}, "finishReason": "STOP"}],
            "usageMetadata": {
                "promptTokenCount": 180,
                "candidatesTokenCount": 16,
                "thoughtsTokenCount": 7,
                "cachedContentTokenCount": 90,
                "totalTokenCount": 203,
            },
        }),
    ]
    with patch.object(gem_binding, "_async_http_client", return_value=_FakeHTTP(gem_lines)):
        gem_events = [ev async for ev in gem_binding.build_agent_provider().call_stream([_user("hi")], None)]
    assert gem_events[-1]["usage"]["input_tokens"] == 180
    assert gem_events[-1]["usage"]["output_tokens"] == 16
    assert gem_events[-1]["usage"]["reasoning_tokens"] == 7
    assert gem_events[-1]["usage"]["cache_read_tokens"] == 90


def test_bounded_session_dict_evicts_cold_and_protects_locked() -> None:
    from app.api.runtime import BoundedSessionDict, SessionState
    from app.core.models import WorkbenchSnapshot

    evicted: list[str] = []
    locked_ids = {"s-1"}

    store = BoundedSessionDict(
        max_entries=4,
        on_evict=lambda st: evicted.append(st.session_id),
        is_locked=lambda sid: sid in locked_ids,
    )
    for idx in range(6):
        sid = f"s-{idx}"
        store[sid] = SessionState(
            session_id=sid,
            workspace_id="ws",
            workspace_name="WS",
            snapshot=WorkbenchSnapshot(contextId="ws"),
        )
        if sid == "s-2":
            _ = store.get("s-0")  # touch s-0 so s-2 becomes older than s-0!

    # s-1 is locked so never evicted; s-0 was touched after s-2 so s-2 and s-0/s-3 get evicted in LRU order
    assert len(store) == 4
    assert "s-1" in dict.keys(store)
    assert "s-2" in evicted


def test_thinking_learned_state_thread_safe_lru_bound() -> None:
    from types import SimpleNamespace

    from app.llm.provider.thinking import (
        _LEARNED_CACHE_LIMIT,
        learned_param_repairs,
        learned_policy,
        remember_param_repairs,
        remember_policy,
        reset_learned_policies,
    )

    reset_learned_policies()
    try:
        for i in range(_LEARNED_CACHE_LIMIT + 10):
            p = SimpleNamespace(base_url="https://gw.example.com", model=f"m-{i}", protocol="openai")
            remember_policy(p, "enabled")
            remember_param_repairs(p, ("temperature",))
            if i == 5:
                # Touch m-0 so it stays hot
                p0 = SimpleNamespace(base_url="https://gw.example.com", model="m-0", protocol="openai")
                assert learned_policy(p0) == "enabled"
        oldest_untouched = SimpleNamespace(base_url="https://gw.example.com", model="m-1", protocol="openai")
        newest = SimpleNamespace(
            base_url="https://gw.example.com",
            model=f"m-{_LEARNED_CACHE_LIMIT + 9}",
            protocol="openai",
        )
        assert learned_policy(oldest_untouched) is None
        assert learned_param_repairs(oldest_untouched) == ()
        assert learned_policy(newest) == "enabled"
        assert learned_param_repairs(newest) == ("temperature",)
    finally:
        reset_learned_policies()


def test_dead_legacy_tool_handlers_retired_from_tools_module() -> None:
    import app.llm.tools as tools_mod

    assert not hasattr(tools_mod, "_handle_generate_training_card")
    assert not hasattr(tools_mod, "_handle_coach_finalize")


def test_general_coach_followup_retains_history_and_prior_tool_trace() -> None:
    from app.core.models import UserProfile
    from app.llm.prompts import build_coaching_messages

    profile = UserProfile(long_term_goal="Master distributed systems")
    history = [
        {"role": "user", "content": "帮我看看项目里的 README.md 入口"},
        {
            "role": "assistant",
            "content": "我已经读取了 README.md。\n[Prior turn tool trace: project_read(read):README.md[ok]]",
        },
    ]
    built = build_coaching_messages(
        profile,
        "确认一下刚才读了哪个文件？",
        response_language="zh-CN",
        coach_context={
            "scenario": "general",
            "history_mode": "fresh_lane",
            "active_view": "coach",
        },
        history=history,
    )
    assert any(
        "[Prior turn tool trace: project_read(read):README.md[ok]]" in str(m.get("content") or "")
        for m in built
    )





