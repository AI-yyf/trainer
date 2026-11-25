"""Browser chat lane: a full conversation client over the paired credential.

The Chrome side panel is a real Trainer client, not a draft form. It needs the
same session/streaming machinery as the VS Code workbench without ever seeing
the per-instance sidecar token or provider credentials. This router is a
narrow, bearer-authenticated proxy:

- every request is scoped to the credential's workspace;
- every proxied body is rebuilt from a per-route *allowlist*: the browser can
  send a message or answer a practice, and nothing else it sends reaches
  ``/session/*`` — no provider overrides or API keys, no ``intent``, no
  current-file content, no workspace path or file snapshot. A paired browser
  therefore cannot choose what the coach reads, where the workspace root
  points, or whether the evaluator runs;
- the proxy calls the existing ``/session/*`` routes in-process, so the coaching
  pipeline is shared rather than duplicated.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..runtime import TrainerRuntime
from ._deps import RouterDeps
from .browser import _require_browser_credential

# Kept as documentation of the invariant the allowlist enforces: these never
# travel on the browser lane, whatever a caller puts in the body.
_BROWSER_FORBIDDEN_FIELDS = frozenset(
    {
        "provider",
        "provider_config",
        "providerConfig",
        "api_key",
        "apiKey",
        "intent",
        "current_file",
        "currentFile",
        "workspace_path",
        "workspacePath",
        "workspace_context",
        "workspaceContext",
        "workspace_file_snapshot",
        "workspaceFileSnapshot",
    }
)

_MAX_BODY_BYTES = 256 * 1024
_MAX_MESSAGE_CHARS = 32_000
_MAX_ID_CHARS = 200
_MAX_NESTING_DEPTH = 4
_MAX_LIST_ITEMS = 50
_MAX_STRING_CHARS = 8_000
_LANGUAGE_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_PAGE_CONTEXT_LIMITS = {"url": 2048, "title": 160, "selection": 1200}

# Exactly what the side panel sends on each lane route. Anything else in the
# request body is dropped before it can reach the shared coaching routes.
_MESSAGE_FIELDS = ("session_id", "message", "response_language", "stream_id", "request_id")
_CANCEL_FIELDS = ("session_id", "stream_id", "request_id")
_TRAINING_FIELDS: dict[str, tuple[str, ...]] = {
    "/training/attempt/start": ("card_id", "session_id"),
    "/training/attempt/update": ("attempt_id", "card_id", "answer_draft"),
    "/training/attempt/evidence": (
        "attempt_id",
        "artifact_hash",
        "result",
        "runner_version",
        "execution_location",
        "limitations",
    ),
    "/training/flashcard/answer": (
        "card_id",
        "learner_answer",
        "selected_option_index",
        "selectedOptionIndex",
        "selected_option_indices",
        "selectedOptionIndices",
        "fill_blank_answers",
        "fillBlankAnswers",
        "sort_order",
        "sortOrder",
    ),
    "/training/practice-return": (
        "card_id",
        "passed",
        "summary",
        "next_step",
        "focus_area",
        "evidence_source",
    ),
}


class _InvalidPayload(ValueError):
    """A browser-lane body that is too large or too deeply nested."""


def _sidecar_token(request: Request) -> str:
    return os.getenv("TRAINER_SIDECAR_TOKEN", "").strip()


def _transport(request: Request) -> httpx.ASGITransport:
    return httpx.ASGITransport(app=request.app)


async def _read_json_object(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "browser_payload_too_large",
                "message": "The browser request body is too large.",
            },
        )
    try:
        body = json.loads(raw)
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _bounded_copy(value: Any, *, depth: int = 0) -> Any:
    """Deep-copy one JSON value within size limits, so a paired browser cannot
    push an unbounded structure into the shared coaching routes."""
    if depth > _MAX_NESTING_DEPTH:
        raise _InvalidPayload("nesting")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, str):
        if len(value) > _MAX_STRING_CHARS:
            raise _InvalidPayload("string")
        return value
    if isinstance(value, list):
        if len(value) > _MAX_LIST_ITEMS:
            raise _InvalidPayload("list")
        return [_bounded_copy(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > _MAX_LIST_ITEMS:
            raise _InvalidPayload("object")
        return {str(key)[:64]: _bounded_copy(item, depth=depth + 1) for key, item in value.items()}
    return None


def _browser_payload(workspace_id: str, body: Any, allowed: tuple[str, ...]) -> dict[str, Any]:
    """Rebuild a lane payload from the allowlist only.

    The credential names the workspace; every other field must be one the route
    declares. Fields outside the list — provider settings, ``intent``,
    ``current_file``, workspace paths and snapshots — are dropped here, before
    the request is proxied in-process with the sidecar's own token.
    """
    payload: dict[str, Any] = {"workspace_id": workspace_id}
    if not isinstance(body, dict):
        return payload
    try:
        for key in allowed:
            if key in body and key not in _BROWSER_FORBIDDEN_FIELDS:
                payload[key] = _bounded_copy(body[key])
    except _InvalidPayload as exc:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "browser_payload_too_large",
                "message": f"The browser request body is too large ({exc}).",
            },
        ) from exc
    for key in _BROWSER_FORBIDDEN_FIELDS:
        payload.pop(key, None)
    return payload


def _clean_page_context(value: Any) -> dict[str, str] | None:
    """The page context is three bounded strings; anything else is dropped."""
    if not isinstance(value, dict):
        return None
    context = {
        key: str(value.get(key) or "").strip()[:limit]
        for key, limit in _PAGE_CONTEXT_LIMITS.items()
        if str(value.get(key) or "").strip()
    }
    return context or None


def _normalize_message_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Type-check the conversation fields a browser may set.

    ``message`` must be text; identifiers are short strings; the language tag
    has to look like one. The browser never chooses the conversation scope:
    ``active_view`` is always the coach thread.
    """
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise HTTPException(
            status_code=422,
            detail={"code": "message_required", "message": "A message is required."},
        )
    if len(message) > _MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=413,
            detail={"code": "browser_payload_too_large", "message": "The message is too long."},
        )
    payload["message"] = message
    for key in ("session_id", "stream_id", "request_id"):
        value = payload.get(key)
        if isinstance(value, str):
            payload[key] = value.strip()[:_MAX_ID_CHARS]
        else:
            payload.pop(key, None)
    language = payload.get("response_language")
    if not (isinstance(language, str) and _LANGUAGE_TAG_RE.match(language)):
        payload.pop("response_language", None)
    context = _clean_page_context(payload.get("page_context") or payload.get("pageContext"))
    payload.pop("pageContext", None)
    if context is None:
        payload.pop("page_context", None)
    else:
        payload["page_context"] = context
    payload["active_view"] = "coach"
    return payload


def _page_context_text(payload: dict[str, Any]) -> str:
    context = payload.get("page_context")
    if not isinstance(context, dict):
        return ""
    url = str(context.get("url") or "").strip()
    title = str(context.get("title") or "").strip()
    selection = str(context.get("selection") or "").strip()
    if not url and not title and not selection:
        return ""
    lines = ["[Current web page]"]
    if title:
        lines.append(f"Title: {title}")
    if url:
        lines.append(f"URL: {url}")
    if selection:
        lines.append("Selected text:")
        lines.extend(f"> {line}" for line in selection.splitlines() if line.strip())
    return "\n".join(lines)


def build_browser_chat_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter(prefix="/browser/chat", tags=["browser-chat"])

    async def proxy_json(
        request: Request,
        *,
        method: str,
        path: str,
        workspace_id: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> JSONResponse:
        headers: dict[str, str] = {}
        token = _sidecar_token(request)
        if token:
            headers["x-trainer-token"] = token
        async with httpx.AsyncClient(
            transport=_transport(request),
            base_url="http://trainer-browser-chat",
        ) as client:
            response = await client.request(
                method,
                path,
                json=payload,
                params=params,
                headers=headers,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "browser_chat_bad_upstream", "message": str(exc)},
            ) from exc
        return JSONResponse(body, status_code=response.status_code)

    @router.get("/bootstrap")
    async def browser_chat_bootstrap(
        request: Request,
        session_id: str = "",
    ) -> JSONResponse:
        credential = _require_browser_credential(runtime, request)
        # The credential names the workspace, label included. A paired browser
        # used to be able to relabel the host's session through a query
        # parameter (uncapped text, persisted by /session/start).
        payload: dict[str, Any] = {
            "workspace_id": credential.workspace_id,
            "workspace_name": credential.workspace_name or credential.workspace_id,
        }
        if session_id:
            payload["session_id"] = session_id
        return await proxy_json(
            request,
            method="POST",
            path="/session/start",
            workspace_id=credential.workspace_id,
            payload=payload,
        )

    @router.get("/sessions")
    async def browser_chat_sessions(request: Request) -> JSONResponse:
        credential = _require_browser_credential(runtime, request)
        return await proxy_json(
            request,
            method="GET",
            path="/session/list",
            workspace_id=credential.workspace_id,
            params={"workspace_id": credential.workspace_id},
        )

    @router.get("/history")
    async def browser_chat_history(
        request: Request,
        session_id: str,
    ) -> JSONResponse:
        credential = _require_browser_credential(runtime, request)
        return await proxy_json(
            request,
            method="GET",
            path="/session/history",
            workspace_id=credential.workspace_id,
            params={
                "workspace_id": credential.workspace_id,
                "session_id": session_id,
            },
        )

    @router.post("/message")
    async def browser_chat_message(request: Request) -> JSONResponse:
        credential = _require_browser_credential(runtime, request)
        body = await _read_json_object(request)
        payload = _normalize_message_payload(
            _browser_payload(credential.workspace_id, body, _MESSAGE_FIELDS + ("page_context", "pageContext"))
        )
        context = _page_context_text(payload)
        if context:
            payload["message"] = f"{payload['message'].strip()}\n\n{context}".strip()
        return await proxy_json(
            request,
            method="POST",
            path="/session/message",
            workspace_id=credential.workspace_id,
            payload=payload,
        )

    @router.post("/message/stream")
    async def browser_chat_message_stream(request: Request) -> Any:
        credential = _require_browser_credential(runtime, request)
        body = await _read_json_object(request)
        payload = _normalize_message_payload(
            _browser_payload(credential.workspace_id, body, _MESSAGE_FIELDS + ("page_context", "pageContext"))
        )
        payload["stream"] = True
        context = _page_context_text(payload)
        if context:
            payload["message"] = f"{payload['message'].strip()}\n\n{context}".strip()

        raw_body = json.dumps(payload).encode("utf-8")
        asgi_headers: list[tuple[bytes, bytes]] = [
            (b"content-type", b"application/json"),
            (b"accept", b"text/event-stream"),
            (b"content-length", str(len(raw_body)).encode("ascii")),
        ]
        token = _sidecar_token(request)
        if token:
            asgi_headers.append((b"x-trainer-token", token.encode("utf-8")))

        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": request.scope.get("scheme", "http"),
            "path": "/session/message/stream",
            "raw_path": b"/session/message/stream",
            "query_string": b"",
            "headers": asgi_headers,
            "client": request.scope.get("client"),
            "server": request.scope.get("server"),
        }

        queue: asyncio.Queue[dict[str, Any] | Exception | None] = asyncio.Queue()
        disconnect_event = asyncio.Event()
        body_sent = False

        async def receive() -> dict[str, Any]:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            await disconnect_event.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            await queue.put(message)

        async def run_upstream() -> None:
            try:
                await request.app(scope, receive, send)
            except Exception as exc:  # noqa: BLE001
                await queue.put(exc)
            finally:
                await queue.put(None)

        upstream_task = asyncio.create_task(run_upstream())

        status_code = 500
        first = await queue.get()
        if isinstance(first, Exception):
            upstream_task.cancel()
            return JSONResponse({"detail": "Browser chat stream failed."}, status_code=500)
        if isinstance(first, dict) and first.get("type") == "http.response.start":
            status_code = int(first.get("status", 200))
        elif first is None:
            return JSONResponse({"detail": "Browser chat stream ended unexpectedly."}, status_code=502)

        if status_code >= 400:
            error_chunks: list[bytes] = []
            try:
                while True:
                    item = await queue.get()
                    if item is None or isinstance(item, Exception):
                        break
                    if item.get("type") == "http.response.body":
                        chunk = item.get("body") or b""
                        if chunk:
                            error_chunks.append(bytes(chunk))
                        if not item.get("more_body", False):
                            break
            finally:
                disconnect_event.set()
                upstream_task.cancel()
            detail = b"".join(error_chunks).decode("utf-8", errors="replace") or "Browser chat stream failed."
            return JSONResponse({"detail": detail}, status_code=status_code)

        async def body_stream():
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item
                    if item.get("type") == "http.response.body":
                        chunk = item.get("body") or b""
                        if chunk:
                            yield bytes(chunk)
                        if not item.get("more_body", False):
                            break
            finally:
                disconnect_event.set()
                if not upstream_task.done():
                    upstream_task.cancel()
                    try:
                        await upstream_task
                    except BaseException:
                        pass

        return StreamingResponse(
            body_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------------
    # Training lane: a practice answer typed in the browser is a real
    # attempt, recorded with the same honesty rules as the workbench.
    # The credential already names the workspace, so the browser never
    # chooses where the evidence lands — and it cannot hand the server a
    # file path, a verification interpreter or an execution scenario: only
    # the answer and its self-report travel.
    # ------------------------------------------------------------------

    def training_route(lane_path: str):
        allowed = _TRAINING_FIELDS[lane_path]

        async def handler(request: Request) -> JSONResponse:
            credential = _require_browser_credential(runtime, request)
            body = await _read_json_object(request)
            payload = _browser_payload(credential.workspace_id, body, allowed)
            return await proxy_json(
                request,
                method="POST",
                path=lane_path,
                workspace_id=credential.workspace_id,
                payload=payload,
            )

        return handler

    for lane_path in _TRAINING_FIELDS:
        router.add_api_route(lane_path, training_route(lane_path), methods=["POST"])

    @router.post("/cancel")
    async def browser_chat_cancel(request: Request) -> JSONResponse:
        credential = _require_browser_credential(runtime, request)
        body = await _read_json_object(request)
        payload = _browser_payload(credential.workspace_id, body, _CANCEL_FIELDS)
        return await proxy_json(
            request,
            method="POST",
            path="/stream/cancel",
            workspace_id=credential.workspace_id,
            payload=payload,
        )

    return router


__all__ = ["build_browser_chat_router"]
