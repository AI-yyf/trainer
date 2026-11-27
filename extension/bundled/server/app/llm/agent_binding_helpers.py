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
from collections.abc import AsyncIterator, Callable
from inspect import isawaitable
from typing import Any

from .agent_loop import CoachAgentLoop
from .harness import extract_provider_usage
from .provider.streaming import (
    STREAM_IDLE_TIMEOUT_SECONDS,
    _iterate_provider_stream_with_cancellation,
)
from .provider_protocols import (
    _finish_reason_is_truncated,
)
from .provider_service import (
    _visible_model_text,
)
from .vision_payload import openai_responses_input_image_parts

logger = logging.getLogger(__name__)

logger = logging.getLogger("trainer.llm.agent_binding")


async def _iterate_and_close_provider_stream(
    stream: Any,
    *,
    finish_seen: Callable[[], bool] | None = None,
) -> AsyncIterator[Any]:
    """Consume a provider stream with post-finish drain bounds and release its HTTP response."""
    try:
        async for chunk in _iterate_provider_stream_with_cancellation(
            stream,
            None,
            idle_timeout=STREAM_IDLE_TIMEOUT_SECONDS,
            finish_seen=finish_seen,
        ):
            yield chunk
    finally:
        close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
        if close is not None:
            result = close()
            if isawaitable(result):
                await result

ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_DEFAULT_MAX_TOKENS = 1024
TRANSPORT_TIMEOUT_MARGIN_SECONDS = 5.0
# The agent loop owns cancellation; native transport timeouts must not preempt it.
DEFAULT_REQUEST_TIMEOUT_SECONDS = (
    CoachAgentLoop.MAX_STEP_TIMEOUT_SECONDS + TRANSPORT_TIMEOUT_MARGIN_SECONDS
)
ANTHROPIC_VISIBLE_REPLY_RETRY_ATTEMPTS = 2
ANTHROPIC_VISIBLE_REPLY_RETRY_HINT = (
    "Return at least one visible coaching sentence outside any <think>...</think> block. "
    "Do not leave the visible reply empty."
)
ANTHROPIC_PROTOCOL_MISMATCH_STATUS_CODES = frozenset({404, 405, 415, 422})
ANTHROPIC_AUTH_HEADER_MARKERS = (
    "authorization",
    "authorization header",
    "bearer",
    "bearer token",
    "bearer authentication",
    "x-api-key",
    "authentication scheme",
    "anthropic-version",
    "anthropic version",
)
ANTHROPIC_AUTH_MISMATCH_MARKERS = (
    "expected",
    "missing",
    "must use",
    "required",
    "requires",
    "use bearer",
    "unsupported",
)
OPENAI_VISIBLE_REPLY_RETRY_ATTEMPTS = 2
#: Ceiling for recovering truncated reasoning or tool arguments in one retry.
OPENAI_TRUNCATED_OUTPUT_RETRY_MAX_TOKENS = 32768
OPENAI_VISIBLE_REPLY_RETRY_HINT = (
    "Return at least one visible user-facing coaching sentence outside any <think>...</think> block. "
    "Do not leave the visible reply empty."
)


# ---------------------------------------------------------------------------
# Protocol normalisation
# ---------------------------------------------------------------------------


class _StreamWhitespaceTrimmer:
    """Strip leading whitespace only prior to the first visible streamed token."""

    __slots__ = ("emitted_visible",)

    def __init__(self) -> None:
        self.emitted_visible = False

    def push(self, text: str) -> str:
        if self.emitted_visible:
            return text
        trimmed = text.lstrip()
        if not trimmed:
            return ""
        self.emitted_visible = True
        return trimmed


def _usage_payload(raw: Any) -> dict[str, Any] | None:
    """Extract canonical provider token/cost usage for agent loop accounting."""
    usage = extract_provider_usage(raw)
    if usage is None:
        return None
    return {
        "input_tokens": usage.estimated_input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "total_tokens": usage.total_tokens,
        "total_cost": usage.total_cost,
    }


def resolve_agent_protocol(raw: str | None, *, base_url: str | None = None) -> str:
    """Map the configured provider protocol/name to one the agent loop knows.

    ``raw`` may be a real protocol id (``anthropic_messages``) or a provider
    display name (``Anthropic``, ``claude``). When that is ambiguous we also
    sniff ``base_url`` so a user who only filled in ``https://api.anthropic.com``
    still lands on the native Messages path (which carries vision blocks).
    """
    value = (raw or "").strip().lower()
    if value in {
        "openai_chat_completions",
        "openai_chat_completions_compatible",
        "openai_compatible",
        "openai",
        "",
    }:
        if _url_is_anthropic(base_url):
            return "anthropic_messages"
        return "openai_chat_completions"
    if value in {"openai_responses", "responses"}:
        return "openai_responses"
    if value in {"anthropic_messages", "anthropic", "claude"}:
        return "anthropic_messages"
    if value in {"gemini_generate_content", "gemini", "google"}:
        if (
            isinstance(base_url, str)
            and base_url.strip()
            and not _url_is_google_gemini_native(base_url)
        ):
            return "openai_chat_completions"
        return "gemini_generate_content"
    if _url_is_anthropic(base_url):
        return "anthropic_messages"
    return "openai_chat_completions"


def _url_is_anthropic(base_url: str | None) -> bool:
    if not isinstance(base_url, str):
        return False
    lowered = base_url.strip().lower()
    return "anthropic.com" in lowered


def _url_is_google_gemini_native(base_url: str | None) -> bool:
    if not isinstance(base_url, str):
        return False
    return "googleapis.com" in base_url.strip().lower()


def _base_url_is_official_anthropic(base_url: str | None) -> bool:
    return _url_is_anthropic(base_url)


def _anthropic_response_indicates_protocol_mismatch(status_code: int, body: str) -> bool:
    """Return whether a native Messages failure points to a gateway mismatch.

    Authentication and permission failures are terminal by default. A 401 or
    403 only opts into the OpenAI-compatible retry when its response explicitly
    identifies an incompatible authentication header or scheme.
    """
    if status_code in ANTHROPIC_PROTOCOL_MISMATCH_STATUS_CODES:
        return True
    if status_code not in {401, 403}:
        return False

    normalized_body = " ".join(body.lower().split())
    has_header_evidence = any(marker in normalized_body for marker in ANTHROPIC_AUTH_HEADER_MARKERS)
    has_mismatch_evidence = any(
        marker in normalized_body for marker in ANTHROPIC_AUTH_MISMATCH_MARKERS
    )
    return has_header_evidence and has_mismatch_evidence


def _requested_protocol_is_gemini(raw: str | None) -> bool:
    value = (raw or "").strip().lower()
    return value in {"gemini_generate_content", "gemini", "google"}


def attachments_supported(protocol: str, capability_vision: bool) -> bool:
    if not capability_vision:
        return False
    return protocol in {
        "openai_chat_completions",
        "openai_chat_completions_compatible",
        "anthropic_messages",
        "openai_responses",
        "gemini_generate_content",
    }


# ---------------------------------------------------------------------------
# OpenAI chat completions binding
# ---------------------------------------------------------------------------


def _format_openai_messages(
    messages: list[dict[str, Any]],
    *,
    attachments: list[dict[str, Any]] | None = None,
    vision_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Translate canonical OpenAI-format history to the OpenAI SDK shape.

    The history is *already* in canonical OpenAI format (system / user /
    assistant / tool roles). Two adjustments:

    1. Tool messages must keep ``tool_call_id`` and ``content`` strings.
    2. The latest user message is augmented with image content parts
       when ``vision_enabled`` and ``attachments`` are present.
    """
    formatted: list[dict[str, Any]] = []
    last_user_index = _last_index_with_role(messages, "user")
    image_parts = _openai_image_parts(attachments) if vision_enabled else []
    for index, msg in enumerate(messages):
        role = str(msg.get("role") or "")
        if role == "control":
            formatted.append({"role": "system", "content": str(msg.get("content") or "")})
            continue
        if role == "tool":
            formatted.append(
                {
                    "role": "tool",
                    "tool_call_id": str(msg.get("tool_call_id") or ""),
                    "content": str(msg.get("content") or ""),
                }
            )
            continue
        if role == "assistant" and msg.get("tool_calls"):
            assistant_entry: dict[str, Any] = {
                "role": "assistant",
                "content": str(msg.get("content") or ""),
                "tool_calls": list(msg.get("tool_calls") or []),
            }
            provider_reasoning = msg.get("_provider_reasoning")
            reasoning_content = (
                provider_reasoning.get("openai_reasoning_content")
                if isinstance(provider_reasoning, dict)
                else msg.get("reasoning_content")
            )
            if isinstance(reasoning_content, str) and reasoning_content:
                assistant_entry["reasoning_content"] = reasoning_content
            formatted.append(assistant_entry)
            continue
        if role == "user" and image_parts and index == last_user_index:
            text_value = str(msg.get("content") or "")
            content_parts: list[dict[str, Any]] = []
            if text_value:
                content_parts.append({"type": "text", "text": text_value})
            content_parts.extend(image_parts)
            formatted.append({"role": "user", "content": content_parts})
            continue
        formatted.append({"role": role, "content": str(msg.get("content") or "")})
    return formatted


def _last_index_with_role(messages: list[dict[str, Any]], role: str) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if str(messages[index].get("role") or "") == role:
            return index
    return -1


def _openai_image_parts(
    attachments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not attachments:
        return []
    parts: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "image").lower() != "image":
            continue
        data_base64 = str(item.get("data_base64") or "").strip()
        if not data_base64:
            continue
        mime_type = str(item.get("mime_type") or "image/png").strip() or "image/png"
        url = f"data:{mime_type};base64,{data_base64}"
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts


def _openai_tool_payload(tools: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not tools:
        return {}
    normalized_tools = [
        normalized
        for tool in tools
        if (normalized := _normalize_openai_chat_tool(tool)) is not None
    ]
    if not normalized_tools:
        return {}
    return {"tools": normalized_tools, "tool_choice": "auto"}


def _normalize_openai_chat_tool(tool: Any) -> dict[str, Any] | None:
    if not isinstance(tool, dict):
        return None

    explicit_type = str(tool.get("type") or "").strip().lower()
    if explicit_type not in {"", "function"}:
        return None

    function_block = tool.get("function")
    if isinstance(function_block, dict):
        name = str(function_block.get("name") or tool.get("name") or "").strip()
        if not name:
            return None
        description = function_block.get("description")
        if not isinstance(description, str) or not description.strip():
            description = tool.get("description")
        parameters = function_block.get("parameters")
        if not isinstance(parameters, dict):
            parameters = tool.get("parameters")
        if not isinstance(parameters, dict):
            parameters = tool.get("input_schema")
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": str(description or ""),
                "parameters": parameters
                if isinstance(parameters, dict)
                else {"type": "object", "properties": {}},
            },
        }

    name = str(tool.get("name") or "").strip()
    if not name:
        return None
    description = tool.get("description")
    parameters = tool.get("parameters")
    if not isinstance(parameters, dict):
        parameters = tool.get("input_schema")
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": str(description or ""),
            "parameters": parameters
            if isinstance(parameters, dict)
            else {"type": "object", "properties": {}},
        },
    }


def _extract_openai_tool_calls(message: Any) -> list[dict[str, Any]]:
    raw_calls = _get_field(message, "tool_calls", None)
    if not raw_calls:
        return []
    parsed: list[dict[str, Any]] = []
    for call in raw_calls if isinstance(raw_calls, list) else [raw_calls]:
        function = _get_field(call, "function", None)
        name = (
            _get_field(function, "name", None)
            if function is not None
            else _get_field(call, "name", None)
        )
        arguments = (
            _get_field(function, "arguments", None)
            if function is not None
            else _get_field(call, "arguments", None)
        )
        if not name:
            continue
        parsed.append(
            {
                "id": str(_get_field(call, "id", "") or ""),
                "name": str(name or ""),
                "arguments": arguments,
            }
        )
    return parsed


def _openai_chat_visible_text(message: Any) -> str:
    content = _get_field(message, "content", None)
    if isinstance(content, str):
        return _visible_model_text(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
            text = _get_field(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return _visible_model_text("".join(parts))
    if isinstance(content, dict):
        text = _get_field(content, "text", None)
        if isinstance(text, str):
            return _visible_model_text(text)
    if content is None:
        return ""
    return _visible_model_text(str(content))


def _parse_openai_chat_response(response: Any) -> dict[str, Any]:
    if isinstance(response, str):
        return {"content": _visible_model_text(response), "tool_calls": []}

    choices = _get_field(response, "choices", None)
    choice = None
    if isinstance(choices, list) and choices:
        choice = choices[0]
    elif choices is not None:
        choice = choices

    message = _get_field(choice, "message", None) if choice is not None else None
    if message is None:
        message = choice if choice is not None else response

    content = _openai_chat_visible_text(message)
    tool_calls = _extract_openai_tool_calls(message)
    finish_reason = None
    if choice is not None:
        raw_finish = _get_field(choice, "finish_reason", None)
        if not isinstance(raw_finish, str):
            raw_finish = _get_field(choice, "finishReason", None)
        if isinstance(raw_finish, str) and raw_finish.strip():
            finish_reason = raw_finish.strip()
    parsed: dict[str, Any] = {"content": content, "tool_calls": tool_calls}
    usage_payload = _usage_payload(response)
    if usage_payload is not None:
        parsed["usage"] = usage_payload
    reasoning_content = _get_field(message, "reasoning_content", None)
    if isinstance(reasoning_content, str) and reasoning_content:
        parsed["provider_reasoning"] = {"openai_reasoning_content": reasoning_content}
    if _finish_reason_is_truncated(finish_reason):
        parsed["stop_reason"] = "length"
    elif tool_calls:
        parsed["stop_reason"] = "tool_calls"
    elif finish_reason:
        parsed["stop_reason"] = finish_reason
    return parsed


# ---------------------------------------------------------------------------
# OpenAI Responses binding
# ---------------------------------------------------------------------------


def _get_field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _format_openai_responses_input(
    messages: list[dict[str, Any]],
    *,
    attachments: list[dict[str, Any]] | None = None,
    vision_enabled: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []
    last_user_index = _last_index_with_role(messages, "user")
    image_urls = _openai_responses_image_urls(attachments) if vision_enabled else []
    for index, msg in enumerate(messages):
        role = str(msg.get("role") or "")
        if role == "control":
            text = str(msg.get("content") or "").strip()
            if text:
                input_items.append({"role": "developer", "content": text})
            continue
        if role == "system":
            text = str(msg.get("content") or "").strip()
            if text:
                instructions.append(text)
            continue
        if role == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(msg.get("tool_call_id") or msg.get("name") or ""),
                    "output": str(msg.get("content") or ""),
                }
            )
            continue
        if role == "assistant" and msg.get("tool_calls"):
            provider_reasoning = msg.get("_provider_reasoning")
            if isinstance(provider_reasoning, dict):
                reasoning_items = provider_reasoning.get("responses_reasoning_items")
                if isinstance(reasoning_items, list):
                    for reasoning_item in reasoning_items:
                        if isinstance(reasoning_item, dict):
                            input_items.append(dict(reasoning_item))
            text_value = str(msg.get("content") or "").strip()
            if text_value:
                input_items.append({"role": "assistant", "content": text_value})
            for call in msg.get("tool_calls") or []:
                fn = call.get("function") if isinstance(call, dict) else None
                name = (fn or {}).get("name") if isinstance(fn, dict) else call.get("name")
                arguments = (
                    (fn or {}).get("arguments") if isinstance(fn, dict) else call.get("arguments")
                )
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": str(call.get("id") or name or ""),
                        "name": str(name or ""),
                        "arguments": _ensure_json_arguments(arguments),
                    }
                )
            continue
        if role in {"user", "assistant"}:
            text_value = str(msg.get("content") or "")
            if role == "user" and index == last_user_index and image_urls:
                image_item = openai_responses_input_image_parts(
                    prompt=text_value,
                    image_url=image_urls[0],
                )[0]
                image_item["content"].extend(
                    {"type": "input_image", "image_url": url} for url in image_urls[1:]
                )
                input_items.append(image_item)
            else:
                input_items.append({"role": role, "content": text_value})
    return "\n\n".join(instructions), input_items


def _openai_responses_image_urls(
    attachments: list[dict[str, Any]] | None,
) -> list[str]:
    urls: list[str] = []
    for item in attachments or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "image").strip().lower() != "image":
            continue
        data_base64 = str(item.get("data_base64") or "").strip()
        if not data_base64:
            continue
        mime_type = str(item.get("mime_type") or "image/png").strip() or "image/png"
        urls.append(f"data:{mime_type};base64,{data_base64}")
    return urls


def _ensure_json_arguments(arguments: Any) -> str:
    if arguments is None:
        return "{}"
    if isinstance(arguments, str):
        return arguments.strip() or "{}"
    try:
        return json.dumps(arguments, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps({"_raw_arguments": str(arguments)}, ensure_ascii=False)


def _serialize_responses_reasoning_item(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        return dict(item)
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(exclude_none=True)
            if isinstance(dumped, dict):
                return dumped
        except (AttributeError, TypeError, ValueError) as exc:
            logger.debug("Binding item model_dump fallback triggered: %s", exc)
    item_id = _get_field(item, "id", None)
    summary = _get_field(item, "summary", None)
    encrypted = _get_field(item, "encrypted_content", None)
    if not any((item_id, summary, encrypted)):
        return None
    record: dict[str, Any] = {"type": "reasoning"}
    if item_id:
        record["id"] = str(item_id)
    if summary is not None:
        record["summary"] = summary
    if encrypted is not None:
        record["encrypted_content"] = encrypted
    return record


def _parse_openai_responses_response(response: Any) -> dict[str, Any]:
    direct_text = _get_field(response, "output_text", None)
    text_parts: list[str] = [str(direct_text)] if isinstance(direct_text, str) else []
    tool_calls: list[dict[str, Any]] = []
    reasoning_items: list[dict[str, Any]] = []
    output_items = _get_field(response, "output", None) or []
    for item in output_items:
        item_type = str(_get_field(item, "type", "") or "")
        if item_type == "reasoning":
            serialized = _serialize_responses_reasoning_item(item)
            if serialized:
                reasoning_items.append(serialized)
            continue
        if item_type == "message":
            for content_item in _get_field(item, "content", None) or []:
                content_type = str(_get_field(content_item, "type", "") or "")
                if content_type in {"output_text", "text"}:
                    text_parts.append(str(_get_field(content_item, "text", "") or ""))
            continue
        if item_type in {"function_call", "tool_call"}:
            name = str(_get_field(item, "name", "") or "")
            if not name:
                continue
            call_id = str(_get_field(item, "call_id", None) or _get_field(item, "id", None) or name)
            tool_calls.append(
                {
                    "id": call_id,
                    "name": name,
                    "arguments": _get_field(item, "arguments", None) or "{}",
                }
            )
    parsed: dict[str, Any] = {
        "content": _visible_model_text("".join(text_parts)),
        "tool_calls": tool_calls,
    }
    usage_payload = _usage_payload(response)
    if usage_payload is not None:
        parsed["usage"] = usage_payload
    if reasoning_items:
        parsed["provider_reasoning"] = {"responses_reasoning_items": reasoning_items}
    status = str(_get_field(response, "status", "") or "").strip().lower()
    if status == "incomplete" and not tool_calls:
        parsed["stop_reason"] = "length"
    return parsed


# ---------------------------------------------------------------------------
# Gemini GenerateContent binding
# ---------------------------------------------------------------------------


def _format_gemini_payload(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    attachments: list[dict[str, Any]] | None = None,
    vision_enabled: bool = False,
) -> dict[str, Any]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    last_user_index = _last_index_with_role(messages, "user")
    image_parts = _gemini_image_parts(attachments) if vision_enabled else []
    for index, msg in enumerate(messages):
        role = str(msg.get("role") or "")
        if role == "control":
            text = str(msg.get("content") or "").strip()
            if text:
                contents.append({"role": "user", "parts": [{"text": text}]})
            continue
        if role == "system":
            text = str(msg.get("content") or "").strip()
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            fn_part = {
                "functionResponse": {
                    "name": str(msg.get("name") or msg.get("tool_call_id") or ""),
                    "response": {"content": str(msg.get("content") or "")},
                }
            }
            if contents and contents[-1].get("role") == "function" and isinstance(contents[-1].get("parts"), list):
                contents[-1]["parts"].append(fn_part)
            else:
                contents.append({"role": "function", "parts": [fn_part]})
            continue
        if role == "assistant":
            parts: list[dict[str, Any]] = []
            provider_reasoning = msg.get("_provider_reasoning")
            gemini_signatures = (
                provider_reasoning.get("gemini_thought_signatures")
                if isinstance(provider_reasoning, dict)
                else None
            )
            text_value = str(msg.get("content") or "").strip()
            if text_value:
                parts.append({"text": text_value})
            for call_idx, call in enumerate(msg.get("tool_calls") or []):
                fn = call.get("function") if isinstance(call, dict) else None
                name = (fn or {}).get("name") if isinstance(fn, dict) else call.get("name")
                arguments = (
                    (fn or {}).get("arguments") if isinstance(fn, dict) else call.get("arguments")
                )
                fc_part: dict[str, Any] = {
                    "functionCall": {
                        "name": str(name or ""),
                        "args": _coerce_to_dict(arguments),
                    }
                }
                if isinstance(gemini_signatures, list) and call_idx < len(gemini_signatures):
                    sig = gemini_signatures[call_idx]
                    if isinstance(sig, str) and sig:
                        fc_part["thoughtSignature"] = sig
                parts.append(fc_part)
            if parts:
                contents.append({"role": "model", "parts": parts})
            continue
        if role == "user":
            parts: list[dict[str, Any]] = [{"text": str(msg.get("content") or "")}]
            if image_parts and index == last_user_index:
                parts.extend(image_parts)
            contents.append({"role": "user", "parts": parts})
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system_parts:
        payload["systemInstruction"] = {
            "parts": [{"text": "\n\n".join(system_parts)}],
        }
    if tools:
        payload["tools"] = [{"functionDeclarations": tools}]
    return payload


def _gemini_image_parts(
    attachments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not attachments:
        return []
    parts: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "image").strip().lower() != "image":
            continue
        data_base64 = str(item.get("data_base64") or "").strip()
        if not data_base64:
            continue
        mime_type = str(item.get("mime_type") or "image/png").strip() or "image/png"
        parts.append({"inlineData": {"mimeType": mime_type, "data": data_base64}})
    return parts


def _parse_gemini_response(payload: dict[str, Any]) -> dict[str, Any]:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    thought_signatures: list[str | None] = []
    finish_reason: str | None = None
    candidates = payload.get("candidates") or []
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
                continue
            if isinstance(part.get("text"), str):
                text_parts.append(part["text"])
                continue
            function_call = part.get("functionCall") or part.get("function_call")
            if isinstance(function_call, dict):
                name = str(function_call.get("name") or "")
                if not name:
                    continue
                sig = part.get("thoughtSignature") or part.get("thought_signature")
                thought_signatures.append(str(sig) if isinstance(sig, str) and sig else None)
                tool_calls.append(
                    {
                        "id": name,
                        "name": name,
                        "arguments": function_call.get("args") or {},
                    }
                )
    parsed: dict[str, Any] = {
        "content": _visible_model_text("".join(text_parts)),
        "tool_calls": tool_calls,
    }
    usage_payload = _usage_payload(payload)
    if usage_payload is not None:
        parsed["usage"] = usage_payload
    if any(thought_signatures):
        parsed["provider_reasoning"] = {"gemini_thought_signatures": thought_signatures}
    if _finish_reason_is_truncated(finish_reason) and not tool_calls:
        parsed["stop_reason"] = "length"
    return parsed


# ---------------------------------------------------------------------------
# Anthropic Messages binding
# ---------------------------------------------------------------------------


def _apply_anthropic_history_cache_breakpoint(
    anthropic_messages: list[dict[str, Any]],
) -> None:
    """Mark the last stable history message before the latest user turn for prompt caching."""
    if len(anthropic_messages) < 2:
        return
    target_message = anthropic_messages[-2]
    content = target_message.get("content")
    if not isinstance(content, list):
        return
    for block in reversed(content):
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "") in {"text", "tool_result", "tool_use", "image"}:
            block["cache_control"] = {"type": "ephemeral"}
            return


def _format_anthropic_payload(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    model: str,
    max_tokens: int = ANTHROPIC_DEFAULT_MAX_TOKENS,
    attachments: list[dict[str, Any]] | None = None,
    vision_enabled: bool = False,
    stream: bool = False,
) -> dict[str, Any]:
    system_text, anthropic_messages = _split_anthropic_messages(
        messages,
        attachments=attachments,
        vision_enabled=vision_enabled,
    )
    _apply_anthropic_history_cache_breakpoint(anthropic_messages)
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": anthropic_messages,
    }
    if system_text:
        payload["system"] = [
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    if tools:
        payload["tools"] = tools
    if stream:
        payload["stream"] = True
    return payload


def _split_anthropic_messages(
    messages: list[dict[str, Any]],
    *,
    attachments: list[dict[str, Any]] | None,
    vision_enabled: bool,
) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    last_user_index = _last_index_with_role(messages, "user")
    image_blocks = _anthropic_image_blocks(attachments) if vision_enabled else []
    pending_tool_uses: list[dict[str, Any]] = []
    for index, msg in enumerate(messages):
        role = str(msg.get("role") or "")
        if role == "control":
            ctrl_text = str(msg.get("content") or "").strip()
            if ctrl_text:
                converted.append({"role": "user", "content": [{"type": "text", "text": ctrl_text}]})
            continue
        if role == "system":
            system_parts.append(str(msg.get("content") or ""))
            continue
        if role == "tool":
            tool_use_id = str(msg.get("tool_call_id") or msg.get("name") or "")
            content_text = str(msg.get("content") or "")
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content_text,
            }
            if (
                converted
                and converted[-1].get("role") == "user"
                and isinstance(converted[-1].get("content"), list)
                and converted[-1]["content"]
                and isinstance(converted[-1]["content"][0], dict)
                and converted[-1]["content"][0].get("type") == "tool_result"
            ):
                converted[-1]["content"].append(tool_result_block)
            else:
                converted.append({"role": "user", "content": [tool_result_block]})
            continue
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            provider_reasoning = msg.get("_provider_reasoning")
            if isinstance(provider_reasoning, dict):
                thinking_blocks = provider_reasoning.get("anthropic_blocks")
                if isinstance(thinking_blocks, list):
                    for tb in thinking_blocks:
                        if isinstance(tb, dict) and tb.get("type") in {"thinking", "redacted_thinking"}:
                            blocks.append(dict(tb))
            text_value = str(msg.get("content") or "").strip()
            if text_value:
                blocks.append({"type": "text", "text": text_value})
            for call in msg.get("tool_calls") or []:
                fn = call.get("function") if isinstance(call, dict) else None
                name = (fn or {}).get("name") if isinstance(fn, dict) else call.get("name")
                arguments = (
                    (fn or {}).get("arguments") if isinstance(fn, dict) else call.get("arguments")
                )
                parsed_args = _coerce_to_dict(arguments)
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(call.get("id") or name or ""),
                        "name": str(name or ""),
                        "input": parsed_args,
                    }
                )
                pending_tool_uses.append(call)
            if not blocks:
                continue
            if converted and converted[-1].get("role") == "assistant" and isinstance(converted[-1].get("content"), list):
                converted[-1]["content"].extend(blocks)
            else:
                converted.append({"role": "assistant", "content": blocks})
            continue
        if role == "user":
            user_blocks: list[dict[str, Any]] = []
            text_value = str(msg.get("content") or "")
            if text_value:
                user_blocks.append({"type": "text", "text": text_value})
            if image_blocks and index == last_user_index:
                user_blocks.extend(image_blocks)
            if not user_blocks:
                continue
            if (
                converted
                and converted[-1].get("role") == "user"
                and isinstance(converted[-1].get("content"), list)
                and converted[-1]["content"]
                and isinstance(converted[-1]["content"][0], dict)
                and converted[-1]["content"][0].get("type") == "tool_result"
            ):
                converted[-1]["content"].extend(user_blocks)
            else:
                converted.append({"role": "user", "content": user_blocks})
            continue
    return "\n\n".join(part for part in system_parts if part), converted


def _anthropic_image_blocks(
    attachments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not attachments:
        return []
    blocks: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "image").lower() != "image":
            continue
        data_base64 = str(item.get("data_base64") or "").strip()
        if not data_base64:
            continue
        mime_type = str(item.get("mime_type") or "image/png").strip() or "image/png"
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": data_base64,
                },
            }
        )
    return blocks


def _coerce_to_dict(arguments: Any) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"_raw_arguments": text}
        return parsed if isinstance(parsed, dict) else {"_raw_arguments": parsed}
    return {"_raw_arguments": arguments}


def _parse_anthropic_response(payload: dict[str, Any]) -> dict[str, Any]:
    content_blocks = payload.get("content") or []
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    thinking_blocks: list[dict[str, Any]] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        if block_type == "thinking":
            thinking_block: dict[str, Any] = {
                "type": "thinking",
                "thinking": str(block.get("thinking") or ""),
            }
            if isinstance(block.get("signature"), str) and block["signature"]:
                thinking_block["signature"] = block["signature"]
            thinking_blocks.append(thinking_block)
        elif block_type == "redacted_thinking":
            redacted: dict[str, Any] = {"type": "redacted_thinking"}
            if isinstance(block.get("data"), str):
                redacted["data"] = block["data"]
            thinking_blocks.append(redacted)
        elif block_type == "text":
            text_parts.append(str(block.get("text") or ""))
        elif block_type == "tool_use":
            tool_calls.append(
                {
                    "id": str(block.get("id") or block.get("name") or ""),
                    "name": str(block.get("name") or ""),
                    "arguments": block.get("input") or {},
                }
            )
    parsed: dict[str, Any] = {"content": "".join(text_parts), "tool_calls": tool_calls}
    usage_payload = _usage_payload(payload)
    if usage_payload is not None:
        parsed["usage"] = usage_payload
    if thinking_blocks:
        parsed["provider_reasoning"] = {"anthropic_blocks": thinking_blocks}
    stop_reason = payload.get("stop_reason")
    if isinstance(stop_reason, str) and _finish_reason_is_truncated(stop_reason) and not tool_calls:
        parsed["stop_reason"] = "length"
    return parsed


def _format_anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return tools


def _anthropic_visible_retry_payload(payload: dict[str, Any]) -> dict[str, Any]:
    retry_payload = dict(payload)
    retry_payload.pop("stream", None)
    raw_system = retry_payload.get("system")
    if isinstance(raw_system, list):
        blocks = [dict(block) if isinstance(block, dict) else block for block in raw_system]
        if any(
            isinstance(block, dict)
            and ANTHROPIC_VISIBLE_REPLY_RETRY_HINT in str(block.get("text") or "")
            for block in blocks
        ):
            retry_payload["system"] = blocks
            return retry_payload
        blocks.append({"type": "text", "text": ANTHROPIC_VISIBLE_REPLY_RETRY_HINT})
        retry_payload["system"] = blocks
        return retry_payload
    system_text = str(raw_system or "").strip()
    if ANTHROPIC_VISIBLE_REPLY_RETRY_HINT in system_text:
        return retry_payload
    retry_payload["system"] = (
        f"{system_text}\n\n{ANTHROPIC_VISIBLE_REPLY_RETRY_HINT}"
        if system_text
        else ANTHROPIC_VISIBLE_REPLY_RETRY_HINT
    )
    return retry_payload


def _openai_visible_retry_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    retry_messages = [dict(message) for message in messages]
    for index in range(len(retry_messages) - 1, -1, -1):
        message = retry_messages[index]
        if str(message.get("role") or "") != "system":
            continue
        content = message.get("content")
        if isinstance(content, str):
            if OPENAI_VISIBLE_REPLY_RETRY_HINT in content:
                return retry_messages
            retry_messages[index] = {
                **message,
                "content": f"{content}\n\n{OPENAI_VISIBLE_REPLY_RETRY_HINT}"
                if content.strip()
                else OPENAI_VISIBLE_REPLY_RETRY_HINT,
            }
            return retry_messages
    return [
        {"role": "system", "content": OPENAI_VISIBLE_REPLY_RETRY_HINT},
        *retry_messages,
    ]


# ---------------------------------------------------------------------------
# Public binder
# ---------------------------------------------------------------------------

