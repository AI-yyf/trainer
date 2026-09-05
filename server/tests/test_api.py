from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.api.routers import _resolve_agent_loop_enabled
from app.core.models import (
    CoachingAdaptationProfile,
    EvaluationCheck,
    EvaluationReport,
    LearningPlan,
    MessageAttachment,
    PlanStage,
    ProviderConfig,
    ProviderModelsResponse,
    ProviderTestResponse,
    ResourceComposerIntent,
    ResourceRecord,
    TeachingKnowledgeAsset,
    TrainingCardCandidateSnapshot,
    TurnRequest,
    WorkspaceUnderstandingSnapshot,
)
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.network_fetch import ControlledFetchResponse


def build_client(tmp_path: Path, *, configure_provider: bool = True) -> TestClient:
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
    if configure_provider:
        provider = ProviderConfig(
            name="test-openai-compatible",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={
                "chat": True,
                "responses": True,
                "vision": False,
                "embeddings": True,
                "tools": False,
                "json_schema": False,
                "streaming": True,
            },
        )
        runtime = app.state.runtime
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()
        seed_verified_capabilities(runtime, provider, "sk-test", tools=False)
    return TestClient(app)


def test_health_check_initializes_database(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["initialized"] is True
    assert payload["database_path"].endswith("trainer-test.db")


def test_provider_test_preserves_explicit_protocol_and_profile_fields(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_test(
        self: ProviderService,
        provider: ProviderConfig,
        api_key: str | None,
        **_: object,
    ) -> ProviderTestResponse:
        captured["provider"] = provider
        captured["api_key"] = api_key
        return ProviderTestResponse(
            ok=True,
            detail="connected",
            diagnostics=["mocked"],
            provider_reachable=True,
            model_supported=True,
        )

    with patch.object(ProviderService, "test", fake_test):
        with build_client(tmp_path, configure_provider=False) as client:
            response = client.post(
                "/provider/test",
                json={
                    "apiKey": "sk-test",
                    "provider": {
                        "name": "MiniMax Gateway",
                        "label": "MiniMax Anthropic",
                        "protocol": "anthropic_messages",
                        "baseUrl": "http://minimax.redfast.top",
                        "apiKeyRef": "trainer.minimax",
                        "model": "MiniMax-M3",
                        "credentialMode": "workspace_secret",
                        "availableModels": ["MiniMax-M3"],
                        "modelAliases": {"coach-fast": "MiniMax-M3"},
                        "taskBindings": {"coach_reply": {"alias": "coach-fast"}},
                        "requestDefaults": {"max_tokens": 1024},
                        "capabilities": {
                            "chat": True,
                            "responses": False,
                            "vision": True,
                            "embeddings": False,
                            "tools": True,
                            "jsonSchema": False,
                            "structuredOutput": False,
                            "streaming": True,
                        },
                    },
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["protocol"] == "anthropic_messages"
    assert payload["protocol_family"] == "anthropic"
    provider = captured["provider"]
    assert isinstance(provider, ProviderConfig)
    assert provider.name == "MiniMax Gateway"
    assert provider.protocol == "anthropic_messages"
    assert provider.credential_mode == "workspace_secret"
    assert provider.available_models == ["MiniMax-M3"]
    assert provider.model_aliases["coach-fast"] == "MiniMax-M3"
    assert provider.task_bindings["coach_reply"]["alias"] == "coach-fast"
    assert provider.capabilities.structured_output is False


def test_provider_test_blocks_denied_model_before_live_probe(tmp_path: Path) -> None:
    provider_payload = {
        "name": "model-policy-provider",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.model-policy",
        "model": "  MiniMax-M3  ",
        "allowedModels": ["minimax-m3"],
        "deniedModels": [" MINIMAX-M3 "],
    }

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(ProviderService, "test", autospec=True) as provider_test,
    ):
        response = client.post(
            "/provider/test",
            json={
                "provider": provider_payload,
                "apiKey": "sk-test",
                "responseLanguage": "zh-CN",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "model_denied"
    assert payload["error_category"] == "model_denied"
    assert payload["model_supported"] is False
    assert payload["detail"] == (
        "\u5f53\u524d\u8fde\u63a5\u5df2\u7981\u6b62\u4f7f\u7528\u6a21\u578b\u300cMiniMax-M3\u300d\u3002"
        "\u8bf7\u4ece\u6a21\u578b\u5217\u8868\u4e2d\u66f4\u6362\u4e00\u4e2a\u540e\u518d\u8bd5\u3002"
    )
    provider_test.assert_not_called()


def test_provider_test_keeps_empty_allow_list_unrestricted(tmp_path: Path) -> None:
    provider_payload = {
        "name": "model-policy-provider",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.model-policy",
        "model": "AnyModel",
        "allowedModels": [],
        "deniedModels": [],
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
            ),
        ) as provider_test,
    ):
        response = client.post(
            "/provider/test",
            json={"provider": provider_payload, "apiKey": "sk-test"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "connected"
    provider_test.assert_called_once()


def test_provider_models_keeps_model_free_discovery_path(tmp_path: Path) -> None:
    provider_payload = {
        "name": "model-policy-provider",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.model-policy",
        "allowedModels": ["approved-model"],
        "deniedModels": ["blocked-model"],
    }

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "list_models",
            autospec=True,
            return_value=ProviderModelsResponse(
                ok=True,
                detail="Provider reachable.",
                available_models=["approved-model"],
                listed=True,
            ),
        ) as list_models,
    ):
        response = client.post(
            "/provider/models",
            json={"provider": provider_payload, "apiKey": "sk-test"},
        )

    assert response.status_code == 200
    assert response.json()["available_models"] == ["approved-model"]
    list_models.assert_called_once()


@pytest.mark.parametrize(
    ("path", "is_turn"),
    [
        ("/session/message", False),
        ("/turn", True),
        ("/session/message/stream", False),
        ("/turn/stream", True),
    ],
)
def test_coaching_routes_block_models_outside_the_allow_list(
    tmp_path: Path,
    path: str,
    is_turn: bool,
) -> None:
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        provider = runtime.provider_config.model_copy(
            update={
                "model": "BlockedModel",
                "allowed_models": ["approved-model"],
                "denied_models": [],
            }
        )
        runtime.provider_config = provider
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()

        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": f"workspace-model-policy-{path.replace('/', '-')}",
                "workspace_name": "trainer-model-policy",
            },
        )
        assert start_response.status_code == 200
        request_payload = {
            "session_id": start_response.json()["session_id"],
            "message": "Help me make the next small change.",
            "responseLanguage": "zh-CN",
        }
        if is_turn:
            request_payload["intent"] = "coach"

        with (
            patch.object(ProviderService, "coaching_reply", new=AsyncMock()) as coaching_reply,
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(),
            ) as coaching_reply_agentic,
            patch.object(
                ProviderService,
                "coaching_reply_stream",
                new=AsyncMock(),
            ) as coaching_reply_stream,
            patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=AsyncMock(),
            ) as coaching_reply_agentic_stream,
        ):
            response = client.post(path, json=request_payload)

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "\u5f53\u524d\u9009\u62e9\u7684\u6a21\u578b\u300cBlockedModel\u300d"
        "\u4e0d\u5728\u6b64\u8fde\u63a5\u5141\u8bb8\u4f7f\u7528\u7684\u6a21\u578b\u5217\u8868\u4e2d\u3002"
        "\u8bf7\u4ece\u5217\u8868\u4e2d\u9009\u62e9\u4e00\u4e2a\u6a21\u578b\u540e\u518d\u8bd5\u3002"
    )
    coaching_reply.assert_not_called()
    coaching_reply_agentic.assert_not_called()
    coaching_reply_stream.assert_not_called()
    coaching_reply_agentic_stream.assert_not_called()


def test_turn_request_accepts_use_agent_loop_snake_case_and_alias() -> None:
    snake_case = TurnRequest.model_validate(
        {
            "message": "hello",
            "use_agent_loop": False,
        }
    )
    camel_case = TurnRequest.model_validate(
        {
            "message": "hello",
            "useAgentLoop": True,
        }
    )

    assert snake_case.use_agent_loop is False
    assert camel_case.use_agent_loop is True


def test_agent_loop_default_requires_explicit_or_typed_tool_input() -> None:
    service = ProviderService(
        config=ProviderConfig(
            name="tool-capable-provider",
            base_url="https://provider.example/v1",
            api_key_ref="trainer.test",
            model="tool-model",
            capabilities={"chat": True, "tools": True, "streaming": True},
        ),
        api_key="sk-test",
    )
    plain_request = TurnRequest(message="Explain Python closures in three sentences.")
    attachment_request = TurnRequest(
        message="Explain this image.",
        attachments=[MessageAttachment(id="attachment-1")],
    )
    resource_request = TurnRequest(
        message="Search my resources.",
        resource_composer_intent=ResourceComposerIntent(mode="locate"),
    )
    explicit_request = TurnRequest(message="Use tools for this.", use_agent_loop=True)
    plan_view_request = TurnRequest(message="Explain the current stage.", active_view="plan")
    training_view_request = TurnRequest(message="Why is this answer wrong?", active_view="training")
    formal_plan_request = TurnRequest(
        message="Create the formal plan after we agree on the scope.",
        intent="plan",
        formal_plan_mutation=True,
    )
    disabled_request = TurnRequest(
        message="Keep this direct.",
        attachments=[MessageAttachment(id="attachment-1")],
        use_agent_loop=False,
    )

    for stream in (False, True):
        assert _resolve_agent_loop_enabled(plain_request, service, stream=stream) is False
        assert _resolve_agent_loop_enabled(attachment_request, service, stream=stream) is True
        # Resources/library composer turns use the managed-sandbox agent loop.
        # Learner project writes stay denied; sandbox library work is the write surface.
        assert _resolve_agent_loop_enabled(resource_request, service, stream=stream) is True
        assert _resolve_agent_loop_enabled(explicit_request, service, stream=stream) is True
        assert _resolve_agent_loop_enabled(plan_view_request, service, stream=stream) is True
        assert _resolve_agent_loop_enabled(training_view_request, service, stream=stream) is False
        assert _resolve_agent_loop_enabled(formal_plan_request, service, stream=stream) is True
        # An explicit false flag cannot downgrade an attachment into plain
        # chat; otherwise the file would be accepted without being delivered.
        assert _resolve_agent_loop_enabled(disabled_request, service, stream=stream) is True


def test_provider_test_infers_tool_capabilities_from_declared_protocol(tmp_path: Path) -> None:
    captured: dict[str, ProviderConfig] = {}

    def fake_test(
        self: ProviderService,
        provider: ProviderConfig,
        api_key: str | None,
        **_: object,
    ) -> ProviderTestResponse:
        captured["provider"] = provider
        return ProviderTestResponse(
            ok=True,
            detail="connected",
            diagnostics=["mocked"],
            provider_reachable=True,
            model_supported=True,
        )

    with patch.object(ProviderService, "test", fake_test):
        with build_client(tmp_path, configure_provider=False) as client:
            response = client.post(
                "/provider/test",
                json={
                    "apiKey": "sk-test",
                    "provider": {
                        "name": "MiniMax Gateway",
                        "api": "anthropic",
                        "baseUrl": "http://minimax.redfast.top",
                        "apiKeyRef": "trainer.minimax",
                        "model": "MiniMax-M3",
                    },
                },
            )

    assert response.status_code == 200
    payload = response.json()
    provider = captured["provider"]
    assert payload["protocol"] == "anthropic_messages"
    assert payload["protocol_family"] == "anthropic"
    assert provider.capabilities.tools is True
    assert provider.capabilities.streaming is True
    assert provider.capabilities.vision is True
    assert payload["tools_ready"] is False
    assert payload["capability_evidence"] == []


def test_provider_test_keeps_minimal_preview_override_chat_only(tmp_path: Path) -> None:
    captured: dict[str, ProviderConfig] = {}

    def fake_test(
        self: ProviderService,
        provider: ProviderConfig,
        api_key: str | None,
        **_: object,
    ) -> ProviderTestResponse:
        captured["provider"] = provider
        return ProviderTestResponse(
            ok=True,
            detail="connected",
            diagnostics=["mocked"],
            provider_reachable=True,
            model_supported=True,
        )

    with patch.object(ProviderService, "test", fake_test):
        with build_client(tmp_path, configure_provider=False) as client:
            response = client.post(
                "/provider/test",
                json={
                    "apiKey": "sk-test",
                    "provider": {
                        "name": "preview-provider",
                        "baseUrl": "https://api.openai.com/v1",
                        "model": "gpt-4o-mini",
                    },
                },
            )

    assert response.status_code == 200
    provider = captured["provider"]
    assert provider.protocol == "openai_chat_completions_compatible"
    assert provider.capabilities.chat is True
    assert provider.capabilities.streaming is True
    assert provider.capabilities.tools is False
    assert provider.capabilities.structured_output is False


def test_session_message_provider_override_protocol_matrix_routes_to_agent_loop(
    tmp_path: Path,
) -> None:
    captured: dict[str, list[dict[str, object]]] = {"calls": []}

    class FakeAgentProvider:
        def __init__(self, protocol: str) -> None:
            self.protocol = protocol

        async def call(
            self,
            messages: list[dict[str, object]],
            tools: list[dict[str, object]] | None,
        ) -> dict[str, object]:
            captured["calls"].append(
                {
                    "protocol": self.protocol,
                    "messages": messages,
                    "tools": tools or [],
                }
            )
            return {
                "content": f"{self.protocol} coach reply: learn first, then verify one step.",
                "tool_calls": [],
            }

        async def call_stream(
            self,
            messages: list[dict[str, object]],
            tools: list[dict[str, object]] | None,
        ):  # type: ignore[no-untyped-def]
            result = await self.call(messages, tools)
            yield {
                "type": "final",
                "content": result["content"],
                "tool_calls": [],
                "stop_reason": "stop",
            }

    def fake_build_agent_provider(
        self: ProviderService,
        **kwargs: object,
    ) -> tuple[object, object]:
        protocol = str(kwargs.get("protocol") or getattr(self._config, "protocol", ""))  # noqa: SLF001
        provider = FakeAgentProvider(protocol)
        return provider, provider

    protocol_payloads = [
        (
            "openai_chat_completions",
            "openai",
            "https://api.openai.com/v1",
            "gpt-4o-mini",
        ),
        (
            "openai_chat_completions_compatible",
            "openai-compatible",
            "https://gateway.example/v1",
            "MiniMax-M3",
        ),
        (
            "openai_responses",
            "responses",
            "https://api.openai.com/v1",
            "gpt-5.1-mini",
        ),
        (
            "anthropic_messages",
            "anthropic",
            "http://minimax.redfast.top",
            "MiniMax-M3",
        ),
        (
            "gemini_generate_content",
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            "gemini-2.0-flash",
        ),
    ]

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "build_agent_provider",
            autospec=True,
            side_effect=fake_build_agent_provider,
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-protocol-matrix",
                "workspace_name": "Protocol Matrix",
                "profile": {
                    "long_term_goal": "verify provider protocols",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200, start_response.text
        session_id = start_response.json()["session_id"]

        for expected_protocol, api_alias, base_url, model in protocol_payloads:
            override_provider = ProviderConfig(
                name=f"{expected_protocol}-provider",
                base_url=base_url,
                api_key_ref=f"trainer.{expected_protocol}",
                model=model,
                protocol=expected_protocol,
                capabilities={"tools": True, "streaming": True},
            )
            seed_verified_capabilities(
                client.app.state.runtime,
                override_provider,
                "sk-test",
                tools=True,
            )
            response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-protocol-matrix",
                    "message": f"Teach a tiny debug loop with {expected_protocol}.",
                    "response_language": "en-US",
                    "useAgentLoop": True,
                    "apiKey": "sk-test",
                    "provider": {
                        "name": f"{expected_protocol}-provider",
                        "api": api_alias,
                        "baseUrl": base_url,
                        "apiKeyRef": f"trainer.{expected_protocol}",
                        "model": model,
                        "capabilities": {"tools": True, "streaming": True},
                    },
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["reply"]["content"].startswith(expected_protocol)
            assert payload["agent_meta"]["agentic"] is True
            assert payload["agent_meta"]["stop_reason"] == "completed"

    seen_protocols = [str(item["protocol"]) for item in captured["calls"]]
    assert seen_protocols == [item[0] for item in protocol_payloads]
    for call in captured["calls"]:
        protocol = str(call["protocol"])
        tools = call["tools"]
        assert isinstance(tools, list)
        assert tools, f"{protocol} should expose coach tools to the agent loop"
        first_tool = tools[0]
        assert isinstance(first_tool, dict)
        if protocol in {"openai_chat_completions", "openai_chat_completions_compatible"}:
            assert first_tool["type"] == "function"
            assert first_tool["function"]["name"] == "search_resources"  # type: ignore[index]
        elif protocol == "openai_responses":
            assert first_tool["type"] == "function"
            assert first_tool["name"] == "search_resources"
        elif protocol == "anthropic_messages":
            assert first_tool["name"] == "search_resources"
            assert "input_schema" in first_tool
        elif protocol == "gemini_generate_content":
            assert first_tool["name"] == "search_resources"
            assert "parameters" in first_tool


def test_turn_provider_override_uses_agent_loop_for_coach_requests(
    tmp_path: Path,
) -> None:
    captured: dict[str, list[dict[str, object]]] = {"calls": []}

    class FakeAgentProvider:
        def __init__(self, protocol: str) -> None:
            self.protocol = protocol

        async def call(
            self,
            messages: list[dict[str, object]],
            tools: list[dict[str, object]] | None,
        ) -> dict[str, object]:
            captured["calls"].append(
                {
                    "protocol": self.protocol,
                    "messages": messages,
                    "tools": tools or [],
                }
            )
            return {
                "content": f"{self.protocol} coach reply: learn first, then verify one step.",
                "tool_calls": [],
            }

        async def call_stream(
            self,
            messages: list[dict[str, object]],
            tools: list[dict[str, object]] | None,
        ):  # type: ignore[no-untyped-def]
            result = await self.call(messages, tools)
            yield {
                "type": "final",
                "content": result["content"],
                "tool_calls": [],
                "stop_reason": "stop",
            }

    def fake_build_agent_provider(
        self: ProviderService,
        **kwargs: object,
    ) -> tuple[object, object]:
        protocol = str(kwargs.get("protocol") or getattr(self._config, "protocol", ""))  # noqa: SLF001
        provider = FakeAgentProvider(protocol)
        return provider, provider

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "build_agent_provider",
            autospec=True,
            side_effect=fake_build_agent_provider,
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-turn-agentic-override",
                "workspace_name": "Turn Agentic Override",
                "profile": {
                    "long_term_goal": "verify /turn agent loop parity",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200, start_response.text
        session_id = start_response.json()["session_id"]
        override_provider = ProviderConfig(
            name="anthropic-turn-provider",
            base_url="http://minimax.redfast.top",
            api_key_ref="trainer.anthropic.turn",
            model="MiniMax-M3",
            protocol="anthropic_messages",
            capabilities={"tools": True, "streaming": True},
        )
        seed_verified_capabilities(
            client.app.state.runtime,
            override_provider,
            "sk-test",
            tools=True,
        )

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-turn-agentic-override",
                "intent": "coach",
                "message": "Teach a tiny debug loop with anthropic messages.",
                "response_language": "en-US",
                "use_agent_loop": True,
                "apiKey": "sk-test",
                "provider": {
                    "name": "anthropic-turn-provider",
                    "api": "anthropic",
                    "baseUrl": "http://minimax.redfast.top",
                    "apiKeyRef": "trainer.anthropic.turn",
                    "model": "MiniMax-M3",
                    "capabilities": {"tools": True, "streaming": True},
                },
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["reply"]["content"].startswith("anthropic_messages coach reply")
    assert payload["agent_meta"]["agentic"] is True
    assert payload["agent_meta"]["stop_reason"] == "completed"
    assert payload["coach_turn"]["scenario"] == "debug_loop"
    assert captured["calls"], "expected /turn to invoke the agent loop"
    assert captured["calls"][0]["protocol"] == "anthropic_messages"


def test_session_message_minimal_provider_override_stays_plain_chat(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    async def fake_coaching_reply(
        self: ProviderService,
        profile: object,
        message: str,
        *args: object,
        **kwargs: object,
    ) -> str:
        captured["plain_protocol"] = getattr(self._config, "protocol", None)  # noqa: SLF001
        captured["plain_tools"] = getattr(self._config.capabilities, "tools", None)  # noqa: SLF001
        return "Plain preview reply."

    def fail_build_agent_provider(self: ProviderService, **_: object) -> tuple[object, object]:
        raise AssertionError("Minimal preview provider should not enter the agent loop")

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(ProviderService, "coaching_reply", autospec=True, side_effect=fake_coaching_reply),
        patch.object(ProviderService, "build_agent_provider", autospec=True, side_effect=fail_build_agent_provider),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-preview-plain",
                "workspace_name": "Preview Plain",
                "profile": {
                    "long_term_goal": "keep preview provider honest",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200, start_response.text
        override_provider = ProviderConfig(
            name="preview-provider",
            base_url="https://gateway.example/v1",
            api_key_ref="",
            model="preview-model",
            capabilities={"tools": False, "streaming": True},
        )
        seed_verified_capabilities(
            client.app.state.runtime,
            override_provider,
            "sk-test",
            tools=False,
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": start_response.json()["session_id"],
                "workspace_id": "workspace-preview-plain",
                "message": "Give me a tiny function guidance hint.",
                "response_language": "en-US",
                "apiKey": "sk-test",
                "provider": {
                    "name": "preview-provider",
                    "baseUrl": "https://gateway.example/v1",
                    "model": "preview-model",
                    "capabilities": {"tools": False, "streaming": True},
                },
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["reply"]["content"] == "Plain preview reply."
    assert payload.get("agent_meta") is None
    assert captured["plain_protocol"] == "openai_chat_completions_compatible"
    assert captured["plain_tools"] is False


def test_session_and_plan_flow(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "user_profile": {
                    "long_term_goals": ["Build a document Q&A trainer"],
                    "weekly_hours": 6,
                    "allow_direct_answers": False,
                    "focus_libraries": ["fastapi", "transformers"],
                },
                "workspace_context": {
                    "workspace_id": "workspace-1",
                    "name": "trainer",
                    "root_path": "F:/trainer",
                    "language": "python",
                },
                "initial_message": "I want to practice with tight feedback loops.",
            },
        )
        assert start_response.status_code == 200
        start_payload = start_response.json()
        session_id = start_payload["session_id"]
        assert start_payload["stage"] == "intake"
        assert start_payload["messages"][0]["role"] == "user"
        assert start_payload["messages"][0]["content"] == "I want to practice with tight feedback loops."
        assert any(message["role"] == "assistant" for message in start_payload["messages"])

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Please help me break the first milestone into steps.",
            },
        )
        assert message_response.status_code == 200
        message_payload = message_response.json()
        assert message_payload["reply"]["role"] == "assistant"
        assert message_payload["reply"]["content"]
        assert message_payload["suggested_actions"][0]["action"] in {"plan", "task", "review", "hint"}
        assert "snapshot" in message_payload
        assert "coach_turn" in message_payload
        assert "artifacts" in message_payload
        assert message_payload["reply"]["metadata"]["artifacts"]
        rich_artifact = message_payload["reply"]["metadata"]["artifacts"][0]
        assert rich_artifact["title"]
        assert rich_artifact["summary"]
        assert rich_artifact["recommended_action"] in {"plan", "task", "review", "hint"}
        assert "coach_focus" in message_payload["reply"]["metadata"]
        assert "coach_turn" in message_payload["reply"]["metadata"]

        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": ["Ship the first vertical slice of the trainer"],
                "constraints": ["Keep the UI dialogue-first", "Reuse existing tooling"],
            },
        )
        assert plan_response.status_code == 200
        plan_payload = plan_response.json()
        plan_id = plan_payload["plan"]["plan_id"]
        assert plan_payload["plan"]["session_id"] == session_id
        assert len(plan_payload["plan"]["phases"]) == 3
        assert plan_payload["diagnostics"]
        runtime_status = plan_payload["plan_runtime_status"]
        assert runtime_status["current_stage"]["title"]
        assert runtime_status["current_main_thread"]["focus_area"]
        assert "summary" in runtime_status["coach_judgment"]
        assert runtime_status["next_training_action"]
        assert runtime_status["current_step"]
        assert runtime_status["why_now"]
        assert isinstance(runtime_status["verify_method"], list)
        if runtime_status["review_points"]:
            review_point = runtime_status["review_points"][0]
            assert "surface_mode" in review_point
            assert "task_hint" in review_point
            assert "focus_area" in review_point
            assert "linked_context" in review_point

        update_response = client.post(
            "/plan/update",
            json={
                "plan_id": plan_id,
                "frozen": True,
                "weekly_cadence": "8 hours per week",
            },
        )
        assert update_response.status_code == 200
        updated_plan = update_response.json()["plan"]
        assert updated_plan["frozen"] is True
        assert updated_plan["weekly_cadence"] == "8 hours per week"
        assert "current_step" in updated_plan
        assert "why_now" in updated_plan


def test_session_start_persists_first_look_summary(tmp_path: Path) -> None:
    project_dir = tmp_path / "first-look-workspace"
    project_dir.mkdir()

    with build_client(tmp_path) as client:
        response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-first-look",
                "workspace_name": "first-look",
                "workspace_path": str(project_dir),
            },
        )

    assert response.status_code == 200
    payload = response.json()
    first_look = payload["memory"]["workspace_understanding"]["firstLookSummary"]
    assert first_look["folder_role"] == "empty_new_project"
    assert first_look["classification_method"] == "heuristic"
    assert "scaffold" in first_look["recommended_next_step"].lower()


def test_session_start_persists_first_look_from_remote_snapshot(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-remote-first-look",
                "workspace_name": "RAP remote",
                "workspace_path": "/mnt/vdb1/yunfei.yan/RAP",
                "remote_name": "ssh-remote",
                "force_new": True,
                "workspace_file_snapshot": {
                    "is_remote": True,
                    "files": [
                        {"path": "README.md"},
                        {"path": "setup.py"},
                        {"path": "requirements.txt"},
                        {"path": "navsim/agents/abstract_agent.py"},
                    ],
                },
            },
        )
    assert response.status_code == 200, response.text
    first_look = response.json()["memory"]["workspace_understanding"]["firstLookSummary"]
    assert first_look["folder_role"] != "empty_new_project"
    assert first_look["folder_role"] in {"existing_engineering", "algorithm_model"}


def test_session_start_remote_without_snapshot_is_not_empty_new_project(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-remote-no-snapshot",
                "workspace_name": "Remote",
                "workspace_path": "/mnt/vdb1/yunfei.yan/RAP",
                "remote_name": "ssh-remote",
                "force_new": True,
            },
        )
    assert response.status_code == 200, response.text
    first_look = response.json()["memory"]["workspace_understanding"]["firstLookSummary"]
    assert first_look["folder_role"] == "mixed_uncertain"


def test_session_start_localizes_heuristic_first_look_for_chinese(tmp_path: Path) -> None:
    project_dir = tmp_path / "first-look-chinese-workspace"
    project_dir.mkdir()

    with build_client(tmp_path) as client:
        response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-first-look-chinese",
                "workspace_name": "first-look-chinese",
                "workspace_path": str(project_dir),
                "response_language": "zh-CN",
            },
        )

    assert response.status_code == 200
    first_look = response.json()["memory"]["workspace_understanding"]["firstLookSummary"]
    assert first_look["why_this_guess"] == "目录为空或文件很少，适合作为新项目的起点。"
    assert first_look["recommended_next_step"] == "先搭建新项目的第一个最小功能。"
    assert "scaffold" not in first_look["recommended_next_step"].lower()


def test_session_start_accepts_coach_first_answer_policy_alias(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-answer-policy-alias",
                "workspace_name": "trainer-answer-policy-alias",
                "profile": {
                    "long_term_goal": "Keep coach-first answer policy aliases truthful",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "coach-first",
                },
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["profile"]["answer_policy"] == "guided"
    assert payload["memory"]["profile"]["answer_policy"] == "guided"


def test_session_start_invalid_answer_policy_returns_422(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-answer-policy-invalid",
                "workspace_name": "trainer-answer-policy-invalid",
                "profile": {
                    "long_term_goal": "Reject invalid answer policy values cleanly",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "not-a-real-mode",
                },
            },
        )

    assert response.status_code == 422
    payload = response.json()
    assert isinstance(payload.get("detail"), list)
    assert any(
        isinstance(item, dict) and [*item.get("loc", [])][-2:] == ["profile", "answer_policy"]
        for item in payload["detail"]
    )


def test_plan_generate_without_objectives_uses_first_look_summary(tmp_path: Path) -> None:
    project_dir = tmp_path / "first-look-plan"
    project_dir.mkdir()

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-first-look-plan",
                "workspace_name": "first-look-plan",
                "workspace_path": str(project_dir),
            },
        )
        session_id = start_response.json()["session_id"]
        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": [],
                "constraints": [],
            },
        )

    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    assert "scaffold a new project" in plan_payload["plan"]["title"].lower()


def test_task_next_without_focus_uses_first_look_summary(tmp_path: Path) -> None:
    project_dir = tmp_path / "first-look-task"
    project_dir.mkdir()

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-first-look-task",
                "workspace_name": "first-look-task",
                "workspace_path": str(project_dir),
            },
        )
        session_id = start_response.json()["session_id"]
        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": ["Use first-look summary under a live plan"],
            },
        )
        assert plan_response.status_code == 200, plan_response.text
        plan_id = str(
            (plan_response.json().get("plan") or plan_response.json()).get("id")
            or (plan_response.json().get("plan") or plan_response.json()).get("plan_id")
            or ""
        ).strip()
        assert plan_id
        task_response = client.post(
            "/task/next",
            json={
                "session_id": session_id,
            },
        )

    assert task_response.status_code == 200
    task_payload = task_response.json()
    assert task_payload["id"]
    assert task_payload["title"]
    assert str((task_payload.get("metadata") or {}).get("plan_id") or "").strip() == plan_id
    # Live plan may surface due-review/stage over first-look invent; plan_id must stay bound.


def test_session_message_updates_plan_lifecycle(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-lifecycle",
                "workspace_name": "trainer-plan-lifecycle",
                "profile": {
                    "long_term_goal": "Keep the plan lifecycle updating",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": ["Ship a visible plan loop"],
                "constraints": ["Keep it small"],
            },
        )
        assert plan_response.status_code == 200
        plan_payload = plan_response.json()["plan"]
        assert plan_payload["current_step"]
        assert plan_payload["why_now"]

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Please help me verify the current step and then tell me the next move.",
            },
        )
        assert message_response.status_code == 200
        message_payload = message_response.json()
        runtime_status = message_payload["snapshot"]["plan_runtime_status"]
        assert runtime_status["current_step"]
        assert runtime_status["why_now"]
        assert "verify_method" in runtime_status
        assert "next_after_current" in runtime_status


def test_provider_test_without_api_key_is_graceful(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/provider/test",
            json={
                "provider": {
                    "name": "local-openai-compatible",
                    "base_url": "http://localhost:1234/v1",
                    "api_key_ref": "trainer.default",
                    "model": "demo-model",
                    "capabilities": {
                        "chat": True,
                        "responses": True,
                        "vision": False,
                        "embeddings": True,
                        "tools": False,
                        "json_schema": False,
                        "streaming": True,
                    },
                }
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["configured"] is True
    assert payload["api_key_supplied"] is False
    assert payload["reachable"] is False
    assert payload["success"] is False
    assert payload["status"] == "missing_api_key"
    assert payload["error_category"] == "missing_api_key"
    assert payload["provider_name"] == "local-openai-compatible"
    assert "no api key" in payload["detail"].lower()
    assert any("skipped" in item.lower() or "no api key" in item.lower() for item in payload["diagnostics"])


def test_provider_test_rejects_newapi_type_alias_as_protocol(tmp_path: Path) -> None:
    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(ProviderService, "test", autospec=True) as test_mock,
    ):
        response = client.post(
            "/provider/test",
            json={
                "provider": {
                    "name": "NewAPI MiniMax",
                    "base_url": "http://example.invalid/v1",
                    "api_key_ref": "trainer.newapi",
                    "model": "MiniMax-M3",
                    "_type": "newapi_channel_conn",
                },
                "api_key": "sk-test",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "unknown_protocol"
    assert payload["error_category"] == "unknown_protocol"
    assert payload["connection_type"] == "newapi_channel_conn"
    test_mock.assert_not_called()


def test_memory_settings_rejects_unknown_response_language(tmp_path: Path) -> None:
    with build_client(tmp_path, configure_provider=False) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-invalid-response-language",
                "workspace_name": "invalid-language",
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/memory/settings",
            json={"session_id": session_id, "response_language": "xx"},
        )
        assert response.status_code == 422

        summary = client.get("/memory/summary", params={"session_id": session_id})
        assert summary.status_code == 200
        assert (summary.json()["memory"]["workspace"].get("response_language") or "") != "xx"


@pytest.mark.parametrize(
    "workspace_id",
    ["../escape", "nested/./workspace", "nested/workspace", "workspace-\x00id"],
)
def test_session_start_rejects_relative_or_unsafe_workspace_ids(
    tmp_path: Path,
    workspace_id: str,
) -> None:
    with build_client(tmp_path, configure_provider=False) as client:
        response = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "unsafe"},
        )

    assert response.status_code == 422


def test_session_start_accepts_absolute_windows_workspace_alias(tmp_path: Path) -> None:
    with build_client(tmp_path, configure_provider=False) as client:
        response = client.post(
            "/session/start",
            json={
                "workspace_id": r"C:\\trainer\\legacy-project",
                "workspace_name": "legacy-project",
            },
        )

    assert response.status_code == 200


def test_provider_test_without_api_key_localizes_chinese_detail(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/provider/test",
            json={
                "response_language": "zh-CN",
                "provider": {
                    "name": "local-openai-compatible",
                    "base_url": "http://localhost:1234/v1",
                    "api_key_ref": "trainer.default",
                    "model": "demo-model",
                    "capabilities": {
                        "chat": True,
                        "responses": True,
                        "vision": False,
                        "embeddings": True,
                        "tools": False,
                        "json_schema": False,
                        "streaming": True,
                    },
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "missing_api_key"
    assert payload["detail"] == (
        "provider 设置已经保存，但还没有可用的 API key。补上之后 Trainer 才能继续工作。"
    )


def test_provider_test_incomplete_config_is_not_treated_as_success(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/provider/test",
            json={
                "provider": {
                    "name": "broken-provider",
                    "base_url": "",
                    "api_key_ref": "trainer.default",
                    "model": "",
                    "capabilities": {
                        "chat": True,
                        "responses": True,
                        "vision": False,
                        "embeddings": True,
                        "tools": False,
                        "json_schema": False,
                        "streaming": True,
                    },
                },
                "api_key": "sk-test",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["configured"] is False
    assert payload["api_key_supplied"] is True
    assert payload["reachable"] is False
    assert payload["success"] is False
    assert payload["status"] == "incomplete"
    assert "incomplete" in payload["detail"].lower()
    assert any("configuration incomplete" in item.lower() for item in payload["diagnostics"])


def test_provider_test_incomplete_config_localizes_chinese_detail(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/provider/test",
            json={
                "responseLanguage": "zh-CN",
                "provider": {
                    "name": "broken-provider",
                    "base_url": "",
                    "api_key_ref": "trainer.default",
                    "model": "",
                    "capabilities": {
                        "chat": True,
                        "responses": True,
                        "vision": False,
                        "embeddings": True,
                        "tools": False,
                        "json_schema": False,
                        "streaming": True,
                    },
                },
                "api_key": "sk-test",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "incomplete"
    assert payload["detail"] == (
        "provider 配置还不完整。开始测试前，请先保存 provider name、base URL 和 model。"
    )


def test_session_message_requires_provider_and_api_key_before_coaching(tmp_path: Path) -> None:
    with build_client(tmp_path, configure_provider=False) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-requires-key-session-message",
                "workspace_name": "trainer-requires-key-session-message",
                "profile": {
                    "long_term_goal": "Require a provider before coaching starts",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Help me break this feature into the first thin slice.",
            },
        )

    assert response.status_code == 400
    assert "provider" in response.json()["detail"].lower()
    assert "api key" in response.json()["detail"].lower()


def test_turn_requires_provider_and_api_key_before_coaching(tmp_path: Path) -> None:
    with build_client(tmp_path, configure_provider=False) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-requires-key-turn",
                "workspace_name": "trainer-requires-key-turn",
                "profile": {
                    "long_term_goal": "Require a provider before turn execution",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "intent": "coach",
                "message": "Help me implement the first visible slice.",
            },
        )

    assert response.status_code == 400
    assert "provider" in response.json()["detail"].lower()
    assert "api key" in response.json()["detail"].lower()


def test_provider_test_accepts_camel_case_provider_payload(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/provider/test",
            json={
                "provider": {
                    "name": "camel-openai-compatible",
                    "baseUrl": "http://localhost:1234/v1",
                    "apiKeyRef": "trainer.default",
                    "model": "demo-model",
                    "capabilities": {
                        "chat": True,
                        "responses": True,
                        "vision": False,
                        "embeddings": False,
                        "tools": False,
                        "jsonSchema": False,
                        "streaming": True,
                    },
                }
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is True
    assert payload["provider_name"] == "camel-openai-compatible"
    assert payload["status"] == "missing_api_key"


def test_provider_test_surfaces_invalid_key_category_and_retryability(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        with patch(
            "app.llm.provider_service.ProviderService.test",
            return_value=ProviderTestResponse(
                ok=False,
                detail="Provider rejected the API key or permissions. Incorrect API key provided.",
                error_category="invalid_key_or_permission",
                retryable=False,
                status_code=401,
                diagnostics=["Chat probe failed.", "Incorrect API key provided."],
                provider_reachable=True,
                model_supported=None,
            ),
        ):
            response = client.post(
                "/provider/test",
                json={
                    "provider": {
                        "name": "invalid-key-provider",
                        "base_url": "https://example.com/v1",
                        "api_key_ref": "trainer.default",
                        "model": "demo-model",
                        "capabilities": {
                            "chat": True,
                            "responses": True,
                            "vision": False,
                            "embeddings": False,
                            "tools": False,
                            "json_schema": False,
                            "streaming": True,
                        },
                    },
                    "api_key": "sk-test",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "invalid_key_or_permission"
    assert payload["reachable"] is True
    assert payload["retryable"] is False
    assert payload["status_code"] == 401
    assert payload["error_category"] == "invalid_key_or_permission"


def test_provider_test_hides_upstream_gateway_reason_for_invalid_key_errors(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        with patch(
            "app.llm.provider_service.ProviderService.test",
            return_value=ProviderTestResponse(
                ok=False,
                detail=(
                    "Provider rejected the API key or permissions. Check the key, workspace/project access, "
                    "and model entitlement. Error code: 401 - {'error': {'message': '閻犲洢鍎伴幎銈夋偋瀹€鈧慨鎼佸箑娴ｉ鐟濋柛娆樺灣閺?"
                    "(request id: 2026062907515610546991244595261)', 'type': 'one_api_error'}}"
                ),
                error_category="invalid_key_or_permission",
                retryable=False,
                status_code=401,
                diagnostics=["Chat probe failed."],
                provider_reachable=True,
                model_supported=None,
            ),
        ):
            response = client.post(
                "/provider/test",
                json={
                    "provider": {
                        "name": "gateway-provider",
                        "base_url": "https://example.com/v1",
                        "api_key_ref": "trainer.default",
                        "model": "demo-model",
                        "capabilities": {
                            "chat": True,
                            "responses": True,
                            "vision": False,
                            "embeddings": False,
                            "tools": False,
                            "json_schema": False,
                            "streaming": True,
                        },
                    },
                    "api_key": "sk-test",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert (
        payload["detail"]
        == "Provider rejected the API key or permissions. Check the key, scope, and model access."
    )
    assert "request id" not in payload["detail"].lower()
    assert "request id" not in payload["detail"]


def test_session_message_surfaces_provider_auth_failure_as_blocked_turn(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-provider-auth-blocked",
                "workspace_name": "trainer-provider-auth-blocked",
                "profile": {
                    "long_term_goal": "Keep provider truth aligned with coach turns",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        failing_completion = AsyncMock(
            side_effect=Exception(
                "Error code: 401 - {'error': {'message': 'Incorrect API key provided'}}"
            )
        )
        with patch(
            "app.llm.provider_service.ProviderService._create_chat_completion",
            new=failing_completion,
        ):
            response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "message": "Help me continue this exact coaching lane.",
                    "response_language": "en-US",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_meta"]["stop_reason"] == "invalid_key_or_permission"
    assert payload["coach_turn"]["summary"] == "The provider rejected this turn's API key or permissions."
    assert payload["coach_turn"]["next_step"].startswith("Check the API key")
    assert "retest the connection" in payload["coach_turn"]["next_step"]
    assert payload["reply"]["metadata"]["coach_visible_status"]["status"] == "blocked"
    assert payload["reply"]["metadata"]["coach_visible_status"]["stopReason"] == "invalid_key_or_permission"
    assert "Trainer is blocked on the provider path" in payload["reply"]["content"]
    assert "Error code: 401" not in payload["reply"]["content"]
    assert "Incorrect API key provided" not in payload["reply"]["content"]


def test_turn_surfaces_provider_auth_failure_as_blocked_turn(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-turn-provider-auth-blocked",
                "workspace_name": "trainer-turn-provider-auth-blocked",
                "profile": {
                    "long_term_goal": "Keep turn truth aligned with provider failures",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        failing_completion = AsyncMock(
            side_effect=Exception(
                "Error code: 401 - {'error': {'message': 'Incorrect API key provided'}}"
            )
        )
        with patch(
            "app.llm.provider_service.ProviderService._create_chat_completion",
            new=failing_completion,
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-turn-provider-auth-blocked",
                    "intent": "coach",
                    "message": "Keep guiding me on this same thread.",
                    "response_language": "en-US",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_meta"]["stop_reason"] == "invalid_key_or_permission"
    assert payload["reply"]["metadata"]["coach_visible_status"]["status"] == "blocked"
    assert payload["reply"]["metadata"]["coach_visible_status"]["stopReason"] == "invalid_key_or_permission"
    assert "Error code: 401" not in payload["reply"]["content"]
    assert "Incorrect API key provided" not in payload["reply"]["content"]


def test_turn_surfaces_visible_reply_corruption_as_blocked_turn(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-turn-provider-language-corruption",
                "workspace_name": "trainer-turn-provider-language-corruption",
                "profile": {
                    "long_term_goal": "Keep reply integrity truthful",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        corrupt_choice = MagicMock()
        corrupt_choice.message.content = (
            "Glad you want to start with VS Code remote "
            "\u0431\u043a"
            " it's a great target because once the model clicks, debugging and run confi"
            "\u0431\u043d"
            " stay more stable."
        )
        corrupt_response = MagicMock()
        corrupt_response.choices = [corrupt_choice]
        with patch(
            "app.llm.provider_service.ProviderService._create_chat_completion",
            new=AsyncMock(return_value=(corrupt_response, "gpt-4o-mini")),
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-turn-provider-language-corruption",
                    "intent": "coach",
                    "message": "Keep guiding me on this same thread.",
                    "response_language": "en-US",
                },
            )
    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_meta"]["stop_reason"] == "language_corruption_recovered"
    assert "provider" in payload["coach_turn"]["summary"].lower()
    assert payload["reply"]["metadata"]["coach_visible_status"]["status"] == "degraded"
    assert payload["reply"]["metadata"]["coach_visible_status"]["stopReason"] == "language_corruption_recovered"
    assert payload["reply"]["content"]
    assert "\u0431\u043a" not in payload["reply"]["content"]
    assert "confi\u0431\u043d" not in payload["reply"]["content"]


def test_turn_localizes_language_corruption_recovery_copy_for_chinese(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-turn-provider-language-corruption-zh",
                "workspace_name": "trainer-turn-provider-language-corruption-zh",
                "profile": {
                    "long_term_goal": "Keep zh-CN recovery copy truthful",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        with patch(
            "app.llm.provider_service.ProviderService.test",
            autospec=True,
            return_value=ProviderTestResponse(
                ok=False,
                detail="?? provider ??????????????????????????",
                error_category="language_corruption",
                provider_reachable=True,
                model_supported=True,
                status_code=200,
            ),
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-turn-provider-language-corruption-zh",
                    "intent": "coach",
                    "message": "请带我理解 VS Code remote workspace boundary，先给一个可验证的 checkpoint。",
                    "response_language": "zh-CN",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "remote_workspace"
    assert payload["agent_meta"]["stop_reason"] in {
        "language_corruption",
        "language_corruption_recovered",
    }
    assert payload["reply"]["metadata"]["coach_visible_status"]["status"] in {
        "blocked",
        "degraded",
    }
    assert (
        payload["reply"]["metadata"]["coach_visible_status"]["stopReason"]
        in {"language_corruption", "language_corruption_recovered"}
    )
    assert "模型服务" in payload["coach_turn"]["summary"]
    assert "中文内容" in payload["coach_turn"]["summary"]
    assert "VS Code remote" in payload["coach_turn"]["summary"]
    assert payload["reply"]["content"]
    assert "?? provider" not in payload["reply"]["content"]
    assert "This provider is reachable" not in payload["reply"]["content"]


def test_turn_language_corruption_does_not_reuse_previous_remote_lane_for_fresh_general_turn(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-turn-language-corruption-fresh-general",
                "workspace_name": "trainer-turn-language-corruption-fresh-general",
                "profile": {
                    "long_term_goal": "Keep fresh general turns isolated from earlier remote lessons",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        visible_choice = MagicMock()
        visible_choice.message.content = (
            "Start with the remote workspace boundary. First identify whether this workspace is "
            "SSH, tunnels, dev container, WSL, or local."
        )
        visible_response = MagicMock()
        visible_response.choices = [visible_choice]
        with patch(
            "app.llm.provider_service.ProviderService._create_chat_completion",
            new=AsyncMock(return_value=(visible_response, "gpt-4o-mini")),
        ):
            remote_response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-turn-language-corruption-fresh-general",
                    "intent": "coach",
                    "message": "Teach me VS Code Remote SSH step by step. Keep it to one checkpoint first.",
                    "response_language": "en-US",
                },
            )
        assert remote_response.status_code == 200
        assert remote_response.json()["coach_turn"]["scenario"] == "remote_workspace"

        with patch(
            "app.llm.provider_service.ProviderService.test",
            autospec=True,
            return_value=ProviderTestResponse(
                ok=False,
                detail=(
                    "This provider is reachable, but it corrupted Chinese input into question marks "
                    "before the model saw the message."
                ),
                error_category="language_corruption",
                provider_reachable=True,
                model_supported=True,
                status_code=200,
            ),
        ):
            writing_response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-turn-language-corruption-fresh-general",
                    "intent": "coach",
                    "message": "????? Python ??????????????????????",
                    "response_language": "zh-CN",
                },
            )

    assert writing_response.status_code == 200
    payload = writing_response.json()
    assert payload["agent_meta"]["stop_reason"] == "language_corruption"
    assert payload["coach_turn"]["scenario"] == "general"
    assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "general"
    assert "provider" in payload["coach_turn"]["summary"]
    assert "VS Code remote" not in payload["coach_turn"]["summary"]
    assert "VS Code remote" not in payload["reply"]["content"]
    assert "credential mode" not in payload["reply"]["content"]


def test_turn_surfaces_empty_visible_reply_as_degraded_debug_turn(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-turn-provider-empty-debug",
                "workspace_name": "trainer-turn-provider-empty-debug",
                "profile": {
                    "long_term_goal": "Keep empty provider turns aligned with debug coaching",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        empty_choice = MagicMock()
        empty_choice.message.content = ""
        empty_response = MagicMock()
        empty_response.choices = [empty_choice]
        with patch(
            "app.llm.provider_service.ProviderService._create_chat_completion",
            new=AsyncMock(return_value=(empty_response, "gpt-4o-mini")),
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-turn-provider-empty-debug",
                    "intent": "coach",
                    "message": "Keep guiding me through this VS Code debug loop and the next breakpoint.",
                    "response_language": "en-US",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    expected_summary = (
        "The provider returned no visible answer, so this turn stays in the VS Code debug lane."
    )
    expected_next_step = (
        "Tell me where you will pause first and which single value, branch, or stack frame you expect to inspect there."
    )
    assert payload["agent_meta"]["stop_reason"] == "empty_response"
    assert payload["coach_turn"]["summary"] == expected_summary
    assert payload["coach_turn"]["next_step"] == expected_next_step
    assert payload["reply"]["metadata"]["coach_visible_status"]["status"] == "degraded"
    assert payload["reply"]["metadata"]["coach_visible_status"]["stopReason"] == "empty_response"
    assert payload["reply"]["metadata"]["coach_visible_status"]["summary"] == expected_summary
    assert payload["reply"]["metadata"]["coach_visible_status"]["nextStep"] == expected_next_step
    assert expected_summary in payload["reply"]["content"]


def test_turn_keeps_remote_workspace_summary_aligned_when_provider_reply_is_visible(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-turn-provider-remote-visible",
                "workspace_name": "trainer-turn-provider-remote-visible",
                "profile": {
                    "long_term_goal": "Keep remote coaching summary aligned with the visible reply",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        visible_choice = MagicMock()
        visible_choice.message.content = (
            "Start with the remote workspace boundary. First identify whether this workspace is SSH, "
            "tunnels, dev container, WSL, or local, then confirm where files and credentials should live."
        )
        visible_response = MagicMock()
        visible_response.choices = [visible_choice]
        with patch(
            "app.llm.provider_service.ProviderService._create_chat_completion",
            new=AsyncMock(return_value=(visible_response, "gpt-4o-mini")),
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-turn-provider-remote-visible",
                    "intent": "coach",
                    "message": "Teach me VS Code Remote SSH step by step before you test me.",
                    "response_language": "en-US",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "remote_workspace"
    assert payload["coach_turn"]["summary"] == (
        "Establish the VS Code remote workspace boundary before widening the lesson."
    )
    assert payload["coach_turn"]["next_step"] == (
        "Return one real boundary signal from the current VS Code window, such as an Explorer path, `pwd`, or the remote host label."
    )
    assert "remote workspace boundary" in payload["reply"]["content"].lower()


def test_turn_keeps_debug_loop_summary_aligned_when_provider_reply_is_visible(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-turn-provider-debug-visible",
                "workspace_name": "trainer-turn-provider-debug-visible",
                "profile": {
                    "long_term_goal": "Keep debug coaching summary aligned with the visible reply",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        visible_choice = MagicMock()
        visible_choice.message.content = (
            "Build one trustworthy debug loop first. Set one breakpoint, pause at the first state change, "
            "and bring back one observed value before you widen the investigation."
        )
        visible_response = MagicMock()
        visible_response.choices = [visible_choice]
        with patch(
            "app.llm.provider_service.ProviderService._create_chat_completion",
            new=AsyncMock(return_value=(visible_response, "gpt-4o-mini")),
        ):
            response = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-turn-provider-debug-visible",
                    "intent": "coach",
                    "message": "Teach me how to debug Python in VS Code before you quiz me.",
                    "response_language": "en-US",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "debug_loop"
    assert payload["coach_turn"]["summary"] == (
        "Build one trustworthy VS Code debug loop before widening the investigation."
    )
    assert payload["coach_turn"]["next_step"] == (
        "Choose one breakpoint or launch.json move, then tell me where you will pause and what single value or branch you expect to inspect there."
    )
    assert "debug loop" in payload["reply"]["content"].lower()


def test_turn_stream_requires_provider_before_coach_stream_starts(tmp_path: Path) -> None:
    with build_client(tmp_path, configure_provider=False) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-stream-provider-gate",
                "workspace_name": "trainer-stream-provider-gate",
                "profile": {
                    "long_term_goal": "Keep provider gating consistent",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        stream_response = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "intent": "coach",
                "message": "Help me keep going on this idea.",
            },
        )

    assert stream_response.status_code == 400
    assert "api key" in stream_response.text.lower()


def test_session_message_stream_requires_provider_before_coach_stream_starts(tmp_path: Path) -> None:
    with build_client(tmp_path, configure_provider=False) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-message-stream-provider-gate",
                "workspace_name": "trainer-stream-provider-gate",
                "profile": {
                    "long_term_goal": "Keep provider gating consistent",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        stream_response = client.post(
            "/session/message/stream",
            json={
                "session_id": session_id,
                "message": "Help me continue this coaching thread.",
            },
        )

    assert stream_response.status_code == 400
    assert "api key" in stream_response.text.lower()


def test_session_message_stream_surfaces_provider_auth_failure_as_blocked_turn(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-stream-provider-auth-blocked",
                "workspace_name": "trainer-stream-provider-auth-blocked",
                "profile": {
                    "long_term_goal": "Keep stream truth aligned with provider failures",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        failing_completion = AsyncMock(
            side_effect=Exception(
                "Error code: 401 - {'error': {'message': 'Incorrect API key provided'}}"
            )
        )
        with patch(
            "app.llm.provider_service.ProviderService._create_chat_completion",
            new=failing_completion,
        ):
            response = client.post(
                "/session/message/stream",
                json={
                    "session_id": session_id,
                    "message": "Keep this coaching lane intact and continue.",
                    "response_language": "en-US",
                },
            )

    assert response.status_code == 200
    body = response.text
    assert "event: complete" in body
    assert body.count('data: {"chunk": ') == 1
    marker = 'data: {"tokens":'
    last_data_line = [line for line in body.splitlines() if line.startswith(marker)][-1]
    complete_payload = __import__("json").loads(last_data_line[len("data: ") :])
    final_response = complete_payload["response"]
    assert final_response["agent"]["stop_reason"] == "invalid_key_or_permission"
    assert final_response["reply"]["metadata"]["coach_visible_status"]["status"] == "blocked"
    assert (
        final_response["reply"]["metadata"]["coach_visible_status"]["stopReason"]
        == "invalid_key_or_permission"
    )
    assert "Trainer is blocked on the provider path" in final_response["reply"]["content"]


def test_session_message_stream_does_not_promote_partial_truncated_provider_text(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-stream-provider-truncated",
                "workspace_name": "trainer-stream-provider-truncated",
                "profile": {
                    "long_term_goal": "Keep truncated streams recoverable",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        chunk_1 = MagicMock()
        chunk_1.choices = [MagicMock()]
        chunk_1.choices[0].delta.content = "partial visible answer " * 20
        chunk_1.choices[0].finish_reason = None
        chunk_2 = MagicMock()
        chunk_2.choices = [MagicMock()]
        chunk_2.choices[0].delta.content = "unfinished tail"
        chunk_2.choices[0].finish_reason = "length"

        async def async_iter():
            yield chunk_1
            yield chunk_2

        with patch.object(
            ProviderService,
            "_create_chat_completion",
            new=AsyncMock(return_value=(async_iter(), "gpt-4o-mini")),
        ):
            response = client.post(
                "/session/message/stream",
                json={
                    "session_id": session_id,
                    "message": "Keep this coaching lane intact and continue.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )

    assert response.status_code == 200
    body = response.text
    assert "event: complete" in body
    assert "event: error" not in body
    marker = 'data: {"tokens":'
    complete_payload = __import__("json").loads(
        [line for line in body.splitlines() if line.startswith(marker)][-1][len("data: ") :]
    )
    final_response = complete_payload["response"]
    assert final_response["agent"]["stop_reason"] == "truncated_or_empty"
    assert final_response["reply"]["metadata"]["coach_visible_status"]["status"] == "degraded"
    assert "partial visible answer" not in final_response["reply"]["content"]


def test_session_message_stream_suppresses_visible_reply_corruption_chunks(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-stream-provider-language-corruption",
                "workspace_name": "trainer-stream-provider-language-corruption",
                "profile": {
                    "long_term_goal": "Keep stream reply integrity truthful",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        chunk_1 = MagicMock()
        chunk_1.choices = [MagicMock()]
        chunk_1.choices[0].delta.content = "Glad you want to start with VS Code remote "

        chunk_2 = MagicMock()
        chunk_2.choices = [MagicMock()]
        chunk_2.choices[0].delta.content = (
            "\u0431\u043a it's a great target because once the model clicks, debugging and run confi"
        )

        chunk_3 = MagicMock()
        chunk_3.choices = [MagicMock()]
        chunk_3.choices[0].delta.content = "\u0431\u043d stay more stable."

        async def async_iter():
            for item in (chunk_1, chunk_2, chunk_3):
                yield item

        with patch(
            "app.llm.provider_service.ProviderService._create_chat_completion",
            new=AsyncMock(return_value=(async_iter(), "gpt-4o-mini")),
        ):
            response = client.post(
                "/session/message/stream",
                json={
                    "session_id": session_id,
                    "message": "Keep this coaching lane intact and continue.",
                    "response_language": "en-US",
                },
            )

    assert response.status_code == 200
    body = response.text
    assert "event: complete" in body
    assert "\u0431\u043a" not in body
    assert "confi\u0431\u043d" not in body
    marker = 'data: {"tokens":'
    last_data_line = [line for line in body.splitlines() if line.startswith(marker)][-1]
    complete_payload = __import__("json").loads(last_data_line[len("data: ") :])
    final_response = complete_payload["response"]
    assert final_response["agent"]["stop_reason"] == "language_corruption_recovered"
    assert final_response["agent"]["fell_back"] is True
    assert final_response["reply"]["metadata"]["coach_visible_status"]["status"] == "degraded"
    assert (
        final_response["reply"]["metadata"]["coach_visible_status"]["stopReason"]
        in {"language_corruption", "language_corruption_recovered"}
    )
    assert "visibly corrupted coaching reply" not in final_response["reply"]["content"]


def test_session_message_stream_surfaces_empty_visible_reply_as_degraded_remote_turn(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-stream-provider-empty-remote",
                "workspace_name": "trainer-stream-provider-empty-remote",
                "profile": {
                    "long_term_goal": "Keep streamed empty turns aligned with remote coaching",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        async def async_iter():
            if False:
                yield None

        with patch(
            "app.llm.provider_service.ProviderService._create_chat_completion",
            new=AsyncMock(return_value=(async_iter(), "gpt-4o-mini")),
        ):
            response = client.post(
                "/session/message/stream",
                json={
                    "session_id": session_id,
                    "message": "Keep this VS Code remote workspace thread intact and continue.",
                    "response_language": "en-US",
                },
            )

    assert response.status_code == 200
    body = response.text
    assert "event: complete" in body
    marker = 'data: {"tokens":'
    last_data_line = [line for line in body.splitlines() if line.startswith(marker)][-1]
    complete_payload = __import__("json").loads(last_data_line[len("data: ") :])
    final_response = complete_payload["response"]
    expected_summary = (
        "The provider returned no visible answer, so this turn stays in the VS Code remote lane."
    )
    expected_next_step = (
        "Return one real workspace label or path and one sentence about the safe credential mode."
    )
    assert final_response["agent"]["stop_reason"] == "empty_response"
    assert final_response["coach_turn"]["summary"] == expected_summary
    assert final_response["coach_turn"]["next_step"] == expected_next_step
    assert final_response["reply"]["metadata"]["coach_visible_status"]["status"] == "degraded"
    assert final_response["reply"]["metadata"]["coach_visible_status"]["stopReason"] == "empty_response"
    assert final_response["reply"]["metadata"]["coach_visible_status"]["summary"] == expected_summary
    assert final_response["reply"]["metadata"]["coach_visible_status"]["nextStep"] == expected_next_step
    assert expected_summary in final_response["reply"]["content"]


def test_session_message_stream_prefers_non_streaming_truth_for_resource_contract_questions(
    tmp_path: Path,
) -> None:
    drifting_reply = (
        "Resources first viewport promise is the first-screen promise users should grasp before they search, review, or convert. "
        "Do not drift into the VS Code remote lane when the question is about the Resources contract."
    )

    async def unexpected_stream(*_args, **_kwargs):
        raise AssertionError("streaming reply path should be skipped for resource contract questions")
        if False:
            yield None
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-stream-resource-contract-truth",
                "workspace_name": "trainer-stream-resource-contract-truth",
                "profile": {
                    "long_term_goal": "Keep resource contract answers truthful in stream mode",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        upload_response = client.post(
            "/resource/upload",
            json={
                "workspace_id": "workspace-stream-resource-contract-truth",
                "kind": "markdown",
                "name": "resources-view-contract.md",
                "source": "inline://resources-view-contract.md",
                "content": (
                    "# Resources view contract\n"
                    "### 6.3 Resources\n\n"
                    "First viewport promise:\n"
                    "the learner can find, trust, preview, and convert resources without losing provenance.\n\n"
                    "Must not become:\n\n"
                    "- a CMS,\n"
                    "- a raw filesystem browser,\n"
                    "- a place that writes into user project code by surprise.\n"
                ),
                "content_encoding": "utf-8",
            },
        )
        assert upload_response.status_code == 200, upload_response.text
        resource_id = upload_response.json()["id"]

        index_response = client.post(
            "/resource/index",
            json={
                "workspace_id": "workspace-stream-resource-contract-truth",
                "resource_id": resource_id,
                "enable_network": False,
            },
        )
        assert index_response.status_code == 200, index_response.text

        with (
            patch.object(
                ProviderService,
                "coaching_reply",
                new=AsyncMock(return_value=drifting_reply),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_stream",
                new=unexpected_stream,
            ),
        ):
            response = client.post(
                "/session/message/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-stream-resource-contract-truth",
                    "message": "Please explain the Resources view first viewport promise and must not become. Do not drift into VS Code remote.",
                    "response_language": "zh-CN",
                },
            )

    assert response.status_code == 200
    body = response.text
    assert "event: complete" in body
    marker = 'data: {"tokens":'
    last_data_line = [line for line in body.splitlines() if line.startswith(marker)][-1]
    complete_payload = __import__("json").loads(last_data_line[len("data: ") :])
    final_response = complete_payload["response"]
    assert final_response["agent"]["grounded_resource_contract_repaired"] is True
    assert "raw filesystem browser" in final_response["reply"]["content"]
    assert "VS Code remote" not in final_response["reply"]["content"]
    assert "remote lane" not in final_response["reply"]["content"]


def test_turn_stream_prefers_non_streaming_truth_for_resource_contract_questions(
    tmp_path: Path,
) -> None:
    drifting_reply = (
        "Resources first viewport promise is the first-screen promise users should grasp before they search, review, or convert. "
        "Do not drift into the VS Code remote lane when the question is about the Resources contract."
    )

    async def unexpected_stream(*_args, **_kwargs):
        raise AssertionError("streaming reply path should be skipped for resource contract questions")
        if False:
            yield None
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-turn-stream-resource-contract-truth",
                "workspace_name": "trainer-turn-stream-resource-contract-truth",
                "profile": {
                    "long_term_goal": "Keep turn stream resource contract answers truthful",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        upload_response = client.post(
            "/resource/upload",
            json={
                "workspace_id": "workspace-turn-stream-resource-contract-truth",
                "kind": "markdown",
                "name": "resources-view-contract.md",
                "source": "inline://resources-view-contract.md",
                "content": (
                    "# Resources view contract\n"
                    "### 6.3 Resources\n\n"
                    "First viewport promise:\n"
                    "the learner can find, trust, preview, and convert resources without losing provenance.\n\n"
                    "Must not become:\n\n"
                    "- a CMS,\n"
                    "- a raw filesystem browser,\n"
                    "- a place that writes into user project code by surprise.\n"
                ),
                "content_encoding": "utf-8",
            },
        )
        assert upload_response.status_code == 200, upload_response.text
        resource_id = upload_response.json()["id"]

        index_response = client.post(
            "/resource/index",
            json={
                "workspace_id": "workspace-turn-stream-resource-contract-truth",
                "resource_id": resource_id,
                "enable_network": False,
            },
        )
        assert index_response.status_code == 200, index_response.text

        with (
            patch.object(
                ProviderService,
                "coaching_reply",
                new=AsyncMock(return_value=drifting_reply),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_stream",
                new=unexpected_stream,
            ),
        ):
            response = client.post(
                "/turn/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-turn-stream-resource-contract-truth",
                    "intent": "coach",
                    "message": "Please explain the Resources view first viewport promise and must not become. Do not drift into VS Code remote.",
                    "response_language": "zh-CN",
                },
            )

    assert response.status_code == 200
    body = response.text
    assert "event: complete" in body
    marker = 'data: {"tokens":'
    last_data_line = [line for line in body.splitlines() if line.startswith(marker)][-1]
    complete_payload = __import__("json").loads(last_data_line[len("data: ") :])
    final_response = complete_payload["response"]
    assert final_response["intent"] == "coach"
    assert final_response["agent"]["grounded_resource_contract_repaired"] is True
    assert "raw filesystem browser" in final_response["reply"]["content"]
    assert "VS Code remote" not in final_response["reply"]["content"]
    assert "remote lane" not in final_response["reply"]["content"]


def test_provider_test_surfaces_model_unsupported_category(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        with patch(
            "app.llm.provider_service.ProviderService.test",
            return_value=ProviderTestResponse(
                ok=False,
                detail="Provider reached, but the chat model 'demo-model' is not accepted by the endpoint.",
                error_category="model_unsupported",
                retryable=False,
                status_code=400,
                diagnostics=["Tried model candidates: demo-model", "Not supported model demo-model"],
                provider_reachable=True,
                model_supported=False,
            ),
        ):
            response = client.post(
                "/provider/test",
                json={
                    "provider": {
                        "name": "unsupported-model-provider",
                        "base_url": "https://example.com/v1",
                        "api_key_ref": "trainer.default",
                        "model": "demo-model",
                        "capabilities": {
                            "chat": True,
                            "responses": True,
                            "vision": False,
                            "embeddings": False,
                            "tools": False,
                            "json_schema": False,
                            "streaming": True,
                        },
                    },
                    "api_key": "sk-test",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "model_unsupported"
    assert payload["reachable"] is True
    assert payload["model_supported"] is False
    assert payload["retryable"] is False


def test_provider_test_surfaces_model_not_found_category(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        with patch(
            "app.llm.provider_service.ProviderService.test",
            return_value=ProviderTestResponse(
                ok=False,
                detail="Provider reached, but there is currently no available gateway channel for chat model 'demo-model'.",
                error_category="model_not_found",
                retryable=False,
                status_code=503,
                diagnostics=["No available channel for model demo-model"],
                provider_reachable=True,
                model_supported=False,
            ),
        ):
            response = client.post(
                "/provider/test",
                json={
                    "provider": {
                        "name": "missing-channel-provider",
                        "base_url": "https://example.com/v1",
                        "api_key_ref": "trainer.default",
                        "model": "demo-model",
                        "capabilities": {
                            "chat": True,
                            "responses": True,
                            "vision": False,
                            "embeddings": False,
                            "tools": False,
                            "json_schema": False,
                            "streaming": True,
                        },
                    },
                    "api_key": "sk-test",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["status"] == "model_not_found"
    assert payload["reachable"] is True
    assert payload["model_supported"] is False
    assert payload["retryable"] is False


def test_provider_models_requires_service_root_address(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/provider/models",
            json={
                "provider": {
                    "name": "broken-provider",
                    "baseUrl": "",
                    "apiKeyRef": "trainer.default",
                    "model": "",
                    "capabilities": {
                        "chat": True,
                        "responses": True,
                        "vision": False,
                        "embeddings": False,
                        "tools": False,
                        "jsonSchema": False,
                        "streaming": True,
                    },
                },
                "apiKey": "sk-test",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["available_models"] == []
    assert payload["detail"] == "Add a service root address before fetching models."


def test_provider_models_missing_service_root_localizes_chinese_detail(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/provider/models",
            json={
                "responseLanguage": "zh-CN",
                "provider": {
                    "name": "broken-provider",
                    "baseUrl": "",
                    "apiKeyRef": "trainer.default",
                    "model": "",
                    "capabilities": {
                        "chat": True,
                        "responses": True,
                        "vision": False,
                        "embeddings": False,
                        "tools": False,
                        "jsonSchema": False,
                        "streaming": True,
                    },
                },
                "apiKey": "sk-test",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["detail"] == "\u83b7\u53d6\u6a21\u578b\u524d\uff0c\u8bf7\u5148\u586b\u5199\u670d\u52a1\u6839\u5730\u5740\u3002"


def test_provider_models_discovers_without_a_selected_model_or_name(tmp_path: Path) -> None:
    captured: dict[str, ProviderConfig] = {}

    def fake_list_models(
        self: ProviderService,
        provider: ProviderConfig,
        api_key: str | None,
    ) -> ProviderModelsResponse:
        captured["provider"] = provider
        assert api_key == "sk-test"
        return ProviderModelsResponse(
            ok=True,
            detail="Models listed.",
            available_models=["model-from-provider"],
            listed=True,
        )

    with build_client(tmp_path, configure_provider=False) as client, patch.object(
        ProviderService,
        "list_models",
        autospec=True,
        side_effect=fake_list_models,
    ):
        response = client.post(
            "/provider/models",
            json={
                "provider": {
                    "protocol": "openai_chat_completions_compatible",
                    "baseUrl": "https://gateway.example/v1/chat/completions",
                    "apiKeyRef": "trainer.discovery",
                    "model": "",
                },
                "apiKey": "sk-test",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["available_models"] == ["model-from-provider"]
    assert captured["provider"].name == "custom-openai-compatible"
    assert captured["provider"].model == ""
    assert captured["provider"].base_url == "https://gateway.example/v1"


def test_provider_test_threads_request_defaults_into_provider_config(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_test(self, provider, api_key, **_: object):  # type: ignore[no-untyped-def]
        captured["request_defaults"] = provider.request_defaults
        return ProviderTestResponse(
            ok=True,
            detail="Provider reachable.",
            diagnostics=["Probe succeeded."],
            provider_reachable=True,
            model_supported=True,
        )

    with build_client(tmp_path) as client, patch.object(ProviderService, "test", autospec=True, side_effect=fake_test):
        response = client.post(
            "/provider/test",
            json={
                "provider": {
                    "name": "mini-max",
                    "baseUrl": "http://47.107.101.18:3000/v1",
                    "apiKeyRef": "trainer.minimax",
                    "model": "MiniMax-M3",
                    "requestDefaults": {
                        "extra_body": {
                            "thinking": {
                                "type": "disabled",
                            }
                        }
                    },
                    "capabilities": {
                        "chat": True,
                        "responses": True,
                        "vision": False,
                        "embeddings": False,
                        "tools": False,
                        "jsonSchema": False,
                        "streaming": True,
                    },
                },
                "api_key": "sk-test",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert captured["request_defaults"]["extra_body"]["thinking"]["type"] == "disabled"


def test_provider_test_uses_cached_provider_service_instance(tmp_path: Path) -> None:
    with build_client(tmp_path, configure_provider=False) as client:
        runtime = client.app.state.runtime
        fake_service = MagicMock()
        fake_service.test.return_value = ProviderTestResponse(
            ok=True,
            detail="Provider reachable.",
            diagnostics=["Probe succeeded."],
            provider_reachable=True,
            model_supported=True,
        )
        runtime.provider_service_for = MagicMock(return_value=fake_service)

        response = client.post(
            "/provider/test",
            json={
                "provider": {
                    "name": "mini-max",
                    "baseUrl": "http://47.107.101.18:3000/v1",
                    "apiKeyRef": "trainer.minimax",
                    "model": "MiniMax-M3",
                },
                "apiKey": "sk-test",
            },
        )

    assert response.status_code == 200
    runtime.provider_service_for.assert_called_once()
    provider_arg, api_key_arg = runtime.provider_service_for.call_args.args
    assert isinstance(provider_arg, ProviderConfig)
    assert provider_arg.model == "MiniMax-M3"
    assert api_key_arg == "sk-test"
    fake_service.test.assert_called_once()
    tested_provider_arg, tested_api_key_arg = fake_service.test.call_args.args
    assert isinstance(tested_provider_arg, ProviderConfig)
    assert tested_provider_arg.base_url == "http://47.107.101.18:3000/v1"
    assert tested_api_key_arg == "sk-test"


def test_provider_models_threads_request_defaults_into_provider_config(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_list_models(self, provider, api_key):  # type: ignore[no-untyped-def]
        captured["request_defaults"] = provider.request_defaults
        captured["model_token_limits"] = provider.model_token_limits
        return ProviderModelsResponse(
            ok=True,
            detail="Models listed.",
            available_models=["MiniMax-M3"],
            model_token_limits={
                "MiniMax-M3": {
                    "contextWindowTokens": 64000,
                    "maxOutputTokens": 8000,
                }
            },
            listed=True,
            cache_hit=False,
        )

    with build_client(tmp_path) as client, patch.object(ProviderService, "list_models", autospec=True, side_effect=fake_list_models):
        response = client.post(
            "/provider/models",
            json={
                "provider": {
                    "name": "mini-max",
                    "baseUrl": "http://47.107.101.18:3000/v1",
                    "apiKeyRef": "trainer.minimax",
                    "model": "MiniMax-M3",
                    "requestDefaults": {
                        "extra_body": {
                            "thinking": {
                                "type": "disabled",
                            }
                        }
                    },
                    "modelTokenLimits": {
                        "MiniMax-M3": {
                            "contextWindowTokens": 64000,
                            "maxOutputTokens": 8000,
                        }
                    },
                    "capabilities": {
                        "chat": True,
                        "responses": True,
                        "vision": False,
                        "embeddings": False,
                        "tools": False,
                        "jsonSchema": False,
                        "streaming": True,
                    },
                },
                "apiKey": "sk-test",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert captured["request_defaults"]["extra_body"]["thinking"]["type"] == "disabled"
    assert captured["model_token_limits"]["MiniMax-M3"].context_window_tokens == 64000
    assert payload["model_token_limits"]["MiniMax-M3"]["context_window_tokens"] == 64000
    assert payload["model_token_limits"]["MiniMax-M3"]["max_output_tokens"] == 8000


def test_provider_models_uses_cached_provider_service_instance(tmp_path: Path) -> None:
    with build_client(tmp_path, configure_provider=False) as client:
        runtime = client.app.state.runtime
        fake_service = MagicMock()
        fake_service.list_models.return_value = ProviderModelsResponse(
            ok=True,
            detail="Models listed.",
            available_models=["MiniMax-M3"],
            resolved_model="MiniMax-M3",
            listed=True,
            cache_hit=False,
        )
        runtime.provider_service_for = MagicMock(return_value=fake_service)

        response = client.post(
            "/provider/models",
            json={
                "provider": {
                    "name": "mini-max",
                    "baseUrl": "http://47.107.101.18:3000/v1",
                    "apiKeyRef": "trainer.minimax",
                    "model": "MiniMax-M3",
                },
                "apiKey": "sk-test",
            },
        )

    assert response.status_code == 200
    runtime.provider_service_for.assert_called_once()
    provider_arg, api_key_arg = runtime.provider_service_for.call_args.args
    assert isinstance(provider_arg, ProviderConfig)
    assert provider_arg.model == "MiniMax-M3"
    assert api_key_arg == "sk-test"
    fake_service.list_models.assert_called_once()
    listed_provider_arg, listed_api_key_arg = fake_service.list_models.call_args.args
    assert isinstance(listed_provider_arg, ProviderConfig)
    assert listed_provider_arg.base_url == "http://47.107.101.18:3000/v1"
    assert listed_api_key_arg == "sk-test"


def test_provider_models_protocol_matrix_preserves_route_metadata(tmp_path: Path) -> None:
    captured: list[ProviderConfig] = []

    def fake_list_models(
        self: ProviderService,
        provider: ProviderConfig,
        api_key: str | None,
    ) -> ProviderModelsResponse:
        captured.append(provider)
        return ProviderModelsResponse(
            ok=True,
            detail=f"Models listed for {provider.protocol}.",
            available_models=[provider.model],
            resolved_model=provider.model,
            listed=True,
            cache_hit=False,
        )

    protocol_payloads = [
        (
            "openai_chat_completions",
            "openai",
            "https://api.openai.com/v1",
            "gpt-4o-mini",
            "openai",
        ),
        (
            "openai_chat_completions_compatible",
            "openai-compatible",
            "https://gateway.example/v1",
            "MiniMax-M3",
            "openai",
        ),
        (
            "openai_responses",
            "responses",
            "https://api.openai.com/v1",
            "gpt-5.1-mini",
            "openai",
        ),
        (
            "anthropic_messages",
            "anthropic",
            "http://minimax.redfast.top",
            "MiniMax-M3",
            "anthropic",
        ),
        (
            "gemini_generate_content",
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            "gemini-2.0-flash",
            "gemini",
        ),
    ]

    with build_client(tmp_path, configure_provider=False) as client, patch.object(
        ProviderService,
        "list_models",
        autospec=True,
        side_effect=fake_list_models,
    ):
        for expected_protocol, api_alias, base_url, model, expected_family in protocol_payloads:
            response = client.post(
                "/provider/models",
                json={
                    "apiKey": "sk-test",
                    "provider": {
                        "name": f"{expected_protocol}-provider",
                        "api": api_alias,
                        "baseUrl": base_url,
                        "apiKeyRef": f"trainer.{expected_protocol}",
                        "model": model,
                        "capabilities": {"tools": True, "streaming": True},
                    },
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["ok"] is True
            assert payload["protocol"] == expected_protocol
            assert payload["protocol_family"] == expected_family
            assert payload["available_models"] == [model]

    assert [provider.protocol for provider in captured] == [
        item[0] for item in protocol_payloads
    ]
    assert all(provider.capabilities.tools is True for provider in captured)


def test_provider_models_infers_capabilities_from_declared_protocol(tmp_path: Path) -> None:
    captured: dict[str, ProviderConfig] = {}

    def fake_list_models(
        self: ProviderService,
        provider: ProviderConfig,
        api_key: str | None,
    ) -> ProviderModelsResponse:
        captured["provider"] = provider
        return ProviderModelsResponse(
            ok=True,
            detail="Models listed.",
            available_models=["gemini-2.0-flash"],
            listed=True,
            cache_hit=False,
        )

    with build_client(tmp_path) as client, patch.object(
        ProviderService,
        "list_models",
        autospec=True,
        side_effect=fake_list_models,
    ):
        response = client.post(
            "/provider/models",
            json={
                "provider": {
                    "name": "gemini",
                    "protocol": "gemini_generate_content",
                    "baseUrl": "https://generativelanguage.googleapis.com",
                    "apiKeyRef": "trainer.gemini",
                    "model": "gemini-2.0-flash",
                },
                "apiKey": "sk-test",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    provider = captured["provider"]
    assert payload["protocol"] == "gemini_generate_content"
    assert payload["protocol_family"] == "gemini"
    assert provider.capabilities.tools is True
    assert provider.capabilities.streaming is True
    assert provider.capabilities.structured_output is True


def test_session_snapshot_restores_between_requests(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-restore",
                "workspace_name": "trainer-restore",
                "profile": {
                    "long_term_goal": "Keep the coach thread alive across requests",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Help me keep the next step tied to session restore.",
                "response_language": "zh-CN",
            },
        )
        assert message_response.status_code == 200

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        summary_payload = summary_response.json()
        assert summary_payload["messages"]
        assert summary_payload["memory"]["current_focus"]
        assert summary_payload["memory"]["active_thread"]["focus_area"]
        assert summary_payload["memory"]["active_thread"]["next_step"]


def test_session_message_persists_coach_defaults_and_language_preferences(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-preferences",
                "workspace_name": "trainer-preferences",
                "profile": {
                    "long_term_goal": "Keep coach defaults stable across turns",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "\u8bf7\u4ee5\u540e\u90fd\u5148\u7528\u4e2d\u6587\u5e26\u6211\u62c6\u5c0f\u6b65\uff0c\u5e76\u4fdd\u6301\u5f53\u524d\u9879\u76ee\u8303\u56f4\u3002",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
                "coach_defaults": {
                    "memory_scope": "project",
                    "working_set_mode": "focused",
                    "review_cadence": "active",
                    "review_reminder_mode": "ahead",
                    "workspace_memory_toggles": {
                        "decisions": True,
                        "patterns": True,
                        "resources": False,
                    },
                },
            },
        )
        assert message_response.status_code == 200

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        summary_payload = summary_response.json()
        workspace = summary_payload["memory"]["workspace"]
        assert workspace["response_language"] == "zh-CN"
        assert workspace["answer_mode"] == "coach-first"
        assert workspace["coach_defaults"]["working_set_mode"] == "focused"
        assert workspace["coach_defaults"]["review_cadence"] == "active"
        assert workspace["coach_defaults"]["review_reminder_mode"] == "ahead"
        assert workspace["workspace_memory_toggles"]["resources"] is False


def test_session_message_returns_project_sourcing_artifact(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-project-source",
                "workspace_name": "trainer-project-source",
                "profile": {
                    "long_term_goal": "Find a realistic training repo for long-term coaching work",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "\u5e2e\u6211\u627e\u9002\u5408\u8bad\u7ec3\u957f\u671f\u6559\u7ec3\u80fd\u529b\u7684\u516c\u5f00\u9879\u76ee\u6765\u6e90\u3002",
                "response_language": "zh-CN",
            },
        )
        assert message_response.status_code == 200
        payload = message_response.json()
        assert payload["coach_turn"]["scenario"] == "project_sourcing"
        assert any(item["kind"] == "project_source" for item in payload["reply"]["metadata"]["artifacts"])


@patch("app.ingest.service.fetch_url")
def test_project_sourcing_prefers_grounded_external_reference_after_url_index(
    mock_fetch_url,
    tmp_path: Path,
) -> None:
    mock_fetch_url.return_value = ControlledFetchResponse(
        body=(
            b"<html><body><article><h1>Coach Research</h1>"
            b"<p>SPDX-License-Identifier: MIT</p><p>Last updated: 2026-07-01</p>"
            b"<p>Keep the next implementation slice thin and verifiable.</p>"
            b"</article></body></html>"
        ),
        final_url="https://example.com/coach-research",
        status=200,
        headers={"content-type": "text/html"},
        fetched_at="2026-07-12T00:00:00+00:00",
    )

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-grounded-project-source",
                "workspace_name": "trainer-grounded-project-source",
                "profile": {
                    "long_term_goal": "Find grounded outside sources for coaching work",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        upload_response = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "url",
                "name": "Grounded Coach Research",
                "source": "https://example.com/coach-research",
            },
        )
        assert upload_response.status_code == 200
        resource_id = upload_response.json()["id"]

        index_response = client.post(
            "/resource/index",
            json={"session_id": session_id, "resource_id": resource_id, "enable_network": True},
        )
        assert index_response.status_code == 200

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Help me find public project sources that are good for training long-horizon coaching ability.",
                "response_language": "zh-CN",
            },
        )
        assert message_response.status_code == 200
        payload = message_response.json()
        assert payload["coach_turn"]["scenario"] == "project_sourcing"
        top_source = payload["snapshot"]["project_sources"][0]
        assert "Coach Research" in top_source["title"] or "Grounded source" in top_source["title"]
        assert top_source["source_url"] == "https://example.com/coach-research"
        assert top_source["retrieved_at"]
        assert top_source["trust_score"] > 0.4
        assert "commercial_reuse_eligible" in top_source["quality_flags"]
        assert "controlled_source" in top_source["quality_flags"]
        assert any(
            "teaching_asset_grounded" in item["quality_flags"]
            for item in payload["snapshot"]["project_sources"][1:]
        )

        project_source_artifact = next(
            item for item in payload["reply"]["metadata"]["artifacts"] if item["kind"] == "project_source"
        )
        assert "https://example.com/coach-research" in project_source_artifact["content"]
        assert project_source_artifact["metadata"]["source_url"] == "https://example.com/coach-research"
        assert project_source_artifact["metadata"]["retrieved_at"]
        assert project_source_artifact["metadata"]["trust_score"] > 0.4
        assert payload["reply"]["metadata"]["external_references"][0]["source"] == "https://example.com/coach-research"


def test_session_message_project_sourcing_uses_saved_teaching_asset_grounding(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-asset-grounding",
                "workspace_name": "trainer-asset-grounding",
                "profile": {
                    "long_term_goal": "Find grounded outside sources for coaching work",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime
        runtime.memory_service.record_teaching_asset(
            "workspace-asset-grounding",
            TeachingKnowledgeAsset(
                kind="implementation_pattern",
                scope="project",
                workspace_id="workspace-asset-grounding",
                title="Thin verified coaching slice",
                summary="Keep the next implementation slice thin and verifiable.",
                implementation_pattern="Keep the next implementation slice thin and verifiable.",
                focus_area="long-term coaching flow",
                scenario="project_sourcing",
                source_key="asset::thin-slice",
                trust_score=0.83,
            ),
        )

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Help me find public project sources that are good for training long-horizon coaching ability.",
                "response_language": "zh-CN",
            },
        )
        assert message_response.status_code == 200
        payload = message_response.json()
        grounded = next(
            item
            for item in payload["snapshot"]["project_sources"]
            if "teaching_asset_grounded" in item["quality_flags"]
        )
        assert "Thin verified coaching slice" in grounded["title"]
        assert "Thin verified coaching slice" in grounded["repo_hint"]
        project_source_artifact = next(
            item for item in payload["reply"]["metadata"]["artifacts"] if item["kind"] == "project_source"
        )
        assert "Thin verified coaching slice" in project_source_artifact["content"]


def test_session_message_project_sourcing_uses_workspace_understanding_grounding(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-understanding-grounding",
                "workspace_name": "trainer-understanding-grounding",
                "profile": {
                    "long_term_goal": "Find grounded outside sources for coaching work",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime
        runtime.memory_service.save_workspace_understanding(
            "workspace-understanding-grounding",
            WorkspaceUnderstandingSnapshot(
                repo_summary="Reply assembly currently flows through the coach router and planner boundary.",
                entry_points=["server/app/api/routers.py", "server/app/pedagogy/service.py"],
                feature_lanes=["Keep the reply assembly lane narrow and verifiable."],
                risk_zones=["Recent edits already span multiple coaching files."],
                training_opportunities=["Strengthen the first reply path before widening the workflow."],
                resource_brief="",
            ),
        )

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Help me find public project sources that are good for training long-horizon coaching ability.",
                "response_language": "zh-CN",
            },
        )
        assert message_response.status_code == 200
        payload = message_response.json()
        grounded = next(
            item
            for item in payload["snapshot"]["project_sources"]
            if "workspace_grounded" in item["quality_flags"]
        )
        assert "server/app/api/routers.py" in grounded["repo_hint"]
        assert "server/app/api/routers.py" in grounded["first_task"]


def test_evaluate_snippet_persists_learning_outcome_into_memory_summary(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-learning-outcome-api",
                "workspace_name": "trainer-learning-outcome-api",
                "profile": {
                    "long_term_goal": "Track learning outcomes through evaluation",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-learning-outcome-api",
                "objectives": ["Track learning outcomes through evaluation"],
            },
        )
        assert generated.status_code == 200, generated.text

        task_response = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-learning-outcome-api",
                "natural_language_goal": (
                    "Add two integers and return the sum.\n"
                    "Keep the slice reviewable in one pass."
                ),
            },
        )
        assert task_response.status_code == 200

        evaluate_response = client.post(
            "/evaluate/snippet",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-learning-outcome-api",
                "task_spec_id": task_response.json()["id"],
                "language_id": "python",
                "content": "def add(a: int, b: int) -> int:\n    return a + b\n",
            },
        )
        assert evaluate_response.status_code == 200

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        payload = summary_response.json()
        assert "learning_outcomes" in payload["memory"]
        assert payload["memory"]["learning_outcomes"]
        latest = payload["memory"]["learning_outcomes"][0]
        assert latest["outcome"] == "verification_pending"
        assert latest["summary"]
        assert latest["checks"] == []
        assert latest["missing_requirements"] == []
        assert payload["memory"]["coaching_adaptation"]["summary"] == ""
        assert payload["memory"]["coaching_adaptation"]["evidence"][0] == latest["summary"]
        assert payload["memory"]["teaching_observations"]
        assert not payload["memory"]["workspace"].get("latest_evaluation_feedback")
        assert payload["memory"]["workspace"]["latest_learning_outcome"] == "verification_pending"
        assert payload["memory"]["workspace"]["latest_learning_blocker"]


def test_training_current_file_evaluation_projects_practice_handoff(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-training-evaluation-handoff",
                "workspace_name": "trainer-training-evaluation-handoff",
                "profile": {
                    "long_term_goal": "Keep practice verification inside the training loop",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime
        runtime.memory_service.upsert_card(
            "workspace-training-evaluation-handoff",
            TrainingCardCandidateSnapshot(
                card_id="practice-api-1",
                card_type="practice",
                title="Verify IDE evidence handoff",
                status="active",
                focus_area="IDE evidence",
                target_skill="practice verification",
            ),
        )
        runtime.evaluator_service.evaluate_current_file = MagicMock(
            return_value=EvaluationReport(
                task_spec_id="task-practice-api",
                summary="The current file passed practice verification.",
                static_checks=[],
                dynamic_checks=[],
                semantic_checks=[
                    EvaluationCheck(
                        id="semantic-review",
                        label="semantic-review",
                        status="passed",
                        detail="Implementation satisfies the available signals.",
                    )
                ],
                next_step="Return to Coach and route the next training card.",
                reflection="The practice card has verified evidence.",
                passed=True,
            )
        )

        evaluate_response = client.post(
            "/evaluate/current-file",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-training-evaluation-handoff",
                "task_spec_id": "task-practice-api",
                "file_path": str(tmp_path / "practice.py"),
                "language_id": "python",
                "content": "def ok():\n    return True\n",
                "diagnostics": [],
                "evaluation_source": "training",
                "training_card_id": "practice-api-1",
                "training_card_title": "Verify IDE evidence handoff",
            },
        )
        assert evaluate_response.status_code == 200
        sandbox_root = runtime.sandbox_service.ensure_workspace_root("workspace-training-evaluation-handoff")
        assert (sandbox_root / "cards" / "practice" / "practice-api-1.md").exists()
        assert (sandbox_root / "cards" / "current" / "active.md").exists()
        evaluation_note = sandbox_root / "notes" / "training-handoffs" / "practice-api-1.md"
        assert evaluation_note.exists()
        assert "The current file passed practice verification." in evaluation_note.read_text(encoding="utf-8")

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        workspace = summary_response.json()["memory"]["workspace"]
        assert workspace["selected_card_id"] == "practice-api-1"
        assert workspace["selected_card_status"] == "active"
        assert workspace["latest_training_submode"] == "practice"
        assert workspace["latest_learning_verified_result"] == ""
        assert workspace["latest_training_handoff"]["learning_phase"] == "verify"
        assert workspace["latest_training_handoff"]["return_mode"] == "reflection_required"
        assert workspace["latest_training_handoff"]["continue_in"] == "training"
        assert workspace["latest_training_handoff"]["accepted_into"] == "training"
        assert workspace["latest_training_next_hop"]["continue_in"] == "training"
        assert workspace["latest_training_next_hop"]["accepted_into"] == "training"
        assert workspace["latest_training_next_hop"]["status"] == "reflection_required"
        verify_pending = summary_response.json()["memory"]["evidence_queue"]["pending"]
        assert not any(
            item["source_card_id"] == "practice-api-1" and item["verified"]
            for item in verify_pending
        )

        handoff_id = workspace["latest_training_handoff"]["handoff_id"]
        reflected_response = client.post(
            "/training/reflect",
            json={
                "workspace_id": "workspace-training-evaluation-handoff",
                "card_id": "practice-api-1",
                "handoff_id": handoff_id,
                "reflection": "The current-file result proves this practice branch behaves as expected.",
            },
        )
        assert reflected_response.status_code == 200
        reflected_workspace = reflected_response.json()["workspace"]
        assert reflected_workspace["selected_card_status"] == "active"
        assert reflected_workspace["latest_training_handoff"]["learning_phase"] == "reflect"
        assert reflected_workspace["latest_training_handoff"]["return_mode"] == "return_required"

        returned_response = client.post(
            "/training/return",
            json={
                "workspace_id": "workspace-training-evaluation-handoff",
                "card_id": "practice-api-1",
                "handoff_id": handoff_id,
            },
        )
        assert returned_response.status_code == 200
        returned_workspace = returned_response.json()["workspace"]
        assert returned_workspace["selected_card_status"] == "implemented"
        assert returned_workspace["latest_learning_verified_result"] == (
            "The current file passed practice verification."
        )
        assert returned_workspace["latest_training_handoff"]["learning_phase"] == "return"
        assert returned_workspace["latest_training_handoff"]["return_mode"] == "result"
        assert returned_workspace["latest_training_next_hop"]["continue_in"] == "chat"
        assert returned_workspace["latest_training_next_hop"]["accepted_into"] == "coach"
        assert returned_workspace["latest_training_next_hop"]["status"] == "continued_in_chat"

        completed_summary = client.get("/memory/summary", params={"session_id": session_id})
        assert completed_summary.status_code == 200
        evidence = [
            item
            for item in completed_summary.json()["memory"]["evidence_queue"]["pending"]
            if item["source_card_id"] == "practice-api-1"
        ]
        assert len(evidence) == 1
        assert evidence[0]["verified"] is True
        assert evidence[0]["verification_source"] == "ide_current_file"
        assert evidence[0]["source"] == "training_handoff_return"


def test_training_current_file_evaluation_with_failed_diagnostics_blocks_practice_handoff(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-training-evaluation-blocker",
                "workspace_name": "trainer-training-evaluation-blocker",
                "profile": {
                    "long_term_goal": "Keep practice verification honest when IDE diagnostics fail",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime
        runtime.memory_service.upsert_card(
            "workspace-training-evaluation-blocker",
            TrainingCardCandidateSnapshot(
                card_id="practice-api-blocked-1",
                card_type="practice",
                title="Reject failed IDE evidence",
                status="active",
                focus_area="IDE evidence",
                target_skill="practice verification",
            ),
        )
        runtime.evaluator_service.evaluate_current_file = MagicMock(
            return_value=EvaluationReport(
                task_spec_id="task-practice-api-blocked",
                summary="Evaluation failed on: VS Code diagnostics.",
                static_checks=[
                    EvaluationCheck(
                        id="vscode-diagnostics",
                        label="VS Code diagnostics",
                        status="failed",
                        detail="[error] practice.py:1: Type mismatch in implemented branch.",
                    )
                ],
                dynamic_checks=[],
                semantic_checks=[
                    EvaluationCheck(
                        id="semantic-review",
                        label="semantic-review",
                        status="failed",
                        detail="Fix the IDE diagnostic before accepting this practice card.",
                    )
                ],
                next_step="Fix the VS Code diagnostic, then re-run current file verification.",
                reflection="The practice card still has IDE evidence blocking completion.",
                passed=False,
            )
        )

        evaluate_response = client.post(
            "/evaluate/current-file",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-training-evaluation-blocker",
                "task_spec_id": "task-practice-api-blocked",
                "file_path": str(tmp_path / "practice.py"),
                "language_id": "python",
                "content": "def broken() -> int:\n    return 'nope'\n",
                "diagnostics": ["[error] practice.py:1: Type mismatch in implemented branch."],
                "evaluation_source": "training",
                "training_card_id": "practice-api-blocked-1",
                "training_card_title": "Reject failed IDE evidence",
            },
        )
        assert evaluate_response.status_code == 200
        sandbox_root = runtime.sandbox_service.ensure_workspace_root("workspace-training-evaluation-blocker")
        assert (sandbox_root / "cards" / "practice" / "practice-api-blocked-1.md").exists()
        evaluation_note = sandbox_root / "notes" / "training-handoffs" / "practice-api-blocked-1.md"
        assert evaluation_note.exists()
        assert "Fix the VS Code diagnostic" in evaluation_note.read_text(encoding="utf-8")

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        workspace = summary_response.json()["memory"]["workspace"]
        assert workspace["selected_card_id"] == "practice-api-blocked-1"
        assert workspace["selected_card_status"] == "blocked"
        assert workspace["latest_training_submode"] == "practice"
        assert workspace["latest_learning_verified_result"] == ""
        assert workspace["latest_learning_blocker"] == (
            "Fix the VS Code diagnostic, then re-run current file verification."
        )
        assert workspace["latest_learning_partial_progress"] == (
            "Evaluation failed on: VS Code diagnostics."
        )
        assert workspace["latest_training_handoff"]["return_mode"] == "blocker"
        assert workspace["latest_training_handoff"]["blocked_by"] == (
            "Fix the VS Code diagnostic, then re-run current file verification."
        )
        assert workspace["latest_training_handoff"]["continue_in"] == "training"
        assert workspace["latest_training_handoff"]["accepted_into"] == "training"
        assert workspace["latest_training_next_hop"]["continue_in"] == "training"
        assert workspace["latest_training_next_hop"]["accepted_into"] == "training"
        assert workspace["latest_training_next_hop"]["status"] == "blocked"
        assert workspace["latest_training_next_hop"]["blocked_by"] == (
            "Fix the VS Code diagnostic, then re-run current file verification."
        )


def test_training_snippet_evaluation_cannot_complete_practice_card(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-training-snippet-guard",
                "workspace_name": "trainer-training-snippet-guard",
                "profile": {
                    "long_term_goal": "Require real IDE-file evidence for practice cards",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime
        runtime.memory_service.upsert_card(
            "workspace-training-snippet-guard",
            TrainingCardCandidateSnapshot(
                card_id="practice-snippet-guard-1",
                card_type="practice",
                title="Reject snippet-only practice proof",
                status="active",
                focus_area="IDE evidence",
                target_skill="practice verification",
            ),
        )
        runtime.evaluator_service.evaluate_snippet = MagicMock(
            side_effect=AssertionError("training practice snippets must be blocked before evaluation")
        )

        evaluate_response = client.post(
            "/evaluate/snippet",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-training-snippet-guard",
                "task_spec_id": "task-practice-snippet-guard",
                "language_id": "python",
                "content": "def looks_ok():\n    return True\n",
                "evaluation_source": "training",
                "training_card_id": "practice-snippet-guard-1",
                "training_card_title": "Reject snippet-only practice proof",
            },
        )
        assert evaluate_response.status_code == 200
        report = evaluate_response.json()
        assert report["passed"] is False
        assert report["static_checks"][0]["id"] == "current-file-required"
        assert "current IDE file" in report["summary"]
        runtime.evaluator_service.evaluate_snippet.assert_not_called()

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        workspace = summary_response.json()["memory"]["workspace"]
        assert workspace["selected_card_id"] == "practice-snippet-guard-1"
        assert workspace["selected_card_status"] == "active"
        assert workspace["latest_training_submode"] == "practice"
        assert workspace["latest_learning_verified_result"] == ""
        assert workspace["latest_learning_blocker"] == ""
        assert workspace["latest_learning_outcome"] == "verification_pending"
        assert workspace["latest_training_handoff"]["return_mode"] == "verification_required"
        assert workspace["latest_training_handoff"]["verification_state"] == "verification_required"
        assert workspace["latest_training_handoff"]["source_chain"] == [
            "training",
            "snippet_or_selection",
            "learner_return",
        ]
        assert workspace["latest_training_next_hop"]["status"] == "verification_required"
        assert workspace["latest_training_next_hop"]["blocked_by"] == ""


def test_training_generate_card_keeps_explicit_flash_mode_for_conversation_gap(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-training-flash-mode",
                "workspace_name": "trainer-training-flash-mode",
                "profile": {
                    "long_term_goal": "Keep learn-first and flash follow-up truthful",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200

        generate_response = client.post(
            "/training/generate-card",
            json={
                "workspace_id": "workspace-training-flash-mode",
                "source": "conversation_gap",
                "card_type": "flash",
                "focus_area": "VS Code Remote SSH credential mode",
                "context_hint": "The learner is confused about where the API key should live in a remote workspace.",
                "response_language": "en-US",
            },
        )
        assert generate_response.status_code == 200
        payload = generate_response.json()
        assert payload["card"]["card_type"] == "flash"
        assert payload["card"]["scenario_pack"] == "remote_workspace"
        assert payload["card"]["question"]
        assert payload["active_routing"]["selected_card"]["card_type"] == "flash"
        runtime = client.app.state.runtime
        sandbox_root = runtime.sandbox_service.ensure_workspace_root("workspace-training-flash-mode")
        assert (sandbox_root / "cards" / "flash" / f"{payload['card']['card_id']}.md").exists()
        assert (sandbox_root / "cards" / "current" / "active.md").exists()

        active_response = client.get(
            "/training/active-card",
            params={"workspace_id": "workspace-training-flash-mode"},
        )
        assert active_response.status_code == 200
        active_payload = active_response.json()
        assert active_payload["selected_card"]["card_type"] == "flash"
        assert active_payload["selected_card"]["scenario_pack"] == "remote_workspace"


def test_training_generate_card_uses_nested_function_facts_and_legacy_source(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "function-training-root"
    workspace_root.mkdir()
    workspace_id = "workspace-training-nested-function"
    file_path = workspace_root / "src" / "demo.ts"

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "trainer-training-nested-function",
                "workspace_path": str(workspace_root),
            },
        )
        assert start_response.status_code == 200, start_response.text

        response = client.post(
            "/training/generate-card",
            json={
                "workspace_id": workspace_id,
                # Older webviews may still send this source name.
                "source": "conversation",
                "card_type": "practice",
                "focus_area": "function guidance",
                "target_skill": "function contract",
                "context_hint": "Read the TypeScript function contract before editing.",
                "current_file_path": "C:/outside/attacker.ts",
                "workspace_root_path": "C:/outside",
                "remote_workspace_name": "attacker-remote",
                "current_file": {
                    "path": str(file_path),
                    "language_id": "typescript",
                    "content": (
                        "export async function fetchLesson(lessonId: string): Promise<Response> {\n"
                        "  return request(`/api/lessons/${lessonId}`);\n"
                        "}"
                    ),
                    "selection_text": "export async function fetchLesson(lessonId: string) { return request(lessonId); }",
                    "selection_range": "1:1-3:2",
                },
            },
        )

    assert response.status_code == 200, response.text
    card = response.json()["card"]
    card_text = str(card)
    assert card["created_from"] == "conversation"
    assert card["scenario_pack"] == "function_guidance"
    assert card["files_to_touch"] == ["src/demo.ts"]
    assert "fetchLesson" in card_text
    assert str(workspace_root) not in card_text
    assert "attacker.ts" not in card_text
    assert "attacker-remote" not in card_text


def test_training_generate_card_redacts_debug_facts_before_card_persistence(tmp_path: Path) -> None:
    workspace_root = tmp_path / "debug-training-root"
    workspace_root.mkdir()
    workspace_id = "workspace-training-nested-debug"
    file_path = workspace_root / "src" / "debug.ts"
    secret = "sk-live-secret-123456789"

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "trainer-training-nested-debug",
                "workspace_path": str(workspace_root),
            },
        )
        assert start_response.status_code == 200, start_response.text

        response = client.post(
            "/training/generate-card",
            json={
                "workspace_id": workspace_id,
                "card_type": "practice",
                "focus_area": "VS Code debug loop",
                "target_skill": "diagnostic reproduction",
                "context_hint": "Use one breakpoint to reproduce the reported diagnostic.",
                "current_file": {
                    "path": str(file_path),
                    "language_id": "typescript",
                    "content": "export const status = response.payload.id;",
                    "diagnostics": [
                        f"[error] {file_path}:1 Authorization: Bearer {secret}",
                    ],
                },
            },
        )

    assert response.status_code == 200, response.text
    card = response.json()["card"]
    card_text = str(card)
    assert card["scenario_pack"] == "debug_loop"
    assert card["files_to_touch"] == ["src/debug.ts"]
    assert "[redacted" in card_text
    assert str(workspace_root) not in card_text
    assert secret not in card_text


def test_training_generate_card_uses_session_remote_facts_without_persisting_root(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "remote-training-root"
    workspace_root.mkdir()
    workspace_id = "workspace-training-nested-remote"
    file_path = workspace_root / "src" / "remote.ts"

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "trainer-training-nested-remote",
                "workspace_path": str(workspace_root),
                "remoteName": "ssh-remote+lab",
            },
        )
        assert start_response.status_code == 200, start_response.text

        response = client.post(
            "/training/generate-card",
            json={
                "workspace_id": workspace_id,
                "card_type": "practice",
                "focus_area": "VS Code remote workspace",
                "target_skill": "remote workspace boundary",
                "context_hint": "Check the Remote SSH credential boundary before editing.",
                "workspace_root_path": "C:/attacker-root",
                "remote_workspace_name": "attacker-remote",
                "current_file": {
                    "path": str(file_path),
                    "language_id": "typescript",
                    "content": "export const remoteMode = 'ssh';",
                },
            },
        )

    assert response.status_code == 200, response.text
    card = response.json()["card"]
    card_text = str(card)
    assert card["scenario_pack"] == "remote_workspace"
    assert card["files_to_touch"] == ["src/remote.ts"]
    assert "ssh-remote+lab" in card_text
    assert "workspace root" in card_text
    assert str(workspace_root) not in card_text
    assert "attacker-root" not in card_text
    assert "attacker-remote" not in card_text


def test_training_generate_card_rejects_untrusted_file_uri_and_flat_facts(tmp_path: Path) -> None:
    workspace_root = tmp_path / "untrusted-training-root"
    workspace_root.mkdir()
    workspace_id = "workspace-training-untrusted-facts"

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "trainer-training-untrusted-facts",
                "workspace_path": str(workspace_root),
            },
        )
        assert start_response.status_code == 200, start_response.text

        response = client.post(
            "/training/generate-card",
            json={
                "workspace_id": workspace_id,
                "card_type": "practice",
                "focus_area": "function guidance",
                "target_skill": "function contract",
                "context_hint": "Inspect one function before editing.",
                "current_file_path": "C:/outside/attacker.ts",
                "current_file_diagnostics": ["Bearer sk-outside-secret-123456789"],
                "workspace_root_path": "C:/outside",
                "remote_workspace_name": "attacker-remote",
                "current_file": {
                    "path": "vscode-remote://ssh-remote+attacker/outside.ts",
                    "language_id": "typescript",
                    "content": "export function stolenToken() { return 'sk-outside-secret-123456789'; }",
                    "diagnostics": ["Bearer sk-outside-secret-123456789"],
                },
            },
        )

    assert response.status_code == 200, response.text
    card = response.json()["card"]
    card_text = str(card)
    assert card["scenario_pack"] == "function_guidance"
    assert card["status"] == "needs_primer"
    assert card["files_to_touch"] == []
    assert "attacker" not in card_text
    assert "sk-outside-secret-123456789" not in card_text
    assert str(workspace_root) not in card_text


def test_training_generate_card_projects_only_indexed_resource_evidence(tmp_path: Path) -> None:
    trainer_root = tmp_path / "trainer-resource-root"
    workspace_root = trainer_root / "resource-evidence-root"
    workspace_root.mkdir(parents=True)
    workspace_id = "workspace-training-resource-evidence"
    trusted_resource = ResourceRecord(
        id="resource-trusted-timeout",
        kind="text",
        name="HTTPX timeout guide",
        source="https://trusted.example/httpx-timeouts",
        summary="HTTPX timeout guide",
        parse_status="parsed",
        index_status="indexed",
        source_type="url:reference",
        trust_score=0.95,
        freshness="fresh",
        knowledge_fragments=[
            {
                "id": "fragment-trusted-timeout",
                "resource_id": "resource-trusted-timeout",
                "snippet": "HTTPX separates connect and read timeout limits.",
                "summary": "HTTPX separates connect and read timeout limits.",
                "evidence_summary": "HTTPX separates connect and read timeout limits.",
                "focus_area": "HTTPX timeout behavior",
                "source": "https://trusted.example/httpx-timeouts",
                "source_type": "url:reference",
                "trust_score": 0.95,
                "freshness": "fresh",
            }
        ],
    )

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        provisioning = runtime.provision_project_adoption(
            workspace_id=workspace_id,
            root_path=str(trainer_root),
            project_path=str(workspace_root),
            project_name="trainer-training-resource-evidence",
        )
        managed_workspace_id = provisioning.context_id
        runtime.repository.save_resource(managed_workspace_id, trusted_resource)

        with patch.object(
            runtime.card_generation_service,
            "_try_llm_generation",
            side_effect=AssertionError("governed resource cards must not call the provider"),
        ):
            response = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": managed_workspace_id,
                    "source": "resource_knowledge",
                    "card_type": "practice",
                    "resource_id": trusted_resource.id,
                    "focus_area": "client-selected focus must not be used",
                    "context_hint": "https://attacker.invalid/raw-resource-context",
                    "resourceKnowledgeEvidence": {
                        "resourceId": "attacker-resource",
                        "fragmentId": "client-forged-fragment",
                        "sourceType": "url",
                        "focusArea": "client-forged focus",
                        "summary": "client-forged summary",
                    },
                },
            )

    assert response.status_code == 200, response.text
    card = response.json()["card"]
    card_text = str(card)
    assert card["status"] == "candidate"
    assert card["scenario_pack"] == "resource_knowledge"
    assert any("fragment-trusted-timeout" in item for item in card["source_chain"])
    assert "HTTPX separates connect and read timeout limits." in card_text
    assert "client-selected focus" not in card_text
    assert "attacker.invalid" not in card_text
    assert "client-forged" not in card_text


def test_training_generate_card_reuses_open_resource_card_before_creating_another(tmp_path: Path) -> None:
    trainer_root = tmp_path / "trainer-resource-card-idempotency-root"
    workspace_root = trainer_root / "resource-card-idempotency-project"
    workspace_root.mkdir(parents=True)
    workspace_id = "workspace-training-resource-card-idempotency"
    trusted_resource = ResourceRecord(
        id="resource-idempotent-timeout",
        kind="text",
        name="HTTPX timeout guide",
        source="https://trusted.example/httpx-timeouts",
        summary="HTTPX timeout guide",
        parse_status="parsed",
        index_status="indexed",
        source_type="url:reference",
        trust_score=0.95,
        freshness="fresh",
        knowledge_fragments=[
            {
                "id": "fragment-idempotent-timeout",
                "resource_id": "resource-idempotent-timeout",
                "snippet": "HTTPX separates connect and read timeout limits.",
                "summary": "HTTPX separates connect and read timeout limits.",
                "evidence_summary": "HTTPX separates connect and read timeout limits.",
                "focus_area": "HTTPX timeout behavior",
                "source": "https://trusted.example/httpx-timeouts",
                "source_type": "url:reference",
                "trust_score": 0.95,
                "freshness": "fresh",
            }
        ],
    )
    request_payload = {
        "source": "resource_knowledge",
        "card_type": "flash",
        "resource_id": trusted_resource.id,
    }

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        provisioning = runtime.provision_project_adoption(
            workspace_id=workspace_id,
            root_path=str(trainer_root),
            project_path=str(workspace_root),
            project_name="resource-card-idempotency-project",
        )
        managed_workspace_id = provisioning.context_id
        runtime.repository.save_resource(managed_workspace_id, trusted_resource)

        first = client.post(
            "/training/generate-card",
            json={"workspace_id": managed_workspace_id, **request_payload},
        )
        second = client.post(
            "/training/generate-card",
            json={
                "workspace_id": managed_workspace_id,
                **request_payload,
                "resource_id": f" {trusted_resource.id} ",
            },
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        first_card_id = first.json()["card"]["card_id"]
        assert second.json()["card"]["card_id"] == first_card_id
        assert [card.card_id for card in runtime.memory_service.get_cards(managed_workspace_id)] == [
            first_card_id
        ]

        runtime.memory_service.transition_card_status(
            managed_workspace_id,
            first_card_id,
            "answered",
            reason="Regression test: resource card was answered.",
        )
        runtime.memory_service.transition_card_status(
            managed_workspace_id,
            first_card_id,
            "reviewed",
            reason="Regression test: completed resource card may be regenerated.",
        )
        regenerated = client.post(
            "/training/generate-card",
            json={"workspace_id": managed_workspace_id, **request_payload},
        )

        assert regenerated.status_code == 200, regenerated.text
        assert regenerated.json()["card"]["card_id"] != first_card_id
        assert len(runtime.memory_service.get_cards(managed_workspace_id)) == 2


def test_training_generate_card_rejects_unready_resource_cards_before_persisting(tmp_path: Path) -> None:
    trainer_root = tmp_path / "trainer-resource-card-root"
    workspace_root = trainer_root / "resource-card-project"
    workspace_root.mkdir(parents=True)
    workspace_id = "workspace-training-resource-card-gate"

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        provisioning = runtime.provision_project_adoption(
            workspace_id=workspace_id,
            root_path=str(trainer_root),
            project_path=str(workspace_root),
            project_name="resource-card-project",
        )
        managed_workspace_id = provisioning.context_id
        resources = [
            ResourceRecord(
                id="resource-pending",
                kind="text",
                name="Pending notes",
                source="pending.txt",
                parse_status="parsed",
                index_status="pending",
                trust_score=0.95,
                freshness="fresh",
            ),
            ResourceRecord(
                id="resource-stale",
                kind="text",
                name="Stale notes",
                source="stale.txt",
                parse_status="parsed",
                index_status="indexed",
                trust_score=0.95,
                freshness="stale",
            ),
            ResourceRecord(
                id="resource-untrusted",
                kind="text",
                name="Untrusted notes",
                source="untrusted.txt",
                parse_status="parsed",
                index_status="indexed",
                trust_score=0.2,
                freshness="fresh",
            ),
            ResourceRecord(
                id="resource-blocked",
                kind="text",
                name="Blocked notes",
                source="blocked.txt",
                parse_status="parsed",
                index_status="indexed",
                trust_score=0.95,
                freshness="fresh",
                quality_flags=["blocked_source"],
            ),
            ResourceRecord(
                id="resource-without-evidence",
                kind="text",
                name="Empty notes",
                source="empty.txt",
                parse_status="parsed",
                index_status="indexed",
                trust_score=0.95,
                freshness="fresh",
            ),
        ]
        for resource in resources:
            runtime.repository.save_resource(managed_workspace_id, resource)

        with patch.object(
            runtime.card_generation_service,
            "_try_llm_generation",
            side_effect=AssertionError("unready resource cards must not call the provider"),
        ):
            for resource_id in ["missing-resource", *(resource.id for resource in resources)]:
                response = client.post(
                    "/training/generate-card",
                    json={
                        "workspace_id": managed_workspace_id,
                        "source": "resource_knowledge",
                        "card_type": "practice",
                        "resource_id": resource_id,
                    },
                )
                assert response.status_code == 409, response.text
                assert runtime.memory_service.get_cards(managed_workspace_id) == []

        unmanaged = client.post(
            "/training/generate-card",
            json={
                "workspace_id": "workspace-resource-not-managed",
                "source": "resource_knowledge",
                "card_type": "practice",
                "resource_id": "missing-resource",
            },
        )

    assert unmanaged.status_code == 409, unmanaged.text
    assert "Add this project" in unmanaged.json()["detail"]


def test_training_generate_card_dependency_requires_verified_file_evidence(tmp_path: Path) -> None:
    workspace_root = tmp_path / "dependency-evidence-root"
    source_dir = workspace_root / "src"
    source_dir.mkdir(parents=True)
    client_file = source_dir / "client.py"
    client_file.write_text("import httpx\nclient = httpx.Client()\n", encoding="utf-8")
    comment_file = source_dir / "comment_only.py"
    comment_file.write_text(
        "# import httpx\nvalue = 1  # httpx.Client()\nnote = 'import httpx'\n",
        encoding="utf-8",
    )
    commonjs_file = source_dir / "client.js"
    commonjs_file.write_text(
        "const httpx = require('httpx');\nhttpx.Client();\n",
        encoding="utf-8",
    )
    workspace_id = "workspace-training-dependency-evidence"

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "trainer-training-dependency-evidence",
                "workspace_path": str(workspace_root),
            },
        )
        assert start_response.status_code == 200, start_response.text
        runtime = client.app.state.runtime

        with patch.object(
            runtime.card_generation_service,
            "_try_llm_generation",
            side_effect=AssertionError("governed dependency cards must not call the provider"),
        ):
            verified_response = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "source": "dependency_mastery",
                    "card_type": "practice",
                    "target_skill": "httpx.Client API",
                    "context_hint": "https://attacker.invalid/raw-dependency-context",
                    "dependencyUsageEvidence": [
                        {
                            "filePath": "src/client.py",
                            "kind": "import",
                            "identifier": "requests",
                            "summary": "client-forged evidence",
                        }
                    ],
                    "currentFile": {
                        "path": str(client_file),
                        "languageId": "python",
                        "content": client_file.read_text(encoding="utf-8"),
                    },
                },
            )
            fake_relative_response = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "source": "dependency_mastery",
                    "card_type": "flash",
                    "target_skill": "httpx.Client API",
                    "currentFile": {
                        "path": "src/invented.py",
                        "languageId": "python",
                        "content": "import httpx\nhttpx.Client()\n",
                    },
                },
            )
            comment_only_response = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "source": "dependency_mastery",
                    "card_type": "flash",
                    "target_skill": "httpx.Client API",
                    "currentFile": {
                        "path": str(comment_file),
                        "languageId": "python",
                        "content": comment_file.read_text(encoding="utf-8"),
                    },
                },
            )
            commonjs_response = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "source": "dependency_mastery",
                    "card_type": "flash",
                    "target_skill": "httpx.Client API",
                    "currentFile": {
                        "path": str(commonjs_file),
                        "languageId": "javascript",
                        "content": commonjs_file.read_text(encoding="utf-8"),
                    },
                },
            )

    assert verified_response.status_code == 200, verified_response.text
    verified_card = verified_response.json()["card"]
    assert verified_card["status"] == "candidate"
    assert verified_card["files_to_touch"] == ["src/client.py"]
    assert any("Verified import: import httpx in src/client.py" in item for item in verified_card["source_chain"])
    assert "attacker.invalid" not in str(verified_card)
    assert "client-forged evidence" not in str(verified_card)

    assert commonjs_response.status_code == 200, commonjs_response.text
    commonjs_card = commonjs_response.json()["card"]
    assert commonjs_card["status"] == "candidate"
    assert commonjs_card["files_to_touch"] == ["src/client.js"]
    assert any("Verified import: import httpx in src/client.js" in item for item in commonjs_card["source_chain"])

    for response in (fake_relative_response, comment_only_response):
        assert response.status_code == 200, response.text
        card = response.json()["card"]
        assert card["status"] == "needs_primer"
        assert card["files_to_touch"] == []
        assert "verified import, call, or declaration" in card["return_with"]


def test_training_active_card_prefers_same_topic_practice_before_flash(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-training-learn-first",
                "workspace_name": "trainer-training-learn-first",
                "profile": {
                    "long_term_goal": "Learn first, then test without losing the active practice card",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200

        practice_response = client.post(
            "/training/generate-card",
            json={
                "workspace_id": "workspace-training-learn-first",
                "source": "conversation_gap",
                "card_type": "practice",
                "focus_area": "VS Code remote workspace",
                "target_skill": "remote workspace boundary",
                "context_hint": "Learn the remote boundary first, then test it with one tiny verified step.",
                "response_language": "en-US",
            },
        )
        assert practice_response.status_code == 200
        practice_payload = practice_response.json()
        assert practice_payload["active_routing"]["selected_card"]["card_type"] == "practice"

        flash_response = client.post(
            "/training/generate-card",
            json={
                "workspace_id": "workspace-training-learn-first",
                "source": "conversation_gap",
                "card_type": "flash",
                "focus_area": "VS Code remote workspace",
                "target_skill": "remote workspace boundary",
                "context_hint": "Learn the remote boundary first, then test it with one tiny verified step.",
                "response_language": "en-US",
            },
        )
        assert flash_response.status_code == 200
        flash_payload = flash_response.json()
        assert flash_payload["card"]["card_type"] == "flash"
        assert flash_payload["active_routing"]["selected_card"]["card_type"] == "practice"
        assert flash_payload["active_routing"]["candidate_count"] == 2
        runtime = client.app.state.runtime
        sandbox_root = runtime.sandbox_service.ensure_workspace_root("workspace-training-learn-first")
        assert (sandbox_root / "cards" / "scenario" / f"{practice_payload['card']['card_id']}.md").exists()
        assert list((sandbox_root / "cards" / "flash").glob("*.md"))
        assert (sandbox_root / "cards" / "current" / "active.md").exists()

        active_response = client.get(
            "/training/active-card",
            params={"workspace_id": "workspace-training-learn-first"},
        )
        assert active_response.status_code == 200
        active_payload = active_response.json()
        assert active_payload["selected_card"]["card_type"] == "practice"
        assert active_payload["selected_card"]["scenario_pack"] == "remote_workspace"
        assert active_payload["candidate_count"] == 2
        assert any("Flash: Remote workspace boundary" in reason for reason in active_payload["why_not_others"])

        runtime = client.app.state.runtime
        cards = runtime.memory_service.get_cards("workspace-training-learn-first")
        status_by_type = {card.card_type: card.status for card in cards}
        assert status_by_type["practice"] == "needs_primer"
        assert status_by_type["flash"] == "needs_primer"

        summary_response = client.get(
            "/memory/summary",
            params={"workspace_id": "workspace-training-learn-first"},
        )
        assert summary_response.status_code == 200
        workspace = summary_response.json()["memory"]["workspace"]
        assert workspace["selected_card_status"] == "needs_primer"
        assert workspace["latest_training_submode"] == "practice"


def test_session_message_explicit_training_card_request_stays_hint_only(tmp_path: Path) -> None:
    """Composer chat must not mint; POST /training/generate-card remains the binder."""

    async def fake_coaching_reply(*args, **kwargs) -> str:
        return "I can outline the debug loop first; use Training generate-card to mint."

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=fake_coaching_reply),
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-coach-training-card",
                "workspace_name": "trainer-coach-training-card",
                "profile": {
                    "long_term_goal": "Keep explicit Coach training-card asks truthful",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-coach-training-card",
                "message": (
                    "Create a learn-first training card for understanding a VS Code debug loop. "
                    "I want the primer before any test."
                ),
                "response_language": "en-US",
                "current_file": {
                    "path": "src/session.ts",
                    "language_id": "typescript",
                    "content": "export function loadSession() { return undefined; }",
                    "diagnostics": ["TypeError: Cannot read properties of undefined (reading 'id')"],
                },
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        memory = payload["snapshot"]["memory"]
        assert memory["active_training_card_routing"] is None
        workspace = memory.get("workspace") or {}
        assert not str(workspace.get("selected_card_id") or "").strip()

        runtime = client.app.state.runtime
        assert runtime.memory_service.get_cards("workspace-coach-training-card") == []
        assert (
            runtime.memory_service.snapshot(
                "workspace-coach-training-card"
            ).active_training_card_routing
            is None
        )


def test_turn_guided_remote_coach_request_stays_in_coach_without_explicit_training_card(
    tmp_path: Path,
) -> None:
    async def fake_coaching_reply_agentic(*args, **kwargs) -> dict[str, object]:
        return {
            "content": (
                "我们先把 VS Code Remote SSH 的连接边界说清楚，再验证一个最小事实。"
            ),
            "summary": "先留在远程工作区这条主线。",
            "next_step": "说出一个真实的工作区边界，再继续排查。",
            "stop_reason": "completed",
        }

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "coaching_reply_agentic",
            new=AsyncMock(side_effect=fake_coaching_reply_agentic),
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-turn-learn-first-remote-card",
                "workspace_name": "trainer-turn-learn-first-remote-card",
                "profile": {
                    "long_term_goal": "先把远程工作区问题讲清楚并能验证",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200, start_response.text
        session_id = start_response.json()["session_id"]
        override_provider = ProviderConfig(
            name="turn-openai-compatible",
            base_url="http://minimax.redfast.top",
            api_key_ref="trainer.turn.remote",
            model="MiniMax-M3",
            protocol="openai_chat_completions_compatible",
            capabilities={"tools": True, "streaming": True},
        )
        seed_verified_capabilities(
            client.app.state.runtime,
            override_provider,
            "sk-test",
            tools=True,
        )

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-turn-learn-first-remote-card",
                "intent": "coach",
                "message": (
                    "教我一步一步排查 VS Code Remote SSH 的连接问题并验证。"
                    "先讲清楚，再给我一个很小的可验证动作；不要直接给我训练卡。"
                ),
                "response_language": "zh-CN",
                "answer_mode": "guided",
                "use_agent_loop": True,
                "api_key": "sk-test",
                "provider": {
                    "name": "turn-openai-compatible",
                    "baseUrl": "http://minimax.redfast.top",
                    "apiKeyRef": "trainer.turn.remote",
                    "model": "MiniMax-M3",
                    "protocol": "openai_chat_completions_compatible",
                    "capabilities": {"tools": True, "streaming": True},
                },
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "remote_workspace"
    assert payload["snapshot"]["memory"]["active_training_card_routing"] is None
    assert "连接边界" in payload["reply"]["content"]

    runtime = client.app.state.runtime
    cards = runtime.memory_service.get_cards("workspace-turn-learn-first-remote-card")
    assert cards == []


def test_session_message_first_class_lane_uses_canonical_focus_labels(tmp_path: Path) -> None:
    async def fake_coaching_reply(*args, **kwargs) -> str:
        return "Stay on the remote boundary, learn it first, and verify one tiny fact."

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=fake_coaching_reply),
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-canonical-focus",
                "workspace_name": "trainer-canonical-focus",
                "profile": {
                    "long_term_goal": "Keep first-class lane focus labels stable",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-canonical-focus",
                "message": (
                    "Teach me the smallest safe VS Code remote workspace boundary. "
                    "Learn first, then give me one tiny verification step."
                ),
                "response_language": "en-US",
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        memory = payload["snapshot"]["memory"]
        assert "Teach me" not in memory["review_rhythm"]
        assert "VS Code remote workspace" in memory["review_rhythm"]
        assert memory["active_thread"]["focus_area"] == "VS Code remote workspace"


def test_session_message_function_guidance_uses_chinese_canonical_focus_label(
    tmp_path: Path,
) -> None:
    async def fake_coaching_reply(*args, **kwargs) -> str:
        return "Start at one live call site, then use hover and signature help to recover the contract."

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=fake_coaching_reply),
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-function-focus-zh",
                "workspace_name": "trainer-function-focus-zh",
                "profile": {
                    "long_term_goal": "Keep function guidance labels aligned with the learner language",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-function-focus-zh",
                "message": "Teach me VS Code function hints from one call site before testing me.",
                "response_language": "zh-CN",
                "answer_mode": "guided",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    assert payload["snapshot"]["memory"]["active_thread"]["focus_area"] == "\u51fd\u6570\u5951\u7ea6\u5224\u65ad"


def test_repeated_failed_snippet_evaluation_tightens_adaptive_coaching(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-learning-loop-tighten",
                "workspace_name": "trainer-learning-loop-tighten",
                "profile": {
                    "long_term_goal": "Adapt coaching after repeated evaluation failure",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-learning-loop-tighten",
                "objectives": ["Adapt coaching after repeated evaluation failure"],
            },
        )
        assert generated.status_code == 200, generated.text

        task_response = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-learning-loop-tighten",
                "natural_language_goal": (
                    "Handle the invalid config branch.\n"
                    "Return a typed error payload.\n"
                    "Keep the slice reviewable in one pass."
                ),
            },
        )
        assert task_response.status_code == 200
        task_id = task_response.json()["id"]
        runtime.evaluator_service.evaluate_snippet = MagicMock(
            return_value=EvaluationReport(
                task_spec_id=task_id,
                summary="Evaluation failed on: pyright.",
                static_checks=[
                    EvaluationCheck(
                        id="pyright",
                        label="pyright",
                        status="failed",
                        detail="Type mismatch in config branch.",
                    )
                ],
                dynamic_checks=[],
                semantic_checks=[
                    EvaluationCheck(
                        id="semantic-review",
                        label="semantic-review",
                        status="failed",
                        detail="Handle the invalid config branch.\nReturn a typed error payload.",
                    )
                ],
                next_step="Handle the invalid config branch first.",
                reflection="The config branch still fails.",
                passed=False,
            )
        )

        broken_code = "def add(a: int, b: int) -> int:\n    return a - b\n"
        for _ in range(2):
            evaluate_response = client.post(
                "/evaluate/snippet",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-learning-loop-tighten",
                    "task_spec_id": task_id,
                    "language_id": "python",
                    "content": broken_code,
                },
            )
            assert evaluate_response.status_code == 200

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        payload = summary_response.json()
        latest = payload["memory"]["learning_outcomes"][0]
        adaptation = payload["memory"]["coaching_adaptation"]
        assert latest["outcome"] == "repeated_error"
        assert latest["repetition_count"] >= 2
        assert adaptation["next_step_bias"] == "shrink"
        assert adaptation["review_urgency"] == "high"
        assert adaptation["hint_depth"] == "direct"


def test_first_failed_snippet_evaluation_records_evaluation_not_repeated_error(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-single-evaluation-failure",
                "workspace_name": "trainer-single-evaluation-failure",
                "profile": {
                    "long_term_goal": "Distinguish first failure from repeated failure",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-single-evaluation-failure",
                "objectives": ["Handle a single evaluation failure under a live plan"],
            },
        )
        assert generated.status_code == 200, generated.text

        task_response = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-single-evaluation-failure",
                "natural_language_goal": (
                    "Handle the invalid config branch.\n"
                    "Return a typed error payload.\n"
                    "Keep the slice reviewable in one pass."
                ),
            },
        )
        assert task_response.status_code == 200
        task_id = task_response.json()["id"]
        runtime.evaluator_service.evaluate_snippet = MagicMock(
            return_value=EvaluationReport(
                task_spec_id=task_id,
                summary="Evaluation failed on: pyright.",
                static_checks=[
                    EvaluationCheck(
                        id="pyright",
                        label="pyright",
                        status="failed",
                        detail="Type mismatch in config branch.",
                    )
                ],
                dynamic_checks=[],
                semantic_checks=[
                    EvaluationCheck(
                        id="semantic-review",
                        label="semantic-review",
                        status="failed",
                        detail="Handle the invalid config branch.\nReturn a typed error payload.",
                    )
                ],
                next_step="Handle the invalid config branch first.",
                reflection="The config branch still fails.",
                passed=False,
            )
        )

        evaluate_response = client.post(
            "/evaluate/snippet",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-single-evaluation-failure",
                "task_spec_id": task_id,
                "language_id": "python",
                "content": "def add(a: int, b: int) -> int:\n    return a - b\n",
            },
        )
        assert evaluate_response.status_code == 200

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        memory_payload = summary_response.json()["memory"]
        latest = memory_payload["learning_outcomes"][0]
        assert latest["outcome"] == "evaluation"
        assert latest["repetition_count"] == 1
        # First failure must not escalate to repeated_error. Bias/urgency may tighten
        # when missing_requirements are present on the report.
        assert memory_payload["coaching_adaptation"]["next_step_bias"] in {"steady", "shrink"}
        assert memory_payload["coaching_adaptation"]["review_urgency"] in {"normal", "high"}
        assert latest["missing_requirements"] == [
            "Handle the invalid config branch.",
            "Return a typed error payload.",
        ]


def test_second_failed_snippet_evaluation_with_different_failure_family_does_not_escalate_to_repeated_error(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-different-evaluation-families",
                "workspace_name": "trainer-different-evaluation-families",
                "profile": {
                    "long_term_goal": "Keep different failed evaluations from collapsing together",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-different-evaluation-families",
                "objectives": ["Compare different evaluation families under a live plan"],
            },
        )
        assert generated.status_code == 200, generated.text

        task_response = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-different-evaluation-families",
                "natural_language_goal": (
                    "Handle the invalid config branch.\n"
                    "Return a typed error payload.\n"
                    "Keep the slice reviewable in one pass."
                ),
            },
        )
        assert task_response.status_code == 200
        task_id = task_response.json()["id"]
        runtime.evaluator_service.evaluate_snippet = MagicMock(
            side_effect=[
                EvaluationReport(
                    task_spec_id=task_id,
                    summary="Evaluation failed on: pyright.",
                    static_checks=[
                        EvaluationCheck(
                            id="pyright",
                            label="pyright",
                            status="failed",
                            detail="Type mismatch in config branch.",
                        )
                    ],
                    dynamic_checks=[],
                    semantic_checks=[
                        EvaluationCheck(
                            id="semantic-review",
                            label="semantic-review",
                            status="failed",
                            detail="Handle the invalid config branch.\nReturn a typed error payload.",
                        )
                    ],
                    next_step="Handle the invalid config branch first.",
                    reflection="The config branch still fails.",
                    passed=False,
                ),
                EvaluationReport(
                    task_spec_id=task_id,
                    summary="Evaluation failed on: pytest.",
                    static_checks=[],
                    dynamic_checks=[
                        EvaluationCheck(
                            id="pytest",
                            label="pytest",
                            status="failed",
                            detail="Assertion failed in the success path.",
                        )
                    ],
                    semantic_checks=[
                        EvaluationCheck(
                            id="semantic-review",
                            label="semantic-review",
                            status="failed",
                            detail="Preserve the success path.\nAdd the focused regression test.",
                        )
                    ],
                    next_step="Preserve the success path first.",
                    reflection="A different failure family appeared.",
                    passed=False,
                ),
            ]
        )

        for _ in range(2):
            evaluate_response = client.post(
                "/evaluate/snippet",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-different-evaluation-families",
                    "task_spec_id": task_id,
                    "language_id": "python",
                    "content": "def add(a: int, b: int) -> int:\n    return a - b\n",
                },
            )
            assert evaluate_response.status_code == 200

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        latest = summary_response.json()["memory"]["learning_outcomes"][0]
        assert latest["outcome"] == "evaluation"
        assert latest["repetition_count"] == 1
        assert latest["missing_requirements"] == [
            "Preserve the success path.",
            "Add the focused regression test.",
        ]


def test_review_turn_evaluation_persists_learning_loop_without_duplicate_evaluation_outcome(tmp_path: Path) -> None:
    target_file = tmp_path / "review_learning_loop_sample.py"
    target_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-review-learning-loop",
                "workspace_name": "trainer-review-learning-loop",
                "profile": {
                    "long_term_goal": "Persist review evaluation into adaptive memory",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-review-learning-loop",
                "objectives": ["Persist review evaluation into adaptive memory"],
            },
        )
        assert plan_response.status_code == 200, plan_response.text

        task_response = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-review-learning-loop",
                "natural_language_goal": "Implement an add helper that returns the sum.",
            },
        )
        assert task_response.status_code == 200, task_response.text
        runtime = client.app.state.runtime
        runtime.evaluator_service.evaluate_current_file = MagicMock(
            return_value=EvaluationReport(
                task_spec_id=task_response.json()["id"],
                summary="Evaluation failed on: pyright.",
                static_checks=[
                    EvaluationCheck(
                        id="pyright",
                        label="pyright",
                        status="failed",
                        detail="Type mismatch in add path.",
                    )
                ],
                dynamic_checks=[],
                semantic_checks=[
                    EvaluationCheck(
                        id="semantic-review",
                        label="semantic-review",
                        status="failed",
                        detail="Return the correct addition result.\nKeep the function behavior aligned with the task.",
                    )
                ],
                next_step="Return the correct addition result first.",
                reflection="The first review pass still fails the main behavior.",
                passed=False,
            )
        )

        review_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-review-learning-loop",
                "intent": "review",
                "message": "Review this implementation and tell me the first thing to fix.",
                "response_language": "en-US",
                "answer_mode": "guided",
                "current_file": {
                    "path": str(target_file),
                    "language_id": "python",
                    "content": target_file.read_text(encoding="utf-8"),
                    "diagnostics": ["Function behavior is incorrect for normal addition."],
                },
            },
        )

        assert review_response.status_code == 200
        payload = review_response.json()
        outcomes = payload["snapshot"]["memory"]["learning_outcomes"]
        assert outcomes
        assert outcomes[0]["outcome"] == "evaluation"
        assert payload["snapshot"]["memory"]["workspace"]["latest_evaluation_feedback"]
        assert payload["snapshot"]["memory"]["coaching_adaptation"]["summary"]

        second_review_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-review-learning-loop",
                "intent": "review",
                "message": "Review this implementation again and tell me the first thing to fix.",
                "response_language": "en-US",
                "answer_mode": "guided",
                "current_file": {
                    "path": str(target_file),
                    "language_id": "python",
                    "content": target_file.read_text(encoding="utf-8"),
                    "diagnostics": ["Function behavior is incorrect for normal addition."],
                },
            },
        )

        assert second_review_response.status_code == 200
        second_payload = second_review_response.json()
        second_outcomes = second_payload["snapshot"]["memory"]["learning_outcomes"]
        assert second_outcomes
        assert second_outcomes[0]["outcome"] == "repeated_error"
        assert second_outcomes[0]["repetition_count"] == 2


def test_memory_settings_endpoint_persists_workspace_coach_defaults(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-settings",
                "workspace_name": "trainer-settings",
                "profile": {
                    "long_term_goal": "Keep coach settings across refreshes",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        settings_response = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
                "teaching_style": "hands-on",
                "coach_defaults": {
                    "memory_scope": "personal",
                    "working_set_mode": "broad",
                    "review_cadence": "light",
                    "review_reminder_mode": "digest",
                    "workspace_memory_toggles": {
                        "decisions": True,
                        "patterns": False,
                        "resources": True,
                    },
                },
                "follow_current_file": False,
                "context_detail": "full",
                "include_current_file": True,
                "include_selection": False,
                "include_diagnostics": True,
                "include_related_files": True,
            },
        )
        assert settings_response.status_code == 200

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        summary_payload = summary_response.json()
        assert summary_payload["profile"]["teaching_style"] == "hands-on"
        workspace = summary_payload["memory"]["workspace"]
        assert workspace["response_language"] == "zh-CN"
        assert workspace["answer_mode"] == "coach-first"
        assert workspace["follow_current_file"] is False
        assert workspace["context_detail"] == "full"
        assert workspace["include_current_file"] is True
        assert workspace["include_selection"] is False
        assert workspace["include_diagnostics"] is True
        assert workspace["include_related_files"] is True
        assert workspace["coach_defaults"]["memory_scope"] == "personal"
        assert workspace["coach_defaults"]["working_set_mode"] == "broad"
        assert workspace["coach_defaults"]["review_cadence"] == "light"
        assert workspace["coach_defaults"]["review_reminder_mode"] == "digest"
        assert workspace["workspace_memory_toggles"]["patterns"] is False


def test_session_message_uses_saved_teaching_style_bias_in_followup_prompt(tmp_path: Path) -> None:
    captured_messages: dict[str, object] = {}

    async def fake_create_chat_completion(
        self,
        *,
        client,
        model,
        messages,
        temperature,
        max_tokens,
        stream=False,
    ):
        captured_messages["messages"] = messages
        mock_choice = MagicMock()
        mock_choice.message.content = "Start with one thin boundary."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response, model

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=fake_create_chat_completion,
    ):
        with build_client(tmp_path) as client:
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": "workspace-style-bias",
                    "workspace_name": "trainer-style-bias",
                    "profile": {
                        "long_term_goal": "Keep teaching style stable across future turns",
                        "weekly_hours": 4,
                        "teaching_style": "guided",
                        "answer_policy": "guided",
                    },
                },
            )
            assert start_response.status_code == 200
            session_id = start_response.json()["session_id"]

            settings_response = client.post(
                "/memory/settings",
                json={
                    "session_id": session_id,
                    "response_language": "en-US",
                    "answer_mode": "guided",
                    "teaching_style": "challenging",
                },
            )
            assert settings_response.status_code == 200

            message_response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "message": "Help me implement the first thin slice of this feature.",
                    "provider": {
                        "name": "test-provider",
                        "base_url": "https://api.openai.com/v1",
                        "api_key_ref": "trainer.test",
                        "model": "gpt-4o-mini",
                    },
                    "api_key": "sk-test",
                },
            )

    assert message_response.status_code == 200
    assert message_response.json()["reply"]["content"].startswith("Start with one thin boundary.")
    system_prompt = captured_messages["messages"][0]["content"]
    assert "## Teaching Style Bias" in system_prompt
    assert "Active style: challenging" in system_prompt
    assert "Hold back the full answer a little longer." in system_prompt


def test_session_message_accepts_per_turn_teaching_style_override_without_saving_it(
    tmp_path: Path,
) -> None:
    captured_messages: dict[str, object] = {}

    async def fake_create_chat_completion(
        self,
        *,
        client,
        model,
        messages,
        temperature,
        max_tokens,
        stream=False,
    ):
        captured_messages["messages"] = messages
        mock_choice = MagicMock()
        mock_choice.message.content = "Try the first design move before I reveal more."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response, model

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=fake_create_chat_completion,
    ):
        with build_client(tmp_path) as client:
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": "workspace-style-override",
                    "workspace_name": "trainer-style-override",
                    "profile": {
                        "long_term_goal": "Keep per-turn teaching overrides separate from saved defaults",
                        "weekly_hours": 4,
                        "teaching_style": "guided",
                        "answer_policy": "guided",
                    },
                },
            )
            assert start_response.status_code == 200
            session_id = start_response.json()["session_id"]

            message_response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "message": "Challenge me on the next design choice and let me try first.",
                    "teaching_style": "challenging",
                    "provider": {
                        "name": "test-provider",
                        "base_url": "https://api.openai.com/v1",
                        "api_key_ref": "trainer.test",
                        "model": "gpt-4o-mini",
                    },
                    "api_key": "sk-test",
                },
            )
            assert message_response.status_code == 200

            profile_response = client.get("/memory/profile", params={"session_id": session_id})
            assert profile_response.status_code == 200

    system_prompt = captured_messages["messages"][0]["content"]
    assert "## Teaching Style Bias" in system_prompt
    assert "Active style: challenging" in system_prompt
    assert "Hold back the full answer a little longer." in system_prompt
    assert profile_response.json()["teaching_style"] == "guided"


def test_session_message_saved_auto_teaching_style_goes_hands_on_for_remote_boundary_turns(
    tmp_path: Path,
) -> None:
    captured_messages: dict[str, object] = {}

    async def fake_create_chat_completion(
        self,
        *,
        client,
        model,
        messages,
        temperature,
        max_tokens,
        stream=False,
    ):
        captured_messages["messages"] = messages
        mock_choice = MagicMock()
        mock_choice.message.content = "Start from one real workspace boundary."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response, model

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=fake_create_chat_completion,
    ):
        with build_client(tmp_path) as client:
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": "workspace-style-auto-remote",
                    "workspace_name": "trainer-style-auto-remote",
                    "profile": {
                        "long_term_goal": "Keep adaptive teaching truthful on remote turns",
                        "weekly_hours": 4,
                        "teaching_style": "auto",
                        "answer_policy": "guided",
                    },
                },
            )
            assert start_response.status_code == 200
            session_id = start_response.json()["session_id"]

            settings_response = client.post(
                "/memory/settings",
                json={
                    "session_id": session_id,
                    "teaching_style": "auto",
                },
            )
            assert settings_response.status_code == 200

            message_response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "message": (
                        "In VS Code Remote SSH, where should the API key live, and how do I verify "
                        "the workspace boundary before I change anything?"
                    ),
                    "provider": {
                        "name": "test-provider",
                        "base_url": "https://api.openai.com/v1",
                        "api_key_ref": "trainer.test",
                        "model": "gpt-4o-mini",
                    },
                    "api_key": "sk-test",
                },
            )
            assert message_response.status_code == 200

            profile_response = client.get("/memory/profile", params={"session_id": session_id})
            assert profile_response.status_code == 200

    system_prompt = captured_messages["messages"][0]["content"]
    assert "## Teaching Style Bias" in system_prompt
    assert "Active style: hands-on" in system_prompt
    assert "Bias toward concrete implementation moves" in system_prompt
    assert profile_response.json()["teaching_style"] == "auto"


def test_session_message_accepts_simple_provider_override_without_api_key_ref(
    tmp_path: Path,
) -> None:
    async def fake_create_chat_completion(
        self,
        *,
        client,
        model,
        messages,
        temperature,
        max_tokens,
        stream=False,
    ):
        mock_choice = MagicMock()
        mock_choice.message.content = "Keep the first patch tiny."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response, model

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=fake_create_chat_completion,
    ):
        with build_client(tmp_path, configure_provider=False) as client:
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": "workspace-simple-provider-override",
                    "workspace_name": "trainer-simple-provider-override",
                    "profile": {
                        "long_term_goal": "Allow lightweight provider overrides from preview smoke",
                        "weekly_hours": 4,
                        "teaching_style": "guided",
                        "answer_policy": "guided",
                    },
                },
            )
            assert start_response.status_code == 200
            session_id = start_response.json()["session_id"]

            message_response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "message": "Help me land the first thin slice.",
                    "response_language": "en-US",
                    "provider": {
                        "name": "preview-provider",
                        "baseUrl": "https://api.openai.com/v1",
                        "model": "gpt-4o-mini",
                    },
                    "api_key": "sk-preview",
                },
            )

    assert message_response.status_code == 200, message_response.text
    payload = message_response.json()
    assert payload["reply"]["content"].startswith("Keep the first patch tiny.")
    assert payload["coach_turn"].get("agent_meta", {}).get("agentic") is not True


def test_session_message_keeps_chinese_remote_ssh_request_in_remote_lane(
    tmp_path: Path,
) -> None:
    async def fake_create_chat_completion(
        self,
        *,
        client,
        model,
        messages,
        temperature,
        max_tokens,
        stream=False,
    ):
        mock_choice = MagicMock()
        mock_choice.message.content = (
            "??? VS Code Remote SSH ? workspace boundary?"
            "????? tiny checkpoint???? credential mode ????"
        )
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response, model

    message = "?????? VS Code Remote SSH ? workspace boundary?????? tiny checkpoint?"

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=fake_create_chat_completion,
    ):
        with build_client(tmp_path, configure_provider=False) as client:
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": "workspace-zh-remote-ssh-session-message",
                    "workspace_name": "trainer-zh-remote-ssh-session-message",
                    "profile": {
                        "long_term_goal": "Keep remote/debug/function lanes first-class.",
                        "weekly_hours": 4,
                        "teaching_style": "guided",
                        "answer_policy": "guided",
                    },
                },
            )
            assert start_response.status_code == 200
            session_id = start_response.json()["session_id"]

            message_response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-zh-remote-ssh-session-message",
                    "message": message,
                    "response_language": "zh-CN",
                    "use_agent_loop": False,
                    "provider": {
                        "name": "preview-provider",
                        "baseUrl": "https://api.openai.com/v1",
                        "model": "gpt-4o-mini",
                    },
                    "api_key": "sk-preview",
                },
            )

    assert message_response.status_code == 200, message_response.text
    payload = message_response.json()
    assert payload["coach_turn"]["scenario"] == "remote_workspace"
    assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "remote_workspace"
    assert payload["snapshot"]["memory"]["active_thread"]["scenario"] == "remote_workspace"
    assert "remote" in payload["reply"]["content"].lower()
    assert payload["snapshot"]["memory"]["current_focus"]


def test_session_message_language_corruption_does_not_reuse_previous_remote_lane_for_fresh_general_turn(
    tmp_path: Path,
) -> None:
    visible_choice = MagicMock()
    visible_choice.message.content = (
        "Start with the remote workspace boundary. First identify whether this workspace is SSH, "
        "tunnels, dev container, WSL, or local."
    )
    visible_response = MagicMock()
    visible_response.choices = [visible_choice]

    corrupt_choice = MagicMock()
    corrupt_choice.message.content = (
        "Glad you want to start with VS Code remote "
        "\u0431\u043a"
        " it's a great target because once the model clicks, debugging and run confi"
        "\u0431\u043d"
        " stay more stable."
    )
    corrupt_response = MagicMock()
    corrupt_response.choices = [corrupt_choice]

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=AsyncMock(
            side_effect=[
                (visible_response, "gpt-4o-mini"),
                (corrupt_response, "gpt-4o-mini"),
            ]
        ),
    ):
        with build_client(tmp_path, configure_provider=False) as client:
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": "workspace-session-message-corruption-fresh-general",
                    "workspace_name": "trainer-session-message-corruption-fresh-general",
                    "profile": {
                        "long_term_goal": "Keep fresh general session turns isolated from older remote lanes",
                        "weekly_hours": 4,
                        "teaching_style": "guided",
                        "answer_policy": "guided",
                    },
                },
            )
            assert start_response.status_code == 200
            session_id = start_response.json()["session_id"]

            remote_response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-session-message-corruption-fresh-general",
                    "message": "Teach me VS Code Remote SSH step by step. Keep it to one checkpoint first.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                    "provider": {
                        "name": "preview-provider",
                        "baseUrl": "https://api.openai.com/v1",
                        "model": "gpt-4o-mini",
                    },
                    "api_key": "sk-preview",
                },
            )
            assert remote_response.status_code == 200
            assert remote_response.json()["coach_turn"]["scenario"] == "remote_workspace"

            writing_response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-session-message-corruption-fresh-general",
                    "message": "????? Python ??????????????????????",
                    "response_language": "zh-CN",
                    "use_agent_loop": False,
                    "provider": {
                        "name": "preview-provider",
                        "baseUrl": "https://api.openai.com/v1",
                        "model": "gpt-4o-mini",
                    },
                    "api_key": "sk-preview",
                },
            )

    assert writing_response.status_code == 200, writing_response.text
    payload = writing_response.json()
    assert payload["agent_meta"]["stop_reason"] == "language_corruption_recovered"
    assert payload["agent_meta"]["scenario"] == "general"
    assert payload["coach_turn"]["scenario"] == "general"
    assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "general"
    assert payload["snapshot"]["memory"]["active_thread"]["scenario"] == "general"
    assert "这条回复没有读清" in payload["coach_turn"]["summary"]
    assert "请把刚才的问题再发一次" in payload["coach_turn"]["next_step"]
    assert "VS Code remote lane" not in payload["coach_turn"]["summary"]
    assert "这条回复没有读清" in payload["reply"]["content"]
    assert "VS Code remote" not in payload["reply"]["content"]
    assert "credential mode" not in payload["reply"]["content"]


def test_session_message_stream_accepts_simple_provider_override_without_api_key_ref(
    tmp_path: Path,
) -> None:
    chunk_1 = MagicMock()
    chunk_1.choices = [MagicMock()]
    chunk_1.choices[0].delta.content = "Keep the first reply grounded. "

    chunk_2 = MagicMock()
    chunk_2.choices = [MagicMock()]
    chunk_2.choices[0].delta.content = "Then verify one visible step."

    async def async_iter():
        for item in (chunk_1, chunk_2):
            yield item

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=AsyncMock(return_value=(async_iter(), "gpt-4o-mini")),
    ):
        with build_client(tmp_path, configure_provider=False) as client:
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": "workspace-simple-provider-override-stream",
                    "workspace_name": "trainer-simple-provider-override-stream",
                    "profile": {
                        "long_term_goal": "Allow lightweight stream provider overrides from preview smoke",
                        "weekly_hours": 4,
                        "teaching_style": "guided",
                        "answer_policy": "guided",
                    },
                },
            )
            assert start_response.status_code == 200
            session_id = start_response.json()["session_id"]
            override_provider = ProviderConfig(
                name="preview-provider",
                base_url="https://api.openai.com/v1",
                api_key_ref="",
                model="gpt-4o-mini",
                capabilities={"tools": False, "streaming": True},
            )
            seed_verified_capabilities(
                client.app.state.runtime,
                override_provider,
                "sk-preview",
                tools=False,
            )

            stream_response = client.post(
                "/session/message/stream",
                json={
                    "session_id": session_id,
                    "message": "Help me keep the first streamed reply grounded.",
                    "response_language": "en-US",
                    "provider": {
                        "name": "preview-provider",
                        "baseUrl": "https://api.openai.com/v1",
                        "model": "gpt-4o-mini",
                        "capabilities": {"tools": False, "streaming": True},
                    },
                    "api_key": "sk-preview",
                },
            )

    assert stream_response.status_code == 200, stream_response.text
    assert "event: complete" in stream_response.text
    assert "Keep the first reply grounded." in stream_response.text


def test_session_message_prefers_background_reference_summary_over_raw_snippet(tmp_path: Path) -> None:
    captured_messages: dict[str, object] = {}

    async def fake_create_chat_completion(
        self,
        *,
        client,
        model,
        messages,
        temperature,
        max_tokens,
        stream=False,
    ):
        captured_messages["messages"] = messages
        mock_choice = MagicMock()
        mock_choice.message.content = "Keep the grounding tight."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response, model

    note_file = tmp_path / "background-summary-note.md"
    note_file.write_text(
        "# Raw title and BOM noise should stay out of the prompt.\n\nThe distilled proof path is here.\n",
        encoding="utf-8",
    )

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=fake_create_chat_completion,
    ):
        with build_client(tmp_path) as client:
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": "workspace-background-summary",
                    "workspace_name": "trainer-background-summary",
                    "profile": {
                        "long_term_goal": "Keep background references summarized in coach prompts",
                        "weekly_hours": 4,
                        "teaching_style": "guided",
                        "answer_policy": "guided",
                    },
                },
            )
            assert start_response.status_code == 200
            session_id = start_response.json()["session_id"]

            upload_response = client.post(
                "/resource/upload",
                json={
                    "session_id": session_id,
                    "kind": "markdown",
                    "name": "Background Summary Note",
                    "source": str(note_file),
                },
            )
            assert upload_response.status_code == 200
            resource_id = upload_response.json()["id"]

            index_response = client.post(
                "/resource/index",
                json={"session_id": session_id, "resource_id": resource_id},
            )
            assert index_response.status_code == 200

            message_response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "message": "Keep the grounding tight.",
                    "resource_ids": [resource_id],
                    "response_language": "en-US",
                    "answer_mode": "coach-first",
                    "provider": {
                        "name": "test-provider",
                        "base_url": "https://api.openai.com/v1",
                        "api_key_ref": "trainer.test",
                        "model": "gpt-4o-mini",
                    },
                    "api_key": "sk-test",
                },
            )

    assert message_response.status_code == 200
    assert "Keep the grounding tight." in message_response.json()["reply"]["content"]
    system_prompt = captured_messages["messages"][0]["content"]
    assert "Background research summary: The distilled proof path is here." in system_prompt
    assert "One useful reference: The distilled proof path is here." in system_prompt
    assert "Teaching knowledge fragment:" not in system_prompt


def test_blocked_followup_turn_uses_review_recovery_mode(tmp_path: Path) -> None:
    async def fake_create_chat_completion(
        self,
        *,
        client,
        model,
        messages,
        temperature,
        max_tokens,
        stream=False,
    ):
        mock_choice = MagicMock()
        mock_choice.message.content = "Take the next tiny recovery step before widening."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response, model

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=fake_create_chat_completion,
    ):
        with build_client(tmp_path) as client:
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": "workspace-recovery-mode",
                    "workspace_name": "trainer-recovery-mode",
                    "profile": {
                        "long_term_goal": "Recover smoothly when implementation turns get blocked",
                        "weekly_hours": 4,
                        "teaching_style": "guided",
                        "answer_policy": "guided",
                    },
                },
            )
            assert start_response.status_code == 200
            session_id = start_response.json()["session_id"]

            first_response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "message": "Help me implement one thin slice of the startup recovery path.",
                    "provider": {
                        "name": "test-provider",
                        "base_url": "https://api.openai.com/v1",
                        "api_key_ref": "trainer.test",
                        "model": "gpt-4o-mini",
                    },
                    "api_key": "sk-test",
                },
            )
            assert first_response.status_code == 200

            followup_response = client.post(
                "/session/message",
                json={
                    "session_id": session_id,
                    "message": "I am stuck and overwhelmed, the startup branch still fails before boot completes. Help me recover with the next tiny move.",
                    "provider": {
                        "name": "test-provider",
                        "base_url": "https://api.openai.com/v1",
                        "api_key_ref": "trainer.test",
                        "model": "gpt-4o-mini",
                    },
                    "api_key": "sk-test",
                },
            )

    assert followup_response.status_code == 200
    payload = followup_response.json()
    assert payload["snapshot"]["memory"]["due_reviews"]
    assert payload["snapshot"]["affect_state"]["recovery_signal"] == "overloaded"
    assert payload["snapshot"]["teaching_decision"]["mode"] == "review_reflection"
    assert payload["snapshot"]["tone_decision"]["tone"] == "concise_rescue"
    assert payload["reply"]["metadata"]["coach_focus"]["review_rhythm"]


def test_session_message_uses_saved_workspace_language_and_answer_mode_defaults(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-defaults-flow",
                "workspace_name": "trainer-defaults-flow",
                "profile": {
                    "long_term_goal": "Keep saved coach defaults active on future turns",
                    "weekly_hours": 5,
                    "teaching_style": "guided",
                    "answer_policy": "balanced",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        settings_response = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "response_language": "zh-CN",
                "answer_mode": "auto",
                "coach_defaults": {
                    "memory_scope": "project",
                    "working_set_mode": "focused",
                    "review_cadence": "active",
                    "review_reminder_mode": "ahead",
                    "workspace_memory_toggles": {
                        "decisions": True,
                        "patterns": True,
                        "resources": False,
                    },
                },
            },
        )
        assert settings_response.status_code == 200

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Continue guiding me along the current lane, but this time I am not resending language or answer-mode settings.",
            },
        )
        assert message_response.status_code == 200
        payload = message_response.json()
        reply_metadata = payload["reply"]["metadata"]
        assert reply_metadata["response_language"] == "zh-CN"
        assert reply_metadata["coach_focus"]["coach_defaults"]["working_set_mode"] == "focused"
        assert payload["coach_turn"]["teaching_mode"] == "coach"
        assert payload["snapshot"]["coaching_state"]["answer_mode"] == "guided"

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        workspace = summary_response.json()["memory"]["workspace"]
        assert workspace["response_language"] == "zh-CN"
        assert workspace["answer_mode"] == "auto"
        assert workspace["coach_defaults"]["working_set_mode"] == "focused"


def test_session_message_saved_auto_answers_remote_boundary_questions_directly(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-auto-remote-balance",
                "workspace_name": "trainer-auto-remote-balance",
                "profile": {
                    "long_term_goal": "Keep remote coaching adaptive by default",
                    "weekly_hours": 5,
                    "teaching_style": "auto",
                    "answer_policy": "auto",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        settings_response = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "answer_mode": "auto",
            },
        )
        assert settings_response.status_code == 200

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": (
                    "In VS Code Remote SSH, where should the API key live, and how do I verify the workspace boundary "
                    "before I change anything?"
                ),
            },
        )
        assert message_response.status_code == 200
        payload = message_response.json()
        assert payload["coach_turn"]["scenario"] == "remote_workspace"
        assert payload["snapshot"]["coaching_state"]["answer_mode"] == "direct"

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        assert summary_response.json()["memory"]["workspace"]["answer_mode"] == "auto"


def test_session_message_saved_auto_goes_direct_when_learner_is_blocked(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-auto-direct-rescue",
                "workspace_name": "trainer-auto-direct-rescue",
                "profile": {
                    "long_term_goal": "Escalate auto feedback when the learner is clearly blocked",
                    "weekly_hours": 5,
                    "teaching_style": "auto",
                    "answer_policy": "auto",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        settings_response = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "answer_mode": "auto",
            },
        )
        assert settings_response.status_code == 200

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "I'm stuck on this crash. Just show me the fix I should make next.",
            },
        )
        assert message_response.status_code == 200
        payload = message_response.json()
        assert payload["snapshot"]["coaching_state"]["answer_mode"] == "direct"

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        assert summary_response.json()["memory"]["workspace"]["answer_mode"] == "auto"


def test_turn_uses_saved_workspace_defaults_when_request_omits_them(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-turn-defaults",
                "workspace_name": "trainer-turn-defaults",
                "profile": {
                    "long_term_goal": "Carry saved coach defaults into future turn requests",
                    "weekly_hours": 5,
                    "teaching_style": "guided",
                    "answer_policy": "balanced",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        settings_response = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
                "coach_defaults": {
                    "memory_scope": "personal",
                    "working_set_mode": "broad",
                    "review_cadence": "active",
                    "review_reminder_mode": "digest",
                    "workspace_memory_toggles": {
                        "decisions": True,
                        "patterns": False,
                        "resources": True,
                    },
                },
            },
        )
        assert settings_response.status_code == 200

        turn_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-turn-defaults",
                "intent": "coach",
                "message": "Continue the current training lane, but do not repeat the saved defaults inside the request.",
            },
        )
        assert turn_response.status_code == 200
        payload = turn_response.json()

        assert payload["reply"]["metadata"]["response_language"] == "zh-CN"
        assert payload["reply"]["metadata"]["coach_focus"]["coach_defaults"]["memory_scope"] == "personal"
        assert payload["reply"]["metadata"]["coach_focus"]["coach_defaults"]["working_set_mode"] == "broad"
        assert payload["reply"]["metadata"]["coach_focus"]["coach_defaults"]["review_cadence"] == "active"
        assert payload["reply"]["metadata"]["coach_focus"]["coach_defaults"]["review_reminder_mode"] == "digest"
        assert payload["coach_turn"]["teaching_mode"] == "coach"

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        workspace = summary_response.json()["memory"]["workspace"]
        assert workspace["response_language"] == "zh-CN"
        assert workspace["answer_mode"] == "guided"
        assert workspace["coach_defaults"]["memory_scope"] == "personal"
        assert workspace["coach_defaults"]["working_set_mode"] == "broad"
        assert workspace["coach_defaults"]["review_cadence"] == "active"
        assert workspace["coach_defaults"]["review_reminder_mode"] == "digest"
        assert workspace["workspace_memory_toggles"]["patterns"] is False


def test_saved_defaults_do_not_implicitly_mutate_formal_plan(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-continuity",
                "workspace_name": "trainer-plan-continuity",
                "profile": {
                    "long_term_goal": "Keep one narrow training lane stable across follow-up turns",
                    "weekly_hours": 5,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        settings_response = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
                "coach_defaults": {
                    "memory_scope": "project",
                    "working_set_mode": "focused",
                    "review_cadence": "active",
                    "review_reminder_mode": "ahead",
                },
            },
        )
        assert settings_response.status_code == 200

        plan_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-plan-continuity",
                "intent": "plan",
                "message": "Refresh the plan around the long-horizon coaching lane and give me one very small next step.",
            },
        )
        assert plan_response.status_code == 200
        plan_payload = plan_response.json()
        first_plan = plan_payload["snapshot"]["plan"]
        assert first_plan is None
        assert plan_payload["reply"]["metadata"]["response_language"] == "zh-CN"
        assert plan_payload["coach_turn"]["scenario"] == "plan"
        assert plan_payload["snapshot"]["review_queue_summary"]

        followup_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Continue the previous main thread. Do not change direction yet; just tell me the smallest verifiable next move.",
            },
        )
        assert followup_response.status_code == 200
        followup_payload = followup_response.json()
        assert followup_payload["reply"]["metadata"]["response_language"] == "zh-CN"
        assert followup_payload["snapshot"]["plan"] is None


def test_idea_turn_keeps_chinese_and_review_rhythm_on_followup_session_message(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-idea-followup",
                "workspace_name": "trainer-idea-followup",
                "profile": {
                    "long_term_goal": "Turn ideas into small verified implementation loops",
                    "weekly_hours": 5,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        settings_response = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
                "coach_defaults": {
                    "memory_scope": "project",
                    "working_set_mode": "focused",
                    "review_cadence": "active",
                    "review_reminder_mode": "ahead",
                },
            },
        )
        assert settings_response.status_code == 200

        first_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-idea-followup",
                "intent": "coach",
                "message": "I want to turn Trainer into a long-term unified learning coach. Please help me break down the first implementation slice.",
            },
        )
        assert first_response.status_code == 200
        first_payload = first_response.json()
        assert first_payload["coach_turn"]["scenario"] == "idea_implementation"
        assert first_payload["reply"]["metadata"]["response_language"] == "zh-CN"

        followup_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Continue along the first slice you just outlined, keep it in Chinese, and do not skip verification.",
            },
        )
        assert followup_response.status_code == 200
        followup_payload = followup_response.json()
        assert followup_payload["reply"]["metadata"]["response_language"] == "zh-CN"
        assert followup_payload["coach_turn"]["scenario"] in {"idea_implementation", "general"}
        assert followup_payload["snapshot"]["memory"]["active_thread"]["focus_area"]
        assert followup_payload["snapshot"]["memory"]["active_thread"]["next_step"]
        assert followup_payload["reply"]["metadata"]["artifacts"]
        assert followup_payload["reply"]["metadata"]["coach_focus"]["current_focus"]


def test_saved_defaults_keep_chinese_active_thread_and_plan_continuity_across_followup_turns(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-followup-continuity",
                "workspace_name": "trainer-followup-continuity",
                "profile": {
                    "long_term_goal": "Keep one Chinese coaching lane stable across follow-up turns",
                    "weekly_hours": 5,
                    "teaching_style": "guided",
                    "answer_policy": "balanced",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        settings_response = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
                "coach_defaults": {
                    "memory_scope": "project",
                    "working_set_mode": "focused",
                    "review_cadence": "active",
                    "review_reminder_mode": "ahead",
                    "workspace_memory_toggles": {
                        "decisions": True,
                        "patterns": True,
                        "resources": True,
                    },
                },
            },
        )
        assert settings_response.status_code == 200

        first_turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-followup-continuity",
                "intent": "coach",
                "message": "????????????????????????",
            },
        )
        assert first_turn.status_code == 200
        first_payload = first_turn.json()
        first_focus = first_payload["snapshot"]["memory"]["active_thread"]["focus_area"]
        assert first_payload["reply"]["metadata"]["response_language"] == "zh-CN"
        assert first_payload["coach_turn"]["teaching_mode"] == "coach"
        assert first_focus

        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": ["Keep the current coaching lane visible across follow-up turns"],
                "constraints": ["Prefer one thin implementation slice", "Do not widen scope before verification"],
            },
        )
        assert plan_response.status_code == 200
        plan_payload = plan_response.json()
        current_stage_title = plan_payload["plan_runtime_status"]["current_stage"]["title"]
        assert current_stage_title

        followup_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Continue the lane you just established. Do not switch to English or open a brand-new training branch this time.",
            },
        )
        assert followup_response.status_code == 200
        followup_payload = followup_response.json()
        followup_metadata = followup_payload["reply"]["metadata"]
        followup_thread = followup_payload["snapshot"]["memory"]["active_thread"]
        assert followup_metadata["response_language"] == "zh-CN"
        assert followup_payload["coach_turn"]["teaching_mode"] == "coach"
        assert followup_thread["focus_area"] == first_focus
        assert followup_metadata["coach_focus"]["coach_defaults"]["working_set_mode"] == "focused"
        assert followup_payload["snapshot"]["plan_runtime_status"]["current_stage"]["title"] == current_stage_title
        assert followup_payload["snapshot"]["plan_runtime_status"]["current_main_thread"]["focus_area"] == first_focus

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        summary_payload = summary_response.json()
        workspace = summary_payload["memory"]["workspace"]
        assert workspace["response_language"] == "zh-CN"
        assert workspace["coach_defaults"]["review_cadence"] == "active"
        assert summary_payload["memory"]["active_thread"]["focus_area"] == first_focus
        assert summary_payload["plan_runtime_status"]["current_stage"]["title"] == current_stage_title


def test_resource_upload_index_and_memory_summary_roundtrip(tmp_path: Path) -> None:
    resource_file = tmp_path / "coach-memory-notes.md"
    resource_file.write_text(
        "# Coach lane\nKeep the current slice small.\nVerify before widening scope.\n",
        encoding="utf-8",
    )

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-resource-roundtrip",
                "workspace_name": "trainer-resource-roundtrip",
                "profile": {
                    "long_term_goal": "Keep uploaded resources visible in memory summary",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        upload_response = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Coach Memory Notes",
                "source": str(resource_file),
                "tags": ["coach", "memory"],
            },
        )
        assert upload_response.status_code == 200
        resource_payload = upload_response.json()
        assert resource_payload["summary"] == "Registered and waiting for parsing."
        assert resource_payload["parse_status"] == "pending"
        assert resource_payload["index_status"] == "pending"
        assert resource_payload["knowledge_fragments"] == []
        assert resource_payload["fetched_at"] is None

        index_response = client.post(
            "/resource/index",
            json={
                "session_id": session_id,
                "resource_id": resource_payload["id"],
            },
        )
        assert index_response.status_code == 200
        indexed_payload = index_response.json()
        assert indexed_payload["parse_status"] == "parsed"
        assert indexed_payload["index_status"] == "indexed"
        assert "Keep the current slice small." in indexed_payload["summary"]

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        summary_payload = summary_response.json()
        resources = summary_payload["memory"]["resources"]
        assert [item["id"] for item in resources] == [resource_payload["id"]]
        assert resources[0]["name"] == "Coach Memory Notes"
        assert resources[0]["source"] == str(resource_file)
        assert resources[0]["parse_status"] == "parsed"
        assert resources[0]["index_status"] == "indexed"
        assert "Verify before widening scope." in resources[0]["summary"]


def test_workspace_understanding_persists_and_guides_followup_adaptation_turns(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-understanding-adaptation",
                "workspace_name": "trainer-understanding-adaptation",
                "profile": {
                    "long_term_goal": "Learn how to adapt real projects from stable entry points",
                    "weekly_hours": 5,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        first_turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-understanding-adaptation",
                "intent": "coach",
                "message": "Help me adapt this existing project, but first tell me where the first boundary should be drawn.",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
                "current_file": {
                    "path": "server/app/api/routers.py",
                    "language_id": "python",
                    "content": "def route():\n    pass\n",
                    "diagnostics": ["The router mixes orchestration and rendering details."],
                    "recent_files": [
                        "server/app/pedagogy/service.py",
                        "server/app/memory/service.py",
                    ],
                    "recent_edited_files": [
                        "server/app/api/routers.py",
                        "server/app/pedagogy/service.py",
                        "server/tests/test_api.py",
                    ],
                    "related_files": [
                        {"path": "server/app/pedagogy/service.py", "reason": "coach decisions"},
                        {"path": "server/tests/test_api.py", "reason": "verification"},
                    ],
                },
            },
        )
        assert first_turn.status_code == 200
        first_payload = first_turn.json()
        understanding = first_payload["snapshot"]["memory"]["workspace_understanding"]
        assert understanding["repo_summary"]
        assert understanding["entry_points"][0] == "server/app/api/routers.py"
        assert "server/app/pedagogy/service.py" in understanding["entry_points"]
        assert understanding["training_opportunities"]

        followup_turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-understanding-adaptation",
                "intent": "coach",
                "message": "Keep adapting this project along the current lane and preserve the first boundary instead of widening scope.",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )
        assert followup_turn.status_code == 200
        followup_payload = followup_turn.json()
        followup_understanding = followup_payload["snapshot"]["memory"]["workspace_understanding"]
        assert followup_understanding["entry_points"][0] == "server/app/api/routers.py"
        guide = followup_payload["snapshot"]["project_adaptation_guide"]
        assert guide["first_migration_step"]
        assert "server/app/api/routers.py" in guide["first_migration_step"]
        adaptation_artifact = next(
            artifact
            for artifact in followup_payload["reply"]["metadata"]["artifacts"]
            if artifact["kind"] == "project_adaptation"
        )
        assert "server/app/api/routers.py" in adaptation_artifact["content"]


def test_project_idea_turn_uses_indexed_resource_context_for_workspace_understanding(tmp_path: Path) -> None:
    resource_file = tmp_path / "pedagogy-service-notes.md"
    resource_file.write_text(
        "# Pedagogy service\nThe service decides teaching modes and shapes project ideas.\n",
        encoding="utf-8",
    )

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-understanding-resource",
                "workspace_name": "trainer-understanding-resource",
                "profile": {
                    "long_term_goal": "Extract project ideas from attached workspace notes",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        upload_response = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Pedagogy Service Notes",
                "source": str(resource_file),
                "tags": ["pedagogy", "workspace"],
            },
        )
        assert upload_response.status_code == 200
        resource_id = upload_response.json()["id"]

        index_response = client.post(
            "/resource/index",
            json={
                "session_id": session_id,
                "resource_id": resource_id,
            },
        )
        assert index_response.status_code == 200

        turn_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-understanding-resource",
                "intent": "coach",
                "message": "What project idea should I extract from these attached notes next?",
                "response_language": "en-US",
                "answer_mode": "coach-first",
                "resource_ids": [resource_id],
            },
        )
        assert turn_response.status_code == 200
        payload = turn_response.json()
        understanding = payload["snapshot"]["memory"]["workspace_understanding"]
        assert "Pedagogy Service Notes" in understanding["repo_summary"]
        assert "Pedagogy Service Notes" in understanding["entry_points"]
        assert understanding["training_opportunities"]
        assert payload["snapshot"]["project_ideas"][0]["source_area"] == "Pedagogy Service Notes"


def test_project_idea_turn_uses_folder_resource_file_anchors_for_workspace_understanding(tmp_path: Path) -> None:
    source_directory = tmp_path / "trainer-workspace"
    source_directory.mkdir()
    api_file = source_directory / "api.py"
    api_file.write_text("def coach_reply():\n    return 'ok'\n", encoding="utf-8")
    note_file = source_directory / "notes.md"
    note_file.write_text("# Notes\nKeep the first patch thin and explainable.\n", encoding="utf-8")
    test_file = source_directory / "test_api.py"
    test_file.write_text("def test_reply():\n    assert True\n", encoding="utf-8")

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-folder-understanding",
                "workspace_name": "trainer-folder-understanding",
                "profile": {
                    "long_term_goal": "Use attached folders as real project context",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        upload_response = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Attached Workspace",
                "source": str(source_directory),
                "source_type": "folder",
                "source_items": [str(api_file), str(note_file), str(test_file)],
                "tags": ["workspace", "folder"],
            },
        )
        assert upload_response.status_code == 200
        resource_id = upload_response.json()["id"]

        index_response = client.post(
            "/resource/index",
            json={
                "session_id": session_id,
                "resource_id": resource_id,
            },
        )
        assert index_response.status_code == 200

        turn_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-folder-understanding",
                "intent": "coach",
                "message": "What should I extract from this attached project folder first?",
                "response_language": "en-US",
                "answer_mode": "coach-first",
                "resource_ids": [resource_id],
            },
        )
        assert turn_response.status_code == 200
        payload = turn_response.json()
        understanding = payload["snapshot"]["memory"]["workspace_understanding"]
        entry_points = understanding["entry_points"]
        assert any("api.py" in item for item in entry_points)
        assert any("notes.md" in item for item in entry_points)
        assert any("test_api.py" in item for item in understanding["training_opportunities"])
        assert "api.py" in understanding["repo_summary"] or "notes.md" in understanding["repo_summary"]


def test_project_idea_artifact_surfaces_multiple_candidate_drills(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-project-ideas-rich",
                "intent": "coach",
                "message": "What project idea should I extract from this codebase next?",
                "response_language": "en-US",
                "answer_mode": "coach-first",
                "current_file": {
                    "path": "server/app/pedagogy/service.py",
                    "language_id": "python",
                    "content": "def analyze_turn():\n    pass\n",
                    "diagnostics": ["The current implementation path loses a clear anchor."],
                    "recent_files": ["server/app/api/routers.py"],
                    "recent_edited_files": [
                        "server/app/pedagogy/service.py",
                        "server/app/api/routers.py",
                        "server/tests/test_api.py",
                    ],
                    "related_files": [
                        {"path": "server/app/api/routers.py", "reason": "reply assembly"},
                        {"path": "server/app/core/models.py", "reason": "contracts"},
                    ],
                },
            },
        )
        assert response.status_code == 200
        payload = response.json()
        artifact = next(
            item
            for item in payload["reply"]["metadata"]["artifacts"]
            if item["kind"] == "project_idea"
        )
        assert "Candidate drills" in artifact["content"]
        assert "[small]" in artifact["content"] or "[medium]" in artifact["content"]
        assert payload["snapshot"]["project_ideas"][0]["difficulty"] in {"small", "medium", "stretch"}
        assert payload["snapshot"]["project_ideas"][0]["why_now"]
        assert payload["snapshot"]["project_ideas"][0]["first_step"]


def test_resource_upload_rejects_missing_file_and_directory_sources(tmp_path: Path) -> None:
    missing_file = tmp_path / "does-not-exist.md"
    source_directory = tmp_path / "resource-folder"
    source_directory.mkdir()

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-resource-errors",
                "workspace_name": "trainer-resource-errors",
                "profile": {
                    "long_term_goal": "Fail fast on invalid resource uploads",
                    "weekly_hours": 3,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        missing_response = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Missing Notes",
                "source": str(missing_file),
                "tags": ["missing"],
            },
        )
        assert missing_response.status_code == 400
        assert "does not exist" in missing_response.json()["detail"]

        directory_response = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Directory Notes",
                "source": str(source_directory),
                "tags": ["directory"],
            },
        )
        assert directory_response.status_code == 400
        assert "must point to a file, not a directory" in directory_response.json()["detail"]


def test_resource_upload_accepts_folder_source_metadata(tmp_path: Path) -> None:
    source_directory = tmp_path / "resource-folder"
    source_directory.mkdir()
    file_one = source_directory / "one.md"
    file_one.write_text("# One\nKeep it narrow.\n", encoding="utf-8")
    file_two = source_directory / "two.py"
    file_two.write_text("def patch():\n    return True\n", encoding="utf-8")

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-folder-resource",
                "workspace_name": "trainer-folder-resource",
                "profile": {
                    "long_term_goal": "Import folder-backed resources safely",
                    "weekly_hours": 3,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        upload_response = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-folder-resource",
                "kind": "markdown",
                "name": "Folder Notes",
                "source": str(source_directory),
                "source_type": "folder",
                "source_items": [str(file_one), str(file_two), str(file_one)],
                "tags": ["folder"],
            },
        )
        assert upload_response.status_code == 200
        payload = upload_response.json()
        assert payload["source_type"] == "local:markdown"
        assert payload["source_items"] == [str(file_one), str(file_two)]


def test_learning_outcome_saves_general_teaching_asset_and_reuses_it(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-general-asset",
                "workspace_name": "trainer-general-asset",
                "profile": {
                    "long_term_goal": "Promote reusable teaching knowledge",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        runtime = client.app.state.runtime
        runtime.memory_service.record_learning_outcome(
            workspace_id="workspace-general-asset",
            concepts=["coaching rhythm"],
            outcome="tests_passed",
            summary="The learner kept the patch narrow and the verification passed.",
            checks=["pytest server/tests/test_api.py -q"],
            focus_area="coaching rhythm",
            scenario="review",
            verified_result="The narrow patch verified cleanly.",
            verified_by_evaluator=True,
        )

        first_summary = client.get("/memory/summary", params={"session_id": session_id})
        assert first_summary.status_code == 200
        first_assets = first_summary.json()["memory"]["teaching_assets"]
        assert any(asset["kind"] == "implementation_pattern" for asset in first_assets)
        assert all(asset["scope"] != "general" for asset in first_assets)
        assert all("reusable pattern" not in asset["title"].lower() for asset in first_assets)

        runtime.memory_service.record_learning_outcome(
            workspace_id="workspace-general-asset-transfer",
            concepts=["coaching rhythm"],
            outcome="tests_passed",
            summary="The same rhythm transferred into a second workspace.",
            checks=["pytest server/tests/test_api.py -q"],
            focus_area="coaching rhythm",
            scenario="review",
            verified_result="The transferred patch verified cleanly.",
            verified_by_evaluator=True,
        )

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        teaching_assets = summary_response.json()["memory"]["teaching_assets"]
        assert any(asset["kind"] == "implementation_pattern" for asset in teaching_assets)
        assert any(asset["scope"] == "general" for asset in teaching_assets)
        assert any("reusable pattern" in asset["title"].lower() for asset in teaching_assets)


def test_learning_signal_endpoint_records_concept_success_and_task_abandonment(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-learning-signal",
                "workspace_name": "trainer-learning-signal",
                "profile": {
                    "long_term_goal": "Let explicit learning signals shape coaching",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        concept_response = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-learning-signal",
                "concepts": ["state machine boundary"],
                "outcome": "concept_answered_correctly",
                "summary": "The learner explained why the state machine should reject invalid transitions first.",
                "action_type": "reflection",
                "focus_area": "state machine boundary",
                "scenario": "concept_teaching",
            },
        )
        assert concept_response.status_code == 200
        concept_payload = concept_response.json()
        assert concept_payload["memory"]["coaching_adaptation"]["explanation_mode"] == "transfer"
        assert concept_payload["memory"]["learning_outcomes"][0]["outcome"] == "concept_answered_correctly"

        abandon_response = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-learning-signal",
                "concepts": ["state machine boundary"],
                "outcome": "task_abandoned",
                "summary": "The learner abandoned the refactor after widening scope too far.",
                "action_type": "task",
                "focus_area": "state machine boundary",
                "scenario": "idea_implementation",
                "abandoned_reason": "The refactor touched too many branches at once.",
            },
        )
        assert abandon_response.status_code == 200
        abandon_payload = abandon_response.json()
        latest = abandon_payload["memory"]["learning_outcomes"][0]
        adaptation = abandon_payload["memory"]["coaching_adaptation"]
        workspace = abandon_payload["memory"]["workspace"]
        assert latest["outcome"] == "task_abandoned"
        assert adaptation["next_step_bias"] == "shrink"
        assert adaptation["challenge_level"] == "lower"
        assert workspace["latest_learning_abandon_reason"] == "The refactor touched too many branches at once."


def test_learning_signal_endpoint_accepts_blocked_outcome_as_recoverable_failure(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-learning-signal-blocked",
                "workspace_name": "trainer-learning-signal-blocked",
                "profile": {
                    "long_term_goal": "Keep blocked learning work recoverable",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-learning-signal-blocked",
                "concepts": ["workspace boundary"],
                "outcome": "blocked",
                "summary": "The next step is blocked until the workspace root is trusted.",
                "blocked_reason": "Workspace trust has not been established.",
                "action_type": "task",
                "focus_area": "workspace boundary",
                "scenario": "idea_implementation",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    latest = payload["memory"]["learning_outcomes"][0]
    adaptation = payload["memory"]["coaching_adaptation"]
    workspace = payload["memory"]["workspace"]
    pending_evidence = payload["memory"]["evidence_queue"]["pending"]
    assert latest["outcome"] == "blocked"
    assert adaptation["challenge_level"] == "lower"
    assert adaptation["next_step_bias"] == "shrink"
    assert workspace["latest_learning_outcome"] == "blocked"
    assert workspace["latest_learning_blocker"] == "Workspace trust has not been established."
    assert pending_evidence[0]["outcome"] == "fail"
    assert pending_evidence[0]["verified"] is False


def test_learning_signal_endpoint_replans_active_plan_after_abandonment(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-learning-plan-replan",
                "workspace_name": "trainer-learning-plan-replan",
                "profile": {
                    "long_term_goal": "Let learning outcomes reshape the active plan",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        runtime = client.app.state.runtime
        state = runtime.ensure_session(session_id, workspace_id="workspace-learning-plan-replan")
        state.snapshot.plan = LearningPlan(
            id="plan-learning-replan",
            title="Coach-first trainer",
            summary="Keep moving forward.",
            stages=[
                PlanStage(
                    id="stage-practice",
                    title="Practice",
                    goal="Deepen planner and memory",
                    outcomes=["Strengthen the coach loop"],
                    status="active",
                )
            ],
            current_stage_id="stage-practice",
            current_step="Rebuild the whole planner loop at once.",
            next_after_current="Then review the broad patch.",
        )

        response = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-learning-plan-replan",
                "concepts": ["planner loop"],
                "outcome": "task_abandoned",
                "summary": "The learner abandoned the patch after widening too much.",
                "action_type": "task",
                "focus_area": "planner loop",
                "scenario": "idea_implementation",
                "blocked_reason": "Too many branches changed at once.",
                "abandoned_reason": "The patch became too broad to reason about.",
                "repetition_count": 2,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        plan = payload["plan"]
        assert plan["blocked_reason"] == "Too many branches changed at once."
        assert "Shrink the slice" in plan["current_step"]
        assert "planner loop" in plan["current_step"]
        assert "return to" in plan["next_after_current"].lower()


def test_learning_signal_records_teaching_strategy_effectiveness_from_snapshot(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-learning-signal-strategy",
                "workspace_name": "trainer-learning-signal-strategy",
                "profile": {
                    "long_term_goal": "Let Trainer learn which teaching strategy works best",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        runtime = client.app.state.runtime
        state = runtime.ensure_session(session_id, workspace_id="workspace-learning-signal-strategy")
        state.snapshot.memory.coaching_adaptation = CoachingAdaptationProfile(
            challenge_level="steady",
            hint_depth="guided",
            review_urgency="low",
            explanation_mode="transfer",
            next_step_bias="widen",
            summary="Prefer transfer with a slightly wider next step after verified progress.",
            evidence=["The learner responds well to verified transfer loops."],
        )

        response = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-learning-signal-strategy",
                "concepts": ["review scheduler"],
                "outcome": "tests_passed",
                "summary": "The review scheduler slice passed with a transfer-oriented explanation.",
                "action_type": "evaluate_current_file",
                "focus_area": "review scheduler",
                "scenario": "idea_implementation",
                "verified_result": "The review scheduler slice passed with a transfer-oriented explanation.",
            },
        )
        assert response.status_code == 200

        structured = runtime.memory_service.structured_for_workspace("workspace-learning-signal-strategy").snapshot()
        assert structured.teaching_strategy_effectiveness
        latest = structured.teaching_strategy_effectiveness[0]
        assert latest.focus_area == "review scheduler"
        assert latest.scenario == "idea_implementation"
        assert latest.explanation_mode == "transfer"
        assert latest.next_step_bias == "widen"


def test_url_resource_upload_and_memory_summary_visibility(tmp_path: Path) -> None:
    url_source = "https://example.com/trainer/coach-defaults"

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-url-resource",
                "workspace_name": "trainer-url-resource",
                "profile": {
                    "long_term_goal": "Keep URL resources visible in memory summary",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        upload_response = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-url-resource",
                "kind": "url",
                "name": "Coach Defaults URL",
                "source": url_source,
                "tags": ["url", "defaults"],
            },
        )
        assert upload_response.status_code == 200
        resource_payload = upload_response.json()
        assert resource_payload["kind"] == "url"
        assert resource_payload["source"] == url_source

        index_response = client.post(
            "/resource/index",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-url-resource",
                "resource_id": resource_payload["id"],
            },
        )
        assert index_response.status_code == 200
        indexed_payload = index_response.json()
        assert indexed_payload["source_type"].startswith("url:")
        assert indexed_payload["canonical_source"] == url_source
        assert indexed_payload["fetched_at"] is None
        assert indexed_payload["freshness"] == "unknown"
        assert indexed_payload["parse_status"] == "failed"
        assert indexed_payload["index_status"] == "failed"
        assert indexed_payload["trust_score"] > 0
        assert indexed_payload["duplicate_key"]
        assert isinstance(indexed_payload["knowledge_fragments"], list)

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        resources = summary_response.json()["memory"]["resources"]
        assert [item["id"] for item in resources] == [resource_payload["id"]]
        assert resources[0]["kind"] == "url"
        assert resources[0]["source"] == url_source
        assert resources[0]["duplicate_key"]
        assert resources[0]["knowledge_fragments"] == []
        assert "network_disabled" in resources[0]["quality_flags"]


@patch("app.ingest.service.fetch_url")
def test_url_resource_index_real_fetch_roundtrip_includes_summary_source_and_retrieved_at(
    mock_fetch_url,
    tmp_path: Path,
) -> None:
    mock_fetch_url.return_value = ControlledFetchResponse(
        body=b"<html><body><article><h1>Trainer</h1><p>External coaching note.</p></article></body></html>",
        final_url="https://example.com/trainer",
        status=200,
        headers={"content-type": "text/html"},
        fetched_at="2026-07-12T00:00:00+00:00",
    )
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-url-fetch",
                "workspace_name": "trainer-url-fetch",
                "profile": {
                    "long_term_goal": "Use external references honestly",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]
        upload_response = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "url",
                "name": "Fetched URL",
                "source": "https://example.com/trainer",
            },
        )
        resource_id = upload_response.json()["id"]
        index_response = client.post(
            "/resource/index",
            json={"session_id": session_id, "resource_id": resource_id, "enable_network": True},
        )
        assert index_response.status_code == 200
        payload = index_response.json()
        assert "External coaching note." in payload["summary"]
        assert payload["fetched_at"]
        assert payload["canonical_source"] == "https://example.com/trainer"
        assert payload["trust_score"] > 0.4
        assert payload["knowledge_fragments"][0]["source"] == "https://example.com/trainer"
        assert payload["knowledge_fragments"][0]["source_type"].startswith("url:")
        assert payload["knowledge_fragments"][0]["focus_area"] == "Fetched URL"
        assert payload["knowledge_fragments"][0]["quality_flags"] == []
        assert payload["knowledge_fragments"][0]["duplicate_key"] == payload["duplicate_key"]


def test_duplicate_resource_upload_does_not_duplicate_curated_context(tmp_path: Path) -> None:
    note_file = tmp_path / "coach-note.md"
    note_file.write_text("# Note\nUse one narrow patch.\n", encoding="utf-8")
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-dedupe",
                "workspace_name": "trainer-dedupe",
                "profile": {
                    "long_term_goal": "Deduplicate external resources",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]
        first = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Coach Note A",
                "source": str(note_file),
            },
        ).json()
        second = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Coach Note B",
                "source": str(note_file),
            },
        ).json()
        first_index = client.post("/resource/index", json={"session_id": session_id, "resource_id": first["id"]}).json()
        second_index = client.post("/resource/index", json={"session_id": session_id, "resource_id": second["id"]}).json()
        assert first_index["duplicate_key"] == second_index["duplicate_key"]
        assert "duplicate" in second_index["quality_flags"]
        assert second_index["knowledge_fragments"] == []

        turn_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-dedupe",
                "intent": "coach",
                "message": "Use the attached notes but do not duplicate context.",
                "resource_ids": [first["id"], second["id"]],
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert turn_response.status_code == 200
        external_references = turn_response.json()["reply"]["metadata"]["external_references"]
        assert len(external_references) == 1


def test_same_source_with_changed_content_is_marked_as_conflict_and_not_curated(tmp_path: Path) -> None:
    note_file = tmp_path / "evolving-note.md"
    note_file.write_text("# Note\nKeep one narrow patch.\n", encoding="utf-8")
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-conflict",
                "workspace_name": "trainer-conflict",
                "profile": {
                    "long_term_goal": "Handle conflicting source revisions honestly",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        first = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Evolving Note v1",
                "source": str(note_file),
            },
        ).json()
        first_index = client.post("/resource/index", json={"session_id": session_id, "resource_id": first["id"]}).json()
        assert first_index["knowledge_fragments"]

        note_file.write_text("# Note\nRewrite the whole lane before testing.\n", encoding="utf-8")
        second = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Evolving Note v2",
                "source": str(note_file),
            },
        ).json()
        second_index = client.post("/resource/index", json={"session_id": session_id, "resource_id": second["id"]}).json()
        assert second_index["duplicate_key"] != first_index["duplicate_key"]
        assert "source_conflict" in second_index["quality_flags"]
        assert second_index["trust_score"] < first_index["trust_score"]
        assert second_index["knowledge_fragments"] == []

        turn_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-conflict",
                "intent": "coach",
                "message": "Use the latest attached note only if it is trustworthy.",
                "resource_ids": [first["id"], second["id"]],
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert turn_response.status_code == 200
        external_references = turn_response.json()["reply"]["metadata"]["external_references"]
        assert len(external_references) == 1
        assert "Keep one narrow patch." in external_references[0]["snippet"]


@patch("app.ingest.service.fetch_url")
def test_resource_index_populates_teaching_assets_and_memory_snapshot(
    mock_fetch_url,
    tmp_path: Path,
) -> None:
    mock_fetch_url.return_value = ControlledFetchResponse(
        body=b"<html><body><article><h1>Trainer</h1><p>Reusable coaching note.</p></article></body></html>",
        final_url="https://example.com/trainer-asset",
        status=200,
        headers={"content-type": "text/html"},
        fetched_at="2026-07-12T00:00:00+00:00",
    )
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-asset-flow",
                "workspace_name": "trainer-asset-flow",
                "profile": {
                    "long_term_goal": "Build a learning loop that remembers teaching assets",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]
        upload_response = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-asset-flow",
                "kind": "url",
                "name": "Trainer note",
                "source": "https://example.com/trainer-asset",
            },
        )
        resource_id = upload_response.json()["id"]
        index_response = client.post(
            "/resource/index",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-asset-flow",
                "resource_id": resource_id,
                "enable_network": True,
            },
        )
        assert index_response.status_code == 200

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        memory_payload = summary_response.json()["memory"]
        teaching_assets = memory_payload["teaching_assets"]
        assert teaching_assets
        assert teaching_assets[0]["summary"]


def test_turn_resource_context_exposes_h1_ready_fragments(tmp_path: Path) -> None:
    note_file = tmp_path / "grounding-note.md"
    note_file.write_text("# Note\nCoach from real snippets.\n", encoding="utf-8")
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-fragments",
                "workspace_name": "trainer-fragments",
                "profile": {
                    "long_term_goal": "Use grounded fragments in coaching",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]
        upload = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Grounding Note",
                "source": str(note_file),
            },
        ).json()
        client.post("/resource/index", json={"session_id": session_id, "resource_id": upload["id"]})
        turn_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-fragments",
                "intent": "coach",
                "message": "Use the attached note to guide the next patch.",
                "resource_ids": [upload["id"]],
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert turn_response.status_code == 200
        payload = turn_response.json()
        assert payload["reply"]["metadata"]["external_references"]
        assert payload["reply"]["metadata"]["external_references"][0]["snippet"]
        assert payload["reply"]["metadata"]["external_references"][0]["summary"]
        assert payload["reply"]["metadata"]["external_references"][0]["source_type"] == "local:markdown"
        assert payload["reply"]["metadata"]["coach_focus"]


def test_turn_marks_selected_teaching_asset_usage(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-asset-usage",
                "workspace_name": "trainer-asset-usage",
                "profile": {
                    "long_term_goal": "Turn teaching assets into reusable coaching knowledge",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime
        runtime.memory_service.record_teaching_asset(
            "workspace-asset-usage",
            TeachingKnowledgeAsset(
                kind="implementation_pattern",
                scope="project",
                workspace_id="workspace-asset-usage",
                title="Review scheduler pattern",
                summary="Keep the review scheduler inside one verified branch.",
                implementation_pattern="Keep the review scheduler inside one verified branch.",
                focus_area="review scheduler",
                scenario="idea_implementation",
                source_key="pattern::review-scheduler",
                trust_score=0.86,
            ),
        )
        runtime.memory_service.record_teaching_asset(
            "workspace-asset-usage",
            TeachingKnowledgeAsset(
                kind="concept_card",
                scope="project",
                workspace_id="workspace-asset-usage",
                title="Unrelated deployment note",
                summary="General deployment reminder.",
                concept_card="General deployment reminder.",
                focus_area="deployment",
                scenario="planning",
                source_key="concept::deployment",
                trust_score=0.55,
            ),
        )

        turn_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-asset-usage",
                "intent": "coach",
                "message": "Help me implement the next thin slice of the review scheduler.",
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert turn_response.status_code == 200

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        teaching_assets = summary_response.json()["memory"]["teaching_assets"]
        relevant_asset = next(item for item in teaching_assets if item["title"] == "Review scheduler pattern")
        unrelated_asset = next(item for item in teaching_assets if item["title"] == "Unrelated deployment note")
        assert relevant_asset["usage_count"] >= 1
        assert unrelated_asset["usage_count"] == 0


def test_principle_turn_uses_saved_explanation_asset_in_snapshot_and_marks_usage(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-principle-asset-usage",
                "workspace_name": "trainer-principle-asset-usage",
                "profile": {
                    "long_term_goal": "Explain principles from saved teaching assets",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime
        runtime.memory_service.record_teaching_asset(
            "workspace-principle-asset-usage",
            TeachingKnowledgeAsset(
                kind="explanation_recipe",
                scope="project",
                workspace_id="workspace-principle-asset-usage",
                title="Boundary-first explanation",
                summary="Start from the failing branch before widening into architecture.",
                explanation_recipe="Start from the failing branch before widening into architecture.",
                why_it_matters="It keeps the mechanism visible before the explanation turns abstract.",
                example="Walk one failing branch, then name the rule it reveals.",
                focus_area="review-first planning",
                scenario="principle_explanation",
                source_key="explanation::boundary-first",
                trust_score=0.9,
            ),
        )
        runtime.memory_service.record_teaching_asset(
            "workspace-principle-asset-usage",
            TeachingKnowledgeAsset(
                kind="implementation_pattern",
                scope="project",
                workspace_id="workspace-principle-asset-usage",
                title="Unrelated implementation note",
                summary="Ship the smallest patch first.",
                implementation_pattern="Ship the smallest patch first.",
                focus_area="patch discipline",
                scenario="idea_implementation",
                source_key="pattern::unrelated",
                trust_score=0.55,
            ),
        )

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-principle-asset-usage",
                "intent": "coach",
                "message": "Why is this a better approach? Explain the principle behind it.",
                "focus_area": "review-first planning",
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert "Boundary-first explanation" in payload["snapshot"]["principle_notes"]["why_it_matters"]
        assert "Walk one failing branch" in payload["snapshot"]["principle_notes"]["apply_now"]
        assert payload["snapshot"]["selected_teaching_assets"]
        assert payload["snapshot"]["selected_teaching_assets"][0]["title"] == "Boundary-first explanation"
        assert any(
            "Boundary-first explanation" in item
            for item in payload["snapshot"]["exercise_prompt"]["constraints"]
        )

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        teaching_assets = summary_response.json()["memory"]["teaching_assets"]
        relevant_asset = next(item for item in teaching_assets if item["title"] == "Boundary-first explanation")
        unrelated_asset = next(item for item in teaching_assets if item["title"] == "Unrelated implementation note")
        assert relevant_asset["usage_count"] >= 1
        assert unrelated_asset["usage_count"] == 0


def test_project_idea_turn_uses_saved_exercise_seed_as_top_idea_and_marks_usage(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-project-idea-asset-usage",
                "workspace_name": "trainer-project-idea-asset-usage",
                "profile": {
                    "long_term_goal": "Turn saved exercise seeds into project-backed drills",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime
        runtime.memory_service.record_teaching_asset(
            "workspace-project-idea-asset-usage",
            TeachingKnowledgeAsset(
                kind="exercise_seed",
                scope="project",
                workspace_id="workspace-project-idea-asset-usage",
                title="Review scheduler regression loop",
                summary="Turn the saved review scheduler boundary into one regression-first exercise.",
                exercise_seed="Turn the saved review scheduler boundary into one regression-first exercise.",
                focus_area="review scheduler",
                scenario="project_idea_mining",
                source_key="exercise::review-scheduler-regression",
                trust_score=0.92,
            ),
        )
        runtime.memory_service.record_teaching_asset(
            "workspace-project-idea-asset-usage",
            TeachingKnowledgeAsset(
                kind="concept_card",
                scope="project",
                workspace_id="workspace-project-idea-asset-usage",
                title="Unrelated deployment card",
                summary="General deployment reminder.",
                concept_card="General deployment reminder.",
                focus_area="deployment",
                scenario="planning",
                source_key="concept::deployment",
                trust_score=0.5,
            ),
        )

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-project-idea-asset-usage",
                "intent": "coach",
                "message": "What should I build or extract from this codebase next?",
                "focus_area": "review scheduler",
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        top_idea = payload["snapshot"]["project_ideas"][0]
        assert "Review scheduler regression loop" in top_idea["title"]
        assert top_idea["idea_kind"] == "test"
        assert payload["snapshot"]["exercise_prompt"]["prompt"] == top_idea["first_step"]
        assert payload["snapshot"]["selected_teaching_assets"]
        assert payload["snapshot"]["selected_teaching_assets"][0]["title"] == "Review scheduler regression loop"
        project_idea_artifact = next(
            artifact
            for artifact in payload["reply"]["metadata"]["artifacts"]
            if artifact["kind"] == "project_idea"
        )
        assert "Review scheduler regression loop" in project_idea_artifact["summary"]

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        teaching_assets = summary_response.json()["memory"]["teaching_assets"]
        relevant_asset = next(item for item in teaching_assets if item["title"] == "Review scheduler regression loop")
        unrelated_asset = next(item for item in teaching_assets if item["title"] == "Unrelated deployment card")
        assert relevant_asset["usage_count"] >= 1
        assert unrelated_asset["usage_count"] == 0


def test_background_references_flow_into_turn_without_explicit_resource_ids(tmp_path: Path) -> None:
    note_file = tmp_path / "background-note.md"
    note_file.write_text(
        "# Grounding\nTrainer should keep the next patch thin and verifiable.\n",
        encoding="utf-8",
    )
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-background-flow",
                "workspace_name": "trainer-background-flow",
                "profile": {
                    "long_term_goal": "Build a learning loop that uses external grounding",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]
        upload = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Grounding Note",
                "source": str(note_file),
            },
        ).json()
        client.post("/resource/index", json={"session_id": session_id, "resource_id": upload["id"]})

        turn_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-background-flow",
                "intent": "coach",
                "message": "缂佈呯敾缂佹瑦鍨滄稉瀣╃濮濄儻绱濇担鍡氱箹濞嗏€茬瑝鐟曚線鍣告径宥堫洣濮瑰倹鍨滈柌宥嗘煀娑撳﹣绱剁挧鍕灐",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )
        assert turn_response.status_code == 200
        payload = turn_response.json()
        external_references = payload["reply"]["metadata"]["external_references"]
        assert external_references
        assert "thin and verifiable" in external_references[0]["snippet"]
        assert external_references[0]["evidence_summary"]
        assert "thin and verifiable" in external_references[0]["evidence_summary"]
        assert external_references[0]["source"]
        assert external_references[0]["reference_origin"] in {"curated_resource", "background_research"}


def test_coach_turn_external_references_are_persisted_into_background_research_without_duplicates(
    tmp_path: Path,
) -> None:
    note_file = tmp_path / "background-memory-note.md"
    note_file.write_text(
        "# Grounding\nKeep the next implementation slice thin and verifiable.\n",
        encoding="utf-8",
    )
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-background-persist",
                "workspace_name": "trainer-background-persist",
                "profile": {
                    "long_term_goal": "Persist grounded references between coach turns",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        upload = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Background Memory Note",
                "source": str(note_file),
            },
        ).json()
        client.post("/resource/index", json={"session_id": session_id, "resource_id": upload["id"]})

        first_turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-background-persist",
                "intent": "coach",
                "message": "Use the attached note to guide the next implementation slice.",
                "resource_ids": [upload["id"]],
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert first_turn.status_code == 200

        runtime = client.app.state.runtime
        first_references = runtime.research_service.recent_background_references(
            workspace_id="workspace-background-persist",
            min_confidence=0.3,
            limit=10,
        )
        assert first_references
        assert any("thin and verifiable" in item["snippet"] for item in first_references)

        second_turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-background-persist",
                "intent": "coach",
                "message": "Use the same attached note again, but do not duplicate stored grounding.",
                "resource_ids": [upload["id"]],
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert second_turn.status_code == 200

        second_references = runtime.research_service.recent_background_references(
            workspace_id="workspace-background-persist",
            min_confidence=0.3,
            limit=10,
        )
        matching = [item for item in second_references if "thin and verifiable" in item["snippet"]]
        assert len(matching) == 1


def test_turn_external_references_merge_requested_and_background_without_duplicates(tmp_path: Path) -> None:
    note_file = tmp_path / "merged-grounding-note.md"
    note_file.write_text(
        "# Grounding\nKeep the next implementation slice thin and verifiable.\n",
        encoding="utf-8",
    )
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-merged-background",
                "workspace_name": "trainer-merged-background",
                "profile": {
                    "long_term_goal": "Blend attached grounding with background research",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        upload = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Merged Grounding Note",
                "source": str(note_file),
            },
        ).json()
        client.post("/resource/index", json={"session_id": session_id, "resource_id": upload["id"]})
        runtime = client.app.state.runtime
        runtime.research_service.record_background_reference(
            workspace_id="workspace-merged-background",
            focus_area="implementation grounding",
            source="https://example.com/coach-research",
            content="Map one verified boundary before widening scope.",
            trust_score=0.93,
            tags=["background", "grounding"],
        )

        turn_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-merged-background",
                "intent": "coach",
                "message": "Use the attached note and keep any background research grounded, but do not repeat the same reference twice.",
                "resource_ids": [upload["id"]],
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert turn_response.status_code == 200
        external_references = turn_response.json()["reply"]["metadata"]["external_references"]
        assert len(external_references) == 2
        assert "thin and verifiable" in external_references[0]["snippet"]
        assert external_references[0]["reference_origin"] == "requested_resource"
        assert external_references[1]["source"] == "https://example.com/coach-research"
        assert len({(item["source"], item["snippet"]) for item in external_references}) == len(external_references)


def test_merge_external_references_honors_duplicate_keys_across_variants(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        merged = runtime.resource_service.merge_external_references(
            requested_fragments=[
                {
                    "source": "https://example.com/reference",
                    "snippet": "Keep one verified boundary before widening scope.",
                    "duplicate_key": "boundary-key-1",
                    "evidence_summary": "Verified boundary before widening scope.",
                    "trust_score": 0.9,
                }
            ],
            curated_fragments=[],
            research_findings=[
                {
                    "source": "https://example.com/reference",
                    "snippet": "Keep the verified boundary before widening the scope!",
                    "duplicate_key": "boundary-key-1",
                    "evidence_summary": "Verified boundary before widening scope.",
                    "trust_score": 0.86,
                }
            ],
            focus_area="boundary discipline",
            limit=4,
        )

        assert len(merged) == 1
        assert merged[0]["duplicate_key"] == "boundary-key-1"
        assert merged[0]["evidence_summary"] == "Verified boundary before widening scope."


def test_resource_index_persists_evidence_summary_in_fragments(tmp_path: Path) -> None:
    note_file = tmp_path / "resource-evidence-note.md"
    note_file.write_text(
        "# Evidence Note\nOne narrow boundary is enough.\nThis line explains the concrete proof path.\n",
        encoding="utf-8",
    )
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-resource-evidence",
                "workspace_name": "trainer-resource-evidence",
                "profile": {
                    "long_term_goal": "Persist evidence-first fragments",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        upload = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "markdown",
                "name": "Evidence Note",
                "source": str(note_file),
            },
        ).json()
        index = client.post(
            "/resource/index",
            json={"session_id": session_id, "resource_id": upload["id"]},
        )
        assert index.status_code == 200

        runtime = client.app.state.runtime
        resources = runtime.repository.list_resources("workspace-resource-evidence")
        assert len(resources) == 1
        fragment = resources[0].knowledge_fragments[0]
        assert fragment["evidence_summary"]
        assert "proof path" in fragment["evidence_summary"].lower()


def test_project_sourcing_does_not_auto_promote_ungoverned_background_reference(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-background-project-source",
                "workspace_name": "trainer-background-project-source",
                "profile": {
                    "long_term_goal": "Find grounded outside sources for coaching work",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime
        runtime.research_service.record_background_reference(
            workspace_id="workspace-background-project-source",
            focus_area="long-term coaching flow",
            source="https://example.com/background-project-source",
            content="Map one verified boundary before widening scope.",
            trust_score=0.92,
            tags=["background", "grounding"],
        )

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Help me find public project sources that are good for training long-horizon coaching ability.",
                "response_language": "zh-CN",
            },
        )
        assert message_response.status_code == 200
        payload = message_response.json()
        assert payload["coach_turn"]["scenario"] == "project_sourcing"
        assert all(
            item["source_url"] != "https://example.com/background-project-source"
            for item in payload["snapshot"]["project_sources"]
        )
        background_reference = next(
            item
            for item in payload["reply"]["metadata"]["external_references"]
            if item["source"] == "https://example.com/background-project-source"
        )
        assert background_reference["commercial_reuse_status"] == "review_required"
        assert "commercial_reuse_not_auto_promoted" in background_reference["quality_flags"]
        assert "source_governance_missing" in background_reference["quality_flags"]


def test_memory_summary_exposes_teaching_knowledge_catalog(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-knowledge-catalog",
                "workspace_name": "trainer-knowledge-catalog",
                "profile": {
                    "long_term_goal": "Build a reusable teaching knowledge base",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime
        runtime.memory_service.record_teaching_asset(
            "workspace-knowledge-catalog",
            TeachingKnowledgeAsset(
                kind="implementation_pattern",
                scope="project",
                workspace_id="workspace-knowledge-catalog",
                title="Review scheduler pattern",
                summary="Keep the review scheduler inside one verified branch.",
                implementation_pattern="Keep the review scheduler inside one verified branch.",
                origin="learning_outcome",
                focus_area="review scheduler",
                scenario="idea_implementation",
                source_key="pattern::review-scheduler",
                trust_score=0.86,
            ),
        )

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        memory_payload = summary_response.json()["memory"]
        catalog = memory_payload["teaching_knowledge_catalog"]
        assert catalog["total"] >= 1
        assert "project" in catalog["by_scope"]
        assert "implementation_pattern" in catalog["by_kind"]
        assert "learning_outcome" in catalog["by_origin"]
        assert catalog["top_assets"][0]["source_summary"]
        assert "retrieval_hints" in catalog["top_assets"][0]


def test_memory_teaching_assets_endpoint_returns_filtered_library(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-teaching-library",
                "workspace_name": "trainer-teaching-library",
                "profile": {
                    "long_term_goal": "Browse teaching assets like a real knowledge base",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]
        runtime = client.app.state.runtime
        runtime.memory_service.record_teaching_asset(
            "workspace-teaching-library",
            TeachingKnowledgeAsset(
                kind="implementation_pattern",
                scope="project",
                workspace_id="workspace-teaching-library",
                title="Review scheduler pattern",
                summary="Keep the review scheduler inside one verified branch.",
                implementation_pattern="Keep the review scheduler inside one verified branch.",
                source_summary="Verified review scheduler branch pattern.",
                evidence_snippets=["Keep the review scheduler inside one verified branch."],
                retrieval_hints=["review scheduler", "verified branch"],
                origin="learning_outcome",
                focus_area="review scheduler",
                scenario="idea_implementation",
                source_key="pattern::review-scheduler",
                trust_score=0.86,
            ),
        )
        runtime.memory_service.record_teaching_asset(
            "workspace-teaching-library",
            TeachingKnowledgeAsset(
                kind="concept_card",
                scope="general",
                workspace_id="__global__",
                title="General verification concept",
                summary="Keep verification visible.",
                concept_card="Keep verification visible.",
                source_summary="Reusable verification concept.",
                evidence_snippets=["Keep verification visible."],
                retrieval_hints=["verification", "general"],
                origin="learning_outcome",
                focus_area="verification",
                scenario="review_reflection",
                source_key="general::verification",
                trust_score=0.74,
            ),
        )

        response = client.get(
            "/memory/teaching-assets",
            params={
                "session_id": session_id,
                "scenario": "idea_implementation",
                "focus_area": "review scheduler",
                "limit": 6,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] >= 1
        assert payload["items"]
        assert payload["items"][0]["title"] == "Review scheduler pattern"
        assert payload["items"][0]["source_summary"]
        assert payload["items"][0]["evidence_snippets"]
        assert payload["items"][0]["retrieval_hints"]


def test_personal_teaching_assets_stay_local_across_workspaces(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        first_session = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-personal-a",
                "workspace_name": "trainer-personal-a",
                "profile": {
                    "long_term_goal": "Reuse personal teaching assets across projects",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        first_session_id = first_session.json()["session_id"]
        runtime = client.app.state.runtime
        runtime.memory_service.record_teaching_asset(
            "workspace-personal-a",
            TeachingKnowledgeAsset(
                kind="explanation_recipe",
                scope="personal",
                workspace_id="workspace-personal-a",
                title="Boundary-first explanation",
                summary="Explain one boundary before widening scope.",
                explanation_recipe="Explain one boundary before widening scope.",
                source_summary="A personal explanation habit that worked before.",
                evidence_snippets=["Explain one boundary before widening scope."],
                retrieval_hints=["boundary", "personal", "explanation"],
                origin="learning_outcome",
                focus_area="boundary",
                scenario="concept_teaching",
                source_key="personal::boundary",
                trust_score=0.81,
            ),
        )
        client.post(
            "/memory/settings",
            json={
                "session_id": first_session_id,
                "workspace_id": "workspace-personal-a",
                "coach_defaults": {
                    "memory_scope": "personal",
                    "working_set_mode": "balanced",
                    "review_cadence": "steady",
                    "review_reminder_mode": "due",
                    "workspace_memory_toggles": {
                        "decisions": True,
                        "patterns": True,
                        "resources": True,
                    },
                },
            },
        )

        second_session = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-personal-b",
                "workspace_name": "trainer-personal-b",
                "profile": {
                    "long_term_goal": "Continue the same teaching habits in another project",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        second_session_id = second_session.json()["session_id"]
        client.post(
            "/memory/settings",
            json={
                "session_id": second_session_id,
                "workspace_id": "workspace-personal-b",
                "coach_defaults": {
                    "memory_scope": "personal",
                    "working_set_mode": "balanced",
                    "review_cadence": "steady",
                    "review_reminder_mode": "due",
                    "workspace_memory_toggles": {
                        "decisions": True,
                        "patterns": True,
                        "resources": True,
                    },
                },
            },
        )

        summary_response = client.get("/memory/summary", params={"session_id": second_session_id})
        assert summary_response.status_code == 200
        teaching_assets = summary_response.json()["memory"]["teaching_assets"]
        assert not any(item["title"] == "Boundary-first explanation" for item in teaching_assets)


def test_memory_share_grant_routes_return_refreshed_snapshot(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-share-target",
                "workspace_name": "trainer-share-target",
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        created = client.post(
            "/memory/share-grants",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-share-target",
                "source_workspace_id": "workspace-share-source",
                "categories": ["preferences", "mastery"],
            },
        )
        assert created.status_code == 200
        created_snapshot = created.json()
        created_grants = created_snapshot["memory"]["memory_share_grants"]
        assert len(created_grants) == 1
        assert created_grants[0]["source_workspace_id"] == "workspace-share-source"
        assert created_grants[0]["target_workspace_id"] == "workspace-share-target"
        assert created_grants[0]["categories"] == ["preferences", "mastery"]

        listed = client.get(
            "/memory/share-grants",
            params={"session_id": session_id, "workspace_id": "workspace-share-target"},
        )
        assert listed.status_code == 200
        assert listed.json()[0]["categories"] == ["preferences", "mastery"]

        rejected_category = client.post(
            "/memory/share-grants",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-share-target",
                "source_workspace_id": "workspace-share-source",
                "categories": ["teaching_assets"],
            },
        )
        assert rejected_category.status_code == 422

        revoked = client.post(
            "/memory/share-grants/revoke",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-share-target",
                "source_workspace_id": "workspace-share-source",
            },
        )
        assert revoked.status_code == 200
        assert revoked.json()["memory"]["memory_share_grants"] == []


def test_default_settings_model_respects_network_fetch_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRAINER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRAINER_ENABLE_NETWORK_FETCH", "true")
    app = create_app()
    runtime = app.state.runtime
    assert runtime.resource_service.enable_network_fetch is True


def test_url_resource_index_surfaces_network_disabled_degradation(tmp_path: Path) -> None:
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
    with TestClient(create_app(settings)) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-network-off",
                "workspace_name": "trainer-network-off",
                "profile": {
                    "long_term_goal": "Degrade honestly when the network is disabled",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]
        upload = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "url",
                "name": "Disabled URL",
                "source": "https://example.com/no-fetch",
            },
        ).json()
        index_response = client.post(
            "/resource/index",
            json={"session_id": session_id, "resource_id": upload["id"], "enable_network": True},
        )
        assert index_response.status_code == 200
        payload = index_response.json()
        assert "network_disabled" in payload["quality_flags"]
        assert payload["trust_score"] < 0.5
        assert payload["warnings"]
        assert payload["knowledge_fragments"] == []


def test_blocked_url_resource_is_marked_failed_and_not_curated(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-blocked-url",
                "workspace_name": "trainer-blocked-url",
                "profile": {
                    "long_term_goal": "Block unsafe URLs honestly",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        session_id = start_response.json()["session_id"]
        upload = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "kind": "url",
                "name": "Unsafe URL",
                "source": "http://localhost/private",
            },
        ).json()
        index_response = client.post(
            "/resource/index",
            json={"session_id": session_id, "resource_id": upload["id"], "enable_network": True},
        )
        assert index_response.status_code == 200
        payload = index_response.json()
        assert payload["parse_status"] == "failed"
        assert payload["index_status"] == "failed"
        assert "blocked_source" in payload["quality_flags"]
        assert payload["trust_score"] <= 0.2
        assert payload["knowledge_fragments"] == []


def test_resource_and_memory_routes_follow_active_session_workspace(tmp_path: Path) -> None:
    workspace_one_file = tmp_path / "workspace-one-notes.md"
    workspace_one_file.write_text("# FastAPI\nUse tests to lock behavior.\n", encoding="utf-8")

    workspace_one_summary = None
    with build_client(tmp_path) as client:
        first_start = client.post(
            "/session/start",
            json={
                "user_profile": {
                    "long_term_goals": ["Learn FastAPI deeply"],
                    "weekly_hours": 5,
                    "allow_direct_answers": False,
                    "focus_libraries": ["fastapi", "pytest"],
                },
                "workspace_context": {
                    "workspace_id": "workspace-1",
                    "name": "trainer-one",
                },
            },
        )
        assert first_start.status_code == 200
        first_session_id = first_start.json()["session_id"]

        upload_response = client.post(
            "/resource/upload",
            json={
                "kind": "markdown",
                "name": "Workspace One Notes",
                "source": str(workspace_one_file),
                "tags": ["fastapi"],
            },
        )
        assert upload_response.status_code == 200
        resource_one = upload_response.json()

        index_response = client.post("/resource/index", json={"resource_id": resource_one["id"]})
        assert index_response.status_code == 200
        indexed_resource = index_response.json()
        assert indexed_resource["index_status"] == "indexed"
        assert indexed_resource["parse_status"] == "parsed"

        summary_response = client.get("/memory/summary")
        assert summary_response.status_code == 200
        workspace_one_summary = summary_response.json()
        assert workspace_one_summary["profile"]["long_term_goal"] == "Learn FastAPI deeply"
        assert workspace_one_summary["memory"]["profile"]["long_term_goal"] == "Learn FastAPI deeply"
        assert [item["id"] for item in workspace_one_summary["memory"]["resources"]] == [resource_one["id"]]
        assert "teaching_observations" in workspace_one_summary["memory"]
        assert isinstance(workspace_one_summary["memory"]["teaching_observations"], list)
        assert "due_reviews" in workspace_one_summary["memory"]
        assert isinstance(workspace_one_summary["memory"]["due_reviews"], list)
        assert "review_queue_summary" in workspace_one_summary
        assert "coaching_state" in workspace_one_summary
        assert workspace_one_summary["memory"]["current_focus"]
        assert workspace_one_summary["memory"]["current_focus"].startswith("Current coaching focus:")
        assert workspace_one_summary["memory"]["review_rhythm"]
        assert workspace_one_summary["memory"]["review_rhythm"].startswith("Review rhythm:")

        second_start = client.post(
            "/session/start",
            json={
                "user_profile": {
                    "long_term_goals": ["Learn React composition"],
                    "weekly_hours": 3,
                    "allow_direct_answers": True,
                    "focus_libraries": ["react"],
                },
                "workspace_context": {
                    "workspace_id": "workspace-2",
                    "name": "trainer-two",
                },
            },
        )
        assert second_start.status_code == 200
        second_session_id = second_start.json()["session_id"]

        latest_summary_response = client.get("/memory/summary")
        assert latest_summary_response.status_code == 200
        latest_summary = latest_summary_response.json()
        assert latest_summary["profile"]["long_term_goal"] == "Learn React composition"
        assert latest_summary["memory"]["resources"] == []

        profile_response = client.get("/memory/profile", params={"session_id": first_session_id})
        assert profile_response.status_code == 200
        assert profile_response.json()["long_term_goal"] == "Learn FastAPI deeply"

        weaknesses_response = client.get("/memory/weaknesses", params={"workspace_id": "workspace-1"})
        assert weaknesses_response.status_code == 200
        assert isinstance(weaknesses_response.json(), list)

        reviews_response = client.get("/memory/reviews", params={"session_id": second_session_id})
        assert reviews_response.status_code == 200
        assert reviews_response.json()

        workspace_two_file = tmp_path / "workspace-two-notes.md"
        workspace_two_file.write_text("React server components notes", encoding="utf-8")
        override_upload_response = client.post(
            "/resource/upload",
            json={
                "workspace_id": "workspace-1",
                "kind": "markdown",
                "name": "Workspace One Override Notes",
                "source": str(workspace_two_file),
                "tags": ["override"],
            },
        )
        assert override_upload_response.status_code == 200
        override_resource = override_upload_response.json()

        override_index_response = client.post(
            "/resource/index",
            json={
                "workspace_id": "workspace-1",
                "resource_id": override_resource["id"],
            },
        )
        assert override_index_response.status_code == 200

        workspace_one_by_id_response = client.get("/memory/summary", params={"workspace_id": "workspace-1"})
        assert workspace_one_by_id_response.status_code == 200
        workspace_one_by_id = workspace_one_by_id_response.json()
        assert workspace_one_by_id["profile"]["long_term_goal"] == "Learn FastAPI deeply"
        assert [item["id"] for item in workspace_one_by_id["memory"]["resources"]] == [
            override_resource["id"],
            resource_one["id"],
        ]

    assert workspace_one_summary is not None


def test_turn_response_exposes_coach_state_snapshot(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "profile": {
                    "long_term_goal": "Learn to reshape existing projects carefully",
                    "long_term_goals": ["Learn to reshape existing projects carefully"],
                    "weekly_hours": 5,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                    "preferred_libraries": ["fastapi", "react"],
                },
                "workspace_id": "workspace-coach-state",
                "workspace_name": "trainer",
            },
        )
        assert start_response.status_code == 200
        snapshot = start_response.json()
        assert snapshot["coaching_state"]["summary"]
        assert "review_queue_summary" in snapshot

        with patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(
                return_value=(
                    "\u5148\u628a\u7b2c\u4e00\u5c42\u6539\u9020\u8fb9\u754c\u56fa\u5b9a\u4e0b\u6765\uff1a"
                    "\u4fdd\u6301\u7a33\u5b9a\u6a21\u5757\u4e0d\u52a8\uff0c\u53ea\u9a8c\u8bc1\u4e00\u4e2a\u6700\u5c0f\u6539\u52a8\u3002"
                )
            ),
        ):
            turn_response = client.post(
                "/turn",
                json={
                    "workspace_id": "workspace-coach-state",
                    "intent": "coach",
                    "message": (
                        "\u6211\u60f3\u628a\u8fd9\u4e2a\u73b0\u6709\u9879\u76ee\u6539\u9020\u6210\u957f\u671f\u5b66\u4e60\u6559\u7ec3\uff0c"
                        "\u4f46\u6211\u5361\u4f4f\u4e86\uff1a\u4e0d\u77e5\u9053\u7b2c\u4e00\u5c42\u8fb9\u754c\u8be5\u600e\u4e48\u5212\u3002"
                        "\u8bf7\u76f4\u63a5\u544a\u8bc9\u6211\u600e\u4e48\u5212\u3002"
                    ),
                    "response_language": "zh-CN",
                    "answer_mode": "coach-first",
                },
        )
        assert turn_response.status_code == 200
        payload = turn_response.json()
        coaching_state = payload["snapshot"]["coaching_state"]
        coach_turn = payload["coach_turn"]

        assert coaching_state["scenario"] == "project_adaptation"
        assert coaching_state["answer_mode"] == "guided"
        assert coaching_state["learner_signal"] == "blocked"
        assert coaching_state["summary"]
        assert coaching_state["next_step"]
        assert payload["snapshot"]["review_queue_summary"]

        assert coach_turn["scenario"] == coaching_state["scenario"]
        assert coach_turn["learner_signal"] == coaching_state["learner_signal"]
        assert coach_turn["summary"]
        assert coach_turn["next_step"]
        assert coach_turn["background_mode"] == "embedded"
        assert coach_turn["teaching_mode"] == "coach"
        assert coach_turn["emotional_tone"] == "supportive"
        assert "plan" in coach_turn["suggested_action_types"]

        adaptation_artifact = next(
            artifact
            for artifact in payload["reply"]["metadata"]["artifacts"]
            if artifact["kind"] == "project_adaptation"
        )
        assert adaptation_artifact["recommended_action"] == "plan"
        assert adaptation_artifact["content"]
        assert adaptation_artifact["metadata"]["background_mode"] == "embedded"
        assert adaptation_artifact["metadata"]["coach_focus"]["scenario"] == coaching_state["scenario"]
        assert adaptation_artifact["metadata"]["coach_focus"]["current_focus"]
        assert payload["artifacts"]["project_adaptation"]["content"] == adaptation_artifact["content"]


def test_stream_complete_response_includes_rich_artifact_content(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-stream-rich",
                "workspace_name": "trainer",
                "profile": {
                    "long_term_goal": "Learn to explain principles through code",
                    "long_term_goals": ["Learn to explain principles through code"],
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                    "preferred_libraries": ["python"],
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-stream-rich",
                "intent": "coach",
                "message": "\u8bf7\u89e3\u91ca\u8fd9\u4e2a\u5b9e\u73b0\u80cc\u540e\u7684\u539f\u7406\uff0c\u6700\u597d\u8d34\u7740\u4ee3\u7801\u8fb9\u754c\u8bb2\u3002",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )
        assert response.status_code == 200

        body = response.text
        assert "event: complete" in body
        marker = 'data: {"tokens":'
        last_data_line = [line for line in body.splitlines() if line.startswith(marker)][-1]
        payload = last_data_line[len("data: ") :]
        complete_payload = __import__("json").loads(payload)
        principle_artifact = complete_payload["response"]["artifacts"]["principle"]
        assert principle_artifact["content"]
        assert "### \u63a8\u8fdb\u8def\u5f84" in principle_artifact["content"]
        assert principle_artifact["content"].count("###") >= 2
        assert complete_payload["response"]["reply"]["metadata"]["artifacts"]
        principle_reply_artifact = next(
            artifact
            for artifact in complete_payload["response"]["reply"]["metadata"]["artifacts"]
            if artifact["kind"] == "principle"
        )
        assert principle_reply_artifact["content"] == principle_artifact["content"]


def test_stream_coach_reply_uses_postprocessed_suffix_and_complete_response_matches(tmp_path: Path) -> None:
    async def fake_create_chat_completion(
        self,
        *,
        client,
        model,
        messages,
        temperature,
        max_tokens,
        stream=False,
    ):
        assert stream is True
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Start from the mechanism first."

        async def async_iter():
            yield mock_chunk

        return async_iter(), model

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=fake_create_chat_completion,
    ):
        with build_client(tmp_path) as client:
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": "workspace-stream-postprocess",
                    "workspace_name": "trainer-stream-postprocess",
                    "profile": {
                        "long_term_goal": "Explain principles from saved teaching assets",
                        "weekly_hours": 4,
                        "teaching_style": "guided",
                        "answer_policy": "guided",
                    },
                },
            )
            assert start_response.status_code == 200
            session_id = start_response.json()["session_id"]
            runtime = client.app.state.runtime
            runtime.memory_service.record_teaching_asset(
                "workspace-stream-postprocess",
                TeachingKnowledgeAsset(
                    kind="explanation_recipe",
                    scope="project",
                    workspace_id="workspace-stream-postprocess",
                    title="Boundary-first explanation",
                    summary="Start from the failing branch before widening into architecture.",
                    explanation_recipe="Start from the failing branch before widening into architecture.",
                    why_it_matters="It keeps the mechanism visible before the explanation turns abstract.",
                    example="Walk one failing branch, then name the rule it reveals.",
                    focus_area="review-first planning",
                    scenario="principle_explanation",
                    source_key="explanation::boundary-first-stream",
                    trust_score=0.9,
                ),
            )

            response = client.post(
                "/turn/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-stream-postprocess",
                    "intent": "coach",
                    "message": "Why is this a better approach? Explain the principle behind it.",
                    "focus_area": "review-first planning",
                    "response_language": "en-US",
                    "answer_mode": "coach-first",
                },
            )
            assert response.status_code == 200

    body = response.text
    assert "Start from the mechanism first." in body
    assert "Walk one failing branch" in body
    marker = 'data: {"tokens":'
    last_data_line = [line for line in body.splitlines() if line.startswith(marker)][-1]
    payload = last_data_line[len("data: ") :]
    complete_payload = __import__("json").loads(payload)
    final_reply = complete_payload["response"]["reply"]["content"]
    assert final_reply.startswith("Start from the mechanism first.")
    assert "Walk one failing branch" in final_reply
    assert "Boundary-first explanation" in final_reply


def test_turn_stream_runs_final_coach_postprocessing_for_first_turn(tmp_path: Path) -> None:
    async def fake_create_chat_completion(
        self,
        *,
        client,
        model,
        messages,
        temperature,
        max_tokens,
        stream=False,
    ):
        assert stream is True
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = (
            "\u5148\u5b9e\u73b0\u8ba4\u8bc1\u548c\u652f\u4ed8\uff0c\u518d\u8865\u65e5\u5fd7\u3002\n\n"
            "## \u8ba1\u5212\n"
            "- \u76f4\u63a5\u628a\u6240\u6709\u6838\u5fc3\u6a21\u5757\u4e00\u8d77\u505a\u5b8c\u3002"
        )

        async def async_iter():
            yield mock_chunk

        return async_iter(), model

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=fake_create_chat_completion,
    ):
        with build_client(tmp_path) as client:
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": "workspace-stream-first-turn-reframe",
                    "workspace_name": "trainer-stream-first-turn-reframe",
                },
            )
            assert start_response.status_code == 200
            session_id = start_response.json()["session_id"]

            response = client.post(
                "/turn/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-stream-first-turn-reframe",
                    "intent": "coach",
                    "message": "\u6211\u60f3\u628a trainer \u505a\u6210\u957f\u671f\u4ee3\u7801\u6559\u7ec3\uff0c\u5148\u966a\u6211\u770b\u770b\u8be5\u600e\u4e48\u5f00\u59cb\u3002",
                    "response_language": "zh-CN",
                    "answer_mode": "coach-first",
                },
            )
            assert response.status_code == 200

    body = response.text
    marker = 'data: {"tokens":'
    last_data_line = [line for line in body.splitlines() if line.startswith(marker)][-1]
    payload = last_data_line[len("data: ") :]
    complete_payload = __import__("json").loads(payload)
    final_reply = complete_payload["response"]["reply"]["content"]

    assert "\u8ba4\u8bc1\u548c\u652f\u4ed8" not in final_reply
    assert "## \u8ba1\u5212" not in final_reply
    assert "给我" in final_reply
    assert "长期代码教练" in final_reply



def test_next_task_prefers_due_review_when_available(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "profile": {
                    "long_term_goal": "Learn FastAPI carefully",
                    "long_term_goals": ["Learn FastAPI carefully"],
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                    "preferred_libraries": ["fastapi"],
                },
                "workspace_id": "workspace-review-aware",
                "workspace_name": "trainer",
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-review-aware",
                "objectives": ["Learn FastAPI carefully"],
            },
        )
        assert plan_response.status_code == 200, plan_response.text

        structured = client.app.state.runtime.memory_service.structured_for_workspace(
            "workspace-review-aware"
        )
        structured.record_weakness(
            "router-boundary",
            "The empty-input path still needs one visible verification.",
            severity=2,
            review_after_days=0,
            context="router boundary",
        )

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-review-aware",
                "intent": "next_task",
                "message": "缂佹瑦鍨滄稉瀣╃",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["snapshot"]["current_task"]["title"]
        assert payload["coach_turn"]["scenario"] == "next_task"
        assert payload["coach_turn"]["active_task"]
        assert payload["coach_turn"]["teaching_mode"] == "practice"
        assert payload["coach_turn"]["review_rhythm"]
        assert "review" in payload["coach_turn"]["suggested_action_types"]
        assert payload["coach_turn"]["summary"]
        assert "\u590d\u4e60\u8282\u594f" not in payload["coach_turn"]["summary"]
        next_step_artifact = next(
            artifact
            for artifact in payload["reply"]["metadata"]["artifacts"]
            if artifact["kind"] == "next_step"
        )
        assert next_step_artifact["recommended_action"] == "review"
        assert next_step_artifact["metadata"]["background_mode"] == "embedded"
        assert next_step_artifact["metadata"]["coach_focus"]["active_task"]


def test_session_message_exposes_structured_actions_and_artifacts(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "profile": {
                    "long_term_goal": "Turn ideas into small implementation loops",
                    "long_term_goals": ["Turn ideas into small implementation loops"],
                    "weekly_hours": 5,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                    "preferred_libraries": ["fastapi", "react"],
                },
                "workspace_id": "workspace-session-structured",
                "workspace_name": "trainer",
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Help me reshape this existing project into something closer to a long-horizon unified learning coach, but keep the scope narrow first.",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["coach_turn"]["scenario"] == "project_adaptation"
        assert payload["suggested_actions"]
        assert isinstance(payload["suggested_actions"][0]["label"], str)
        assert payload["suggested_actions"][0]["action"] == "plan"
        assert payload["reply"]["metadata"]["artifacts"]
        adaptation_artifact = next(
            artifact
            for artifact in payload["reply"]["metadata"]["artifacts"]
            if artifact["kind"] == "project_adaptation"
        )
        assert adaptation_artifact["recommended_action"] == "plan"
        assert adaptation_artifact["metadata"]["background_mode"] == "embedded"
        assert adaptation_artifact["metadata"]["coach_focus"]["scenario"] == "project_adaptation"
        assert adaptation_artifact["bullets"][0]
        assert adaptation_artifact["content"]
        assert payload["suggested_actions"][1]["action"] == "task"
        assert payload["suggested_actions"][2]["action"] == "review"


def test_task_next_endpoint_prefers_due_review_task(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "profile": {
                    "long_term_goal": "Practice review-first coding habits",
                    "long_term_goals": ["Practice review-first coding habits"],
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                    "preferred_libraries": ["fastapi"],
                },
                "workspace_id": "workspace-task-next-review",
                "workspace_name": "trainer",
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]
        structured = client.app.state.runtime.memory_service.structured_for_workspace(
            "workspace-task-next-review"
        )
        structured.record_weakness(
            "review-boundary",
            "The last narrow slice still needs one explicit verification pass.",
            severity=2,
            review_after_days=0,
            context="review boundary",
        )

        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-task-next-review",
                "objectives": ["Practice review-first coding habits"],
            },
        )
        assert plan_response.status_code == 200, plan_response.text

        response = client.post(
            "/task/next",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-task-next-review",
                "response_language": "zh-CN",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["title"]
        assert payload["natural_language_goal"]


def test_task_next_localizes_generic_active_thread_focus_in_zh_cn(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-task-next-generic-focus",
                "workspace_name": "trainer-task-next-generic-focus",
                "profile": {
                    "long_term_goal": "Keep generic internal focus labels out of the learner-facing task title",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-task-next-generic-focus",
                "objectives": [
                    "Keep generic internal focus labels out of the learner-facing task title"
                ],
            },
        )
        assert plan_response.status_code == 200, plan_response.text

        client.app.state.runtime.memory_service.record_turn_memory(
            workspace_id="workspace-task-next-generic-focus",
            session_id=session_id,
            scenario="idea_implementation",
            focus_area="implementation",
            summary="Keep the blocked provider lane narrow and honest.",
            next_step="Switch the provider or gateway before reopening the lesson thread.",
            response_language="zh-CN",
            answer_mode="coach-first",
        )

        response = client.post(
            "/task/next",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-task-next-generic-focus",
                "response_language": "zh-CN",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "继续：实现切片"
    assert "implementation" not in payload["title"]


def test_principle_turn_exposes_principle_artifact_and_hint_action(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "profile": {
                    "long_term_goal": "Understand backend boundaries deeply",
                    "long_term_goals": ["Understand backend boundaries deeply"],
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                    "preferred_libraries": ["fastapi"],
                },
                "workspace_id": "workspace-principle",
                "workspace_name": "trainer",
            },
        )
        assert start_response.status_code == 200

        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-principle",
                "intent": "coach",
                "message": "Explain the principle first, show why it matters, and then give me one concrete way to apply it.",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["coach_turn"]["scenario"] == "principle"
        assert "hint" in payload["coach_turn"]["suggested_action_types"]
        assert payload["coach_turn"]["summary"]
        assert "\u5f53\u524d\u805a\u7126" not in payload["coach_turn"]["summary"]
        assert payload["coach_turn"]["next_step"]
        assert "\u590d\u4e60\u8282\u594f" not in payload["coach_turn"]["next_step"]
        principle_artifact = next(
            artifact
            for artifact in payload["reply"]["metadata"]["artifacts"]
            if artifact["kind"] == "principle"
        )
        assert principle_artifact["recommended_action"] == "hint"
        assert principle_artifact["focus_area"] == "principle"
        assert principle_artifact["verification"]
        assert principle_artifact["metadata"]["coach_focus"]["scenario"] == "principle"
        assert principle_artifact["bullets"][0]
        assert principle_artifact["content"].count("###") >= 3


def test_saved_defaults_keep_project_sourcing_in_chinese_across_followup_session_messages(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-project-sourcing-followup",
                "workspace_name": "trainer-project-sourcing-followup",
                "profile": {
                    "long_term_goal": "Keep project sourcing suggestions stable across follow-up turns",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        settings_response = client.post(
            "/memory/settings",
            json={
                "session_id": session_id,
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
                "coach_defaults": {
                    "memory_scope": "project",
                    "working_set_mode": "focused",
                    "review_cadence": "active",
                    "review_reminder_mode": "ahead",
                },
            },
        )
        assert settings_response.status_code == 200

        first_message = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Help me find public project sources that are good for training long-horizon coaching ability.",
            },
        )
        assert first_message.status_code == 200
        first_payload = first_message.json()
        assert first_payload["reply"]["metadata"]["response_language"] == "zh-CN"
        assert first_payload["coach_turn"]["scenario"] == "project_sourcing"
        assert first_payload["snapshot"]["project_sources"]
        first_repo_hint = first_payload["snapshot"]["project_sources"][0]["repo_hint"]
        assert first_repo_hint
        project_source_artifact = next(
            item for item in first_payload["reply"]["metadata"]["artifacts"] if item["kind"] == "project_source"
        )
        assert project_source_artifact["title"] == "\u9879\u76ee\u6765\u6e90\u5efa\u8bae"
        assert "### \u63a8\u8fdb\u8def\u5f84" in project_source_artifact["content"]
        assert "### \u600e\u4e48\u7b5b" in project_source_artifact["content"]
        assert "\u95bb\u6ec4\u6f98\u5a40\ue046\u62e0\u93c7\u72b3\u7d7b" not in project_source_artifact["content"]

        followup_message = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Continue filtering the source suggestions we just discussed, but do not switch languages or jump into implementation details yet.",
            },
        )
        assert followup_message.status_code == 200
        followup_payload = followup_message.json()
        assert followup_payload["reply"]["metadata"]["response_language"] == "zh-CN"
        assert followup_payload["coach_turn"]["scenario"] in {"project_sourcing", "idea_implementation"}
        project_source_artifacts = [
            item for item in followup_payload["reply"]["metadata"]["artifacts"] if item["kind"] == "project_source"
        ]
        if project_source_artifacts:
            assert project_source_artifacts[0]["metadata"]["coach_focus"]["scenario"] == "project_sourcing"
        else:
            assert first_repo_hint


def test_review_turn_surfaces_failing_checks_and_retry_review_action(tmp_path: Path) -> None:
    target_file = tmp_path / "broken_module.py"
    target_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "profile": {
                    "long_term_goal": "Review code with priority",
                    "long_term_goals": ["Review code with priority"],
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                    "preferred_libraries": ["fastapi"],
                },
                "workspace_id": "workspace-review-details",
                "workspace_name": "trainer",
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-review-details",
                "objectives": ["Review code with priority"],
            },
        )
        assert plan_response.status_code == 200, plan_response.text

        task_response = client.post(
            "/task/specify",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-review-details",
                "natural_language_goal": (
                    "Implement an add helper that returns the sum and handles "
                    "invalid input with a documented failure path."
                ),
            },
        )
        assert task_response.status_code == 200, task_response.text

        review_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-review-details",
                "intent": "review",
                "message": "Review this implementation and tell me the first thing to fix.",
                "response_language": "en-US",
                "answer_mode": "guided",
                "current_file": {
                    "path": str(target_file),
                    "language_id": "python",
                    "content": target_file.read_text(encoding="utf-8"),
                    "diagnostics": ["Function behavior is incorrect for normal addition."],
                },
            },
        )

        assert review_response.status_code == 200
        payload = review_response.json()
        assert payload["coach_turn"]["scenario"] == "review"
        assert payload["coach_turn"]["failing_checks"]
        assert "retry_review" in payload["coach_turn"]["suggested_action_types"]
        assert payload["coach_turn"]["summary"]
        assert "Review rhythm:" not in payload["coach_turn"]["summary"]
        review_artifact = next(
            artifact
            for artifact in payload["reply"]["metadata"]["artifacts"]
            if artifact["kind"] == "review"
        )
        assert review_artifact["recommended_action"] in {"review", "retry_review"}
        assert review_artifact["metadata"]["background_mode"] == "embedded"
        assert "failing_checks" in review_artifact["metadata"]
        assert review_artifact["metadata"]["coach_focus"]["review_rhythm"]
        assert not review_artifact["metadata"]["coach_focus"]["review_rhythm"].startswith(
            "Review rhythm:"
        )


def test_non_stream_turns_persist_latest_coach_reflection_into_memory(tmp_path: Path) -> None:
    target_file = tmp_path / "memory_turn_sample.py"
    target_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "profile": {
                    "long_term_goal": "Strengthen coach turn memory loops",
                    "long_term_goals": ["Strengthen coach turn memory loops"],
                    "weekly_hours": 5,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                    "preferred_libraries": ["fastapi"],
                },
                "workspace_id": "workspace-turn-memory",
                "workspace_name": "trainer",
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-turn-memory",
                "objectives": ["Strengthen coach turn memory loops"],
            },
        )
        assert plan_response.status_code == 200, plan_response.text

        task_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-turn-memory",
                "intent": "task",
                "message": "Turn this idea into a tiny training task around coach memory write-back.",
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert task_response.status_code == 200
        task_payload = task_response.json()
        task_memory = task_payload["snapshot"]["memory"]
        assert task_memory["current_focus"]
        assert "Current coaching focus:" not in task_memory["current_focus"]
        assert task_memory["due_reviews"]
        assert task_memory["review_rhythm"]
        assert not task_memory["review_rhythm"].startswith("Review rhythm:")
        assert any("latest coach turn" in item.lower() or "coach" in item.lower() for item in task_memory["recent_wins"])
        assert task_memory["teaching_observations"]
        assert any(
            "last coach turn" in item.lower()
            or "coaching decision" in item.lower()
            or "onboarding anchor" in item.lower()
            or "preference" in item.lower()
            for item in task_memory["teaching_observations"]
        )

        review_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-turn-memory",
                "intent": "review",
                "message": "Review the current implementation and tell me the first fix.",
                "response_language": "en-US",
                "answer_mode": "coach-first",
                "current_file": {
                    "path": str(target_file),
                    "language_id": "python",
                    "content": target_file.read_text(encoding="utf-8"),
                    "diagnostics": ["The function subtracts instead of adding."],
                },
            },
        )
        assert review_response.status_code == 200
        review_payload = review_response.json()
        review_memory = review_payload["snapshot"]["memory"]
        assert review_memory["due_reviews"]
        assert any(
            "verify this next move" in item["reason"].lower()
            or "re-check the latest coaching move" in item["reason"].lower()
            or "implementation move" in item["reason"].lower()
            or "recall prompt" in item["reason"].lower()
            or "thin implementation slice" in item["reason"].lower()
            for item in review_memory["due_reviews"]
        )
        assert any(
            "last coach turn" in item.lower()
            or "verified result" in item.lower()
            or "onboarding anchor" in item.lower()
            for item in review_memory["teaching_observations"]
        )

        plan_turn_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-turn-memory",
                "intent": "plan",
                "message": "Refresh my plan around this memory-sensitive coaching loop.",
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert plan_turn_response.status_code == 200
        plan_payload = plan_turn_response.json()
        plan_memory = plan_payload["snapshot"]["memory"]
        assert plan_memory["current_focus"]
        assert "Current coaching focus:" not in plan_memory["current_focus"]
        assert plan_memory["review_rhythm"]
        assert not plan_memory["review_rhythm"].startswith("Review rhythm:")
        assert plan_memory["due_reviews"]
        assert plan_memory["recent_wins"]
        assert plan_memory["teaching_observations"]


def test_plan_update_returns_coach_turn_and_suggested_actions(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "profile": {
                    "long_term_goal": "Ship a coach-first trainer",
                    "long_term_goals": ["Ship a coach-first trainer"],
                    "weekly_hours": 6,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                    "preferred_libraries": ["fastapi", "react"],
                },
                "workspace_id": "workspace-plan-update",
                "workspace_name": "trainer",
            },
        )
        assert start_response.status_code == 200

        plan_response = client.post(
            "/plan/generate",
            json={
                "workspace_id": "workspace-plan-update",
                "profile": {
                    "long_term_goal": "Ship a coach-first trainer",
                    "long_term_goals": ["Ship a coach-first trainer"],
                    "weekly_hours": 6,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                    "preferred_libraries": ["fastapi", "react"],
                },
                "goals": ["Ship a coach-first trainer"],
                "constraints": ["Keep research embedded in turns"],
            },
        )
        assert plan_response.status_code == 200
        plan_payload = plan_response.json()
        plan_id = plan_payload["plan"]["plan_id"]

        update_response = client.post(
            "/plan/update",
            json={
                "plan_id": plan_id,
                "workspace_id": "workspace-plan-update",
                "instructions": "Tighten the current stage around implementation before expansion.",
                "weekly_cadence": "6 hours per week",
                "frozen": True,
            },
        )

        assert update_response.status_code == 200
        payload = update_response.json()
        assert payload["plan"]["weekly_cadence"] == "6 hours per week"
        assert payload["coach_turn"]["scenario"] == "plan"
        assert payload["coach_turn"]["artifact_kinds"] == ["plan_update"]
        assert any(action["action"] == "next_task" for action in payload["suggested_actions"])
        assert payload["diagnostics"]
        runtime_status = payload["plan_runtime_status"]
        assert runtime_status["current_stage"]["goal"]
        assert "implementation" in runtime_status["current_stage"]["goal"].lower()
        assert "summary" in runtime_status["coach_judgment"]
        assert runtime_status["next_training_action"]
        runtime = client.app.state.runtime
        sandbox_root = runtime.sandbox_service.ensure_workspace_root("workspace-plan-update")
        plan_snapshot = sandbox_root / "plan" / "current-plan.md"
        assert plan_snapshot.exists()
        assert "Ship a coach-first trainer" in plan_snapshot.read_text(encoding="utf-8")


def test_memory_summary_exposes_plan_runtime_status(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-runtime-summary",
                "workspace_name": "trainer-plan-runtime-summary",
                "profile": {
                    "long_term_goal": "Keep plan snapshots tied to live training state",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        message_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Help me continue the current lane and keep the next action visible.",
            },
        )
        assert message_response.status_code == 200

        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": ["Keep the current trainer loop grounded in live coaching state"],
                "constraints": ["Prefer one narrow next move at a time"],
            },
        )
        assert plan_response.status_code == 200

        summary_response = client.get("/memory/summary", params={"session_id": session_id})
        assert summary_response.status_code == 200
        summary_payload = summary_response.json()
        assert summary_payload["plan"]["current_stage_id"]
        active_thread = summary_payload["memory"]["active_thread"]
        assert active_thread["focus_area"]
        memory_evidence = summary_payload["memory"]["memory_evidence"]
        assert memory_evidence
        assert any(
            active_thread["focus_area"] in item or active_thread["next_step"] in item
            for item in memory_evidence
        )
        assert isinstance(summary_payload["memory"]["due_reviews"], list)
        assert summary_payload["coaching_state"]["summary"]
        assert summary_payload["coaching_state"]["next_step"]


def test_turn_continuation_inherits_active_thread_scenario_across_mixed_lanes(tmp_path: Path) -> None:
    captured_context: dict[str, object] = {}

    async def fake_coaching_reply(*args, **kwargs) -> str:
        coach_context = kwargs.get("coach_context")
        if isinstance(coach_context, dict):
            captured_context.update(coach_context)
        return "Stay on the current adaptation lane and lock the first boundary before widening."

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=fake_coaching_reply),
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-mixed-lane-continuation",
                "workspace_name": "trainer-mixed-lane-continuation",
                "profile": {
                    "long_term_goal": "Keep vague follow-ups attached to the right teaching lane",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        runtime = client.app.state.runtime
        for seeded_scenario, focus_area, summary, next_step in (
            (
                "remote_workspace",
                "remote onboarding",
                "Kept the remote entry path narrow.",
                "Verify one host label before opening another remote path.",
            ),
            (
                "debug_loop",
                "launch diagnostics",
                "Pinned the first breakpoint branch.",
                "Re-run one launch target and inspect the first failing frame.",
            ),
            (
                "function_guidance",
                "signature help",
                "Read one function boundary instead of the whole module.",
                "Inspect the first call site and name one parameter contract.",
            ),
            (
                "project_adaptation",
                "adaptation boundary",
                "Kept the adaptation branch focused on one boundary.",
                "Protect the first boundary before widening the migration.",
            ),
        ):
            runtime.memory_service.record_turn_memory(
                workspace_id="workspace-mixed-lane-continuation",
                session_id=session_id,
                scenario=seeded_scenario,
                focus_area=focus_area,
                summary=summary,
                next_step=next_step,
                response_language="en-US",
                answer_mode="guided",
            )

        seeded_snapshot = runtime.memory_service.snapshot("workspace-mixed-lane-continuation")
        assert seeded_snapshot.active_thread is not None
        assert seeded_snapshot.active_thread.scenario == "project_adaptation"

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-mixed-lane-continuation",
                "intent": "coach",
                "message": "Continue.",
                "response_language": "en-US",
                "answer_mode": "auto",
            },
        )

    assert response.status_code == 200, response.text
    assert captured_context["scenario"] == "project_adaptation"
    active_thread = captured_context.get("active_thread")
    assert isinstance(active_thread, dict)
    assert active_thread["scenario"] == "project_adaptation"

    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "project_adaptation"
    assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "project_adaptation"
    assert payload["snapshot"]["coaching_state"]["scenario"] == "project_adaptation"
    assert payload["snapshot"]["memory"]["active_thread"]["scenario"] == "project_adaptation"


def test_session_message_function_guidance_does_not_prepare_starter_without_real_code_context(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-function-guidance-starter"
    provider_reply = AsyncMock(
        return_value="Start from the prepared call site, then read the function contract before you edit anything."
    )

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=provider_reply,
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "trainer-function-guidance-starter",
                "profile": {
                    "long_term_goal": "Teach function guidance from one trustworthy call site before any quiz.",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": "Teach me TypeScript fetch options in VS Code by reading one real call site before you test me.",
                "response_language": "en-US",
                "answer_mode": "auto",
                "current_file": {
                    "path": "index.html",
                    "language_id": "html",
                    "content": "<!doctype html><html><body><script>function renderUser() {}</script></body></html>",
                },
            },
        )
        assert response.status_code == 200, response.text

        runtime = client.app.state.runtime
        sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)

    provider_reply.assert_awaited_once()
    call_site_path = sandbox_root / "knowledge/function-guidance/typescript/src/usage.ts"
    definition_path = sandbox_root / "knowledge/function-guidance/typescript/src/client.ts"
    assert not call_site_path.exists()
    assert not definition_path.exists()
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    routing = payload["snapshot"]["memory"]["active_training_card_routing"]
    assert routing["selected_card"]["status"] == "needs_primer"
    assert routing["selected_card"]["files_to_touch"] == []
    assert "code-file path" in routing["selected_card"]["suggested_workspace_action"]
    assert "<live call site>" not in " ".join(routing["selected_card"]["files_to_touch"])
    assert "call site" in payload["reply"]["content"].lower()


def test_session_message_function_guidance_current_file_anchor_sets_structured_lane(
    tmp_path: Path,
) -> None:
    async def fake_coaching_reply(*_args, **_kwargs) -> str:
        return (
            "我会先把这一轮锚定在当前文件 `src/demo.ts` 里的 `fetchLesson`。"
            "\n\n下一步：回到 `src/demo.ts`，先说清这个函数的参数 contract 和 return contract。"
        )

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=fake_coaching_reply),
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-function-guidance-current-file",
                "workspace_name": "trainer-function-guidance-current-file",
                "profile": {
                    "long_term_goal": "Teach function guidance from a live current file before any quiz.",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-function-guidance-current-file",
                "message": "请教我如何判断一个 TypeScript 函数的 contract。先学习，再让我做一个很小的 try。",
                "response_language": "zh-CN",
                "current_file": {
                    "path": "src/demo.ts",
                    "language_id": "typescript",
                    "content": (
                        "type RetryPolicy = { maxAttempts: number; backoffMs: number };\\n"
                        "export async function fetchLesson(lessonId: string, policy: RetryPolicy): Promise<Response> {\\n"
                        "  return request(`/api/lessons/${lessonId}`, policy);\\n"
                        "}\\n"
                    ),
                    "selection_text": (
                        "export async function fetchLesson(lessonId: string, policy: RetryPolicy): Promise<Response> {\\n"
                        "  return request(`/api/lessons/${lessonId}`, policy);\\n"
                        "}"
                    ),
                    "selection_range": "2:1-4:2",
                    "content_excerpt": (
                        "export async function fetchLesson(lessonId: string, policy: RetryPolicy): Promise<Response> {\\n"
                        "  return request(`/api/lessons/${lessonId}`, policy);\\n"
                        "}"
                    ),
                },
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    assert "demo.ts" in payload["coach_turn"]["next_step"]
    assert "contract" in payload["coach_turn"]["next_step"].lower()


def test_session_message_remote_training_card_uses_session_remote_facts(tmp_path: Path) -> None:
    async def fake_coaching_reply(*_args, **_kwargs) -> str:
        return "Start with the current remote boundary and one verifiable fact."

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=fake_coaching_reply),
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-remote-facts",
                "workspace_name": "trainer-remote-facts",
                "workspace_path": "/workspaces/trainer",
                "remote_name": "ssh-remote+lab",
            },
        )
        assert start_response.status_code == 200, start_response.text
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-remote-facts",
                "message": (
                    "Create a learn-first training card for the VS Code Remote SSH credential boundary. "
                    "Start with one tiny verifiable step before any test."
                ),
                "response_language": "en-US",
                "current_file": {
                    "path": "src/remote.ts",
                    "language_id": "typescript",
                    "content": "export const remoteMode = 'ssh';",
                },
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    workspace = payload["snapshot"]["memory"]["workspace"]
    assert workspace["remote_name"] == "ssh-remote+lab"
    assert workspace["is_remote_workspace"] is True
    # Composer chat preserves remote facts but must not mint or activate a card.
    assert payload["snapshot"]["memory"]["active_training_card_routing"] is None
    assert client.app.state.runtime.memory_service.get_cards("workspace-remote-facts") == []


def test_session_message_non_agent_empty_reply_override_stays_non_agentic(
    tmp_path: Path,
) -> None:
    override = {
        "stop_reason": "empty_response",
        "summary": "provider 没有返回可见内容，所以我先把这一轮留在 function guidance 这条线上。",
        "next_step": "请返回函数名、一个 call site，以及能证明它期望什么的 contract 证据。",
        "blocker": "provider 返回空内容。",
        "teaching_note": "空回复时继续保留当前教学主线，但不要假装 agent loop 已经执行。",
        "resume_thread": (
            "provider 没有返回可见内容，所以我先把这一轮留在 function guidance 这条线上。 "
            "下一步：请返回函数名、一个 call site，以及能证明它期望什么的 contract 证据。"
        ),
    }

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value=""),
        ),
        patch.object(
            ProviderService,
            "consume_last_reply_override",
            autospec=True,
            return_value=override,
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-function-guidance-empty-override",
                "workspace_name": "trainer-function-guidance-empty-override",
                "profile": {
                    "long_term_goal": "Stay truthful when the provider returns empty content.",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-function-guidance-empty-override",
                "message": "请教我如何判断一个 TypeScript 函数的 contract。先学习，再让我做一个很小的 try。",
                "response_language": "zh-CN",
                "useAgentLoop": False,
                "current_file": {
                    "path": "src/demo.ts",
                    "language_id": "typescript",
                    "content": (
                        "type RetryPolicy = { maxAttempts: number; backoffMs: number };\\n"
                        "export async function fetchLesson(lessonId: string, policy: RetryPolicy): Promise<Response> {\\n"
                        "  return request(`/api/lessons/${lessonId}`, policy);\\n"
                        "}\\n"
                    ),
                    "selection_text": (
                        "export async function fetchLesson(lessonId: string, policy: RetryPolicy): Promise<Response> {\\n"
                        "  return request(`/api/lessons/${lessonId}`, policy);\\n"
                        "}"
                    ),
                    "selection_range": "2:1-4:2",
                    "content_excerpt": (
                        "export async function fetchLesson(lessonId: string, policy: RetryPolicy): Promise<Response> {\\n"
                        "  return request(`/api/lessons/${lessonId}`, policy);\\n"
                        "}"
                    ),
                },
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    assert payload["agent_meta"]["stop_reason"] == "empty_response"
    assert payload["agent_meta"]["agentic"] is False


def test_session_start_seeds_learning_project_prompt_in_requested_language(tmp_path: Path) -> None:
    workspace_root = tmp_path / "opened-folder"
    workspace_root.mkdir(parents=True, exist_ok=True)

    with build_client(tmp_path) as client:
        response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-learning-project-prompt",
                "workspace_name": "trainer-learning-project-prompt",
                "workspace_path": str(workspace_root),
                "responseLanguage": "zh-CN",
                "profile": {
                    "long_term_goal": "Keep the learning project binding prompt aligned with the default language",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert "\u5b66\u4e60\u9879\u76ee\u6587\u4ef6\u5939" in payload["messages"][-1]["content"]
    workspace = payload["memory"]["workspace"]
    assert workspace["learning_project_prompt_status"] == "pending"
    assert workspace["learning_project_source_path"] == str(workspace_root)


def test_session_message_use_this_folder_links_learning_project_root_and_writes_note(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "opened-folder"
    workspace_root.mkdir(parents=True, exist_ok=True)

    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-learning-project-link",
                "workspace_name": "trainer-learning-project-link",
                "workspace_path": str(workspace_root),
                "profile": {
                    "long_term_goal": "Turn the current VS Code folder into the governed learning project root",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-learning-project-link",
                "message": "use this folder",
                "response_language": "en-US",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        workspace = payload["snapshot"]["memory"]["workspace"]
        linked_root = Path(workspace["sandbox_root_override"]).resolve(strict=False)
        expected_root = (tmp_path / "projects" / "opened-folder").resolve(strict=False)
        assert linked_root == expected_root
        assert workspace["learning_project_prompt_status"] == "linked"
        assert workspace["learning_project_source_path"] == str(workspace_root)
        assert payload["reply"]["content"].startswith("Linked the current VS Code folder")
        project_link = linked_root / "notes" / "project-link.md"
        assert project_link.exists()
        project_link_text = project_link.read_text(encoding="utf-8")
        assert str(workspace_root) in project_link_text
        assert str(linked_root) in project_link_text


def test_learning_signal_replan_persists_plan_snapshot_into_sandbox(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-learning-plan-replan-persist",
                "workspace_name": "trainer-learning-plan-replan-persist",
                "profile": {
                    "long_term_goal": "Keep learning-signal replans visible inside the managed sandbox",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        runtime = client.app.state.runtime
        state = runtime.ensure_session(
            session_id,
            workspace_id="workspace-learning-plan-replan-persist",
        )
        state.snapshot.plan = LearningPlan(
            id="plan-learning-replan-persist",
            title="Coach-first trainer",
            summary="Keep moving forward.",
            stages=[
                PlanStage(
                    id="stage-practice",
                    title="Practice",
                    goal="Deepen planner and memory",
                    outcomes=["Strengthen the coach loop"],
                    status="active",
                )
            ],
            current_stage_id="stage-practice",
            current_step="Rebuild the whole planner loop at once.",
            next_after_current="Then review the broad patch.",
        )

        response = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-learning-plan-replan-persist",
                "concepts": ["planner loop"],
                "outcome": "task_abandoned",
                "summary": "The learner abandoned the patch after widening too much.",
                "action_type": "task",
                "focus_area": "planner loop",
                "scenario": "idea_implementation",
                "blocked_reason": "Too many branches changed at once.",
                "abandoned_reason": "The patch became too broad to reason about.",
                "repetition_count": 2,
            },
        )
        assert response.status_code == 200

        sandbox_root = runtime.sandbox_service.ensure_workspace_root(
            "workspace-learning-plan-replan-persist"
        )
        plan_snapshot = sandbox_root / "plan" / "current-plan.md"
        assert plan_snapshot.exists()
        plan_text = plan_snapshot.read_text(encoding="utf-8")
        assert "Too many branches changed at once." in plan_text
        assert "planner loop" in plan_text


def test_session_message_resource_grounding_reanchors_from_old_active_thread(tmp_path: Path) -> None:
    captured_context: dict[str, object] = {}

    async def fake_coaching_reply(*args, **kwargs) -> str:
        coach_context = kwargs.get("coach_context")
        if isinstance(coach_context, dict):
            captured_context.update(coach_context)
        return "???? Resources ? first viewport promise?"

    workspace_id = "workspace-resource-fresh-lane"
    message = "Please explain the Resources view first viewport promise and must not become. Do not drift into VS Code remote."

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=fake_coaching_reply),
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "trainer-resource-fresh-lane",
                "profile": {
                    "long_term_goal": "Keep grounded resource answers attached to the requested doc question.",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        runtime = client.app.state.runtime
        runtime.memory_service.record_turn_memory(
            workspace_id=workspace_id,
            session_id=session_id,
            scenario="principle",
            focus_area="implementation",
            summary="code ???????????????? patch?",
            next_step="???? focused code review????????????",
            response_language="zh-CN",
            answer_mode="guided",
        )

        upload_response = client.post(
            "/resource/upload",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "resources-view-contract.md",
                "source": "inline://resources-view-contract.md",
                "content": (
                    "# Resources view contract\n"
                    "First viewport promise: the learner can find, trust, preview, and convert resources without losing provenance.\n"
                    "Must not become: a raw filesystem browser.\n"
                ),
                "content_encoding": "utf-8",
            },
        )
        assert upload_response.status_code == 200, upload_response.text
        resource_id = upload_response.json()["id"]

        index_response = client.post(
            "/resource/index",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "resource_id": resource_id,
            },
        )
        assert index_response.status_code == 200, index_response.text

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": message,
                "response_language": "zh-CN",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    assert captured_context["scenario"] == "principle"
    assert captured_context["history_mode"] == "fresh_lane"
    assert (
        captured_context["first_turn_priority"]
        == "answer the grounded library question directly before widening into adjacent coaching"
    )
    assert captured_context["auto_resource_lookup"] is True
    assert captured_context["active_thread"] is None
    assert isinstance(captured_context["requested_resources"], list)
    assert captured_context["requested_resources"][0]["title"] == "resources-view-contract.md"
    facets = captured_context["resource_question_facets"]
    assert isinstance(facets, list)
    assert "Resources" in facets
    assert "first viewport promise" in facets
    assert "must not become" in facets
    assert "褰撳墠 code" not in str(captured_context["summary"])
    assert "code review" not in str(captured_context["next_step"])
    assert "Resources" in str(captured_context["current_focus"]) or "viewport" in str(
        captured_context["current_focus"]
    )
    memory = captured_context["memory"]
    assert isinstance(memory, dict)
    assert memory["active_thread"] is None


@pytest.mark.parametrize(
    ("active_view", "message", "expected_summary", "expected_next_step"),
    [
        (
            "plan",
            "请先帮我生成一条正式主线，不要静默改计划。",
            "Plan",
            "why now",
        ),
        (
            "resources",
            "请先在资料里定位我现在最该打开的那一份。",
            "Resources",
            "sources、knowledge 还是 cards",
        ),
        (
            "training",
            "请先带我学当前卡片内容，再给我一个最小验证项；先学后测。",
            "Training",
            "Learn -> Try -> Verify -> Reflect -> Return",
        ),
    ],
)
def test_turn_active_view_reanchors_structured_lane_from_old_code_thread(
    tmp_path: Path,
    active_view: str,
    message: str,
    expected_summary: str,
    expected_next_step: str,
) -> None:
    captured_context: dict[str, object] = {}

    async def fake_coaching_reply(*args, **kwargs) -> str:
        coach_context = kwargs.get("coach_context")
        if isinstance(coach_context, dict):
            captured_context.update(coach_context)
        return "好的，我先按当前视图继续。"

    workspace_id = f"workspace-structured-lane-{active_view}"

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=fake_coaching_reply),
        ),
    ):
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": f"trainer-{active_view}-lane",
                "profile": {
                    "long_term_goal": "Keep structured lanes clean and recoverable.",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        runtime = client.app.state.runtime
        runtime.memory_service.record_turn_memory(
            workspace_id=workspace_id,
            session_id=session_id,
            scenario="principle",
            focus_area="implementation mechanism",
            summary="先沿着当前 code 背后的机制继续推进，再扩大 patch 范围。",
            next_step="Ignore secondary issues and only name the first fix plus one verification.",
            response_language="zh-CN",
            answer_mode="guided",
        )

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": message,
                "response_language": "zh-CN",
                "active_view": active_view,
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    assert captured_context["active_view"] == active_view
    assert captured_context["history_mode"] == "fresh_lane"
    assert captured_context["active_thread"] is None
    assert expected_summary in str(captured_context["summary"])
    assert expected_next_step in str(captured_context["next_step"])
    assert "current code" not in str(captured_context["summary"]).lower()
    assert "ignore secondary issues" not in str(captured_context["next_step"]).lower()


def test_idea_implementation_turn_uses_coach_first_structure(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "profile": {
                    "long_term_goal": "Ship coach-first backend loops",
                    "long_term_goals": ["Ship coach-first backend loops"],
                    "weekly_hours": 5,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                    "preferred_libraries": ["fastapi"],
                },
                "workspace_id": "workspace-idea-implementation",
                "workspace_name": "trainer",
            },
        )
        assert start_response.status_code == 200

        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-idea-implementation",
                "intent": "coach",
                "message": "I want to implement a single-turn reply loop that feels more like a long-horizon unified learning coach.",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["coach_turn"]["scenario"] == "idea_implementation"
        assert payload["suggested_actions"][0]["action"] == "plan"
        assert payload["suggested_actions"][1]["action"] == "task"
        assert payload["suggested_actions"][2]["action"] == "review"
        assert payload["coach_turn"]["summary"]
        assert "\u5f53\u524d\u805a\u7126" not in payload["coach_turn"]["summary"]
        assert payload["coach_turn"]["next_step"]
        assert "\u590d\u4e60\u8282\u594f" not in payload["coach_turn"]["next_step"]
        idea_artifact = next(
            artifact
            for artifact in payload["reply"]["metadata"]["artifacts"]
            if artifact["kind"] == "idea_implementation"
        )
        assert idea_artifact["recommended_action"] == "task"
        assert idea_artifact["metadata"]["coach_focus"]["scenario"] == "idea_implementation"
        assert idea_artifact["bullets"][0].startswith("当前聚焦点")
        assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "idea_implementation"


def test_turn_keeps_concrete_chinese_idea_request_out_of_plan_lane(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-idea-no-plan-drift",
                "intent": "coach",
                "message": (
                    "\u6211\u6709\u4e00\u4e2a AI idea\uff0c\u60f3\u628a\u5b83\u843d\u5730\u6210\u4e00\u4e2a\u6700\u5c0f\u53ef\u9a8c\u8bc1\u7684\u539f\u578b\u3002"
                    "\u5148\u522b\u5c55\u5f00\u6210\u603b\u8ba1\u5212\uff0c\u5148\u966a\u6211\u538b\u51fa\u7b2c\u4e00\u6761\u6700\u5c0f\u5207\u7247\u3002"
                ),
                "response_language": "zh-CN",
                "answer_mode": "auto",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "idea_implementation"
    assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "idea_implementation"


def test_turn_keeps_chinese_writing_help_out_of_project_adaptation_lane(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-writing-no-adaptation-drift",
                "intent": "coach",
                "message": (
                    "\u5e2e\u6211\u6da6\u8272\u4e00\u6bb5\u4e2d\u6587\u9879\u76ee\u8fdb\u5c55\u66f4\u65b0\u3002"
                    "\u5148\u53ea\u6539\u8fd9\u4e00\u4e2a\u6bb5\u843d\uff0c\u4e0d\u8981\u628a\u5b83\u53d8\u6210\u5b8c\u6574\u5b66\u4e60\u8ba1\u5212\u3002"
                ),
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "general"
    assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "general"


def test_first_turn_onboarding_message_persists_relationship_memory(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-onboarding-api",
                "workspace_name": "trainer",
            },
        )
        assert start_response.status_code == 200

        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-onboarding-api",
                "intent": "coach",
                "message": (
                    "My long-term goal is to become a stronger backend engineer. "
                    "Right now I am an intermediate Python developer, and I can invest 8 hours per week. "
                    "Please guide me step by step. I am currently stuck on Trainer session restore."
                ),
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        profile = payload["snapshot"]["profile"]
        assert profile["long_term_goal"] == "become a stronger backend engineer"
        assert profile["background"] == "intermediate Python developer"
        assert profile["weekly_hours"] == 8
        assert payload["coach_turn"]["scenario"] == "onboarding"
        assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "onboarding"


def test_turn_exposes_relationship_stage_and_strategy_preference_in_coach_context(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        workspace_id = "workspace-coach-context-signals"
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["review scheduler"],
            outcome="tests_passed",
            summary="The review scheduler slice landed cleanly with transfer-oriented guidance.",
            checks=[],
            missing_requirements=[],
            action_type="evaluate_current_file",
            focus_area="review scheduler",
            scenario="idea_implementation",
            verified_result="The review scheduler slice landed cleanly with transfer-oriented guidance.",
            teaching_strategy_context={
                "challenge_level": "steady",
                "hint_depth": "guided",
                "review_urgency": "low",
                "explanation_mode": "transfer",
                "next_step_bias": "widen",
            },
        )
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["review scheduler"],
            outcome="concept_answered_correctly",
            summary="The learner transferred the review scheduler idea correctly.",
            checks=[],
            missing_requirements=[],
            action_type="reflection",
            focus_area="review scheduler",
            scenario="idea_implementation",
            teaching_strategy_context={
                "challenge_level": "steady",
                "hint_depth": "guided",
                "review_urgency": "low",
                "explanation_mode": "transfer",
                "next_step_bias": "widen",
            },
        )
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["review scheduler"],
            outcome="tests_passed",
            summary="The same strategy worked again for the review scheduler lane.",
            checks=[],
            missing_requirements=[],
            action_type="evaluate_current_file",
            focus_area="review scheduler",
            scenario="idea_implementation",
            verified_result="The same strategy worked again for the review scheduler lane.",
            teaching_strategy_context={
                "challenge_level": "steady",
                "hint_depth": "guided",
                "review_urgency": "low",
                "explanation_mode": "transfer",
                "next_step_bias": "widen",
            },
        )

        response = client.post(
            "/turn",
            json={
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Continue the review scheduler lane and guide me through the next cut.",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        coach_focus = payload["reply"]["metadata"]["coach_focus"]
        assert coach_focus["relationship_stage"] == "active"
        assert coach_focus["strategy_preference_summary"]
        assert "review scheduler" in coach_focus["strategy_preference_summary"].lower()
        assert coach_focus["continuity_summary"]
        assert isinstance(coach_focus["recent_teaching_signals"], list)


def test_turn_low_context_opening_prefers_relationship_first_onboarding_lane(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-low-context-onboarding",
                "intent": "coach",
                "message": "你好，我想开始系统学习编程，但还不知道该从哪里开始。",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "onboarding"
    coach_focus = payload["reply"]["metadata"]["coach_focus"]
    assert coach_focus["relationship_stage"] == "intake"
    assert "choose one coaching lane" in coach_focus["first_turn_priority"]


def test_turn_beginner_goal_without_code_prefers_onboarding_before_implementation(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-beginner-goal-onboarding",
                "intent": "coach",
                "message": "\u6211\u5b8c\u5168\u4e0d\u4f1a\u7f16\u7a0b\uff0c\u60f3\u5728\u4e24\u4e2a\u6708\u5185\u505a\u4e00\u4e2a\u8bb0\u8d26\u7f51\u9875\u3002",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "onboarding"
    assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "onboarding"
    assert payload["reply"]["metadata"]["coach_focus"]["relationship_stage"] == "intake"


def test_turn_current_file_execution_ready_request_stays_in_implementation_lane(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-execution-ready-next-step",
                "intent": "coach",
                "message": (
                    "Based on the current file and my goal, give me one very small next step "
                    "with strong teaching value."
                ),
                "response_language": "en-US",
                "answer_mode": "coach-first",
                "current_file": {
                    "path": "demo.py",
                    "language_id": "python",
                    "content": "def add(a, b):\n    return a + b\n",
                    "diagnostics": [],
                    "recent_files": [],
                    "recent_edited_files": [],
                    "related_files": [],
                },
            },
        )

        runtime_snapshot = client.app.state.runtime.memory_service.snapshot(
            "workspace-execution-ready-next-step"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "idea_implementation"
    assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "idea_implementation"
    assert payload["snapshot"]["review_queue_summary"] == "No immediate review item is due yet."
    assert payload["snapshot"]["memory"]["due_review_count"] == 0
    assert payload["snapshot"]["memory"]["due_reviews"] == []
    assert payload["coach_turn"]["next_step"]
    assert "new-workspace" not in payload["coach_turn"]["next_step"].lower()
    assert "new-workspace" not in payload["reply"]["metadata"]["coach_focus"]["review_rhythm"].lower()
    assert all(
        "new-workspace" not in (artifact.get("content") or "").lower()
        for artifact in payload["reply"]["metadata"]["artifacts"]
    )
    active_thread = runtime_snapshot.active_thread
    assert active_thread is not None
    assert active_thread.focus_area
    assert "new-workspace" not in active_thread.blocker.lower()
    assert "follow-up review" not in active_thread.blocker.lower()


def test_turn_english_coach_context_filters_out_cjk_memory_hints(tmp_path: Path) -> None:
    captured_context: dict[str, object] = {}

    async def fake_coaching_reply(*args, **kwargs) -> str:
        coach_context = kwargs.get("coach_context")
        if isinstance(coach_context, dict):
            captured_context.update(coach_context)
        return "Stay on one very small English step and verify it before widening scope."

    def contains_cjk(value: object) -> bool:
        text = str(value or "")
        return any("\u3400" <= char <= "\u9fff" for char in text)

    with (
        build_client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=fake_coaching_reply),
        ),
    ):
        runtime = client.app.state.runtime
        runtime.memory_service.record_turn_memory(
            workspace_id="workspace-english-language-guard",
            session_id="session-zh-memory-seed",
            scenario="coach",
            focus_area="remote recovery lane",
            summary="Keep the remote recovery path stable before widening scope.",
            next_step="Verify one minimal recovery step first.",
            response_language="zh-CN",
            answer_mode="guided",
        )

        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-english-language-guard",
                "intent": "coach",
                "message": "Keep the next step in English and stay on one small recovery slice.",
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )

    assert response.status_code == 200
    assert captured_context
    payload = response.json()
    coach_focus = payload["reply"]["metadata"]["coach_focus"]
    for key in (
        "summary",
        "current_focus",
        "review_rhythm",
        "continuity_summary",
        "strategy_preference_summary",
        "review_queue_summary",
    ):
        assert not contains_cjk(captured_context.get(key))
    if "summary" in coach_focus:
        assert not contains_cjk(coach_focus["summary"])
    if "current_focus" in coach_focus:
        assert not contains_cjk(coach_focus["current_focus"])

    active_thread = captured_context.get("active_thread") or {}
    assert isinstance(active_thread, dict)
    for key in ("focus_area", "summary", "next_step", "blocker", "decision", "teaching_note"):
        assert not contains_cjk(active_thread.get(key))

    memory = captured_context.get("memory") or {}
    assert isinstance(memory, dict)
    assert not contains_cjk(memory.get("current_focus"))
    assert all(not contains_cjk(item) for item in memory.get("teaching_observations", []))


def test_turn_response_exposes_full_implementation_guide_for_idea_only_input(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-idea-guide",
                "intent": "coach",
                "message": "I have an idea for a calmer coach reply flow.",
                "response_language": "en-US",
                "answer_mode": "coach-first",
                "current_file": {
                    "path": "server/app/api/routers.py",
                    "language_id": "python",
                    "content": "def route():\n    pass\n",
                    "diagnostics": [],
                    "recent_files": ["server/app/pedagogy/service.py"],
                    "recent_edited_files": ["server/app/api/routers.py"],
                    "related_files": [
                        {"path": "server/app/pedagogy/service.py", "reason": "coach decisions"},
                    ],
                },
            },
        )
        assert response.status_code == 200
        payload = response.json()
        guide = payload["snapshot"]["implementation_guide"]
        assert guide["scope_boundary"]
        assert guide["mvp_definition"]
        assert guide["current_step"]
        assert guide["validation_strategy"]
        assert guide["fallback_step"]
        assert guide["codebase_entry_points"]
        idea_artifact = next(
            artifact
            for artifact in payload["reply"]["metadata"]["artifacts"]
            if artifact["kind"] == "idea_implementation"
        )
        assert "Start in:" in idea_artifact["content"]


def test_project_adaptation_plan_generation_seeds_from_adaptation_guide(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-seed-adaptation",
                "workspace_name": "trainer-plan-seed-adaptation",
                "profile": {
                    "long_term_goal": "Adapt real projects without losing the first stable boundary",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        turn_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-plan-seed-adaptation",
                "intent": "coach",
                "message": "I want to adapt this project into a long-term coaching mode.",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
                "current_file": {
                    "path": "server/app/api/routers.py",
                    "language_id": "python",
                    "content": "def route():\n    pass\n",
                    "diagnostics": ["The router mixes orchestration and rendering details."],
                    "recent_files": ["server/app/pedagogy/service.py"],
                    "recent_edited_files": [
                        "server/app/api/routers.py",
                        "server/app/pedagogy/service.py",
                    ],
                    "related_files": [
                        {"path": "server/tests/test_api.py", "reason": "verification"},
                    ],
                },
            },
        )
        assert turn_response.status_code == 200
        turn_payload = turn_response.json()
        guide = turn_payload["snapshot"]["project_adaptation_guide"]

        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": ["Keep the adaptation lane grounded in the first safe boundary"],
                "constraints": ["Do not widen before verification"],
            },
        )
        assert plan_response.status_code == 200
        plan_payload = plan_response.json()["plan"]
        assert plan_payload["current_step"] == guide["first_migration_step"]
        assert plan_payload["verify_method"][0] == guide["validation_checkpoints"][0]
        assert guide["first_migration_step"].startswith("")


def test_project_idea_turn_updates_plan_runtime_from_structured_artifacts(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-project-idea-runtime",
                "workspace_name": "trainer-plan-project-idea-runtime",
                "profile": {
                    "long_term_goal": "Keep plan runtime aligned with project idea coaching",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        runtime = client.app.state.runtime
        runtime.memory_service.record_teaching_asset(
            "workspace-plan-project-idea-runtime",
            TeachingKnowledgeAsset(
                kind="exercise_seed",
                scope="project",
                workspace_id="workspace-plan-project-idea-runtime",
                title="Review scheduler regression loop",
                summary="Extract one tight review scheduler regression loop.",
                exercise_seed="Extract one tight review scheduler regression loop.",
                focus_area="review scheduler",
                scenario="project_idea_mining",
                source_key="seed::review-scheduler-plan-runtime",
                trust_score=0.88,
            ),
        )

        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": ["Keep the live training thread visible in the plan"],
                "constraints": ["Do not widen before verification"],
            },
        )
        assert plan_response.status_code == 200

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "What should I build or extract from this codebase next?",
                "response_language": "en-US",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        top_idea = payload["snapshot"]["project_ideas"][0]
        runtime_status = payload["snapshot"]["plan_runtime_status"]
        assert runtime_status["current_step"] == top_idea["first_step"]
        assert runtime_status["why_now"] == top_idea["why_now"]
        assert runtime_status["verify_method"][0] == top_idea["acceptance_signals"][0]


def test_project_sourcing_turn_updates_plan_runtime_from_structured_source(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-plan-project-source-runtime",
                "workspace_name": "trainer-plan-project-source-runtime",
                "profile": {
                    "long_term_goal": "Keep project sourcing grounded inside the training plan",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        plan_response = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "objectives": ["Find one realistic training source"],
                "constraints": ["Stay with a patch-sized first move"],
            },
        )
        assert plan_response.status_code == 200

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "Help me find public project sources that are good for training long-horizon coaching ability.",
                "response_language": "zh-CN",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        top_source = payload["snapshot"]["project_sources"][0]
        runtime_status = payload["snapshot"]["plan_runtime_status"]
        assert runtime_status["current_step"] == top_source["first_task"]
        assert runtime_status["why_now"] in {
            top_source["fit_reason"],
            top_source["training_value"],
            top_source["repo_hint"],
        }
        assert runtime_status["verify_method"]
        assert top_source["first_filter"] in runtime_status["verify_method"][0]


def test_turn_respects_coach_defaults_in_memory_and_prompt(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start_response = client.post(
            "/session/start",
            json={
                "profile": {
                    "long_term_goal": "Learn to reshape existing projects carefully",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
                "workspace_id": "workspace-defaults",
                "workspace_name": "trainer",
            },
        )
        assert start_response.status_code == 200

        response = client.post(
            "/turn",
            json={
                "workspace_id": "workspace-defaults",
                "intent": "coach",
                "message": "Keep the thread on the current project.",
                "response_language": "en-US",
                "answer_mode": "guided",
                "coach_defaults": {
                    "memory_scope": "personal",
                    "working_set_mode": "focused",
                    "review_cadence": "active",
                    "review_reminder_mode": "ahead",
                    "workspace_memory_toggles": {
                        "decisions": True,
                        "patterns": False,
                        "resources": False,
                    },
                },
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["reply"]["content"]
        assert payload["snapshot"]["memory"]["workspace"]["coach_defaults"]["working_set_mode"] == "focused"
        assert payload["snapshot"]["memory"]["workspace"]["coach_defaults"]["review_reminder_mode"] == "ahead"
        assert payload["snapshot"]["memory"]["resources"] == []


def test_user_feedback_persists_and_adapts_only_its_workspace(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/memory/feedback",
            json={
                "workspace_id": "workspace-feedback-a",
                "kind": "too_hard",
                "message": "The task was too hard to start independently.",
                "focus_area": "planner loop",
                "scenario": "idea_implementation",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        memory = payload["memory"]
        assert memory["userFeedback"][0]["kind"] == "too_hard"
        assert memory["workspace"]["latest_user_feedback"] == "The task was too hard to start independently."
        assert memory["coaching_adaptation"]["challenge_level"] == "lower"
        assert memory["coaching_adaptation"]["hint_depth"] == "direct"
        assert memory["coaching_adaptation"]["next_step_bias"] == "shrink"

        isolated = client.post(
            "/memory/feedback",
            json={
                "workspace_id": "workspace-feedback-b",
                "kind": "too_simple",
                "message": "This exercise was too simple.",
                "focus_area": "planner loop",
            },
        )
        assert isolated.status_code == 200
        isolated_memory = isolated.json()["memory"]
        assert isolated_memory["userFeedback"][0]["kind"] == "too_simple"
        assert isolated_memory["coaching_adaptation"]["challenge_level"] == "raise"
        assert isolated_memory["workspace"]["latest_user_feedback"] == "This exercise was too simple."
