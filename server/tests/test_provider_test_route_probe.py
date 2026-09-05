from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.core.models import ProviderCapabilityEvidence, ProviderModelsResponse, ProviderTestResponse
from app.llm.provider_service import ProviderService
from tests.test_api import build_client

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


def test_provider_test_route_localizes_failed_probe_detail_for_chinese(tmp_path: Path) -> None:
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
                ok=False,
                detail="",
                error_category="language_probe_inconclusive",
                provider_reachable=True,
                model_supported=True,
                status_code=200,
            ),
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
    payload = response.json()
    assert payload["error_category"] == "language_probe_inconclusive"
    assert payload["detail"] == (
        "provider \u53ef\u8fbe\uff0c\u4f46 Trainer "
        "\u8fd8\u4e0d\u80fd\u5b8c\u6574\u9a8c\u8bc1\u8fd9\u6761\u8fde\u63a5\u7684 "
        "zh-CN \u8f93\u5165\u4fdd\u771f\u5ea6\u3002"
    )


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
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="tools",
                        declared=True,
                        observed=True,
                        state="verified",
                    )
                ],
                tools_ready=True,
                tool_probe_status="verified",
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
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    )
                ],
                streaming_ready=True,
                stream_probe_status="verified",
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


def test_provider_test_route_rejects_tools_ready_without_verified_evidence(tmp_path: Path) -> None:
    provider_payload = {
        "name": "declared-only-provider",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.declared-only",
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
                tools_ready=True,
                tool_probe_status="verified",
            ),
        ),
    ):
        response = client.post(
            "/provider/test",
            json={"provider": provider_payload, "api_key": "sk-test"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tools_ready"] is False
    assert payload["tool_probe_status"] == "unverified"
    assert payload["capability_evidence"] == []
    assert not any(item.get("name") == "tools" for item in payload["capability_evidence"])


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


def test_provider_test_route_localizes_success_detail_and_diagnostics_for_chinese(
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
            "test",
            autospec=True,
            return_value=ProviderTestResponse(
                ok=True,
                detail="Provider reachable. Chat probe succeeded with model MiniMax-M3. Response: pong",
                diagnostics=[
                    "Chat probe succeeded with model MiniMax-M3.",
                    "Probe response preview: pong",
                ],
                provider_reachable=True,
                model_supported=True,
            ),
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
    payload = response.json()
    assert payload["ok"] is True
    assert payload["detail"] == (
        "provider \u5df2\u8fde\u901a\uff0cchat probe \u5df2\u901a\u8fc7\uff0c"
        "\u5f53\u524d model\u300cMiniMax-M3\u300d\u53ef\u4ee5\u8fd4\u56de\u53ef\u89c1\u5185\u5bb9\u3002 "
        "\u54cd\u5e94\u9884\u89c8\uff1apong"
    )
    assert "live connectivity check \u5df2\u901a\u8fc7\u3002" in payload["diagnostics"]
    assert (
        "chat probe \u5df2\u901a\u8fc7\uff0c\u4f7f\u7528\u7684 model \u662f MiniMax-M3\u3002"
        in payload["diagnostics"]
    )
    assert "probe \u54cd\u5e94\u9884\u89c8\uff1apong" in payload["diagnostics"]


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


def test_provider_test_route_chips_only_from_observed_live_evidence(tmp_path: Path) -> None:
    provider_payload = {
        "name": "observed-only-provider",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.observed-only",
        "model": "StreamModel",
        "capabilities": {"chat": True, "tools": True, "streaming": True, "vision": True},
    }
    workspace_id = "workspace-observed-chips"

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
                streaming_ready=True,
                stream_probe_status="verified",
                tools_ready=True,
                tool_probe_status="verified",
                vision_ready=True,
                vision_probe_status="verified",
                capability_evidence=[
                    ProviderCapabilityEvidence(
                        name="streaming",
                        declared=True,
                        observed=True,
                        state="verified",
                    )
                ],
            ),
        ),
    ):
        response = client.post(
            "/provider/test",
            json={
                "workspace_id": workspace_id,
                "provider": provider_payload,
                "api_key": "sk-test",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["streaming_ready"] is True
    assert payload["tools_ready"] is False
    assert payload["vision_ready"] is False
    assert payload["thinking_ready"] is False
    assert payload["capability_evidence"] == [
        {
            "name": "streaming",
            "declared": True,
            "observed": True,
            "state": "verified",
        }
    ]
    assert "sk-test" not in str(payload)
    recovered = (
        client.get(f"/memory/summary?workspace_id={workspace_id}").json().get("memory") or {}
    ).get("workspace", {}).get("latest_provider_capability") or {}
    assert recovered.get("ok") is True
    assert recovered.get("streaming_ready") is True
    assert recovered.get("tools_ready") is not True
    assert "sk-test" not in str(recovered)
    assert "api_key" not in recovered
    assert "apiKey" not in recovered


def test_provider_test_route_failed_test_clears_prior_success_chips(tmp_path: Path) -> None:
    provider_payload = {
        "name": "sticky-provider",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.sticky",
        "model": "ToolModel",
    }
    workspace_id = "workspace-sticky-chips"
    success = ProviderTestResponse(
        ok=True,
        detail="Provider reachable.",
        provider_reachable=True,
        model_supported=True,
        tools_ready=True,
        tool_probe_status="verified",
        capability_evidence=[
            ProviderCapabilityEvidence(
                name="tools",
                declared=True,
                observed=True,
                state="verified",
            )
        ],
    )
    failure = ProviderTestResponse(
        ok=False,
        detail="Authentication failed.",
        error_category="invalid_key_or_permission",
        provider_reachable=False,
        model_supported=False,
        tools_ready=True,
        tool_probe_status="verified",
        capability_evidence=[
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
                    "provider": provider_payload,
                    "api_key": "sk-test",
                },
            )
        assert first.status_code == 200
        assert first.json()["tools_ready"] is True
        with patch.object(ProviderService, "test", autospec=True, return_value=failure):
            second = client.post(
                "/provider/test",
                json={
                    "workspace_id": workspace_id,
                    "provider": provider_payload,
                    "api_key": "sk-test",
                },
            )
        assert second.status_code == 200
        payload = second.json()
        assert payload["ok"] is False
        assert payload["tools_ready"] is False
        assert payload["capability_evidence"] == []
        assert "sk-test" not in str(payload)
        recovered = (
            client.get(f"/memory/summary?workspace_id={workspace_id}").json().get("memory") or {}
        ).get("workspace", {}).get("latest_provider_capability") or {}
        assert recovered.get("ok") is not True
        assert recovered.get("tools_ready") is not True
        assert recovered.get("capability_evidence") in (None, [])
        runtime = client.app.state.runtime
        assert runtime.provider_connection_verified(runtime.provider_service) is False
        for service in (
            runtime.provider_service,
            *runtime.provider_service_cache.values(),
        ):
            assert runtime.provider_capability_state_for(service, "tools") != "verified"


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
        tools_ready=True,
        tool_probe_status="verified",
        capability_evidence=[
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

