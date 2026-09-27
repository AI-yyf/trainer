"""Provider capability detection (§五十二: extracted from provider_service.py).

Inspects ProviderConfig attributes to detect gateway type, reasoning-first
models, thinking support, and probe budgets. The only external dependency
is ``normalize_provider_connection_type`` from ``provider_gateway``.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

from ...core.models import ProviderConfig
from ..provider_gateway import normalize_provider_connection_type


def _is_loopback_provider_url(value: object | None) -> bool:
    """Return whether a provider URL is explicitly confined to this machine."""
    try:
        hostname = urlsplit(str(value or "")).hostname
    except ValueError:
        return False
    if not hostname:
        return False

    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _should_fingerprint_gateway(provider: ProviderConfig | None) -> bool:
    if provider is None:
        return False
    if normalize_provider_connection_type(getattr(provider, "connection_type", None)):
        return True
    identity = " ".join(
        str(value or "")
        for value in (
            getattr(provider, "name", None),
            getattr(provider, "base_url", None),
            getattr(provider, "label", None),
        )
    )
    return bool(re.search(r"new[\s_-]*api|one[\s_-]*api", identity, re.I))


def _is_minimax_like_provider(provider: ProviderConfig | None) -> bool:
    if provider is None:
        return False
    identity = " ".join(
        str(value or "")
        for value in (
            getattr(provider, "name", None),
            getattr(provider, "base_url", None),
            getattr(provider, "model", None),
        )
    )
    return "minimax" in identity.lower()


def _is_kimi_like_provider(provider: ProviderConfig | None) -> bool:
    if provider is None:
        return False
    identity = " ".join(
        str(value or "")
        for value in (
            getattr(provider, "name", None),
            getattr(provider, "base_url", None),
            getattr(provider, "model", None),
        )
    ).lower()
    return "kimi" in identity or "moonshot" in identity


# Reasoning-first model families whose hidden reasoning can consume an entire
# small output budget before the first visible token, regardless of gateway.
_REASONING_FIRST_MODEL_PATTERN = re.compile(
    r"deepseek[-_. ]?r|deepseek[-_. ]?reasoner|qwq|o1(?:[-_.](?:mini|preview|pro))?|"
    r"o3(?:[-_.]mini)?|o4[-_.]mini|glm[-_. ]?\d*[-_. ]?z|thinking|reasoner",
    re.IGNORECASE,
)


def _model_looks_reasoning_first(provider: ProviderConfig | None) -> bool:
    model = str(getattr(provider, "model", "") or "")
    return bool(model) and bool(_REASONING_FIRST_MODEL_PATTERN.search(model))


def _needs_generous_visible_probe_budget(provider: ProviderConfig | None) -> bool:
    return (
        _is_minimax_like_provider(provider)
        or _is_kimi_like_provider(provider)
        or _model_looks_reasoning_first(provider)
    )


def _visible_probe_max_tokens(provider: ProviderConfig | None, default: int = 96) -> int:
    """Leave room for a visible token after reasoning-first gateways finish thinking.

    Measured reasoning-first gateways can spend 256+ output tokens on hidden
    reasoning for a one-word visible reply, so the generous tier grants 1024.
    """
    return max(default, 1024) if _needs_generous_visible_probe_budget(provider) else default


_MINIMAX_NATIVE_THINKING_MODEL = re.compile(r"minimax[-_. ]?m\d|abab\d", re.IGNORECASE)


def _minimax_native_thinking_confirmed(provider: ProviderConfig | None) -> bool:
    """Native MiniMax thinking fields only for known MiniMax models or live-declared thinking."""
    if not _is_minimax_like_provider(provider):
        return False
    model = str(getattr(provider, "model", "") or "")
    if _MINIMAX_NATIVE_THINKING_MODEL.search(model):
        return True
    return bool(getattr(getattr(provider, "capabilities", None), "thinking", False))


def _normalized_provider_request_defaults(provider: ProviderConfig | None) -> dict[str, Any]:
    defaults = getattr(provider, "request_defaults", None) if provider is not None else None
    normalized = dict(defaults) if isinstance(defaults, dict) else {}
    if not _is_minimax_like_provider(provider):
        return normalized

    extra_body = normalized.get("extra_body")
    normalized_extra_body = dict(extra_body) if isinstance(extra_body, dict) else {}
    if not _minimax_native_thinking_confirmed(provider):
        # Unknown models must not receive invented thinking fields.
        normalized_extra_body.pop("thinking", None)
        if normalized_extra_body:
            normalized["extra_body"] = normalized_extra_body
        else:
            normalized.pop("extra_body", None)
        normalized.pop("thinking", None)
        normalized.pop("thinkingBudget", None)
        normalized.pop("thinking_budget", None)
        return normalized

    # MiniMax-compatible gateways can consume a short reply budget in hidden
    # reasoning unless this request-body field is explicitly disabled.
    thinking = normalized_extra_body.get("thinking")
    thinking_type = (
        str(thinking.get("type") or "").strip().lower()
        if isinstance(thinking, dict)
        else ""
    )
    declared_thinking = bool(getattr(getattr(provider, "capabilities", None), "thinking", False))
    # MiniMax thinks-by-default and can swallow a short visible-reply budget.
    # Keep enabled only when the profile explicitly declared thinking after a live probe.
    # A thinking-capability probe overlays extra_body after defaults are applied.
    if thinking_type == "enabled" and declared_thinking:
        thinking_type = "enabled"
    else:
        thinking_type = "disabled"
    normalized_extra_body["thinking"] = {"type": thinking_type}
    normalized["extra_body"] = normalized_extra_body
    return normalized


def _flatten_minimax_thinking_for_raw_http(
    payload: dict[str, Any],
    provider: ProviderConfig | None,
) -> dict[str, Any]:
    """Put confirmed MiniMax thinking on the wire the same way the OpenAI SDK does.

    The SDK flattens ``extra_body`` onto the HTTP JSON body. Nested
    ``extra_body.thinking`` on raw httpx paths is not honored by MiniMax/New API.
    Unknown models and gateways must not receive invented thinking fields.
    """
    if not isinstance(payload, dict) or not _minimax_native_thinking_confirmed(provider):
        return payload
    extra_body = payload.get("extra_body")
    extra_thinking = extra_body.get("thinking") if isinstance(extra_body, dict) else None
    top_thinking = payload.get("thinking")
    if isinstance(extra_thinking, dict):
        thinking = dict(extra_thinking)
    elif isinstance(top_thinking, dict):
        thinking = dict(top_thinking)
    else:
        return payload
    flattened = dict(payload)
    flattened["thinking"] = thinking
    if isinstance(extra_body, dict):
        next_extra = {key: value for key, value in extra_body.items() if key != "thinking"}
        if next_extra:
            flattened["extra_body"] = next_extra
        else:
            flattened.pop("extra_body", None)
    return flattened
