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
from app.llm.provider.capability import (
    _allows_keyless_local_provider,
    _flatten_minimax_thinking_for_raw_http,
)
from app.llm.provider.thinking import (
    declared_thinking,
    resolve_thinking_policy,
)
from app.llm.provider_service import ProviderService
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app
from app.memory.note_request import message_requests_lecture_note_save
from app.network_fetch import ControlledFetchResponse
from app.pedagogy.service import PedagogyService
from app.pedagogy.smalltalk import is_bogus_smalltalk_step
from app.sandbox.service import SandboxService


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
