from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app


def test_explicit_function_guidance_first_turn_stays_out_of_onboarding() -> None:
    async def fake_create_chat_completion(
        self,
        *,
        client,
        model,
        messages,
        temperature,
        max_tokens,
        stream=False,
    ):
        mock_choice = MagicMock()
        mock_choice.message.content = (
            "Start from one live call site and read the contract before changing code."
        )
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response, model

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=fake_create_chat_completion,
    ):
        client = TestClient(app)
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-first-turn-function-guidance",
                "workspace_name": "trainer-first-turn-function-guidance",
                "profile": {
                    "long_term_goal": "Use Trainer as a VS Code function-guidance coach",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "In VS Code, coach me through understanding a function contract with hover, signature help, and Go to Definition. Keep it concrete.",
                "response_language": "en-US",
                "provider": {
                    "name": "preview-provider",
                    "baseUrl": "https://api.openai.com/v1",
                    "model": "gpt-4o-mini",
                },
                "api_key": "sk-preview",
            },
        )

    assert message_response.status_code == 200, message_response.text
    payload = message_response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    assert payload["coach_turn"]["next_step"]
    assert "call site" in payload["reply"]["content"].lower()
