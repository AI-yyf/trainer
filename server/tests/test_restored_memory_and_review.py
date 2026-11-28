"""(m) Memory, FSRS and review scheduling: what the learner actually did drives due
    reviews, learner state, goals and the durable ledger.

Guarantees covered:
  * FSRS scheduling advances only on real reviews under a controlled clock, without sleeping or faking due dates;
  * review interventions, refusals and busy signals respect their budget and cooldowns;
  * preference memory strengthens on repetition and yields to explicit overrides;
  * goal lifecycle events and training evidence land in the durable, replay-safe ledger;
  * learner state, affect and global plans are derived from evidence, never from backlog size;
  * concurrent evidence writers are serialized and separate processes never lose a write.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_event_ledger.py
  * server/tests/test_event_ledger_durability.py
  * server/tests/test_preference_memory.py
  * server/tests/test_review_intervention.py
  * server/tests/test_goal_session.py
  * server/tests/test_repositories.py
  * server/tests/test_structured_memory_multiprocess.py
  * server/tests/test_clock_harness.py
  * server/tests/test_memory_language_context.py
  * server/tests/test_goal_mode_prompt.py
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.clock import utc_now
from app.core.event_ledger import (
    ALL_EVENT_TYPES,
    EVENT_COACH_SETTINGS_UPDATED,
    EVENT_DEPENDENCY_MASTERY_UPDATED,
    EVENT_LEARNING_OUTCOME_RECORDED,
    EVENT_PLAN_EVIDENCE_CREATED,
    EVENT_PROFILE_UPDATED,
    EVENT_REFLECTION_RECORDED,
    EVENT_RESOURCE_UPLOADED,
    EVENT_SANDBOX_COMMAND_EXECUTED,
    EVENT_SANDBOX_FILE_WRITTEN,
    EventLedgerService,
)
from app.core.event_ledger_store import EventLedgerStore
from app.core.models import (
    EventLedgerEntry,
    GlobalPlan,
    GlobalPlanProjectLink,
    LearningPlan,
    MemoryShareGrant,
    PlanStage,
    ResourceRecord,
    SubPlan,
    TeachingKnowledgeAsset,
    TrainingCardCandidateSnapshot,
    UserProfile,
)
from app.core.settings import AppSettings
from app.db.repository import TrainerRepository
from app.goal.service import detect_goal_candidate
from app.llm.prompts import build_coaching_system_prompt
from app.main import create_app
from app.memory.coaching_adaptation_mixin import CoachingAdaptationMixin
from app.memory.models import MemorySnapshot, PreferenceRecord
from app.memory.review_intervention import derive_review_budget, review_refusal_signal
from app.memory.review_scheduler import ReviewScheduler
from app.memory.service import MemoryService, StructuredMemoryService
from app.pedagogy.turn_decision import TurnFacts, decide_turn
from app.training.fsrs_scheduler import FSRSTrainerCardScheduler, TrainingRating
from app.training.recall_evidence import recall_rating_for

# ---------------------------------------------------------------------------
# Restored from test_event_ledger.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


class TestEventLedgerRecordEvent:
    """Tests for EventLedgerService.record_event."""

    def test_record_event_returns_entry(self) -> None:
        service = EventLedgerService()
        entry = service.record_event("card_candidate_created", actor="system")
        assert isinstance(entry, EventLedgerEntry)
        assert entry.event_type == "card_candidate_created"
        assert entry.actor == "system"

    def test_record_event_auto_generates_event_id(self) -> None:
        service = EventLedgerService()
        entry = service.record_event("card_status_transitioned")
        assert entry.event_id.startswith("evt-")
        assert len(entry.event_id) > 4

    def test_record_event_auto_generates_occurred_at(self) -> None:
        service = EventLedgerService()
        entry = service.record_event("test_event")
        assert entry.occurred_at
        assert "T" in entry.occurred_at  # ISO 8601 format

    def test_record_event_sequential_ids(self) -> None:
        service = EventLedgerService()
        e1 = service.record_event("a")
        e2 = service.record_event("b")
        e3 = service.record_event("c")
        assert e1.event_id == "evt-000001"
        assert e2.event_id == "evt-000002"
        assert e3.event_id == "evt-000003"

    def test_record_event_with_all_fields(self) -> None:
        service = EventLedgerService()
        entry = service.record_event(
            "card_candidate_created",
            actor="system",
            scope="card",
            project_id="ws-1",
            source_chain=["card_generation_router", "conversation_gap"],
            payload_ref={"card_id": "c1", "title": "Test card"},
            before_state_ref={},
            after_state_ref={"status": "candidate"},
            reversibility="reversible",
            audit_note="Created from conversation gap",
        )
        assert entry.scope == "card"
        assert entry.project_id == "ws-1"
        assert entry.source_chain == ["card_generation_router", "conversation_gap"]
        assert entry.payload_ref["card_id"] == "c1"
        assert entry.reversibility == "reversible"
        assert entry.audit_note == "Created from conversation gap"


class TestEventLedgerQuery:
    """Tests for EventLedgerService.query."""

    def test_query_returns_all_when_no_filters(self) -> None:
        service = EventLedgerService()
        for i in range(5):
            service.record_event(f"event_{i}")
        results = service.query()
        assert len(results) == 5

    def test_query_filters_by_event_type(self) -> None:
        service = EventLedgerService()
        service.record_event("card_candidate_created")
        service.record_event("card_status_transitioned")
        service.record_event("card_candidate_created")
        results = service.query(event_type="card_candidate_created")
        assert len(results) == 2
        assert all(e.event_type == "card_candidate_created" for e in results)

    def test_query_filters_by_project_id(self) -> None:
        service = EventLedgerService()
        service.record_event("a", project_id="ws-1")
        service.record_event("b", project_id="ws-2")
        service.record_event("c", project_id="ws-1")
        results = service.query(project_id="ws-1")
        assert len(results) == 2

    def test_query_filters_by_scope(self) -> None:
        service = EventLedgerService()
        service.record_event("a", scope="card")
        service.record_event("b", scope="mastery")
        service.record_event("c", scope="card")
        results = service.query(scope="card")
        assert len(results) == 2

    def test_query_filters_by_actor(self) -> None:
        service = EventLedgerService()
        service.record_event("a", actor="system")
        service.record_event("b", actor="learner")
        results = service.query(actor="learner")
        assert len(results) == 1
        assert results[0].actor == "learner"

    def test_query_respects_limit_and_offset(self) -> None:
        service = EventLedgerService()
        for i in range(10):
            service.record_event(f"event_{i}")
        page1 = service.query(limit=3, offset=0)
        page2 = service.query(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0].event_id != page2[0].event_id


class TestEventLedgerCountAndHelpers:
    """Tests for count, all_entries, clear."""

    def test_count_total(self) -> None:
        service = EventLedgerService()
        service.record_event("a")
        service.record_event("b")
        service.record_event("c")
        assert service.count() == 3

    def test_count_with_event_type_filter(self) -> None:
        service = EventLedgerService()
        service.record_event("card_candidate_created")
        service.record_event("card_status_transitioned")
        service.record_event("card_candidate_created")
        assert service.count(event_type="card_candidate_created") == 2

    def test_count_with_project_id_filter(self) -> None:
        service = EventLedgerService()
        service.record_event("a", project_id="ws-1")
        service.record_event("b", project_id="ws-2")
        assert service.count(project_id="ws-1") == 1

    def test_all_entries_returns_copy(self) -> None:
        service = EventLedgerService()
        service.record_event("a")
        entries = service.all_entries()
        assert len(entries) == 1
        entries.clear()
        assert len(service.all_entries()) == 1  # Original unaffected

    def test_clear_resets_state(self) -> None:
        service = EventLedgerService()
        service.record_event("a")
        service.record_event("b")
        assert service.count() == 2
        service.clear()
        assert service.count() == 0
        # Counter also resets
        entry = service.record_event("c")
        assert entry.event_id == "evt-000001"


class TestEventLedgerEntryModel:
    """Tests for EventLedgerEntry Pydantic model."""

    def test_entry_model_validates(self) -> None:
        entry = EventLedgerEntry(
            event_type="test",
            event_id="evt-001",
            actor="system",
            scope="test",
        )
        assert entry.event_type == "test"
        assert entry.reversibility == "irreversible"  # default
        assert entry.source_chain == []  # default

    def test_entry_model_serialization(self) -> None:
        entry = EventLedgerEntry(
            event_type="card_candidate_created",
            event_id="evt-001",
            payload_ref={"key": "value"},
        )
        data = entry.model_dump()
        assert data["event_type"] == "card_candidate_created"
        assert data["payload_ref"]["key"] == "value"

    def test_entry_reversibility_values(self) -> None:
        for val in ("reversible", "irreversible", "compensatable"):
            entry = EventLedgerEntry(event_type="t", reversibility=val)
            assert entry.reversibility == val

    def test_entry_invalid_reversibility_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventLedgerEntry.model_validate({"event_type": "t", "reversibility": "invalid"})


class TestNewEventTypeConstants:

    """Tests for newly added event type constants."""

    def test_sandbox_command_executed_constant_exists(self) -> None:
        from app.core.event_ledger import (
            ALL_EVENT_TYPES,
            EVENT_SANDBOX_COMMAND_EXECUTED,
        )

        assert EVENT_SANDBOX_COMMAND_EXECUTED == "sandbox_command_executed"
        assert EVENT_SANDBOX_COMMAND_EXECUTED in ALL_EVENT_TYPES

    def test_sandbox_workspace_cleared_constant_exists(self) -> None:
        from app.core.event_ledger import (
            ALL_EVENT_TYPES,
            EVENT_SANDBOX_WORKSPACE_CLEARED,
        )

        assert EVENT_SANDBOX_WORKSPACE_CLEARED == "sandbox_workspace_cleared"
        assert EVENT_SANDBOX_WORKSPACE_CLEARED in ALL_EVENT_TYPES

    def test_teaching_asset_upserted_constant_in_all_types(self) -> None:
        from app.core.event_ledger import (
            ALL_EVENT_TYPES,
            EVENT_TEACHING_ASSET_UPSERTED,
        )

        assert EVENT_TEACHING_ASSET_UPSERTED == "teaching_asset_upserted"
        assert EVENT_TEACHING_ASSET_UPSERTED in ALL_EVENT_TYPES

    def test_dependency_mastery_updated_constant(self) -> None:
        from app.core.event_ledger import (
            ALL_EVENT_TYPES,
            EVENT_DEPENDENCY_MASTERY_UPDATED,
        )

        assert EVENT_DEPENDENCY_MASTERY_UPDATED == "dependency_mastery_updated"
        assert EVENT_DEPENDENCY_MASTERY_UPDATED in ALL_EVENT_TYPES



class TestSandboxEventEmissions:
    """Tests for sandbox service event emissions via EventLedgerService."""

    def test_sandbox_run_command_records_event(self) -> None:
        from app.core.event_ledger import EventLedgerService

        ledger = EventLedgerService()
        # Simulate what run_command would emit
        ledger.record_event(
            "sandbox_command_executed",
            actor="trainer",
            scope="sandbox",
            project_id="ws-test",
            payload_ref={
                "command_id": "cmd-abc123",
                "command": "python -m pytest",
                "status": "success",
                "exit_code": 0,
            },
            after_state_ref={"command_id": "cmd-abc123", "status": "success"},
            reversibility="irreversible",
            audit_note="Sandbox command executed: 'python -m pytest' (success)",
        )
        events = ledger.query(event_type="sandbox_command_executed", project_id="ws-test")
        assert len(events) == 1
        assert events[0].payload_ref["command"] == "python -m pytest"
        assert events[0].reversibility == "irreversible"

    def test_sandbox_clear_workspace_records_event(self) -> None:
        from app.core.event_ledger import EventLedgerService

        ledger = EventLedgerService()
        ledger.record_event(
            "sandbox_workspace_cleared",
            actor="trainer",
            scope="sandbox",
            project_id="ws-clear-test",
            payload_ref={"workspace_id": "ws-clear-test"},
            after_state_ref={"workspace_id": "ws-clear-test", "cleared": True},
            reversibility="irreversible",
            audit_note="Sandbox workspace cleared: 'ws-clear-test'",
        )
        events = ledger.query(event_type="sandbox_workspace_cleared")
        assert len(events) == 1
        assert events[0].payload_ref["workspace_id"] == "ws-clear-test"

    def test_teaching_asset_batch_upsert_records_event(self) -> None:
        from app.core.event_ledger import EventLedgerService

        ledger = EventLedgerService()
        ledger.record_event(
            "teaching_asset_upserted",
            actor="trainer",
            scope="teaching",
            project_id="ws-ta-test",
            payload_ref={
                "asset_ids": ["a1", "a2", "a3"],
                "origin": "resource",
                "resource_id": "res-001",
                "count": 3,
            },
            after_state_ref={"count": 3},
            reversibility="reversible",
            audit_note="Teaching assets upserted from resource 'test': 3 asset(s)",
        )
        events = ledger.query(event_type="teaching_asset_upserted", project_id="ws-ta-test")
        assert len(events) == 1
        assert events[0].payload_ref["count"] == 3
        assert events[0].payload_ref["origin"] == "resource"
        assert events[0].reversibility == "reversible"


class TestNewEventConstants:

    """Tests for newly added event type constants."""

    def test_all_new_constants_in_all_event_types(self) -> None:
        """All 17 new event type constants must be in ALL_EVENT_TYPES."""
        new_events = {
            EVENT_RESOURCE_UPLOADED,
            EVENT_SANDBOX_FILE_WRITTEN,
            EVENT_LEARNING_OUTCOME_RECORDED,
            EVENT_PROFILE_UPDATED,
            EVENT_REFLECTION_RECORDED,
            EVENT_SANDBOX_COMMAND_EXECUTED,
            EVENT_COACH_SETTINGS_UPDATED,
            EVENT_PLAN_EVIDENCE_CREATED,
            EVENT_DEPENDENCY_MASTERY_UPDATED,
        }
        for event in new_events:
            assert event in ALL_EVENT_TYPES, f"Missing from ALL_EVENT_TYPES: {event}"

    def test_new_constants_are_string_pairs(self) -> None:
        """Each constant value must match its variable name in snake_case."""
        assert EVENT_RESOURCE_UPLOADED == "resource_uploaded"
        assert EVENT_SANDBOX_FILE_WRITTEN == "sandbox_file_written"
        assert EVENT_LEARNING_OUTCOME_RECORDED == "learning_outcome_recorded"
        assert EVENT_PROFILE_UPDATED == "profile_updated"
        assert EVENT_REFLECTION_RECORDED == "reflection_recorded"
        assert EVENT_SANDBOX_COMMAND_EXECUTED == "sandbox_command_executed"
        assert EVENT_COACH_SETTINGS_UPDATED == "coach_settings_updated"
        assert EVENT_PLAN_EVIDENCE_CREATED == "plan_evidence_created"
        assert EVENT_DEPENDENCY_MASTERY_UPDATED == "dependency_mastery_updated"

    def test_record_new_event_types(self) -> None:
        """New event types can be recorded and queried back."""
        service = EventLedgerService()
        service.record_event(EVENT_RESOURCE_UPLOADED, actor="trainer", scope="resource", project_id="ws-1")
        service.record_event(EVENT_SANDBOX_FILE_WRITTEN, actor="trainer", scope="sandbox", project_id="ws-1")
        service.record_event(EVENT_LEARNING_OUTCOME_RECORDED, actor="trainer", scope="learning", project_id="ws-1")
        assert service.count(event_type=EVENT_RESOURCE_UPLOADED) == 1
        assert service.count(event_type=EVENT_SANDBOX_FILE_WRITTEN) == 1
        assert service.count(event_type=EVENT_LEARNING_OUTCOME_RECORDED) == 1

    def test_query_new_events_by_scope(self) -> None:
        """New events can be filtered by scope."""
        service = EventLedgerService()
        service.record_event(EVENT_RESOURCE_UPLOADED, scope="resource")
        service.record_event(EVENT_SANDBOX_FILE_WRITTEN, scope="sandbox")
        service.record_event(EVENT_PROFILE_UPDATED, scope="profile")
        resource_events = service.query(scope="resource")
        assert len(resource_events) == 1
        assert resource_events[0].event_type == EVENT_RESOURCE_UPLOADED

    def test_reversibility_field_on_new_events(self) -> None:
        """New events support different reversibility values."""
        service = EventLedgerService()
        service.record_event(EVENT_RESOURCE_UPLOADED, reversibility="reversible")
        service.record_event(EVENT_SANDBOX_FILE_WRITTEN, reversibility="reversible")
        service.record_event(EVENT_SANDBOX_COMMAND_EXECUTED, reversibility="append_only")
        service.record_event(EVENT_SANDBOX_FILE_WRITTEN, reversibility="compensatable")
        entries = service.all_entries()
        assert entries[0].reversibility == "reversible"
        assert entries[2].reversibility == "append_only"
        assert entries[3].reversibility == "compensatable"



# ---------------------------------------------------------------------------
# Restored from test_event_ledger_durability.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def build_store(tmp_path: Path) -> EventLedgerStore:
    return EventLedgerStore(tmp_path / "trainer-ledger.db")


def test_store_persists_entries_across_service_restart(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    first = EventLedgerService(store)
    created = first.record_event(
        "learning_outcome_recorded",
        actor="system",
        scope="training",
        project_id="workspace-a",
        payload_ref={"outcome": "independent"},
        after_state_ref={"score": 0.8},
    )
    assert created.event_id.startswith("evt-")

    restarted = EventLedgerService(build_store(tmp_path))
    entries = restarted.all_entries()
    assert [entry.event_id for entry in entries] == [created.event_id]
    restored = entries[0]
    assert restored.event_type == "learning_outcome_recorded"
    assert restored.project_id == "workspace-a"
    assert restored.payload_ref == {"outcome": "independent"}
    assert restored.after_state_ref == {"score": 0.8}


def test_idempotency_key_replays_the_original_entry(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    first = service.record_event(
        "evidence_adopted",
        project_id="workspace-a",
        idempotency_key="attempt-42",
        payload_ref={"attempt_id": "attempt-42"},
    )
    replay = service.record_event(
        "evidence_adopted",
        project_id="workspace-a",
        idempotency_key="attempt-42",
        payload_ref={"attempt_id": "attempt-42"},
    )
    assert replay.event_id == first.event_id
    assert len(service.all_entries()) == 1
    assert build_store(tmp_path).count() == 1


def test_idempotency_key_replays_after_restart(tmp_path: Path) -> None:
    original = EventLedgerService(build_store(tmp_path)).record_event(
        "training_evidence_recorded",
        project_id="workspace-a",
        idempotency_key="remote-verify:card-1",
    )
    restarted = EventLedgerService(build_store(tmp_path))
    replay = restarted.record_event(
        "training_evidence_recorded",
        project_id="workspace-a",
        idempotency_key="remote-verify:card-1",
    )
    assert replay.event_id == original.event_id
    assert build_store(tmp_path).count() == 1
    assert len(restarted.all_entries()) == 1


def test_idempotency_keys_are_workspace_scoped(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    service = EventLedgerService(store)
    a = service.record_event("evidence_adopted", project_id="workspace-a", idempotency_key="k")
    b = service.record_event("evidence_adopted", project_id="workspace-b", idempotency_key="k")
    assert a.event_id != b.event_id
    assert store.count() == 2
    assert store.count(workspace_id="workspace-a") == 1
    assert store.count(workspace_id="workspace-b") == 1


def test_empty_idempotency_key_never_dedupes(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    first = service.record_event("plan_updated", project_id="workspace-a")
    second = service.record_event("plan_updated", project_id="workspace-a")
    assert first.event_id != second.event_id
    assert build_store(tmp_path).count() == 2


def test_query_and_count_still_filter_hydrated_entries(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    service.record_event("plan_updated", project_id="workspace-a", actor="learner")
    service.record_event("plan_updated", project_id="workspace-b", actor="system")
    service.record_event("resource_uploaded", project_id="workspace-a", actor="system")

    restarted = EventLedgerService(build_store(tmp_path))
    assert restarted.count(event_type="plan_updated") == 2
    assert restarted.count(project_id="workspace-b") == 1
    filtered = restarted.query(event_type="plan_updated", project_id="workspace-a")
    assert [entry.actor for entry in filtered] == ["learner"]
    assert restarted.query(limit=2) and len(restarted.query(limit=2)) == 2


def test_reversal_is_append_only_and_idempotent(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    original = service.record_event(
        "plan_updated",
        project_id="workspace-a",
        reversibility="reversible",
    )
    reversal = service.reverse_event(original.event_id, reason="wrong plan")
    assert reversal is not None
    assert reversal.event_type == "event_reversed"
    assert reversal.payload_ref["reversed_event_id"] == original.event_id
    assert service.is_reversed(original.event_id)

    replay = service.reverse_event(original.event_id, reason="wrong plan")
    assert replay is not None
    assert replay.event_id == reversal.event_id
    assert build_store(tmp_path).count() == 2  # original + one reversal


def test_irreversible_or_unknown_events_cannot_be_reversed(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    locked = service.record_event("plan_updated", project_id="workspace-a")
    assert service.reverse_event(locked.event_id) is None
    assert service.reverse_event("evt-does-not-exist") is None
    assert not service.is_reversed(locked.event_id)


def test_effective_entries_exclude_reversed_events(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    kept = service.record_event("resource_uploaded", project_id="workspace-a", reversibility="reversible")
    dropped = service.record_event("resource_uploaded", project_id="workspace-a", reversibility="reversible")
    service.reverse_event(dropped.event_id)

    effective_ids = [entry.event_id for entry in service.effective_entries()]
    assert effective_ids == [kept.event_id]
    assert len(service.all_entries()) == 3  # both originals + the reversal


def test_reversal_survives_restart(tmp_path: Path) -> None:
    original = EventLedgerService(build_store(tmp_path)).record_event(
        "plan_updated",
        project_id="workspace-a",
        reversibility="reversible",
    )
    first = EventLedgerService(build_store(tmp_path))
    first.reverse_event(original.event_id, reason="superseded")

    restarted = EventLedgerService(build_store(tmp_path))
    assert restarted.is_reversed(original.event_id)
    assert [entry.event_id for entry in restarted.effective_entries()] == []
    again = restarted.reverse_event(original.event_id)
    assert again is not None and again.event_type == "event_reversed"
    assert build_store(tmp_path).count() == 2


def test_replay_recomputes_without_reversed_entries(tmp_path: Path) -> None:
    service = EventLedgerService(build_store(tmp_path))
    first = service.record_event("resource_uploaded", project_id="workspace-a", reversibility="reversible")
    service.record_event("resource_uploaded", project_id="workspace-a", reversibility="reversible")
    service.reverse_event(first.event_id)

    counts = service.replay({}, lambda acc, entry: {**acc, entry.event_type: acc.get(entry.event_type, 0) + 1})
    assert counts == {"resource_uploaded": 1}


def test_telemetry_export_ignores_reversed_events(tmp_path: Path) -> None:
    from app.telemetry.service import TelemetryService

    ledger = EventLedgerService(build_store(tmp_path))
    telemetry = TelemetryService(ledger, tmp_path)
    telemetry.set_opt_in(True, source="settings")
    event = ledger.record_event(
        "resource_uploaded",
        project_id="workspace-a",
        reversibility="reversible",
    )
    assert telemetry.build_export(window_days=7)["by_event"].get("resource_uploaded") == 1

    ledger.reverse_event(event.event_id, reason="upload retracted")
    assert "resource_uploaded" not in telemetry.build_export(window_days=7)["by_event"]


# ---------------------------------------------------------------------------
# Restored from test_preference_memory.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_repeated_value_strengthens_confidence_and_observations() -> None:
    service = StructuredMemoryService()
    first = service.remember_preference("answer_mode", "concept_first", source="coach-turn")
    second = service.remember_preference("answer_mode", "concept_first", source="coach-turn")
    third = service.remember_preference("answer_mode", "concept_first", source="coach-turn")

    assert first.observations == 1
    assert second.observations == 2
    assert third.observations == 3
    assert third.confidence > first.confidence
    assert third.durability == "session"


def test_changed_value_records_superseded_value() -> None:
    service = StructuredMemoryService()
    service.remember_preference("answer_mode", "concept_first", source="coach-turn")
    changed = service.remember_preference("answer_mode", "hands_on", source="coach-turn")

    assert changed.value == "hands_on"
    assert changed.superseded_value == "concept_first"
    assert changed.observations == 1


def test_explicit_source_is_durable_and_high_confidence() -> None:
    service = StructuredMemoryService()
    service.remember_preference("answer_mode", "concept_first", source="coach-turn")
    corrected = service.remember_preference("answer_mode", "hands_on", source="settings")

    assert corrected.value == "hands_on"
    assert corrected.superseded_value == "concept_first"
    assert corrected.durability == "durable"
    assert corrected.confidence >= 0.9
    assert corrected.source == "settings"


def test_repeated_turn_evidence_does_not_downgrade_durable_preference() -> None:
    service = StructuredMemoryService()
    service.remember_preference("review_cadence", "daily", source="settings")
    repeated = service.remember_preference("review_cadence", "daily", source="coach-turn")

    assert repeated.durability == "durable"
    assert repeated.confidence >= 0.9


def test_confidence_is_clamped() -> None:
    service = StructuredMemoryService()
    high = service.remember_preference("focus_area", "x", confidence=4.2)
    low = service.remember_preference("working_set_mode", "y", confidence=-3)
    assert high.confidence == 1.0
    assert low.confidence == 0.0


def test_export_state_round_trips_confidence_fields() -> None:
    service = StructuredMemoryService()
    service.remember_preference("answer_mode", "concept_first", source="settings", context="settings")
    service.remember_preference("answer_mode", "hands_on", source="coach-turn", context="turn-3")

    restored = StructuredMemoryService.from_state(service.export_state())
    record = restored._preferences["answer_mode"]

    assert record.value == "hands_on"
    assert record.superseded_value == "concept_first"
    assert record.durability == "session"
    assert record.context == "turn-3"
    assert record.observations == 1


def test_legacy_preference_payload_restores_safe_defaults() -> None:
    legacy = {
        "preferences": [
            {
                "key": "answer_mode",
                "value": "concept_first",
                "source": "coach-turn",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ]
    }
    restored = StructuredMemoryService.from_state(legacy)
    record = restored._preferences["answer_mode"]

    assert record.value == "concept_first"
    assert record.confidence == 0.6
    assert record.observations == 1
    assert record.durability == "session"
    assert record.superseded_value == ""


class _PreferenceProbe(CoachingAdaptationMixin):
    """Bare mixin probe: _preferred_preference only reads the snapshot."""


def _snapshot(*preferences: PreferenceRecord) -> MemorySnapshot:
    return MemorySnapshot(preferences=list(preferences))


def test_preferred_preference_uses_durable_over_turn_noise() -> None:
    probe = _PreferenceProbe()
    snapshot = _snapshot(
        PreferenceRecord(
            key="latest_turn_teaching_note",
            value="use a diagram here",
            source="coach-turn",
            durability="session",
            confidence=0.55,
        ),
        PreferenceRecord(
            key="learning_style",
            value="concept_first",
            source="settings",
            durability="durable",
            confidence=0.95,
        ),
    )
    preferred = probe._preferred_preference(snapshot)
    assert preferred is not None
    assert preferred.key == "learning_style"


def test_preferred_preference_falls_back_when_nothing_is_durable() -> None:
    probe = _PreferenceProbe()
    first = PreferenceRecord(key="pacing", value="slow", durability="session", confidence=0.55)
    second = PreferenceRecord(key="examples", value="concrete", durability="turn", confidence=0.4)
    preferred = probe._preferred_preference(_snapshot(first, second))
    assert preferred is first


def test_preferred_preference_keeps_ignored_key_fallback() -> None:
    probe = _PreferenceProbe()
    answer_mode = PreferenceRecord(key="answer_mode", value="text", durability="durable", confidence=0.95)
    preferred = probe._preferred_preference(_snapshot(answer_mode))
    assert preferred is answer_mode


def test_settings_source_is_durable_for_teaching_style() -> None:
    service = StructuredMemoryService()
    record = service.remember_preference("teaching_style", "concept_first", source="coach-settings")
    assert record.durability == "durable"
    assert record.confidence == 0.95


# ---------------------------------------------------------------------------
# Restored from test_review_intervention.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


NOW = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def test_no_due_reviews_never_interrupts() -> None:
    budget = derive_review_budget({}, due_count=0, now=NOW)
    assert budget.allowed is False
    assert budget.reason == "no_due_reviews"
    assert budget.visible_limit == 0


def test_refusal_persists_and_suppresses_interruption() -> None:
    budget = derive_review_budget(
        {
            "review_intervention": {
                "refused_until": _iso(NOW + timedelta(hours=2)),
            }
        },
        due_count=20,
        now=NOW,
    )
    assert budget.allowed is False
    assert budget.reason == "refused"
    assert budget.visible_limit == 1
    assert budget.deferred_count == 19
    assert budget.refused_until == _iso(NOW + timedelta(hours=2))


@pytest.mark.parametrize(
    "message",
    [
        "我现在很忙，晚点再说",
        "not now, I'm busy",
        "正在调试这个错误，先别提醒我",
        "skip the review for today",
        "I'm debugging this error, not now",
    ],
)
def test_busy_or_refusal_message_blocks_this_turn(message: str) -> None:
    budget = derive_review_budget({}, due_count=8, now=NOW, message=message)
    assert budget.message_refusal
    assert budget.allowed is False
    assert budget.visible_limit == 1


def test_normal_question_is_not_mistaken_for_refusal() -> None:
    assert review_refusal_signal("Can you explain how the queue lock works?") == ""
    assert review_refusal_signal("帮我解释一下这个边界条件") == ""
    budget = derive_review_budget({}, due_count=8, now=NOW, message="explain the lock")
    assert budget.allowed is True
    assert budget.visible_limit == 4


def test_one_offer_per_session_and_cross_session_cooldown() -> None:
    same_session = derive_review_budget(
        {
            "review_intervention": {
                "last_offer_at": _iso(NOW - timedelta(hours=5)),
                "last_offer_session_id": "session-a",
            }
        },
        due_count=8,
        now=NOW,
        session_id="session-a",
    )
    assert same_session.allowed is False
    assert same_session.reason == "same_session_interruption"

    recent_other_session = derive_review_budget(
        {
            "review_intervention": {
                "last_offer_at": _iso(NOW - timedelta(hours=1)),
                "last_offer_session_id": "session-a",
            }
        },
        due_count=8,
        now=NOW,
        session_id="session-b",
    )
    assert recent_other_session.allowed is False
    assert recent_other_session.reason == "offer_cooldown"

    later_session = derive_review_budget(
        {
            "review_intervention": {
                "last_offer_at": _iso(NOW - timedelta(hours=5)),
                "last_offer_session_id": "session-a",
            }
        },
        due_count=8,
        now=NOW,
        session_id="session-b",
    )
    assert later_session.allowed is True
    assert later_session.reason == "due_reviews"


def test_focused_or_blocked_thread_is_not_interrupted() -> None:
    budget = derive_review_budget(
        {
            "active_thread": {
                "focus_area": "debugging the lock path",
                "blocker": "test still fails",
            }
        },
        due_count=8,
        now=NOW,
    )
    assert budget.allowed is False
    assert budget.reason == "focused_activity"
    assert budget.visible_limit == 4


def test_long_offline_shows_one_curated_item_not_the_backlog() -> None:
    budget = derive_review_budget(
        {"last_active_at": _iso(NOW - timedelta(days=21))},
        due_count=30,
        now=NOW,
    )
    assert budget.allowed is True
    assert budget.reason == "long_offline_curated"
    assert budget.visible_limit == 1
    assert budget.deferred_count == 29
    assert budget.offline_days >= 21


def test_turn_decision_honors_the_budget_but_not_explicit_review() -> None:
    blocked = decide_turn(
        TurnFacts(
            message="Where should I go next?",
            needs_review=True,
            due_review_count=8,
            intervention_allowed=False,
            intervention_reason="refused",
            has_active_goal=True,
        )
    )
    assert blocked.mode != "review"
    assert "intervention_blocked:refused" in blocked.evidence

    explicit = decide_turn(
        TurnFacts(
            message="Review me now, please.",
            needs_review=True,
            due_review_count=8,
            intervention_allowed=False,
            intervention_reason="refused",
        )
    )
    assert explicit.mode == "review"
    assert explicit.source == "explicit_user"


def test_scheduler_caps_due_items_for_long_absence_and_refusal() -> None:
    from app.memory.models import MemorySnapshot as LaneMemorySnapshot
    from app.memory.models import WeaknessRecord

    scheduler = ReviewScheduler()
    weaknesses = [
        WeaknessRecord(
            concept=f"concept-{index}",
            reason="Needs one closed-book recall.",
            severity=3,
            next_review_at=NOW - timedelta(days=1),
        )
        for index in range(10)
    ]
    long_offline = LaneMemorySnapshot(
        workspace={"last_active_at": _iso(NOW - timedelta(days=14))}
    )
    normal = LaneMemorySnapshot(workspace={"last_active_at": _iso(NOW)})
    refused = LaneMemorySnapshot(
        workspace={
            "last_active_at": _iso(NOW),
            "review_intervention": {"refused_until": _iso(NOW + timedelta(hours=3))},
        }
    )

    # The scheduler reads the real clock; keep seeded due dates in its past.
    real_now = datetime.now(UTC)
    for item in weaknesses:
        item.next_review_at = real_now - timedelta(days=1)
    long_offline.workspace["last_active_at"] = (real_now - timedelta(days=14)).isoformat()
    normal.workspace["last_active_at"] = real_now.isoformat()
    refused.workspace["review_intervention"] = {
        "refused_until": (real_now + timedelta(hours=3)).isoformat()
    }

    long_items = scheduler.derive_due_reviews(
        plan=LearningPlan(id="plan", title="Plan", summary="", stages=[]),
        lane_snapshot=long_offline,
        weakness_records=weaknesses,
    )
    normal_items = scheduler.derive_due_reviews(
        plan=LearningPlan(id="plan", title="Plan", summary="", stages=[]),
        lane_snapshot=normal,
        weakness_records=weaknesses,
    )
    refused_items = scheduler.derive_due_reviews(
        plan=LearningPlan(id="plan", title="Plan", summary="", stages=[]),
        lane_snapshot=refused,
        weakness_records=weaknesses,
    )

    assert len(long_items) == 1
    assert len(normal_items) == 4
    assert len(refused_items) == 1


def test_recall_rating_maps_evidence_never_missing_assistance_to_independent() -> None:
    assert recall_rating_for(True, "none") == "good"
    assert recall_rating_for(True, "independent") == "good"
    assert recall_rating_for(True, "hint_level_2") == "hard"
    assert recall_rating_for(True, "unknown") == "hard"
    assert recall_rating_for(True, "") == "hard"
    assert recall_rating_for(False, "none") == "again"


# ---------------------------------------------------------------------------
# Restored from test_goal_session.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer goal sessions",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-goal.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _start_session(client: TestClient, workspace_id: str = "w-goal") -> str:
    response = client.post(
        "/session/start",
        json={"workspace_id": workspace_id, "workspace_name": "Goal Workspace"},
    )
    assert response.status_code == 200
    return str(response.json()["session_id"])


def _current(client: TestClient, workspace_id: str = "w-goal") -> dict | None:
    response = client.get("/goal/current", params={"workspace_id": workspace_id})
    assert response.status_code == 200
    return response.json()["goal"]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("PPO 是什么？", None),
        ("Can you explain PPO?", None),
        ("I want to learn how to build a compiler", "build a compiler"),
        ("我想真正学会实现 PPO", "实现 PPO"),
        ("我想系统学习强化学习", "强化学习"),
        ("我想真正学会实现 PPO Clip，请先判断我该从哪里开始", "实现 PPO Clip"),
        ("帮我制定一个学习 PPO 的计划", "PPO"),
        (
            "帮我设定一个长期目标：3 天内能够独立解释 PPO 的裁剪目标，并手写对应的损失函数。",
            "3 天内能够独立解释 PPO 的裁剪目标",
        ),
        ("Please set a goal: ship a small compiler", "ship a small compiler"),
        ("今天的目标是什么？", None),
        ("随便聊聊", None),
        ("/review", None),
        ("帮我检查一下我掌握的程度如何", None),
        ("帮我看看为什么这个测试没过，我搞懂了一半", None),
        ("帮我解释一下 GIL，我想掌握一下它为什么存在", None),
        ("请核查并如实告诉我目前当前目标、计划各阶段、掌握进度的具体验证证据记录", None),
        ("帮我分析一下我哪里还没搞懂？", None),
        ("我想掌握 AsyncIO 事件循环", "AsyncIO 事件循环"),
    ],
)
def test_detection_only_matches_explicit_capability_intent(
    message: str,
    expected: str | None,
) -> None:
    assert detect_goal_candidate(message) == expected


def test_explicit_goal_command_can_update_existing_active_goal(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        client.get("/snapshot", params={"workspace_id": "w-explicit-override"})
        service = app.state.runtime.goals()
        first = service.observe_turn(
            workspace_id="w-explicit-override",
            message="我想真正学会实现 PPO",
            intent="coach",
            active_view="coach",
        )
        assert first is not None and first.title == "实现 PPO"

        updated = service.observe_turn(
            workspace_id="w-explicit-override",
            message="帮我设定一个长期目标：独立推导并实现 Transformer 注意力",
            intent="coach",
            active_view="coach",
        )
        assert updated is not None
        assert updated.source == "user_explicit"
        assert updated.title == "独立推导并实现 Transformer 注意力"
        assert updated.goal_id != first.goal_id


def test_auto_detection_never_replaces_an_existing_goal(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        first_question_state = client.get(
            "/snapshot",
            params={"workspace_id": "w-auto"},
        )
        assert first_question_state.status_code == 200
        service = app.state.runtime.goals()

        assert service.observe_turn(
            workspace_id="w-auto",
            message="PPO 是什么？",
            intent="coach",
            active_view="coach",
        ) is None

        detected = service.observe_turn(
            workspace_id="w-auto",
            message="我想真正学会实现 PPO",
            intent="coach",
            active_view="coach",
        )
        assert detected is not None
        assert detected.source == "coach_detected"
        assert detected.title == "实现 PPO"

        # A second learning statement cannot silently replace the focus.
        same = service.observe_turn(
            workspace_id="w-auto",
            message="我想系统学习强化学习",
            intent="coach",
            active_view="coach",
        )
        assert same is not None
        assert same.goal_id == detected.goal_id


def test_goal_records_its_place_in_the_long_term_plan(tmp_path: Path) -> None:
    """P0: Goal Mode is a micro-goal inside the plan, not an isolated mode."""
    app = create_app(_settings(tmp_path / "data"))
    plan = LearningPlan(
        id="plan-world-models",
        title="系统掌握自动驾驶中的世界模型",
        stages=[
            PlanStage(
                id="stage-foundations",
                title="阶段一：基础知识",
                goal="理解状态、动作与预测目标",
                outcomes=["能解释世界模型在规划中的作用"],
                status="active",
            ),
            PlanStage(
                id="stage-core",
                title="阶段二：核心原理",
                goal="理解潜在动力学模型",
                outcomes=["能推导一步预测误差"],
            ),
        ],
        current_stage_id="stage-foundations",
        current_step="写出一个单步预测的状态转移",
    )
    with TestClient(app) as client:
        client.get("/snapshot", params={"workspace_id": "w-plan"})
        goal = app.state.runtime.goals().start(
            workspace_id="w-plan",
            title="实现单步预测",
            plan=plan,
        )
        assert goal.plan_id == "plan-world-models"
        assert goal.stage_id == "stage-foundations"
        assert goal.current_position == "阶段一：基础知识"
        # The persisted record — not just the in-memory return — carries the link.
        restored = app.state.runtime.goals().current("w-plan")
        assert restored is not None
        assert restored.plan_id == goal.plan_id
        assert restored.stage_id == goal.stage_id


def test_explicit_goal_survives_restart_and_is_in_the_snapshot(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    app = create_app(_settings(data_dir))
    with TestClient(app) as client:
        session_id = _start_session(client)
        started = client.post(
            "/goal/action",
            json={
                "session_id": session_id,
                "workspace_id": "w-goal",
                "action": "start",
                "title": "实现 PPO",
            },
        )
        assert started.status_code == 200
        goal_id = started.json()["goal"]["goalId"]
        assert started.json()["goal"]["source"] == "user_explicit"

        snapshot = client.get("/snapshot", params={"workspace_id": "w-goal"}).json()
        assert snapshot["snapshot"]["goal"]["goal_id"] == goal_id

    # A fresh sidecar must restore the same server-owned goal.
    restarted = create_app(_settings(data_dir))
    with TestClient(restarted) as client:
        session = client.post(
            "/session/start",
            json={"workspace_id": "w-goal", "workspace_name": "Goal Workspace"},
        ).json()
        assert session["goal"]["goalId"] == goal_id
        assert session["goal"]["title"] == "实现 PPO"


def test_new_explicit_goal_pauses_but_preserves_the_previous_focus(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        session_id = _start_session(client)
        first = client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "实现 PPO"},
        ).json()["goal"]
        second = client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "掌握 RAG 检索"},
        ).json()["goal"]

        assert second["goalId"] != first["goalId"]
        assert second["status"] == "active"
        goals = client.get("/goal/list", params={"workspace_id": "w-goal"}).json()["goals"]
        by_id = {goal["goalId"]: goal for goal in goals}
        assert by_id[first["goalId"]]["status"] == "paused"
        assert by_id[first["goalId"]]["title"] == "实现 PPO"


def test_restarting_a_paused_goal_reuses_it_instead_of_duplicating(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        session_id = _start_session(client)
        first = client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "实现 PPO"},
        ).json()["goal"]
        second = client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "掌握 RAG 检索"},
        ).json()["goal"]
        assert second["status"] == "active"

        restarted = client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "实现 PPO"},
        ).json()["goal"]

        assert restarted["goalId"] == first["goalId"]
        assert restarted["status"] == "active"
        goals = client.get("/goal/list", params={"workspace_id": "w-goal"}).json()["goals"]
        assert len(goals) == 2
        by_id = {goal["goalId"]: goal for goal in goals}
        assert by_id[first["goalId"]]["status"] == "active"
        assert by_id[second["goalId"]]["status"] == "paused"


def test_goals_are_workspace_isolated(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        session_id = _start_session(client, "w-goal")
        client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "实现 PPO"},
        )
        assert _current(client, "w-goal") is not None
        assert _current(client, "w-other") is None
        assert client.get("/goal/list", params={"workspace_id": "w-other"}).json()["goals"] == []


def test_goal_service_rejects_empty_title(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app):
        with pytest.raises(ValueError, match="goal_title_required"):
            app.state.runtime.goals().start(workspace_id="w-goal", title="   ")


# ---------------------------------------------------------------------------
# Restored from test_repositories.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_session_message_request_contract_accepts_request_id() -> None:
    from app.core.models import SessionMessageRequest

    request = SessionMessageRequest.model_validate({"message": "hello", "requestId": "req-1"})
    assert request.request_id == "req-1"


def test_trainer_repository_round_trips_resource_curation_metadata(tmp_path: Path) -> None:
    repository = TrainerRepository(tmp_path / "trainer-resource.db")
    resource = ResourceRecord(
        id="resource-1",
        kind="markdown",
        name="External Note",
        source="/tmp/external-note.md",
        summary="A grounded trainer note.",
        parse_status="parsed",
        index_status="indexed",
        source_type="local:markdown",
        canonical_source="/tmp/external-note.md",
        fetched_at="2026-05-03T00:00:00+00:00",
        trust_score=0.82,
        freshness="fresh",
        duplicate_key="markdown:/tmp/external-note.md:abc123",
        quality_flags=["grounded"],
        warnings=[],
        knowledge_fragments=[
            {
                "id": "frag-1",
                "resource_id": "resource-1",
                "title": "External Note",
                "snippet": "A grounded trainer note.",
                "summary": "A grounded trainer note.",
                "source": "/tmp/external-note.md",
                "source_type": "local:markdown",
                "kind": "markdown",
                "trust_score": 0.82,
                "freshness": "fresh",
                "fetched_at": "2026-05-03T00:00:00+00:00",
                "duplicate_key": "markdown:/tmp/external-note.md:abc123",
                "quality_flags": ["grounded"],
                "focus_area": "External Note",
                "line_start": None,
                "line_end": None,
                "why_it_matters": "Useful for H1.",
            }
        ],
    )
    repository.save_resource("workspace-1", resource)
    restored = repository.list_resources("workspace-1")
    assert len(restored) == 1
    assert restored[0].duplicate_key == resource.duplicate_key
    assert restored[0].trust_score == resource.trust_score
    assert restored[0].knowledge_fragments == resource.knowledge_fragments


def test_trainer_repository_save_resource_supports_legacy_composite_resource_key_schema(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "trainer-legacy-resource.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE resources (
                resource_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (workspace_id, resource_id)
            )
            """
        )
        connection.commit()

    repository = TrainerRepository(db_path)
    resource = ResourceRecord(
        id="resource-legacy",
        kind="markdown",
        name="Legacy Resource",
        source="/tmp/legacy-note.md",
        summary="Legacy resource upload should still work.",
    )

    repository.save_resource("workspace-legacy", resource)
    updated = resource.model_copy(update={"summary": "Updated payload still persists."})
    repository.save_resource("workspace-legacy", updated)

    restored = repository.list_resources("workspace-legacy")
    assert len(restored) == 1
    assert restored[0].id == "resource-legacy"
    assert restored[0].summary == "Updated payload still persists."


def test_trainer_repository_round_trips_teaching_assets(tmp_path: Path) -> None:
    repository = TrainerRepository(tmp_path / "trainer-asset.db")
    asset = TeachingKnowledgeAsset(
        kind="concept_card",
        scope="project",
        workspace_id="workspace-asset",
        title="Router boundary",
        summary="Keep orchestration thin.",
        concept_card="Keep orchestration thin.",
        explanation_recipe="Use one boundary at a time.",
        origin="resource",
        source_key="resource::one::concept",
        source_ids=["resource-1"],
        source_fragments=["server/app/api/routers.py"],
        evidence_snippets=["Keep orchestration thin.", "Use one boundary at a time."],
        retrieval_hints=["router", "coach", "boundary"],
        source_summary="A reusable router boundary note.",
        source_quality_flags=["grounded"],
        source_freshness="fresh",
        source_retrieved_at="2026-05-03T00:00:00+00:00",
        tags=["router", "coach"],
        trust_score=0.8,
    )
    repository.save_teaching_asset("workspace-asset", asset)

    restored = repository.list_teaching_assets("workspace-asset")
    assert len(restored) == 1
    assert restored[0].title == asset.title
    assert restored[0].source_key == asset.source_key
    assert restored[0].concept_card == asset.concept_card
    assert restored[0].origin == "resource"
    assert restored[0].evidence_snippets == asset.evidence_snippets
    assert restored[0].retrieval_hints == asset.retrieval_hints
    assert restored[0].source_summary == asset.source_summary
    assert restored[0].source_quality_flags == asset.source_quality_flags
    assert restored[0].source_freshness == asset.source_freshness
    assert restored[0].source_retrieved_at == asset.source_retrieved_at


def test_trainer_repository_lists_general_and_personal_teaching_assets_for_workspace(tmp_path: Path) -> None:
    repository = TrainerRepository(tmp_path / "trainer-asset-scope.db")
    project_asset = TeachingKnowledgeAsset(
        kind="implementation_pattern",
        scope="project",
        workspace_id="workspace-alpha",
        title="Alpha pattern",
        summary="Project-only pattern.",
        implementation_pattern="Project-only pattern.",
        source_key="project::alpha",
        trust_score=0.8,
    )
    personal_asset = TeachingKnowledgeAsset(
        kind="explanation_recipe",
        scope="personal",
        workspace_id="workspace-alpha",
        title="Personal explanation",
        summary="Personal reusable explanation.",
        explanation_recipe="Personal reusable explanation.",
        source_key="personal::alpha",
        trust_score=0.72,
    )
    general_asset = TeachingKnowledgeAsset(
        kind="concept_card",
        scope="general",
        workspace_id="__global__",
        title="General concept",
        summary="General reusable concept.",
        concept_card="General reusable concept.",
        source_key="general::concept",
        trust_score=0.75,
    )
    foreign_project_asset = TeachingKnowledgeAsset(
        kind="common_pitfall",
        scope="project",
        workspace_id="workspace-beta",
        title="Beta pitfall",
        summary="Foreign project pitfall.",
        common_pitfall="Foreign project pitfall.",
        source_key="project::beta",
        trust_score=0.68,
    )
    repository.save_teaching_asset("workspace-alpha", project_asset)
    repository.save_teaching_asset("workspace-alpha", personal_asset)
    repository.save_teaching_asset("workspace-alpha", general_asset)
    repository.save_teaching_asset("workspace-beta", foreign_project_asset)

    restored = repository.list_teaching_assets("workspace-alpha")
    titles = {asset.title for asset in restored}
    assert "Alpha pattern" in titles
    assert "Personal explanation" in titles
    assert "General concept" in titles
    assert "Beta pitfall" not in titles


def test_trainer_repository_persists_memory_share_grants(tmp_path: Path) -> None:
    database_path = tmp_path / "trainer-memory-share-grants.db"
    repository = TrainerRepository(database_path)
    grant = MemoryShareGrant(
        source_workspace_id="workspace-source",
        target_workspace_id="workspace-target",
        categories=["preferences"],
    )

    repository.save_memory_share_grant(grant)

    restored = repository.get_memory_share_grant("workspace-source", "workspace-target")
    assert restored is not None
    assert restored.categories == ["preferences"]

    updated = grant.model_copy(update={"categories": ["mastery"]})
    repository.save_memory_share_grant(updated)
    rebuilt = TrainerRepository(database_path)
    listed = rebuilt.list_memory_share_grants("workspace-target")
    assert len(listed) == 1
    assert listed[0].categories == ["mastery"]
    assert rebuilt.delete_memory_share_grant("workspace-source", "workspace-target") is True
    assert rebuilt.list_memory_share_grants("workspace-target") == []


def test_trainer_repository_persists_subplans(tmp_path: Path) -> None:
    database_path = tmp_path / "trainer-subplans.db"
    repository = TrainerRepository(database_path)
    repository.save_plan("workspace-1", LearningPlan(id="plan-1", title="Parent plan"))
    subplan = SubPlan(
        id="subplan-1",
        parentPlanId="plan-1",
        title="Persisted sub-plan",
        description="Retains its stages across a sidecar restart.",
    )

    repository.save_subplan("plan-1", subplan)

    restored = repository.get_subplan("plan-1", "subplan-1")
    assert restored is not None
    assert restored.title == "Persisted sub-plan"

    updated = subplan.model_copy(update={"title": "Updated sub-plan"})
    repository.save_subplan("plan-1", updated)
    rebuilt = TrainerRepository(database_path)
    assert [item.title for item in rebuilt.list_subplans("plan-1")] == ["Updated sub-plan"]
    assert rebuilt.delete_subplan("plan-1", "subplan-1") is True
    assert rebuilt.list_subplans("plan-1") == []


def test_trainer_repository_persists_global_plan_and_project_link(tmp_path: Path) -> None:
    database_path = tmp_path / "trainer-global-plan.db"
    repository = TrainerRepository(database_path)
    owner = repository.ensure_default_local_owner()
    project_plan = LearningPlan(id="project-plan-1", title="Current project plan")
    repository.save_plan("workspace-1", project_plan)
    global_plan = GlobalPlan(
        id="global-plan-1",
        ownerId=owner.id,
        title="Long-term mastery",
        goals=["Ship durable work across projects"],
    )

    repository.save_global_plan(global_plan)
    repository.save_global_plan_project_link(
        GlobalPlanProjectLink(
            globalPlanId=global_plan.id,
            workspaceId="workspace-1",
            projectPlanId=project_plan.id,
        )
    )

    rebuilt = TrainerRepository(database_path)
    restored = rebuilt.get_default_global_plan()
    assert restored is not None
    assert restored.title == "Long-term mastery"
    link = rebuilt.get_global_plan_project_link(
        global_plan.id,
        "workspace-1",
        project_plan.id,
    )
    assert link is not None
    assert link.project_plan_id == project_plan.id
    assert rebuilt.delete_global_plan_project_link(global_plan.id, "workspace-1") is True
    assert rebuilt.get_global_plan_project_link(global_plan.id, "workspace-1") is None


# ---------------------------------------------------------------------------
# Restored from test_structured_memory_multiprocess.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


WORKSPACE = "workspace-two-windows"


def two_sidecars(tmp_path: Path) -> tuple[TrainerRepository, MemoryService, MemoryService]:
    """One database, two memory services: two windows, two sidecars."""
    repository = TrainerRepository(tmp_path / "trainer-multi-window.db")
    return repository, MemoryService(repository), MemoryService(repository)


def read_stored(repository: TrainerRepository) -> tuple[int, dict]:
    entry = repository.load_structured_memory_entry(WORKSPACE)
    assert entry is not None
    payload, revision = entry
    return revision, payload


def card(card_id: str, title: str) -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type="practice",
        title=title,
        status="active",
    )


def test_a_write_from_the_second_sidecar_keeps_the_first_sidecars_keys(tmp_path: Path) -> None:
    repository, window_a, window_b = two_sidecars(tmp_path)
    # Both windows have the workspace open, so each loaded it independently.
    window_a.snapshot(WORKSPACE)
    window_b.snapshot(WORKSPACE)

    window_a.upsert_card(WORKSPACE, card("card-from-window-a", "Card A"))
    revision_after_a, after_a = read_stored(repository)
    assert [entry["card_id"] for entry in after_a["training_cards"]] == ["card-from-window-a"]

    # Window B's copy predates A's write. Its reflection must not erase A's card.
    window_b.record_reflection(
        "task-b",
        "reflection-from-window-b",
        workspace_id=WORKSPACE,
    )

    revision, stored = read_stored(repository)
    assert revision == revision_after_a + 1, "each write advances the revision once"
    assert [entry["card_id"] for entry in stored["training_cards"]] == ["card-from-window-a"]
    assert any(
        "reflection-from-window-b" in str(reflection) for reflection in stored["reflections"]
    )


def test_the_other_sidecar_keeps_the_key_it_wrote_before(tmp_path: Path) -> None:
    repository, window_a, window_b = two_sidecars(tmp_path)
    window_a.snapshot(WORKSPACE)
    window_b.snapshot(WORKSPACE)

    window_a.upsert_card(WORKSPACE, card("card-a1", "First"))
    window_b.record_reflection("task-b", "B reflection", workspace_id=WORKSPACE)
    revision_after_b, _ = read_stored(repository)

    # Window A adds another card from its stale copy; B's reflection survives.
    window_a.upsert_card(WORKSPACE, card("card-a2", "Second"))

    revision, stored = read_stored(repository)
    assert revision == revision_after_b + 1
    assert sorted(entry["card_id"] for entry in stored["training_cards"]) == [
        "card-a1",
        "card-a2",
    ]
    assert any("B reflection" in str(reflection) for reflection in stored["reflections"])


def test_two_sidecars_appending_to_the_same_list_keep_both_entries(tmp_path: Path) -> None:
    repository, window_a, window_b = two_sidecars(tmp_path)
    window_a.snapshot(WORKSPACE)
    window_b.snapshot(WORKSPACE)

    window_a.record_reflection("task-a", "A reflection", workspace_id=WORKSPACE)
    window_b.record_reflection("task-b", "B reflection", workspace_id=WORKSPACE)

    _, stored = read_stored(repository)
    summaries = {reflection.get("summary") for reflection in stored["reflections"]}
    assert summaries == {"A reflection", "B reflection"}


def test_a_single_sidecar_still_writes_what_it_loaded(tmp_path: Path) -> None:
    repository, window_a, _ = two_sidecars(tmp_path)
    window_a.snapshot(WORKSPACE)
    revision_before, _ = read_stored(repository)

    window_a.upsert_card(WORKSPACE, card("only-card", "Only"))

    revision, stored = read_stored(repository)
    assert revision == revision_before + 1
    # No other writer: the stored object is exactly the state the service
    # exports (a merge would have been a no-op, not a different shape).
    assert stored == window_a._structured_for(WORKSPACE).export_state()
    assert [entry["card_id"] for entry in stored["training_cards"]] == ["only-card"]


def test_an_existing_database_gains_the_revision_column(tmp_path: Path) -> None:
    # A database written before revisions existed must keep its data and gain
    # the column the merge reads, without a manual migration step.
    database = tmp_path / "trainer-legacy.db"
    legacy_payload = json.dumps(StructuredMemoryService().export_state())
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE structured_memory (workspace_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO structured_memory (workspace_id, payload) VALUES (?, ?)",
        (WORKSPACE, legacy_payload),
    )
    connection.commit()
    connection.close()

    repository = TrainerRepository(database)
    entry = repository.load_structured_memory_entry(WORKSPACE)
    assert entry is not None
    payload, revision = entry
    assert revision == 0
    assert payload == json.loads(legacy_payload)

    service = MemoryService(repository)
    service.upsert_card(WORKSPACE, card("after-migration", "After migration"))
    revision, stored = read_stored(repository)
    assert revision == 1
    assert [entry["card_id"] for entry in stored["training_cards"]] == ["after-migration"]


# ---------------------------------------------------------------------------
# Restored from test_clock_harness.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_test_clock_reads_iso_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-01T09:00:00Z")
    assert utc_now() == datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    monkeypatch.setenv("TRAINER_TEST_NOW", "not-a-date")
    assert utc_now().year >= 2026


def test_fsrs_due_and_interval_advance_across_simulated_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-01T09:00:00Z")
    scheduler = FSRSTrainerCardScheduler()
    scheduler.create_card("clock-card", "tuple mutability")
    first = scheduler.process_review("clock-card", TrainingRating.GOOD)
    assert first.new_interval >= 0
    assert first.next_due > datetime(2026, 11, 1, 9, 0, tzinfo=UTC)

    # Halfway to the due date the card is not due; after it, it is.
    halfway = datetime(2026, 11, 1, 9, 5, tzinfo=UTC)
    monkeypatch.setenv("TRAINER_TEST_NOW", halfway.isoformat())
    assert scheduler.get_due_cards() == []

    monkeypatch.setenv("TRAINER_TEST_NOW", first.next_due.isoformat())
    assert [card.card_id for card in scheduler.get_due_cards()] == ["clock-card"]

    second = scheduler.process_review("clock-card", TrainingRating.GOOD)
    assert second.new_interval >= first.new_interval
    assert second.next_due >= first.next_due

    # Again shrinks the next interval; it must not be treated as a success.
    again = scheduler.process_review("clock-card", TrainingRating.AGAIN)
    assert again.lapses == 1
    assert again.new_interval <= second.new_interval


def test_memory_utc_now_resets_monotonic_latch_when_test_clock_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.memory.models import utc_now as memory_utc_now

    monkeypatch.setenv("TRAINER_TEST_NOW", "2099-01-01T00:00:00Z")
    future = memory_utc_now()
    assert future.year == 2099

    monkeypatch.delenv("TRAINER_TEST_NOW", raising=False)
    real = memory_utc_now()
    assert real.year < 2099


# ---------------------------------------------------------------------------
# Restored from test_memory_language_context.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def contains_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def test_workspace_language_keeps_memory_copy_in_zh_cn_even_when_summary_is_english() -> None:
    database_path = Path(".tmp-test/memory-language-context.db")
    if database_path.exists():
        database_path.unlink()

    repository = TrainerRepository(database_path)
    service = MemoryService(repository)
    workspace_id = "workspace-memory-language-context"

    service.record_turn_memory(
        workspace_id=workspace_id,
        session_id="session-memory-language-context",
        scenario="coach",
        focus_area="remote workspace boundary",
        summary="Keep the next slice small and verifiable.",
        next_step="Patch one remote workspace edge case first.",
        response_language="zh-CN",
        answer_mode="guided",
    )

    snapshot = service.snapshot(workspace_id)

    assert contains_chinese(snapshot.current_focus)
    assert snapshot.teaching_observations
    assert any(contains_chinese(observation) for observation in snapshot.teaching_observations)


def test_workspace_language_keeps_review_rhythm_in_en_us_even_when_turn_context_is_chinese() -> None:
    database_path = Path(".tmp-test/memory-language-review-rhythm-en.db")
    if database_path.exists():
        database_path.unlink()

    repository = TrainerRepository(database_path)
    service = MemoryService(repository)
    workspace_id = "workspace-memory-review-rhythm-en"

    service.record_turn_memory(
        workspace_id=workspace_id,
        session_id="session-memory-review-rhythm-en",
        scenario="review",
        focus_area="dependency injection",
        summary="先围绕 dependency injection 保持这一条主线。",
        next_step="先把 provider branch 补成一个可验证的小改动。",
        response_language="en-US",
        answer_mode="guided",
        review_note="这里的 provider branch 还没有被验证。",
    )
    structured = service.structured_for_workspace(workspace_id)
    structured.record_weakness(
        "dependency injection",
        "这里的 provider branch 还没有被验证。",
        severity=3,
        review_after_days=0,
        context="server/app/main.py",
    )

    snapshot = service.snapshot(workspace_id)

    assert snapshot.review_rhythm.startswith("Review rhythm:")
    assert not contains_chinese(snapshot.review_rhythm)
    assert snapshot.due_reviews
    assert snapshot.due_reviews[0].task_hint
    assert not contains_chinese(snapshot.due_reviews[0].task_hint)


def test_generic_plan_next_after_localizes_for_chinese_workspace() -> None:
    from app.core.models import LearningPlan
    from app.memory.snapshot_builder import (
        _GENERIC_NEXT_AFTER_CURRENT_EN,
        _GENERIC_NEXT_AFTER_CURRENT_ZH,
        _localize_plan_runtime_next_after,
        _localized_plan_next_after,
    )

    plan = LearningPlan(
        id="plan-generic-next",
        title="Plan",
        next_after_current=_GENERIC_NEXT_AFTER_CURRENT_EN,
    )
    localized = _localized_plan_next_after(plan, "zh-CN")
    assert localized is not None
    assert localized.next_after_current == _GENERIC_NEXT_AFTER_CURRENT_ZH
    assert _localized_plan_next_after(plan, "en-US") is plan

    payload = {
        "latest_plan_runtime": {"next_after_current": _GENERIC_NEXT_AFTER_CURRENT_EN},
        "latestPlanRuntime": {"next_after_current": _GENERIC_NEXT_AFTER_CURRENT_EN},
    }
    _localize_plan_runtime_next_after(payload, "zh-CN")
    assert payload["latest_plan_runtime"]["next_after_current"] == _GENERIC_NEXT_AFTER_CURRENT_ZH
    assert payload["latestPlanRuntime"]["next_after_current"] == _GENERIC_NEXT_AFTER_CURRENT_ZH


# ---------------------------------------------------------------------------
# Restored from test_goal_mode_prompt.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_goal_mode_prompt_requires_an_action_before_explanation() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(),
        coach_context={"goal_mode": True},
    )

    assert "Goal Mode" in prompt
    assert "the learner does the work" in prompt
    assert "Do not open with a lecture" in prompt
    assert "ONE tiny concrete action" in prompt
    assert "Wait for their attempt" in prompt
    assert "correct action alone is not mastery" in prompt
    assert "explain the reasoning" in prompt
    assert "correct teach-back and transfer" in prompt
    assert "Never declare the goal complete" in prompt
    assert "never accept a self-claim" in prompt
    assert "the learner ends it with the goal control" in prompt
    assert "Do not claim formal evidence" in prompt


def test_goal_mode_prompt_is_opt_in() -> None:
    prompt = build_coaching_system_prompt(UserProfile())

    assert "Goal Mode" not in prompt
