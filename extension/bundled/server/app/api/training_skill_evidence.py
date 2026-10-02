"""Connect executed, card-bound file evaluations to the capability projection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..training.attempt_store import content_hash
from ..training.skill_projection import project_skills

if TYPE_CHECKING:
    from ..core.models import EvaluateCurrentFileRequest, EvaluationReport
    from .runtime import TrainerRuntime


def persist_skill_projection(
    runtime: TrainerRuntime, workspace_id: str, attempt_id: str
) -> dict[str, dict[str, Any]] | None:
    store = runtime.attempt_store
    if store is None:
        return None
    attempt = store.get_attempt(attempt_id, workspace_id=workspace_id)
    if attempt is None:
        return None
    # Growth describes the workspace, so entering a new card must not erase
    # evidence earned on another card. The attempt endpoint remains card-scoped.
    records = [
        evidence
        for item in store.list_attempts(workspace_id=workspace_id)
        for evidence in store.list_evidence(item["attempt_id"])
    ]
    projection = project_skills(records)
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


def record_executed_training_evidence(
    runtime: TrainerRuntime,
    *,
    workspace_id: str,
    request: EvaluateCurrentFileRequest,
    report: EvaluationReport,
) -> None:
    """Called only after server evaluation and live-card/file identity checks.

    Bind the evidence to the exact evaluated content, never a success flag or
    the text of a summary. A static-only report cannot verify implementation.
    """
    store = runtime.attempt_store
    if store is None:
        return
    dynamic_passed = any(check.status == "passed" for check in report.dynamic_checks)
    dynamic_failed = any(check.status == "failed" for check in report.dynamic_checks)
    artifact_hash = content_hash(request.content)
    card_id = str(request.training_card_id)
    card = runtime.memory_service.get_card(workspace_id, card_id)
    returned_card = card is not None and card.learning_phase == "return"
    attempt = store.find_active_attempt(workspace_id, card_id)
    if attempt is None and returned_card:
        history = store.list_attempts(workspace_id=workspace_id, card_id=card_id)
        attempt = history[-1] if history else None
    if attempt is None:
        attempt = store.start_attempt(
            workspace_id=workspace_id, card_id=card_id,
            file_path=request.file_path, file_hash=artifact_hash,
        )
    else:
        store.update_attempt_for_workspace(
            attempt["attempt_id"], workspace_id=workspace_id,
            file_path=request.file_path, file_hash=artifact_hash,
        )
    controlled = dynamic_passed or dynamic_failed
    result = "passed" if report.passed and dynamic_passed else "failed"
    if report.passed and not dynamic_passed:
        result = "partial"
    store.record_evidence(
        attempt_id=attempt["attempt_id"],
        caller_workspace_id=workspace_id,
        artifact_hash=artifact_hash,
        result=result,
        trust_level="controlled_check" if controlled else "static_analysis",
        runner_version="trainer-current-file-evaluator",
        execution_location="workspace",
        limitations=[
            f"{check.label}: {check.detail}"
            for check in report.dynamic_checks
            if check.status in {"skipped", "pending"}
        ],
    )
    if returned_card:
        store.close_attempt(attempt["attempt_id"], workspace_id=workspace_id)
    persist_skill_projection(runtime, workspace_id, attempt["attempt_id"])
