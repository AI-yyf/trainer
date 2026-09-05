"""Fail-closed POST /session/start: leftover stays stored; empty restore must not auto-bind."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.models import LearningPlan, PlanStage, ProviderConfig, UserProfile
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.memory.workspace_recovery import PLAN_RUNTIME_KEY, leftover_formal_plan_is_live_for_fill


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer session-start leftover bind",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-session-start-leftover-bind.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _runtime(workspace: dict) -> dict:
    value = workspace.get("latest_plan_runtime") or workspace.get("latestPlanRuntime") or {}
    return value if isinstance(value, dict) else {}


def _snapshot_plan(body: dict) -> dict:
    plan = body.get("plan")
    return plan if isinstance(plan, dict) else {}


def _action_names(body: dict) -> list[str]:
    return [
        str(item.get("action") or "")
        for item in (body.get("suggested_actions") or body.get("suggestedActions") or [])
        if isinstance(item, dict)
    ]


def _seed_leftover(runtime, workspace_id: str, *, plan_id: str, title: str, step: str) -> LearningPlan:
    leftover = LearningPlan(
        id=plan_id,
        title=title,
        current_step=step,
        why_now="Keep the leftover why",
        next_after_current="Then review the leftover path",
        stages=[
            PlanStage(
                id="stage-leftover",
                title="Leftover",
                goal="Stay leftover-not-live",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    runtime.repository.save_plan(workspace_id, leftover)
    return leftover


def test_session_start_empty_restore_does_not_auto_bind_leftover(tmp_path: Path) -> None:
    workspace_id = "workspace-start-empty-restore"
    leftover_title = "Keep the leftover stage"
    leftover_step = "Keep one auth check"
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        leftover = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-leftover-empty-start",
            title=leftover_title,
            step=leftover_step,
        )
        # No recovered runtime at all — empty restore must not invent live plan_id.
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Empty restore lab"},
        )
        assert started.status_code == 200, started.text
        body = started.json()
        assert body.get("plan") in (None, {})
        snapshot_plan = _snapshot_plan(body)
        assert not (snapshot_plan.get("id") or snapshot_plan.get("plan_id"))
        assert leftover_title not in str(snapshot_plan.get("title") or "")

        stored = app.state.runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.id == leftover.id
        assert stored.current_step == leftover_step

        recovered = app.state.runtime.memory_service.recover_workspace_facts(workspace_id).get(
            PLAN_RUNTIME_KEY
        ) or {}
        assert str(recovered.get("plan_id") or recovered.get("planId") or "").strip() in {"", "None"}
        # After start, any persisted runtime must still fail the live-identity check
        # when a recovered record exists (empty plan_id / no matching id).
        if recovered:
            assert not leftover_formal_plan_is_live_for_fill(
                plan=leftover,
                runtime=recovered,
                existing=recovered,
            )
        # Leftover/hint chips: no live plan minting actions.
        actions = _action_names(body)
        assert "plan" not in actions
        assert "next_task" not in actions
        assert "task" not in actions
        status = body.get("plan_runtime_status") or body.get("planRuntimeStatus") or {}
        assert str(status.get("plan_id") or status.get("planId") or "").strip() in {"", "None"}
        # Cold start: leftover stored, not live → stamp recovered so FE overlay lights.
        assert status.get("recovered") is True


def test_session_start_mismatched_runtime_plan_id_stays_fail_closed(tmp_path: Path) -> None:
    workspace_id = "workspace-start-mismatched"
    leftover_title = "Keep the leftover stage"
    leftover_step = "Keep one auth check"
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        leftover = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-leftover-mismatch-start",
            title=leftover_title,
            step=leftover_step,
        )
        app.state.runtime.memory_service.structured_for_workspace(workspace_id).update_workspace(
            latest_plan_runtime={
                "current_step": "Add a token expiry test",
                "plan_id": "plan-other-runtime",
                "resume_state": "in_progress",
                "workspace_id": workspace_id,
            }
        )
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Mismatched restore lab"},
        )
        assert started.status_code == 200, started.text
        body = started.json()
        assert body.get("plan") in (None, {})
        stored = app.state.runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.id == leftover.id
        recovered = app.state.runtime.memory_service.recover_workspace_facts(workspace_id)[
            PLAN_RUNTIME_KEY
        ]
        assert str(recovered.get("plan_id") or "").strip() == "plan-other-runtime"
        assert recovered.get("current_step") == "Add a token expiry test"
        assert not leftover_formal_plan_is_live_for_fill(
            plan=leftover,
            runtime=recovered,
            existing=recovered,
        )
        status = body.get("plan_runtime_status") or body.get("planRuntimeStatus") or {}
        assert status.get("recovered") is True
        assert str(status.get("plan_id") or status.get("planId") or "").strip() == "plan-other-runtime"
        assert body.get("plan") in (None, {})


def test_session_start_matching_runtime_plan_id_may_restore_live(tmp_path: Path) -> None:
    workspace_id = "workspace-start-matching-live"
    leftover_title = "Live matching stage"
    leftover_step = "Keep the live auth check"
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        live = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-live-matching-start",
            title=leftover_title,
            step=leftover_step,
        )
        app.state.runtime.memory_service.structured_for_workspace(workspace_id).update_workspace(
            latest_plan_runtime={
                "current_step": leftover_step,
                "plan_id": live.id,
                "resume_state": "in_progress",
                "workspace_id": workspace_id,
            }
        )
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Matching live lab"},
        )
        assert started.status_code == 200, started.text
        body = started.json()
        snapshot_plan = _snapshot_plan(body)
        assert str(snapshot_plan.get("id") or snapshot_plan.get("plan_id") or "") == live.id
        assert snapshot_plan.get("current_step") == leftover_step
        mem_runtime = _runtime((body.get("memory") or {}).get("workspace") or {})
        assert str(mem_runtime.get("plan_id") or mem_runtime.get("planId") or "") == live.id
        recovered = app.state.runtime.memory_service.recover_workspace_facts(workspace_id)[
            PLAN_RUNTIME_KEY
        ]
        assert str(recovered.get("plan_id") or "") == live.id
        assert leftover_formal_plan_is_live_for_fill(
            plan=live,
            runtime=recovered,
            existing=recovered,
        )
        status = body.get("plan_runtime_status") or body.get("planRuntimeStatus") or {}
        # Live restore: plan bound; leftover overlay stays off via live formal identity.
        assert str(snapshot_plan.get("id") or snapshot_plan.get("plan_id") or "") == live.id
        assert str(status.get("plan_id") or status.get("planId") or "") == live.id


def test_session_start_then_plan_generate_binds_new_live_plan_id(tmp_path: Path) -> None:
    workspace_id = "workspace-start-then-generate"
    leftover_title = "Keep the leftover stage"
    leftover_step = "Keep one auth check"
    app = create_app(_settings(tmp_path / "data"))
    _wire_provider(app, streaming=True)
    with TestClient(app) as client:
        leftover = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-leftover-before-generate",
            title=leftover_title,
            step=leftover_step,
        )
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Generate after start lab"},
        )
        assert started.status_code == 200, started.text
        body = started.json()
        session_id = body["session_id"]
        assert body.get("plan") in (None, {})
        assert app.state.runtime.repository.get_latest_plan(workspace_id).id == leftover.id

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Ship token refresh under a newly bound plan"],
                "profile": UserProfile(long_term_goal="Ship under live plan").model_dump(
                    mode="json"
                ),
            },
        )
        assert generated.status_code == 200, generated.text
        plan = generated.json().get("plan") or generated.json()
        new_plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
        assert new_plan_id
        assert new_plan_id != leftover.id
        live_runtime = _runtime((generated.json().get("memory") or {}).get("workspace") or {})
        assert str(live_runtime.get("plan_id") or live_runtime.get("planId") or "").strip() == new_plan_id
        recovered = app.state.runtime.memory_service.recover_workspace_facts(workspace_id)[
            PLAN_RUNTIME_KEY
        ]
        assert str(recovered.get("plan_id") or "") == new_plan_id


def _wire_provider(app, *, streaming: bool = False, tools: bool = False) -> None:
    from tests.test_router_stream_scenarios import mark_provider_capabilities_verified

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
            "tools": tools,
            "json_schema": False,
            "streaming": streaming,
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
    if streaming or tools:
        mark_provider_capabilities_verified(
            runtime,
            provider,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=tools,
        )


def _plan_runtime_status(body: dict) -> dict:
    status = body.get("plan_runtime_status") or body.get("planRuntimeStatus") or {}
    if not status and isinstance(body.get("snapshot"), dict):
        status = (
            body["snapshot"].get("plan_runtime_status")
            or body["snapshot"].get("planRuntimeStatus")
            or {}
        )
    return status if isinstance(status, dict) else {}


def test_turn_preserves_leftover_not_live_recovered_after_empty_restore(tmp_path: Path) -> None:
    """Cold-start recovered stamp must survive build_session_response attach rebuild."""
    workspace_id = "workspace-turn-preserve-leftover-recovered"
    leftover_title = "Keep the leftover stage"
    leftover_step = "Keep one auth check"
    app = create_app(_settings(tmp_path / "data"))
    _wire_provider(app)

    async def fake_reply(*args: object, **kwargs: object) -> str:
        return "Stay on the leftover check without inventing a live plan."

    with TestClient(app) as client, patch.object(
        ProviderService, "coaching_reply", new=fake_reply
    ):
        leftover = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-leftover-turn-preserve",
            title=leftover_title,
            step=leftover_step,
        )
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Turn preserve lab"},
        )
        assert started.status_code == 200, started.text
        start_body = started.json()
        session_id = start_body["session_id"]
        start_status = (
            start_body.get("plan_runtime_status") or start_body.get("planRuntimeStatus") or {}
        )
        assert start_status.get("recovered") is True
        assert start_body.get("plan") in (None, {})

        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": "Continue without binding the leftover plan.",
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        body = turn.json()
        status = body.get("plan_runtime_status") or body.get("planRuntimeStatus") or {}
        if not status and isinstance(body.get("snapshot"), dict):
            status = (
                body["snapshot"].get("plan_runtime_status")
                or body["snapshot"].get("planRuntimeStatus")
                or {}
            )
        assert status.get("recovered") is True
        assert body.get("plan") in (None, {})
        snapshot = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else {}
        if "plan" in snapshot:
            assert snapshot.get("plan") in (None, {})
        actions = _action_names(body)
        assert "plan" not in actions
        assert "next_task" not in actions
        assert "task" not in actions
        stored = app.state.runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.id == leftover.id
        assert stored.current_step == leftover_step


def test_session_message_preserves_leftover_not_live_recovered(tmp_path: Path) -> None:
    workspace_id = "workspace-message-preserve-leftover-recovered"
    leftover_step = "Keep one auth check"
    app = create_app(_settings(tmp_path / "data"))
    _wire_provider(app)

    async def fake_reply(*args: object, **kwargs: object) -> str:
        return "Keep coaching without minting a live formal plan."

    with TestClient(app) as client, patch.object(
        ProviderService, "coaching_reply", new=fake_reply
    ):
        leftover = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-leftover-message-preserve",
            title="Keep the leftover stage",
            step=leftover_step,
        )
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Message preserve lab"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        message = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": "Stay fail-closed on leftover.",
                "response_language": "en-US",
            },
        )
        assert message.status_code == 200, message.text
        body = message.json()
        status = body.get("plan_runtime_status") or body.get("planRuntimeStatus") or {}
        if not status and isinstance(body.get("snapshot"), dict):
            status = (
                body["snapshot"].get("plan_runtime_status")
                or body["snapshot"].get("planRuntimeStatus")
                or {}
            )
        assert status.get("recovered") is True
        assert body.get("plan") in (None, {})
        assert app.state.runtime.repository.get_latest_plan(workspace_id).id == leftover.id


def test_turn_live_matching_plan_id_not_leftover_overlay(tmp_path: Path) -> None:
    workspace_id = "workspace-turn-live-matching-no-overlay"
    leftover_step = "Keep the live auth check"
    app = create_app(_settings(tmp_path / "data"))
    _wire_provider(app)

    async def fake_reply(*args: object, **kwargs: object) -> str:
        return "Continue the live matching plan step."

    with TestClient(app) as client, patch.object(
        ProviderService, "coaching_reply", new=fake_reply
    ):
        live = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-live-matching-turn",
            title="Live matching stage",
            step=leftover_step,
        )
        app.state.runtime.memory_service.structured_for_workspace(workspace_id).update_workspace(
            latest_plan_runtime={
                "current_step": leftover_step,
                "plan_id": live.id,
                "resume_state": "in_progress",
                "workspace_id": workspace_id,
            }
        )
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Live matching turn lab"},
        )
        assert started.status_code == 200, started.text
        start_body = started.json()
        session_id = start_body["session_id"]
        start_plan = _snapshot_plan(start_body)
        assert str(start_plan.get("id") or start_plan.get("plan_id") or "") == live.id

        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": "Continue the live plan.",
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        body = turn.json()
        plan = body.get("plan") or (body.get("snapshot") or {}).get("plan") or {}
        if not isinstance(plan, dict):
            plan = {}
        assert str(plan.get("id") or plan.get("plan_id") or "") == live.id
        status = body.get("plan_runtime_status") or body.get("planRuntimeStatus") or {}
        if not status and isinstance(body.get("snapshot"), dict):
            status = (
                body["snapshot"].get("plan_runtime_status")
                or body["snapshot"].get("planRuntimeStatus")
                or {}
            )
        assert str(status.get("plan_id") or status.get("planId") or "") == live.id
        recovered = app.state.runtime.memory_service.recover_workspace_facts(workspace_id)[
            PLAN_RUNTIME_KEY
        ]
        assert leftover_formal_plan_is_live_for_fill(
            plan=live,
            runtime=recovered,
            existing=recovered,
        )


def test_turn_stream_preserves_leftover_not_live_recovered_after_empty_restore(
    tmp_path: Path,
) -> None:
    """`/turn/stream` shares build_session_response → attach_plan_runtime_status."""
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = "workspace-turn-stream-preserve-leftover-recovered"
    leftover_step = "Keep one auth check"
    app = create_app(_settings(tmp_path / "data"))
    _wire_provider(app, streaming=True)

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Stay on the leftover check without inventing a live plan."

    async def fake_reply(*_args: object, **_kwargs: object) -> str:
        return "Stay on the leftover check without inventing a live plan."

    with (
        TestClient(app) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        patch.object(ProviderService, "coaching_reply", new=fake_reply),
    ):
        leftover = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-leftover-turn-stream-preserve",
            title="Keep the leftover stage",
            step=leftover_step,
        )
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Turn stream preserve lab"},
        )
        assert started.status_code == 200, started.text
        start_body = started.json()
        session_id = start_body["session_id"]
        assert _plan_runtime_status(start_body).get("recovered") is True
        assert start_body.get("plan") in (None, {})

        streamed = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Continue without binding the leftover plan.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert streamed.status_code == 200, streamed.text
        body = completed_stream_response(streamed.text)
        status = _plan_runtime_status(body)
        assert status.get("recovered") is True
        assert not str(status.get("plan_id") or status.get("planId") or "").strip()
        assert body.get("plan") in (None, {})
        snapshot = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else {}
        if "plan" in snapshot:
            assert snapshot.get("plan") in (None, {})
        actions = _action_names(body)
        assert "plan" not in actions
        assert "next_task" not in actions
        assert "task" not in actions
        stored = app.state.runtime.repository.get_latest_plan(workspace_id)
        assert stored is not None
        assert stored.id == leftover.id
        assert stored.current_step == leftover_step


def test_session_message_stream_preserves_leftover_not_live_recovered(
    tmp_path: Path,
) -> None:
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = "workspace-message-stream-preserve-leftover-recovered"
    leftover_step = "Keep one auth check"
    app = create_app(_settings(tmp_path / "data"))
    _wire_provider(app, streaming=True)

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Keep coaching without minting a live formal plan."

    async def fake_reply(*_args: object, **_kwargs: object) -> str:
        return "Keep coaching without minting a live formal plan."

    with (
        TestClient(app) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        patch.object(ProviderService, "coaching_reply", new=fake_reply),
    ):
        leftover = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-leftover-message-stream-preserve",
            title="Keep the leftover stage",
            step=leftover_step,
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Message stream preserve lab",
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        streamed = client.post(
            "/session/message/stream",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": "Stay fail-closed on leftover.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert streamed.status_code == 200, streamed.text
        body = completed_stream_response(streamed.text)
        status = _plan_runtime_status(body)
        assert status.get("recovered") is True
        assert not str(status.get("plan_id") or status.get("planId") or "").strip()
        assert body.get("plan") in (None, {})
        snapshot = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else {}
        if "plan" in snapshot:
            assert snapshot.get("plan") in (None, {})
        actions = _action_names(body)
        assert "plan" not in actions
        assert "next_task" not in actions
        assert "task" not in actions
        assert app.state.runtime.repository.get_latest_plan(workspace_id).id == leftover.id


def test_turn_stream_live_matching_plan_id_not_leftover_overlay(tmp_path: Path) -> None:
    """One stream proof is enough: same attach helper as /turn."""
    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = "workspace-turn-stream-live-matching-no-overlay"
    leftover_step = "Keep the live auth check"
    app = create_app(_settings(tmp_path / "data"))
    _wire_provider(app, streaming=True)

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "Continue the live matching plan step."

    async def fake_reply(*_args: object, **_kwargs: object) -> str:
        return "Continue the live matching plan step."

    with (
        TestClient(app) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=fake_stream),
        patch.object(ProviderService, "coaching_reply", new=fake_reply),
    ):
        live = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-live-matching-turn-stream",
            title="Live matching stage",
            step=leftover_step,
        )
        app.state.runtime.memory_service.structured_for_workspace(workspace_id).update_workspace(
            latest_plan_runtime={
                "current_step": leftover_step,
                "plan_id": live.id,
                "resume_state": "in_progress",
                "workspace_id": workspace_id,
            }
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Live matching turn stream lab",
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        streamed = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Continue the live plan.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert streamed.status_code == 200, streamed.text
        body = completed_stream_response(streamed.text)
        plan = body.get("plan") or (body.get("snapshot") or {}).get("plan") or {}
        if not isinstance(plan, dict):
            plan = {}
        assert str(plan.get("id") or plan.get("plan_id") or "") == live.id
        status = _plan_runtime_status(body)
        assert str(status.get("plan_id") or status.get("planId") or "") == live.id
        recovered = app.state.runtime.memory_service.recover_workspace_facts(workspace_id)[
            PLAN_RUNTIME_KEY
        ]
        assert leftover_formal_plan_is_live_for_fill(
            plan=live,
            runtime=recovered,
            existing=recovered,
        )


def _fake_agentic_stream_text(text: str):
    async def _stream(*_args: object, **_kwargs: object):
        yield {
            "type": "text",
            "delta": text,
            "safe_to_stream": True,
        }
        yield {
            "type": "final",
            "content": text,
            "summary": "Leftover not live",
            "next_step": "One thin check",
            "stop_reason": "completed",
            "tool_events": [],
        }

    return _stream


def _assert_no_invented_live_objects(
    body: dict, *, leftover_id: str, workspace_id: str, runtime
) -> None:
    status = _plan_runtime_status(body)
    assert status.get("recovered") is True
    assert not str(status.get("plan_id") or status.get("planId") or "").strip()
    assert body.get("plan") in (None, {})
    snapshot = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else {}
    if "plan" in snapshot:
        assert snapshot.get("plan") in (None, {})
    assert snapshot.get("current_task") in (None, {})
    memory = snapshot.get("memory") if isinstance(snapshot.get("memory"), dict) else {}
    workspace = memory.get("workspace") if isinstance(memory.get("workspace"), dict) else {}
    routing = (
        memory.get("active_training_card_routing")
        if isinstance(memory.get("active_training_card_routing"), dict)
        else {}
    )
    assert not str(
        workspace.get("selected_card_id") or workspace.get("selectedCardId") or ""
    ).strip()
    assert not str(
        routing.get("selected_card_id") or routing.get("selectedCardId") or ""
    ).strip()
    actions = _action_names(body)
    assert "plan" not in actions
    assert "next_task" not in actions
    assert "task" not in actions
    # Hint-only / non-minting chips (review is allowed; plan/task mint is not).
    assert all(action in {"hint", "review", "retry_review"} for action in actions)
    stored = runtime.repository.get_latest_plan(workspace_id)
    assert stored is not None
    assert stored.id == leftover_id


def test_turn_stream_agent_tools_preserves_leftover_not_live_recovered_after_empty_restore(
    tmp_path: Path,
) -> None:
    """Empty-restore leftover + `/turn/stream` ReAct/tools must keep recovered, not invent."""
    from unittest.mock import PropertyMock

    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = "workspace-turn-stream-agent-tools-leftover-recovered"
    leftover_step = "Keep one auth check"
    app = create_app(_settings(tmp_path / "data"))
    _wire_provider(app, streaming=True, tools=True)

    with (
        TestClient(app) as client,
        patch.object(
            ProviderService,
            "has_api_key",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch.object(
            ProviderService,
            "coaching_reply_agentic_stream",
            new=_fake_agentic_stream_text(
                "Stay on the leftover check without inventing a live plan."
            ),
        ),
    ):
        leftover = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-leftover-turn-stream-agent-tools",
            title="Keep the leftover stage",
            step=leftover_step,
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Turn stream agent-tools leftover lab",
            },
        )
        assert started.status_code == 200, started.text
        start_body = started.json()
        session_id = start_body["session_id"]
        assert _plan_runtime_status(start_body).get("recovered") is True
        assert start_body.get("plan") in (None, {})

        streamed = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Continue without binding the leftover plan.",
                "response_language": "en-US",
                "use_agent_loop": True,
            },
        )
        assert streamed.status_code == 200, streamed.text
        body = completed_stream_response(streamed.text)
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert agent_meta.get("agentic") is True
        _assert_no_invented_live_objects(
            body,
            leftover_id=leftover.id,
            workspace_id=workspace_id,
            runtime=app.state.runtime,
        )
        assert (
            app.state.runtime.repository.get_latest_plan(workspace_id).current_step
            == leftover_step
        )


def test_session_message_stream_agent_tools_preserves_leftover_not_live_recovered(
    tmp_path: Path,
) -> None:
    """Empty-restore leftover + `/session/message/stream` ReAct/tools: recovered stays."""
    from unittest.mock import PropertyMock

    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = "workspace-message-stream-agent-tools-leftover-recovered"
    leftover_step = "Keep one auth check"
    app = create_app(_settings(tmp_path / "data"))
    _wire_provider(app, streaming=True, tools=True)

    with (
        TestClient(app) as client,
        patch.object(
            ProviderService,
            "has_api_key",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch.object(
            ProviderService,
            "coaching_reply_agentic_stream",
            new=_fake_agentic_stream_text(
                "Keep coaching without minting a live formal plan."
            ),
        ),
    ):
        leftover = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-leftover-message-stream-agent-tools",
            title="Keep the leftover stage",
            step=leftover_step,
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Message stream agent-tools leftover lab",
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        assert _plan_runtime_status(started.json()).get("recovered") is True

        streamed = client.post(
            "/session/message/stream",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": "Stay fail-closed on leftover.",
                "response_language": "en-US",
                "use_agent_loop": True,
            },
        )
        assert streamed.status_code == 200, streamed.text
        body = completed_stream_response(streamed.text)
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert agent_meta.get("agentic") is True
        _assert_no_invented_live_objects(
            body,
            leftover_id=leftover.id,
            workspace_id=workspace_id,
            runtime=app.state.runtime,
        )


def test_turn_stream_agent_tools_live_matching_plan_id_not_leftover_overlay(
    tmp_path: Path,
) -> None:
    """One agent-tools stream case: matching plan_id stays live, not leftover overlay."""
    from unittest.mock import PropertyMock

    from tests.test_router_stream_scenarios import completed_stream_response

    workspace_id = "workspace-turn-stream-agent-tools-live-matching"
    live_step = "Keep the live auth check"
    app = create_app(_settings(tmp_path / "data"))
    _wire_provider(app, streaming=True, tools=True)

    with (
        TestClient(app) as client,
        patch.object(
            ProviderService,
            "has_api_key",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch.object(
            ProviderService,
            "coaching_reply_agentic_stream",
            new=_fake_agentic_stream_text("Continue the live matching plan step."),
        ),
    ):
        live = _seed_leftover(
            app.state.runtime,
            workspace_id,
            plan_id="plan-live-matching-turn-stream-agent-tools",
            title="Live matching stage",
            step=live_step,
        )
        app.state.runtime.memory_service.structured_for_workspace(workspace_id).update_workspace(
            latest_plan_runtime={
                "current_step": live_step,
                "plan_id": live.id,
                "resume_state": "in_progress",
                "workspace_id": workspace_id,
            }
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Live matching agent-tools stream lab",
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        streamed = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Continue the live plan.",
                "response_language": "en-US",
                "use_agent_loop": True,
            },
        )
        assert streamed.status_code == 200, streamed.text
        body = completed_stream_response(streamed.text)
        agent_meta = body.get("agent_meta") or body.get("agent") or {}
        assert agent_meta.get("agentic") is True
        plan = body.get("plan") or (body.get("snapshot") or {}).get("plan") or {}
        if not isinstance(plan, dict):
            plan = {}
        assert str(plan.get("id") or plan.get("plan_id") or "") == live.id
        status = _plan_runtime_status(body)
        assert str(status.get("plan_id") or status.get("planId") or "") == live.id
        # Live bind: matching plan_id on status + formal object — not leftover overlay.
        assert plan not in (None, {})
        recovered = app.state.runtime.memory_service.recover_workspace_facts(workspace_id)[
            PLAN_RUNTIME_KEY
        ]
        assert leftover_formal_plan_is_live_for_fill(
            plan=live,
            runtime=recovered,
            existing=recovered,
        )
