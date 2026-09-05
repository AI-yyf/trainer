import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.provider_service import ProviderService
from tests.test_api import build_client


def test_session_history_summary_prefers_latest_user_marker_over_assistant_tail(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-history-user-marker",
                "workspace_name": "trainer-history-user-marker",
                "profile": {
                    "long_term_goal": "Keep user marker visible in session history summary",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        with patch.object(ProviderService, "coaching_reply", autospec=True) as coaching_reply:
            coaching_reply.return_value = (
                "收到，我会先给出一个较长的教练解释，并保持纯对话，不进入训练或计划。"
            )
            message_response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-history-user-marker",
                    "message": "NEW-WORKSPACE-MARKER 先别进训练，也别改计划。",
                    "response_language": "zh-CN",
                },
            )
        assert message_response.status_code == 200

        history_response = client.get(
            "/session/history",
            params={
                "workspace_id": "workspace-history-user-marker",
                "session_id": session_id,
            },
        )
        assert history_response.status_code == 200
        history_items = history_response.json()
        assert history_items
        assert "NEW-WORKSPACE-MARKER" in history_items[0]["summary"]
