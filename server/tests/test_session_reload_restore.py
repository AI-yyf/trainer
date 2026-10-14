"""Reload-restore behavior: saved sessions survive a sidecar reload.

保存会话 → 模拟重载 → 会话与消息恢复. A "reload" is a brand-new app/runtime
over the same data directory (the TestClient pair below shares ``tmp_path``),
which is exactly what the extension host sees when VS Code restarts and
reconnects to a fresh sidecar process.

Pinned contract:

* ``/memory/summary?session_id=...`` serves the stored transcript and stamps
  ``sessionHistoryRestored`` after the reload.
* ``/session/activate`` restores the requested session (the host's stored
  session id is verified through it on reload).
* ``/session/start`` without an initial message resumes the workspace's latest
  thread and returns the id actually in use — the fallback the host now uses
  when a persisted session id can no longer be restored.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.provider_service import ProviderService
from tests.test_api import build_client

WORKSPACE = "workspace-session-reload"


def _start(client, workspace: str = WORKSPACE, *, force_new: bool = False) -> str:
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace,
            "workspace_name": "trainer-reload",
            # Plain starts resume the workspace's latest thread; force_new is
            # the explicit "start over" the host also sends.
            **({"force_new": True} if force_new else {}),
        },
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def _say(client, session_id: str, text: str, workspace: str = WORKSPACE) -> None:
    with patch.object(ProviderService, "coaching_reply", autospec=True) as coaching_reply:
        coaching_reply.return_value = f"教练回复：{text}"
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace,
                "message": text,
                "response_language": "zh-CN",
            },
        )
    assert response.status_code == 200


def test_reload_restores_session_and_messages_through_memory_summary(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        session_id = _start(client)
        _say(client, session_id, "RELOAD-MARKER 重载后恢复我。")

    # Simulated reload: fresh app + runtime over the same data directory.
    with build_client(tmp_path) as client:
        response = client.get(
            "/memory/summary",
            params={"workspace_id": WORKSPACE, "session_id": session_id},
        )
        assert response.status_code == 200
        body = response.json()
        contents = [message.get("content") for message in body.get("messages", [])]
        assert any("RELOAD-MARKER" in str(content) for content in contents), contents
        assert body.get("sessionHistoryRestored") is True

        # The host verifies the stored id through /session/activate on reload.
        activate = client.post(
            "/session/activate",
            json={"session_id": session_id, "workspace_id": WORKSPACE},
        )
        assert activate.status_code == 200
        activated = activate.json()
        assert activated["session_id"] == session_id
        activated_contents = [
            message.get("content") for message in activated["snapshot"]["messages"]
        ]
        assert any("RELOAD-MARKER" in str(content) for content in activated_contents)


def test_reload_plain_start_resumes_the_latest_thread_for_the_fallback(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        older = _start(client)
        _say(client, older, "OLDER-MARKER 早期会话。")
        latest = _start(client, force_new=True)
        _say(client, latest, "LATEST-MARKER 最近的会话。")
    assert latest != older

    # Reload, then a plain /session/start (no initial message) — the host's
    # fallback when the persisted session id cannot be restored. It must hand
    # back the latest thread and its transcript, not an empty new session.
    with build_client(tmp_path) as client:
        response = client.post(
            "/session/start",
            json={"workspace_id": WORKSPACE, "workspace_name": "trainer-reload"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == latest
        contents = [message.get("content") for message in body.get("messages", [])]
        assert any("LATEST-MARKER" in str(content) for content in contents), contents
        assert not any("OLDER-MARKER" in str(content) for content in contents)
