from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.event_ledger import (
    EVENT_ACTIVE_CARD_SELECTED,
    EVENT_BASELINE_IMPORTED,
    EVENT_CARD_STATUS_TRANSITIONED,
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
from app.core.workspace_state_projector import (
    bootstrap_baseline_event_from_snapshot,
    project_workspace_state,
    shadow_diff_with_workspace_recovery,
)


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
