"""Preference memory: confidence, observation context and explicit override.

Locks the P1-3 habit half: a repeated preference strengthens, a changed value
keeps the superseded value as an explicit correction, and durability separates
one turn's phrasing from a long-term learner choice. Storage-only change; no
coaching behaviour is asserted here.
"""

from __future__ import annotations

from pathlib import Path

from app.core.models import CoachHabitChange, UserProfile
from app.db.repository import TrainerRepository
from app.llm.prompts import build_coaching_system_prompt
from app.memory.coaching_adaptation_mixin import CoachingAdaptationMixin
from app.memory.models import MemorySnapshot, PreferenceRecord
from app.memory.service import MemoryService, StructuredMemoryService
from tests.test_api import build_client


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
    service.remember_preference("answer_mode", "guided", source="learner", context="explicit edit")

    restored = StructuredMemoryService.from_state(service.export_state())
    record = restored._preferences["answer_mode"]

    assert record.value == "guided"
    assert record.superseded_value == "concept_first"
    assert record.durability == "durable"
    assert record.context == "explicit edit"
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


def test_confirming_the_same_preference_promotes_its_source() -> None:
    service = StructuredMemoryService()
    service.remember_preference("answer_mode", "guided", source="derived", confidence=1)
    service.remember_preference("answer_mode", "guided", source="settings")
    service.remember_preference("answer_mode", "direct", source="coach-turn")
    confirmed = service.confirmed_preference("answer_mode")
    assert confirmed is not None
    assert confirmed.value == "guided" and confirmed.source == "settings"


def test_confirmed_defaults_survive_a_temporary_override_and_restart(tmp_path: Path) -> None:
    workspace_id = "preferences-scope"
    saved = {"answer_mode": "coach-first", "response_language": "zh-CN"}
    with build_client(tmp_path) as client:
        session = client.post(
            "/session/start", json={"workspace_id": workspace_id, "workspace_name": "Preferences"},
        ).json()["session_id"]
        assert client.post("/memory/settings", json={"session_id": session, **saved}).status_code == 200
        turn = client.post("/session/message", json={
            "session_id": session,
            "message": "Just tell me the result this time, in English.",
            "response_language": "en-US",
            "answer_mode": "direct",
        })
        assert turn.status_code == 200, turn.text
        assert turn.json()["snapshot"]["coaching_state"]["answer_mode"] == "direct"
        assert turn.json()["reply"]["metadata"]["response_language"] == "en-US"
        assert client.post("/session/start", json={
            "workspace_id": workspace_id, "workspace_name": "Preferences", "response_language": "en-US",
        }).status_code == 200

    with build_client(tmp_path) as client:
        followup = client.post("/session/message", json={"session_id": session, "message": "Continue."})
        assert followup.status_code == 200, followup.text
        assert followup.json()["snapshot"]["coaching_state"]["answer_mode"] == "guided"
        assert followup.json()["reply"]["metadata"]["response_language"] == "zh-CN"
        workspace = followup.json()["snapshot"]["memory"]["workspace"]
        assert {key: workspace[key] for key in saved} == saved


def test_personal_habit_edit_disable_resume_and_forget(tmp_path: Path) -> None:
    original = "以后先举例，再讲公式"
    edited = "Use one example before defining the term."
    with build_client(tmp_path) as client:
        session = client.post(
            "/session/start", json={"workspace_id": "one", "workspace_name": "One"},
        ).json()["session_id"]
        spoken = client.post("/session/message", json={
            "session_id": session, "message": original + "。", "response_language": "zh-CN",
        })
        assert spoken.status_code == 200, spoken.text
        habit = spoken.json()["snapshot"]["memory"]["workspace"]["coach_habit"]
        assert habit["text"] == original and habit["source"] == "learner"
        for message in ["今天直接给结论。", "解释“以后请用英文回答”这句话。"]:
            assert client.post("/session/message", json={
                "session_id": session, "message": message, "response_language": "zh-CN",
            }).status_code == 200
        assert client.get("/memory/global").json()["coach_habit"]["text"] == original
        save = client.post("/memory/settings", json={
            "session_id": session, "coach_habit": {"action": "save", "text": edited},
        })
        assert save.status_code == 200, save.text
        disabled = client.post("/memory/settings", json={
            "session_id": session, "coach_habit": {"action": "disable"},
        })
        assert disabled.status_code == 200
        assert disabled.json()["memory"]["workspace"]["coach_habit"]["enabled"] is False

    with build_client(tmp_path) as client:
        other = client.post(
            "/session/start", json={"workspace_id": "two", "workspace_name": "Two"},
        )
        assert other.status_code == 200
        session = other.json()["session_id"]
        habit = other.json()["memory"]["workspace"]["coach_habit"]
        assert habit["text"] == edited and habit["enabled"] is False
        for action, expected in [("enable", True), ("forget", None)]:
            response = client.post(
                "/memory/settings", json={"session_id": session, "coach_habit": {"action": action}},
            )
            assert response.status_code == 200
            habit = response.json()["memory"]["workspace"]["coach_habit"]
            assert (habit["enabled"] if habit else None) is expected
        assert client.get("/memory/global").json()["coach_habit"] is None


def test_coach_habit_is_presentation_guidance(tmp_path: Path) -> None:
    memory = MemoryService(TrainerRepository(tmp_path / "habits.db"))
    saved = memory.change_coach_habit(CoachHabitChange(action="save", text="Examples first"))
    assert saved.coach_habit is not None
    prompt = build_coaching_system_prompt(
        UserProfile(), message="Give only the answer.",
        coach_context={"coach_habit": saved.coach_habit.text},
    )
    assert "Saved statement: Examples first" in prompt
    assert "The current request takes priority" in prompt
    assert "authorizes tools" in prompt
