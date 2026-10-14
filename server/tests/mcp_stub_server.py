#!/usr/bin/env python3
"""Minimal MCP (Model Context Protocol) stdio server stub for tests.

Speaks newline-delimited JSON-RPC 2.0 on stdin/stdout and implements just the
methods Trainer's minimal client uses: ``initialize``,
``notifications/initialized``, ``tools/list``, ``tools/call``.

Modes exist to exercise failure handling in ``app.llm.mcp_client``:

* ``ok`` (default) — normal responses.
* ``garbage`` — prints a non-JSON line before ``tools/list`` so the client's
  framing tolerance can be checked.
* ``crash-after-init`` — exits with code 3 right after answering
  ``initialize`` (server dies before discovery finishes).
* ``crash-on-call`` — exits with code 4 on the first ``tools/call``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

STUB_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_repo_info",
        "description": "Return basic information about the stub repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository slug to inspect."},
            },
            "required": ["repo"],
        },
    },
    {
        "name": "list_issues",
        "description": "List open issues in the stub repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "Issue state filter."},
            },
        },
    },
    {
        "name": "create_issue",
        "description": "Create a new issue in the stub repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Issue title."},
                "body": {"type": "string", "description": "Issue body."},
            },
            "required": ["title"],
        },
    },
    {
        "name": "delete_branch",
        "description": "Delete a branch in the stub repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Branch name to delete."},
            },
            "required": ["branch"],
        },
    },
    {
        "name": "echo_env",
        "description": "Echo a test environment variable value.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "fail_tool",
        "description": "Always fails, to exercise isError handling.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _reply(request_id: Any, result: Any) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "result": result})


def _reply_error(request_id: Any, code: int, message: str) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "get_repo_info":
        repo = str(arguments.get("repo") or "unknown")
        return _text_result(f"stub repo info for {repo}")
    if name == "list_issues":
        return _text_result("issue #1: stub issue open")
    if name == "create_issue":
        title = str(arguments.get("title") or "")
        return _text_result(f"created issue: {title}")
    if name == "delete_branch":
        branch = str(arguments.get("branch") or "")
        return _text_result(f"deleted branch: {branch}")
    if name == "echo_env":
        return _text_result(str(os.environ.get("MCP_STUB_TEST_ENV", "")))
    if name == "fail_tool":
        return _text_result("stub tool failure", is_error=True)
    return _text_result(f"unknown tool: {name}", is_error=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal MCP stdio stub server")
    parser.add_argument(
        "--mode",
        default="ok",
        choices=["ok", "garbage", "crash-after-init", "crash-on-call", "paginate"],
    )
    parser.add_argument("--protocol-version", default="2025-03-26")
    parser.add_argument("--initialize-delay", type=float, default=0.0)
    parser.add_argument("--call-delay", type=float, default=0.0)
    parser.add_argument("--call-delay-tool", default="")
    args = parser.parse_args()

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        method = str(message.get("method") or "")
        request_id = message.get("id")

        if method == "initialize":
            if args.initialize_delay:
                time.sleep(args.initialize_delay)
            _reply(
                request_id,
                {
                    "protocolVersion": args.protocol_version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "stub-mcp", "version": "0.0.1"},
                },
            )
            if args.mode == "crash-after-init":
                return 3
            continue

        if method == "notifications/initialized":
            continue

        if method == "tools/list":
            if args.mode == "garbage":
                sys.stdout.write("this is not json\n")
                sys.stdout.flush()
            if args.mode == "paginate":
                params = message.get("params") if isinstance(message.get("params"), dict) else {}
                cursor = str(params.get("cursor") or "")
                split = len(STUB_TOOLS) // 2
                if cursor == "page-2":
                    _reply(request_id, {"tools": STUB_TOOLS[split:]})
                else:
                    _reply(request_id, {"tools": STUB_TOOLS[:split], "nextCursor": "page-2"})
                continue
            _reply(request_id, {"tools": STUB_TOOLS})
            continue

        if method == "tools/call":
            if args.mode == "crash-on-call":
                return 4
            params = message.get("params") if isinstance(message.get("params"), dict) else {}
            tool_name = str(params.get("name") or "")
            tool_arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            if args.call_delay and (
                not args.call_delay_tool or args.call_delay_tool == tool_name
            ):
                time.sleep(args.call_delay)
            _reply(request_id, _call_tool(tool_name, tool_arguments))
            continue

        if request_id is not None:
            _reply_error(request_id, -32601, f"Method not found: {method}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
