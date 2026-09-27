"""Provider error types (§五十二: extracted from provider_service.py)."""

from __future__ import annotations


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
