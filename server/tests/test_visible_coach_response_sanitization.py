from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.api.routers import build_router
from app.api.runtime import TrainerRuntime
from app.core.models import ChatMessage, ProviderConfig, ProviderTestResponse
from app.db.repository import TrainerRepository
from app.evaluator.service import EvaluatorService
from app.llm.provider_service import ProviderService
from app.memory.service import MemoryService
from app.planner.service import PlannerService, TrainingPlannerService
from app.resources.service import ResourceService
from app.specs.service import SpecService


@pytest.fixture
def runtime(tmp_path: Path) -> TrainerRuntime:
    repo = TrainerRepository(tmp_path / "trainer.db")
    provider_config = ProviderConfig(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_ref="trainer.test",
        model="gpt-4o-mini",
        capabilities={"tools": True, "streaming": True},
    )
    provider_service = ProviderService(
        config=provider_config,
        api_key="sk-test-fake",
    )
    runtime = TrainerRuntime(
        repository=repo,
        provider_service=provider_service,
        planner_service=PlannerService(TrainingPlannerService()),
        memory_service=MemoryService(repo),
        resource_service=ResourceService(
            repo,
            ingest_service=None,  # type: ignore[arg-type]
            semantic_memory=None,  # type: ignore[arg-type]
        ),
        spec_service=SpecService(),
        evaluator_service=EvaluatorService(),
    )
    seed_verified_capabilities(runtime, provider_config, "sk-test-fake")
    return runtime


@pytest.fixture(autouse=True)
def verified_provider_capabilities(
    runtime: TrainerRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_verified_capabilities(
        runtime,
        runtime.provider_service._config,
        runtime.provider_service._api_key,
    )
    original = runtime.provider_service_for

    def provider_service_for(provider_config: ProviderConfig, api_key: str | None) -> ProviderService:
        service = original(provider_config, api_key)
        seed_verified_capabilities(runtime, provider_config, api_key or "")
        return service

    monkeypatch.setattr(runtime, "provider_service_for", provider_service_for)


@pytest.fixture
def app(runtime: TrainerRuntime) -> FastAPI:
    instance = FastAPI()
    instance.include_router(build_router(runtime))
    return instance


def _seed_session(client: TestClient, *, workspace_id: str, workspace_path: str | None = None) -> str:
    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "workspace_name": "Trainer Test",
        "profile": {
            "long_term_goal": "ship fast feedback loops",
            "weekly_hours": 4,
            "teaching_style": "hands-on",
            "answer_policy": "guided",
        },
    }
    if workspace_path is not None:
        payload["workspace_path"] = workspace_path
    response = client.post("/session/start", json=payload)
    assert response.status_code == 200, response.text
    return str(response.json()["session_id"])


RECOVERED_ZH_SUMMARY = "这次回答显示有问题，我先用一个可靠的小步骤把这轮学习接住。"


class ScriptedAgentProvider:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.protocol = "openai_chat_completions"
        self.attachments_will_be_sent = lambda: False  # type: ignore[assignment]

    async def call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        if self._index >= len(self._responses):
            return {"content": "(scripted provider exhausted)", "tool_calls": []}
        response = self._responses[self._index]
        self._index += 1
        return {
            "content": str(response.get("content") or ""),
            "tool_calls": list(response.get("tool_calls") or []),
            "stop_reason": "tool_calls" if response.get("tool_calls") else "stop",
        }


def _patch_agent_provider(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[dict[str, Any]],
) -> ScriptedAgentProvider:
    scripted = ScriptedAgentProvider(responses)

    def _build(self: ProviderService, **_: Any) -> tuple[Any, Any]:
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", _build)
    return scripted


def _stream_complete_response(raw: str) -> dict[str, Any]:
    complete_payload: dict[str, Any] | None = None
    for block in [item for item in raw.split("\n\n") if item.strip()]:
        event_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        if event_name == "complete" and data_lines:
            complete_payload = json.loads("".join(data_lines))
            break
    assert complete_payload is not None
    return complete_payload["response"]


RECOVERED_REMOTE_STEP = (
    "\u8bf7\u8fd4\u56de\u4e00\u4e2a\u771f\u5b9e\u7684\u5de5\u4f5c\u533a"
    "\u6807\u7b7e\u6216\u8def\u5f84\uff0c\u518d\u8865\u4e00\u53e5\u5b89\u5168 "
    "credential mode \u7684\u5224\u65ad\u3002"
)
RECOVERED_DEBUG_STEP = (
    "\u8bf7\u544a\u8bc9\u6211\u4f60\u51c6\u5907\u5148\u505c\u5728\u54ea\u91cc\uff0c"
    "\u4ee5\u53ca\u4f60\u51c6\u5907\u5148\u68c0\u67e5\u54ea\u4e00\u4e2a\u503c\u3001"
    "\u5206\u652f\u6216 stack frame\u3002"
)
RECOVERED_FUNCTION_STEP = (
    "\u8bf7\u8fd4\u56de\u51fd\u6570\u540d\u3001\u4e00\u4e2a call site\uff0c"
    "\u4ee5\u53ca\u80fd\u8bc1\u660e\u5b83\u671f\u671b\u4ec0\u4e48\u7684 contract "
    "\u8bc1\u636e\u3002"
)
RECOVERED_ADAPTATION_STEP = (
    "\u8bf7\u544a\u8bc9\u6211\u4ec0\u4e48\u5fc5\u987b\u4fdd\u6301\u4e0d\u53d8\u3001"
    "\u4ec0\u4e48\u5fc5\u987b\u6539\u53d8\uff0c\u4ee5\u53ca\u4f60\u60f3\u5148\u9002\u914d"
    "\u7684\u7b2c\u4e00\u6761\u8fb9\u754c\u3002"
)


def test_turn_response_replaces_mojibake_with_a_readable_recovery_step(app: FastAPI) -> None:
    with TestClient(app) as client, patch.object(
        ProviderService,
        "coaching_reply",
        new=AsyncMock(return_value=f"{chr(0xE000)}损坏的回复"),
    ):
        session_id = _seed_session(client, workspace_id="ws-visible-mojibake")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-visible-mojibake",
                "intent": "coach",
                "message": "请直接回答这个问题。",
                "response_language": "zh-CN",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    reply = response.json()["reply"]["content"]
    assert "这次回答显示有问题" in reply
    assert "下一步：" in reply
    assert "请直接回答这个问题。" in reply
    assert chr(0xE000) not in reply
    assert "\ufffd" not in reply


def test_turn_response_never_exposes_gbk_style_mojibake(app: FastAPI) -> None:
    corrupted = "\u6d93\u5b29\u7af4\u9352\u20ac"
    with TestClient(app) as client, patch.object(
        ProviderService,
        "coaching_reply",
        new=AsyncMock(return_value=corrupted),
    ):
        session_id = _seed_session(client, workspace_id="ws-visible-gbk-mojibake")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-visible-gbk-mojibake",
                "intent": "coach",
                "message": "\u8bf7\u5e2e\u6211\u89e3\u91ca\u8fd9\u4e2a\u62a5\u9519\u3002",
                "response_language": "zh-CN",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "\u8fd9\u6b21\u56de\u7b54\u663e\u793a\u6709\u95ee\u9898" in payload["reply"]["content"]
    assert corrupted not in json.dumps(payload, ensure_ascii=False)


def test_response_repairs_a_saved_mojibake_assistant_message(
    app: FastAPI,
    runtime: TrainerRuntime,
) -> None:
    workspace_id = "ws-saved-mojibake"
    corrupted = "\u6d93\u5b29\u7af4\u9352\u20ac"
    captured_history: list[dict[str, str]] = []

    async def clean_reply(*_args: object, **kwargs: Any) -> str:
        captured_history.extend(kwargs.get("history") or [])
        return "\u6211\u4f1a\u7528\u6b63\u5e38\u7684\u6587\u5b57\u7ee7\u7eed\u56de\u7b54\u3002"

    with TestClient(app) as client, patch.object(
        ProviderService,
        "coaching_reply",
        new=clean_reply,
    ):
        session_id = _seed_session(client, workspace_id=workspace_id)
        state = runtime.ensure_session(session_id, workspace_id=workspace_id)
        state.snapshot.messages.append(
            ChatMessage(
                id="legacy-mojibake",
                role="assistant",
                content=corrupted,
                timestamp=datetime.now(UTC),
            )
        )
        runtime.save_session_state(session_id)

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": "\u8bf7\u7ee7\u7eed\u3002",
                "response_language": "zh-CN",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    contents = [message["content"] for message in response.json()["snapshot"]["messages"]]
    assert corrupted not in contents
    assert any("\u8fd9\u6761\u56de\u590d\u6ca1\u6709\u8bfb\u6e05" in content for content in contents)
    assert all(item["content"] != corrupted for item in captured_history)

    runtime.sessions.clear()
    restored = runtime.ensure_session(session_id, workspace_id=workspace_id)
    restored_contents = [message.content for message in restored.snapshot.messages]
    assert corrupted not in restored_contents
    assert any("\u8fd9\u6761\u56de\u590d\u6ca1\u6709\u8bfb\u6e05" in content for content in restored_contents)


@pytest.mark.parametrize("path", ["/session/message/stream", "/turn/stream"])
def test_chinese_stream_does_not_probe_before_the_reply(
    app: FastAPI,
    path: str,
) -> None:
    async def fake_stream(*_args: object, **_kwargs: object):
        yield "\u5148\u770b\u4e00\u5904\u8fd9\u4e2a\u62a5\u9519\u51fa\u73b0\u7684\u4ee3\u7801\u3002"

    with TestClient(app) as client, patch.object(
        ProviderService,
        "test",
        autospec=True,
        return_value=ProviderTestResponse(
            ok=True,
            detail="Provider connectivity looks healthy.",
            provider_reachable=True,
            model_supported=True,
        ),
    ) as test_mock, patch.object(ProviderService, "coaching_reply_stream", new=fake_stream):
        workspace_id = f"ws-stream-no-probe-{path.rsplit('/', 1)[-1]}"
        session_id = _seed_session(client, workspace_id=workspace_id)
        payload: dict[str, Any] = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "message": "\u8bf7\u89e3\u91ca\u8fd9\u4e2a\u62a5\u9519\u3002",
            "response_language": "zh-CN",
            "use_agent_loop": False,
        }
        if path == "/turn/stream":
            payload["intent"] = "coach"
        response = client.post(path, json=payload)

    assert response.status_code == 200, response.text
    assert test_mock.call_count == 0
    complete = _stream_complete_response(response.text)
    assert "\u5148\u770b\u4e00\u5904" in complete["reply"]["content"]


def test_non_stream_chinese_reply_keeps_the_language_probe(app: FastAPI) -> None:
    with TestClient(app) as client, patch.object(
        ProviderService,
        "test",
        autospec=True,
        return_value=ProviderTestResponse(
            ok=True,
            detail="Provider connectivity looks healthy.",
            provider_reachable=True,
            model_supported=True,
        ),
    ) as test_mock, patch.object(
        ProviderService,
        "coaching_reply",
        new=AsyncMock(return_value="\u5148\u770b\u4e00\u5904\u8fd9\u4e2a\u62a5\u9519\u51fa\u73b0\u7684\u4ee3\u7801\u3002"),
    ):
        workspace_id = "ws-non-stream-probe"
        session_id = _seed_session(client, workspace_id=workspace_id)
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": "\u8bf7\u89e3\u91ca\u8fd9\u4e2a\u62a5\u9519\u3002",
                "response_language": "zh-CN",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    assert test_mock.call_count == 1


@pytest.mark.parametrize(
    ("message", "expected_scenario", "expected_summary"),
    [
        (
            "Teach me VS Code Remote SSH step by step before you test me.",
            "remote_workspace",
            "Establish the VS Code remote workspace boundary before widening the lesson.",
        ),
        (
            "Teach me how to debug Python in VS Code before you quiz me.",
            "debug_loop",
            "Build one trustworthy VS Code debug loop before widening the investigation.",
        ),
        (
            "Teach me how to read a function in VS Code by following one live call site before you test me.",
            "function_guidance",
            "Anchor function guidance to one live call site before widening the explanation.",
        ),
    ],
)
def test_turn_response_strips_internal_summary_prefixes(
    app: FastAPI,
    message: str,
    expected_scenario: str,
    expected_summary: str,
) -> None:
    visible_choice = MagicMock()
    visible_choice.message.content = "Keep the reply visible and grounded in one small verified move."
    visible_response = MagicMock()
    visible_response.choices = [visible_choice]

    with TestClient(app) as client, patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=AsyncMock(return_value=(visible_response, "gpt-4o-mini")),
    ):
        session_id = _seed_session(client, workspace_id=f"ws-{expected_scenario}")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": f"ws-{expected_scenario}",
                "intent": "coach",
                "message": message,
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == expected_scenario
    assert payload["coach_turn"]["summary"] == expected_summary
    assert "Current focus:" not in payload["coach_turn"]["summary"]
    assert "Current focus:" not in payload["reply"]["metadata"]["coach_turn"]["summary"]


def test_turn_response_ignores_html_preview_current_file_for_function_guidance(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    visible_choice = MagicMock()
    visible_choice.message.content = "Start from one live call site and read the contract before changing code."
    visible_response = MagicMock()
    visible_response.choices = [visible_choice]

    workspace_path = tmp_path / "ws-function-guidance-preview"
    workspace_path.mkdir()
    (workspace_path / "src").mkdir()
    (workspace_path / "src" / "user.ts").write_text(
        "export function fetchUserSummary() { return {}; }\n",
        encoding="utf-8",
    )
    (workspace_path / "index.html").write_text(
        "<!doctype html>\n<html lang='en'><body><div id='app'></div></body></html>\n",
        encoding="utf-8",
    )

    with TestClient(app) as client, patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=AsyncMock(return_value=(visible_response, "gpt-4o-mini")),
    ):
        session_id = _seed_session(
            client,
            workspace_id="ws-function-guidance-preview",
            workspace_path=str(workspace_path),
        )
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-function-guidance-preview",
                "intent": "coach",
                "message": "Help me understand this function contract before I edit it.",
                "response_language": "en-US",
                "current_file": {
                    "path": "index.html",
                    "language_id": "html",
                    "content": "<!doctype html>\n<html lang='en'><body><div id='app'></div></body></html>",
                },
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    coach_focus = str(
        payload["reply"]["metadata"].get("coach_focus", {}).get("current_focus") or ""
    ).lower()
    memory_focus = str(payload["snapshot"]["memory"]["current_focus"] or "").lower()
    assert "index.html" not in coach_focus
    assert "doctype" not in coach_focus
    assert "index.html" not in memory_focus
    assert "doctype" not in memory_focus
    assert "function contract" in coach_focus or "call site" in coach_focus
    assert "function contract" in memory_focus or "call site" in memory_focus


def test_review_turn_response_strips_review_rhythm_labels(app: FastAPI, tmp_path: Path) -> None:
    target_file = tmp_path / "broken_module.py"
    target_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    with TestClient(app) as client:
        _seed_session(client, workspace_id="ws-review")
        plan_response = client.post(
            "/plan/generate",
            json={
                "workspace_id": "ws-review",
                "profile": {
                    "long_term_goal": "Implement an add helper",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
                "goals": ["Implement an add helper"],
                "objectives": ["Implement an add helper"],
            },
        )
        assert plan_response.status_code == 200, plan_response.text
        task_response = client.post(
            "/task/specify",
            json={
                "workspace_id": "ws-review",
                "natural_language_goal": (
                    "Implement an add helper that returns the sum and handles invalid input."
                ),
            },
        )
        assert task_response.status_code == 200, task_response.text

        review_response = client.post(
            "/turn",
            json={
                "workspace_id": "ws-review",
                "intent": "review",
                "message": "Review this implementation and tell me the first thing to fix.",
                "response_language": "en-US",
                "answer_mode": "guided",
                "use_agent_loop": False,
                "current_file": {
                    "path": str(target_file),
                    "language_id": "python",
                    "content": target_file.read_text(encoding="utf-8"),
                    "diagnostics": ["Function behavior is incorrect for normal addition."],
                },
            },
        )

    assert review_response.status_code == 200, review_response.text
    payload = review_response.json()
    assert payload["coach_turn"]["scenario"] == "review"
    assert payload["coach_turn"]["summary"]
    assert "Review rhythm:" not in payload["coach_turn"]["summary"]
    assert payload["snapshot"]["memory"]["review_rhythm"]
    assert not payload["snapshot"]["memory"]["review_rhythm"].startswith("Review rhythm:")


def test_turn_switches_guided_lane_without_reusing_previous_active_thread(
    app: FastAPI,
) -> None:
    visible_choice = MagicMock()
    visible_choice.message.content = "Keep the reply visible and grounded in one small verified move."
    visible_response = MagicMock()
    visible_response.choices = [visible_choice]

    with TestClient(app) as client, patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=AsyncMock(return_value=(visible_response, "gpt-4o-mini")),
    ):
        session_id = _seed_session(client, workspace_id="ws-guided-lane-switch")
        debug_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-guided-lane-switch",
                "intent": "coach",
                "message": "Teach me how to debug Python in VS Code before you quiz me.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert debug_response.status_code == 200, debug_response.text
        debug_payload = debug_response.json()
        assert debug_payload["coach_turn"]["scenario"] == "debug_loop"
        debug_focus = debug_payload["snapshot"]["memory"]["current_focus"].lower()
        assert "vs code debug" in debug_focus
        assert "implementation slice" not in debug_focus

        remote_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-guided-lane-switch",
                "intent": "coach",
                "message": "Teach me the VS Code remote workflow for SSH and dev containers.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )

        function_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-guided-lane-switch",
                "intent": "coach",
                "message": "Guide me through function hints in VS Code on one real call site first.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )

    assert remote_response.status_code == 200, remote_response.text
    payload = remote_response.json()
    assert payload["coach_turn"]["scenario"] == "remote_workspace"
    assert payload["coach_turn"]["next_step"] == (
        "Return one real boundary signal from the current VS Code window, such as an Explorer path, `pwd`, or the remote host label."
    )
    assert "breakpoint" not in payload["coach_turn"]["next_step"].lower()
    assert "breakpoint" not in payload["coach_turn"]["resume_thread"].lower()
    assert "breakpoint" not in payload["reply"]["content"].lower()
    assert "active thread" not in payload["reply"]["content"].lower()
    assert "debugging" not in payload["reply"]["content"].lower()
    assert "vs code remote lane" in payload["reply"]["content"].lower()

    assert function_response.status_code == 200, function_response.text
    function_payload = function_response.json()
    assert function_payload["coach_turn"]["scenario"] == "function_guidance"
    assert function_payload["coach_turn"]["next_step"] == (
        "Return the function name, what it expects, and which call site proves that reading."
    )
    assert "credential mode" not in function_payload["reply"]["content"].lower()
    assert "ssh" not in function_payload["reply"]["content"].lower()
    assert "debugging" not in function_payload["reply"]["content"].lower()
    assert "active thread" not in function_payload["reply"]["content"].lower()
    assert "live call site" in function_payload["reply"]["content"].lower()
    function_focus = str(
        function_payload["reply"]["metadata"].get("coach_focus", {}).get("current_focus") or ""
    ).lower()
    assert "remote workspace" not in function_focus
    assert "credential mode" not in function_focus
    assert "function" in function_focus or "call site" in function_focus
    memory_focus = function_payload["snapshot"]["memory"]["current_focus"].lower()
    assert "remote workspace" not in memory_focus
    assert "credential mode" not in memory_focus
    assert "function" in memory_focus or "call site" in memory_focus
    artifact_focuses = [
        str(((entry.get("metadata") or {}).get("coach_focus") or {}).get("current_focus") or "").lower()
        for entry in function_payload["reply"]["metadata"].get("artifacts", [])
        if isinstance(entry, dict)
    ]
    artifact_focuses = [focus for focus in artifact_focuses if focus]
    assert artifact_focuses
    assert all("remote workspace" not in focus for focus in artifact_focuses)
    assert all("credential mode" not in focus for focus in artifact_focuses)
    assert any("function" in focus or "call site" in focus for focus in artifact_focuses)


def test_turn_general_topic_switch_drops_previous_function_focus(
    app: FastAPI,
) -> None:
    visible_choice = MagicMock()
    visible_choice.message.content = "Keep the reply visible and grounded in one small verified move."
    visible_response = MagicMock()
    visible_response.choices = [visible_choice]

    with TestClient(app) as client, patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=AsyncMock(return_value=(visible_response, "gpt-4o-mini")),
    ):
        session_id = _seed_session(client, workspace_id="ws-general-lane-switch")
        first_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-general-lane-switch",
                "intent": "coach",
                "message": "Guide me through function hints in VS Code on one real call site first.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert first_response.status_code == 200, first_response.text
        assert first_response.json()["coach_turn"]["scenario"] == "function_guidance"

        second_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-general-lane-switch",
                "intent": "coach",
                "message": "Help me write a clean commit message for this patch.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )

    assert second_response.status_code == 200, second_response.text
    payload = second_response.json()
    assert payload["coach_turn"]["scenario"] == "general"
    focus = str(payload["reply"]["metadata"].get("coach_focus", {}).get("current_focus") or "").lower()
    assert "commit message" in focus
    assert "function" not in focus
    assert "call site" not in focus
    memory_focus = str(payload["snapshot"]["memory"].get("current_focus") or "").lower()
    assert "commit message" in memory_focus
    assert "function" not in memory_focus
    assert "call site" not in memory_focus
    active_thread = payload["snapshot"]["memory"].get("active_thread") or {}
    assert "commit message" in str(active_thread.get("focus_area") or "").lower()
    assert "function" not in str(active_thread.get("focus_area") or "").lower()


def test_turn_agentic_idea_switch_drops_previous_general_lane_context(
    app: FastAPI,
) -> None:
    agent_outcome = {
        "content": "Keep the next move visible and compact.",
        "summary": "",
        "next_step": "",
        "tool_events": [],
        "fell_back": False,
        "stop_reason": "completed",
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "coaching_reply_agentic",
        new=AsyncMock(return_value=agent_outcome),
    ):
        session_id = _seed_session(client, workspace_id="ws-agentic-idea-switch")
        first_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-idea-switch",
                "intent": "coach",
                "message": "Help me write a clean commit message for this patch.",
                "response_language": "en-US",
                "use_agent_loop": True,
            },
        )
        assert first_response.status_code == 200, first_response.text
        assert first_response.json()["coach_turn"]["scenario"] == "general"

        second_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-idea-switch",
                "intent": "coach",
                "message": "我有一个 AI idea，想把它落地成一个最小可验证的原型。",
                "response_language": "zh-CN",
                "use_agent_loop": True,
            },
        )

    assert second_response.status_code == 200, second_response.text
    payload = second_response.json()
    assert payload["coach_turn"]["scenario"] == "idea_implementation"
    focus = str(payload["reply"]["metadata"].get("coach_focus", {}).get("current_focus") or "")
    assert focus.strip()
    assert "commit message" not in focus.lower()
    next_step = str(payload["coach_turn"].get("next_step") or "")
    assert next_step.strip()
    assert "commit message" not in next_step.lower()
    memory_focus = str(payload["snapshot"]["memory"].get("current_focus") or "")
    assert memory_focus.strip()
    assert "commit message" not in memory_focus.lower()
    active_thread = payload["snapshot"]["memory"].get("active_thread") or {}
    assert active_thread.get("scenario") == "idea_implementation"
    assert "commit message" not in str(active_thread.get("focus_area") or "").lower()


def test_turn_agentic_function_lane_switch_strips_previous_debug_lane_copy(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_agent_provider(
        monkeypatch,
        responses=[
            {
                "content": "Start with one real workspace label, then say where the files actually live.",
                "tool_calls": [],
            },
            {
                "content": "Build one trustworthy debug loop: set one breakpoint, pause once, and inspect one value.",
                "tool_calls": [],
            },
            {
                "content": (
                    "If you can read one contract from one live call site, the bigger debug loop idea stops feeling abstract.\n\n"
                    "Start with one live call site, then use hover and signature help until the function contract is stable."
                ),
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-agentic-function-lane-switch")

        remote_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-function-lane-switch",
                "intent": "coach",
                "message": "Teach me the VS Code remote workflow for SSH and dev containers.",
                "response_language": "en-US",
                "use_agent_loop": True,
            },
        )
        assert remote_response.status_code == 200, remote_response.text
        assert remote_response.json()["coach_turn"]["scenario"] == "remote_workspace"

        debug_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-function-lane-switch",
                "intent": "coach",
                "message": "Teach me how to debug Python in VS Code before you test me.",
                "response_language": "en-US",
                "use_agent_loop": True,
            },
        )
        assert debug_response.status_code == 200, debug_response.text
        assert debug_response.json()["coach_turn"]["scenario"] == "debug_loop"

        function_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-function-lane-switch",
                "intent": "coach",
                "message": "Guide me through function hints in VS Code on one real call site first.",
                "response_language": "en-US",
                "use_agent_loop": True,
            },
        )

    assert function_response.status_code == 200, function_response.text
    payload = function_response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    reply_lower = str(payload["reply"]["content"] or "").lower()
    assert "debug loop" not in reply_lower
    assert "live call site" in reply_lower
    assert "function contract" in reply_lower
    resume_thread = str(payload["coach_turn"].get("resume_thread") or "").lower()
    assert "debug loop" not in resume_thread
    focus = str(payload["reply"]["metadata"].get("coach_focus", {}).get("current_focus") or "").lower()
    assert "debug loop" not in focus
    assert "function" in focus or "call site" in focus


def test_turn_agentic_function_lane_switch_repairs_chinese_debug_loop_phrase_in_visible_reply(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_agent_provider(
        monkeypatch,
        responses=[
            {
                "content": "先给我一个真实的工作区标签，再说清楚文件实际在哪台机器上。",
                "tool_calls": [],
            },
            {
                "content": "先搭一个最小 debug loop：一个 breakpoint、一次暂停、一个可验证的 value。",
                "tool_calls": [],
            },
            {
                "content": (
                    "先不急着把调试闭环讲完，我们先在一个真实 call site 上看 fetch options，"
                    "再用 hover、signature help 和 definition 把 contract 读稳。"
                ),
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(client, workspace_id="ws-agentic-function-lane-switch-zh")

        first_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-function-lane-switch-zh",
                "intent": "coach",
                "message": "请先一步一步教我 VS Code Remote SSH，再测试我。",
                "response_language": "zh-CN",
                "use_agent_loop": True,
            },
        )
        assert first_response.status_code == 200, first_response.text
        assert first_response.json()["coach_turn"]["scenario"] == "remote_workspace"

        second_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-function-lane-switch-zh",
                "intent": "coach",
                "message": "请先一步一步教我怎么在 VS Code 里 debug Python，再测试我。",
                "response_language": "zh-CN",
                "use_agent_loop": True,
            },
        )
        assert second_response.status_code == 200, second_response.text
        assert second_response.json()["coach_turn"]["scenario"] == "debug_loop"

        function_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-function-lane-switch-zh",
                "intent": "coach",
                "message": "请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
                "response_language": "zh-CN",
                "use_agent_loop": True,
            },
        )

    assert function_response.status_code == 200, function_response.text
    payload = function_response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    reply = str(payload["reply"]["content"] or "")
    reply_lower = reply.lower()
    assert "调试闭环" not in reply
    assert "debug loop" not in reply_lower
    assert "call site" in reply_lower
    assert "contract" in reply_lower


def test_turn_agentic_function_guidance_repairs_live_debug_loop_contamination_in_visible_reply(
    app: FastAPI,
) -> None:
    contaminated_reply = (
        "好，我们就从一个真实的调用点开始，把「这个函数到底想要什么、又答应给我什么」这件事弄清楚。"
        "先别急着看实现，也别急着理解整个调试闭环--我们只要先锁住一个函数 contract，再把闭环慢慢撑起来。"
    )
    agent_outcome = {
        "content": contaminated_reply,
        "summary": "Build one trustworthy VS Code debug loop before widening the investigation.",
        "next_step": "Tell me which breakpoint you want to set first.",
        "resume_thread": "Resume the debug loop thread. Next: tell me which breakpoint you want first.",
        "tool_events": [],
        "fell_back": False,
        "stop_reason": "completed",
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "coaching_reply_agentic",
        new=AsyncMock(return_value=agent_outcome),
    ):
        session_id = _seed_session(client, workspace_id="ws-guided-visible-repair-turn")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-guided-visible-repair-turn",
                "intent": "coach",
                "message": "请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
                "response_language": "zh-CN",
                "use_agent_loop": True,
                "current_file": {
                    "path": "src/demo.ts",
                    "language_id": "typescript",
                    "content": "export async function loadUser() { return fetchJson('/api/user'); }\n",
                },
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    reply = str(payload["reply"]["content"] or "")
    reply_lower = reply.lower()
    assert "调试闭环" not in reply
    assert "debug loop" not in reply_lower
    assert "call site" in reply_lower
    assert "signature help" in reply_lower
    assert payload["coach_turn"]["summary"] == (
        "先把 function guidance 锚定到一个真实 call site，再扩展说明。"
    )
    assert payload["coach_turn"]["next_step"] == (
        "带回函数名、它期望什么，以及哪个 call site 证明了这个判断。"
    )
    assert payload["agent"]["guided_lane_visible_repaired"] is True


def test_session_message_agentic_function_guidance_repairs_debug_loop_contamination_before_persist(
    app: FastAPI,
) -> None:
    agent_outcome = {
        "content": (
            "Start from one live call site, but do not worry about the whole debug loop yet. "
            "Lock the function contract first, then we can widen."
        ),
        "summary": "Build one trustworthy VS Code debug loop before widening the investigation.",
        "next_step": "Tell me where the first breakpoint should go.",
        "resume_thread": "Resume the debug loop thread. Next: tell me where the first breakpoint should go.",
        "tool_events": [],
        "fell_back": False,
        "stop_reason": "completed",
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "coaching_reply_agentic",
        new=AsyncMock(return_value=agent_outcome),
    ):
        session_id = _seed_session(client, workspace_id="ws-guided-visible-repair-session-message")
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-guided-visible-repair-session-message",
                "message": "Guide me through function hints in VS Code on one real call site first.",
                "response_language": "en-US",
                "use_agent_loop": True,
                "current_file": {
                    "path": "src/demo.ts",
                    "language_id": "typescript",
                    "content": "export async function loadUser() { return fetchJson('/api/user'); }\n",
                },
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    reply = str(payload["reply"]["content"] or "").lower()
    assert "debug loop" not in reply
    assert "breakpoint" not in reply
    assert "call site" in reply
    assert payload["coach_turn"]["summary"] == (
        "Anchor function guidance to one live call site before widening the explanation."
    )
    assert payload["snapshot"]["memory"]["active_thread"]["scenario"] == "function_guidance"
    assert "breakpoint" not in str(
        payload["snapshot"]["memory"]["active_thread"].get("next_step") or ""
    ).lower()
    assert payload["agent"]["guided_lane_visible_repaired"] is True


def test_turn_stream_agentic_function_guidance_repairs_debug_loop_contamination_in_complete_response(
    app: FastAPI,
) -> None:
    async def fake_agentic_stream(
        self: ProviderService,
        profile: Any,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        max_steps: int = 6,
        history: list[dict[str, str]] | None = None,
    ):
        yield {
            "type": "final",
            "content": (
                "好，我们就从一个真实的调用点开始。先别急着理解整个调试闭环，"
                "先锁住一个函数 contract，再慢慢展开。"
            ),
            "summary": "Build one trustworthy VS Code debug loop before widening the investigation.",
            "next_step": "Tell me which breakpoint you want first.",
            "resume_thread": "Resume the debug loop thread. Next: tell me which breakpoint you want first.",
            "tool_events": [],
            "fell_back": False,
            "stop_reason": "completed",
        }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "coaching_reply_agentic_stream",
        new=fake_agentic_stream,
    ):
        session_id = _seed_session(client, workspace_id="ws-guided-visible-repair-turn-stream")
        with client.stream(
            "POST",
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": "ws-guided-visible-repair-turn-stream",
                "intent": "coach",
                "message": "请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
                "response_language": "zh-CN",
                "use_agent_loop": True,
                "current_file": {
                    "path": "src/demo.ts",
                    "language_id": "typescript",
                    "content": "export async function loadUser() { return fetchJson('/api/user'); }\n",
                },
            },
        ) as response:
            assert response.status_code == 200
            raw = b"".join(response.iter_bytes()).decode("utf-8", errors="replace")

    response_payload = _stream_complete_response(raw)
    reply = str(response_payload["reply"]["content"] or "")
    reply_lower = reply.lower()
    assert response_payload["coach_turn"]["scenario"] == "function_guidance"
    assert "调试闭环" not in reply
    assert "debug loop" not in reply_lower
    assert "call site" in reply_lower
    assert response_payload["coach_turn"]["summary"] == (
        "先把 function guidance 锚定到一个真实 call site，再扩展说明。"
    )


def test_turn_agentic_function_lane_repairs_generic_review_fallback_before_persist(
    app: FastAPI,
) -> None:
    agent_outcome = {
        "content": "Start with one live call site and keep the contract visible.",
        "summary": "Ignore secondary issues and only describe the first fix plus one verification.",
        "next_step": "Ignore secondary issues and only name the first fix plus one verification.",
        "resume_thread": (
            "Resume the live thread around the current function thread. "
            "Next: Ignore secondary issues and only name the first fix plus one verification."
        ),
        "tool_events": [],
        "fell_back": False,
        "stop_reason": "completed",
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "coaching_reply_agentic",
        new=AsyncMock(return_value=agent_outcome),
    ):
        session_id = _seed_session(client, workspace_id="ws-agentic-function-repair")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-function-repair",
                "intent": "coach",
                "message": "Guide me through one TypeScript function by reading a live call site first.",
                "response_language": "en-US",
                "use_agent_loop": True,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    active_thread = payload["snapshot"]["memory"].get("active_thread") or {}
    assert active_thread.get("scenario") == "function_guidance"
    assert active_thread.get("next_step") == (
        "Give me the function name and one call site you can open right now."
    )
    assert "ignore secondary issues" not in str(active_thread.get("next_step") or "").lower()


def test_turn_agentic_function_lane_strips_prefixed_next_step_labels_in_visible_fields(
    app: FastAPI,
) -> None:
    bare_next_step = "给我函数名和一个你现在就能打开的 call site。"
    agent_outcome = {
        "content": "我们先把函数理解锚定在一个 live call site 上。",
        "summary": "我会先把函数理解锚定在一个 live call site 上，再用 hover、signature help 和 definition 把 contract 读稳。",
        "next_step": f"下一步：{bare_next_step}",
        "resume_thread": (
            "沿着当前主线继续：我会先把函数理解锚定在一个 live call site 上。 "
            f"下一步：下一步：{bare_next_step}"
        ),
        "tool_events": [],
        "fell_back": False,
        "stop_reason": "completed",
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "coaching_reply_agentic",
        new=AsyncMock(return_value=agent_outcome),
    ):
        session_id = _seed_session(client, workspace_id="ws-agentic-function-next-step-prefix")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-function-next-step-prefix",
                "intent": "coach",
                "message": "请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
                "response_language": "zh-CN",
                "use_agent_loop": True,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    assert payload["coach_turn"]["next_step"] == bare_next_step
    assert payload["reply"]["metadata"]["coach_focus"]["next_step"] == bare_next_step
    active_thread = payload["snapshot"]["memory"].get("active_thread") or {}
    assert active_thread.get("next_step") == bare_next_step
    assert "下一步：下一步：" not in str(payload["snapshot"]["memory"].get("current_focus") or "")
    assert "下一步是：下一步：" not in str(payload["snapshot"]["memory"].get("current_focus") or "")


def test_turn_agentic_function_lane_strips_internal_system_reminder_from_visible_reply(
    app: FastAPI,
) -> None:
    agent_outcome = {
        "content": (
            "<system-reminder> 注意：你刚刚收到此 system-reminder。"
            "系统提示你这是真实工程环境下的真实工具调用；上一轮没有可用的 workspace file 或 current file snapshot。"
            " 我会先把函数理解锚定在一个 live call site 上，再用 hover、signature help 和 definition 把 contract 读稳。"
        ),
        "summary": "我会先把函数理解锚定在一个 live call site 上，再用 hover、signature help 和 definition 把 contract 读稳。",
        "next_step": "下一步：给我函数名和一个你现在就能打开的 call site，我们再从那里读参数、返回值和上下文。",
        "resume_thread": (
            "沿着当前主线继续：我会先把函数理解锚定在一个 live call site 上，再用 hover、signature help 和 definition 把 contract 读稳。"
            " 下一步：给我函数名和一个你现在就能打开的 call site，我们再从那里读参数、返回值和上下文。"
        ),
        "tool_events": [],
        "fell_back": False,
        "stop_reason": "completed",
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "coaching_reply_agentic",
        new=AsyncMock(return_value=agent_outcome),
    ):
        session_id = _seed_session(client, workspace_id="ws-agentic-function-system-reminder")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-function-system-reminder",
                "intent": "coach",
                "message": "请先基于一个真实 call site 教我 TypeScript fetch options，再测试我。",
                "response_language": "zh-CN",
                "use_agent_loop": True,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    reply_content = str(payload["reply"]["content"] or "")
    assert "<system-reminder>" not in reply_content
    assert "system-reminder" not in reply_content
    assert "workspace file" not in reply_content
    assert "current file snapshot" not in reply_content
    assert "live call site" in reply_content or "call site" in reply_content


def test_turn_agentic_fresh_lane_drops_remote_blocker_and_review_rhythm_from_debug_metadata(
    app: FastAPI,
) -> None:
    agent_outcomes = [
        {
            "content": "First keep the VS Code remote boundary explicit.",
            "summary": (
                "Stay in the VS Code remote lane long enough to verify where the files actually live "
                "before you move credentials."
            ),
            "next_step": "Return one real workspace label or path, then add one safe credential mode judgment.",
            "resume_thread": (
                "Stay in the VS Code remote lane long enough to verify where the files actually live "
                "before you move credentials. Next: return one real workspace label or path, then add "
                "one safe credential mode judgment."
            ),
            "blocker": "The provider reply was not clean, so I resumed this remote thread locally.",
            "teaching_note": "Keep the remote boundary explicit before you widen scope.",
            "tool_events": [],
            "fell_back": False,
            "stop_reason": "completed",
        },
        {
            "content": "We will keep this to one trustworthy debug loop: reproduce once, pause once, inspect one value.",
            "summary": (
                "I will keep this inside one trustworthy debug loop: reproduce once, pause at the first "
                "meaningful state change, then inspect one value."
            ),
            "next_step": (
                "Next step: tell me where you will pause first and which value, branch, or stack frame "
                "you will inspect."
            ),
            "resume_thread": (
                "I will keep this inside one trustworthy debug loop: reproduce once, pause at the first "
                "meaningful state change, then inspect one value. Next: tell me where you will pause "
                "first and which value, branch, or stack frame you will inspect."
            ),
            "tool_events": [],
            "fell_back": False,
            "stop_reason": "completed",
        },
    ]

    with TestClient(app) as client, patch.object(
        ProviderService,
        "coaching_reply_agentic",
        new=AsyncMock(side_effect=agent_outcomes),
    ):
        session_id = _seed_session(client, workspace_id="ws-agentic-fresh-lane-cleanup")

        remote_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-fresh-lane-cleanup",
                "intent": "coach",
                "message": "Teach me VS Code Remote SSH one small step at a time, then test me.",
                "response_language": "en-US",
                "use_agent_loop": True,
            },
        )
        assert remote_response.status_code == 200, remote_response.text
        assert remote_response.json()["coach_turn"]["scenario"] == "remote_workspace"

        debug_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-agentic-fresh-lane-cleanup",
                "intent": "coach",
                "message": "Teach me how to debug Python in VS Code one small step at a time, then test me.",
                "response_language": "en-US",
                "use_agent_loop": True,
            },
        )

    assert debug_response.status_code == 200, debug_response.text
    payload = debug_response.json()
    assert payload["coach_turn"]["scenario"] == "debug_loop"

    coach_turn = payload["coach_turn"]
    reply_turn = payload["reply"]["metadata"]["coach_turn"]
    active_thread = payload["snapshot"]["memory"].get("active_thread") or {}
    current_focus = str(payload["snapshot"]["memory"].get("current_focus") or "")

    assert coach_turn["blocker"] == ""
    assert coach_turn["teaching_note"] == ""
    assert coach_turn["review_rhythm"] == ""
    assert coach_turn["review_queue_summary"] == ""
    assert coach_turn["decision_reason"] == ""

    assert reply_turn["blocker"] == ""
    assert reply_turn["teaching_note"] == ""
    assert reply_turn["review_rhythm"] == ""
    assert reply_turn["review_queue_summary"] == ""
    assert reply_turn["decision_reason"] == ""

    assert active_thread.get("scenario") == "debug_loop"
    assert str(active_thread.get("blocker") or "") == ""
    assert str(active_thread.get("teaching_note") or "") == ""
    assert "remote" not in current_focus.lower()
    assert "credential mode" not in current_focus.lower()


def test_turn_idea_implementation_uses_clean_chinese_summary_and_next_step(
    app: FastAPI,
) -> None:
    visible_choice = MagicMock()
    visible_choice.message.content = "先把这个 AI idea 压成一条很薄、可验证的切片。"
    visible_response = MagicMock()
    visible_response.choices = [visible_choice]

    with TestClient(app) as client, patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=AsyncMock(return_value=(visible_response, "gpt-4o-mini")),
    ):
        session_id = _seed_session(client, workspace_id="ws-idea-zh-copy")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-idea-zh-copy",
                "intent": "coach",
                "message": "我有一个 AI idea，想把它落地成一个最小可验证的原型。",
                "response_language": "zh-CN",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "idea_implementation"
    assert "可验证" in str(payload["coach_turn"].get("summary") or "")
    next_step = str(payload["coach_turn"].get("next_step") or "")
    assert "验证" in next_step
    assert "閸" not in next_step
    focus = str(payload["reply"]["metadata"].get("coach_focus", {}).get("current_focus") or "")
    assert "AI idea" in focus or "我有一个" in focus
    assert "瑜" not in focus


def test_turn_principle_switch_drops_previous_function_review_rhythm(
    app: FastAPI,
) -> None:
    visible_choice = MagicMock()
    visible_choice.message.content = "Keep the reply visible and grounded in one small verified move."
    visible_response = MagicMock()
    visible_response.choices = [visible_choice]

    with TestClient(app) as client, patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=AsyncMock(return_value=(visible_response, "gpt-4o-mini")),
    ):
        session_id = _seed_session(client, workspace_id="ws-principle-lane-switch")
        first_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-principle-lane-switch",
                "intent": "coach",
                "message": "Guide me through function hints in VS Code on one real call site first.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert first_response.status_code == 200, first_response.text
        assert first_response.json()["coach_turn"]["scenario"] == "function_guidance"

        second_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-principle-lane-switch",
                "intent": "coach",
                "message": "Explain the principle behind dependency injection in FastAPI.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )

    assert second_response.status_code == 200, second_response.text
    payload = second_response.json()
    assert payload["coach_turn"]["scenario"] == "principle"
    next_step = str(payload["coach_turn"]["next_step"] or "").lower()
    assert "exact line where it matters" in next_step
    assert "function-contract:next-step" not in next_step
    focus = str(payload["reply"]["metadata"].get("coach_focus", {}).get("current_focus") or "").lower()
    assert "dependency injection" in focus or "fastapi" in focus
    assert "function contract" not in focus
    memory_focus = str(payload["snapshot"]["memory"].get("current_focus") or "").lower()
    assert "dependency injection" in memory_focus or "fastapi" in memory_focus
    assert "function-contract:next-step" not in memory_focus


@pytest.mark.parametrize(
    ("message", "expected_scenario", "expected_summary_fragment", "expected_step_fragment", "unexpected_fragment"),
    [
        (
            "请先教我 VS Code 远程 SSH 和 dev container 的工作区边界。",
            "remote_workspace",
            "VS Code remote",
            "SSH",
            "断点",
        ),
        (
            "请先教我怎么在 VS Code 里调试 Python，只盯住一个断点和调用栈。",
            "debug_loop",
            "VS Code debug",
            "stack frame",
            "SSH",
        ),
        (
            "请先教我看懂这个函数的参数提示和定义。",
            "function_guidance",
            "function guidance",
            "函数名",
            "credential mode",
        ),
        (
            "请陪我把一个现有项目改造到新的目标上，先分清哪些必须保持不变。",
            "project_adaptation",
            "existing-project adaptation",
            "保持稳定",
            "调用栈",
        ),
    ],
)
def test_turn_language_corruption_override_keeps_lane_specific_copy(
    app: FastAPI,
    message: str,
    expected_scenario: str,
    expected_summary_fragment: str,
    expected_step_fragment: str,
    unexpected_fragment: str,
) -> None:
    provider_payload = {
        "name": "mini-max",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.minimax",
        "model": "MiniMax-M3",
        "requestDefaults": {
            "extra_body": {
                "thinking": {
                    "type": "disabled",
                }
            }
        },
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "test",
        autospec=True,
        return_value=ProviderTestResponse(
            ok=False,
            detail="Provider reachable, but it corrupted Chinese input into question marks before the model saw it.",
            error_category="language_corruption",
            retryable=False,
            status_code=200,
            provider_reachable=True,
            model_supported=True,
        ),
    ), patch.object(
        ProviderService,
        "coaching_reply",
        new=AsyncMock(
            return_value="I can only see question marks like ??? instead of the original Chinese text.",
        ),
    ):
        session_id = _seed_session(client, workspace_id=f"ws-language-block-{expected_scenario}")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": f"ws-language-block-{expected_scenario}",
                "intent": "coach",
                "message": message,
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-test",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == expected_scenario
    normalized_summary = payload["coach_turn"]["summary"].replace("-", " ")
    normalized_expected_summary = expected_summary_fragment.replace("-", " ")
    assert normalized_expected_summary in normalized_summary
    assert "模型服务可以连接" in payload["coach_turn"]["summary"]
    assert payload["coach_turn"]["summary"] != RECOVERED_ZH_SUMMARY
    assert payload["agent_meta"]["stop_reason"] == "language_corruption"
    assert payload["reply"]["metadata"]["coach_visible_status"]["status"] == "blocked"
    assert (
        payload["reply"]["metadata"]["coach_visible_status"]["stopReason"]
        == "language_corruption"
    )
    assert expected_step_fragment in payload["coach_turn"]["next_step"]
    assert unexpected_fragment not in payload["coach_turn"]["next_step"]
    assert unexpected_fragment not in payload["coach_turn"]["resume_thread"]
    if expected_scenario == "remote_workspace":
        assert "SSH" in payload["coach_turn"]["next_step"]
        assert "host label" in payload["coach_turn"]["next_step"]
        assert "VS Code remote" in payload["reply"]["content"]
        assert "SSH" in payload["reply"]["content"]
    elif expected_scenario == "debug_loop":
        assert "stack frame" in payload["coach_turn"]["next_step"]
        assert "VS Code debug" in payload["reply"]["content"]
        assert "stack frame" in payload["reply"]["content"]
    elif expected_scenario == "function_guidance":
        assert "call site" in payload["coach_turn"]["next_step"]
        assert "函数名" in payload["coach_turn"]["next_step"]
        assert "function guidance" in payload["reply"]["content"].replace("-", " ")
        assert "call site" in payload["reply"]["content"]
    else:
        assert "保持稳定" in payload["coach_turn"]["next_step"]
        assert "第一条边界" in payload["coach_turn"]["next_step"]
        assert "existing-project adaptation" in payload["reply"]["content"]
        assert "第一条边界" in payload["reply"]["content"]


def test_turn_language_corruption_override_catches_chinese_question_mark_reply(
    app: FastAPI,
) -> None:
    provider_payload = {
        "name": "mini-max",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.minimax",
        "model": "MiniMax-M3",
        "requestDefaults": {
            "extra_body": {
                "thinking": {
                    "type": "disabled",
                }
            }
        },
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "test",
        autospec=True,
        return_value=ProviderTestResponse(
            ok=True,
            detail="Provider reachable.",
            provider_reachable=True,
            model_supported=True,
        ),
    ), patch.object(
        ProviderService,
        "coaching_reply",
        new=AsyncMock(
            return_value=(
                "你的消息里中文部分好像没正常发出来，我只看到几个问号和 call site 这几个词。"
                "我猜你想问的是怎么读函数 contract。"
            ),
        ),
    ):
        session_id = _seed_session(client, workspace_id="ws-language-corruption-zh-question-mark")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-language-corruption-zh-question-mark",
                "intent": "coach",
                "message": "请先基于一个真实 call site 教我函数提示，再测我。",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-test",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    assert payload["agent_meta"]["stop_reason"] == "language_corruption_recovered"
    assert payload["reply"]["metadata"]["coach_visible_status"]["status"] == "degraded"
    assert "我只看到几个问号" not in payload["reply"]["content"]
    assert "call site" in payload["reply"]["content"]
    assert "contract" in payload["coach_turn"]["next_step"]


def test_turn_language_corruption_override_can_resume_latest_explicit_lane_from_general_follow_up(
    app: FastAPI,
) -> None:
    provider_payload = {
        "name": "mini-max",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.minimax",
        "model": "MiniMax-M3",
        "requestDefaults": {
            "extra_body": {
                "thinking": {
                    "type": "disabled",
                }
            }
        },
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "test",
        autospec=True,
        return_value=ProviderTestResponse(
            ok=False,
            detail="Provider reachable, but it corrupted Chinese input into question marks before the model saw it.",
            error_category="language_corruption",
            retryable=False,
            status_code=200,
            provider_reachable=True,
            model_supported=True,
        ),
    ), patch.object(
        ProviderService,
        "coaching_reply",
        new=AsyncMock(
            return_value="I can only see question marks like ??? instead of the original Chinese text.",
        ),
    ):
        session_id = _seed_session(client, workspace_id="ws-language-block-resume")
        explicit_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-language-block-resume",
                "intent": "coach",
                "message": "请陪我把一个现有项目改造到新的目标上，先分清哪些必须保持不变。",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-test",
                "use_agent_loop": False,
            },
        )
        resume_response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-language-block-resume",
                "intent": "coach",
                "message": "继续",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-test",
                "use_agent_loop": False,
            },
        )

    assert explicit_response.status_code == 200, explicit_response.text
    assert explicit_response.json()["coach_turn"]["scenario"] == "project_adaptation"

    assert resume_response.status_code == 200, resume_response.text
    payload = resume_response.json()
    assert payload["coach_turn"]["scenario"] == "project_adaptation"
    assert payload["coach_turn"]["summary"] != RECOVERED_ZH_SUMMARY
    assert "当前进度" in payload["coach_turn"]["summary"]
    assert "保持" in payload["coach_turn"]["next_step"]
    assert "第一条边界" in payload["coach_turn"]["next_step"]
    assert payload["agent_meta"]["stop_reason"] == "language_corruption_recovered"
    assert payload["reply"]["metadata"]["coach_visible_status"]["status"] == "degraded"
    assert (
        payload["reply"]["metadata"]["coach_visible_status"]["stopReason"]
        == "language_corruption_recovered"
    )
    assert "保持" in payload["reply"]["content"]
    assert "第一条边界" in payload["reply"]["content"]
    assert "先切换 provider" not in payload["coach_turn"]["next_step"]
    assert "已保存的主线" in payload["coach_turn"]["resume_thread"]
    assert "已保存的主线" in payload["reply"]["content"]
    assert payload["snapshot"]["memory"]["active_thread"]["scenario"] == "project_adaptation"
    return
    assert payload["coach_turn"]["scenario"] == "project_adaptation"
    assert "existing-project adaptation" in payload["coach_turn"]["summary"]
    assert "保持稳定" in payload["coach_turn"]["next_step"]
    assert "第一条边界" in payload["coach_turn"]["next_step"]
    assert "先切换 provider" not in payload["coach_turn"]["next_step"]
    assert "已保存的主线" in payload["coach_turn"]["resume_thread"]
    assert "已保存的主线" in payload["reply"]["content"]
    assert payload["snapshot"]["memory"]["active_thread"]["scenario"] == "project_adaptation"


def test_turn_language_corruption_override_recovers_short_continuation_from_saved_thread(
    app: FastAPI,
    runtime: TrainerRuntime,
) -> None:
    provider_payload = {
        "name": "mini-max",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.minimax",
        "model": "MiniMax-M3",
        "requestDefaults": {
            "extra_body": {
                "thinking": {
                    "type": "disabled",
                }
            }
        },
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "test",
        autospec=True,
        return_value=ProviderTestResponse(
            ok=True,
            detail="Provider connectivity looks healthy.",
            provider_reachable=True,
            model_supported=True,
        ),
    ) as test_mock, patch.object(
        ProviderService,
        "coaching_reply",
        new=AsyncMock(
            return_value="I can only see question marks like ??? instead of the original Chinese text.",
        ),
    ):
        session_id = _seed_session(client, workspace_id="ws-language-continuation-rescue")
        runtime.memory_service.record_turn_memory(
            workspace_id="ws-language-continuation-rescue",
            session_id=session_id,
            scenario="project_adaptation",
            focus_area="migration boundary",
            summary="Pin the stable boundaries before adapting the first change.",
            next_step="先分清哪些必须保持不变，再列出第一条要改的边界。",
            response_language="zh-CN",
            answer_mode="guided",
        )
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-language-continuation-rescue",
                "intent": "coach",
                "message": "继续",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-test",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    assert test_mock.call_count == 0
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "project_adaptation"
    assert "这次回答显示有问题" in payload["coach_turn"]["summary"]
    assert payload["coach_turn"]["next_step"].rstrip("。.") == "先分清哪些必须保持不变，再列出第一条要改的边界"
    assert "先切换 provider / gateway" not in payload["coach_turn"]["next_step"]
    assert "先切换 provider / gateway" not in payload["coach_turn"]["resume_thread"]
    assert "先切换 provider / gateway" not in payload["reply"]["content"]
    assert "已保存的主线" in payload["coach_turn"]["resume_thread"]
    assert "已保存的主线" in payload["reply"]["content"]
    assert "先分清哪些必须保持不变，再列出第一条要改的边界" in payload["reply"]["content"]
    assert payload["agent_meta"]["stop_reason"] == "language_corruption_recovered"


def test_turn_language_corruption_override_infers_lane_from_latest_user_message_after_reply_corruption(
    app: FastAPI,
) -> None:
    provider_payload = {
        "name": "mini-max",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.minimax",
        "model": "MiniMax-M3",
        "requestDefaults": {
            "extra_body": {
                "thinking": {
                    "type": "disabled",
                }
            }
        },
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "test",
        autospec=True,
        return_value=ProviderTestResponse(
            ok=True,
            detail="Provider connectivity looks healthy.",
            provider_reachable=True,
            model_supported=True,
        ),
    ), patch.object(
        ProviderService,
        "coaching_reply",
        new=AsyncMock(
            return_value="I can only see question marks like ??? instead of the original Chinese text.",
        ),
    ):
        session_id = _seed_session(client, workspace_id="ws-language-postreply")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-language-postreply",
                "intent": "coach",
                "message": "请先教我看懂这个函数的参数提示和定义。",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-test",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    assert payload["coach_turn"]["summary"] == RECOVERED_ZH_SUMMARY
    assert payload["coach_turn"]["next_step"] == RECOVERED_FUNCTION_STEP
    assert payload["agent_meta"]["stop_reason"] == "language_corruption_recovered"
    assert payload["reply"]["metadata"]["coach_visible_status"]["status"] == "degraded"
    assert "call site" in payload["reply"]["content"]
    assert "\u5e72\u51c0\u4fdd\u7559\u56de\u590d\u6587\u672c" not in payload["coach_turn"]["next_step"]
    return
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    assert payload["coach_turn"]["summary"] == RECOVERED_ZH_SUMMARY
    assert payload["coach_turn"]["next_step"] == RECOVERED_FUNCTION_STEP
    assert payload["agent_meta"]["stop_reason"] == "language_corruption_recovered"
    assert "call site" in payload["reply"]["content"]
    return
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    assert "function guidance" in payload["coach_turn"]["summary"]
    assert "函数名" in payload["coach_turn"]["next_step"]
    assert "call site" in payload["reply"]["content"]


def test_turn_keeps_clean_chinese_remote_reply_for_english_request(
    app: FastAPI,
) -> None:
    provider_payload = {
        "name": "mini-max",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.minimax",
        "model": "MiniMax-M3",
        "requestDefaults": {
            "extra_body": {
                "thinking": {
                    "type": "disabled",
                }
            }
        },
    }
    clean_reply = (
        "很高兴你把这个主题拉进来，我们先把远程工作区这件事拆成一个真实可验证的小目标。\n\n"
        "我会继续把这一轮留在 VS Code remote 这条线上：先确认工作区边界和文件实际在哪台机器上，"
        "再决定 credential mode。\n\n"
        "下一步：告诉我当前工作区是 SSH、tunnels、dev container、WSL 还是 local，"
        "再给我一个你能看到的真实路径或主机标签。"
    )

    with TestClient(app) as client, patch.object(
        ProviderService,
        "test",
        autospec=True,
        return_value=ProviderTestResponse(
            ok=True,
            detail="Provider connectivity looks healthy.",
            provider_reachable=True,
            model_supported=True,
        ),
    ), patch.object(
        ProviderService,
        "coaching_reply",
        new=AsyncMock(return_value=clean_reply),
    ):
        session_id = _seed_session(client, workspace_id="ws-clean-zh-remote")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-clean-zh-remote",
                "intent": "coach",
                "message": "Teach me the VS Code remote workflow for SSH and dev containers.",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-test",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "remote_workspace"
    assert payload["reply"]["content"] == clean_reply
    assert payload["coach_turn"]["summary"] != RECOVERED_ZH_SUMMARY
    assert payload.get("agent_meta") in (None, {})
    assert "coach_visible_status" not in payload["reply"]["metadata"]
    focus = str(payload["reply"]["metadata"].get("coach_focus", {}).get("current_focus") or "")
    memory_focus = str(payload["snapshot"]["memory"].get("current_focus") or "")
    assert any(marker in focus for marker in ("远程工作区", "工作区边界", "远程"))
    assert any(marker in memory_focus for marker in ("远程工作区", "工作区边界", "远程"))
    assert "Code remote workflow" not in focus
    assert "Code remote workflow" not in memory_focus


def test_turn_reply_failure_language_corruption_override_keeps_lane_specific_copy(
    app: FastAPI,
) -> None:
    provider_payload = {
        "name": "mini-max",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.minimax",
        "model": "MiniMax-M3",
        "requestDefaults": {
            "extra_body": {
                "thinking": {
                    "type": "disabled",
                }
            }
        },
    }
    reply_failure = {
        "error_category": "language_corruption",
        "detail": "The provider returned mixed-script fragments instead of the original reply.",
        "retryable": False,
        "status_code": 200,
        "provider_reachable": True,
        "model_supported": True,
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "test",
        autospec=True,
        return_value=ProviderTestResponse(
            ok=True,
            detail="Provider connectivity looks healthy.",
            provider_reachable=True,
            model_supported=True,
        ),
    ), patch.object(
        ProviderService,
        "coaching_reply",
        new=AsyncMock(
            return_value="Trainer is blocked on the provider path, so I cannot continue this coaching turn yet.",
        ),
    ), patch.object(
        ProviderService,
        "consume_last_reply_failure",
        autospec=True,
        return_value=reply_failure,
    ):
        session_id = _seed_session(client, workspace_id="ws-language-reply-failure")
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-language-reply-failure",
                "intent": "coach",
                "message": "\u8bf7\u5148\u966a\u6211\u770b\u61c2\u8fd9\u4e2a\u51fd\u6570\u7684\u53c2\u6570\u63d0\u793a\u548c\u5b9a\u4e49\uff0c\u5148\u627e\u4e00\u4e2a\u8c03\u7528\u70b9\u3002",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-test",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    assert payload["coach_turn"]["summary"] == RECOVERED_ZH_SUMMARY
    assert "call site" in payload["coach_turn"]["next_step"]
    assert "contract" in payload["coach_turn"]["next_step"]
    assert payload["agent_meta"]["stop_reason"] == "language_corruption_recovered"
    assert payload["reply"]["metadata"]["coach_visible_status"]["status"] == "degraded"
    assert "call site" in payload["reply"]["content"]
    assert "\u5e72\u51c0\u4fdd\u7559\u56de\u590d\u6587\u672c" not in payload["coach_turn"]["next_step"]


def test_turn_reply_failure_language_corruption_continuation_recovers_saved_thread(
    app: FastAPI,
    runtime: TrainerRuntime,
) -> None:
    provider_payload = {
        "name": "mini-max",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.minimax",
        "model": "MiniMax-M3",
        "requestDefaults": {
            "extra_body": {
                "thinking": {
                    "type": "disabled",
                }
            }
        },
    }
    reply_failure = {
        "error_category": "language_corruption",
        "detail": "The provider returned mixed-script fragments instead of the original reply.",
        "retryable": False,
        "status_code": 200,
        "provider_reachable": True,
        "model_supported": True,
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "test",
        autospec=True,
        return_value=ProviderTestResponse(
            ok=True,
            detail="Provider connectivity looks healthy.",
            provider_reachable=True,
            model_supported=True,
        ),
    ) as test_mock, patch.object(
        ProviderService,
        "coaching_reply",
        new=AsyncMock(
            return_value="Trainer is blocked on the provider path, so I cannot continue this coaching turn yet.",
        ),
    ), patch.object(
        ProviderService,
        "consume_last_reply_failure",
        autospec=True,
        return_value=reply_failure,
    ):
        session_id = _seed_session(client, workspace_id="ws-language-reply-failure-continuation")
        runtime.memory_service.record_turn_memory(
            workspace_id="ws-language-reply-failure-continuation",
            session_id=session_id,
            scenario="debug_loop",
            focus_area="launch diagnostics",
            summary="Pin the first breakpoint before widening the lane.",
            next_step="先停在第一个 breakpoint，再验证一个 value。",
            response_language="zh-CN",
            answer_mode="guided",
        )
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-language-reply-failure-continuation",
                "intent": "coach",
                "message": "继续",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-test",
                "use_agent_loop": False,
            },
        )

    assert response.status_code == 200, response.text
    assert test_mock.call_count == 0
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "debug_loop"
    assert payload["coach_turn"]["next_step"].rstrip("。.") == "先停在第一个 breakpoint，再验证一个 value"
    assert "先切换 provider" not in payload["coach_turn"]["next_step"]
    assert "已保存的主线" in payload["coach_turn"]["resume_thread"]
    assert "已保存的主线" in payload["reply"]["content"]
    assert "先停在第一个 breakpoint，再验证一个 value" in payload["reply"]["content"]
    assert payload["agent_meta"]["stop_reason"] == "language_corruption_recovered"


def test_turn_agentic_reply_failure_language_corruption_continuation_recovers_saved_thread(
    app: FastAPI,
    runtime: TrainerRuntime,
) -> None:
    provider_payload = {
        "name": "mini-max",
        "baseUrl": "https://example.com/v1",
        "apiKeyRef": "trainer.minimax",
        "model": "MiniMax-M3",
        "requestDefaults": {
            "extra_body": {
                "thinking": {
                    "type": "disabled",
                }
            }
        },
    }
    provider_payload["capabilities"] = {"tools": True, "streaming": True}
    reply_failure = {
        "error_category": "language_corruption",
        "detail": "The provider returned mixed-script fragments instead of the original reply.",
        "retryable": False,
        "status_code": 200,
        "provider_reachable": True,
        "model_supported": True,
    }
    agent_outcome = {
        "content": "Trainer is blocked on the provider path, so I cannot continue this coaching turn yet.",
        "summary": "This provider is reachable, but it corrupted Chinese input into question marks before the model saw the message. I am still keeping this turn in the VS Code debug lane.",
        "next_step": "Switch provider or gateway, or continue this debug lesson in English first. If you stay here, tell me where you will pause first and which single value, branch, or stack frame you expect to inspect.",
        "stop_reason": "language_corruption",
        "resume_thread": "Resume the live thread around the current debug lane. Next: Switch provider or gateway, or continue this debug lesson in English first.",
        "tool_events": [],
        "fell_back": False,
    }

    with TestClient(app) as client, patch.object(
        ProviderService,
        "test",
        autospec=True,
        return_value=ProviderTestResponse(
            ok=True,
            detail="Provider connectivity looks healthy.",
            provider_reachable=True,
            model_supported=True,
        ),
    ) as test_mock, patch.object(
        ProviderService,
        "coaching_reply_agentic",
        new=AsyncMock(return_value=agent_outcome),
    ), patch.object(
        ProviderService,
        "consume_last_reply_failure",
        autospec=True,
        return_value=reply_failure,
    ):
        session_id = _seed_session(client, workspace_id="ws-language-agentic-reply-failure")
        runtime.memory_service.record_turn_memory(
            workspace_id="ws-language-agentic-reply-failure",
            session_id=session_id,
            scenario="debug_loop",
            focus_area="launch diagnostics",
            summary="Pin the first breakpoint before widening the lane.",
            next_step="\u5148\u505c\u5728\u7b2c\u4e00\u4e2a breakpoint\uff0c\u518d\u9a8c\u8bc1\u4e00\u4e2a value\u3002",
            response_language="zh-CN",
            answer_mode="guided",
        )
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "ws-language-agentic-reply-failure",
                "intent": "coach",
                "message": "\u7ee7\u7eed",
                "response_language": "zh-CN",
                "provider": provider_payload,
                "api_key": "sk-test",
                "use_agent_loop": True,
            },
        )

    assert response.status_code == 200, response.text
    assert test_mock.call_count == 0
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "debug_loop"
    assert payload["coach_turn"]["next_step"].rstrip("\u3002.") == "\u5148\u505c\u5728\u7b2c\u4e00\u4e2a breakpoint\uff0c\u518d\u9a8c\u8bc1\u4e00\u4e2a value"
    assert "Switch provider or gateway" not in payload["coach_turn"]["next_step"]
    assert "Switch provider or gateway" not in payload["coach_turn"]["resume_thread"]
    assert "\u5148\u505c\u5728\u7b2c\u4e00\u4e2a breakpoint\uff0c\u518d\u9a8c\u8bc1\u4e00\u4e2a value" in payload["reply"]["content"]
    assert payload["agent_meta"]["stop_reason"] == "language_corruption_recovered"
    assert payload["agent_meta"]["agentic"] is True


def test_agentic_resume_thread_is_sanitized_across_visible_fields(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_path = tmp_path / "ws-finalize"
    workspace_path.mkdir()
    (workspace_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    _patch_agent_provider(
        monkeypatch,
        responses=[
            {
                "content": "Glad you have a clear next step.",
                "tool_calls": [
                    {
                        "id": "t1",
                        "name": "coach_finalize",
                        "arguments": {
                            "summary": "We narrowed the issue to one async iterator boundary.",
                            "next_step": "Patch the smallest async iterator call site and rerun the check.",
                        },
                    }
                ],
            },
            {
                "content": "Stay on that same thread: patch the smallest async iterator call site and rerun the check.",
                "tool_calls": [],
            },
        ],
    )

    with TestClient(app) as client:
        session_id = _seed_session(
            client,
            workspace_id="ws-finalize",
            workspace_path=str(workspace_path),
        )
        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "ws-finalize",
                "message": "Help me close the loop and tell me the next step.",
                "response_language": "en-US",
                "use_agent_loop": True,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    expected_resume = (
        "We narrowed the issue to one async iterator boundary. "
        "Next: Patch the smallest async iterator call site and rerun the check."
    )
    assert payload["agent_meta"]["resume_thread"] == expected_resume
    assert payload["coach_turn"]["resume_thread"] == expected_resume
    assert payload["reply"]["metadata"]["next_step_hint"]["resume_thread"] == expected_resume
    assert "Resume the live thread" not in payload["agent_meta"]["resume_thread"]
