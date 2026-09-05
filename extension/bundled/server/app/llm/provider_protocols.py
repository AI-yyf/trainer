from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ..core.models import (
    CapabilityFlags,
    ProviderProtocol,
    ProviderProtocolCatalogEntry,
    ProviderProtocolFamily,
)

ProviderProtocolTestMode = Literal["openai_chat", "responses", "anthropic", "gemini"]
ProviderCapabilityName = Literal[
    "chat",
    "responses",
    "vision",
    "embeddings",
    "tools",
    "json_schema",
    "structured_output",
    "streaming",
    "thinking",
    "model_listing",
]
ProviderCapabilityState = Literal["verified", "unsupported", "unverified", "disabled"]
ProviderResponseOutcome = Literal[
    "visible_text",
    "tool_calls",
    "empty_response",
    "reasoning_only",
    "truncated",
    "protocol_mismatch",
    "provider_error",
]
ProviderErrorCategory = Literal["protocol_mismatch", "provider_error"]

_CAPABILITY_NAMES: tuple[ProviderCapabilityName, ...] = (
    "chat",
    "responses",
    "vision",
    "embeddings",
    "tools",
    "json_schema",
    "structured_output",
    "streaming",
    "thinking",
    "model_listing",
)
_CAPABILITY_ALIASES: dict[str, ProviderCapabilityName] = {
    "chat": "chat",
    "responses": "responses",
    "vision": "vision",
    "embeddings": "embeddings",
    "tools": "tools",
    "jsonschema": "json_schema",
    "structuredoutput": "structured_output",
    "streaming": "streaming",
    "thinking": "thinking",
    "reasoning": "thinking",
    "modellisting": "model_listing",
    "models": "model_listing",
    "listing": "model_listing",
}

_THINK_BLOCK_PATTERN = re.compile(
    r"<(?:think|thinking|analysis)\b[^>]*>.*?</(?:think|thinking|analysis)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_OPEN_THINK_BLOCK_PATTERN = re.compile(
    r"<(?:think|thinking|analysis)\b[^>]*>.*$",
    re.IGNORECASE | re.DOTALL,
)
_SECRET_FIELD_PATTERN = re.compile(
    r"(?P<name>\b(?:api[-_]?key|access[-_]?token|auth(?:orization)?|token|secret|password|"
    r"client[-_]?secret|key)\b)(?P<separator>\s*[:=]\s*)(?P<value>\"[^\"]*\"|'[^']*'|[^,\s}\]]+)",
    re.IGNORECASE,
)
_SECRET_QUERY_PATTERN = re.compile(
    r"(?P<prefix>[?&](?:[a-z0-9]+[-_])*(?:api[-_]?key|access[-_]?token|auth(?:orization)?|"
    r"token|secret|password|client[-_]?secret|key)=)[^&#\s]+",
    re.IGNORECASE,
)
_BEARER_TOKEN_PATTERN = re.compile(r"\bBearer\s+[^\s,;]+", re.IGNORECASE)
_KEY_LIKE_TOKEN_PATTERN = re.compile(r"\b(?:sk|pk|rk|AIza)[-_A-Za-z0-9]{8,}\b")
_UPSTREAM_BODY_PATTERN = re.compile(
    r"(?P<prefix>\b(?:upstream|provider|response)\s+(?:body|payload|content)\s*"
    r"(?:[:=]|was|is)\s*)(?P<body>.+)",
    re.IGNORECASE | re.DOTALL,
)
_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "accesstoken",
        "authorization",
        "token",
        "secret",
        "password",
        "client_secret",
        "clientsecret",
        "key",
    }
)
_UPSTREAM_BODY_FIELD_NAMES = frozenset({"body", "payload", "content", "response", "upstream_body"})
_TRUNCATION_MARKERS = frozenset(
    {
        "length",
        "max_tokens",
        "max_output_tokens",
        "max_completion_tokens",
        "max_tokens_reached",
        "incomplete",
        "token_limit",
    }
)
_PROTOCOL_MISMATCH_STATUS_CODES = frozenset({400, 404, 405, 415, 422})
_PROTOCOL_MISMATCH_MARKERS: dict[ProviderProtocol, tuple[str, ...]] = {
    "openai_responses": ("/v1/responses", "responses"),
    "openai_chat_completions": ("/v1/chat/completions", "chat/completions"),
    "openai_chat_completions_compatible": ("/v1/chat/completions", "chat/completions"),
    "anthropic_messages": ("/v1/messages", "anthropic-version", "x-api-key"),
    "gemini_generate_content": ("generatecontent", "generate_content", ":generatecontent"),
}
_ENDPOINT_REJECTION_MARKERS = (
    "invalid url",
    "invalid endpoint",
    "unsupported endpoint",
    "unsupported protocol",
    "protocol mismatch",
    "not found",
    "method not allowed",
    "unsupported media type",
    "invalid_request_error",
)


@dataclass(frozen=True, slots=True)
class ProviderCapabilityEvidence:
    """The configured claim and observed result for one capability."""

    name: ProviderCapabilityName
    declared: bool
    observed: bool | None
    state: ProviderCapabilityState


@dataclass(frozen=True, slots=True)
class ProviderCapabilityAssessment:
    """Capability truth that keeps configuration claims separate from probe evidence."""

    protocol: ProviderProtocol | None
    evidence: tuple[ProviderCapabilityEvidence, ...]

    def for_capability(self, name: str) -> ProviderCapabilityEvidence | None:
        normalized = normalize_provider_capability_name(name)
        if normalized is None:
            return None
        return next((item for item in self.evidence if item.name == normalized), None)

    def supports(self, name: str, *, require_verified: bool = True) -> bool:
        evidence = self.for_capability(name)
        if evidence is None:
            return False
        if require_verified:
            return evidence.state == "verified"
        return evidence.state in {"verified", "unverified"}


@dataclass(frozen=True, slots=True)
class ProviderResponseAssessment:
    """Canonical, safe-to-diagnose result of one provider response."""

    protocol: ProviderProtocol | None
    detected_protocol: ProviderProtocol | None
    content: str
    outcome: ProviderResponseOutcome
    error_category: str | None
    retryable: bool
    truncated: bool
    hidden_reasoning_observed: bool
    tool_call_count: int
    finish_reason: str | None
    diagnostic: str

    @property
    def has_visible_text(self) -> bool:
        return bool(self.content.strip())


@dataclass(frozen=True, slots=True)
class ProviderToolProbeAssessment:
    """Safe verdict for a forced, no-op structured tool-call probe."""

    protocol: ProviderProtocol | None
    observed: bool | None
    state: ProviderCapabilityState
    diagnostic: str


@dataclass(frozen=True, slots=True)
class ProviderVisionProbeAssessment:
    """Safe verdict for the fixed OpenAI Chat vision probe."""

    protocol: ProviderProtocol | None
    observed: bool | None
    state: ProviderCapabilityState
    category: str
    diagnostic: str


@dataclass(frozen=True, slots=True)
class ProviderErrorAssessment:
    """A provider failure classified without exposing an upstream body."""

    protocol: ProviderProtocol | None
    category: ProviderErrorCategory
    status_code: int | None
    retryable: bool
    diagnostic: str


SUPPORTED_PROVIDER_PROTOCOLS: tuple[ProviderProtocol, ...] = (
    "openai_responses",
    "openai_chat_completions",
    "anthropic_messages",
    "openai_chat_completions_compatible",
    "gemini_generate_content",
)

_PROTOCOL_FAMILIES: dict[ProviderProtocol, ProviderProtocolFamily] = {
    "openai_responses": "openai",
    "openai_chat_completions": "openai",
    "openai_chat_completions_compatible": "openai",
    "anthropic_messages": "anthropic",
    "gemini_generate_content": "gemini",
}

_PROTOCOL_ENDPOINT_HINTS: dict[ProviderProtocol, str] = {
    "openai_responses": "/v1/responses",
    "openai_chat_completions": "/v1/chat/completions",
    "openai_chat_completions_compatible": "/v1/chat/completions",
    "anthropic_messages": "/v1/messages",
    "gemini_generate_content": "google.genai.models.generate_content",
}

_PROTOCOL_REQUIRED_CAPABILITIES: dict[ProviderProtocol, str | None] = {
    "openai_responses": "responses",
    "openai_chat_completions": "chat",
    "openai_chat_completions_compatible": "chat",
    "anthropic_messages": "chat",
    "gemini_generate_content": "chat",
}

_PROTOCOL_CLIENT_KINDS: dict[ProviderProtocol, str] = {
    "openai_responses": "openai",
    "openai_chat_completions": "openai",
    "openai_chat_completions_compatible": "openai",
    "anthropic_messages": "anthropic",
    "gemini_generate_content": "gemini",
}

_PROTOCOL_DIAGNOSTIC_NOTES: dict[ProviderProtocol, tuple[str, ...]] = {
    "openai_responses": (
        "Responses mode uses typed input parts and structured output extraction.",
    ),
    "openai_chat_completions": (
        "Chat completions mode uses an OpenAI-style chat.completions surface.",
    ),
    "openai_chat_completions_compatible": (
        "Compatible mode assumes an OpenAI-style chat.completions surface.",
    ),
    "anthropic_messages": ("Anthropic Messages uses a system prompt plus structured messages.",),
    "gemini_generate_content": (
        "Gemini GenerateContent uses SDK-native content submission and text extraction.",
    ),
}

_PROTOCOL_COMPLETION_LABELS: dict[ProviderProtocol, str] = {
    "openai_responses": "OpenAI Responses",
    "openai_chat_completions": "OpenAI Chat Completions",
    "openai_chat_completions_compatible": "OpenAI-compatible chat completions",
    "anthropic_messages": "Anthropic Messages",
    "gemini_generate_content": "Gemini GenerateContent",
}

_PROTOCOL_TEST_MODEL_HINTS: dict[ProviderProtocol, str] = {
    "anthropic_messages": "claude-3-haiku-20240307",
    "gemini_generate_content": "gemini-2.0-flash",
}

_PROTOCOL_MODEL_SUPPORTS: dict[ProviderProtocol, Callable[[CapabilityFlags], bool]] = {
    "openai_responses": lambda model_capabilities: bool(model_capabilities.responses),
    "openai_chat_completions": lambda model_capabilities: bool(model_capabilities.chat),
    "openai_chat_completions_compatible": lambda model_capabilities: bool(model_capabilities.chat),
    "anthropic_messages": lambda model_capabilities: bool(
        model_capabilities.chat or model_capabilities.tools,
    ),
    "gemini_generate_content": lambda model_capabilities: bool(
        model_capabilities.chat or model_capabilities.vision,
    ),
}

_PROTOCOL_TEST_MODES: dict[ProviderProtocol, ProviderProtocolTestMode] = {
    "openai_responses": "responses",
    "openai_chat_completions": "openai_chat",
    "openai_chat_completions_compatible": "openai_chat",
    "anthropic_messages": "anthropic",
    "gemini_generate_content": "gemini",
}


def is_supported_provider_protocol(value: object) -> bool:
    return value in SUPPORTED_PROVIDER_PROTOCOLS


def normalize_provider_protocol(value: ProviderProtocol | str | None) -> ProviderProtocol | None:
    if isinstance(value, str):
        stripped = value.strip()
        for protocol in SUPPORTED_PROVIDER_PROTOCOLS:
            if stripped == protocol:
                return protocol
        return None
    return None


def normalize_provider_capability_name(value: str | None) -> ProviderCapabilityName | None:
    """Normalize Python and JSON aliases without silently accepting unknown claims."""
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[^a-z0-9]", "", value.strip().lower())
    return _CAPABILITY_ALIASES.get(normalized)


def assess_provider_capabilities(
    protocol: ProviderProtocol | str | None,
    declared: CapabilityFlags | Mapping[str, object] | None,
    observed: Mapping[str, bool | None] | None = None,
) -> ProviderCapabilityAssessment:
    """Separate configured capabilities from outcomes observed by a real probe.

    A protocol default or profile declaration is deliberately never treated as
    verification. A capability becomes ``verified`` only after an explicit
    ``True`` observation; a failed probe is ``unsupported``; unprobed claims
    remain ``unverified``.
    """
    resolved_protocol = normalize_provider_protocol(protocol)
    observations = _normalize_capability_observations(observed)
    evidence: list[ProviderCapabilityEvidence] = []
    for name in _CAPABILITY_NAMES:
        declared_value = _read_capability_value(declared, name)
        observed_value = observations.get(name)
        if observed_value is True:
            state: ProviderCapabilityState = "verified"
        elif observed_value is False:
            state = "unsupported"
        elif name in observations:
            state = "unverified"
        elif declared_value:
            state = "unverified"
        else:
            state = "disabled"
        evidence.append(
            ProviderCapabilityEvidence(
                name=name,
                declared=declared_value,
                observed=observed_value,
                state=state,
            )
        )
    return ProviderCapabilityAssessment(protocol=resolved_protocol, evidence=tuple(evidence))


def normalize_provider_response(
    protocol: ProviderProtocol | str | None,
    response: object | None,
    *,
    api_key: str | None = None,
) -> ProviderResponseAssessment:
    """Extract a canonical response without presenting hidden or incompatible data.

    The returned diagnostic is intentionally derived from response shape and
    outcome only. It never embeds an upstream body, reasoning text, tool
    arguments, or credentials.
    """
    resolved_protocol = normalize_provider_protocol(protocol)
    upstream_error = _get_field(response, "error")
    if _has_substantive_value(upstream_error):
        failure = assess_provider_error(
            resolved_protocol,
            upstream_error,
            status_code=_extract_status_code(response),
            api_key=api_key,
        )
        return ProviderResponseAssessment(
            protocol=resolved_protocol,
            detected_protocol=None,
            content="",
            outcome=failure.category,
            error_category=failure.category,
            retryable=failure.retryable,
            truncated=False,
            hidden_reasoning_observed=False,
            tool_call_count=0,
            finish_reason=None,
            diagnostic=failure.diagnostic,
        )

    detected_protocol = detect_provider_response_protocol(response)
    if (
        resolved_protocol is not None
        and detected_protocol is not None
        and not _response_matches_protocol(
            resolved_protocol,
            detected_protocol,
        )
    ):
        return ProviderResponseAssessment(
            protocol=resolved_protocol,
            detected_protocol=detected_protocol,
            content="",
            outcome="protocol_mismatch",
            error_category="protocol_mismatch",
            retryable=False,
            truncated=False,
            hidden_reasoning_observed=False,
            tool_call_count=0,
            finish_reason=None,
            diagnostic=(
                f"Received {provider_protocol_completion_label(detected_protocol)} response data "
                f"while configured for {provider_protocol_completion_label(resolved_protocol)}."
            ),
        )

    parts = _extract_response_parts(resolved_protocol, response)
    if parts.truncated:
        outcome: ProviderResponseOutcome = "truncated"
        error_category: str | None = "truncated_or_empty"
        retryable = True
        diagnostic = "Provider response reached its output limit before completion."
    elif parts.content.strip():
        outcome = "visible_text"
        error_category = None
        retryable = False
        diagnostic = "Provider returned visible text."
    elif parts.tool_call_count:
        outcome = "tool_calls"
        error_category = None
        retryable = False
        diagnostic = "Provider returned tool calls without a user-facing text reply."
    elif parts.hidden_reasoning_observed:
        outcome = "reasoning_only"
        error_category = "reasoning_leak"
        retryable = True
        diagnostic = "Provider returned hidden reasoning without visible text."
    else:
        outcome = "empty_response"
        error_category = "empty_response"
        retryable = True
        diagnostic = "Provider returned no visible text, tool call, or completion signal."

    return ProviderResponseAssessment(
        protocol=resolved_protocol,
        detected_protocol=detected_protocol,
        content=parts.content,
        outcome=outcome,
        error_category=error_category,
        retryable=retryable,
        truncated=parts.truncated,
        hidden_reasoning_observed=parts.hidden_reasoning_observed,
        tool_call_count=parts.tool_call_count,
        finish_reason=parts.finish_reason,
        diagnostic=diagnostic,
    )


def assess_provider_tool_call_probe(
    protocol: ProviderProtocol | str | None,
    response: object | None,
    *,
    expected_tool_name: str,
    api_key: str | None = None,
) -> ProviderToolProbeAssessment:
    """Assess a forced tool-call response without exposing provider payloads.

    A declared tool flag is intentionally not evidence. Only the requested
    structured tool call verifies the capability. Text-only replies are a
    negative observation because the request forced a tool; malformed,
    hidden, truncated, or protocol-mismatched replies remain unverified.
    """
    resolved_protocol = normalize_provider_protocol(protocol)
    response_assessment = normalize_provider_response(
        resolved_protocol,
        response,
        api_key=api_key,
    )
    parts = _extract_response_parts(resolved_protocol, response)
    expected = expected_tool_name.strip()
    if expected and expected in parts.tool_call_names:
        return ProviderToolProbeAssessment(
            protocol=resolved_protocol,
            observed=True,
            state="verified",
            diagnostic="Provider returned the requested structured tool call.",
        )
    if response_assessment.outcome == "visible_text":
        return ProviderToolProbeAssessment(
            protocol=resolved_protocol,
            observed=False,
            state="unsupported",
            diagnostic="Provider returned visible text instead of the requested structured tool call.",
        )
    if response_assessment.outcome == "tool_calls":
        return ProviderToolProbeAssessment(
            protocol=resolved_protocol,
            observed=None,
            state="unverified",
            diagnostic="Provider returned an unexpected or incomplete structured tool call.",
        )
    return ProviderToolProbeAssessment(
        protocol=resolved_protocol,
        observed=None,
        state="unverified",
        diagnostic="Provider tool-call probe did not return a usable structured tool call.",
    )


def assess_provider_vision_probe(
    protocol: ProviderProtocol | str | None,
    response: object | None,
    *,
    expected_token: str,
    api_key: str | None = None,
) -> ProviderVisionProbeAssessment:
    """Assess a fixed vision response without exposing image or upstream data."""
    resolved_protocol = normalize_provider_protocol(protocol)
    if resolved_protocol not in {
        "openai_responses",
        "openai_chat_completions",
        "openai_chat_completions_compatible",
        "gemini_generate_content",
    }:
        return ProviderVisionProbeAssessment(
            protocol=resolved_protocol,
            observed=None,
            state="unverified",
            category="protocol_not_supported",
            diagnostic=(
                "Vision probe is supported only for OpenAI Chat and native Gemini protocols."
            ),
        )
    assessment = normalize_provider_response(resolved_protocol, response, api_key=api_key)
    if assessment.outcome == "visible_text":
        if assessment.content.strip() == expected_token.strip():
            return ProviderVisionProbeAssessment(
                protocol=resolved_protocol,
                observed=True,
                state="verified",
                category="verified",
                diagnostic="Vision probe returned the expected token.",
            )
        return ProviderVisionProbeAssessment(
            protocol=resolved_protocol,
            observed=False,
            state="unsupported",
            category="token_mismatch",
            diagnostic="Vision probe returned visible text other than the expected token.",
        )
    if assessment.outcome in {"provider_error", "protocol_mismatch"}:
        return ProviderVisionProbeAssessment(
            protocol=resolved_protocol,
            observed=None,
            state="unverified",
            category=assessment.error_category or assessment.outcome,
            diagnostic="Vision probe could not be completed safely.",
        )
    return ProviderVisionProbeAssessment(
        protocol=resolved_protocol,
        observed=None,
        state="unverified",
        category=assessment.error_category or assessment.outcome,
        diagnostic="Vision probe did not return a usable visible token.",
    )


def detect_provider_response_protocol(value: object | None) -> ProviderProtocol | None:
    """Infer only protocol shapes that are distinguishable without payload logging."""
    if value is None or isinstance(value, str):
        return None
    if _get_field(value, "choices") is not None:
        return "openai_chat_completions"
    if _get_field(value, "output_text") is not None or _get_field(value, "output") is not None:
        return "openai_responses"
    if _get_field(value, "candidates") is not None:
        return "gemini_generate_content"

    content = _get_field(value, "content")
    if _get_field(value, "stop_reason") is not None and _is_nontext_sequence(content):
        return "anthropic_messages"
    return None


def assess_provider_error(
    protocol: ProviderProtocol | str | None,
    error: object | None,
    *,
    status_code: int | None = None,
    api_key: str | None = None,
) -> ProviderErrorAssessment:
    """Classify a protocol failure while keeping the raw provider message private."""
    resolved_protocol = normalize_provider_protocol(protocol)
    resolved_status = _coerce_status_code(status_code) or _extract_status_code(error)
    if _looks_like_protocol_mismatch(resolved_protocol, error, resolved_status):
        return ProviderErrorAssessment(
            protocol=resolved_protocol,
            category="protocol_mismatch",
            status_code=resolved_status,
            retryable=False,
            diagnostic=(
                f"{provider_protocol_completion_label(resolved_protocol)} endpoint rejected the "
                "configured protocol shape."
            ),
        )

    retryable = bool(
        resolved_status is not None and (resolved_status == 429 or 500 <= resolved_status <= 599)
    )
    return ProviderErrorAssessment(
        protocol=resolved_protocol,
        category="provider_error",
        status_code=resolved_status,
        retryable=retryable,
        diagnostic=safe_provider_diagnostic(error, api_key=api_key),
    )


def safe_provider_diagnostic(
    value: object | None,
    *,
    api_key: str | None = None,
    fallback: str = "Provider request failed",
    limit: int = 400,
) -> str:
    """Return a bounded diagnostic that cannot expose credentials or upstream bodies."""
    status_code = _extract_status_code(value)
    if isinstance(value, BaseException):
        return _fallback_diagnostic(fallback, status_code)
    if isinstance(value, Mapping):
        suffix = (
            "credentials redacted"
            if _mapping_contains_sensitive_value(value)
            else "upstream body redacted"
        )
        return _fallback_diagnostic(f"{fallback}; {suffix}", status_code)
    if value is None:
        return _fallback_diagnostic(fallback, status_code)

    text = str(value)
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = _SECRET_QUERY_PATTERN.sub(r"\g<prefix>[REDACTED]", text)
    text = _BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", text)
    text = _KEY_LIKE_TOKEN_PATTERN.sub("[REDACTED]", text)
    text = _SECRET_FIELD_PATTERN.sub(
        lambda match: f"{match.group('name')}{match.group('separator')}[REDACTED]",
        text,
    )
    text = _UPSTREAM_BODY_PATTERN.sub(
        lambda match: f"{match.group('prefix')}[REDACTED_UPSTREAM_BODY]",
        text,
    )
    compacted = " ".join(text.split()).strip()
    if not compacted:
        return _fallback_diagnostic(fallback, status_code)
    bounded_limit = max(32, limit)
    if len(compacted) > bounded_limit:
        compacted = f"{compacted[: bounded_limit - 3].rstrip()}..."
    return compacted


def _normalize_capability_observations(
    observed: Mapping[str, bool | None] | None,
) -> dict[ProviderCapabilityName, bool | None]:
    normalized: dict[ProviderCapabilityName, bool | None] = {}
    if observed is None:
        return normalized
    for key, value in observed.items():
        capability = normalize_provider_capability_name(key)
        if capability is not None and (value is None or isinstance(value, bool)):
            normalized[capability] = value
    return normalized


def _read_capability_value(
    declared: CapabilityFlags | Mapping[str, object] | None,
    name: ProviderCapabilityName,
) -> bool:
    if declared is None:
        return False
    if isinstance(declared, Mapping):
        for key, value in declared.items():
            if normalize_provider_capability_name(str(key)) == name and isinstance(value, bool):
                return value
        return False
    value = getattr(declared, name, None)
    return value if isinstance(value, bool) else False


@dataclass(slots=True)
class _ResponseParts:
    content: str = ""
    hidden_reasoning_observed: bool = False
    tool_call_count: int = 0
    tool_call_names: tuple[str, ...] = ()
    finish_reason: str | None = None
    truncated: bool = False


def _extract_response_parts(protocol: ProviderProtocol | None, response: object | None) -> _ResponseParts:
    if isinstance(response, str):
        content, hidden_reasoning_observed = _visible_text_from_value(response)
        return _ResponseParts(
            content=content,
            hidden_reasoning_observed=hidden_reasoning_observed,
        )
    if protocol == "openai_responses":
        return _extract_openai_responses_parts(response)
    if protocol == "anthropic_messages":
        return _extract_anthropic_parts(response)
    if protocol == "gemini_generate_content":
        return _extract_gemini_parts(response)
    return _extract_openai_chat_parts(response)


def _extract_openai_chat_parts(response: object | None) -> _ResponseParts:
    choices = _get_field(response, "choices")
    choice = _first_item(choices)
    message = _get_field(choice, "message") if choice is not None else None
    source = message if message is not None else (choice if choice is not None else response)
    content, hidden = _visible_text_from_value(_get_field(source, "content"))
    hidden = hidden or _has_reasoning_fields(response) or _has_reasoning_fields(choice)
    hidden = hidden or _has_reasoning_fields(source)
    finish_reason = _first_string_field(choice, "finish_reason", "finishReason")
    finish_reason = finish_reason or _first_string_field(response, "finish_reason", "finishReason")
    return _ResponseParts(
        content=content,
        hidden_reasoning_observed=hidden,
        tool_call_count=_tool_call_count(source),
        tool_call_names=_tool_call_names(source),
        finish_reason=finish_reason,
        truncated=_finish_reason_is_truncated(finish_reason),
    )


def _extract_openai_responses_parts(response: object | None) -> _ResponseParts:
    text_parts: list[str] = []
    hidden = _has_reasoning_fields(response)
    direct_text, direct_hidden = _visible_text_from_value(_get_field(response, "output_text"))
    hidden = hidden or direct_hidden
    tool_call_count = 0
    tool_call_names: list[str] = []
    for item in _as_sequence(_get_field(response, "output")):
        item_type = _normalized_identifier(_get_field(item, "type"))
        if item_type in {"reasoning", "thinking", "analysis"}:
            hidden = True
            continue
        if item_type in {"functioncall", "toolcall"}:
            tool_call_count += 1
            name = _tool_name_from_call(item)
            if name:
                tool_call_names.append(name)
            continue
        content, content_hidden = _visible_text_from_value(_get_field(item, "content"))
        if content:
            text_parts.append(content)
        hidden = hidden or content_hidden or _has_reasoning_fields(item)
    finish_reason = _first_string_field(response, "finish_reason", "finishReason", "status")
    incomplete_details = _get_field(response, "incomplete_details")
    finish_reason = finish_reason or _first_string_field(incomplete_details, "reason")
    nested_text = "".join(text_parts).strip()
    return _ResponseParts(
        content=_merge_visible_text(direct_text, nested_text),
        hidden_reasoning_observed=hidden,
        tool_call_count=tool_call_count,
        tool_call_names=tuple(tool_call_names),
        finish_reason=finish_reason,
        truncated=_finish_reason_is_truncated(finish_reason),
    )


def _extract_anthropic_parts(response: object | None) -> _ResponseParts:
    text_parts: list[str] = []
    hidden = _has_reasoning_fields(response)
    tool_call_count = 0
    tool_call_names: list[str] = []
    for block in _as_sequence(_get_field(response, "content")):
        block_type = _normalized_identifier(_get_field(block, "type"))
        if block_type in {"thinking", "redactedthinking", "reasoning", "analysis"}:
            hidden = True
            continue
        if block_type == "tooluse":
            tool_call_count += 1
            name = _tool_name_from_call(block)
            if name:
                tool_call_names.append(name)
            continue
        text, text_hidden = _visible_text_from_value(_get_field(block, "text"))
        if text:
            text_parts.append(text)
        hidden = hidden or text_hidden or _has_reasoning_fields(block)
    finish_reason = _first_string_field(response, "stop_reason", "stopReason")
    return _ResponseParts(
        content="".join(text_parts).strip(),
        hidden_reasoning_observed=hidden,
        tool_call_count=tool_call_count,
        tool_call_names=tuple(tool_call_names),
        finish_reason=finish_reason,
        truncated=_finish_reason_is_truncated(finish_reason),
    )


def _extract_gemini_parts(response: object | None) -> _ResponseParts:
    text_parts: list[str] = []
    hidden = _has_reasoning_fields(response)
    tool_call_count = 0
    tool_call_names: list[str] = []
    finish_reason: str | None = None
    for candidate in _as_sequence(_get_field(response, "candidates")):
        finish_reason = finish_reason or _first_string_field(
            candidate,
            "finish_reason",
            "finishReason",
        )
        content = _get_field(candidate, "content")
        for part in _as_sequence(_get_field(content, "parts")):
            if _get_field(part, "thought") is True:
                hidden = True
                continue
            function_call = _get_field(part, "functionCall") or _get_field(part, "function_call")
            if _has_substantive_value(function_call):
                tool_call_count += 1
                name = _tool_name_from_call(function_call)
                if name:
                    tool_call_names.append(name)
                continue
            text, text_hidden = _visible_text_from_value(_get_field(part, "text"))
            if text:
                text_parts.append(text)
            hidden = hidden or text_hidden or _has_reasoning_fields(part)
    finish_reason = finish_reason or _first_string_field(response, "finish_reason", "finishReason")
    return _ResponseParts(
        content="".join(text_parts).strip(),
        hidden_reasoning_observed=hidden,
        tool_call_count=tool_call_count,
        tool_call_names=tuple(tool_call_names),
        finish_reason=finish_reason,
        truncated=_finish_reason_is_truncated(finish_reason),
    )


def _visible_text_from_value(value: object | None) -> tuple[str, bool]:
    if isinstance(value, str):
        hidden = bool(_THINK_BLOCK_PATTERN.search(value) or _OPEN_THINK_BLOCK_PATTERN.search(value))
        visible = _THINK_BLOCK_PATTERN.sub("", value)
        visible = _OPEN_THINK_BLOCK_PATTERN.sub("", visible)
        return visible.strip(), hidden
    if value is None:
        return "", False
    if isinstance(value, Mapping) or hasattr(value, "text"):
        value_type = _normalized_identifier(_get_field(value, "type"))
        if value_type in {"reasoning", "thinking", "analysis", "redactedthinking"}:
            return "", True
        text = _get_field(value, "text")
        if text is not None and text is not value:
            return _visible_text_from_value(text)
        content = _get_field(value, "content")
        if content is not None and content is not value:
            return _visible_text_from_value(content)
        return "", _has_reasoning_fields(value)

    parts: list[str] = []
    hidden = False
    for item in _as_sequence(value):
        text, item_hidden = _visible_text_from_value(item)
        if text:
            parts.append(text)
        hidden = hidden or item_hidden
    return "".join(parts).strip(), hidden


def _merge_visible_text(primary: str, secondary: str) -> str:
    """Prefer an aggregate SDK field when it already contains nested output text."""
    if not primary:
        return secondary
    if not secondary or secondary in primary:
        return primary
    if primary in secondary:
        return secondary
    return f"{primary}{secondary}"


def _has_reasoning_fields(value: object | None) -> bool:
    if value is None:
        return False
    if _normalized_identifier(_get_field(value, "type")) in {
        "reasoning",
        "thinking",
        "analysis",
        "redactedthinking",
    }:
        return True
    for field_name in (
        "reasoning",
        "reasoning_content",
        "reasoningContent",
        "thinking",
        "thinking_content",
        "thinkingContent",
    ):
        if _has_substantive_value(_get_field(value, field_name)):
            return True
    return _get_field(value, "thought") is True and _has_substantive_value(
        _get_field(value, "text")
    )


def _tool_call_count(value: object | None) -> int:
    tool_calls = _get_field(value, "tool_calls") or _get_field(value, "toolCalls")
    if _has_substantive_value(tool_calls):
        return len(_as_sequence(tool_calls)) or 1
    return 1 if _has_substantive_value(_get_field(value, "function_call")) else 0


def _tool_call_names(value: object | None) -> tuple[str, ...]:
    raw_calls = _get_field(value, "tool_calls") or _get_field(value, "toolCalls")
    calls = _as_sequence(raw_calls)
    if isinstance(raw_calls, Mapping):
        calls = (raw_calls,)
    names = [name for call in calls if (name := _tool_name_from_call(call))]
    legacy_call = _get_field(value, "function_call") or _get_field(value, "functionCall")
    if legacy_call is not None and (name := _tool_name_from_call(legacy_call)):
        names.append(name)
    return tuple(names)


def _tool_name_from_call(value: object | None) -> str | None:
    name = _get_field(value, "name")
    if not isinstance(name, str) or not name.strip():
        function = _get_field(value, "function")
        name = _get_field(function, "name")
    return name.strip() if isinstance(name, str) and name.strip() else None


def _response_matches_protocol(expected: ProviderProtocol, detected: ProviderProtocol) -> bool:
    if expected == "openai_chat_completions_compatible":
        return detected == "openai_chat_completions"
    return expected == detected


def _get_field(value: object | None, name: str) -> object | None:
    if isinstance(value, Mapping):
        return value.get(name)
    try:
        return getattr(value, name, None)
    except (AttributeError, TypeError):
        return None


def _as_sequence(value: object | None) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray, Mapping)) or value is None:
        return ()
    if isinstance(value, Sequence):
        return tuple(value)
    return ()


def _is_nontext_sequence(value: object | None) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _first_item(value: object | None) -> object | None:
    values = _as_sequence(value)
    if values:
        return values[0]
    return value if isinstance(value, Mapping) else None


def _first_string_field(value: object | None, *field_names: str) -> str | None:
    for field_name in field_names:
        field_value = _get_field(value, field_name)
        if isinstance(field_value, str) and field_value.strip():
            return field_value.strip()
    return None


def _normalized_identifier(value: object | None) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _finish_reason_is_truncated(value: object | None) -> bool:
    normalized = _normalized_identifier(value)
    if not normalized:
        return False
    return normalized in {_normalized_identifier(item) for item in _TRUNCATION_MARKERS} or (
        "maxtoken" in normalized or "tokenlimit" in normalized
    )


def _has_substantive_value(value: object | None) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    return bool(_as_sequence(value)) or value is True


def _extract_status_code(value: object | None) -> int | None:
    for candidate in (value, _get_field(value, "response")):
        for field_name in ("status_code", "statusCode", "status", "code"):
            status_code = _coerce_status_code(_get_field(candidate, field_name))
            if status_code is not None:
                return status_code
    if value is None or isinstance(value, Mapping):
        return None
    match = re.search(r"(?:http|status|error\s+code)\D{0,12}(\d{3})", str(value), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _coerce_status_code(value: object | None) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 100 <= value <= 599:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if 100 <= parsed <= 599 else None
    return None


def _looks_like_protocol_mismatch(
    protocol: ProviderProtocol | None,
    error: object | None,
    status_code: int | None,
) -> bool:
    if protocol is None:
        return False
    text = _error_text(error).lower()
    if not text:
        return False
    if "protocol mismatch" in text or "unsupported protocol" in text:
        return True
    has_protocol_marker = any(marker in text for marker in _PROTOCOL_MISMATCH_MARKERS[protocol])
    has_endpoint_rejection = any(marker in text for marker in _ENDPOINT_REJECTION_MARKERS)
    if status_code in _PROTOCOL_MISMATCH_STATUS_CODES:
        return has_protocol_marker and has_endpoint_rejection
    if protocol == "anthropic_messages" and status_code in {401, 403}:
        return has_protocol_marker and any(
            marker in text for marker in ("expected", "missing", "must use", "unsupported")
        )
    return False


def _error_text(value: object | None) -> str:
    if isinstance(value, Mapping):
        parts: list[str] = []
        for field_name in ("message", "detail", "type", "code", "error"):
            field_value = value.get(field_name)
            if field_value is value:
                continue
            text = _error_text(field_value)
            if text:
                parts.append(text)
        return " ".join(parts)
    if value is None:
        return ""
    return str(value)


def _mapping_contains_sensitive_value(value: Mapping[object, object]) -> bool:
    for key, nested_value in value.items():
        normalized_key = _normalized_identifier(str(key))
        if normalized_key in _SENSITIVE_FIELD_NAMES or normalized_key in _UPSTREAM_BODY_FIELD_NAMES:
            return True
        if isinstance(nested_value, Mapping) and _mapping_contains_sensitive_value(nested_value):
            return True
    return False


def _fallback_diagnostic(fallback: str, status_code: int | None) -> str:
    detail = fallback.strip().rstrip(".") or "Provider request failed"
    suffix = f" (HTTP {status_code})" if status_code is not None else ""
    return f"{detail}{suffix}."


def default_capabilities_for_protocol(protocol: ProviderProtocol | str | None) -> CapabilityFlags:
    normalized = normalize_provider_protocol(protocol)
    if normalized == "openai_responses":
        return CapabilityFlags(
            chat=True,
            responses=True,
            vision=False,
            embeddings=False,
            tools=True,
            jsonSchema=True,
            structuredOutput=True,
            streaming=True,
        )
    if normalized == "anthropic_messages":
        return CapabilityFlags(
            chat=True,
            responses=False,
            vision=True,
            embeddings=False,
            tools=True,
            jsonSchema=False,
            structuredOutput=False,
            streaming=True,
        )
    if normalized == "gemini_generate_content":
        return CapabilityFlags(
            chat=True,
            responses=False,
            vision=False,
            embeddings=False,
            tools=True,
            jsonSchema=True,
            structuredOutput=True,
            streaming=True,
        )
    if normalized == "openai_chat_completions":
        return CapabilityFlags(
            chat=True,
            responses=False,
            vision=True,
            embeddings=False,
            tools=True,
            jsonSchema=True,
            structuredOutput=True,
            streaming=True,
        )
    if normalized == "openai_chat_completions_compatible":
        return CapabilityFlags(
            chat=True,
            responses=False,
            vision=False,
            embeddings=False,
            tools=False,
            jsonSchema=False,
            structuredOutput=False,
            streaming=True,
            thinking=False,
        )
    return CapabilityFlags(
        chat=False,
        responses=False,
        vision=False,
        embeddings=False,
        tools=False,
        jsonSchema=False,
        structuredOutput=False,
        streaming=False,
        thinking=False,
    )


def provider_protocol_family(
    protocol: ProviderProtocol | str | None,
) -> ProviderProtocolFamily | None:
    normalized = normalize_provider_protocol(protocol)
    if normalized is None:
        return None
    return _PROTOCOL_FAMILIES[normalized]


def provider_protocol_endpoint_hint(protocol: ProviderProtocol | str | None) -> str:
    normalized = normalize_provider_protocol(protocol)
    if normalized is None:
        return ""
    return _PROTOCOL_ENDPOINT_HINTS[normalized]


def provider_protocol_client_kind(protocol: ProviderProtocol | str | None) -> str | None:
    normalized = normalize_provider_protocol(protocol)
    if normalized is None:
        return None
    return _PROTOCOL_CLIENT_KINDS[normalized]


def provider_protocol_diagnostic_notes(protocol: ProviderProtocol | str | None) -> tuple[str, ...]:
    normalized = normalize_provider_protocol(protocol)
    if normalized is None:
        return (
            "Protocol is unverified. Trainer will not assume an OpenAI-compatible gateway.",
        )
    return _PROTOCOL_DIAGNOSTIC_NOTES[normalized]


def provider_protocol_required_capability(protocol: ProviderProtocol | str | None) -> str | None:
    normalized = normalize_provider_protocol(protocol)
    if normalized is None:
        return None
    return _PROTOCOL_REQUIRED_CAPABILITIES[normalized]


def protocol_model_supported(
    protocol: ProviderProtocol | str | None, model_capabilities: CapabilityFlags
) -> bool:
    normalized = normalize_provider_protocol(protocol)
    if normalized is None:
        return False
    return _PROTOCOL_MODEL_SUPPORTS[normalized](model_capabilities)


def provider_protocol_test_mode(
    protocol: ProviderProtocol | str | None,
) -> ProviderProtocolTestMode | None:
    normalized = normalize_provider_protocol(protocol)
    if normalized is None:
        return None
    return _PROTOCOL_TEST_MODES[normalized]


def provider_protocol_completion_label(protocol: ProviderProtocol | str | None) -> str:
    normalized = normalize_provider_protocol(protocol)
    if normalized is None:
        return "Protocol unverified"
    return _PROTOCOL_COMPLETION_LABELS[normalized]


def provider_protocol_test_model_hint(protocol: ProviderProtocol | str | None) -> str | None:
    normalized = normalize_provider_protocol(protocol)
    if normalized is None:
        return None
    return _PROTOCOL_TEST_MODEL_HINTS.get(normalized)


def list_supported_provider_protocol_catalog() -> list[ProviderProtocolCatalogEntry]:
    return [
        ProviderProtocolCatalogEntry(
            protocol=protocol,
            protocolFamily=_PROTOCOL_FAMILIES[protocol],
            clientKind=_PROTOCOL_CLIENT_KINDS[protocol],
            completionLabel=_PROTOCOL_COMPLETION_LABELS[protocol],
            endpointHint=_PROTOCOL_ENDPOINT_HINTS[protocol],
            testMode=_PROTOCOL_TEST_MODES[protocol],
            requiredCapability=_PROTOCOL_REQUIRED_CAPABILITIES[protocol],
            diagnosticNotes=list(_PROTOCOL_DIAGNOSTIC_NOTES[protocol]),
        )
        for protocol in SUPPORTED_PROVIDER_PROTOCOLS
    ]
