from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.api.provider_payload import provider_config_from_payload
from app.api.routers import _resolve_agent_loop_enabled
from app.core.models import (
    ProviderConfig,
    ResourceRecord,
    TurnRequest,
    UserProfile,
)
from app.core.settings import AppSettings
from app.llm.agent_binding import _format_gemini_payload
from app.llm.agent_loop import (
    AgentProvider,
    CoachAgentLoop,
    _build_completion_continuity,
    _build_empty_response_recovery,
    _build_no_progress_recovery,
    _build_runtime_failure_recovery,
    _build_step_limit_recovery,
    _visible_coach_finalize_reply,
    run_with_scripted_responses,
)
from app.llm.provider.capability import (
    _allows_keyless_local_provider,
    _flatten_minimax_thinking_for_raw_http,
    _normalized_provider_request_defaults,
)
from app.llm.provider.thinking import (
    apply_thinking_policy,
    declared_thinking,
    resolve_thinking_policy,
)
from app.llm.provider_service import ProviderService
from app.llm.tools import ToolContext, ToolDefinition, ToolRegistry, build_default_tool_registry
from app.main import create_app
from app.memory.note_request import message_requests_lecture_note_save
from app.network_fetch import ControlledFetchResponse
from app.pedagogy.service import PedagogyService
from app.pedagogy.smalltalk import (
    is_bogus_smalltalk_step,
    is_casual_greeting_or_smalltalk,
    is_exploratory_or_research_query,
)
from app.sandbox.service import SandboxService
from app.training.card_generator import (
    _WHY_NOW_MESSAGES,
    CardGenerationProviderFailure,
    _fallback_provenance_copy,
    _localized_why_now,
)


def _offline_app(tmp_path: Path, *, enable_network_fetch: bool = False):
    settings = AppSettings(
        app_name="Trainer Autonomous Teacher Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-autonomous.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=enable_network_fetch,
    )
    return create_app(settings)


def test_casual_greetings_and_exploratory_queries_never_forge_patch_step() -> None:
    svc = PedagogyService()
    for msg in (
        "你好",
        "hi",
        "hello!",
        "谢谢",
        "讲解一下这个文件夹项目呢",
        "你帮我找找目前的世界模型的研究进展可以吗",
    ):
        for mode in ("auto", "guided", "balanced", "coach-first", "direct"):
            _ls, _dec, artifacts = svc.analyze_turn(
                request=TurnRequest(
                    message=msg,
                    answer_mode=mode,
                    response_language="zh-CN",
                )
            )
            assert artifacts.implementation_guide is None, (msg, mode)


@pytest.mark.asyncio
async def test_list_workspace_files_prunes_ignored_dirs_and_supports_subdirs(tmp_path: Path) -> None:
    project = tmp_path / "sample-repo"
    for rel in (
        ".git/objects/aa",
        "node_modules/pkg/index.js",
        ".venv/lib/site.py",
        "__pycache__/mod.pyc",
        "dist/bundle.js",
        "README.md",
        "scripts/dev.sh",
        "src/core/engine.py",
        "src/api/routes.ts",
    ):
        target = project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# content\n", encoding="utf-8")

    registry = build_default_tool_registry()
    runtime = SimpleNamespace(resolve_workspace_path=lambda _ws: str(project))
    context = ToolContext(runtime=runtime, workspace_id="ws-list", extra={})

    listed = await registry.invoke(context, "list_workspace_files", {"pattern": "**/*", "limit": 120})
    assert listed["ok"] is True
    paths = {item["path"] for item in listed["items"]}
    assert {"README.md", "scripts/dev.sh", "src/core/engine.py", "src/api/routes.ts"}.issubset(paths)
    assert not any(
        bad in p
        for p in paths
        for bad in (".git/", "node_modules/", ".venv/", "__pycache__/", "dist/")
    )

    src_only = await registry.invoke(context, "list_workspace_files", {"directory": "src", "limit": 50})
    assert src_only["ok"] is True
    src_paths = {item["path"] for item in src_only["items"] if not item["is_dir"]}
    assert src_paths == {"src/core/engine.py", "src/api/routes.ts"}


@pytest.mark.asyncio
async def test_import_workspace_file_supports_selective_batch_into_sandbox(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    (project / "docs").mkdir(parents=True)
    (project / "README.md").write_text("# Repo Guide\nArchitecture details.\n", encoding="utf-8")
    (project / "docs" / "design.md").write_text("# Design\nModule boundaries.\n", encoding="utf-8")
    (project / "main.py").write_text("def run():\n    return True\n", encoding="utf-8")

    sandbox = SandboxService(
        data_root=tmp_path / "data",
        workspace_path_resolver=lambda _ws: str(project),
        workspace_authority_resolver=lambda _ws: None,
    )
    saved: list[ResourceRecord] = []

    class FakeResourceService:
        enable_network_fetch = False

        def upload(self, workspace_id: str, req, workspace_path: str = ""):
            record = ResourceRecord(
                id=f"res-{len(saved) + 1}",
                workspace_id=workspace_id,
                kind=req.kind,
                name=req.name,
                source=req.source,
                source_type=req.source_type,
                tags=req.tags,
            )
            saved.append(record)
            return record

        def index(self, workspace_id: str, req):
            return next(r for r in saved if r.id == req.resource_id)

    runtime = SimpleNamespace(
        sandbox_service=sandbox,
        resource_service=FakeResourceService(),
        repository=SimpleNamespace(list_resources=lambda _ws: list(saved), save_resource=lambda *_a: None),
        resolve_workspace_path=lambda _ws: str(project),
        postprocess_indexed_resource=None,
    )
    context = ToolContext(
        runtime=runtime,
        workspace_id="ws-batch-import",
        session_id="sess-batch-import",
        extra={"library_sandbox_work": True},
    )
    registry = build_default_tool_registry()

    batch = await registry.invoke(
        context,
        "import_workspace_file",
        {"paths": ["README.md", "docs/design.md"], "folder": "Architecture"},
    )
    assert batch["ok"] is True
    assert batch["imported_count"] == 2
    sandbox_root = sandbox.ensure_workspace_root("ws-batch-import")
    assert (sandbox_root / "sources" / "workspace" / "Architecture" / "README.md").is_file()
    assert (sandbox_root / "sources" / "workspace" / "Architecture" / "design.md").is_file()
    # User repository never receives writes
    assert not (project / "Architecture").exists()


@pytest.mark.asyncio
async def test_web_search_and_fetch_web_page_tools_honor_network_switch_and_arxiv_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry = build_default_tool_registry()
    disabled_runtime = SimpleNamespace(research_network_fetch_enabled=False)
    disabled_ctx = ToolContext(runtime=disabled_runtime, workspace_id="ws-net-off", extra={})

    off_res = await registry.invoke(disabled_ctx, "web_search", {"query": "world models"})
    assert off_res["ok"] is False
    assert off_res["error"] == "network_disabled"

    def fake_fetch(url: str, **_kwargs) -> ControlledFetchResponse:
        if "search.brave.com" in url or "duckduckgo.com" in url or "bing.com" in url or "wikipedia.org" in url:
            body = b"<html><body><div>no matches</div></body></html>"
            content_type = "text/html"
        elif "export.arxiv.org" in url:
            body = (
                b'<?xml version="1.0" encoding="UTF-8"?>'
                b'<feed xmlns="http://www.w3.org/2005/Atom">'
                b"<entry><id>https://arxiv.org/abs/2501.00001v1</id>"
                b"<published>2025-02-01T00:00:00Z</published>"
                b"<title>World Models Survey 2025</title>"
                b"<summary>Latent dynamics and predictive planning progress.</summary></entry>"
                b"</feed>"
            )
            content_type = "application/atom+xml"
        elif "arxiv.org/abs/2501.00001v1" in url:
            body = b"<html><body><main><h1>World Models Survey 2025</h1><p>Full abstract excerpt.</p></main></body></html>"
            content_type = "text/html"
        else:
            raise AssertionError(f"Unexpected URL {url}")
        return ControlledFetchResponse(
            body=body,
            final_url=url,
            status=200,
            headers={"content-type": content_type},
            fetched_at="2026-11-22T10:00:00+00:00",
        )

    monkeypatch.setattr("app.research.web_search.fetch_url", fake_fetch)
    enabled_runtime = SimpleNamespace(research_network_fetch_enabled=True)
    enabled_ctx = ToolContext(runtime=enabled_runtime, workspace_id="ws-net-on", extra={})

    searched = await registry.invoke(enabled_ctx, "web_search", {"query": "world models 2025", "limit": 3})
    assert searched["ok"] is True
    assert searched["results"][0]["source"] == "arxiv.org"
    assert "World Models Survey 2025" in searched["results"][0]["title"]

    fetched = await registry.invoke(
        enabled_ctx,
        "fetch_web_page",
        {"url": "https://arxiv.org/abs/2501.00001v1", "max_chars": 2000},
    )
    assert fetched["ok"] is True
    assert "Full abstract excerpt" in fetched["content"]


@pytest.mark.asyncio
async def test_blocking_tool_io_runs_off_the_event_loop(monkeypatch, tmp_path: Path) -> None:
    """A slow walk or web request must not stall the sidecar's event loop."""
    import os
    import threading

    import app.llm.tools as tools_module

    registry = build_default_tool_registry()
    project = tmp_path / "repo"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")

    walk_threads: list[str] = []
    real_walk = os.walk

    def recording_walk(*args, **kwargs):
        walk_threads.append(threading.current_thread().name)
        return real_walk(*args, **kwargs)

    monkeypatch.setattr(tools_module.os, "walk", recording_walk)
    runtime = SimpleNamespace(
        resolve_workspace_path=lambda _ws: str(project),
        research_network_fetch_enabled=True,
    )
    context = ToolContext(runtime=runtime, workspace_id="ws-offload", extra={})

    listed = await registry.invoke(context, "list_workspace_files", {"pattern": "**/*"})
    assert listed["ok"] is True
    assert "src/app.py" in {item["path"] for item in listed["items"]}

    fetch_threads: list[str] = []

    def fake_fetch(url: str, **_kwargs) -> ControlledFetchResponse:
        fetch_threads.append(threading.current_thread().name)
        return ControlledFetchResponse(
            body=b"<html><body><div>no matches</div></body></html>",
            final_url=url,
            status=200,
            headers={"content-type": "text/html"},
            fetched_at="2026-11-22T10:00:00+00:00",
        )

    monkeypatch.setattr("app.research.web_search.fetch_url", fake_fetch)
    searched = await registry.invoke(
        context,
        "web_search",
        {"query": "trainer", "limit": 1, "fetch_excerpts": False},
    )
    assert searched["ok"] is True

    main_thread = threading.main_thread().name
    assert walk_threads and all(name != main_thread for name in walk_threads)
    assert fetch_threads and all(name != main_thread for name in fetch_threads)


def test_lesson_prep_phrases_unlock_lecture_save_without_breaking_plain_turns() -> None:
    assert message_requests_lecture_note_save("帮我自主备课并生成讲稿") is True
    assert message_requests_lecture_note_save("Please prepare a lesson plan for this module") is True
    assert message_requests_lecture_note_save("请讲明白注意力缩放。") is False


def test_resolve_agent_loop_enables_project_and_research_turns_not_greetings() -> None:
    service = ProviderService(
        config=ProviderConfig(
            name="tool-provider",
            base_url="https://provider.example/v1",
            api_key_ref="trainer.test",
            model="tool-model",
            capabilities={"chat": True, "tools": True, "streaming": True},
        ),
        api_key="sk-test",
    )
    assert _resolve_agent_loop_enabled(TurnRequest(message="hello"), service) is False
    assert _resolve_agent_loop_enabled(TurnRequest(message="你好"), service) is False
    assert _resolve_agent_loop_enabled(TurnRequest(message="讲解一下这个文件夹项目"), service) is True
    assert _resolve_agent_loop_enabled(TurnRequest(message="找找世界模型研究进展"), service) is True


@pytest.mark.asyncio
async def test_agent_loop_falls_back_to_plain_reply_when_provider_rejects_tools() -> None:
    service = ProviderService(
        config=ProviderConfig(
            name="plain-relay",
            base_url="https://provider.example/v1",
            api_key_ref="trainer.test",
            model="plain-model",
            capabilities={"chat": True, "tools": True, "streaming": True},
        ),
        api_key="sk-test",
    )
    profile = UserProfile(long_term_goal="Understand project architecture")

    class FakeFailAgentLoop:
        def __init__(self, **_kwargs):
            pass

        async def run(self, _messages):
            return SimpleNamespace(
                final_content="",
                steps=[],
                summary=None,
                next_step=None,
                stop_reason="provider_error",
                error="HTTP 400: this model does not support tools",
                decision=None,
                blocker=None,
                teaching_note=None,
                resume_thread=None,
                confidence=None,
                evidence=[],
            )

    with (
        patch("app.llm.agent_loop.CoachAgentLoop", FakeFailAgentLoop),
        patch.object(service, "_llm_reply", AsyncMock(return_value="Plain fallback explanation works.")),
    ):
        outcome = await service.coaching_reply_agentic(
            profile,
            "Explain this project",
            response_language="en-US",
            answer_mode="direct",
        )
    assert outcome["stop_reason"] == "completed"
    assert outcome["fell_back"] is True
    assert "Plain fallback explanation works." in outcome["content"]


def test_resource_pdf_export_endpoint_returns_valid_cjk_pdf(tmp_path: Path) -> None:
    with TestClient(_offline_app(tmp_path)) as client:
        workspace_id = "ws-pdf-export"
        client.post("/session/start", json={"workspace_id": workspace_id, "workspace_name": "PDF Repo"})
        upload = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "世界模型备课简报.md",
                "source": "inline://world-model-brief.md",
                "content": "# 世界模型研究进展\n\n- 代表工作: DreamerV3\n\n```python\ndef rollout(state, action):\n    return state + action\n```\n",
                "content_encoding": "utf-8",
            },
        )
        assert upload.status_code == 200, upload.text
        resource_id = upload.json()["id"]
        idx = client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": resource_id, "enable_network": False},
        )
        assert idx.status_code == 200, idx.text

        pdf_resp = client.get(
            "/resource/export",
            params={"workspace_id": workspace_id, "resource_id": resource_id, "format": "pdf"},
        )
        assert pdf_resp.status_code == 200, pdf_resp.text
        assert "application/pdf" in pdf_resp.headers.get("content-type", "")
        assert pdf_resp.content.startswith(b"%PDF-")

        doc = pymupdf.open(stream=pdf_resp.content, filetype="pdf")
        try:
            text = "".join(page.get_text() for page in doc)
            assert "世界模型研究进展" in text
            assert "DreamerV3" in text
        finally:
            doc.close()


def test_settings_and_protocol_regressions() -> None:
    cfg = provider_config_from_payload(
        {
            "provider": {
                "name": "Local Ollama",
                "baseUrl": "http://localhost:11434/v1",
                "model": "qwen2.5-coder:7b",
                "ignoreSystemProxy": True,
            }
        }
    )
    assert cfg is not None
    assert cfg.ignore_system_proxy is True
    assert _allows_keyless_local_provider(cfg) is True

    generic_local = ProviderConfig(
        name="Private Relay",
        base_url="http://127.0.0.1:9000/v1",
        api_key_ref="",
        model="custom-model",
    )
    assert _allows_keyless_local_provider(generic_local) is False

    minimax = ProviderConfig(
        name="MiniMax",
        base_url="https://api.minimaxi.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3.1-Flash",
        protocol="openai_chat_completions_compatible",
    )
    flat = _flatten_minimax_thinking_for_raw_http(
        {"model": "MiniMax-M3.1-Flash", "extra_body": {"thinking": {"type": "disabled"}}},
        minimax,
    )
    assert flat["thinking"] == {"type": "disabled"}

    assert declared_thinking({"reasoning_effort": "high"}) == "omit"
    resolved_omit = resolve_thinking_policy({"reasoning_effort": "high"}, cfg)
    assert resolved_omit == "omit"

    gemini_payload = _format_gemini_payload(
        [
            {"role": "user", "content": "Inspect project"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "function": {"name": "list_workspace_files", "arguments": "{}"}},
                    {"id": "c2", "function": {"name": "read_workspace_file", "arguments": '{"path":"README.md"}'}},
                ],
            },
            {"role": "tool", "name": "list_workspace_files", "content": '{"ok":true}'},
            {"role": "tool", "name": "read_workspace_file", "content": '{"ok":true}'},
        ],
        None,
    )
    function_turns = [c for c in gemini_payload["contents"] if c.get("role") == "function"]
    # Parallel tool responses grouped into ONE single function content turn
    assert len(function_turns) == 1
    assert len(function_turns[0]["parts"]) == 2


def test_legacy_untested_tool_capable_profile_enables_autonomous_web_tools() -> None:
    legacy_minimax = ProviderService(
        config=ProviderConfig(
            name="MiniMax",
            base_url="https://api.minimaxi.com/v1",
            api_key_ref="trainer.minimax",
            model="MiniMax-M3.1-Flash",
            protocol="openai_chat_completions_compatible",
            capabilities={"chat": True, "tools": False, "streaming": True},
        ),
        api_key="sk-minimax",
    )
    assert _resolve_agent_loop_enabled(TurnRequest(message="你好"), legacy_minimax) is False
    assert _resolve_agent_loop_enabled(TurnRequest(message="你现在可以联网了吗"), legacy_minimax) is True
    assert (
        _resolve_agent_loop_enabled(
            TurnRequest(message="你帮我找找目前的世界模型的研究进展可以吗"),
            legacy_minimax,
        )
        is True
    )

    legacy_minimax.replace_observed_capability_states({"tools": "unsupported"})
    assert _resolve_agent_loop_enabled(TurnRequest(message="你现在可以联网了吗"), legacy_minimax) is False


def test_bogus_smalltalk_step_detection_preserves_technical_steps() -> None:
    assert is_bogus_smalltalk_step("先把 你好 压成一个很小的补丁目标，再继续写。") is True
    assert is_bogus_smalltalk_step("先把 hello 压成一个很小的补丁目标，再继续写。") is True
    assert is_bogus_smalltalk_step("围绕「你好」先做一个小动作") is True
    assert is_bogus_smalltalk_step("先把 Python 的 asyncio 压成一个很小的补丁目标，再继续写。") is False
    assert is_bogus_smalltalk_step("先打开 app.py，确认 Router 注册。") is False


def test_session_message_stream_without_use_agent_loop_does_not_409_when_unverified(tmp_path: Path) -> None:
    with TestClient(_offline_app(tmp_path)) as client:
        workspace_id = "ws-no-409"
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Chat Stream Test"},
        )
        assert started.status_code == 200
        session_id = started.json()["session_id"]

        client.app.state.runtime.provider_service = ProviderService(
            config=ProviderConfig(
                name="MiniMax",
                base_url="https://api.minimaxi.com/v1",
                api_key_ref="trainer.minimax",
                model="MiniMax-M3.1-Flash",
                protocol="openai_chat_completions_compatible",
                capabilities={"chat": True, "tools": False, "streaming": True},
            ),
            api_key="",
        )
        resp = client.post(
            "/session/message/stream",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": "你好",
            },
        )
        assert resp.status_code != 409


def test_nested_finder_group_organization_and_index(tmp_path: Path) -> None:
    with TestClient(_offline_app(tmp_path)) as client:
        workspace_id = "ws-finder-nested"
        client.post("/session/start", json={"workspace_id": workspace_id, "workspace_name": "Finder Repo"})
        upload = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "auth-flow.md",
                "source": "inline://auth-flow.md",
                "content": "# Auth Flow\nToken verification details.\n",
                "content_encoding": "utf-8",
            },
        )
        assert upload.status_code == 200, upload.text
        resource_id = upload.json()["id"]

        organized = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": resource_id,
                "action": "set_group",
                "group": "API/Auth",
            },
        )
        assert organized.status_code == 200, organized.text
        body = organized.json()
        assert body["collection_path"].startswith("Auth/")
        assert str(body["collection_root"]).replace("\\", "/").endswith("/groups/API/Auth")

        idx = client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": resource_id, "enable_network": False},
        )
        assert idx.status_code == 200, idx.text
        indexed_body = idx.json()
        assert indexed_body["collection_path"].startswith("Auth/")
        assert str(indexed_body["collection_root"]).replace("\\", "/").endswith("/groups/API/Auth")


@pytest.mark.asyncio
async def test_agent_loop_8_locale_recovery_and_prior_tool_empty_response_continuity() -> None:
    expected_blocker_prefixes = {
        "es-ES": "Bloqueo actual: ",
        "fr-FR": "Blocage actuel : ",
        "de-DE": "Aktueller Blocker: ",
        "ja-JP": "現在のブロッカー: ",
        "ko-KR": "현재 막힌 지점: ",
        "pt-BR": "Bloqueio atual: ",
    }
    english_empty_summary, english_empty_next = _build_empty_response_recovery(
        context=None, response_language="en-US"
    )
    english_no_progress, _ = _build_no_progress_recovery(
        [{"name": "web_search"}], previous_step=None, context=None, response_language="en-US"
    )
    english_step_limit, _ = _build_step_limit_recovery(
        None, context=None, response_language="en-US"
    )
    english_timeout, _ = _build_runtime_failure_recovery(
        "timeout", context=None, response_language="en-US", previous_step=None
    )
    english_cont, _ = _build_completion_continuity(
        "", context=None, response_language="en-US"
    )

    for locale, blocker_prefix in expected_blocker_prefixes.items():
        rendered = _visible_coach_finalize_reply(
            {"summary": "Summary", "blocker": "timeout"},
            response_language=locale,
        )
        assert f"{blocker_prefix}timeout" in rendered

        no_progress_sum, _ = _build_no_progress_recovery(
            [{"name": "web_search"}], previous_step=None, context=None, response_language=locale
        )
        assert no_progress_sum != english_no_progress

        step_limit_sum, _ = _build_step_limit_recovery(
            None, context=None, response_language=locale
        )
        assert step_limit_sum != english_step_limit

        timeout_sum, _ = _build_runtime_failure_recovery(
            "timeout", context=None, response_language=locale, previous_step=None
        )
        assert timeout_sum != english_timeout

        empty_sum, empty_next = _build_empty_response_recovery(
            context=None, response_language=locale
        )
        assert empty_sum != english_empty_summary
        assert empty_next != english_empty_next

        cont_sum, _ = _build_completion_continuity(
            "", context=None, response_language=locale
        )
        assert cont_sum != english_cont

    # Multi-step run & stream: prior executed tools are surfaced when the final answer is empty
    registry = ToolRegistry()

    async def _echo(_context: ToolContext, args: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "text": args.get("text", "")}

    registry.register(
        ToolDefinition(
            name="echo_check",
            description="Echo check helper.",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            handler=_echo,
        )
    )
    ctx_ja = ToolContext(
        runtime=None,
        workspace_id="ws-ja",
        session_id="sess-ja",
        response_language="ja-JP",
        extra={},
    )
    tool_step = {
        "content": "",
        "tool_calls": [{"id": "c1", "name": "echo_check", "arguments": '{"text": "ok"}'}],
    }
    run_res = await run_with_scripted_responses(
        registry=registry,
        context=ctx_ja,
        scripted_responses=[tool_step, {"content": "   ", "tool_calls": []}],
        initial_messages=[{"role": "user", "content": "確認して"}],
        max_steps=4,
    )
    assert run_res.stop_reason == "empty_response"
    assert run_res.summary and "echo_check" in run_res.summary
    assert "実行済みの確認" in run_res.summary

    stream_responses = iter(
        [
            {"content": "", "tool_calls": [{"id": "c2", "name": "echo_check", "arguments": "{}"}]},
            {"content": "", "tool_calls": []},
        ]
    )

    async def _stream_call(_messages, _tools):
        yield {"type": "final", **next(stream_responses)}

    stream_loop = CoachAgentLoop(
        provider=AgentProvider(
            protocol="openai_chat_completions",
            call=AsyncMock(return_value={"content": "", "tool_calls": []}),
            call_stream=_stream_call,
        ),
        registry=registry,
        context=ToolContext(
            runtime=None,
            workspace_id="ws-ko",
            session_id="sess-ko",
            response_language="ko-KR",
            extra={},
        ),
        max_steps=4,
    )
    events = [event async for event in stream_loop.run_stream([{"role": "user", "content": "확인해 줘"}])]
    final = next(event for event in events if event["type"] == "final")
    assert final["stop_reason"] == "empty_response"
    assert final["summary"] and "echo_check" in final["summary"]
    assert "실행된 점검" in final["summary"]


def test_smalltalk_and_exploratory_queries_across_all_8_locales() -> None:
    for greeting in ("你好", "hello", "こんにちは", "안녕하세요", "hola", "bonjour", "hallo", "olá"):
        assert is_casual_greeting_or_smalltalk(greeting) is True

    for research_prompt in (
        "你帮我找找目前的世界模型的研究进展可以吗",
        "Could you search the latest research progress on world models?",
        "このプロジェクトの構造と最新研究を調べてください",
        "이 프로젝트 구조와 최신 연구 동향을 검색해 줄 수 있나요?",
        "¿Puedes explicar la estructura de este proyecto y buscar últimos avances?",
        "Peux-tu expliquer la structure du projet et rechercher les dernières recherches ?",
        "Kannst du die Projektstruktur erklären und neueste Forschung suchen?",
        "Você pode explicar a estrutura do projeto e pesquisar novidades recentes?",
    ):
        assert is_exploratory_or_research_query(research_prompt) is True


def test_training_card_generator_8_locale_provenance_and_why_now() -> None:
    non_zh_en_locales = ("es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR")
    english_failure = CardGenerationProviderFailure("invalid_json", response_language="en-US")
    zh_failure = CardGenerationProviderFailure("invalid_json", response_language="zh-CN")
    assert "model-authored card" in english_failure.detail
    assert "模型生成的卡片" in zh_failure.detail

    english_marker, english_detail = _fallback_provenance_copy("invalid_json", "en-US")
    assert english_marker == "generation_source=deterministic_fallback;reason=invalid_json"
    assert "deterministic fallback" in english_detail

    for locale in non_zh_en_locales:
        failure = CardGenerationProviderFailure("invalid_json", response_language=locale)
        assert failure.detail != english_failure.detail
        assert failure.detail != zh_failure.detail

        localized_why = _localized_why_now(
            "conversation_gap",
            _WHY_NOW_MESSAGES["conversation_gap"],
            locale,
        )
        assert localized_why != _WHY_NOW_MESSAGES["conversation_gap"]

        marker, detail = _fallback_provenance_copy("invalid_json", locale)
        assert marker == "generation_source=deterministic_fallback;reason=invalid_json"
        assert detail != english_detail


def test_unified_library_folder_rename_and_delete_for_set_group_and_nested_resources(tmp_path: Path) -> None:
    with TestClient(_offline_app(tmp_path)) as client:
        runtime = client.app.state.runtime
        project_dir = tmp_path / "project"
        project_dir.mkdir(exist_ok=True)
        trainer_root = tmp_path / "trainer-root"
        trainer_root.mkdir(exist_ok=True)
        provisioning = runtime.provision_project_adoption(
            workspace_id="ws-unified-folder-ops",
            root_path=str(trainer_root),
            project_path=str(project_dir),
            project_name="Unified Folder Repo",
        )
        workspace_id = provisioning.context_id
        runtime.memory_service.update_workspace_state(workspace_id, workspace_trusted=True)
        runtime.workspace_authority(workspace_id)

        # 1. Top-level group via upload + set_group
        upload_top = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "world-model-notes.md",
                "source": "inline://world-model-notes.md",
                "content": "# World Models\nLatent dynamics summary.\n",
                "content_encoding": "utf-8",
            },
        )
        assert upload_top.status_code == 200, upload_top.text
        top_id = upload_top.json()["id"]

        org_top = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": top_id,
                "action": "set_group",
                "group": "WorldModels",
            },
        )
        assert org_top.status_code == 200, org_top.text

        listed_before = client.get(f"/library/groups?workspace_id={workspace_id}")
        assert listed_before.status_code == 200, listed_before.text
        groups_before = {item["path"]: item for item in listed_before.json()["groups"]}
        assert "WorldModels" in groups_before
        assert groups_before["WorldModels"]["resource_count"] >= 1

        renamed_top = client.post(
            "/library/groups/rename",
            json={
                "workspace_id": workspace_id,
                "path": "WorldModels",
                "new_path": "InfraDocs",
            },
        )
        assert renamed_top.status_code == 200, renamed_top.text
        assert renamed_top.json()["moved_resource_count"] == 1

        summary_after = client.get(f"/memory/summary?workspace_id={workspace_id}")
        assert summary_after.status_code == 200, summary_after.text
        res_map = {item["id"]: item for item in summary_after.json()["memory"]["resources"]}
        res_body = res_map[top_id]
        assert res_body["collection_path"].startswith("InfraDocs/")
        assert Path(res_body["source"]).is_file()

        listed_after = client.get(f"/library/groups?workspace_id={workspace_id}")
        assert listed_after.status_code == 200, listed_after.text
        paths_after = {item["path"] for item in listed_after.json()["groups"]}
        assert "InfraDocs" in paths_after
        assert "WorldModels" not in paths_after

        # 2. Nested child group via set_group ("InfraDocs/Auth") + parent rename ("InfraDocs" -> "CoreDocs")
        upload_nested = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "token-guard.md",
                "source": "inline://token-guard.md",
                "content": "# Token Guard\nAuth sequence.\n",
                "content_encoding": "utf-8",
            },
        )
        assert upload_nested.status_code == 200, upload_nested.text
        nested_id = upload_nested.json()["id"]

        org_nested = client.post(
            "/resource/organize",
            json={
                "workspace_id": workspace_id,
                "resource_id": nested_id,
                "action": "set_group",
                "group": "InfraDocs/Auth",
            },
        )
        assert org_nested.status_code == 200, org_nested.text

        renamed_parent = client.post(
            "/library/groups/rename",
            json={
                "workspace_id": workspace_id,
                "path": "InfraDocs",
                "new_path": "CoreDocs",
            },
        )
        assert renamed_parent.status_code == 200, renamed_parent.text
        assert renamed_parent.json()["moved_resource_count"] == 2

        summary_nested = client.get(f"/memory/summary?workspace_id={workspace_id}")
        assert summary_nested.status_code == 200, summary_nested.text
        nested_map = {item["id"]: item for item in summary_nested.json()["memory"]["resources"]}
        nested_body = nested_map[nested_id]
        assert str(nested_body["collection_root"]).replace("\\", "/").endswith("/groups/CoreDocs/Auth")
        assert nested_body["collection_path"].startswith("Auth/")
        assert Path(nested_body["source"]).is_file()

        # 3. Deleting "CoreDocs" safely moves inline-grouped files into Trainer Library/.trash/
        deleted = client.request(
            "DELETE",
            "/library/groups",
            json={"workspace_id": workspace_id, "path": "CoreDocs"},
        )
        assert deleted.status_code == 200, deleted.text
        trash_body = deleted.json()
        assert trash_body["recoverable"] is True
        trash_rel = trash_body["trash_path"]
        assert ".trash" in trash_rel
        trash_dir = trainer_root / trash_rel
        assert trash_dir.exists()
        assert list(trash_dir.rglob("*world-model-notes*.md"))
        assert list(trash_dir.rglob("*token-guard*.md"))
        summary_trashed = client.get(f"/memory/summary?workspace_id={workspace_id}")
        assert summary_trashed.status_code == 200, summary_trashed.text
        trashed_map = {item["id"]: item for item in summary_trashed.json()["memory"]["resources"]}
        assert Path(trashed_map[top_id]["source"]).is_file()
        assert Path(trashed_map[nested_id]["source"]).is_file()


def test_minimax_and_compatible_custom_thinking_budget_preserved_and_stripped() -> None:
    enabled_provider = ProviderConfig(
        name="MiniMax",
        base_url="https://api.minimaxi.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3.1-Flash",
        protocol="openai_chat_completions_compatible",
        capabilities={"chat": True, "tools": True, "thinking": True, "streaming": True},
        request_defaults={
            "reasoning_effort": "medium",
            "extra_body": {"thinking": {"type": "enabled", "budget_tokens": 8192}},
        },
    )
    normalized = _normalized_provider_request_defaults(enabled_provider)
    assert normalized["reasoning_effort"] == "medium"
    assert normalized["extra_body"]["thinking"] == {"type": "enabled", "budget_tokens": 8192}

    raw_payload = _flatten_minimax_thinking_for_raw_http(
        {
            "model": "MiniMax-M3.1-Flash",
            "reasoning_effort": "medium",
            "extra_body": {"thinking": {"type": "enabled", "budget_tokens": 8192}},
        },
        enabled_provider,
    )
    assert raw_payload["thinking"] == {"type": "enabled", "budget_tokens": 8192}
    assert "extra_body" not in raw_payload

    disabled_provider = ProviderConfig(
        name="MiniMax",
        base_url="https://api.minimaxi.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3.1-Flash",
        protocol="openai_chat_completions_compatible",
        capabilities={"chat": True, "tools": True, "thinking": False, "streaming": True},
        request_defaults={
            "extra_body": {"thinking": {"type": "disabled", "budget_tokens": 8192}},
        },
    )
    disabled_norm = _normalized_provider_request_defaults(disabled_provider)
    assert disabled_norm["extra_body"]["thinking"] == {"type": "disabled"}

    applied_disabled = apply_thinking_policy(
        {
            "reasoning_effort": "high",
            "extra_body": {"thinking": {"type": "enabled", "budget_tokens": 8192}},
        },
        "disabled",
    )
    assert applied_disabled["extra_body"]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in applied_disabled



@pytest.mark.asyncio
async def test_slow_tool_io_keeps_the_event_loop_responsive(monkeypatch, tmp_path: Path) -> None:
    """Thread identity is not enough: while a slow search or tree walk is in
    flight the loop must keep scheduling other tasks."""
    import asyncio
    import time as time_module

    import app.llm.tools as tools_module
    from app.research.web_search import WebSearchClient

    registry = build_default_tool_registry()
    runtime = SimpleNamespace(
        resolve_workspace_path=lambda _ws: str(tmp_path),
        research_network_fetch_enabled=True,
    )
    context = ToolContext(runtime=runtime, workspace_id="ws-responsive-loop", extra={})

    async def tick_fifty_times(inflight):
        for _ in range(50):
            await asyncio.sleep(0)
        return not inflight.done()

    def slow_search(self, query, limit=5):
        time_module.sleep(0.5)
        return [{"url": "https://example.com/slow", "title": "Slow", "snippet": "result"}]

    monkeypatch.setattr(WebSearchClient, "search", slow_search)
    search = asyncio.create_task(
        registry.invoke(
            context, "web_search", {"query": "slow probe", "limit": 1, "fetch_excerpts": False}
        )
    )
    search_still_running = await tick_fifty_times(search)
    searched = await asyncio.wait_for(search, timeout=10)
    assert search_still_running is True, "the event loop was blocked while the search ran"
    assert searched["ok"] is True

    def slow_walk(root, search_root, pattern, *, max_depth, limit):
        time_module.sleep(0.5)
        return [], 0

    monkeypatch.setattr(tools_module, "_walk_workspace_files", slow_walk)
    listed = asyncio.create_task(
        registry.invoke(context, "list_workspace_files", {"pattern": "**/*"})
    )
    walk_still_running = await tick_fifty_times(listed)
    walked = await asyncio.wait_for(listed, timeout=10)
    assert walk_still_running is True, "the event loop was blocked while the tree was walked"
    assert walked["ok"] is True
