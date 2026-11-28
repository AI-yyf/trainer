"""The browser side panel must reach the model the UI host uses for the workspace.

The sidecar has no provider of its own, and the browser lane strips provider
fields by design (the browser must never see a provider key). Before this
memory existed every browser message fell through to the sidecar's empty
default provider and was answered with 400. The existing browser-chat tests
assigned ``runtime.provider_service`` by hand, or accepted a 400, so neither
noticed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from app.core.models import ProviderConfig
from app.llm.provider_service import ProviderService
from tests.client_fixtures import build_client
from tests.test_browser_chat import _pair_browser, _runtime

REPLY = "好的，我们先从一个最小验证步骤开始。"


def _script_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every provider call in the test returns one scripted reply."""

    async def _chat(self: ProviderService, *_: Any, **__: Any) -> str:
        return REPLY

    async def _stream(self: ProviderService, *_: Any, **__: Any) -> AsyncIterator[str]:
        yield REPLY

    monkeypatch.setattr(ProviderService, "chat_completion", _chat)
    monkeypatch.setattr(ProviderService, "chat_completion_stream", _stream)
    monkeypatch.setattr(ProviderService, "coaching_reply", _chat)
    monkeypatch.setattr(ProviderService, "coaching_reply_stream", _stream)


def _host_provider() -> dict[str, Any]:
    return {
        "name": "host-gateway",
        "baseUrl": "http://127.0.0.1:9/v1",
        "apiKeyRef": "trainer.browser-provider",
        "model": "glm-4.6",
        "protocol": "openai_chat_completions_compatible",
        "capabilities": {
            "chat": True,
            "responses": True,
            "vision": False,
            "embeddings": True,
            "tools": False,
            "jsonSchema": False,
            "streaming": True,
        },
    }


def test_browser_message_uses_the_provider_the_host_last_used_for_the_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = "workspace-browser-provider"
    with build_client(tmp_path, configure_provider=False) as client:
        _script_reply(monkeypatch)
        credential = _pair_browser(client, workspace_id)
        headers = {"Authorization": f"Bearer {credential}"}
        session_id = str(client.get("/browser/chat/bootstrap", headers=headers).json()["session_id"])

        # Nothing from the UI host yet: the sidecar has no provider to use.
        before = client.post(
            "/browser/chat/message", headers=headers, json={"session_id": session_id, "message": "你好"}
        )
        assert before.status_code == 400

        # The UI host names the provider for this workspace on its own lane.
        host = client.post(
            "/session/message",
            json={
                "workspace_id": workspace_id,
                "message": "你好",
                "provider": _host_provider(),
                "api_key": "sk-test",
            },
        )
        assert host.status_code == 200, host.text

        after = client.post(
            "/browser/chat/message",
            headers=headers,
            json={"session_id": session_id, "message": "给我一个最小练习"},
        )
        assert after.status_code == 200, after.text

        service = _runtime(client).workspace_provider_service(workspace_id)
        assert service is not None
        assert service._config is not None and service._config.model == "glm-4.6"  # noqa: SLF001


def test_browser_message_keeps_workspaces_apart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A workspace the UI host never sent from has no provider to borrow."""
    used, unused = "workspace-browser-used", "workspace-browser-unused"
    with build_client(tmp_path, configure_provider=False) as client:
        _script_reply(monkeypatch)
        used_credential = _pair_browser(client, used)
        unused_credential = _pair_browser(client, unused)
        host = client.post(
            "/session/message",
            json={
                "workspace_id": used,
                "message": "你好",
                "provider": _host_provider(),
                "api_key": "sk-test",
            },
        )
        assert host.status_code == 200, host.text

        unused_session = str(
            client.get(
                "/browser/chat/bootstrap", headers={"Authorization": f"Bearer {unused_credential}"}
            ).json()["session_id"]
        )
        refused = client.post(
            "/browser/chat/message",
            headers={"Authorization": f"Bearer {unused_credential}"},
            json={"session_id": unused_session, "message": "你好"},
        )
        assert refused.status_code == 400

        used_session = str(
            client.get(
                "/browser/chat/bootstrap", headers={"Authorization": f"Bearer {used_credential}"}
            ).json()["session_id"]
        )
        allowed = client.post(
            "/browser/chat/message",
            headers={"Authorization": f"Bearer {used_credential}"},
            json={"session_id": used_session, "message": "你好"},
        )
        assert allowed.status_code == 200, allowed.text


def test_workspace_provider_memory_only_records_what_the_host_named(tmp_path: Path) -> None:
    runtime = _runtime(build_client(tmp_path, configure_provider=False))
    provider = ProviderConfig(
        name="host-gateway",
        baseUrl="http://127.0.0.1:9/v1",
        apiKeyRef="trainer.browser-provider",
        model="glm-4.6",
        protocol="openai_chat_completions_compatible",
    )

    runtime.remember_workspace_provider("", provider, "sk-test")
    runtime.remember_workspace_provider("workspace-browser-none", None, "sk-test")
    assert runtime.workspace_provider_services == {}

    runtime.remember_workspace_provider("workspace-browser-one", provider, "sk-test")
    remembered = runtime.workspace_provider_service("workspace-browser-one")
    assert remembered is not None and remembered.has_api_key
    # The same cached service every request-scoped lane uses, not a second copy.
    assert remembered is runtime.provider_service_for(provider, "sk-test")
    assert runtime.workspace_provider_service("workspace-browser-other") is None


def test_browser_bootstrap_exposes_redacted_workspace_provider_without_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = "workspace-browser-redacted-summary"
    with build_client(tmp_path, configure_provider=False) as client:
        _script_reply(monkeypatch)
        credential = _pair_browser(client, workspace_id)
        headers = {"Authorization": f"Bearer {credential}"}

        initial = client.get("/browser/chat/bootstrap", headers=headers)
        assert initial.status_code == 200
        initial_body = initial.json()
        assert initial_body["workspace_provider"]["configured"] is False
        assert "api_key" not in initial_body["workspace_provider"]

        host = client.post(
            "/session/message",
            json={
                "workspace_id": workspace_id,
                "message": "你好",
                "provider": _host_provider(),
                "api_key": "sk-secret-never-leak",
            },
        )
        assert host.status_code == 200, host.text

        refreshed = client.get("/browser/chat/bootstrap", headers=headers)
        assert refreshed.status_code == 200
        wp = refreshed.json()["workspace_provider"]
        assert wp["configured"] is True
        assert wp["model"] == "glm-4.6"
        assert wp["api_key_configured"] is True
        assert "sk-secret-never-leak" not in refreshed.text
        assert "baseUrl" not in wp
        assert "api_key" not in wp

        new_sess = client.post("/browser/chat/session/new", headers=headers, json={})
        assert new_sess.status_code == 200
        assert new_sess.json()["workspace_provider"]["configured"] is True
