"""Regression coverage for durable task specifications."""

from __future__ import annotations

from pathlib import Path

from tests.test_api import build_client


def test_specified_task_survives_sidecar_restart(tmp_path: Path) -> None:
    workspace_id = "workspace-task-spec-persistence"

    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Task persistence workspace",
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Persist a specified task under a live plan"],
            },
        )
        assert generated.status_code == 200, generated.text

        specified = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "natural_language_goal": (
                    "Build a formatter for status messages. "
                    "Input: a message and severity. "
                    "Output: one readable formatted line."
                ),
            },
        )
        assert specified.status_code == 200, specified.text
        task = specified.json()
        assert str((task.get("metadata") or {}).get("plan_id") or "").strip()
    with build_client(tmp_path) as restarted_client:
        restored = restarted_client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Task persistence workspace",
            },
        )

    assert restored.status_code == 200, restored.text
    restored_payload = restored.json()
    assert restored_payload["session_id"] == session_id
    assert restored_payload["current_task"] == task
