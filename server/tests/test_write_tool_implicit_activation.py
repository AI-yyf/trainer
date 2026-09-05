from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from provider_fixtures import seed_verified_capabilities

from app.core.models import ProviderConfig
from app.llm.provider_service import ProviderService
from app.memory.note_request import message_requests_explicit_learning_note
from tests.test_api import build_client


def test_explicit_learning_note_language_bar_stays_tight() -> None:
    assert message_requests_explicit_learning_note(
        "Save a learning note that I prefer tiny verified slices."
    )
    assert message_requests_explicit_learning_note("Record a learning note about the remote boundary.")
    assert message_requests_explicit_learning_note("\u8bb0\u4e0b\u4e00\u6761\u5b66\u4e60\u7b14\u8bb0")
    assert not message_requests_explicit_learning_note(
        "Help me understand this VS Code remote workspace first, then verify one tiny step."
    )
    assert not message_requests_explicit_learning_note("What is a learning note?")
    assert not message_requests_explicit_learning_note("Remember to check the remote host label.")
    assert not message_requests_explicit_learning_note("continue")


class _ScriptedWriteToolProvider:
    protocol = "openai_chat_completions"

    def __init__(self, tool_name: str, arguments: dict[str, Any]) -> None:
        self.tool_name = tool_name
        self.arguments = arguments
        self.calls = 0
        self.tools_seen: list[list[dict[str, Any]] | None] = []
        self.attachments_will_be_sent = lambda: False

    async def call(
        self,
        _messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        self.tools_seen.append(tools)
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": f"auto-mint-understand-{self.tool_name}",
                        "name": self.tool_name,
                        "arguments": self.arguments,
                    }
                ],
            }
        return {
            "content": "Stay with the first-look next step. Do not invent a note or resource.",
            "tool_calls": [],
        }


def _training_provider_payload() -> dict[str, object]:
    return {
        "name": "deterministic-agent",
        "base_url": "https://provider.invalid/v1",
        "api_key_ref": "test-only",
        "model": "test-model",
        "protocol": "openai_chat_completions",
        "capabilities": {"tools": True, "streaming": False},
    }


@pytest.mark.parametrize(
    ("workspace_id", "tool_name", "arguments"),
    (
        (
            "workspace-understand-no-agent-note",
            "record_learning_note",
            {"note": "Ship one invented note", "kind": "preference"},
        ),
        (
            "workspace-understand-no-agent-import",
            "import_resource_url",
            {"url": "https://example.invalid/source"},
        ),
        (
            "workspace-understand-no-agent-organize",
            "organize_resources",
            {"operations": [{"op": "mkdir", "path": "invented"}]},
        ),
    ),
)
def test_agent_loop_understand_turn_does_not_mint_write_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workspace_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> None:
    scripted = _ScriptedWriteToolProvider(tool_name, arguments)

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    with build_client(tmp_path, configure_provider=False) as client:
        seed_verified_capabilities(
            client.app.state.runtime,
            ProviderConfig.model_validate(_training_provider_payload()),
            "test-only-key",
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Understand without invented write",
                "profile": {
                    "long_term_goal": "Understand first without inventing a note or resource",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": (
                    "Help me understand this VS Code remote workspace first, then verify one tiny step."
                ),
                "response_language": "en-US",
                "answer_mode": "guided",
                "use_agent_loop": True,
                "provider": _training_provider_payload(),
                "api_key": "test-only-key",
            },
        )

        runtime = client.app.state.runtime
        stored_cards = runtime.memory_service.get_cards(workspace_id)
        snapshot_memory = runtime.memory_service.snapshot(workspace_id)
        persisted_plan = runtime.repository.get_latest_plan(workspace_id)
        stored_resources = runtime.repository.list_resources(workspace_id)

    assert response.status_code == 200, response.text
    payload = response.json()
    snapshot = payload["snapshot"]
    schema_names = {
        schema.get("function", {}).get("name")
        for schema in (scripted.tools_seen[0] or [])
    }
    assert tool_name not in schema_names
    assert persisted_plan is None
    assert snapshot.get("plan") in (None, {})
    assert snapshot.get("current_task") in (None, {})
    assert stored_cards == []
    assert stored_resources == []
    assert snapshot["memory"]["active_training_card_routing"] is None
    observations = snapshot_memory.teaching_observations
    assert "Ship one invented note" not in observations
    assert not any("invented" in str(item).lower() for item in observations)
