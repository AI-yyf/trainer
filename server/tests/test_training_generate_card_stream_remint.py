"""POST /training/generate-card/stream cancel remint — same request_id fail-closed."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from tests.test_leftover_training_card_identity import _seed_leftover_card_not_live
from tests.test_router_stream_scenarios import mark_provider_capabilities_verified


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer generate-card stream remint",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-generate-card-stream-remint.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _build_app(tmp_path: Path):
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
    return app


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
async def test_generate_card_stream_mid_cancel_publishes_failure_complete_blocks_remint(
    tmp_path: Path,
) -> None:
    """Cancel mid-stream must failed→acked + publish; same request_id retry must not remint."""
    app = _build_app(tmp_path)
    workspace_id = "ws-generate-card-mid-remint"
    request_id = "generate-card-mid-remint-1"
    owner_stream_id = f"stream-{request_id}-owner"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_id)
        cards_before = {
            card.card_id: card.title
            for card in runtime.memory_service.get_cards(workspace_id)
        }
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""

    call_count = 0
    entered = asyncio.Event()

    async def hang_then_end(self, *_args, **kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        cancel_event = kwargs.get("cancel_event")
        assert isinstance(cancel_event, asyncio.Event)
        await cancel_event.wait()
        return
        yield "unreachable"  # pragma: no cover

    owner_payload = {
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": owner_stream_id,
        "source": "conversation_gap",
        "card_type": "practice",
        "focus_area": "Add a token expiry test",
        "target_skill": "token expiry",
        "response_language": "en-US",
    }
    retry_payload = {**owner_payload, "stream_id": f"stream-{request_id}-retry"}

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "chat_completion_stream", new=hang_then_end):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            owner = asyncio.create_task(
                client.post("/training/generate-card/stream", json=owner_payload)
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            cancel = await client.post(
                "/stream/cancel",
                json={"stream_id": owner_stream_id},
            )
            assert cancel.status_code == 200, cancel.text
            owner_resp = await asyncio.wait_for(owner, timeout=5.0)
            retry_resp = await client.post(
                "/training/generate-card/stream",
                json=retry_payload,
            )

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

    with TestClient(app) as probe:
        runtime = probe.app.state.runtime
        still = {
            card.card_id: card.title
            for card in runtime.memory_service.get_cards(workspace_id)
        }
        assert still == cards_before
        assert leftover_card_id in still
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""


@pytest.mark.asyncio
async def test_generate_card_stream_exception_publishes_failure_complete_blocks_remint(
    tmp_path: Path,
) -> None:
    """Owner exception must failed→acked + publish; same request_id retry must not remint."""
    app = _build_app(tmp_path)
    workspace_id = "ws-generate-card-exc-remint"
    request_id = "generate-card-exc-remint-1"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_id)
        cards_before = {
            card.card_id: card.title
            for card in runtime.memory_service.get_cards(workspace_id)
        }

    call_count = 0

    async def boom_stream(self, *_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("provider boom for generate-card remint proof")
        yield "unreachable"  # pragma: no cover

    payload = {
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-a",
        "source": "conversation_gap",
        "card_type": "practice",
        "focus_area": "Add a token expiry test",
        "target_skill": "token expiry",
        "response_language": "en-US",
    }
    retry = {**payload, "stream_id": f"stream-{request_id}-b"}

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "chat_completion_stream", new=boom_stream):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/training/generate-card/stream", json=payload)
            second = await client.post("/training/generate-card/stream", json=retry)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert "event: error" in first.text
    assert '"phase": "failed"' in first.text
    assert '"phase": "acked"' in first.text
    body1 = _parse_sse_complete_response(first.text)
    body2 = _parse_sse_complete_response(second.text)
    assert (body1.get("reliability") or {}).get("outcome") == "failure"
    assert (body2.get("reliability") or {}).get("outcome") == "failure"
    assert call_count == 1

    with TestClient(app) as probe:
        runtime = probe.app.state.runtime
        still = {
            card.card_id: card.title
            for card in runtime.memory_service.get_cards(workspace_id)
        }
        assert still == cards_before
        assert leftover_card_id in still
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""


@pytest.mark.asyncio
async def test_generate_card_stream_concurrent_same_request_id_executes_once(
    tmp_path: Path,
) -> None:
    """Two in-flight identical request_ids must wait — one generate, shared complete."""
    app = _build_app(tmp_path)
    workspace_id = "ws-generate-card-concurrent-same"
    request_id = "generate-card-concurrent-same-1"

    card_payload = {
        "title": "Practice concurrent singleflight",
        "focus_area": "JSON",
        "target_skill": "stream parsing",
        "scenario": "Build a safe parser",
        "problem_statement": "Parse one response without losing boundaries.",
        "api_hints": ["Use the accumulated visible chunks."],
        "deliverable": "A parsed card",
        "self_check": ["Verify the JSON before persistence."],
        "grading_rubric": ["The card is complete and grounded."],
        "stuck_recovery": "Inspect the accumulated response.",
        "reflection_prompt": "What boundary made the parse reliable?",
    }

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_id)
        cards_before = {
            card.card_id: card.title
            for card in runtime.memory_service.get_cards(workspace_id)
        }
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_stream(self, *_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        yield json.dumps(card_payload)

    payload = {
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-a",
        "source": "conversation_gap",
        "card_type": "practice",
        "focus_area": "JSON",
        "target_skill": "stream parsing",
        "response_language": "en-US",
    }
    payload_b = {**payload, "stream_id": f"stream-{request_id}-b"}

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "chat_completion_stream", new=slow_stream):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(
                client.post("/training/generate-card/stream", json=payload)
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(
                client.post("/training/generate-card/stream", json=payload_b)
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
    assert (body1.get("reliability") or {}).get("outcome") == "success"
    assert (body2.get("reliability") or {}).get("outcome") == "success"
    card1 = body1.get("card") if isinstance(body1.get("card"), dict) else {}
    card2 = body2.get("card") if isinstance(body2.get("card"), dict) else {}
    assert card1.get("title") == card_payload["title"]
    assert card2.get("title") == card_payload["title"]
    assert card1.get("card_id") == card2.get("card_id")

    with TestClient(app) as probe:
        runtime = probe.app.state.runtime
        still = {
            card.card_id: card.title
            for card in runtime.memory_service.get_cards(workspace_id)
        }
        assert leftover_card_id in still
        assert still[leftover_card_id] == cards_before[leftover_card_id]
        live_id = runtime.memory_service.live_selected_training_card_id(workspace_id)
        assert live_id
        assert live_id != leftover_card_id
        assert live_id == card1.get("card_id")


@pytest.mark.asyncio
async def test_generate_card_stream_concurrent_same_request_id_failure_complete(
    tmp_path: Path,
) -> None:
    """Owner failure while waiter inflight: one generate, both get failure complete."""
    app = _build_app(tmp_path)
    workspace_id = "ws-generate-card-concurrent-fail"
    request_id = "generate-card-concurrent-fail-1"

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_id)
        cards_before = {
            card.card_id: card.title
            for card in runtime.memory_service.get_cards(workspace_id)
        }
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""

    call_count = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def boom_after_wait(self, *_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        entered.set()
        await release.wait()
        raise RuntimeError("provider boom for concurrent waiter proof")
        yield "unreachable"  # pragma: no cover

    payload = {
        "workspace_id": workspace_id,
        "request_id": request_id,
        "stream_id": f"stream-{request_id}-a",
        "source": "conversation_gap",
        "card_type": "practice",
        "focus_area": "Add a token expiry test",
        "target_skill": "token expiry",
        "response_language": "en-US",
    }
    payload_b = {**payload, "stream_id": f"stream-{request_id}-b"}

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "chat_completion_stream", new=boom_after_wait):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(
                client.post("/training/generate-card/stream", json=payload)
            )
            await asyncio.wait_for(entered.wait(), timeout=5.0)
            second = asyncio.create_task(
                client.post("/training/generate-card/stream", json=payload_b)
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
    assert (body1.get("reliability") or {}).get("outcome") == "failure"
    assert (body2.get("reliability") or {}).get("outcome") == "failure"

    with TestClient(app) as probe:
        runtime = probe.app.state.runtime
        still = {
            card.card_id: card.title
            for card in runtime.memory_service.get_cards(workspace_id)
        }
        assert still == cards_before
        assert leftover_card_id in still
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""


@pytest.mark.asyncio
async def test_generate_card_stream_success_still_binds_and_distinct_ids_mint(
    tmp_path: Path,
) -> None:
    """Success still binds a live card; distinct request_ids must not collapse."""
    app = _build_app(tmp_path)
    workspace_id = "ws-generate-card-success-bind"

    card_payload = {
        "title": "Practice remint-safe bind",
        "focus_area": "JSON",
        "target_skill": "stream parsing",
        "scenario": "Build a safe parser",
        "problem_statement": "Parse one response without losing boundaries.",
        "api_hints": ["Use the accumulated visible chunks."],
        "deliverable": "A parsed card",
        "self_check": ["Verify the JSON before persistence."],
        "grading_rubric": ["The card is complete and grounded."],
        "stuck_recovery": "Inspect the accumulated response.",
        "reflection_prompt": "What boundary made the parse reliable?",
    }

    call_count = 0

    async def fake_stream(self, *_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        yield json.dumps(card_payload)

    with TestClient(app) as bootstrap:
        start = bootstrap.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        runtime = app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_id)

    transport = httpx.ASGITransport(app=app)
    with patch.object(ProviderService, "chat_completion_stream", new=fake_stream):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.post(
                "/training/generate-card/stream",
                json={
                    "workspace_id": workspace_id,
                    "request_id": "generate-card-success-a",
                    "stream_id": "stream-generate-card-success-a",
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "JSON",
                    "target_skill": "stream parsing",
                    "response_language": "en-US",
                },
            )
            r2 = await client.post(
                "/training/generate-card/stream",
                json={
                    "workspace_id": workspace_id,
                    "request_id": "generate-card-success-b",
                    "stream_id": "stream-generate-card-success-b",
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "JSON",
                    "target_skill": "stream parsing",
                    "response_language": "en-US",
                },
            )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    body1 = _parse_sse_complete_response(r1.text)
    body2 = _parse_sse_complete_response(r2.text)
    assert (body1.get("reliability") or {}).get("outcome") == "success"
    assert (body2.get("reliability") or {}).get("outcome") == "success"
    assert call_count == 2
    card1 = body1.get("card") if isinstance(body1.get("card"), dict) else {}
    card2 = body2.get("card") if isinstance(body2.get("card"), dict) else {}
    assert card1.get("title") == card_payload["title"]
    assert card2.get("title") == card_payload["title"]

    with TestClient(app) as probe:
        runtime = probe.app.state.runtime
        live_id = runtime.memory_service.live_selected_training_card_id(workspace_id)
        assert live_id
        assert live_id != leftover_card_id
        card_ids = {card.card_id for card in runtime.memory_service.get_cards(workspace_id)}
        assert leftover_card_id in card_ids
        assert live_id in card_ids
