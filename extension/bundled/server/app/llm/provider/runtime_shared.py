from __future__ import annotations

import logging
import re

import httpx

from ...core.models import (
    ProviderProbeUsage,
)
from ..harness import extract_provider_usage
from ..provider_protocols import (
    normalize_provider_response,
)
from .context_budget import (
    MIN_CONTEXT_OUTPUT_TOKENS as MIN_CONTEXT_OUTPUT_TOKENS,
)
from .errors import (
    ProviderRuntimeResponseError,
)
from .language_probes import (
    _LANGUAGE_PROBE_VARIANTS as _LANGUAGE_PROBE_VARIANTS,
)
from .language_probes import (
    _NATURAL_LANGUAGE_PROBE_FRAGMENTS as _NATURAL_LANGUAGE_PROBE_FRAGMENTS,
)
from .language_probes import (
    _NATURAL_LANGUAGE_PROBE_PROMPT as _NATURAL_LANGUAGE_PROBE_PROMPT,
)
from .model_catalog import (
    _ANTHROPIC_MODELS_PAGE_SIZE as _ANTHROPIC_MODELS_PAGE_SIZE,
)
from .model_catalog import (
    _GEMINI_MODELS_PAGE_SIZE as _GEMINI_MODELS_PAGE_SIZE,
)
from .model_catalog import (
    _NATIVE_MODEL_DISCOVERY_MAX_MODELS as _NATIVE_MODEL_DISCOVERY_MAX_MODELS,
)
from .model_catalog import (
    _NATIVE_MODEL_DISCOVERY_MAX_PAGES as _NATIVE_MODEL_DISCOVERY_MAX_PAGES,
)

logger = logging.getLogger(__name__)

logger = logging.getLogger("trainer.provider")


def _looks_like_tools_unsupported_error(detail: object) -> bool:
    """Return True when a provider error indicates function/tool schemas were rejected."""
    raw = str(detail or "").strip().lower()
    if not raw:
        return False
    has_tool_term = any(
        term in raw
        for term in (
            "tool",
            "tools",
            "tool_choice",
            "function",
            "functions",
            "function_calling",
        )
    )
    if not has_tool_term:
        return False
    return any(
        marker in raw
        for marker in (
            "not support",
            "unsupported",
            "not enabled",
            "unavailable",
            "unknown parameter",
            "unrecognized",
            "not allowed",
            "cannot use",
            "does not support",
            "不支持",
        )
    )

DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS = 45.0
DEFAULT_OPENAI_CLIENT_MAX_RETRIES = 0
MIN_OPENAI_CLIENT_TIMEOUT_SECONDS = 5.0
FORMAL_PLAN_OUTPUT_TOKENS = 4096
LECTURE_OUTPUT_TOKENS = 4096
# Generation (chat completions, streams, agent turns) carries NO designed
# read-time ceiling: reasoning-first models think for as long as the task
# needs, and a fixed read cap converts long reasoning into a false timeout
# (measured: a 45s cap killed real MiniMax-M3.x card authoring twice in a
# row). Liveness comes from the stream guards (the agent loop's idle watchdog
# and step budgets, the plain stream's idle ceiling) and from transport errors
# — not from an arbitrary wall. The transport read timeout is only a last
# resort for a path with no guard at all: five minutes without a single byte
# from the provider is a dead connection, never a model still thinking.
# Probe/control calls keep the bounded 45s via per-request overrides.
GENERATION_READ_BACKSTOP_SECONDS = 300.0
GENERATION_CLIENT_TIMEOUT = httpx.Timeout(
    connect=10.0, write=60.0, pool=30.0, read=GENERATION_READ_BACKSTOP_SECONDS
)
#: Sentinel: a rejected request named no repairable parameter.
_NOT_REPAIRED = object()

_TOOL_CAPABILITY_PROBE_NAME = "trainer_capability_probe"
#: Output cap for the forced no-op tool call; a reasoning model gets one
#: escalated retry (see ``_probe_tool_capability``).
_TOOL_PROBE_OUTPUT_TOKENS = 64
_TOOL_CAPABILITY_PROBE_PROMPT = (
    "Call the supplied trainer_capability_probe tool now with probe set to ok. "
    "Do not call external services and do not return text."
)
# Native model discovery walks cursor pages until the provider says the
# catalog is exhausted. The caps below are purely defensive: they stop a
# misbehaving (or hostile) endpoint from turning discovery into an endless
# request loop, and the truncated catalog is reported with incomplete=True.


# _compact_text is imported from .provider.redaction above (§五十二 extraction).


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
