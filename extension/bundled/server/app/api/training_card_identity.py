from __future__ import annotations

from typing import Any

from fastapi import HTTPException

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
