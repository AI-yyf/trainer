"""Minimal MCP (Model Context Protocol) client for Trainer's coach agent.

Trainer speaks a deliberately small subset of MCP over the stdio transport so
the coach can use third-party MCP servers (Gitee, GitHub, ...) as agent tools:

* ``initialize`` (protocol negotiation + ``notifications/initialized``)
* ``tools/list`` (cursor pagination)
* ``tools/call`` (normalized text content back to the agent loop)

Design boundaries:

* **Explicit opt-in**: servers come from the ``TRAINER_MCP_SERVERS`` env var
  (a JSON array of ``{name, command, args?, env?}``). Empty/unset means MCP is
  disabled. The extension host may project VS Code workspace settings into
  that variable when it launches the sidecar.
* **Local spawn only**: Trainer executes the configured command directly on
  the sidecar machine with the ambient environment plus the per-server ``env``
  overrides. There is no remote/SSE transport in this slice.
* **Authority-gated**: every discovered tool is classified as read or write.
  Read-only tools are allowed by default (and recorded on the workspace
  operation ledger when an authority exists). Write-class tools go through the
  same permission ladder as Trainer's built-in tools
  (:class:`~app.workspace.authority.WorkspaceAuthority`), so they stay denied
  until the learner's workspace grants the matching level.
* **Honest failures**: a server that cannot start, crashes, or times out is
  recorded as ``unavailable`` with a diagnostic — never silently dropped.

Tool registration names are ``mcp_<server>_<tool>`` and reuse Trainer's normal
``ToolDefinition`` / ``ToolRegistry`` path, so results flow back to the model
as regular tool messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tools import ToolContext, ToolDefinition

logger = logging.getLogger("trainer.llm.mcp_client")

MCP_SERVERS_ENV_VAR = "TRAINER_MCP_SERVERS"
MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_CLIENT_NAME = "trainer-coach"
MCP_CLIENT_VERSION = "0.1.0"

DEFAULT_INITIALIZE_TIMEOUT_SECONDS = 10.0
DEFAULT_LIST_TIMEOUT_SECONDS = 10.0
DEFAULT_CALL_TIMEOUT_SECONDS = 30.0
DEFAULT_CLOSE_GRACE_SECONDS = 2.0
MAX_LIST_PAGES = 8
MAX_TOOLS_PER_SERVER = 256
MAX_TOOL_NAME_LENGTH = 128
MAX_TOOL_DESCRIPTION_LENGTH = 1024
MAX_DETAIL_LENGTH = 400

_NAME_SANITIZE_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")
_TOKEN_SPLIT_PATTERN = re.compile(r"[^a-z0-9]+")

_READ_TOKENS = frozenset(
    {
        "get", "list", "read", "search", "fetch", "query", "view", "show",
        "describe", "inspect", "check", "diff", "log", "status", "info",
        "lookup", "find", "resolve", "download", "export", "compare",
        "history", "blame", "tree", "content", "metadata", "summary",
    }
)
_DESTRUCTIVE_TOKENS = frozenset(
    {"delete", "remove", "destroy", "drop", "unlink", "purge", "erase"}
)
_REORGANIZE_TOKENS = frozenset({"move", "rename", "mkdir"})
_WRITE_TOKENS = frozenset(
    {
        "write", "update", "edit", "modify", "patch", "replace", "upload",
        "import", "restore", "set", "put", "apply",
    }
)
_GENERATE_TOKENS = frozenset(
    {
        "create", "add", "new", "insert", "submit", "post", "push", "merge",
        "rebase", "assign", "label", "comment", "open", "fork", "star",
        "follow", "deploy", "publish", "release", "invite", "grant", "revoke",
        "cancel", "run", "execute", "start", "stop", "restart", "trigger",
        "approve", "reject", "review", "enable", "disable", "archive",
    }
)


class McpTransportError(RuntimeError):
    """The MCP server process could not be started, died, or broke framing."""


class McpTimeoutError(McpTransportError):
    """An MCP request exceeded its deadline."""


class McpProtocolError(McpTransportError):
    """The MCP server answered a request with a JSON-RPC error object."""


# ---------------------------------------------------------------------------
# Server configuration
# ---------------------------------------------------------------------------


@dataclass
class McpServerConfig:
    """One configured MCP server (stdio transport)."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)

    def fingerprint(self) -> str:
        return json.dumps(
            {
                "name": self.name,
                "command": self.command,
                "args": list(self.args),
                "env": dict(sorted(self.env.items())),
            },
            sort_keys=True,
            ensure_ascii=True,
        )


def sanitize_mcp_token(value: object) -> str:
    """Normalize a server/tool token so it fits an agent tool name."""
    text = str(value or "").strip()
    text = _NAME_SANITIZE_PATTERN.sub("_", text)
    return text.strip("_")


def _coerce_args(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        text = raw.strip()
        return (text,) if text else ()
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(item) for item in raw if isinstance(item, (str, int, float)) and str(item))


def _coerce_env(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    env: dict[str, str] = {}
    for key, value in raw.items():
        key_text = str(key or "").strip()
        if not key_text or value is None:
            continue
        env[key_text] = str(value)
    return env


def parse_mcp_server_configs(raw: object) -> list[McpServerConfig]:
    """Validate a raw ``TRAINER_MCP_SERVERS`` payload into configs.

    Invalid entries (missing name/command, non-string shapes, duplicates) are
    skipped with a log line — an empty list means "MCP disabled".
    """
    if not isinstance(raw, list):
        if raw not in (None, ""):
            logger.warning("mcp_servers_payload_not_a_list", extra={"payload_type": type(raw).__name__})
        return []
    configs: list[McpServerConfig] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            logger.warning("mcp_server_entry_skipped", extra={"index": index, "reason": "not_an_object"})
            continue
        name = sanitize_mcp_token(item.get("name"))
        command = str(item.get("command") or "").strip()
        if not name or not command:
            logger.warning(
                "mcp_server_entry_skipped",
                extra={"index": index, "reason": "missing_name_or_command"},
            )
            continue
        if name in seen:
            logger.warning(
                "mcp_server_entry_skipped",
                extra={"index": index, "reason": "duplicate_name", "server": name},
            )
            continue
        seen.add(name)
        configs.append(
            McpServerConfig(
                name=name,
                command=command,
                args=_coerce_args(item.get("args")),
                env=_coerce_env(item.get("env")),
            )
        )
    return configs


def load_mcp_server_configs(env: Mapping[str, str] | None = None) -> list[McpServerConfig]:
    """Load MCP server configs from the environment (default: disabled)."""
    source = os.environ if env is None else env
    raw = str(source.get(MCP_SERVERS_ENV_VAR) or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("mcp_servers_payload_invalid_json")
        return []
    return parse_mcp_server_configs(payload)


# ---------------------------------------------------------------------------
# Operation classification (authority ladder mapping)
# ---------------------------------------------------------------------------


def classify_mcp_tool_operation(tool_name: str) -> str:
    """Map an MCP tool name to a workspace ``OperationType`` string.

    Fail-closed: a tool whose name carries no recognizable read verb is
    treated as a write (``write``), which the default permission ladder
    denies. Only explicit view/query verbs open the read-only fast path.
    """
    from ..workspace.authority import OperationType

    tokens = {token for token in _TOKEN_SPLIT_PATTERN.split(str(tool_name or "").lower()) if token}
    if tokens & _DESTRUCTIVE_TOKENS:
        return OperationType.DELETE
    if tokens & _REORGANIZE_TOKENS:
        return OperationType.MOVE
    if tokens & _WRITE_TOKENS:
        return OperationType.WRITE
    if tokens & _GENERATE_TOKENS:
        return OperationType.GENERATE
    if tokens & _READ_TOKENS:
        return OperationType.READ
    return OperationType.WRITE


# ---------------------------------------------------------------------------
# stdio client
# ---------------------------------------------------------------------------


class McpStdioClient:
    """One MCP server child process speaking JSON-RPC 2.0 over stdio.

    Messages are newline-delimited JSON on stdout/stdin, matching the MCP
    stdio transport. A background reader task dispatches responses to the
    futures of in-flight requests; a second task drains stderr so a chatty
    server cannot fill its pipe buffer and block.
    """

    def __init__(
        self,
        config: McpServerConfig,
        *,
        initialize_timeout: float = DEFAULT_INITIALIZE_TIMEOUT_SECONDS,
        list_timeout: float = DEFAULT_LIST_TIMEOUT_SECONDS,
        call_timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS,
        close_grace: float = DEFAULT_CLOSE_GRACE_SECONDS,
    ) -> None:
        self.config = config
        self.initialize_timeout = initialize_timeout
        self.list_timeout = list_timeout
        self.call_timeout = call_timeout
        self.close_grace = close_grace
        self.protocol_version: str | None = None
        self.server_info: dict[str, Any] = {}
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_request_id = 0
        self._send_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._closed = False
        self._disconnect_reason: str | None = None

    # -- lifecycle -----------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None and not self._closed

    @property
    def returncode(self) -> int | None:
        """Child process exit code, or None while it is alive/not started."""
        return self._process.returncode if self._process is not None else None

    async def start(self) -> None:
        """Spawn the server process and wire its pipes."""
        if self._process is not None:
            return
        env = {**os.environ, **self.config.env}
        try:
            self._process = await asyncio.create_subprocess_exec(
                self.config.command,
                *self.config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except (FileNotFoundError, PermissionError, OSError, ValueError) as exc:
            raise McpTransportError(
                f"MCP server {self.config.name!r} could not start: {exc.__class__.__name__}: {exc}"
            ) from exc
        self._reader_task = asyncio.create_task(self._read_loop(), name=f"mcp-reader-{self.config.name}")
        self._stderr_task = asyncio.create_task(self._drain_stderr(), name=f"mcp-stderr-{self.config.name}")
        logger.info("mcp_server_started", extra={"server": self.config.name})

    async def initialize(self) -> dict[str, Any]:
        """Run the MCP handshake and negotiate the protocol version."""
        result = await self.request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": MCP_CLIENT_NAME, "version": MCP_CLIENT_VERSION},
            },
            timeout=self.initialize_timeout,
        )
        payload = result if isinstance(result, dict) else {}
        server_version = str(payload.get("protocolVersion") or "").strip()
        # Best-effort negotiation: adopt the server's declared version; the
        # subset we use (initialize/tools/list/tools/call) is unchanged across
        # the revisions that shipped these methods. A server that returns
        # nothing falls back to the requested version.
        self.protocol_version = server_version or MCP_PROTOCOL_VERSION
        server_info = payload.get("serverInfo")
        self.server_info = dict(server_info) if isinstance(server_info, dict) else {}
        await self.notify("notifications/initialized", {})
        return payload

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return every tool the server exposes, following cursors."""
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _page in range(MAX_LIST_PAGES):
            params = {"cursor": cursor} if cursor else {}
            result = await self.request("tools/list", params, timeout=self.list_timeout)
            payload = result if isinstance(result, dict) else {}
            page = payload.get("tools")
            if isinstance(page, list):
                tools.extend(item for item in page if isinstance(item, dict))
            next_cursor = payload.get("nextCursor")
            cursor = str(next_cursor).strip() if isinstance(next_cursor, str) and next_cursor.strip() else None
            if cursor is None or len(tools) >= MAX_TOOLS_PER_SERVER:
                break
        return tools[:MAX_TOOLS_PER_SERVER]

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Call one tool and normalize the MCP result envelope."""
        result = await self.request(
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
            timeout=self.call_timeout if timeout is None else timeout,
        )
        payload = result if isinstance(result, dict) else {}
        return normalize_tool_call_result(payload)

    async def request(self, method: str, params: dict[str, Any], *, timeout: float) -> Any:
        process = self._process
        if self._closed or process is None or process.returncode is not None:
            raise McpTransportError(self._unavailable_detail())
        self._next_request_id += 1
        request_id = self._next_request_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = future
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        try:
            await self._send(message)
            if self._reader_task is not None and self._reader_task.done():
                # The reader already saw EOF; a future added now would never
                # be resolved. Fail fast instead of waiting out the timeout.
                raise McpTransportError(self._unavailable_detail())
            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError as exc:
                raise McpTimeoutError(
                    f"MCP request {method!r} to server {self.config.name!r} timed out after {timeout}s."
                ) from exc
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def _send(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise McpTransportError(self._unavailable_detail())
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        async with self._send_lock:
            try:
                process.stdin.write(data)
                await process.stdin.drain()
            except (OSError, RuntimeError) as exc:
                # A failed write to the child's stdin is terminal for this
                # stdio session (BrokenPipeError/ConnectionResetError are
                # OSError subclasses; Windows may surface other OSError
                # codes). Record it as a disconnect so availability checks do
                # not depend on the exit code having been reaped yet.
                detail = (
                    f"MCP server {self.config.name!r} closed its stdin: {exc.__class__.__name__}"
                )
                if self._disconnect_reason is None:
                    self._disconnect_reason = detail
                raise McpTransportError(detail) from exc

    async def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning("mcp_non_json_stdout", extra={"server": self.config.name})
                    continue
                if isinstance(message, dict):
                    self._dispatch(message)
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "mcp_reader_failed",
                extra={"server": self.config.name, "detail": exc.__class__.__name__},
            )
        finally:
            reason = "process exited" if process.returncode is not None else "stdout closed"
            self._fail_pending(f"MCP server {self.config.name!r} ended unexpectedly ({reason}).")

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            while True:
                line = await process.stderr.readline()
                if not line:
                    return
                # Keep stderr out of the client, but never let it block the child.
                logger.debug(
                    "mcp_server_stderr",
                    extra={"server": self.config.name, "line": line.decode("utf-8", errors="replace").strip()[:200]},
                )
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:  # pragma: no cover - defensive
            return

    def _dispatch(self, message: dict[str, Any]) -> None:
        response_id = message.get("id")
        if response_id is None:
            return  # notification from the server; nothing to route
        try:
            key = int(response_id)
        except (TypeError, ValueError):
            return
        future = self._pending.pop(key, None)
        if future is None or future.done():
            return
        error = message.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            text = str(error.get("message") or "").strip()
            future.set_exception(McpProtocolError(f"MCP error {code}: {text or 'unknown error'}"))
            return
        future.set_result(message.get("result"))

    def _fail_pending(self, detail: str) -> None:
        if self._disconnect_reason is None:
            self._disconnect_reason = detail
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(McpTransportError(detail))
        self._pending.clear()

    def _unavailable_detail(self) -> str:
        base = f"MCP server {self.config.name!r} is not available."
        if self._disconnect_reason:
            return f"{base} {self._disconnect_reason}"
        return base

    def availability_detail(self) -> str | None:
        """Return an honest diagnostic for an unusable session, else None."""
        if self._closed:
            return self._disconnect_reason or f"MCP server {self.config.name!r} session is closed."
        process = self._process
        if process is None:
            return f"MCP server {self.config.name!r} is not started."
        if process.returncode is not None:
            return (
                f"MCP server {self.config.name!r} exited with code {process.returncode}."
            )
        # The child reaper may not have recorded the exit code yet (notably on
        # Windows). A recorded transport disconnect already means the session
        # is unusable, so callers never receive a half-dead client.
        if self._disconnect_reason is not None:
            return self._disconnect_reason
        return None

    async def close(self) -> None:
        """Gracefully stop the child: EOF stdin, wait, terminate, kill."""
        if self._closed:
            return
        self._closed = True
        process = self._process
        self._fail_pending(f"MCP server {self.config.name!r} session was closed.")
        if process is not None:
            if process.stdin is not None and not process.stdin.is_closing():
                try:
                    process.stdin.close()
                except (OSError, RuntimeError):  # pragma: no cover - defensive
                    pass
            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), self.close_grace)
                except asyncio.TimeoutError:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), self.close_grace)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                except ProcessLookupError:  # pragma: no cover - defensive
                    pass
        current = asyncio.current_task()
        for task in (self._reader_task, self._stderr_task):
            if task is not None and task is not current:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001 - cleanup must not raise
                    pass
        self._reader_task = None
        self._stderr_task = None


def normalize_tool_call_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Flatten an MCP ``tools/call`` result into a Trainer tool payload."""
    is_error = payload.get("isError") is True
    text_parts: list[str] = []
    content = payload.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").strip().lower() != "text":
                continue
            text = item.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
    structured = payload.get("structuredContent")
    result: dict[str, Any] = {
        "ok": not is_error,
        "content": "\n".join(text_parts),
    }
    if is_error:
        result["error"] = "mcp_tool_error"
    if structured is not None:
        result["structured_content"] = structured
    return result


# ---------------------------------------------------------------------------
# Session manager (per runtime)
# ---------------------------------------------------------------------------


@dataclass
class McpServerStatus:
    """Last observed state of one configured MCP server."""

    name: str
    status: str = "unprobed"  # "unprobed" | "ok" | "unavailable"
    protocol_version: str | None = None
    tool_count: int = 0
    tool_names: list[str] = field(default_factory=list)
    detail: str | None = None

    def to_payload(self) -> dict[str, Any]:
        message = None
        if self.status == "unavailable":
            message = "MCP 服务器不可用"
        return {
            "name": self.name,
            "status": self.status,
            "protocol_version": self.protocol_version,
            "tool_count": self.tool_count,
            "tool_names": list(self.tool_names),
            "detail": self.detail,
            "message": message,
        }


class McpSessionManager:
    """Owns live MCP server sessions for one Trainer runtime.

    Sessions start lazily on first discovery and stay alive so later turns
    reuse the same process. ``refresh`` compares the config fingerprint and
    restarts everything when the configured servers change.
    """

    def __init__(
        self,
        *,
        initialize_timeout: float = DEFAULT_INITIALIZE_TIMEOUT_SECONDS,
        list_timeout: float = DEFAULT_LIST_TIMEOUT_SECONDS,
        call_timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS,
    ) -> None:
        self.initialize_timeout = initialize_timeout
        self.list_timeout = list_timeout
        self.call_timeout = call_timeout
        self._configs: dict[str, McpServerConfig] = {}
        self._sessions: dict[str, McpStdioClient] = {}
        self._tools: dict[str, list[dict[str, Any]]] = {}
        self._statuses: dict[str, McpServerStatus] = {}
        self._fingerprint: str | None = None
        self._lock = asyncio.Lock()

    # -- config lifecycle ----------------------------------------------------

    @staticmethod
    def _fingerprint_for(configs: list[McpServerConfig]) -> str:
        return "|".join(config.fingerprint() for config in configs)

    async def refresh(self, configs: list[McpServerConfig]) -> None:
        """Adopt a config list, restarting sessions when it changed."""
        fingerprint = self._fingerprint_for(configs)
        async with self._lock:
            if fingerprint == self._fingerprint:
                return
            await self._aclose_sessions_locked()
            self._configs = {config.name: config for config in configs}
            self._tools = {}
            self._statuses = {
                config.name: McpServerStatus(name=config.name) for config in configs
            }
            self._fingerprint = fingerprint

    @property
    def configs(self) -> list[McpServerConfig]:
        return list(self._configs.values())

    async def session(self, config: McpServerConfig) -> McpStdioClient | None:
        """Return a started + initialized session for ``config``, or None.

        A server whose process cannot start, exits, or cannot list tools is
        recorded as ``unavailable`` and returns ``None`` so callers never get
        a half-dead session.
        """
        async with self._lock:
            if config.name not in self._configs:
                self._configs[config.name] = config
                self._statuses.setdefault(config.name, McpServerStatus(name=config.name))
            existing = self._sessions.get(config.name)
            if existing is not None and not existing.is_running:
                await existing.close()
                self._sessions.pop(config.name, None)
                self._tools.pop(config.name, None)
                existing = None
            if existing is None:
                client = McpStdioClient(
                    config,
                    initialize_timeout=self.initialize_timeout,
                    list_timeout=self.list_timeout,
                    call_timeout=self.call_timeout,
                )
                try:
                    await client.start()
                    await client.initialize()
                except McpTransportError as exc:
                    detail = str(exc)
                    await client.close()
                    self._mark_unavailable(config.name, detail)
                    logger.warning(
                        "mcp_server_unavailable",
                        extra={"server": config.name, "detail": detail[:MAX_DETAIL_LENGTH]},
                    )
                    return None
                self._sessions[config.name] = client
                existing = client
            if config.name not in self._tools:
                tools = await self._discover_tools(existing)
                if tools is not None:
                    self._tools[config.name] = tools
                    self._mark_ok(config.name, existing, tools)
                elif existing.availability_detail() is not None:
                    # The server died during discovery; drop it so a later
                    # turn can start a fresh process.
                    self._sessions.pop(config.name, None)
                    self._tools.pop(config.name, None)
                    await existing.close()
                    return None
            return existing

    async def _discover_tools(self, client: McpStdioClient) -> list[dict[str, Any]] | None:
        try:
            return await client.list_tools()
        except McpTransportError as exc:
            detail = str(exc)
            self._mark_unavailable(client.config.name, detail)
            logger.warning(
                "mcp_tools_list_failed",
                extra={"server": client.config.name, "detail": detail[:MAX_DETAIL_LENGTH]},
            )
            return None

    def _mark_ok(self, name: str, client: McpStdioClient, tools: list[dict[str, Any]]) -> None:
        status = self._statuses.setdefault(name, McpServerStatus(name=name))
        status.status = "ok"
        status.protocol_version = client.protocol_version
        status.tool_count = len(tools)
        status.tool_names = [str(tool.get("name") or "") for tool in tools if str(tool.get("name") or "")]
        status.detail = None
        logger.info(
            "mcp_server_ready",
            extra={"server": name, "tool_count": len(tools)},
        )

    def _mark_unavailable(self, name: str, detail: str) -> None:
        status = self._statuses.setdefault(name, McpServerStatus(name=name))
        status.status = "unavailable"
        status.protocol_version = None
        status.tool_count = 0
        status.tool_names = []
        status.detail = detail[:MAX_DETAIL_LENGTH] or "MCP 服务器不可用"

    # -- tools ---------------------------------------------------------------

    def tools_for(self, server_name: str) -> list[dict[str, Any]]:
        return list(self._tools.get(server_name) or [])

    async def call(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        client = self._sessions.get(server_name)
        if client is None or not client.is_running:
            detail = (
                client.availability_detail()
                if client is not None
                else f"MCP server {server_name!r} is not connected."
            )
            self._mark_unavailable(server_name, detail or "MCP 服务器不可用")
            return {
                "ok": False,
                "error": "mcp_server_unavailable",
                "mcp_server": server_name,
                "detail": detail,
            }
        try:
            result = await client.call_tool(tool_name, arguments, timeout=timeout)
        except McpTimeoutError as exc:
            return {
                "ok": False,
                "error": "mcp_timeout",
                "mcp_server": server_name,
                "mcp_tool": tool_name,
                "detail": str(exc),
            }
        except McpTransportError as exc:
            detail = str(exc)
            self._mark_unavailable(server_name, detail)
            await self._drop_session(server_name)
            return {
                "ok": False,
                "error": "mcp_server_unavailable",
                "mcp_server": server_name,
                "mcp_tool": tool_name,
                "detail": detail,
            }
        if not isinstance(result, dict):  # pragma: no cover - defensive
            result = {"ok": True, "content": str(result)}
        return {"mcp_server": server_name, "mcp_tool": tool_name, **result}

    async def _drop_session(self, server_name: str) -> None:
        async with self._lock:
            client = self._sessions.pop(server_name, None)
            self._tools.pop(server_name, None)
        if client is not None:
            await client.close()

    # -- status --------------------------------------------------------------

    def statuses(self) -> list[McpServerStatus]:
        return [self._statuses[name] for name in self._configs if name in self._statuses]

    def status_payload(self) -> dict[str, Any]:
        statuses = self.statuses()
        return {
            "enabled": bool(self._configs),
            "config_source": MCP_SERVERS_ENV_VAR,
            "server_count": len(self._configs),
            "tool_count": sum(status.tool_count for status in statuses),
            "servers": [status.to_payload() for status in statuses],
        }

    # -- shutdown ------------------------------------------------------------

    async def _aclose_sessions_locked(self) -> None:
        clients = list(self._sessions.values())
        self._sessions = {}
        for client in clients:
            await client.close()

    async def aclose(self) -> None:
        async with self._lock:
            await self._aclose_sessions_locked()


# ---------------------------------------------------------------------------
# Runtime attachment + agent integration
# ---------------------------------------------------------------------------


def mcp_manager_for(runtime: Any) -> McpSessionManager:
    """Return (creating on first use) the runtime-owned MCP session manager."""
    manager = getattr(runtime, "mcp_session_manager", None)
    if isinstance(manager, McpSessionManager):
        return manager
    manager = McpSessionManager()
    try:
        runtime.mcp_session_manager = manager
    except (AttributeError, TypeError):  # pragma: no cover - defensive
        pass
    return manager


async def aclose_runtime_mcp_sessions(runtime: Any) -> None:
    """Best-effort shutdown used by the app lifespan."""
    manager = getattr(runtime, "mcp_session_manager", None)
    if isinstance(manager, McpSessionManager):
        try:
            await manager.aclose()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            logger.warning("mcp_shutdown_failed", exc_info=True)


def _registration_name(server_name: str, tool_name: str, used: set[str]) -> str:
    base = f"mcp_{sanitize_mcp_token(server_name)}_{sanitize_mcp_token(tool_name) or 'tool'}"
    base = base[:MAX_TOOL_NAME_LENGTH]
    candidate = base
    suffix = 2
    while candidate in used:
        suffix_text = f"_{suffix}"
        candidate = base[: MAX_TOOL_NAME_LENGTH - len(suffix_text)] + suffix_text
        suffix += 1
    used.add(candidate)
    return candidate


def _tool_parameters(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema")
    if isinstance(schema, dict) and schema:
        normalized = dict(schema)
        normalized.setdefault("type", "object")
        if normalized.get("type") == "object" and not isinstance(normalized.get("properties"), dict):
            normalized["properties"] = {}
        return normalized
    return {"type": "object", "properties": {}}


def _tool_description(server_name: str, tool: dict[str, Any]) -> str:
    raw = str(tool.get("description") or "").strip()
    if not raw:
        raw = f"MCP tool {tool.get('name')!r} from server {server_name!r}."
    provenance = (
        f"[MCP server: {server_name}. Calls run on the external MCP server and are "
        "gated by the workspace permission ladder.]"
    )
    return f"{raw[:MAX_TOOL_DESCRIPTION_LENGTH]} {provenance}"


def _gate_mcp_tool_call(
    context: ToolContext,
    *,
    server_name: str,
    tool_name: str,
    operation: str,
    arguments: dict[str, Any],
) -> dict[str, Any] | None:
    """Authority gate; returns a denial payload or None when allowed."""
    from ..workspace.authority import OperationType

    runtime = context.runtime
    authority = None
    if runtime is not None:
        try:
            authority = runtime.workspace_authority(context.workspace_id)
        except Exception:
            authority = None
    target = "mcp://{server}/{tool}".format(server=server_name, tool=tool_name)
    if operation == OperationType.READ:
        # Read-only view tools are allowed by default; record them when an
        # authority exists so the ledger stays auditable.
        if authority is not None:
            authority.log_operation(
                OperationType.READ,
                target,
                "allowed",
                details={"actor": "mcp", "server": server_name, "tool": tool_name, "arguments": arguments},
            )
        return None
    if authority is None:
        return {
            "ok": False,
            "error": "workspace_authority_unavailable",
            "detail": (
                f"MCP tool {tool_name!r} on server {server_name!r} is a write-class operation, "
                "but no workspace authority is available to approve it."
            ),
        }
    allowed = authority.check_permission(operation, authority.active_workspace_root or target)
    if allowed:
        return None
    return {
        "ok": False,
        "error": "workspace_permission_denied",
        "detail": (
            f"MCP tool {tool_name!r} on server {server_name!r} maps to workspace operation "
            f"{operation!r}, which the current permission level does not allow."
        ),
        "required_operation": operation,
        "current_permission_level": authority.permission_level.name,
    }


async def build_coach_mcp_tools(
    runtime: Any,
    workspace_id: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    configs: list[McpServerConfig] | None = None,
) -> list[ToolDefinition]:
    """Discover MCP tools and expose them as Trainer agent tools.

    Returns ``[]`` when MCP is disabled or every server is unavailable; the
    manager records per-server status either way so the settings surface can
    report honestly.
    """
    from .tools import ToolDefinition

    resolved_configs = configs if configs is not None else load_mcp_server_configs(env)
    if not resolved_configs:
        return []
    if runtime is None:
        # Without a runtime there is no persistent session owner and no
        # workspace authority to gate writes; MCP tools stay unavailable.
        logger.warning("mcp_tools_skipped_without_runtime", extra={"server_count": len(resolved_configs)})
        return []
    manager = mcp_manager_for(runtime)
    await manager.refresh(resolved_configs)
    definitions: list[ToolDefinition] = []
    used_names: set[str] = set()
    for config in resolved_configs:
        client = await manager.session(config)
        if client is None:
            continue
        for tool in manager.tools_for(config.name):
            raw_tool_name = str(tool.get("name") or "").strip()
            if not raw_tool_name:
                continue
            registration_name = _registration_name(config.name, raw_tool_name, used_names)
            operation = classify_mcp_tool_operation(raw_tool_name)

            def _make_handler(
                server_name: str,
                mcp_tool_name: str,
                tool_operation: str,
            ) -> Any:
                async def _handler(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
                    denial = _gate_mcp_tool_call(
                        context,
                        server_name=server_name,
                        tool_name=mcp_tool_name,
                        operation=tool_operation,
                        arguments=args,
                    )
                    if denial is not None:
                        return denial
                    call_manager = mcp_manager_for(context.runtime)
                    return await call_manager.call(server_name, mcp_tool_name, args)

                return _handler

            definitions.append(
                ToolDefinition(
                    name=registration_name,
                    description=_tool_description(config.name, tool),
                    parameters=_tool_parameters(tool),
                    handler=_make_handler(config.name, raw_tool_name, operation),
                )
            )
    if definitions:
        logger.info(
            "mcp_tools_registered",
            extra={
                "server_count": len(resolved_configs),
                "tool_count": len(definitions),
                "workspace_id": workspace_id,
            },
        )
    return definitions


async def probe_mcp_servers(runtime: Any, *, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Probe every configured server and return the settings-facing payload."""
    configs = load_mcp_server_configs(env)
    manager = mcp_manager_for(runtime)
    await manager.refresh(configs)
    for config in configs:
        await manager.session(config)
    return manager.status_payload()
