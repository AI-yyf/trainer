"""Regression coverage for the sidecar session-start recovery contract."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.llm.provider_service import ProviderService
from app.workspace.classifier import classify_heuristic
from tests.test_api import build_client


def _profile(goal: str) -> dict[str, object]:
    return {
        "long_term_goal": goal,
        "weekly_hours": 4,
        "teaching_style": "guided",
        "answer_policy": "guided",
    }


def test_session_start_restores_latest_workspace_thread_after_sidecar_restart(tmp_path: Path) -> None:
    """The rehydration request must not replace a user's existing conversation."""
    workspace_id = "workspace-session-start-recovery"

    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Recovery workspace",
                "profile": _profile("Keep a durable learning thread"),
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        with patch.object(ProviderService, "coaching_reply", autospec=True) as coaching_reply:
            coaching_reply.return_value = (
                "Start with one list comprehension, then check the result in the Python REPL."
            )
            messaged = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "message": "Keep this user message when the sidecar restarts.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )
        assert messaged.status_code == 200, messaged.text

        generated_plan = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": ["Build one verified Python learning loop"],
                "constraints": ["Keep the first task small"],
            },
        )
        assert generated_plan.status_code == 200, generated_plan.text
        plan_id = generated_plan.json()["plan"]["id"]

        uploaded = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "list-comprehension-notes.md",
                "source": "inline://list-comprehension-notes.md",
                "content": "# Lists\nA list comprehension makes a new list.\n",
                "content_encoding": "utf-8",
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        resource_id = uploaded.json()["id"]
        indexed = client.post(
            "/resource/index",
            json={
                "workspace_id": workspace_id,
                "resource_id": resource_id,
                "enable_network": False,
            },
        )
        assert indexed.status_code == 200, indexed.text

        settings = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "response_language": "zh-CN",
                "answer_mode": "direct",
                "teaching_style": "guided",
                "context_detail": "focused",
            },
        )
        assert settings.status_code == 200, settings.text

    # A fresh app instance is the sidecar restart path used by VS Code rehydration.
    with build_client(tmp_path) as restarted_client:
        restored = restarted_client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Recovery workspace",
            },
        )
        assert restored.status_code == 200, restored.text
        restored_payload = restored.json()
        assert restored_payload["session_id"] == session_id
        assert restored_payload["plan"]["id"] == plan_id
        assert any(
            message["content"] == "Keep this user message when the sidecar restarts."
            for message in restored_payload["messages"]
        )
        assert {item["id"] for item in restored_payload["memory"]["resources"]} >= {resource_id}
        assert restored_payload["memory"]["workspace"]["response_language"] == "zh-CN"
        assert restored_payload["memory"]["workspace"]["answer_mode"] == "direct"

        # Workspaces remain isolated even when their first start happens after a restart.
        isolated = restarted_client.post(
            "/session/start",
            json={"workspace_id": "workspace-session-start-isolated", "workspace_name": "Isolated"},
        )
        assert isolated.status_code == 200, isolated.text
        assert isolated.json()["session_id"] != session_id
        assert not isolated.json()["messages"]
        assert isolated.json()["plan"] is None

        # The explicit restart command must still create a fresh Coach thread.
        fresh = restarted_client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Recovery workspace",
                "force_new": True,
            },
        )
        assert fresh.status_code == 200, fresh.text
        assert fresh.json()["session_id"] != session_id
        assert not fresh.json()["messages"]
        assert fresh.json()["plan"]["id"] == plan_id

        # A new onboarding profile also intentionally starts a distinct session.
        profile_start = restarted_client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Recovery workspace",
                "profile": _profile("Start a new learning outcome"),
            },
        )
        assert profile_start.status_code == 200, profile_start.text
        assert profile_start.json()["session_id"] not in {session_id, fresh.json()["session_id"]}
        assert profile_start.json()["profile"]["long_term_goal"] == "Start a new learning outcome"


def test_session_start_rejects_project_from_different_registered_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    other_root = tmp_path / "other-root"
    project = tmp_path / "project"
    root.mkdir()
    other_root.mkdir()
    project.mkdir()
    with build_client(tmp_path) as client:
        registered = client.post(
            "/workspace/classify",
            json={"workspace_id": "root-mismatch", "folder_path": str(project), "root_path": str(root)},
        )
        root_id = registered.json()["root_identity"]["rootId"]
        response = client.post(
            "/session/start",
            json={
                "workspace_id": "root-mismatch",
                "workspace_name": "Mismatch",
                "workspace_path": str(project),
                "root_id": root_id,
                "root_path": str(other_root),
            },
        )
    assert response.status_code == 409
    assert "not registered" in response.text


def test_session_start_persists_selected_language_across_sidecar_rehydration(tmp_path: Path) -> None:
    workspace_id = "workspace-session-language-recovery"
    workspace_path = tmp_path / "language-recovery"
    workspace_path.mkdir()

    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Language recovery",
                "workspace_path": str(workspace_path),
                "response_language": "ja-JP",
            },
        )
        assert started.status_code == 200, started.text
        assert started.json()["memory"]["workspace"]["response_language"] == "ja-JP"

    with build_client(tmp_path) as restarted_client:
        restored = restarted_client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Language recovery",
                "workspace_path": str(workspace_path),
                "force_new": True,
            },
        )

    assert restored.status_code == 200, restored.text
    restored_memory = restored.json()["memory"]
    assert restored_memory["workspace"]["response_language"] == "ja-JP"
    expected_first_look = classify_heuristic(str(workspace_path), response_language="ja-JP")
    restored_first_look = restored_memory["workspace_understanding"]["firstLookSummary"]
    assert restored_first_look["recommended_next_step"] == expected_first_look.recommended_next_step


def test_pending_plan_candidate_without_ack_is_not_live_plan_after_restart(tmp_path: Path) -> None:
    workspace_id = "workspace-pending-candidate-recovery"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Pending candidate"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Keep the acknowledged plan"],
            },
        )
        assert generated.status_code == 200, generated.text
        plan_id = generated.json()["plan"]["id"]
        current_step = generated.json()["plan"]["current_step"]
        feedback = client.post(
            "/memory/feedback",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "kind": "plan_mismatch",
                "plan_id": plan_id,
                "message": "This pending candidate must not become the live plan.",
            },
        )
        assert feedback.status_code == 200, feedback.text
        candidates = feedback.json()["memory"]["planChangeCandidates"]
        assert candidates
        assert candidates[0]["status"] == "pending"
        assert generated.json()["plan"]["id"] == plan_id

    with build_client(tmp_path) as restarted_client:
        restored = restarted_client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Pending candidate"},
        )
        assert restored.status_code == 200, restored.text
        restored_plan = restored.json()["plan"]
        assert restored_plan["id"] == plan_id
        assert restored_plan["current_step"] == current_step
        restored_candidates = restored.json()["memory"]["planChangeCandidates"]
        assert restored_candidates
        assert all(item.get("status") == "pending" for item in restored_candidates)
        assert all(item.get("impact", {}).get("formal_plan_changed") is not True for item in restored_candidates)


def test_session_message_retry_same_request_id_does_not_double_persist(tmp_path: Path) -> None:
    workspace_id = "workspace-request-id-retry"
    request_id = "retry-once-only"
    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Retry"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        with patch.object(ProviderService, "coaching_reply", autospec=True) as coaching_reply:
            coaching_reply.return_value = "Stay with the same acknowledged turn."
            first = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "message": "Persist this user message once.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                    "request_id": request_id,
                },
            )
            second = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "message": "Persist this user message once.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                    "request_id": request_id,
                },
            )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text

        def _user_copies(payload: dict) -> list[str]:
            snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else payload
            messages = []
            if isinstance(snapshot, dict):
                messages.extend(snapshot.get("messages") or [])
            messages.extend(payload.get("messages") or [])
            return [
                str(item.get("content") or "")
                for item in messages
                if isinstance(item, dict)
                and item.get("content") == "Persist this user message once."
            ]

        assert len(set(_user_copies(first.json()))) <= 1
        assert len(set(_user_copies(second.json()))) <= 1
        assert coaching_reply.call_count == 1
        live = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Retry"},
        )
        assert live.status_code == 200, live.text
        live_copies = [
            item["content"]
            for item in live.json()["messages"]
            if item.get("content") == "Persist this user message once."
        ]
        assert live_copies == ["Persist this user message once."]

    with build_client(tmp_path) as restarted_client:
        restored = restarted_client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Retry"},
        )
        assert restored.status_code == 200, restored.text
        restored_messages = [
            item["content"]
            for item in restored.json()["messages"]
            if item.get("content") == "Persist this user message once."
        ]
        assert restored_messages == ["Persist this user message once."]
