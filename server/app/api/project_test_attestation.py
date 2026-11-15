"""Bind saved-project test results to the existing host attestation route."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from ..core.event_ledger import EVENT_EVALUATION_FEEDBACK_RECORDED
from ..core.models import EvaluationReport, ResourceVersionAnchor
from ..training.resource_practice import is_independent_resource_card
from ..training.skill_projection import SAVED_PROJECT_TEST_EVIDENCE_KIND
from .training_card_identity import training_card_is_live_for_verify
from .training_skill_evidence import persist_skill_projection

if TYPE_CHECKING:
    from .runtime import TrainerRuntime

_ACTOR = "project_test_evaluator"


class ProjectTestRun(BaseModel):
    card_id: str
    session_id: str
    selection_at: str
    card_updated_at: str
    started_at: str
    source: ResourceVersionAnchor
    file_path: str
    sha256: str
    verdict: Literal["passed", "failed"]
    summary: str
    test_detail: str = ""


def current_practice_source(
    runtime: TrainerRuntime, workspace_id: str, anchor: ResourceVersionAnchor,
) -> dict[str, Any] | None:
    resource = runtime.repository.get_resource(workspace_id, anchor.resource_id)
    if resource is None or resource.content_hash != anchor.content_hash:
        return None
    version = runtime.resource_service.version_store.current_version(workspace_id, anchor.resource_id)
    if version and version["version_id"] == anchor.version_id and version["content_hash"] == anchor.content_hash:
        return version
    return None


def issue_project_test_receipt(
    runtime: TrainerRuntime, workspace_id: str, report: EvaluationReport, *,
    session_id: str, started_at: str, selection_at: str, card_updated_at: str,
    source: ResourceVersionAnchor,
) -> None:
    proof = report.saved_file_verification
    if proof is None or proof.verdict == "unknown":
        return
    ledger = runtime.event_ledger
    if ledger is None:
        raise HTTPException(status_code=503, detail="The project test ledger is unavailable.")
    run = ProjectTestRun(
        card_id=proof.card_id, session_id=session_id, selection_at=selection_at,
        card_updated_at=card_updated_at,
        started_at=started_at, source=source, file_path=proof.file_path, sha256=proof.sha256,
        verdict=proof.verdict, summary=report.summary,
        test_detail=next((check.detail for check in report.dynamic_checks if check.id == "pytest"), ""),
    )
    receipt_id = uuid4().hex
    ledger.record_event(
        EVENT_EVALUATION_FEEDBACK_RECORDED, actor=_ACTOR, scope="training",
        workspace_id=workspace_id, project_id=workspace_id,
        idempotency_key=f"project-test:{receipt_id}", payload_ref=run.model_dump(mode="json"),
    )
    proof.receipt_id = receipt_id


def _saved_revision_is_current(
    runtime: TrainerRuntime, workspace_id: str, run: ProjectTestRun,
) -> bool:
    authority = runtime.workspace_authority(workspace_id)
    if authority is None or authority.is_remote_workspace or not authority.active_workspace_root:
        return False
    try:
        project = Path(authority.active_workspace_root).resolve(strict=True)
        file = Path(run.file_path)
        target = file.resolve(strict=True)
        target.relative_to(project)
        if target != file or not target.is_file():
            return False
        with target.open("rb") as saved:
            return hashlib.file_digest(saved, "sha256").hexdigest() == run.sha256
    except (OSError, RuntimeError, ValueError):
        return False


def attest_project_test_run(
    runtime: TrainerRuntime, workspace_id: str, *,
    session_id: str, card_id: str, receipt_id: str,
) -> dict[str, object]:
    ledger = runtime.event_ledger
    store = runtime.attempt_store
    if ledger is None or store is None:
        raise HTTPException(status_code=503, detail="The project test ledger is unavailable.")
    if not re.fullmatch(r"[0-9a-f]{32}", receipt_id):
        raise HTTPException(status_code=422, detail="A project test receipt is required.")
    entry = ledger.find_by_idempotency_key(workspace_id, f"project-test:{receipt_id}")
    if entry is None or entry.actor != _ACTOR or entry.event_type != EVENT_EVALUATION_FEEDBACK_RECORDED:
        raise HTTPException(status_code=409, detail="The project test receipt is unavailable.")
    try:
        run = ProjectTestRun.model_validate(entry.payload_ref)
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail="The project test receipt is invalid.") from exc
    if run.card_id != card_id or run.session_id != session_id:
        raise HTTPException(status_code=409, detail="The project test receipt belongs to another card or session.")

    def prior_evidence():
        return [
            evidence
            for attempt in store.list_attempts(workspace_id=workspace_id, card_id=card_id)
            for evidence in store.list_evidence(attempt["attempt_id"])
            if evidence.get("evidence_kind") == SAVED_PROJECT_TEST_EVIDENCE_KIND
        ]

    def saved_run(evidence: dict[str, Any]) -> dict[str, Any]:
        return evidence.get("environment") or {}

    def from_receipt(evidence: dict[str, Any]) -> bool:
        return (
            evidence.get("evidence_kind") == SAVED_PROJECT_TEST_EVIDENCE_KIND
            and saved_run(evidence).get("receipt_id") == receipt_id
        )

    def record() -> dict[str, Any]:
        previous = prior_evidence()
        evidence = next((item for item in previous if from_receipt(item)), None)
        workspace = runtime.memory_service.snapshot(workspace_id).workspace
        card = runtime.memory_service.get_card(workspace_id, card_id)
        if (
            not is_independent_resource_card(card) or card is None or card.resource_anchor != run.source
            or runtime.memory_service.live_selected_training_card_id(workspace_id) != card_id
            or not training_card_is_live_for_verify(runtime, workspace_id, card_id)
            or str(workspace.get("selected_card_updated_at") or "") != run.selection_at
            or card.updated_at != run.card_updated_at
        ):
            raise HTTPException(status_code=409, detail="The source-linked practice changed after testing.")
        version = current_practice_source(runtime, workspace_id, run.source)
        if version is None:
            raise HTTPException(status_code=409, detail={"code": "stale_version"})
        if not _saved_revision_is_current(runtime, workspace_id, run):
            raise HTTPException(status_code=409, detail="The saved project file changed after testing.")
        if any(str(saved_run(item).get("started_at") or "") > run.started_at for item in previous):
            raise HTTPException(status_code=409, detail="A newer project test has already been attested.")
        if evidence is None:
            attempt = store.start_attempt(
                workspace_id=workspace_id, card_id=card_id,
                file_path=run.file_path, file_hash=run.sha256,
            )
            evidence = store.record_evidence(
                attempt_id=attempt["attempt_id"], caller_workspace_id=workspace_id,
                artifact_hash=run.sha256, result=run.verdict,
                trust_level="controlled_check", runner_version="trainer-saved-project-pytest",
                execution_location="workspace_copy", dimension="implementation",
                evidence_kind=SAVED_PROJECT_TEST_EVIDENCE_KIND,
                limitations=["Existing project tests. Coverage of all practice requirements is unconfirmed."],
                environment={
                    "receipt_id": receipt_id, "started_at": run.started_at,
                    "scope": "test_suite", "test_detail": run.test_detail,
                },
                resource_id=run.source.resource_id, resource_version_id=run.source.version_id,
                resource_content_hash=run.source.content_hash, resource_location=version.get("location"),
                skip_if=lambda items: any(from_receipt(item) for item in items),
            )
            if evidence is None:
                evidence = next((item for item in prior_evidence() if from_receipt(item)), None)
            if evidence is None:
                raise HTTPException(status_code=409, detail="The project test evidence could not be recorded.")
        persist_skill_projection(runtime, workspace_id, evidence["attempt_id"])
        if run.verdict == "passed":
            resource = runtime.repository.get_resource(workspace_id, run.source.resource_id)
            runtime.memory_service.initialize_training_card_review(
                workspace_id, training_card_id=card_id,
                project_test_concept=resource.name if resource else card.title,
            )
        runtime.goals().record_activity(
            workspace_id=workspace_id, kind="verification", summary=run.summary,
            result=run.verdict, concept=card.title, evidence_refs=[evidence["evidence_id"]],
            event_key=f"project-test:{receipt_id}",
        )
        return runtime.memory_service.snapshot(workspace_id).workspace

    workspace = runtime.memory_service.run_training_reliability(
        workspace_id, request_id=receipt_id, idempotency_key=f"project-test:{receipt_id}",
        command_id="trainer.evaluate.currentFile", card_id=card_id, learning_phase="verify",
        work=record,
    )
    if not any(from_receipt(item) for item in prior_evidence()):
        raise HTTPException(status_code=409, detail="The project test attestation is still pending.")
    runtime.publish_goal(workspace_id)
    return {"ok": True, "workspace": workspace}
