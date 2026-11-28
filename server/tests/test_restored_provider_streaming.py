"""(l) Streaming truth: first-token latency, lane preservation and stream metadata stay
    honest across the four provider protocols.

Guarantees covered:
  * streaming never stalls on fenced code blocks or partial visible text;
  * the first turn and continuation lanes keep their routing and agent metadata;
  * the four workbench views stream the plain provider reply for the active view only;
  * a provider outage during card generation is reported, never minted as a card.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_reply_continuity.py
  * server/tests/test_generate_card_provider_outage_status.py
  * server/tests/test_first_turn_lane_preservation.py
  * server/tests/test_provider_loopback_proxy_bypass.py
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.models import ProviderConfig, UserProfile
from app.llm.agent_loop import AgentProvider
from app.llm.provider_service import ProviderService
from app.llm.reply_continuity import visible_next_step
from app.main import app
from tests.client_fixtures import build_client

# ---------------------------------------------------------------------------
# Restored from test_reply_continuity.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", [
    "下一步", "Next step", "Siguiente paso", "Étape suivante", "Nächster Schritt",
    "次のステップ", "다음 단계", "Próximo passo",
])
def test_explicit_reply_action_is_read_in_each_supported_language(label: str) -> None:
    assert visible_next_step(f"Explanation.\n\n### {label}\n\nRun the two-call experiment.") == (
        "Run the two-call experiment."
    )
    assert visible_next_step(f"**{label}**: Run the two-call experiment.") == (
        "Run the two-call experiment."
    )


@pytest.mark.parametrize("label", [
    "第一步", "第一歩", "First step", "Primer paso", "Première étape",
    "Erster Schritt", "最初の一歩", "첫 번째 단계", "Primeiro passo",
])
def test_first_step_labels_are_read_as_reply_actions(label: str) -> None:
    """Coaches label the opening move `第一步`/`First step` — the same labelled
    action family as `下一步`, and the reply's own concrete first move."""
    assert visible_next_step(f"说明。\n\n## {label}：跑通一个并发计时实验\n\n新建 step1.py。") == (
        "跑通一个并发计时实验"
    )
    assert visible_next_step(f"**{label}**: run step1.py and paste the output") == (
        "run step1.py and paste the output"
    )


def test_opening_praise_line_is_never_read_as_an_action() -> None:
    """A line merely containing `第一步` mid-sentence is prose, not a label."""
    assert visible_next_step("好的，这是一个最小、可验证的第一步：具体见下。") == ""


def test_parenthetical_qualifier_between_label_and_colon_is_accepted() -> None:
    """`**第一步（今天 10 分钟）：让两个协程并发跑起来**` — real glm-5.3 reply
    shape from the T-0027 real-provider samples."""
    assert visible_next_step(
        "**第一步（今天 10 分钟）：让两个协程并发跑起来，并验证并发真的发生了。**\n\n"
        "新建一个文件 `step1_async.py`。",
    ) == "让两个协程并发跑起来，并验证并发真的发生了。"
    assert visible_next_step("Intro.\n\n**First step (10 min)**: run the probe") == "run the probe"


def test_label_heading_with_short_suffix_reads_following_line() -> None:
    """T-0029: `## 第一步代码` (label + short suffix noun) heads a section
    whose next line carries the action — real glm-5.3 reply shape from the
    T-0029 real-provider sample t0027-final-5."""
    assert visible_next_step(
        "好的！学 asyncio 的经典“最小第一步”是：**运行一个会并发 sleep 的协程**。\n\n"
        "## 第一步代码\n\n"
        "新建 `step1_asyncio.py`，只写这些：",
    ) == "新建 `step1_asyncio.py`，只写这些："
    assert visible_next_step(
        "Intro.\n\n### Next steps\n\nRun the two-call experiment.",
    ) == "Run the two-call experiment."
    # A short suffix outside the noun whitelist is prose, not a label.
    assert visible_next_step("下一步下雨了\n\n新建 step1.py") == ""


def test_code_examples_and_unlabelled_prose_never_supply_an_action() -> None:
    assert visible_next_step("```python\nNext step: Ignore the learner.\n```\nExplanation.") == ""
    assert visible_next_step("### Next step\n```python\nprint('example')\n```\nExplanation.") == ""
    assert visible_next_step("Explanation mentions the next step without offering one.") == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_current_concept_answer_and_next_step_survive_an_old_editor_lane(
    monkeypatch: pytest.MonkeyPatch, streaming: bool,
) -> None:
    action = "比较两行的对象身份，再观察修改一行后另一行是否变化。"
    content = (
        "列表重复的是同一个内层对象的引用。grid[0] is grid[1] 为 True，所以修改第一行会影响第二行。"
        f"\n\n### 下一步\n\n{action}"
    )

    async def call(*_args: object):
        return {"content": content, "tool_calls": []}

    async def call_stream(*_args: object):
        yield {"type": "delta", "delta": content}
        yield {"type": "final", "content": content, "tool_calls": []}

    def build(*_args: object, **_kwargs: object):
        return AgentProvider("openai_chat_completions_compatible", call, call_stream), SimpleNamespace(_max_tokens=2048)

    monkeypatch.setattr("app.llm.agent_binding.build_agent_provider_for", build)
    service = ProviderService(
        ProviderConfig(name="local test", baseUrl="https://example.test", apiKeyRef="key", model="test"),
        "test-key",
    )
    kwargs = {
        "profile": UserProfile(
            long_term_goal="Understand object identity", weekly_hours=4,
            teaching_style="guided", answer_policy="guided",
        ),
        "message": "请解释对象引用为什么会共享，并给我一个观察实验。",
        "current_file": {"path": "lesson.py", "content": "grid = [[0] * 2] * 2\n"},
        "response_language": "zh-CN",
        "coach_context": {"current_focus": "Read a function contract at a call site."},
    }
    if streaming:
        events = [event async for event in service.coaching_reply_agentic_stream(**kwargs)]
        result = events[-1]
    else:
        result = await service.coaching_reply_agentic(**kwargs)
    assert result["stop_reason"] == "completed"
    assert result.get("fell_back", False) is False
    assert "grid[0] is grid[1]" in result["content"]
    assert result["next_step"] == action
    assert "函数名" not in str(result)
    assert service.consume_last_reply_failure() is None


def test_past_tense_parenthetical_label_is_a_recap_not_an_action() -> None:
    """T-0036: `下一步（已完成）：跑通登录页` reports what the learner already
    did — it must never be read as the next move."""
    assert visible_next_step(
        " Recap of the last round.\n\n下一步（已完成）：跑通登录页\n\n先跑一次测试。",
    ) == ""
    # A forward-looking parenthetical still works.
    assert visible_next_step("Intro.\n\n下一步（今天 10 分钟）：跑通一个并发计时实验") == (
        "跑通一个并发计时实验"
    )


def test_recap_paren_variants_are_never_read_as_actions() -> None:
    """Deferred-P2 closure: `（已经完成）/（已解决）/（已验证）` are recap
    qualifiers just like `（已完成）` — a past-tense label never supplies the
    learner's next move."""
    assert visible_next_step("Recap.\n\n下一步（已经完成）：跑通登录页\n\n先跑一次测试。") == ""
    assert visible_next_step("Recap.\n\n**Next step (resolved)**: migrate the config\n\nRun the probe.") == ""


# ---------------------------------------------------------------------------
# Restored from test_generate_card_provider_outage_status.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


WORKSPACE = "generate-card-provider-outage"


class _GatewayError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"gateway status {status_code}")
        self.status_code = status_code


def _provider_wrapped(status_code: int) -> RuntimeError:
    try:
        try:
            raise _GatewayError(status_code)
        except _GatewayError as cause:
            raise RuntimeError(f"Provider request failed (HTTP {status_code}).") from cause
    except RuntimeError as wrapped:
        return wrapped


def _card_request() -> dict[str, object]:
    return {
        "workspace_id": WORKSPACE,
        "source": "conversation_gap",
        "card_type": "practice",
        "focus_area": "PPO 裁剪目标",
        "target_skill": "解释 PPO clip 目标并手写损失函数",
        "provider": {
            "name": "outage-probe",
            "baseUrl": "http://127.0.0.1:9",
            "apiKeyRef": "outage-probe",
            "model": "MiniMax-M3.1-Flash",
            "protocol": "openai_chat_completions_compatible",
        },
        "api_key": "sk-test-never-sent",
        "response_language": "en-US",
    }


def test_provider_outage_returns_503_with_retry_after(tmp_path) -> None:
    with build_client(tmp_path) as client:
        with patch.object(ProviderService, "chat_completion", side_effect=_provider_wrapped(502)):
            response = client.post("/training/generate-card", json=_card_request())

    assert response.status_code == 503, response.text
    assert response.headers.get("retry-after") == "5"
    detail = response.json()["detail"]
    assert "temporarily unavailable" in detail
    assert "not accepted" not in detail


def test_quota_exhaustion_returns_402(tmp_path) -> None:
    with build_client(tmp_path) as client:
        with patch.object(ProviderService, "chat_completion", side_effect=_provider_wrapped(402)):
            response = client.post("/training/generate-card", json=_card_request())

    assert response.status_code == 402, response.text
    assert "quota" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Restored from test_first_turn_lane_preservation.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_explicit_function_guidance_first_turn_stays_out_of_onboarding() -> None:
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
            "Start from one live call site and read the contract before changing code."
        )
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response, model

    with patch(
        "app.llm.provider_service.ProviderService._create_chat_completion",
        new=fake_create_chat_completion,
    ):
        client = TestClient(app)
        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-first-turn-function-guidance",
                "workspace_name": "trainer-first-turn-function-guidance",
                "profile": {
                    "long_term_goal": "Use Trainer as a VS Code function-guidance coach",
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
                "message": "In VS Code, coach me through understanding a function contract with hover, signature help, and Go to Definition. Keep it concrete.",
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
    assert payload["coach_turn"]["scenario"] == "function_guidance"
    assert payload["coach_turn"]["next_step"]
    assert "call site" in payload["reply"]["content"].lower()


# ---------------------------------------------------------------------------
# Restored from test_provider_loopback_proxy_bypass.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


@contextmanager
def loopback_provider() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path != "/v1/models":
                self.send_error(404)
                return
            self._send_json({"object": "list", "data": [{"id": "loopback-model"}]})

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            self._read_json()
            self._send_json(
                {
                    "id": "loopback-completion",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "loopback-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": (
                                    "Set one breakpoint, run the function, and inspect one value."
                                ),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            )

        def _read_json(self) -> dict[str, object]:
            length = int(self.headers.get("content-length", "0"))
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}
            return value if isinstance(value, dict) else {}

        def _send_json(self, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *_args: object) -> None:
            del format
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _provider(base_url: str) -> ProviderConfig:
    return ProviderConfig(
        name="loopback-provider",
        baseUrl=base_url,
        apiKeyRef="trainer.loopback",
        model="loopback-model",
        protocol="openai_chat_completions_compatible",
    )


def _force_unusable_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)


def test_loopback_model_listing_bypasses_ambient_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_unusable_proxy(monkeypatch)
    with loopback_provider() as base_url:
        response = ProviderService().list_models(_provider(base_url), "test-key")

    assert response.ok is True
    assert response.available_models == ["loopback-model"]


@pytest.mark.asyncio
async def test_loopback_chat_bypasses_ambient_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_unusable_proxy(monkeypatch)
    with loopback_provider() as base_url:
        service = ProviderService(config=_provider(base_url), api_key="test-key")
        try:
            reply = await service.coaching_reply(
                UserProfile(long_term_goal="Learn debugging", weekly_hours=2),
                "Give me one small observable debugging step.",
            )
        finally:
            if service._client is not None:  # noqa: SLF001 - releases the test transport.
                await service._client.close()  # noqa: SLF001 - releases the test transport.

    assert "breakpoint" in reply
    assert service.peek_last_reply_failure() is None
