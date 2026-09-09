from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.core.models import (
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderTestResponse,
)
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def _seed_runtime(app: Any, *, base_url: str) -> None:
    provider = ProviderConfig(
        name="abort-idle-hang",
        base_url=base_url,
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        protocol="openai_chat_completions_compatible",
        capabilities={"tools": True, "streaming": True},
    )
    runtime = app.state.runtime
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test-fake"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test-fake")
    runtime.provider_service_cache.clear()
    runtime.remember_provider_capability_test(
        provider,
        "sk-test-fake",
        ProviderTestResponse(
            ok=True,
            detail="mocked provider capability test",
            capability_evidence=[
                ProviderCapabilityEvidence(
                    name="streaming",
                    declared=True,
                    observed=True,
                    state="verified",
                ),
                ProviderCapabilityEvidence(
                    name="tools",
                    declared=True,
                    observed=True,
                    state="verified",
                ),
            ],
            tools_ready=True,
            tool_probe_status="verified",
        ),
    )


def _build_app(tmp_path: Path, *, base_url: str = "http://127.0.0.1:9/v1") -> Any:
    settings = AppSettings(
        app_name="Trainer Abort Idle Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    _seed_runtime(app, base_url=base_url)
    return app


def _seed_session(client: TestClient, *, workspace_id: str) -> str:
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": "Abort idle",
            "profile": {"long_term_goal": "Prove cancel closes upstream", "weekly_hours": 1},
        },
    )
    assert response.status_code == 200
    session_id = response.json().get("session_id")
    assert isinstance(session_id, str) and session_id
    return session_id


@pytest.mark.asyncio
async def test_admission_middleware_forwards_http_disconnect() -> None:
    """BaseHTTPMiddleware swallowed disconnect; the ASGI gate must replay it."""
    from app.api.admission import BrowseOnlyAdmissionMiddleware

    seen: list[str] = []

    async def inner(scope: dict, receive: Any, send: Any) -> None:
        while True:
            message = await receive()
            seen.append(str(message.get("type") or ""))
            if message.get("type") == "http.disconnect":
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                await send({"type": "http.response.body", "body": b"ok"})
                return

    app = BrowseOnlyAdmissionMiddleware(inner)
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put({"type": "http.request", "body": b"{}", "more_body": False})

    async def receive() -> dict:
        return await queue.get()

    sent: list[str] = []

    async def send(message: dict) -> None:
        sent.append(str(message.get("type") or ""))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/turn",
        "raw_path": b"/turn",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
    }
    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.sleep(0.05)
    await queue.put({"type": "http.disconnect"})
    await asyncio.wait_for(task, timeout=2.0)
    assert "http.disconnect" in seen
    assert "http.response.start" in sent


class _Uvicorn(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        return


@pytest.mark.asyncio
async def test_nonstream_turn_tcp_abort_closes_hanging_upstream(tmp_path: Path) -> None:
    """Real HTTP client abort must EOF a hanging OpenAI-compatible upstream."""
    peer_eof = asyncio.Event()
    accepted = asyncio.Event()

    async def hang(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.set()
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = await reader.read(1024)
                if not chunk:
                    break
                data += chunk
            header, rest = (data.split(b"\r\n\r\n", 1) + [b""])[:2]
            content_length = 0
            for line in header.decode("latin1", errors="ignore").split("\r\n"):
                if line.lower().startswith("content-length:"):
                    content_length = int(line.split(":", 1)[1].strip() or 0)
            body = rest
            while len(body) < content_length:
                chunk = await reader.read(content_length - len(body))
                if not chunk:
                    break
                body += chunk
            while True:
                peek = await reader.read(1)
                if not peek:
                    peer_eof.set()
                    break
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    hang_server = await asyncio.start_server(hang, "127.0.0.1", 0)
    hang_port = hang_server.sockets[0].getsockname()[1]
    app = _build_app(tmp_path, base_url=f"http://127.0.0.1:{hang_port}/v1")
    with TestClient(app) as seed_client:
        session_id = _seed_session(seed_client, workspace_id="ws-abort-idle-tcp")

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", loop="asyncio")
    server = _Uvicorn(config)
    serve_task = asyncio.create_task(server.serve())
    try:
        for _ in range(80):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        sidecar_port = server.servers[0].sockets[0].getsockname()[1]
        payload = {
            "session_id": session_id,
            "workspace_id": "ws-abort-idle-tcp",
            "intent": "coach",
            "message": "Hang until the client aborts.",
            "response_language": "en-US",
            "use_agent_loop": False,
            "stream_id": "tcp-abort-idle",
        }
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{sidecar_port}", timeout=10.0) as client:
            turn_task = asyncio.create_task(client.post("/turn", json=payload))
            await asyncio.wait_for(accepted.wait(), timeout=5.0)
            await asyncio.sleep(0.3)
            turn_task.cancel()
            await asyncio.gather(turn_task, return_exceptions=True)
            await asyncio.wait_for(peer_eof.wait(), timeout=4.0)
        assert peer_eof.is_set()
    finally:
        server.should_exit = True
        await asyncio.gather(serve_task, return_exceptions=True)
        hang_server.close()
        await hang_server.wait_closed()
