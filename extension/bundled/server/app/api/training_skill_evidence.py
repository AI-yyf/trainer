"""Connect executed, card-bound file evaluations to the capability projection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..training.attempt_store import content_hash
from ..training.skill_projection import (
    DIMENSION_REGISTRY,
    project_skills,
)

if TYPE_CHECKING:
    from ..core.models import EvaluateCurrentFileRequest, EvaluationReport
    from .runtime import TrainerRuntime


def _card_subject_family(card: Any) -> str:
    """Classify one training card's subject family through the taxonomy.

    Unknown/unregistered families fail closed to ``code`` — the same fallback
    SubjectProfile resolution uses. ``theory`` keeps the code vocabulary until
    a theory profile registers its own dimensions.
    """
    if card is None:
        return "code"
    from ..training.subject_taxonomy import classify_learning_subject

    subject = classify_learning_subject(
        getattr(card, "title", ""),
        getattr(card, "focus_area", ""),
        getattr(card, "target_skill", ""),
        getattr(card, "scenario_pack", ""),
    )
    return subject.family if str(subject.family) == "literature" else "code"


def resolve_workspace_projection_scope(
    runtime: TrainerRuntime, workspace_id: str
) -> tuple[str, tuple[str, ...], str]:
    """Dimension vocabulary for a workspace projection (P2 #21).

    Majority-votes the subject family across the cards that actually carry
    attempts (tie → ``code``, matching the profile-resolution fallback) and
    returns ``(family, dimensions, default_dimension)``. Literature
    submissions default to ``comprehension`` — the submission's first
    obligation is the text response — while code keeps the historical
    ``implementation`` fallback.
    """
    store = runtime.attempt_store
    counts: dict[str, int] = {}
    if store is not None:
        for attempt in store.list_attempts(workspace_id=workspace_id):
            card_id = str(attempt.get("card_id") or "")
            card = runtime.memory_service.get_card(workspace_id, card_id) if card_id else None
            family = _card_subject_family(card)
            counts[family] = counts.get(family, 0) + 1
    family = max(counts, key=lambda name: (counts[name], name == "code")) if counts else "code"
    dimensions = DIMENSION_REGISTRY.get(family, DIMENSION_REGISTRY["code"])
    default_dimension = "comprehension" if family == "literature" else "implementation"
    return family, dimensions, default_dimension


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
    family, dimensions, default_dimension = resolve_workspace_projection_scope(runtime, workspace_id)
    card_id = attempt.get("card_id")
    projection = project_skills(
        records, card_id=card_id, dimensions=dimensions, default_dimension=default_dimension
    )
    runtime.memory_service.update_workspace_state(
        workspace_id,
        training_skill_projection={
            "workspace_id": workspace_id,
            "attempt_id": attempt_id,
            "card_id": card_id,
            "subject_family": family,
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
