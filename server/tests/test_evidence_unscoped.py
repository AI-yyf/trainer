"""L4 regressions: evidence auto-bind and the unscoped queue bucket."""

from __future__ import annotations

from pathlib import Path

from app.core.models import EvidenceItem
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService
from app.memory.workspace_recovery import (
    PLAN_RUNTIME_KEY,
    scope_evidence_queue_to_runtime_step,
)

CURRENT_STEP = "Review the refresh path"


def _seed_recovered_runtime(service: MemoryService, workspace_id: str) -> None:
    service.update_workspace_state(
        workspace_id,
        **{
            PLAN_RUNTIME_KEY: {
                "workspace_id": workspace_id,
                "plan_id": "plan-refresh",
                "current_step": CURRENT_STEP,
                "why_now": "Recovered runtime is current for this workspace.",
                "resume_state": "in_progress",
            }
        },
    )


def test_enqueue_autobinds_to_recovered_current_step(tmp_path: Path) -> None:
    workspace_id = "ws-evidence-autobind"
    service = MemoryService(TrainerRepository(tmp_path / "autobind.db"))
    _seed_recovered_runtime(service, workspace_id)

    item = service.enqueue_evidence(
        workspace_id, EvidenceItem(id="ev-autobind", summary="Fresh verify note", outcome="pass")
    )

    assert item.target_plan_stage_id == CURRENT_STEP
    snapshot = service.evidence_queue(workspace_id)
    assert [pending.id for pending in snapshot.pending] == [item.id]
    assert snapshot.unscoped == []


def test_unbound_pending_item_surfaces_unscoped_after_recovery(tmp_path: Path) -> None:
    workspace_id = "ws-evidence-unscoped"
    service = MemoryService(TrainerRepository(tmp_path / "unscoped.db"))
    # Enqueue before the runtime exists, so no auto-bind can stamp a target.
    item = service.enqueue_evidence(workspace_id, EvidenceItem(id="ev-loose", summary="Pre-recovery note"))
    assert item.target_plan_stage_id == ""

    _seed_recovered_runtime(service, workspace_id)
    snapshot = service.evidence_queue(workspace_id)

    assert [unscoped.id for unscoped in snapshot.unscoped] == [item.id]
    assert snapshot.pending == []
    assert all(history.id != item.id for history in snapshot.history)


def test_item_bound_to_other_step_stays_history(tmp_path: Path) -> None:
    workspace_id = "ws-evidence-other-step"
    service = MemoryService(TrainerRepository(tmp_path / "other-step.db"))
    _seed_recovered_runtime(service, workspace_id)

    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(id="ev-earlier", summary="Earlier stage note", target_plan_stage_id="stage-earlier"),
    )

    snapshot = service.evidence_queue(workspace_id)
    assert snapshot.pending == []
    assert snapshot.unscoped == []
    assert [history.id for history in snapshot.history] == [item.id]


def test_no_recovery_keeps_pass_through_without_unscoped(tmp_path: Path) -> None:
    workspace_id = "ws-evidence-no-recovery"
    service = MemoryService(TrainerRepository(tmp_path / "no-recovery.db"))

    item = service.enqueue_evidence(workspace_id, EvidenceItem(id="ev-plain", summary="Plain note"))

    snapshot = service.evidence_queue(workspace_id)
    assert [pending.id for pending in snapshot.pending] == [item.id]
    assert snapshot.unscoped == []
    assert snapshot.history == []


def test_explicit_target_still_wins_over_autobind(tmp_path: Path) -> None:
    workspace_id = "ws-evidence-explicit-target"
    service = MemoryService(TrainerRepository(tmp_path / "explicit-target.db"))
    _seed_recovered_runtime(service, workspace_id)

    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(id="ev-explicit", summary="Bound at enqueue", target_plan_stage_id="stage-next"),
    )

    assert item.target_plan_stage_id == "stage-next"


def test_scope_helper_partitions_pending_unscoped_and_history() -> None:
    bound = EvidenceItem(id="ev-bound", summary="bound", concepts=[CURRENT_STEP])
    other = EvidenceItem(id="ev-other", summary="other", target_plan_stage_id="stage-earlier")
    loose = EvidenceItem(id="ev-loose", summary="loose")
    deferred = EvidenceItem(id="ev-deferred", summary="deferred", deferred_at="2026-01-01T00:00:00Z")

    scoped = scope_evidence_queue_to_runtime_step(
        pending=[bound, other, loose],
        deferred=[deferred],
        adopted=[],
        rejected=[],
        current_step=CURRENT_STEP,
        recovered=True,
    )

    assert [item.id for item in scoped["pending"]] == [bound.id]
    assert [item.id for item in scoped["unscoped"]] == [loose.id]
    assert {item.id for item in scoped["history"]} == {other.id, deferred.id}

    passthrough = scope_evidence_queue_to_runtime_step(
        pending=[loose],
        deferred=[],
        adopted=[],
        rejected=[],
        current_step="",
        recovered=False,
    )
    assert [item.id for item in passthrough["pending"]] == [loose.id]
    assert passthrough["unscoped"] == []
