from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..runtime import TrainerRuntime


class AttemptStartRequest(BaseModel):
    workspace_id: str
    card_id: str
    file_path: str | None = None
    file_hash: str | None = None
    file_version: int | None = None
    assistance_level: str | None = None


class AttemptUpdateRequest(BaseModel):
    attempt_id: str
    workspace_id: str | None = None
    answer_draft: str | None = None
    assistance_level: str | None = None
    status: str | None = None
    file_path: str | None = None
    file_hash: str | None = None
    file_version: int | None = None


class AttemptEvidenceRequest(BaseModel):
    attempt_id: str
    artifact_hash: str
    result: str
    runner_version: str = "trainer-sidecar"
    execution_location: str = "workspace"
    limitations: list[str] = Field(default_factory=list)
    # Optional fields keep old clients valid while allowing the server to
    # distinguish transfer facts from merely running in a preview/sandbox.
    execution_status: str | None = None
    error_category: str | None = None
    failure_reason: str | None = None
    error_code: str | None = None
    scenario: Any = None
    environment: Any = None
    constraints: Any = None
    transfer_metadata: dict[str, Any] | None = None
    # Optional citation anchor. The server, not the client, resolves the
    # version id / content hash / location so deletion propagation is
    # resource-scoped and cannot be forged onto another resource's version.
    resource_id: str | None = None
    resource_version_id: str | None = None


def build_training_attempts_router(runtime: TrainerRuntime) -> APIRouter:
    router = APIRouter(tags=["training"])

    def _projection_records(store, *, workspace_id: str, card_id: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for attempt in store.list_attempts(workspace_id=workspace_id, card_id=card_id):
            records.extend(store.list_evidence(attempt["attempt_id"]))
        return records

    def persist_skill_projection(workspace_id: str, attempt_id: str) -> dict | None:
        """Phase-D UI closure: project the attempt's evidence into skill
        states and mirror it into workspace memory so every snapshot (Coach,
        Plan, Training views) carries the learner's current capability
        ladder without extra round-trips."""
        from app.training.skill_projection import project_skills

        store = runtime.attempt_store
        if store is None:
            return None
        attempt = store.get_attempt(attempt_id, workspace_id=workspace_id)
        if attempt is None:
            return None
        projection = project_skills(
            _projection_records(
                store,
                workspace_id=workspace_id,
                card_id=str(attempt.get("card_id") or ""),
            ),
            card_id=attempt.get("card_id"),
        )
        runtime.memory_service.update_workspace_state(
            workspace_id,
            training_skill_projection={
                "workspace_id": workspace_id,
                "attempt_id": attempt_id,
                "card_id": attempt.get("card_id"),
                "dimensions": projection,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        return projection

    def require_store():
        if runtime.attempt_store is None:
            raise HTTPException(status_code=503, detail="Attempt store is unavailable.")
        return runtime.attempt_store

    @router.post("/training/attempt/start")
    def start_attempt(request: AttemptStartRequest) -> dict:
        # Idempotent: entering a card twice resumes the same attempt.
        store = require_store()
        kwargs: dict = {}
        if request.file_path is not None:
            kwargs["file_path"] = request.file_path
        if request.file_hash is not None:
            kwargs["file_hash"] = request.file_hash
        if request.file_version is not None:
            kwargs["file_version"] = request.file_version
        if request.assistance_level is not None:
            kwargs["assistance_level"] = request.assistance_level
        attempt = store.start_attempt(
            workspace_id=request.workspace_id,
            card_id=request.card_id,
            **kwargs,
        )
        persist_skill_projection(request.workspace_id, attempt["attempt_id"])
        return {"ok": True, "attempt": attempt}

    @router.post("/training/attempt/update")
    def update_attempt(request: AttemptUpdateRequest) -> dict:
        store = require_store()
        attempt = store.update_attempt(
            request.attempt_id,
            workspace_id=request.workspace_id,
            answer_draft=request.answer_draft,
            assistance_level=request.assistance_level,
            status=request.status,
            file_path=request.file_path,
            file_hash=request.file_hash,
            file_version=request.file_version,
        )
        if attempt is None:
            raise HTTPException(status_code=404, detail="Training attempt not found.")
        if request.workspace_id:
            persist_skill_projection(request.workspace_id, attempt["attempt_id"])
        return {"ok": True, "attempt": attempt}

    @router.post("/training/attempt/evidence")
    def record_attempt_evidence(request: AttemptEvidenceRequest) -> dict:
        store = require_store()
        attempt = store.get_attempt(request.attempt_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="Training attempt not found.")
        workspace_id = str(attempt.get("workspace_id") or "")
        resource_fields: dict[str, Any] = {}
        requested_resource_id = str(request.resource_id or "").strip()
        if requested_resource_id:
            version_store = getattr(runtime, "resource_version_store", None)
            if version_store is None:
                raise HTTPException(
                    status_code=503,
                    detail="Resource versioning is unavailable; evidence cannot cite a resource.",
                )
            current_version = version_store.current_version(workspace_id, requested_resource_id)
            if current_version is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown resource_id for this workspace: {requested_resource_id}.",
                )
            if request.resource_version_id and request.resource_version_id != current_version.get(
                "version_id"
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "resource_version_conflict",
                        "resource_id": requested_resource_id,
                        "expected_version_id": request.resource_version_id,
                        "current_version_id": current_version.get("version_id"),
                    },
                )
            location = current_version.get("location")
            resource_fields = {
                "resource_id": requested_resource_id,
                "resource_version_id": current_version.get("version_id"),
                "resource_content_hash": current_version.get("content_hash"),
                "resource_location": location if isinstance(location, dict) else {},
            }
        evidence = store.record_evidence(
            attempt_id=request.attempt_id,
            artifact_hash=request.artifact_hash,
            result=request.result,
            runner_version=request.runner_version,
            execution_location=request.execution_location,
            trust_level="self_reported",
            limitations=list(request.limitations),
            execution_status=request.execution_status,
            error_category=request.error_category,
            failure_reason=request.failure_reason,
            error_code=request.error_code,
            scenario=request.scenario,
            environment=request.environment,
            constraints=request.constraints,
            transfer_metadata=request.transfer_metadata,
            **resource_fields,
        )
        if evidence is None:
            raise HTTPException(status_code=404, detail="Training attempt not found.")
        if workspace_id:
            persist_skill_projection(workspace_id, request.attempt_id)
        return {"ok": True, "evidence": evidence}

    @router.get("/training/attempt/{attempt_id}")
    def get_attempt(attempt_id: str, workspace_id: str | None = None) -> dict:
        store = require_store()
        attempt = store.get_attempt(attempt_id, workspace_id=workspace_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="Training attempt not found.")
        return {"ok": True, "attempt": attempt}

    class AttemptRecoverRequest(BaseModel):
        workspace_id: str
        card_id: str

    @router.post("/training/attempt/recover")
    def recover_attempt(request: AttemptRecoverRequest) -> dict:
        """Re-entering a card resumes the in-flight attempt, if any."""
        store = require_store()
        active = store.find_active_attempt(request.workspace_id, request.card_id)
        if active is not None:
            persist_skill_projection(request.workspace_id, active["attempt_id"])
        return {"ok": True, "attempt": active}

    class AttemptCloseRequest(BaseModel):
        attempt_id: str
        workspace_id: str

    @router.post("/training/attempt/close")
    def close_attempt(request: AttemptCloseRequest) -> dict:
        # Return retires the lifecycle; history stays queryable.
        store = require_store()
        closed = store.close_attempt(request.attempt_id, workspace_id=request.workspace_id)
        if closed is None:
            raise HTTPException(status_code=404, detail="Training attempt not found.")
        return {"ok": True, "attempt": closed}

    @router.get("/training/attempt/{attempt_id}/projection")
    def get_skill_projection(attempt_id: str, workspace_id: str | None = None) -> dict:
        """Evidence → skill state projection (Phase-D capability model)."""
        from app.training.skill_projection import project_skills
        store = require_store()
        attempt = store.get_attempt(attempt_id, workspace_id=workspace_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="Training attempt not found.")
        projection = project_skills(
            _projection_records(
                store,
                workspace_id=str(attempt.get("workspace_id") or workspace_id or ""),
                card_id=str(attempt.get("card_id") or ""),
            ),
            card_id=attempt.get("card_id"),
        )
        return {"ok": True, "card_id": attempt.get("card_id"), "projection": projection}

    return router
