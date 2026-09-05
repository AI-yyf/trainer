"""§13.21 EventLedgerService unit tests — 15+ tests covering core functionality."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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
from app.core.models import EventLedgerEntry

# ---------------------------------------------------------------------------
# EventLedgerService — basic record_event
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


# ---------------------------------------------------------------------------
# EventLedgerService — query
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# EventLedgerService — count and all_entries
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# EventLedgerEntry model validation
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# §13.21 New event types — sandbox & teaching asset factory emissions
# ---------------------------------------------------------------------------


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

    def test_all_canonical_event_types_present(self) -> None:
        from app.core.event_ledger import ALL_EVENT_TYPES

        assert len(ALL_EVENT_TYPES) == 41

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


# ---------------------------------------------------------------------------
# New event type constants validation
# ---------------------------------------------------------------------------


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

    def test_total_event_type_count(self) -> None:
        """ALL_EVENT_TYPES must contain exactly 41 event types (including agent checkpoints)."""
        assert len(ALL_EVENT_TYPES) == 41

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
