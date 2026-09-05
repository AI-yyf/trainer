from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from provider_fixtures import seed_verified_capabilities

from app.core.models import ProviderConfig
from app.llm.provider_service import ProviderService
from app.training.card_request import message_requests_explicit_training_card
from tests.test_api import build_client


class _ScriptedGenerateCardProvider:
    protocol = "openai_chat_completions"

    def __init__(self) -> None:
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
                        "id": "auto-mint-understand-card",
                        "name": "generate_training_card",
                        "arguments": {
                            "focus_area": "VS Code remote workspace",
                            "target_skill": "name the remote boundary",
                            "card_type": "practice",
                            "why_now": "The understand turn felt ready for practice.",
                        },
                    }
                ],
            }
        return {
            "content": "Stay with the first-look next step. Do not invent a card.",
            "tool_calls": [],
        }


def test_explicit_training_card_language_bar_matches_router_and_tool() -> None:
    assert message_requests_explicit_training_card(
        "Create a practice card for debugging a Python traceback in VS Code."
    )
    assert message_requests_explicit_training_card("Give me a flash card for Remote SSH.")
    assert not message_requests_explicit_training_card(
        "Help me understand this VS Code remote workspace first, then verify one tiny step."
    )
    assert not message_requests_explicit_training_card("What is a training card?")
    assert not message_requests_explicit_training_card("continue")


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
    ("answer_mode", "message"),
    (
        ("auto", "Explain how to inspect a Python traceback in VS Code."),
        (
            "guided",
            "Teach me how to debug Python step by step, then help me verify the result.",
        ),
        (
            "coach-first",
            "\u8bf7\u6559\u6211\u5982\u4f55\u5728 VS Code \u91cc\u6392\u67e5 Python \u62a5\u9519\uff0c\u518d\u5e2e\u6211\u9a8c\u8bc1\u7ed3\u679c\u3002",
        ),
    ),
)
def test_normal_coach_requests_do_not_open_training_without_consent(
    tmp_path: Path,
    answer_mode: str,
    message: str,
) -> None:
    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Start with one concrete observation, then verify it."),
        ) as coaching_reply,
    ):
        response = client.post(
            "/turn",
            json={
                "workspace_id": f"workspace-normal-coach-{answer_mode}",
                "intent": "coach",
                "message": message,
                "response_language": "en-US",
                "answer_mode": answer_mode,
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    coaching_reply.assert_awaited_once()
    assert payload["snapshot"]["memory"]["active_training_card_routing"] is None
    assert payload["reply"]["content"] == "Start with one concrete observation, then verify it."


@pytest.mark.parametrize(
    ("message", "expected_card_type"),
    (
        ("Create a practice card for debugging a Python traceback in VS Code.", "practice"),
        ("Please give me a flash card for VS Code Remote SSH basics.", "flash"),
        ("\u7ed9\u6211\u4e00\u9053\u7ec3\u4e60\u9898\uff0c\u5e2e\u6211\u590d\u4e60 Python \u8c03\u8bd5\u3002", "practice"),
    ),
)
def test_explicit_practice_requests_do_not_mint_from_chat(
    tmp_path: Path,
    message: str,
    expected_card_type: str,
) -> None:
    """Composer chat must not mint; POST /training/generate-card remains the binder."""
    del expected_card_type
    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Stay hint-only. Use Training generate-card to mint."),
        ),
    ):
        response = client.post(
            "/turn",
            json={
                "workspace_id": f"workspace-explicit-training-chat-{hash(message) & 0xFFFF:x}",
                "intent": "coach",
                "message": message,
                "response_language": "en-US",
                "answer_mode": "coach-first",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    memory = body["snapshot"]["memory"]
    assert memory.get("active_training_card_routing") is None
    workspace = memory.get("workspace") or {}
    assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
    assert body["snapshot"].get("plan") in (None, {})
    assert body["snapshot"].get("current_task") in (None, {})


@pytest.mark.parametrize(
    "message",
    (
        "What is a training card?",
        "\u8bad\u7ec3\u5361\u662f\u4ec0\u4e48\uff1f",
    ),
)
def test_training_card_questions_stay_in_coach(tmp_path: Path, message: str) -> None:
    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="A training card is a focused practice prompt."),
        ) as coaching_reply,
    ):
        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-training-card-question",
                "intent": "coach",
                "message": message,
                "response_language": "en-US",
                "answer_mode": "auto",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    coaching_reply.assert_awaited_once()
    assert response.json()["snapshot"]["memory"]["active_training_card_routing"] is None


@pytest.mark.parametrize(
    ("workspace_id", "message", "expected_scenario"),
    (
        (
            "workspace-auto-learn-try-verify",
            "Teach me VS Code Remote SSH with a learn -> try -> verify loop.",
            "remote_workspace",
        ),
        (
            "workspace-auto-understand-first",
            "Help me understand this VS Code remote workspace first, then verify one tiny step.",
            "remote_workspace",
        ),
        (
            "workspace-auto-diagnose-learn-first",
            "Diagnose this VS Code debug loop. Learn first, then verify one checkpoint.",
            "debug_loop",
        ),
    ),
)
def test_auto_learn_first_turn_does_not_mint_a_training_card(
    tmp_path: Path,
    workspace_id: str,
    message: str,
    expected_scenario: str,
) -> None:
    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Stay with the first-look next step. Do not invent a card."),
        ),
    ):
        response = client.post(
            "/turn",
            json={
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": message,
                "response_language": "en-US",
                "answer_mode": "auto",
                "use_agent_loop": False,
            },
        )
        stored_cards = client.app.state.runtime.memory_service.get_cards(workspace_id)

    assert response.status_code == 200, response.text
    payload = response.json()
    snapshot = payload["snapshot"]
    routing = snapshot["memory"]["active_training_card_routing"]
    assert routing is None
    assert payload["coach_turn"]["scenario"] == expected_scenario
    assert snapshot.get("plan") in (None, {})
    assert snapshot.get("current_task") in (None, {})
    assert stored_cards == []
    orientation = snapshot.get("coach_orientation") or snapshot.get("coachOrientation") or {}
    assert orientation.get("primary_action") != "open_training"
    assert orientation.get("object_kind") != "training"
    assert "Ship one invented card" not in str(orientation.get("next_step") or "")


def test_coach_first_keeps_the_same_learn_try_verify_request_in_coach(tmp_path: Path) -> None:
    message = "Teach me VS Code Remote SSH with a learn -> try -> verify loop."
    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="We will start with the remote boundary."),
        ) as coaching_reply,
    ):
        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-coach-first-learn-try-verify",
                "intent": "coach",
                "message": message,
                "response_language": "en-US",
                "answer_mode": "coach-first",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    coaching_reply.assert_awaited_once()
    assert response.json()["snapshot"]["memory"]["active_training_card_routing"] is None


def test_agent_loop_understand_turn_does_not_mint_via_generate_training_card(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = _ScriptedGenerateCardProvider()

    def build_agent_provider(_self: ProviderService, **_kwargs: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)
    workspace_id = "workspace-understand-no-agent-card"
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
                "workspace_name": "Understand without invented card",
                "profile": {
                    "long_term_goal": "Understand first without inventing a card",
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

        stored_cards = client.app.state.runtime.memory_service.get_cards(workspace_id)

    assert response.status_code == 200, response.text
    payload = response.json()
    snapshot = payload["snapshot"]
    tool_names = [
        event["name"]
        for event in (payload.get("agent_meta") or {}).get("tool_events") or []
        if event.get("type") == "tool_call"
    ]
    assert "generate_training_card" not in {
        schema.get("function", {}).get("name")
        for schema in (scripted.tools_seen[0] or [])
    }
    assert stored_cards == []
    assert snapshot["memory"]["active_training_card_routing"] is None
    assert snapshot.get("plan") in (None, {})
    assert snapshot.get("current_task") in (None, {})
    if "generate_training_card" in tool_names:
        assert all(
            event.get("result", {}).get("ok") is False
            for event in (payload.get("agent_meta") or {}).get("tool_events") or []
            if event.get("type") == "tool_result" and event.get("name") == "generate_training_card"
        )
    orientation = snapshot.get("coach_orientation") or snapshot.get("coachOrientation") or {}
    assert orientation.get("primary_action") != "open_training"
    assert orientation.get("object_kind") != "training"
    assert "Ship one invented card" not in str(orientation.get("next_step") or "")
    status = snapshot.get("plan_runtime_status") or snapshot.get("planRuntimeStatus") or {}
    next_action = str(
        status.get("next_training_action") or status.get("nextTrainingAction") or ""
    )
    assert next_action != "Ship one invented card"
    assert not next_action.startswith("Practice:")
