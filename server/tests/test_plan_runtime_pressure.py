from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.api import routers as routers_mod
from app.core.models import EvidenceItem, LearningPlan, PlanStage, ProviderConfig
from app.core.settings import AppSettings
from app.db.repository import TrainerRepository
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.memory.service import MemoryService
from app.memory.workspace_recovery import (
    PLAN_RUNTIME_KEY,
    select_plan_runtime_for_pressure,
)
from app.pedagogy.context_pressure import derive_context_pressure
from app.pedagogy.evidence_controls import resolve_pedagogy_controls

FORMAL_NEXT_WHY = "Expiry cases still skip the refresh path."
FORMAL_NEXT_BLOCK = "Refresh still fails after expiry."
FORMAL_NEXT_VERIFY = ["Run the expiry refresh check"]


def _plan_with_formal_next(plan: LearningPlan) -> SimpleNamespace:
    return SimpleNamespace(
        id=plan.id,
        plan_id=getattr(plan, "plan_id", None),
        current_stage_id=plan.current_stage_id,
        current_step=plan.current_step,
        why_now=plan.why_now,
        verify_method=list(plan.verify_method),
        blocked_reason=plan.blocked_reason,
        next_after_current=plan.next_after_current,
        frozen=plan.frozen,
        stages=plan.stages,
        next_why_now=FORMAL_NEXT_WHY,
        next_blocked_reason=FORMAL_NEXT_BLOCK,
        next_verify_method=list(FORMAL_NEXT_VERIFY),
    )


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Plan Runtime Pressure",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-plan-runtime-pressure.db",
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
    seed_verified_capabilities(
        runtime,
        provider,
        "sk-test-not-a-real-key-aaaaaaaa",
        tools=False,
    )
    return TestClient(app)


def test_hydrate_plan_runtime_without_repo_plan_drives_pressure(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-plan-runtime-pressure.db"
    service = MemoryService(TrainerRepository(db_path))
    workspace_id = "workspace-plan-runtime-a"
    persisted = service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Keep one auth check",
            "blocked_reason": "The auth guard still fails on expired tokens.",
        },
    )
    assert persisted is not None
    assert service.repository.get_latest_plan(workspace_id) is None

    restarted = MemoryService(TrainerRepository(db_path))
    assert restarted.repository.get_latest_plan(workspace_id) is None
    snapshot = restarted.snapshot(workspace_id)
    assert snapshot.active_plan is None
    runtime = snapshot.workspace.get(PLAN_RUNTIME_KEY)
    assert runtime is not None
    assert runtime["workspace_id"] == workspace_id
    assert select_plan_runtime_for_pressure(runtime, workspace_id) is not None
    pressure = derive_context_pressure(
        workspace=snapshot.workspace,
        plan=snapshot.active_plan,
        workspace_id=workspace_id,
    )
    assert pressure.task_urgency == "high"
    controls = resolve_pedagogy_controls(task_urgency=pressure.task_urgency)
    assert controls.next_plan_step == "shrink"
    adaptation = snapshot.coaching_adaptation
    assert adaptation is not None
    assert adaptation.task_urgency == "high"
    assert adaptation.next_plan_step == "shrink"
    assert adaptation.challenge_level != "raise"
    assert adaptation.success_streak == 0
    assert not snapshot.learning_outcomes


def test_current_step_without_blocker_holds_and_does_not_invent_plan(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-plan-runtime-pressure.db"
    service = MemoryService(TrainerRepository(db_path))
    workspace_id = "workspace-plan-runtime-hold"
    service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={"current_step": "Stay on the parser guard"},
    )
    snapshot = MemoryService(TrainerRepository(db_path)).snapshot(workspace_id)
    assert snapshot.active_plan is None
    adaptation = snapshot.coaching_adaptation
    assert adaptation is not None
    assert adaptation.next_plan_step == "hold"
    assert adaptation.task_urgency == "medium"
    assert adaptation.challenge_level != "raise"
    assert adaptation.material_recommendation != "transfer"


def test_incomplete_plan_runtime_is_not_a_generated_plan(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-plan-runtime-pressure.db"
    service = MemoryService(TrainerRepository(db_path))
    workspace_id = "workspace-plan-runtime-stale"
    persisted = service.update_workspace_state(
        workspace_id,
        **{
            PLAN_RUNTIME_KEY: {
                "workspace_id": workspace_id,
                "plan_id": "plan-missing-from-repo",
                "frozen": True,
                "revision": 1,
            }
        },
    )[PLAN_RUNTIME_KEY]
    assert persisted["plan_id"] == "plan-missing-from-repo"
    assert select_plan_runtime_for_pressure(persisted, workspace_id) is None
    snapshot = MemoryService(TrainerRepository(db_path)).snapshot(workspace_id)
    assert snapshot.active_plan is None
    assert service.repository.get_latest_plan(workspace_id) is None
    assert snapshot.coaching_adaptation is None


def test_plan_runtime_switch_isolation(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-plan-runtime-pressure.db"
    service = MemoryService(TrainerRepository(db_path))
    service.persist_plan_runtime_recovery(
        "workspace-plan-runtime-a",
        plan_runtime={
            "current_step": "Keep one auth check",
            "blocked_reason": "The auth guard still fails on expired tokens.",
        },
    )
    other = service.snapshot("workspace-plan-runtime-b")
    assert other.active_plan is None
    assert select_plan_runtime_for_pressure(other.workspace.get(PLAN_RUNTIME_KEY), "workspace-plan-runtime-b") is None
    assert other.coaching_adaptation is None

    leaked = dict(service._structured_for("workspace-plan-runtime-a")._workspace[PLAN_RUNTIME_KEY])
    service._structured_for("workspace-plan-runtime-b").update_workspace(**{PLAN_RUNTIME_KEY: leaked})
    leaked_snapshot = service.snapshot("workspace-plan-runtime-b")
    assert leaked_snapshot.active_plan is None
    assert leaked_snapshot.coaching_adaptation is None


def test_session_start_hydrates_pressure_without_generating_plan(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        runtime = client.app.state.runtime
        runtime.memory_service.persist_plan_runtime_recovery(
            "workspace-plan-runtime-a",
            plan_runtime={
                "current_step": "Keep one auth check",
                "blocked_reason": "The auth guard still fails on expired tokens.",
                "why_now": "Expired tokens still leak the session.",
                "next_after_current": "Return with the focused test.",
                "verify_method": ["Run the focused auth check"],
            },
        )
        assert runtime.repository.get_latest_plan("workspace-plan-runtime-a") is None

    with _client(tmp_path) as restarted:
        hydrate = restarted.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-a",
                "workspace_name": "workspace-plan-runtime-a",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert hydrate.status_code == 200
        payload = hydrate.json()
        assert payload.get("plan") is None
        memory = payload["memory"]
        assert memory.get("active_plan") is None
        status = payload["plan_runtime_status"]
        assert status is not None
        assert status["recovered"] is True
        assert status["current_step"] == "Keep one auth check"
        assert status["blocked_reason"] == "The auth guard still fails on expired tokens."
        assert status["why_now"] == "Expired tokens still leak the session."
        assert status["next_after_current"] == "Return with the focused test."
        assert status["current_stage"] is None
        assert not status.get("stages")
        adaptation = memory["coaching_adaptation"]
        assert adaptation is not None
        assert adaptation["task_urgency"] == "high"
        assert adaptation["next_plan_step"] == "shrink"
        assert adaptation["success_streak"] == 0
        switch = restarted.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-b",
                "workspace_name": "workspace-plan-runtime-b",
                "profile": {
                    "long_term_goal": "Other project",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert switch.status_code == 200
        other = switch.json()
        assert other.get("plan") is None
        assert other["memory"].get("coaching_adaptation") is None
        assert not other["memory"]["workspace"].get(PLAN_RUNTIME_KEY)
        other_status = other.get("plan_runtime_status") or {}
        assert other_status.get("recovered") is not True
        assert not other_status.get("current_step")
        assert not other_status.get("blocked_reason")


def test_incomplete_runtime_does_not_attach_ready_plan_status(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        runtime = client.app.state.runtime
        runtime.memory_service.update_workspace_state(
            "workspace-plan-runtime-stale",
            **{
                PLAN_RUNTIME_KEY: {
                    "workspace_id": "workspace-plan-runtime-stale",
                    "plan_id": "plan-missing-from-repo",
                    "frozen": True,
                    "revision": 1,
                }
            },
        )
        hydrate = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-stale",
                "workspace_name": "workspace-plan-runtime-stale",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert hydrate.status_code == 200
        payload = hydrate.json()
        assert payload.get("plan") is None
        status = payload.get("plan_runtime_status") or {}
        assert status.get("recovered") is not True
        assert not status.get("current_step")
        assert not status.get("blocked_reason")
        assert status.get("current_stage") is None


def test_turn_resume_continue_step_uses_recovered_runtime_without_generating_plan(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def fake_reply(
        self: ProviderService,
        profile: object,
        message: str,
        *args: object,
        coach_context: dict[str, object] | None = None,
        **kwargs: object,
    ) -> str:
        captured["message"] = message
        captured["coach_context"] = coach_context
        return "Stay on the recovered auth check. Next I would invent: Add a token expiry test."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=fake_reply),
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("recovered resume must not generate a plan"),
        ),
    ):
        runtime = client.app.state.runtime
        runtime.memory_service.persist_plan_runtime_recovery(
            "workspace-plan-runtime-a",
            plan_runtime={
                "current_step": "Keep one auth check",
                "current_stage": {"id": "step-auth-1"},
                "why_now": "Expired tokens still leak the session.",
            },
        )
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-a",
                "workspace_name": "workspace-plan-runtime-a",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        assert start.json().get("plan") is None
        before = start.json()["plan_runtime_status"]
        assert before["recovered"] is True
        assert before.get("resume_state") != "in_progress"
        turn = client.post(
            "/turn",
            json={
                "session_id": start.json()["session_id"],
                "workspace_id": "workspace-plan-runtime-a",
                "intent": "plan",
                "formalPlanMutation": False,
                "requestId": "plan-resume-continue-1",
                "message": "Continue this step: Keep one auth check. Why now: Expired tokens still leak the session.",
                "response_language": "en-US",
                "planRuntimeRecovery": {
                    "action": "continue_step",
                    "recovered": True,
                    "formalPlanMutation": False,
                    "currentStep": "Keep one auth check",
                    "currentStepId": "step-auth-1",
                    "whyNow": "Expired tokens still leak the session.",
                },
            },
        )
        assert turn.status_code == 200, turn.text
        payload = turn.json()
        assert payload.get("plan") is None
        assert payload["snapshot"].get("plan") is None
        recovery = captured["coach_context"]["plan_runtime_recovery"]
        assert recovery["action"] == "continue_step"
        assert recovery["current_step"] == "Keep one auth check"
        assert recovery["current_step_id"] == "step-auth-1"
        assert recovery["formal_plan_mutation"] is False
        assert captured["coach_context"].get("formal_plan_mutation") is not True
        assert "Keep one auth check" in str(captured["message"])
        live_status = payload.get("plan_runtime_status") or payload["snapshot"].get("plan_runtime_status")
        assert live_status["resume_state"] == "in_progress"
        assert live_status["request_id"] == "plan-resume-continue-1"
        assert live_status["current_step"] == "Keep one auth check"
        assert live_status.get("recovered") is True
        persisted = runtime.memory_service.recover_workspace_facts("workspace-plan-runtime-a")[
            PLAN_RUNTIME_KEY
        ]
        assert persisted is not None
        assert persisted["request_id"] == "plan-resume-continue-1"
        assert persisted["resume_state"] == "in_progress"
        assert persisted["revision"] > (before.get("revision") or 0)

    with _client(tmp_path) as restarted:
        hydrate = restarted.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-a",
                "workspace_name": "workspace-plan-runtime-a",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert hydrate.status_code == 200
        after = hydrate.json()["plan_runtime_status"]
        assert hydrate.json().get("plan") is None
        assert after["recovered"] is True
        assert after["resume_state"] == "in_progress"
        assert after["request_id"] == "plan-resume-continue-1"
        assert after["current_step"] == "Keep one auth check"
        assert after.get("resume_state") != before.get("resume_state")
        switch = restarted.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-b",
                "workspace_name": "workspace-plan-runtime-b",
                "profile": {
                    "long_term_goal": "Other project",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert switch.status_code == 200
        other = switch.json().get("plan_runtime_status") or {}
        assert other.get("resume_state") != "in_progress"
        assert other.get("request_id") != "plan-resume-continue-1"
        assert switch.json().get("plan") is None


def test_turn_resume_clear_blocker_uses_recovered_blocker_without_generating_plan(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def fake_reply(
        self: ProviderService,
        profile: object,
        message: str,
        *args: object,
        coach_context: dict[str, object] | None = None,
        **kwargs: object,
    ) -> str:
        captured["coach_context"] = coach_context
        return "Clear the recovered blocker first."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=fake_reply),
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("recovered resume must not generate a plan"),
        ),
    ):
        runtime = client.app.state.runtime
        runtime.memory_service.persist_plan_runtime_recovery(
            "workspace-plan-runtime-a",
            plan_runtime={
                "current_step": "Keep one auth check",
                "blocked_reason": "The auth guard still fails on expired tokens.",
            },
        )
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-a",
                "workspace_name": "workspace-plan-runtime-a",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        turn = client.post(
            "/turn",
            json={
                "session_id": start.json()["session_id"],
                "workspace_id": "workspace-plan-runtime-a",
                "intent": "plan",
                "formalPlanMutation": False,
                "requestId": "plan-resume-blocker-1",
                "message": "Help me clear this blocker: The auth guard still fails on expired tokens.",
                "response_language": "en-US",
                "planRuntimeRecovery": {
                    "action": "clear_blocker",
                    "recovered": True,
                    "formalPlanMutation": False,
                    "blockedReason": "The auth guard still fails on expired tokens.",
                    "currentStep": "Keep one auth check",
                },
            },
        )
        assert turn.status_code == 200, turn.text
        assert turn.json().get("plan") is None
        recovery = captured["coach_context"]["plan_runtime_recovery"]
        assert recovery["action"] == "clear_blocker"
        assert recovery["blocked_reason"] == "The auth guard still fails on expired tokens."
        assert recovery["formal_plan_mutation"] is False
        status = turn.json().get("plan_runtime_status") or turn.json()["snapshot"].get(
            "plan_runtime_status"
        )
        assert status["resume_state"] == "in_progress"
        assert status["request_id"] == "plan-resume-blocker-1"
        assert status["blocked_reason"] == "The auth guard still fails on expired tokens."
        assert turn.json().get("plan") is None


def test_turn_resume_without_recovered_runtime_does_not_invent_plan(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def fake_reply(
        self: ProviderService,
        profile: object,
        message: str,
        *args: object,
        coach_context: dict[str, object] | None = None,
        **kwargs: object,
    ) -> str:
        captured["coach_context"] = coach_context
        return "Stay in setup."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=fake_reply),
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("missing runtime must not generate a plan"),
        ),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-empty",
                "workspace_name": "workspace-plan-runtime-empty",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        assert start.json().get("plan") is None
        turn = client.post(
            "/turn",
            json={
                "session_id": start.json()["session_id"],
                "workspace_id": "workspace-plan-runtime-empty",
                "intent": "plan",
                "formalPlanMutation": False,
                "message": "Continue this step: Invented theater step.",
                "response_language": "en-US",
                "planRuntimeRecovery": {
                    "action": "continue_step",
                    "recovered": True,
                    "formalPlanMutation": False,
                    "currentStep": "Invented theater step",
                },
            },
        )
        assert turn.status_code == 200, turn.text
        payload = turn.json()
        assert payload.get("plan") is None
        assert payload["snapshot"].get("plan") is None
        context = captured.get("coach_context") or {}
        assert not context.get("plan_runtime_recovery")
        assert context.get("formal_plan_mutation") is not True
        empty_status = payload.get("plan_runtime_status") or payload["snapshot"].get(
            "plan_runtime_status"
        ) or {}
        assert empty_status.get("resume_state") != "in_progress"
        assert client.app.state.runtime.memory_service.recover_workspace_facts(
            "workspace-plan-runtime-empty"
        ).get(PLAN_RUNTIME_KEY) is None


def test_failed_resume_turn_does_not_mark_step_resumed(tmp_path: Path) -> None:
    async def empty_reply(*args: object, **kwargs: object) -> str:
        return ""

    with _client(tmp_path) as client:
        runtime = client.app.state.runtime
        runtime.memory_service.persist_plan_runtime_recovery(
            "workspace-plan-runtime-fail",
            plan_runtime={"current_step": "Keep one auth check"},
        )
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-fail",
                "workspace_name": "workspace-plan-runtime-fail",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        before = start.json()["plan_runtime_status"]
        assert before["recovered"] is True
        assert before.get("resume_state") != "in_progress"
        with patch.object(ProviderService, "coaching_reply", new=empty_reply):
            turn = client.post(
                "/turn",
                json={
                    "session_id": start.json()["session_id"],
                    "workspace_id": "workspace-plan-runtime-fail",
                    "intent": "plan",
                    "formalPlanMutation": False,
                    "requestId": "plan-resume-failed-1",
                    "message": "Continue this step: Keep one auth check.",
                    "response_language": "en-US",
                    "planRuntimeRecovery": {
                        "action": "continue_step",
                        "recovered": True,
                        "formalPlanMutation": False,
                        "currentStep": "Keep one auth check",
                    },
                },
            )
        assert turn.status_code == 200, turn.text
        persisted = runtime.memory_service.recover_workspace_facts("workspace-plan-runtime-fail")[
            PLAN_RUNTIME_KEY
        ]
        assert persisted is not None
        assert persisted.get("resume_state") != "in_progress"
        assert persisted.get("request_id") != "plan-resume-failed-1"

    with _client(tmp_path) as restarted:
        hydrate = restarted.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-fail",
                "workspace_name": "workspace-plan-runtime-fail",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert hydrate.status_code == 200
        status = hydrate.json()["plan_runtime_status"]
        assert hydrate.json().get("plan") is None
        assert status["recovered"] is True
        assert status["current_step"] == "Keep one auth check"
        assert status.get("resume_state") != "in_progress"
        assert status.get("request_id") != "plan-resume-failed-1"


def test_turn_resume_structured_reply_facts_update_runtime_without_generating_plan(
    tmp_path: Path,
) -> None:
    async def fake_reply(*args: object, **kwargs: object) -> str:
        return "Stay on the recovered auth check."

    structured_facts = {
        "current_step": "Add a token expiry test",
        "blocked_reason": "Token refresh still returns 401.",
        "why_now": "Expired tokens still leak the session.",
        "next_after_current": "Wire the guard into the login path.",
    }

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=fake_reply),
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("structured resume facts must not generate a plan"),
        ),
        patch.object(
            routers_mod,
            "extract_structured_plan_runtime_facts",
            return_value=structured_facts,
        ),
    ):
        runtime = client.app.state.runtime
        runtime.memory_service.persist_plan_runtime_recovery(
            "workspace-plan-runtime-a",
            plan_runtime={
                "current_step": "Keep one auth check",
                "current_stage": {"id": "step-auth-1"},
                "why_now": "Expired tokens still leak the session.",
                "next_after_current": "Return with the focused test.",
            },
        )
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-a",
                "workspace_name": "workspace-plan-runtime-a",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        turn = client.post(
            "/turn",
            json={
                "session_id": start.json()["session_id"],
                "workspace_id": "workspace-plan-runtime-a",
                "intent": "plan",
                "formalPlanMutation": False,
                "requestId": "plan-resume-facts-1",
                "message": "Continue this step: Keep one auth check. Why now: Expired tokens still leak the session.",
                "response_language": "en-US",
                "planRuntimeRecovery": {
                    "action": "continue_step",
                    "recovered": True,
                    "formalPlanMutation": False,
                    "currentStep": "Keep one auth check",
                    "currentStepId": "step-auth-1",
                    "whyNow": "Expired tokens still leak the session.",
                },
            },
        )
        assert turn.status_code == 200, turn.text
        payload = turn.json()
        assert payload.get("plan") is None
        live_status = payload.get("plan_runtime_status") or payload["snapshot"].get(
            "plan_runtime_status"
        )
        assert live_status["resume_state"] == "in_progress"
        assert live_status["current_step"] == "Add a token expiry test"
        assert live_status["blocked_reason"] == "Token refresh still returns 401."
        assert live_status["why_now"] == "Expired tokens still leak the session."
        assert live_status["next_after_current"] == "Wire the guard into the login path."
        persisted = runtime.memory_service.recover_workspace_facts("workspace-plan-runtime-a")[
            PLAN_RUNTIME_KEY
        ]
        assert persisted["current_step"] == "Add a token expiry test"
        assert persisted["blocked_reason"] == "Token refresh still returns 401."
        assert persisted["next_after_current"] == "Wire the guard into the login path."
        assert persisted.get("plan_id") in {None, ""}

    with _client(tmp_path) as restarted:
        hydrate = restarted.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-a",
                "workspace_name": "workspace-plan-runtime-a",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert hydrate.status_code == 200
        after = hydrate.json()["plan_runtime_status"]
        assert hydrate.json().get("plan") is None
        assert after["recovered"] is True
        assert after["resume_state"] == "in_progress"
        assert after["current_step"] == "Add a token expiry test"
        assert after["blocked_reason"] == "Token refresh still returns 401."
        assert after["next_after_current"] == "Wire the guard into the login path."
        switch = restarted.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-b",
                "workspace_name": "workspace-plan-runtime-b",
                "profile": {
                    "long_term_goal": "Other project",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert switch.status_code == 200
        other = switch.json().get("plan_runtime_status") or {}
        assert other.get("current_step") != "Add a token expiry test"
        assert other.get("blocked_reason") != "Token refresh still returns 401."
        assert switch.json().get("plan") is None


def test_failed_resume_turn_does_not_write_structured_reply_facts(tmp_path: Path) -> None:
    async def empty_reply(*args: object, **kwargs: object) -> str:
        return ""

    with (
        _client(tmp_path) as client,
        patch.object(
            routers_mod,
            "extract_structured_plan_runtime_facts",
            return_value={
                "current_step": "Add a token expiry test",
                "blocked_reason": "Token refresh still returns 401.",
            },
        ),
    ):
        runtime = client.app.state.runtime
        runtime.memory_service.persist_plan_runtime_recovery(
            "workspace-plan-runtime-fail-facts",
            plan_runtime={"current_step": "Keep one auth check"},
        )
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-fail-facts",
                "workspace_name": "workspace-plan-runtime-fail-facts",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        with patch.object(ProviderService, "coaching_reply", new=empty_reply):
            turn = client.post(
                "/turn",
                json={
                    "session_id": start.json()["session_id"],
                    "workspace_id": "workspace-plan-runtime-fail-facts",
                    "intent": "plan",
                    "formalPlanMutation": False,
                    "requestId": "plan-resume-failed-facts-1",
                    "message": "Continue this step: Keep one auth check.",
                    "response_language": "en-US",
                    "planRuntimeRecovery": {
                        "action": "continue_step",
                        "recovered": True,
                        "formalPlanMutation": False,
                        "currentStep": "Keep one auth check",
                    },
                },
            )
        assert turn.status_code == 200, turn.text
        persisted = runtime.memory_service.recover_workspace_facts(
            "workspace-plan-runtime-fail-facts"
        )[PLAN_RUNTIME_KEY]
        assert persisted["current_step"] == "Keep one auth check"
        assert persisted.get("blocked_reason") in {None, ""}
        assert persisted.get("resume_state") != "in_progress"
        assert persisted.get("request_id") != "plan-resume-failed-facts-1"


def test_in_progress_runtime_accepts_structured_reply_facts_without_generating_plan(
    tmp_path: Path,
) -> None:
    async def fake_reply(*args: object, **kwargs: object) -> str:
        return "Stay on the recovered auth check."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=fake_reply),
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("in-progress plan turn must not generate a plan"),
        ),
    ):
        runtime = client.app.state.runtime
        runtime.memory_service.persist_plan_runtime_recovery(
            "workspace-plan-runtime-follow",
            plan_runtime={
                "current_step": "Keep one auth check",
                "why_now": "Expired tokens still leak the session.",
            },
        )
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-follow",
                "workspace_name": "workspace-plan-runtime-follow",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        first = client.post(
            "/turn",
            json={
                "session_id": start.json()["session_id"],
                "workspace_id": "workspace-plan-runtime-follow",
                "intent": "plan",
                "formalPlanMutation": False,
                "requestId": "plan-resume-follow-1",
                "message": "Continue this step: Keep one auth check. Why now: Expired tokens still leak the session.",
                "response_language": "en-US",
                "planRuntimeRecovery": {
                    "action": "continue_step",
                    "recovered": True,
                    "formalPlanMutation": False,
                    "currentStep": "Keep one auth check",
                    "whyNow": "Expired tokens still leak the session.",
                },
            },
        )
        assert first.status_code == 200, first.text
        first_status = first.json().get("plan_runtime_status") or first.json()["snapshot"].get(
            "plan_runtime_status"
        )
        assert first_status["resume_state"] == "in_progress"
        assert first_status["current_step"] == "Keep one auth check"
        updated = runtime.memory_service.persist_plan_runtime_resume(
            "workspace-plan-runtime-follow",
            accepted={
                "action": "continue_step",
                "recovered": True,
                "current_step": "Keep one auth check",
                "why_now": "Expired tokens still leak the session.",
                "formal_plan_mutation": False,
            },
            request_id="plan-resume-follow-2",
            reply_facts={
                "current_step": "Add a token expiry test",
                "next_after_current": "Wire the guard into the login path.",
            },
        )
        assert updated is not None
        assert updated["current_step"] == "Add a token expiry test"
        assert updated.get("plan_id") in {None, ""}

    with _client(tmp_path) as restarted:
        hydrate = restarted.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-follow",
                "workspace_name": "workspace-plan-runtime-follow",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert hydrate.status_code == 200
        after = hydrate.json()["plan_runtime_status"]
        assert hydrate.json().get("plan") is None
        assert after["recovered"] is True
        assert after["resume_state"] == "in_progress"
        assert after["request_id"] == "plan-resume-follow-2"
        assert after["current_step"] == "Add a token expiry test"
        assert after["next_after_current"] == "Wire the guard into the login path."
        assert after["why_now"] == "Expired tokens still leak the session."


def test_structured_finish_leaves_in_progress_and_persists_verify_method(
    tmp_path: Path,
) -> None:
    async def fake_reply(*args: object, **kwargs: object) -> str:
        return "The recovered auth check is ready to verify."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=fake_reply),
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("finished resume must not generate a plan"),
        ),
        patch.object(
            routers_mod,
            "extract_structured_plan_runtime_facts",
            return_value={
                "current_step": "Keep one auth check",
                "why_now": "Expired tokens still leak the session.",
                "verify_method": ["Run the focused auth check"],
                "resume_state": "waiting",
            },
        ),
    ):
        runtime = client.app.state.runtime
        runtime.memory_service.persist_plan_runtime_recovery(
            "workspace-plan-runtime-finish",
            plan_runtime={
                "current_step": "Keep one auth check",
                "why_now": "Expired tokens still leak the session.",
            },
        )
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-finish",
                "workspace_name": "workspace-plan-runtime-finish",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        turn = client.post(
            "/turn",
            json={
                "session_id": start.json()["session_id"],
                "workspace_id": "workspace-plan-runtime-finish",
                "intent": "plan",
                "formalPlanMutation": False,
                "requestId": "plan-resume-finished-1",
                "message": "Continue this step: Keep one auth check. Why now: Expired tokens still leak the session.",
                "response_language": "en-US",
                "planRuntimeRecovery": {
                    "action": "continue_step",
                    "recovered": True,
                    "formalPlanMutation": False,
                    "currentStep": "Keep one auth check",
                    "whyNow": "Expired tokens still leak the session.",
                },
            },
        )
        assert turn.status_code == 200, turn.text
        payload = turn.json()
        assert payload.get("plan") is None
        live_status = payload.get("plan_runtime_status") or payload["snapshot"].get(
            "plan_runtime_status"
        )
        assert live_status["resume_state"] == "waiting"
        assert live_status["resume_state"] != "in_progress"
        assert live_status["verify_method"] == ["Run the focused auth check"]
        persisted = runtime.memory_service.recover_workspace_facts(
            "workspace-plan-runtime-finish"
        )[PLAN_RUNTIME_KEY]
        assert persisted["resume_state"] == "waiting"
        assert persisted["verify_method"] == ["Run the focused auth check"]
        assert persisted.get("plan_id") in {None, ""}
        pending = runtime.memory_service.evidence_queue("workspace-plan-runtime-finish").pending
        assert len(pending) == 1
        assert pending[0].summary == "Run the focused auth check"
        assert pending[0].concepts == ["Keep one auth check"]
        assert pending[0].verified is False
        assert pending[0].adopted is False
        assert persisted["evidence_binding"] == pending[0].id
        memory = payload.get("memory") or payload["snapshot"]["memory"]
        assert len(memory["evidence_queue"]["pending"]) == 1

    with _client(tmp_path) as restarted:
        hydrate = restarted.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-finish",
                "workspace_name": "workspace-plan-runtime-finish",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert hydrate.status_code == 200
        after = hydrate.json()["plan_runtime_status"]
        assert hydrate.json().get("plan") is None
        assert after["recovered"] is True
        assert after["resume_state"] == "waiting"
        assert after["resume_state"] != "in_progress"
        assert after["verify_method"] == ["Run the focused auth check"]


def test_missing_structured_finish_stays_in_progress_and_does_not_invent_verify(
    tmp_path: Path,
) -> None:
    async def fake_reply(*args: object, **kwargs: object) -> str:
        return "Stay on the recovered auth check. I would invent: run pytest on auth.py."

    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=fake_reply),
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("unfinished resume must not generate a plan"),
        ),
    ):
        runtime = client.app.state.runtime
        runtime.memory_service.persist_plan_runtime_recovery(
            "workspace-plan-runtime-unfinished",
            plan_runtime={
                "current_step": "Keep one auth check",
                "why_now": "Expired tokens still leak the session.",
            },
        )
        start = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-unfinished",
                "workspace_name": "workspace-plan-runtime-unfinished",
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        turn = client.post(
            "/turn",
            json={
                "session_id": start.json()["session_id"],
                "workspace_id": "workspace-plan-runtime-unfinished",
                "intent": "plan",
                "formalPlanMutation": False,
                "requestId": "plan-resume-unfinished-1",
                "message": "Continue this step: Keep one auth check. Why now: Expired tokens still leak the session.",
                "response_language": "en-US",
                "planRuntimeRecovery": {
                    "action": "continue_step",
                    "recovered": True,
                    "formalPlanMutation": False,
                    "currentStep": "Keep one auth check",
                    "whyNow": "Expired tokens still leak the session.",
                },
            },
        )
        assert turn.status_code == 200, turn.text
        assert turn.json().get("plan") is None
        live_status = turn.json().get("plan_runtime_status") or turn.json()["snapshot"].get(
            "plan_runtime_status"
        )
        assert live_status["resume_state"] == "in_progress"
        assert not live_status.get("verify_method")
        persisted = runtime.memory_service.recover_workspace_facts(
            "workspace-plan-runtime-unfinished"
        )[PLAN_RUNTIME_KEY]
        assert persisted["resume_state"] == "in_progress"
        assert not persisted.get("verify_method")
        assert persisted.get("plan_id") in {None, ""}
        assert runtime.memory_service.evidence_queue("workspace-plan-runtime-unfinished").pending == []


def _persist_waiting_runtime(
    runtime: object,
    workspace_id: str,
    *,
    next_after_current: str = "Add a token expiry test",
) -> None:
    memory = runtime.memory_service
    memory.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Keep one auth check",
            "why_now": "Expired tokens still leak the session.",
            "next_after_current": next_after_current,
            "verify_method": ["Run the focused auth check"],
            "resume_state": "waiting",
        },
        request_id=f"plan-waiting-{workspace_id}",
    )


def _hydrate_plan_runtime(client: TestClient, workspace_id: str) -> dict:
    hydrate = client.post(
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
    assert hydrate.status_code == 200
    payload = hydrate.json()
    assert payload.get("plan") is None
    return payload["plan_runtime_status"]


def test_adopt_with_structured_next_advances_waiting_runtime(tmp_path: Path) -> None:
    with (
        _client(tmp_path) as client,
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("adopt advance must not generate a plan"),
        ),
    ):
        runtime = client.app.state.runtime
        workspace_id = "workspace-plan-runtime-adopt-next"
        _persist_waiting_runtime(runtime, workspace_id)
        item = runtime.memory_service.enqueue_evidence(
            workspace_id,
            EvidenceItem(
                summary="Auth check passed",
                outcome="pass",
                concepts=["Keep one auth check"],
            ),
            verified=True,
            verification_source="focused_auth_check",
        )
        adopt = client.post(
            "/evidence/adopt",
            json={"workspace_id": workspace_id, "evidence_id": item.id},
        )
        assert adopt.status_code == 200, adopt.text
        assert adopt.json()["plan_updated"] is False
        persisted = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert persisted["resume_state"] == "in_progress"
        assert persisted["current_step"] == "Add a token expiry test"
        assert persisted.get("next_after_current") in {None, ""}
        assert persisted["verify_method"] == []
        assert persisted.get("why_now") in {None, ""}
        assert persisted.get("why_now") != "Expired tokens still leak the session."
        assert persisted.get("blocked_reason") in {None, ""}
        assert persisted.get("plan_id") in {None, ""}
        assert runtime.memory_service.repository.get_latest_plan(workspace_id) is None
        queue = runtime.memory_service.evidence_queue(workspace_id)
        assert queue.pending == []
        assert queue.adopted == []
        assert any(row.id == item.id for row in queue.history)
        assert item.id not in {row.id for row in queue.adopted}
        assert queue.total_count == 1

    with _client(tmp_path) as restarted:
        after = _hydrate_plan_runtime(restarted, "workspace-plan-runtime-adopt-next")
        assert after["recovered"] is True
        assert after["resume_state"] == "in_progress"
        assert after["current_step"] == "Add a token expiry test"
        assert not after.get("next_after_current")
        assert not after.get("why_now")
        assert after.get("why_now") != "Expired tokens still leak the session."
        assert restarted.app.state.runtime.memory_service.repository.get_latest_plan(
            "workspace-plan-runtime-adopt-next"
        ) is None
        restarted_queue = restarted.app.state.runtime.memory_service.evidence_queue(
            "workspace-plan-runtime-adopt-next"
        )
        assert restarted_queue.pending == []
        assert restarted_queue.adopted == []
        assert any(row.summary == "Auth check passed" for row in restarted_queue.history)


def test_formal_plan_old_why_loses_to_advanced_runtime_on_hydrate(tmp_path: Path) -> None:
    with (
        _client(tmp_path) as client,
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("runtime overlay must not generate a plan"),
        ),
    ):
        runtime = client.app.state.runtime
        workspace_id = "workspace-plan-runtime-formal-overlay"
        runtime.memory_service.repository.save_plan(
            workspace_id,
            LearningPlan(
                id="plan-formal-old",
                title="Keep the current stage",
                current_stage_id="stage-1",
                current_step="Keep one auth check",
                why_now="Expired tokens still leak the session.",
                next_after_current="Add a token expiry test",
                frozen=True,
                blocked_reason="Keep the leftover blocker",
                verify_method=["Run the focused auth check"],
                stages=[
                    PlanStage(
                        id="stage-1",
                        title="Auth",
                        goal="Keep one check",
                        outcomes=["pass"],
                        status="active",
                    )
                ],
            ),
        )
        formal_plan = runtime.memory_service.repository.get_latest_plan(workspace_id)
        assert formal_plan is not None
        persisted = runtime.memory_service.persist_plan_runtime_recovery(
            workspace_id,
            plan=_plan_with_formal_next(formal_plan),
            plan_runtime={
                "current_step": "Add a token expiry test",
                "why_now": "",
                "next_after_current": "",
                "verify_method": [],
                "blocked_reason": "",
                "resume_state": "in_progress",
            },
            request_id="plan-formal-overlay-1",
        )
        assert persisted is not None
        assert persisted.get("next_why_now") in {None, ""}
        assert persisted.get("next_why_now") != FORMAL_NEXT_WHY
        assert persisted.get("next_blocked_reason") in {None, ""}
        assert persisted.get("next_verify_method") in (None, [])
        assert runtime.memory_service.repository.get_latest_plan(workspace_id) is not None
        started = client.post(
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
        assert started.status_code == 200, started.text
        payload = started.json()
        status = payload["plan_runtime_status"]
        # Fail-closed: recovered plan_id empty/mismatched → leftover stays stored, not live.
        assert payload.get("plan") in (None, {})
        saved_before_restart = runtime.memory_service.repository.get_latest_plan(workspace_id)
        assert saved_before_restart is not None
        assert saved_before_restart.id == "plan-formal-old"
        assert saved_before_restart.current_step == "Keep one auth check"
        assert saved_before_restart.why_now == "Expired tokens still leak the session."
        assert status["recovered"] is True
        assert status["current_step"] == "Add a token expiry test"
        assert status.get("current_stage") is None
        assert status.get("current_stage_id") in {None, ""}
        recovered_after = client.app.state.runtime.memory_service.recover_workspace_facts(
            workspace_id
        )[PLAN_RUNTIME_KEY]
        assert recovered_after["current_step"] == "Add a token expiry test"
        assert recovered_after.get("current_stage_id") in {None, ""}
        assert recovered_after.get("current_stage_id") != "stage-1"
        assert recovered_after.get("plan_id") in {None, ""}
        assert recovered_after.get("plan_id") != "plan-formal-old"
        assert recovered_after.get("frozen") is not True
        assert recovered_after.get("next_why_now") in {None, ""}
        assert recovered_after.get("next_why_now") != FORMAL_NEXT_WHY
        assert recovered_after.get("next_blocked_reason") in {None, ""}
        assert recovered_after.get("next_blocked_reason") != FORMAL_NEXT_BLOCK
        assert recovered_after.get("next_verify_method") in (None, [])
        assert FORMAL_NEXT_VERIFY[0] not in (recovered_after.get("next_verify_method") or [])
        assert (status.get("current_stage") or {}).get("title") != "Auth"
        assert status.get("why_now") in {None, ""}
        assert status.get("why_now") != "Expired tokens still leak the session."
        assert not status.get("next_after_current")
        assert status.get("verify_method") in (None, [])
        assert "Run the focused auth check" not in (status.get("verify_method") or [])
        assert status.get("blocked_reason") in {None, ""}
        assert status.get("blocked_reason") != "Keep the leftover blocker"
        next_hint = status.get("next_step_hint") or {}
        hint_verify = next_hint.get("verification") or next_hint.get("verify_method") or []
        hint_text = " ".join(
            [
                str(next_hint.get("title") or ""),
                str(next_hint.get("reason") or ""),
                str(next_hint.get("summary") or ""),
                *[str(item) for item in hint_verify],
            ]
        )
        assert "Keep the leftover blocker" not in hint_text
        assert "Run the focused auth check" not in hint_text
        saved = client.app.state.runtime.memory_service.repository.get_latest_plan(workspace_id)
        assert saved is not None
        assert saved.current_stage_id == "stage-1"
        assert saved.current_step == "Keep one auth check"
        assert saved.why_now == "Expired tokens still leak the session."
        assert saved.blocked_reason == "Keep the leftover blocker"
        restarted = client.post(
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
        assert restarted.status_code == 200, restarted.text
        assert restarted.json().get("plan") in (None, {})
        again = restarted.json()["plan_runtime_status"]
        assert again["recovered"] is True
        assert again["current_step"] == "Add a token expiry test"
        assert again.get("current_stage") is None
        assert again.get("current_stage_id") in {None, ""}
        recovered_again = client.app.state.runtime.memory_service.recover_workspace_facts(
            workspace_id
        )[PLAN_RUNTIME_KEY]
        assert recovered_again.get("current_stage_id") in {None, ""}
        assert recovered_again.get("current_stage_id") != "stage-1"
        assert recovered_again.get("plan_id") in {None, ""}
        assert recovered_again.get("plan_id") != "plan-formal-old"
        assert recovered_again.get("frozen") is not True
        assert recovered_again.get("next_why_now") in {None, ""}
        assert recovered_again.get("next_blocked_reason") in {None, ""}
        assert recovered_again.get("next_verify_method") in (None, [])
        formal = client.app.state.runtime.memory_service.repository.get_latest_plan(workspace_id)
        assert formal is not None
        assert formal.id == "plan-formal-old"
        assert formal.frozen is True
        assert formal.current_stage_id == "stage-1"
        assert formal.current_step == "Keep one auth check"
        assert client.app.state.runtime.memory_service.repository.get_latest_plan(
            workspace_id
        ).stages[0].status == "active"
        assert again.get("why_now") in {None, ""}
        assert again.get("why_now") != "Expired tokens still leak the session."
        assert again.get("blocked_reason") in {None, ""}
        assert again.get("blocked_reason") != "Keep the leftover blocker"
        assert client.app.state.runtime.memory_service.repository.get_latest_plan(
            workspace_id
        ).why_now == "Expired tokens still leak the session."
        assert client.app.state.runtime.memory_service.repository.get_latest_plan(
            workspace_id
        ).blocked_reason == "Keep the leftover blocker"


def test_leftover_formal_freeze_update_does_not_clobber_advanced_runtime(tmp_path: Path) -> None:
    with (
        _client(tmp_path) as client,
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("leftover formal mutate must not generate a plan"),
        ),
    ):
        runtime = client.app.state.runtime
        workspace_id = "workspace-plan-runtime-formal-mutate"
        leftover = LearningPlan(
            id="plan-formal-old",
            title="Keep the current stage",
            current_stage_id="stage-1",
            current_step="Keep one auth check",
            why_now="Expired tokens still leak the session.",
            next_after_current="Add a token expiry test",
            frozen=False,
            verify_method=["Run the focused auth check"],
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
        runtime.memory_service.repository.save_plan(workspace_id, leftover)
        persisted = runtime.memory_service.persist_plan_runtime_recovery(
            workspace_id,
            plan_runtime={
                "current_step": "Add a token expiry test",
                "why_now": "",
                "next_after_current": "",
                "verify_method": [],
                "blocked_reason": "",
                "resume_state": "in_progress",
            },
            request_id="plan-formal-mutate-runtime-1",
        )
        assert persisted is not None
        assert persisted["current_step"] == "Add a token expiry test"
        assert persisted.get("plan_id") in {None, ""}

        frozen = client.post(
            "/plan/update",
            json={
                "plan_id": "plan-formal-old",
                "workspace_id": workspace_id,
                "frozen": True,
            },
        )
        assert frozen.status_code == 409, frozen.text
        detail = str(frozen.json().get("detail") or "")
        assert "leftover-not-live" in detail.lower() or "leftover" in detail.lower()
        formal_after_freeze = runtime.memory_service.repository.get_latest_plan(workspace_id)
        assert formal_after_freeze is not None
        assert formal_after_freeze.id == "plan-formal-old"
        assert formal_after_freeze.frozen is False
        assert formal_after_freeze.current_step == "Keep one auth check"
        recovered_frozen = runtime.memory_service.recover_workspace_facts(workspace_id)[
            PLAN_RUNTIME_KEY
        ]
        assert recovered_frozen["current_step"] == "Add a token expiry test"
        assert recovered_frozen.get("plan_id") in {None, ""}
        assert recovered_frozen.get("plan_id") != "plan-formal-old"
        assert recovered_frozen.get("frozen") is not True

        updated = client.post(
            "/plan/update",
            json={
                "plan_id": "plan-formal-old",
                "workspace_id": workspace_id,
                "instructions": "Rework the formal plan around async error handling.",
            },
        )
        assert updated.status_code == 409, updated.text
        recovered_updated = runtime.memory_service.recover_workspace_facts(workspace_id)[
            PLAN_RUNTIME_KEY
        ]
        assert recovered_updated["current_step"] == "Add a token expiry test"
        assert recovered_updated.get("plan_id") in {None, ""}
        assert recovered_updated.get("why_now") in {None, ""}
        formal = runtime.memory_service.repository.get_latest_plan(workspace_id)
        assert formal is not None
        assert formal.id == "plan-formal-old"
        assert formal.frozen is False
        assert formal.current_step == "Keep one auth check"
        assert formal.current_step != recovered_updated["current_step"]
        assert "async error handling" not in (formal.summary or "").lower()


def test_adopt_without_structured_next_does_not_invent_next_step(tmp_path: Path) -> None:
    with (
        _client(tmp_path) as client,
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("empty next must not generate a plan"),
        ),
    ):
        runtime = client.app.state.runtime
        workspace_id = "workspace-plan-runtime-adopt-empty"
        _persist_waiting_runtime(runtime, workspace_id, next_after_current="")
        item = runtime.memory_service.enqueue_evidence(
            workspace_id,
            EvidenceItem(summary="Auth check passed", outcome="pass"),
            verified=True,
            verification_source="focused_auth_check",
        )
        adopt = client.post(
            "/evidence/adopt",
            json={"workspace_id": workspace_id, "evidence_id": item.id},
        )
        assert adopt.status_code == 200, adopt.text
        persisted = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert persisted["resume_state"] == "waiting"
        assert persisted["current_step"] == "Keep one auth check"
        assert persisted.get("next_after_current") in {None, ""}
        assert runtime.memory_service.repository.get_latest_plan(workspace_id) is None

    with _client(tmp_path) as restarted:
        after = _hydrate_plan_runtime(restarted, "workspace-plan-runtime-adopt-empty")
        assert after["resume_state"] == "waiting"
        assert after["current_step"] == "Keep one auth check"


def test_failed_verify_adopt_stays_waiting(tmp_path: Path) -> None:
    with (
        _client(tmp_path) as client,
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("failed verify must not generate a plan"),
        ),
    ):
        runtime = client.app.state.runtime
        fail_ws = "workspace-plan-runtime-adopt-fail"
        unverified_ws = "workspace-plan-runtime-adopt-unverified"
        _persist_waiting_runtime(runtime, fail_ws)
        _persist_waiting_runtime(runtime, unverified_ws)
        fail_item = runtime.memory_service.enqueue_evidence(
            fail_ws,
            EvidenceItem(summary="Auth check failed", outcome="fail"),
            verified=True,
            verification_source="focused_auth_check",
        )
        unverified_item = runtime.memory_service.enqueue_evidence(
            unverified_ws,
            EvidenceItem(summary="Auth check passed", outcome="pass"),
            verified=False,
        )
        fail_adopt = client.post(
            "/evidence/adopt",
            json={"workspace_id": fail_ws, "evidence_id": fail_item.id},
        )
        unverified_adopt = client.post(
            "/evidence/adopt",
            json={"workspace_id": unverified_ws, "evidence_id": unverified_item.id},
        )
        assert fail_adopt.status_code == 200, fail_adopt.text
        assert unverified_adopt.status_code == 200, unverified_adopt.text
        fail_runtime = runtime.memory_service.recover_workspace_facts(fail_ws)[PLAN_RUNTIME_KEY]
        unverified_runtime = runtime.memory_service.recover_workspace_facts(unverified_ws)[
            PLAN_RUNTIME_KEY
        ]
        assert fail_runtime["resume_state"] == "waiting"
        assert fail_runtime["current_step"] == "Keep one auth check"
        assert fail_runtime["next_after_current"] == "Add a token expiry test"
        assert unverified_runtime["resume_state"] == "waiting"
        assert unverified_runtime["current_step"] == "Keep one auth check"


def test_adopt_advance_stays_isolated_across_workspaces(tmp_path: Path) -> None:
    with (
        _client(tmp_path) as client,
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("isolated adopt must not generate a plan"),
        ),
    ):
        runtime = client.app.state.runtime
        workspace_a = "workspace-plan-runtime-adopt-a"
        workspace_b = "workspace-plan-runtime-adopt-b"
        _persist_waiting_runtime(runtime, workspace_a)
        runtime.memory_service.persist_plan_runtime_recovery(
            workspace_b,
            plan_runtime={
                "current_step": "Keep the other login path",
                "why_now": "The other workspace still waits.",
                "next_after_current": "Wire the other guard.",
                "verify_method": ["Run the other check"],
                "resume_state": "waiting",
            },
            request_id="plan-waiting-b",
        )
        item = runtime.memory_service.enqueue_evidence(
            workspace_a,
            EvidenceItem(summary="Auth check passed", outcome="pass"),
            verified=True,
            verification_source="focused_auth_check",
        )
        adopt = client.post(
            "/evidence/adopt",
            json={"workspace_id": workspace_a, "evidence_id": item.id},
        )
        assert adopt.status_code == 200, adopt.text
        advanced = runtime.memory_service.recover_workspace_facts(workspace_a)[PLAN_RUNTIME_KEY]
        isolated = runtime.memory_service.recover_workspace_facts(workspace_b)[PLAN_RUNTIME_KEY]
        assert advanced["resume_state"] == "in_progress"
        assert advanced["current_step"] == "Add a token expiry test"
        assert isolated["resume_state"] == "waiting"
        assert isolated["current_step"] == "Keep the other login path"
        assert isolated["next_after_current"] == "Wire the other guard."
        assert runtime.memory_service.repository.get_latest_plan(workspace_a) is None
        assert runtime.memory_service.repository.get_latest_plan(workspace_b) is None

    with _client(tmp_path) as restarted:
        after_a = _hydrate_plan_runtime(restarted, "workspace-plan-runtime-adopt-a")
        after_b = _hydrate_plan_runtime(restarted, "workspace-plan-runtime-adopt-b")
        assert after_a["resume_state"] == "in_progress"
        assert after_a["current_step"] == "Add a token expiry test"
        assert after_b["resume_state"] == "waiting"
        assert after_b["current_step"] == "Keep the other login path"


def test_waiting_composer_submit_enqueues_without_inventing_or_advancing(tmp_path: Path) -> None:
    with (
        _client(tmp_path) as client,
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("composer evidence must not generate a plan"),
        ),
    ):
        runtime = client.app.state.runtime
        workspace_id = "workspace-plan-runtime-composer"
        other_ws = "workspace-plan-runtime-composer-other"
        runtime.memory_service.persist_plan_runtime_recovery(
            workspace_id,
            plan_runtime={
                "current_step": "Keep one auth check",
                "why_now": "Expired tokens still leak the session.",
                "next_after_current": "Add a token expiry test",
                "resume_state": "waiting",
            },
            request_id="plan-composer-http-1",
        )
        runtime.memory_service.persist_plan_runtime_recovery(
            other_ws,
            plan_runtime={
                "current_step": "Keep the other login path",
                "resume_state": "in_progress",
            },
            request_id="plan-composer-http-other",
        )
        empty = client.post(
            "/evidence/enqueue",
            json={"workspace_id": workspace_id, "waiting_composer": True, "summary": "  "},
        )
        assert empty.status_code == 400
        rejected = client.post(
            "/evidence/enqueue",
            json={
                "workspace_id": other_ws,
                "waiting_composer": True,
                "summary": "I ran the other check.",
            },
        )
        assert rejected.status_code == 400
        assert runtime.memory_service.evidence_queue(other_ws).pending == []
        submit = client.post(
            "/evidence/enqueue",
            json={
                "workspace_id": workspace_id,
                "waitingComposer": True,
                "summary": "I ran the focused auth check on the login path.",
            },
        )
        assert submit.status_code == 200, submit.text
        item = submit.json()
        assert item["summary"] == "I ran the focused auth check on the login path."
        assert item["concepts"] == ["Keep one auth check"]
        assert item["verified"] is False
        assert item["outcome"] == "partial"
        pending = runtime.memory_service.evidence_queue(workspace_id).pending
        assert len(pending) == 1
        persisted = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert persisted["resume_state"] == "waiting"
        assert persisted["current_step"] == "Keep one auth check"
        assert persisted.get("plan_id") in {None, ""}
        assert runtime.memory_service.repository.get_latest_plan(workspace_id) is None
        adopt = client.post(
            "/evidence/adopt",
            json={"workspace_id": workspace_id, "evidence_id": item["id"]},
        )
        assert adopt.status_code == 200, adopt.text
        advanced = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert advanced["resume_state"] == "in_progress"
        assert advanced["current_step"] == "Add a token expiry test"
        assert runtime.memory_service.repository.get_latest_plan(workspace_id) is None


def test_waiting_composer_replace_after_reject_stays_waiting_until_adopt(
    tmp_path: Path,
) -> None:
    with (
        _client(tmp_path) as client,
        patch.object(
            client.app.state.runtime.planner_service,
            "generate_plan",
            side_effect=AssertionError("replacement evidence must not generate a plan"),
        ),
    ):
        runtime = client.app.state.runtime
        workspace_id = "workspace-plan-runtime-composer-replace"
        runtime.memory_service.persist_plan_runtime_recovery(
            workspace_id,
            plan_runtime={
                "current_step": "Keep one auth check",
                "why_now": "Expired tokens still leak the session.",
                "next_after_current": "Add a token expiry test",
                "resume_state": "waiting",
            },
            request_id="plan-composer-replace-http",
        )
        first = client.post(
            "/evidence/enqueue",
            json={
                "workspace_id": workspace_id,
                "waiting_composer": True,
                "summary": "I ran the focused auth check on the login path.",
            },
        )
        assert first.status_code == 200, first.text
        first_id = first.json()["id"]
        duplicate = client.post(
            "/evidence/enqueue",
            json={
                "workspace_id": workspace_id,
                "waiting_composer": True,
                "summary": "A duplicate invented verify result.",
            },
        )
        assert duplicate.status_code == 400
        assert len(runtime.memory_service.evidence_queue(workspace_id).pending) == 1
        reject = client.post(
            "/evidence/reject",
            json={"workspace_id": workspace_id, "evidence_id": first_id, "reason": "Not enough proof"},
        )
        assert reject.status_code == 200, reject.text
        after_reject = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert after_reject["resume_state"] == "waiting"
        assert after_reject["current_step"] == "Keep one auth check"
        assert runtime.memory_service.evidence_queue(workspace_id).pending == []
        empty = client.post(
            "/evidence/enqueue",
            json={"workspace_id": workspace_id, "waiting_composer": True, "summary": "  "},
        )
        assert empty.status_code == 400
        replacement = client.post(
            "/evidence/enqueue",
            json={
                "workspace_id": workspace_id,
                "waitingComposer": True,
                "summary": "I reran the focused auth check with the expiry case.",
            },
        )
        assert replacement.status_code == 200, replacement.text
        item = replacement.json()
        assert item["id"] != first_id
        assert item["summary"] == "I reran the focused auth check with the expiry case."
        pending = runtime.memory_service.evidence_queue(workspace_id).pending
        assert len(pending) == 1
        persisted = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert persisted["resume_state"] == "waiting"
        assert persisted.get("plan_id") in {None, ""}
        adopt = client.post(
            "/evidence/adopt",
            json={"workspace_id": workspace_id, "evidence_id": item["id"]},
        )
        assert adopt.status_code == 200, adopt.text
        advanced = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert advanced["resume_state"] == "in_progress"
        assert advanced["current_step"] == "Add a token expiry test"
        assert runtime.memory_service.repository.get_latest_plan(workspace_id) is None
