"""Phase 4 — provider_payload 拆分后的独立行为锁.

覆盖: API key 解析、base URL 归一化 (端点→基址、无 scheme 主机)、
connection type / protocol / mode / credential mode 解析、capabilities
默认语义与完整 ProviderConfig 组装。网络探测用 monkeypatch 隔离。
"""

from __future__ import annotations

import pytest

from app.api import provider_payload as payload_module
from app.api.provider_payload import (
    normalize_provider_base_url,
    provider_api_key_from_payload,
    provider_capabilities_from_payload,
    provider_config_from_payload,
    provider_connection_type_from_payload,
    provider_credential_mode_from_payload,
    provider_mode_from_payload,
    provider_payload_declares_protocol,
    provider_protocol_from_payload,
)


def test_api_key_parsing() -> None:
    assert provider_api_key_from_payload({"api_key": "  sk-1  "}) == "sk-1"
    assert provider_api_key_from_payload({"apiKey": "sk-2"}) == "sk-2"
    assert provider_api_key_from_payload({"api_key": 123}) is None
    assert provider_api_key_from_payload({}) is None


def test_base_url_strips_request_endpoints_by_protocol() -> None:
    assert normalize_provider_base_url(
        "https://relay.example.com/v1/chat/completions", "openai_chat_completions",
    ) == "https://relay.example.com/v1"
    assert normalize_provider_base_url(
        "https://relay.example.com/v1/responses", "openai_responses",
    ) == "https://relay.example.com/v1"
    assert normalize_provider_base_url(
        "https://api.anthropic.com/v1/messages", "anthropic_messages",
    ) == "https://api.anthropic.com/v1"
    # Non-endpoint path is preserved (trailing slash trimmed).
    assert normalize_provider_base_url(
        "https://relay.example.com/proxy/", "openai_chat_completions_compatible",
    ) == "https://relay.example.com/proxy"


def test_schemeless_host_gets_probed_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        payload_module, "looks_like_schemeless_provider_host", lambda value: True
    )
    monkeypatch.setattr(
        payload_module, "resolve_provider_url_scheme", lambda value: "http"
    )
    assert normalize_provider_base_url("relay.example.com/v1", "openai_chat_completions") == (
        "http://relay.example.com/v1"
    )


def test_connection_type_protocol_mode_credential_parsing() -> None:
    assert provider_connection_type_from_payload(
        {"_type": "newapi_channel_conn"}
    ) == "newapi_channel_conn"
    assert provider_connection_type_from_payload({"connectionType": "newapi_channel_conn"}) == (
        "newapi_channel_conn"
    )
    assert provider_connection_type_from_payload({}) is None

    assert provider_protocol_from_payload({"api": "anthropic"}) == "anthropic_messages"
    assert provider_protocol_from_payload({"protocol": "openai"}) == "openai_chat_completions"
    assert provider_protocol_from_payload({"protocol": "compatible"}) == (
        "openai_chat_completions_compatible"
    )
    assert provider_protocol_from_payload({}) is None

    assert provider_mode_from_payload({"mode": "gateway"}) == "gateway"
    assert provider_mode_from_payload({"mode": "other"}) is None
    assert provider_credential_mode_from_payload({"credentialMode": "workspace_secret"}) == (
        "workspace_secret"
    )
    assert provider_credential_mode_from_payload({}) is None

    assert provider_payload_declares_protocol({"api": "openai"}) is True
    assert provider_payload_declares_protocol({"providerKey": "x"}) is True
    assert provider_payload_declares_protocol({"name": "x"}) is False


def test_capabilities_defaults_are_protocol_and_declaration_aware() -> None:
    explicit = provider_capabilities_from_payload(
        {"capabilities": {"chat": True, "tools": True}}
    )
    assert explicit.tools is True

    # Undeclared protocol: permissive defaults are withheld (fail-closed).
    undeclared = provider_capabilities_from_payload({"name": "x"})
    assert undeclared.tools is False
    assert undeclared.embeddings is False

    declared = provider_capabilities_from_payload({"api": "openai"})
    assert declared.tools is True


def test_config_from_payload_assembles_provider_config() -> None:
    config = provider_config_from_payload(
        {
            "provider": {
                "name": "My Relay",
                "api": "openai",
                "baseUrl": "https://relay.example.com/v1/chat/completions",
                "model": " gpt-4o-mini ",
                "mode": "gateway",
                "credentialMode": "workspace_secret",
                "_type": "newapi_channel_conn",
                "availableModels": ["gpt-4o-mini"],
                "modelAliases": {"fast": "gpt-4o-mini"},
                "capabilities": {"chat": True, "tools": True},
            }
        }
    )
    assert config is not None
    assert config.name == "My Relay"
    assert config.base_url == "https://relay.example.com/v1"
    assert config.model == "gpt-4o-mini"
    assert config.protocol == "openai_chat_completions"
    assert config.mode == "gateway"
    assert config.credential_mode == "workspace_secret"
    assert config.connection_type == "newapi_channel_conn"
    assert config.available_models == ["gpt-4o-mini"]
    assert config.capabilities.tools is True

    assert provider_config_from_payload({}) is None
    assert provider_config_from_payload({"provider": {"api": "not-a-protocol"}}) is None
    assert provider_config_from_payload(
        {"provider": {"_type": "newapi_channel_conn"}}
    ) is None
