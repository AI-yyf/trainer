from __future__ import annotations

import importlib.util
import json
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "live-protocol-probe.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("live_protocol_probe", SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib guard
        raise RuntimeError(f"Could not load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_prompts_are_readable_utf8() -> None:
    module = _load_module()

    assert "learn-first practice card" in module.DEFAULT_REMOTE_PROMPT
    assert "VS Code Remote SSH" in module.DEFAULT_REMOTE_PROMPT
    assert "可验证" in module.DEFAULT_REMOTE_PROMPT

    assert "learn-first practice card" in module.DEFAULT_DEBUG_PROMPT
    assert "debug Python" in module.DEFAULT_DEBUG_PROMPT
    assert "breakpoint" in module.DEFAULT_DEBUG_PROMPT

    assert "learn-first practice card" in module.DEFAULT_FUNCTION_PROMPT
    assert "TypeScript fetch options" in module.DEFAULT_FUNCTION_PROMPT


def test_load_cases_rejects_inline_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv(
        "TRAINER_LIVE_PROTOCOL_CASES_JSON",
        json.dumps(
            [
                {
                    "protocol": "openai_chat_completions_compatible",
                    "baseUrl": "http://gateway.example",
                    "model": "MiniMax-M3",
                    "apiKey": "inline-secret-must-not-be-accepted",
                },
            ]
        ),
    )

    with pytest.raises(RuntimeError, match="must not contain apiKey"):
        module._load_cases()


def test_load_cases_rejects_empty_inline_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv(
        "TRAINER_LIVE_PROTOCOL_CASES_JSON",
        json.dumps(
            [
                {
                    "protocol": "openai_chat_completions_compatible",
                    "baseUrl": "http://gateway.example",
                    "model": "MiniMax-M3",
                    "apiKey": "",
                },
            ]
        ),
    )

    with pytest.raises(RuntimeError, match="must not contain apiKey"):
        module._load_cases()


def test_resolve_case_api_key_uses_only_global_environment_value() -> None:
    module = _load_module()

    assert (
        module._resolve_case_api_key({"protocol": "openai_responses", "apiKey": "ignored"}, "env-secret")
        == "env-secret"
    )

    with pytest.raises(RuntimeError, match="requires TRAINER_LIVE_PROTOCOL_API_KEY"):
        module._resolve_case_api_key({"protocol": "openai_responses"}, None)


def test_assert_turn_rejects_generic_interruption_reply() -> None:
    module = _load_module()

    payload = {
        "reply": {
            "content": "这一轮教练服务在中途断开了，但我们可以沿着同一条主线续回去。 当前主线还是：function contract 判断。"
        },
        "coach_turn": {"scenario": "function_guidance"},
        "snapshot": {
            "memory": {
                "active_training_card_routing": {
                    "selected_card_id": "card-1",
                    "selected_card": {
                        "id": "card-1",
                        "card_type": "practice",
                        "scenario_pack": "function_guidance",
                        "title": "函数 contract 判断",
                        "problem_statement": "先基于真实 call site 读取函数 contract。",
                    },
                }
            }
        },
    }

    with pytest.raises(RuntimeError, match="generic interruption copy"):
        module._assert_turn(
            case_protocol="anthropic_messages",
            payload=payload,
            expected_scenario="function_guidance",
            expected_pack="function_guidance",
            label="function",
        )


def test_assert_turn_summary_omits_reply_content() -> None:
    module = _load_module()
    payload = {
        "reply": {"content": "请先从真实 call site 读取 fetch 的 options，再验证一次。"},
        "coach_turn": {"scenario": "function_guidance"},
        "snapshot": {
            "memory": {
                "active_training_card_routing": {
                    "selected_card": {
                        "card_type": "practice",
                        "scenario_pack": "function_guidance",
                        "title": "函数 contract 判断",
                        "problem_statement": "先读取真实 call site，再确认参数语义。",
                    }
                }
            }
        },
    }

    summary = module._assert_turn(
        case_protocol="anthropic_messages",
        payload=payload,
        expected_scenario="function_guidance",
        expected_pack="function_guidance",
        label="function",
    )

    assert summary == {"scenario": "function_guidance", "scenarioPack": "function_guidance"}


def test_provider_result_summary_uses_only_safe_status_fields() -> None:
    module = _load_module()

    summary = module._provider_result_summary(
        {
            "status": "auth_failed",
            "error_category": "invalid_key_or_permission",
            "status_code": 401,
            "retryable": False,
            "detail": "credential should never be printed",
        }
    )

    assert summary == "status=auth_failed, error_category=invalid_key_or_permission, status_code=401, retryable=False"
    assert "credential" not in summary


def test_post_json_with_retries_recovers_transient_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    calls = 0

    def fake_post_json(*_args: object, **_kwargs: object) -> tuple[int, dict[str, object]]:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("temporary gateway failure")
        return 200, {"ok": True}

    monkeypatch.setattr(module, "_post_json", fake_post_json)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    assert module._post_json_with_retries("http://sidecar", "/provider/test", {}) == (
        200,
        {"ok": True},
    )
    assert calls == 3


def test_loopback_sidecar_bypasses_ambient_proxy_without_leaking_env_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    observed: dict[str, str | None] = {}

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "example.invalid")
    monkeypatch.setenv("no_proxy", "example.invalid")

    def fake_urlopen(_request: urllib.request.Request, *, timeout: int):
        observed["no_proxy"] = module.os.environ.get("NO_PROXY")
        observed["lower_no_proxy"] = module.os.environ.get("no_proxy")
        assert timeout == 5
        return _FakeResponse()

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

        status = 200

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    status, payload = module._post_json("http://127.0.0.1:34914", "/health", {}, timeout=5)

    assert status == 200
    assert payload == {"ok": True}
    assert "127.0.0.1" in str(observed["no_proxy"])
    assert module.os.environ["NO_PROXY"] == "example.invalid"
    assert module.os.environ["no_proxy"] == "example.invalid"
