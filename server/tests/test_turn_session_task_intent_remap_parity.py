"""Parity: no-live-plan task/next_task remap on turn + session routes.

/turn remaps intent task|next_task → coach via request_with_workspace_defaults.
Prove /turn/stream and /session/message(+stream) also do not mint TaskSpec.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from tests.test_router_stream_scenarios import (
    completed_stream_response,
    mark_provider_capabilities_verified,
)


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer task-intent remap parity",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-task-intent-remap.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(_settings(tmp_path / "data"))
    provider = ProviderConfig(
        name="test-openai-compatible",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={
            "chat": True,
            "responses": True,
            "vision": False,
            "embeddings": True,
            "tools": False,
            "json_schema": False,
            "streaming": True,
        },
    )
    runtime = app.state.runtime
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
    runtime.provider_service = ProviderService(
        config=provider,
        api_key="sk-test-not-a-real-key-aaaaaaaa",
    )
    runtime.provider_service_cache.clear()
    return TestClient(app)


def _task_title(body: dict) -> str:
    task = (
        body.get("current_task")
        or body.get("currentTask")
        or (body.get("snapshot") or {}).get("current_task")
        or (body.get("snapshot") or {}).get("currentTask")
        or {}
    )
    if not isinstance(task, dict):
        return ""
    return str(task.get("title") or "").strip()


def _action_names(body: dict) -> set[str]:
    actions = body.get("suggested_actions") or body.get("suggestedActions") or []
    return {
        str(item.get("action") or "")
        for item in actions
        if isinstance(item, dict) and str(item.get("action") or "").strip()
    }


@pytest.mark.parametrize("intent", ["task", "next_task"])
@pytest.mark.parametrize("path", ["/turn", "/turn/stream"])
def test_turn_routes_remap_task_intent_without_live_plan(
    tmp_path: Path,
    path: str,
    intent: str,
) -> None:
    """No live plan: task/next_task must coach/hint — no TaskSpec mint."""

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Stay with coaching. Do not invent a task."

    with (
        _client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Stay with coaching. Do not invent a task."),
        ),
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
    ):
        workspace_id = f"ws-remap-{intent}-{path.replace('/', '-')}"
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Remap lab"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        runtime = client.app.state.runtime
        assert runtime.repository.get_latest_plan(workspace_id) is None
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

        next_calls: list[object] = []
        specify_calls: list[object] = []
        original_next = runtime.planner_service.next_task
        original_specify = runtime.spec_service.specify

        def _track_next(*args: object, **kwargs: object):
            next_calls.append((args, kwargs))
            return original_next(*args, **kwargs)

        def _track_specify(*args: object, **kwargs: object):
            specify_calls.append((args, kwargs))
            return original_specify(*args, **kwargs)

        with (
            patch.object(runtime.planner_service, "next_task", _track_next),
            patch.object(runtime.spec_service, "specify", _track_specify),
        ):
            response = client.post(
                path,
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": intent,
                    "message": "Give me the next task. Turn this into a focused exercise.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )
        assert next_calls == []
        assert specify_calls == []
        assert not _task_title(body)
        assert runtime.repository.get_latest_plan(workspace_id) is None
        actions = _action_names(body)
        assert "task" not in actions
        assert "next_task" not in actions
        assert "plan" not in actions
        assert "hint" in actions or actions <= {"hint", "review"}
        scenario = str(
            ((body.get("coach_turn") or body.get("coachTurn") or {}).get("scenario") or "")
        ).strip()
        assert scenario in {"", "general", "coach", "hint", "onboarding", "review"}
        assert scenario not in {"task", "next_task"}


@pytest.mark.parametrize("path", ["/session/message", "/session/message/stream"])
def test_session_message_routes_chat_next_task_without_live_plan_does_not_mint(
    tmp_path: Path,
    path: str,
) -> None:
    """Session routes have no intent field; next-task chat must not mint TaskSpec."""

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Stay with coaching. Do not invent a task."

    with (
        _client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Stay with coaching. Do not invent a task."),
        ),
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
    ):
        workspace_id = f"ws-session-remap-{path.replace('/', '-')}"
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Session remap lab"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        runtime = client.app.state.runtime
        assert runtime.repository.get_latest_plan(workspace_id) is None
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

        next_calls: list[object] = []
        specify_calls: list[object] = []
        original_next = runtime.planner_service.next_task
        original_specify = runtime.spec_service.specify

        def _track_next(*args: object, **kwargs: object):
            next_calls.append((args, kwargs))
            return original_next(*args, **kwargs)

        def _track_specify(*args: object, **kwargs: object):
            specify_calls.append((args, kwargs))
            return original_specify(*args, **kwargs)

        with (
            patch.object(runtime.planner_service, "next_task", _track_next),
            patch.object(runtime.spec_service, "specify", _track_specify),
        ):
            response = client.post(
                path,
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    # Intent is ignored on SessionMessageRequest (extra=ignore);
                    # include it anyway to mirror host payloads that still send it.
                    "intent": "next_task",
                    "message": "Give me the next task. Turn this into a focused exercise.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )
        assert response.status_code == 200, response.text
        body = (
            completed_stream_response(response.text)
            if path.endswith("/stream")
            else response.json()
        )
        assert next_calls == []
        assert specify_calls == []
        assert not _task_title(body)
        assert runtime.repository.get_latest_plan(workspace_id) is None
        actions = _action_names(body)
        assert "task" not in actions
        assert "next_task" not in actions
        assert "plan" not in actions
        assert "hint" in actions or actions <= {"hint", "review"}
        scenario = str(
            ((body.get("coach_turn") or body.get("coachTurn") or {}).get("scenario") or "")
        ).strip()
        assert scenario not in {"task", "next_task"}
