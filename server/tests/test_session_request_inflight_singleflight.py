"""Same request_id first-pass must single-flight — no double-exec mint race."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from threading import Lock
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routers import (
    claim_session_request_singleflight,
    fail_session_request_singleflight,
    overlay_session_response_honesty_stamps,
    publish_session_request_singleflight,
)
from app.core.models import ProviderConfig, ProviderTestResponse
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from tests.test_router_stream_scenarios import mark_provider_capabilities_verified


def _mark_provider_last_test_failed(runtime, provider: ProviderConfig, api_key: str) -> None:
    """Seed an explicit failed last-test (not never-tested / empty cache)."""
    mark_provider_capabilities_verified(runtime, provider, api_key, tools=False)
    runtime.remember_provider_capability_test(
        provider,
        api_key,
        ProviderTestResponse(
            ok=False,
            detail="auth failed",
            tools_ready=False,
            tool_probe_status="unverified",
        ),
    )


def test_claim_session_request_singleflight_second_waits() -> None:
    completed: dict[tuple[str, str, str], dict[str, object]] = {}
    inflight: dict[tuple[str, str, str], asyncio.Future] = {}
    guard = Lock()
    key = ("ws", "sess", "req-1")

    async def _run() -> None:
        kind1, cached1, fut1 = claim_session_request_singleflight(
            key, completed=completed, inflight=inflight, guard=guard
        )
        assert kind1 == "owner"
        assert cached1 is None
        assert fut1 is not None
        assert not fut1.done()

        kind2, cached2, fut2 = claim_session_request_singleflight(
            key, completed=completed, inflight=inflight, guard=guard
        )
        assert kind2 == "wait"
        assert cached2 is None
        assert fut2 is fut1

        payload = {"reply": {"content": "once"}, "agent_meta": {}}
        publish_session_request_singleflight(
            key, payload, completed=completed, inflight=inflight, guard=guard
        )
        assert fut1.done()
        assert await fut1 == payload
        assert completed[key] is payload

        kind3, cached3, fut3 = claim_session_request_singleflight(
            key, completed=completed, inflight=inflight, guard=guard
        )
        assert kind3 == "cached"
        assert cached3 is payload
        assert fut3 is None

    asyncio.run(_run())


def test_fail_session_request_singleflight_unblocks_waiter() -> None:
    """Cancel/fail mid-flight must release waiters — never hang on the owner future."""
    completed: dict[tuple[str, str, str], dict[str, object]] = {}
    inflight: dict[tuple[str, str, str], asyncio.Future] = {}
    guard = Lock()
    key = ("ws", "sess", "req-cancel-1")

    async def _run() -> None:
        kind1, _cached1, fut1 = claim_session_request_singleflight(
            key, completed=completed, inflight=inflight, guard=guard
        )
        assert kind1 == "owner"
        assert fut1 is not None
        assert not fut1.done()

        kind2, _cached2, fut2 = claim_session_request_singleflight(
            key, completed=completed, inflight=inflight, guard=guard
        )
        assert kind2 == "wait"
        assert fut2 is fut1

        fail_session_request_singleflight(
            key,
            RuntimeError("session stream failed"),
            inflight=inflight,
            guard=guard,
        )
        assert key not in inflight
        assert fut1.done()
        with pytest.raises(RuntimeError, match="session stream failed"):
            await fut1

        # Same request_id after fail_inflight may reclaim (no completed cache) —
        # concurrent double-mint is what singleflight blocks; post-fail re-own is OK
        # when nothing was published. Waiter must not still be awaiting the old future.
        kind3, _cached3, fut3 = claim_session_request_singleflight(
            key, completed=completed, inflight=inflight, guard=guard
        )
        assert kind3 == "owner"
        assert fut3 is not None
        assert fut3 is not fut1

    asyncio.run(_run())


def test_waiter_overlay_honesty_stamps_after_shared_result() -> None:
    shared = {
        "reply": {"metadata": {"coach_focus": {}}},
        "agent_meta": {"agentic": False},
        "snapshot": {"plan_runtime_status": {}},
    }
    stamped = overlay_session_response_honesty_stamps(
        shared,
        pressure_blocks=True,
        streak_blocks=False,
        recovered_leftover=True,
    )
    assert stamped["agent_meta"]["pressure_blocks_live_object_mint"] is True
    assert stamped["snapshot"]["plan_runtime_status"]["recovered"] is True


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Session Inflight Singleflight",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-session-inflight.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _build_app(tmp_path: Path):
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
    return app


@pytest.mark.asyncio
async def test_concurrent_same_request_id_executes_once(tmp_path: Path) -> None:
    """Two in-flight identical request_ids must not double-call coaching_reply."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-session-inflight-1"
    request_id = "session-inflight-same-1"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_reply(*_args, **_kwargs) -> str:
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        return "Single-flight shared reply."

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "message": "What should I do next?",
        "response_language": "en-US",
        "use_agent_loop": False,
    }

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "coaching_reply", new=slow_reply):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(client.post("/session/message", json=payload))
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            # Second arrives while first is still executing — must wait, not mint again.
            second = asyncio.create_task(client.post("/session/message", json=payload))
            await asyncio.sleep(0.05)
            assert call_count == 1
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert call_count == 1
    body1 = r1.json()
    body2 = r2.json()
    assert "Single-flight shared reply." in str(body1.get("reply") or body1)
    assert "Single-flight shared reply." in str(body2.get("reply") or body2)


def test_distinct_request_ids_still_execute_separately(tmp_path: Path) -> None:
    """Explicit generate uses unique request_id — must not collapse distinct ids."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-session-inflight-distinct"
    calls: list[str] = []

    async def counting_reply(*_args, **_kwargs) -> str:
        calls.append("hit")
        return "Distinct reply."

    with (
        TestClient(app) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(side_effect=counting_reply)),
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        for rid in ("gen-plan-a", "gen-plan-b"):
            resp = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "request_id": rid,
                    "message": "Generate the next step.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )
            assert resp.status_code == 200, resp.text
    assert len(calls) == 2


def _parse_sse_complete_response(body: str) -> dict[str, object]:
    for block in body.split("\n\n"):
        if not block.strip().startswith("event: complete"):
            continue
        for line in block.splitlines():
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                response = payload.get("response")
                assert isinstance(response, dict)
                return response
    raise AssertionError(f"no SSE complete frame in: {body[:500]}")


@pytest.mark.asyncio
async def test_concurrent_same_request_id_stream_executes_once(tmp_path: Path) -> None:
    """Two in-flight identical request_ids on /session/message/stream must not double-stream-mint."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-session-inflight-stream-1"
    request_id = "session-inflight-stream-same-1"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_stream(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        yield "Single-flight stream reply."

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-a",
        "message": "What should I do next?",
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    payload_b = {**payload, "stream_id": f"stream-{request_id}-b"}

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "coaching_reply_stream", new=slow_stream):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(
                client.post("/session/message/stream", json=payload)
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(
                client.post("/session/message/stream", json=payload_b)
            )
            await asyncio.sleep(0.05)
            assert call_count == 1
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert call_count == 1
    body1 = _parse_sse_complete_response(r1.text)
    body2 = _parse_sse_complete_response(r2.text)
    assert "Single-flight stream reply." in str(body1.get("reply") or body1)
    assert "Single-flight stream reply." in str(body2.get("reply") or body2)


@pytest.mark.asyncio
async def test_stream_waiter_gets_honesty_overlay_stamps(tmp_path: Path) -> None:
    """Waiter complete-frame replay must carry additive honesty stamps after hydrate."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-session-inflight-stream-honesty"
    request_id = "session-inflight-stream-honesty-1"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_stream(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        yield "Honesty stream reply."

    def force_honesty_overlay(
        payload: dict[str, object],
        *,
        pressure_blocks: bool = False,
        streak_blocks: bool = False,
        recovered_leftover: bool = False,
    ) -> dict[str, object]:
        # Nested pressure helper is not patchable at module scope; force additive stamps
        # through the shared overlay entry the waiter path always calls.
        return overlay_session_response_honesty_stamps(
            payload,
            pressure_blocks=True,
            streak_blocks=streak_blocks,
            recovered_leftover=recovered_leftover,
        )

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-owner",
        "message": "What should I do next?",
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    waiter_payload = {**payload, "stream_id": f"stream-{request_id}-waiter"}

    transport = httpx.ASGITransport(app=app)
    with (
        patch.object(ProviderService, "coaching_reply_stream", new=slow_stream),
        patch("app.api.routers.overlay_session_response_honesty_stamps", force_honesty_overlay),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(
                client.post("/session/message/stream", json=payload)
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(
                client.post("/session/message/stream", json=waiter_payload)
            )
            await asyncio.sleep(0.05)
            assert call_count == 1
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert call_count == 1
    waiter_body = _parse_sse_complete_response(r2.text)
    agent_meta = waiter_body.get("agent_meta") or waiter_body.get("agent") or {}
    assert isinstance(agent_meta, dict)
    assert agent_meta.get("pressure_blocks_live_object_mint") is True


def test_stream_distinct_request_ids_still_independent(tmp_path: Path) -> None:
    """Distinct stream request_ids must not collapse into one flight."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-session-inflight-stream-distinct"
    calls: list[str] = []

    async def counting_stream(*_args, **_kwargs):
        calls.append("hit")
        yield "Distinct stream reply."

    with (
        TestClient(app) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=counting_stream),
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        for rid in ("stream-gen-a", "stream-gen-b"):
            resp = client.post(
                "/session/message/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "request_id": rid,
                    "stream_id": f"stream-{rid}",
                    "message": "Generate the next step.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )
            assert resp.status_code == 200, resp.text
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_turn_stream_concurrent_same_request_id_executes_once(tmp_path: Path) -> None:
    """Two in-flight identical request_ids on /turn/stream must not double-stream-mint."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-turn-inflight-stream-1"
    request_id = "turn-inflight-stream-same-1"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_stream(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        yield "Turn single-flight stream reply."

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-a",
        "intent": "coach",
        "message": "What should I do next?",
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    payload_b = {**payload, "stream_id": f"stream-{request_id}-b"}

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "coaching_reply_stream", new=slow_stream):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(client.post("/turn/stream", json=payload))
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(client.post("/turn/stream", json=payload_b))
            await asyncio.sleep(0.05)
            assert call_count == 1
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert call_count == 1
    body1 = _parse_sse_complete_response(r1.text)
    body2 = _parse_sse_complete_response(r2.text)
    assert "Turn single-flight stream reply." in str(body1.get("reply") or body1)
    assert "Turn single-flight stream reply." in str(body2.get("reply") or body2)


@pytest.mark.asyncio
async def test_turn_stream_waiter_gets_honesty_overlay_stamps(tmp_path: Path) -> None:
    """/turn/stream waiter complete-frame replay must carry additive honesty stamps."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-turn-inflight-stream-honesty"
    request_id = "turn-inflight-stream-honesty-1"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_stream(*_args, **_kwargs):
        entered.set()
        await release.wait()
        yield "Turn honesty stream reply."

    def force_honesty_overlay(
        payload: dict[str, object],
        *,
        pressure_blocks: bool = False,
        streak_blocks: bool = False,
        recovered_leftover: bool = False,
    ) -> dict[str, object]:
        return overlay_session_response_honesty_stamps(
            payload,
            pressure_blocks=True,
            streak_blocks=streak_blocks,
            recovered_leftover=recovered_leftover,
        )

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-owner",
        "intent": "coach",
        "message": "What should I do next?",
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    waiter_payload = {**payload, "stream_id": f"stream-{request_id}-waiter"}

    transport = httpx.ASGITransport(app=app)
    with (
        patch.object(ProviderService, "coaching_reply_stream", new=slow_stream),
        patch("app.api.routers.overlay_session_response_honesty_stamps", force_honesty_overlay),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(client.post("/turn/stream", json=payload))
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(client.post("/turn/stream", json=waiter_payload))
            await asyncio.sleep(0.05)
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    waiter_body = _parse_sse_complete_response(r2.text)
    agent_meta = waiter_body.get("agent_meta") or waiter_body.get("agent") or {}
    assert isinstance(agent_meta, dict)
    assert agent_meta.get("pressure_blocks_live_object_mint") is True


def test_turn_stream_distinct_request_ids_still_independent(tmp_path: Path) -> None:
    """Distinct /turn/stream request_ids must not collapse into one flight."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-turn-inflight-stream-distinct"
    calls: list[str] = []

    async def counting_stream(*_args, **_kwargs):
        calls.append("hit")
        yield "Distinct turn stream reply."

    with (
        TestClient(app) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=counting_stream),
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        for rid in ("turn-stream-gen-a", "turn-stream-gen-b"):
            resp = client.post(
                "/turn/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "request_id": rid,
                    "stream_id": f"stream-{rid}",
                    "intent": "coach",
                    "message": "Generate the next step.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )
            assert resp.status_code == 200, resp.text
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
async def test_unusable_provider_stream_same_request_id_singleflights(
    tmp_path: Path,
    path: str,
) -> None:
    """Never-tested honesty SSE must claim before run — same request_id appends once."""
    app = _build_app(tmp_path)
    workspace_id = f"workspace-unusable-sf-{path.strip('/').replace('/', '-')}"
    request_id = f"unusable-sf-{path.strip('/').replace('/', '-')}"
    message = "Give me the next small debugging step."

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        runtime.provider_capability_cache.clear()

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-a",
        "message": message,
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    if path == "/turn/stream":
        payload["intent"] = "coach"
    payload_b = {**payload, "stream_id": f"stream-{request_id}-b"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r1, r2 = await asyncio.gather(
            client.post(path, json=payload),
            client.post(path, json=payload_b),
        )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    body1 = _parse_sse_complete_response(r1.text)
    body2 = _parse_sse_complete_response(r2.text)
    assert (body1.get("reliability") or {}).get("outcome") == "failure"
    assert (body2.get("reliability") or {}).get("outcome") == "failure"

    state = runtime.ensure_session(session_id, workspace_id=workspace_id)
    user_msgs = [
        message_row
        for message_row in state.snapshot.messages
        if message_row.role == "user" and message_row.content == message
    ]
    assert len(user_msgs) == 1


@pytest.mark.asyncio
async def test_turn_concurrent_same_request_id_executes_once(tmp_path: Path) -> None:
    """Non-stream /turn same request_id must claim/publish — one coaching_reply."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-turn-inflight-1"
    request_id = "turn-inflight-same-1"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_reply(*_args, **_kwargs) -> str:
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        return "Turn single-flight shared reply."

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "intent": "coach",
        "message": "What should I do next?",
        "response_language": "en-US",
        "use_agent_loop": False,
    }

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "coaching_reply", new=slow_reply):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(client.post("/turn", json=payload))
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(client.post("/turn", json=payload))
            await asyncio.sleep(0.05)
            assert call_count == 1
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert call_count == 1
    body1 = r1.json()
    body2 = r2.json()
    assert "Turn single-flight shared reply." in str(body1.get("reply") or body1)
    assert "Turn single-flight shared reply." in str(body2.get("reply") or body2)


def test_turn_distinct_request_ids_still_execute_separately(tmp_path: Path) -> None:
    """Distinct /turn request_ids must not collapse."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-turn-inflight-distinct"
    calls: list[str] = []

    async def counting_reply(*_args, **_kwargs) -> str:
        calls.append("hit")
        return "Distinct turn reply."

    with (
        TestClient(app) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(side_effect=counting_reply)),
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        for rid in ("turn-gen-a", "turn-gen-b"):
            resp = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "request_id": rid,
                    "intent": "coach",
                    "message": "Generate the next step.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )
            assert resp.status_code == 200, resp.text
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_turn_waiter_gets_honesty_overlay_stamps(tmp_path: Path) -> None:
    """Non-stream /turn waiter replay must carry additive honesty stamps."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-turn-inflight-honesty"
    request_id = "turn-inflight-honesty-1"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_reply(*_args, **_kwargs) -> str:
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        return "Turn honesty reply."

    def force_honesty_overlay(
        payload: dict[str, object],
        *,
        pressure_blocks: bool = False,
        streak_blocks: bool = False,
        recovered_leftover: bool = False,
    ) -> dict[str, object]:
        return overlay_session_response_honesty_stamps(
            payload,
            pressure_blocks=True,
            streak_blocks=streak_blocks,
            recovered_leftover=recovered_leftover,
        )

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "intent": "coach",
        "message": "What should I do next?",
        "response_language": "en-US",
        "use_agent_loop": False,
    }

    transport = httpx.ASGITransport(app=app)
    with (
        patch.object(ProviderService, "coaching_reply", new=slow_reply),
        patch("app.api.routers.overlay_session_response_honesty_stamps", force_honesty_overlay),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(client.post("/turn", json=payload))
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(client.post("/turn", json=payload))
            await asyncio.sleep(0.05)
            assert call_count == 1
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert call_count == 1
    body2 = r2.json()
    agent_meta = body2.get("agent_meta") if isinstance(body2.get("agent_meta"), dict) else {}
    assert agent_meta.get("pressure_blocks_live_object_mint") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["/session/message", "/turn", "/session/message/stream", "/turn/stream"],
)
async def test_failed_last_test_honesty_same_request_id_singleflights(
    tmp_path: Path,
    path: str,
) -> None:
    """Failed last-test honesty SSE/JSON must claim before return — one user append."""
    app = _build_app(tmp_path)
    workspace_id = f"workspace-failed-lt-{path.strip('/').replace('/', '-')}"
    request_id = f"failed-lt-{path.strip('/').replace('/', '-')}"
    message = "Give me the next small debugging step."

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        _mark_provider_last_test_failed(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
        )
        assert runtime.provider_connection_verified(runtime.provider_service) is False

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "message": message,
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    if path in {"/turn", "/turn/stream"}:
        payload["intent"] = "coach"
    if path.endswith("/stream"):
        payload["stream_id"] = f"stream-{request_id}-a"
        payload_b = {**payload, "stream_id": f"stream-{request_id}-b"}
    else:
        payload_b = payload

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r1, r2 = await asyncio.gather(
            client.post(path, json=payload),
            client.post(path, json=payload_b),
        )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    if path.endswith("/stream"):
        body1 = _parse_sse_complete_response(r1.text)
        body2 = _parse_sse_complete_response(r2.text)
    else:
        body1 = r1.json()
        body2 = r2.json()
    assert (body1.get("reliability") or {}).get("outcome") == "failure"
    assert (body2.get("reliability") or {}).get("outcome") == "failure"

    state = runtime.ensure_session(session_id, workspace_id=workspace_id)
    user_msgs = [
        message_row
        for message_row in state.snapshot.messages
        if message_row.role == "user" and message_row.content == message
    ]
    assert len(user_msgs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner_path", "waiter_path"),
    [
        ("/session/message", "/turn"),
        ("/turn", "/session/message"),
    ],
)
async def test_cross_route_same_request_id_executes_once(
    tmp_path: Path,
    owner_path: str,
    waiter_path: str,
) -> None:
    """Session+turn racing same request_id must share one inflight claim — one coaching exec."""
    app = _build_app(tmp_path)
    workspace_id = f"workspace-cross-route-{owner_path.strip('/').replace('/', '-')}-owner"
    request_id = "cross-route-same-1"
    message = "What should I do next?"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_reply(*_args, **_kwargs) -> str:
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        return "Cross-route single-flight shared reply."

    def _payload_for(path: str) -> dict[str, object]:
        body: dict[str, object] = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "request_id": request_id,
            "message": message,
            "response_language": "en-US",
            "use_agent_loop": False,
        }
        if path == "/turn":
            body["intent"] = "coach"
        return body

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "coaching_reply", new=slow_reply):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(client.post(owner_path, json=_payload_for(owner_path)))
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(client.post(waiter_path, json=_payload_for(waiter_path)))
            await asyncio.sleep(0.05)
            assert call_count == 1
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert call_count == 1
    body1 = r1.json()
    body2 = r2.json()
    assert "Cross-route single-flight shared reply." in str(body1.get("reply") or body1)
    assert "Cross-route single-flight shared reply." in str(body2.get("reply") or body2)

    state = runtime.ensure_session(session_id, workspace_id=workspace_id)
    user_msgs = [
        message_row
        for message_row in state.snapshot.messages
        if message_row.role == "user" and message_row.content == message
    ]
    assert len(user_msgs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner_path", "waiter_path"),
    [
        ("/session/message", "/turn"),
        ("/turn", "/session/message"),
    ],
)
async def test_cross_route_waiter_gets_honesty_overlay_stamps(
    tmp_path: Path,
    owner_path: str,
    waiter_path: str,
) -> None:
    """Cross-route waiter replay must carry additive honesty stamps on the shared payload."""
    app = _build_app(tmp_path)
    workspace_id = f"workspace-cross-honesty-{owner_path.strip('/').replace('/', '-')}"
    request_id = "cross-route-honesty-1"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_reply(*_args, **_kwargs) -> str:
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        return "Cross-route honesty reply."

    def force_honesty_overlay(
        payload: dict[str, object],
        *,
        pressure_blocks: bool = False,
        streak_blocks: bool = False,
        recovered_leftover: bool = False,
    ) -> dict[str, object]:
        return overlay_session_response_honesty_stamps(
            payload,
            pressure_blocks=True,
            streak_blocks=streak_blocks,
            recovered_leftover=recovered_leftover,
        )

    def _payload_for(path: str) -> dict[str, object]:
        body: dict[str, object] = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "request_id": request_id,
            "message": "What should I do next?",
            "response_language": "en-US",
            "use_agent_loop": False,
        }
        if path == "/turn":
            body["intent"] = "coach"
        return body

    transport = httpx.ASGITransport(app=app)
    with (
        patch.object(ProviderService, "coaching_reply", new=slow_reply),
        patch("app.api.routers.overlay_session_response_honesty_stamps", force_honesty_overlay),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(client.post(owner_path, json=_payload_for(owner_path)))
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(client.post(waiter_path, json=_payload_for(waiter_path)))
            await asyncio.sleep(0.05)
            assert call_count == 1
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert call_count == 1
    body2 = r2.json()
    agent_meta = body2.get("agent_meta") if isinstance(body2.get("agent_meta"), dict) else {}
    assert agent_meta.get("pressure_blocks_live_object_mint") is True


def test_cross_route_distinct_request_ids_still_independent(tmp_path: Path) -> None:
    """Distinct ids on /session/message vs /turn must not collapse into one flight."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-cross-route-distinct"
    calls: list[str] = []

    async def counting_reply(*_args, **_kwargs) -> str:
        calls.append("hit")
        return "Distinct cross-route reply."

    with TestClient(app) as client:
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

        with patch.object(ProviderService, "coaching_reply", new=counting_reply):
            r1 = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "request_id": "cross-distinct-a",
                    "message": "First distinct ask.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )
            r2 = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "request_id": "cross-distinct-b",
                    "intent": "coach",
                    "message": "Second distinct ask.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )
            assert r1.status_code == 200, r1.text
            assert r2.status_code == 200, r2.text
    assert len(calls) == 2


def _is_stream_path(path: str) -> bool:
    return path.endswith("/stream")


def _cross_route_payload(
    *,
    path: str,
    session_id: str,
    workspace_id: str,
    request_id: str,
    message: str,
    stream_suffix: str = "a",
) -> dict[str, object]:
    body: dict[str, object] = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "message": message,
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    if path in {"/turn", "/turn/stream"}:
        body["intent"] = "coach"
    if _is_stream_path(path):
        body["stream_id"] = f"stream-{request_id}-{stream_suffix}"
    return body


def _body_for_path(path: str, response: httpx.Response) -> dict[str, object]:
    if _is_stream_path(path):
        return _parse_sse_complete_response(response.text)
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner_path", "waiter_path"),
    [
        ("/session/message/stream", "/turn/stream"),
        ("/turn/stream", "/session/message/stream"),
    ],
)
async def test_cross_route_stream_same_request_id_executes_once(
    tmp_path: Path,
    owner_path: str,
    waiter_path: str,
) -> None:
    """Session+turn stream racing same request_id must share one inflight claim."""
    app = _build_app(tmp_path)
    workspace_id = f"workspace-cross-stream-{owner_path.strip('/').replace('/', '-')}"
    request_id = "cross-route-stream-same-1"
    message = "What should I do next?"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_stream(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        yield "Cross-route stream single-flight reply."

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "coaching_reply_stream", new=slow_stream):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(
                client.post(
                    owner_path,
                    json=_cross_route_payload(
                        path=owner_path,
                        session_id=session_id,
                        workspace_id=workspace_id,
                        request_id=request_id,
                        message=message,
                        stream_suffix="owner",
                    ),
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(
                client.post(
                    waiter_path,
                    json=_cross_route_payload(
                        path=waiter_path,
                        session_id=session_id,
                        workspace_id=workspace_id,
                        request_id=request_id,
                        message=message,
                        stream_suffix="waiter",
                    ),
                )
            )
            await asyncio.sleep(0.05)
            assert call_count == 1
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert call_count == 1
    body1 = _body_for_path(owner_path, r1)
    body2 = _body_for_path(waiter_path, r2)
    assert "Cross-route stream single-flight reply." in str(body1.get("reply") or body1)
    assert "Cross-route stream single-flight reply." in str(body2.get("reply") or body2)

    state = runtime.ensure_session(session_id, workspace_id=workspace_id)
    user_msgs = [
        message_row
        for message_row in state.snapshot.messages
        if message_row.role == "user" and message_row.content == message
    ]
    assert len(user_msgs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner_path", "waiter_path"),
    [
        ("/session/message/stream", "/turn/stream"),
        ("/turn/stream", "/session/message/stream"),
    ],
)
async def test_cross_route_stream_waiter_gets_honesty_overlay_stamps(
    tmp_path: Path,
    owner_path: str,
    waiter_path: str,
) -> None:
    """Cross-route stream waiter complete-frame must carry additive honesty stamps."""
    app = _build_app(tmp_path)
    workspace_id = f"workspace-cross-stream-honesty-{owner_path.strip('/').replace('/', '-')}"
    request_id = "cross-route-stream-honesty-1"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_stream(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        yield "Cross-route stream honesty reply."

    def force_honesty_overlay(
        payload: dict[str, object],
        *,
        pressure_blocks: bool = False,
        streak_blocks: bool = False,
        recovered_leftover: bool = False,
    ) -> dict[str, object]:
        return overlay_session_response_honesty_stamps(
            payload,
            pressure_blocks=True,
            streak_blocks=streak_blocks,
            recovered_leftover=recovered_leftover,
        )

    transport = httpx.ASGITransport(app=app)
    with (
        patch.object(ProviderService, "coaching_reply_stream", new=slow_stream),
        patch("app.api.routers.overlay_session_response_honesty_stamps", force_honesty_overlay),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(
                client.post(
                    owner_path,
                    json=_cross_route_payload(
                        path=owner_path,
                        session_id=session_id,
                        workspace_id=workspace_id,
                        request_id=request_id,
                        message="What should I do next?",
                        stream_suffix="owner",
                    ),
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(
                client.post(
                    waiter_path,
                    json=_cross_route_payload(
                        path=waiter_path,
                        session_id=session_id,
                        workspace_id=workspace_id,
                        request_id=request_id,
                        message="What should I do next?",
                        stream_suffix="waiter",
                    ),
                )
            )
            await asyncio.sleep(0.05)
            assert call_count == 1
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert call_count == 1
    body2 = _body_for_path(waiter_path, r2)
    agent_meta = body2.get("agent_meta") if isinstance(body2.get("agent_meta"), dict) else {}
    assert agent_meta.get("pressure_blocks_live_object_mint") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner_path", "waiter_path"),
    [
        ("/session/message/stream", "/turn"),
        ("/turn/stream", "/session/message"),
        ("/session/message", "/turn/stream"),
        ("/turn", "/session/message/stream"),
    ],
)
async def test_cross_route_stream_nonstream_same_request_id_executes_once(
    tmp_path: Path,
    owner_path: str,
    waiter_path: str,
) -> None:
    """Stream+non-stream racing same request_id must share one coaching exec."""
    app = _build_app(tmp_path)
    workspace_id = (
        f"workspace-cross-mix-{owner_path.strip('/').replace('/', '-')}"
        f"-{waiter_path.strip('/').replace('/', '-')}"
    )
    request_id = "cross-route-mix-same-1"
    message = "What should I do next?"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_reply(*_args, **_kwargs) -> str:
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        return "Cross-route mix single-flight reply."

    async def slow_stream(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        yield "Cross-route mix single-flight reply."

    transport = httpx.ASGITransport(app=app)
    with (
        patch.object(ProviderService, "coaching_reply", new=slow_reply),
        patch.object(ProviderService, "coaching_reply_stream", new=slow_stream),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(
                client.post(
                    owner_path,
                    json=_cross_route_payload(
                        path=owner_path,
                        session_id=session_id,
                        workspace_id=workspace_id,
                        request_id=request_id,
                        message=message,
                        stream_suffix="owner",
                    ),
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(
                client.post(
                    waiter_path,
                    json=_cross_route_payload(
                        path=waiter_path,
                        session_id=session_id,
                        workspace_id=workspace_id,
                        request_id=request_id,
                        message=message,
                        stream_suffix="waiter",
                    ),
                )
            )
            await asyncio.sleep(0.05)
            assert call_count == 1
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert call_count == 1
    body1 = _body_for_path(owner_path, r1)
    body2 = _body_for_path(waiter_path, r2)
    assert "Cross-route mix single-flight reply." in str(body1.get("reply") or body1)
    assert "Cross-route mix single-flight reply." in str(body2.get("reply") or body2)

    state = runtime.ensure_session(session_id, workspace_id=workspace_id)
    user_msgs = [
        message_row
        for message_row in state.snapshot.messages
        if message_row.role == "user" and message_row.content == message
    ]
    assert len(user_msgs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner_path", "waiter_path"),
    [
        ("/session/message/stream", "/turn"),
        ("/turn", "/session/message/stream"),
        ("/session/message", "/turn/stream"),
        ("/turn/stream", "/session/message"),
    ],
)
async def test_cross_route_stream_nonstream_waiter_honesty_overlay(
    tmp_path: Path,
    owner_path: str,
    waiter_path: str,
) -> None:
    """Stream↔non-stream waiter replay must stamp honesty on complete-frame or JSON."""
    app = _build_app(tmp_path)
    workspace_id = (
        f"workspace-cross-mix-honesty-{owner_path.strip('/').replace('/', '-')}"
        f"-{waiter_path.strip('/').replace('/', '-')}"
    )
    request_id = "cross-route-mix-honesty-1"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_reply(*_args, **_kwargs) -> str:
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        return "Cross-route mix honesty reply."

    async def slow_stream(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        yield "Cross-route mix honesty reply."

    def force_honesty_overlay(
        payload: dict[str, object],
        *,
        pressure_blocks: bool = False,
        streak_blocks: bool = False,
        recovered_leftover: bool = False,
    ) -> dict[str, object]:
        return overlay_session_response_honesty_stamps(
            payload,
            pressure_blocks=True,
            streak_blocks=streak_blocks,
            recovered_leftover=recovered_leftover,
        )

    transport = httpx.ASGITransport(app=app)
    with (
        patch.object(ProviderService, "coaching_reply", new=slow_reply),
        patch.object(ProviderService, "coaching_reply_stream", new=slow_stream),
        patch("app.api.routers.overlay_session_response_honesty_stamps", force_honesty_overlay),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(
                client.post(
                    owner_path,
                    json=_cross_route_payload(
                        path=owner_path,
                        session_id=session_id,
                        workspace_id=workspace_id,
                        request_id=request_id,
                        message="What should I do next?",
                        stream_suffix="owner",
                    ),
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(
                client.post(
                    waiter_path,
                    json=_cross_route_payload(
                        path=waiter_path,
                        session_id=session_id,
                        workspace_id=workspace_id,
                        request_id=request_id,
                        message="What should I do next?",
                        stream_suffix="waiter",
                    ),
                )
            )
            await asyncio.sleep(0.05)
            assert call_count == 1
            release.set()
            r1, r2 = await asyncio.gather(first, second)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert call_count == 1
    body2 = _body_for_path(waiter_path, r2)
    agent_meta = body2.get("agent_meta") if isinstance(body2.get("agent_meta"), dict) else {}
    assert agent_meta.get("pressure_blocks_live_object_mint") is True


def test_cross_route_stream_distinct_request_ids_still_independent(tmp_path: Path) -> None:
    """Distinct stream ids on session vs turn must not collapse into one flight."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-cross-stream-distinct"
    calls: list[str] = []

    async def counting_stream(*_args, **_kwargs):
        calls.append("hit")
        yield "Distinct cross-route stream reply."

    with TestClient(app) as client:
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

        with patch.object(ProviderService, "coaching_reply_stream", new=counting_stream):
            r1 = client.post(
                "/session/message/stream",
                json=_cross_route_payload(
                    path="/session/message/stream",
                    session_id=session_id,
                    workspace_id=workspace_id,
                    request_id="cross-stream-distinct-a",
                    message="First distinct stream ask.",
                    stream_suffix="a",
                ),
            )
            r2 = client.post(
                "/turn/stream",
                json=_cross_route_payload(
                    path="/turn/stream",
                    session_id=session_id,
                    workspace_id=workspace_id,
                    request_id="cross-stream-distinct-b",
                    message="Second distinct stream ask.",
                    stream_suffix="b",
                ),
            )
            assert r1.status_code == 200, r1.text
            assert r2.status_code == 200, r2.text
    assert len(calls) == 2

@pytest.mark.asyncio
async def test_stream_cancel_fail_inflight_unblocks_same_request_id_waiter(
    tmp_path: Path,
) -> None:
    """Host /stream/cancel mid-flight must fail_inflight — waiter must not hang forever."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-session-inflight-cancel-1"
    request_id = "session-inflight-cancel-1"
    owner_stream_id = f"stream-{request_id}-owner"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()

    async def cancellable_stream(*_args, **kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        cancel_event = kwargs.get("cancel_event")
        assert isinstance(cancel_event, asyncio.Event)
        await cancel_event.wait()
        raise asyncio.CancelledError
        yield "unreachable"  # pragma: no cover — makes this an async generator

    owner_payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": owner_stream_id,
        "message": "Cancel me mid-flight.",
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    waiter_payload = {
        **owner_payload,
        "stream_id": f"stream-{request_id}-waiter",
    }

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "coaching_reply_stream", new=cancellable_stream):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            owner = asyncio.create_task(
                client.post("/session/message/stream", json=owner_payload)
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            waiter = asyncio.create_task(
                client.post("/session/message/stream", json=waiter_payload)
            )
            await asyncio.sleep(0.05)
            assert call_count == 1
            cancel = await client.post(
                "/stream/cancel",
                json={"stream_id": owner_stream_id},
            )
            assert cancel.status_code == 200, cancel.text
            assert cancel.json().get("status") == "cancellation_requested"
            owner_resp, waiter_resp = await asyncio.wait_for(
                asyncio.gather(owner, waiter),
                timeout=5.0,
            )

    assert call_count == 1
    assert owner_resp.status_code == 200, owner_resp.text
    assert waiter_resp.status_code == 200, waiter_resp.text
    assert "event: status" in owner_resp.text
    assert '"phase": "failed"' in owner_resp.text
    assert '"phase": "acked"' in owner_resp.text
    # Waiter must terminate (error or complete) — not hang on owner future.
    assert (
        "event: error" in waiter_resp.text
        or "event: complete" in waiter_resp.text
        or '"phase": "failed"' in waiter_resp.text
    )
    assert "unreachable" not in owner_resp.text
    assert "unreachable" not in waiter_resp.text


@pytest.mark.asyncio
async def test_session_stream_mid_turn_cancel_emits_failed_acked_without_cancelled_error(
    tmp_path: Path,
) -> None:
    """stream_cancelled() early return (not CancelledError) must still emit failed→acked."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-session-mid-turn-cancel-1"
    request_id = "session-mid-turn-cancel-1"
    owner_stream_id = f"stream-{request_id}-owner"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    entered = asyncio.Event()

    async def hang_then_end(*_args, **kwargs):
        entered.set()
        cancel_event = kwargs.get("cancel_event")
        assert isinstance(cancel_event, asyncio.Event)
        await cancel_event.wait()
        # End without raising CancelledError — hits mid-turn stream_cancelled() return.
        return
        yield "unreachable"  # pragma: no cover — async generator

    owner_payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": owner_stream_id,
        "message": "Cancel after provider hang ends cleanly.",
        "response_language": "en-US",
        "use_agent_loop": False,
    }

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "coaching_reply_stream", new=hang_then_end):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            owner = asyncio.create_task(
                client.post("/session/message/stream", json=owner_payload)
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            cancel = await client.post(
                "/stream/cancel",
                json={"stream_id": owner_stream_id},
            )
            assert cancel.status_code == 200, cancel.text
            owner_resp = await asyncio.wait_for(owner, timeout=5.0)

    assert owner_resp.status_code == 200, owner_resp.text
    assert '"phase": "failed"' in owner_resp.text
    assert '"phase": "acked"' in owner_resp.text
    assert "unreachable" not in owner_resp.text


@pytest.mark.asyncio
async def test_turn_stream_cancel_fail_inflight_unblocks_same_request_id_waiter(
    tmp_path: Path,
) -> None:
    """Host /stream/cancel mid-flight on /turn/stream must fail_inflight — waiter must not hang."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-turn-inflight-cancel-1"
    request_id = "turn-inflight-cancel-1"
    owner_stream_id = f"stream-{request_id}-owner"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()

    async def cancellable_stream(*_args, **kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        cancel_event = kwargs.get("cancel_event")
        assert isinstance(cancel_event, asyncio.Event)
        await cancel_event.wait()
        raise asyncio.CancelledError
        yield "unreachable"  # pragma: no cover — makes this an async generator

    owner_payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": owner_stream_id,
        "intent": "coach",
        "message": "Cancel me mid-flight on turn stream.",
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    waiter_payload = {
        **owner_payload,
        "stream_id": f"stream-{request_id}-waiter",
    }

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "coaching_reply_stream", new=cancellable_stream):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            owner = asyncio.create_task(
                client.post("/turn/stream", json=owner_payload)
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            waiter = asyncio.create_task(
                client.post("/turn/stream", json=waiter_payload)
            )
            await asyncio.sleep(0.05)
            assert call_count == 1
            cancel = await client.post(
                "/stream/cancel",
                json={"stream_id": owner_stream_id},
            )
            assert cancel.status_code == 200, cancel.text
            assert cancel.json().get("status") == "cancellation_requested"
            owner_resp, waiter_resp = await asyncio.wait_for(
                asyncio.gather(owner, waiter),
                timeout=5.0,
            )

    assert call_count == 1
    assert owner_resp.status_code == 200, owner_resp.text
    assert waiter_resp.status_code == 200, waiter_resp.text
    assert "event: status" in owner_resp.text
    assert '"phase": "failed"' in owner_resp.text
    assert '"phase": "acked"' in owner_resp.text
    # Waiter error path must terminate with failure complete (honesty overlay) or status.
    assert "event: complete" in waiter_resp.text or '"phase": "failed"' in waiter_resp.text
    assert "unreachable" not in owner_resp.text
    assert "unreachable" not in waiter_resp.text


@pytest.mark.asyncio
async def test_stream_waiter_error_path_emits_failure_complete_with_overlay_hook(
    tmp_path: Path,
) -> None:
    """Waiter exception path must yield failure complete (overlay applied), not error-only."""
    app = _build_app(tmp_path)
    workspace_id = "workspace-waiter-error-overlay-1"
    request_id = "waiter-error-overlay-1"
    owner_stream_id = f"stream-{request_id}-owner"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    entered = asyncio.Event()

    async def cancellable_stream(*_args, **kwargs):
        entered.set()
        cancel_event = kwargs.get("cancel_event")
        assert isinstance(cancel_event, asyncio.Event)
        await cancel_event.wait()
        raise asyncio.CancelledError
        yield "unreachable"  # pragma: no cover

    owner_payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": owner_stream_id,
        "message": "Owner fails; waiter needs failure complete.",
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    waiter_payload = {
        **owner_payload,
        "stream_id": f"stream-{request_id}-waiter",
    }

    stamped_calls: list[dict[str, object]] = []

    def tracking_overlay(payload, **kwargs):
        out = overlay_session_response_honesty_stamps(
            payload,
            pressure_blocks=True,
            streak_blocks=True,
            recovered_leftover=True,
        )
        stamped_calls.append(out)
        return out

    transport = httpx.ASGITransport(app=app)
    with (
        patch.object(ProviderService, "coaching_reply_stream", new=cancellable_stream),
        patch(
            "app.api.routers.overlay_session_response_honesty_stamps",
            side_effect=tracking_overlay,
        ),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            owner = asyncio.create_task(
                client.post("/session/message/stream", json=owner_payload)
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            waiter = asyncio.create_task(
                client.post("/session/message/stream", json=waiter_payload)
            )
            await asyncio.sleep(0.05)
            cancel = await client.post(
                "/stream/cancel",
                json={"stream_id": owner_stream_id},
            )
            assert cancel.status_code == 200, cancel.text
            owner_resp, waiter_resp = await asyncio.wait_for(
                asyncio.gather(owner, waiter),
                timeout=5.0,
            )

    assert owner_resp.status_code == 200, owner_resp.text
    assert waiter_resp.status_code == 200, waiter_resp.text
    assert "event: complete" in waiter_resp.text
    assert '"outcome": "failure"' in waiter_resp.text
    assert stamped_calls, "waiter error path must call honesty overlay"
    last = stamped_calls[-1]
    agent_meta = last.get("agent_meta")
    assert isinstance(agent_meta, dict)
    assert agent_meta.get("pressure_blocks_live_object_mint") is True
    assert agent_meta.get("streak_blocks_live_object_mint") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
async def test_owner_exception_publishes_failure_complete_blocks_remint(
    tmp_path: Path,
    path: str,
) -> None:
    """Owner except Exception must emit failed->acked + publish so same request_id cannot remint."""
    app = _build_app(tmp_path)
    workspace_id = f"workspace-owner-exc-{path.strip('/').replace('/', '-')}"
    request_id = f"owner-exc-{path.strip('/').replace('/', '-')}"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0

    async def boom_stream(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("provider boom for remint proof")
        yield "unreachable"  # pragma: no cover

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-a",
        "message": "Trigger owner exception path.",
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    if path == "/turn/stream":
        payload["intent"] = "coach"
    retry_payload = {**payload, "stream_id": f"stream-{request_id}-b"}

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "coaching_reply_stream", new=boom_stream):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(path, json=payload)
            second = await client.post(path, json=retry_payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert '"phase": "failed"' in first.text
    assert '"phase": "acked"' in first.text
    assert "event: complete" in first.text
    assert "event: complete" in second.text
    body1 = _parse_sse_complete_response(first.text)
    body2 = _parse_sse_complete_response(second.text)
    assert (body1.get("reliability") or {}).get("outcome") == "failure"
    assert (body2.get("reliability") or {}).get("outcome") == "failure"
    assert call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
async def test_agent_loop_error_event_publishes_failure_complete_blocks_remint(
    tmp_path: Path,
    path: str,
) -> None:
    """Agent-loop event_type==error must failed->acked + publish; retry must not remint."""
    app = _build_app(tmp_path)
    workspace_id = f"workspace-agent-err-{path.strip('/').replace('/', '-')}"
    request_id = f"agent-err-{path.strip('/').replace('/', '-')}"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        provider = ProviderConfig(
            name="test-agent-error-remint",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
        runtime.provider_service = ProviderService(
            config=provider,
            api_key="sk-test-not-a-real-key-aaaaaaaa",
        )
        runtime.provider_service_cache.clear()
        mark_provider_capabilities_verified(
            runtime,
            provider,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=True,
        )

    call_count = 0

    async def error_agent_stream(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        yield {"type": "error", "detail": "agent loop terminal error", "category": "provider"}

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-a",
        "message": "Trigger agent error event.",
        "response_language": "en-US",
        "use_agent_loop": True,
    }
    if path == "/turn/stream":
        payload["intent"] = "coach"
    retry_payload = {**payload, "stream_id": f"stream-{request_id}-b"}

    transport = httpx.ASGITransport(app=app)
    with patch.object(
        ProviderService,
        "coaching_reply_agentic_stream",
        new=error_agent_stream,
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(path, json=payload)
            second = await client.post(path, json=retry_payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert '"phase": "failed"' in first.text
    assert '"phase": "acked"' in first.text
    assert "event: complete" in first.text
    assert "event: complete" in second.text
    body1 = _parse_sse_complete_response(first.text)
    body2 = _parse_sse_complete_response(second.text)
    assert (body1.get("reliability") or {}).get("outcome") == "failure"
    assert (body2.get("reliability") or {}).get("outcome") == "failure"
    assert call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
async def test_mid_turn_cancel_publishes_failure_complete_blocks_remint(
    tmp_path: Path,
    path: str,
) -> None:
    """Mid-turn stream_cancelled abort must publish failure complete; retry must not remint."""
    app = _build_app(tmp_path)
    workspace_id = f"workspace-mid-remint-{path.strip('/').replace('/', '-')}"
    request_id = f"mid-remint-{path.strip('/').replace('/', '-')}"
    owner_stream_id = f"stream-{request_id}-owner"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    entered = asyncio.Event()

    async def hang_then_end(*_args, **kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        cancel_event = kwargs.get("cancel_event")
        assert isinstance(cancel_event, asyncio.Event)
        await cancel_event.wait()
        return
        yield "unreachable"  # pragma: no cover

    owner_payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": owner_stream_id,
        "message": "Cancel mid-turn then retry same request_id.",
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    if path == "/turn/stream":
        owner_payload["intent"] = "coach"
    retry_payload = {**owner_payload, "stream_id": f"stream-{request_id}-retry"}

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "coaching_reply_stream", new=hang_then_end):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            owner = asyncio.create_task(client.post(path, json=owner_payload))
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            cancel = await client.post(
                "/stream/cancel",
                json={"stream_id": owner_stream_id},
            )
            assert cancel.status_code == 200, cancel.text
            owner_resp = await asyncio.wait_for(owner, timeout=5.0)
            retry_resp = await client.post(path, json=retry_payload)

    assert owner_resp.status_code == 200, owner_resp.text
    assert retry_resp.status_code == 200, retry_resp.text
    assert '"phase": "failed"' in owner_resp.text
    assert '"phase": "acked"' in owner_resp.text
    assert "event: complete" in owner_resp.text
    assert "event: complete" in retry_resp.text
    body1 = _parse_sse_complete_response(owner_resp.text)
    body2 = _parse_sse_complete_response(retry_resp.text)
    assert (body1.get("reliability") or {}).get("outcome") == "failure"
    assert (body2.get("reliability") or {}).get("outcome") == "failure"
    assert call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
@pytest.mark.parametrize(
    "boom",
    [
        pytest.param(RuntimeError("honest unusable boom for remint"), id="exception"),
        pytest.param(asyncio.CancelledError(), id="cancelled"),
    ],
)
async def test_honest_unusable_provider_stream_abort_publishes_failure_complete_blocks_remint(
    tmp_path: Path,
    path: str,
    boom: BaseException,
) -> None:
    """honest_unusable CancelledError/Exception must publish failure complete; retry must not remint."""
    app = _build_app(tmp_path)
    workspace_id = f"workspace-honest-abort-{path.strip('/').replace('/', '-')}-{type(boom).__name__}"
    request_id = f"honest-abort-{path.strip('/').replace('/', '-')}-{type(boom).__name__}"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        # Never-tested capability cache → honest_unusable_provider_stream path.
        runtime.provider_capability_cache.clear()

    call_count = 0
    real_message = None

    def counting_chat_message(*args, **kwargs):
        nonlocal call_count, real_message
        call_count += 1
        if call_count == 1:
            raise boom
        assert real_message is not None
        return real_message(*args, **kwargs)

    import app.api.routers as routers_mod
    from app.core.models import ChatMessage as RealChatMessage

    real_message = RealChatMessage

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-a",
        "message": "Honest abort must publish and block remint.",
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    if path == "/turn/stream":
        payload["intent"] = "coach"
    retry_payload = {**payload, "stream_id": f"stream-{request_id}-b"}

    transport = httpx.ASGITransport(app=app)
    with patch.object(routers_mod, "ChatMessage", side_effect=counting_chat_message):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(path, json=payload)
            second = await client.post(path, json=retry_payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert '"phase": "failed"' in first.text
    assert '"phase": "acked"' in first.text
    assert "event: complete" in first.text
    assert "event: complete" in second.text
    body1 = _parse_sse_complete_response(first.text)
    body2 = _parse_sse_complete_response(second.text)
    assert (body1.get("reliability") or {}).get("outcome") == "failure"
    assert (body2.get("reliability") or {}).get("outcome") == "failure"
    # Published failure complete: same request_id retry must not re-enter execute_turn mint.
    assert call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
async def test_cancel_before_commit_publishes_failure_complete_blocks_remint(
    tmp_path: Path,
    path: str,
) -> None:
    """Built-payload cancel-before-commit must publish failure; same request_id retry must not invent."""
    app = _build_app(tmp_path)
    workspace_id = f"workspace-precommit-{path.strip('/').replace('/', '-')}"
    request_id = f"precommit-remint-{path.strip('/').replace('/', '-')}"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

    call_count = 0
    stream_done = False
    captured_cancel: asyncio.Event | None = None
    orig_snapshot = runtime.memory_service.snapshot

    async def finish_then_allow_precommit_cancel(*_args, **kwargs):
        nonlocal call_count, stream_done, captured_cancel
        call_count += 1
        captured_cancel = kwargs.get("cancel_event")
        yield "Pre-commit cancel remint proof reply."
        stream_done = True

    def snapshot_arm_precommit_cancel(ws: str):
        result = orig_snapshot(ws)
        # Arm after mid-turn checks, before commit publish (built payload path).
        if stream_done and captured_cancel is not None and not captured_cancel.is_set():
            captured_cancel.set()
        return result

    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-a",
        "message": "Cancel after payload build, before commit.",
        "response_language": "en-US",
        "use_agent_loop": False,
    }
    if path == "/turn/stream":
        payload["intent"] = "coach"
    retry_payload = {**payload, "stream_id": f"stream-{request_id}-b"}

    transport = httpx.ASGITransport(app=app)
    with (
        patch.object(ProviderService, "coaching_reply_stream", new=finish_then_allow_precommit_cancel),
        patch.object(runtime.memory_service, "snapshot", side_effect=snapshot_arm_precommit_cancel),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(path, json=payload)
            second = await client.post(path, json=retry_payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert '"phase": "failed"' in first.text
    assert '"phase": "acked"' in first.text
    assert "event: complete" in first.text
    assert "event: complete" in second.text
    body1 = _parse_sse_complete_response(first.text)
    body2 = _parse_sse_complete_response(second.text)
    assert (body1.get("reliability") or {}).get("outcome") == "failure"
    assert (body2.get("reliability") or {}).get("outcome") == "failure"
    # Before-commit path publishes the built payload (not empty mid-turn abort).
    reply = body1.get("reply")
    assert isinstance(reply, dict)
    assert "Pre-commit cancel remint proof reply." in str(reply.get("content") or "")
    assert call_count == 1
    assert stream_done is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,extra_payload",
    [
        ("/session/message/stream", {}),
        ("/turn/stream", {"intent": "coach"}),
        # Non-coach turn prep path — routers.py built-payload cancel before commit (~23235).
        (
            "/turn/stream",
            {
                "intent": "review",
                "current_file": {
                    "path": "main.py",
                    "language_id": "python",
                    "content": "print('agent-precommit')\n",
                },
            },
        ),
    ],
)
async def test_agent_loop_cancel_before_commit_publishes_failure_complete_blocks_remint(
    tmp_path: Path,
    path: str,
    extra_payload: dict[str, object],
) -> None:
    """Agent-loop built-payload cancel-before-commit must publish; same request_id must not remint."""
    app = _build_app(tmp_path)
    case = str(extra_payload.get("intent") or "session")
    workspace_id = f"workspace-agent-precommit-{path.strip('/').replace('/', '-')}-{case}"
    request_id = f"agent-precommit-remint-{path.strip('/').replace('/', '-')}-{case}"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
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
        runtime = app.state.runtime
        provider = ProviderConfig(
            name="test-agent-precommit-remint",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={"chat": True, "tools": True, "streaming": True},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
        runtime.provider_service = ProviderService(
            config=provider,
            api_key="sk-test-not-a-real-key-aaaaaaaa",
        )
        runtime.provider_service_cache.clear()
        mark_provider_capabilities_verified(
            runtime,
            provider,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=True,
        )

    call_count = 0
    stream_done = False
    captured_cancel: asyncio.Event | None = None
    orig_snapshot = runtime.memory_service.snapshot
    proof_reply = "Agent pre-commit cancel remint proof reply."

    async def finish_agent_then_allow_precommit_cancel(*_args, **kwargs):
        nonlocal call_count, stream_done, captured_cancel
        call_count += 1
        ctx = kwargs.get("coach_context")
        if isinstance(ctx, dict):
            captured_cancel = ctx.get("stream_cancel_event")
        yield {
            "type": "text",
            "delta": proof_reply,
            "safe_to_stream": True,
        }
        yield {
            "type": "final",
            "content": proof_reply,
            "stop_reason": "completed",
        }
        stream_done = True

    def snapshot_arm_precommit_cancel(ws: str):
        result = orig_snapshot(ws)
        # Arm after mid-turn / post-agent abort gates, before commit publish.
        if stream_done and captured_cancel is not None and not captured_cancel.is_set():
            captured_cancel.set()
        return result

    payload: dict[str, object] = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-a",
        "message": "Cancel after agent payload build, before commit.",
        "response_language": "en-US",
        "use_agent_loop": True,
        **extra_payload,
    }
    if path == "/turn/stream" and "intent" not in payload:
        payload["intent"] = "coach"
    retry_payload = {**payload, "stream_id": f"stream-{request_id}-b"}

    transport = httpx.ASGITransport(app=app)
    with (
        patch.object(
            ProviderService,
            "coaching_reply_agentic_stream",
            new=finish_agent_then_allow_precommit_cancel,
        ),
        patch.object(runtime.memory_service, "snapshot", side_effect=snapshot_arm_precommit_cancel),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(path, json=payload)
            second = await client.post(path, json=retry_payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert '"phase": "failed"' in first.text
    assert '"phase": "acked"' in first.text
    assert "event: complete" in first.text
    assert "event: complete" in second.text
    body1 = _parse_sse_complete_response(first.text)
    body2 = _parse_sse_complete_response(second.text)
    assert (body1.get("reliability") or {}).get("outcome") == "failure"
    assert (body2.get("reliability") or {}).get("outcome") == "failure"
    reply = body1.get("reply")
    assert isinstance(reply, dict)
    assert proof_reply in str(reply.get("content") or "")
    assert call_count == 1
    assert stream_done is True
