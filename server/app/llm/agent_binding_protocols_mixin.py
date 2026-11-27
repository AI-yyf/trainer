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
import sys as _sys
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit

import httpx as _real_httpx

from .agent_binding_helpers import (
    ANTHROPIC_API_VERSION,
    ANTHROPIC_VISIBLE_REPLY_RETRY_ATTEMPTS,
    _anthropic_response_indicates_protocol_mismatch,
    _anthropic_visible_retry_payload,
    _base_url_is_official_anthropic,
    _format_anthropic_payload,
    _format_anthropic_tools,
    _format_openai_messages,
    _get_field,
    _iterate_and_close_provider_stream,
    _openai_tool_payload,
    _parse_anthropic_response,
    _parse_openai_chat_response,
    _StreamWhitespaceTrimmer,
    _usage_payload,
    attachments_supported,
)
from .provider.capability import (
    _allows_keyless_local_provider,
    _model_looks_reasoning_first,
)
from .provider.streaming import (
    STREAM_IDLE_TIMEOUT_SECONDS,
    _iterate_provider_stream_with_cancellation,
    extract_non_sse_json_stream_payload,
)
from .provider.text import ReasoningBlockFilter
from .provider.thinking import (
    clamp_anthropic_thinking_budget,
    clamp_wire_thinking_budget,
    learned_policy,
)
from .provider_protocols import (
    _finish_reason_is_truncated,
    safe_provider_diagnostic,
)
from .provider_service import (
    ProviderRuntimeResponseError,
    _flatten_minimax_thinking_for_raw_http,
    _looks_like_provider_html_shell,
    _malformed_provider_html_shell_detail,
    _visible_model_text,
)


class _AgentBindingHttpxProxy:
    def __getattr__(self, name: str) -> Any:
        ab_mod = _sys.modules.get("app.llm.agent_binding")
        target = getattr(ab_mod, "httpx", _real_httpx) if ab_mod is not None else _real_httpx
        return getattr(target, name)


httpx: Any = _AgentBindingHttpxProxy()

logger = logging.getLogger(__name__)


class AgentBindingProtocolsMixin:
    if TYPE_CHECKING:
        _anthropic_base_url: Any
        _api_key_for_diagnostics: Any
        _async_http_client: Any
        _attachments: Any
        _base_url: Any
        _create_openai_negotiated: Any
        _emit_activity: Any
        _http_failure: Any
        _max_tokens: Any
        _openai_chat_call: Any
        _openai_truncated_budget_retry: Any
        _openai_visible_retry_result: Any
        _protocol: Any
        _provider_service: Any
        _temperature: Any
        _validated_result: Any
        _vision_enabled: Any

    async def _openai_chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        compatibility_thinking_disabled: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        client = self._provider_service._get_client()  # noqa: SLF001
        formatted = _format_openai_messages(
            messages,
            attachments=self._attachments,
            vision_enabled=self._vision_enabled,
        )
        kwargs: dict[str, Any] = {
            "messages": formatted,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": True,
        }
        kwargs.update(_openai_tool_payload(tools))
        kwargs = self._provider_service._apply_request_defaults(kwargs)  # noqa: SLF001
        if compatibility_thinking_disabled:
            kwargs = self._apply_compatibility_thinking_disabled(kwargs)
        model = self._provider_service._resolve_model()  # noqa: SLF001
        last_error: Exception | None = None
        stream = None
        chosen_model = model
        for candidate in self._provider_service._model_candidates(model):  # noqa: SLF001
            try:
                stream = await self._create_openai_negotiated(
                    client,
                    {"model": candidate, **kwargs},
                )
                chosen_model = candidate
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not self._provider_service._is_model_not_supported_error(exc):  # noqa: SLF001
                    raise
                continue
        if stream is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError(f"Unable to resolve a usable OpenAI model for {model!r}.")

        text_buffer = ""
        reasoning_filter = ReasoningBlockFilter()
        trimmer = _StreamWhitespaceTrimmer()
        emitted_reasoning = False
        emitted_tool_drafts: set[int] = set()
        tool_call_state: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        reasoning_content_parts: list[str] = []
        stream_usage_payload: dict[str, Any] | None = None

        def _finish_seen() -> bool:
            return finish_reason is not None

        async for chunk in _iterate_and_close_provider_stream(
            stream,
            finish_seen=_finish_seen,
        ):
            if _get_field(chunk, "usage", None) is not None:
                candidate_usage = _usage_payload(chunk)
                if candidate_usage is not None:
                    stream_usage_payload = candidate_usage
            choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
            if choice is None:
                continue
            candidate_finish_reason = getattr(choice, "finish_reason", None)
            if isinstance(candidate_finish_reason, str) and candidate_finish_reason.strip():
                finish_reason = candidate_finish_reason
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            delta_reasoning_content = getattr(delta, "reasoning_content", None)
            if isinstance(delta_reasoning_content, str) and delta_reasoning_content:
                reasoning_content_parts.append(delta_reasoning_content)
            has_reasoning_delta = any(
                bool(getattr(delta, field_name, None))
                for field_name in ("reasoning_content", "reasoning", "thinking")
            )
            if has_reasoning_delta and not emitted_reasoning:
                emitted_reasoning = True
                if self._emit_activity:
                    yield {"type": "provider_activity", "phase": "model_reasoning"}
            piece = getattr(delta, "content", None)
            if isinstance(piece, str) and piece:
                visible_piece = trimmer.push(reasoning_filter.push(piece))
                if visible_piece:
                    text_buffer += visible_piece
                    yield {"type": "delta", "delta": visible_piece}
                elif not emitted_reasoning and ("<think" in piece.lower() or not trimmer.emitted_visible):
                    emitted_reasoning = True
                    if self._emit_activity:
                        yield {"type": "provider_activity", "phase": "model_reasoning"}
            for delta_call in getattr(delta, "tool_calls", []) or []:
                index = int(getattr(delta_call, "index", 0) or 0)
                slot = tool_call_state.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if getattr(delta_call, "id", None):
                    slot["id"] = str(delta_call.id)
                fn = getattr(delta_call, "function", None)
                if fn is None:
                    continue
                if getattr(fn, "name", None):
                    slot["name"] = str(fn.name)
                    if index not in emitted_tool_drafts:
                        emitted_tool_drafts.add(index)
                        if self._emit_activity:
                            yield {
                                "type": "provider_activity",
                                "phase": "tool_drafting",
                                "name": slot["name"],
                            }
                if getattr(fn, "arguments", None):
                    slot["arguments"] += str(fn.arguments)

        tail = trimmer.push(reasoning_filter.flush())
        if tail:
            text_buffer += tail
            yield {"type": "delta", "delta": tail}

        tool_calls = [
            {"id": item["id"] or item["name"], "name": item["name"], "arguments": item["arguments"]}
            for item in tool_call_state.values()
            if item["name"]
        ]
        if not text_buffer.strip() and not tool_calls:
            json_fallback = extract_non_sse_json_stream_payload(stream)
            if json_fallback is not None:
                parsed_json = _parse_openai_chat_response(json_fallback)
                json_text = trimmer.push(str(parsed_json.get("content") or ""))
                json_tools = list(parsed_json.get("tool_calls") or [])
                if json_text.strip() or json_tools:
                    if json_text:
                        yield {"type": "delta", "delta": json_text}
                    yield {
                        "type": "final",
                        "content": json_text,
                        "tool_calls": json_tools,
                        "stop_reason": str(
                            parsed_json.get("stop_reason")
                            or ("tool_calls" if json_tools else "stop")
                        ),
                        **(
                            {"usage": parsed_json["usage"]}
                            if isinstance(parsed_json.get("usage"), dict)
                            else {}
                        ),
                    }
                    return
        if not text_buffer.strip() and not tool_calls:
            retry_result = await self._openai_visible_retry_result(
                client,
                messages=formatted,
                tools=tools,
                model=chosen_model,
            )
            if retry_result is not None:
                retry_text = str(retry_result.get("content") or "")
                retry_tool_calls = list(retry_result.get("tool_calls") or [])
                if retry_text:
                    yield {"type": "delta", "delta": retry_text}
                yield {
                    "type": "final",
                    "content": retry_text,
                    "tool_calls": retry_tool_calls,
                    "stop_reason": "tool_calls" if retry_tool_calls else "stop",
                    **(
                        {"usage": retry_result["usage"]}
                        if isinstance(retry_result.get("usage"), dict)
                        else {}
                    ),
                }
                return
        if not text_buffer.strip() and (not tool_calls or _finish_reason_is_truncated(finish_reason)):
            # Neither learner-visible text nor usable tool calls escaped this
            # response. Retry the same step without replaying earlier tools.
            budget_result = await self._openai_truncated_budget_retry(
                client,
                messages=formatted,
                tools=tools,
                model=chosen_model,
            )
            if budget_result is not None:
                budget_text = str(budget_result.get("content") or "")
                budget_tool_calls = list(budget_result.get("tool_calls") or [])
                if budget_text:
                    yield {"type": "delta", "delta": budget_text}
                yield {
                    "type": "final",
                    "content": budget_text,
                    "tool_calls": budget_tool_calls,
                    "stop_reason": (
                        "tool_calls"
                        if budget_tool_calls
                        else str(budget_result.get("stop_reason") or "stop")
                    ),
                    **(
                        {"usage": budget_result["usage"]}
                        if isinstance(budget_result.get("usage"), dict)
                        else {}
                    ),
                    **(
                        {"provider_reasoning": budget_result["provider_reasoning"]}
                        if isinstance(budget_result.get("provider_reasoning"), dict)
                        else {}
                    ),
                }
                return
        normalized = self._validated_result(
            {
                "choices": [
                    {
                        "message": {
                            "content": text_buffer,
                            "tool_calls": [
                                {
                                    "id": item["id"],
                                    "function": {
                                        "name": item["name"],
                                        "arguments": item["arguments"],
                                    },
                                }
                                for item in tool_calls
                            ],
                        },
                        "finish_reason": finish_reason,
                    }
                ]
            },
            {"content": text_buffer, "tool_calls": tool_calls},
            protocol="openai_chat_completions",
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
        if stream_usage_payload is not None:
            final_event["usage"] = stream_usage_payload
        if reasoning_content_parts:
            final_event["provider_reasoning"] = {
                "openai_reasoning_content": "".join(reasoning_content_parts)
            }
        yield final_event

    # -- Anthropic Messages -------------------------------------------------

    async def _anthropic_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        api_key, model = self._anthropic_credentials()
        payload = _format_anthropic_payload(
            messages,
            _format_anthropic_tools(tools),
            model=model,
            max_tokens=self._max_tokens,
            attachments=self._attachments,
            vision_enabled=self._vision_enabled,
        )
        payload = self._apply_anthropic_request_defaults(payload)
        payload = self._apply_nonofficial_anthropic_thinking_default(payload)
        payload = self._flatten_raw_http_thinking(payload)
        response = await self._anthropic_post_payload(payload, api_key)
        if response.status_code >= 400:
            fallback_result = await self._anthropic_protocol_mismatch_fallback(
                messages,
                tools,
                status_code=response.status_code,
                body=response.text,
            )
            if fallback_result is not None:
                return fallback_result
            raise self._http_failure(status_code=response.status_code, body=response.text)
        try:
            body = response.json()
            parsed = _parse_anthropic_response(body)
        except Exception as exc:  # noqa: BLE001 - compatibility fallback is best-effort
            fallback_result = await self._anthropic_compatible_openai_fallback(messages, tools)
            if fallback_result is not None:
                return fallback_result
            raise RuntimeError(
                f"Malformed response: {_malformed_provider_html_shell_detail()}"
            ) from exc
        parsed["content"] = _visible_model_text(parsed.get("content"))
        if _looks_like_provider_html_shell(str(parsed.get("content") or "")):
            fallback_result = await self._anthropic_compatible_openai_fallback(messages, tools)
            if fallback_result is not None:
                return fallback_result
            raise RuntimeError(f"Malformed response: {_malformed_provider_html_shell_detail()}")
        if not str(parsed.get("content") or "").strip() and not parsed.get("tool_calls"):
            retry_result = await self._anthropic_retry_visible_result(payload, api_key)
            if retry_result is not None:
                return retry_result
            fallback_result = await self._anthropic_compatible_openai_fallback(messages, tools)
            if fallback_result is not None:
                return fallback_result
        try:
            return self._validated_result(body, parsed)
        except ProviderRuntimeResponseError as exc:
            if exc.provider_error_category != "truncated_or_empty":
                raise
            retry_result = await self._anthropic_truncated_response_retry(payload, api_key)
            if retry_result is not None:
                return retry_result
            fallback_result = await self._anthropic_compatible_openai_fallback(messages, tools)
            if fallback_result is not None:
                return fallback_result
            raise

    async def _anthropic_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        api_key, model = self._anthropic_credentials()
        payload = _format_anthropic_payload(
            messages,
            _format_anthropic_tools(tools),
            model=model,
            max_tokens=self._max_tokens,
            attachments=self._attachments,
            vision_enabled=self._vision_enabled,
            stream=True,
        )
        payload = self._apply_anthropic_request_defaults(payload)
        payload = self._apply_nonofficial_anthropic_thinking_default(payload)
        payload = self._flatten_raw_http_thinking(payload)
        async with self._async_http_client() as client:
            async with client.stream(
                "POST",
                f"{self._anthropic_base_url}/v1/messages",
                json=payload,
                headers=self._anthropic_headers(api_key),
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    body_text = body.decode("utf-8", errors="replace")
                    fallback_emitted = False
                    async for event in self._anthropic_protocol_mismatch_stream_fallback(
                        messages,
                        tools,
                        status_code=response.status_code,
                        body=body_text,
                    ):
                        fallback_emitted = True
                        yield event
                    if fallback_emitted:
                        return
                    raise self._http_failure(
                        status_code=response.status_code,
                        body=body_text,
                    )
                text_buffer = ""
                reasoning_filter = ReasoningBlockFilter()
                trimmer = _StreamWhitespaceTrimmer()
                emitted_reasoning = False
                tool_block_states: dict[int, dict[str, Any]] = {}
                thinking_block_states: dict[int, dict[str, Any]] = {}
                anthropic_usage_raw: dict[str, Any] = {}
                stop_reason: str | None = None

                def _stop_seen() -> bool:
                    return bool(stop_reason)

                async for raw_line in _iterate_provider_stream_with_cancellation(
                    response.aiter_lines(),
                    None,
                    idle_timeout=STREAM_IDLE_TIMEOUT_SECONDS,
                    finish_seen=_stop_seen,
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
                    event_type = str(event.get("type") or "")
                    if event_type == "message_start":
                        msg_obj = event.get("message")
                        msg_usage = msg_obj.get("usage") if isinstance(msg_obj, dict) else None
                        if isinstance(msg_usage, dict):
                            anthropic_usage_raw.update(msg_usage)
                    elif event_type == "content_block_start":
                        block = event.get("content_block") or {}
                        block_type = str(block.get("type") or "")
                        block_index = int(event.get("index") or 0)
                        if block_type == "thinking":
                            thinking_block_states[block_index] = {
                                "type": "thinking",
                                "thinking": str(block.get("thinking") or ""),
                                **(
                                    {"signature": str(block["signature"])}
                                    if isinstance(block.get("signature"), str) and block["signature"]
                                    else {}
                                ),
                            }
                            if not emitted_reasoning:
                                emitted_reasoning = True
                                if self._emit_activity:
                                    yield {"type": "provider_activity", "phase": "model_reasoning"}
                        elif block_type == "redacted_thinking":
                            thinking_block_states[block_index] = {
                                "type": "redacted_thinking",
                                **(
                                    {"data": str(block["data"])}
                                    if isinstance(block.get("data"), str)
                                    else {}
                                ),
                            }
                        if block_type == "tool_use":
                            block_name = str(block.get("name") or "")
                            tool_block_states[block_index] = {
                                "id": str(block.get("id") or ""),
                                "name": block_name,
                                "arguments": "",
                            }
                            if block_name and self._emit_activity:
                                yield {
                                    "type": "provider_activity",
                                    "phase": "tool_drafting",
                                    "name": block_name,
                                }
                    elif event_type == "content_block_delta":
                        delta = event.get("delta") or {}
                        delta_kind = str(delta.get("type") or "")
                        block_index = int(event.get("index") or 0)
                        if delta_kind == "thinking_delta":
                            slot = thinking_block_states.setdefault(
                                block_index, {"type": "thinking", "thinking": ""}
                            )
                            slot["thinking"] = str(slot.get("thinking") or "") + str(
                                delta.get("thinking") or ""
                            )
                        elif delta_kind == "signature_delta":
                            slot = thinking_block_states.setdefault(
                                block_index, {"type": "thinking", "thinking": ""}
                            )
                            slot["signature"] = str(slot.get("signature") or "") + str(
                                delta.get("signature") or ""
                            )
                        elif delta_kind == "text_delta":
                            piece = str(delta.get("text") or "")
                            if piece:
                                visible_piece = trimmer.push(
                                    reasoning_filter.push(piece)
                                )
                                if visible_piece:
                                    text_buffer += visible_piece
                                    yield {"type": "delta", "delta": visible_piece}
                        elif delta_kind == "input_json_delta":
                            slot = tool_block_states.setdefault(
                                block_index,
                                {"id": "", "name": "", "arguments": ""},
                            )
                            slot["arguments"] += str(delta.get("partial_json") or "")
                    elif event_type == "message_delta":
                        delta = event.get("delta") or {}
                        candidate_stop_reason = delta.get("stop_reason")
                        if isinstance(candidate_stop_reason, str) and candidate_stop_reason.strip():
                            stop_reason = candidate_stop_reason
                        delta_usage = event.get("usage")
                        if isinstance(delta_usage, dict):
                            anthropic_usage_raw.update(delta_usage)
                    elif event_type == "message_stop":
                        break
                tail = trimmer.push(reasoning_filter.flush())
                if tail:
                    text_buffer += tail
                    yield {"type": "delta", "delta": tail}
        tool_calls = [
            {
                "id": item["id"] or item["name"],
                "name": item["name"],
                "arguments": item["arguments"],
            }
            for item in tool_block_states.values()
            if item["name"]
        ]
        if not text_buffer.strip() and not tool_calls:
            retry_result = await self._anthropic_retry_visible_result(payload, api_key)
            if retry_result is not None:
                retry_text = str(retry_result.get("content") or "")
                if retry_text:
                    yield {"type": "delta", "delta": retry_text}
                yield {
                    "type": "final",
                    "content": retry_text,
                    "tool_calls": list(retry_result.get("tool_calls") or []),
                    "stop_reason": (
                        "tool_calls" if list(retry_result.get("tool_calls") or []) else "stop"
                    ),
                    **(
                        {"usage": retry_result["usage"]}
                        if isinstance(retry_result.get("usage"), dict)
                        else {}
                    ),
                }
                return
            fallback_emitted = False
            async for event in self._anthropic_compatible_openai_stream_fallback(messages, tools):
                fallback_emitted = True
                yield event
            if fallback_emitted:
                return
        if _looks_like_provider_html_shell(text_buffer):
            fallback_emitted = False
            async for event in self._anthropic_compatible_openai_stream_fallback(messages, tools):
                fallback_emitted = True
                yield event
            if fallback_emitted:
                return
            raise RuntimeError(f"Malformed response: {_malformed_provider_html_shell_detail()}")
        normalized = self._validated_result(
            {
                "content": [
                    *([{"type": "text", "text": text_buffer}] if text_buffer else []),
                    *[
                        {
                            "type": "tool_use",
                            "id": item["id"],
                            "name": item["name"],
                            "input": item["arguments"],
                        }
                        for item in tool_calls
                    ],
                ],
                "stop_reason": stop_reason or ("tool_use" if tool_calls else "end_turn"),
            },
            {"content": text_buffer, "tool_calls": tool_calls},
        )
        anthropic_thinking_blocks = [
            block for _, block in sorted(thinking_block_states.items())
        ]
        final_event: dict[str, Any] = {
            "type": "final",
            "content": normalized["content"],
            "tool_calls": tool_calls,
            "stop_reason": (
                "tool_calls"
                if tool_calls
                else ("length" if _finish_reason_is_truncated(stop_reason) else "stop")
            ),
        }
        usage_payload = _usage_payload({"usage": anthropic_usage_raw}) if anthropic_usage_raw else None
        if usage_payload is not None:
            final_event["usage"] = usage_payload
        if anthropic_thinking_blocks:
            final_event["provider_reasoning"] = {"anthropic_blocks": anthropic_thinking_blocks}
        yield final_event

    # -- helpers ------------------------------------------------------------

    def _flatten_raw_http_thinking(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _flatten_minimax_thinking_for_raw_http(
            payload,
            getattr(self._provider_service, "_config", None),
        )

    async def _anthropic_post_payload(
        self,
        payload: dict[str, Any],
        api_key: str,
    ) -> _real_httpx.Response:
        payload = self._flatten_raw_http_thinking(payload)
        async with self._async_http_client() as client:
            return await client.post(
                f"{self._anthropic_base_url}/v1/messages",
                json=payload,
                headers=self._anthropic_headers(api_key),
            )

    async def _anthropic_compatible_openai_fallback(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any] | None:
        if _base_url_is_official_anthropic(self._base_url):
            return None
        try:
            return await self._openai_chat_call(
                messages,
                tools,
                compatibility_thinking_disabled=self._should_default_compatibility_thinking(),
            )
        except Exception as exc:  # noqa: BLE001 - compatibility fallback is best-effort
            logger.warning(
                "anthropic_compatible_openai_fallback_failed",
                extra={
                    "detail": safe_provider_diagnostic(
                        exc,
                        api_key=self._api_key_for_diagnostics(),
                    )
                },
            )
            return None

    async def _anthropic_compatible_openai_stream_fallback(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[dict[str, Any]]:
        if _base_url_is_official_anthropic(self._base_url):
            return
        async for event in self._openai_chat_stream(
            messages,
            tools,
            compatibility_thinking_disabled=self._should_default_compatibility_thinking(),
        ):
            yield event

    async def _anthropic_protocol_mismatch_fallback(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        status_code: int,
        body: str,
    ) -> dict[str, Any] | None:
        if not _anthropic_response_indicates_protocol_mismatch(status_code, body):
            return None
        logger.info(
            "anthropic_messages_protocol_mismatch_falling_back",
            extra={"status_code": status_code},
        )
        return await self._anthropic_compatible_openai_fallback(messages, tools)

    async def _anthropic_protocol_mismatch_stream_fallback(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        status_code: int,
        body: str,
    ) -> AsyncIterator[dict[str, Any]]:
        if not _anthropic_response_indicates_protocol_mismatch(status_code, body):
            return
        logger.info(
            "anthropic_messages_protocol_mismatch_falling_back",
            extra={"status_code": status_code},
        )
        async for event in self._anthropic_compatible_openai_stream_fallback(messages, tools):
            yield event

    async def _anthropic_retry_visible_result(
        self,
        payload: dict[str, Any],
        api_key: str,
    ) -> dict[str, Any] | None:
        retry_payload = _anthropic_visible_retry_payload(payload)
        for _attempt in range(ANTHROPIC_VISIBLE_REPLY_RETRY_ATTEMPTS):
            try:
                response = await self._anthropic_post_payload(retry_payload, api_key)
                if response.status_code >= 400:
                    logger.warning(
                        "anthropic_visible_retry_failed",
                        extra={"status_code": response.status_code},
                    )
                    return None
                body = response.json()
                parsed = _parse_anthropic_response(body)
            except Exception as exc:  # noqa: BLE001 - retry is best-effort only
                logger.warning(
                    "anthropic_visible_retry_exception",
                    extra={
                        "detail": safe_provider_diagnostic(
                            exc,
                            api_key=self._api_key_for_diagnostics(),
                        )
                    },
                )
                return None
            parsed["content"] = _visible_model_text(parsed.get("content"))
            try:
                return self._validated_result(body, parsed)
            except ProviderRuntimeResponseError:
                continue
        return None

    async def _anthropic_truncated_response_retry(
        self,
        payload: dict[str, Any],
        api_key: str,
    ) -> dict[str, Any] | None:
        retry_payload = _anthropic_visible_retry_payload(payload)
        try:
            response = await self._anthropic_post_payload(retry_payload, api_key)
            if response.status_code >= 400:
                logger.info(
                    "anthropic_truncated_response_retry_rejected",
                    extra={"status_code": response.status_code},
                )
                return None
            body = response.json()
            parsed = _parse_anthropic_response(body)
            parsed["content"] = _visible_model_text(parsed.get("content"))
            return self._validated_result(body, parsed)
        except Exception as exc:  # noqa: BLE001 - recovery retry is best-effort
            logger.warning(
                "anthropic_truncated_response_retry_failed",
                extra={
                    "detail": safe_provider_diagnostic(
                        exc,
                        api_key=self._api_key_for_diagnostics(),
                    )
                },
            )
            return None

    def _should_default_compatibility_thinking(self) -> bool:
        return not _base_url_is_official_anthropic(self._base_url)

    @staticmethod
    def _thinking_record_enabled(value: Any) -> bool:
        """A configured thinking record only counts as "on" when it says so —
        an explicit {type: 'disabled'} marker must not block the disabled
        injection it is itself producing."""
        if not isinstance(value, dict):
            return False
        marker = value.get("type", value.get("mode"))
        if isinstance(marker, str) and marker.strip().lower() == "enabled":
            return True
        if value.get("enabled") is True:
            return True
        budget = value.get("budget_tokens", value.get("budgetTokens"))
        return isinstance(budget, int) and not isinstance(budget, bool) and budget > 0

    @classmethod
    def _configured_thinking_explicitly_on(cls, defaults: dict[str, Any]) -> bool:
        """Detect a user-chosen thinking-ON intent in any supported wire shape —
        flat reasoning effort, anthropic `thinking`, budgets, or gemini
        generationConfig.thinkingConfig — so compatibility defaults never
        contradict it with an injected disabled flag."""
        effort = defaults.get("reasoning_effort", defaults.get("reasoningEffort"))
        if isinstance(effort, str) and effort.strip().lower() not in {"", "auto", "off", "none", "disabled"}:
            return True
        reasoning = defaults.get("reasoning")
        if isinstance(reasoning, dict):
            nested_effort = reasoning.get("effort")
            if isinstance(nested_effort, str) and nested_effort.strip().lower() not in {"", "auto", "off", "none", "disabled"}:
                return True
        if cls._thinking_record_enabled(defaults.get("thinking")):
            return True
        extra_body = defaults.get("extra_body")
        if isinstance(extra_body, dict) and cls._thinking_record_enabled(extra_body.get("thinking")):
            return True
        budget = defaults.get("thinking_budget", defaults.get("thinkingBudget"))
        if isinstance(budget, int) and not isinstance(budget, bool) and budget > 0:
            return True
        generation = defaults.get("generationConfig", defaults.get("generation_config"))
        if isinstance(generation, dict):
            gemini = generation.get("thinkingConfig", generation.get("thinking_config"))
            if isinstance(gemini, dict):
                if gemini.get("includeThoughts") is True or gemini.get("include_thoughts") is True:
                    return True
                gemini_budget = gemini.get("thinkingBudget", gemini.get("thinking_budget"))
                if isinstance(gemini_budget, int) and not isinstance(gemini_budget, bool) and gemini_budget > 0:
                    return True
        return False

    def _apply_nonofficial_anthropic_thinking_default(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        configured_defaults = self._request_defaults()
        configured_extra_body = configured_defaults.get("extra_body")
        explicit_thinking_budget = configured_defaults.get(
            "thinking_budget",
            configured_defaults.get("thinkingBudget"),
        )
        config = getattr(self._provider_service, "_config", None)
        if (
            not self._should_default_compatibility_thinking()
            or "thinking" in payload
            or (isinstance(configured_extra_body, dict) and "thinking" in configured_extra_body)
            or (isinstance(explicit_thinking_budget, int) and explicit_thinking_budget > 0)
            or self._configured_thinking_explicitly_on(configured_defaults)
        ):
            return payload
        # Respect a gateway-learned "enabled" policy (mandatory-thinking models),
        # while keeping third-party Anthropic-compatible gateways defaulting to
        # disabled when the user did not configure thinking explicitly.
        if learned_policy(config) == "enabled":
            return payload
        return {**payload, "thinking": {"type": "disabled"}}

    def _apply_compatibility_thinking_disabled(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        existing_extra_body = payload.get("extra_body")
        configured_defaults = self._request_defaults()
        configured_extra_body = configured_defaults.get("extra_body")
        # An explicit thinking-on choice in any wire shape means the user
        # turned thinking on — injecting a disabled flag would contradict it.
        if (
            not self._should_default_compatibility_thinking()
            or self._configured_thinking_explicitly_on(configured_defaults)
            or (isinstance(existing_extra_body, dict) and "thinking" in existing_extra_body)
            or (isinstance(configured_extra_body, dict) and "thinking" in configured_extra_body)
        ):
            return payload
        return {
            **payload,
            "extra_body": self._merge_record(
                dict(existing_extra_body) if isinstance(existing_extra_body, dict) else {},
                {"thinking": {"type": "disabled"}},
            ),
        }

    def _extra_headers(self) -> dict[str, str]:
        defaults = self._request_defaults()
        raw = defaults.get("extra_headers") or defaults.get("extraHeaders")
        if not isinstance(raw, dict):
            return {}
        return {
            str(k).strip(): str(v)
            for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, str) and k.strip()
        }

    def _anthropic_credentials(self) -> tuple[str, str]:
        api_key = getattr(self._provider_service, "_api_key", None)
        config = getattr(self._provider_service, "_config", None)
        if not isinstance(api_key, str) or not api_key.strip():
            if _allows_keyless_local_provider(config):
                api_key = "local-no-key"
            else:
                raise RuntimeError("Anthropic provider requires an API key.")
        model = getattr(config, "model", None) or "claude-3-5-sonnet-latest"
        return api_key.strip(), str(model).strip()

    def _anthropic_headers(self, api_key: str) -> dict[str, str]:
        return {
            **self._extra_headers(),
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

    def _gemini_headers(self, api_key: str) -> dict[str, str]:
        return {
            **self._extra_headers(),
            "x-goog-api-key": api_key,
            "content-type": "application/json",
        }

    def _request_defaults(self) -> dict[str, Any]:
        getter = getattr(self._provider_service, "_provider_request_defaults", None)
        if callable(getter):
            defaults = getter()
            return dict(defaults) if isinstance(defaults, dict) else {}
        config = getattr(self._provider_service, "_config", None)
        defaults = getattr(config, "request_defaults", None)
        return dict(defaults) if isinstance(defaults, dict) else {}

    @staticmethod
    def _merge_record(base: dict[str, Any], override: Any) -> dict[str, Any]:
        if not isinstance(override, dict):
            return base
        merged = dict(base)
        for key, value in override.items():
            if value is None:
                continue
            current = merged.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                merged[key] = AgentBindingProtocolsMixin._merge_record(current, value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _first_default(defaults: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in defaults and defaults[key] is not None:
                return defaults[key]
        return None

    @staticmethod
    def _usable_default(value: Any) -> Any:
        if isinstance(value, str) and value.strip().lower() in {"", "auto"}:
            return None
        return value

    def _apply_openai_responses_request_defaults(self, payload: dict[str, Any]) -> dict[str, Any]:
        defaults = self._request_defaults()
        merged = dict(payload)
        extra_headers = self._extra_headers()
        if extra_headers:
            merged["extra_headers"] = extra_headers
        if defaults:
            if isinstance(defaults.get("extra_body"), dict):
                merged["extra_body"] = self._merge_record(
                    dict(merged.get("extra_body") or {}),
                    defaults["extra_body"],
                )
            if "store" in defaults:
                merged["store"] = defaults["store"]
            if isinstance(defaults.get("metadata"), dict):
                merged["metadata"] = self._merge_record(
                    dict(merged.get("metadata") or {}),
                    defaults["metadata"],
                )
            for output_key, aliases in {
                "service_tier": ("service_tier", "serviceTier"),
                "temperature": ("temperature",),
                "max_output_tokens": ("max_output_tokens", "maxOutputTokens", "maxTokens"),
            }.items():
                raw_value = self._first_default(defaults, *aliases)
                value = raw_value if output_key == "service_tier" else self._usable_default(raw_value)
                if value is not None:
                    merged[output_key] = value
            from .provider.thinking import apply_reasoning_effort_to_payload

            reasoning_effort = self._usable_default(
                self._first_default(defaults, "reasoning_effort", "reasoningEffort")
            )
            if isinstance(reasoning_effort, str):
                merged = apply_reasoning_effort_to_payload(
                    merged, reasoning_effort, "openai_responses"
                )
        explicit_temperature = (
            self._usable_default(self._first_default(defaults, "temperature"))
            if defaults
            else None
        )
        config = getattr(self._provider_service, "_config", None)
        if explicit_temperature is None and (
            (isinstance(merged.get("reasoning"), dict) and merged["reasoning"])
            or _model_looks_reasoning_first(config)
        ):
            merged.pop("temperature", None)
        return merged

    def _apply_anthropic_request_defaults(self, payload: dict[str, Any]) -> dict[str, Any]:
        defaults = self._request_defaults()
        if not defaults:
            return payload
        merged = dict(payload)
        if isinstance(defaults.get("extra_body"), dict):
            merged = self._merge_record(merged, defaults["extra_body"])
        direct_thinking = defaults.get("thinking")
        if isinstance(direct_thinking, dict):
            merged["thinking"] = self._merge_record(
                dict(merged.get("thinking") or {}), direct_thinking
            )
        for output_key, aliases in {
            "max_tokens": ("max_tokens", "maxTokens", "maxOutputTokens"),
            "temperature": ("temperature",),
            "top_p": ("top_p", "topP"),
            "top_k": ("top_k", "topK"),
            "stop_sequences": ("stop_sequences", "stopSequences", "stop"),
        }.items():
            value = self._usable_default(self._first_default(defaults, *aliases))
            if value is not None:
                merged[output_key] = value
        from .provider.thinking import apply_reasoning_effort_to_payload

        thinking_budget = self._first_default(defaults, "thinking_budget", "thinkingBudget")
        reasoning_effort = self._usable_default(
            self._first_default(defaults, "reasoning_effort", "reasoningEffort")
        )
        explicit_wire_thinking = isinstance(defaults.get("thinking"), dict) or (
            isinstance(defaults.get("extra_body"), dict)
            and isinstance(defaults["extra_body"].get("thinking"), dict)
        )
        if not explicit_wire_thinking and isinstance(thinking_budget, int) and thinking_budget > 0:
            merged["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        elif not explicit_wire_thinking and isinstance(thinking_budget, str) and thinking_budget.strip().lower() == "disabled":
            merged.pop("thinking", None)
        elif not explicit_wire_thinking and isinstance(reasoning_effort, str):
            merged = apply_reasoning_effort_to_payload(
                merged, reasoning_effort, "anthropic_messages"
            )
        merged_thinking = merged.get("thinking")
        if isinstance(merged_thinking, dict) and merged_thinking.get("type") == "enabled":
            # Anthropic Messages rejects temperature != 1 and top_k when extended thinking is enabled.
            temp = merged.get("temperature")
            if temp is not None and temp != 1:
                merged.pop("temperature", None)
            merged.pop("top_k", None)
            top_p = merged.get("top_p")
            if isinstance(top_p, (int, float)) and top_p < 0.95:
                merged.pop("top_p", None)
            budget_tokens = merged_thinking.get("budget_tokens", merged_thinking.get("budgetTokens"))
            merged_max_tokens = merged.get("max_tokens")
            if (
                isinstance(budget_tokens, int)
                and not isinstance(budget_tokens, bool)
                and isinstance(merged_max_tokens, int)
                and not isinstance(merged_max_tokens, bool)
                and merged_max_tokens <= budget_tokens
            ):
                config = getattr(self._provider_service, "_config", None)
                configured_cap = None
                if config is not None:
                    limits_fn = getattr(self._provider_service, "_configured_token_limits", None)
                    if callable(limits_fn):
                        limits_result = limits_fn(config)
                        if isinstance(limits_result, tuple) and len(limits_result) >= 2:
                            configured_cap = limits_result[1]
                if isinstance(configured_cap, int) and configured_cap > 0:
                    merged = clamp_wire_thinking_budget(merged, configured_cap)
                else:
                    # Anthropic requires max_tokens > budget_tokens; without a smaller
                    # explicit output cap, lift max_tokens to keep visible headroom.
                    merged["max_tokens"] = budget_tokens + 1024
        config = getattr(self._provider_service, "_config", None)
        base_url = str(getattr(config, "base_url", "") or "").strip()
        is_official_anthropic = (urlsplit(base_url).hostname or "").lower().endswith("anthropic.com")
        return self._flatten_raw_http_thinking(
            clamp_anthropic_thinking_budget(
                merged,
                enforce_min_budget=is_official_anthropic,
            )
        )

    def _apply_gemini_request_defaults(self, payload: dict[str, Any]) -> dict[str, Any]:
        defaults = self._request_defaults()
        if not defaults:
            return payload
        merged = dict(payload)
        gemini_allowed_root = {"safetySettings", "cachedContent", "labels", "toolConfig", "thinkingConfig"}
        if isinstance(defaults.get("extra_body"), dict):
            gemini_extra = {
                k: v for k, v in defaults["extra_body"].items() if k in gemini_allowed_root
            }
            if gemini_extra:
                merged = self._merge_record(merged, gemini_extra)
        generation_config = dict(merged.get("generationConfig") or {})
        if isinstance(defaults.get("generationConfig"), dict):
            generation_config = self._merge_record(generation_config, defaults["generationConfig"])
        for output_key, aliases in {
            "maxOutputTokens": ("maxOutputTokens", "maxTokens", "max_output_tokens"),
            "temperature": ("temperature",),
            "topP": ("topP", "top_p"),
            "topK": ("topK", "top_k"),
            "candidateCount": ("candidateCount", "candidate_count"),
            "stopSequences": ("stopSequences", "stop_sequences", "stop"),
        }.items():
            value = self._usable_default(self._first_default(defaults, *aliases))
            if value is not None:
                generation_config[output_key] = value
        merged["generationConfig"] = generation_config
        reasoning_effort = self._usable_default(
            self._first_default(defaults, "reasoning_effort", "reasoningEffort")
        )
        has_explicit_gemini_thinking = isinstance(generation_config.get("thinkingConfig"), dict)
        if not has_explicit_gemini_thinking and isinstance(reasoning_effort, str):
            from .provider.thinking import apply_reasoning_effort_to_payload

            merged = apply_reasoning_effort_to_payload(
                merged, reasoning_effort, "gemini_generate_content"
            )
        return clamp_wire_thinking_budget(merged)

    def _gemini_credentials(self) -> tuple[str, str]:
        api_key = getattr(self._provider_service, "_api_key", None)
        config = getattr(self._provider_service, "_config", None)
        if not isinstance(api_key, str) or not api_key.strip():
            if _allows_keyless_local_provider(config):
                api_key = "local-no-key"
            else:
                raise RuntimeError("Gemini GenerateContent provider requires an API key.")
        model = getattr(config, "model", None) or "gemini-2.0-flash"
        return api_key.strip(), str(model).strip()

    def _gemini_endpoint(self, model: str, *, stream: bool = False) -> str:
        config = getattr(self._provider_service, "_config", None)
        url = getattr(config, "base_url", None)
        base_url = str(url).strip().rstrip("/") if isinstance(url, str) and url.strip() else ""
        if not base_url:
            base_url = "https://generativelanguage.googleapis.com/v1beta"
        if base_url.endswith(":generateContent"):
            if stream:
                return f"{base_url[:-len(':generateContent')]}:streamGenerateContent?alt=sse"
            return base_url
        if base_url.endswith(":streamGenerateContent"):
            if stream:
                return base_url
            return f"{base_url[:-len(':streamGenerateContent')]}:generateContent"
        if "/models/" in base_url:
            suffix = "streamGenerateContent?alt=sse" if stream else "generateContent"
            return f"{base_url}:{suffix}"
        if not (base_url.endswith("/v1") or base_url.endswith("/v1beta")):
            base_url = f"{base_url}/v1beta"
        escaped_model = quote(model, safe="/-_.")
        suffix = "streamGenerateContent?alt=sse" if stream else "generateContent"
        return f"{base_url}/models/{escaped_model}:{suffix}"

    def _infer_vision_enabled(self) -> bool:
        config = getattr(self._provider_service, "_config", None)
        capabilities = getattr(config, "capabilities", None)
        declared = bool(getattr(capabilities, "vision", False))
        truth = getattr(self._provider_service, "_capability_truth", {})
        verified = truth.get("vision") == "verified"
        if not verified:
            result = getattr(self._provider_service, "_last_capability_result", None)
            evidence = getattr(result, "capability_evidence", None) or []
            verified = any(
                getattr(item, "name", "") == "vision"
                and getattr(item, "state", "") == "verified"
                and getattr(item, "observed", False) is True
                for item in evidence
            )
        return attachments_supported(self._protocol, declared and verified)

    def _infer_anthropic_base_url(self) -> str | None:
        config = getattr(self._provider_service, "_config", None)
        url = getattr(config, "base_url", None)
        if isinstance(url, str) and url.strip().startswith("http"):
            stripped = url.strip().rstrip("/")
            if stripped.lower().endswith("/v1"):
                stripped = stripped[: -len("/v1")]
            return stripped
        return None
