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


_VERIFICATION_POLICY_VERSION = 1


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


def _card_capability_dimension(card: Any) -> str:
    """Map a card's declared task shape to one capability dimension.

    The dimension is task metadata, not mastery: the projection still requires
    controlled evidence before any state can advance. A code task without an
    implementation/debugging signal is an implementation check; a theory or
    reading task is a comprehension check.
    """
    if card is None:
        return "implementation"
    subtype = str(getattr(card, "learning_subtype", "") or "").strip().lower()
    family = str(getattr(card, "learning_family", "") or "").strip().lower()
    if subtype in {"debug", "debugging", "bugfix", "bug_fix", "failure_diagnosis"}:
        return "debugging"
    if subtype in {"transfer", "migration", "cross_context"}:
        return "transfer"
    if (
        getattr(card, "files_to_touch", None)
        or getattr(card, "expected_symbols", None)
        or str(getattr(card, "verification_method", "") or "").strip().lower()
        in {"dynamic", "test", "pytest", "file", "evaluator"}
    ):
        return "implementation"
    if family == "theory" or subtype in {
        "concept",
        "reading",
        "explanation",
        "derivation",
        "memorization",
        "orientation",
        "project_orientation",
    }:
        return "comprehension"
    return "implementation"


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
            "verification_policy_version": _VERIFICATION_POLICY_VERSION,
            "workspace_id": workspace_id,
            "attempt_id": attempt_id,
            "card_id": card_id,
            "subject_family": family,
            "dimensions": projection,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    return projection


def refresh_legacy_skill_projections(runtime: TrainerRuntime) -> None:
    """Recompute previously stored capability claims using current evidence rules."""
    if runtime.attempt_store is None:
        return
    for workspace_id, payload in runtime.repository.list_structured_memory():
        workspace = payload.get("workspace") or {}
        projection = workspace.get("training_skill_projection") or {}
        if not isinstance(projection, dict) or projection.get("verification_policy_version") == _VERIFICATION_POLICY_VERSION:
            continue
        attempt_id = projection.get("attempt_id")
        if not attempt_id:
            continue
        dimensions = projection.get("dimensions")
        if not isinstance(dimensions, dict) or not dimensions:
            continue
        # The persisted result is disposable. Original attempt evidence stays auditable.
        persist_skill_projection(runtime, workspace_id, attempt_id)


def record_executed_training_evidence(
    runtime: TrainerRuntime,
    *,
    workspace_id: str,
    request: EvaluateCurrentFileRequest,
    report: EvaluationReport,
    returned_card: bool | None = None,
) -> None:
    """Called only after server evaluation and live-card/file identity checks.

    Bind the evidence to the exact evaluated content, never a success flag or
    the text of a summary. A static-only report cannot verify implementation.
    ``returned_card`` is captured before the evaluation body advances the
    card's phase; it identifies the same capability applied in a new context.
    """
    store = runtime.attempt_store
    if store is None:
        return
    behavior = next((check for check in report.dynamic_checks if check.id == "python-behavior"), None)
    controlled = behavior is not None and behavior.status in {"passed", "failed"}
    artifact_hash = content_hash(request.content)
    card_id = str(request.training_card_id)
    card = runtime.memory_service.get_card(workspace_id, card_id)
    is_return_context = (
        returned_card
        if returned_card is not None
        else bool(card is not None and card.learning_phase == "return")
    )
    attempt = store.find_active_attempt(workspace_id, card_id)
    if attempt is None and is_return_context:
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
    if controlled:
        result = "passed" if report.passed else "failed"
    elif behavior is not None and behavior.status in {"warning", "skipped"}:
        result = "execution_error"
    else:
        result = "partial"
    # A returned card is the same capability applied back in the project after
    # a scenario/handoff. That is a real cross-context transfer fact; a normal
    # practice card is not.
    dimension = "transfer" if is_return_context else _card_capability_dimension(card)
    resource_fields: dict[str, Any] = {}
    evidence_limitations = [
        f"{check.label}: {check.detail}"
        for check in report.dynamic_checks
        if check.status in {"skipped", "warning"}
    ]
    if not controlled:
        evidence_limitations.append(f"Verification scope: {report.verification_scope}.")
    resource_id = str(getattr(card, "resource_id", "") or "").strip()
    if resource_id:
        repository = getattr(runtime, "repository", None)
        resource_available = bool(
            repository is not None
            and any(
                str(getattr(item, "id", "")) == resource_id
                for item in repository.list_resources(workspace_id)
            )
        )
        version_store = getattr(runtime, "resource_version_store", None)
        current_version = (
            version_store.current_version(workspace_id, resource_id)
            if resource_available and version_store is not None
            else None
        )
        if current_version:
            location = current_version.get("location")
            resource_fields = {
                "resource_id": resource_id,
                "resource_version_id": current_version.get("version_id"),
                "resource_content_hash": current_version.get("content_hash"),
                "resource_location": location if isinstance(location, dict) else {},
            }
        else:
            evidence_limitations.append(
                f"resource version unavailable for {resource_id}"
            )
    store.record_evidence(
        attempt_id=attempt["attempt_id"],
        caller_workspace_id=workspace_id,
        artifact_hash=artifact_hash,
        result=result,
        trust_level="controlled_check" if controlled else "static_analysis",
        runner_version="trainer-current-file-evaluator-v2",
        execution_location="workspace",
        dimension=dimension,
        evidence_kind="controlled_evaluation" if controlled else "current_file_observation",
        scenario=(
            str(getattr(card, "scenario", "") or getattr(card, "focus_area", "") or "").strip()
            or None
        )
        if is_return_context
        else None,
        environment={"phase": "return"} if is_return_context else None,
        transfer_metadata={"source": "training_return"} if is_return_context else None,
        limitations=evidence_limitations,
        **resource_fields,
    )
    if is_return_context and controlled:
        store.close_attempt(attempt["attempt_id"], workspace_id=workspace_id)
    persist_skill_projection(runtime, workspace_id, attempt["attempt_id"])
