"""Run the authored experience matrix through the real FastAPI sidecar.

The provider is a local scripted OpenAI-compatible HTTP server. That keeps
this suite deterministic and credential-free while proving the route,
ProviderService request, visible reply, and persisted session path. It does
not claim to validate a live model, VS Code host, or browser rendering.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from provider_fixtures import seed_verified_capabilities

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
MATRIX_EXPORT = ROOT / "e2e" / "export-trainer-experience-matrix.cjs"
MATRIX_MARKER = re.compile(r"\bmatrixCase(?P<scenario>[A-Z]\d+)\b")
MOJIBAKE_FRAGMENTS = ("涓嬩", "鍒€", "锟", "\ufffd")
SIDECAR_EVIDENCE = {
    "primary_layer": "FastAPI sidecar + scripted OpenAI-compatible provider",
    "real_sidecar": True,
    "live_model": False,
    "vsix_host": False,
    "limitation": (
        "The provider is scripted. This layer proves the sidecar contract and session persistence, "
        "not live-model quality, VS Code extension hosting, or browser rendering."
    ),
}


def _load_authored_scenarios() -> tuple[dict[str, Any], ...]:
    node = shutil.which("node")
    if node is None:
        pytest.fail("The real sidecar experience matrix needs Node.js to load the authored 200 scenarios.")
    result = subprocess.run(
        [node, str(MATRIX_EXPORT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        encoding="utf-8",
        timeout=20,
    )
    if result.returncode:
        pytest.fail(f"Could not load the authored experience matrix: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, list) or len(payload) != 200:
        pytest.fail("The authored experience matrix must export exactly 200 scenarios.")
    scenarios = tuple(item for item in payload if isinstance(item, dict))
    if len(scenarios) != 200 or len({item.get("id") for item in scenarios}) != 200:
        pytest.fail("The authored experience matrix has invalid scenario identifiers.")
    return scenarios


SCENARIOS = _load_authored_scenarios()


def _last_user_content(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


class ScriptedOpenAIProvider:
    """A tiny local OpenAI-compatible server used only by this test module."""

    def __init__(self) -> None:
        self._requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def requests_for(self, marker: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                request
                for request in self._requests
                if marker in _last_user_content(request)
            ]

    def _remember(self, request: dict[str, Any]) -> None:
        with self._lock:
            self._requests.append(request)

    @staticmethod
    def _reply_for(request: dict[str, Any]) -> str:
        user_content = _last_user_content(request)
        if user_content.startswith("Repeat exactly: "):
            return user_content.removeprefix("Repeat exactly: ")
        if "只回复最后四个汉字" in user_content:
            return "验证动作"
        if "只用简体中文回答一句话" in user_content:
            return "先学再测，再用 VS Code 检查一个可观察的结果。"
        if "只返回一个可见中文短句：provider ready。" in user_content:
            return "provider ready。"
        if "请只输出可见文字：provider ready。" in user_content:
            return "provider ready。"
        if "Reply with exactly: pong" in user_content:
            return "pong"
        if "Please only output visible text: provider ready." in user_content:
            return "provider ready"

        marker = MATRIX_MARKER.search(user_content)
        if marker is None:
            return "Next: check one observable result before widening the task."
        if "languagezhCN" in user_content:
            return (
                "我会只围绕当前小目标继续，先确认一个可观察到的事实，不扩大范围。"
                "下一步：检查一个可观察到的结果。"
            )
        return (
            "I will stay with currentMicroGoal and keep the next move small. "
            "Next: check one observable result."
        )

    @contextmanager
    def running(self) -> Iterator[str]:
        harness = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
                length = int(self.headers.get("content-length", "0"))
                try:
                    request = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    request = {}
                if not isinstance(request, dict):
                    request = {}
                harness._remember(request)
                if self.path.rstrip("/") != "/v1/chat/completions":
                    self.send_error(404, "Only OpenAI chat completions are available in this fixture.")
                    return
                reply = harness._reply_for(request)
                body = json.dumps(
                    {
                        "id": "chatcmpl-trainer-matrix",
                        "object": "chat.completion",
                        "created": 0,
                        "model": "trainer-matrix-model",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": reply},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json; charset=utf-8")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
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


@pytest.fixture(scope="module")
def sidecar_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[TestClient, ScriptedOpenAIProvider]]:
    provider_harness = ScriptedOpenAIProvider()
    with provider_harness.running() as provider_url:
        settings = AppSettings(
            app_name="Trainer Real Sidecar Experience Matrix",
            host="127.0.0.1",
            port=8765,
            data_dir=tmp_path_factory.mktemp("real-sidecar-experience-matrix"),
            database_name="trainer-experience-matrix.db",
            default_session_stage="intake",
            summary_message_limit=6,
            enable_network_fetch=False,
        )
        app = create_app(settings)
        provider = ProviderConfig(
            name="scripted-openai-compatible-matrix-provider",
            base_url=provider_url,
            api_key_ref="trainer.matrix",
            model="trainer-matrix-model",
            protocol="openai_chat_completions_compatible",
            capabilities={
                "chat": True,
                "responses": False,
                "vision": False,
                "embeddings": False,
                "tools": False,
                "json_schema": False,
                "streaming": True,
            },
        )
        runtime = app.state.runtime
        runtime.provider_config = provider
        runtime.provider_api_key = "matrix-local-key"
        runtime.provider_service = ProviderService(config=provider, api_key="matrix-local-key")
        runtime.provider_service_cache.clear()
        # Record explicit observed capability evidence so /session/message treats the
        # scripted provider as a verified connection. Without this the unconfigured
        # provider gate short-circuits the request before it reaches ProviderService.
        seed_verified_capabilities(runtime, provider, "matrix-local-key")
        # Avoid a machine-level proxy intercepting a loopback-only test server.
        direct_transport = httpx.AsyncClient(trust_env=False)
        direct_client = AsyncOpenAI(
            api_key="matrix-local-key",
            base_url=provider_url,
            http_client=direct_transport,
        )
        runtime.provider_service._client = direct_client  # noqa: SLF001 - fixture transport only
        try:
            with TestClient(app) as client:
                # Sanity check this fixture actually threads the live provider path:
                # the matrix's own assertions depend on it.
                assert runtime.provider_connection_verified(runtime.provider_service)
                yield client, provider_harness
        finally:
            asyncio.run(direct_client.close())


def _authored_message(scenario: dict[str, Any]) -> str:
    action = scenario.get("userAction")
    action_input = action.get("input") if isinstance(action, dict) else None
    source = str(action_input or scenario.get("userGoal") or "Keep the current goal in focus.").strip()
    anchor = "当前小目标" if scenario["language"] == "zh-CN" else "currentMicroGoal"
    return "\n\n".join(
        [
            source,
            "Please keep this as a small coaching step. Do not change any formal plan or claim mastery.",
            f"Keep `{anchor}` visible in the reply.",
            f"Matrix test context matrixCase{scenario['id']} language{scenario['language'].replace('-', '')}.",
        ]
    )


def _expected_reply_prefix(scenario: dict[str, Any]) -> str:
    if scenario["language"] == "zh-CN":
        return "我会只围绕当前小目标继续"
    return "I will stay with currentMicroGoal"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: str(scenario["id"]))
def test_authored_journey_crosses_fastapi_sidecar_and_persists_context(
    sidecar_client: tuple[TestClient, ScriptedOpenAIProvider],
    scenario: dict[str, Any],
) -> None:
    client, provider_harness = sidecar_client
    workspace_id = f"real-sidecar-matrix-{str(scenario['id']).lower()}"
    response_language = str(scenario["language"])
    message = _authored_message(scenario)
    marker = f"matrixCase{scenario['id']}"

    started = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": f"Experience matrix {scenario['id']}",
            "profile": {
                "long_term_goal": str(scenario["userGoal"]),
                "weekly_hours": 4,
                "teaching_style": "guided",
                "answer_policy": "direct",
            },
        },
    )
    assert started.status_code == 200, started.text
    session_id = str(started.json()["session_id"])
    # Dedicated provider health tests cover probes. This matrix focuses on the
    # authored request itself, which still travels through ProviderService.
    client.app.state.runtime.provider_service.mark_language_integrity_success(
        message=message,
        response_language=response_language,
    )

    replied = client.post(
        "/session/message",
        json={
            "session_id": session_id,
            "workspace_id": workspace_id,
            "message": message,
            "active_view": scenario["view"],
            "response_language": response_language,
            "answer_mode": "direct",
            "use_agent_loop": False,
        },
    )
    assert replied.status_code == 200, replied.text
    payload = replied.json()
    visible_reply = str(payload["reply"]["content"])

    provider_requests = provider_harness.requests_for(marker)
    assert provider_requests, f"{scenario['id']} did not reach the scripted OpenAI-compatible provider."
    assert any(marker in _last_user_content(request) for request in provider_requests)
    assert _expected_reply_prefix(scenario) in visible_reply
    assert ("下一步：" if response_language == "zh-CN" else "Next:") in visible_reply
    assert all(fragment not in visible_reply for fragment in MOJIBAKE_FRAGMENTS)

    service = client.app.state.runtime.provider_service
    assert service.detect_language_corruption(
        message=message,
        reply=visible_reply,
        response_language=response_language,
    ) is False

    client.app.state.runtime.sessions.pop(session_id, None)
    restored = client.get(
        "/session/history",
        params={"session_id": session_id, "workspace_id": workspace_id},
    )
    assert restored.status_code == 200, restored.text
    history = restored.json()
    assert history and history[0]["latest_user_message"] == message
    assert _expected_reply_prefix(scenario) in str(history[0]["latest_assistant_message"])
    assert session_id in client.app.state.runtime.sessions
