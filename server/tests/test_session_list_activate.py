import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.provider_service import ProviderService
from tests.test_api import build_client


WORKSPACE = "workspace-session-list-activate"


def _start(client, workspace: str = WORKSPACE) -> str:
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace,
            "workspace_name": "trainer-session-list",
            "profile": {
                "long_term_goal": "Session list coverage",
                "weekly_hours": 3,
                "teaching_style": "guided",
                "answer_policy": "guided",
            },
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


def test_session_list_returns_workspace_sessions_newest_first(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        first = _start(client)
        _say(client, first, "FIRST-MARKER 第一条会话。")
        second = _start(client)
        _say(client, second, "SECOND-MARKER 第二条会话。")

        response = client.get("/session/list", params={"workspace_id": WORKSPACE})
        assert response.status_code == 200
        items = response.json()
        ids = [item["session_id"] for item in items]
        assert ids[:2] == [second, first]
        by_id = {item["session_id"]: item for item in items}
        assert by_id[first]["message_count"] == 2
        assert "FIRST-MARKER" in by_id[first]["summary"]
        assert "SECOND-MARKER" in by_id[second]["summary"]
        assert by_id[second]["is_active"] is True
        assert by_id[first].get("is_active") in (False, None)


def test_session_activate_restores_requested_session(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        first = _start(client)
        _say(client, first, "RESTORE-MARKER 恢复我。")
        second = _start(client)
        _say(client, second, "OTHER-MARKER 别的会话。")

        response = client.post(
            "/session/activate",
            json={"session_id": first, "workspace_id": WORKSPACE},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == first
        contents = [m.get("content") for m in body["snapshot"]["messages"]]
        assert any("RESTORE-MARKER" in str(content) for content in contents)
        assert not any("OTHER-MARKER" in str(content) for content in contents)

        # The activated session is registered server-side, so a follow-up
        # message continues it instead of the previously-latest session.
        _say(client, first, "RESTORE-MARKER 继续说。", workspace=WORKSPACE)
        history = client.get(
            "/session/history",
            params={"workspace_id": WORKSPACE, "session_id": first},
        )
        assert history.status_code == 200


def test_session_activate_rejects_foreign_workspace(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        first = _start(client)
        _say(client, first, "MARKER。")
        response = client.post(
            "/session/activate",
            json={"session_id": first, "workspace_id": "workspace-foreign-other"},
        )
        assert response.status_code == 404
