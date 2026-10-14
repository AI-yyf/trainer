"""Tests for the minimal MCP stdio client, tool registration, and gating.

A real python child process (``tests/mcp_stub_server.py``) implements the
minimal JSON-RPC stdio loop (initialize / tools-list / tools-call) so these
tests exercise discovery, calling, timeout, crash cleanup, and the workspace
authority ladder against actual subprocess behavior.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.mcp_client import (
    MCP_SERVERS_ENV_VAR,
    McpServerConfig,
    McpSessionManager,
    McpStdioClient,
    McpTimeoutError,
    McpTransportError,
    aclose_runtime_mcp_sessions,
    build_coach_mcp_tools,
    classify_mcp_tool_operation,
    load_mcp_server_configs,
    mcp_manager_for,
    parse_mcp_server_configs,
    probe_mcp_servers,
)
from app.llm.tools import ToolContext, build_default_tool_registry
from app.workspace.authority import PermissionLevel, WorkspaceAuthority

STUB_SERVER = Path(__file__).resolve().parent / "mcp_stub_server.py"


def stub_config(name: str = "stub", *extra_args: str, env: dict[str, str] | None = None) -> McpServerConfig:
    return McpServerConfig(
        name=name,
        command=sys.executable,
        args=(str(STUB_SERVER), *extra_args),
        env=env or {},
    )


class _FakeRuntime:
    """Minimal runtime stand-in exposing the authority accessor."""

    def __init__(self, authority: WorkspaceAuthority | None = None) -> None:
        self._authority = authority

    def workspace_authority(self, workspace_id: str | None) -> WorkspaceAuthority | None:
        return self._authority


def _context(runtime: Any, workspace_id: str = "ws-1") -> ToolContext:
    return ToolContext(runtime=runtime, workspace_id=workspace_id)


def _trusted_authority(tmp_path: Path, level: PermissionLevel = PermissionLevel.INSPECT) -> WorkspaceAuthority:
    authority = WorkspaceAuthority(root_path=str(tmp_path), initial_permission=level)
    authority.set_workspace_context(workspace_trusted=True)
    return authority


# ---------------------------------------------------------------------------
# Configuration parsing
# ---------------------------------------------------------------------------


def test_load_configs_from_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {"name": "gitee", "command": "java", "args": ["-jar", "gitee-mcp.jar"], "env": {"TOKEN": "x"}},
        {"name": "github", "command": "npx", "args": "-y github-mcp-server"},
    ]
    monkeypatch.setenv(MCP_SERVERS_ENV_VAR, json.dumps(payload))
    configs = load_mcp_server_configs()
    assert [config.name for config in configs] == ["gitee", "github"]
    assert configs[0].args == ("-jar", "gitee-mcp.jar")
    assert configs[0].env == {"TOKEN": "x"}
    # A single string arg is coerced to a one-element tuple.
    assert configs[1].args == ("-y github-mcp-server",)


def test_load_configs_default_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MCP_SERVERS_ENV_VAR, raising=False)
    assert load_mcp_server_configs() == []
    assert load_mcp_server_configs({"TRAINER_MCP_SERVERS": ""}) == []
    assert load_mcp_server_configs({"TRAINER_MCP_SERVERS": "   "}) == []


def test_load_configs_invalid_payloads_are_skipped() -> None:
    assert load_mcp_server_configs({"TRAINER_MCP_SERVERS": "{not json"}) == []
    assert load_mcp_server_configs({"TRAINER_MCP_SERVERS": json.dumps({"name": "x"})}) == []
    configs = parse_mcp_server_configs(
        [
            "not-an-object",
            {"name": "missing-command"},
            {"command": "missing-name"},
            {"name": "ok", "command": "python3"},
            {"name": "ok", "command": "python3"},  # duplicate name
        ]
    )
    assert [config.name for config in configs] == ["ok"]


def test_server_name_sanitization() -> None:
    configs = parse_mcp_server_configs([{"name": "gitee/enterprise pro", "command": "java"}])
    assert [config.name for config in configs] == ["gitee_enterprise_pro"]


# ---------------------------------------------------------------------------
# Operation classification (authority ladder mapping)
# ---------------------------------------------------------------------------


def test_classify_read_and_write_tools() -> None:
    assert classify_mcp_tool_operation("get_repo_info") == "read"
    assert classify_mcp_tool_operation("list_issues") == "read"
    assert classify_mcp_tool_operation("search_code") == "read"
    assert classify_mcp_tool_operation("create_issue") == "generate"
    assert classify_mcp_tool_operation("update_readme") == "write"
    assert classify_mcp_tool_operation("rename_widget") == "move"
    assert classify_mcp_tool_operation("delete_branch") == "delete"
    # Fail-closed: unrecognized names are treated as writes.
    assert classify_mcp_tool_operation("frobnicate") == "write"


# ---------------------------------------------------------------------------
# Discovery + calling against a real child process
# ---------------------------------------------------------------------------


async def test_discovery_call_and_protocol_negotiation() -> None:
    manager = McpSessionManager()
    config = stub_config("dev", "--protocol-version", "2025-03-26", env={"MCP_STUB_TEST_ENV": "hello-env"})
    try:
        await manager.refresh([config])
        client = await manager.session(config)
        assert client is not None
        # The client adopts the protocol version the server negotiates.
        assert client.protocol_version == "2025-03-26"

        statuses = manager.statuses()
        assert [(status.name, status.status) for status in statuses] == [("dev", "ok")]
        assert statuses[0].tool_count == 6
        assert "get_repo_info" in statuses[0].tool_names

        result = await manager.call("dev", "get_repo_info", {"repo": "trainer"})
        assert result["ok"] is True
        assert "stub repo info for trainer" in result["content"]
        assert result["mcp_server"] == "dev"

        env_result = await manager.call("dev", "echo_env", {})
        assert env_result["content"] == "hello-env"

        failure = await manager.call("dev", "fail_tool", {})
        assert failure["ok"] is False
        assert failure["error"] == "mcp_tool_error"

        # A second session call reuses the same live process.
        assert await manager.session(config) is client
    finally:
        await manager.aclose()


async def test_garbage_stdout_is_tolerated() -> None:
    manager = McpSessionManager()
    config = stub_config("garbage", "--mode", "garbage")
    try:
        await manager.refresh([config])
        client = await manager.session(config)
        assert client is not None
        result = await manager.call("garbage", "list_issues", {})
        assert result["ok"] is True
    finally:
        await manager.aclose()


async def test_tools_list_pagination_is_followed() -> None:
    manager = McpSessionManager()
    config = stub_config("paged", "--mode", "paginate")
    try:
        await manager.refresh([config])
        client = await manager.session(config)
        assert client is not None
        statuses = manager.statuses()
        assert statuses[0].tool_count == 6
        assert "delete_branch" in statuses[0].tool_names
        result = await manager.call("paged", "get_repo_info", {"repo": "trainer"})
        assert result["ok"] is True
    finally:
        await manager.aclose()


# ---------------------------------------------------------------------------
# Tool registration + workspace authority gating
# ---------------------------------------------------------------------------


async def test_build_tools_registers_prefixed_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        MCP_SERVERS_ENV_VAR,
        json.dumps([{"name": "dev", "command": sys.executable, "args": [str(STUB_SERVER)]}]),
    )
    runtime = _FakeRuntime()
    try:
        tools = await build_coach_mcp_tools(runtime, "ws-1")
        names = [tool.name for tool in tools]
        assert "mcp_dev_get_repo_info" in names
        assert "mcp_dev_create_issue" in names
        assert all(name.startswith("mcp_dev_") for name in names)

        # The MCP inputSchema is mapped to the agent tool parameters,
        # including property descriptions and required fields.
        by_name = {tool.name: tool for tool in tools}
        params = by_name["mcp_dev_get_repo_info"].parameters
        assert params["type"] == "object"
        assert params["properties"]["repo"]["description"] == "Repository slug to inspect."
        assert params["required"] == ["repo"]

        registry = build_default_tool_registry(extra_tools=tools)
        for name in names:
            assert registry.get(name) is not None
        # Built-ins still present.
        assert registry.get("search_resources") is not None
    finally:
        await aclose_runtime_mcp_sessions(runtime)


async def test_build_tools_disabled_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MCP_SERVERS_ENV_VAR, raising=False)
    assert await build_coach_mcp_tools(_FakeRuntime(), "ws-1") == []


async def test_build_tools_without_runtime_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        MCP_SERVERS_ENV_VAR,
        json.dumps([{"name": "dev", "command": sys.executable, "args": [str(STUB_SERVER)]}]),
    )
    assert await build_coach_mcp_tools(None, "ws-1") == []


async def test_read_tool_allowed_by_default_write_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        MCP_SERVERS_ENV_VAR,
        json.dumps([{"name": "dev", "command": sys.executable, "args": [str(STUB_SERVER)]}]),
    )
    authority = _trusted_authority(tmp_path, PermissionLevel.INSPECT)
    runtime = _FakeRuntime(authority)
    try:
        tools = await build_coach_mcp_tools(runtime, "ws-1")
        registry = build_default_tool_registry(extra_tools=tools)
        context = _context(runtime)

        read_result = await registry.invoke(context, "mcp_dev_get_repo_info", {"repo": "trainer"})
        assert read_result["ok"] is True
        assert "stub repo info for trainer" in read_result["content"]

        write_result = await registry.invoke(context, "mcp_dev_create_issue", {"title": "doc"})
        assert write_result["ok"] is False
        assert write_result["error"] == "workspace_permission_denied"
        assert write_result["required_operation"] == "generate"

        delete_result = await registry.invoke(context, "mcp_dev_delete_branch", {"branch": "wip"})
        assert delete_result["ok"] is False
        assert delete_result["error"] == "workspace_permission_denied"
    finally:
        await aclose_runtime_mcp_sessions(runtime)


async def test_granted_permission_opens_write_ladder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        MCP_SERVERS_ENV_VAR,
        json.dumps([{"name": "dev", "command": sys.executable, "args": [str(STUB_SERVER)]}]),
    )
    authority = _trusted_authority(tmp_path, PermissionLevel.INSPECT)
    runtime = _FakeRuntime(authority)
    try:
        tools = await build_coach_mcp_tools(runtime, "ws-1")
        registry = build_default_tool_registry(extra_tools=tools)
        context = _context(runtime)

        authority.grant_permission(PermissionLevel.GENERATE)
        create_result = await registry.invoke(context, "mcp_dev_create_issue", {"title": "doc"})
        assert create_result["ok"] is True
        assert "created issue: doc" in create_result["content"]

        delete_result = await registry.invoke(context, "mcp_dev_delete_branch", {"branch": "wip"})
        assert delete_result["ok"] is False  # delete needs DESTRUCTIVE, still denied

        authority.grant_permission(PermissionLevel.DESTRUCTIVE)
        delete_result = await registry.invoke(context, "mcp_dev_delete_branch", {"branch": "wip"})
        assert delete_result["ok"] is True
        assert "deleted branch: wip" in delete_result["content"]
    finally:
        await aclose_runtime_mcp_sessions(runtime)


async def test_untrusted_workspace_blocks_write_even_when_granted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        MCP_SERVERS_ENV_VAR,
        json.dumps([{"name": "dev", "command": sys.executable, "args": [str(STUB_SERVER)]}]),
    )
    authority = WorkspaceAuthority(root_path=str(tmp_path), initial_permission=PermissionLevel.INSPECT)
    authority.set_workspace_context(workspace_trusted=False)
    authority.grant_permission(PermissionLevel.DESTRUCTIVE)
    runtime = _FakeRuntime(authority)
    try:
        tools = await build_coach_mcp_tools(runtime, "ws-1")
        registry = build_default_tool_registry(extra_tools=tools)
        context = _context(runtime)

        write_result = await registry.invoke(context, "mcp_dev_create_issue", {"title": "doc"})
        assert write_result["ok"] is False
        assert write_result["error"] == "workspace_permission_denied"
    finally:
        await aclose_runtime_mcp_sessions(runtime)


async def test_missing_authority_allows_read_denies_write(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        MCP_SERVERS_ENV_VAR,
        json.dumps([{"name": "dev", "command": sys.executable, "args": [str(STUB_SERVER)]}]),
    )
    runtime = _FakeRuntime(authority=None)
    try:
        tools = await build_coach_mcp_tools(runtime, "ws-1")
        registry = build_default_tool_registry(extra_tools=tools)
        context = _context(runtime)

        read_result = await registry.invoke(context, "mcp_dev_list_issues", {})
        assert read_result["ok"] is True

        write_result = await registry.invoke(context, "mcp_dev_create_issue", {"title": "doc"})
        assert write_result["ok"] is False
        assert write_result["error"] == "workspace_authority_unavailable"
    finally:
        await aclose_runtime_mcp_sessions(runtime)


# ---------------------------------------------------------------------------
# Failure handling: unavailable server, timeout, crash cleanup
# ---------------------------------------------------------------------------


async def test_server_that_cannot_start_is_reported_unavailable() -> None:
    manager = McpSessionManager()
    config = McpServerConfig(name="broken", command="/nonexistent-mcp-binary-trainer-test")
    try:
        await manager.refresh([config])
        assert await manager.session(config) is None
        statuses = manager.statuses()
        assert len(statuses) == 1
        assert statuses[0].status == "unavailable"
        assert statuses[0].tool_count == 0
        payload = manager.status_payload()
        assert payload["enabled"] is True
        assert payload["servers"][0]["message"] == "MCP 服务器不可用"
        assert payload["servers"][0]["detail"]
        assert payload["tool_count"] == 0
    finally:
        await manager.aclose()


async def test_build_tools_skips_unavailable_server() -> None:
    configs = [
        McpServerConfig(name="broken", command="/nonexistent-mcp-binary-trainer-test"),
        stub_config("dev"),
    ]
    runtime = _FakeRuntime()
    try:
        tools = await build_coach_mcp_tools(runtime, "ws-1", configs=configs)
        assert tools, "the healthy server should still contribute tools"
        assert all(tool.name.startswith("mcp_dev_") for tool in tools)
        manager = mcp_manager_for(runtime)
        statuses = {status.name: status for status in manager.statuses()}
        assert statuses["broken"].status == "unavailable"
        assert statuses["dev"].status == "ok"
    finally:
        await aclose_runtime_mcp_sessions(runtime)


async def test_initialize_timeout_marks_unavailable() -> None:
    manager = McpSessionManager(initialize_timeout=0.3, list_timeout=0.3, call_timeout=0.3)
    config = stub_config("slow-init", "--mode", "ok", "--initialize-delay", "5")
    try:
        await manager.refresh([config])
        assert await manager.session(config) is None
        statuses = manager.statuses()
        assert statuses[0].status == "unavailable"
        assert "timed out" in (statuses[0].detail or "")
    finally:
        await manager.aclose()


async def test_client_initialize_timeout_reaps_process() -> None:
    client = McpStdioClient(
        stub_config("slow-init", "--mode", "ok", "--initialize-delay", "5"),
        initialize_timeout=0.3,
    )
    await client.start()
    with pytest.raises(McpTimeoutError):
        await client.initialize()
    await client.close()
    assert client.returncode is not None
    assert client.is_running is False


async def test_call_timeout_keeps_session_alive() -> None:
    manager = McpSessionManager(call_timeout=5.0)
    config = stub_config("slow-call", "--mode", "ok", "--call-delay", "0.6", "--call-delay-tool", "get_repo_info")
    try:
        await manager.refresh([config])
        client = await manager.session(config)
        assert client is not None

        slow = await manager.call("slow-call", "get_repo_info", {"repo": "x"}, timeout=0.15)
        assert slow["ok"] is False
        assert slow["error"] == "mcp_timeout"

        # The process survived the timed-out call and still answers.
        fast = await manager.call("slow-call", "list_issues", {})
        assert fast["ok"] is True
    finally:
        await manager.aclose()


async def test_crash_during_discovery_is_cleaned_up() -> None:
    client = McpStdioClient(stub_config("crasher", "--mode", "crash-after-init"))
    await client.start()
    try:
        await client.initialize()
    except McpTransportError:
        pass  # the stub may exit before the response is read; either is fine
    with pytest.raises(McpTransportError):
        await client.list_tools()
    await client.close()
    assert client.returncode is not None

    manager = McpSessionManager()
    config = stub_config("crasher", "--mode", "crash-after-init")
    try:
        await manager.refresh([config])
        assert await manager.session(config) is None
        statuses = manager.statuses()
        assert statuses[0].status == "unavailable"
        assert statuses[0].detail
    finally:
        await manager.aclose()


async def test_crash_on_call_reports_unavailable_and_session_restarts() -> None:
    manager = McpSessionManager(call_timeout=5.0)
    config = stub_config("crasher", "--mode", "crash-on-call")
    try:
        await manager.refresh([config])
        assert await manager.session(config) is not None
        result = await manager.call("crasher", "get_repo_info", {"repo": "x"})
        assert result["ok"] is False
        assert result["error"] in {"mcp_server_unavailable", "mcp_timeout"}
        statuses = manager.statuses()
        assert statuses[0].status == "unavailable"

        # A later turn starts a fresh process instead of staying dead.
        restarted = await manager.session(config)
        assert restarted is not None
        assert manager.statuses()[0].status == "ok"
    finally:
        await manager.aclose()


async def test_close_reaps_running_process() -> None:
    client = McpStdioClient(stub_config("dev"))
    await client.start()
    await client.initialize()
    process = client._process  # noqa: SLF001 - lifecycle assertion
    assert process is not None
    await client.close()
    assert client.returncode is not None
    assert not client.is_running
    await client.close()  # idempotent


# ---------------------------------------------------------------------------
# Settings visibility
# ---------------------------------------------------------------------------


async def test_probe_status_payload_reports_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        MCP_SERVERS_ENV_VAR,
        json.dumps(
            [
                {"name": "dev", "command": sys.executable, "args": [str(STUB_SERVER)]},
                {"name": "broken", "command": "/nonexistent-mcp-binary-trainer-test"},
            ]
        ),
    )
    runtime = SimpleNamespace()
    try:
        payload = await probe_mcp_servers(runtime)
        assert payload["enabled"] is True
        assert payload["server_count"] == 2
        assert payload["tool_count"] == 6
        servers = {item["name"]: item for item in payload["servers"]}
        assert servers["dev"]["status"] == "ok"
        assert servers["broken"]["status"] == "unavailable"
        assert servers["broken"]["message"] == "MCP 服务器不可用"
    finally:
        await aclose_runtime_mcp_sessions(runtime)


async def test_probe_status_payload_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MCP_SERVERS_ENV_VAR, raising=False)
    runtime = SimpleNamespace()
    payload = await probe_mcp_servers(runtime)
    assert payload == {
        "enabled": False,
        "config_source": MCP_SERVERS_ENV_VAR,
        "server_count": 0,
        "tool_count": 0,
        "servers": [],
    }
