"""Runtime-negotiated ``thinking`` request-field policy.

Trainer used to hard-code ``thinking: {"type": "disabled"}`` on every request to
any non-official Anthropic base URL. The motivation was real — reasoning-first
gateways can burn a short reply budget on hidden reasoning — but a blanket
override has two failure modes:

* Models that *require* thinking (e.g. ``…-Flash-Preview`` on a MiniMax-style
  gateway) reject ``type="disabled"`` with HTTP 400, so the model becomes
  permanently unusable even though the provider lists it.
* An explicit ``request_defaults.extra_body.thinking`` written by the user is
  silently discarded, so the settings screen lies about what is on the wire.

This module makes the field *negotiated* instead of assumed:

* ``disabled`` stays the default first attempt (it keeps probe replies short).
* When a gateway rejects that field, the rejection is classified, the model
  remembers which policy actually worked, and the request is replayed.
* A user-declared thinking config is always honoured; auto-tuning never
  overrides an explicit choice.
"""

from __future__ import annotations

import re
from typing import Any, Literal

ThinkingPolicy = Literal["disabled", "omit", "enabled"]

DEFAULT_POLICY: ThinkingPolicy = "disabled"

#: Where to go next, tried once each, when the gateway rejects a policy.
_FALLBACK_ORDER: dict[ThinkingPolicy, tuple[ThinkingPolicy, ...]] = {
    "disabled": ("omit", "enabled"),
    "enabled": ("omit", "disabled"),
    "omit": ("enabled", "disabled"),
}

# Gateway wording varies, so match on the field name plus the rejection verbs
# rather than on one exact sentence.
_THINKING_FIELD_RE = re.compile(
    r"(?:thinking|reasoning_effort|reasoningEffort|enable_thinking|thinkingBudget|thinking_budget)",
    re.IGNORECASE,
)
_REJECTION_RE = re.compile(
    r"(?:is not allowed|not allowed|not supported|unsupported|invalid|"
    r"requires|required|must be|not permitted|unrecognized|unexpected|"
    r"unknown (?:field|parameter|param))",
    re.IGNORECASE,
)
#: "requires adaptive thinking" is the canonical *mandatory-thinking* phrasing:
#: dropping the field is not enough, it has to be enabled.
_REQUIRES_THINKING_RE = re.compile(
    r"requires?\s+(?:adaptive\s+|mandatory\s+)?thinking|"
    r"thinking\s+(?:is\s+)?(?:required|mandatory)|"
    r"must\s+(?:enable|use)\s+thinking|"
    r"thinking\.type\s*=\s*\"enabled\"",
    re.IGNORECASE,
)


# --- learned per-model state -------------------------------------------------
# Once a gateway tells us it rejects a thinking policy we stop re-probing it on
# every subsequent request for the rest of the process. Keyed by
# (base_url, model) so one model never poisons another on the same gateway.
_learned_policy: dict[tuple[str, str], ThinkingPolicy] = {}


def model_key(provider: Any) -> tuple[str, str]:
    base = str(getattr(provider, "base_url", "") or "").strip().lower()
    model = str(getattr(provider, "model", "") or "").strip().lower()
    return base, model


def learned_policy(provider: Any) -> ThinkingPolicy | None:
    return _learned_policy.get(model_key(provider))


def remember_policy(provider: Any, policy: ThinkingPolicy) -> None:
    _learned_policy[model_key(provider)] = policy


def reset_learned_policies() -> None:
    """Test hook — clears every learned per-model policy."""
    _learned_policy.clear()


# --- classification ----------------------------------------------------------
def _error_text(error: BaseException) -> str:
    """Flatten an SDK/provider exception into searchable text."""
    parts: list[str] = [type(error).__name__, str(error)]
    for attribute in ("body", "message", "param", "code"):
        value = getattr(error, attribute, None)
        if value is not None:
            parts.append(str(value))
    response = getattr(error, "response", None)
    if response is not None:
        text = getattr(response, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(part for part in parts if part)


def _status_code(error: BaseException) -> int | None:
    for attribute in ("status_code", "http_status"):
        value = getattr(error, attribute, None)
        if isinstance(value, int) and 100 <= value < 600:
            return value
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    return None


def thinking_rejection_policy(
    error: BaseException,
    attempted: ThinkingPolicy | None = None,
) -> ThinkingPolicy | None:
    """Classify a gateway rejection of the thinking field.

    Returns the policy to retry with, or ``None`` when the failure is unrelated
    to thinking (those must keep the caller's normal error handling).
    """
    status = _status_code(error)
    if status is not None and status != 400:
        return None

    text = _error_text(error)
    if not text or not _THINKING_FIELD_RE.search(text):
        return None
    if not _REJECTION_RE.search(text):
        return None

    if attempted is None:
        attempted = DEFAULT_POLICY

    if _REQUIRES_THINKING_RE.search(text):
        # Dropping the field will not satisfy a mandatory-thinking model.
        return None if attempted == "enabled" else "enabled"

    for candidate in _FALLBACK_ORDER.get(attempted, ()):
        return candidate
    return None


def declared_thinking(payload: dict[str, Any] | None) -> ThinkingPolicy | None:
    """Read a thinking policy the caller/user already put on the payload."""
    if not isinstance(payload, dict):
        return None
    for container_key in ("extra_body", "thinking"):
        container = payload.get(container_key)
        if not isinstance(container, dict):
            continue
        thinking = container.get("thinking") if container_key == "extra_body" else container
        if not isinstance(thinking, dict):
            continue
        kind = str(thinking.get("type") or "").strip().lower()
        if kind == "disabled":
            return "disabled"
        if kind in {"enabled", "adaptive", "auto"}:
            return "enabled"
    if "thinking" in payload and payload.get("thinking") is None:
        return "omit"
    return None


def resolve_thinking_policy(
    payload: dict[str, Any] | None,
    provider: Any,
) -> ThinkingPolicy:
    """Pick the policy for this request.

    Precedence, highest first:

    1. A user-declared thinking config is never overridden.
    2. A policy this model already taught us by rejecting the previous one.
    3. The default first attempt (``disabled``), which keeps probe replies short.
    """
    explicit = declared_thinking(payload)
    if explicit == "enabled":
        return "enabled"
    learned = learned_policy(provider)
    if learned is not None:
        return learned
    if explicit is not None:
        return explicit
    return DEFAULT_POLICY


def apply_thinking_policy(
    payload: dict[str, Any],
    policy: ThinkingPolicy,
) -> dict[str, Any]:
    """Return ``payload`` with the thinking field set to ``policy``.

    The field is written to ``extra_body`` unless the payload already carries a
    top-level ``thinking`` key. That matters: the OpenAI SDK's
    ``chat.completions.create`` rejects unknown keyword arguments with a
    ``TypeError`` *before* any HTTP request goes out, so a top-level
    ``thinking=`` would turn a working provider into a client-side crash. The SDK
    flattens ``extra_body`` onto the wire, which is what these gateways expect.
    """
    out = dict(payload)
    has_top_level = "thinking" in out
    extra_body = out.get("extra_body")
    extra_body = dict(extra_body) if isinstance(extra_body, dict) else None

    if policy == "omit":
        if has_top_level:
            out.pop("thinking", None)
        if extra_body is not None:
            extra_body.pop("thinking", None)
    elif has_top_level:
        existing = out.get("thinking")
        thinking = dict(existing) if isinstance(existing, dict) else {}
        thinking["type"] = policy
        out["thinking"] = thinking
    else:
        if extra_body is None:
            extra_body = {}
        existing = extra_body.get("thinking")
        thinking = dict(existing) if isinstance(existing, dict) else {}
        thinking["type"] = policy
        extra_body["thinking"] = thinking

    if extra_body is not None:
        if extra_body:
            out["extra_body"] = extra_body
        else:
            out.pop("extra_body", None)
    return out
