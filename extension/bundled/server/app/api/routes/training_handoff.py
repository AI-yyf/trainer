from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from ...core.models import (
    TrainingHandoffActionResponse,
    TrainingHandoffReflectionRequest,
    TrainingHandoffReturnRequest,
    TrainingReliabilityControlRequest,
)
from ..runtime import TrainerRuntime
from ..training_card_identity import require_live_selected_card_for_status


def build_training_handoff_router(
    runtime: TrainerRuntime,
    refresh_workspace_sessions: Callable[[str], None] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["training"])

    def refresh(workspace_id: str) -> None:
        if refresh_workspace_sessions is not None:
            refresh_workspace_sessions(workspace_id)
            return
        for state in runtime.sessions.values():
            if state.workspace_id != workspace_id:
                continue
            state.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
            state.snapshot.profile = runtime.repository.get_profile(workspace_id)
            runtime.hydrate_plan_context(state.snapshot, workspace_id)
            runtime.save_session_state(state.session_id)

    @router.post("/training/reflect", response_model=TrainingHandoffActionResponse)
    def reflect_training_handoff(
        request: TrainingHandoffReflectionRequest,
    ) -> TrainingHandoffActionResponse:
        require_live_selected_card_for_status(runtime, request.workspace_id, request.card_id)
        if runtime.memory_service.get_card(request.workspace_id, request.card_id) is None:
            raise HTTPException(status_code=404, detail="Training card not found.")
        try:
            workspace = runtime.memory_service.record_training_handoff_reflection(
                workspace_id=request.workspace_id,
                card_id=request.card_id,
                handoff_id=request.handoff_id,
                reflection=request.reflection,
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                revision=request.revision,
                timeout_ms=request.timeout_ms,
                cancel=request.cancel,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        refresh(request.workspace_id)
        return TrainingHandoffActionResponse(workspace=workspace)

    @router.post("/training/return", response_model=TrainingHandoffActionResponse)
    def return_training_handoff(
        request: TrainingHandoffReturnRequest,
    ) -> TrainingHandoffActionResponse:
        require_live_selected_card_for_status(runtime, request.workspace_id, request.card_id)
        if runtime.memory_service.get_card(request.workspace_id, request.card_id) is None:
            raise HTTPException(status_code=404, detail="Training card not found.")
        try:
            workspace = runtime.memory_service.return_training_handoff(
                workspace_id=request.workspace_id,
                card_id=request.card_id,
                handoff_id=request.handoff_id,
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                revision=request.revision,
                timeout_ms=request.timeout_ms,
                cancel=request.cancel,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        refresh(request.workspace_id)
        return TrainingHandoffActionResponse(workspace=workspace)

    @router.post("/training/reliability/control", response_model=TrainingHandoffActionResponse)
    def control_training_reliability(
        request: TrainingReliabilityControlRequest,
    ) -> TrainingHandoffActionResponse:
        try:
            if request.action == "cancel":
                workspace = runtime.memory_service.cancel_training_reliability(
                    request.workspace_id,
                    request_id=request.request_id,
                    command_id=request.command_id,
                    card_id=request.card_id,
                )
            elif request.action == "recover":
                workspace = runtime.memory_service.recover_training_reliability(
                    request.workspace_id,
                    request_id=request.request_id,
                    revision=request.revision,
                    timeout_ms=request.timeout_ms,
                )
            else:
                workspace = runtime.memory_service.expire_training_reliability(request.workspace_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        refresh(request.workspace_id)
        return TrainingHandoffActionResponse(workspace=workspace)

    return router
