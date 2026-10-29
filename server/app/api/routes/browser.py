"""Browser capture lane: pairing, status and the coach-draft queue.

The Trainer Capture browser extension authenticates with the Bearer credential
it redeemed from a host-registered pairing code (see ``app.browser_bridge``);
the host itself talks to ``/browser/pair-code`` on the regular trusted loopback
boundary. Route-level behavior:

- ``POST /browser/pair-code``      host registers a 6-digit, single-use code;
- ``POST /browser/pair``           browser exchanges the code for a credential;
- ``DELETE /browser/pair``         revoke (Bearer = that credential; no Bearer =
                                   the host retires the latest registration);
- ``GET  /browser/status``         workspace name, learning-focus options and
                                   the library count for the paired workspace;
- ``POST /browser/coach-draft``    queue a prefilled coach draft (selection);
- ``GET  /browser/pending-drafts`` host polls queued drafts (host-facing:
                                   trusted loopback / instance token, and an
                                   explicit workspace reference is required);
- ``POST /browser/pending-drafts/ack`` host acks the drafts it forwarded (same
                                   host-facing boundary).

The browser extension never reads the pending queue — the host is its only
consumer — so the two queue routes do not take a Bearer credential. They are
strictly workspace-scoped: a caller that does not state which workspace it is
polling for gets an error, never another project's captures.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ...browser_bridge import BrowserBridgeService, BrowserCredential, BrowserPairingError
from ..runtime import TrainerRuntime
from ._deps import RouterDeps


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



def _loopback_request(request: Request) -> bool:
    client = getattr(request, "client", None)
    host = str(getattr(client, "host", "") or "").strip().lower()
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _extension_origin_allowed(request: Request) -> bool:
    """Only a browser-extension origin may auto-pair.

    A request with no Origin is a native/local caller (curl, tests); an Origin
    from a normal website is refused, so a random page cannot silently mint a
    capture credential even though the endpoint is loopback-only.
    """
    origin = str(request.headers.get("origin") or "").strip().lower()
    if not origin:
        return True
    return origin.startswith(("chrome-extension://", "moz-extension://"))


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
    def exchange_pair_code(payload: dict[str, Any]) -> dict[str, object]:
        """Browser-side redemption: one code becomes one long-lived credential."""

        body = payload if isinstance(payload, dict) else {}
        bridge = _browser_bridge(runtime)
        try:
            credential, token = bridge.exchange_pair_code(
                str(body.get("code") or body.get("pairing_code") or "")
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
        """Zero-code pairing: the extension discovers the loopback sidecar.

        The extension calls this on first use. The credential is bound to the
        workspace of the latest host session, so the browser never has to ask
        the learner for a code, port, URL or token.
        """
        if not _loopback_request(request):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "loopback_only",
                    "message": "Automatic browser pairing is only available on the local machine.",
                },
            )
        if not _extension_origin_allowed(request):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "extension_origin_required",
                    "message": "Automatic pairing is only available to a browser extension.",
                },
            )
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
        bridge = _browser_bridge(runtime)
        try:
            credential, token = bridge.issue_auto_credential(
                workspace_id=workspace_id,
                workspace_name=workspace_name,
            )
        except BrowserPairingError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc
        return credential.as_payload(credential=token)

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
            )
        except BrowserPairingError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc
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

    @router.get("/browser/pending-drafts")
    def list_pending_drafts(
        workspace_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        """Host poll: only the drafts captured for the polling workspace."""

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

    return router


__all__ = ["build_browser_router"]
