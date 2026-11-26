"""Shared primitives for decomposed core sidecar routes."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from ...core.event_ledger import EVENT_COACH_TURN_RECORDED
from ...core.models import (
    EvaluateCurrentFileRequest,
    EvaluateSnippetRequest,
    SessionMessageResponse,
    TurnRequest,
)
from ...llm.provider_service import ProviderService
from ...memory.workspace_recovery import leftover_formal_plan_is_live_for_fill
from ...training.card_generator import CardGenerationProviderFailure
from .._singleflight import remember_completed_request
from ..router_support import overlay_session_response_honesty_stamps
from ..routes.resources import PrepareResearchTurn
from ..runtime import TrainerRuntime

if TYPE_CHECKING:
    from .core import CoreRouteDeps

logger = logging.getLogger(__name__)

_BACKGROUND_TAIL_TASKS: set[asyncio.Task[Any]] = set()


def _schedule_background_tail(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> None:
    """Run non-critical post-stream work in the background without blocking the event loop."""

    async def _runner() -> None:
        try:
            if inspect.iscoroutinefunction(fn):
                await fn(*args, **kwargs)
            else:
                result = await asyncio.to_thread(fn, *args, **kwargs)
                if asyncio.iscoroutine(result):
                    await result
        except Exception:  # noqa: BLE001 - background tail must never crash the event loop
            logger.warning("trainer_stream_background_tail_failed", exc_info=True)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        fn(*args, **kwargs)
        return
    task = loop.create_task(_runner())
    _BACKGROUND_TAIL_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TAIL_TASKS.discard)


async def drain_background_tail_tasks(timeout: float = 3.0) -> None:
    """Await in-flight background tail writes during graceful sidecar shutdown."""
    pending = [task for task in list(_BACKGROUND_TAIL_TASKS) if not task.done()]
    if not pending:
        return
    _, still_running = await asyncio.wait(pending, timeout=max(0.1, timeout))
    for task in still_running:
        task.cancel()


def _build_stream_timings(
    *,
    stream_started_at: float,
    model_requested_at: float | None,
    provider_first_event_at: float | None,
    visible_first_at: float | None,
    finished_at: float,
) -> dict[str, float | None]:
    model_mark = model_requested_at if model_requested_at is not None else stream_started_at
    return {
        "local_prep_ms": round(max(0.0, (model_mark - stream_started_at) * 1000.0), 1),
        "provider_first_event_ms": (
            round(max(0.0, (provider_first_event_at - model_mark) * 1000.0), 1)
            if provider_first_event_at is not None
            else None
        ),
        "visible_ttft_ms": (
            round(max(0.0, (visible_first_at - stream_started_at) * 1000.0), 1)
            if visible_first_at is not None
            else None
        ),
        "total_ms": round(max(0.0, (finished_at - stream_started_at) * 1000.0), 1),
    }


def _record_coach_turn_event(
    runtime: TrainerRuntime,
    *,
    workspace_id: str,
    session_id: str,
    request_id: str,
    message: str,
) -> None:
    """Best-effort ledger entry for a finished coaching turn."""
    ledger = getattr(runtime, "event_ledger", None)
    if ledger is None:
        return
    fingerprint = hashlib.sha256(
        json.dumps({"session": session_id, "message": message}, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    try:
        ledger.record_event(
            EVENT_COACH_TURN_RECORDED,
            actor="coach",
            scope="coach",
            project_id=workspace_id,
            workspace_id=workspace_id,
            source_chain=["coach_turn"],
            payload_ref={
                "workspace_id": workspace_id,
                "session_id": session_id,
                "request_id": request_id,
            },
            reversibility="reversible",
            audit_note=f"Coach turn recorded ({fingerprint})",
            idempotency_key=f"coach_turn:{workspace_id}:{session_id}:{request_id or fingerprint}",
        )
    except Exception:
        return


def _card_generation_failure_response(exc: CardGenerationProviderFailure) -> HTTPException:
    if exc.reason == "provider_unavailable":
        return HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "5"})
    if exc.reason == "provider_quota_exhausted":
        return HTTPException(status_code=402, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


async def finish_research_preparation(
    runtime: TrainerRuntime,
    prepare_research_turn: PrepareResearchTurn,
    request: TurnRequest,
    response: SessionMessageResponse,
    workspace_id: str,
    provider: ProviderService,
    is_cancelled: Callable[[], Awaitable[bool]] | None = None,
) -> bool:
    if not await prepare_research_turn(request, response, workspace_id, provider, is_cancelled):
        return False
    evidence = response.reply.metadata["research_preparation"]
    state = runtime.ensure_session(response.session_id, workspace_id=workspace_id)
    catalog = runtime.memory_service.snapshot(workspace_id).asset_catalog
    for snapshot in (state.snapshot, response.snapshot):
        snapshot.memory = snapshot.memory.model_copy(update={"asset_catalog": catalog})
        for message in snapshot.messages:
            if message.id == response.reply.id:
                message.metadata["research_preparation"] = evidence
    runtime.save_session_state(state.session_id)
    return True


def observe_goal_for_request(runtime: TrainerRuntime, request: Any, workspace_id: str) -> Any:
    """Persist an explicit goal (or a conservative detection) for this turn."""
    state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
    if not request.session_id:
        # Later ensure_session(None) calls must land on this same session.
        request.session_id = state.session_id
    goal = runtime.goals().observe_turn(
        workspace_id=workspace_id,
        message=str(getattr(request, "message", "") or ""),
        intent=str(getattr(request, "intent", "coach") or "coach"),
        active_view=getattr(request, "active_view", None),
        goal_mode=bool(getattr(request, "goal_mode", False)),
        goal_text=getattr(request, "goal_text", None),
        session_id=state.session_id,
        plan=state.snapshot.plan,
    )
    if state.snapshot.goal != goal:
        state.snapshot.goal = goal
        runtime.save_session_state(state.session_id)
    return goal


def record_goal_evaluation(
    runtime: TrainerRuntime,
    workspace_id: str,
    request: EvaluateCurrentFileRequest | EvaluateSnippetRequest,
    report: Any,
) -> None:
    """Attribute one real evaluation to the active goal, idempotently."""
    content_hash = hashlib.sha256(
        str(getattr(request, "content", "") or "").encode("utf-8")
    ).hexdigest()[:16]
    card_id = str(getattr(request, "training_card_id", "") or "").strip()
    target = (
        card_id
        or str(getattr(request, "file_path", "") or "").strip()
        or str(getattr(request, "language_id", "") or "").strip()
        or "snippet"
    )
    evidence_refs = [f"evaluation:{content_hash}"]
    if card_id:
        evidence_refs.insert(0, f"training_card:{card_id}")
    runtime.goals().record_activity(
        workspace_id=workspace_id,
        kind="evaluation",
        summary=str(getattr(report, "summary", "") or getattr(report, "next_step", "") or ""),
        result="passed" if bool(getattr(report, "passed", False)) else "failed",
        concept=str(getattr(request, "training_card_title", "") or "").strip(),
        evidence_refs=evidence_refs,
        event_key=f"{target}:{content_hash}:{bool(getattr(report, 'passed', False))}",
    )
    runtime.publish_goal(workspace_id)


def overlay_completed_session_or_turn_response(
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    *,
    workspace_id: str,
    session_id: str | None,
    message: str,
    request_key: tuple[str, str, str],
    cached_response: dict[str, object],
) -> dict[str, object]:
    """Fail-closed honesty overlay for replayed or coalesced singleflight responses."""
    overlay_state = runtime.ensure_session(session_id, workspace_id=workspace_id)
    snapshot = overlay_state.snapshot
    pressure_blocks = core.domain.pressure_without_live_object_blocks_mint(
        workspace_id,
        snapshot=snapshot,
        current_task=snapshot.current_task,
        current_plan=snapshot.plan,
        message=message,
    )
    streak_blocks = core.domain.streak_without_live_object_blocks_mint(
        workspace_id,
        snapshot=snapshot,
        current_task=snapshot.current_task,
        current_plan=snapshot.plan,
    )
    live_status = (
        snapshot.plan_runtime_status
        if isinstance(snapshot.plan_runtime_status, dict)
        else {}
    )
    leftover_plan, leftover_runtime = core.domain.leftover_runtime_for_workspace(workspace_id)
    leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
    live_for_attach = bool(leftover_runtime) and leftover_formal_plan_is_live_for_fill(
        plan=snapshot.plan or leftover_plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
    )
    recovered_leftover = False
    if not live_for_attach:
        if leftover_plan is not None:
            recovered_leftover = True
        elif live_status.get("recovered") is True and snapshot.plan is None:
            recovered_leftover = True
    stamped = overlay_session_response_honesty_stamps(
        cached_response,
        pressure_blocks=pressure_blocks,
        streak_blocks=streak_blocks,
        recovered_leftover=recovered_leftover,
    )
    if stamped is not cached_response:
        remember_completed_request(
            core.domain.completed_session_requests,
            request_key,
            stamped,
            guard=core.domain.completed_session_requests_guard,
        )
    return stamped
