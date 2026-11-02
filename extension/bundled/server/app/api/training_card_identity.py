from __future__ import annotations

import ntpath
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import HTTPException

from ..core.models import EvaluateCurrentFileRequest
from ..memory.workspace_recovery import PLAN_RUNTIME_KEY, select_plan_runtime_for_scope

_LEFTOVER_NOT_LIVE_MISMATCH = (
    "Recovered training card is leftover-not-live or does not match live "
    "selected_card_id. Trainer will not skip, grade, reflect, return, or "
    "resurrect leftover as live."
)
_LEFTOVER_NOT_LIVE = (
    "Recovered training card is leftover-not-live. "
    "Trainer will not skip, grade, reflect, return, or resurrect leftover as live."
)


def leftover_runtime_overlay(runtime: Any, workspace_id: str) -> dict[str, object]:
    memory = runtime.memory_service.snapshot(workspace_id)
    workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
    recovered = select_plan_runtime_for_scope(
        workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
        workspace_id,
    )
    return recovered if isinstance(recovered, dict) else {}


def training_card_is_live_for_verify(runtime: Any, workspace_id: str, card_id: str) -> bool:
    """Leftover-not-live cards may still evaluate; they must not FSRS or persist status."""

    requested = str(card_id or "").strip()
    if not requested:
        return False
    live_id = runtime.memory_service.live_selected_training_card_id(workspace_id)
    if live_id:
        return requested == live_id
    leftover_runtime = leftover_runtime_overlay(runtime, workspace_id)
    return not leftover_runtime


def _normalize_card_target(value: object) -> str:
    """Strip model-authored Markdown wrappers without inventing a new path."""
    text = str(value).strip().strip("`'\"")
    text = text.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.strip()


def _path_is_within_project(value: str, project: str) -> bool:
    if not project:
        return True
    try:
        Path(value).resolve().relative_to(Path(project).resolve())
        return True
    except (OSError, ValueError):
        return False


def prepare_training_file_evaluation(
    runtime: Any, workspace_id: str, request: EvaluateCurrentFileRequest,
) -> EvaluateCurrentFileRequest:
    """Use the live stored card contract and reject proof from a different file."""
    if str(request.evaluation_source or "").strip().lower() != "training":
        return request
    card_id = str(request.training_card_id or "").strip()
    if not training_card_is_live_for_verify(runtime, workspace_id, card_id):
        return request  # Historical evaluation remains readable, without status persistence.
    card = runtime.memory_service.get_card(workspace_id, card_id)
    if card is None:
        return request
    workspace = runtime.memory_service.snapshot(workspace_id).workspace
    project = str(workspace.get("canonical_project_path") or workspace.get("project_path") or "")

    def canonical(value: str) -> str:
        if ntpath.splitdrive(value)[0]:
            return ntpath.normcase(ntpath.normpath(value))
        if ntpath.splitdrive(project)[0] and not Path(value).is_absolute():
            return ntpath.normcase(ntpath.normpath(ntpath.join(project, value)))
        path = Path(value)
        if not path.is_absolute():
            if not project:
                return ""
            path = Path(project) / path
        return str(path.resolve())

    targets = [
        normalized
        for item in (card.files_to_touch or [])
        if (normalized := _normalize_card_target(item))
    ]
    requested_path = canonical(request.file_path)
    if targets and requested_path and not _path_is_within_project(requested_path, project):
        raise HTTPException(
            status_code=409,
            detail="This file is outside the current project; open the training card target and retry.",
        )
    if targets:
        target_paths = {canonical(item) for item in targets}
        matched = bool(requested_path) and requested_path in target_paths
        if not matched:
            # Cards often name only the leaf file (`queue_lock.py`) while the
            # project keeps it under src/. Match the leaf for that form, and
            # require the full relative suffix when the card names a directory.
            requested_posix = str(request.file_path or "").replace("\\", "/")
            requested_name = PurePosixPath(requested_posix).name
            for target in targets:
                normalized_target = target.replace("\\", "/")
                if "/" not in normalized_target:
                    if requested_name == normalized_target:
                        matched = True
                        break
                elif requested_posix.endswith("/" + normalized_target):
                    matched = True
                    break
        if not matched:
            raise HTTPException(
                status_code=409,
                detail="This file is not a target of the current training card. Open its target file and retry.",
            )
    updates: dict[str, object] = {}
    for field in ("acceptance_criteria", "learner_deliverables", "expected_symbols"):
        values = list(getattr(card, field, []) or [])
        if values:
            updates[field] = values
    return request.model_copy(update=updates) if updates else request


def require_live_selected_card_for_status(runtime: Any, workspace_id: str, card_id: str) -> None:
    """Leftover-not-live dump must not skip/grade/reflect/return as live. Title is not identity.

    Live matching selected_card_id still persists (including request_id replay).
    Recovered overlay without a live selected_card_id fail-closes 409.
    No leftover overlay keeps stored-card-id persist for unbound sessions.
    """
    requested = str(card_id or "").strip()
    live_id = runtime.memory_service.live_selected_training_card_id(workspace_id)
    if live_id:
        if requested == live_id:
            return
        raise HTTPException(status_code=409, detail=_LEFTOVER_NOT_LIVE_MISMATCH)
    workspace = runtime.memory_service.snapshot(workspace_id).workspace
    completed_handoff = workspace.get("latest_training_handoff")
    if (
        isinstance(completed_handoff, dict)
        and str(completed_handoff.get("card_id") or completed_handoff.get("candidate_id") or "").strip()
        == requested
        and str(completed_handoff.get("learning_phase") or "").strip().lower() == "return"
        and str(completed_handoff.get("status") or "").strip().lower() == "completed"
    ):
        return
    leftover_runtime = leftover_runtime_overlay(runtime, workspace_id)
    if leftover_runtime:
        raise HTTPException(status_code=409, detail=_LEFTOVER_NOT_LIVE)
