from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APIStatusError

from app.core.models import ProviderConfig, UserProfile
from app.llm.agent_loop import AgentProvider
from app.llm.provider.errors import ProviderRuntimeResponseError, provider_http_failure
from app.llm.provider.quota_copy import provider_quota_reply
from app.llm.provider_service import ProviderService


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
])
def test_billing_codes_override_status_without_reclassifying_auth_or_throttling(
    status: int, code: str, expected: str, retryable: bool,
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


@pytest.mark.parametrize("protocol", ["anthropic_messages", "gemini_generate_content"])
def test_native_probe_keeps_safe_quota_category_before_discarding_body(protocol: str) -> None:
    provider = ProviderConfig(
        name="quota-probe", base_url="https://provider.example", api_key_ref="test-key",
        model="test-model", protocol=protocol,
    )
    response = httpx.Response(403, json={"error": {
        "code": "insufficient_user_quota", "message": "secret-key upstream private details",
    }})
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response
    service = ProviderService(provider, "secret-key")
    with patch("app.llm.provider_service.httpx.Client", return_value=client):
        with pytest.raises(ProviderRuntimeResponseError) as raised:
            service._native_protocol_probe_preview(
                protocol=protocol, provider=provider, api_key="secret-key", prompt="probe",
            )
    error = raised.value
    assert service._classify_error(error) == ("quota_exhausted", False, 403, True, None)
    assert "secret-key" not in str(error)
    assert "upstream private" not in str(error)


def test_native_non_json_error_keeps_existing_status_diagnosis() -> None:
    response = httpx.Response(403, text="PRIVATE HTML")
    error = provider_http_failure(response, detail="Native request failed (HTTP 403).")
    assert ProviderService()._classify_error(error)[0] == "invalid_key_or_permission"
    assert "PRIVATE" not in str(error)


@pytest.mark.parametrize("language", ["zh-CN", "en-US", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR"])
def test_coach_and_test_details_share_localized_quota_recovery(language: str) -> None:
    service = ProviderService(api_key="private-api-key")
    provider = ProviderConfig(name="quota", base_url="https://example.test", api_key_ref="key", model="model")
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
        name="transport", base_url="https://example.test/v1", api_key_ref="private",
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
