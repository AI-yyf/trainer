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
    localized_text: Callable[..., str]
    contains_cjk_text: Callable[..., bool]
    prefers_chinese: Callable[..., bool]
    operation_reliability_record: Callable[..., Any]
    provider_capabilities_from_payload: Callable[[dict[str, Any]], Any]
    provider_connection_type_from_payload: Callable[[dict[str, Any]], str | None]
    provider_protocol_from_payload: Callable[[dict[str, Any]], Any]
    provider_model_policy_detail: Callable[..., Any]
    provider_model_policy_violation: Callable[..., Any]
    require_sandbox_service: Callable[[], Any]
    apply_host_workspace_trust_attestation: Callable[..., None]
    workspace_learning_project_state: Callable[..., dict[str, str]]
    sync_resource_record_to_sandbox: Callable[..., Any]
