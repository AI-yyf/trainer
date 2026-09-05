from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routers import (
    _attach_requested_workspace_files,
    _request_is_plan_agent_turn,
    _resolve_agent_loop_enabled,
)
from app.core.models import ProviderConfig, ResourceRecord, TurnRequest
from app.core.settings import AppSettings
from app.llm.agent_loop import CoachAgentLoop, _shrink_older_tool_history, _tool_message
from app.llm.harness import tool_output_limit
from app.llm.provider_service import ProviderService, _agent_loop_max_steps
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app
from app.sandbox.service import SandboxService


def _context(runtime: object, workspace_id: str = "workspace-sandbox-library") -> ToolContext:
    return ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id="session-sandbox-library",
        extra={"active_view": "resources", "library_sandbox_work": True},
    )


def test_default_registry_exposes_sandbox_library_tools() -> None:
    names = set(build_default_tool_registry().names())
    assert {
        "list_sandbox",
        "read_sandbox_file",
        "write_sandbox_file",
        "index_sandbox_file",
        "search_resources",
        "organize_resources",
        "import_workspace_file",
        "read_workspace_file",
        "list_workspace_files",
    }.issubset(names)


def test_library_turns_enable_the_agent_loop_when_tools_are_declared() -> None:
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
    resources_view = TurnRequest(message="整理资料库里的登录笔记", active_view="resources")
    composer = TurnRequest(
        message="Search my resources.",
        resource_composer_intent={"mode": "locate"},
    )
    coach = TurnRequest(message="Explain closures.")
    assert _resolve_agent_loop_enabled(resources_view, service) is True
    assert _resolve_agent_loop_enabled(composer, service) is True
    assert _resolve_agent_loop_enabled(coach, service) is False
    assert _resolve_agent_loop_enabled(
        TurnRequest(message="Search my resources."),
        service,
        payload={"intent": "resources"},
    ) is True
    plan_view = TurnRequest(message="调整当前阶段", active_view="plan")
    plan_intent = TurnRequest(message="讨论下一步", intent="plan")
    assert _request_is_plan_agent_turn(plan_view) is True
    assert _resolve_agent_loop_enabled(plan_view, service) is True
    assert _resolve_agent_loop_enabled(plan_intent, service) is True
    assert _agent_loop_max_steps({"active_view": "plan"}) == CoachAgentLoop.SAFETY_MAX_STEPS


def test_agent_turns_share_a_high_safety_ceiling_not_lane_budgets() -> None:
    ceiling = CoachAgentLoop.SAFETY_MAX_STEPS
    assert ceiling >= 100
    assert _agent_loop_max_steps({"library_sandbox_work": True}) == ceiling
    assert _agent_loop_max_steps({"active_view": "resources"}) == ceiling
    assert _agent_loop_max_steps({"formal_plan_mutation": True}) == ceiling
    assert _agent_loop_max_steps({"active_view": "plan"}) == ceiling
    assert _agent_loop_max_steps({}) == ceiling
    assert _agent_loop_max_steps({"library_sandbox_work": True}, requested=3) == 3


def test_agent_loop_truncates_large_tool_payloads_and_shrinks_older_history() -> None:
    huge = {"ok": True, "body": "n" * 12_000}
    message = _tool_message("call-1", "write_sandbox_file", huge)
    assert len(str(message["content"])) <= tool_output_limit("write_sandbox_file") + 20
    history = [
        _tool_message("call-old-1", "list_sandbox", {"ok": True, "items": ["a" * 5_000]}),
        _tool_message("call-old-2", "read_sandbox_file", {"ok": True, "content": "b" * 5_000}),
        _tool_message("call-old-3", "read_sandbox_file", {"ok": True, "content": "c" * 5_000}),
        _tool_message("call-new", "write_sandbox_file", {"ok": True, "path": "notes.md"}),
    ]
    _shrink_older_tool_history(history)
    assert len(str(history[0]["content"])) <= CoachAgentLoop.MAX_KEPT_TOOL_RESULT_CHARS + 20
    assert "notes.md" in str(history[3]["content"])


def test_agent_loop_stubs_oldest_tool_bodies_when_turn_history_exceeds_budget() -> None:
    history = [
        _tool_message(f"call-{index}", "read_sandbox_file", {"ok": True, "body": "x" * 4_000})
        for index in range(6)
    ]
    original_budget = CoachAgentLoop.MAX_TURN_HISTORY_CHARS
    CoachAgentLoop.MAX_TURN_HISTORY_CHARS = 12_000
    try:
        _shrink_older_tool_history(history)
    finally:
        CoachAgentLoop.MAX_TURN_HISTORY_CHARS = original_budget
    assert CoachAgentLoop.PRUNED_TOOL_RESULT_MARK in str(history[0]["content"])
    assert "xxxx" in str(history[-1]["content"])


def _remote_snapshot_context(runtime: object | None = None) -> ToolContext:
    return ToolContext(
        runtime=runtime,
        workspace_id="workspace-remote-snapshot",
        session_id="session-remote-snapshot",
        extra={
            "library_sandbox_work": True,
            "workspace_file_snapshot": {
                "is_remote": True,
                "root_uri": "vscode-remote://ssh-remote+lab/home/dev/app",
                "files": [
                    {"path": "src/auth.py", "size": 120},
                    {"path": "src/router.ts", "size": 80},
                ],
                "contents": {
                    "src/auth.py": {
                        "content": "def login():\n    return 401\n",
                        "language_id": "python",
                    }
                },
            },
        },
    )


@pytest.mark.asyncio
async def test_workspace_tools_read_and_list_from_remote_snapshot() -> None:
    registry = build_default_tool_registry()
    context = _remote_snapshot_context()
    listed = await registry.invoke(context, "list_workspace_files", {"pattern": "**/*", "limit": 20})
    assert listed["ok"] is True
    assert listed["source"] == "workspace_snapshot"
    assert any(item["path"] == "src/auth.py" for item in listed["items"])
    read = await registry.invoke(context, "read_workspace_file", {"path": "src/auth.py"})
    assert read["ok"] is True
    assert read["source"] == "workspace_snapshot"
    assert "return 401" in read["content"]
    missing_body = await registry.invoke(
        context, "read_workspace_file", {"path": "src/router.ts"}
    )
    assert missing_body["ok"] is False
    assert missing_body["error"] == "snapshot_content_unavailable"
    assert missing_body["listed"] is True
    py_only = await registry.invoke(
        context, "list_workspace_files", {"pattern": "**/*.py", "limit": 20}
    )
    assert py_only["ok"] is True
    assert any(item["path"] == "src/auth.py" for item in py_only["items"])
    assert not any(item["path"].endswith(".ts") for item in py_only["items"])


@pytest.mark.asyncio
async def test_import_workspace_file_copies_remote_snapshot_into_local_library(tmp_path: Path) -> None:
    workspace_id = "workspace-remote-import"
    project = tmp_path / "remote-project"
    project.mkdir()
    sandbox = SandboxService(
        data_root=tmp_path / "data",
        workspace_path_resolver=lambda _workspace_id: str(project),
        workspace_authority_resolver=lambda _workspace_id: None,
    )
    runtime = SimpleNamespace(
        sandbox_service=sandbox,
        resource_service=None,
        repository=SimpleNamespace(list_resources=lambda _workspace_id: [], save_resource=lambda *_args: None),
        resolve_workspace_path=lambda _workspace_id: "/home/dev/app",
        postprocess_indexed_resource=None,
    )
    context = _remote_snapshot_context(runtime)
    context.workspace_id = workspace_id
    registry = build_default_tool_registry()
    imported = await registry.invoke(context, "import_workspace_file", {"path": "src/auth.py"})
    assert imported["ok"] is True
    assert imported["imported"] is True
    assert imported["sandbox_path"] == "sources/workspace/src/auth.py"
    written = sandbox.ensure_workspace_root(workspace_id) / "sources" / "workspace" / "src" / "auth.py"
    assert written.read_text(encoding="utf-8") == "def login():\n    return 401\n"
    assert not (project / "src" / "auth.py").exists()


@pytest.mark.asyncio
async def test_missing_snapshot_body_is_requested_then_importable_on_next_snapshot(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-remote-snapshot"
    remote_path = "/home/dev/app"
    settings = AppSettings(
        app_name="Trainer remote snapshot",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "sidecar-data",
        database_name="trainer-remote-snapshot.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    with TestClient(create_app(settings)) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "remote app",
                "workspace_path": remote_path,
                "remote_name": "ssh-remote",
                "force_new": True,
                "workspace_file_snapshot": {
                    "is_remote": True,
                    "files": [
                        {"path": "src/auth.py"},
                        {"path": "src/router.ts"},
                    ],
                    "contents": {
                        "src/auth.py": {
                            "content": "def login():\n    return 401\n",
                            "language_id": "python",
                        }
                    },
                },
            },
        )
        assert started.status_code == 200, started.text
        runtime = client.app.state.runtime
        session_id = started.json().get("session_id") or started.json().get("sessionId")
        context = _remote_snapshot_context(runtime)
        context.workspace_id = workspace_id
        context.session_id = str(session_id or "session-remote-snapshot")
        registry = build_default_tool_registry()

        missing = await registry.invoke(context, "read_workspace_file", {"path": "src/router.ts"})
        assert missing["ok"] is False
        assert missing["error"] == "snapshot_content_unavailable"
        assert runtime.requested_workspace_file_paths(workspace_id) == ["src/router.ts"]
        stamped = _attach_requested_workspace_files({}, runtime, workspace_id)
        assert stamped["requested_workspace_files"] == ["src/router.ts"]

        blocked = await registry.invoke(context, "import_workspace_file", {"path": "src/router.ts"})
        assert blocked["ok"] is False
        assert blocked["error"] == "snapshot_content_unavailable"

        snapshot = dict(context.extra["workspace_file_snapshot"])
        contents = dict(snapshot["contents"])
        contents["src/router.ts"] = {"content": "export const ok = true;\n", "language_id": "typescript"}
        snapshot["contents"] = contents
        context.extra["workspace_file_snapshot"] = snapshot

        imported = await registry.invoke(context, "import_workspace_file", {"path": "src/router.ts"})
        assert imported["ok"] is True
        dest = runtime.sandbox_service.ensure_workspace_root(workspace_id) / "sources" / "workspace" / "src" / "router.ts"
        assert dest.is_file()
        assert "export const ok" in dest.read_text(encoding="utf-8")
        assert runtime.requested_workspace_file_paths(workspace_id) == []
        assert Path(remote_path).exists() is False


def test_remote_snapshot_enables_the_agent_loop() -> None:
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
    request = TurnRequest(message="Explain this remote auth helper.")
    request.workspace_file_snapshot = {"is_remote": True, "files": [{"path": "src/auth.py"}]}
    assert _resolve_agent_loop_enabled(request, service) is True


@pytest.mark.asyncio
async def test_sandbox_library_tools_write_read_and_never_touch_project(tmp_path: Path) -> None:
    workspace_id = "workspace-sandbox-write"
    project = tmp_path / "project"
    project.mkdir()
    sentinel = project / "user-project.txt"
    sentinel.write_text("project-owned", encoding="utf-8")
    sandbox = SandboxService(
        data_root=tmp_path / "data",
        workspace_path_resolver=lambda _workspace_id: str(project),
    )
    runtime = SimpleNamespace(
        sandbox_service=sandbox,
        resource_service=None,
        repository=SimpleNamespace(list_resources=lambda _workspace_id: [], save_resource=lambda *_args: None),
        resolve_workspace_path=lambda _workspace_id: str(project),
        postprocess_indexed_resource=None,
    )
    registry = build_default_tool_registry()
    context = _context(runtime, workspace_id)
    written = await registry.invoke(
        context,
        "write_sandbox_file",
        {"path": "notes/login-errors.md", "content": "Map the login error to the real return code."},
    )
    assert written["ok"] is True
    assert written["written"] is True
    listed = await registry.invoke(context, "list_sandbox", {"limit": 40})
    assert listed["ok"] is True
    paths = {item["path"] for item in listed["items"]}
    assert any(path.endswith("login-errors.md") for path in paths)
    read = await registry.invoke(
        context,
        "read_sandbox_file",
        {"path": "notes/login-errors.md"},
    )
    assert read["ok"] is True
    assert "real return code" in str(read.get("content") or "")
    assert sentinel.read_text(encoding="utf-8") == "project-owned"
    escaped = await registry.invoke(
        context,
        "write_sandbox_file",
        {"path": "../escape.md", "content": "nope"},
    )
    assert escaped["ok"] is False
    assert escaped["error"] == "invalid_path"


@pytest.mark.asyncio
async def test_index_sandbox_file_registers_library_record_and_search_finds_it(tmp_path: Path) -> None:
    workspace_id = "workspace-sandbox-index"
    settings = AppSettings(
        app_name="Trainer sandbox library agent",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-sandbox-library.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Sandbox library"},
        )
        assert started.status_code == 200, started.text
        runtime = app.state.runtime
        registry = build_default_tool_registry()
        context = ToolContext(
            runtime=runtime,
            workspace_id=workspace_id,
            session_id=started.json()["session_id"],
            extra={"active_view": "resources", "library_sandbox_work": True},
        )
        written = await registry.invoke(
            context,
            "write_sandbox_file",
            {
                "path": "archive/unique-token-9912.md",
                "content": "unique-token-9912 login error mapping notes",
            },
        )
        assert written["ok"] is True
        indexed = await registry.invoke(
            context,
            "index_sandbox_file",
            {"path": "archive/unique-token-9912.md", "name": "Login error notes"},
        )
        assert indexed["ok"] is True, indexed
        assert indexed["committed"] is True
        resource_id = str(indexed.get("resource_id") or "")
        assert resource_id
        stored = runtime.repository.get_resource(workspace_id, resource_id)
        assert stored is not None
        assert stored.sandbox_path
        assert Path(stored.sandbox_path).name.endswith("unique-token-9912.md") or "unique-token-9912" in str(
            stored.sandbox_path
        )
        search = client.post(
            "/resource/search",
            json={"workspace_id": workspace_id, "query": "unique-token-9912"},
        )
        assert search.status_code == 200, search.text
        hits = search.json().get("hits") or search.json().get("results") or []
        assert any(str(item.get("resource_id") or item.get("id") or "") == resource_id for item in hits)

        rewritten = await registry.invoke(
            context,
            "write_sandbox_file",
            {
                "path": "archive/unique-token-9912.md",
                "content": "unique-token-9912 updated: wrong password shows the real code.",
            },
        )
        assert rewritten["ok"] is True
        assert (rewritten.get("library") or {}).get("reindexed") is True
        search_after = client.post(
            "/resource/search",
            json={"workspace_id": workspace_id, "query": "wrong password"},
        )
        assert search_after.status_code == 200, search_after.text
        hits_after = search_after.json().get("hits") or search_after.json().get("results") or []
        assert any(str(item.get("resource_id") or item.get("id") or "") == resource_id for item in hits_after)


@pytest.mark.asyncio
async def test_write_sandbox_file_updates_existing_library_record(tmp_path: Path) -> None:
    sandbox = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-sandbox-reindex"
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "notes.md"
    source.write_text("old notes", encoding="utf-8")
    stored = [
        ResourceRecord(
            id="resource-notes",
            kind="markdown",
            name="notes.md",
            source=str(source),
            summary="old notes",
            parse_status="parsed",
            index_status="indexed",
            sandbox_path=str(source.resolve()),
        )
    ]

    class _ResourceService:
        def index(self, _workspace_id: str, request: object) -> ResourceRecord:
            stored[0] = stored[0].model_copy(
                update={"summary": "Map the login error to the real return code."}
            )
            return stored[0]

    runtime = SimpleNamespace(
        sandbox_service=sandbox,
        resource_service=_ResourceService(),
        repository=SimpleNamespace(
            list_resources=lambda _workspace_id: list(stored),
            save_resource=lambda _workspace_id, resource: stored.__setitem__(0, resource),
        ),
        resolve_workspace_path=lambda _workspace_id: None,
        postprocess_indexed_resource=None,
    )
    result = await build_default_tool_registry().invoke(
        _context(runtime, workspace_id),
        "write_sandbox_file",
        {"path": "notes.md", "content": "Map the login error to the real return code."},
    )
    assert result["ok"] is True
    assert result["library"]["reindexed"] is True
    assert "real return code" in (root / "notes.md").read_text(encoding="utf-8")
