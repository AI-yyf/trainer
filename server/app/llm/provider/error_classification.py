"""Provider error classification for ProviderService (§五十二 extraction)."""

from __future__ import annotations

import re
import socket
from typing import TYPE_CHECKING

import httpx

from ...core.models import ProviderConfig
from ..coaching_recovery import _localized_text
from .errors import ProviderRuntimeResponseError, provider_error_quota_exhausted
from .quota_copy import provider_quota_reply
from .redaction import redact_provider_error


class ErrorClassificationMixin:
    if TYPE_CHECKING:
        _api_key: str | None


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

        if status_code == 402 or provider_error_quota_exhausted(error):
            return ("quota_exhausted", False, status_code, True, None)
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
        if category == "quota_exhausted":
            return provider_quota_reply(response_language)
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

