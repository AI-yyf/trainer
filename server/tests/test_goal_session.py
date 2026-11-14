"""Behavior tests for server-owned goal sessions."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.goal.service import detect_goal_candidate
from app.main import create_app


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer goal sessions",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-goal.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _start_session(client: TestClient, workspace_id: str = "w-goal") -> str:
    response = client.post(
        "/session/start",
        json={"workspace_id": workspace_id, "workspace_name": "Goal Workspace"},
    )
    assert response.status_code == 200
    return str(response.json()["session_id"])


def _current(client: TestClient, workspace_id: str = "w-goal") -> dict | None:
    response = client.get("/goal/current", params={"workspace_id": workspace_id})
    assert response.status_code == 200
    return response.json()["goal"]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("PPO 是什么？", None),
        ("Can you explain PPO?", None),
        ("I want to learn how to build a compiler", "build a compiler"),
        ("我想真正学会实现 PPO", "实现 PPO"),
        ("我想系统学习强化学习", "强化学习"),
        ("我想真正学会实现 PPO Clip，请先判断我该从哪里开始", "实现 PPO Clip"),
        ("帮我制定一个学习 PPO 的计划", "PPO"),
        (
            "帮我设定一个长期目标：3 天内能够独立解释 PPO 的裁剪目标，并手写对应的损失函数。",
            "3 天内能够独立解释 PPO 的裁剪目标，并手写对应的损失函数",
        ),
        (
            "帮我设置学习目标：解释公式并手写损失函数，请先给我一个最小例子。",
            "解释公式并手写损失函数",
        ),
        ("Please set a goal: ship a small compiler", "ship a small compiler"),
        (
            "Set a goal: explain the parser, and implement it; please suggest a first exercise.",
            "explain the parser, and implement it",
        ),
        ("今天的目标是什么？", None),
        ("随便聊聊", None),
        ("/review", None),
    ],
)
def test_detection_only_matches_explicit_capability_intent(
    message: str,
    expected: str | None,
) -> None:
    assert detect_goal_candidate(message) == expected


def test_auto_detection_never_replaces_an_existing_goal(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        first_question_state = client.get(
            "/snapshot",
            params={"workspace_id": "w-auto"},
        )
        assert first_question_state.status_code == 200
        service = app.state.runtime.goals()

        assert service.observe_turn(
            workspace_id="w-auto",
            message="PPO 是什么？",
            intent="coach",
            active_view="coach",
        ) is None

        detected = service.observe_turn(
            workspace_id="w-auto",
            message="我想真正学会实现 PPO",
            intent="coach",
            active_view="coach",
        )
        assert detected is not None
        assert detected.source == "coach_detected"
        assert detected.title == "实现 PPO"

        # A second learning statement cannot silently replace the focus.
        same = service.observe_turn(
            workspace_id="w-auto",
            message="我想系统学习强化学习",
            intent="coach",
            active_view="coach",
        )
        assert same is not None
        assert same.goal_id == detected.goal_id


def test_explicit_goal_survives_restart_and_is_in_the_snapshot(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    app = create_app(_settings(data_dir))
    with TestClient(app) as client:
        session_id = _start_session(client)
        started = client.post(
            "/goal/action",
            json={
                "session_id": session_id,
                "workspace_id": "w-goal",
                "action": "start",
                "title": "实现 PPO",
            },
        )
        assert started.status_code == 200
        goal_id = started.json()["goal"]["goalId"]
        assert started.json()["goal"]["source"] == "user_explicit"

        snapshot = client.get("/snapshot", params={"workspace_id": "w-goal"}).json()
        assert snapshot["snapshot"]["goal"]["goal_id"] == goal_id

    # A fresh sidecar must restore the same server-owned goal.
    restarted = create_app(_settings(data_dir))
    with TestClient(restarted) as client:
        session = client.post(
            "/session/start",
            json={"workspace_id": "w-goal", "workspace_name": "Goal Workspace"},
        ).json()
        assert session["goal"]["goalId"] == goal_id
        assert session["goal"]["title"] == "实现 PPO"


def test_pause_resume_complete_transitions_and_current_focus(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        session_id = _start_session(client)
        client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "实现 PPO"},
        )

        paused = client.post(
            "/goal/action",
            json={"workspace_id": "w-goal", "action": "pause"},
        )
        assert paused.status_code == 200
        assert paused.json()["goal"]["status"] == "paused"
        assert _current(client)["status"] == "paused"

        resumed = client.post(
            "/goal/action",
            json={"workspace_id": "w-goal", "action": "resume"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["goal"]["status"] == "active"

        completed = client.post(
            "/goal/action",
            json={"workspace_id": "w-goal", "action": "complete"},
        )
        assert completed.status_code == 200
        assert completed.json()["goal"]["status"] == "completed"
        assert completed.json()["goal"]["completedAt"]
        assert _current(client) is None

        listed = client.get("/goal/list", params={"workspace_id": "w-goal"}).json()["goals"]
        assert [goal["status"] for goal in listed] == ["completed"]


def test_new_explicit_goal_pauses_but_preserves_the_previous_focus(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        session_id = _start_session(client)
        first = client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "实现 PPO"},
        ).json()["goal"]
        second = client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "掌握 RAG 检索"},
        ).json()["goal"]

        assert second["goalId"] != first["goalId"]
        assert second["status"] == "active"
        goals = client.get("/goal/list", params={"workspace_id": "w-goal"}).json()["goals"]
        by_id = {goal["goalId"]: goal for goal in goals}
        assert by_id[first["goalId"]]["status"] == "paused"
        assert by_id[first["goalId"]]["title"] == "实现 PPO"


def test_restarting_a_paused_goal_reuses_it_instead_of_duplicating(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        session_id = _start_session(client)
        first = client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "实现 PPO"},
        ).json()["goal"]
        second = client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "掌握 RAG 检索"},
        ).json()["goal"]
        assert second["status"] == "active"

        restarted = client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "实现 PPO"},
        ).json()["goal"]

        assert restarted["goalId"] == first["goalId"]
        assert restarted["status"] == "active"
        goals = client.get("/goal/list", params={"workspace_id": "w-goal"}).json()["goals"]
        assert len(goals) == 2
        by_id = {goal["goalId"]: goal for goal in goals}
        assert by_id[first["goalId"]]["status"] == "active"
        assert by_id[second["goalId"]]["status"] == "paused"


def test_evaluation_activity_is_attributed_once_per_artifact(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        session_id = _start_session(client)
        client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "实现 PPO"},
        )
        payload = {
            "session_id": session_id,
            "workspace_id": "w-goal",
            "language_id": "python",
            "content": "print('hello')\n",
        }
        assert client.post("/evaluate/snippet", json=payload).status_code == 200
        goal = _current(client)
        assert goal["activityCount"] == 1
        assert goal["evidenceCount"] == 1
        assert goal["latestActivity"]["kind"] == "evaluation"
        assert goal["latestActivity"]["result"] == "failed"
        assert goal["latestActivity"]["evidenceRefs"][0].startswith("evaluation:")

        # Same artifact hash is the same evidence, not a second learning event.
        assert client.post("/evaluate/snippet", json=payload).status_code == 200
        assert _current(client)["activityCount"] == 1

        payload["content"] = "print('hello world')\n"
        assert client.post("/evaluate/snippet", json=payload).status_code == 200
        assert _current(client)["activityCount"] == 2


def test_training_attempt_evidence_advances_the_active_goal(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        session_id = _start_session(client)
        client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "实现 PPO"},
        )
        attempt = app.state.runtime.attempt_store.start_attempt(
            workspace_id="w-goal",
            card_id="card-ppo-clip",
        )
        response = client.post(
            "/training/attempt/evidence",
            json={
                "attempt_id": attempt["attempt_id"],
                "workspace_id": "w-goal",
                "artifact_hash": "sha256:abc123",
                "result": "passed",
            },
        )
        assert response.status_code == 200
        goal = _current(client)
        assert goal["activityCount"] == 1
        assert goal["latestActivity"]["kind"] == "training_attempt"
        assert goal["latestActivity"]["result"] == "passed"
        assert f"attempt:{attempt['attempt_id']}" in goal["latestActivity"]["evidenceRefs"]


def test_goals_are_workspace_isolated(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        session_id = _start_session(client, "w-goal")
        client.post(
            "/goal/action",
            json={"session_id": session_id, "workspace_id": "w-goal", "action": "start", "title": "实现 PPO"},
        )
        assert _current(client, "w-goal") is not None
        assert _current(client, "w-other") is None
        assert client.get("/goal/list", params={"workspace_id": "w-other"}).json()["goals"] == []


def test_goal_service_rejects_empty_title(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app):
        with pytest.raises(ValueError, match="goal_title_required"):
            app.state.runtime.goals().start(workspace_id="w-goal", title="   ")
