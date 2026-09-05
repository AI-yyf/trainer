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
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx

from .agent_loop import AgentProvider, CoachAgentLoop
from .provider_protocols import (
    _finish_reason_is_truncated,
    assess_provider_error,
    safe_provider_diagnostic,
)
from .provider_service import (
    ProviderRuntimeResponseError,
    _flatten_minimax_thinking_for_raw_http,
    _looks_like_provider_html_shell,
    _malformed_provider_html_shell_detail,
    _ReasoningBlockFilter,
    _require_provider_runtime_response,
    _visible_model_text,
)
from .tools import ToolDefinition, ToolRegistry
from .vision_payload import openai_responses_input_image_parts

logger = logging.getLogger("trainer.llm.agent_binding")

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
OPENAI_VISIBLE_REPLY_RETRY_HINT = (
    "Return at least one visible user-facing coaching sentence outside any <think>...</think> block. "
    "Do not leave the visible reply empty."
)


# ---------------------------------------------------------------------------
# Protocol normalisation
# ---------------------------------------------------------------------------


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
            formatted.append(
                {
                    "role": "assistant",
                    "content": str(msg.get("content") or ""),
                    "tool_calls": list(msg.get("tool_calls") or []),
                }
            )
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


def _parse_openai_responses_response(response: Any) -> dict[str, Any]:
    direct_text = _get_field(response, "output_text", None)
    text_parts: list[str] = [str(direct_text)] if isinstance(direct_text, str) else []
    tool_calls: list[dict[str, Any]] = []
    output_items = _get_field(response, "output", None) or []
    for item in output_items:
        item_type = str(_get_field(item, "type", "") or "")
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
    return {"content": _visible_model_text("".join(text_parts)), "tool_calls": tool_calls}


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
        if role == "system":
            text = str(msg.get("content") or "").strip()
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            contents.append(
                {
                    "role": "function",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": str(msg.get("name") or msg.get("tool_call_id") or ""),
                                "response": {"content": str(msg.get("content") or "")},
                            }
                        }
                    ],
                }
            )
            continue
        if role == "assistant":
            parts: list[dict[str, Any]] = []
            text_value = str(msg.get("content") or "").strip()
            if text_value:
                parts.append({"text": text_value})
            for call in msg.get("tool_calls") or []:
                fn = call.get("function") if isinstance(call, dict) else None
                name = (fn or {}).get("name") if isinstance(fn, dict) else call.get("name")
                arguments = (
                    (fn or {}).get("arguments") if isinstance(fn, dict) else call.get("arguments")
                )
                parts.append(
                    {
                        "functionCall": {
                            "name": str(name or ""),
                            "args": _coerce_to_dict(arguments),
                        }
                    }
                )
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
    candidates = payload.get("candidates") or []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content") or {}
        parts = content.get("parts") if isinstance(content, dict) else []
        for part in parts or []:
            if not isinstance(part, dict):
                continue
            if isinstance(part.get("text"), str):
                text_parts.append(part["text"])
                continue
            function_call = part.get("functionCall") or part.get("function_call")
            if isinstance(function_call, dict):
                name = str(function_call.get("name") or "")
                if not name:
                    continue
                tool_calls.append(
                    {
                        "id": name,
                        "name": name,
                        "arguments": function_call.get("args") or {},
                    }
                )
    return {"content": _visible_model_text("".join(text_parts)), "tool_calls": tool_calls}


# ---------------------------------------------------------------------------
# Anthropic Messages binding
# ---------------------------------------------------------------------------


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
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": anthropic_messages,
    }
    if system_text:
        payload["system"] = system_text
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
        if role == "system":
            system_parts.append(str(msg.get("content") or ""))
            continue
        if role == "tool":
            tool_use_id = str(msg.get("tool_call_id") or msg.get("name") or "")
            content_text = str(msg.get("content") or "")
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": content_text,
                        }
                    ],
                }
            )
            continue
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
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
                blocks.append({"type": "text", "text": ""})
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
                user_blocks.append({"type": "text", "text": ""})
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
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        if block_type == "text":
            text_parts.append(str(block.get("text") or ""))
        elif block_type == "tool_use":
            tool_calls.append(
                {
                    "id": str(block.get("id") or block.get("name") or ""),
                    "name": str(block.get("name") or ""),
                    "arguments": block.get("input") or {},
                }
            )
    return {"content": "".join(text_parts), "tool_calls": tool_calls}


def _format_anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return tools


def _anthropic_visible_retry_payload(payload: dict[str, Any]) -> dict[str, Any]:
    retry_payload = dict(payload)
    retry_payload.pop("stream", None)
    system_text = str(retry_payload.get("system") or "").strip()
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


class ProviderAgentBinding:
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
    ) -> None:
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
        detail = (
            assessment.diagnostic
            if assessment.category == "protocol_mismatch"
            else f"Provider request failed (HTTP {status_code})."
        )
        return ProviderRuntimeResponseError(
            category=assessment.category,
            detail=detail,
            retryable=assessment.retryable,
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
            try:
                response = await client.responses.create(model=candidate, **kwargs)
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
        stream = None
        for candidate in self._provider_service._model_candidates(model):  # noqa: SLF001
            try:
                stream = client.responses.stream(model=candidate, **kwargs)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not self._provider_service._is_model_not_supported_error(exc):  # noqa: SLF001
                    raise
                continue
        if stream is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError(f"Unable to resolve a usable OpenAI Responses model for {model!r}.")

        text_buffer = ""
        reasoning_filter = _ReasoningBlockFilter()
        emitted_visible = False

        def _normalize_stream_chunk(text: str) -> str:
            nonlocal emitted_visible
            if emitted_visible:
                return text
            trimmed = text.lstrip()
            if not trimmed:
                return ""
            emitted_visible = True
            return trimmed

        tool_call_state: dict[int, dict[str, Any]] = {}
        async with stream as response_stream:
            async for event in response_stream:
                event_type = str(getattr(event, "type", "") or "")
                if event_type in {"response.output_item.added", "response.output_item.done"}:
                    item = getattr(event, "item", None)
                    if item is None or str(getattr(item, "type", "") or "") != "function_call":
                        continue
                    index = int(getattr(event, "output_index", 0) or 0)
                    slot = tool_call_state.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    call_id = getattr(item, "call_id", None) or getattr(item, "id", None)
                    if call_id:
                        slot["id"] = str(call_id)
                    name = getattr(item, "name", None)
                    if name:
                        slot["name"] = str(name)
                    arguments = getattr(item, "arguments", None)
                    if isinstance(arguments, str):
                        slot["arguments"] = arguments
                    elif arguments is not None:
                        slot["arguments"] = _ensure_json_arguments(arguments)
                    continue
                if event_type == "response.output_text.delta":
                    piece = str(getattr(event, "delta", "") or "")
                    if piece:
                        visible_piece = _normalize_stream_chunk(reasoning_filter.push(piece))
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

        tail = _normalize_stream_chunk(reasoning_filter.flush())
        if tail:
            text_buffer += tail
            yield {"type": "delta", "delta": tail}

        tool_calls = [
            {"id": item["id"] or item["name"], "name": item["name"], "arguments": item["arguments"]}
            for _, item in sorted(tool_call_state.items())
            if item["name"]
        ]
        normalized = self._validated_result(
            final_response,
            {"content": _visible_model_text(text_buffer), "tool_calls": tool_calls},
            protocol="openai_responses",
        )
        yield {
            "type": "final",
            "content": normalized["content"],
            "tool_calls": tool_calls,
            "stop_reason": "tool_calls" if tool_calls else "stop",
        }

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
        async with httpx.AsyncClient(timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                endpoint,
                json=payload,
                headers={
                    "x-goog-api-key": api_key,
                    "content-type": "application/json",
                },
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
        async with httpx.AsyncClient(timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS) as client:
            async with client.stream(
                "POST",
                endpoint,
                json=payload,
                headers={
                    "x-goog-api-key": api_key,
                    "content-type": "application/json",
                },
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise self._http_failure(
                        status_code=response.status_code,
                        body=body.decode("utf-8", errors="replace"),
                    )
                text_buffer = ""
                reasoning_filter = _ReasoningBlockFilter()
                emitted_visible = False

                def _normalize_stream_chunk(text: str) -> str:
                    nonlocal emitted_visible
                    if emitted_visible:
                        return text
                    trimmed = text.lstrip()
                    if not trimmed:
                        return ""
                    emitted_visible = True
                    return trimmed

                tool_call_state: dict[tuple[int, int], dict[str, Any]] = {}
                async for raw_line in response.aiter_lines():
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
                    candidates = event.get("candidates") or []
                    for candidate_index, candidate in enumerate(candidates):
                        if not isinstance(candidate, dict):
                            continue
                        content = candidate.get("content") or {}
                        parts = content.get("parts") if isinstance(content, dict) else []
                        for part_index, part in enumerate(parts or []):
                            if not isinstance(part, dict):
                                continue
                            piece = part.get("text")
                            if isinstance(piece, str) and piece:
                                visible_piece = _normalize_stream_chunk(reasoning_filter.push(piece))
                                if visible_piece:
                                    text_buffer += visible_piece
                                    yield {"type": "delta", "delta": visible_piece}
                            function_call = part.get("functionCall") or part.get("function_call")
                            if not isinstance(function_call, dict):
                                continue
                            name = str(function_call.get("name") or "")
                            if not name:
                                continue
                            slot = tool_call_state.setdefault(
                                (candidate_index, part_index),
                                {"id": "", "name": "", "arguments": None},
                            )
                            slot["name"] = name
                            slot["id"] = slot["id"] or name
                            args = function_call.get("args")
                            if args is None:
                                args = function_call.get("arguments")
                            if isinstance(args, dict):
                                existing_args = slot.get("arguments")
                                slot["arguments"] = (
                                    self._merge_record(existing_args, args)
                                    if isinstance(existing_args, dict)
                                    else dict(args)
                                )
                            elif args is not None:
                                slot["arguments"] = str(args)
                tail = _normalize_stream_chunk(reasoning_filter.flush())
                if tail:
                    text_buffer += tail
                    yield {"type": "delta", "delta": tail}

        tool_calls = [
            {
                "id": item["id"] or item["name"],
                "name": item["name"],
                "arguments": item["arguments"] if item["arguments"] is not None else {},
            }
            for _, item in sorted(tool_call_state.items())
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
                    }
                }
            ]
        }
        normalized = self._validated_result(
            final_payload,
            {"content": _visible_model_text(text_buffer), "tool_calls": tool_calls},
            protocol="gemini_generate_content",
        )
        yield {
            "type": "final",
            "content": normalized["content"],
            "tool_calls": tool_calls,
            "stop_reason": "tool_calls" if tool_calls else "stop",
        }

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
                response = await client.chat.completions.create(model=candidate, **kwargs)
            except Exception as exc:  # noqa: BLE001 - normalised below
                last_error = exc
                if not self._provider_service._is_model_not_supported_error(exc):  # noqa: SLF001
                    raise
                continue
            parsed = _parse_openai_chat_response(response)
            if not str(parsed.get("content") or "").strip() and not parsed.get("tool_calls"):
                retry_result = await self._openai_visible_retry_result(
                    client,
                    messages=formatted,
                    tools=tools,
                    model=candidate,
                )
                if retry_result is not None:
                    return retry_result
            return self._validated_result(
                response,
                parsed,
                protocol="openai_chat_completions",
            )
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Unable to resolve a usable OpenAI model for {model!r}.")

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
                stream = await client.chat.completions.create(model=candidate, **kwargs)
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
        reasoning_filter = _ReasoningBlockFilter()
        emitted_visible = False

        def _normalize_stream_chunk(text: str) -> str:
            nonlocal emitted_visible
            if emitted_visible:
                return text
            trimmed = text.lstrip()
            if not trimmed:
                return ""
            emitted_visible = True
            return trimmed

        tool_call_state: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        async for chunk in stream:
            choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
            if choice is None:
                continue
            candidate_finish_reason = getattr(choice, "finish_reason", None)
            if isinstance(candidate_finish_reason, str) and candidate_finish_reason.strip():
                finish_reason = candidate_finish_reason
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            piece = getattr(delta, "content", None)
            if isinstance(piece, str) and piece:
                visible_piece = _normalize_stream_chunk(reasoning_filter.push(piece))
                if visible_piece:
                    text_buffer += visible_piece
                    yield {"type": "delta", "delta": visible_piece}
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
                if getattr(fn, "arguments", None):
                    slot["arguments"] += str(fn.arguments)

        tail = _normalize_stream_chunk(reasoning_filter.flush())
        if tail:
            text_buffer += tail
            yield {"type": "delta", "delta": tail}

        tool_calls = [
            {"id": item["id"] or item["name"], "name": item["name"], "arguments": item["arguments"]}
            for item in tool_call_state.values()
            if item["name"]
        ]
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
        yield {
            "type": "final",
            "content": normalized["content"],
            "tool_calls": tool_calls,
            "stop_reason": "tool_calls" if tool_calls else "stop",
        }

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
        async with httpx.AsyncClient(timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS) as client:
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
                reasoning_filter = _ReasoningBlockFilter()
                emitted_visible = False

                def _normalize_stream_chunk(text: str) -> str:
                    nonlocal emitted_visible
                    if emitted_visible:
                        return text
                    trimmed = text.lstrip()
                    if not trimmed:
                        return ""
                    emitted_visible = True
                    return trimmed

                tool_block_states: dict[int, dict[str, Any]] = {}
                stop_reason: str | None = None
                async for raw_line in response.aiter_lines():
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
                    if event_type == "content_block_start":
                        block = event.get("content_block") or {}
                        if str(block.get("type") or "") == "tool_use":
                            tool_block_states[int(event.get("index") or 0)] = {
                                "id": str(block.get("id") or ""),
                                "name": str(block.get("name") or ""),
                                "arguments": "",
                            }
                    elif event_type == "content_block_delta":
                        delta = event.get("delta") or {}
                        delta_kind = str(delta.get("type") or "")
                        if delta_kind == "text_delta":
                            piece = str(delta.get("text") or "")
                            if piece:
                                visible_piece = _normalize_stream_chunk(
                                    reasoning_filter.push(piece)
                                )
                                if visible_piece:
                                    text_buffer += visible_piece
                                    yield {"type": "delta", "delta": visible_piece}
                        elif delta_kind == "input_json_delta":
                            slot = tool_block_states.setdefault(
                                int(event.get("index") or 0),
                                {"id": "", "name": "", "arguments": ""},
                            )
                            slot["arguments"] += str(delta.get("partial_json") or "")
                    elif event_type == "message_delta":
                        delta = event.get("delta") or {}
                        candidate_stop_reason = delta.get("stop_reason")
                        if isinstance(candidate_stop_reason, str) and candidate_stop_reason.strip():
                            stop_reason = candidate_stop_reason
                    elif event_type == "message_stop":
                        break
                tail = _normalize_stream_chunk(reasoning_filter.flush())
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
        yield {
            "type": "final",
            "content": normalized["content"],
            "tool_calls": tool_calls,
            "stop_reason": "tool_calls" if tool_calls else "stop",
        }

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
    ) -> httpx.Response:
        payload = self._flatten_raw_http_thinking(payload)
        async with httpx.AsyncClient(timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS) as client:
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
        if (
            not self._should_default_compatibility_thinking()
            or "thinking" in payload
            or (isinstance(configured_extra_body, dict) and "thinking" in configured_extra_body)
            or (isinstance(explicit_thinking_budget, int) and explicit_thinking_budget > 0)
        ):
            return payload
        return {**payload, "thinking": {"type": "disabled"}}

    def _apply_compatibility_thinking_disabled(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        existing_extra_body = payload.get("extra_body")
        configured_extra_body = self._request_defaults().get("extra_body")
        if (
            not self._should_default_compatibility_thinking()
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

    def _anthropic_credentials(self) -> tuple[str, str]:
        api_key = getattr(self._provider_service, "_api_key", None)
        if not isinstance(api_key, str) or not api_key.strip():
            raise RuntimeError("Anthropic provider requires an API key.")
        config = getattr(self._provider_service, "_config", None)
        model = getattr(config, "model", None) or "claude-3-5-sonnet-latest"
        return api_key.strip(), str(model).strip()

    def _anthropic_headers(self, api_key: str) -> dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
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
                merged[key] = ProviderAgentBinding._merge_record(current, value)
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
        if not defaults:
            return payload
        merged = dict(payload)
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
        reasoning_effort = self._usable_default(
            self._first_default(defaults, "reasoning_effort", "reasoningEffort")
        )
        if isinstance(reasoning_effort, str):
            existing_reasoning = merged.get("reasoning")
            existing = dict(existing_reasoning) if isinstance(existing_reasoning, dict) else {}
            merged["reasoning"] = {**existing, "effort": reasoning_effort.strip()}
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
        thinking_budget = self._first_default(defaults, "thinking_budget", "thinkingBudget")
        explicit_wire_thinking = isinstance(defaults.get("thinking"), dict) or (
            isinstance(defaults.get("extra_body"), dict)
            and isinstance(defaults["extra_body"].get("thinking"), dict)
        )
        if not explicit_wire_thinking and isinstance(thinking_budget, int) and thinking_budget > 0:
            merged["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        elif not explicit_wire_thinking and isinstance(thinking_budget, str) and thinking_budget.strip().lower() == "disabled":
            merged.pop("thinking", None)
        return self._flatten_raw_http_thinking(merged)

    def _apply_gemini_request_defaults(self, payload: dict[str, Any]) -> dict[str, Any]:
        defaults = self._request_defaults()
        if not defaults:
            return payload
        merged = dict(payload)
        if isinstance(defaults.get("extra_body"), dict):
            merged = self._merge_record(merged, defaults["extra_body"])
        merged = self._flatten_raw_http_thinking(merged)
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
        return self._flatten_raw_http_thinking(merged)

    def _gemini_credentials(self) -> tuple[str, str]:
        api_key = getattr(self._provider_service, "_api_key", None)
        if not isinstance(api_key, str) or not api_key.strip():
            raise RuntimeError("Gemini GenerateContent provider requires an API key.")
        config = getattr(self._provider_service, "_config", None)
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
            if stripped.endswith("/v1"):
                stripped = stripped[: -len("/v1")]
            return stripped
        return None


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
) -> tuple[AgentProvider, ProviderAgentBinding]:
    binding = ProviderAgentBinding(
        provider_service=provider_service,
        protocol=protocol,
        attachments=attachments,
        temperature=temperature,
        max_tokens=max_tokens,
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
