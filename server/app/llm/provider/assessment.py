"""Response assessment helpers (§五十二: extracted from provider_service.py)."""

from __future__ import annotations

from typing import Any


def _unusable_visible_reply_category(
    *,
    hidden_reasoning_observed: bool,
    reasoning_budget_exhausted: bool = False,
) -> str:
    """Classify a provider reply that carried no usable visible text.

    ``reasoning_budget_exhausted`` separates "the model's hidden reasoning
    consumed the whole output budget" (retryable; a larger output budget or a
    non-reasoning model helps) from "the model answered with hidden reasoning
    only" (a model/protocol choice issue). The non-exhausted reasoning case
    keeps the historical ``reasoning_leak`` name that downstream matchers rely
    on.
    """
    if not hidden_reasoning_observed:
        return "empty_response"
    if reasoning_budget_exhausted:
        return "reasoning_budget_exhausted"
    return "reasoning_leak"


def _usage_output_tokens(response: object | None) -> int | None:
    """Best-effort read of billed output (completion) tokens from a provider response."""
    usage = getattr(response, "usage", None)
    if usage is None:
        response_record = _as_mapping(response)
        usage = response_record.get("usage") if response_record else None
    usage_record = _as_mapping(usage)
    if usage_record is None:
        return None
    for field_name in ("completion_tokens", "output_tokens", "completionTokens", "outputTokens"):
        value = usage_record.get(field_name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value > 0:
            return int(value)
    return None


def _as_mapping(value: object | None) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    if value is None:
        return None

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
        except TypeError:
            dumped = model_dump(mode="python")
        if isinstance(dumped, dict):
            return dumped

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        dumped = to_dict()
        if isinstance(dumped, dict):
            return dumped

    model_extra = getattr(value, "model_extra", None)
    if isinstance(model_extra, dict):
        mapped = dict(model_extra)
        for field_name in ("id", "name"):
            field_value = getattr(value, field_name, None)
            if field_value is not None and field_name not in mapped:
                mapped[field_name] = field_value
        return mapped
    return None


def _reasoning_budget_exhausted(response: object | None, *, max_tokens: int | None) -> bool:
    """Conservative signal that hidden reasoning consumed the entire output budget."""
    if not max_tokens or max_tokens <= 0:
        return False
    output_tokens = _usage_output_tokens(response)
    return output_tokens is not None and output_tokens >= max_tokens
