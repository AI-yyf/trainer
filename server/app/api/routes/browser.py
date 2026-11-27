"""Browser capture lane: pairing, status and the coach-draft queue.

The Trainer Capture browser extension authenticates with the Bearer credential
it redeemed from a host-registered pairing code (see ``app.browser_bridge``);
the host itself talks to ``/browser/pair-code`` on the regular trusted loopback
boundary. Route-level behavior:

- ``POST /browser/pair-code``      host registers a 6-digit, single-use code;
- ``POST /browser/pair``           browser exchanges the code for a credential
                                   (and its extension origin becomes trusted
                                   for zero-code re-pairing);
- ``POST /browser/auto-pair``      zero-code pairing, only for an extension
                                   origin that already redeemed a code here, or
                                   for a caller proving the instance token;
- ``DELETE /browser/pair``         revoke (Bearer = that credential; no Bearer =
                                   the host retires every pairing and forgets
                                   the trusted origins);
- ``GET  /browser/status``         workspace name, learning-focus options and
                                   the library count for the paired workspace;
- ``POST /browser/coach-draft``    queue a prefilled coach draft (selection);
- ``GET  /browser/pending-drafts`` host polls queued drafts (host-facing:
                                   trusted loopback / instance token, and an
                                   explicit workspace reference is required);
- ``POST /browser/pending-drafts/ack`` host acks the drafts it forwarded (same
                                   host-facing boundary);
- ``GET  /browser/library-revision`` host polls a cheap library fingerprint so
                                   browser captures refresh the live snapshot.

The browser extension never reads the pending queue — the host is its only
consumer — so the two queue routes do not take a Bearer credential. They are
strictly workspace-scoped: a caller that does not state which workspace it is
polling for gets an error, never another project's captures.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...browser_bridge import BrowserBridgeService, BrowserCredential, BrowserPairingError
from ...browser_bridge.service import normalize_extension_origin
from ...core.event_ledger import EVENT_BROWSER_SOURCE_RECEIVED
from ...resources.library import LibraryService
from ..runtime import TrainerRuntime
from ._deps import RouterDeps

logger = logging.getLogger(__name__)


def _browser_bridge(runtime: TrainerRuntime) -> BrowserBridgeService:
    service = getattr(runtime, "browser_bridge", None)
    if not isinstance(service, BrowserBridgeService):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "browser_lane_unavailable",
                "message": "The browser capture lane is not available in this sidecar.",
            },
        )
    return service


def _bearer_token(request: Request) -> str:
    header = str(request.headers.get("authorization") or "").strip()
    if not header:
        return ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()



class HostFocusRequest(BaseModel):
    workspace_id: str = ""


def _loopback_request(request: Request) -> bool:
    client = getattr(request, "client", None)
    host = str(getattr(client, "host", "") or "").strip().lower()
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _instance_token_proven(request: Request) -> bool:
    """True when the caller proves the per-instance token.

    Only the host and native tooling on this machine hold it; a browser
    extension never does. A sidecar started without a token (manual dev launch)
    has nothing to prove, so nobody passes this check there.
    """
    expected = str(getattr(request.app.state, "instance_token", "") or "").strip()
    if not expected:
        return False
    presented = str(request.headers.get("x-trainer-token") or "")
    return bool(presented) and secrets.compare_digest(presented, expected)


def _auto_pair_refusal(request: Request, bridge: BrowserBridgeService) -> tuple[str, str] | None:
    """Why a zero-code pairing caller is refused, or ``None`` when it may pair.

    A web page always sends its own ``Origin`` and a browser refuses to let a
    page or an extension choose another one, so the origin is trustworthy: a
    non-extension origin is refused outright, and an extension origin is
    honoured only after it redeemed a pairing code on this sidecar. A request
    with no ``Origin`` is not a browser; it has to prove the instance token.
    """
    origin = str(request.headers.get("origin") or "").strip()
    if not origin:
        if _instance_token_proven(request):
            return None
        return (
            "extension_origin_required",
            "Automatic pairing is only available to a paired browser extension.",
        )
    if not normalize_extension_origin(origin):
        return (
            "extension_origin_required",
            "Automatic pairing is only available to a browser extension.",
        )
    if bridge.is_trusted_extension_origin(origin):
        return None
    return (
        "extension_not_paired",
        "Pair this browser once with a pairing code from Trainer; it reconnects on its own afterwards.",
    )


def _require_auto_pair_caller(request: Request, bridge: BrowserBridgeService) -> None:
    if not _loopback_request(request):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "loopback_only",
                "message": "Automatic browser pairing is only available on the local machine.",
            },
        )
    refusal = _auto_pair_refusal(request, bridge)
    if refusal is not None:
        raise HTTPException(
            status_code=403,
            detail={"code": refusal[0], "message": refusal[1]},
        )


def _require_browser_credential(
    runtime: TrainerRuntime,
    request: Request,
) -> BrowserCredential:
    token = _bearer_token(request)
    credential = _browser_bridge(runtime).credential_for_token(token) if token else None
    if credential is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "invalid_credential",
                "message": "Pair the Trainer Capture extension again — this credential is missing, invalid or revoked.",
            },
        )
    return credential


def _workspace_display_name(runtime: TrainerRuntime, workspace_id: str, fallback: str) -> str:
    normalized = str(fallback or "").strip()
    if normalized and normalized != workspace_id:
        return normalized
    for state in runtime.sessions.values():
        if state.workspace_id == workspace_id and str(state.workspace_name or "").strip():
            return str(state.workspace_name).strip()
    return normalized or workspace_id


def _focus_options(runtime: TrainerRuntime, workspace_id: str) -> list[dict[str, str]]:
    """Learning-focus options reuse the plan stages as the focus structure.

    A stage is exactly what the coach treats as the learner's current focus, so
    the browser binding writes the captured resource onto that stage instead of
    inventing a parallel focus registry.
    """

    plan = runtime.repository.get_latest_plan(workspace_id)
    if plan is None:
        return []
    options: list[dict[str, str]] = []
    for stage in plan.stages:
        stage_id = str(stage.id or "").strip()
        label = " ".join(str(stage.title or "").split())
        if stage_id and label:
            options.append({"id": stage_id, "label": label})
    return options


def build_browser_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter(tags=["browser"])

    current_workspace_id = deps.current_workspace_id
    effective_response_language = deps.effective_response_language

    @router.post("/browser/pair-code")
    def register_pair_code(payload: dict[str, Any]) -> dict[str, object]:
        """Host-side registration of the pairing code shown in the workbench."""

        body = payload if isinstance(payload, dict) else {}
        workspace_id = current_workspace_id(
            session_id=str(body.get("session_id") or body.get("sessionId") or "").strip() or None,
            workspace_id=str(body.get("workspace_id") or body.get("workspaceId") or "").strip()
            or None,
        )
        workspace_name = str(
            body.get("workspace_name") or body.get("workspaceName") or ""
        ).strip()
        if not workspace_name:
            for state in runtime.sessions.values():
                if state.workspace_id == workspace_id:
                    workspace_name = str(state.workspace_name or "").strip()
                    break
        bridge = _browser_bridge(runtime)
        try:
            registration = bridge.register_pair_code(
                code=str(body.get("code") or ""),
                workspace_id=workspace_id,
                workspace_name=workspace_name or workspace_id,
                expires_in=body.get("expires_in", body.get("expiresIn")),
            )
        except BrowserPairingError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc
        return registration.as_payload()

    @router.post("/browser/pair")
    def exchange_pair_code(request: Request, payload: dict[str, Any]) -> dict[str, object]:
        """Browser-side redemption: one code becomes one long-lived credential.

        The redeeming browser extension's origin is remembered, which is what
        lets the same extension pair without a code next time.
        """

        body = payload if isinstance(payload, dict) else {}
        bridge = _browser_bridge(runtime)
        try:
            credential, token = bridge.exchange_pair_code(
                str(body.get("code") or body.get("pairing_code") or ""),
                origin=str(request.headers.get("origin") or ""),
            )
        except BrowserPairingError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc
        # The raw token is returned exactly once (only its hash is persisted).
        return credential.as_payload(credential=token)

    @router.delete("/browser/pair")
    def revoke_pairing(request: Request) -> dict[str, object]:
        """Revoke a credential (Bearer) or retire the latest host registration."""

        bridge = _browser_bridge(runtime)
        token = _bearer_token(request)
        if token:
            credential = bridge.credential_for_token(token, touch=False)
            if credential is None:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "code": "invalid_credential",
                        "message": "This credential does not exist (it may already be revoked).",
                    },
                )
            bridge.revoke_token(token)
            return {"revoked": True, "had_registration": True, "credentials_revoked": 1}
        return bridge.revoke_registered_pairing()

    @router.post("/browser/auto-pair")
    def auto_pair(request: Request) -> dict[str, object]:
        """Zero-code pairing: the extension re-discovers the loopback sidecar.

        The extension calls this whenever it has no working credential (first
        use after a code pairing, or after a sidecar restart). The credential is
        bound to the workspace of the latest host session, so the browser never
        has to ask the learner for a port, URL or token again.
        """
        bridge = _browser_bridge(runtime)
        _require_auto_pair_caller(request, bridge)
        latest = runtime.latest_session()
        if latest is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "no_workspace",
                    "message": "Open Trainer in VS Code first; the browser extension connects automatically.",
                },
            )
        workspace_id = latest.workspace_id
        workspace_name = _workspace_display_name(runtime, workspace_id, "")
        origin_authorized = not _instance_token_proven(request)
        try:
            credential, token = bridge.issue_auto_credential(
                workspace_id=workspace_id,
                workspace_name=workspace_name,
                extension_origin=(
                    str(request.headers.get("origin") or "").strip() if origin_authorized else ""
                ),
            )
        except BrowserPairingError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc
        return credential.as_payload(credential=token)

    @router.post("/browser/host-focus")
    def host_focus(body: HostFocusRequest) -> dict[str, object]:
        """Record which Trainer window currently has the learner's focus.

        Host-facing (instance token); the browser lane never calls it. The
        timestamp lets the extension choose the right sidecar when several VS
        Code windows are open.
        """
        bridge = _browser_bridge(runtime)
        try:
            focused_at = bridge.mark_host_focus(body.workspace_id)
        except BrowserPairingError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc
        return {"ok": True, "focused_at": focused_at}

    @router.get("/browser/auto-pair/candidates")
    def auto_pair_candidates(request: Request) -> dict[str, object]:
        """One candidate per sidecar, used to rank auto-pair targets.

        The candidate carries the workspace name, so it is gated exactly like
        the mint itself.
        """
        bridge = _browser_bridge(runtime)
        _require_auto_pair_caller(request, bridge)
        latest = runtime.latest_session()
        if latest is None:
            return {
                "workspace_id": "",
                "workspace_name": "",
                "has_session": False,
                "last_host_focus_at": "",
            }
        return {
            "workspace_id": latest.workspace_id,
            "workspace_name": _workspace_display_name(runtime, latest.workspace_id, ""),
            "has_session": True,
            "last_host_focus_at": bridge.host_focus_for(latest.workspace_id),
        }

    def download_target(workspace_id: str) -> str:
        """Where a browser download belongs: the library root.

        The download always lands in the library root, so every capture shows
        up in one place instead of being scattered over per-project folders.
        The popup never asks the learner for a path.
        """

        managed_root = "Trainer Library"
        try:
            library = LibraryService(
                runtime.repository,
                workspace_authority_resolver=runtime.library_carrier_authority,
                inline_resource_root_resolver=runtime.resource_service._inline_resource_root,
            )
            groups = library.list_groups(workspace_id)
            managed_root = str(groups.managed_root or managed_root)
        except Exception:
            logger.debug("Could not resolve the browser download target", exc_info=True)
        return managed_root

    @router.get("/browser/status")
    def browser_status(request: Request) -> dict[str, object]:
        credential = _require_browser_credential(runtime, request)
        workspace_id = credential.workspace_id
        try:
            library_count = len(runtime.repository.list_resources(workspace_id))
        except Exception:
            library_count = 0
        return {
            "workspace_id": workspace_id,
            "workspace_name": _workspace_display_name(
                runtime,
                workspace_id,
                credential.workspace_name,
            ),
            "focus_options": _focus_options(runtime, workspace_id),
            "library_count": library_count,
            "download_target": download_target(workspace_id),
        }

    @router.post("/browser/coach-draft")
    def create_coach_draft(request: Request, payload: dict[str, Any]) -> dict[str, object]:
        credential = _require_browser_credential(runtime, request)
        body = payload if isinstance(payload, dict) else {}
        # A selection without a workspace language still gets a natural draft
        # language: CJK selections read as zh-CN, everything else falls back to
        # English (the same heuristic the coach uses for replies).
        language = effective_response_language(
            credential.workspace_id,
            None,
            str(body.get("selection") or ""),
        )
        bridge = _browser_bridge(runtime)
        try:
            queued = bridge.enqueue_draft(
                workspace_id=credential.workspace_id,
                selection=str(body.get("selection") or ""),
                url=str(body.get("url") or ""),
                title=str(body.get("title") or ""),
                client_id=str(body.get("client_id") or body.get("clientId") or ""),
                language=str(language) if language else None,
                # Ask Trainer (P4): the learner's own question replaces the
                # default ask line in the staged draft; the source kind tells
                # Trainer whether the page is a PDF document or a GitHub repo.
                question=str(body.get("question") or body.get("learner_question") or ""),
                source_kind=str(body.get("source_kind") or body.get("sourceKind") or ""),
            )
        except BrowserPairingError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc
        draft_id = str(queued.get("draft_id") or "")
        if draft_id and not queued.get("duplicate") and runtime.event_ledger is not None:
            try:
                runtime.event_ledger.record_event(
                    EVENT_BROWSER_SOURCE_RECEIVED, actor="learner", scope="resources",
                    project_id=credential.workspace_id, idempotency_key=f"browser-source:{draft_id}",
                    payload_ref={"draft_id": draft_id},
                )
            except Exception:
                logger.exception("Could not record browser intake in the event ledger")
        return {"workspace_id": credential.workspace_id, **queued}

    def host_workspace_scope(raw_workspace_id: object, raw_session_id: object) -> str:
        """The workspace a host-facing queue call is scoped to.

        The host always knows its runtime workspace id; a call without one is
        refused instead of being guessed from the latest session, because
        guessing is exactly how one project's captures would surface in
        another project's coach.
        """

        workspace_id = str(raw_workspace_id or "").strip()
        session_id = str(raw_session_id or "").strip()
        if not workspace_id and not session_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "workspace_required",
                    "message": "Pending drafts are workspace-scoped: pass workspace_id or session_id.",
                },
            )
        return current_workspace_id(
            session_id=session_id or None,
            workspace_id=workspace_id or None,
        )

    def compute_library_revision(scope: str, requested_workspace_id: str) -> dict[str, object]:
        resources = runtime.repository.list_resources(scope)
        resource_ids = sorted({str(resource.id) for resource in resources})
        revision = (
            hashlib.sha1("\n".join(resource_ids).encode("utf-8")).hexdigest()[:16]
            if resource_ids
            else ""
        )
        return {
            "workspace_id": scope,
            "requested_workspace_id": requested_workspace_id,
            "count": len(resource_ids),
            "revision": revision,
        }

    @router.get("/browser/library-revision")
    def library_revision(
        workspace_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """Host fingerprint of the workspace library."""

        scope = host_workspace_scope(workspace_id, session_id)
        return compute_library_revision(scope, str(workspace_id or "").strip())

    @router.get("/browser/pending-drafts")
    def list_pending_drafts(
        workspace_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """Host read: only the drafts captured for the polling workspace."""

        scope = host_workspace_scope(workspace_id, session_id)
        return {"workspace_id": scope, "drafts": _browser_bridge(runtime).pending_drafts(scope)}

    @router.post("/browser/pending-drafts/ack")
    def acknowledge_pending_drafts(payload: dict[str, Any]) -> dict[str, object]:
        """Host ack: drop only drafts that belong to the acking workspace."""

        body = payload if isinstance(payload, dict) else {}
        scope = host_workspace_scope(
            body.get("workspace_id", body.get("workspaceId")),
            body.get("session_id", body.get("sessionId")),
        )
        raw_ids = body.get("ids")
        ids = [str(item) for item in raw_ids] if isinstance(raw_ids, list) else []
        removed = _browser_bridge(runtime).ack_drafts(scope, ids)
        return {"ok": True, "workspace_id": scope, "removed": removed}

    @router.get("/browser/events/stream")
    async def browser_events_stream(
        request: Request,
        workspace_id: str | None = None,
        session_id: str | None = None,
        once: bool = False,
        max_events: int | None = None,
    ) -> StreamingResponse:
        """Real-time host SSE push for queued drafts, library captures and pairing changes."""

        if not _loopback_request(request):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "loopback_only",
                    "message": "Workspace event streaming is only available on the local machine.",
                },
            )
        requested = str(workspace_id or "").strip()
        scope = host_workspace_scope(workspace_id, session_id)
        bridge = _browser_bridge(runtime)

        def matches_workspace(raw_event_workspace: str) -> bool:
            candidate = str(raw_event_workspace or "").strip()
            if not candidate:
                return False
            if candidate == "*" or candidate in {scope, requested}:
                return True
            try:
                return current_workspace_id(workspace_id=candidate) == scope
            except HTTPException:
                return False

        async def event_generator():
            loop = asyncio.get_running_loop()
            with bridge.subscribe_events(loop) as queue:
                snapshot_payload = {
                    "type": "snapshot",
                    "workspace_id": scope,
                    "requested_workspace_id": requested,
                    "drafts": bridge.pending_drafts(scope),
                    "library": compute_library_revision(scope, requested),
                    "paired_credentials": bridge.credential_count(),
                }
                yield f"event: snapshot\ndata: {json.dumps(snapshot_payload, ensure_ascii=False)}\n\n"
                if once:
                    return
                emitted = 0
                event_limit = max_events if isinstance(max_events, int) and max_events > 0 else None
                while event_limit is None or emitted < event_limit:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    except TimeoutError:
                        if await request.is_disconnected():
                            break
                        yield ": keepalive\n\n"
                        continue
                    if not matches_workspace(str(event.get("workspace_id") or "")):
                        continue
                    raw_seq = event.get("seq")
                    frame_payload = {
                        "type": "workspace_event",
                        "kind": str(event.get("kind") or "updated"),
                        "seq": raw_seq if isinstance(raw_seq, int) else 0,
                        "workspace_id": scope,
                        "requested_workspace_id": requested,
                        "drafts": bridge.pending_drafts(scope),
                        "library": compute_library_revision(scope, requested),
                        "paired_credentials": bridge.credential_count(),
                    }
                    yield f"event: workspace_event\ndata: {json.dumps(frame_payload, ensure_ascii=False)}\n\n"
                    emitted += 1

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router


__all__ = ["build_browser_router"]
