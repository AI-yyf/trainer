from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import ChatMessage, LearningPlan, SubPlan, TrainingCardCandidateSnapshot
from app.core.settings import AppSettings
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            AppSettings(
                app_name="Trainer Library Management API Tests",
                host="127.0.0.1",
                port=8765,
                data_dir=tmp_path,
                database_name="trainer-library-management-api.db",
                default_session_stage="intake",
                summary_message_limit=6,
                enable_network_fetch=False,
            )
        )
    )


def start_session(client: TestClient, workspace_id: str) -> str:
    response = client.post(
        "/session/start",
        json={"workspace_id": workspace_id, "workspace_name": "Library API"},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["session_id"])


def test_library_overview_reads_real_persisted_snapshot_messages(tmp_path: Path) -> None:
    workspace_id = "workspace-library-overview"
    with build_client(tmp_path) as client:
        session_id = start_session(client, workspace_id)
        runtime = client.app.state.runtime
        state = runtime.get_session(session_id)
        assert state is not None
        state.snapshot.messages.extend(
            [
                ChatMessage(id="user-1", role="user", content="Help me learn durable state."),
                ChatMessage(id="assistant-1", role="assistant", content="Start with one lifecycle."),
            ]
        )
        runtime.save_session_state(session_id)

        response = client.get(
            "/library/overview",
            params={"workspace_id": workspace_id, "session_id": session_id},
        )

    assert response.status_code == 200, response.text
    sessions = response.json()["sessions"]
    assert sessions == [
        {
            "id": session_id,
            "title": "Help me learn durable state.",
            "messageCount": 2,
            "updatedAt": state.snapshot.messages[-1].created_at,
            "isActive": True,
        }
    ]


def test_library_delete_rejects_current_session_without_losing_history(tmp_path: Path) -> None:
    workspace_id = "workspace-library-current-session"
    with build_client(tmp_path) as client:
        session_id = start_session(client, workspace_id)

        response = client.post(
            "/library/delete",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "type": "session",
                "id": session_id,
                "request_id": "delete-current-session",
            },
        )
        stored = client.app.state.runtime.repository.load_session(session_id)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Switch to another conversation before deleting the current one."
    assert stored is not None


def test_library_delete_removes_loaded_inactive_session_without_resurrection(tmp_path: Path) -> None:
    workspace_id = "workspace-library-inactive-session"
    with build_client(tmp_path) as client:
        inactive_session_id = start_session(client, workspace_id)
        runtime = client.app.state.runtime
        active_session_id = runtime.start_session(workspace_id, "Library API active").session_id
        assert runtime.get_session(inactive_session_id) is not None

        response = client.post(
            "/library/delete",
            json={
                "session_id": active_session_id,
                "workspace_id": workspace_id,
                "type": "session",
                "id": inactive_session_id,
                "request_id": "delete-inactive-session",
            },
        )
        stored = runtime.repository.load_session(inactive_session_id)
        overview = client.get(
            "/library/overview",
            params={"workspace_id": workspace_id, "session_id": active_session_id},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert {key: payload[key] for key in ("ok", "type", "id", "requestId")} == {
        "ok": True,
        "type": "session",
        "id": inactive_session_id,
        "requestId": "delete-inactive-session",
    }
    assert payload["activity"]["action"] == "deleted"
    assert payload["activity"]["type"] == "session"
    assert payload["activity"]["id"] == inactive_session_id
    assert stored is None
    assert runtime.get_session(inactive_session_id) is None
    assert inactive_session_id not in {item["id"] for item in overview.json()["sessions"]}
    assert overview.json()["activity"][0] == payload["activity"]
    ledger_entries = runtime.event_ledger.query(project_id=workspace_id)
    assert [entry.event_type for entry in ledger_entries][-1] == "coach_session_deleted"

    # The deletion audit is durable rather than an in-memory toast only.
    with build_client(tmp_path) as restarted_client:
        restarted = restarted_client.get(
            "/library/overview",
            params={"workspace_id": workspace_id, "session_id": active_session_id},
        )
    assert restarted.status_code == 200, restarted.text
    assert restarted.json()["activity"][0] == payload["activity"]


def test_library_delete_plan_cascades_and_clears_live_snapshot(tmp_path: Path) -> None:
    workspace_id = "workspace-library-plan"
    with build_client(tmp_path) as client:
        session_id = start_session(client, workspace_id)
        runtime = client.app.state.runtime
        runtime.repository.save_plan(
            workspace_id,
            LearningPlan(id="plan-delete-api", title="Delete this plan", stages=[]),
        )
        runtime.repository.save_subplan(
            "plan-delete-api",
            SubPlan(
                id="subplan-delete-api",
                parent_plan_id="plan-delete-api",
                title="Delete this subplan",
            ),
        )
        runtime.refresh_workspace_sessions(workspace_id)

        response = client.post(
            "/library/delete",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "type": "plan",
                "id": "plan-delete-api",
                "request_id": "delete-plan-api",
            },
        )
        state = runtime.get_session(session_id)

    assert response.status_code == 200, response.text
    assert runtime.repository.list_plans(workspace_id) == []
    assert runtime.repository.list_subplans("plan-delete-api") == []
    assert state is not None and state.snapshot.plan is None
    assert response.json()["activity"]["payload"]["title"] == "Delete this plan"
    assert runtime.event_ledger.query(project_id=workspace_id)[-1].event_type == "training_plan_deleted"


def test_library_delete_card_clears_routing_and_records_audit(tmp_path: Path) -> None:
    workspace_id = "workspace-library-card"
    with build_client(tmp_path) as client:
        session_id = start_session(client, workspace_id)
        runtime = client.app.state.runtime
        runtime.memory_service.upsert_card(
            workspace_id,
            TrainingCardCandidateSnapshot(
                card_id="card-delete-api",
                card_type="practice",
                title="Delete this card",
                status="active",
            ),
        )
        structured = runtime.memory_service._structured_for(workspace_id)
        structured.update_workspace(selected_card_id="card-delete-api", selected_card_status="active")
        runtime.memory_service._persist_structured(workspace_id)

        response = client.post(
            "/library/delete",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "type": "card",
                "id": "card-delete-api",
                "request_id": "delete-card-api",
            },
        )
        memory = runtime.memory_service.snapshot(workspace_id)

    assert response.status_code == 200, response.text
    assert runtime.memory_service.get_card(workspace_id, "card-delete-api") is None
    assert memory.workspace.get("selected_card_id") == ""
    assert response.json()["activity"]["payload"]["title"] == "Delete this card"
    assert runtime.event_ledger.query(project_id=workspace_id)[-1].event_type == "training_card_deleted"
