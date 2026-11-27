from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.event_ledger import (
    EVENT_ACTIVE_CARD_SELECTED,
    EVENT_BASELINE_IMPORTED,
    EVENT_CARD_STATUS_TRANSITIONED,
    EVENT_COACH_TURN_RECORDED,
    EVENT_EVIDENCE_ADOPTED,
    EVENT_EVIDENCE_ENQUEUED,
    EVENT_EVIDENCE_REJECTED,
    EVENT_PLAN_CLEARED,
    EVENT_PLAN_GENERATED,
    EVENT_PLAN_STAGE_ADVANCED,
    EVENT_RESOURCE_INDEXED,
    EVENT_SANDBOX_RESOURCE_REMOVED,
    EVENT_WORKSPACE_RESET,
    EventLedgerService,
)
from app.core.event_ledger_store import EventLedgerStore
from app.core.models import (
    ActiveCardSelectionResult,
    EvidenceItem,
    LearningPlan,
    PlanStage,
    TrainingCardCandidateSnapshot,
)
from app.core.workspace_state_projector import (
    apply_projected_workspace_state,
    bootstrap_baseline_event_from_snapshot,
    project_workspace_state,
    shadow_diff_with_workspace_recovery,
)
from app.main import create_app


def test_event_ledger_store_assigns_monotonic_seq_and_bumps_epoch_on_reset(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    store = EventLedgerStore(db_path)
    ledger = EventLedgerService(store)

    e1 = ledger.record_event(
        EVENT_PLAN_GENERATED,
        workspace_id="ws-a",
        project_id="ws-a",
        payload_ref={"plan_id": "plan-1", "title": "Async Python", "current_step_id": "step-1"},
    )
    e2 = ledger.record_event(
        EVENT_ACTIVE_CARD_SELECTED,
        workspace_id="ws-a",
        project_id="ws-a",
        payload_ref={"card_id": "card-1"},
    )
    e3 = ledger.record_event(
        EVENT_EVIDENCE_ENQUEUED,
        workspace_id="ws-a",
        project_id="ws-a",
        payload_ref={"evidence_id": "ev-1"},
    )
    # Different workspace maintains independent monotonic seq
    eb = ledger.record_event(
        EVENT_PLAN_GENERATED,
        workspace_id="ws-b",
        project_id="ws-b",
        payload_ref={"plan_id": "plan-b", "title": "Other"},
    )
    assert (e1.workspace_epoch, e1.seq) == (0, 1)
    assert (e2.workspace_epoch, e2.seq) == (0, 2)
    assert (e3.workspace_epoch, e3.seq) == (0, 3)
    assert (eb.workspace_epoch, eb.seq) == (0, 1)

    # Reset bumps workspace_epoch so pre-reset plan/card/evidence never leak into live projection
    e4 = ledger.record_event(
        EVENT_WORKSPACE_RESET,
        workspace_id="ws-a",
        project_id="ws-a",
    )
    assert (e4.workspace_epoch, e4.seq) == (1, 4)
    assert ledger.current_workspace_coords("ws-a") == (1, 4)

    projected = project_workspace_state("ws-a", ledger.effective_workspace_entries("ws-a"))
    assert projected.workspace_epoch == 1
    assert projected.state_seq == 4
    assert projected.has_live_plan is False
    assert projected.active_plan_id is None
    assert projected.selected_card_id is None
    assert projected.pending_evidence_ids == ()
    assert projected.recovered_without_live_plan is True
    assert projected.has_plan_authority is True
    assert projected.has_card_authority is True


def test_event_ledger_store_migrates_legacy_table_without_epoch_and_seq(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_ledger.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE event_ledger (
            event_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'system',
            scope TEXT NOT NULL DEFAULT '',
            project_id TEXT NOT NULL DEFAULT '',
            source_chain_json TEXT NOT NULL DEFAULT '[]',
            payload_ref_json TEXT NOT NULL DEFAULT '{}',
            before_state_ref_json TEXT NOT NULL DEFAULT '{}',
            after_state_ref_json TEXT NOT NULL DEFAULT '{}',
            reversibility TEXT NOT NULL DEFAULT 'irreversible',
            audit_note TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()

    store = EventLedgerStore(db_path)
    ledger = EventLedgerService(store)
    entry = ledger.record_event(
        EVENT_PLAN_GENERATED,
        workspace_id="ws-legacy",
        project_id="ws-legacy",
        payload_ref={"plan_id": "plan-legacy"},
    )
    assert entry.workspace_epoch == 0
    assert entry.seq == 1


def test_shadow_diff_matches_workspace_recovery_across_live_and_recovered_scenarios(tmp_path: Path) -> None:
    store = EventLedgerStore(tmp_path / "shadow.db")
    ledger = EventLedgerService(store)

    # Scenario 1: Active live plan + selected card + pending/adopted/rejected evidence + resources
    ledger.record_event(
        EVENT_PLAN_GENERATED,
        workspace_id="ws-1",
        project_id="ws-1",
        payload_ref={"plan_id": "plan-101", "title": "Concurrency", "current_step_id": "step-1"},
    )
    ledger.record_event(
        EVENT_PLAN_STAGE_ADVANCED,
        workspace_id="ws-1",
        project_id="ws-1",
        payload_ref={"step_id": "step-2"},
    )
    ledger.record_event(
        EVENT_ACTIVE_CARD_SELECTED,
        workspace_id="ws-1",
        project_id="ws-1",
        payload_ref={"card_id": "card-9"},
    )
    ledger.record_event(
        EVENT_EVIDENCE_ENQUEUED,
        workspace_id="ws-1",
        project_id="ws-1",
        payload_ref={"evidence_id": "ev-a"},
    )
    ledger.record_event(
        EVENT_EVIDENCE_ENQUEUED,
        workspace_id="ws-1",
        project_id="ws-1",
        payload_ref={"evidence_id": "ev-b"},
    )
    ledger.record_event(
        EVENT_EVIDENCE_ADOPTED,
        workspace_id="ws-1",
        project_id="ws-1",
        payload_ref={"evidence_id": "ev-a"},
    )
    ledger.record_event(
        EVENT_EVIDENCE_ENQUEUED,
        workspace_id="ws-1",
        project_id="ws-1",
        payload_ref={"evidence_id": "ev-c"},
    )
    ledger.record_event(
        EVENT_EVIDENCE_REJECTED,
        workspace_id="ws-1",
        project_id="ws-1",
        payload_ref={"evidence_id": "ev-c"},
    )
    ledger.record_event(
        EVENT_RESOURCE_INDEXED,
        workspace_id="ws-1",
        project_id="ws-1",
        payload_ref={"resource_id": "res-1"},
    )
    ledger.record_event(
        EVENT_CARD_STATUS_TRANSITIONED,
        workspace_id="ws-1",
        project_id="ws-1",
        payload_ref={"card_id": "card-9", "status": "completed"},
    )

    projected_live = project_workspace_state("ws-1", ledger.effective_workspace_entries("ws-1"))
    legacy_live_snapshot = {
        "plan": {"id": "plan-101", "title": "Concurrency", "current_step_id": "step-2"},
        "selected_card_id": "card-9",
        "evidence_queue": [{"id": "ev-b"}],
        "plan_runtime_status": {"recovered": False},
    }
    assert shadow_diff_with_workspace_recovery(projected_live, legacy_live_snapshot) == {}
    assert projected_live.adopted_evidence_ids == ("ev-a",)
    assert projected_live.rejected_evidence_ids == ("ev-c",)
    assert projected_live.completed_card_ids == ("card-9",)
    assert projected_live.resource_ids == ("res-1",)

    # Scenario 2: Plan cleared -> matches recovered-without-live-plan legacy overlay with zero diff
    ledger.record_event(
        EVENT_PLAN_CLEARED,
        workspace_id="ws-1",
        project_id="ws-1",
    )
    ledger.record_event(
        EVENT_SANDBOX_RESOURCE_REMOVED,
        workspace_id="ws-1",
        project_id="ws-1",
        payload_ref={"resource_id": "res-1"},
    )
    projected_cleared = project_workspace_state("ws-1", ledger.effective_workspace_entries("ws-1"))
    legacy_recovered_snapshot = {
        "plan": None,
        "selected_card_id": None,
        "evidence_queue": [],
        "plan_runtime_status": {"recovered": True},
    }
    assert shadow_diff_with_workspace_recovery(projected_cleared, legacy_recovered_snapshot) == {}
    assert projected_cleared.resource_ids == ()

    # Scenario 3: Cold-start legacy snapshot bootstrap yields zero shadow diff
    baseline_payload = bootstrap_baseline_event_from_snapshot(legacy_live_snapshot)
    ledger_cold = EventLedgerService()
    ledger_cold.record_event(
        EVENT_BASELINE_IMPORTED,
        workspace_id="ws-cold",
        project_id="ws-cold",
        payload_ref=baseline_payload,
    )
    projected_cold = project_workspace_state("ws-cold", ledger_cold.effective_workspace_entries("ws-cold"))
    assert shadow_diff_with_workspace_recovery(projected_cold, legacy_live_snapshot) == {}


def test_step2_event_ledger_project_and_apply_projected_state_on_snapshot(tmp_path: Path) -> None:
    store = EventLedgerStore(tmp_path / "step2.db")
    ledger = EventLedgerService(store)

    ledger.record_event(
        EVENT_PLAN_GENERATED,
        workspace_id="ws-s2",
        project_id="ws-s2",
        payload_ref={"plan_id": "plan-old", "title": "Old Plan", "current_step_id": "step-1"},
    )
    ledger.record_event(
        EVENT_ACTIVE_CARD_SELECTED,
        workspace_id="ws-s2",
        project_id="ws-s2",
        payload_ref={"card_id": "card-live"},
    )

    projected_live = ledger.project_workspace_state("ws-s2")
    assert projected_live.to_dict()["has_live_plan"] is True
    assert projected_live.to_dict()["active_plan_id"] == "plan-old"
    assert projected_live.to_dict()["selected_card_id"] == "card-live"

    live_snap = {"plan": {"id": "plan-old"}, "selected_card_id": "stale-card"}
    apply_projected_workspace_state(live_snap, projected_live, primary_read=True)
    assert live_snap["selected_card_id"] == "card-live"

    ledger.record_event(
        EVENT_WORKSPACE_RESET,
        workspace_id="ws-s2",
        project_id="ws-s2",
    )
    projected_reset = ledger.project_workspace_state("ws-s2")
    assert projected_reset.workspace_epoch == 1
    assert projected_reset.recovered_without_live_plan is True

    stale_snap = {
        "plan": {"id": "plan-old"},
        "selected_card_id": "card-live",
        "plan_runtime_status": {"recovered": False},
    }
    apply_projected_workspace_state(stale_snap, projected_reset, primary_read=False)
    assert stale_snap["plan"] is None
    assert stale_snap["selected_card_id"] is None
    assert stale_snap["plan_runtime_status"]["recovered"] is True
    assert stale_snap["plan_runtime_status"]["workspace_epoch"] == 1
    assert stale_snap["plan_runtime_status"]["state_seq"] == 3


def test_step3_snapshot_default_primary_read_hydrates_baseline_and_tracks_live_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRAINER_EVENT_LOG_PRIMARY_READ", raising=False)
    app = create_app(Settings(data_dir=tmp_path))
    runtime = app.state.runtime
    assert runtime.event_ledger is not None
    assert runtime.memory_service._event_ledger is runtime.event_ledger

    ws_cold = "ws-step3-cold"
    legacy_plan = LearningPlan(
        id="plan-cold-1",
        title="Legacy Cold Plan",
        summary="Cold start baseline",
        current_stage_id="stage-1",
        current_step="Verify event projection",
        stages=[
            PlanStage(
                id="stage-1",
                title="Stage 1",
                goal="Verify event projection",
                status="active",
                outcomes=["projection"],
            )
        ],
    )
    # Seed legacy SQLite state without emitting ledger events to simulate pre-Step-3 workspace
    runtime.memory_service._event_ledger = None
    runtime.repository.save_plan(ws_cold, legacy_plan)
    runtime.memory_service.bind_explicit_generated_plan(ws_cold, legacy_plan)
    runtime.memory_service._event_ledger = runtime.event_ledger

    # Record an unrelated chat event first to ensure state_seq > 0 does not wipe cold-start plan
    runtime.event_ledger.record_event(
        EVENT_COACH_TURN_RECORDED,
        workspace_id=ws_cold,
        project_id=ws_cold,
        payload_ref={"message": "hello"},
    )

    with TestClient(app) as client:
        res1 = client.get("/snapshot", params={"workspace_id": ws_cold, "fields": "full"})
        assert res1.status_code == 200
        body1 = res1.json()
        assert body1["snapshot"]["plan"]["id"] == "plan-cold-1"
        proj1 = body1["workspace_projection"]
        assert proj1["has_live_plan"] is True
        assert proj1["active_plan_id"] == "plan-cold-1"
        assert proj1["has_plan_authority"] is True
        seq_after_import = proj1["state_seq"]

        # Repeated /snapshot must not duplicate baseline_imported
        res2 = client.get("/snapshot", params={"workspace_id": ws_cold, "fields": "full"})
        assert res2.status_code == 200
        assert res2.json()["workspace_projection"]["state_seq"] == seq_after_import

        # Live mutations: select saved card -> enqueue evidence -> skip card -> reset workspace
        saved_card = TrainingCardCandidateSnapshot(
            card_id="card-step3-1",
            card_type="practice",
            title="Practice Event Projection",
            status="candidate",
            review_state="saved",
            focus_area="event_ledger",
            target_skill="projection",
        )
        runtime.memory_service.upsert_card(ws_cold, saved_card)
        runtime.memory_service.persist_active_card_selection(
            ws_cold,
            ActiveCardSelectionResult(
                selected_card_id=saved_card.card_id,
                selected_card=saved_card,
                candidate_count=1,
                eligible_count=1,
            ),
        )
        ev = runtime.memory_service.enqueue_evidence(
            ws_cold,
            EvidenceItem(id="ev-step3-1", summary="Passed check", concepts=["projection"], outcome="pass"),
            verified=True,
            verification_source="pytest",
        )
        assert ev.id == "ev-step3-1"

        res_selected = client.get("/snapshot", params={"workspace_id": ws_cold, "fields": "full"})
        body_selected = res_selected.json()
        assert body_selected["workspace_projection"]["selected_card_id"] == "card-step3-1"
        assert "ev-step3-1" in body_selected["workspace_projection"]["pending_evidence_ids"]
        assert body_selected["snapshot"]["memory"]["workspace"]["selected_card_id"] == "card-step3-1"

        # Skipping active card clears selected_card_id in both projection and snapshot
        runtime.memory_service.transition_card_status(ws_cold, "card-step3-1", "skipped", reason="skip")
        res_skipped = client.get("/snapshot", params={"workspace_id": ws_cold, "fields": "full"})
        body_skipped = res_skipped.json()
        assert body_skipped["workspace_projection"]["selected_card_id"] is None
        assert body_skipped["snapshot"]["memory"]["workspace"].get("selected_card_id", "") == ""

        # Resetting workspace bumps epoch and structurally clears live plan on default primary read
        runtime.memory_service.reset_workspace_training_state(ws_cold)
        res_reset = client.get("/snapshot", params={"workspace_id": ws_cold, "fields": "full"})
        body_reset = res_reset.json()
        assert body_reset["workspace_projection"]["workspace_epoch"] == 1
        assert body_reset["workspace_projection"]["has_live_plan"] is False
        assert body_reset["workspace_projection"]["recovered_without_live_plan"] is True
        assert body_reset["snapshot"]["plan"] is None
        assert body_reset["snapshot"]["plan_runtime_status"]["recovered"] is True


def test_step3_primary_read_opt_out_env_preserves_legacy_non_reset_read(
    tmp_path: Path,
) -> None:
    store = EventLedgerStore(tmp_path / "step3_optout.db")
    ledger = EventLedgerService(store)
    ledger.record_event(
        EVENT_PLAN_GENERATED,
        workspace_id="ws-opt",
        project_id="ws-opt",
        payload_ref={"plan_id": "plan-ledger", "title": "Ledger Plan"},
    )
    ledger.record_event(
        EVENT_ACTIVE_CARD_SELECTED,
        workspace_id="ws-opt",
        project_id="ws-opt",
        payload_ref={"card_id": "card-ledger"},
    )
    projected = ledger.project_workspace_state("ws-opt")

    # Default primary_read=True overrides mismatched legacy plan & card
    snap_default = {
        "plan": {"id": "plan-mismatched"},
        "memory": {"workspace": {"selected_card_id": "card-stale"}},
    }
    apply_projected_workspace_state(snap_default, projected)
    assert snap_default["plan"] is None
    assert snap_default["memory"]["workspace"]["selected_card_id"] == "card-ledger"

    # Opt-out primary_read=False leaves non-reset legacy snapshot untouched
    snap_optout = {
        "plan": {"id": "plan-mismatched"},
        "memory": {"workspace": {"selected_card_id": "card-stale"}},
    }
    apply_projected_workspace_state(snap_optout, projected, primary_read=False)
    assert snap_optout["plan"] == {"id": "plan-mismatched"}
    assert snap_optout["memory"]["workspace"]["selected_card_id"] == "card-stale"


def test_step4_session_start_activate_and_memory_summary_carry_authoritative_projection(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    runtime = app.state.runtime
    ws = "ws-step4-parity"

    with TestClient(app) as client:
        start_res = client.post(
            "/session/start",
            json={"workspace_id": ws, "workspace_name": "Step 4 Demo"},
        )
        assert start_res.status_code == 200
        start_body = start_res.json()
        session_id = start_body["session_id"]
        assert start_body["workspaceProjection"]["workspace_id"] == ws
        assert start_body["workspace_projection"]["workspace_id"] == ws

        plan = LearningPlan(
            id="plan-step4-live",
            title="Step 4 Projection Plan",
            summary="End-to-end projection",
            current_stage_id="stage-s4",
            current_step="Wire host projection",
            stages=[
                PlanStage(
                    id="stage-s4",
                    title="Stage S4",
                    goal="Wire host projection",
                    status="active",
                    outcomes=["projection"],
                )
            ],
        )
        runtime.repository.save_plan(ws, plan)
        runtime.memory_service.bind_explicit_generated_plan(ws, plan)
        card = TrainingCardCandidateSnapshot(
            card_id="card-step4-live",
            card_type="practice",
            title="Step 4 Card",
            status="candidate",
            review_state="saved",
            focus_area="projection",
            target_skill="projection",
        )
        runtime.memory_service.upsert_card(ws, card)
        runtime.memory_service.persist_active_card_selection(
            ws,
            ActiveCardSelectionResult(
                selected_card_id=card.card_id,
                selected_card=card,
                candidate_count=1,
                eligible_count=1,
            ),
        )

        summary_res = client.get("/memory/summary", params={"workspace_id": ws, "session_id": session_id})
        assert summary_res.status_code == 200
        summary_proj = summary_res.json()["workspace_projection"]
        assert summary_proj["has_live_plan"] is True
        assert summary_proj["active_plan_id"] == "plan-step4-live"
        assert summary_proj["selected_card_id"] == "card-step4-live"
        assert summary_proj["has_plan_authority"] is True
        assert summary_proj["has_card_authority"] is True

        activate_res = client.post(
            "/session/activate",
            json={"session_id": session_id, "workspace_id": ws},
        )
        assert activate_res.status_code == 200
        activate_body = activate_res.json()
        assert activate_body["workspace_projection"]["active_plan_id"] == "plan-step4-live"
        assert activate_body["workspace_projection"]["selected_card_id"] == "card-step4-live"
        assert activate_body["snapshot"]["workspace_projection"]["state_seq"] == summary_proj["state_seq"]

