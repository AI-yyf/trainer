"""Completed session-request dedup must not drop honesty stamps after later hydrate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.routers import overlay_session_response_honesty_stamps
from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.memory.workspace_recovery import PLAN_RUNTIME_KEY
from tests.test_router_stream_scenarios import mark_provider_capabilities_verified


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Session Dedup Honesty",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-session-dedup-honesty.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(_settings(tmp_path))
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


def _completed_session_cache(app) -> dict:
    routes = []
    for route in app.routes:
        if getattr(route, "path", None) == "/session/message":
            routes.append(route)
        original = getattr(route, "original_router", None)
        routes.extend(
            child
            for child in getattr(original, "routes", [])
            if getattr(child, "path", None) == "/session/message"
        )
    for route in routes:
        endpoint = getattr(route, "endpoint", None)
        closure = getattr(endpoint, "__closure__", None)
        if endpoint is None or closure is None:
            continue
        names = endpoint.__code__.co_freevars
        for name, cell in zip(names, closure, strict=True):
            if name == "completed_session_requests":
                value = cell.cell_contents
                assert isinstance(value, dict)
                return value
    raise AssertionError("completed_session_requests cache not found on /session/message")


def test_overlay_session_response_honesty_stamps_is_additive() -> None:
    payload = {
        "reply": {"content": "ok", "metadata": {}},
        "snapshot": {"plan": None},
        "agent_meta": {"agentic": False},
    }
    stamped = overlay_session_response_honesty_stamps(
        payload,
        pressure_blocks=True,
        streak_blocks=True,
        recovered_leftover=True,
    )
    assert stamped is not payload
    assert stamped["agent_meta"]["pressure_blocks_live_object_mint"] is True
    assert stamped["agent_meta"]["streak_blocks_live_object_mint"] is True
    assert stamped["agent"]["pressure_blocks_live_object_mint"] is True
    assert stamped["reply"]["metadata"]["coach_focus"]["pressure_blocks_live_object_mint"] is True
    assert stamped["reply"]["metadata"]["coach_focus"]["streak_blocks_live_object_mint"] is True
    assert stamped["snapshot"]["plan_runtime_status"]["recovered"] is True
    # Additive only: clearing flags must not wipe existing stamps on a second pass.
    again = overlay_session_response_honesty_stamps(
        stamped,
        pressure_blocks=False,
        streak_blocks=False,
        recovered_leftover=False,
    )
    assert again is stamped
    assert again["agent_meta"]["pressure_blocks_live_object_mint"] is True


def test_session_message_dedup_cache_overlays_stamps_after_later_hydrate(
    tmp_path: Path,
) -> None:
    """Older completed-cache payload must pick up leftover recovered + mint blocks."""
    workspace_id = "workspace-session-dedup-honesty"
    request_id = "session-dedup-honesty-1"

    with (
        _client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Keep the recovered check only."),
        ),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship token refresh",
                    "weekly_hours": 2,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = str(start.json()["session_id"])
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

        first = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "request_id": request_id,
                "message": "What should I do next?",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert first.status_code == 200, first.text

        cache = _completed_session_cache(client.app)
        cache_key = (workspace_id, session_id, request_id)
        assert cache_key in cache
        # Simulate an older cached snapshot that lost honesty stamps before a later hydrate.
        cache[cache_key] = {
            "session_id": session_id,
            "reply": {
                "id": "message-cached",
                "role": "assistant",
                "content": "Keep the recovered check only.",
                "metadata": {"coach_focus": {}},
            },
            "snapshot": {
                "plan": None,
                "current_task": None,
                "plan_runtime_status": {"status": "in_progress"},
                "memory": {"workspace": {}, "coaching_adaptation": {}},
            },
            "agent_meta": {"agentic": False},
            "coach_turn": {"coach_context": {}},
            "suggested_actions": [],
        }

        runtime.memory_service.update_workspace_state(
            workspace_id,
            **{
                PLAN_RUNTIME_KEY: {
                    "current_step": "Check token refresh once",
                    "why_now": "Leftover pressure-only runtime",
                    "status": "in_progress",
                }
            },
        )
        state = runtime.ensure_session(session_id, workspace_id=workspace_id)
        state.snapshot.plan = None
        state.snapshot.current_task = None
        state.snapshot.plan_runtime_status = {
            "recovered": True,
            "status": "in_progress",
            "current_step": "Check token refresh once",
        }
        state.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
        runtime.save_session_state(session_id)

        with (
            patch(
                "app.pedagogy.context_pressure.pressure_adapts_without_inventing_live_objects",
                return_value=True,
            ),
            patch(
                "app.pedagogy.evidence_controls.streak_adapts_without_inventing_live_objects",
                return_value=True,
            ),
        ):
            second = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "request_id": request_id,
                    "message": "What should I do next?",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )
        assert second.status_code == 200, second.text
        body = second.json()
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        reply_meta = (body.get("reply") or {}).get("metadata") or {}
        coach_focus = reply_meta.get("coach_focus") or {}
        status = (body.get("snapshot") or {}).get("plan_runtime_status") or {}

        assert status.get("recovered") is True
        assert agent_meta.get("pressure_blocks_live_object_mint") is True
        assert agent_meta.get("streak_blocks_live_object_mint") is True
        assert coach_focus.get("pressure_blocks_live_object_mint") is True
        assert coach_focus.get("streak_blocks_live_object_mint") is True
        # Dedup must not re-run the turn (same cached reply content).
        assert (body.get("reply") or {}).get("content") == "Keep the recovered check only."
