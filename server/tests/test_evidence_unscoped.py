"""L4 regressions: evidence auto-bind and the unscoped queue bucket."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.models import EvidenceItem, LearningPlan, PlanStage
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService
from app.memory.workspace_recovery import (
    PLAN_RUNTIME_KEY,
    scope_evidence_queue_to_runtime_step,
)

CURRENT_STEP = "Review the refresh path"


def test_historical_verified_evidence_cannot_complete_revised_stage(tmp_path: Path) -> None:
    workspace_id = "ws-history-adopt"
    repository = TrainerRepository(tmp_path / "history-adopt.db")
    service = MemoryService(repository)
    plan = LearningPlan(
        id="plan-refresh", title="Refresh boundaries", current_stage_id="stage-1",
        current_step=CURRENT_STEP,
        stages=[PlanStage(id="stage-1", title="Boundary checks", goal=CURRENT_STEP, status="active", outcomes=["boundary"])],
    )
    repository.save_plan(workspace_id, plan)
    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(summary="Earlier boundary passed", outcome="pass", target_plan_stage_id="stage-1"),
        verified=True, verification_source="current_file_evaluation",
    )
    _seed_recovered_runtime(service, workspace_id)
    before = repository.get_latest_plan(workspace_id).model_dump()
    with pytest.raises(HTTPException) as error:
        service.adopt_evidence(workspace_id, item.id)
    assert error.value.status_code == 409
    assert repository.get_latest_plan(workspace_id).model_dump() == before
    rebuilt = MemoryService(TrainerRepository(tmp_path / "history-adopt.db"))
    history = rebuilt.evidence_queue(workspace_id).history
    assert len(history) == 1
    assert history[0].id == item.id
    assert not history[0].adopted


def test_independent_verified_evidence_is_recorded_without_advancing_plan(tmp_path: Path) -> None:
    workspace_id = "ws-independent-adopt"
    repository = TrainerRepository(tmp_path / "independent-adopt.db")
    service = MemoryService(repository)
    plan = LearningPlan(
        id="plan-refresh", title="Refresh boundaries", current_stage_id="stage-1",
        current_step=CURRENT_STEP,
        stages=[PlanStage(id="stage-1", title="Boundary checks", goal=CURRENT_STEP, status="active", outcomes=["boundary"])],
    )
    repository.save_plan(workspace_id, plan)
    _seed_recovered_runtime(service, workspace_id)
    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(summary="Independent boundary check", outcome="pass", concepts=["boundary"]),
        verified=True, verification_source="current_file_evaluation", auto_bind_current_plan=False,
    )
    before = repository.get_latest_plan(workspace_id).model_dump()
    service.update_workspace_state(workspace_id, selected_card_id="current-review",
                                   selected_card_title="Recall: Python",
                                   latest_training_next_hop={"title": "Recall: Python"})
    workspace_before = service.snapshot(workspace_id).workspace.copy()
    response = service.adopt_evidence(workspace_id, item.id)
    assert response.evidence.adopted
    assert not response.plan_updated
    assert repository.get_latest_plan(workspace_id).model_dump() == before
    assert service.snapshot(workspace_id).workspace == workspace_before
    assert service.recover_workspace_facts(workspace_id)["latest_plan_runtime"]["current_step"] == CURRENT_STEP


def test_fresh_stage_evidence_keeps_its_step_binding_after_plan_revision(tmp_path: Path) -> None:
    workspace_id = "ws-fresh-stage-binding"
    repository = TrainerRepository(tmp_path / "fresh-binding.db")
    service = MemoryService(repository)
    plan = LearningPlan(
        id="plan-refresh", title="Refresh boundaries", current_stage_id="stage-1",
        current_step=CURRENT_STEP,
        stages=[PlanStage(id="stage-1", title="Boundary checks", goal=CURRENT_STEP, status="active", outcomes=["boundary"])],
    )
    repository.save_plan(workspace_id, plan)
    _seed_recovered_runtime(service, workspace_id)
    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(summary="Current stage check", outcome="pass", target_plan_stage_id="stage-1",
                     target_plan_step="Client-supplied step must be ignored"),
        verified=True, verification_source="current_file_evaluation",
    )
    assert item.target_plan_step == CURRENT_STEP
    assert [entry.id for entry in service.evidence_queue(workspace_id).pending] == [item.id]
    revised_step = "Add the missing hash boundary"
    revised = plan.model_copy(update={"current_step": revised_step})
    repository.save_plan(workspace_id, revised)
    service.bind_explicit_generated_plan(workspace_id, revised)
    rebuilt = MemoryService(TrainerRepository(tmp_path / "fresh-binding.db"))
    assert [entry.id for entry in rebuilt.evidence_queue(workspace_id).history] == [item.id]
    with pytest.raises(HTTPException) as error:
        rebuilt.adopt_evidence(workspace_id, item.id)
    assert error.value.status_code == 409
    assert repository.get_latest_plan(workspace_id).current_step == revised_step


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
