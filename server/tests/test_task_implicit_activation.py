from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.llm.provider_service import ProviderService
from tests.test_api import build_client


def test_session_start_does_not_invent_a_task_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        next_task_calls: list[object] = []
        generate_plan_calls: list[object] = []
        original_next = runtime.planner_service.next_task
        original_generate = runtime.planner_service.generate_plan

        def _track_next(*args: object, **kwargs: object) -> object:
            next_task_calls.append((args, kwargs))
            return original_next(*args, **kwargs)

        def _track_generate(*args: object, **kwargs: object) -> object:
            generate_plan_calls.append((args, kwargs))
            return original_generate(*args, **kwargs)

        monkeypatch.setattr(runtime.planner_service, "next_task", _track_next)
        monkeypatch.setattr(runtime.planner_service, "generate_plan", _track_generate)

        response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-no-invented-task",
                "workspace_name": "trainer-no-invented-task",
                "profile": {
                    "long_term_goal": "Understand first without inventing a task",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert next_task_calls == []
        assert generate_plan_calls == []
        assert payload.get("plan") in (None, {})
        current_task = payload.get("current_task") or payload.get("currentTask") or {}
        assert not current_task.get("title")
        assert current_task.get("title") != "Ship one invented task"
        status = payload.get("plan_runtime_status") or payload.get("planRuntimeStatus") or {}
        next_action = str(status.get("next_training_action") or status.get("nextTrainingAction") or "").strip()
        assert next_action != "Ship one invented task"
        assert not next_action.startswith("Continue:")
        assert not next_action.startswith("Review:")


@pytest.mark.parametrize(
    ("workspace_id", "message"),
    (
        (
            "workspace-understand-no-task",
            "Help me understand this VS Code remote workspace first, then verify one tiny step.",
        ),
        (
            "workspace-diagnose-no-task",
            "Diagnose this VS Code debug loop. Learn first, then verify one checkpoint.",
        ),
        (
            "workspace-what-next-no-task",
            "What should I do next after this slice?",
        ),
    ),
)
def test_coach_turn_does_not_invent_a_task_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workspace_id: str,
    message: str,
) -> None:
    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Stay with the first-look next step. Do not invent a task."),
        ),
    ):
        runtime = client.app.state.runtime
        next_task_calls: list[object] = []
        original_next = runtime.planner_service.next_task

        def _track_next(*args: object, **kwargs: object) -> object:
            next_task_calls.append((args, kwargs))
            return original_next(*args, **kwargs)

        monkeypatch.setattr(runtime.planner_service, "next_task", _track_next)
        response = client.post(
            "/turn",
            json={
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": message,
                "response_language": "en-US",
                "answer_mode": "auto",
                "use_agent_loop": False,
            },
        )
        stored_task = runtime.ensure_session(response.json().get("session_id"), workspace_id=workspace_id)

    assert response.status_code == 200, response.text
    payload = response.json()
    snapshot = payload["snapshot"]
    assert next_task_calls == []
    assert snapshot.get("current_task") in (None, {})
    assert stored_task.snapshot.current_task in (None, {})
    assert snapshot.get("plan") in (None, {})
    routing = snapshot["memory"]["active_training_card_routing"]
    assert routing is None


def test_explicit_task_next_still_creates_a_task_spec(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-explicit-next-task",
                "workspace_name": "trainer-explicit-next-task",
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-explicit-next-task",
                "objectives": ["Ship one explicit next-task slice"],
            },
        )
        assert generated.status_code == 200, generated.text
        plan_id = str(
            (generated.json().get("plan") or generated.json()).get("id")
            or (generated.json().get("plan") or generated.json()).get("plan_id")
            or ""
        ).strip()
        assert plan_id
        created = client.post(
            "/task/next",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-explicit-next-task",
            },
        )
        assert created.status_code == 200, created.text
        task = created.json()
        assert task.get("title")
        assert task.get("id")
        assert str((task.get("metadata") or {}).get("plan_id") or "").strip() == plan_id
