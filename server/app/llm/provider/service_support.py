"""Pure helpers shared by the provider service (extracted §五十二)."""

from __future__ import annotations

from typing import Any

from ...core.models import ProviderModelTokenLimit
from .assessment import _as_mapping


def optional_text(value: object | None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def positive_int(value: object | None) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else None
    if isinstance(value, str):
        normalized = value.strip().replace("_", "")
        if normalized.isdigit():
            parsed = int(normalized)
            return parsed if parsed > 0 else None
    return None


def extract_model_token_limit(value: object | None) -> ProviderModelTokenLimit | None:
    record = _as_mapping(value)
    if not record:
        return None

    context_window_tokens = next(
        (
            parsed
            for parsed in (
                positive_int(record.get("context_window_tokens")),
                positive_int(record.get("contextWindowTokens")),
                positive_int(record.get("context_window")),
                positive_int(record.get("contextWindow")),
                positive_int(record.get("context_length")),
                positive_int(record.get("contextLength")),
                positive_int(record.get("max_context_length")),
                positive_int(record.get("maxContextLength")),
                positive_int(record.get("max_model_len")),
                positive_int(record.get("maxModelLen")),
                positive_int(record.get("max_sequence_length")),
                positive_int(record.get("maxSequenceLength")),
                positive_int(record.get("input_token_limit")),
                positive_int(record.get("inputTokenLimit")),
                positive_int(record.get("input_tokens")),
            )
            if parsed is not None
        ),
        None,
    )
    max_output_tokens = next(
        (
            parsed
            for parsed in (
                positive_int(record.get("max_output_tokens")),
                positive_int(record.get("maxOutputTokens")),
                positive_int(record.get("output_token_limit")),
                positive_int(record.get("outputTokenLimit")),
                positive_int(record.get("max_completion_tokens")),
                positive_int(record.get("maxCompletionTokens")),
                positive_int(record.get("max_tokens")),
                positive_int(record.get("maxTokens")),
                positive_int(record.get("max_new_tokens")),
                positive_int(record.get("maxNewTokens")),
            )
            if parsed is not None
        ),
        None,
    )
    if context_window_tokens is None and max_output_tokens is None:
        return None

    return ProviderModelTokenLimit(
        contextWindowTokens=context_window_tokens,
        maxOutputTokens=max_output_tokens,
    )


def agent_tool_events(result: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for step in list(getattr(result, "steps", []) or []):
        step_index = getattr(step, "index", -1)
        for call in list(getattr(step, "tool_calls", []) or []):
            if isinstance(call, dict):
                events.append({"type": "tool_call", **call, "step": step_index})
        for tool_result in list(getattr(step, "tool_results", []) or []):
            if isinstance(tool_result, dict):
                events.append({"type": "tool_result", **tool_result, "step": step_index})
    return events


def agentic_recoverable_grounded_stop_reason(stop_reason: object) -> str:
    normalized = str(stop_reason or "").strip()
    return normalized if normalized in {"max_steps", "no_progress"} else ""


def timeout_recovery_should_replace_content(content: str) -> bool:
    """Whether a timeout may replace the visible reply with the recovery text.

    A later agent step can time out after earlier steps already produced a
    substantive answer. Replacing that answer with the generic timeout notice
    loses real progress. The recovery still supplies summary/next-step; it only
    owns the visible body when what we have is empty or a short fragment.
    """
    text = content.strip()
    if not text:
        return True
    return len(text) < 120
