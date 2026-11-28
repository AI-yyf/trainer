"""(k) Provider protocol truth: token limits, quotas, schemes, capability evidence and
    failure categories are derived from real probes, never from declarations.

Guarantees covered:
  * token limits, quotas and reasoning budgets are enforced from resolved model limits;
  * scheme-less and loopback base URLs resolve and bypass the ambient proxy without leaking it;
  * capability truth survives sidecar restarts and is only granted by observed probes;
  * an unconfigured provider is refused with honest copy instead of a fabricated reply;
  * reasoning-leak and vision failures are categorized from real provider responses.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_reasoning_error_category.py
  * server/tests/test_provider_scheme_resolution.py
  * server/tests/test_provider_quota.py
  * server/tests/test_provider_test_route_probe.py
  * server/tests/test_provider_capability_persistence.py
  * server/tests/test_vision_challenge.py
  * server/tests/test_provider_recovery_and_stream_close.py
  * server/tests/test_vision_cache_upgrade.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import fitz
import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from openai import APIStatusError

from app.api import router_support as routers
from app.api.router_support import looks_like_schemeless_provider_host, resolve_provider_url_scheme
from app.api.runtime import _provider_capability_cache_key
from app.core.models import (
    CapabilityFlags,
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderModelsResponse,
    ProviderTestResponse,
    UserProfile,
)
from app.core.settings import AppSettings
from app.llm.agent_binding import _iterate_and_close_provider_stream
from app.llm.agent_loop import AgentProvider
from app.llm.provider import streaming
from app.llm.provider.assessment import _usage_output_tokens
from app.llm.provider.errors import provider_http_failure, provider_quota_exhausted
from app.llm.provider.quota_copy import provider_quota_reply
from app.llm.provider_service import (
    ProviderService,
    _reasoning_budget_exhausted,
    _unusable_visible_reply_category,
)
from app.llm.vision_challenge import VISION_PROBE_VERSION, build_vision_challenge
from app.main import create_app
from tests.client_fixtures import build_client
from tests.test_runtime_provider_cache import _make_runtime

# ---------------------------------------------------------------------------
# Restored from test_reasoning_error_category.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _config() -> ProviderConfig:
    return ProviderConfig(
        name="test-provider",
        baseUrl="https://api.openai.com/v1",
        apiKeyRef="trainer.test",
        model="gpt-4o-mini",
    )


class TestUnusableVisibleReplyCategory(unittest.TestCase):
    """Three outcomes: budget exhausted, reasoning only, plain empty."""

    def test_no_hidden_reasoning_is_empty_response(self) -> None:
        self.assertEqual(
            _unusable_visible_reply_category(hidden_reasoning_observed=False),
            "empty_response",
        )

    def test_hidden_reasoning_without_budget_exhaustion_keeps_reasoning_leak(self) -> None:
        self.assertEqual(
            _unusable_visible_reply_category(hidden_reasoning_observed=True),
            "reasoning_leak",
        )

    def test_hidden_reasoning_with_budget_exhaustion_is_budget_exhausted(self) -> None:
        self.assertEqual(
            _unusable_visible_reply_category(
                hidden_reasoning_observed=True,
                reasoning_budget_exhausted=True,
            ),
            "reasoning_budget_exhausted",
        )

    def test_budget_exhaustion_alone_does_not_claim_a_reasoning_category(self) -> None:
        self.assertEqual(
            _unusable_visible_reply_category(
                hidden_reasoning_observed=False,
                reasoning_budget_exhausted=True,
            ),
            "empty_response",
        )


class TestReasoningBudgetExhaustedSignal(unittest.TestCase):
    """Conservative usage-based exhaustion signal."""

    def test_completion_tokens_at_budget_is_exhausted(self) -> None:
        response = SimpleNamespace(usage=SimpleNamespace(completion_tokens=96))
        self.assertTrue(
            _reasoning_budget_exhausted(response, max_tokens=96),
        )

    def test_completion_tokens_below_budget_is_not_exhausted(self) -> None:
        response = SimpleNamespace(usage=SimpleNamespace(completion_tokens=40))
        self.assertFalse(
            _reasoning_budget_exhausted(response, max_tokens=96),
        )

    def test_missing_usage_defaults_to_false(self) -> None:
        self.assertFalse(_reasoning_budget_exhausted(SimpleNamespace(), max_tokens=96))
        self.assertFalse(_reasoning_budget_exhausted(None, max_tokens=96))
        self.assertFalse(_reasoning_budget_exhausted(SimpleNamespace(usage=None), max_tokens=96))

    def test_missing_budget_defaults_to_false(self) -> None:
        response = SimpleNamespace(usage=SimpleNamespace(completion_tokens=96))
        self.assertFalse(_reasoning_budget_exhausted(response, max_tokens=None))
        self.assertFalse(_reasoning_budget_exhausted(response, max_tokens=0))

    def test_output_tokens_field_is_supported(self) -> None:
        response = SimpleNamespace(usage=SimpleNamespace(output_tokens=32))
        self.assertTrue(_reasoning_budget_exhausted(response, max_tokens=32))

    def test_usage_from_payload_dict_is_supported(self) -> None:
        response = {"usage": {"completion_tokens": 128}}
        self.assertTrue(_reasoning_budget_exhausted(response, max_tokens=128))
        self.assertEqual(_usage_output_tokens(response), 128)


class TestBudgetExhaustedDetail(unittest.TestCase):
    """The new category yields actionable localized detail text."""

    def test_detail_is_actionable_english(self) -> None:
        detail = ProviderService()._detail_from_category(
            "reasoning_budget_exhausted",
            provider=_config(),
        )
        lowered = detail.lower()
        self.assertIn("provider is reachable", lowered)
        self.assertIn("hidden reasoning", lowered)
        self.assertIn("output budget", lowered)
        self.assertIn("retry", lowered)
        self.assertIn("non-reasoning model", lowered)

    def test_detail_localizes_to_chinese(self) -> None:
        detail = ProviderService()._detail_from_category(
            "reasoning_budget_exhausted",
            provider=_config(),
            response_language="zh-CN",
        )
        self.assertIn("provider 已连通", detail)
        self.assertIn("隐藏思考", detail)
        self.assertIn("非思考", detail)

    def test_detail_appends_safe_error_detail(self) -> None:
        from app.llm.provider_service import ProviderRuntimeResponseError

        detail = ProviderService()._detail_from_category(
            "reasoning_budget_exhausted",
            provider=_config(),
            error=ProviderRuntimeResponseError(
                category="reasoning_budget_exhausted",
                detail="the model burned the whole budget",
                retryable=True,
            ),
        )
        self.assertIn("the model burned the whole budget", detail)


# ---------------------------------------------------------------------------
# Restored from test_provider_scheme_resolution.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_local_hosts_short_circuit_to_http() -> None:
    assert resolve_provider_url_scheme("localhost:8765") == "http"
    assert resolve_provider_url_scheme("127.0.0.1:8099/v1") == "http"
    assert resolve_provider_url_scheme("192.168.1.10:11434") == "http"
    assert resolve_provider_url_scheme("nas.local:1234") == "http"
    assert resolve_provider_url_scheme("host.docker.internal:11434") == "http"


def test_looks_like_schemeless_provider_host_matches_service_addresses() -> None:
    assert looks_like_schemeless_provider_host("minimax.relay.example.test")
    assert looks_like_schemeless_provider_host("api.deepseek.com/v1")
    assert looks_like_schemeless_provider_host("localhost:1234/v1")
    assert looks_like_schemeless_provider_host("ollama:11434")
    assert not looks_like_schemeless_provider_host("https://api.deepseek.com/v1")
    assert not looks_like_schemeless_provider_host("ftp://example.com")
    assert not looks_like_schemeless_provider_host("not a host")


def test_public_host_probed_for_tls_before_http() -> None:
    with patch.object(
        routers,
        "_probe_provider_url_scheme",
        side_effect=lambda host, port: "https" if port == 443 else None,
    ) as probe:
        assert resolve_provider_url_scheme("tls-only.example.com") == "https"
    assert probe.call_args_list[0].args == ("tls-only.example.com", 443)


def test_http_only_relay_falls_back_after_closed_tls_port() -> None:
    # Port 443 unreachable, port 80 answers in plain HTTP: the relay must
    # resolve to http instead of failing later with an opaque request error.
    with patch.object(
        routers,
        "_probe_provider_url_scheme",
        side_effect=lambda host, port: None if port == 443 else "http",
    ) as probe:
        assert resolve_provider_url_scheme("http-only.example.com") == "http"
    assert [call.args[1] for call in probe.call_args_list] == [443, 80]


def test_unreachable_public_host_defaults_to_https() -> None:
    with patch.object(routers, "_probe_provider_url_scheme", return_value=None):
        assert resolve_provider_url_scheme("offline.example.com") == "https"


def test_scheme_resolution_is_memoized_per_host() -> None:
    with patch.object(
        routers,
        "_probe_provider_url_scheme",
        side_effect=lambda host, port: "http" if port == 80 else None,
    ) as probe:
        assert resolve_provider_url_scheme("cached.example.com") == "http"
        assert resolve_provider_url_scheme("cached.example.com") == "http"
        assert resolve_provider_url_scheme("cached.example.com/v1") == "http"
    assert probe.call_count == 2


def test_explicit_non_default_port_is_probed_directly() -> None:
    with patch.object(
        routers,
        "_probe_provider_url_scheme",
        side_effect=lambda host, port: "https" if port == 8443 else None,
    ) as probe:
        assert resolve_provider_url_scheme("gateway.example.com:8443") == "https"
    assert probe.call_args_list[0].args == ("gateway.example.com", 8443)


def test_provider_test_route_resolves_schemeless_local_base_url(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_test(
        self: ProviderService,
        provider: ProviderConfig,
        api_key: str | None,
        **_: object,
    ) -> ProviderTestResponse:
        captured["base_url"] = provider.base_url
        return ProviderTestResponse(ok=True, detail="connected", diagnostics=["mocked"])

    settings = AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    app = create_app(settings)
    with patch.object(ProviderService, "test", fake_test):
        with TestClient(app) as client:
            response = client.post(
                "/provider/test",
                json={
                    "apiKey": "sk-test",
                    "provider": {
                        "name": "Relay",
                        "baseUrl": "127.0.0.1:8099/v1",
                        "model": "test-model",
                        "protocol": "openai_chat_completions_compatible",
                    },
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reachable"] is True
    assert captured["base_url"] == "http://127.0.0.1:8099/v1"
    assert payload["base_url"] == "http://127.0.0.1:8099/v1"


def test_turn_stream_rejects_blank_coach_message(tmp_path: Path) -> None:
    """A blank coach message would burn a live model call; it must 422."""
    settings = AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/turn/stream",
            json={"message": "   ", "workspace_id": "ws-blank", "session_id": "s-blank"},
        )

    assert response.status_code == 422
    assert "message" in response.text.lower() or "消息" in response.text


# ---------------------------------------------------------------------------
# Restored from test_provider_quota.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


class UpstreamError(Exception):
    def __init__(self, status: int, body: object) -> None:
        super().__init__(f"Provider request failed (HTTP {status}).")
        self.status_code = status
        self.body = body


@pytest.mark.parametrize("status,code,expected,retryable", [
    (403, "insufficient_user_quota", "quota_exhausted", False),
    (429, "insufficient_quota", "quota_exhausted", False),
    (402, "billing_hard_limit_reached", "quota_exhausted", False),
    (403, "invalid_api_key", "invalid_key_or_permission", False),
    (429, "rate_limit_exceeded", "rate_limit", True),
    (429, 2056, "quota_exhausted", False),
])
def test_billing_codes_override_status_without_reclassifying_auth_or_throttling(
    status: int, code: object, expected: str, retryable: bool,
) -> None:
    service = ProviderService()
    error = UpstreamError(status, {"error": {"code": code, "message": "PRIVATE API KEY"}})
    category, can_retry, observed_status, reachable, supported = service._classify_error(error)
    assert (category, can_retry, observed_status, reachable, supported) == (
        expected, retryable, status, True, None,
    )


def test_an_arbitrary_mention_of_quota_does_not_override_permission_error() -> None:
    error = UpstreamError(403, {"error": {"message": "quota: permission denied"}})
    assert ProviderService()._classify_error(error)[0] == "invalid_key_or_permission"


def test_httpx_error_preserves_billing_semantics_without_reading_a_live_stream() -> None:
    response = httpx.Response(403, json={"error": {"code": "insufficient_quota"}})
    error = httpx.HTTPStatusError("Forbidden", request=httpx.Request("POST", "https://example.test"), response=response)
    assert ProviderService()._classify_error(error)[:2] == ("quota_exhausted", False)
    live = httpx.Response(403, stream=httpx.ByteStream(b'{"error":{"code":"insufficient_quota"}}'))
    unread = httpx.HTTPStatusError("Forbidden", request=error.request, response=live)
    assert ProviderService()._classify_error(unread)[0] == "invalid_key_or_permission"
    assert live.is_stream_consumed is False


def test_native_non_json_error_keeps_existing_status_diagnosis() -> None:
    response = httpx.Response(403, text="PRIVATE HTML")
    error = provider_http_failure(response, detail="Native request failed (HTTP 403).")
    assert ProviderService()._classify_error(error)[0] == "invalid_key_or_permission"
    assert "PRIVATE" not in str(error)


@pytest.mark.parametrize("language", ["zh-CN", "en-US", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR"])
def test_coach_and_test_details_share_localized_quota_recovery(language: str) -> None:
    service = ProviderService(api_key="private-api-key")
    provider = ProviderConfig(name="quota", baseUrl="https://example.test", apiKeyRef="key", model="model")
    reply = service.provider_failure_reply("quota_exhausted", "private-api-key", language)
    assert reply == provider_quota_reply(language)
    assert reply == service._detail_from_category("quota_exhausted", provider=provider, response_language=language)
    assert "private-api-key" not in reply
    assert service.provider_failure_summary("quota_exhausted", language) in reply
    assert service.provider_failure_next_step("quota_exhausted", language) in reply
    if language != "en-US":
        assert reply != provider_quota_reply("en-US")


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("status,code,category,retryable", [
    (402, "insufficient_balance", "quota_exhausted", False),
    (403, "insufficient_user_quota", "quota_exhausted", False),
    (403, "invalid_api_key", "invalid_key_or_permission", False),
    (429, "rate_limit_exceeded", "rate_limit", True),
    (429, 2056, "quota_exhausted", False),
])
async def test_agent_transport_failure_survives_child_task_without_teaching_or_attestation(
    monkeypatch: pytest.MonkeyPatch,
    streaming: bool,
    status: int,
    code: str,
    category: str,
    retryable: bool,
) -> None:
    config = ProviderConfig(
        name="transport", baseUrl="https://example.test/v1", apiKeyRef="private",
        model="test-model", protocol="openai_chat_completions_compatible",
    )
    service = ProviderService(config, "private-secret-key")
    profile = UserProfile(
        long_term_goal="Understand code", background="Beginner", weekly_hours=4,
        teaching_style="guided", answer_policy="guided",
    )
    error = APIStatusError(
        "private-secret-key upstream private body",
        response=httpx.Response(status, request=httpx.Request("POST", config.base_url)),
        body={"error": {"code": code, "message": "private-secret-key"}},
    )

    async def call(*_args: object) -> dict[str, object]:
        raise error

    async def call_stream(*_args: object):
        if False:
            yield {}
        raise error

    def build(*_args: object, **_kwargs: object):
        return AgentProvider(config.protocol, call, call_stream), SimpleNamespace(_max_tokens=2048)

    async def forbidden_verification(**_kwargs: object):
        pytest.fail("An unavailable provider must not start verification or create evidence.")

    monkeypatch.setattr("app.llm.agent_binding.build_agent_provider_for", build)
    monkeypatch.setattr("app.llm.provider_service._maybe_auto_verify_practice_current_file", forbidden_verification)
    kwargs = {
        "profile": profile,
        "message": "请解释这个断言为何失败，下一步再验证代码。",
        "current_file": {"path": "lesson.py", "content": "assert False\n"},
        "response_language": "zh-CN",
        "coach_context": {"current_focus": "Old function contract lane"},
    }
    if streaming:
        events = [event async for event in service.coaching_reply_agentic_stream(**kwargs)]
        failure_frame = next(event for event in events if event["type"] == "error")
        assert failure_frame["category"] == category
        assert failure_frame["retryable"] is retryable
        assert failure_frame["terminal"] is False
        result = events[-1]
        assert result["type"] == "final"
    else:
        result = await service.coaching_reply_agentic(**kwargs)
    assert result["stop_reason"] == category
    assert result["fell_back"] is True
    assert result["retryable"] is retryable
    assert result["evidence"] == []
    assert "private-secret-key" not in str(result)
    assert "upstream private body" not in str(result)
    assert "lesson.py" not in result["next_step"]
    failure = service.consume_last_reply_failure()
    assert failure is not None
    assert failure["error_category"] == category
    assert failure["status_code"] == status
    assert "private-secret-key" not in str(failure)
    if category == "quota_exhausted":
        assert result["content"] == provider_quota_reply("zh-CN")
        assert "API key" not in result["content"]


def test_numeric_token_plan_limit_is_quota_not_generic_rate_limit() -> None:
    payload = {
        "error": {
            "code": 2056,
            "type": "rate_limit_error",
            "message": "已达到 Token Plan 用量上限",
        }
    }
    assert provider_quota_exhausted(payload) is True
    assert provider_quota_exhausted({"error": {"code": "2056"}}) is True
    assert provider_quota_exhausted({"error": {"code": "rate_limit_exceeded"}}) is False


# ---------------------------------------------------------------------------
# Restored from test_provider_test_route_probe.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


MOJIBAKE_MARKERS = (
    "\ufffd",
    "\ue000",
    "\ue1ec",
    "\u9227",
    "\u95b8",
    "\u9420",
    "\u5a11",
    "\u7f02",
    "\u934f",
    "\u6769",
)


def test_provider_test_route_forwards_probe_message_and_response_language(tmp_path: Path) -> None:
    provider_payload = {
        "name": "mini-max",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.minimax",
        "model": "MiniMax-M3",
    }

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "test",
            autospec=True,
            return_value=ProviderTestResponse(
                ok=True,
                detail="Provider reachable. Chat probe succeeded with model MiniMax-M3. Response: pong",
                provider_reachable=True,
                model_supported=True,
            ),
        ) as test_mock,
    ):
        response = client.post(
            "/provider/test",
            json={
                "provider": provider_payload,
                "api_key": "sk-test",
                "probe_message": (
                    "\u8bf7\u5148\u89e3\u91ca remote workspace boundary\uff0c"
                    "\u518d\u7ed9\u6211\u4e00\u4e2a tiny verification step ABC123\u3002"
                ),
                "response_language": "zh-CN",
            },
        )

    assert response.status_code == 200
    assert test_mock.call_args is not None
    assert test_mock.call_args.kwargs["probe_message"].startswith(
        "\u8bf7\u5148\u89e3\u91ca remote workspace boundary"
    )
    assert test_mock.call_args.kwargs["response_language"] == "zh-CN"


def test_provider_test_route_returns_observed_tool_capability_truth(tmp_path: Path) -> None:
    provider_payload = {
        "name": "tool-aware-provider",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.tool-aware",
        "model": "ToolModel",
        "capabilities": {"chat": True, "tools": True},
    }

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "test",
            autospec=True,
            return_value=ProviderTestResponse(
                ok=True,
                detail="Provider reachable.",
                provider_reachable=True,
                model_supported=True,
                capabilityEvidence=[
                    ProviderCapabilityEvidence(
                        name="tools",
                        declared=True,
                        observed=True,
                        state="verified",
                    )
                ],
                toolsReady=True,
                toolProbeStatus="verified",
            ),
        ),
    ):
        response = client.post(
            "/provider/test",
            json={"provider": provider_payload, "api_key": "sk-test"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_name"] == "tool-aware-provider"
    assert payload["base_url"] == "https://example.com/v1"
    assert payload["model"] == "ToolModel"
    assert payload["protocol"] == "openai_chat_completions_compatible"
    assert payload["protocol_family"] == "openai"
    assert payload["available_models"] == []
    assert payload["resolved_model"] is None
    assert payload["model_capabilities"]["ToolModel"]["tools"] is True
    assert payload["warnings"] == []
    assert payload["tools_ready"] is True
    assert payload["tool_probe_status"] == "verified"
    assert payload["capability_evidence"] == [
        {
            "name": "tools",
            "declared": True,
            "observed": True,
            "state": "verified",
        }
    ]


def test_provider_test_route_returns_observed_streaming_capability_truth(tmp_path: Path) -> None:
    provider_payload = {
        "name": "stream-aware-provider",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.stream-aware",
        "model": "StreamModel",
        "capabilities": {"chat": True, "streaming": True},
    }

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "test",
            autospec=True,
            return_value=ProviderTestResponse(
                ok=True,
                detail="Provider reachable.",
                provider_reachable=True,
                model_supported=True,
                capabilityEvidence=[
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    )
                ],
                streamingReady=True,
                streamProbeStatus="verified",
            ),
        ),
    ):
        response = client.post(
            "/provider/test",
            json={"provider": provider_payload, "api_key": "sk-test"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["streaming_ready"] is True
    assert payload["stream_probe_status"] == "verified"
    assert payload["capability_evidence"] == [
        {
            "name": "streaming",
            "declared": True,
            "observed": True,
            "state": "verified",
        }
    ]


def test_provider_test_route_hides_mojibake_from_all_chinese_failure_details(
    tmp_path: Path,
) -> None:
    categories = [
        "invalid_key_or_permission",
        "language_corruption",
        "language_probe_inconclusive",
        "empty_response",
        "rate_limit",
        "timeout",
        "network",
        "malformed_response",
        "model_unsupported",
        "model_not_found",
        "unknown_failure",
    ]
    provider_payload = {
        "name": "mini-max",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.minimax",
        "model": "MiniMax-M3",
    }

    with build_client(tmp_path, configure_provider=False) as client:
        for category in categories:
            with patch.object(
                ProviderService,
                "test",
                autospec=True,
                return_value=ProviderTestResponse(
                    ok=False,
                    detail="",
                    error_category=category,
                    provider_reachable=category
                    not in {"invalid_key_or_permission", "timeout", "network"},
                    model_supported=category not in {"model_unsupported", "model_not_found"},
                    status_code=200,
                ),
            ):
                response = client.post(
                    "/provider/test",
                    json={
                        "provider": provider_payload,
                        "api_key": "sk-test",
                        "response_language": "zh-CN",
                    },
                )

            assert response.status_code == 200
            detail = response.json()["detail"]
            assert detail.strip(), category
            assert not any(marker in detail for marker in MOJIBAKE_MARKERS), (category, detail)
            assert (
                "API" in detail
                or "provider" in detail
                or "protocol" in detail
                or "model" in detail
            )


def test_provider_models_route_localizes_success_detail_and_diagnostics_for_chinese(
    tmp_path: Path,
) -> None:
    provider_payload = {
        "name": "mini-max",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.minimax",
        "model": "MiniMax-M3",
    }

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "list_models",
            autospec=True,
            return_value=ProviderModelsResponse(
                ok=True,
                detail="Fetched 2 models. Resolved configured model to MiniMax-M3.",
                available_models=["MiniMax-M2.7-highspeed", "MiniMax-M3"],
                resolved_model="MiniMax-M3",
                diagnostics=[
                    "Using OpenAI-compatible model listing for provider mini-max.",
                    "Listed 2 models from provider mini-max.",
                    "Resolved configured model to MiniMax-M3.",
                ],
                listed=True,
                cache_hit=False,
            ),
        ),
    ):
        response = client.post(
            "/provider/models",
            json={
                "provider": provider_payload,
                "api_key": "sk-test",
                "response_language": "zh-CN",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["detail"] == (
        "\u5df2\u83b7\u53d6 2 \u4e2a models\u3002 "
        "\u5f53\u524d\u914d\u7f6e\u7684 model \u5bf9\u5e94\u5230\u300cMiniMax-M3\u300d\u3002"
    )
    assert (
        "\u5bf9 provider mini-max \u4f7f\u7528 OpenAI-compatible model listing\u3002"
        in payload["diagnostics"]
    )
    assert (
        "\u5df2\u4ece provider mini-max \u5217\u51fa 2 \u4e2a models\u3002"
        in payload["diagnostics"]
    )
    assert (
        "\u5f53\u524d\u914d\u7f6e\u7684 model \u5bf9\u5e94\u5230 MiniMax-M3\u3002"
        in payload["diagnostics"]
    )


def test_provider_test_route_rejects_newapi_connection_type_as_protocol(tmp_path: Path) -> None:
    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(ProviderService, "test", autospec=True) as test_mock,
    ):
        response = client.post(
            "/provider/test",
            json={
                "provider": {
                    "name": "NewAPI MiniMax",
                    "baseUrl": "http://example.invalid/v1",
                    "apiKeyRef": "trainer.newapi",
                    "model": "MiniMax-M2.7",
                    "protocol": "newapi_channel_conn",
                },
                "api_key": "sk-test",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error_category"] == "unknown_protocol"
    assert payload["protocol"] is None
    assert "sk-test" not in str(payload)
    assert any("newapi_channel_conn" in item for item in payload["diagnostics"])
    test_mock.assert_not_called()


def test_provider_test_unknown_protocol_overwrites_prior_success(tmp_path: Path) -> None:
    workspace_id = "workspace-unknown-protocol-overwrite"
    known_payload = {
        "name": "known-provider",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.known",
        "model": "ChatModel",
    }
    success = ProviderTestResponse(
        ok=True,
        detail="Provider reachable.",
        provider_reachable=True,
        model_supported=True,
        toolsReady=True,
        toolProbeStatus="verified",
        capabilityEvidence=[
            ProviderCapabilityEvidence(
                name="tools",
                declared=True,
                observed=True,
                state="verified",
            )
        ],
    )

    with build_client(tmp_path, configure_provider=False) as client:
        with patch.object(ProviderService, "test", autospec=True, return_value=success):
            first = client.post(
                "/provider/test",
                json={
                    "workspace_id": workspace_id,
                    "provider": known_payload,
                    "api_key": "sk-test",
                },
            )
        assert first.status_code == 200
        assert first.json()["ok"] is True
        unknown = client.post(
            "/provider/test",
            json={
                "workspace_id": workspace_id,
                "provider": {
                    **known_payload,
                    "protocol": "newapi_channel_conn",
                },
                "api_key": "sk-test",
            },
        )
        assert unknown.status_code == 200
        payload = unknown.json()
        assert payload["ok"] is False
        assert payload["error_category"] == "unknown_protocol"
        assert payload["tools_ready"] is False
        assert payload["capability_evidence"] == []
        assert "sk-test" not in str(payload)
        recovered = (
            client.get(f"/memory/summary?workspace_id={workspace_id}").json().get("memory") or {}
        ).get("workspace", {}).get("latest_provider_capability") or {}
        assert recovered.get("ok") is not True
        assert recovered.get("tools_ready") is not True


# ---------------------------------------------------------------------------
# Restored from test_provider_capability_persistence.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )


def _provider() -> ProviderConfig:
    return ProviderConfig(
        name="MiniMax Relay",
        baseUrl="http://minimax.relay.example.test",
        apiKeyRef="trainer.default",
        model="MiniMax-M2.7",
    )


def test_capability_truth_survives_runtime_rebuild(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    runtime_one = create_app(settings).state.runtime
    provider = _provider()

    runtime_one.remember_provider_capability_test(
        provider,
        "sk-test",
        {"ok": True, "capability_evidence": [{"name": "connection", "state": "verified"}]},
    )
    assert runtime_one.provider_connection_verified(
        runtime_one.provider_service_for(provider, "sk-test")
    )

    # 模拟 sidecar 重启:全新运行时,同一个数据库。
    runtime_two = create_app(settings).state.runtime
    service_two = runtime_two.provider_service_for(provider, "sk-test")
    assert runtime_two.provider_connection_verified(service_two), (
        "capability truth must survive a sidecar restart"
    )


def test_failed_test_does_not_persist_as_verified(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    runtime = create_app(settings).state.runtime
    provider = _provider()
    runtime.remember_provider_capability_test(
        provider,
        "sk-test",
        {"ok": False, "capability_evidence": []},
    )
    service = runtime.provider_service_for(provider, "sk-test")
    assert not runtime.provider_connection_verified(service)


def _passed_test_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "ok": True,
        "checkedAt": datetime.now(UTC).isoformat(),
        "baseUrl": "http://minimax.relay.example.test",
        "model": "MiniMax-M2.7",
        "capabilityEvidence": [
            {"name": "connection", "declared": True, "observed": True, "state": "verified"},
            {"name": "streaming", "declared": True, "observed": True, "state": "verified"},
            {"name": "tools", "declared": True, "observed": True, "state": "verified"},
        ],
    }
    record.update(overrides)
    return record


def test_host_recorded_test_restores_capability_after_a_data_root_switch(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    runtime = create_app(settings).state.runtime
    provider = _provider()
    service = runtime.provider_service_for(provider, "sk-test")
    request = SimpleNamespace(last_test_result=_passed_test_record())

    runtime.adopt_request_provider_evidence(request, service)

    assert runtime.provider_connection_verified(service)
    assert runtime.provider_capability_state_for(service, "streaming") == "verified"
    assert runtime.provider_capability_state_for(service, "tools") == "verified"

    # The adopted evidence is persisted, so the next process does not need the
    # request at all.
    runtime_two = create_app(settings).state.runtime
    service_two = runtime_two.provider_service_for(provider, "sk-test")
    assert runtime_two.provider_connection_verified(service_two)
    assert runtime_two.provider_capability_state_for(service_two, "streaming") == "verified"


def test_stale_or_mismatched_host_evidence_never_unlocks_the_provider(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    runtime = create_app(settings).state.runtime
    provider = _provider()
    service = runtime.provider_service_for(provider, "sk-test")

    stale = _passed_test_record(
        checkedAt=(datetime.now(UTC) - timedelta(hours=2)).isoformat()
    )
    runtime.adopt_request_provider_evidence(SimpleNamespace(last_test_result=stale), service)
    assert not runtime.provider_connection_verified(service)

    mismatched = _passed_test_record(model="another-model")
    runtime.adopt_request_provider_evidence(
        SimpleNamespace(last_test_result=mismatched), service
    )
    assert not runtime.provider_connection_verified(service)

    failed = _passed_test_record(ok=False)
    runtime.adopt_request_provider_evidence(SimpleNamespace(last_test_result=failed), service)
    assert not runtime.provider_connection_verified(service)


def test_session_message_request_keeps_host_last_test_evidence() -> None:
    from app.core.models import SessionMessageRequest

    record = _passed_test_record()
    for payload in (
        {"message": "hello", "lastTestResult": record},
        {"message": "hello", "last_test_result": record},
    ):
        request = SessionMessageRequest.model_validate(payload)
        assert request.last_test_result is not None
        assert request.last_test_result.get("ok") is True


# ---------------------------------------------------------------------------
# Restored from test_vision_challenge.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_challenge_is_decodable_content_and_does_not_disclose_the_answer() -> None:
    with patch("app.llm.vision_challenge.secrets.randbelow", side_effect=[31, 16, 69]):
        challenge = build_vision_challenge()
    image = fitz.Pixmap(base64.b64decode(challenge.image_url.split(",")[1]))
    assert (image.width, image.height) == (384, 128)
    assert challenge.expected == ("41", "26", "79")
    assert all(number not in challenge.prompt for number in challenge.expected)
    assert challenge.matches('{"left":"41","middle":"26","right":"79"}')
    # The bitmap has actual black digit strokes and white holes, not a single
    # colored pixel with a yes/no marker that a text-only model can echo.
    assert image.pixel(24, 39)[:3] == (18, 18, 18)
    assert image.pixel(24 + 7, 39)[:3] == (255, 255, 255)


@pytest.mark.parametrize("answer", [
    "VISION_OK", "Yes VISION_OK", "UNKNOWN", "41,26,79",
    '{"left":"41","middle":"26","right":"78"}',
    '{"left":41,"middle":26,"right":79}',
    '{"left":"41","middle":"26","right":"79","extra":"ok"}',
    'The answer is {"left":"41","middle":"26","right":"79"}',
])
def test_marker_guess_and_partially_matching_content_never_verify(answer: str) -> None:
    with patch("app.llm.vision_challenge.secrets.randbelow", side_effect=[31, 16, 69]):
        challenge = build_vision_challenge()
    assert not challenge.matches(answer)


def test_replayed_visual_answer_does_not_verify_a_new_challenge() -> None:
    with patch("app.llm.vision_challenge.secrets.randbelow", side_effect=[31, 16, 69, 54, 35, 82]):
        first, second = build_vision_challenge(), build_vision_challenge()
    answer = json.dumps(dict(zip(("left", "middle", "right"), first.expected, strict=True)))
    assert first.matches(answer)
    assert not second.matches(answer)
    assert first.image_url != second.image_url


@pytest.mark.parametrize("fence", ["json", "JSON", ""])
def test_single_json_code_block_verifies_the_same_visible_content(fence: str) -> None:
    with patch("app.llm.vision_challenge.secrets.randbelow", side_effect=[31, 16, 69]):
        challenge = build_vision_challenge()
    answer = '{"left":"41","middle":"26","right":"79"}'
    assert challenge.matches(f"```{fence}\n{answer}\n```")
    assert not challenge.matches(f"```{fence}\n{answer}\n```\nI guessed.")
    assert not challenge.matches(f"I guessed.\n```{fence}\n{answer}\n```")
    assert not challenge.matches(f"```{fence}\n{answer.replace('79', '78')}\n```")


def test_live_probe_path_rejects_an_echoed_marker() -> None:
    service = ProviderService()
    provider = ProviderConfig(
        name="visual-check", baseUrl="https://example.invalid/v1", model="model",
        apiKeyRef="test", protocol="openai_responses",
        capabilities=CapabilityFlags(responses=True, vision=True),
    )
    client = MagicMock()
    client.responses.create.return_value = {"output_text": "VISION_OK"}
    with patch.object(service, "_create_sync_client", return_value=client):
        observed, diagnostic = service._probe_vision_capability(provider, "test-secret")
    assert observed is False
    assert "randomized image content" in diagnostic
    assert "test-secret" not in diagnostic


# ---------------------------------------------------------------------------
# Restored from test_provider_recovery_and_stream_close.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


async def test_error_classification_unwraps_openai_connection_and_timeout_chains() -> None:
    config = ProviderConfig(
        name="journey-f",
        baseUrl="http://127.0.0.1:19999/v1",
        apiKeyRef="trainer.journey_f",
        model="MiniMax-M3.1-Flash",
        protocol="openai_chat_completions_compatible",
    )
    service = ProviderService(config=config, api_key="sk-test-recovery")

    closed = False

    class DummyClient:
        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    service._client = DummyClient()
    req = httpx.Request("POST", "http://127.0.0.1:19999/v1/chat/completions")
    conn_exc: Exception
    try:
        try:
            raise httpx.ConnectError("All connection attempts failed", request=req)
        except httpx.ConnectError as root:
            raise openai.APIConnectionError(message="Connection error.", request=req) from root
    except Exception as exc:
        conn_exc = exc

    category, retryable, _status, reachable, _supported = service._classify_error(conn_exc)
    assert category == "network"
    assert retryable is True
    assert reachable is False

    service._record_last_reply_failure(
        category=category,
        detail=service._detail_from_category(category, provider=config, error=conn_exc),
        retryable=retryable,
        status_code=None,
        provider_reachable=reachable,
        model_supported=None,
        error=conn_exc,
    )
    await asyncio.sleep(0)
    assert service._client is None
    assert closed is True

    timeout_exc = openai.APITimeoutError(request=req)
    t_cat, t_retry, _t_status, t_reach, _ = service._classify_error(timeout_exc)
    assert t_cat == "timeout"
    assert t_retry is True
    assert t_reach is False


async def test_hanging_stream_after_finish_reason_closes_promptly() -> None:
    class HangingAfterFinishStream:
        def __init__(self) -> None:
            self.closed = False
            self._step = 0

        def __aiter__(self) -> "HangingAfterFinishStream":
            return self

        async def __anext__(self) -> SimpleNamespace:
            self._step += 1
            if self._step == 1:
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="幂等键确保重试不会重复扣款。"),
                            finish_reason="stop",
                        )
                    ]
                )
            await asyncio.sleep(30.0)
            raise StopAsyncIteration

        async def aclose(self) -> None:
            self.closed = True

    config = ProviderConfig(
        name="m31-stream-close",
        baseUrl="https://example.com/v1",
        apiKeyRef="trainer.m31",
        model="MiniMax-M3.1",
        protocol="openai_chat_completions_compatible",
    )
    service = ProviderService(config=config, api_key="sk-m31")
    profile = UserProfile(long_term_goal="Idempotency", answer_policy="guided")
    hanging_stream_1 = HangingAfterFinishStream()
    hanging_stream_2 = HangingAfterFinishStream()

    async def fake_create_completion(*_args: object, **_kwargs: object):
        return hanging_stream_1, "MiniMax-M3.1"

    with (
        patch.object(streaming, "POST_FINISH_DRAIN_TIMEOUT_SECONDS", 0.12),
        patch.object(streaming, "STREAM_IDLE_TIMEOUT_SECONDS", 5.0),
        patch.object(ProviderService, "_create_chat_completion", fake_create_completion),
    ):
        collected = []
        started = asyncio.get_running_loop().time()
        async for chunk in service.coaching_reply_stream(
            profile,
            "为什么需要幂等键？",
            response_language="zh-CN",
        ):
            collected.append(chunk)
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 1.2
        assert "幂等键确保重试不会重复扣款。" in "".join(collected)
        assert hanging_stream_1.closed is True

        # Also verify agent_binding helper closes a stream that stalls after finish_reason="stop".
        finish_flag = {"done": False}
        binding_started = asyncio.get_running_loop().time()
        binding_chunks = []
        async for chunk in _iterate_and_close_provider_stream(
            hanging_stream_2,
            finish_seen=lambda: finish_flag["done"],
        ):
            binding_chunks.append(chunk)
            if chunk.choices[0].finish_reason == "stop":
                finish_flag["done"] = True
        binding_elapsed = asyncio.get_running_loop().time() - binding_started

        assert binding_elapsed < 1.2
        assert len(binding_chunks) == 1
        assert hanging_stream_2.closed is True


# ---------------------------------------------------------------------------
# Restored from test_vision_cache_upgrade.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_upgrade_invalidates_only_legacy_visual_understanding_truth(tmp_path) -> None:
    runtime = _make_runtime(tmp_path)
    runtime.repository.save_provider_capability("legacy", {
        "connection": "verified", "tools": "verified", "streaming": "verified", "vision": "verified",
    })
    runtime.hydrate_provider_capability_cache()
    assert runtime.provider_capability_cache["legacy"] == {
        "connection": "verified", "tools": "verified", "streaming": "verified", "vision": "unverified",
    }


def test_content_probe_truth_survives_reload_without_retesting_other_capabilities(tmp_path) -> None:
    runtime = _make_runtime(tmp_path)
    config = ProviderConfig(name="visual", baseUrl="https://example.com/v1", model="visual", apiKeyRef="trainer.visual")
    runtime.remember_provider_capability_test(config, "test-key", {
        "ok": True, "capabilityEvidence": [{"name": "vision", "state": "verified"}],
    })
    runtime.provider_capability_cache.clear()
    runtime.hydrate_provider_capability_cache()
    states = runtime.provider_capability_cache[_provider_capability_cache_key(config, "test-key")]
    assert states["vision"] == "verified"
    assert states["vision_probe_version"] == VISION_PROBE_VERSION
    assert states["connection"] == "verified"
