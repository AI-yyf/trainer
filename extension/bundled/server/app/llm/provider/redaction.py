"""Provider error redaction (§五十二: extracted from provider_service.py).

Ensures API keys, bearer tokens, upstream response bodies, tracebacks,
and hidden reasoning never appear in diagnostics or SSE output.
"""

from __future__ import annotations

import json
import re

# ---------------------------------------------------------------------------
# Regex constants
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compact_text(value: object | None, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 1)].rstrip()}..."


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
