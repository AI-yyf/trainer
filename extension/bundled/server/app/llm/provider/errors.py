"""Provider error types (§五十二: extracted from provider_service.py)."""

from __future__ import annotations

import json
import re

import httpx

_QUOTA_ERROR_CODES = frozenset({
    "insufficient_quota", "insufficient_user_quota", "billing_hard_limit_reached",
    "credit_balance_too_low", "insufficient_balance",
})


def provider_quota_exhausted(payload: object) -> bool:
    """Read explicit billing codes, without exposing upstream text or secrets."""
    if not isinstance(payload, dict):
        return False
    nested = payload.get("error")
    error = nested if isinstance(nested, dict) else payload
    return any(
        isinstance(error.get(key), str) and error[key].strip().lower() in _QUOTA_ERROR_CODES
        for key in ("code", "type")
    )


def provider_error_quota_exhausted(error: Exception) -> bool:
    if provider_quota_exhausted(getattr(error, "body", None)):
        return True
    response = getattr(error, "response", None)
    if isinstance(response, httpx.Response) and _response_quota_exhausted(response):
        return True
    # Older transports retain a JSON error in the exception string. Match only
    # its code/type field, never a mention of quota in arbitrary error prose.
    return any(
        match.lower() in _QUOTA_ERROR_CODES
        for match in re.findall(
            r"[\"'](?:code|type)[\"']\s*:\s*[\"']([a-zA-Z0-9_]+)[\"']",
            str(error)[:16384],
        )
    )


def _response_quota_exhausted(response: httpx.Response) -> bool:
    if not isinstance(response, httpx.Response):
        return False
    payload: object = None
    try:
        content = response.content
    except httpx.ResponseNotRead:
        # Classification cannot consume a live stream or make another request.
        return False
    if len(content) <= 16384:
        try:
            payload = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            # Non-JSON HTTP failures retain their existing safe status detail.
            payload = None
    return provider_quota_exhausted(payload)


def provider_http_failure(response: httpx.Response, *, detail: str) -> RuntimeError:
    """Keep safe failure semantics before native transports discard raw bodies."""
    if response.status_code == 402 or _response_quota_exhausted(response):
        return ProviderRuntimeResponseError(
            category="quota_exhausted", detail="Provider account quota is exhausted.",
            retryable=False, status_code=response.status_code, model_supported=None,
        )
    return RuntimeError(detail)


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
