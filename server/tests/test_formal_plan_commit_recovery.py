from typing import Any

import pytest

from app.llm.agent_loop import AgentProvider, CoachAgentLoop
from app.llm.tools import ToolContext, ToolDefinition, ToolRegistry


def tool_call(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": name, "name": name, "arguments": arguments or {}}


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("premature_tool", [False, True])
async def test_authorized_save_repairs_premature_final_once(streaming, premature_tool):
    result, calls, commits = await run_script(
        [
            {"content": "Here is the corrected draft.", "tool_calls":
             [tool_call("coach_finalize")] if premature_tool else []},
            {"tool_calls": [tool_call("save_formal_plan", {"plan_id": "same-plan"})]},
            {"tool_calls": [tool_call("coach_finalize")]},
        ], streaming=streaming,
    )
    assert len(calls) == 3
    assert commits == [{"plan_id": "same-plan"}]
    correction = calls[1][-1]
    assert correction["role"] == "system"
    assert "latest learner request" in correction["content"]
    assert result["stop_reason"] == "coach_finalize"


@pytest.mark.parametrize("streaming", [False, True])
async def test_noncompliant_provider_gets_only_one_repair_turn(streaming):
    result, calls, commits = await run_script(
        [{"content": "Draft only."}, {"content": "Still only a draft."}], streaming=streaming,
    )
    assert len(calls) == 2
    assert commits == []
    assert result["content"] == "Still only a draft."


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("extra", [{}, {"formal_plan_mutation": False},
                                  {"formal_plan_mutation": True, "denied_tool_names": ["save_formal_plan"]}])
async def test_ordinary_or_denied_turn_never_requests_a_save_repair(streaming, extra):
    _, calls, commits = await run_script([{"content": "Discuss the plan."}],
                                         streaming=streaming, extra=extra)
    assert len(calls) == 1
    assert commits == []


@pytest.mark.parametrize("streaming", [False, True])
async def test_real_blocker_stops_without_attempting_a_write(streaming):
    _, calls, commits = await run_script(
        [{"tool_calls": [tool_call("coach_finalize", {"decision": "blocked", "blocker": "Plan is frozen."})]}],
        streaming=streaming,
    )
    assert len(calls) == 1
    assert commits == []


@pytest.mark.parametrize("streaming", [False, True])
async def test_successful_commit_does_not_trigger_a_second_save(streaming):
    _, calls, commits = await run_script(
        [{"tool_calls": [tool_call("save_formal_plan")]}, {"content": "Saved."}],
        streaming=streaming,
    )
    assert len(calls) == 2
    assert len(commits) == 1


async def run_script(responses, *, streaming, extra=None):
    registry = ToolRegistry()
    commits = []

    async def save(_context, args):
        commits.append(args)
        return {"ok": True, "committed": True}

    async def finalize(_context, args):
        return {"ok": True, "final": True, "summary": "Done", **args}

    for name, handler in [("save_formal_plan", save), ("coach_finalize", finalize)]:
        registry.register(ToolDefinition(name=name, description=name,
                                         parameters={"type": "object", "properties": {}}, handler=handler))
    calls = []

    async def call(history, _tools):
        calls.append([dict(message) for message in history])
        assert len(calls) <= len(responses), "The model repair must be bounded."
        return responses[len(calls) - 1]

    async def stream(history, tools):
        yield {"type": "final", **await call(history, tools)}

    context = ToolContext(runtime=None, workspace_id="workspace-test", extra=(
        {"formal_plan_mutation": True} if extra is None else extra))
    loop = CoachAgentLoop(provider=AgentProvider(protocol="openai_chat_completions",
                                                call=call, call_stream=stream),
                          registry=registry, context=context)
    messages = [{"role": "user", "content": "Correct and save the same three-stage plan."}]
    if streaming:
        events = [event async for event in loop.run_stream(messages)]
        result = next(event for event in reversed(events) if event["type"] == "final")
    else:
        final = await loop.run(messages)
        result = {"stop_reason": final.stop_reason, "content": final.final_content}
    return result, calls, commits
