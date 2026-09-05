from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.models import AffectState, ProviderConfig, TaskSpec, UserProfile
from app.core.settings import AppSettings
from app.db.repository import TrainerRepository
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.memory.service import MemoryService
from app.memory.workspace_recovery import AFFECT_STATE_KEY, CURRENT_TASK_KEY
from app.pedagogy.context_pressure import derive_context_pressure
from app.pedagogy.evidence_controls import LearningEvidenceSignals, resolve_pedagogy_controls
from tests.test_router_stream_scenarios import mark_provider_capabilities_verified


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Turn Context Pressure Persist",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-turn-pressure.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(_settings(tmp_path))
    provider = ProviderConfig(
        name="test-openai-compatible",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={
            "chat": True,
            "responses": True,
            "vision": False,
            "embeddings": True,
            "tools": False,
            "json_schema": False,
            "streaming": True,
        },
    )
    runtime = app.state.runtime
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
    runtime.provider_service = ProviderService(
        config=provider,
        api_key="sk-test-not-a-real-key-aaaaaaaa",
    )
    runtime.provider_service_cache.clear()
    return TestClient(app)


def _heavy_task() -> TaskSpec:
    return TaskSpec(
        id="task-auth-slice",
        title="Auth slice",
        natural_language_goal="Ship one auth check",
        constraints=["keep the session local", "no extra routes"],
        edge_cases=["expired token"],
        failure_conditions=["leaks another workspace"],
    )


def test_memory_persist_survives_new_runtime_and_drives_pressure(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-turn-pressure.db"
    service = MemoryService(TrainerRepository(db_path))
    workspace_id = "workspace-pressure-a"
    service.persist_turn_context_pressure(
        workspace_id,
        current_task=_heavy_task(),
        affect_state=AffectState(urgency_level="high", frustration_level=0.9),
    )

    restarted = MemoryService(TrainerRepository(db_path))
    workspace = restarted._structured_for(workspace_id)._workspace
    assert workspace[CURRENT_TASK_KEY]["id"] == "task-auth-slice"
    assert workspace[CURRENT_TASK_KEY]["workspace_id"] == workspace_id
    assert workspace[AFFECT_STATE_KEY]["urgency_level"] == "high"
    assert workspace[AFFECT_STATE_KEY]["workspace_id"] == workspace_id

    pressure = derive_context_pressure(
        workspace=workspace,
        current_task=workspace.get(CURRENT_TASK_KEY),
        affect_state=workspace.get(AFFECT_STATE_KEY),
    )
    assert pressure.task_urgency == "high"
    assert pressure.project_complexity == "complex"
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=2, success_count=2, concept_success=True),
        time_budget=pressure.time_budget,
        task_urgency=pressure.task_urgency,
        project_complexity=pressure.project_complexity,
        transfer_scene_count=1,
    )
    assert controls.task_urgency == "high"
    assert controls.next_plan_step == "shrink"
    assert controls.material_recommendation == "current"


def test_wrong_workspace_scope_is_ignored(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-turn-pressure.db"
    service = MemoryService(TrainerRepository(db_path))
    service.persist_turn_context_pressure(
        "workspace-pressure-a",
        current_task=_heavy_task(),
        affect_state=AffectState(urgency_level="high"),
    )
    leaked = dict(service._structured_for("workspace-pressure-a")._workspace[CURRENT_TASK_KEY])
    other = service._structured_for("workspace-pressure-b")
    assert CURRENT_TASK_KEY not in other._workspace
    assert AFFECT_STATE_KEY not in other._workspace

    other.update_workspace(**{CURRENT_TASK_KEY: leaked, AFFECT_STATE_KEY: {
        "urgency_level": "high",
        "workspace_id": "workspace-pressure-a",
    }})
    snapshot = service.snapshot("workspace-pressure-b")
    from app.memory.workspace_recovery import (
        normalize_latest_affect_state,
        normalize_latest_current_task,
    )

    assert normalize_latest_current_task(snapshot.workspace.get(CURRENT_TASK_KEY), "workspace-pressure-b") is None
    assert normalize_latest_affect_state(snapshot.workspace.get(AFFECT_STATE_KEY), "workspace-pressure-b") is None
    assert snapshot.coaching_adaptation is None
    assert not snapshot.learning_outcomes


def test_hydrate_task_affect_without_outcome_shows_adaptation(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-turn-pressure.db"
    service = MemoryService(TrainerRepository(db_path))
    workspace_id = "workspace-pressure-a"
    service.persist_turn_context_pressure(
        workspace_id,
        current_task=_heavy_task(),
        affect_state=AffectState(urgency_level="high", frustration_level=0.9),
    )

    restarted = MemoryService(TrainerRepository(db_path))
    snapshot = restarted.snapshot(workspace_id)
    adaptation = snapshot.coaching_adaptation
    assert adaptation is not None
    assert not snapshot.learning_outcomes
    assert adaptation.success_streak == 0
    assert adaptation.failure_streak == 0
    assert adaptation.challenge_level != "raise"
    assert adaptation.material_recommendation != "transfer"
    assert adaptation.transfer_scene_count == 0
    assert adaptation.task_urgency == "high"
    assert adaptation.project_complexity == "complex"
    assert adaptation.next_plan_step == "shrink"
    assert "not global mastery" in (adaptation.summary or "").lower()


def test_no_outcome_does_not_invent_global_raise(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-turn-pressure.db"
    service = MemoryService(TrainerRepository(db_path))
    workspace_id = "workspace-pressure-profile"
    service.record_profile(
        workspace_id,
        UserProfile(long_term_goal="Ship one auth check", weekly_hours=2, teaching_style="guided"),
    )
    snapshot = service.snapshot(workspace_id)
    adaptation = snapshot.coaching_adaptation
    assert adaptation is not None
    assert not snapshot.learning_outcomes
    assert adaptation.success_streak == 0
    assert adaptation.challenge_level != "raise"
    assert adaptation.material_recommendation != "transfer"
    assert adaptation.time_budget == "tight"
    assert adaptation.next_plan_step == "shrink"


def test_failures_still_degrade_after_persisted_pressure(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-turn-pressure.db"
    service = MemoryService(TrainerRepository(db_path))
    workspace_id = "workspace-pressure-failures"
    service.persist_turn_context_pressure(
        workspace_id,
        current_task=_heavy_task(),
        affect_state=AffectState(urgency_level="high"),
    )
    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["auth slice"],
        outcome="evaluation",
        summary="Auth check still fails.",
        action_type="evaluate_current_file",
        focus_area="auth slice",
        scenario="review_reflection",
        repetition_count=1,
    )
    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["auth slice"],
        outcome="repeated_error",
        summary="Auth check still fails.",
        action_type="evaluate_current_file",
        focus_area="auth slice",
        scenario="review_reflection",
        repetition_count=2,
    )
    snapshot = service.snapshot(workspace_id)
    adaptation = snapshot.coaching_adaptation
    assert adaptation is not None
    assert adaptation.failure_streak >= 2
    assert adaptation.challenge_level == "lower"
    assert adaptation.difficulty == "easy"
    assert adaptation.material_recommendation != "transfer"
    assert adaptation.next_plan_step == "shrink"
    assert adaptation.task_urgency == "high"


def test_turn_does_not_invent_current_task_without_verified_provider(tmp_path: Path) -> None:
    """Capability comes from a live last-test; unusable provider must not mint TaskSpec."""
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one check.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-pressure-unverified",
                "workspace_name": "workspace-pressure-unverified",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        assert runtime.provider_connection_verified(runtime.provider_service) is False

        for intent, message in (
            ("coach", "What should I do next?"),
            ("next_task", "Give me the next task."),
            ("task", "Turn this into a task: ship one auth check."),
        ):
            turn = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-pressure-unverified",
                    "intent": intent,
                    "message": message,
                    "response_language": "en-US",
                },
            )
            assert turn.status_code == 200, turn.text
            body = turn.json()
            live_workspace = body["snapshot"]["memory"]["workspace"]
            assert live_workspace.get(CURRENT_TASK_KEY) in (None, {})
            assert body["snapshot"].get("current_task") in (None, {})
            if intent in {"next_task", "task"}:
                summary = str(body.get("coach_turn", {}).get("summary") or "")
                assert "did not invent a task" in summary.lower()


def test_turn_persists_task_and_urgency_for_restart_and_switch(tmp_path: Path) -> None:
    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!!"
    )
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one check.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-pressure-a",
                "workspace_name": "workspace-pressure-a",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        # Persist path requires a live last-test; do not invent task under unverified provider.
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        assert runtime.provider_connection_verified(runtime.provider_service) is True
        state = runtime.ensure_session(session_id, workspace_id="workspace-pressure-a")
        state.snapshot.current_task = _heavy_task()
        runtime.save_session_state(session_id)

        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-pressure-a",
                "intent": "coach",
                "message": urgent,
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        live_memory = turn.json()["snapshot"]["memory"]
        live_workspace = live_memory["workspace"]
        assert live_workspace[CURRENT_TASK_KEY]["id"] == "task-auth-slice"
        assert live_workspace[AFFECT_STATE_KEY]["urgency_level"] == "high"
        assert live_workspace.get("task_urgency") == "high"
        live_adaptation = live_memory["coaching_adaptation"]
        assert live_adaptation is not None
        assert live_adaptation["success_streak"] == 0
        assert live_adaptation["challenge_level"] != "raise"
        assert live_adaptation["material_recommendation"] != "transfer"
        assert live_adaptation["task_urgency"] == "high"
        assert live_adaptation["next_plan_step"] == "shrink"

        switch = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-pressure-b",
                "workspace_name": "workspace-pressure-b",
                "profile": {
                    "long_term_goal": "Other project",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert switch.status_code == 200
        other_workspace = switch.json()["memory"]["workspace"]
        assert not other_workspace.get(CURRENT_TASK_KEY)
        assert not other_workspace.get(AFFECT_STATE_KEY)
        assert other_workspace.get("task_urgency") in {None, "", "medium"}

    with _client(tmp_path) as restarted:
        hydrate = restarted.post(
            "/session/start",
            json={
                "workspace_id": "workspace-pressure-a",
                "workspace_name": "workspace-pressure-a",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert hydrate.status_code == 200
        restored_memory = hydrate.json()["memory"]
        restored = restored_memory["workspace"]
        assert restored[CURRENT_TASK_KEY]["id"] == "task-auth-slice"
        assert restored[AFFECT_STATE_KEY]["urgency_level"] == "high"
        restored_adaptation = restored_memory["coaching_adaptation"]
        assert restored_adaptation is not None
        assert restored_adaptation["success_streak"] == 0
        assert restored_adaptation["challenge_level"] != "raise"
        assert restored_adaptation["material_recommendation"] != "transfer"
        assert restored_adaptation["task_urgency"] == "high"
        session_id = str(hydrate.json()["session_id"])
        signal = restarted.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-pressure-a",
                "concepts": ["auth slice"],
                "outcome": "tests_passed",
                "summary": "The focused auth check now passes.",
                "action_type": "evaluate_current_file",
                "focus_area": "auth slice",
                "scenario": "review_reflection",
                "repetition_count": 1,
            },
        )
        assert signal.status_code == 200
        adaptation = signal.json()["memory"]["coaching_adaptation"]
        assert adaptation["task_urgency"] == "high"
        assert adaptation["project_complexity"] == "complex"
        assert adaptation["next_plan_step"] == "shrink"
        assert adaptation["material_recommendation"] == "current"


def test_tight_budget_orphaned_runtime_does_not_invent_live_task(tmp_path: Path) -> None:
    """weekly_hours/urgency may shrink pedagogy; orphaned runtime must not invent a task."""
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one check.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-pressure-no-invent-task",
                "workspace_name": "workspace-pressure-no-invent-task",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 2,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        from app.memory.workspace_recovery import PLAN_RUNTIME_KEY

        runtime.memory_service.update_workspace_state(
            "workspace-pressure-no-invent-task",
            **{
                PLAN_RUNTIME_KEY: {
                    "workspace_id": "workspace-pressure-no-invent-task",
                    "blocked_reason": "auth still fails",
                    "current_step": "Keep one auth check",
                    "resume_state": "in_progress",
                }
            },
        )
        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-pressure-no-invent-task",
                "intent": "coach",
                "message": "What should I do next?",
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        body = turn.json()
        snapshot = body["snapshot"]
        assert snapshot.get("current_task") in (None, {})
        assert snapshot["memory"]["workspace"].get(CURRENT_TASK_KEY) in (None, {})
        coach_turn = body.get("coach_turn") or {}
        assert coach_turn.get("active_task") in (None, "")
        assert "Keep one auth check" not in str(coach_turn.get("active_task") or "")
        status = snapshot.get("plan_runtime_status") or {}
        hint = status.get("next_step_hint") or {}
        if hint:
            assert hint.get("recommended_action") != "task" or hint.get("source") != "plan"
            assert hint.get("title") != "Keep one auth check"
        adaptation = snapshot["memory"].get("coaching_adaptation") or {}
        assert adaptation.get("time_budget") == "tight"
        assert adaptation.get("next_plan_step") == "shrink"


def test_tight_budget_without_live_objects_does_not_invent_card(tmp_path: Path) -> None:
    """Tight weekly_hours adapts hints; must not mint plan/task/card when none are live."""
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one thin slice.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-pressure-no-invent-card",
                "workspace_name": "workspace-pressure-no-invent-card",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 2,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-pressure-no-invent-card",
                "intent": "coach",
                "message": "What should I do next?",
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        body = turn.json()
        snapshot = body["snapshot"]
        memory = snapshot["memory"]
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        plan = snapshot.get("plan") or {}
        assert not str(plan.get("id") or plan.get("plan_id") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("time_budget") == "tight"
        assert adaptation.get("next_plan_step") == "shrink"
        assert int(adaptation.get("hint_count") or 0) >= 2


def test_complex_without_live_objects_does_not_invent(tmp_path: Path) -> None:
    """High complexity adapts hints/pace; must not mint plan/task/card when none live."""
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one thin slice.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-complexity-no-invent",
                "workspace_name": "workspace-complexity-no-invent",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        runtime.memory_service.update_workspace_state(
            "workspace-complexity-no-invent",
            project_complexity="complex",
        )
        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-complexity-no-invent",
                "intent": "coach",
                "message": "What should I do next?",
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        body = turn.json()
        snapshot = body["snapshot"]
        memory = snapshot["memory"]
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("time_budget") != "tight"
        assert adaptation.get("task_urgency") != "high"
        assert adaptation.get("project_complexity") == "complex"
        assert adaptation.get("material_recommendation") != "transfer"
        assert (memory.get("mastery") or []) == []
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True


def test_struggling_ability_without_live_objects_does_not_invent(tmp_path: Path) -> None:
    """Lower ability adapts hints/pace; must not mint plan/task/card when none live."""
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one thin slice.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-ability-no-invent",
                "workspace_name": "workspace-ability-no-invent",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        runtime.memory_service.update_workspace_state(
            "workspace-ability-no-invent",
            current_ability="struggling",
        )
        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-ability-no-invent",
                "intent": "coach",
                "message": "What should I do next?",
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        body = turn.json()
        snapshot = body["snapshot"]
        memory = snapshot["memory"]
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("time_budget") != "tight"
        assert adaptation.get("task_urgency") != "high"
        assert adaptation.get("project_complexity") != "complex"
        assert (memory.get("mastery") or []) == []
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True


def test_preference_too_hard_without_live_objects_does_not_invent(tmp_path: Path) -> None:
    """Preference-to-hints adapts scaffolding; must not mint plan/task/card when none live."""
    workspace_id = "workspace-pref-hint-no-invent"
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one thin slice.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        feedback = client.post(
            "/memory/feedback",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "kind": "too_hard",
                "message": "This slice is too hard to start alone.",
                "focus_area": "auth check",
                "scenario": "coach",
            },
        )
        assert feedback.status_code == 200, feedback.text
        assert (feedback.json().get("memory") or {}).get("workspace", {}).get(
            "latest_user_feedback_kind"
        ) == "too_hard"
        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "What should I do next?",
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        body = turn.json()
        snapshot = body["snapshot"]
        memory = snapshot["memory"]
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("challenge_level") == "lower"
        assert adaptation.get("hint_count") == 3
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True


def test_preference_too_simple_without_live_objects_does_not_invent(tmp_path: Path) -> None:
    """Raise preference without live objects must not mint via trust theater."""
    workspace_id = "workspace-pref-raise-no-invent"
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one thin slice.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        feedback = client.post(
            "/memory/feedback",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "kind": "too_simple",
                "message": "This slice is too simple; stretch me.",
                "focus_area": "auth check",
                "scenario": "coach",
            },
        )
        assert feedback.status_code == 200, feedback.text
        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "What should I do next?",
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        body = turn.json()
        snapshot = body["snapshot"]
        memory = snapshot["memory"]
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        assert (memory.get("mastery") or []) == []
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True


def test_low_evidence_trust_without_live_objects_does_not_invent(tmp_path: Path) -> None:
    """Unverified success labels are low-trust; coach turn must not mint live objects."""
    workspace_id = "workspace-low-trust-no-invent"
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one thin slice.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        for summary in ("Client claimed pass one.", "Client claimed pass two."):
            signal = client.post(
                "/learning/signal",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "concepts": ["auth check"],
                    "outcome": "tests_passed",
                    "summary": summary,
                    "action_type": "evaluate_current_file",
                    "focus_area": "auth check",
                },
            )
            assert signal.status_code == 200, signal.text
        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "What should I do next?",
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        body = turn.json()
        snapshot = body["snapshot"]
        memory = snapshot["memory"]
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("challenge_level") == "steady"
        assert (memory.get("mastery") or []) == []
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True


@pytest.mark.parametrize(
    "path",
    ["/turn/stream", "/session/message", "/session/message/stream"],
)
def test_low_evidence_trust_stream_and_session_does_not_invent(
    tmp_path: Path,
    path: str,
) -> None:
    """Unverified tests_passed: /turn/stream + /session/message must not invent; stamp stays."""
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = f"workspace-low-trust-{path.strip('/').replace('/', '-')}"

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Stay on one thin slice."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Stay on one thin slice."),
        ),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        for summary in ("Client claimed pass one.", "Client claimed pass two."):
            signal = client.post(
                "/learning/signal",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "concepts": ["auth check"],
                    "outcome": "tests_passed",
                    "summary": summary,
                    "action_type": "evaluate_current_file",
                    "focus_area": "auth check",
                },
            )
            assert signal.status_code == 200, signal.text
        payload: dict[str, object] = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "message": "What should I do next?",
            "response_language": "en-US",
            "use_agent_loop": False,
        }
        if path.startswith("/turn"):
            payload["intent"] = "coach"
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )
        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions if isinstance(item, dict)}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("challenge_level") == "steady"
        assert (memory.get("mastery") or []) == []
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True


@pytest.mark.parametrize(
    "path",
    ["/turn/stream", "/session/message", "/session/message/stream"],
)
def test_preference_too_hard_stream_and_session_does_not_invent(
    tmp_path: Path,
    path: str,
) -> None:
    """Preference too_hard without live objects: /turn/stream + /session/message must not invent."""
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = f"workspace-pref-hard-{path.strip('/').replace('/', '-')}"

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Stay on one thin slice."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Stay on one thin slice."),
        ),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        feedback = client.post(
            "/memory/feedback",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "kind": "too_hard",
                "message": "This slice is too hard to start alone.",
                "focus_area": "auth check",
                "scenario": "coach",
            },
        )
        assert feedback.status_code == 200, feedback.text
        assert (feedback.json().get("memory") or {}).get("workspace", {}).get(
            "latest_user_feedback_kind"
        ) == "too_hard"
        payload = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "message": "What should I do next?",
            "response_language": "en-US",
            "use_agent_loop": False,
        }
        if path.startswith("/turn"):
            payload["intent"] = "coach"
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )
        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions if isinstance(item, dict)}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True


def test_turn_stream_agent_tools_too_hard_does_not_invent(tmp_path: Path) -> None:
    """`/turn/stream` ReAct + tools under too_hard preference: hint-only, stamp preserved."""
    from unittest.mock import PropertyMock

    from app.core.models import (
        ProviderCapabilityEvidence,
        ProviderConfig,
        ProviderTestResponse,
    )
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = "workspace-stream-agent-pref-hard-no-invent"
    captured: dict[str, object] = {}

    async def fake_agent_stream(*_args: object, **kwargs: object):
        coach_context = kwargs.get("coach_context") or {}
        assert isinstance(coach_context, dict)
        captured["pressure_blocks_live_object_mint"] = coach_context.get(
            "pressure_blocks_live_object_mint"
        )
        yield {
            "type": "text",
            "delta": "Stay with one thin repair slice.",
            "safe_to_stream": True,
        }
        yield {
            "type": "final",
            "content": "Stay with one thin repair slice.",
            "summary": "Preference hint-only",
            "next_step": "Shrink to one check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="test-tool-stream-pref-hard",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.stream-agent-pref-hard",
            model="test-model",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
        runtime.provider_service = ProviderService(
            config=provider,
            api_key="sk-test-not-a-real-key-aaaaaaaa",
        )
        runtime.provider_service_cache.clear()
        runtime.remember_provider_capability_test(
            provider,
            "sk-test-not-a-real-key-aaaaaaaa",
            ProviderTestResponse(
                ok=True,
                detail="mocked provider capability test",
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="tools",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                ],
                tools_ready=True,
                tool_probe_status="verified",
            ),
        )
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=fake_agent_stream,
            ),
        ):
            feedback = client.post(
                "/memory/feedback",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "kind": "too_hard",
                    "message": "This slice is too hard to start alone.",
                    "focus_area": "auth check",
                    "scenario": "coach",
                },
            )
            assert feedback.status_code == 200, feedback.text
            response = client.post(
                "/turn/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "coach",
                    "message": "What should I do next? Create a practice card.",
                    "response_language": "en-US",
                    "use_agent_loop": True,
                },
            )
        assert response.status_code == 200, response.text
        body = completed_stream_response(response.text)
        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions if isinstance(item, dict)}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        assert captured.get("pressure_blocks_live_object_mint") is True
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True


def test_strategy_bias_hints_without_feedback_kind_does_not_invent(tmp_path: Path) -> None:
    """Strategy bias can prefer hints without latest_user_feedback_kind; still block mint."""
    workspace_id = "workspace-strategy-bias-hint-no-invent"
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one thin slice.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        structured = runtime.memory_service.structured_for_workspace(workspace_id)
        structured.update_workspace(focus_area="auth check", scenario="coach")
        for index in range(3):
            structured.remember_teaching_strategy_effectiveness(
                scenario="coach",
                focus_area="auth check",
                challenge_level="lower",
                hint_depth="direct",
                review_urgency="high",
                explanation_mode="rebuild",
                next_step_bias="shrink",
                outcome="concept_answered_correctly",
                summary=f"Hint-first lane worked {index + 1}.",
            )
            structured.remember_learning_outcome(
                "auth check",
                "concept_answered_correctly",
                summary=f"Explained auth check slice {index + 1}.",
                action_type="coach",
            )
        assert not str(structured._workspace.get("latest_user_feedback_kind") or "").strip()
        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "What should I do next? Create a practice card.",
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        body = turn.json()
        snapshot = body["snapshot"]
        memory = snapshot["memory"]
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert not str(workspace.get("latest_user_feedback_kind") or "").strip()
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("challenge_level") == "lower"
        assert adaptation.get("hint_depth") == "direct"
        assert adaptation.get("next_step_bias") == "shrink"
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True


@pytest.mark.parametrize(
    "path",
    ["/turn/stream", "/session/message", "/session/message/stream"],
)
def test_strategy_bias_hints_stream_and_session_does_not_invent(
    tmp_path: Path,
    path: str,
) -> None:
    """Strategy bias without latest_user_feedback_kind: stream/session must not invent."""
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = f"workspace-strategy-bias-{path.strip('/').replace('/', '-')}"

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Stay on one thin slice."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Stay on one thin slice."),
        ),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        structured = runtime.memory_service.structured_for_workspace(workspace_id)
        structured.update_workspace(focus_area="auth check", scenario="coach")
        for index in range(3):
            structured.remember_teaching_strategy_effectiveness(
                scenario="coach",
                focus_area="auth check",
                challenge_level="lower",
                hint_depth="direct",
                review_urgency="high",
                explanation_mode="rebuild",
                next_step_bias="shrink",
                outcome="concept_answered_correctly",
                summary=f"Hint-first lane worked {index + 1}.",
            )
            structured.remember_learning_outcome(
                "auth check",
                "concept_answered_correctly",
                summary=f"Explained auth check slice {index + 1}.",
                action_type="coach",
            )
        assert not str(structured._workspace.get("latest_user_feedback_kind") or "").strip()
        payload: dict[str, object] = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "message": "What should I do next? Create a practice card.",
            "response_language": "en-US",
            "use_agent_loop": False,
        }
        if path.startswith("/turn"):
            payload["intent"] = "coach"
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )
        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert not str(workspace.get("latest_user_feedback_kind") or "").strip()
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("challenge_level") == "lower"
        assert adaptation.get("hint_depth") == "direct"
        assert adaptation.get("next_step_bias") == "shrink"
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions if isinstance(item, dict)}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True


@pytest.mark.parametrize("path", ["/turn/stream", "/session/message"])
def test_low_evidence_trust_agent_tools_does_not_invent(
    tmp_path: Path,
    path: str,
) -> None:
    """Unverified tests_passed + ReAct tools ON: stamp stays; mint tools denied; no invent.

    Fail-closed already via pressure_blocks → denied_tool_names / _task_mint_tool_allowed —
    this proves /turn/stream and /session/message wire the low-trust stamp into agentic ReAct.
    """
    from unittest.mock import PropertyMock

    from app.core.models import (
        ProviderCapabilityEvidence,
        ProviderConfig,
        ProviderTestResponse,
    )
    from app.llm.provider_service import _build_agent_tool_context_extra
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = f"workspace-low-trust-agent-{path.strip('/').replace('/', '-')}"
    captured: dict[str, object] = {}
    learner_message = (
        "I passed tests. Create a practice card and give me the next task."
    )

    async def fake_agent(*_args: object, **kwargs: object):
        coach_context = kwargs.get("coach_context") or {}
        assert isinstance(coach_context, dict)
        captured["pressure_blocks_live_object_mint"] = coach_context.get(
            "pressure_blocks_live_object_mint"
        )
        captured["coach_context"] = dict(coach_context)
        return {
            "content": "Stay with one thin verified slice.",
            "summary": "Low-trust hint-only",
            "next_step": "One thinner check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    async def fake_agent_stream(*_args: object, **kwargs: object):
        coach_context = kwargs.get("coach_context") or {}
        assert isinstance(coach_context, dict)
        captured["pressure_blocks_live_object_mint"] = coach_context.get(
            "pressure_blocks_live_object_mint"
        )
        captured["coach_context"] = dict(coach_context)
        yield {
            "type": "text",
            "delta": "Stay with one thin verified slice.",
            "safe_to_stream": True,
        }
        yield {
            "type": "final",
            "content": "Stay with one thin verified slice.",
            "summary": "Low-trust hint-only",
            "next_step": "One thinner check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="test-tool-low-trust-agent",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.stream-agent-low-trust",
            model="test-model",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
        runtime.provider_service = ProviderService(
            config=provider,
            api_key="sk-test-not-a-real-key-aaaaaaaa",
        )
        runtime.provider_service_cache.clear()
        runtime.remember_provider_capability_test(
            provider,
            "sk-test-not-a-real-key-aaaaaaaa",
            ProviderTestResponse(
                ok=True,
                detail="mocked provider capability test",
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="tools",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                ],
                tools_ready=True,
                tool_probe_status="verified",
            ),
        )
        for summary in ("Client claimed pass one.", "Client claimed pass two."):
            signal = client.post(
                "/learning/signal",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "concepts": ["auth check"],
                    "outcome": "tests_passed",
                    "summary": summary,
                    "action_type": "evaluate_current_file",
                    "focus_area": "auth check",
                },
            )
            assert signal.status_code == 200, signal.text
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(side_effect=fake_agent),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=fake_agent_stream,
            ),
        ):
            payload: dict[str, object] = {
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": learner_message,
                "response_language": "en-US",
                "use_agent_loop": True,
            }
            if path.startswith("/turn"):
                payload["intent"] = "coach"
            response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )

        assert captured.get("pressure_blocks_live_object_mint") is True
        coach_context = captured.get("coach_context")
        assert isinstance(coach_context, dict)
        extra = _build_agent_tool_context_extra(
            coach_context=coach_context,
            attachment_delivery={"attachments_present": False},
            answer_mode="guided",
            current_file=None,
            learner_message=learner_message,
        )
        denied = extra.get("denied_tool_names") or []
        assert "generate_training_card" in denied
        assert "specify_task" in denied
        assert "next_task" in denied
        assert "inspect_current_file" not in denied
        assert "inspect_plan" not in denied

        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True
        assert agent_meta.get("agentic") is True

        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(
            workspace.get("selected_card_id") or workspace.get("selectedCardId") or ""
        ).strip()
        assert not str(
            routing.get("selected_card_id") or routing.get("selectedCardId") or ""
        ).strip()
        actions = body.get("suggested_actions") or []
        action_types = {
            str(item.get("action") or "") for item in actions if isinstance(item, dict)
        }
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types


@pytest.mark.parametrize("path", ["/turn/stream", "/session/message"])
def test_strategy_bias_agent_tools_does_not_invent(
    tmp_path: Path,
    path: str,
) -> None:
    """Strategy-bias too_hard equivalent + ReAct tools ON: stamp stays; mint denied; no invent.

    Fail-closed already via preference_equivalent_from_strategy_bias → pressure_blocks →
    denied_tool_names. Proves /turn/stream and /session/message agentic wiring.
    """
    from unittest.mock import PropertyMock

    from app.core.models import (
        ProviderCapabilityEvidence,
        ProviderConfig,
        ProviderTestResponse,
    )
    from app.llm.provider_service import _build_agent_tool_context_extra
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = f"workspace-strategy-bias-agent-{path.strip('/').replace('/', '-')}"
    captured: dict[str, object] = {}
    learner_message = "What should I do next? Create a practice card and next task."

    async def fake_agent(*_args: object, **kwargs: object):
        coach_context = kwargs.get("coach_context") or {}
        assert isinstance(coach_context, dict)
        captured["pressure_blocks_live_object_mint"] = coach_context.get(
            "pressure_blocks_live_object_mint"
        )
        captured["coach_context"] = dict(coach_context)
        return {
            "content": "Stay with one thin repair slice.",
            "summary": "Strategy-bias hint-only",
            "next_step": "Shrink to one check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    async def fake_agent_stream(*_args: object, **kwargs: object):
        coach_context = kwargs.get("coach_context") or {}
        assert isinstance(coach_context, dict)
        captured["pressure_blocks_live_object_mint"] = coach_context.get(
            "pressure_blocks_live_object_mint"
        )
        captured["coach_context"] = dict(coach_context)
        yield {
            "type": "text",
            "delta": "Stay with one thin repair slice.",
            "safe_to_stream": True,
        }
        yield {
            "type": "final",
            "content": "Stay with one thin repair slice.",
            "summary": "Strategy-bias hint-only",
            "next_step": "Shrink to one check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="test-tool-strategy-bias-agent",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.stream-agent-strategy-bias",
            model="test-model",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
        runtime.provider_service = ProviderService(
            config=provider,
            api_key="sk-test-not-a-real-key-aaaaaaaa",
        )
        runtime.provider_service_cache.clear()
        runtime.remember_provider_capability_test(
            provider,
            "sk-test-not-a-real-key-aaaaaaaa",
            ProviderTestResponse(
                ok=True,
                detail="mocked provider capability test",
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="tools",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                ],
                tools_ready=True,
                tool_probe_status="verified",
            ),
        )
        structured = runtime.memory_service.structured_for_workspace(workspace_id)
        structured.update_workspace(focus_area="auth check", scenario="coach")
        for index in range(3):
            structured.remember_teaching_strategy_effectiveness(
                scenario="coach",
                focus_area="auth check",
                challenge_level="lower",
                hint_depth="direct",
                review_urgency="high",
                explanation_mode="rebuild",
                next_step_bias="shrink",
                outcome="concept_answered_correctly",
                summary=f"Hint-first lane worked {index + 1}.",
            )
            structured.remember_learning_outcome(
                "auth check",
                "concept_answered_correctly",
                summary=f"Explained auth check slice {index + 1}.",
                action_type="coach",
            )
        assert not str(structured._workspace.get("latest_user_feedback_kind") or "").strip()
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(side_effect=fake_agent),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=fake_agent_stream,
            ),
        ):
            payload: dict[str, object] = {
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": learner_message,
                "response_language": "en-US",
                "use_agent_loop": True,
            }
            if path.startswith("/turn"):
                payload["intent"] = "coach"
            response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )

        assert captured.get("pressure_blocks_live_object_mint") is True
        coach_context = captured.get("coach_context")
        assert isinstance(coach_context, dict)
        extra = _build_agent_tool_context_extra(
            coach_context=coach_context,
            attachment_delivery={"attachments_present": False},
            answer_mode="guided",
            current_file=None,
            learner_message=learner_message,
        )
        denied = extra.get("denied_tool_names") or []
        assert "generate_training_card" in denied
        assert "specify_task" in denied
        assert "next_task" in denied
        assert "inspect_current_file" not in denied
        assert "inspect_plan" not in denied

        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True
        assert agent_meta.get("agentic") is True

        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert not str(workspace.get("latest_user_feedback_kind") or "").strip()
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(
            workspace.get("selected_card_id") or workspace.get("selectedCardId") or ""
        ).strip()
        assert not str(
            routing.get("selected_card_id") or routing.get("selectedCardId") or ""
        ).strip()
        actions = body.get("suggested_actions") or []
        action_types = {
            str(item.get("action") or "") for item in actions if isinstance(item, dict)
        }
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types


def test_high_urgency_without_weekly_hours_does_not_invent_card(tmp_path: Path) -> None:
    """High urgency alone (no tight weekly_hours) adapts hints; must not mint live objects."""
    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "Create a practice card for debugging a Python traceback in VS Code."
    )
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one thin slice.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-pressure-urgency-no-invent",
                "workspace_name": "workspace-pressure-urgency-no-invent",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-pressure-urgency-no-invent",
                "intent": "coach",
                "message": urgent,
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        body = turn.json()
        snapshot = body["snapshot"]
        memory = snapshot["memory"]
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        plan = snapshot.get("plan") or {}
        assert not str(plan.get("id") or plan.get("plan_id") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("time_budget") != "tight"
        assert adaptation.get("task_urgency") == "high"
        assert adaptation.get("next_plan_step") == "shrink"


def test_turn_stream_high_urgency_without_live_objects_does_not_invent(tmp_path: Path) -> None:
    """`/turn/stream` high-urgency-only matches non-stream: hint chips, no card/plan/task invent."""
    from tests.test_router_stream_scenarios import completed_stream_response

    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "Create a practice card for debugging a Python traceback in VS Code."
    )

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Stay on one thin slice."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one thin slice.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-stream-urgency-no-invent",
                "workspace_name": "workspace-stream-urgency-no-invent",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        response = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-stream-urgency-no-invent",
                "intent": "coach",
                "message": urgent,
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert response.status_code == 200, response.text
        body = completed_stream_response(response.text)
        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions if isinstance(item, dict)}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("time_budget") != "tight"
        assert adaptation.get("task_urgency") == "high"
        assert adaptation.get("next_plan_step") == "shrink"


@pytest.mark.parametrize("path", ["/turn", "/turn/stream"])
@pytest.mark.parametrize("intent", ["task", "next_task"])
def test_high_urgency_task_intent_does_not_invent_live_task(
    tmp_path: Path,
    path: str,
    intent: str,
) -> None:
    """Message-time high urgency must remap task/next_task invent before persist."""
    from tests.test_router_stream_scenarios import completed_stream_response

    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "Give me the next task."
    )

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Stay on one thin slice."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one thin slice.")),
    ):
        workspace_id = f"workspace-urgency-{intent}-{path.rsplit('/', 1)[-1]}"
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        payload = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "intent": intent,
            "message": urgent,
            "response_language": "en-US",
            "use_agent_loop": False,
        }
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )
        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        assert snapshot.get("current_task") in (None, {})
        assert workspace.get(CURRENT_TASK_KEY) in (None, {})
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions if isinstance(item, dict)}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("task_urgency") == "high"


def test_high_urgency_orphaned_runtime_does_not_invent_live_task(tmp_path: Path) -> None:
    """Orphaned runtime (current_step, no plan_id) + high urgency: no plan-sourced task / active_task."""
    from app.memory.workspace_recovery import PLAN_RUNTIME_KEY

    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "What should I do next?"
    )
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one check.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-urgency-orphan-no-invent",
                "workspace_name": "workspace-urgency-orphan-no-invent",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        runtime.memory_service.update_workspace_state(
            "workspace-urgency-orphan-no-invent",
            **{
                PLAN_RUNTIME_KEY: {
                    "workspace_id": "workspace-urgency-orphan-no-invent",
                    "blocked_reason": "auth still fails",
                    "current_step": "Keep one auth check",
                    "resume_state": "in_progress",
                }
            },
        )
        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-urgency-orphan-no-invent",
                "intent": "coach",
                "message": urgent,
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        body = turn.json()
        snapshot = body["snapshot"]
        assert snapshot.get("current_task") in (None, {})
        assert snapshot["memory"]["workspace"].get(CURRENT_TASK_KEY) in (None, {})
        coach_turn = body.get("coach_turn") or {}
        assert coach_turn.get("active_task") in (None, "")
        assert "Keep one auth check" not in str(coach_turn.get("active_task") or "")
        status = snapshot.get("plan_runtime_status") or {}
        hint = status.get("next_step_hint") or {}
        if hint:
            assert hint.get("recommended_action") != "task" or hint.get("source") != "plan"
            assert hint.get("title") != "Keep one auth check"
        adaptation = snapshot["memory"].get("coaching_adaptation") or {}
        assert adaptation.get("time_budget") != "tight"
        assert adaptation.get("task_urgency") == "high"
        assert adaptation.get("next_plan_step") == "shrink"


def test_explicit_generate_card_under_pressure_still_mints(tmp_path: Path) -> None:
    """Pressure blocks invent on coach turns; explicit /training/generate-card must still mint."""
    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "What should I do next?"
    )
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one slice.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-pressure-explicit-card",
                "workspace_name": "workspace-pressure-explicit-card",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 2,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-pressure-explicit-card",
                "intent": "coach",
                "message": urgent,
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        turn_body = turn.json()
        adaptation = turn_body["snapshot"]["memory"].get("coaching_adaptation") or {}
        assert adaptation.get("time_budget") == "tight"
        assert adaptation.get("task_urgency") == "high"
        before = turn_body["snapshot"]["memory"].get("workspace") or {}
        assert not str(before.get("selected_card_id") or before.get("selectedCardId") or "").strip()

        model_card_json = json.dumps(
            {
                "title": "Practice auth check",
                "focus_area": "auth check",
                "target_skill": "verify one auth check",
                "scenario": "One auth check is failing and needs a verified slice.",
                "problem_statement": "Reproduce the failing auth check and verify one fix.",
                "api_hints": ["Run the auth check", "Fix one failing branch"],
                "deliverable": "A snippet that exercises the fixed auth check.",
                "self_check": ["The check passes", "No other branch changed"],
                "grading_rubric": ["Fixes the failing check", "Includes verification output"],
                "stuck_recovery": "Write the expected auth flow on paper first.",
                "reflection_prompt": "What assumption made the check fail?",
            }
        )
        with patch.object(
            ProviderService,
            "chat_completion",
            new=AsyncMock(return_value=model_card_json),
        ):
            generated = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": "workspace-pressure-explicit-card",
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "auth check",
                    "context_hint": "Explicit generate under pressure must still mint.",
                    "response_language": "en-US",
                },
            )
        assert generated.status_code == 200, generated.text
        payload = generated.json()
        assert payload.get("success") is True
        card = payload.get("card") or {}
        card_id = str(card.get("card_id") or card.get("id") or "").strip()
        assert card_id
        routing = payload.get("active_routing") or {}
        assert str(routing.get("selected_card_id") or "").strip() == card_id


_URGENT_NO_INVENT = (
    "I am stuck and blocked and overwhelmed and frustrated. "
    "This is not working, broken, error, struggling!! "
    "Create a practice card for debugging a Python traceback in VS Code."
)


@pytest.mark.parametrize("path", ["/session/message", "/session/message/stream"])
def test_session_message_high_urgency_without_live_objects_does_not_invent(
    tmp_path: Path,
    path: str,
) -> None:
    """`/session/message` (+ stream) high-urgency-only matches `/turn`: hint chips, no invent."""
    from tests.test_router_stream_scenarios import completed_stream_response

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Stay on one thin slice."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Stay on one thin slice."),
        ),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-session-urgency-no-invent",
                "workspace_name": "workspace-session-urgency-no-invent",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        response = client.post(
            path,
            json={
                "session_id": session_id,
                "workspace_id": "workspace-session-urgency-no-invent",
                "message": _URGENT_NO_INVENT,
                "response_language": "en-US",
                "use_agent_loop": False,
                # Coaching must ignore silent formalPlanMutation under urgency.
                "formalPlanMutation": True,
            },
        )
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )
        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions if isinstance(item, dict)}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("time_budget") != "tight"
        assert adaptation.get("task_urgency") == "high"
        assert adaptation.get("next_plan_step") == "shrink"
        # Response stamp parity: snake on coach_focus + agent_meta (host adapter → camelCase).
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True


@pytest.mark.parametrize("path", ["/turn", "/turn/stream"])
def test_turn_high_urgency_without_live_objects_stamps_pressure_block(
    tmp_path: Path,
    path: str,
) -> None:
    """`/turn` (+ stream) high-urgency stamp matches `/session/message` coach_focus/agent_meta."""
    from tests.test_router_stream_scenarios import completed_stream_response

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Stay on one thin slice."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Stay on one thin slice."),
        ),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-turn-urgency-stamp",
                "workspace_name": "workspace-turn-urgency-stamp",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        response = client.post(
            path,
            json={
                "session_id": session_id,
                "workspace_id": "workspace-turn-urgency-stamp",
                "intent": "coach",
                "message": _URGENT_NO_INVENT,
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("pressure_blocks_live_object_mint") is True


@pytest.mark.parametrize(
    "path",
    ["/turn", "/turn/stream", "/session/message", "/session/message/stream"],
)
def test_turn_after_consecutive_failures_preserves_streak_blocks_stamp(
    tmp_path: Path,
    path: str,
) -> None:
    """Consecutive fail streak stamp must survive build_session_response coach_context refresh.

    Shared by /turn(+stream) and /session/message(+stream) — same resolve→build path.
    """
    from tests.test_router_stream_scenarios import completed_stream_response

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Stay with a smaller hint."

    workspace_id = "workspace-turn-streak-stamp-preserve"
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Stay with a smaller hint."),
        ),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        for summary in ("First consecutive miss.", "Same miss again."):
            signaled = client.post(
                "/learning/signal",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "concepts": ["blocked slice"],
                    "outcome": "evaluation",
                    "summary": summary,
                    "action_type": "evaluate_current_file",
                    "focus_area": "blocked slice",
                    "scenario": "review_reflection",
                },
            )
            assert signaled.status_code == 200, signaled.text
        coaching = (signaled.json().get("memory") or {}).get("coaching_adaptation") or {}
        assert int(coaching.get("failure_streak") or 0) >= 2
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        payload: dict[str, object] = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "message": "I failed twice. What should I do next?",
            "response_language": "en-US",
            "use_agent_loop": False,
        }
        if path.startswith("/turn"):
            payload["intent"] = "coach"
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert coach_focus.get("streak_blocks_live_object_mint") is True
        assert isinstance(agent_meta, dict)
        assert agent_meta.get("streak_blocks_live_object_mint") is True
        snapshot = body.get("snapshot") or body
        memory = (snapshot.get("memory") if isinstance(snapshot, dict) else None) or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert (snapshot.get("plan") if isinstance(snapshot, dict) else None) in (None, {})
        assert body.get("plan") in (None, {})
        assert not (body.get("current_task") or body.get("currentTask") or {}).get("title")
        if isinstance(snapshot, dict):
            assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()


def test_explicit_plan_generate_under_high_urgency_still_binds(tmp_path: Path) -> None:
    """Pressure blocks invent on coach turns; explicit /plan/generate must still bind."""
    urgent_probe = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "What should I do next?"
    )
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay thin.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-pressure-explicit-plan",
                "workspace_name": "workspace-pressure-explicit-plan",
                "profile": {
                    "long_term_goal": "Ship token refresh",
                    "weekly_hours": 2,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-pressure-explicit-plan",
                "intent": "coach",
                "message": urgent_probe,
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        turn_body = turn.json()
        adaptation = turn_body["snapshot"]["memory"].get("coaching_adaptation") or {}
        assert adaptation.get("task_urgency") == "high"
        assert adaptation.get("time_budget") == "tight"
        assert turn_body["snapshot"].get("plan") in (None, {})

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-pressure-explicit-plan",
                "objectives": ["Ship token refresh"],
            },
        )
        assert generated.status_code == 200, generated.text
        payload = generated.json()
        plan = payload.get("plan") or payload
        plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
        assert plan_id
        latest = runtime.repository.get_latest_plan("workspace-pressure-explicit-plan")
        assert latest is not None
        assert latest.id == plan_id
        workspace = (payload.get("memory") or {}).get("workspace") or {}
        live_runtime = workspace.get("latest_plan_runtime") or workspace.get("latestPlanRuntime") or {}
        assert str(live_runtime.get("plan_id") or live_runtime.get("planId") or "").strip() == plan_id
        # Fail-closed: pressure must not leave first-screen status unbound while runtime binds.
        status = payload.get("plan_runtime_status") or payload.get("planRuntimeStatus") or {}
        assert str(status.get("plan_id") or status.get("planId") or "").strip() == plan_id
        assert str(plan.get("id") or plan.get("plan_id") or "").strip() == plan_id


def test_explicit_formal_plan_mutation_under_high_urgency_keeps_mutation_flag(
    tmp_path: Path,
) -> None:
    """High urgency must not strip explicit plan intent + formalPlanMutation for save."""
    from unittest.mock import PropertyMock

    from app.core.models import (
        ProviderCapabilityEvidence,
        ProviderConfig,
        ProviderTestResponse,
    )

    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "Generate and save a formal learning plan for token refresh."
    )
    captured: dict[str, object] = {}

    async def capture_agentic(*_args: object, **kwargs: object) -> dict[str, object]:
        coach_context = kwargs.get("coach_context") or {}
        assert isinstance(coach_context, dict)
        captured["formal_plan_mutation"] = coach_context.get("formal_plan_mutation")
        return {
            "content": "Discussed scope; formal save still available.",
            "summary": "Explicit formal plan mutation remains open.",
            "next_step": "Save the formal plan when ready.",
            "stop_reason": "completed",
            "tool_events": [],
            "fell_back": False,
        }

    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-urgency-formal-mutation",
                "workspace_name": "workspace-urgency-formal-mutation",
                "profile": {
                    "long_term_goal": "Ship token refresh",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="test-tool-provider",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.formal-plan-urgency",
            model="test-model",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
        runtime.provider_service = ProviderService(
            config=provider,
            api_key="sk-test-not-a-real-key-aaaaaaaa",
        )
        runtime.provider_service_cache.clear()
        runtime.remember_provider_capability_test(
            provider,
            "sk-test-not-a-real-key-aaaaaaaa",
            ProviderTestResponse(
                ok=True,
                detail="mocked provider capability test",
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="tools",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                ],
                tools_ready=True,
                tool_probe_status="verified",
            ),
        )
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(side_effect=capture_agentic),
            ),
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-urgency-formal-mutation",
                    "intent": "plan",
                    "formalPlanMutation": True,
                    "message": urgent,
                    "use_agent_loop": True,
                    "response_language": "en-US",
                },
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("agent_meta", {}).get("formal_plan_mutation_blocked") is not True
        assert captured.get("formal_plan_mutation") is True
        adaptation = body["snapshot"]["memory"].get("coaching_adaptation") or {}
        assert adaptation.get("task_urgency") == "high"


def test_turn_stream_agent_tools_high_urgency_does_not_invent(tmp_path: Path) -> None:
    """`/turn/stream` ReAct + tools under high urgency: hint-only, no plan/card/task mint."""
    from unittest.mock import PropertyMock

    from app.core.models import (
        ProviderCapabilityEvidence,
        ProviderConfig,
        ProviderTestResponse,
    )
    from tests.test_router_stream_scenarios import completed_stream_response

    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "Create a practice card for debugging a Python traceback in VS Code."
    )
    captured: dict[str, object] = {}

    async def fake_agent_stream(*_args: object, **kwargs: object):
        coach_context = kwargs.get("coach_context") or {}
        assert isinstance(coach_context, dict)
        captured["pressure_blocks_live_object_mint"] = coach_context.get(
            "pressure_blocks_live_object_mint"
        )
        yield {
            "type": "text",
            "delta": "Stay with one thin repair slice.",
            "safe_to_stream": True,
        }
        yield {
            "type": "final",
            "content": "Stay with one thin repair slice.",
            "summary": "Pressure hint-only",
            "next_step": "Shrink to one check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-stream-agent-urgency-no-invent",
                "workspace_name": "workspace-stream-agent-urgency-no-invent",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="test-tool-stream-provider",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.stream-agent-urgency",
            model="test-model",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
        runtime.provider_service = ProviderService(
            config=provider,
            api_key="sk-test-not-a-real-key-aaaaaaaa",
        )
        runtime.provider_service_cache.clear()
        runtime.remember_provider_capability_test(
            provider,
            "sk-test-not-a-real-key-aaaaaaaa",
            ProviderTestResponse(
                ok=True,
                detail="mocked provider capability test",
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="tools",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                ],
                tools_ready=True,
                tool_probe_status="verified",
            ),
        )
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=fake_agent_stream,
            ),
        ):
            response = client.post(
                "/turn/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-stream-agent-urgency-no-invent",
                    "intent": "coach",
                    "message": urgent,
                    "response_language": "en-US",
                    "use_agent_loop": True,
                },
            )
        assert response.status_code == 200, response.text
        body = completed_stream_response(response.text)
        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert captured.get("pressure_blocks_live_object_mint") is True
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert not str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip()
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions if isinstance(item, dict)}
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("task_urgency") == "high"
        assert adaptation.get("next_plan_step") == "shrink"


def test_turn_stream_agent_tools_leftover_not_live_does_not_invent(tmp_path: Path) -> None:
    """Recovered leftover runtime without live plan must not mint under stream+tools pressure."""
    from unittest.mock import PropertyMock

    from app.core.models import (
        ProviderCapabilityEvidence,
        ProviderConfig,
        ProviderTestResponse,
    )
    from app.memory.workspace_recovery import PLAN_RUNTIME_KEY
    from tests.test_router_stream_scenarios import completed_stream_response

    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "Generate a learning plan for the next auth slice."
    )

    async def fake_agent_stream(*_args: object, **_kwargs: object):
        yield {
            "type": "text",
            "delta": "Resume the recovered check only.",
            "safe_to_stream": True,
        }
        yield {
            "type": "final",
            "content": "Resume the recovered check only.",
            "summary": "Leftover not live",
            "next_step": "One thin check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-stream-leftover-no-invent",
                "workspace_name": "workspace-stream-leftover-no-invent",
                "profile": {
                    "long_term_goal": "Ship token refresh",
                    "weekly_hours": 2,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        runtime.memory_service.update_workspace_state(
            "workspace-stream-leftover-no-invent",
            **{
                PLAN_RUNTIME_KEY: {
                    "current_step": "Check token refresh once",
                    "why_now": "Leftover pressure-only runtime",
                    "status": "in_progress",
                }
            },
        )
        provider = ProviderConfig(
            name="test-tool-stream-leftover",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.stream-leftover-urgency",
            model="test-model",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
        runtime.provider_service = ProviderService(
            config=provider,
            api_key="sk-test-not-a-real-key-aaaaaaaa",
        )
        runtime.provider_service_cache.clear()
        runtime.remember_provider_capability_test(
            provider,
            "sk-test-not-a-real-key-aaaaaaaa",
            ProviderTestResponse(
                ok=True,
                detail="mocked provider capability test",
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="tools",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                ],
                tools_ready=True,
                tool_probe_status="verified",
            ),
        )
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=fake_agent_stream,
            ),
        ):
            response = client.post(
                "/turn/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-stream-leftover-no-invent",
                    "intent": "coach",
                    "message": urgent,
                    "response_language": "en-US",
                    "use_agent_loop": True,
                },
            )
        assert response.status_code == 200, response.text
        body = completed_stream_response(response.text)
        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        actions = body.get("suggested_actions") or []
        action_types = {str(item.get("action") or "") for item in actions if isinstance(item, dict)}
        assert "plan" not in action_types
        assert "hint" in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("task_urgency") == "high"


@pytest.mark.parametrize("path", ["/session/message", "/session/message/stream"])
def test_session_message_leftover_not_live_does_not_invent(
    tmp_path: Path,
    path: str,
) -> None:
    """Leftover PLAN_RUNTIME without live plan must not resurrect on /session/message."""
    from app.memory.workspace_recovery import PLAN_RUNTIME_KEY
    from tests.test_router_stream_scenarios import completed_stream_response

    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "Generate a learning plan for the next auth slice."
    )

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Resume the recovered check only."

    with (
        _client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Resume the recovered check only."),
        ),
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-session-leftover-no-invent",
                "workspace_name": "workspace-session-leftover-no-invent",
                "profile": {
                    "long_term_goal": "Ship token refresh",
                    "weekly_hours": 2,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        runtime.memory_service.update_workspace_state(
            "workspace-session-leftover-no-invent",
            **{
                PLAN_RUNTIME_KEY: {
                    "current_step": "Check token refresh once",
                    "why_now": "Leftover pressure-only runtime",
                    "status": "in_progress",
                }
            },
        )
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        response = client.post(
            path,
            json={
                "session_id": session_id,
                "workspace_id": "workspace-session-leftover-no-invent",
                "message": urgent,
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )
        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(
            workspace.get("selected_card_id") or workspace.get("selectedCardId") or ""
        ).strip()
        assert not str(
            routing.get("selected_card_id") or routing.get("selectedCardId") or ""
        ).strip()
        actions = body.get("suggested_actions") or []
        action_types = {
            str(item.get("action") or "") for item in actions if isinstance(item, dict)
        }
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        coach_turn = body.get("coach_turn") or {}
        assert coach_turn.get("active_task") in (None, "")
        assert "Check token refresh once" not in str(coach_turn.get("active_task") or "")
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("task_urgency") == "high"


@pytest.mark.parametrize("path", ["/session/message", "/session/message/stream"])
def test_session_message_repo_formal_plan_leftover_not_live_does_not_resurrect(
    tmp_path: Path,
    path: str,
) -> None:
    """Stored formal LearningPlan with mismatched recovered plan_id stays stored, not live."""
    from app.core.models import LearningPlan, PlanStage
    from app.memory.workspace_recovery import PLAN_RUNTIME_KEY
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = "workspace-session-formal-leftover-no-invent"
    leftover_plan_id = "plan-formal-old"
    recovered_other_plan_id = "plan-runtime-other"
    leftover = LearningPlan(
        id=leftover_plan_id,
        title="Leftover formal auth plan",
        summary="Leftover formal summary of the old stage path",
        current_stage_id="stage-1",
        current_step="Keep one auth check",
        why_now="Leftover formal why",
        stages=[
            PlanStage(
                id="stage-1",
                title="Auth",
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "Generate a learning plan for the next auth slice."
    )

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Resume the recovered check only."

    with (
        _client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Resume the recovered check only."),
        ),
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship token refresh",
                    "weekly_hours": 2,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        runtime.repository.save_plan(workspace_id, leftover)
        runtime.memory_service.update_workspace_state(
            workspace_id,
            **{
                PLAN_RUNTIME_KEY: {
                    "workspace_id": workspace_id,
                    "plan_id": recovered_other_plan_id,
                    "current_step": "Add a token expiry test",
                    "why_now": "Recovered runtime does not match leftover formal",
                    "status": "in_progress",
                }
            },
        )
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        response = client.post(
            path,
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": urgent,
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )
        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        stored = runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.id == leftover_plan_id
        assert stored.title == leftover.title
        actions = body.get("suggested_actions") or []
        action_types = {
            str(item.get("action") or "") for item in actions if isinstance(item, dict)
        }
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("task_urgency") == "high"

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Ship a thin token refresh check"],
                "response_language": "en-US",
            },
        )
        assert generated.status_code == 200, generated.text
        generated_body = generated.json()
        live_plan = generated_body.get("plan") or generated_body.get("snapshot", {}).get("plan")
        assert isinstance(live_plan, dict)
        new_plan_id = str(live_plan.get("id") or live_plan.get("plan_id") or "").strip()
        assert new_plan_id
        assert new_plan_id != leftover_plan_id
        assert new_plan_id != recovered_other_plan_id
        bound = runtime.memory_service.recover_workspace_facts(workspace_id).get(
            PLAN_RUNTIME_KEY
        ) or {}
        assert str(bound.get("plan_id") or "").strip() == new_plan_id


@pytest.mark.parametrize("path", ["/session/message", "/session/message/stream"])
def test_session_message_agent_tools_leftover_not_live_does_not_invent(
    tmp_path: Path,
    path: str,
) -> None:
    """`/session/message` (+ stream) ReAct + tools + leftover-not-live: hint-only, no invent."""
    from unittest.mock import PropertyMock

    from app.core.models import (
        ProviderCapabilityEvidence,
        ProviderConfig,
        ProviderTestResponse,
    )
    from app.memory.workspace_recovery import PLAN_RUNTIME_KEY
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = "workspace-session-agent-leftover-no-invent"
    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "Generate a learning plan for the next auth slice."
    )

    async def fake_agent(*_args: object, **_kwargs: object):
        return {
            "content": "Resume the recovered check only.",
            "summary": "Leftover not live",
            "next_step": "One thin check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    async def fake_agent_stream(*_args: object, **_kwargs: object):
        yield {
            "type": "text",
            "delta": "Resume the recovered check only.",
            "safe_to_stream": True,
        }
        yield {
            "type": "final",
            "content": "Resume the recovered check only.",
            "summary": "Leftover not live",
            "next_step": "One thin check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship token refresh",
                    "weekly_hours": 2,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        runtime.memory_service.update_workspace_state(
            workspace_id,
            **{
                PLAN_RUNTIME_KEY: {
                    "workspace_id": workspace_id,
                    "current_step": "Check token refresh once",
                    "why_now": "Leftover pressure-only runtime",
                    "status": "in_progress",
                }
            },
        )
        provider = ProviderConfig(
            name="test-tool-session-leftover",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.session-leftover-urgency",
            model="test-model",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
        runtime.provider_service = ProviderService(
            config=provider,
            api_key="sk-test-not-a-real-key-aaaaaaaa",
        )
        runtime.provider_service_cache.clear()
        runtime.remember_provider_capability_test(
            provider,
            "sk-test-not-a-real-key-aaaaaaaa",
            ProviderTestResponse(
                ok=True,
                detail="mocked provider capability test",
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="tools",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                ],
                tools_ready=True,
                tool_probe_status="verified",
            ),
        )
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(side_effect=fake_agent),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=fake_agent_stream,
            ),
        ):
            response = client.post(
                path,
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "message": urgent,
                    "response_language": "en-US",
                    "use_agent_loop": True,
                },
            )
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )
        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        actions = body.get("suggested_actions") or []
        action_types = {
            str(item.get("action") or "") for item in actions if isinstance(item, dict)
        }
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
        adaptation = memory.get("coaching_adaptation") or {}
        assert adaptation.get("task_urgency") == "high"
        agent_meta = body.get("agent_meta") or {}
        assert agent_meta.get("agentic") is True


@pytest.mark.parametrize("path", ["/session/message", "/session/message/stream"])
def test_session_message_agent_tools_streak_does_not_invent(
    tmp_path: Path,
    path: str,
) -> None:
    """Consecutive-fail streak + ReAct tools ON: stamp stays; mint tools denied; no invent.

    Fail-closed already via denied_tool_names / _task_mint_tool_allowed — this proves
    /session/message(+stream) wires the streak stamp into the agentic path.
    """
    from unittest.mock import PropertyMock

    from app.core.models import (
        ProviderCapabilityEvidence,
        ProviderConfig,
        ProviderTestResponse,
    )
    from app.llm.provider_service import _build_agent_tool_context_extra
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = "workspace-session-agent-streak-no-invent"
    captured: dict[str, object] = {}

    async def fake_agent(*_args: object, **kwargs: object):
        coach_context = kwargs.get("coach_context") or {}
        assert isinstance(coach_context, dict)
        captured["streak_blocks_live_object_mint"] = coach_context.get(
            "streak_blocks_live_object_mint"
        )
        captured["coach_context"] = dict(coach_context)
        return {
            "content": "Stay with a smaller hint after the streak.",
            "summary": "Streak hint-only",
            "next_step": "One thinner check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    async def fake_agent_stream(*_args: object, **kwargs: object):
        coach_context = kwargs.get("coach_context") or {}
        assert isinstance(coach_context, dict)
        captured["streak_blocks_live_object_mint"] = coach_context.get(
            "streak_blocks_live_object_mint"
        )
        captured["coach_context"] = dict(coach_context)
        yield {
            "type": "text",
            "delta": "Stay with a smaller hint after the streak.",
            "safe_to_stream": True,
        }
        yield {
            "type": "final",
            "content": "Stay with a smaller hint after the streak.",
            "summary": "Streak hint-only",
            "next_step": "One thinner check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        for summary in ("First consecutive miss.", "Same miss again."):
            signaled = client.post(
                "/learning/signal",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "concepts": ["blocked slice"],
                    "outcome": "evaluation",
                    "summary": summary,
                    "action_type": "evaluate_current_file",
                    "focus_area": "blocked slice",
                    "scenario": "review_reflection",
                },
            )
            assert signaled.status_code == 200, signaled.text
        coaching = (signaled.json().get("memory") or {}).get("coaching_adaptation") or {}
        assert int(coaching.get("failure_streak") or 0) >= 2

        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="test-tool-session-streak",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.session-streak-tools",
            model="test-model",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
        runtime.provider_service = ProviderService(
            config=provider,
            api_key="sk-test-not-a-real-key-aaaaaaaa",
        )
        runtime.provider_service_cache.clear()
        runtime.remember_provider_capability_test(
            provider,
            "sk-test-not-a-real-key-aaaaaaaa",
            ProviderTestResponse(
                ok=True,
                detail="mocked provider capability test",
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="tools",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                ],
                tools_ready=True,
                tool_probe_status="verified",
            ),
        )
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(side_effect=fake_agent),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=fake_agent_stream,
            ),
        ):
            response = client.post(
                path,
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "message": (
                        "I failed twice. Create a practice card and give me the next task."
                    ),
                    "response_language": "en-US",
                    "use_agent_loop": True,
                },
            )
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )

        assert captured.get("streak_blocks_live_object_mint") is True
        coach_context = captured.get("coach_context")
        assert isinstance(coach_context, dict)
        extra = _build_agent_tool_context_extra(
            coach_context=coach_context,
            attachment_delivery={"attachments_present": False},
            answer_mode="guided",
            current_file=None,
            learner_message=(
                "I failed twice. Create a practice card and give me the next task."
            ),
        )
        denied = extra.get("denied_tool_names") or []
        assert "generate_training_card" in denied
        assert "specify_task" in denied
        assert "next_task" in denied
        assert "inspect_current_file" not in denied
        assert "inspect_plan" not in denied

        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or {}
        assert coach_focus.get("streak_blocks_live_object_mint") is True
        assert agent_meta.get("streak_blocks_live_object_mint") is True
        assert agent_meta.get("agentic") is True

        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(
            workspace.get("selected_card_id") or workspace.get("selectedCardId") or ""
        ).strip()
        assert not str(
            routing.get("selected_card_id") or routing.get("selectedCardId") or ""
        ).strip()
        actions = body.get("suggested_actions") or []
        action_types = {
            str(item.get("action") or "") for item in actions if isinstance(item, dict)
        }
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types


@pytest.mark.parametrize("path", ["/turn", "/turn/stream"])
def test_turn_agent_tools_streak_does_not_invent(
    tmp_path: Path,
    path: str,
) -> None:
    """Consecutive-fail streak + ReAct tools ON: stamp stays; mint tools denied; no invent.

    Fail-closed already via denied_tool_names / _task_mint_tool_allowed — this proves
    /turn(+stream) wires the streak stamp into the agentic path (session/message sibling).
    """
    from unittest.mock import PropertyMock

    from app.core.models import (
        ProviderCapabilityEvidence,
        ProviderConfig,
        ProviderTestResponse,
    )
    from app.llm.provider_service import _build_agent_tool_context_extra
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = "workspace-turn-agent-streak-no-invent"
    captured: dict[str, object] = {}

    async def fake_agent(*_args: object, **kwargs: object):
        coach_context = kwargs.get("coach_context") or {}
        assert isinstance(coach_context, dict)
        captured["streak_blocks_live_object_mint"] = coach_context.get(
            "streak_blocks_live_object_mint"
        )
        captured["coach_context"] = dict(coach_context)
        return {
            "content": "Stay with a smaller hint after the streak.",
            "summary": "Streak hint-only",
            "next_step": "One thinner check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    async def fake_agent_stream(*_args: object, **kwargs: object):
        coach_context = kwargs.get("coach_context") or {}
        assert isinstance(coach_context, dict)
        captured["streak_blocks_live_object_mint"] = coach_context.get(
            "streak_blocks_live_object_mint"
        )
        captured["coach_context"] = dict(coach_context)
        yield {
            "type": "text",
            "delta": "Stay with a smaller hint after the streak.",
            "safe_to_stream": True,
        }
        yield {
            "type": "final",
            "content": "Stay with a smaller hint after the streak.",
            "summary": "Streak hint-only",
            "next_step": "One thinner check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        for summary in ("First consecutive miss.", "Same miss again."):
            signaled = client.post(
                "/learning/signal",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "concepts": ["blocked slice"],
                    "outcome": "evaluation",
                    "summary": summary,
                    "action_type": "evaluate_current_file",
                    "focus_area": "blocked slice",
                    "scenario": "review_reflection",
                },
            )
            assert signaled.status_code == 200, signaled.text
        coaching = (signaled.json().get("memory") or {}).get("coaching_adaptation") or {}
        assert int(coaching.get("failure_streak") or 0) >= 2

        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="test-tool-turn-streak",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.turn-streak-tools",
            model="test-model",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
        runtime.provider_service = ProviderService(
            config=provider,
            api_key="sk-test-not-a-real-key-aaaaaaaa",
        )
        runtime.provider_service_cache.clear()
        runtime.remember_provider_capability_test(
            provider,
            "sk-test-not-a-real-key-aaaaaaaa",
            ProviderTestResponse(
                ok=True,
                detail="mocked provider capability test",
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="tools",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    ),
                ],
                tools_ready=True,
                tool_probe_status="verified",
            ),
        )
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(side_effect=fake_agent),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=fake_agent_stream,
            ),
        ):
            response = client.post(
                path,
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "coach",
                    "message": (
                        "I failed twice. Create a practice card and give me the next task."
                    ),
                    "response_language": "en-US",
                    "use_agent_loop": True,
                },
            )
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )

        assert captured.get("streak_blocks_live_object_mint") is True
        coach_context = captured.get("coach_context")
        assert isinstance(coach_context, dict)
        extra = _build_agent_tool_context_extra(
            coach_context=coach_context,
            attachment_delivery={"attachments_present": False},
            answer_mode="guided",
            current_file=None,
            learner_message=(
                "I failed twice. Create a practice card and give me the next task."
            ),
        )
        denied = extra.get("denied_tool_names") or []
        assert "generate_training_card" in denied
        assert "specify_task" in denied
        assert "next_task" in denied
        assert "inspect_current_file" not in denied
        assert "inspect_plan" not in denied

        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        agent_meta = body.get("agent_meta") or {}
        assert coach_focus.get("streak_blocks_live_object_mint") is True
        assert agent_meta.get("streak_blocks_live_object_mint") is True
        assert agent_meta.get("agentic") is True

        snapshot = body.get("snapshot") or {}
        memory = snapshot.get("memory") or {}
        workspace = memory.get("workspace") or {}
        routing = memory.get("active_training_card_routing") or {}
        assert snapshot.get("plan") in (None, {})
        assert snapshot.get("current_task") in (None, {})
        assert not str(
            workspace.get("selected_card_id") or workspace.get("selectedCardId") or ""
        ).strip()
        assert not str(
            routing.get("selected_card_id") or routing.get("selectedCardId") or ""
        ).strip()
        actions = body.get("suggested_actions") or []
        action_types = {
            str(item.get("action") or "") for item in actions if isinstance(item, dict)
        }
        assert "plan" not in action_types
        assert "task" not in action_types
        assert "next_task" not in action_types
        assert "hint" in action_types
