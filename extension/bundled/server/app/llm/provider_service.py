from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import socket
from contextvars import ContextVar
from importlib import import_module
from time import monotonic
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import quote, urlsplit

import httpx

from ..core.models import (
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderModelsResponse,
    ProviderModelTokenLimit,
    ProviderProtocol,
    ProviderTestResponse,
    UserProfile,
)
from ..training.subject_taxonomy import classify_learning_subject
from .prompts import (
    _format_due_review_item,
    _truncate_coaching_history_content,
    build_coaching_messages,
    extract_coaching_context,
    infer_coaching_scenario,
    infer_learner_signal,
    normalize_answer_policy,
)
from .provider_gateway import (
    catalog_endpoint_type_claims,
    gateway_fingerprint_diagnostics,
    inspect_provider_gateway_headers,
    normalize_provider_connection_type,
)
from .provider_protocols import (
    assess_provider_capabilities,
    assess_provider_tool_call_probe,
    normalize_provider_protocol,
    normalize_provider_response,
    provider_protocol_family,
    provider_protocol_required_capability,
)
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
_VISION_CAPABILITY_PROBE_PROMPT = (
    "Inspect the supplied image and reply with exactly VISION_OK if you can see it. "
    "Do not explain your answer."
)
# A deterministic, harmless 1x1 white PNG. It is sent only by the live capability probe.
_VISION_CAPABILITY_PROBE_IMAGE = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _compact_text(value: object | None, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 1)].rstrip()}..."


def _optional_text(value: object | None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _stream_cancel_event(value: object | None) -> asyncio.Event | None:
    return value if isinstance(value, asyncio.Event) else None


async def _iterate_provider_stream_with_cancellation(
    stream: object,
    cancel_event: asyncio.Event | None,
):
    """Iterate an upstream async stream while promptly closing it on cancel."""

    iterator = stream.__aiter__()  # type: ignore[attr-defined]

    async def close_iterator() -> None:
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()

    while True:
        if cancel_event is None:
            try:
                yield await iterator.__anext__()
            except StopAsyncIteration:
                return
            continue
        if cancel_event.is_set():
            await close_iterator()
            raise asyncio.CancelledError

        next_item = asyncio.ensure_future(iterator.__anext__())
        cancellation = asyncio.create_task(cancel_event.wait())
        try:
            done, _ = await asyncio.wait(
                {next_item, cancellation},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation in done and cancel_event.is_set():
                next_item.cancel()
                await asyncio.gather(next_item, return_exceptions=True)
                await close_iterator()
                raise asyncio.CancelledError
            try:
                yield next_item.result()
            except StopAsyncIteration:
                return
        finally:
            if not cancellation.done():
                cancellation.cancel()
            await asyncio.gather(cancellation, return_exceptions=True)


async def _await_provider_stream_with_cancellation(
    awaitable: Any,
    cancel_event: asyncio.Event | None,
) -> Any:
    """Cancel stream creation as well as iteration when a turn is cancelled."""

    if cancel_event is None:
        return await awaitable
    if cancel_event.is_set():
        raise asyncio.CancelledError

    operation = asyncio.ensure_future(awaitable)
    cancellation = asyncio.create_task(cancel_event.wait())
    try:
        done, _ = await asyncio.wait(
            {operation, cancellation},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation in done and cancel_event.is_set():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise asyncio.CancelledError
        return operation.result()
    finally:
        if not cancellation.done():
            cancellation.cancel()
        await asyncio.gather(cancellation, return_exceptions=True)


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


def _needs_generous_visible_probe_budget(provider: ProviderConfig | None) -> bool:
    return (
        _is_minimax_like_provider(provider)
        or _is_kimi_like_provider(provider)
        or _model_looks_reasoning_first(provider)
    )


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
    normalized.pop("thinking", None)
    normalized.pop("thinkingBudget", None)
    normalized.pop("thinking_budget", None)
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


def _looks_like_json_error_body(text: str) -> bool:
    stripped = text.strip()
    start_obj = stripped.find("{")
    start_arr = stripped.find("[")
    start = min(
        start_obj if start_obj >= 0 else len(stripped) + 1,
        start_arr if start_arr >= 0 else len(stripped) + 1,
    )
    if start > len(stripped):
        return False
    candidate = stripped[start:]
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError):
        return False
    if isinstance(parsed, list):
        return True
    if not isinstance(parsed, dict):
        return False
    lowered = {str(key).lower() for key in parsed}
    return bool(
        lowered
        & {
            "choices",
            "content",
            "error",
            "data",
            "upstream_body",
            "payload",
            "response",
            "token",
            "api_key",
        }
        or len(lowered) >= 2
    )


def redact_provider_error(
    value: object | None,
    *,
    api_key: str | None = None,
    fallback: str = "Provider request failed",
) -> str:
    """Return an error detail that is safe to include in diagnostics or SSE output."""
    if isinstance(value, BaseException):
        status_code = getattr(value, "status_code", None)
        response = getattr(value, "response", None)
        if not isinstance(status_code, int):
            status_code = getattr(response, "status_code", None)
        suffix = f" (HTTP {status_code})" if isinstance(status_code, int) else ""
        return f"{fallback}{suffix}."

    if isinstance(value, dict):
        lowered_keys = {str(key).lower() for key in value}
        if any(_PROVIDER_SECRET_NAME_PATTERN.fullmatch(key) for key in lowered_keys):
            return f"{fallback}; credentials redacted."
        if lowered_keys & {"body", "payload", "content", "response", "upstream_body"}:
            return f"{fallback}; upstream response body redacted."
        try:
            text = json.dumps(value, default=str, ensure_ascii=True, sort_keys=True)
        except (TypeError, ValueError):
            return f"{fallback}."
    elif value is None:
        return f"{fallback}."
    else:
        text = str(value)

    if _PROVIDER_TRACEBACK_PATTERN.search(text):
        return f"{fallback}; technical details hidden."
    if _PROVIDER_THINK_PATTERN.search(text):
        return f"{fallback}; hidden reasoning redacted."
    if not isinstance(value, dict) and _looks_like_json_error_body(text):
        return f"{fallback}; upstream response body redacted."

    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = _PROVIDER_QUERY_CREDENTIAL_PATTERN.sub(r"\g<prefix>[REDACTED]", text)
    text = _PROVIDER_BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", text)
    text = _PROVIDER_SECRET_FIELD_PATTERN.sub(
        lambda match: f"{match.group('name')}{match.group('separator')}[REDACTED]",
        text,
    )
    text = _PROVIDER_UPSTREAM_BODY_PATTERN.sub(
        lambda match: f"{match.group('prefix')}[REDACTED_UPSTREAM_BODY]",
        text,
    )
    return _compact_text(text, limit=400) or f"{fallback}."


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

    if hasattr(value, "__dict__"):
        mapped = {
            key: field_value
            for key, field_value in vars(value).items()
            if not key.startswith("_")
        }
        return mapped or None

    return None


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


def _looks_like_mojibake_text(value: object) -> bool:
    text = str(value or "")
    return any(marker in text for marker in _MOJIBAKE_FALLBACK_MARKERS) or bool(
        _LATIN1_MOJIBAKE_PATTERN.search(text)
    )


def _localized_text(english: str, chinese: str, response_language: str | None) -> str:
    if _prefers_chinese(response_language) and _looks_like_mojibake_text(chinese):
        return (
            "\u5f53\u524d\u65e0\u6cd5\u5b89\u5168\u663e\u793a\u8fd9\u6761\u4e2d\u6587\u63d0\u793a\u3002"
            "\u8bf7\u68c0\u67e5 provider\u3001model \u548c\u8fde\u63a5\u540e\u91cd\u8bd5\u3002"
        )
    return chinese if _prefers_chinese(response_language) else english


_THINK_BLOCK_PATTERN = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_THINK_CLOSE_TAG_PATTERN = re.compile(r"</think\b[^>]*>", re.IGNORECASE | re.DOTALL)
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
_QUESTION_RUN_PATTERN = re.compile(r"\?{4,}")
_VISIBLE_TOKEN_PATTERN = re.compile(r"\S+")
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
_INPUT_CORRUPTION_MARKERS = (
    "question mark",
    "question marks",
    "garbled",
    "corrupted",
    "cannot read",
    "can't read",
    "could not read",
    "only saw",
    "only see",
    "\u95ee\u53f7",
    "\u4e71\u7801",
    "\u53ea\u80fd\u770b\u5230\u4e00\u4e32",
    "\u770b\u8d77\u6765\u4f60\u53d1\u8fc7\u6765\u7684\u5185\u5bb9\u91cc\u4e2d\u6587\u90fd\u53d8\u6210\u4e86\u95ee\u53f7",
    "\u7f16\u7801",
    "\u8f93\u5165\u6cd5",
)


def _strip_provider_control_markers(text: str) -> str:
    if not text:
        return ""
    cleaned = _PROVIDER_CONTROL_MARKER_PATTERN.sub("", text)
    cleaned = _PSEUDO_TOOL_CALL_BLOCK_PATTERN.sub("", cleaned)
    cleaned = _PSEUDO_TOOL_CALL_TAG_PATTERN.sub("", cleaned)
    return cleaned.strip()


def _strip_reasoning_blocks(text: str) -> str:
    if not text:
        return ""
    cleaned = _THINK_BLOCK_PATTERN.sub("", text)
    cleaned = _THINK_TAG_PATTERN.sub("", cleaned)
    return _strip_provider_control_markers(cleaned)


def _visible_model_text(value: object | None) -> str:
    if not isinstance(value, str):
        return ""
    return _strip_reasoning_blocks(value).translate(_VISIBLE_MODEL_PUNCTUATION_MAP)


def _has_hidden_reasoning(value: object | None) -> bool:
    if isinstance(value, str):
        return bool(value.strip()) and bool(_THINK_TAG_PATTERN.search(value)) and not _visible_model_text(value)
    if isinstance(value, list):
        return any(_has_hidden_reasoning(item) for item in value)

    record = _as_mapping(value) or {}

    for field_name in (
        "reasoning",
        "reasoning_content",
        "reasoningContent",
        "thinking",
        "thinking_content",
        "thinkingContent",
    ):
        field_value = record.get(field_name, getattr(value, field_name, None))
        if isinstance(field_value, str) and field_value.strip():
            return True
        if isinstance(field_value, (dict, list)) and field_value:
            return True

    if str(record.get("type", getattr(value, "type", "")) or "").strip().lower() in {
        "reasoning",
        "thinking",
    }:
        return True
    if record.get("thought", getattr(value, "thought", None)) is True and str(
        record.get("text", getattr(value, "text", "")) or ""
    ).strip():
        return True

    for field_name in ("content", "output", "parts", "text"):
        field_value = record.get(field_name, getattr(value, field_name, None))
        if isinstance(field_value, (dict, list)) and _has_hidden_reasoning(field_value):
            return True
        if isinstance(field_value, str) and _has_hidden_reasoning(field_value):
            return True
    return False


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


def _reasoning_budget_exhausted(response: object | None, *, max_tokens: int | None) -> bool:
    """Conservative signal that hidden reasoning consumed the entire output budget.

    Only a usage report at or above the requested output budget counts; when
    usage is unavailable the answer is False.
    """
    if not max_tokens or max_tokens <= 0:
        return False
    output_tokens = _usage_output_tokens(response)
    return output_tokens is not None and output_tokens >= max_tokens


class ProviderRuntimeResponseError(RuntimeError):
    """A safe failure raised when a provider response is not usable at runtime."""

    def __init__(
        self,
        *,
        category: str,
        detail: str,
        retryable: bool,
        status_code: int | None = 200,
        provider_reachable: bool = True,
        model_supported: bool | None = True,
    ) -> None:
        super().__init__(detail)
        self.provider_error_category = category
        self.safe_detail = detail
        self.provider_retryable = retryable
        self.status_code = status_code
        self.provider_reachable = provider_reachable
        self.model_supported = model_supported


class ContextBudgetExhaustedError(RuntimeError):
    """Raised before an upstream request when no usable reply budget remains."""

    def __init__(
        self,
        *,
        context_window_tokens: int,
        input_tokens: int,
        minimum_output_tokens: int,
    ) -> None:
        super().__init__("The request cannot reserve a visible output budget within the context window.")
        self.context_window_tokens = context_window_tokens
        self.input_tokens = input_tokens
        self.minimum_output_tokens = minimum_output_tokens


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


def _agent_result_visible_text(result: Any) -> str:
    return _visible_model_text(getattr(result, "final_content", "") or "")


def _agentic_has_grounded_resource_evidence(tool_events: list[dict[str, Any]]) -> bool:
    grounded_tool_names = {"search_resources", "read_workspace_file"}
    for event in tool_events:
        if not isinstance(event, dict):
            continue
        name = str(event.get("name") or "").strip()
        if name in grounded_tool_names:
            return True
    return False


def _agentic_recoverable_grounded_stop_reason(stop_reason: object) -> str:
    normalized = str(stop_reason or "").strip()
    return normalized if normalized in {"max_steps", "no_progress"} else ""


def _agentic_final_event_from_result(result: Any) -> dict[str, Any]:
    return {
        "type": "final",
        "content": _agent_result_visible_text(result),
        "summary": getattr(result, "summary", None),
        "next_step": getattr(result, "next_step", None),
        "stop_reason": getattr(result, "stop_reason", "completed"),
        "decision": getattr(result, "decision", None),
        "blocker": getattr(result, "blocker", None),
        "teaching_note": getattr(result, "teaching_note", None),
        "resume_thread": getattr(result, "resume_thread", None),
        "confidence": getattr(result, "confidence", None),
        "evidence": getattr(result, "evidence", None),
    }


_INTERNAL_COACH_META_MARKERS = (
    "current coaching focus:",
    "current focus:",
    "current focus to continue:",
    "review rhythm:",
    "memory scope is",
    "preferred teaching asset:",
    "reusable teaching asset:",
    "resume the live thread around",
    "evidence to anchor on:",
    "keep the next move as",
    "keep the blocker in view:",
    "build on the verified result:",
    "carry this teaching note forward:",
    "coach confidence:",
    "useful recalled memory:",
    "relevant recalled memory:",
    "continuity evidence:",
    "this follows the teaching lane from",
    "reuse the saved teaching asset",
    "saved teaching asset",
    "\u5f53\u524d\u805a\u7126\uff1a",
    "\u5f53\u524d\u805a\u7126\u70b9\uff1a",
    "\u590d\u4e60\u8282\u594f\uff1a",
    "\u8bb0\u5fc6\u8303\u56f4\u662f",
)
_INTERNAL_COACH_META_LABELS = {
    "project implementation",
    "idea implementation guidance",
    "project idea mining",
    "existing project adaptation",
    "project adaptation",
    "principle explanation",
    "review and reflection coaching",
    "plan and review rhythm",
    "plan and review",
    "task execution coaching",
    "next task coaching",
    "next step after review",
    "general coaching",
}
_INTERNAL_COACH_META_PREFIXES = (
    "current coaching focus:",
    "current focus:",
    "current focus to continue:",
    "review rhythm:",
    "preferred teaching asset:",
    "reusable teaching asset:",
    "resume the live thread around",
    "build on the verified result:",
    "keep the blocker in view:",
    "coach confidence:",
    "\u5f53\u524d\u805a\u7126\uff1a",
    "\u5f53\u524d\u805a\u7126\u70b9\uff1a",
    "\u590d\u4e60\u8282\u594f\uff1a",
)
_VISIBLE_COACH_PARAGRAPH_SPLIT_PATTERN = re.compile(r"\n\s*\n")
_VISIBLE_COACH_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?\u3002\uff01\uff1f])\s+")


def _normalize_coach_meta_candidate(text: str) -> str:
    return " ".join(text.strip().split())


def _strip_leading_coach_meta_prefix(text: str) -> str:
    normalized = _normalize_coach_meta_candidate(text)
    lowered = normalized.casefold()
    for prefix in _INTERNAL_COACH_META_PREFIXES:
        if lowered.startswith(prefix):
            return normalized[len(prefix) :].strip()
    return normalized


def _looks_like_internal_coach_meta(text: str) -> bool:
    normalized = _normalize_coach_meta_candidate(text)
    if not normalized:
        return False
    lowered = normalized.casefold()
    if any(marker in lowered for marker in _INTERNAL_COACH_META_MARKERS):
        return True
    label = lowered.strip(" -:*_#>~`[](){}")
    return label in _INTERNAL_COACH_META_LABELS


def _strip_internal_coach_meta(text: str) -> str:
    normalized_text = _visible_model_text(text)
    if not normalized_text.strip():
        return ""

    kept_paragraphs: list[str] = []
    for paragraph in _VISIBLE_COACH_PARAGRAPH_SPLIT_PATTERN.split(normalized_text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        kept_lines: list[str] = []
        for line in paragraph.splitlines():
            stripped_line = line.strip()
            if not stripped_line:
                continue
            stripped_line_without_prefix = _strip_leading_coach_meta_prefix(stripped_line)
            if (
                stripped_line_without_prefix
                and stripped_line_without_prefix != _normalize_coach_meta_candidate(stripped_line)
            ):
                stripped_line = stripped_line_without_prefix
            elif _looks_like_internal_coach_meta(stripped_line):
                continue
            kept_fragments: list[str] = []
            for fragment in _VISIBLE_COACH_SENTENCE_SPLIT_PATTERN.split(stripped_line):
                stripped_fragment = fragment.strip()
                if not stripped_fragment:
                    continue
                stripped_fragment_without_prefix = _strip_leading_coach_meta_prefix(stripped_fragment)
                if (
                    stripped_fragment_without_prefix
                    and stripped_fragment_without_prefix
                    != _normalize_coach_meta_candidate(stripped_fragment)
                ):
                    stripped_fragment = stripped_fragment_without_prefix
                elif _looks_like_internal_coach_meta(stripped_fragment):
                    continue
                kept_fragments.append(stripped_fragment)
            if not kept_fragments:
                continue
            joined = " ".join(kept_fragments)
            joined = re.sub(r"\s+([,.;:!?])", r"\1", joined).strip()
            if joined:
                kept_lines.append(joined)
        if kept_lines:
            kept_paragraphs.append("\n".join(kept_lines))

    cleaned = "\n\n".join(kept_paragraphs).strip()
    if not cleaned:
        return ""

    for prefix in _INTERNAL_COACH_META_PREFIXES:
        if cleaned.casefold().startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    return cleaned


def _contains_cjk(text: str | None) -> bool:
    if not text:
        return False
    return bool(_CJK_CHAR_PATTERN.search(text))


def _contains_latin(text: str | None) -> bool:
    if not text:
        return False
    return bool(_LATIN_CHAR_PATTERN.search(text))


def _contains_cyrillic(text: str | None) -> bool:
    if not text:
        return False
    return bool(_CYRILLIC_CHAR_PATTERN.search(text))


def _compact_visible_text(value: object | None, limit: int = 220) -> str:
    visible = _visible_model_text(value)
    normalized = " ".join(visible.split()).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 1)].rstrip()}..."


def _message_probe_fragment(message: str | None, limit: int = 120) -> str:
    normalized = " ".join(str(message or "").split()).strip()
    if not normalized or not _contains_cjk(normalized):
        return ""
    if len(normalized) <= limit:
        return normalized
    cjk_index = next((index for index, char in enumerate(normalized) if _contains_cjk(char)), 0)
    start = max(0, min(cjk_index, max(0, len(normalized) - limit)))
    fragment = normalized[start : start + limit].strip()
    if not _contains_cjk(fragment):
        fragment = normalized[:limit].strip()
    ascii_match = re.search(r"[A-Za-z][A-Za-z0-9._/-]{1,}", normalized)
    if ascii_match:
        ascii_token = ascii_match.group(0)
        if ascii_token not in fragment:
            remaining = limit - len(fragment) - 1
            if remaining > 0:
                fragment = f"{fragment} {ascii_token[:remaining]}".strip()
    return fragment


def _message_probe_variant(message: str | None) -> tuple[str, str] | None:
    fragment = _message_probe_fragment(message)
    if not fragment:
        return None
    return (f"Repeat exactly: {fragment}", fragment)


def _looks_like_input_corruption_reply(
    reply: str,
    *,
    expected_probe: str | None = None,
) -> bool:
    visible = _compact_visible_text(reply, limit=400)
    if not visible:
        return False
    lowered = visible.casefold()
    has_marker = any(marker.casefold() in lowered for marker in _INPUT_CORRUPTION_MARKERS)
    if expected_probe and expected_probe in visible:
        return False
    if has_marker and (
        "?" in visible
        or _QUESTION_RUN_PATTERN.search(visible)
        or "question mark" in lowered
        or "\u95ee\u53f7" in visible
        or "\u4e71\u7801" in visible
    ):
        return True
    if expected_probe:
        ascii_tail = "".join(char for char in expected_probe if char.isascii() and char.isalnum())
        cjk_chars = "".join(char for char in expected_probe if _contains_cjk(char))
        if (
            ascii_tail
            and ascii_tail in visible
            and cjk_chars
            and cjk_chars not in visible
            and "?" in visible
        ):
            return True
    return False


def _normalize_script_token(token: str) -> str:
    return re.sub(r"^[^A-Za-z\u0400-\u04FF]+|[^A-Za-z\u0400-\u04FF]+$", "", token)


def _normalize_cjk_script_token(token: str) -> str:
    return re.sub(r"^[^A-Za-z\u3400-\u9fff]+|[^A-Za-z\u3400-\u9fff]+$", "", token)


def _dedupe_fragments(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _strip_short_cyrillic_noise(
    reply: str,
    *,
    message: str | None = None,
) -> str:
    if not reply or not _contains_cyrillic(reply):
        return reply
    if message and _contains_cyrillic(message):
        return reply

    parts = re.split(r"(\s+)", reply)
    visible_positions = [index for index, part in enumerate(parts) if part and not part.isspace()]
    changed = False

    for visible_index, part_index in enumerate(visible_positions):
        token = parts[part_index]
        normalized = _normalize_script_token(token)
        if not normalized or not _contains_cyrillic(normalized):
            continue
        if _contains_latin(normalized):
            updated = re.sub(r"[\u0400-\u04FF]{1,2}", "", token)
            if updated != token and _contains_latin(updated):
                parts[part_index] = updated
                changed = True
            continue

        cyrillic_only = "".join(char for char in normalized if _contains_cyrillic(char))
        if len(cyrillic_only) > 2:
            continue
        previous_token = parts[visible_positions[visible_index - 1]] if visible_index > 0 else ""
        next_token = (
            parts[visible_positions[visible_index + 1]]
            if visible_index + 1 < len(visible_positions)
            else ""
        )
        if _contains_latin(previous_token) and _contains_latin(next_token):
            parts[part_index] = token.replace(normalized, "")
            changed = True

    if not changed:
        return reply
    sanitized = "".join(parts)
    sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
    return sanitized or reply


def _mixed_script_corruption_fragments(
    reply: str,
    *,
    message: str | None = None,
) -> list[str]:
    visible = _compact_visible_text(reply, limit=480)
    if not visible or not _contains_cyrillic(visible):
        return []
    if message and _contains_cyrillic(message):
        return []

    mixed_tokens: list[str] = []
    short_cyrillic_tokens: list[str] = []
    for match in _VISIBLE_TOKEN_PATTERN.finditer(visible):
        raw_token = match.group(0)
        token = _normalize_script_token(raw_token)
        if not token or not _contains_cyrillic(token):
            continue
        if _contains_latin(token):
            mixed_tokens.append(token)
            continue
        if len(token) <= 3:
            context_window = visible[max(0, match.start() - 12) : min(len(visible), match.end() + 12)]
            if _contains_latin(context_window):
                short_cyrillic_tokens.append(token)

    mixed_tokens = _dedupe_fragments(mixed_tokens)
    short_cyrillic_tokens = _dedupe_fragments(short_cyrillic_tokens)
    if mixed_tokens:
        return mixed_tokens[:2] + [
            token for token in short_cyrillic_tokens if token not in mixed_tokens
        ][:1]
    if len(short_cyrillic_tokens) >= 2 and _contains_latin(visible):
        return short_cyrillic_tokens[:3]
    return []


def _unexpected_cjk_corruption_fragments(
    reply: str,
    *,
    message: str | None = None,
    response_language: str | None = None,
) -> list[str]:
    visible = _compact_visible_text(reply, limit=480)
    if not visible or not _contains_cjk(visible):
        return []
    if _prefers_chinese(response_language):
        return []
    if message and _contains_cjk(message):
        return []

    mixed_tokens: list[str] = []
    short_cjk_tokens: list[str] = []
    for match in _VISIBLE_TOKEN_PATTERN.finditer(visible):
        raw_token = match.group(0)
        token = _normalize_cjk_script_token(raw_token)
        if not token or not _contains_cjk(token):
            continue
        if _contains_latin(token):
            mixed_tokens.append(token)
            continue
        cjk_only = "".join(char for char in token if "\u3400" <= char <= "\u9fff")
        if not cjk_only or len(cjk_only) > 3:
            continue
        context_window = visible[max(0, match.start() - 12) : min(len(visible), match.end() + 12)]
        if _contains_latin(context_window):
            short_cjk_tokens.append(cjk_only)

    mixed_tokens = _dedupe_fragments(mixed_tokens)
    short_cjk_tokens = _dedupe_fragments(short_cjk_tokens)
    if mixed_tokens:
        return mixed_tokens[:2] + [
            token for token in short_cjk_tokens if token not in mixed_tokens
        ][:1]
    if len(short_cjk_tokens) >= 2 and _contains_latin(visible):
        return short_cjk_tokens[:3]
    return []


def _wrong_language_cjk_reply_detail(
    reply: str,
    *,
    message: str | None = None,
    response_language: str | None = None,
) -> str | None:
    if _prefers_chinese(response_language):
        return None
    if message and _contains_cjk(message):
        # A CJK learner message invites a mirrored CJK reply; that is language
        # alignment with the learner, not a wrong-language corruption signal.
        return None
    visible = _compact_visible_text(reply, limit=480)
    if not visible or not _contains_cjk(visible):
        return None
    cjk_count = sum(1 for char in visible if "\u3400" <= char <= "\u9fff")
    latin_count = sum(1 for char in visible if char.isascii() and char.isalpha())
    if cjk_count < 12:
        return None
    if latin_count > 0 and cjk_count < latin_count * 2:
        return None
    return (
        "The provider returned a coaching reply in the wrong language. Trainer cannot "
        "trust this text as a clean coaching turn."
    )


def _wrong_language_zh_reply_detail(
    reply: str,
    *,
    response_language: str | None = None,
) -> str | None:
    """Reject prose-only English replies when the learner selected zh-CN.

    Code/API identifiers may remain English, so fenced and inline code are
    removed before deciding whether the remaining visible prose lacks CJK.
    """
    if not _prefers_chinese(response_language):
        return None
    visible = _compact_visible_text(reply, limit=480)
    if not visible or _contains_cjk(visible):
        return None
    prose = re.sub(r"```[\\s\\S]*?```", "", visible).strip()
    prose = re.sub(r"`[^`]*`", "", prose).strip()
    latin_words = re.findall(r"[A-Za-z]{3,}", prose)
    if len(latin_words) < 3:
        return None
    return (
        "The provider returned English-only visible prose while zh-CN is selected. "
        "Trainer cannot trust this text as a clean coaching turn."
    )


def _mixed_script_reply_corruption_detail(
    reply: str,
    *,
    message: str | None = None,
    response_language: str | None = None,
) -> str | None:
    visible = _compact_visible_text(reply, limit=480)
    wrong_language_zh_detail = _wrong_language_zh_reply_detail(
        reply,
        response_language=response_language,
    )
    if wrong_language_zh_detail:
        return wrong_language_zh_detail
    wrong_language_detail = _wrong_language_cjk_reply_detail(
        reply,
        message=message,
        response_language=response_language,
    )
    if wrong_language_detail:
        return wrong_language_detail
    unexpected_cjk_fragments = _unexpected_cjk_corruption_fragments(
        reply,
        message=message,
        response_language=response_language,
    )
    if unexpected_cjk_fragments:
        return (
            "The provider returned unexpected CJK fragments in an otherwise English coaching "
            "reply. Trainer cannot trust this text as a clean coaching turn."
        )
    if _looks_like_mojibake_text(visible):
        return (
            "The provider returned mojibake-corrupted text in the visible coaching reply. "
            "Trainer cannot trust this text as a clean coaching turn."
        )
    fragments = _mixed_script_corruption_fragments(reply, message=message)
    if fragments:
        return (
            "The provider returned suspicious mixed-script fragments in an otherwise readable "
            "coaching reply. Trainer cannot trust this text as a clean coaching turn."
        )
    return None


def _is_think_tag_prefix(text: str) -> bool:
    if not text.startswith("<"):
        return False
    lowered = text.lower()
    if lowered.startswith("</think"):
        remainder = text[7:]
        if not remainder:
            return True
        first = remainder[0]
        return not (first.isalnum() or first == "_")
    if lowered.startswith("<think"):
        remainder = text[6:]
        if not remainder:
            return True
        first = remainder[0]
        return not (first.isalnum() or first == "_")
    if "</think".startswith(lowered) or "<think".startswith(lowered):
        return True
    return False


def _reasoning_prefix_start(text: str) -> int | None:
    last_lt = text.rfind("<")
    if last_lt < 0:
        return None
    suffix = text[last_lt:]
    if _is_think_tag_prefix(suffix):
        return last_lt
    return None


def _trim_trailing_reasoning_prefix(text: str) -> str:
    prefix_start = _reasoning_prefix_start(text)
    if prefix_start is None:
        return text
    return text[:prefix_start]


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
            return 180.0
        return DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS

    def _agent_loop_timeout_kwargs(self) -> dict[str, float]:
        if not _is_kimi_like_provider(self._config):
            return {}
        return {
            "step_timeout": 120.0,
            "first_step_timeout": 180.0,
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

        return merged

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
            return ("network", True, status_code, False, None)
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
            return list(response)
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
                response = await client.chat.completions.create(**request_payload)
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

    def _plain_completion_protocol(self) -> str:
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
            merged["thinking"] = {"type": "disabled"}
            return merged
        thinking_budget = defaults.get("thinking_budget", defaults.get("thinkingBudget"))
        if isinstance(thinking_budget, int) and thinking_budget > 0:
            merged["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        elif isinstance(thinking_budget, str) and thinking_budget.strip().lower() == "disabled":
            merged.pop("thinking", None)
        return _flatten_minimax_thinking_for_raw_http(merged, provider)

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
        try:
            if protocol == "openai_responses":
                client = self._create_sync_client(provider, api_key)
                response = client.responses.create(
                    model=provider.model,
                    input=openai_responses_input_image_parts(
                        prompt=_VISION_CAPABILITY_PROBE_PROMPT,
                        image_url=_VISION_CAPABILITY_PROBE_IMAGE,
                    ),
                    temperature=0,
                    max_output_tokens=16,
                )
            elif protocol in {"openai_chat_completions", "openai_chat_completions_compatible"}:
                client = self._create_sync_client(provider, api_key)
                vision_max_tokens = 256 if _needs_generous_visible_probe_budget(provider) else 16
                payload = self._apply_request_defaults(
                    {
                        "model": provider.model,
                        "messages": [{"role": "user", "content": [
                            {"type": "text", "text": _VISION_CAPABILITY_PROBE_PROMPT},
                            {"type": "image_url", "image_url": {"url": _VISION_CAPABILITY_PROBE_IMAGE}},
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

                image_data = _VISION_CAPABILITY_PROBE_IMAGE.split(",", 1)[1]
                image_block = _anthropic_image_blocks([
                    {"kind": "image", "mime_type": "image/png", "data_base64": image_data}
                ])[0]
                payload = self._apply_anthropic_native_probe_defaults({
                    "model": provider.model,
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": _VISION_CAPABILITY_PROBE_PROMPT},
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
                image_data = _VISION_CAPABILITY_PROBE_IMAGE.split(",", 1)[1]
                payload = self._apply_gemini_native_probe_defaults({
                    "contents": [{"role": "user", "parts": [
                        {"text": _VISION_CAPABILITY_PROBE_PROMPT},
                        {"inlineData": {"mimeType": "image/png", "data": image_data}},
                    ]}],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": 16},
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
        normalized_visible = "".join(visible.split()).upper()
        if assessment.has_visible_text and "VISION_OK" in normalized_visible:
            return True, "Vision probe returned the expected token."
        if assessment.has_visible_text:
            return False, "Vision probe returned visible text other than the expected token."
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

        async def consume() -> bool:
            async for chunk in self.chat_completion_stream(
                [{"role": "user", "content": "Reply with one short visible word: OK."}],
                model=provider.model,
                temperature=0,
                # Some reasoning-first providers consume a short output budget
                # before emitting their first visible token. Keep this probe
                # aligned with the other visible-token probes so a working
                # native stream is not reported as unavailable.
                max_tokens=256 if _needs_generous_visible_probe_budget(provider) else 16,
            ):
                if isinstance(chunk, str) and chunk.strip():
                    # Streaming is verified as soon as the provider emits one visible chunk.
                    # Waiting for the stream to terminate can hang on providers that keep the
                    # connection open after already proving incremental output.
                    return True
            return False

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
                        response = client.chat.completions.create(**request_payload)
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
                            retry_probe_response = client.chat.completions.create(**retry_probe_request)
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
                        visible_probe_response = client.chat.completions.create(**visible_probe_request)
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
                    detail = (
                        f"Provider reachable and listed {count} models, but the chat probe did not verify "
                        f"a usable reply for model {provider.model}."
                    )
                    if models_result.resolved_model:
                        detail += f" The configured model resolves to {models_result.resolved_model}."
                    diagnostics = [
                        "Chat probe failed; model listing does not prove the selected model is usable.",
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
                    error_category="model_not_tested" if models_result.ok else category,
                    retryable=retryable if models_result.ok else models_result.retryable,
                    status_code=status_code if models_result.ok else models_result.status_code,
                    diagnostics=diagnostics,
                    provider_reachable=models_result.ok or provider_reachable,
                    model_supported=False if models_result.ok else model_supported,
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
        file_path = str(context.get("file_path") or "").strip() or None
        pace_signal = str(context.get("pace_signal") or "").strip()
        mode = normalize_answer_policy(answer_mode or profile.answer_policy)

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

        next_step_hint = _prefer_structured_next_step(
            scenario=scenario,
            next_step_hint=_extract_next_step_hint_text(context.get("next_step_hint")),
            implementation_guide=implementation_guide,
            adaptation_guide=adaptation_guide,
            principle_note=principle_note,
            project_ideas=project_ideas,
            exercise_prompt=exercise_prompt,
        )

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

        next_step_patch = _compose_missing_next_step_patch(
            reply=reply,
            scenario=scenario,
            next_step_hint=next_step_hint,
            file_path=file_path,
            project_entry_points=project_entry_points,
            learner_signal=learner_signal,
            mode=mode,
            chinese=chinese,
            coach_context=context,
        )
        if not next_step_patch:
            next_step_patch = None
        if next_step_patch:
            additions.append(next_step_patch)

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


def _agent_loop_max_steps(
    coach_context: dict[str, Any] | None,
    requested: int | None = None,
) -> int:
    """Resolve the last-resort safety ceiling for one agent turn.

    Pi's inner loop has no operational step cap: it continues until the model
    stops calling tools. Lane-specific 8/16/20 budgets were the wrong bound.
    ``requested`` still lets tests and callers pin a smaller ceiling.
    """

    _ = coach_context
    if requested is not None:
        return max(1, int(requested))
    from .agent_loop import SAFETY_MAX_STEPS

    return SAFETY_MAX_STEPS


def _denied_auto_mint_tool_names(extra: dict[str, Any]) -> list[str]:
    from .tools import PROJECT_WRITE_TOOL_NAMES

    denied: list[str] = []
    pressure_blocks = extra.get("pressure_blocks_live_object_mint") is True
    streak_blocks = extra.get("streak_blocks_live_object_mint") is True
    # Learning OS: never silently write learner project / business code.
    denied.extend(sorted(PROJECT_WRITE_TOOL_NAMES))
    # Composer chat never mints cards (even explicit "create a practice card").
    # Intentional mint is POST /training/generate-card only.
    denied.append("generate_training_card")
    if extra.get("formal_plan_mutation") is not True:
        denied.append("save_formal_plan")
    if extra.get("explicit_learning_note_request") is not True:
        denied.append("record_learning_note")
    if extra.get("explicit_resource_import") is not True:
        denied.append("import_resource_url")
    if extra.get("explicit_resource_organize") is not True:
        denied.append("organize_resources")
    # Same live-plan identity as HTTP /task/next and /task/specify.
    if (
        pressure_blocks
        or streak_blocks
        or extra.get("live_formal_plan_for_task_mint") is not True
        or extra.get("closed_loop_return_blocks_task_mint") is True
    ):
        denied.append("specify_task")
        denied.append("next_task")
    return denied


def _stamp_explicit_write_tool_flags(
    extra: dict[str, Any],
    *,
    coach_context: dict[str, Any] | None,
    learner_message: str | None,
) -> None:
    from ..memory.note_request import message_requests_explicit_learning_note
    from .tools import resource_write_explicitly_requested

    extra["explicit_learning_note_request"] = (
        isinstance(coach_context, dict)
        and coach_context.get("explicit_learning_note_request") is True
    ) or message_requests_explicit_learning_note(learner_message)
    extra["explicit_resource_import"] = (
        isinstance(coach_context, dict)
        and coach_context.get("explicit_resource_import") is True
    ) or resource_write_explicitly_requested(extra, mode="download")
    extra["explicit_resource_organize"] = (
        isinstance(coach_context, dict)
        and coach_context.get("explicit_resource_organize") is True
    ) or resource_write_explicitly_requested(extra, mode="organize")
    if (
        extra.get("library_sandbox_work") is True
        or str(extra.get("active_view") or "").strip().lower() == "resources"
        or extra.get("resource_composer_intent")
        or (isinstance(coach_context, dict) and coach_context.get("library_sandbox_work") is True)
    ):
        extra["library_sandbox_work"] = True
        extra["explicit_resource_organize"] = True
        extra["explicit_resource_import"] = True
    extra["denied_tool_names"] = _denied_auto_mint_tool_names(extra)


def _build_agent_tool_context_extra(
    *,
    coach_context: dict[str, Any] | None,
    attachment_delivery: dict[str, Any],
    answer_mode: str | None,
    current_file: dict[str, object] | None,
    provider_config: ProviderConfig | None = None,
    learner_message: str | None = None,
) -> dict[str, Any]:
    from ..training.card_request import message_requests_explicit_training_card

    normalized_answer_mode = normalize_answer_policy(answer_mode)
    extra: dict[str, Any] = {
        "attachments_will_send": bool(attachment_delivery.get("attachments_delivered_to_model")),
        "answer_mode": normalized_answer_mode,
        "allow_coach_only_tools": normalized_answer_mode in {"guided", "balanced"},
    }
    if provider_config is not None:
        window = getattr(provider_config, "context_window_tokens", None)
        try:
            if window is not None:
                extra["context_window_tokens"] = int(window)
        except (TypeError, ValueError):
            pass
    resolved_learner_message = learner_message
    if not isinstance(coach_context, dict):
        if isinstance(current_file, dict):
            extra["current_file"] = dict(current_file)
        extra["explicit_training_card_request"] = message_requests_explicit_training_card(
            resolved_learner_message
        )
        _stamp_explicit_write_tool_flags(
            extra,
            coach_context=None,
            learner_message=resolved_learner_message,
        )
        if isinstance(resolved_learner_message, str) and resolved_learner_message.strip():
            extra["learner_message"] = resolved_learner_message
        return extra

    if isinstance(current_file, dict):
        extra["current_file"] = dict(current_file)

    explicit_tool_scope = coach_context.get("allow_coach_only_tools")
    if isinstance(explicit_tool_scope, bool):
        extra["allow_coach_only_tools"] = explicit_tool_scope

    def _add_if_present(key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        extra[key] = value

    for key in (
        "scenario",
        "active_view",
        "library_sandbox_work",
        "workspace_file_snapshot",
        "resource_composer_intent",
        "learner_signal",
        "current_focus",
        "summary",
        "continuity_summary",
        "review_queue_summary",
        "next_step_hint",
        "pace_signal",
        "first_turn_priority",
        "formal_plan_mutation",
        # Local-only cooperative cancellation signal for active SSE turns.
        "stream_cancel_event",
    ):
        _add_if_present(key, coach_context.get(key))

    if coach_context.get("formal_plan_mutation") is True:
        extra["formal_plan_mutation"] = True
        # Formal plan turns are an explicit, governed write lane. They must be
        # able to call the commit tool even when the learner's default answer
        # policy is guided and would otherwise hide coach-only writes.
        extra["allow_coach_only_tools"] = True

    if coach_context.get("pressure_blocks_live_object_mint") is True:
        extra["pressure_blocks_live_object_mint"] = True
    if coach_context.get("streak_blocks_live_object_mint") is True:
        extra["streak_blocks_live_object_mint"] = True
    if coach_context.get("closed_loop_return_blocks_task_mint") is True:
        extra["closed_loop_return_blocks_task_mint"] = True
    if coach_context.get("live_formal_plan_for_task_mint") is True:
        extra["live_formal_plan_for_task_mint"] = True

    # Host/user attestation only — never trust model tool-arg self-attestation.
    if coach_context.get("resource_organization_confirmed") is True:
        extra["resource_organization_confirmed"] = True

    if not isinstance(resolved_learner_message, str) or not resolved_learner_message.strip():
        context_message = coach_context.get("learner_message")
        if isinstance(context_message, str) and context_message.strip():
            resolved_learner_message = context_message
    extra["explicit_training_card_request"] = (
        coach_context.get("explicit_training_card_request") is True
        or message_requests_explicit_training_card(resolved_learner_message)
    )
    _stamp_explicit_write_tool_flags(
        extra,
        coach_context=coach_context,
        learner_message=resolved_learner_message,
    )
    if isinstance(resolved_learner_message, str) and resolved_learner_message.strip():
        extra["learner_message"] = resolved_learner_message

    thread_summary = _compact_text(coach_context.get("thread_summary"), 140)
    thread_next_step = _compact_text(coach_context.get("thread_next_step"), 110)
    resume_hint = _compact_text(coach_context.get("resume_hint"), 160)
    active_thread = coach_context.get("active_thread")
    if isinstance(active_thread, dict):
        if not thread_summary:
            thread_summary = _compact_text(active_thread.get("summary"), 140) or _compact_text(active_thread.get("focus_area"), 140)
        if not thread_next_step:
            thread_next_step = _compact_text(active_thread.get("next_step"), 110)
    if not resume_hint:
        resume_hint_parts: list[str] = []
        if thread_summary:
            resume_hint_parts.append(f"Resume the live thread around {thread_summary}.")
        if thread_next_step:
            resume_hint_parts.append(f"Keep the next move as {thread_next_step}.")
        if isinstance(active_thread, dict):
            blocker = _compact_text(active_thread.get("blocker"), 96)
            verified_result = _compact_text(active_thread.get("verified_result"), 96)
            if blocker:
                resume_hint_parts.append(f"Keep the blocker in view: {blocker}.")
            if verified_result:
                resume_hint_parts.append(f"Build on the verified result: {verified_result}.")
        resume_hint = " ".join(resume_hint_parts).strip()
    _add_if_present("thread_summary", thread_summary)
    _add_if_present("thread_next_step", thread_next_step)
    _add_if_present("resume_hint", resume_hint)

    implementation_guide = coach_context.get("implementation_guide")
    if isinstance(implementation_guide, dict):
        for key in ("current_step", "scope_boundary", "validation_strategy"):
            _add_if_present(f"implementation_{key}", implementation_guide.get(key))

    exercise_prompt = coach_context.get("exercise_prompt")
    if isinstance(exercise_prompt, dict):
        for key in ("prompt", "success_signal", "fallback_step"):
            _add_if_present(f"exercise_{key}", exercise_prompt.get(key))

    active_thread = coach_context.get("active_thread")
    if isinstance(active_thread, dict):
        for key in ("focus_area", "verified_result", "blocker", "next_step"):
            _add_if_present(f"thread_{key}", active_thread.get(key))

    if _compatibility_intake_is_tool_free(
        provider_config=provider_config,
        coach_context=coach_context,
        attachment_delivery=attachment_delivery,
        current_file=current_file,
    ):
        extra["allowed_tool_names"] = []

    return extra


def _compatibility_intake_is_tool_free(
    *,
    provider_config: ProviderConfig | None,
    coach_context: dict[str, Any] | None,
    attachment_delivery: dict[str, Any],
    current_file: dict[str, object] | None,
) -> bool:
    if provider_config is None or not isinstance(coach_context, dict):
        return False
    if normalize_provider_protocol(getattr(provider_config, "protocol", None)) != "anthropic_messages":
        return False
    hostname = (urlsplit(str(getattr(provider_config, "base_url", "") or "")).hostname or "").lower()
    if hostname.endswith("anthropic.com"):
        return False
    if str(coach_context.get("relationship_stage") or "").strip() != "intake":
        return False
    if not str(coach_context.get("first_turn_priority") or "").startswith(
        "orient, reassure, clarify learner goal"
    ):
        return False
    if str(coach_context.get("scenario") or "").strip() not in {
        "remote_workspace",
        "debug_loop",
        "function_guidance",
    }:
        return False
    if current_file or attachment_delivery.get("attachments_present"):
        return False
    if coach_context.get("auto_resource_lookup") is True:
        return False
    if any(
        isinstance(coach_context.get(key), list) and coach_context[key]
        for key in ("resource_fragments", "requested_resources")
    ):
        return False
    active_view = str(coach_context.get("active_view") or "").strip().lower()
    return active_view in {"", "coach"}


def _agentic_practice_completion_guard(
    *,
    content: str,
    tool_events: list[dict[str, Any]],
    message: str,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, str] | None:
    if not _agentic_practice_verification_context_active(
        message=message,
        current_file=current_file,
        coach_context=coach_context,
    ):
        return None
    if not _claims_verified_practice_completion(content):
        return None
    verification_result = _current_file_practice_verification_result(tool_events)
    if isinstance(verification_result, dict) and verification_result.get("passed") is True:
        return None

    chinese = _prefers_chinese(response_language)
    if isinstance(verification_result, dict):
        tool_summary = str(verification_result.get("summary") or "").strip()
        tool_next_step = str(verification_result.get("next_step") or "").strip()
        if chinese:
            summary = tool_summary or "\u5f53\u524d\u6587\u4ef6\u7684\u7ec3\u4e60\u9a8c\u8bc1\u8fd8\u6ca1\u901a\u8fc7\u3002"
            next_step = tool_next_step or "\u5148\u6839\u636e\u9a8c\u8bc1\u7ed3\u679c\u4fee\u8865\u5f53\u524d\u6587\u4ef6\uff0c\u7136\u540e\u518d\u9a8c\u8bc1\u4e00\u6b21\u3002"
            content = f"\u6211\u68c0\u67e5\u4e86 IDE \u91cc\u7684\u5f53\u524d\u6587\u4ef6\uff0c\u4f46\u8fd8\u4e0d\u80fd\u628a\u8fd9\u6b21\u52a8\u624b\u7ec3\u4e60\u6807\u8bb0\u4e3a\u901a\u8fc7\u3002\n\n{summary}\n\n{next_step}"
        else:
            summary = tool_summary or "Current-file practice verification did not pass."
            next_step = tool_next_step or "Patch the current file against the verification result, then verify again."
            content = (
                "I checked the active IDE file, but I cannot mark this practice as passed yet.\n\n"
                f"{summary}\n\n{next_step}"
            )
    elif chinese:
        summary = "\u8fd9\u6b21\u7ec3\u4e60\u8fd8\u6ca1\u6709\u53ef\u7528\u7684 current-file verification evidence\u3002"
        next_step = "\u6253\u5f00 implementation file\uff0c\u8fd0\u884c Verify current file\uff0c\u8ba9 Trainer \u68c0\u67e5\u6587\u4ef6\u3001diagnostics \u548c acceptance signals\u3002"
        content = (
            "\u6211\u8fd8\u4e0d\u80fd\u628a\u8fd9\u6b21\u52a8\u624b\u7ec3\u4e60\u6807\u8bb0\u4e3a\u901a\u8fc7\u3002"
            "Trainer \u8fd8\u9700\u8981\u6765\u81ea VS Code \u7684 current-file verification evidence\uff1a"
            "active file\u3001diagnostics \u548c acceptance signals\u3002\n\n"
            f"{next_step}"
        )
    else:
        summary = "Practice is not marked passed yet because current-file verification evidence is missing."
        next_step = "Open the implementation file and run Verify current file so Trainer can check the file, diagnostics, and acceptance signals."
        content = (
            "I cannot mark this hands-on practice as passed yet. The coach still needs current-file "
            "verification evidence from VS Code: the active file, diagnostics, and acceptance signals.\n\n"
            f"{next_step}"
        )
    return {
        "content": content,
        "summary": summary,
        "next_step": next_step,
        "stop_reason": "practice_verification_required",
    }


async def _maybe_auto_verify_practice_current_file(
    *,
    registry: Any,
    context: Any,
    tool_events: list[dict[str, Any]],
    message: str,
    content: str,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if _current_file_practice_verification_result(tool_events) is not None:
        return []
    if not _agentic_practice_verification_context_active(
        message=message,
        current_file=current_file,
        coach_context=coach_context,
    ):
        return []
    if not _practice_verification_requested_or_claimed(message=message, content=content):
        return []
    if not isinstance(current_file, dict):
        return []
    file_content = current_file.get("content") or current_file.get("content_excerpt") or ""
    if not str(file_content).strip():
        return []
    arguments = _practice_verification_arguments(
        current_file=current_file,
        coach_context=coach_context,
    )
    if not arguments.get("acceptance_criteria") and not arguments.get("expected_symbols"):
        return []

    tool_id = "auto_verify_practice_current_file"
    tool_call = {
        "type": "tool_call",
        "id": tool_id,
        "name": "verify_practice_current_file",
        "arguments": arguments,
        "step": "auto",
        "auto": True,
    }
    tool_result = await registry.invoke(context, "verify_practice_current_file", arguments)
    return [
        tool_call,
        {
            "type": "tool_result",
            "id": tool_id,
            "name": "verify_practice_current_file",
            "ok": bool(tool_result.get("ok")) if isinstance(tool_result, dict) else False,
            "result": tool_result,
            "step": "auto",
            "auto": True,
        },
    ]


def _practice_verification_requested_or_claimed(*, message: str, content: str) -> bool:
    combined = f"{message}\n{content}".lower()
    if _claims_verified_practice_completion(content):
        return True
    return any(
        phrase in combined
        for phrase in (
            "can i mark",
            "mark it",
            "mark this",
            "verify",
            "verification",
            "passed",
            "complete",
            "done",
            "review my practice",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        )
    )


def _practice_verification_arguments(
    *,
    current_file: dict[str, object],
    coach_context: dict[str, Any] | None,
) -> dict[str, Any]:
    criteria: list[str] = []
    expected_symbols: list[str] = []

    def add_text(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in criteria:
            criteria.append(text)

    def add_list(value: Any) -> None:
        if not isinstance(value, list):
            return
        for item in value:
            add_text(item)

    def add_symbol(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in expected_symbols:
            expected_symbols.append(text)

    def add_symbol_list(value: Any) -> None:
        if not isinstance(value, list):
            return
        for item in value:
            add_symbol(item)

    def collect_from_record(record: Any) -> None:
        if not isinstance(record, dict):
            return
        add_list(record.get("acceptance_criteria") or record.get("acceptanceCriteria"))
        add_list(record.get("learner_deliverables") or record.get("learnerDeliverables"))
        add_list(record.get("verification_steps") or record.get("verificationSteps"))
        add_list(record.get("self_check") or record.get("selfCheck"))
        add_list(record.get("constraints"))
        for key in (
            "success_signal",
            "successSignal",
            "deliverable",
            "problem_statement",
            "problemStatement",
            "suggested_workspace_action",
            "suggestedWorkspaceAction",
        ):
            add_text(record.get(key))
        add_symbol_list(record.get("expected_symbols") or record.get("expectedSymbols"))
        add_symbol_list(record.get("api_hints") or record.get("apiHints"))

    collect_from_record(current_file)
    if isinstance(coach_context, dict):
        collect_from_record(coach_context.get("exercise_prompt"))
        collect_from_record(coach_context)
        routing = coach_context.get("active_training_card_routing") or coach_context.get("activeTrainingCardRouting")
        if isinstance(routing, dict):
            collect_from_record(routing.get("selected_card") or routing.get("selectedCard"))
        memory = coach_context.get("memory")
        if isinstance(memory, dict):
            routing = memory.get("active_training_card_routing") or memory.get("activeTrainingCardRouting")
            if isinstance(routing, dict):
                collect_from_record(routing.get("selected_card") or routing.get("selectedCard"))
            ledger = memory.get("training_event_ledger") or memory.get("trainingEventLedger")
            if isinstance(ledger, list):
                for item in ledger[-4:]:
                    collect_from_record(item)

    return {
        "acceptance_criteria": criteria[:12],
        "expected_symbols": expected_symbols[:12],
        "max_evidence": 8,
    }


def _training_record_has_verification_clues(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    list_keys = (
        "acceptance_criteria",
        "acceptanceCriteria",
        "learner_deliverables",
        "learnerDeliverables",
        "verification_steps",
        "verificationSteps",
        "self_check",
        "selfCheck",
        "expected_symbols",
        "expectedSymbols",
        "api_hints",
        "apiHints",
    )
    for key in list_keys:
        value = record.get(key)
        if isinstance(value, list) and any(str(item or "").strip() for item in value):
            return True
    scalar_keys = (
        "training_card_id",
        "trainingCardId",
        "selected_card_id",
        "selectedCardId",
        "success_signal",
        "successSignal",
        "deliverable",
        "problem_statement",
        "problemStatement",
        "suggested_workspace_action",
        "suggestedWorkspaceAction",
    )
    for key in scalar_keys:
        if str(record.get(key) or "").strip():
            return True
    target_skill = str(record.get("target_skill") or record.get("targetSkill") or "").strip().lower()
    return bool(target_skill) and any(
        token in target_skill for token in ("practice", "current-file", "verification")
    )


def _coach_context_has_active_training_card(coach_context: dict[str, Any] | None) -> bool:
    if not isinstance(coach_context, dict):
        return False
    routing_candidates: list[Any] = [
        coach_context.get("active_training_card_routing"),
        coach_context.get("activeTrainingCardRouting"),
    ]
    memory = coach_context.get("memory")
    if isinstance(memory, dict):
        routing_candidates.extend(
            [
                memory.get("active_training_card_routing"),
                memory.get("activeTrainingCardRouting"),
            ]
        )
    for routing in routing_candidates:
        if not isinstance(routing, dict):
            continue
        selected_card = routing.get("selected_card") or routing.get("selectedCard")
        if _training_record_has_verification_clues(selected_card):
            return True
        if str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip():
            return True
    return False


def _current_file_has_training_context(current_file: dict[str, object] | None) -> bool:
    if not isinstance(current_file, dict):
        return False
    if _training_record_has_verification_clues(current_file):
        return True
    return any(
        str(current_file.get(key) or "").strip().lower() == "training"
        for key in ("evaluation_source", "source", "mode")
    )


def _current_file_has_visible_content(current_file: dict[str, object] | None) -> bool:
    if not isinstance(current_file, dict):
        return False
    return any(
        str(current_file.get(key) or "").strip()
        for key in ("path", "content", "content_excerpt")
    )


def _agentic_practice_verification_context_active(
    *,
    message: str,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> bool:
    context = extract_coaching_context(message, current_file, coach_context)
    if isinstance(context.get("exercise_prompt"), dict):
        return True

    coaching_state = context.get("coaching_state")
    if isinstance(coaching_state, dict):
        teaching_mode = str(coaching_state.get("teaching_mode") or "").strip().lower()
        if teaching_mode == "practice":
            return True

    if _current_file_has_training_context(current_file):
        return True

    practice_focus_text = " ".join(
        str(value or "")
        for value in (
            message,
            context.get("summary"),
            context.get("current_focus"),
            context.get("next_step_hint"),
        )
    )
    practice_terms_present = _text_has_practice_verification_terms(practice_focus_text)
    if not practice_terms_present:
        return False

    if _current_file_has_visible_content(current_file):
        return True
    if _coach_context_has_active_training_card(coach_context):
        return True
    return False


def _text_has_practice_verification_terms(text: str) -> bool:
    lowered = text.lower()
    return any(
        term in lowered
        for term in (
            "practice",
            "training card",
            "hands-on",
            "acceptance",
            "",
            "",
            "",
        )
    )


def _claims_verified_practice_completion(content: str) -> bool:
    lowered = content.lower()
    if any(
        phrase in lowered
        for phrase in (
            "not passed",
            "did not pass",
            "does not pass",
            "not verified",
            "cannot mark",
            "can't mark",
            "needs review",
            "need current-file",
            "needs current-file",
            "missing current-file",
            "\u8fd8\u6ca1\u901a\u8fc7",
            "\u4e0d\u80fd\u6807\u8bb0\u4e3a\u901a\u8fc7",
            "\u7f3a\u5c11 current-file",
            "verification evidence",
        )
    ):
        return False
    return any(
        phrase in lowered
        for phrase in (
            "practice passed",
            "you passed",
            "verification passed",
            "practice is verified",
            "verified from the current file",
            "verified by current-file evidence",
            "this passes",
            "meets the acceptance",
            "mark it complete",
            "mark this complete",
            "ready to mark complete",
            "passed the practice",
            "\u5df2\u901a\u8fc7",
            "\u9a8c\u8bc1\u5df2\u901a\u8fc7",
            "\u53ef\u4ee5\u6807\u8bb0\u5b8c\u6210",
        )
    )

def _has_passed_current_file_practice_verification(tool_events: list[dict[str, Any]]) -> bool:
    result = _current_file_practice_verification_result(tool_events)
    return isinstance(result, dict) and result.get("passed") is True


def _current_file_practice_verification_result(tool_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in tool_events:
        if str(event.get("type") or "") != "tool_result":
            continue
        if str(event.get("name") or "") != "verify_practice_current_file":
            continue
        result = event.get("result")
        if isinstance(result, dict):
            return result
    return None


def _agentic_fallback_continuity(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> tuple[str, str]:
    context = extract_coaching_context(message, current_file, coach_context)
    chinese = _prefers_chinese(response_language)
    summary = str(
        context.get("thread_summary")
        or context.get("summary")
        or context.get("current_focus")
        or context.get("continuity_summary")
        or context.get("review_queue_summary")
        or ""
    ).strip()
    if not summary:
        summary = (
            "This turn needs a fresh provider retry, but the same thread can continue."
            if not chinese
            else "这轮需要重新连接模型服务，但同一条对话可以继续。"
        )

    scenario = str(context.get("scenario") or "general").strip()
    next_step_hint = _prefer_structured_next_step(
        scenario=scenario,
        next_step_hint=_extract_next_step_hint_text(
            context.get("thread_next_step") or context.get("resume_hint") or context.get("next_step_hint")
        ),
        implementation_guide=context.get("implementation_guide") if isinstance(context.get("implementation_guide"), dict) else {},
        adaptation_guide=context.get("project_adaptation_guide") if isinstance(context.get("project_adaptation_guide"), dict) else context.get("adaptation_guide") if isinstance(context.get("adaptation_guide"), dict) else {},
        principle_note=context.get("principle_notes") if isinstance(context.get("principle_notes"), dict) else context.get("principle_note") if isinstance(context.get("principle_note"), dict) else {},
        project_ideas=[item for item in context.get("project_ideas", []) if isinstance(item, dict)] if isinstance(context.get("project_ideas"), list) else [],
        exercise_prompt=context.get("exercise_prompt") if isinstance(context.get("exercise_prompt"), dict) else {},
    )
    next_step = str(
        next_step_hint
        or context.get("thread_next_step")
        or context.get("resume_hint")
        or context.get("next_step")
        or context.get("continuity_summary")
        or context.get("review_queue_summary")
        or ""
    ).strip()
    if not next_step:
        next_step = (
            "Retry from the smallest verified step after checking the provider connection."
            if not chinese
            else "检查模型服务后，从上一次已验证的最小步骤继续。"
        )
    return summary, next_step


def _agentic_completion_continuity(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
    content: str,
) -> tuple[str, str]:
    context = extract_coaching_context(message, current_file, coach_context)
    chinese = _prefers_chinese(response_language)

    summary_candidates: list[Any] = [
        context.get("thread_summary"),
        context.get("summary"),
        context.get("current_focus"),
        context.get("continuity_summary"),
        context.get("review_queue_summary"),
        context.get("project_summary"),
    ]
    active_thread = context.get("active_thread")
    if isinstance(active_thread, dict):
        summary_candidates.extend(
            [
                active_thread.get("summary"),
                active_thread.get("focus_area"),
                active_thread.get("verified_result"),
            ]
        )
    exercise_prompt = context.get("exercise_prompt")
    if isinstance(exercise_prompt, dict):
        summary_candidates.extend(
            [
                exercise_prompt.get("summary"),
                exercise_prompt.get("prompt"),
                exercise_prompt.get("success_signal"),
            ]
        )
    implementation_guide = context.get("implementation_guide")
    if isinstance(implementation_guide, dict):
        summary_candidates.extend(
            [
                implementation_guide.get("current_step"),
                implementation_guide.get("scope_boundary"),
            ]
        )

    summary = next(
        (
            text
            for text in (_compact_text(candidate, 140) for candidate in summary_candidates)
            if text
        ),
        "",
    )
    if not summary:
        summary = _trim_sentence(content, 140)
    if not summary:
        summary = (
            "This turn is complete; keep the same coaching thread moving."
            if not chinese
            else "\u8fd9\u4e00\u8f6e\u5df2\u7ecf\u6536\u675f\uff0c\u4fdd\u6301\u540c\u4e00\u6761\u6559\u7ec3\u7ebf\u7a0b\u7ee7\u7eed\u5f80\u524d\u8d70\u3002"
        )

    next_step = _prefer_structured_next_step(
        scenario=str(context.get("scenario") or "general").strip(),
        next_step_hint=_extract_next_step_hint_text(
            context.get("thread_next_step") or context.get("resume_hint") or context.get("next_step_hint")
        ),
        implementation_guide=implementation_guide if isinstance(implementation_guide, dict) else {},
        adaptation_guide=context.get("project_adaptation_guide")
        if isinstance(context.get("project_adaptation_guide"), dict)
        else context.get("adaptation_guide")
        if isinstance(context.get("adaptation_guide"), dict)
        else {},
        principle_note=context.get("principle_notes")
        if isinstance(context.get("principle_notes"), dict)
        else context.get("principle_note")
        if isinstance(context.get("principle_note"), dict)
        else {},
        project_ideas=[item for item in context.get("project_ideas", []) if isinstance(item, dict)]
        if isinstance(context.get("project_ideas"), list)
        else [],
        exercise_prompt=exercise_prompt if isinstance(exercise_prompt, dict) else {},
    )
    if not next_step and isinstance(active_thread, dict):
        for candidate_key in ("next_step", "blocker", "verified_result"):
            text = _compact_text(active_thread.get(candidate_key), 120)
            if text:
                next_step = text
                break
    if not next_step:
        next_step = _compact_text(context.get("thread_next_step"), 120) or ""
    if not next_step:
        next_step = _compact_text(context.get("resume_hint"), 120) or ""
    if not next_step:
        next_step = _trim_sentence(content, 120)
    if not next_step:
        next_step = (
            "Continue from the same thread and verify the smallest concrete result."
            if not chinese
            else "\u6cbf\u7740\u540c\u4e00\u6761\u7ebf\u7a0b\u7ee7\u7eed\uff0c\u5148\u9a8c\u8bc1\u6700\u5c0f\u7684\u5177\u4f53\u7ed3\u679c\u3002"
        )

    resolved_scenario = _resolve_first_turn_guided_lane(
        scenario=str(context.get("scenario") or "").strip(),
        learner_message=message,
        reply=content,
    )
    if resolved_scenario in _GUIDED_DOMAIN_SCENARIOS:
        if _looks_like_generic_guided_review_fallback(summary):
            repaired_summary = _first_turn_lane_continuity_note(
                resolved_scenario,
                chinese=chinese,
                coach_context=context,
            )
            if repaired_summary:
                summary = repaired_summary
        if _looks_like_generic_guided_review_fallback(next_step):
            repaired_next_step = _first_turn_lane_next_step(
                resolved_scenario,
                chinese=chinese,
                coach_context=context,
            )
            if repaired_next_step:
                next_step = repaired_next_step

    return summary, next_step


def _agentic_resume_thread_text(
    summary: object | None,
    next_step: object | None,
    *,
    response_language: str | None,
) -> str:
    chinese = _prefers_chinese(response_language)
    summary_text = _compact_text(summary, 160) or ""
    next_step_text = _compact_text(next_step, 160) or ""
    if next_step_text:
        if chinese:
            for prefix in ("\u4e0b\u4e00\u6b65\uff1a", "\u4e0b\u4e00\u6b65:"):
                if next_step_text.startswith(prefix):
                    next_step_text = next_step_text[len(prefix) :].strip()
                    break
        else:
            lowered_next_step = next_step_text.casefold()
            for prefix in ("next step:", "next:"):
                if lowered_next_step.startswith(prefix):
                    next_step_text = next_step_text[len(prefix) :].strip()
                    break
    if not summary_text and not next_step_text:
        return ""
    if summary_text and summary_text[-1] not in ".!?。！？":
        summary_text = f"{summary_text}{'。' if chinese else '.'}"
    if summary_text and next_step_text:
        if chinese:
            return f"\u56de\u5230\u540c\u4e00\u6761\u6559\u7ec3\u7ebf\u7a0b\uff1a{summary_text}\n\n\u4e0b\u4e00\u6b65\uff1a{next_step_text}"
        return f"Resume the live thread around {summary_text} Next: {next_step_text}"
    if summary_text:
        if chinese:
            return f"\u56de\u5230\u540c\u4e00\u6761\u6559\u7ec3\u7ebf\u7a0b\uff1a{summary_text}"
        return f"Resume the live thread around {summary_text}"
    if chinese:
        return f"\u6cbf\u7740\u540c\u4e00\u6761\u7ebf\u7a0b\u7ee7\u7eed\u3002\u4e0b\u4e00\u6b65\uff1a{next_step_text}"
    return f"Resume the live thread. Next: {next_step_text}"


_GUIDED_DOMAIN_SCENARIOS = {
    "remote_workspace",
    "debug_loop",
    "function_guidance",
    "project_adaptation",
}

_STRUCTURED_ACTIVE_VIEWS = frozenset({"plan", "resources", "training", "settings"})


def _coaching_active_view_name(coach_context: dict[str, Any] | None) -> str:
    if not isinstance(coach_context, dict):
        return ""
    normalized = str(
        coach_context.get("active_view")
        or coach_context.get("activeView")
        or ""
    ).strip().lower()
    return normalized if normalized in _STRUCTURED_ACTIVE_VIEWS else ""


def _guided_domain_inference_coach_context(coach_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(coach_context, dict):
        return []
    scenario = str(coach_context.get("scenario") or "").strip().lower()
    history_mode = str(coach_context.get("history_mode") or "").strip().lower()
    parts: list[str] = []
    if scenario:
        parts.append(scenario)
    if history_mode == "fresh_lane":
        return parts
    if scenario not in _GUIDED_DOMAIN_SCENARIOS:
        return parts
    for key in ("current_focus", "summary", "thread_summary", "thread_next_step"):
        value = coach_context.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return parts


def _guided_domain_blob(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> str:
    parts: list[str] = [message]
    if current_file:
        for key in ("path", "language_id", "content"):
            value = current_file.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    parts.extend(_guided_domain_inference_coach_context(coach_context))
    return " ".join(parts).lower()


def _infer_guided_coaching_domain(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> str | None:
    blob = _guided_domain_blob(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    if not blob:
        return None

    for domain in (
        "remote_workspace",
        "debug_loop",
        "function_guidance",
        "project_adaptation",
    ):
        if domain in blob:
            return domain

    remote_tokens = (
        "remote ssh",
        "remote workspace",
        "remote tunnel",
        "remote tunnels",
        "vscode remote",
        "dev container",
        "dev containers",
        "devcontainer",
        "wsl",
        "credential mode",
        "ssh",
        "远程",
        "远程开发",
        "远程工作区",
        "远程连接",
        "隧道",
        "容器",
        "凭据模式",
    )
    if any(token in blob for token in remote_tokens):
        return "remote_workspace"

    debug_tokens = (
        "debug",
        "launch.json",
        "breakpoint",
        "debug console",
        "watch expression",
        "stack trace",
        "step into",
        "step over",
        "exception breakpoint",
        "调试",
        "断点",
        "调用栈",
        "堆栈",
        "单步",
        "启动配置",
    )
    if any(token in blob for token in debug_tokens):
        return "debug_loop"

    function_tokens = (
        "signature help",
        "function hint",
        "parameter hint",
        "hover",
        "call site",
        "function call",
        "peek definition",
        "go to definition",
        "find all references",
        "intellisense",
        "autocomplete",
        "completion",
        "function contract",
        "typescript function",
        "ts function",
        "api call",
        "函数提示",
        "函数签名",
        "参数提示",
        "悬停",
        "查看定义",
        "转到定义",
        "引用",
        "补全",
    )
    if any(token in blob for token in function_tokens):
        return "function_guidance"

    project_tokens = (
        "existing project",
        "project adaptation",
        "adaptation",
        "migration",
        "migrate",
        "改造",
        "适配",
        "迁移",
        "接入现有项目",
    )
    if any(token in blob for token in project_tokens):
        return "project_adaptation"
    return None

def _guided_domain_empty_reply(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> str:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    return _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
    )

def _guided_domain_empty_reply_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, str] | None:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    return _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
    )

def _prefers_chinese(response_language: str | None) -> bool:
    return bool(response_language and response_language.lower().startswith("zh"))


def _stream_holdback_chars(response_language: str | None) -> int:
    """Keep a shorter Chinese tail in reserve so real deltas appear sooner."""

    return 24 if _prefers_chinese(response_language) else 32


def _compose_scaffold_paragraphs(
    *,
    scenario: str,
    mode: str,
    learner_signal: str,
    anchor: str,
    diagnosis: str,
    next_step: str,
    teaching_note: str,
    close: str,
    chinese: bool,
) -> list[str]:
    if chinese:
        if scenario in {"review", "task", "next_task", "engineering_challenge"}:
            return [
                anchor,
                f"{diagnosis} {next_step}".strip(),
                teaching_note,
                close,
            ]
        if scenario in {"principle", "plan", "concept_teaching"}:
            return [
                anchor,
                diagnosis,
                f"{next_step} {teaching_note}".strip(),
                close,
            ]
        if learner_signal == "blocked" or mode == "direct":
            return [
                anchor,
                f"{diagnosis} {next_step}".strip(),
                close,
            ]
        return [
            anchor,
            diagnosis,
            next_step,
            teaching_note,
            close,
        ]

    if scenario in {"review", "task", "next_task", "engineering_challenge"}:
        return [
            anchor,
            f"{diagnosis} {next_step}".strip(),
            teaching_note,
            close,
        ]
    if scenario in {"principle", "plan", "concept_teaching"}:
        return [
            anchor,
            diagnosis,
            f"{next_step} {teaching_note}".strip(),
            close,
        ]
    if learner_signal == "blocked" or mode == "direct":
        return [
            anchor,
            f"{diagnosis} {next_step}".strip(),
            close,
        ]
    return [
        anchor,
        diagnosis,
        next_step,
        teaching_note,
        close,
    ]


def _prefer_structured_next_step(
    *,
    scenario: str,
    next_step_hint: str,
    implementation_guide: dict[str, object] | None,
    adaptation_guide: dict[str, object] | None,
    principle_note: dict[str, object] | None,
    project_ideas: list[dict[str, object]],
    exercise_prompt: dict[str, object] | None,
) -> str:
    implementation_guide = implementation_guide or {}
    adaptation_guide = adaptation_guide or {}
    principle_note = principle_note or {}
    exercise_prompt = exercise_prompt or {}
    if scenario == "principle":
        value = principle_note.get("follow_up_exercise") or principle_note.get("apply_now")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if next_step_hint:
        return next_step_hint
    value = exercise_prompt.get("prompt")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if scenario == "idea_implementation":
        value = implementation_guide.get("current_step")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if scenario == "project_adaptation":
        value = adaptation_guide.get("first_migration_step")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if scenario == "project_idea" and project_ideas:
        value = project_ideas[0].get("first_step")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_next_step_hint_text(value: object | None) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("title", "label", "next_step", "nextStep", "summary"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


def _surface_context_text(text: str, *, chinese: bool) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    if not chinese:
        return cleaned
    if _looks_english_heavy(cleaned):
        return None
    return cleaned


def _looks_english_heavy(text: str) -> bool:
    alpha_count = sum(1 for char in text if char.isalpha() and char.isascii())
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return alpha_count > 8 and cjk_count == 0


def _append_unique_paragraphs(reply: str, additions: list[str]) -> str:
    resolved: list[str] = []
    for item in additions:
        cleaned = item.strip()
        if not cleaned:
            continue
        if _reply_mentions_excerpt(reply, cleaned):
            continue
        if any(_reply_mentions_excerpt(existing, cleaned) for existing in resolved):
            continue
        resolved.append(cleaned)
    if not resolved:
        return reply
    return f"{reply}\n\n" + "\n\n".join(resolved)


def _trim_sentence(text: str, limit: int) -> str:
    normalized = " ".join(text.split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _first_turn_guided_lane(scenario: str | None, learner_message: str) -> str:
    normalized = str(scenario or "").strip().lower()
    if normalized in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return normalized
    inferred_scenario = infer_coaching_scenario(
        learner_message,
        current_file=None,
        coach_context=None,
        default=normalized or "general",
    )
    if inferred_scenario in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return inferred_scenario
    inferred = _infer_guided_coaching_domain(
        learner_message,
        current_file=None,
        coach_context=None,
    )
    if inferred in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return inferred
    return normalized


def _resolve_first_turn_guided_lane(
    *,
    scenario: str | None,
    learner_message: str,
    reply: str,
) -> str:
    guided_lane = _first_turn_guided_lane(scenario, learner_message)
    if guided_lane in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return guided_lane
    inferred_from_reply = _infer_guided_coaching_domain(
        f"{learner_message}\n{reply}".strip(),
        current_file=None,
        coach_context=None,
    )
    if inferred_from_reply in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return inferred_from_reply
    return guided_lane


def _selection_function_symbol(selection_text: str) -> str | None:
    normalized = " ".join(str(selection_text or "").split())
    if not normalized:
        return None
    patterns = (
        r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(?:async\s*)?\(",
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match.group(1)
    return None


def _function_guidance_starter_reply_parts(
    coach_context: dict[str, Any] | None,
    *,
    chinese: bool,
) -> tuple[str, str]:
    if not isinstance(coach_context, dict):
        return "", ""
    starter = coach_context.get("function_guidance_starter")
    if not isinstance(starter, dict) or str(starter.get("status") or "").strip() != "ready":
        selection_text = str(coach_context.get("selection_text") or "").strip()
        file_path = _compact_text(coach_context.get("file_path"), 120)
        symbol = _selection_function_symbol(selection_text)
        if selection_text and file_path and symbol:
            if chinese:
                return (
                    f"我会先把这一轮锚定在当前文件 `{file_path}` 里的 `{symbol}` 上，再用 hover、signature help 和 definition 读稳它的 contract。",
                    f"下一步：留在 `{file_path}`，先围绕 `{symbol}` 说清 parameter contract 和 return contract，再决定要不要扩大解释。",
                )
            return (
                f"I will keep this anchored to `{symbol}` in the current file `{file_path}`, then use hover, signature help, and definition until the contract stops moving.",
                f"Next step: stay in `{file_path}`, read `{symbol}` from the current selection, and name the parameter contract and return contract before we widen the explanation.",
            )
        return "", ""
    call_site_path = _compact_text(starter.get("call_site_path"), 120) or "the prepared call site"
    definition_path = _compact_text(starter.get("definition_path"), 120) or "the prepared definition"
    symbol = (
        _compact_text(starter.get("definition_symbol"), 48)
        or _compact_text(starter.get("call_site_symbol"), 48)
        or "the prepared function"
    )
    if chinese:
        return (
            f"我会先把这一轮锚定在准备好的 live call site `{call_site_path}`，再用 hover、signature help 和 definition 读稳 `{symbol}` 的 contract。",
            f"下一步：打开 `{call_site_path}`，把光标放到 `{symbol}` 上，先看 hover 和 signature help，再跳到 `{definition_path}` 说清参数 contract 和返回 contract。",
        )
    return (
        f"I will keep this anchored to the prepared live call site in `{call_site_path}`, then use hover, signature help, and definition to read `{symbol}` with a stable contract.",
        f"Next step: open `{call_site_path}`, place the cursor on `{symbol}`, check hover and signature help, then jump to `{definition_path}` and name the parameter and return contract.",
    )


def _first_turn_lane_continuity_note(
    scenario: str,
    *,
    chinese: bool,
    coach_context: dict[str, Any] | None = None,
) -> str:
    if scenario == "remote_workspace":
        if chinese:
            return "我会继续把这一轮留在 VS Code remote 这条线上：先确认工作区边界和文件实际在哪台机器上，再收住一个最小验证动作。"
        return (
            "I will keep this in the VS Code remote lane: first prove the workspace boundary "
            "and where the files actually live, then line up one minimal verification move."
        )
    if scenario == "debug_loop":
        if chinese:
            return "我会先把这一轮收束成一个可信的 debug loop：先复现一次，在第一个有意义的 state change 停下，再检查一个值。"
        return (
            "I will keep this as one trustworthy debug loop: reproduce once, pause at the first "
            "meaningful state change, and inspect one value before we widen anything."
        )
    if scenario == "function_guidance":
        starter_note, _ = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=chinese,
        )
        if starter_note:
            return starter_note
        if chinese:
            return "我会先把函数理解锚定在一个 live call site 上，再用 hover、signature help 和 definition 把 contract 读稳。"
        return (
            "I will keep this anchored to one live call site, then use hover, signature help, "
            "and definition until the function contract stops moving."
        )
    if scenario == "project_adaptation":
        if chinese:
            return "我会先理解你的目标、项目语境和当前阻塞点，再分清现有项目里哪些必须稳定、哪些必须改变，然后落一个窄范围 adaptation。"
        return (
            "I will keep this in the existing-project lane: first separate what must stay stable "
            "from what must change, then land one narrow adaptation before we widen scope."
        )
    return ""

def _first_turn_lane_next_step(
    scenario: str,
    *,
    chinese: bool,
    coach_context: dict[str, Any] | None = None,
) -> str:
    if scenario == "remote_workspace":
        if chinese:
            return "下一步：先把工作区落点说清楚：告诉我当前工作区是 SSH、tunnels、dev container、WSL 还是 local，再给我一个 Explorer 路径、`pwd` 结果或 remote host 标签。"
        return (
            "Next step: give me one minimal verification move for the workspace boundary - tell "
            "me whether this workspace is SSH, tunnels, dev container, WSL, or local, then show "
            "one Explorer path, `pwd`, or remote host label."
        )
    if scenario == "debug_loop":
        if chinese:
            return "下一步：告诉我你准备先停在哪里，以及你准备先检查哪一个值、分支或 stack frame。"
        return (
            "Next step: tell me where you will pause first and which single value, branch, "
            "or stack frame you expect to inspect there."
        )
    if scenario == "function_guidance":
        _, starter_next_step = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=chinese,
        )
        if starter_next_step:
            return starter_next_step
        if chinese:
            return "下一步：给我函数名和一个你现在就能打开的 call site，我们再从那里读参数、返回值和上下文。"
        return (
            "Next step: give me the function name and one call site you can open right now, "
            "and we will read the parameters, return value, and context from there."
        )
    if scenario == "project_adaptation":
        if chinese:
            return "下一步：带回一个真实例子、片段或输入，告诉我哪个现有模块或行为必须稳定、哪一部分必须改变，以及你想先适配的第一道边界。"
        return (
            "Next step: tell me which existing module or behavior must stay stable, which part "
            "must change, and the first boundary you want to adapt."
        )
    return ""


def _fresh_lane_reanchor_reply(
    scenario: str,
    *,
    response_language: str | None = None,
    coach_context: dict[str, Any] | None = None,
) -> str:
    chinese = _prefers_chinese(response_language)
    guided_note = _first_turn_lane_continuity_note(
        scenario,
        chinese=chinese,
        coach_context=coach_context,
    )
    guided_close = _first_turn_lane_next_step(
        scenario,
        chinese=chinese,
        coach_context=coach_context,
    )
    return "\n\n".join(part for part in (guided_note, guided_close) if part.strip())


def _should_preserve_visible_reply(
    message: str,
    *,
    answer_mode: str | None,
    profile: UserProfile,
) -> bool:
    if normalize_answer_policy(answer_mode or profile.answer_policy) == "direct":
        return True

    normalized = " ".join(str(message or "").casefold().split())
    explicit_answer_markers = (
        "directly answer",
        "just answer",
        "only answer",
        "in three sentences",
        "in 3 sentences",
        "do not ask",
        "don't ask",
        "no next step",
        "without asking",
        "\u8bf7\u76f4\u63a5\u56de\u7b54",
        "\u53ea\u8981\u56de\u7b54",
        "\u4e09\u53e5\u8bdd",
        "\u4e0d\u8981\u5148\u95ee",
        "\u4e0d\u8981\u7ed9\u6211\u4e0b\u4e00\u6b65",
    )
    return any(marker in normalized for marker in explicit_answer_markers)


def _reply_needs_first_turn_reframe(reply: str) -> bool:
    stripped = reply.strip()
    if not stripped:
        return False

    paragraphs = [part.strip() for part in stripped.split("\n\n") if part.strip()]
    if len(paragraphs) >= 3:
        return True
    if len(stripped) >= 260:
        return True

    lowered = stripped.lower()
    structural_signals = ("```", "## ", "### ", "\n- ", "\n* ", "\n1. ", "\n2. ")
    if any(signal in lowered for signal in structural_signals):
        return True

    return False


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


def _has_repeated_failure_signal(
    learning_outcomes: list[dict[str, object]],
    pace_signal: str,
    learner_signal: str,
) -> bool:
    if pace_signal in {"fragile", "stalled", "recovery"}:
        return True
    if learner_signal == "blocked":
        return True
    repeated_markers = {
        "repeated_error",
        "blocked",
        "repeated_failure",
        "regression",
        "forgotten",
        "failed_review",
        "retry",
    }
    for item in learning_outcomes:
        outcome = str(item.get("outcome") or "").strip().lower()
        summary = str(item.get("summary") or "").strip().lower()
        if outcome in repeated_markers:
            return True
        if "failed twice" in summary or "repeated" in summary or "again" in summary:
            return True
    return False


def _strip_generic_lane_prompt_artifacts(
    reply: str,
    scenario: str,
    learner_message: str,
    chinese: bool,
) -> str:
    resolved_scenario = _resolve_first_turn_guided_lane(
        scenario=scenario,
        learner_message=learner_message,
        reply=reply,
    )
    if resolved_scenario not in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return reply

    generic_paragraphs = {
        "I will first understand your goal, project, and blocker, remember that context for the next turn, then decide whether to guide the code, explain the principle, or shape the training thread first.",
        "Tell me which lane is closest right now: implementing an idea, adapting a project, or shaping the training thread first.",
        "Tell me which lane is closest right now: implementing an idea, adapting an existing project, or shaping the training thread first.",
    }
    if chinese:
        generic_paragraphs.update(
            {
                "我会先理解你的目标、项目和阻塞点，记住这些上下文，再决定先带你改代码、讲原理，还是先整理训练线程。",
                "请告诉我现在最接近哪条线：实现一个想法、适配一个项目，还是先整理训练线程。",
                "请告诉我现在最接近哪条线：实现一个想法、适配现有项目，还是先整理训练线程。",
            }
        )

    paragraphs = [part.strip() for part in reply.split("\n\n") if part.strip()]
    filtered = [part for part in paragraphs if part not in generic_paragraphs]
    if len(filtered) == len(paragraphs):
        return reply
    return "\n\n".join(filtered).strip()


def _fresh_lane_comparison_requested(learner_message: str) -> bool:
    lowered = learner_message.casefold()
    markers = (
        "compare",
        "comparison",
        "difference",
        "different",
        "versus",
        "compared to",
        "对比",
        "区别",
        "相比",
    )
    return any(marker.casefold() in lowered for marker in markers)


def _fresh_lane_marker_map(*, chinese: bool) -> dict[str, tuple[str, ...]]:
    lane_markers: dict[str, tuple[str, ...]] = {
        "remote_workspace": (
            "remote lane",
            "remote workspace",
            "remote workflow",
            "ssh",
            "tunnels",
            "devcontainer",
            "dev container",
            "container",
            "wsl",
            "credential mode",
        ),
        "debug_loop": (
            "debug loop",
            "breakpoint",
            "launch.json",
            "call stack",
            "stack frame",
            "watch value",
        ),
        "function_guidance": (
            "function-guidance lane",
            "function contract",
            "live call site",
            "call site",
            "signature help",
            "go to definition",
        ),
        "project_adaptation": (
            "existing-project lane",
            "adaptation lane",
            "must stay stable",
            "must change",
        ),
    }
    if chinese:
        lane_markers["remote_workspace"] += (
            "\u8fdc\u7a0b",
            "\u8fdc\u7a0b\u5de5\u4f5c\u533a",
            "\u8fdc\u7a0b\u8fb9\u754c",
            "\u8fdc\u7a0b ssh",
            "\u5bb9\u5668",
            "\u5f00\u53d1\u5bb9\u5668",
            "\u96a7\u9053",
            "\u51ed\u636e\u6a21\u5f0f",
        )
        lane_markers["debug_loop"] += (
            "\u8c03\u8bd5",
            "\u8c03\u8bd5\u95ed\u73af",
            "\u65ad\u70b9",
            "\u8c03\u7528\u6808",
            "\u5355\u6b65",
            "\u53d8\u91cf\u503c",
        )
        lane_markers["function_guidance"] += (
            "\u51fd\u6570",
            "\u51fd\u6570\u5951\u7ea6",
            "\u8c03\u7528\u70b9",
            "\u8c03\u7528\u4f4d\u7f6e",
            "\u7b7e\u540d\u63d0\u793a",
            "\u67e5\u770b\u5b9a\u4e49",
        )
        lane_markers["project_adaptation"] += (
            "\u6539\u9020",
            "\u8fc1\u79fb",
            "\u9002\u914d",
        )
    return lane_markers


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


def _strip_fresh_lane_cross_lane_carryover(
    reply: str,
    *,
    scenario: str,
    learner_message: str,
    chinese: bool,
) -> str:
    if not reply.strip() or _fresh_lane_comparison_requested(learner_message):
        return reply

    lane_markers: dict[str, tuple[str, ...]] = {
        "remote_workspace": (
            "remote lane",
            "remote workspace",
            "remote workflow",
            "ssh",
            "tunnels",
            "devcontainer",
            "dev container",
            "container",
            "wsl",
            "credential mode",
        ),
        "debug_loop": (
            "debug loop",
            "breakpoint",
            "launch.json",
            "call stack",
            "stack frame",
            "watch value",
        ),
        "function_guidance": (
            "function-guidance lane",
            "function contract",
            "live call site",
            "call site",
            "signature help",
            "go to definition",
        ),
        "project_adaptation": (
            "existing-project lane",
            "adaptation lane",
            "must stay stable",
            "must change",
        ),
    }
    if chinese:
        lane_markers["remote_workspace"] += (
            "远程",
            "远程工作区",
            "远程边界",
            "远程 ssh",
            "容器",
            "开发容器",
            "隧道",
            "凭据模式",
        )
        lane_markers["debug_loop"] += (
            "调试",
            "断点",
            "调用栈",
            "单步",
            "变量值",
        )
        lane_markers["function_guidance"] += (
            "函数",
            "函数契约",
            "调用点",
            "调用位置",
            "签名提示",
            "查看定义",
        )
        lane_markers["project_adaptation"] += ("改造", "迁移", "适配")

    lane_markers = _fresh_lane_marker_map(chinese=chinese)

    bridge_markers = (
        "already were",
        "previous",
        "earlier",
        "same lane",
        "same line",
        "we were with",
        "coming out of",
        "fits where we already were",
        "keep circling",
        "keep circling back",
        "circling back",
        "keep coming back to",
        "from the debug loop",
        "from the remote lane",
        "沿着上一条",
        "上一条",
        "前一条",
        "刚才那条",
    )
    other_lane_markers = [
        marker
        for lane, markers in lane_markers.items()
        if lane != scenario
        for marker in markers
    ]
    if not other_lane_markers:
        return reply

    paragraphs = [part.strip() for part in reply.split("\n\n") if part.strip()]
    filtered: list[str] = []
    removed = False
    for part in paragraphs:
        lowered = part.casefold()
        mentions_other_lane = any(marker.casefold() in lowered for marker in other_lane_markers)
        has_bridge_cue = any(marker.casefold() in lowered for marker in bridge_markers)
        if mentions_other_lane and has_bridge_cue:
            removed = True
            continue
        filtered.append(part)

    if removed and filtered:
        reply = "\n\n".join(filtered).strip()
    elif removed:
        return reply

    sentence_filtered: list[str] = []
    sentence_removed = False
    for part in filtered:
        if "```" in part:
            sentence_filtered.append(part)
            continue
        kept_sentences: list[str] = []
        sentences = re.split(r"(?<=[.!?。！？])(?:\s+|(?=[^\s]))", part)
        for sentence in sentences:
            normalized = sentence.strip()
            if not normalized:
                continue
            lowered = normalized.casefold()
            mentions_other_lane = any(marker.casefold() in lowered for marker in other_lane_markers)
            if mentions_other_lane:
                sentence_removed = True
                continue
            kept_sentences.append(normalized)
        if kept_sentences:
            joiner = "" if chinese else " "
            sentence_filtered.append(joiner.join(kept_sentences).strip())

    if sentence_removed and sentence_filtered:
        return "\n\n".join(sentence_filtered).strip()
    return reply


def _sanitize_agentic_continuity_text(
    value: str,
    *,
    scenario: str,
    learner_message: str,
    chinese: bool,
    history_mode: str,
    field_kind: str = "summary",
    response_language: str | None = None,
    coach_context: dict[str, Any] | None = None,
    current_file: dict[str, object] | None = None,
) -> str:
    if field_kind == "resume_thread":
        text = _visible_model_text(value).strip()
    else:
        text = _strip_internal_coach_meta(value).strip()
    if not text:
        return text
    if _reply_needs_current_request_reanchor(
        text,
        message=learner_message,
        current_file=current_file,
        coach_context=coach_context,
    ):
        repaired = _reanchor_agentic_continuity_to_current_request(
            field_kind=field_kind,
            message=learner_message,
            current_file=current_file,
            response_language=response_language,
        )
        if repaired:
            return repaired
    if history_mode == "fresh_lane":
        text = _strip_fresh_lane_cross_lane_carryover(
            text,
            scenario=scenario,
            learner_message=learner_message,
            chinese=chinese,
        )
    resolved_scenario = _resolve_first_turn_guided_lane(
        scenario=scenario,
        learner_message=learner_message,
        reply=text,
    )
    active_view = _coaching_active_view_name(coach_context)
    active_view_override = (
        _build_active_view_recovery_override(
            active_view=active_view,
            response_language=response_language,
            reason="reanchor",
        )
        if active_view
        else None
    )
    if isinstance(active_view_override, dict):
        if field_kind == "summary" and _structured_view_summary_needs_repair(
            text,
            active_view=active_view,
            chinese=chinese,
            learner_message=learner_message,
            current_file=current_file,
        ):
            override_summary = str(active_view_override.get("summary") or "").strip()
            if override_summary:
                return override_summary
        if field_kind == "next_step" and _structured_view_next_step_needs_repair(
            text,
            active_view=active_view,
            chinese=chinese,
            learner_message=learner_message,
            current_file=current_file,
        ):
            override_next_step = str(active_view_override.get("next_step") or "").strip()
            if override_next_step:
                return override_next_step
    if field_kind == "summary" and resolved_scenario in _GUIDED_DOMAIN_SCENARIOS:
        repaired_summary = _first_turn_lane_continuity_note(
            resolved_scenario,
            chinese=chinese,
            coach_context=coach_context,
        )
        if repaired_summary and _guided_lane_summary_needs_repair(
            text,
            scenario=resolved_scenario,
            chinese=chinese,
        ):
            text = repaired_summary
    if field_kind == "next_step" and resolved_scenario in _GUIDED_DOMAIN_SCENARIOS:
        repaired_next_step = _first_turn_lane_next_step(
            resolved_scenario,
            chinese=chinese,
            coach_context=coach_context,
        )
        if repaired_next_step and _guided_lane_next_step_needs_repair(
            text,
            scenario=resolved_scenario,
            chinese=chinese,
        ):
            text = repaired_next_step
    if _looks_like_generic_guided_review_fallback(text):
        if resolved_scenario in _GUIDED_DOMAIN_SCENARIOS:
            repaired_summary = _first_turn_lane_continuity_note(
                resolved_scenario,
                chinese=chinese,
                coach_context=coach_context,
            )
            repaired_next_step = _first_turn_lane_next_step(
                resolved_scenario,
                chinese=chinese,
                coach_context=coach_context,
            )
            if field_kind == "next_step" and repaired_next_step:
                text = repaired_next_step
            elif field_kind == "resume_thread" and (repaired_summary or repaired_next_step):
                text = _agentic_resume_thread_text(
                    repaired_summary,
                    repaired_next_step,
                    response_language=response_language or ("zh-CN" if chinese else "en-US"),
                )
            elif repaired_summary:
                text = repaired_summary
    return text


def _normalize_visible_resume_thread_text(text: str, *, chinese: bool) -> str:
    normalized = _strip_internal_coach_meta(text).strip()
    if not normalized:
        return ""
    if chinese:
        prefixes = (
            "回到同一条教练线程：",
            "沿着当前主线继续：",
            "继续当前主线。",
            "沿着同一条线继续。",
        )
        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                break
        normalized = re.sub(r"(下一步[:：]\s*){2,}", "下一步：", normalized)
        return normalized.strip()
    english_prefixes = (
        "Resume the live thread around ",
        "Resume the live thread. ",
        "Stay on that same thread: ",
    )
    lowered = normalized.casefold()
    for prefix in english_prefixes:
        if lowered.startswith(prefix.casefold()):
            normalized = normalized[len(prefix) :].strip()
            lowered = normalized.casefold()
            break
    normalized = re.sub(
        r"(?i)(next(?: step)?:\s*)(next(?: step)?:\s*)+",
        lambda match: match.group(1),
        normalized,
    )
    return normalized.strip()


def _looks_like_generic_guided_review_fallback(text: str) -> bool:
    normalized = " ".join(text.split()).strip().casefold()
    if not normalized:
        return False
    generic_fallbacks = (
        "ignore secondary issues and only name the first fix plus one verification.",
        "ignore secondary issues and only describe the first fix plus one verification.",
    )
    return any(fragment in normalized for fragment in generic_fallbacks)

def _reply_has_guided_lane_signal(reply: str, scenario: str, chinese: bool) -> bool:
    if not reply.strip():
        return False

    lowered = reply.casefold()
    english_markers: dict[str, tuple[str, ...]] = {
        "remote_workspace": (
            "vs code remote lane",
            "workspace boundary",
            "credential mode",
            "files actually live",
            "credential move",
        ),
        "debug_loop": (
            "trustworthy debug loop",
            "breakpoint",
            "state change",
            "pause at the first",
            "single value",
        ),
        "function_guidance": (
            "live call site",
            "signature help",
            "function contract",
            "hover",
            "go to definition",
        ),
        "project_adaptation": (
            "existing-project lane",
            "must stay stable",
            "must change",
            "narrow adaptation",
        ),
    }
    chinese_markers: dict[str, tuple[str, ...]] = {
        "remote_workspace": (
            "VS Code remote",
            "工作区边界",
            "credential mode",
            "API key",
            "文件实际在哪台机器",
        ),
        "debug_loop": (
            "debug loop",
            "断点",
            "state change",
            "调用栈",
            "stack frame",
        ),
        "function_guidance": (
            "live call site",
            "signature help",
            "function contract",
            "hover",
            "definition",
        ),
        "project_adaptation": (
            "project adaptation",
            "必须稳定",
            "必须改变",
            "适配",
            "边界",
        ),
    }
    markers = english_markers.get(scenario, ())
    if chinese:
        markers = markers + chinese_markers.get(scenario, ())
    return any(marker.casefold() in lowered for marker in markers)


def _guided_lane_summary_needs_repair(text: str, *, scenario: str, chinese: bool) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    lowered = normalized.casefold()
    if lowered.startswith("next step:") or lowered.startswith("next:"):
        return True
    if normalized.startswith(("下一步：", "下一步:")):
        return True
    ascii_tokens = re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", normalized)
    if ascii_tokens and len(ascii_tokens) <= 5:
        return True
    if not _reply_has_guided_lane_signal(normalized, scenario, chinese):
        return True
    if ascii_tokens and len(ascii_tokens) <= 8 and not any(char in normalized for char in ".!?。！？"):
        return True
    return len(normalized) <= (8 if chinese else 14)


def _guided_lane_next_step_needs_repair(text: str, *, scenario: str, chinese: bool) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    normalized_search = _normalize_search_text(normalized)
    if scenario == "function_guidance":
        if "functionnameandonecallsiteyoucanopenrightnow" in normalized_search:
            return True
        if "给我函数名和一个你现在就能打开的callsite" in normalized_search:
            return True
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if chinese and not any("\u4e00" <= char <= "\u9fff" for char in normalized):
        return True
    if len(normalized) > 110:
        return True
    if normalized.count("。") + normalized.count(". ") + normalized.count("! ") + normalized.count("? ") >= 2:
        return True
    return False


def _structured_view_lane_markers(*, active_view: str, chinese: bool) -> tuple[str, ...]:
    english_markers: dict[str, tuple[str, ...]] = {
        "plan": (
            "planlane",
            "formalplan",
            "currentstage",
            "whynow",
            "verifymethod",
            "evidence",
            "blocker",
        ),
        "resources": (
            "resourceslane",
            "resourcelane",
            "resource",
            "sandbox",
            "library",
            "folder",
            "file",
            "sources",
            "knowledge",
            "cards",
            "download",
            "organize",
        ),
        "training": (
            "traininglane",
            "learn",
            "try",
            "verify",
            "reflect",
            "return",
            "currentcard",
            "card",
            "answer",
            "deliverable",
            "whynow",
        ),
        "settings": (
            "settingslane",
            "settings",
            "provider",
            "model",
            "protocol",
            "runtime",
            "apikey",
            "connection",
        ),
    }
    chinese_markers: dict[str, tuple[str, ...]] = {
        "plan": ("plan视图", "正式计划", "当前阶段", "whynow", "verifymethod", "证据", "阻塞"),
        "resources": ("resources视图", "资料库", "资源", "沙箱", "目录", "文件", "sources", "knowledge", "cards"),
        "training": ("training视图", "训练", "学习", "单卡", "作答", "验证", "复盘", "回流", "whynow"),
        "settings": ("settings视图", "设置", "provider", "model", "protocol", "runtime", "apikey"),
    }
    markers = english_markers.get(active_view, ())
    if chinese:
        markers = markers + chinese_markers.get(active_view, ())
    return markers


def _structured_view_has_lane_signal(text: str, *, active_view: str, chinese: bool) -> bool:
    normalized = _normalize_search_text(text)
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in _structured_view_lane_markers(active_view=active_view, chinese=chinese)
    )


def _structured_view_summary_needs_repair(
    text: str,
    *,
    active_view: str,
    chinese: bool,
    learner_message: str | None = None,
    current_file: dict[str, object] | None = None,
) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    if _reply_mentions_current_request_anchor(
        normalized,
        message=learner_message,
        current_file=current_file,
    ):
        return False
    lowered = normalized.casefold()
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if lowered.startswith("next step:") or lowered.startswith("next:"):
        return True
    if normalized.startswith(("下一步：", "下一步:")):
        return True
    if not _structured_view_has_lane_signal(normalized, active_view=active_view, chinese=chinese):
        return True
    return len(normalized) <= (10 if chinese else 18)


def _structured_view_next_step_needs_repair(
    text: str,
    *,
    active_view: str,
    chinese: bool,
    learner_message: str | None = None,
    current_file: dict[str, object] | None = None,
) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    if _reply_mentions_current_request_anchor(
        normalized,
        message=learner_message,
        current_file=current_file,
    ):
        return False
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if not _structured_view_has_lane_signal(normalized, active_view=active_view, chinese=chinese):
        return True
    return len(normalized) <= (10 if chinese else 18)


def _structured_view_visible_reply_needs_repair(
    text: str,
    *,
    active_view: str,
    chinese: bool,
    learner_message: str | None = None,
    current_file: dict[str, object] | None = None,
) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    if _reply_mentions_current_request_anchor(
        normalized,
        message=learner_message,
        current_file=current_file,
    ):
        return False
    if active_view == "training":
        return False
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if _structured_view_has_lane_signal(normalized, active_view=active_view, chinese=chinese):
        return False
    normalized_search = _normalize_search_text(normalized)
    stale_markers: dict[str, tuple[str, ...]] = {
        "plan": (
            "codemechanism",
            "patch",
            "branch",
            "breakage",
            "callsite",
            "signaturehelp",
            "hover",
            "debugloop",
        ),
        "resources": (
            "codemechanism",
            "patch",
            "branch",
            "breakage",
            "debugloop",
            "signaturehelp",
            "formalplan",
        ),
        "settings": (
            "patch",
            "branch",
            "breakage",
            "callsite",
            "debugloop",
            "formalplan",
        ),
    }
    if any(marker in normalized_search for marker in stale_markers.get(active_view, ())):
        return True
    # A structured-view reply does not need to repeat the view's internal
    # vocabulary to be valid.  Once the provider has returned a substantive
    # answer, preserve it; only very short acknowledgements remain eligible
    # for the local lane-recovery copy above.
    return len(normalized) <= (12 if chinese else 18)

def _reply_mentions_excerpt(reply: str, source: str) -> bool:
    excerpt = _search_excerpt(source)
    if not excerpt:
        return False
    return _normalize_search_text(excerpt) in _normalize_search_text(reply)


def _search_excerpt(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return ""
    if any("\u4e00" <= char <= "\u9fff" for char in cleaned):
        compact = "".join(
            char for char in cleaned if ("\u4e00" <= char <= "\u9fff") or char.isascii() and char.isalnum()
        )
        return compact[:12]
    words = cleaned.split(" ")
    return " ".join(words[:6])[:48]


def _normalize_search_text(text: str) -> str:
    return "".join(
        char.casefold()
        for char in text
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    )


_REQUEST_ANCHOR_CODE_PATTERN = re.compile(r"`([^`\n]{2,80})`")
_REQUEST_ANCHOR_QUOTED_PATTERN = re.compile(r"[\"']([^\"'\n]{2,80})[\"']")
_REQUEST_ANCHOR_IDENTIFIER_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_./-]{1,}\b")
_REQUEST_ANCHOR_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]{2,}")
_REQUEST_ANCHOR_STOP_WORDS = frozenset(
    {
        "about",
        "answer",
        "because",
        "current",
        "directly",
        "does",
        "explain",
        "file",
        "help",
        "issue",
        "please",
        "problem",
        "question",
        "return",
        "returns",
        "step",
        "that",
        "the",
        "this",
        "typescript",
        "javascript",
        "python",
        "fastapi",
        "trainer",
        "what",
        "when",
        "why",
        "with",
    }
)
_STALE_VISIBLE_REPLY_MARKERS = (
    "current lane:",
    "i will keep this turn inside",
    "keep the work alive inside",
    "resume the live thread",
    "which lane is closest",
    "stay inside the formal plan lane",
    "stay inside the resource lane",
    "stay inside the configuration lane",
    "ignore secondary issues and only",
    "\u5f53\u524d\u5148\u7559\u5728",
    "\u8fd9\u4e00\u8f6e\u6211\u5148\u5728",
    "\u56de\u5230\u540c\u4e00\u6761\u6559\u7ec3\u7ebf\u7a0b",
    "\u8bf7\u544a\u8bc9\u6211\u73b0\u5728\u6700\u63a5\u8fd1\u54ea\u6761\u7ebf",
    "\u5148\u7559\u5728\u6b63\u5f0f\u8ba1\u5212",
    "\u5148\u7559\u5728\u8d44\u6599\u5e93",
    "\u5148\u7559\u5728\u914d\u7f6e",
)
_GENERIC_COMPLETION_MARKERS = (
    "next step",
    "continue",
    "completed",
    "keep going",
    "\u4e0b\u4e00\u6b65",
    "\u7ee7\u7eed",
    "\u5b8c\u6210",
)


def _clean_request_anchor_candidate(value: object | None) -> str:
    candidate = " ".join(str(value or "").split()).strip(" `\"'")
    if not candidate:
        return ""
    return candidate[:80]


def _request_relevance_anchor_terms(
    message: str | None,
    *,
    current_file: dict[str, object] | None = None,
) -> list[str]:
    """Extract user-visible nouns that a recovery reply can safely keep in view."""
    source = str(message or "")
    if not source.strip():
        return []

    candidates: list[str] = []
    candidates.extend(match.group(1) for match in _REQUEST_ANCHOR_CODE_PATTERN.finditer(source))
    candidates.extend(match.group(1) for match in _REQUEST_ANCHOR_QUOTED_PATTERN.finditer(source))
    has_explicit_subject = bool(candidates)
    for token_match in _REQUEST_ANCHOR_IDENTIFIER_PATTERN.finditer(source):
        token = token_match.group(0).strip()
        lowered = token.casefold()
        looks_specific = (
            bool(re.search(r"[a-z][A-Z]", token))
            or "_" in token
            or "." in token
            or "/" in token
            or "-" in token
        )
        if looks_specific and lowered not in _REQUEST_ANCHOR_STOP_WORDS:
            candidates.append(token)
            has_explicit_subject = True

    if has_explicit_subject:
        for cjk_match in _REQUEST_ANCHOR_CJK_PATTERN.finditer(source):
            phrase = cjk_match.group(0)
            phrase = re.sub(
                r"^(?:\u8bf7|\u5e2e\u6211|\u8bf7\u95ee|\u4e3a\u4ec0\u4e48|\u600e\u4e48|\u5982\u4f55|"
                r"\u89e3\u91ca|\u544a\u8bc9\u6211|\u9047\u5230|\u5173\u4e8e|\u5f53\u524d|\u8fd9\u4e2a|\u73b0\u5728)+",
                "",
                phrase,
            )
            if len(phrase) >= 2:
                candidates.append(phrase[:12])

    normalized_source = source.casefold()
    references_current_file = any(
        marker in normalized_source
        for marker in ("current file", "this file", "\u5f53\u524d\u6587\u4ef6", "\u8fd9\u4e2a\u6587\u4ef6", "\u5f53\u524d\u4ee3\u7801")
    )
    if isinstance(current_file, dict) and (has_explicit_subject or references_current_file):
        raw_path = _clean_request_anchor_candidate(current_file.get("path"))
        if raw_path:
            candidates.append(raw_path.replace("\\", "/").rsplit("/", 1)[-1])
        selection = _clean_request_anchor_candidate(current_file.get("selection_text"))
        if selection:
            candidates.extend(
                match.group(0)
                for match in _REQUEST_ANCHOR_IDENTIFIER_PATTERN.finditer(selection)
                if (
                    any(char.isupper() for char in match.group(0))
                    or "_" in match.group(0)
                    or len(match.group(0)) >= 8
                )
            )

    terms: list[str] = []
    seen: set[str] = set()
    for raw_candidate in candidates:
        candidate = _clean_request_anchor_candidate(raw_candidate)
        normalized = _normalize_search_text(candidate)
        if not normalized or normalized in seen:
            continue
        ascii_count = sum(char.isascii() and char.isalnum() for char in candidate)
        cjk_count = sum("\u3400" <= char <= "\u9fff" for char in candidate)
        if ascii_count < 3 and cjk_count < 2:
            continue
        seen.add(normalized)
        terms.append(candidate)
        if len(terms) >= 5:
            break
    return terms


def _reply_mentions_current_request_anchor(
    reply: str,
    *,
    message: str | None,
    current_file: dict[str, object] | None = None,
) -> bool:
    normalized_reply = _normalize_search_text(reply)
    if not normalized_reply:
        return False
    return any(
        (normalized_term := _normalize_search_text(term)) and normalized_term in normalized_reply
        for term in _request_relevance_anchor_terms(message, current_file=current_file)
    )


def _reply_mentions_unrequested_lane(reply: str, *, message: str | None) -> bool:
    normalized_reply = _normalize_search_text(reply)
    normalized_request = _normalize_search_text(str(message or ""))
    if not normalized_reply or not normalized_request:
        return False
    for markers in _fresh_lane_marker_map(chinese=True).values():
        normalized_markers = [
            _normalize_search_text(marker)
            for marker in markers
            if _normalize_search_text(marker)
        ]
        if any(marker in normalized_reply for marker in normalized_markers) and not any(
            marker in normalized_request for marker in normalized_markers
        ):
            return True
    return False


def _reply_needs_current_request_reanchor(
    reply: str,
    *,
    message: str | None,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> bool:
    resolved_guided_scenario = _resolve_first_turn_guided_lane(
        scenario=str((coach_context or {}).get("scenario") or "").strip(),
        learner_message=str(message or ""),
        reply=reply,
    )
    if resolved_guided_scenario in _GUIDED_DOMAIN_SCENARIOS:
        return False
    if not _request_relevance_anchor_terms(message, current_file=current_file):
        return False
    if _reply_mentions_current_request_anchor(
        reply,
        message=message,
        current_file=current_file,
    ):
        return False

    normalized = " ".join(reply.split()).strip().casefold()
    if not normalized:
        return False
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if any(marker.casefold() in normalized for marker in _STALE_VISIBLE_REPLY_MARKERS):
        return True
    if _reply_mentions_unrequested_lane(reply, message=message):
        return True

    active_view = _coaching_active_view_name(coach_context)
    if active_view:
        chinese = _contains_cjk(reply) or _contains_cjk(str(message or ""))
        reply_has_active_view_signal = _structured_view_has_lane_signal(
            reply,
            active_view=active_view,
            chinese=chinese,
        )
        request_has_active_view_signal = _structured_view_has_lane_signal(
            str(message or ""),
            active_view=active_view,
            chinese=chinese,
        )
        if reply_has_active_view_signal and not request_has_active_view_signal:
            return True
    return len(normalized) <= 160 and any(
        marker in normalized for marker in _GENERIC_COMPLETION_MARKERS
    )


def _format_request_anchor(term: str) -> str:
    cleaned = _clean_request_anchor_candidate(term)
    if not cleaned:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_./-]+", cleaned):
        return f"`{cleaned}`"
    return f"\u300c{cleaned}\u300d"


def _current_request_anchor_label(
    message: str | None,
    *,
    current_file: dict[str, object] | None,
) -> str:
    terms = _request_relevance_anchor_terms(message, current_file=current_file)
    formatted = [_format_request_anchor(term) for term in terms[:2]]
    return "\u3001".join(term for term in formatted if term)


def _relevance_reanchor_next_step(
    *,
    message: str | None,
    current_file: dict[str, object] | None,
    response_language: str | None,
) -> str:
    anchor = _current_request_anchor_label(message, current_file=current_file)
    path = ""
    if isinstance(current_file, dict):
        path = _clean_request_anchor_candidate(current_file.get("path"))
        if path:
            path = path.replace("\\", "/").rsplit("/", 1)[-1]
    if _prefers_chinese(response_language):
        if path:
            return (
                f"\u4e0b\u4e00\u6b65\uff1a\u56f4\u7ed5 {anchor} \uff0c\u5148\u5728 `{path}` \u91cc\u67e5\u770b\u4e0e\u8fd9\u4e2a\u95ee\u9898\u76f4\u63a5\u76f8\u8fde\u7684"
                "\u8f93\u5165\u3001\u5206\u652f\u6216\u8c03\u7528\uff0c\u5e26\u56de\u7b2c\u4e00\u6761\u5b9e\u9645\u8f93\u51fa\u6216\u62a5\u9519\u3002"
            )
        return f"\u4e0b\u4e00\u6b65\uff1a\u56f4\u7ed5 {anchor} \u5e26\u56de\u6700\u5c0f\u7684\u4ee3\u7801\u7247\u6bb5\u3001\u8f93\u5165\u8f93\u51fa\u6216\u62a5\u9519\uff0c\u6211\u4f1a\u53ea\u56f4\u7ed5\u8fd9\u4e2a\u70b9\u7ee7\u7eed\u3002"
    if path:
        return (
            f"Next step: stay with {anchor} and inspect the input, branch, or call directly connected to it in `{path}`, "
            "then bring back the first real output or error."
        )
    return (
        f"Next step: stay with {anchor}; bring back the smallest code fragment, input/output pair, or error, "
        "and I will stay on this exact question."
    )


def _relevance_reanchor_visible_reply(
    *,
    message: str | None,
    current_file: dict[str, object] | None,
    response_language: str | None,
) -> str:
    anchor = _current_request_anchor_label(message, current_file=current_file)
    if not anchor:
        return ""
    next_step = _relevance_reanchor_next_step(
        message=message,
        current_file=current_file,
        response_language=response_language,
    )
    if _prefers_chinese(response_language):
        return (
            f"\u6211\u5148\u56de\u5230\u4f60\u521a\u624d\u95ee\u7684 {anchor}\uff0c\u4e0d\u628a\u5b83\u5e26\u56de\u524d\u4e00\u6761\u4e3b\u7ebf\u3002\n\n"
            f"{next_step}"
        )
    return (
        f"I will return to your question about {anchor} instead of pulling this turn back to an earlier lane.\n\n"
        f"{next_step}"
    )


def _reanchor_visible_reply_to_current_request(
    reply: str,
    *,
    message: str | None,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> str:
    if not _reply_needs_current_request_reanchor(
        reply,
        message=message,
        current_file=current_file,
        coach_context=coach_context,
    ):
        return reply
    repaired = _relevance_reanchor_visible_reply(
        message=message,
        current_file=current_file,
        response_language=response_language,
    )
    return repaired or reply


def _reanchor_agentic_continuity_to_current_request(
    *,
    field_kind: str,
    message: str | None,
    current_file: dict[str, object] | None,
    response_language: str | None,
) -> str:
    anchor = _current_request_anchor_label(message, current_file=current_file)
    if not anchor:
        return ""
    next_step = _relevance_reanchor_next_step(
        message=message,
        current_file=current_file,
        response_language=response_language,
    )
    if _prefers_chinese(response_language):
        summary = f"\u5f53\u524d\u95ee\u9898\uff1a{anchor}\u3002"
        if field_kind == "summary":
            return summary
        if field_kind == "next_step":
            return next_step
        return f"{summary}\n\n{next_step}"
    summary = f"Current request: {anchor}."
    if field_kind == "summary":
        return summary
    if field_kind == "next_step":
        return next_step
    return f"{summary} {next_step}"


def _is_meta_step_hint(text: str) -> bool:
    normalized = _normalize_coach_meta_candidate(text)
    if not normalized:
        return False
    lowered = normalized.casefold()
    return (
        lowered.startswith("review rhythm:")
        or lowered.startswith("current coaching focus:")
        or lowered.startswith("\u590d\u4e60\u8282\u594f\uff1a")
        or lowered.startswith("\u5f53\u524d\u805a\u7126\uff1a")
        or _looks_like_internal_coach_meta(normalized)
    )


def _contains_meta_coach_context(text: str) -> bool:
    return _looks_like_internal_coach_meta(text)


def _provider_service_onboarding_reply(self, response_language: str | None = None) -> str:
    if _prefers_chinese(response_language):
        return (
            "先别急着直接上方案。第一轮我更想先把你的目标、项目语境和你更适合的带法对齐起来。\n\n"
            "你可以直接告诉我你现在手上的项目、想学到哪一步、卡在哪里，我会把这些判断记住，后面继续沿着同一条线带你，不会每一轮都重开。\n\n"
            "你现在更需要我带你做哪一类：实现一个 idea、改造现有项目，还是先把训练主线和节奏定下来？"
        )
    return (
        "Let's not jump straight into a solution. On the first turn I want to line up the few things that matter most: "
        "your goal, the project context, and how you prefer to be coached.\n\n"
        "Tell me what you are working on, where you want to get to, and where the thread feels unstable right now. "
        "I will remember that context so the next turn can continue the same lane instead of restarting.\n\n"
        "Which lane is closest right now: implement an idea, adapt a project, or shape the training thread first?"
    )


def _provider_service_error_reply(self, exc: Exception, response_language: str | None = None) -> str:
    detail = redact_provider_error(exc, api_key=self._api_key)
    if _prefers_chinese(response_language):
        return (
            "连接教练服务时遇到了一点问题，所以这一轮我先用本地教练逻辑把你接住。"
            f" 这次的错误是：{detail}。"
        )
    return (
        "I hit an issue connecting to the coach service, so I am keeping this turn moving locally. "
        f"The error was: {detail}."
    )


def _provider_service_missing_api_key_reply(
    self,
    response_language: str | None = None,
) -> str:
    if _prefers_chinese(response_language):
        return (
            "还没有设置可用的 API 密钥。"
            "请到设置里填写模型服务和密钥，然后就可以开始对话。"
        )
    return (
        "Trainer cannot start working yet because there is no usable API key. "
        "Open Settings, save a provider, model, and API key, and I can continue from there."
    )


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


def _clean_guided_domain_empty_reply(
    domain: str | None,
    *,
    response_language: str | None,
    coach_context: dict[str, Any] | None = None,
) -> str:
    if domain == "remote_workspace":
        return _localized_text(
            (
                "Remote work gets easier once the workspace boundary stops moving. "
                "Stay in the VS Code remote lane for one more turn: identify whether this workspace is SSH, "
                "tunnels, dev container, WSL, or local, then verify which machine owns the files and whether "
                "the API key should stay local or remote. Return in 2 short lines: one real workspace label or "
                "path, and one sentence about the safe credential mode."
            ),
            (
                "先把工作区边界说清楚，remote 才会变简单。继续留在 VS Code remote 这条线上："
                "先确认当前是 SSH、tunnels、dev container、WSL 还是 local，再确认文件实际在哪台机器上，"
                "以及 API key 应该留在 local 还是 remote。请用 2 行回复：第一行给一个真实的工作区标签或路径，"
                "第二行给一个安全 credential mode 的判断。"
            ),
            response_language,
        )
    if domain == "debug_loop":
        return _localized_text(
            (
                "Keep this in one trustworthy VS Code debug loop. Reproduce once, pause at the first meaningful "
                "state change, and inspect one value, branch, or stack frame before widening the story. Return in "
                "2 short lines: where you will pause first, and what single thing you expect to inspect there."
            ),
            (
                "先把这一轮收束成一个可信的 VS Code debug loop。先复现一次，在第一个有意义的 state change 停下，"
                "再检查一个 value、branch 或 stack frame，不要先把叙述铺开。请用 2 行回复：第一行写你准备停在哪里，"
                "第二行写你准备先检查哪一个点。"
            ),
            response_language,
        )
    if domain == "function_guidance":
        starter_note, starter_next_step = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=_prefers_chinese(response_language),
        )
        if starter_note or starter_next_step:
            return "\n\n".join(part for part in (starter_note, starter_next_step) if part.strip())
        return _localized_text(
            (
                "Keep this in the function-guidance lane. Start from one live call site, then use hover, "
                "signature help, and definition in that order until the contract stops moving. Return in 2 short "
                "lines: the function name, and the call site or evidence that proves what the function expects."
            ),
            (
                "先把这一轮留在 function guidance 这条线上。先从一个 live call site 开始，再按顺序用 hover、"
                "signature help、definition 把 contract 读稳。请用 3 行回复：第一行写函数名，第二行写你看的 "
                "call site，第三行写能证明它期望什么的 contract 证据。"
            ),
            response_language,
        )
    if domain == "project_adaptation":
        return _localized_text(
            (
                "Keep this in the existing-project adaptation lane. First separate what must stay stable from what "
                "must change, then land one narrow adaptation before widening scope. Return in 3 short lines: one "
                "stable behavior you must keep, one thing that must change, and the first boundary you want to adapt."
            ),
            (
                "先把这一轮留在现有项目 adaptation 这条线上。先分清哪些必须保持不变、哪些必须改变，"
                "再先落一个窄范围 adaptation，不要一开始就铺大。请用 3 行回复：第一行写必须保持不变的行为，"
                "第二行写必须改变的目标，第三行写你想先适配的第一条边界。"
            ),
            response_language,
        )
    return ""


def _clean_guided_domain_empty_reply_override(
    domain: str | None,
    *,
    response_language: str | None,
    coach_context: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    if domain == "remote_workspace":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the VS Code remote lane.",
                "provider 没有返回可见内容，所以我先把这一轮继续留在 VS Code remote 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Return one real workspace label or path and one sentence about the safe credential mode.",
                "请返回一个真实的工作区标签或路径，再补一句安全 credential mode 的判断。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Keep the lesson grounded in the real workspace boundary before widening the remote story.",
                "先把真实工作区边界说稳，再展开 remote 细节。",
                response_language,
            ),
        }
    if domain == "debug_loop":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the VS Code debug lane.",
                "provider 没有返回可见内容，所以我先把这一轮收束在 VS Code debug 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Tell me where you will pause first and which single value, branch, or stack frame you expect to inspect there.",
                "请告诉我你准备先停在哪里，以及你准备先检查哪一个 value、branch 或 stack frame。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Pause at one meaningful state change before widening the debug story.",
                "先在一个有意义的 state change 停下，再展开 debug 叙述。",
                response_language,
            ),
        }
    if domain == "function_guidance":
        starter_note, starter_next_step = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=_prefers_chinese(response_language),
        )
        if starter_note or starter_next_step:
            return {
                "summary": starter_note or "",
                "next_step": starter_next_step or "",
                "teaching_note": starter_note or "",
            }
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the function-guidance lane.",
                "provider 没有返回可见内容，所以我先把这一轮留在 function guidance 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Return the function name and one call site that proves what the function expects.",
                "请返回函数名、一个 call site，以及能证明它期望什么的 contract 证据。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Keep the contract anchored to one live call site before widening the explanation.",
                "先把 contract 锚定在一个 live call site 上，再展开解释。",
                response_language,
            ),
        }
    if domain == "project_adaptation":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the existing-project adaptation lane.",
                "provider 没有返回可见内容，所以我先把这一轮留在现有项目 adaptation 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Tell me what must stay stable, what must change, and the first boundary you want to adapt.",
                "请告诉我什么必须保持不变、什么必须改变，以及你想先适配的第一条边界。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Separate stable behavior from change scope before widening the adaptation plan.",
                "先分清稳定面和变更面，再扩大 adaptation 计划。",
                response_language,
            ),
        }
    return None


def _build_empty_reply_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, object]:
    domain_override = _guided_domain_empty_reply_override(
        message,
        current_file=current_file,
        coach_context=coach_context,
        response_language=response_language,
    )
    summary = str(domain_override.get("summary") or "").strip() if isinstance(domain_override, dict) else ""
    next_step = str(domain_override.get("next_step") or "").strip() if isinstance(domain_override, dict) else ""
    teaching_note = (
        str(domain_override.get("teaching_note") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    if not summary:
        summary = _localized_text(
            "The provider returned an empty visible answer.",
            "provider 没有返回可见内容。",
            response_language,
        )
    if not next_step:
        next_step = _localized_text(
            "Retry with a visible conclusion.",
            "先返回一个可见结论：目标行为、当前判断，以及下一步最小可验证动作。",
            response_language,
        )
    if not teaching_note:
        teaching_note = _localized_text(
            "Keep the same lane and ask for one visible, verifiable conclusion on the next turn.",
            "继续沿着同一条教学线走，下一轮先拿回一个可见且可验证的结论。",
            response_language,
        )
    resume_thread = _agentic_resume_thread_text(
        summary,
        next_step,
        response_language=response_language,
    )
    return {
        "summary": summary,
        "next_step": next_step,
        "blocker": summary,
        "teaching_note": teaching_note,
        "resume_thread": resume_thread,
        "stop_reason": "empty_response",
        "fell_back": True,
    }


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


def _timeout_focus_seed(
    message: str,
    *,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> str:
    chinese = response_language == "zh-CN"
    candidates: list[object] = []
    if isinstance(coach_context, dict):
        scenario = str(coach_context.get("scenario") or "").strip().lower()
        history_mode = str(coach_context.get("history_mode") or "").strip().lower()
        prefer_message_first = history_mode == "fresh_lane" or scenario in {"", "general"}
        if prefer_message_first:
            candidates.append(message)
        candidates.extend(
            [
                coach_context.get("current_focus"),
                coach_context.get("currentFocus"),
                coach_context.get("thread_summary"),
                coach_context.get("threadSummary"),
                coach_context.get("summary"),
            ]
        )
        if not prefer_message_first:
            candidates.append(message)
    else:
        candidates.append(message)
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        cleaned = " ".join(candidate.strip().split())
        if not cleaned:
            continue
        return _trim_sentence(cleaned, 28 if chinese else 96)
    return ""


def _looks_code_or_tooling_focus(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    return classify_learning_subject(lowered).family == "code"


def _general_recovery_focus_and_subject(
    message: str,
    *,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
):
    focus = _timeout_focus_seed(
        message,
        coach_context=coach_context,
        response_language=response_language,
    )
    if not focus:
        return None, None
    subject = classify_learning_subject(
        focus,
        message,
    )
    return focus, subject


def _build_active_view_recovery_override(
    *,
    active_view: str | None,
    response_language: str | None,
    reason: str,
) -> dict[str, str] | None:
    normalized = str(active_view or "").strip().lower()
    if normalized not in _STRUCTURED_ACTIVE_VIEWS:
        return None

    if reason == "timeout":
        summary_prefix = (
            "The provider timed out before it could finish",
            "provider 在完成前超时了",
        )
        reply_prefix = (
            "The provider timed out before finishing",
            "provider 还没讲完就超时了",
        )
    elif reason == "language_corruption":
        summary_prefix = (
            "The provider reply was not trustworthy enough to use directly",
            "这次回答显示有问题，不能直接拿来用",
        )
        reply_prefix = summary_prefix
    elif reason == "reanchor":
        summary_prefix = ("", "")
        reply_prefix = ("", "")
    else:
        summary_prefix = (
            "The provider became unstable on this turn",
            "这一轮 provider 链路不稳定",
        )
        reply_prefix = (
            "The provider became unstable before finishing",
            "provider 还没讲完就变得不稳定了",
        )

    view_copy: dict[str, dict[str, str]] = {
        "plan": {
            "lane_en": "the Plan lane",
            "lane_zh": "Plan 视图",
            "unit_en": "plan move",
            "unit_zh": "计划动作",
            "next_en": (
                "Stay inside the formal plan lane and compress the thread into four short items: "
                "current stage, why now, the smallest next step, and the verify method. "
                "Do not silently mutate the formal plan."
            ),
            "next_zh": (
                "先留在正式计划这条主线里，把这一轮压成四项：当前阶段、why now、最小 next step、"
                "verify method。普通聊天不要静默改正式计划。"
            ),
            "note_en": "Keep the plan truthful, compact, and evidence-first while the provider recovers.",
            "note_zh": "先保住计划的真实性、紧凑度和 evidence 导向，再等 provider 恢复。",
        },
        "resources": {
            "lane_en": "the Resources lane",
            "lane_zh": "Resources 视图",
            "unit_en": "resource move",
            "unit_zh": "资料动作",
            "next_en": (
                "Stay inside the resource lane and do one small library pass: locate the most relevant material, "
                "decide which sandbox folder should receive it, then describe how it should be organized into "
                "sources, knowledge, and cards."
            ),
            "next_zh": (
                "先留在资料库这条主线里，做一轮很小的整理：定位最相关资料、决定该放进资料库里的哪个分组目录，"
                "再说明如何整理成 sources、knowledge、cards。"
            ),
            "note_en": "Keep provenance, sandbox boundaries, and the next transformation path visible.",
            "note_zh": "先保住 provenance、沙箱边界和下一步转化路径的清晰度。",
        },
        "training": {
            "lane_en": "the Training lane",
            "lane_zh": "Training 视图",
            "unit_en": "Learn-first training move",
            "unit_zh": "Learn-first 训练动作",
            "next_en": (
                "Stay inside Learn -> Try -> Verify -> Reflect -> Return. "
                "Do not start with an exam. Land one single card that states why now, the problem, "
                "the learner deliverable, the verify method, and what to bring back."
            ),
            "next_zh": (
                "先留在 Learn -> Try -> Verify -> Reflect -> Return 这条训练闭环里，不要一上来考试。"
                "先落一张单卡，至少说清 why now、problem、deliverable、verify、return。"
            ),
            "note_en": "Keep one dominant card and preserve the learn-first loop while the provider recovers.",
            "note_zh": "先保住单卡优先和 learn-first 的训练闭环，再等 provider 恢复。",
        },
        "settings": {
            "lane_en": "the Settings lane",
            "lane_zh": "Settings 视图",
            "unit_en": "settings check",
            "unit_zh": "设置检查",
            "next_en": (
                "Stay inside the configuration lane and verify the current provider, model, protocol, and runtime truth "
                "before resuming the work."
            ),
            "next_zh": "先留在配置这条主线里，核对 provider、model、protocol 和 runtime 真相，再回来续上这一轮。",
            "note_en": "Keep capability truth explicit before resuming teaching work.",
            "note_zh": "先把能力真相说清楚，再恢复教学动作。",
        },
    }
    spec = view_copy.get(normalized)
    if spec is None:
        return None

    next_step = _localized_text(spec["next_en"], spec["next_zh"], response_language)
    teaching_note = _localized_text(spec["note_en"], spec["note_zh"], response_language)
    if reason == "reanchor":
        summary = _localized_text(
            f"I kept this turn inside {spec['lane_en']}.",
            f"这一轮我继续留在 {spec['lane_zh']} 里。",
            response_language,
        )
        reply = _localized_text(
            f"I will keep this turn inside {spec['lane_en']} with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"这一轮我先在 {spec['lane_zh']} 里用一个更小的{spec['unit_zh']}把它接住。\n\n下一步：{next_step}",
            response_language,
        )
    else:
        summary = _localized_text(
            f"{summary_prefix[0]}, so I kept this turn inside {spec['lane_en']}.",
            f"{summary_prefix[1]}，所以我先把这一轮继续留在 {spec['lane_zh']} 里。",
            response_language,
        )
        reply = _localized_text(
            f"{reply_prefix[0]}, so I will keep the work alive inside {spec['lane_en']} with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"{reply_prefix[1]}，所以我先在 {spec['lane_zh']} 里用一个更小的{spec['unit_zh']}把这轮工作接住。\n\n下一步：{next_step}",
            response_language,
        )

    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
    }


def _general_theory_recovery_next_step(
    focus: str,
    *,
    subtype: str,
    response_language: str | None,
) -> str:
    if subtype == "derivation":
        return _localized_text(
            f"Write one tiny worked step or mini-derivation about {focus}, name the rule that justifies it, then bring back one check that proves it.",
            f"先围绕 {focus} 写出一个很小的步骤或小推导，说明支撑它的规则，再带回一个证明它成立的检查结果。",
            response_language,
        )
    if subtype == "writing":
        return _localized_text(
            f"Write or revise one sentence about {focus}, name one nearby alternative you rejected, then bring back the tone or meaning difference it proves.",
            f"先围绕 {focus} 写一句或改一句，说明你放弃了哪个相邻表达，再带回它证明了什么语气或含义差别。",
            response_language,
        )
    if subtype == "memorization":
        return _localized_text(
            f"Turn {focus} into one tiny fact cluster, do one closed-book recall, then bring back what you remembered versus missed.",
            f"先把 {focus} 收成一小组事实点，做一次闭卷回忆，再带回你记住了什么、漏了什么。",
            response_language,
        )
    if subtype == "reading":
        return _localized_text(
            f"Make one narrow claim about {focus}, support it with one real excerpt or detail, then bring back the evidence link.",
            f"先围绕 {focus} 提出一个很窄的判断，用一个真实片段或细节支撑它，再带回证据和判断之间的联系。",
            response_language,
        )
    return _localized_text(
        f"Explain {focus} in one short example, boundary, or contrast, then bring back one check that proves the explanation holds.",
        f"先用一个短例子、边界或对比把 {focus} 讲清楚，再带回一个能证明这段解释站得住的检查结果。",
        response_language,
    )


def _build_general_theory_recovery_override(
    message: str,
    *,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
    reason: str,
) -> dict[str, str] | None:
    focus, subject = _general_recovery_focus_and_subject(
        message,
        coach_context=coach_context,
        response_language=response_language,
    )
    if not focus or subject is None or subject.family == "code":
        return None

    next_step = _general_theory_recovery_next_step(
        focus,
        subtype=subject.subtype,
        response_language=response_language,
    )
    if reason == "timeout":
        summary = _localized_text(
            "The provider timed out before it could finish, so I kept the lesson on the same learning thread.",
            "provider 还没讲完就 timeout 了，所以我先把这次学习留在同一条学习主线上。",
            response_language,
        )
        teaching_note = _localized_text(
            "When the provider is slow, keep the lesson alive with one Learn -> Try -> Verify micro-loop.",
            "当 provider 变慢时，先用一个 Learn -> Try -> Verify 的微循环把教学接住。",
            response_language,
        )
        reply = _localized_text(
            (
                "The provider timed out before finishing, so I will keep the lesson alive with one tiny Learn-first move.\n\n"
                f"Next step: {next_step}"
            ),
            (
                "provider 还没讲完就 timeout 了，所以我先用一个很小的 Learn-first 动作把这次学习接住。\n\n"
                f"下一步：{next_step}"
            ),
            response_language,
        )
    elif reason == "language_corruption":
        summary = _localized_text(
            "The provider reply was not trustworthy enough to use directly, so I kept the lesson on the same learning thread.",
            "这次回答显示有问题，不能直接拿来用，所以我先把你的问题留在当前进度里。",
            response_language,
        )
        teaching_note = _localized_text(
            "When the visible reply is corrupted or in the wrong language, keep the lesson alive with one Learn -> Try -> Verify micro-loop in the requested language.",
            "当回答显示异常或语言不对时，先用你选择的语言补上一小步说明和检查。",
            response_language,
        )
        reply = _localized_text(
            (
                "The provider reply was not trustworthy enough to use directly, so I will keep the lesson alive with one tiny Learn-first move.\n\n"
                "Trainer will not pretend this broken input is normal teaching, because the model never really saw the original sentence.\n\n"
                f"Next step: {next_step}"
            ),
            (
                "这次回答显示有问题，不能直接拿来用，所以我先用一个很小的步骤把当前问题接住。\n\n"
                "为了避免误导你，我不会把这段异常内容当成正常回答。\n\n"
                f"下一步：{next_step}"
            ),
            response_language,
        )
    else:
        summary = _localized_text(
            "The provider became unstable before it could finish, so I kept the lesson on the same learning thread.",
            "这次 provider 在讲完前变得不稳定，所以我先把这次学习留在同一条学习主线上。",
            response_language,
        )
        teaching_note = _localized_text(
            "When the provider path is unstable, keep the lesson alive with one Learn -> Try -> Verify micro-loop.",
            "当 provider 链路不稳定时，先用一个 Learn -> Try -> Verify 的微循环把教学接住。",
            response_language,
        )
        reply = _localized_text(
            (
                "The provider broke before finishing, so I will keep the lesson alive with one tiny Learn-first move.\n\n"
                f"Next step: {next_step}"
            ),
            (
                "provider 在讲完前出错了，所以我先用一个很小的 Learn-first 动作把这次学习接住。\n\n"
                f"下一步：{next_step}"
            ),
            response_language,
        )

    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
    }


def _build_general_timeout_teaching_override(
    message: str,
    *,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, str] | None:
    return _build_general_theory_recovery_override(
        message,
        coach_context=coach_context,
        response_language=response_language,
        reason="timeout",
    )

    focus = _timeout_focus_seed(
        message,
        coach_context=coach_context,
        response_language=response_language,
    )
    if not focus or _looks_code_or_tooling_focus(focus):
        return None

    next_step = _localized_text(
        f"Write one tiny explanation, worked step, or example about {focus}, then bring back one check that proves it.",
        f"先围绕「{focus}」写出一小步解释、例题或推导，再带回一个最小验证结果。",
        response_language,
    )
    teaching_note = _localized_text(
        "When the provider is slow, keep the lesson alive with one Learn-first move and one tiny verification step.",
        "当 provider 较慢时，先用一个 Learn-first 动作和一个最小验证步骤把教学线程接住。",
        response_language,
    )
    summary = _localized_text(
        "The provider timed out before it could finish, so I kept the lesson on the same learning thread.",
        "provider 还没讲完就 timeout 了，所以我先把这次学习继续留在同一条学习主线上。",
        response_language,
    )
    reply = _localized_text(
        (
            "The provider timed out before finishing, so I will keep the lesson alive with one tiny Learn-first move.\n\n"
            f"Next step: {next_step}"
        ),
        (
            "provider 还没讲完就 timeout 了，所以我先用一个很小的 Learn-first 动作把这次学习接住。\n\n"
            f"下一步：{next_step}"
        ),
        response_language,
    )
    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
    }


def _build_timeout_recovery_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, object]:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    guided_reply = _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    ).strip()
    domain_override = _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    )
    active_view = _coaching_active_view_name(coach_context)
    active_view_override = (
        _build_active_view_recovery_override(
            active_view=active_view,
            response_language=response_language,
            reason="timeout",
        )
        if active_view
        else None
    )
    if isinstance(active_view_override, dict):
        summary = str(active_view_override.get("summary") or "").strip()
        next_step = str(active_view_override.get("next_step") or "").strip()
        teaching_note = str(active_view_override.get("teaching_note") or "").strip()
        reply = str(active_view_override.get("reply") or "").strip()
        resume_thread = _agentic_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
        return {
            "summary": summary,
            "next_step": next_step,
            "blocker": summary,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
            "reply": reply,
            "stop_reason": "timeout",
            "fell_back": True,
        }
    summary_map: dict[str | None, tuple[str, str]] = {
        "remote_workspace": (
            "The provider timed out before it could finish, so I kept this turn in the VS Code remote lane.",
            "provider 在完成前超时了，所以我先把这一轮继续留在 VS Code remote 这条主线上。",
        ),
        "debug_loop": (
            "The provider timed out before it could finish, so I kept this turn inside one trustworthy debug loop.",
            "provider 在完成前超时了，所以我先把这一轮继续收束在一个可信的 debug loop 里。",
        ),
        "function_guidance": (
            "The provider timed out before it could finish, so I kept this turn in the function-guidance lane.",
            "provider 在完成前超时了，所以我先把这一轮继续留在 function guidance 这条主线上。",
        ),
        "project_adaptation": (
            "The provider timed out before it could finish, so I kept this turn in the existing-project adaptation lane.",
            "provider 在完成前超时了，所以我先把这一轮继续留在 existing-project adaptation 这条主线上。",
        ),
    }
    default_summary = _localized_text(
        "The provider timed out before it could finish, so I kept this turn anchored to the same coaching lane.",
        "provider 在完成前超时了，所以我先把这一轮继续锚定在同一条教学主线上。",
        response_language,
    )
    summary = _localized_text(
        *(summary_map.get(domain, ("", ""))),
        response_language,
    ).strip() or default_summary
    general_timeout_override = (
        _build_general_timeout_teaching_override(
            message,
            coach_context=coach_context,
            response_language=response_language,
        )
        if domain in {"", "general", None}
        else None
    )
    if isinstance(general_timeout_override, dict):
        summary = str(general_timeout_override.get("summary") or "").strip() or summary
    next_step = (
        str(domain_override.get("next_step") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    if not next_step and isinstance(general_timeout_override, dict):
        next_step = str(general_timeout_override.get("next_step") or "").strip()
    if not next_step:
        next_step = _localized_text(
            "Return with the next local, visible, verifiable move on this same lane.",
            "请直接带回这条主线上下一个本地可见、可验证的小动作。",
            response_language,
        )
    teaching_note = (
        str(domain_override.get("teaching_note") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    if not teaching_note and isinstance(general_timeout_override, dict):
        teaching_note = str(general_timeout_override.get("teaching_note") or "").strip()
    if not teaching_note:
        teaching_note = _localized_text(
            "Keep the lesson grounded in one small local move while the provider path is slow.",
            "当 provider 链路偏慢时，先把教学继续锚定在一个本地的小动作上。",
            response_language,
        )
    resume_thread = _agentic_resume_thread_text(
        summary,
        next_step,
        response_language=response_language,
    )
    reply = guided_reply or (
        str(general_timeout_override.get("reply") or "").strip()
        if isinstance(general_timeout_override, dict)
        else ""
    ) or _localized_text(
        (
            "I kept this turn on the same coaching lane instead of letting the timeout break the lesson.\n\n"
            f"Next step: {next_step}"
        ),
        (
            "我先把这一轮继续留在同一条教学主线上，不让 timeout 把这次学习打断。\n\n"
            f"下一步：{next_step}"
        ),
        response_language,
    )
    return {
        "summary": summary,
        "next_step": next_step,
        "blocker": summary,
        "teaching_note": teaching_note,
        "resume_thread": resume_thread,
        "reply": reply,
        "stop_reason": "timeout",
        "fell_back": True,
    }


def _provider_error_recovery_kind(error_detail: str | None) -> str:
    normalized = str(error_detail or "").strip().lower()
    if not normalized:
        return "unstable"

    overloaded_markers = (
        "high load",
        "rate limit",
        "too many requests",
        "status 429",
        "status 529",
        "overloaded",
    )
    if any(marker in normalized for marker in overloaded_markers):
        return "overloaded"

    auth_markers = (
        "unauthorized",
        "forbidden",
        "permission",
        "access denied",
        "invalid api key",
        "missing api key",
        "status 401",
        "status 403",
    )
    if any(marker in normalized for marker in auth_markers):
        return "auth"

    config_markers = (
        "model not found",
        "unsupported model",
        "protocol",
        "malformed",
        "status 404",
        "status 400",
    )
    if any(marker in normalized for marker in config_markers):
        return "config"

    return "unstable"


def _build_provider_error_recovery_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
    error_detail: str | None = None,
) -> dict[str, object]:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    guided_reply = _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    ).strip()
    domain_override = _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    )
    active_view = _coaching_active_view_name(coach_context)
    active_view_override = (
        _build_active_view_recovery_override(
            active_view=active_view,
            response_language=response_language,
            reason="provider_error",
        )
        if active_view
        else None
    )
    issue_kind = _provider_error_recovery_kind(error_detail)

    if issue_kind == "auth":
        summary = _localized_text(
            "The provider rejected this turn, so Trainer cannot continue on this connection yet.",
            "这一轮 provider 拒绝了请求，所以 Trainer 还不能沿着这条连接继续。",
            response_language,
        )
        next_step = _localized_text(
            "Check the API key, model access, and provider permissions, then resend this same turn.",
            "先检查 API key、model 访问权限和 provider 权限，再重发这一轮。",
            response_language,
        )
        teaching_note = _localized_text(
            "Keep the current coaching lane, but restore the connection truth before continuing.",
            "先保留当前教学主线，但继续之前必须先恢复连接真相。",
            response_language,
        )
        reply = _localized_text(
            "This turn was blocked by the provider connection, so I will not pretend it completed.\n\n"
            "Fix the connection first, then continue the same coaching thread.",
            "这一轮被 provider 连接拦住了，所以我不会假装它已经完成。\n\n"
            "先修好连接，再继续同一条教学主线。",
            response_language,
        )
    elif issue_kind == "config":
        summary = _localized_text(
            "This provider configuration blocked the turn before Trainer could finish it.",
            "这一轮被当前 provider 配置拦住了，Trainer 还没法把它完整带完。",
            response_language,
        )
        next_step = _localized_text(
            "Check the protocol, model name, and endpoint compatibility, then retry this same turn.",
            "先检查 protocol、model 名称和 endpoint 兼容性，再重试这一轮。",
            response_language,
        )
        teaching_note = _localized_text(
            "Keep the live coaching lane, but repair the configuration truth before continuing.",
            "先保留当前教学主线，但继续之前必须先修好配置真相。",
            response_language,
        )
        reply = _localized_text(
            "This turn hit a provider configuration problem, so I will not pretend the lesson completed.\n\n"
            "Repair the configuration first, then continue the same coaching thread.",
            "这一轮碰到了 provider 配置问题，所以我不会假装这次教学已经完成。\n\n"
            "先修好配置，再继续同一条教学主线。",
            response_language,
        )
    else:
        summary_map: dict[str | None, tuple[str, str]] = {
            "remote_workspace": (
                "The provider was slow or overloaded on this turn, so I kept the lesson in the VS Code remote lane.",
                "这一轮 provider 负载偏高或链路不稳，所以我先把教学继续留在 VS Code remote 这条线上。",
            ),
            "debug_loop": (
                "The provider was slow or overloaded on this turn, so I kept the lesson inside one trustworthy debug loop.",
                "这一轮 provider 负载偏高或链路不稳，所以我先把教学继续收束在一个可信的 debug loop 里。",
            ),
            "function_guidance": (
                "The provider was slow or overloaded on this turn, so I kept the lesson in the function-guidance lane.",
                "这一轮 provider 负载偏高或链路不稳，所以我先把教学继续留在 function guidance 这条线上。",
            ),
            "project_adaptation": (
                "The provider was slow or overloaded on this turn, so I kept the lesson in the existing-project adaptation lane.",
                "这一轮 provider 负载偏高或链路不稳，所以我先把教学继续留在现有项目 adaptation 这条线上。",
            ),
        }
        default_summary = _localized_text(
            "The provider became unstable on this turn, so I kept the lesson anchored to the same coaching lane.",
            "这一轮 provider 链路不稳定，所以我先把教学继续锚定在同一条主线上。",
            response_language,
        )
        general_override = _build_general_theory_recovery_override(
            message,
            coach_context=coach_context,
            response_language=response_language,
            reason="provider_error",
        )
        if isinstance(active_view_override, dict):
            summary = str(active_view_override.get("summary") or "").strip() or default_summary
            next_step = str(active_view_override.get("next_step") or "").strip()
            teaching_note = str(active_view_override.get("teaching_note") or "").strip()
            reply = str(active_view_override.get("reply") or "").strip()
        else:
            summary = (
                _localized_text(*(summary_map.get(domain, ("", ""))), response_language).strip()
                or default_summary
            )
            if isinstance(general_override, dict):
                summary = str(general_override.get("summary") or "").strip() or summary
            next_step = (
                str(domain_override.get("next_step") or "").strip()
                if isinstance(domain_override, dict)
                else ""
            )
            if not next_step and isinstance(general_override, dict):
                next_step = str(general_override.get("next_step") or "").strip()
            if not next_step:
                next_step = _localized_text(
                    "Return with the next visible, local, verifiable move on this same lane.",
                    "请直接带回这条主线上下一个本地可见、可验证的小动作。",
                    response_language,
                )
            teaching_note = (
                str(domain_override.get("teaching_note") or "").strip()
                if isinstance(domain_override, dict)
                else ""
            )
            if not teaching_note and isinstance(general_override, dict):
                teaching_note = str(general_override.get("teaching_note") or "").strip()
            if not teaching_note:
                teaching_note = _localized_text(
                    "Keep the lesson narrow and verifiable while the provider path settles.",
                    "在 provider 链路恢复稳定前，先把教学收窄成可验证的小动作。",
                    response_language,
                )
            reply = guided_reply or (
                str(general_override.get("reply") or "").strip()
                if isinstance(general_override, dict)
                else ""
            ) or _localized_text(
                (
                    "I kept this turn on the same coaching lane instead of letting the provider glitch break the lesson.\n\n"
                    f"Next step: {next_step}"
                ),
                (
                    "我先把这一轮继续留在同一条教学主线上，不让 provider 抖动把这次学习打断。\n\n"
                    f"下一步：{next_step}"
                ),
                response_language,
            )

    resume_thread = _agentic_resume_thread_text(
        summary,
        next_step,
        response_language=response_language,
    )
    return {
        "summary": summary,
        "next_step": next_step,
        "blocker": summary,
        "teaching_note": teaching_note,
        "resume_thread": resume_thread,
        "reply": reply,
        "stop_reason": "provider_error",
        "fell_back": True,
    }


def _build_language_corruption_recovery_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, object] | None:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    guided_reply = _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    ).strip()
    domain_override = _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    )
    active_view = _coaching_active_view_name(coach_context)
    active_view_override = (
        _build_active_view_recovery_override(
            active_view=active_view,
            response_language=response_language,
            reason="language_corruption",
        )
        if active_view
        else None
    )
    general_override = _build_general_theory_recovery_override(
        message,
        coach_context=coach_context,
        response_language=response_language,
        reason="language_corruption",
    )
    if (
        not guided_reply
        and not isinstance(domain_override, dict)
        and not isinstance(general_override, dict)
    ):
        summary = _localized_text(
            "The reply was not readable, so I did not use it as your answer.",
            "这条回复没有读清，我不会把它当作答案。",
            response_language,
        )
        next_step = _localized_text(
            "Please send the same question again.",
            "请把刚才的问题再发一次。",
            response_language,
        )
        reply = _localized_text(
            "I could not read that reply. Please send the same question again.",
            "这条回复没有读清。请把刚才的问题再发一次。",
            response_language,
        )
        return {
            "summary": summary,
            "next_step": next_step,
            "teaching_note": "",
            "reply": reply,
            "resume_thread": _agentic_resume_thread_text(
                summary,
                next_step,
                response_language=response_language,
            ),
            "stop_reason": "language_corruption_recovered",
            "fell_back": True,
            "scenario": domain or "general",
        }

    if isinstance(active_view_override, dict):
        summary = str(active_view_override.get("summary") or "").strip()
        next_step = str(active_view_override.get("next_step") or "").strip()
        teaching_note = str(active_view_override.get("teaching_note") or "").strip()
        reply = str(active_view_override.get("reply") or "").strip()
    else:
        summary = _localized_text(
            "The provider reply came back degraded, so I kept this lesson moving with a local recovery scaffold.",
            "这次回答显示有问题，我先用一个可靠的小步骤把这轮学习接住。",
            response_language,
        )
        if isinstance(general_override, dict):
            summary = str(general_override.get("summary") or "").strip() or summary
        next_step = (
            str(domain_override.get("next_step") or "").strip()
            if isinstance(domain_override, dict)
            else ""
        )
        if not next_step and isinstance(general_override, dict):
            next_step = str(general_override.get("next_step") or "").strip()
        teaching_note = (
            str(domain_override.get("teaching_note") or "").strip()
            if isinstance(domain_override, dict)
            else ""
        )
        if not teaching_note and isinstance(general_override, dict):
            teaching_note = str(general_override.get("teaching_note") or "").strip()
        if not next_step:
            next_step = _localized_text(
                "Keep going with the next small verifiable move on this same lane.",
                "继续沿着同一条主线做下一个可验证的小动作。",
                response_language,
            )
        if not teaching_note:
            teaching_note = _localized_text(
                "Keep the lesson narrow, visible, and verifiable until the provider path is stable again.",
                "先把这一步收窄成一个可见、可验证的小动作，等回答恢复正常后再继续。",
                response_language,
            )
        if not guided_reply:
            guided_reply = (
                str(general_override.get("reply") or "").strip()
                if isinstance(general_override, dict)
                else ""
            ) or summary
        reply = guided_reply if guided_reply.startswith(summary) else f"{summary}\n\n{guided_reply}"
    resume_thread = _agentic_resume_thread_text(
        summary,
        next_step,
        response_language=response_language,
    )
    resolved_scenario = domain or ("general" if isinstance(general_override, dict) else domain)
    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
        "resume_thread": resume_thread,
        "stop_reason": "language_corruption_recovered",
        "fell_back": True,
        "scenario": resolved_scenario,
    }


def _mode_style_label(mode: str, chinese: bool) -> str:
    if chinese:
        return {
            "guided": "我先带你把",
            "balanced": "我们先把",
            "direct": "先直接把",
        }.get(mode, "我们先把")
    return {
        "guided": "In guided mode,",
        "balanced": "In balanced mode,",
        "direct": "In direct mode,",
    }.get(mode, "In guided mode,")


def _scaffold_anchor(
    *,
    scenario: str,
    goal: str,
    file_path: str | None,
    current_focus: str,
    chinese: bool,
) -> str:
    visible_focus = _surface_context_text(current_focus, chinese=chinese)
    if visible_focus:
        return (
            f"我们先沿着这条线继续：{visible_focus}。"
            if chinese
            else f"I will keep working along this live thread: {visible_focus}."
        )

    if scenario == "remote_workspace":
        base = "我们先把这一轮留在 VS Code remote 这条线上。" if chinese else (
            "I will keep this turn in the VS Code remote lane."
        )
    elif scenario == "debug_loop":
        base = "我们先把这一轮收束成一个可信的 debug loop。" if chinese else (
            "I will keep this turn inside one trustworthy debug loop."
        )
    elif scenario == "function_guidance":
        base = "我们先把这一轮留在 function guidance 这条线上。" if chinese else (
            "I will keep this turn in the function-guidance lane."
        )
    elif scenario == "project_adaptation":
        base = "我们先沿着现有项目 adaptation 这条线继续。" if chinese else (
            "I will keep this turn in the existing-project adaptation lane."
        )
    elif scenario == "principle":
        base = "我们先把这一轮锚定在当前原理和代码边界上。" if chinese else (
            "I will anchor this turn in the current principle and code boundary first."
        )
    else:
        base = (
            f"我们先回到 `{file_path}` 这一步。"
            if chinese and file_path
            else f"I will re-anchor on `{file_path}` first."
            if file_path
            else "我们先对齐这一步真正要完成的目标。"
            if chinese
            else "I want to re-anchor on the real goal of this step first."
        )

    if goal and scenario not in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        goal_text = _trim_sentence(goal, 42 if chinese else 96)
        if chinese:
            return f"{base} 这一轮先服务这个目标：{goal_text}。"
        return f"{base} The immediate goal for this round is: {goal_text}."
    return base


def _scaffold_diagnosis(
    *,
    scenario: str,
    learner_signal: str,
    diagnostics_count: int,
    weak_spots: list[str],
    teaching_observations: list[str],
    summary: str,
    teaching_decision_reason: str,
    chinese: bool,
) -> str:
    visible_summary = _surface_context_text(summary, chinese=chinese)
    if visible_summary:
        return visible_summary if visible_summary.endswith(("。", ".", "!", "！", "?", "？")) else (
            f"{visible_summary}。"
            if chinese
            else f"{visible_summary}."
        )

    visible_reason = _surface_context_text(teaching_decision_reason, chinese=chinese)
    if visible_reason:
        return (
            f"这一轮先这样收束，是因为{visible_reason}。"
            if chinese
            else f"I am narrowing this turn this way because {visible_reason}."
        )

    if diagnostics_count > 0:
        return (
            f"当前文件里还有 {diagnostics_count} 条 diagnostics，先不要铺开，先恢复一条最小反馈链。"
            if chinese
            else f"There are still {diagnostics_count} diagnostics in the current file, so I want one minimal feedback loop before we widen anything."
        )

    if weak_spots:
        weak_spot = _trim_sentence(weak_spots[0], 28 if chinese else 72)
        return (
            f"这一轮先盯住最容易反复卡住的点：{weak_spot}。"
            if chinese
            else f"The riskiest recurring weak spot on this turn is: {weak_spot}."
        )

    if teaching_observations:
        observation = _surface_context_text(teaching_observations[0], chinese=chinese)
        if observation:
            return observation if observation.endswith(("。", ".", "!", "！", "?", "？")) else (
                f"{observation}。"
                if chinese
                else f"{observation}."
            )

    if learner_signal == "blocked":
        return (
            "你现在更需要的是先把范围压小，而不是再加更多解释。"
            if chinese
            else "Right now you need a smaller scope more than a larger explanation."
        )

    scenario_map = {
        "remote_workspace": (
            "先把工作区边界说稳，再决定 remote 里的下一步。",
            "The next useful move depends on proving the real workspace boundary first.",
        ),
        "debug_loop": (
            "先把 debug 收束到一个 pause point、一个 value 和一个验证动作上。",
            "The next useful move is to keep debugging inside one pause point, one observed value, and one verification move.",
        ),
        "function_guidance": (
            "先把函数 contract 锚定在一个 live call site 上，再扩解释。",
            "The next useful move is to anchor the function contract to one live call site before the explanation widens.",
        ),
        "project_adaptation": (
            "先分清稳定面和变更面，再动第一条 adaptation 边界。",
            "The next useful move is to separate the stable surface from the change surface before the first adaptation.",
        ),
        "principle": (
            "先把原理压回当前代码边界，再做一个最小验证。",
            "The next useful move is to pin the principle back to the live code boundary and test it once.",
        ),
    }
    zh, en = scenario_map.get(
        scenario,
        (
            "这一轮先落一个最小可验证动作，把线程继续接稳。",
            "The next useful move is one small verifiable action that keeps the thread continuous.",
        ),
    )
    return zh if chinese else en


def _scaffold_next_step(
    *,
    scenario: str,
    mode: str,
    learner_signal: str,
    file_path: str | None,
    weak_spots: list[str],
    next_step_hint: str,
    chinese: bool,
) -> str:
    localized_hint = _surface_context_text(next_step_hint, chinese=chinese)
    if next_step_hint and (localized_hint or not chinese):
        visible_hint = localized_hint or next_step_hint
        if chinese:
            if scenario in {"project_idea", "engineering_challenge"}:
                return f"先别把它讲成更大的计划，先做这一步：{visible_hint}"
            if scenario == "principle":
                return f"先把这个原理落成动作：{visible_hint}"
            if learner_signal == "blocked":
                return f"这一轮先只做这一个动作：{visible_hint}"
            if mode == "direct":
                return f"先直接从这一步开始：{visible_hint}"
            return f"下一步先做这个：{visible_hint}"
        return f"The next move I recommend is this: {next_step_hint}"

    scenario_step = _scenario_step_text(
        scenario=scenario,
        file_path=file_path,
        weak_spots=weak_spots,
        chinese=chinese,
    )
    mode_prefix = _mode_style_label(mode, chinese)
    if chinese:
        if learner_signal == "blocked":
            return f"先别同时做太多，只做这一步：{scenario_step}"
        if mode == "direct":
            return f"先直接从这一步开始：{scenario_step}"
        return f"{mode_prefix}{scenario_step}。"
    if learner_signal == "blocked":
        return f"{mode_prefix} do not do too much at once; start by {scenario_step}"
    return f"{mode_prefix} the highest-value next move is to {scenario_step}"


def _scenario_step_text(
    scenario: str,
    *,
    file_path: str | None,
    weak_spots: list[str],
    chinese: bool,
) -> str:
    file_suffix = _file_suffix(file_path, chinese=chinese)
    weak_spot = _trim_sentence(weak_spots[0], 24 if chinese else 56) if weak_spots else ""

    if scenario == "remote_workspace":
        return (
            "判断当前工作区是 SSH、tunnels、dev container、WSL 还是 local，再确认文件实际在哪台机器上"
            if chinese
            else "identify whether the workspace is SSH, tunnels, dev container, WSL, or local, then prove which machine actually owns the files"
        )
    if scenario == "debug_loop":
        return (
            "只复现一次，在第一个有意义的 breakpoint 停下，检查一个 value、branch 或 stack frame"
            if chinese
            else "reproduce once, pause at the first meaningful breakpoint, and inspect one value, branch, or stack frame"
        )
    if scenario == "function_guidance":
        return (
            "先从一个 live call site 读这个函数，再用 hover、signature help、definition 把 contract 读稳"
            if chinese
            else "start from one live call site, then use hover, signature help, and definition until the contract stops moving"
        )
    if scenario == "project_adaptation":
        return (
            "写出必须保持不变的行为、必须改变的目标，以及要先碰的第一条边界"
            if chinese
            else "write down what must stay stable, what must change, and the first boundary you want to adapt"
        )
    if scenario == "principle":
        return (
            f"把当前原理钉在一处 live code boundary 上，再做一个最小验证{file_suffix}"
            if chinese
            else f"pin the current principle to one live code boundary and run one small verification{file_suffix}"
        )
    if scenario in {"review", "task", "next_task"}:
        return (
            f"先恢复一条最小反馈链{file_suffix}"
            if chinese
            else f"restore one minimal feedback loop{file_suffix}"
        )
    if scenario == "plan":
        return (
            "只保留一个最近的里程碑和一个验证点"
            if chinese
            else "keep only the nearest milestone and one verification point"
        )
    if weak_spot:
        return (
            f"先把 {weak_spot} 这一处压稳{file_suffix}"
            if chinese
            else f"stabilize {weak_spot} first{file_suffix}"
        )
    return (
        f"先落一个最小可验证切片{file_suffix}"
        if chinese
        else f"land one smallest verifiable slice{file_suffix}"
    )


def _scaffold_teaching_note(
    *,
    scenario: str,
    mode: str,
    recent_wins: list[str],
    weak_spots: list[str],
    due_reviews: list[dict[str, str]],
    review_rhythm: str,
    coach_defaults: dict[str, object],
    tone_name: str,
    verbosity_bias: str,
    chinese: bool,
) -> str:
    if recent_wins:
        recent_win = _surface_context_text(recent_wins[0], chinese=chinese) or recent_wins[0]
        return (
            f"你前面已经把这条线的一部分走通了：{recent_win}。这一轮继续沿着可验证的节奏走。"
            if chinese
            else f"You already proved part of this lane earlier: {recent_win}. I want to keep the same verifiable rhythm."
        )
    if weak_spots:
        weak_spot = _surface_context_text(weak_spots[0], chinese=chinese) or weak_spots[0]
        return (
            f"我会继续盯住 {weak_spot} 这个易错点，不让它在这一轮重新扩散。"
            if chinese
            else f"I will keep watching the recurring weak spot around {weak_spot} so it does not spread again on this turn."
        )
    if due_reviews:
        reason = _format_due_review_item(due_reviews[0])
        return (
            f"做完这一步后，我们再决定要不要把复习队列里的这条也收回来：{reason}。"
            if chinese
            else f"After this move, we can decide whether to pull this review thread back in: {reason}."
        )
    if review_rhythm and scenario == "plan":
        visible_rhythm = _surface_context_text(review_rhythm, chinese=chinese)
        if visible_rhythm:
            return (
                f"这一步完成后，再按现在的 review rhythm 接着走：{visible_rhythm}。"
                if chinese
                else f"After this move, continue with the current review rhythm: {visible_rhythm}."
            )
    if mode == "direct":
        return (
            "我会把解释压短一点，但会把为什么这一步重要和怎么验证说清楚。"
            if chinese
            else "I will keep the explanation short, but I will still make the reason and verification signal explicit."
        )
    if verbosity_bias == "short":
        return (
            "这一轮先保持短一点，只围绕当前这一条线说清楚。"
            if chinese
            else "I will keep this turn compact and stay on one line of coaching."
        )
    if tone_name:
        return (
            f"这一轮我会保持 {tone_name} 这类语气，但优先保证动作可验证。"
            if chinese
            else f"I will keep the {tone_name} tone, but I still want the move to stay verifiable."
        )
    if coach_defaults:
        return (
            "我会继续沿着你已经设定好的教练偏好来带，不额外打开新的面。"
            if chinese
            else "I will keep following your saved coaching defaults instead of opening a new lane."
        )
    return (
        "这一步的重点不是讲更多，而是把线程继续接稳。"
        if chinese
        else "The point of this turn is not more breadth; it is keeping the thread stable."
    )


def _scaffold_close(
    *,
    learner_signal: str,
    mode: str,
    verbosity_bias: str,
    chinese: bool,
) -> str:
    if chinese:
        if learner_signal == "blocked":
            return "如果你一动手又卡住，就把那一小段原样带回来，我帮你再缩一层。"
        if mode == "direct":
            return "做完别只说“好了”，告诉我你验证到了什么，我再帮你选下一步。"
        if verbosity_bias == "short":
            return "先做这一步，再把结果带回来。"
        return "先做这一步，再把结果带回来，我们再决定是扩展、复盘，还是继续收紧。"
    if learner_signal == "blocked":
        return "If you get stuck again as soon as you start, show me the exact small section you were about to change and I will help you reduce it one step further."
    if mode == "direct":
        return "When you finish, do not just say 'done'; tell me what result you verified and I will help you choose the next move."
    if verbosity_bias == "short":
        return "Take that one step first, then bring back the result."
    return "Take that one step first, then bring back the result and we can decide whether to expand, review, or tighten the loop."


def _file_suffix(file_path: str | None, chinese: bool = False) -> str:
    if not file_path:
        return ""
    if chinese:
        return f"，先从 `{file_path}` 开始"
    return f" in `{file_path}`"


_FIRST_TURN_EXPLICIT_SCENARIOS = {
    "concept_teaching",
    "debug_loop",
    "engineering_challenge",
    "function_guidance",
    "idea_implementation",
    "next_task",
    "principle",
    "project_adaptation",
    "project_idea",
    "project_sourcing",
    "remote_workspace",
    "review",
    "review_reflection",
}


def _first_turn_concrete_followthrough(*, chinese: bool) -> str:
    if chinese:
        return "\u4e0b\u4e00\u6b65\uff1a\u6cbf\u7740\u4f60\u521a\u624d\u8fd9\u4e2a\u5177\u4f53\u4efb\u52a1\u7ee7\u7eed\uff0c\u7ed9\u6211\u4e00\u4e2a\u4f60\u73b0\u5728\u5c31\u80fd\u5c55\u5f00\u7684\u771f\u5b9e\u4f8b\u5b50\u3001\u7247\u6bb5\u6216\u8f93\u5165\uff0c\u6211\u4f1a\u5728\u540c\u4e00\u6761\u7ebf\u91cc\u7ee7\u7eed\u5e26\u4f60\u505a\u3002"
    return (
        "Next step: stay on the exact task you just named and give me one real example, "
        "snippet, or input you can open right now so we can keep the same thread moving."
    )


def _first_turn_has_concrete_focus(
    *,
    scenario: str | None,
    learner_message: str,
    reply: str,
) -> bool:
    normalized = str(scenario or "").strip().lower()
    if normalized and normalized in _FIRST_TURN_EXPLICIT_SCENARIOS:
        return True

    source = f"{learner_message}\n{reply}".strip()
    if not source:
        return False

    if _infer_guided_coaching_domain(
        source,
        current_file=None,
        coach_context=None,
    ):
        return True

    lowered = source.casefold()
    concrete_markers = (
        "`",
        "/",
        "\\",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".java",
        ".go",
        ".rs",
        ".md",
        "http://",
        "https://",
        "api",
        "bug",
        "class",
        "code",
        "dataset",
        "debug",
        "endpoint",
        "error",
        "essay",
        "file",
        "function",
        "grammar",
        "implement",
        "implementation",
        "library",
        "method",
        "module",
        "outline",
        "paragraph",
        "project",
        "python",
        "react",
        "refactor",
        "remote",
        "review",
        "sentence",
        "snippet",
        "sql",
        "ssh",
        "stack frame",
        "stack trace",
        "test",
        "traceback",
        "translation",
        "typescript",
        "vocabulary",
        "word",
        "writing",
        "\u4ee3\u7801",
        "\u5199\u4f5c",
        "\u51fd\u6570",
        "\u5355\u8bcd",
        "\u53e5\u5b50",
        "\u6bb5\u843d",
        "\u65b9\u6cd5",
        "\u62a5\u9519",
        "\u63a5\u53e3",
        "\u7ffb\u8bd1",
        "\u8bed\u6cd5",
        "\u8bcd\u6c47",
        "\u8c03\u8bd5",
        "\u8fdc\u7a0b",
        "\u9879\u76ee",
    )
    if any(marker in lowered for marker in concrete_markers):
        return True

    meta_markers = (
        "coach me",
        "help me learn",
        "how should we start",
        "how should we work",
        "learning plan",
        "study plan",
        "training plan",
        "training rhythm",
        "what should we focus on first",
        "where should we start",
        "\u4ece\u54ea\u5f00\u59cb",
        "\u5148\u5b66\u4ec0\u4e48",
        "\u5b66\u4e60\u8ba1\u5212",
        "\u5b66\u4e60\u8282\u594f",
        "\u600e\u4e48\u5f00\u59cb",
        "\u600e\u4e48\u5b66",
        "\u8bad\u7ec3\u4e3b\u7ebf",
        "\u8bad\u7ec3\u8ba1\u5212",
        "\u8bad\u7ec3\u8282\u594f",
        "\u5e26\u6211\u5b66",
    )
    if any(marker in lowered for marker in meta_markers):
        return False

    words = [part for part in re.split(r"\s+", lowered) if part]
    return len(words) >= 12


def _should_offer_generic_first_turn_lane_prompt(
    *,
    scenario: str | None,
    learner_message: str,
    reply: str,
) -> bool:
    if _fresh_lane_comparison_requested(learner_message):
        return False
    return not _first_turn_has_concrete_focus(
        scenario=scenario,
        learner_message=learner_message,
        reply=reply,
    )


def _compact_first_turn_reply(
    reply: str,
    *,
    chinese: bool,
    scenario: str | None = None,
    learner_message: str = "",
    coach_context: dict[str, Any] | None = None,
) -> str:
    paragraphs = [part.strip() for part in reply.split("\n\n") if part.strip()]
    if not paragraphs:
        return ""

    kept: list[str] = []
    for paragraph in paragraphs:
        lowered = paragraph.lower()
        if lowered.startswith("##") or lowered.startswith("###"):
            continue
        if lowered.startswith("- ") or lowered.startswith("* "):
            continue
        kept.append(paragraph)
        if len(kept) >= 2:
            break

    if not kept:
        kept = paragraphs[:2]

    trimmed = [_trim_sentence(item, 112 if chinese else 142) for item in kept[:2]]
    first = trimmed[0] if trimmed else ""
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
    if guided_lane == "function_guidance" and isinstance(coach_context, dict):
        starter = coach_context.get("function_guidance_starter")
        if isinstance(starter, dict) and str(starter.get("status") or "").strip() == "ready":
            starter_tokens = [
                _compact_text(starter.get("call_site_path"), 120),
                _compact_text(starter.get("definition_path"), 120),
                _compact_text(starter.get("definition_symbol"), 48),
                _compact_text(starter.get("call_site_symbol"), 48),
            ]
            reply_mentions_starter = any(token and token in reply for token in starter_tokens)
            if reply_mentions_starter:
                if starter_tokens[0] and starter_tokens[1] and starter_tokens[0] in reply and starter_tokens[1] in reply:
                    return first
                guided_note = ""
    if guided_note and guided_close:
        second = guided_note
        close = guided_close
        return "\n\n".join([part for part in (first, second, close) if part.strip()])

    if not _should_offer_generic_first_turn_lane_prompt(
        scenario=scenario,
        learner_message=learner_message,
        reply=reply,
    ):
        second = trimmed[1] if len(trimmed) > 1 else _first_turn_concrete_followthrough(chinese=chinese)
        return "\n\n".join([part for part in (first, second) if part.strip()])

    second = (
        trimmed[1]
        if len(trimmed) > 1
        else (
            "我会先理解你的目标、项目语境和当前阻塞点，再把这一轮收束到最合适的教学线里。"
            if chinese
            else "I will first understand your goal, project, and blocker, remember that context for the next turn, then decide whether to guide the code, explain the principle, or shape the training thread first."
        )
    )
    if chinese:
        close = "告诉我现在更接近哪一类：实现一个 idea、改造现有项目，还是先把训练主线和节奏定下来。"
    else:
        close = "Tell me which lane is closest right now: implementing an idea, adapting a project, or shaping the training thread first."
    return "\n\n".join([part for part in (first, second, close) if part.strip()])


def _compose_principle_followthrough_patch(
    *,
    reply: str,
    principle_note: dict[str, object] | None,
    chinese: bool,
) -> str:
    principle_note = principle_note or {}
    if not principle_note:
        return ""

    why_it_matters = str(principle_note.get("why_it_matters") or "").strip()
    apply_now = str(principle_note.get("apply_now") or principle_note.get("follow_up_exercise") or "").strip()
    source_asset_title = str(principle_note.get("source_asset_title") or "").strip()

    needs_reason = bool(why_it_matters) and not (
        _reply_mentions_excerpt(reply, why_it_matters) or _reply_has_reason_signal(reply, chinese)
    )
    needs_apply = bool(apply_now) and not (
        _reply_mentions_excerpt(reply, apply_now) or _reply_has_action_signal(reply, chinese)
    )
    needs_source = bool(source_asset_title) and not (
        _reply_mentions_excerpt(reply, source_asset_title)
    )

    parts: list[str] = []
    if chinese:
        if needs_reason:
            parts.append(f"它在这里重要，是因为{why_it_matters}。")
        if needs_apply:
            prefix = "你现在" if apply_now.startswith("先") else "你现在先"
            parts.append(f"{prefix}{apply_now}。")
        if needs_source:
            parts.append(f"继续沿着 `{source_asset_title}` 这条解释线。")
    else:
        if needs_reason:
            parts.append(f"It matters here because {why_it_matters}.")
        if needs_apply:
            parts.append(f"Apply it now by {apply_now}.")
        if needs_source:
            parts.append(f"Stay on `{source_asset_title}` for the next explanation move.")
    return " ".join(parts).strip()


def _compose_missing_next_step_patch(
    *,
    reply: str,
    scenario: str,
    next_step_hint: str,
    file_path: str | None,
    project_entry_points: list[str],
    learner_signal: str,
    mode: str,
    chinese: bool,
    coach_context: dict[str, Any] | None = None,
) -> str:
    step = next_step_hint.strip()
    if scenario == "function_guidance":
        starter_note, starter_next_step = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=chinese,
        )
        starter = coach_context.get("function_guidance_starter") if isinstance(coach_context, dict) else None
        starter_tokens = [
            _compact_text(starter.get("call_site_path"), 120) if isinstance(starter, dict) else None,
            _compact_text(starter.get("definition_path"), 120) if isinstance(starter, dict) else None,
            _compact_text(starter.get("definition_symbol"), 48) if isinstance(starter, dict) else None,
            _compact_text(starter.get("call_site_symbol"), 48) if isinstance(starter, dict) else None,
        ]
        if any(token and token in reply for token in starter_tokens):
            return ""
        if starter_note or starter_next_step:
            step = starter_next_step.strip() or step
    if not step:
        return ""
    if _is_meta_step_hint(step):
        return ""

    if _reply_mentions_excerpt(reply, step):
        return ""
    if _reply_has_action_signal(reply, chinese) and len(reply) > 120:
        return ""

    anchored_step = _anchor_step_to_workspace(
        step,
        file_path=file_path,
        project_entry_points=project_entry_points,
        chinese=chinese,
    )
    if chinese:
        if scenario in {"project_idea", "engineering_challenge"}:
            return f"先别把它讲成更大的计划，先做这一步：{anchored_step}"
        if scenario == "principle":
            return f"先把这个原理落成动作：{anchored_step}"
        if learner_signal == "blocked":
            return f"这一轮先只做这一个动作：{anchored_step}"
        if mode == "direct":
            return f"先直接从这一步开始：{anchored_step}"
        return f"下一步先做这个：{anchored_step}"

    if scenario in {"project_idea", "engineering_challenge"}:
        return f"Do not widen this into a larger plan yet. Take this first cut: {anchored_step}"
    if scenario == "principle":
        return f"Turn the principle into action with this move: {anchored_step}"
    if learner_signal == "blocked":
        return f"For this turn, do only this next move: {anchored_step}"
    if mode == "direct":
        return f"Start directly with this step: {anchored_step}"
    return f"The next move is this: {anchored_step}"


def _compose_review_tightening_patch(
    *,
    reply: str,
    scenario: str,
    failing_checks: list[str],
    learning_outcomes: list[dict[str, object]],
    pace_signal: str,
    learner_signal: str,
    chinese: bool,
) -> str:
    repeated_failure = _has_repeated_failure_signal(learning_outcomes, pace_signal, learner_signal)
    review_pressure = scenario in {"review", "task", "next_task", "plan", "project_adaptation"} or bool(
        failing_checks or repeated_failure
    )
    if not review_pressure:
        return ""
    if _reply_has_scope_tightening_signal(reply, chinese) and _reply_has_verification_signal(reply, chinese):
        return ""

    check = failing_checks[0] if failing_checks else ""
    if chinese:
        if check:
            return f"先别扩范围。先把 `{check}` 这一条最小反馈链恢复出来，确认它通过，再决定要不要扩。"
        return "先别扩范围。先恢复一条最小反馈链，确认这一步通过，再决定要不要扩。"

    if check:
        return f"Do not widen scope on this turn. First restore one minimal feedback loop around `{check}`, confirm it passes, then decide whether to expand."
    return "Do not widen scope on this turn. First restore one minimal feedback loop, confirm this step passes, then decide whether to expand."


def _compose_success_signal_patch(
    *,
    reply: str,
    exercise_prompt: dict[str, object] | None,
    chinese: bool,
) -> str:
    exercise_prompt = exercise_prompt or {}
    if not exercise_prompt:
        return ""
    success_signal = str(exercise_prompt.get("success_signal") or "").strip()
    if not success_signal:
        return ""
    if _contains_meta_coach_context(success_signal):
        return ""
    if _reply_mentions_excerpt(reply, success_signal):
        return ""
    if _reply_has_verification_signal(reply, chinese) and len(reply) > 180:
        return ""
    if chinese:
        return f"这一步算过的信号是：{success_signal}。"
    return f"You can count this slice as done when: {success_signal}."


def _compose_recalled_memory_patch(
    *,
    reply: str,
    recalled_coaching_memories: list[dict[str, object]],
    chinese: bool,
) -> str:
    if not recalled_coaching_memories:
        return ""
    if _reply_has_recall_signal(reply, chinese):
        return ""

    first = recalled_coaching_memories[0]
    lesson = str(first.get("lesson") or first.get("summary") or "").strip()
    title = str(first.get("title") or "").strip()
    if not lesson:
        return ""
    if _reply_mentions_excerpt(reply, lesson) or (title and _reply_mentions_excerpt(reply, title)):
        return ""
    if (
        len(reply) > 220
        and _reply_has_action_signal(reply, chinese)
        and _reply_has_verification_signal(reply, chinese)
    ):
        return ""
    if chinese:
        return f"先沿着之前已经验证过的做法走：{lesson}。"
    return f"Stay on the line that already worked before: {lesson}."


def _anchor_step_to_workspace(
    step: str,
    *,
    file_path: str | None,
    project_entry_points: list[str],
    chinese: bool,
) -> str:
    anchor = file_path or (project_entry_points[0] if project_entry_points else "")
    if not anchor or _reply_mentions_excerpt(step, anchor):
        return step
    if chinese:
        return f"{step}，先从 `{anchor}` 开始。"
    return f"{step} Start in `{anchor}`."


def _reply_has_reason_signal(reply: str, chinese: bool) -> bool:
    markers = ["because", "this matters", "the reason", "so that", "which helps", "why this matters"]
    if chinese:
        markers.extend(["因为", "这很重要", "原因", "这样就能", "为什么这一步重要", "它在这里重要"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_action_signal(reply: str, chinese: bool) -> bool:
    markers = [
        "next step",
        "start by",
        "start with",
        "begin with",
        "the next move",
        "apply it now",
        "try ",
        "run ",
        "verify",
        "check ",
        "implement ",
        "patch ",
    ]
    if chinese:
        markers.extend(["下一步", "现在先", "先做", "先跑", "先改", "先补", "先验证", "先检查", "先指出", "先确认", "直接从这一步"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_verification_signal(reply: str, chinese: bool) -> bool:
    markers = ["verify", "check", "run", "test", "confirm", "passes", "feedback loop"]
    if chinese:
        markers.extend(["验证", "检查", "确认", "跑一次", "通过", "反馈链", "验收信号", "可验证"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_scope_tightening_signal(reply: str, chinese: bool) -> bool:
    markers = ["do not widen", "reduce scope", "tighten", "smallest", "minimal", "one branch", "one patch"]
    if chinese:
        markers.extend(["先别扩范围", "不要扩范围", "收紧", "最小反馈链", "最小可验证", "缩小范围"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_recall_signal(reply: str, chinese: bool) -> bool:
    markers = ["previous", "earlier", "already worked", "reuse", "stay on the line", "keep this lane"]
    if chinese:
        markers.extend(["之前", "前面", "已经验证过", "复用", "沿着这条线", "继续这条线"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


ProviderService._onboarding_reply = _provider_service_onboarding_reply
ProviderService._error_reply = _provider_service_error_reply
ProviderService._missing_api_key_reply = _provider_service_missing_api_key_reply
ProviderService.coaching_reply_stream = _provider_service_coaching_reply_stream


def _clean_provider_service_onboarding_reply(
    self,
    response_language: str | None = None,
) -> str:
    if _prefers_chinese(response_language):
        return (
            "先别急着直接上方案。第一轮我想先把你的目标、项目语境、"
            "以及更适合你的带法对齐起来。\n\n"
            "你可以直接告诉我现在手上的项目、想学到哪一步、卡在哪里。"
            "我会记住这些判断，后面继续沿着同一条线带你，不会每一轮都重开。\n\n"
            "你现在更需要我带你做哪一类：实现一个 idea、改造现有项目，"
            "还是先把训练主线和节奏定下来？"
        )
    return (
        "Let's not jump straight into a solution. On the first turn I want to line up the few things that matter most: "
        "your goal, the project context, and how you prefer to be coached.\n\n"
        "Tell me what you are working on, where you want to get to, and where the thread feels unstable right now. "
        "I will remember that context so the next turn can continue the same lane instead of restarting.\n\n"
        "Which lane is closest right now: implement an idea, adapt a project, or shape the training thread first?"
    )


def _clean_provider_service_error_reply(
    self,
    exc: Exception,
    response_language: str | None = None,
) -> str:
    detail = redact_provider_error(exc, api_key=self._api_key)
    if _prefers_chinese(response_language):
        return (
            "连接教练服务时遇到问题，所以这轮我先用本地恢复逻辑接住你。"
            f"这次错误是：{detail}。"
        )
    return (
        "I hit an issue connecting to the coach service, so I am keeping this turn moving locally. "
        f"The error was: {detail}."
    )


def _clean_provider_service_missing_api_key_reply(
    self,
    response_language: str | None = None,
) -> str:
    if _prefers_chinese(response_language):
        return (
            "还没有设置可用的 API 密钥。"
            "请到设置里填写模型服务和密钥，然后就可以开始对话。"
        )
    return (
        "Trainer cannot start working yet because there is no usable API key. "
        "Open Settings, save a provider, model, and API key, and I can continue from there."
    )


def _clean_provider_failure_summary(
    self,
    category: str,
    response_language: str | None,
) -> str:
    if category == "streaming_unavailable":
        return _localized_text(
            "The configured provider has no verified native streaming path for this turn.",
            "当前 provider 没有通过验证的原生流式路径，这一轮不能继续。",
            response_language,
        )
    summary_map: dict[str, tuple[str, str]] = {
        "invalid_key_or_permission": (
            "The provider rejected this turn's API key or permissions.",
            "这个 provider 拒绝了这一轮使用的 API key 或 permission。",
        ),
        "model_unsupported": (
            "The provider reached the endpoint, but this model name is not accepted there.",
            "这个 provider 可以连通，但当前 model name 不被这个 endpoint 接受。",
        ),
        "model_not_found": (
            "The provider reached the gateway, but no available channel matched this model.",
            "这个 provider 可以连通，但 gateway 里没有可用 channel 匹配当前 model。",
        ),
        "language_corruption": (
            "The provider returned a visibly corrupted coaching reply on this turn.",
            "这个 provider 可达，但这一轮返回了肉眼可见的乱码回复。",
        ),
        "language_probe_inconclusive": (
            "The provider reached the endpoint, but Trainer could not fully verify zh-CN input integrity yet.",
            "这个 provider 可达，但 Trainer 还不能完整验证这条链路的 zh-CN 输入保真度。",
        ),
        "empty_response": (
            "The provider reached the endpoint, but returned no usable visible reply.",
            "这个 provider 可达，但没有返回可用的可见回复。",
        ),
        "malformed_response": (
            "The endpoint responded, but the payload did not match the configured protocol.",
            "这个 endpoint 有响应，但 payload 不符合当前配置的 protocol。",
        ),
        "rate_limit": (
            "The provider rate-limited this turn before Trainer could continue.",
            "这个 provider 对这一轮请求触发了 rate limit，Trainer 暂时不能继续。",
        ),
        "timeout": (
            "Trainer could not get a response from the provider before the timeout.",
            "Trainer 在 timeout 前没有从 provider 收到响应。",
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
            "Trainer 这一轮被 provider path 卡住了。",
        ),
    )
    return _localized_text(english, chinese, response_language)


def _clean_provider_failure_next_step(
    self,
    category: str,
    response_language: str | None,
) -> str:
    if category == "streaming_unavailable":
        return _localized_text(
            "Choose a provider and model with verified native streaming in Settings, retest it, and resend this exact turn.",
            "先在设置里选择已验证支持原生流式的 provider 和 model，重新测试后再重发这一轮。",
            response_language,
        )
    next_step_map: dict[str, tuple[str, str]] = {
        "invalid_key_or_permission": (
            "Check the API key or provider permissions, retest the connection, and resend this exact turn.",
            "先检查 API key 或 provider permission，重新测试连接后再重发这一轮。",
        ),
        "model_unsupported": (
            "Switch to a model name that this provider actually supports, retest, and resend this exact turn.",
            "先换成这个 provider 真正支持的 model name，重新测试后再重发这一轮。",
        ),
        "model_not_found": (
            "Pick a channel-backed model at this gateway, retest, and resend this exact turn.",
            "先换成这个 gateway 里真实可用的 model，重新测试后再重发这一轮。",
        ),
        "language_corruption": (
            "Switch provider or gateway first, then resend this same turn after the visible corruption disappears.",
            "先切换 provider 或 gateway，确认乱码消失后再重发这一轮。",
        ),
        "language_probe_inconclusive": (
            "Retest with a zh-CN probe before trusting this provider for Chinese coaching turns.",
            "先用 zh-CN probe 重新测试，再把这个 provider 用于中文 coaching。",
        ),
        "empty_response": (
            "Retest with a visible-text probe or switch to a model that returns visible text.",
            "先用 visible-text probe 重新测试，或切换到会返回可见文本的 model。",
        ),
        "malformed_response": (
            "Check that the endpoint really speaks the configured protocol, then retest and resend this exact turn.",
            "先确认这个 endpoint 真的支持当前配置的 protocol，再测试并重发这一轮。",
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


def _clean_provider_failure_reply(
    self,
    category: str,
    detail: str | None,
    response_language: str | None,
) -> str:
    detail_text = _compact_text(
        redact_provider_error({"upstream_body": detail}, api_key=self._api_key)
    )
    summary = self.provider_failure_summary(category, response_language)
    next_step = self.provider_failure_next_step(category, response_language)
    if _prefers_chinese(response_language):
        lines = [
            "Trainer 当前卡在 provider path，所以这轮 coaching 还不能继续。",
            "",
            summary,
        ]
        if detail_text:
            lines.append(f"详情：{detail_text}")
        lines.append(f"下一步：{next_step}")
        return "\n".join(lines)
    if detail_text:
        return (
            "Trainer is blocked on the provider path, so I cannot continue this coaching turn yet.\n\n"
            f"{summary}\nDetail: {detail_text}\nNext: {next_step}"
        )
    return (
        "Trainer is blocked on the provider path, so I cannot continue this coaching turn yet.\n\n"
        f"{summary}\nNext: {next_step}"
    )


ProviderService._onboarding_reply = _clean_provider_service_onboarding_reply
ProviderService._error_reply = _clean_provider_service_error_reply
ProviderService._missing_api_key_reply = _clean_provider_service_missing_api_key_reply
ProviderService.provider_failure_summary = _clean_provider_failure_summary
ProviderService.provider_failure_next_step = _clean_provider_failure_next_step
ProviderService.provider_failure_reply = _clean_provider_failure_reply


def _clean_agentic_fallback_continuity(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> tuple[str, str]:
    context = extract_coaching_context(message, current_file, coach_context)
    chinese = _prefers_chinese(response_language)
    summary = str(
        context.get("thread_summary")
        or context.get("summary")
        or context.get("current_focus")
        or context.get("continuity_summary")
        or context.get("review_queue_summary")
        or ""
    ).strip()
    if not summary:
        summary = (
            "This turn needs a fresh provider retry, but the same thread can continue."
            if not chinese
            else "这轮 provider 需要重新连接，但同一条学习线可以继续。"
        )

    scenario = str(context.get("scenario") or "general").strip()
    next_step_hint = _prefer_structured_next_step(
        scenario=scenario,
        next_step_hint=_extract_next_step_hint_text(
            context.get("thread_next_step")
            or context.get("resume_hint")
            or context.get("next_step_hint")
        ),
        implementation_guide=(
            context.get("implementation_guide")
            if isinstance(context.get("implementation_guide"), dict)
            else {}
        ),
        adaptation_guide=(
            context.get("project_adaptation_guide")
            if isinstance(context.get("project_adaptation_guide"), dict)
            else context.get("adaptation_guide")
            if isinstance(context.get("adaptation_guide"), dict)
            else {}
        ),
        principle_note=(
            context.get("principle_notes")
            if isinstance(context.get("principle_notes"), dict)
            else context.get("principle_note")
            if isinstance(context.get("principle_note"), dict)
            else {}
        ),
        project_ideas=(
            [item for item in context.get("project_ideas", []) if isinstance(item, dict)]
            if isinstance(context.get("project_ideas"), list)
            else []
        ),
        exercise_prompt=(
            context.get("exercise_prompt")
            if isinstance(context.get("exercise_prompt"), dict)
            else {}
        ),
    )
    next_step = str(
        next_step_hint
        or context.get("thread_next_step")
        or context.get("resume_hint")
        or context.get("next_step")
        or context.get("continuity_summary")
        or context.get("review_queue_summary")
        or ""
    ).strip()
    if not next_step:
        next_step = (
            "Retry from the smallest verified step after checking the provider connection."
            if not chinese
            else "先检查 provider connection，再从已验证的最小步骤继续。"
        )
    return summary, next_step


_agentic_fallback_continuity = _clean_agentic_fallback_continuity


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
