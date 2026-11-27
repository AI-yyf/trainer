"""Bind :class:`~app.llm.provider_service.ProviderService` to
:class:`~app.llm.agent_loop.CoachAgentLoop`.

The agent loop only needs three concrete capabilities from a provider:

1. ``call(messages, tools)`` -> ``{"content": str, "tool_calls": [...]}``
2. ``call_stream(messages, tools)`` -> async iterator yielding
   ``{"type": "delta", "delta": str}`` / ``{"type": "final", ...}``
3. ``protocol`` (string)

This module is the only place that knows how to translate Trainer's
canonical OpenAI-format history into each provider protocol's native
request, and how to extract a tool-use response back into canonical form.

Supported protocols:

* ``openai_chat_completions`` / ``openai_chat_completions_compatible`` -
  uses the openai SDK's ``chat.completions.create`` with ``tools=`` and
  parses ``response.choices[0].message.tool_calls``.
* ``anthropic_messages`` - minimal direct httpx call against the public
  Anthropic Messages API. We avoid a hard dependency on the ``anthropic``
  Python SDK (the venv currently does not ship it) so this code runs on
  any Trainer install. Tool-use is parsed from the ``tool_use`` content
  blocks; vision attachments are sent as ``image`` content blocks.
* ``openai_responses`` - uses ``responses.create`` with Responses-format
  input items and parses both visible text and function calls.
* ``gemini_generate_content`` - posts native GenerateContent payloads with
  ``functionDeclarations`` and parses ``functionCall`` parts.

Vision / multimodal:

* OpenAI chat completions: ``image_url`` content parts.
* Anthropic: ``image`` content blocks (base64).
* Gemini GenerateContent: ``inlineData`` parts (base64).

This module deliberately does no model-specific routing or temperature
choice; ``ProviderService`` already handles model resolution and
``coaching_reply`` parameters. Here we only thread the request through.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast

import httpx as httpx

from .agent_binding_helpers import (
    ANTHROPIC_API_VERSION as ANTHROPIC_API_VERSION,
)
from .agent_binding_helpers import (
    ANTHROPIC_AUTH_HEADER_MARKERS as ANTHROPIC_AUTH_HEADER_MARKERS,
)
from .agent_binding_helpers import (
    ANTHROPIC_AUTH_MISMATCH_MARKERS as ANTHROPIC_AUTH_MISMATCH_MARKERS,
)
from .agent_binding_helpers import (
    ANTHROPIC_DEFAULT_MAX_TOKENS as ANTHROPIC_DEFAULT_MAX_TOKENS,
)
from .agent_binding_helpers import (
    ANTHROPIC_PROTOCOL_MISMATCH_STATUS_CODES as ANTHROPIC_PROTOCOL_MISMATCH_STATUS_CODES,
)
from .agent_binding_helpers import (
    ANTHROPIC_VISIBLE_REPLY_RETRY_ATTEMPTS as ANTHROPIC_VISIBLE_REPLY_RETRY_ATTEMPTS,
)
from .agent_binding_helpers import (
    ANTHROPIC_VISIBLE_REPLY_RETRY_HINT as ANTHROPIC_VISIBLE_REPLY_RETRY_HINT,
)
from .agent_binding_helpers import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS as DEFAULT_REQUEST_TIMEOUT_SECONDS,
)
from .agent_binding_helpers import (
    OPENAI_TRUNCATED_OUTPUT_RETRY_MAX_TOKENS as OPENAI_TRUNCATED_OUTPUT_RETRY_MAX_TOKENS,
)
from .agent_binding_helpers import (
    OPENAI_VISIBLE_REPLY_RETRY_ATTEMPTS as OPENAI_VISIBLE_REPLY_RETRY_ATTEMPTS,
)
from .agent_binding_helpers import (
    OPENAI_VISIBLE_REPLY_RETRY_HINT as OPENAI_VISIBLE_REPLY_RETRY_HINT,
)
from .agent_binding_helpers import (
    TRANSPORT_TIMEOUT_MARGIN_SECONDS as TRANSPORT_TIMEOUT_MARGIN_SECONDS,
)
from .agent_binding_helpers import (
    _anthropic_image_blocks as _anthropic_image_blocks,
)
from .agent_binding_helpers import (
    _anthropic_response_indicates_protocol_mismatch as _anthropic_response_indicates_protocol_mismatch,
)
from .agent_binding_helpers import (
    _anthropic_visible_retry_payload as _anthropic_visible_retry_payload,
)
from .agent_binding_helpers import (
    _base_url_is_official_anthropic as _base_url_is_official_anthropic,
)
from .agent_binding_helpers import (
    _coerce_to_dict as _coerce_to_dict,
)
from .agent_binding_helpers import (
    _ensure_json_arguments as _ensure_json_arguments,
)
from .agent_binding_helpers import (
    _extract_openai_tool_calls as _extract_openai_tool_calls,
)
from .agent_binding_helpers import (
    _format_anthropic_payload as _format_anthropic_payload,
)
from .agent_binding_helpers import (
    _format_anthropic_tools as _format_anthropic_tools,
)
from .agent_binding_helpers import (
    _format_gemini_payload as _format_gemini_payload,
)
from .agent_binding_helpers import (
    _format_openai_messages as _format_openai_messages,
)
from .agent_binding_helpers import (
    _format_openai_responses_input as _format_openai_responses_input,
)
from .agent_binding_helpers import (
    _gemini_image_parts as _gemini_image_parts,
)
from .agent_binding_helpers import (
    _get_field as _get_field,
)
from .agent_binding_helpers import (
    _iterate_and_close_provider_stream as _iterate_and_close_provider_stream,
)
from .agent_binding_helpers import (
    _last_index_with_role as _last_index_with_role,
)
from .agent_binding_helpers import (
    _normalize_openai_chat_tool as _normalize_openai_chat_tool,
)
from .agent_binding_helpers import (
    _openai_chat_visible_text as _openai_chat_visible_text,
)
from .agent_binding_helpers import (
    _openai_image_parts as _openai_image_parts,
)
from .agent_binding_helpers import (
    _openai_responses_image_urls as _openai_responses_image_urls,
)
from .agent_binding_helpers import (
    _openai_tool_payload as _openai_tool_payload,
)
from .agent_binding_helpers import (
    _openai_visible_retry_messages as _openai_visible_retry_messages,
)
from .agent_binding_helpers import (
    _parse_anthropic_response as _parse_anthropic_response,
)
from .agent_binding_helpers import (
    _parse_gemini_response as _parse_gemini_response,
)
from .agent_binding_helpers import (
    _parse_openai_chat_response as _parse_openai_chat_response,
)
from .agent_binding_helpers import (
    _parse_openai_responses_response as _parse_openai_responses_response,
)
from .agent_binding_helpers import (
    _requested_protocol_is_gemini as _requested_protocol_is_gemini,
)
from .agent_binding_helpers import (
    _serialize_responses_reasoning_item as _serialize_responses_reasoning_item,
)
from .agent_binding_helpers import (
    _split_anthropic_messages as _split_anthropic_messages,
)
from .agent_binding_helpers import (
    _StreamWhitespaceTrimmer as _StreamWhitespaceTrimmer,
)
from .agent_binding_helpers import (
    _url_is_anthropic as _url_is_anthropic,
)
from .agent_binding_helpers import (
    _url_is_google_gemini_native as _url_is_google_gemini_native,
)
from .agent_binding_helpers import (
    _usage_payload as _usage_payload,
)
from .agent_binding_helpers import (
    attachments_supported as attachments_supported,
)
from .agent_binding_helpers import (
    resolve_agent_protocol as resolve_agent_protocol,
)
from .agent_binding_protocols_mixin import AgentBindingProtocolsMixin
from .agent_loop import AgentProvider
from .provider.capability import (
    _is_loopback_provider_url,
)
from .provider.errors import ContextBudgetExhaustedError
from .provider.streaming import (
    STREAM_IDLE_TIMEOUT_SECONDS,
    _iterate_provider_stream_with_cancellation,
)
from .provider.text import ReasoningBlockFilter
from .provider_protocols import (
    _finish_reason_is_truncated,
    assess_provider_error,
    safe_provider_diagnostic,
)
from .provider_service import (
    ProviderRuntimeResponseError,
    _require_provider_runtime_response,
    _visible_model_text,
)
from .tools import ToolDefinition, ToolRegistry

logger = logging.getLogger(__name__)


class ProviderAgentBinding(AgentBindingProtocolsMixin):
    """Builds and dispatches agent-loop calls for a configured provider.

    A single binding is cheap to construct and stateless beyond holding a
    reference to the underlying ``ProviderService`` (for OpenAI client
    reuse and model resolution) plus the negotiated protocol.
    """

    def __init__(
        self,
        *,
        provider_service: Any,
        protocol: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        anthropic_base_url: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        emit_activity: bool = False,
    ) -> None:
        self._emit_activity = bool(emit_activity)
        self._provider_service = provider_service
        config = getattr(provider_service, "_config", None)
        config_base_url = getattr(config, "base_url", None) if config is not None else None
        config_protocol = getattr(config, "protocol", None) if config is not None else None
        self._base_url = str(config_base_url or "").strip()
        if protocol is None:
            protocol = config_protocol
        self._requested_protocol = str(protocol or "").strip().lower()
        self._protocol = resolve_agent_protocol(protocol, base_url=config_base_url)
        self._compatibility_openai_visible_retry = (
            _requested_protocol_is_gemini(self._requested_protocol)
            and bool(self._base_url)
            and not _url_is_google_gemini_native(self._base_url)
        )
        self._attachments = list(attachments or [])
        self._vision_enabled = self._infer_vision_enabled()
        self._anthropic_base_url = (
            anthropic_base_url or self._infer_anthropic_base_url() or "https://api.anthropic.com"
        ).rstrip("/")
        self._temperature = temperature
        self._max_tokens = max(
            1024 if self._protocol == "gemini_generate_content" else 1, int(max_tokens)
        )

    # -- public --------------------------------------------------------------

    @property
    def protocol(self) -> str:
        return self._protocol

    def build_agent_provider(self) -> AgentProvider:
        return AgentProvider(
            protocol=self._protocol,
            call=self._call,
            call_stream=self._call_stream,
        )

    def attachments_will_be_sent(self) -> bool:
        return bool(self._attachments and self._vision_enabled)

    def _api_key_for_diagnostics(self) -> str | None:
        api_key = getattr(self._provider_service, "_api_key", None)
        return api_key if isinstance(api_key, str) and api_key else None

    def _uses_loopback_transport(self) -> bool:
        """Return whether the bound provider targets a local loopback host."""
        probe = getattr(self._provider_service, "_uses_loopback_transport", None)
        if callable(probe):
            return bool(probe())
        config = getattr(self._provider_service, "_config", None)
        return _is_loopback_provider_url(getattr(config, "base_url", None))

    def _should_bypass_system_proxy(self) -> bool:
        """Return whether HTTP requests should bypass ambient proxy environment variables."""
        probe = getattr(self._provider_service, "_should_bypass_system_proxy", None)
        if callable(probe):
            return bool(probe())
        config = getattr(self._provider_service, "_config", None)
        return bool(getattr(config, "ignore_system_proxy", False)) or self._uses_loopback_transport()

    def _async_http_client(
        self,
        *,
        timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> httpx.AsyncClient:
        """Construct an async HTTP client bypassing ambient proxies for loopback or direct mode."""
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if self._should_bypass_system_proxy():
            client_kwargs["trust_env"] = False
        return httpx.AsyncClient(**client_kwargs)

    def _validated_result(
        self,
        response: object | None,
        parsed: dict[str, Any],
        *,
        protocol: str | None = None,
    ) -> dict[str, Any]:
        """Keep only a normalized response that can continue an agent turn."""
        normalized = dict(parsed)
        normalized["content"] = _require_provider_runtime_response(
            protocol or self._protocol,
            response,
            api_key=self._api_key_for_diagnostics(),
            allow_tool_calls=True,
        )
        return normalized

    def _http_failure(
        self,
        *,
        status_code: int,
        body: object | None,
    ) -> ProviderRuntimeResponseError:
        """Classify an HTTP error without carrying its body into runtime output."""
        assessment = assess_provider_error(
            self._protocol,
            body,
            status_code=status_code,
            api_key=self._api_key_for_diagnostics(),
        )
        category = assessment.category
        retryable = assessment.retryable
        if category == "provider_error":
            if status_code in {401, 403}:
                category = "invalid_key_or_permission"
                retryable = False
            elif status_code == 402:
                category = "quota_exhausted"
                retryable = False
            elif status_code == 429:
                category = "rate_limit"
                retryable = True
        detail = (
            assessment.diagnostic
            if category == "protocol_mismatch"
            else f"Provider request failed (HTTP {status_code})."
        )
        return ProviderRuntimeResponseError(
            category=category,
            detail=detail,
            retryable=retryable,
            status_code=status_code,
        )

    # -- protocol dispatch ---------------------------------------------------

    async def _call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        if self._protocol == "anthropic_messages":
            return await self._anthropic_call(messages, tools)
        if self._protocol == "openai_responses":
            return await self._openai_responses_call(messages, tools)
        if self._protocol == "gemini_generate_content":
            return await self._gemini_call(messages, tools)
        return await self._openai_chat_call(messages, tools)

    async def _call_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        if self._protocol == "anthropic_messages":
            async for event in self._anthropic_stream(messages, tools):
                yield event
            return
        if self._protocol == "openai_responses":
            async for event in self._openai_responses_stream(messages, tools):
                yield event
            return
        if self._protocol == "gemini_generate_content":
            async for event in self._gemini_stream(messages, tools):
                yield event
            return
        async for event in self._openai_chat_stream(messages, tools):
            yield event

    # -- OpenAI Responses ---------------------------------------------------

    async def _openai_responses_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        client = self._provider_service._get_client()  # noqa: SLF001 - intentional
        instructions, input_items = _format_openai_responses_input(
            messages,
            attachments=self._attachments,
            vision_enabled=self._vision_enabled,
        )
        kwargs: dict[str, Any] = {
            "input": input_items,
            "temperature": self._temperature,
            "max_output_tokens": self._max_tokens,
        }
        if instructions:
            kwargs["instructions"] = instructions
        if tools:
            kwargs["tools"] = tools
        kwargs = self._apply_openai_responses_request_defaults(kwargs)
        model = self._provider_service._resolve_model()  # noqa: SLF001
        last_error: Exception | None = None
        for candidate in self._provider_service._model_candidates(model):  # noqa: SLF001
            attempt_kwargs = dict(kwargs)
            try:
                try:
                    response = await client.responses.create(model=candidate, **attempt_kwargs)
                except Exception as temp_exc:  # noqa: BLE001
                    if "temperature" in attempt_kwargs and "temperature" in str(temp_exc).lower():
                        attempt_kwargs.pop("temperature", None)
                        response = await client.responses.create(model=candidate, **attempt_kwargs)
                    else:
                        raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not self._provider_service._is_model_not_supported_error(exc):  # noqa: SLF001
                    raise
                continue
            return self._validated_result(response, _parse_openai_responses_response(response))
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Unable to resolve a usable OpenAI Responses model for {model!r}.")

    async def _openai_responses_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        client = self._provider_service._get_client()  # noqa: SLF001 - intentional
        instructions, input_items = _format_openai_responses_input(
            messages,
            attachments=self._attachments,
            vision_enabled=self._vision_enabled,
        )
        kwargs: dict[str, Any] = {
            "input": input_items,
            "temperature": self._temperature,
            "max_output_tokens": self._max_tokens,
        }
        if instructions:
            kwargs["instructions"] = instructions
        if tools:
            kwargs["tools"] = tools
        kwargs = self._apply_openai_responses_request_defaults(kwargs)
        model = self._provider_service._resolve_model()  # noqa: SLF001
        last_error: Exception | None = None
        response_stream_cm = None
        response_stream = None
        for candidate in self._provider_service._model_candidates(model):  # noqa: SLF001
            attempt_kwargs = dict(kwargs)
            try:
                try:
                    cm = client.responses.stream(model=candidate, **attempt_kwargs)
                    entered = await cm.__aenter__()
                    response_stream_cm = cm
                    response_stream = entered
                    break
                except Exception as temp_exc:  # noqa: BLE001
                    if "temperature" in attempt_kwargs and "temperature" in str(temp_exc).lower():
                        attempt_kwargs.pop("temperature", None)
                        cm = client.responses.stream(model=candidate, **attempt_kwargs)
                        entered = await cm.__aenter__()
                        response_stream_cm = cm
                        response_stream = entered
                        break
                    raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not self._provider_service._is_model_not_supported_error(exc):  # noqa: SLF001
                    raise
                continue
        if response_stream is None or response_stream_cm is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError(f"Unable to resolve a usable OpenAI Responses model for {model!r}.")

        text_buffer = ""
        reasoning_filter = ReasoningBlockFilter()
        trimmer = _StreamWhitespaceTrimmer()
        emitted_reasoning = False
        emitted_tool_drafts: set[int] = set()
        reasoning_items: list[dict[str, Any]] = []
        tool_call_state: dict[int, dict[str, Any]] = {}
        try:
            async for event in _iterate_provider_stream_with_cancellation(
                response_stream,
                None,
                idle_timeout=STREAM_IDLE_TIMEOUT_SECONDS,
            ):
                event_type = str(getattr(event, "type", "") or "")
                if "reasoning" in event_type and not emitted_reasoning:
                    emitted_reasoning = True
                    if self._emit_activity:
                        yield {"type": "provider_activity", "phase": "model_reasoning"}
                if event_type in {"response.output_item.added", "response.output_item.done"}:
                    item = getattr(event, "item", None)
                    item_type = str(getattr(item, "type", "") or "") if item is not None else ""
                    if item_type == "reasoning":
                        if not emitted_reasoning:
                            emitted_reasoning = True
                            if self._emit_activity:
                                yield {"type": "provider_activity", "phase": "model_reasoning"}
                        if event_type == "response.output_item.done":
                            serialized = _serialize_responses_reasoning_item(item)
                            if serialized:
                                reasoning_items.append(serialized)
                        continue
                    if item is None or item_type != "function_call":
                        continue
                    index = int(getattr(event, "output_index", 0) or 0)
                    slot = tool_call_state.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    call_id = getattr(item, "call_id", None) or getattr(item, "id", None)
                    if call_id:
                        slot["id"] = str(call_id)
                    name = getattr(item, "name", None)
                    if name:
                        slot["name"] = str(name)
                        if index not in emitted_tool_drafts:
                            emitted_tool_drafts.add(index)
                            if self._emit_activity:
                                yield {
                                    "type": "provider_activity",
                                    "phase": "tool_drafting",
                                    "name": slot["name"],
                                }
                    arguments = getattr(item, "arguments", None)
                    if isinstance(arguments, str):
                        slot["arguments"] = arguments
                    elif arguments is not None:
                        slot["arguments"] = _ensure_json_arguments(arguments)
                    continue
                if event_type == "response.output_text.delta":
                    piece = str(getattr(event, "delta", "") or "")
                    if piece:
                        visible_piece = trimmer.push(reasoning_filter.push(piece))
                        if visible_piece:
                            text_buffer += visible_piece
                            yield {"type": "delta", "delta": visible_piece}
                    continue
                if event_type == "response.function_call_arguments.delta":
                    piece = str(getattr(event, "delta", "") or "")
                    if piece:
                        index = int(getattr(event, "output_index", 0) or 0)
                        slot = tool_call_state.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        slot["arguments"] += piece
                    continue
                if event_type == "response.completed":
                    break
            final_response = await response_stream.get_final_response()
        finally:
            await response_stream_cm.__aexit__(None, None, None)

        tail = trimmer.push(reasoning_filter.flush())
        if tail:
            text_buffer += tail
            yield {"type": "delta", "delta": tail}

        tool_calls = [
            {"id": item["id"] or item["name"], "name": item["name"], "arguments": item["arguments"]}
            for _, item in sorted(tool_call_state.items())
            if item["name"]
        ]
        if not reasoning_items and final_response is not None:
            parsed_final = _parse_openai_responses_response(final_response)
            final_pr = parsed_final.get("provider_reasoning")
            if isinstance(final_pr, dict) and isinstance(final_pr.get("responses_reasoning_items"), list):
                reasoning_items = list(final_pr["responses_reasoning_items"])
        final_status = str(_get_field(final_response, "status", "") or "").strip().lower()
        normalized = self._validated_result(
            final_response,
            {"content": _visible_model_text(text_buffer), "tool_calls": tool_calls},
            protocol="openai_responses",
        )
        final_event: dict[str, Any] = {
            "type": "final",
            "content": normalized["content"],
            "tool_calls": tool_calls,
            "stop_reason": (
                "tool_calls"
                if tool_calls
                else ("length" if final_status == "incomplete" else "stop")
            ),
        }
        usage_payload = _usage_payload(final_response)
        if usage_payload is not None:
            final_event["usage"] = usage_payload
        if reasoning_items:
            final_event["provider_reasoning"] = {"responses_reasoning_items": reasoning_items}
        yield final_event

    # -- Gemini GenerateContent --------------------------------------------

    async def _gemini_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        api_key, model = self._gemini_credentials()
        payload = self._apply_gemini_request_defaults(
            _format_gemini_payload(
                messages,
                tools,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                attachments=self._attachments,
                vision_enabled=self._vision_enabled,
            )
        )
        endpoint = self._gemini_endpoint(model)
        async with self._async_http_client() as client:
            response = await client.post(
                endpoint,
                json=payload,
                headers=self._gemini_headers(api_key),
            )
        if response.status_code >= 400:
            raise self._http_failure(status_code=response.status_code, body=response.text)
        payload = response.json()
        return self._validated_result(payload, _parse_gemini_response(payload))

    async def _gemini_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        api_key, model = self._gemini_credentials()
        payload = self._apply_gemini_request_defaults(
            _format_gemini_payload(
                messages,
                tools,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                attachments=self._attachments,
                vision_enabled=self._vision_enabled,
            )
        )
        endpoint = self._gemini_endpoint(model, stream=True)
        async with self._async_http_client() as client:
            async with client.stream(
                "POST",
                endpoint,
                json=payload,
                headers=self._gemini_headers(api_key),
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise self._http_failure(
                        status_code=response.status_code,
                        body=body.decode("utf-8", errors="replace"),
                    )
                text_buffer = ""
                reasoning_filter = ReasoningBlockFilter()
                trimmer = _StreamWhitespaceTrimmer()
                emitted_reasoning = False
                finish_reason: str | None = None
                last_usage_event: dict[str, Any] | None = None

                def _finish_seen() -> bool:
                    return bool(finish_reason)

                tool_call_entries: list[dict[str, Any]] = []
                thought_signatures: list[str | None] = []
                async for raw_line in _iterate_provider_stream_with_cancellation(
                    response.aiter_lines(),
                    None,
                    idle_timeout=STREAM_IDLE_TIMEOUT_SECONDS,
                    finish_seen=_finish_seen,
                ):
                    if not raw_line or not raw_line.startswith("data:"):
                        continue
                    data_text = raw_line[5:].strip()
                    if not data_text or data_text == "[DONE]":
                        continue
                    try:
                        event = json.loads(data_text)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if isinstance(event.get("usageMetadata") or event.get("usage_metadata"), dict):
                        last_usage_event = event
                    candidates = event.get("candidates") or []
                    for candidate in candidates:
                        if not isinstance(candidate, dict):
                            continue
                        candidate_finish = candidate.get("finishReason") or candidate.get("finish_reason")
                        if isinstance(candidate_finish, str) and candidate_finish.strip():
                            finish_reason = candidate_finish.strip()
                        content = candidate.get("content") or {}
                        parts = content.get("parts") if isinstance(content, dict) else []
                        for part in parts or []:
                            if not isinstance(part, dict):
                                continue
                            if part.get("thought") is True:
                                if not emitted_reasoning:
                                    emitted_reasoning = True
                                    if self._emit_activity:
                                        yield {"type": "provider_activity", "phase": "model_reasoning"}
                                continue
                            piece = part.get("text")
                            if isinstance(piece, str) and piece:
                                visible_piece = trimmer.push(reasoning_filter.push(piece))
                                if visible_piece:
                                    text_buffer += visible_piece
                                    yield {"type": "delta", "delta": visible_piece}
                            function_call = part.get("functionCall") or part.get("function_call")
                            if not isinstance(function_call, dict):
                                continue
                            name = str(function_call.get("name") or "")
                            if not name:
                                continue
                            call_id = str(function_call.get("id") or "")
                            args = function_call.get("args")
                            if args is None:
                                args = function_call.get("arguments")
                            sig = part.get("thoughtSignature") or part.get("thought_signature")
                            resolved_sig = str(sig) if isinstance(sig, str) and sig else None
                            matched_entry = (
                                next((e for e in tool_call_entries if call_id and e.get("id") == call_id), None)
                                if call_id
                                else None
                            )
                            if matched_entry is None:
                                entry: dict[str, Any] = {
                                    "id": call_id or name,
                                    "name": name,
                                    "arguments": dict(args) if isinstance(args, dict) else (str(args) if args is not None else {}),
                                }
                                tool_call_entries.append(entry)
                                thought_signatures.append(resolved_sig)
                                if self._emit_activity:
                                    yield {
                                        "type": "provider_activity",
                                        "phase": "tool_drafting",
                                        "name": name,
                                    }
                            else:
                                if isinstance(args, dict):
                                    existing_args = matched_entry.get("arguments")
                                    matched_entry["arguments"] = (
                                        self._merge_record(existing_args, args)
                                        if isinstance(existing_args, dict)
                                        else dict(args)
                                    )
                                elif args is not None:
                                    matched_entry["arguments"] = str(args)
                tail = trimmer.push(reasoning_filter.flush())
                if tail:
                    text_buffer += tail
                    yield {"type": "delta", "delta": tail}

        tool_calls = [
            {
                "id": item["id"] or item["name"],
                "name": item["name"],
                "arguments": item["arguments"] if item["arguments"] is not None else {},
            }
            for item in tool_call_entries
            if item["name"]
        ]
        final_payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            *([{"text": text_buffer}] if text_buffer else []),
                            *[
                                {
                                    "functionCall": {
                                        "name": item["name"],
                                        "args": item["arguments"]
                                        if item["arguments"] is not None
                                        else {},
                                    }
                                }
                                for item in tool_calls
                            ],
                        ]
                    },
                    **({"finishReason": finish_reason} if finish_reason else {}),
                }
            ]
        }
        normalized = self._validated_result(
            final_payload,
            {"content": _visible_model_text(text_buffer), "tool_calls": tool_calls},
            protocol="gemini_generate_content",
        )
        final_event: dict[str, Any] = {
            "type": "final",
            "content": normalized["content"],
            "tool_calls": tool_calls,
            "stop_reason": (
                "tool_calls"
                if tool_calls
                else ("length" if _finish_reason_is_truncated(finish_reason) else "stop")
            ),
        }
        usage_payload = _usage_payload(last_usage_event) if last_usage_event is not None else None
        if usage_payload is not None:
            final_event["usage"] = usage_payload
        if any(thought_signatures):
            final_event["provider_reasoning"] = {"gemini_thought_signatures": thought_signatures}
        yield final_event

    async def _create_openai_negotiated(
        self,
        client: Any,
        payload: dict[str, Any],
    ) -> Any:
        """Create through the provider's thinking re-negotiation when present.

        Unit-test bindings and third-party provider services may only expose a
        raw OpenAI client; production ProviderService owns the negotiated path.
        """
        negotiated = getattr(
            self._provider_service,
            "_create_chat_completion_negotiated_async",
            None,
        )
        if callable(negotiated):
            create = cast(Callable[..., Awaitable[Any]], negotiated)
            return await create(client, payload)
        return await client.chat.completions.create(**payload)

    async def _openai_visible_retry_result(
        self,
        client: Any,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
    ) -> dict[str, Any] | None:
        if not self._compatibility_openai_visible_retry:
            return None
        retry_messages = _openai_visible_retry_messages(messages)
        kwargs: dict[str, Any] = {
            "messages": retry_messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        kwargs.update(_openai_tool_payload(tools))
        kwargs = self._provider_service._apply_request_defaults(kwargs)  # noqa: SLF001
        for _attempt in range(OPENAI_VISIBLE_REPLY_RETRY_ATTEMPTS):
            try:
                response = await client.chat.completions.create(model=model, **kwargs)
            except Exception as exc:  # noqa: BLE001 - compatibility retry is best-effort
                logger.warning(
                    "gemini_compatible_openai_visible_retry_failed",
                    extra={
                        "detail": safe_provider_diagnostic(
                            exc,
                            api_key=self._api_key_for_diagnostics(),
                        )
                    },
                )
                return None
            parsed = _parse_openai_chat_response(response)
            try:
                return self._validated_result(
                    response,
                    parsed,
                    protocol="openai_chat_completions",
                )
            except ProviderRuntimeResponseError:
                continue
        return None

    async def _openai_truncated_budget_retry(
        self,
        client: Any,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
    ) -> dict[str, Any] | None:
        """Retry once with a larger output budget after a truncated reply.

        Reasoning and tool arguments can exhaust the initial budget. Respect
        the configured model and context limits for the replacement request.
        """
        escalated = OPENAI_TRUNCATED_OUTPUT_RETRY_MAX_TOKENS
        budget = getattr(self._provider_service, "_effective_output_token_budget", None)
        if callable(budget):
            try:
                configured = budget(messages, model=model, requested_max_tokens=escalated)
            except ContextBudgetExhaustedError:
                return None
            if isinstance(configured, int):
                escalated = min(escalated, configured)
        if escalated <= self._max_tokens:
            return None
        kwargs: dict[str, Any] = {
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": escalated,
        }
        kwargs.update(_openai_tool_payload(tools))
        kwargs = self._provider_service._apply_request_defaults(kwargs)  # noqa: SLF001
        try:
            response = await self._create_openai_negotiated(
                client,
                {"model": model, **kwargs},
            )
        except Exception as exc:  # noqa: BLE001 - escalation is best-effort
            logger.warning(
                "openai_truncated_budget_retry_failed",
                extra={
                    "detail": safe_provider_diagnostic(
                        exc,
                        api_key=self._api_key_for_diagnostics(),
                    )
                },
            )
            return None
        parsed = _parse_openai_chat_response(response)
        try:
            return self._validated_result(
                response,
                parsed,
                protocol="openai_chat_completions",
            )
        except ProviderRuntimeResponseError:
            return None

    # -- OpenAI chat completions -------------------------------------------

    async def _openai_chat_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        compatibility_thinking_disabled: bool = False,
    ) -> dict[str, Any]:
        client = self._provider_service._get_client()  # noqa: SLF001 - intentional
        formatted = _format_openai_messages(
            messages,
            attachments=self._attachments,
            vision_enabled=self._vision_enabled,
        )
        kwargs: dict[str, Any] = {
            "messages": formatted,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        kwargs.update(_openai_tool_payload(tools))
        kwargs = self._provider_service._apply_request_defaults(kwargs)  # noqa: SLF001
        if compatibility_thinking_disabled:
            kwargs = self._apply_compatibility_thinking_disabled(kwargs)
        model = self._provider_service._resolve_model()  # noqa: SLF001
        last_error: Exception | None = None
        for candidate in self._provider_service._model_candidates(model):  # noqa: SLF001
            try:
                response = await self._create_openai_negotiated(
                    client,
                    {"model": candidate, **kwargs},
                )
            except Exception as exc:  # noqa: BLE001 - normalised below
                last_error = exc
                if not self._provider_service._is_model_not_supported_error(exc):  # noqa: SLF001
                    raise
                continue
            parsed = _parse_openai_chat_response(response)
            empty = not str(parsed.get("content") or "").strip() and not parsed.get("tool_calls")
            if empty:
                retry_result = await self._openai_visible_retry_result(
                    client,
                    messages=formatted,
                    tools=tools,
                    model=candidate,
                )
                if retry_result is not None:
                    return retry_result
            if empty or (tools and parsed.get("stop_reason") == "length"):
                budget_result = await self._openai_truncated_budget_retry(
                    client,
                    messages=formatted,
                    tools=tools,
                    model=candidate,
                )
                if budget_result is not None:
                    return budget_result
            return self._validated_result(
                response,
                parsed,
                protocol="openai_chat_completions",
            )
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Unable to resolve a usable OpenAI model for {model!r}.")


# ---------------------------------------------------------------------------
# Convenience for ProviderService
# ---------------------------------------------------------------------------


def build_agent_provider_for(
    provider_service: Any,
    *,
    protocol: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    emit_activity: bool = False,
) -> tuple[AgentProvider, ProviderAgentBinding]:
    binding = ProviderAgentBinding(
        provider_service=provider_service,
        protocol=protocol,
        attachments=attachments,
        temperature=temperature,
        max_tokens=max_tokens,
        emit_activity=emit_activity,
    )
    return binding.build_agent_provider(), binding


# Re-export for tests / callers
__all__ = [
    "ProviderAgentBinding",
    "build_agent_provider_for",
    "resolve_agent_protocol",
    "attachments_supported",
    "ANTHROPIC_API_VERSION",
]


# Quiet unused-import warning when ToolDefinition / ToolRegistry aren't directly
# referenced — they're part of the public surface for callers that need to
# inspect schemas before binding.
_re_export = (ToolDefinition, ToolRegistry)
