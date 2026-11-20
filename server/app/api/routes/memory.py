from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.models import (
    CoachSettingsRequest,
    EvidenceAdoptResponse,
    EvidenceItem,
    EvidenceQueueSnapshot,
    GlobalMemory,
    GlobalMemoryUpdateRequest,
    MemoryShareGrant,
    MemoryShareGrantRevokeRequest,
    MemoryShareGrantUpsertRequest,
    TransferPromotionScopeRequest,
    UserProfile,
    WorkbenchSnapshot,
)
from ...learner_state import collect_unified_evidence
from ...memory.proactive_budget import evaluate_proactive_opportunity
from ..runtime import TrainerRuntime
from ._deps import RouterDeps


class ProactiveEvaluateRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    diagnostics: list[Any] = Field(default_factory=list)
    message: str = ""
    response_language: str | None = None
    learner_actively_typing: bool = False
    record: bool = False
    now: str | None = None


def build_memory_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter(tags=["memory"])

    current_workspace_id = deps.current_workspace_id
    current_snapshot = deps.current_snapshot
    refresh_workspace_sessions = deps.refresh_workspace_sessions
    hydrate_snapshot = deps.hydrate_snapshot


    @router.get("/memory/summary", response_model=WorkbenchSnapshot)
    def memory_summary(session_id: str | None = None, workspace_id: str | None = None) -> WorkbenchSnapshot:
        if session_id is None and workspace_id:
            runtime.restore_latest_session_for_workspace(workspace_id)
        return current_snapshot(session_id=session_id, workspace_id=workspace_id)

    @router.get("/memory/global", response_model=GlobalMemory)
    def memory_global() -> GlobalMemory:
        return runtime.memory_service.global_memory()

    @router.post("/memory/global", response_model=WorkbenchSnapshot)
    def update_memory_global(request: GlobalMemoryUpdateRequest) -> WorkbenchSnapshot:
        workspace_id = current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        runtime.memory_service.update_global_memory(
            preferences=request.preferences,
            long_term_goals=request.long_term_goals,
        )
        refresh_workspace_sessions(workspace_id)
        return current_snapshot(session_id=request.session_id, workspace_id=workspace_id)

    @router.get("/memory/share-grants", response_model=list[MemoryShareGrant])
    def memory_share_grants(
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[MemoryShareGrant]:
        target_workspace_id = current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        return runtime.memory_service.list_memory_share_grants(target_workspace_id)

    @router.post("/memory/share-grants", response_model=WorkbenchSnapshot)
    def save_memory_share_grant(request: MemoryShareGrantUpsertRequest) -> WorkbenchSnapshot:
        target_workspace_id = current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        if request.source_workspace_id == target_workspace_id:
            raise HTTPException(status_code=422, detail="memory share source and target must differ")
        runtime.memory_service.save_memory_share_grant(
            source_workspace_id=request.source_workspace_id,
            target_workspace_id=target_workspace_id,
            categories=request.categories,
        )
        refresh_workspace_sessions(target_workspace_id)
        return current_snapshot(session_id=request.session_id, workspace_id=target_workspace_id)

    @router.post("/memory/transfer/exclude-workspace")
    def exclude_workspace_from_transfer_promotion(request: TransferPromotionScopeRequest) -> dict[str, object]:
        workspace_ids = [item.strip() for item in request.workspace_ids if item and item.strip()]
        if request.workspace_id and request.workspace_id.strip():
            workspace_ids.append(request.workspace_id.strip())
        excluded = runtime.memory_service.exclude_workspaces_from_transfer_promotion(workspace_ids)
        return {"ok": True, "workspace_ids": excluded}

    @router.post("/memory/transfer/include-workspace")
    def include_workspace_in_transfer_promotion(request: TransferPromotionScopeRequest) -> dict[str, object]:
        workspace_ids = [item.strip() for item in request.workspace_ids if item and item.strip()]
        if request.workspace_id and request.workspace_id.strip():
            workspace_ids.append(request.workspace_id.strip())
        included = runtime.memory_service.include_workspaces_in_transfer_promotion(workspace_ids)
        return {"ok": True, "workspace_ids": included}

    @router.post("/memory/share-grants/revoke", response_model=WorkbenchSnapshot)
    def revoke_memory_share_grant(request: MemoryShareGrantRevokeRequest) -> WorkbenchSnapshot:
        target_workspace_id = current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        runtime.memory_service.revoke_memory_share_grant(
            source_workspace_id=request.source_workspace_id,
            target_workspace_id=target_workspace_id,
        )
        refresh_workspace_sessions(target_workspace_id)
        return current_snapshot(session_id=request.session_id, workspace_id=target_workspace_id)

    @router.get("/memory/profile", response_model=UserProfile | None)
    def memory_profile(session_id: str | None = None, workspace_id: str | None = None) -> UserProfile | None:
        resolved_workspace_id = current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        return runtime.memory_service.profile(resolved_workspace_id)

    @router.get("/memory/weaknesses", response_model=list[str])
    def memory_weaknesses(session_id: str | None = None, workspace_id: str | None = None) -> list[str]:
        resolved_workspace_id = current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        return runtime.memory_service.weaknesses(resolved_workspace_id)

    @router.get("/memory/reviews", response_model=list[str])
    def memory_reviews(session_id: str | None = None, workspace_id: str | None = None) -> list[str]:
        resolved_workspace_id = current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        # Review reads the same LearnerState projection as Coach/Plan/Training.
        service = getattr(runtime, "learner_state_service", None)
        if service is not None:
            projection = service.snapshot(resolved_workspace_id)
            due = projection.memory_snapshot.due_reviews
            if due:
                return [
                    f"{item.concept}: {item.reason}"
                    + (f" (due {item.due_at})" if item.due_at else "")
                    for item in due[:4]
                ]
        return runtime.memory_service.reviews(resolved_workspace_id)

    @router.get("/memory/teaching-assets")
    def memory_teaching_assets(
        session_id: str | None = None,
        workspace_id: str | None = None,
        scope: str | None = None,
        scenario: str | None = None,
        focus_area: str | None = None,
        query: str | None = None,
        kind: str | None = None,
        limit: int = 12,
    ) -> dict[str, object]:
        resolved_workspace_id = current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        safe_limit = max(1, min(limit, 40))
        return runtime.memory_service.teaching_asset_library(
            resolved_workspace_id,
            scope=scope,
            scenario=scenario,
            focus_area=focus_area,
            query=query,
            kind=kind,
            limit=safe_limit,
        )

    @router.get("/evidence/queue", response_model=EvidenceQueueSnapshot)
    def evidence_queue(session_id: str | None = None, workspace_id: str | None = None) -> EvidenceQueueSnapshot:
        resolved_workspace_id = current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        return runtime.memory_service.evidence_queue(resolved_workspace_id)

    @router.get("/evidence/records")
    def evidence_records(
        session_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        """One normalized evidence stream across attempt/handoff/memory stores.

        The stores keep their own lifecycle and persistence. This route is the
        read contract that normalizes trust, result, resource version facts and
        duplicate identity so Coach/Learning never parse three shapes.
        """
        resolved_workspace_id = current_workspace_id(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        safe_limit = max(1, min(limit, 200))
        unified = collect_unified_evidence(
            memory_service=runtime.memory_service,
            attempt_store=getattr(runtime, "attempt_store", None),
            workspace_id=resolved_workspace_id,
            limit=safe_limit,
        )
        return {
            "workspace_id": resolved_workspace_id,
            "schema_version": 1,
            "total": len(unified),
            "evidence": [item.model_dump(by_alias=True) for item in unified],
        }

    @router.get("/learner/state")
    def learner_state(
        workspace_id: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        """The single read projection Coach, Plan, Training and Review consume."""
        resolved_workspace_id = current_workspace_id(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        service = getattr(runtime, "learner_state_service", None)
        if service is None:
            raise HTTPException(status_code=503, detail="Learner state projection is unavailable.")
        return service.snapshot(resolved_workspace_id, evidence_limit=limit).to_payload()

    @router.post("/evidence/enqueue", response_model=EvidenceItem)
    def evidence_enqueue(payload: dict) -> EvidenceItem:
        workspace_id = current_workspace_id(
            session_id=payload.get("session_id"),
            workspace_id=payload.get("workspace_id"),
        )
        if payload.get("waiting_composer") is True or payload.get("waitingComposer") is True:
            enqueued = runtime.memory_service.enqueue_waiting_composer_evidence(
                workspace_id,
                str(payload.get("summary") or payload.get("text") or ""),
            )
            if enqueued is None:
                raise HTTPException(
                    status_code=400,
                    detail="Waiting composer evidence was not accepted.",
                )
            refresh_workspace_sessions(workspace_id)
            return enqueued
        raw_concepts = payload.get("concepts")
        item = EvidenceItem.model_validate(
            {
                "summary": payload.get("summary", ""),
                "source": payload.get("source", "learning_signal"),
                "source_card_id": payload.get("source_card_id") or payload.get("sourceCardId", ""),
                "concepts": raw_concepts if isinstance(raw_concepts, list) else [],
                "outcome": payload.get("outcome", "partial"),
                "confidence": payload.get("confidence", 0.0),
                "target_plan_stage_id": (
                    payload.get("target_plan_stage_id") or payload.get("targetPlanStageId", "")
                ),
            }
        )
        enqueued = runtime.memory_service.enqueue_evidence(workspace_id, item)
        refresh_workspace_sessions(workspace_id)
        return enqueued

    @router.post("/evidence/adopt", response_model=EvidenceAdoptResponse)
    def evidence_adopt(payload: dict) -> EvidenceAdoptResponse:
        workspace_id = current_workspace_id(
            session_id=payload.get("session_id"),
            workspace_id=payload.get("workspace_id"),
        )
        evidence_id = str(payload.get("evidence_id") or payload.get("id") or "").strip()
        if not evidence_id:
            raise HTTPException(status_code=400, detail="evidence_id is required")
        response = runtime.memory_service.adopt_evidence(workspace_id, evidence_id)
        refresh_workspace_sessions(workspace_id)
        return response

    @router.post("/evidence/reject", response_model=EvidenceItem)
    def evidence_reject(payload: dict) -> EvidenceItem:
        workspace_id = current_workspace_id(
            session_id=payload.get("session_id"),
            workspace_id=payload.get("workspace_id"),
        )
        evidence_id = str(payload.get("evidence_id") or payload.get("id") or "").strip()
        if not evidence_id:
            raise HTTPException(status_code=400, detail="evidence_id is required")
        reason = str(payload.get("reason") or "").strip()
        rejected = runtime.memory_service.reject_evidence(workspace_id, evidence_id, reason)
        refresh_workspace_sessions(workspace_id)
        return rejected

    @router.post("/evidence/defer", response_model=EvidenceItem)
    def evidence_defer(payload: dict) -> EvidenceItem:
        workspace_id = current_workspace_id(
            session_id=payload.get("session_id"),
            workspace_id=payload.get("workspace_id"),
        )
        evidence_id = str(payload.get("evidence_id") or payload.get("id") or "").strip()
        if not evidence_id:
            raise HTTPException(status_code=400, detail="evidence_id is required")
        reason = str(payload.get("reason") or "").strip()
        deferred = runtime.memory_service.defer_evidence(workspace_id, evidence_id, reason)
        refresh_workspace_sessions(workspace_id)
        return deferred

    @router.post("/memory/settings", response_model=WorkbenchSnapshot)
    def save_coach_settings(request: CoachSettingsRequest) -> WorkbenchSnapshot:
        workspace_id = current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        runtime.memory_service.save_coach_settings(
            workspace_id=workspace_id,
            response_language=request.response_language,
            answer_mode=request.answer_mode,
            teaching_style=request.teaching_style,
            coach_defaults=request.coach_defaults,
            follow_current_file=request.follow_current_file,
            context_detail=request.context_detail,
            include_current_file=request.include_current_file,
            include_selection=request.include_selection,
            include_diagnostics=request.include_diagnostics,
            include_related_files=request.include_related_files,
        )

        state = runtime.get_session(request.session_id) if request.session_id else runtime.latest_session()
        if state and state.workspace_id == workspace_id:
            state.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
            state.snapshot.profile = runtime.repository.get_profile(workspace_id)
            state.snapshot.plan = runtime.repository.get_latest_plan(workspace_id)
            workspace_memory = state.snapshot.memory.workspace if isinstance(state.snapshot.memory.workspace, dict) else {}
            hydrate_snapshot(
                state.snapshot,
                response_language=(
                    str(workspace_memory.get("response_language")).strip()
                    if workspace_memory.get("response_language")
                    else None
                ),
                answer_mode=(
                    str(workspace_memory.get("answer_mode")).strip()
                    if workspace_memory.get("answer_mode")
                    else (state.snapshot.profile.answer_policy if state.snapshot.profile else None)
                ),
            )
            runtime.save_session_state(state.session_id)

        return current_snapshot(session_id=request.session_id, workspace_id=workspace_id)

    @router.post("/proactive/evaluate", response_model=None)
    def proactive_evaluate(request: ProactiveEvaluateRequest) -> dict[str, object]:
        workspace_id = current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        memory_snapshot = runtime.memory_service.snapshot(workspace_id)
        moment = datetime.now(timezone.utc)
        if request.now:
            try:
                parsed_now = datetime.fromisoformat(str(request.now).strip().replace("Z", "+00:00"))
                moment = (
                    parsed_now.replace(tzinfo=timezone.utc)
                    if parsed_now.tzinfo is None
                    else parsed_now.astimezone(timezone.utc)
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="now must be a valid ISO-8601 timestamp.") from exc
        response_language = str(
            deps.effective_response_language(
                workspace_id,
                request.response_language,
                request.message,
            )
            or "zh"
        )
        weakness_items: list[Any] = (
            runtime.memory_service.weakness_records(workspace_id)
            or list(memory_snapshot.weaknesses)
        )
        whisper = evaluate_proactive_opportunity(
            memory_snapshot.workspace,
            now=moment,
            diagnostics=request.diagnostics,
            weaknesses=weakness_items,
            due_reviews=memory_snapshot.due_reviews,
            due_count=memory_snapshot.due_review_count,
            session_id=request.session_id or "",
            message=request.message,
            response_language=response_language,
            learner_actively_typing=bool(request.learner_actively_typing),
        )
        if request.record and whisper.should_nudge:
            runtime.memory_service.record_proactive_nudge(
                workspace_id,
                kind=whisper.kind,
                dedup_key=whisper.dedup_key,
                session_id=request.session_id or "",
                now=moment,
            )
            if whisper.kind == "review_gap":
                runtime.memory_service.record_review_offer(
                    workspace_id,
                    session_id=request.session_id or "",
                    now=moment,
                )
        return whisper.to_payload()

    return router
