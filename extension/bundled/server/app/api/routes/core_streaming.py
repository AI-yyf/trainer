"""Modular SSE streaming engine and routes (/session/message/stream, /turn/stream).

Eliminates duplicated agentic/plain stream loops and removes all Pyright
complexity exemptions while preserving singleflight, cancellation, and recovery
semantics byte-for-byte.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ...core.models import (
    ChatMessage,
    SessionMessageRequest,
    SessionMessageResponse,
    TurnRequest,
    UserProfile,
    WorkbenchSnapshot,
)
from ...llm.coaching_replies import preserve_streamed_reply_prefix
from ...llm.provider.service_support import has_successful_agent_tool_result
from ...llm.provider_service import ProviderService, redact_provider_error
from ...llm.stream_agent_metadata import merge_stream_agent_metadata
from ...memory.workspace_recovery import leftover_formal_plan_is_live_for_fill
from .. import coach_support
from .._singleflight import (
    claim_session_request_singleflight,
    fail_session_request_singleflight,
    publish_session_request_singleflight,
)
from ..coach_support import CoachTurnPayload
from ..router_support import (
    _attach_requested_workspace_files,
    _normalize_resource_turn_request,
    _resolve_agent_loop_enabled,
    register_request_workspace_path,
)
from ..routes.resources import PrepareResearchTurn
from ..runtime import SessionState, TrainerRuntime
from .core_sessions import SessionMessageHandler
from .core_shared import (
    _build_stream_timings,
    _schedule_background_tail,
    finish_research_preparation,
    observe_goal_for_request,
    overlay_completed_session_or_turn_response,
)

if TYPE_CHECKING:
    from .core import CoreRouteDeps

logger = logging.getLogger(__name__)

StreamCancelChecker = Callable[[], Awaitable[bool]]
StreamPublishFn = Callable[[dict[str, object]], dict[str, object]]


@dataclass(slots=True)
class StreamExecutionState:
    """Mutable state for a single SSE coaching or turn stream execution."""

    stream_started_at: float
    model_requested_at: float | None = None
    provider_first_event_at: float | None = None
    visible_first_at: float | None = None
    token_count: int = 0
    streamed_reply_content: str = ""
    pending_streamed_reply_content: str = ""
    full_content: str = ""
    agent_summary: str | None = None
    agent_next_step: str | None = None
    agent_stop_reason: str | None = None
    agent_decision: str | None = None
    agent_blocker: str | None = None
    agent_teaching_note: str | None = None
    agent_resume_thread: str | None = None
    agent_confidence: str | None = None
    agent_evidence: list[object] | None = None
    agent_tool_events: list[dict[str, object]] = field(default_factory=list)
    agent_steps: list[dict[str, object]] = field(default_factory=list)
    final_agent_meta: dict[str, object] = field(default_factory=dict)
    provider_failure_detected: bool = False
    stream_user_message: ChatMessage | None = None
    stream_assistant_message_ids: set[str] = field(default_factory=set)
    preexisting_assistant_ids: set[str] = field(default_factory=set)
    stream_committed: bool = False
    stream_failed: bool = False
    stream_singleflight_published: bool = False
    aborted: bool = False


def _make_stream_cancelled_checker(
    core: CoreRouteDeps,
    *,
    stream_id: str,
    http_request: Request,
) -> StreamCancelChecker:
    async def _is_cancelled() -> bool:
        if core.domain.stream_cancellation_requested(stream_id):
            return True
        try:
            return await http_request.is_disconnected()
        except RuntimeError:
            return False

    return _is_cancelled


async def _emit_abort_fail_closed(
    core: CoreRouteDeps,
    st: StreamExecutionState,
    *,
    stream_id: str,
    request_id: str,
    publish_fn: StreamPublishFn,
    error_detail: object | None = None,
) -> AsyncIterator[str]:
    """Emit failed -> acked and publish failure complete so same request_id cannot remint."""
    st.stream_failed = True
    st.aborted = True
    failure_payload: dict[str, object] = core.domain.attach_operation_reliability(
        {},
        phase="acked",
        outcome="failure",
        request_id=request_id or None,
    )
    if request_id and not st.stream_singleflight_published:
        failure_payload = publish_fn(failure_payload)
        st.stream_singleflight_published = True
    yield core.domain.stream_status_event("failed", stream_id)
    if error_detail is not None:
        yield (
            "event: error\n"
            f"data: {json.dumps({'error': error_detail, 'stream_id': stream_id, 'terminal': True})}\n\n"
        )
    yield core.domain.stream_status_event("acked", stream_id)
    yield core.domain.sse_complete_frame(
        tokens=st.token_count,
        response_data=failure_payload,
        stream_id=stream_id,
        outcome="failure",
        request_id=request_id or None,
        provider_failure_detected=True,
    )


async def _emit_abort_for_cancellation(
    core: CoreRouteDeps,
    st: StreamExecutionState,
    *,
    stream_id: str,
    request_id: str,
    publish_fn: StreamPublishFn,
) -> AsyncIterator[str]:
    """Explicit /stream/cancel stays fail-closed; a client disconnect only interrupts."""
    st.aborted = True
    if core.domain.stream_cancellation_requested(stream_id):
        async for closed_frame in _emit_abort_fail_closed(
            core,
            st,
            stream_id=stream_id,
            request_id=request_id,
            publish_fn=publish_fn,
        ):
            yield closed_frame
        return
    yield core.domain.stream_status_event("cancelled", stream_id)


async def _build_singleflight_waiter_stream(
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    *,
    kind: Literal["wait", "cached"],
    cached_response: dict[str, object] | None,
    shared_future: asyncio.Future[dict[str, object]] | None,
    stream_id: str,
    request_id: str,
    workspace_id: str,
    session_id: str | None,
    message: str,
    request_key: tuple[str, str, str],
    coaching_service: ProviderService | None,
) -> AsyncIterator[str]:
    try:
        shared_payload: dict[str, object]
        if kind == "wait":
            assert shared_future is not None
            shared_payload = cast("dict[str, object]", await shared_future)
        else:
            assert cached_response is not None
            shared_payload = cached_response
        stamped = overlay_completed_session_or_turn_response(
            runtime,
            core,
            workspace_id=workspace_id,
            session_id=session_id,
            message=message,
            request_key=request_key,
            cached_response=shared_payload,
        )
        yield core.domain.sse_complete_frame(
            tokens=0,
            response_data=stamped,
            stream_id=stream_id,
            request_id=request_id,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        failure_payload = core.domain.attach_operation_reliability(
            {},
            phase="acked",
            outcome="failure",
            request_id=request_id or None,
        )
        stamped = overlay_completed_session_or_turn_response(
            runtime,
            core,
            workspace_id=workspace_id,
            session_id=session_id,
            message=message,
            request_key=request_key,
            cached_response=failure_payload,
        )
        yield core.domain.stream_status_event("failed", stream_id)
        yield core.domain.stream_status_event("acked", stream_id)
        redacted = redact_provider_error(
            exc,
            api_key=getattr(coaching_service, "_api_key", None),
        )
        yield (
            "event: error\n"
            f"data: {json.dumps({'error': redacted, 'stream_id': stream_id, 'terminal': True})}\n\n"
        )
        yield core.domain.sse_complete_frame(
            tokens=0,
            response_data=stamped,
            stream_id=stream_id,
            outcome="failure",
            request_id=request_id,
            provider_failure_detected=True,
        )


async def _consume_agentic_coach_events(
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    st: StreamExecutionState,
    *,
    coaching_service: ProviderService,
    profile: UserProfile,
    request: SessionMessageRequest | TurnRequest,
    workspace_id: str,
    state: SessionState,
    coach_context: dict[str, Any],
    attachments_payload: list[dict[str, Any]],
    stream_id: str,
    request_id: str,
    stream_cancelled: StreamCancelChecker,
    publish_fn: StreamPublishFn,
) -> AsyncIterator[str]:
    agent_context = dict(coach_context)
    agent_context["__runtime__"] = runtime
    agent_context["workspace_id"] = workspace_id
    agent_context["session_id"] = state.session_id
    agent_context["stream_cancel_event"] = core.domain.stream_cancellation_events.get(stream_id)

    async for event in coaching_service.coaching_reply_agentic_stream(
        profile,
        request.message,
        request.current_file.model_dump() if request.current_file else None,
        response_language=request.response_language,
        answer_mode=request.answer_mode,
        coach_context=agent_context,
        attachments=attachments_payload,
        protocol=(
            getattr(coaching_service._config, "protocol", None)
            if coaching_service._config
            else None
        ),
        history=core.domain.build_conversation_history(
            state.snapshot.messages,
            active_view=request.active_view,
            drop_latest_user=True,
        ),
    ):
        if await stream_cancelled():
            async for abort_frame in _emit_abort_for_cancellation(
                core,
                st,
                stream_id=stream_id,
                request_id=request_id,
                publish_fn=publish_fn,
            ):
                yield abort_frame
            return
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "")
        if st.provider_first_event_at is None and event_type in {
            "provider_activity",
            "text",
            "tool_call",
            "final",
        }:
            st.provider_first_event_at = time.perf_counter()
        if event_type == "provider_activity":
            activity_phase = str(event.get("phase") or "")
            if activity_phase == "model_reasoning":
                yield core.domain.stream_status_event("model_reasoning", stream_id)
            elif activity_phase == "tool_drafting" and event.get("name"):
                yield core.domain.stream_status_event(
                    "tool_intent",
                    stream_id,
                    detail={"name": str(event.get("name"))},
                )
        elif event_type == "text":
            delta = str(event.get("delta") or "")
            if delta:
                st.full_content += delta
                st.token_count += 1
                if event.get("safe_to_stream") is True and (
                    not core.domain.requires_formal_plan_commit(request)
                    or core.domain.formal_plan_commit_tool_succeeded(st.agent_tool_events)
                ):
                    visible_delta, st.pending_streamed_reply_content = core.domain.safe_stream_delta(
                        st.pending_streamed_reply_content,
                        delta,
                        st.full_content,
                    )
                    if visible_delta:
                        if st.visible_first_at is None:
                            st.visible_first_at = time.perf_counter()
                        st.streamed_reply_content += visible_delta
                        yield f"data: {json.dumps({'chunk': visible_delta})}\n\n"
        elif event_type == "tool_call":
            if st.visible_first_at is None:
                st.visible_first_at = time.perf_counter()
            st.agent_tool_events.append(dict(event))
            yield core.domain.stream_frame("tool_call", event, stream_id)
        elif event_type == "tool_result":
            st.agent_tool_events.append(dict(event))
            yield core.domain.stream_frame("tool_result", event, stream_id)
        elif event_type == "step":
            st.agent_steps.append(dict(event))
            yield core.domain.stream_frame("step", event, stream_id)
        elif event_type == "final":
            final_content = str(event.get("content") or "")
            if final_content:
                st.full_content = final_content
            summary_val = event.get("summary")
            st.agent_summary = summary_val if isinstance(summary_val, str) else None
            next_step_val = event.get("next_step")
            st.agent_next_step = next_step_val if isinstance(next_step_val, str) else None
            stop_reason_val = event.get("stop_reason")
            st.agent_stop_reason = stop_reason_val if isinstance(stop_reason_val, str) else None
            decision_val = event.get("decision")
            st.agent_decision = decision_val if isinstance(decision_val, str) else None
            blocker_val = event.get("blocker")
            st.agent_blocker = blocker_val if isinstance(blocker_val, str) else None
            note_val = event.get("teaching_note")
            st.agent_teaching_note = note_val if isinstance(note_val, str) else None
            resume_val = event.get("resume_thread")
            st.agent_resume_thread = resume_val if isinstance(resume_val, str) else None
            conf_val = event.get("confidence")
            st.agent_confidence = conf_val if isinstance(conf_val, str) else None
            st.agent_evidence = (
                list(event.get("evidence") or [])
                if isinstance(event.get("evidence"), list)
                else None
            )
        elif event_type == "error":
            if event.get("terminal") is False:
                continue
            async for abort_frame in _emit_abort_fail_closed(
                core,
                st,
                stream_id=stream_id,
                request_id=request_id,
                publish_fn=publish_fn,
                error_detail=redact_provider_error(
                    event.get("detail"),
                    api_key=getattr(coaching_service, "_api_key", None),
                ),
            ):
                yield abort_frame
            return

    if st.full_content:
        raw_before_finalize = st.full_content
        finalized = coaching_service.finalize_coaching_reply(
            raw_before_finalize,
            profile=profile,
            message=request.message,
            current_file=request.current_file.model_dump() if request.current_file else None,
            response_language=request.response_language,
            answer_mode=request.answer_mode,
            coach_context=dict(coach_context),
            grounded_completion=has_successful_agent_tool_result(st.agent_tool_events),
        )
        st.full_content = preserve_streamed_reply_prefix(
            st.streamed_reply_content,
            finalized,
            raw_before_finalize,
            tool_events=st.agent_tool_events,
            response_language=request.response_language,
        )


async def _consume_plain_coach_chunks(
    core: CoreRouteDeps,
    st: StreamExecutionState,
    *,
    coaching_service: ProviderService,
    profile: UserProfile,
    request: SessionMessageRequest | TurnRequest,
    state: SessionState,
    coach_context: dict[str, Any],
    stream_id: str,
    request_id: str,
    stream_cancelled: StreamCancelChecker,
    publish_fn: StreamPublishFn,
    finalize_even_if_empty: bool,
) -> AsyncIterator[str]:
    async for chunk in coaching_service.coaching_reply_stream(
        profile,
        request.message,
        request.current_file.model_dump() if request.current_file else None,
        response_language=request.response_language,
        answer_mode=request.answer_mode,
        coach_context=dict(coach_context),
        history=core.domain.build_conversation_history(
            state.snapshot.messages,
            active_view=request.active_view,
            drop_latest_user=True,
        ),
        cancel_event=core.domain.stream_cancellation_events.get(stream_id),
    ):
        if await stream_cancelled():
            async for abort_frame in _emit_abort_for_cancellation(
                core,
                st,
                stream_id=stream_id,
                request_id=request_id,
                publish_fn=publish_fn,
            ):
                yield abort_frame
            return
        delta = str(chunk or "")
        if not finalize_even_if_empty and not delta:
            continue
        st.full_content += delta
        st.token_count += 1
        if st.provider_first_event_at is None and delta:
            st.provider_first_event_at = time.perf_counter()
        visible_chunk, st.pending_streamed_reply_content = core.domain.safe_stream_delta(
            st.pending_streamed_reply_content,
            delta,
            st.full_content,
        )
        if visible_chunk and not core.domain.requires_formal_plan_commit(request):
            if st.visible_first_at is None:
                st.visible_first_at = time.perf_counter()
            st.streamed_reply_content += visible_chunk
            yield f"data: {json.dumps({'chunk': visible_chunk})}\n\n"

    raw_before_finalize = st.full_content
    stream_finalization = coaching_service.consume_stream_finalization()
    if stream_finalization is not None:
        candidate_final = stream_finalization[1]
    elif finalize_even_if_empty or st.full_content:
        candidate_final = coaching_service.finalize_coaching_reply(
            raw_before_finalize,
            profile=profile,
            message=request.message,
            current_file=request.current_file.model_dump() if request.current_file else None,
            response_language=request.response_language,
            answer_mode=request.answer_mode,
            coach_context=dict(coach_context),
        )
    else:
        candidate_final = raw_before_finalize
    if coaching_service.peek_last_reply_failure() is None:
        st.full_content = preserve_streamed_reply_prefix(
            st.streamed_reply_content,
            candidate_final,
            raw_before_finalize,
            response_language=request.response_language,
        )
    else:
        st.full_content = candidate_final


def _apply_stream_provider_overrides(
    core: CoreRouteDeps,
    st: StreamExecutionState,
    *,
    coaching_service: ProviderService,
    state: SessionState,
    coach_turn_map: dict[str, object],
    message: str,
    response_language: str | None,
) -> dict[str, object]:
    provider_empty_reply_override = core.domain.consume_provider_empty_reply_override(
        coaching_service=coaching_service,
        snapshot=state.snapshot,
        coach_turn=coach_turn_map,
        response_language=response_language,
        assistant_content=st.full_content,
    )
    if provider_empty_reply_override is not None:
        st.provider_failure_detected = True
        st.full_content, updated_turn, override_meta = provider_empty_reply_override
        st.final_agent_meta.update(override_meta)
        return updated_turn

    provider_failure_override = core.domain.consume_provider_reply_failure_override(
        coaching_service=coaching_service,
        snapshot=state.snapshot,
        coach_turn=coach_turn_map,
        message=message,
        response_language=response_language,
        workspace_id=state.workspace_id,
    )
    if provider_failure_override is not None:
        st.provider_failure_detected = True
        st.full_content, updated_turn, override_meta = provider_failure_override
        st.final_agent_meta.update(override_meta)
        return updated_turn

    return coach_turn_map


def _apply_stream_guided_repairs_and_card(
    core: CoreRouteDeps,
    st: StreamExecutionState,
    *,
    state: SessionState,
    request: SessionMessageRequest | TurnRequest,
    profile: UserProfile,
    coaching_service: ProviderService,
    coach_turn: CoachTurnPayload,
    scenario: str,
    use_agent_stream: bool,
    guided_training_prefers_local_reply: bool,
    raw_requested_answer_mode: str,
    saved_answer_mode: str,
) -> CoachTurnPayload:
    visible_agent_meta = {
        "stop_reason": st.agent_stop_reason,
        "summary": st.agent_summary,
        "next_step": st.agent_next_step,
        "decision": st.agent_decision,
        "blocker": st.agent_blocker,
        "teaching_note": st.agent_teaching_note,
        "resume_thread": st.agent_resume_thread,
        "confidence": st.agent_confidence,
        "evidence": st.agent_evidence,
        "steps": st.agent_steps,
        "tool_events": st.agent_tool_events,
        "agentic": use_agent_stream and not guided_training_prefers_local_reply,
        **st.final_agent_meta,
    }
    candidate_guided_reply, updated_coach_turn, st.final_agent_meta, _ = (
        core.domain.apply_guided_lane_visible_fallback(
            reply=st.full_content,
            scenario=str(coach_turn.get("scenario") or scenario),
            learner_message=request.message,
            response_language=request.response_language,
            coach_turn=core.domain.coach_turn_mapping(coach_turn),
            agent_meta=visible_agent_meta,
        )
    )
    st.full_content = preserve_streamed_reply_prefix(
        st.streamed_reply_content,
        candidate_guided_reply,
        st.full_content,
        tool_events=st.agent_tool_events,
        response_language=request.response_language,
    )
    coach_turn = core.domain.extract_coach_turn_payload(updated_coach_turn)
    repaired_summary = st.final_agent_meta.get("summary")
    st.agent_summary = repaired_summary if isinstance(repaired_summary, str) else None
    repaired_next_step = st.final_agent_meta.get("next_step")
    st.agent_next_step = repaired_next_step if isinstance(repaired_next_step, str) else None
    repaired_decision = st.final_agent_meta.get("decision")
    st.agent_decision = repaired_decision if isinstance(repaired_decision, str) else None
    repaired_blocker = st.final_agent_meta.get("blocker")
    st.agent_blocker = repaired_blocker if isinstance(repaired_blocker, str) else None
    repaired_note = st.final_agent_meta.get("teaching_note")
    st.agent_teaching_note = repaired_note if isinstance(repaired_note, str) else None
    repaired_resume = st.final_agent_meta.get("resume_thread")
    st.agent_resume_thread = repaired_resume if isinstance(repaired_resume, str) else None
    repaired_conf = st.final_agent_meta.get("confidence")
    st.agent_confidence = repaired_conf if isinstance(repaired_conf, str) else None
    repaired_evidence = st.final_agent_meta.get("evidence")
    st.agent_evidence = list(repaired_evidence) if isinstance(repaired_evidence, list) else None

    core.domain.ensure_explicit_training_card_after_coach_reply(
        state=state,
        message=request.message,
        current_file=request.current_file,
        response_language=request.response_language,
        fallback_scenario=str(coach_turn.get("scenario") or ""),
        force_training_card=(
            core.domain.auto_preference_requests_training_card(
                request.message,
                requested_scenario=str(coach_turn.get("scenario") or scenario),
                requested_answer_mode=raw_requested_answer_mode,
                saved_answer_mode=saved_answer_mode,
                profile=profile,
            )
            or core.domain.auto_lane_learn_first_force_training_card(
                request.message,
                requested_scenario=str(coach_turn.get("scenario") or scenario),
                requested_answer_mode=raw_requested_answer_mode,
                saved_answer_mode=saved_answer_mode,
                profile=profile,
            )
        ),
        provider_service_override=coaching_service,
    )
    return coach_turn


async def _commit_and_emit_complete_frame(
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    st: StreamExecutionState,
    *,
    state: SessionState,
    workspace_id: str,
    response_data: dict[str, object],
    coaching_service: ProviderService | None,
    stream_id: str,
    request_id: str,
    stream_cancelled: StreamCancelChecker,
    publish_fn: StreamPublishFn,
    post_save_hook: Callable[[dict[str, object]], Awaitable[None]] | None = None,
) -> AsyncIterator[str]:
    st.stream_assistant_message_ids.update(
        message.id
        for message in state.snapshot.messages
        if message.role == "assistant" and message.id not in st.preexisting_assistant_ids
    )
    reply_record = response_data.get("reply")
    visible_content = (
        str(reply_record.get("content") or "").strip() if isinstance(reply_record, dict) else ""
    )
    visible_delta = core.domain.completion_stream_delta(st.streamed_reply_content, visible_content)
    if visible_delta:
        if st.visible_first_at is None:
            st.visible_first_at = time.perf_counter()
        st.token_count += 1
        yield f"data: {json.dumps({'chunk': visible_delta})}\n\n"

    timings_payload = _build_stream_timings(
        stream_started_at=st.stream_started_at,
        model_requested_at=st.model_requested_at,
        provider_first_event_at=st.provider_first_event_at,
        visible_first_at=st.visible_first_at,
        finished_at=time.perf_counter(),
    )
    st.final_agent_meta["timings"] = timings_payload
    response_data["timings"] = timings_payload
    if st.final_agent_meta:
        response_data["agent"] = st.final_agent_meta

    if await stream_cancelled():
        if not core.domain.stream_cancellation_requested(stream_id):
            yield core.domain.stream_status_event("cancelled", stream_id)
            return
        st.stream_failed = True
        response_data = core.domain.attach_operation_reliability(
            response_data,
            phase="acked",
            outcome="failure",
            request_id=request_id or None,
        )
        response_data = publish_fn(response_data)
        st.stream_singleflight_published = True
        yield core.domain.stream_status_event("failed", stream_id)
        yield core.domain.stream_status_event("acked", stream_id)
        yield core.domain.sse_complete_frame(
            tokens=st.token_count,
            response_data=response_data,
            stream_id=stream_id,
            outcome="failure",
            request_id=request_id or None,
            provider_failure_detected=True,
        )
        return

    if (
        coaching_service is not None
        and not st.provider_failure_detected
        and (st.final_agent_meta or {}).get("fell_back") is not True
        and st.token_count > 0
    ):
        runtime.mark_provider_live_turn_succeeded(coaching_service)
    await asyncio.to_thread(runtime.save_session_state, state.session_id)
    st.stream_committed = True
    if post_save_hook is not None:
        await post_save_hook(response_data)
    response_data = await asyncio.to_thread(
        _attach_requested_workspace_files,
        response_data,
        runtime,
        workspace_id,
    )
    response_data = publish_fn(response_data)
    st.stream_singleflight_published = True
    yield core.domain.sse_complete_frame(
        tokens=st.token_count,
        response_data=response_data,
        stream_id=stream_id,
        provider_failure_detected=st.provider_failure_detected,
    )


async def _run_non_coach_prepared_turn_stream(
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    st: StreamExecutionState,
    *,
    request: TurnRequest,
    payload: dict[str, Any],
    original_intent: str,
    workspace_id: str,
    raw_requested_answer_mode: str,
    saved_answer_mode: str,
    stream_id: str,
    request_id: str,
    stream_cancelled: StreamCancelChecker,
    publish_fn: StreamPublishFn,
    set_resolved_state: Callable[[SessionState, ProviderService], None],
) -> AsyncIterator[str]:
    preparation_or_response, _prepared_artifacts, prepared_service = (
        await coach_support.execute_turn(
            core.coach_support_deps,
            request,
            payload,
            stream=True,
            stream_id=stream_id,
        )
    )
    if not (
        isinstance(preparation_or_response, dict)
        and preparation_or_response.get("__turn_stream_preparation__") is True
    ):
        raise TypeError("Turn stream preparation was not produced for the requested turn.")

    preparation = preparation_or_response
    prepared_state = preparation.get("state")
    prepared_request = preparation.get("request")
    prepared_profile = preparation.get("profile")
    prepared_coach_turn = preparation.get("coach_turn_data")
    if not isinstance(prepared_state, SessionState):
        raise TypeError("Turn stream preparation is missing session state.")
    if not isinstance(prepared_request, TurnRequest):
        raise TypeError("Turn stream preparation is missing the normalized request.")
    if not isinstance(prepared_profile, UserProfile):
        raise TypeError("Turn stream preparation is missing the learner profile.")
    if not isinstance(prepared_coach_turn, dict):
        raise TypeError("Turn stream preparation is missing coach-turn data.")
    if not isinstance(prepared_service, ProviderService):
        raise TypeError("Turn stream preparation is missing the provider service.")

    set_resolved_state(prepared_state, prepared_service)
    state = prepared_state
    st.preexisting_assistant_ids = {
        message.id for message in state.snapshot.messages if message.role == "assistant"
    }
    st.stream_user_message = next(
        (
            message
            for message in reversed(state.snapshot.messages)
            if message.role == "user"
            and str(message.metadata.get("stream_id") or "").strip() == stream_id
        ),
        None,
    )
    request = prepared_request
    profile = prepared_profile
    coaching_service = prepared_service
    artifacts: dict[str, object] = core.domain.normalized_object_mapping(preparation.get("artifacts")) or {}
    suggested_actions = list(preparation.get("suggested_actions") or [])
    st.final_agent_meta = dict(core.domain.normalized_object_mapping(preparation.get("agent_meta")) or {})
    coach_turn_data = dict(prepared_coach_turn)
    response_snapshot = preparation.get("response_snapshot")
    if not isinstance(response_snapshot, WorkbenchSnapshot):
        response_snapshot = state.snapshot
    scenario = str(preparation.get("scenario") or coach_turn_data.get("scenario") or "general")
    learner_signal = str(preparation.get("learner_signal") or "")
    raw_delivery = preparation.get("attachment_delivery")
    attachment_delivery = raw_delivery if isinstance(raw_delivery, dict) else None
    fallback_reply = str(preparation.get("fallback_reply") or "").strip()
    use_agent_stream = bool(preparation.get("use_agent_loop"))
    attachments_payload = [attachment.model_dump() for attachment in request.attachments]
    raw_coach_ctx = coach_turn_data.get("coach_context")
    coach_context = raw_coach_ctx if isinstance(raw_coach_ctx, dict) else {}

    prepared_raw_answer_mode = str(
        preparation.get("raw_requested_answer_mode") or raw_requested_answer_mode
    ).strip()
    prepared_saved_answer_mode = str(
        preparation.get("saved_answer_mode") or saved_answer_mode
    ).strip()
    language_corruption_detected = bool(preparation.get("language_corruption_detected"))
    st.provider_failure_detected = bool(preparation.get("provider_failure_detected"))

    st.model_requested_at = time.perf_counter()
    yield core.domain.stream_status_event("requesting_model", stream_id)
    if use_agent_stream:
        async for frame in _consume_agentic_coach_events(
            runtime,
            core,
            st,
            coaching_service=coaching_service,
            profile=profile,
            request=request,
            workspace_id=workspace_id,
            state=state,
            coach_context=coach_context,
            attachments_payload=attachments_payload,
            stream_id=stream_id,
            request_id=request_id,
            stream_cancelled=stream_cancelled,
            publish_fn=publish_fn,
        ):
            yield frame
        if st.aborted:
            return
        if not st.agent_resume_thread and (st.agent_summary or st.agent_next_step):
            st.agent_resume_thread = core.domain.build_resume_thread_text(
                str(st.agent_summary or "").strip(),
                str(st.agent_next_step or "").strip(),
                response_language=request.response_language,
            )
    else:
        async for frame in _consume_plain_coach_chunks(
            core,
            st,
            coaching_service=coaching_service,
            profile=profile,
            request=request,
            state=state,
            coach_context=coach_context,
            stream_id=stream_id,
            request_id=request_id,
            stream_cancelled=stream_cancelled,
            publish_fn=publish_fn,
            finalize_even_if_empty=False,
        ):
            yield frame
        if st.aborted:
            return

    if not st.full_content:
        st.full_content = fallback_reply
    if not st.full_content:
        st.full_content = coaching_service._fallback_empty_reply(
            profile=profile,
            message=request.message,
            current_file=request.current_file.model_dump() if request.current_file else None,
            response_language=request.response_language,
            answer_mode=request.answer_mode,
            coach_context=coach_context,
        )
        st.token_count += 1

    coach_turn_data = _apply_stream_provider_overrides(
        core,
        st,
        coaching_service=coaching_service,
        state=state,
        coach_turn_map=coach_turn_data,
        message=request.message,
        response_language=request.response_language,
    )

    if use_agent_stream and not st.provider_failure_detected:
        st.final_agent_meta = merge_stream_agent_metadata(
            st.final_agent_meta,
            {
                "stop_reason": st.agent_stop_reason,
                "summary": st.agent_summary,
                "next_step": st.agent_next_step,
                "decision": st.agent_decision,
                "blocker": st.agent_blocker,
                "teaching_note": st.agent_teaching_note,
                "resume_thread": st.agent_resume_thread,
                "confidence": st.agent_confidence,
                "evidence": st.agent_evidence,
                "steps": st.agent_steps,
                "tool_events": st.agent_tool_events,
                "agentic": True,
            },
        )
        coach_turn_data = core.domain.merge_agent_finalize_into_coach_turn(
            coach_turn_data,
            summary=st.agent_summary,
            next_step=st.agent_next_step,
            blocker=st.agent_blocker,
            resume_thread=st.agent_resume_thread,
            decision=st.agent_decision,
            teaching_note=st.agent_teaching_note,
            confidence=st.agent_confidence,
            evidence=st.agent_evidence,
        )

    if await stream_cancelled():
        async for abort_frame in _emit_abort_for_cancellation(
            core,
            st,
            stream_id=stream_id,
            request_id=request_id,
            publish_fn=publish_fn,
        ):
            yield abort_frame
        return

    coach_turn_data = (
        core.domain.repair_generic_finalize_next_step(
            st.full_content,
            st.final_agent_meta if st.final_agent_meta else None,
            coach_turn_data,
            response_language=request.response_language,
        )
        or coach_turn_data
    )
    streaming_grounding_decision = await core.domain.resolve_turn_grounding_async(
        coach_turn_payload=coach_turn_data,
        reply_content=st.full_content,
        request=request,
        agent_meta=st.final_agent_meta or None,
        history_text=core.domain.turn_history_text(state.snapshot),
        coaching_service=coaching_service,
    )
    st.final_agent_meta = (
        core.domain.apply_grounding_decision(
            coach_turn_payload=coach_turn_data,
            decision=streaming_grounding_decision,
            agent_meta=st.final_agent_meta or None,
        )
        or st.final_agent_meta
    )
    if not language_corruption_detected and not st.provider_failure_detected:
        _schedule_background_tail(
            core.domain.persist_external_references_as_background,
            workspace_id=workspace_id,
            scenario=scenario,
            coach_turn_data=coach_turn_data,
        )

    def _persist_and_build_non_coach() -> dict[str, object]:
        coach_support.persist_turn_reflection(
            core.coach_support_deps,
            workspace_id=workspace_id,
            session_id=state.session_id,
            user_message=request.message,
            scenario=scenario,
            response_language=request.response_language,
            answer_mode=core.domain.answer_mode_preference_for_persistence(
                prepared_raw_answer_mode,
                prepared_saved_answer_mode,
                request.answer_mode,
                profile.answer_policy,
            ),
            coach_defaults=request.coach_defaults,
            coach_turn_data=coach_turn_data,
            grounding_decision=streaming_grounding_decision,
            stop_reason=str(st.final_agent_meta.get("stop_reason") or ""),
            recovered_stop_reason=str(st.final_agent_meta.get("recovered_stop_reason") or ""),
            local_sequence_fallback=bool(st.final_agent_meta.get("local_sequence_fallback")),
        )
        core.domain.persist_recovered_plan_resume_after_turn(
            workspace_id=workspace_id,
            request=request,
            reply_content=st.full_content,
            agent_meta=st.final_agent_meta,
            coach_context=coach_context,
            recovered_status=state.snapshot.plan_runtime_status
            if isinstance(state.snapshot.plan_runtime_status, dict)
            else None,
        )
        state.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
        state.snapshot.profile = runtime.repository.get_profile(workspace_id) or profile
        runtime.hydrate_plan_context(state.snapshot, workspace_id)
        coach_support.hydrate_snapshot(
            core.coach_support_deps,
            state.snapshot,
            response_language=request.response_language,
            answer_mode=request.answer_mode or profile.answer_policy,
            scenario=scenario,
            learner_signal=learner_signal,
            message=request.message,
            current_file=request.current_file,
            active_view=request.active_view,
            session_workspace_id=workspace_id,
        )
        if request.intent == "plan" and request.formal_plan_mutation:
            persisted_plan = runtime.repository.get_latest_plan(workspace_id)
            _leftover_after, leftover_runtime_after = core.domain.leftover_runtime_for_workspace(workspace_id)
            if persisted_plan is not None and leftover_formal_plan_is_live_for_fill(
                plan=persisted_plan,
                runtime=leftover_runtime_after,
                existing=leftover_runtime_after,
            ):
                state.snapshot.plan = persisted_plan
        built = coach_support.build_session_response(
            core.coach_support_deps,
            state=state,
            request=request,
            reply_content=st.full_content,
            artifacts=artifacts,
            suggested_actions=suggested_actions,
            scenario=scenario,
            learner_signal=learner_signal,
            coach_turn_data=coach_turn_data,
            response_snapshot=state.snapshot,
            agent_meta=st.final_agent_meta or None,
            attachment_delivery=attachment_delivery,
            streamed_prefix=st.streamed_reply_content if not st.provider_failure_detected else "",
        )
        return core.domain.json_object_payload(built)

    response_data = await asyncio.to_thread(_persist_and_build_non_coach)
    response_data["artifacts"] = artifacts
    response_data["intent"] = original_intent

    async for frame in _commit_and_emit_complete_frame(
        runtime,
        core,
        st,
        state=state,
        workspace_id=workspace_id,
        response_data=response_data,
        coaching_service=coaching_service,
        stream_id=stream_id,
        request_id=request_id,
        stream_cancelled=stream_cancelled,
        publish_fn=publish_fn,
    ):
        yield frame


async def _run_coach_lane_stream(
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    st: StreamExecutionState,
    *,
    state: SessionState,
    profile: UserProfile,
    request: SessionMessageRequest | TurnRequest,
    workspace_id: str,
    coaching_service: ProviderService,
    use_agent_stream: bool,
    attachment_delivery: dict[str, object] | None,
    attachments_payload: list[dict[str, Any]],
    stream_recovery_requested: bool,
    raw_requested_answer_mode: str,
    saved_answer_mode: str,
    stream_id: str,
    request_id: str,
    stream_cancelled: StreamCancelChecker,
    publish_fn: StreamPublishFn,
    recover_plain_stream_fn: Callable[[], Awaitable[dict[str, object]]],
    synthesize_resume_thread: bool,
    include_resume_thread_in_stream_meta: bool,
    update_plan_on_turn: bool,
    original_intent: str | None = None,
    prepare_research_turn: PrepareResearchTurn | None = None,
) -> AsyncIterator[str]:
    st.preexisting_assistant_ids = {
        message.id for message in state.snapshot.messages if message.role == "assistant"
    }
    st.stream_user_message, _ = core.domain.prepare_stream_user_message(
        state=state,
        request=request,
        profile=profile,
        attachment_delivery=attachment_delivery,
        stream_id=stream_id,
    )
    def _prepare_coach_stream_turn() -> tuple[
        CoachTurnPayload,
        str,
        bool,
        dict[str, str] | None,
        list[dict[str, object]],
    ]:
        core.domain.safe_activate_training_card_from_coach_request(
            workspace_id=state.workspace_id,
            snapshot=state.snapshot,
            message=request.message,
            current_file=request.current_file,
            response_language=request.response_language,
            provider_service_override=coaching_service,
        )
        state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        resolved_turn: CoachTurnPayload = coach_support.resolve_coach_turn(
            core.coach_support_deps,
            state=state,
            profile=profile,
            request=request,
            message=request.message,
            coaching_service=coaching_service,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
            current_evaluation=state.snapshot.evaluation,
        )
        resolved_scenario = str(resolved_turn.get("scenario") or "general")
        if core.domain.guarantee_guided_learn_first_training_card(
            workspace_id=state.workspace_id,
            scenario=str(resolved_turn["scenario"] or ""),
            message=request.message,
            current_file=request.current_file,
            response_language=request.response_language,
            active_thread=state.snapshot.memory.active_thread,
            requested_answer_mode=raw_requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        ):
            state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        prefers_local = core.domain.should_bypass_agent_loop_for_guided_training(
            workspace_id=state.workspace_id,
            scenario=str(resolved_turn["scenario"] or resolved_scenario),
            message=request.message,
            active_view=request.active_view,
            requested_answer_mode=raw_requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        )
        local_reply = (
            core.domain.build_guided_training_visible_fallback(
                workspace_id=state.workspace_id,
                response_language=request.response_language,
            )
            if prefers_local
            else None
        )
        res_events = core.domain.auto_resource_lookup_tool_events(
            dict(resolved_turn["coach_context"]),
            request.message,
        )
        return resolved_turn, resolved_scenario, prefers_local, local_reply, res_events

    (
        coach_turn,
        scenario,
        guided_training_prefers_local_reply,
        guided_training_local_reply,
        auto_resource_events,
    ) = await asyncio.to_thread(_prepare_coach_stream_turn)

    if guided_training_local_reply is None:
        st.model_requested_at = time.perf_counter()
        yield core.domain.stream_status_event("requesting_model", stream_id)

    if guided_training_local_reply is not None:
        st.full_content, updated_coach_turn, guided_meta = (
            core.domain.apply_guided_training_visible_fallback(
                coach_turn=core.domain.coach_turn_mapping(coach_turn),
                fallback=guided_training_local_reply,
            )
        )
        coach_turn = core.domain.extract_coach_turn_payload(updated_coach_turn)
        st.final_agent_meta.update(guided_meta)
        st.token_count += 1
    elif use_agent_stream and not guided_training_prefers_local_reply:
        async for frame in _consume_agentic_coach_events(
            runtime,
            core,
            st,
            coaching_service=coaching_service,
            profile=profile,
            request=request,
            workspace_id=workspace_id,
            state=state,
            coach_context=dict(coach_turn["coach_context"]),
            attachments_payload=attachments_payload,
            stream_id=stream_id,
            request_id=request_id,
            stream_cancelled=stream_cancelled,
            publish_fn=publish_fn,
        ):
            yield frame
        if st.aborted:
            return
        if synthesize_resume_thread and not st.agent_resume_thread and (
            st.agent_summary or st.agent_next_step
        ):
            st.agent_resume_thread = core.domain.build_resume_thread_text(
                str(st.agent_summary or "").strip(),
                str(st.agent_next_step or "").strip(),
                response_language=request.response_language,
            )
        if not st.full_content:
            local_sequence_fallback = core.domain.build_local_sequence_visible_fallback(
                coach_context=dict(coach_turn["coach_context"]),
                response_language=request.response_language,
            )
            if local_sequence_fallback is not None:
                st.full_content = local_sequence_fallback["reply"]
                coaching_service.clear_last_reply_override()
                st.agent_summary = st.agent_summary or local_sequence_fallback["summary"]
                st.agent_next_step = st.agent_next_step or local_sequence_fallback["next_step"]
                st.agent_teaching_note = (
                    st.agent_teaching_note or local_sequence_fallback["teaching_note"]
                )
                st.agent_resume_thread = (
                    st.agent_resume_thread or local_sequence_fallback["resume_thread"]
                )
                st.final_agent_meta["local_sequence_fallback"] = True
                if str(st.agent_stop_reason or "").strip() == "empty_response":
                    st.final_agent_meta["fell_back"] = True
                    st.final_agent_meta["recovered_stop_reason"] = "empty_response"
                    st.final_agent_meta["stop_reason"] = "completed"
            else:
                st.full_content = coaching_service._fallback_empty_reply(
                    profile=profile,
                    message=request.message,
                    current_file=request.current_file.model_dump() if request.current_file else None,
                    response_language=request.response_language,
                    answer_mode=request.answer_mode,
                    coach_context=dict(coach_turn["coach_context"]),
                )
            st.token_count += 1
        updated_coach_turn = core.domain.merge_agent_finalize_into_coach_turn(
            core.domain.coach_turn_mapping(coach_turn),
            summary=st.agent_summary,
            next_step=st.agent_next_step,
            blocker=st.agent_blocker,
            resume_thread=st.agent_resume_thread,
            decision=st.agent_decision,
            teaching_note=st.agent_teaching_note,
            confidence=st.agent_confidence,
            evidence=st.agent_evidence,
        )
        coach_turn = core.domain.extract_coach_turn_payload(updated_coach_turn)
    else:
        try:
            async for frame in _consume_plain_coach_chunks(
                core,
                st,
                coaching_service=coaching_service,
                profile=profile,
                request=request,
                state=state,
                coach_context=dict(coach_turn["coach_context"]),
                stream_id=stream_id,
                request_id=request_id,
                stream_cancelled=stream_cancelled,
                publish_fn=publish_fn,
                finalize_even_if_empty=True,
            ):
                yield frame
            if st.aborted:
                return
        except Exception:
            if not stream_recovery_requested or st.streamed_reply_content or st.full_content:
                raise
            if st.stream_user_message is not None:
                provisional_id = st.stream_user_message.id
                state.snapshot.messages = [
                    item for item in state.snapshot.messages if item.id != provisional_id
                ]
                st.stream_user_message = None
            recovered_payload = await recover_plain_stream_fn()
            reply_record = recovered_payload.get("reply")
            reply_content = (
                str(reply_record.get("content") or "").strip()
                if isinstance(reply_record, dict)
                else ""
            )
            if reply_content:
                st.token_count += 1
                yield f"data: {json.dumps({'chunk': reply_content})}\n\n"
            st.stream_committed = True
            recovered_payload = publish_fn(recovered_payload)
            st.stream_singleflight_published = True
            yield core.domain.sse_complete_frame(
                tokens=st.token_count,
                response_data=recovered_payload,
                stream_id=stream_id,
                provider_failure_detected=True,
            )
            return

    if await stream_cancelled():
        async for abort_frame in _emit_abort_for_cancellation(
            core,
            st,
            stream_id=stream_id,
            request_id=request_id,
            publish_fn=publish_fn,
        ):
            yield abort_frame
        return

    updated_turn_map = _apply_stream_provider_overrides(
        core,
        st,
        coaching_service=coaching_service,
        state=state,
        coach_turn_map=core.domain.coach_turn_mapping(coach_turn),
        message=request.message,
        response_language=request.response_language,
    )
    coach_turn = core.domain.extract_coach_turn_payload(updated_turn_map)

    if not st.provider_failure_detected:
        coach_turn = await asyncio.to_thread(
            _apply_stream_guided_repairs_and_card,
            core,
            st,
            state=state,
            request=request,
            profile=profile,
            coaching_service=coaching_service,
            coach_turn=coach_turn,
            scenario=scenario,
            use_agent_stream=use_agent_stream,
            guided_training_prefers_local_reply=guided_training_prefers_local_reply,
            raw_requested_answer_mode=raw_requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
        )

    if await stream_cancelled():
        async for abort_frame in _emit_abort_for_cancellation(
            core,
            st,
            stream_id=stream_id,
            request_id=request_id,
            publish_fn=publish_fn,
        ):
            yield abort_frame
        return

    grounding_decision = await core.domain.resolve_turn_grounding_async(
        coach_turn_payload=coach_turn,
        reply_content=st.full_content,
        request=request,
        agent_meta=st.final_agent_meta if isinstance(st.final_agent_meta, dict) else None,
        history_text=core.domain.turn_history_text(state.snapshot),
        coaching_service=coaching_service,
    )
    st.final_agent_meta = (
        core.domain.apply_grounding_decision(
            coach_turn_payload=coach_turn,
            decision=grounding_decision,
            agent_meta=st.final_agent_meta if isinstance(st.final_agent_meta, dict) else None,
        )
        or st.final_agent_meta
    )
    repaired_turn = core.domain.repair_generic_finalize_next_step(
        st.full_content,
        st.final_agent_meta if st.final_agent_meta else None,
        core.domain.coach_turn_mapping(coach_turn),
        response_language=request.response_language,
    )
    if repaired_turn is not None:
        coach_turn = core.domain.extract_coach_turn_payload(repaired_turn)
    if not st.provider_failure_detected:
        _schedule_background_tail(
            core.domain.persist_external_references_as_background,
            workspace_id=workspace_id,
            scenario=str(coach_turn["scenario"]),
            coach_turn_data=core.domain.coach_turn_mapping(coach_turn),
        )

    def _persist_and_build_coach() -> tuple[SessionMessageResponse, dict[str, object]]:
        coach_support.persist_turn_reflection(
            core.coach_support_deps,
            workspace_id=workspace_id,
            session_id=state.session_id,
            user_message=request.message,
            scenario=str(coach_turn["scenario"]),
            response_language=request.response_language,
            answer_mode=core.domain.answer_mode_preference_for_persistence(
                raw_requested_answer_mode,
                saved_answer_mode,
                request.answer_mode,
                profile.answer_policy if profile else None,
            ),
            coach_defaults=request.coach_defaults,
            coach_turn_data=core.domain.coach_turn_mapping(coach_turn),
            grounding_decision=grounding_decision,
            stop_reason=str(st.final_agent_meta.get("stop_reason") or ""),
            recovered_stop_reason=str(st.final_agent_meta.get("recovered_stop_reason") or ""),
            local_sequence_fallback=bool(st.final_agent_meta.get("local_sequence_fallback")),
        )
        core.domain.persist_recovered_plan_resume_after_turn(
            workspace_id=workspace_id,
            request=request,
            reply_content=st.full_content,
            agent_meta=st.final_agent_meta,
            coach_context=coach_turn.get("coach_context") if isinstance(coach_turn, dict) else None,
            recovered_status=state.snapshot.plan_runtime_status
            if isinstance(state.snapshot.plan_runtime_status, dict)
            else None,
        )
        state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.profile = runtime.repository.get_profile(workspace_id) or profile
        runtime.hydrate_plan_context(state.snapshot, workspace_id)
        coach_support.hydrate_snapshot(
            core.coach_support_deps,
            state.snapshot,
            response_language=request.response_language,
            answer_mode=request.answer_mode or (profile.answer_policy if profile else None),
            scenario=str(coach_turn["scenario"]),
            learner_signal=str(coach_turn["learner_signal"]),
            message=request.message,
            session_workspace_id=workspace_id,
        )
        if update_plan_on_turn:
            core.domain.update_snapshot_plan_from_turn(
                state=state,
                reply_content=st.full_content,
                coach_turn=core.domain.coach_turn_mapping(coach_turn),
                allow_formal_plan_mutation=core.domain.requires_formal_plan_commit(request),
            )
        if use_agent_stream and not guided_training_prefers_local_reply:
            stream_agent_meta: dict[str, object] = {
                "stop_reason": st.agent_stop_reason,
                "summary": st.agent_summary,
                "next_step": st.agent_next_step,
                "decision": st.agent_decision,
                "blocker": st.agent_blocker,
                "teaching_note": st.agent_teaching_note,
                "confidence": st.agent_confidence,
                "evidence": st.agent_evidence,
                "steps": st.agent_steps,
                "tool_events": st.agent_tool_events,
                "agentic": True,
                **(core.domain.normalize_attachment_delivery_payload(attachment_delivery) or {}),
            }
            if include_resume_thread_in_stream_meta:
                stream_agent_meta["resume_thread"] = st.agent_resume_thread
            st.final_agent_meta = merge_stream_agent_metadata(
                st.final_agent_meta,
                stream_agent_meta,
                preserve_failure=st.provider_failure_detected,
            )
        if core.domain.should_attach_auto_resource_events(st.final_agent_meta):
            st.final_agent_meta = core.domain.apply_auto_resource_agent_evidence(
                st.final_agent_meta,
                auto_resource_events,
            )
        built = coach_support.build_session_response(
            core.coach_support_deps,
            state=state,
            request=request,
            reply_content=st.full_content,
            artifacts=dict(coach_turn["artifacts"]),
            suggested_actions=list(coach_turn["suggested_actions"]),
            scenario=str(coach_turn["scenario"]),
            learner_signal=str(coach_turn["learner_signal"]),
            coach_turn_data=core.domain.coach_turn_mapping(coach_turn),
            agent_meta=st.final_agent_meta or None,
            attachment_delivery=attachment_delivery,
            streamed_prefix=st.streamed_reply_content if not st.provider_failure_detected else "",
        )
        return built, core.domain.json_object_payload(built)

    built_response, response_data = await asyncio.to_thread(_persist_and_build_coach)
    if original_intent is not None:
        response_data["artifacts"] = dict(coach_turn["artifacts"])
        response_data["intent"] = original_intent

    async def _maybe_finish_research(target_payload: dict[str, object]) -> None:
        if (
            prepare_research_turn is not None
            and isinstance(request, TurnRequest)
            and isinstance(built_response, SessionMessageResponse)
            and not st.provider_failure_detected
            and await finish_research_preparation(
                runtime,
                prepare_research_turn,
                request,
                built_response,
                workspace_id,
                coaching_service,
                stream_cancelled,
            )
        ):
            updated_response = core.domain.json_object_payload(built_response)
            target_payload.update(
                reply=updated_response["reply"],
                snapshot=updated_response["snapshot"],
            )

    async for frame in _commit_and_emit_complete_frame(
        runtime,
        core,
        st,
        state=state,
        workspace_id=workspace_id if original_intent is not None else state.workspace_id,
        response_data=response_data,
        coaching_service=coaching_service,
        stream_id=stream_id,
        request_id=request_id,
        stream_cancelled=stream_cancelled,
        publish_fn=publish_fn,
        post_save_hook=_maybe_finish_research if prepare_research_turn is not None else None,
    ):
        yield frame


def _register_session_message_stream_route(
    router: APIRouter,
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    *,
    session_message_handler: SessionMessageHandler,
) -> None:
    """Register /session/message/stream."""

    @router.post("/session/message/stream")
    async def session_message_stream(payload: dict, http_request: Request) -> StreamingResponse:
        core.domain._stream_snapshot_fields.set(
            "slim" if str(payload.get("fields") or "") == "slim" else "full"
        )
        stream_id = core.domain.resolve_stream_id(payload)
        request = SessionMessageRequest.model_validate(payload)
        workspace_id = core.domain.current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        core.domain.apply_host_workspace_trust_attestation(workspace_id, payload)
        observe_goal_for_request(runtime, request, workspace_id)
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        register_request_workspace_path(runtime, state.workspace_id, payload, request)
        profile = core.domain.resolved_profile(state.workspace_id)
        raw_requested_answer_mode = str(
            payload.get("answer_mode") or payload.get("answerMode") or ""
        ).strip()
        saved_answer_mode = str(
            core.domain.workspace_preferences(workspace_id).get("answer_mode") or ""
        ).strip()
        request = core.domain.request_with_workspace_defaults(
            request,
            workspace_id=workspace_id,
            profile=profile,
        )
        profile = core.domain.profile_with_teaching_style(profile, request.teaching_style)
        coaching_service = runtime.provider_service
        override_config = core.domain.provider_config_from_payload(payload)
        api_key_override = core.domain.provider_api_key_from_payload(payload)
        if override_config is not None or api_key_override is not None:
            coaching_service = runtime.provider_service_for(override_config, api_key_override)
        elif (workspace_service := runtime.workspace_provider_service(state.workspace_id)) is not None:
            coaching_service = workspace_service
        if coaching_service is not None:
            runtime.adopt_request_provider_evidence(request, coaching_service)
        core.domain.ensure_coach_provider_ready(
            coaching_service,
            response_language=request.response_language,
        )

        request_id = str(request.request_id or "").strip()
        request_key = (workspace_id, str(request.session_id or "").strip(), request_id)

        def _publish_stream_session_response(payload_map: dict[str, object]) -> dict[str, object]:
            if not request_id:
                return payload_map
            return publish_session_request_singleflight(
                request_key,
                payload_map,
                completed=core.domain.completed_session_requests,
                inflight=core.domain.inflight_session_requests,
                guard=core.domain.completed_session_requests_guard,
            )

        def _fail_stream_session_singleflight(error: BaseException) -> None:
            if not request_id:
                return
            wrapped = (
                error
                if isinstance(error, Exception)
                else RuntimeError(str(error) or "session message failed")
            )
            fail_session_request_singleflight(
                request_key,
                wrapped,
                inflight=core.domain.inflight_session_requests,
                guard=core.domain.completed_session_requests_guard,
            )

        if request_id:
            kind, cached_response, shared_future = claim_session_request_singleflight(
                request_key,
                completed=core.domain.completed_session_requests,
                inflight=core.domain.inflight_session_requests,
                guard=core.domain.completed_session_requests_guard,
            )
            if kind in ("wait", "cached"):
                return StreamingResponse(
                    _build_singleflight_waiter_stream(
                        runtime,
                        core,
                        kind=kind,
                        cached_response=cached_response,
                        shared_future=shared_future,
                        stream_id=stream_id,
                        request_id=request_id,
                        workspace_id=workspace_id,
                        session_id=request.session_id,
                        message=request.message,
                        request_key=request_key,
                        coaching_service=coaching_service,
                    ),
                    media_type="text/event-stream",
                )

        if coaching_service is not None:
            runtime.adopt_request_provider_evidence(request, coaching_service)
        if not core.domain.provider_is_live_usable(coaching_service, payload):
            turn_request = core.domain.turn_request_from_stream_payload(payload, intent="coach")
            core.domain.register_stream_cancellation(stream_id)
            return StreamingResponse(
                core.domain.honest_unusable_provider_stream(
                    turn_request,
                    payload,
                    stream_id=stream_id,
                    original_intent="coach",
                    http_request=http_request,
                    publish_complete=_publish_stream_session_response if request_id else None,
                    fail_inflight=_fail_stream_session_singleflight if request_id else None,
                ),
                media_type="text/event-stream",
            )

        try:
            core.domain.ensure_streaming_ready(coaching_service, request.response_language)
            core.domain.ensure_agent_tools_ready(request, coaching_service)
            active_service = cast(ProviderService, coaching_service)
            use_agent_stream = _resolve_agent_loop_enabled(
                request,
                active_service,
                stream=True,
                payload=payload,
            )
            attachment_delivery = core.domain.describe_request_attachment_delivery(
                request,
                active_service,
                use_agent_loop=use_agent_stream,
            )
            attachments_payload = [a.model_dump() for a in request.attachments]
            stream_recovery_requested = core.domain.resource_contract_stream_recovery_requested(
                request.message
            )
            learning_project_state = core.domain.workspace_learning_project_state(state.workspace_id)
        except BaseException as exc:
            _fail_stream_session_singleflight(exc)
            raise

        if learning_project_state.get("prompt_status") == "pending" and (
            core.domain.message_confirms_learning_project_folder(request.message)
            or core.domain.message_rejects_learning_project_folder(request.message)
        ):
            stream_recovery_requested = True

        stream_cancelled = _make_stream_cancelled_checker(
            core,
            stream_id=stream_id,
            http_request=http_request,
        )

        async def _recover_session_stream() -> dict[str, object]:
            nested_payload = dict(payload)
            nested_payload.pop("request_id", None)
            nested_payload.pop("requestId", None)
            response_data = await session_message_handler(nested_payload)
            response_payload = (
                {str(key): value for key, value in response_data.items()}
                if isinstance(response_data, dict)
                else core.domain.json_object_payload(response_data)
            )
            if "agent" not in response_payload and isinstance(
                response_payload.get("agent_meta"),
                dict,
            ):
                response_payload["agent"] = response_payload["agent_meta"]
            return response_payload

        async def _generate_session_stream() -> AsyncIterator[str]:
            st = StreamExecutionState(stream_started_at=time.perf_counter())
            session_lock_cm = runtime.acquire_session_lock(state.session_id)
            session_lock_entered = False
            try:
                await session_lock_cm.__aenter__()
                session_lock_entered = True
                if await stream_cancelled():
                    async for abort_frame in _emit_abort_for_cancellation(
                        core,
                        st,
                        stream_id=stream_id,
                        request_id=request_id,
                        publish_fn=_publish_stream_session_response,
                    ):
                        yield abort_frame
                    return
                yield core.domain.stream_status_event("preparing_context", stream_id)
                async for frame in _run_coach_lane_stream(
                    runtime,
                    core,
                    st,
                    state=state,
                    profile=profile,
                    request=request,
                    workspace_id=workspace_id,
                    coaching_service=active_service,
                    use_agent_stream=use_agent_stream,
                    attachment_delivery=attachment_delivery,
                    attachments_payload=attachments_payload,
                    stream_recovery_requested=stream_recovery_requested,
                    raw_requested_answer_mode=raw_requested_answer_mode,
                    saved_answer_mode=saved_answer_mode,
                    stream_id=stream_id,
                    request_id=request_id,
                    stream_cancelled=stream_cancelled,
                    publish_fn=_publish_stream_session_response,
                    recover_plain_stream_fn=_recover_session_stream,
                    synthesize_resume_thread=True,
                    include_resume_thread_in_stream_meta=True,
                    update_plan_on_turn=False,
                ):
                    yield frame
            except asyncio.CancelledError:
                logger.info("trainer_stream_cancelled", extra={"stream_id": stream_id})
                async for abort_frame in _emit_abort_for_cancellation(
                    core,
                    st,
                    stream_id=stream_id,
                    request_id=request_id,
                    publish_fn=_publish_stream_session_response,
                ):
                    yield abort_frame
                return
            except Exception as exc:
                async for abort_frame in _emit_abort_fail_closed(
                    core,
                    st,
                    stream_id=stream_id,
                    request_id=request_id,
                    publish_fn=_publish_stream_session_response,
                    error_detail=redact_provider_error(
                        exc,
                        api_key=getattr(active_service, "_api_key", None),
                    ),
                ):
                    yield abort_frame
            finally:
                if request_id and not st.stream_singleflight_published:
                    fail_session_request_singleflight(
                        request_key,
                        RuntimeError(
                            "session stream failed"
                            if st.stream_failed
                            else "session stream completed without publishing a payload"
                        ),
                        inflight=core.domain.inflight_session_requests,
                        guard=core.domain.completed_session_requests_guard,
                    )
                core.domain.finalize_stream_persistence(
                    state=state,
                    user_message=st.stream_user_message,
                    stream_id=stream_id,
                    committed=st.stream_committed,
                    assistant_message_ids=st.stream_assistant_message_ids,
                    stream_state=(
                        "completed"
                        if st.stream_committed
                        else ("failed" if st.stream_failed else "interrupted")
                    ),
                )
                core.domain.unregister_stream_cancellation(stream_id)
                if session_lock_entered:
                    await session_lock_cm.__aexit__(None, None, None)

        core.domain.register_stream_cancellation(stream_id)
        return StreamingResponse(_generate_session_stream(), media_type="text/event-stream")


def _register_turn_stream_route(
    router: APIRouter,
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    prepare_research_turn: PrepareResearchTurn,
) -> None:
    """Register /turn/stream."""

    @router.post("/turn/stream")
    async def turn_stream(payload: dict, http_request: Request) -> StreamingResponse:
        core.domain._stream_snapshot_fields.set(
            "slim" if str(payload.get("fields") or "") == "slim" else "full"
        )
        stream_id = core.domain.resolve_stream_id(payload)
        parsed_request = TurnRequest.model_validate(payload)
        core.domain.reject_blank_coach_message(parsed_request)
        request: TurnRequest = _normalize_resource_turn_request(parsed_request)
        original_intent = parsed_request.intent
        workspace_id = core.domain.current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        core.domain.apply_host_workspace_trust_attestation(workspace_id, payload)
        observe_goal_for_request(runtime, request, workspace_id)
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        register_request_workspace_path(runtime, state.workspace_id, payload, request)
        profile = core.domain.resolved_profile(state.workspace_id)
        raw_requested_answer_mode = str(
            payload.get("answer_mode") or payload.get("answerMode") or ""
        ).strip()
        saved_answer_mode = str(
            core.domain.workspace_preferences(workspace_id).get("answer_mode") or ""
        ).strip()
        request_with_defaults = core.domain.request_with_workspace_defaults(
            request,
            workspace_id=workspace_id,
            profile=profile,
        )
        if not isinstance(request_with_defaults, TurnRequest):
            raise TypeError("Workspace defaults did not produce a TurnRequest.")
        request = request_with_defaults
        profile = core.domain.profile_with_teaching_style(profile, request.teaching_style)
        coaching_service = core.domain.build_coaching_service(payload)
        core.domain.ensure_coach_provider_ready(
            coaching_service,
            response_language=request.response_language,
        )

        request_id = str(request.request_id or "").strip()
        request_key = (workspace_id, str(request.session_id or "").strip(), request_id)

        def _publish_stream_turn_response(payload_map: dict[str, object]) -> dict[str, object]:
            if not request_id:
                return payload_map
            return publish_session_request_singleflight(
                request_key,
                payload_map,
                completed=core.domain.completed_session_requests,
                inflight=core.domain.inflight_session_requests,
                guard=core.domain.completed_session_requests_guard,
            )

        def _fail_stream_turn_singleflight(error: BaseException) -> None:
            if not request_id:
                return
            wrapped = (
                error
                if isinstance(error, Exception)
                else RuntimeError(str(error) or "training turn failed")
            )
            fail_session_request_singleflight(
                request_key,
                wrapped,
                inflight=core.domain.inflight_session_requests,
                guard=core.domain.completed_session_requests_guard,
            )

        if request_id:
            kind, cached_response, shared_future = claim_session_request_singleflight(
                request_key,
                completed=core.domain.completed_session_requests,
                inflight=core.domain.inflight_session_requests,
                guard=core.domain.completed_session_requests_guard,
            )
            if kind in ("wait", "cached"):
                return StreamingResponse(
                    _build_singleflight_waiter_stream(
                        runtime,
                        core,
                        kind=kind,
                        cached_response=cached_response,
                        shared_future=shared_future,
                        stream_id=stream_id,
                        request_id=request_id,
                        workspace_id=workspace_id,
                        session_id=request.session_id,
                        message=request.message,
                        request_key=request_key,
                        coaching_service=coaching_service,
                    ),
                    media_type="text/event-stream",
                )

        if coaching_service is not None:
            runtime.adopt_request_provider_evidence(request, coaching_service)
        if not core.domain.provider_is_live_usable(coaching_service, payload):
            core.domain.register_stream_cancellation(stream_id)
            return StreamingResponse(
                core.domain.honest_unusable_provider_stream(
                    request,
                    payload,
                    stream_id=stream_id,
                    original_intent=original_intent,
                    http_request=http_request,
                    publish_complete=_publish_stream_turn_response if request_id else None,
                    fail_inflight=_fail_stream_turn_singleflight if request_id else None,
                ),
                media_type="text/event-stream",
            )

        try:
            core.domain.ensure_streaming_ready(coaching_service, request.response_language)
            core.domain.ensure_agent_tools_ready(request, coaching_service)
            active_service = cast(ProviderService, coaching_service)
            use_agent_stream = _resolve_agent_loop_enabled(
                request,
                active_service,
                stream=True,
                payload=payload,
            )
            stream_recovery_requested = core.domain.resource_contract_stream_recovery_requested(
                request.message
            )
            learning_project_state = core.domain.workspace_learning_project_state(state.workspace_id)
        except BaseException as exc:
            _fail_stream_turn_singleflight(exc)
            raise

        if learning_project_state.get("prompt_status") == "pending" and (
            core.domain.message_confirms_learning_project_folder(request.message)
            or core.domain.message_rejects_learning_project_folder(request.message)
        ):
            stream_recovery_requested = True

        stream_cancelled = _make_stream_cancelled_checker(
            core,
            stream_id=stream_id,
            http_request=http_request,
        )

        async def _recover_turn_coach_stream() -> dict[str, object]:
            fallback_response, fallback_artifacts, _ = await coach_support.execute_turn(
                core.coach_support_deps,
                request,
                payload,
                stream=False,
            )
            if isinstance(fallback_response, SessionMessageResponse):
                fallback_workspace_id = core.domain.current_workspace_id(
                    session_id=request.session_id,
                    workspace_id=request.workspace_id,
                )
                fallback_response.snapshot.memory = (
                    core.domain.repair_guided_lane_memory_snapshot_for_response(
                        runtime.memory_service.snapshot(fallback_workspace_id),
                        scenario=(
                            fallback_response.coach_turn.scenario
                            if fallback_response.coach_turn
                            else None
                        ),
                        response_language=request.response_language,
                        learner_message=request.message,
                    )
                )
                fallback_workspace_memory = (
                    fallback_response.snapshot.memory.workspace
                    if isinstance(fallback_response.snapshot.memory.workspace, dict)
                    else {}
                )
                coach_support.hydrate_snapshot(
                    core.coach_support_deps,
                    fallback_response.snapshot,
                    preserve_turn_coaching_state=True,
                    response_language=request.response_language
                    or str(fallback_workspace_memory.get("response_language") or "").strip()
                    or None,
                    answer_mode=(
                        str(fallback_workspace_memory.get("answer_mode") or "").strip()
                        or (
                            fallback_response.snapshot.profile.answer_policy
                            if fallback_response.snapshot.profile is not None
                            else None
                        )
                    ),
                    message=request.message,
                    session_workspace_id=fallback_workspace_id,
                )
            response_data = core.domain.json_object_payload(fallback_response)
            response_data["artifacts"] = fallback_artifacts
            response_data["intent"] = original_intent
            if "agent" not in response_data and isinstance(
                response_data.get("agent_meta"),
                dict,
            ):
                response_data["agent"] = response_data["agent_meta"]
            return response_data

        async def _generate_turn_stream() -> AsyncIterator[str]:
            st = StreamExecutionState(stream_started_at=time.perf_counter())
            resolved_state: SessionState = state
            resolved_service: ProviderService = active_service

            def _update_resolved(new_state: SessionState, new_service: ProviderService) -> None:
                nonlocal resolved_state, resolved_service
                resolved_state = new_state
                resolved_service = new_service

            session_lock_cm = runtime.acquire_session_lock(state.session_id)
            session_lock_entered = False
            try:
                await session_lock_cm.__aenter__()
                session_lock_entered = True
                if await stream_cancelled():
                    async for abort_frame in _emit_abort_for_cancellation(
                        core,
                        st,
                        stream_id=stream_id,
                        request_id=request_id,
                        publish_fn=_publish_stream_turn_response,
                    ):
                        yield abort_frame
                    return
                yield core.domain.stream_status_event("preparing_context", stream_id)
                if request.intent != "coach":
                    async for frame in _run_non_coach_prepared_turn_stream(
                        runtime,
                        core,
                        st,
                        request=request,
                        payload=payload,
                        original_intent=original_intent,
                        workspace_id=workspace_id,
                        raw_requested_answer_mode=raw_requested_answer_mode,
                        saved_answer_mode=saved_answer_mode,
                        stream_id=stream_id,
                        request_id=request_id,
                        stream_cancelled=stream_cancelled,
                        publish_fn=_publish_stream_turn_response,
                        set_resolved_state=_update_resolved,
                    ):
                        yield frame
                    return

                coach_ws_id = core.domain.current_workspace_id(
                    session_id=request.session_id,
                    workspace_id=request.workspace_id,
                )
                coach_service = cast(ProviderService, core.domain.build_coaching_service(payload))
                resolved_service = coach_service
                attachment_delivery = core.domain.describe_request_attachment_delivery(
                    request,
                    coach_service,
                    use_agent_loop=use_agent_stream,
                )
                attachments_payload = [a.model_dump() for a in request.attachments]
                async for frame in _run_coach_lane_stream(
                    runtime,
                    core,
                    st,
                    state=resolved_state,
                    profile=profile,
                    request=request,
                    workspace_id=coach_ws_id,
                    coaching_service=coach_service,
                    use_agent_stream=use_agent_stream,
                    attachment_delivery=attachment_delivery,
                    attachments_payload=attachments_payload,
                    stream_recovery_requested=stream_recovery_requested,
                    raw_requested_answer_mode=raw_requested_answer_mode,
                    saved_answer_mode=saved_answer_mode,
                    stream_id=stream_id,
                    request_id=request_id,
                    stream_cancelled=stream_cancelled,
                    publish_fn=_publish_stream_turn_response,
                    recover_plain_stream_fn=_recover_turn_coach_stream,
                    synthesize_resume_thread=False,
                    include_resume_thread_in_stream_meta=False,
                    update_plan_on_turn=True,
                    original_intent=original_intent,
                    prepare_research_turn=prepare_research_turn,
                ):
                    yield frame
            except asyncio.CancelledError:
                logger.info("trainer_stream_cancelled", extra={"stream_id": stream_id})
                async for abort_frame in _emit_abort_for_cancellation(
                    core,
                    st,
                    stream_id=stream_id,
                    request_id=request_id,
                    publish_fn=_publish_stream_turn_response,
                ):
                    yield abort_frame
                return
            except Exception as exc:
                async for abort_frame in _emit_abort_fail_closed(
                    core,
                    st,
                    stream_id=stream_id,
                    request_id=request_id,
                    publish_fn=_publish_stream_turn_response,
                    error_detail=redact_provider_error(
                        exc,
                        api_key=getattr(resolved_service, "_api_key", None),
                    ),
                ):
                    yield abort_frame
            finally:
                if request_id and not st.stream_singleflight_published:
                    fail_session_request_singleflight(
                        request_key,
                        RuntimeError(
                            "turn stream failed"
                            if st.stream_failed
                            else "turn stream completed without publishing a payload"
                        ),
                        inflight=core.domain.inflight_session_requests,
                        guard=core.domain.completed_session_requests_guard,
                    )
                core.domain.finalize_stream_persistence(
                    state=resolved_state,
                    user_message=st.stream_user_message,
                    stream_id=stream_id,
                    committed=st.stream_committed,
                    assistant_message_ids=st.stream_assistant_message_ids,
                    stream_state=(
                        "completed"
                        if st.stream_committed
                        else ("failed" if st.stream_failed else "interrupted")
                    ),
                )
                core.domain.unregister_stream_cancellation(stream_id)
                if session_lock_entered:
                    await session_lock_cm.__aexit__(None, None, None)

        core.domain.register_stream_cancellation(stream_id)
        return StreamingResponse(_generate_turn_stream(), media_type="text/event-stream")


def register_core_stream_routes(
    router: APIRouter,
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    prepare_research_turn: PrepareResearchTurn,
    *,
    session_message_handler: SessionMessageHandler,
) -> None:
    """Register /session/message/stream and /turn/stream in exact historical order."""
    _register_session_message_stream_route(
        router,
        runtime,
        core,
        session_message_handler=session_message_handler,
    )
    _register_turn_stream_route(router, runtime, core, prepare_research_turn)
