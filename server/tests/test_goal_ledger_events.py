"""Goal lifecycle events land in the unified ledger (§P1-3c).

A goal start, a real activity and a completion are facts about learning, so
they must be auditable in the same ledger as training — with idempotency keys
so retries never inflate the history.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.goal.service import GoalService
from app.main import create_app


def build_app(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Goal Ledger Test",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="goal-ledger.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_goal_start_records_a_ledger_event(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    runtime = client.app.state.runtime
    goal = runtime.goals().start(
        workspace_id="w-ledger",
        title="3 天内独立解释 PPO 裁剪目标",
        source="user_explicit",
    )
    entries = [
        entry
        for entry in runtime.event_ledger.all_entries()
        if entry.event_type == "goal_started"
    ]
    assert len(entries) == 1
    assert entries[0].payload_ref.get("goal_id") == goal.goal_id
    assert entries[0].payload_ref.get("source") == "user_explicit"


def test_goal_start_is_idempotent_in_the_ledger(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    runtime = client.app.state.runtime
    goals = runtime.goals()
    goals.start(workspace_id="w-ledger", title="学会 FSRS", source="user_explicit")
    # A second explicit start that resolves to the same active goal must not
    # append a second ledger entry (the service keeps one active focus).
    goals.start(workspace_id="w-ledger", title="学会 FSRS", source="user_explicit")
    entries = [
        entry
        for entry in runtime.event_ledger.all_entries()
        if entry.event_type == "goal_started"
    ]
    assert len(entries) == 1


def test_goal_activity_records_with_idempotent_key(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    runtime = client.app.state.runtime
    goals = runtime.goals()
    goals.start(workspace_id="w-ledger", title="学会 FSRS", source="user_explicit")
    goals.record_activity(
        workspace_id="w-ledger",
        kind="verification",
        result="passed",
        summary="通过了受控验证",
        event_key="verify-1",
    )
    goals.record_activity(
        workspace_id="w-ledger",
        kind="verification",
        result="passed",
        summary="通过了受控验证",
        event_key="verify-1",
    )
    events = [
        entry
        for entry in runtime.event_ledger.all_entries()
        if entry.event_type == "goal_activity_recorded"
    ]
    assert len(events) == 1
    assert events[0].payload_ref.get("kind") == "verification"


def test_goal_activity_replay_survives_history_truncation_and_restart(tmp_path: Path) -> None:
    runtime = build_app(tmp_path).app.state.runtime
    goals = GoalService(runtime.repository, max_activities=1, event_ledger=runtime.event_ledger)
    goals.start(workspace_id="workspace", title="Review results")
    for key in ("first", "second"):
        goals.record_activity(
            workspace_id="workspace", kind="review", event_key=key, summary=key,
        )
    restarted = build_app(tmp_path).app.state.runtime
    replayed = restarted.goals().record_activity(
        workspace_id="workspace", kind="review", event_key="first", summary="Duplicate",
    )

    assert replayed.activity_count == 2
    assert [item.summary for item in replayed.activities] == ["second"]
    assert restarted.event_ledger.count(event_type="goal_activity_recorded") == 2


def test_goal_activity_does_not_commit_when_event_write_fails(tmp_path: Path, monkeypatch) -> None:
    runtime = build_app(tmp_path).app.state.runtime
    goals = runtime.goals()
    goals.start(workspace_id="workspace", title="Review results")
    record_event = runtime.event_ledger.record_event

    def failing_event(*args, **kwargs):
        record_event(*args, **kwargs)
        raise RuntimeError("Ledger write failed")

    monkeypatch.setattr(runtime.event_ledger, "record_event", failing_event)
    with pytest.raises(RuntimeError, match="Ledger write failed"):
        goals.record_activity(workspace_id="workspace", kind="review", event_key="first")
    assert goals.current("workspace").activity_count == 0
    assert runtime.event_ledger.count(event_type="goal_activity_recorded") == 0


def test_goal_completion_records_once(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    runtime = client.app.state.runtime
    goals = runtime.goals()
    goals.start(workspace_id="w-ledger", title="学会 FSRS", source="user_explicit")
    goals.complete(workspace_id="w-ledger")
    goals.complete(workspace_id="w-ledger")
    events = [
        entry
        for entry in runtime.event_ledger.all_entries()
        if entry.event_type == "goal_completed"
    ]
    assert len(events) == 1
    assert events[0].reversibility == "reversible"


def test_events_persist_across_app_restart(tmp_path: Path) -> None:
    first = build_app(tmp_path)
    runtime = first.app.state.runtime
    goal = runtime.goals().start(
        workspace_id="w-ledger",
        title="学会 FSRS",
        source="user_explicit",
    )
    runtime.goals().record_activity(
        workspace_id="w-ledger",
        kind="verification",
        result="passed",
        event_key="verify-9",
    )

    restarted = build_app(tmp_path)
    restarted_runtime = restarted.app.state.runtime
    started = [
        entry
        for entry in restarted_runtime.event_ledger.all_entries()
        if entry.event_type == "goal_started"
    ]
    activity = [
        entry
        for entry in restarted_runtime.event_ledger.all_entries()
        if entry.event_type == "goal_activity_recorded"
    ]
    assert len(started) == 1
    assert len(activity) == 1
    assert started[0].payload_ref.get("goal_id") == goal.goal_id



def _started_goal_id(runtime) -> str:
    entries = [
        entry
        for entry in runtime.event_ledger.all_entries()
        if entry.event_type == "goal_started"
    ]
    return str(entries[-1].payload_ref.get("goal_id"))


def test_recompute_rebuilds_goal_from_effective_ledger_events(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    runtime = client.app.state.runtime
    goals = runtime.goals()
    goals.start(workspace_id="w-ledger", title="学会 FSRS", source="user_explicit")
    goals.record_activity(
        workspace_id="w-ledger",
        kind="verification",
        result="passed",
        summary="第一次受控验证通过",
        event_key="verify-1",
    )
    goals.record_activity(
        workspace_id="w-ledger",
        kind="training_attempt",
        result="failed",
        summary="第二次练习未通过",
        event_key="attempt-2",
    )
    goal_id = _started_goal_id(runtime)

    rebuilt = goals.recompute_goal_from_ledger("w-ledger", goal_id)
    assert rebuilt is not None
    assert rebuilt["title"] == "学会 FSRS"
    assert rebuilt["source"] == "user_explicit"
    assert rebuilt["status"] == "active"
    assert rebuilt["activity_count"] == 2


def test_recompute_excludes_reversed_activity(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    runtime = client.app.state.runtime
    goals = runtime.goals()
    goals.start(workspace_id="w-ledger", title="学会 FSRS", source="user_explicit")
    goals.record_activity(
        workspace_id="w-ledger",
        kind="verification",
        result="passed",
        event_key="verify-1",
    )
    goals.record_activity(
        workspace_id="w-ledger",
        kind="training_attempt",
        result="failed",
        event_key="attempt-2",
    )
    activity_events = [
        entry
        for entry in runtime.event_ledger.all_entries()
        if entry.event_type == "goal_activity_recorded"
    ]
    reversed_id = str(activity_events[0].event_id)
    runtime.event_ledger.reverse_event(reversed_id, reason="误记的活动")

    rebuilt = runtime.goals().recompute_goal_from_ledger("w-ledger", _started_goal_id(runtime))
    assert rebuilt is not None
    assert rebuilt["activity_count"] == 1
    assert not rebuilt["completed"]


def test_recompute_returns_none_for_unknown_goal(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    runtime = client.app.state.runtime
    assert runtime.goals().recompute_goal_from_ledger("w-ledger", "goal-unknown") is None


def test_recompute_marks_completion(tmp_path: Path) -> None:
    client = build_app(tmp_path)
    runtime = client.app.state.runtime
    goals = runtime.goals()
    goal = goals.start(workspace_id="w-ledger", title="学会 FSRS", source="user_explicit")
    goals.complete(workspace_id="w-ledger")

    rebuilt = runtime.goals().recompute_goal_from_ledger("w-ledger", goal.goal_id)
    assert rebuilt is not None
    assert rebuilt["completed"] is True
    assert rebuilt["status"] == "completed"


def test_archived_and_completed_goals_keep_distinct_history_after_restart(tmp_path: Path) -> None:
    scope = {"workspace_id": "w-ledger"}
    first = build_app(tmp_path)
    draft = first.post("/goal/action", json={**scope, "action": "start", "title": "Implement a queue"})
    archived_id = draft.json()["goal"]["goalId"]
    focused = first.post("/goal/action", json={**scope, "action": "start", "title": "Explain FIFO"})
    focused_id = focused.json()["goal"]["goalId"]

    archived = first.post("/goal/action", json={**scope, "action": "archive", "goalId": archived_id})
    assert archived.status_code == 200
    assert archived.json()["goal"]["status"] == "archived"
    assert archived.json()["goal"]["archivedAt"]
    assert archived.json()["goal"]["completedAt"] is None
    assert archived.json()["currentGoal"]["goalId"] == focused_id

    for action in ("archive", "resume", "complete"):
        replay = first.post("/goal/action", json={**scope, "action": action, "goalId": archived_id})
        assert replay.json()["goal"]["status"] == "archived"

    result = first.post("/goal/action", json={**scope, "action": "complete", "goalId": focused_id})
    assert result.json()["goal"]["completionBasis"] == "user_confirmed"
    assert result.json()["goal"]["completedAt"]
    assert result.json()["currentGoal"] is None

    restarted = build_app(tmp_path)
    goals = restarted.get("/goal/list", params=scope).json()["goals"]
    assert {goal["goalId"]: goal["status"] for goal in goals} == {
        archived_id: "archived", focused_id: "completed",
    }
    assert restarted.get("/goal/current", params=scope).json()["goal"] is None
    runtime = restarted.app.state.runtime
    entries = [entry for entry in runtime.event_ledger.all_entries() if entry.scope == "goal"]
    assert [entry.event_type for entry in entries] == [
        "goal_started", "goal_started", "goal_archived", "goal_completed",
    ]
    projection = runtime.goals().recompute_goal_from_ledger(scope["workspace_id"], archived_id)
    assert projection and projection["status"] == "archived" and not projection["completed"]
    assert not runtime.memory_service.global_memory().capability_profile
