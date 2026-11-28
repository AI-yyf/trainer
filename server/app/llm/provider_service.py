from __future__ import annotations

import asyncio
import json
import logging
import math
import re
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
    _streamable_visible_prefix,
    _strip_fresh_lane_cross_lane_carryover,
    _strip_internal_coach_meta,
    preserve_streamed_reply_prefix,
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
from .harness import estimate_tokens, extract_provider_usage
from .library_practice import (
    build_library_practice,
    library_practice_requested,
    remove_model_practice,
)
from .prompts import (
    _is_rethinkfun_lecture_request,
    build_coaching_messages,
    extract_coaching_context,
    infer_learner_signal,
    normalize_answer_policy,
)
from .provider.agentic_execution_mixin import (
    AgenticExecutionMixin,
)
from .provider.assessment import (
    _as_mapping,
    _reasoning_budget_exhausted,
    _unusable_visible_reply_category,
)
from .provider.capability import (
    _allows_keyless_local_provider,
    _flatten_minimax_thinking_for_raw_http,
    _is_loopback_provider_url,
    _is_minimax_like_provider,
    _model_looks_reasoning_first,
    _needs_generous_visible_probe_budget,
    _normalized_provider_request_defaults,
    _should_fingerprint_gateway,
    _visible_probe_max_tokens,
)
from .provider.coaching_reply_mixin import (
    CoachingReplyMixin,
    _provider_service_coaching_reply_stream,
)
from .provider.connectivity_and_probes_mixin import ConnectivityAndProbesMixin
from .provider.context_budget import (
    DEFAULT_COACHING_MAX_OUTPUT_TOKENS,
    ContextBudgetMixin,
)
from .provider.context_budget import (
    MIN_CONTEXT_OUTPUT_TOKENS as MIN_CONTEXT_OUTPUT_TOKENS,
)
from .provider.error_classification import ErrorClassificationMixin
from .provider.errors import (
    ContextBudgetExhaustedError,
    ProviderRuntimeResponseError,
    provider_http_failure,
)
from .provider.failure_copy import (
    provider_failure_next_step_text,
    provider_failure_summary_text,
)
from .provider.language_probes import (
    _LANGUAGE_PROBE_VARIANTS as _LANGUAGE_PROBE_VARIANTS,
)
from .provider.language_probes import (
    _NATURAL_LANGUAGE_PROBE_FRAGMENTS as _NATURAL_LANGUAGE_PROBE_FRAGMENTS,
)
from .provider.language_probes import (
    _NATURAL_LANGUAGE_PROBE_PROMPT as _NATURAL_LANGUAGE_PROBE_PROMPT,
)
from .provider.language_probes import (
    LanguageProbeMixin,
)
from .provider.model_catalog import (
    _ANTHROPIC_MODELS_PAGE_SIZE as _ANTHROPIC_MODELS_PAGE_SIZE,
)
from .provider.model_catalog import (
    _GEMINI_MODELS_PAGE_SIZE as _GEMINI_MODELS_PAGE_SIZE,
)
from .provider.model_catalog import (
    _NATIVE_MODEL_DISCOVERY_MAX_MODELS as _NATIVE_MODEL_DISCOVERY_MAX_MODELS,
)
from .provider.model_catalog import (
    _NATIVE_MODEL_DISCOVERY_MAX_PAGES as _NATIVE_MODEL_DISCOVERY_MAX_PAGES,
)
from .provider.model_catalog import (
    ModelCatalogMixin,
)
from .provider.quota_copy import provider_quota_reply
from .provider.redaction import _compact_text, redact_provider_error
from .provider.runtime_shared import (
    _NOT_REPAIRED,
    FORMAL_PLAN_OUTPUT_TOKENS,
    GENERATION_CLIENT_TIMEOUT,
    GENERATION_READ_BACKSTOP_SECONDS,
    LECTURE_OUTPUT_TOKENS,
    MIN_OPENAI_CLIENT_TIMEOUT_SECONDS,
    logger,
)
from .provider.runtime_shared import (
    DEFAULT_OPENAI_CLIENT_MAX_RETRIES as DEFAULT_OPENAI_CLIENT_MAX_RETRIES,
)
from .provider.runtime_shared import (
    DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS as DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS,
)
from .provider.runtime_shared import (
    _looks_like_provider_html_shell as _looks_like_provider_html_shell,
)
from .provider.runtime_shared import (
    _malformed_provider_html_shell_detail as _malformed_provider_html_shell_detail,
)
from .provider.runtime_shared import (
    _require_provider_runtime_response as _require_provider_runtime_response,
)
from .provider.service_support import (
    agent_tool_events as _agent_tool_events,
)
from .provider.service_support import (
    agentic_recoverable_grounded_stop_reason as _agentic_recoverable_grounded_stop_reason,
)
from .provider.service_support import (
    has_successful_agent_tool_result as _has_successful_agent_tool_result,
)
from .provider.service_support import (
    optional_text as _optional_text,
)
from .provider.service_support import (
    positive_int as _positive_int,
)
from .provider.service_support import (
    timeout_recovery_should_replace_content as _timeout_recovery_should_replace_content,
)
from .provider.streaming import (
    _await_provider_stream_with_cancellation,
    _iterate_provider_stream_with_cancellation,
    _stream_cancel_event,
    extract_non_sse_json_stream_payload,
)
from .provider.text import (
    _QUESTION_RUN_PATTERN,
    ReasoningBlockFilter,
    _compact_visible_text,
    _contains_cjk,
    _has_hidden_reasoning,
    _looks_like_input_corruption_reply,
    _looks_like_mojibake_text,
    _mixed_script_reply_corruption_detail,
    _strip_short_cyrillic_noise,
    _visible_model_text,
    _wrong_language_cjk_reply_detail,
)
from .provider.thinking import (
    DEFAULT_POLICY,
    apply_thinking_policy,
    chat_parameter_repairs,
    clamp_anthropic_thinking_budget,
    clamp_wire_thinking_budget,
    declared_thinking,
    learned_param_repairs,
    learned_policy,
    remember_param_repairs,
    remember_policy,
    repair_chat_parameters,
    resolve_thinking_policy,
    thinking_rejection_policy,
)
from .provider_protocols import (
    _finish_reason_is_truncated,
    assess_provider_capabilities,
    assess_provider_tool_call_probe,
    normalize_provider_protocol,
    normalize_provider_response,
    provider_protocol_family,
    provider_protocol_required_capability,
)
from .vision_challenge import build_vision_challenge
from .vision_payload import openai_responses_input_image_parts


class ProviderService(
    LanguageProbeMixin,
    ErrorClassificationMixin,
    ContextBudgetMixin,
    ModelCatalogMixin,
    ConnectivityAndProbesMixin,
    CoachingReplyMixin,
    AgenticExecutionMixin,
):
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
        # Models on this transport that already answered a probe with hidden
        # reasoning. A service instance is per (config, api key), so this is
        # scoped to the connection it was observed on.
        self._reasoning_observed_models: set[str] = set()
        self._language_integrity_success: dict[str, float] = {}
        self._shared_language_integrity_resolver: (
            Callable[[ProviderConfig | None, str | None], dict[str, float] | None] | None
        ) = None
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

    def _note_hidden_reasoning(self, provider: ProviderConfig | None) -> None:
        """Remember that this connection's model answered with hidden reasoning.

        The name patterns in ``_needs_generous_visible_probe_budget`` lag behind
        thinking-by-default model families (glm-4.6, qwen3, kimi-k2, …), so a
        model whose small probe budget was spent on reasoning is promoted by
        live evidence: the remaining probes of this and later tests start from
        the generous tier instead of re-paying the same blank attempt.
        """
        if provider is None:
            return
        model = str(getattr(provider, "model", "") or "").strip().lower()
        if model:
            self._reasoning_observed_models.add(model)

    def _visible_probe_budget(self, provider: ProviderConfig | None, default: int = 96) -> int:
        """Output cap for a probe that must yield one short visible token."""
        budget = _visible_probe_max_tokens(provider, default)
        model = str(getattr(provider, "model", "") or "").strip().lower()
        if model and model in self._reasoning_observed_models:
            return max(budget, 1024)
        return budget

    def _probe_retry_budget(self, provider: ProviderConfig, base: int) -> int | None:
        """One-shot larger output cap for a probe that reasoning cut short.

        Never exceeds the model's configured output limit, so the retry cannot
        be rejected for asking for more output than the model allows.
        """
        escalated = self._escalated_chat_budget(base)
        if not escalated:
            return None
        _, max_output_tokens = self._configured_token_limits(provider)
        if isinstance(max_output_tokens, int) and max_output_tokens > 0:
            escalated = min(escalated, max_output_tokens)
        return escalated if escalated > base else None

    def supports_executable_tools(self) -> bool:
        """Return whether this live connection can run the tool loop.

        Template flags may pin ``tools`` false for OpenAI-compatible defaults.
        A successful connection test that recorded tools as verified overlays
        that pin so coach/library/plan loops can run.
        """
        if not self.has_api_key and not _is_loopback_provider_url(
            getattr(self._config, "base_url", None)
        ):
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

    def has_usable_credential(
        self,
        provider: ProviderConfig | None = None,
        api_key: str | None = None,
    ) -> bool:
        effective_key = self._api_key if api_key is None else api_key
        if bool((effective_key or "").strip()):
            return True
        target = provider or self._config
        return _allows_keyless_local_provider(target)

    @staticmethod
    def _effective_wire_api_key(provider: ProviderConfig | None, api_key: str | None) -> str:
        stripped = (api_key or "").strip() if isinstance(api_key, str) else ""
        if stripped:
            return stripped
        if _allows_keyless_local_provider(provider):
            return "local-no-key"
        return ""

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

    def bind_language_integrity_store(
        self,
        resolver: Callable[[ProviderConfig | None, str | None], dict[str, float] | None] | None,
    ) -> None:
        self._shared_language_integrity_resolver = resolver

    def _language_integrity_store(
        self,
        *,
        provider_config: ProviderConfig | None = None,
        api_key: str | None = None,
    ) -> dict[str, float]:
        config = provider_config if provider_config is not None else self._config
        resolved_key = api_key if api_key is not None else self._api_key
        if self._shared_language_integrity_resolver is not None:
            bucket = self._shared_language_integrity_resolver(config, resolved_key)
            if isinstance(bucket, dict):
                return bucket
        return self._language_integrity_success

    def has_recent_language_integrity_success(
        self,
        *,
        message: str | None = None,
        response_language: str | None = None,
        provider_config: ProviderConfig | None = None,
        api_key: str | None = None,
    ) -> bool:
        cache_key = self._language_integrity_cache_key(
            message=message,
            response_language=response_language,
        )
        if not cache_key:
            return False
        store = self._language_integrity_store(
            provider_config=provider_config,
            api_key=api_key,
        )
        cached_at = store.get(cache_key)
        if cached_at is None:
            return False
        if monotonic() - cached_at > self._LANGUAGE_INTEGRITY_SUCCESS_TTL_SECONDS:
            store.pop(cache_key, None)
            return False
        return True

    def mark_language_integrity_success(
        self,
        *,
        message: str | None = None,
        response_language: str | None = None,
        provider_config: ProviderConfig | None = None,
        api_key: str | None = None,
    ) -> None:
        cache_key = self._language_integrity_cache_key(
            message=message,
            response_language=response_language,
        )
        if not cache_key:
            return
        store = self._language_integrity_store(
            provider_config=provider_config,
            api_key=api_key,
        )
        now = monotonic()
        store[cache_key] = now
        if cache_key == "zh":
            store["cjk"] = now

    def clear_language_integrity_success(
        self,
        *,
        message: str | None = None,
        response_language: str | None = None,
        provider_config: ProviderConfig | None = None,
        api_key: str | None = None,
    ) -> None:
        cache_key = self._language_integrity_cache_key(
            message=message,
            response_language=response_language,
        )
        if not cache_key:
            return
        store = self._language_integrity_store(
            provider_config=provider_config,
            api_key=api_key,
        )
        store.pop(cache_key, None)
        if cache_key in {"zh", "cjk"}:
            store.pop("zh", None)
            store.pop("cjk", None)

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
        # Provider turn failures must be observable in the sidecar log: the
        # user-facing copy is intentionally generic, which previously left a
        # failing gateway with no diagnostic trail at all. ``detail`` is
        # already redacted by the classifier.
        logger.warning(
            "[provider] reply failure category=%s status=%s retryable=%s detail=%s",
            category,
            status_code,
            retryable,
            _compact_text(detail, limit=400),
        )
        if category in {"network", "timeout", "upstream_unavailable", "unknown"}:
            self.reset_transport_client()
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
        return provider_failure_summary_text(category, response_language)

    def provider_failure_next_step(self, category: str, response_language: str | None) -> str:
        return provider_failure_next_step_text(category, response_language)

    def provider_failure_reply(
        self,
        category: str,
        detail: str | None,
        response_language: str | None,
    ) -> str:
        if category == "quota_exhausted":
            return provider_quota_reply(response_language)
        detail_text = (
            _compact_text(redact_provider_error(detail, api_key=self._api_key))
            if detail
            else ""
        )
        if _prefers_chinese(response_language):
            category_hint = {
                "invalid_key_or_permission": "先在设置里检查 API 密钥或访问权限是否有效。",
                "malformed_response": "先确认当前服务地址支持 OpenAI 兼容接口协议。",
                "truncated_or_empty": "先缩短回答长度或提高模型输出上限。",
                "rate_limit": "先稍等片刻，再重试同一轮。",
                "model_unsupported": "先换一个当前模型连接支持的模型名称。",
            }.get(category, "先检查并修复模型连接，再重试同一轮。")
            lines = [
                "当前模型连接不可用，这轮对话暂时无法继续。",
                "",
                category_hint,
            ]
            if detail_text:
                lines.append(f"详情：{detail_text}")
            lines.append("下一步：先把模型连接恢复到可用状态，再重新发送这轮。")
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

    def _should_bypass_system_proxy(self, provider: ProviderConfig | None = None) -> bool:
        config = provider or self._config
        return bool(getattr(config, "ignore_system_proxy", False)) or self._uses_loopback_transport(
            config
        )

    def _direct_http_client(self, provider: ProviderConfig, *, timeout: float) -> httpx.Client:
        return httpx.Client(
            timeout=timeout,
            # Bypass ambient proxy for loopback endpoints or when direct connection is configured.
            trust_env=not self._should_bypass_system_proxy(provider),
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
                "api_key": self._effective_wire_api_key(self._config, self._api_key),
                "base_url": base_url,
                # Generation client: no designed read ceiling beyond the
                # transport backstop (see GENERATION_CLIENT_TIMEOUT). Probe and
                # control callers that share this client pass a per-request
                # bounded timeout instead.
                "timeout": GENERATION_CLIENT_TIMEOUT,
                "max_retries": self._provider_client_max_retries(),
            }
            if self._should_bypass_system_proxy():
                client_kwargs["http_client"] = httpx.AsyncClient(trust_env=False)
            self._client = async_openai_cls(**client_kwargs)
        return self._client

    def reset_transport_client(self) -> None:
        """Drop the pooled async HTTP client after a transport/connection failure."""
        client = self._client
        self._client = None
        if client is None:
            return
        close_fn = getattr(client, "aclose", None) or getattr(client, "close", None)
        if not callable(close_fn):
            return
        try:
            result = close_fn()
        except Exception:
            return
        if not asyncio.iscoroutine(result):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            result.close()
        else:
            task = loop.create_task(result)
            task.add_done_callback(
                lambda finished: finished.exception() if not finished.cancelled() else None
            )

    def _create_sync_client(self, provider: ProviderConfig, api_key: str) -> Any:
        openai_cls = self._get_sync_openai_class()
        client_kwargs: dict[str, Any] = {
            "api_key": self._effective_wire_api_key(provider, api_key),
            "base_url": self._normalized_openai_compatible_base_url(provider),
            # The sync client only serves bounded capability probes.
            "timeout": self._probe_client_timeout_seconds(provider),
            "max_retries": self._provider_client_max_retries(provider),
        }
        if self._should_bypass_system_proxy(provider):
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

    @staticmethod
    def _probe_client_timeout_seconds(provider: ProviderConfig | None = None) -> float:
        """Bounded wall for short probe/control calls (never generation).

        Providers may declare their own bound via request defaults; anything
        slower than the default is treated as the default so a misconfigured
        provider cannot disable the probe's liveness bound.
        """
        defaults = _normalized_provider_request_defaults(provider)
        for key in (
            "clientTimeoutSeconds",
            "client_timeout_seconds",
            "timeoutSeconds",
            "timeout_seconds",
            "timeout",
        ):
            value = defaults.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return max(MIN_OPENAI_CLIENT_TIMEOUT_SECONDS, float(value))
        return DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS

    def _agent_loop_timeout_kwargs(self) -> dict[str, float | None]:
        # Reasoning-first gateways (kimi-k3, MiniMax-M3.x, deepseek-r1, …)
        # think for as long as the task needs — measured runs blow past every
        # fixed tier (24s/90s/120s/240s/300s) as a false timeout. Steps carry
        # no designed wall-clock. Liveness and pace come from the loop's own
        # guards instead: a stream silent for 60 s is a stall, the first step
        # must show the learner something within 20 s or is restarted once, and
        # that second attempt is capped; the user's own cancel still applies.
        if _needs_generous_visible_probe_budget(self._config):
            return {"step_timeout": math.inf, "first_step_timeout": math.inf}
        return {}

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
            if normalized_key == "stop" and key == "stopSequences":
                merged[normalized_key] = value
                continue
            merged[normalized_key] = value

        # Apply the negotiated thinking policy here, on the central chokepoint
        # every chat request passes through. Without this the policy learned
        # from a gateway rejection is never re-applied, so every later turn
        # re-pays the same HTTP 400 round trip before succeeding. The chat wire
        # cannot carry the profile's top-level ``thinking`` marker (the SDK
        # rejects unknown kwargs, and the key filter above drops it), so the
        # declared policy is also read from the defaults themselves: an explicit
        # "off" still reaches the gateway, while an undeclared profile sends
        # nothing and keeps the model's own default (the composer's "auto").
        scope = self._thinking_scope(provider)
        declared = declared_thinking(merged) or declared_thinking(request_defaults)
        applied = apply_thinking_policy(
            merged,
            resolve_thinking_policy(merged, scope, declared=declared),
        )
        known_repairs = learned_param_repairs(scope)
        if known_repairs:
            repaired = repair_chat_parameters(applied, known_repairs)
            if repaired is not None:
                applied = repaired
        return clamp_wire_thinking_budget(applied)


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
        if not attachments_present:
            return {
                "attachments_present": False,
                "image_attachment_count": 0,
                "attachments_delivered_to_model": False,
                "attachments_delivery_path": "not_sent",
                "attachments_delivery_reason": "no_attachments",
            }

        if config is not None and self._capability_truth.get("vision") != "verified":
            return {
                "attachments_present": True,
                "image_attachment_count": image_attachment_count,
                "attachments_delivered_to_model": False,
                "attachments_delivery_path": "not_sent",
                "attachments_delivery_reason": "vision_not_available",
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









    def _configured_protocol(self, provider: ProviderConfig) -> ProviderProtocol | None:
        return normalize_provider_protocol(getattr(provider, "protocol", None))

    def recommended_generation_max_tokens(self, default: int) -> int:
        """Reasoning-first models can spend the whole default budget on hidden
        reasoning before any visible JSON appears, so grant them headroom."""
        if self._config is not None and _model_looks_reasoning_first(self._config):
            return max(default, 8192)
        return default

    def _coaching_requested_output_tokens(
        self,
        message: str,
        coach_context: dict[str, Any] | None = None,
        *,
        analysis_requested: bool = False,
        agent_loop_enabled: bool = False,
    ) -> int | None:
        """Grant sufficient output headroom for deep RethinkFun lectures,
        formal-plan updates, library analysis, and reasoning-first agentic turns
        without inflating fast Q&A."""
        generous_model = (
            self._config is not None and _needs_generous_visible_probe_budget(self._config)
        )
        if (coach_context or {}).get("formal_plan_mutation") is True:
            base = FORMAL_PLAN_OUTPUT_TOKENS
            if generous_model:
                return max(base, 8192)
            return self.recommended_generation_max_tokens(base)
        if analysis_requested or _is_rethinkfun_lecture_request(message):
            base = LECTURE_OUTPUT_TOKENS
            if generous_model:
                return max(base, 8192)
            return self.recommended_generation_max_tokens(base)
        if agent_loop_enabled and generous_model:
            return 4096
        return None

    @staticmethod
    def _escalated_chat_budget(requested: int | None) -> int | None:
        """One-shot budget escalation for truncated reasoning replies.

        Reasoning-first models can spend several thousand tokens thinking
        before any visible text; a 4x jump from the coaching default (1024)
        still truncated on measured runs, so the single retry grants the
        reasoned headroom directly. It only fires after an explicit truncation,
        so models that answer within the normal budget never pay for it.
        """
        base = _positive_int(requested) or DEFAULT_COACHING_MAX_OUTPUT_TOKENS
        escalated = min(max(int(base) * 4, 8192), 16384)
        return escalated if escalated > int(base) else None

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
            try:
                payload: dict[str, Any] = {
                    "model": provider.model,
                    "input": prompt,
                    "max_output_tokens": max_tokens,
                }
                if not _model_looks_reasoning_first(provider):
                    payload["temperature"] = 0
                if system:
                    payload["instructions"] = system
                payload = self._apply_openai_responses_probe_defaults(payload, provider)
                try:
                    response = client.responses.create(**payload)
                except Exception as temp_exc:  # noqa: BLE001
                    if "temperature" in payload and "temperature" in str(temp_exc).lower():
                        payload.pop("temperature", None)
                        response = client.responses.create(**payload)
                    else:
                        raise
                return self._native_probe_preview(getattr(response, "output_text", ""))
            finally:
                self._close_sync_client(client)

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
                    headers=self._anthropic_probe_headers(provider, api_key),
                )
            if response.status_code >= 400:
                raise provider_http_failure(
                    response,
                    detail=redact_provider_error(
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
                raise provider_http_failure(
                    response,
                    detail=redact_provider_error(
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
                    if (
                        isinstance(part, dict)
                        and part.get("thought") is not True
                        and isinstance(part.get("text"), str)
                    ):
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
        if hidden_reasoning_observed:
            self._note_hidden_reasoning(provider)
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

    @staticmethod
    def _extra_headers_from_defaults(provider: ProviderConfig) -> dict[str, str]:
        defaults = _normalized_provider_request_defaults(provider)
        raw = defaults.get("extra_headers") or defaults.get("extraHeaders")
        if not isinstance(raw, dict):
            return {}
        return {
            str(k).strip(): str(v)
            for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, str) and k.strip()
        }

    def _anthropic_probe_headers(self, provider: ProviderConfig, api_key: str) -> dict[str, str]:
        return {
            **self._extra_headers_from_defaults(provider),
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _gemini_probe_headers(self, provider: ProviderConfig, api_key: str) -> dict[str, str]:
        return {
            **self._extra_headers_from_defaults(provider),
            "x-goog-api-key": api_key,
            "content-type": "application/json",
        }

    def _apply_openai_responses_probe_defaults(
        self,
        payload: dict[str, Any],
        provider: ProviderConfig,
    ) -> dict[str, Any]:
        defaults = self._provider_request_defaults(provider)
        merged = dict(payload)
        extra_headers = self._extra_headers_from_defaults(provider)
        if extra_headers:
            merged["extra_headers"] = extra_headers
        if defaults:
            if isinstance(defaults.get("extra_body"), dict):
                merged["extra_body"] = self._merge_request_records(
                    dict(merged.get("extra_body") or {}),
                    defaults["extra_body"],
                )
            if "store" in defaults:
                merged["store"] = defaults["store"]
            service_tier = defaults.get("service_tier", defaults.get("serviceTier"))
            if service_tier is not None:
                merged["service_tier"] = service_tier
            effort = defaults.get("reasoning_effort", defaults.get("reasoningEffort"))
            if isinstance(effort, str) and effort.strip() and effort.strip().lower() != "auto":
                existing = merged.get("reasoning")
                merged["reasoning"] = {
                    **(dict(existing) if isinstance(existing, dict) else {}),
                    "effort": effort.strip(),
                }
        if (
            _model_looks_reasoning_first(provider)
            or (isinstance(merged.get("reasoning"), dict) and merged["reasoning"])
        ):
            merged.pop("temperature", None)
        return merged

    @staticmethod
    def _close_sync_client(client: Any) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                logger.debug("Provider sync HTTP client close raised: %s", exc)

    def _apply_anthropic_native_probe_defaults(
        self,
        payload: dict[str, Any],
        provider: ProviderConfig,
    ) -> dict[str, Any]:
        defaults = self._provider_request_defaults(provider)
        merged = dict(payload)
        if defaults:
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
                merged = apply_thinking_policy(
                    merged, resolve_thinking_policy(merged, provider)
                )
            else:
                thinking_budget = defaults.get("thinking_budget", defaults.get("thinkingBudget"))
                if isinstance(thinking_budget, int) and thinking_budget > 0:
                    merged["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
                elif isinstance(thinking_budget, str) and thinking_budget.strip().lower() == "disabled":
                    merged.pop("thinking", None)
        merged = _flatten_minimax_thinking_for_raw_http(merged, provider)
        if isinstance(merged.get("extra_body"), dict):
            raw_extra = merged.pop("extra_body")
            if isinstance(raw_extra.get("thinking"), dict) and "thinking" not in merged:
                merged["thinking"] = raw_extra["thinking"]
        return clamp_anthropic_thinking_budget(merged)

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

    @staticmethod
    def _replay_with_repaired_parameters(client: Any, payload: dict[str, Any], error: Exception) -> Any:
        """Replay once without a parameter the provider named as unsupported.

        Returns ``_NOT_REPAIRED`` when the failure is not a named-parameter
        rejection, so the caller keeps its normal error handling.
        """
        retry_payload = repair_chat_parameters(payload, chat_parameter_repairs(error))
        if retry_payload is None:
            return _NOT_REPAIRED
        try:
            return client.chat.completions.create(**retry_payload)
        except Exception as retry_exc:
            raise error from retry_exc

    @staticmethod
    async def _replay_with_repaired_parameters_async(
        client: Any, payload: dict[str, Any], error: Exception
    ) -> Any:
        retry_payload = repair_chat_parameters(payload, chat_parameter_repairs(error))
        if retry_payload is None:
            return _NOT_REPAIRED
        try:
            return await client.chat.completions.create(**retry_payload)
        except Exception as retry_exc:
            raise error from retry_exc

    def _create_chat_completion_negotiated(
        self,
        client: Any,
        payload: dict[str, Any],
        provider: ProviderConfig | None = None,
    ) -> Any:
        """Sync ``chat.completions.create`` with bounded parameter and thinking repair."""
        scope = self._thinking_scope(provider)
        current_payload = dict(payload)
        attempted = (
            declared_thinking(current_payload)
            or (learned_policy(scope) if scope else None)
            or DEFAULT_POLICY
        )
        first_error: Exception | None = None
        for _ in range(4):
            try:
                return client.chat.completions.create(**current_payload)
            except Exception as exc:
                if first_error is None:
                    first_error = exc
                repairs = chat_parameter_repairs(exc)
                repaired_payload = (
                    repair_chat_parameters(current_payload, repairs) if repairs else None
                )
                if repaired_payload is not None:
                    if scope is not None:
                        remember_param_repairs(scope, repairs)
                    current_payload = repaired_payload
                    continue
                policy = thinking_rejection_policy(exc, attempted)
                if policy is not None:
                    retry_payload = self._retry_payload_for_thinking(
                        current_payload, scope, attempted, policy
                    )
                    if retry_payload is not None:
                        attempted = policy
                        current_payload = retry_payload
                        continue
                if first_error is not exc:
                    raise first_error from exc
                raise
        assert first_error is not None
        raise first_error


ProviderService.coaching_reply_stream = _provider_service_coaching_reply_stream
ProviderService._onboarding_reply = _clean_provider_service_onboarding_reply
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


__all__ = [
    'ProviderService',
    'asyncio',
    'json',
    'logging',
    'math',
    're',
    'import_module',
    'monotonic',
    'SimpleNamespace',
    'quote',
    'urlsplit',
    'httpx',
    'ProviderCapabilityEvidence',
    'ProviderConfig',
    'ProviderModelsResponse',
    'ProviderProbeUsage',
    'ProviderProtocol',
    'ProviderTestResponse',
    'UserProfile',
    '_build_agent_tool_context_extra',
    '_compact_first_turn_reply',
    '_first_turn_concrete_followthrough',
    '_first_turn_guided_lane',
    '_first_turn_lane_continuity_note',
    '_first_turn_lane_next_step',
    '_fresh_lane_comparison_requested',
    '_resolve_first_turn_guided_lane',
    '_should_offer_generic_first_turn_lane_prompt',
    '_build_empty_reply_override',
    '_compose_principle_followthrough_patch',
    '_compose_scaffold_paragraphs',
    '_guided_domain_empty_reply_override',
    '_maybe_auto_verify_practice_current_file',
    '_normalize_visible_resume_thread_text',
    '_scaffold_next_step',
    '_structured_view_visible_reply_needs_repair',
    '_GUIDED_DOMAIN_SCENARIOS',
    '_agentic_resume_thread_text',
    '_build_active_view_recovery_override',
    '_build_language_corruption_recovery_override',
    '_build_provider_error_recovery_override',
    '_build_timeout_recovery_override',
    '_coaching_active_view_name',
    '_localized_text',
    '_prefers_chinese',
    '_trim_sentence',
    '_agentic_completion_continuity',
    '_agentic_fallback_continuity',
    '_agentic_practice_completion_guard',
    '_clean_provider_failure_next_step',
    '_clean_provider_failure_reply',
    '_clean_provider_failure_summary',
    '_current_file_practice_verification_result',
    '_extract_next_step_hint_text',
    '_fresh_lane_marker_map',
    '_prefer_structured_next_step',
    '_reply_has_guided_lane_signal',
    '_sanitize_agentic_continuity_text',
    '_stream_holdback_chars',
    '_streamable_visible_prefix',
    '_strip_fresh_lane_cross_lane_carryover',
    '_strip_internal_coach_meta',
    'preserve_streamed_reply_prefix',
    '_agent_loop_max_steps',
    '_agent_result_visible_text',
    '_agentic_has_grounded_resource_evidence',
    '_append_unique_paragraphs',
    '_clean_provider_service_error_reply',
    '_clean_provider_service_missing_api_key_reply',
    '_clean_provider_service_onboarding_reply',
    '_compose_recalled_memory_patch',
    '_compose_review_tightening_patch',
    '_compose_success_signal_patch',
    '_fresh_lane_reanchor_reply',
    '_guided_domain_empty_reply',
    '_provider_service_error_reply',
    '_provider_service_missing_api_key_reply',
    '_provider_service_onboarding_reply',
    '_reanchor_visible_reply_to_current_request',
    '_reply_needs_first_turn_reframe',
    '_scaffold_close',
    '_should_preserve_visible_reply',
    '_strip_generic_lane_prompt_artifacts',
    '_scaffold_anchor',
    '_scaffold_diagnosis',
    '_scaffold_teaching_note',
    'estimate_tokens',
    'extract_provider_usage',
    'build_library_practice',
    'library_practice_requested',
    'remove_model_practice',
    '_is_rethinkfun_lecture_request',
    'build_coaching_messages',
    'extract_coaching_context',
    'infer_learner_signal',
    'normalize_answer_policy',
    '_as_mapping',
    '_reasoning_budget_exhausted',
    '_unusable_visible_reply_category',
    '_allows_keyless_local_provider',
    '_flatten_minimax_thinking_for_raw_http',
    '_is_loopback_provider_url',
    '_is_minimax_like_provider',
    '_model_looks_reasoning_first',
    '_needs_generous_visible_probe_budget',
    '_normalized_provider_request_defaults',
    '_should_fingerprint_gateway',
    '_visible_probe_max_tokens',
    'DEFAULT_COACHING_MAX_OUTPUT_TOKENS',
    'ContextBudgetMixin',
    'MIN_CONTEXT_OUTPUT_TOKENS',
    'ErrorClassificationMixin',
    'ContextBudgetExhaustedError',
    'ProviderRuntimeResponseError',
    'provider_http_failure',
    'provider_failure_next_step_text',
    'provider_failure_summary_text',
    '_LANGUAGE_PROBE_VARIANTS',
    '_NATURAL_LANGUAGE_PROBE_FRAGMENTS',
    '_NATURAL_LANGUAGE_PROBE_PROMPT',
    'LanguageProbeMixin',
    '_ANTHROPIC_MODELS_PAGE_SIZE',
    '_GEMINI_MODELS_PAGE_SIZE',
    '_NATIVE_MODEL_DISCOVERY_MAX_MODELS',
    '_NATIVE_MODEL_DISCOVERY_MAX_PAGES',
    'ModelCatalogMixin',
    'provider_quota_reply',
    '_compact_text',
    'redact_provider_error',
    '_agent_tool_events',
    '_agentic_recoverable_grounded_stop_reason',
    '_has_successful_agent_tool_result',
    '_optional_text',
    '_positive_int',
    '_timeout_recovery_should_replace_content',
    '_await_provider_stream_with_cancellation',
    '_iterate_provider_stream_with_cancellation',
    '_stream_cancel_event',
    'extract_non_sse_json_stream_payload',
    '_QUESTION_RUN_PATTERN',
    'ReasoningBlockFilter',
    '_compact_visible_text',
    '_contains_cjk',
    '_has_hidden_reasoning',
    '_looks_like_input_corruption_reply',
    '_looks_like_mojibake_text',
    '_mixed_script_reply_corruption_detail',
    '_strip_short_cyrillic_noise',
    '_visible_model_text',
    '_wrong_language_cjk_reply_detail',
    'DEFAULT_POLICY',
    'apply_thinking_policy',
    'chat_parameter_repairs',
    'clamp_anthropic_thinking_budget',
    'clamp_wire_thinking_budget',
    'declared_thinking',
    'learned_param_repairs',
    'learned_policy',
    'remember_param_repairs',
    'remember_policy',
    'repair_chat_parameters',
    'resolve_thinking_policy',
    'thinking_rejection_policy',
    '_finish_reason_is_truncated',
    'assess_provider_capabilities',
    'assess_provider_tool_call_probe',
    'normalize_provider_protocol',
    'normalize_provider_response',
    'provider_protocol_family',
    'provider_protocol_required_capability',
    'build_vision_challenge',
    'openai_responses_input_image_parts',
    '_NOT_REPAIRED',
    'FORMAL_PLAN_OUTPUT_TOKENS',
    'GENERATION_CLIENT_TIMEOUT',
    'GENERATION_READ_BACKSTOP_SECONDS',
    'LECTURE_OUTPUT_TOKENS',
    'MIN_OPENAI_CLIENT_TIMEOUT_SECONDS',
    'logger',
    'DEFAULT_OPENAI_CLIENT_MAX_RETRIES',
    'DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS',
    '_looks_like_provider_html_shell',
    '_malformed_provider_html_shell_detail',
    '_require_provider_runtime_response',
]
