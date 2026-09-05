from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.core.models import SessionMessageRequest
from app.llm.provider_service import redact_provider_error


def _run_bundled_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[2]
    bundled_server_dir = repo_root / "extension" / "bundled" / "server"
    tests_dir = repo_root / "server" / "tests"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(tests_dir), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), *args],
        cwd=bundled_server_dir,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def _bundled_stream_error_payload(endpoint: str, failure_kind: str) -> dict[str, object]:
    # Some library imports print to stdout on POSIX (e.g. PyMuPDF >= 1.28 emits
    # "warning: The `fitz` API is deprecated..." when `app.ingest` imports
    # `fitz`). The child therefore prints a unique sentinel line before the
    # JSON payload and the parent slices on it, so startup noise can never
    # corrupt the parity payload.
    payload_marker = "BUNDLED_STREAM_ERROR_PAYLOAD_JSON"
    result = _run_bundled_script(
        """
        import json
        import sys
        import tempfile
        from pathlib import Path
        from typing import Any
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from app.api import routers
        from app.core.models import ProviderConfig
        from app.core.settings import AppSettings
        from app.llm.provider_service import ProviderService
        from app.main import create_app
        from provider_fixtures import seed_verified_capabilities

        endpoint = sys.argv[1]
        failure_kind = sys.argv[2]
        api_key = "sk-bundled-stream-secret"
        unsafe_detail = (
            "provider rejected request (HTTP 429): literal sk-bundled-stream-secret; "
            "Authorization: Bearer bearer-bundled-secret; "
            "https://provider.invalid/chat?api_key=query-bundled-secret; "
            "response body: raw upstream response"
        )

        class ProviderFailure(RuntimeError):
            status_code = 429

        async def fake_agentic_stream(self: ProviderService, *_: Any, **__: Any):
            if failure_kind == "event":
                yield {"type": "error", "detail": unsafe_detail}
                return
            raise ProviderFailure(unsafe_detail)

        def error_payload(raw: str) -> dict[str, object]:
            for block in raw.split("\\n\\n"):
                if not block.startswith("event: error\\n"):
                    continue
                for line in block.splitlines():
                    if line.startswith("data:"):
                        return json.loads(line.removeprefix("data:").strip())
            raise AssertionError(f"missing SSE error event: {raw}")

        assert routers.__file__ is not None
        assert Path(routers.__file__).resolve() == Path.cwd().resolve() / "app" / "api" / "routers.py"
        with tempfile.TemporaryDirectory() as data_dir:
            settings = AppSettings(
                app_name="Bundled Stream Redaction Smoke",
                host="127.0.0.1",
                port=8765,
                data_dir=Path(data_dir),
                database_name="trainer-test.db",
                default_session_stage="intake",
                summary_message_limit=6,
                enable_network_fetch=False,
            )
            app = create_app(settings)
            provider = ProviderConfig(
                name="test-openai-compatible",
                base_url="http://127.0.0.1:9/v1",
                api_key_ref="trainer.default",
                model="gpt-4o-mini",
                capabilities={"tools": True, "streaming": True},
            )
            runtime = app.state.runtime
            runtime.provider_config = provider
            runtime.provider_api_key = api_key
            runtime.provider_service = ProviderService(config=provider, api_key=api_key)
            runtime.provider_service_cache.clear()
            seed_verified_capabilities(runtime, provider, api_key)

            with TestClient(app) as client, patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=fake_agentic_stream,
            ):
                workspace_id = f"bundled-stream-{failure_kind}-{endpoint.count('/')}"
                session_response = client.post(
                    "/session/start",
                    json={
                        "workspace_id": workspace_id,
                        "workspace_name": "Bundled Stream Redaction",
                        "profile": {"long_term_goal": "Ship a focused test", "weekly_hours": 4},
                    },
                )
                assert session_response.status_code == 200, session_response.text
                payload: dict[str, object] = {
                    "session_id": session_response.json()["session_id"],
                    "workspace_id": workspace_id,
                    "message": "Give me one small next step.",
                    "use_agent_loop": True,
                }
                if endpoint == "/turn/stream":
                    payload["intent"] = "coach"
                with client.stream("POST", endpoint, json=payload) as response:
                    assert response.status_code == 200
                    raw = b"".join(response.iter_bytes()).decode("utf-8", errors="replace")

        payload = error_payload(raw)
        assert api_key not in raw
        assert "bearer-bundled-secret" not in raw
        assert "query-bundled-secret" not in raw
        assert "raw upstream response" not in raw
        print('BUNDLED_STREAM_ERROR_PAYLOAD_JSON')
        print(json.dumps(payload, sort_keys=True))
        """,
        endpoint,
        failure_kind,
    )
    assert result.returncode == 0, result.stderr
    stdout = result.stdout
    if payload_marker in stdout:
        stdout = stdout.split(payload_marker, 1)[1]
    return json.loads(stdout)


def test_bundled_session_message_formal_plan_mutation_matches_source_contract() -> None:
    source_camel_request = SessionMessageRequest.model_validate(
        {"message": "Keep the plan current.", "formalPlanMutation": True}
    )
    source_snake_request = SessionMessageRequest(
        message="Keep the plan current.",
        formal_plan_mutation=True,
    )
    result = _run_bundled_script(
        """
        import json

        from app.core.models import SessionMessageRequest

        camel_request = SessionMessageRequest.model_validate(
            {"message": "Keep the plan current.", "formalPlanMutation": True}
        )
        snake_request = SessionMessageRequest(
            message="Keep the plan current.",
            formal_plan_mutation=True,
        )
        print(
            json.dumps(
                {
                    "camel": camel_request.formal_plan_mutation,
                    "snake": snake_request.formal_plan_mutation,
                    "alias": camel_request.model_dump(by_alias=True)["formalPlanMutation"],
                },
                sort_keys=True,
            )
        )
        """
    )

    assert result.returncode == 0, result.stderr
    assert source_camel_request.formal_plan_mutation is True
    assert source_snake_request.formal_plan_mutation is True
    assert source_camel_request.model_dump(by_alias=True)["formalPlanMutation"] is True
    assert json.loads(result.stdout) == {"alias": True, "camel": True, "snake": True}


def test_bundled_nonofficial_anthropic_disables_thinking_on_first_request() -> None:
    result = _run_bundled_script(
        """
        import asyncio
        import json
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.llm.agent_binding import ProviderAgentBinding

        class Response:
            status_code = 200

            def __init__(self, body):
                self._body = body

            def json(self):
                return self._body

        async def main():
            service = SimpleNamespace(
                _api_key="sk-bundled-test",
                _config=SimpleNamespace(
                    name="compatible-gateway",
                    base_url="https://gateway.example/v1",
                    model="compatible-model",
                    capabilities=SimpleNamespace(vision=False, chat=True),
                ),
            )
            binding = ProviderAgentBinding(
                provider_service=service,
                protocol="anthropic_messages",
            )
            client = MagicMock()
            client.post = AsyncMock(
                return_value=Response(
                    {
                        "content": [{"type": "text", "text": "complete reply"}],
                        "stop_reason": "end_turn",
                    }
                )
            )
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=client)
            context.__aexit__ = AsyncMock(return_value=False)
            with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=context):
                reply = await binding.build_agent_provider().call(
                    [{"role": "user", "content": "help me"}],
                    None,
                )
            payload = client.post.call_args.kwargs["json"]
            print(
                json.dumps(
                    {
                        "reply": reply["content"],
                        "request_count": client.post.await_count,
                        "thinking": payload.get("thinking"),
                    },
                    sort_keys=True,
                )
            )

        asyncio.run(main())
        """
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "reply": "complete reply",
        "request_count": 1,
        "thinking": {"type": "disabled"},
    }


def test_bundled_truncation_fallback_disables_openai_thinking() -> None:
    result = _run_bundled_script(
        """
        import asyncio
        import json
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.llm.agent_binding import ProviderAgentBinding

        class Response:
            status_code = 200

            def __init__(self, body):
                self._body = body

            def json(self):
                return self._body

        async def main():
            openai_choice = MagicMock()
            openai_choice.message.content = "fallback reply"
            openai_choice.message.tool_calls = []
            openai_response = MagicMock()
            openai_response.choices = [openai_choice]
            openai_client = MagicMock()
            openai_client.chat.completions.create = AsyncMock(return_value=openai_response)
            service = SimpleNamespace(
                _api_key="sk-bundled-test",
                _config=SimpleNamespace(
                    name="compatible-gateway",
                    base_url="https://gateway.example/v1",
                    model="compatible-model",
                    capabilities=SimpleNamespace(vision=False, chat=True),
                ),
                _get_client=MagicMock(return_value=openai_client),
                _apply_request_defaults=lambda payload: payload,
                _resolve_model=lambda: "compatible-model",
                _model_candidates=lambda model: [model],
                _is_model_not_supported_error=lambda exc: False,
            )
            binding = ProviderAgentBinding(
                provider_service=service,
                protocol="anthropic_messages",
            )
            native_client = MagicMock()
            native_client.post = AsyncMock(
                side_effect=[
                    Response(
                        {
                            "content": [{"type": "text", "text": "first partial"}],
                            "stop_reason": "max_tokens",
                        }
                    ),
                    Response(
                        {
                            "content": [{"type": "text", "text": "second partial"}],
                            "stop_reason": "max_tokens",
                        }
                    ),
                ]
            )
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=native_client)
            context.__aexit__ = AsyncMock(return_value=False)
            with patch("app.llm.agent_binding.httpx.AsyncClient", return_value=context):
                reply = await binding.build_agent_provider().call(
                    [{"role": "user", "content": "help me"}],
                    None,
                )
            _, kwargs = openai_client.chat.completions.create.call_args
            explicit_binding = ProviderAgentBinding(
                provider_service=SimpleNamespace(
                    _config=SimpleNamespace(base_url="https://gateway.example/v1"),
                    _provider_request_defaults=lambda: {
                        "extra_body": {"thinking": {"type": "enabled"}}
                    },
                ),
                protocol="anthropic_messages",
            )
            explicit_payload = {"messages": [{"role": "user", "content": "help me"}]}
            print(
                json.dumps(
                    {
                        "reply": reply["content"],
                        "thinking": kwargs["extra_body"]["thinking"],
                        "explicit_preserved": (
                            explicit_binding._apply_compatibility_thinking_disabled(
                                explicit_payload
                            )
                            == explicit_payload
                        ),
                    },
                    sort_keys=True,
                )
            )

        asyncio.run(main())
        """
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "explicit_preserved": True,
        "reply": "fallback reply",
        "thinking": {"type": "disabled"},
    }


@pytest.mark.parametrize("endpoint", ["/session/message/stream", "/turn/stream"])
@pytest.mark.parametrize("failure_kind", ["event", "exception"])
def test_bundled_stream_error_redaction_matches_source_sidecar(
    endpoint: str,
    failure_kind: str,
) -> None:
    api_key = "sk-bundled-stream-secret"
    unsafe_detail = (
        "provider rejected request (HTTP 429): literal sk-bundled-stream-secret; "
        "Authorization: Bearer bearer-bundled-secret; "
        "https://provider.invalid/chat?api_key=query-bundled-secret; "
        "response body: raw upstream response"
    )

    class ProviderFailure(RuntimeError):
        status_code = 429

    source_detail = (
        redact_provider_error(unsafe_detail, api_key=api_key)
        if failure_kind == "event"
        else redact_provider_error(ProviderFailure(unsafe_detail), api_key=api_key)
    )

    bundled_payload = _bundled_stream_error_payload(endpoint, failure_kind)

    assert bundled_payload["error"] == source_detail


def test_bundled_session_message_accepts_simple_provider_override_without_api_key_ref(
    tmp_path: Path,
) -> None:
    result = _run_bundled_script(
        """
        from pathlib import Path
        import sys
        from unittest.mock import MagicMock, patch

        from fastapi.testclient import TestClient

        from app.core.settings import AppSettings
        from app.main import create_app

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

        settings = AppSettings(
            app_name="Bundled Trainer Smoke",
            host="127.0.0.1",
            port=8765,
            data_dir=Path(sys.argv[1]),
            database_name="trainer-test.db",
            default_session_stage="intake",
            summary_message_limit=6,
            enable_network_fetch=False,
        )
        app = create_app(settings)

        with patch(
            "app.llm.provider_service.ProviderService._create_chat_completion",
            new=fake_create_chat_completion,
        ):
            with TestClient(app) as client:
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
                assert start_response.status_code == 200, start_response.text
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
                print(message_response.json()["reply"]["content"])
        """,
        str(tmp_path / "provider-override"),
    )

    assert result.returncode == 0, result.stderr
    assert "Keep the first patch tiny." in result.stdout


def test_bundled_strip_short_cyrillic_noise_from_visible_reply() -> None:
    result = _run_bundled_script(
        """
        from app.llm.provider_service import _strip_short_cyrillic_noise

        print(
            _strip_short_cyrillic_noise(
                "Good \\u0431\\u043a staying tiny and grounded.",
                message="Help me keep the first training slice very small.",
            )
        )
        """
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Good staying tiny and grounded."


def test_bundled_models_accept_auto_coach_defaults() -> None:
    result = _run_bundled_script(
        """
        import json

        from app.core.models import TurnRequest, UserProfile

        profile = UserProfile()
        turn = TurnRequest.model_validate(
            {
                "workspace_id": "workspace-auto-defaults",
                "intent": "coach",
                "message": "Teach me in auto mode.",
                "answer_mode": "auto",
            }
        )
        print(
            json.dumps(
                {
                    "teaching_style": profile.teaching_style,
                    "answer_policy": profile.answer_policy,
                    "turn_answer_mode": turn.answer_mode,
                }
            )
        )
        """
    )

    assert result.returncode == 0, result.stderr
    payload = result.stdout.strip()
    assert '"teaching_style": "auto"' in payload
    assert '"answer_policy": "auto"' in payload
    assert '"turn_answer_mode": "auto"' in payload


def test_bundled_timeout_recovery_for_general_non_code_request_stays_learn_first() -> None:
    result = _run_bundled_script(
        """
        import json

        from app.llm.provider_service import _build_timeout_recovery_override

        payload = _build_timeout_recovery_override(
            "\\u8bf7\\u5148\\u6559\\u6211\\u7528\\u914d\\u65b9\\u6cd5\\u7406\\u89e3\\u4e00\\u5143\\u4e8c\\u6b21\\u65b9\\u7a0b\\uff0c\\u4e0d\\u8981\\u4e00\\u4e0a\\u6765\\u5c31\\u8003\\u8bd5\\u6211\\u3002",
            current_file=None,
            coach_context={
                "scenario": "general",
                "current_focus": "\\u7528\\u914d\\u65b9\\u6cd5\\u7406\\u89e3\\u4e00\\u5143\\u4e8c\\u6b21\\u65b9\\u7a0b",
            },
            response_language="zh-CN",
        )
        print(json.dumps(payload, ensure_ascii=True))
        """
    )

    assert result.returncode == 0, result.stderr
    payload = result.stdout
    assert "\\u89e3\\u91ca" in payload or "\\u4f8b\\u9898" in payload or "\\u63a8\\u5bfc" in payload
    assert "\\u672c\\u5730\\u53ef\\u89c1" not in payload
    assert "Learn-first" in payload


def test_bundled_provider_error_recovery_for_general_non_code_request_stays_learn_first() -> None:
    result = _run_bundled_script(
        """
        import json

        from app.llm.provider_service import _build_provider_error_recovery_override

        payload = _build_provider_error_recovery_override(
            "Teach me the word resilient with one sentence and one contrast before any quiz.",
            current_file=None,
            coach_context={
                "scenario": "general",
                "current_focus": "the word resilient in one sentence",
            },
            response_language="en-US",
            error_detail="status 502",
        )
        print(json.dumps(payload, ensure_ascii=True))
        """
    )

    assert result.returncode == 0, result.stderr
    payload = result.stdout.lower()
    assert "sentence" in payload or "contrast" in payload
    assert "local, visible, verifiable move" not in payload
    assert "learn-first" in payload


def test_bundled_language_corruption_recovery_for_general_writing_request_ignores_stale_remote_lane() -> None:
    result = _run_bundled_script(
        """
        import json

        from app.llm.provider_service import _build_language_corruption_recovery_override

        payload = _build_language_corruption_recovery_override(
            "Help me revise one English project update paragraph. Only fix this paragraph and keep it natural.",
            current_file=None,
            coach_context={
                "scenario": "general",
                "history_mode": "fresh_lane",
                "current_focus": "Switch provider or gateway, or continue this remote lesson in English first.",
                "summary": "I am still keeping this turn in the VS Code remote lane.",
                "thread_summary": "Teach me VS Code Remote SSH step by step.",
                "thread_next_step": "Tell me whether the workspace is SSH, tunnels, dev container, WSL, or local.",
            },
            response_language="en-US",
        )
        print(json.dumps(payload, ensure_ascii=True))
        """
    )

    assert result.returncode == 0, result.stderr
    payload = result.stdout.lower()
    assert '"scenario": "general"' in payload
    assert "remote lane" not in payload
    assert "sentence" in payload or "paragraph" in payload


def test_bundled_conversation_gap_generation_switches_active_training_lane(tmp_path: Path) -> None:
    result = _run_bundled_script(
        """
        from pathlib import Path
        import sys

        from fastapi.testclient import TestClient

        from app.core.models import ProviderConfig
        from app.core.settings import AppSettings
        from app.llm.provider_service import ProviderService
        from app.main import create_app
        from provider_fixtures import seed_verified_capabilities

        settings = AppSettings(
            app_name="Bundled Trainer Lane Switch Smoke",
            host="127.0.0.1",
            port=8765,
            data_dir=Path(sys.argv[1]),
            database_name="trainer-test.db",
            default_session_stage="intake",
            summary_message_limit=6,
            enable_network_fetch=False,
        )
        app = create_app(settings)
        api_key = "sk-bundled-lane-switch-secret"
        provider = ProviderConfig(
            name="test-openai-compatible",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={"tools": True, "streaming": True},
        )
        runtime = app.state.runtime
        runtime.provider_config = provider
        runtime.provider_api_key = api_key
        runtime.provider_service = ProviderService(config=provider, api_key=api_key)
        runtime.provider_service_cache.clear()
        seed_verified_capabilities(runtime, provider, api_key)

        with TestClient(app) as client:
            workspace_id = "bundled-sequential-lane-switch"

            def generate(focus_area: str, target_skill: str, context_hint: str) -> dict:
                response = client.post(
                    "/training/generate-card",
                    json={
                        "workspace_id": workspace_id,
                        "source": "conversation_gap",
                        "card_type": "practice",
                        "focus_area": focus_area,
                        "target_skill": target_skill,
                        "context_hint": context_hint,
                        "why_now": "The learner asked Coach for one learn-first training move.",
                        "difficulty": "medium",
                        "response_language": "zh-CN",
                    },
                )
                assert response.status_code == 200, response.text
                return response.json()

            remote = generate(
                "VS Code remote workspace",
                "remote workspace boundary",
                "Coach request: 请先一步一步教我 VS Code Remote SSH，再测试我。",
            )
            debug = generate(
                "VS Code debug loop",
                "the smallest trustworthy debug loop",
                "Coach request: 请先一步一步教我怎么在 VS Code 里 debug Python，再测试我。",
            )
            function = generate(
                "VS Code function guidance",
                "function contract and call-site reading",
                "Coach request: 请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
            )

            assert remote["card"]["scenario_pack"] == "remote_workspace"
            assert remote["active_routing"]["selected_card"]["scenario_pack"] == "remote_workspace"
            assert debug["card"]["scenario_pack"] == "debug_loop"
            assert debug["active_routing"]["selected_card"]["scenario_pack"] == "debug_loop"
            assert function["card"]["scenario_pack"] == "function_guidance"
            assert function["active_routing"]["selected_card"]["scenario_pack"] == "function_guidance"

            print("ok")
        """,
        str(tmp_path / "lane-switch"),
    )

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_bundled_openai_chat_call_handles_string_response() -> None:
    result = _run_bundled_script(
        """
        import asyncio
        from types import SimpleNamespace

        from app.llm.agent_binding import ProviderAgentBinding

        class FakeCompletions:
            async def create(self, *, model, **kwargs):
                return "Visible compatibility reply"

        class FakeClient:
            def __init__(self):
                self.chat = SimpleNamespace(completions=FakeCompletions())

        class FakeConfig:
            base_url = "http://minimax.redfast.top"
            protocol = "openai_chat_completions_compatible"

        class FakeProviderService:
            _config = FakeConfig()

            def _get_client(self):
                return FakeClient()

            def _apply_request_defaults(self, payload):
                return payload

            def _resolve_model(self):
                return "MiniMax-M3"

            def _model_candidates(self, model):
                return [model]

            def _is_model_not_supported_error(self, exc):
                return False

        async def main():
            binding = ProviderAgentBinding(
                provider_service=FakeProviderService(),
                protocol="openai_chat_completions_compatible",
            )
            result = await binding._openai_chat_call(
                [{"role": "user", "content": "Keep the reply visible."}],
                None,
            )
            print(result["content"])

        asyncio.run(main())
        """
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Visible compatibility reply"
