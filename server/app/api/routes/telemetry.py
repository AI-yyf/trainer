"""Opt-in anonymous telemetry router (P2 #18).

Three endpoints, none of them a turn or identity channel:

- ``GET /telemetry/status``  — consent state as fact (no event data).
- ``POST /telemetry/consent`` — the only consent write path; the change is
  audited via the service, the body carries a flag and a charset-checked
  source token, never free text.
- ``GET /telemetry/export``  — the coarse anonymous payload, empty by
  construction when consent is off.

The service is host-wired in ``app/main.py``; a runtime without it fails
closed with 503 rather than guessing a consent answer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...telemetry.service import MAX_WINDOW_DAYS, TelemetryService
from ..runtime import TrainerRuntime

_TELEMETRY_UNAVAILABLE = "Telemetry service is not wired on this runtime."


def _service(runtime: TrainerRuntime) -> TelemetryService:
    service = getattr(runtime, "telemetry_service", None)
    if not isinstance(service, TelemetryService):
        raise HTTPException(status_code=503, detail=_TELEMETRY_UNAVAILABLE)
    return service


def build_telemetry_router(runtime: TrainerRuntime) -> APIRouter:
    router = APIRouter(prefix="/telemetry", tags=["telemetry"])

    @router.get("/status")
    def telemetry_status() -> dict[str, Any]:
        return _service(runtime).status()

    @router.post("/consent")
    def telemetry_consent(payload: dict[str, Any]) -> dict[str, Any]:
        return _service(runtime).set_opt_in(bool(payload.get("opt_in", False)), source=payload.get("source"))

    @router.get("/export")
    def telemetry_export(window_days: int = Query(default=7, ge=1, le=MAX_WINDOW_DAYS)) -> dict[str, Any]:
        return _service(runtime).build_export(window_days=window_days)

    return router
