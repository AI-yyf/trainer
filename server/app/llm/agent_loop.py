"""Trainer coach agent loop.

A Pi-style until-done ReAct loop on top of
:class:`~app.llm.provider_service.ProviderService`. Given a list of canonical
OpenAI-format messages, a :class:`~app.llm.tools.ToolRegistry`, and a
:class:`~app.llm.tools.ToolContext`, it drives a tool-use conversation:

1. Call the model with the current message history and tool schema.
2. If the response declares ``tool_calls``: execute each via the registry,
   append the assistant's tool call message and a ``role=tool`` result for
   every call, prune older tool bodies, and loop.
3. If the response is plain text (no tool calls): yield it as the final
   assistant turn and stop. This is the operational bound, matching
   earendil-works/pi ``while (hasMoreToolCalls)``.
4. Stop early if the model calls the ``coach_finalize`` sentinel tool,
   abort/cancel fires, or an identical-tool / same-result circuit-breaker
   trips. A high safety ceiling exists only as a last-resort runaway guard.

The streaming variant ``run_stream`` yields a sequence of typed events:

* ``{"type": "text", "delta": str}`` for assistant text deltas.
* ``{"type": "tool_call", "id": str, "name": str, "arguments": str}`` once a
  tool call is decided.
* ``{"type": "tool_result", "id": str, "name": str, "ok": bool, "result": Any}``
  when a tool finishes.
* ``{"type": "step", "index": int, "stop_reason": str | None}`` between steps
  for UI progress.
* ``{"type": "final", "content": str, "summary": str | None, "next_step": str | None}``
  on a clean stop.
* ``{"type": "error", "detail": str, "category": str}`` on terminal failure.

Tool-capable turns preserve the provider's visible text deltas when the
provider marks them as safe. Tool-call argument deltas are still owned by the
provider binding and are never exposed as learner text. A final frame only
fills in text that was not already forwarded, so consumers can render a true
incremental stream without duplicating the completion envelope.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from .harness import (
    DEFAULT_TOOL_OUTPUT_LIMIT,
    OVERFLOW_KEEP_RECENT_TOKENS,
    append_steering_messages,
    compact_history,
    drain_steering_messages,
    is_prompt_too_long_error,
    is_truncated_stop,
    prepare_next_turn,
    prune_older_tool_results,
    tool_output_limit,
    tools_are_read_only,
    truncated_tool_failure,
)
from .harness import (
    MAX_KEPT_TOOL_RESULT_CHARS as HARNESS_KEPT_TOOL_CHARS,
)
from .harness import (
    PRUNED_TOOL_RESULT_MARK as HARNESS_PRUNED_MARK,
)
from .harness import (
    RECENT_TOOL_KEEP as HARNESS_RECENT_TOOL_KEEP,
)
from .provider_service import redact_provider_error
from .tools import ToolContext, ToolRegistry

logger = logging.getLogger("trainer.llm.agent_loop")

@dataclass
class AgentStep:
    """One iteration of the loop, kept for tracing/debug."""

    index: int
    assistant_content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None


@dataclass
class AgentRunResult:
    """Final outcome of a non-streaming run."""

    final_content: str
    steps: list[AgentStep] = field(default_factory=list)
    summary: str | None = None
    next_step: str | None = None
    stop_reason: str = "completed"
    error: str | None = None
    decision: str | None = None
    blocker: str | None = None
    teaching_note: str | None = None
    resume_thread: str | None = None
    confidence: str | None = None
    evidence: list[str] | None = None


class AgentLoopError(RuntimeError):
    """Raised when the agent loop cannot make any progress."""


# -- The provider hook signature --------------------------------------------
#
# The loop only needs three concrete capabilities from the provider:
#
# 1. ``call_with_tools(messages, tools)`` -> (assistant_text, tool_calls)
#    A non-streaming completion that may include tool calls.
# 2. ``call_with_tools_stream(messages, tools)`` -> async generator yielding
#    ``{"type": "delta", "delta": str}`` and finally
#    ``{"type": "final", "content": str, "tool_calls": list, "stop_reason": str}``.
# 3. ``protocol_name`` (string) for tool-schema formatting.
#
# We accept a duck-typed object so unit tests can pass a tiny stub.

ProviderHookCall = Callable[
    [list[dict[str, Any]], list[dict[str, Any]] | None],
    Awaitable[dict[str, Any]],
]
ProviderHookStream = Callable[
    [list[dict[str, Any]], list[dict[str, Any]] | None],
    AsyncIterator[dict[str, Any]],
]


def _stream_cancel_event(context: ToolContext) -> asyncio.Event | None:
    value = context.extra.get("stream_cancel_event") if isinstance(context.extra, dict) else None
    return value if isinstance(value, asyncio.Event) else None


async def _await_with_stream_cancellation(
    awaitable: Awaitable[Any],
    cancel_event: asyncio.Event | None,
) -> Any:
    """Cancel an upstream await as soon as the active SSE turn is cancelled."""

    if cancel_event is None:
        return await awaitable
    if cancel_event.is_set():
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise asyncio.CancelledError

    operation = asyncio.ensure_future(awaitable)
    cancellation = asyncio.create_task(cancel_event.wait())
    try:
        done, _ = await asyncio.wait(
            {operation, cancellation},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation in done and cancel_event.is_set():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise asyncio.CancelledError
        return operation.result()
    finally:
        if not cancellation.done():
            cancellation.cancel()
        await asyncio.gather(cancellation, return_exceptions=True)


async def _iterate_with_stream_cancellation(
    stream: AsyncIterator[dict[str, Any]],
    cancel_event: asyncio.Event | None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield provider events while making cancellation close the upstream iterator."""

    iterator = stream.__aiter__()

    async def close_iterator() -> None:
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()

    while True:
        if cancel_event is None:
            try:
                yield await iterator.__anext__()
            except StopAsyncIteration:
                return
            continue
        if cancel_event.is_set():
            await close_iterator()
            raise asyncio.CancelledError
        next_event = asyncio.ensure_future(iterator.__anext__())
        cancellation = asyncio.create_task(cancel_event.wait())
        try:
            done, _ = await asyncio.wait(
                {next_event, cancellation},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation in done and cancel_event.is_set():
                next_event.cancel()
                await asyncio.gather(next_event, return_exceptions=True)
                await close_iterator()
                raise asyncio.CancelledError
            try:
                yield next_event.result()
            except StopAsyncIteration:
                return
        finally:
            if not cancellation.done():
                cancellation.cancel()
            await asyncio.gather(cancellation, return_exceptions=True)


@dataclass
class AgentProvider:
    protocol: str
    call: ProviderHookCall
    call_stream: ProviderHookStream | None = None


# ---------------------------------------------------------------------------
# Core driver
# ---------------------------------------------------------------------------

# Last-resort runaway guard. Pi core has no default cap; pi-agents uses
# maxTurns=250; loop-guard defaults to unbounded. Kept as a module-level
# constant so callers can read it even when tests replace CoachAgentLoop.
SAFETY_MAX_STEPS = 250


class CoachAgentLoop:
    """Drives multi-step tool-use coaching turns.

    Inner-loop contract (Pi agent-loop.ts): keep calling the model while the
    latest assistant message still contains tool calls. Context window +
    within-turn prune + abort + circuit-breakers are the real bounds. Lane
    budgets of 8/16/20 steps are the wrong bound and are not used.

    Heavy lifting (formatting tool schemas per protocol, parsing tool calls
    from native responses) lives in :mod:`app.llm.provider_service`.
    """

    SAFETY_MAX_STEPS = SAFETY_MAX_STEPS
    DEFAULT_MAX_STEPS = SAFETY_MAX_STEPS
    LIBRARY_MAX_STEPS = SAFETY_MAX_STEPS
    PLAN_MAX_STEPS = SAFETY_MAX_STEPS
    MAX_TOOL_RESULT_CHARS = DEFAULT_TOOL_OUTPUT_LIMIT
    MAX_KEPT_TOOL_RESULT_CHARS = HARNESS_KEPT_TOOL_CHARS
    RECENT_TOOL_KEEP = HARNESS_RECENT_TOOL_KEEP
    MAX_TURN_HISTORY_CHARS = 80_000
    PRUNED_TOOL_RESULT_MARK = HARNESS_PRUNED_MARK
    MAX_IDENTICAL_TOOL_STREAK = 2
    DEFAULT_STEP_TIMEOUT_SECONDS = 24.0
    DEFAULT_FIRST_STEP_TIMEOUT_SECONDS = 90.0
    MIN_STEP_TIMEOUT_SECONDS = 1.0
    MAX_STEP_TIMEOUT_SECONDS = 180.0

    def __init__(
        self,
        *,
        provider: AgentProvider,
        registry: ToolRegistry,
        context: ToolContext,
        max_steps: int | None = None,
        step_timeout: float | None = None,
        first_step_timeout: float | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.context = context
        resolved_max_steps = self.SAFETY_MAX_STEPS if max_steps is None else max_steps
        self.max_steps = max(1, int(resolved_max_steps))
        has_explicit_step_timeout = step_timeout is not None
        self.step_timeout = self._bounded_step_timeout(
            self.DEFAULT_STEP_TIMEOUT_SECONDS if step_timeout is None else step_timeout
        )
        resolved_first_step_timeout = first_step_timeout
        if resolved_first_step_timeout is None:
            resolved_first_step_timeout = (
                self.step_timeout
                if has_explicit_step_timeout
                else self.DEFAULT_FIRST_STEP_TIMEOUT_SECONDS
            )
        self.first_step_timeout = self._bounded_step_timeout(resolved_first_step_timeout)

    # ---- non-streaming -----------------------------------------------------

    async def run(self, messages: list[dict[str, Any]]) -> AgentRunResult:
        history: list[dict[str, Any]] = list(messages)
        steps: list[AgentStep] = []
        last_tool_calls_signature: tuple[tuple[str, str], ...] | None = None
        last_tool_results_signature: tuple[tuple[str, str], ...] | None = None
        identical_call_streak = 0
        index = 0
        self._prepare_next_turn(history)
        while True:
            if index >= self.max_steps:
                summary, next_step = _build_step_limit_recovery(
                    steps[-1] if steps else None,
                    context=self.context,
                    response_language=self.context.response_language,
                )
                return AgentRunResult(
                    final_content=_visible_text_from_steps(steps, summary, next_step),
                    steps=steps,
                    summary=summary,
                    next_step=next_step,
                    stop_reason="max_steps",
                )
            tools_schema = self._tools_schema()
            timeout = self._step_timeout_for(index)
            try:
                response = await self._call_provider(history, tools_schema, timeout)
            except asyncio.TimeoutError:
                summary, next_step = _build_runtime_failure_recovery(
                    "timeout",
                    context=self.context,
                    response_language=self.context.response_language,
                    previous_step=steps[-1] if steps else None,
                )
                return AgentRunResult(
                    final_content=_visible_text_from_steps(steps, summary, next_step),
                    steps=steps,
                    summary=summary,
                    next_step=next_step,
                    stop_reason="timeout",
                    error=f"agent step {index} exceeded {timeout}s",
                )
            except Exception as exc:
                logger.exception("agent_step_failed", extra={"step": index})
                summary, next_step = _build_runtime_failure_recovery(
                    "provider_error",
                    context=self.context,
                    response_language=self.context.response_language,
                    previous_step=steps[-1] if steps else None,
                )
                return AgentRunResult(
                    final_content=_visible_text_from_steps(steps, summary, next_step),
                    steps=steps,
                    summary=summary,
                    next_step=next_step,
                    stop_reason="provider_error",
                    error=redact_provider_error(exc),
                )

            assistant_text = str(response.get("content") or "")
            tool_calls = list(response.get("tool_calls") or [])
            step = AgentStep(
                index=index,
                assistant_content=assistant_text,
                tool_calls=tool_calls,
            )
            steps.append(step)

            history.append(_assistant_message(assistant_text, tool_calls))

            if not tool_calls:
                if not assistant_text.strip():
                    step.stop_reason = "empty_response"
                    summary, next_step = _build_empty_response_recovery(
                        context=self.context,
                        response_language=self.context.response_language,
                    )
                    return AgentRunResult(
                        final_content="",
                        steps=steps,
                        summary=summary,
                        next_step=next_step,
                        stop_reason="empty_response",
                    )
                step.stop_reason = "final"
                summary, next_step = _build_completion_continuity(
                    assistant_text,
                    context=self.context,
                    response_language=self.context.response_language,
                    previous_step=steps[-2] if len(steps) >= 2 else None,
                )
                return AgentRunResult(
                    final_content=assistant_text,
                    steps=steps,
                    summary=summary,
                    next_step=next_step,
                    stop_reason="completed",
                )

            tool_calls_signature = _tool_calls_signature(tool_calls)
            if last_tool_calls_signature == tool_calls_signature:
                identical_call_streak += 1
            else:
                identical_call_streak = 0
            if identical_call_streak >= self.MAX_IDENTICAL_TOOL_STREAK:
                step.stop_reason = "no_progress"
                summary, next_step = _build_no_progress_recovery(
                    tool_calls,
                    previous_step=steps[-2] if len(steps) >= 2 else None,
                    context=self.context,
                    response_language=self.context.response_language,
                )
                return AgentRunResult(
                    final_content=_visible_text_from_steps(steps, summary, next_step),
                    steps=steps,
                    summary=summary,
                    next_step=next_step,
                    stop_reason="no_progress",
                )
            last_tool_calls_signature = tool_calls_signature

            finalize_payload, finalize_arguments, _events = await self._invoke_tool_batch(
                tool_calls,
                history,
                step,
                truncated=is_truncated_stop(response.get("stop_reason") or response.get("finish_reason")),
            )

            if finalize_payload is not None:
                finalize_data = _normalize_coach_finalize_payload(
                    _merge_coach_finalize_payload(
                        arguments=merge_tool_arguments(finalize_arguments),
                        tool_result=finalize_payload,
                    )
                )
                visible_reply = _visible_coach_finalize_reply(
                    finalize_data,
                    response_language=self.context.response_language,
                )
                step.stop_reason = "coach_finalize"
                return AgentRunResult(
                    final_content=visible_reply,
                    steps=steps,
                    summary=finalize_data["summary"],
                    next_step=finalize_data["next_step"],
                    stop_reason="coach_finalize",
                    decision=finalize_data["decision"],
                    blocker=finalize_data["blocker"],
                    teaching_note=finalize_data["teaching_note"],
                    resume_thread=finalize_data["resume_thread"],
                    confidence=finalize_data["confidence"],
                    evidence=finalize_data["evidence"],
                )

            current_tool_results_signature = _tool_results_signature(step.tool_results)
            if (
                current_tool_results_signature
                and last_tool_results_signature == current_tool_results_signature
            ):
                step.stop_reason = "no_progress"
                summary, next_step = _build_no_progress_recovery(
                    tool_calls,
                    previous_step=steps[-2] if len(steps) >= 2 else None,
                    context=self.context,
                    response_language=self.context.response_language,
                )
                return AgentRunResult(
                    final_content=_visible_text_from_steps(steps, summary, next_step),
                    steps=steps,
                    summary=summary,
                    next_step=next_step,
                    stop_reason="no_progress",
                )
            if current_tool_results_signature:
                last_tool_results_signature = current_tool_results_signature
            self._prepare_next_turn(history)
            index += 1

    # ---- streaming ---------------------------------------------------------

    async def run_stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        history: list[dict[str, Any]] = list(messages)
        cancel_event = _stream_cancel_event(self.context)
        last_tool_calls_signature: tuple[tuple[str, str], ...] | None = None
        last_tool_results_signature: tuple[tuple[str, str], ...] | None = None
        identical_call_streak = 0
        previous_step: AgentStep | None = None
        streamed_steps: list[AgentStep] = []
        index = 0
        self._prepare_next_turn(history)
        while True:
            if index >= self.max_steps:
                summary, next_step = _build_step_limit_recovery(
                    previous_step,
                    context=self.context,
                    response_language=self.context.response_language,
                )
                yield {
                    "type": "final",
                    "content": _visible_text_from_steps(streamed_steps, summary, next_step),
                    "summary": summary,
                    "next_step": next_step,
                    "stop_reason": "max_steps",
                }
                return
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError
            tools_schema = self._tools_schema()
            # Without a tool schema, a provider cannot validly choose a tool
            # path. Preserve true first-token streaming for that direct path.
            stream_direct_text = not tools_schema
            assistant_text = ""
            streamed_text = ""
            streamed_text_safe = False
            tool_calls: list[dict[str, Any]] = []
            stream_stop_reason: str | None = None
            yield {"type": "step", "index": index, "stop_reason": None}

            stream_fn = self.provider.call_stream
            if stream_fn is None:
                summary, next_step = _build_runtime_failure_recovery(
                    "streaming_unavailable",
                    context=self.context,
                    response_language=self.context.response_language,
                    previous_step=previous_step,
                )
                yield {
                    "type": "error",
                    "detail": "The configured provider does not expose native streaming.",
                    "category": "streaming_unavailable",
                    "recoverable": True,
                    "terminal": True,
                    "degraded": False,
                }
                yield {
                    "type": "final",
                    "content": "",
                    "summary": summary,
                    "next_step": next_step,
                    "stop_reason": "streaming_unavailable",
                    "recoverable": True,
                    "degraded": False,
                }
                return
            else:
                try:
                    async for event in _iterate_with_stream_cancellation(
                        stream_fn(history, tools_schema),
                        cancel_event,
                    ):
                        event_type = event.get("type")
                        if event_type == "delta":
                            delta = str(event.get("delta") or "")
                            if delta:
                                assistant_text += delta
                                if stream_direct_text:
                                    yield {"type": "text", "delta": delta}
                                    streamed_text += delta
                                elif event.get("safe_to_stream") is True:
                                    yield {
                                        "type": "text",
                                        "delta": delta,
                                        "safe_to_stream": True,
                                    }
                                    streamed_text += delta
                                    streamed_text_safe = True
                        elif event_type == "final":
                            assistant_text = str(event.get("content") or assistant_text)
                            tool_calls = list(event.get("tool_calls") or [])
                            raw_stop = event.get("stop_reason") or event.get("finish_reason")
                            stream_stop_reason = str(raw_stop) if raw_stop else None
                            break
                        else:
                            yield event
                except Exception as exc:
                    if is_prompt_too_long_error(exc):
                        compact_history(
                            history,
                            extra=self._extra(),
                            keep_recent_tokens=OVERFLOW_KEEP_RECENT_TOKENS,
                            reason="overflow",
                            force=True,
                        )
                        prune_older_tool_results(history, history_char_budget=40_000)
                        continue
                    logger.exception("agent_stream_failed", extra={"step": index})
                    yield {
                        "type": "error",
                        "detail": redact_provider_error(exc),
                        "category": "provider_error",
                    }
                    summary, next_step = _build_runtime_failure_recovery(
                        "provider_error",
                        context=self.context,
                        response_language=self.context.response_language,
                        previous_step=previous_step,
                    )
                    yield {
                        "type": "final",
                        "content": assistant_text,
                        "summary": summary,
                        "next_step": next_step,
                        "stop_reason": "provider_error",
                    }
                    return

            history.append(_assistant_message(assistant_text, tool_calls))

            if not tool_calls:
                if not assistant_text.strip():
                    summary, next_step = _build_empty_response_recovery(
                        context=self.context,
                        response_language=self.context.response_language,
                    )
                    yield {
                        "type": "final",
                        "content": assistant_text,
                        "summary": summary,
                        "next_step": next_step,
                        "stop_reason": "empty_response",
                    }
                    return
                # The provider may omit a tail in its delta sequence and only
                # include it in the final frame. Emit that suffix exactly
                # once, preserving the incremental contract for both direct
                # and tool-capable streams.
                if assistant_text.startswith(streamed_text):
                    missing_text = assistant_text[len(streamed_text) :]
                else:
                    # A provider is allowed to normalize its final content.
                    # Do not duplicate a prefix already rendered; emit the
                    # normalized final content as one replacement delta.
                    missing_text = assistant_text
                if missing_text:
                    if stream_direct_text:
                        yield {"type": "text", "delta": missing_text}
                    else:
                        event = {"type": "text", "delta": missing_text}
                        if streamed_text_safe:
                            event["safe_to_stream"] = True
                        yield event
                summary, next_step = _build_completion_continuity(
                    assistant_text,
                    context=self.context,
                    response_language=self.context.response_language,
                    previous_step=previous_step,
                )
                yield {
                    "type": "final",
                    "content": assistant_text,
                    "summary": summary,
                    "next_step": next_step,
                    "stop_reason": "completed",
                }
                return

            tool_calls_signature = _tool_calls_signature(tool_calls)
            if last_tool_calls_signature == tool_calls_signature:
                identical_call_streak += 1
            else:
                identical_call_streak = 0
            if identical_call_streak >= self.MAX_IDENTICAL_TOOL_STREAK:
                summary, next_step = _build_no_progress_recovery(
                    tool_calls,
                    previous_step=previous_step,
                    context=self.context,
                    response_language=self.context.response_language,
                )
                yield {
                    "type": "final",
                    "content": _visible_text_from_steps(streamed_steps, summary, next_step),
                    "summary": summary,
                    "next_step": next_step,
                    "stop_reason": "no_progress",
                }
                return
            last_tool_calls_signature = tool_calls_signature
            step = AgentStep(
                index=index,
                assistant_content=assistant_text,
                tool_calls=tool_calls,
            )

            finalize_payload, finalize_arguments, tool_events = await self._invoke_tool_batch(
                tool_calls,
                history,
                step,
                truncated=is_truncated_stop(stream_stop_reason),
                cancel_event=cancel_event,
            )
            for tool_event in tool_events:
                yield tool_event

            if finalize_payload is not None:
                finalize_data = _normalize_coach_finalize_payload(
                    _merge_coach_finalize_payload(
                        arguments=merge_tool_arguments(finalize_arguments),
                        tool_result=finalize_payload,
                    )
                )
                visible_reply = _visible_coach_finalize_reply(
                    finalize_data,
                    response_language=self.context.response_language,
                )
                if visible_reply:
                    yield {"type": "text", "delta": visible_reply}
                yield {
                    "type": "final",
                    "content": visible_reply,
                    "summary": finalize_data["summary"],
                    "next_step": finalize_data["next_step"],
                    "stop_reason": "coach_finalize",
                    "decision": finalize_data["decision"],
                    "blocker": finalize_data["blocker"],
                    "teaching_note": finalize_data["teaching_note"],
                    "resume_thread": finalize_data["resume_thread"],
                    "confidence": finalize_data["confidence"],
                    "evidence": finalize_data["evidence"],
                }
                return

            current_tool_results_signature = _tool_results_signature(step.tool_results)
            if (
                current_tool_results_signature
                and last_tool_results_signature == current_tool_results_signature
            ):
                summary, next_step = _build_no_progress_recovery(
                    tool_calls,
                    previous_step=previous_step,
                    context=self.context,
                    response_language=self.context.response_language,
                )
                yield {
                    "type": "final",
                    "content": _visible_text_from_steps(streamed_steps + [step], summary, next_step),
                    "summary": summary,
                    "next_step": next_step,
                    "stop_reason": "no_progress",
                }
                return
            if current_tool_results_signature:
                last_tool_results_signature = current_tool_results_signature
            self._prepare_next_turn(history)

            previous_step = step
            streamed_steps.append(step)
            index += 1

    # ---- helpers -----------------------------------------------------------

    def _tools_schema(self) -> list[dict[str, Any]]:
        extra = self.context.extra if isinstance(self.context.extra, dict) else {}
        return self.registry.as_protocol_schemas(
            self.provider.protocol,
            allow_coach_only=extra.get("allow_coach_only_tools") is True,
            allowed_tool_names=extra.get("allowed_tool_names"),
            denied_tool_names=extra.get("denied_tool_names"),
            explicit_training_card_request=extra.get("explicit_training_card_request") is True,
            formal_plan_mutation=extra.get("formal_plan_mutation") is True,
            explicit_learning_note_request=extra.get("explicit_learning_note_request") is True,
            explicit_resource_import=extra.get("explicit_resource_import") is True,
            explicit_resource_organize=extra.get("explicit_resource_organize") is True,
            live_formal_plan_for_task_mint=extra.get("live_formal_plan_for_task_mint") is True,
        )

    @classmethod
    def _bounded_step_timeout(cls, timeout: float) -> float:
        return min(
            cls.MAX_STEP_TIMEOUT_SECONDS,
            max(cls.MIN_STEP_TIMEOUT_SECONDS, float(timeout)),
        )

    def _step_timeout_for(self, index: int) -> float:
        return self.first_step_timeout if index == 0 else self.step_timeout

    def _extra(self) -> dict[str, Any]:
        extra = self.context.extra if isinstance(self.context.extra, dict) else {}
        return extra

    def _prepare_next_turn(self, history: list[dict[str, Any]]) -> None:
        steered = drain_steering_messages(self.context)
        append_steering_messages(history, steered)
        prepare_next_turn(
            history,
            extra=self._extra(),
            history_char_budget=self.MAX_TURN_HISTORY_CHARS,
        )

    async def _call_provider(
        self,
        history: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]],
        timeout: float,
    ) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(self.provider.call(history, tools_schema), timeout=timeout)
        except Exception as exc:
            if not is_prompt_too_long_error(exc):
                raise
            compact_history(
                history,
                extra=self._extra(),
                keep_recent_tokens=OVERFLOW_KEEP_RECENT_TOKENS,
                reason="overflow",
                force=True,
            )
            prune_older_tool_results(history, history_char_budget=40_000)
            return await asyncio.wait_for(self.provider.call(history, tools_schema), timeout=timeout)

    async def _invoke_one_tool(
        self,
        call: dict[str, Any],
        cancel_event: asyncio.Event | None,
    ) -> tuple[str, str, Any, dict[str, Any]]:
        tool_name = str(call.get("name") or "")
        tool_id = str(call.get("id") or tool_name)
        arguments = call.get("arguments")
        if cancel_event is None:
            tool_result = await self.registry.invoke(self.context, tool_name, arguments)
        else:
            tool_result = await _await_with_stream_cancellation(
                self.registry.invoke(self.context, tool_name, arguments),
                cancel_event,
            )
        return tool_id, tool_name, arguments, tool_result

    async def _invoke_tool_batch(
        self,
        tool_calls: list[dict[str, Any]],
        history: list[dict[str, Any]],
        step: AgentStep,
        *,
        truncated: bool,
        cancel_event: asyncio.Event | None = None,
    ) -> tuple[dict[str, Any] | None, Any, list[dict[str, Any]]]:
        events: list[dict[str, Any]] = []
        if truncated and tool_calls:
            for call in tool_calls:
                tool_name = str(call.get("name") or "")
                tool_id = str(call.get("id") or tool_name)
                tool_result = truncated_tool_failure(tool_name)
                events.append(
                    {"type": "tool_call", "id": tool_id, "name": tool_name, "arguments": call.get("arguments")}
                )
                events.append(
                    {
                        "type": "tool_result",
                        "id": tool_id,
                        "name": tool_name,
                        "ok": False,
                        "result": tool_result,
                    }
                )
                step.tool_results.append({"id": tool_id, "name": tool_name, "result": tool_result})
                history.append(_tool_message(tool_id, tool_name, tool_result))
            return None, None, events

        parallel = tools_are_read_only(tool_calls) and len(tool_calls) > 1
        if parallel:
            for call in tool_calls:
                tool_name = str(call.get("name") or "")
                tool_id = str(call.get("id") or tool_name)
                events.append(
                    {
                        "type": "tool_call",
                        "id": tool_id,
                        "name": tool_name,
                        "arguments": call.get("arguments"),
                    }
                )
            invoked = await asyncio.gather(
                *[self._invoke_one_tool(call, cancel_event) for call in tool_calls]
            )
            for tool_id, tool_name, _arguments, tool_result in invoked:
                events.append(
                    {
                        "type": "tool_result",
                        "id": tool_id,
                        "name": tool_name,
                        "ok": bool(tool_result.get("ok")),
                        "result": tool_result,
                    }
                )
                step.tool_results.append({"id": tool_id, "name": tool_name, "result": tool_result})
                history.append(_tool_message(tool_id, tool_name, tool_result))
            return None, None, events

        finalize_payload: dict[str, Any] | None = None
        finalize_arguments: Any = None
        for call in tool_calls:
            tool_name = str(call.get("name") or "")
            tool_id = str(call.get("id") or tool_name)
            arguments = call.get("arguments")
            events.append(
                {
                    "type": "tool_call",
                    "id": tool_id,
                    "name": tool_name,
                    "arguments": arguments,
                }
            )
            _tool_id, _tool_name, _arguments, tool_result = await self._invoke_one_tool(
                call, cancel_event
            )
            events.append(
                {
                    "type": "tool_result",
                    "id": tool_id,
                    "name": tool_name,
                    "ok": bool(tool_result.get("ok")),
                    "result": tool_result,
                }
            )
            step.tool_results.append({"id": tool_id, "name": tool_name, "result": tool_result})
            history.append(_tool_message(tool_id, tool_name, tool_result))
            if tool_name == "coach_finalize" and tool_result.get("final"):
                finalize_payload = tool_result
                finalize_arguments = arguments
                break
        return finalize_payload, finalize_arguments, events

def _assistant_message(
    content: str,
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Append an assistant turn to the history in canonical OpenAI format."""
    message: dict[str, Any] = {"role": "assistant", "content": content or ""}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": str(call.get("id") or call.get("name") or ""),
                "type": "function",
                "function": {
                    "name": str(call.get("name") or ""),
                    "arguments": _ensure_string_args(call.get("arguments")),
                },
            }
            for call in tool_calls
        ]
    return message


def _truncate_tool_payload(content_text: str, *, limit: int) -> str:
    text = str(content_text or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit)] + "\n…[truncated]"


def _tool_message(call_id: str, name: str, result: Any) -> dict[str, Any]:
    if not isinstance(result, str):
        try:
            content_text = json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            content_text = str(result)
    else:
        content_text = result
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": _truncate_tool_payload(
            content_text,
            limit=tool_output_limit(name),
        ),
    }


def _shrink_older_tool_history(history: list[dict[str, Any]]) -> None:
    """Pi/OpenCode within-turn prune: keep recent tool bodies, shrink then stub older ones."""

    prune_older_tool_results(
        history,
        recent_keep=CoachAgentLoop.RECENT_TOOL_KEEP,
        kept_chars=CoachAgentLoop.MAX_KEPT_TOOL_RESULT_CHARS,
        history_char_budget=CoachAgentLoop.MAX_TURN_HISTORY_CHARS,
    )


def _visible_text_from_steps(
    steps: list[AgentStep],
    summary: str | None = None,
    next_step: str | None = None,
) -> str:
    """Keep a visible bubble when the loop stops without a natural final reply."""

    for step in reversed(steps):
        text = str(step.assistant_content or "").strip()
        if text:
            return text
    for step in reversed(steps):
        for item in reversed(step.tool_results):
            if not isinstance(item, dict):
                continue
            payload = item.get("result")
            if not isinstance(payload, dict):
                continue
            for key in ("summary", "content", "detail"):
                value = str(payload.get(key) or "").strip()
                if value:
                    return value[:2000]
    parts = [str(summary or "").strip(), str(next_step or "").strip()]
    return "\n\n".join(part for part in parts if part)


def _ensure_string_args(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    if arguments is None:
        return ""
    try:
        return json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(arguments)


def _tool_calls_signature(tool_calls: list[dict[str, Any]]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            str(call.get("name") or ""),
            _ensure_string_args(call.get("arguments")),
        )
        for call in tool_calls
    )


def _tool_results_signature(
    tool_results: list[dict[str, Any]],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            str(result.get("name") or ""),
            _ensure_string_args(result.get("result")),
        )
        for result in tool_results
    )


def _normalize_coach_finalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    def text(value: object | None, *, limit: int = 160) -> str:
        if value is None:
            return ""
        return _compact_text(str(value), limit) or ""

    summary = text(payload.get("summary"), limit=240)
    decision = text(payload.get("decision"), limit=240)
    next_step = text(payload.get("next_step"), limit=240)
    blocker = text(payload.get("blocker"), limit=240)
    teaching_note = text(payload.get("teaching_note"), limit=240)
    resume_thread = text(payload.get("resume_thread"), limit=240)
    confidence = text(payload.get("confidence"), limit=80)
    evidence: list[str] = []
    raw_evidence = payload.get("evidence")
    if isinstance(raw_evidence, list):
        for item in raw_evidence:
            item_text = text(item, limit=240)
            if item_text:
                evidence.append(item_text)

    return {
        "summary": summary or decision or None,
        "decision": decision or None,
        "next_step": next_step or None,
        "blocker": blocker or None,
        "teaching_note": teaching_note or None,
        "resume_thread": resume_thread or None,
        "confidence": confidence or None,
        "evidence": evidence or None,
    }


def _visible_coach_finalize_reply(
    payload: dict[str, Any],
    *,
    response_language: str | None,
) -> str:
    """Turn verified finalize metadata into a compact learner-facing close."""
    chinese = bool(response_language and response_language.lower().startswith("zh"))
    next_label = "\u4e0b\u4e00\u6b65\uff1a" if chinese else "Next step: "
    blocker_label = "\u5f53\u524d\u963b\u585e\uff1a" if chinese else "Current blocker: "
    parts: list[str] = []

    for key in ("summary", "decision", "teaching_note"):
        value = str(payload.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)

    blocker = str(payload.get("blocker") or "").strip()
    if blocker:
        parts.append(f"{blocker_label}{blocker}")

    next_step = str(payload.get("next_step") or "").strip()
    if next_step:
        parts.append(f"{next_label}{next_step}")

    return "\n\n".join(parts)


def _merge_coach_finalize_payload(
    *,
    arguments: dict[str, Any],
    tool_result: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(arguments)
    merged.update(tool_result)
    for key in (
        "summary",
        "next_step",
        "decision",
        "blocker",
        "teaching_note",
        "resume_thread",
        "confidence",
        "evidence",
    ):
        if key in merged and merged.get(key):
            continue
        if arguments.get(key):
            merged[key] = arguments.get(key)
    return merged


def _build_no_progress_recovery(
    tool_calls: list[dict[str, Any]],
    *,
    previous_step: AgentStep | None,
    context: ToolContext | None,
    response_language: str | None,
) -> tuple[str, str]:
    chinese = bool(response_language and response_language.lower().startswith("zh"))
    tool_names = [
        str(call.get("name") or "").strip()
        for call in tool_calls
        if str(call.get("name") or "").strip()
        and str(call.get("name") or "").strip() != "coach_finalize"
    ]
    unique_tool_names = list(dict.fromkeys(tool_names))
    tool_path = " → ".join(unique_tool_names[:3]) if unique_tool_names else ""
    failure_note = _previous_step_failure_note(previous_step)
    focus_note = _recovery_focus_note(context)
    next_step_note = _recovery_next_step_note(context)

    if chinese:
        summary = (
            f"模型重复了相同的工具路径{f'：{tool_path}' if tool_path else ''}，但没有带来新的证据。"
        )
        if focus_note:
            summary = f"{summary} 当前应该回到：{focus_note}。"
        if failure_note:
            summary = f"{summary} 上一次还卡在：{failure_note}。"
        next_step = (
            "换一个证据来源，或者先把问题收窄，再继续同样的工具路径。"
            if not tool_path
            else f"先换一个证据来源，或者收窄问题，再重新评估是否要继续 `{tool_path}`。"
        )
        if next_step_note:
            next_step = f"{next_step} 也可以先回到 {next_step_note}。"
        if failure_note:
            next_step = f"{next_step} 先修掉 `{failure_note}` 对应的问题。"
        return summary, next_step

    summary = f"The model repeated the same tool path{f': {tool_path}' if tool_path else ''} without new evidence."
    if focus_note:
        summary = f"{summary} The turn should stay anchored to {focus_note}."
    if failure_note:
        summary = f"{summary} The last attempt was already stuck on: {failure_note}."
    next_step = (
        "Switch evidence sources or narrow the question before trying the same tool path again."
        if not tool_path
        else f"Try a different evidence source, then decide whether `{tool_path}` is still the right path."
    )
    if next_step_note:
        next_step = f"{next_step} Or return to {next_step_note}."
    if failure_note:
        next_step = f"{next_step} Fix the issue tied to `{failure_note}` first."
    return summary, next_step


def _previous_step_failure_note(previous_step: AgentStep | None) -> str:
    if previous_step is None:
        return ""
    for result in previous_step.tool_results:
        if not isinstance(result, dict):
            continue
        payload = result.get("result")
        if not isinstance(payload, dict):
            continue
        if payload.get("ok") is False or payload.get("error"):
            name = str(result.get("name") or "").strip()
            error = str(payload.get("error") or "").strip()
            detail = str(payload.get("detail") or "").strip()
            parts = [part for part in [name, error, detail] if part]
            return " / ".join(parts)
    return ""


def _build_step_limit_recovery(
    previous_step: AgentStep | None,
    *,
    context: ToolContext | None,
    response_language: str | None,
) -> tuple[str, str]:
    chinese = bool(response_language and response_language.lower().startswith("zh"))
    failure_note = _previous_step_failure_note(previous_step)
    focus_note = _recovery_focus_note(context)
    next_step_note = _recovery_next_step_note(context)

    if chinese:
        summary = "模型已经跑到步数上限，但还没有自然收束。"
        if focus_note:
            summary = f"{summary} 当前仍应围绕：{focus_note}。"
        next_step = "下一轮先从最近一次工具路径继续；如果还是卡住，就换证据来源或缩小问题。"
        if next_step_note:
            next_step = f"{next_step} 也可以先回到 {next_step_note}。"
        if failure_note:
            summary = f"{summary} 上一轮最接近的卡点是：{failure_note}。"
            next_step = f"{next_step} 先修掉 `{failure_note}` 对应的问题。"
        return summary, next_step

    summary = "The model reached the step limit without a natural stop."
    if focus_note:
        summary = f"{summary} The turn should still be anchored to {focus_note}."
    next_step = "Continue from the latest tool path, but switch evidence sources or narrow scope if you are still stuck."
    if next_step_note:
        next_step = f"{next_step} Or return to {next_step_note}."
    if failure_note:
        summary = f"{summary} The closest blocker was: {failure_note}."
        next_step = f"{next_step} Fix the issue tied to `{failure_note}` first."
    return summary, next_step


def _build_runtime_failure_recovery(
    reason: str,
    *,
    context: ToolContext | None,
    response_language: str | None,
    previous_step: AgentStep | None,
) -> tuple[str, str]:
    chinese = bool(response_language and response_language.lower().startswith("zh"))
    focus_note = _recovery_focus_note(context)
    next_step_note = _recovery_next_step_note(context)
    failure_note = _previous_step_failure_note(previous_step)

    if chinese:
        if reason == "timeout":
            summary = "这一轮工具调用超时了，还没来得及自然收束。"
            next_step = "先回到最近的证据，再缩小问题或换一个更快的检查。"
        else:
            summary = "这一轮教练服务在中途断开了，但我们可以沿着同一条主线续回去。"
            next_step = "先检查 provider 或连接状态，再继续最小的下一步。"
        if focus_note:
            summary = f"{summary} 当前主线还是：{focus_note}。"
        if failure_note:
            summary = f"{summary} 上一轮最接近的卡点是：{failure_note}。"
        if next_step_note:
            next_step = f"{next_step} 也可以先回到 {next_step_note}。"
        return summary, next_step

    if reason == "timeout":
        summary = "This turn timed out before the provider could finish."
        next_step = "Re-anchor on the latest evidence and retry the smallest check."
    else:
        summary = "The provider stopped mid-turn, but the thread can still resume."
        next_step = "Check the provider connection, then retry the smallest anchored step."
    if focus_note:
        summary = f"{summary} Stay anchored to {focus_note}."
    if failure_note:
        summary = f"{summary} The closest blocker was: {failure_note}."
    if next_step_note:
        next_step = f"{next_step} Or return to {next_step_note}."
    return summary, next_step


def _build_empty_response_recovery(
    *,
    context: ToolContext | None,
    response_language: str | None,
) -> tuple[str, str]:
    chinese = bool(response_language and response_language.lower().startswith("zh"))
    focus_note = _recovery_focus_note(context)
    next_step_note = _recovery_next_step_note(context)

    if chinese:
        summary = "模型返回了空内容，所以这轮不能算完成。"
        if focus_note:
            summary = f"{summary} 当前主线仍然是：{focus_note}。"
        next_step = "重新发起这一轮，但要求模型给出可见结论；如果再次为空，就先切回最小可验证动作。"
        if next_step_note:
            next_step = f"{next_step} 也可以先回到 {next_step_note}。"
        return summary, next_step

    summary = (
        "The provider returned an empty visible answer, so this turn cannot be treated as complete."
    )
    if focus_note:
        summary = f"{summary} The thread should stay anchored to {focus_note}."
    next_step = "Retry the turn and require a visible conclusion; if it repeats, fall back to the smallest verifiable move."
    if next_step_note:
        next_step = f"{next_step} Or return to {next_step_note}."
    return summary, next_step


def _build_completion_continuity(
    content: str,
    *,
    context: ToolContext | None,
    response_language: str | None,
    previous_step: AgentStep | None = None,
) -> tuple[str, str]:
    chinese = bool(response_language and response_language.lower().startswith("zh"))
    extra = context.extra if context is not None and isinstance(context.extra, dict) else {}

    def first_text(*keys: str) -> str:
        for key in keys:
            value = extra.get(key)
            text = _compact_text(value, 160)
            if text:
                return text
            if isinstance(value, dict):
                for candidate_key in (
                    "title",
                    "label",
                    "next_step",
                    "nextStep",
                    "summary",
                    "current_step",
                    "fallback_step",
                    "blocker",
                    "verified_result",
                ):
                    text = _compact_text(value.get(candidate_key), 160)
                    if text:
                        return text
        return ""

    def tool_result_text(*keys: str) -> str:
        if previous_step is None:
            return ""
        for tool_result in reversed(previous_step.tool_results):
            if not isinstance(tool_result, dict):
                continue
            payload = tool_result.get("result")
            if not isinstance(payload, dict):
                continue
            for key in keys:
                text = _compact_text(payload.get(key), 160)
                if text:
                    return text
            evidence = payload.get("evidence")
            if isinstance(evidence, list):
                compacted = "; ".join(
                    text for text in (_compact_text(item, 80) for item in evidence[:3]) if text
                )
                if compacted:
                    return compacted
            hits = payload.get("hits")
            if isinstance(hits, list):
                snippets: list[str] = []
                for item in hits[:2]:
                    if not isinstance(item, dict):
                        text = _compact_text(item, 80)
                        if text:
                            snippets.append(text)
                        continue
                    for candidate_key in ("summary", "title", "path", "detail"):
                        text = _compact_text(item.get(candidate_key), 80)
                        if text:
                            snippets.append(text)
                            break
                if snippets:
                    return "; ".join(snippets)
        return ""

    summary = first_text(
        "thread_summary",
        "summary",
        "current_focus",
        "continuity_summary",
        "review_queue_summary",
        "project_summary",
    )
    if not summary:
        summary = tool_result_text("summary", "detail", "status")
    if not summary:
        summary = _trim_sentence(content, 140)
    if not summary:
        summary = (
            "This turn completed cleanly and the thread can continue."
            if not chinese
            else "这一轮已经自然收口，可以继续同一条主线。"
        )

    next_step = first_text(
        "thread_next_step",
        "resume_hint",
        "next_step_hint",
        "implementation_current_step",
        "exercise_fallback_step",
        "thread_blocker",
        "thread_verified_result",
    )
    if not next_step:
        next_step = tool_result_text("next_step", "nextStep", "fallback_step", "recommended_action")
    if not next_step:
        candidate = _trim_sentence(content, 120)
        if candidate and candidate != summary:
            next_step = candidate
    if not next_step:
        next_step = (
            "Continue from the same thread and verify the smallest concrete result."
            if not chinese
            else "继续沿着同一条主线，验证最小的具体结果。"
        )
    return summary, next_step


def _recovery_focus_note(context: ToolContext | None) -> str:
    if context is None:
        return ""
    extra = context.extra if isinstance(context.extra, dict) else {}
    for key in ("current_focus", "thread_summary", "thread_focus_area", "scenario"):
        value = str(extra.get(key) or "").strip()
        if value:
            normalized = value.replace("_", " ")
            if _looks_like_recovery_meta_text(normalized):
                continue
            return normalized
    return ""


def _recovery_next_step_note(context: ToolContext | None) -> str:
    if context is None:
        return ""
    extra = context.extra if isinstance(context.extra, dict) else {}
    for key in (
        "thread_next_step",
        "resume_hint",
        "next_step_hint",
        "implementation_current_step",
        "exercise_fallback_step",
    ):
        value = extra.get(key)
        if isinstance(value, str) and value.strip():
            candidate = value.strip()
            if _looks_like_recovery_meta_text(candidate):
                continue
            return candidate
        if isinstance(value, dict):
            for candidate_key in (
                "title",
                "label",
                "next_step",
                "nextStep",
                "summary",
                "fallback_step",
                "current_step",
            ):
                text = str(value.get(candidate_key) or "").strip()
                if text:
                    if _looks_like_recovery_meta_text(text):
                        continue
                    return text
    return ""


def _looks_like_recovery_meta_text(value: str) -> bool:
    normalized = " ".join(value.split()).strip().lower()
    if not normalized:
        return False

    english_markers = (
        "empty visible answer",
        "no visible answer",
        "turn cannot be treated as complete",
        "retry the turn and require a visible conclusion",
        "resume the live thread around",
        "keep the next move as",
    )
    if any(marker in normalized for marker in english_markers):
        return True

    chinese_markers = (
        "\u7a7a\u5185\u5bb9",
        "\u53ef\u89c1\u7ed3\u8bba",
        "\u91cd\u65b0\u53d1\u8d77\u8fd9\u4e00\u8f6e",
        "\u7ee7\u7eed\u6cbf\u7740\u540c\u4e00\u6761\u4e3b\u7ebf",
    )
    return any(marker in value for marker in chinese_markers)


def _compact_text(value: object | None, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 1)].rstrip()}..."


def _trim_sentence(text: str, limit: int) -> str:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 1)].rstrip()}..."


__all__ = [
    "AgentProvider",
    "AgentRunResult",
    "AgentStep",
    "AgentLoopError",
    "CoachAgentLoop",
]


# ---------------------------------------------------------------------------
# Convenience: construct a non-streaming hook that calls back into a
# ProviderService instance using the new tool-aware request paths.
#
# Importing here is a stub-friendly pattern: the actual binding lives next to
# ProviderService (see ``ProviderService.build_agent_provider`` below) so this
# module stays free of provider_service import cycles.
# ---------------------------------------------------------------------------


def merge_tool_arguments(arguments: Any) -> dict[str, Any]:
    """Public helper for callers that need to parse tool-call arguments the
    same way the registry does."""
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"_raw_arguments": text}
        if isinstance(parsed, dict):
            return parsed
        return {"_raw_arguments": parsed}
    return {"_raw_arguments": arguments}


# Smoke-test entry-point used by automated tests to drive the loop with a
# scripted provider that returns precomputed responses.
async def run_with_scripted_responses(
    *,
    registry: ToolRegistry,
    context: ToolContext,
    scripted_responses: list[dict[str, Any]],
    initial_messages: list[dict[str, Any]],
    max_steps: int = 4,
) -> AgentRunResult:
    """Drive ``CoachAgentLoop`` using a list of precomputed provider responses.

    Each response is a dict with ``content`` and ``tool_calls`` keys.
    """
    iterator = iter(scripted_responses)

    async def _call(
        _messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        try:
            return next(iterator)
        except StopIteration as exc:  # pragma: no cover - defensive
            raise AgentLoopError("Scripted responses exhausted") from exc

    provider = AgentProvider(protocol="openai_chat_completions", call=_call)
    loop = CoachAgentLoop(
        provider=provider,
        registry=registry,
        context=context,
        max_steps=max_steps,
    )
    return await loop.run(initial_messages)


# Allow ``await`` users to keep the module importable in async contexts.
async def _identity(value: Any) -> Any:  # pragma: no cover - convenience
    if inspect.isawaitable(value):
        return await value
    return value
