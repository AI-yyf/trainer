"""Fail-closed POST /task/specify: live plan may mint TaskSpec; leftover/no-plan must not."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import AffectState, LearningPlan, PlanStage, ProviderConfig, UserProfile
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.memory.workspace_recovery import leftover_formal_plan_is_live_for_fill


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer task-specify live-plan gate",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-task-specify-gate.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _card_ids(runtime, workspace_id: str) -> set[str]:
    return {
        str(getattr(card, "card_id", "") or getattr(card, "cardId", "") or "").strip()
        for card in runtime.memory_service.get_cards(workspace_id)
        if str(getattr(card, "card_id", "") or getattr(card, "cardId", "") or "").strip()
    }


def _runtime(workspace: dict) -> dict:
    value = workspace.get("latest_plan_runtime") or workspace.get("latestPlanRuntime") or {}
    return value if isinstance(value, dict) else {}


def _seed_provider(app) -> None:
    """Seed an offline provider with observed capabilities so provider-gated routes pass."""

    provider = ProviderConfig(
        name="test-openai-compatible",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={
            "chat": True,
            "responses": True,
            "vision": False,
            "embeddings": False,
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


def test_task_specify_with_live_plan_mints_task_bound_to_plan_id(tmp_path: Path) -> None:
    workspace_id = "workspace-task-specify-live"
    app = create_app(_settings(tmp_path / "data"))
    _seed_provider(app)
    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Live plan lab"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Ship token refresh under a live plan"],
            },
        )
        assert generated.status_code == 200, generated.text
        plan = generated.json().get("plan") or generated.json()
        plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
        assert plan_id
        live_runtime = _runtime((generated.json().get("memory") or {}).get("workspace") or {})
        assert str(live_runtime.get("plan_id") or live_runtime.get("planId") or "").strip() == plan_id
        runtime = app.state.runtime
        cards_before = _card_ids(runtime, workspace_id)

        response = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "natural_language_goal": "Add an expiry check for the refresh token",
            },
        )
        assert response.status_code == 200, response.text
        task = response.json()
        assert task.get("title")
        assert task.get("id")
        assert str((task.get("metadata") or {}).get("plan_id") or "").strip() == plan_id
        produced_workspace = str(task.get("workspace_id") or task.get("workspaceId") or "")
        assert produced_workspace == workspace_id
        latest = runtime.repository.get_latest_plan(workspace_id)
        assert latest is not None
        assert latest.id == plan_id
        assert _card_ids(runtime, workspace_id) == cards_before


def test_task_specify_leftover_not_live_does_not_invent_or_resurrect(tmp_path: Path) -> None:
    workspace_id = "workspace-task-specify-leftover"
    leftover_title = "Keep the leftover stage"
    leftover_step = "Keep one auth check"
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Leftover lab"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        leftover = LearningPlan(
            id="plan-leftover-task-specify",
            title=leftover_title,
            current_step=leftover_step,
            why_now="Keep the leftover why",
            next_after_current="Then review the leftover path",
            stages=[
                PlanStage(
                    id="stage-leftover",
                    title="Leftover",
                    goal="Stay leftover-not-live",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        runtime = app.state.runtime
        runtime.repository.save_plan(workspace_id, leftover)
        runtime.memory_service.structured_for_workspace(workspace_id).update_workspace(
            latest_plan_runtime={
                "current_step": leftover_step,
                "plan_id": "",
                "resume_state": "in_progress",
                "workspace_id": workspace_id,
            }
        )
        assert not leftover_formal_plan_is_live_for_fill(
            plan=leftover,
            runtime=runtime.memory_service.recover_workspace_facts(workspace_id)[
                "latest_plan_runtime"
            ],
            existing=runtime.memory_service.recover_workspace_facts(workspace_id)[
                "latest_plan_runtime"
            ],
        )
        cards_before = _card_ids(runtime, workspace_id)
        response = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "natural_language_goal": "Invent a task from leftover",
            },
        )
        assert response.status_code == 409, response.text
        detail = str(response.json().get("detail") or "")
        assert "leftover-not-live" in detail.lower() or "leftover" in detail.lower()
        stored = runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.id == leftover.id
        assert stored.title == leftover_title
        assert stored.current_step == leftover_step
        assert _card_ids(runtime, workspace_id) == cards_before
        state = runtime.ensure_session(session_id, workspace_id=workspace_id)
        task = state.snapshot.current_task
        assert task is None or not str(getattr(task, "title", "") or "").strip()


def test_task_specify_no_live_plan_does_not_invent_plan_task_pair(tmp_path: Path) -> None:
    workspace_id = "workspace-task-specify-empty"
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Empty lab"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        runtime = app.state.runtime
        assert runtime.repository.get_latest_plan(workspace_id) is None
        response = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "natural_language_goal": "Invent a task without a plan",
            },
        )
        assert response.status_code == 409, response.text
        detail = str(response.json().get("detail") or "")
        assert "does not invent" in detail.lower() or "no live" in detail.lower()
        assert runtime.repository.get_latest_plan(workspace_id) is None
        state = runtime.ensure_session(session_id, workspace_id=workspace_id)
        task = state.snapshot.current_task
        assert task is None or not str(getattr(task, "title", "") or "").strip()


def test_task_specify_high_urgency_without_live_plan_still_fail_closed(tmp_path: Path) -> None:
    """/plan/generate still binds under urgency; /task/specify must not invent a plan."""
    workspace_id = "workspace-task-specify-urgency"
    app = create_app(_settings(tmp_path / "data"))
    _seed_provider(app)
    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Urgency lab"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        runtime = app.state.runtime
        runtime.memory_service.persist_turn_context_pressure(
            workspace_id,
            affect_state=AffectState(urgency_level="high", frustration_level=0.9),
        )
        response = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "natural_language_goal": "Ship under high urgency without a plan",
            },
        )
        assert response.status_code == 409, response.text
        assert runtime.repository.get_latest_plan(workspace_id) is None

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Ship under high urgency with an explicit plan"],
                "profile": UserProfile(long_term_goal="Ship under urgency").model_dump(
                    mode="json"
                ),
            },
        )
        assert generated.status_code == 200, generated.text
        plan = generated.json().get("plan") or generated.json()
        plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
        assert plan_id
        live_runtime = _runtime((generated.json().get("memory") or {}).get("workspace") or {})
        assert str(live_runtime.get("plan_id") or live_runtime.get("planId") or "").strip() == plan_id

        allowed = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "natural_language_goal": "Add one urgency-safe verify step",
            },
        )
        assert allowed.status_code == 200, allowed.text
        task = allowed.json()
        assert task.get("title")
        assert str((task.get("metadata") or {}).get("plan_id") or "").strip() == plan_id
        assert runtime.repository.get_latest_plan(workspace_id).id == plan_id
