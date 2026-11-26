"""Training card lifecycle, streaming card generation, recall drills, and artifact/lab actions."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Literal, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...core.models import (
    ActiveCardSelectionResult,
    CardGenerationRequest,
    CardGenerationResponse,
    CardImportanceRequest,
    CardLibraryActionRequest,
    CardMergeRequest,
    CardPriorityRequest,
    CardStatusTransitionRequest,
    CardStatusTransitionResponse,
    DependencySkillMapActionRequest,
    DependencySkillMapRestoreRequest,
    FlashcardAnswerRequest,
    PracticeReturnRequest,
    ReviewArtifactActionRequest,
    ReviewArtifactRestoreRequest,
    ReviewQueueActionRequest,
    ScenarioLabActionRequest,
    ScenarioLabRestoreRequest,
    TheoryDrillAnswerRequest,
    TheoryDrillRestoreRequest,
    TrainingCardCandidateSnapshot,
)
from ...llm.provider_service import ProviderService, redact_provider_error
from ...training.card_generator import CardGenerationProviderFailure
from ...training.recall_evidence import record_recall_evidence
from ...training.reliability import busy_marker, should_replay
from .._helpers import localized_text
from .._singleflight import (
    claim_session_request_singleflight,
    fail_session_request_singleflight,
    publish_session_request_singleflight,
)
from ..runtime import TrainerRuntime, _provider_test_record_matches
from .core_shared import _card_generation_failure_response

if TYPE_CHECKING:
    from .core import CoreRouteDeps

logger = logging.getLogger(__name__)


async def _waiter_training_card_stream(
    core: CoreRouteDeps,
    *,
    kind: Literal["wait", "cached"],
    cached_response: dict[str, object] | None,
    shared_future: asyncio.Future[dict[str, object]] | None,
    stream_id: str,
    request_id: str,
    training_provider_service: ProviderService | None,
) -> AsyncIterator[str]:
    try:
        shared_payload: dict[str, object]
        if kind == "wait":
            assert shared_future is not None
            shared_payload = cast("dict[str, object]", await shared_future)
        else:
            assert cached_response is not None
            shared_payload = cached_response
        reliability = shared_payload.get("reliability")
        reliability_outcome = (
            str(reliability.get("outcome") or "") if isinstance(reliability, dict) else ""
        )
        yield core.domain.sse_complete_frame(
            tokens=0,
            response_data=shared_payload,
            stream_id=stream_id,
            request_id=request_id or None,
            provider_live_usable=reliability_outcome != "failure",
            provider_failure_detected=reliability_outcome == "failure",
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
        yield core.domain.stream_status_event("failed", stream_id)
        yield core.domain.stream_status_event("acked", stream_id)
        redacted_err = redact_provider_error(
            exc,
            api_key=getattr(training_provider_service, "_api_key", None),
        )
        yield (
            "event: error\n"
            f"data: {json.dumps({'error': redacted_err, 'stream_id': stream_id, 'terminal': True})}\n\n"
        )
        yield core.domain.sse_complete_frame(
            tokens=0,
            response_data=failure_payload,
            stream_id=stream_id,
            outcome="failure",
            request_id=request_id or None,
            provider_failure_detected=True,
        )


async def _run_training_card_owner_stream(
    core: CoreRouteDeps,
    *,
    request: CardGenerationRequest,
    training_provider_service: ProviderService | None,
    stream_id: str,
    stream_id_payload: dict[str, str],
    request_id: str,
    request_key: tuple[str, str, str] | None,
    publish_fn: Callable[[dict[str, object]], dict[str, object]],
    fail_fn: Callable[[BaseException], None],
) -> AsyncIterator[str]:
    token_count = 0
    generated_card: TrainingCardCandidateSnapshot | None = None
    stream_singleflight_published = False

    async def _abort_fail_closed(*, error_detail: object | None = None) -> AsyncIterator[str]:
        nonlocal stream_singleflight_published
        failure_payload: dict[str, object] = core.domain.attach_operation_reliability(
            {},
            phase="acked",
            outcome="failure",
            request_id=request_id or None,
        )
        if request_key is not None and not stream_singleflight_published:
            failure_payload = publish_fn(failure_payload)
            stream_singleflight_published = True
        yield core.domain.stream_status_event("failed", stream_id)
        if error_detail is not None:
            yield (
                "event: error\n"
                f"data: {json.dumps({'error': error_detail, 'stream_id': stream_id, 'terminal': True, **stream_id_payload})}\n\n"
            )
        yield core.domain.stream_status_event("acked", stream_id)
        yield core.domain.sse_complete_frame(
            tokens=token_count,
            response_data=failure_payload,
            stream_id=stream_id,
            outcome="failure",
            request_id=request_id or None,
            provider_failure_detected=True,
        )

    try:
        if core.domain.stream_cancellation_requested(stream_id):
            async for abort_frame in _abort_fail_closed():
                yield abort_frame
            return
        generator = core.domain.card_generation_service_for(training_provider_service)
        trusted_request = core.domain.trusted_training_card_request_from_api(request)
        request_payload = core.domain.prepare_training_card_request(trusted_request)
        existing_card = (
            core.domain.existing_open_resource_training_card(request_payload)
            if request_payload.source == "resource_knowledge" and request_payload.resource_id
            else None
        )
        if existing_card is not None:
            if core.domain.stream_cancellation_requested(stream_id):
                async for abort_frame in _abort_fail_closed():
                    yield abort_frame
                return
            response = await asyncio.to_thread(
                core.domain.training_generate_candidate,
                trusted_request,
                provider_service_override=training_provider_service,
            )
            response_data = response.model_dump(mode="json")
            response_data = core.domain.attach_operation_reliability(
                response_data,
                phase="acked",
                outcome="success",
                request_id=request_id or None,
            )
            if request_key is not None:
                response_data = publish_fn(response_data)
                stream_singleflight_published = True
            yield core.domain.sse_complete_frame(
                tokens=0,
                response_data=response_data,
                stream_id=stream_id,
                request_id=request_id or None,
            )
            return

        async for event in generator.generate_card_stream(
            request_payload.source,
            request_payload,
            cancel_event=core.domain.stream_cancellation_events.get(stream_id),
        ):
            if core.domain.stream_cancellation_requested(stream_id):
                async for abort_frame in _abort_fail_closed():
                    yield abort_frame
                return
            if event.chunk:
                token_count += 1
                yield f"data: {json.dumps({'chunk': event.chunk, **stream_id_payload})}\n\n"
            if event.card is not None:
                generated_card = event.card

        if core.domain.stream_cancellation_requested(stream_id):
            async for abort_frame in _abort_fail_closed():
                yield abort_frame
            return
        if generated_card is None:
            raise RuntimeError("Card generation stream ended without a card.")
        response = core.domain.training_generate_candidate(
            trusted_request,
            generated_card=generated_card,
            provider_service_override=training_provider_service,
        )
        response_data = response.model_dump(mode="json")
        response_data = core.domain.attach_operation_reliability(
            response_data,
            phase="acked",
            outcome="success",
            request_id=request_id or None,
        )
        if request_key is not None:
            response_data = publish_fn(response_data)
            stream_singleflight_published = True
        yield core.domain.sse_complete_frame(
            tokens=token_count,
            response_data=response_data,
            stream_id=stream_id,
            request_id=request_id or None,
        )
    except asyncio.CancelledError:
        logger.info("trainer_training_card_stream_cancelled", extra={"stream_id": stream_id})
        async for abort_frame in _abort_fail_closed():
            yield abort_frame
        return
    except Exception as exc:
        error = exc.detail if isinstance(exc, HTTPException) else exc
        async for abort_frame in _abort_fail_closed(
            error_detail=redact_provider_error(
                error,
                api_key=getattr(training_provider_service, "_api_key", None),
            ),
        ):
            yield abort_frame
    finally:
        if request_key is not None and not stream_singleflight_published:
            fail_fn(RuntimeError("training generate-card stream completed without publishing"))
        core.domain.unregister_stream_cancellation(stream_id)


def _register_training_card_routes(
    router: APIRouter,
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
) -> None:
    """Register training card status, metadata, generation, and active-card routes."""

    @router.post("/training/card-status", response_model=CardStatusTransitionResponse)
    def training_card_status(request: CardStatusTransitionRequest) -> CardStatusTransitionResponse:
        if request.new_status in {"implemented", "completed"}:
            raise HTTPException(
                status_code=422,
                detail="Use current-file verification before marking a training card implemented or completed.",
            )
        reliability = runtime.memory_service.latest_training_reliability(request.workspace_id)
        status_replay = bool(
            isinstance(reliability, dict)
            and should_replay(reliability, request.request_id, request.idempotency_key)
            and str(reliability.get("command_id") or "") == "trainer.training.cardStatusTransition"
            and str(reliability.get("card_id") or "") == request.card_id
        )
        if not status_replay:
            core.domain.require_live_selected_card_for_status(request.workspace_id, request.card_id)
        if request.cancel:
            try:
                runtime.memory_service.cancel_training_reliability(
                    request.workspace_id,
                    request_id=request.request_id,
                    command_id="trainer.training.cardStatusTransition",
                    card_id=request.card_id,
                )
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            card = runtime.memory_service.get_card(request.workspace_id, request.card_id)
            if card is None:
                raise HTTPException(status_code=404, detail="Training card not found.")
            core.domain.refresh_workspace_sessions(request.workspace_id)
            return CardStatusTransitionResponse(card=card)

        captured: list[CardStatusTransitionResponse] = []

        def work() -> dict[str, object]:
            captured.append(
                runtime.memory_service.transition_card_status(
                    request.workspace_id,
                    request.card_id,
                    request.new_status,
                    reason=request.reason,
                )
            )
            structured = runtime.memory_service._structured_for(request.workspace_id)
            return dict(structured._workspace)

        try:
            reliability_workspace = runtime.memory_service.run_training_reliability(
                request.workspace_id,
                request_id=request.request_id,
                command_id="trainer.training.cardStatusTransition",
                card_id=request.card_id,
                idempotency_key=request.idempotency_key,
                revision=request.revision,
                timeout_ms=request.timeout_ms,
                cancel=False,
                work=work,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        core.domain.refresh_workspace_sessions(request.workspace_id)
        busy = busy_marker(reliability_workspace)
        if busy is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "training_reliability_busy",
                    "message": (
                        "Another training save is still running in this workspace. "
                        "The card was not changed; retry once it finishes."
                    ),
                    **busy,
                },
            )
        if not captured:
            card = runtime.memory_service.get_card(request.workspace_id, request.card_id)
            if card is None:
                raise HTTPException(status_code=404, detail="Training card not found.")
            return CardStatusTransitionResponse(card=card)
        return captured[0]

    @router.post("/training/card/importance", response_model=CardStatusTransitionResponse)
    def training_card_importance(request: CardImportanceRequest) -> CardStatusTransitionResponse:
        try:
            with core.domain.training_card_lock(request.workspace_id):
                card = runtime.memory_service.set_card_importance(
                    request.workspace_id,
                    request.card_id,
                    request.important,
                )
        except ValueError as exc:
            message = str(exc)
            status_code = 404 if "not found" in message else 422
            raise HTTPException(status_code=status_code, detail=message) from exc
        core.domain.refresh_workspace_sessions(request.workspace_id)
        return card

    @router.post("/training/card/priority", response_model=CardStatusTransitionResponse)
    def training_card_priority(request: CardPriorityRequest) -> CardStatusTransitionResponse:
        try:
            with core.domain.training_card_lock(request.workspace_id):
                card = runtime.memory_service.set_card_priority(
                    request.workspace_id,
                    request.card_id,
                    request.priority,
                )
        except ValueError as exc:
            message = str(exc)
            status_code = 404 if "not found" in message else 422
            raise HTTPException(status_code=status_code, detail=message) from exc
        core.domain.refresh_workspace_sessions(request.workspace_id)
        return card

    @router.post("/training/cards/merge", response_model=CardStatusTransitionResponse)
    def training_cards_merge(request: CardMergeRequest) -> CardStatusTransitionResponse:
        try:
            with core.domain.training_card_lock(request.workspace_id):
                card = runtime.memory_service.merge_training_cards(
                    request.workspace_id,
                    request.keep_card_id,
                    request.duplicate_card_ids,
                )
        except ValueError as exc:
            message = str(exc)
            status_code = 404 if "not found" in message else 422
            raise HTTPException(status_code=status_code, detail=message) from exc
        core.domain.refresh_workspace_sessions(request.workspace_id)
        return card

    @router.post("/training/card/library", response_model=CardStatusTransitionResponse)
    def training_card_library(request: CardLibraryActionRequest) -> CardStatusTransitionResponse:
        try:
            return core.domain.training_card_library_action(request)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/training/generate-card", response_model=CardGenerationResponse)
    def training_generate_card(request: CardGenerationRequest) -> CardGenerationResponse:
        generate_payload: dict[str, object] = {
            "workspace_id": request.workspace_id,
        }
        if isinstance(request.provider, dict) and request.provider:
            generate_payload["provider"] = request.provider
        if request.api_key:
            generate_payload["api_key"] = request.api_key
        if request.last_test_result:
            generate_payload["lastTestResult"] = request.last_test_result
        coaching_service = core.domain.build_coaching_service(generate_payload)
        last_test = request.last_test_result
        if isinstance(last_test, dict) and last_test.get("ok") is True:
            config = getattr(coaching_service, "_config", None)
            if config is not None and not _provider_test_record_matches(last_test, config):
                raise HTTPException(
                    status_code=400,
                    detail=localized_text(
                        "This connection is not ready. Test it in Settings, then resend this turn.",
                        "当前连接还不能用。请先在设置里测试，再重发这一轮。",
                        getattr(request, "response_language", None),
                    ),
                )
        core.domain.ensure_coach_provider_ready(
            coaching_service,
            response_language=getattr(request, "response_language", None),
        )
        core.domain.reject_if_provider_not_live_usable(
            coaching_service,
            generate_payload,
            getattr(request, "response_language", None),
        )
        try:
            return core.domain.training_generate_candidate(
                core.domain.trusted_training_card_request_from_api(request),
                provider_service_override=coaching_service,
            )
        except CardGenerationProviderFailure as exc:
            raise _card_generation_failure_response(exc) from exc

    @router.post("/training/generate-card/stream")
    async def training_generate_card_stream(
        request: CardGenerationRequest,
        http_request: Request,
    ) -> StreamingResponse:
        try:
            raw_payload = await http_request.json()
        except Exception:
            raw_payload = {}
        stream_payload = raw_payload if isinstance(raw_payload, dict) else {}
        training_provider_service = runtime.overlay_last_test_on_service(
            core.domain.build_coaching_service(stream_payload)
        )
        if training_provider_service is not None:
            runtime.adopt_request_provider_evidence(request, training_provider_service)
            last_test = request.last_test_result
            if isinstance(last_test, dict) and last_test.get("ok") is True:
                config = getattr(training_provider_service, "_config", None)
                if config is not None and not _provider_test_record_matches(last_test, config):
                    raise HTTPException(
                        status_code=400,
                        detail=localized_text(
                            "This connection is not ready. Test it in Settings, then resend this turn.",
                            "当前连接还不能用。请先在设置里测试，再重发这一轮。",
                            getattr(request, "response_language", None),
                        ),
                    )
        core.domain.ensure_coach_provider_ready(
            training_provider_service,
            response_language=getattr(request, "response_language", None),
        )
        core.domain.reject_if_provider_not_live_usable(
            training_provider_service,
            stream_payload,
            getattr(request, "response_language", None),
        )
        core.domain.ensure_streaming_ready(
            training_provider_service,
            getattr(request, "response_language", None),
        )
        stream_id = core.domain.resolve_stream_id(raw_payload)
        stream_id_payload = (
            {"stream_id": stream_id}
            if isinstance(raw_payload, dict)
            and str(raw_payload.get("stream_id") or raw_payload.get("streamId") or "").strip()
            else {}
        )
        request_id = str(getattr(request, "request_id", "") or "").strip()
        if not request_id and isinstance(raw_payload, dict):
            request_id = str(
                raw_payload.get("request_id") or raw_payload.get("requestId") or ""
            ).strip()
        workspace_id = str(getattr(request, "workspace_id", "") or "").strip()
        request_key = (workspace_id, "generate-card", request_id) if request_id else None

        def _publish_training_card_stream_response(payload: dict[str, object]) -> dict[str, object]:
            if request_key is None:
                return payload
            return publish_session_request_singleflight(
                request_key,
                payload,
                completed=core.domain.completed_training_card_requests,
                inflight=core.domain.inflight_training_card_requests,
                guard=core.domain.completed_training_card_requests_guard,
            )

        def _fail_training_card_stream_singleflight(error: BaseException) -> None:
            if request_key is None:
                return
            fail_session_request_singleflight(
                request_key,
                error,
                inflight=core.domain.inflight_training_card_requests,
                guard=core.domain.completed_training_card_requests_guard,
            )

        if request_key is not None:
            kind, cached_response, shared_future = claim_session_request_singleflight(
                request_key,
                completed=core.domain.completed_training_card_requests,
                inflight=core.domain.inflight_training_card_requests,
                guard=core.domain.completed_training_card_requests_guard,
            )
            if kind in ("wait", "cached"):
                return StreamingResponse(
                    _waiter_training_card_stream(
                        core,
                        kind=kind,
                        cached_response=cached_response,
                        shared_future=shared_future,
                        stream_id=stream_id,
                        request_id=request_id,
                        training_provider_service=training_provider_service,
                    ),
                    media_type="text/event-stream",
                )

        core.domain.register_stream_cancellation(stream_id)
        return StreamingResponse(
            _run_training_card_owner_stream(
                core,
                request=request,
                training_provider_service=training_provider_service,
                stream_id=stream_id,
                stream_id_payload=stream_id_payload,
                request_id=request_id,
                request_key=request_key,
                publish_fn=_publish_training_card_stream_response,
                fail_fn=_fail_training_card_stream_singleflight,
            ),
            media_type="text/event-stream",
        )

    @router.get("/training/active-card", response_model=ActiveCardSelectionResult)
    def training_active_card(
        workspace_id: str,
        session_id: str | None = None,
    ) -> ActiveCardSelectionResult:
        resolved_workspace_id = core.domain.current_workspace_id(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        selection = core.domain.select_active_training_card(resolved_workspace_id)
        snapshot = runtime.memory_service.snapshot(resolved_workspace_id)
        existing = snapshot.active_training_card_routing
        if core.domain.routing_changed(existing, selection):
            runtime.memory_service.persist_active_card_selection(resolved_workspace_id, selection)
            core.domain.refresh_workspace_sessions(resolved_workspace_id)
        return runtime.memory_service.snapshot(resolved_workspace_id).active_training_card_routing or selection


def _register_training_drill_and_artifact_routes(
    router: APIRouter,
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
) -> None:
    """Register flashcard, theory drill, practice return, review, lab, and skill-map routes."""

    @router.post("/training/flashcard/answer")
    def training_flashcard_answer(request: FlashcardAnswerRequest) -> dict[str, object]:
        attempt = runtime.memory_service.submit_flashcard_answer(
            request.workspace_id,
            request.card_id,
            learner_answer=request.learner_answer,
            selected_option_index=request.selected_option_index,
            selected_option_indices=request.selected_option_indices,
            fill_blank_answers=request.fill_blank_answers,
            sort_order=request.sort_order,
        )
        core.domain.refresh_workspace_sessions(request.workspace_id)
        card = runtime.memory_service.get_card(request.workspace_id, request.card_id)
        recall_evidence = record_recall_evidence(
            runtime,
            workspace_id=request.workspace_id,
            card_id=request.card_id,
            correct=attempt.correct,
            source="flashcard",
            answer_mode=attempt.answer_mode,
            detail=attempt.detail,
            assistance_level="none",
            immediate_dimension="delayed_recall",
        )
        return {
            "correct": attempt.correct,
            "score": attempt.score,
            "detail": attempt.detail,
            "feedback": attempt.feedback,
            "card_status": card.status if card is not None else None,
            "retry_required": not attempt.correct,
            "attempt": attempt.model_dump(mode="json"),
            "recall_evidence": recall_evidence,
        }

    @router.post("/training/theory-drill/answer")
    def training_theory_drill_answer(request: TheoryDrillAnswerRequest) -> dict[str, object]:
        snapshot = runtime.memory_service.snapshot(request.workspace_id)
        theory_drill = snapshot.theory_drill
        if theory_drill is None:
            raise HTTPException(
                status_code=404,
                detail="No current theory drill was found. Refresh Training and start a new drill.",
            )
        if theory_drill.id != request.theory_drill_id:
            raise HTTPException(
                status_code=409,
                detail="This theory drill is no longer current. Refresh Training to load the latest drill.",
            )
        question = next(
            (item for item in theory_drill.questions if item.id == request.question_id),
            None,
        )
        if question is None:
            raise HTTPException(
                status_code=409,
                detail="This theory question is no longer current. Refresh Training to load the latest question.",
            )
        answer = re.sub(r"\s+", " ", request.learner_answer.strip().lower())
        reference = re.sub(r"\s+", " ", question.answer.strip().lower())
        if not reference:
            raise HTTPException(
                status_code=409,
                detail="This theory question has no answer key yet. Refresh Training to load a gradeable question.",
            )
        reference_tokens = {
            token for token in re.findall(r"[a-z0-9][a-z0-9_-]*", reference) if len(token) > 2
        }
        prompt_tokens = {
            token
            for token in re.findall(r"[a-z0-9][a-z0-9_-]*", question.prompt.lower())
            if len(token) > 2
        }
        answer_tokens = {
            token for token in re.findall(r"[a-z0-9][a-z0-9_-]*", answer) if len(token) > 2
        }
        grounded_terms = reference_tokens | prompt_tokens
        dependency_hint = re.sub(r"[^a-z0-9]+", "", question.dependency_key.lower())
        normalized_answer = re.sub(r"[^a-z0-9]+", "", answer)
        has_dependency_context = bool(dependency_hint and dependency_hint in normalized_answer)
        correct = bool(
            answer
            and (
                answer == reference
                or reference in answer
                or (has_dependency_context and len(answer_tokens & grounded_terms) >= 2)
                or (not dependency_hint and len(answer_tokens & grounded_terms) >= 2)
            )
        )
        detail = (
            "Theory drill answer is grounded enough to continue."
            if correct
            else "Answer is still too thin; rebuild the explanation before widening scope."
        )
        if correct:
            updated, _ = runtime.memory_service.apply_theory_drill_action(
                request.workspace_id,
                theory_drill_id=request.theory_drill_id,
                action="reopen",
                note="Theory drill answer recorded.",
            )
            if updated is None:
                raise HTTPException(
                    status_code=409,
                    detail="This theory drill changed before the answer could be saved. Refresh Training and try again.",
                )
        recall_evidence = record_recall_evidence(
            runtime,
            workspace_id=request.workspace_id,
            card_id=theory_drill.id,
            correct=correct,
            source="theory_drill",
            answer_mode="text",
            detail=detail,
            immediate_dimension="comprehension",
            allow_missing_card=True,
        )
        core.domain.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": True,
            "detail": detail,
            "correct": correct,
            "recall_evidence": recall_evidence,
        }

    @router.post("/training/practice-return")
    def training_practice_return(request: PracticeReturnRequest) -> dict[str, object]:
        card = runtime.memory_service.get_card(request.workspace_id, request.card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="Training card not found.")
        manual_verification = (
            str(getattr(card, "learning_subtype", "") or "").strip().lower()
            in {"reading", "writing", "derivation", "memorization", "orientation", "project_orientation"}
            or str(getattr(card, "verification_method", "") or "").strip().lower() == "manual"
        )
        updated = runtime.memory_service.record_training_practice_evaluation_result(
            workspace_id=request.workspace_id,
            card_id=request.card_id,
            passed=request.passed,
            summary=request.summary,
            next_step=request.next_step,
            focus_area=request.focus_area,
            failed_checks=request.failed_checks,
            missing_requirements=request.missing_requirements,
            evidence_source=request.evidence_source,
            verified_by_evaluator=False,
            manual_verification=manual_verification,
            request_id=request.request_id,
            idempotency_key=request.idempotency_key,
            revision=request.revision,
            timeout_ms=request.timeout_ms,
            cancel=request.cancel,
        )
        busy = busy_marker(updated)
        if busy is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "training_reliability_busy",
                    "message": (
                        "Another training save is still running in this workspace. "
                        "The practice result was not recorded; retry once it finishes."
                    ),
                    **busy,
                },
            )
        core.domain.refresh_workspace_sessions(request.workspace_id)
        return {"ok": True, "workspace": updated}

    @router.post("/training/review-queue/action")
    def training_review_queue_action(request: ReviewQueueActionRequest) -> dict[str, object]:
        actions = runtime.memory_service.apply_review_queue_action(
            request.workspace_id,
            concept=request.concept,
            action=request.action,
            scope=request.scope,
            focus_area=request.focus_area,
            task_hint=request.task_hint,
            note=request.note,
            batch_limit=request.batch_limit,
        )
        core.domain.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": True,
            "detail": f"Applied review queue action '{request.action}'.",
            "actions": [item.model_dump(mode="json") for item in actions],
        }

    @router.post("/training/review-artifact/action")
    def training_review_artifact_action(request: ReviewArtifactActionRequest) -> dict[str, object]:
        artifact, history = runtime.memory_service.apply_review_artifact_action(
            request.workspace_id,
            review_artifact_id=request.review_artifact_id,
            action=request.action,
            note=request.note,
            edit_patch=request.edit_patch,
        )
        core.domain.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": artifact is not None,
            "detail": "Review result saved." if artifact is not None else "Review item was not found.",
            "review_artifact": artifact.model_dump(mode="json") if artifact is not None else None,
            "history": [item.model_dump(mode="json") for item in history],
        }

    @router.post("/training/scenario-lab/action")
    def training_scenario_lab_action(request: ScenarioLabActionRequest) -> dict[str, object]:
        try:
            scenario_lab, history = runtime.memory_service.apply_scenario_lab_action(
                request.workspace_id,
                scenario_lab_id=request.scenario_lab_id,
                action=request.action,
                note=request.note,
                review_outcome=request.review_outcome,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if scenario_lab is None:
            raise HTTPException(
                status_code=409,
                detail="This scenario lab is no longer current. Refresh Training to load the current lab.",
            )
        core.domain.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": True,
            "detail": "Scenario lab updated.",
            "scenario_lab": scenario_lab.model_dump(mode="json"),
            "history": [item.model_dump(mode="json") for item in history],
        }

    @router.post("/training/scenario-lab/restore")
    def training_scenario_lab_restore(request: ScenarioLabRestoreRequest) -> dict[str, object]:
        scenario_lab, history = runtime.memory_service.restore_scenario_lab_history(
            request.workspace_id,
            scenario_lab_id=request.scenario_lab_id,
            history_entry_id=request.history_entry_id,
            history_version=request.history_version,
            note=request.note,
        )
        core.domain.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": scenario_lab is not None,
            "scenario_lab": scenario_lab.model_dump(mode="json") if scenario_lab is not None else None,
            "history": [item.model_dump(mode="json") for item in history],
        }

    @router.post("/training/theory-drill/restore")
    def training_theory_drill_restore(request: TheoryDrillRestoreRequest) -> dict[str, object]:
        theory_drill, history = runtime.memory_service.restore_theory_drill_history(
            request.workspace_id,
            theory_drill_id=request.theory_drill_id,
            history_entry_id=request.history_entry_id,
            history_version=request.history_version,
            note=request.note,
        )
        core.domain.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": theory_drill is not None,
            "theory_drill": theory_drill.model_dump(mode="json") if theory_drill is not None else None,
            "history": [item.model_dump(mode="json") for item in history],
        }

    @router.post("/training/review-artifact/restore")
    def training_review_artifact_restore(request: ReviewArtifactRestoreRequest) -> dict[str, object]:
        artifact, history = runtime.memory_service.restore_review_artifact_history(
            request.workspace_id,
            review_artifact_id=request.review_artifact_id,
            history_entry_id=request.history_entry_id,
            history_version=request.history_version,
            note=request.note,
        )
        core.domain.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": artifact is not None,
            "review_artifact": artifact.model_dump(mode="json") if artifact is not None else None,
            "history": [item.model_dump(mode="json") for item in history],
        }

    @router.post("/training/dependency-skill-map/action")
    def training_dependency_skill_map_action(
        request: DependencySkillMapActionRequest,
    ) -> dict[str, object]:
        workspace_id = core.domain.current_workspace_id(workspace_id=request.workspace_id)
        action = request.action.strip()
        if action in {"mark_practiced", "mark_applied", "mark_transferable"}:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Run Verify current file before Trainer updates dependency mastery. "
                    "Your current stage has not changed."
                ),
            )
        try:
            maps, history, scenario_lab = runtime.memory_service.apply_dependency_skill_map_action(
                workspace_id,
                dependency_key=request.dependency_key,
                action=action,
                note=request.note,
                focus_item_key=request.focus_item_key,
                related_api=request.related_api,
                scenario=request.scenario,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not maps or not history:
            raise HTTPException(
                status_code=409,
                detail="Dependency skill map changed before the action could be saved. Refresh Training and try again.",
            )
        core.domain.refresh_workspace_sessions(workspace_id)
        return {
            "ok": True,
            "detail": (
                "Trainer is waiting for current-file verification before changing dependency mastery."
                if action == "request_verification"
                else "Dependency training action recorded."
            ),
            "maps": [item.model_dump(mode="json") for item in maps],
            "history": [item.model_dump(mode="json") for item in history],
            "scenario_lab": scenario_lab.model_dump(mode="json") if scenario_lab is not None else None,
        }

    @router.post("/training/dependency-skill-map/restore")
    def training_dependency_skill_map_restore(
        request: DependencySkillMapRestoreRequest,
    ) -> dict[str, object]:
        workspace_id = core.domain.current_workspace_id(workspace_id=request.workspace_id)
        maps, history = runtime.memory_service.restore_dependency_skill_map_history(
            workspace_id,
            dependency_key=request.dependency_key,
            history_entry_id=request.history_entry_id,
            note=request.note,
        )
        core.domain.refresh_workspace_sessions(workspace_id)
        return {
            "ok": bool(maps),
            "maps": [item.model_dump(mode="json") for item in maps],
            "history": [item.model_dump(mode="json") for item in history],
        }


def register_core_training_routes(
    router: APIRouter,
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
) -> None:
    """Register training card, streaming card generation, drill, and review routes."""
    _register_training_card_routes(router, runtime, core)
    _register_training_drill_and_artifact_routes(router, runtime, core)
