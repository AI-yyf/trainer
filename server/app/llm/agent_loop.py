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
import math
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, NoReturn, cast

from .harness import (
    DEFAULT_TOOL_OUTPUT_LIMIT,
    OVERFLOW_KEEP_RECENT_TOKENS,
    append_steering_messages,
    compact_history,
    drain_steering_messages,
    format_tool_result_for_llm,
    is_prompt_too_long_error,
    is_truncated_stop,
    prepare_next_turn,
    prune_older_tool_results,
    split_tool_result_channels,
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
from .reply_continuity import closing_action_step, visible_next_step
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
    usage: dict[str, Any] | None = None


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
    usage: dict[str, Any] | None = None


class AgentLoopError(RuntimeError):
    """Raised when the agent loop cannot make any progress."""


class ProviderStreamStalledError(asyncio.TimeoutError):
    """No provider event arrived for the idle budget: the stream is dead, not slow.

    A timeout (it is handled like a step timeout), but distinct so the turn can say "stalled"
    instead of "exceeded its budget".
    """

    def __init__(self, idle_seconds: float | None) -> None:
        super().__init__(f"no provider event for {idle_seconds:g}s" if idle_seconds else "stalled")
        self.idle_seconds = idle_seconds


class FirstOutputBudgetExceeded(Exception):
    """A step produced nothing within the first-output budget while the learner had seen no text.

    Reasoning-first models stream hidden reasoning for as long as they like: one measured turn
    spent 65 s on 1,317 reasoning tokens before its first tool call, another 18.5 s before the
    answer that followed its tool calls (2026-11-28). A step's wall clock allows that; the learner,
    who is still waiting for a first word, should not have to.
    """

    def __init__(self, budget_seconds: float) -> None:
        super().__init__(f"no learner-visible output for {budget_seconds:g}s")
        self.budget_seconds = budget_seconds


# Appended to the last system message of the retried first step only (never stored in the history
# the later steps or the session see).
FIRST_OUTPUT_RESTART_HINT = (
    "The previous attempt for this turn was stopped because it produced nothing for the learner "
    "within {budget:g} seconds. Do not deliberate further: give your reply now, or make the tool "
    "call you need now, and keep the reply short."
)


def _messages_with_restart_hint(
    messages: list[dict[str, Any]], budget_seconds: float
) -> list[dict[str, Any]]:
    """A copy of ``messages`` whose last system message carries the restart hint."""

    hinted = [dict(message) for message in messages]
    for index in range(len(hinted) - 1, -1, -1):
        message = hinted[index]
        if str(message.get("role") or "") not in {"system", "control"}:
            continue
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        hint = FIRST_OUTPUT_RESTART_HINT.format(budget=budget_seconds)
        hinted[index] = {**message, "content": f"{text}\n\n{hint}" if text.strip() else hint}
        return hinted
    return [{"role": "system", "content": FIRST_OUTPUT_RESTART_HINT.format(budget=budget_seconds)}, *hinted]


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
    *,
    step_timeout: float | None = None,
    idle_timeout: float | None = None,
    first_output_budget: float | None = None,
    has_output: Callable[[], bool] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield provider events while cancellation, step timeouts, stalls and the first-output
    budget close the upstream iterator.

    ``step_timeout`` bounds the whole step. ``idle_timeout`` bounds the gap between two provider
    events: a stream silent for that long is dead, not slow, and is reported as a stall even when
    the step's own budget would still allow it. ``first_output_budget`` bounds the time before
    ``has_output()`` first turns true (learner-visible text or a finished model message); after
    that the step is bound only by its own timeouts.
    """

    iterator = stream.__aiter__()
    iterator_closed = False
    iterator_exhausted = False
    loop = asyncio.get_running_loop()
    started = loop.time()
    deadline = (
        started + step_timeout
        if step_timeout is not None and step_timeout > 0
        else None
    )
    idle_seconds = float(idle_timeout) if idle_timeout is not None and idle_timeout > 0 else None
    idle_deadline = started + idle_seconds if idle_seconds is not None else None
    output_deadline = (
        started + first_output_budget
        if first_output_budget is not None and first_output_budget > 0 and has_output is not None
        else None
    )

    async def close_iterator() -> None:
        nonlocal iterator_closed
        if iterator_closed or iterator_exhausted:
            return
        iterator_closed = True
        close = getattr(iterator, "aclose", None)
        if close is not None:
            try:
                await close()
            except RuntimeError as exc:
                if "asynchronous generator is already running" not in str(exc):
                    raise

    def waiting_for_output() -> bool:
        assert has_output is not None and output_deadline is not None
        return not has_output()

    def remaining() -> float | None:
        now = loop.time()
        bounds = [
            bound - now
            for bound, active in (
                (deadline, True),
                (idle_deadline, True),
                (output_deadline, output_deadline is not None and waiting_for_output()),
            )
            if active and bound is not None
        ]
        return min(bounds) if bounds else None

    async def fail_closed(budget: float | None) -> NoReturn:
        # Close the upstream stream first, then say which budget ended the step.
        await close_iterator()
        now = loop.time()
        if (
            output_deadline is not None
            and first_output_budget is not None
            and waiting_for_output()
            and now >= output_deadline
        ):
            raise FirstOutputBudgetExceeded(float(first_output_budget))
        if idle_deadline is not None and now >= idle_deadline:
            raise ProviderStreamStalledError(idle_seconds)
        raise asyncio.TimeoutError

    try:
        while True:
            left = remaining()
            if left is not None and left <= 0:
                await fail_closed(left)
            if cancel_event is None:
                try:
                    if left is None:
                        item = await iterator.__anext__()
                    else:
                        item = await asyncio.wait_for(iterator.__anext__(), timeout=left)
                except StopAsyncIteration:
                    iterator_exhausted = True
                    return
                except asyncio.TimeoutError:
                    await fail_closed(left)
                if idle_deadline is not None:
                    assert idle_seconds is not None
                    idle_deadline = loop.time() + idle_seconds
                yield item
                continue
            if cancel_event.is_set():
                await close_iterator()
                raise asyncio.CancelledError
            next_event = asyncio.ensure_future(iterator.__anext__())
            cancellation = asyncio.create_task(cancel_event.wait())
            try:
                done, _ = await asyncio.wait(
                    {next_event, cancellation},
                    timeout=left,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    next_event.cancel()
                    await asyncio.gather(next_event, return_exceptions=True)
                    await fail_closed(left)
                if cancellation in done and cancel_event.is_set():
                    next_event.cancel()
                    await asyncio.gather(next_event, return_exceptions=True)
                    await close_iterator()
                    raise asyncio.CancelledError
                try:
                    item = next_event.result()
                except StopAsyncIteration:
                    iterator_exhausted = True
                    return
                if idle_deadline is not None:
                    assert idle_seconds is not None
                    idle_deadline = loop.time() + idle_seconds
                yield item
            finally:
                if not cancellation.done():
                    cancellation.cancel()
                await asyncio.gather(cancellation, return_exceptions=True)
    finally:
        await close_iterator()


@dataclass
class AgentProvider:
    protocol: str
    call: ProviderHookCall
    call_stream: ProviderHookStream | None = None
    # The loop awaits provider calls in child tasks. Keep safe transport facts
    # on this per-turn provider, because ContextVar writes do not return to the
    # caller across that task boundary.
    last_failure: dict[str, Any] | None = None


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
    # A stream silent this long between two events is dead. Generous, because a reasoning-first
    # model may legitimately send nothing while it thinks; it only shortens how long a truly dead
    # first step takes to be noticed (the step's own budget is 90 s).
    DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS = 60.0
    # Until the learner has seen the first visible text of a turn, every step must produce something
    # (text or a tool call) within this time. A reasoning model that is still deliberating gets one
    # fresh attempt per turn with an explicit instruction to stop deliberating. 0 disables the
    # restart. The second attempt is not unbounded: on a reasoning-first gateway steps carry no wall
    # clock at all, so the restarted step is capped here.
    DEFAULT_FIRST_OUTPUT_RESTART_SECONDS = 20.0
    SECOND_ATTEMPT_MAX_SECONDS = 120.0
    MIN_AUX_TIMEOUT_SECONDS = 5.0
    # Reasoning-first gateways can spend several minutes on a single step
    # before the first visible token, so the clamp must sit above the
    # generous kimi-like tier rather than below it.
    MAX_STEP_TIMEOUT_SECONDS = 300.0

    def __init__(
        self,
        *,
        provider: AgentProvider,
        registry: ToolRegistry,
        context: ToolContext,
        max_steps: int | None = None,
        step_timeout: float | None = None,
        first_step_timeout: float | None = None,
        stream_idle_timeout: float | None = None,
        first_output_restart_seconds: float | None = None,
    ) -> None:
        self.provider = provider
        self.stream_idle_timeout = self._bounded_aux_timeout(
            self.DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS
            if stream_idle_timeout is None
            else stream_idle_timeout
        )
        self.first_output_restart_seconds = self._bounded_aux_timeout(
            self.DEFAULT_FIRST_OUTPUT_RESTART_SECONDS
            if first_output_restart_seconds is None
            else first_output_restart_seconds
        )
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
        self._formal_plan_commit_retries = 0
        self._last_provider_input_tokens: int | None = None
        self._accumulated_usage: dict[str, Any] = {}

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
            step_usage = self._record_step_usage(response.get("usage"))
            provider_reasoning = (
                response.get("provider_reasoning")
                if isinstance(response.get("provider_reasoning"), dict)
                else None
            )
            step = AgentStep(
                index=index,
                assistant_content=assistant_text,
                tool_calls=tool_calls,
                usage=step_usage,
            )
            steps.append(step)

            history.append(
                _assistant_message(
                    assistant_text,
                    tool_calls,
                    provider_reasoning=provider_reasoning,
                )
            )

            if not tool_calls:
                if assistant_text.strip() and self._continue_required_plan_save(history, steps):
                    step.stop_reason = "formal_plan_save_pending"
                    self._prepare_next_turn(history)
                    index += 1
                    continue
                if not assistant_text.strip():
                    step.stop_reason = "empty_response"
                    summary, next_step = _build_empty_response_recovery(
                        context=self.context,
                        response_language=self.context.response_language,
                        executed_steps=steps[:-1],
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
                if self._continue_required_plan_save(history, steps, finalize_data):
                    step.stop_reason = "formal_plan_save_pending"
                    self._prepare_next_turn(history)
                    index += 1
                    continue
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
        overflow_retries = 0
        previous_step: AgentStep | None = None
        streamed_steps: list[AgentStep] = []
        index = 0
        restart_step: int | None = None  # the step that was restarted in this turn, if any
        restart_hint_budget = 0.0
        turn_showed_text = False

        def _has_output() -> bool:
            # Late bound on purpose: read the current step's accumulators.
            return provider_final_received or bool(streamed_text)

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
            stream_provider_reasoning: dict[str, Any] | None = None
            provider_final_received = False
            step_timeout = self._step_timeout_for(index)
            if restart_step == index:
                step_timeout = min(step_timeout, self.SECOND_ATTEMPT_MAX_SECONDS)
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
                # The retried step carries the restart hint; history itself never does.
                step_messages = (
                    _messages_with_restart_hint(history, restart_hint_budget)
                    if restart_step == index
                    else history
                )
                first_output_budget = (
                    self.first_output_restart_seconds
                    if restart_step is None and not turn_showed_text
                    else None
                )
                try:
                    async for event in _iterate_with_stream_cancellation(
                        stream_fn(step_messages, tools_schema),
                        cancel_event,
                        step_timeout=step_timeout,
                        idle_timeout=self.stream_idle_timeout,
                        first_output_budget=first_output_budget,
                        has_output=_has_output,
                    ):
                        if provider_final_received:
                            continue
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
                            tool_calls = list(
                                cast("list[dict[str, Any]]", event.get("tool_calls") or [])
                            )
                            self._record_step_usage(event.get("usage"))
                            raw_stop = event.get("stop_reason") or event.get("finish_reason")
                            stream_stop_reason = str(raw_stop) if raw_stop else None
                            raw_reasoning = event.get("provider_reasoning")
                            if isinstance(raw_reasoning, dict):
                                stream_provider_reasoning = {
                                    str(k): v for k, v in raw_reasoning.items()
                                }
                            provider_final_received = True
                        else:
                            yield event
                except FirstOutputBudgetExceeded as exc:
                    # The learner is still waiting for a first word and the model is still
                    # deliberating: drop the attempt and ask once more, this time with an
                    # instruction to stop deliberating. Once per turn.
                    restart_step = index
                    restart_hint_budget = exc.budget_seconds
                    logger.info(
                        "agent_stream_first_output_restart",
                        extra={"step": index, "budget_seconds": exc.budget_seconds},
                    )
                    yield {
                        "type": "stream_restart",
                        "reason": "first_output_budget",
                        "after_seconds": exc.budget_seconds,
                    }
                    continue
                except asyncio.TimeoutError as exc:
                    summary, next_step = _build_runtime_failure_recovery(
                        "timeout",
                        context=self.context,
                        response_language=self.context.response_language,
                        previous_step=previous_step,
                    )
                    stalled = isinstance(exc, ProviderStreamStalledError)
                    yield {
                        "type": "final",
                        "content": assistant_text or _visible_text_from_steps(streamed_steps, summary, next_step),
                        "summary": summary,
                        "next_step": next_step,
                        "stop_reason": "timeout",
                        "error": (
                            f"agent step {index} stalled: {exc}"
                            if stalled
                            else f"agent step {index} exceeded {step_timeout}s"
                        ),
                        "stalled": stalled,
                    }
                    return
                except Exception as exc:
                    if is_prompt_too_long_error(exc) and overflow_retries < 2:
                        overflow_retries += 1
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
                        "error": redact_provider_error(exc),
                    }
                    return

            turn_showed_text = turn_showed_text or bool(streamed_text)
            history.append(
                _assistant_message(
                    assistant_text,
                    tool_calls,
                    provider_reasoning=stream_provider_reasoning,
                )
            )

            if not tool_calls:
                if assistant_text.strip() and self._continue_required_plan_save(history, streamed_steps):
                    step = AgentStep(index=index, assistant_content=assistant_text,
                                     stop_reason="formal_plan_save_pending")
                    streamed_steps.append(step)
                    previous_step = step
                    self._prepare_next_turn(history)
                    index += 1
                    continue
                if not assistant_text.strip():
                    summary, next_step = _build_empty_response_recovery(
                        context=self.context,
                        response_language=self.context.response_language,
                        executed_steps=streamed_steps,
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
                if not streamed_text:
                    missing_text = assistant_text
                elif assistant_text.startswith(streamed_text):
                    missing_text = assistant_text[len(streamed_text) :]
                else:
                    # A provider may normalize whitespace/punctuation on text
                    # already streamed. Never duplicate the entire reply; only
                    # emit a genuine unstreamed suffix if present.
                    stripped_streamed = streamed_text.strip()
                    stripped_final = assistant_text.strip()
                    if stripped_streamed and stripped_final.startswith(stripped_streamed):
                        idx = assistant_text.find(stripped_streamed)
                        missing_text = (
                            assistant_text[idx + len(stripped_streamed) :]
                            if idx >= 0
                            else ""
                        )
                    else:
                        missing_text = ""
                if missing_text:
                    if stream_direct_text:
                        yield {"type": "text", "delta": missing_text}
                    else:
                        event: dict[str, object] = {"type": "text", "delta": missing_text}
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
                if self._continue_required_plan_save(history, streamed_steps + [step], finalize_data):
                    step.stop_reason = "formal_plan_save_pending"
                    streamed_steps.append(step)
                    previous_step = step
                    self._prepare_next_turn(history)
                    index += 1
                    continue
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

    def _continue_required_plan_save(
        self,
        history: list[dict[str, Any]],
        steps: list[AgentStep],
        finalize: dict[str, Any] | None = None,
    ) -> bool:
        """Give an authorized, incomplete save one bounded model repair turn."""
        if self._extra().get("formal_plan_mutation") is not True or self._formal_plan_commit_retries:
            return False
        exposed_schemas = self._tools_schema()
        learning_action_tool = self.registry.get("learning_action")
        legacy_save_tool = self.registry.get("save_formal_plan")
        uses_orthogonal = (
            learning_action_tool is not None
            and learning_action_tool.schema_for(self.provider.protocol) in exposed_schemas
        )
        uses_legacy = (
            not uses_orthogonal
            and legacy_save_tool is not None
            and legacy_save_tool.schema_for(self.provider.protocol) in exposed_schemas
        )
        if not uses_orthogonal and not uses_legacy:
            return False
        if finalize and (finalize.get("blocker") or finalize.get("decision") == "blocked"):
            return False
        for step in steps:
            for event in step.tool_results:
                result = event.get("result")
                event_name = str(event.get("name") or "").strip()
                if (
                    event_name in {"learning_action", "save_formal_plan"}
                    and isinstance(result, dict)
                    and result.get("ok") is True
                    and result.get("committed") is True
                    and (
                        event_name == "save_formal_plan"
                        or str(result.get("action") or "save_formal_plan").strip().lower()
                        == "save_formal_plan"
                    )
                ):
                    return False
        self._formal_plan_commit_retries += 1
        commit_call_text = (
            "learning_action(action='save_formal_plan', ...)"
            if uses_orthogonal
            else "save_formal_plan"
        )
        history.append({
            "role": "control",
            "_harness_control": True,
            "content": (
                "<system-reminder>\n"
                "The explicitly requested formal plan save is still pending. A text draft "
                "does not commit this turn. Re-read the latest learner request; "
                "its corrections take priority over older plan, memory and verification summaries. "
                "Preserve its plan identity, stage count, stage statuses and unexecuted work. "
                f"Call {commit_call_text} with the plan you shaped, then inspect its result. "
                "Do not invent test counts or claim a save before ok=true and committed=true. "
                "If a concrete requirement prevents saving, state the exact blocker clearly "
                "and ask one concise question without claiming the plan was saved. "
                "Do not retry indefinitely.\n"
                "</system-reminder>"
            ),
        })
        return True

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
            explicit_lecture_note_save_request=extra.get("explicit_lecture_note_save_request") is True,
            explicit_resource_import=extra.get("explicit_resource_import") is True,
            explicit_resource_organize=extra.get("explicit_resource_organize") is True,
            live_formal_plan_for_task_mint=extra.get("live_formal_plan_for_task_mint") is True,
            stabilize_orthogonal_schema=extra.get("stabilize_orthogonal_schema", True) is not False,
        )

    @classmethod
    def _bounded_step_timeout(cls, timeout: float) -> float:
        # math.inf is the explicit "no designed wall-clock for reasoning"
        # marker: reasoning-first gateways think for as long as the task
        # needs, and every fixed tier measured as a false timeout.
        if timeout == math.inf:
            return math.inf
        return min(
            cls.MAX_STEP_TIMEOUT_SECONDS,
            max(cls.MIN_STEP_TIMEOUT_SECONDS, float(timeout)),
        )

    def _step_timeout_for(self, index: int) -> float:
        return self.first_step_timeout if index == 0 else self.step_timeout

    @classmethod
    def _bounded_aux_timeout(cls, timeout: float) -> float:
        # 0 switches the guard off; anything else stays within [5 s, 5 min].
        if timeout <= 0:
            return 0.0
        return min(cls.MAX_STEP_TIMEOUT_SECONDS, max(cls.MIN_AUX_TIMEOUT_SECONDS, float(timeout)))

    def _extra(self) -> dict[str, Any]:
        extra = self.context.extra if isinstance(self.context.extra, dict) else {}
        return extra

    def _record_step_usage(self, raw_usage: object) -> dict[str, Any] | None:
        if not isinstance(raw_usage, dict):
            return None
        in_tok = raw_usage.get("input_tokens")
        if isinstance(in_tok, int) and in_tok > 0:
            self._last_provider_input_tokens = in_tok
        for key in (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "total_tokens",
        ):
            val = raw_usage.get(key)
            if isinstance(val, int) and val >= 0:
                self._accumulated_usage[key] = int(self._accumulated_usage.get(key) or 0) + val
        cost = raw_usage.get("total_cost")
        if isinstance(cost, (int, float)) and cost >= 0:
            self._accumulated_usage["total_cost"] = float(self._accumulated_usage.get("total_cost") or 0.0) + float(cost)
        extra = self.context.extra
        if isinstance(extra, dict) and self._accumulated_usage:
            extra["_last_provider_usage"] = dict(self._accumulated_usage)
        return dict(raw_usage)

    def _prepare_next_turn(self, history: list[dict[str, Any]]) -> None:
        steered = drain_steering_messages(self.context)
        append_steering_messages(history, steered)
        prepare_next_turn(
            history,
            extra=self._extra(),
            history_char_budget=self.MAX_TURN_HISTORY_CHARS,
            last_provider_input_tokens=self._last_provider_input_tokens,
        )

    async def _call_provider(
        self,
        history: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]],
        timeout: float,
    ) -> dict[str, Any]:
        # math.inf means "no designed wall-clock for reasoning": wait_for(None)
        # waits without a timer while transport errors still surface.
        wait_timeout = None if timeout == math.inf else timeout
        try:
            return await asyncio.wait_for(
                self.provider.call(history, tools_schema), timeout=wait_timeout
            )
        except Exception as exc:
            if not is_prompt_too_long_error(exc):
                raise
            compact_history(
                history,
                extra=self._extra(),
                keep_recent_tokens=OVERFLOW_KEEP_RECENT_TOKENS,
                reason="overflow",
                force=True,
                last_provider_input_tokens=self._last_provider_input_tokens,
            )
            prune_older_tool_results(history, history_char_budget=40_000)
            return await asyncio.wait_for(
                self.provider.call(history, tools_schema), timeout=wait_timeout
            )

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
            for tool_id, tool_name, arguments, tool_result in invoked:
                llm_content, ui_details = split_tool_result_channels(tool_name, tool_result)
                events.append(
                    {
                        "type": "tool_result",
                        "id": tool_id,
                        "name": tool_name,
                        "ok": bool(ui_details.get("ok")) if isinstance(ui_details, dict) else True,
                        "result": ui_details,
                    }
                )
                step.tool_results.append(
                    {"id": tool_id, "name": tool_name, "arguments": arguments, "result": ui_details}
                )
                history.append(_tool_message(tool_id, tool_name, llm_content))
            return None, None, events

        finalize_payload: dict[str, Any] | None = None
        finalize_arguments: Any = None
        for call_idx, call in enumerate(tool_calls):
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
            llm_content, ui_details = split_tool_result_channels(tool_name, tool_result)
            events.append(
                {
                    "type": "tool_result",
                    "id": tool_id,
                    "name": tool_name,
                    "ok": bool(ui_details.get("ok")) if isinstance(ui_details, dict) else True,
                    "result": ui_details,
                }
            )
            step.tool_results.append(
                {"id": tool_id, "name": tool_name, "arguments": arguments, "result": ui_details}
            )
            history.append(_tool_message(tool_id, tool_name, llm_content))
            if tool_name == "coach_finalize" and isinstance(ui_details, dict) and ui_details.get("final"):
                finalize_payload = ui_details
                finalize_arguments = arguments
                for skipped in tool_calls[call_idx + 1 :]:
                    skipped_name = str(skipped.get("name") or "")
                    skipped_id = str(skipped.get("id") or skipped_name)
                    skipped_result = {
                        "ok": False,
                        "skipped": True,
                        "detail": "Skipped because coach_finalize ran earlier in the same batch.",
                    }
                    history.append(_tool_message(skipped_id, skipped_name, skipped_result))
                break
            mid_steered = drain_steering_messages(self.context)
            if mid_steered:
                for skipped in tool_calls[call_idx + 1 :]:
                    skipped_name = str(skipped.get("name") or "")
                    skipped_id = str(skipped.get("id") or skipped_name)
                    skipped_result = {
                        "ok": False,
                        "skipped": True,
                        "detail": "Skipped because the learner sent a steering message.",
                    }
                    events.append(
                        {
                            "type": "tool_result",
                            "id": skipped_id,
                            "name": skipped_name,
                            "ok": False,
                            "result": skipped_result,
                        }
                    )
                    step.tool_results.append(
                        {
                            "id": skipped_id,
                            "name": skipped_name,
                            "arguments": skipped.get("arguments"),
                            "result": skipped_result,
                        }
                    )
                    history.append(_tool_message(skipped_id, skipped_name, skipped_result))
                append_steering_messages(history, mid_steered)
                break
        return finalize_payload, finalize_arguments, events

def _assistant_message(
    content: str,
    tool_calls: list[dict[str, Any]],
    *,
    provider_reasoning: dict[str, Any] | None = None,
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
    if provider_reasoning:
        message["_provider_reasoning"] = dict(provider_reasoning)
    return message


def _truncate_tool_payload(content_text: str, *, limit: int) -> str:
    text = str(content_text or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit)] + "\n…[truncated]"


def _tool_message(call_id: str, name: str, result: Any) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": format_tool_result_for_llm(name, result),
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


def _normalize_loop_locale(response_language: str | None) -> str:
    raw = str(response_language or "").strip().lower().replace("_", "-")
    if raw.startswith("zh"):
        return "zh-CN"
    if raw.startswith("es"):
        return "es-ES"
    if raw.startswith("fr"):
        return "fr-FR"
    if raw.startswith("de"):
        return "de-DE"
    if raw.startswith("ja"):
        return "ja-JP"
    if raw.startswith("ko"):
        return "ko-KR"
    if raw.startswith("pt"):
        return "pt-BR"
    return "en-US"


_BLOCKER_PREFIX_BY_LOCALE: dict[str, str] = {
    "zh-CN": "\u5f53\u524d\u963b\u585e\uff1a",
    "en-US": "Current blocker: ",
    "es-ES": "Bloqueo actual: ",
    "fr-FR": "Blocage actuel : ",
    "de-DE": "Aktueller Blocker: ",
    "ja-JP": "\u73fe\u5728\u306e\u30d6\u30ed\u30c3\u30ab\u30fc: ",
    "ko-KR": "\ud604\uc7ac \ub9c9\ud78c \uc9c0\uc810: ",
    "pt-BR": "Bloqueio atual: ",
}


def _visible_coach_finalize_reply(
    payload: dict[str, Any],
    *,
    response_language: str | None,
) -> str:
    """Turn verified finalize metadata into a compact learner-facing close.

    The next step intentionally stays out of the body: it reaches the learner
    through the reply's icon strip (agent_meta.next_step), keeping the reply
    text to the coach's own words.
    """
    locale = _normalize_loop_locale(response_language)
    blocker_label = _BLOCKER_PREFIX_BY_LOCALE.get(locale, _BLOCKER_PREFIX_BY_LOCALE["en-US"])
    parts: list[str] = []

    for key in ("summary", "decision", "teaching_note"):
        value = str(payload.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)

    blocker = str(payload.get("blocker") or "").strip()
    if blocker:
        parts.append(f"{blocker_label}{blocker}")

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


_NO_PROGRESS_COPY: dict[str, dict[str, str]] = {
    "zh-CN": {
        "summary_base": "模型重复了相同的工具路径{suffix}，但没有带来新的证据。",
        "summary_suffix": "：{tool_path}",
        "focus": " 当前应该回到：{focus_note}。",
        "failure": " 上一次还卡在：{failure_note}。",
        "next_plain": "换一个证据来源，或者先把问题收窄，再继续同样的工具路径。",
        "next_tool": "先换一个证据来源，或者收窄问题，再重新评估是否要继续 `{tool_path}`。",
        "return_to": " 也可以先回到 {next_step_note}。",
        "fix_first": " 先修掉 `{failure_note}` 对应的问题。",
    },
    "en-US": {
        "summary_base": "The model repeated the same tool path{suffix} without new evidence.",
        "summary_suffix": ": {tool_path}",
        "focus": " The turn should stay anchored to {focus_note}.",
        "failure": " The last attempt was already stuck on: {failure_note}.",
        "next_plain": "Switch evidence sources or narrow the question before trying the same tool path again.",
        "next_tool": "Try a different evidence source, then decide whether `{tool_path}` is still the right path.",
        "return_to": " Or return to {next_step_note}.",
        "fix_first": " Fix the issue tied to `{failure_note}` first.",
    },
    "es-ES": {
        "summary_base": "El modelo repitió la misma ruta de herramientas{suffix} sin aportar nueva evidencia.",
        "summary_suffix": ": {tool_path}",
        "focus": " Este turno debe seguir anclado en {focus_note}.",
        "failure": " El intento anterior quedó bloqueado en: {failure_note}.",
        "next_plain": "Cambia de fuente de evidencia o acota la pregunta antes de repetir la misma ruta de herramientas.",
        "next_tool": "Prueba otra fuente de evidencia y decide si `{tool_path}` sigue siendo la ruta adecuada.",
        "return_to": " O vuelve a {next_step_note}.",
        "fix_first": " Resuelve primero el problema asociado a `{failure_note}`.",
    },
    "fr-FR": {
        "summary_base": "Le modèle a répété le même enchaînement d'outils{suffix} sans apporter de nouvelle preuve.",
        "summary_suffix": " : {tool_path}",
        "focus": " Cet échange doit rester ancré sur {focus_note}.",
        "failure": " La tentative précédente bloquait déjà sur : {failure_note}.",
        "next_plain": "Change de source de preuve ou resserre la question avant de relancer le même parcours d'outils.",
        "next_tool": "Essaie une autre source de preuve, puis vérifie si `{tool_path}` reste la bonne piste.",
        "return_to": " Ou reviens à {next_step_note}.",
        "fix_first": " Corrige d'abord le problème lié à `{failure_note}`.",
    },
    "de-DE": {
        "summary_base": "Das Modell hat denselben Werkzeugpfad{suffix} ohne neue Belege wiederholt.",
        "summary_suffix": ": {tool_path}",
        "focus": " Die Runde sollte auf {focus_note} ausgerichtet bleiben.",
        "failure": " Der letzte Versuch hing bereits an: {failure_note}.",
        "next_plain": "Wechsle die Belegquelle oder grenze die Frage enger ein, bevor du denselben Werkzeugpfad wiederholst.",
        "next_tool": "Nutze eine andere Belegquelle und prüfe dann, ob `{tool_path}` noch der richtige Weg ist.",
        "return_to": " Oder kehre zu {next_step_note} zurück.",
        "fix_first": " Behebe zuerst das Problem rund um `{failure_note}`.",
    },
    "ja-JP": {
        "summary_base": "モデルが新しい根拠を得られないまま同じツール経路{suffix}を繰り返しました。",
        "summary_suffix": "（{tool_path}）",
        "focus": " 現在の焦点は {focus_note} に保ってください。",
        "failure": " 前回の詰まり箇所: {failure_note}。",
        "next_plain": "別の根拠ソースに切り替えるか、論点を絞ってから同じツール経路を再試行してください。",
        "next_tool": "別の根拠ソースを試し、`{tool_path}` を続けるべきか見直してください。",
        "return_to": " または {next_step_note} に戻ってください。",
        "fix_first": " まず `{failure_note}` に関連する問題を修正してください。",
    },
    "ko-KR": {
        "summary_base": "모델이 새로운 근거 없이 동일한 도구 경로{suffix}를 반복했습니다.",
        "summary_suffix": "({tool_path})",
        "focus": " 현재 초점은 {focus_note}에 맞춰 유지해야 합니다.",
        "failure": " 이전 시도에서 막힌 지점: {failure_note}.",
        "next_plain": "같은 도구 경로를 다시 시도하기 전에 다른 근거 출처로 전환하거나 질문을 좁혀 주세요.",
        "next_tool": "다른 근거 출처를 시도한 뒤 `{tool_path}`가 여전히 적절한 경로인지 다시 판단하세요.",
        "return_to": " 또는 {next_step_note} 단계로 돌아가세요.",
        "fix_first": " 먼저 `{failure_note}`와 관련된 문제를 해결하세요.",
    },
    "pt-BR": {
        "summary_base": "O modelo repetiu o mesmo caminho de ferramentas{suffix} sem novas evidências.",
        "summary_suffix": ": {tool_path}",
        "focus": " A conversa deve permanecer ancorada em {focus_note}.",
        "failure": " A última tentativa já havia travado em: {failure_note}.",
        "next_plain": "Troque a fonte de evidência ou restrinja a pergunta antes de repetir o mesmo caminho de ferramentas.",
        "next_tool": "Tente outra fonte de evidência e decida se `{tool_path}` ainda é o melhor caminho.",
        "return_to": " Ou volte para {next_step_note}.",
        "fix_first": " Corrija primeiro o problema ligado a `{failure_note}`.",
    },
}

_STEP_LIMIT_COPY: dict[str, dict[str, str]] = {
    "zh-CN": {
        "summary": "模型已经跑到步数上限，但还没有自然收束。",
        "focus": " 当前仍应围绕：{focus_note}。",
        "next_step": "下一轮先从最近一次工具路径继续；如果还是卡住，就换证据来源或缩小问题。",
        "return_to": " 也可以先回到 {next_step_note}。",
        "failure": " 上一轮最接近的卡点是：{failure_note}。",
        "fix_first": " 先修掉 `{failure_note}` 对应的问题。",
    },
    "en-US": {
        "summary": "The model reached the step limit without a natural stop.",
        "focus": " The turn should still be anchored to {focus_note}.",
        "next_step": "Continue from the latest tool path, but switch evidence sources or narrow scope if you are still stuck.",
        "return_to": " Or return to {next_step_note}.",
        "failure": " The closest blocker was: {failure_note}.",
        "fix_first": " Fix the issue tied to `{failure_note}` first.",
    },
    "es-ES": {
        "summary": "El modelo alcanzó el límite de pasos sin cerrar de forma natural.",
        "focus": " El turno debe seguir anclado en {focus_note}.",
        "next_step": "Continúa desde la última ruta de herramientas, pero cambia de fuente o acota el alcance si sigues atascado.",
        "return_to": " O vuelve a {next_step_note}.",
        "failure": " El bloqueo más cercano fue: {failure_note}.",
        "fix_first": " Resuelve primero el problema asociado a `{failure_note}`.",
    },
    "fr-FR": {
        "summary": "Le modèle a atteint la limite d'étapes sans conclure naturellement.",
        "focus": " L'échange doit rester ancré sur {focus_note}.",
        "next_step": "Reprends depuis le dernier outil utilisé, mais change de source de preuve ou réduis la portée si tu restes bloqué.",
        "return_to": " Ou reviens à {next_step_note}.",
        "failure": " Le blocage le plus proche était : {failure_note}.",
        "fix_first": " Corrige d'abord le problème lié à `{failure_note}`.",
    },
    "de-DE": {
        "summary": "Das Modell hat das Schrittlimit ohne natürlichen Abschluss erreicht.",
        "focus": " Die Runde sollte auf {focus_note} verankert bleiben.",
        "next_step": "Setze beim letzten Werkzeugpfad fort, wechsle aber die Belegquelle oder grenze den Umfang ein, wenn es weiter stockt.",
        "return_to": " Oder kehre zu {next_step_note} zurück.",
        "failure": " Der nächste Blocker war: {failure_note}.",
        "fix_first": " Behebe zuerst das Problem rund um `{failure_note}`.",
    },
    "ja-JP": {
        "summary": "モデルが自然な完了に至らないままステップ上限に達しました。",
        "focus": " 論点は引き続き {focus_note} に合わせてください。",
        "next_step": "直近のツール経路から再開し、まだ詰まる場合は根拠ソースを変えるか範囲を狭めてください。",
        "return_to": " または {next_step_note} に戻ってください。",
        "failure": " 直前のブロッカー: {failure_note}。",
        "fix_first": " まず `{failure_note}` に関連する問題を修正してください。",
    },
    "ko-KR": {
        "summary": "모델이 자연스럽게 마무리되지 못한 채 단계 한도에 도달했습니다.",
        "focus": " 대화 초점은 여전히 {focus_note}에 두어야 합니다.",
        "next_step": "최근 도구 경로에서 이어가되, 계속 막히면 근거 출처를 바꾸거나 범위를 좁혀 주세요.",
        "return_to": " 또는 {next_step_note} 단계로 돌아가세요.",
        "failure": " 가장 가까운 막힌 지점: {failure_note}.",
        "fix_first": " 먼저 `{failure_note}`와 관련된 문제를 해결하세요.",
    },
    "pt-BR": {
        "summary": "O modelo atingiu o limite de etapas sem encerrar naturalmente.",
        "focus": " A conversa deve continuar ancorada em {focus_note}.",
        "next_step": "Continue pelo último caminho de ferramentas, mas troque a fonte de evidência ou reduza o escopo se ainda estiver travado.",
        "return_to": " Ou volte para {next_step_note}.",
        "failure": " O bloqueio mais próximo foi: {failure_note}.",
        "fix_first": " Corrija primeiro o problema ligado a `{failure_note}`.",
    },
}

_RUNTIME_FAILURE_COPY: dict[str, dict[str, str]] = {
    "zh-CN": {
        "timeout_summary": "这一轮工具调用超时了，还没来得及自然收束。",
        "timeout_next": "先回到最近的证据，再缩小问题或换一个更快的检查。",
        "error_summary": "这一轮教练服务在中途断开了，但我们可以沿着同一条主线续回去。",
        "error_next": "先检查 provider 或连接状态，再继续最小的下一步。",
        "focus": " 当前主线还是：{focus_note}。",
        "failure": " 上一轮最接近的卡点是：{failure_note}。",
        "return_to": " 也可以先回到 {next_step_note}。",
    },
    "en-US": {
        "timeout_summary": "This turn timed out before the provider could finish.",
        "timeout_next": "Re-anchor on the latest evidence and retry the smallest check.",
        "error_summary": "The provider stopped mid-turn, but the thread can still resume.",
        "error_next": "Check the provider connection, then retry the smallest anchored step.",
        "focus": " Stay anchored to {focus_note}.",
        "failure": " The closest blocker was: {failure_note}.",
        "return_to": " Or return to {next_step_note}.",
    },
    "es-ES": {
        "timeout_summary": "Este turno superó el tiempo de espera antes de que el proveedor terminara.",
        "timeout_next": "Vuelve a apoyarte en la evidencia más reciente y reintenta la comprobación más pequeña.",
        "error_summary": "El proveedor se detuvo a mitad del turno, pero el hilo aún puede continuar.",
        "error_next": "Revisa la conexión del proveedor y vuelve a intentar el paso anclado más pequeño.",
        "focus": " Mantén el foco en {focus_note}.",
        "failure": " El bloqueo más cercano fue: {failure_note}.",
        "return_to": " O vuelve a {next_step_note}.",
    },
    "fr-FR": {
        "timeout_summary": "Ce tour a expiré avant que le fournisseur puisse terminer.",
        "timeout_next": "Appuie-toi sur la preuve la plus récente et relance la plus petite vérification.",
        "error_summary": "Le fournisseur s'est interrompu en cours de tour, mais le fil peut reprendre.",
        "error_next": "Vérifie la connexion du fournisseur, puis relance la plus petite étape ciblée.",
        "focus": " Reste ancré sur {focus_note}.",
        "failure": " Le blocage le plus proche était : {failure_note}.",
        "return_to": " Ou reviens à {next_step_note}.",
    },
    "de-DE": {
        "timeout_summary": "Diese Runde hat das Zeitlimit überschritten, bevor der Anbieter fertig war.",
        "timeout_next": "Orientiere dich am letzten Beleg und wiederhole die kleinste Prüfung.",
        "error_summary": "Der Anbieter wurde mitten in der Runde unterbrochen, aber der Faden lässt sich fortsetzen.",
        "error_next": "Prüfe die Anbieterverbindung und wiederhole dann den kleinsten verankerten Schritt.",
        "focus": " Bleibe bei {focus_note}.",
        "failure": " Der nächste Blocker war: {failure_note}.",
        "return_to": " Oder kehre zu {next_step_note} zurück.",
    },
    "ja-JP": {
        "timeout_summary": "プロバイダーが完了する前にこのターンがタイムアウトしました。",
        "timeout_next": "最新の根拠に戻り、最小の確認を再試行してください。",
        "error_summary": "プロバイダーが途中で停止しましたが、同じ流れから再開できます。",
        "error_next": "プロバイダーの接続状態を確認し、最小の次の一歩を再試行してください。",
        "focus": " 引き続き {focus_note} に焦点を合わせてください。",
        "failure": " 直前のブロッカー: {failure_note}。",
        "return_to": " または {next_step_note} に戻ってください。",
    },
    "ko-KR": {
        "timeout_summary": "공급자가 완료하기 전에 이 턴의 제한 시간이 초과되었습니다.",
        "timeout_next": "가장 최근 근거를 기준으로 가장 작은 점검부터 다시 시도하세요.",
        "error_summary": "공급자가 턴 중간에 중단되었지만, 같은 흐름에서 다시 이어갈 수 있습니다.",
        "error_next": "공급자 연결 상태를 확인한 뒤 가장 작은 다음 단계를 다시 시도하세요.",
        "focus": " 계속 {focus_note}에 초점을 맞추세요.",
        "failure": " 가장 가까운 막힌 지점: {failure_note}.",
        "return_to": " 또는 {next_step_note} 단계로 돌아가세요.",
    },
    "pt-BR": {
        "timeout_summary": "Este turno atingiu o tempo limite antes de o provedor concluir.",
        "timeout_next": "Reancore na evidência mais recente e tente novamente a menor verificação.",
        "error_summary": "O provedor parou no meio do turno, mas a conversa ainda pode continuar.",
        "error_next": "Verifique a conexão do provedor e tente novamente o menor passo ancorado.",
        "focus": " Mantenha o foco em {focus_note}.",
        "failure": " O bloqueio mais próximo foi: {failure_note}.",
        "return_to": " Ou volte para {next_step_note}.",
    },
}

_EMPTY_RESPONSE_COPY: dict[str, dict[str, str]] = {
    "zh-CN": {
        "summary": "模型返回了空内容，所以这轮不能算完成。",
        "focus": " 当前主线仍然是：{focus_note}。",
        "tools": " 已执行的检查：{tools}。",
        "next_step": "重新发起这一轮，但要求模型给出可见结论；如果再次为空，就先切回最小可验证动作。",
        "return_to": " 也可以先回到 {next_step_note}。",
    },
    "en-US": {
        "summary": "The provider returned an empty visible answer, so this turn cannot be treated as complete.",
        "focus": " The thread should stay anchored to {focus_note}.",
        "tools": " Completed checks: {tools}.",
        "next_step": "Retry the turn and require a visible conclusion; if it repeats, fall back to the smallest verifiable move.",
        "return_to": " Or return to {next_step_note}.",
    },
    "es-ES": {
        "summary": "El proveedor devolvió una respuesta visible vacía, por lo que este turno no puede darse por terminado.",
        "focus": " El hilo debe seguir anclado en {focus_note}.",
        "tools": " Comprobaciones ejecutadas: {tools}.",
        "next_step": "Reintenta el turno pidiendo una conclusión visible; si se repite, vuelve al paso verificable más pequeño.",
        "return_to": " O vuelve a {next_step_note}.",
    },
    "fr-FR": {
        "summary": "Le fournisseur a renvoyé une réponse visible vide ; ce tour ne peut donc pas être considéré comme terminé.",
        "focus": " Le fil doit rester ancré sur {focus_note}.",
        "tools": " Vérifications exécutées : {tools}.",
        "next_step": "Relance le tour en demandant une conclusion visible ; si cela se répète, reviens au plus petit geste vérifiable.",
        "return_to": " Ou reviens à {next_step_note}.",
    },
    "de-DE": {
        "summary": "Der Anbieter hat eine leere sichtbare Antwort geliefert, daher gilt diese Runde nicht als abgeschlossen.",
        "focus": " Der Faden sollte auf {focus_note} verankert bleiben.",
        "tools": " Ausgeführte Prüfungen: {tools}.",
        "next_step": "Wiederhole die Runde und verlange ein sichtbares Ergebnis; falls es sich wiederholt, geh zum kleinsten prüfbaren Schritt zurück.",
        "return_to": " Oder kehre zu {next_step_note} zurück.",
    },
    "ja-JP": {
        "summary": "プロバイダーが空の応答を返したため、このターンは完了とみなせません。",
        "focus": " スレッドの軸は引き続き {focus_note} に保ってください。",
        "tools": " 実行済みの確認: {tools}。",
        "next_step": "目に見える結論を返すよう指定して再試行し、繰り返す場合は検証可能な最小の一歩へ戻ってください。",
        "return_to": " または {next_step_note} に戻ってください。",
    },
    "ko-KR": {
        "summary": "공급자가 빈 응답을 반환했으므로 이번 턴을 완료로 처리할 수 없습니다.",
        "focus": " 대화 흐름은 계속 {focus_note}에 맞추세요.",
        "tools": " 실행된 점검: {tools}.",
        "next_step": "보이는 결론을 반환하도록 다시 시도하고, 반복되면 검증 가능한 가장 작은 동작으로 돌아가세요.",
        "return_to": " 또는 {next_step_note} 단계로 돌아가세요.",
    },
    "pt-BR": {
        "summary": "O provedor retornou uma resposta visível vazia, portanto este turno não pode ser tratado como concluído.",
        "focus": " A conversa deve continuar ancorada em {focus_note}.",
        "tools": " Verificações executadas: {tools}.",
        "next_step": "Tente novamente o turno exigindo uma conclusão visível; se repetir, volte ao menor passo verificável.",
        "return_to": " Ou volte para {next_step_note}.",
    },
}

_COMPLETION_CONTINUITY_DEFAULTS: dict[str, tuple[str, str]] = {
    "zh-CN": (
        "这一轮已经自然收口，可以继续同一条主线。",
        "继续沿着同一条主线，验证最小的具体结果。",
    ),
    "en-US": (
        "This turn completed cleanly and the thread can continue.",
        "Continue from the same thread and verify the smallest concrete result.",
    ),
    "es-ES": (
        "Este turno terminó limpiamente y el hilo puede continuar.",
        "Continúa por el mismo hilo y verifica el resultado concreto más pequeño.",
    ),
    "fr-FR": (
        "Ce tour s'est terminé proprement et le fil peut se poursuivre.",
        "Poursuis sur le même fil et vérifie le plus petit résultat concret.",
    ),
    "de-DE": (
        "Diese Runde wurde sauber abgeschlossen und der Faden kann weitergehen.",
        "Setze am selben Faden fort und prüfe das kleinste konkrete Ergebnis.",
    ),
    "ja-JP": (
        "このターンはきれいに完了しました。同じ流れで続けられます。",
        "同じ流れを続け、最小の具体的な結果を確認してください。",
    ),
    "ko-KR": (
        "이번 턴이 깔끔하게 마무리되었으며 같은 흐름을 이어갈 수 있습니다.",
        "같은 흐름에서 계속 진행하며 가장 작은 구체적 결과를 확인하세요.",
    ),
    "pt-BR": (
        "Este turno terminou de forma limpa e a conversa pode continuar.",
        "Continue pela mesma linha e verifique o menor resultado concreto.",
    ),
}


def _build_no_progress_recovery(
    tool_calls: list[dict[str, Any]],
    *,
    previous_step: AgentStep | None,
    context: ToolContext | None,
    response_language: str | None,
) -> tuple[str, str]:
    locale = _normalize_loop_locale(response_language)
    copy = _NO_PROGRESS_COPY.get(locale, _NO_PROGRESS_COPY["en-US"])
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

    suffix = copy["summary_suffix"].format(tool_path=tool_path) if tool_path else ""
    summary = copy["summary_base"].format(suffix=suffix)
    if focus_note:
        summary = f"{summary}{copy['focus'].format(focus_note=focus_note)}"
    if failure_note:
        summary = f"{summary}{copy['failure'].format(failure_note=failure_note)}"
    next_step = (
        copy["next_plain"]
        if not tool_path
        else copy["next_tool"].format(tool_path=tool_path)
    )
    if next_step_note:
        next_step = f"{next_step}{copy['return_to'].format(next_step_note=next_step_note)}"
    if failure_note:
        next_step = f"{next_step}{copy['fix_first'].format(failure_note=failure_note)}"
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
    locale = _normalize_loop_locale(response_language)
    copy = _STEP_LIMIT_COPY.get(locale, _STEP_LIMIT_COPY["en-US"])
    failure_note = _previous_step_failure_note(previous_step)
    focus_note = _recovery_focus_note(context)
    next_step_note = _recovery_next_step_note(context)

    summary = copy["summary"]
    if focus_note:
        summary = f"{summary}{copy['focus'].format(focus_note=focus_note)}"
    next_step = copy["next_step"]
    if next_step_note:
        next_step = f"{next_step}{copy['return_to'].format(next_step_note=next_step_note)}"
    if failure_note:
        summary = f"{summary}{copy['failure'].format(failure_note=failure_note)}"
        next_step = f"{next_step}{copy['fix_first'].format(failure_note=failure_note)}"
    return summary, next_step


def _build_runtime_failure_recovery(
    reason: str,
    *,
    context: ToolContext | None,
    response_language: str | None,
    previous_step: AgentStep | None,
) -> tuple[str, str]:
    locale = _normalize_loop_locale(response_language)
    copy = _RUNTIME_FAILURE_COPY.get(locale, _RUNTIME_FAILURE_COPY["en-US"])
    focus_note = _recovery_focus_note(context)
    next_step_note = _recovery_next_step_note(context)
    failure_note = _previous_step_failure_note(previous_step)

    if reason == "timeout":
        summary = copy["timeout_summary"]
        next_step = copy["timeout_next"]
    else:
        summary = copy["error_summary"]
        next_step = copy["error_next"]
    if focus_note:
        summary = f"{summary}{copy['focus'].format(focus_note=focus_note)}"
    if failure_note:
        summary = f"{summary}{copy['failure'].format(failure_note=failure_note)}"
    if next_step_note:
        next_step = f"{next_step}{copy['return_to'].format(next_step_note=next_step_note)}"
    return summary, next_step


def _extract_executed_tool_names(executed_steps: list[AgentStep] | None) -> list[str]:
    tool_names: list[str] = []
    for step in executed_steps or ():
        for call in step.tool_calls:
            if not isinstance(call, dict):
                continue
            name = str(call.get("name") or "").strip()
            if name and name != "coach_finalize":
                tool_names.append(name)
        for result in step.tool_results:
            if not isinstance(result, dict):
                continue
            name = str(result.get("name") or "").strip()
            if name and name != "coach_finalize":
                tool_names.append(name)
    return list(dict.fromkeys(tool_names))


def _build_empty_response_recovery(
    *,
    context: ToolContext | None,
    response_language: str | None,
    executed_steps: list[AgentStep] | None = None,
) -> tuple[str, str]:
    locale = _normalize_loop_locale(response_language)
    copy = _EMPTY_RESPONSE_COPY.get(locale, _EMPTY_RESPONSE_COPY["en-US"])
    focus_note = _recovery_focus_note(context)
    next_step_note = _recovery_next_step_note(context)
    executed_tools = _extract_executed_tool_names(executed_steps)

    summary = copy["summary"]
    if focus_note:
        summary = f"{summary}{copy['focus'].format(focus_note=focus_note)}"
    if executed_tools:
        summary = f"{summary}{copy['tools'].format(tools=', '.join(executed_tools[:5]))}"
    next_step = copy["next_step"]
    if next_step_note:
        next_step = f"{next_step}{copy['return_to'].format(next_step_note=next_step_note)}"
    return summary, next_step


def _build_completion_continuity(
    content: str,
    *,
    context: ToolContext | None,
    response_language: str | None,
    previous_step: AgentStep | None = None,
) -> tuple[str, str]:
    locale = _normalize_loop_locale(response_language)
    default_summary, default_next_step = _COMPLETION_CONTINUITY_DEFAULTS.get(
        locale, _COMPLETION_CONTINUITY_DEFAULTS["en-US"]
    )
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
        summary = default_summary

    next_step = visible_next_step(content) or first_text(
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
    # A specific hint from the thread outranks an unlabelled sentence; the reply's closing
    # instruction still beats the neutral default, and the reply's opening prose is never used.
    if not next_step:
        next_step = closing_action_step(content)
    if not next_step:
        next_step = default_next_step
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

    latin_markers = (
        "empty visible answer",
        "no visible answer",
        "turn cannot be treated as complete",
        "retry the turn and require a visible conclusion",
        "resume the live thread around",
        "keep the next move as",
        "respuesta visible vacía",
        "no puede darse por terminado",
        "réponse visible vide",
        "considéré comme terminé",
        "leere sichtbare antwort",
        "nicht als abgeschlossen",
        "resposta visível vazia",
        "tratado como concluído",
    )
    if any(marker in normalized for marker in latin_markers):
        return True

    cjk_markers = (
        "\u7a7a\u5185\u5bb9",
        "\u53ef\u89c1\u7ed3\u8bba",
        "\u91cd\u65b0\u53d1\u8d77\u8fd9\u4e00\u8f6e",
        "\u7ee7\u7eed\u6cbf\u7740\u540c\u4e00\u6761\u4e3b\u7ebf",
        "\u7a7a\u306e\u5fdc\u7b54",
        "\u76ee\u306b\u898b\u3048\u308b\u7d50\u8ad6",
        "\ube48 \uc751\ub2f5\uc744",
        "\ubcf4\uc774\ub294 \uacb0\ub860\uc744",
    )
    return any(marker in value for marker in cjk_markers)


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
