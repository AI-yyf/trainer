"""Scheme-less provider base URLs resolve to a working scheme.

A user who types or pastes "minimax.example.com" (no scheme) must still reach
http-only relays and https-only providers. The sidecar transport owns scheme
resolution: local hosts are http without probing, public hosts get a TLS
handshake probe, and the resolution is memoized per host.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api import routers
from app.api.routers import (
    looks_like_schemeless_provider_host,
    reset_provider_scheme_cache,
    resolve_provider_url_scheme,
)
from app.core.models import ProviderConfig, ProviderTestResponse
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


@pytest.fixture(autouse=True)
def _clean_scheme_cache():
    reset_provider_scheme_cache()
    yield
    reset_provider_scheme_cache()


def test_local_hosts_short_circuit_to_http() -> None:
    assert resolve_provider_url_scheme("localhost:8765") == "http"
    assert resolve_provider_url_scheme("127.0.0.1:8099/v1") == "http"
    assert resolve_provider_url_scheme("192.168.1.10:11434") == "http"
    assert resolve_provider_url_scheme("nas.local:1234") == "http"
    assert resolve_provider_url_scheme("host.docker.internal:11434") == "http"


def test_looks_like_schemeless_provider_host_matches_service_addresses() -> None:
    assert looks_like_schemeless_provider_host("minimax.redfast.top")
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
