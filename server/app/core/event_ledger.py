"""§13.21 Unified Event Ledger Service.

Append-only audit trail for core state changes. Most legacy event consumers keep
their short-lived in-memory view here. Durable agent-turn checkpoints are stored
by :class:`TrainerRepository` because they need restart-safe replay without
re-running providers or tools.

With an :class:`~app.core.event_ledger_store.EventLedgerStore` supplied, entries
are also persisted and idempotency keys replay instead of duplicating.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import uuid4

from .models import EventLedgerEntry, EventReversibility

if TYPE_CHECKING:
    import sqlite3

    from .event_ledger_store import EventLedgerStore

# ---------------------------------------------------------------------------
# §13.21 Event type constants — 39 canonical event types
# ---------------------------------------------------------------------------

# Card lifecycle (6)
EVENT_CARD_CANDIDATE_CREATED = "card_candidate_created"
EVENT_CARD_STATUS_TRANSITIONED = "card_status_transitioned"
EVENT_CARD_SCORE_COMPUTED = "card_score_computed"
EVENT_ACTIVE_CARD_SELECTED = "active_card_selected"
EVENT_PRACTICE_SUBMISSION_RECORDED = "practice_submission_recorded"
EVENT_CARD_GENERATION_FAILED = "card_generation_failed"

# Plan lifecycle (4)
EVENT_PLAN_GENERATED = "plan_generated"
EVENT_PLAN_UPDATED = "plan_updated"
EVENT_PLAN_STAGE_ADVANCED = "plan_stage_advanced"
EVENT_PLAN_REPLANNED_AFTER_FAILURE = "plan_replanned_after_failure"

# Evidence & memory (5)
EVENT_PLAN_EVIDENCE_CREATED = "plan_evidence_created"
EVENT_EVIDENCE_ENQUEUED = "evidence_enqueued"
EVENT_EVIDENCE_ADOPTED = "evidence_adopted"
EVENT_EVIDENCE_REJECTED = "evidence_rejected"
EVENT_MASTERY_SCORE_UPDATED = "mastery_score_updated"

# Weakness & dependency (2)
EVENT_DEPENDENCY_MASTERY_UPDATED = "dependency_mastery_updated"
EVENT_WEAKNESS_RECORDED = "weakness_recorded"

# SubPlan CRUD (3)
EVENT_SUBPLAN_CREATED = "subplan_created"
EVENT_SUBPLAN_UPDATED = "subplan_updated"
EVENT_SUBPLAN_DELETED = "subplan_deleted"

# Sandbox — existing (2)
EVENT_SANDBOX_SKILL_RUN_EXECUTED = "sandbox_skill_run_executed"
EVENT_SANDBOX_ARCHIVE_AUDITED = "sandbox_archive_audited"

# Sandbox — file & resource mutations (9)
EVENT_SANDBOX_FILE_WRITTEN = "sandbox_file_written"
EVENT_SANDBOX_FILE_DELETED = "sandbox_file_deleted"
EVENT_SANDBOX_FILE_RENAMED = "sandbox_file_renamed"
EVENT_SANDBOX_FILES_REORGANIZED = "sandbox_files_reorganized"
EVENT_SANDBOX_COMMAND_EXECUTED = "sandbox_command_executed"
EVENT_SANDBOX_RESOURCE_SYNCED = "sandbox_resource_synced"
EVENT_SANDBOX_RESOURCE_REMOVED = "sandbox_resource_removed"
EVENT_SANDBOX_WORKSPACE_CLEARED = "sandbox_workspace_cleared"

# Resource (2)
EVENT_RESOURCE_UPLOADED = "resource_uploaded"
EVENT_RESOURCE_INDEXED = "resource_indexed"

# Profile & settings (3)
EVENT_PROFILE_UPDATED = "profile_updated"
EVENT_COACH_SETTINGS_UPDATED = "coach_settings_updated"
EVENT_WORKSPACE_UNDERSTANDING_UPDATED = "workspace_understanding_updated"

# Learning & teaching (4)
EVENT_LEARNING_OUTCOME_RECORDED = "learning_outcome_recorded"
EVENT_TEACHING_ASSET_UPSERTED = "teaching_asset_upserted"
EVENT_TEACHING_ASSET_EFFECTIVENESS_UPDATED = "teaching_asset_effectiveness_updated"
EVENT_EVALUATION_FEEDBACK_RECORDED = "evaluation_feedback_recorded"

# Reflection (1)
EVENT_REFLECTION_RECORDED = "reflection_recorded"

# Goal lifecycle (4) — starts, real activities, completion and archival.
EVENT_GOAL_STARTED = "goal_started"
EVENT_GOAL_ACTIVITY_RECORDED = "goal_activity_recorded"
EVENT_GOAL_COMPLETED = "goal_completed"
EVENT_GOAL_ARCHIVED = "goal_archived"

# Agent recovery (1)
EVENT_AGENT_TURN_CHECKPOINTED = "agent_turn_checkpointed"

# Telemetry consent (1) — §P2-18: consent changes are audited like every other
# state change; the entry carries only the opt-in flag and a charset-checked
# source token.
EVENT_TELEMETRY_CONSENT_CHANGED = "telemetry_consent_changed"

# Ledger integrity (1) — append-only compensation for a reversible entry. The
# reversal is a new event; the reversed entry is never mutated or deleted.
EVENT_EVENT_REVERSED = "event_reversed"

# Coaching turns (1) — one entry per completed coach turn so the chat round is
# auditable in the same ledger as training and goals (§P1-3c).
EVENT_COACH_TURN_RECORDED = "coach_turn_recorded"

# Training evidence (2) — the strongest learning fact joins the ledger:
# a recorded controlled check and the reversal of the evidence it superseded.
EVENT_TRAINING_EVIDENCE_RECORDED = "training_evidence_recorded"
EVENT_TRAINING_EVIDENCE_SUPERSEDED = "training_evidence_superseded"

_T = TypeVar("_T")

ALL_EVENT_TYPES: frozenset[str] = frozenset({
    EVENT_CARD_CANDIDATE_CREATED,
    EVENT_CARD_STATUS_TRANSITIONED,
    EVENT_CARD_SCORE_COMPUTED,
    EVENT_ACTIVE_CARD_SELECTED,
    EVENT_PRACTICE_SUBMISSION_RECORDED,
    EVENT_CARD_GENERATION_FAILED,
    EVENT_PLAN_GENERATED,
    EVENT_PLAN_UPDATED,
    EVENT_PLAN_STAGE_ADVANCED,
    EVENT_PLAN_REPLANNED_AFTER_FAILURE,
    EVENT_PLAN_EVIDENCE_CREATED,
    EVENT_EVIDENCE_ENQUEUED,
    EVENT_EVIDENCE_ADOPTED,
    EVENT_EVIDENCE_REJECTED,
    EVENT_MASTERY_SCORE_UPDATED,
    EVENT_DEPENDENCY_MASTERY_UPDATED,
    EVENT_WEAKNESS_RECORDED,
    EVENT_SUBPLAN_CREATED,
    EVENT_SUBPLAN_UPDATED,
    EVENT_SUBPLAN_DELETED,
    EVENT_SANDBOX_SKILL_RUN_EXECUTED,
    EVENT_SANDBOX_ARCHIVE_AUDITED,
    EVENT_SANDBOX_FILE_WRITTEN,
    EVENT_SANDBOX_FILE_DELETED,
    EVENT_SANDBOX_FILE_RENAMED,
    EVENT_SANDBOX_FILES_REORGANIZED,
    EVENT_SANDBOX_COMMAND_EXECUTED,
    EVENT_SANDBOX_RESOURCE_SYNCED,
    EVENT_SANDBOX_RESOURCE_REMOVED,
    EVENT_SANDBOX_WORKSPACE_CLEARED,
    EVENT_RESOURCE_UPLOADED,
    EVENT_RESOURCE_INDEXED,
    EVENT_PROFILE_UPDATED,
    EVENT_COACH_SETTINGS_UPDATED,
    EVENT_WORKSPACE_UNDERSTANDING_UPDATED,
    EVENT_LEARNING_OUTCOME_RECORDED,
    EVENT_TEACHING_ASSET_UPSERTED,
    EVENT_TEACHING_ASSET_EFFECTIVENESS_UPDATED,
    EVENT_EVALUATION_FEEDBACK_RECORDED,
    EVENT_REFLECTION_RECORDED,
    EVENT_AGENT_TURN_CHECKPOINTED,
    EVENT_TELEMETRY_CONSENT_CHANGED,
    EVENT_EVENT_REVERSED,
    EVENT_COACH_TURN_RECORDED,
    EVENT_TRAINING_EVIDENCE_RECORDED,
    EVENT_TRAINING_EVIDENCE_SUPERSEDED,
    EVENT_GOAL_STARTED,
    EVENT_GOAL_ACTIVITY_RECORDED,
    EVENT_GOAL_COMPLETED,
    EVENT_GOAL_ARCHIVED,
})


class EventLedgerService:
    """§13.21 Central event ledger — append-only, queryable store.

    When an :class:`EventLedgerStore` is supplied the ledger reads durable history and
    replays ``(workspace, idempotency_key)`` duplicates instead of appending
    the same learning fact twice.
    """

    def __init__(
        self,
        store: "EventLedgerStore | None" = None,
        *,
        hydrate_limit: int = 2000,
    ) -> None:
        self._entries: list[EventLedgerEntry] = []
        self._counter: int = 0
        self._store = store
        self._idempotent: dict[tuple[str, str], EventLedgerEntry] = {}
        self._reversals: set[str] = set()
        self._lock = threading.Lock()
        # Kept for callers that previously configured startup hydration.
        # Persistent reads no longer depend on hydration.
        del hydrate_limit

    def record_event(
        self,
        event_type: str,
        *,
        actor: str = "system",
        scope: str = "",
        project_id: str = "",
        source_chain: list[str] | None = None,
        payload_ref: dict[str, Any] | None = None,
        before_state_ref: dict[str, Any] | None = None,
        after_state_ref: dict[str, Any] | None = None,
        reversibility: EventReversibility = "irreversible",
        audit_note: str = "",
        workspace_id: str = "",
        idempotency_key: str = "",
        transaction: "sqlite3.Connection | None" = None,
    ) -> EventLedgerEntry:
        """Record a new event in the ledger and return the entry.

        ``workspace_id`` scopes storage and idempotency (defaults to
        ``project_id``). A repeated non-empty ``idempotency_key`` within the
        same workspace returns the already-recorded entry unchanged.
        """
        workspace = workspace_id or project_id
        key = idempotency_key.strip()
        if transaction is not None and self._store is None:
            raise ValueError("A persistent event ledger is required for transactional writes.")
        # Persistent writes are serialized by SQLite. A caller can hold the
        # database lock already, so taking the in-memory lock risks deadlock.
        with self._lock if self._store is None else nullcontext():
            if key and self._store is None:
                cached = self._idempotent.get((workspace, key))
                if cached is not None:
                    return cached
            from .models import utc_now_iso

            fields: dict[str, Any] = {
                "event_type": event_type,
                "occurred_at": utc_now_iso(),
                "actor": actor,
                "scope": scope,
                "project_id": project_id,
                "source_chain": list(source_chain or []),
                "payload_ref": dict(payload_ref or {}),
                "before_state_ref": dict(before_state_ref or {}),
                "after_state_ref": dict(after_state_ref or {}),
                "reversibility": reversibility,
                "audit_note": audit_note,
            }
            if self._store is None:
                self._counter += 1
                entry = EventLedgerEntry(event_id=f"evt-{self._counter:06d}", **fields)
                created = True
            else:
                entry = EventLedgerEntry(event_id=f"evt-{uuid4().hex}", **fields)
                entry, created = self._store.append(
                    entry,
                    workspace_id=workspace,
                    idempotency_key=key,
                    transaction=transaction,
                )
            if created and self._store is None:
                self._entries.append(entry)
            if self._store is None and entry.event_type == EVENT_EVENT_REVERSED:
                reversed_id = entry.payload_ref.get("reversed_event_id")
                if isinstance(reversed_id, str) and reversed_id:
                    self._reversals.add(reversed_id)
            if key and self._store is None:
                self._idempotent[(workspace, key)] = entry
            return entry

    def _find_entry(self, event_id: str) -> EventLedgerEntry | None:
        with self._lock:
            for entry in reversed(self._entries):
                if entry.event_id == event_id:
                    return entry
        return None

    def reverse_event(
        self,
        event_id: str,
        *,
        workspace_id: str = "",
        actor: str = "learner",
        reason: str = "",
    ) -> EventLedgerEntry | None:
        """Append a reversal for ``event_id``; only reversible entries qualify.

        The original entry is never mutated or deleted. Repeating the reversal
        returns the already-recorded reversal (idempotent). Returns ``None`` for
        an unknown or irreversible event.
        """
        if self._store is None:
            target = self._find_entry(event_id)
            target_workspace = target.project_id if target is not None else ""
        else:
            stored = self._store.find_event(event_id)
            target_workspace, target = stored if stored is not None else ("", None)
        if target is None or target.reversibility != "reversible":
            return None
        if workspace_id and workspace_id != target_workspace:
            return None
        if self._store is not None:
            recorded = self._store.find_reversal(event_id)
            if recorded is not None:
                return recorded
        with self._lock:
            already_reversed = event_id in self._reversals
            existing = (
                next(
                    (
                        entry
                        for entry in reversed(self._entries)
                        if entry.event_type == EVENT_EVENT_REVERSED
                        and entry.payload_ref.get("reversed_event_id") == event_id
                    ),
                    None,
                )
                if already_reversed
                else None
            )
        if existing is not None:
            return existing
        return self._record_reversal(target, target_workspace, actor, reason)

    def _record_reversal(
        self, target: EventLedgerEntry, workspace_id: str, actor: str, reason: str,
        *, transaction: "sqlite3.Connection | None" = None,
    ) -> EventLedgerEntry:
        event_id = target.event_id
        return self.record_event(
            EVENT_EVENT_REVERSED,
            actor=actor,
            scope=target.scope,
            project_id=target.project_id,
            workspace_id=workspace_id,
            source_chain=[*target.source_chain, "reversal"],
            payload_ref={"reversed_event_id": event_id, "reason": reason},
            reversibility="irreversible",
            audit_note=(
                f"Reversed event {event_id}" + (f": {reason}" if reason else "")
            ),
            idempotency_key=f"reversal:{event_id}",
            transaction=transaction,
        )

    def is_reversed(self, event_id: str) -> bool:
        if self._store is not None:
            return self._store.find_reversal(event_id) is not None
        with self._lock:
            return event_id in self._reversals

    def reverse_by_idempotency_key(
        self,
        workspace_id: str,
        idempotency_key: str,
        *,
        actor: str = "system",
        reason: str = "",
        transaction: "sqlite3.Connection | None" = None,
    ) -> EventLedgerEntry | None:
        """Reverse the event recorded under ``(workspace, idempotency_key)``.

        Looks the entry up in the persistent store (so it works across
        restarts), then appends a reversal. Returns None when no such event
        exists or it was not reversible.
        """
        key = str(idempotency_key or "").strip()
        if not key or self._store is None:
            return None
        entry = self._store.find_by_idempotency_key(
            workspace_id=workspace_id or "", idempotency_key=key, transaction=transaction,
        )
        if entry is None or entry.reversibility != "reversible":
            return None
        if transaction is not None:
            return self._record_reversal(entry, workspace_id, actor, reason, transaction=transaction)
        return self.reverse_event(
            entry.event_id, workspace_id=workspace_id, actor=actor, reason=reason
        )

    def effective_entries(self, *, project_id: str | None = None) -> list[EventLedgerEntry]:
        """Entries with reversed events (and reversal bookkeeping) removed."""
        if self._store is not None:
            return self._store.query(project_id=project_id, effective=True)
        with self._lock:
            reversed_ids = set(self._reversals)
            return [
                entry
                for entry in self._entries
                if entry.event_id not in reversed_ids
                and entry.event_type != EVENT_EVENT_REVERSED
                and (project_id is None or entry.project_id == project_id)
            ]

    def replay(
        self,
        initial: _T,
        apply: Callable[[_T, EventLedgerEntry], _T],
    ) -> _T:
        """Recompute a projection from effective entries in order."""
        state = initial
        for entry in self.effective_entries():
            state = apply(state, entry)
        return state

    def query(
        self,
        *,
        event_type: str | None = None,
        project_id: str | None = None,
        scope: str | None = None,
        actor: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EventLedgerEntry]:
        """Query events with optional filters. Returns entries in chronological order."""
        if self._store is not None:
            return self._store.query(
                event_type=event_type, project_id=project_id, scope=scope, actor=actor,
                limit=limit, offset=offset,
            )
        results = self._entries
        if event_type is not None:
            results = [e for e in results if e.event_type == event_type]
        if project_id is not None:
            results = [e for e in results if e.project_id == project_id]
        if scope is not None:
            results = [e for e in results if e.scope == scope]
        if actor is not None:
            results = [e for e in results if e.actor == actor]
        return results[offset : offset + limit]

    def count(
        self,
        *,
        event_type: str | None = None,
        project_id: str | None = None,
    ) -> int:
        """Count events matching optional filters."""
        if self._store is not None:
            return self._store.count(event_type=event_type, project_id=project_id)
        results = self._entries
        if event_type is not None:
            results = [e for e in results if e.event_type == event_type]
        if project_id is not None:
            results = [e for e in results if e.project_id == project_id]
        return len(results)

    def all_entries(self) -> list[EventLedgerEntry]:
        """Return all entries, including reversed ones (testing / audit)."""
        if self._store is not None:
            return self._store.query()
        return list(self._entries)

    def clear(self) -> None:
        """Clear the in-memory view (for testing only; the store is untouched)."""
        with self._lock:
            self._entries.clear()
            self._counter = 0
            self._idempotent.clear()
            self._reversals.clear()
