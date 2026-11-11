"""Goal lifecycle events land in the unified ledger (§P1-3c).

A goal start, a real activity and a completion are facts about learning, so
they must be auditable in the same ledger as training — with idempotency keys
so retries never inflate the history.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
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
