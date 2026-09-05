from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.models import (
    LearningPlan,
    PlanStage,
    ProviderConfig,
    ProviderTestResponse,
    UserProfile,
)
from app.llm.provider_service import ProviderService
from tests.test_api import build_client


def test_server_and_bundled_sources_exclude_known_gbk_mojibake_residue() -> None:
    project_root = Path(__file__).resolve().parents[2]
    source_paths = (
        project_root / "server" / "app" / "llm" / "prompts.py",
        project_root / "server" / "app" / "api" / "routers.py",
        project_root / "extension" / "bundled" / "server" / "app" / "llm" / "prompts.py",
        project_root / "extension" / "bundled" / "server" / "app" / "api" / "routers.py",
    )
    forbidden_fragments = ("\u5bf0\u581d\u76ac", "\u6960\u5c83\u7609", "\u9225")

    for source_path in source_paths:
        source = source_path.read_text(encoding="utf-8")
        assert not any(fragment in source for fragment in forbidden_fragments), source_path


def test_detect_language_corruption_respects_response_language_even_for_english_message() -> None:
    service = ProviderService()

    detected = service.detect_language_corruption(
        message="Help me scope the first tiny slice.",
        reply="The provider only saw question marks: ?????",
        response_language="zh-CN",
    )

    assert detected is True


def test_detect_language_corruption_rejects_english_only_prose_for_zh_cn() -> None:
    service = ProviderService()

    detected = service.detect_language_corruption(
        message="\u8bf7\u89e3\u91ca VS Code remote workspace boundary\u3002",
        reply="First identify the host that owns the workspace, then verify one real path.",
        response_language="zh-CN",
    )

    assert detected is True


def test_finalize_coaching_reply_recovers_english_only_zh_cn_prose_in_chinese() -> None:
    service = ProviderService()
    profile = UserProfile(long_term_goal="\u5b66\u4e60 VS Code remote workflow")

    reply = service.finalize_coaching_reply(
        "First identify the host that owns the workspace, then verify one real path.",
        profile=profile,
        message="\u8bf7\u89e3\u91ca VS Code remote workspace boundary\u3002",
        response_language="zh-CN",
        coach_context={"scenario": "remote_workspace"},
    )

    assert any("\u3400" <= char <= "\u9fff" for char in reply)
    assert "First identify" not in reply
    failure = service.peek_last_reply_failure()
    assert failure is not None
    assert failure["error_category"] == "language_corruption"


def test_detect_language_corruption_flags_mixed_script_junk_in_english_reply() -> None:
    service = ProviderService()

    detected = service.detect_language_corruption(
        message="Help me learn VS Code remote workflows first.",
        reply=(
            "Glad you want to start with VS Code remote "
            "\u0431\u043a"
            " it's a great target because once the model clicks, debugging and run confi"
            "\u0431\u043d"
            " stay more stable."
        ),
        response_language="en-US",
    )

    assert detected is True


def test_detect_language_corruption_flags_latin1_style_mojibake_for_zh_reply() -> None:
    service = ProviderService()
    reply = "先沿着 VS Code 远程工作区 这条主线继续推进。".encode("utf-8").decode("latin-1")

    detected = service.detect_language_corruption(
        message="请继续",
        reply=reply,
        response_language="zh-CN",
    )

    assert detected is True


def test_provider_service_marks_recent_zh_integrity_success_after_clean_visible_reply() -> None:
    service = ProviderService()
    profile = UserProfile(
        long_term_goal="Keep Chinese coaching reliable",
        weekly_hours=4,
        teaching_style="guided",
        answer_policy="guided",
    )

    reply = service.finalize_coaching_reply(
        "好，我们继续沿着当前 debug 这条线往下走，先只盯住一个 breakpoint 和一个 value。",
        profile=profile,
        message="继续",
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={"scenario": "debug_loop"},
    )

    assert "当前 debug" in reply
    assert service.has_recent_language_integrity_success(
        message="继续",
        response_language="zh-CN",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_language", "reply", "expect_recovery"),
    [
        (
            "zh-CN",
            "First inspect the VS Code API boundary, then verify one real response path.",
            True,
        ),
        (
            "zh-CN",
            "先检查 VS Code 的 API 边界，再验证一条真实 response path。",
            False,
        ),
        (
            "en-US",
            "First inspect the VS Code API boundary, then verify one real response path.",
            False,
        ),
    ],
)
async def test_agentic_stream_defers_text_until_final_integrity_check(
    monkeypatch: pytest.MonkeyPatch,
    response_language: str,
    reply: str,
    expect_recovery: bool,
) -> None:
    service = ProviderService(
        config=ProviderConfig(
            name="test-provider",
            base_url="https://api.openai.com/v1",
            api_key_ref="trainer.test",
            model="gpt-4o-mini",
        ),
        api_key="sk-test",
    )
    profile = UserProfile(
        long_term_goal="Keep coaching language reliable",
        weekly_hours=4,
        teaching_style="guided",
        answer_policy="guided",
    )

    async def _fake_call(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {"content": reply, "tool_calls": []}

    async def _fake_call_stream(
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ):
        midpoint = len(reply) // 2
        yield {"type": "delta", "delta": reply[:midpoint]}
        yield {"type": "delta", "delta": reply[midpoint:]}
        yield {"type": "final", "content": reply, "tool_calls": [], "stop_reason": "stop"}

    provider = SimpleNamespace(
        protocol="openai_chat_completions",
        call=_fake_call,
        call_stream=_fake_call_stream,
    )

    def _build_agent_provider(
        self: ProviderService,
        **_: object,
    ) -> tuple[object, object]:
        return provider, provider

    monkeypatch.setattr(ProviderService, "build_agent_provider", _build_agent_provider)

    events: list[dict[str, object]] = []
    async for event in service.coaching_reply_agentic_stream(
        profile,
        "请带我检查 VS Code API 的一条真实 response path。",
        response_language=response_language,
        coach_context={
            "__runtime__": object(),
            "workspace_id": "workspace-language-stream",
            "session_id": "session-language-stream",
        },
    ):
        events.append(event)

    text_events = [event for event in events if event["type"] == "text"]
    final = next(event for event in events if event["type"] == "final")

    assert not text_events
    if expect_recovery:
        assert str(final["stop_reason"]).startswith("language_corruption")
        assert "First inspect" not in str(final["content"])
        assert any("\u3400" <= char <= "\u9fff" for char in str(final["content"]))
        return

    assert not str(final["stop_reason"]).startswith("language_corruption")
    assert final["content"] == reply


def test_turn_preflights_language_integrity_for_workspace_default_zh_cn(tmp_path: Path) -> None:
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
    provider_config = ProviderConfig.model_validate(provider_payload)

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
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
        ) as test_mock,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=AssertionError("coaching_reply should not run after preflight block")),
        ),
    ):
        runtime = client.app.state.runtime
        runtime.provider_config = provider_config
        runtime.provider_api_key = "sk-test"
        runtime.provider_service_cache.clear()

        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-zh-guard",
                "workspace_name": "trainer-zh-guard",
                "profile": {
                    "long_term_goal": "Guard zh-CN coaching truthfully",
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
                "workspace_id": "workspace-zh-guard",
                "response_language": "zh-CN",
                "answer_mode": "coach-first",
            },
        )
        assert settings_response.status_code == 200

        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-zh-guard",
                "intent": "coach",
                "message": "Help me scope the first tiny slice for session restore.",
                "provider": provider_payload,
                "api_key": "sk-test",
                "answer_mode": "coach-first",
            },
        )
        live_plan = LearningPlan(
            id="plan-zh-guard-live",
            title="zh-CN language integrity plan",
            current_step="Keep the blocked provider lane honest",
            why_now="Language integrity must stay fail-closed",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Integrity",
                    goal="Keep zh-CN honest",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        runtime.repository.save_plan("workspace-zh-guard", live_plan)
        runtime.memory_service.bind_explicit_generated_plan("workspace-zh-guard", live_plan)
        next_task_response = client.post(
            "/task/next",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-zh-guard",
            },
        )

    assert response.status_code == 200
    assert next_task_response.status_code == 200
    assert test_mock.call_args is not None
    assert test_mock.call_args.kwargs["probe_message"] == "Help me scope the first tiny slice for session restore."
    assert test_mock.call_args.kwargs["response_language"] == "zh-CN"
    payload = response.json()
    next_task_payload = next_task_response.json()
    assert "为了避免误导你" in payload["reply"]["content"]
    assert payload["reply"]["metadata"]["response_language"] == "zh-CN"
    assert payload["coach_turn"]["scenario"] == "general"
    assert payload["agent_meta"]["scenario"] == "general"
    assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "general"
    assert payload["snapshot"]["memory"]["active_thread"]["scenario"] == "general"
    assert "先切换 provider" in payload["coach_turn"]["next_step"]
    assert "gateway" in payload["coach_turn"]["next_step"]
    assert "沿着当前教练主线继续推进" in next_task_payload["natural_language_goal"]
    assert "先切换 provider" in next_task_payload["natural_language_goal"]
    assert "gateway" in next_task_payload["natural_language_goal"]
    assert next_task_payload["verification_strategy"][0].startswith("补丁落地后")
    assert next_task_payload["metadata"]["scenario"] == "general"
    assert next_task_payload["metadata"]["source"] == "active_thread"


def test_session_message_reuses_recent_zh_language_integrity_success_for_short_continuations(
    tmp_path: Path,
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
    provider_config = ProviderConfig.model_validate(provider_payload)

    test_results = iter(
        [
            ProviderTestResponse(
                ok=True,
                detail="Provider reachable. Chat probe succeeded with model MiniMax-M3. Response: pong",
                provider_reachable=True,
                model_supported=True,
            ),
            ProviderTestResponse(
                ok=False,
                detail="Provider reachable, but it corrupted Chinese input into question marks before the model saw it.",
                error_category="language_corruption",
                retryable=False,
                status_code=200,
                provider_reachable=True,
                model_supported=True,
            ),
        ]
    )

    async def coaching_reply(*args, **kwargs) -> str:
        del args, kwargs
        return "好，我们继续沿着当前 debug 这条线往下走，先只盯住一个 breakpoint 和一个 value。"

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
            ProviderService,
            "test",
            autospec=True,
            side_effect=lambda *args, **kwargs: next(test_results),
        ) as test_mock,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(side_effect=coaching_reply),
        ),
    ):
        runtime = client.app.state.runtime
        runtime.provider_config = provider_config
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider_config, api_key="sk-test")
        runtime.provider_service_cache.clear()

        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-zh-session-message-cache",
                "workspace_name": "trainer-zh-session-message-cache",
                "profile": {
                    "long_term_goal": "Keep short zh-CN continuation messages inside the same lane",
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
                "workspace_id": "workspace-zh-session-message-cache",
                "message": "请先一步一步教我怎么在 VS Code 里 debug Python，再测试我。先从一个 breakpoint 和一个可验证的 value 开始。",
                "response_language": "zh-CN",
                "answer_mode": "guided",
                "provider": provider_payload,
                "api_key": "sk-test",
            },
        )
        assert first_response.status_code == 200, first_response.text
        runtime.provider_service_for(provider_config, "sk-test").mark_language_integrity_success(
            message="继续",
            response_language="zh-CN",
        )

        second_response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-zh-session-message-cache",
                "message": "继续",
                "response_language": "zh-CN",
                "answer_mode": "guided",
                "provider": provider_payload,
                "api_key": "sk-test",
            },
        )

    assert second_response.status_code == 200, second_response.text
    assert test_mock.call_count == 1
    second_payload = second_response.json()
    assert second_payload["coach_turn"]["scenario"] == "debug_loop"
    assert second_payload["reply"]["metadata"]["coach_turn"]["scenario"] == "debug_loop"
    assert second_payload["snapshot"]["memory"]["active_thread"]["scenario"] == "debug_loop"
    assert "question marks" not in second_payload["reply"]["content"]
    assert "好，我们继续沿着当前 debug 这条线往下走" in second_payload["reply"]["content"]


def test_session_message_short_zh_continuation_skips_language_preflight_and_keeps_lane(
    tmp_path: Path,
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
    provider_config = ProviderConfig.model_validate(provider_payload)

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
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
        ) as test_mock,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(
                return_value="好，我们继续沿着当前 debug 这条线往下走，先只盯住一个 breakpoint 和一个 value。"
            ),
        ),
    ):
        runtime = client.app.state.runtime
        runtime.provider_config = provider_config
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider_config, api_key="sk-test")
        runtime.provider_service_cache.clear()

        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-zh-continuation-preflight-skip",
                "workspace_name": "trainer-zh-continuation-preflight-skip",
                "profile": {
                    "long_term_goal": "Keep short zh-CN continuation messages inside the same debug lane",
                    "weekly_hours": 4,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start_response.status_code == 200
        session_id = start_response.json()["session_id"]

        runtime.memory_service.record_turn_memory(
            workspace_id="workspace-zh-continuation-preflight-skip",
            session_id=session_id,
            scenario="debug_loop",
            focus_area="launch diagnostics",
            summary="Pinned the first breakpoint branch.",
            next_step="Re-run one launch target and inspect the first failing frame.",
            response_language="zh-CN",
            answer_mode="guided",
        )

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-zh-continuation-preflight-skip",
                "message": "继续",
                "response_language": "zh-CN",
                "answer_mode": "guided",
                "provider": provider_payload,
                "api_key": "sk-test",
            },
        )

    assert response.status_code == 200, response.text
    assert test_mock.call_count == 0
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "debug_loop"
    assert payload["reply"]["metadata"]["coach_turn"]["scenario"] == "debug_loop"
    assert payload["snapshot"]["memory"]["active_thread"]["scenario"] == "debug_loop"
    assert "当前 debug" in payload["reply"]["content"]


def test_session_message_library_first_doc_question_skips_language_preflight(
    tmp_path: Path,
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
    provider_config = ProviderConfig.model_validate(provider_payload)
    agentic_reply = AsyncMock(
        return_value={
            "content": (
                "Resources 视图的 first viewport promise 是让用户先 find、trust、preview、convert 资料，"
                "并且绝不能变成 raw filesystem browser。"
            ),
            "summary": "resources contract",
            "next_step": "把这条 promise 和 must not become 变成一个可验证 checklist。",
            "decision": None,
            "blocker": None,
            "teaching_note": None,
            "resume_thread": "继续围绕 resources contract 这条线往下走。",
            "confidence": None,
            "evidence": None,
            "tool_events": [],
            "stop_reason": "completed",
            "fell_back": False,
            "recovered_stop_reason": None,
        }
    )
    plain_reply = AsyncMock(
        return_value=(
            "Resources 视图的 first viewport promise 是让用户先 find、trust、preview、convert 资料，"
            "并且绝不能变成 raw filesystem browser。"
        )
    )

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
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
        ) as test_mock,
        patch.object(ProviderService, "coaching_reply_agentic", new=agentic_reply),
        patch.object(ProviderService, "coaching_reply", new=plain_reply),
    ):
        runtime = client.app.state.runtime
        runtime.provider_config = provider_config
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider_config, api_key="sk-test")
        runtime.provider_service_cache.clear()

        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-library-first-preflight-skip",
                "workspace_name": "trainer-library-first-preflight-skip",
                "profile": {
                    "long_term_goal": "Keep library-grounded doc turns truthful without blocking real provider runs",
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
                "workspace_id": "workspace-library-first-preflight-skip",
                "kind": "markdown",
                "name": "resources-view-contract.md",
                "source": "inline://resources-view-contract.md",
                "content": (
                    "# Resources view contract\n"
                    "First viewport promise: the learner can find, trust, preview, and convert resources.\n"
                    "Must not become: a raw filesystem browser.\n"
                ),
                "content_encoding": "utf-8",
                "tags": ["library-first", "language-integrity"],
            },
        )
        assert upload_response.status_code == 200, upload_response.text
        upload_payload = upload_response.json()

        index_response = client.post(
            "/resource/index",
            json={
                "workspace_id": "workspace-library-first-preflight-skip",
                "resource_id": upload_payload["id"],
                "enable_network": False,
            },
        )
        assert index_response.status_code == 200, index_response.text

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-library-first-preflight-skip",
                "message": "我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise，以及它绝不能变成什么。",
                "response_language": "zh-CN",
                "answer_mode": "guided",
                "provider": provider_payload,
                "api_key": "sk-test",
            },
    )

    assert response.status_code == 200, response.text
    assert test_mock.call_count == 0
    assert agentic_reply.await_count + plain_reply.await_count == 1
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "principle"
    assert payload["agent_meta"]["stop_reason"] in {"completed", "coach_finalize"}
    assert payload["agent_meta"]["auto_resource_lookup"] is True
    assert any(
        event["name"] == "search_resources" for event in payload["agent_meta"]["tool_events"]
    )
    assert "raw filesystem browser" in payload["reply"]["content"]


def test_session_message_library_first_doc_question_repairs_missing_boundary(
    tmp_path: Path,
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
    provider_config = ProviderConfig.model_validate(provider_payload)
    drifting_reply = (
        "Resources 视图的 first viewport promise 是让用户先 find、trust、preview、convert 资料。"
        "我们继续沿着 VS Code remote 这条线往下走。"
    )
    agentic_reply = AsyncMock(
        return_value={
            "content": drifting_reply,
            "summary": "continue remote thread",
            "next_step": "告诉我你现在用的是哪一种 remote 连接。",
            "decision": None,
            "blocker": None,
            "teaching_note": None,
            "resume_thread": "继续 remote 这条线。",
            "confidence": None,
            "evidence": None,
            "tool_events": [],
            "stop_reason": "completed",
            "fell_back": False,
            "recovered_stop_reason": None,
        }
    )
    plain_reply = AsyncMock(return_value=drifting_reply)

    with (
        build_client(tmp_path, configure_provider=False) as client,
        patch.object(
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
        ) as test_mock,
        patch.object(ProviderService, "coaching_reply_agentic", new=agentic_reply),
        patch.object(ProviderService, "coaching_reply", new=plain_reply),
    ):
        runtime = client.app.state.runtime
        runtime.provider_config = provider_config
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider_config, api_key="sk-test")
        runtime.provider_service_cache.clear()

        start_response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-library-first-contract-repair",
                "workspace_name": "trainer-library-first-contract-repair",
                "profile": {
                    "long_term_goal": "Keep grounded resource answers attached to the requested contract.",
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
                "workspace_id": "workspace-library-first-contract-repair",
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
                "tags": ["library-first", "resource-contract"],
            },
        )
        assert upload_response.status_code == 200, upload_response.text
        upload_payload = upload_response.json()

        index_response = client.post(
            "/resource/index",
            json={
                "workspace_id": "workspace-library-first-contract-repair",
                "resource_id": upload_payload["id"],
                "enable_network": False,
            },
        )
        assert index_response.status_code == 200, index_response.text

        response = client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-library-first-contract-repair",
                "message": "我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise，以及它绝不能变成什么。",
                "response_language": "zh-CN",
                "answer_mode": "guided",
                "provider": provider_payload,
                "api_key": "sk-test",
            },
        )

    assert response.status_code == 200, response.text
    assert test_mock.call_count == 0
    payload = response.json()
    assert payload["coach_turn"]["scenario"] == "principle"
    assert payload["agent_meta"]["grounded_resource_contract_repaired"] is True
    assert "raw filesystem browser" in payload["reply"]["content"]
    assert "VS Code remote" not in payload["reply"]["content"]
    assert "remote 连接" not in payload["reply"]["content"]
