"""Fail-closed POST /plan/update: live matching plan_id may mutate; leftover must not resurrect."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import LearningPlan, PlanStage
from app.core.settings import AppSettings
from app.main import create_app
from app.memory.workspace_recovery import PLAN_RUNTIME_KEY, leftover_formal_plan_is_live_for_fill


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer plan-update live-plan gate",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-plan-update-gate.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _runtime(workspace: dict) -> dict:
    value = workspace.get("latest_plan_runtime") or workspace.get("latestPlanRuntime") or {}
    return value if isinstance(value, dict) else {}


def _seed_live_plan(runtime, workspace_id: str, *, plan_id: str) -> LearningPlan:
    plan = LearningPlan(
        id=plan_id,
        title="Ship token refresh under a live plan",
        current_step="Ship token refresh under a live plan",
        why_now="Keep the live stage visible",
        next_after_current="Review the refresh path",
        stages=[
            PlanStage(
                id="stage-live",
                title="Live",
                goal="Ship token refresh under a live plan",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    runtime.repository.save_plan(workspace_id, plan)
    runtime.memory_service.bind_explicit_generated_plan(workspace_id, plan)
    return plan


def test_plan_update_with_live_plan_freezes_without_changing_plan_id(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-update-live"
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Live plan update lab"},
        )
        assert started.status_code == 200, started.text
        seeded = _seed_live_plan(app.state.runtime, workspace_id, plan_id="plan-live-freeze")
        plan_id = seeded.id
        live_runtime = _runtime(
            (app.state.runtime.memory_service.snapshot(workspace_id).workspace or {})
        )
        assert str(live_runtime.get("plan_id") or live_runtime.get("planId") or "").strip() == plan_id

        frozen = client.post(
            "/plan/update",
            json={
                "plan_id": plan_id,
                "workspace_id": workspace_id,
                "frozen": True,
            },
        )
        assert frozen.status_code == 200, frozen.text
        updated = frozen.json().get("plan") or frozen.json()
        assert updated.get("frozen") is True
        assert str(updated.get("id") or updated.get("plan_id") or "").strip() == plan_id
        after_runtime = _runtime((frozen.json().get("memory") or {}).get("workspace") or {})
        if after_runtime:
            asserted_id = str(
                after_runtime.get("plan_id") or after_runtime.get("planId") or ""
            ).strip()
            if asserted_id:
                assert asserted_id == plan_id
        stored = app.state.runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.id == plan_id
        assert stored.frozen is True


def test_plan_update_leftover_not_live_does_not_resurrect(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-update-leftover"
    leftover_title = "Keep the leftover stage"
    leftover_step = "Keep one auth check"
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Leftover plan update lab"},
        )
        assert started.status_code == 200, started.text
        leftover = LearningPlan(
            id="plan-leftover-update",
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
        recovered = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert not leftover_formal_plan_is_live_for_fill(
            plan=leftover,
            runtime=recovered,
            existing=recovered,
        )

        response = client.post(
            "/plan/update",
            json={
                "plan_id": leftover.id,
                "workspace_id": workspace_id,
                "frozen": True,
            },
        )
        assert response.status_code == 409, response.text
        detail = str(response.json().get("detail") or "")
        assert "leftover-not-live" in detail.lower() or "leftover" in detail.lower()
        body = response.json()
        assert body.get("plan") in (None, {}, "")
        stored = runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.id == leftover.id
        assert stored.title == leftover_title
        assert stored.current_step == leftover_step
        assert stored.frozen is False
        after = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert str(after.get("plan_id") or "").strip() in {"", "None"}
        assert after.get("current_step") == leftover_step


def test_plan_update_empty_recovered_plan_id_stays_fail_closed(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-update-empty-id"
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Empty plan_id lab"},
        )
        assert started.status_code == 200, started.text
        leftover = LearningPlan(
            id="plan-empty-runtime-id",
            title="Stored but not live",
            current_step="Do not resurrect this step",
            why_now="Leftover why",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Stored",
                    goal="Remain leftover",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        runtime = app.state.runtime
        runtime.repository.save_plan(workspace_id, leftover)
        runtime.memory_service.persist_plan_runtime_recovery(
            workspace_id,
            plan_runtime={
                "current_step": "Advanced overlay step",
                "plan_id": "",
                "resume_state": "in_progress",
            },
            request_id="plan-update-empty-id-1",
        )

        response = client.post(
            "/plan/update",
            json={
                "plan_id": leftover.id,
                "workspace_id": workspace_id,
                "instructions": "Rewrite leftover as if it were live.",
            },
        )
        assert response.status_code == 409, response.text
        stored = runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.id == leftover.id
        assert stored.current_step == "Do not resurrect this step"
        assert "rewrite leftover" not in (stored.summary or "").lower()
        recovered = runtime.memory_service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
        assert recovered.get("current_step") == "Advanced overlay step"
        assert recovered.get("plan_id") in {None, ""}
