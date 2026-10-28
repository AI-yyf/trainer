"""Token-budget planning for ProviderService (§五十二 extraction).

The methods move together because they form one contract: estimate the
request, reserve a minimum visible answer, compact history when needed, and
report an honest context-budget failure instead of a provider error.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ...core.models import ProviderConfig, ProviderModelTokenLimit
from ..coaching_recovery import _localized_text
from ..prompts import _truncate_coaching_history_content
from .errors import ContextBudgetExhaustedError
from .service_support import (
    extract_model_token_limit as _extract_model_token_limit,
)
from .service_support import (
    positive_int as _positive_int,
)

DEFAULT_COACHING_MAX_OUTPUT_TOKENS = 1024
MIN_CONTEXT_OUTPUT_TOKENS = 128
CONTEXT_BUDGET_SAFETY_TOKENS = 256


class ContextBudgetMixin:
    """Methods inherited by ProviderService; state lives on the main class."""

    if TYPE_CHECKING:
        _config: ProviderConfig | None

        def _model_candidates(self, override: str | None = None) -> list[str]: ...

        def _resolve_model(self, override: str | None = None) -> str: ...

        @staticmethod
        def _raw_provider_request_defaults(provider: ProviderConfig | None) -> dict[str, Any]: ...


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
