from __future__ import annotations

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
    answer_draft: str | None = None
    assistance_level: str | None = None
    status: str | None = None
    file_path: str | None = None
    file_hash: str | None = None
    file_version: int | None = None


class AttemptEvidenceRequest(BaseModel):
    attempt_id: str
    workspace_id: str
    card_id: str
    artifact_hash: str
    result: str
    runner_version: str = "trainer-sidecar"
    execution_location: str = "workspace"
    trust_level: str = "controlled_check"
    limitations: list[str] = Field(default_factory=list)


def build_training_attempts_router(runtime: TrainerRuntime) -> APIRouter:
    router = APIRouter(tags=["training"])

    def require_store():
        if runtime.attempt_store is None:
            raise HTTPException(status_code=503, detail="Attempt store is unavailable.")
        return runtime.attempt_store

    @router.post("/training/attempt/start")
    def start_attempt(request: AttemptStartRequest) -> dict:
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
        return {"ok": True, "attempt": attempt}

    @router.post("/training/attempt/update")
    def update_attempt(request: AttemptUpdateRequest) -> dict:
        store = require_store()
        attempt = store.update_attempt(
            request.attempt_id,
            answer_draft=request.answer_draft,
            status=request.status,
            file_path=request.file_path,
            file_hash=request.file_hash,
            file_version=request.file_version,
        )
        if attempt is None:
            raise HTTPException(status_code=404, detail="Training attempt not found.")
        return {"ok": True, "attempt": attempt}

    @router.post("/training/attempt/evidence")
    def record_attempt_evidence(request: AttemptEvidenceRequest) -> dict:
        store = require_store()
        evidence = store.record_evidence(
            attempt_id=request.attempt_id,
            workspace_id=request.workspace_id,
            card_id=request.card_id,
            artifact_hash=request.artifact_hash,
            result=request.result,
            runner_version=request.runner_version,
            execution_location=request.execution_location,
            trust_level=request.trust_level,
            limitations=list(request.limitations),
        )
        if evidence is None:
            raise HTTPException(status_code=404, detail="Training attempt not found.")
        return {"ok": True, "evidence": evidence}

    @router.get("/training/attempt/{attempt_id}")
    def get_attempt(attempt_id: str) -> dict:
        store = require_store()
        attempt = store.get_attempt(attempt_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="Training attempt not found.")
        return {"ok": True, "attempt": attempt}

    return router
