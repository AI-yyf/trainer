"""§13.21 Unified Event Ledger Service.

Append-only audit trail for core state changes. Most legacy event consumers keep
their short-lived in-memory view here. Durable agent-turn checkpoints are stored
by :class:`TrainerRepository` because they need restart-safe replay without
re-running providers or tools.
"""

from __future__ import annotations

from typing import Any

from .models import EventLedgerEntry, EventReversibility

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

# Agent recovery (1)
EVENT_AGENT_TURN_CHECKPOINTED = "agent_turn_checkpointed"

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
})


class EventLedgerService:
    """§13.21 Central event ledger — append-only, queryable in-memory store."""

    def __init__(self) -> None:
        self._entries: list[EventLedgerEntry] = []
        self._counter: int = 0

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
    ) -> EventLedgerEntry:
        """Record a new event in the ledger and return the entry."""
        self._counter += 1
        from .models import utc_now_iso

        entry = EventLedgerEntry(
            event_id=f"evt-{self._counter:06d}",
            event_type=event_type,
            occurred_at=utc_now_iso(),
            actor=actor,
            scope=scope,
            project_id=project_id,
            source_chain=list(source_chain or []),
            payload_ref=dict(payload_ref or {}),
            before_state_ref=dict(before_state_ref or {}),
            after_state_ref=dict(after_state_ref or {}),
            reversibility=reversibility,
            audit_note=audit_note,
        )
        self._entries.append(entry)
        return entry

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
        results = self._entries
        if event_type is not None:
            results = [e for e in results if e.event_type == event_type]
        if project_id is not None:
            results = [e for e in results if e.project_id == project_id]
        return len(results)

    def all_entries(self) -> list[EventLedgerEntry]:
        """Return all entries (for testing / debugging)."""
        return list(self._entries)

    def clear(self) -> None:
        """Clear all entries (for testing only)."""
        self._entries.clear()
        self._counter = 0
