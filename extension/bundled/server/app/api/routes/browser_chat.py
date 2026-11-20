"""Browser chat lane: a full conversation client over the paired credential.

The Chrome side panel is a real Trainer client, not a draft form. It needs the
same session/streaming machinery as the VS Code workbench without ever seeing
the per-instance sidecar token or provider credentials. This router is a
narrow, bearer-authenticated proxy:

- every request is scoped to the credential's workspace;
- provider overrides/API keys from the browser are stripped;
- the proxy calls the existing `/session/*` routes in-process, so the coaching
  pipeline is shared rather than duplicated.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..runtime import TrainerRuntime
from ._deps import RouterDeps
from .browser import _require_browser_credential

_BROWSER_FORBIDDEN_FIELDS = frozenset(
    {
        "provider",
        "provider_config",
        "providerConfig",
        "api_key",
        "apiKey",
    }
)


def _sidecar_token(request: Request) -> str:
    return os.getenv("TRAINER_SIDECAR_TOKEN", "").strip()


def _transport(request: Request) -> httpx.ASGITransport:
    return httpx.ASGITransport(app=request.app)


def _scoped_payload(workspace_id: str, body: Any) -> dict[str, Any]:
    payload = dict(body) if isinstance(body, dict) else {}
    payload["workspace_id"] = workspace_id
    for key in _BROWSER_FORBIDDEN_FIELDS:
        payload.pop(key, None)
    return payload


def _page_context_text(body: dict[str, Any]) -> str:
    context = body.get("page_context") or body.get("pageContext")
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
        workspace_name: str = "",
    ) -> JSONResponse:
        credential = _require_browser_credential(runtime, request)
        payload: dict[str, Any] = {
            "workspace_id": credential.workspace_id,
            "workspace_name": workspace_name or credential.workspace_name or credential.workspace_id,
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
        body = await request.json()
        payload = _scoped_payload(credential.workspace_id, body)
        context = _page_context_text(payload)
        if context:
            payload["message"] = f"{str(payload.get('message') or '').strip()}\n\n{context}".strip()
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
        body = await request.json()
        payload = _scoped_payload(credential.workspace_id, body)
        payload["stream"] = True
        context = _page_context_text(payload)
        if context:
            payload["message"] = f"{str(payload.get('message') or '').strip()}\n\n{context}".strip()

        headers: dict[str, str] = {"accept": "text/event-stream"}
        token = _sidecar_token(request)
        if token:
            headers["x-trainer-token"] = token

        client = httpx.AsyncClient(
            transport=_transport(request),
            base_url="http://trainer-browser-chat",
        )
        upstream = await client.send(
            client.build_request(
                "POST",
                "/session/message/stream",
                json=payload,
                headers=headers,
            ),
            stream=True,
        )
        if upstream.status_code >= 400:
            content = await upstream.aread()
            await client.aclose()
            try:
                detail = content.decode("utf-8", errors="replace")
            except Exception:
                detail = "Browser chat stream failed."
            return JSONResponse({"detail": detail}, status_code=upstream.status_code)

        async def body_stream():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(
            body_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------------
    # Training lane: a practice answer typed in the browser is a real
    # attempt, recorded with the same honesty rules as the workbench.
    # The credential already names the workspace, so the browser never
    # chooses where the evidence lands.
    # ------------------------------------------------------------------

    @router.post("/training/attempt/start")
    async def browser_training_attempt_start(request: Request) -> JSONResponse:
        credential = _require_browser_credential(runtime, request)
        body = await request.json()
        payload = _scoped_payload(credential.workspace_id, body)
        return await proxy_json(
            request,
            method="POST",
            path="/training/attempt/start",
            workspace_id=credential.workspace_id,
            payload=payload,
        )

    @router.post("/training/attempt/update")
    async def browser_training_attempt_update(request: Request) -> JSONResponse:
        credential = _require_browser_credential(runtime, request)
        body = await request.json()
        payload = _scoped_payload(credential.workspace_id, body)
        return await proxy_json(
            request,
            method="POST",
            path="/training/attempt/update",
            workspace_id=credential.workspace_id,
            payload=payload,
        )

    @router.post("/training/attempt/evidence")
    async def browser_training_attempt_evidence(request: Request) -> JSONResponse:
        credential = _require_browser_credential(runtime, request)
        body = await request.json()
        payload = _scoped_payload(credential.workspace_id, body)
        return await proxy_json(
            request,
            method="POST",
            path="/training/attempt/evidence",
            workspace_id=credential.workspace_id,
            payload=payload,
        )

    @router.post("/training/flashcard/answer")
    async def browser_training_flashcard_answer(request: Request) -> JSONResponse:
        credential = _require_browser_credential(runtime, request)
        body = await request.json()
        payload = _scoped_payload(credential.workspace_id, body)
        return await proxy_json(
            request,
            method="POST",
            path="/training/flashcard/answer",
            workspace_id=credential.workspace_id,
            payload=payload,
        )

    @router.post("/training/practice-return")
    async def browser_training_practice_return(request: Request) -> JSONResponse:
        """A practice answered in the browser panel is a real practice return.

        The panel owns the learner's answer, so the completion travels the same
        server route the workbench uses: the server decides the evidence
        trust level (a learner return is never host-verified) and owns the
        workspace the result lands in.
        """
        credential = _require_browser_credential(runtime, request)
        body = await request.json()
        payload = _scoped_payload(credential.workspace_id, body)
        return await proxy_json(
            request,
            method="POST",
            path="/training/practice-return",
            workspace_id=credential.workspace_id,
            payload=payload,
        )

    @router.post("/cancel")
    async def browser_chat_cancel(request: Request) -> JSONResponse:
        credential = _require_browser_credential(runtime, request)
        body = await request.json()
        payload = _scoped_payload(credential.workspace_id, body)
        return await proxy_json(
            request,
            method="POST",
            path="/stream/cancel",
            workspace_id=credential.workspace_id,
            payload=payload,
        )

    return router


__all__ = ["build_browser_chat_router"]
