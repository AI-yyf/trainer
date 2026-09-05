"""Regression coverage for local providers in proxy-configured environments."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import pytest

from app.core.models import ProviderConfig, UserProfile
from app.llm.provider_service import ProviderService


@contextmanager
def loopback_provider() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path != "/v1/models":
                self.send_error(404)
                return
            self._send_json({"object": "list", "data": [{"id": "loopback-model"}]})

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            self._read_json()
            self._send_json(
                {
                    "id": "loopback-completion",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "loopback-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": (
                                    "Set one breakpoint, run the function, and inspect one value."
                                ),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            )

        def _read_json(self) -> dict[str, object]:
            length = int(self.headers.get("content-length", "0"))
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}
            return value if isinstance(value, dict) else {}

        def _send_json(self, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *_args: object) -> None:
            del format
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _provider(base_url: str) -> ProviderConfig:
    return ProviderConfig(
        name="loopback-provider",
        baseUrl=base_url,
        apiKeyRef="trainer.loopback",
        model="loopback-model",
        protocol="openai_chat_completions_compatible",
    )


def _force_unusable_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)


def test_loopback_model_listing_bypasses_ambient_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_unusable_proxy(monkeypatch)
    with loopback_provider() as base_url:
        response = ProviderService().list_models(_provider(base_url), "test-key")

    assert response.ok is True
    assert response.available_models == ["loopback-model"]


@pytest.mark.asyncio
async def test_loopback_chat_bypasses_ambient_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_unusable_proxy(monkeypatch)
    with loopback_provider() as base_url:
        service = ProviderService(config=_provider(base_url), api_key="test-key")
        try:
            reply = await service.coaching_reply(
                UserProfile(long_term_goal="Learn debugging", weekly_hours=2),
                "Give me one small observable debugging step.",
            )
        finally:
            if service._client is not None:  # noqa: SLF001 - releases the test transport.
                await service._client.close()  # noqa: SLF001 - releases the test transport.

    assert "breakpoint" in reply
    assert service.peek_last_reply_failure() is None
