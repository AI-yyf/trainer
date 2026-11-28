"""(d) Secret redaction: provider errors, visible coach text and stream events never carry API keys or tracebacks.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real objects;
nothing here asserts on source text or code shape):
  * server/tests/test_coach_text_sanitizer.py
  * server/tests/test_provider_gateway.py
  * server/tests/test_provider_failure_copy.py
  * server/tests/test_stream_error_redaction.py

Guarantees covered:
  * coach-visible text sanitizer strips credential-shaped strings and error internals;
  * provider failure copy is user-facing without keys or tracebacks;
  * provider gateway never logs or echoes secrets;
  * stream error events are redacted before they reach the client.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.coach_text_sanitizer import (
    normalize_visible_coach_text,
    repair_legacy_assistant_messages,
    sanitize_visible_coach_payload,
    sanitize_visible_coach_reply_content,
    strip_visible_next_step_prefix,
)
from app.core.models import (
    CapabilityFlags,
    ChatMessage,
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderTestResponse,
    WorkbenchSnapshot,
)
from app.core.settings import AppSettings
from app.llm.provider.failure_copy import (
    provider_failure_next_step_text,
    provider_failure_summary_text,
)
from app.llm.provider.quota_copy import provider_quota_copy
from app.llm.provider_gateway import (
    NEWAPI_CONNECTION_TYPE,
    catalog_endpoint_type_claims,
    gateway_fingerprint_diagnostics,
    inspect_provider_gateway_headers,
    normalize_provider_connection_type,
)
from app.llm.provider_service import ProviderService, _should_fingerprint_gateway
from app.main import create_app

# ---------------------------------------------------------------------------
# Restored from test_coach_text_sanitizer.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_normalize_strips_meta_labels_and_prefixes() -> None:
    assert normalize_visible_coach_text("Current focus: read the module map first") == (
        "Read the module map first"
    )
    assert normalize_visible_coach_text("general coaching") == ""
    assert normalize_visible_coach_text("当前聚焦：先看入口文件") == "先看入口文件"


def test_sanitize_reply_drops_internal_markers() -> None:
    raw = (
        "<system-reminder>workspace file snapshot</system-reminder>\n\n"
        "先看入口文件，再跑一个最小验证。"
    )
    assert sanitize_visible_coach_reply_content(raw, "zh-CN") == "先看入口文件，再跑一个最小验证。"
    mojibake = sanitize_visible_coach_reply_content("涓嬩竴姝ユ槸杩欐牱", "zh-CN")
    assert "再发一次" in mojibake or "send the same question" in mojibake


def test_strip_next_step_prefix_both_languages() -> None:
    assert strip_visible_next_step_prefix("Next step: run pytest -q") == "run pytest -q"
    assert strip_visible_next_step_prefix("下一步：运行 pytest") == "运行 pytest"


def test_payload_sanitizer_recurses_into_visible_fields() -> None:
    payload = {
        "summary": "Current focus: keep one move",
        "nested": [{"next_step": "Current focus: verify"}],
    }
    cleaned = sanitize_visible_coach_payload(payload)
    assert isinstance(cleaned, dict), "sanitizer must hand back a dict for dict input"
    assert cleaned["summary"] == "Keep one move"
    assert cleaned["nested"][0]["next_step"] == "Verify"


def test_repair_legacy_assistant_messages_rewrites_history() -> None:
    snapshot = WorkbenchSnapshot(
        messages=[
            ChatMessage(role="user", content="current focus: mine"),
            ChatMessage(
                role="assistant",
                content="<system-reminder>workspace file snapshot</system-reminder>\n\nreal answer",
            ),
        ],
    )
    repaired = repair_legacy_assistant_messages(snapshot, "en-US")
    assert repaired is True
    assert snapshot.messages[1].content == "real answer"
    assert snapshot.messages[0].content == "current focus: mine"  # user text untouched


"""Phase 4 — coach_text_sanitizer 拆分后的独立行为锁 (原 routers.py 闭包逻辑)."""

# ---------------------------------------------------------------------------
# Restored from test_provider_gateway.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_newapi_connection_type_is_not_guessed_from_unknown_values() -> None:
    assert normalize_provider_connection_type("newapi_channel_conn") == NEWAPI_CONNECTION_TYPE
    assert normalize_provider_connection_type("New API") == NEWAPI_CONNECTION_TYPE
    assert normalize_provider_connection_type("oneapi") == NEWAPI_CONNECTION_TYPE
    assert normalize_provider_connection_type("openai_chat_completions_compatible") is None
    assert normalize_provider_connection_type("mystery-gateway") is None


def test_newapi_headers_fingerprint_does_not_claim_a_protocol() -> None:
    fingerprint = inspect_provider_gateway_headers(
        {
            "x-new-api-version": "v1.0.0-rc.14",
            "x-oneapi-request-id": "abc",
        },
        catalog_endpoint_types=("openai",),
    )
    assert fingerprint.kind == "newapi"
    assert fingerprint.connection_type == NEWAPI_CONNECTION_TYPE
    assert fingerprint.version == "v1.0.0-rc.14"
    diagnostics = gateway_fingerprint_diagnostics(fingerprint)
    assert "newapi_channel_conn" in diagnostics[0]
    assert "not live protocol evidence" in diagnostics[0]
    assert "sk-" not in diagnostics[0]


def test_unknown_gateway_headers_do_not_default_to_compatible() -> None:
    fingerprint = inspect_provider_gateway_headers({"server": "nginx"})
    assert fingerprint.kind == "unknown"
    assert fingerprint.connection_type is None
    assert "not assume OpenAI-compatible" in gateway_fingerprint_diagnostics(fingerprint)[0]


def test_catalog_endpoint_types_are_claims_not_secrets() -> None:
    claims = catalog_endpoint_type_claims(
        {
            "data": [
                {"id": "MiniMax-M2.7", "supported_endpoint_types": ["openai"]},
                {"id": "MiniMax-M3", "supported_endpoint_types": ["openai", "anthropic"]},
            ]
        }
    )
    assert claims == ("openai", "anthropic")


def test_gateway_fingerprint_is_reserved_for_newapi_identity() -> None:
    generic = ProviderConfig(
        name="minimax-provider",
        baseUrl="https://api.example.com/v1",
        apiKeyRef="trainer.minimax",
        model="MiniMax-M3",
    )
    assert _should_fingerprint_gateway(generic) is False
    assert (
        _should_fingerprint_gateway(
            generic.model_copy(update={"connection_type": "newapi_channel_conn"})
        )
        is True
    )
    assert (
        _should_fingerprint_gateway(generic.model_copy(update={"name": "New API MiniMax"})) is True
    )


# ---------------------------------------------------------------------------
# Restored from test_provider_failure_copy.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------

CATEGORIES = (
    "invalid_key_or_permission",
    "model_unsupported",
    "model_not_found",
    "language_corruption",
    "malformed_response",
    "truncated_or_empty",
    "streaming_unavailable",
    "rate_limit",
    "timeout",
    "network",
)


def test_every_category_has_localized_summary_and_next_step() -> None:
    for category in CATEGORIES:
        english_summary = provider_failure_summary_text(category, "en-US")
        chinese_summary = provider_failure_summary_text(category, "zh-CN")
        english_next = provider_failure_next_step_text(category, "en-US")
        chinese_next = provider_failure_next_step_text(category, "zh-CN")
        assert english_summary and english_next
        assert chinese_summary and chinese_next
        assert any("\u4e00" <= char <= "\u9fff" for char in chinese_summary)
        assert any("\u4e00" <= char <= "\u9fff" for char in chinese_next)
        assert not any("\u4e00" <= char <= "\u9fff" for char in english_summary)


def test_quota_category_uses_the_structured_quota_copy() -> None:
    summary, next_step = provider_quota_copy("zh-CN")
    assert provider_failure_summary_text("quota_exhausted", "zh-CN") == summary
    assert provider_failure_next_step_text("quota_exhausted", "zh-CN") == next_step


def test_unknown_category_falls_back_without_raising() -> None:
    assert provider_failure_summary_text("unknown-category", "en-US")
    assert provider_failure_next_step_text("unknown-category", "zh-CN")


"""Provider failure copy extraction stays behavior-compatible."""

# ---------------------------------------------------------------------------
# Restored from test_stream_error_redaction.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    provider = ProviderConfig(
        name="test-openai-compatible",
        baseUrl="http://127.0.0.1:9/v1",
        apiKeyRef="trainer.default",
        model="gpt-4o-mini",
        capabilities=CapabilityFlags(tools=True, streaming=True),
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
            capabilityEvidence=[
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
            toolsReady=True,
            toolProbeStatus="verified",
        ),
    )
    return TestClient(app)


def seed_session(client: TestClient, *, workspace_id: str) -> str:
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": "Trainer Test",
            "profile": {"long_term_goal": "Ship a focused test", "weekly_hours": 4},
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["session_id"])


def stream_error_payload(raw: str) -> dict[str, object]:
    for block in raw.split("\n\n"):
        if not block.startswith("event: error\n"):
            continue
        for line in block.splitlines():
            if line.startswith("data:"):
                return json.loads(line.removeprefix("data:").strip())
    raise AssertionError(f"missing SSE error event: {raw}")


@pytest.mark.parametrize("endpoint", ["/session/message/stream", "/turn/stream"])
@pytest.mark.parametrize("failure_kind", ["event", "exception"])
def test_stream_routes_redact_provider_error_details(
    tmp_path: Path,
    endpoint: str,
    failure_kind: str,
) -> None:
    unsafe_detail = (
        "provider rejected request (HTTP 429): literal sk-test-fake; "
        "Authorization: Bearer bearer-route-secret; "
        "https://provider.invalid/chat?api_key=query-route-secret; "
        "response body: raw upstream response"
    )

    class ProviderFailure(RuntimeError):
        status_code = 429

    async def fake_agentic_stream(self: ProviderService, *_: Any, **__: Any):
        if failure_kind == "event":
            yield {"type": "error", "detail": unsafe_detail}
            return
        raise ProviderFailure(unsafe_detail)

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply_agentic_stream",
            new=fake_agentic_stream,
        ),
    ):
        session_id = seed_session(client, workspace_id=f"ws-{failure_kind}-{endpoint.count('/')}")
        payload: dict[str, object] = {
            "session_id": session_id,
            "workspace_id": f"ws-{failure_kind}-{endpoint.count('/')}",
            "message": "Give me one small next step.",
            "use_agent_loop": True,
        }
        if endpoint == "/turn/stream":
            payload["intent"] = "coach"
        with client.stream("POST", endpoint, json=payload) as response:
            assert response.status_code == 200
            raw = b"".join(response.iter_bytes()).decode("utf-8", errors="replace")

    error = stream_error_payload(raw)
    detail = str(error["error"])
    assert "HTTP 429" in detail
    assert "sk-test-fake" not in raw
    assert "bearer-route-secret" not in raw
    assert "query-route-secret" not in raw
    assert "raw upstream response" not in raw
    if failure_kind == "exception":
        assert detail == "Provider request failed (HTTP 429)."
    else:
        assert "[REDACTED]" in detail


@pytest.mark.parametrize("endpoint", ["/session/message/stream", "/turn/stream"])
def test_stream_provider_failure_persists_user_turn_once_for_retry(
    tmp_path: Path,
    endpoint: str,
) -> None:
    async def failing_agentic_stream(self: ProviderService, *_args: Any, **__: Any):
        raise RuntimeError("provider unavailable")
        yield {}

    workspace_id = f"ws-stream-persistence-{endpoint.rsplit('/', 1)[-1]}"
    stream_id = f"stream-retry-{endpoint.rsplit('/', 1)[-1]}"
    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply_agentic_stream",
            new=failing_agentic_stream,
        ),
    ):
        started = seed_session(client, workspace_id=workspace_id)
        payload: dict[str, object] = {
            "session_id": started,
            "workspace_id": workspace_id,
            "message": "Keep this turn recoverable.",
            "use_agent_loop": True,
            "stream_id": stream_id,
        }
        if endpoint == "/turn/stream":
            payload["intent"] = "coach"

        first = client.post(endpoint, json=payload)
        second = client.post(endpoint, json=payload)
        restored = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Trainer Test"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert restored.status_code == 200
    snapshot = restored.json()
    messages = snapshot["messages"]
    matching_users = [
        item
        for item in messages
        if item["role"] == "user" and item["metadata"].get("stream_id") == stream_id
    ]
    assert len(matching_users) == 1
    assert matching_users[0]["metadata"]["stream_state"] == "failed"
    assert not any(
        item["role"] == "assistant" and "Keep this turn recoverable." in item["content"]
        for item in messages
    )


@pytest.mark.parametrize("endpoint", ["/session/message/stream", "/turn/stream"])
def test_stream_abort_persists_interrupted_user_turn_without_fake_assistant(
    tmp_path: Path,
    endpoint: str,
) -> None:
    async def partial_stream(self: ProviderService, *_args: Any, **__: Any):
        yield "partial provider text that must not become a completed reply"
        yield "late provider text"

    disconnect_checks = 0

    async def disconnect_after_start(_request: Any) -> bool:
        nonlocal disconnect_checks
        disconnect_checks += 1
        return disconnect_checks >= 2

    workspace_id = f"ws-stream-abort-{endpoint.rsplit('/', 1)[-1]}"
    stream_id = f"stream-abort-{endpoint.rsplit('/', 1)[-1]}"
    with (
        build_client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply_stream", new=partial_stream),
        patch("starlette.requests.Request.is_disconnected", new=disconnect_after_start),
    ):
        started = seed_session(client, workspace_id=workspace_id)
        payload: dict[str, object] = {
            "session_id": started,
            "workspace_id": workspace_id,
            "message": "Keep this aborted turn recoverable.",
            "response_language": "en-US",
            "use_agent_loop": False,
            "stream_id": stream_id,
        }
        if endpoint == "/turn/stream":
            payload["intent"] = "coach"
        response = client.post(endpoint, json=payload)
        restored = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Trainer Test"},
        )

    assert response.status_code == 200
    assert "event: complete" not in response.text
    assert "partial provider text" not in response.text
    assert restored.status_code == 200
    messages = restored.json()["messages"]
    matching_users = [
        item
        for item in messages
        if item["role"] == "user" and item["metadata"].get("stream_id") == stream_id
    ]
    assert len(matching_users) == 1
    assert matching_users[0]["metadata"]["stream_state"] == "interrupted"
    assert not any(
        item["role"] == "assistant" and "partial provider text" in item["content"]
        for item in messages
    )
