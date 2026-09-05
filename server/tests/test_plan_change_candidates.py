from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import LearningPlan, PlanStage
from app.core.settings import AppSettings
from app.main import create_app


def test_plan_mismatch_creates_persisted_candidate_without_mutating_plan(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            AppSettings(
                app_name="Candidate Test",
                host="127.0.0.1",
                port=8765,
                default_session_stage="intake",
                summary_message_limit=6,
                data_dir=tmp_path,
                database_name="candidate-test.db",
                enable_network_fetch=False,
            )
        )
    )
    workspace_id = "workspace-plan-mismatch"
    plan = LearningPlan(
        id="plan-candidate",
        title="Current plan",
        stages=[PlanStage(id="stage-1", title="Current", goal="Learn", outcomes=["Understand"], status="active")],
        current_stage_id="stage-1",
        current_step="Inspect the current boundary.",
        verify_method=["Run the focused test."],
    )

    with client:
        runtime = client.app.state.runtime
        runtime.repository.save_plan(workspace_id, plan)
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Candidate test"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        response = client.post(
            "/memory/feedback",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "kind": "plan_mismatch",
                "plan_id": plan.id,
                "message": "计划不适合：当前步骤太大。",
            },
        )
        assert response.status_code == 200, response.text
        candidates = response.json()["memory"]["planChangeCandidates"]
        assert len(candidates) == 1
        assert candidates[0]["status"] == "pending"
        assert candidates[0]["reason"] == "计划不适合：当前步骤太大。"
        assert candidates[0]["diff"]["current_step"] == plan.current_step
        assert candidates[0]["impact"]["formal_plan_changed"] is False
        assert runtime.repository.get_latest_plan(workspace_id).model_dump() == plan.model_dump()

        listed = client.get("/plan/change-candidates", params={"workspace_id": workspace_id})
        assert listed.status_code == 200
        candidate_id = listed.json()[0]["id"]
        acknowledged = client.post(
            f"/plan/change-candidates/{candidate_id}/ack",
            json={"workspace_id": workspace_id, "note": "Review this candidate in Plan."},
        )
        assert acknowledged.status_code == 200
        assert acknowledged.json()["status"] == "acknowledged"
        assert runtime.repository.get_latest_plan(workspace_id).model_dump() == plan.model_dump()


def test_non_plan_feedback_does_not_create_candidate(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            AppSettings(
                app_name="Candidate Test",
                host="127.0.0.1",
                port=8765,
                default_session_stage="intake",
                summary_message_limit=6,
                data_dir=tmp_path,
                database_name="candidate-noop.db",
                enable_network_fetch=False,
            )
        )
    )
    with client:
        response = client.post(
            "/memory/feedback",
            json={
                "workspace_id": "workspace-feedback-noop",
                "kind": "too_hard",
                "message": "This is too hard.",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["memory"]["planChangeCandidates"] == []
