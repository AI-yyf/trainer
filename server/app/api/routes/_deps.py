from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RouterDeps:
    """Closure helpers owned by ``build_router`` and shared with extracted routers."""

    current_workspace_id: Callable[..., str]
    current_snapshot: Callable[..., Any]
    refresh_workspace_sessions: Callable[[str], None]
    hydrate_snapshot: Callable[..., Any]
    effective_response_language: Callable[..., Any]
    persist_first_look_summary: Callable[..., Any]
    provider_config_from_payload: Callable[[dict[str, Any]], Any]
    provider_api_key_from_payload: Callable[[dict[str, Any]], str | None]
    normalize_trainer_root_path: Callable[[str], str]
    routing_learner_state: Callable[..., Any]
