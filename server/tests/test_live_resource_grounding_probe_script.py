from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "live-resource-grounding-probe.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("live_resource_grounding_probe", SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib guard
        raise RuntimeError(f"Could not load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_grounding_prompt_is_readable_utf8() -> None:
    module = _load_module()

    assert "我刚导入了一份设计文档。" in module.DEFAULT_GROUNDING_PROMPT
    assert "Resources 视图" in module.DEFAULT_GROUNDING_PROMPT
    assert "first viewport promise" in module.DEFAULT_GROUNDING_PROMPT
    assert "绝不能变成什么" in module.DEFAULT_GROUNDING_PROMPT
    assert "鎴戝垰" not in module.DEFAULT_GROUNDING_PROMPT
    assert module.DEFAULT_RESOURCE_PATH.name == "2026-06-29-unified-coach-master-plan.md"


def test_load_cases_rejects_inline_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv(
        "TRAINER_LIVE_GROUNDING_CASES_JSON",
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
        "TRAINER_LIVE_GROUNDING_CASES_JSON",
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

    with pytest.raises(RuntimeError, match="requires TRAINER_LIVE_GROUNDING_API_KEY"):
        module._resolve_case_api_key({"protocol": "openai_responses"}, None)


def test_reply_contract_helpers_detect_promise_and_boundary() -> None:
    module = _load_module()

    assert module._reply_mentions_promise(
        "Resources 视图的 first viewport promise 是先让用户定位资料，再决定下一步。"
    )
    assert module._reply_mentions_boundary(
        "它不能退化成 raw filesystem browser，而要保持知识库和受控沙箱的语义。"
    )


def test_collect_grounding_evidence_extracts_search_hits_and_contract_coverage() -> None:
    module = _load_module()

    payload = {
        "agent_meta": {
            "auto_resource_lookup": True,
            "stop_reason": "completed",
            "tool_events": [
                {
                    "type": "tool_call",
                    "name": "search_resources",
                },
                {
                    "type": "tool_result",
                    "name": "search_resources",
                    "result": {
                        "query": "Resources first viewport promise",
                        "hits": [
                            {
                                "title": "2026-06-29-unified-coach-master-plan.md",
                            },
                            {
                                "title": "2026-06-29-unified-coach-master-plan.md",
                            },
                        ],
                    },
                },
            ],
        },
        "reply": {
            "content": (
                "Resources 视图的首屏承诺，是让学习者先找到、确认、预览并转化资料。"
                "它不能退化成 raw filesystem browser。"
            ),
        },
    }

    evidence = module._collect_grounding_evidence(
        payload,
        expected_title="2026-06-29-unified-coach-master-plan.md",
    )

    assert evidence["autoResourceLookup"] is True
    assert evidence["searchCalls"] == 1
    assert evidence["searchResults"] == 1
    assert evidence["matchedExpectedTitle"] is True
    assert evidence["replyPresent"] is True
    assert evidence["replyHasCjk"] is True
    assert evidence["mentionsPromise"] is True
    assert evidence["mentionsBoundary"] is True
    assert evidence["coversRequestedContract"] is True
    assert evidence["stopCompleted"] is True


def test_collect_grounding_evidence_flags_missing_boundary() -> None:
    module = _load_module()

    payload = {
        "agent_meta": {
            "tool_events": [],
        },
        "reply": {
            "content": "Resources 视图的首屏承诺，是让用户快速确认资料是否值得继续学习。",
        },
    }

    evidence = module._collect_grounding_evidence(
        payload,
        expected_title="2026-06-29-unified-coach-master-plan.md",
    )

    assert evidence["mentionsPromise"] is True
    assert evidence["mentionsBoundary"] is False
    assert evidence["coversRequestedContract"] is False


def test_post_json_redacts_http_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    secret = b"live-grounding-upstream-secret"

    def raise_http_error(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.HTTPError(
            "http://127.0.0.1:8765/resource/upload",
            500,
            "server error",
            None,
            io.BytesIO(secret),
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", raise_http_error)

    with pytest.raises(module.ProbeFailure) as raised:
        module._post_json("http://127.0.0.1:8765", "/resource/upload", {})

    assert raised.value.step == "resource_upload"
    assert raised.value.category == "http_error"
    assert raised.value.status == 500
    assert secret.decode() not in str(raised.value)


def test_loopback_sidecar_bypasses_ambient_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    observed: dict[str, str | None] = {}
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "example.invalid")

    class _FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

    def fake_urlopen(_request: urllib.request.Request, *, timeout: int):
        observed["no_proxy"] = module.os.environ.get("NO_PROXY")
        assert timeout == 5
        return _FakeResponse()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    status, payload = module._post_json("http://127.0.0.1:34914", "/health", {}, timeout=5)

    assert status == 200
    assert payload == {"ok": True}
    assert "127.0.0.1" in str(observed["no_proxy"])
    assert module.os.environ["NO_PROXY"] == "example.invalid"
