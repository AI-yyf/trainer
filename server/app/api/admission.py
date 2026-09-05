from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response

# The extension can send either JSON aliases or this header. Treat every
# explicit read-only marker as restrictive so stale managed data cannot widen
# a project request.
ADMISSION_MODE_HEADER = "x-trainer-admission-mode"
ADMISSION_MODE_KEYS = (
    "admission_mode",
    "admissionMode",
    "workspace_admission_mode",
    "workspaceAdmissionMode",
    "project_admission_mode",
    "projectAdmissionMode",
)
ADMISSION_CONTAINER_KEYS = (
    "admission",
    "workspace_admission",
    "workspaceAdmission",
    "trainer_workspace_admission",
    "trainerWorkspaceAdmission",
    "trainer_workspace",
    "trainerWorkspace",
)
ADMISSION_CONTAINER_MODE_KEYS = (
    "mode",
    "status",
    "admission_mode",
    "admissionMode",
)

BROWSE_ONLY_MODE = "browse"
IGNORED_MODE = "ignored"
READ_ONLY_ADMISSION_MODES = frozenset({BROWSE_ONLY_MODE, IGNORED_MODE})
READ_ONLY_ADMISSION_MODE_PRIORITY = (BROWSE_ONLY_MODE, IGNORED_MODE)
BROWSE_ONLY_BLOCK_CODE = "browse_only_persistence_blocked"

# These POST routes only inspect remote provider capabilities or existing
# indexed data. Every other mutating route is denied by default so new stateful
# endpoints cannot accidentally bypass browse-only admission.
BROWSE_SAFE_POST_PATHS = frozenset(
    {
        "/provider/test",
        "/provider/models",
        "/resource/search",
    }
)

# The active-card selector writes the chosen routing back to structured
# memory, despite using GET for the transport.
BROWSE_BLOCKED_READ_PATHS = frozenset({"/training/active-card"})


def _normalized_mode(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _payload_admission_modes(payload: Mapping[str, Any]) -> list[str]:
    modes: list[str] = []
    for key in ADMISSION_MODE_KEYS:
        normalized = _normalized_mode(payload.get(key))
        if normalized is not None:
            modes.append(normalized)

    for key in ADMISSION_CONTAINER_KEYS:
        container = payload.get(key)
        if not isinstance(container, Mapping):
            continue
        for mode_key in ADMISSION_CONTAINER_MODE_KEYS:
            normalized = _normalized_mode(container.get(mode_key))
            if normalized is not None:
                modes.append(normalized)
    return modes


async def request_admission_mode(request: Request) -> str | None:
    """Return the most restrictive explicit admission mode on a request.

    A read-only mode wins when supported carriers disagree. This keeps a stale
    managed value from widening a browse-only or ignored project request.
    """

    modes: list[str] = []
    header_mode = _normalized_mode(request.headers.get(ADMISSION_MODE_HEADER))
    if header_mode is not None:
        modes.append(header_mode)

    for key in ADMISSION_MODE_KEYS:
        query_mode = _normalized_mode(request.query_params.get(key))
        if query_mode is not None:
            modes.append(query_mode)

    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            payload = json.loads((await request.body()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, Mapping):
            modes.extend(_payload_admission_modes(payload))

    for read_only_mode in READ_ONLY_ADMISSION_MODE_PRIORITY:
        if read_only_mode in modes:
            return read_only_mode
    return modes[0] if modes else None


def request_would_persist_browse_state(method: str, path: str) -> bool:
    """Whether a read-only request must be rejected before its handler runs."""

    normalized_method = method.upper()
    if normalized_method in {"GET", "HEAD", "OPTIONS"}:
        return path in BROWSE_BLOCKED_READ_PATHS
    if normalized_method in {"POST", "PUT", "PATCH", "DELETE"}:
        return path not in BROWSE_SAFE_POST_PATHS
    return False


async def browse_only_rejection(request: Request) -> Response | None:
    """Build a uniform rejection for persistent read-only operations."""

    admission_mode = await request_admission_mode(request)
    if admission_mode not in READ_ONLY_ADMISSION_MODES:
        return None
    if not request_would_persist_browse_state(request.method, request.url.path):
        return None
    return JSONResponse(
        status_code=409,
        content={
            "detail": "Browse-only admission does not allow persistent Trainer operations.",
            "code": BROWSE_ONLY_BLOCK_CODE,
            "admission_mode": admission_mode,
        },
    )
