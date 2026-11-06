"""Provider payload parsing (Phase 4 split, third router slice).

Pure helpers extracted from ``api/routers.py`` (build_router closure): parse
provider payloads into protocol/connection/mode/credential/capability/config
objects, and normalize pasted base URLs (request endpoints → base URL, scheme
probing for scheme-less hosts). Behaviour unchanged — the router keeps
aliases with the original names so every call site and RouterDeps binding
stays identical.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from ..core.models import CapabilityFlags, ProviderConfig, ProviderCredentialMode
from ..llm.provider_gateway import NEWAPI_CONNECTION_TYPE, normalize_provider_connection_type
from ..llm.provider_protocols import (
    ProviderProtocol,
    default_capabilities_for_protocol,
    normalize_provider_protocol,
)
from .router_support import looks_like_schemeless_provider_host, resolve_provider_url_scheme


def provider_api_key_from_payload(payload: dict) -> str | None:
    api_key_raw = payload.get("api_key") or payload.get("apiKey")
    return api_key_raw.strip() if isinstance(api_key_raw, str) else None

def normalize_provider_base_url(value: object, protocol: ProviderProtocol) -> str:
    """Keep a pasted request endpoint from becoming the client's base URL."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""

    # Scheme-less service hosts ("minimax.example.com", "localhost:1234/v1",
    # "ollama:11434") get a probed scheme so http-only relays and local
    # servers both work instead of failing later with an opaque error.
    # Mirrors the webview draft checks in shared TS providerProtocols.
    candidate = raw_value
    if not candidate.lower().startswith(("http://", "https://")) and looks_like_schemeless_provider_host(
        candidate
    ):
        candidate = f"{resolve_provider_url_scheme(candidate)}://{candidate}"

    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return raw_value.rstrip("/")

    if not parsed.scheme or not parsed.netloc:
        return raw_value.rstrip("/")

    path = parsed.path.rstrip("/")
    lowered_path = path.lower()
    if protocol in {
        "openai_responses",
        "openai_chat_completions",
        "openai_chat_completions_compatible",
    }:
        for suffix in ("/chat/completions", "/responses"):
            if lowered_path.endswith(suffix):
                path = path[: -len(suffix)] or "/"
                break
    elif protocol == "anthropic_messages" and lowered_path.endswith("/messages"):
        path = path[: -len("/messages")] or "/"
    elif protocol == "gemini_generate_content":
        model_marker = "/models/"
        marker_index = lowered_path.rfind(model_marker)
        if marker_index >= 0 and lowered_path.endswith(":generatecontent"):
            path = path[:marker_index] or "/"

    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))

def provider_connection_type_from_payload(provider_payload: dict) -> str | None:
    raw = (
        provider_payload.get("connection_type")
        or provider_payload.get("connectionType")
        or provider_payload.get("_type")
        or provider_payload.get("protocol")
    )
    if not isinstance(raw, str):
        return None
    return normalize_provider_connection_type(raw)

def provider_protocol_from_payload(provider_payload: dict) -> ProviderProtocol | None:
    raw = provider_payload.get("protocol") or provider_payload.get("api") or ""
    value = str(raw or "").strip().lower()
    if not value:
        return None
    if normalize_provider_connection_type(value) is not None:
        return None
    if value in {"anthropic_messages", "anthropic", "claude"}:
        return "anthropic_messages"
    if value in {"openai_responses", "responses"}:
        return "openai_responses"
    if value in {"gemini_generate_content", "gemini", "google"}:
        return "gemini_generate_content"
    if value in {"openai_chat_completions", "openai"}:
        return "openai_chat_completions"
    if value in {"openai_chat_completions_compatible", "openai-compatible", "compatible"}:
        return "openai_chat_completions_compatible"
    return normalize_provider_protocol(value)

def provider_mode_from_payload(
    provider_payload: dict,
) -> Literal["direct", "gateway"] | None:
    raw_mode = provider_payload.get("mode")
    if not isinstance(raw_mode, str):
        return None
    normalized_mode = raw_mode.strip()
    if normalized_mode == "direct":
        return "direct"
    if normalized_mode == "gateway":
        return "gateway"
    return None

def provider_credential_mode_from_payload(
    provider_payload: dict,
) -> ProviderCredentialMode | None:
    raw_mode = provider_payload.get("credential_mode") or provider_payload.get("credentialMode")
    if not isinstance(raw_mode, str):
        return None
    normalized_mode = raw_mode.strip()
    if normalized_mode == "workspace_secret":
        return "workspace_secret"
    if normalized_mode == "ui_proxy":
        return "ui_proxy"
    return None

def provider_payload_declares_protocol(provider_payload: dict) -> bool:
    for key in ("protocol", "api", "provider_key", "providerKey"):
        raw_value = provider_payload.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return True
    return False

def provider_capabilities_from_payload(provider_payload: dict) -> CapabilityFlags:
    explicit_capabilities = provider_payload.get("capabilities")
    if isinstance(explicit_capabilities, dict) and explicit_capabilities:
        return CapabilityFlags.model_validate(explicit_capabilities)
    protocol = provider_protocol_from_payload(provider_payload) or (
        "openai_chat_completions_compatible"
    )
    defaults = default_capabilities_for_protocol(protocol)
    if not provider_payload_declares_protocol(provider_payload):
        defaults = defaults.model_copy(
            update={
                "embeddings": False,
                "tools": False,
                "json_schema": False,
                "structured_output": False,
            }
        )
    return defaults

def provider_config_from_payload(payload: dict) -> ProviderConfig | None:
    provider_payload = payload.get("provider")
    if not isinstance(provider_payload, dict):
        return None
    provider_protocol = provider_protocol_from_payload(provider_payload)
    declared_protocol_raw = provider_payload.get("protocol") or provider_payload.get("api")
    declared_protocol = (
        isinstance(declared_protocol_raw, str) and bool(str(declared_protocol_raw).strip())
    )
    connection_type = provider_connection_type_from_payload(provider_payload)
    if declared_protocol and provider_protocol is None:
        return None
    if provider_protocol is None and connection_type == NEWAPI_CONNECTION_TYPE:
        return None
    if provider_protocol is None:
        provider_protocol = "openai_chat_completions_compatible"
    provider_name_raw = (
        provider_payload.get("name")
        or provider_payload.get("label")
        or provider_payload.get("provider_key")
        or provider_payload.get("providerKey")
        or provider_payload.get("api")
        or "custom-openai-compatible"
    )
    return ProviderConfig(
        name=str(provider_name_raw).strip() or "custom-openai-compatible",
        baseUrl=normalize_provider_base_url(
            provider_payload.get("base_url") or provider_payload.get("baseUrl", ""),
            provider_protocol,
        ),
        apiKeyRef=provider_payload.get("api_key_ref")
        or provider_payload.get("apiKeyRef", "trainer.default"),
        model=(provider_payload.get("model", "") or "").strip(),
        protocol=provider_protocol,
        label=(provider_payload.get("label") or provider_payload.get("name") or "").strip() or None,
        mode=provider_mode_from_payload(provider_payload),
        connectionType=connection_type,
        credentialMode=provider_credential_mode_from_payload(provider_payload),
        availableModels=list(provider_payload.get("available_models") or provider_payload.get("availableModels") or []),
        allowedModels=list(provider_payload.get("allowed_models") or provider_payload.get("allowedModels") or []),
        deniedModels=list(provider_payload.get("denied_models") or provider_payload.get("deniedModels") or []),
        modelAliases=dict(provider_payload.get("model_aliases") or provider_payload.get("modelAliases") or {}),
        modelCapabilities=dict(
            provider_payload.get("model_capabilities") or provider_payload.get("modelCapabilities") or {}
        ),
        modelTokenLimits=dict(
            provider_payload.get("model_token_limits") or provider_payload.get("modelTokenLimits") or {}
        ),
        taskBindings=dict(provider_payload.get("task_bindings") or provider_payload.get("taskBindings") or {}),
        contextWindowTokens=provider_payload.get("context_window_tokens")
        or provider_payload.get("contextWindowTokens"),
        maxOutputTokens=provider_payload.get("max_output_tokens")
        or provider_payload.get("maxOutputTokens"),
        embeddingModel=provider_payload.get("embedding_model")
        or provider_payload.get("embeddingModel"),
        catalogSource=(provider_payload.get("catalog_source") or provider_payload.get("catalogSource") or "").strip()
        or None,
        cacheTtlSeconds=provider_payload.get("cache_ttl_seconds")
        or provider_payload.get("cacheTtlSeconds"),
        profileId=(provider_payload.get("profile_id") or provider_payload.get("profileId") or "").strip()
        or None,
        profileLabel=(provider_payload.get("profile_label") or provider_payload.get("profileLabel") or "").strip()
        or None,
        profileMode=(provider_payload.get("profile_mode") or provider_payload.get("profileMode") or "").strip()
        or None,
        requestDefaults=provider_payload.get("request_defaults")
        or provider_payload.get("requestDefaults")
        or {},
        capabilities=provider_capabilities_from_payload(provider_payload),
    )
