"""Pure append-only workspace state projection (Event-Log Evolution Steps 1-3).

Reduces effective ``EventLedgerEntry`` records for a single workspace into an
authoritative, deterministic :class:`ProjectedWorkspaceState`. Only events in
the latest ``workspace_epoch`` contribute to live workspace state, so stale
pre-reset plans, cards, and evidence are excluded structurally instead of
requiring heuristic ``leftover_*`` scrubbers.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

_PLAN_AUTHORITY_EVENTS = frozenset(
    {
        EVENT_BASELINE_IMPORTED,
        EVENT_WORKSPACE_RESET,
        EVENT_SANDBOX_WORKSPACE_CLEARED,
        EVENT_PLAN_GENERATED,
        EVENT_PLAN_UPDATED,
        EVENT_PLAN_STAGE_ADVANCED,
        EVENT_PLAN_REPLANNED_AFTER_FAILURE,
        EVENT_PLAN_CLEARED,
    }
)

_CARD_AUTHORITY_EVENTS = frozenset(
    {
        EVENT_BASELINE_IMPORTED,
        EVENT_WORKSPACE_RESET,
        EVENT_SANDBOX_WORKSPACE_CLEARED,
        EVENT_PLAN_CLEARED,
        EVENT_ACTIVE_CARD_SELECTED,
        EVENT_CARD_STATUS_TRANSITIONED,
    }
)


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
    has_plan_authority: bool = False
    has_card_authority: bool = False

    @property
    def has_live_plan(self) -> bool:
        return bool(self.active_plan_id) and not self.recovered_without_live_plan

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "workspace_epoch": self.workspace_epoch,
            "state_seq": self.state_seq,
            "has_live_plan": self.has_live_plan,
            "active_plan_id": self.active_plan_id,
            "active_plan_title": self.active_plan_title,
            "active_step_id": self.active_step_id,
            "selected_card_id": self.selected_card_id,
            "completed_card_ids": list(self.completed_card_ids),
            "pending_evidence_ids": list(self.pending_evidence_ids),
            "adopted_evidence_ids": list(self.adopted_evidence_ids),
            "rejected_evidence_ids": list(self.rejected_evidence_ids),
            "resource_ids": list(self.resource_ids),
            "recovered_without_live_plan": self.recovered_without_live_plan,
            "has_plan_authority": self.has_plan_authority,
            "has_card_authority": self.has_card_authority,
        }


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


def _extract_snapshot_selected_card_id(snapshot: Mapping[str, Any]) -> str | None:
    direct = _clean_id(snapshot.get("selected_card_id") or snapshot.get("selectedCardId"))
    if direct is not None:
        return direct
    memory = snapshot.get("memory")
    if isinstance(memory, Mapping):
        workspace = memory.get("workspace")
        if isinstance(workspace, Mapping):
            ws_selected = _clean_id(
                workspace.get("selected_card_id") or workspace.get("selectedCardId")
            )
            if ws_selected is not None:
                return ws_selected
        routing = memory.get("active_training_card_routing") or memory.get(
            "activeTrainingCardRouting"
        )
        if isinstance(routing, Mapping):
            routed = _clean_id(
                routing.get("selected_card_id") or routing.get("selectedCardId")
            )
            if routed is not None:
                return routed
    return None


def _extract_snapshot_pending_evidence_ids(snapshot: Mapping[str, Any]) -> list[str]:
    pending_ids: list[str] = []
    candidates: list[Any] = [snapshot.get("evidence_queue")]
    memory = snapshot.get("memory")
    if isinstance(memory, Mapping):
        ev_queue = memory.get("evidence_queue") or memory.get("evidenceQueue")
        if isinstance(ev_queue, Mapping):
            candidates.append(ev_queue.get("pending"))
        else:
            candidates.append(ev_queue)
    for raw in candidates:
        if isinstance(raw, Mapping):
            raw = raw.get("pending")
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            for item in raw:
                if isinstance(item, Mapping):
                    ev_id = _clean_id(item.get("id") or item.get("evidence_id"))
                    if ev_id and ev_id not in pending_ids:
                        pending_ids.append(ev_id)
    return pending_ids


def _extract_snapshot_resource_ids(snapshot: Mapping[str, Any]) -> list[str]:
    resource_ids: list[str] = []
    candidates: list[Any] = [snapshot.get("resources")]
    memory = snapshot.get("memory")
    if isinstance(memory, Mapping):
        candidates.append(memory.get("resources"))
    for raw in candidates:
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            for item in raw:
                if isinstance(item, Mapping):
                    res_id = _clean_id(item.get("id") or item.get("resource_id"))
                    if res_id and res_id not in resource_ids:
                        resource_ids.append(res_id)
    return resource_ids


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
    has_plan_authority = False
    has_card_authority = False

    for entry in ordered:
        payload = entry.payload_ref
        after = entry.after_state_ref
        kind = entry.event_type

        if kind in _PLAN_AUTHORITY_EVENTS:
            has_plan_authority = True
        if kind in _CARD_AUTHORITY_EVENTS:
            has_card_authority = True

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
            status = str(
                payload.get("status") or payload.get("result") or after.get("status") or ""
            ).strip().lower()
            if card_id and status in {"completed", "implemented", "passed", "mastered"}:
                if card_id not in completed_cards:
                    completed_cards.append(card_id)
            if card_id and card_id == selected_card_id and status in {
                "archived",
                "skipped",
                "dismissed",
                "deleted",
            }:
                selected_card_id = None

        elif kind in {EVENT_EVIDENCE_ENQUEUED, EVENT_PLAN_EVIDENCE_CREATED}:
            ev_id = _clean_id(payload.get("evidence_id") or after.get("evidence_id"))
            if (
                ev_id
                and ev_id not in pending_evidence
                and ev_id not in adopted_evidence
                and ev_id not in rejected_evidence
            ):
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
        has_plan_authority=has_plan_authority,
        has_card_authority=has_card_authority,
    )


def bootstrap_baseline_event_from_snapshot(
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert a legacy memory/session snapshot dict into a ``baseline_imported`` payload."""
    plan = snapshot.get("plan")
    plan_map = plan if isinstance(plan, Mapping) else {}
    plan_id = _clean_id(plan_map.get("id") or plan_map.get("plan_id"))
    plan_title = str(plan_map.get("title") or "").strip()
    step_id = _clean_id(
        plan_map.get("current_step_id")
        or plan_map.get("current_stage_id")
        or plan_map.get("active_step_id")
    )

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
        "selected_card_id": _extract_snapshot_selected_card_id(snapshot),
        "pending_evidence_ids": _extract_snapshot_pending_evidence_ids(snapshot),
        "resource_ids": _extract_snapshot_resource_ids(snapshot),
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
    legacy_selected_card = _extract_snapshot_selected_card_id(legacy_snapshot)
    legacy_pending_ids = tuple(_extract_snapshot_pending_evidence_ids(legacy_snapshot))

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


def _apply_card_projection_to_snapshot(
    snapshot_dict: dict[str, Any],
    card_id: str | None,
) -> None:
    if "selected_card_id" in snapshot_dict or card_id is not None:
        snapshot_dict["selected_card_id"] = card_id
    memory = snapshot_dict.get("memory")
    if isinstance(memory, dict):
        workspace = memory.get("workspace")
        if isinstance(workspace, dict):
            workspace["selected_card_id"] = card_id or ""
            if not card_id:
                workspace.pop("selectedCardId", None)
                workspace["selected_card_title"] = ""
        if not card_id:
            memory["active_training_card_routing"] = None


def apply_projected_workspace_state(
    snapshot_dict: dict[str, Any],
    projected: ProjectedWorkspaceState,
    *,
    primary_read: bool = True,
) -> dict[str, Any]:
    """Overlay authoritative event-log projection onto a ``/snapshot`` dict.

    - ``primary_read`` defaults to ``True`` (Event-Log Evolution Step 3).
    - Enforces projected plan state whenever ``projected.has_plan_authority``
      (under ``primary_read=True``) or ``projected.recovered_without_live_plan``
      is active, preventing pre-reset or mismatched leftover plans from leaking.
    - Enforces projected card selection whenever ``projected.has_card_authority``
      (under ``primary_read=True``) or ``projected.recovered_without_live_plan``
      is active, including clearing ``selected_card_id`` on skip/archive/reset.
    """
    if projected.state_seq <= 0:
        return snapshot_dict

    diff = shadow_diff_with_workspace_recovery(projected, snapshot_dict)
    if diff:
        logger.debug(
            "workspace_projection shadow diff workspace=%s epoch=%d seq=%d fields=%s",
            projected.workspace_id,
            projected.workspace_epoch,
            projected.state_seq,
            sorted(diff.keys()),
        )

    enforce_plan = (primary_read and projected.has_plan_authority) or projected.recovered_without_live_plan
    if enforce_plan:
        if not projected.has_live_plan:
            snapshot_dict["plan"] = None
            memory = snapshot_dict.get("memory")
            if isinstance(memory, dict):
                memory["active_plan"] = None
            if projected.recovered_without_live_plan:
                _apply_card_projection_to_snapshot(snapshot_dict, None)
                existing_status = snapshot_dict.get("plan_runtime_status")
                status_map = dict(existing_status) if isinstance(existing_status, Mapping) else {}
                status_map["recovered"] = True
                status_map["workspace_epoch"] = projected.workspace_epoch
                status_map["state_seq"] = projected.state_seq
                snapshot_dict["plan_runtime_status"] = status_map
        elif primary_read:
            existing_plan = snapshot_dict.get("plan")
            if isinstance(existing_plan, Mapping):
                existing_plan_id = _clean_id(existing_plan.get("id") or existing_plan.get("plan_id"))
                if existing_plan_id and existing_plan_id != projected.active_plan_id:
                    snapshot_dict["plan"] = None

    if primary_read and projected.has_card_authority and not projected.recovered_without_live_plan:
        _apply_card_projection_to_snapshot(snapshot_dict, projected.selected_card_id)

    return snapshot_dict
