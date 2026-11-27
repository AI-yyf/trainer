"""Pure append-only workspace state projection (Event-Log Evolution Step 1).

Reduces effective ``EventLedgerEntry`` records for a single workspace into an
authoritative, deterministic :class:`ProjectedWorkspaceState`. Only events in
the latest ``workspace_epoch`` contribute to live workspace state, so stale
pre-reset plans, cards, and evidence are excluded structurally instead of
requiring heuristic ``leftover_*`` scrubbers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .event_ledger import (
    EVENT_ACTIVE_CARD_SELECTED,
    EVENT_BASELINE_IMPORTED,
    EVENT_CARD_STATUS_TRANSITIONED,
    EVENT_EVENT_REVERSED,
    EVENT_EVIDENCE_ADOPTED,
    EVENT_EVIDENCE_ENQUEUED,
    EVENT_EVIDENCE_REJECTED,
    EVENT_PLAN_CLEARED,
    EVENT_PLAN_EVIDENCE_CREATED,
    EVENT_PLAN_GENERATED,
    EVENT_PLAN_REPLANNED_AFTER_FAILURE,
    EVENT_PLAN_STAGE_ADVANCED,
    EVENT_PLAN_UPDATED,
    EVENT_RESOURCE_INDEXED,
    EVENT_RESOURCE_UPLOADED,
    EVENT_SANDBOX_RESOURCE_REMOVED,
    EVENT_SANDBOX_RESOURCE_SYNCED,
    EVENT_SANDBOX_WORKSPACE_CLEARED,
    EVENT_WORKSPACE_RESET,
)
from .models import EventLedgerEntry


@dataclass(frozen=True, slots=True)
class ProjectedWorkspaceState:
    """Authoritative pure projection derived solely from append-only events."""

    workspace_id: str
    workspace_epoch: int = 0
    state_seq: int = 0
    active_plan_id: str | None = None
    active_plan_title: str = ""
    active_step_id: str | None = None
    selected_card_id: str | None = None
    completed_card_ids: tuple[str, ...] = ()
    pending_evidence_ids: tuple[str, ...] = ()
    adopted_evidence_ids: tuple[str, ...] = ()
    rejected_evidence_ids: tuple[str, ...] = ()
    resource_ids: tuple[str, ...] = ()
    recovered_without_live_plan: bool = False

    @property
    def has_live_plan(self) -> bool:
        return bool(self.active_plan_id) and not self.recovered_without_live_plan


def _clean_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _clean_id_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    out: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def project_workspace_state(
    workspace_id: str,
    entries: Sequence[EventLedgerEntry],
) -> ProjectedWorkspaceState:
    """Fold ``entries`` for ``workspace_id`` into a deterministic state view."""
    if not entries:
        return ProjectedWorkspaceState(workspace_id=workspace_id)

    reversed_ids = {
        str(e.payload_ref.get("reversed_event_id") or "").strip()
        for e in entries
        if e.event_type == EVENT_EVENT_REVERSED
    }
    effective = [
        e
        for e in entries
        if e.event_type != EVENT_EVENT_REVERSED and e.event_id not in reversed_ids
    ]
    if not effective:
        latest_epoch = max((e.workspace_epoch for e in entries), default=0)
        latest_seq = max((e.seq for e in entries), default=0)
        return ProjectedWorkspaceState(
            workspace_id=workspace_id,
            workspace_epoch=latest_epoch,
            state_seq=latest_seq,
        )

    active_epoch = max(e.workspace_epoch for e in effective)
    latest_seq = max(e.seq for e in entries)
    ordered = sorted(
        (e for e in effective if e.workspace_epoch == active_epoch),
        key=lambda e: (e.seq, e.occurred_at, e.event_id),
    )

    active_plan_id: str | None = None
    active_plan_title = ""
    active_step_id: str | None = None
    selected_card_id: str | None = None
    completed_cards: list[str] = []
    pending_evidence: list[str] = []
    adopted_evidence: list[str] = []
    rejected_evidence: list[str] = []
    resources: list[str] = []
    recovered_without_live_plan = False

    for entry in ordered:
        payload = entry.payload_ref
        after = entry.after_state_ref
        kind = entry.event_type

        if kind == EVENT_BASELINE_IMPORTED:
            active_plan_id = _clean_id(payload.get("active_plan_id") or after.get("active_plan_id"))
            active_plan_title = str(payload.get("active_plan_title") or "").strip()
            active_step_id = _clean_id(payload.get("active_step_id") or after.get("active_step_id"))
            selected_card_id = _clean_id(payload.get("selected_card_id") or after.get("selected_card_id"))
            completed_cards = _clean_id_list(payload.get("completed_card_ids"))
            pending_evidence = _clean_id_list(payload.get("pending_evidence_ids"))
            adopted_evidence = _clean_id_list(payload.get("adopted_evidence_ids"))
            rejected_evidence = _clean_id_list(payload.get("rejected_evidence_ids"))
            resources = _clean_id_list(payload.get("resource_ids"))
            recovered_without_live_plan = bool(payload.get("recovered_without_live_plan")) and not active_plan_id

        elif kind in {EVENT_WORKSPACE_RESET, EVENT_SANDBOX_WORKSPACE_CLEARED}:
            active_plan_id = None
            active_plan_title = ""
            active_step_id = None
            selected_card_id = None
            completed_cards.clear()
            pending_evidence.clear()
            adopted_evidence.clear()
            rejected_evidence.clear()
            if kind == EVENT_WORKSPACE_RESET and not bool(payload.get("retain_resources")):
                resources.clear()
            recovered_without_live_plan = True

        elif kind in {
            EVENT_PLAN_GENERATED,
            EVENT_PLAN_UPDATED,
            EVENT_PLAN_STAGE_ADVANCED,
            EVENT_PLAN_REPLANNED_AFTER_FAILURE,
        }:
            plan_id = _clean_id(payload.get("plan_id") or after.get("plan_id") or active_plan_id)
            if plan_id is not None:
                active_plan_id = plan_id
            title = str(payload.get("title") or after.get("title") or "").strip()
            if title:
                active_plan_title = title
            step_id = _clean_id(
                payload.get("current_step_id")
                or payload.get("step_id")
                or after.get("current_step_id")
                or after.get("step_id")
            )
            if step_id is not None:
                active_step_id = step_id
            recovered_without_live_plan = False

        elif kind == EVENT_PLAN_CLEARED:
            active_plan_id = None
            active_plan_title = ""
            active_step_id = None
            selected_card_id = None
            pending_evidence.clear()
            recovered_without_live_plan = True

        elif kind == EVENT_ACTIVE_CARD_SELECTED:
            selected_card_id = _clean_id(payload.get("card_id") or after.get("selected_card_id"))

        elif kind == EVENT_CARD_STATUS_TRANSITIONED:
            card_id = _clean_id(payload.get("card_id") or after.get("card_id"))
            status = str(payload.get("status") or after.get("status") or "").strip().lower()
            if card_id and status in {"completed", "passed", "mastered"}:
                if card_id not in completed_cards:
                    completed_cards.append(card_id)
            if card_id and card_id == selected_card_id and status in {"archived", "dismissed", "deleted"}:
                selected_card_id = None

        elif kind in {EVENT_EVIDENCE_ENQUEUED, EVENT_PLAN_EVIDENCE_CREATED}:
            ev_id = _clean_id(payload.get("evidence_id") or after.get("evidence_id"))
            if ev_id and ev_id not in pending_evidence and ev_id not in adopted_evidence and ev_id not in rejected_evidence:
                pending_evidence.append(ev_id)

        elif kind == EVENT_EVIDENCE_ADOPTED:
            ev_id = _clean_id(payload.get("evidence_id") or after.get("evidence_id"))
            if ev_id:
                if ev_id in pending_evidence:
                    pending_evidence.remove(ev_id)
                if ev_id not in adopted_evidence:
                    adopted_evidence.append(ev_id)

        elif kind == EVENT_EVIDENCE_REJECTED:
            ev_id = _clean_id(payload.get("evidence_id") or after.get("evidence_id"))
            if ev_id:
                if ev_id in pending_evidence:
                    pending_evidence.remove(ev_id)
                if ev_id not in rejected_evidence:
                    rejected_evidence.append(ev_id)

        elif kind in {EVENT_RESOURCE_UPLOADED, EVENT_RESOURCE_INDEXED, EVENT_SANDBOX_RESOURCE_SYNCED}:
            res_id = _clean_id(payload.get("resource_id") or after.get("resource_id"))
            if res_id and res_id not in resources:
                resources.append(res_id)

        elif kind == EVENT_SANDBOX_RESOURCE_REMOVED:
            res_id = _clean_id(payload.get("resource_id") or after.get("resource_id"))
            if res_id and res_id in resources:
                resources.remove(res_id)

    return ProjectedWorkspaceState(
        workspace_id=workspace_id,
        workspace_epoch=active_epoch,
        state_seq=latest_seq,
        active_plan_id=active_plan_id,
        active_plan_title=active_plan_title,
        active_step_id=active_step_id,
        selected_card_id=selected_card_id,
        completed_card_ids=tuple(completed_cards),
        pending_evidence_ids=tuple(pending_evidence),
        adopted_evidence_ids=tuple(adopted_evidence),
        rejected_evidence_ids=tuple(rejected_evidence),
        resource_ids=tuple(resources),
        recovered_without_live_plan=recovered_without_live_plan,
    )


def bootstrap_baseline_event_from_snapshot(
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert a legacy memory/session snapshot dict into a ``baseline_imported`` payload."""
    plan = snapshot.get("plan")
    plan_map = plan if isinstance(plan, Mapping) else {}
    plan_id = _clean_id(plan_map.get("id") or plan_map.get("plan_id"))
    plan_title = str(plan_map.get("title") or "").strip()
    step_id = _clean_id(plan_map.get("current_step_id") or plan_map.get("active_step_id"))

    evidence_raw = snapshot.get("evidence_queue")
    pending_ids: list[str] = []
    if isinstance(evidence_raw, Sequence) and not isinstance(evidence_raw, (str, bytes)):
        for item in evidence_raw:
            if isinstance(item, Mapping):
                ev_id = _clean_id(item.get("id") or item.get("evidence_id"))
                if ev_id and ev_id not in pending_ids:
                    pending_ids.append(ev_id)

    resources_raw = snapshot.get("resources")
    resource_ids: list[str] = []
    if isinstance(resources_raw, Sequence) and not isinstance(resources_raw, (str, bytes)):
        for item in resources_raw:
            if isinstance(item, Mapping):
                res_id = _clean_id(item.get("id") or item.get("resource_id"))
                if res_id and res_id not in resource_ids:
                    resource_ids.append(res_id)

    runtime_status = snapshot.get("plan_runtime_status")
    recovered = (
        isinstance(runtime_status, Mapping)
        and bool(runtime_status.get("recovered"))
        and plan_id is None
    )
    return {
        "active_plan_id": plan_id,
        "active_plan_title": plan_title,
        "active_step_id": step_id,
        "selected_card_id": _clean_id(snapshot.get("selected_card_id")),
        "pending_evidence_ids": pending_ids,
        "resource_ids": resource_ids,
        "recovered_without_live_plan": recovered,
    }


def shadow_diff_with_workspace_recovery(
    projected: ProjectedWorkspaceState,
    legacy_snapshot: Mapping[str, Any],
) -> dict[str, tuple[Any, Any]]:
    """Compare core fields of ``projected`` against a legacy ``workspace_recovery`` snapshot.

    Returns an empty dict when both views agree; otherwise maps each diverging
    field name to ``(projected_value, legacy_value)``.
    """
    legacy_plan = legacy_snapshot.get("plan")
    legacy_plan_map = legacy_plan if isinstance(legacy_plan, Mapping) else {}
    legacy_plan_id = _clean_id(legacy_plan_map.get("id") or legacy_plan_map.get("plan_id"))
    legacy_selected_card = _clean_id(legacy_snapshot.get("selected_card_id"))

    legacy_evidence_raw = legacy_snapshot.get("evidence_queue")
    legacy_pending_ids: tuple[str, ...] = ()
    if isinstance(legacy_evidence_raw, Sequence) and not isinstance(legacy_evidence_raw, (str, bytes)):
        extracted = [
            ev_id
            for item in legacy_evidence_raw
            if isinstance(item, Mapping)
            for ev_id in (_clean_id(item.get("id") or item.get("evidence_id")),)
            if ev_id is not None
        ]
        legacy_pending_ids = tuple(dict.fromkeys(extracted))

    legacy_runtime = legacy_snapshot.get("plan_runtime_status")
    legacy_recovered = (
        isinstance(legacy_runtime, Mapping)
        and bool(legacy_runtime.get("recovered"))
        and legacy_plan_id is None
    )

    pairs: dict[str, tuple[Any, Any]] = {
        "has_live_plan": (projected.has_live_plan, legacy_plan_id is not None),
        "active_plan_id": (projected.active_plan_id, legacy_plan_id),
        "selected_card_id": (projected.selected_card_id, legacy_selected_card),
        "pending_evidence_ids": (projected.pending_evidence_ids, legacy_pending_ids),
        "recovered_without_live_plan": (projected.recovered_without_live_plan, legacy_recovered),
    }
    return {field: (a, b) for field, (a, b) in pairs.items() if a != b}
