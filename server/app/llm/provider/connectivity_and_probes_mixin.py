from __future__ import annotations

import asyncio
import json
import sys as _sys
from typing import TYPE_CHECKING, Any, Callable, cast
from urllib.parse import quote

import httpx as _real_httpx

from ...core.models import (
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderTestResponse,
)
from ..coaching_recovery import (
    _localized_text,
)
from ..prompts import (
    build_coaching_messages as _real_build_coaching_messages,
)
from ..provider_protocols import (
    _finish_reason_is_truncated,
    assess_provider_capabilities,
    assess_provider_tool_call_probe,
    normalize_provider_response,
    provider_protocol_family,
    provider_protocol_required_capability,
)
from ..vision_challenge import build_vision_challenge as _real_build_vision_challenge
from ..vision_payload import openai_responses_input_image_parts
from .assessment import (
    _reasoning_budget_exhausted,
    _unusable_visible_reply_category,
)
from .capability import (
    _flatten_minimax_thinking_for_raw_http,
    _is_minimax_like_provider,
    _model_looks_reasoning_first,
    _needs_generous_visible_probe_budget,
    _should_fingerprint_gateway,
    _visible_probe_max_tokens,
)
from .context_budget import (
    MIN_CONTEXT_OUTPUT_TOKENS as MIN_CONTEXT_OUTPUT_TOKENS,
)
from .errors import (
    provider_http_failure,
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
from .redaction import redact_provider_error
from .runtime_shared import (
    _TOOL_CAPABILITY_PROBE_NAME,
    _TOOL_CAPABILITY_PROBE_PROMPT,
    _TOOL_PROBE_OUTPUT_TOKENS,
    _probe_usage_payload,
)
from .text import (
    ReasoningBlockFilter,
    _has_hidden_reasoning,
    _visible_model_text,
)
from .thinking import (
    DEFAULT_POLICY,
    chat_parameter_repairs,
    clamp_anthropic_thinking_budget,
    clamp_wire_thinking_budget,
    declared_thinking,
    learned_policy,
    remember_param_repairs,
    repair_chat_parameters,
    thinking_rejection_policy,
)


class _ProviderHttpxProxy:
    def __getattr__(self, name: str) -> Any:
        ps_mod = _sys.modules.get("app.llm.provider_service")
        target = getattr(ps_mod, "httpx", _real_httpx) if ps_mod is not None else _real_httpx
        return getattr(target, name)


httpx: Any = _ProviderHttpxProxy()


def build_vision_challenge(*args: Any, **kwargs: Any) -> Any:
    ps_mod = _sys.modules.get("app.llm.provider_service")
    fn = getattr(ps_mod, "build_vision_challenge", _real_build_vision_challenge) if ps_mod is not None else _real_build_vision_challenge
    return fn(*args, **kwargs)


def build_coaching_messages(*args: Any, **kwargs: Any) -> Any:
    ps_mod = _sys.modules.get("app.llm.provider_service")
    fn = getattr(ps_mod, "build_coaching_messages", _real_build_coaching_messages) if ps_mod is not None else _real_build_coaching_messages
    return fn(*args, **kwargs)


class ConnectivityAndProbesMixin:
    if TYPE_CHECKING:
        _anthropic_probe_headers: Any
        _api_key: Any
        _apply_anthropic_native_probe_defaults: Any
        _apply_openai_responses_probe_defaults: Any
        _apply_request_defaults: Any
        _capability_truth: Any
        _classify_error: Any
        _close_sync_client: Any
        _config: Any
        _configured_protocol: Any
        _create_chat_completion_negotiated: Any
        _create_sync_client: Any
        _detail_from_category: Any
        _direct_http_client: Any
        _effective_wire_api_key: Any
        _escalated_chat_budget: Any
        _finalize_native_protocol_test: Any
        _gateway_fingerprint_diagnostics: Any
        _gemini_base_url_is_google_native: Any
        _gemini_probe_headers: Any
        _is_model_not_supported_error: Any
        _language_probe_result_resilient: Any
        _model_candidates: Any
        _native_probe_preview: Any
        _native_probe_prompts: Any
        _note_hidden_reasoning: Any
        _probe_retry_budget: Any
        _provider_request_defaults: Any
        _retry_payload_for_thinking: Any
        _thinking_scope: Any
        _trusted_visible_probe_reply: Any
        _visible_probe_budget: Any
        chat_completion_stream: Any
        clear_language_integrity_success: Any
        list_models: Any
        mark_language_integrity_success: Any

    async def _create_chat_completion_negotiated_async(
        self,
        client: Any,
        payload: dict[str, Any],
        provider: ProviderConfig | None = None,
    ) -> Any:
        """Async ``chat.completions.create`` with bounded parameter and thinking repair."""
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
                return await client.chat.completions.create(**current_payload)
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

    def _apply_gemini_native_probe_defaults(
        self,
        payload: dict[str, Any],
        provider: ProviderConfig,
    ) -> dict[str, Any]:
        defaults = self._provider_request_defaults(provider)
        merged = dict(payload)
        if defaults:
            extra_body = defaults.get("extra_body")
            gemini_allowed_root = {"safetySettings", "cachedContent", "labels", "toolConfig", "thinkingConfig"}
            if isinstance(extra_body, dict):
                for key, value in extra_body.items():
                    if key in gemini_allowed_root:
                        merged[key] = value
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
        return clamp_wire_thinking_budget(_flatten_minimax_thinking_for_raw_http(merged, provider))

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
            try:
                last_error: Exception | None = None
                response = None
                chosen_model = provider.model
                preview = ""
                hidden_reasoning_observed = False
                reasoning_budget_exhausted = False
                probe_output_budget = self._visible_probe_budget(provider, default=32)
                for candidate in self._model_candidates(provider.model):
                    chosen_model = candidate
                    try:
                        for attempt, prompt in enumerate(
                            self._native_probe_prompts(response_language),
                            start=1,
                        ):
                            attempt_budget = (
                                probe_output_budget
                                if attempt == 1
                                else (
                                    self._probe_retry_budget(provider, probe_output_budget)
                                    or max(probe_output_budget * 2, 128)
                                )
                            )
                            request_kwargs: dict[str, Any] = {
                                "model": candidate,
                                "input": prompt,
                                "max_output_tokens": attempt_budget,
                            }
                            if not _model_looks_reasoning_first(provider):
                                request_kwargs["temperature"] = 0
                            request_kwargs = self._apply_openai_responses_probe_defaults(
                                request_kwargs, provider
                            )
                            try:
                                response = client.responses.create(**request_kwargs)
                            except Exception as temp_exc:  # noqa: BLE001
                                if (
                                    "temperature" in request_kwargs
                                    and "temperature" in str(temp_exc).lower()
                                ):
                                    request_kwargs.pop("temperature", None)
                                    response = client.responses.create(**request_kwargs)
                                else:
                                    raise
                            hidden_reasoning_observed = _has_hidden_reasoning(response)
                            reasoning_budget_exhausted = (
                                reasoning_budget_exhausted
                                or _reasoning_budget_exhausted(
                                    response,
                                    max_tokens=attempt_budget,
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
            finally:
                self._close_sync_client(client)
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
        if base_url.lower().endswith("/v1"):
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
                        "max_tokens": self._visible_probe_budget(provider, default=64),
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
                        headers=self._gemini_probe_headers(provider, api_key),
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
                    hidden_reasoning_observed = hidden_reasoning_observed or _has_hidden_reasoning(body)
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
        *,
        max_tokens: int | None = None,
    ) -> tuple[str, object]:
        protocol = self._configured_protocol(provider)
        schema = self._tool_probe_schema()
        # A forced no-op tool call is short, but a reasoning model thinks
        # first and its reasoning counts against this cap.
        budget = (
            max_tokens
            if isinstance(max_tokens, int) and max_tokens > 0
            else self._visible_probe_budget(provider, _TOOL_PROBE_OUTPUT_TOKENS)
        )
        if protocol == "anthropic_messages":
            payload: dict[str, Any] = {
                "model": provider.model,
                "max_tokens": budget,
                "messages": [{"role": "user", "content": _TOOL_CAPABILITY_PROBE_PROMPT}],
            }
            payload = self._apply_anthropic_native_probe_defaults(payload, provider)
            # Anthropic forbids extended thinking alongside forced tool_choice
            # (`{"type": "tool", "name": ...}`), returning HTTP 400.
            thinking_obj = payload.get("thinking")
            if isinstance(thinking_obj, dict) and str(thinking_obj.get("type") or "").lower() == "enabled":
                payload.pop("thinking", None)
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
                    headers=self._anthropic_probe_headers(provider, api_key),
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
            try:
                req = self._apply_openai_responses_probe_defaults(
                    {
                        "model": provider.model,
                        "input": _TOOL_CAPABILITY_PROBE_PROMPT,
                        "tools": [
                            {
                                "type": "function",
                                "name": _TOOL_CAPABILITY_PROBE_NAME,
                                "description": "Internal capability probe. Do not perform any action.",
                                "parameters": schema,
                            }
                        ],
                        "tool_choice": {"type": "function", "name": _TOOL_CAPABILITY_PROBE_NAME},
                        "max_output_tokens": budget,
                    },
                    provider,
                )
                response = client.responses.create(**req)
                return protocol, response
            finally:
                self._close_sync_client(client)

        if protocol == "gemini_generate_content" and self._gemini_base_url_is_google_native(provider):
            payload = self._apply_gemini_native_probe_defaults(
                {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": _TOOL_CAPABILITY_PROBE_PROMPT}],
                        }
                    ],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": budget},
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
                    headers=self._gemini_probe_headers(provider, api_key),
                )
            if response.status_code >= 400:
                raise RuntimeError(f"Gemini GenerateContent tool probe failed (HTTP {response.status_code}).")
            return protocol, response.json()

        client = self._create_sync_client(provider, api_key)
        try:
            payload = self._apply_request_defaults(
                {
                    "model": provider.model,
                    "messages": [{"role": "user", "content": _TOOL_CAPABILITY_PROBE_PROMPT}],
                    "temperature": 0,
                    "max_tokens": budget,
                },
                provider,
            )
            payload["tools"] = [openai_tool]
            payload["tool_choice"] = {
                "type": "function",
                "function": {"name": _TOOL_CAPABILITY_PROBE_NAME},
            }
            return "openai_chat_completions_compatible", self._create_chat_completion_negotiated(
                client, payload, provider
            )
        finally:
            self._close_sync_client(client)

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
            effective_protocol = protocol
            if protocol == "openai_responses":
                client = self._create_sync_client(provider, api_key)
                try:
                    req = self._apply_openai_responses_probe_defaults(
                        {
                            "model": provider.model,
                            "input": openai_responses_input_image_parts(
                                prompt=challenge.prompt,
                                image_url=challenge.image_url,
                            ),
                            "temperature": 0,
                            "max_output_tokens": 96,
                        },
                        provider,
                    )
                    response = client.responses.create(**req)
                finally:
                    self._close_sync_client(client)
            elif protocol in {"openai_chat_completions", "openai_chat_completions_compatible"} or (
                protocol == "gemini_generate_content" and not self._gemini_base_url_is_google_native(provider)
            ):
                effective_protocol = (
                    "openai_chat_completions_compatible"
                    if protocol == "gemini_generate_content"
                    else protocol
                )
                client = self._create_sync_client(provider, api_key)
                try:
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
                    response = self._create_chat_completion_negotiated(client, payload, provider)
                finally:
                    self._close_sync_client(client)
            elif protocol == "anthropic_messages":
                from ..agent_binding import _anthropic_image_blocks

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
                        headers=self._anthropic_probe_headers(provider, api_key),
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
                        headers=self._gemini_probe_headers(provider, api_key),
                    )
                if response.status_code >= 400:
                    return False, "Vision probe was rejected by the provider."
                response = response.json()
            assessment = normalize_provider_response(effective_protocol, response, api_key=api_key)
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
        if assessment.observed is None:
            reply = normalize_provider_response(protocol, response, api_key=api_key)
            if reply.hidden_reasoning_observed or reply.truncated:
                self._note_hidden_reasoning(provider)
                # The short cap was spent before the tool call. That says
                # nothing about tool support, so buy one retry with real
                # headroom before leaving the capability unverified.
                retry_budget = self._probe_retry_budget(provider, _TOOL_PROBE_OUTPUT_TOKENS)
                if retry_budget:
                    try:
                        protocol, retry_response = self._tool_probe_response(
                            provider, api_key, max_tokens=retry_budget
                        )
                    except Exception:  # noqa: BLE001 - reduced to capability truth.
                        return assessment.observed, assessment.diagnostic
                    assessment = assess_provider_tool_call_probe(
                        protocol,
                        retry_response,
                        expected_tool_name=_TOOL_CAPABILITY_PROBE_NAME,
                        api_key=api_key,
                    )
                    if assessment.observed is True:
                        return True, (
                            "Provider returned the requested structured tool call after a "
                            "larger output budget."
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
            effective_protocol = protocol
            if protocol == "openai_responses":
                client = self._create_sync_client(provider, api_key)
                try:
                    req = self._apply_openai_responses_probe_defaults(
                        {
                            "model": provider.model,
                            "input": prompt,
                            "reasoning": {"effort": "low"},
                            "max_output_tokens": 128,
                        },
                        provider,
                    )
                    response = client.responses.create(**req)
                finally:
                    self._close_sync_client(client)
            elif protocol in {"openai_chat_completions", "openai_chat_completions_compatible"} or (
                protocol == "gemini_generate_content" and not self._gemini_base_url_is_google_native(provider)
            ):
                effective_protocol = (
                    "openai_chat_completions_compatible"
                    if protocol == "gemini_generate_content"
                    else protocol
                )
                client = self._create_sync_client(provider, api_key)
                try:
                    payload: dict[str, Any] = {
                        "model": provider.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0,
                        "max_tokens": 256 if _is_minimax_like_provider(provider) else 128,
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
                    if "reasoning_effort" in payload:
                        payload.pop("temperature", None)
                    response = self._create_chat_completion_negotiated(client, payload, provider)
                finally:
                    self._close_sync_client(client)
            elif protocol == "anthropic_messages":
                payload = self._apply_anthropic_native_probe_defaults({
                    "model": provider.model,
                    "max_tokens": 2048,
                    # Anthropic rejects an enabled budget below 1024 (and a
                    # max_tokens that does not exceed it). The old 128/256 pair
                    # was refused for every thinking-capable Claude, and that
                    # refusal was recorded as "unsupported".
                    "thinking": {"type": "enabled", "budget_tokens": 1024},
                    "messages": [{"role": "user", "content": prompt}],
                }, provider)
                payload = clamp_anthropic_thinking_budget(payload)
                with self._direct_http_client(provider, timeout=60.0) as client:
                    response = client.post(
                        f"{self._anthropic_base_url(provider)}/v1/messages",
                        json=payload,
                        headers=self._anthropic_probe_headers(provider, api_key),
                    )
                if response.status_code >= 400:
                    return False, "Thinking probe was rejected by the provider."
                response = response.json()
            elif protocol == "gemini_generate_content":
                payload = self._apply_gemini_native_probe_defaults({
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    # 512 is inside every Gemini 2.5 budget range (Pro >= 128,
                    # Flash-Lite >= 512); 64 was refused and read as unsupported.
                    "generationConfig": {"temperature": 0, "maxOutputTokens": 4096, "thinkingConfig": {"thinkingBudget": 512}},
                }, provider)
                with self._direct_http_client(provider, timeout=60.0) as client:
                    response = client.post(
                        self._gemini_endpoint(provider),
                        json=payload,
                        headers=self._gemini_probe_headers(provider, api_key),
                    )
                if response.status_code >= 400:
                    return False, "Thinking probe was rejected by the provider."
                response = response.json()
            else:
                return None, "Thinking probe is unsupported for this provider protocol."
            assessment = normalize_provider_response(effective_protocol, response, api_key=api_key)
        except Exception:  # noqa: BLE001 - capability probes must not leak upstream details.
            return None, "Thinking capability probe could not complete safely."
        if assessment.has_visible_text and assessment.content.strip() == "THINKING_OK":
            return True, "Thinking probe returned the expected visible token."
        if assessment.outcome in {"protocol_mismatch", "provider_error"}:
            return False, "Thinking probe was rejected by the provider."
        return None, "Thinking probe did not return a trustworthy visible result."

    def _streaming_probe_attempt(
        self,
        provider: ProviderConfig,
        api_key: str,
        max_tokens: int,
    ) -> tuple[bool, bool] | None:
        """Run one bounded chat-completions stream probe.

        Returns ``(visible_observed, reasoning_limited)``. ``reasoning_limited``
        is True when hidden reasoning or the output cap explains a missing
        visible token: that is a fact about the model's thinking, never about
        whether the transport can stream. ``None`` means the probe could not run.
        """
        client = None
        stream = None
        try:
            client = self._create_sync_client(provider, api_key)
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
            stream = self._create_chat_completion_negotiated(client, payload, provider)
            reasoning_filter = ReasoningBlockFilter()
            observed = False
            reasoning_limited = False
            for chunk in stream:
                choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
                if choice is None:
                    continue
                if _finish_reason_is_truncated(getattr(choice, "finish_reason", None)):
                    reasoning_limited = True
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue
                for field_name in ("reasoning_content", "reasoning", "thinking"):
                    reasoning_delta = getattr(delta, field_name, None)
                    if isinstance(reasoning_delta, str) and reasoning_delta.strip():
                        reasoning_limited = True
                content = getattr(delta, "content", None)
                if isinstance(content, str):
                    if "<think" in content.lower():
                        reasoning_limited = True
                    if reasoning_filter.push(content).strip():
                        observed = True
            if reasoning_filter.flush().strip():
                observed = True
            return observed, reasoning_limited
        except Exception:  # noqa: BLE001 - capability probes must not leak upstream details.
            return None
        finally:
            if stream is not None:
                close = getattr(stream, "close", None)
                if close is not None:
                    close()
            if client is not None:
                close_client = getattr(client, "close", None)
                if close_client is not None:
                    close_client()

    def _probe_streaming_capability(
        self,
        provider: ProviderConfig,
        api_key: str,
    ) -> tuple[bool | None, str]:
        """Run one real incremental request and observe visible streamed output.

        A stream that delivered only hidden reasoning is reported as
        *unverified*, never as *unsupported*: the missing visible token came
        from the probe's own output cap, and a persisted ``unsupported`` verdict
        blocks every later streaming turn with HTTP 409. The probe first buys
        one retry with real headroom; the first real send stays the live
        confirmation when that is still not enough.
        """

        protocol = self._configured_protocol(provider)
        uses_default_stream = (
            getattr(self.chat_completion_stream, "__func__", None)
            is getattr(type(self), "chat_completion_stream", None)
        )
        if uses_default_stream and protocol in {
            "openai_chat_completions",
            "openai_chat_completions_compatible",
        }:
            max_tokens = self._visible_probe_budget(provider, 16)
            outcome = self._streaming_probe_attempt(provider, api_key, max_tokens)
            if outcome is None:
                return None, "Streaming capability probe could not complete safely."
            observed, reasoning_limited = outcome
            if not observed and reasoning_limited:
                self._note_hidden_reasoning(provider)
                escalated = self._probe_retry_budget(provider, max_tokens)
                retry = (
                    self._streaming_probe_attempt(provider, api_key, escalated)
                    if escalated
                    else None
                )
                if retry is not None and retry[0]:
                    return True, (
                        "Streaming probe returned visible incremental content after a "
                        "larger output budget."
                    )
                return None, (
                    "Streaming probe returned only hidden reasoning within its output "
                    "budget; streaming support remains unverified."
                )
            if observed:
                return True, "Streaming probe returned visible incremental content."
            return False, "Streaming probe completed without visible incremental content."

        async def consume(max_tokens: int) -> bool:
            target_service = (
                self
                if self._config is provider and self._api_key == api_key
                else cast(Any, getattr(_sys.modules.get("app.llm.provider_service"), "ProviderService", type(self)))(config=provider, api_key=api_key)
            )
            stream = target_service.chat_completion_stream(
                [{"role": "user", "content": "Reply with one short visible word: OK."}],
                model=provider.model,
                temperature=0,
                # Some reasoning-first providers consume a short output budget
                # before emitting their first visible token. Keep this probe
                # aligned with the other visible-token probes so a working
                # native stream is not reported as unavailable.
                max_tokens=max_tokens,
            )
            try:
                async for chunk in stream:
                    if isinstance(chunk, str) and chunk.strip():
                        return True
                return False
            finally:
                await stream.aclose()

        def consume_from_event_loop(max_tokens: int) -> bool:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(consume(max_tokens))
            # Provider tests are normally synchronous FastAPI handlers, but
            # keep the probe safe when called from an async test or host.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, consume(max_tokens)).result()

        # This path yields visible text only, so a silent stream cannot be
        # attributed to reasoning from the outside. Buy one larger-budget
        # attempt, then leave the capability unverified instead of reporting a
        # working native stream as unsupported.
        max_tokens = self._visible_probe_budget(provider, 16)
        budgets = [max_tokens]
        escalated = self._probe_retry_budget(provider, max_tokens)
        if escalated:
            budgets.append(escalated)
        try:
            for index, budget in enumerate(budgets):
                if consume_from_event_loop(budget):
                    return True, (
                        "Streaming probe returned visible incremental content."
                        if index == 0
                        else (
                            "Streaming probe returned visible incremental content "
                            "after a larger output budget."
                        )
                    )
        except Exception:  # noqa: BLE001 - capability probes must not leak upstream details.
            return None, "Streaming capability probe could not complete safely."
        return None, (
            "Streaming probe returned no visible incremental content within its output "
            "budget; streaming support remains unverified."
        )

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
            try:
                response = client.embeddings.create(model=embedding_model, input="ok")
            finally:
                self._close_sync_client(client)
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
            try:
                if protocol == "openai_responses":
                    req = self._apply_openai_responses_probe_defaults(
                        {
                            "model": provider.model,
                            "input": 'Reply with JSON object {"ok": true} only.',
                            "temperature": 0,
                            "max_output_tokens": 32,
                            "text": {"format": {"type": "json_object"}},
                        },
                        provider,
                    )
                    response = client.responses.create(**req)
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
                    response = self._create_chat_completion_negotiated(client, payload, provider)
                    message = response.choices[0].message if getattr(response, "choices", None) else None
                    content = str(getattr(message, "content", "") or "")
            finally:
                self._close_sync_client(client)
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
        *,
        reuse_verified_capabilities: bool = False,
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

        # ``_capability_truth`` is keyed to this exact transport: the runtime
        # overlays its persisted last-test states, and a live test on this
        # instance writes them. A caller that only needs the language probes
        # may reuse a verified observation instead of paying for it again.
        verified_before = dict(self._capability_truth) if reuse_verified_capabilities else {}

        def observe(
            name: str, probe: Callable[[], tuple[bool | None, str]]
        ) -> tuple[bool | None, str]:
            if verified_before.get(name) == "verified":
                return True, "Reused the verified observation recorded for this connection."
            return self._retry_indeterminate_capability_probe(probe)

        tool_probe_diagnostic: str | None = None
        should_probe_tools = bool(provider.capabilities.tools) or openai_chat_family
        if should_probe_tools:
            if result.ok and api_key:
                observations["tools"], tool_probe_diagnostic = observe(
                    "tools", lambda: self._probe_tool_capability(provider, api_key)
                )
            else:
                tool_probe_diagnostic = (
                    "Tool-call capability was not probed because the base provider check did not complete."
                )

        stream_probe_diagnostic: str | None = None
        if provider.capabilities.streaming:
            if result.ok and api_key:
                observations["streaming"], stream_probe_diagnostic = observe(
                    "streaming", lambda: self._probe_streaming_capability(provider, api_key)
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
                observations["thinking"], thinking_probe_diagnostic = observe(
                    "thinking", lambda: self._probe_thinking_capability(provider, api_key)
                )
            else:
                thinking_probe_diagnostic = (
                    "Thinking capability was not probed because the base provider check did not complete."
                )

        vision_probe_diagnostic: str | None = None
        if provider.capabilities.vision:
            if result.ok and api_key:
                observations["vision"], vision_probe_diagnostic = observe(
                    "vision", lambda: self._probe_vision_capability(provider, api_key)
                )
            else:
                vision_probe_diagnostic = (
                    "Vision capability was not probed because the base provider check did not complete."
                )

        embeddings_probe_diagnostic: str | None = None
        if provider.capabilities.embeddings:
            if result.ok and api_key:
                observations["embeddings"], embeddings_probe_diagnostic = observe(
                    "embeddings", lambda: self._probe_embeddings_capability(provider, api_key)
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
                observations["structured_output"], structured_probe_diagnostic = observe(
                    "structured_output",
                    lambda: self._probe_structured_output_capability(provider, api_key),
                )
                if provider.capabilities.json_schema:
                    observations["json_schema"] = observations.get("structured_output")
            else:
                structured_probe_diagnostic = (
                    "Structured output capability was not probed because the base provider check did not complete."
                )

        listing_probe_diagnostic: str | None = None
        if result.ok and api_key:
            observations["model_listing"], listing_probe_diagnostic = observe(
                "model_listing", lambda: self._probe_model_listing_capability(provider, api_key)
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
        transient_preflight_failure = (
            reuse_verified_capabilities
            and not result.ok
            and result.error_category in {"rate_limit", "timeout", "network", "upstream_unavailable"}
        )
        if not transient_preflight_failure:
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
        reuse_verified_capabilities: bool = False,
    ) -> ProviderTestResponse:
        """Run the connection test.

        ``reuse_verified_capabilities`` is for the turn-time language preflight,
        which only reads ``ok``/``error_category``: capabilities this exact
        transport already verified are reused instead of being probed again
        before every coaching reply. An explicit Settings test keeps live probes.
        """
        result = self._test_connectivity(
            provider,
            api_key,
            probe_message=probe_message,
            response_language=response_language,
        )
        effective_key = self._effective_wire_api_key(provider, api_key) or api_key
        result = self._with_capability_truth(
            result,
            provider,
            effective_key,
            reuse_verified_capabilities=reuse_verified_capabilities,
        )
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
        effective_key = self._effective_wire_api_key(provider, api_key)
        if not effective_key:
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
            effective_key,
            probe_message,
            response_language,
        )
        if native_result is not None:
            return native_result
        try:
            client = self._create_sync_client(provider, effective_key)
            try:
                chosen_model = None
                response = None
                compact_probe, visible_probe = self._native_probe_prompts(response_language)
                diagnostics = []
                hidden_reasoning_observed = False
                probe_max_tokens = _visible_probe_max_tokens(provider)
                # Reasoning-first models can spend the whole compact-probe
                # budget on hidden reasoning; retries use the same bounded
                # escalation as the coaching lanes so a working model is not
                # reported as an unusable provider.
                probe_retry_max_tokens = (
                    self._escalated_chat_budget(probe_max_tokens) or probe_max_tokens
                )
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
                                        "max_tokens": probe_retry_max_tokens,
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
                                "max_tokens": probe_retry_max_tokens,
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
                            max_tokens=max(probe_max_tokens, probe_retry_max_tokens),
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
                # Every compact attempt has run by now: later probes of this
                # connection start from a budget that fits its reasoning.
                if hidden_reasoning_observed:
                    self._note_hidden_reasoning(provider)
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
                        provider_config=provider,
                        api_key=api_key,
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
                    provider_config=provider,
                    api_key=api_key,
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
