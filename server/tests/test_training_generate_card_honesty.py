from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from app.api.routers import _resolve_agent_loop_enabled
from app.core.models import (
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderTestResponse,
    TurnRequest,
)
from app.llm.provider_service import ProviderService
from tests.test_api import build_client
from tests.test_unconfigured_provider_gate import build_client as build_unconfigured_client

KIMI_COMPATIBLE_PROVIDER = {
    "name": "Kimi",
    "baseUrl": "https://api.moonshot.cn/v1",
    "apiKeyRef": "kimi.default",
    "model": "moonshot-v1-8k",
    "protocol": "openai_chat_completions_compatible",
    "capabilities": {
        "chat": True,
        "tools": False,
        "streaming": True,
        "jsonSchema": False,
        "vision": False,
    },
}


def _practice_model_card() -> str:
    return json.dumps(
        {
            "title": "Practice tuple unpacking",
            "focus_area": "tuple unpacking",
            "target_skill": "unpack a pair into two names",
            "scenario": "A helper returns a pair and the learner needs both values.",
            "problem_statement": "Unpack the pair from parse_pair() into left and right.",
            "api_hints": ["Call parse_pair()", "Unpack into two names"],
            "deliverable": "A snippet that unpacks the pair and prints both names.",
            "self_check": ["Both names are bound", "No index lookups remain"],
            "grading_rubric": ["Uses unpacking", "Prints both values"],
            "stuck_recovery": "Write the two names on paper first, then unpack.",
            "reflection_prompt": "What broke when you used indexes instead?",
            "verification_steps": ["Run the snippet", "Confirm both names print"],
            "success_signal": "Both values print from the unpacked names.",
            "return_with": "The snippet and its printed output.",
            "learner_deliverables": ["The snippet", "The printed output"],
        }
    )


def _sandbox_card_markdown(tmp_path: Path) -> list[Path]:
    return [path for path in tmp_path.rglob("*.md") if "cards" in path.parts]


def _assert_sandbox_card_persisted(sandbox_root: Path, card_id: str) -> None:
    cards_root = sandbox_root / "cards"
    persisted = [path for path in cards_root.rglob("*.md") if card_id in path.name]
    assert persisted, f"expected sandbox card file for {card_id} under {cards_root}"
    assert (cards_root / "current" / "active.md").is_file()


def _sse_complete_response(body: str) -> dict[str, object]:
    for line in reversed(body.splitlines()):
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: ") :])
        if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
            return payload["response"]
    return {}


def _kimi_provider_config() -> ProviderConfig:
    return ProviderConfig(
        name="Kimi",
        base_url="https://api.moonshot.cn/v1",
        api_key_ref="kimi.default",
        model="moonshot-v1-8k",
        protocol="openai_chat_completions_compatible",
        capabilities={"chat": True, "tools": False, "streaming": True},
    )


def _tools_verified_test_result() -> ProviderTestResponse:
    return ProviderTestResponse(
        ok=True,
        detail="chat probe passed",
        provider_reachable=True,
        model_supported=True,
        capability_evidence=[
            ProviderCapabilityEvidence(
                name="tools",
                declared=False,
                observed=True,
                state="verified",
            ),
            ProviderCapabilityEvidence(
                name="streaming",
                declared=True,
                observed=True,
                state="verified",
            ),
        ],
        tools_ready=True,
        tool_probe_status="verified",
        streaming_ready=True,
        stream_probe_status="verified",
    )


def _install_untested_compatible_provider(client) -> ProviderConfig:
    provider = _kimi_provider_config()
    runtime = client.app.state.runtime
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
    runtime.provider_service_cache.clear()
    runtime.provider_capability_cache.clear()
    return provider


def test_generate_card_without_live_provider_returns_400_and_writes_no_card(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-unconfigured-card-file"
    with build_unconfigured_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Unconfigured card"},
        )
        assert started.status_code == 200, started.text
        response = client.post(
            "/training/generate-card",
            json={
                "session_id": started.json()["session_id"],
                "workspace_id": workspace_id,
                "source": "conversation_gap",
                "card_type": "practice",
                "focus_area": "tuple unpacking",
                "response_language": "en-US",
            },
        )
        runtime = client.app.state.runtime
        sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)
    assert response.status_code == 400, response.text
    assert not response.json().get("card")
    assert _sandbox_card_markdown(tmp_path) == []
    cards_root = sandbox_root / "cards"
    assert not cards_root.exists() or not list(cards_root.rglob("*.md"))


def test_generate_card_stream_without_live_provider_returns_400_and_writes_no_card(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-unconfigured-card-stream"
    with build_unconfigured_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Unconfigured stream card"},
        )
        assert started.status_code == 200, started.text
        response = client.post(
            "/training/generate-card/stream",
            json={
                "session_id": started.json()["session_id"],
                "workspace_id": workspace_id,
                "source": "conversation_gap",
                "card_type": "practice",
                "focus_area": "tuple unpacking",
                "response_language": "en-US",
            },
        )
        runtime = client.app.state.runtime
        sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)
    assert response.status_code == 400, response.text
    assert not response.json().get("card")
    assert "event: complete" not in response.text
    cards_root = sandbox_root / "cards"
    assert not cards_root.exists() or not list(cards_root.rglob("*.md"))


def test_generate_card_stream_untested_compatible_profile_returns_400(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-untested-compatible-stream"
    with build_client(tmp_path, configure_provider=False) as client:
        _install_untested_compatible_provider(client)
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Untested compatible"},
        )
        assert started.status_code == 200, started.text
        response = client.post(
            "/training/generate-card/stream",
            json={
                "workspace_id": workspace_id,
                "source": "conversation_gap",
                "card_type": "practice",
                "focus_area": "tuple unpacking",
                "response_language": "en-US",
            },
        )
        runtime = client.app.state.runtime
        sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)
        assert runtime.provider_service.supports_executable_tools() is False
    assert response.status_code == 400, response.text
    cards_root = sandbox_root / "cards"
    assert not cards_root.exists() or not list(cards_root.rglob("*.md"))


def test_generate_card_with_live_provider_persists_contract_fields(tmp_path: Path) -> None:
    workspace_id = "workspace-live-card-contract"

    async def fake_chat(*_args: object, **_kwargs: object) -> str:
        return _practice_model_card()

    with patch.object(ProviderService, "chat_completion", new=fake_chat):
        with build_client(tmp_path) as client:
            started = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": "Live card"},
            )
            assert started.status_code == 200, started.text
            response = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "tuple unpacking",
                    "target_skill": "unpack a pair",
                    "response_language": "en-US",
                },
            )
            assert response.status_code == 200, response.text
            card = response.json()["card"]
            assert card["card_type"] == "practice"
            assert card["deliverable"]
            assert card["verification_steps"]
            assert card["success_signal"]
            assert card["return_with"]
            runtime = client.app.state.runtime
            sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)
            _assert_sandbox_card_persisted(sandbox_root, card["card_id"])
            assert (sandbox_root / "cards" / "practice" / f"{card['card_id']}.md").is_file()


def test_generate_card_stream_with_live_provider_persists_contract_fields(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-live-card-stream-contract"
    raw = _practice_model_card()

    async def fake_stream(*_args: object, **_kwargs: object):
        yield raw[: len(raw) // 2]
        yield raw[len(raw) // 2 :]

    with patch.object(ProviderService, "chat_completion_stream", new=fake_stream):
        with build_client(tmp_path) as client:
            started = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": "Live stream card"},
            )
            assert started.status_code == 200, started.text
            response = client.post(
                "/training/generate-card/stream",
                json={
                    "workspace_id": workspace_id,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "tuple unpacking",
                    "target_skill": "unpack a pair",
                    "response_language": "en-US",
                },
            )
            runtime = client.app.state.runtime
            sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)
    assert response.status_code == 200, response.text
    assert "event: complete" in response.text
    card = _sse_complete_response(response.text).get("card")
    assert isinstance(card, dict)
    assert card["card_type"] == "practice"
    assert card["deliverable"]
    assert card["verification_steps"]
    assert card["success_signal"]
    assert card["return_with"]
    _assert_sandbox_card_persisted(sandbox_root, str(card["card_id"]))


def test_generate_card_live_provider_failure_does_not_persist_a_template(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-live-card-failure"

    async def fake_chat(*_args: object, **_kwargs: object) -> str:
        return "not valid card JSON"

    with patch.object(ProviderService, "chat_completion", new=fake_chat):
        with build_client(tmp_path) as client:
            started = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": "Live card fail"},
            )
            assert started.status_code == 200, started.text
            response = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "tuple unpacking",
                    "response_language": "en-US",
                },
            )
            runtime = client.app.state.runtime
            sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)
    assert response.status_code == 400, response.text
    assert not response.json().get("card")
    cards_root = sandbox_root / "cards"
    assert not cards_root.exists() or not list(cards_root.rglob("*.md"))


def test_generate_card_stream_live_provider_failure_does_not_persist_a_template(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-live-card-stream-failure"

    async def fake_stream(*_args: object, **_kwargs: object):
        yield "not valid card JSON"

    with patch.object(ProviderService, "chat_completion_stream", new=fake_stream):
        with build_client(tmp_path) as client:
            started = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": "Live stream fail"},
            )
            assert started.status_code == 200, started.text
            response = client.post(
                "/training/generate-card/stream",
                json={
                    "workspace_id": workspace_id,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "tuple unpacking",
                    "response_language": "en-US",
                },
            )
            runtime = client.app.state.runtime
            sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)
    assert response.status_code == 200, response.text
    assert "event: error" in response.text
    completed = _sse_complete_response(response.text)
    assert not completed.get("card")
    cards_root = sandbox_root / "cards"
    assert not cards_root.exists() or not list(cards_root.rglob("*.md"))


def test_observed_tools_enable_agent_loop_on_compatible_template() -> None:
    service = ProviderService(
        config=_kimi_provider_config(),
        api_key="sk-test",
    )
    resources = TurnRequest(message="整理资料库", active_view="resources")
    assert service.supports_executable_tools() is False
    assert _resolve_agent_loop_enabled(resources, service) is False
    service.apply_observed_capability_states({"tools": "verified", "connection": "verified"})
    assert service.supports_executable_tools() is True
    assert _resolve_agent_loop_enabled(resources, service) is True


def test_provider_test_overlays_tools_on_default_compatible_profile(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-kimi-tools-overlay"

    async def fake_chat(*_args: object, **_kwargs: object) -> str:
        return _practice_model_card()

    with build_client(tmp_path, configure_provider=False) as client:
        provider = _install_untested_compatible_provider(client)
        runtime = client.app.state.runtime
        resources = TurnRequest(message="整理资料库", active_view="resources")
        assert runtime.provider_service.supports_executable_tools() is False
        assert _resolve_agent_loop_enabled(resources, runtime.provider_service) is False

        with patch.object(ProviderService, "test", autospec=True, return_value=_tools_verified_test_result()):
            tested = client.post(
                "/provider/test",
                json={
                    "provider": KIMI_COMPATIBLE_PROVIDER,
                    "api_key": "sk-test",
                    "workspace_id": workspace_id,
                },
            )
        assert tested.status_code == 200, tested.text
        payload = tested.json()
        assert payload["ok"] is True
        assert payload["tools_ready"] is True
        assert runtime.provider_service.supports_executable_tools() is True
        assert _resolve_agent_loop_enabled(resources, runtime.provider_service) is True
        assert runtime.provider_config.capabilities.tools is False

        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Kimi overlay"},
        )
        assert started.status_code == 200, started.text

        with patch.object(ProviderService, "chat_completion", new=fake_chat):
            minted = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "tuple unpacking",
                    "target_skill": "unpack a pair",
                    "response_language": "en-US",
                },
            )
        assert minted.status_code == 200, minted.text
        card = minted.json()["card"]
        assert card["deliverable"]
        assert card["verification_steps"]
        assert card["success_signal"]
        assert card["return_with"]
        sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)
        _assert_sandbox_card_persisted(sandbox_root, card["card_id"])
        assert provider.protocol == "openai_chat_completions_compatible"


def _host_last_test_payload(provider: ProviderConfig) -> dict[str, object]:
    return {
        "ok": True,
        "baseUrl": provider.base_url,
        "model": provider.model,
        "capabilityEvidence": [
            {
                "name": "tools",
                "declared": False,
                "observed": True,
                "state": "verified",
            },
            {
                "name": "streaming",
                "declared": True,
                "observed": True,
                "state": "verified",
            },
        ],
        "toolsReady": True,
        "toolProbeStatus": "verified",
        "streamingReady": True,
        "streamProbeStatus": "verified",
    }


def test_generate_card_rehydrates_host_last_test_when_sidecar_cache_is_empty(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-rehydrate-last-test"

    async def fake_chat(*_args: object, **_kwargs: object) -> str:
        return _practice_model_card()

    with build_client(tmp_path, configure_provider=False) as client:
        provider = _install_untested_compatible_provider(client)
        runtime = client.app.state.runtime
        assert runtime.provider_capability_cache == {}
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Rehydrate last-test"},
        )
        assert started.status_code == 200, started.text
        with patch.object(ProviderService, "chat_completion", new=fake_chat):
            response = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "tuple unpacking",
                    "target_skill": "unpack a pair",
                    "response_language": "en-US",
                    "provider": KIMI_COMPATIBLE_PROVIDER,
                    "api_key": "sk-test",
                    "lastTestResult": _host_last_test_payload(provider),
                },
            )
        assert response.status_code == 200, response.text
        card = response.json()["card"]
        assert card["deliverable"]
        assert runtime.provider_service.supports_executable_tools() is True
        sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)
        _assert_sandbox_card_persisted(sandbox_root, card["card_id"])


def test_generate_card_rejects_last_test_for_a_different_model(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-rehydrate-mismatch"
    with build_client(tmp_path, configure_provider=False) as client:
        provider = _install_untested_compatible_provider(client)
        mismatched = _host_last_test_payload(provider)
        mismatched["model"] = "other-model"
        response = client.post(
            "/training/generate-card",
            json={
                "workspace_id": workspace_id,
                "source": "conversation_gap",
                "card_type": "practice",
                "focus_area": "tuple unpacking",
                "response_language": "en-US",
                "provider": KIMI_COMPATIBLE_PROVIDER,
                "api_key": "sk-test",
                "lastTestResult": mismatched,
            },
        )
        assert response.status_code == 400, response.text
        assert not response.json().get("card")
        assert client.app.state.runtime.provider_service.supports_executable_tools() is False


def test_empty_new_api_profile_is_not_live_usable_and_writes_no_card(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-newapi-empty"
    empty_new_api = {
        "name": "New API",
        "baseUrl": "",
        "model": "",
        "protocol": "openai_chat_completions_compatible",
        "connectionType": "newapi_channel_conn",
        "apiKeyRef": "newapi.default",
    }
    with build_client(tmp_path, configure_provider=False) as client:
        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="New API",
            base_url="",
            api_key_ref="newapi.default",
            model="",
            protocol="openai_chat_completions_compatible",
            connectionType="newapi_channel_conn",
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()
        runtime.provider_capability_cache.clear()
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Empty New API"},
        )
        assert started.status_code == 200, started.text
        response = client.post(
            "/training/generate-card",
            json={
                "workspace_id": workspace_id,
                "source": "conversation_gap",
                "card_type": "practice",
                "focus_area": "tuple unpacking",
                "response_language": "en-US",
                "provider": empty_new_api,
                "api_key": "sk-test",
                "lastTestResult": {
                    "ok": True,
                    "baseUrl": "",
                    "model": "",
                    "capabilityEvidence": [
                        {
                            "name": "tools",
                            "declared": False,
                            "observed": True,
                            "state": "verified",
                        }
                    ],
                },
            },
        )
        runtime = client.app.state.runtime
        sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)
    assert response.status_code == 400, response.text
    assert not response.json().get("card")
    cards_root = sandbox_root / "cards"
    assert not cards_root.exists() or not list(cards_root.rglob("*.md"))

