"""A turn that fails on the provider path says what happened once.

Seen on 2026-11-28 with the provider port closed and the agent loop on, on both turn routes::

    Trainer 当前卡在 provider path，所以这轮 coaching 还不能继续。

    Trainer 目前无法通过 network 连到这个 provider。
    详情：Trainer 当前卡在 provider path，所以这轮 coaching 还不能继续。 Trainer 目前无法通过 network 连到这个
    provider。 详情：Trainer 目前无法通过 network 连到这个 provider。 下一步：先检查 network 路径或 proxy 设置，再重发...
    下一步：先检查 network 路径或 proxy 设置，再重发这一轮。

The agent path built the clean reply with its own summary as the "detail" line, stored that reply as
the failure's detail, and the route then wrapped the reply around itself as its own "详情".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from client_fixtures import build_client
from fastapi import FastAPI
from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.api.runtime import TrainerRuntime
from app.core.models import CapabilityFlags, ProviderConfig

pytestmark = pytest.mark.asyncio

SUMMARY = "Trainer 目前无法通过 network 连到这个 provider。"
NEXT_STEP = "下一步：先检查 network 路径或 proxy 设置，再重发这一轮。"
PLAIN_BANNER = "这次没能连上模型服务。请在设置里检查服务地址、模型和 API 密钥后再试一次。"


def _provider() -> ProviderConfig:
    # Nothing listens on port 9: the connection is refused at once.
    return ProviderConfig(
        name="closed-port",
        baseUrl="http://127.0.0.1:9/v1",
        apiKeyRef="trainer.closed",
        model="minimax-m2",
        capabilities=CapabilityFlags(chat=True, streaming=True, tools=True),
    )


def _runtime(client: TestClient) -> TrainerRuntime:
    """Starlette types ``TestClient.app`` as the ASGI callable; the app behind it is FastAPI."""
    application = client.app
    assert isinstance(application, FastAPI), "test client must wrap the Trainer FastAPI app"
    runtime = application.state.runtime
    assert isinstance(runtime, TrainerRuntime), "FastAPI app must expose a TrainerRuntime"
    return runtime


def _start(client: TestClient, project: Path) -> dict[str, object]:
    started = client.post(
        "/session/start",
        json={"workspace_id": "ws-closed", "workspace_name": "Closed port", "workspace_path": str(project)},
    )
    assert started.status_code == 200, started.text
    return {
        "session_id": started.json()["session_id"],
        "workspace_id": "ws-closed",
        "intent": "coach",
        "message": "这段为什么会报 KeyError？",
        "answer_mode": "guided",
        "response_language": "zh-CN",
        "use_agent_loop": True,
        "provider": _provider().model_dump(by_alias=True),
        "api_key": "test-only-key",
        "current_file": {"path": str(project / "app.py"), "language_id": "python", "content": "print(1)\n"},
    }


def _assert_said_once(visible: str) -> None:
    assert visible.count(SUMMARY) == 1, visible
    assert visible.count(NEXT_STEP) == 1, visible
    assert "详情" not in visible, visible
    assert "..." not in visible, visible


@pytest.mark.parametrize("route", ["turn", "stream"])
async def test_an_unreachable_provider_is_reported_once(tmp_path: Path, route: str) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    (project / "app.py").write_text("print(1)\n", encoding="utf-8")
    with build_client(tmp_path / "sidecar", configure_provider=False) as client:
        seed_verified_capabilities(_runtime(client), _provider(), "test-only-key")
        body = _start(client, project)
        if route == "turn":
            response = client.post("/turn", json=body)
            assert response.status_code == 200, response.text
            _assert_said_once(response.json()["reply"]["content"])
            return

        chunks: list[str] = []
        with client.stream("POST", "/turn/stream", json=body, headers={"accept": "text/event-stream"}) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                frame = json.loads(line[5:].strip())
                if isinstance(frame.get("chunk"), str):
                    chunks.append(frame["chunk"])

    _assert_said_once("".join(chunks))


def _english_sentences(text: str) -> list[str]:
    """Sentences written in English. A Chinese turn carries identifiers and code, not sentences."""
    segments = [part.strip() for part in re.split(r"[\n。：:]|(?<=[a-z])\. ", text) if part.strip()]
    return [
        segment
        for segment in segments
        if sum(char.isascii() and char.isalpha() for char in segment) > 8
        and not any("\u4e00" <= char <= "\u9fff" for char in segment)
    ]


def _plain_turn(client: TestClient, project: Path, session_id: str) -> str:
    body = {
        "session_id": session_id,
        "workspace_id": "ws-closed",
        "intent": "coach",
        "message": "这段为什么会报 KeyError？",
        "answer_mode": "guided",
        "response_language": "zh-CN",
        "use_agent_loop": False,
        "provider": _provider().model_dump(by_alias=True),
        "api_key": "test-only-key",
        "current_file": {"path": str(project / "app.py"), "language_id": "python", "content": "print(1)\n"},
    }
    chunks: list[str] = []
    with client.stream("POST", "/turn/stream", json=body, headers={"accept": "text/event-stream"}) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data:"):
                frame = json.loads(line[5:].strip())
                if isinstance(frame.get("chunk"), str):
                    chunks.append(frame["chunk"])
    return "".join(chunks)


async def test_the_local_scaffold_after_a_failure_is_written_in_the_learner_s_language(tmp_path: Path) -> None:
    """Without the agent loop the coach answers from its local scaffold. That material is English
    prompt text with Chinese anchors inside — an exercise prompt, a remembered win — and it slipped
    past a gate that refused only text with no Chinese at all. The learner read
    "先把这个原理落成动作：Point at one line or branch in /var/folders/…/app.py, explain how 'Anchor 当前聚焦：…'"
    under "这次没能连上模型服务". A second failure quotes what the first stored in the thread."""
    project = tmp_path / "repo"
    project.mkdir()
    (project / "app.py").write_text("print(1)\n", encoding="utf-8")
    with build_client(tmp_path / "sidecar", configure_provider=False) as client:
        seed_verified_capabilities(_runtime(client), _provider(), "test-only-key", tools=False)
        session_id = str(_start(client, project)["session_id"])
        visible = "".join(_plain_turn(client, project, session_id) for _ in range(2))

    assert visible.startswith(PLAIN_BANNER)
    assert not _english_sentences(visible), _english_sentences(visible)
    assert str(project) not in visible
    assert "。。" not in visible
    assert "当前聚焦：" not in visible
    # Sentences of one paragraph end with a sentence end, not with a space: "先从 `app.py` 开始 我会把…".
    assert not re.search("[\u4e00-\u9fff] [\u4e00-\u9fff]", visible), visible
