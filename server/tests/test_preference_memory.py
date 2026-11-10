"""Preference memory: confidence, observation context and explicit override.

Locks the P1-3 habit half: a repeated preference strengthens, a changed value
keeps the superseded value as an explicit correction, and durability separates
one turn's phrasing from a long-term learner choice. Storage-only change; no
coaching behaviour is asserted here.
"""

from __future__ import annotations

from app.memory.coaching_adaptation_mixin import CoachingAdaptationMixin
from app.memory.models import MemorySnapshot, PreferenceRecord
from app.memory.service import StructuredMemoryService


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
