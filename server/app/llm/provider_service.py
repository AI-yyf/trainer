from __future__ import annotations

import asyncio
import hashlib
import json
import re
import socket
from contextvars import ContextVar
from importlib import import_module
from time import monotonic
from types import SimpleNamespace
from typing import Any, Callable, cast
from urllib.parse import quote, urlsplit

import httpx

from ..core.models import (
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderModelsResponse,
    ProviderModelTokenLimit,
    ProviderProbeUsage,
    ProviderProtocol,
    ProviderTestResponse,
    UserProfile,
)
from .agent_tool_context import (
    _build_agent_tool_context_extra,
)
from .coaching_first_turn import (
    _compact_first_turn_reply,
    _first_turn_concrete_followthrough,
    _first_turn_guided_lane,
    _first_turn_lane_continuity_note,
    _first_turn_lane_next_step,
    _fresh_lane_comparison_requested,
    _resolve_first_turn_guided_lane,
    _should_offer_generic_first_turn_lane_prompt,
)
from .coaching_patches import (
    _build_empty_reply_override,
    _compose_principle_followthrough_patch,
    _compose_scaffold_paragraphs,
    _guided_domain_empty_reply_override,
    _maybe_auto_verify_practice_current_file,
    _normalize_visible_resume_thread_text,
    _scaffold_next_step,
    _structured_view_visible_reply_needs_repair,
)
from .coaching_recovery import (
    _GUIDED_DOMAIN_SCENARIOS,
    _agentic_resume_thread_text,
    _build_active_view_recovery_override,
    _build_language_corruption_recovery_override,
    _build_provider_error_recovery_override,
    _build_timeout_recovery_override,
    _coaching_active_view_name,
    _localized_text,
    _prefers_chinese,
    _trim_sentence,
)
from .coaching_replies import (
    _agentic_completion_continuity,
    _agentic_fallback_continuity,
    _agentic_practice_completion_guard,
    _clean_provider_failure_next_step,
    _clean_provider_failure_reply,
    _clean_provider_failure_summary,
    _current_file_practice_verification_result,
    _extract_next_step_hint_text,
    _fresh_lane_marker_map,
    _prefer_structured_next_step,
    _reply_has_guided_lane_signal,
    _sanitize_agentic_continuity_text,
    _stream_holdback_chars,
    _strip_fresh_lane_cross_lane_carryover,
    _strip_internal_coach_meta,
)
from .coaching_reply_drafts import (
    _agent_loop_max_steps,
    _agent_result_visible_text,
    _agentic_has_grounded_resource_evidence,
    _append_unique_paragraphs,
    _clean_provider_service_error_reply,
    _clean_provider_service_missing_api_key_reply,
    _clean_provider_service_onboarding_reply,
    _compose_recalled_memory_patch,
    _compose_review_tightening_patch,
    _compose_success_signal_patch,
    _fresh_lane_reanchor_reply,
    _guided_domain_empty_reply,
    _message_probe_variant,
    _provider_service_error_reply,
    _provider_service_missing_api_key_reply,
    _provider_service_onboarding_reply,
    _reanchor_visible_reply_to_current_request,
    _reply_needs_first_turn_reframe,
    _scaffold_close,
    _should_preserve_visible_reply,
    _strip_generic_lane_prompt_artifacts,
)
from .coaching_scaffold import (
    _scaffold_anchor,
    _scaffold_diagnosis,
    _scaffold_teaching_note,
)
from .harness import extract_provider_usage
from .prompts import (
    _truncate_coaching_history_content,
    build_coaching_messages,
    extract_coaching_context,
    infer_learner_signal,
    normalize_answer_policy,
)
from .provider.assessment import (
    _as_mapping,
    _reasoning_budget_exhausted,
    _unusable_visible_reply_category,
)
from .provider.capability import (
    _flatten_minimax_thinking_for_raw_http,
    _is_kimi_like_provider,
    _is_loopback_provider_url,
    _is_minimax_like_provider,
    _model_looks_reasoning_first,
    _needs_generous_visible_probe_budget,
    _normalized_provider_request_defaults,
    _should_fingerprint_gateway,
    _visible_probe_max_tokens,
)
from .provider.errors import ContextBudgetExhaustedError, ProviderRuntimeResponseError
from .provider.redaction import _compact_text, redact_provider_error
from .provider.streaming import (
    _await_provider_stream_with_cancellation,
    _iterate_provider_stream_with_cancellation,
    _stream_cancel_event,
)
from .provider.text import (
    _QUESTION_RUN_PATTERN,
    _THINK_CLOSE_TAG_PATTERN,
    _compact_visible_text,
    _contains_cjk,
    _has_hidden_reasoning,
    _looks_like_input_corruption_reply,
    _looks_like_mojibake_text,
    _mixed_script_reply_corruption_detail,
    _reasoning_prefix_start,
    _strip_reasoning_blocks,
    _strip_short_cyrillic_noise,
    _trim_trailing_reasoning_prefix,
    _visible_model_text,
    _wrong_language_cjk_reply_detail,
)
from .provider.thinking import (
    apply_thinking_policy,
    declared_thinking,
    learned_policy,
    remember_policy,
    resolve_thinking_policy,
    thinking_rejection_policy,
)
from .provider_gateway import (
    catalog_endpoint_type_claims,
    gateway_fingerprint_diagnostics,
    inspect_provider_gateway_headers,
)
from .provider_protocols import (
    assess_provider_capabilities,
    assess_provider_tool_call_probe,
    normalize_provider_protocol,
    normalize_provider_response,
    provider_protocol_family,
    provider_protocol_required_capability,
)
from .vision_challenge import build_vision_challenge
from .vision_payload import openai_responses_input_image_parts

DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS = 45.0
DEFAULT_OPENAI_CLIENT_MAX_RETRIES = 0
MIN_OPENAI_CLIENT_TIMEOUT_SECONDS = 5.0
DEFAULT_COACHING_MAX_OUTPUT_TOKENS = 1024
MIN_CONTEXT_OUTPUT_TOKENS = 128
CONTEXT_BUDGET_SAFETY_TOKENS = 256
_TOOL_CAPABILITY_PROBE_NAME = "trainer_capability_probe"
_TOOL_CAPABILITY_PROBE_PROMPT = (
    "Call the supplied trainer_capability_probe tool now with probe set to ok. "
    "Do not call external services and do not return text."
)



# _compact_text is imported from .provider.redaction above (§五十二 extraction).


def _optional_text(value: object | None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


_PROVIDER_SECRET_NAME_PATTERN = re.compile(
    r"(?:api[-_]?key|access[-_]?token|auth(?:orization)?|token|secret|password|client[-_]?secret|key)",
    re.IGNORECASE,
)
_PROVIDER_SECRET_FIELD_PATTERN = re.compile(
    r"(?P<name>\b(?:api[-_]?key|access[-_]?token|auth(?:orization)?|token|secret|password|client[-_]?secret|key)\b)"
    r"(?P<separator>\s*[:=]\s*)(?P<value>\"[^\"]*\"|'[^']*'|[^,\s}\]]+)",
    re.IGNORECASE,
)
_PROVIDER_QUERY_CREDENTIAL_PATTERN = re.compile(
    r"(?P<prefix>[?&](?:[a-z0-9]+[-_])*(?:api[-_]?key|access[-_]?token|auth(?:orization)?|token|secret|password|client[-_]?secret|key)=)"
    r"[^&#\s]+",
    re.IGNORECASE,
)
_PROVIDER_BEARER_TOKEN_PATTERN = re.compile(r"\bBearer\s+[^\s,;]+", re.IGNORECASE)
_PROVIDER_UPSTREAM_BODY_PATTERN = re.compile(
    r"(?P<prefix>\b(?:upstream|provider|response)\s+(?:body|payload|content)\s*(?:[:=]|was|is)\s*)"
    r"(?P<body>.+)",
    re.IGNORECASE | re.DOTALL,
)
_PROVIDER_TRACEBACK_PATTERN = re.compile(
    r"Traceback \(most recent call last\)|File \"[^\"]+\", line \d+|^\s+at \S+",
    re.IGNORECASE | re.MULTILINE,
)
_PROVIDER_THINK_PATTERN = re.compile(
    r"<think\b[^>]*>.*?</think>|reasoning_content|redactedthinking",
    re.IGNORECASE | re.DOTALL,
)


# redact_provider_error imported from .provider.redaction above (§五十二).

# _as_mapping, _unusable_visible_reply_category, _usage_output_tokens, and
# _reasoning_budget_exhausted are imported from .provider.assessment above
# (§五十二 extraction).


def _positive_int(value: object | None) -> int | None:
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


def _extract_model_token_limit(value: object | None) -> ProviderModelTokenLimit | None:
    record = _as_mapping(value)
    if not record:
        return None

    context_window_tokens = next(
        (
            parsed
            for parsed in (
                _positive_int(record.get("context_window_tokens")),
                _positive_int(record.get("contextWindowTokens")),
                _positive_int(record.get("context_window")),
                _positive_int(record.get("contextWindow")),
                _positive_int(record.get("context_length")),
                _positive_int(record.get("contextLength")),
                _positive_int(record.get("max_context_length")),
                _positive_int(record.get("maxContextLength")),
                _positive_int(record.get("max_model_len")),
                _positive_int(record.get("maxModelLen")),
                _positive_int(record.get("max_sequence_length")),
                _positive_int(record.get("maxSequenceLength")),
                _positive_int(record.get("input_token_limit")),
                _positive_int(record.get("inputTokenLimit")),
                _positive_int(record.get("input_tokens")),
            )
            if parsed is not None
        ),
        None,
    )
    max_output_tokens = next(
        (
            parsed
            for parsed in (
                _positive_int(record.get("max_output_tokens")),
                _positive_int(record.get("maxOutputTokens")),
                _positive_int(record.get("output_token_limit")),
                _positive_int(record.get("outputTokenLimit")),
                _positive_int(record.get("max_completion_tokens")),
                _positive_int(record.get("maxCompletionTokens")),
                _positive_int(record.get("max_tokens")),
                _positive_int(record.get("maxTokens")),
                _positive_int(record.get("max_new_tokens")),
                _positive_int(record.get("maxNewTokens")),
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


_MOJIBAKE_FALLBACK_MARKERS = (
    "\ufffd",
    "\ue000",
    "\ue1ec",
    "锟",
    "闂",
    "濠",
    "閻",
    "缂",
    "鈧",
    "鐢",
    "鍙",
    "鏂",
    "瀹",
    "涓",
    "浣",
    "璇",
    "骞",
    "搴",
    "绠",
    "鎴",
    "灏",
    "鏄",
    "杩",
    "鍏",
    "鐩",
    "閸",
    "鐠",
    "娑",
)
_LATIN1_MOJIBAKE_PATTERN = re.compile(
    r"(?:[\u00C2\u00C3\u00C4\u00C5\u00C6\u00C7\u00C8\u00C9\u00CF\u00D0\u00E2\u00E3\u00E4\u00E5\u00E6\u00E7\u00E8\u00E9\u00EF\u00F0][\u0080-\u00BF]{1,2}){2,}"
)


_THINK_BLOCK_PATTERN = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_THINK_TAG_PATTERN = re.compile(r"</?think\b[^>]*>", re.IGNORECASE | re.DOTALL)
_PROVIDER_CONTROL_MARKER_PATTERN = re.compile(
    r"\]\s*<\]\s*minimax\s*\[>\s*\[",
    re.IGNORECASE | re.DOTALL,
)
_PSEUDO_TOOL_CALL_BLOCK_PATTERN = re.compile(
    r"<tool_call\b[^>]*>.*?(?:</tool_call\s*>|$)",
    re.IGNORECASE | re.DOTALL,
)
_PSEUDO_TOOL_CALL_TAG_PATTERN = re.compile(r"</?tool_call\b[^>]*>", re.IGNORECASE | re.DOTALL)
_VISIBLE_MODEL_PUNCTUATION_MAP = str.maketrans(
    {
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
    }
)
_CJK_CHAR_PATTERN = re.compile(r"[\u3400-\u9fff]")
_LATIN_CHAR_PATTERN = re.compile(r"[A-Za-z]")
_CYRILLIC_CHAR_PATTERN = re.compile(r"[\u0400-\u04FF]")
_LANGUAGE_PROBE_VARIANTS = (
    (
        "Repeat exactly: \u4e0d\u8981\u76f4\u63a5\u8003\u8bd5\uff0c\u5148\u5b66\u518d\u6d4b\u3002\u8bf7\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\u3002ABC123",
        "\u4e0d\u8981\u76f4\u63a5\u8003\u8bd5\uff0c\u5148\u5b66\u518d\u6d4b\u3002\u8bf7\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\u3002ABC123",
    ),
    (
        "\u8bfb\u8fd9\u53e5\u8bdd\uff0c\u53ea\u56de\u590d\u6700\u540e\u56db\u4e2a\u6c49\u5b57\uff0c\u4e0d\u8981\u89e3\u91ca\uff1a\u4e0d\u8981\u76f4\u63a5\u8003\u8bd5\uff0c\u5148\u7528\u6700\u5c0f\u6559\u5b66\u6b65\u9aa4\u6559\u6211\u5982\u4f55\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\uff0c\u518d\u7ed9\u6211\u4e00\u4e2a\u5f88\u5c0f\u7684\u9a8c\u8bc1\u52a8\u4f5c",
        "\u9a8c\u8bc1\u52a8\u4f5c",
    ),
)
_NATURAL_LANGUAGE_PROBE_PROMPT = (
    "只用简体中文回答一句话，并完整保留“先学再测”和“VS Code”。不要解释，不要加引号。"
)
_NATURAL_LANGUAGE_PROBE_FRAGMENTS = ("先学再测", "VS Code")


# ProviderRuntimeResponseError and ContextBudgetExhaustedError are
# imported from .provider.errors above (§五十二 extraction).


def _require_provider_runtime_response(
    protocol: str | None,
    response: object | None,
    *,
    api_key: str | None,
    allow_tool_calls: bool = False,
    allow_local_empty_fallback: bool = False,
) -> str:
    """Return only coach-ready text or raise a redacted runtime failure.

    Protocol response normalization already separates visible text from hidden
    reasoning, truncated output, provider errors, and incompatible payload
    shapes. Runtime callers must not collapse those states into an empty
    string and accidentally treat the turn as a usable coaching response.
    """
    assessment = normalize_provider_response(protocol, response, api_key=api_key)
    if assessment.outcome == "visible_text":
        return assessment.content
    if allow_tool_calls and assessment.outcome == "tool_calls":
        return ""
    if allow_local_empty_fallback and assessment.outcome in {"empty_response", "reasoning_only"}:
        return ""
    raise ProviderRuntimeResponseError(
        category=assessment.error_category or assessment.outcome,
        detail=assessment.diagnostic,
        retryable=assessment.retryable,
    )


_LEADING_HTML_SHELL_PATTERN = re.compile(
    r"^\s*(?:<!doctype\s+html\b[\s\S]*?</html>|<html\b[\s\S]*?</html>)\s*",
    re.IGNORECASE,
)
_PROVIDER_HTML_SHELL_MARKERS = (
    '<div id="root"></div>',
    "<div id='root'></div>",
    '<div id="app"></div>',
    "<div id='app'></div>",
    "<title>new api</title>",
    "unified ai api gateway",
    "/static/js/",
    "/static/css/",
)


def _looks_like_provider_html_shell(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if not (lowered.startswith("<!doctype html") or lowered.startswith("<html")):
        return False
    marker_hits = sum(1 for marker in _PROVIDER_HTML_SHELL_MARKERS if marker in lowered)
    return marker_hits >= 1 or ("<head" in lowered and "<body" in lowered)


def _strip_leading_html_shell_artifact(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    stripped = _LEADING_HTML_SHELL_PATTERN.sub("", cleaned, count=1).strip()
    if stripped:
        return stripped
    if _looks_like_provider_html_shell(cleaned):
        return ""
    return cleaned


def _malformed_provider_html_shell_detail() -> str:
    return (
        "Provider returned an HTML app shell instead of a chat payload. "
        "Check the base URL and protocol."
    )


def _agent_tool_events(result: Any) -> list[dict[str, Any]]:
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


def _agentic_recoverable_grounded_stop_reason(stop_reason: object) -> str:
    normalized = str(stop_reason or "").strip()
    return normalized if normalized in {"max_steps", "no_progress"} else ""


class _ReasoningBlockFilter:
    def __init__(self) -> None:
        self._buffer = ""
        self._inside_think = False

    def push(self, chunk: str) -> str:
        self._buffer += chunk
        emitted: list[str] = []

        while self._buffer:
            if self._inside_think:
                close_match = _THINK_CLOSE_TAG_PATTERN.search(self._buffer)
                if close_match:
                    self._buffer = self._buffer[close_match.end() :]
                    self._inside_think = False
                    continue

                tail_length = len("</think>") - 1
                if len(self._buffer) > tail_length:
                    self._buffer = self._buffer[-tail_length:]
                break

            open_match = _THINK_BLOCK_PATTERN.search(self._buffer)
            if open_match:
                emitted.append(self._buffer[: open_match.start()])
                self._buffer = self._buffer[open_match.end() :]
                continue

            start_match = re.search(r"<think\b[^>]*>", self._buffer, re.IGNORECASE | re.DOTALL)
            if start_match:
                emitted.append(self._buffer[: start_match.start()])
                self._buffer = self._buffer[start_match.end() :]
                self._inside_think = True
                continue

            prefix_start = _reasoning_prefix_start(self._buffer)
            if prefix_start is None:
                emitted.append(self._buffer)
                self._buffer = ""
            elif prefix_start > 0:
                emitted.append(self._buffer[:prefix_start])
                self._buffer = self._buffer[prefix_start:]
            break

        return "".join(emitted)

    def flush(self) -> str:
        if self._inside_think:
            self._buffer = ""
            self._inside_think = False
            return ""
        buffered = _trim_trailing_reasoning_prefix(self._buffer)
        self._buffer = ""
        return _strip_reasoning_blocks(buffered)


def _probe_usage_payload(response: object | None) -> ProviderProbeUsage | None:
    """Echo provider-reported usage from a live probe response.

    Never estimates: when the provider did not report usage (or cost detail),
    the field stays None so the UI can hide it instead of fabricating numbers.
    """
    usage = extract_provider_usage(response)
    if usage is None:
        return None
    return ProviderProbeUsage(
        inputTokens=usage.input_tokens,
        outputTokens=usage.output_tokens,
        totalTokens=usage.total_tokens,
        inputCost=usage.input_cost,
        outputCost=usage.output_cost,
        totalCost=usage.total_cost,
    )


class ProviderService:
    _MODEL_CACHE_TTL_SECONDS = 30.0
    _LANGUAGE_INTEGRITY_SUCCESS_TTL_SECONDS = 60.0 * 10.0

    def __init__(
        self,
        config: ProviderConfig | None = None,
        api_key: str | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._client: Any | None = None
        self._models_cache: dict[tuple[str, str], tuple[float, ProviderModelsResponse]] = {}
        self._capability_truth: dict[str, str] = {}
        self._language_integrity_success: dict[str, float] = {}
        self._last_reply_failure: ContextVar[dict[str, Any] | None] = ContextVar(
            f"provider_service_last_reply_failure_{id(self)}",
            default=None,
        )
        self._last_reply_override: ContextVar[dict[str, Any] | None] = ContextVar(
            f"provider_service_last_reply_override_{id(self)}",
            default=None,
        )
        self._last_stream_finalization: ContextVar[tuple[str, str] | None] = ContextVar(
            f"provider_service_last_stream_finalization_{id(self)}",
            default=None,
        )
        self._agent_context_budget_states: dict[
            int,
            dict[str, ContextBudgetExhaustedError | None],
        ] = {}

    def apply_observed_capability_states(self, states: dict[str, str] | None) -> None:
        if not states:
            return
        observed: dict[str, str] = {}
        for raw_name, raw_state in states.items():
            name = str(raw_name or "").strip().lower()
            state = str(raw_state or "").strip().lower()
            if name and state:
                observed[name] = state
        if observed:
            self._capability_truth = {**self._capability_truth, **observed}

    def replace_observed_capability_states(self, states: dict[str, str] | None) -> None:
        """Replace last-test truth from the sidecar cache snapshot.

        Merge would keep a prior tools=verified overlay after a failed retest.
        """
        observed: dict[str, str] = {}
        for raw_name, raw_state in (states or {}).items():
            name = str(raw_name or "").strip().lower()
            state = str(raw_state or "").strip().lower()
            if name and state:
                observed[name] = state
        self._capability_truth = observed

    def supports_executable_tools(self) -> bool:
        """Return whether this live connection can run the tool loop.

        Template flags may pin ``tools`` false for OpenAI-compatible defaults.
        A successful connection test that recorded tools as verified overlays
        that pin so coach/library/plan loops can run.
        """
        if not self.has_api_key:
            return False
        truth = str(self._capability_truth.get("tools") or "").strip().lower()
        if truth == "verified":
            return True
        if truth in {"unsupported", "disabled"}:
            return False
        capabilities = getattr(self._config, "capabilities", None)
        return bool(capabilities is not None and getattr(capabilities, "tools", False))

    @property
    def has_api_key(self) -> bool:
        return bool(self._api_key)

    def clear_last_reply_state(self) -> None:
        self.clear_last_reply_failure()
        self.clear_last_reply_override()
        self._last_stream_finalization.set(None)

    def clear_last_reply_failure(self) -> None:
        self._last_reply_failure.set(None)

    def clear_last_reply_override(self) -> None:
        self._last_reply_override.set(None)

    def _record_stream_finalization(self, raw_content: str, final_content: str) -> None:
        self._last_stream_finalization.set((raw_content, final_content))

    def consume_stream_finalization(self) -> tuple[str, str] | None:
        finalization = self._last_stream_finalization.get()
        self._last_stream_finalization.set(None)
        return finalization

    def _agent_provider_context_budget_exhausted(self, provider: object) -> bool:
        state = self._agent_context_budget_states.get(id(provider))
        return isinstance(state, dict) and isinstance(state.get("error"), ContextBudgetExhaustedError)

    def _clear_agent_provider_context_budget_state(self, provider: object) -> None:
        self._agent_context_budget_states.pop(id(provider), None)

    def _language_integrity_cache_key(
        self,
        *,
        message: str | None = None,
        response_language: str | None = None,
    ) -> str | None:
        normalized_language = str(response_language or "").strip().lower()
        if normalized_language:
            if normalized_language.startswith("zh"):
                return "zh"
            return normalized_language
        if _contains_cjk(message):
            return "cjk"
        return None

    def has_recent_language_integrity_success(
        self,
        *,
        message: str | None = None,
        response_language: str | None = None,
    ) -> bool:
        cache_key = self._language_integrity_cache_key(
            message=message,
            response_language=response_language,
        )
        if not cache_key:
            return False
        cached_at = self._language_integrity_success.get(cache_key)
        if cached_at is None:
            return False
        if monotonic() - cached_at > self._LANGUAGE_INTEGRITY_SUCCESS_TTL_SECONDS:
            self._language_integrity_success.pop(cache_key, None)
            return False
        return True

    def mark_language_integrity_success(
        self,
        *,
        message: str | None = None,
        response_language: str | None = None,
    ) -> None:
        cache_key = self._language_integrity_cache_key(
            message=message,
            response_language=response_language,
        )
        if not cache_key:
            return
        self._language_integrity_success[cache_key] = monotonic()

    def clear_language_integrity_success(
        self,
        *,
        message: str | None = None,
        response_language: str | None = None,
    ) -> None:
        cache_key = self._language_integrity_cache_key(
            message=message,
            response_language=response_language,
        )
        if not cache_key:
            return
        self._language_integrity_success.pop(cache_key, None)

    def peek_last_reply_failure(self) -> dict[str, Any] | None:
        failure = self._last_reply_failure.get()
        if not isinstance(failure, dict):
            return None
        return dict(failure)

    def consume_last_reply_failure(self) -> dict[str, Any] | None:
        failure = self.peek_last_reply_failure()
        self.clear_last_reply_failure()
        return failure

    def peek_last_reply_override(self) -> dict[str, Any] | None:
        override = self._last_reply_override.get()
        if not isinstance(override, dict):
            return None
        return dict(override)

    def consume_last_reply_override(self) -> dict[str, Any] | None:
        override = self.peek_last_reply_override()
        self.clear_last_reply_override()
        return override

    def _record_last_reply_failure(
        self,
        *,
        category: str,
        detail: str,
        retryable: bool,
        status_code: int | None,
        provider_reachable: bool,
        model_supported: bool | None,
        error: Exception,
    ) -> None:
        self._last_reply_failure.set(
            {
                "error_category": category,
                "detail": detail,
                "retryable": retryable,
                "status_code": status_code,
                "provider_reachable": provider_reachable,
                "model_supported": model_supported,
                "error": redact_provider_error(error, api_key=self._api_key),
            }
        )

    def _record_last_reply_override(self, **payload: Any) -> None:
        self._last_reply_override.set(dict(payload))


    def provider_failure_summary(self, category: str, response_language: str | None) -> str:
        summary_map: dict[str, tuple[str, str]] = {
            "invalid_key_or_permission": (
                "The provider rejected this turn's API key or permissions.",
                "这个 provider 拒绝了这轮请求使用的 API key 或 permission。",
            ),
            "model_unsupported": (
                "The provider reached the endpoint, but this model name is not accepted there.",
                "这个 provider 可以连通，但当前 model name 不被这个 endpoint 接受。",
            ),
            "model_not_found": (
                "The provider reached the gateway, but no available channel matched this model.",
                "这个 provider 可以连通，但 gateway 里没有可用 channel 能匹配当前 model。",
            ),
            "language_corruption": (
                "The provider returned a visibly corrupted coaching reply on this turn.",
                "这个 provider 可达，但这一轮返回了肉眼可见的乱码回复。",
            ),
            "malformed_response": (
                "The endpoint responded, but the payload was not a valid OpenAI-compatible response.",
                "这个 endpoint 有响应，但返回 payload 不是有效的 OpenAI-compatible response。",
            ),
            "truncated_or_empty": (
                "The provider ended the visible stream before a complete answer was available.",
                "provider \u5728\u5b8c\u6574\u8fd4\u56de\u4e4b\u524d\u5c31\u7ed3\u675f\u4e86\u6d41\uff0c\u8fd9\u4e00\u8f6e\u6ca1\u6709\u53ef\u4fe1\u7684\u5b8c\u6574\u7b54\u6848\u3002",
            ),
            "streaming_unavailable": (
                "The configured provider has no verified native streaming path for this turn.",
                "当前 provider 没有通过验证的原生流式路径，这一轮不能继续。",
            ),
            "rate_limit": (
                "The provider rate-limited this turn before Trainer could continue.",
                "这个 provider 对这轮请求触发了 rate limit，Trainer 暂时无法继续。",
            ),
            "timeout": (
                "Trainer could not get a response from the provider before the timeout.",
                "Trainer 在超时前没有从 provider 收到响应。",
            ),
            "network": (
                "Trainer could not reach the provider over the network.",
                "Trainer 目前无法通过 network 连到这个 provider。",
            ),
        }
        english, chinese = summary_map.get(
            category,
            (
                "Trainer is blocked on the provider path for this turn.",
                "Trainer 这轮被 provider path 卡住了。",
            ),
        )
        return _localized_text(english, chinese, response_language)

    def provider_failure_next_step(self, category: str, response_language: str | None) -> str:
        next_step_map: dict[str, tuple[str, str]] = {
            "invalid_key_or_permission": (
                "Check the API key or provider permissions, retest the connection, and resend this exact turn.",
                "先检查 API key 或 provider permission，重新测试连接后再重发这一轮。",
            ),
            "model_unsupported": (
                "Switch to a model name that this provider actually supports, retest, and resend this exact turn.",
                "先换成这个 provider 真的支持的 model name，重新测试后再重发这一轮。",
            ),
            "model_not_found": (
                "Pick a channel-backed model at this gateway, retest, and resend this exact turn.",
                "先换成这个 gateway 里真的有 channel 的 model，重新测试后再重发这一轮。",
            ),
            "language_corruption": (
                "Switch provider or gateway first, then resend this same turn after the visible corruption disappears.",
                "先切换 provider 或 gateway，确认乱码消失后再重发这一轮。",
            ),
            "malformed_response": (
                "Check that the endpoint really speaks the OpenAI-compatible protocol, then retest and resend this exact turn.",
                "先确认这个 endpoint 真的返回 OpenAI-compatible protocol，再测试并重发这一轮。",
            ),
            "truncated_or_empty": (
                "Retry with a shorter visible answer or raise the provider output limit, then resend this exact turn.",
                "\u5148\u7f29\u77ed\u53ef\u89c1\u7b54\u6848\u6216\u63d0\u9ad8 provider \u7684\u8f93\u51fa\u9650\u5236\uff0c\u7136\u540e\u91cd\u65b0\u53d1\u9001\u8fd9\u4e00\u8f6e\u3002",
            ),
            "streaming_unavailable": (
                "Choose a provider and model with verified native streaming in Settings, retest it, and resend this exact turn.",
                "先在设置里选择已验证支持原生流式的 provider 和 model，重新测试后再重发这一轮。",
            ),
            "rate_limit": (
                "Wait briefly, then retry this same turn once the rate limit clears.",
                "先等一会儿，等 rate limit 过去后再重试这一轮。",
            ),
            "timeout": (
                "Retry once after checking provider latency or gateway load.",
                "先检查 provider 延迟或 gateway 负载，再重试这一轮。",
            ),
            "network": (
                "Check the network path or proxy settings, then resend this exact turn.",
                "先检查 network 路径或 proxy 设置，再重发这一轮。",
            ),
        }
        english, chinese = next_step_map.get(
            category,
            (
                "Repair the provider path, then resend this exact coaching turn.",
                "先修好 provider path，再重发这一轮 coaching。",
            ),
        )
        return _localized_text(english, chinese, response_language)

    def provider_failure_reply(
        self,
        category: str,
        detail: str | None,
        response_language: str | None,
    ) -> str:
        detail_text = _compact_text(
            redact_provider_error({"upstream_body": detail}, api_key=self._api_key)
        )
        if _prefers_chinese(response_language):
            category_hint = {
                "invalid_key_or_permission": "先检查 API key / permission 是否有效。",
                "malformed_response": "先确认 endpoint 真正返回的是 OpenAI-compatible protocol。",
                "truncated_or_empty": "先缩短可见答案或提高 provider 的输出限制。",
                "rate_limit": "先等一会儿，再重试同一轮。",
                "model_unsupported": "先换一个这个 provider 支持的 model name。",
            }.get(category, "先修复 provider path，再重试同一轮。")
            lines = [
                "Trainer 目前卡在 provider path，暂时无法继续这轮 coaching。",
                "",
                category_hint,
            ]
            if detail_text:
                lines.append(f"详情: {detail_text}")
            lines.append("下一步：先把 provider 恢复到可用状态，再重新发送这轮。")
            return "\n".join(lines)

        summary = self.provider_failure_summary(category, response_language)
        next_step = self.provider_failure_next_step(category, response_language)
        if detail_text:
            return (
                "Trainer is blocked on the provider path, so I cannot continue this coaching turn yet.\n\n"
                f"{summary}\nDetail: {detail_text}\nNext: {next_step}"
            )
        return (
            "Trainer is blocked on the provider path, so I cannot continue this coaching turn yet.\n\n"
            f"{summary}\nNext: {next_step}"
        )

    def _load_openai_module(self) -> Any:
        return import_module("openai")

    def _get_async_openai_class(self) -> Any:
        openai_module = self._load_openai_module()
        return openai_module.AsyncOpenAI

    def _get_sync_openai_class(self) -> Any:
        openai_module = self._load_openai_module()
        return openai_module.OpenAI

    def _uses_loopback_transport(self, provider: ProviderConfig | None = None) -> bool:
        config = provider or self._config
        return _is_loopback_provider_url(getattr(config, "base_url", None))

    def _direct_http_client(self, provider: ProviderConfig, *, timeout: float) -> httpx.Client:
        return httpx.Client(
            timeout=timeout,
            # A local model or gateway must not be sent to an ambient corporate proxy.
            trust_env=not self._uses_loopback_transport(provider),
        )

    def _normalized_openai_compatible_base_url(
        self,
        provider: ProviderConfig | None = None,
    ) -> str | None:
        config = provider or self._config
        if config is None:
            return None
        raw_base_url = str(getattr(config, "base_url", "") or "").strip()
        if not raw_base_url:
            return None

        protocol = normalize_provider_protocol(getattr(config, "protocol", None))
        lowered = raw_base_url.lower().rstrip("/")
        if protocol == "gemini_generate_content" and "googleapis.com" in lowered:
            return raw_base_url
        if protocol == "anthropic_messages" and "anthropic.com" in lowered:
            return raw_base_url

        parsed = urlsplit(raw_base_url)
        path = (parsed.path or "").strip()
        lowered_path = path.lower().rstrip("/")
        if lowered_path.endswith("/v1") or lowered_path.endswith("/v1beta"):
            return raw_base_url

        needs_openai_compatible_root = protocol in {
            "openai_chat_completions",
            "openai_chat_completions_compatible",
            "openai_responses",
        } or (
            protocol == "gemini_generate_content" and "googleapis.com" not in lowered
        ) or (
            protocol == "anthropic_messages" and "anthropic.com" not in lowered
        )
        if not needs_openai_compatible_root:
            return raw_base_url
        if lowered_path not in {"", "/"}:
            return raw_base_url
        return f"{raw_base_url.rstrip('/')}/v1"

    def _get_client(self) -> Any:
        if self._client is None:
            async_openai_cls = self._get_async_openai_class()
            base_url = self._normalized_openai_compatible_base_url()
            client_kwargs: dict[str, Any] = {
                "api_key": self._api_key,
                "base_url": base_url,
                "timeout": self._provider_client_timeout_seconds(),
                "max_retries": self._provider_client_max_retries(),
            }
            if self._uses_loopback_transport():
                client_kwargs["http_client"] = httpx.AsyncClient(trust_env=False)
            self._client = async_openai_cls(**client_kwargs)
        return self._client

    def _create_sync_client(self, provider: ProviderConfig, api_key: str) -> Any:
        openai_cls = self._get_sync_openai_class()
        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": self._normalized_openai_compatible_base_url(provider),
            "timeout": self._provider_client_timeout_seconds(provider),
            "max_retries": self._provider_client_max_retries(provider),
        }
        if self._uses_loopback_transport(provider):
            client_kwargs["http_client"] = httpx.Client(trust_env=False)
        return openai_cls(**client_kwargs)

    def _provider_request_defaults(self, provider: ProviderConfig | None = None) -> dict[str, Any]:
        config = provider or self._config
        if config is None:
            return {}
        copied = _normalized_provider_request_defaults(config)
        context_window_tokens, max_output_tokens = self._configured_token_limits(config)
        if context_window_tokens is None and max_output_tokens is None:
            return copied

        output_token_keys = {
            "max_tokens",
            "maxTokens",
            "max_output_tokens",
            "maxOutputTokens",
            "max_completion_tokens",
            "maxCompletionTokens",
        }
        for key in output_token_keys:
            copied.pop(key, None)
        generation_config = copied.get("generationConfig")
        if isinstance(generation_config, dict):
            filtered_generation_config = {
                key: value
                for key, value in generation_config.items()
                if key not in {"maxOutputTokens", "maxTokens", "max_output_tokens", "max_tokens"}
            }
            if filtered_generation_config:
                copied["generationConfig"] = filtered_generation_config
            else:
                copied.pop("generationConfig", None)
        return copied

    @staticmethod
    def _raw_provider_request_defaults(provider: ProviderConfig | None) -> dict[str, Any]:
        return _normalized_provider_request_defaults(provider)

    @staticmethod
    def _request_default_max_output_tokens(defaults: dict[str, Any]) -> int | None:
        output_token_keys = {
            "max_tokens",
            "maxTokens",
            "max_output_tokens",
            "maxOutputTokens",
            "max_completion_tokens",
            "maxCompletionTokens",
        }
        resolved: int | None = None
        for key, value in defaults.items():
            if key in output_token_keys:
                parsed = _positive_int(value)
                if parsed is not None:
                    resolved = parsed
                continue
            if key == "generationConfig" and isinstance(value, dict):
                for nested_key in ("maxOutputTokens", "maxTokens", "max_output_tokens", "max_tokens"):
                    parsed = _positive_int(value.get(nested_key))
                    if parsed is not None:
                        resolved = parsed
        return resolved

    def _selected_model_token_limit(
        self,
        provider: ProviderConfig,
        model: str | None = None,
    ) -> ProviderModelTokenLimit | None:
        token_limits = getattr(provider, "model_token_limits", None)
        if not isinstance(token_limits, dict) or not token_limits:
            return None

        requested_model = (
            model.strip()
            if isinstance(model, str) and model.strip()
            else str(getattr(provider, "model", "") or "").strip() or self._resolve_model()
        )
        candidates = self._model_candidates(requested_model)
        by_lower = {
            name.strip().lower(): limit
            for name, limit in token_limits.items()
            if isinstance(name, str) and name.strip()
        }
        by_flat = {
            name.replace(".", "").replace("-", "").replace("_", ""): limit
            for name, limit in by_lower.items()
        }
        for candidate in candidates:
            normalized = candidate.lower()
            value = by_lower.get(normalized)
            if value is None:
                value = by_flat.get(normalized.replace(".", "").replace("-", "").replace("_", ""))
            limit = _extract_model_token_limit(value)
            if limit is not None:
                return limit
        return None

    def _configured_token_limits(
        self,
        provider: ProviderConfig | None = None,
        model: str | None = None,
    ) -> tuple[int | None, int | None]:
        config = provider or self._config
        if config is None:
            return None, None
        selected_limit = self._selected_model_token_limit(config, model)
        context_window_tokens = (
            _positive_int(getattr(selected_limit, "context_window_tokens", None))
            if selected_limit is not None
            else None
        )
        max_output_tokens = (
            _positive_int(getattr(selected_limit, "max_output_tokens", None))
            if selected_limit is not None
            else None
        )
        return (
            context_window_tokens
            if context_window_tokens is not None
            else _positive_int(getattr(config, "context_window_tokens", None)),
            max_output_tokens
            if max_output_tokens is not None
            else _positive_int(getattr(config, "max_output_tokens", None)),
        )

    @staticmethod
    def _estimate_request_input_tokens(messages: list[dict[str, Any]] | None) -> int:
        if not messages:
            return 0
        estimated_tokens = 32
        for message in messages:
            try:
                serialized = json.dumps(message, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                serialized = str(message)
            cjk_chars = sum(1 for character in serialized if "\u3400" <= character <= "\u9fff")
            non_cjk_chars = max(0, len(serialized) - cjk_chars)
            estimated_tokens += cjk_chars + ((non_cjk_chars + 3) // 4) + 16
        return estimated_tokens

    def _desired_output_token_budget(
        self,
        *,
        model: str | None = None,
        requested_max_tokens: int | None = None,
        prefer_configured_output: bool = False,
        provider: ProviderConfig | None = None,
    ) -> int:
        config = provider or self._config
        _context_window_tokens, configured_max_output_tokens = self._configured_token_limits(
            config,
            model,
        )
        default_max_output_tokens = self._request_default_max_output_tokens(
            self._raw_provider_request_defaults(config)
        )
        requested = _positive_int(requested_max_tokens)
        if prefer_configured_output:
            desired = (
                configured_max_output_tokens
                or default_max_output_tokens
                or requested
                or DEFAULT_COACHING_MAX_OUTPUT_TOKENS
            )
        else:
            desired = (
                default_max_output_tokens
                or requested
                or configured_max_output_tokens
                or DEFAULT_COACHING_MAX_OUTPUT_TOKENS
            )
        if configured_max_output_tokens is not None:
            desired = min(desired, configured_max_output_tokens)
        return max(1, desired)

    @staticmethod
    def _context_budget_safety_margin(
        *,
        desired_output_tokens: int,
        context_window_tokens: int,
    ) -> int:
        return max(
            CONTEXT_BUDGET_SAFETY_TOKENS,
            min(
                desired_output_tokens,
                max(MIN_CONTEXT_OUTPUT_TOKENS, context_window_tokens // 16),
            ),
        )

    def _available_output_token_budget(
        self,
        messages: list[dict[str, Any]] | None,
        *,
        desired_output_tokens: int,
        context_window_tokens: int,
    ) -> int:
        return (
            context_window_tokens
            - self._estimate_request_input_tokens(messages)
            - self._context_budget_safety_margin(
                desired_output_tokens=desired_output_tokens,
                context_window_tokens=context_window_tokens,
            )
        )

    @staticmethod
    def _minimum_visible_output_tokens(desired_output_tokens: int) -> int:
        return min(max(1, desired_output_tokens), MIN_CONTEXT_OUTPUT_TOKENS)

    @staticmethod
    def _essential_system_context(content: str) -> str:
        language_marker = "\n## Language\n"
        if language_marker in content:
            language_instruction = content.rsplit(language_marker, 1)[1].strip()
            if language_instruction:
                return (
                    "## Language\n"
                    + _truncate_coaching_history_content(language_instruction, token_budget=48).strip()
                )
        return "Answer the latest learner request directly and concisely."

    def _compact_message_content_for_context_budget(
        self,
        messages: list[dict[str, Any]],
        index: int,
        *,
        desired_output_tokens: int,
        minimum_output_tokens: int,
        context_window_tokens: int,
        preserved_content: str | None = None,
    ) -> bool:
        message = messages[index]
        original_content = message.get("content")
        if not isinstance(original_content, str):
            return False
        preserved = str(preserved_content or "").strip()

        def has_visible_budget() -> bool:
            return (
                self._available_output_token_budget(
                    messages,
                    desired_output_tokens=desired_output_tokens,
                    context_window_tokens=context_window_tokens,
                )
                >= minimum_output_tokens
            )

        message["content"] = preserved
        if not has_visible_budget():
            return False

        base_message = dict(message)
        source_message = {**message, "content": original_content}
        source_budget = max(
            1,
            self._estimate_request_input_tokens([source_message])
            - self._estimate_request_input_tokens([base_message]),
        )
        best_content = preserved
        low = 1
        high = source_budget
        while low <= high:
            candidate_budget = (low + high) // 2
            shortened_content = _truncate_coaching_history_content(
                original_content,
                token_budget=candidate_budget,
            )
            candidate_content = (
                f"{shortened_content}\n\n{preserved}" if preserved else shortened_content
            )
            message["content"] = candidate_content
            if has_visible_budget():
                best_content = candidate_content
                low = candidate_budget + 1
            else:
                high = candidate_budget - 1
        message["content"] = best_content
        return True

    def _compact_messages_for_context_budget(
        self,
        messages: list[dict[str, Any]],
        *,
        desired_output_tokens: int,
        minimum_output_tokens: int,
        context_window_tokens: int,
    ) -> list[dict[str, Any]]:
        compacted = [dict(message) for message in messages if isinstance(message, dict)]

        def has_visible_budget() -> bool:
            return (
                self._available_output_token_budget(
                    compacted,
                    desired_output_tokens=desired_output_tokens,
                    context_window_tokens=context_window_tokens,
                )
                >= minimum_output_tokens
            )

        if has_visible_budget() or not compacted:
            return compacted

        # Compress older turns before dropping them so a long thread still has
        # compressed recall instead of only the latest user message.
        last_index = len(compacted) - 1
        for index in range(last_index):
            if has_visible_budget():
                return compacted
            role = str(compacted[index].get("role") or "").strip().lower()
            if role in {"system", "developer"}:
                continue
            self._compact_message_content_for_context_budget(
                compacted,
                index,
                desired_output_tokens=desired_output_tokens,
                minimum_output_tokens=minimum_output_tokens,
                context_window_tokens=context_window_tokens,
            )

        if has_visible_budget():
            return compacted

        while not has_visible_budget() and len(compacted) > 1:
            first_role = str(compacted[0].get("role") or "").strip().lower()
            oldest_history_index = 1 if first_role in {"system", "developer"} else 0
            if oldest_history_index >= len(compacted) - 1:
                break
            del compacted[oldest_history_index]

        if has_visible_budget() or not compacted:
            return compacted

        for index, item in enumerate(compacted):
            role = str(item.get("role") or "").strip().lower()
            if role not in {"system", "developer"}:
                continue
            self._compact_message_content_for_context_budget(
                compacted,
                index,
                desired_output_tokens=desired_output_tokens,
                minimum_output_tokens=minimum_output_tokens,
                context_window_tokens=context_window_tokens,
                preserved_content=self._essential_system_context(str(item.get("content") or "")),
            )
            if has_visible_budget():
                return compacted

        current_message_index = len(compacted) - 1
        self._compact_message_content_for_context_budget(
            compacted,
            current_message_index,
            desired_output_tokens=desired_output_tokens,
            minimum_output_tokens=minimum_output_tokens,
            context_window_tokens=context_window_tokens,
        )
        return compacted

    def _prepare_context_budget(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        requested_max_tokens: int | None = None,
        prefer_configured_output: bool = False,
        provider: ProviderConfig | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        config = provider or self._config
        context_window_tokens, _configured_max_output_tokens = self._configured_token_limits(
            config,
            model,
        )
        desired_output_tokens = self._desired_output_token_budget(
            model=model,
            requested_max_tokens=requested_max_tokens,
            prefer_configured_output=prefer_configured_output,
            provider=config,
        )
        if context_window_tokens is None:
            return messages, desired_output_tokens

        minimum_output_tokens = self._minimum_visible_output_tokens(desired_output_tokens)
        available_output_tokens = self._available_output_token_budget(
            messages,
            desired_output_tokens=desired_output_tokens,
            context_window_tokens=context_window_tokens,
        )
        if available_output_tokens >= minimum_output_tokens:
            return messages, min(desired_output_tokens, available_output_tokens)

        compacted_messages = self._compact_messages_for_context_budget(
            messages,
            desired_output_tokens=desired_output_tokens,
            minimum_output_tokens=minimum_output_tokens,
            context_window_tokens=context_window_tokens,
        )
        available_output_tokens = self._available_output_token_budget(
            compacted_messages,
            desired_output_tokens=desired_output_tokens,
            context_window_tokens=context_window_tokens,
        )
        if available_output_tokens >= minimum_output_tokens:
            return compacted_messages, min(desired_output_tokens, available_output_tokens)

        raise ContextBudgetExhaustedError(
            context_window_tokens=context_window_tokens,
            input_tokens=self._estimate_request_input_tokens(compacted_messages),
            minimum_output_tokens=minimum_output_tokens,
        )

    def _effective_output_token_budget(
        self,
        messages: list[dict[str, Any]] | None,
        *,
        model: str | None = None,
        requested_max_tokens: int | None = None,
        prefer_configured_output: bool = False,
        provider: ProviderConfig | None = None,
    ) -> int:
        config = provider or self._config
        context_window_tokens, _configured_max_output_tokens = self._configured_token_limits(
            config,
            model,
        )
        desired = self._desired_output_token_budget(
            model=model,
            requested_max_tokens=requested_max_tokens,
            prefer_configured_output=prefer_configured_output,
            provider=config,
        )
        if context_window_tokens is None:
            return desired

        minimum_output_tokens = self._minimum_visible_output_tokens(desired)
        available_output_tokens = self._available_output_token_budget(
            messages,
            desired_output_tokens=desired,
            context_window_tokens=context_window_tokens,
        )
        if available_output_tokens < minimum_output_tokens:
            raise ContextBudgetExhaustedError(
                context_window_tokens=context_window_tokens,
                input_tokens=self._estimate_request_input_tokens(messages),
                minimum_output_tokens=minimum_output_tokens,
            )
        return min(desired, available_output_tokens)

    def _context_budget_status_reply(self, response_language: str | None) -> str:
        return _localized_text(
            (
                "This content is too long to leave enough room for a complete reply right now. "
                "Shorten this message or continue in a new, more focused conversation."
            ),
            (
                "\u8fd9\u6b21\u5185\u5bb9\u592a\u957f\uff0c\u6682\u65f6\u65e0\u6cd5\u7559\u51fa\u8db3\u591f\u7a7a\u95f4\u751f\u6210\u5b8c\u6574\u56de\u7b54\u3002"
                "\u8bf7\u7f29\u77ed\u672c\u6b21\u5185\u5bb9\u6216\u4ece\u65b0\u7684\u5bf9\u8bdd\u7ee7\u7eed\u3002"
            ),
            response_language,
        )

    def _context_budget_agentic_result(
        self,
        *,
        response_language: str | None,
        attachment_delivery: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "content": self._context_budget_status_reply(response_language),
            "steps": [],
            "summary": None,
            "next_step": None,
            "stop_reason": "context_budget_exhausted",
            "tool_events": [],
            "fell_back": False,
            **attachment_delivery,
        }

    def _coaching_output_token_budget(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
    ) -> int:
        return self._effective_output_token_budget(
            messages,
            model=model,
            prefer_configured_output=True,
        )

    @staticmethod
    def _request_default_number(value: object | None) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return float(stripped)
            except ValueError:
                return None
        return None

    def _provider_client_timeout_seconds(self, provider: ProviderConfig | None = None) -> float:
        defaults = self._provider_request_defaults(provider)
        for key in (
            "clientTimeoutSeconds",
            "client_timeout_seconds",
            "timeoutSeconds",
            "timeout_seconds",
            "timeout",
        ):
            resolved = self._request_default_number(defaults.get(key))
            if resolved is not None:
                return max(MIN_OPENAI_CLIENT_TIMEOUT_SECONDS, resolved)
        config = provider or self._config
        if _is_kimi_like_provider(config):
            return 300.0
        return DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS

    def _agent_loop_timeout_kwargs(self) -> dict[str, float]:
        if not _is_kimi_like_provider(self._config):
            return {}
        # Measured kimi-k3 gateways: a single hidden-reasoning completion can
        # take 160s+ with coach-sized prompts, so per-step waits must exceed
        # the old 120s tier or every turn dies as a false timeout.
        return {
            "step_timeout": 240.0,
            "first_step_timeout": 300.0,
        }

    def _provider_client_max_retries(self, provider: ProviderConfig | None = None) -> int:
        defaults = self._provider_request_defaults(provider)
        for key in (
            "clientMaxRetries",
            "client_max_retries",
            "maxRetries",
            "max_retries",
        ):
            resolved = self._request_default_number(defaults.get(key))
            if resolved is not None:
                return max(0, int(resolved))
        return DEFAULT_OPENAI_CLIENT_MAX_RETRIES

    @staticmethod
    def _merge_request_records(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in override.items():
            current = merged.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                merged[key] = ProviderService._merge_request_records(current, value)
            else:
                merged[key] = value
        return merged

    def _apply_request_defaults(
        self,
        payload: dict[str, Any],
        provider: ProviderConfig | None = None,
    ) -> dict[str, Any]:
        request_defaults = self._provider_request_defaults(provider)
        if not request_defaults:
            return payload

        merged = {**payload}
        chat_key_aliases = {
            "maxOutputTokens": "max_tokens",
            "max_output_tokens": "max_tokens",
            "maxTokens": "max_tokens",
            "stopSequences": "stop",
            "reasoningEffort": "reasoning_effort",
            "serviceTier": "service_tier",
            "topP": "top_p",
            "presencePenalty": "presence_penalty",
            "frequencyPenalty": "frequency_penalty",
            "logitBias": "logit_bias",
            "responseFormat": "response_format",
            "parallelToolCalls": "parallel_tool_calls",
            "promptCacheKey": "prompt_cache_key",
            "promptCacheRetention": "prompt_cache_retention",
            "safetyIdentifier": "safety_identifier",
            "streamOptions": "stream_options",
            "topLogprobs": "top_logprobs",
            "webSearchOptions": "web_search_options",
        }
        chat_allowed_keys = {
            "audio",
            "extra_headers",
            "extra_query",
            "frequency_penalty",
            "function_call",
            "functions",
            "logit_bias",
            "logprobs",
            "max_completion_tokens",
            "max_tokens",
            "metadata",
            "modalities",
            "moderation",
            "n",
            "parallel_tool_calls",
            "prediction",
            "presence_penalty",
            "prompt_cache_key",
            "prompt_cache_retention",
            "reasoning_effort",
            "response_format",
            "safety_identifier",
            "seed",
            "service_tier",
            "stop",
            "store",
            "stream_options",
            "temperature",
            "timeout",
            "top_logprobs",
            "top_p",
            "user",
            "verbosity",
            "web_search_options",
        }
        skipped_values = {"auto", ""}
        for key, value in request_defaults.items():
            if value is None:
                continue
            if key == "extra_body" and isinstance(value, dict):
                existing = merged.get("extra_body")
                existing_record = existing if isinstance(existing, dict) else {}
                merged["extra_body"] = self._merge_request_records(dict(value), existing_record)
                continue
            normalized_key = chat_key_aliases.get(key, key)
            if normalized_key not in chat_allowed_keys:
                continue
            if isinstance(value, str) and value.strip().lower() in skipped_values:
                continue
            if normalized_key == "max_tokens" and isinstance(value, int) and value > 0:
                merged[normalized_key] = value
                continue
            if normalized_key == "stop" and key == "stopSequences":
                merged[normalized_key] = value
                continue
            merged[normalized_key] = value

        # Apply the negotiated thinking policy here, on the central chokepoint
        # every chat request passes through. Without this the policy learned
        # from a gateway rejection is never re-applied, so every later turn
        # re-pays the same HTTP 400 round trip before succeeding.
        return apply_thinking_policy(merged, resolve_thinking_policy(merged, self._thinking_scope(provider)))

    def _provider_cache_key(self, provider: ProviderConfig, api_key: str | None) -> tuple[str, str]:
        try:
            provider_fingerprint = json.dumps(
                provider.model_dump(mode="json", by_alias=True, exclude_none=True),
                ensure_ascii=True,
                sort_keys=True,
            )
        except Exception:
            provider_fingerprint = repr(provider)
        api_key_fingerprint = hashlib.sha256(
            (api_key.strip() if isinstance(api_key, str) else "").encode("utf-8")
        ).hexdigest()
        return (provider_fingerprint, api_key_fingerprint)

    def _get_cached_models(self, provider: ProviderConfig, api_key: str | None) -> ProviderModelsResponse | None:
        cache_key = self._provider_cache_key(provider, api_key)
        cached = self._models_cache.get(cache_key)
        if not cached:
            return None
        cached_at, response = cached
        if monotonic() - cached_at > self._MODEL_CACHE_TTL_SECONDS:
            self._models_cache.pop(cache_key, None)
            return None
        return response.model_copy(update={"cache_hit": True})

    def _store_cached_models(
        self,
        provider: ProviderConfig,
        api_key: str | None,
        response: ProviderModelsResponse,
    ) -> None:
        if not response.listed:
            return
        cache_key = self._provider_cache_key(provider, api_key)
        self._models_cache[cache_key] = (monotonic(), response.model_copy(update={"cache_hit": False}))

    def _resolve_model(self, override: str | None = None) -> str:
        if override and override.strip():
            return override.strip()
        if self._config and self._config.model.strip():
            return self._config.model.strip()
        return "gpt-4o-mini"

    @staticmethod
    def _count_image_attachments(attachments: list[dict[str, Any]] | None) -> int:
        if not attachments:
            return 0
        count = 0
        for item in attachments:
            if not isinstance(item, dict):
                continue
            if str(item.get("kind") or "image").strip().lower() == "image":
                count += 1
        return count

    def describe_attachment_delivery(
        self,
        *,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        use_agent_loop: bool,
    ) -> dict[str, Any]:
        normalized_attachments = list(attachments or [])
        attachments_present = bool(normalized_attachments)
        image_attachment_count = self._count_image_attachments(normalized_attachments)
        config = self._config
        if protocol is None and config is not None:
            protocol = getattr(config, "protocol", None)
        if config is not None and self._capability_truth.get("vision") != "verified":
            return {
                "attachments_present": True,
                "image_attachment_count": image_attachment_count,
                "attachments_delivered_to_model": False,
                "attachments_delivery_path": "not_sent",
                "attachments_delivery_reason": "vision_not_available",
            }

        if not attachments_present:
            return {
                "attachments_present": False,
                "image_attachment_count": 0,
                "attachments_delivered_to_model": False,
                "attachments_delivery_path": "not_sent",
                "attachments_delivery_reason": "no_attachments",
            }

        if image_attachment_count <= 0:
            return {
                "attachments_present": True,
                "image_attachment_count": 0,
                "attachments_delivered_to_model": False,
                "attachments_delivery_path": "not_sent",
                "attachments_delivery_reason": "non_image_attachments_not_supported",
            }

        if not use_agent_loop:
            return {
                "attachments_present": True,
                "image_attachment_count": image_attachment_count,
                "attachments_delivered_to_model": False,
                "attachments_delivery_path": "not_sent",
                "attachments_delivery_reason": "agent_loop_disabled",
            }

        delivered = False
        try:
            from .agent_binding import ProviderAgentBinding

            binding = ProviderAgentBinding(
                provider_service=self,
                protocol=protocol,
                attachments=normalized_attachments,
            )
            delivered = bool(binding.attachments_will_be_sent())
        except Exception:
            delivered = False

        return {
            "attachments_present": True,
            "image_attachment_count": image_attachment_count,
            "attachments_delivered_to_model": delivered,
            "attachments_delivery_path": "vision" if delivered else "not_sent",
            "attachments_delivery_reason": "image_sent_to_model" if delivered else "vision_not_available",
        }

    def _model_candidates(self, override: str | None = None) -> list[str]:
        primary = self._resolve_model(override)
        normalized = primary.strip()
        candidates: list[str] = []

        def add(candidate: str | None) -> None:
            value = candidate.strip() if isinstance(candidate, str) else ""
            if value and value not in candidates:
                candidates.append(value)

        add(normalized)
        lowered = normalized.lower()
        add(lowered)
        add(lowered.replace(".", "-"))
        add(lowered.replace("-", "."))
        add(lowered.replace("_", "-"))
        add(lowered.replace("_", "."))
        add(lowered.replace(".", "").replace("-", "").replace("_", ""))

        if lowered == "mimo-v2.5" or normalized == "MiMo-V2.5":
            add("mimo-v2.5")
            add("mimo-v2.5-pro")

        return candidates

    def _is_model_not_supported_error(self, error: Exception | str) -> bool:
        message = str(error)
        lowered = message.lower()
        return (
            "not supported model" in lowered
            or "model" in lowered and "param incorrect" in lowered
            or "unsupported model" in lowered
        )

    def _is_model_not_found_error(self, error: Exception | str) -> bool:
        message = str(error)
        lowered = message.lower()
        return (
            "model_not_found" in lowered
            or "no available channel for model" in lowered
            or "does not exist" in lowered and "model" in lowered
        )

    def _looks_like_protocol_mismatch_error(self, error: Exception | str) -> bool:
        lowered = str(error).lower()
        protocol_markers = (
            "/v1/responses",
            "/v1/messages",
            ":generatecontent",
            "generatecontent",
        )
        if "invalid url" in lowered and any(marker in lowered for marker in protocol_markers):
            return True
        if "invalid_request_error" in lowered and any(marker in lowered for marker in protocol_markers):
            return True
        if "not found" in lowered and any(marker in lowered for marker in protocol_markers):
            return True
        return False

    def _extract_status_code(self, error: Exception) -> int | None:
        status_code = getattr(error, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        match = re.search(r"(?:HTTP|status|error code:)\s*(?:status\s*)?(\d{3})", str(error), re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _classify_error(self, error: Exception) -> tuple[str, bool, int | None, bool, bool | None]:
        runtime_category = getattr(error, "provider_error_category", None)
        if isinstance(runtime_category, str) and runtime_category:
            status_code = getattr(error, "status_code", None)
            return (
                runtime_category,
                bool(getattr(error, "provider_retryable", False)),
                status_code if isinstance(status_code, int) else None,
                bool(getattr(error, "provider_reachable", True)),
                getattr(error, "model_supported", True),
            )
        message = str(error).strip()
        lowered = message.lower()
        status_code = self._extract_status_code(error)

        if self._is_model_not_found_error(error):
            return ("model_not_found", False, status_code or 503, True, False)
        if self._is_model_not_supported_error(error):
            return ("model_unsupported", False, status_code or 400, True, False)
        if (
            status_code in {401, 403}
            or "invalid api key" in lowered
            or "incorrect api key" in lowered
            or "permission denied" in lowered
            or "forbidden" in lowered
            or "invalid token" in lowered
            or "not authorized" in lowered
        ):
            return ("invalid_key_or_permission", False, status_code or 401, True, None)
        if (
            status_code in {400, 404, 405, 415, 422}
            and self._looks_like_protocol_mismatch_error(error)
        ):
            return ("malformed_response", False, status_code, True, None)
        if status_code == 429 or "rate limit" in lowered or "too many requests" in lowered:
            return ("rate_limit", True, status_code or 429, True, None)
        if (
            isinstance(error, (TimeoutError, socket.timeout, httpx.TimeoutException))
            or "timeout" in lowered
        ):
            return ("timeout", True, status_code, False, None)
        if (
            isinstance(error, (OSError, httpx.NetworkError))
            or "connection refused" in lowered
            or "name or service not known" in lowered
        ):
            return ("network", True, status_code, False, None)
        if "malformed" in lowered or "invalid json" in lowered or "unexpected response" in lowered:
            return ("malformed_response", False, status_code, True, None)
        if status_code and 500 <= status_code <= 599:
            # A 5xx means the endpoint answered — its own upstream failed. That
            # is not the same as "cannot reach the provider", and collapsing the
            # two sent users off to debug a base URL that was working fine.
            return ("upstream_unavailable", True, status_code, True, None)
        return ("unknown", False, status_code, False, None)

    def _detail_from_category(
        self,
        category: str,
        *,
        provider: ProviderConfig,
        error: Exception | None = None,
        response_language: str | None = None,
    ) -> str:
        error_message = (
            error.safe_detail
            if isinstance(error, ProviderRuntimeResponseError)
            else redact_provider_error(error, api_key=self._api_key)
            if error
            else ""
        )
        if category == "protocol_mismatch":
            return (
                "Provider returned a response for a different protocol than the configured endpoint. "
                f"{error_message}"
            ).strip()
        if category == "reasoning_budget_exhausted":
            return (
                _localized_text(
                    (
                        "Provider is reachable, but the model spent its entire output budget on hidden "
                        "reasoning and returned no visible coaching reply. Retry the request, or choose "
                        "a non-reasoning model for short probes and health checks. "
                    ),
                    (
                        "provider 已连通，但模型把全部输出额度都花在了隐藏思考上，没有返回可见的教练回复。"
                        "请重试该请求，或为短探测与健康检查改用非思考（non-reasoning）模型。 "
                    ),
                    response_language,
                )
                + error_message
            ).strip()
        if category == "reasoning_leak":
            return (
                "Provider returned hidden reasoning without a visible coaching reply. "
                f"{error_message}"
            ).strip()
        if category == "truncated_or_empty":
            return (
                "Provider response ended before Trainer received a complete visible coaching reply. "
                f"{error_message}"
            ).strip()
        if category == "empty_response":
            return (
                "Provider returned no visible coaching reply. "
                f"{error_message}"
            ).strip()
        if category == "provider_error":
            return f"Provider request failed. {error_message}".strip()
        if category == "invalid_key_or_permission":
            return (
                "Provider rejected the API key or permissions. Check the key, workspace/project access, "
                f"and model entitlement. {error_message}".strip()
            )
        if category == "rate_limit":
            return f"Provider rate limited the request. Wait a moment and retry. {error_message}".strip()
        if category == "timeout":
            return f"Provider request timed out before the endpoint replied. {error_message}".strip()
        if category == "network":
            return f"Trainer could not reach the provider endpoint. Check the base URL and network path. {error_message}".strip()
        if category == "malformed_response":
            return f"Provider responded with an unexpected or malformed payload. {error_message}".strip()
        if category == "model_unsupported":
            return (
                f"Provider reached, but the chat model '{provider.model}' is not accepted by the endpoint. "
                f"{error_message}"
            ).strip()
        if category == "model_not_found":
            return (
                f"Provider reached, but there is currently no available gateway channel for chat model "
                f"'{provider.model}'. {error_message}"
            ).strip()
        return f"Provider test failed: {error_message}".strip()

    def _normalize_model_id(self, value: object) -> str | None:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return None

    def _resolve_model_from_list(self, requested_model: str, available_models: list[str]) -> str | None:
        requested = requested_model.strip()
        if not requested or not available_models:
            return None

        requested_lower = requested.lower()
        normalized_candidates = self._model_candidates(requested)
        available_by_lower = {model.lower(): model for model in available_models}
        available_by_flat = {
            model.lower().replace(".", "").replace("-", "").replace("_", ""): model
            for model in available_models
        }

        for candidate in normalized_candidates:
            direct = available_by_lower.get(candidate.lower())
            if direct:
                return direct

            flattened = candidate.lower().replace(".", "").replace("-", "").replace("_", "")
            fuzzy = available_by_flat.get(flattened)
            if fuzzy:
                return fuzzy

        return available_by_lower.get(requested_lower)

    def _models_response_from_ids(
        self,
        provider: ProviderConfig,
        models: list[str],
        *,
        diagnostics: list[str],
        listed: bool = True,
        model_token_limits: dict[str, ProviderModelTokenLimit] | None = None,
    ) -> ProviderModelsResponse:
        unique_models = sorted({model for model in models if model}, key=str.lower)
        has_visible_models = bool(unique_models)
        resolved = self._resolve_model_from_list(provider.model, unique_models)
        resolved_from_input = bool(resolved and resolved != provider.model)
        normalized_model_token_limits = {
            model_name: limit
            for model_name, limit in (model_token_limits or {}).items()
            if model_name in unique_models
        }
        detail = (
            f"Fetched {len(unique_models)} models."
            if unique_models
            else "Provider responded, but did not return any visible models."
        )
        if resolved:
            detail += f" Resolved configured model to {resolved}."
        return ProviderModelsResponse(
            ok=has_visible_models,
            detail=detail,
            available_models=unique_models,
            resolved_model=resolved,
            model_token_limits=normalized_model_token_limits,
            resolved_from_input=resolved_from_input,
            listed=listed and has_visible_models,
            diagnostics=[
                *diagnostics,
                f"Listed {len(unique_models)} models from provider {provider.name}.",
                *( [f"Resolved configured model to {resolved}."] if resolved else [] ),
            ],
        )

    def _anthropic_list_models(self, provider: ProviderConfig, api_key: str) -> ProviderModelsResponse:
        diagnostics = ["Using native anthropic_messages model listing."]
        with self._direct_http_client(provider, timeout=60.0) as client:
            response = client.get(
                f"{self._anthropic_base_url(provider)}/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
        if response.status_code >= 400:
            if not self._anthropic_base_url_is_official(provider):
                return self._anthropic_fallback_to_openai_model_list(
                    provider,
                    api_key,
                    diagnostics=diagnostics,
                    failure_detail=redact_provider_error(
                        {"upstream_body": response.text},
                        api_key=api_key,
                        fallback=f"Anthropic Models list failed (HTTP {response.status_code})",
                    ),
                )
            raise RuntimeError(
                redact_provider_error(
                    {"upstream_body": response.text},
                    api_key=api_key,
                    fallback=f"Anthropic Models list failed (HTTP {response.status_code})",
                )
            )
        body = response.json()
        models: list[str] = []
        model_token_limits: dict[str, ProviderModelTokenLimit] = {}
        for item in body.get("data") or []:
            if not isinstance(item, dict):
                continue
            model_id = self._normalize_model_id(item.get("id"))
            if model_id:
                models.append(model_id)
                token_limit = _extract_model_token_limit(item)
                if token_limit is not None:
                    model_token_limits[model_id] = token_limit
        return self._models_response_from_ids(
            provider,
            models,
            diagnostics=diagnostics,
            model_token_limits=model_token_limits,
        )

    @staticmethod
    def _anthropic_base_url_is_official(provider: ProviderConfig) -> bool:
        return "anthropic.com" in str(provider.base_url or "").strip().lower()

    def _anthropic_fallback_to_openai_model_list(
        self,
        provider: ProviderConfig,
        api_key: str,
        *,
        diagnostics: list[str],
        failure_detail: str,
    ) -> ProviderModelsResponse:
        """Retry discovery with the common gateway-compatible list endpoint.

        Several non-Anthropic gateways accept the Messages request shape but
        expose discovery only through the OpenAI-compatible /models endpoint.
        This fallback is intentionally limited to third-party endpoints; the
        official API remains on its native transport.
        """
        fallback = self._openai_list_models(provider, api_key)
        return fallback.model_copy(
            update={
                "diagnostics": [
                    *diagnostics,
                    "Native Anthropic model listing was unavailable on this gateway; tried OpenAI-compatible /models.",
                    failure_detail,
                    *fallback.diagnostics,
                ],
            }
        )

    def _gemini_models_endpoint(self, provider: ProviderConfig) -> str:
        base_url = str(provider.base_url or "").strip().rstrip("/")
        if not base_url:
            base_url = "https://generativelanguage.googleapis.com/v1beta"
        if base_url.endswith(":generateContent"):
            base_url = base_url.rsplit("/models/", 1)[0] if "/models/" in base_url else base_url
        if "/models/" in base_url:
            base_url = base_url.rsplit("/models/", 1)[0]
        if base_url.rstrip("/").endswith("/models"):
            return base_url
        if base_url.endswith("/v1") or base_url.endswith("/v1beta"):
            return f"{base_url}/models"
        return f"{base_url}/v1beta/models"

    def _gemini_base_url_is_google_native(self, provider: ProviderConfig) -> bool:
        return "googleapis.com" in str(provider.base_url or "").strip().lower()

    def _gemini_fallback_to_openai_model_list(
        self,
        provider: ProviderConfig,
        api_key: str,
        *,
        diagnostics: list[str],
        failure_detail: str,
    ) -> ProviderModelsResponse:
        diagnostics = [
            *diagnostics,
            "Native Gemini model listing did not return usable models on a non-Google endpoint; trying OpenAI-compatible /models for this gateway.",
            failure_detail,
        ]
        fallback = self._openai_list_models(provider, api_key)
        return fallback.model_copy(
            update={
                "diagnostics": [*diagnostics, *fallback.diagnostics],
            }
        )

    def _gemini_list_models(self, provider: ProviderConfig, api_key: str) -> ProviderModelsResponse:
        diagnostics = ["Using native gemini_generate_content model listing."]
        with self._direct_http_client(provider, timeout=60.0) as client:
            response = client.get(
                self._gemini_models_endpoint(provider),
                headers={
                    "x-goog-api-key": api_key,
                    "content-type": "application/json",
                },
            )
        if response.status_code >= 400:
            if not self._gemini_base_url_is_google_native(provider):
                return self._gemini_fallback_to_openai_model_list(
                    provider,
                    api_key,
                    diagnostics=diagnostics,
                    failure_detail=redact_provider_error(
                        {"upstream_body": response.text},
                        api_key=api_key,
                        fallback=f"Gemini Models list failed (HTTP {response.status_code})",
                    ),
                )
            raise RuntimeError(
                redact_provider_error(
                    {"upstream_body": response.text},
                    api_key=api_key,
                    fallback=f"Gemini Models list failed (HTTP {response.status_code})",
                )
            )
        body = response.json()
        models: list[str] = []
        model_token_limits: dict[str, ProviderModelTokenLimit] = {}
        for item in body.get("models") or []:
            if not isinstance(item, dict):
                continue
            raw_name = self._normalize_model_id(item.get("name"))
            if not raw_name:
                continue
            model_id = raw_name.removeprefix("models/")
            models.append(model_id)
            token_limit = _extract_model_token_limit(item)
            if token_limit is not None:
                model_token_limits[model_id] = token_limit
        if not models and not self._gemini_base_url_is_google_native(provider):
            return self._gemini_fallback_to_openai_model_list(
                provider,
                api_key,
                diagnostics=diagnostics,
                failure_detail="Gemini Models list returned HTTP 200 but no usable native models.",
            )
        return self._models_response_from_ids(
            provider,
            models,
            diagnostics=diagnostics,
            model_token_limits=model_token_limits,
        )

    @staticmethod
    def _iter_listed_models(response: object) -> list[object]:
        """Iterate a models.list payload without treating MagicMock as a catalog."""
        data = getattr(response, "data", None)
        if isinstance(data, list):
            return data
        if isinstance(response, list):
            return response
        module = type(response).__module__
        if module.startswith("unittest.mock"):
            return []
        iterator = getattr(response, "__iter__", None)
        if not callable(iterator):
            return []
        try:
            return list(cast("list[object]", response))
        except TypeError:
            return []

    def _openai_list_models(self, provider: ProviderConfig, api_key: str) -> ProviderModelsResponse:
        client = self._create_sync_client(provider, api_key)
        response = client.models.list()
        models: list[str] = []
        model_token_limits: dict[str, ProviderModelTokenLimit] = {}

        for item in self._iter_listed_models(response):
            model_id = self._normalize_model_id(getattr(item, "id", None))
            if model_id:
                models.append(model_id)
                token_limit = _extract_model_token_limit(item)
                if token_limit is not None:
                    model_token_limits[model_id] = token_limit

        protocol = self._configured_protocol(provider)
        listing_note = (
            f"Using OpenAI-shaped model listing as a catalog probe for provider {provider.name}."
            if protocol is None
            else f"Using OpenAI-compatible model listing for provider {provider.name}."
        )
        return self._models_response_from_ids(
            provider,
            models,
            diagnostics=[listing_note],
            model_token_limits=model_token_limits,
        )

    def _gateway_fingerprint_diagnostics(
        self,
        provider: ProviderConfig,
        api_key: str,
    ) -> list[str]:
        base_url = self._normalized_openai_compatible_base_url(provider)
        if not base_url:
            return []
        try:
            with self._direct_http_client(provider, timeout=2.0) as client:
                response = client.get(
                    f"{base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            catalog_claims = catalog_endpoint_type_claims(
                response.json() if response.status_code < 400 else None
            )
            fingerprint = inspect_provider_gateway_headers(
                response.headers,
                catalog_endpoint_types=catalog_claims,
            )
            return list(gateway_fingerprint_diagnostics(fingerprint))
        except Exception:
            return []

    def list_models(
        self,
        provider: ProviderConfig,
        api_key: str | None,
        *,
        skip_cache: bool = False,
    ) -> ProviderModelsResponse:
        if not api_key:
            return ProviderModelsResponse(
                ok=False,
                detail="Provider config is saved, but no API key is available. Trainer cannot fetch models until you add one.",
                error_category="missing_api_key",
                retryable=False,
                diagnostics=["No API key supplied for model listing."],
            )

        if not skip_cache:
            cached = self._get_cached_models(provider, api_key)
            if cached is not None:
                return cached

        try:
            protocol = self._configured_protocol(provider)
            if protocol == "anthropic_messages":
                result = self._anthropic_list_models(provider, api_key)
            elif protocol == "gemini_generate_content":
                result = self._gemini_list_models(provider, api_key)
            else:
                result = self._openai_list_models(provider, api_key)
            self._store_cached_models(provider, api_key, result)
            return result
        except Exception as exc:  # pragma: no cover - network dependent
            category, retryable, status_code, _, _ = self._classify_error(exc)
            return ProviderModelsResponse(
                ok=False,
                detail=self._detail_from_category(category, provider=provider, error=exc),
                error_category=category,
                retryable=retryable,
                status_code=status_code,
                diagnostics=[
                    "Model listing request failed.",
                    redact_provider_error(exc, api_key=api_key),
                ],
            )

    async def _create_chat_completion(
        self,
        *,
        client: Any,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> tuple[Any, str]:
        last_error: Exception | None = None
        last_model = self._resolve_model(model)

        for candidate in self._model_candidates(model):
            last_model = candidate
            try:
                prepared_messages, effective_max_tokens = self._prepare_context_budget(
                    messages,
                    model=candidate,
                    requested_max_tokens=max_tokens,
                    prefer_configured_output=True,
                )
                request_payload = self._apply_request_defaults(
                    {
                        "model": candidate,
                        "messages": prepared_messages,  # type: ignore[arg-type]
                        "temperature": temperature,
                        "max_tokens": effective_max_tokens,
                        "stream": stream,
                    }
                )
                response = await self._create_chat_completion_negotiated_async(
                    client, request_payload
                )
                return response, candidate
            except Exception as exc:
                last_error = exc
                if not self._is_model_not_supported_error(exc):
                    raise

        if last_error is not None:
            raise last_error

        raise RuntimeError(f"Unable to resolve a usable model for {last_model}.")

    def _language_probe_result(
        self,
        *,
        client: Any,
        model: str,
        provider: ProviderConfig | None = None,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> dict[str, object]:
        probe_max_tokens = _visible_probe_max_tokens(provider)

        def natural_language_probe_result() -> dict[str, object]:
            if not _prefers_chinese(response_language):
                return {"ok": False}
            try:
                request_payload = self._apply_request_defaults(
                    {
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Reply in Chinese only. Keep required phrases exactly. Do not explain or add quotes.",
                            },
                            {
                                "role": "user",
                                "content": _NATURAL_LANGUAGE_PROBE_PROMPT,
                            },
                        ],
                        "temperature": 0,
                        "max_tokens": probe_max_tokens,
                    },
                    provider,
                )
                response = client.chat.completions.create(**request_payload)
            except Exception:  # pragma: no cover - network dependent
                return {"ok": False}
            content = response.choices[0].message.content if response.choices else None
            preview = _compact_visible_text(content)
            if not preview:
                return {"ok": False}
            if _looks_like_input_corruption_reply(preview):
                return {"ok": False}
            if not _contains_cjk(preview):
                return {"ok": False}
            if not all(fragment in preview for fragment in _NATURAL_LANGUAGE_PROBE_FRAGMENTS):
                return {"ok": False}
            return {
                "ok": True,
                "detail": _localized_text(
                    (
                        "Natural-language zh-CN probe succeeded after the strict echo probe was unstable. "
                        "Trainer can keep using this connection for Chinese coaching."
                    ),
                    "自然中文探测通过了：虽然严格回显探测不稳定，但这条连接仍能输出可用的中文教学句子。",
                    response_language,
                ),
                "preview": preview,
                "kind": "natural_language_fallback",
            }

        previews: list[str] = []
        probe_variants: list[tuple[str, str, str]] = []
        message_probe = _message_probe_variant(probe_message)
        if message_probe is not None:
            probe_variants.append((message_probe[0], message_probe[1], "message"))
        if _prefers_chinese(response_language):
            probe_variants.extend(
                (prompt_text, expected_output, "generic")
                for prompt_text, expected_output in _LANGUAGE_PROBE_VARIANTS
            )
        if not probe_variants:
            return {
                "ok": True,
                "detail": "Language integrity probe skipped for this English-only flow.",
                "preview": "",
                "skipped": True,
            }
        for _attempt in range(2):
            for prompt_text, expected_output, probe_kind in probe_variants:
                try:
                    request_payload = self._apply_request_defaults(
                        {
                            "model": model,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": "Return exactly the requested text. Do not explain or add quotes.",
                                },
                                {
                                    "role": "user",
                                    "content": prompt_text,
                                },
                            ],
                            "temperature": 0,
                            "max_tokens": probe_max_tokens,
                        },
                        provider,
                    )
                    response = client.chat.completions.create(**request_payload)
                except Exception as exc:  # pragma: no cover - network dependent
                    return {
                        "ok": False,
                        "category": "language_probe_inconclusive",
                        "detail": _localized_text(
                            (
                                "Language integrity probe could not complete after connectivity succeeded. "
                                f"Follow-up check failed: {redact_provider_error(exc, api_key=self._api_key)}"
                            ),
                            f"语言完整性探测在连通性成功后没能完成。后续检查失败：{redact_provider_error(exc, api_key=self._api_key)}",
                            response_language,
                        ),
                        "preview": "",
                    }

                content = response.choices[0].message.content if response.choices else None
                preview = _compact_visible_text(content)
                if not preview:
                    return {
                        "ok": False,
                        "category": "language_probe_inconclusive",
                        "detail": _localized_text(
                            (
                                "Language integrity probe returned no visible content after connectivity succeeded. "
                                "Trainer cannot verify non-English input on this connection."
                            ),
                            (
                                "语言完整性探测在连通性成功后没有拿到可见内容。"
                                "Trainer 现在还不能验证这条链路上的非 English 输入。"
                            ),
                            response_language,
                        ),
                        "preview": "",
                    }
                previews.append(preview)
                if expected_output in preview:
                    continue
                fallback_probe = natural_language_probe_result()
                if fallback_probe.get("ok") is True:
                    return fallback_probe
                if _looks_like_input_corruption_reply(preview, expected_probe=expected_output):
                    if probe_kind == "message":
                        detail = _localized_text(
                            (
                                "Provider reachable, but it corrupted the actual mixed-language coaching "
                                "message into question marks before the model saw it."
                            ),
                            "这个 provider 可达，但在模型看到之前就把当前这条混合语言教学消息变成了一串问号。",
                            response_language,
                        )
                    else:
                        detail = _localized_text(
                            (
                                "Provider reachable, but it corrupted Chinese input into question marks "
                                "before the model saw it."
                            ),
                            "这个 provider 可达，但在模型看到消息之前把中文输入变成了一串问号。",
                            response_language,
                        )
                    return {
                        "ok": False,
                        "category": "language_corruption",
                        "detail": detail,
                        "preview": preview,
                    }
                detail = _localized_text(
                    (
                        "Language integrity probe was inconclusive. The provider replied, but it did not preserve "
                        "the message-derived probe text exactly enough for Trainer to trust it."
                        if probe_kind == "message"
                        else (
                            "Language integrity probe was inconclusive. The provider replied, but it did not preserve "
                            "the mixed-language probe text exactly enough for Trainer to trust it."
                        )
                    ),
                    (
                        "语言完整性探测没有通过。provider 虽然回复了，"
                        "但没有把基于当前消息生成的探测文本完整保留下来，Trainer 还不能信任这条链路。"
                        if probe_kind == "message"
                        else (
                            "语言完整性探测没有通过。provider 虽然回复了，"
                            "但没有把混合语言探测文本完整保留下来，Trainer 还不能信任这条链路。"
                        )
                    ),
                    response_language,
                )
                return {
                    "ok": False,
                    "category": "language_probe_inconclusive",
                    "detail": detail,
                    "preview": preview,
                }

        final_detail = _localized_text(
            (
                "Language integrity probe preserved the message-derived and mixed CJK/ASCII probe text across all checks."
                if message_probe is not None or _prefers_chinese(response_language)
                else "Language integrity probe preserved the mixed CJK/ASCII probe text across all checks."
            ),
            (
                "语言完整性探测通过了：基于当前消息生成的探测文本和 mixed CJK/ASCII 探测文本都被完整保留下来了。"
                if message_probe is not None or _prefers_chinese(response_language)
                else "语言完整性探测通过了：mixed CJK/ASCII 探测文本在所有检查里都被完整保留下来了。"
            ),
            response_language,
        )
        return {
            "ok": True,
            "detail": final_detail,
            "preview": previews[-1] if previews else "",
            "kind": "strict_integrity",
        }

    def _language_probe_result_resilient(
        self,
        *,
        client: Any,
        model: str,
        provider: ProviderConfig | None = None,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> dict[str, object]:
        probe_max_tokens = _visible_probe_max_tokens(provider)
        zh_natural_success = (
            "\u81ea\u7136 zh-CN \u63a2\u6d4b\u5df2\u901a\u8fc7\uff1a"
            "\u867d\u7136\u4e25\u683c\u56de\u663e\u63a2\u6d4b\u4e0d\u7a33\u5b9a\uff0c"
            "Trainer \u4ecd\u7136\u80fd\u5728\u8fd9\u6761\u8fde\u63a5\u4e0a\u7ee7\u7eed zh-CN \u6559\u7ec3\u3002"
        )
        zh_probe_failed = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u5728\u8fde\u901a\u6027\u6210\u529f\u540e\u6ca1\u80fd\u5b8c\u6210\u3002"
            "\u540e\u7eed\u68c0\u67e5\u5931\u8d25\uff1a"
        )
        zh_no_visible = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u5728\u8fde\u901a\u6027\u6210\u529f\u540e\u6ca1\u6709\u62ff\u5230\u53ef\u89c1\u5185\u5bb9\u3002"
            "Trainer \u73b0\u5728\u8fd8\u4e0d\u80fd\u9a8c\u8bc1\u8fd9\u6761\u94fe\u8def\u4e0a\u7684\u975e English \u8f93\u5165\u3002"
        )
        zh_message_corruption = (
            "\u8fd9\u4e2a provider \u53ef\u8fbe\uff0c"
            "\u4f46\u5728\u6a21\u578b\u770b\u5230\u4e4b\u524d\u5c31\u628a\u5f53\u524d\u8fd9\u6761\u6df7\u5408\u8bed\u8a00\u6559\u7ec3\u6d88\u606f"
            "\u53d8\u6210\u4e86\u4e00\u4e32\u95ee\u53f7\u3002"
        )
        zh_generic_corruption = (
            "\u8fd9\u4e2a provider \u53ef\u8fbe\uff0c"
            "\u4f46\u5728\u6a21\u578b\u770b\u5230\u6d88\u606f\u4e4b\u524d\u628a\u4e2d\u6587\u8f93\u5165\u53d8\u6210\u4e86\u4e00\u4e32\u95ee\u53f7\u3002"
        )
        zh_message_inconclusive = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u6ca1\u6709\u901a\u8fc7\u3002provider \u867d\u7136\u56de\u590d\u4e86\uff0c"
            "\u4f46\u6ca1\u6709\u628a\u57fa\u4e8e\u5f53\u524d\u6d88\u606f\u751f\u6210\u7684\u63a2\u6d4b\u6587\u672c\u5b8c\u6574\u4fdd\u7559\u4e0b\u6765\uff0c"
            "Trainer \u8fd8\u4e0d\u80fd\u4fe1\u4efb\u8fd9\u6761\u94fe\u8def\u3002"
        )
        zh_generic_inconclusive = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u6ca1\u6709\u901a\u8fc7\u3002provider \u867d\u7136\u56de\u590d\u4e86\uff0c"
            "\u4f46\u6ca1\u6709\u628a mixed CJK/ASCII \u63a2\u6d4b\u6587\u672c\u5b8c\u6574\u4fdd\u7559\u4e0b\u6765\uff0c"
            "Trainer \u8fd8\u4e0d\u80fd\u4fe1\u4efb\u8fd9\u6761\u94fe\u8def\u3002"
        )
        zh_retry_success = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u5728\u91cd\u8bd5\u540e\u6062\u590d\u6210\u529f\uff1a"
            "\u81f3\u5c11\u6709\u4e00\u6761\u57fa\u4e8e\u5f53\u524d\u6d88\u606f\u6216 mixed CJK/ASCII \u7684\u63a2\u6d4b\u6587\u672c"
            "\u88ab\u53ef\u7528\u5730\u5b8c\u6574\u4fdd\u7559\u4e86\u3002"
        )
        zh_strict_success = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u901a\u8fc7\u4e86\uff1a"
            "\u57fa\u4e8e\u5f53\u524d\u6d88\u606f\u751f\u6210\u7684\u63a2\u6d4b\u6587\u672c\u548c mixed CJK/ASCII \u63a2\u6d4b\u6587\u672c"
            "\u90fd\u88ab\u5b8c\u6574\u4fdd\u7559\u4e0b\u6765\u4e86\u3002"
        )
        zh_generic_success = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u901a\u8fc7\u4e86\uff1a"
            "mixed CJK/ASCII \u63a2\u6d4b\u6587\u672c\u5728\u6240\u6709\u68c0\u67e5\u91cc\u90fd\u88ab\u5b8c\u6574\u4fdd\u7559\u4e0b\u6765\u4e86\u3002"
        )
        zh_no_signal = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u5728\u8fde\u901a\u6027\u6210\u529f\u540e\u4ecd\u6ca1\u6709\u62ff\u5230\u53ef\u7528\u4fe1\u53f7\u3002"
            "Trainer \u73b0\u5728\u8fd8\u4e0d\u80fd\u9a8c\u8bc1\u8fd9\u6761\u94fe\u8def\u4e0a\u7684\u975e English \u8f93\u5165\u3002"
        )

        def natural_language_probe_result() -> dict[str, object]:
            if not _prefers_chinese(response_language):
                return {"ok": False}
            try:
                request_payload = self._apply_request_defaults(
                    {
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Reply in Chinese only. Keep required phrases exactly. Do not explain or add quotes.",
                            },
                            {
                                "role": "user",
                                "content": _NATURAL_LANGUAGE_PROBE_PROMPT,
                            },
                        ],
                        "temperature": 0,
                        "max_tokens": probe_max_tokens,
                    },
                    provider,
                )
                response = client.chat.completions.create(**request_payload)
            except Exception:  # pragma: no cover - network dependent
                return {"ok": False}
            content = response.choices[0].message.content if response.choices else None
            preview = _compact_visible_text(content)
            if not preview:
                return {"ok": False}
            if _looks_like_input_corruption_reply(preview):
                return {"ok": False}
            if not _contains_cjk(preview):
                return {"ok": False}
            if not all(fragment in preview for fragment in _NATURAL_LANGUAGE_PROBE_FRAGMENTS):
                return {"ok": False}
            return {
                "ok": True,
                "detail": _localized_text(
                    (
                        "Natural-language zh-CN probe succeeded after the strict echo probe was unstable. "
                        "Trainer can keep using this connection for Chinese coaching."
                    ),
                    zh_natural_success,
                    response_language,
                ),
                "preview": preview,
                "kind": "natural_language_fallback",
            }

        previews: list[str] = []
        probe_variants: list[tuple[str, str, str]] = []
        message_probe = _message_probe_variant(probe_message)
        if message_probe is not None:
            probe_variants.append((message_probe[0], message_probe[1], "message"))
        if _prefers_chinese(response_language):
            probe_variants.extend(
                (prompt_text, expected_output, "generic")
                for prompt_text, expected_output in _LANGUAGE_PROBE_VARIANTS
            )
        if not probe_variants:
            return {
                "ok": True,
                "detail": "Language integrity probe skipped for this English-only flow.",
                "preview": "",
                "skipped": True,
            }

        last_inconclusive: dict[str, object] | None = None
        saw_blank_preview = False
        for _attempt in range(2):
            natural_fallback_attempted = False
            strict_successes = 0
            for prompt_text, expected_output, probe_kind in probe_variants:
                try:
                    request_payload = self._apply_request_defaults(
                        {
                            "model": model,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": "Return exactly the requested text. Do not explain or add quotes.",
                                },
                                {
                                    "role": "user",
                                    "content": prompt_text,
                                },
                            ],
                            "temperature": 0,
                            "max_tokens": probe_max_tokens,
                        },
                        provider,
                    )
                    response = client.chat.completions.create(**request_payload)
                except Exception as exc:  # pragma: no cover - network dependent
                    return {
                        "ok": False,
                        "category": "language_probe_inconclusive",
                        "detail": _localized_text(
                            (
                                "Language integrity probe could not complete after connectivity succeeded. "
                                f"Follow-up check failed: {redact_provider_error(exc, api_key=self._api_key)}"
                            ),
                            f"{zh_probe_failed}{redact_provider_error(exc, api_key=self._api_key)}",
                            response_language,
                        ),
                        "preview": "",
                    }

                content = response.choices[0].message.content if response.choices else None
                preview = _compact_visible_text(content)
                if not preview:
                    saw_blank_preview = True
                    last_inconclusive = {
                        "ok": False,
                        "category": "language_probe_inconclusive",
                        "detail": _localized_text(
                            (
                                "Language integrity probe returned no visible content after connectivity succeeded. "
                                "Trainer cannot verify non-English input on this connection."
                            ),
                            zh_no_visible,
                            response_language,
                        ),
                        "preview": "",
                    }
                    if not natural_fallback_attempted:
                        natural_fallback_attempted = True
                        fallback_probe = natural_language_probe_result()
                        if fallback_probe.get("ok") is True:
                            return fallback_probe
                    continue

                previews.append(preview)
                if expected_output in preview:
                    strict_successes += 1
                    continue

                if _looks_like_input_corruption_reply(preview, expected_probe=expected_output):
                    return {
                        "ok": False,
                        "category": "language_corruption",
                        "detail": _localized_text(
                            (
                                "Provider reachable, but it corrupted the actual mixed-language coaching "
                                "message into question marks before the model saw it."
                            )
                            if probe_kind == "message"
                            else (
                                "Provider reachable, but it corrupted Chinese input into question marks "
                                "before the model saw it."
                            ),
                            zh_message_corruption if probe_kind == "message" else zh_generic_corruption,
                            response_language,
                        ),
                        "preview": preview,
                    }

                if not natural_fallback_attempted:
                    natural_fallback_attempted = True
                    fallback_probe = natural_language_probe_result()
                    if fallback_probe.get("ok") is True:
                        return fallback_probe

                last_inconclusive = {
                    "ok": False,
                    "category": "language_probe_inconclusive",
                    "detail": _localized_text(
                        (
                            "Language integrity probe was inconclusive. The provider replied, but it did not preserve "
                            "the message-derived probe text exactly enough for Trainer to trust it."
                        )
                        if probe_kind == "message"
                        else (
                            "Language integrity probe was inconclusive. The provider replied, but it did not preserve "
                            "the mixed-language probe text exactly enough for Trainer to trust it."
                        ),
                        zh_message_inconclusive if probe_kind == "message" else zh_generic_inconclusive,
                        response_language,
                    ),
                    "preview": preview,
                }

            if strict_successes == len(probe_variants):
                recovered = saw_blank_preview or last_inconclusive is not None or _attempt > 0
                detail = _localized_text(
                    (
                        "Language integrity probe recovered after retry and preserved usable message-derived or mixed "
                        "CJK/ASCII text."
                        if recovered
                        else (
                            "Language integrity probe preserved the message-derived and mixed CJK/ASCII probe text across all checks."
                            if message_probe is not None or _prefers_chinese(response_language)
                            else "Language integrity probe preserved the mixed CJK/ASCII probe text across all checks."
                        )
                    ),
                    zh_retry_success
                    if recovered
                    else (
                        zh_strict_success
                        if message_probe is not None or _prefers_chinese(response_language)
                        else zh_generic_success
                    ),
                    response_language,
                )
                return {
                    "ok": True,
                    "detail": detail,
                    "preview": previews[-1] if previews else "",
                    "kind": "strict_integrity",
                }

        return last_inconclusive or {
            "ok": False,
            "category": "language_probe_inconclusive",
            "detail": _localized_text(
                (
                    "Language integrity probe returned no usable signal after connectivity succeeded. "
                    "Trainer cannot verify non-English input on this connection yet."
                ),
                zh_no_signal,
                response_language,
            ),
            "preview": previews[-1] if previews else "",
        }

    def detect_language_corruption(
        self,
        *,
        message: str,
        reply: str,
        response_language: str | None = None,
    ) -> bool:
        if (
            (_contains_cjk(message) or _prefers_chinese(response_language))
            and _looks_like_input_corruption_reply(reply)
        ):
            return True
        if _looks_like_mojibake_text(reply):
            return True
        return (
            _mixed_script_reply_corruption_detail(
                reply,
                message=message,
                response_language=response_language,
            )
            is not None
        )

    def _language_corruption_lane_note(
        self,
        scenario: str | None,
        response_language: str | None,
    ) -> str:
        normalized = str(scenario or "").strip().lower()
        if normalized == "remote_workspace":
            return _localized_text(
                "I am still keeping this turn in the VS Code remote lane.",
                "当前这轮我仍然保留在 VS Code remote 这条主线里。",
                response_language,
            )
        if normalized == "debug_loop":
            return _localized_text(
                "I am still keeping this turn in the VS Code debug lane.",
                "当前这轮我仍然保留在 VS Code debug 这条主线里。",
                response_language,
            )
        if normalized == "function_guidance":
            return _localized_text(
                "I am still keeping this turn in the function-guidance lane.",
                "当前这轮我仍然保留在 function-guidance 这条主线里。",
                response_language,
            )
        if normalized == "project_adaptation":
            return _localized_text(
                "I am still keeping this turn in the existing-project adaptation lane.",
                "当前这轮我仍然保留在 existing-project adaptation 这条主线里。",
                response_language,
            )
        return ""

    def language_corruption_summary(
        self,
        response_language: str | None,
        scenario: str | None = None,
    ) -> str:
        summary = _localized_text(
            "This provider is reachable, but it corrupted Chinese input into question marks before the model saw the message.",
            "模型服务可以连接，但中文内容在送到模型前变成了一串问号。",
            response_language,
        )
        if _prefers_chinese(response_language):
            summary = f"{summary} \u8bf7\u68c0\u67e5 provider \u662f\u5426\u652f\u6301\u4e2d\u6587\u3002"
        lane_note = self._language_corruption_lane_note(scenario, response_language)
        if lane_note:
            return f"{summary} {lane_note}"
        return summary

    def language_corruption_next_step(
        self,
        response_language: str | None,
        scenario: str | None = None,
    ) -> str:
        normalized = str(scenario or "").strip().lower()
        if normalized == "remote_workspace":
            return _localized_text(
                "Switch provider or gateway, or continue this remote lesson in English first. If you stay here, tell me whether the workspace is SSH, tunnels, dev container, WSL, or local, plus one real path or host label.",
                "先切换 provider 或 gateway，或者先用 English 继续这节 remote lesson。如果继续留在这里，请告诉我当前工作区是 SSH、tunnels、dev container、WSL 还是 local，并给我一个真实路径或 host label。",
                response_language,
            )
        if normalized == "debug_loop":
            return _localized_text(
                "Switch provider or gateway, or continue this debug lesson in English first. If you stay here, tell me where you will pause first and which single value, branch, or stack frame you expect to inspect.",
                "先切换 provider 或 gateway，或者先用 English 继续这节 debug lesson。如果继续留在这里，请告诉我你会先停在哪个断点，以及准备检查哪一个值、分支或 stack frame。",
                response_language,
            )
        if normalized == "function_guidance":
            return _localized_text(
                "Switch provider or gateway, or continue this function-guidance lesson in English first. If you stay here, give me the function name and one call site you can open right now.",
                "先切换 provider 或 gateway，或者先用 English 继续这节 function-guidance lesson。如果继续留在这里，请给我函数名，以及你现在就能打开的一个 call site。",
                response_language,
            )
        if normalized == "project_adaptation":
            return _localized_text(
                "Switch provider or gateway, or continue this project-adaptation lesson in English first. If you stay here, tell me what must stay stable, what must change, and the first boundary you want to adapt.",
                "先切换 provider 或 gateway，或者先用 English 继续这节 project-adaptation lesson。如果继续留在这里，请告诉我什么必须保持稳定、什么必须变化，以及你想先适配的第一条边界。",
                response_language,
            )
        return _localized_text(
            "Switch provider or gateway, or continue this test in English first, before resuming the coach thread.",
            "先切换 provider 或 gateway，或者先用 English 完成这次测试，再回来继续 coach thread。",
            response_language,
        )

    def language_corruption_reply(
        self,
        response_language: str | None,
        scenario: str | None = None,
    ) -> str:
        summary = self.language_corruption_summary(response_language, scenario=scenario)
        next_step = self.language_corruption_next_step(response_language, scenario=scenario)
        if _prefers_chinese(response_language):
            return (
                f"{summary}\n\n"
                "为了避免误导你，我不会把这段异常内容当成正常回答。"
                f"\n\n\u4e0b\u4e00\u6b65\uff1a{next_step}"
            )
        return (
            f"{summary}\n\n"
            "Trainer will not pretend this is a normal coaching turn, because the model never saw your actual sentence."
            f"\n\nNext step: {next_step}"
        )

    def _record_reply_language_corruption(self, detail: str) -> None:
        self._record_last_reply_failure(
            category="language_corruption",
            detail=detail,
            retryable=False,
            status_code=200,
            provider_reachable=True,
            model_supported=True,
            error=ValueError(detail),
        )

    def _configured_protocol(self, provider: ProviderConfig) -> ProviderProtocol | None:
        return normalize_provider_protocol(getattr(provider, "protocol", None))

    def recommended_generation_max_tokens(self, default: int) -> int:
        """Reasoning-first models can spend the whole default budget on hidden
        reasoning before any visible JSON appears, so grant them headroom."""
        if self._config is not None and _model_looks_reasoning_first(self._config):
            return max(default, 8192)
        return default

    def _plain_completion_protocol(self) -> str | None:
        provider = self._config or ProviderConfig(
            name="unspecified-provider",
            baseUrl="",
            apiKeyRef="trainer.unspecified",
            model=self._resolve_model(),
        )
        return self._configured_protocol(provider)

    def _plain_completion_uses_agent_binding(self) -> bool:
        protocol = self._plain_completion_protocol()
        if (
            protocol == "gemini_generate_content"
            and self._config is not None
            and not self._gemini_base_url_is_google_native(self._config)
        ):
            return False
        return protocol not in {
            "openai_chat_completions",
            "openai_chat_completions_compatible",
        }

    async def _completion_via_agent_binding(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int | None = None,
        prefer_configured_output: bool = False,
        allow_local_empty_fallback: bool = False,
    ) -> str:
        prepared_messages, effective_max_tokens = self._prepare_context_budget(
            messages,
            requested_max_tokens=max_tokens,
            prefer_configured_output=prefer_configured_output,
        )
        provider, _binding = self.build_agent_provider(
            protocol=self._plain_completion_protocol(),
            temperature=temperature,
            max_tokens=effective_max_tokens,
        )
        try:
            result = await provider.call(prepared_messages, None)
        except ProviderRuntimeResponseError as exc:
            if allow_local_empty_fallback and exc.provider_error_category in {
                "empty_response",
                "reasoning_leak",
            }:
                return ""
            raise
        return _visible_model_text(result.get("content"))

    async def _completion_stream_via_agent_binding(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int | None = None,
        prefer_configured_output: bool = False,
        allow_local_empty_fallback: bool = False,
        cancel_event: asyncio.Event | None = None,
    ):
        prepared_messages, effective_max_tokens = self._prepare_context_budget(
            messages,
            requested_max_tokens=max_tokens,
            prefer_configured_output=prefer_configured_output,
        )
        provider, _binding = self.build_agent_provider(
            protocol=self._plain_completion_protocol(),
            temperature=temperature,
            max_tokens=effective_max_tokens,
        )
        emitted = ""
        stream_call = provider.call_stream
        if stream_call is None:
            raise RuntimeError("The configured agent provider does not support streaming.")
        try:
            async for event in _iterate_provider_stream_with_cancellation(
                stream_call(prepared_messages, None),
                cancel_event,
            ):
                event_type = str(event.get("type") or "")
                if event_type in {"delta", "text"}:
                    chunk = str(event.get("delta") or event.get("chunk") or "")
                    if chunk:
                        emitted += chunk
                        yield chunk
                    continue
                if event_type != "final":
                    continue
                final_content = _visible_model_text(event.get("content"))
                if not final_content:
                    continue
                if not emitted:
                    emitted = final_content
                    yield final_content
                elif final_content.startswith(emitted):
                    suffix = final_content[len(emitted) :]
                    if suffix:
                        emitted = final_content
                        yield suffix
        except ProviderRuntimeResponseError as exc:
            if allow_local_empty_fallback and exc.provider_error_category in {
                "empty_response",
                "reasoning_leak",
            }:
                return
            raise

    def _native_probe_preview(self, content: object | None) -> str:
        return _compact_visible_text(content, limit=240)

    @staticmethod
    def _trusted_visible_probe_reply(preview: str) -> bool:
        visible = _compact_visible_text(preview, limit=240)
        return bool(
            visible
            and not _looks_like_mojibake_text(visible)
            and not _QUESTION_RUN_PATTERN.search(visible)
            and not _looks_like_input_corruption_reply(visible)
        )

    def _native_provider_success(
        self,
        *,
        protocol: str,
        provider: ProviderConfig,
        preview: str,
        diagnostics: list[str],
    ) -> ProviderTestResponse:
        return ProviderTestResponse(
            ok=True,
            detail=(
                f"Provider reachable. Native {protocol} probe succeeded with model "
                f"{provider.model}. Response: {preview}"
            ),
            diagnostics=diagnostics,
            provider_reachable=True,
            model_supported=True,
        )

    def _native_provider_empty_response(
        self,
        *,
        protocol: str,
        provider: ProviderConfig,
        diagnostics: list[str],
        hidden_reasoning_observed: bool = False,
        reasoning_budget_exhausted: bool = False,
    ) -> ProviderTestResponse:
        if hidden_reasoning_observed:
            diagnostics = [*diagnostics, "Native probe returned hidden reasoning without visible text."]
        error_category = _unusable_visible_reply_category(
            hidden_reasoning_observed=hidden_reasoning_observed,
            reasoning_budget_exhausted=reasoning_budget_exhausted,
        )
        detail = (
            f"Provider reachable, but the native {protocol} probe returned no usable visible reply "
            f"for model {provider.model}."
        )
        if error_category == "reasoning_budget_exhausted":
            detail = (
                f"Provider reachable, but the native {protocol} probe's hidden reasoning consumed the "
                f"entire output budget for model {provider.model}. Retry, or choose a non-reasoning "
                "model for short probes."
            )
        return ProviderTestResponse(
            ok=False,
            detail=detail,
            error_category=error_category,
            retryable=True,
            status_code=200,
            diagnostics=diagnostics,
            provider_reachable=True,
            model_supported=True,
        )

    def _native_protocol_probe_preview(
        self,
        *,
        protocol: str,
        provider: ProviderConfig,
        api_key: str,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 96,
    ) -> str:
        max_tokens = _visible_probe_max_tokens(provider, max_tokens)
        if protocol == "openai_responses":
            client = self._create_sync_client(provider, api_key)
            payload: dict[str, Any] = {
                "model": provider.model,
                "input": prompt,
                "temperature": 0,
                "max_output_tokens": max_tokens,
            }
            if system:
                payload["instructions"] = system
            response = client.responses.create(**payload)
            return self._native_probe_preview(getattr(response, "output_text", ""))

        if protocol == "anthropic_messages":
            payload = {
                "model": provider.model,
                "max_tokens": max(64, max_tokens),
                "system": system
                or "Return visible text in the message content. Do not answer only with hidden reasoning.",
                "messages": [{"role": "user", "content": prompt}],
            }
            payload = self._apply_anthropic_native_probe_defaults(payload, provider)
            with self._direct_http_client(provider, timeout=60.0) as client:
                response = client.post(
                    f"{self._anthropic_base_url(provider)}/v1/messages",
                    json=payload,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                )
            if response.status_code >= 400:
                raise RuntimeError(
                    redact_provider_error(
                        {"upstream_body": response.text},
                        api_key=api_key,
                        fallback=f"Anthropic Messages probe failed (HTTP {response.status_code})",
                    )
                )
            body = response.json()
            text_parts = [
                str(block.get("text") or "")
                for block in body.get("content") or []
                if isinstance(block, dict) and str(block.get("type") or "") == "text"
            ]
            return self._native_probe_preview("".join(text_parts))

        if protocol == "gemini_generate_content":
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
                "generationConfig": {"temperature": 0, "maxOutputTokens": max(256, max_tokens)},
            }
            if system:
                payload["systemInstruction"] = {"parts": [{"text": system}]}
            payload = self._apply_gemini_native_probe_defaults(payload, provider)
            with self._direct_http_client(provider, timeout=60.0) as client:
                response = client.post(
                    self._gemini_endpoint(provider),
                    json=payload,
                    headers={
                        "x-goog-api-key": api_key,
                        "content-type": "application/json",
                    },
                )
            if response.status_code >= 400:
                raise RuntimeError(
                    redact_provider_error(
                        {"upstream_body": response.text},
                        api_key=api_key,
                        fallback=f"Gemini GenerateContent probe failed (HTTP {response.status_code})",
                    )
                )
            body = response.json()
            text_parts: list[str] = []
            for candidate in body.get("candidates") or []:
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content") or {}
                for part in content.get("parts") or []:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        text_parts.append(part["text"])
            return self._native_probe_preview("".join(text_parts))

        raise RuntimeError(f"Unsupported native protocol probe for {protocol}.")

    def _native_protocol_language_probe_result_resilient(
        self,
        *,
        protocol: str,
        provider: ProviderConfig,
        api_key: str,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> dict[str, object]:
        service = self

        class _NativeProtocolCompletions:
            def create(self, **kwargs: Any) -> Any:
                messages = kwargs.get("messages") or []
                system_parts: list[str] = []
                user_text = ""
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    role = str(message.get("role") or "").strip().lower()
                    content = str(message.get("content") or "")
                    if role == "system" and content:
                        system_parts.append(content)
                    elif role == "user" and content:
                        user_text = content
                preview = service._native_protocol_probe_preview(
                    protocol=protocol,
                    provider=provider,
                    api_key=api_key,
                    prompt=user_text,
                    system="\n\n".join(part for part in system_parts if part.strip()) or None,
                    max_tokens=int(kwargs.get("max_tokens") or 96),
                )
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=preview))]
                )

        native_client = SimpleNamespace(
            chat=SimpleNamespace(completions=_NativeProtocolCompletions())
        )
        return self._language_probe_result_resilient(
            client=native_client,
            model=provider.model,
            provider=provider,
            probe_message=probe_message,
            response_language=response_language,
        )

    def _finalize_native_protocol_test(
        self,
        *,
        protocol: str,
        provider: ProviderConfig,
        api_key: str,
        preview: str,
        diagnostics: list[str],
        hidden_reasoning_observed: bool = False,
        reasoning_budget_exhausted: bool = False,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> ProviderTestResponse:
        language_probe: dict[str, object] | None = None
        if not preview:
            language_probe = self._native_protocol_language_probe_result_resilient(
                protocol=protocol,
                provider=provider,
                api_key=api_key,
                probe_message=probe_message,
                response_language=response_language,
            )
            recovered_preview = str(language_probe.get("preview") or "").strip()
            if recovered_preview:
                diagnostics.append(
                    "Native visible-text probe returned no visible text, but the language integrity probe recovered usable visible text."
                )
                preview = recovered_preview
            else:
                return self._native_provider_empty_response(
                    protocol=protocol,
                    provider=provider,
                    diagnostics=diagnostics,
                    hidden_reasoning_observed=hidden_reasoning_observed,
                    reasoning_budget_exhausted=reasoning_budget_exhausted,
                )

        if language_probe is None:
            language_probe = self._native_protocol_language_probe_result_resilient(
                protocol=protocol,
                provider=provider,
                api_key=api_key,
                probe_message=probe_message,
                response_language=response_language,
            )
        if language_probe.get("ok") is False:
            probe_category = str(
                language_probe.get("category") or "language_probe_inconclusive"
            ).strip() or "language_probe_inconclusive"
            probe_detail = str(language_probe.get("detail") or "").strip()
            probe_preview = str(language_probe.get("preview") or "").strip()
            diagnostics.append(f"Probe response preview: {preview}")
            if probe_category == "language_corruption":
                diagnostics.append(
                    "Language integrity probe failed: the mixed CJK/ASCII probe text was corrupted."
                )
            else:
                diagnostics.append(
                    "Language integrity probe was inconclusive: the mixed CJK/ASCII probe text was not preserved clearly enough."
                )
            if probe_preview:
                diagnostics.append(f"Language probe preview: {probe_preview}")
            if (
                probe_category == "language_probe_inconclusive"
                and self._trusted_visible_probe_reply(preview)
            ):
                diagnostics.append(
                    "A trusted visible probe reply succeeded, so the inconclusive optional language check is not blocking this connection."
                )
                return ProviderTestResponse(
                    ok=True,
                    detail=_localized_text(
                        (
                            f"Provider reachable. Native {protocol} probe returned a usable visible reply for "
                            f"model {provider.model}. The optional zh-CN integrity check was inconclusive, "
                            "so Trainer will keep checking future replies."
                        ),
                        (
                            f"provider 已连通，当前 model「{provider.model}」返回了可用的可见回复。"
                            "中文完整性补充检查没有得到确定结论，Trainer 会继续检查后续回复。"
                        ),
                        response_language,
                    ),
                    diagnostics=diagnostics,
                    provider_reachable=True,
                    model_supported=True,
                )
            return ProviderTestResponse(
                ok=False,
                detail=probe_detail
                or (
                    "Provider reachable, but Trainer could not fully verify zh-CN input integrity on this connection yet."
                    if probe_category == "language_probe_inconclusive"
                    else (
                        "Provider reachable, but it corrupted Chinese input into question marks "
                        "before the model saw it. Trainer cannot safely coach in zh-CN on this "
                        "connection yet."
                    )
                ),
                error_category=probe_category,
                retryable=False,
                status_code=200,
                diagnostics=diagnostics,
                provider_reachable=True,
                model_supported=True,
            )

        probe_detail = str(language_probe.get("detail") or "").strip()
        if probe_detail:
            diagnostics.append(probe_detail)
        success_detail = (
            probe_detail
            if language_probe.get("kind") == "natural_language_fallback"
            else (
                f"Provider reachable. Native {protocol} probe succeeded with model "
                f"{provider.model}. Response: {preview}"
            )
        )
        return ProviderTestResponse(
            ok=True,
            detail=success_detail,
            diagnostics=diagnostics,
            provider_reachable=True,
            model_supported=True,
        )

    def _native_probe_prompts(self, response_language: str | None = None) -> list[str]:
        if _prefers_chinese(response_language):
            return [
                "只返回一个可见中文短句：provider ready。",
                (
                    "请只输出可见文字：provider ready。"
                    "不要只返回 reasoning、tool call 或 hidden text。"
                ),
            ]
        return [
            "Reply with exactly: pong",
            (
                "Return one short visible sentence only: provider ready. "
                "Do not return only reasoning, tool calls, or hidden text."
            ),
        ]

    def _apply_anthropic_native_probe_defaults(
        self,
        payload: dict[str, Any],
        provider: ProviderConfig,
    ) -> dict[str, Any]:
        defaults = self._provider_request_defaults(provider)
        if not defaults:
            return payload
        merged = dict(payload)
        extra_body = defaults.get("extra_body")
        if isinstance(extra_body, dict):
            merged.update(extra_body)
        max_tokens = defaults.get("max_tokens", defaults.get("maxTokens"))
        if isinstance(max_tokens, int) and max_tokens > 0:
            merged["max_tokens"] = min(max_tokens, max(64, int(merged.get("max_tokens") or 64)))
        for key in ("temperature", "top_p", "top_k", "stop_sequences"):
            if key in defaults and defaults[key] is not None:
                merged[key] = defaults[key]
        if not self._anthropic_base_url_is_official(provider):
            # Previously an unconditional `thinking: disabled`. That is still the
            # right first attempt for reasoning-first gateways (it keeps probe
            # replies short), but it must not be a blanket override: a user's
            # explicit request_defaults wins, and models that *require* thinking
            # reject this field with HTTP 400. provider.thinking re-negotiates
            # the policy per model at runtime and replays the request.
            return apply_thinking_policy(
                merged, resolve_thinking_policy(merged, provider)
            )
        thinking_budget = defaults.get("thinking_budget", defaults.get("thinkingBudget"))
        if isinstance(thinking_budget, int) and thinking_budget > 0:
            merged["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        elif isinstance(thinking_budget, str) and thinking_budget.strip().lower() == "disabled":
            merged.pop("thinking", None)
        return _flatten_minimax_thinking_for_raw_http(merged, provider)

    # --- thinking re-negotiation ------------------------------------------------
    # A gateway may reject the `thinking` request field outright (mandatory-
    # thinking models answer HTTP 400 "requires adaptive thinking"). Rather than
    # failing the turn, replay once with the policy the gateway actually accepts
    # and remember it for this (base_url, model) so later requests go out right.

    @staticmethod
    def _retry_payload_for_thinking(
        payload: dict[str, Any],
        provider: ProviderConfig | None,
        attempted: str,
        policy: str,
    ) -> dict[str, Any] | None:
        """Rebuild ``payload`` under a different thinking policy, or ``None``.

        Returns ``None`` when a user-declared ``enabled`` opt-in is in play — we
        never silently downgrade a choice the user made themselves.
        """
        if declared_thinking(payload) == "enabled" and policy != "enabled":
            return None
        candidate = apply_thinking_policy(payload, policy)  # type: ignore[arg-type]
        if candidate.get("thinking") == payload.get("thinking") and (
            candidate.get("extra_body") or {}
        ) == (payload.get("extra_body") or {}):
            return None
        if provider is not None:
            remember_policy(provider, policy)  # type: ignore[arg-type]
        return candidate

    def _thinking_scope(self, provider: ProviderConfig | None) -> ProviderConfig | None:
        """The provider identity a learned thinking policy is cached under."""
        return provider or self._config

    def _create_chat_completion_negotiated(
        self,
        client: Any,
        payload: dict[str, Any],
        provider: ProviderConfig | None = None,
    ) -> Any:
        """Sync ``chat.completions.create`` with one thinking re-negotiation."""
        scope = self._thinking_scope(provider)
        attempted = declared_thinking(payload) or (learned_policy(scope) if scope else None) or "disabled"
        try:
            return client.chat.completions.create(**payload)
        except Exception as exc:
            policy = thinking_rejection_policy(exc, attempted)
            if policy is None:
                raise
            retry_payload = self._retry_payload_for_thinking(payload, scope, attempted, policy)
            if retry_payload is None:
                raise
            try:
                return client.chat.completions.create(**retry_payload)
            except Exception as retry_exc:
                # The first rejection is the actionable diagnosis ("this model
                # requires adaptive thinking"). Never let a retry's own failure
                # mask it — re-raise the original and chain the retry detail.
                raise exc from retry_exc

    async def _create_chat_completion_negotiated_async(
        self,
        client: Any,
        payload: dict[str, Any],
        provider: ProviderConfig | None = None,
    ) -> Any:
        """Async ``chat.completions.create`` with one thinking re-negotiation."""
        scope = self._thinking_scope(provider)
        attempted = declared_thinking(payload) or (learned_policy(scope) if scope else None) or "disabled"
        try:
            return await client.chat.completions.create(**payload)
        except Exception as exc:
            policy = thinking_rejection_policy(exc, attempted)
            if policy is None:
                raise
            retry_payload = self._retry_payload_for_thinking(payload, scope, attempted, policy)
            if retry_payload is None:
                raise
            try:
                return await client.chat.completions.create(**retry_payload)
            except Exception as retry_exc:
                raise exc from retry_exc

    def _apply_gemini_native_probe_defaults(
        self,
        payload: dict[str, Any],
        provider: ProviderConfig,
    ) -> dict[str, Any]:
        defaults = self._provider_request_defaults(provider)
        if not defaults:
            return payload
        merged = dict(payload)
        extra_body = defaults.get("extra_body")
        if isinstance(extra_body, dict):
            merged.update(extra_body)
        generation_config = dict(merged.get("generationConfig") or {})
        if isinstance(defaults.get("generationConfig"), dict):
            generation_config.update(defaults["generationConfig"])
        max_tokens = defaults.get("maxOutputTokens", defaults.get("maxTokens"))
        if isinstance(max_tokens, int) and max_tokens > 0:
            generation_config["maxOutputTokens"] = max(max_tokens, int(generation_config.get("maxOutputTokens") or 256), 256)
        for key in ("temperature", "topP", "topK", "candidateCount", "stopSequences"):
            if key in defaults and defaults[key] is not None:
                generation_config[key] = defaults[key]
        merged["generationConfig"] = generation_config
        return _flatten_minimax_thinking_for_raw_http(merged, provider)

    def _test_openai_responses_protocol(
        self,
        provider: ProviderConfig,
        api_key: str,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> ProviderTestResponse:
        diagnostics = ["Using native openai_responses probe."]
        try:
            client = self._create_sync_client(provider, api_key)
            last_error: Exception | None = None
            response = None
            chosen_model = provider.model
            preview = ""
            hidden_reasoning_observed = False
            reasoning_budget_exhausted = False
            probe_output_budget = _visible_probe_max_tokens(provider, default=32)
            for candidate in self._model_candidates(provider.model):
                chosen_model = candidate
                try:
                    for attempt, prompt in enumerate(
                        self._native_probe_prompts(response_language),
                        start=1,
                    ):
                        response = client.responses.create(
                            model=candidate,
                            input=prompt,
                            temperature=0,
                            max_output_tokens=probe_output_budget,
                        )
                        hidden_reasoning_observed = _has_hidden_reasoning(response)
                        reasoning_budget_exhausted = (
                            reasoning_budget_exhausted
                            or _reasoning_budget_exhausted(
                                response,
                                max_tokens=probe_output_budget,
                            )
                        )
                        preview = self._native_probe_preview(getattr(response, "output_text", ""))
                        if preview:
                            if attempt > 1:
                                diagnostics.append(
                                    "Responses probe returned visible text after empty first attempt."
                                )
                            break
                        diagnostics.append(
                            f"Responses probe returned no visible text on attempt {attempt}."
                        )
                    if preview:
                        break
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if not self._is_model_not_supported_error(exc):
                        raise
            if response is None:
                raise last_error or RuntimeError(f"Unable to resolve model {provider.model}.")
            diagnostics.append(f"Responses probe succeeded with model {chosen_model}.")
            return self._finalize_native_protocol_test(
                protocol="openai_responses",
                provider=provider,
                api_key=api_key,
                preview=preview,
                diagnostics=diagnostics,
                hidden_reasoning_observed=hidden_reasoning_observed,
                reasoning_budget_exhausted=reasoning_budget_exhausted,
                probe_message=probe_message,
                response_language=response_language,
            )
        except Exception as exc:
            category, retryable, status_code, provider_reachable, model_supported = self._classify_error(exc)
            return ProviderTestResponse(
                ok=False,
                detail=self._detail_from_category(category, provider=provider, error=exc),
                error_category=category,
                retryable=retryable,
                status_code=status_code,
                diagnostics=[*diagnostics, redact_provider_error(exc, api_key=api_key)],
                provider_reachable=provider_reachable,
                model_supported=model_supported,
            )

    def _anthropic_base_url(self, provider: ProviderConfig) -> str:
        base_url = str(provider.base_url or "").strip().rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[: -len("/v1")]
        return base_url or "https://api.anthropic.com"

    def _test_anthropic_messages_protocol(
        self,
        provider: ProviderConfig,
        api_key: str,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> ProviderTestResponse:
        diagnostics = ["Using native anthropic_messages probe."]
        try:
            preview = ""
            hidden_reasoning_observed = False
            with self._direct_http_client(provider, timeout=60.0) as client:
                for attempt, prompt in enumerate(
                    self._native_probe_prompts(response_language),
                    start=1,
                ):
                    payload = {
                        "model": provider.model,
                        "max_tokens": _visible_probe_max_tokens(provider, default=64),
                        "system": (
                            "Return visible text in the message content. "
                            "Do not answer only with hidden reasoning."
                        ),
                        "messages": [{"role": "user", "content": prompt}],
                    }
                    payload = self._apply_anthropic_native_probe_defaults(payload, provider)
                    response = client.post(
                        f"{self._anthropic_base_url(provider)}/v1/messages",
                        json=payload,
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                    )
                    if response.status_code >= 400:
                        raise RuntimeError(
                            redact_provider_error(
                                {"upstream_body": response.text},
                                api_key=api_key,
                                fallback=f"Anthropic Messages probe failed (HTTP {response.status_code})",
                            )
                        )
                    body = response.json()
                    hidden_reasoning_observed = hidden_reasoning_observed or _has_hidden_reasoning(body)
                    text_parts = [
                        str(block.get("text") or "")
                        for block in body.get("content") or []
                        if isinstance(block, dict) and str(block.get("type") or "") == "text"
                    ]
                    preview = self._native_probe_preview("".join(text_parts))
                    if preview:
                        if attempt > 1:
                            diagnostics.append(
                                "Anthropic Messages probe returned visible text after empty first attempt."
                            )
                        break
                    diagnostics.append(
                        f"Anthropic Messages probe returned no visible text on attempt {attempt}."
                    )
            diagnostics.append("Anthropic Messages probe reached /v1/messages.")
            return self._finalize_native_protocol_test(
                protocol="anthropic_messages",
                provider=provider,
                api_key=api_key,
                preview=preview,
                diagnostics=diagnostics,
                hidden_reasoning_observed=hidden_reasoning_observed,
                probe_message=probe_message,
                response_language=response_language,
            )
        except Exception as exc:
            category, retryable, status_code, provider_reachable, model_supported = self._classify_error(exc)
            return ProviderTestResponse(
                ok=False,
                detail=self._detail_from_category(category, provider=provider, error=exc),
                error_category=category,
                retryable=retryable,
                status_code=status_code,
                diagnostics=[*diagnostics, redact_provider_error(exc, api_key=api_key)],
                provider_reachable=provider_reachable,
                model_supported=model_supported,
            )

    def _gemini_endpoint(self, provider: ProviderConfig) -> str:
        base_url = str(provider.base_url or "").strip().rstrip("/")
        if not base_url:
            base_url = "https://generativelanguage.googleapis.com/v1beta"
        if base_url.endswith(":generateContent"):
            return base_url
        if "/models/" in base_url:
            return f"{base_url}:generateContent"
        if not (base_url.endswith("/v1") or base_url.endswith("/v1beta")):
            base_url = f"{base_url}/v1beta"
        escaped_model = quote(provider.model, safe="/-_.")
        return f"{base_url}/models/{escaped_model}:generateContent"

    def _test_gemini_generate_content_protocol(
        self,
        provider: ProviderConfig,
        api_key: str,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> ProviderTestResponse:
        diagnostics = ["Using native gemini_generate_content probe."]
        try:
            preview = ""
            hidden_reasoning_observed = False
            with self._direct_http_client(provider, timeout=60.0) as client:
                for attempt, prompt in enumerate(
                    self._native_probe_prompts(response_language),
                    start=1,
                ):
                    payload = {
                        "contents": [
                            {
                                "role": "user",
                                "parts": [{"text": prompt}],
                            }
                        ],
                        "generationConfig": {"temperature": 0, "maxOutputTokens": 256},
                    }
                    payload = self._apply_gemini_native_probe_defaults(payload, provider)
                    response = client.post(
                        self._gemini_endpoint(provider),
                        json=payload,
                        headers={
                            "x-goog-api-key": api_key,
                            "content-type": "application/json",
                        },
                    )
                    if response.status_code >= 400:
                        raise RuntimeError(
                            redact_provider_error(
                                {"upstream_body": response.text},
                                api_key=api_key,
                                fallback=f"Gemini GenerateContent probe failed (HTTP {response.status_code})",
                            )
                        )
                    body = response.json()
                    hidden_reasoning_observed = hidden_reasoning_observed or _has_hidden_reasoning(body)
                    text_parts: list[str] = []
                    for candidate in body.get("candidates") or []:
                        if not isinstance(candidate, dict):
                            continue
                        content = candidate.get("content") or {}
                        for part in content.get("parts") or []:
                            if isinstance(part, dict) and isinstance(part.get("text"), str):
                                text_parts.append(part["text"])
                    preview = self._native_probe_preview("".join(text_parts))
                    if preview:
                        if attempt > 1:
                            diagnostics.append(
                                "Gemini GenerateContent probe returned visible text after empty first attempt."
                            )
                        break
                    diagnostics.append(
                        f"Gemini GenerateContent probe returned no visible text on attempt {attempt}."
                    )
            diagnostics.append("Gemini GenerateContent probe reached generateContent.")
            return self._finalize_native_protocol_test(
                protocol="gemini_generate_content",
                provider=provider,
                api_key=api_key,
                preview=preview,
                diagnostics=diagnostics,
                hidden_reasoning_observed=hidden_reasoning_observed,
                probe_message=probe_message,
                response_language=response_language,
            )
        except Exception as exc:
            category, retryable, status_code, provider_reachable, model_supported = self._classify_error(exc)
            return ProviderTestResponse(
                ok=False,
                detail=self._detail_from_category(category, provider=provider, error=exc),
                error_category=category,
                retryable=retryable,
                status_code=status_code,
                diagnostics=[*diagnostics, redact_provider_error(exc, api_key=api_key)],
                provider_reachable=provider_reachable,
                model_supported=model_supported,
            )

    def _test_native_protocol(
        self,
        provider: ProviderConfig,
        api_key: str,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> ProviderTestResponse | None:
        protocol = self._configured_protocol(provider)
        if protocol == "openai_responses":
            return self._test_openai_responses_protocol(
                provider,
                api_key,
                probe_message,
                response_language,
            )
        if protocol == "anthropic_messages":
            return self._test_anthropic_messages_protocol(
                provider,
                api_key,
                probe_message,
                response_language,
            )
        if protocol == "gemini_generate_content":
            if not self._gemini_base_url_is_google_native(provider):
                return None
            return self._test_gemini_generate_content_protocol(
                provider,
                api_key,
                probe_message,
                response_language,
            )
        return None

    def _tool_probe_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"probe": {"type": "string", "enum": ["ok"]}},
            "required": ["probe"],
            "additionalProperties": False,
        }

    def _tool_probe_response(
        self,
        provider: ProviderConfig,
        api_key: str,
    ) -> tuple[str, object]:
        protocol = self._configured_protocol(provider)
        schema = self._tool_probe_schema()
        if protocol == "anthropic_messages":
            payload: dict[str, Any] = {
                "model": provider.model,
                "max_tokens": 64,
                "messages": [{"role": "user", "content": _TOOL_CAPABILITY_PROBE_PROMPT}],
            }
            payload = self._apply_anthropic_native_probe_defaults(payload, provider)
            payload["tools"] = [
                {
                    "name": _TOOL_CAPABILITY_PROBE_NAME,
                    "description": "Internal capability probe. Do not perform any action.",
                    "input_schema": schema,
                }
            ]
            payload["tool_choice"] = {"type": "tool", "name": _TOOL_CAPABILITY_PROBE_NAME}
            with self._direct_http_client(provider, timeout=30.0) as client:
                response = client.post(
                    f"{self._anthropic_base_url(provider)}/v1/messages",
                    json=payload,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                )
            if response.status_code >= 400:
                raise RuntimeError(f"Anthropic Messages tool probe failed (HTTP {response.status_code}).")
            return protocol, response.json()

        openai_tool = {
            "type": "function",
            "function": {
                "name": _TOOL_CAPABILITY_PROBE_NAME,
                "description": "Internal capability probe. Do not perform any action.",
                "parameters": schema,
            },
        }
        if protocol == "openai_responses":
            client = self._create_sync_client(provider, api_key)
            response = client.responses.create(
                model=provider.model,
                input=_TOOL_CAPABILITY_PROBE_PROMPT,
                tools=[
                    {
                        "type": "function",
                        "name": _TOOL_CAPABILITY_PROBE_NAME,
                        "description": "Internal capability probe. Do not perform any action.",
                        "parameters": schema,
                    }
                ],
                tool_choice={"type": "function", "name": _TOOL_CAPABILITY_PROBE_NAME},
                max_output_tokens=64,
            )
            return protocol, response

        if protocol == "gemini_generate_content" and self._gemini_base_url_is_google_native(provider):
            payload = self._apply_gemini_native_probe_defaults(
                {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": _TOOL_CAPABILITY_PROBE_PROMPT}],
                        }
                    ],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": 64},
                },
                provider,
            )
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": _TOOL_CAPABILITY_PROBE_NAME,
                            "description": "Internal capability probe. Do not perform any action.",
                            "parameters": schema,
                        }
                    ]
                }
            ]
            payload["toolConfig"] = {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": [_TOOL_CAPABILITY_PROBE_NAME],
                }
            }
            with self._direct_http_client(provider, timeout=30.0) as client:
                response = client.post(
                    self._gemini_endpoint(provider),
                    json=payload,
                    headers={
                        "x-goog-api-key": api_key,
                        "content-type": "application/json",
                    },
                )
            if response.status_code >= 400:
                raise RuntimeError(f"Gemini GenerateContent tool probe failed (HTTP {response.status_code}).")
            return protocol, response.json()

        client = self._create_sync_client(provider, api_key)
        payload = self._apply_request_defaults(
            {
                "model": provider.model,
                "messages": [{"role": "user", "content": _TOOL_CAPABILITY_PROBE_PROMPT}],
                "temperature": 0,
                "max_tokens": 64,
            },
            provider,
        )
        payload["tools"] = [openai_tool]
        payload["tool_choice"] = {
            "type": "function",
            "function": {"name": _TOOL_CAPABILITY_PROBE_NAME},
        }
        return "openai_chat_completions_compatible", client.chat.completions.create(**payload)

    def _probe_vision_capability(
        self,
        provider: ProviderConfig,
        api_key: str,
    ) -> tuple[bool | None, str]:
        """Probe vision using the same native image block shape as runtime delivery."""
        protocol = self._configured_protocol(provider)
        if protocol not in {
            "openai_responses",
            "openai_chat_completions",
            "openai_chat_completions_compatible",
            "anthropic_messages",
            "gemini_generate_content",
        }:
            return None, "Vision probe is unsupported for this provider protocol."
        challenge = build_vision_challenge()
        try:
            if protocol == "openai_responses":
                client = self._create_sync_client(provider, api_key)
                response = client.responses.create(
                    model=provider.model,
                    input=openai_responses_input_image_parts(
                        prompt=challenge.prompt,
                        image_url=challenge.image_url,
                    ),
                    temperature=0,
                    max_output_tokens=96,
                )
            elif protocol in {"openai_chat_completions", "openai_chat_completions_compatible"}:
                client = self._create_sync_client(provider, api_key)
                vision_max_tokens = 256 if _needs_generous_visible_probe_budget(provider) else 96
                payload = self._apply_request_defaults(
                    {
                        "model": provider.model,
                        "messages": [{"role": "user", "content": [
                            {"type": "text", "text": challenge.prompt},
                            {"type": "image_url", "image_url": {"url": challenge.image_url}},
                        ]}],
                        "temperature": 0,
                        "max_tokens": vision_max_tokens,
                    },
                    provider,
                )
                if _is_minimax_like_provider(provider):
                    extra_body = dict(payload.get("extra_body") or {})
                    extra_body["thinking"] = {"type": "disabled"}
                    payload["extra_body"] = extra_body
                response = client.chat.completions.create(**payload)
            elif protocol == "anthropic_messages":
                from .agent_binding import _anthropic_image_blocks

                image_data = challenge.image_url.split(",", 1)[1]
                image_block = _anthropic_image_blocks([
                    {"kind": "image", "mime_type": "image/png", "data_base64": image_data}
                ])[0]
                payload = self._apply_anthropic_native_probe_defaults({
                    "model": provider.model,
                    "max_tokens": 96,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": challenge.prompt},
                        image_block,
                    ]}],
                }, provider)
                with self._direct_http_client(provider, timeout=60.0) as client:
                    response = client.post(
                        f"{self._anthropic_base_url(provider)}/v1/messages",
                        json=payload,
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                    )
                if response.status_code >= 400:
                    return False, "Vision probe was rejected by the provider."
                response = response.json()
            else:
                image_data = challenge.image_url.split(",", 1)[1]
                payload = self._apply_gemini_native_probe_defaults({
                    "contents": [{"role": "user", "parts": [
                        {"text": challenge.prompt},
                        {"inlineData": {"mimeType": "image/png", "data": image_data}},
                    ]}],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": 96},
                }, provider)
                with self._direct_http_client(provider, timeout=60.0) as client:
                    response = client.post(
                        self._gemini_endpoint(provider),
                        json=payload,
                        headers={
                            "x-goog-api-key": api_key,
                            "content-type": "application/json",
                        },
                    )
                if response.status_code >= 400:
                    return False, "Vision probe was rejected by the provider."
                response = response.json()
            assessment = normalize_provider_response(protocol, response, api_key=api_key)
        except Exception:
            return None, "Vision capability probe could not complete safely."
        visible = assessment.content.strip()
        # Think-text / hidden reasoning must never count as vision-ready.
        if assessment.has_visible_text and challenge.matches(visible):
            return True, "Vision probe correctly read randomized image content."
        if assessment.has_visible_text:
            return False, "Vision probe did not correctly read the randomized image content."
        if assessment.outcome == "reasoning_only":
            return None, "Vision probe returned hidden reasoning instead of a visible token."
        if assessment.outcome in {"protocol_mismatch", "provider_error"}:
            return False, "Vision probe was rejected by the provider."
        return None, "Vision probe did not return a trustworthy visible result."

    def _probe_tool_capability(
        self,
        provider: ProviderConfig,
        api_key: str,
    ) -> tuple[bool | None, str]:
        try:
            protocol, response = self._tool_probe_response(provider, api_key)
        except Exception:  # noqa: BLE001 - failures are deliberately reduced to capability truth.
            return None, "Tool-call capability probe could not complete safely."
        assessment = assess_provider_tool_call_probe(
            protocol,
            response,
            expected_tool_name=_TOOL_CAPABILITY_PROBE_NAME,
            api_key=api_key,
        )
        return assessment.observed, assessment.diagnostic

    def _probe_thinking_capability(
        self,
        provider: ProviderConfig,
        api_key: str,
    ) -> tuple[bool | None, str]:
        """Probe native thinking without exposing or accepting hidden reasoning text."""
        protocol = self._configured_protocol(provider)
        prompt = "Reply with exactly THINKING_OK and no other text."
        try:
            if protocol == "openai_responses":
                client = self._create_sync_client(provider, api_key)
                response = client.responses.create(
                    model=provider.model,
                    input=prompt,
                    reasoning={"effort": "low"},
                    temperature=0,
                    max_output_tokens=16,
                )
            elif protocol in {"openai_chat_completions", "openai_chat_completions_compatible"}:
                client = self._create_sync_client(provider, api_key)
                payload: dict[str, Any] = {
                    "model": provider.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 256 if _is_minimax_like_provider(provider) else 16,
                }
                if _is_minimax_like_provider(provider):
                    payload["extra_body"] = {"thinking": {"type": "enabled"}}
                else:
                    payload["reasoning_effort"] = "low"
                payload = self._apply_request_defaults(payload, provider)
                if _is_minimax_like_provider(provider):
                    extra_body = dict(payload.get("extra_body") or {})
                    extra_body["thinking"] = {"type": "enabled"}
                    payload["extra_body"] = extra_body
                response = client.chat.completions.create(**payload)
            elif protocol == "anthropic_messages":
                payload = self._apply_anthropic_native_probe_defaults({
                    "model": provider.model,
                    "max_tokens": 256,
                    "thinking": {"type": "enabled", "budget_tokens": 128},
                    "messages": [{"role": "user", "content": prompt}],
                }, provider)
                with self._direct_http_client(provider, timeout=60.0) as client:
                    response = client.post(
                        f"{self._anthropic_base_url(provider)}/v1/messages",
                        json=payload,
                        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    )
                if response.status_code >= 400:
                    return False, "Thinking probe was rejected by the provider."
                response = response.json()
            elif protocol == "gemini_generate_content":
                payload = self._apply_gemini_native_probe_defaults({
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": 16, "thinkingConfig": {"thinkingBudget": 128}},
                }, provider)
                with self._direct_http_client(provider, timeout=60.0) as client:
                    response = client.post(self._gemini_endpoint(provider), json=payload, headers={"x-goog-api-key": api_key, "content-type": "application/json"})
                if response.status_code >= 400:
                    return False, "Thinking probe was rejected by the provider."
                response = response.json()
            else:
                return None, "Thinking probe is unsupported for this provider protocol."
            assessment = normalize_provider_response(protocol, response, api_key=api_key)
        except Exception:  # noqa: BLE001 - capability probes must not leak upstream details.
            return None, "Thinking capability probe could not complete safely."
        if assessment.has_visible_text and assessment.content.strip() == "THINKING_OK":
            return True, "Thinking probe returned the expected visible token."
        if assessment.outcome in {"protocol_mismatch", "provider_error"}:
            return False, "Thinking probe was rejected by the provider."
        return None, "Thinking probe did not return a trustworthy visible result."

    def _probe_streaming_capability(
        self,
        provider: ProviderConfig,
        api_key: str,
    ) -> tuple[bool | None, str]:
        """Run one real incremental request and observe visible streamed output."""

        protocol = self._configured_protocol(provider)
        uses_default_stream = (
            getattr(self.chat_completion_stream, "__func__", None)
            is ProviderService.chat_completion_stream
        )
        if uses_default_stream and protocol in {
            "openai_chat_completions",
            "openai_chat_completions_compatible",
        }:
            client = None
            stream = None
            try:
                client = self._create_sync_client(provider, api_key)
                max_tokens = 256 if _needs_generous_visible_probe_budget(provider) else 16
                payload = self._apply_request_defaults(
                    {
                        "model": provider.model,
                        "messages": [
                            {"role": "user", "content": "Reply with one short visible word: OK."}
                        ],
                        "temperature": 0,
                        "max_tokens": max_tokens,
                        "stream": True,
                    },
                    provider,
                )
                if _is_minimax_like_provider(provider):
                    extra_body = dict(payload.get("extra_body") or {})
                    extra_body["thinking"] = {"type": "disabled"}
                    payload["extra_body"] = extra_body
                stream = client.chat.completions.create(**payload)
                reasoning_filter = _ReasoningBlockFilter()
                observed = False
                for chunk in stream:
                    choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
                    delta = getattr(choice, "delta", None)
                    content = getattr(delta, "content", None)
                    if isinstance(content, str) and reasoning_filter.push(content).strip():
                        observed = True
                if reasoning_filter.flush().strip():
                    observed = True
            except Exception:  # noqa: BLE001 - capability probes must not leak upstream details.
                return None, "Streaming capability probe could not complete safely."
            finally:
                if stream is not None:
                    close = getattr(stream, "close", None)
                    if close is not None:
                        close()
                if client is not None:
                    close_client = getattr(client, "close", None)
                    if close_client is not None:
                        close_client()
            if observed:
                return True, "Streaming probe returned visible incremental content."
            return False, "Streaming probe completed without visible incremental content."

        async def consume() -> bool:
            stream = self.chat_completion_stream(
                [{"role": "user", "content": "Reply with one short visible word: OK."}],
                model=provider.model,
                temperature=0,
                # Some reasoning-first providers consume a short output budget
                # before emitting their first visible token. Keep this probe
                # aligned with the other visible-token probes so a working
                # native stream is not reported as unavailable.
                max_tokens=256 if _needs_generous_visible_probe_budget(provider) else 16,
            )
            try:
                async for chunk in stream:
                    if isinstance(chunk, str) and chunk.strip():
                        return True
                return False
            finally:
                await stream.aclose()

        try:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                observed = asyncio.run(consume())
            else:
                # Provider tests are normally synchronous FastAPI handlers, but
                # keep the probe safe when called from an async test or host.
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    observed = pool.submit(asyncio.run, consume()).result()
        except Exception:  # noqa: BLE001 - capability probes must not leak upstream details.
            return None, "Streaming capability probe could not complete safely."
        if observed:
            return True, "Streaming probe returned visible incremental content."
        return False, "Streaming probe completed without visible incremental content."

    def _probe_embeddings_capability(
        self,
        provider: ProviderConfig,
        api_key: str,
    ) -> tuple[bool | None, str]:
        embedding_model = str(
            getattr(provider, "embedding_model", None) or getattr(provider, "model", "") or ""
        ).strip()
        if not embedding_model:
            return False, "Embeddings probe has no model to call."
        try:
            client = self._create_sync_client(provider, api_key)
            response = client.embeddings.create(model=embedding_model, input="ok")
        except Exception:  # noqa: BLE001 - capability probes must not leak upstream details.
            return None, "Embeddings capability probe could not complete safely."
        data = getattr(response, "data", None)
        if data is None and isinstance(response, dict):
            data = response.get("data")
        if not isinstance(data, list) or not data:
            return False, "Embeddings probe did not return embedding vectors."
        first = data[0]
        embedding = getattr(first, "embedding", None)
        if embedding is None and isinstance(first, dict):
            embedding = first.get("embedding")
        if (
            isinstance(embedding, list)
            and embedding
            and all(isinstance(item, (int, float)) for item in embedding[:8])
        ):
            return True, "Embeddings probe returned a numeric vector."
        return False, "Embeddings probe did not return embedding vectors."

    def _probe_structured_output_capability(
        self,
        provider: ProviderConfig,
        api_key: str,
    ) -> tuple[bool | None, str]:
        protocol = self._configured_protocol(provider)
        try:
            if protocol not in {
                "openai_chat_completions",
                "openai_chat_completions_compatible",
                "openai_responses",
            }:
                return None, "Structured output probe is unsupported for this provider protocol."
            client = self._create_sync_client(provider, api_key)
            if protocol == "openai_responses":
                response = client.responses.create(
                    model=provider.model,
                    input='Reply with JSON object {"ok": true} only.',
                    temperature=0,
                    max_output_tokens=32,
                    text={"format": {"type": "json_object"}},
                )
                content = str(getattr(response, "output_text", "") or "")
            else:
                payload: dict[str, Any] = {
                    "model": provider.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": 'Reply with JSON object {"ok": true} only.',
                        }
                    ],
                    "temperature": 0,
                    "max_tokens": 32,
                    "response_format": {"type": "json_object"},
                }
                payload = self._apply_request_defaults(payload, provider)
                response = client.chat.completions.create(**payload)
                message = response.choices[0].message if getattr(response, "choices", None) else None
                content = str(getattr(message, "content", "") or "")
        except Exception:  # noqa: BLE001 - capability probes must not leak upstream details.
            return None, "Structured output capability probe could not complete safely."
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            return False, "Structured output probe did not return parseable JSON."
        if isinstance(parsed, dict):
            return True, "Structured output probe returned JSON object content."
        return False, "Structured output probe did not return a JSON object."

    def _probe_model_listing_capability(
        self,
        provider: ProviderConfig,
        api_key: str,
    ) -> tuple[bool | None, str]:
        try:
            result = self.list_models(provider, api_key, skip_cache=True)
        except Exception:  # noqa: BLE001 - capability probes must not leak upstream details.
            return None, "Model listing capability probe could not complete safely."
        ids = [
            str(item).strip()
            for item in (result.available_models or [])
            if isinstance(item, str) and str(item).strip()
        ]
        if result.ok and result.listed and ids:
            return True, "Model listing returned live model ids."
        if result.error_category:
            return False, "Model listing was rejected by the provider."
        return False, "Model listing completed without usable model ids."

    @staticmethod
    def _retry_indeterminate_capability_probe(
        probe: Callable[[], tuple[bool | None, str]],
    ) -> tuple[bool | None, str]:
        """Retry one inconclusive capability probe without overriding a real negative."""

        observed, diagnostic = probe()
        if observed is not None:
            return observed, diagnostic

        retried_observed, retried_diagnostic = probe()
        if retried_observed is not None:
            return retried_observed, (
                f"{retried_diagnostic} The initial probe was inconclusive and was retried once."
            )
        return None, f"{retried_diagnostic} The capability remains unverified after one retry."

    def _with_capability_truth(
        self,
        result: ProviderTestResponse,
        provider: ProviderConfig,
        api_key: str | None,
    ) -> ProviderTestResponse:
        protocol = self._configured_protocol(provider)
        openai_chat_family = protocol in {
            "openai_chat_completions",
            "openai_chat_completions_compatible",
        }
        observations: dict[str, bool | None] = {}
        if result.ok:
            required_capability = provider_protocol_required_capability(protocol)
            if required_capability:
                observations[required_capability] = True

        tool_probe_diagnostic: str | None = None
        should_probe_tools = bool(provider.capabilities.tools) or openai_chat_family
        if should_probe_tools:
            if result.ok and api_key:
                observations["tools"], tool_probe_diagnostic = self._retry_indeterminate_capability_probe(
                    lambda: self._probe_tool_capability(provider, api_key)
                )
            else:
                tool_probe_diagnostic = (
                    "Tool-call capability was not probed because the base provider check did not complete."
                )

        stream_probe_diagnostic: str | None = None
        if provider.capabilities.streaming:
            if result.ok and api_key:
                observations["streaming"], stream_probe_diagnostic = (
                    self._retry_indeterminate_capability_probe(
                        lambda: self._probe_streaming_capability(provider, api_key)
                    )
                )
            else:
                stream_probe_diagnostic = (
                    "Streaming capability was not probed because the base provider check did not complete."
                )

        thinking_probe_diagnostic: str | None = None
        should_probe_thinking = bool(provider.capabilities.thinking) or (
            openai_chat_family and _is_minimax_like_provider(provider)
        )
        if should_probe_thinking:
            if result.ok and api_key:
                observations["thinking"], thinking_probe_diagnostic = (
                    self._retry_indeterminate_capability_probe(
                        lambda: self._probe_thinking_capability(provider, api_key)
                    )
                )
            else:
                thinking_probe_diagnostic = (
                    "Thinking capability was not probed because the base provider check did not complete."
                )

        vision_probe_diagnostic: str | None = None
        if provider.capabilities.vision:
            if result.ok and api_key:
                observations["vision"], vision_probe_diagnostic = (
                    self._retry_indeterminate_capability_probe(
                        lambda: self._probe_vision_capability(provider, api_key)
                    )
                )
            else:
                vision_probe_diagnostic = (
                    "Vision capability was not probed because the base provider check did not complete."
                )

        embeddings_probe_diagnostic: str | None = None
        if provider.capabilities.embeddings:
            if result.ok and api_key:
                observations["embeddings"], embeddings_probe_diagnostic = (
                    self._retry_indeterminate_capability_probe(
                        lambda: self._probe_embeddings_capability(provider, api_key)
                    )
                )
            else:
                embeddings_probe_diagnostic = (
                    "Embeddings capability was not probed because the base provider check did not complete."
                )

        structured_probe_diagnostic: str | None = None
        should_probe_structured = bool(
            provider.capabilities.structured_output or provider.capabilities.json_schema
        )
        if should_probe_structured:
            if result.ok and api_key:
                observations["structured_output"], structured_probe_diagnostic = (
                    self._retry_indeterminate_capability_probe(
                        lambda: self._probe_structured_output_capability(provider, api_key)
                    )
                )
                if provider.capabilities.json_schema:
                    observations["json_schema"] = observations.get("structured_output")
            else:
                structured_probe_diagnostic = (
                    "Structured output capability was not probed because the base provider check did not complete."
                )

        listing_probe_diagnostic: str | None = None
        if result.ok and api_key:
            observations["model_listing"], listing_probe_diagnostic = (
                self._retry_indeterminate_capability_probe(
                    lambda: self._probe_model_listing_capability(provider, api_key)
                )
            )
        elif api_key:
            listing_probe_diagnostic = (
                "Model listing capability was not probed because the base provider check did not complete."
            )

        assessment = assess_provider_capabilities(
            self._configured_protocol(provider),
            provider.capabilities,
            observations,
        )
        evidence = [
            ProviderCapabilityEvidence(
                name=item.name,
                declared=item.declared,
                observed=item.observed,
                state=item.state,
            )
            for item in assessment.evidence
        ]
        tools = assessment.for_capability("tools")
        diagnostics = list(result.diagnostics)
        if tool_probe_diagnostic:
            diagnostics.append(f"Tool capability {tools.state if tools else 'unverified'}. {tool_probe_diagnostic}")
        streaming = assessment.for_capability("streaming")
        if stream_probe_diagnostic:
            diagnostics.append(
                f"Streaming capability {streaming.state if streaming else 'unverified'}. "
                f"{stream_probe_diagnostic}"
            )
        thinking = assessment.for_capability("thinking")
        if thinking_probe_diagnostic:
            diagnostics.append(
                f"Thinking capability {thinking.state if thinking else 'unverified'}. "
                f"{thinking_probe_diagnostic}"
            )
        vision = assessment.for_capability("vision")
        if provider.capabilities.vision and vision_probe_diagnostic:
            diagnostics.append(
                f"Vision capability {vision.state if vision else 'unverified'}. "
                f"{vision_probe_diagnostic}"
            )
        embeddings = assessment.for_capability("embeddings")
        if embeddings_probe_diagnostic:
            diagnostics.append(
                f"Embeddings capability {embeddings.state if embeddings else 'unverified'}. "
                f"{embeddings_probe_diagnostic}"
            )
        structured = assessment.for_capability("structured_output")
        if structured_probe_diagnostic:
            diagnostics.append(
                f"Structured output capability {structured.state if structured else 'unverified'}. "
                f"{structured_probe_diagnostic}"
            )
        listing = assessment.for_capability("model_listing")
        if listing_probe_diagnostic:
            diagnostics.append(
                f"Model listing capability {listing.state if listing else 'unverified'}. "
                f"{listing_probe_diagnostic}"
            )
        if api_key and openai_chat_family and _should_fingerprint_gateway(provider):
            diagnostics.extend(self._gateway_fingerprint_diagnostics(provider, api_key))
        self._capability_truth = {item.name: item.state for item in evidence}
        return result.model_copy(
            update={
                "diagnostics": diagnostics,
                "capability_evidence": evidence,
                "tools_ready": bool(tools and tools.state == "verified"),
                "tool_probe_status": tools.state if tools else "unverified",
                "streaming_ready": bool(streaming and streaming.state == "verified"),
                "stream_probe_status": streaming.state if streaming else "unverified",
                "thinking_ready": bool(thinking and thinking.state == "verified"),
                "thinking_probe_status": thinking.state if thinking else "unverified",
                "vision_ready": bool(vision and vision.state == "verified"),
                "vision_probe_status": vision.state if vision else "unverified",
            }
        )

    def test(
        self,
        provider: ProviderConfig,
        api_key: str | None,
        *,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> ProviderTestResponse:
        result = self._test_connectivity(
            provider,
            api_key,
            probe_message=probe_message,
            response_language=response_language,
        )
        result = self._with_capability_truth(result, provider, api_key)
        protocol = self._configured_protocol(provider)
        return result.model_copy(
            update={
                "configured": bool(provider.name and provider.base_url and provider.model),
                "api_key_supplied": bool(api_key),
                "success": result.ok,
                "provider_name": provider.name or None,
                "base_url": provider.base_url or None,
                "model": provider.model or None,
                "protocol": protocol,
                "protocol_family": provider_protocol_family(protocol),
                "status": result.error_category or ("connected" if result.ok else "failed"),
            }
        )

    def _test_connectivity(
        self,
        provider: ProviderConfig,
        api_key: str | None,
        *,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> ProviderTestResponse:
        if not api_key:
            return ProviderTestResponse(
                ok=False,
                detail="Provider config is saved, but no API key is available. Trainer cannot work until you add one.",
                error_category="missing_api_key",
                retryable=False,
                diagnostics=["No API key supplied for provider test."],
                provider_reachable=False,
            )
        native_result = self._test_native_protocol(
            provider,
            api_key,
            probe_message,
            response_language,
        )
        if native_result is not None:
            return native_result
        try:
            client = self._create_sync_client(provider, api_key)
            try:
                chosen_model = None
                response = None
                compact_probe, visible_probe = self._native_probe_prompts(response_language)
                diagnostics = []
                hidden_reasoning_observed = False
                probe_max_tokens = _visible_probe_max_tokens(provider)
                if (
                    self._configured_protocol(provider) == "gemini_generate_content"
                    and not self._gemini_base_url_is_google_native(provider)
                ):
                    diagnostics.append(
                        "Using OpenAI-compatible chat probe for a Gemini-compatible non-Google gateway."
                    )
                for candidate in self._model_candidates(provider.model):
                    chosen_model = candidate
                    try:
                        request_payload = self._apply_request_defaults(
                            {
                                "model": candidate,
                                "messages": [
                                    {
                                        "role": "user",
                                        "content": compact_probe,
                                    }
                                ],
                                "temperature": 0,
                                "max_tokens": probe_max_tokens,
                            },
                            provider,
                        )
                        response = self._create_chat_completion_negotiated(
                            client, request_payload, provider
                        )
                        break
                    except Exception as chat_exc:
                        if not self._is_model_not_supported_error(chat_exc):
                            raise
                        response = None
                        continue

                if response is None:
                    raise Exception(
                        f"Not supported model {provider.model}. Tried: {', '.join(self._model_candidates(provider.model))}"
                    )
                latest_probe_response = response
                message = response.choices[0].message if response.choices else None
                content = message.content if message is not None else None
                hidden_reasoning_observed = _has_hidden_reasoning(message)
                preview = _visible_model_text(content)
                diagnostics.append(f"Chat probe succeeded with model {chosen_model or provider.model}.")
                if not preview:
                    for attempt in range(3):
                        if attempt > 0:
                            diagnostics.append(
                                f"Trainer retried the compact chat probe after blank visible text (attempt {attempt + 1})."
                            )
                            retry_probe_request = self._apply_request_defaults(
                                {
                                    "model": chosen_model or provider.model,
                                    "messages": [
                                        {
                                            "role": "user",
                                            "content": compact_probe,
                                        }
                                    ],
                                    "temperature": 0,
                                        "max_tokens": probe_max_tokens,
                                },
                                provider,
                            )
                            retry_probe_response = self._create_chat_completion_negotiated(
                                client, retry_probe_request, provider
                            )
                            latest_probe_response = retry_probe_response
                            retry_probe_message = (
                                retry_probe_response.choices[0].message
                                if retry_probe_response.choices
                                else None
                            )
                            retry_probe_content = (
                                retry_probe_message.content
                                if retry_probe_message is not None
                                else None
                            )
                            hidden_reasoning_observed = (
                                hidden_reasoning_observed
                                or _has_hidden_reasoning(retry_probe_message)
                            )
                            preview = _visible_model_text(retry_probe_content)
                            if preview:
                                break
                        diagnostics.append(
                            "Compact chat probe returned no visible text, so Trainer retried with a visible-text probe."
                        )
                        visible_probe_request = self._apply_request_defaults(
                            {
                                "model": chosen_model or provider.model,
                                "messages": [
                                        {
                                            "role": "user",
                                            "content": visible_probe,
                                        }
                                ],
                                "temperature": 0,
                                "max_tokens": probe_max_tokens,
                            },
                            provider,
                        )
                        visible_probe_response = self._create_chat_completion_negotiated(
                            client, visible_probe_request, provider
                        )
                        latest_probe_response = visible_probe_response
                        visible_probe_message = (
                            visible_probe_response.choices[0].message
                            if visible_probe_response.choices
                            else None
                        )
                        visible_probe_content = (
                            visible_probe_message.content
                            if visible_probe_message is not None
                            else None
                        )
                        hidden_reasoning_observed = (
                            hidden_reasoning_observed
                            or _has_hidden_reasoning(visible_probe_message)
                        )
                        preview = _visible_model_text(visible_probe_content)
                        if preview:
                            break
                        diagnostics.append("Visible-text probe also returned no usable text.")
                    if not preview:
                        reasoning_budget_exhausted = _reasoning_budget_exhausted(
                            latest_probe_response,
                            max_tokens=probe_max_tokens,
                        )
                        if hidden_reasoning_observed:
                            diagnostics.append(
                                "Chat probe returned hidden reasoning without visible text."
                            )
                        if reasoning_budget_exhausted and hidden_reasoning_observed:
                            diagnostics.append(
                                "Probe usage reported the entire output budget consumed, "
                                "so hidden reasoning exhausted it."
                            )
                            detail = self._detail_from_category(
                                "reasoning_budget_exhausted",
                                provider=provider,
                                response_language=response_language,
                            )
                        else:
                            detail = (
                                "Provider reachable, but the chat probe returned no usable visible reply "
                                f"for model {chosen_model or provider.model}."
                            )
                        return ProviderTestResponse(
                            ok=False,
                            detail=detail,
                            error_category=_unusable_visible_reply_category(
                                hidden_reasoning_observed=hidden_reasoning_observed,
                                reasoning_budget_exhausted=reasoning_budget_exhausted,
                            ),
                            retryable=True,
                            status_code=200,
                            diagnostics=diagnostics,
                            provider_reachable=True,
                            model_supported=True,
                            probeUsage=_probe_usage_payload(latest_probe_response),
                        )
                language_probe = self._language_probe_result_resilient(
                    client=client,
                    model=chosen_model or provider.model,
                    provider=provider,
                    probe_message=probe_message,
                    response_language=response_language,
                )
                if language_probe.get("ok") is False:
                    probe_category = str(
                        language_probe.get("category") or "language_probe_inconclusive"
                    ).strip() or "language_probe_inconclusive"
                    probe_detail = str(language_probe.get("detail") or "").strip()
                    probe_preview = str(language_probe.get("preview") or "").strip()
                    self.clear_language_integrity_success(
                        message=probe_message,
                        response_language=response_language,
                    )
                    diagnostics.append(f"Probe response preview: {preview}")
                    if probe_category == "language_corruption":
                        diagnostics.append(
                            "Language integrity probe failed: the mixed CJK/ASCII probe text was corrupted."
                        )
                    else:
                        diagnostics.append(
                            "Language integrity probe was inconclusive: the mixed CJK/ASCII probe text was not preserved clearly enough."
                        )
                    if probe_preview:
                        diagnostics.append(f"Language probe preview: {probe_preview}")
                    if (
                        probe_category == "language_probe_inconclusive"
                        and self._trusted_visible_probe_reply(preview)
                    ):
                        diagnostics.append(
                            "A trusted visible chat probe succeeded, so the inconclusive optional language check is not blocking this connection."
                        )
                        return ProviderTestResponse(
                            ok=True,
                            detail=_localized_text(
                                (
                                    "Provider reachable and the chat probe returned a usable visible reply. "
                                    "The optional zh-CN integrity check was inconclusive, so Trainer will keep "
                                    "checking future replies."
                                ),
                                (
                                    "provider 已连通，chat probe 返回了可用的可见回复。"
                                    "中文完整性补充检查没有得到确定结论，Trainer 会继续检查后续回复。"
                                ),
                                response_language,
                            ),
                            diagnostics=diagnostics,
                            provider_reachable=True,
                            model_supported=True,
                            probeUsage=_probe_usage_payload(latest_probe_response),
                        )
                    return ProviderTestResponse(
                        ok=False,
                        detail=probe_detail
                        or (
                            "Provider reachable, but Trainer could not fully verify zh-CN input integrity on this connection yet."
                            if probe_category == "language_probe_inconclusive"
                            else (
                                "Provider reachable, but it corrupted Chinese input into question marks "
                                "before the model saw it. Trainer cannot safely coach in zh-CN on this "
                                "connection yet."
                            )
                        ),
                        error_category=probe_category,
                        retryable=False,
                        status_code=200,
                        diagnostics=diagnostics,
                        provider_reachable=True,
                        model_supported=True,
                        probeUsage=_probe_usage_payload(latest_probe_response),
                    )
                diagnostics.append(f"Probe response preview: {preview}")
                probe_detail = str(language_probe.get("detail") or "").strip()
                if probe_detail:
                    diagnostics.append(probe_detail)
                self.mark_language_integrity_success(
                    message=probe_message,
                    response_language=response_language,
                )
                success_detail = (
                    probe_detail
                    if language_probe.get("kind") == "natural_language_fallback"
                    else (
                        "Provider reachable. Chat probe succeeded with model "
                        f"{chosen_model or provider.model}. Response: {preview}"
                    )
                )
                return ProviderTestResponse(
                    ok=True,
                    detail=success_detail,
                    diagnostics=diagnostics,
                    provider_reachable=True,
                    model_supported=True,
                    probeUsage=_probe_usage_payload(latest_probe_response),
                )
            except Exception as chat_exc:
                category, retryable, status_code, provider_reachable, model_supported = self._classify_error(chat_exc)
                if category in {"model_unsupported", "model_not_found"}:
                    return ProviderTestResponse(
                        ok=False,
                        detail=self._detail_from_category(category, provider=provider, error=chat_exc),
                        error_category=category,
                        retryable=retryable,
                        status_code=status_code,
                        diagnostics=[
                            f"Tried model candidates: {', '.join(self._model_candidates(provider.model))}",
                            redact_provider_error(chat_exc, api_key=api_key),
                        ],
                        provider_reachable=provider_reachable,
                        model_supported=model_supported,
                    )
                models_result = self.list_models(provider, api_key)
                count = len(models_result.available_models)
                if models_result.ok:
                    listing_detail = (
                        f"Provider reachable and listed {count} models, but the chat probe did not verify "
                        f"a usable reply for model {provider.model}."
                    )
                    if models_result.resolved_model:
                        listing_detail += f" The configured model resolves to {models_result.resolved_model}."
                    detail = (
                        listing_detail
                        if category == "unknown"
                        else self._detail_from_category(category, provider=provider, error=chat_exc)
                    )
                    diagnostics = [
                        "Chat probe failed; model listing does not prove the selected model is usable.",
                        listing_detail,
                        redact_provider_error(chat_exc, api_key=api_key),
                        *models_result.diagnostics,
                    ]
                else:
                    detail = self._detail_from_category(category, provider=provider, error=chat_exc)
                    diagnostics = [
                        "Chat probe failed.",
                        redact_provider_error(chat_exc, api_key=api_key),
                        *models_result.diagnostics,
                    ]
                return ProviderTestResponse(
                    ok=False,
                    detail=detail,
                    # A successful model list cannot erase a concrete chat failure;
                    # a failed list is a secondary probe, not the chat's status.
                    error_category="model_not_tested" if models_result.ok and category == "unknown" else category,
                    retryable=retryable,
                    status_code=status_code,
                    diagnostics=diagnostics,
                    provider_reachable=models_result.ok or provider_reachable,
                    model_supported=model_supported,
                )
        except Exception as exc:  # pragma: no cover - network dependent
            category, retryable, status_code, provider_reachable, model_supported = self._classify_error(exc)
            return ProviderTestResponse(
                ok=False,
                detail=self._detail_from_category(category, provider=provider, error=exc),
                error_category=category,
                retryable=retryable,
                status_code=status_code,
                diagnostics=[
                    "Provider test failed before any successful probe completed.",
                    redact_provider_error(exc, api_key=api_key),
                ],
                provider_reachable=provider_reachable,
                model_supported=model_supported,
            )

    async def coaching_reply(
        self,
        profile: UserProfile | None,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        self.clear_last_reply_state()
        if not self.has_api_key:
            if not profile:
                return self._missing_api_key_reply(response_language)
            return self._missing_api_key_reply_with_scaffold(
                profile,
                message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
        if not profile:
            return self._onboarding_reply(response_language)
        return await self._llm_reply(
            profile,
            message,
            current_file,
            response_language,
            answer_mode,
            coach_context=coach_context,
            history=history,
        )

    async def _llm_reply(
        self,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        messages = build_coaching_messages(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            history=history,
        )
        model = self._resolve_model()
        try:
            messages, max_tokens = self._prepare_context_budget(
                messages,
                model=model,
                prefer_configured_output=True,
            )
            if self._plain_completion_uses_agent_binding():
                content = await self._completion_via_agent_binding(
                    messages,
                    temperature=0.7,
                    max_tokens=max_tokens,
                    prefer_configured_output=True,
                    allow_local_empty_fallback=True,
                )
                return self.finalize_coaching_reply(
                    content or "",
                    profile=profile,
                    message=message,
                    current_file=current_file,
                    response_language=response_language,
                    answer_mode=answer_mode,
                    coach_context=coach_context,
                )
            client = self._get_client()
            response, _ = await self._create_chat_completion(
                client=client,
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=max_tokens,
            )
            content = _require_provider_runtime_response(
                "openai_chat_completions",
                response,
                api_key=self._api_key,
                allow_local_empty_fallback=True,
            )
            return self.finalize_coaching_reply(
                content or "",
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
        except ContextBudgetExhaustedError:
            self._record_last_reply_override(
                stop_reason="context_budget_exhausted",
                fell_back=False,
                context_budget_exhausted=True,
            )
            return self._context_budget_status_reply(response_language)
        except Exception as exc:
            category, retryable, status_code, provider_reachable, model_supported = self._classify_error(exc)
            provider_config = self._config or ProviderConfig(
                name="unspecified-provider",
                baseUrl="",
                apiKeyRef="trainer.unspecified",
                model=self._resolve_model(),
            )
            detail = self._detail_from_category(
                category,
                provider=provider_config,
                error=exc,
            )
            self._record_last_reply_failure(
                category=category,
                detail=detail,
                retryable=retryable,
                status_code=status_code,
                provider_reachable=provider_reachable,
                model_supported=model_supported,
                error=exc,
            )
            return self._error_reply_with_scaffold(
                exc=exc,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )

    def finalize_coaching_reply(
        self,
        content: str,
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        visible_content = _strip_internal_coach_meta(content)
        visible_content = _strip_leading_html_shell_artifact(visible_content)
        if not visible_content.strip():
            if _looks_like_provider_html_shell(content):
                detail = _malformed_provider_html_shell_detail()
                self._record_last_reply_failure(
                    category="malformed_response",
                    detail=detail,
                    retryable=False,
                    status_code=200,
                    provider_reachable=True,
                    model_supported=None,
                    error=ValueError(detail),
                )
                return self.provider_failure_reply(
                    "malformed_response",
                    detail,
                    response_language,
                )
            return self._fallback_empty_reply(
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
        reply = self._postprocess_coaching_reply(
            visible_content,
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        if _should_preserve_visible_reply(
            message,
            answer_mode=answer_mode,
            profile=profile,
        ):
            return _reanchor_visible_reply_to_current_request(
                reply,
                message=message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
        context = extract_coaching_context(message, current_file, coach_context)
        is_non_execution_intake = (
            str(context.get("relationship_stage") or "").strip().lower() == "intake"
            and not bool(context.get("execution_ready"))
        )
        if not is_non_execution_intake or not _reply_needs_first_turn_reframe(visible_content):
            return _reanchor_visible_reply_to_current_request(
                reply,
                message=message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
        reframed_reply = self._postprocess_first_turn_reply(
            reply,
            response_language=response_language,
            learner_message=message,
            scenario=str(context.get("scenario") or "").strip() or None,
            coach_context=context,
        )
        return _reanchor_visible_reply_to_current_request(
            reframed_reply,
            message=message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )

    def _postprocess_coaching_reply(
        self,
        content: str,
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        reply = content.strip()
        if not reply:
            return self._fallback_empty_reply(
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )

        raw_reply_corruption_detail = _mixed_script_reply_corruption_detail(
            reply,
            message=message,
            response_language=response_language,
        )
        if raw_reply_corruption_detail:
            self.clear_language_integrity_success(
                message=message,
                response_language=response_language,
            )
            self._record_reply_language_corruption(raw_reply_corruption_detail)
            recovery_override = _build_language_corruption_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(recovery_override, dict):
                reply_override = str(recovery_override.get("reply") or "").strip()
                if reply_override:
                    return reply_override
            return self.provider_failure_reply(
                "language_corruption",
                raw_reply_corruption_detail,
                response_language,
            )

        reply = _strip_short_cyrillic_noise(reply, message=message)
        reply_corruption_detail = _mixed_script_reply_corruption_detail(
            reply,
            message=message,
            response_language=response_language,
        )
        if reply_corruption_detail:
            self.clear_language_integrity_success(
                message=message,
                response_language=response_language,
            )
            self._record_reply_language_corruption(reply_corruption_detail)
            recovery_override = _build_language_corruption_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(recovery_override, dict):
                reply_override = str(recovery_override.get("reply") or "").strip()
                if reply_override:
                    return reply_override
            return self.provider_failure_reply(
                "language_corruption",
                reply_corruption_detail,
                response_language,
            )
        if _prefers_chinese(response_language):
            if _contains_cjk(reply):
                self.mark_language_integrity_success(
                    message=message,
                    response_language=response_language,
                )
        elif reply.strip() and not _wrong_language_cjk_reply_detail(
            reply,
            message=message,
            response_language=response_language,
        ):
            self.mark_language_integrity_success(
                message=message,
                response_language=response_language,
            )

        if _should_preserve_visible_reply(
            message,
            answer_mode=answer_mode,
            profile=profile,
        ):
            return _reanchor_visible_reply_to_current_request(
                reply,
                message=message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )

        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario") or "idea_implementation").strip()
        resolved_visible_scenario = _resolve_first_turn_guided_lane(
            scenario=scenario,
            learner_message=message,
            reply=reply,
        )
        if resolved_visible_scenario in _GUIDED_DOMAIN_SCENARIOS:
            scenario = resolved_visible_scenario
        history_mode = str(context.get("history_mode") or "").strip().lower()
        chinese = _prefers_chinese(response_language)
        learner_signal = str(
            context.get("learner_signal") or infer_learner_signal(message, current_file)
        ).strip()
        reply = _strip_generic_lane_prompt_artifacts(
            reply,
            scenario=scenario,
            learner_message=message,
            chinese=chinese,
        )
        should_strip_cross_lane = history_mode == "fresh_lane" or (
            scenario in _GUIDED_DOMAIN_SCENARIOS
            and not _fresh_lane_comparison_requested(message)
        )
        if should_strip_cross_lane:
            reply = _strip_fresh_lane_cross_lane_carryover(
                reply,
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
            )
            if (
                scenario in _GUIDED_DOMAIN_SCENARIOS
                and not _fresh_lane_comparison_requested(message)
                and _reply_mentions_other_guided_lane(
                reply,
                scenario=scenario,
                chinese=chinese,
                )
            ):
                repaired_reply = _fresh_lane_reanchor_reply(
                    scenario,
                    response_language=response_language,
                    coach_context=context,
                )
                if repaired_reply.strip():
                    reply = repaired_reply
        active_view = _coaching_active_view_name(context)
        active_view_override = (
            _build_active_view_recovery_override(
                active_view=active_view,
                response_language=response_language,
                reason="reanchor",
            )
            if active_view
            else None
        )
        if (
            isinstance(active_view_override, dict)
            and _structured_view_visible_reply_needs_repair(
                reply,
                active_view=active_view,
                chinese=chinese,
                learner_message=message,
                current_file=current_file,
            )
        ):
            repaired_reply = str(active_view_override.get("reply") or "").strip()
            if repaired_reply:
                return _reanchor_visible_reply_to_current_request(
                    repaired_reply,
                    message=message,
                    current_file=current_file,
                    coach_context=coach_context,
                    response_language=response_language,
                )
        pace_signal = str(context.get("pace_signal") or "").strip()

        implementation_guide = (
            context.get("implementation_guide") if isinstance(context.get("implementation_guide"), dict) else {}
        )
        adaptation_guide = (
            context.get("project_adaptation_guide")
            if isinstance(context.get("project_adaptation_guide"), dict)
            else context.get("adaptation_guide")
            if isinstance(context.get("adaptation_guide"), dict)
            else {}
        )
        principle_note = (
            context.get("principle_notes")
            if isinstance(context.get("principle_notes"), dict)
            else context.get("principle_note")
            if isinstance(context.get("principle_note"), dict)
            else {}
        )
        project_ideas = (
            [item for item in context.get("project_ideas", []) if isinstance(item, dict)]
            if isinstance(context.get("project_ideas"), list)
            else []
        )
        exercise_prompt = context.get("exercise_prompt") if isinstance(context.get("exercise_prompt"), dict) else {}
        failing_checks = [
            str(item).strip() for item in context.get("failing_checks", []) if str(item).strip()
        ] if isinstance(context.get("failing_checks"), list) else []
        project_entry_points = [
            str(item).strip() for item in context.get("project_entry_points", []) if str(item).strip()
        ] if isinstance(context.get("project_entry_points"), list) else []
        learning_outcomes = [
            item for item in context.get("learning_outcomes", []) if isinstance(item, dict)
        ] if isinstance(context.get("learning_outcomes"), list) else []
        recalled_coaching_memories = [
            item for item in context.get("recalled_coaching_memories", []) if isinstance(item, dict)
        ] if isinstance(context.get("recalled_coaching_memories"), list) else []

        has_structured_context = any(
            (
                current_file,
                implementation_guide,
                adaptation_guide,
                principle_note,
                project_ideas,
                exercise_prompt,
                failing_checks,
                project_entry_points,
                learning_outcomes,
                recalled_coaching_memories,
                pace_signal,
            )
        )
        if not has_structured_context:
            return reply

        additions: list[str] = []

        principle_patch = _compose_principle_followthrough_patch(
            reply=reply,
            principle_note=principle_note,
            chinese=chinese,
        )
        if principle_patch:
            additions.append(principle_patch)

        guided_lane_patch = _compose_guided_lane_continuity_patch(
            reply=reply,
            scenario=scenario,
            chinese=chinese,
        )
        if guided_lane_patch:
            additions.append(guided_lane_patch)

        # The next step no longer appends to the body: it reaches the learner
        # through the reply's icon strip (coach_turn.next_step / next_step_hint
        # metadata), so the text ends with the coach's own words.

        review_patch = _compose_review_tightening_patch(
            reply=reply,
            scenario=scenario,
            failing_checks=failing_checks,
            learning_outcomes=learning_outcomes,
            pace_signal=pace_signal,
            learner_signal=learner_signal,
            chinese=chinese,
        )
        if review_patch:
            additions.append(review_patch)

        success_signal_patch = _compose_success_signal_patch(
            reply=reply,
            exercise_prompt=exercise_prompt,
            chinese=chinese,
        )
        if success_signal_patch:
            additions.append(success_signal_patch)

        recalled_memory_patch = _compose_recalled_memory_patch(
            reply=reply,
            recalled_coaching_memories=recalled_coaching_memories,
            chinese=chinese,
        )
        if recalled_memory_patch:
            additions.append(recalled_memory_patch)

        if not additions:
            return reply
        return _append_unique_paragraphs(reply, additions[:3])

    def _sanitize_agentic_visible_reply(
        self,
        content: str,
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        reply = _strip_internal_coach_meta(content).strip()
        if not reply:
            return reply

        if _mixed_script_reply_corruption_detail(
            reply,
            message=message,
            response_language=response_language,
        ):
            return reply

        reply = _strip_short_cyrillic_noise(reply, message=message)
        if _mixed_script_reply_corruption_detail(
            reply,
            message=message,
            response_language=response_language,
        ):
            return reply

        if _should_preserve_visible_reply(
            message,
            answer_mode=answer_mode,
            profile=profile,
        ):
            return _reanchor_visible_reply_to_current_request(
                reply,
                message=message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )

        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario") or "idea_implementation").strip()
        resolved_visible_scenario = _resolve_first_turn_guided_lane(
            scenario=scenario,
            learner_message=message,
            reply=reply,
        )
        if resolved_visible_scenario in _GUIDED_DOMAIN_SCENARIOS:
            scenario = resolved_visible_scenario
        history_mode = str(context.get("history_mode") or "").strip().lower()
        chinese = _prefers_chinese(response_language)
        reply = _strip_generic_lane_prompt_artifacts(
            reply,
            scenario=scenario,
            learner_message=message,
            chinese=chinese,
        )
        should_strip_cross_lane = history_mode == "fresh_lane" or (
            scenario in _GUIDED_DOMAIN_SCENARIOS
            and not _fresh_lane_comparison_requested(message)
        )
        if should_strip_cross_lane:
            reply = _strip_fresh_lane_cross_lane_carryover(
                reply,
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
            )
            if (
                scenario in _GUIDED_DOMAIN_SCENARIOS
                and not _fresh_lane_comparison_requested(message)
                and _reply_mentions_other_guided_lane(
                reply,
                scenario=scenario,
                chinese=chinese,
                )
            ):
                repaired_reply = _fresh_lane_reanchor_reply(
                    scenario,
                    response_language=response_language,
                    coach_context=context,
                )
                if repaired_reply.strip():
                    reply = repaired_reply
        active_view = _coaching_active_view_name(context)
        active_view_override = (
            _build_active_view_recovery_override(
                active_view=active_view,
                response_language=response_language,
                reason="reanchor",
            )
            if active_view
            else None
        )
        if (
            isinstance(active_view_override, dict)
            and _structured_view_visible_reply_needs_repair(
                reply,
                active_view=active_view,
                chinese=chinese,
                learner_message=message,
                current_file=current_file,
            )
        ):
            repaired_reply = str(active_view_override.get("reply") or "").strip()
            if repaired_reply:
                return _reanchor_visible_reply_to_current_request(
                    repaired_reply,
                    message=message,
                    current_file=current_file,
                    coach_context=coach_context,
                    response_language=response_language,
                )
        return _reanchor_visible_reply_to_current_request(
            reply,
            message=message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )

    def _postprocess_first_turn_reply(
        self,
        reply: str,
        *,
        response_language: str | None = None,
        learner_message: str,
        scenario: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        chinese = _prefers_chinese(response_language)
        is_non_execution_intake = (
            isinstance(coach_context, dict)
            and str(coach_context.get("relationship_stage") or "").strip().lower() == "intake"
            and not bool(coach_context.get("execution_ready"))
        )
        condensed = ""
        if not (is_non_execution_intake and _reply_needs_first_turn_reframe(reply)):
            condensed = _compact_first_turn_reply(
                reply,
                chinese=chinese,
                scenario=scenario,
                learner_message=learner_message,
                coach_context=coach_context,
            )
        if condensed:
            return condensed

        learner_excerpt = learner_message.strip()
        guided_lane = _resolve_first_turn_guided_lane(
            scenario=scenario,
            learner_message=learner_message,
            reply=reply,
        )
        guided_note = _first_turn_lane_continuity_note(
            guided_lane,
            chinese=chinese,
            coach_context=coach_context,
        )
        guided_close = _first_turn_lane_next_step(
            guided_lane,
            chinese=chinese,
            coach_context=coach_context,
        )
        if guided_note and guided_close:
            if chinese:
                lead = "\u5148\u522b\u76f4\u63a5\u7ed9\u7b54\u6848\u3002\u5148\u5b9a\u4f4f\u8fd9\u4e00\u8f6e\u7684\u8d77\u6b65\u52a8\u4f5c\uff0c\u518d\u7ee7\u7eed\u3002"
                if learner_excerpt:
                    lead += f" \u4f60\u521a\u521a\u5e26\u6765\u7684\u91cd\u70b9\u662f\uff1a{_trim_sentence(learner_excerpt, 72)}\u3002"
                return f"{lead}\n\n{guided_note}\n\n{guided_close}"

            lead = (
                "I do not want to jump straight into a solution yet. "
                "First I want to anchor this round in one trustworthy starting move and keep the thread continuous."
            )
            if learner_excerpt:
                lead += f" What you just brought in is: {_trim_sentence(learner_excerpt, 72)}."
            return f"{lead}\n\n{guided_note}\n\n{guided_close}"
        if not _should_offer_generic_first_turn_lane_prompt(
            scenario=scenario,
            learner_message=learner_message,
            reply=reply,
        ):
            lead = "I do not want to jump straight into a solution yet. First I want to stay on the concrete task you already named."
            if chinese:
                lead = "\u5148\u522b\u76f4\u63a5\u7ed9\u7b54\u6848\u3002\u5148\u6cbf\u7740\u4f60\u521a\u624d\u5df2\u7ecf\u8bf4\u6e05\u695a\u7684\u5177\u4f53\u4efb\u52a1\u7ee7\u7eed\u5f80\u524d\u3002"
            if learner_excerpt:
                lead += (
                    f" \u4f60\u521a\u521a\u5e26\u6765\u7684\u91cd\u70b9\u662f\uff1a{_trim_sentence(learner_excerpt, 72)}\u3002"
                    if chinese
                    else f" What you just brought in is: {_trim_sentence(learner_excerpt, 72)}."
                )
            return f"{lead}\n\n{_first_turn_concrete_followthrough(chinese=chinese)}"
        if chinese:
            lead = "\u5148\u522b\u76f4\u63a5\u7ed9\u7b54\u6848\u3002\u5148\u5bf9\u9f50\u8fd9\u4e00\u8f6e\uff0c\u518d\u9009\u5408\u9002\u7684\u5f15\u5bfc\u65b9\u5f0f\u3002"
            if learner_excerpt:
                lead += f" \u4f60\u521a\u521a\u5e26\u6765\u7684\u91cd\u70b9\u662f\uff1a{_trim_sentence(learner_excerpt, 72)}\u3002"
            return (
                f"{lead}\n\n"
                "\u7b2c\u4e00\u8f6e\u901a\u5e38\u4f1a\u5148\u843d\u5230\u4e09\u6761\u8def\u5f84\u4e4b\u4e00\uff1a\u5b9e\u73b0\u4e00\u4e2a idea\u3001\u6539\u9020\u73b0\u6709\u9879\u76ee\uff0c\u6216\u5148\u5b9a\u8bad\u7ec3\u4e3b\u7ebf\u3002\n\n\u544a\u8bc9\u6211\u73b0\u5728\u66f4\u63a5\u8fd1\u54ea\u4e00\u6761\u3002"
            )

        lead = "I do not want to jump straight into a solution yet. First I want to align on this round and choose the right way to guide you."
        if learner_excerpt:
            lead += f" What you just brought in is: {_trim_sentence(learner_excerpt, 72)}."
        return (
            f"{lead}\n\n"
            "I usually sort the first turn into one of three lanes: turning an idea into code, guiding changes inside an existing project, or shaping the longer training thread and rhythm first. I will also remember the goal, project context, and coaching preference we make clear here so the next turn can continue the same thread.\n\n"
            "Tell me which lane is closest right now: implementing an idea, adapting an existing project, or shaping the training thread first."
        )

    def _scaffold_reply(
        self,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        chinese = _prefers_chinese(response_language)
        mode = normalize_answer_policy(answer_mode or profile.answer_policy)
        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario", "idea_implementation"))
        learner_signal = str(context.get("learner_signal", infer_learner_signal(message, current_file)))
        file_path = context.get("file_path")
        diagnostics_count = int(context.get("diagnostics_count", 0) or 0)
        current_focus = str(context.get("current_focus") or "").strip()
        recent_wins = [str(item) for item in context.get("recent_wins", []) if str(item).strip()]
        weak_spots = [str(item) for item in context.get("weak_spots", []) if str(item).strip()]
        due_reviews = context.get("due_reviews", [])
        review_rhythm = str(context.get("review_rhythm") or "").strip()
        teaching_observations = [
            str(item) for item in context.get("teaching_observations", []) if str(item).strip()
        ]
        coach_defaults = _as_mapping(context.get("coach_defaults")) or {}
        summary = str(context.get("thread_summary") or context.get("summary") or "").strip()
        next_step_hint = _extract_next_step_hint_text(
            context.get("thread_next_step") or context.get("resume_hint") or context.get("next_step_hint")
        )
        teaching_decision = _as_mapping(context.get("teaching_decision")) or {}
        tone_decision = _as_mapping(context.get("tone_decision")) or {}
        implementation_guide = (
            context.get("implementation_guide") if isinstance(context.get("implementation_guide"), dict) else {}
        )
        adaptation_guide = (
            context.get("project_adaptation_guide")
            if isinstance(context.get("project_adaptation_guide"), dict)
            else context.get("adaptation_guide")
            if isinstance(context.get("adaptation_guide"), dict)
            else {}
        )
        principle_note = (
            context.get("principle_notes")
            if isinstance(context.get("principle_notes"), dict)
            else context.get("principle_note")
            if isinstance(context.get("principle_note"), dict)
            else {}
        )
        project_ideas = [
            item for item in context.get("project_ideas", []) if isinstance(item, dict)
        ] if isinstance(context.get("project_ideas"), list) else []
        exercise_prompt = (
            context.get("exercise_prompt") if isinstance(context.get("exercise_prompt"), dict) else {}
        )
        verbosity_bias = str(tone_decision.get("verbosity_bias") or "medium").strip()
        tone_name = str(tone_decision.get("tone") or "").strip()

        goal_line = profile.long_term_goal or (profile.long_term_goals[0] if profile.long_term_goals else "")
        anchor = _scaffold_anchor(
            scenario=scenario,
            goal=goal_line,
            file_path=str(file_path) if file_path else None,
            current_focus=current_focus,
            chinese=chinese,
        )
        diagnosis = _scaffold_diagnosis(
            scenario=scenario,
            learner_signal=learner_signal,
            diagnostics_count=diagnostics_count,
            weak_spots=weak_spots,
            teaching_observations=teaching_observations,
            summary=summary,
            teaching_decision_reason=str(teaching_decision.get("reason") or "").strip(),
            chinese=chinese,
        )
        next_step = _scaffold_next_step(
            scenario=scenario,
            mode=mode,
            learner_signal=learner_signal,
            file_path=str(file_path) if file_path else None,
            weak_spots=weak_spots,
            next_step_hint=_prefer_structured_next_step(
                scenario=scenario,
                next_step_hint=next_step_hint,
                implementation_guide=implementation_guide,
                adaptation_guide=adaptation_guide,
                principle_note=principle_note,
                project_ideas=project_ideas,
                exercise_prompt=exercise_prompt,
            ),
            chinese=chinese,
        )
        teaching_note = _scaffold_teaching_note(
            scenario=scenario,
            mode=mode,
            recent_wins=recent_wins,
            weak_spots=weak_spots,
            due_reviews=due_reviews,
            review_rhythm=review_rhythm,
            coach_defaults=coach_defaults,
            tone_name=tone_name,
            verbosity_bias=verbosity_bias,
            chinese=chinese,
        )
        close = _scaffold_close(
            learner_signal=learner_signal,
            mode=mode,
            verbosity_bias=verbosity_bias,
            chinese=chinese,
        )

        paragraphs = _compose_scaffold_paragraphs(
            scenario=scenario,
            mode=mode,
            learner_signal=learner_signal,
            anchor=anchor,
            diagnosis=diagnosis,
            next_step=next_step,
            teaching_note=teaching_note,
            close=close,
            chinese=chinese,
        )
        resolved = [part for part in paragraphs if part.strip()]
        if verbosity_bias == "short":
            resolved = resolved[:3]
        return "\n\n".join(resolved)

    def _onboarding_reply(self, response_language: str | None = None) -> str:
        if _prefers_chinese(response_language):
            return (
                "先别急着直接上方案。先把你的目标、项目语境和当前卡点对齐。"
                "\n\n"
                "先告诉我最重要的几件事：你想达到的目标、手上的项目、当前水平、希望我怎样带你，以及最想推进或卡住的地方。"
                "\n\n"
                "我会记住这些判断，再决定这更适合从想法实现、已有项目改造、原理解释，还是一条可持续的训练主线开始。"
                "\n\n"
                "你现在更需要我带你做哪一类：实现一个想法、改造一个项目，还是先搭建训练主线？"
            )
        return (
            "Let's not jump straight into a solution yet. First I want to align on your goal, project context, and the coaching lane that fits you best."
            "\n\n"
            "Start with the few things that matter most right now: your goal, the project in front of you, your current level, "
            "how you prefer to be coached, and the point you most want to move forward or feel stuck on."
            "\n\n"
            "Then I can decide whether this should become an idea implementation discussion, an existing-project adaptation lane shaped around your intent, "
            "a principle explanation, or a training plan we shape together and keep over time."
            "\n\n"
            "If you want to keep it simple, answer just one thing first: do you mainly want to implement an idea, adapt a project, or shape the training thread?"
        )

    def _error_reply(self, exc: Exception, response_language: str | None = None) -> str:
        if _prefers_chinese(response_language):
            return (
                "这次连接教练服务时遇到了一点问题。请检查模型连接后再试。"
                "\n\n"
                "在恢复前，先把目标行为说清楚，找出当前最不确定的一点，再做一个能快速验证的小改动。"
            )
        return (
            "I hit an issue connecting to the coaching service. Please check your provider configuration and try again. "
            "While that is blocked, keep moving: restate the target behavior, identify the single highest-uncertainty point, "
            "and implement the smallest change you can verify quickly. "
            f"Error: {redact_provider_error(exc, api_key=self._api_key)}"
        )

    def _error_reply_with_scaffold(
        self,
        *,
        exc: Exception,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        error_line = self._error_reply(exc, response_language=response_language).strip()
        scaffold = self._scaffold_reply(
            profile,
            message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        ).strip()
        if not scaffold:
            return error_line
        return f"{error_line}\n\n{scaffold}"

    def _missing_api_key_reply(self, response_language: str | None = None) -> str:
        if _prefers_chinese(response_language):
            return "还没有设置可用的 API 密钥。请到设置里填写模型服务和密钥，然后就可以开始对话。"
        return "Trainer cannot start working yet because there is no usable API key. Save a large-model provider and API key in Settings, then I can properly start coaching."

    def _missing_api_key_reply_with_scaffold(
        self,
        profile: UserProfile,
        message: str,
        *,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        missing_key_line = self._missing_api_key_reply(response_language=response_language).strip()
        scaffold = self._scaffold_reply(
            profile,
            message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        ).strip()
        if not scaffold:
            return missing_key_line
        return f"{missing_key_line}\n\n{scaffold}"

    def _fallback_empty_reply(
        self,
        *,
        profile: UserProfile | None = None,
        message: str = "",
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        self._record_last_reply_override(
            **_build_empty_reply_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
        )
        return self._visible_empty_reply_guidance(
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        lead = _localized_text(
            "The provider finished this turn without any visible coaching reply, so I am keeping the same learning lane moving locally.",
            "",
            response_language,
        )
        guided_lane_reply = _guided_domain_empty_reply(
            message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if guided_lane_reply:
            return f"{lead}\n\n{guided_lane_reply}"

        if profile is not None:
            scaffold = self._scaffold_reply(
                profile,
                message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            ).strip()
            if scaffold:
                return f"{lead}\n\n{scaffold}"

        file_path = current_file.get("path") if current_file else None
        if file_path:
            return (
                f"I am still with you. Re-anchor on `{file_path}`, restate the target behavior, "
                "and tell me the one decision that feels most uncertain so we can reduce it to the next smallest verifiable step."
            )
        return (
            "I am still with you. Re-anchor on the target behavior and tell me the one decision that feels most uncertain "
            "so we can reduce it to the next smallest verifiable step."
        )

    def _visible_empty_reply_guidance(
        self,
        *,
        profile: UserProfile | None = None,
        message: str = "",
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        guided_lane_reply = _guided_domain_empty_reply(
            message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if guided_lane_reply:
            return guided_lane_reply

        if profile is not None:
            scaffold = self._scaffold_reply(
                profile,
                message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            ).strip()
            if scaffold:
                return scaffold

        file_path = current_file.get("path") if current_file else None
        if file_path:
            return _localized_text(
                f"I am still with you. Re-anchor on `{file_path}`, restate the target behavior, and tell me the one decision that feels most uncertain so we can reduce it to the next smallest verifiable step.",
                f"\u6211\u8fd8\u5728\u8ddf\u7740\u4f60\u3002\u5148\u56de\u5230 `{file_path}` \u8fd9\u6761\u94fe\u8def\uff0c\u91cd\u65b0\u786e\u8ba4\u76ee\u6807\u884c\u4e3a\uff0c\u7136\u540e\u544a\u8bc9\u6211\u4f60\u6700\u4e0d\u786e\u5b9a\u7684\u90a3\u4e00\u4e2a\u5224\u65ad\u70b9\uff0c\u6211\u4eec\u628a\u5b83\u538b\u7f29\u6210\u4e00\u4e2a\u6700\u5c0f\u53ef\u9a8c\u8bc1\u52a8\u4f5c\u3002",
                response_language,
            )
        return _localized_text(
            "I am still with you. Re-anchor on the target behavior and tell me the one decision that feels most uncertain so we can reduce it to the next smallest verifiable step.",
            "\u6211\u8fd8\u5728\u8ddf\u7740\u4f60\u3002\u5148\u91cd\u65b0\u786e\u8ba4\u76ee\u6807\u884c\u4e3a\uff0c\u518d\u544a\u8bc9\u6211\u4f60\u73b0\u5728\u6700\u4e0d\u786e\u5b9a\u7684\u4e00\u70b9\uff0c\u6211\u4eec\u628a\u5b83\u538b\u7f29\u6210\u4e00\u4e2a\u6700\u5c0f\u53ef\u9a8c\u8bc1\u52a8\u4f5c\u3002",
            response_language,
        )

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        if not self.has_api_key:
            raise RuntimeError(
                "API key not configured. Please set up your provider API key in settings."
            )
        model = self._resolve_model(model)
        try:
            if self._plain_completion_uses_agent_binding():
                return await self._completion_via_agent_binding(
                    messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            client = self._get_client()
            response, _ = await self._create_chat_completion(
                client=client,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return _require_provider_runtime_response(
                "openai_chat_completions",
                response,
                api_key=self._api_key,
            )
        except ContextBudgetExhaustedError as exc:
            raise RuntimeError(self._context_budget_status_reply(None)) from exc
        except Exception as exc:
            raise RuntimeError(redact_provider_error(exc, api_key=self._api_key)) from exc

    async def chat_completion_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        cancel_event: asyncio.Event | None = None,
    ):
        if not self.has_api_key:
            raise RuntimeError(
                "API key not configured. Please set up your provider API key in settings."
            )
        model = self._resolve_model(model)
        try:
            if self._plain_completion_uses_agent_binding():
                async for chunk in self._completion_stream_via_agent_binding(
                    messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                    cancel_event=cancel_event,
                ):
                    yield chunk
                return
            client = self._get_client()
            stream, _ = await _await_provider_stream_with_cancellation(
                self._create_chat_completion(
                    client=client,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                ),
                cancel_event,
            )
            reasoning_filter = _ReasoningBlockFilter()
            emitted_visible = False

            def _normalize_stream_chunk(text: str) -> str:
                nonlocal emitted_visible
                if emitted_visible:
                    return text
                trimmed = text.lstrip()
                if not trimmed:
                    return ""
                emitted_visible = True
                return trimmed

            raw_content = ""
            finish_reason: str | None = None
            async for chunk in _iterate_provider_stream_with_cancellation(stream, cancel_event):
                choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
                candidate_finish_reason = getattr(choice, "finish_reason", None)
                if isinstance(candidate_finish_reason, str) and candidate_finish_reason.strip():
                    finish_reason = candidate_finish_reason
                delta = getattr(choice, "delta", None)
                if delta is not None and getattr(delta, "content", None):
                    visible_chunk = _normalize_stream_chunk(
                        reasoning_filter.push(delta.content)
                    )
                    if visible_chunk:
                        raw_content += visible_chunk
                        yield visible_chunk
            tail = _normalize_stream_chunk(reasoning_filter.flush())
            if tail:
                raw_content += tail
                yield tail
            _require_provider_runtime_response(
                "openai_chat_completions",
                {
                    "choices": [
                        {
                            "message": {"content": raw_content},
                            "finish_reason": finish_reason,
                        }
                    ]
                },
                api_key=self._api_key,
            )
        except ContextBudgetExhaustedError as exc:
            raise RuntimeError(self._context_budget_status_reply(None)) from exc
        except Exception as exc:
            raise RuntimeError(redact_provider_error(exc, api_key=self._api_key)) from exc

    async def coaching_reply_stream(
        self,
        profile: UserProfile | None,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ):
        self.clear_last_reply_state()
        if not self.has_api_key:
            raise RuntimeError(
                "API key not configured. Please set up your provider API key in settings."
            )
        if not profile:
            yield self._onboarding_reply(response_language)
            return
        messages = build_coaching_messages(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            history=history,
        )
        model = self._resolve_model()
        try:
            messages, max_tokens = self._prepare_context_budget(
                messages,
                model=model,
                prefer_configured_output=True,
            )
            if self._plain_completion_uses_agent_binding():
                raw_content = ""
                async for chunk in self._completion_stream_via_agent_binding(
                    messages,
                    temperature=0.7,
                    max_tokens=max_tokens,
                    prefer_configured_output=True,
                    allow_local_empty_fallback=True,
                ):
                    raw_content += chunk
                    reply_corruption_detail = _mixed_script_reply_corruption_detail(
                        raw_content,
                        message=message,
                        response_language=response_language,
                    )
                    if reply_corruption_detail:
                        self._record_reply_language_corruption(reply_corruption_detail)
                        return
                reply_corruption_detail = _mixed_script_reply_corruption_detail(
                    raw_content,
                    message=message,
                    response_language=response_language,
                )
                if reply_corruption_detail:
                    self._record_reply_language_corruption(reply_corruption_detail)
                    return
                final_content = self.finalize_coaching_reply(
                    raw_content,
                    profile=profile,
                    message=message,
                    current_file=current_file,
                    response_language=response_language,
                    answer_mode=answer_mode,
                    coach_context=coach_context,
                )
                if final_content:
                    yield final_content
                return
            client = self._get_client()
            stream, _ = await _await_provider_stream_with_cancellation(
                self._create_chat_completion(
                    client=client,
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=max_tokens,
                    stream=True,
                ),
                cancel_event,
            )
            reasoning_filter = _ReasoningBlockFilter()
            emitted_visible = False

            def _normalize_stream_chunk(text: str) -> str:
                nonlocal emitted_visible
                if emitted_visible:
                    return text
                trimmed = text.lstrip()
                if not trimmed:
                    return ""
                emitted_visible = True
                return trimmed

            raw_content = ""
            finish_reason: str | None = None
            async for chunk in stream:
                choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
                candidate_finish_reason = getattr(choice, "finish_reason", None)
                if isinstance(candidate_finish_reason, str) and candidate_finish_reason.strip():
                    finish_reason = candidate_finish_reason
                delta = getattr(choice, "delta", None)
                if delta is not None and getattr(delta, "content", None):
                    text = _normalize_stream_chunk(
                        reasoning_filter.push(delta.content)
                    )
                    if not text:
                        continue
                    raw_content += text
                    reply_corruption_detail = _mixed_script_reply_corruption_detail(
                        raw_content,
                        message=message,
                        response_language=response_language,
                    )
                    if reply_corruption_detail:
                        self._record_reply_language_corruption(reply_corruption_detail)
                        return
            tail = _normalize_stream_chunk(reasoning_filter.flush())
            if tail:
                raw_content += tail
            reply_corruption_detail = _mixed_script_reply_corruption_detail(
                raw_content,
                message=message,
                response_language=response_language,
            )
            if reply_corruption_detail:
                self._record_reply_language_corruption(reply_corruption_detail)
                return
            _require_provider_runtime_response(
                "openai_chat_completions",
                {
                    "choices": [
                        {
                            "message": {"content": raw_content},
                            "finish_reason": finish_reason,
                        }
                    ]
                },
                api_key=self._api_key,
                allow_local_empty_fallback=True,
            )
            final_content = self.finalize_coaching_reply(
                raw_content,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
            if final_content:
                yield final_content
        except Exception as exc:
            category, retryable, status_code, provider_reachable, model_supported = self._classify_error(exc)
            provider_config = self._config or ProviderConfig(
                name="unspecified-provider",
                baseUrl="",
                apiKeyRef="trainer.unspecified",
                model=self._resolve_model(),
            )
            detail = self._detail_from_category(
                category,
                provider=provider_config,
                error=exc,
            )
            self._record_last_reply_failure(
                category=category,
                detail=detail,
                retryable=retryable,
                status_code=status_code,
                provider_reachable=provider_reachable,
                model_supported=model_supported,
                error=exc,
            )
            yield self._error_reply_with_scaffold(
                exc=exc,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )

    # ------------------------------------------------------------------
    # Agent-loop based coaching
    # ------------------------------------------------------------------

    def build_agent_provider(
        self,
        *,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        messages: list[dict[str, Any]] | None = None,
    ):
        """Return a (AgentProvider, binding) tuple for this provider instance.

        Imported lazily so the heavy ``agent_binding`` module is only loaded
        when an agent loop turn actually runs.
        """
        from .agent_binding import build_agent_provider_for

        if protocol is None and self._config is not None:
            protocol = getattr(self._config, "protocol", None)
        effective_max_tokens = self._effective_output_token_budget(
            messages or [],
            requested_max_tokens=max_tokens,
            prefer_configured_output=True,
        )
        provider_obj, binding = build_agent_provider_for(
            self,
            protocol=protocol,
            attachments=attachments,
            temperature=temperature,
            max_tokens=effective_max_tokens,
        )
        binding._max_tokens = effective_max_tokens  # noqa: SLF001 - request budget is set per call below
        original_call = provider_obj.call
        original_call_stream = provider_obj.call_stream
        context_budget_state: dict[str, ContextBudgetExhaustedError | None] = {"error": None}
        self._agent_context_budget_states[id(provider_obj)] = context_budget_state

        async def guarded_call(
            call_messages: list[dict[str, Any]],
            tools: list[dict[str, Any]] | None,
        ) -> dict[str, Any]:
            try:
                prepared_messages, call_max_tokens = self._prepare_context_budget(
                    call_messages,
                    requested_max_tokens=effective_max_tokens,
                    prefer_configured_output=True,
                )
            except ContextBudgetExhaustedError as exc:
                context_budget_state["error"] = exc
                return {"content": "", "tool_calls": []}
            previous_max_tokens = binding._max_tokens  # noqa: SLF001 - binding owns protocol payloads
            binding._max_tokens = call_max_tokens  # noqa: SLF001 - binding owns protocol payloads
            try:
                return await original_call(prepared_messages, tools)
            finally:
                binding._max_tokens = previous_max_tokens  # noqa: SLF001 - restore this binding for callers

        if original_call_stream is not None:

            async def guarded_call_stream(
                call_messages: list[dict[str, Any]],
                tools: list[dict[str, Any]] | None,
            ):
                try:
                    prepared_messages, call_max_tokens = self._prepare_context_budget(
                        call_messages,
                        requested_max_tokens=effective_max_tokens,
                        prefer_configured_output=True,
                    )
                except ContextBudgetExhaustedError as exc:
                    context_budget_state["error"] = exc
                    yield {
                        "type": "final",
                        "content": "",
                        "tool_calls": [],
                        "stop_reason": "context_budget_exhausted",
                    }
                    return
                previous_max_tokens = binding._max_tokens  # noqa: SLF001 - binding owns protocol payloads
                binding._max_tokens = call_max_tokens  # noqa: SLF001 - binding owns protocol payloads
                try:
                    async for event in original_call_stream(prepared_messages, tools):
                        # AgentLoop only forwards tool-capable text deltas when
                        # the binding has explicitly identified them as
                        # visible model output. Tool argument fragments remain
                        # untouched and are handled by the binding's final
                        # tool-call envelope.
                        if tools and str(event.get("type") or "") in {"delta", "text"}:
                            yield {**event, "safe_to_stream": True}
                        else:
                            yield event
                finally:
                    binding._max_tokens = previous_max_tokens  # noqa: SLF001 - restore this binding

            provider_obj.call_stream = guarded_call_stream

        provider_obj.call = guarded_call
        return provider_obj, binding

    def _build_agent_provider_with_budget(
        self,
        *,
        attachments: list[dict[str, Any]] | None,
        protocol: str | None,
        max_tokens: int,
        messages: list[dict[str, Any]],
    ):
        try:
            return self.build_agent_provider(
                attachments=attachments,
                protocol=protocol,
                max_tokens=max_tokens,
                messages=messages,
            )
        except TypeError as error:
            detail = str(error)
            if "unexpected keyword argument" not in detail or "max_tokens" not in detail:
                raise

        try:
            return self.build_agent_provider(
                attachments=attachments,
                protocol=protocol,
                messages=messages,
            )
        except TypeError as error:
            detail = str(error)
            if "unexpected keyword argument" not in detail or "messages" not in detail:
                raise

        return self.build_agent_provider(
            attachments=attachments,
            protocol=protocol,
        )

    async def coaching_reply_agentic(
        self,
        profile: UserProfile | None,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        max_steps: int | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Drive the coach agent loop and return a structured outcome.

        On any agent error, the result falls back to ``coaching_reply``'s
        text output so callers always have something to show. The dict
        shape is::

            {
              "content": str,           # final assistant text
              "steps": [...],           # AgentStep dicts (best-effort)
              "summary": str | None,
              "next_step": str | None,
              "stop_reason": str,
              "tool_events": [...],     # tool_call+tool_result pairs
              "fell_back": bool,
            }
        """
        self.clear_last_reply_state()
        attachment_delivery = self.describe_attachment_delivery(
            attachments=attachments,
            protocol=protocol,
            use_agent_loop=True,
        )
        provider_attachments = (
            list(attachments or [])
            if bool(attachment_delivery.get("attachments_delivered_to_model"))
            else None
        )
        if not self.has_api_key:
            return {
                "content": self._missing_api_key_reply(response_language),
                "steps": [],
                "summary": None,
                "next_step": None,
                "stop_reason": "missing_api_key",
                "tool_events": [],
                "fell_back": True,
                **attachment_delivery,
            }
        if not profile:
            return {
                "content": self._onboarding_reply(response_language),
                "steps": [],
                "summary": None,
                "next_step": None,
                "stop_reason": "onboarding",
                "tool_events": [],
                "fell_back": True,
                **attachment_delivery,
            }
        from .agent_loop import CoachAgentLoop
        from .tools import ToolContext, build_default_tool_registry

        messages = build_coaching_messages(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            agent_loop_enabled=True,
            history=history,
        )
        try:
            messages, max_tokens = self._prepare_context_budget(
                messages,
                prefer_configured_output=True,
            )
        except ContextBudgetExhaustedError:
            return self._context_budget_agentic_result(
                response_language=response_language,
                attachment_delivery=attachment_delivery,
            )
        provider_obj, binding = self._build_agent_provider_with_budget(
            attachments=provider_attachments,
            protocol=protocol,
            max_tokens=max_tokens,
            messages=messages,
        )
        registry = build_default_tool_registry()
        runtime_obj = (coach_context or {}).get("__runtime__") if coach_context else None
        workspace_id = str((coach_context or {}).get("workspace_id") or "workspace-default")
        session_id = str((coach_context or {}).get("session_id") or "")
        context = ToolContext(
            runtime=runtime_obj,
            workspace_id=workspace_id,
            session_id=session_id or None,
            profile=profile,
            response_language=response_language,
            extra=_build_agent_tool_context_extra(
                coach_context=coach_context,
                attachment_delivery=attachment_delivery,
                answer_mode=answer_mode or profile.answer_policy,
                current_file=current_file,
                provider_config=self._config,
                learner_message=message,
            ),
        )
        loop = CoachAgentLoop(
            provider=provider_obj,
            registry=registry,
            context=context,
            max_steps=_agent_loop_max_steps(coach_context, max_steps),
            **self._agent_loop_timeout_kwargs(),
        )
        try:
            result = await loop.run(messages)
        except ContextBudgetExhaustedError:
            return self._context_budget_agentic_result(
                response_language=response_language,
                attachment_delivery=attachment_delivery,
            )
        except Exception as exc:
            fallback = await self._llm_reply(
                profile,
                message,
                current_file,
                response_language,
                answer_mode,
                coach_context=coach_context,
                history=history,
            )
            fallback_summary, fallback_next_step = _agentic_fallback_continuity(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            fallback_resume_thread = _agentic_resume_thread_text(
                fallback_summary,
                fallback_next_step,
                response_language=response_language,
            )
            return {
                "content": fallback,
                "steps": [],
                "summary": fallback_summary,
                "next_step": fallback_next_step,
                "stop_reason": f"agent_error: {exc.__class__.__name__}",
                "resume_thread": fallback_resume_thread,
                "tool_events": [],
                "fell_back": True,
                **attachment_delivery,
            }
        if self._agent_provider_context_budget_exhausted(provider_obj):
            return self._context_budget_agentic_result(
                response_language=response_language,
                attachment_delivery=attachment_delivery,
            )
        fell_back = False
        recovered_stop_reason: str | None = None
        tool_events = _agent_tool_events(result)
        grounded_resource_evidence = _agentic_has_grounded_resource_evidence(tool_events)
        # When the model never produced text (e.g. only tool calls then max_steps)
        # surface a short scaffold so the bubble isn't empty.
        final_text = _agent_result_visible_text(result)
        if not final_text.strip() and result.stop_reason == "empty_response":
            if not tool_events:
                self.clear_last_reply_state()
                plain_reply = await self._llm_reply(
                    profile,
                    message,
                    current_file,
                    response_language,
                    answer_mode,
                    coach_context=coach_context,
                    history=history,
                )
                plain_failure = self.consume_last_reply_failure()
                plain_override = self.consume_last_reply_override()
                plain_stop_reason = (
                    str(plain_override.get("stop_reason") or "").strip()
                    if isinstance(plain_override, dict)
                    else ""
                )
                if (
                    plain_reply.strip()
                    and plain_failure is None
                    and plain_stop_reason != "empty_response"
                ):
                    final_text = plain_reply
                    result.stop_reason = "completed"
                    result.summary = None
                    result.next_step = None
                    result.resume_thread = None
            if not final_text.strip():
                guided_recovery = _guided_domain_empty_reply_override(
                    message,
                    current_file=current_file,
                    coach_context=coach_context,
                    response_language=response_language,
                )
                final_text = self._visible_empty_reply_guidance(
                    profile=profile,
                    message=message,
                    current_file=current_file,
                    response_language=response_language,
                    answer_mode=answer_mode,
                    coach_context=coach_context,
                )
                if isinstance(guided_recovery, dict) and final_text.strip():
                    recovered_stop_reason = "empty_response"
                    result.stop_reason = "completed"
                    result.summary = guided_recovery.get("summary") or result.summary
                    result.next_step = guided_recovery.get("next_step") or result.next_step
                    result.teaching_note = (
                        guided_recovery.get("teaching_note")
                        or getattr(result, "teaching_note", None)
                    )
                    result.resume_thread = _agentic_resume_thread_text(
                        result.summary,
                        result.next_step,
                        response_language=response_language,
                    )
        recoverable_grounded_stop_reason = (
            _agentic_recoverable_grounded_stop_reason(result.stop_reason)
            if grounded_resource_evidence
            else ""
        )
        if recoverable_grounded_stop_reason:
            self.clear_last_reply_state()
            plain_reply = await self._llm_reply(
                profile,
                message,
                current_file,
                response_language,
                answer_mode,
                coach_context=coach_context,
                history=history,
            )
            plain_failure = self.consume_last_reply_failure()
            plain_override = self.consume_last_reply_override()
            plain_stop_reason = (
                str(plain_override.get("stop_reason") or "").strip()
                if isinstance(plain_override, dict)
                else ""
            )
            if (
                plain_reply.strip()
                and plain_failure is None
                and plain_stop_reason not in {"empty_response", "max_steps", "no_progress"}
            ):
                final_text = plain_reply
                result.stop_reason = "completed"
                result.summary = None
                result.next_step = None
                result.resume_thread = None
                recovered_stop_reason = recoverable_grounded_stop_reason
                fell_back = True
        if str(result.stop_reason or "").strip() == "timeout":
            timeout_recovery = _build_timeout_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(timeout_recovery, dict):
                result.summary = _optional_text(timeout_recovery.get("summary")) or result.summary
                result.next_step = _optional_text(timeout_recovery.get("next_step")) or result.next_step
                result.teaching_note = _optional_text(timeout_recovery.get("teaching_note")) or result.teaching_note
                result.resume_thread = _optional_text(timeout_recovery.get("resume_thread")) or _agentic_resume_thread_text(
                    result.summary,
                    result.next_step,
                    response_language=response_language,
                )
                timeout_reply = str(timeout_recovery.get("reply") or "").strip()
                if timeout_reply:
                    final_text = timeout_reply
                fell_back = True
        if str(result.stop_reason or "").strip() == "provider_error":
            provider_error_recovery = _build_provider_error_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
                error_detail=getattr(result, "error", None),
            )
            result.summary = _optional_text(provider_error_recovery.get("summary")) or result.summary
            result.next_step = _optional_text(provider_error_recovery.get("next_step")) or result.next_step
            result.teaching_note = _optional_text(provider_error_recovery.get("teaching_note")) or result.teaching_note
            result.resume_thread = _optional_text(provider_error_recovery.get("resume_thread")) or _agentic_resume_thread_text(
                result.summary,
                result.next_step,
                response_language=response_language,
            )
            provider_error_reply = str(provider_error_recovery.get("reply") or "").strip()
            if provider_error_reply:
                final_text = provider_error_reply
            fell_back = True
        if not final_text.strip() and result.stop_reason == "coach_finalize":
            self.clear_last_reply_state()
            try:
                plain_reply = await self._llm_reply(
                    profile,
                    message,
                    current_file,
                    response_language,
                    answer_mode,
                    coach_context=coach_context,
                    history=history,
                )
            except Exception:
                plain_reply = ""
            plain_failure = self.consume_last_reply_failure()
            plain_override = self.consume_last_reply_override()
            plain_stop_reason = (
                str(plain_override.get("stop_reason") or "").strip()
                if isinstance(plain_override, dict)
                else ""
            )
            if (
                plain_reply.strip()
                and plain_failure is None
                and plain_stop_reason != "empty_response"
            ):
                final_text = plain_reply
                result.stop_reason = "completed"
        if not final_text.strip():
            final_text = self._scaffold_reply(
                profile,
                message,
                current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
        final_text = self._sanitize_agentic_visible_reply(
            final_text,
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        reply_corruption_detail = _mixed_script_reply_corruption_detail(
            final_text,
            message=message,
            response_language=response_language,
        )
        if reply_corruption_detail:
            self._record_reply_language_corruption(reply_corruption_detail)
            recovery_override = _build_language_corruption_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(recovery_override, dict):
                result.summary = str(recovery_override.get("summary") or "").strip() or (
                    self.provider_failure_summary("language_corruption", response_language)
                )
                result.next_step = str(recovery_override.get("next_step") or "").strip() or (
                    self.provider_failure_next_step("language_corruption", response_language)
                )
                result.teaching_note = str(recovery_override.get("teaching_note") or "").strip()
                result.blocker = reply_corruption_detail
                result.stop_reason = "language_corruption_recovered"
                result.resume_thread = str(recovery_override.get("resume_thread") or "").strip() or (
                    _agentic_resume_thread_text(
                        result.summary,
                        result.next_step,
                        response_language=response_language,
                    )
                )
                final_text = str(recovery_override.get("reply") or "").strip() or self.provider_failure_reply(
                    "language_corruption",
                    reply_corruption_detail,
                    response_language,
                )
                fell_back = True
            else:
                result.summary = self.provider_failure_summary(
                    "language_corruption",
                    response_language,
                )
                result.next_step = self.provider_failure_next_step(
                    "language_corruption",
                    response_language,
                )
                result.stop_reason = "language_corruption"
                result.resume_thread = _agentic_resume_thread_text(
                    result.summary,
                    result.next_step,
                    response_language=response_language,
                )
                final_text = self.provider_failure_reply(
                    "language_corruption",
                    reply_corruption_detail,
                    response_language,
                )
        tool_events.extend(
            await _maybe_auto_verify_practice_current_file(
                registry=registry,
                context=context,
                tool_events=tool_events,
                message=message,
                content=final_text,
                current_file=current_file,
                coach_context=coach_context,
            )
        )
        guard = _agentic_practice_completion_guard(
            content=final_text,
            tool_events=tool_events,
            message=message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if guard is not None:
            final_text = guard["content"]
            result.summary = guard["summary"]
            result.next_step = guard["next_step"]
            result.stop_reason = guard["stop_reason"]
        else:
            summary, next_step = _agentic_completion_continuity(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
                content=final_text,
            )
            if not str(result.summary or "").strip():
                result.summary = summary
            if not str(result.next_step or "").strip():
                result.next_step = next_step
        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario") or "").strip()
        history_mode = str(context.get("history_mode") or "").strip().lower()
        chinese = _prefers_chinese(response_language)
        summary_before_visible = str(result.summary or "").strip()
        next_step_before_visible = str(result.next_step or "").strip()
        if str(result.summary or "").strip():
            result.summary = _sanitize_agentic_continuity_text(
                str(result.summary or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="summary",
                response_language=response_language,
                coach_context=context,
                current_file=current_file,
            )
        if str(result.next_step or "").strip():
            result.next_step = _sanitize_agentic_continuity_text(
                str(result.next_step or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="next_step",
                response_language=response_language,
                coach_context=context,
                current_file=current_file,
            )
        summary_changed_for_visible = str(result.summary or "").strip() != summary_before_visible
        next_step_changed_for_visible = str(result.next_step or "").strip() != next_step_before_visible
        if (
            not str(getattr(result, "resume_thread", "") or "").strip()
            or summary_changed_for_visible
            or next_step_changed_for_visible
        ):
            result.resume_thread = _agentic_resume_thread_text(
                result.summary,
                result.next_step,
                response_language=response_language,
            )
        if str(getattr(result, "resume_thread", "") or "").strip():
            sanitized_resume_thread = _sanitize_agentic_continuity_text(
                str(getattr(result, "resume_thread", "") or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="resume_thread",
                response_language=response_language,
                coach_context=context,
                current_file=current_file,
            )
            if summary_changed_for_visible or next_step_changed_for_visible:
                result.resume_thread = _normalize_visible_resume_thread_text(
                    sanitized_resume_thread,
                    chinese=chinese,
                )
            else:
                result.resume_thread = sanitized_resume_thread
        return {
            "content": final_text,
            "steps": [self._step_to_dict(step) for step in result.steps],
            "summary": result.summary,
            "next_step": result.next_step,
            "stop_reason": result.stop_reason,
            "decision": getattr(result, "decision", None),
            "blocker": getattr(result, "blocker", None),
            "teaching_note": getattr(result, "teaching_note", None),
            "resume_thread": getattr(result, "resume_thread", None),
            "confidence": getattr(result, "confidence", None),
            "evidence": getattr(result, "evidence", None),
            "tool_events": tool_events,
            "fell_back": fell_back,
            "recovered_stop_reason": recovered_stop_reason,
            **attachment_delivery,
        }

    async def coaching_reply_agentic_stream(
        self,
        profile: UserProfile | None,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        max_steps: int | None = None,
        history: list[dict[str, str]] | None = None,
    ):
        """Yield typed agent events for the stream transport.

        Text is held until the final response has passed the same integrity
        checks as a non-streaming reply. Tool progress remains live.
        """
        attachment_delivery = self.describe_attachment_delivery(
            attachments=attachments,
            protocol=protocol,
            use_agent_loop=True,
        )
        provider_attachments = (
            list(attachments or [])
            if bool(attachment_delivery.get("attachments_delivered_to_model"))
            else None
        )
        if not self.has_api_key:
            yield {
                "type": "final",
                "content": self._missing_api_key_reply(response_language),
                "summary": None,
                "next_step": None,
                "stop_reason": "missing_api_key",
                **attachment_delivery,
            }
            return
        if not profile:
            yield {
                "type": "final",
                "content": self._onboarding_reply(response_language),
                "summary": None,
                "next_step": None,
                "stop_reason": "onboarding",
                **attachment_delivery,
            }
            return
        from .agent_loop import CoachAgentLoop
        from .tools import ToolContext, build_default_tool_registry

        messages = build_coaching_messages(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            agent_loop_enabled=True,
            history=history,
        )
        try:
            messages, max_tokens = self._prepare_context_budget(
                messages,
                prefer_configured_output=True,
            )
        except ContextBudgetExhaustedError:
            yield {
                "type": "final",
                "content": self._context_budget_status_reply(response_language),
                "summary": None,
                "next_step": None,
                "stop_reason": "context_budget_exhausted",
                "fell_back": False,
                **attachment_delivery,
            }
            return
        provider_obj, binding = self._build_agent_provider_with_budget(
            attachments=provider_attachments,
            protocol=protocol,
            max_tokens=max_tokens,
            messages=messages,
        )
        registry = build_default_tool_registry()
        runtime_obj = (coach_context or {}).get("__runtime__") if coach_context else None
        workspace_id = str((coach_context or {}).get("workspace_id") or "workspace-default")
        session_id = str((coach_context or {}).get("session_id") or "")
        context = ToolContext(
            runtime=runtime_obj,
            workspace_id=workspace_id,
            session_id=session_id or None,
            profile=profile,
            response_language=response_language,
            extra=_build_agent_tool_context_extra(
                coach_context=coach_context,
                attachment_delivery=attachment_delivery,
                answer_mode=answer_mode or profile.answer_policy,
                current_file=current_file,
                provider_config=self._config,
                learner_message=message,
            ),
        )
        loop = CoachAgentLoop(
            provider=provider_obj,
            registry=registry,
            context=context,
            max_steps=_agent_loop_max_steps(coach_context, max_steps),
            **self._agent_loop_timeout_kwargs(),
        )
        try:
            native_stream_available = provider_obj.call_stream is not None
            if not native_stream_available:
                # A stream endpoint must never silently downgrade to a buffered
                # completion. Callers can retry after choosing a stream-capable
                # provider and the UI can keep the lane explicitly blocked.
                detail = (
                    "The configured provider does not expose native streaming; "
                    "Trainer cannot continue this streaming action."
                )
                summary = self.provider_failure_summary(
                    "streaming_unavailable",
                    response_language,
                )
                next_step = self.provider_failure_next_step(
                    "streaming_unavailable",
                    response_language,
                )
                yield {
                    "type": "error",
                    "detail": detail,
                    "category": "streaming_unavailable",
                    "recoverable": True,
                    "terminal": True,
                    "degraded": False,
                }
                yield {
                    "type": "final",
                    "content": self.provider_failure_reply(
                        "streaming_unavailable",
                        detail,
                        response_language,
                    ),
                    "summary": summary,
                    "next_step": next_step,
                    "resume_thread": _agentic_resume_thread_text(
                        summary,
                        next_step,
                        response_language=response_language,
                    ),
                    "stop_reason": "streaming_unavailable",
                    "fell_back": False,
                    "recoverable": True,
                    **attachment_delivery,
                }
                return
            buffered_text = ""
            streamed_visible_text = ""
            tool_events: list[dict[str, Any]] = []
            holdback_chars = _stream_holdback_chars(response_language)

            def safe_direct_reply_prefix() -> str:
                if (
                    not native_stream_available
                    or tool_events
                    or current_file
                    or not _should_preserve_visible_reply(
                        message,
                        answer_mode=answer_mode,
                        profile=profile,
                    )
                ):
                    return ""
                visible = _strip_internal_coach_meta(buffered_text)
                if (
                    not visible
                    or visible != _visible_model_text(buffered_text).strip()
                    or _mixed_script_reply_corruption_detail(
                        visible,
                        message=message,
                        response_language=response_language,
                    )
                    or _strip_short_cyrillic_noise(visible, message=message) != visible
                    or len(visible) <= holdback_chars
                ):
                    return ""
                available = visible[:-holdback_chars]
                if not available.startswith(streamed_visible_text):
                    return ""
                return available[len(streamed_visible_text) :]

            async for event in loop.run_stream(messages):
                if self._agent_provider_context_budget_exhausted(provider_obj):
                    yield {
                        "type": "final",
                        "content": self._context_budget_status_reply(response_language),
                        "summary": None,
                        "next_step": None,
                        "stop_reason": "context_budget_exhausted",
                        "fell_back": False,
                        **attachment_delivery,
                    }
                    return
                event_type = str(event.get("type") or "")
                if event_type == "tool_call" or event_type == "tool_result":
                    tool_events.append(dict(event))
                if event_type == "text":
                    delta = str(event.get("delta") or "")
                    buffered_text += delta
                    if event.get("safe_to_stream") is True:
                        # Native tool-capable streams can expose visible model
                        # text before the tool decision arrives. Keep the
                        # guardrails that strip internal metadata and reject
                        # mixed-script corruption, but do not wait for the
                        # complete tool loop before forwarding a valid prefix.
                        visible = _strip_internal_coach_meta(buffered_text)
                        if (
                            visible == _visible_model_text(buffered_text).strip()
                            and _strip_short_cyrillic_noise(visible, message=message) == visible
                            and not _mixed_script_reply_corruption_detail(
                                visible,
                                message=message,
                                response_language=response_language,
                            )
                            and visible.startswith(streamed_visible_text)
                        ):
                            safe_delta = visible[len(streamed_visible_text) :]
                            if safe_delta:
                                streamed_visible_text = visible
                                yield {
                                    "type": "text",
                                    "delta": safe_delta,
                                    "safe_to_stream": True,
                                }
                        continue
                    safe_delta = safe_direct_reply_prefix()
                    if safe_delta:
                        streamed_visible_text += safe_delta
                        yield {
                            "type": "text",
                            "delta": safe_delta,
                            "safe_to_stream": True,
                        }
                    continue
                if event_type == "final":
                    if not str(event.get("content") or "").strip():
                        event = {**event, "content": buffered_text}
                    event = await self._recover_agentic_stream_final_event(
                        event,
                        profile=profile,
                        message=message,
                        current_file=current_file,
                        response_language=response_language,
                        answer_mode=answer_mode,
                        coach_context=coach_context,
                        history=history,
                        tool_events=tool_events,
                    )
                    auto_events = await _maybe_auto_verify_practice_current_file(
                        registry=registry,
                        context=context,
                        tool_events=tool_events,
                        message=message,
                        content=str(event.get("content") or ""),
                        current_file=current_file,
                        coach_context=coach_context,
                    )
                    for auto_event in auto_events:
                        tool_events.append(auto_event)
                        yield auto_event
                    event = self._visible_agentic_final_event(
                        event,
                        profile=profile,
                        message=message,
                        current_file=current_file,
                        response_language=response_language,
                        answer_mode=answer_mode,
                        coach_context=coach_context,
                        tool_events=tool_events,
                    )
                elif event_type == "error":
                    # AgentLoop emits a recovery final after provider errors.
                    # Mark this frame explicitly so SSE consumers do not
                    # mistake it for a terminal stream failure.
                    event = {
                        **event,
                        "recoverable": event.get("recoverable", True),
                        "terminal": event.get("terminal", False),
                        "degraded": event.get("degraded", True),
                    }
                yield event
        except ContextBudgetExhaustedError:
            yield {
                "type": "final",
                "content": self._context_budget_status_reply(response_language),
                "summary": None,
                "next_step": None,
                "stop_reason": "context_budget_exhausted",
                "fell_back": False,
                **attachment_delivery,
            }
        except Exception as exc:
            scaffold = self._error_reply_with_scaffold(
                exc=exc,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
            fallback_summary, fallback_next_step = _agentic_fallback_continuity(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            fallback_resume_thread = _agentic_resume_thread_text(
                fallback_summary,
                fallback_next_step,
                response_language=response_language,
            )
            yield {
                "type": "error",
                "detail": redact_provider_error(exc, api_key=self._api_key),
                "category": exc.__class__.__name__,
                "recoverable": True,
                "terminal": False,
                "degraded": True,
            }
            yield {
                "type": "final",
                "content": scaffold,
                "summary": fallback_summary,
                "next_step": fallback_next_step,
                "resume_thread": fallback_resume_thread,
                "stop_reason": "agent_error",
                **attachment_delivery,
            }

    async def _recover_agentic_stream_final_event(
        self,
        event: dict[str, Any],
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None,
        response_language: str | None,
        answer_mode: str | None,
        coach_context: dict[str, Any] | None,
        history: list[dict[str, str]] | None,
        tool_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        final_event = dict(event)
        content = _strip_internal_coach_meta(str(final_event.get("content") or ""))
        final_event["content"] = content
        stop_reason = str(final_event.get("stop_reason") or "").strip()
        grounded_resource_evidence = _agentic_has_grounded_resource_evidence(tool_events)
        needs_empty_response_recovery = not content.strip() and stop_reason == "empty_response"
        needs_finalize_visible_reply_recovery = (
            not content.strip() and stop_reason == "coach_finalize"
        )
        needs_timeout_recovery = stop_reason == "timeout"
        needs_provider_error_recovery = stop_reason == "provider_error"
        recoverable_grounded_stop_reason = (
            _agentic_recoverable_grounded_stop_reason(stop_reason)
            if grounded_resource_evidence
            else ""
        )
        needs_grounded_stop_recovery = bool(recoverable_grounded_stop_reason)
        if (
            not needs_empty_response_recovery
            and not needs_finalize_visible_reply_recovery
            and not needs_grounded_stop_recovery
            and not needs_timeout_recovery
            and not needs_provider_error_recovery
        ):
            return final_event
        if needs_timeout_recovery:
            timeout_recovery = _build_timeout_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(timeout_recovery, dict):
                final_event["content"] = str(timeout_recovery.get("reply") or content).strip()
                final_event["summary"] = timeout_recovery.get("summary")
                final_event["next_step"] = timeout_recovery.get("next_step")
                final_event["teaching_note"] = timeout_recovery.get("teaching_note")
                final_event["resume_thread"] = timeout_recovery.get("resume_thread")
                final_event["fell_back"] = True
            return final_event
        if needs_provider_error_recovery:
            provider_error_recovery = _build_provider_error_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
                error_detail=str(final_event.get("error") or "").strip() or None,
            )
            final_event["content"] = str(provider_error_recovery.get("reply") or content).strip()
            final_event["summary"] = provider_error_recovery.get("summary")
            final_event["next_step"] = provider_error_recovery.get("next_step")
            final_event["teaching_note"] = provider_error_recovery.get("teaching_note")
            final_event["resume_thread"] = provider_error_recovery.get("resume_thread")
            final_event["fell_back"] = True
            return final_event
        if needs_empty_response_recovery and tool_events:
            return final_event

        self.clear_last_reply_state()
        plain_reply = await self._llm_reply(
            profile,
            message,
            current_file,
            response_language,
            answer_mode,
            coach_context=coach_context,
            history=history,
        )
        plain_failure = self.consume_last_reply_failure()
        plain_override = self.consume_last_reply_override()
        plain_stop_reason = (
            str(plain_override.get("stop_reason") or "").strip()
            if isinstance(plain_override, dict)
            else ""
        )
        if (
            plain_reply.strip()
            and plain_failure is None
            and plain_stop_reason not in {"empty_response", "max_steps", "no_progress"}
        ):
            final_event["content"] = plain_reply
            final_event["stop_reason"] = "completed"
            final_event["summary"] = None
            final_event["next_step"] = None
            final_event["resume_thread"] = None
            if needs_grounded_stop_recovery:
                final_event["recovered_stop_reason"] = recoverable_grounded_stop_reason
                final_event["fell_back"] = True
            return final_event
        if needs_grounded_stop_recovery:
            return final_event
        guided_recovery = _guided_domain_empty_reply_override(
            message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if isinstance(guided_recovery, dict):
            guided_reply = _guided_domain_empty_reply(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if guided_reply.strip():
                summary = guided_recovery.get("summary") or final_event.get("summary")
                next_step = guided_recovery.get("next_step") or final_event.get("next_step")
                final_event["content"] = guided_reply
                final_event["stop_reason"] = "completed"
                final_event["recovered_stop_reason"] = (
                    "coach_finalize"
                    if needs_finalize_visible_reply_recovery
                    else "empty_response"
                )
                final_event["summary"] = summary
                final_event["next_step"] = next_step
                final_event["teaching_note"] = guided_recovery.get("teaching_note")
                final_event["resume_thread"] = _agentic_resume_thread_text(
                    str(summary or "").strip(),
                    str(next_step or "").strip(),
                    response_language=response_language,
                )
        return final_event

    @staticmethod
    def _step_to_dict(step: Any) -> dict[str, Any]:
        return {
            "index": getattr(step, "index", -1),
            "assistant_content": getattr(step, "assistant_content", ""),
            "tool_calls": list(getattr(step, "tool_calls", []) or []),
            "tool_results": list(getattr(step, "tool_results", []) or []),
            "stop_reason": getattr(step, "stop_reason", None),
        }

    def _visible_agentic_final_event(
        self,
        event: dict[str, Any],
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None,
        response_language: str | None,
        answer_mode: str | None,
        coach_context: dict[str, Any] | None,
        tool_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        final_event = dict(event)
        content = self._sanitize_agentic_visible_reply(
            str(final_event.get("content") or ""),
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        final_event["content"] = content
        if str(final_event.get("summary") or "").strip():
            final_event["summary"] = _strip_internal_coach_meta(str(final_event.get("summary") or ""))
        if str(final_event.get("next_step") or "").strip():
            final_event["next_step"] = _strip_internal_coach_meta(str(final_event.get("next_step") or ""))
        if str(final_event.get("resume_thread") or "").strip():
            final_event["resume_thread"] = _visible_model_text(
                str(final_event.get("resume_thread") or "")
            )
        reply_corruption_detail = _mixed_script_reply_corruption_detail(
            content,
            message=message,
            response_language=response_language,
        )
        if reply_corruption_detail:
            self._record_reply_language_corruption(reply_corruption_detail)
            recovery_override = _build_language_corruption_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(recovery_override, dict):
                summary = str(recovery_override.get("summary") or "").strip() or (
                    self.provider_failure_summary("language_corruption", response_language)
                )
                next_step = str(recovery_override.get("next_step") or "").strip() or (
                    self.provider_failure_next_step("language_corruption", response_language)
                )
                final_event.update(
                    {
                        "content": str(recovery_override.get("reply") or "").strip()
                        or self.provider_failure_reply(
                            "language_corruption",
                            reply_corruption_detail,
                            response_language,
                        ),
                        "summary": summary,
                        "next_step": next_step,
                        "stop_reason": "language_corruption_recovered",
                        "teaching_note": str(recovery_override.get("teaching_note") or "").strip(),
                        "blocker": reply_corruption_detail,
                        "resume_thread": str(recovery_override.get("resume_thread") or "").strip()
                        or _agentic_resume_thread_text(
                            summary,
                            next_step,
                            response_language=response_language,
                        ),
                        "fell_back": True,
                    }
                )
            else:
                summary = self.provider_failure_summary("language_corruption", response_language)
                next_step = self.provider_failure_next_step("language_corruption", response_language)
                final_event.update(
                    {
                        "content": self.provider_failure_reply(
                            "language_corruption",
                            reply_corruption_detail,
                            response_language,
                        ),
                        "summary": summary,
                        "next_step": next_step,
                        "stop_reason": "language_corruption",
                        "resume_thread": _agentic_resume_thread_text(
                            summary,
                            next_step,
                            response_language=response_language,
                        ),
                    }
                )
            return final_event
        guard = _agentic_practice_completion_guard(
            content=content,
            tool_events=tool_events or [],
            message=message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if guard is not None:
            final_event.update(guard)
            resume_thread = _agentic_resume_thread_text(
                final_event.get("summary"),
                final_event.get("next_step"),
                response_language=response_language,
            )
            if resume_thread:
                final_event["resume_thread"] = resume_thread
            return final_event

        summary, next_step = _agentic_completion_continuity(
            message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
            content=content,
        )
        if not str(final_event.get("summary") or "").strip():
            final_event["summary"] = _strip_internal_coach_meta(summary)
        if not str(final_event.get("next_step") or "").strip():
            final_event["next_step"] = _strip_internal_coach_meta(next_step)
        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario") or "").strip()
        history_mode = str(context.get("history_mode") or "").strip().lower()
        chinese = _prefers_chinese(response_language)
        summary_before_visible = str(final_event.get("summary") or "").strip()
        next_step_before_visible = str(final_event.get("next_step") or "").strip()
        if str(final_event.get("summary") or "").strip():
            final_event["summary"] = _sanitize_agentic_continuity_text(
                str(final_event.get("summary") or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="summary",
                response_language=response_language,
                coach_context=context,
                current_file=current_file,
            )
        if str(final_event.get("next_step") or "").strip():
            final_event["next_step"] = _sanitize_agentic_continuity_text(
                str(final_event.get("next_step") or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="next_step",
                response_language=response_language,
                coach_context=context,
                current_file=current_file,
            )
        summary_changed_for_visible = (
            str(final_event.get("summary") or "").strip() != summary_before_visible
        )
        next_step_changed_for_visible = (
            str(final_event.get("next_step") or "").strip() != next_step_before_visible
        )
        if (
            not str(final_event.get("resume_thread") or "").strip()
            or summary_changed_for_visible
            or next_step_changed_for_visible
        ):
            final_event["resume_thread"] = _agentic_resume_thread_text(
                final_event.get("summary"),
                final_event.get("next_step"),
                response_language=response_language,
            )
        if str(final_event.get("resume_thread") or "").strip():
            sanitized_resume_thread = _sanitize_agentic_continuity_text(
                str(final_event.get("resume_thread") or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="resume_thread",
                response_language=response_language,
                coach_context=context,
                current_file=current_file,
            )
            if summary_changed_for_visible or next_step_changed_for_visible:
                final_event["resume_thread"] = _normalize_visible_resume_thread_text(
                    sanitized_resume_thread,
                    chinese=chinese,
                )
            else:
                final_event["resume_thread"] = sanitized_resume_thread

        if content.strip():
            return final_event

        summary_text = str(final_event.get("summary") or "").strip()
        if summary_text:
            final_event["content"] = summary_text
            return final_event

        final_event["content"] = self._scaffold_reply(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        return final_event


def _has_passed_current_file_practice_verification(tool_events: list[dict[str, Any]]) -> bool:
    result = _current_file_practice_verification_result(tool_events)
    return isinstance(result, dict) and result.get("passed") is True


def _compose_guided_lane_continuity_patch(
    *,
    reply: str,
    scenario: str,
    chinese: bool,
) -> str:
    guided_lane = _first_turn_guided_lane(scenario, "")
    if guided_lane not in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return ""
    if _reply_has_guided_lane_signal(reply, guided_lane, chinese):
        return ""
    return _first_turn_lane_continuity_note(guided_lane, chinese=chinese)


def _reply_mentions_other_guided_lane(reply: str, *, scenario: str, chinese: bool) -> bool:
    if not reply.strip() or scenario not in _GUIDED_DOMAIN_SCENARIOS:
        return False
    lowered = reply.casefold()
    lane_markers = _fresh_lane_marker_map(chinese=chinese)
    other_lane_markers = [
        marker
        for lane, markers in lane_markers.items()
        if lane != scenario
        for marker in markers
    ]
    return any(marker.casefold() in lowered for marker in other_lane_markers)


async def _provider_service_coaching_reply_stream(
    self,
    profile: UserProfile | None,
    message: str,
    current_file: dict[str, object] | None = None,
    response_language: str | None = None,
    answer_mode: str | None = None,
    coach_context: dict[str, Any] | None = None,
    history: list[dict[str, str]] | None = None,
    cancel_event: asyncio.Event | None = None,
):
    self.clear_last_reply_state()
    cancel_event = cancel_event or _stream_cancel_event(
        coach_context.get("stream_cancel_event") if isinstance(coach_context, dict) else None
    )
    if not self.has_api_key:
        if not profile:
            yield self._missing_api_key_reply(response_language)
            return
        yield self._missing_api_key_reply_with_scaffold(
            profile,
            message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        return
    if not profile:
        yield self._onboarding_reply(response_language)
        return

    messages = build_coaching_messages(
        profile,
        message,
        current_file,
        response_language=response_language,
        answer_mode=answer_mode,
        coach_context=coach_context,
        history=history,
    )
    model = self._resolve_model()
    try:
        messages, max_tokens = self._prepare_context_budget(
            messages,
            model=model,
            prefer_configured_output=True,
        )
        if self._plain_completion_uses_agent_binding():
            raw_content = ""
            pending_visible = ""
            yielded_visible = False
            holdback_chars = _stream_holdback_chars(response_language)
            async for chunk in self._completion_stream_via_agent_binding(
                messages,
                temperature=0.7,
                max_tokens=max_tokens,
                prefer_configured_output=True,
                allow_local_empty_fallback=True,
                cancel_event=cancel_event,
            ):
                raw_content += chunk
                pending_visible += chunk
                reply_corruption_detail = _mixed_script_reply_corruption_detail(
                    raw_content,
                    message=message,
                    response_language=response_language,
                )
                if reply_corruption_detail:
                    self._record_reply_language_corruption(reply_corruption_detail)
                    if not yielded_visible:
                        recovery_override = _build_language_corruption_recovery_override(
                            message,
                            current_file=current_file,
                            coach_context=coach_context,
                            response_language=response_language,
                        )
                        if isinstance(recovery_override, dict):
                            reply_override = str(recovery_override.get("reply") or "").strip()
                            if reply_override:
                                yield reply_override
                    return
                if len(pending_visible) > holdback_chars:
                    safe_prefix = pending_visible[:-holdback_chars]
                    pending_visible = pending_visible[-holdback_chars:]
                    if safe_prefix:
                        yielded_visible = True
                        yield safe_prefix
            reply_corruption_detail = _mixed_script_reply_corruption_detail(
                raw_content,
                message=message,
                response_language=response_language,
            )
            if reply_corruption_detail:
                self._record_reply_language_corruption(reply_corruption_detail)
                if not yielded_visible:
                    recovery_override = _build_language_corruption_recovery_override(
                        message,
                        current_file=current_file,
                        coach_context=coach_context,
                        response_language=response_language,
                    )
                    if isinstance(recovery_override, dict):
                        reply_override = str(recovery_override.get("reply") or "").strip()
                        if reply_override:
                            yield reply_override
                return
            if pending_visible:
                yielded_visible = True
                yield pending_visible
            final_content = self.finalize_coaching_reply(
                raw_content,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
            self._record_stream_finalization(raw_content, final_content)
            if not raw_content and final_content:
                yield final_content
                return
            if final_content.startswith(raw_content) and final_content != raw_content:
                yield final_content[len(raw_content) :]
            return
        client = self._get_client()
        stream, _ = await _await_provider_stream_with_cancellation(
            self._create_chat_completion(
                client=client,
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=max_tokens,
                stream=True,
            ),
            cancel_event,
        )
        reasoning_filter = _ReasoningBlockFilter()
        emitted_visible = False
        yielded_visible = False

        def _normalize_stream_chunk(text: str) -> str:
            nonlocal emitted_visible
            if emitted_visible:
                return text
            trimmed = text.lstrip()
            if not trimmed:
                return ""
            emitted_visible = True
            return trimmed

        raw_content = ""
        pending_visible = ""
        holdback_chars = _stream_holdback_chars(response_language)
        finish_reason: str | None = None
        async for chunk in _iterate_provider_stream_with_cancellation(stream, cancel_event):
            choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
            candidate_finish_reason = getattr(choice, "finish_reason", None)
            if isinstance(candidate_finish_reason, str) and candidate_finish_reason.strip():
                finish_reason = candidate_finish_reason
            delta = getattr(choice, "delta", None)
            if delta is not None and getattr(delta, "content", None):
                text = _normalize_stream_chunk(reasoning_filter.push(delta.content))
                if not text:
                    continue
                raw_content += text
                pending_visible += text
                reply_corruption_detail = _mixed_script_reply_corruption_detail(
                    raw_content,
                    message=message,
                    response_language=response_language,
                )
                if reply_corruption_detail:
                    self._record_reply_language_corruption(reply_corruption_detail)
                    if not yielded_visible:
                        recovery_override = _build_language_corruption_recovery_override(
                            message,
                            current_file=current_file,
                            coach_context=coach_context,
                            response_language=response_language,
                        )
                        if isinstance(recovery_override, dict):
                            reply_override = str(recovery_override.get("reply") or "").strip()
                            if reply_override:
                                yield reply_override
                    return
                if len(pending_visible) > holdback_chars:
                    safe_prefix = pending_visible[:-holdback_chars]
                    pending_visible = pending_visible[-holdback_chars:]
                    if safe_prefix:
                        yielded_visible = True
                        yield safe_prefix
        tail = _normalize_stream_chunk(reasoning_filter.flush())
        if tail:
            raw_content += tail
            pending_visible += tail
        reply_corruption_detail = _mixed_script_reply_corruption_detail(
            raw_content,
            message=message,
            response_language=response_language,
        )
        if reply_corruption_detail:
            self._record_reply_language_corruption(reply_corruption_detail)
            if not yielded_visible:
                recovery_override = _build_language_corruption_recovery_override(
                    message,
                    current_file=current_file,
                    coach_context=coach_context,
                    response_language=response_language,
                )
                if isinstance(recovery_override, dict):
                    reply_override = str(recovery_override.get("reply") or "").strip()
                    if reply_override:
                        yield reply_override
            return
        _require_provider_runtime_response(
            "openai_chat_completions",
            {
                "choices": [
                    {
                        "message": {"content": raw_content},
                        "finish_reason": finish_reason,
                    }
                ]
            },
            api_key=self._api_key,
            allow_local_empty_fallback=True,
        )
        if pending_visible:
            yielded_visible = True
            yield pending_visible
        final_content = self.finalize_coaching_reply(
            raw_content,
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        self._record_stream_finalization(raw_content, final_content)
        if not raw_content and final_content:
            yield final_content
            return
        if final_content.startswith(raw_content) and final_content != raw_content:
            yield final_content[len(raw_content) :]
    except ContextBudgetExhaustedError:
        self._record_last_reply_override(
            stop_reason="context_budget_exhausted",
            fell_back=False,
            context_budget_exhausted=True,
        )
        yield self._context_budget_status_reply(response_language)
    except Exception as exc:
        category, retryable, status_code, provider_reachable, model_supported = self._classify_error(exc)
        provider_config = self._config or ProviderConfig(
            name="unspecified-provider",
            baseUrl="",
            apiKeyRef="trainer.unspecified",
            model=self._resolve_model(),
        )
        detail = self._detail_from_category(
            category,
            provider=provider_config,
            error=exc,
        )
        self._record_last_reply_failure(
            category=category,
            detail=detail,
            retryable=retryable,
            status_code=status_code,
            provider_reachable=provider_reachable,
            model_supported=model_supported,
            error=exc,
        )
        yield self._error_reply_with_scaffold(
            exc=exc,
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )


_GENERAL_TIMEOUT_CODE_MARKERS = (
    "vs code",
    "vscode",
    "debug",
    "remote",
    "function",
    "call site",
    "stack trace",
    "traceback",
    "workspace",
    "repo",
    "repository",
    "api",
    "json",
    "typescript",
    "javascript",
    "python",
    "java",
    "rust",
    "golang",
    "sql",
    "git",
    "patch",
    "refactor",
    "bug",
    "launch.json",
    ".py",
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
)


ProviderService._onboarding_reply = _provider_service_onboarding_reply
ProviderService._error_reply = _provider_service_error_reply
ProviderService._missing_api_key_reply = _provider_service_missing_api_key_reply
ProviderService.coaching_reply_stream = _provider_service_coaching_reply_stream


ProviderService._onboarding_reply = _clean_provider_service_onboarding_reply
ProviderService._error_reply = _clean_provider_service_error_reply
ProviderService._missing_api_key_reply = _clean_provider_service_missing_api_key_reply
ProviderService.provider_failure_summary = _clean_provider_failure_summary
ProviderService.provider_failure_next_step = _clean_provider_failure_next_step
ProviderService.provider_failure_reply = _clean_provider_failure_reply


def _safe_provider_service_error_reply(
    self,
    exc: Exception,
    response_language: str | None = None,
) -> str:
    if _prefers_chinese(response_language):
        return "这次没能连上模型服务。请在设置里检查服务地址、模型和 API 密钥后再试一次。"
    return (
        "I could not reach the model service for this reply. Check the provider address, model, and API key in Settings, then try again."
    )


ProviderService._error_reply = _safe_provider_service_error_reply
