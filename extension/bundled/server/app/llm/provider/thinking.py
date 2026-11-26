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

* ``disabled`` stays the default first attempt where a probe or a
  provider-specific rule declares it (it keeps probe replies short).
* When a gateway rejects that field, the rejection is classified, the model
  remembers which policy actually worked, and the request is replayed.
* A user-declared thinking config is always honoured; auto-tuning never
  overrides an explicit choice.
"""

from __future__ import annotations

import re
from threading import Lock
from typing import Any, Literal

ThinkingPolicy = Literal["disabled", "omit", "enabled"]
ReasoningEffortLevel = Literal["off", "low", "medium", "high"]

#: Canonical token budgets when mapping request-level ``reasoning_effort`` to
#: budget-based protocols (Anthropic ``thinking.budget_tokens`` and Gemini
#: ``generationConfig.thinkingConfig.thinkingBudget``).
REASONING_EFFORT_BUDGET_TOKENS: dict[ReasoningEffortLevel, int] = {
    "off": 0,
    "low": 2048,
    "medium": 8192,
    "high": 24576,
}


def normalize_reasoning_effort(value: object) -> ReasoningEffortLevel | None:
    """Normalize any user/config reasoning_effort alias to ``off|low|medium|high``.

    Returns ``None`` for empty / ``auto`` / unrecognized values so callers leave
    the model's native default untouched.
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    if cleaned in {"", "auto", "default"}:
        return None
    if cleaned in {"off", "none", "disabled", "false", "0"}:
        return "off"
    if cleaned in {"low", "minimal"}:
        return "low"
    if cleaned in {"medium", "med", "balanced"}:
        return "medium"
    if cleaned in {"high", "max", "deep"}:
        return "high"
    return None


def apply_reasoning_effort_to_payload(
    payload: dict[str, Any],
    effort: object,
    protocol: str,
) -> dict[str, Any]:
    """Map a unified request-level ``reasoning_effort`` onto the wire protocol.

    - OpenAI Chat Completions: ``reasoning_effort`` (omitted when ``off``)
    - OpenAI Responses: ``reasoning = {"effort": ...}`` (omitted when ``off``)
    - Anthropic Messages: ``thinking = {"type": "disabled"}`` or ``{"type": "enabled", "budget_tokens": N}``
    - Gemini GenerateContent: ``generationConfig.thinkingConfig = {"thinkingBudget": 0 | N}``
    """
    level = normalize_reasoning_effort(effort)
    if level is None:
        return payload
    out = dict(payload)
    proto = str(protocol or "").strip().lower()

    if proto in {"openai_chat_completions", "openai_chat_completions_compatible"}:
        if level == "off":
            out.pop("reasoning_effort", None)
            out.pop("reasoningEffort", None)
        else:
            out["reasoning_effort"] = level
        return out

    if proto == "openai_responses":
        if level == "off":
            out.pop("reasoning", None)
            out.pop("reasoning_effort", None)
        else:
            existing = out.get("reasoning")
            merged_reasoning = dict(existing) if isinstance(existing, dict) else {}
            merged_reasoning["effort"] = level
            out["reasoning"] = merged_reasoning
        return out

    if proto == "anthropic_messages":
        if level == "off":
            out["thinking"] = {"type": "disabled"}
        else:
            out["thinking"] = {
                "type": "enabled",
                "budget_tokens": REASONING_EFFORT_BUDGET_TOKENS[level],
            }
        return out

    if proto == "gemini_generate_content":
        gen_cfg = dict(out.get("generationConfig") or {}) if isinstance(out.get("generationConfig"), dict) else {}
        existing_tc = gen_cfg.get("thinkingConfig")
        next_tc = dict(existing_tc) if isinstance(existing_tc, dict) else {}
        next_tc["thinkingBudget"] = REASONING_EFFORT_BUDGET_TOKENS[level]
        gen_cfg["thinkingConfig"] = next_tc
        out["generationConfig"] = gen_cfg
        return out

    return out


#: What to send when a profile declares no thinking policy at all. ``omit``
#: leaves the model's own default in charge, which is what the composer's
#: "auto" choice promises. (``disabled`` is still the first *attempt* wherever a
#: probe or a provider-specific rule declares it explicitly.)
DEFAULT_POLICY: ThinkingPolicy = "omit"

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
# Once a gateway tells us it rejects a thinking policy or parameter we stop
# re-probing it on every subsequent request for the rest of the process. Keyed
# by (base_url, model, protocol) so neither another model nor another protocol
# on the same multi-protocol gateway is ever cross-poisoned.
_LEARNED_CACHE_LIMIT = 128
_LEARNED_STATE_GUARD = Lock()
_learned_policy: dict[tuple[str, str, str], ThinkingPolicy] = {}
_learned_param_repairs: dict[tuple[str, str, str], frozenset[str]] = {}


def _lru_put(cache: dict[Any, Any], key: Any, value: Any) -> None:
    cache.pop(key, None)
    cache[key] = value
    while len(cache) > _LEARNED_CACHE_LIMIT:
        oldest = next(iter(cache), None)
        if oldest is None or oldest == key:
            break
        cache.pop(oldest, None)


def model_key(provider: Any) -> tuple[str, str, str]:
    base = str(getattr(provider, "base_url", "") or "").strip().rstrip("/").lower()
    model = str(getattr(provider, "model", "") or "").strip().lower()
    protocol = str(getattr(provider, "protocol", "") or "").strip().lower()
    return base, model, protocol


def learned_policy(provider: Any) -> ThinkingPolicy | None:
    key = model_key(provider)
    with _LEARNED_STATE_GUARD:
        if key not in _learned_policy:
            return None
        value = _learned_policy.pop(key)
        _learned_policy[key] = value
        return value


def remember_policy(provider: Any, policy: ThinkingPolicy) -> None:
    key = model_key(provider)
    with _LEARNED_STATE_GUARD:
        _lru_put(_learned_policy, key, policy)


def learned_param_repairs(provider: Any) -> tuple[str, ...]:
    if provider is None:
        return ()
    key = model_key(provider)
    with _LEARNED_STATE_GUARD:
        existing = _learned_param_repairs.pop(key, None)
        if existing is None:
            return ()
        _learned_param_repairs[key] = existing
        return tuple(sorted(existing))


def remember_param_repairs(provider: Any, repairs: tuple[str, ...]) -> None:
    if provider is None or not repairs:
        return
    key = model_key(provider)
    with _LEARNED_STATE_GUARD:
        existing = _learned_param_repairs.get(key, frozenset())
        _lru_put(_learned_param_repairs, key, existing | frozenset(repairs))


def reset_learned_policies() -> None:
    """Test hook — clears every learned per-model policy and parameter repair."""
    with _LEARNED_STATE_GUARD:
        _learned_policy.clear()
        _learned_param_repairs.clear()


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
    # Respect OpenAI / gateway `reasoning_effort` / `reasoning` overrides without
    # injecting a contradictory `extra_body.thinking = {"type": "disabled"}`.
    extra_body = payload.get("extra_body")
    containers = (payload, extra_body) if isinstance(extra_body, dict) else (payload,)
    for container in containers:
        effort = container.get("reasoning_effort")
        if effort is None:
            effort = container.get("reasoningEffort")
        if isinstance(effort, str) and effort.strip():
            return "omit"
        reasoning = container.get("reasoning")
        if isinstance(reasoning, dict) and reasoning:
            return "omit"
    if "thinking" in payload and payload.get("thinking") is None:
        return "omit"
    return None


def resolve_thinking_policy(
    payload: dict[str, Any] | None,
    provider: Any,
    *,
    declared: ThinkingPolicy | None = None,
) -> ThinkingPolicy:
    """Pick the policy for this request.

    Precedence, highest first:

    1. An explicit opt-in (`enabled`) or `omit` (`reasoning_effort` / explicit
       ``thinking: None``) is never overridden.
    2. A policy this model already taught us by rejecting the previous one
       (so mandatory-thinking models aren't re-sent an auto-injected ``disabled``).
    3. Any remaining declared policy (such as an explicit ``disabled`` default).
    4. Nothing declared (``declared`` is ``None``): send nothing, so the model's
       own default applies. The composer shows that state as "auto", and a
       profile without request defaults already behaved this way; injecting
       ``disabled`` here only for profiles that carry an unrelated default
       (temperature, seed, …) silently turned thinking off for reasoning models.

    ``declared`` carries a policy the caller read from a source the payload
    cannot hold, such as a top-level ``thinking`` marker in the profile's
    request defaults (the chat wire only accepts it inside ``extra_body``).
    """
    explicit = declared_thinking(payload) if declared is None else declared
    if explicit in {"enabled", "omit"}:
        return explicit
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
        if policy == "disabled":
            thinking.pop("budget_tokens", None)
            thinking.pop("budgetTokens", None)
            out.pop("reasoning_effort", None)
            out.pop("reasoningEffort", None)
        thinking["type"] = policy
        out["thinking"] = thinking
    else:
        if extra_body is None:
            extra_body = {}
        existing = extra_body.get("thinking")
        thinking = dict(existing) if isinstance(existing, dict) else {}
        if policy == "disabled":
            thinking.pop("budget_tokens", None)
            thinking.pop("budgetTokens", None)
            out.pop("reasoning_effort", None)
            out.pop("reasoningEffort", None)
        thinking["type"] = policy
        extra_body["thinking"] = thinking

    if extra_body is not None:
        if extra_body:
            out["extra_body"] = extra_body
        else:
            out.pop("extra_body", None)
    return out


def clamp_wire_thinking_budget(
    payload: dict[str, Any],
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Ensure enabled wire ``budget_tokens`` / ``thinkingBudget`` stays strictly below output max.

    Providers return HTTP 400 when ``thinking.budget_tokens >= max_tokens`` (or
    when Gemini ``thinkingBudget >= maxOutputTokens``). Keeping thinking safely
    below the output cap guarantees headroom for the visible answer.
    """
    out = dict(payload)
    effective_cap = max_tokens
    if not isinstance(effective_cap, int) or isinstance(effective_cap, bool) or effective_cap <= 0:
        for key in ("max_tokens", "max_completion_tokens", "max_output_tokens", "maxTokens", "maxOutputTokens"):
            raw = out.get(key)
            if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
                effective_cap = raw
                break
        if effective_cap is None and isinstance(out.get("generationConfig"), dict):
            gen_max = out["generationConfig"].get("maxOutputTokens")
            if isinstance(gen_max, int) and not isinstance(gen_max, bool) and gen_max > 0:
                effective_cap = gen_max
    if not isinstance(effective_cap, int) or isinstance(effective_cap, bool) or effective_cap <= 0:
        return out

    reserve = min(2_048, max(128, effective_cap // 5))
    safe_thinking_cap = effective_cap - reserve

    def _clamp_thinking_record(thinking_obj: dict[str, Any]) -> dict[str, Any]:
        updated = dict(thinking_obj)
        mode = str(updated.get("type") or updated.get("mode") or "").strip().lower()
        if mode == "disabled":
            return updated
        budget = updated.get("budget_tokens", updated.get("budgetTokens"))
        if isinstance(budget, int) and not isinstance(budget, bool) and budget >= effective_cap:
            if safe_thinking_cap >= 64:
                if "budget_tokens" in updated:
                    updated["budget_tokens"] = safe_thinking_cap
                if "budgetTokens" in updated:
                    updated["budgetTokens"] = safe_thinking_cap
            else:
                updated.pop("budget_tokens", None)
                updated.pop("budgetTokens", None)
        return updated

    top_thinking = out.get("thinking")
    if isinstance(top_thinking, dict):
        out["thinking"] = _clamp_thinking_record(top_thinking)

    extra_body = out.get("extra_body")
    if isinstance(extra_body, dict) and isinstance(extra_body.get("thinking"), dict):
        next_extra = dict(extra_body)
        next_extra["thinking"] = _clamp_thinking_record(extra_body["thinking"])
        out["extra_body"] = next_extra

    gen_cfg = out.get("generationConfig")
    if isinstance(gen_cfg, dict) and isinstance(gen_cfg.get("thinkingConfig"), dict):
        next_gen = dict(gen_cfg)
        next_tc = dict(gen_cfg["thinkingConfig"])
        raw_tc_budget = next_tc.get("thinkingBudget", next_tc.get("thinking_budget"))
        if isinstance(raw_tc_budget, int) and not isinstance(raw_tc_budget, bool) and raw_tc_budget >= effective_cap:
            if safe_thinking_cap >= 64:
                if "thinkingBudget" in next_tc:
                    next_tc["thinkingBudget"] = safe_thinking_cap
                if "thinking_budget" in next_tc:
                    next_tc["thinking_budget"] = safe_thinking_cap
            else:
                next_tc.pop("thinkingBudget", None)
                next_tc.pop("thinking_budget", None)
        next_gen["thinkingConfig"] = next_tc
        out["generationConfig"] = next_gen

    return out


#: Anthropic refuses an enabled ``budget_tokens`` below this value, and requires
#: ``max_tokens`` to exceed the budget.
ANTHROPIC_MIN_THINKING_BUDGET = 1024


def clamp_anthropic_thinking_budget(
    payload: dict[str, Any],
    *,
    enforce_min_budget: bool = True,
) -> dict[str, Any]:
    """Make an enabled Anthropic ``thinking`` record acceptable to the API.

    Anthropic enforces three strict constraints when extended thinking is on:
    1. ``budget_tokens >= 1024`` on official Anthropic endpoints.
    2. ``max_tokens > budget_tokens``.
    3. ``temperature`` (other than 1), ``top_k``, and ``top_p < 0.95`` are
       rejected with HTTP 400.
    """
    thinking = payload.get("thinking")
    if not isinstance(thinking, dict):
        return payload
    if str(thinking.get("type") or "").strip().lower() != "enabled":
        return payload

    out = dict(payload)
    next_thinking = dict(thinking)
    budget = next_thinking.get("budget_tokens", next_thinking.get("budgetTokens"))
    if isinstance(budget, int) and not isinstance(budget, bool):
        clamped_budget = (
            max(budget, ANTHROPIC_MIN_THINKING_BUDGET) if enforce_min_budget else max(budget, 1)
        )
        next_thinking.pop("budgetTokens", None)
        next_thinking["budget_tokens"] = clamped_budget
        max_tokens = out.get("max_tokens")
        if (
            isinstance(max_tokens, int)
            and not isinstance(max_tokens, bool)
            and max_tokens <= clamped_budget
        ):
            out["max_tokens"] = clamped_budget + 1024
    out["thinking"] = next_thinking
    temp = out.get("temperature")
    if temp is not None and temp != 1:
        out.pop("temperature", None)
    out.pop("top_k", None)
    top_p = out.get("top_p")
    if isinstance(top_p, (int, float)) and not isinstance(top_p, bool) and top_p < 0.95:
        out.pop("top_p", None)
    return out


# --- unsupported-parameter repair ---------------------------------------------
# Reasoning models on the OpenAI chat wire refuse parameters the runtime sends
# by default: ``max_tokens`` ("use max_completion_tokens instead") and a
# non-default ``temperature``. The provider names the offending parameter in its
# HTTP 400, so one repaired replay is exact rather than guesswork.

_MAX_TOKENS_PARAM_RE = re.compile(r"\bmax_tokens\b", re.IGNORECASE)
_TEMPERATURE_PARAM_RE = re.compile(r"\btemperature\b", re.IGNORECASE)


def chat_parameter_repairs(error: BaseException) -> tuple[str, ...]:
    """Parameters an upstream HTTP 400 explicitly named as unsupported.

    Returns any of ``("max_tokens", "temperature")``; ``()`` when the failure is
    not a parameter rejection, so unrelated errors keep their normal handling.
    """
    status = _status_code(error)
    if status is not None and status != 400:
        return ()
    text = _error_text(error)
    if not text or not _REJECTION_RE.search(text):
        return ()
    repairs: list[str] = []
    if _MAX_TOKENS_PARAM_RE.search(text):
        repairs.append("max_tokens")
    if _TEMPERATURE_PARAM_RE.search(text):
        repairs.append("temperature")
    return tuple(repairs)


def repair_chat_parameters(
    payload: dict[str, Any], repairs: tuple[str, ...]
) -> dict[str, Any] | None:
    """Rebuild ``payload`` without the named parameters.

    ``max_tokens`` moves to ``max_completion_tokens`` (same value), which is the
    documented replacement; ``temperature`` is simply omitted so the model's
    default applies. Returns ``None`` when nothing there is left to repair.
    """
    if not repairs:
        return None
    out = dict(payload)
    changed = False
    if "max_tokens" in repairs and "max_tokens" in out and "max_completion_tokens" not in out:
        out["max_completion_tokens"] = out.pop("max_tokens")
        changed = True
    if "temperature" in repairs and "temperature" in out:
        out.pop("temperature")
        changed = True
    return out if changed else None
